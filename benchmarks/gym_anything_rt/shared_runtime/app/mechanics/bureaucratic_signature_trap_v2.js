(() => {
  'use strict';
  let model, frame = 0;
  const esc = x => String(x).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  function spline(knots, t, span) {
    const u = Math.max(0, t) / span, i = Math.min(Math.floor(u), knots.length - 2), f = Math.min(1, u-i);
    const [a,b,c,d] = [knots[Math.max(0,i-1)],knots[i],knots[i+1],knots[Math.min(knots.length-1,i+2)]];
    return [0,1].map(j => .5*(2*b[j]+(-a[j]+c[j])*f+(2*a[j]-5*b[j]+4*c[j]-d[j])*f*f+(-a[j]+3*b[j]-3*c[j]+d[j])*f*f*f));
  }
  function target(w,t) {
    const a=spline(w.knots,t,w.params.knot_ms), b=spline(w.drift_knots,t,w.params.drift_ms);
    return a.map((v,j)=>v+b[j]);
  }
  const hazards = (w,t) => w.hazards.map(h=>spline(h.knots,t,h.span_ms));
  function initial(w) {
    const p=target(w,0);
    return {tick:0,pen:[...p],velocity:[0,0],aim:[...p],ink:false,copied:0,available:0,missing_run:0,maximum_missing_run:0,terminal:'',reason:'',active:false};
  }
  function movePen(w,s) {
    const dt=w.dt_ms/1000;
    let desired=s.aim.map((v,j)=>(v-s.pen[j])/w.params.response_s), length=Math.hypot(...desired);
    if(length>w.pen_speed) desired=desired.map(v=>v*w.pen_speed/length);
    const change=desired.map((v,j)=>v-s.velocity[j]); length=Math.hypot(...change);
    const scale=Math.min(1,w.pen_acceleration*dt/Math.max(length,1e-12));
    for(let j=0;j<2;j++) {
      s.velocity[j]+=change[j]*scale;
      s.pen[j]=Math.max(w.pen_radius,Math.min(w[j?'height':'width']-w.pen_radius,s.pen[j]+s.velocity[j]*dt));
    }
  }
  function step(w,s) {
    if (!s.active || s.terminal) return;
    const previous=target(w,s.tick*w.dt_ms);
    s.tick++; const t=s.tick*w.dt_ms, p=target(w,t);
    movePen(w,s);
    const hp=hazards(w,t);
    const safe=hp.every((q,i)=>Math.hypot(p[0]-q[0],p[1]-q[1])>w.hazards[i].radius+w.params.tolerance+16);
    if(s.ink && hp.some((q,i)=>Math.hypot(s.pen[0]-q[0],s.pen[1]-q[1])<=w.hazards[i].radius+w.pen_radius)) {
      s.terminal='fail';s.reason='INK TOUCHED A VOID STAMP';return;
    }
    const distance=Math.hypot(p[0]-previous[0],p[1]-previous[1]);
    if(safe) {
      s.available+=distance;
      if(s.ink && Math.hypot(s.pen[0]-p[0],s.pen[1]-p[1])<=w.params.tolerance) {
        s.copied+=distance;s.missing_run=0;
      } else {
        s.missing_run+=distance;s.maximum_missing_run=Math.max(s.maximum_missing_run,s.missing_run);
        if(s.missing_run>w.params.maximum_gap){s.terminal='fail';s.reason='UNCOPIED STROKE TOO LONG';return;}
      }
    } else s.missing_run=0;
    if(t>=w.params.duration_ms) {
      const passed=s.available>0 && s.copied/s.available>=w.params.minimum_coverage;
      s.terminal=passed?'pass':'fail';s.reason=passed?'ORIGINAL COUNTERSIGNED':'INCOMPLETE CARBON COPY';
    }
  }
  function advance() {
    if(!model || !model.sim.active || model.sim.terminal) return;
    const w=model.state.world, tick=Math.min(Math.floor((performance.now()-model.startedAt)/w.dt_ms), w.params.duration_ms/w.dt_ms);
    while(model.sim.tick<tick && !model.sim.terminal) {
      step(w,model.sim);
      if(model.sim.ink) model.inkPath.push({point:[...model.sim.pen],tick:model.sim.tick});
      const t=model.sim.tick*w.dt_ms,p=target(w,t);
      if(model.sim.missing_run>0)model.missedPath.push({point:p,tick:model.sim.tick});
    }
    if(model.sim.terminal) finish();
  }
  function record(kind, source, detail={}) {
    model.events.push({sequence:model.events.length+1,kind,input_source:source,tick:model.sim.tick,...detail});
  }
  function aim(p) {
    advance(); if(!model.sim.active || model.sim.terminal)return;
    const w=model.state.world;
    p=p.map((x,j)=>Math.max(0,Math.min(w[j?'height':'width'],x)));
    record('aim',model.interaction==='full'?'pen_pointer':'pen_position_proxy',{point:p});
    model.sim.aim=p;
    paint();
  }
  function contact(down) {
    advance();if(!model.sim.active || model.sim.terminal || model.sim.ink===down)return;
    record('ink',model.interaction==='full'?'pen_contact':'ink_proxy',{down});model.sim.ink=down;
    const w=model.state.world,s=model.sim,hp=hazards(w,s.tick*w.dt_ms);
    if(down && hp.some((q,i)=>Math.hypot(s.pen[0]-q[0],s.pen[1]-q[1])<=w.hazards[i].radius+w.pen_radius)){
      s.terminal='fail';s.reason='INK TOUCHED A VOID STAMP';finish();
    }
    paint();
  }
  async function finish() {
    if(model.submitted)return;
    model.submitted=true;
    record('certify','certify_button');
    if(!model.sim.terminal){model.sim.terminal='fail';model.sim.reason='SUBMITTED BEFORE COPY FINISHED';}
    model.payload={mechanic_id:model.state.mechanic_id,revision:model.state.revision,task_id:model.state.task_id,
      challenge_id:model.state.challenge_id,interaction_mode:model.interaction,events:model.events,final_tick:model.sim.tick};
    model.helpers.setReadout('VERIFYING CARBON COPY…','pending');
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(model.payload)});
      model.serverGrade=await response.json();
      model.helpers.setReadout(model.serverGrade.passed?'PASS · ORIGINAL COUNTERSIGNED':`FAIL · ${model.sim.reason}`,model.serverGrade.passed?'passed':'error');
    }catch(e){model.helpers.setReadout(`VERIFIER ERROR · ${e.message}`,'error');}
    document.querySelector('#bst-status').textContent=model.sim.reason;
    document.querySelector('#bst-start').disabled=true;
    document.querySelector('#bst-ink').disabled=true;
    document.querySelector('#bst-certify').disabled=true;
    paint();
  }
  function paint() {
    const w=model.state.world, s=model.sim, t=s.tick*w.dt_ms, c=model.context;
    c.clearRect(0,0,w.width,w.height);
    c.fillStyle='#eee5ce';c.fillRect(0,0,w.width,w.height);
    const offset=spline(w.drift_knots,t,w.params.drift_ms);
    c.save();c.translate(offset[0],offset[1]);
    c.fillStyle='#fff8e7';c.shadowColor='#342e3855';c.shadowBlur=18;c.fillRect(55,38,850,397);c.shadowBlur=0;
    c.strokeStyle='#1f807255';c.lineWidth=1;c.strokeRect(66,49,828,375);
    for(let y=92;y<410;y+=28){c.beginPath();c.moveTo(77,y);c.lineTo(880,y);c.strokeStyle='#75654616';c.stroke();}
    c.fillStyle='#74634c';c.font='12px monospace';c.fillText('FORM 27B / CARBON DUPLICATE / DO NOT VOID',82,74);
    c.restore();
    // The frontier and its bounded future trace are visible task information.
    // Retired segments are visibly grey; they cannot be copied retroactively.
    c.beginPath();
    for(let ms=0;ms<=t;ms+=40){const p=target(w,ms);if(ms===0)c.moveTo(...p);else c.lineTo(...p);}
    c.strokeStyle='#81776744';c.lineWidth=3;c.stroke();
    const hp=hazards(w,t), p=target(w,t);
    hp.forEach((q,i)=>{
      const h=w.hazards[i];
      c.beginPath();c.moveTo(...spline(h.knots,Math.max(0,t-600),h.span_ms));c.lineTo(...q);
      c.strokeStyle='#b9413666';c.lineWidth=3;c.stroke();
      c.beginPath();c.arc(...q,h.radius+w.params.tolerance+16,0,Math.PI*2);c.setLineDash([5,5]);c.strokeStyle='#b9413655';c.stroke();c.setLineDash([]);
      c.beginPath();c.arc(...q,h.radius,0,Math.PI*2);c.fillStyle='#be403acc';c.fill();c.strokeStyle='#8c2727';c.lineWidth=3;c.stroke();
      c.save();c.translate(...q);c.rotate(-.16);c.fillStyle='#fff1dd';c.font='bold 18px monospace';c.textAlign='center';c.fillText('VOID',0,6);c.restore();
    });
    let last=null; c.strokeStyle='#273659';c.lineWidth=3;
    for(const point of model.inkPath){
      if(last && point.tick===last.tick+1){c.beginPath();c.moveTo(...last.point);c.lineTo(...point.point);c.stroke();}last=point;
    }
    last=null;c.strokeStyle='#ca791c';c.lineWidth=4;
    for(const point of model.missedPath){
      if(last && point.tick===last.tick+1){c.beginPath();c.moveTo(...last.point);c.lineTo(...point.point);c.stroke();}last=point;
    }
    // A chronological receipt retains the motion information that was visible
    // earlier. It ends at the current 1.4-s preview, never reveals the whole
    // future, and never restores an expired copy opportunity. The bounded
    // current view therefore contains the trajectory evidence of older views.
    const receipts=[{name:'ORIGINAL',at:ms=>target(w,ms)},
      {name:'SHEET',at:ms=>spline(w.drift_knots,ms,w.params.drift_ms)},
      ...w.hazards.map((h,i)=>({name:`VOID ${i+1}`,at:ms=>spline(h.knots,ms,h.span_ms)}))];
    receipts.forEach((item,i)=>{
      const width=924/receipts.length,x=18+i*width,y=9,plotWidth=width-14;
      c.fillStyle='#fff9e8ed';c.fillRect(x,y,plotWidth,69);
      c.strokeStyle='#70695066';c.lineWidth=.7;c.strokeRect(x,y,plotWidth,69);
      c.fillStyle='#485949';c.font='9px monospace';c.fillText(`${item.name} · x— y·· · RECORD / PREVIEW`,x+4,y+11);
      for(let axis=0;axis<2;axis++){
        c.beginPath();
        for(let ms=0;ms<=Math.min(w.params.duration_ms,t+w.preview_ms);ms+=20){
          const value=item.at(ms)[axis],height=item.name==='SHEET'?80:w[axis?'height':'width'];
          const q=[x+4+ms/w.params.duration_ms*(plotWidth-8),y+52-(item.name==='SHEET'?value+40:value)/height*33];
          if(ms===0)c.moveTo(...q);else c.lineTo(...q);
        }
        c.strokeStyle=axis?'#a14e32':'#246b73';c.lineWidth=1;c.setLineDash(axis?[2,2]:[]);c.stroke();c.setLineDash([]);
      }
      const now=x+4+t/w.params.duration_ms*(plotWidth-8);
      c.beginPath();c.moveTo(now,y+15);c.lineTo(now,y+54);c.strokeStyle='#1b423c';c.stroke();
      c.fillStyle='#485949';c.fillText(`0          NOW ${(t/1000).toFixed(2)}s / ${w.params.duration_ms/1000}s`,x+4,y+64);
    });
    // Forecasts are drawn ABOVE stamp fills and historical ink. Time-labelled
    // marks keep original / VOID identities visible through overlapping paths.
    const series=[{name:'ORIGINAL',color:'#178f87',at:ms=>target(w,ms)},
      ...w.hazards.map((h,i)=>({name:`V${i+1}`,color:i?'#a04b15':'#a52f50',at:ms=>spline(h.knots,ms,h.span_ms)}))];
    series.forEach((item,index)=>{
      c.beginPath();
      for(let ms=t;ms<=Math.min(w.params.duration_ms,t+w.preview_ms);ms+=20){const q=item.at(ms);if(ms===t)c.moveTo(...q);else c.lineTo(...q);}
      c.strokeStyle='#fff9e8';c.lineWidth=4;c.stroke();c.strokeStyle=item.color;c.lineWidth=2;c.setLineDash(index?[4,4]:[]);c.stroke();c.setLineDash([]);
      for(let ms=t+200;ms<=Math.min(w.params.duration_ms,t+w.preview_ms);ms+=200){
        const q=item.at(ms);c.beginPath();c.arc(...q,3.5,0,Math.PI*2);c.fillStyle='#fff9e8';c.fill();c.strokeStyle=item.color;c.lineWidth=1.5;c.stroke();
        if(ms===t+w.lead_ms){
          const radius=index?w.hazards[index-1].radius+w.pen_radius:w.params.tolerance;
          c.beginPath();c.arc(...q,radius,0,Math.PI*2);c.setLineDash([3,5]);c.strokeStyle=item.color;c.stroke();c.setLineDash([]);
          c.font='bold 10px monospace';c.fillStyle=item.color;c.fillText(`${item.name} +0.20s`,q[0]+radius+4,q[1]-5);
          const following=item.at(Math.min(w.params.duration_ms,ms+w.dt_ms));
          c.beginPath();c.moveTo(...q);c.lineTo(...following);c.strokeStyle=item.color;c.lineWidth=3;c.stroke();
          c.beginPath();c.arc(...following,2,0,Math.PI*2);c.fillStyle=item.color;c.fill();
        }
      }
    });
    const ghost={pen:[...s.pen],velocity:[...s.velocity],aim:[...s.aim]};
    c.beginPath();c.moveTo(...s.pen);
    for(let ms=0;ms<w.lead_ms;ms+=w.dt_ms){movePen(w,ghost);c.lineTo(...ghost.pen);}
    c.strokeStyle='#1e587b';c.lineWidth=2;c.setLineDash([3,4]);c.stroke();c.setLineDash([]);
    c.beginPath();c.moveTo(ghost.pen[0],ghost.pen[1]-7);c.lineTo(ghost.pen[0]+7,ghost.pen[1]);c.lineTo(ghost.pen[0],ghost.pen[1]+7);c.lineTo(ghost.pen[0]-7,ghost.pen[1]);c.closePath();c.fillStyle='#fff9e8';c.fill();c.strokeStyle='#1e587b';c.stroke();
    c.font='bold 10px monospace';c.fillStyle='#1e587b';c.fillText('HELD PEN +0.20s',ghost.pen[0]+10,ghost.pen[1]+18);
    const nextGhost={pen:[...ghost.pen],velocity:[...ghost.velocity],aim:[...ghost.aim]};movePen(w,nextGhost);
    c.beginPath();c.moveTo(...ghost.pen);c.lineTo(...nextGhost.pen);c.strokeStyle='#1e587b';c.lineWidth=3;c.stroke();
    c.beginPath();c.arc(...nextGhost.pen,2,0,Math.PI*2);c.fillStyle='#1e587b';c.fill();
    c.beginPath();c.moveTo(...s.pen);c.lineTo(s.pen[0]+s.velocity[0]*.12,s.pen[1]+s.velocity[1]*.12);c.strokeStyle='#1e587b80';c.stroke();
    const projected={...s,pen:[...s.pen],velocity:[...s.velocity],aim:[...s.aim]};
    for(let ms=0;ms<w.lead_ms && !projected.terminal;ms+=w.dt_ms)step(w,projected);
    document.querySelector('#bst-lead').textContent=projected.terminal?`HELD +0.20s: ${projected.reason}`:`HELD +0.20s STRETCH ${projected.missing_run.toFixed(1)} px`;
    // Exact coordinates of already drawn glyphs, for read-only construction
    // comparisons only. This is not an input surface or a screenshot solver.
    model.visibleForecast={lead_ms:w.lead_ms,pen:ghost.pen,pen_next:nextGhost.pen,
      original:target(w,Math.min(w.params.duration_ms,t+w.lead_ms)),
      original_next:target(w,Math.min(w.params.duration_ms,t+w.lead_ms+w.dt_ms)),
      voids:hazards(w,Math.min(w.params.duration_ms,t+w.lead_ms)),
      voids_next:hazards(w,Math.min(w.params.duration_ms,t+w.lead_ms+w.dt_ms)),
      void_radii:w.hazards.map(h=>h.radius+w.pen_radius),copy_tolerance:w.params.tolerance,
      current_gap:s.missing_run,held_gap:projected.missing_run,gap_limit:w.params.maximum_gap,
      aim:[...s.aim],ink:s.ink};
    const safe=hp.every((q,i)=>Math.hypot(p[0]-q[0],p[1]-q[1])>w.hazards[i].radius+w.params.tolerance+16);
    c.beginPath();c.arc(...p,w.params.tolerance,0,Math.PI*2);c.fillStyle=safe?'#29ab9530':'#ba403a20';c.fill();c.strokeStyle=safe?'#178f87':'#be403a';c.lineWidth=2;c.stroke();
    c.beginPath();c.arc(...p,5,0,Math.PI*2);c.fillStyle=safe?'#178f87':'#be403a';c.fill();
    c.beginPath();c.arc(...s.aim,7,0,Math.PI*2);c.strokeStyle='#29345180';c.stroke();
    c.save();c.translate(...s.pen);c.rotate(-.65);c.fillStyle=s.ink?'#24385d':'#757775';c.fillRect(-4,-29,8,24);c.beginPath();c.moveTo(-4,-5);c.lineTo(4,-5);c.lineTo(0,0);c.fill();c.restore();
    if(!s.active){c.fillStyle='#153e3d';c.font='bold 18px monospace';c.fillText('START THE FEED · FOLLOW THE GREEN ORIGINAL',212,451);}
    const progress=t/w.params.duration_ms;
    document.querySelector('#bst-feed').style.width=`${progress*100}%`;
    document.querySelector('#bst-copy').textContent=`COPIED ${Math.round(100*s.copied/Math.max(1,s.available))}% / REQUIRED ${Math.round(w.params.minimum_coverage*100)}%`;
    document.querySelector('#bst-gap').textContent=`UNCOPIED STRETCH ${s.missing_run.toFixed(1)} / ${w.params.maximum_gap} px`;
    document.querySelector('#bst-motion').textContent=`NIB ${s.pen.map(v=>v.toFixed(1)).join(',')} · V ${s.velocity.map(v=>v.toFixed(1)).join(',')} px/s · AIM ${s.aim.map(v=>v.toFixed(1)).join(',')}`;
    document.querySelector('#bst-gap-fill').style.width=`${Math.min(100,100*s.missing_run/w.params.maximum_gap)}%`;
    document.querySelector('#bst-ink').textContent=s.ink?'LIFT PEN':'LOWER PEN';
    if(!s.terminal)document.querySelector('#bst-status').textContent=!s.active?'INSPECTION · FEED STOPPED':safe?(s.ink?'INK DOWN · COPY THE GREEN FRONTIER':'PEN LIFTED · ORIGINAL STILL MOVING'):'VOID CROSSING · LIFT THE PEN';
    if(s.terminal){c.fillStyle=s.terminal==='pass'?'#154b3de6':'#8e2828e6';c.fillRect(222,183,516,92);c.fillStyle='#fff6df';c.textAlign='center';c.font='bold 26px monospace';c.fillText(s.terminal==='pass'?'ORIGINAL COUNTERSIGNED':'FORM VOID / ATTEMPT ENDED',480,223);c.font='14px monospace';c.fillText(s.reason,480,249);c.textAlign='left';}
  }
  function animate(){advance();paint();frame=requestAnimationFrame(animate);}
  async function render(state,helpers){
    cancelAnimationFrame(frame);document.body.dataset.mechanic='moving-carbon-v2';
    model={state,helpers,interaction:state.control_condition?.interaction||'full',sim:initial(state.world),events:[],inkPath:[],missedPath:[],startedAt:null,submitted:false,serverGrade:null,payload:null};
    window.bureaucraticSignatureV2Model=model;
    helpers.app.innerHTML=`<section class="bst-desk"><header><div><p>MINISTRY OF REDUNDANT SIGNATURES / DESK 27B</p><h1>Bureaucratic Signature Trap V2</h1></div><span class="bst-badge">CARBON COPY<br>ONE ORIGINAL · ONE ATTEMPT</span></header>
      <div class="bst-note"><b>COUNTERSIGN THE MOVING ORIGINAL.</b> Follow green; lift over solid VOID stamps. A continuous uncovered stretch over ${state.world.params.maximum_gap} px voids the form; stamp crossings interrupt that stretch. Orange is missed ink. Dashed rings and blue diamond predict +0.20 s; short stems show the next 20 ms step. Marks are 0.20 s apart, through 1.4 s. Motion receipts retain earlier paths. Pen response ${state.world.params.response_s}s; speed ≤650 px/s, acceleration ≤3600 px/s². ${model.interaction==='full'?'Move the pointer. Hold left to write; release to lift.':'Click the desk to aim; use LOWER / LIFT PEN.'}</div>
      <div class="bst-paper"><canvas id="bst-canvas" width="960" height="480"></canvas></div>
      <footer><div class="bst-ledger"><b id="bst-status"></b><span id="bst-copy"></span><span id="bst-gap"></span><span id="bst-lead"></span><span id="bst-motion"></span><div class="bst-gap-progress"><i id="bst-gap-fill"></i></div><div class="bst-progress"><i id="bst-feed"></i></div></div><div class="bst-controls"><button id="bst-start">START FEED</button><button id="bst-ink" ${model.interaction==='full'?'hidden':''}>LOWER PEN</button><button id="bst-certify">CERTIFY COPY</button></div><div class="readout" aria-live="polite"></div></footer></section>`;
    const canvas=document.querySelector('#bst-canvas');model.context=canvas.getContext('2d');
    const point=e=>{const r=canvas.getBoundingClientRect();return[(e.clientX-r.left)*960/r.width,(e.clientY-r.top)*480/r.height];};
    canvas.addEventListener('pointermove',e=>{if(model.interaction==='full')aim(point(e));});
    canvas.addEventListener('pointerdown',e=>{
      if(e.button!==0 || model.interaction!=='full' || !model.sim.active || model.sim.terminal)return;
      e.preventDefault();canvas.setPointerCapture(e.pointerId);aim(point(e));contact(true);
    });
    canvas.addEventListener('pointerup',e=>{if(model.interaction==='full'){contact(false);if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);}});
    canvas.addEventListener('pointercancel',()=>{if(model.interaction==='full')contact(false);});
    canvas.addEventListener('lostpointercapture',()=>{if(model.interaction==='full')contact(false);});
    canvas.addEventListener('click',e=>{if(model.interaction==='simplified')aim(point(e));});
    document.querySelector('#bst-start').addEventListener('click',()=>{
      if(model.sim.active || model.sim.terminal)return;
      record('start','start_button');model.sim.active=true;model.startedAt=performance.now();
      document.querySelector('#bst-start').disabled=true;
      paint();
    });
    document.querySelector('#bst-ink').addEventListener('click',()=>{if(model.interaction==='simplified')contact(!model.sim.ink);});
    document.querySelector('#bst-certify').addEventListener('click',()=>{advance();finish();});
    paint();frame=requestAnimationFrame(animate);
  }
  // Physics exports support read-only construction comparisons, never input.
  window.BureaucraticSignatureV2Physics={spline,target,hazards,initial,step,movePen};
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.bureaucratic_signature_trap_v2={render,rootSelector:'.bst-desk'};
})();
