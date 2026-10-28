(() => {
  'use strict';
  const ID='rorschach_fixed_rubric_v3_nonrealtime', COLORS=['#127c83','#c65949','#795d9a'];
  const ACTION_EVENTS=new Set(['begin','release','place']);
  let model, raf=0;
  function channel(knots,t) {
    let index=0;
    while(index<knots.length-2 && knots[index+1][0]<=t) index++;
    const a=knots[index], b=knots[index+1], f=Math.max(0,Math.min(1,(t-a[0])/(b[0]-a[0])));
    return a[1]+(b[1]-a[1])*f*f*(3-2*f);
  }
  function inkCentres(s,t) {
    const q=Object.fromEntries(Object.entries(s.channels).map(([k,v])=>[k,channel(v,t)]));
    const x=460+q.x,y=210+q.y,span=190+q.spread,a=q.twist;
    const out=[[x-span*Math.cos(a),y-span*Math.sin(a)],[x+span*Math.cos(a),y+span*Math.sin(a)]];
    if(s.parameters.landmarks===3) out.push([x+q.flex,y+110]);
    return out;
  }
  function padTargets(s,t) {const points=inkCentres(s,t);return s.registration.map(i=>points[i]);}
  const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
  class Press {
    constructor(s) {
      this.state=s;this.t_ms=0;this.started=false;this.pads=inkCentres(s,0).map(p=>({p:[...p],v:[0,0],aim:[...p]}));
      this.developed=0;this.spilled=0;this.terminal='';this.drag=null;this.selected=null;
      this.inspected=new Set();
    }
    advance(until) {
      if(!this.started) return;
      const s=this.state,h=s.dt_ms/1000;
      while(this.t_ms+s.dt_ms<=until&&!this.terminal) {
        this.t_ms+=s.dt_ms;
        for(const pad of this.pads) {
          const a=pad.p.map((p,i)=>s.parameters.spring*(pad.aim[i]-p)-s.parameters.damping*pad.v[i]);
          let scale=Math.min(1,s.acceleration_limit/Math.max(Math.hypot(...a),1e-12));
          for(let i=0;i<2;i++) pad.v[i]+=a[i]*scale*h;
          scale=Math.min(1,s.speed_limit/Math.max(Math.hypot(...pad.v),1e-12));
          for(let i=0;i<2;i++) {
            const limit=i===0?s.stage.width:s.stage.height;
            pad.v[i]*=scale;pad.p[i]+=pad.v[i]*h;
            if(pad.p[i]<0||pad.p[i]>limit) {pad.p[i]=Math.max(0,Math.min(limit,pad.p[i]));pad.v[i]=0;}
          }
        }
        const targets=padTargets(s,this.t_ms);
        const fits=this.pads.map((pad,i)=>distance(pad.p,targets[i])<=s.parameters.tolerance);
        if(fits.every(Boolean)) this.developed=Math.min(s.development_seconds,this.developed+h);
        else {this.developed=Math.max(0,this.developed-s.fade_rate*h);this.spilled+=h*fits.filter(f=>!f).length/fits.length;}
        if(this.spilled>=s.spill_limit-1e-9) this.terminal='spill';
        else if(this.developed>=s.development_seconds-1e-9) this.terminal='printed';
        else if(this.t_ms>=s.duration_ms) this.terminal='expired';
      }
    }
    place(i,point) {
      this.pads[i].aim=[...point];
      if(!this.started) {this.pads[i].p=[...point];this.pads[i].v=[0,0];}
    }
    event(e) {
      if(e.kind==='begin') this.started=true;
      else if(e.kind==='inspect') this.inspected.add(e.contact);
      else if(e.kind==='grab') this.drag={index:e.pad,offset:this.pads[e.pad].p.map((p,i)=>p-e.point[i])};
      else if(e.kind==='move'||e.kind==='release') {
        this.place(this.drag.index,e.point.map((p,i)=>Math.max(0,Math.min(i===0?this.state.stage.width:this.state.stage.height,p+this.drag.offset[i]))));
        if(e.kind==='release') this.drag=null;
      } else if(e.kind==='cancel') this.drag=null;
      else if(e.kind==='select') this.selected=e.pad;
      else if(e.kind==='place') this.place(e.pad,e.point);
    }
    snapshot() {
      return {t_ms:this.t_ms,started:this.started,pads:JSON.parse(JSON.stringify(this.pads)),
        developed:this.developed,spilled:this.spilled,terminal:this.terminal,inspected:[...this.inspected].sort()};
    }
  }
  function settleAfterAction() {
    if(!model||model.finished) return;
    if(model.press.started) {
      const step=model.state.action_window_ms;
      if(Number.isInteger(step)&&step>0) model.press.advance(Math.min(model.state.duration_ms,model.press.t_ms+step));
    }
    if(model.press.terminal) finish();
  }
  function record(kind,extra={},synchronized=false) {
    if(model.finished) return false;
    const e={sequence:model.events.length+1,t_ms:model.press.t_ms,input_source:model.interaction,kind,...extra};
    model.events.push(e);model.press.event(e);
    if(ACTION_EVENTS.has(kind)) settleAfterAction();
    return true;
  }
  async function finish(reason='') {
    if(model.finished) return;
    model.finished=true;
    const p=model.press,s=model.state;
    model.result={mechanic_id:ID,task_id:s.task_id,challenge_id:s.challenge_id,revision:s.revision,
      interaction:model.interaction,events:model.events,final_t_ms:p.t_ms,developed:p.developed,spilled:p.spilled,
      completed:p.terminal==='printed'};
    const root=document.querySelector('.living-ink');
    root.dataset.outcome=p.terminal==='printed'?'checking':'fail';
    model.helpers.setReadout(p.terminal==='printed'?'VERIFYING PRINT…':`FAIL · ${reason||p.terminal.toUpperCase()}`,p.terminal==='printed'?'pending':'error');
    document.querySelectorAll('.living-ink button').forEach(b=>b.disabled=true);
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(model.result)});
      model.grade=await response.json();root.dataset.outcome=model.grade.passed?'pass':'fail';
      model.helpers.setReadout(model.grade.passed?'PASS · THE RUBRIC IS SATISFIED':`FAIL · ${reason||p.terminal.toUpperCase()||'INCOMPLETE PRINT'}`,model.grade.passed?'passed':'error');
    } catch(error) {root.dataset.outcome='error';model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`,'error');}
    draw();
  }
  function point(e) {
    const r=model.canvas.getBoundingClientRect();
    return [Math.max(0,Math.min(920,(e.clientX-r.left)*920/r.width)),Math.max(0,Math.min(440,(e.clientY-r.top)*440/r.height))];
  }
  function circle(ctx,p,r) {ctx.beginPath();ctx.arc(p[0],p[1],r,0,Math.PI*2);}
  function inspect(q) {
    if(model.finished)return;
    const ink=inkCentres(model.state,model.press.t_ms);
    const contact=ink.findIndex(p=>distance(p,q)<=model.state.inspection_radius);
    if(contact<0||model.press.inspected.has(contact))return;
    if(record('inspect',{contact,point:q},true)) {
      const aperture=model.state.registration.indexOf(contact);
      model.helpers.setReadout(`${model.state.contact_labels[contact]} MARK · APERTURE ${aperture+1}`,'idle');
      draw();
    }
  }
  function draw() {
    if(!model) return;
    const c=model.ctx,p=model.press,s=model.state,ink=inkCentres(s,p.t_ms);
    c.clearRect(0,0,920,440);c.fillStyle='#f6f0df';c.fillRect(0,0,920,440);
    c.strokeStyle='#d8d0bd';c.lineWidth=.7;
    for(let x=20;x<920;x+=40) {c.beginPath();c.moveTo(x,0);c.lineTo(x,440);c.stroke();}
    for(let y=20;y<440;y+=40) {c.beginPath();c.moveTo(0,y);c.lineTo(920,y);c.stroke();}
    // Original procedural ink art. Coloured circular centres are the rubric's contact geometry.
    const centre=[(ink[0][0]+ink[1][0])/2,(ink[0][1]+ink[1][1])/2];
    for(let i=0;i<2;i++) {
      const q=ink[i],sign=i===0?-1:1;
      c.fillStyle='#252235';c.beginPath();c.moveTo(...centre);
      c.bezierCurveTo(q[0]+sign*50,q[1]-100,q[0]+sign*80,q[1]-70,q[0],q[1]);
      c.bezierCurveTo(q[0]+sign*50,q[1]+85,q[0]-sign*10,q[1]+125,centre[0],centre[1]+75);c.closePath();c.fill();
      c.fillStyle='#695570';c.beginPath();c.ellipse(q[0],q[1]-32,24,47,sign*.4,0,Math.PI*2);c.fill();
    }
    if(ink[2]) {c.fillStyle='#252235';c.beginPath();c.ellipse(ink[2][0],ink[2][1]-45,19,65,0,0,Math.PI*2);c.fill();}
    for(let i=0;i<ink.length;i++) {
      const aperture=s.registration.indexOf(i),known=p.inspected.has(i),color=known?COLORS[aperture]:'#766879';
      c.strokeStyle=color;c.lineWidth=3;c.globalAlpha=.42;c.setLineDash([]);c.beginPath();
      for(let dt=-s.trail_ms;dt<=0;dt+=50) {const q=inkCentres(s,Math.max(0,p.t_ms+dt))[i];if(dt===-s.trail_ms)c.moveTo(...q);else c.lineTo(...q);}c.stroke();
      c.globalAlpha=.8;c.setLineDash([3,6]);c.beginPath();
      for(let dt=0;dt<=s.forecast_ms;dt+=50) {const q=inkCentres(s,p.t_ms+dt)[i];if(dt===0)c.moveTo(...q);else c.lineTo(...q);}c.stroke();
      c.setLineDash([]);c.globalAlpha=1;
      circle(c,ink[i],s.ink_radius);c.fillStyle=color;c.fill();c.lineWidth=2;c.strokeStyle='#faf3dd';c.stroke();
      c.fillStyle='#fff';c.font='bold 15px sans-serif';c.textAlign='center';c.fillText(known?String(aperture+1):'?',ink[i][0],ink[i][1]+5);
      const archive=document.querySelector(`.ink-mark-${i}`);
      archive.textContent=known?`${s.contact_labels[i]} → APERTURE ${aperture+1}`:`${s.contact_labels[i]} · MARK CONCEALED`;
      archive.style.color=color;
    }
    const targets=padTargets(s,p.t_ms);
    for(let i=0;i<p.pads.length;i++) {
      const known=p.inspected.has(s.registration[i]);
      const pad=p.pads[i],radius=s.ink_radius+s.parameters.tolerance,fit=distance(pad.p,targets[i])<=s.parameters.tolerance;
      circle(c,pad.p,radius);c.fillStyle=known?(fit?'#39aa8614':'#e07e5514'):'#76687914';c.fill();c.lineWidth=3;c.strokeStyle=COLORS[i];c.stroke();
      circle(c,pad.p,radius+7);c.lineWidth=1;c.strokeStyle='#57505e';c.stroke();
      c.fillStyle=COLORS[i];c.font='bold 12px monospace';c.textAlign='center';c.fillText(`A${i+1}`,pad.p[0],pad.p[1]-radius-10);
      if(ink.every(q=>distance(pad.p,q)>s.ink_radius+6)) {
        c.strokeStyle=COLORS[i];c.lineWidth=2;c.beginPath();c.moveTo(pad.p[0]-9,pad.p[1]);c.lineTo(pad.p[0]+9,pad.p[1]);c.moveTo(pad.p[0],pad.p[1]-9);c.lineTo(pad.p[0],pad.p[1]+9);c.stroke();
      }
      if(distance(pad.aim,pad.p)>3) {c.globalAlpha=.55;c.setLineDash([3,4]);c.beginPath();c.moveTo(...pad.p);c.lineTo(...pad.aim);c.stroke();c.setLineDash([]);circle(c,pad.aim,5);c.stroke();c.globalAlpha=1;}
      const badge=document.querySelector(`.ink-status-${i}`);badge.dataset.fit=known?String(fit):'unknown';badge.textContent=known?(fit?'REGISTERED':'UNCOVERED'):'INSPECT INK MARK';
    }
    c.fillStyle='#766879';c.textAlign='left';c.font='12px monospace';c.fillText('SOLID FIBRE: RECENT FLOW     DOTTED FIBRE: NEXT 1.2 s',18,422);
    const ratio=Math.min(1,p.developed/s.development_seconds);
    document.querySelector('.ink-development i').style.width=`${ratio*100}%`;
    document.querySelector('.ink-print-art').style.opacity=String(.12+.88*ratio);
    document.querySelector('.ink-spill i').style.height=`${Math.min(1,p.spilled/s.spill_limit)*100}%`;
    document.querySelector('.ink-percent').textContent=`${p.terminal==='printed'?100:Math.floor(ratio*100)}%`;
    document.querySelector('.ink-sheet-time').textContent=p.started?`${Math.ceil((s.duration_ms-p.t_ms)/1000)} s`:'READY';
  }
  function animate() {draw();raf=requestAnimationFrame(animate);}
  function render(state,helpers) {
    cancelAnimationFrame(raf);document.body.dataset.mechanic='living-ink-press';
    const interaction=state.control_condition?.interaction||'full';
    model={state,helpers,interaction,press:new Press(state),events:[],finished:false};window.livingInkModel=model;
    helpers.app.innerHTML=`<section class="living-ink" data-interaction="${interaction}" data-outcome="ready">
      <header class="inkv2-head"><div><span>THE DEPARTMENT OF OBJECTIVE FEELINGS</span><h1>Rorschach / Subjective Prompt With A Fixed Rubric V3</h1></div><b class="ink-sheet-time">READY</b></header>
      <div class="inkv2-rubric"><b>“I SEE A BUTTERFLY.”</b><span>Inspect the ? ink centres with the pointer to uncover this sheet’s registration marks. Keep each centre wholly inside its marked aperture. Uncovered ink spills and washes out the print.</span></div>
      <main class="inkv2-main"><canvas class="inkv2-field" width="920" height="440" aria-label="Living ink and draggable registration apertures"></canvas>
        <aside><p>REGISTRATION APERTURES</p>${state.labels.map((label,i)=>`<div class="ink-pad-card" style="--pad:${COLORS[i]}"><b>${label}</b><span class="ink-status-${i}">INSPECT INK MARK</span>${interaction==='simplified'?`<button class="ink-proxy" data-pad="${i}" aria-label="Select ${label}">SELECT</button>`:''}</div>`).join('')}
        <div class="ink-mark-archive"><b>UNCOVERED REGISTRATION MARKS</b>${state.contact_labels.map((label,i)=>`<span class="ink-mark-${i}">${label} · MARK CONCEALED</span>`).join('')}</div>
        <div class="ink-print-panel"><span>DEVELOPED PRINT <b class="ink-percent">0%</b></span><div class="ink-development"><i></i></div><svg class="ink-print-art" viewBox="0 0 200 100" aria-hidden="true"><path d="M100 50 C5 -20 4 74 82 53 C8 104 89 104 100 52 C111 104 192 104 118 53 C196 74 195 -20 100 50 M100 22 Q90 70 100 92 Q110 70 100 22"/></svg><div class="ink-gutter"><span>SPILL GUTTER</span><div class="ink-spill"><i></i></div></div></div>
        <div class="ink-mode-instruction">${interaction==='full'?'Drag an aperture by its ring or centre; release to leave its motor aim.':'Select an aperture, then click its motor aim in the field.'} Prepare before BEGIN FLOW. Each deliberate action advances one fixed flow window; waiting and inspection hold the current state.</div></aside></main>
      <footer><button class="ink-begin">BEGIN FLOW</button><div class="readout">PREPARE THE APERTURES · THEN BEGIN FLOW</div><button class="ink-certify">CERTIFY PRINT</button></footer>
      <div class="ink-terminal"><span>FIXED RUBRIC</span><strong></strong><p class="ink-terminal-text"></p></div></section>`;
    model.canvas=document.querySelector('.inkv2-field');model.ctx=model.canvas.getContext('2d');
    document.querySelector('.ink-begin').addEventListener('click',()=>{
      if(!model.press.started&&!model.finished&&record('begin')) {document.querySelector('.ink-begin').disabled=true;helpers.setReadout('FLOW ACTIVE · REGISTER ALL INK CENTRES','pending');}
    });
    document.querySelector('.ink-certify').addEventListener('click',()=>{finish('INCOMPLETE PRINT');});
    for(const b of document.querySelectorAll('.ink-proxy')) b.addEventListener('click',()=>{
      if(record('select',{pad:Number(b.dataset.pad)})) document.querySelectorAll('.ink-proxy').forEach(n=>n.dataset.selected=String(n===b));
    });
    model.canvas.addEventListener('pointerdown',e=>{
      if(e.button!==0||model.finished) return;
      const q=point(e);
      inspect(q);
      if(interaction==='simplified') {if(model.press.selected!==null) record('place',{pad:model.press.selected,point:q},true);return;}
      const candidates=model.press.pads.map((p,i)=>({i,d:distance(p.p,q)})).filter(v=>v.d<=state.ink_radius+state.parameters.tolerance+10).sort((a,b)=>a.d-b.d);
      if(!candidates.length||model.press.drag) return;
      e.preventDefault();if(record('grab',{pad:candidates[0].i,point:q},true)) model.canvas.setPointerCapture(e.pointerId);
    });
    model.canvas.addEventListener('pointermove',e=>{
      if(!model.finished)inspect(point(e));
      if(model.press.drag&&!model.finished) {e.preventDefault();record('move',{pad:model.press.drag.index,point:point(e)},true);}
    });
    model.canvas.addEventListener('pointerup',e=>{
      if(model.press.drag&&!model.finished) {e.preventDefault();record('release',{pad:model.press.drag.index,point:point(e)},true);}
      if(model.canvas.hasPointerCapture(e.pointerId)) model.canvas.releasePointerCapture(e.pointerId);
    });
    const cancel=()=>{if(model.press.drag&&!model.finished)record('cancel');};
    model.canvas.addEventListener('pointercancel',cancel);model.canvas.addEventListener('lostpointercapture',cancel);
    draw();raf=requestAnimationFrame(animate);
  }
  window.LivingInkPress={Press,inkCentres,padTargets,channel};
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.living-ink',render};
})();
