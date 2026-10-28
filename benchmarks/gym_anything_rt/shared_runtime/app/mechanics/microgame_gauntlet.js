(() => {
  "use strict";

  let helpersCache = null;
  let model = null;
  let keyDownHandler = null;
  let keyUpHandler = null;

  function esc(value) {
    return String(value == null ? "" : value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  function currentRound() {
    return model.state.rounds[model.roundIndex] || null;
  }

  function interactionMode() {
    const mode = model?.state?.control_condition?.interaction;
    return mode === "simplified" || mode === "full" ? mode : "full";
  }

  function isSimplified() {
    return interactionMode() === "simplified";
  }

  function cleanupRound() {
    (model?.timers || []).forEach((timer) => window.clearInterval(timer));
    if (model) model.timers = [];
    if (keyDownHandler) window.removeEventListener("keydown", keyDownHandler, true);
    if (keyUpHandler) window.removeEventListener("keyup", keyUpHandler, true);
    keyDownHandler = null;
    keyUpHandler = null;
  }

  function event(action, details = {}) {
    const source = model?.state?.control_condition ? {input_surface: interactionMode()} : {};
    model.roundEvents.push({sequence: model.roundEvents.length + 1, action, ...source, ...details});
  }

  function resource(kind, reason) {
    const round = currentRound();
    const before = model.energy;
    const cost = kind === "round_complete" ? Number(round?.energy_cost || 8) : kind === "fault" ? Number(model.state.fault_penalty || 12) : Number(model.state.reset_penalty || 4);
    model.energy = Math.max(0, model.energy - cost);
    model.resourceEvents.push({
      sequence: model.resourceEvents.length + 1,
      round_id: round?.id || "complete",
      kind,
      reason,
      energy_before: before,
      energy_after: model.energy,
    });
    renderEnergy();
    renderTelemetry();
  }

  function renderEnergy() {
    const fill = document.getElementById("gauntlet-energy-fill");
    const value = document.getElementById("gauntlet-energy-value");
    if (fill) fill.style.width = `${model.energy}%`;
    if (value) value.textContent = String(model.energy).padStart(3, "0");
    const root = document.querySelector(".gauntlet-reactor");
    if (root) root.dataset.energy = model.energy <= 30 ? "critical" : model.energy <= 60 ? "warn" : "stable";
  }

  function renderTelemetry() {
    const list = document.getElementById("gauntlet-telemetry");
    if (!list) return;
    const entries = model.resourceEvents.slice(-7).reverse();
    list.innerHTML = entries.length ? entries.map((item) => `<li data-kind="${esc(item.kind)}"><i>${String(item.sequence).padStart(2, "0")}</i><b>${esc(item.kind.replaceAll("_", " ").toUpperCase())}</b><span>${item.energy_before} → ${item.energy_after}</span></li>`).join("") : '<li class="is-empty">NO RESOURCE EVENTS</li>';
  }

  function renderRail() {
    const rail = document.getElementById("gauntlet-round-rail");
    if (!rail) return;
    rail.innerHTML = model.state.rounds.map((round, index) => {
      const status = index < model.roundIndex ? "done" : index === model.roundIndex ? "active" : "queued";
      return `<li data-status="${status}"><i>${String(index + 1).padStart(2, "0")}</i><span>${esc(round.type.toUpperCase())}</span><b>${status === "done" ? "SEALED" : status.toUpperCase()}</b></li>`;
    }).join("");
  }

  function clearFreshFailure() {
    const root = document.querySelector(".gauntlet-reactor");
    if (!root || root.dataset.freshFailure !== "true") return;
    root.dataset.freshFailure = "false";
    document.querySelector(".gauntlet-fail-stamp")?.remove();
    helpersCache.setReadout("REACTOR LIVE · FIVE TRIALS", "idle");
  }

  function fault(reason) {
    if (!model || model.transitioning || model.submitting || model.terminal) return;
    cleanupRound();
    resource("fault", reason);
    helpersCache.setReadout(`STABILITY LOSS · ${reason.toUpperCase()} · RETRY ROUND`, "error");
    model.roundEvents = [];
    if (model.energy <= 0) {
      window.setTimeout(certify, 120);
      return;
    }
    window.setTimeout(renderRound, 320);
  }

  function resetRound() {
    if (!model || model.transitioning || model.submitting || model.terminal) return;
    clearFreshFailure();
    resource("reset", "operator_reset");
    model.roundEvents = [];
    helpersCache.setReadout("ROUND RESET · 4 STABILITY SPENT", "error");
    renderRound();
  }

  function completeRound() {
    if (!model || model.transitioning) return;
    model.transitioning = true;
    cleanupRound();
    const round = currentRound();
    model.roundRecords.push({round_id: round.id, type: round.type, interaction_mode: interactionMode(), events: model.roundEvents.map((item) => ({...item}))});
    resource("round_complete", "trial_sealed");
    helpersCache.setReadout(`ROUND ${model.roundIndex + 1} SEALED · STABILITY ${model.energy}`, "passed");
    model.roundIndex += 1;
    model.roundEvents = [];
    renderRail();
    window.setTimeout(() => {
      model.transitioning = false;
      if (model.roundIndex >= model.state.rounds.length) renderComplete();
      else renderRound();
    }, 420);
  }

  function pressureRound(round, stage) {
    const pulses = round.pulses || [];
    const proxy = isSimplified()
      ? '<div class="gauntlet-proxy-controls"><button type="button" id="pressure-proxy-engage">ENGAGE PRESSURE</button><button type="button" id="pressure-proxy-release" disabled>RELEASE BANK</button></div>'
      : "";
    stage.innerHTML = `<div class="pressure-field"><div class="pressure-key" id="pressure-key"><span>CONTINUOUS PRESSURE</span><strong>${isSimplified() ? "PROXY" : "SPACE"}</strong><i>${isSimplified() ? "ENGAGE / RELEASE FROM CONTROL PANEL" : "RELEASE RESETS BANK"}</i></div>${pulses.map((pulse, index) => `<button type="button" class="pulse-socket" data-pulse-id="${esc(pulse.id)}" data-order="${index}" data-status="${index === 0 ? "lit" : "dark"}" style="--x:${pulse.x}%;--y:${pulse.y}%"><i></i><b>${String(index + 1).padStart(2, "0")}</b></button>`).join("")}${proxy}</div>`;
    const progress = {held: false, clicked: 0};
    const engage = () => {
      if (progress.held) return;
      clearFreshFailure();
      progress.held = true;
      event("space_down");
      document.getElementById("pressure-key")?.classList.add("is-held");
      helpersCache.setReadout("PRESSURE HELD · CLICK PULSE BANK", "idle");
    };
    const release = () => {
      if (!progress.held) return;
      progress.held = false;
      event("space_up");
      document.getElementById("pressure-key")?.classList.remove("is-held");
      if (progress.clicked === pulses.length) completeRound();
      else fault("pressure_released_early");
    };
    if (isSimplified()) {
      document.getElementById("pressure-proxy-engage")?.addEventListener("click", () => {
        engage();
        document.getElementById("pressure-proxy-engage")?.setAttribute("disabled", "disabled");
        document.getElementById("pressure-proxy-release")?.removeAttribute("disabled");
      });
      document.getElementById("pressure-proxy-release")?.addEventListener("click", release);
    } else {
      keyDownHandler = (keyEvent) => {
        if (keyEvent.code !== "Space" || keyEvent.repeat || progress.held) return;
        keyEvent.preventDefault();
        engage();
      };
      keyUpHandler = (keyEvent) => {
        if (keyEvent.code !== "Space" || !progress.held) return;
        keyEvent.preventDefault();
        release();
      };
      window.addEventListener("keydown", keyDownHandler, true);
      window.addEventListener("keyup", keyUpHandler, true);
    }
    stage.querySelectorAll(".pulse-socket").forEach((button) => button.addEventListener("click", () => {
      if (!progress.held) {
        fault("pulse_without_pressure");
        return;
      }
      const order = Number(button.dataset.order);
      if (order !== progress.clicked) {
        fault("pulse_out_of_order");
        return;
      }
      event("pulse_click", {pulse_id: String(button.dataset.pulseId)});
      button.dataset.status = "captured";
      progress.clicked += 1;
      const next = stage.querySelector(`.pulse-socket[data-order="${progress.clicked}"]`);
      if (next) next.dataset.status = "lit";
      helpersCache.setReadout(progress.clicked === pulses.length ? "BANK DARK · RELEASE SPACE" : `PULSE ${progress.clicked}/${pulses.length} CAPTURED`, "idle");
    }));
  }

  function chordRound(round, stage) {
    const chords = (round.chords || []).map((chord) => chord.map((key) => String(key).toUpperCase()));
    const proxy = isSimplified() ? '<div class="gauntlet-proxy-controls"><button type="button" id="chord-proxy-engage">ENGAGE DISPLAYED PAIR</button><button type="button" id="chord-proxy-release" disabled>RELEASE CHARGED PAIR</button></div>' : "";
    stage.innerHTML = `<div class="chord-field"><div class="chord-sequence">${chords.map((chord, index) => `<div data-chord-stage="${index}" data-status="${index === 0 ? "active" : "waiting"}"><span>FIELD ${index + 1}</span><b>${esc(chord[0])} + ${esc(chord[1])}</b></div>`).join("")}</div><div class="chord-keys"></div><div class="chord-charge"></div><p>CHARGE → RELEASE → ADVANCE / ${chords.length} CONTINUOUS FIELDS</p>${proxy}</div>`;
    const progress = {stage: 0, held: new Set(), ticks: 0, charged: false, faulted: false, timer: null};
    const stopTimer = () => { if (progress.timer) window.clearInterval(progress.timer); progress.timer = null; };
    const required = () => new Set(chords[progress.stage] || []);
    const paintStage = () => {
      stage.querySelectorAll("[data-chord-stage]").forEach((node, index) => { node.dataset.status = index < progress.stage ? "done" : index === progress.stage ? "active" : "waiting"; });
      const keys = chords[progress.stage] || [];
      const keyRack = stage.querySelector(".chord-keys");
      const charge = stage.querySelector(".chord-charge");
      if (keyRack) keyRack.innerHTML = keys.map((key) => `<div class="chord-key" data-key="${esc(key)}"><span>HOLD</span><strong>${esc(key)}</strong><i></i></div>`).join('<b class="chord-plus">+</b>');
      if (charge) charge.innerHTML = Array.from({length: Number(round.required_ticks)}, (_, index) => `<i data-tick="${index}"></i>`).join("");
    };
    const resetProxyButtons = () => {
      if (!isSimplified()) return;
      document.getElementById("chord-proxy-engage")?.removeAttribute("disabled");
      document.getElementById("chord-proxy-release")?.setAttribute("disabled", "disabled");
    };
    const sealField = () => {
      progress.stage += 1;
      progress.ticks = 0;
      progress.charged = false;
      if (progress.stage >= chords.length) completeRound();
      else {
        paintStage();
        resetProxyButtons();
        helpersCache.setReadout(`FIELD ${progress.stage}/${chords.length} SEALED · CHARGE FIELD ${progress.stage + 1}`, "idle");
      }
    };
    const startChargeTimer = () => {
      if (progress.timer) return;
      progress.timer = window.setInterval(() => {
        if (progress.held.size !== required().size || progress.faulted) return;
        progress.ticks += 1;
        event("hold_tick", {keys: [...progress.held].sort(), chord_index: progress.stage});
        stage.querySelector(`[data-tick="${progress.ticks - 1}"]`)?.classList.add("is-filled");
        if (progress.ticks >= Number(round.required_ticks)) {
          progress.charged = true;
          stopTimer();
          if (isSimplified()) document.getElementById("chord-proxy-release")?.removeAttribute("disabled");
          helpersCache.setReadout(`FIELD ${progress.stage + 1}/${chords.length} CHARGED · RELEASE BOTH KEYS`, "idle");
        }
      }, Number(round.tick_ms));
      model.timers.push(progress.timer);
    };
    const pressKey = (key) => {
      progress.held.add(key);
      event("key_down", {key, chord_index: progress.stage});
      stage.querySelector(`.chord-key[data-key="${CSS.escape(key)}"]`)?.classList.add("is-held");
      if (progress.held.size === required().size) startChargeTimer();
    };
    const releaseKey = (key) => {
      progress.held.delete(key);
      event("key_up", {key, chord_index: progress.stage});
      stage.querySelector(`.chord-key[data-key="${CSS.escape(key)}"]`)?.classList.remove("is-held");
      if (!progress.charged) {
        progress.faulted = true;
        stopTimer();
        fault("chord_released_early");
      } else if (progress.held.size === 0) {
        sealField();
      }
    };
    paintStage();
    if (isSimplified()) {
      document.getElementById("chord-proxy-engage")?.addEventListener("click", () => {
        if (progress.faulted || progress.stage >= chords.length || progress.held.size) return;
        clearFreshFailure();
        [...required()].sort().forEach(pressKey);
        document.getElementById("chord-proxy-engage")?.setAttribute("disabled", "disabled");
      });
      document.getElementById("chord-proxy-release")?.addEventListener("click", () => {
        if (!progress.charged) {
          fault("chord_released_early");
          return;
        }
        [...required()].sort().forEach(releaseKey);
      });
    }
    keyDownHandler = (keyEvent) => {
      const key = keyEvent.key.toUpperCase();
      const expected = required();
      if (!expected.has(key) || keyEvent.repeat || progress.held.has(key) || progress.faulted) return;
      keyEvent.preventDefault();
      clearFreshFailure();
      pressKey(key);
    };
    keyUpHandler = (keyEvent) => {
      const key = keyEvent.key.toUpperCase();
      if (!required().has(key) || !progress.held.has(key) || progress.faulted) return;
      keyEvent.preventDefault();
      releaseKey(key);
    };
    if (!isSimplified()) {
      window.addEventListener("keydown", keyDownHandler, true);
      window.addEventListener("keyup", keyUpHandler, true);
    }
  }

  function pointerAngle(element, pointerEvent) {
    const rect = element.getBoundingClientRect();
    return canonicalAngle(Math.atan2(pointerEvent.clientY - (rect.top + rect.height / 2), pointerEvent.clientX - (rect.left + rect.width / 2)) * 180 / Math.PI);
  }

  function canonicalAngle(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 0;
    return ((numeric % 360) + 360) % 360;
  }

  function telemetryAngle(value) {
    // Rounding a valid 359.999... position used to serialize as 360.  The
    // server correctly replays that position as 0, so keep the browser
    // telemetry in the same half-open [0, 360) representation.
    const rounded = Number(canonicalAngle(value).toFixed(3));
    return rounded >= 360 ? 0 : rounded;
  }

  function dialRound(round, stage) {
    const proxy = isSimplified() ? '<div class="gauntlet-proxy-controls"><button type="button" id="dial-proxy-begin">GRIP CALIBRATION</button><button type="button" id="dial-proxy-ccw" disabled>TURN −12°</button><button type="button" id="dial-proxy-cw" disabled>TURN +12°</button><button type="button" id="dial-proxy-release" disabled>RELEASE / COAST</button></div>' : "";
    stage.innerHTML = `<div class="dial-field"><div class="dial-target-label">BRAKE SECTOR <b>${Math.round(round.target_angle)}° ± ${round.target_tolerance}°</b></div><div class="dial-shell"><div class="dial-sector" style="--target:${Number(round.target_angle)}deg;--spread:${Number(round.target_tolerance) * 2}deg"></div><div class="gauntlet-dial" id="gauntlet-dial"><i></i><b>INERTIA</b><span>${isSimplified() ? "PROXY COAST" : "DRAG RIM"}</span></div></div><button type="button" class="dial-brake" id="gauntlet-brake" data-in-zone="false">BRAKE</button><div class="dial-readout"><span>ANGLE <b id="dial-angle">${Math.round(round.start_angle)}°</b></span><span>VELOCITY <b id="dial-velocity">0.0</b></span></div>${proxy}</div>`;
    const dial = document.getElementById("gauntlet-dial");
    const brake = document.getElementById("gauntlet-brake");
    const progress = {dragging: false, angle: canonicalAngle(round.start_angle), lastPointer: 0, velocity: 0, coast: null, moved: 0, proxyAwaitTick: false};
    const angleDistance = () => Math.abs(((canonicalAngle(progress.angle) - canonicalAngle(round.target_angle) + 180) % 360 + 360) % 360 - 180);
    const paint = () => {
      dial.style.transform = `rotate(${canonicalAngle(progress.angle)}deg)`;
      const angleLabel = document.getElementById("dial-angle");
      const velocityLabel = document.getElementById("dial-velocity");
      if (angleLabel) angleLabel.textContent = `${Math.round(canonicalAngle(progress.angle)) % 360}°`;
      if (velocityLabel) velocityLabel.textContent = progress.velocity.toFixed(1);
      brake.dataset.inZone = !progress.proxyAwaitTick && angleDistance() <= Number(round.target_tolerance) ? "true" : "false";
    };
    const beginCoast = () => {
      progress.coast = window.setInterval(() => {
        progress.angle = canonicalAngle(progress.angle + progress.velocity);
        progress.velocity *= Number(round.friction);
        progress.proxyAwaitTick = false;
        event("dial_tick", {angle: telemetryAngle(progress.angle), velocity: Number(progress.velocity.toFixed(3))});
        paint();
      }, Number(round.tick_ms));
      model.timers.push(progress.coast);
    };
    paint();
    const proxyBegin = () => {
      if (progress.dragging || progress.coast) return;
      clearFreshFailure();
      progress.dragging = true;
      progress.velocity = 0;
      progress.moved = 0;
      event("drag_start", {angle: telemetryAngle(progress.angle)});
      document.getElementById("dial-proxy-begin")?.setAttribute("disabled", "disabled");
      document.getElementById("dial-proxy-ccw")?.removeAttribute("disabled");
      document.getElementById("dial-proxy-cw")?.removeAttribute("disabled");
      document.getElementById("dial-proxy-release")?.removeAttribute("disabled");
      helpersCache.setReadout("CALIBRATION GRIPPED · TURN, THEN RELEASE TO COAST", "idle");
    };
    const proxyTurn = (delta) => {
      if (!progress.dragging) return;
      const next = canonicalAngle(progress.angle + delta);
      const actualDelta = (next - progress.angle + 540) % 360 - 180;
      progress.angle = next;
      progress.velocity = Math.max(-18, Math.min(18, actualDelta));
      progress.lastPointer = next;
      progress.moved += 1;
      event("drag_move", {angle: telemetryAngle(next), delta: Number(actualDelta.toFixed(3))});
      paint();
    };
    const proxyRelease = () => {
      if (!progress.dragging) return;
      progress.dragging = false;
      event("drag_end", {angle: telemetryAngle(progress.angle), velocity: Number(progress.velocity.toFixed(3))});
      if (progress.moved < 2 || Math.abs(progress.velocity) < 2.5) {
        fault("insufficient_dial_spin");
        return;
      }
      progress.proxyAwaitTick = true;
      paint();
      beginCoast();
    };
    if (isSimplified()) {
      document.getElementById("dial-proxy-begin")?.addEventListener("click", proxyBegin);
      document.getElementById("dial-proxy-ccw")?.addEventListener("click", () => proxyTurn(-12));
      document.getElementById("dial-proxy-cw")?.addEventListener("click", () => proxyTurn(12));
      document.getElementById("dial-proxy-release")?.addEventListener("click", proxyRelease);
    }
    if (!isSimplified()) dial.addEventListener("pointerdown", (pointerEvent) => {
      clearFreshFailure();
      if (progress.coast) window.clearInterval(progress.coast);
      progress.dragging = true;
      progress.lastPointer = pointerAngle(dial, pointerEvent);
      progress.angle = canonicalAngle(progress.lastPointer);
      progress.velocity = 0;
      progress.moved = 0;
      event("drag_start", {angle: telemetryAngle(progress.angle)});
      dial.setPointerCapture(pointerEvent.pointerId);
      paint();
    });
    if (!isSimplified()) dial.addEventListener("pointermove", (pointerEvent) => {
      if (!progress.dragging) return;
      const next = pointerAngle(dial, pointerEvent);
      const delta = (next - progress.lastPointer + 540) % 360 - 180;
      progress.angle = canonicalAngle(next);
      progress.velocity = Math.max(-18, Math.min(18, delta));
      progress.lastPointer = next;
      progress.moved += 1;
      event("drag_move", {angle: telemetryAngle(next), delta: Number(delta.toFixed(3))});
      paint();
    });
    if (!isSimplified()) dial.addEventListener("pointerup", () => {
      if (!progress.dragging) return;
      progress.dragging = false;
      event("drag_end", {angle: telemetryAngle(progress.angle), velocity: Number(progress.velocity.toFixed(3))});
      if (progress.moved < 2 || Math.abs(progress.velocity) < 2.5) {
        fault("insufficient_dial_spin");
        return;
      }
      beginCoast();
    });
    brake.addEventListener("click", () => {
      if (!progress.coast) {
        fault("brake_before_coast");
        return;
      }
      window.clearInterval(progress.coast);
      progress.coast = null;
      event("brake", {angle: telemetryAngle(progress.angle)});
      if (angleDistance() <= Number(round.target_tolerance)) completeRound();
      else fault("brake_outside_sector");
    });
  }

  function interceptRound(round, stage) {
    const packets = round.packets || [];
    const proxy = isSimplified() ? '<div class="gauntlet-proxy-controls"><button type="button" id="intercept-proxy-arm">ARM SCANNER</button><button type="button" id="intercept-proxy-capture" disabled>CAPTURE ALIGNED PACKET</button></div>' : "";
    stage.innerHTML = `<div class="intercept-field"><div class="intercept-bank">${packets.map((packet, index) => `<i data-packet-mark="${index}">${index + 1}</i>`).join("")}</div><div class="capture-gate"><span>CAPTURE GATE</span></div><div class="intercept-track"><button type="button" class="intercept-target" id="intercept-target" data-in-gate="false"><i></i><b>PK-1</b></button></div>${isSimplified() ? "" : `<button type="button" class="intercept-arm" id="intercept-arm">ARM ${packets.length}-PACKET SCANNER</button>`}<p>${packets.length} SPEEDS / ${packets.length} MOVING GATES / ONE ARM CYCLE</p>${proxy}</div>`;
    const target = document.getElementById("intercept-target");
    const arm = document.getElementById("intercept-arm");
    const gate = stage.querySelector(".capture-gate");
    const progress = {armed: false, packetIndex: 0, position: 8, direction: 1, timer: null, ticks: 0};
    const packet = () => packets[progress.packetIndex];
    const paint = () => {
      const current = packet();
      if (!current) return;
      gate.style.setProperty("--center", `${current.gate_center}%`);
      gate.style.setProperty("--width", `${Number(current.gate_half_width) * 2}%`);
      target.style.left = `${progress.position}%`;
      target.dataset.inGate = Math.abs(progress.position - Number(current.gate_center)) <= Number(current.gate_half_width) ? "true" : "false";
      target.querySelector("b").textContent = current.id;
    };
    paint();
    const armScanner = () => {
      if (progress.armed) return;
      clearFreshFailure();
      progress.armed = true;
      if (arm) arm.disabled = true;
      event("arm");
      progress.timer = window.setInterval(() => {
        const current = packet();
        if (!current) return;
        progress.position += Number(current.speed) * progress.direction;
        if (progress.position >= 92) { progress.position = 92; progress.direction = -1; }
        else if (progress.position <= 8) { progress.position = 8; progress.direction = 1; }
        progress.ticks += 1;
        event("intercept_tick", {packet_index: progress.packetIndex, packet_id: current.id, position: Number(progress.position.toFixed(2)), direction: progress.direction});
        paint();
      }, Number(round.tick_ms));
      model.timers.push(progress.timer);
    };
    const capture = () => {
      if (!progress.armed) { fault("packet_before_arm"); return; }
      const current = packet();
      event("intercept_click", {packet_index: progress.packetIndex, packet_id: current.id, position: Number(progress.position.toFixed(2))});
      if (progress.ticks < 2 || target.dataset.inGate !== "true") { window.clearInterval(progress.timer); fault("packet_outside_gate"); return; }
      stage.querySelector(`[data-packet-mark="${progress.packetIndex}"]`)?.setAttribute("data-status", "captured");
      progress.packetIndex += 1;
      if (progress.packetIndex >= packets.length) { window.clearInterval(progress.timer); completeRound(); return; }
      progress.position = 8;
      progress.direction = 1;
      progress.ticks = 0;
      helpersCache.setReadout(`PACKET ${progress.packetIndex}/${packets.length} CAPTURED · GATE HAS MOVED`, "idle");
      paint();
    };
    if (isSimplified()) {
      document.getElementById("intercept-proxy-arm")?.addEventListener("click", () => {
        armScanner();
        document.getElementById("intercept-proxy-arm")?.setAttribute("disabled", "disabled");
        document.getElementById("intercept-proxy-capture")?.removeAttribute("disabled");
      });
      document.getElementById("intercept-proxy-capture")?.addEventListener("click", capture);
    } else {
      arm.addEventListener("click", armScanner);
      target.addEventListener("click", capture);
    }
  }

  function distanceToSegment(px, py, ax, ay, bx, by) {
    const dx = bx - ax; const dy = by - ay;
    if (!dx && !dy) return Math.hypot(px - ax, py - ay);
    const amount = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
    return Math.hypot(px - (ax + amount * dx), py - (ay + amount * dy));
  }

  function routeRound(round, stage) {
    const points = round.points || [];
    const hoops = points.map((point, index) => isSimplified()
      ? `<button type="button" class="route-hoop route-hoop-select" data-point="${index}" style="--x:${point.x}%;--y:${point.y}%" aria-label="Select hoop ${index + 1}"><b>${index + 1}</b></button>`
      : `<i class="route-hoop" data-point="${index}" style="--x:${point.x}%;--y:${point.y}%"><b>${index + 1}</b></i>`).join("");
    stage.innerHTML = `<div class="route-field"><svg class="route-map" viewBox="0 0 100 100" preserveAspectRatio="none"><polyline class="route-corridor" points="${points.map((point) => `${point.x},${point.y}`).join(" ")}"></polyline><polyline class="route-line" points="${points.map((point) => `${point.x},${point.y}`).join(" ")}"></polyline></svg><div class="route-pad" id="route-pad">${hoops}<button type="button" class="route-capsule" id="route-capsule" style="--x:${points[0].x}%;--y:${points[0].y}%"><i></i></button></div><p>${isSimplified() ? "SELECT THE VISIBLE HOOPS IN ROUTE ORDER" : "HOLD AND DRAG / DO NOT LEAVE THE CORRIDOR"}</p></div>`;
    const pad = document.getElementById("route-pad");
    const capsule = document.getElementById("route-capsule");
    const progress = {dragging: false, checkpoint: 0, failed: false, lastPoint: null};
    // Both surfaces replay a sampled continuous path. Full mode obtains the
    // path from pointer movement; simplified mode asks for the next visible
    // hoop and moves the capsule through the same intervening corridor.
    const sampleSpacing = Math.max(1, Math.min(Number(round.checkpoint_radius), Number(round.corridor_radius)) / 2);
    const coords = (pointerEvent) => {
      const rect = pad.getBoundingClientRect();
      return {x: Math.max(0, Math.min(100, (pointerEvent.clientX - rect.left) / rect.width * 100)), y: Math.max(0, Math.min(100, (pointerEvent.clientY - rect.top) / rect.height * 100))};
    };
    const corridorDistance = (point) => Math.min(...points.slice(0, -1).map((start, index) => distanceToSegment(point.x, point.y, start.x, start.y, points[index + 1].x, points[index + 1].y)));
    const updateCheckpoint = (point) => {
      if (progress.checkpoint < points.length && Math.hypot(point.x - points[progress.checkpoint].x, point.y - points[progress.checkpoint].y) <= Number(round.checkpoint_radius)) {
        pad.querySelector(`[data-point="${progress.checkpoint}"]`)?.classList.add("is-cleared");
        progress.checkpoint += 1;
      }
    };
    const moveCapsule = (point) => {
      capsule.style.setProperty("--x", `${point.x}%`);
      capsule.style.setProperty("--y", `${point.y}%`);
    };
    const recordPathPoint = (point) => {
      moveCapsule(point);
      event("route_move", {x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2))});
      if (corridorDistance(point) > Number(round.corridor_radius)) {
        progress.failed = true;
        progress.dragging = false;
        fault("route_left_corridor");
        return false;
      }
      updateCheckpoint(point);
      return true;
    };
    const traverseSegment = (target) => {
      const start = progress.lastPoint || points[0];
      const distance = Math.hypot(target.x - start.x, target.y - start.y);
      const steps = Math.max(1, Math.ceil(distance / sampleSpacing));
      for (let index = 1; index <= steps; index += 1) {
        const amount = index / steps;
        const point = {x: start.x + (target.x - start.x) * amount, y: start.y + (target.y - start.y) * amount};
        if (!recordPathPoint(point)) return false;
      }
      progress.lastPoint = {x: target.x, y: target.y};
      return true;
    };
    const beginRoute = (point) => {
      progress.dragging = true;
      progress.checkpoint = 0;
      progress.failed = false;
      progress.lastPoint = {x: point.x, y: point.y};
      moveCapsule(point);
      event("route_start", {x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2))});
      if (corridorDistance(point) > Number(round.corridor_radius)) {
        progress.failed = true;
        progress.dragging = false;
        fault("route_left_corridor");
        return false;
      }
      updateCheckpoint(point);
      return true;
    };
    const completeIfFinished = () => {
      if (progress.checkpoint < points.length) return false;
      const last = points[points.length - 1];
      progress.dragging = false;
      event("route_end", {x: Number(last.x.toFixed(2)), y: Number(last.y.toFixed(2))});
      completeRound();
      return true;
    };
    const selectHoop = (index) => {
      if (progress.failed || progress.checkpoint >= points.length) return;
      clearFreshFailure();
      if (index !== progress.checkpoint) {
        fault("route_wrong_hoop");
        return;
      }
      const point = points[index];
      if (!progress.dragging) {
        if (!beginRoute(point)) return;
      } else if (!traverseSegment(point)) {
        return;
      }
      if (!completeIfFinished()) {
        helpersCache.setReadout(`HOOP ${progress.checkpoint}/${points.length} SELECTED · SELECT HOOP ${progress.checkpoint + 1}`, "idle");
      }
    };
    if (isSimplified()) stage.querySelectorAll(".route-hoop-select").forEach((button) => button.addEventListener("click", () => selectHoop(Number(button.dataset.point))));
    if (!isSimplified()) capsule.addEventListener("pointerdown", (pointerEvent) => {
      clearFreshFailure();
      const point = coords(pointerEvent);
      if (Math.hypot(point.x - points[0].x, point.y - points[0].y) > Number(round.checkpoint_radius)) { fault("route_bad_start"); return; }
      if (!beginRoute(point)) return;
      capsule.setPointerCapture(pointerEvent.pointerId);
    });
    if (!isSimplified()) capsule.addEventListener("pointermove", (pointerEvent) => {
      if (!progress.dragging || progress.failed) return;
      const point = coords(pointerEvent);
      traverseSegment(point);
    });
    if (!isSimplified()) capsule.addEventListener("pointerup", (pointerEvent) => {
      if (!progress.dragging || progress.failed) return;
      const point = coords(pointerEvent);
      if (!traverseSegment(point)) return;
      progress.dragging = false;
      event("route_end", {x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2))});
      if (progress.checkpoint === points.length) completeRound();
      else fault("route_incomplete");
    });
  }

  const ROUND_RENDERERS = {pressure: pressureRound, chord: chordRound, dial: dialRound, intercept: interceptRound, route: routeRound};

  function displayedInstruction(round) {
    if (!isSimplified()) return round.instruction;
    const instructions = {
      pressure: "Engage the pressure bank, click the lit pulse sockets in order, then release after the bank is dark.",
      chord: "Engage each displayed pair, hold it through the charge interval, then release the charged pair in order.",
      dial: "Grip calibration, turn the flywheel in visible steps, release it to coast, then brake inside the striped target sector.",
      intercept: "Arm the scanner once, then capture each packet only while it crosses the moving gate.",
      route: "Select each numbered hoop in order. The capsule traverses the same visible route corridor between selected hoops.",
    };
    return instructions[round.type] || round.instruction;
  }

  function renderRound() {
    cleanupRound();
    if (!model || model.roundIndex >= model.state.rounds.length) return;
    const round = currentRound();
    model.roundEvents = [];
    const root = document.querySelector(".gauntlet-reactor");
    if (root) { root.dataset.roundType = round.type; root.dataset.roundId = round.id; }
    const title = document.getElementById("gauntlet-round-title");
    const instruction = document.getElementById("gauntlet-round-instruction");
    const counter = document.getElementById("gauntlet-round-counter");
    if (title) title.textContent = round.title;
    if (instruction) instruction.textContent = displayedInstruction(round);
    if (counter) counter.textContent = `${String(model.roundIndex + 1).padStart(2, "0")} / 05`;
    const stage = document.getElementById("gauntlet-stage");
    ROUND_RENDERERS[round.type](round, stage);
    renderRail();
    helpersCache.setReadout(`ROUND ${model.roundIndex + 1} LIVE · ${round.type.toUpperCase()}`, "idle");
  }

  function renderComplete() {
    cleanupRound();
    const root = document.querySelector(".gauntlet-reactor");
    if (root) root.dataset.roundType = "complete";
    const stage = document.getElementById("gauntlet-stage");
    if (stage) stage.innerHTML = `<div class="gauntlet-complete"><span>FIVE REACTOR SEALS CLOSED</span><strong>${model.energy}</strong><i>STABILITY REMAINS</i></div>`;
    const button = document.getElementById("gauntlet-certify");
    if (button) button.dataset.ready = "true";
    helpersCache.setReadout("ALL FIVE ROUNDS SEALED · CERTIFY REACTOR", "passed");
  }

  async function certify() {
    if (!model || model.submitting || model.terminal) return;
    model.submitting = true;
    cleanupRound();
    document.getElementById("gauntlet-certify")?.setAttribute("disabled", "disabled");
    helpersCache.setReadout("REPLAYING FIVE CONTROL SYSTEMS…", "pending");
    try {
      const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({
        mechanic_id: model.state.mechanic_id,
        task_id: model.state.task_id,
        challenge_id: model.state.challenge_id,
        interaction_mode: interactionMode(),
        round_records: model.roundRecords,
        resource_events: model.resourceEvents,
        final_energy: model.energy,
        completed: true,
      })});
      const outcome = await response.json();
      if (outcome.passed === true) {
        model.terminal = true;
        document.querySelector(".gauntlet-reactor")?.insertAdjacentHTML("beforeend", '<div class="gauntlet-pass-stamp"><span>MIXED-INPUT REACTOR CERTIFIED</span><strong>PASS</strong><i>FIVE SYSTEMS / ONE STABILITY TRACE</i></div>');
        helpersCache.setReadout("PASS", "passed");
      } else if (outcome.passed === false && outcome.state) {
        await helpersCache.render(outcome.state);
        const root = document.querySelector(".gauntlet-reactor");
        if (root) root.dataset.freshFailure = "true";
        root?.insertAdjacentHTML("beforeend", '<div class="gauntlet-fail-stamp"><span>REACTOR TRACE REJECTED</span><strong>FAIL</strong><i>FRESH CORE ISSUED</i></div>');
        helpersCache.setReadout("FAIL · FRESH CORE ISSUED", "error");
      } else {
        model.submitting = false;
        helpersCache.setReadout("FAIL · REPLAY UNAVAILABLE", "error");
      }
    } catch (_error) {
      model.submitting = false;
      helpersCache.setReadout("FAIL · REACTOR LINK OFFLINE", "error");
    }
  }

  async function render(state, helpers) {
    cleanupRound();
    helpersCache = helpers || helpersCache;
    if (!helpersCache) throw new Error("microgame_gauntlet requires runtime helpers");
    document.body.dataset.mechanic = "verification-reactor";
    document.body.dataset.cheatMode = helpersCache.isCheatMode() ? "true" : "false";
    model = {state, roundIndex: 0, energy: Number(state.starting_energy), roundRecords: [], resourceEvents: [], roundEvents: [], timers: [], transitioning: false, submitting: false, terminal: false};
    helpersCache.app.innerHTML = `<section class="gauntlet-reactor" data-challenge-id="${esc(state.challenge_id)}" data-interaction="${esc(interactionMode())}" data-fresh-failure="false" data-round-type="loading">
      <header class="gauntlet-head"><div><span>MIXED-INPUT VERIFICATION REACTOR / ${esc(state.reactor_id)}</span><h1>${esc(state.prompt)}</h1></div><aside><span>SHARED STABILITY</span><div><i id="gauntlet-energy-fill"></i></div><b id="gauntlet-energy-value">100</b></aside></header>
      <main class="gauntlet-main"><aside class="gauntlet-sidebar"><div class="gauntlet-side-title">FIVE SEALED SYSTEMS</div><ol id="gauntlet-round-rail"></ol><button type="button" id="gauntlet-reset">↺ RESET CURRENT ROUND <small>−4 STABILITY</small></button><div class="gauntlet-side-title">RESOURCE TAPE</div><ol id="gauntlet-telemetry"></ol></aside><section class="gauntlet-work"><header><div><span id="gauntlet-round-counter">01 / 05</span><h2 id="gauntlet-round-title"></h2></div><p id="gauntlet-round-instruction"></p></header><div class="gauntlet-stage" id="gauntlet-stage"></div></section></main>
      <footer class="gauntlet-foot"><div class="readout" data-status="idle">REACTOR LIVE · FIVE TRIALS</div><span>${isSimplified() ? "REACTOR PROXIES + TIMING / SHARED RESOURCE" : "POINTER + KEYBOARD + INERTIA / SHARED RESOURCE"}</span><button type="button" id="gauntlet-certify">${esc(state.submit_label || "CERTIFY REACTOR")} →</button></footer>${helpersCache.cheatPanelTemplate()}
    </section>`;
    document.getElementById("gauntlet-reset")?.addEventListener("click", resetRound);
    document.getElementById("gauntlet-certify")?.addEventListener("click", certify);
    renderEnergy(); renderTelemetry(); renderRail(); renderRound(); helpersCache.installCheatPanel();
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.microgame_gauntlet = {rootSelector: ".gauntlet-reactor", render};
})();
