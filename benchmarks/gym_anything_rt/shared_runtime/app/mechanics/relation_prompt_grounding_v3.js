(() => {
  'use strict';
  let model, frame = 0;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const clean = x => String(x).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function drift(body, p, t) {
    const u = (t + body.phase_ms) / p.drift_span_ms, k = Math.floor(u), f = u-k, h = f*f*(3-2*f);
    return [0,1,2].map(i => p.drift_amplitude * (noise(body.motor_seed+i*7919,k)*(1-h)+noise(body.motor_seed+i*7919,k+1)*h));
  }
  function positions(state, commands, t) {
    return commands.map((q, i) => drift(state.objects[i], state.parameters, t).map((d, j) => clamp(q[j]+d,24,state.world_size[j]-24)));
  }
  function motionVector(state, commands, index, view, t) {
    const current=positions(state,commands,t)[index],previous=positions(state,commands,Math.max(0,t-100))[index],axis=view==='front'?0:2;
    return [(current[axis]-previous[axis])*5,(current[1]-previous[1])*5];
  }
  function shift(state, commands, index, view, delta) {
    const axes = view === 'front' ? [0,1] : [2,1];
    commands.forEach((q,i) => axes.forEach((axis,j) => { q[axis]=clamp(q[axis]+(i===index?1:state.parameters.coupling)*delta[j],...state.command_bounds); }));
  }
  function hull(points) {
    const ps=[...new Map(points.map(p=>[p.join(','),p])).values()].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
    const cross=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]);
    const chain=seq=>{const out=[];for(const p of seq){while(out.length>=2&&cross(out.at(-2),out.at(-1),p)<=0)out.pop();out.push(p);}return out.slice(0,-1);};
    return [...chain(ps),...chain([...ps].reverse())];
  }
  function contains(body, center, view, point) {
    const axis=view==='front'?0:2,x=point[0]-center[axis],y=point[1]-center[1];
    if(body.shape==='sphere')return Math.hypot(x,y)<=body.radius;
    const ps=hull(body.vertices.map(v=>[v[axis],v[1]]));
    return ps.every((a,i)=>{const b=ps[(i+1)%ps.length];return (b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])>=-1e-7;});
  }
  function fit(state, commands, stage, t) {
    return positions(state,commands,t).every((pos,i)=>pos.every((v,j)=>Math.abs(v-state.plates[stage].targets[i][j])<=state.parameters.tolerance+1e-7));
  }
  window.SculptureRigMath={noise,drift,positions,motionVector,shift,hull,contains,fit};
  const now=()=>model.active&&!model.terminal?Math.max(0,Math.round(performance.now()-model.startedAt)):model.t;
  function record(kind, extra={}) { model.events.push({sequence:model.events.length+1,kind,t_ms:model.t,...extra}); }
  function sync() {
    if(!model.active||model.terminal)return;
    model.t=now();
    if(model.t>=model.state.duration_ms){model.t=model.state.duration_ms;record('timeout');finish('fail','INSPECTION EXPIRED');}
  }
  function point(event) {
    const r=document.querySelector('#rig-canvas').getBoundingClientRect();
    const x=(event.clientX-r.left)*960/r.width,y=(event.clientY-r.top)*410/r.height;
    const view=x>=500?'side':'front',left=view==='front'?40:520;
    return {view,point:[clamp(x-left,0,400),clamp(y-45,0,340)],inside:x>=left&&x<=left+400&&y>=45&&y<=385};
  }
  function hit(view,p) {
    const ps=positions(model.state,model.commands,model.t),axis=view==='front'?2:0;
    const order=ps.map((_,i)=>i).sort((a,b)=>ps[a][axis]-ps[b][axis]);
    return order.filter(i=>contains(model.state.objects[i],ps[i],view,p)).at(-1);
  }
  function down(event) {
    if(event.button!==0||!model.active||model.terminal)return;
    event.preventDefault();sync();if(model.terminal)return;
    const p=point(event);if(!p.inside)return;
    if(model.interaction==='simplified'&&model.hold){
      if(p.view!==model.hold.view)return;
      const h=model.hold;
      record('place',{body:h.body,view:p.view,point:p.point,input_source:'proxy_click'});
      shift(model.state,model.commands,h.body,p.view,p.point.map((v,j)=>v-h.point[j]));model.hold=null;draw();return;
    }
    if(model.hold)return;
    const i=hit(p.view,p.point);if(i===undefined)return;
    const kind=model.interaction==='full'?'drag_start':'select';
    record(kind,{body:i,view:p.view,point:p.point,input_source:model.interaction==='full'?'direct_drag':'proxy_click'});
    // Selecting the actual sculpture opens its paired optical seals. Keep
    // learned seals and the live motor forecast available for the portfolio.
    model.inspected.add(i);
    model.hold={body:i,view:p.view,point:p.point,pointer:event.pointerId};
    if(model.interaction==='full')event.currentTarget.setPointerCapture(event.pointerId);
    draw();
  }
  function move(event, ending=false) {
    if(!model.hold||model.interaction!=='full'||event.pointerId!==model.hold.pointer||model.terminal)return;
    event.preventDefault();sync();if(model.terminal)return;
    const r=document.querySelector('#rig-canvas').getBoundingClientRect(),h=model.hold,left=h.view==='front'?40:520;
    const p=[clamp((event.clientX-r.left)*960/r.width-left,0,400),clamp((event.clientY-r.top)*410/r.height-45,0,340)];
    record(ending?'drag_end':'drag_move',{body:h.body,view:h.view,point:p,input_source:'direct_drag'});
    shift(model.state,model.commands,h.body,h.view,p.map((v,j)=>v-h.point[j]));h.point=p;
    if(ending){model.hold=null;event.currentTarget.releasePointerCapture?.(event.pointerId);}
    draw();
  }
  function cancel() {
    if(!model.hold||model.terminal)return;
    sync();if(model.terminal)return;
    record('cancel');model.hold=null;draw();
  }
  function start() {
    if(model.active||model.terminal)return;
    model.active=true;model.startedAt=performance.now();model.t=0;record('start');draw();
  }
  function expose() {
    if(!model.active||model.terminal)return;sync();if(model.terminal)return;
    record('expose');
    if(model.hold||model.stage>=model.state.plates.length||!fit(model.state,model.commands,model.stage,model.t)){finish('fail','EXPOSURE MISALIGNED');return;}
    model.stage++;model.photos.push(model.t);
    model.helpers.setReadout(model.stage===model.state.plates.length?'THREE PLATES EXPOSED · CERTIFY':'PLATE EXPOSED · NEXT SCULPTURE', 'idle');draw();
  }
  function certify() {
    if(!model.active||model.terminal)return;sync();if(model.terminal)return;
    record('certify');finish(model.stage===model.state.plates.length&&!model.hold?'pass':'fail','INCOMPLETE INSPECTION');
  }
  async function finish(terminal, reason) {
    if(model.terminal)return;
    const current=model;model.terminal=terminal;model.reason=terminal==='pass'?'SCULPTURE PORTFOLIO COMPLETE':reason;
    model.payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,revision:model.state.revision,interaction:model.interaction,events:structuredClone(model.events),commands:structuredClone(model.commands),plates:model.stage,terminal,final_t_ms:model.t};draw();
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(model.payload)});
      current.serverGrade=await response.json();
      if(current.serverGrade.passed!==true&&terminal==='pass'){current.reason='VERIFIER REJECTED INSPECTION';current.terminal='fail';}
      current.helpers.setReadout(current.serverGrade.passed?'PASS':'FAIL',current.serverGrade.passed?'passed':'error');draw();
    } catch(error){current.helpers.setReadout('VERIFIER ERROR · '+error.message,'error');}
  }
  function bodyPath(ctx, body, view, center) {
    const axis=view==='front'?0:2;ctx.beginPath();
    if(body.shape==='sphere')ctx.arc(center[0],center[1],body.radius,0,Math.PI*2);
    else hull(body.vertices.map(v=>[v[axis],v[1]])).forEach((p,i)=>{if(i===0)ctx.moveTo(center[0]+p[0],center[1]+p[1]);else ctx.lineTo(center[0]+p[0],center[1]+p[1]);});
    ctx.closePath();
  }
  function draw() {
    if(!model)return;
    const canvas=document.querySelector('#rig-canvas');if(!canvas)return;
    const ctx=canvas.getContext('2d'),s=model.state,ps=positions(s,model.commands,model.t),stage=Math.min(model.stage,s.plates.length-1),targets=s.plates[stage].targets;
    ctx.clearRect(0,0,960,410);ctx.fillStyle='#111c28';ctx.fillRect(0,0,960,410);
    for(const view of ['front','side']){
      const left=view==='front'?40:520,axis=view==='front'?0:2;ctx.save();ctx.translate(left,45);
      ctx.fillStyle='#142536';ctx.fillRect(0,0,400,340);
      ctx.lineWidth=1;ctx.strokeStyle='#293e50';
      for(let x=0;x<=400;x+=40){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,340);ctx.stroke();}
      for(let y=0;y<=340;y+=34){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(400,y);ctx.stroke();}
      ctx.strokeStyle='#638295';ctx.strokeRect(0,0,400,340);
      ctx.font='bold 13px ui-monospace,monospace';ctx.fillStyle='#cfdae2';ctx.fillText(view==='front'?'FRONT · X / HEIGHT':'SIDE · DEPTH / HEIGHT',0,-17);
      targets.forEach((target,i)=>{
        if(!model.inspected.has(i))return;
        const b=s.objects[i],cx=target[axis],cy=target[1],tol=s.parameters.tolerance;
        ctx.globalAlpha=.22;ctx.fillStyle=b.color;ctx.fillRect(cx-tol,cy-tol,2*tol,2*tol);ctx.globalAlpha=.85;ctx.strokeStyle=b.color;ctx.setLineDash([4,4]);ctx.strokeRect(cx-tol,cy-tol,2*tol,2*tol);
        bodyPath(ctx,b,view,[cx,cy]);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;
      });
      // Faint paths are recent motor drift, translated to the current carriage
      // frame, not a fabricated history of pointer-driven placements.
      s.objects.forEach((b,i)=>{
        ctx.strokeStyle=b.color;ctx.globalAlpha=.28;ctx.lineWidth=3;ctx.beginPath();
        for(let ago=400;ago>=0;ago-=40){const q=positions(s,model.commands,Math.max(0,model.t-ago))[i];if(ago===400)ctx.moveTo(q[axis],q[1]);else ctx.lineTo(q[axis],q[1]);}ctx.stroke();ctx.globalAlpha=1;
        if(!model.inspected.has(i))return;
        // The motor program is observable before its next bend. This preview
        // is the actual four-second path at the current carriage setting;
        // moving any carriage translates it through the same coupling.
        ctx.globalAlpha=.38;ctx.lineWidth=1.5;ctx.setLineDash([2,5]);ctx.beginPath();
        for(let ahead=0;ahead<=4000;ahead+=100){const q=positions(s,model.commands,model.t+ahead)[i];if(ahead===0)ctx.moveTo(q[axis],q[1]);else ctx.lineTo(q[axis],q[1]);}ctx.stroke();ctx.setLineDash([]);
        ctx.font='bold 10px ui-monospace,monospace';
        for(let ahead=1000;ahead<=4000;ahead+=1000){const q=positions(s,model.commands,model.t+ahead)[i];ctx.beginPath();ctx.arc(q[axis],q[1],4,0,Math.PI*2);ctx.stroke();ctx.fillStyle=b.color;ctx.fillText(String(ahead/1000)+'s',q[axis]+6,q[1]-6);}
        ctx.globalAlpha=1;
      });
      const order=ps.map((_,i)=>i).sort((a,b)=>ps[a][view==='front'?2:0]-ps[b][view==='front'?2:0]);
      for(const i of order){
        const b=s.objects[i],p=ps[i],c=[p[axis],p[1]],grad=ctx.createLinearGradient(c[0]-22,c[1]-22,c[0]+22,c[1]+22);
        grad.addColorStop(0,b.color);grad.addColorStop(1,'#233344');bodyPath(ctx,b,view,c);ctx.fillStyle=grad;ctx.fill();ctx.strokeStyle=b.color;ctx.lineWidth=model.hold?.body===i?4:2;ctx.stroke();
        ctx.beginPath();ctx.arc(...c,3,0,Math.PI*2);ctx.fillStyle='#fff5db';ctx.fill();
        const v=motionVector(s,model.commands,i,view,model.t);
        if(Math.hypot(...v)>1){ctx.beginPath();ctx.moveTo(...c);ctx.lineTo(c[0]+v[0],c[1]+v[1]);ctx.strokeStyle=b.color;ctx.lineWidth=2;ctx.stroke();ctx.beginPath();ctx.arc(c[0]+v[0],c[1]+v[1],3,0,Math.PI*2);ctx.fillStyle=b.color;ctx.fill();}
      }
      if(model.hold?.view===view){ctx.beginPath();ctx.arc(...model.hold.point,7,0,Math.PI*2);ctx.strokeStyle='#fff5db';ctx.lineWidth=1.5;ctx.stroke();}
      if(!model.inspected.size){ctx.font='12px ui-monospace,monospace';ctx.fillStyle='#cfdae2';ctx.fillText('SELECT A BODY TO INSPECT ITS PAIRED SEALS',12,325);}
      ctx.restore();
    }
    const ready=model.active&&!model.terminal&&model.stage<s.plates.length&&fit(s,model.commands,model.stage,model.t)&&!model.hold;
    document.querySelector('#rig-plate').textContent=model.stage===3?'PORTFOLIO READY':s.plates[stage].name;
    document.querySelector('#rig-status').textContent=model.terminal?model.reason:!model.active?'MOTORS IDLE':model.hold?(model.interaction==='full'?'RELEASE THE SCULPTURE':'CLICK A DESTINATION IN THE SAME VIEW'):ready?'BOTH VIEWS ALIGNED':'MOTORS RUNNING · TRACK THE DRIFT';
    document.querySelector('#rig-status').dataset.ready=String(ready);
    document.querySelector('#rig-start').disabled=model.active||!!model.terminal;
    document.querySelector('#rig-expose').disabled=!model.active||!!model.terminal||model.stage===3;
    document.querySelector('#rig-certify').disabled=!model.active||!!model.terminal;
    document.querySelector('#rig-receipts').innerHTML=s.plates.map((p,i)=>`<div class="rig-receipt ${model.stage>i?'complete':''}"><span>${clean(p.name)}</span><b>${model.stage>i?'EXPOSED':'—'}</b></div>`).join('');
    const verdict=document.querySelector('#rig-verdict');verdict.hidden=!model.terminal;verdict.dataset.outcome=model.terminal;verdict.querySelector('b').textContent=model.terminal==='pass'&&model.serverGrade?.passed?'PASS':model.terminal==='pass'?'VERIFYING':'FAIL';verdict.querySelector('span').textContent=model.reason;
  }
  function animate(){sync();draw();frame=requestAnimationFrame(animate);}
  async function render(state,helpers){
    cancelAnimationFrame(frame);document.body.dataset.mechanic='sculpture-rig-v2';
    model={state,helpers,interaction:state.control_condition.interaction,commands:state.objects.map(b=>[...b.initial]),inspected:new Set(),events:[],stage:0,t:0,active:false,startedAt:null,hold:null,terminal:'',reason:'',photos:[],serverGrade:null,payload:null};window.sculptureRigV3Model=model;
    helpers.app.innerHTML=`<section class="sculpture-rig-v2"><header class="rig-header"><div><span>THE KINETIC COLLECTION / OPTICAL WORKSHOP</span><h1>Dual-Projection Sculpture Rig V3</h1></div><div id="rig-plate">PLATE 1</div></header><main class="rig-main"><div class="rig-viewport"><canvas id="rig-canvas" width="960" height="410"></canvas><div class="rig-legend"><span>● LIVE CENTER</span><span>▧ INSPECTED TARGET SEAL</span><span>↗ 0.4 s TRAIL</span><span>··· INSPECTED MOTOR PATH · 4 s</span></div></div><aside class="rig-aside"><span>ONE CONTINUOUS MOTOR RUN</span><h2>One sculpture.<br>Two views.</h2><p>Select a body to reveal its paired target seals and four-second forecast. These stay visible across plates. Match every center in both views.</p><p>${model.interaction==='full'?'Drag in FRONT for X/height or SIDE for depth/height. Release without moving to inspect safely.':'Click a body, then its drag endpoint in the same view. The white ring marks the origin. Click that point again to inspect safely. FRONT shifts X/height; SIDE shifts depth/height.'}</p><p>${state.parameters.coupling?'Carriages share tension.':'Carriages move independently.'} Motors keep drifting during inspection and held gestures. Expose all three plates.</p><div id="rig-receipts"></div><p class="rig-warning">A misaligned exposure or incomplete certification ends the attempt.</p></aside></main><footer class="rig-footer"><div><strong id="rig-status">MOTORS IDLE</strong><div class="readout">Ready for inspection</div></div><button id="rig-start">START MOTORS</button><button id="rig-expose">EXPOSE PLATE</button><button id="rig-certify">CERTIFY</button></footer><div id="rig-verdict" hidden><b></b><span></span></div></section>`;
    const canvas=document.querySelector('#rig-canvas');canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',e=>move(e));canvas.addEventListener('pointerup',e=>move(e,true));canvas.addEventListener('pointercancel',cancel);canvas.addEventListener('lostpointercapture',()=>{if(model.hold&&model.interaction==='full')cancel();});
    document.querySelector('#rig-start').addEventListener('click',start);document.querySelector('#rig-expose').addEventListener('click',expose);document.querySelector('#rig-certify').addEventListener('click',certify);
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.relation_prompt_grounding_v3={rootSelector:'.sculpture-rig-v2',render};
})();
