(() => {
  'use strict';
  const ID = 'apothecary_dead_reckoning_v3';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const esc = x => String(x).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  const rounded = a => a.map(x => Math.round(x * 10000) / 10000);
  const courseMark = ingredient => ['→', '↓', '←', '↑'][ingredient.angle_deg / 90];
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function motion(seed, ms, span) {
    const u = Math.max(0, ms) / span, n = Math.floor(u), f = u - n;
    return noise(seed, n) + (noise(seed, n + 1) - noise(seed, n)) * f * f * (3 - 2 * f);
  }
  const center = (item, ms) => item.center.map((x, i) => x + item.sway * motion(item.seed + i * 7919, ms, item.span_ms));
  function targetVelocity(item, ms) {
    const u = Math.max(0, ms) / item.span_ms, n = Math.floor(u), f = u - n;
    return [0, 1].map(i => item.sway * (noise(item.seed + i * 7919, n + 1) - noise(item.seed + i * 7919, n)) * 6 * f * (1 - f) * 1000 / item.span_ms);
  }
  function flow(w, point, ms) {
    const p = w.parameters;
    const value = [0, 1].map(i => p.current_speed * motion(w.flow_seed + i * 7919, ms, p.current_span_ms));
    for (const v of w.vortices) {
      const dx = point[0] - v.center[0], dy = point[1] - v.center[1], length = Math.hypot(dx, dy);
      const gain = v.strength * v.spin * Math.exp(-(length ** 2) / v.radius ** 2) * (.7 + .3 * motion(v.seed, ms, p.current_span_ms));
      value[0] -= gain * dy / Math.max(30, length); value[1] += gain * dx / Math.max(30, length);
    }
    return value;
  }
  class Physics {
    constructor(world) {
      this.world = world; this.tick = 0; this.position = [...world.origin]; this.velocity = [0, 0];
      this.ingredient = 0; this.grind = this.stir = this.water = 0;
      this.active = false; this.progress = 0; this.charge = 0; this.failure = '';
    }
    get done() { return this.progress === this.world.effects.length; }
    advance(targetTick) {
      if (!this.active) return;
      const w = this.world, p = w.parameters, m = w.mechanics, dt = m.tick_ms / 1000;
      while (this.tick < targetTick && !this.failure && !this.done) {
        this.tick++; const ms = this.tick * m.tick_ms;
        const angle = (w.ingredients[this.ingredient].angle_deg + 90 * this.grind) * Math.PI / 180;
        const current = flow(w, this.position, ms), dx = w.origin[0] - this.position[0], dy = w.origin[1] - this.position[1], distance = Math.hypot(dx, dy);
        const desired = [Math.cos(angle), Math.sin(angle)].map((q, i) => m.drive_speed * this.stir * q + current[i] + m.water_speed * this.water * (i === 0 ? dx : dy) / Math.max(40, distance));
        for (let i = 0; i < 2; i++) { this.velocity[i] += (desired[i] - this.velocity[i]) * dt / p.inertia_seconds; this.position[i] += this.velocity[i] * dt; }
        const r = m.flask_radius;
        if (this.position.some((x, i) => x < r || x > w.stage[i === 0 ? 'width' : 'height'] - r)) this.failure = 'The flask struck the atlas rim.';
        for (const bone of w.bones) if (dist(this.position, center(bone, ms)) <= r + bone.radius) { this.failure = 'Bone contact spoiled the brew.'; break; }
        if (this.failure) break;
        const target = w.effects[this.progress];
        const inside = dist(this.position, center(target, ms)) + r <= target.radius;
        const slow = dist(this.velocity, targetVelocity(target, ms)) <= p.relative_speed_limit;
        this.charge = inside && slow ? Math.min(p.dwell_ms, this.charge + m.tick_ms) : Math.max(0, this.charge - m.tick_ms * m.charge_leak);
        if (this.charge >= p.dwell_ms) { this.progress++; this.charge = 0; }
        if (ms >= m.max_time_ms && !this.done) this.failure = 'The brew exhausted its active time.';
      }
    }
    snapshot() {
      return {tick:this.tick, position:[...this.position], velocity:[...this.velocity], ingredient:this.ingredient,
        grind:this.grind, stir:this.stir, water:this.water, active:this.active, progress:this.progress,
        charge:this.charge, failure:this.failure, done:this.done};
    }
  }
  window.ApothecaryLivingAtlas = {Physics, noise, motion, center, targetVelocity, flow};
  let model = null, frame = 0;
  function sync() {
    if (!model || model.terminal) return;
    if (model.physics.active) model.physics.advance(Math.floor((performance.now() - model.startedAt) / 20 + 1e-7));
    if (model.physics.failure || model.physics.done) finish();
  }
  function record(kind, details = {}) {
    model.events.push({sequence:model.events.length + 1, tick:model.physics.tick, kind,
      input_source:kind === 'begin' || kind === 'submit' ? 'common_button' : model.interaction === 'full' ? 'direct_drag' : 'proxy_click', ...details});
  }
  function change(kind, value, gesture = {}) {
    sync(); if (model.terminal) return;
    record(kind, {value, ...gesture}); model.physics[kind] = value;
    // A mortar sample reveals the herb's course without lighting the atlas.
    // A propulsion preview also reveals it; never discard a fact already seen.
    if (kind === 'ingredient' || (kind === 'stir' && value > 0)) model.sampled.add(model.physics.ingredient);
    update();
  }
  function payload() {
    const s = model.physics;
    return {mechanic_id:ID, task_id:model.state.task_id, challenge_id:model.state.challenge_id,
      interaction_mode:model.interaction, events:model.events, final_tick:s.tick,
      position:rounded(s.position), velocity:rounded(s.velocity), progress:s.progress,
      completed:s.done && !s.failure, failure:s.failure};
  }
  async function finish() {
    if (model.terminal) return;
    model.terminal = true;
    const s = model.physics, current = model;
    document.querySelector('.apoth2-verdict').hidden = false;
    document.querySelector('.apoth2-verdict strong').textContent = s.failure ? 'BREW LOST' : 'BREW COMPLETE';
    document.querySelector('.apoth2-verdict span').textContent = s.failure || 'All seals absorbed.';
    current.helpers.setReadout(s.failure ? 'FAIL · ' + s.failure : 'VERIFYING BREW', s.failure ? 'error' : 'pending');
    try {
      const response = await fetch('/result', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload())});
      const result = await response.json();
      if (model !== current) return;
      current.decision = result;
      document.querySelector('.apoth2-verdict strong').textContent = result.passed ? 'PASS' : 'FAIL';
      document.querySelector('.apoth2-verdict').dataset.status = result.passed ? 'pass' : 'fail';
      current.helpers.setReadout(result.passed ? 'PASS · LIVING ATLAS BREWED' : 'FAIL · ATTEMPT ENDED', result.passed ? 'passed' : 'error');
    } catch (error) { current.helpers.setReadout('VERIFIER ERROR · ' + error.message, 'error'); }
  }
  function relative(event, node) {
    const r = node.getBoundingClientRect();
    return [(event.clientX - r.left) / r.width, (event.clientY - r.top) / r.height];
  }
  function arrow(c, x, y, vx, vy, color, scale = 1) {
    const length = Math.hypot(vx, vy) * scale;
    if (length < 1) return;
    c.save(); c.translate(x, y); c.rotate(Math.atan2(vy, vx)); c.strokeStyle = color; c.fillStyle = color; c.lineWidth = 1.8;
    c.beginPath(); c.moveTo(0, 0); c.lineTo(length, 0); c.stroke();
    c.beginPath(); c.moveTo(length, 0); c.lineTo(length - 5, -3); c.lineTo(length - 5, 3); c.closePath(); c.fill(); c.restore();
  }
  function path(c, points, color, width = 2) {
    c.beginPath(); points.forEach((p, i) => i ? c.lineTo(...p) : c.moveTo(...p)); c.strokeStyle = color; c.lineWidth = width; c.stroke();
  }
  function draw() {
    if (!model) return;
    const canvas = document.querySelector('#apoth2-map'), c = canvas.getContext('2d'), w = model.state, s = model.physics, ms = s.tick * 20;
    const bg = c.createLinearGradient(0, 0, 840, 460); bg.addColorStop(0, '#ead9aa'); bg.addColorStop(.55, '#d4bd86'); bg.addColorStop(1, '#ae976d'); c.fillStyle = bg; c.fillRect(0, 0, 840, 460);
    c.strokeStyle = '#76623b22'; c.lineWidth = 1;
    for (let x = 0; x < 840; x += 40) { c.beginPath(); c.moveTo(x, 0); c.lineTo(x, 460); c.stroke(); }
    for (let y = 0; y < 460; y += 40) { c.beginPath(); c.moveTo(0, y); c.lineTo(840, y); c.stroke(); }
    for (let y = 40; y < 460; y += 70) for (let x = 35; x < 840; x += 80) { const v = flow(w, [x, y], ms); arrow(c, x, y, ...v, '#367b7988', 1.1); }
    c.strokeStyle = '#624d32'; c.lineWidth = 2; c.beginPath(); c.arc(...w.origin, 18, 0, Math.PI * 2); c.stroke();
    c.fillStyle = '#624d32'; c.font = '12px Georgia'; c.textAlign = 'center'; c.fillText('WATER ORIGIN', w.origin[0], w.origin[1] + 34);
    for (const [i, target] of w.effects.entries()) {
      const p = center(target, ms), v = targetVelocity(target, ms), current = i === s.progress, done = i < s.progress;
      const trail = Array.from({length:9}, (_, j) => center(target, Math.max(0, ms - 800 + j * 100)));
      path(c, trail, target.color + '99');
      c.beginPath(); c.arc(...p, target.radius, 0, Math.PI * 2); c.fillStyle = target.color + (done ? '38' : '16'); c.fill();
      c.strokeStyle = current ? '#314e43' : target.color; c.lineWidth = current ? 3 : 1.5; c.setLineDash(current || done ? [] : [5, 5]); c.stroke(); c.setLineDash([]);
      if (current) { c.beginPath(); c.arc(...p, target.radius + 6, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * s.charge / w.parameters.dwell_ms); c.strokeStyle = '#277b55'; c.lineWidth = 5; c.stroke(); }
      c.fillStyle = target.color; c.font = 'bold 27px Georgia'; c.fillText(done ? '✓' : target.glyph === 'moth' ? '⋈' : target.glyph === 'eye' ? '◉' : '✣', p[0], p[1] + 9);
      c.fillStyle = '#493d2a'; c.font = 'bold 12px Georgia'; c.fillText(`${i + 1} · ${target.name}`, p[0], p[1] - target.radius - 12);
      arrow(c, p[0], p[1] + target.radius + 10, ...v, target.color, 1.4);
    }
    for (const bone of w.bones) {
      const p = center(bone, ms);
      path(c, Array.from({length:9}, (_, j) => center(bone, Math.max(0, ms - 800 + j * 100))), '#8a423577');
      c.beginPath(); c.arc(...p, bone.radius - 1, 0, Math.PI * 2); c.fillStyle = '#efe0ba'; c.strokeStyle = '#8a4235'; c.lineWidth = 2; c.fill(); c.stroke();
      c.save(); c.translate(...p); c.rotate(.7); c.strokeStyle = '#9b6650'; c.lineWidth = 5; c.beginPath(); c.moveTo(-12, 0); c.lineTo(12, 0); c.stroke();
      c.fillStyle = '#9b6650'; for (const x of [-12, 12]) for (const y of [-3, 3]) { c.beginPath(); c.arc(x, y, 4, 0, Math.PI * 2); c.fill(); } c.restore();
    }
    if (model.trail.at(-1)?.tick !== s.tick) { model.trail.push({tick:s.tick, p:[...s.position]}); model.trail = model.trail.filter(t => s.tick - t.tick <= 40); }
    path(c, model.trail.map(t => t.p), '#214b43bb', 3);
    // This local course preview holds today's observed flow constant. It is
    // not an oracle of tomorrow's current or an automatic interception tool.
    const preview = [[...s.position]], pos = [...s.position], vel = [...s.velocity], current = flow(w, pos, ms);
    const a = (w.ingredients[s.ingredient].angle_deg + 90 * s.grind) * Math.PI / 180;
    for (let j = 0; j < 40; j++) {
      const dx = w.origin[0] - pos[0], dy = w.origin[1] - pos[1], d = Math.hypot(dx, dy);
      for (let i = 0; i < 2; i++) { const desired = 68 * s.stir * (i ? Math.sin(a) : Math.cos(a)) + current[i] + 40 * s.water * (i ? dy : dx) / Math.max(40, d); vel[i] += (desired - vel[i]) * .05 / w.parameters.inertia_seconds; pos[i] += vel[i] * .05; }
      preview.push([...pos]);
    }
    c.setLineDash([6, 5]); path(c, preview, w.ingredients[s.ingredient].color, 2); c.setLineDash([]);
    c.beginPath(); c.arc(...s.position, 7, 0, Math.PI * 2); c.fillStyle = '#6ab09e'; c.strokeStyle = '#153e36'; c.lineWidth = 2; c.fill(); c.stroke();
    c.fillStyle = '#e2f6e6'; c.fillRect(s.position[0] - 2, s.position[1] - 5, 4, 4);
    arrow(c, ...s.position, ...s.velocity, '#173d33', .6);
    c.strokeStyle = '#73583b'; c.lineWidth = 2; c.strokeRect(0, 0, 840, 460);
    c.fillStyle = '#4e5b49'; c.font = '12px Georgia'; c.textAlign = 'left'; c.fillText('CURRENT →   TRAIL = LAST 0.8 s   DASHED = LOCAL 2 s COURSE', 16, 442);
  }
  function update() {
    if (!model) return;
    const s = model.physics, w = model.state;
    for (const kind of ['grind', 'stir', 'water']) {
      document.querySelector(`[data-track="${kind}"] i`).style.left = `${100 * s[kind]}%`;
      document.querySelector(`[data-value="${kind}"]`).textContent = `${Math.round(100 * s[kind])}%`;
    }
    for (const jar of document.querySelectorAll('[data-ingredient]')) {
      const index = +jar.dataset.ingredient, known = model.sampled.has(index);
      jar.classList.toggle('selected', index === s.ingredient);
      jar.querySelector('i').textContent = known ? courseMark(w.ingredients[index]) : '?';
      jar.querySelector('small').textContent = known ? 'whole course' : 'sample in mortar';
    }
    document.querySelector('.apoth2-mortar b').textContent = w.ingredients[s.ingredient].name;
    document.querySelector('#apoth2-begin').disabled = s.active || model.terminal;
    document.querySelector('#apoth2-status').textContent = `${s.progress}/${w.effects.length} seals · ${s.tick * .02|0} / 140 s`;
    const target = w.effects[Math.min(s.progress, w.effects.length - 1)], ms = s.tick * 20;
    document.querySelector('#apoth2-potency').textContent = `ALIGN ${Math.round(s.charge / w.parameters.dwell_ms * 100)}% · RELATIVE SPEED ${dist(s.velocity, targetVelocity(target, ms)).toFixed(0)} / ${w.parameters.relative_speed_limit}`;
    draw();
  }
  async function render(state, helpers) {
    cancelAnimationFrame(frame);
    document.body.dataset.mechanic = ID;
    model = {state, helpers, physics:new Physics(state), interaction:state.control_condition.interaction,
      events:[], terminal:false, startedAt:null, trail:[], drag:null, sampled:new Set()};
    window.apothecaryLivingAtlasModel = model;
    const s = model.physics, mode = model.interaction;
    helpers.app.innerHTML = `<section class="apoth2" data-interaction="${mode}">
      <header><div><small>THE LIVING ATLAS / DISPLACEMENT DISPENSARY</small><h1>Apothecary Dead Reckoning V3</h1></div><aside id="apoth2-status"></aside></header>
      <div class="apoth2-order">${state.effects.map((e, i) => `<span>${i + 1} · ${esc(e.name)}</span>`).join('<em>→</em>')}<b>Stay inside each seal at low relative speed to absorb it.</b></div>
      <main><div class="apoth2-map-frame"><canvas id="apoth2-map" width="840" height="460"></canvas><div id="apoth2-potency"></div></div>
      <aside class="apoth2-bench"><small>BOTANICAL COURSE · SAMPLE TO REVEAL</small><div class="apoth2-jars">${state.ingredients.map((e, i) => `<button data-ingredient="${i}" style="--herb:${e.color}"><i>?</i>${esc(e.name)}<small>sample in mortar</small></button>`).join('')}</div>
      <div class="apoth2-mortar"><span>◡</span><b>${esc(state.ingredients[0].name)}</b><small>${mode === 'full' ? 'Drop jars here. Drag each handle.' : 'Select a jar. Click each scale.'}</small></div>
      ${['grind','stir','water'].map(kind => `<label><span>${kind === 'grind' ? 'GRIND · course bend' : kind === 'stir' ? 'STIR · propulsion' : 'WATER · pull to origin'}</span><b data-value="${kind}"></b><div data-track="${kind}" class="apoth2-track"><i></i></div><small>${kind === 'grind' ? 'whole → fine' : kind === 'stir' ? 'rest → full' : 'closed → open'}</small></label>`).join('')}</aside></main>
      <footer><div class="readout">Sample jars in the mortar; learned courses stay on their labels. Preview freely before LIGHT CAULDRON. Grind bends clockwise 90°. Bone or rim contact ends the brew.</div><button id="apoth2-begin">LIGHT CAULDRON</button><button id="apoth2-submit">SEAL BREW</button></footer>
      <div class="apoth2-verdict" hidden><strong></strong><span></span></div></section>`;
    for (const jar of document.querySelectorAll('[data-ingredient]')) {
      const index = +jar.dataset.ingredient;
      jar.addEventListener('click', () => { if (mode === 'simplified') change('ingredient', index); });
      jar.addEventListener('pointerdown', e => {
        if (mode !== 'full' || e.button !== 0 || model.terminal) return;
        model.drag = {kind:'ingredient', index, start:relative(e, jar), pointer:e.pointerId};
        jar.setPointerCapture(e.pointerId); jar.classList.add('held'); e.preventDefault();
      });
      jar.addEventListener('pointerup', e => {
        const d = model.drag; if (!d || d.kind !== 'ingredient' || d.index !== index) return;
        const end = relative(e, document.querySelector('.apoth2-mortar'));
        model.drag = null; jar.classList.remove('held'); jar.releasePointerCapture(e.pointerId);
        if (end.every(x => x >= 0 && x <= 1)) change('ingredient', index, {start:d.start, end});
      });
      const cancel = () => { if (model.drag?.index === index) model.drag = null; jar.classList.remove('held'); };
      jar.addEventListener('pointercancel', cancel); jar.addEventListener('lostpointercapture', cancel);
    }
    for (const track of document.querySelectorAll('[data-track]')) {
      const kind = track.dataset.track;
      track.addEventListener('click', e => { if (mode === 'simplified') { const p = relative(e, track); change(kind, clamp(p[0], 0, 1)); } });
      track.addEventListener('pointerdown', e => {
        if (mode !== 'full' || e.button !== 0 || model.terminal) return;
        const start = relative(e, track);
        if (Math.abs(start[0] - s[kind]) > .085 || start[1] < -.1 || start[1] > 1.1) return;
        model.drag = {kind, start, pointer:e.pointerId}; track.setPointerCapture(e.pointerId); e.preventDefault();
      });
      track.addEventListener('pointerup', e => {
        const d = model.drag; if (!d || d.kind !== kind) return;
        const end = relative(e, track); model.drag = null; track.releasePointerCapture(e.pointerId);
        if (end[1] >= 0 && end[1] <= 1) { end[0] = clamp(end[0], 0, 1); change(kind, end[0], {start:d.start, end}); }
      });
      const cancel = () => { if (model.drag?.kind === kind) model.drag = null; };
      track.addEventListener('pointercancel', cancel); track.addEventListener('lostpointercapture', cancel);
    }
    document.querySelector('#apoth2-begin').addEventListener('click', () => {
      if (s.active || model.terminal) return;
      record('begin'); s.active = true; model.startedAt = performance.now(); update();
    });
    document.querySelector('#apoth2-submit').addEventListener('click', () => {
      sync(); if (model.terminal) return;
      record('submit'); s.failure = 'Submitted an incomplete brew.'; finish();
    });
    const current = model;
    function animate() { if (model !== current) return; sync(); update(); frame = requestAnimationFrame(animate); }
    update(); frame = requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics[ID] = {rootSelector:'.apoth2', render};
})();
