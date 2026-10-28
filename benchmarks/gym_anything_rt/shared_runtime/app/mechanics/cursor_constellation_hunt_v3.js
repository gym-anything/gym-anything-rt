(() => {
  'use strict';
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  const copy = v => structuredClone(v);
  const dist = (a,b) => Math.hypot(a[0]-b[0],a[1]-b[1]);
  function targetAt(field,ms) {
    const u = Math.max(0,ms)/field.span_ms;
    const i = Math.min(Math.floor(u),field.path.length-2), f = Math.min(1,u-i);
    const blend = f*f*(3-2*f), a = field.path[i], b = field.path[i+1];
    return a.map((v,k) => v+(b[k]-v)*blend);
  }
  function targetVelocity(field,ms) {
    const u = Math.max(0,ms)/field.span_ms;
    const i = Math.min(Math.floor(u),field.path.length-2), f = Math.min(1,u-i);
    return field.path[i].map((v,k) => (field.path[i+1][k]-v)*6*f*(1-f)*1000/field.span_ms);
  }
  class Optics {
    constructor(world) {
      this.world=world; this.ms=0; this.origin=null; this.passed=false; this.failed=''; this.drag=null;
      this.lenses=world.fields.map(f => ({p:[...f.initial_lens],v:[...f.initial_velocity],target:[...f.initial_lens],charge:0}));
    }
    advance(absoluteMs) {
      if (this.origin===null) return;
      const w=this.world, end=absoluteMs-this.origin, dt=w.tick_ms/1000;
      while (this.ms+w.tick_ms<=end && !this.failed && !this.passed) {
        this.ms+=w.tick_ms;
        this.lenses.forEach((lens,index) => {
          for (const axis of [0,1]) {
            const force=clamp((lens.target[axis]-lens.p[axis])*w.spring-lens.v[axis]*w.damping,-w.acceleration_cap,w.acceleration_cap);
            lens.v[axis]=clamp(lens.v[axis]+force*dt,-w.max_speed,w.max_speed);
            lens.p[axis]=clamp(lens.p[axis]+lens.v[axis]*dt,16,304);
            if (lens.p[axis]===16 || lens.p[axis]===304) lens.v[axis]=0;
          }
          const good=dist(lens.p,targetAt(w.fields[index],this.ms))<=w.tolerance;
          lens.charge=clamp(lens.charge+w.tick_ms*(good?1:-w.fade_rate),0,w.exposure_ms);
        });
        this.passed=this.lenses.every(l => l.charge>=w.exposure_ms);
        if (this.ms>=w.max_active_ms && !this.passed) this.failed='EXPOSURE EXPIRED';
      }
    }
    snapshot() {return {ms:this.ms,origin:this.origin,passed:this.passed,failed:this.failed,lenses:copy(this.lenses),drag:this.drag};}
  }
  let model=null, raf=0;
  const now = () => Math.max(0,Math.round(performance.now()-model.epoch));
  function record(kind,details={},at=now()) {
    model.events.push({sequence:model.events.length+1,kind,t_ms:at,input_source:model.mode,...details});
  }
  function sync(at=now()) {
    if (!model || model.terminal) return;
    model.sim.advance(at);
    if (model.sim.origin!==null) {
      const snap=model.sim.snapshot();
      if (!model.history.length || model.history.at(-1).ms!==snap.ms) model.history.push(snap);
      model.history=model.history.filter(s => s.ms>=snap.ms-model.state.world.trail_window_ms-100);
    }
    if (model.sim.passed || model.sim.failed) finish(at);
  }
  function starPoint(star,lens,field,ms) {
    const goal=targetAt(field,ms), error=lens.p.map((v,k) => v-goal[k]);
    const c=Math.cos(star.angle), s=Math.sin(star.angle);
    return [star.anchor[0]+c*error[0]-s*error[1],star.anchor[1]+s*error[0]+c*error[1]];
  }
  function wideGuidePoint(star,lens,field,ms) {
    // A fixed, invertible view of the same optical point, relative to its
    // anchor. Lens coordinates are 16..304 and alignment stays in 60..260:
    // both scope coordinates are therefore 6..250, including boundary play.
    const p=starPoint(star,lens,field,ms);
    return p.map((v,k)=>128+(v-star.anchor[k])/2);
  }
  function circle(ctx,p,r,stroke,fill=null) {
    ctx.beginPath();ctx.arc(p[0],p[1],r,0,Math.PI*2);
    if (fill) {ctx.fillStyle=fill;ctx.fill();}
    if (stroke) {ctx.strokeStyle=stroke;ctx.stroke();}
  }
  function drawField(index) {
    const canvas=document.querySelector(`canvas[data-field="${index}"]`), ctx=canvas.getContext('2d');
    const w=model.state.world, f=w.fields[index], l=model.sim.lenses[index];
    const good=dist(l.p,targetAt(f,model.sim.ms))<=w.tolerance;
    const bg=ctx.createRadialGradient(160,140,12,160,160,230);
    bg.addColorStop(0,'#122e46');bg.addColorStop(1,'#050d20');
    ctx.fillStyle=bg;ctx.fillRect(0,0,320,320);
    ctx.strokeStyle='#25445b';ctx.lineWidth=.5;
    for(let p=40;p<320;p+=40) {ctx.beginPath();ctx.moveTo(p,0);ctx.lineTo(p,320);ctx.moveTo(0,p);ctx.lineTo(320,p);ctx.stroke();}
    // Grey flecks are clearly separate from the colored exposure stars.
    for (const p of f.noise) circle(ctx,p,1.2,null,'#466475');
    ctx.lineWidth=1;
    ctx.strokeStyle='#54768b';ctx.beginPath();
    f.stars.forEach((star,j) => j?ctx.lineTo(...star.anchor):ctx.moveTo(...star.anchor));
    ctx.closePath();ctx.stroke();
    f.stars.forEach((star,j) => {
      // Each halo has exactly the norm used by replay; all transforms are
      // orthogonal. A star on the boundary is a valid exposure, in every mode.
      circle(ctx,star.anchor,w.tolerance,j===0?'#bfa369':'#26465b');
      if (model.sim.origin!==null) {
        ctx.beginPath();
        model.history.filter((s,k) => k%2===0).forEach((s,k) => {
          const p=starPoint(star,s.lenses[index],f,s.ms);
          k?ctx.lineTo(...p):ctx.moveTo(...p);
        });
        ctx.strokeStyle=j===0?'#dfbd8280':'#90dceb38';ctx.stroke();
      }
      const p=starPoint(star,l,f,model.sim.ms);
      circle(ctx,p,j===0?5:2.5,null,j===0?'#ffe0a0':good?'#b2ffd2':'#93ddf4');
      if (j===0) {ctx.strokeStyle='#ffe0a0';ctx.strokeRect(star.anchor[0]-6,star.anchor[1]-6,12,12);}
    });
    ctx.lineWidth=2;
    circle(ctx,l.p,19,model.sim.drag===index?'#ffffff':'#faaa9e','#ef827a18');
    ctx.strokeStyle='#faaa9e';ctx.beginPath();ctx.moveTo(l.p[0]-26,l.p[1]);ctx.lineTo(l.p[0]+26,l.p[1]);ctx.moveTo(l.p[0],l.p[1]-26);ctx.lineTo(l.p[0],l.p[1]+26);ctx.stroke();
    // The commanded point is visible separately from the inertial lens.
    circle(ctx,l.target,3,'#faaa9e');
    // The main field may clip stars at large lens errors. The wide view keeps
    // the actual guide and its bounded recent motion visible without moving
    // a physical star, clamping feedback, or changing the input surface.
    const guide=f.stars.find(star=>star.guide), p=wideGuidePoint(guide,l,f,model.sim.ms);
    const scope=document.querySelector(`[data-guide-scope="${index}"]`);
    const dot=scope.querySelector('[data-guide-current]');
    dot.setAttribute('cx',p[0]);dot.setAttribute('cy',p[1]);
    const trail=model.history.filter(s=>s.ms>=model.sim.ms-w.trail_window_ms)
      .map(s=>wideGuidePoint(guide,s.lenses[index],f,s.ms));
    scope.querySelector('[data-guide-trail]').setAttribute('d',
      trail.map((point,k)=>`${k?'L':'M'}${point[0]},${point[1]}`).join(' '));
    document.querySelector(`[data-meter="${index}"] i`).style.width=`${100*l.charge/w.exposure_ms}%`;
    document.querySelector(`[data-meter="${index}"]`).dataset.sharp=good?'true':'false';
    document.querySelector(`[data-caption="${index}"]`).textContent=model.sim.origin===null?'PREPARE LENS':good?'EXPOSING':'FADING';
  }
  function draw() {
    model.state.world.fields.forEach((_,i) => drawField(i));
    document.getElementById('ccv2-time').textContent=model.sim.origin===null?'READY':`${Math.max(0,Math.ceil((model.state.world.max_active_ms-model.sim.ms)/1000))} s`;
  }
  async function finish(at=now()) {
    if (!model || model.terminal) return;
    model.terminal=true;record('seal',{},at);
    const passed=model.sim.passed && !model.sim.failed;
    document.getElementById('ccv2-verdict').textContent=passed?'VERIFYING':'FAIL';
    document.querySelector('.ccv2').dataset.verdict=passed?'pending':'fail';
    document.getElementById('ccv2-start').disabled=true;
    document.getElementById('ccv2-seal').disabled=true;
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      interaction_mode:model.mode,events:copy(model.events),completed:passed,final:model.sim.snapshot()};
    model.payload=payload;
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const outcome=await response.json();model.grade=outcome;
      const yes=outcome.passed===true;
      document.querySelector('.ccv2').dataset.verdict=yes?'pass':'fail';
      document.getElementById('ccv2-verdict').textContent=yes?'PASS':'FAIL';
      model.helpers.setReadout(yes?'ALL CONSTELLATIONS EXPOSED TOGETHER':model.sim.failed || 'EXPOSURE INCOMPLETE',yes?'passed':'error');
    } catch(error) {
      document.querySelector('.ccv2').dataset.verdict='error';
      document.getElementById('ccv2-verdict').textContent='VERIFIER ERROR';
      model.helpers.setReadout(String(error),'error');
    }
  }
  function point(event,index) {
    const rect=document.querySelector(`canvas[data-field="${index}"]`).getBoundingClientRect();
    return [clamp((event.clientX-rect.left)*320/rect.width,0,320),clamp((event.clientY-rect.top)*320/rect.height,0,320)].map(x=>Math.round(x*10000)/10000);
  }
  function retarget(index,p) {
    const l=model.sim.lenses[index];l.target=p.map(x=>clamp(x,16,304));
    if(model.sim.origin===null) l.p=[...l.target];
  }
  function animate() {sync();draw();raf=requestAnimationFrame(animate);}
  function render(state,helpers) {
    cancelAnimationFrame(raf);
    document.body.dataset.mechanic='cursor-constellation-v2';
    model={state,helpers,mode:state.control_condition.interaction,epoch:performance.now(),sim:new Optics(state.world),events:[],history:[],terminal:false,grade:null};
    window.cursorConstellationV3Model=model;
    const verb=model.mode==='full'?'Drag each coral lens':'Click a field to set its lens target';
    helpers.app.innerHTML=`<section class="ccv2" data-verdict="" data-interaction="${model.mode}">
      <header><div><span>THE DRIFT OBSERVATORY</span><h1>Cursor-Controlled Constellation Hunt V3</h1></div><b id="ccv2-time">READY</b></header>
      <p class="ccv2-rule">${verb}. Probe each lens before exposure: its gold guide has a fixed response direction that varies between hunts and fields. Learn how your moves shift it, then bring every star into its halo. Start exposure and keep all bars full together.</p>
      <div class="ccv2-fields">${state.world.fields.map((f,i)=>`<article><div class="ccv2-field-title"><b>${['I','II','III'][i]} · ${f.shape.toUpperCase()}</b><span data-caption="${i}">PREPARE LENS</span></div><canvas data-field="${i}" width="320" height="320" aria-label="Constellation field ${i+1}"></canvas><div class="ccv2-guide"><svg data-guide-scope="${i}" viewBox="0 0 256 256" role="img" aria-label="Wide view of the same gold guide and recent trail for field ${i+1}"><path class="ccv2-guide-grid" d="M64 12V344M128 12V344M192 12V344M12 64H244M12 128H244M12 192H244"/><circle class="ccv2-guide-halo" data-guide-halo="${i}" cx="128" cy="128" r="${state.world.tolerance/2}"/><rect class="ccv2-guide-anchor" x="122" y="122" width="12" height="12"/><path class="ccv2-guide-trail" data-guide-trail="${i}"/><circle class="ccv2-guide-dot" data-guide-current="${i}" cx="128" cy="128" r="5"/></svg><div><b>WIDE GUIDE</b><span>Scaled view of the same<br>gold star and recent trail.</span><span>Keep it near the center.<br>Steer the lens above.</span></div></div><div class="ccv2-meter" data-meter="${i}"><i></i></div></article>`).join('')}</div>
      <div class="ccv2-note"><span>Compare the gold guide before and after a lens move to discover its response. The same response lasts for this hunt. The square is its center.</span><span>The wide guide stays visible at the field edges. During exposure, gold trails show recent motion and the coral lens has inertia. Blur fades exposure twice as fast as sharpness fills it. ${state.world.fields.length>1?'Every field keeps evolving while you adjust another.':''}</span></div>
      <footer><div class="readout" data-status="idle">Prepare safely: lens probes are reversible. No restart during an exposure.</div><button id="ccv2-start">START EXPOSURE</button><button id="ccv2-seal">SEAL EXPOSURE</button></footer>
      <div id="ccv2-verdict" role="status"></div></section>`;
    state.world.fields.forEach((_,i)=>{
      const canvas=document.querySelector(`canvas[data-field="${i}"]`);
      canvas.addEventListener('pointerdown',e=>{
        if(model.terminal || e.button!==0) return;
        // Layout can cross a physics tick. Sample once for replay and physics.
        const at=now();sync(at);if(model.terminal) return;
        const p=point(e,i);
        if(model.mode==='simplified') {record('aim',{field:i,point:p},at);retarget(i,p);}
        else if(model.sim.drag===null && dist(p,model.sim.lenses[i].p)<=22) {
          model.sim.drag=i;record('down',{field:i,point:p},at);canvas.setPointerCapture(e.pointerId);
        }
        e.preventDefault();draw();
      });
      canvas.addEventListener('pointermove',e=>{
        if(model.terminal || model.mode!=='full' || model.sim.drag!==i) return;
        const at=now();sync(at);if(model.terminal) return;
        const p=point(e,i);record('move',{field:i,point:p},at);retarget(i,p);e.preventDefault();draw();
      });
      const up=e=>{
        if(model.terminal || model.mode!=='full' || model.sim.drag!==i) return;
        const at=now();sync(at);if(model.terminal) return;
        record('up',{field:i,point:point(e,i)},at);model.sim.drag=null;
        if(canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
        draw();
      };
      canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',up);
      canvas.addEventListener('lostpointercapture',up);
    });
    document.getElementById('ccv2-start').addEventListener('click',()=>{
      if(model.terminal || model.sim.origin!==null || model.sim.drag!==null) return;
      record('start');model.sim.origin=model.events.at(-1).t_ms;
      document.getElementById('ccv2-start').disabled=true;
      helpers.setReadout('EXPOSURE RUNNING · TRACK THE DRIFT','pending');
    });
    document.getElementById('ccv2-seal').addEventListener('click',()=>{const at=now();sync(at);finish(at);});
    draw();raf=requestAnimationFrame(animate);
  }
  window.CursorConstellationV3={Optics,targetAt,targetVelocity,starPoint,wideGuidePoint};
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.cursor_constellation_hunt_v3={rootSelector:'.ccv2',render};
})();
