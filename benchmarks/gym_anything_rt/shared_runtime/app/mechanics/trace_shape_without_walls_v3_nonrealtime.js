(() => {
  'use strict';
  const ACTION_STEP_MS = 240;
  let model;
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const smooth = x => x*x*(3-2*x);
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index+1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function motion(seed, ms, span) {
    const u = Math.max(0, ms)/span, i = Math.floor(u);
    return noise(seed,i)+(noise(seed,i+1)-noise(seed,i))*smooth(u-i);
  }
  function center(w, x, ms) {
    let i = w.nodes.findIndex((n,j) => j < w.nodes.length-1 && x <= w.nodes[j+1].x);
    if (i < 0) i = w.nodes.length-2;
    const a = w.nodes[i], b = w.nodes[i+1], f = smooth(clamp((x-a.x)/(b.x-a.x),0,1));
    const common=w.coherence*motion(w.wall_seed,ms,w.span_ms),local=1-w.coherence;
    const ay = a.y+w.amplitude*(common+local*motion(a.seed,ms,w.span_ms)), by = b.y+w.amplitude*(common+local*motion(b.seed,ms,w.span_ms));
    return ay+(by-ay)*f;
  }
  const wind = (w,ms) => w.wind*motion(w.wind_seed,ms,4300);
  function clearance(w,x,y,ms) {
    let best = Infinity;
    for (let xx = Math.max(0,Math.floor((x-12)/4)*4); xx <= Math.min(996,Math.ceil((x+12)/4)*4); xx+=4) {
      for (const side of [-1,1]) {
        const ay = center(w,xx,ms)+side*w.radius, by = center(w,xx+4,ms)+side*w.radius;
        const dy = by-ay, f = clamp(((x-xx)*4+(y-ay)*dy)/(16+dy*dy),0,1);
        best = Math.min(best,Math.hypot(x-xx-f*4,y-ay-f*dy));
      }
    }
    return Math.abs(y-center(w,x,ms))<=w.radius ? best : -best;
  }
  class Physics {
    constructor(w) {
      this.world=w; this.ms=0; this.x=w.start_x; this.y=center(w,this.x,0);
      this.v=0; this.target=this.y; this.active=false; this.done=false; this.failed='';
    }
    launch() { this.active=true; this.y=center(this.world,this.x,this.ms); this.target=this.y; }
    advance(end) {
      const w=this.world;
      while (this.ms+10<=end && !this.failed && !this.done) {
        this.ms+=10;
        if (!this.active) { this.y=center(w,this.x,this.ms); this.target=this.y; if(this.ms>=w.max_ms)this.failed='TRACE TIME EXHAUSTED'; continue; }
        const a=clamp((this.target-this.y)*w.response**2-2*w.response*this.v+wind(w,this.ms),-w.max_acceleration,w.max_acceleration);
        this.v=clamp(this.v+a*.01,-w.max_velocity,w.max_velocity);
        this.x=Math.min(w.exit_x,this.x+w.speed*.01); this.y+=this.v*.01;
        if (clearance(w,this.x,this.y,this.ms)<w.probe_radius-1e-7) this.failed='WALL CONTACT';
        else if (this.x>=w.exit_x) this.done=true;
        else if (this.ms>=w.max_ms) this.failed='TRACE TIME EXHAUSTED';
      }
    }
  }
  // Exposed for read-only construction diagnostics, never an agent action.
  window.TraceShapeV3Physics={Physics,center,clearance,wind};
  function sync() {
    if (model.terminal) return;
    model.currentMs=model.physics.ms;
  }
  function advanceForAction() {
    if (!model || model.terminal || !model.physics.active) return false;
    const next=Math.min(model.state.world.max_ms,model.physics.ms+ACTION_STEP_MS);
    model.physics.advance(next);
    model.currentMs=model.physics.ms;
    if (model.physics.failed || model.physics.done) {
      finish();
      return false;
    }
    return true;
  }
  const point = e => {
    const r=document.querySelector('#trace-v2-scope').getBoundingClientRect();
    return [clamp((e.clientX-r.left)*1000/r.width,0,1000),clamp((e.clientY-r.top)*480/r.height,0,480)];
  };
  function record(kind,p,source) {
    model.events.push({sequence:model.events.length+1,kind,t_ms:model.currentMs,input_source:source,...(p?{point:p}:{})});
  }
  function scan(p) {
    if (model.terminal) return;
    model.lens=p;
    const w=model.state.world, left=Math.max(0,Math.floor((p[0]-80)/4)*4),right=Math.min(1000,Math.ceil((p[0]+w.sonar)/4)*4);
    let acquired=false;
    for(let x=left;x<=right;x+=4) {
      if(!model.survey.has(x)) {model.survey.set(x,center(w,x,model.physics.ms));acquired=true;}
    }
    // A scan is an information probe, never a steering input or a pass quota.
    // Retain the first measured outline; it is explicitly an old reference.
    if(acquired) record('scan',p,'pointer_sonar');
    draw();
  }
  function control(kind,p) {
    if (model.terminal || !model.physics.active) return;
    record(kind,p,model.interaction==='full'?'pen_drag':'height_click');
    if (kind!=='release') model.physics.target=p[1];
    if (!advanceForAction()) return;
    draw();
  }
  function launch() {
    sync(); if (model.terminal || model.physics.active) return;
    record('launch',null,'launch_button'); model.physics.launch();
    document.querySelector('#trace-v2-launch').disabled=true;
    model.helpers.setReadout('TRACE ACTIVE · KEEP THE PROBE BETWEEN THE GREEN WALLS','pending'); draw();
  }
  function payload() {
    const p=model.physics;
    return {mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      revision:model.state.revision,interaction_mode:model.interaction,events:model.events,final_t_ms:model.currentMs,
      completed:p.done&&!p.failed,final:{x:p.x,y:p.y,v:p.v,ms:p.ms,failed:p.failed,done:p.done}};
  }
  async function finish() {
    if (model.terminal) return;
    model.terminal=true; model.hold=null;
    document.querySelector('#trace-v2-launch').disabled=true;
    document.querySelector('#trace-v2-submit').disabled=true;
    model.helpers.setReadout(model.physics.failed || (!model.physics.done?'INCOMPLETE TRACE':'CERTIFYING TRACE'), 'pending');
    draw();
    try {
      const response=await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
      const outcome=await response.json(); model.verdict=outcome.passed===true?'PASS':'FAIL';
      model.helpers.setReadout(model.verdict==='PASS'?'PASS · EXIT REACHED':`FAIL · ${model.physics.failed || 'INCOMPLETE TRACE'} · EPISODE ENDED`,outcome.passed?'passed':'error');
      document.querySelector('.trace-v2-verdict').textContent=model.verdict;
      document.querySelector('.trace-v2').dataset.verdict=model.verdict.toLowerCase(); draw();
    } catch (e) {
      model.verdict='ERROR'; document.querySelector('.trace-v2-verdict').textContent='VERIFIER ERROR';
      model.helpers.setReadout('VERIFIER ERROR · '+e.message,'error');
    }
  }
  function path(c,w,left,right,ms,side) {
    c.beginPath();
    const first=Math.max(0,Math.floor(left/4)*4),last=Math.min(1000,Math.ceil(right/4)*4);
    let joined=false;
    for(let x=first;x<=last;x+=4) {
      if(!model.survey.has(x)) {joined=false;continue;}
      const y=center(w,x,ms)+side*w.radius;
      if(!joined)c.moveTo(x,y);else c.lineTo(x,y);joined=true;
    }
  }
  function draw() {
    if (!model) return;
    const c=document.querySelector('#trace-v2-scope').getContext('2d'),p=model.physics,w=model.state.world;
    const t=p.ms, active=p.active;
    c.fillStyle='#031e20';c.fillRect(0,0,1000,480);
    c.lineWidth=1; c.strokeStyle='#1c4342';
    for(let x=0;x<=1000;x+=50){c.beginPath();c.moveTo(x,0);c.lineTo(x,480);c.stroke();}
    for(let y=0;y<=480;y+=40){c.beginPath();c.moveTo(0,y);c.lineTo(1000,y);c.stroke();}
    // The amber record preserves acquired information outside the live lens.
    // It is not a wall/collider: green sonar below is the current geometry.
    c.strokeStyle='#c7964e';c.lineWidth=1;c.setLineDash([3,5]);
    for(const side of [-1,1]) {
      c.beginPath();let joined=false;
      for(let x=0;x<=1000;x+=4) {
        if(!model.survey.has(x)) {joined=false;continue;}
        const y=model.survey.get(x)+side*w.radius;
        if(!joined)c.moveTo(x,y);else c.lineTo(x,y);joined=true;
      }
      c.stroke();
    }
    c.setLineDash([]);
    const lx=active?p.x:model.lens[0],left=Math.max(0,lx-80),right=Math.min(1000,lx+w.sonar);
    // Recent wall echoes are historical positions, never alternate colliders.
    for (const ago of [600,400,200,0]) {
      c.strokeStyle=ago?'rgba(67,225,194,.18)':'#6dffce';c.lineWidth=ago?1:3;
      for (const side of [-1,1]) {path(c,w,left,right,Math.max(0,t-ago),side);c.stroke();}
    }
    c.fillStyle='rgba(99,255,210,.045)';
    for(let x=Math.max(0,Math.floor(left/4)*4);x<Math.min(1000,Math.ceil(right/4)*4);x+=4) {
      if(!model.survey.has(x)||!model.survey.has(x+4))continue;
      c.beginPath();c.moveTo(x,center(w,x,t)-w.radius);c.lineTo(x+4,center(w,x+4,t)-w.radius);
      c.lineTo(x+4,center(w,x+4,t)+w.radius);c.lineTo(x,center(w,x,t)+w.radius);c.closePath();c.fill();
    }
    // Arrows show measured wall motion. The long echoes make direction visible.
    c.strokeStyle='#82b7a9';c.lineWidth=2;
    for (let x=Math.ceil(left/65)*65;x<right;x+=65) {
      if(!model.survey.has(Math.round(x/4)*4))continue;
      const y=center(w,x,t),v=(y-center(w,x,Math.max(0,t-300)))/.3;
      c.beginPath();c.moveTo(x,y);c.lineTo(x,y+v*.5);c.stroke();
      if(Math.abs(v)>3){c.beginPath();c.moveTo(x-4,y+v*.5-Math.sign(v)*5);c.lineTo(x,y+v*.5);c.lineTo(x+4,y+v*.5-Math.sign(v)*5);c.stroke();}
    }
    // Lit launch and exit rings move with their actual channel cross-sections.
    for (const [x,label] of [[70,'START'],[930,'EXIT']]) {
      const y=center(w,x,t);c.strokeStyle='#f6d280';c.lineWidth=2;c.beginPath();c.arc(x,y,19,0,Math.PI*2);c.stroke();
      c.font='bold 13px monospace';c.fillStyle='#f6d280';c.textAlign='center';c.fillText(label,x,y-28);
    }
    c.strokeStyle='#e7e6c3';c.setLineDash([5,5]);c.lineWidth=1;
    c.beginPath();c.moveTo(p.x-30,p.target);c.lineTo(p.x+35,p.target);c.stroke();c.setLineDash([]);
    c.strokeStyle='#efffd7';c.lineWidth=3;c.beginPath();c.moveTo(p.x,p.y);c.lineTo(p.x,p.y+p.v*.22);c.stroke();
    c.fillStyle=p.failed?'#ff665f':'#eaffb2';c.shadowColor=c.fillStyle;c.shadowBlur=15;c.beginPath();c.arc(p.x,p.y,w.probe_radius,0,Math.PI*2);c.fill();c.shadowBlur=0;
    if(!active){c.strokeStyle='#ffdc8880';c.beginPath();c.arc(lx,model.lens[1],18,0,Math.PI*2);c.stroke();}
    c.fillStyle='#90b7ad';c.textAlign='left';c.font='12px monospace';c.fillText(active?'FIXED-STEP → / SONAR FOLLOWS PROBE':'PREVIEW / MOVE POINTER TO REVEAL THE HIDDEN CHANNEL',20,26);
    c.fillText('GREEN = WALL NOW · DIM GREEN = RECENT ECHO · AMBER DASHES = OLD SCAN',20,460);
    const current=wind(w,t);
    document.querySelector('#trace-v2-distance').textContent=`${Math.round((p.x-70)/860*100)}%`;
    document.querySelector('#trace-v2-wind').textContent=current>3?'↓':current< -3?'↑':'·';
    document.querySelector('#trace-v2-current').style.height=`${8+Math.abs(current)*1.4}px`;
    document.querySelector('#trace-v2-status').textContent=p.failed?p.failed:p.done?'EXIT REACHED':model.terminal?'TRACE ENDED':active?'TRACE IN PROGRESS':'LISTEN BEFORE LAUNCH';
  }
  async function render(state,helpers) {
    document.body.dataset.mechanic='trace-shape-v2';
    model={state,helpers,interaction:state.control_condition?.interaction||'full',physics:new Physics(state.world),
      events:[],survey:new Map(),currentMs:0,hold:null,lens:[70,240],terminal:false,verdict:''};
    window.traceShapeV3Model=model;
    helpers.app.innerHTML=`<section class="trace-v2" data-verdict=""><header><div><span>BCO / EXPERIMENT 02</span><h1>Blind Corridor Oscilloscope V3</h1></div><div class="trace-v2-badge">SONAR<br><b>FIXED-STEP CHANNEL</b></div></header>
      <main><div class="trace-v2-screen"><canvas id="trace-v2-scope" width="1000" height="480"></canvas><div class="trace-v2-verdict"></div></div>
      <aside><span>PHOSPHOR CONTROL</span><h2>Listen.<br>Trace.<br>Correct.</h2><p>Move the pointer across the scope to reveal concealed channel sections before launch or during flight. Hover scans do not steer. Amber dashes retain the first scan.</p><p>${model.interaction==='full'?'Drag on the scope to steer the control pen.':'Click a height on the scope to steer the control pen.'} Each steering control advances one fixed 240 ms slice; the probe has inertia and the walls/current update in that slice. Waiting keeps the current state stable.</p><div class="trace-v2-meters"><label>TRACE <b id="trace-v2-distance">0%</b></label><label>CURRENT <b id="trace-v2-wind">·</b><i id="trace-v2-current"></i></label></div><p>Green walls and fading echoes follow the probe through scanned sections. They keep deforming after each control. Touching a wall ends the trace.</p><button id="trace-v2-launch">LAUNCH PROBE →</button></aside></main>
      <footer><div><b id="trace-v2-status">LISTEN BEFORE LAUNCH</b><div class="readout">MOVE POINTER TO SCAN · FIRST FAILED TRACE ENDS EPISODE · 180 SECOND LIMIT</div></div><button id="trace-v2-submit">CERTIFY TRACE</button></footer></section>`;
    const canvas=document.querySelector('#trace-v2-scope');
    canvas.addEventListener('pointerdown',e=>{
      if(e.button!==0||model.terminal)return; const p=point(e);scan(p);
      if(model.terminal||!model.physics.active)return;
      if(model.interaction==='full'){model.hold=e.pointerId;canvas.setPointerCapture(e.pointerId);control('hold',p);}
      else control('steer',p);e.preventDefault();
    });
    canvas.addEventListener('pointermove',e=>{
      if(model.terminal)return;const p=point(e);scan(p);
      if(model.physics.active&&model.interaction==='full'&&model.hold===e.pointerId)control('steer',p);
    });
    function release(e){if(model.hold!==e.pointerId)return;control('release',point(e));model.hold=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);}
    canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);
    canvas.addEventListener('lostpointercapture',e=>{if(model.hold===e.pointerId){control('release',[500,model.physics.target]);model.hold=null;}});
    document.querySelector('#trace-v2-launch').addEventListener('click',launch);
    document.querySelector('#trace-v2-submit').addEventListener('click',()=>{sync();finish();});
    // No autonomous animation loop: task time advances only after an
    // existing steering control, so waiting preserves the current state.
    draw();
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.trace_shape_without_walls_v3_nonrealtime={rootSelector:'.trace-v2',render};
})();
