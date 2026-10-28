(() => {
  'use strict';
  const colors=['#f9b766','#69d9dd','#c29af3'];
  const names=['OUTER · ROLL','MIDDLE · PITCH','INNER · YAW'];
  let model=null, raf=0;
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  const clean=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function noise(seed,index) {
    let x=(seed^Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function wind(c,axis,ms) {
    if(axis>=c.parameters.axes)return 0;
    const u=Math.max(0,ms)/c.parameters.gust_span_ms,n=Math.floor(u),f=u-n;
    const a=noise(c.wind_seeds[axis],n),b=noise(c.wind_seeds[axis],n+1);
    return c.parameters.gust_rate*(a+(b-a)*f*f*(3-2*f));
  }
  class Physics {
    constructor(c) {
      this.c=c;this.x=[...c.initial];this.v=[...c.initial_velocity];this.u=[0,0,0];
      this.tick=0;this.dwell=0;this.best=0;this.started=false;this.solved=false;this.failed='';this.history=[];
    }
    advance(target) {
      if(!this.started)return;
      const p=this.c.parameters;
      while(this.tick<target&&!this.solved&&!this.failed) {
        this.tick++;
        const ms=this.tick*this.c.tick_ms;
        for(let i=0;i<p.axes;i++) {
          const drive=this.c.motor_rate*this.c.matrix[i].reduce((sum,a,j)=>sum+a*this.u[j],0);
          this.v[i]+=(drive+wind(this.c,i,ms)-this.v[i])*.01/p.response_s;
          this.x[i]+=this.v[i]*.01;
          if(Math.abs(this.x[i])>=this.c.stop_deg) {this.x[i]=Math.sign(this.x[i])*this.c.stop_deg;this.v[i]=0;}
        }
        const aligned=this.x.slice(0,p.axes).every((a,i)=>Math.abs(a)<=p.tolerance_deg&&Math.abs(this.v[i])<=p.speed_tolerance);
        this.dwell=aligned?this.dwell+this.c.tick_ms:0;this.best=Math.max(this.best,this.dwell);
        if(this.dwell>=this.c.hold_ms)this.solved=true;
        else if(ms>=this.c.run_limit_ms)this.failed='Alignment run expired.';
        if(this.tick%5===0) {
          this.history.push({ms,x:[...this.x],v:[...this.v]});
          while(this.history.length&&this.history[0].ms<ms-this.c.history_ms)this.history.shift();
        }
      }
    }
    snapshot() {return {tick:this.tick,angles:[...this.x],velocity:[...this.v],drive:[...this.u],
      dwell_ms:this.dwell,best_ms:this.best,started:this.started,solved:this.solved,failed:this.failed};}
    advanceAfterAction() {
      const stepMs=this.c.action_step_ms;
      if(!Number.isInteger(stepMs)||stepMs<=0||stepMs%this.c.tick_ms!==0)throw new Error('invalid action step');
      this.advance(this.tick+stepMs/this.c.tick_ms);
    }
  }
  function fullHandle(axis,value) {
    const phi=value*110*Math.PI/180;return [150+axis*300+60*Math.sin(phi),76-60*Math.cos(phi)];
  }
  function pointerValue(axis,p) {return clamp(Math.atan2(p[0]-(150+axis*300),76-p[1])*180/Math.PI/110,-1,1);}
  function record(kind,details={}) {model.events.push({sequence:model.events.length+1,kind,tick:model.sim.tick,...details});}
  function sync() {
    if(!model||model.submitting||model.terminal)return;
    if(model.sim.solved||model.sim.failed) {
      // Terminal physics ends a captured gesture without waiting for a mouse
      // release. The world must not hide or postpone failure while held.
      if(model.hold) {
        const captured=model.hold;model.hold=null;
        record('capture_cancel',{axis:captured.axis,input_source:'physical_termination'});
        try{document.querySelector('#rw-controls').releasePointerCapture(captured.pointer);}catch(_){}
      }
      void finish();
    }
  }
  function transform(point,angles) {
    let [x,y,z]=point;
    const [a,b,c]=angles.map(v=>v*Math.PI/180);
    [x,z]=[x*Math.cos(c)+z*Math.sin(c),-x*Math.sin(c)+z*Math.cos(c)];
    [y,z]=[y*Math.cos(b)-z*Math.sin(b),y*Math.sin(b)+z*Math.cos(b)];
    return [x*Math.cos(a)-y*Math.sin(a),x*Math.sin(a)+y*Math.cos(a),z];
  }
  function project(p,view) {
    if(view==='front')return [p[0],-p[1],p[2]];
    if(view==='side')return [p[2],-p[1],-p[0]];
    if(view==='top')return [p[0],p[2],p[1]];
    return [p[0]*.82+p[2]*.57,-p[1]*.92+p[2]*.28-p[0]*.16,p[2]*.82-p[0]*.57];
  }
  function line(ctx,points,angles,view,cx,cy,scale,color,width=3,dash=[]) {
    ctx.beginPath();points.forEach((p,i)=>{const q=project(transform(p,angles),view);if(!i)ctx.moveTo(cx+q[0]*scale,cy+q[1]*scale);else ctx.lineTo(cx+q[0]*scale,cy+q[1]*scale);});
    ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);
  }
  function sculpture(ctx,angles,view,cx,cy,scale,ghost=false) {
    const s=model.state.gimbal.sculpture,h=s.mast_height,w=s.wing_width;
    const strokes=[[[0,-42,0],[0,h,0]], [[-w,15,0],[0,34,24],[w,15,0]],
      [[-28,-42,-20],[28,-42,-20],[28,-42,20],[-28,-42,20],[-28,-42,-20]],
      [[0,34,24],[0,60,36]], [[0,h,0],[-16,h-23,8],[16,h-23,8],[0,h,0]]];
    if(s.crown==='fork')strokes.push([[-18,h+9,0],[0,h-8,0],[18,h+9,0]]);
    if(s.crown==='lantern')strokes.push([[-15,h+12,-10],[15,h+12,-10],[15,h-12,-10],[-15,h-12,-10],[-15,h+12,-10]]);
    for(const points of strokes)line(ctx,points,angles,view,cx,cy,scale,ghost?'#98cdb64d':'#ffe6a1',ghost?1.5:4,ghost?[4,5]:[]);
    if(!ghost) {
      const p=project(transform([0,h,0],angles),view);ctx.fillStyle='#fff6cf';ctx.beginPath();ctx.arc(cx+p[0]*scale,cy+p[1]*scale,5,0,Math.PI*2);ctx.fill();
    }
  }
  function drawWorld() {
    const ctx=document.querySelector('#rw-world')?.getContext('2d');if(!ctx)return;
    const gradient=ctx.createRadialGradient(280,190,20,300,240,530);gradient.addColorStop(0,'#1e393f');gradient.addColorStop(1,'#071316');ctx.fillStyle=gradient;ctx.fillRect(0,0,900,340);
    ctx.strokeStyle='#73b8bd16';ctx.lineWidth=1;
    for(let x=0;x<900;x+=30){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,340);ctx.stroke();}
    for(let y=10;y<340;y+=30){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(900,y);ctx.stroke();}
    const a=model.sim.x;
    // Each ring lies in its actual rotated plane; no screen-space pseudo projection.
    for(let ring=0;ring<3;ring++) {
      const r=ring===0?148:ring===1?125:103,points=[];
      for(let j=0;j<=100;j++){const t=j*Math.PI/50;points.push(ring===0?[r*Math.cos(t),r*Math.sin(t),0]:ring===1?[0,r*Math.cos(t),r*Math.sin(t)]:[r*Math.cos(t),0,r*Math.sin(t)]);}
      const angle=[a[0],ring>0?a[1]:0,ring>1?a[2]:0];
      line(ctx,points,angle,'iso',275,191,1,colors[ring]+'88',3);
    }
    sculpture(ctx,[0,0,0],'iso',275,191,1.15,true);sculpture(ctx,a,'iso',275,191,1.15);
    ctx.fillStyle='#78a8ac';ctx.font='12px monospace';ctx.fillText('WORLD PLUMB / GHOST = TARGET',30,28);
    ['front','side','top'].forEach((view,i)=>{
      const cx=602+i*116,cy=203;
      ctx.fillStyle='#0b2025';ctx.fillRect(cx-54,75,108,214);ctx.strokeStyle='#52848a55';ctx.strokeRect(cx-54,75,108,214);
      ctx.fillStyle='#b4d8d4';ctx.font='11px monospace';ctx.textAlign='center';ctx.fillText(view.toUpperCase(),cx,99);
      sculpture(ctx,[0,0,0],view,cx,cy,.48,true);sculpture(ctx,a,view,cx,cy,.48);
    });ctx.textAlign='left';
    ctx.fillStyle='#a7c5c0';ctx.font='13px monospace';ctx.fillText('STEER THE RINGS. KEEP THE INNER SCULPTURE UPRIGHT.',30,320);
  }
  function drawGauges() {
    const ctx=document.querySelector('#rw-gauges')?.getContext('2d');if(!ctx)return;
    ctx.clearRect(0,0,900,96);
    for(let i=0;i<3;i++) {
      const x=i*300+16,p=model.state.gimbal.parameters,active=i<p.axes;
      ctx.globalAlpha=active?1:.28;ctx.fillStyle=colors[i];ctx.font='12px monospace';ctx.fillText(names[i],x,16);
      ctx.fillStyle='#152d32';ctx.fillRect(x,25,268,30);
      const scale=268/300;ctx.fillStyle='#70dbad44';ctx.fillRect(x+134-p.tolerance_deg*scale,25,p.tolerance_deg*2*scale,30);
      ctx.strokeStyle='#b4e1ce';ctx.beginPath();ctx.moveTo(x+134,25);ctx.lineTo(x+134,55);ctx.stroke();
      for(const sample of model.sim.history){ctx.fillStyle=colors[i]+'44';ctx.beginPath();ctx.arc(x+134+sample.x[i]*scale,40,3,0,Math.PI*2);ctx.fill();}
      ctx.fillStyle=colors[i];ctx.beginPath();ctx.arc(x+134+model.sim.x[i]*scale,40,6,0,Math.PI*2);ctx.fill();
      const v=model.sim.v[i];ctx.strokeStyle=colors[i];ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x+134,65);ctx.lineTo(x+134+clamp(v,-65,65),65);ctx.stroke();
      ctx.fillStyle='#ccdfd8';ctx.font='12px monospace';ctx.fillText(active?`${model.sim.x[i].toFixed(1)}°   ${v.toFixed(1)}°/s   SAFE ±${p.tolerance_deg}° / ${p.speed_tolerance}°/s`:'FIXED AXIS',x,89);
    }ctx.globalAlpha=1;
  }
  function drawControls() {
    const ctx=document.querySelector('#rw-controls')?.getContext('2d');if(!ctx)return;
    ctx.clearRect(0,0,900,152);
    for(let i=0;i<3;i++) {
      const active=i<model.state.gimbal.parameters.axes,cx=150+i*300,u=model.sim.u[i];ctx.globalAlpha=active?1:.25;
      ctx.strokeStyle=colors[i];ctx.fillStyle=colors[i];ctx.lineWidth=2;
      if(model.interaction==='full') {
        ctx.beginPath();ctx.arc(cx,76,60,(-200)*Math.PI/180,20*Math.PI/180);ctx.stroke();
        for(let j=-1;j<=1;j+=.25) {const [x,y]=fullHandle(i,j);ctx.beginPath();ctx.arc(x,y,2,0,Math.PI*2);ctx.fill();}
        const [x,y]=fullHandle(i,u);ctx.beginPath();ctx.moveTo(cx,76);ctx.lineTo(x,y);ctx.stroke();ctx.fillStyle='#1c383d';ctx.beginPath();ctx.arc(x,y,19,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.fillStyle=colors[i];ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill();
      } else {
        ctx.fillStyle='#182e32';ctx.fillRect(cx-102,53,204,46);ctx.strokeRect(cx-102,53,204,46);
        ctx.fillStyle=colors[i];ctx.fillRect(cx+u*100-5,56,10,40);
        ctx.font='20px monospace';ctx.fillText('−',cx-92,84);ctx.fillText('+',cx+75,84);
      }
      ctx.textAlign='center';ctx.fillStyle=colors[i];
      // The actual motor wiring is engraved under a liftable gear cover.
      // Controls work with it closed; inspection reveals information only.
      ctx.fillStyle='#18363b';ctx.fillRect(cx-134,104,268,28);ctx.strokeStyle=colors[i];ctx.strokeRect(cx-134,104,268,28);
      ctx.fillStyle=colors[i];ctx.font='11px monospace';
      if(model.inspected[i]) {
        const column=model.state.gimbal.matrix.map(row=>row[i]);
        const signed=value=>`${value>0?'+':''}${Math.round(value*100)}%`;
        ctx.fillText(`+DIAL → ${['ROLL','PITCH','YAW'][i]} ${signed(column[i])}`,cx,115);
        const linked=column.map((value,j)=>j!==i&&value!==0?`${['ROLL','PITCH','YAW'][j]} ${signed(value)}`:null).filter(Boolean);
        ctx.fillText(linked.length?`ALSO ${linked.join(' / ')}`:'NO CROSS-AXIS GEAR',cx,128);
      } else {
        ctx.fillText(active?`GEAR COVER ${i+1} · LIFT TO INSPECT`:'FIXED AXIS',cx,122);
      }
      ctx.font='12px monospace';ctx.fillText(`DIAL ${i+1}   ${(u*65).toFixed(0)}°/s`,cx,148);ctx.textAlign='left';
    }ctx.globalAlpha=1;
  }
  function drawWind() {
    const canvas=document.querySelector('#rw-wind'),ctx=canvas?.getContext('2d');if(!ctx)return;
    ctx.fillStyle='#0d2227';ctx.fillRect(0,0,250,360);
    ctx.fillStyle='#c6ddd6';ctx.font='12px monospace';ctx.fillText('LOAD FORECAST',12,22);ctx.font='11px monospace';ctx.fillText('PAST 0.6s │ NOW │ NEXT 2s',12,44);
    const c=model.state.gimbal,ms=model.sim.tick*10;
    for(let i=0;i<3;i++) {
      const cy=99+i*102;ctx.globalAlpha=i<c.parameters.axes?1:.25;ctx.strokeStyle='#38575c';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(10,cy);ctx.lineTo(240,cy);ctx.stroke();
      const nowx=10+230*.6/2.6;ctx.strokeStyle='#d1e4da88';ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(nowx,cy-32);ctx.lineTo(nowx,cy+32);ctx.stroke();ctx.setLineDash([]);
      ctx.strokeStyle=colors[i];ctx.lineWidth=2;ctx.beginPath();
      for(let j=0;j<=115;j++){const t=ms-600+j*2600/115,x=10+j*2,y=cy-wind(c,i,Math.max(0,t))/c.parameters.gust_rate*31;if(j===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();
      ctx.fillStyle=colors[i];ctx.font='12px monospace';ctx.fillText(`${names[i]} / ${wind(c,i,ms).toFixed(1)}°/s`,12,cy+47);
    }ctx.globalAlpha=1;
  }
  function draw() {
    if(!model)return;drawWorld();drawGauges();drawControls();drawWind();
    const s=model.sim,bar=document.querySelector('#rw-charge');bar.style.width=`${s.dwell/s.c.hold_ms*100}%`;
    document.querySelector('#rw-charge-text').textContent=`PLUMB HOLD ${(s.dwell/1000).toFixed(1)} / 10.0s`;
    document.querySelector('#rw-clock').textContent=model.terminal&&model.verdict!=='pass'?(model.verdict==='error'?'UNAVAILABLE':'ENDED'):s.started?`${Math.max(0,(s.c.run_limit_ms-s.tick*10)/1000).toFixed(1)}s`:'READY';
    document.querySelector('#rw-begin').disabled=s.started||model.terminal||model.submitting;
    document.querySelector('#rw-certify').disabled=model.terminal||model.submitting;
  }
  function canvasPoint(e) {const r=e.currentTarget.getBoundingClientRect();return [clamp((e.clientX-r.x)*900/r.width,0,900),clamp((e.clientY-r.y)*152/r.height,0,152)];}
  function down(e) {
    if(!model||model.terminal||model.submitting||model.hold||e.button!==0)return;
    sync();if(model.sim.solved||model.sim.failed)return;
    const p=canvasPoint(e),axis=clamp(Math.floor(p[0]/300),0,2);
    if(axis>=model.state.gimbal.parameters.axes)return;
    if(p[0]>=16+axis*300&&p[0]<=284+axis*300&&p[1]>=104&&p[1]<=132) {
      if(!model.inspected[axis]) {
        model.inspected[axis]=true;record('inspect_motor',{axis,point:p,input_source:'gear_cover'});
        model.helpers.setReadout(`MOTOR ${axis+1} WINDING EXPOSED · +DIAL EFFECTS SHOWN`,'pending');
      }
      e.preventDefault();draw();return;
    }
    if(model.interaction==='simplified') {
      if(p[0]<48+axis*300||p[0]>252+axis*300||p[1]<53||p[1]>99)return;
      model.sim.u[axis]=clamp((p[0]-(150+axis*300))/100,-1,1);record('drive_click',{axis,point:p,input_source:'motor_rail'});model.sim.advanceAfterAction();
    } else {
      if(Math.hypot(...p.map((v,i)=>v-fullHandle(axis,model.sim.u[axis])[i]))>20)return;
      model.hold={axis,pointer:e.pointerId};e.currentTarget.setPointerCapture(e.pointerId);record('drive_down',{axis,point:p,input_source:'handwheel_drag'});
    }e.preventDefault();draw();
  }
  function move(e) {
    if(!model?.hold||model.hold.pointer!==e.pointerId||model.terminal||model.submitting)return;
    sync();if(model.sim.solved||model.sim.failed)return;
    const p=canvasPoint(e),axis=model.hold.axis;
    model.sim.u[axis]=pointerValue(axis,p);record('drive_move',{axis,point:p,input_source:'handwheel_drag'});model.sim.advanceAfterAction();e.preventDefault();draw();
  }
  function up(e) {
    if(!model?.hold||model.hold.pointer!==e.pointerId||model.terminal||model.submitting)return;
    sync();if(!model.hold||model.submitting||model.terminal)return;
    const p=canvasPoint(e),axis=model.hold.axis;model.hold=null;
    record('drive_up',{axis,point:p,input_source:'handwheel_drag'});
    try{e.currentTarget.releasePointerCapture(e.pointerId);}catch(_){}
    e.preventDefault();draw();sync();
  }
  function payload() {return {mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,
    challenge_id:model.state.challenge_id,revision:model.state.revision,interaction_mode:model.interaction,
    events:model.events,final:model.sim.snapshot(),completed:model.sim.solved&&!model.sim.failed};}
  async function finish() {
    if(!model||model.submitting||model.terminal||model.hold)return;
    record('seal',{input_source:'certify_button'});model.submitting=true;
    model.helpers.setReadout('VERIFYING ALIGNMENT…','pending');
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const outcome=await response.json();model.terminal=true;model.verdict=outcome.passed?'pass':'fail';
      document.querySelector('.rw-chamber').dataset.verdict=model.verdict;
      const v=document.querySelector('#rw-verdict');v.innerHTML=`<strong>${outcome.passed?'PASS':'FAIL'}</strong><span>${outcome.passed?'WORLD PLUMB HELD / ALL AXES VERIFIED':'FIRST FAILED ATTEMPT · EPISODE ENDED'}</span>`;
      model.helpers.setReadout(outcome.passed?'PASS':'FAIL · EPISODE ENDED',outcome.passed?'passed':'error');
      document.querySelector('#rw-certify').disabled=true;draw();
    } catch(e) {model.terminal=true;model.verdict='error';model.helpers.setReadout(`VERIFIER ERROR · ${e.message}`,'error');}
  }
  function frame() {sync();draw();if(model&&!model.terminal)raf=requestAnimationFrame(frame);}
  async function render(state,helpers) {
    cancelAnimationFrame(raf);document.body.dataset.mechanic='wind-gimbal-v2';
    model={state,helpers,interaction:state.control_condition?.interaction||'full',sim:new Physics(state.gimbal),events:[],inspected:[false,false,false],hold:null,terminal:false,submitting:false,verdict:''};
    window.rotateWrongV3Model=model;
    const p=state.gimbal.parameters;
    helpers.app.innerHTML=`<section class="rw-chamber" data-verdict="" data-interaction="${model.interaction}">
      <header class="rw-head"><div><small>THE ORIENTATION CONSERVATORY · POWERED GIMBAL</small><h1>${clean(state.prompt)}</h1></div><b id="rw-clock">READY</b></header>
      <main class="rw-main"><div class="rw-scene"><canvas id="rw-world" width="900" height="340"></canvas><canvas id="rw-gauges" width="900" height="96"></canvas><canvas id="rw-controls" width="900" height="152" aria-label="gimbal motor controls"></canvas></div>
      <aside><canvas id="rw-wind" width="250" height="360"></canvas><p>${model.interaction==='full'?'Drag handles to set persistent motor dials.':'Click the rails to set persistent motor dials.'}</p><p>Lift GEAR COVERS: reveal this rig’s +DIAL directions and cross-axis gears. Safe before or during motion; stays visible.</p><p>Each accepted drive action advances one fixed 200ms control interval; between inputs the current state is stable. Wind and inertia turn the sculpture. Match the dashed world-plumb ghost.</p><p>Hold every active angle within ±${p.tolerance_deg}° and speed within ±${p.speed_tolerance}°/s for 10s. Leaving a band clears progress. Early CERTIFY or 90s expiry ends the episode.</p></aside></main>
      <footer class="rw-foot"><button id="rw-begin">BEGIN ALIGNMENT</button><div class="rw-progress"><span id="rw-charge-text">PLUMB HOLD 0.0 / 10.0s</span><div><i id="rw-charge"></i></div><div class="readout" data-status="idle">INSPECT GEAR COVERS · SET DRIVES · BEGIN</div></div><button id="rw-certify">CERTIFY</button></footer><div id="rw-verdict"></div></section>`;
    const canvas=document.querySelector('#rw-controls');canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',up);canvas.addEventListener('lostpointercapture',up);
    document.querySelector('#rw-begin').addEventListener('click',()=>{if(model.sim.started||model.terminal||model.hold)return;model.sim.started=true;record('start',{input_source:'begin_button'});model.helpers.setReadout('WIND ACTIVE · STEER ALL AXES','pending');draw();});
    document.querySelector('#rw-certify').addEventListener('click',()=>{if(!model.hold)void finish();});
    if(state.episode_failed||state.episode_history_error) {
      model.terminal=true;model.verdict=state.episode_history_error?'error':'fail';
      document.querySelector('.rw-chamber').dataset.verdict='fail';
      document.querySelector('#rw-verdict').innerHTML=state.episode_history_error?'<strong>ERROR</strong><span>EPISODE UNAVAILABLE</span>':'<strong>FAIL</strong><span>EPISODE ENDED · PRIOR FAILURE RETAINED</span>';
      model.helpers.setReadout(state.episode_history_error?'VERIFIER ERROR · EPISODE UNAVAILABLE':'FAIL · EPISODE ENDED','error');
    }
    draw();if(!model.terminal)raf=requestAnimationFrame(frame);
  }
  window.RotateWrongV3Physics={Physics,noise,wind,fullHandle,pointerValue,transform,project};
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.rotate_wrong_thing_upright_v3_nonrealtime={render,rootSelector:'.rw-chamber'};
})();
