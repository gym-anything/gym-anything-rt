(() => {
  'use strict';
  const ID = 'zero_g_cable_autopsy_v2';
  let m = null, frame = 0, cleanup = null;
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  const dist = (a,b) => Math.hypot(a[0]-b[0],a[1]-b[1]);
  const clone = x => JSON.parse(JSON.stringify(x));
  function noise(seed,index) {
    let x = (seed ^ Math.imul(index+1,0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16),0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13),0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0)/4294967295*2-1;
  }
  function motion(spec,ms) {
    const u = Math.max(0,ms)/spec.span_ms, i = Math.floor(u), f = u-i;
    return spec.center+spec.amplitude*(noise(spec.seed,i)+(noise(spec.seed,i+1)-noise(spec.seed,i))*f*f*(3-2*f));
  }
  function closest(p,a,b) {
    const dx=b[0]-a[0],dy=b[1]-a[1],den=dx*dx+dy*dy;
    const f=den ? clamp(((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den,0,1) : 0;
    return [[a[0]+f*dx,a[1]+f*dy],f];
  }
  function collar(w,s,c) {
    const u=motion(c,s.tick*w.tick_ms)*(s.nodes.length-1),i=clamp(Math.floor(u),0,s.nodes.length-2),f=u-i;
    const a=s.nodes[i],b=s.nodes[i+1];
    return [[a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1])],i];
  }
  function isolated(w,s) {
    return s.grips.every((g,i)=>Math.abs(g.y-motion(w.ports[i],s.tick*w.tick_ms))+w.grip_radius<=w.ports[i].radius+1e-7);
  }
  function stretch(w,s) {return Math.max(...w.rest_lengths.map((r,i)=>dist(s.nodes[i],s.nodes[i+1])/r));}
  function constraint(nodes,i,j,rest,strength=1) {
    const a=nodes[i],b=nodes[j],dx=b[0]-a[0],dy=b[1]-a[1],d=Math.hypot(dx,dy);
    if(d<1e-10)return;
    const wa=Number(i!==0),wb=Number(j!==nodes.length-1);
    if(!wa&&!wb)return;
    const q=(d-rest)/d*strength/(wa+wb);
    if(wa){a[0]+=dx*q;a[1]+=dy*q;}if(wb){b[0]-=dx*q;b[1]-=dy*q;}
  }
  function pegCollision(nodes,peg,radius) {
    const center=[peg.x,peg.y];
    for(let i=0;i<nodes.length-1;i++) {
      const [p,f]=closest(center,nodes[i],nodes[i+1]);let dx=p[0]-center[0],dy=p[1]-center[1],d=Math.hypot(dx,dy);
      if(d>=radius)continue;if(d<1e-10){dx=0;dy=1;d=1;}
      const wa=i>0?1-f:0,wb=i+1<nodes.length-1?f:0;if(wa+wb<1e-9)continue;
      const q=(radius-d)/d/(wa*wa+wb*wb);
      nodes[i][0]+=dx*q*wa;nodes[i][1]+=dy*q*wa;nodes[i+1][0]+=dx*q*wb;nodes[i+1][1]+=dy*q*wb;
    }
  }
  function step(w,s) {
    if(!s.started||s.failed||s.complete)return;
    const dt=w.tick_ms/1000;s.tick++;
    for(const g of s.grips){
      const a=clamp(w.servo_gain**2*(g.target-g.y)-2*w.servo_gain*g.v,-w.servo_acceleration,w.servo_acceleration);
      g.v=clamp(g.v+dt*a,-w.servo_speed,w.servo_speed);g.y=clamp(g.y+dt*g.v,...w.rail_bounds);
    }
    const nodes=s.nodes,old=clone(nodes);
    const force=motion({seed:w.flow_seed,center:0,amplitude:w.parameters.flow_acceleration,span_ms:2300},s.tick*w.tick_ms);
    for(let i=1;i<nodes.length-1;i++){
      nodes[i][0]+=(nodes[i][0]-s.previous[i][0])*w.damping;
      nodes[i][1]+=(nodes[i][1]-s.previous[i][1])*w.damping+force*dt*dt;
    }
    nodes[0]=[w.ports[0].x,s.grips[0].y];nodes[nodes.length-1]=[w.ports[1].x,s.grips[1].y];
    const braces=new Set(w.collars.filter(c=>!s.removed.includes(c.id)).map(c=>collar(w,s,c)[1]));
    for(let k=0;k<w.constraint_iterations;k++){
      w.rest_lengths.forEach((r,i)=>constraint(nodes,i,i+1,r));
      for(const i of braces)if(i+2<nodes.length)constraint(nodes,i,i+2,w.bend_lengths[i],w.clamp_stiffness);
      pegCollision(nodes,w.peg,w.peg.radius+w.cable_radius);
    }
    for(const node of nodes.slice(1,-1)){node[0]=clamp(node[0],35,w.width-35);node[1]=clamp(node[1],35,w.height-35);}
    s.previous=old;
    const safe=isolated(w,s)&&stretch(w,s)<=w.max_stretch;
    s.energy=clamp(s.energy+dt*(safe?-w.discharge_rate:w.recharge_rate),0,1);
    for(const c of w.contacts)if(nodes.slice(0,-1).some((a,i)=>dist(closest([c.x,c.y],a,nodes[i+1])[0],[c.x,c.y])<=c.radius+w.cable_radius))s.failed='RED CONTACT';
    if(s.tick*w.tick_ms>=w.max_time_ms)s.failed='AUTOPSY EXPIRED';
  }
  function cut(w,s,a,b) {
    if(!isolated(w,s)||stretch(w,s)>w.max_stretch){s.failed='CABLE NOT ISOLATED';return [];}
    if(s.energy>w.cut_energy_limit+1e-9){s.failed='COLLAR STILL ENERGIZED';return [];}
    const hits=w.collars.filter(c=>!s.removed.includes(c.id)&&dist(closest(collar(w,s,c)[0],a,b)[0],collar(w,s,c)[0])<=c.radius).map(c=>c.id);
    if(!hits.length||dist(a,b)<8){s.failed='BARE WIRE / MISSED COLLAR';return [];}
    const masks=w.collars.filter(c=>hits.includes(c.id)).map(c=>[collar(w,s,c)[0],c.radius]),n=Math.ceil(dist(a,b)/2);
    for(let j=0;j<=n;j++){
      const f=j/Math.max(1,n),p=[a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1])];
      if(w.contacts.some(c=>dist(p,[c.x,c.y])<=c.radius)){s.failed='BLADE TOUCHED RED CONTACT';return [];}
      if(s.nodes.slice(0,-1).some((a,i)=>dist(closest(p,a,s.nodes[i+1])[0],p)<=w.cable_radius+2)&&!masks.some(([p0,r])=>dist(p,p0)<=r+2)){s.failed='BARE WIRE CUT';return [];}
    }
    s.removed=[...new Set([...s.removed,...hits])].sort((a,b)=>a-b);s.complete=s.removed.length===w.collars.length;
    if(!s.complete)s.energy=Math.min(1,s.energy+w.exposed_energy);return hits;
  }
  function record(kind,extra={},surface='start_button') {m.events.push({seq:m.events.length+1,kind,tick:m.physics.tick,surface,...extra});}
  function sync() {
    if(!m?.physics.started||m.terminal)return;
    const target=Math.floor(Math.max(0,performance.now()-m.startedAt)/m.w.tick_ms);
    while(m.physics.tick<target&&!m.physics.failed&&!m.physics.complete){
      step(m.w,m.physics);
      if(m.physics.tick%4===0){m.history.push({tick:m.physics.tick,nodes:clone(m.physics.nodes)});m.history=m.history.filter(h=>h.tick>=m.physics.tick-m.w.trail_window_ms/m.w.tick_ms);}
    }
    if(m.physics.failed)finish();
  }
  function payload() {return {mechanic_id:ID,task_id:m.state.task_id,challenge_id:m.state.challenge_id,
    revision:m.state.revision,interaction_mode:m.mode,events:clone(m.events),
    final_state:clone(m.physics),completed:m.physics.complete&&!m.physics.failed};}
  async function finish() {
    if(m.terminal)return;m.terminal=true;m.drag=null;m.knife=null;m.result=payload();paint();
    if(m.physics.failed)try{sessionStorage.setItem(m.failureKey,m.physics.failed);}catch(_){}
    m.helpers.setReadout(m.physics.failed?`FAIL · ${m.physics.failed}`:'VERIFYING AUTOPSY…',m.physics.failed?'error':'pending');
    try {
      const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(m.result)});
      m.outcome=await r.json();
      if(!m.outcome.passed)try{sessionStorage.setItem(m.failureKey,m.physics.failed||'REPLAY REJECTED');}catch(_){}
      m.helpers.setReadout(m.outcome.passed?'PASS · CABLE ISOLATED':`FAIL · ${m.physics.failed||'REPLAY REJECTED'}`,m.outcome.passed?'passed':'error');paint();
    } catch(e){m.helpers.setReadout(`VERIFIER ERROR · ${e.message}`,'error');}
  }
  function start() {
    if(m.physics.started||m.terminal)return;
    m.startedAt=performance.now();m.physics.started=true;record('start');paint();
  }
  function target(i,p) {
    if(!m.physics.started||m.terminal)return;
    sync();if(m.terminal)return;
    const point=[m.w.ports[i].x,p[1]];
    m.physics.grips[i].target=clamp(point[1],...m.w.rail_bounds);
    record('target',{grip:i,point},m.mode==='full'?'gripper_drag':'rail_click');paint();
  }
  function stroke(a,b) {
    sync();if(m.terminal||!m.physics.started)return;
    const removed=cut(m.w,m.physics,a,b);
    record('cut',{a,b,removed},m.mode==='full'?'knife_drag':'knife_two_clicks');
    m.lastStroke={a,b,tick:m.physics.tick};m.knife=null;
    if(m.physics.failed||m.physics.complete)finish();paint();
  }
  function pointer(e) {
    const r=m.canvas.getBoundingClientRect();return [clamp((e.clientX-r.left)*m.w.width/r.width,0,m.w.width),clamp((e.clientY-r.top)*m.w.height/r.height,0,m.w.height)];
  }
  function down(e) {
    if(e.button!==0||!m.physics.started||m.terminal)return;
    sync();if(m.terminal)return;const p=pointer(e);e.preventDefault();
    if(m.tool==='knife'){
      if(m.mode==='full'){m.knife={a:p,b:p,id:e.pointerId};m.canvas.setPointerCapture(e.pointerId);}
      else if(m.knife)stroke(m.knife.a,p);else m.knife={a:p,b:p};
      paint();return;
    }
    const i=m.w.ports.findIndex((port,i)=>dist(p,[port.x,m.physics.grips[i].y])<=26);
    if(m.mode==='full'&&i>=0){
      m.drag={grip:i,id:e.pointerId};m.canvas.setPointerCapture(e.pointerId);record('grip_begin',{grip:i,point:p},'gripper_drag');
    } else if(m.mode==='simplified'&&Math.abs(p[0]-m.w.ports[m.selected].x)<=38)target(m.selected,p);
    paint();
  }
  function move(e) {
    if(m.terminal)return;
    if(m.drag)target(m.drag.grip,pointer(e));
    if(m.knife){m.knife.b=pointer(e);paint();}
  }
  function up(e) {
    if(m.terminal)return;
    if(m.drag){sync();if(m.terminal)return;const i=m.drag.grip;target(i,pointer(e));record('grip_end',{grip:i},'gripper_drag');m.drag=null;}
    else if(m.knife&&m.mode==='full')stroke(m.knife.a,pointer(e));
    if(m.canvas.hasPointerCapture(e.pointerId))m.canvas.releasePointerCapture(e.pointerId);paint();
  }
  function cancel() {
    if(m.drag&&!m.terminal){sync();if(!m.terminal)record('grip_end',{grip:m.drag.grip},'gripper_drag');}
    m.drag=null;m.knife=null;paint();
  }
  function circle(ctx,p,r,fill,stroke,width=2) {
    ctx.beginPath();ctx.arc(p[0],p[1],r,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.stroke();
  }
  function line(ctx,points,color,width=2) {ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();}
  function paint() {
    if(!m)return;const w=m.w,s=m.physics,ctx=m.canvas.getContext('2d');
    ctx.clearRect(0,0,w.width,w.height);ctx.fillStyle='#101f2b';ctx.fillRect(0,0,w.width,w.height);
    ctx.strokeStyle='#233c4c';ctx.lineWidth=1;for(let x=30;x<w.width;x+=40)line(ctx,[[x,0],[x,w.height]],'#1b303e',1);for(let y=30;y<w.height;y+=40)line(ctx,[[0,y],[w.width,y]],'#1b303e',1);
    const ms=s.tick*w.tick_ms;
    for(let i=0;i<2;i++){
      const p=w.ports[i],y=motion(p,ms);line(ctx,[[p.x,70],[p.x,390]],'#617989',8);
      ctx.setLineDash([3,7]);line(ctx,Array.from({length:11},(_,j)=>[p.x,motion(p,Math.max(0,ms-800+j*80))]),'#7ecca5',3);ctx.setLineDash([]);
      circle(ctx,[p.x,y],p.radius,'#143e3c','#57d6aa',3);
      // Keep the bounded motion trace outside the opaque port. Horizontal
      // progression marks age; the bright endpoint is the current position.
      const trace=Array.from({length:11},(_,j)=>[i?w.width-7-j*2:9+j*2,motion(p,Math.max(0,ms-800+j*80))]);
      line(ctx,trace,'#84cdb7',2);circle(ctx,trace[10],3,'#d1ffeb','#d1ffeb',1);
      const fits=Math.abs(s.grips[i].y-y)+w.grip_radius<=p.radius+1e-7;
      circle(ctx,[p.x,s.grips[i].y],w.grip_radius,fits?'#b0ffce':'#d9d8c9',fits?'#e8fff0':'#99acba',3);
      ctx.font='bold 17px sans-serif';ctx.textAlign='center';ctx.fillStyle='#f3ecd7';ctx.fillText(i?'B':'A',p.x,41);
      line(ctx,[[p.x+23,s.grips[i].target-6],[p.x+32,s.grips[i].target],[p.x+23,s.grips[i].target+6]],'#efc174',2);
    }
    circle(ctx,[w.peg.x,w.peg.y],w.peg.radius,'#334c5d','#9ca9ac',3);
    ctx.fillStyle='#becdd1';ctx.font='11px sans-serif';ctx.fillText('INSULATOR',w.peg.x,w.peg.y+4);
    for(const c of w.contacts){circle(ctx,[c.x,c.y],c.radius,'#92293e','#ff6674',3);ctx.fillStyle='#ffbdc0';ctx.font='bold 15px sans-serif';ctx.fillText('×',c.x,c.y+5);}
    for(let i=0;i<m.history.length;i+=3)line(ctx,m.history[i].nodes,'#2b4e61',2);
    line(ctx,s.nodes,'#01090e',13);line(ctx,s.nodes,'#b8d2d6',w.cable_radius*2);line(ctx,s.nodes,'#e5f8f6',2);
    for(const c of w.collars){
      if(s.removed.includes(c.id))continue;
      const p=collar(w,s,c)[0];
      const trail=m.history.map(h=>collar(w,{...s,tick:h.tick,nodes:h.nodes},c)[0]);
      circle(ctx,p,c.radius,'#b66f33','#ffc989',3);
      // Paint recent centers above the cuff fill so slow motion remains visible
      // even when its entire bounded trace lies inside the current copper disc.
      line(ctx,trail,'#ffe8bf',2);
      if(trail.length)circle(ctx,trail[0],2,'#654020','#ffe8bf',1);
      ctx.fillStyle='#24190e';ctx.font='bold 15px sans-serif';ctx.fillText('✂',p[0],p[1]+5);
    }
    if(m.knife)line(ctx,[m.knife.a,m.knife.b],'#fff5c7',3);
    if(m.lastStroke&&s.tick-m.lastStroke.tick<25)line(ctx,[m.lastStroke.a,m.lastStroke.b],s.failed?'#ff637b':'#faf9df',3);
    const safe=isolated(w,s)&&stretch(w,s)<=w.max_stretch;
    ctx.fillStyle='#09141d';ctx.fillRect(200,3,460,26);ctx.fillStyle=s.energy<=w.cut_energy_limit?'#68d9a6':'#cb945a';ctx.fillRect(205,8,450*s.energy,14);
    ctx.strokeStyle=s.energy<=w.cut_energy_limit?'#97efbf':'#94aab4';ctx.lineWidth=2;ctx.strokeRect(205,8,450,14);
    ctx.fillStyle='#dce8e3';ctx.font='bold 11px sans-serif';ctx.fillText(s.energy<=w.cut_energy_limit?'CAPACITOR SAFE · CUT WHILE ISOLATED':'CAPACITOR ENERGY · KEEP BOTH ENDS ISOLATED',430,35);
    m.root.dataset.isolated=String(safe);m.root.dataset.started=String(s.started);m.root.dataset.terminal=String(m.terminal);
    m.root.dataset.removed=String(s.removed.length);m.root.dataset.tick=String(s.tick);
    document.getElementById('zg-isolation').textContent=safe?(s.energy<=w.cut_energy_limit?'SAFE TO SLICE':'DISCHARGING'):'TRACK BOTH PORTS';
    document.getElementById('zg-isolation').dataset.safe=String(safe);
    document.getElementById('zg-collars').textContent=`${s.removed.length} / ${w.collars.length} COLLARS REMOVED`;
    document.getElementById('zg-start').disabled=s.started||m.terminal;
    document.getElementById('zg-tool').disabled=m.terminal;
    document.getElementById('zg-seal').disabled=m.terminal;
    document.getElementById('zg-tool').textContent=m.tool==='knife'?'KNIFE ARMED · SWITCH TO GRIPPERS':'ARM KNIFE';
    document.querySelectorAll('[data-zg-select]').forEach(b=>{b.dataset.selected=String(Number(b.dataset.zgSelect)===m.selected);b.disabled=m.terminal;});
    if(m.terminal){ctx.fillStyle='#09151bdc';ctx.fillRect(170,175,520,110);ctx.fillStyle=s.failed?'#ff8695':'#aff3c9';ctx.font='bold 34px sans-serif';ctx.fillText(s.failed?'AUTOPSY FAILED':'CABLE ISOLATED',430,223);ctx.font='16px sans-serif';ctx.fillText(s.failed||'All copper braces removed. Inner wire preserved.',430,257);}
  }
  function animate(){if(!m)return;sync();paint();frame=requestAnimationFrame(animate);}
  async function render(state,helpers) {
    if(cleanup)cleanup();cancelAnimationFrame(frame);document.body.dataset.mechanic=ID;
    const w=state.world;
    helpers.app.innerHTML=`<section class="zg2" data-interaction="${state.control_condition.interaction}"><header><div><p>VACUUM FORENSICS / LIVE CABLE</p><h1>Zero-G Cable Autopsy V2</h1></div><span id="zg-collars"></span></header><div class="zg2-instruction">Keep both ends inside moving ports until capacitor energy is green. Slice a copper collar. Each removed brace exposes another charged section.</div><canvas id="zg-canvas" width="860" height="470" aria-label="Cable, isolation ports, insulating peg and travelling copper collars"></canvas><div class="zg2-controls"><button id="zg-start">ENERGIZE CABLE</button><span id="zg-isolation"></span><button data-zg-select="0">GRIPPER A</button><button data-zg-select="1">GRIPPER B</button><button id="zg-tool">ARM KNIFE</button><button id="zg-seal">SEAL AUTOPSY</button></div><div class="zg2-help">${state.control_condition.interaction==='full'?'Drag a gripper along its rail. Arm the knife and drag a short stroke through a collar.':'Select A or B, then click its rail. Arm the knife and click the two ends of a short stroke through a collar.'} Release while isolated and safe. Bare-wire cuts and red contacts end the attempt. Motion continues while holding tools. Trails show the last 0.8 s; bright dots mark the newest port positions.</div><footer class="readout">Inspect before energizing. One live attempt.</footer></section>`;
    m={state,helpers,w,physics:{tick:0,nodes:clone(w.nodes),previous:clone(w.nodes),grips:[{y:210,v:0,target:210},{y:210,v:0,target:210}],removed:[],failed:'',complete:false,started:false,energy:1},mode:state.control_condition.interaction,events:[],history:[],terminal:false,selected:0,tool:'grip',knife:null,drag:null,startedAt:0,root:document.querySelector('.zg2'),canvas:document.getElementById('zg-canvas')};
    window.zeroGCableV2Model=m;
    m.failureKey=`${ID}:terminal:${state.task_id}:${location.pathname}:${location.search}`;
    try{const prior=sessionStorage.getItem(m.failureKey);if(prior){m.physics.failed=prior;m.terminal=true;m.outcome={passed:false};helpers.setReadout(`FAIL · ${prior}`,'error');}}catch(_){}
    document.getElementById('zg-start').addEventListener('click',start);
    document.getElementById('zg-tool').addEventListener('click',()=>{if(m.terminal)return;cancel();m.tool=m.tool==='knife'?'grip':'knife';paint();});
    document.querySelectorAll('[data-zg-select]').forEach(b=>b.addEventListener('click',()=>{if(m.terminal)return;m.selected=Number(b.dataset.zgSelect);m.tool='grip';m.knife=null;paint();}));
    document.getElementById('zg-seal').addEventListener('click',()=>{if(m.terminal)return;if(!m.physics.started)start();sync();if(m.terminal)return;record('seal',{},'seal_button');m.physics.failed='INCOMPLETE AUTOPSY';finish();});
    m.canvas.addEventListener('pointerdown',down);m.canvas.addEventListener('pointermove',move);m.canvas.addEventListener('pointerup',up);m.canvas.addEventListener('pointercancel',cancel);m.canvas.addEventListener('lostpointercapture',()=>{if(m.drag)cancel();});
    cleanup=()=>{cancelAnimationFrame(frame);m=null;};paint();frame=requestAnimationFrame(animate);
  }
  window.ZeroGCableV2Physics={noise,motion,step,collar,isolated,stretch,cut};
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.zg2',render};
})();
