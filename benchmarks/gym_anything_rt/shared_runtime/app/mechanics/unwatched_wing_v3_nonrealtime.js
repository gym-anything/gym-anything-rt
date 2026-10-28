(() => {
  'use strict';
  // Independent browser implementation of the optical rule and collision model.
  const noise = (seed, n) => {
    let x = (seed ^ Math.imul(n + 1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  };
  const motion = (seed, ms, span) => {
    const n = Math.floor(ms / span), f = ms / span - n, a = noise(seed, n), b = noise(seed, n + 1);
    return a + (b - a) * f * f * (3 - 2 * f);
  };
  const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const coordinate = x => Math.round(x * 1000) / 1000;
  const phaseY = object => coordinate(object.baseline + object.amplitude * Math.sin(object.phase_code * Math.PI / 180000));
  const freeVertical = object => (phaseY({...object,phase_code:(object.phase_code + object.rate_code * 2) % 360000})-object.y)/.02;
  function circleRect(x, y, radius, left, top, right, bottom) {
    if (bottom < top) return false;
    const dx = x - clamp(x, left, right), dy = y - clamp(y, top, bottom);
    return dx * dx + dy * dy < radius * radius - 1e-9;
  }
  class Transit {
    constructor(state) {
      this.world = state.world;
      this.gates = structuredClone(this.world.gates);
      this.cargo = structuredClone(this.world.cargo);
      this.ms = 0; this.started = false; this.active = false;
      this.goal = [...this.world.initial_lens]; this.lens = [...this.goal];
      this.pinned = null; this.failed = ''; this.impact = null; this.passed = false;
      this.photo_id = null; this.photo_until_ms = 0;
      this.inspected = new Set();
      for (const g of this.gates) Object.assign(g, {y:phaseY(g), age_ms:0, vy:0});
      for (const c of this.cargo) Object.assign(c, {delivered:false, vx:0, vy:0, age_ms:0});
      this.traces = {};
    }
    observed() {
      if (!this.active) return null;
      const objects = this.gates.map(g => [g.id, [g.x + 26, g.y]])
        .concat(this.cargo.filter(c => !c.delivered).map(c => [c.id, [c.x, c.y]]));
      const candidates = objects.map(([id, p]) => [distance(this.lens, p), id])
        .filter(([d]) => d <= this.world.focus_radius)
        .sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1]));
      return candidates[0]?.[1] || null;
    }
    releaseVelocity(object) {
      return 'width' in object ? freeVertical(object) : object.speed_code/20;
    }
    releaseVerticalVelocity(courier) {
      return freeVertical(courier);
    }
    rates() {
      if(this.ms % this.world.rate_update_ms)return;
      const step=(obj,prefix)=>{
        let value=obj[prefix+'_code']+obj[prefix+'_direction']*obj[prefix+'_step'];
        const low=obj[prefix+'_min'],high=obj[prefix+'_max'];
        if(value<=low){value=2*low-value;obj[prefix+'_direction']=1;}
        else if(value>=high){value=2*high-value;obj[prefix+'_direction']=-1;}
        obj[prefix+'_code']=value;
      };
      this.gates.forEach(g=>step(g,'rate'));
      this.cargo.forEach(c=>{step(c,'rate');step(c,'speed');});
    }

    motionCue(object) {
      // A tangent vector at a common one-second scale, not a future path.
      // Restraint hides actual motion, so show the immediate free velocity.
      const restrained = object.id === this.pinned || object.id === this.photo_id;
      const vx = 'width' in object ? 0 : (restrained ? this.releaseVelocity(object) : object.vx);
      const vy = restrained ? ('width' in object ? this.releaseVelocity(object) : this.releaseVerticalVelocity(object)) : object.vy;
      const anchor = 'width' in object ? [object.x + 49, object.y] : [object.x + 17, object.y];
      return {anchor, tip:[anchor[0] + vx, anchor[1] + vy], vx, vy, restrained, scale_seconds:1};
    }
    advance(end) {
      if (!this.started) return;
      const step = this.world.tick_ms, dt = step / 1000;
      while (this.ms + step <= end && !this.failed && !this.passed) {
        this.ms += step;
        this.rates();
        if (this.photo_id !== null && this.ms >= this.photo_until_ms) this.photo_id = null;
        const dx = this.goal[0] - this.lens[0], dy = this.goal[1] - this.lens[1], d = Math.hypot(dx, dy);
        const fraction = d ? Math.min(1, this.world.aim_speed * dt / d) : 0;
        this.lens = [coordinate(this.lens[0] + dx * fraction), coordinate(this.lens[1] + dy * fraction)];
        // The fixed brass plate is visible through the frosted survey screen.
        // Reading it reveals the running shutter; it does not alter collision,
        // pinning, rates or time, and the revealed view remains available.
        if (this.active) for (const g of this.gates) {
          if (distance(this.lens, [g.x + 26, g.baseline]) <= this.world.focus_radius)
            this.inspected.add(g.id);
        }
        this.pinned = this.observed();
        for (const g of this.gates) {
          const before = g.y;
          if (g.id !== this.pinned && g.id !== this.photo_id) {
            g.age_ms += step;
            g.phase_code=(g.phase_code+g.rate_code*2)%360000;
            g.phase=g.phase_code*Math.PI/180000;
            g.y=phaseY(g);
          }
          g.vy = (g.y - before) / dt;
          const trace = this.traces[g.id] ||= [];
          trace.push({t:this.ms, y:g.y});
          while (trace.length && trace[0].t < this.ms - this.world.trace_ms) trace.shift();
        }
        for (const c of this.cargo) {
          const beforeY = c.y;
          c.vx = c.vy = 0;
          if (c.delivered) continue;
          if (c.id !== this.pinned && c.id !== this.photo_id) {
            c.vx = c.speed_code/20;
            c.x = coordinate(c.x + c.vx * dt);
            c.age_ms += step;
            c.phase_code=(c.phase_code+c.rate_code*2)%360000;
            c.phase=c.phase_code*Math.PI/180000;
            c.y=phaseY(c);
            c.vy = (c.y - beforeY) / dt;
          }
          const trace = this.traces[c.id] ||= [];
          trace.push({t:this.ms, x:c.x, y:c.y});
          while (trace.length && trace[0].t < this.ms - this.world.trace_ms) trace.shift();
          for (const g of this.gates) {
            if (g.lane !== c.lane) continue;
            const left = g.x - g.width / 2, right = g.x + g.width / 2;
            if (circleRect(c.x, c.y, c.radius, left, g.baseline - 104, right, g.y - g.half)
              || circleRect(c.x, c.y, c.radius, left, g.y + g.half, right, g.baseline + 104)) {
              this.failed = 'A courier touched a closed shutter.';
              this.impact = {courier:c.id, shutter:g.id, t_ms:this.ms, x:c.x, y:c.y, aperture_y:g.y};
              return;
            }
          }
          if (c.x - c.radius >= this.world.dock_x) c.delivered = true;
        }
        this.passed = this.cargo.every(c => c.delivered);
        if (this.ms >= this.world.max_active_ms && !this.passed)
          this.failed = 'The night transfer ended before every courier arrived.';
      }
    }
    snapshot() {
      return {t_ms:this.ms, started:this.started, lamp_active:this.active,
        inspected:[...this.inspected].sort(),
        lens:this.lens, goal:this.goal, pinned:this.pinned, failed:this.failed, passed:this.passed,
        impact:this.impact, photo_id:this.photo_id, photo_until_ms:this.photo_until_ms,
        gates:this.gates.map(g => ({id:g.id, y:g.y, phase:g.phase, phase_code:g.phase_code, rate_code:g.rate_code, rate_direction:g.rate_direction, age_ms:g.age_ms})),
        cargo:this.cargo.map(c => ({id:c.id, x:c.x, y:c.y, phase:c.phase, phase_code:c.phase_code, rate_code:c.rate_code, rate_direction:c.rate_direction, speed_code:c.speed_code, speed_direction:c.speed_direction, age_ms:c.age_ms, delivered:c.delivered}))};
    }
  }
  window.UnwatchedWingTransit = Transit;
  let model, frame = 0, keyHandler = null;
  const record = (kind, input_source, extra = {}) => {
    model.events.push({sequence:model.events.length + 1, kind, input_source, t_ms:model.currentMs, ...extra});
  };
  function actionAdvance() {
    if (!model || model.terminal || !model.sim.started) return;
    model.sim.advance(model.sim.ms + model.state.world.action_step_ms);
    model.currentMs = model.sim.ms;
    if (model.sim.failed || model.sim.passed) finish('terminal_auto');
  }
  function stagePoint(event) {
    const r = model.canvas.getBoundingClientRect(), w = model.state.world;
    return [Math.round(clamp((event.clientX - r.left) * w.width / r.width, 0, w.width) * 1000) / 1000,
      Math.round(clamp((event.clientY - r.top) * w.height / r.height, 0, w.height) * 1000) / 1000];
  }
  async function finish(source) {
    if (model.terminal) return;
    model.terminal = true;
    record('submit', source);
    const s = model.sim;
    const payload = {mechanic_id:model.state.mechanic_id, revision:model.state.revision,
      task_id:model.state.task_id, challenge_id:model.state.challenge_id,
      interaction_mode:model.mode, events:model.events,
      final_t_ms:model.events.at(-1).t_ms, final_state:s.snapshot(), completed:s.passed && !s.failed};
    model.payload = payload;
    document.querySelector('.uw2-transfer').dataset.verdict = s.failed || !s.passed ? 'fail' : 'checking';
    document.querySelector('#uw2-start').disabled = true;
    document.querySelector('#uw2-submit').disabled = true;
    const note = document.querySelector('#uw2-status');
    note.textContent = s.failed || (s.passed ? 'ARCHIVE ARRIVED · VERIFYING…' : 'INCOMPLETE TRANSFER');
    draw();
    try {
      const response = await fetch('/result', {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(payload)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const decision = await response.json();
      model.decision = decision;
      document.querySelector('.uw2-transfer').dataset.verdict = decision.passed ? 'pass' : 'fail';
      note.textContent = decision.passed ? 'PASS · THE COURIERS ARE HOME' : s.failed || 'FAIL · TRANSFER ENDED';
      model.helpers.setReadout(note.textContent, decision.passed ? 'passed' : 'error');
      draw();
    } catch (error) {
      document.querySelector('.uw2-transfer').dataset.verdict = 'error';
      note.textContent = `VERIFIER ERROR · ${error.message}`;
      draw();
    }
  }
  function start() {
    if (model.terminal || model.sim.started) return;
    model.currentMs = 0; model.sim.started = true;
    record('start', 'start_button');
    document.querySelector('#uw2-start').disabled = true;
    document.querySelector('#uw2-status').textContent = 'THE WING IS MOVING';
    draw();
  }
  function lamp(kind, event) {
    if (model.terminal || !model.sim.started) return;
    const s = model.sim;
    if (kind === 'lamp_up') { s.active = false; model.held = null; record(kind, 'lantern_drag'); }
    else {
      const point = stagePoint(event);
      s.active = true; s.goal = point;
      record(kind, model.mode === 'full' ? 'lantern_drag' : 'lantern_click', {point});
    }
    actionAdvance();
    draw();
  }
  function photo(clear = false) {
    if (model.terminal || !model.sim.started) return;
    const s = model.sim;
    if (clear) {
      if (s.photo_id === null) return;
      s.photo_id = null;
      record('photo_clear', model.mode === 'full' ? 'viewer_key' : 'viewer_button');
    } else {
      const id = s.observed();
      if (id === null) return;
      s.photo_id = id; s.photo_until_ms = s.ms + s.world.photo_lifetime_ms;
      record('photo', model.mode === 'full' ? 'camera_key' : 'camera_button', {object_id:id});
    }
    actionAdvance();
    draw();
  }
  function drawGlyph(c, x, y, size, type, color) {
    c.save(); c.translate(x, y); c.scale(size / 12, size / 12);
    c.strokeStyle = color; c.fillStyle = color; c.lineWidth = 1.6;
    if (type === 'moth') {
      for (const side of [-1, 1]) { c.beginPath(); c.ellipse(side * 5, -1, 6, 9, side * .4, 0, Math.PI * 2); c.fill(); }
      c.strokeStyle = '#101d26'; c.beginPath(); c.moveTo(0,-10); c.lineTo(0,10); c.stroke();
    } else {
      c.beginPath(); c.ellipse(-2,3,7,5,-.3,0,Math.PI*2); c.fill();
      c.beginPath(); c.moveTo(2,2); c.quadraticCurveTo(9,-6,4,-9); c.lineTo(10,-7); c.stroke();
    }
    c.restore();
  }
  function draw() {
    if (!model) return;
    const ctx = model.canvas.getContext('2d'), s = model.sim, w = s.world;
    const bg = ctx.createLinearGradient(0,0,0,500);
    bg.addColorStop(0,'#111a2d'); bg.addColorStop(1,'#0a1620');
    ctx.fillStyle = bg; ctx.fillRect(0,0,w.width,w.height);
    ctx.strokeStyle = '#ac986b28'; ctx.lineWidth = 1;
    for (let x=30; x<1100; x+=80) { ctx.strokeRect(x,18,60,464); ctx.beginPath(); ctx.arc(x+30,30,30,Math.PI,0); ctx.stroke(); }
    ctx.font = '12px ui-monospace, monospace'; ctx.textAlign = 'left';
    for (const [i,y] of w.lanes.entries()) {
      ctx.fillStyle = '#07111aaa'; ctx.fillRect(28,y-104,1048,208);
      ctx.strokeStyle = '#b8aa7a55'; ctx.strokeRect(28,y-104,1048,208);
      ctx.setLineDash([4,7]); ctx.strokeStyle = '#9fdbdd55'; ctx.beginPath(); ctx.moveTo(45,y); ctx.lineTo(1030,y); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = i ? '#e3b3ff' : '#93e8cf'; ctx.fillText(i ? 'HERON GALLERY' : 'MOTH GALLERY',42,y-80);
      const courier=s.cargo.find(c=>c.lane===i);
      ctx.setLineDash([2,9]);ctx.strokeStyle='#aacbd22a';
      for(const offset of [-courier.amplitude,courier.amplitude]) {
        ctx.beginPath();ctx.moveTo(45,y+offset);ctx.lineTo(1020,y+offset);ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.fillStyle = '#203b37'; ctx.fillRect(w.dock_x,y-82,44,164);
      ctx.strokeStyle = '#93e8cf'; ctx.lineWidth=2; ctx.strokeRect(w.dock_x,y-82,44,164);
      ctx.save(); ctx.translate(1058,y); ctx.rotate(-Math.PI/2); ctx.fillStyle='#c6e3c5';ctx.textAlign='center';ctx.fillText('ARCHIVE',0,0);ctx.restore();
    }
    for (const g of s.gates) {
      const pinned = s.pinned === g.id || s.photo_id === g.id;
      const top=g.baseline-104, bottom=g.baseline+104, a=g.y-g.half, b=g.y+g.half;
      if (!s.inspected.has(g.id)) {
        // Opaque survey glass conceals the aperture, eye, trail and rate cues.
        // Its full envelope is a warning, not additional collision geometry.
        ctx.fillStyle='#263544';ctx.fillRect(g.x-13,top,72,208);
        ctx.strokeStyle='#81909b';ctx.lineWidth=1;ctx.strokeRect(g.x-13,top,72,208);
        ctx.strokeStyle='#c3d7da22';
        for(let y=top+9;y<bottom;y+=13){ctx.beginPath();ctx.moveTo(g.x-12,y);ctx.lineTo(g.x+58,y-8);ctx.stroke();}
        ctx.fillStyle='#b9995c';ctx.fillRect(g.x+16,g.baseline-10,20,20);
        ctx.fillStyle='#efe5cc';ctx.font='10px ui-monospace,monospace';ctx.textAlign='center';
        const label=`${g.lane===0?'M':'H'}${Number(g.id.split('-')[2])+1}`;
        ctx.fillText(label,g.x+23,top+17);
        ctx.save();ctx.translate(g.x+26,g.baseline+58);ctx.rotate(-Math.PI/2);
        ctx.fillText('LANTERN SURVEY',0,0);ctx.restore();ctx.textAlign='left';
        continue;
      }
      ctx.strokeStyle='#bddbd22a';ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(g.x+49,g.baseline-g.amplitude);ctx.lineTo(g.x+49,g.baseline+g.amplitude);
      ctx.moveTo(g.x+46,g.baseline-g.amplitude);ctx.lineTo(g.x+52,g.baseline-g.amplitude);
      ctx.moveTo(g.x+46,g.baseline+g.amplitude);ctx.lineTo(g.x+52,g.baseline+g.amplitude);ctx.stroke();
      ctx.fillStyle=pinned?'#ccb675':'#66778a';
      if (a>top) ctx.fillRect(g.x-g.width/2,top,g.width,a-top);
      if (b<bottom) ctx.fillRect(g.x-g.width/2,b,g.width,bottom-b);
      ctx.strokeStyle=pinned?'#ffe2a1':'#9cdad6';ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(g.x-12,a);ctx.lineTo(g.x+12,a);ctx.moveTo(g.x-12,b);ctx.lineTo(g.x+12,b);ctx.stroke();
      // All visible trail samples come from the last 400 ms of actual motion.
      const trail=s.traces[g.id]||[];
      ctx.strokeStyle='#bfdad64d';ctx.lineWidth=2;ctx.beginPath();
      trail.forEach((p,i)=>{const x=g.x+26+24*(s.ms-p.t)/400;i?ctx.lineTo(x,p.y):ctx.moveTo(x,p.y);});ctx.stroke();
      ctx.strokeStyle=pinned?'#ffe1a3':'#b5c7d7';ctx.fillStyle=pinned?'#786344':'#26394e';ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(g.x+7,g.y);ctx.lineTo(g.x+13,g.y);ctx.stroke();
      ctx.beginPath();ctx.arc(g.x+26,g.y,13,0,Math.PI*2);ctx.fill();ctx.stroke();
      ctx.beginPath();ctx.ellipse(g.x+26,g.y,8,4,0,0,Math.PI*2);ctx.stroke();
      ctx.fillStyle=pinned?'#ffe3a5':'#c4d8e7';ctx.beginPath();ctx.arc(g.x+26,g.y,2,0,Math.PI*2);ctx.fill();
      drawMotionCue(ctx,s.motionCue(g),pinned?'#ffe2a0':'#b5c7d7');
    }
    for (const c of s.cargo) {
      const trail=s.traces[c.id]||[];
      ctx.strokeStyle=c.color+'88';ctx.lineWidth=2;ctx.beginPath();
      trail.forEach((p,i)=>{i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);});ctx.stroke();
      ctx.fillStyle='#132f35';ctx.strokeStyle=s.pinned===c.id||s.photo_id===c.id?'#ffe2a0':c.color;ctx.lineWidth=2;
      ctx.beginPath();ctx.arc(c.x,c.y,c.radius,0,Math.PI*2);ctx.fill();ctx.stroke();
      drawGlyph(ctx,c.x,c.y,9,c.glyph,c.color);
      if (!c.delivered) drawMotionCue(ctx,s.motionCue(c),s.pinned===c.id||s.photo_id===c.id?'#ffe2a0':c.color);
    }
    if(s.active) {
      ctx.strokeStyle='#ffe2a077';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(20,480);ctx.lineTo(...s.lens);ctx.stroke();
      ctx.fillStyle='#fff0b211';ctx.strokeStyle='#ffe2a0';ctx.lineWidth=2;ctx.beginPath();ctx.arc(...s.lens,w.focus_radius,0,Math.PI*2);ctx.fill();ctx.stroke();
      ctx.strokeStyle='#ffe2a050';ctx.beginPath();ctx.arc(...s.goal,6,0,Math.PI*2);ctx.stroke();
    }
    if (s.impact) {ctx.strokeStyle='#ff907d';ctx.lineWidth=3;ctx.beginPath();ctx.arc(s.impact.x,s.impact.y,23,0,Math.PI*2);ctx.stroke();}
    const verdict=document.querySelector('.uw2-transfer').dataset.verdict;
    if(verdict) {
      ctx.fillStyle='#08131ce8';ctx.fillRect(330,185,440,130);ctx.strokeStyle=verdict==='pass'?'#93e8cf':'#ecad93';ctx.strokeRect(330,185,440,130);
      ctx.fillStyle=verdict==='pass'?'#93e8cf':'#ffb2a0';ctx.font='48px Georgia, serif';ctx.textAlign='center';
      ctx.fillText(verdict==='pass'?'PASS':verdict==='checking'?'ARRIVED':verdict==='error'?'VERIFIER ERROR':'FAIL',550,244);
      ctx.font='15px ui-monospace, monospace';ctx.fillText(verdict==='pass'?'THE SLEEPING COLLECTION IS HOME':'THE TRANSFER HAS ENDED',550,280);
    }
    document.querySelector('#uw2-count').textContent=`${s.cargo.filter(c=>c.delivered).length}/${s.cargo.length} HOME`;
    document.querySelector('#uw2-lamp-state').textContent=s.active?(s.pinned?'ONE OBJECT PINNED':'LANTERN SEARCHING'):'LANTERN DARK';
    const image = document.querySelector('#uw2-image'), imageCtx = image.getContext('2d');
    imageCtx.fillStyle='#080e18';imageCtx.fillRect(0,0,100,50);
    if (s.photo_id) {
      const cargo=s.cargo.find(c=>c.id===s.photo_id), gate=s.gates.find(g=>g.id===s.photo_id);
      imageCtx.globalAlpha=Math.max(.2,(s.photo_until_ms-s.ms)/w.photo_lifetime_ms);
      if(cargo)drawGlyph(imageCtx,32,23,18,cargo.glyph,cargo.color);
      else if(gate){imageCtx.strokeStyle='#ffe1a3';imageCtx.lineWidth=3;imageCtx.strokeRect(17,12,28,25);imageCtx.beginPath();imageCtx.ellipse(31,24,8,4,0,0,Math.PI*2);imageCtx.stroke();}
      imageCtx.fillStyle='#c9ad76';imageCtx.fillRect(3,44,94*(s.photo_until_ms-s.ms)/w.photo_lifetime_ms,3);imageCtx.globalAlpha=1;
      imageCtx.fillStyle='#e5d6b1';imageCtx.font='12px ui-monospace,monospace';imageCtx.fillText(`${((s.photo_until_ms-s.ms)/1000).toFixed(1)}s`,57,27);
    } else {imageCtx.fillStyle='#c0b698';imageCtx.font='11px ui-monospace,monospace';imageCtx.fillText('NO IMAGE',18,29);}
    drawMeters();
  }
  function drawMeters() {
    const s=model.sim,w=s.world,p=model.state.parameters;
    const f=(x,n=3)=>Number(x).toFixed(n);
    const label=id=>id?.startsWith('iris-')?`${id.split('-')[1]==='0'?'M':'H'}${Number(id.split('-')[2])+1}`:id==='courier-0'?'MOTH':id==='courier-1'?'HERON':'—';
    const meter=document.querySelector('#uw2-meters');
    meter.querySelector('.uw2-lens-meter').textContent=`t ${model.currentMs.toString()} ms · step ${s.ms}\nL ${f(s.lens[0])}, ${f(s.lens[1])} → ${f(s.goal[0])}, ${f(s.goal[1])}\n${s.active?'ON':'DARK'} · pin ${label(s.pinned)} · photo ${label(s.photo_id)} until ${s.photo_id?s.photo_until_ms:'—'} ms`;
    for(const obj of [...s.cargo,...s.gates]) {
      const row=meter.querySelector(`[data-object="${obj.id}"]`);
      if ('width' in obj && !s.inspected.has(obj.id)) {
        row.textContent=`${label(obj.id)} · FROSTED · LANTERN SURVEY`;
        row.dataset.held='no';
        continue;
      }
      row.textContent=`${label(obj.id)} x${f(obj.x)} θ${f(obj.phase_code/1000)} ω${f(obj.rate_code/10,1)}${obj.rate_direction>0?'↑':'↓'}${'width' in obj?'':` v${f(obj.speed_code/20,2)}${obj.speed_direction>0?'↑':'↓'}`}${obj.delivered?' HOME':''}`;
      row.dataset.held=(obj.id===s.pinned||obj.id===s.photo_id)?'yes':'no';
    }
    const g=s.gates[0],c=s.cargo[0];
    meter.querySelector('.uw2-motion-scale').textContent=`Height = lane + swing × sin θ\nLanes ${w.lanes.join(', ')} · eye x = gate + 26\nGate swing ±${p.amplitude}; opening ±${p.aperture_half}; width 14\nCourier swing ±${p.cargo_amplitude}; radius 12\nSpin limits G ${f(g.rate_min/10,1)}…${f(g.rate_max/10,1)}, C ${f(c.rate_min/10,1)}…${f(c.rate_max/10,1)}°/s\nStep G ${f(g.rate_step/10,1)}, C ${f(c.rate_step/10,1)}°/s each 0.2 s; reflect at limits\nForward ${s.cargo.map(c=>`${label(c.id)} ${f(c.speed_min/20,2)}…${f(c.speed_max/20,2)} step${f(c.speed_step/20,2)}`).join('; ')}\nLantern r34; speed620 · archive x1030\nWorld 1100×500; tick20ms; photo ${w.photo_lifetime_ms}ms`;
  }
  function drawMotionCue(ctx,cue,color) {
    const length=Math.hypot(cue.vx,cue.vy);
    if(length<.05)return;
    const dx=cue.vx/length,dy=cue.vy/length,tip=cue.tip;
    ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(cue.restrained?[3,3]:[]);
    ctx.beginPath();ctx.moveTo(...cue.anchor);ctx.lineTo(...tip);ctx.stroke();ctx.setLineDash([]);
    ctx.beginPath();ctx.moveTo(tip[0]-dx*5-dy*4,tip[1]-dy*5+dx*4);ctx.lineTo(...tip);ctx.lineTo(tip[0]-dx*5+dy*4,tip[1]-dy*5-dx*4);ctx.stroke();
  }
  // Rendering may repaint continuously, but it never advances task state.
  function animate() { draw(); frame=requestAnimationFrame(animate); }
  async function render(state, helpers) {
    cancelAnimationFrame(frame);
    if(keyHandler)window.removeEventListener('keydown',keyHandler);
    document.body.dataset.mechanic='unwatched-wing-v3-nonrealtime';
    const mode=state.control_condition?.interaction||'full';
    helpers.app.innerHTML=`<section class="uw2-transfer" data-interaction="${mode}">
      <header class="uw2-head"><div><small>NIGHT MUSEUM / LANTERN TRANSIT</small><h1>The Unwatched Wing V3</h1></div><canvas id="uw2-image" width="100" height="50" aria-label="Observed photograph with visible fading lifetime"></canvas><aside><b id="uw2-count"></b><span id="uw2-lamp-state"></span></aside></header>
      <div class="uw2-rules">Bring every courier home. Aim the lantern at each brass survey plate to reveal the frosted shutter's opening and live dials permanently. Inspect before couriers arrive; the glass conceals a physical moving shutter.<br><span>Light pins one nearby eye or courier; one fading photo pins another. Unlit couriers advance and drift vertically during each fixed 400 ms action step after a deliberate lantern or photo control; waiting between controls leaves the wing stable. Trails: 0.4 s; arrows: one-second speed, dashed release drift. Rates step every 0.2 s and reflect, even while pinned.</span><br><span>${mode==='full'?'Hold and drag to aim; release for darkness. SPACE takes a photo; X closes it.':'Click to aim. PHOTO takes a picture; CLOSE releases it; DARK extinguishes the lamp.'} The lantern travels toward your aim. Shutter contact ends the attempt.</span></div>
      <div class="uw2-stage"><canvas id="uw2-world" width="1100" height="500" aria-label="Two-dimensional museum transit and moving shutters"></canvas><aside id="uw2-meters" aria-label="Current motion dials and lantern readings"><strong>MOTION DIALS · M=MOTH, H=HERON</strong><div class="uw2-lens-meter"></div>${[...state.world.cargo,...state.world.gates].map(o=>`<div class="uw2-object-meter" data-object="${o.id}"></div>`).join('')}<div class="uw2-motion-scale"></div></aside></div>
      <footer class="uw2-foot"><button id="uw2-start">BEGIN TRANSFER</button><div id="uw2-status" class="readout">BRING EVERY COURIER TO THE ARCHIVE</div>${mode==='simplified'?'<button id="uw2-photo">PHOTO</button><button id="uw2-clear">CLOSE</button><button id="uw2-off">DARK</button>':''}<button id="uw2-submit">CERTIFY</button></footer>
    </section>`;
    model={state,helpers,mode,sim:new Transit(state),currentMs:0,events:[],terminal:false,held:null,
      canvas:document.querySelector('#uw2-world')};
    window.unwatchedWingV3Model=model;
    document.querySelector('#uw2-start').addEventListener('click',start);
    document.querySelector('#uw2-submit').addEventListener('click',()=>finish('submit_button'));
    document.querySelector('#uw2-photo')?.addEventListener('click',()=>photo());
    document.querySelector('#uw2-clear')?.addEventListener('click',()=>photo(true));
    keyHandler=event=>{if(mode!=='full'||event.repeat||event.ctrlKey||event.metaKey||event.altKey)return;
      if(event.code==='Space'||event.code==='KeyX'){event.preventDefault();photo(event.code==='KeyX');}};
    window.addEventListener('keydown',keyHandler);
    document.querySelector('#uw2-off')?.addEventListener('click',()=>{
      if(model.terminal||!model.sim.started)return;
      model.sim.active=false;record('lamp_off','lamp_off_button');
      actionAdvance();
      draw();
    });
    const canvas=model.canvas;
    canvas.addEventListener('pointerdown',event=>{
      if(event.button!==0||model.terminal||!model.sim.started)return;
      event.preventDefault();
      if(mode==='full') {model.held=event.pointerId;canvas.setPointerCapture(event.pointerId);lamp('lamp_down',event);}
      else lamp('lamp_target',event);
    });
    canvas.addEventListener('pointermove',event=>{
      if(mode==='full'&&model.held===event.pointerId)lamp('lamp_move',event);
    });
    const release=event=>{
      if(mode!=='full'||model.held!==event.pointerId)return;
      lamp('lamp_up',event);
      if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);
    };
    canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);
    canvas.addEventListener('lostpointercapture',release);
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics ||= {};
  window.GymAnythingRTMechanics.unwatched_wing_v3_nonrealtime={rootSelector:'.uw2-transfer',render};
})();
