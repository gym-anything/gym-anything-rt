(() => {
  "use strict";

  const WIDTH = 820;
  const HEIGHT = 390;
  const DIRECTION_VECTORS = {
    NORTH: {x: 0, y: -1, angle: -90}, EAST: {x: 1, y: 0, angle: 0},
    SOUTH: {x: 0, y: 1, angle: 90}, WEST: {x: -1, y: 0, angle: 180},
  };
  let model = null;
  let cleanup = null;

  const esc = (value) => String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const interaction = () => model.state.control_condition?.interaction || "full";
  const now = () => model.helpers.interactionNow();
  const elapsed = () => Math.max(0, now() - model.roundStartedAt);
  const round = () => model.state.rounds[model.roundIndex];
  const token = (id) => round().tokens.find((item) => item.id === id);
  const angleDiff = (left, right) => Math.abs(((left - right + 180) % 360 + 360) % 360 - 180);

  function logicalPoint(event) {
    const stage = document.querySelector(".fsr-stage");
    const rect = stage.getBoundingClientRect();
    return {
      x: Number(clamp((event.clientX - rect.left) / rect.width * WIDTH, 0, WIDTH).toFixed(3)),
      y: Number(clamp((event.clientY - rect.top) / rect.height * HEIGHT, 0, HEIGHT).toFixed(3)),
    };
  }

  function motionPosition(item, t) {
    if (!item.motion) return {x: item.x, y: item.y};
    return {
      x: item.motion.x0 + item.motion.vx * t / 1000,
      y: item.motion.y0 + item.motion.amplitude * Math.sin(t / item.motion.period_ms * Math.PI * 2 + item.motion.phase),
    };
  }

  function bayOpen(bay, t) {
    return ((t + bay.phase_offset_ms) % bay.period_ms) < bay.open_ms;
  }

  function pointerAngle(spec, t) {
    return ((spec.angle_zero_deg + spec.angular_speed_deg_s * t / 1000) % 360 + 360) % 360;
  }

  function clearFreshFailure() {
    if (!model.freshFailure) return;
    model.freshFailure = false;
    const verdict = document.querySelector(".fsr-verdict");
    if (verdict) verdict.className = "fsr-verdict";
    model.helpers.setReadout("DISPATCH ACTIVE", "idle");
  }

  function record(event) {
    clearFreshFailure();
    const complete = {sequence: ++model.sequence, ...event};
    model.currentEvents.push(complete);
    return complete;
  }

  function tokenVisual(item, small = false) {
    return `<span class="fsr-glyph shape-${esc(item.shape.toLowerCase())} mark-${esc(item.mark.toLowerCase())} ${small ? "is-small" : ""}" style="--token:${esc(item.color_hex)}"><i></i></span>`;
  }

  function tokenNode(item, options = {}) {
    const disabled = interaction() === "simplified" ? 'aria-disabled="true" tabindex="-1"' : "";
    const label = `${item.color} ${item.shape}, ${item.mark.toLowerCase()} mark`;
    return `<button class="fsr-token-node ${options.className || ""}" data-token-id="${esc(item.id)}" aria-label="${esc(label)}" ${disabled}
      style="--x:${Number(item.x).toFixed(2)};--y:${Number(item.y).toFixed(2)}">${tokenVisual(item)}<b>${esc(item.color)}</b><small>${esc(item.shape)}</small></button>`;
  }

  function tokenProxy(item, action = "select") {
    return `<button class="fsr-proxy-token" data-proxy-${esc(action)}="${esc(item.id)}" aria-label="${esc(action)} ${esc(item.color)} ${esc(item.shape)}">
      ${tokenVisual(item, true)}<span>${esc(item.color)}<b>${esc(item.shape)}</b></span>
    </button>`;
  }

  function gateStage(spec) {
    return `<div class="fsr-gate" style="--gate-x:${spec.gate.x};--gate-half:${spec.gate.half_width}"><i></i><b>TAG WINDOW</b></div>
      <div class="fsr-motion-track"></div>${spec.tokens.map((item) => tokenNode(item, {className: "is-moving"})).join("")}`;
  }

  function holdStage(spec) {
    return `<div class="fsr-sweep-board">
        <div class="fsr-sweep-head"><b>SYNCHRONIZATION NEEDLES</b><span>WHITE NOTCH / AMBER RELEASE</span></div>
        <div class="fsr-rail rail-a"><i class="fsr-notch"></i><em class="fsr-needle"></em></div>
        <div class="fsr-rail rail-b"><i class="fsr-notch"></i><em class="fsr-needle"></em></div>
      </div><div class="fsr-token-field is-hold-field">${spec.tokens.map((item) => tokenNode(item, {className: "is-hold"})).join("")}</div>`;
  }

  function flickStage(spec) {
    return `<div class="fsr-compass"><i>N</i><i>E</i><i>S</i><i>W</i><b>VECTOR FIELD</b></div>
      <div class="fsr-token-field is-flick-field">${spec.tokens.map((item) => `${tokenNode(item, {className: "is-flick"})}<span class="fsr-pointer" data-pointer-for="${esc(item.id)}" style="--x:${Number(item.x).toFixed(2)};--y:${Number(item.y).toFixed(2)}"><i></i></span>`).join("")}</div>`;
  }

  function relayStage(spec) {
    return `<div class="fsr-relay-grid"><div class="fsr-relay-lines"></div>${spec.tokens.map((item) => tokenNode(item, {className: "is-relay"})).join("")}</div>`;
  }

  function dropStage(spec) {
    const cargo = spec.tokens.map((item) => tokenNode(item, {className: "is-cargo"})).join("");
    const bays = spec.bays.map((bay) => `<button class="fsr-bay" data-bay-id="${esc(bay.id)}" aria-disabled="${interaction() === "simplified"}" tabindex="-1"
      style="--x:${bay.x};--y:${bay.y};--bay:${esc(bay.color_hex)};--radius:${bay.radius}"><i></i><b>${esc(bay.color)}</b><small>SHUTTER</small></button>`).join("");
    return `<div class="fsr-cargo-lane"><span>CARGO RACK</span></div><div class="fsr-bay-wall"><span>RECEIVING WALL</span></div>${cargo}${bays}`;
  }

  function stageMarkup(spec) {
    const body = {
      gate_tag: gateStage, sync_hold: holdStage, vector_flick: flickStage,
      relay_pair: relayStage, shutter_drop: dropStage,
    }[spec.family](spec);
    return `<section class="fsr-stage family-${esc(spec.family)}" aria-label="five-second dispatch stage">${body}<div class="fsr-stage-flash"></div></section>`;
  }

  function proxyMarkup(spec) {
    if (interaction() !== "simplified") {
      const copy = {
        gate_tag: ["DIRECT TAG", "Click the moving token inside the gate."],
        sync_hold: ["DIRECT HOLD", "Hold and release the physical token."],
        vector_flick: ["DIRECT FLICK", "Drag from the token in the ordered direction."],
        relay_pair: ["DIRECT RELAY", "Tap both tokens on the field."],
        shutter_drop: ["DIRECT DROP", "Drag cargo into the open bay."],
      }[spec.family];
      return `<div class="fsr-direct-card"><i></i><small>INPUT SURFACE</small><b>${copy[0]}</b><p>${copy[1]}</p></div>`;
    }
    const tokens = spec.tokens.map((item) => tokenProxy(item, spec.family === "relay_pair" ? "tap" : "select")).join("");
    if (spec.family === "gate_tag") return `<div class="fsr-proxy-title">STATIONARY TAG KEYS</div><div class="fsr-proxy-grid">${spec.tokens.map((item) => tokenProxy(item, "tag")).join("")}</div>`;
    if (spec.family === "sync_hold") return `<div class="fsr-proxy-title">STATIONARY HOLD KEYS</div><div class="fsr-proxy-grid">${spec.tokens.map((item) => tokenProxy(item, "hold")).join("")}</div>`;
    if (spec.family === "relay_pair") return `<div class="fsr-proxy-title">STATIONARY RELAY KEYS</div><div class="fsr-proxy-grid">${tokens}</div>`;
    if (spec.family === "vector_flick") return `<div class="fsr-proxy-title">SELECT TOKEN / SEND VECTOR</div><div class="fsr-proxy-grid">${tokens}</div><div class="fsr-directions">${Object.keys(DIRECTION_VECTORS).map((name) => `<button data-proxy-direction="${name}">${name[0]}</button>`).join("")}</div>`;
    return `<div class="fsr-proxy-title">SELECT CARGO / OPEN BAY</div><div class="fsr-proxy-grid">${tokens}</div><div class="fsr-proxy-bays">${spec.bays.map((bay) => `<button data-proxy-bay="${esc(bay.id)}" style="--bay:${esc(bay.color_hex)}">${esc(bay.color)}</button>`).join("")}</div>`;
  }

  function shellMarkup() {
    const spec = round();
    const progress = model.state.rounds.map((_, index) => `<i class="${index < model.roundIndex ? "is-done" : index === model.roundIndex ? "is-live" : ""}"></i>`).join("");
    return `<section class="five-second-rule mode-${interaction()}" data-fresh-failure="${model.freshFailure ? "true" : "false"}">
      <div class="fsr-verdict"></div>
      <header class="fsr-masthead"><div class="fsr-brand"><span>FIVE</span><b>SECOND</b><i>RULE</i></div><div class="fsr-status"><small>DISPATCH DECK / ${esc(model.state.challenge_id.slice(-7).toUpperCase())}</small><h1>${esc(model.state.prompt)}</h1><div>${progress}<span>ROUND ${model.roundIndex + 1} / 5</span></div></div><div class="fsr-mode"><small>${interaction().toUpperCase()}</small><b>INPUT</b></div></header>
      <main><section class="fsr-order"><small>ORDER ${String(model.roundIndex + 1).padStart(2, "0")} · READ BOTH LINES</small><h2><span>1</span>${esc(spec.instruction[0])}</h2><h2><span>2</span>${esc(spec.instruction[1])}</h2></section>
        <div class="fsr-workbench">${stageMarkup(spec)}<aside class="fsr-side"><div class="fsr-timer" style="--remaining:1"><i></i><strong>5</strong><span>SECONDS</span></div><div class="fsr-proxy-panel">${proxyMarkup(spec)}</div></aside></div>
      </main>
      <footer><div class="readout" data-status="idle">DISPATCH ACTIVE</div><span>EVERY ORDER EXPIRES AT THE RED LINE</span></footer>
      ${model.helpers.cheatPanelTemplate()}
    </section>`;
  }

  function showVerdict(kind) {
    const node = document.querySelector(".fsr-verdict");
    if (!node) return;
    node.className = `fsr-verdict is-${kind}`;
    node.innerHTML = `<small>DISPATCH CONTROL</small><b>${kind.toUpperCase()}</b>`;
  }

  function renderRound() {
    cancelAnimationFrame(model.frame);
    model.currentEvents = [];
    model.roundResolved = false;
    model.proxySelected = null;
    model.pending = null;
    model.roundStartedAt = now();
    model.helpers.app.innerHTML = shellMarkup();
    bindControls();
    model.helpers.installCheatPanel();
    if (model.freshFailure) showVerdict("fail");
    model.frame = requestAnimationFrame(tick);
  }

  function passRound() {
    if (model.roundResolved || model.terminal) return;
    model.roundResolved = true;
    model.rounds.push({round_id: round().id, family: round().family, events: model.currentEvents.slice()});
    model.helpers.setReadout("ORDER CLEARED", "passed");
    document.querySelector(".fsr-stage")?.classList.add("is-cleared");
    cancelAnimationFrame(model.frame);
    if (model.roundIndex === model.state.rounds.length - 1) {
      setTimeout(() => submit(true), 160);
    } else {
      setTimeout(() => { model.roundIndex += 1; renderRound(); }, 180);
    }
  }

  async function submit(completed) {
    if (!model || model.submitting || model.terminal) return;
    const current = model;
    current.submitting = true;
    current.helpers.setReadout(completed ? "REPLAYING FIVE ORDERS…" : "ORDER FAILED", completed ? "pending" : "error");
    try {
      const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({
        mechanic_id: current.state.mechanic_id,
        task_id: current.state.task_id,
        challenge_id: current.state.challenge_id,
        world_fingerprint: current.state.world_fingerprint,
        interaction_mode: interaction(),
        rounds: current.rounds,
        completed,
      })});
      const outcome = await response.json();
      if (outcome.passed === true) {
        current.terminal = true;
        current.helpers.setReadout("PASS", "passed");
        showVerdict("pass");
      } else if (outcome.passed === false && outcome.state) {
        const helpers = current.helpers;
        await render(outcome.state, helpers, {freshFailure: true});
        model.helpers.setReadout("FAIL", "error");
        showVerdict("fail");
      } else {
        current.submitting = false;
        current.helpers.setReadout("DISPATCH REJECTED", "error");
        showVerdict("fail");
      }
    } catch (_error) {
      if (model === current) {
        current.submitting = false;
        current.helpers.setReadout("DISPATCH LINK OFFLINE", "error");
      }
    }
  }

  function failAttempt(message) {
    if (model.roundResolved || model.submitting || model.terminal) return;
    model.roundResolved = true;
    if (model.currentEvents.length) {
      model.rounds.push({round_id: round().id, family: round().family, events: model.currentEvents.slice()});
    }
    cancelAnimationFrame(model.frame);
    model.helpers.setReadout(message || "ORDER FAILED", "error");
    document.querySelector(".fsr-stage")?.classList.add("is-failed");
    setTimeout(() => submit(false), 120);
  }

  function attemptTag(id, source, point = null) {
    const spec = round();
    const t = elapsed();
    record({type: "tag", target_id: id, t_ms: Number(t.toFixed(3)), input_source: source, ...(point ? {point} : {})});
    const expected = spec.predicate.target_id;
    const position = motionPosition(token(expected), t);
    const valid = id === expected && Math.abs(position.x - spec.gate.x) <= spec.gate.half_width;
    if (valid && (source !== "direct_tag" || Math.hypot(point.x - position.x, point.y - position.y) <= 37)) passRound();
    else failAttempt("TAG MISSED");
  }

  function attemptHold(id, source, startMs, endMs, startPoint = null) {
    const spec = round();
    record({type: "hold", target_id: id, start_ms: Number(startMs.toFixed(3)), end_ms: Number(endMs.toFixed(3)), input_source: source, ...(startPoint ? {start_point: startPoint} : {})});
    const cue = spec.cue;
    const valid = id === spec.predicate.target_id && Math.abs(startMs - cue.start_ms) <= cue.tolerance_ms && Math.abs(endMs - cue.end_ms) <= cue.tolerance_ms && endMs - startMs >= cue.end_ms - cue.start_ms - cue.tolerance_ms * 2;
    if (valid) passRound(); else failAttempt("SYNCHRONIZATION LOST");
  }

  function attemptFlick(id, source, t, direction, startPoint = null, endPoint = null) {
    const spec = round();
    const event = {type: "flick", target_id: id, t_ms: Number(t.toFixed(3)), input_source: source};
    if (source === "direct_flick") Object.assign(event, {start_point: startPoint, end_point: endPoint});
    else event.direction = direction;
    record(event);
    const flick = spec.flick;
    let valid = id === spec.predicate.target_id && angleDiff(pointerAngle(flick, t), flick.face_angle_deg) <= flick.angle_tolerance_deg;
    if (source === "direct_flick") {
      const dx = endPoint.x - startPoint.x, dy = endPoint.y - startPoint.y;
      const vector = DIRECTION_VECTORS[flick.flick_direction];
      valid = valid && Math.hypot(dx, dy) >= flick.min_travel_px && angleDiff(Math.atan2(dy, dx) * 180 / Math.PI, vector.angle) <= 20;
    } else valid = valid && direction === flick.flick_direction;
    if (valid) passRound(); else failAttempt("VECTOR REJECTED");
  }

  function attemptRelay(id, source, point = null) {
    const spec = round();
    const expected = model.currentEvents.length === 0 ? spec.predicate.first_id : spec.predicate.second_id;
    record({type: "tap", target_id: id, t_ms: Number(elapsed().toFixed(3)), input_source: source, ...(point ? {point} : {})});
    if (id !== expected) return failAttempt("RELAY ORDER BROKEN");
    document.querySelector(`[data-token-id="${CSS.escape(id)}"]`)?.classList.add("is-armed");
    document.querySelector(`[data-proxy-tap="${CSS.escape(id)}"]`)?.classList.add("is-armed");
    if (model.currentEvents.length === 2) passRound();
  }

  function attemptDrop(targetId, bayId, source, t, startPoint = null, endPoint = null) {
    const spec = round();
    const event = {type: "drop", target_id: targetId, bay_id: bayId, t_ms: Number(t.toFixed(3)), input_source: source};
    if (source === "direct_drag") Object.assign(event, {start_point: startPoint, end_point: endPoint});
    record(event);
    const bay = spec.bays.find((item) => item.id === bayId);
    let valid = targetId === spec.predicate.target_id && bayId === spec.predicate.bay_id && bay && bayOpen(bay, t);
    if (source === "direct_drag" && bay) valid = valid && Math.hypot(endPoint.x - bay.x, endPoint.y - bay.y) <= bay.radius && Math.hypot(endPoint.x - startPoint.x, endPoint.y - startPoint.y) >= 120;
    if (valid) passRound(); else failAttempt("SHUTTER CLOSED");
  }

  function bindDirectToken(node, spec) {
    const id = node.dataset.tokenId;
    if (spec.family === "gate_tag") node.addEventListener("click", (event) => attemptTag(id, "direct_tag", logicalPoint(event)));
    if (spec.family === "relay_pair") node.addEventListener("click", (event) => attemptRelay(id, "direct_tap", logicalPoint(event)));
    if (spec.family === "sync_hold") {
      node.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault(); clearFreshFailure();
        model.pending = {kind: "hold", id, startMs: elapsed(), startPoint: logicalPoint(event)};
        node.setPointerCapture?.(event.pointerId);
        node.classList.add("is-held");
      });
      node.addEventListener("pointerup", (event) => {
        if (!model.pending || model.pending.kind !== "hold" || model.pending.id !== id) return;
        const pending = model.pending; model.pending = null; node.classList.remove("is-held");
        attemptHold(id, "direct_hold", pending.startMs, elapsed(), pending.startPoint);
      });
    }
    if (spec.family === "vector_flick" || spec.family === "shutter_drop") {
      node.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault(); clearFreshFailure();
        model.pending = {kind: spec.family, id, startPoint: logicalPoint(event)};
        node.setPointerCapture?.(event.pointerId);
        node.classList.add("is-held");
      });
      node.addEventListener("pointerup", (event) => {
        if (!model.pending || model.pending.id !== id) return;
        const pending = model.pending; model.pending = null; node.classList.remove("is-held");
        const endPoint = logicalPoint(event); const t = elapsed();
        if (pending.kind === "vector_flick") attemptFlick(id, "direct_flick", t, null, pending.startPoint, endPoint);
        else {
          const bay = spec.bays.find((item) => Math.hypot(endPoint.x - item.x, endPoint.y - item.y) <= item.radius);
          attemptDrop(id, bay?.id || "", "direct_drag", t, pending.startPoint, endPoint);
        }
      });
    }
  }

  function selectProxy(id) {
    clearFreshFailure();
    model.proxySelected = id;
    document.querySelectorAll(".fsr-proxy-token").forEach((button) => button.classList.toggle("is-selected", Object.values(button.dataset).includes(id)));
  }

  function bindControls() {
    const spec = round();
    if (interaction() === "full") {
      document.querySelectorAll("[data-token-id]").forEach((node) => bindDirectToken(node, spec));
      return;
    }
    document.querySelectorAll("[data-proxy-tag]").forEach((button) => button.addEventListener("click", () => attemptTag(button.dataset.proxyTag, "proxy_tag")));
    document.querySelectorAll("[data-proxy-tap]").forEach((button) => button.addEventListener("click", () => attemptRelay(button.dataset.proxyTap, "proxy_tap")));
    document.querySelectorAll("[data-proxy-select]").forEach((button) => button.addEventListener("click", () => selectProxy(button.dataset.proxySelect)));
    document.querySelectorAll("[data-proxy-hold]").forEach((button) => {
      button.addEventListener("pointerdown", (event) => { event.preventDefault(); clearFreshFailure(); model.pending = {kind: "hold", id: button.dataset.proxyHold, startMs: elapsed()}; button.setPointerCapture?.(event.pointerId); button.classList.add("is-held"); });
      button.addEventListener("pointerup", () => { if (!model.pending || model.pending.id !== button.dataset.proxyHold) return; const pending = model.pending; model.pending = null; button.classList.remove("is-held"); attemptHold(pending.id, "proxy_hold", pending.startMs, elapsed()); });
    });
    document.querySelectorAll("[data-proxy-direction]").forEach((button) => button.addEventListener("click", () => attemptFlick(model.proxySelected || "", "proxy_flick", elapsed(), button.dataset.proxyDirection)));
    document.querySelectorAll("[data-proxy-bay]").forEach((button) => button.addEventListener("click", () => attemptDrop(model.proxySelected || "", button.dataset.proxyBay, "proxy_drop", elapsed())));
  }

  function tick() {
    if (!model || model.roundResolved || model.terminal) return;
    const spec = round();
    const t = elapsed();
    const remaining = clamp(1 - t / spec.duration_ms, 0, 1);
    const timer = document.querySelector(".fsr-timer");
    if (timer) {
      timer.style.setProperty("--remaining", remaining.toFixed(5));
      const strong = timer.querySelector("strong");
      if (strong) strong.textContent = String(Math.max(0, Math.ceil((spec.duration_ms - t) / 1000)));
      timer.classList.toggle("is-urgent", remaining < .24);
    }
    if (spec.family === "gate_tag") {
      spec.tokens.forEach((item) => {
        const position = motionPosition(item, t);
        const node = document.querySelector(`[data-token-id="${CSS.escape(item.id)}"]`);
        if (node) {
          node.style.setProperty("--x", position.x.toFixed(3));
          node.style.setProperty("--y", position.y.toFixed(3));
          node.classList.toggle("is-in-gate", Math.abs(position.x - spec.gate.x) <= spec.gate.half_width);
        }
      });
    } else if (spec.family === "sync_hold") {
      const before = spec.cue.start_ms - 760;
      const after = spec.cue.end_ms + 520;
      const position = t < spec.cue.start_ms ? 8 + clamp((t - before) / 760, 0, 1) * 42 : t <= spec.cue.end_ms ? 50 : 50 + clamp((t - spec.cue.end_ms) / (after - spec.cue.end_ms), 0, 1) * 44;
      document.querySelectorAll(".fsr-needle").forEach((node, index) => node.style.left = `${clamp(position + (index ? -1.4 : 1.4), 4, 96)}%`);
      document.querySelector(".fsr-sweep-board")?.classList.toggle("is-release", t >= spec.cue.end_ms && t <= spec.cue.end_ms + spec.cue.tolerance_ms);
      document.querySelector(".fsr-sweep-board")?.classList.toggle("is-ready", t >= spec.cue.start_ms && t < spec.cue.end_ms);
    } else if (spec.family === "vector_flick") {
      const angle = pointerAngle(spec.flick, t);
      document.querySelectorAll("[data-pointer-for]").forEach((node) => { node.style.setProperty("--angle", `${angle}deg`); });
      document.querySelector(".fsr-compass")?.classList.toggle("is-aligned", angleDiff(angle, spec.flick.face_angle_deg) <= spec.flick.angle_tolerance_deg);
    } else if (spec.family === "shutter_drop") {
      spec.bays.forEach((bay) => {
        const node = document.querySelector(`[data-bay-id="${CSS.escape(bay.id)}"]`);
        if (node) {
          const open = bayOpen(bay, t);
          const phase = (t + bay.phase_offset_ms) % bay.period_ms;
          const aperture = open ? .18 + .82 * Math.sin(Math.PI * phase / bay.open_ms) : 0;
          node.classList.toggle("is-open", open);
          node.style.setProperty("--aperture", aperture.toFixed(4));
        }
        document.querySelector(`[data-proxy-bay="${CSS.escape(bay.id)}"]`)?.classList.toggle("is-open", bayOpen(bay, t));
      });
    }
    if (t >= spec.duration_ms) return failAttempt("TIME EXPIRED");
    model.frame = requestAnimationFrame(tick);
  }

  async function render(state, helpers, options = {}) {
    cleanup?.();
    document.body.dataset.mechanic = "five-second-rule";
    model = {
      state, helpers, roundIndex: 0, roundStartedAt: 0, rounds: [], currentEvents: [], sequence: 0,
      frame: 0, pending: null, proxySelected: null, roundResolved: false, submitting: false,
      terminal: false, freshFailure: Boolean(options.freshFailure),
    };
    renderRound();
    cleanup = () => { cancelAnimationFrame(model?.frame || 0); };
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.five_second_rule = {rootSelector: ".five-second-rule", render};
})();
