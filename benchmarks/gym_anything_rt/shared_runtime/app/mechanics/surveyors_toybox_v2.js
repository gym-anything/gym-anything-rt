(() => {
  'use strict';
  const REVISION = 'live-cuboid-survey-v2';
  const clone = x => structuredClone(x), clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  const clean = x => String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  let model, frame = 0;
  function sweepFraction(u){u=clamp(u,0,1);const a=.06;return u<a?u*u/(2*a*(1-a)):u>1-a?1-(1-u)**2/(2*a*(1-a)):(u-a/2)/(1-a);}
  function pose(obj, ms) {
    const m=obj.motion,u=(Math.max(0,ms)+m.offset_ms)/m.span_ms,i=Math.min(m.knots.length-2,Math.floor(u));
    const f=sweepFraction(u-i);
    const a=m.knots[i],b=m.knots[i+1],p=a.map((v,j)=>v+(b[j]-v)*f);
    const s=m.steering,su=(Math.max(0,ms)+s.offset_ms)/s.span_ms,si=Math.min(s.knots.length-2,Math.floor(su));
    let sf=Math.min(1,su-si);sf=sf*sf*(3-2*sf);p[0]+=s.knots[si]+(s.knots[si+1]-s.knots[si])*sf;
    return {center:p.slice(0,3),half:[...obj.half],yaw:p[3]};
  }
  function project(v,p) { return v.origin.map((x,j)=>x+v.scale*v.signs[j]*p[v.axes[j]]); }
  function corners(b) {
    const a=b.yaw*Math.PI/180,co=Math.cos(a),si=Math.sin(a),c=b.center,h=b.half,points=[];
    for(const x of [-1,1])for(const y of [-1,1])for(const z of [-1,1])
      points.push([c[0]+x*h[0]*co-z*h[2]*si,c[1]+y*h[1],c[2]+x*h[0]*si+z*h[2]*co]);
    return points;
  }
  function footprint(b) {
    const c=b.center,h=b.half,a=b.yaw*Math.PI/180,co=Math.cos(a),si=Math.sin(a);
    return [[-1,-1],[1,-1],[1,1],[-1,1]].map(([x,z])=>[c[0]+x*h[0]*co-z*h[2]*si,c[2]+x*h[0]*si+z*h[2]*co]);
  }
  const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
  function clip(poly,a,b) {
    if(!poly.length)return [];
    const out=[];let p=poly.at(-1),before=cross(a,b,p)>=-1e-10;
    for(const q of poly){
      const after=cross(a,b,q)>=-1e-10;
      if(before!==after){
        const d=[q[0]-p[0],q[1]-p[1]],e=[b[0]-a[0],b[1]-a[1]],den=d[0]*e[1]-d[1]*e[0];
        if(Math.abs(den)>1e-12){const t=((a[0]-p[0])*e[1]-(a[1]-p[1])*e[0])/den;out.push([p[0]+t*d[0],p[1]+t*d[1]]);}
      }
      if(after)out.push(q);p=q;before=after;
    }return out;
  }
  function iou(a,b){
    let poly=footprint(a);const boundary=footprint(b);
    for(let j=0;j<4;j++)poly=clip(poly,boundary[j],boundary[(j+1)%4]);
    const area=poly.length?Math.abs(poly.reduce((s,p,j)=>s+p[0]*poly[(j+1)%poly.length][1]-poly[(j+1)%poly.length][0]*p[1],0)/2):0;
    const height=Math.max(0,Math.min(a.center[1]+a.half[1],b.center[1]+b.half[1])-Math.max(a.center[1]-a.half[1],b.center[1]-b.half[1]));
    const intersection=area*height,union=8*a.half.reduce((p,x)=>p*x,1)+8*b.half.reduce((p,x)=>p*x,1)-intersection;
    return union>0?intersection/union:0;
  }
  function fit(a,b,r){return Math.hypot(...a.center.map((x,j)=>x-b.center[j]))<=r.center_tolerance+1e-9 &&
    Math.max(...a.half.map((x,j)=>Math.abs(x-b.half[j])))<=r.extent_tolerance+1e-9 &&
    Math.abs(((a.yaw-b.yaw+90)%180+180)%180-90)<=r.yaw_tolerance+1e-9 && iou(a,b)>=r.iou_min-1e-9;}
  function handle(state,a,tool){
    if(tool==='plan')return project(state.views.plan,a.center);
    if(tool==='height'){const p=project(state.views.front,a.center);return [p[0]-22,p[1]];}
    if(tool==='yaw'){const r=a.yaw*Math.PI/180;return [115+56*Math.cos(r),80+56*Math.sin(r)];}
    const axis=Number(tool.at(-1));return [20+160*a.half[axis],25+40*axis];
  }
  function manipulate(state,a,tool,p,start=null,base=null){
    if(tool==='plan'){
      const v=state.views.plan;
      a.center[0]=start?base.center[0]+(p[0]-start[0])/v.scale:(p[0]-v.origin[0])/v.scale;
      a.center[2]=start?base.center[2]+(p[1]-start[1])/v.scale:(p[1]-v.origin[1])/v.scale;
    }else if(tool==='height'){
      const v=state.views.front;a.center[1]=start?base.center[1]-(p[1]-start[1])/v.scale:(v.origin[1]-p[1])/v.scale;
    }else if(tool==='yaw'){
      if(Math.hypot(p[0]-115,p[1]-80)<12)return;
      a.yaw=Math.atan2(p[1]-80,p[0]-115)*180/Math.PI;
    }else{
      const j=Number(tool.at(-1));a.half[j]=clamp(start?base.half[j]+(p[0]-start[0])/160:(p[0]-20)/160,.18,1);
    }
    a.center=a.center.map((x,j)=>clamp(x,...state.world.bounds[j]));
  }
  function hitObject(state,view,p,ms){
    const candidates=state.objects.map(o=>({id:o.id,d:Math.hypot(...project(state.views[view],pose(o,ms).center).map((v,j)=>v-p[j]))})).sort((a,b)=>a.d-b.d||a.id.localeCompare(b.id));
    return candidates[0].d<=14.01?candidates[0].id:null;
  }
  class Survey {
    constructor(state){this.state=state;this.annotations=clone(state.initial_annotations);this.objects=Object.fromEntries(state.objects.map(o=>[o.id,o]));this.links={};this.ms=0;this.charge=0;this.active=false;this.completed=false;this.failed='';this.lost=Object.fromEntries(state.targets.map(t=>[t.id,0]));}
    start(){
      if(this.active||this.completed||this.failed)return;
      const expected=Object.fromEntries(this.state.targets.map(t=>[t.id,this.state.objects.find(o=>o.color===t.color&&o.shape===t.shape).id]));
      if(JSON.stringify(Object.entries(this.links).sort())!==JSON.stringify(Object.entries(expected).sort()))this.failed='Camera links identify the wrong toys.';
      else this.active=true;
    }
    advance(end){
      const r=this.state.requirements,tick=this.state.world.tick_ms;
      while(this.active&&!this.completed&&!this.failed&&this.ms+tick<=end){
        this.ms+=tick;let allFit=true;
        for(const [label,id]of Object.entries(this.links)){
          const good=fit(this.annotations[label],pose(this.objects[id],this.ms),r);
          this.lost[label]=good?0:this.lost[label]+tick;allFit=allFit&&good;
          if(this.lost[label]>=r.lost_limit_ms)this.failed='A tug left its survey volume for too long.';
        }
        this.charge=clamp(this.charge+(allFit?tick:-tick*r.charge_leak),0,r.charge_ms);
        if(this.charge>=r.charge_ms&&!this.failed)this.completed=true;
        if(this.ms>=r.max_run_ms&&!this.completed)this.failed='The scan ended before all volumes were tracked.';
      }
    }
  }
  // Read-only diagnostic helpers for implementation checks, never a model API.
  window.SurveyorsToyboxV2Math={pose,project,corners,footprint,iou,fit,handle,manipulate,Survey};
  function record(kind,extra={}){model.events.push({sequence:model.events.length+1,kind,t_ms:model.sim.ms,input_source:model.interaction,...extra});}
  function payload(){return {mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
    physics_revision:REVISION,interaction_mode:model.interaction,events:model.events,final_t_ms:model.sim.ms,
    annotations:model.sim.annotations,links:model.sim.links,charge_ms:model.sim.charge,lost_ms:model.sim.lost,completed:model.sim.completed&&!model.sim.failed};}
  function sync(){
    if(!model||model.terminal)return;
    if(model.sim.active)model.sim.advance(Math.floor((performance.now()-model.startedAt)/20)*20);
    if(model.sim.failed)finish(false,model.sim.failed);
    else if(model.sim.completed)finish(true,'');
  }
  async function finish(success,reason){
    if(model.terminal)return;
    model.terminal=true;
    // Certification is administrative. A held edit cannot freeze the moving scan.
    record('certify');model.hold=null;
    const verdict=document.querySelector('.st2-verdict');verdict.hidden=false;
    verdict.dataset.kind=success?'pending':'fail';verdict.innerHTML=`<small>LIVE VOLUMETRIC SURVEY</small><strong>${success?'VERIFYING':'FAIL'}</strong><p>${clean(reason||'All tracked volumes acquired. Checking the survey.')}</p>`;
    try{
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
      const result=await response.json();model.outcome=result;
      verdict.dataset.kind=result.passed?'pass':'fail';verdict.querySelector('strong').textContent=result.passed?'PASS':'FAIL';
      verdict.querySelector('p').textContent=result.passed?'Camera identity and live 3D volume tracking verified.':`${reason||'Survey incomplete or rejected.'} This episode cannot be retried.`;
      model.helpers.setReadout(result.passed?'PASS · SURVEY SEALED':'FAIL · EPISODE ENDED',result.passed?'passed':'error');
    }catch(error){verdict.dataset.kind='error';verdict.querySelector('strong').textContent='ERROR';verdict.querySelector('p').textContent='Survey verifier unavailable.';model.helpers.setReadout('VERIFIER ERROR','error');}
  }
  function surfacePoint(event,canvas){const r=canvas.getBoundingClientRect();return [clamp((event.clientX-r.left)*canvas.width/r.width,0,canvas.width),clamp((event.clientY-r.top)*canvas.height/r.height,0,canvas.height)];}
  function toolSurface(tool){return tool==='plan'?'plan':tool==='height'?'front':tool==='yaw'?'dial':'extent';}
  function pointerDown(event){
    if(event.button!==0||model.terminal||model.hold)return;sync();if(model.terminal)return;
    const canvas=event.currentTarget,surface=canvas.dataset.surface,p=surfacePoint(event,canvas),a=model.sim.annotations[model.selected];
    if(model.tool==='link'){
      if(model.sim.active||!['plan','front'].includes(surface))return;
      const id=hitObject(model.state,surface,p,0);if(!id)return;
      if(model.interaction==='simplified'){record('link_click',{view:surface,point:p});model.sim.links[model.selected]=id;}
      else{record('link_start',{view:surface,point:p});model.hold={kind:'link',objectId:id,pointer:event.pointerId,canvas};canvas.setPointerCapture(event.pointerId);}
    }else if(surface===toolSurface(model.tool)){
      if(model.interaction==='simplified'){record('click',{surface,point:p});manipulate(model.state,a,model.tool,p);}
      else if(Math.hypot(...handle(model.state,a,model.tool).map((x,j)=>x-p[j]))<=14.01){
        record('down',{surface,point:p});model.hold={kind:'edit',start:p,base:clone(a),pointer:event.pointerId,canvas};canvas.setPointerCapture(event.pointerId);
      }
    }
    event.preventDefault();draw();
  }
  function pointerMove(event){
    if(model.terminal||!model.hold||model.hold.pointer!==event.pointerId)return;
    sync();if(model.terminal)return;
    if(model.hold.kind==='edit'){
      const p=surfacePoint(event,model.hold.canvas);record('move',{surface:model.hold.canvas.dataset.surface,point:p});
      manipulate(model.state,model.sim.annotations[model.selected],model.tool,p,model.hold.start,model.hold.base);
    }
    draw();
  }
  function pointerUp(event,cancel=false){
    if(model.terminal||!model.hold||model.hold.pointer!==event.pointerId)return;
    sync();if(model.terminal)return;
    const hold=model.hold;
    if(hold.kind==='link'){
      const r=document.querySelector('.st2-socket').getBoundingClientRect();
      if(!cancel&&event.clientX>=r.left&&event.clientX<=r.right&&event.clientY>=r.top&&event.clientY<=r.bottom){
        record('link_end',{socket_point:[(event.clientX-r.left)*100/r.width,(event.clientY-r.top)*100/r.height]});model.sim.links[model.selected]=hold.objectId;
      }else{record('link_cancel');}
    }else{
      const p=surfacePoint(event,hold.canvas);record(cancel?'cancel':'up',{surface:hold.canvas.dataset.surface,point:p});
      if(!cancel)manipulate(model.state,model.sim.annotations[model.selected],model.tool,p,hold.start,hold.base);
    }
    model.hold=null;hold.canvas.releasePointerCapture(event.pointerId);draw();
  }
  function line(ctx,points,color,width=1,closed=false){ctx.beginPath();ctx.moveTo(...points[0]);for(const p of points.slice(1))ctx.lineTo(...p);if(closed)ctx.closePath();ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();}
  const edges=[[0,1],[0,2],[0,4],[1,3],[1,5],[2,3],[2,6],[3,7],[4,5],[4,6],[5,7],[6,7]];
  function drawBox(ctx,b,projection,color,width=1){const c=corners(b).map(projection);for(const [a,z]of edges)line(ctx,[c[a],c[z]],color,width);}
  function disc(ctx,p,color,r=14){ctx.beginPath();ctx.arc(...p,r,0,Math.PI*2);ctx.strokeStyle=color;ctx.lineWidth=1;ctx.stroke();}
  function knob(ctx,p,color,label){ctx.beginPath();ctx.arc(...p,12,0,Math.PI*2);ctx.fillStyle='#0d1f2940';ctx.fill();ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();ctx.fillStyle=color;ctx.font='bold 10px monospace';ctx.textAlign='center';ctx.fillText(label,p[0],p[1]+4);ctx.textAlign='left';}
  function drawPlate(viewId){
    const canvas=document.querySelector(`[data-surface="${viewId}"]`),ctx=canvas.getContext('2d'),v=model.state.views[viewId],time=model.sim.ms;
    ctx.fillStyle='#102633';ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.strokeStyle='#2e4852';ctx.lineWidth=1;
    for(let x=12;x<440;x+=26)line(ctx,[[x,32],[x,400]],'#2e485240');
    for(let y=32;y<410;y+=26)line(ctx,[[12,y],[428,y]],'#2e485240');
    for(const obj of model.state.objects){
      const b=pose(obj,time),p=project(v,b.center),past=[];
      for(let j=0;j<=10;j++)past.push(project(v,pose(obj,Math.max(0,time-1000+j*100)).center));
      if(model.sim.active){line(ctx,past,obj.color+'70',3);ctx.setLineDash([3,5]);
        const forecast=model.state.world.forecast_ms,future=[];for(let j=0;j<=forecast/100;j++)future.push(project(v,pose(obj,time+j*100).center));line(ctx,future,obj.color+'aa',1.5);ctx.setLineDash([]);
        const end=pose(obj,time+forecast),ep=project(v,end.center);disc(ctx,ep,obj.color+'aa',5);
        if(viewId==='plan'){const a=end.yaw*Math.PI/180;line(ctx,[ep,[ep[0]+18*Math.cos(a),ep[1]+18*Math.sin(a)]],obj.color+'aa',1.5);}
      }
      drawBox(ctx,b,point=>project(v,point),obj.color+'b8',1.5);
      disc(ctx,p,obj.color+'90');
      ctx.fillStyle=obj.color;
      if(obj.shape==='tug'){
        const a=viewId==='plan'?b.yaw*Math.PI/180:0;ctx.save();ctx.translate(...p);ctx.rotate(a);ctx.beginPath();ctx.moveTo(-9,-8);ctx.lineTo(12,0);ctx.lineTo(-9,8);ctx.closePath();ctx.fill();ctx.restore();
      }else{line(ctx,[[p[0]-8,p[1]-7],[p[0]+8,p[1]+7]],obj.color,3);line(ctx,[[p[0]-8,p[1]+7],[p[0]+8,p[1]-7]],obj.color,3);}
    }
    for(const target of model.state.targets){
      const a=model.sim.annotations[target.id],selected=target.id===model.selected,id=model.sim.links[target.id],expected=id?pose(model.sim.objects[id],time):null;
      const good=expected&&fit(a,expected,model.state.requirements),color=good?'#d4ffc2':selected?'#fff4d1':target.color+'a0';
      ctx.setLineDash([8,4]);drawBox(ctx,a,point=>project(v,point),color,selected?2.5:1);ctx.setLineDash([]);
      const p=project(v,a.center);ctx.fillStyle=color;ctx.font='12px monospace';ctx.fillText(target.label,p[0]+13,p[1]-16);
      if(selected&&model.tool===(viewId==='plan'?'plan':'height'))knob(ctx,handle(model.state,a,model.tool),color,viewId==='plan'?'↔':'Y');
    }
    ctx.fillStyle='#8cb4c2';ctx.font='12px monospace';ctx.fillText(viewId==='plan'?'OVERHEAD CAMERA · X / Z':'FRONT CAMERA · X / Y',16,23);
    ctx.fillText(model.sim.active?`SOLID = NOW   DOTTED = +${(model.state.world.forecast_ms/1000).toFixed(1)} s`:'CALIBRATION · CAMERA LINK DISCS',16,407);
  }
  function drawCloud(){
    const canvas=document.querySelector('.st2-cloud'),ctx=canvas.getContext('2d'),iso=p=>[150+(p[0]*.84-p[2]*.54)*31,158-p[1]*29+(p[0]*.21+p[2]*.34)*23];
    ctx.fillStyle='#0b1c25';ctx.fillRect(0,0,300,210);
    for(let k=-3;k<=3;k++){line(ctx,[iso([k,0,-2]),iso([k,0,2])],'#3b616740');line(ctx,[iso([-3,0,k*.6]),iso([3,0,k*.6])],'#3b616740');}
    for(const obj of model.state.objects){const b=pose(obj,model.sim.ms),r=b.yaw*Math.PI/180;
      for(const p of obj.local_points){const w=[b.center[0]+p[0]*Math.cos(r)-p[2]*Math.sin(r),b.center[1]+p[1],b.center[2]+p[0]*Math.sin(r)+p[2]*Math.cos(r)],s=iso(w);ctx.fillStyle=obj.color;ctx.fillRect(s[0]-1.5,s[1]-1.5,3,3);}
    }
    for(const target of model.state.targets)drawBox(ctx,model.sim.annotations[target.id],iso,target.id===model.selected?'#f8f0d0':'#79949b',1);
  }
  function drawInstruments(){
    const a=model.sim.annotations[model.selected],target=model.state.targets.find(t=>t.id===model.selected);
    let canvas=document.querySelector('[data-surface="dial"]'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,230,160);
    disc(ctx,[115,80],'#446a76',56);ctx.fillStyle='#83a9b8';ctx.font='12px monospace';ctx.fillText('HEADING',10,15);
    line(ctx,[[115,80],handle(model.state,a,'yaw')],target.color,3);knob(ctx,handle(model.state,a,'yaw'),target.color,'↻');
    ctx.fillStyle='#d2e5e6';ctx.fillText(`${Math.round(a.yaw)}°`,98,154);
    canvas=document.querySelector('[data-surface="extent"]');ctx=canvas.getContext('2d');ctx.clearRect(0,0,230,130);
    ['W','H','D'].forEach((label,j)=>{line(ctx,[[20,25+40*j],[180,25+40*j]],'#446a76',3);ctx.fillStyle='#83a9b8';ctx.font='12px monospace';ctx.fillText(label,2,29+40*j);knob(ctx,handle(model.state,a,`extent${j}`),target.color,label);});
  }
  function draw(){
    if(!model)return;drawCloud();drawPlate('plan');drawPlate('front');drawInstruments();
    for(const t of model.state.targets){const card=document.querySelector(`[data-target="${t.id}"]`),linked=Boolean(model.sim.links[t.id]);card.dataset.selected=String(t.id===model.selected);card.querySelector('small').textContent=linked?'CAMERA LINKED':'CAMERA UNLINKED';card.querySelector('.st2-lost i').style.width=`${100*(1-model.sim.lost[t.id]/model.state.requirements.lost_limit_ms)}%`;}
    document.querySelector('.st2-charge i').style.width=`${100*model.sim.charge/model.state.requirements.charge_ms}%`;
    document.querySelector('.st2-charge span').textContent=`${(model.sim.charge/1000).toFixed(1)} / 8.0 s`;
    document.querySelector('.st2-phase').textContent=model.terminal?'SURVEY ENDED':model.sim.active?`LIVE SURVEY · ${((model.state.requirements.max_run_ms-model.sim.ms)/1000).toFixed(1)} s LEFT`:'CALIBRATION';
    document.querySelector('.st2-start').disabled=model.sim.active||model.terminal||Object.keys(model.sim.links).length!==model.state.targets.length;
    document.querySelector('.st2-socket').textContent=`LINK SOCKET · ${model.state.targets.find(t=>t.id===model.selected).label}`;
    document.querySelectorAll('[data-tool]').forEach(n=>n.dataset.selected=String(n.dataset.tool===model.tool));
  }
  function animate(){sync();draw();if(!model.terminal)frame=requestAnimationFrame(animate);}
  async function render(state,helpers){
    cancelAnimationFrame(frame);document.body.dataset.mechanic='surveyors-toybox-v2';
    model={state,helpers,sim:new Survey(state),interaction:state.interaction_mode,selected:state.targets[0].id,tool:'plan',events:[],hold:null,terminal:false,startedAt:0,outcome:null};
    window.surveyorsToyboxV2Model=model;
    const tools=[['link','LINK'],['plan','XZ MOVE'],['height','Y LIFT'],['yaw','HEADING'],['extent0','WIDTH'],['extent1','HEIGHT'],['extent2','DEPTH']];
    helpers.app.innerHTML=`<section class="st2-game" data-interaction="${model.interaction}">
      <header class="st2-head"><div><small>FIELD STATION 088 · SENSOR FUSION</small><h1>Surveyors Toybox V2</h1></div><div class="st2-phase">CALIBRATION</div><span>D${state.control_condition?.difficulty||5} · ${model.interaction.toUpperCase()}</span></header>
      <main class="st2-main"><aside class="st2-bench"><div class="st2-label">SPARSE 3D RETURNS</div><canvas class="st2-cloud" width="300" height="210"></canvas>
        <div class="st2-targets">${state.targets.map(t=>`<button data-target="${t.id}" style="--toy:${t.color}"><b>➤ ${t.label}</b><small>CAMERA UNLINKED</small><div class="st2-lost"><i></i></div></button>`).join('')}</div>
        <div class="st2-socket">LINK SOCKET</div><div class="st2-mini-tools"><canvas data-surface="dial" width="230" height="160"></canvas><canvas data-surface="extent" width="230" height="130"></canvas></div>
      </aside><section class="st2-cameras"><div class="st2-rules"><b>➤ TUGS ONLY · × PALLETS ARE LOOK-ALIKES</b><span>${model.interaction==='full'?'LINK: drag a camera disc to its socket. EDIT: drag the highlighted handle.':'LINK: select a tug, then click its camera disc. EDIT: select a tool, then click its desired coordinate.'}</span></div>
        <div class="st2-plates"><canvas data-surface="plan" width="440" height="420"></canvas><canvas data-surface="front" width="440" height="420"></canvas></div>
        <div class="st2-tools">${tools.map(([tool,label])=>`<button data-tool="${tool}">${label}</button>`).join('')}</div>
        <div class="st2-progress"><div><b>SIMULTANEOUS 3D FIT</b><div class="st2-charge"><i></i><span>0 / 8.0 s</span></div></div><p>START commits links; wrong links end the episode. Keep all tugs fitted. Brief slips recover; 10 s lost, 90 s expiry or incomplete CERTIFY end the episode.</p></div>
      </section></main><footer class="st2-foot"><div class="readout">Calibration edits are reversible. START commits links; CERTIFY is final. An ended episode cannot be retried.</div><button class="st2-start">START LIVE SURVEY</button><button class="st2-submit">CERTIFY SURVEY</button></footer>
      <div class="st2-verdict" hidden></div></section>`;
    document.querySelectorAll('[data-target]').forEach(n=>n.addEventListener('click',()=>{sync();if(model.terminal||model.hold)return;model.selected=n.dataset.target;record('select',{target_id:model.selected});draw();}));
    document.querySelectorAll('[data-tool]').forEach(n=>n.addEventListener('click',()=>{sync();if(model.terminal||model.hold||n.dataset.tool==='link'&&model.sim.active)return;model.tool=n.dataset.tool;record('tool',{tool:model.tool});draw();}));
    document.querySelectorAll('[data-surface]').forEach(c=>{c.addEventListener('pointerdown',pointerDown);c.addEventListener('pointermove',pointerMove);c.addEventListener('pointerup',e=>pointerUp(e));c.addEventListener('pointercancel',e=>pointerUp(e,true));c.addEventListener('lostpointercapture',e=>pointerUp(e,true));});
    document.querySelector('.st2-start').addEventListener('click',()=>{if(model.terminal||model.sim.active||model.hold)return;record('start');model.startedAt=performance.now();model.sim.start();if(model.tool==='link'){model.tool='plan';record('tool',{tool:'plan'});}helpers.setReadout('LIVE · TRACK EVERY VOLUME','pending');sync();draw();});
    document.querySelector('.st2-submit').addEventListener('click',()=>{sync();if(!model.terminal)finish(false,'Incomplete survey certified.');});
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.surveyors_toybox_v2={rootSelector:'.st2-game',render};
})();
