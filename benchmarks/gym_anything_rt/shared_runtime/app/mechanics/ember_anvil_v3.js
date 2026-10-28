(() => {
  'use strict';
  let m, frame = 0;
  const D = [[1,0],[0,1],[-1,0],[0,-1]], names = ['E','S','W','N'];
  const $ = s => m.helpers.app.querySelector(s);
  const clean = s => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const q = x => Math.round(x*1000)/1000;
  function noise(seed,index) {
    let x = ((seed>>>0)^Math.imul(index+1,0x9e3779b9))>>>0;
    x = Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x = Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function motion(seed,ms,span) {
    const u=Math.max(0,ms)/span,index=Math.floor(u),f=u-index,a=noise(seed,index),b=noise(seed,index+1);
    return a+(b-a)*f*f*(3-2*f);
  }
  function pose(w,ms) {
    const v=w.travel.map((a,i)=>a*motion(w.motion_seed+i*7919,ms,w.motion_span_ms));
    return [w.origin[0]+v[0],w.origin[1]+v[1],v[2]];
  }
  function heat(w,i,ms) { return .60+.40*motion(w.heat_seeds[i],ms,w.heat_span_ms); }
  function project(w,x,y,ms) {
    const [cx,cy,a]=pose(w,ms);x=(x-w.size/2)*w.cell_px;y=(y-w.size/2)*w.cell_px;
    return [cx+x*Math.cos(a)-y*Math.sin(a),cy+x*Math.sin(a)+y*Math.cos(a)];
  }
  function contact(w,p,ms) {
    const [cx,cy,a]=pose(w,ms),dx=p[0]-cx,dy=p[1]-cy;
    const x=(dx*Math.cos(a)+dy*Math.sin(a))/w.cell_px+w.size/2,y=(-dx*Math.sin(a)+dy*Math.cos(a))/w.cell_px+w.size/2;
    const ix=Math.floor(x),iy=Math.floor(y),edge=w.face_inset/w.cell_px;
    return ix<0||ix>=w.size||iy<0||iy>=w.size||x-ix<edge||x-ix>1-edge||y-iy<edge||y-iy>1-edge?null:iy*w.size+ix;
  }
  function strike(w,h,tool,d,p,ms) {
    const out=h.slice(),i=contact(w,p,ms);
    if(i===null||!h[i])return [out,i,'air',0];
    if(heat(w,i,ms)<w.workable)return [out,i,'cold',0];
    if(tool==='split'){out[i]--;return [out,i,'split',1];}
    const x=i%w.size+D[d][0],y=Math.floor(i/w.size)+D[d][1],j=y*w.size+x;
    if(x<0||x>=w.size||y<0||y>=w.size||h[j]>=w.cap||(tool==='draw'&&h[j]>=h[i])||(tool==='upset'&&h[j]!==h[i]))return [out,i,'blocked',0];
    out[i]--;out[j]++;return [out,i,'moved',0];
  }
  window.EmberAnvilV3Math={noise,motion,pose,heat,contact,strike};
  function now() { return m.begun?Math.min(m.w.run_ms,Math.max(0,Math.floor(performance.now()-m.startedAt))):0; }
  function log(kind,data={},input_source='tool_control',t_ms=now()) {
    m.events.push({seq:m.events.length+1,kind,t_ms,input_source,...data});
  }
  function point(e) {
    const r=$('#eav-work').getBoundingClientRect();
    return [q((e.clientX-r.left)*860/r.width),q((e.clientY-r.top)*450/r.height)];
  }
  function message(text,status='idle') { $('#eav-message').textContent=text;m.helpers.setReadout(text,status); }
  function begin() {
    if(m.begun||m.terminal)return;
    m.startedAt=performance.now();m.begun=true;log('begin',{},'tool_control',0);
    $('#eav-begin').disabled=true;message('FORGE LIVE · Strike the glowing metal.');paint();
  }
  function polygon(ctx,points,fill,stroke,width=1) {
    ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();
    if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.stroke();}
  }
  function hammer(ctx,x,y,held=false) {
    ctx.save();ctx.translate(x,y);ctx.rotate(held?-.35:-.65);
    ctx.fillStyle='#a17a50';ctx.strokeStyle='#4a3420';ctx.lineWidth=2;ctx.fillRect(-5,0,10,35);ctx.strokeRect(-5,0,10,35);
    ctx.fillStyle='#b8c4c5';ctx.strokeStyle='#e9eeea';ctx.fillRect(-20,-10,40,19);ctx.strokeRect(-20,-10,40,19);ctx.restore();
  }
  function drawTarget() {
    const c=$('#eav-target'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);
    const size=24, p=(x,y,z)=>[125+(x-y)*size,69+(x+y-5)*size*.48-z*12];
    polygon(ctx,[p(-.3,-.3,0),p(5.3,-.3,0),p(5.3,5.3,0),p(-.3,5.3,0)],'#152d2c','#45615a');
    const cubes=[];
    // Only measured columns belong to the relief sketch. The concealed die's
    // unmeasured shape must not leak through the isometric view or layer dots.
    m.measurements.forEach((h,i)=>{for(let z=0;z<(h??0);z++)cubes.push([i%5,Math.floor(i/5),z]);});
    cubes.sort((a,b)=>a[0]+a[1]-b[0]-b[1]||a[2]-b[2]);
    for(const [x,y,z] of cubes){const top=[p(x,y,z+1),p(x+1,y,z+1),p(x+1,y+1,z+1),p(x,y+1,z+1)];
      polygon(ctx,[top[1],top[2],p(x+1,y+1,z),p(x+1,y,z)],'#34645b','#122c29');
      polygon(ctx,[top[2],top[3],p(x,y+1,z),p(x+1,y+1,z)],'#254840','#122c29');
      polygon(ctx,top,'#82b99b','#c0d6ad');
    }
    ctx.fillStyle='#c5d5bc';ctx.font='10px system-ui';ctx.textAlign='center';
    ctx.fillText('CLICK SQUARES TO GAUGE THE DIE',125,121);
    // A depth gauge reads one location in the closed die. Its persistent
    // measurements include empty locations, not just the occupied silhouette.
    for(let i=0;i<25;i++){const x=55+(i%5)*28,y=133+Math.floor(i/5)*28,h=m.measurements[i];
      ctx.fillStyle=h===null?'#3a4850':h?'#345c4c':'#162b27';ctx.fillRect(x,y,26,26);ctx.strokeStyle='#82958a';ctx.strokeRect(x,y,26,26);
      if(h===null){ctx.fillStyle='#d3d8d3';ctx.font='14px system-ui';ctx.fillText('?',x+13,y+18);}
      else if(h===0){ctx.fillStyle='#a8b9b2';ctx.font='11px system-ui';ctx.fillText('0',x+13,y+17);}
      else for(let j=0;j<h;j++){ctx.fillStyle='#d9e9c1';ctx.beginPath();ctx.arc(x+6+j*5,y+13,2,0,Math.PI*2);ctx.fill();}}
    ctx.fillStyle='#c5d5bc';ctx.font='11px system-ui';ctx.textAlign='center';ctx.fillText('E →    S ↓   ·   dots = layers',125,294);
  }
  function inspect(e) {
    if(e.button!==0||m.terminal||m.hold)return;
    const r=$('#eav-target').getBoundingClientRect();
    const p=[q((e.clientX-r.left)*250/r.width),q((e.clientY-r.top)*308/r.height)];
    const x=Math.floor((p[0]-55)/28),y=Math.floor((p[1]-133)/28);
    if(x<0||x>=5||y<0||y>=5||p[0]-(55+x*28)>26||p[1]-(133+y*28)>26)return;
    const cell=y*5+x,layers=m.w.target[cell];m.measurements[cell]=layers;
    log('inspect',{point:p,cell,layers},'target_gauge');
    message(`DIE GAUGE · column ${x+1}, row ${y+1}: ${layers} layer${layers===1?'':'s'}. Measurement retained.`);
    drawTarget();paint();
  }
  function paint() {
    const t=m.terminal?m.finalMs:now(),c=$('#eav-work'),ctx=c.getContext('2d');m.currentMs=t;
    const g=ctx.createLinearGradient(0,0,0,450);g.addColorStop(0,'#142229');g.addColorStop(1,'#263035');ctx.fillStyle=g;ctx.fillRect(0,0,860,450);
    ctx.strokeStyle='#43515a';ctx.lineWidth=4;for(const y of [48,352]){ctx.beginPath();ctx.moveTo(30,y);ctx.lineTo(830,y);ctx.stroke();}
    ctx.fillStyle='#31434b';for(let x=40;x<830;x+=55){ctx.fillRect(x,40,18,16);ctx.fillRect(x,344,18,16);}
    // The controller projects a short, finite path. It never exposes the complete seed tape.
    ctx.strokeStyle='#e8b96788';ctx.lineWidth=2;ctx.setLineDash([4,5]);ctx.beginPath();
    for(let d=0;d<=1200;d+=80){const [x,y]=pose(m.w,t+d);d?ctx.lineTo(x,y):ctx.moveTo(x,y);}ctx.stroke();ctx.setLineDash([]);
    for(const d of [400,800,1200]){const [x,y]=pose(m.w,t+d);ctx.fillStyle='#e5c793';ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();}
    const [cx,cy,a]=pose(m.w,t);ctx.save();ctx.translate(cx,cy);ctx.rotate(a);
    ctx.shadowBlur=18;ctx.shadowColor='#030b0d';ctx.fillStyle='#0a1114';ctx.fillRect(-123,-117,246,245);ctx.shadowBlur=0;
    ctx.fillStyle='#43575f';ctx.strokeStyle='#799198';ctx.lineWidth=3;ctx.fillRect(-119,-119,238,238);ctx.strokeRect(-119,-119,238,238);
    const inset=m.w.face_inset;
    for(let i=0;i<25;i++){
      const x=(i%5-2.5)*44+inset,y=(Math.floor(i/5)-2.5)*44+inset,h=m.h[i],hot=heat(m.w,i,t)>=m.w.workable;
      ctx.fillStyle=h?(hot?'#e68a3d':'#654b42'):'#26373d';ctx.fillRect(x,y,44-2*inset,44-2*inset);
      ctx.strokeStyle=h?(hot?'#ffdb8d':'#9b7a62'):'#53636a';ctx.lineWidth=1;ctx.strokeRect(x,y,44-2*inset,44-2*inset);
      if(h){for(let j=0;j<h;j++){ctx.fillStyle=hot?'#fff0b8':'#d7c2a0';ctx.beginPath();ctx.arc(x+9+j*6,y+18,2.3,0,Math.PI*2);ctx.fill();}
        for(let j=1;j<=3;j++){ctx.fillStyle=heat(m.w,i,t+j*400)>=m.w.workable?'#c8eb90':'#302c2c';ctx.fillRect(x+8+(j-1)*10,y+28,7,5);}
        if(m.hover===i){ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.strokeRect(x+1,y+1,38,38);}}
    }
    ctx.textAlign='center';ctx.font='bold 16px system-ui';
    const ds=[[138,5],[0,142],[-138,5],[0,-133]];
    ds.forEach(([x,y],i)=>{ctx.fillStyle=i===m.direction?'#ffdc92':'#b4c3c7';ctx.fillText(names[i],x,y);});
    ctx.restore();
    // One labelled future frame stays visible even when it overlaps the billet.
    // Its 220px edge equals five real cells; it never supplies an aimed action.
    const [fx,fy,fa]=pose(m.w,t+800);ctx.save();ctx.translate(fx,fy);ctx.rotate(fa);
    ctx.strokeStyle='#92cbe8';ctx.lineWidth=1.8;ctx.setLineDash([5,7]);ctx.strokeRect(-110,-110,220,220);ctx.setLineDash([]);
    ctx.fillStyle='#92cbe8';ctx.font='bold 11px system-ui';ctx.textAlign='center';ctx.fillText('E +0.8s',145,-8);ctx.fillText('S +0.8s',0,129);ctx.restore();
    ctx.fillStyle='#acb7b9';ctx.font='11px system-ui';ctx.textAlign='left';ctx.fillText('DASHED FRAME: +0.8 s · CARRIAGE TRACE: NEXT 1.2 s',22,23);
    const [hx,hy,hw,hh]=m.w.hammer_box;ctx.fillStyle=m.hold?'#384950':'#1e2b31';ctx.strokeStyle='#829797';ctx.lineWidth=1;ctx.fillRect(hx,hy,hw,hh);ctx.strokeRect(hx,hy,hw,hh);
    hammer(ctx,hx+30,hy+16);ctx.fillStyle='#dae0d9';ctx.font='bold 10px system-ui';ctx.fillText(m.mode==='full'?'DRAG':'HAMMER',hx+57,hy+25);
    if(m.hold&&m.pointer)hammer(ctx,...m.pointer,true);
    if(m.flash&&t<m.flash.until){ctx.strokeStyle='#ffe3a3';ctx.lineWidth=3;ctx.beginPath();ctx.arc(...m.flash.point,18,0,Math.PI*2);ctx.stroke();}
    $('#eav-elapsed').textContent=m.begun?`${Math.ceil((m.w.run_ms-t)/1000)} s fuel`:'PREPARATION';
    $('#eav-ledger').textContent=`Metal ${m.h.reduce((a,b)=>a+b,0)} · split ${m.discarded}`;
    $('#eav-tool').textContent=`${m.tool.toUpperCase()} · ${names[m.direction]}`;
  }
  async function finish(reason='') {
    if(m.terminal)return;
    m.finalMs=now();m.terminal=true;m.hold=null;log('stamp',{},'tool_control',m.finalMs);
    m.helpers.app.querySelectorAll('button').forEach(b=>b.disabled=true);
    const completed=!reason&&m.h.every((v,i)=>v===m.w.target[i]);
    const payload={mechanic_id:m.state.mechanic_id,task_id:m.state.task_id,challenge_id:m.state.challenge_id,
      interaction_mode:m.mode,events:m.events,heights:m.h.slice(),discarded:m.discarded,final_t_ms:m.finalMs,completed};
    message(reason?`FAIL · ${reason}`:'STAMPING THE TOOL…',reason?'error':'pending');paint();
    $('#eav-verdict').classList.add('show');$('#eav-verdict').textContent=reason?`FAIL · ${reason}`:'VERIFYING';
    try {
      const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)}),out=await r.json();
      const passed=out.passed===true;
      $('#eav-verdict').classList.toggle('pass',passed);$('#eav-verdict').textContent=passed?'PASS · TOOL ACCEPTED':`FAIL · ${reason||'TOOL DOES NOT MATCH'}`;
      message(passed?'PASS · TOOL ACCEPTED':'FAIL · EPISODE ENDED · NO RETRY',passed?'passed':'error');
    }catch(e){$('#eav-verdict').textContent='STAMP LINK ERROR · ATTEMPT SEALED';message('Stamp link error.','error');}
  }
  function hit(p) {
    if(!m.begun||m.terminal)return;
    const t=now(),[h,i,outcome,lost]=strike(m.w,m.h,m.tool,m.direction,p,t);m.h=h;m.discarded+=lost;
    log('strike',{point:p,cell:i,tool:m.tool,direction:m.direction,outcome,heights:h.slice()},m.mode==='full'?'hammer_drag':'contact_click',t);
    m.flash={point:p,until:t+240};
    const words={air:'AIR · No metal changed.',cold:'COLD · Wait for the local glow to return.',blocked:'BLOCKED · Check the neighbor heights.',moved:'Metal moved. Compare the relief.',split:'One layer split away permanently.'};message(words[outcome]);paint();
    if(h.reduce((a,b)=>a+b,0)<m.w.target.reduce((a,b)=>a+b,0))finish('INSUFFICIENT METAL');
  }
  function animate() {
    if(m&&!m.terminal){paint();if(m.begun&&now()>=m.w.run_ms)finish('FUEL EXHAUSTED');}
    frame=requestAnimationFrame(animate);
  }
  async function render(state,helpers) {
    cancelAnimationFrame(frame);document.body.dataset.mechanic='ember-anvil-v2';
    m={state,helpers,w:state.world,h:state.world.initial.slice(),mode:state.control_condition?.interaction||'full',
      events:[],measurements:Array(25).fill(null),tool:'draw',direction:0,discarded:0,begun:false,terminal:false,hold:null,hover:null,currentMs:0,startedAt:0,finalMs:0};
    window.emberAnvilV3Model=m;
    helpers.app.innerHTML=`<section class="ember-anvil-v2" data-interaction="${m.mode}">
      <header><div><small>THE FLOATING FOUNDRY</small><h1>Ember Anvil V3</h1></div><p>Shape a tool on a restless anvil.</p><b id="eav-elapsed"></b></header>
      <main><div class="eav-stage"><canvas id="eav-work" width="860" height="450" aria-label="Moving billet and physical hammer"></canvas><div id="eav-verdict"></div></div>
      <aside><small>TARGET DIE · ${clean(m.w.title)}</small><canvas id="eav-target" width="250" height="308" aria-label="Target die depth gauge: click a square to measure required layers"></canvas>
      <div class="eav-glow"><i></i><span>Bright metal can be worked.<br>Dark metal reheats in place.<br>Three pips: heat in 0.4 / 0.8 / 1.2 s.</span></div>
      <button id="eav-begin">LIGHT THE FORGE →</button><p>Gauge the die safely before lighting; measurements stay. ${m.mode==='full'?'Drag the hammer to a top face.':'Click a top face to strike.'} Direction turns with the billet. Inspection never stops forging.</p></aside></main>
      <section class="eav-tools"><div>${['draw','upset','split'].map(tool=>`<button data-tool="${tool}" class="${tool==='draw'?'selected':''}">${tool.toUpperCase()}<small>${{draw:'into lower metal',upset:'onto equal metal',split:'discard one layer'}[tool]}</small></button>`).join('')}</div>
      <div class="eav-directions">${names.map((name,i)=>`<button data-dir="${i}" class="${i===0?'selected':''}">${name}</button>`).join('')}</div><b id="eav-tool"></b></section>
      <footer><div><span id="eav-message">Gauge the target die. Air, cold and blocked hits are recoverable; terminal failure ends the episode.</span><small id="eav-ledger"></small><div class="readout" data-status="idle"></div></div><button id="eav-stamp">STAMP TOOL →</button></footer></section>`;
    $('#eav-target').addEventListener('click',inspect);
    $('#eav-begin').onclick=begin;$('#eav-stamp').onclick=()=>{if(m.begun&&!m.hold)finish();};
    $('[data-tool]').parentElement.onclick=e=>{const b=e.target.closest('[data-tool]');if(!b||m.terminal||m.hold)return;m.tool=b.dataset.tool;log('mode',{tool:m.tool});$('[data-tool]').parentElement.querySelectorAll('button').forEach(x=>x.classList.toggle('selected',x===b));paint();};
    $('.eav-directions').onclick=e=>{const b=e.target.closest('[data-dir]');if(!b||m.terminal||m.hold)return;m.direction=Number(b.dataset.dir);log('direction',{direction:m.direction});$('.eav-directions').querySelectorAll('button').forEach(x=>x.classList.toggle('selected',x===b));paint();};
    const c=$('#eav-work');
    c.addEventListener('pointerdown',e=>{if(e.button!==0||!m.begun||m.terminal||m.mode!=='full')return;const p=point(e),r=m.w.hammer_box;if(p[0]<r[0]||p[0]>r[0]+r[2]||p[1]<r[1]||p[1]>r[1]+r[3])return;e.preventDefault();c.setPointerCapture(e.pointerId);m.hold={id:e.pointerId,start:p};m.pointer=p;log('hammer_down',{point:p},'hammer_drag');paint();});
    c.addEventListener('pointermove',e=>{if(m.terminal)return;const p=point(e);m.hover=contact(m.w,p,now());if(m.hold?.id===e.pointerId)m.pointer=p;});
    c.addEventListener('pointerup',e=>{if(m.mode!=='full'||m.hold?.id!==e.pointerId||m.terminal)return;const p=point(e),start=m.hold.start;m.hold=null;if(c.hasPointerCapture(e.pointerId))c.releasePointerCapture(e.pointerId);if(Math.hypot(p[0]-start[0],p[1]-start[1])<8){log('hammer_cancel',{point:p},'hammer_drag');paint();return;}if(p[0]<0||p[0]>860||p[1]<0||p[1]>450){log('hammer_cancel',{point:start},'hammer_drag');paint();return;}hit(p);});
    for(const event of ['pointercancel','lostpointercapture'])c.addEventListener(event,e=>{if(m.hold?.id!==e.pointerId||m.terminal)return;const p=m.hold.start;m.hold=null;log('hammer_cancel',{point:p},'hammer_drag');paint();});
    c.addEventListener('click',e=>{if(m.mode==='simplified'&&e.button===0)hit(point(e));});
    drawTarget();paint();
    if(state.episode_failed||state.episode_history_error){
      m.terminal=true;m.helpers.app.querySelectorAll('button').forEach(b=>b.disabled=true);
      $('#eav-verdict').classList.add('show');$('#eav-verdict').textContent='FAIL · EPISODE ENDED';
      message(state.episode_history_error?'EPISODE HISTORY UNAVAILABLE · NO RETRY':'FAIL · EPISODE ENDED · NO RETRY','error');
    }
    frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.ember_anvil_v3={rootSelector:'.ember-anvil-v2',render};
})();
