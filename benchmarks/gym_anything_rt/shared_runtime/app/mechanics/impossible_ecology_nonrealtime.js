(() => {
  "use strict";

  let model = null;

  const esc = (value) => String(value == null ? "" : value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const round = (value, digits = 6) => Math.round(value * (10 ** digits)) / (10 ** digits);
  const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

  function record(kind, details = {}) {
    const event = {sequence: model.events.length + 1, kind, ...details};
    model.events.push(event);
    return event;
  }

  function clearFresh() {
    const root = document.querySelector(".impossible-ecology-nonrealtime-captcha");
    if (!root || root.dataset.freshFailure !== "true") return;
    root.dataset.freshFailure = "false";
    document.querySelector(".eco-fail-stamp")?.remove();
    model.helpers.setReadout("FIELD LAB ACTIVE · CALIBRATE OR INTERVENE", "idle");
  }

  function initialOrganisms() {
    return Object.fromEntries(model.state.organisms.map((item) => [item.id, {
      id: item.id,
      label: item.label,
      color: item.color,
      radius: Number(item.radius),
      responses: {...item.responses},
      currentSeed: Number(item.current_seed),
      x: Number(item.initial_position[0]),
      y: Number(item.initial_position[1]),
      vx: 0,
      vy: 0,
      captured: false,
      trail: [],
    }]));
  }

  function resetWorld(recordEvent = true) {
    if (!model || model.submitting || model.terminal || model.active || model.calibrating) return;
    clearFresh();
    if (recordEvent) record("reset");
    model.organisms = initialOrganisms();
    model.tick = 0;
    model.active = false;
    model.pointerDown = false;
    model.completed = false;
    model.selectedField = null;
    model.lure = [model.state.arena.width / 2, model.state.arena.height / 2];
    model.resets += recordEvent ? 1 : 0;
    document.querySelector(".eco-complete")?.setAttribute("data-visible", "false");
    updateHUD();
    model.helpers.setReadout("ECOSYSTEM RESET · ALL ORGANISMS MOBILE", "idle");
  }

  function targetFor(id) {
    return model.targets.get(id);
  }

  function resolveObstacle(organism, next) {
    const obstacle = model.state.obstacle;
    const dx = next[0] - obstacle.center[0], dy = next[1] - obstacle.center[1];
    const size = Math.hypot(dx, dy);
    const minimum = Number(obstacle.radius) + organism.radius;
    if (size >= minimum) return next;
    const ux = size > 1e-9 ? dx / size : 1, uy = size > 1e-9 ? dy / size : 0;
    const inward = organism.vx * ux + organism.vy * uy;
    if (inward < 0) {
      organism.vx -= 1.55 * inward * ux;
      organism.vy -= 1.55 * inward * uy;
    }
    return [obstacle.center[0] + ux * minimum, obstacle.center[1] + uy * minimum];
  }

  function advancePhysics() {
    const controls = model.state.controls;
    const arena = model.state.arena;
    for (const organism of Object.values(model.organisms)) {
      if (organism.captured) continue;
      const current = ambientCurrent(organism.currentSeed, model.tick, controls);
      organism.vx += current[0]; organism.vy += current[1];
      if (model.active && model.selectedField) {
        const dx = model.lure[0] - organism.x, dy = model.lure[1] - organism.y;
        const size = Math.hypot(dx, dy);
        if (size > 1e-9) {
          const acceleration = Number(organism.responses[model.selectedField]);
          organism.vx += dx / size * acceleration;
          organism.vy += dy / size * acceleration;
        }
      }
      organism.vx *= Number(controls.damping);
      organism.vy *= Number(controls.damping);
      const speed = Math.hypot(organism.vx, organism.vy);
      if (speed > Number(controls.max_speed)) {
        organism.vx = organism.vx / speed * Number(controls.max_speed);
        organism.vy = organism.vy / speed * Number(controls.max_speed);
      }
      let next = resolveObstacle(organism, [organism.x + organism.vx, organism.y + organism.vy]);
      const low = Number(arena.margin) + organism.radius;
      const highX = Number(arena.width) - Number(arena.margin) - organism.radius;
      const highY = Number(arena.height) - Number(arena.margin) - organism.radius;
      if (next[0] < low || next[0] > highX) { next[0] = Math.max(low, Math.min(highX, next[0])); organism.vx *= -.35; }
      if (next[1] < low || next[1] > highY) { next[1] = Math.max(low, Math.min(highY, next[1])); organism.vy *= -.35; }
      organism.x = round(next[0]); organism.y = round(next[1]); organism.vx = round(organism.vx); organism.vy = round(organism.vy);
      organism.trail.push([organism.x, organism.y]);
      if (organism.trail.length > 26) organism.trail.shift();
      const target = targetFor(organism.id);
      const captureRadius = Number(target.radius) - organism.radius - Number(controls.capture_margin);
      if (distance([organism.x, organism.y], target.center) <= captureRadius && Math.hypot(organism.vx, organism.vy) <= Number(controls.capture_speed)) {
        organism.x = Number(target.center[0]); organism.y = Number(target.center[1]);
        organism.vx = 0; organism.vy = 0; organism.captured = true;
      }
    }
  }

  function ambientCurrent(seed, tick, controls) {
    const segment = Number(controls.current_segment_ticks);
    const index = Math.floor(tick / segment), fraction = (tick % segment) / segment;
    const direction = (k) => {
      let value = (seed ^ Math.imul(k + 1, 0x9e3779b1)) >>> 0;
      value = Math.imul(value ^ (value >>> 16), 0x85ebca6b) >>> 0;
      value = Math.imul(value ^ (value >>> 13), 0xc2b2ae35) >>> 0;
      value = (value ^ (value >>> 16)) >>> 0;
      return value / 4294967296 * Math.PI * 2;
    };
    const start = direction(index), finish = direction(index + 1), tau = Math.PI * 2;
    const delta = ((finish - start + Math.PI) % tau + tau) % tau - Math.PI;
    const blend = fraction ** 3 * (10 + fraction * (-15 + 6 * fraction));
    const angle = start + delta * blend, magnitude = Number(controls.current_acceleration);
    return [magnitude * Math.cos(angle), magnitude * Math.sin(angle)];
  }

  function snapshot() {
    return Object.values(model.organisms).sort((a, b) => a.id.localeCompare(b.id)).map((item) => ({
      id: item.id,
      position: [round(item.x, 3), round(item.y, 3)],
      velocity: [round(item.vx, 3), round(item.vy, 3)],
      captured: item.captured,
    }));
  }

  function physicsTick() {
    if (!model || model.submitting || model.terminal || model.completed) return;
    model.tick += 1;
    advancePhysics();
    record("physics_tick", {
      tick: model.tick,
      active: model.active,
      field: model.active ? model.selectedField : null,
      lure: model.lure.map((value) => round(value, 3)),
      organisms: snapshot(),
    });
    const captured = Object.values(model.organisms).filter((item) => item.captured).length;
    if (captured === Object.keys(model.organisms).length && !model.completed) {
      model.completed = true;
      model.active = false;
      model.pointerDown = false;
      record("complete", {tick: model.tick});
      document.querySelector(".eco-complete")?.setAttribute("data-visible", "true");
      model.helpers.setReadout(`ALL ${Object.keys(model.organisms).length} SANCTUARIES STABLE · READY TO CERTIFY`, "idle");
    }
    updateHUD();
  }

  function arenaPoint(event) {
    const box = model.canvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(model.state.arena.width, (event.clientX - box.left) / box.width * model.state.arena.width)),
      Math.max(0, Math.min(model.state.arena.height, (event.clientY - box.top) / box.height * model.state.arena.height)),
    ];
  }

  function coordinatePadPoint(event) {
    const box = model.coordinatePad.getBoundingClientRect();
    return [
      Math.max(0, Math.min(model.state.arena.width, (event.clientX - box.left) / box.width * model.state.arena.width)),
      Math.max(0, Math.min(model.state.arena.height, (event.clientY - box.top) / box.height * model.state.arena.height)),
    ];
  }

  function selectField(field) {
    if (!model || model.active || model.completed || model.submitting || model.terminal || model.calibrating || !model.state.fields.includes(field)) return;
    clearFresh();
    model.selectedField = field;
    model.fieldSelections += 1;
    record("field_select", {field, tick: model.tick});
    updateHUD();
    model.helpers.setReadout(model.interaction === "simplified" ? `${field} FIELD ARMED · HOLD AND MOVE ON THE COORDINATE PAD` : `${field} FIELD ARMED · HOLD THE POINTER IN THE ARENA`, "idle");
  }

  function pointerDown(event) {
    if (model?.interaction !== "full" || !model.selectedField || model.completed || model.submitting || model.terminal || model.calibrating) return;
    event.preventDefault();
    clearFresh();
    model.lure = arenaPoint(event);
    model.active = true;
    model.pointerDown = true;
    model.pointerDrags += 1;
    record("pointer_down", {tick: model.tick, field: model.selectedField, input_source: "arena_pointer", point: model.lure.map((value) => round(value, 3))});
    physicsTick();
    model.canvas.setPointerCapture?.(event.pointerId);
    model.helpers.setReadout(`${model.selectedField} FIELD LIVE · ALL MOBILE ORGANISMS RESPOND`, "pending");
  }

  function pointerMove(event) {
    if (!model || model.interaction !== "full") return;
    const point = arenaPoint(event);
    if (!model.pointerDown) { model.lure = point; return; }
    if (distance(point, model.lure) < Number(model.state.controls.pointer_sample_distance)) return;
    model.lure = point;
    record("pointer_move", {tick: model.tick, field: model.selectedField, input_source: "arena_pointer", point: model.lure.map((value) => round(value, 3))});
    physicsTick();
  }

  function pointerUp(event) {
    if (model?.interaction !== "full" || !model.pointerDown) return;
    model.lure = arenaPoint(event);
    record("pointer_up", {tick: model.tick, field: model.selectedField, input_source: "arena_pointer", point: model.lure.map((value) => round(value, 3))});
    model.pointerDown = false;
    model.active = false;
    physicsTick();
    model.helpers.setReadout("FIELD RELEASED · WORLD HOLDS UNTIL NEXT ACTION", "idle");
  }

  function coordinatePadDown(event) {
    if (!model || model.interaction !== "simplified" || !model.selectedField || model.completed || model.submitting || model.terminal || model.calibrating) return;
    event.preventDefault();
    clearFresh();
    model.lure = coordinatePadPoint(event);
    model.active = true;
    model.pointerDown = true;
    model.pointerDrags += 1;
    record("pointer_down", {tick: model.tick, field: model.selectedField, input_source: "coordinate_pad", point: model.lure.map((value) => round(value, 3))});
    physicsTick();
    event.currentTarget?.setPointerCapture?.(event.pointerId);
    updateCoordinatePad();
    model.helpers.setReadout(`${model.selectedField} FIELD LIVE · ALL MOBILE ORGANISMS RESPOND`, "pending");
  }

  function coordinatePadMove(event) {
    if (!model || model.interaction !== "simplified") return;
    const point = coordinatePadPoint(event);
    if (!model.pointerDown) { model.lure = point; updateCoordinatePad(); return; }
    if (distance(point, model.lure) < Number(model.state.controls.pointer_sample_distance)) return;
    model.lure = point;
    record("pointer_move", {tick: model.tick, field: model.selectedField, input_source: "coordinate_pad", point: model.lure.map((value) => round(value, 3))});
    physicsTick();
    updateCoordinatePad();
  }

  function coordinatePadUp(event) {
    if (!model || model.interaction !== "simplified" || !model.pointerDown) return;
    event.preventDefault();
    model.lure = coordinatePadPoint(event);
    record("pointer_up", {tick: model.tick, field: model.selectedField, input_source: "coordinate_pad", point: model.lure.map((value) => round(value, 3))});
    model.pointerDown = false;
    model.active = false;
    physicsTick();
    updateCoordinatePad();
    model.helpers.setReadout("FIELD RELEASED · WORLD HOLDS UNTIL NEXT ACTION", "idle");
  }

  function runCalibration() {
    if (!model || model.active || model.completed || model.submitting || model.terminal || model.calibrating) return;
    clearFresh();
    model.calibrationRuns += 1;
    model.calibrating = {started: performance.now()};
    record("calibration", {tick: model.tick, fields: [...model.state.fields]});
    document.querySelector(".eco-calibrate")?.setAttribute("disabled", "disabled");
    model.helpers.setReadout("CALIBRATION FILM RUNNING · FIELD IS STATIONARY", "pending");
  }

  function calibrationState(now) {
    if (!model.calibrating) return null;
    const elapsed = now - model.calibrating.started;
    const duration = Number(model.state.controls.calibration_field_ms);
    const index = Math.floor(elapsed / duration);
    if (index >= model.state.fields.length) {
      model.calibrating = null;
      document.querySelector(".eco-calibrate")?.removeAttribute("disabled");
      model.helpers.setReadout("CALIBRATION COMPLETE · FIELD IS STATIONARY", "idle");
      return null;
    }
    return {field: model.state.fields[index], progress: (elapsed % duration) / duration};
  }

  function updateHUD() {
    const captured = Object.values(model.organisms).filter((item) => item.captured).length;
    const root = document.querySelector(".impossible-ecology-nonrealtime-captcha");
    if (root) root.dataset.captured = String(captured);
    const count = document.getElementById("eco-capture-count");
    if (count) count.textContent = `${captured} / ${Object.keys(model.organisms).length}`;
    const tick = document.getElementById("eco-tick-count");
    if (tick) tick.textContent = String(model.tick).padStart(4, "0");
    document.querySelectorAll("[data-field]").forEach((button) => button.dataset.selected = button.dataset.field === model.selectedField ? "true" : "false");
    const ledger = document.getElementById("eco-organism-ledger");
    if (ledger) ledger.innerHTML = Object.values(model.organisms).map((item) => `<li data-captured="${item.captured}"><i style="--organism:${esc(item.color)}">${esc(item.label)}</i><span>${item.captured ? "SANCTUARY LOCKED" : "RESPONDING TO GLOBAL FIELD"}</span><b>${item.captured ? "STABLE" : "MOBILE"}</b></li>`).join("");
    updateCoordinatePad();
  }

  function updateCoordinatePad() {
    if (!model?.coordinatePad) return;
    model.coordinatePad.dataset.armed = String(Boolean(model.selectedField));
    model.coordinatePad.dataset.active = String(model.active);
    model.coordinatePad.style.setProperty("--eco-lure-x", `${model.lure[0] / model.state.arena.width * 100}%`);
    model.coordinatePad.style.setProperty("--eco-lure-y", `${model.lure[1] / model.state.arena.height * 100}%`);
  }

  function draw(now) {
    if (!model) return;
    const ctx = model.canvas.getContext("2d");
    const {width, height} = model.state.arena;
    const palette = model.state.palette;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = palette.paper; ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = palette.grid; ctx.lineWidth = 1; ctx.globalAlpha = .42;
    for (let x = 20; x < width; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke(); }
    for (let y = 15; y < height; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke(); }
    ctx.globalAlpha = 1;
    const obstacle = model.state.obstacle;
    ctx.beginPath(); ctx.arc(obstacle.center[0], obstacle.center[1], obstacle.radius, 0, Math.PI * 2); ctx.fillStyle = `${palette.danger}18`; ctx.fill(); ctx.setLineDash([8, 6]); ctx.strokeStyle = palette.danger; ctx.lineWidth = 2; ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = palette.danger; ctx.font = "800 9px ui-monospace"; ctx.textAlign = "center"; ctx.fillText("STERILE NURSERY / SOLID", obstacle.center[0], obstacle.center[1] + 3);
    for (const target of model.state.targets) {
      const organism = model.organisms[target.organism_id];
      ctx.beginPath(); ctx.arc(target.center[0], target.center[1], target.radius, 0, Math.PI * 2); ctx.fillStyle = `${target.color}12`; ctx.fill(); ctx.strokeStyle = target.color; ctx.lineWidth = organism.captured ? 5 : 2; ctx.setLineDash(organism.captured ? [] : [7, 6]); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = target.color; ctx.font = "900 12px ui-monospace"; ctx.fillText(`SANCTUARY ${target.label}`, target.center[0], target.center[1] + 4);
    }
    const calibration = calibrationState(now);
    for (const organism of Object.values(model.organisms)) {
      if (organism.trail.length > 1) { ctx.beginPath(); organism.trail.forEach((point, index) => index ? ctx.lineTo(point[0], point[1]) : ctx.moveTo(point[0], point[1])); ctx.strokeStyle = `${organism.color}66`; ctx.lineWidth = 2; ctx.stroke(); }
      if (calibration) {
        const dx = model.state.obstacle.center[0] - organism.x, dy = model.state.obstacle.center[1] - organism.y, size = Math.hypot(dx, dy) || 1;
        const offset = Number(organism.responses[calibration.field]) * 27 * Math.sin(calibration.progress * Math.PI);
        ctx.beginPath(); ctx.arc(organism.x + dx / size * offset, organism.y + dy / size * offset, organism.radius + 5, 0, Math.PI * 2); ctx.strokeStyle = organism.color; ctx.globalAlpha = .45; ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
      }
      ctx.beginPath(); ctx.arc(organism.x, organism.y, organism.radius, 0, Math.PI * 2); ctx.fillStyle = organism.color; ctx.shadowColor = organism.color; ctx.shadowBlur = organism.captured ? 18 : 8; ctx.fill(); ctx.shadowBlur = 0; ctx.fillStyle = "#07100a"; ctx.font = "900 13px ui-monospace"; ctx.fillText(organism.label, organism.x, organism.y + 5);
    }
    if (calibration) { ctx.fillStyle = `${palette.paper}dd`; ctx.fillRect(355, 16, 290, 45); ctx.strokeStyle = palette.ink; ctx.strokeRect(355, 16, 290, 45); ctx.fillStyle = palette.ink; ctx.font = "900 13px ui-monospace"; ctx.fillText(`CALIBRATION FILM · ${calibration.field}`, 500, 44); }
    else if (model.selectedField) { ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(model.lure[0], model.lure[1], 12, 0, Math.PI * 2); ctx.moveTo(model.lure[0] - 18, model.lure[1]); ctx.lineTo(model.lure[0] + 18, model.lure[1]); ctx.moveTo(model.lure[0], model.lure[1] - 18); ctx.lineTo(model.lure[0], model.lure[1] + 18); ctx.stroke(); ctx.fillStyle = palette.ink; ctx.font = "800 8px ui-monospace"; ctx.fillText(`${model.selectedField}${model.active ? " LIVE" : " ARMED"}`, model.lure[0], model.lure[1] - 22); }
    model.raf = requestAnimationFrame(draw);
  }

  async function submit() {
    if (!model || model.submitting || model.terminal) return;
    model.submitting = true;
    model.helpers.setReadout("REPLAYING COUPLED FIELD PHYSICS…", "pending");
    const payload = {
      mechanic_id: model.state.mechanic_id,
      task_id: model.state.task_id,
      challenge_id: model.state.challenge_id,
      interaction: model.interaction,
      control_condition: model.state.control_condition || null,
      events: model.events,
      final_organisms: snapshot(),
      tick: model.tick,
      completed: model.completed,
      field_selections: model.fieldSelections,
      pointer_drags: model.pointerDrags,
      calibration_runs: model.calibrationRuns,
      resets: model.resets,
    };
    try {
      const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(payload)});
      const outcome = await response.json();
      if (outcome.passed === true) {
        model.terminal = true;
        document.querySelector(".eco-complete")?.setAttribute("data-visible", "false");
        document.querySelector(".impossible-ecology-nonrealtime-captcha")?.insertAdjacentHTML("beforeend", '<div class="eco-verdict"><span>COUPLED ECOSYSTEM STABLE</span><strong>PASS</strong><i>FIELD / MOTION / SANCTUARY REPLAY VERIFIED</i></div>');
        model.helpers.setReadout("PASS", "passed");
      } else if (outcome.passed === false && outcome.state) {
        await model.helpers.render(outcome.state);
        const root = document.querySelector(".impossible-ecology-nonrealtime-captcha");
        root?.setAttribute("data-fresh-failure", "true");
        root?.insertAdjacentHTML("afterbegin", '<div class="eco-fail-stamp"><b>FAIL</b><span>UNSTABLE ECOLOGY · FRESH FIELD ISSUED</span></div>');
        const readout = document.querySelector(".readout"); if (readout) { readout.textContent = "FAIL · FRESH COUPLED FIELD ISSUED"; readout.dataset.status = "error"; }
      } else { model.submitting = false; model.helpers.setReadout("FAIL · ECOLOGY GRADE UNAVAILABLE", "error"); }
    } catch (_error) { model.submitting = false; model.helpers.setReadout("FAIL · ECOLOGY VERIFIER OFFLINE", "error"); }
  }

  async function render(state, helpers) {
    if (model?.raf) cancelAnimationFrame(model.raf);
        document.body.dataset.mechanic = "impossible-ecology-nonrealtime";
    document.body.dataset.cheatMode = helpers.isCheatMode() ? "true" : "false";
    const interaction = state.control_condition?.interaction || "full";
    const organismCount = state.organisms.length;
    const coordinateControls = interaction === "simplified" ? `<section class="eco-coordinate-control"><p>FIELD-LURE COORDINATE PAD</p><span>Hold and move anywhere in this scaled arena map. Every position maps directly to the same field-lure coordinate as the full arena.</span><div class="eco-coordinate-pad" data-armed="false" data-active="false" aria-label="field-lure coordinate pad"><i aria-hidden="true"></i><b>ARENA X 0–1000 · Y 0–430</b></div></section>` : "";
    const rules = interaction === "simplified"
      ? ["Select one global field, then hold and move anywhere in the coordinate pad.", "Every uncaptured organism responds at once. Each pointer action advances one physics step.", "A matching sanctuary locks an organism permanently. Stabilize all organisms."]
      : state.rules;
    const arenaNote = interaction === "simplified"
      ? "SELECT FIELD · HOLD / MOVE COORDINATE PAD · ACTIONS ADVANCE THE FIELD"
      : "SELECT FIELD · HOLD / MOVE POINTER · ACTIONS ADVANCE THE FIELD";
    const consoleHeading = interaction === "simplified"
      ? "One field. A direct coordinate pad."
      : `One pointer. ${organismCount} incompatible responses.`;
    helpers.app.innerHTML = `<section class="impossible-ecology-nonrealtime-captcha" data-interaction="${esc(interaction)}" data-challenge-id="${esc(state.challenge_id)}" data-fresh-failure="false" data-captured="0" style="--eco-grid:${esc(state.palette.grid)};--eco-ink:${esc(state.palette.ink)};--eco-danger:${esc(state.palette.danger)}"><header class="eco-head"><div><span>IMPOSSIBLE ECOLOGY / COUPLED FIELD ${esc(state.challenge_id)}</span><h1>${esc(state.prompt)}</h1></div><aside><span>STABLE SANCTUARIES</span><b id="eco-capture-count">0 / ${organismCount}</b><i>TICK <strong id="eco-tick-count">0000</strong></i></aside></header><main class="eco-main"><section class="eco-arena-shell"><canvas class="eco-arena" width="${state.arena.width}" height="${state.arena.height}"></canvas><div class="eco-arena-note">${arenaNote}</div><div class="eco-complete" data-visible="false"><b>ALL ${organismCount} SANCTUARIES STABLE</b><span>CERTIFY THE LIVING FIELD</span></div></section><aside class="eco-console"><p class="eco-console-label">GLOBAL FIELD CONSOLE</p><h2>${consoleHeading}</h2><div class="eco-fields">${state.fields.map((field, index) => `<button type="button" data-field="${esc(field)}"><i>${String(index + 1).padStart(2, "0")}</i><b>${esc(field)}</b><span>ARM FIELD</span></button>`).join("")}</div><button type="button" class="eco-calibrate">RUN ${state.fields.length}-FIELD CALIBRATION FILM</button>${coordinateControls}<ol id="eco-organism-ledger" class="eco-ledger"></ol><div class="eco-rules">${rules.map((rule) => `<p>${esc(rule)}</p>`).join("")}</div></aside></main><footer class="eco-foot"><button type="button" class="eco-reset">RESET ECOSYSTEM</button><div><span>FIELD STATUS</span><div class="readout" data-status="idle">FIELD LAB ACTIVE · CALIBRATE OR INTERVENE</div></div><button type="button" class="eco-submit">${esc(state.submit_label)}</button></footer>${helpers.cheatPanelTemplate()}</section>`;
    model = {state, helpers, interaction, canvas: document.querySelector(".eco-arena"), coordinatePad: document.querySelector(".eco-coordinate-pad"), targets: new Map(state.targets.map((target) => [target.organism_id, target])), organisms: {}, selectedField: null, lure: [state.arena.width / 2, state.arena.height / 2], active: false, pointerDown: false, tick: 0, completed: false, events: [], fieldSelections: 0, pointerDrags: 0, calibrationRuns: 0, resets: 0, calibrating: null, submitting: false, terminal: false, raf: null};
    model.organisms = initialOrganisms();
    window.impossibleEcologyNonRealtimeModel = model;
    document.querySelectorAll("[data-field]").forEach((button) => button.addEventListener("click", () => selectField(button.dataset.field)));
    document.querySelector(".eco-calibrate")?.addEventListener("click", runCalibration);
    document.querySelector(".eco-reset")?.addEventListener("click", () => resetWorld(true));
    document.querySelector(".eco-submit")?.addEventListener("click", submit);
    if (interaction === "full") {
      model.canvas.addEventListener("pointerdown", pointerDown);
      model.canvas.addEventListener("pointermove", pointerMove);
      model.canvas.addEventListener("pointerup", pointerUp);
      model.canvas.addEventListener("pointercancel", pointerUp);
    } else {
      model.coordinatePad.addEventListener("pointerdown", coordinatePadDown);
      model.coordinatePad.addEventListener("pointermove", coordinatePadMove);
      model.coordinatePad.addEventListener("pointerup", coordinatePadUp);
      model.coordinatePad.addEventListener("pointercancel", coordinatePadUp);
    }
    updateHUD();
    model.raf = requestAnimationFrame(draw);
    helpers.installCheatPanel();
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.impossible_ecology_nonrealtime = {rootSelector: ".impossible-ecology-nonrealtime-captcha", render};
})();
