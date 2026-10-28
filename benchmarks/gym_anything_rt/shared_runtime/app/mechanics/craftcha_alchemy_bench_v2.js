(() => {
  'use strict';
  let model, raf;
  const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  function noise(seed, index) {
    let v = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    v = Math.imul(v ^ (v >>> 16), 0x85ebca6b) >>> 0;
    v = Math.imul(v ^ (v >>> 13), 0xc2b2ae35) >>> 0;
    return ((v ^ (v >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function position(lot, ms) {
    const phase = Math.max(0, ms) / lot.span_ms, n = Math.floor(phase), f = phase - n;
    const s = f * f * (3 - 2 * f);
    return lot.center.map((v, i) => v + lot.amplitude[i] *
      (noise(lot.motion_seed + i * 7919, n) * (1 - s) + noise(lot.motion_seed + i * 7919, n + 1) * s));
  }
  const now = () => model.status === 'running' ? Math.round(performance.now() - model.startedAt) : model.t_ms;
  const surface = kind => ({full:{pick:'pointer_down', drop:'pointer_up'}, simplified:{pick:'select_click', drop:'place_click'}})[model.mode][kind];
  function record(kind, extra = {}) {
    model.events.push({sequence:model.events.length + 1, kind, t_ms:model.t_ms, ...extra});
  }
  function point(event) {
    const r = model.canvas.getBoundingClientRect();
    return [Math.round((event.clientX - r.x) / r.width * 880 * 100) / 100,
      Math.round((event.clientY - r.y) / r.height * 360 * 100) / 100];
  }
  function hit(p, exclude = null) {
    return [...model.items.values()].find(item => item.id !== exclude &&
      Math.hypot(...position(model.state.lots[item.lot], model.t_ms).map((v, i) => v - p[i])) <= model.state.parameters.radius)?.id ?? null;
  }
  function payload() {
    return {mechanic_id:model.state.mechanic_id, revision:model.state.revision, task_id:model.state.task_id,
      challenge_id:model.state.challenge_id, interaction_mode:model.mode, events:model.events,
      final_t_ms:model.t_ms, final_inventory:[...model.items.values()].sort((a,b)=>a.id.localeCompare(b.id)), completed:model.status === 'won'};
  }
  function retainFailure() {
    sessionStorage.setItem(model.storageKey, model.reason);
    sessionStorage.setItem(model.episodeFailureKey, model.reason);
  }
  async function submit(reason = '') {
    if (model.submitting || model.submitted) return;
    model.t_ms = now();
    if (reason || model.status !== 'won') {
      model.status = 'failed'; model.reason = reason || 'Heart not crafted';
      record('failure', {reason:model.reason, input_surface:'terminal'});
      retainFailure();
    } else record('submit', {input_surface:'certify_button'});
    model.submitting = true; draw(); update();
    const current = model;
    try {
      const response = await fetch('/result', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload())});
      const grade = await response.json();
      if (model !== current) return;
      model.submitted = true; model.submitting = false;
      if (grade.passed) {
        model.status = 'passed'; model.helpers.setReadout('PASS · STORMGLASS HEART CERTIFIED', 'passed');
      } else {
        model.status = 'failed'; model.reason ||= grade.feedback || 'Certification failed';
        retainFailure();
        model.helpers.setReadout(`FAIL · ${model.reason}`, 'error');
      }
      update(); draw();
    } catch (error) {
      model.submitting = false;
      model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`, 'error');
    }
  }
  function sync() {
    if (model.status !== 'running') return;
    model.t_ms = now();
    if (model.t_ms > model.state.play_time_ms) { submit('Run allowance exhausted'); return; }
    const expired = [...model.items.values()].find(i => model.state.materials[i.id].hot &&
      model.t_ms - i.born_ms > model.state.parameters.hot_lifetime_ms);
    if (expired) submit(`${model.state.materials[expired.id].name} crystallized`);
  }
  function pick(p) {
    sync();
    if (model.status !== 'running' || model.held) return;
    const selected = hit(p);
    record(selected ? 'pick' : 'probe', {point:p, material_id:selected, input_surface:surface('pick')});
    if (selected) { model.held = selected; model.pointer = p; }
    draw(); update();
  }
  function drop(p) {
    sync();
    if (model.status !== 'running' || !model.held) return;
    const target = hit(p, model.held);
    const recipe = model.state.recipes.find(r => r.inputs.includes(model.held) && r.inputs.includes(target));
    record('drop', {point:p, target_id:target, output_id:recipe?.output ?? null, input_surface:surface('drop')});
    if (!target || !recipe) { submit(!target ? 'Spill — release missed the moving circle' : 'Wrong pair — material lineage destroyed'); return; }
    if ([model.held,target].some(id=>model.state.materials[id].hot && model.t_ms-model.items.get(id).born_ms<model.state.formation_ms)) {
      submit('Premature merge shattered a forming blend'); return;
    }
    const lot = model.items.get(target).lot;
    model.items.delete(model.held); model.items.delete(target);
    model.items.set(recipe.output, {id:recipe.output, lot, born_ms:model.t_ms});
    model.held = null;
    if (model.items.size === 1 && recipe.output === model.state.goal) model.status = 'won';
    draw(); update();
  }
  function update() {
    const root = model.root;
    root.dataset.status = model.status;
    document.querySelector('#stormglass-start').disabled = model.status !== 'ready';
    document.querySelector('#stormglass-certify').disabled = model.submitting || model.submitted || model.status === 'failed';
    document.querySelector('#stormglass-remaining').textContent = `${model.items.size} reagents`;
    for (const node of root.querySelectorAll('[data-recipe]')) {
      const r = model.state.recipes[Number(node.dataset.recipe)];
      node.classList.toggle('sg-available', r.inputs.every(id => model.items.has(id) && (!model.state.materials[id].hot || model.t_ms-model.items.get(id).born_ms>=model.state.formation_ms)));
      node.classList.toggle('sg-made', model.events.some(e => e.output_id === r.output));
    }
    if (model.status === 'ready') model.helpers.setReadout('Study the formula. Open the storm when ready.', 'idle');
    else if (model.status === 'running') model.helpers.setReadout(model.held ? 'REAGENT IN HAND · TARGET STILL MOVES' : 'LIVE STORM · FOLLOW THE REAGENTS', 'pending');
    else if (model.status === 'won') model.helpers.setReadout('HEART COMPLETE · CERTIFY BELOW', 'passed');
    else if (model.status === 'failed') model.helpers.setReadout(`FAIL · ${model.reason}`, 'error');
  }
  function drawBody(ctx, item, p, held = false) {
    const meta = model.state.materials[item.id], radius = model.state.parameters.radius;
    ctx.save(); ctx.translate(...p);
    const gradient = ctx.createRadialGradient(-radius*.3, -radius*.3, 1, 0, 0, radius);
    gradient.addColorStop(0, '#fcf7df'); gradient.addColorStop(.2, meta.color); gradient.addColorStop(1, '#263a48');
    ctx.fillStyle = gradient; ctx.strokeStyle = held ? '#fff9d7' : meta.color; ctx.lineWidth = held ? 3 : 2;
    ctx.beginPath(); ctx.arc(0, 0, radius, 0, 2*Math.PI); ctx.fill(); ctx.stroke();
    ctx.fillStyle = '#142333'; ctx.font = 'bold 25px Georgia'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(meta.symbol, 0, 0);
    if (meta.hot) {
      const formation = Math.min(1,(model.t_ms-item.born_ms)/model.state.formation_ms);
      ctx.strokeStyle = '#9cd9ff'; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(0,0,radius-5,-Math.PI/2,-Math.PI/2+formation*2*Math.PI); ctx.stroke();
      const fraction = Math.max(0, 1 - (model.t_ms-item.born_ms)/model.state.parameters.hot_lifetime_ms);
      ctx.strokeStyle = fraction < .25 ? '#ff8d80' : '#fff1b1'; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(0, 0, radius + 6, -Math.PI/2, -Math.PI/2 + fraction*2*Math.PI); ctx.stroke();
    }
    ctx.fillStyle = '#eceddc'; ctx.font = '12px Arial'; ctx.textBaseline = 'top'; ctx.fillText(meta.name, 0, radius + 10);
    if (meta.hot && model.t_ms-item.born_ms<model.state.formation_ms) {
      ctx.fillStyle='#b0dcff';ctx.font='bold 10px Arial';ctx.fillText('FORMING',0,radius+24);
    }
    ctx.restore();
  }
  function draw() {
    if (!model) return;
    const ctx = model.canvas.getContext('2d');
    ctx.clearRect(0, 0, 880, 360);
    const bg = ctx.createLinearGradient(0,0,0,360); bg.addColorStop(0,'#142838'); bg.addColorStop(1,'#0b192b');
    ctx.fillStyle = bg; ctx.fillRect(0,0,880,360);
    for (const lot of model.state.lots) {
      ctx.strokeStyle = '#294353'; ctx.lineWidth = 1;
      ctx.strokeRect(lot.center[0]-84, lot.center[1]-72, 168, 146);
      ctx.strokeStyle = '#203b49'; ctx.beginPath(); ctx.ellipse(...lot.center, 62, 32, 0, 0, Math.PI*2); ctx.stroke();
    }
    for (const item of model.items.values()) {
      if (item.id === model.held) continue;
      const lot = model.state.lots[item.lot], p = position(lot, model.t_ms);
      if (model.status === 'running') {
        ctx.strokeStyle = '#a7c5c955'; ctx.lineWidth = 3; ctx.beginPath();
        for (let back = model.state.trail_ms; back >= 0; back -= 100) {
          const q = position(lot, Math.max(0, model.t_ms-back)); if (back === model.state.trail_ms) ctx.moveTo(...q); else ctx.lineTo(...q);
        } ctx.stroke();
        ctx.strokeStyle = '#afd3d270'; ctx.lineWidth = 1.5; ctx.setLineDash([3,4]); ctx.beginPath(); ctx.moveTo(...p);
        for (let ahead = 100; ahead <= model.state.forecast_ms; ahead += 100) ctx.lineTo(...position(lot, model.t_ms+ahead));
        ctx.stroke(); ctx.setLineDash([]);
        const q = position(lot, model.t_ms+model.state.forecast_ms);
        ctx.strokeStyle = '#b4e4dd'; ctx.beginPath(); ctx.arc(...q, 4, 0, Math.PI*2); ctx.stroke();
      }
      drawBody(ctx,item,p);
    }
    if (model.held) drawBody(ctx,model.items.get(model.held),model.pointer,true);
    if (model.status === 'failed' || model.status === 'passed' || model.status === 'won') {
      ctx.fillStyle = '#10202bdf'; ctx.fillRect(120,116,640,126);
      ctx.strokeStyle = model.status === 'failed' ? '#ff8a83' : '#a9ead0'; ctx.lineWidth = 2; ctx.strokeRect(120,116,640,126);
      ctx.fillStyle = ctx.strokeStyle; ctx.font = 'bold 36px Georgia'; ctx.textAlign = 'center';
      ctx.fillText(model.status === 'failed' ? 'FAIL · BATCH LOST' : model.status === 'passed' ? 'PASS · HEART CERTIFIED' : 'STORMGLASS HEART',440,166);
      ctx.font = '16px Arial'; ctx.fillText(model.status === 'failed' ? model.reason : 'The recipe lineage is complete.',440,203);
    }
  }
  function animate() { sync(); draw(); update(); raf = requestAnimationFrame(animate); }
  function badge(meta) { return `<span class="sg-badge" style="--reagent:${esc(meta.color)}" title="${esc(meta.name)}">${esc(meta.symbol)}</span>`; }
  function render(state, helpers) {
    cancelAnimationFrame(raf);
    document.body.dataset.mechanic = 'stormglass-alchemy';
    const mode = state.control_condition.interaction;
    helpers.app.innerHTML = `<section class="stormglass-bench" data-status="ready" data-interaction="${mode}">
      <header class="sg-head"><div><small>CRAFTCHA / STORMGLASS FOUNDRY</small><h1>Alchemy Bench V2</h1><p>Turn drifting matter into a living heart.</p></div><aside><b>DIFFICULTY ${state.control_condition.difficulty}</b><span>${mode === 'full' ? 'DIRECT DRAG' : 'TWO CLICK TRANSFER'}</span></aside></header>
      <div class="sg-rules">${mode === 'full' ? 'Drag a reagent into its moving partner.' : 'Click a reagent, then click inside its moving partner.'} Follow the formula. Missed, wrong or premature merges end the episode.</div>
      <main class="sg-main"><div class="sg-world"><canvas id="stormglass-canvas" width="880" height="360"></canvas><div class="sg-legend"><b>✧ STORM TRACKS</b><span>Solid wake = last 0.8 s · dotted path = next 2.5 s</span><span>Blue ring fills in 5 s; use blends when full. Gold ring empties in ${state.parameters.hot_lifetime_ms/1000} s.<br>Holding a reagent keeps every other reagent moving.</span></div></div>
      <aside class="sg-formula"><header><small>MATERIAL LINEAGE</small><h2>Formula for a heart</h2></header>${state.recipes.map((r,i)=>`<div class="sg-recipe" data-recipe="${i}">${badge(state.materials[r.inputs[0]])}<em>+</em>${badge(state.materials[r.inputs[1]])}<em>→</em>${badge(state.materials[r.output])}<span>${esc(state.materials[r.output].name)}</span></div>`).join('')}<p>Any available pair may be merged.<br>New blend inherits the target's well.</p></aside></main>
      <footer class="sg-foot"><button id="stormglass-start">OPEN THE STORM</button><div><div class="readout"></div><span id="stormglass-remaining"></span></div><button id="stormglass-certify">CERTIFY HEART</button></footer>
    </section>`;
    model = {state, helpers, mode, root:document.querySelector('.stormglass-bench'), canvas:document.querySelector('#stormglass-canvas'),
      status:'ready', t_ms:0, startedAt:0, items:new Map(state.initial.map(i=>[i.id,{...i}])), events:[], held:null,
      pointer:[0,0], submitting:false, submitted:false, reason:'', storageKey:`stormglass-failed:${state.challenge_id}`,
      // /result may generate a new challenge after a loss. It is still the
      // same episode, identified by the task and the runtime's task token.
      episodeFailureKey:`stormglass-episode-failed:${JSON.stringify([state.task_id, new URLSearchParams(window.location.search).get('task') || ''])}`};
    // Exposed for disclosed read-only construction planning, never a task input.
    model.snapshot = () => ({status:model.status, t_ms:now(), held:model.held,
      items:[...model.items.values()].map(i=>({...i, point:position(state.lots[i.lot],now())})),
      canvas: (()=>{const r=model.canvas.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};})()});
    window.craftchaStormglassModel = model;
    const oldFailure = sessionStorage.getItem(model.episodeFailureKey) || sessionStorage.getItem(model.storageKey);
    if (oldFailure) { model.status='failed'; model.reason=oldFailure; retainFailure(); }
    document.querySelector('#stormglass-start').addEventListener('click',()=>{
      if (model.status !== 'ready') return;
      model.status='running'; model.startedAt=performance.now(); model.t_ms=0;
      record('start',{input_surface:'start_button'}); update(); draw();
    });
    document.querySelector('#stormglass-certify').addEventListener('click',()=>submit());
    model.canvas.addEventListener('pointerdown',e=>{
      if (mode !== 'full' || e.button !== 0) return;
      e.preventDefault(); pick(point(e));
      if (model.held) model.canvas.setPointerCapture(e.pointerId);
    });
    model.canvas.addEventListener('pointermove',e=>{ if (model.held) {model.pointer=point(e);draw();} });
    model.canvas.addEventListener('pointerup',e=>{
      if (mode !== 'full' || e.button !== 0 || !model.held) return;
      const p=point(e);
      if (p[0]<0 || p[0]>880 || p[1]<0 || p[1]>360) submit('Spill — reagent left the bench'); else drop(p);
      if (model.canvas.hasPointerCapture(e.pointerId)) model.canvas.releasePointerCapture(e.pointerId);
    });
    model.canvas.addEventListener('pointercancel',()=>{if(model.held) submit('Spill — transfer interrupted');});
    model.canvas.addEventListener('click',e=>{if(mode==='simplified' && e.button===0) model.held ? drop(point(e)) : pick(point(e));});
    update(); draw(); raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics ||= {};
  window.GymAnythingRTMechanics.craftcha_alchemy_bench_v2 = {rootSelector:'.stormglass-bench',render};
})();
