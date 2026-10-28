(() => {
  'use strict';

  // A deliberate start launches one finite, task-local transition. The
  // transition exposes the donor's seeded heat cue and then settles at the
  // golden point. There is no idle animation and a settled food never burns
  // while the player is deciding where to serve it.
  const motionUrl = new URL('realtime_four_motion.js', document.currentScript.src).href;
  const TRANSITION_MS = 1200;
  let model, animationFrame = 0;
  const clean = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  const wallNow = () => performance.now();

  function heat(food, time) {
    return time + food.heat_amplitude * RealtimeFourMotion.integral(food.heat_seed, time, food.heat_span_ms);
  }

  function transitionRatio(start) {
    if (start.ready) return 1;
    return Math.max(0, Math.min(1, (wallNow() - start.startedWall) / TRANSITION_MS));
  }

  function virtualCookTime(food, start) {
    return food.target_ms * transitionRatio(start);
  }

  function cookProgress(food, start) {
    if (!start) return 0;
    if (start.ready) return food.target_ms;
    const virtualTime = virtualCookTime(food, start);
    const raw = heat(food, virtualTime) - heat(food, 0);
    return Math.max(0, Math.min(food.target_ms, raw));
  }

  function finishTransitionIfReady(start) {
    if (!start.ready && transitionRatio(start) >= 1) start.ready = true;
    return start.ready;
  }

  function record(kind, food, extra = {}) {
    const event = {
      sequence: model.events.length + 1,
      kind,
      food_id: food.id,
      // This is an action-order clock, not wall time. Delays between native
      // actions therefore do not age a food or close the start window.
      t_ms: model.actionClock,
      input_source: model.interaction,
      ...extra,
    };
    model.actionClock += 1;
    model.events.push(event);
    return event;
  }

  async function finish(reason = '') {
    if (model.terminal) return;
    model.terminal = true;
    if (animationFrame) cancelAnimationFrame(animationFrame);
    animationFrame = 0;
    model.helpers.setReadout(reason ? `FAIL · ${reason}` : 'VERIFYING DINNER RUSH…', reason ? 'error' : 'pending');
    try {
      const response = await fetch('/result', {method: 'POST', headers: {'content-type': 'application/json'},
        body: JSON.stringify({mechanic_id: model.state.mechanic_id, task_id: model.state.task_id,
          challenge_id: model.state.challenge_id, interaction_mode: model.interaction,
          events: model.events, completed: !reason, final_t_ms: model.actionClock})});
      const result = await response.json();
      model.helpers.setReadout(result.passed ? 'PASS · ALL FOODS SERVED' : `FAIL · ${reason || 'ATTEMPT ENDED'}`,
        result.passed ? 'passed' : 'error');
    } catch (error) {
      model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`, 'error');
    }
  }

  function renderFood(food) {
    const node = document.querySelector(`[data-food-id="${food.id}"]`);
    if (!node) return false;
    const start = model.starts[food.id];
    const served = model.served.has(food.id);
    const progress = served ? food.target_ms : cookProgress(food, start);
    const ready = Boolean(start && (start.ready || finishTransitionIfReady(start)));
    node.dataset.cookState = served ? 'served' : !start ? 'raw' : ready ? 'ready' : 'warming';
    const fraction = Math.max(0, Math.min(1, progress / (food.target_ms + food.tolerance_ms)));
    node.querySelector('.rt-grill-progress i').style.width = `${fraction * 100}%`;
    const heatTime = start ? virtualCookTime(food, start) : 0;
    node.querySelector('.rt-grill-heat').textContent = served ? 'SERVED' :
      `HEAT ${(1 + food.heat_amplitude * RealtimeFourMotion.motion(food.heat_seed, heatTime, food.heat_span_ms)).toFixed(2)}×`;
    return Boolean(start && !start.ready);
  }

  function animateTransitions() {
    if (!model || model.terminal) return;
    let active = false;
    for (const food of model.state.foods) active = renderFood(food) || active;
    if (active) animationFrame = requestAnimationFrame(animateTransitions);
    else animationFrame = 0;
  }

  function scheduleTransitions() {
    if (!animationFrame) animationFrame = requestAnimationFrame(animateTransitions);
  }

  function refreshTransitions() {
    if (!model || model.terminal) return;
    for (const food of model.state.foods) renderFood(food);
    scheduleTransitions();
  }

  function transfer(food, destination, details) {
    if (model.terminal) return;
    refreshTransitions();
    const started = model.starts[food.id];
    if (destination === 'grill' && !started) {
      const event = record('start', food, details);
      model.starts[food.id] = {eventTime: event.t_ms, startedWall: wallNow(), ready: false};
      document.querySelector(`[data-zone="${destination}"]`).append(document.querySelector(`[data-food-id="${food.id}"]`));
      renderFood(food);
      scheduleTransitions();
      model.selected = null;
      return;
    }
    if (destination !== 'tray' || !started || model.served.has(food.id)) return;

    finishTransitionIfReady(started);
    const cookedMs = Math.round(cookProgress(food, started));
    record('serve', food, {...details, cook_ms: cookedMs, ready: started.ready});
    if (!started.ready || Math.abs(cookedMs - food.target_ms) > food.tolerance_ms) {
      finish(`${food.kind.toUpperCase()} SERVED OUTSIDE GOLDEN WINDOW`);
      return;
    }
    model.served.add(food.id);
    document.querySelector(`[data-zone="${destination}"]`).append(document.querySelector(`[data-food-id="${food.id}"]`));
    model.selected = null;
    renderFood(food);
    if (model.served.size === model.state.foods.length) finish();
  }

  async function render(state, helpers) {
    await import(motionUrl);
    if (animationFrame) cancelAnimationFrame(animationFrame);
    animationFrame = 0;
    document.body.dataset.mechanic = 'grillmaster';
    model = {state, helpers, interaction: state.control_condition?.interaction || 'full',
      starts: {}, served: new Set(), events: [], actionClock: 0, terminal: false, drag: null, selected: null};
    window.parallelGrillmasterNonrealtimeModel = model;
    const foodHTML = food => `<div class="grill-food" data-food-id="${food.id}" data-cook-state="raw"><span class="food-art food-art-${food.kind}"><i></i><b></b></span><span class="food-name">${food.kind}</span><div class="rt-grill-progress"><i></i><b style="left:${100 * (food.target_ms - food.tolerance_ms) / (food.target_ms + food.tolerance_ms)}%"></b></div><small class="rt-grill-heat">HEAT 1.00×</small></div>`;
    helpers.app.innerHTML = `<section class="interaction-captcha grill-captcha rt-grill" data-food-count="${state.foods.length}" data-interaction="${model.interaction}">
      <header class="interaction-head grill-head"><p>VARIABLE FIRE / ONE ATTEMPT</p><h1>Parallel Grillmaster V2</h1></header>
      <div class="rt-grill-rules">${clean(state.prompt)}<br>${model.interaction === 'full' ? 'Drag food from RAW ORDER to LIVE FIRE, then to SERVING TRAY.' : 'Click a food, then its destination zone.'} Each start triggers one finite cook transition; a settled food remains ready while you decide.</div>
      <section class="grill-stage"><div class="grill-zone grill-prep" data-zone="prep"><span class="zone-label">RAW ORDER</span>${state.foods.map(foodHTML).join('')}</div>
      <div class="grill-zone grill-fire" data-zone="grill"><span class="zone-label">LIVE FIRE</span></div><div class="grill-zone grill-tray" data-zone="tray"><span class="zone-label">SERVING TRAY</span></div></section>
      <footer class="interaction-foot"><div class="readout">Watch the seeded heat response. Serve after the bar reaches its golden marker.</div></footer></section>`;
    for (const food of state.foods) {
      const node = document.querySelector(`[data-food-id="${food.id}"]`);
      node.addEventListener('pointerdown', event => {
        if (model.terminal || model.interaction !== 'full' || event.button !== 0 || model.served.has(food.id)) return;
        event.preventDefault();
        node.setPointerCapture(event.pointerId);
        model.drag = {food, point: [event.clientX, event.clientY], pointer: event.pointerId};
        node.classList.add('is-dragging');
      });
      node.addEventListener('pointermove', event => {
        if (model.drag?.food !== food) return;
        node.style.setProperty('--grill-drag-x', `${event.clientX - model.drag.point[0]}px`);
        node.style.setProperty('--grill-drag-y', `${event.clientY - model.drag.point[1]}px`);
      });
      node.addEventListener('pointerup', event => {
        if (model.drag?.food !== food) return;
        const start = model.drag.point;
        model.drag = null;
        node.classList.remove('is-dragging');
        node.style.removeProperty('--grill-drag-x');
        node.style.removeProperty('--grill-drag-y');
        node.releasePointerCapture(event.pointerId);
        const zone = [...document.querySelectorAll('[data-zone]')].find(z => {
          const rect = z.getBoundingClientRect();
          return event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
        });
        if (zone) transfer(food, zone.dataset.zone, {start_point: start, end_point: [event.clientX, event.clientY]});
      });
      const cancelDrag = () => {
        if (model.drag?.food !== food) return;
        model.drag = null;
        node.classList.remove('is-dragging');
        node.style.removeProperty('--grill-drag-x');
        node.style.removeProperty('--grill-drag-y');
      };
      node.addEventListener('pointercancel', cancelDrag);
      node.addEventListener('lostpointercapture', cancelDrag);
      node.addEventListener('click', event => {
        if (model.interaction === 'simplified' && !model.terminal) {
          event.stopPropagation();
          model.selected = food;
        }
      });
    }
    for (const zone of document.querySelectorAll('[data-zone]')) zone.addEventListener('click', event => {
      if (model.interaction === 'simplified' && model.selected) transfer(model.selected, zone.dataset.zone, {point: [event.clientX, event.clientY]});
    });
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.parallel_grillmaster_nonrealtime = {rootSelector: '.rt-grill', render};
})();
