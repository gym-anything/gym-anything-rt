(() => {
  "use strict";
  const ID = "pocket_locksmith_v3_nonrealtime";
  const ACTION_STEP_MS = 100;
  const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  const radians = a => a*Math.PI/180;
  const esc = x => String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const copy = x => JSON.parse(JSON.stringify(x));
  let model = null, frame = 0;

  function points(base, angles) {
    const p = base.map(x => [...x]);
    angles.forEach((angle,j) => {
      const origin = p[j], axis = p[j+1].map((x,i) => x-origin[i]);
      const length = Math.hypot(...axis); axis.forEach((x,i) => axis[i]=x/length);
      const c=Math.cos(radians(angle)), s=Math.sin(radians(angle));
      for (let k=j+2;k<p.length;k++) {
        const v=p[k].map((x,i)=>x-origin[i]);
        const cross=[axis[1]*v[2]-axis[2]*v[1],axis[2]*v[0]-axis[0]*v[2],axis[0]*v[1]-axis[1]*v[0]];
        const dot=axis.reduce((t,x,i)=>t+x*v[i],0);
        p[k]=v.map((x,i)=>origin[i]+x*c+cross[i]*s+axis[i]*dot*(1-c));
      }
    });
    return p;
  }
  function targetAngles(world,ms) {
    return world.paths.map(path => {
      const times=path.times_ms;let n=times.findIndex((t,i)=>i<times.length-1&&ms<times[i+1]);if(n<0)n=times.length-2;
      const f=clamp((ms-times[n])/(times[n+1]-times[n]),0,1);
      return path.knots[n]+(path.knots[n+1]-path.knots[n])*f*f*(3-2*f);
    });
  }
  class Physics {
    constructor(world) {
      this.world=world;this.p=world.parameters;this.ms=0;
      this.angles=[...world.initial_angles];this.command=[...this.angles];this.velocity=this.angles.map(()=>0);
      this.boundMs=0;this.outageMs=0;this.worstOutageMs=0;this.siteMs=this.angles.map(()=>0);
      this.errors=this.angles.map(()=>0);this.done=false;this.failed="";
    }
    advance(end) {
      const dt=this.world.tick_ms/1000;
      while(this.ms+this.world.tick_ms<=end && !this.done) {
        this.ms+=this.world.tick_ms;
        this.angles.forEach((angle,j)=>{
          const a=clamp((this.command[j]-angle)*this.p.servo_gain-this.velocity[j]*this.p.servo_damping,-this.p.max_acceleration,this.p.max_acceleration);
          this.velocity[j]=clamp(this.velocity[j]+a*dt,-this.p.max_speed,this.p.max_speed);
          this.angles[j]+=this.velocity[j]*dt;
        });
        const key=points(this.world.base_points,this.angles).slice(2),pocket=points(this.world.base_points,targetAngles(this.world,this.ms)).slice(2);
        this.errors=key.map((v,j)=>Math.hypot(...v.map((x,i)=>x-pocket[j][i])));
        const seated=this.errors.map(e=>e<=this.p.clearance+1e-9);
        seated.forEach((hit,j)=>this.siteMs[j]+=this.world.tick_ms*Number(hit));
        if(seated.every(Boolean)){this.boundMs+=this.world.tick_ms;this.outageMs=0;}
        else{this.outageMs+=this.world.tick_ms;this.worstOutageMs=Math.max(this.worstOutageMs,this.outageMs);}
        if(this.outageMs>this.p.max_outage_ms){this.failed="The key dissociated after prolonged contact loss.";this.done=true;}
        else if(this.boundMs>=this.p.required_fraction*this.p.run_ms){this.done=true;}
        else if(this.ms>=this.p.run_ms){this.failed="Insufficient simultaneous binding contact.";this.done=true;}
      }
    }
  }
  window.PocketLocksmithV3Physics={Physics,points,targetAngles};
  function commandPoint(angle){return[110+40*Math.cos(radians(angle-90)),67+40*Math.sin(radians(angle-90))];}
  function commandFromPoint(point,mode){
    if(mode==='simplified')return(point[0]-110)*85/90;
    let a=Math.atan2(point[1]-67,point[0]-110)*180/Math.PI+90;if(a>180)a-=360;
    return clamp(a,-85,85);
  }
  function event(kind,details={}) {
    model.events.push({sequence:model.events.length+1,kind,t_ms:model.physics.ms,...details});
  }
  function sync() {
    // Waiting and camera motion do not advance counterpart task time.
  }
  function advanceAction() {
    if(model.armed&&!model.terminal)model.physics.advance(Math.min(model.physics.p.run_ms,model.physics.ms+ACTION_STEP_MS));
  }
  function payload() {
    const p=model.physics;
    return {mechanic_id:ID,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      interaction_mode:model.mode,events:copy(model.events),completed:p.done&&!p.failed,
      final_t_ms:p.ms,bound_ms:p.boundMs,site_ms:[...p.siteMs],worst_outage_ms:p.worstOutageMs,
      angles:[...p.angles],velocity:[...p.velocity]};
  }
  async function finish(aborted=false) {
    if(model.terminal)return;
    sync();
    model.terminal=true;
    document.getElementById('pk-start').disabled=true;
    document.getElementById('pk-submit').disabled=true;
    event(aborted?'abort':'finish',{input_source:aborted?'submit_button':'physical_trial'});
    const fail=aborted||!!model.physics.failed;
    if(aborted)model.physics.failed='Trial abandoned or submitted before completion.';
    const overlay=document.getElementById('pk-verdict');
    overlay.hidden=false;overlay.dataset.verdict=fail?'fail':'pending';
    overlay.innerHTML=`<b>${fail?'FAIL':'VERIFYING'}</b><span>${esc(model.physics.failed||'The binding trial is complete.')}</span>`;
    model.helpers.setReadout(fail?'FAIL · TRIAL ENDED':'VERIFYING FIT',fail?'error':'pending');
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
      const result=await response.json();
      const passed=result.passed===true&&!fail;
      model.result=result;
      overlay.dataset.verdict=passed?'pass':'fail';
      overlay.innerHTML=`<b>${passed?'PASS':'FAIL'}</b><span>${passed?'The connected key stayed bound.':esc(model.physics.failed||result.feedback||'Fit replay rejected.')+' This episode has ended.'}</span>`;
      model.helpers.setReadout(passed?'PASS':'FAIL · TRIAL ENDED',passed?'passed':'error');
    }catch(error){overlay.innerHTML=`<b>VERIFIER ERROR</b><span>${esc(error.message)}</span>`;model.helpers.setReadout('VERIFIER ERROR','error');}
  }
  function viewCoordinates(point,kind,camera={yaw:34,pitch:18}) {
    let x,y,z;
    if(kind==='front'){[x,y,z]=point;}
    else if(kind==='top'){x=point[0];y=point[2];z=point[1];}
    else {
      const yaw=radians(camera.yaw),pitch=radians(camera.pitch),[a,b,c]=point;
      x=Math.cos(yaw)*a+Math.sin(yaw)*c;
      const depth=-Math.sin(yaw)*a+Math.cos(yaw)*c;
      y=Math.cos(pitch)*b-Math.sin(pitch)*depth;
      z=Math.sin(pitch)*b+Math.cos(pitch)*depth;
    }
    return{x,y,z};
  }
  function fitView(cloud,width,height,kind,clearance,camera) {
    const pad=kind==='main'?{side:28,top:38,bottom:44}:{side:12,top:30,bottom:12};
    const projected=cloud.map(point=>viewCoordinates(point,kind,camera));
    const radius=.10+clearance;
    const minX=Math.min(...projected.map(p=>p.x))-radius,maxX=Math.max(...projected.map(p=>p.x))+radius;
    const minY=Math.min(...projected.map(p=>p.y))-radius,maxY=Math.max(...projected.map(p=>p.y))+radius;
    return {scale:Math.min(kind==='main'?120:60,(width-2*pad.side)/(maxX-minX),
      (height-pad.top-pad.bottom)/(maxY-minY)),centerX:(minX+maxX)/2,centerY:(minY+maxY)/2,
      screenX:width/2,screenY:(pad.top+height-pad.bottom)/2,pad};
  }
  function projection(point,width,height,kind) {
    const view=model.views[kind],p=viewCoordinates(point,kind,model.camera),scale=view.scale;
    return{x:view.screenX+(p.x-view.centerX)*scale,y:view.screenY-(p.y-view.centerY)*scale,z:p.z,scale};
  }
  window.PocketLocksmithV3Physics.fitView=fitView;
  window.PocketLocksmithV3Physics.viewCoordinates=viewCoordinates;
  function drawScene(canvas,kind) {
    const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,world=model.state.world,p=model.physics;
    const bg=ctx.createLinearGradient(0,0,w,h);bg.addColorStop(0,'#081b2d');bg.addColorStop(1,'#141228');
    ctx.fillStyle=bg;ctx.fillRect(0,0,w,h);
    ctx.lineWidth=1;ctx.strokeStyle='#b2d9f00f';
    for(let x=0;x<w;x+=40){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}
    for(let y=0;y<h;y+=40){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
    const key=points(world.base_points,p.angles),target=points(world.base_points,targetAngles(world,p.ms));
    const forecast=[];
    for(let offset=-240;offset<=world.forecast_ms;offset+=80){
      forecast.push(points(world.base_points,targetAngles(world,Math.max(0,p.ms+offset))));
    }
    model.views[kind]=fitView([...key,...target,...forecast.flat()],w,h,kind,world.parameters.clearance,model.camera);
    function circle(pt,r,color,width=2,dash=[]){const q=projection(pt,w,h,kind);ctx.setLineDash(dash);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.arc(q.x,q.y,r*q.scale,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);}
    // The faint path is the actual pocket's next 800 ms, not an auto-aim control.
    for(let j=2;j<key.length;j++){
      const color=world.colors[j-2];
      ctx.strokeStyle=color+'65';ctx.lineWidth=2;ctx.beginPath();
      forecast.forEach((positions,index)=>{const pos=projection(positions[j],w,h,kind);
        if(index===0)ctx.moveTo(pos.x,pos.y);else ctx.lineTo(pos.x,pos.y);});
      ctx.stroke();
      const future=points(world.base_points,targetAngles(world,p.ms+world.forecast_ms))[j];
      circle(future,world.atom_radius+world.parameters.clearance,color+'66',1,[4,4]);
      circle(target[j],world.atom_radius+world.parameters.clearance,color,3);
      circle(target[j],world.parameters.clearance,color+'66',1,[2,3]);
    }
    function drawBond(a,b,color,width){a=projection(a,w,h,kind);b=projection(b,w,h,kind);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();}
    for(let j=0;j<target.length-1;j++)drawBond(target[j],target[j+1],'#8bcbbb33',kind==='main'?2:1);
    for(let j=0;j<key.length-1;j++)drawBond(key[j],key[j+1],j<2?'#839aaa':'#efcc99',kind==='main'?6:3);
    key.map((pos,j)=>({pos,j,q:projection(pos,w,h,kind)})).sort((a,b)=>b.q.z-a.q.z).forEach(({pos,j,q})=>{
      const r=world.atom_radius*q.scale,color=j>=2?world.colors[j-2]:'#8a9eaf';
      const gradient=ctx.createRadialGradient(q.x-r*.35,q.y-r*.35,1,q.x,q.y,r);
      gradient.addColorStop(0,'#fff3df');gradient.addColorStop(.35,color);gradient.addColorStop(1,'#343545');
      ctx.fillStyle=gradient;ctx.beginPath();ctx.arc(q.x,q.y,r,0,Math.PI*2);ctx.fill();ctx.strokeStyle=color;ctx.lineWidth=1;ctx.stroke();
      if(j>=2&&kind==='main'){ctx.fillStyle=color;ctx.font='bold 14px monospace';ctx.fillText(String(j-1),q.x-4,q.y-19);}
    });
    ctx.font='12px monospace';ctx.fillStyle='#95afc4';ctx.fillText(kind==='main'?'DRAG EMPTY SPACE TO ORBIT':kind==='front'?'FRONT · X / Y':'TOP · X / Z',16,22);
  }
  function drawControl(canvas,j) {
    const ctx=canvas.getContext('2d'),p=model.physics,link=model.state.world.drive_linkages[j];
    const bond=link.joint,direction=link.direction;
    // A real joint response reveals the linkage; returning to neutral keeps it.
    if(Math.abs(p.angles[bond])>1e-7)model.discovered[j]=true;
    const known=model.discovered[j],color=known?model.state.world.colors[bond]:'#bbc9d4';
    const actualAngle=direction*p.angles[bond],commandAngle=direction*p.command[bond];
    ctx.clearRect(0,0,220,115);ctx.strokeStyle='#56697b';ctx.lineWidth=6;
    if(model.mode==='full'){
      ctx.beginPath();ctx.arc(110,67,40,radians(-175),radians(-5));ctx.stroke();
      ctx.lineWidth=1;ctx.strokeStyle='#8799a988';ctx.beginPath();ctx.arc(110,67,31,radians(-175),radians(-5));ctx.stroke();
      const actual=commandPoint(actualAngle);ctx.strokeStyle=color;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(110,67);ctx.lineTo(actual[0],actual[1]);ctx.stroke();
      const command=commandPoint(commandAngle);ctx.fillStyle='#fff6d4';ctx.beginPath();ctx.arc(command[0],command[1],9,0,Math.PI*2);ctx.fill();
      ctx.fillStyle='#9fadb8';ctx.font='11px monospace';ctx.fillText('↶',61,53);ctx.fillText('↷',153,53);
    }else{
      ctx.beginPath();ctx.moveTo(20,67);ctx.lineTo(200,67);ctx.stroke();
      const x=110+actualAngle*90/85;ctx.strokeStyle=color;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(x,53);ctx.lineTo(x,81);ctx.stroke();
      ctx.fillStyle='#fff6d4';ctx.beginPath();ctx.arc(110+commandAngle*90/85,67,9,0,Math.PI*2);ctx.fill();
    }
    ctx.fillStyle=color;ctx.font='bold 13px monospace';ctx.fillText(`DRIVE ${String.fromCharCode(65+j)}`,16,16);
    ctx.textAlign='right';ctx.fillStyle='#94aabd';ctx.font='12px monospace';ctx.fillText(`${actualAngle.toFixed(0)}°`,204,16);ctx.textAlign='left';
    ctx.fillStyle=color;ctx.font='12px monospace';
    ctx.fillText(known?`BOND ${bond+1} · ${direction===1?'SAME':'REVERSED'}`:'UNKNOWN · TEST A TURN',16,93);
    // A per-drive contact bar would leak the connection before discovery.
    if(known){
      const fraction=model.armed?p.siteMs[bond]/Math.max(20,p.ms):1;
      ctx.fillStyle='#2b3645';ctx.fillRect(20,99,180,5);ctx.fillStyle=p.errors[bond]<=p.p.clearance?color:'#ea666c';ctx.fillRect(20,99,180*fraction,5);
    }
  }
  function draw() {
    if(!model)return;
    ['main','front','top'].forEach(kind=>drawScene(document.getElementById('pk-'+kind),kind));
    document.querySelectorAll('.pk-dial').forEach((canvas,j)=>drawControl(canvas,j));
    const p=model.physics,progress=document.getElementById('pk-progress'),loss=document.getElementById('pk-loss');
    progress.style.width=`${100*p.ms/p.p.run_ms}%`;
    loss.style.width=`${100*Math.min(1,p.outageMs/p.p.max_outage_ms)}%`;
    document.getElementById('pk-loss-time').textContent=`${(p.outageMs/1000).toFixed(1)} / ${(p.p.max_outage_ms/1000).toFixed(1)}s`;
    document.getElementById('pk-contact').textContent=`${p.errors.filter(e=>e<=p.p.clearance).length}/${p.errors.length} SEATED`;
    document.getElementById('pk-clock').textContent=`${(p.ms/1000).toFixed(1)} / ${p.p.run_ms/1000}s`;
    document.getElementById('pk-binding').textContent=`${(p.boundMs/1000).toFixed(1)} / ${(p.p.run_ms*p.p.required_fraction/1000).toFixed(1)}s`;
  }
  function animate() {
    sync();draw();
    if(model.physics.done&&!model.terminal)finish();
    frame=requestAnimationFrame(animate);
  }
  function localPoint(e,canvas){const b=canvas.getBoundingClientRect();return[(e.clientX-b.x)*canvas.width/b.width,(e.clientY-b.y)*canvas.height/b.height];}
  function render(state,helpers) {
    cancelAnimationFrame(frame);document.body.dataset.mechanic='pocket-locksmith-v3-nonrealtime';
    const mode=state.control_condition?.interaction||'full';
    model={state,helpers,mode,physics:new Physics(state.world),events:[],discovered:state.world.paths.map(()=>false),armed:false,startedAt:0,terminal:false,held:null,camera:{yaw:34,pitch:18},views:{}};
    window.pocketLocksmithV3Model=model;
    helpers.app.innerHTML=`<section class="pk-game" data-interaction="${mode}">
      <header><div><small>MOLECULAR ACCESS · ${esc(state.display.pocket_name)} POCKET</small><h1>Pocket Locksmith V3</h1></div><p>Earn ${(state.world.parameters.run_ms*state.world.parameters.required_fraction/1000).toFixed(2)}s of simultaneous contact within ${state.world.parameters.run_ms/1000}s.<br>Upstream turns move the whole connected key.</p></header>
      <main><section class="pk-scenes"><canvas id="pk-main" width="860" height="440"></canvas><div class="pk-projections"><canvas id="pk-front" width="390" height="160"></canvas><canvas id="pk-top" width="390" height="160"></canvas></div><div class="pk-legend"><i></i>KEY ATOM <b>◯</b>SOCKET <span>··· 0.8s POCKET PATH</span></div></section>
      <aside><h2>UNMARKED LINKAGES</h2><p>${mode==='full'?'Drag the cream bead around each curved ring.':'Click an angle on each straight command rail.'}<br>Test turns before START reveal each drive's bond and direction. Labels stay.<br>Needle = actual; cream bead = command.</p><div class="pk-controls">${state.world.paths.map((_,j)=>`<canvas class="pk-dial" data-joint="${j}" width="220" height="115" aria-label="drive ${String.fromCharCode(65+j)} torsion control"></canvas>`).join('')}</div><div class="pk-contact" id="pk-contact">SEATED</div></aside></main>
      <footer><div><small>BINDING TRIAL</small><div class="pk-bar"><i id="pk-progress"></i></div><span id="pk-clock">0 / 24s</span></div><div><small>SIMULTANEOUS CONTACT</small><b id="pk-binding"></b><div class="readout">READY</div></div><div><small>CONTACT LOSS → DISSOCIATION</small><div class="pk-bar danger"><i id="pk-loss"></i></div><span id="pk-loss-time"></span></div><button id="pk-start">START BINDING</button><button id="pk-submit">ABANDON / SUBMIT</button></footer><div id="pk-verdict" hidden></div></section>`;
    document.querySelectorAll('.pk-dial').forEach((canvas,j)=>{
      const link=state.world.drive_linkages[j],bond=link.joint,direction=link.direction;
      canvas.addEventListener('pointerdown',e=>{
        if(model.terminal||e.button!==0)return;sync();if(model.physics.done){finish();return;}
        const point=localPoint(e,canvas);
        if(mode==='simplified'){
          if(point[0]<20||point[0]>200||point[1]<49||point[1]>85)return;
          event('rail_set',{joint:j,point,input_source:'torsion_rail_click'});
          model.physics.command[bond]=direction*commandFromPoint(point,mode);
          if(!model.armed)model.physics.angles=[...model.physics.command];
          else advanceAction();
        }else{
          if(model.held!==null||Math.hypot(...point.map((x,i)=>x-commandPoint(direction*model.physics.command[bond])[i]))>14)return;
          model.held=j;canvas.setPointerCapture(e.pointerId);event('dial_start',{joint:j,point,input_source:'torsion_ring_drag'});
        }
        e.preventDefault();draw();
      });
      canvas.addEventListener('pointermove',e=>{
        if(model.held!==j||model.terminal)return;sync();if(model.physics.done){finish();return;}
        const point=localPoint(e,canvas);event('dial_move',{joint:j,point,input_source:'torsion_ring_drag'});
        model.physics.command[bond]=direction*commandFromPoint(point,mode);if(!model.armed)model.physics.angles=[...model.physics.command];e.preventDefault();draw();
      });
      const release=e=>{
        if(model.held!==j||model.terminal)return;sync();if(model.physics.done){finish();return;}
        const point=localPoint(e,canvas);event('dial_end',{joint:j,point,input_source:'torsion_ring_drag'});model.held=null;advanceAction();
        try{canvas.releasePointerCapture(e.pointerId);}catch(_error){}draw();
      };
      canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);
      canvas.addEventListener('lostpointercapture',release);
    });
    const scene=document.getElementById('pk-main');let orbit=null;
    scene.addEventListener('pointerdown',e=>{if(model.terminal)return;orbit=localPoint(e,scene);scene.setPointerCapture(e.pointerId);e.preventDefault();});
    scene.addEventListener('pointermove',e=>{
      if(!orbit||model.terminal)return;sync();const end=localPoint(e,scene);event('orbit',{start:orbit,end,input_source:'camera_drag'});
      model.camera.yaw+=(end[0]-orbit[0])*.3;model.camera.pitch=clamp(model.camera.pitch-(end[1]-orbit[1])*.3,-70,70);orbit=end;draw();
    });
    for(const name of ['pointerup','pointercancel','lostpointercapture'])scene.addEventListener(name,()=>{orbit=null;});
    document.getElementById('pk-start').addEventListener('click',()=>{
      if(model.armed||model.terminal||model.held!==null)return;
      model.armed=true;event('arm',{input_source:'start_button'});
      document.getElementById('pk-start').disabled=true;model.helpers.setReadout('KEEP THE KEY BOUND · ONE ATTEMPT','idle');
    });
    document.getElementById('pk-submit').addEventListener('click',()=>finish(true));
    if(state.episode_failed){
      model.terminal=true;
      document.getElementById('pk-start').disabled=true;
      document.getElementById('pk-submit').disabled=true;
      const overlay=document.getElementById('pk-verdict');
      overlay.hidden=false;overlay.dataset.verdict='fail';
      overlay.innerHTML=`<b>FAIL</b><span>${esc(state.episode_failure_reason||'A failed submission already ended this episode.')}</span>`;
      helpers.setReadout('FAIL · EPISODE ENDED','error');
    }else helpers.setReadout('READY · ONE ATTEMPT','idle');
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.pk-game',render};
})();
