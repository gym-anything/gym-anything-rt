(() => {
  'use strict';
  const G = typeof window === 'undefined' ? globalThis : window;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const distance = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1]);
  function target(track, ms) {
    const k = track.knots;
    let i = 0;
    while (i+1 < k.length-1 && k[i+1].t_ms <= ms) i++;
    const a = k[i], b = k[i+1], f = clamp((ms-a.t_ms)/(b.t_ms-a.t_ms), 0, 1), s = f*f*(3-2*f);
    return {point: a.point.map((v, j) => v+(b.point[j]-v)*s), grip: a.grip};
  }
  const ACTION_KINDS = new Set(['grip', 'aim', 'down', 'move', 'up', 'cancel']);
  class Simulation {
    constructor(w) {
      Object.assign(this, {w, ms:0, started:false, done:false, failed:'', held:null});
      this.tools = w.tracks.map(t => ({point:[...t.initial_point], velocity:[0,0], aim:[...t.initial_point], grip:t.initial_grip, charge:0}));
    }
    advance(end) {
      const w = this.w, dt = w.tick_ms/1000;
      while (this.started && !this.done && !this.failed && this.ms+w.tick_ms <= end) {
        this.ms += w.tick_ms;
        this.tools.forEach((tool, i) => {
          [336,390].forEach((limit, axis) => {
            const a = clamp(w.spring*(tool.aim[axis]-tool.point[axis])-w.damping*tool.velocity[axis], -w.acceleration, w.acceleration);
            tool.velocity[axis] = clamp(tool.velocity[axis]+a*dt, -w.speed, w.speed);
            tool.point[axis] = clamp(tool.point[axis]+tool.velocity[axis]*dt, 8, limit-8);
            if (tool.point[axis] === 8 || tool.point[axis] === limit-8) tool.velocity[axis] = 0;
          });
          const t = target(w.tracks[i], this.ms);
          const good = distance(t.point, tool.point)+w.tip_radius <= w.parameters.radius && t.grip === tool.grip;
          tool.charge = clamp(tool.charge+dt*(good ? 1 : -w.decay), 0, w.charge_cap);
        });
        if (this.tools.every(t => t.charge >= w.charge_seconds-1e-9)) this.done = true;
        else if (this.ms >= w.deadline_ms) this.failed = 'The traces faded before the exhibition closed.';
      }
    }
    advanceAction() {
      this.advance(Math.min(this.ms + this.w.action_step_ms, this.w.deadline_ms));
    }
    event(e, mode) {
      if (this.done || this.failed) throw Error('input after terminal outcome');
      const k = e.kind;
      if (k === 'start') { if (this.started || this.held) throw Error('repeated start'); this.started = true; return; }
      if (k === 'close') { this.failed = 'The exhibition was closed before every trace was restored.'; return; }
      const tool = this.tools[e.tool];
      if (k === 'grip') { tool.grip = e.grip; return; }
      if (k === 'aim') tool.aim = [...e.point];
      else if (k === 'down') { this.held = [e.tool, e.button]; tool.grip = e.button; }
      else { tool.aim = [...e.point]; if (k !== 'move') this.held = null; }
    }
    snapshot() { return JSON.parse(JSON.stringify({ms:this.ms, started:this.started, done:this.done, failed:this.failed, held:this.held, tools:this.tools})); }
  }
  G.MuseumGestureV2 = {Simulation, target};
  let cleanup = () => {};
  async function render(state, h) {
    cleanup();
    document.body.dataset.mechanic = 'museum-gestures-v2';
    const w = state.world, mode = state.control_condition?.interaction || 'full', sim = new Simulation(w);
    const abort = new AbortController(), events = [];
    let closed = false, frame = 0, sending = false;
    const text = h.text;
    h.app.innerHTML = `<section class="mgv2" data-interaction="${mode}">
      <header><div><span>DEPARTMENT OF HUMAN INPUT · KINETIC COLLECTION</span><h1>Museum of Lost Gestures <em>II</em></h1></div><div class="mg-edition">${String(w.parameters.tools).padStart(2,'0')}<small>MEMORIES<br>IN MOTION</small></div></header>
      <div class="mg-instructions">Keep the whole dark tip inside each moving ring, using its shown hand. Traces fade outside or with the wrong hand; fill all together.<br>Tips glide toward your aim. Dotted threads preview 1.2 seconds; labels give seconds ahead and the hand.<br>The gallery changes only after deliberate input; each input advances one fixed ${w.action_step_ms} ms slice, so idle waiting leaves this view unchanged.<br>${mode === 'full' ? 'Drag a brass handle with LEFT for an open hand, RIGHT for a pinch. Release to leave its aim in place.' : 'Click a chamber to aim its nib. Use OPEN / PINCH below each chamber to change the hand.'}</div>
      <canvas id="mg-canvas" width="${w.width}" height="${w.height}" aria-label="Kinetic restoration room"></canvas>
      <div class="mg-grips">${w.tracks.map((t,i) => `<div style="left:${100*t.rect[0]/w.width}%;width:${100*336/w.width}%"><span>${text(t.name)}</span>${mode === 'simplified' ? `<button data-tool="${i}" data-grip="0">OPEN · L</button><button data-tool="${i}" data-grip="2">PINCH · R</button>` : '<span class="mg-hand-note">LEFT DRAG / RIGHT DRAG</span>'}</div>`).join('')}</div>
      <footer><div class="readout" data-status="idle">THE GALLERY IS STILL · PREPARE YOUR HANDS</div><div><button id="mg-start">Begin restoration ↗</button><button id="mg-close">Close exhibition</button></div></footer>
      <div class="mg-verdict" hidden></div></section>`;
    const canvas = document.getElementById('mg-canvas'), ctx = canvas.getContext('2d');
    const model = {sim, state, events, mode, view:() => ({...sim.snapshot(), rect:canvas.getBoundingClientRect().toJSON()})};
    window.museumGesturesV2Model = model;
    function listen(node, type, fn) { node.addEventListener(type, fn, {signal:abort.signal}); }
    // The counterpart has an action clock: rendering and idle wall time never
    // advance the world. Each deliberate input advances one fixed slice below.
    function sync() {}
    function record(kind, extra={}) {
      sync();
      if (closed || sim.done || sim.failed) { if (!closed) finish(); return false; }
      const e = {sequence:events.length+1, kind, t_ms:sim.ms, input_source:mode, ...extra};
      events.push(e); sim.event(e, mode);
      if (ACTION_KINDS.has(kind)) sim.advanceAction();
      return true;
    }
    function canvasPoint(e) {
      const r = canvas.getBoundingClientRect();
      return [(e.clientX-r.left)*w.width/r.width, (e.clientY-r.top)*w.height/r.height];
    }
    function local(p, i) {
      const r = w.tracks[i].rect;
      return [clamp(p[0]-r[0],8,328), clamp(p[1]-r[1],8,382)].map(v => Math.round(v*1000)/1000);
    }
    function pane(p) { return w.tracks.findIndex(t => p[0]>=t.rect[0] && p[0]<=t.rect[0]+336 && p[1]>=t.rect[1] && p[1]<=t.rect[1]+390); }
    function arrow(p, color, scale=1) {
      ctx.save(); ctx.translate(...p); ctx.scale(scale,scale); ctx.beginPath();
      ctx.moveTo(0,0); ctx.lineTo(0,18); ctx.lineTo(5,13); ctx.lineTo(11,21); ctx.lineTo(15,19); ctx.lineTo(9,11); ctx.lineTo(17,11); ctx.closePath();
      ctx.fillStyle=color; ctx.fill(); ctx.restore();
    }
    function draw() {
      const background = ctx.createLinearGradient(0,0,0,470); background.addColorStop(0,'#171e23'); background.addColorStop(1,'#090e13'); ctx.fillStyle=background;ctx.fillRect(0,0,w.width,w.height);
      w.tracks.forEach((track,i) => {
        const [x,y,cw,ch] = track.rect, tool=sim.tools[i], t=target(track,sim.ms);
        ctx.save(); ctx.translate(x,y); ctx.strokeStyle='#526164';ctx.lineWidth=1;ctx.strokeRect(0,0,cw,ch);
        ctx.fillStyle='#b9c4bf';ctx.font='13px Courier New';ctx.fillText(`0${i+1} / ${track.name.toUpperCase()}`,10,-28);
        // Original pointer crowd: faint previous positions are memory, not colliders.
        for (let j=8;j>=1;j--) arrow(target(track,Math.max(0,sim.ms-j*100)).point,`rgba(100,166,156,${.08+j*.012})`,.8);
        // The short, visible forecast makes every pending turn and grip observable.
        ctx.beginPath(); for(let d=0;d<=w.guide_ms;d+=60) { const p=target(track,sim.ms+d).point; if(!d)ctx.moveTo(...p);else ctx.lineTo(...p); }
        ctx.setLineDash([4,7]);ctx.strokeStyle='#9d9564';ctx.lineWidth=2;ctx.stroke();ctx.setLineDash([]);
        ctx.fillStyle='rgba(70,180,156,.06)';ctx.strokeStyle=t.grip===0?'#8ecfb7':'#bcace8';ctx.lineWidth=3;
        ctx.beginPath();ctx.arc(...t.point,w.parameters.radius,0,Math.PI*2);ctx.fill();ctx.stroke();
        ctx.strokeStyle='#ffffff2b';ctx.beginPath();ctx.moveTo(t.point[0]-12,t.point[1]);ctx.lineTo(t.point[0]+12,t.point[1]);ctx.moveTo(t.point[0],t.point[1]-12);ctx.lineTo(t.point[0],t.point[1]+12);ctx.stroke();
        ctx.fillStyle='#e4eadf';ctx.textAlign='center';ctx.font='bold 15px Courier New';ctx.fillText(t.grip===0?'OPEN · L':'PINCH · R',t.point[0],t.point[1]-w.parameters.radius-9);ctx.textAlign='left';
        // Paint only the part of the pickup disc that can receive chamber input.
        ctx.save();ctx.beginPath();ctx.rect(0,0,cw,ch);ctx.clip();
        ctx.beginPath();ctx.arc(...tool.point,w.pickup_radius,0,Math.PI*2);ctx.fillStyle='#e6c575';ctx.fill();ctx.strokeStyle='#fff0b5';ctx.lineWidth=2;ctx.stroke();
        ctx.beginPath();ctx.arc(...tool.point,w.tip_radius,0,Math.PI*2);ctx.fillStyle=tool.grip===0?'#1d4135':'#463357';ctx.fill();
        ctx.restore();
        ctx.strokeStyle='#e6c57588';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(...tool.point);ctx.lineTo(...tool.aim);ctx.stroke();ctx.strokeRect(tool.aim[0]-5,tool.aim[1]-5,10,10);
        // Timed marks expose the delayed contact and a short physical lead.
        // Stagger labels so nearby forecast points do not hide one another.
        [900,1100].forEach((delay,j)=>{
          const f=target(track,sim.ms+delay),right=f.point[0]>230;
          ctx.fillStyle=f.grip===0?'#b7e5ce':'#d3c5f4';ctx.beginPath();ctx.arc(...f.point,3,0,Math.PI*2);ctx.fill();
          ctx.font='bold 11px Courier New';ctx.textAlign=right?'right':'left';ctx.strokeStyle='#0d171e';ctx.lineWidth=3;
          const label=`+${(delay/1000).toFixed(1)}s ${f.grip===0?'L':'R'}`,lx=f.point[0]+(right?-9:9),ly=f.point[1]+(j?18:-11);
          ctx.strokeText(label,lx,ly);ctx.fillText(label,lx,ly);ctx.textAlign='left';
        });
        ctx.fillStyle='#34413f';ctx.fillRect(0,402,cw,10);ctx.fillStyle='#a1d7b4';ctx.fillRect(0,402,cw*Math.min(1,tool.charge/w.charge_seconds),10);
        ctx.fillStyle='#d0d6bc';ctx.font='12px Courier New';ctx.fillText(`${tool.charge.toFixed(2)} / ${w.charge_seconds.toFixed(2)}s TRACE / ${tool.grip===0?'OPEN':'PINCH'}`,5,433);
        ctx.restore();
      });
      if (!sim.started) {ctx.fillStyle='#dfd7b9';ctx.font='12px Courier New';ctx.textAlign='right';ctx.fillText('DOTTED THREAD: NEXT 1.2 SECONDS · ARROWS: RECENT MOTION',w.width-20,w.height-5);ctx.textAlign='left';}
      const start=document.getElementById('mg-start'); start.disabled=sim.started || closed;
      document.querySelectorAll('[data-grip]').forEach(b=>{b.classList.toggle('selected',sim.tools[Number(b.dataset.tool)].grip===Number(b.dataset.grip));b.disabled=closed;});
    }
    async function finish() {
      if (sending || closed) return;
      sending=true;closed=true;
      const done=sim.done&&!sim.failed, verdict=document.querySelector('.mg-verdict');
      verdict.hidden=false;verdict.innerHTML=`<b>${done?'RESTORED':'FAIL'}</b><span>${done?'THE HANDS REMEMBER TOGETHER':text(sim.failed)}</span>`;
      h.setReadout(done?'RESTORATION · VERIFYING':'FAIL · EPISODE ENDED',done?'pending':'error');
      try {
        const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,control_condition:state.control_condition||null,events,completed:sim.done,charges:sim.tools.map(t=>t.charge),final_t_ms:sim.ms})});
        const result=await response.json();model.outcome=result;
        h.setReadout(result.passed?'PASS · THE EXHIBITION IS COMPLETE':'FAIL · EPISODE ENDED',result.passed?'passed':'error');
        verdict.dataset.passed=result.passed?'true':'false';verdict.querySelector('b').textContent=result.passed?'PASS':'FAIL';
      } catch(error) {h.setReadout('ARCHIVE ERROR · '+error.message,'error'); model.error=String(error);}
      draw();
    }
    listen(document.getElementById('mg-start'),'click',e=>{if(!e.isTrusted||sim.started||closed||sim.held)return;record('start');h.setReadout('RESTORATION ACTIVE · ACT ONLY WHEN READY · FILL EVERY TRACE TOGETHER','idle');draw();});
    listen(document.getElementById('mg-close'),'click',e=>{if(e.isTrusted&&record('close'))finish();});
    document.querySelectorAll('[data-grip]').forEach(b=>listen(b,'click',e=>{if(e.isTrusted&&mode==='simplified')record('grip',{tool:Number(b.dataset.tool),grip:Number(b.dataset.grip)});draw();}));
    listen(canvas,'contextmenu',e=>e.preventDefault());
    listen(canvas,'pointerdown',e=>{
      if(!e.isTrusted||closed||![0,2].includes(e.button))return;
      e.preventDefault();sync();const p=canvasPoint(e),i=pane(p);if(i<0)return;const point=local(p,i);
      if(mode==='simplified') {if(e.button===0)record('aim',{tool:i,point});}
      else {
        const pickup=[p[0]-w.tracks[i].rect[0],p[1]-w.tracks[i].rect[1]].map(v=>Math.round(v*1000)/1000);
        if(!sim.held&&distance(pickup,sim.tools[i].point)<=w.pickup_radius) {if(record('down',{tool:i,point:pickup,button:e.button}))canvas.setPointerCapture(e.pointerId);}
      }
      draw();
    });
    listen(canvas,'pointermove',e=>{if(e.isTrusted&&mode==='full'&&sim.held&&record('move',{tool:sim.held[0],point:local(canvasPoint(e),sim.held[0])}))draw();});
    function release(e,kind) {if(!e.isTrusted||mode!=='full'||!sim.held||closed)return;const i=sim.held[0];if(kind==='up'&&e.button!==sim.held[1])return;record(kind,{tool:i,point:local(canvasPoint(e),i)});if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);draw();}
    listen(canvas,'pointerup',e=>release(e,'up'));listen(canvas,'pointercancel',e=>release(e,'cancel'));
    listen(canvas,'lostpointercapture',e=>release(e,'cancel'));
    function animate() {sync();draw();if(sim.done||sim.failed)finish();if(!closed)frame=requestAnimationFrame(animate);}
    cleanup=()=>{closed=true;abort.abort();cancelAnimationFrame(frame);};draw();frame=requestAnimationFrame(animate);
  }
  G.GymAnythingRTMechanics=G.GymAnythingRTMechanics||{};
  G.GymAnythingRTMechanics.museum_of_lost_gestures_nonrealtime={rootSelector:'.mgv2',render};
})();
