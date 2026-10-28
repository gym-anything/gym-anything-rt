(() => {
  'use strict';
  const motionUrl = new URL('realtime_four_motion.js', document.currentScript.src).href;
  let model, animationFrame = 0;
  const clean = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  const now = () => Math.round(performance.now() - model.startedAt);
  function heat(food, time) {
    return time + food.heat_amplitude * RealtimeFourMotion.integral(food.heat_seed, time, food.heat_span_ms);
  }
  function progress(food, time) {
    const started = model.starts[food.id];
    return started === undefined ? 0 : heat(food, time) - heat(food, started);
  }
  function record(kind, food, time, extra = {}) {
    model.events.push({sequence:model.events.length + 1, kind, food_id:food.id, t_ms:time,
      input_source:model.interaction, ...extra});
  }
  async function finish(reason = '') {
    if (model.terminal) return;
    model.terminal = true;
    model.helpers.setReadout(reason ? `FAIL · ${reason}` : 'VERIFYING DINNER RUSH…', reason ? 'error' : 'pending');
    try {
      const response = await fetch('/result', {method:'POST', headers:{'content-type':'application/json'},
        body:JSON.stringify({mechanic_id:model.state.mechanic_id, task_id:model.state.task_id,
          challenge_id:model.state.challenge_id, interaction_mode:model.interaction,
          events:model.events, completed:!reason, final_t_ms:now()})});
      const result = await response.json();
      model.helpers.setReadout(result.passed ? 'PASS · ALL FOODS SERVED' : `FAIL · ${reason || 'ATTEMPT ENDED'}`, result.passed ? 'passed' : 'error');
    } catch (error) { model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`, 'error'); }
  }
  function advance() {
    if (!model || model.terminal) return;
    const time = now();
    const starts = Object.values(model.starts);
    if (starts.length && starts.length < model.state.parallel_count && time - Math.min(...starts) > model.state.parallel_window_ms) {
      finish('CONCURRENT START WINDOW MISSED'); return;
    }
    for (const food of model.state.foods) {
      const node = document.querySelector(`[data-food-id="${food.id}"]`);
      const p = progress(food, time), started = model.starts[food.id] !== undefined;
      const served = model.served.has(food.id);
      node.dataset.cookState = served ? 'served' : !started ? 'raw' : p < food.target_ms - food.tolerance_ms ? 'warming' : p <= food.target_ms + food.tolerance_ms ? 'ready' : 'burnt';
      const fraction = Math.max(0, Math.min(1, p / (food.target_ms + food.tolerance_ms)));
      node.querySelector('.rt-grill-progress i').style.width = `${fraction * 100}%`;
      node.querySelector('.rt-grill-heat').textContent = served ? 'SERVED' : `HEAT ${(1 + food.heat_amplitude * RealtimeFourMotion.motion(food.heat_seed, time, food.heat_span_ms)).toFixed(2)}×`;
      if (started && !served && p > food.target_ms + food.tolerance_ms) { finish(`${food.kind.toUpperCase()} BURNT`); return; }
    }
  }
  function animate() { advance(); animationFrame = requestAnimationFrame(animate); }
  function transfer(food, destination, details) {
    if (model.terminal) return;
    advance();
    if (model.terminal) return;
    const time = now(), started = model.starts[food.id] !== undefined;
    if (destination === 'grill' && !started) {
      record('start', food, time, details); model.starts[food.id] = time;
    } else if (destination === 'tray' && started && !model.served.has(food.id)) {
      record('serve', food, time, details);
      const p = progress(food, time);
      if (Math.abs(p - food.target_ms) > food.tolerance_ms) { finish(`${food.kind.toUpperCase()} SERVED OUTSIDE GOLDEN WINDOW`); return; }
      model.served.add(food.id);
    } else return;
    document.querySelector(`[data-zone="${destination}"]`).append(document.querySelector(`[data-food-id="${food.id}"]`));
    model.selected = null;
    advance();
    if (model.served.size === model.state.foods.length) finish();
  }
  async function render(state, helpers) {
    await import(motionUrl); cancelAnimationFrame(animationFrame);
    document.body.dataset.mechanic = 'grillmaster';
    model = {state, helpers, interaction:state.control_condition?.interaction || 'full', starts:{}, served:new Set(),
      events:[], startedAt:performance.now(), terminal:false, drag:null, selected:null};
    window.parallelGrillmasterV2Model = model;
    const foodHTML = food => `<div class="grill-food" data-food-id="${food.id}" data-cook-state="raw"><span class="food-art food-art-${food.kind}"><i></i><b></b></span><span class="food-name">${food.kind}</span><div class="rt-grill-progress"><i></i><b style="left:${100*(food.target_ms-food.tolerance_ms)/(food.target_ms+food.tolerance_ms)}%"></b></div><small class="rt-grill-heat"></small></div>`;
    helpers.app.innerHTML = `<section class="interaction-captcha grill-captcha rt-grill" data-food-count="${state.foods.length}" data-interaction="${model.interaction}">
      <header class="interaction-head grill-head"><p>VARIABLE FIRE / ONE ATTEMPT</p><h1>Parallel Grillmaster V2</h1></header>
      <div class="rt-grill-rules">${clean(state.prompt)}<br>${model.interaction === 'full' ? 'Drag food from RAW ORDER to LIVE FIRE, then to SERVING TRAY.' : 'Click a food, then its destination zone.'} Cooking continues while food is held.</div>
      <section class="grill-stage"><div class="grill-zone grill-prep" data-zone="prep"><span class="zone-label">RAW ORDER</span>${state.foods.map(foodHTML).join('')}</div>
      <div class="grill-zone grill-fire" data-zone="grill"><span class="zone-label">LIVE FIRE</span></div><div class="grill-zone grill-tray" data-zone="tray"><span class="zone-label">SERVING TRAY</span></div></section>
      <footer class="interaction-foot"><div class="readout">Watch browning and the changing heat. Serve inside the golden end of each bar.</div></footer></section>`;
    for (const food of state.foods) {
      const node = document.querySelector(`[data-food-id="${food.id}"]`);
      node.addEventListener('pointerdown', event => {
        if (model.terminal || model.interaction !== 'full' || event.button !== 0 || model.served.has(food.id)) return;
        event.preventDefault(); node.setPointerCapture(event.pointerId);
        model.drag = {food, point:[event.clientX, event.clientY], pointer:event.pointerId}; node.classList.add('is-dragging');
      });
      node.addEventListener('pointermove', event => {
        if (model.drag?.food !== food) return;
        node.style.setProperty('--grill-drag-x', `${event.clientX-model.drag.point[0]}px`);
        node.style.setProperty('--grill-drag-y', `${event.clientY-model.drag.point[1]}px`);
      });
      node.addEventListener('pointerup', event => {
        if (model.drag?.food !== food) return;
        const start = model.drag.point; model.drag = null;
        node.classList.remove('is-dragging'); node.style.removeProperty('--grill-drag-x'); node.style.removeProperty('--grill-drag-y');
        node.releasePointerCapture(event.pointerId);
        const zone = [...document.querySelectorAll('[data-zone]')].find(z => { const r=z.getBoundingClientRect(); return event.clientX>=r.left && event.clientX<=r.right && event.clientY>=r.top && event.clientY<=r.bottom; });
        if (zone) transfer(food, zone.dataset.zone, {start_point:start, end_point:[event.clientX,event.clientY]});
      });
      const cancelDrag = () => {
        if (model.drag?.food !== food) return;
        model.drag = null; node.classList.remove('is-dragging');
        node.style.removeProperty('--grill-drag-x'); node.style.removeProperty('--grill-drag-y');
      };
      node.addEventListener('pointercancel', cancelDrag);
      node.addEventListener('lostpointercapture', cancelDrag);
      node.addEventListener('click', event => { if (model.interaction === 'simplified' && !model.terminal) { event.stopPropagation(); model.selected = food; } });
    }
    for (const zone of document.querySelectorAll('[data-zone]')) zone.addEventListener('click', event => {
      if (model.interaction === 'simplified' && model.selected) transfer(model.selected, zone.dataset.zone, {point:[event.clientX,event.clientY]});
    });
    animationFrame = requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.parallel_grillmaster_v2 = {rootSelector:'.rt-grill', render};
})();
