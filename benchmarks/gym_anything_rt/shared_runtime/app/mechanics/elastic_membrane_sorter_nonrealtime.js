(() => {
  "use strict";

  const registry = {};
  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const round = (value, places = 3) => Math.round(Number(value) * 10 ** places) / 10 ** places;
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const angleError = (a, b, period = 360) => Math.abs((((a - b) % period) + period + period / 2) % period - period / 2);
  const event = (model, type, details = {}) => {
    const item = {seq: model.events.length + 1, type, ...details};
    model.events.push(item);
    return item;
  };
  const shell = (state, eyebrow, title, instruction, body, controls = "") => `
    <section class="ivv ivv-${esc(state.mechanic_id.replaceAll("_", "-"))}" data-interaction="${esc(state.control_condition?.interaction || "")}" data-challenge-id="${esc(state.challenge_id)}">
      <header class="ivv-head"><div><span>${esc(eyebrow)}</span><h1>${esc(title)}</h1></div><p>${esc(instruction)}</p></header>
      <main class="ivv-stage">${body}<aside class="ivv-console">${controls}</aside></main>
      <footer class="ivv-foot"><span>${esc(state.challenge_id.toUpperCase())} · LOCAL PHYSICAL TRIAL</span><div class="readout" data-status="idle">READY</div></footer>
    </section>`;
  const verdict = (kind, title, note) => `<div class="ivv-verdict is-${kind}"><strong>${esc(title)}</strong><span>${esc(note)}</span></div>`;
  const setMessage = (model, message, status = "idle") => { if (model.terminal && message !== "PASS") return; model.helpers.setReadout(message, status); };

  async function submit(model, payload, passTitle, passNote) {
    if (model.submitting || model.terminal) return;
    model.submitting = true;
    setMessage(model, "INDEPENDENT REPLAY IN PROGRESS…", "pending");
    try {
      const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(payload)});
      const result = await response.json();
      if (result.passed === true) {
        model.terminal = true;
        document.querySelector(".ivv")?.insertAdjacentHTML("beforeend", verdict("pass", passTitle || "PASS", passNote || "PHYSICAL TRANSCRIPT ACCEPTED"));
        setMessage(model, "PASS", "passed");
      } else if (result.passed === false && result.state) {
        await model.helpers.render(result.state);
        const root = document.querySelector(".ivv");
        root?.insertAdjacentHTML("beforeend", verdict("fresh", "FAIL · FRESH TRIAL", result.feedback || "THE FAILED WORLD WAS REPLACED"));
        setTimeout(() => document.querySelector(".ivv-verdict.is-fresh")?.remove(), 1800);
        document.querySelector(".readout")?.setAttribute("data-status", "error");
      } else {
        model.submitting = false;
        setMessage(model, `FAIL · ${result.feedback || result.error || "NO AUTHORITATIVE GRADE"}`, "error");
      }
    } catch (error) {
      model.submitting = false;
      setMessage(model, `FAIL · VERIFIER OFFLINE · ${error.message}`, "error");
    }
  }

  function membraneForce(heights, accel) { const left = (heights[0] + heights[2]) / 2, right = (heights[1] + heights[3]) / 2, top = (heights[0] + heights[1]) / 2, bottom = (heights[2] + heights[3]) / 2; return {x: (left - right) * Number(accel), y: (top - bottom) * Number(accel)}; }
  registry.elastic_membrane_sorter_nonrealtime = async (state, helpers) => {
    document.body.dataset.mechanic = "elastic-membrane-sorter";
    const interaction = state.control_condition?.interaction || "simplified";
    const actionTicks = Number(state.physics.action_ticks);
    const model = {state, helpers, interaction, events: [], roundIndex: 0, heights: [...state.rounds[0].post_heights], ball: {x: 450, y: 230, vx: 0, vy: 0}, running: false, checkpoint: 0, captured: [], terminal: false, submitting: false, ticks: 0, elapsedTicks: 0, postDrag: null, falls: 0};
    const effectiveHeights = () => model.heights.map((height) => clamp(height,0,1));
    window.elasticMembraneSorterNonrealtimeModel = model;
    const sliderControls = `<div class="membrane-sliders">${[0, 1, 2, 3].map((index) => `<label>P${index + 1}<input data-post="${index}" type="range" min="0" max="100" value="50"><span id="post-value-${index}">.50</span></label>`).join("")}</div>`;
    const directControls = `<p class="membrane-direct-note">DRAG A GLOWING POST MARKER UP OR DOWN ON THE MEMBRANE. ITS TRACK AND POSITION SHOW THE CURRENT TENSION.</p>`;
    helpers.app.innerHTML = shell(
      state,
      "SOFT-MATTER SORTING OFFICE",
      "ELASTIC MEMBRANE SORTER",
      "Release the first marble, then steer through the numbered rings and matching wells. Keep the marbles away from the open edges.",
      `<canvas id="membrane-canvas" width="900" height="480"></canvas>`,
      `<h2>LIVE TENSION POSTS</h2><p>${interaction === "simplified" ? "Use the labelled tension sliders; each deliberate correction advances one finite motion segment." : "Use direct membrane-post dragging; each deliberate correction advances one finite motion segment."} Momentum persists after every correction.</p><p class="membrane-drift-note">The glowing posts show the current tension. Move them when a correction is needed; the marble and posts hold their state between corrections. Resets and new marbles roll immediately.</p>${interaction === "simplified" ? sliderControls : directControls}<button id="membrane-release" class="ivv-primary">RELEASE FIRST MARBLE</button><button id="membrane-reset">RESTART THIS MARBLE</button><button id="membrane-abandon" class="ivv-danger">CUT MEMBRANE / FRESH SORT</button>`,
    );
    const canvas = document.getElementById("membrane-canvas");
    const current = () => state.rounds[model.roundIndex];
    const postMarker = (index) => {
      const point = state.post_positions[index];
      return {x: point[0], y: clamp(point[1] + (.5 - effectiveHeights()[index]) * 80, 14, 466)};
    };
    const syncPostControl = (index) => {
      const input = document.querySelector(`[data-post="${index}"]`);
      if (input) input.value = String(Math.round(model.heights[index] * 100));
      const label = document.getElementById(`post-value-${index}`);
      if (label) label.textContent = model.heights[index].toFixed(2);
    };
    const setPost = (index, value, inputSource, gesture = {}) => {
      if (model.terminal || ![0, 1, 2, 3].includes(index)) return;
      const before = model.heights[index];
      const after = round(clamp(Number(value), 0, 1), 2);
      if (after === before) return;
      model.heights[index] = after;
      event(model, "post", {round_id: current().id, tick: model.ticks, post: index, before: round(before, 2), after, input_source: inputSource, ...gesture});
      syncPostControl(index);
      if (model.running) advanceAfterPost();
      draw();
    };
    const resetRound = () => {
      model.elapsedTicks += model.ticks;
      model.running = false;
      model.postDrag = null;
      model.heights = [...current().post_heights];
      model.ball = {x: 450, y: 230, vx: 0, vy: 0};
      model.ticks = 0;
      model.checkpoint = 0;
      model.heights.forEach((_value, index) => syncPostControl(index));
      draw();
    };
    const draw = () => {
      const ctx = canvas.getContext("2d"), target = current().target_well;
      const actualHeights = effectiveHeights();
      ctx.fillStyle = "#100e1d";
      ctx.fillRect(0, 0, 900, 480);
      for (let y = 0; y <= 12; y++) {
        ctx.beginPath();
        for (let x = 0; x <= 20; x++) {
          const px = x / 20 * 760 + 70, py = y / 12 * 370 + 55, u = x / 20, v = y / 12;
          const h = (1 - u) * (1 - v) * actualHeights[0] + u * (1 - v) * actualHeights[1] + (1 - u) * v * actualHeights[2] + u * v * actualHeights[3];
          const wave = (h - .5) * 42;
          if (x === 0) ctx.moveTo(px, py - wave); else ctx.lineTo(px, py - wave);
        }
        ctx.strokeStyle = "rgba(145,117,255,.26)";
        ctx.stroke();
      }
      current().wells.forEach((well, index) => {
        ctx.beginPath(); ctx.arc(well[0], well[1], state.physics.well_radius, 0, Math.PI * 2);
        ctx.strokeStyle = index === target ? "#d8ff5b" : "#49435f"; ctx.lineWidth = index === target ? 5 : 2; ctx.stroke();
      });
      current().checkpoints.forEach((point, index) => {
        ctx.strokeStyle = index < model.checkpoint ? "#70d79f" : index === model.checkpoint ? "#ffcf63" : "#6e6685";
        ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(point[0], point[1], state.physics.checkpoint_radius, 0, Math.PI * 2); ctx.stroke();
        ctx.fillStyle = ctx.strokeStyle; ctx.font = "900 14px Courier New"; ctx.fillText(String(index + 1), point[0] - 4, point[1] + 5);
      });
      state.post_positions.forEach((point, index) => {
        const marker = postMarker(index);
        ctx.strokeStyle = "rgba(230,220,255,.36)"; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(point[0], point[1] - 40); ctx.lineTo(point[0], point[1] + 40); ctx.stroke();
        ctx.fillStyle = "rgba(11,7,22,.84)"; ctx.fillRect(point[0] - 16, point[1] - 5, 32, 10);
        ctx.fillStyle = `hsl(${220 + actualHeights[index] * 90} 70% 62%)`; ctx.beginPath(); ctx.arc(marker.x, marker.y, 13, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "#f5edff"; ctx.lineWidth = 2; ctx.stroke(); ctx.fillStyle = "#f5edff"; ctx.font = "800 9px Courier New"; ctx.fillText(`P${index + 1}`, point[0] - 7, point[1] + 4);
      });
      ctx.fillStyle = "#ffcf63"; ctx.beginPath(); ctx.arc(model.ball.x, model.ball.y, 14, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#c885b1"; ctx.lineWidth=2; ctx.setLineDash([7,5]); ctx.strokeRect(14,14,872,452); ctx.setLineDash([]);
      ctx.fillStyle="#100e1d"; ctx.fillRect(200,12,520,17); ctx.fillRect(200,462,440,18);
      ctx.fillStyle = "#e8e1ff"; ctx.font = "800 11px Courier New";
      ctx.fillText(`MARBLE ${model.roundIndex + 1}/${state.rounds.length} · RINGS ${model.checkpoint}/${current().checkpoints.length} · SPEED ${Math.hypot(model.ball.vx, model.ball.vy).toFixed(2)} · TICK ${model.ticks}/${state.physics.max_ticks}`, 200, 24);
      ctx.fillText(`FALLS ${model.falls} · CAPTURE SPEED ≤ ${state.physics.capture_speed}`,200,474);
    };
    const advanceAfterPost = () => {
      for (let step = 0; step < actionTicks && model.running; step += 1) {
        const force = membraneForce(effectiveHeights(), state.physics.slope_accel);
        model.ball.vx = (model.ball.vx + force.x) * state.physics.drag;
        model.ball.vy = (model.ball.vy + force.y) * state.physics.drag;
        model.ball.x += model.ball.vx; model.ball.y += model.ball.vy;
        model.ticks += 1;
        if (model.ball.x < 28 || model.ball.x > 872 || model.ball.y < 28 || model.ball.y > 452) {
          event(model,"fall",{round_id:current().id,tick:model.ticks,ball:copy(model.ball)});
          model.falls += 1;
          resetRound(); release();
          setMessage(model,"MARBLE FELL / COURSE RESTARTED","error");
          return;
        }
        const checkpoint = current().checkpoints[model.checkpoint];
        if (checkpoint && Math.hypot(model.ball.x - checkpoint[0], model.ball.y - checkpoint[1]) <= state.physics.checkpoint_radius) {
          model.checkpoint += 1;
          event(model, "checkpoint", {round_id: current().id, tick: model.ticks, index: model.checkpoint - 1, ball: {x: round(model.ball.x), y: round(model.ball.y), vx: round(model.ball.vx), vy: round(model.ball.vy)}});
          setMessage(model, `INSPECTION RING ${model.checkpoint}/${current().checkpoints.length} CLEARED · KEEP STEERING`, "passed");
        }
        const well = current().wells[current().target_well], distance = Math.hypot(model.ball.x - well[0], model.ball.y - well[1]), speed = Math.hypot(model.ball.vx, model.ball.vy);
        if (model.checkpoint === current().checkpoints.length && distance < state.physics.well_radius && speed <= state.physics.capture_speed) {
          model.running = false; model.captured.push(current().id);
          event(model, "capture", {round_id: current().id, tick: model.ticks, well: current().target_well, checkpoints: model.checkpoint, speed: round(speed), ball: {x: round(model.ball.x), y: round(model.ball.y), vx: round(model.ball.vx), vy: round(model.ball.vy)}, heights: model.heights.map((value) => round(value, 2))});
          if (model.roundIndex < state.rounds.length - 1) { model.roundIndex += 1; resetRound(); release(); setMessage(model, "MARBLE CAPTURED · NEXT MARBLE READY", "passed"); }
          else void submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "MEMBRANE SORT AUTHENTICATED", "FIXED POSTS · ORDERED RINGS · DAMPED CAPTURE");
          return;
        }
        if (model.ticks >= state.physics.max_ticks) {
          event(model, "stall", {round_id: current().id, tick: model.ticks, ball: copy(model.ball), checkpoints: model.checkpoint});
          resetRound(); release();
          setMessage(model, "COURSE LIMIT / MARBLE RESTARTED", "error");
          return;
        }
      }
      draw();
    };
    const release = () => {
      if (model.running || model.terminal) return;
      model.running = true;
      document.getElementById("membrane-release").disabled = true;
      event(model, "release", {round_id: current().id, tick: model.ticks, heights: model.heights.map((value) => round(value, 2))});
      draw();
    };
    document.querySelectorAll("[data-post]").forEach((input) => input.addEventListener("input", () => setPost(Number(input.dataset.post), Number(input.value) / 100, "tension_slider")));
    const canvasPoint = (pointerEvent) => { const box = canvas.getBoundingClientRect(); return {x: (pointerEvent.clientX - box.left) / box.width * 900, y: (pointerEvent.clientY - box.top) / box.height * 480}; };
    canvas.addEventListener("pointerdown", (pointerEvent) => {
      if (interaction !== "full" || model.terminal || model.postDrag) return;
      const point = canvasPoint(pointerEvent);
      const index = [0, 1, 2, 3].find((candidate) => { const marker = postMarker(candidate); return Math.hypot(point.x - marker.x, point.y - marker.y) <= 20; });
      if (index === undefined) return;
      model.postDrag = {index, pointerId: pointerEvent.pointerId, startHeight: model.heights[index], start: point};
      canvas.setPointerCapture(pointerEvent.pointerId); pointerEvent.preventDefault();
    });
    canvas.addEventListener("pointermove", (pointerEvent) => {
      const drag = model.postDrag;
      if (!drag || drag.pointerId !== pointerEvent.pointerId) return;
      const point = canvasPoint(pointerEvent), anchor = state.post_positions[drag.index];
      setPost(drag.index, .5 + (anchor[1] - point.y) / 80, "membrane_post_drag");
      pointerEvent.preventDefault();
    });
    const finishPostDrag = (pointerEvent) => {
      const drag = model.postDrag;
      if (!drag || drag.pointerId !== pointerEvent.pointerId) return;
      model.postDrag = null;
      try { canvas.releasePointerCapture(pointerEvent.pointerId); } catch (_error) {}
      pointerEvent.preventDefault();
    };
    canvas.addEventListener("pointerup", finishPostDrag);
    canvas.addEventListener("pointercancel", finishPostDrag);
    document.getElementById("membrane-release").addEventListener("click", release);
    document.getElementById("membrane-reset").addEventListener("click", () => { if(model.terminal)return; event(model, "reset", {round_id: current().id, tick: model.ticks}); resetRound(); release(); });
    document.getElementById("membrane-abandon").addEventListener("click", () => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", ""));

    resetRound();
  };
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.elastic_membrane_sorter_nonrealtime = {
    rootSelector: ".ivv-elastic-membrane-sorter-nonrealtime",
    render: (state, helpers) => {
      const previous = window.elasticMembraneSorterNonrealtimeModel;
      if (previous) previous.terminal = true;
      return registry.elastic_membrane_sorter_nonrealtime(state, helpers);
    },
  };
})();
