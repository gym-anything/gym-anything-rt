(() => {
  'use strict';
  let model = null, cleanup = null;
  const copy = x => JSON.parse(JSON.stringify(x));
  const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  function noise(seed, index) {
    let v = (seed ^ Math.imul(index+1,0x9e3779b9)) >>> 0;
    v = Math.imul(v ^ (v >>> 16),0x85ebca6b) >>> 0;
    v = Math.imul(v ^ (v >>> 13),0xc2b2ae35) >>> 0;
    return ((v ^ (v >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function motion(seed,time,span) {
    const u=Math.max(0,time)/span, i=Math.floor(u), f=u-i;
    const a=noise(seed,i), b=noise(seed,i+1);
    return a+(b-a)*f*f*(3-2*f);
  }
  function centres(w,t) {
    const p=w.parameters;
    return w.motion_offsets.map((o,i) => o+p.sway*motion(w.motion_seeds[i],t,p.span_ms+i*731));
  }
  function wind(w,t) { return w.parameters.wind*motion(w.motion_seeds[3],t,3100); }
  function bend(w,x) {
    const u=clamp((x-w.landing_start)/(w.end_x-w.landing_start)*2,0,1.999999), i=Math.floor(u), f=u-i;
    return w.parameters.bend*(w.bend_points[i]+(w.bend_points[i+1]-w.bend_points[i])*f*f*(3-2*f));
  }
  function support(w,s,x,t) {
    const p=w.parameters, c=centres(w,t);
    if (0<=x && x<w.red_start) return [0,2.4,0,'apron'];
    if (w.red_start<=x && x<w.red_end) {
      if (x>w.red_start+s.red*2) return null;
      return [c[0]*(x-w.red_start)/6,p.half_width,0,'red'];
    }
    if (w.red_end<=x && x<w.stair_end) {
      if (s.stair===null) return null;
      const f=(x-w.red_end)/6;
      return [c[0]+(c[1]-c[0])*f,p.half_width,p.stair_height*(s.stair==='far'?f:1-f),'yellow'];
    }
    if (w.stair_end<=x && x<=w.slab_end) return [c[1],p.half_width,p.stair_height,'blue'];
    if (w.landing_start<=x && x<=w.end_x+.8) return [c[2]+bend(w,x),p.landing_half_width,p.stair_height,'terrace'];
    return null;
  }
  function initial(w) {
    return {t:0,x:w.start[0],y:0,z:0,vx:0,vy:0,vz:0,ux:0,uy:0,red:0,stair:null,primed:false,
      active:false,flight:false,launched:false,landed:false,loaded:false,aim:0,completed:false,failed:false,reason:'',launch_t:null};
  }
  function step(w,s) {
    if (!s.active || s.failed || s.completed) return;
    const p=w.parameters, dt=w.tick_ms/1000;
    s.t+=w.tick_ms;
    if (s.flight) s.vy+=(w.air_wind*wind(w,s.t)-w.air_drag*s.vy)*dt;
    else {
      const speed=p.cruise+s.ux*.48;
      s.vx+=(speed-s.vx)*Math.min(1,dt*3);
      s.vy+=(p.steering*s.uy+wind(w,s.t)-p.drag*s.vy)*dt;
    }
    s.x+=s.vx*dt; s.y+=s.vy*dt;
    const oldZ=s.z;
    if (s.flight) {
      s.vz-=w.gravity*dt; s.z+=s.vz*dt;
      if (s.vz<0 && s.z<=p.stair_height) {s.flight=false; s.landed=true; s.z=p.stair_height;}
    }
    if (!s.flight) {
      const tile=support(w,s,s.x,s.t);
      if (!tile) {s.failed=true; s.reason='The courier fell through a gap.';}
      else if (Math.abs(s.y-tile[0])+w.radius>tile[1]+1e-9) {s.failed=true; s.reason='The courier rolled off the visible edge.';}
      else if (Math.abs(tile[2]-oldZ)>.24) {s.failed=true; s.reason="The stair’s high face blocked the courier.";}
      else {
        s.z=tile[2];
        s.loaded=!s.launched && tile[3]==='blue' && s.x>=w.launch_x;
        if (s.landed) {
          if (tile[3]==='terrace' && w.delivery_start+w.radius<=s.x && s.x<=w.end_x+.8-w.radius) s.completed=true;
          else {s.failed=true;s.reason='The courier missed the delivery bay.';}
        }
      }
    }
    if (s.t>=w.max_time_ms && !s.completed) {s.failed=true; s.reason='The run ended.';}
  }
  function apply(w,s,event) {
    const kind=event.kind;
    if (kind==='red') s.red=clamp(s.red+event.value,0,3);
    else if (kind==='stair') s.stair=event.value;
    else if (kind==='prime') s.primed=!s.primed;
    else if (kind==='steer') {s.ux=event.ux;s.uy=event.uy;}
    else if (kind==='aim' || kind==='launch') {
      s.aim=event.value;
      if (kind==='launch' && s.active && s.loaded && s.primed && !s.launched) {
        s.flight=true;s.launched=true;s.loaded=false;s.vz=w.spring_vz;s.launch_t=s.t;
        s.vx+=w.spring_vx;s.vy+=w.spring_vy*event.value;
      }
    } else if (kind==='start') s.active=true;
    else if (kind==='submit' || kind==='abandon') {
      s.failed=true;s.reason=kind==='submit'?'The terminal has not been reached.':'The run was abandoned.';
    }
  }
  function sync() {
    if (!model || !model.physics.active || model.terminal) return;
    const end=Math.floor((performance.now()-model.startedAt)/model.world.tick_ms)*model.world.tick_ms;
    while (model.physics.t<end && !model.physics.failed && !model.physics.completed) step(model.world,model.physics);
    if (model.physics.failed || model.physics.completed) finish(model.physics.completed);
  }
  function record(kind,source,extra={}) {
    model.events.push({seq:model.events.length+1,t_ms:model.physics.t,kind,input_source:source,...extra});
  }
  function input(kind,extra={},source=null) {
    if (!model || model.terminal) return;
    sync(); if (model.terminal) return;
    const s=model.physics;
    source=source || (['start','submit','abandon'].includes(kind)?'common_button':['aim','launch'].includes(kind)?(model.interaction==='full'?'launch_drag':'launch_click'):model.interaction==='full'?(kind==='steer'?'stick_drag':'scene_click'):'proxy_click');
    if (kind==='start') {
      if (s.active) return;
      model.startedAt=performance.now();
    }
    apply(model.world,s,{kind,...extra});
    record(kind,source,extra); paint();
    if (s.failed) finish(false);
  }
  function payload(completed) {
    return {mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      interaction:model.interaction,completed,final_t_ms:model.physics.t,events:copy(model.events)};
  }
  async function finish(completed) {
    if (model.terminal) return;
    model.terminal=true; model.pending=payload(completed);
    model.attemptResult=copy(model.pending);
    paint(); await sendResult();
  }
  async function sendResult() {
    if (model.submitting || !model.pending) return;
    const m=model; m.submitting=true;
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(m.pending)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result=await response.json();
      if (typeof result.passed!=='boolean') throw new Error('Invalid grade response');
      m.grade=result; m.pending=null;
      if (result.passed===false && m.state.retry_policy?.classification==='retry_exception' &&
          result.state?.mechanic_id===m.state.mechanic_id && result.state?.task_id===m.state.task_id &&
          JSON.stringify(result.state.control_condition)===JSON.stringify(m.state.control_condition)) {
        m.nextState=result.state;
      }
      document.querySelector('#rcv2-retry').hidden=true;
      m.helpers.setReadout(result.passed?'PASS · COURIER DELIVERED':`FAIL · ${m.physics.reason || 'Traversal rejected.'}`,result.passed?'passed':'error');
      paint();
    } catch (error) {
      m.transportError=String(error); document.querySelector('#rcv2-retry').hidden=false;
      m.helpers.setReadout('CONNECTION LOST · RETRY THE SAME RESULT','error');
    } finally {m.submitting=false;paint();}
  }
  async function retryAttempt() {
    const m=model;
    // Only a completed failed submission can expose the server's next state.
    // There is no mid-run reset, pause, rewind or local re-generation seam.
    if (!m?.terminal || m.grade?.passed!==false || !m.nextState || m.submitting || m.retrying) return;
    m.retrying=true;
    const history=[...m.failureHistory,{result:copy(m.attemptResult),grade:copy(m.grade),reason:m.physics.reason}];
    await render(m.nextState,m.helpers,history);
  }
  function project(x,y,z=0) {
    const px=64+x*25+y*9;
    return [model.world.mirror===1?px:920-px,335-x*3-y*18-z*36];
  }
  function poly(ctx,points,fill,stroke='#8d9f98') {
    ctx.beginPath(); points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fillStyle=fill;ctx.fill();
    ctx.strokeStyle=stroke;ctx.lineWidth=1.4;ctx.stroke();
  }
  function slab(ctx,x0,x1,y0,y1,width,z0,z1,fill) {
    const top=[project(x0,y0-width,z0),project(x1,y1-width,z1),project(x1,y1+width,z1),project(x0,y0+width,z0)];
    const bottom=top.map(p=>[p[0],p[1]+15]);
    poly(ctx,[top[0],top[1],bottom[1],bottom[0]],'#29353c','#54656c');
    poly(ctx,[top[1],top[2],bottom[2],bottom[1]],'#1f2c34','#54656c');
    poly(ctx,top,fill);
    return top;
  }
  function label(ctx,text,point,colour='#e7eee2',size=12) {
    ctx.fillStyle=colour;ctx.font=`600 ${size}px ui-monospace,monospace`;ctx.textAlign='center';ctx.fillText(text,...point);
  }
  function arrow(ctx,from,to,colour) {
    ctx.strokeStyle=colour;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(...from);ctx.lineTo(...to);ctx.stroke();
    const a=Math.atan2(to[1]-from[1],to[0]-from[0]);
    poly(ctx,[to,[to[0]-7*Math.cos(a-.5),to[1]-7*Math.sin(a-.5)],[to[0]-7*Math.cos(a+.5),to[1]-7*Math.sin(a+.5)]],colour,colour);
  }
  function paintForecast(w,s) {
    const canvas=document.querySelector('#rcv2-forecast'),ctx=canvas.getContext('2d');
    const rect=canvas.getBoundingClientRect();
    // Render text/strokes at screen resolution. A fixed, short canvas stretched
    // over a wide panel made its labels thin and its curves difficult to read.
    const width=Math.max(1,Math.round(rect.width)),height=Math.max(1,Math.round(rect.height));
    if (canvas.width!==width || canvas.height!==height) {canvas.width=width;canvas.height=height;}
    const sx=width/920,sy=height/216;
    ctx.setTransform(sx,0,0,sy,0,0);
    function chartLabel(text,point,colour,size) {
      ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle=colour;
      ctx.font=`600 ${Math.max(9,size*Math.min(1,height/160))}px ui-monospace,monospace`;
      ctx.textAlign='center';ctx.fillText(text,point[0]*sx,point[1]*sy);ctx.restore();
    }
    // The actuators announce their next six seconds of travel. This rolling
    // mechanical plan and the recent traces expose the future of the same
    // supports/wind that determine contact and landing; no aim is computed.
    const chart={x:170,width:640};
    ctx.fillStyle='#101e28';ctx.fillRect(0,0,920,216);
    chartLabel('PLANNED TRAVEL / NEXT 6 SECONDS',[chart.x+chart.width/2,17],'#b6cdd0',13);
    for (let second=0;second<=6;second++) {
      const px=chart.x+second/6*chart.width;
      ctx.strokeStyle='#89a3a129';ctx.beginPath();ctx.moveTo(px,28);ctx.lineTo(px,194);ctx.stroke();
      chartLabel(`+${second}s`,[px,210],'#9cb4b7',12);
    }
    // Independent, labelled physical scales prevent two overlapping curves
    // from hiding one another. These are raw travel/acceleration values, not
    // an interception marker or a recommended spring setting.
    const lines=[{colour:'#f8df8e',name:'SPRING',unit:'lateral position',zero:58,scale:4.5,ticks:[-3,0,3],value:t=>centres(w,t)[1]},
      {colour:'#c0ffe0',name:'BAY AT x = 28',unit:'lateral position',zero:119,scale:4.5,ticks:[-3,0,3],value:t=>centres(w,t)[2]+bend(w,28)},
      {colour:'#92d2e5',name:'CROSSWIND',unit:'lateral acceleration',zero:180,scale:20,ticks:[-1,0,1],value:t=>wind(w,t)}];
    for (let i=0;i<lines.length;i++) {
      const line=lines[i];
      chartLabel(line.name,[75,line.zero-3],line.colour,12);
      chartLabel(line.unit,[75,line.zero+13],'#9cb4b7',10);
      for (const value of line.ticks) {
        const py=line.zero-value*line.scale;
        ctx.strokeStyle=value===0?'#89a3a166':'#89a3a122';ctx.lineWidth=1;
        ctx.beginPath();ctx.moveTo(chart.x,py);ctx.lineTo(chart.x+chart.width,py);ctx.stroke();
        chartLabel(String(value),[151,py+4],'#9cb4b7',11);
      }
      ctx.strokeStyle=line.colour;ctx.lineWidth=2/sy;ctx.beginPath();
      for (let ms=0;ms<=w.forecast_ms;ms+=50) {
        const px=chart.x+ms/w.forecast_ms*chart.width,py=line.zero-line.value(s.t+ms)*line.scale;
        ms===0?ctx.moveTo(px,py):ctx.lineTo(px,py);
      }
      ctx.stroke();
    }
  }
  function paintMeasurements(w,s) {
    const panel=document.querySelector('#rcv2-measurements');
    // Contact instruments report the plant, not a steering or launch answer.
    // Keep the original physics and forecast. Display complete decimal values
    // rather than truncating the state used by the visible continuation rule.
    panel.hidden=!(s.loaded || s.launched);
    if (panel.hidden) return;
    const number=value=>String(value===0?0:value);
    const channel=(index,span,offset,scale)=>{
      const first=Math.floor(s.t/span),last=Math.floor((s.t+w.forecast_ms)/span)+1;
      const anchors=[];
      for (let k=first;k<=last;k++) anchors.push(`${number((k*span-s.t)/1000)}s: ${number(offset+scale*noise(w.motion_seeds[index],k))}`);
      return anchors.join(' · ');
    };
    const p=w.parameters;
    document.querySelector('#rcv2-measured-courier').textContent=`${s.t} ms · x ${number(s.x)} · lane ${number(s.y)} · forward speed ${number(s.vx)} · lateral speed ${number(s.vy)}`;
    document.querySelector('#rcv2-measured-drive').textContent=`Drive ${number(s.ux)}, ${number(s.uy)} · spring aim ${number(s.aim)} · coil ${s.primed?'primed':'unprimed'} · stick ${model.dragging?'held':'latched'} · spring handle ${model.aiming?'held':'latched'}`;
    document.querySelector('#rcv2-measured-spring').textContent=`Nominal ${number(w.motion_offsets[1])} m; sway ${number(p.sway)} m. ${channel(1,p.span_ms+731,w.motion_offsets[1],p.sway)}`;
    document.querySelector('#rcv2-measured-bay').textContent=`Nominal ${number(w.motion_offsets[2])} m; sway ${number(p.sway)} m. ${channel(2,p.span_ms+1462,w.motion_offsets[2],p.sway)}`;
    document.querySelector('#rcv2-measured-wind').textContent=`Range ±${number(p.wind)} m/s². ${channel(3,3100,0,p.wind)}`;
    document.querySelector('#rcv2-measured-curve').textContent=`Terrace shape anchors, x ${number(w.landing_start)}, ${number((w.landing_start+w.end_x)/2)}, ${number(w.end_x)}: ${w.bend_points.map(b=>number(p.bend*b)).join(' · ')} m`;
  }
  function paint() {
    if (!model) return;
    const canvas=document.querySelector('#rcv2-scene');if (!canvas) return;
    const ctx=canvas.getContext('2d'), w=model.world,s=model.physics,p=w.parameters,c=centres(w,s.t);
    paintMeasurements(w,s);
    paintForecast(w,s);
    const bg=ctx.createLinearGradient(0,0,0,520);bg.addColorStop(0,w.palette==='dusk'?'#252138':'#142f3b');bg.addColorStop(1,'#0b151f');ctx.fillStyle=bg;ctx.fillRect(0,0,920,520);
    ctx.strokeStyle='#ffffff09';ctx.lineWidth=1;
    for (let x=0;x<32;x+=2) {ctx.beginPath();ctx.moveTo(...project(x,-8,-1));ctx.lineTo(...project(x,8,-1));ctx.stroke();}
    for (let y=-8;y<9;y+=2) {ctx.beginPath();ctx.moveTo(...project(0,y,-1));ctx.lineTo(...project(32,y,-1));ctx.stroke();}
    slab(ctx,0,4,0,0,2.4,0,0,'#83918d');
    for (let i=0;i<3;i++) {
      if (i<s.red) slab(ctx,4+i*2,6+i*2,c[0]*i/3,c[0]*(i+1)/3,p.half_width,0,0,['#c56763','#af5757','#9c4d53'][i]);
      else {
        ctx.setLineDash([4,4]);ctx.strokeStyle='#ef8d7770';ctx.beginPath();ctx.moveTo(...project(4+i*2,c[0]*i/3));ctx.lineTo(...project(6+i*2,c[0]*(i+1)/3));ctx.stroke();ctx.setLineDash([]);
      }
    }
    for (let i=0;i<3;i++) {
      const a=i/3,b=(i+1)/3;
      const za=s.stair===null?-.6:p.stair_height*(s.stair==='far'?a:1-a),zb=s.stair===null?-.6:p.stair_height*(s.stair==='far'?b:1-b);
      slab(ctx,10+i*2,12+i*2,c[0]+(c[1]-c[0])*a,c[0]+(c[1]-c[0])*b,p.half_width,za,zb,s.stair===null?'#554d37':['#baa158','#cdb665','#e1ca7b'][i]);
    }
    slab(ctx,16,18,c[1],c[1],p.half_width,p.stair_height,p.stair_height,'#416d80');
    slab(ctx,w.launch_x,18,c[1],c[1],p.half_width,p.stair_height+.015,p.stair_height+.015,s.loaded?'#b6eff4':s.primed?'#69e2f0':'#355062');
    for (let x=w.landing_start;x<w.end_x+.8;) {
      const end=Math.min(w.end_x+.8,x+.65,x<w.delivery_start?w.delivery_start:Infinity);
      slab(ctx,x,end,c[2]+bend(w,x),c[2]+bend(w,end),p.landing_half_width,p.stair_height,p.stair_height,x>=w.delivery_start?'#9fbda2':'#78958b');
      x=end;
    }
    // Recent support traces and current velocity arrows convey the same motion
    // that can remove support or spoil a landing.
    for (const [i,x] of [[0,10],[1,16],[2,27]]) {
      ctx.strokeStyle=['#f1aaa1','#f8df8e','#adebd1'][i];ctx.lineWidth=2;ctx.setLineDash([3,3]);ctx.beginPath();
      for (let age=400;age>=0;age-=100) {
        const yy=centres(w,Math.max(0,s.t-age))[i]+(i===2?bend(w,x):0),pt=project(x,yy,p.stair_height+(i===0?-p.stair_height:0));
        age===400?ctx.moveTo(...pt):ctx.lineTo(...pt);
      }
      ctx.stroke();ctx.setLineDash([]);
      const yy=c[i]+(i===2?bend(w,x):0), v=(centres(w,s.t+10)[i]-centres(w,Math.max(0,s.t-10))[i])/.02;
      arrow(ctx,project(x,yy,2.9),project(x,yy+v*.6,2.9),['#f1aaa1','#f8df8e','#adebd1'][i]);
    }
    const terminal=project(29,c[2]+bend(w,29),p.stair_height);
    ctx.strokeStyle='#c0ffe0';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(terminal[0],terminal[1]);ctx.lineTo(terminal[0],terminal[1]-43);ctx.stroke();
    poly(ctx,[[terminal[0],terminal[1]-43],[terminal[0]+25,terminal[1]-35],[terminal[0],terminal[1]-28]],'#c0ffe0','#c0ffe0');
    label(ctx,'DELIVERY BAY',[terminal[0],terminal[1]-56],'#c0ffe0',12);
    const shadow=project(s.x,s.y,s.flight?p.stair_height:s.z);ctx.fillStyle='#0008';ctx.beginPath();ctx.ellipse(shadow[0],shadow[1],8,4,0,0,Math.PI*2);ctx.fill();
    const courier=project(s.x,s.y,s.z+w.radius);const glow=ctx.createRadialGradient(courier[0]-2,courier[1]-3,1,...courier,8);
    glow.addColorStop(0,'#fffaf0');glow.addColorStop(1,s.failed?'#fb846d':'#d8deca');ctx.fillStyle=glow;ctx.beginPath();ctx.ellipse(...courier,w.radius*Math.hypot(25,9),w.radius*Math.hypot(3,18,36),0,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#18252d';ctx.stroke();
    arrow(ctx,courier,project(s.x+s.vx,s.y+s.vy,s.z+w.radius),'#faf2c4');
    label(ctx,s.flight?'AIRBORNE':s.landed?'DELIVERY TERRACE':'COURIER',[courier[0],courier[1]-19],'#f4eed6',11);
    label(ctx,'DRIFTING ARCHITECTURE / RECENT MOTION: DOTTED TRACES',[460,32],'#99b8bf',12);
    const windX=wind(w,s.t),lateral=project(0,1),origin=project(0,0),norm=Math.hypot(lateral[0]-origin[0],lateral[1]-origin[1]);
    arrow(ctx,[440,77],[440+(lateral[0]-origin[0])/norm*windX*44,77+(lateral[1]-origin[1])/norm*windX*44],'#92d2e5');label(ctx,'CROSSWIND',[440,132],'#92d2e5',11);
    // Full-mode actuator surfaces are part of the scene, with the same
    // extents used for hit testing. Simplified mode exposes proxies beside it.
    model.hits=[];
    const tiles=[{x:190,y:425,width:116,kind:'red',text:`RED  ${s.red}/3`,fill:'#b76160'},
      {x:393,y:425,width:60,kind:'stair',value:w.mirror===1?'near':'far',text:'▱',fill:'#cbb162'},
      {x:453,y:425,width:60,kind:'stair',value:w.mirror===1?'far':'near',text:'▰',fill:'#cbb162'},
      {x:607,y:425,width:116,kind:'prime',text:s.primed?'PRIMED':'BLUE',fill:s.primed?'#63c5d6':'#426879'}];
    for (const tile of tiles) {
      ctx.fillStyle=tile.fill;ctx.fillRect(tile.x,tile.y,tile.width,46);ctx.strokeStyle='#dce7d1';ctx.strokeRect(tile.x,tile.y,tile.width,46);
      label(ctx,tile.text,[tile.x+tile.width/2,tile.y+29],'#14252b',17);model.hits.push(tile);
    }
    label(ctx,'EXTEND / RIGHT CLICK RETRACT',[248,497],'#bda6a4',11);
    label(ctx,`HIGH END: ${s.stair?s.stair.toUpperCase():'UNSET'}`,[453,497],'#d6c79b',11);
    label(ctx,'CONTACT SPRING / TOGGLE',[665,497],'#9dced6',11);
    const stick=document.querySelector('#rcv2-stick');if (stick) {stick.style.left=`${50+s.uy*36}%`;stick.style.top=`${50-s.ux*36}%`;}
    document.querySelector('#rcv2-launch-handle').style.left=`${50+s.aim*42}%`;
    document.querySelector('#rcv2-launch-state').textContent=s.completed?'DELIVERED / COIL RELEASED':s.failed?(s.launched?'RELEASED / LANDING FAILED':'RUN ENDED / COIL NOT RELEASED'):s.flight?'COMMITTED FLIGHT':s.loaded?(s.primed?'COIL LOADED / AIM & RELEASE':'COIL LOADED / PRIME FIRST'):'CONTACT REQUIRED / NO IMPULSE YET';
    const status=document.querySelector('#rcv2-status');status.textContent=s.failed?'FALL / RUN ENDED':s.completed?'DELIVERED':s.flight?'COMMITTED FLIGHT':s.loaded?'SPRING LOADED':s.active?'RUNNING':'SAFE INSPECTION';
    document.querySelector('#rcv2-speed').textContent=`${s.vx.toFixed(2)} · lateral ${s.vy.toFixed(2)}`;
    document.querySelector('#rcv2-start').disabled=s.active || model.terminal;
    document.querySelector('#rcv2-red').textContent=`Red extension ${s.red}/3`;
    document.querySelector('#rcv2-prime').textContent=s.primed?'Blue spring: primed':'Prime blue spring';
    const verdict=document.querySelector('#rcv2-verdict');
    verdict.hidden=!model.terminal;
    const failedCount=model.failureHistory.length+(model.terminal && (s.failed || model.grade?.passed===false)?1:0);
    document.querySelector('#rcv2-attempt-count').textContent=`${failedCount} FAILED ATTEMPTS / RETRY AFTER RUN END`;
    if (model.terminal) {
      const passed=model.grade?.passed===true;
      verdict.dataset.passed=passed;
      verdict.querySelector('b').textContent=passed?'PASS':s.failed || model.grade?'FAIL':'VERIFYING';
      verdict.querySelector('span').textContent=s.reason || (passed?'Courier delivered.':'Checking traversal.');
      const retry=document.querySelector('#rcv2-retry-attempt');
      retry.hidden=!model.nextState || model.grade?.passed!==false;
      retry.disabled=model.submitting || model.retrying;
    }
  }
  async function render(state,helpers,failureHistory=[]) {
    if (cleanup) cleanup();
    document.body.dataset.mechanic='rising-causeway-v2';
    model={state,helpers,world:state.world,physics:initial(state.world),interaction:state.control_condition?.interaction||'full',
      startedAt:performance.now(),events:[],terminal:false,grade:null,pending:null,submitting:false,hits:[],dragging:false,aiming:false,
      failureHistory:copy(failureHistory),attemptResult:null,nextState:null,retrying:false};
    window.risingCausewayV2Model=model;
    // Read-only diagnostics use these equations; no solver-specific action or
    // success function is added to the runtime.
    model.project=project;
    helpers.app.innerHTML=`<section class="rcv2" data-interaction="${helpers.text(model.interaction)}">
      <header><div><small>ESTUARY 07 / LIVE STONEWORK</small><h1>Rising Causeway V2</h1></div><span id="rcv2-status">SAFE INSPECTION</span></header>
      <p class="rcv2-rule">${helpers.text(state.prompt)}</p>
      <main><div class="rcv2-world"><canvas id="rcv2-forecast" width="920" height="216" aria-label="Rolling six-second spring position, bay position at x 28, and crosswind acceleration on separate labelled scales"></canvas><section id="rcv2-measurements" hidden aria-label="Spring-contact measurements"><strong>CONTACT INSTRUMENTS / METRES AND SECONDS</strong><div id="rcv2-measured-courier"></div><div id="rcv2-measured-drive"></div><div class="rcv2-measured-routes"><div><b>SPRING POSITION</b><span id="rcv2-measured-spring"></span></div><div><b>TERRACE SWAY CENTRE</b><span id="rcv2-measured-bay"></span></div><div><b>CROSSWIND</b><span id="rcv2-measured-wind"></span></div></div><div id="rcv2-measured-curve"></div><small>Anchors bracket the announced route; each segment joins its endpoints smoothly with zero endpoint slope.</small></section><canvas id="rcv2-scene" width="920" height="520" aria-label="Isometric moving causeway, courier and rolling travel forecast"></canvas><div class="rcv2-launch-panel"><small id="rcv2-launch-state">CONTACT REQUIRED</small><div id="rcv2-launch" aria-label="Aim and release the loaded contact spring"><span>LEFT KICK</span><b id="rcv2-launch-handle"></b><span>RIGHT KICK</span></div><p>${model.interaction==='full'?'Drag the spring handle; releasing fires the loaded coil.':'Click the spring rail to aim and fire the loaded coil.'} Flight lasts about 2.4 seconds; wheels cannot steer in air.</p></div><div id="rcv2-verdict" hidden aria-live="assertive"><b></b><span></span><button id="rcv2-retry-attempt" hidden>TRY AGAIN</button></div></div>
      <aside><small>COURIER DRIVE</small><p id="rcv2-how">${model.interaction==='full'?'Drag the round stick. It stays where released.':'Click the drive pad to set the stick.'} Up/down changes forward drive. Right thrusts ${state.world.mirror===1?'↗':'↖'}; left thrusts ${state.world.mirror===1?'↙':'↘'} across the lane.</p>
      <div id="rcv2-pad" aria-label="Forward drive and lateral thrust pad"><span class="rcv2-axis-v"></span><span class="rcv2-axis-h"></span><b id="rcv2-stick"></b><i>FAST</i><em>SLOW</em></div>
      <small>SPEED / LATERAL VELOCITY</small><strong id="rcv2-speed">0</strong>
      <div class="rcv2-proxies" ${model.interaction==='full'?'hidden':''}><button id="rcv2-red">Red extension 0/3</button><button id="rcv2-retract">Retract red</button><div><button id="rcv2-near">Near end high</button><button id="rcv2-far">Far end high</button></div><button id="rcv2-prime">Prime blue spring</button></div>
      <p class="rcv2-legend">${model.interaction==='full'?'Click red to extend; right click retracts. Click a yellow end to raise it. Click blue to prime. ':''}Dotted tracks show 400 ms of drift. The courier arrow shows one second of current velocity. Separate chart rows announce six seconds of spring position, bay centre at x = 28, and wind acceleration. The courier keeps moving after departure.</p>
      <button id="rcv2-start">DEPART</button><button id="rcv2-submit">CERTIFY ARRIVAL</button><button id="rcv2-abandon">ABANDON</button><button id="rcv2-retry" hidden>RETRY RESULT DELIVERY</button></aside></main>
      <footer><div class="readout">Inspect and configure the architecture, then depart.</div><span id="rcv2-attempt-count"></span></footer></section>`;
    const handlers=[];
    function on(node,type,fn) {node.addEventListener(type,fn);handlers.push(()=>node.removeEventListener(type,fn));}
    const find=id=>document.getElementById(id);
    for (const [id,kind,extra] of [['rcv2-start','start',{}],['rcv2-submit','submit',{}],['rcv2-abandon','abandon',{}]]) on(find(id),'click',()=>input(kind,extra));
    on(find('rcv2-retry'),'click',sendResult);
    on(find('rcv2-retry-attempt'),'click',retryAttempt);
    for (const [id,kind,extra] of [['rcv2-red','red',{value:1}],['rcv2-retract','red',{value:-1}],['rcv2-near','stair',{value:'near'}],['rcv2-far','stair',{value:'far'}],['rcv2-prime','prime',{}]]) {
      on(find(id),'click',()=>{if(model.interaction==='simplified')input(kind,extra,'proxy_click');});
    }
    const canvas=find('rcv2-scene');
    function scene(event) {
      event.preventDefault();if (model.interaction!=='full' || model.terminal) return;
      const r=canvas.getBoundingClientRect(),x=(event.clientX-r.left)*920/r.width,y=(event.clientY-r.top)*520/r.height;
      const hit=model.hits.find(h=>x>=h.x && x<=h.x+h.width && y>=h.y && y<=h.y+46);
      if (!hit) return;
      if (event.button===2 && hit.kind!=='red') return;
      input(hit.kind,hit.kind==='red'?{value:event.button===2?-1:1}:hit.kind==='stair'?{value:hit.value}:{},'scene_click');
    }
    on(canvas,'click',scene);on(canvas,'contextmenu',scene);
    const pad=find('rcv2-pad');let dragging=false;
    function steer(event) {
      const r=pad.getBoundingClientRect();
      input('steer',{ux:clamp((.5-(event.clientY-r.top)/r.height)/.36,-1,1),uy:clamp(((event.clientX-r.left)/r.width-.5)/.36,-1,1)});
    }
    on(pad,'pointerdown',event=>{
      if (event.button!==0 || model.terminal) return;
      event.preventDefault();
      if (model.interaction==='simplified') {steer(event);return;}
      const rect=find('rcv2-stick').getBoundingClientRect();
      if (Math.hypot(event.clientX-rect.x-rect.width/2,event.clientY-rect.y-rect.height/2)>23) return;
      dragging=true;model.dragging=true;pad.setPointerCapture(event.pointerId);paint();
    });
    on(pad,'pointermove',event=>{if (dragging && !model.terminal) steer(event);});
    on(pad,'pointerup',event=>{if (dragging) {if (!model.terminal)steer(event);dragging=false;model.dragging=false;pad.releasePointerCapture(event.pointerId);paint();}});
    for (const type of ['pointercancel','lostpointercapture']) on(pad,type,()=>{dragging=false;model.dragging=false;paint();});
    const rail=find('rcv2-launch');let aiming=false;
    function aimValue(event) {
      const r=rail.getBoundingClientRect();return clamp(((event.clientX-r.left)/r.width-.5)/.42,-1,1);
    }
    on(rail,'pointerdown',event=>{
      if (event.button!==0 || model.terminal) return;
      event.preventDefault();
      if (model.interaction==='simplified') {input('launch',{value:aimValue(event)});return;}
      const r=find('rcv2-launch-handle').getBoundingClientRect();
      if (Math.abs(event.clientX-r.x-r.width/2)>24) return;
      aiming=true;model.aiming=true;rail.setPointerCapture(event.pointerId);paint();
    });
    on(rail,'pointermove',event=>{if (aiming && !model.terminal)input('aim',{value:aimValue(event)});});
    on(rail,'pointerup',event=>{
      if (!aiming) return;
      if (!model.terminal) input('launch',{value:aimValue(event)});
      aiming=false;model.aiming=false;rail.releasePointerCapture(event.pointerId);paint();
    });
    for (const type of ['pointercancel','lostpointercapture']) on(rail,type,()=>{aiming=false;model.aiming=false;paint();});
    let frame;
    function animate() {sync();paint();frame=requestAnimationFrame(animate);}
    const timer=setInterval(sync,state.world.tick_ms);
    paint();frame=requestAnimationFrame(animate);
    cleanup=()=>{cancelAnimationFrame(frame);clearInterval(timer);handlers.forEach(h=>h());};
  }
  window.RisingCausewayV2Physics={noise,motion,centres,wind,bend,support,initial,step,apply};
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.rising_causeway_v2={rootSelector:'.rcv2',render};
})();
