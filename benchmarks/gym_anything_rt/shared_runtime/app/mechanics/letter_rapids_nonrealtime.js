(() => {
  "use strict";

  let model = null;
  let cleanupActive = null;
  const COLORS = ["#21d6b1", "#f2bd55", "#ef6d6a", "#73a8ff", "#c7e66b", "#d98bff", "#55d6ee"];
  const esc = (value) => String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");

  function interactionMode() {
    return model?.state?.control_condition?.interaction || "full";
  }

  function isControlled() {
    return Boolean(model?.state?.control_condition);
  }

  function currentRow(output = model.output) {
    const context = output.length ? output.at(-1) : "^";
    return model.state.probability_rows[context];
  }

  function displayRow(output = model.output) {
    const row = currentRow(output);
    const floor = Number(model.state.simulation.display_band_floor_milli);
    const free = 10000 - floor * row.length;
    const widths = row.map((band) => floor + Math.floor(
      free * (Number(band.end_milli) - Number(band.start_milli)) / 10000
    ));
    let remainder = 10000 - widths.reduce((total, width) => total + width, 0);
    for (let index = 0; remainder > 0; index += 1, remainder -= 1) widths[index] += 1;
    let cursor = 0;
    return row.map((band, index) => {
      const visible = {...band, display_start_milli: cursor, display_end_milli: cursor + widths[index]};
      cursor += widths[index];
      return visible;
    });
  }

  function symbolAt(yMilli, output = model.output) {
    const band = displayRow(output).find((item) => Number(item.display_start_milli) <= yMilli && yMilli < Number(item.display_end_milli));
    return band ? String(band.symbol) : null;
  }

  function flowDelta(xMilli, currentMilli) {
    const sim = model.state.simulation;
    const neutral = Number(sim.neutral_x_milli);
    const dead = Number(sim.dead_zone_half_width_milli);
    const speed = Number(sim.maximum_speed_units_per_second);
    const tickMs = Number(sim.tick_ms);
    const minimum = Math.max(1, Math.floor(speed * tickMs * Number(sim.minimum_flow_milli) * currentMilli / 1000000000));
    const forwardEdge = neutral + dead;
    const reverseEdge = neutral - dead;
    if (xMilli > forwardEdge) {
      const distance = xMilli - forwardEdge;
      const extent = 10000 - forwardEdge;
      return {direction: 1, delta: Math.max(minimum, Math.floor(speed * tickMs * distance * currentMilli / (1000 * extent * 1000)))};
    }
    if (xMilli < reverseEdge) {
      const distance = reverseEdge - xMilli;
      const extent = reverseEdge;
      return {direction: -1, delta: Math.max(minimum, Math.floor(speed * tickMs * distance * currentMilli / (1000 * extent * 1000)))};
    }
    return {direction: 1, delta: minimum};
  }

  function recordPointer(xMilli, yMilli, inputSource) {
    if (!model || model.submitting || model.terminalReason) return;
    const x = Math.max(0, Math.min(10000, Math.round(Number(xMilli))));
    const y = Math.max(0, Math.min(9999, Math.round(Number(yMilli))));
    // A release from the control that submitted the previous failed route can
    // land on the freshly rendered equivalent control.  Ignore coordinate-
    // identical input unconditionally so that this trailing release cannot
    // dismiss the visible failure state or add an event to the new route.
    if (x === model.pointer.x && y === model.pointer.y) return;
    model.pointer = {x, y};
    const event = {seq: model.events.length + 1, tick: model.tick, type: "pointer", x_milli: x, y_milli: y};
    event.input_source = inputSource;
    model.events.push(event);
    // Each deliberate pointer update starts one finite flow segment.  The
    // stable decision state after a commit/rewind does not advance on its own.
    model.segmentActive = true;
    clearFreshFailure();
    updateHud();
  }

  function clearFreshFailure() {
    const root = document.querySelector(".letter-rapids-nonrealtime");
    const wasFresh = root?.hasAttribute("data-fresh-failure");
    root?.removeAttribute("data-fresh-failure");
    root?.querySelector(".rapids-fresh-stamp")?.remove();
    if (wasFresh) model?.helpers.setReadout("READY", "idle");
  }

  function finish(reason) {
    if (model.terminalReason) return;
    model.terminalReason = reason;
    model.helpers.setReadout("CHECKING", "pending");
    updateHud();
    queueMicrotask(submitTerminal);
  }

  function stepSimulation() {
    if (!model || model.terminalReason || !model.segmentActive) return;
    const sim = model.state.simulation;
    const pattern = model.state.current_pattern_milli;
    if (model.tick >= pattern.length) {
      finish("travel_budget");
      return;
    }
    const {direction, delta} = flowDelta(model.pointer.x, Number(pattern[model.tick]));
    if (direction > 0 && delta) {
      const symbol = symbolAt(model.pointer.y);
      if (symbol !== model.selectedSymbol) {
        model.selectedSymbol = symbol;
        model.progress = 0;
      }
      model.rewindProgress = 0;
      model.progress += delta;
      model.travelUsed += delta;
      if (model.progress >= Number(sim.commit_units)) {
        model.output += symbol;
        model.committed += 1;
        model.progress = 0;
        model.selectedSymbol = null;
        model.commitFlash = 8;
        if (model.output === model.state.target) model.pendingReason = "target";
        else model.segmentActive = false;
      }
    } else if (direction < 0 && delta) {
      model.travelUsed += delta;
      let remaining = delta;
      const cancelled = Math.min(model.progress, remaining);
      model.progress -= cancelled;
      remaining -= cancelled;
      if (remaining) model.rewindProgress += remaining;
      while (model.rewindProgress >= Number(sim.commit_units) && model.output.length) {
        model.rewindProgress -= Number(sim.commit_units);
        model.output = model.output.slice(0, -1);
        model.rewound += 1;
        model.selectedSymbol = null;
        model.commitFlash = -8;
        model.segmentActive = false;
      }
      if (model.rewound > Number(sim.maximum_rewound_characters)) model.pendingReason = "rewind_budget";
    }
    if (!model.pendingReason && model.travelUsed >= Number(sim.travel_budget_units)) model.pendingReason = "travel_budget";
    model.tick += 1;
    if (model.commitFlash > 0) model.commitFlash -= 1;
    else if (model.commitFlash < 0) model.commitFlash += 1;
    updateHud();
    if (model.pendingReason) finish(model.pendingReason);
  }

  async function submitTerminal() {
    if (!model || model.submitting || !model.terminalReason) return;
    model.submitting = true;
    const payload = {
      mechanic_id: model.state.mechanic_id,
      task_id: model.state.task_id,
      challenge_id: model.state.challenge_id,
      events: model.events,
      completed: model.terminalReason === "target",
      output: model.output,
      terminal_reason: model.terminalReason,
      terminal_tick: model.tick,
      travel_used_units: model.travelUsed,
      committed_characters: model.committed,
      rewound_characters: model.rewound,
      progress_units: model.progress,
    };
    payload.interaction_mode = interactionMode();
    try {
      const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(payload)});
      const outcome = await response.json();
      if (outcome.passed === true) {
        model.submitting = false;
        document.querySelector(".letter-rapids-nonrealtime")?.setAttribute("data-terminal", "pass");
        document.querySelector(".letter-rapids-nonrealtime")?.insertAdjacentHTML("beforeend", '<div class="rapids-terminal"><strong>PASS</strong></div>');
        model.helpers.setReadout("PASS", "passed");
      } else if (outcome.passed === false && outcome.state) {
        await render(outcome.state, model.helpers, {freshFailure: true});
        model.helpers.setReadout("FAIL", "error");
      } else {
        model.submitting = false;
        model.helpers.setReadout("VERIFICATION LINK UNAVAILABLE", "error");
      }
    } catch (_error) {
      model.submitting = false;
      model.helpers.setReadout("VERIFICATION LINK LOST", "error");
    }
  }

  function printable(symbol) {
    return symbol === " " ? "SP" : symbol.toUpperCase();
  }

  function updateHud() {
    if (!model) return;
    const symbol = symbolAt(model.pointer.y) || "?";
    const flow = flowDelta(model.pointer.x, Number(model.state.current_pattern_milli[Math.min(model.tick, model.state.current_pattern_milli.length - 1)]));
    const sim = model.state.simulation;
    const mode = flow.direction < 0 ? "REWIND" : model.pointer.x <= Number(sim.neutral_x_milli) + Number(sim.dead_zone_half_width_milli) ? "DRIFT" : "ADVANCE";
    const output = document.querySelector(".rapids-output-value");
    if (output) {
      output.textContent = model.output || "—";
      output.dataset.output = model.output;
    }
    const selected = document.querySelector(".rapids-selected-letter");
    if (selected) selected.textContent = printable(symbol);
    const helm = document.querySelector(".rapids-helm-mode");
    if (helm) { helm.textContent = mode; helm.dataset.mode = mode.toLowerCase(); }
    const distance = document.querySelector(".rapids-distance i");
    if (distance) distance.style.width = `${Math.min(100, model.travelUsed / Number(model.state.simulation.travel_budget_units) * 100)}%`;
    const progress = document.querySelector(".rapids-gate-progress i");
    if (progress) progress.style.width = `${Math.min(100, model.progress / Number(model.state.simulation.commit_units) * 100)}%`;
    const current = document.querySelector(".rapids-current-number");
    if (current) current.textContent = `${(Number(model.state.current_pattern_milli[Math.min(model.tick, model.state.current_pattern_milli.length - 1)]) / 1000).toFixed(2)}×`;
    const rewind = document.querySelector(".rapids-rewind-count");
    if (rewind) rewind.textContent = `${model.rewound} / ${model.state.simulation.maximum_rewound_characters}`;
    const aim = document.getElementById("rapids-aim");
    if (aim && Number(aim.value) !== model.pointer.y) aim.value = String(model.pointer.y);
    const proxyFlow = document.getElementById("rapids-flow");
    if (proxyFlow && Number(proxyFlow.value) !== model.pointer.x) proxyFlow.value = String(model.pointer.x);
  }

  function roundedRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, Math.abs(width) / 2, Math.abs(height) / 2);
    ctx.beginPath();
    ctx.roundRect(x, y, width, height, r);
  }

  function drawCanvas() {
    if (!model?.canvas) return;
    const canvas = model.canvas;
    const ctx = model.context;
    const width = canvas.width;
    const height = canvas.height;
    const sim = model.state.simulation;
    const neutralX = Number(sim.neutral_x_milli) / 10000 * width;
    const reverseEdge = (Number(sim.neutral_x_milli) - Number(sim.dead_zone_half_width_milli)) / 10000 * width;
    const forwardEdge = (Number(sim.neutral_x_milli) + Number(sim.dead_zone_half_width_milli)) / 10000 * width;
    const pointerX = model.pointer.x / 10000 * width;
    const pointerY = model.pointer.y / 10000 * height;
    const current = Number(model.state.current_pattern_milli[Math.min(model.tick, model.state.current_pattern_milli.length - 1)]);

    const background = ctx.createLinearGradient(0, 0, width, height);
    background.addColorStop(0, "#08191b");
    background.addColorStop(.52, "#0b2527");
    background.addColorStop(1, "#061416");
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, width, height);

    const row = displayRow();
    const active = symbolAt(model.pointer.y);
    row.forEach((band, index) => {
      const y0 = Number(band.display_start_milli) / 10000 * height;
      const y1 = Number(band.display_end_milli) / 10000 * height;
      const selected = band.symbol === active;
      ctx.fillStyle = COLORS[index % COLORS.length] + (selected ? "45" : "1b");
      ctx.fillRect(0, y0, width, Math.max(1, y1 - y0));
      ctx.strokeStyle = selected ? COLORS[index % COLORS.length] + "d8" : "rgba(209,247,237,.17)";
      ctx.lineWidth = selected ? 2 : 1;
      ctx.beginPath(); ctx.moveTo(0, y0 + .5); ctx.lineTo(width, y0 + .5); ctx.stroke();
      const bandHeight = y1 - y0;
      if (bandHeight >= 7) {
        ctx.fillStyle = selected ? "#f7fff8" : "rgba(224,249,242,.72)";
        ctx.font = `${bandHeight < 13 ? 8 : bandHeight < 21 ? 10 : 13}px ui-monospace, SFMono-Regular, Menlo, monospace`;
        ctx.textBaseline = "middle";
        ctx.fillText(printable(band.symbol), forwardEdge + 10, (y0 + y1) / 2);
      }
    });

    const activeBand = row.find((band) => band.symbol === active);
    if (activeBand) {
      const y0 = Number(activeBand.display_start_milli) / 10000 * height;
      const y1 = Number(activeBand.display_end_milli) / 10000 * height;
      const front = forwardEdge + (1 - model.progress / Number(sim.commit_units)) * (width - forwardEdge);
      const glow = ctx.createLinearGradient(front, 0, width, 0);
      glow.addColorStop(0, "rgba(255,255,255,.06)");
      glow.addColorStop(1, "rgba(255,255,255,.20)");
      ctx.fillStyle = glow;
      ctx.fillRect(front, y0, width - front, y1 - y0);
      ctx.strokeStyle = "rgba(255,255,255,.92)";
      ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(front, y0); ctx.lineTo(front, y1); ctx.stroke();
      if (y1 - y0 > 30) {
        const previewRow = model.state.probability_rows[active];
        previewRow.forEach((child, index) => {
          const cy0 = y0 + Number(child.start_milli) / 10000 * (y1 - y0);
          const cy1 = y0 + Number(child.end_milli) / 10000 * (y1 - y0);
          ctx.fillStyle = COLORS[(index + 2) % COLORS.length] + "25";
          ctx.fillRect(width * .76, cy0, width * .24, Math.max(1, cy1 - cy0));
          ctx.strokeStyle = "rgba(255,255,255,.13)";
          ctx.strokeRect(width * .76, cy0, width * .24, Math.max(1, cy1 - cy0));
          if (cy1 - cy0 >= 9) {
            ctx.fillStyle = "rgba(255,255,255,.68)";
            ctx.font = "8px ui-monospace, SFMono-Regular, Menlo, monospace";
            ctx.fillText(printable(child.symbol), width * .77, (cy0 + cy1) / 2);
          }
        });
      }
    }

    ctx.fillStyle = "rgba(238,88,85,.11)";
    ctx.fillRect(0, 0, reverseEdge, height);
    ctx.fillStyle = "rgba(250,222,150,.10)";
    ctx.fillRect(reverseEdge, 0, forwardEdge - reverseEdge, height);
    ctx.save();
    ctx.beginPath(); ctx.rect(reverseEdge, 0, forwardEdge - reverseEdge, height); ctx.clip();
    ctx.strokeStyle = "rgba(255,225,166,.16)"; ctx.lineWidth = 8;
    for (let x = reverseEdge - height; x < forwardEdge + height; x += 20) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x + height, height); ctx.stroke();
    }
    ctx.restore();
    ctx.strokeStyle = "rgba(255,225,166,.85)"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(reverseEdge, 0); ctx.lineTo(reverseEdge, height); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(forwardEdge, 0); ctx.lineTo(forwardEdge, height); ctx.stroke();
    ctx.strokeStyle = "rgba(255,255,255,.28)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(neutralX, 0); ctx.lineTo(neutralX, height); ctx.stroke();

    const particleSpeed = .8 + current / 850;
    ctx.fillStyle = "rgba(194,255,241,.30)";
    for (let index = 0; index < 34; index += 1) {
      const phase = (model.tick * particleSpeed * 5 + index * 79) % (width + 90);
      const x = width + 25 - phase;
      const y = (index * 137 + 31) % height;
      ctx.fillRect(x, y, 18 + (index % 4) * 8, 1);
    }

    ctx.fillStyle = "rgba(5,13,14,.82)";
    roundedRect(ctx, 10, 11, 118, 25, 4); ctx.fill();
    ctx.font = "700 10px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.fillStyle = "#ef7a75"; ctx.fillText("← REWIND", 20, 24);
    ctx.fillStyle = "#f2cf7c"; ctx.fillText("DRIFT", reverseEdge + 10, 24);
    ctx.fillStyle = "#72e5ca"; ctx.fillText("ADVANCE →", forwardEdge + 10, 24);

    ctx.save();
    ctx.translate(pointerX, pointerY);
    ctx.strokeStyle = "#ffffff";
    ctx.fillStyle = "rgba(7,18,19,.72)";
    ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(117,239,216,.8)";
    ctx.shadowBlur = 9;
    ctx.beginPath(); ctx.arc(0, 0, 10, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(-17, 0); ctx.lineTo(-6, 0); ctx.moveTo(6, 0); ctx.lineTo(17, 0); ctx.moveTo(0, -17); ctx.lineTo(0, -6); ctx.moveTo(0, 6); ctx.lineTo(0, 17); ctx.stroke();
    ctx.restore();

    model.raf = requestAnimationFrame(drawCanvas);
  }

  function animationLoop() {
    if (!model) return;
    const now = model.helpers.interactionNow();
    if (model.lastClock == null) model.lastClock = now;
    const elapsed = Math.max(0, now - model.lastClock);
    model.lastClock = now;
    model.accumulator += elapsed;
    while (model.accumulator >= Number(model.state.simulation.tick_ms) && !model.terminalReason) {
      model.accumulator -= Number(model.state.simulation.tick_ms);
      stepSimulation();
    }
    model.loopRaf = requestAnimationFrame(animationLoop);
  }

  function bindFullPointer() {
    const canvas = model.canvas;
    const update = (event) => {
      const rect = canvas.getBoundingClientRect();
      recordPointer((event.clientX - rect.left) / rect.width * 10000, (event.clientY - rect.top) / rect.height * 10000, "canyon_pointer");
    };
    canvas.addEventListener("pointermove", update);
  }

  function bindSimplifiedPointer() {
    const aim = document.getElementById("rapids-aim");
    const flow = document.getElementById("rapids-flow");
    aim.addEventListener("input", () => recordPointer(model.pointer.x, Number(aim.value), "axis_proxy"));
    flow.addEventListener("input", () => recordPointer(Number(flow.value), model.pointer.y, "axis_proxy"));
  }

  async function render(state, helpers, options = {}) {
    if (cleanupActive) cleanupActive();
    document.body.dataset.mechanic = "letter-rapids-nonrealtime";
    document.body.dataset.cheatMode = helpers.isCheatMode() ? "true" : "false";
    const interaction = state.control_condition?.interaction || "full";
    const sim = state.simulation;
    model = {
      state, helpers, events: [], tick: 0, accumulator: 0, lastClock: null,
      pointer: {x: Number(sim.neutral_x_milli), y: 5000},
      output: "", selectedSymbol: null, progress: 0, rewindProgress: 0,
      travelUsed: 0, committed: 0, rewound: 0, pendingReason: null,
      terminalReason: null, submitting: false, commitFlash: 0, segmentActive: false,
      canvas: null, context: null, raf: 0, loopRaf: 0,
    };
    window.letterRapidsNonrealtimeModel = model;
    const controlPanel = interaction === "simplified" ? `
      <section class="rapids-proxy" aria-label="simplified pointer controls">
        <label for="rapids-flow"><span>FLOW</span></label>
        <input id="rapids-flow" type="range" min="0" max="10000" step="1" value="${Number(sim.neutral_x_milli)}" aria-label="flow position">
        <div class="rapids-flow-poles" aria-hidden="true"><span>←</span><i></i><span>→</span></div>
      </section>` : "";
    const aimRail = interaction === "simplified" ? `
      <div class="rapids-aim-rail">
        <label for="rapids-aim">LETTER</label>
        <input id="rapids-aim" type="range" min="0" max="9999" step="1" value="5000" aria-label="letter position">
      </div>` : "";
    helpers.app.innerHTML = `
      <section class="letter-rapids-nonrealtime" data-challenge-id="${esc(state.challenge_id)}" data-interaction="${esc(interaction)}" ${options.freshFailure ? 'data-fresh-failure="true"' : ""}>
        ${options.freshFailure ? '<div class="rapids-fresh-stamp"><b>FAIL</b></div>' : ""}
        <header class="rapids-head">
          <div><span>FLOOD CONTROL / LETTER LOCK 04</span><h1>LETTER RAPIDS</h1><p>${esc(state.prompt)}</p></div>
          <section class="rapids-target"><small>TARGET PHRASE</small><div>${[...state.target].map((symbol) => `<b class="rapids-target-char">${esc(printable(symbol))}</b>`).join("")}</div></section>
          <div class="rapids-live"><i></i><span>HELD BETWEEN INPUTS</span></div>
        </header>
        <main class="rapids-main">
          <section class="rapids-canyon-shell"><canvas id="rapids-canvas" width="920" height="450" aria-label="flowing probability-sized letter canyon"></canvas><div class="rapids-glass"></div>${aimRail}</section>
          <aside class="rapids-console">
            <section class="rapids-selection"><small>SELECTED CHANNEL</small><strong class="rapids-selected-letter">?</strong></section>
            <section class="rapids-output"><small>LOCK OUTPUT</small><b class="rapids-output-value" data-output="">—</b></section>
            <section class="rapids-instrument"><div><span>HELM</span><b class="rapids-helm-mode" data-mode="drift">DRIFT</b></div><div><span>CURRENT</span><b class="rapids-current-number">1.00×</b></div></section>
            <section class="rapids-meter"><header><span>TRAVEL LEDGER</span><b>LIMIT</b></header><em class="rapids-distance"><i></i></em></section>
            <section class="rapids-rewind"><span>CHARACTER REWINDS</span><b class="rapids-rewind-count">0 / ${Number(sim.maximum_rewound_characters)}</b></section>
            ${controlPanel}
          </aside>
        </main>
        <footer class="rapids-foot"><div class="readout" data-status="idle">READY</div></footer>
        ${helpers.cheatPanelTemplate()}
      </section>`;
    model.canvas = document.getElementById("rapids-canvas");
    model.context = model.canvas.getContext("2d");
    if (interaction === "simplified") bindSimplifiedPointer(); else bindFullPointer();
    helpers.installCheatPanel();
    updateHud();
    model.raf = requestAnimationFrame(drawCanvas);
    model.loopRaf = requestAnimationFrame(animationLoop);
    cleanupActive = () => {
      if (model?.raf) cancelAnimationFrame(model.raf);
      if (model?.loopRaf) cancelAnimationFrame(model.loopRaf);
    };
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.letter_rapids_nonrealtime = {rootSelector: ".letter-rapids-nonrealtime", render};
})();
