(() => {
  'use strict';
  let model = null, frame = 0, keyHandler = null;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const dist = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1]);
  const copy = x => JSON.parse(JSON.stringify(x));
  const colors = ['#77d8e5', '#ffbf71'];
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index+1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0)/4294967295*2-1;
  }
  function integral(seed, ms, span) {
    const u=Math.max(0,ms)/span, n=Math.floor(u), f=u-n;
    let total=0;
    for (let i=0;i<n;i++) total+=(noise(seed,i)+noise(seed,i+1))/2;
    const a=noise(seed,n), b=noise(seed,n+1);
    return span*(total+a*f+(b-a)*(f**3-f**4/2));
  }
  function reflect(x, lo, hi) {
    const width=hi-lo, z=((x-lo)%(2*width)+2*width)%(2*width);
    return lo+(z<=width?z:2*width-z);
  }
  function carrierPosition(world, o, ms) {
    const p=world.parameters, b=world.bounds;
    const sx=p.speed*(ms+.22*integral(o.seed_x,ms,p.motion_span_ms))/1000;
    const sy=p.speed*.58*(ms+.32*integral(o.seed_y,ms,p.motion_span_ms+700))/1000;
    return [reflect(o.x0+o.direction_x*sx,b[0],b[1]),reflect(o.y0+o.direction_y*sy,b[2],b[3])];
  }
  class EvidencePhysics {
    constructor(world) {
      this.world=world; this.tick=0; this.worldTick=0; this.active=false;
      this.phase='ready'; this.revealIndex=-1; this.charge=0;
      this.exposureActive=false; this.terminal=''; this.failed='';
      this.selected=0; this.hold=null; this.transition=null;
      this.exposureTransition=null; this.discoveries={};
      this.lenses=world.initial_lenses.map(point=>({position:[...point],velocity:[0,0],target:[...point],bound:null}));
    }
    orderedChanges() { return this.world.changes.slice().sort((a,b)=>a.at_ms-b.at_ms); }
    framed() {
      if(!this.lenses.every(lens=>lens.bound!==null))return false;
      return this.lenses.every(lens=>{
        const o=this.world.carriers.find(item=>item.id===lens.bound);
        return dist(lens.position,carrierPosition(this.world,o,this.worldTick*20))+o.radius<=this.world.parameters.lens_radius+1e-8;
      });
    }
    holdDecision(index) {
      const event=this.orderedChanges()[index];
      this.tick=Math.floor(event.at_ms/20); this.worldTick=this.tick;
      this.revealIndex=index; this.phase='decision';
    }
    beginReveal(index) {
      const target=Math.floor(this.orderedChanges()[index].at_ms/20);
      this.phase='reveal';
      this.transition={index,from:this.tick,to:target,startedAt:performance.now(),
        duration:Math.max(700,Math.min(2200,Math.max(1,target-this.tick)*7))};
    }
    beginExposure() {
      if(this.phase!=='decision'||!this.framed())return;
      this.phase='exposure'; this.exposureActive=true;
      this.exposureTransition={from:this.tick,to:this.tick+Math.ceil(this.world.exposure_ms/20),
        startedAt:performance.now(),duration:1700};
    }
    stepTick() {
      this.tick+=1;
      if(this.phase==='exposure') {
        this.charge=clamp(this.charge+(this.framed()?20:-20*this.world.exposure_loss_rate),0,this.world.exposure_ms);
        if(this.charge>=this.world.exposure_ms)this.terminal='pass';
        else if(this.tick*20>=this.world.max_ms){this.failed='film exhausted';this.terminal='fail';}
      } else this.worldTick=this.tick;
    }
    advanceTo(target) { while(this.tick<target&&!this.terminal)this.stepTick(); }
    updateTransition(now) {
      const transition=this.transition;
      if(transition) {
        const ratio=clamp((now-transition.startedAt)/transition.duration,0,1);
        this.advanceTo(Math.floor(transition.from+(transition.to-transition.from)*ratio));
        if(ratio>=1){this.advanceTo(transition.to);this.transition=null;this.holdDecision(transition.index);}
      }
      if(this.exposureTransition&&!this.terminal) {
        const transition=this.exposureTransition;
        const ratio=clamp((now-transition.startedAt)/transition.duration,0,1);
        this.advanceTo(Math.floor(transition.from+(transition.to-transition.from)*ratio));
        if(ratio>=1){this.advanceTo(transition.to);this.exposureTransition=null;}
      }
    }
    inspect(index) {
      const w=this.world, ms=this.worldTick*20, lens=this.lenses[index], revealed=[];
      for(const o of w.carriers) {
        if(dist(lens.position,carrierPosition(w,o,ms))+o.radius>w.parameters.lens_radius+1e-8)continue;
        const change=w.changes.find(e=>e.object_id===o.id);
        this.discoveries[o.id]={pattern:o.pattern,inspected_at_ms:ms,reversal_at_ms:ms>=change.at_ms?change.at_ms:null};
        revealed.push(o.id);
      }
      return revealed;
    }
  }
  window.FirstChangeEvidencePhysics = {EvidencePhysics,carrierPosition,noise,integral};
  function record(kind, details={}) {
    model.events.push({sequence:model.events.length+1,kind,tick:model.sim.tick,...details});
  }
  function sync() {
    if (!model || model.submitting) return;
    model.sim.updateTransition(performance.now());
  }
  function point(event) {
    const box=document.querySelector('#fce-canvas').getBoundingClientRect(), w=model.state.world;
    return [Number(clamp((event.clientX-box.left)/box.width*w.width,0,w.width).toFixed(4)),
      Number(clamp((event.clientY-box.top)/box.height*w.height,0,w.height).toFixed(4))];
  }
  function moveLens(lens,xy) {
    lens.position=[...xy]; lens.target=[...xy]; lens.velocity=[0,0];
  }
  function maybeStartExposure() {
    if(model.sim.phase==='decision'&&model.sim.lenses.every(lens=>lens.bound!==null))model.sim.beginExposure();
  }
  function act(kind, details={}) {
    if (model.submitting || model.sim.terminal || model.sim.transition ||
        (model.sim.exposureTransition && kind!=='submit')) return;
    sync();
    if (model.sim.terminal) { paint(); publish(); return; }
    const sim=model.sim, w=model.state.world;
    record(kind,details);
    if (kind==='start') { sim.active=true; sim.beginReveal(0); }
    else if (kind==='select') sim.selected=details.lens;
    else if (kind==='aim' || kind==='drag_move') moveLens(sim.lenses[details.lens],details.point);
    else if (kind==='drag_start') { sim.hold=details.lens; sim.selected=details.lens; }
    else if (kind==='drag_end') sim.hold=null;
    else if (kind==='inspect') {
      sim.selected=details.lens;
      const revealed=sim.inspect(details.lens);
      model.helpers.setReadout(revealed.length?'NEGATIVE READ · NOTEBOOK UPDATED':'NO CARRIER FULLY FRAMED · ADJUST LENS','idle');
    }
    else if (kind==='bind') {
      const lens=sim.lenses[details.lens];
      const hit=w.carriers.map(o=>({o,d:dist(lens.position,carrierPosition(w,o,sim.worldTick*20))})).sort((a,b)=>a.d-b.d||a.o.id.localeCompare(b.o.id))[0];
      const target=w.changes.slice().sort((a,b)=>a.at_ms-b.at_ms)[details.lens];
      if (hit.d>w.bind_radius || hit.o.id!==target.object_id || sim.worldTick*20<target.at_ms) {
        sim.failed='wrong carrier or empty binding'; sim.terminal='fail';
      } else {
        lens.bound=hit.o.id;
        if(details.lens+1<sim.lenses.length)sim.beginReveal(details.lens+1);
        else maybeStartExposure();
      }
    } else if (kind==='submit') { sim.failed='incomplete exposure'; sim.terminal='fail'; }
    paint();
    if (sim.terminal) publish();
  }
  function bind(index) {
    if (!model.sim.active || model.sim.lenses[index].bound!==null || model.sim.terminal) return;
    if (model.interaction==='simplified') act('select',{lens:index,input_source:'lens_controls'});
    act('bind',{lens:index,input_source:model.interaction==='full'?'space_key':'bind_button'});
  }
  function motif(ctx, pattern, changed=false, scale=1) {
    ctx.save(); ctx.scale(scale,scale);
    const n=3+pattern%4;
    ctx.strokeStyle=changed?'#ffbf71':'#cee5e7'; ctx.fillStyle=changed?'#ffbf71':'#89bac3'; ctx.lineWidth=2;
    for(let i=0;i<n;i++) {
      const a=i*Math.PI*2/n+(pattern>=4?Math.PI/n:0);
      ctx.save(); ctx.rotate(a); ctx.beginPath();
      if(changed) { ctx.moveTo(2,0);ctx.lineTo(13,-5);ctx.lineTo(13,5); }
      else { ctx.moveTo(14,0);ctx.lineTo(3,-5);ctx.lineTo(3,5); }
      ctx.closePath(); if(pattern>=4) ctx.stroke(); else ctx.fill(); ctx.restore();
    }
    ctx.beginPath();ctx.arc(0,0,2.5,0,Math.PI*2);ctx.fill();ctx.restore();
  }
  function paint() {
    if (!model) return;
    const c=document.querySelector('#fce-canvas'), ctx=c.getContext('2d'), w=model.state.world, sim=model.sim, ms=sim.worldTick*20;
    const grad=ctx.createLinearGradient(0,0,0,w.height);grad.addColorStop(0,'#102b35');grad.addColorStop(1,'#07191f');
    ctx.fillStyle=grad;ctx.fillRect(0,0,w.width,w.height);
    ctx.strokeStyle='#6eacb318';ctx.lineWidth=1;
    for(let x=45;x<960;x+=58){ctx.beginPath();ctx.moveTo(x,45);ctx.lineTo(x,395);ctx.stroke();}
    for(let y=45;y<440;y+=50){ctx.beginPath();ctx.moveTo(45,y);ctx.lineTo(915,y);ctx.stroke();}
    ctx.strokeStyle='#779ba061';ctx.lineWidth=2;ctx.strokeRect(24,24,912,392);
    ctx.font='11px ui-monospace,monospace';ctx.fillStyle='#94b8bd';ctx.fillText('LIVE EMULSION / PETALS REVERSE, THEN RETURN',43,20);
    for(const o of w.carriers) {
      const xy=carrierPosition(w,o,ms), before=carrierPosition(w,o,Math.max(0,ms-200));
      ctx.beginPath();ctx.moveTo(...carrierPosition(w,o,Math.max(0,ms-600)));
      for(let t=Math.max(0,ms-550);t<=ms;t+=50)ctx.lineTo(...carrierPosition(w,o,t));
      ctx.strokeStyle='#abcdd660';ctx.lineWidth=3;ctx.stroke();
      // Opaque negatives reveal neither identity nor reversal until inspected.
      // Keep earned identity visible, including its normal later change cues.
      const known=Object.hasOwn(sim.discoveries,o.id);
      const change=w.changes.find(e=>e.object_id===o.id), changed=known && ms>=change.at_ms && ms<change.at_ms+change.duration_ms;
      ctx.save();ctx.translate(...xy);
      ctx.shadowColor=changed?'#ffbf71':'#72c6d0';ctx.shadowBlur=changed?16:8;
      ctx.beginPath();ctx.arc(0,0,o.radius,0,Math.PI*2);ctx.fillStyle=changed?'#543e28':'#1c414d';ctx.fill();
      ctx.shadowBlur=0;ctx.lineWidth=changed?3:2;ctx.strokeStyle=changed?'#ffce8f':'#6eabb6';ctx.stroke();
      if(known)motif(ctx,o.pattern,changed);
      else {ctx.fillStyle='#94b0b5';ctx.font='16px ui-monospace,monospace';ctx.textAlign='center';ctx.fillText('?',0,6);}
      const a=Math.atan2(xy[1]-before[1],xy[0]-before[0]);
      ctx.rotate(a);ctx.beginPath();ctx.moveTo(28,-4);ctx.lineTo(35,0);ctx.lineTo(28,4);ctx.strokeStyle='#d1f2ed';ctx.lineWidth=2;ctx.stroke();ctx.restore();
    }
    sim.lenses.forEach((lens,i)=>{
      const radius=w.parameters.lens_radius;
      ctx.beginPath();ctx.moveTo(...lens.position);ctx.lineTo(...lens.target);ctx.setLineDash([4,6]);ctx.strokeStyle=colors[i]+'70';ctx.lineWidth=1;ctx.stroke();ctx.setLineDash([]);
      ctx.save();ctx.translate(...lens.position);
      ctx.beginPath();ctx.arc(0,0,radius,0,Math.PI*2);ctx.fillStyle=colors[i]+'0b';ctx.fill();ctx.strokeStyle=colors[i];ctx.lineWidth=sim.selected===i?3:2;ctx.stroke();
      ctx.beginPath();ctx.moveTo(-9,0);ctx.lineTo(9,0);ctx.moveTo(0,-9);ctx.lineTo(0,9);ctx.stroke();
      ctx.fillStyle=colors[i];ctx.font='bold 16px ui-monospace,monospace';ctx.fillText(String.fromCharCode(65+i),-radius+10,-radius+20);ctx.restore();
      const chip=document.querySelector(`#fce-lens-${i}`);chip.dataset.selected=String(sim.selected===i);
      chip.querySelector('small').textContent=lens.bound?'BOUND · KEEP FRAMED':'UNBOUND';
      const icon=chip.querySelector('canvas').getContext('2d');icon.clearRect(0,0,38,38);
      if(lens.bound){icon.save();icon.translate(19,19);motif(icon,w.carriers.find(o=>o.id===lens.bound).pattern);icon.restore();}
    });
    const entries=Object.values(sim.discoveries).sort((a,b)=>a.pattern-b.pattern);
    const notebook=document.querySelector('#fce-notebook');
    const content=JSON.stringify(entries);
    if(notebook.dataset.content!==content) {
      notebook.dataset.content=content;
      notebook.innerHTML=entries.length?entries.map(d=>`<div class="fce-negative" data-pattern="${d.pattern}"><canvas width="38" height="38"></canvas><span>${d.reversal_at_ms===null?`NO REVERSAL BY ${(d.inspected_at_ms/1000).toFixed(1)} s`:`REVERSED @ ${(d.reversal_at_ms/1000).toFixed(1)} s`}</span></div>`).join(''):'<span>Aim a lens over a carrier and inspect its negative. Readings stay here.</span>';
      notebook.querySelectorAll('canvas').forEach((c,i)=>{const ink=c.getContext('2d');ink.translate(19,19);motif(ink,entries[i].pattern);});
    }
    document.querySelector('#fce-charge').style.width=`${100*sim.charge/w.exposure_ms}%`;
    document.querySelector('#fce-exposure').textContent=`${(sim.charge/1000).toFixed(1)} / ${(w.exposure_ms/1000).toFixed(1)} s`;
    document.querySelector('#fce-clock').textContent=`${Math.max(0,(w.max_ms-ms)/1000).toFixed(1)} s`;
    document.querySelector('#fce-start').disabled=sim.active || !!sim.terminal;
    document.querySelector('#fce-certify').disabled=!!sim.terminal;
    document.querySelectorAll('.fce-bind').forEach((b,i)=>{b.disabled=!sim.active||sim.lenses[i].bound!==null||!!sim.terminal;});
    document.querySelectorAll('.fce-inspect').forEach(b=>{b.disabled=!!sim.terminal;});
    const shell=document.querySelector('.fce-desk');shell.dataset.verdict=sim.terminal;
    document.querySelector('#fce-verdict strong').textContent=sim.terminal.toUpperCase();
    document.querySelector('#fce-verdict span').textContent=sim.terminal==='pass'?'FIRST-CHANGE EXPOSURE COMPLETE':sim.failed.toUpperCase();
  }
  async function publish() {
    if (model.submitting) return;
    model.submitting=true;
    const m=model;
    m.payload={mechanic_id:m.state.mechanic_id,revision:m.state.revision,task_id:m.state.task_id,
      challenge_id:m.state.challenge_id,interaction_mode:m.interaction,events:copy(m.events),
      final_tick:m.sim.tick,charge_ms:m.sim.charge,completed:m.sim.terminal==='pass'};
    try {
      const response=await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(m.payload)});
      m.serverGrade=await response.json();
      m.helpers.setReadout(m.serverGrade.passed?'PASS · EVIDENCE VERIFIED':'FAIL · '+(m.sim.failed||'REPLAY REJECTED'),m.serverGrade.passed?'passed':'error');
      if (!m.serverGrade.passed && m.sim.terminal==='pass') {
        document.querySelector('#fce-verdict strong').textContent='REPLAY ERROR';
        document.querySelector('#fce-verdict span').textContent=m.serverGrade.feedback||'VERIFICATION FAILED';
      }
    } catch(error){m.helpers.setReadout('VERIFIER ERROR · '+error.message,'error');}
  }
  function animate() {
    sync();paint();if(model?.sim.terminal && !model.submitting)publish();
    frame=requestAnimationFrame(animate);
  }
  async function render(state,helpers) {
    cancelAnimationFrame(frame);if(keyHandler)window.removeEventListener('keydown',keyHandler);
    document.body.dataset.mechanic='first-change-evidence';
    model={state,helpers,sim:new EvidencePhysics(state.world),interaction:state.control_condition?.interaction||'full',
      events:[],startedAt:performance.now(),submitting:false,serverGrade:null,payload:null};
    window.firstChangeEvidenceV3Model=model;
    helpers.app.innerHTML=`<section class="fce-desk"><header><div><span>THE LIVE EVIDENCE DESK / ONE FILM</span><h1>First Change Memory V3</h1></div><div class="fce-clock">FILM LEFT <b id="fce-clock">75.0 s</b></div></header>
      <div class="fce-brief">${state.prompt}<br><span>${model.interaction==='full'?'Drag a lens to steer it; right-click the lens to inspect. SPACE binds its centred carrier.':'Choose STEER, then click a scene point. INSPECT reads that lens; BIND commits its centred carrier.'} Inspection reveals a fully framed carrier’s motif and past reversal time. Readings persist; each deliberate reveal holds its decision state. Wrong binding ends the film.</span></div>
      <div class="fce-workspace"><div class="fce-stage"><canvas id="fce-canvas" width="960" height="440"></canvas><div id="fce-verdict"><strong></strong><span></span></div></div>
      <aside class="fce-notes" aria-label="inspected negatives"><b>INSPECTED NEGATIVES</b><div id="fce-notebook"></div></aside></div>
      <div class="fce-tools">${state.world.initial_lenses.map((_,i)=>`<div class="fce-lens" id="fce-lens-${i}"><canvas width="38" height="38"></canvas><div><b>LENS ${String.fromCharCode(65+i)} · ${i===0?'FIRST':'SECOND'} CHANGE</b><small>UNBOUND</small></div>${model.interaction==='simplified'?`<button class="fce-select" data-lens="${i}">STEER ${String.fromCharCode(65+i)}</button><button class="fce-inspect" data-lens="${i}">INSPECT ${String.fromCharCode(65+i)}</button><button class="fce-bind" data-lens="${i}">BIND ${String.fromCharCode(65+i)}</button>`:''}</div>`).join('')}
      <div class="fce-exposure"><span>JOINT EXPOSURE <b id="fce-exposure">0.0 / 6.5 s</b></span><div><i id="fce-charge"></i></div><small>All carriers must fit inside their lenses. Lost framing erases exposure.</small></div></div>
      <footer><button id="fce-start">ROLL FILM</button><div class="readout">Inspect negatives without binding. Earliest reversal belongs to A${state.world.initial_lenses.length===2?'; next to B':''}.</div><button id="fce-certify">CERTIFY EXPOSURE</button></footer></section>`;
    const canvas=document.querySelector('#fce-canvas');
    canvas.addEventListener('pointerdown',event=>{
      if(event.button!==0 || model.sim.terminal || model.submitting)return;
      sync();if(model.sim.terminal)return;
      const xy=point(event), sim=model.sim;
      if(model.interaction==='simplified')act('aim',{lens:sim.selected,point:xy,input_source:'lens_controls'});
      else {
        const candidates=sim.lenses.map((l,i)=>({i,d:dist(l.position,xy)})).filter(x=>x.d<=state.world.parameters.lens_radius).sort((a,b)=>a.d-b.d);
        if(!candidates.length || sim.hold!==null)return;
        act('drag_start',{lens:candidates[0].i,point:xy,input_source:'lens_drag'});
        canvas.setPointerCapture(event.pointerId);
      }
      event.preventDefault();
    });
    canvas.addEventListener('pointermove',event=>{if(model.sim.hold!==null&&!model.sim.terminal)act('drag_move',{lens:model.sim.hold,point:point(event),input_source:'lens_drag'});});
    const release=event=>{
      if(model.sim.hold===null||model.sim.terminal)return;
      act('drag_end',{lens:model.sim.hold,point:point(event),input_source:'lens_drag'});
      if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);
    };
    canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);canvas.addEventListener('lostpointercapture',release);
    canvas.addEventListener('contextmenu',event=>{
      event.preventDefault();
      if(model.interaction!=='full'||model.sim.terminal||model.submitting)return;
      sync();if(model.sim.terminal)return;
      const xy=point(event), candidates=model.sim.lenses.map((l,i)=>({i,d:dist(l.position,xy)})).filter(x=>x.d<=state.world.parameters.lens_radius).sort((a,b)=>a.d-b.d||a.i-b.i);
      if(candidates.length)act('inspect',{lens:candidates[0].i,point:xy,input_source:'lens_inspection'});
    });
    document.querySelector('#fce-start').addEventListener('click',()=>{if(!model.sim.active)act('start',{input_source:'start_button'});});
    document.querySelector('#fce-certify').addEventListener('click',()=>act('submit',{input_source:'certify_button'}));
    document.querySelectorAll('.fce-select').forEach(b=>b.addEventListener('click',()=>act('select',{lens:Number(b.dataset.lens),input_source:'lens_controls'})));
    document.querySelectorAll('.fce-inspect').forEach(b=>b.addEventListener('click',()=>act('inspect',{lens:Number(b.dataset.lens),input_source:'inspect_button'})));
    document.querySelectorAll('.fce-bind').forEach(b=>b.addEventListener('click',()=>bind(Number(b.dataset.lens))));
    keyHandler=event=>{if(event.code==='Space'&&model.interaction==='full'){event.preventDefault();if(!event.repeat)bind(model.sim.selected);}};
    window.addEventListener('keydown',keyHandler);paint();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.temporal_memory_first_change_v3_nonrealtime={rootSelector:'.fce-desk',render};
})();
