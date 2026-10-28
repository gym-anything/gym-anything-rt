(() => {
  'use strict';
  let model, raf=0;
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  const rad=a=>a*Math.PI/180;
  function target(piece,t) {
    const k=piece.knots;
    let i=0; while(i<k.length-2 && t>=k[i+1].t_ms) i++;
    const a=k[i],b=k[i+1],span=b.t_ms-a.t_ms,u=clamp((t-a.t_ms)/span,0,1);
    const s=u*u*u*(10+u*(-15+6*u)),ds=30*u*u*(1-u)*(1-u)*1000/span;
    return {x:a.x+(b.x-a.x)*s,y:a.y+(b.y-a.y)*s,angle:a.angle+(b.angle-a.angle)*s,
      vx:(b.x-a.x)*ds,vy:(b.y-a.y)*ds,omega:(b.angle-a.angle)*ds};
  }
  function errors(i) {
    const b=model.sim.bodies[i],q=target(model.state.pieces[i],model.sim.tick*10),p=model.state.parameters;
    const e={position:Math.hypot(b.x-q.x,b.y-q.y),angle:Math.abs(b.angle-q.angle),
      velocity:Math.hypot(b.vx-q.vx,b.vy-q.vy),angular_velocity:Math.abs(b.omega-q.omega)};
    e.ok=e.position<=p.position_tolerance && e.angle<=p.angle_tolerance && e.velocity<=p.velocity_tolerance && e.angular_velocity<=p.angular_velocity_tolerance;
    return e;
  }
  const registered=()=>model.sim.bodies.every((_,i)=>errors(i).ok);
  function step() {
    const s=model.sim,p=model.state.parameters,old=s.bodies.map(b=>({...b})),dt=.01;
    s.bodies.forEach((b,i)=>{
      for(const [axis,vel,command] of [['x','vx','cx'],['y','vy','cy']]) {
        let spring=0; for(const j of [i-1,i+1]) if(j>=0 && j<old.length) spring+=(old[j][axis]-old[i][axis])*p.spring;
        const acc=clamp(p.stiffness*(b[command]-b[axis])-p.damping*b[vel]+spring,-model.state.max_acceleration,model.state.max_acceleration);
        b[vel]=clamp(b[vel]+acc*dt,-model.state.max_speed,model.state.max_speed); b[axis]+=b[vel]*dt;
      }
      if(p.rotation_amplitude) {
        const acc=model.state.angular_stiffness*(b.ca-b.angle)-model.state.angular_damping*b.omega;
        b.omega=clamp(b.omega+acc*dt,-model.state.max_angular_speed,model.state.max_angular_speed);
        b.angle+=b.omega*dt;
      } else {b.angle=0;b.omega=0;b.ca=0;}
    });
    s.tick++;
    if(s.phase==='welding') {
      if(!registered()) {s.phase='failed';s.failure='SEAM SLIPPED';}
      else if((s.tick-s.clamp_tick)*10>=model.state.weld_ms) s.phase='passed';
    }
    if(s.tick*10>=model.state.run_limit_ms && !['passed','failed'].includes(s.phase)) {s.phase='failed';s.failure='RUN EXPIRED';}
  }
  function sync() {
    if(!model || !['running','welding'].includes(model.sim.phase)) return;
    const end=Math.min(Math.floor((performance.now()-model.origin)/10),model.state.run_limit_ms/10);
    while(model.sim.tick<end && ['running','welding'].includes(model.sim.phase)) step();
    if(['passed','failed'].includes(model.sim.phase)) finish();
  }
  function record(kind,extra={}) {
    model.events.push({sequence:model.events.length+1,tick:model.sim.tick,kind,input_source:model.interaction,...extra});
  }
  async function finish() {
    if(model.submitted) return;
    model.submitted=true;
    model.helpers.setReadout(model.sim.phase==='passed'?'VERIFYING REGISTERED SEAMS…':`FAIL · ${model.sim.failure}`,'pending');
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      physics_revision:model.state.physics_revision,interaction_mode:model.interaction,events:model.events,
      final_tick:model.sim.tick,completed:model.sim.phase==='passed'};
    model.payload=payload;
    try {
      const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      model.grade=await r.json();
      model.helpers.setReadout(model.grade.passed?'PASS · PICTURES RESTORED':`FAIL · ${model.sim.failure || 'REPLAY REJECTED'}`,model.grade.passed?'passed':'error');
    } catch(e) {model.helpers.setReadout(`VERIFIER ERROR · ${e.message}`,'error');}
  }
  function path(ctx,polygon) {
    ctx.beginPath(); polygon.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();
  }
  function inside(point,polygon) {
    let hit=false; const [x,y]=point;
    for(let i=0,j=polygon.length-1;i<polygon.length;j=i++) {
      const a=polygon[i],b=polygon[j];
      if((a[1]>y)!==(b[1]>y) && x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]) hit=!hit;
    } return hit;
  }
  function art(piece) {
    const canvas=document.createElement('canvas');canvas.width=250;canvas.height=230;const c=canvas.getContext('2d');
    const sky=c.createLinearGradient(0,0,0,230);sky.addColorStop(0,'#314c68');sky.addColorStop(.65,'#d19e6f');sky.addColorStop(1,'#192a35');c.fillStyle=sky;c.fillRect(0,0,250,230);
    c.fillStyle=piece.color;c.beginPath();c.arc(171,58,23,0,Math.PI*2);c.fill();
    for(let m=0;m<3;m++) {
      c.fillStyle=['#243f4d','#254b4b','#1b3237'][m];c.beginPath();c.moveTo(0,120+m*30);
      for(let x=0;x<=260;x+=26) c.lineTo(x,98+m*30+Math.sin((x+piece.motif*21)/37+m)*30);
      c.lineTo(250,230);c.lineTo(0,230);c.fill();
    }
    c.strokeStyle='#e2caaa';c.lineWidth=4;c.beginPath();c.moveTo(0,173);c.bezierCurveTo(70,142,142,170,250,136);c.stroke();
    c.strokeStyle=piece.color;c.lineWidth=3;c.beginPath();c.moveTo(125,52);c.lineTo(125,158);c.moveTo(94,83);c.lineTo(157,130);c.stroke();
    c.fillStyle='#f2e4c8';c.beginPath();c.arc(122,112,8,0,Math.PI*2);c.fill();
    return canvas;
  }
  function draw() {
    const c=model.ctx,s=model.sim,p=model.state.parameters,n=s.bodies.length,w=1080/n,t=s.tick*10;
    c.clearRect(0,0,1080,540);c.fillStyle='#101c26';c.fillRect(0,0,1080,540);
    c.font='12px monospace';
    if(p.spring) {
      c.strokeStyle='#759091';c.lineWidth=2;
      for(let i=1;i<n;i++) {
        const a=s.bodies[i-1],b=s.bodies[i],ax=(i-.5)*w+a.x,ay=220+a.y,bx=(i+.5)*w+b.x,by=220+b.y;
        c.beginPath();c.moveTo(ax,ay);
        for(let j=1;j<30;j++) {const u=j/30;c.lineTo(ax+(bx-ax)*u,ay+(by-ay)*u+(j%2?5:-5));}
        c.lineTo(bx,by);c.stroke();
      }
    }
    s.bodies.forEach((b,i)=>{
      const piece=model.state.pieces[i],cx=(i+.5)*w,q=target(piece,t),e=errors(i);
      c.save();c.beginPath();c.rect(i*w,0,w,430);c.clip();
      c.strokeStyle='#324656';c.lineWidth=1;c.strokeRect(i*w+1,1,w-2,428);
      c.save();c.translate(cx+q.x,220+q.y);c.rotate(rad(q.angle));c.drawImage(model.art[i],-125,-115);
      path(c,piece.polygon);c.fillStyle='#0b1620';c.fill();c.strokeStyle=e.ok?'#6ee4a4':piece.color;c.lineWidth=3;c.stroke();c.restore();
      const past=target(piece,Math.max(0,t-model.state.trail_ms));c.globalAlpha=.25;c.save();c.translate(cx+past.x,220+past.y);c.rotate(rad(past.angle));path(c,piece.polygon);c.stroke();c.restore();c.globalAlpha=1;
      c.strokeStyle='#bfd8dc';c.setLineDash([2,4]);c.beginPath();c.moveTo(cx+b.x,220+b.y);c.lineTo(cx+b.cx,220+b.cy);c.stroke();c.setLineDash([]);
      c.strokeRect(cx+b.cx-5,220+b.cy-5,10,10);
      c.save();c.translate(cx+b.x,220+b.y);c.rotate(rad(b.angle));
      c.shadowBlur=10;c.shadowColor='#000';path(c,piece.polygon);c.save();c.clip();c.drawImage(model.art[i],-125,-115);c.restore();
      c.shadowBlur=0;c.strokeStyle=e.ok?'#79f2aa':'#fff0d2';c.lineWidth=3;c.stroke();c.fillStyle='#07121c';c.fillRect(-13,-9,26,18);c.fillStyle='#fff';c.textAlign='center';c.fillText(piece.label,0,4);c.restore();
      // Paint predictions above the opaque fragment so registration cannot hide
      // the time evidence needed for a delayed command.
      c.setLineDash([3,6]);c.strokeStyle=piece.color;c.lineWidth=2;c.beginPath();
      for(let d=0;d<=model.state.preview_ms;d+=100) {const f=target(piece,t+d);if(d)c.lineTo(cx+f.x,220+f.y);else c.moveTo(cx+f.x,220+f.y);}
      c.stroke();c.setLineDash([]);
      for(let d=100;d<=model.state.preview_ms;d+=100) {const f=target(piece,t+d);c.fillStyle=piece.color;c.beginPath();c.arc(cx+f.x,220+f.y,2,0,Math.PI*2);c.fill();}
      const forecast=target(piece,t+1000);c.save();c.translate(cx+forecast.x,220+forecast.y);c.rotate(rad(forecast.angle));
      c.strokeStyle=piece.color;c.lineWidth=1.5;c.setLineDash([4,4]);path(c,piece.polygon);c.stroke();c.restore();
      c.fillStyle='#07121ce8';c.fillRect(cx+forecast.x-30,220+forecast.y-85,60,18);c.fillStyle=piece.color;c.textAlign='center';c.fillText('+1.0s',cx+forecast.x,220+forecast.y-72);c.textAlign='left';
      const bx=cx+b.x,by=220+b.y,ex=bx+b.vx*.3,ey=by+b.vy*.3;
      c.strokeStyle='#fff0d2';c.lineWidth=2;c.beginPath();c.moveTo(bx,by);c.lineTo(ex,ey);
      if(Math.hypot(b.vx,b.vy)>1) {const a=Math.atan2(ey-by,ex-bx);c.moveTo(ex-7*Math.cos(a-.5),ey-7*Math.sin(a-.5));c.lineTo(ex,ey);c.lineTo(ex-7*Math.cos(a+.5),ey-7*Math.sin(a+.5));}
      c.stroke();
      c.fillStyle=e.ok?'#79f2aa':'#d8e3e8';c.fillText(`OFFSET ${e.position.toFixed(0)}/${p.position_tolerance}px   ANGLE ${e.angle.toFixed(0)}/${p.angle_tolerance}°`,i*w+18,390);
      c.fillText(`SLIP ${e.velocity.toFixed(0)}/${p.velocity_tolerance}   SPIN ${e.angular_velocity.toFixed(0)}/${p.angular_velocity_tolerance}`,i*w+18,413);
      // Rotated picture backgrounds can reach the lane heading. Keep learned
      // drive information above them; apertures and registered fragments stay below it.
      c.fillStyle='#101c26';c.fillRect(i*w+10,10,w-20,47);
      c.fillStyle=piece.color;c.fillText(`PICTURE ${piece.label}`,i*w+18,27);
      const probe=model.driveObservations[i];
      c.fillStyle=probe?'#d8e3e8':'#e8c48e';
      c.fillText(probe?`X DRIVE ${probe.requested*probe.destination>0?'DIRECT':'REVERSED'} · HAND ${probe.requested.toFixed(0)} → SQUARE ${probe.destination.toFixed(0)}`:'X DRIVE ? · TEST A HORIZONTAL MOVE',i*w+18,49);
      c.restore();
      if(p.rotation_amplitude) {
        c.strokeStyle='#527080';c.lineWidth=9;c.beginPath();c.arc(cx,466,38,Math.PI,2*Math.PI);c.stroke();
        for(const [a,color,len] of [[q.angle,piece.color,43],[b.angle,'#fff0d2',34],[b.ca,'#7c9fa6',25]]) {
          c.strokeStyle=color;c.lineWidth=3;c.beginPath();c.moveTo(cx,466);c.lineTo(cx+Math.sin(rad(a))*len,466-Math.cos(rad(a))*len);c.stroke();
        }
        c.fillStyle='#b0c4cd';c.textAlign='center';c.fillText(`TURN ${piece.label} · ${b.angle.toFixed(0)}°`,cx,518);c.fillText(`FRAGMENT SPIN ${b.omega.toFixed(0)}°/s`,cx,535);c.textAlign='left';
      } else {
        c.fillStyle='#b0c4cd';c.textAlign='center';c.fillText('ROTATION LOCKED · 0°',cx,477);c.textAlign='left';
      }
    });
    const status=document.querySelector('.jigsaw-v2-status');
    const fraction=s.phase==='welding'?Math.min(1,(s.tick-s.clamp_tick)*10/model.state.weld_ms):s.phase==='passed'?1:0;
    document.querySelector('.jigsaw-v2-seam i').style.width=`${fraction*100}%`;
    status.textContent=s.phase==='ready'?'INSPECT · START WHEN READY':s.phase==='failed'?s.failure:s.phase==='passed'?'SEAMS COMPLETE':s.phase==='welding'?`KEEP TRACKING · ${(6-fraction*6).toFixed(1)}s`:`${registered()?'ALL RIMS GREEN · CLAMP WHEN READY':'TRACK THE APERTURES'} · ${(t/1000).toFixed(1)}s / 120s`;
    document.querySelector('[data-control="clamp"]').disabled=s.phase!=='running';
    if(['passed','failed'].includes(s.phase)) {
      c.fillStyle='rgba(6,13,20,.83)';c.fillRect(0,0,1080,540);c.textAlign='center';c.font='bold 42px Georgia';c.fillStyle=s.phase==='passed'?'#79f2aa':'#f3a9a2';c.fillText(s.phase==='passed'?'PICTURES RESTORED':'ATTEMPT ENDED',540,250);c.font='18px monospace';c.fillText(s.phase==='passed'?'All moving seams stayed registered.':s.failure,540,289);c.textAlign='left';
    }
  }
  function canvasPoint(event) {
    const r=model.canvas.getBoundingClientRect();return [(event.clientX-r.left)*1080/r.width,(event.clientY-r.top)*540/r.height];
  }
  function command(i,kind,point) {
    if(kind==='position') {
      const x=clamp(point[0],-120,120),y=clamp(point[1],-145,150),destination=x*model.state.pieces[i].drive_x;
      record('position',{piece:i,point:[x,y]});Object.assign(model.sim.bodies[i],{cx:destination,cy:y});
      // A request displayed as zero supplies no visible polarity evidence.
      // Match the integer readout's precision, including subpixel input noise,
      // and retain the last informative response when returning to the centre.
      if(Math.round(x)!==0)model.driveObservations[i]={requested:x,destination};
    }
    else {const angle=clamp(Math.atan2(point[0],-point[1])*180/Math.PI,-90,90);record('angle',{piece:i,angle});model.sim.bodies[i].ca=angle;}
  }
  function down(event) {
    sync();if(['passed','failed'].includes(model.sim.phase)||event.button!==0)return;
    const point=canvasPoint(event);
    if(point[0]<0||point[0]>1080||point[1]<0||point[1]>540||model.hold)return;
    const n=model.sim.bodies.length,w=1080/n,i=clamp(Math.floor(point[0]/w),0,n-1),cx=(i+.5)*w,b=model.sim.bodies[i];
    const dial=[point[0]-cx,point[1]-466],inDial=model.state.parameters.rotation_amplitude&&Math.hypot(...dial)>=24&&Math.hypot(...dial)<=52&&point[1]<=477;
    const local=[point[0]-cx,point[1]-220];
    if(model.interaction==='simplified') {
      if(inDial) command(i,'angle',dial);
      else if(point[1]>=60&&point[1]<=370&&Math.abs(local[0])<=120)command(i,'position',local);
      return;
    }
    const theta=rad(-b.angle),dx=local[0]-b.x,dy=local[1]-b.y,hit=point[1]<=430&&inside([dx*Math.cos(theta)-dy*Math.sin(theta),dx*Math.sin(theta)+dy*Math.cos(theta)],model.state.pieces[i].polygon);
    if(!inDial&&!hit)return;
    event.preventDefault();model.canvas.setPointerCapture(event.pointerId);
    model.hold={piece:i,kind:inDial?'angle':'position',pointer:event.pointerId};
    record(inDial?'dial_grab':'grab',{piece:i,point:inDial?dial:local});
  }
  function move(event) {
    sync();if(!model.hold||['passed','failed'].includes(model.sim.phase))return;
    const h=model.hold,point=canvasPoint(event),cx=(h.piece+.5)*1080/model.sim.bodies.length;
    command(h.piece,h.kind,[point[0]-cx,point[1]-(h.kind==='position'?220:466)]);
  }
  function up(event) {
    if(!model.hold)return;
    move(event);if(!['passed','failed'].includes(model.sim.phase))record('release');model.hold=null;
    if(model.canvas.hasPointerCapture(event.pointerId))model.canvas.releasePointerCapture(event.pointerId);
  }
  function animate(){if(!model)return;sync();draw();raf=requestAnimationFrame(animate);}
  function render(state,helpers) {
    cancelAnimationFrame(raf);document.body.dataset.mechanic='jigsaw-v2';
    const interaction=state.control_condition.interaction;
    const turnInstruction=state.parameters.rotation_amplitude?(interaction==='full'?' Drag the semicircular dial to turn it.':' Click the semicircular dial to turn it.'):' Rotation is locked at this difficulty.';
    model={state,helpers,interaction,events:[],origin:performance.now(),hold:null,submitted:false,driveObservations:state.pieces.map(()=>null),
      sim:{tick:0,phase:'ready',clamp_tick:null,failure:'',bodies:state.pieces.map(p=>({...p.initial,vx:0,vy:0,omega:0,cx:p.initial.x,cy:p.initial.y,ca:p.initial.angle}))}};
    window.jigsawSliderAlignmentV3Model=model;
    helpers.app.innerHTML=`<section class="jigsaw-v2"><header><div><p>THE RESTORATION ENGINE / MOVING REGISTRATION</p><h1>Parallax / Inertial Jigsaw Alignment V3</h1></div><b>D${state.control_condition.difficulty} · ${interaction.toUpperCase()}</b></header><div class="jigsaw-v2-rules">${state.prompt}<br><strong>${interaction==='full'?'Drag a fragment to steer its carriage.':'Click a destination in each picture lane to steer its carriage.'}${turnInstruction}</strong> White = fragment; colour = aperture; square = commanded destination.<br>Coloured dots are 0.1s apart; dashed shape = aperture in 1.0s. White arrow = fragment travel at its current speed over 0.3s.</div><canvas width="1080" height="540" class="jigsaw-v2-canvas"></canvas><footer><button data-control="start">START MOTION</button><button data-control="clamp" disabled>CLAMP ALL SEAMS</button><div><b class="jigsaw-v2-status"></b><div class="jigsaw-v2-seam"><i></i></div></div></footer><div class="readout">Inspect the matching images, then start. Keep steering during the closing seam.</div></section>`;
    model.canvas=helpers.app.querySelector('canvas');model.ctx=model.canvas.getContext('2d');model.art=state.pieces.map(art);
    model.canvas.addEventListener('pointerdown',down);model.canvas.addEventListener('pointermove',move);model.canvas.addEventListener('pointerup',up);
    model.canvas.addEventListener('pointercancel',up);
    helpers.app.querySelector('[data-control="start"]').addEventListener('click',event=>{
      if(model.sim.phase!=='ready')return;record('start');model.origin=performance.now();model.sim.phase='running';event.currentTarget.disabled=true;
    });
    helpers.app.querySelector('[data-control="clamp"]').addEventListener('click',()=>{
      sync();if(model.sim.phase!=='running')return;record('clamp');
      if(registered()){model.sim.phase='welding';model.sim.clamp_tick=model.sim.tick;}
      else{model.sim.phase='failed';model.sim.failure='BAD CLAMP';finish();}
    });
    draw();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.jigsaw_slider_alignment_v3={rootSelector:'.jigsaw-v2',render};
})();
