(() => {
  'use strict';
  let model, raf = 0;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const clean = v => String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index+1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function wind(r, t, p) {
    const u=(t+r.phase_ms)/p.wind_span_ms, i=Math.floor(u), f=u-i;
    return noise(r.wind_seed,i)+(noise(r.wind_seed,i+1)-noise(r.wind_seed,i))*f*f*(3-2*f);
  }
  function ribbonY(r,x,t,p) {
    const z=clamp(x,0,1)*(r.knots.length-1), i=Math.min(r.knots.length-2,Math.floor(z)), f=z-i;
    return r.knots[i]+(r.knots[i+1]-r.knots[i])*f*f*(3-2*f)+p.amplitude*Math.sin(Math.PI*x)*wind(r,t,p);
  }
  function center(i) {return (450-model.state.lanes.length*150)/2+i*150+75;}
  function record(kind,lane,point) {
    model.events.push({sequence:model.events.length+1,kind,t_ms:model.t,input_source:model.interaction,
      ...(lane===undefined?{}:{lane,point:point.map(a=>Math.round(a*100000)/100000)})});
  }
  function inspect(q) {
    if(model.terminal||model.drag!==null||q[0]<140||q[0]>1040)return;
    const i=model.state.lanes.findIndex(l=>Math.abs(q[1]-center(l.id))<=72);
    if(i<0)return;
    const a=Math.max(140,q[0]-model.state.inspection.radius),b=Math.min(1040,q[0]+model.state.inspection.radius);
    if(model.lit[i].some(([lo,hi])=>a>=lo&&b<=hi))return;
    const spans=[...model.lit[i],[a,b]].sort((a,b)=>a[0]-b[0]),merged=[];
    for(const span of spans) {
      const last=merged.at(-1);
      if(last&&span[0]<=last[1])last[1]=Math.max(last[1],span[1]);else merged.push([...span]);
    }
    model.lit[i]=merged;
    record('inspect',i,[q[0],q[1]-center(i)]);
    model.helpers.setReadout(`CONTACT ${i+1} · LOCAL WEAVE ILLUMINATED · INSPECTED SPANS STAY LIT`,'pending');
  }
  function tick(t) {
    const p=model.state.parameters, dt=model.state.step_ms/1000, x=Math.min(1,t/p.travel_ms);
    for (const lane of model.state.lanes) {
      const b=model.bodies[lane.id], desired=clamp((b.aim-b.y)*6,-130,130);
      b.v+=clamp(desired-b.v,-520*dt,520*dt)*Math.min(1,model.state.step_ms/p.servo_tau_ms*4);
      b.y=clamp(b.y+b.v*dt,-72,72);
      const error=Math.abs(b.y-ribbonY(lane.ribbons[lane.target],x,t,p));
      b.heat=Math.max(0,b.heat+model.state.step_ms*(error>p.tolerance?1:-2));
      b.peak=Math.max(b.peak,b.heat);
      if(b.heat>=p.burn_ms) return lane.id;
    }
    return null;
  }
  function advance() {
    if(!model.started || model.terminal) return;
    const end=Math.min(model.state.parameters.travel_ms,Math.floor((performance.now()-model.startedAt)/model.state.step_ms)*model.state.step_ms);
    while(model.t<end) {
      model.t+=model.state.step_ms;
      const burned=tick(model.t);
      if(burned!==null) { finish(false,`CONTACT ${burned+1} BURNT`);return; }
    }
    if(model.t===model.state.parameters.travel_ms) finish(true,'ALL SIGNALS CONNECTED');
  }
  async function finish(completed,reason) {
    if(model.terminal) return;
    model.terminal=true; model.drag=null;
    document.querySelector('.rs2-stamp').textContent=completed?'VERIFYING…':'FAIL · '+reason;
    document.querySelector('.rs2-stamp').dataset.state=completed?'pending':'fail';
    document.querySelector('.rs2-start').disabled=true;
    model.payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,
      challenge_id:model.state.challenge_id,revision:model.state.revision,interaction_mode:model.interaction,
      events:model.events,final_t_ms:model.t,completed};
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(model.payload)});
      model.grade=await response.json();
      const pass=model.grade.passed===true;
      document.querySelector('.rs2-stamp').textContent=pass?'PASS · ALL SIGNALS CONNECTED':'FAIL · '+reason;
      document.querySelector('.rs2-stamp').dataset.state=pass?'pass':'fail';
      model.helpers.setReadout(pass?'PASS':'FAIL',pass?'passed':'error');
    } catch(e) {model.helpers.setReadout('VERIFIER ERROR · '+e.message,'error');}
  }
  function start() {
    if(model.started||model.terminal)return;
    model.started=true;model.startedAt=performance.now();record('start');
    document.querySelector('.rs2-start').disabled=true;
    model.helpers.setReadout('LIVE CONTACTS · KEEP THE HEADS ON THEIR SOURCE RIBBONS','pending');
  }
  function line(ctx,r,t,width,color,alpha=1) {
    const p=model.state.parameters;
    ctx.beginPath();
    for(let i=0;i<=180;i++) {
      const x=i/180,y=center(model.paintLane)+ribbonY(r,x,t,p);
      if(i===0)ctx.moveTo(140,y);else ctx.lineTo(140+900*x,y);
    }
    ctx.globalAlpha=alpha;ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.stroke();ctx.globalAlpha=1;
  }
  function circle(ctx,x,y,r,fill,stroke) {
    ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();
    if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.stroke();}
  }
  function paint() {
    const canvas=document.querySelector('.rs2-canvas');if(!canvas)return;
    const ctx=canvas.getContext('2d'),p=model.state.parameters,x=model.t/p.travel_ms;
    ctx.clearRect(0,0,1100,450);
    for(const lane of model.state.lanes) {
      model.paintLane=lane.id;
      const cy=center(lane.id),b=model.bodies[lane.id],target=lane.ribbons[lane.target];
      ctx.fillStyle='#102627';ctx.fillRect(10,cy-73,1080,146);
      ctx.strokeStyle='#38504d';ctx.lineWidth=1;ctx.strokeRect(10,cy-73,1080,146);
      ctx.fillStyle='#9aad9f';ctx.font='12px monospace';ctx.textAlign='center';
      ctx.fillText(model.interaction==='full'?'UNLIT WEAVE · HOVER TO ILLUMINATE':'UNLIT WEAVE · CLICK TO ILLUMINATE',590,cy+4);
      // Local light reveals actual moving geometry, including its band and
      // recent echoes. Earned spans stay visible; no inspection modal pauses it.
      ctx.save();ctx.beginPath();
      for(const [lo,hi] of model.lit[lane.id])ctx.rect(lo,cy-72,hi-lo,144);
      ctx.clip();ctx.fillStyle='#102627';ctx.fillRect(140,cy-72,900,144);
      // Two genuine recent geometries evidence ribbon direction in a still image.
      for(const age of [800,400])line(ctx,target,Math.max(0,model.t-age),2,target.color,.24);
      line(ctx,target,model.t,p.tolerance*2,target.color,.14);
      for(const r of [...lane.ribbons].sort((a,b)=>a.depth-b.depth)) {
        line(ctx,r,model.t,12,'#102627');line(ctx,r,model.t,7,r.color);
        line(ctx,r,model.t,1,'#ffffff',.30);
      }
      ctx.restore();
      ctx.strokeStyle='#5b756d';ctx.lineWidth=4;ctx.beginPath();ctx.moveTo(44,cy-67);ctx.lineTo(44,cy+67);ctx.stroke();
      circle(ctx,44,cy+b.aim,20,'#f7ead0','#877e66');
      ctx.fillStyle='#273530';ctx.font='bold 13px sans-serif';ctx.textAlign='center';ctx.fillText('↕',44,cy+b.aim+4);
      ctx.strokeStyle='#f6ead0';ctx.setLineDash([3,5]);ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(70,cy+b.aim);ctx.lineTo(140+900*x,cy+b.aim);ctx.stroke();ctx.setLineDash([]);
      ctx.strokeStyle='#a7b6ab';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(140+900*x,cy-70);ctx.lineTo(140+900*x,cy+70);ctx.stroke();
      const ty=ribbonY(target,x,model.t,p),off=Math.abs(b.y-ty)>p.tolerance;
      circle(ctx,140+900*x,cy+b.y,10,off?'#ed7671':'#eaf7df','#081819');
      circle(ctx,140,cy+target.knots[0],10,target.color,'#fff1d5');
      ctx.fillStyle='#eee1c8';ctx.font='bold 12px monospace';ctx.textAlign='left';ctx.fillText(''+(lane.id+1),83,cy-54);
      ctx.fillStyle=target.color;ctx.fillText('SOURCE',83,cy-39);
      ctx.textAlign='center';ctx.font='bold 11px monospace';ctx.fillText('◆',140,cy+target.knots[0]+4);
      for(const r of lane.ribbons)circle(ctx,1040,cy+r.knots.at(-1),5,r.color);
      const bar=document.querySelector(`[data-heat="${lane.id}"]`);
      bar.querySelector('i').style.width=`${100*b.heat/p.burn_ms}%`;
      bar.querySelector('b').textContent=b.heat>=p.burn_ms?'BURNT':off?'OFF RIBBON':'CONNECTED';
      bar.dataset.off=off?'yes':'no';
    }
    document.querySelector('.rs2-progress i').style.width=`${100*x}%`;
    document.querySelector('.rs2-progress span').textContent=model.started?`${Math.round(x*100)}% ROUTED`:'READY';
  }
  function animate() {if(!model)return;advance();paint();raf=requestAnimationFrame(animate);}
  function stagePoint(e) {
    const r=e.currentTarget.getBoundingClientRect();return [(e.clientX-r.left)*1100/r.width,(e.clientY-r.top)*450/r.height];
  }
  function lanePoint(q,i) {return [clamp(q[0],14,74),clamp(q[1]-center(i),-72,72)];}
  function aim(i,q,kind) {
    const point=lanePoint(q,i).map(a=>Math.round(a*100000)/100000);
    record(kind,i,point);if(kind!=='down')model.bodies[i].aim=point[1];
  }
  async function render(state,helpers) {
    cancelAnimationFrame(raf);document.body.dataset.mechanic='ribbon-switchboard-v3';
    model={state,helpers,t:0,started:false,terminal:false,events:[],interaction:state.control_condition?.interaction||'full',drag:null,
      lit:state.lanes.map(()=>[]),
      bodies:state.lanes.map(l=>({y:l.ribbons[l.target].knots[0],aim:l.ribbons[l.target].knots[0],v:0,heat:0,peak:0}))};
    window.ribbonSwitchboardV3Model=model;
    helpers.app.innerHTML=`<section class="rs2-shell"><header class="rs2-head"><div><p>THE BRAID EXCHANGE / LIVE CIRCUITS</p><h1>Ribbon Switchboard V3</h1></div><button class="rs2-start">ENERGIZE LOOM →</button></header>
      <div class="rs2-rules">${clean(state.prompt)}<br><strong>${model.interaction==='full'?'Hover over the weave to illuminate local spans; drag each ivory knob vertically to steer its contact.':'Click the weave to illuminate local spans; click a height on each ivory rail to steer its contact.'}</strong> You can inspect safely before energizing. Faint ribbon echoes show the last 0.8 seconds.</div>
      <div class="rs2-instruments">${state.lanes.map(l=>`<div data-heat="${l.id}"><span>CONTACT ${l.id+1} · HEAT</span><div class="rs2-heat"><i></i></div><b>CONNECTED</b></div>`).join('')}</div>
      <canvas class="rs2-canvas" width="1100" height="450"></canvas><div class="rs2-stamp" data-state="ready"></div>
      <footer><div class="rs2-progress"><i></i><span>READY</span></div><div class="readout">Illuminate the weave to find each marked source's path. Once energized, all contacts travel together.</div></footer></section>`;
    document.querySelector('.rs2-start').addEventListener('click',start);
    const c=document.querySelector('.rs2-canvas');
    c.addEventListener('pointerdown',e=>{
      advance();if(!model.started||model.terminal||e.button!==0)return;
      const q=stagePoint(e);
      if(model.interaction!=='full'||q[0]<14||q[0]>74)return;
      const i=model.bodies.findIndex((b,i)=>Math.hypot(q[0]-44,q[1]-center(i)-b.aim)<=22);
      if(i<0)return;e.preventDefault();model.drag=i;c.setPointerCapture(e.pointerId);aim(i,q,'down');
    });
    c.addEventListener('pointermove',e=>{
      advance();if(model.terminal)return;
      const q=stagePoint(e);
      if(model.drag!==null)aim(model.drag,q,'move');
      else if(model.interaction==='full')inspect(q);
    });
    c.addEventListener('pointerup',e=>{
      advance();if(model.terminal)return;
      const q=stagePoint(e);
      if(model.interaction==='simplified'&&e.button===0&&q[0]>=140&&q[0]<=1040){inspect(q);return;}
      if(!model.started)return;
      if(model.interaction==='full'){
        if(model.drag===null)return;const i=model.drag;model.drag=null;aim(i,q,'up');
        if(c.hasPointerCapture(e.pointerId))c.releasePointerCapture(e.pointerId);
      } else if(q[0]>=14&&q[0]<=74) {
        const i=model.state.lanes.findIndex(l=>Math.abs(q[1]-center(l.id))<=72);
        if(i>=0)aim(i,q,'click');
      }
    });
    c.addEventListener('pointercancel',e=>{
      if(model.drag!==null&&!model.terminal){advance();if(model.terminal)return;aim(model.drag,stagePoint(e),'up');model.drag=null;}
    });
    paint();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.ribbon_switchboard_v3={rootSelector:'.rs2-shell',render};
})();
