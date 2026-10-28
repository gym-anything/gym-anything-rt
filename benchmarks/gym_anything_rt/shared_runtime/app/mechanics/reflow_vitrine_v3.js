(() => {
  'use strict';
  let model, frame = 0;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    const raw = ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
    return (raw < 0 ? -1 : 1) * (.28 + .72 * Math.abs(raw));
  }
  function wind(i, ms) {
    const w = model.state.world, u = ms / w.parameters.gust_span_ms;
    const n = Math.floor(u), f = u - n;
    const a = noise(w.gust_seeds[i], n), b = noise(w.gust_seeds[i], n + 1);
    return a + (b - a) * f * f * (3 - 2 * f);
  }
  function pixels(p) {
    const s = model.state.world.stage, a = s.x + s.w * p[0];
    return [a, s.y + s.h * p[1], s.y + s.h * p[2], a + s.w * (1 - p[0]) * p[3]];
  }
  function errors() { return pixels(model.p).map((x, i) => Math.abs(x - model.targets[i])); }
  function badge(i, live) {
    const s=model.state.world.stage;
    return i===0?[live[0],s.y+18]:i===1?[s.x+s.w-20,live[1]]:i===2?[s.x+18,live[2]]:[live[3],s.y+18];
  }
  function directions(i) {
    const forward=i===0||i===3?['LEFT','RIGHT']:['UP','DOWN'];
    return model.state.world.linkages[i].sign===1?forward:forward.slice().reverse();
  }
  function summary() {
    return {t_ms:model.ms, positions:model.p.slice(), velocities:model.v.slice(),
      trims:model.trim.slice(), blur_ms:model.blurMs, terminal:model.outcome};
  }
  function event(kind, seam, u, source) {
    model.events.push({sequence:model.events.length + 1, t_ms:model.ms, kind,
      ...(seam === null ? {} : {seam, u}), input_source:source});
  }
  async function submit() {
    if (model.submitted) return;
    model.submitted = true;
    const m = model;
    const payload = {mechanic_id:m.state.mechanic_id, task_id:m.state.task_id,
      challenge_id:m.state.challenge_id, interaction_mode:m.interaction, events:m.events,
      final_t_ms:m.ms, completed:m.outcome === 'pass', summary:summary()};
    m.payload = payload;
    // Premature certification ends the episode visibly. Preserve its incomplete
    // physical summary in the rejected payload; do not invent a physics failure.
    if (!m.outcome) { m.endedEarly = true; m.outcome = 'fail'; }
    // The commitment ends interaction immediately, including while its grade
    // is pending. Keep the terminal affordances consistent with input guards.
    m.helpers.setReadout('VERIFYING · Inspection ended; controls locked.','pending');
    draw();
    try {
      const response = await fetch('/result', {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      m.result = await response.json();
      m.helpers.setReadout(m.result.passed ? 'PASS · DISPLAY REGISTERED' : 'FAIL · EPISODE ENDED',m.result.passed ? 'passed' : 'error');
    } catch (error) {
      m.result = {passed:false, error:String(error)};
      m.helpers.setReadout('VERIFIER ERROR', 'error');
    }
    draw();
  }
  function advance() {
    if (!model.started || model.outcome) return;
    const w = model.state.world, p = w.parameters;
    const end = Math.min(w.duration_ms, Math.floor((performance.now() - model.startedAt) / w.tick_ms) * w.tick_ms);
    while (model.ms + w.tick_ms <= end && !model.outcome) {
      model.ms += w.tick_ms;
      const dt = w.tick_ms / 1000;
      for (let i = 0; i < p.seam_count; i++) {
        const desired = (w.motor_speed * w.linkages[i].sign * model.trim[i] + p.wind_speed * wind(i, model.ms)) / model.scale[i];
        model.v[i] += (desired - model.v[i]) * dt / p.inertia_s;
        model.p[i] += model.v[i] * dt;
        if (model.p[i] < w.limits[0] || model.p[i] > w.limits[1]) {
          model.p[i] = clamp(model.p[i], ...w.limits); model.v[i] = 0;
        }
      }
      if (Math.max(...errors().slice(0, p.seam_count)) > p.tolerance_px) model.blurMs += w.tick_ms;
      if (model.ms % 40 === 0) model.trail.push({ms:model.ms, positions:pixels(model.p)});
      while (model.trail.length && model.trail[0].ms < model.ms - w.trail_ms) model.trail.shift();
      if (model.blurMs > w.blur_budget_ms) model.outcome = 'fail';
      else if (model.ms >= w.duration_ms) model.outcome = 'pass';
    }
    if (model.outcome) submit();
  }
  function art(c, kind, box, tone) {
    const [x,y,w,h] = box;
    c.save(); c.beginPath(); c.rect(x+7,y+7,w-14,h-14); c.clip();
    c.translate(x+w/2,y+h*.58);
    const k = Math.min(w/105,h/120); c.scale(k,k);
    c.fillStyle = tone; c.strokeStyle = '#302524'; c.lineWidth = 3;
    if (kind === 'coat') {
      c.beginPath();c.moveTo(-17,-48);c.lineTo(-40,-29);c.lineTo(-26,-13);c.lineTo(-20,-27);c.lineTo(-21,43);c.lineTo(22,43);c.lineTo(20,-27);c.lineTo(28,-14);c.lineTo(41,-29);c.lineTo(17,-48);c.closePath();c.fill();c.stroke();
      c.beginPath();c.moveTo(0,-41);c.lineTo(0,41);c.stroke();
      c.fillStyle='#efcf85';[-20,0,20].forEach(y=>{c.beginPath();c.arc(7,y,2,0,Math.PI*2);c.fill();});
    } else if (kind === 'vase') {
      c.beginPath();c.moveTo(-13,-47);c.bezierCurveTo(-10,-15,-39,-8,-29,28);c.quadraticCurveTo(-22,43,23,38);c.bezierCurveTo(40,21,25,-13,13,-47);c.closePath();c.fill();c.stroke();
      c.strokeStyle='#e9d8b4';[-15,0,15].forEach(y=>{c.beginPath();c.moveTo(-24,y);c.lineTo(25,y);c.stroke();});
    } else if (kind === 'lamp') {
      c.fillStyle='#e5b85e';c.beginPath();c.moveTo(-32,-35);c.lineTo(30,-35);c.lineTo(42,3);c.lineTo(-42,3);c.closePath();c.fill();c.stroke();
      c.beginPath();c.moveTo(0,3);c.lineTo(0,35);c.stroke();c.fillRect(-26,34,52,7);
    } else if (kind === 'shoe') {
      c.beginPath();c.moveTo(-43,0);c.lineTo(-20,-20);c.lineTo(8,-5);c.quadraticCurveTo(38,-1,45,23);c.lineTo(-45,23);c.closePath();c.fill();c.stroke();
      c.strokeStyle='#e6d3af';c.beginPath();c.moveTo(-42,17);c.lineTo(40,17);c.stroke();
    } else {
      const g=c.createRadialGradient(-12,-17,3,0,0,37);g.addColorStop(0,'#f3e8c9');g.addColorStop(.3,tone);g.addColorStop(1,'#385766');c.fillStyle=g;
      c.beginPath();c.arc(0,-5,38,0,Math.PI*2);c.fill();c.stroke();c.fillStyle='#bb8d58';c.fillRect(-26,35,52,6);
    }
    c.restore();
  }
  function boxes(p) {
    const s=model.state.world.stage, [a,b,cc,d]=pixels(p), r=s.x+s.w, bottom=s.y+s.h;
    return [[s.x,s.y,a-s.x,cc-s.y],[s.x,cc,a-s.x,bottom-cc],
      [a,s.y,d-a,b-s.y],[d,s.y,r-d,b-s.y],[a,b,r-a,bottom-b]];
  }
  function draw() {
    if (!model) return;
    const w=model.state.world, count=w.parameters.seam_count, canvas=document.getElementById('rv2-canvas');
    if (!canvas) return;
    const ended=!!model.outcome;
    document.getElementById('rv2-start').disabled=model.started||ended;
    document.getElementById('rv2-submit').disabled=ended;
    const c=canvas.getContext('2d'), s=w.stage, live=pixels(model.p), goal=model.targets;
    c.fillStyle='#efe7d2';c.fillRect(0,0,800,376);
    const hues=['#9b4b4f','#5d8c83','#cb9b59','#5b7799','#c88778'];
    boxes(model.p).forEach((b,i)=>{c.fillStyle=i%2?'#ded2bb':'#e9dfc7';c.fillRect(...b);art(c,w.merchandise[i],b,hues[i]);});
    const lines=point=>[[point[0],s.y,point[0],s.y+s.h],[point[0],point[1],s.x+s.w,point[1]],
      [s.x,point[2],point[0],point[2]],[point[3],s.y,point[3],point[1]]];
    // The translucent bands are the actual accepted seam-coordinate intervals.
    const gl=lines(goal), ll=lines(live);
    for(let i=0;i<count;i++) {
      const [x1,y1,x2,y2]=gl[i], t=w.parameters.tolerance_px;
      c.fillStyle='#5989702c';
      if(x1===x2)c.fillRect(x1-t,y1,2*t,y2-y1);else c.fillRect(x1,y1-t,x2-x1,2*t);
      c.strokeStyle='#52765c';c.lineWidth=1.5;c.setLineDash([5,5]);c.beginPath();c.moveTo(x1,y1);c.lineTo(x2,y2);c.stroke();c.setLineDash([]);
    }
    c.strokeStyle='#634d3c';c.lineWidth=5;c.strokeRect(s.x,s.y,s.w,s.h);
    for(let i=0;i<4;i++) {
      const [x1,y1,x2,y2]=ll[i];c.strokeStyle=i<count?(errors()[i]>w.parameters.tolerance_px?'#b7524f':'#755333'):'#b4a68c';
      c.lineWidth=i<count?5:2;c.beginPath();c.moveTo(x1,y1);c.lineTo(x2,y2);c.stroke();
      if(i>=count)continue;
      const joint=badge(i,live);
      // A bounded 600-ms trail shows the outcome-affecting motion in one frame.
      model.trail.forEach((sample,j)=>{c.globalAlpha=(j+1)/model.trail.length*.5;c.fillStyle='#345f79';
        const p=i===0?[sample.positions[0],joint[1]+16]:i===3?[sample.positions[3],joint[1]+16]:[joint[0]+16,sample.positions[i]];
        c.beginPath();c.arc(...p,2.5,0,Math.PI*2);c.fill();});c.globalAlpha=1;
      c.fillStyle=model.inspected[i]?'#35634f':'#302821';c.beginPath();c.arc(...joint,13,0,Math.PI*2);c.fill();c.fillStyle='#f4e4bf';c.font='bold 13px sans-serif';c.textAlign='center';c.fillText('ABCD'[i],joint[0],joint[1]+5);
    }
    for(let i=0;i<count;i++) {
      const rail=document.querySelector(`[data-rv2-rail="${i}"]`);
      rail.setAttribute('aria-disabled',String(ended));
      rail.querySelector('.rv2-thumb').style.left=`${(model.trim[i]+1)*50}%`;
      const head=rail.parentElement.querySelector('.rv2-control-head b');
      head.textContent=`RAIL ${String(w.linkages[i].rail).padStart(2,'0')} · ${model.inspected[i]?'ABCD'[i]+' / '+['BAY WIDTH','RIGHT SHELF','LEFT SHELF','NESTED WIDTH'][i]:'LINKAGE UNINSPECTED'}`;
      const labels=rail.parentElement.querySelectorAll('.rv2-labels span');
      const [left,right]=directions(i);
      labels[0].textContent=model.inspected[i]?`← ${left}`:'← trim';
      labels[1].textContent=model.inspected[i]?`${right} →`:'trim →';
      rail.parentElement.querySelector('.rv2-wind i').style.transform=`rotate(${wind(i,model.ms)*65}deg)`;
      rail.parentElement.querySelector('.rv2-error').textContent=errors()[i]<=w.parameters.tolerance_px?'IN REGISTER':'DRIFTING';
    }
    const inspector=document.getElementById('rv3-inspector');
    if(model.selected!==null) {
      const i=model.selected, [left,right]=directions(i);
      inspector.innerHTML=`<b>FRAME ${'ABCD'[i]} → RAIL ${String(w.linkages[i].rail).padStart(2,'0')}</b><span>Lever left: ${left} · right: ${right}</span>`;
    }
    document.getElementById('rv2-progress').style.width=`${model.ms/w.duration_ms*100}%`;
    document.getElementById('rv2-blur').style.width=`${Math.min(1,model.blurMs/w.blur_budget_ms)*100}%`;
    document.getElementById('rv2-time').textContent=`${((w.duration_ms-model.ms)/1000).toFixed(1)} s`;
    document.getElementById('rv2-debt').textContent=`${(model.blurMs/1000).toFixed(2)} / ${(w.blur_budget_ms/1000).toFixed(1)} s`;
    if(model.outcome) {
      const verdict=model.result?.passed===false?'fail':model.outcome;
      const reason=model.endedEarly?'INSPECTION ENDED EARLY':verdict==='pass'?'LIGHTING INSPECTION COMPLETE':model.outcome==='pass'?'INSPECTION REJECTED':'REGISTRATION LOST';
      const stamp=document.getElementById('rv2-verdict');stamp.hidden=false;stamp.dataset.outcome=verdict;
      stamp.innerHTML=`<b>${verdict.toUpperCase()}</b><span>${reason}</span>`;
    }
  }
  function animate() { advance();draw();frame=requestAnimationFrame(animate); }
  function render(state, helpers) {
    cancelAnimationFrame(frame);
    const w=state.world,s=w.stage;
    model={state,helpers,interaction:state.control_condition?.interaction||'full',started:false,startedAt:0,
      ms:0,p:w.initial.slice(),v:[0,0,0,0],trim:[0,0,0,0],blurMs:0,outcome:'',events:[],trail:[],drag:null,submitted:false,
      inspected:[false,false,false,false],selected:null};
    model.scale=[s.w,s.h,s.h,s.w*(1-w.target[0])];model.targets=pixels(w.target);
    window.reflowVitrineV3Model=model; // Privileged diagnostic planning only; not an agent action.
    document.body.dataset.mechanic='reflow-vitrine-v3';
    const levers=w.linkages.map((link,i)=>({link,i})).sort((a,b)=>a.link.rail-b.link.rail).map(({i})=>`<div class="rv2-control"><div class="rv2-control-head"><b></b><span class="rv2-wind" title="Current fan pressure"><i></i></span></div><div class="rv2-rail" data-rv2-rail="${i}"><span class="rv2-thumb"></span><em></em></div><div class="rv2-labels"><span></span><span></span></div><small class="rv2-error"></small></div>`).join('');
    helpers.app.innerHTML=`<section class="rv2"><header class="rv2-head"><div><p>ATELIER / KINETIC WINDOW NO. 03</p><h1>Reflow Vitrine V3</h1></div><div class="rv2-badge">LIGHTING<br>INSPECTION</div></header><div class="rv2-instructions">Keep each brass seam inside its green blueprint band for 20 seconds. Fans and inertia keep the layout moving.<br>${model.interaction==='full'?'Drag the brass trim levers':'Click a position on each trim rail'}. Linkages vary: click a lettered seam badge to inspect its rail and drive direction. Needles show fan pressure; blue trails show motion.</div><div class="rv2-main"><div class="rv2-stage"><canvas id="rv2-canvas" width="800" height="376"></canvas><div id="rv2-verdict" hidden></div></div><aside class="rv2-aside"><p>FRAME INSPECTOR</p><div id="rv3-inspector"><b>Select a seam badge.</b><span>Inspection leaves the fans running.<br>Discovered labels stay on the rails.</span></div><div class="rv2-reference"><canvas id="rv2-ref" width="800" height="376"></canvas></div><span>INSPECTION REMAINING</span><b id="rv2-time">20.0 s</b><div class="rv2-meter"><i id="rv2-progress"></i></div><span>TIME OUTSIDE BANDS</span><b id="rv2-debt">0 / 1.8 s</b><div class="rv2-meter rv2-red"><i id="rv2-blur"></i></div><button id="rv2-start">START INSPECTION →</button></aside></div><div class="rv2-controls" style="--count:${w.parameters.seam_count}">${levers}</div><footer><div class="readout">READY · Inspect frames and set trims before START. Failed inspection or certification ends the episode.</div><button id="rv2-submit">CERTIFY DISPLAY</button></footer></section>`;
    // Draw the same merchandise into a fixed reference view. No hidden answers
    // are displayed; the reference geometry is the task's visible gold artifact.
    draw();
    const ref=document.getElementById('rv2-ref').getContext('2d');ref.drawImage(document.getElementById('rv2-canvas'),0,0);
    document.getElementById('rv2-canvas').addEventListener('click',e=>{
      advance();if(model.outcome||model.drag)return;
      const canvas=e.currentTarget,r=canvas.getBoundingClientRect();
      const x=(e.clientX-r.left)*canvas.width/r.width,y=(e.clientY-r.top)*canvas.height/r.height;
      const live=pixels(model.p);
      const i=w.linkages.findIndex((_,i)=>{const [bx,by]=badge(i,live);return Math.hypot(x-bx,y-by)<=13;});
      if(i<0)return;
      model.inspected[i]=true;model.selected=i;
      model.events.push({sequence:model.events.length+1,t_ms:model.ms,kind:'inspect',seam:i,input_source:'seam_inspection'});
      draw();
    });
    for(const rail of document.querySelectorAll('[data-rv2-rail]')) {
      const i=Number(rail.dataset.rv2Rail);
      const u=e=>{const r=rail.getBoundingClientRect();return Math.round(clamp((e.clientX-r.left)/r.width,0,1)*10000)/10000;};
      const move=e=>{advance();if(model.outcome)return;const value=u(e);model.trim[i]=2*value-1;event('trim',i,value,model.interaction==='full'?'lever_drag':'rail_click');draw();};
      rail.addEventListener('click',e=>{if(model.interaction==='simplified')move(e);});
      rail.addEventListener('pointerdown',e=>{
        if(model.interaction!=='full'||e.button!==0||!e.target.classList.contains('rv2-thumb'))return;
        advance();if(model.outcome)return;e.preventDefault();rail.setPointerCapture(e.pointerId);
        model.drag={i,pointerId:e.pointerId};event('grip',i,u(e),'lever_drag');
      });
      rail.addEventListener('pointermove',e=>{if(model.drag?.i===i&&model.drag.pointerId===e.pointerId)move(e);});
      const release=e=>{if(model.drag?.i!==i)return;advance();if(!model.outcome){const value=u(e);model.trim[i]=2*value-1;event('release',i,value,'lever_drag');}model.drag=null;if(rail.hasPointerCapture(e.pointerId))rail.releasePointerCapture(e.pointerId);draw();};
      rail.addEventListener('pointerup',release);rail.addEventListener('pointercancel',release);
      rail.addEventListener('lostpointercapture',()=>{if(model.drag?.i===i){advance();if(!model.outcome)event('release',i,(model.trim[i]+1)/2,'lever_drag');model.drag=null;}});
    }
    document.getElementById('rv2-start').addEventListener('click',()=>{if(model.started||model.outcome)return;model.started=true;model.startedAt=performance.now();event('start',null,null,'inspection_button');document.getElementById('rv2-start').disabled=true;helpers.setReadout('INSPECTION ACTIVE · Keep every seam registered.','pending');});
    document.getElementById('rv2-submit').addEventListener('click',()=>{advance();submit();});
    frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.reflow_vitrine_v3={rootSelector:'.rv2',render};
})();
