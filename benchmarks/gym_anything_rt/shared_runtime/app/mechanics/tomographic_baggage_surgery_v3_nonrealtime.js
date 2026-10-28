(() => {
  'use strict';
  let m, raf=0;
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  const esc=x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function motion(spec,t) {
    const u=Math.max(0,t)/spec.span_ms,n=Math.min(Math.floor(u),spec.knots.length-2),f=Math.min(1,u-n),h=f*f*(3-2*f);
    return spec.knots[n].map((a,i)=>a+(spec.knots[n+1][i]-a)*h);
  }
  function record(kind,extra={}) { m.events.push({sequence:m.events.length+1,kind,t_ms:m.t,...extra}); }
  const terminal=()=>['failed','complete'].includes(m.phase);
  function tick() {
    const p=m.state.physics,k=m.state.parameters,dt=p.dt_ms/1000;
    m.t+=p.dt_ms;
    for(let i=0;i<2;i++) {
      const a=clamp(k.gain*(m.command[i]-m.yz[i])-k.damping*m.velocity[i],-p.max_accel,p.max_accel);
      m.velocity[i]=clamp(m.velocity[i]+a*dt,-p.max_speed,p.max_speed);m.yz[i]+=m.velocity[i]*dt;
    }
    const old=m.x;
    if(m.phase==='inbound') {m.x=Math.min(p.target_x,m.x+k.speed*dt);if(m.x===p.target_x)m.phase='grip';}
    else if(m.phase==='outbound')m.x=Math.max(p.entry_x,m.x-k.speed*dt);
    const r=m.held?p.load_radius:p.tool_radius;
    if(m.yz.some(v=>Math.abs(v)+r>p.bounds))m.failure='case wall';
    for(const g of m.state.gates) {
      const c=motion(g.motion,m.t);
      if(Math.abs(m.x-g.x)<=g.half+r && Math.hypot(m.yz[0]-c[0],m.yz[1]-c[1])+r>g.radius)m.failure=`layer ${g.id} contact`;
      if((old-g.x)*(m.x-g.x)<=0 && old!==m.x) {
        const tag=`${g.id}:${m.held?'out':'in'}`;if(!m.crossed.includes(tag))m.crossed.push(tag);
      }
    }
    if(m.t>=p.max_ms)m.failure='time allowance exhausted';
    if(m.failure)m.phase='failed';else if(m.held && m.x<=p.entry_x)m.phase='complete';
  }
  function advanceForAction() {
    if(m.phase==='ready'||terminal())return;
    const end=Math.min(m.state.physics.max_ms,m.t+m.state.physics.action_step_ms);
    while(m.t<end&&!terminal())tick();
    if(terminal()) { draw(); void submit(); }
  }
  function nextGate() {
    const r=m.held?m.state.physics.load_radius:m.state.physics.tool_radius;
    if(m.phase==='outbound')return [...m.state.gates].reverse().find(g=>m.x>=g.x-g.half-r);
    return m.state.gates.find(g=>m.x<=g.x+g.half+r);
  }
  function point(canvas,e) {
    const b=canvas.getBoundingClientRect(),v=m.state.views,s=v.pad_scale,o=v.pad_origin,ext=v.pad_extent;
    return [clamp((e.clientX-b.left)*canvas.width/b.width,o[0]-s*ext,o[0]+s*ext),
            clamp((e.clientY-b.top)*canvas.height/b.height,o[1]-s*ext,o[1]+s*ext)].map(x=>Math.round(x*1e6)/1e6);
  }
  function command(p) {const v=m.state.views;return [(p[0]-v.pad_origin[0])/v.pad_scale,(v.pad_origin[1]-p[1])/v.pad_scale];}
  function padEvent(kind,e) {
    if(terminal()||m.submitting)return;
    const p=point(e.currentTarget,e),c=command(p);
    if(m.interaction==='full') {
      if(kind==='pad_down') {
        if(Math.hypot(c[0]-m.command[0],c[1]-m.command[1])*m.state.views.pad_scale>m.state.views.handle_radius)return;
        m.drag=true;e.currentTarget.setPointerCapture(e.pointerId);
      } else if(!m.drag)return;
      advanceForAction();if(terminal()||m.submitting)return;
      if(kind!=='pad_down')m.command=c;
      if(kind==='pad_up'){m.drag=false;e.currentTarget.releasePointerCapture(e.pointerId);}
    } else if(kind==='pad_click'){
      advanceForAction();if(terminal()||m.submitting)return;
      m.command=c;
    } else return;
    record(kind,{point:p,input_source:m.interaction==='full'?'drag_pad':'click_pad'});draw();
  }
  function grip(source) {
    if(terminal()||m.submitting||m.held)return;
    advanceForAction();if(terminal()||m.submitting)return;
    // Early presses do not arm a later automatic catch. A failed actual clamp
    // closure is visible and terminal; OS repeat never creates another closure.
    record('grip',{input_source:source});
    const target=motion(m.state.target.motion,m.t);
    if(m.phase!=='grip'||Math.hypot(m.yz[0]-target[0],m.yz[1]-target[1])>m.state.physics.grip_distance){m.failure='empty grip';m.phase='failed';}
    else {m.held=true;m.phase='outbound';m.helpers.setReadout('RELIC HELD · GUIDE THE WITHDRAWAL','pending');}
    draw();if(terminal())void submit();
  }
  function start() {
    if(m.phase!=='ready'||m.submitting)return;
    record('start');m.phase='inbound';
    m.helpers.setReadout('LIVE INSERTION · SCAN VIEWS REMAIN AVAILABLE','pending');draw();
  }
  function inspectSlice(index) {
    if(terminal()||m.submitting)return;
    const g=m.state.gates[index];if(!g)return;
    advanceForAction();if(terminal()||m.submitting)return;
    m.sliceIndex=index;m.scanned.add(g.id);
    record('slice_scan',{layer_id:g.id,input_source:m.state.sensing.input_source});
    m.helpers.setReadout(`LAYER ${g.id} SCANNED · ${m.phase==='ready'?'TRACK ACQUIRED':'TRACKING LIVE'}`,'pending');
    draw();
  }
  function payload() {return {mechanic_id:m.state.mechanic_id,revision:m.state.revision,task_id:m.state.task_id,
    challenge_id:m.state.challenge_id,interaction:m.interaction,events:m.events,final_t_ms:m.t};}
  async function submit() {
    if(m.submitting||m.submitted)return;
    m.submitting=true;
    if(!terminal()){advanceForAction();}
    if(!terminal()){m.failure='incomplete submission';m.phase='failed';draw();}
    const data=payload();
    try {
      const res=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(data)});
      const result=await res.json();m.grade=result;m.submitted=true;
      m.helpers.setReadout(result.passed===true?'PASS · RELIC EXTRACTED':`FAIL · ${m.failure||result.feedback||'EXTRACTION REJECTED'}`,result.passed===true?'passed':'error');
      // A regenerated response is never used to clear a terminal failure.
    } catch(error) {m.helpers.setReadout(`VERIFIER ERROR · ${error.message}`,'error');}
    m.submitting=false;draw();
  }
  function base(ctx,w,h) {
    ctx.clearRect(0,0,w,h);ctx.fillStyle='#07171e';ctx.fillRect(0,0,w,h);
    ctx.strokeStyle='#24505a';ctx.lineWidth=1;
    for(let x=15;x<w;x+=30){ctx.beginPath();ctx.moveTo(x,12);ctx.lineTo(x,h-12);ctx.stroke();}
    for(let y=20;y<h;y+=30){ctx.beginPath();ctx.moveTo(12,y);ctx.lineTo(w-12,y);ctx.stroke();}
  }
  function dot(ctx,x,y,r,color) {ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#ecfaf4';ctx.lineWidth=1;ctx.stroke();}
  function axialBody(ctx,x,y,r,ds,ts,color) {
    // A short axial cylinder: its depth/height projection is a rectangle;
    // its transverse projection is the circle used by the collision test.
    ctx.fillStyle=color;ctx.strokeStyle='#ecfaf4';ctx.lineWidth=1;
    ctx.fillRect(x-r*ds,y-r*ts,2*r*ds,2*r*ts);
    ctx.strokeRect(x-r*ds,y-r*ts,2*r*ds,2*r*ts);
  }
  function trace(ctx,spec,map,color) {
    for(const [a,b,dash,alpha] of [[-m.state.physics.tail_ms,0,[],.35],[0,m.state.physics.forecast_ms,[3,4],.9]]) {
      ctx.beginPath();for(let off=a;off<=b;off+=40){const p=map(motion(spec,Math.max(0,m.t+off)));if(off===a)ctx.moveTo(...p);else ctx.lineTo(...p);}
      ctx.setLineDash(dash);ctx.globalAlpha=alpha;ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();ctx.globalAlpha=1;ctx.setLineDash([]);
    }
    // The forecast carries time as well as geometry. These marks let a player
    // locate the +800ms interception point from the visible canvas itself.
    ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1.5;
    for(const off of [400,800,1200]) {
      const [x,y]=map(motion(spec,m.t+off));ctx.beginPath();
      if(off===1200) {ctx.moveTo(x,y-5);ctx.lineTo(x+4,y);ctx.lineTo(x,y+5);ctx.lineTo(x-4,y);ctx.closePath();ctx.stroke();}
      else {ctx.arc(x,y,off===400?2:4,0,Math.PI*2);if(off===400)ctx.fill();else ctx.stroke();}
    }
  }
  function projection(canvas,axis) {
    const ctx=canvas.getContext('2d'),v=m.state.views,o=v.origin,ds=v.depth_scale,ts=v.transverse_scale;
    base(ctx,canvas.width,canvas.height);
    const px=x=>o[0]+x*ds,py=y=>o[1]-y*ts;
    ctx.strokeStyle='#b0d8cd';ctx.strokeRect(px(0),py(3),10*ds,6*ts);
    const next=nextGate();
    for(const g of m.state.gates) {
      const x=px(g.x),width=2*g.half*ds;
      if(!m.scanned.has(g.id)) {
        // Opaque survey silhouette: no gap, center marker, tail or forecast
        // may reveal an aperture before its transverse slice is inspected.
        ctx.fillStyle='#507d85';ctx.fillRect(x-width/2,py(3),width,6*ts);
        ctx.fillStyle='#daecec';ctx.font='12px monospace';ctx.fillText(`${g.id}?`,x-6,22);
        continue;
      }
      const c=motion(g.motion,m.t)[axis];
      ctx.fillStyle=next===g?'#efb96a':'#507d85';
      ctx.fillRect(x-width/2,py(3),width,py(c+g.radius)-py(3));
      ctx.fillRect(x-width/2,py(c-g.radius),width,py(-3)-py(c-g.radius));
      ctx.strokeStyle=next===g?'#ffd493':'#80a9ac';ctx.lineWidth=3;
      ctx.beginPath();ctx.moveTo(x,py(c+g.radius));ctx.lineTo(x,py(c-g.radius));ctx.stroke();
      ctx.fillStyle='#daecec';ctx.font='12px monospace';ctx.fillText(String(g.id),x-3,22);
      trace(ctx,g.motion,p=>[x,py(p[axis])],'#efb96a');
    }
    if(!m.held) {const p=motion(m.state.target.motion,m.t);trace(ctx,m.state.target.motion,q=>[px(m.state.target.x),py(q[axis])],'#ff8faa');axialBody(ctx,px(m.state.target.x),py(p[axis]),m.state.target.radius,ds,ts,'#ff6f9f');}
    const r=m.held?m.state.physics.load_radius:m.state.physics.tool_radius;
    axialBody(ctx,px(m.x),py(m.yz[axis]),r,ds,ts,m.held?'#ff7ca7':'#83fce1');
    ctx.strokeStyle='#e6fffc';ctx.beginPath();ctx.moveTo(px(m.x),py(m.yz[axis]));ctx.lineTo(px(m.x),py(m.yz[axis]+m.velocity[axis]*.4));ctx.stroke();
    ctx.fillStyle='#b5d7d7';ctx.font='12px monospace';ctx.fillText(axis===0?'DEPTH → / HEIGHT ↑':'DEPTH → / LATERAL ↑',15,canvas.height-8);
  }
  function slice(canvas) {
    const ctx=canvas.getContext('2d'),v=m.state.views,o=v.slice_origin,scale=v.slice_scale;
    base(ctx,canvas.width,canvas.height);const map=p=>[o[0]+p[0]*scale,o[1]-p[1]*scale];
    ctx.strokeStyle='#9ebabc';ctx.strokeRect(o[0]-3*scale,o[1]-3*scale,6*scale,6*scale);
    const g=m.state.gates[m.sliceIndex];
    if(!g) {
      ctx.fillStyle='#c7dbd8';ctx.font='13px monospace';
      ctx.fillText('OPAQUE BAGGAGE LAYERS',28,108);
      ctx.fillText('SELECT A NUMBER ABOVE',28,134);
      ctx.fillText('TO SCAN ITS APERTURE',28,158);
      return;
    }
    const c=motion(g.motion,m.t),p=map(c);
    // The filled metal plate and its circular hole are the collision geometry.
    ctx.fillStyle='#b6936040';ctx.fillRect(o[0]-3*scale,o[1]-3*scale,6*scale,6*scale);
    ctx.beginPath();ctx.arc(...p,g.radius*scale,0,Math.PI*2);ctx.fillStyle='#07171e';ctx.fill();ctx.strokeStyle='#ffc37d';ctx.lineWidth=3;ctx.stroke();
    trace(ctx,g.motion,map,'#ffe0a4');
    const target=motion(m.state.target.motion,m.t);
    if(!m.held){trace(ctx,m.state.target.motion,map,'#ff8eaf');dot(ctx,...map(target),m.state.target.radius*scale,'#ff719f80');}
    dot(ctx,...map(m.yz),(m.held?m.state.physics.load_radius:m.state.physics.tool_radius)*scale,m.held?'#ff79a4':'#89f9e5');
    ctx.fillStyle='#d5eceb';ctx.font='12px monospace';ctx.fillText(`PROJECTED ON ${g.id} · DEPTH ${g.x.toFixed(1)}`,10,18);
  }
  function pad(canvas) {
    const ctx=canvas.getContext('2d'),v=m.state.views,o=v.pad_origin,s=v.pad_scale;
    base(ctx,canvas.width,canvas.height);ctx.strokeStyle='#83e9d7';ctx.strokeRect(o[0]-s*v.pad_extent,o[1]-s*v.pad_extent,2*s*v.pad_extent,2*s*v.pad_extent);
    const map=p=>[o[0]+s*p[0],o[1]-s*p[1]];
    ctx.strokeStyle='#839ba3';ctx.beginPath();ctx.moveTo(...map(m.yz));ctx.lineTo(...map(m.command));ctx.stroke();
    dot(ctx,...map(m.yz),5,'#fffbde');dot(ctx,...map(m.command),v.handle_radius,'#64ccbf');
    ctx.fillStyle='#082d31';ctx.font='bold 13px monospace';const h=map(m.command);ctx.fillText('+',h[0]-4,h[1]+4);
    ctx.fillStyle='#c5efec';ctx.font='12px monospace';ctx.fillText('HEIGHT → / LATERAL ↑',10,18);
    ctx.fillText(m.interaction==='full'?'DRAG THE + HANDLE':'CLICK A COMMAND POSITION',10,canvas.height-9);
  }
  function draw() {
    if(!m)return;const root=document.querySelector('.tbs2');if(!root)return;
    root.dataset.phase=m.phase;
    projection(root.querySelector('[data-view="height"]'),0);projection(root.querySelector('[data-view="lateral"]'),1);
    slice(root.querySelector('.tbs2-slice'));pad(root.querySelector('.tbs2-pad'));
    const g=nextGate(),remaining=g?Math.max(0,(Math.abs(m.x-g.x)-g.half-(m.held?m.state.physics.load_radius:m.state.physics.tool_radius))/m.state.parameters.speed):null;
    const rejected=m.grade?.passed===false,verified=m.grade?.passed===true;
    root.dataset.verdict=terminal()?(m.failure||rejected?'failed':verified?'passed':'pending'):'none';
    root.querySelector('.tbs2-status').textContent=m.phase==='ready'?'PREPARE · THEN START':terminal()?(m.failure?`FAIL · ${m.failure}`:rejected?'EXTRACTION REJECTED':verified?'EXTRACTION COMPLETE':'VERIFYING EXTRACTION'):m.phase==='grip'?'AT THE BACK · ALIGN & GRIP':`${m.held?'WITHDRAWING':'INSERTING'} · ${g?`NEXT LAYER ${g.id} IN ${remaining.toFixed(1)}s`:'BACK RELIC'}`;
    root.querySelector('.tbs2-progress').textContent=`DEPTH ${m.x.toFixed(2)} / 9.50 · ${m.held?'RELIC HELD':'CLAMP EMPTY'}`;
    root.querySelector('.tbs2-start').disabled=m.phase!=='ready';
    root.querySelectorAll('[data-slice]').forEach(b=>{
      b.setAttribute('aria-pressed',String(Number(b.dataset.slice)===m.sliceIndex));
      b.dataset.scanned=String(m.scanned.has(m.state.gates[Number(b.dataset.slice)].id));
      b.disabled=terminal();
    });
    const gripButton=root.querySelector('.tbs2-grip');if(gripButton)gripButton.disabled=terminal()||m.phase==='ready'||m.held;
    root.querySelector('.tbs2-verdict').textContent=terminal()?(m.failure||rejected?'FAIL':verified?'PASS':'CHECKING'):'';
  }
  function animate() {draw();raf=requestAnimationFrame(animate);}
  async function render(state,helpers) {
    cancelAnimationFrame(raf);document.body.dataset.mechanic='tomographic-baggage-surgery-v3_nonrealtime';
    m={state,helpers,interaction:state.control_condition.interaction,t:0,x:state.physics.entry_x,yz:[0,0],velocity:[0,0],command:[0,0],
      phase:'ready',held:false,failure:null,crossed:[],events:[],drag:false,sliceIndex:null,scanned:new Set(state.sensing.initially_scanned),submitted:false,submitting:false};
    window.tomographicBaggageSurgeryV3NonrealtimeModel=m;
    helpers.app.innerHTML=`<section class="tbs2"><header><div><small>VOLUMETRIC CUSTOMS / MOVING BAGGAGE</small><h1>Tomographic Baggage Surgery V3</h1></div><b>D${state.control_condition.difficulty} · ${esc(m.interaction.toUpperCase())}</b></header>
      <p class="tbs2-rules">${esc(state.prompt)}</p><div class="tbs2-grid"><section><h2>X-RAY / HEIGHT</h2><canvas data-view="height" width="500" height="280"></canvas></section>
      <section><h2>X-RAY / LATERAL</h2><canvas data-view="lateral" width="500" height="280"></canvas></section>
      <section><h2>SCAN LAYER ${state.gates.map((g,i)=>`<button data-slice="${i}" aria-label="Scan layer ${g.id}">${g.id}</button>`).join('')}</h2><canvas class="tbs2-slice" width="300" height="280"></canvas></section>
      <section><h2>INERTIAL PROBE COMMAND</h2><canvas class="tbs2-pad" width="300" height="280"></canvas></section></div>
      <aside><span><i class="tbs2-status"></i><small class="tbs2-progress"></small></span><button class="tbs2-start">START INSERTION</button>${m.interaction==='simplified'?'<button class="tbs2-grip">GRIP RELIC</button>':'<span class="tbs2-key">SPACE / GRIP RELIC</span>'}<button class="tbs2-submit">SEAL REPORT</button></aside>
      <footer><span>TEAL = PROBE · PINK = RELIC · AMBER = SCANNED APERTURE · ? = UNSCANNED<br>SOLID = LAST 0.24s · DASHED: ● +0.4s / ○ +0.8s / ◇ +1.2s<br>FIRST FAILURE ENDS EPISODE: CONTACT / EMPTY GRIP / EXHAUSTED TIME / REJECTED SEAL</span><div class="readout">Scan layers; acquired tracks stay live. Start when ready.</div></footer><div class="tbs2-verdict"></div></section>`;
    const padCanvas=document.querySelector('.tbs2-pad');
    if(m.interaction==='full')for(const [name,kind] of [['pointerdown','pad_down'],['pointermove','pad_move'],['pointerup','pad_up'],['pointercancel','pad_up']])padCanvas.addEventListener(name,e=>{if(e.button===0||kind==='pad_move'||kind==='pad_up'){e.preventDefault();padEvent(kind,e);}});
    else padCanvas.addEventListener('click',e=>padEvent('pad_click',e));
    document.querySelector('.tbs2-start').addEventListener('click',start);
    document.querySelector('.tbs2-submit').addEventListener('click',()=>{void submit();});
    document.querySelector('.tbs2-grip')?.addEventListener('click',()=>grip('grip_button'));
    const key=e=>{if(document.body.dataset.mechanic!=='tomographic-baggage-surgery-v3_nonrealtime')return;if(e.code==='Space'&&m.interaction==='full'&&!e.repeat){e.preventDefault();grip('space_key');}};
    if(window.tbs2KeyHandler)window.removeEventListener('keydown',window.tbs2KeyHandler);window.tbs2KeyHandler=key;window.addEventListener('keydown',key);
    document.querySelectorAll('[data-slice]').forEach(b=>b.addEventListener('click',()=>inspectSlice(Number(b.dataset.slice))));
    draw();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.tomographic_baggage_surgery_v3_nonrealtime={rootSelector:'.tbs2',render};
})();
