(() => {
  'use strict';
  let model, frame;
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  function noise(seed,index) {
    let x=(seed^Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function motion(seed,t,span) {
    const u=Math.max(0,t)/span,n=Math.floor(u),f=u-n,a=noise(seed,n),b=noise(seed,n+1);
    return a+(b-a)*f*f*(3-2*f);
  }
  function demand(i,t) {
    const w=model.state.world,p=w.parameters,f=w.feeds[i];t+=f.phase_ms;
    return [1+p.speed_amplitude*motion(f.speed_seed,t,p.span_ms),p.height_amplitude*motion(f.height_seed,t,p.span_ms)];
  }
  function commandPoint(i,s) {
    const p=model.state.world.feeds[i].pad;
    return [p.x+(s.u-.4)/1.2*p.width,p.y+(1-s.q)/2*p.height];
  }
  function valuePoint(i,v,y) {return commandPoint(i,{u:v,q:y});}
  function record(kind,source,extra={}) {model.events.push({seq:model.events.length+1,kind,t_ms:model.t,input_source:source,...extra});}
  // One fixed simulation interval is consumed by each deliberate steering
  // input. Rendering, waiting, inspection, grip, and release never advance
  // the reader on their own.
  function advance() {
    if (model.status!=='running')return;
    const w=model.state.world,p=w.parameters,dt=w.tick_ms/1000,tau=p.response_ms/1000;
    const target=Math.min(w.duration_ms,model.t+w.action_step_ms);
    while(model.t<target&&model.status==='running') {
      model.t+=w.tick_ms;
      const vs=model.feeds.map(s=>s.v);
      model.feeds.forEach((s,i)=>{
        if(s.done)return;
        const other=model.feeds.length===2?vs[1-i]:vs[i];
        s.v+=(s.u-s.v+p.coupling*(other-s.v))*dt/tau;
        s.y+=(s.q-s.y)*dt/tau;
        const [v,y]=demand(i,model.t);
        const error=Math.max(0,Math.abs(s.y-y)/p.height_tolerance-1,Math.abs(s.v-v)/p.speed_tolerance-1);
        const distance=Math.min(s.v*dt,p.stripe_length-s.distance);
        s.damage+=distance*Math.min(1,error);s.distance+=distance;s.done=s.distance>=p.stripe_length-1e-9;
      });
      if(model.feeds.some(s=>s.damage>w.damage_limit+1e-9)) {
        model.status='failed';post('STRIPE DAMAGED');
      } else if(model.feeds.every(s=>s.done)) {
        model.status='ready';model.finalT=model.t;
        model.helpers.setReadout('ALL CARDS READ · CERTIFY THE STRIPES','pending');
      } else if(model.t>=w.duration_ms) {model.status='failed';post('FEED INCOMPLETE');}
    }
  }
  async function post(reason='') {
    if(model.posted)return;
    model.posted=true;model.finalT=model.t;
    if(reason)model.status='failed';
    document.querySelector('.ms2-verdict').textContent=reason?'FAIL · '+reason:'CHECKING STRIPES…';
    document.querySelector('.ms2-verdict').hidden=false;
    model.helpers.setReadout(reason?'FAIL · '+reason:'VERIFYING STRIPES…',reason?'error':'pending');
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      control_condition:model.state.control_condition,interaction_mode:model.mode,events:model.events,
      final_t_ms:model.t,completed:!reason,feeds:model.feeds.map(s=>({distance:s.distance,damage:s.damage}))};
    model.payload=payload;
    try {
      const r=await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      model.result=await r.json();
      model.helpers.setReadout(model.result.passed?'PASS · ALL STRIPES CERTIFIED':'FAIL · '+(reason||'READ NOT CERTIFIED'),model.result.passed?'passed':'error');
      document.querySelector('.ms2-verdict').textContent=model.result.passed?'PASS · CERTIFIED':'FAIL · '+(reason||'READ NOT CERTIFIED');
      document.querySelector('.ms2-verdict').dataset.passed=String(model.result.passed);
    } catch(e) {model.helpers.setReadout('VERIFIER ERROR · '+e.message,'error');}
  }
  function steer(i,point) {
    const p=model.state.world.feeds[i].pad,s=model.feeds[i];
    s.u=clamp(.4+(point[0]-p.x)/p.width*1.2,.4,1.6);s.q=clamp(1-(point[1]-p.y)/p.height*2,-1,1);
    record('steer',model.mode,{feed:i,point});
    if(model.status==='staged'){s.v=s.u;s.y=s.q;}
  }
  function paint() {
    const w=model.state.world,p=w.parameters,c=model.context;c.clearRect(0,0,w.width,w.height);
    c.fillStyle='#122a32';c.fillRect(0,0,w.width,w.height);
    c.strokeStyle='#203d43';c.lineWidth=1;
    for(let x=0;x<w.width;x+=28){c.beginPath();c.moveTo(x,0);c.lineTo(x,w.height);c.stroke();}
    for(let y=0;y<w.height;y+=28){c.beginPath();c.moveTo(0,y);c.lineTo(w.width,y);c.stroke();}
    function text(s,x,y,size=14,color='#abc3bf') {c.fillStyle=color;c.font=`${size}px ui-monospace, monospace`;c.fillText(s,x,y);}
    function circle(x,y,r,color){c.fillStyle=color;c.beginPath();c.arc(x,y,r,0,Math.PI*2);c.fill();}
    model.feeds.forEach((s,i)=>{
      const f=w.feeds[i],pad=f.pad,cy=w.feeds.length===1?244:135+i*218,[v,y]=demand(i,model.t);
      c.fillStyle='#24414a';c.fillRect(27,cy-95,731,192);c.strokeStyle='#597e81';c.strokeRect(27,cy-95,731,192);
      text(`${f.badge}  READER ${i+1}`,45,cy-68,18,f.color);
      text(s.done?'ACCEPTED':model.status==='staged'?'CARD LOADED':'READING',600,cy+101,14,s.done?'#98e4bc':f.color);
      // Normalize physical height upward in both the pad and the reader drawing.
      c.fillStyle='#081a22';c.fillRect(48,cy-46,672,103);
      const sy=cy-s.y*48,hy=cy-y*48;
      c.fillStyle='#decead';c.fillRect(54,sy-16,632,33);
      c.fillStyle=f.color;c.fillRect(55,sy-8,630,16);
      for(let k=0;k<80;k++) {
        c.fillStyle=k/80<p.stripe_length&&k/80<s.distance/p.stripe_length?'#527d74':'#273d42';
        c.fillRect(58+k*7.8,sy-7,2+(k%3),14);
      }
      const hx=65+Math.min(1,s.distance/p.stripe_length)*610;
      if(s.inspected) {
        c.fillStyle='#76e7bc44';c.fillRect(hx-14,hy-p.height_tolerance*48,28,p.height_tolerance*96);
        c.strokeStyle='#86efc2';c.lineWidth=3;c.strokeRect(hx-14,hy-p.height_tolerance*48,28,p.height_tolerance*96);
        c.fillStyle='#e4eee2';c.fillRect(hx-5,hy-3,10,6);
      } else {
        // The fixed opaque housing conceals the read-head setting, not the
        // card's actual motion. Its bounds do not leak the concealed height.
        c.fillStyle='#456068';c.fillRect(hx-16,cy-51,32,107);
        c.strokeStyle='#91a49a';c.strokeRect(hx-16,cy-51,32,107);
      }
      text('HEIGHT',45,cy+80,12);text('FEED',300,cy+80,12);
      const sx=362,sw=204;
      c.fillStyle='#091c24';c.fillRect(sx,cy+64,sw,16);
      if(s.inspected){c.fillStyle='#86efc266';c.fillRect(sx+(v-.4-p.speed_tolerance)/1.2*sw,cy+64,p.speed_tolerance/1.2*sw*2,16);}
      c.fillStyle=f.color;c.fillRect(sx+(s.v-.4)/1.2*sw-2,cy+59,4,27);
      text('DAMAGED',583,cy+80,12);
      c.fillStyle='#091c24';c.fillRect(652,cy+63,80,18);
      c.fillStyle='#ef8477';c.fillRect(652,cy+63,80*Math.min(1,s.damage/w.damage_limit),18);
      text(`${Math.floor(s.distance/p.stripe_length*100)}%`,45,cy+101,12,f.color);
      c.fillStyle='#0a1d25';c.fillRect(pad.x,pad.y,pad.width,pad.height);c.strokeStyle='#547a80';c.lineWidth=2;c.strokeRect(pad.x,pad.y,pad.width,pad.height);
      c.strokeStyle='#244b55';c.beginPath();c.moveTo(pad.x+pad.width/2,pad.y);c.lineTo(pad.x+pad.width/2,pad.y+pad.height);c.moveTo(pad.x,pad.y+pad.height/2);c.lineTo(pad.x+pad.width,pad.y+pad.height/2);c.stroke();
      text('SLOW  ←  FEED SPEED  →  FAST',pad.x+8,pad.y+pad.height+18,12);
      text('SWIPE GRIP / HEIGHT ↑',pad.x+6,pad.y-12,14,f.color);
      // Inspecting the real cam housing exposes this reader's seeded setting
      // and live incoming motion. It stays exposed in either input mode.
      if(s.inspected) {
        c.strokeStyle='#65a9b0';c.lineWidth=2;c.beginPath();
        for(let dt=-w.trace_ms;dt<=w.forecast_ms;dt+=40) {
          const [a,b]=demand(i,Math.max(0,model.t+dt)),q=valuePoint(i,a,b);
          if(dt===-w.trace_ms)c.moveTo(...q);else c.lineTo(...q);
        }c.stroke();
        const target=valuePoint(i,v,y);c.strokeStyle='#86efc2';c.lineWidth=2;c.fillStyle='#86efc222';
        const rx=p.speed_tolerance/1.2*pad.width,ry=p.height_tolerance/2*pad.height;
        c.fillRect(target[0]-rx,target[1]-ry,2*rx,2*ry);c.strokeRect(target[0]-rx,target[1]-ry,2*rx,2*ry);
        circle(...valuePoint(i,...demand(i,Math.max(0,model.t-w.trace_ms))),4,'#587e88');
      } else text('CAM VIEW COVERED',pad.x+55,pad.y+pad.height-10,12,'#d9ad65');
      const handle=commandPoint(i,s);circle(...handle,w.knob_radius,'#e9e2c5');circle(...handle,13,'#1a3440');circle(...handle,5,f.color);
      // Keep observation feedback visible even when command and response coincide.
      const actual=valuePoint(i,s.v,s.y);c.strokeStyle='#eebc68';c.lineWidth=3;c.beginPath();c.moveTo(actual[0]-8,actual[1]);c.lineTo(actual[0]+8,actual[1]);c.moveTo(actual[0],actual[1]-8);c.lineTo(actual[0],actual[1]+8);c.stroke();
      if(s.inspected)circle(...valuePoint(i,...demand(i,model.t+w.forecast_ms)),7,'#6abce3');
      const tab=w.cam_inspection.tabs[i];
      c.fillStyle=s.inspected?'#244c42':'#586b6a';c.fillRect(tab.x,tab.y,tab.width,tab.height);
      c.strokeStyle=s.inspected?'#86efc2':'#d9ad65';c.lineWidth=2;c.strokeRect(tab.x,tab.y,tab.width,tab.height);
      text(s.inspected?'CAM HOOD OPEN':model.mode==='full'?'CAM HOOD ↑ LIFT':'CAM HOOD · INSPECT',tab.x+7,tab.y+21,12,s.inspected?'#98e4bc':'#f0d494');
      if(s.done){c.fillStyle='#13382bce';c.fillRect(pad.x,pad.y,pad.width,pad.height);text('STRIPE READ',pad.x+62,pad.y+90,20,'#98e4bc');}
    });
    text(p.coupling?'SHARED DRIVE · CHANGING ONE FEED PULLS THE OTHER':'INDEPENDENT DRIVE',31,468,13,'#c7bfa4');
    text('● GREEN: READ WINDOW   + GOLD: CARD   ○ WHITE: GRIP   ● BLUE: +0.8s',31,488,12);
  }
  function animate(){paint();frame=requestAnimationFrame(animate);}
  function render(state,helpers) {
    cancelAnimationFrame(frame);document.body.dataset.mechanic='magnetic_stripe_purgatory_v3_nonrealtime';
    model={state,helpers,mode:state.control_condition.interaction,events:[],feeds:[],t:0,status:'staged',held:null,hood:null,posted:false};
    window.magneticStripePurgatoryV3Model=model;
    state.world.feeds.forEach((f,i)=>{const[v,y]=demand(i,0);model.feeds.push({u:v,q:y,v,y,distance:0,damage:0,done:false,inspected:false});});
    helpers.app.innerHTML=`<section class="ms2-shell"><header class="ms2-head"><div><small>DEPARTMENT OF UNREADABLE IDENTITIES</small><h1>Magnetic-Stripe Purgatory V3</h1></div><span>CONTINUOUS FEED<br>ONE ATTEMPT</span></header>
      <p class="ms2-rules">${model.mode==='full'?'Lift each CAM HOOD tab upward to inspect its read head; drag each white swipe grip':'Click each CAM HOOD tab to inspect its read head; click each control pad'} to match height and speed to the exposed green window. Blue dots show the incoming cam 0.8 seconds ahead. Inspection stays open. Each deliberate steering input advances one fixed reader step; waiting leaves the readers unchanged.</p>
      <canvas class="ms2-stage" width="1120" height="500"></canvas><footer><button class="ms2-start">ENGAGE READERS</button><div class="readout">Cam settings are inside the reader housings. Inspect before engaging; loaded cards wait safely. A full red damage bar ends the attempt.</div><button class="ms2-submit">CERTIFY READ</button></footer><div class="ms2-verdict" hidden></div></section>`;
    const canvas=document.querySelector('.ms2-stage');model.context=canvas.getContext('2d');
    const point=e=>{const r=canvas.getBoundingClientRect();return[(e.clientX-r.x)*1120/r.width,(e.clientY-r.y)*500/r.height];};
    canvas.addEventListener('pointerdown',e=>{
      if(e.button!==0||model.posted||model.status==='ready')return;
      e.preventDefault();const q=point(e),w=state.world;
      if(model.held!==null||model.hood!==null)return;
      for(let i=0;i<model.feeds.length;i++) {
        const tab=w.cam_inspection.tabs[i];
        if(!model.feeds[i].inspected&&q[0]>=tab.x&&q[0]<=tab.x+tab.width&&q[1]>=tab.y&&q[1]<=tab.y+tab.height) {
          if(model.mode==='simplified') {record('inspect',model.mode,{feed:i,point:q});model.feeds[i].inspected=true;}
          else {model.hood={feed:i,start:q};model.pointer=e.pointerId;canvas.setPointerCapture(e.pointerId);record('hood_grip',model.mode,{feed:i,point:q});}
          paint();return;
        }
      }
      for(let i=0;i<model.feeds.length;i++) {
        if(model.feeds[i].done)continue;
        const p=w.feeds[i].pad;
        if(model.mode==='simplified'&&q[0]>=p.x&&q[0]<=p.x+p.width&&q[1]>=p.y&&q[1]<=p.y+p.height){advance();if(!model.posted)steer(i,q);break;}
        if(model.mode==='full'&&model.held===null&&Math.hypot(q[0]-commandPoint(i,model.feeds[i])[0],q[1]-commandPoint(i,model.feeds[i])[1])<=w.knob_radius) {
          model.held=i;model.pointer=e.pointerId;canvas.setPointerCapture(e.pointerId);record('grip','full',{feed:i,point:q});break;
        }
      }paint();
    });
    canvas.addEventListener('pointermove',e=>{if(model.held===null||model.posted)return;advance();if(!model.posted)steer(model.held,point(e));paint();});
    const release=e=>{
      if(model.hood!==null) {
        const h=model.hood,q=point(e),cancelled=e.type!=='pointerup';
        if(!model.posted){record('hood_release','full',{feed:h.feed,point:q,cancelled});if(!cancelled&&q[1]<=h.start[1]-state.world.cam_inspection.lift_px)model.feeds[h.feed].inspected=true;}
        model.hood=null;paint();
        if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);return;
      }
      if(model.held===null)return;if(!model.posted)record('release','full',{feed:model.held});model.held=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);
    };
    canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);canvas.addEventListener('lostpointercapture',e=>{if(model.held!==null||model.hood!==null)release(e);});
    document.querySelector('.ms2-start').onclick=()=>{if(model.status!=='staged')return;record('start','launch_button');model.status='running';document.querySelector('.ms2-start').disabled=true;helpers.setReadout('READERS RUNNING · EACH STEER ADVANCES ONE FIXED STEP','pending');};
    document.querySelector('.ms2-submit').onclick=()=>{if(model.posted)return;record('submit','certify_button');post(model.status==='ready'?'':'INCOMPLETE READ');};
    frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.magnetic_stripe_purgatory_v3_nonrealtime={rootSelector:'.ms2-shell',render};
})();
