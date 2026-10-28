(() => {
  'use strict';
  let model, raf;
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  function noise(seed,n) {
    let x=(seed ^ Math.imul(n+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function target(state,ms) {
    const u=Math.max(0,ms)/state.motion.span_ms,k=Math.floor(u),f=u-k,s=f*f*(3-2*f),n=Math.min(k,state.motion.waypoints.length-2);
    return state.motion.waypoints[n].map((a,i)=>a*(1-s)+state.motion.waypoints[n+1][i]*s);
  }
  function transform(point,pose) {
    let [x,y,z]=point;
    const [yaw,pitch]=pose.slice(3);
    [x,z]=[x*Math.cos(yaw)+z*Math.sin(yaw),-x*Math.sin(yaw)+z*Math.cos(yaw)];
    [y,z]=[y*Math.cos(pitch)-z*Math.sin(pitch),y*Math.sin(pitch)+z*Math.cos(pitch)];
    return [x+pose[0],y+pose[1],z+pose[2]];
  }
  const axes=[[0,1,2],[2,1,0],[0,2,1]];
  function errors(state,pose,goal) {
    const e=[0,0,0];
    for(const rod of state.rods) for(const p of rod.ends) {
      const a=transform(p,pose),b=transform(p,goal);
      axes.forEach(([u,v],i)=>e[i]=Math.max(e[i],Math.hypot(a[u]-b[u],a[v]-b[v])));
    }
    return e;
  }
  function step() {
    const p=model.state.parameters;
    const dt=model.state.timing_rule.action_tick_ms/1000;
    model.t+=model.state.timing_rule.action_tick_ms;
    for(let i=0;i<5;i++) {
      const a=clamp((model.command[i]-model.pose[i])*64-model.velocity[i]*16,-p.servo_acceleration,p.servo_acceleration);
      model.velocity[i]=clamp(model.velocity[i]+a*dt,-p.servo_speed,p.servo_speed);
    }
    const speed=model.velocity.reduce((s,v)=>s+Math.abs(v),0);
    if(speed>p.shared_speed) model.velocity=model.velocity.map(v=>v*p.shared_speed/speed);
    model.pose=model.pose.map((v,i)=>clamp(v+model.velocity[i]*dt,-model.state.limits[i],model.state.limits[i]));
    model.goal=target(model.state,model.startTime===null ? 0 : model.t-model.startTime);
    model.errors=errors(model.state,model.pose,model.goal);
    if(model.phase==='active') {
      const fit=Math.max(...model.errors)<=p.tolerance;
      model.fusion=clamp(model.fusion+(fit ? dt : -dt*p.leak_rate),0,p.fusion_seconds);
      if(model.fusion>=p.fusion_seconds-1e-8) model.phase='fused';
      else if(model.t-model.startTime>=model.state.run_limit_ms) model.phase='failed';
    }
  }
  function advanceAction() {
    if(!model || model.terminal || ['fused','failed'].includes(model.phase)) return false;
    step();
    if(model.phase==='failed') {
      record('timeout',{input_source:'clock'});
      finish();
      return false;
    }
    return true;
  }
  function record(kind,extra={}) {
    model.events.push({sequence:model.events.length+1,kind,t_ms:model.t,...extra});
  }
  async function finish() {
    if(model.terminal) return;
    model.terminal=true;
    model.payload={mechanic_id:model.state.mechanic_id,revision:model.state.revision,task_id:model.state.task_id,
      challenge_id:model.state.challenge_id,interaction_mode:model.interaction,events:model.events,
      completed:model.phase==='fused',phase:model.phase,final_t_ms:model.t,fusion_seconds:model.fusion};
    draw();
    model.helpers.setReadout(model.phase==='fused' ? 'VERIFYING CASTING…' : 'FAIL · CASTING ENDED',model.phase==='fused' ? 'pending' : 'error');
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(model.payload)});
      model.grade=await response.json();
      model.helpers.setReadout(model.grade.passed ? 'PASS · THREE DIES FUSED' : 'FAIL · CASTING ENDED',model.grade.passed ? 'passed' : 'error');
      draw();
    } catch(error) { model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`,'error'); }
  }
  const cx=i=>1019+model.command[i]/model.state.limits[i]*69;
  const point=e=>{const r=model.canvas.getBoundingClientRect();return [(e.clientX-r.x)*1120/r.width,(e.clientY-r.y)*570/r.height];};
  function onDown(e) {
    if(e.button!==0 || model.terminal || ['fused','failed'].includes(model.phase)) return;
    const q=point(e);
    const axis=Math.round((q[1]-148)/69);
    if(axis<0 || axis>=model.state.parameters.active_axes || Math.abs(q[1]-(148+axis*69))>23 || q[0]<938 || q[0]>1100) return;
    if(model.interaction==='full') {
      if(Math.abs(q[0]-cx(axis))>18 || model.held!==null) return;
      if(!advanceAction() || model.terminal || ['fused','failed'].includes(model.phase)) return;
      e.preventDefault(); model.canvas.setPointerCapture(e.pointerId);model.held=axis;
      record('drag_start',{axis,point:q,input_source:'gantry_drag'});
    } else {
      if(!advanceAction() || model.terminal || ['fused','failed'].includes(model.phase)) return;
      model.command[axis]=(clamp(q[0],950,1088)-1019)/69*model.state.limits[axis];
      record('set',{axis,point:q,input_source:'rail_click'});
    }
    draw();
  }
  function drag(e,end=false) {
    if(model.held===null || model.terminal) return;
    advanceAction();
    // Completion closes the physical control opportunity. A late pointerup
    // releases capture but cannot alter the fused casting or its transcript.
    if(['fused','failed'].includes(model.phase)) {model.held=null;return;}
    const axis=model.held,q=point(e);
    q[0]=clamp(q[0],950,1088);q[1]=148+axis*69;
    model.command[axis]=(q[0]-1019)/69*model.state.limits[axis];
    record(end ? 'drag_end' : 'drag_move',{axis,point:q,input_source:'gantry_drag'});
    if(end) {model.held=null;if(model.canvas.hasPointerCapture(e.pointerId)) model.canvas.releasePointerCapture(e.pointerId);}
    draw();
  }
  const viewPoint=(p,view)=>{const [u,v]=axes[view];return [166+view*302+p[u]*48,253-p[v]*48];};
  function text(c,s,x,y,color='#c8d2dd',size=13) {c.fillStyle=color;c.font=`${size}px ui-monospace, monospace`;c.fillText(s,x,y);}
  function sculpture(c,pose,view,ghost) {
    const items=[];
    for(const rod of model.state.rods) {
      const a=transform(rod.ends[0],pose),b=transform(rod.ends[1],pose);
      for(let i=0;i<16;i++) {
        const p=a.map((v,j)=>v+(b[j]-v)*i/16),q=a.map((v,j)=>v+(b[j]-v)*(i+1)/16);
        items.push({rod,p,q,depth:(p[axes[view][2]]+q[axes[view][2]])/2});
      }
    }
    items.sort((a,b)=>b.depth-a.depth);
    c.lineCap='round';
    for(const item of items) {
      const a=viewPoint(item.p,view),b=viewPoint(item.q,view);
      c.beginPath();c.moveTo(...a);c.lineTo(...b);
      c.strokeStyle=ghost ? item.rod.color+'38' : item.rod.color;
      c.lineWidth=ghost ? 12 : 6.7;c.stroke();
    }
    // Receiver rings are intentionally overlaid: occlusion in the sculpture
    // never hides a required acceptance boundary.
    for(const rod of model.state.rods) for(const end of rod.ends) {
      const [x,y]=viewPoint(transform(end,pose),view);
      c.beginPath();c.arc(x,y,ghost ? model.state.parameters.tolerance*48 : 3.3,0,Math.PI*2);
      if(ghost) {c.strokeStyle=rod.color;c.lineWidth=1.8;c.stroke();}
      else {c.fillStyle='#071019';c.fill();c.strokeStyle=rod.color;c.lineWidth=1.4;c.stroke();}
    }
  }
  function draw() {
    if(!model) return;
    const c=model.canvas.getContext('2d'),p=model.state.parameters;
    c.fillStyle='#0a1420';c.fillRect(0,0,1120,570);
    text(c,'THREE MOVING DIES / ONE RIGID CASTING',26,34,'#f2ca7a',16);
    text(c,model.phase==='prepare' ? 'ALIGN BEFORE IGNITION · EACH CONTROL STEP IS FIXED 20MS' : 'DIES ADVANCE ON EACH DELIBERATE CONTROL STEP',26,59,'#8da5bb',12);
    for(let view=0;view<3;view++) {
      const x=22+view*302;
      c.fillStyle='#101f2e';c.fillRect(x,85,288,338);
      c.strokeStyle='#294051';c.strokeRect(x,85,288,338);
      c.strokeStyle='#1d3445';c.lineWidth=1;
      for(let d=-2;d<=2;d++) {
        c.beginPath();c.moveTo(x+8,253+d*48);c.lineTo(x+280,253+d*48);c.stroke();
        c.beginPath();c.moveTo(166+view*302+d*48,122);c.lineTo(166+view*302+d*48,395);c.stroke();
      }
      text(c,['FRONT · X/Y','SIDE · Z/Y','TOP · X/Z'][view],x+14,110,'#e2e9ef',15);
      // Recent, fading motion of one fixed sculpture point is actual target
      // evolution, not an unrelated animation. No future path is displayed.
      if(model.phase!=='prepare') {
        const end=model.state.rods[0].ends[0],age=model.t-model.startTime;
        c.beginPath();
        for(let k=16;k>=0;k--) {
          const q=viewPoint(transform(end,target(model.state,Math.max(0,age-k*50))),view);
          if(k===16)c.moveTo(...q);else c.lineTo(...q);
        }
        c.strokeStyle='#f5dca366';c.lineWidth=2;c.stroke();
      }
      sculpture(c,model.goal,view,true);sculpture(c,model.pose,view,false);
      const fit=model.errors[view]<=p.tolerance;
      text(c,fit ? 'DIE FIT' : 'TIPS OUTSIDE RINGS',x+14,410,fit ? '#81ddbc' : '#e2a087',12);
    }
    text(c,'GANTRY',951,104,'#e5d3a4',16);
    const names=['X / SLIDE','Y / LIFT','Z / DEPTH','YAW / TURN','PITCH / TILT'];
    for(let i=0;i<5;i++) {
      const y=148+i*69,active=i<p.active_axes;
      text(c,names[i],947,y-23,active ? '#c4d6e5' : '#4c6070',12);
      c.lineCap='round';c.strokeStyle=active ? '#476175' : '#20313f';c.lineWidth=7;
      c.beginPath();c.moveTo(950,y);c.lineTo(1088,y);c.stroke();
      if(active) {
        const x=cx(i);c.beginPath();c.arc(x,y,14,0,Math.PI*2);c.fillStyle=model.held===i ? '#edc678' : '#b8ccd9';c.fill();
        c.strokeStyle='#122433';c.lineWidth=2;c.stroke();
        const physical=1019+model.pose[i]/model.state.limits[i]*69;
        c.beginPath();c.moveTo(physical,y+18);c.lineTo(physical,y+24);c.strokeStyle='#6cdbce';c.lineWidth=3;c.stroke();
      }
    }
    text(c,'FUSION · ALL THREE DIES TOGETHER',30,466,'#e5d3a4',14);
    c.fillStyle='#243749';c.fillRect(30,482,852,22);
    c.fillStyle='#79d8ba';c.fillRect(30,482,852*model.fusion/p.fusion_seconds,22);
    text(c,`${Math.round(model.fusion/p.fusion_seconds*100)}%`,895,499,'#92ddc4',14);
    text(c,model.interaction==='full' ? 'DRAG THE ROUND GANTRY HANDLES · WAITING DOES NOT MOVE THE DIES' : 'CLICK A GANTRY RAIL TO SET ITS TARGET · WAITING DOES NOT MOVE THE DIES',30,539,'#a4b8c9',12);
    if(model.phase==='fused' || model.phase==='failed') {
      c.fillStyle='#07131de8';c.fillRect(208,198,698,127);
      text(c,model.phase==='fused' ? 'CASTING FUSED' : 'CASTING FAILED',278,252,model.phase==='fused' ? '#91e6bf' : '#f39b88',32);
      text(c,model.phase==='fused' ? 'All three projection dies matched together. Certify below.' : 'This attempt has ended. It cannot be reset or repaired.',253,289,'#d3dfe7',14);
    }
    model.startButton.disabled=model.phase!=='prepare';
    model.submitButton.textContent=model.phase==='fused' ? 'CERTIFY CASTING' : 'END & SUBMIT';
    model.submitButton.disabled=model.terminal;
  }
  function animate(){draw();raf=requestAnimationFrame(animate);}
  async function render(state,helpers) {
    cancelAnimationFrame(raf);
    document.body.dataset.mechanic='hologram_silhouette_foundry_nonrealtime';
    helpers.app.innerHTML='<section class="hsf2-shell"><header><div><small>OPTICAL WORKSHOP / LIVE CASTING</small><h1>Hologram Silhouette Foundry V2</h1></div><span class="hsf2-badge">THREE VIEWS · ONE WORLD</span></header><canvas class="hsf2-canvas" width="1120" height="570"></canvas><footer><div class="readout">Match colored tip centers to their moving rings. Fit builds fusion; lost fit drains it.</div><button class="hsf2-start">IGNITE FOUNDRY</button><button class="hsf2-submit">END & SUBMIT</button></footer></section>';
    const interaction=state.control_condition.interaction;
    model={state,helpers,interaction,canvas:document.querySelector('.hsf2-canvas'),startButton:document.querySelector('.hsf2-start'),submitButton:document.querySelector('.hsf2-submit'),
      pose:[...state.initial_pose],command:[...state.initial_pose],velocity:[0,0,0,0,0],events:[],t:0,startTime:null,fusion:0,phase:'prepare',held:null,terminal:false,goal:target(state,0)};
    model.errors=errors(state,model.pose,model.goal);
    window.hologramSilhouetteFoundryNonRealtimeModel=model;
    model.canvas.addEventListener('pointerdown',onDown);
    model.canvas.addEventListener('pointermove',e=>drag(e));
    model.canvas.addEventListener('pointerup',e=>drag(e,true));
    model.canvas.addEventListener('pointercancel',e=>drag(e,true));
    model.startButton.addEventListener('click',()=>{if(model.phase!=='prepare'||model.held!==null||model.terminal)return;record('ignite',{input_source:'button'});model.startTime=model.t;model.phase='active';draw();});
    model.submitButton.addEventListener('click',()=>{if(model.terminal)return;advanceAction();if(model.terminal)return;record('submit',{input_source:'button'});if(model.phase!=='fused')model.phase='failed';finish();});
    draw();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.hologram_silhouette_foundry_nonrealtime={rootSelector:'.hsf2-shell',render};
  // Pure equations exposed for cross-language tests; solutions still use
  // ordinary input. This does not supply privileged actions to an agent.
  window.HologramSilhouetteFoundryNonRealtimeMath={noise,target,transform,errors};
})();
