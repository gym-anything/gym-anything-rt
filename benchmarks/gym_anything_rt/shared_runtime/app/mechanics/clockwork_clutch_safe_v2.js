(() => {
  "use strict";

  // Clockwork Clutch Safe V2: additive, self-contained browser mechanic.
  // Does not import or modify `_interaction_vii_viii.js` (the V1 shared
  // bundle); every helper this render function needs is defined locally.
  // Registered directly on `window.GymAnythingRTMechanics`, which is the
  // same generic per-mechanic-id discovery path app.js already uses for
  // every other mechanic (see `renderExternalMechanic` in app.js).

  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const round = (value, places = 3) => Math.round(Number(value) * 10 ** places) / 10 ** places;
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const angleError = (a, b, period = 360) => Math.abs((((a - b) % period) + period + period / 2) % period - period / 2);

  // Same smootherstep-interpolated wobble curve as the Python generator
  // (`_wobble_at`) and grader. Pure arithmetic over the anchor list already
  // present in `state.physics.wobble_anchors`; no independent randomness is
  // drawn in the browser, so the server replay reproduces this exactly.
  const wobbleAt = (tick, anchors) => {
    if (!anchors.length) return 1;
    if (tick <= anchors[0].tick) return anchors[0].mult;
    for (let index = 0; index < anchors.length - 1; index += 1) {
      const first = anchors[index];
      const second = anchors[index + 1];
      if (first.tick <= tick && tick <= second.tick) {
        const span = second.tick - first.tick;
        const t = span <= 0 ? 0 : (tick - first.tick) / span;
        const eased = t * t * t * (t * (t * 6 - 15) + 10);
        return first.mult + (second.mult - first.mult) * eased;
      }
    }
    return anchors[anchors.length - 1].mult;
  };

  const event = (model, type, details = {}) => {
    const item = {seq: model.events.length + 1, type, ...details};
    model.events.push(item);
    return item;
  };

  const shell = (state, eyebrow, title, instruction, body, controls = "") => `
    <section class="ivv2 ivv2-clockwork-clutch-safe-v2" data-interaction="${esc(state.control_condition?.interaction || "")}" data-challenge-id="${esc(state.challenge_id)}">
      <header class="ivv2-head"><div><span>${esc(eyebrow)}</span><h1>${esc(title)}</h1></div><p>${esc(instruction)}</p></header>
      <main class="ivv2-stage">${body}<aside class="ivv2-console">${controls}</aside></main>
      <footer class="ivv2-foot"><span>${esc(state.challenge_id.toUpperCase())} · LOCAL PHYSICAL TRIAL</span><div class="readout" data-status="idle">READY</div></footer>
    </section>`;
  const verdict = (kind, title, note) => `<div class="ivv2-verdict is-${kind}"><strong>${esc(title)}</strong><span>${esc(note)}</span></div>`;
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
        document.querySelector(".ivv2")?.insertAdjacentHTML("beforeend", verdict("pass", passTitle || "PASS", passNote || "PHYSICAL TRANSCRIPT ACCEPTED"));
        setMessage(model, "PASS", "passed");
      } else if (result.passed === false && result.state) {
        await model.helpers.render(result.state);
        const root = document.querySelector(".ivv2");
        root?.insertAdjacentHTML("beforeend", verdict("fresh", "FAIL · FRESH TRIAL", result.feedback || "THE FAILED WORLD WAS REPLACED"));
        setTimeout(() => document.querySelector(".ivv2-verdict.is-fresh")?.remove(), 1800);
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

  async function render(state, helpers) {
    document.body.dataset.mechanic = "clockwork-clutch-safe-v2";
    const interaction = state.control_condition?.interaction || "simplified";
    const model = {state, helpers, interaction, events: [], shafts: copy(state.shafts), tick: 0, running: false, terminal: false, submitting: false, interval: null, clutchDrag: null};
    const anchors = state.physics.wobble_anchors;
    const showAngleReadout = state.physics.show_angle_readout !== false;
    const showSpeedReadout = state.physics.show_speed_readout !== false;
    const reengagementAllowed = state.physics.reengagement_allowed !== false;
    const shaftCountWord = ({1: "one", 2: "two", 3: "three", 4: "four"})[state.shafts.length] || String(state.shafts.length);
    window.clockworkClutchSafeV2Model = model;
    const clutchControl = (shaft, index) => interaction === "simplified"
      ? `<button data-clutch="${index}">RELEASE ${esc(shaft.id.toUpperCase())}</button>`
      : `<div class="clutch-lever" data-clutch-lever="${index}" data-state="coupled" aria-label="${esc(shaft.id)} clutch lever: coupled">
          <span>COUPLED</span><div class="clutch-lever-rail"><i class="clutch-lever-handle"></i></div><span>FREE</span>
        </div>`;
    helpers.app.innerHTML = shell(
      state, "HOROLOGICAL CRIME UNIT", "CLOCKWORK CLUTCH SAFE V2",
      `Release ${shaftCountWord} ${state.shafts.length === 1 ? "seal" : "seals"} at the witness mark. Every clutch change redistributes load, and the master drive's own speed wobbles smoothly and irregularly, so keep watching each gear.`,
      `<div class="clutch-bank">${state.shafts.map((shaft, index) => `<article><canvas id="clutch2-${index}" width="230" height="230"></canvas>${clutchControl(shaft, index)}</article>`).join("")}</div>`,
      `<h2>WOBBLING MASTER DRIVE</h2><p>Fewer engaged shafts run faster. The drive's own tempo is not constant either. ${reengagementAllowed ? "Re-engagement is legal for recovery." : "Released clutches are irreversible in this trial."} Once started, the drive cannot be stopped. TRY SAFE checks alignment while the drive continues. Complete the trial before the wind limit.</p><button id="clutch2-drive" class="ivv2-primary">START DRIVE</button><button id="clutch2-unlock">TRY SAFE</button><div id="clutch2-tick" class="ivv2-telemetry"></div><button id="clutch2-abandon" class="ivv2-danger">BREAK TRAIN / FRESH SAFE</button>`,
    );
    const speeds = () => {
      const active = model.shafts.filter((shaft) => shaft.engaged).length;
      const factor = active ? Number(state.physics.load_numerator) / active : 0;
      const wobble = wobbleAt(model.tick, anchors);
      return model.shafts.map((shaft) => shaft.engaged ? Number(shaft.ratio) * Number(state.physics.drive_deg_per_tick) * wobble * factor : 0);
    };
    const draw = () => {
      const currentSpeeds = speeds();
      model.shafts.forEach((shaft, index) => {
        const ctx = document.getElementById(`clutch2-${index}`).getContext("2d");
        ctx.clearRect(0, 0, 230, 230); ctx.fillStyle = "#0e1310"; ctx.fillRect(0, 0, 230, 230); ctx.save(); ctx.translate(115, 115); ctx.rotate(shaft.angle_deg * Math.PI / 180); ctx.strokeStyle = shaft.engaged ? "#5fd3e0" : "#70d39b"; ctx.lineWidth = 12; ctx.beginPath(); ctx.arc(0, 0, 78, 0, Math.PI * 2); ctx.stroke(); for (let tooth = 0; tooth < 18; tooth += 1) { ctx.rotate(Math.PI * 2 / 18); ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(72, -5, 18, 10); } ctx.fillStyle = "#eef6f2"; ctx.fillRect(-5, -82, 10, 28); ctx.restore(); ctx.fillStyle = "#ff8a5d"; ctx.fillRect(111, 8, 8, 28); ctx.fillStyle = "#bcd6cd"; ctx.font = "800 10px Courier New";
        const currentTelemetry = showAngleReadout && showSpeedReadout
          ? `${shaft.angle_deg.toFixed(1)}° · ${shaft.engaged ? `${currentSpeeds[index].toFixed(1)}°/T` : "FREE"}`
          : [
              shaft.id.toUpperCase(),
              showAngleReadout ? `${shaft.angle_deg.toFixed(1)}°` : null,
              shaft.engaged ? (showSpeedReadout ? `${currentSpeeds[index].toFixed(1)}°/T` : "COUPLED") : "FREE",
            ].filter(Boolean).join(" · ");
        ctx.fillText(currentTelemetry, showAngleReadout && showSpeedReadout ? 52 : 48, 214);
      });
      document.getElementById("clutch2-tick").innerHTML = `<span>DRIVE TICK <b>${model.tick}/${state.physics.max_ticks}</b></span><span>COUPLED <b>${model.shafts.filter((shaft) => shaft.engaged).length}</b></span><span>LOAD FACTOR <b>${model.shafts.some((shaft) => shaft.engaged) ? (state.physics.load_numerator / model.shafts.filter((shaft) => shaft.engaged).length).toFixed(2) : "0"}×</b></span>`;
    };
    const tick = () => {
      if (!model.running || model.terminal || model.submitting) return;
      model.tick += 1;
      const currentSpeeds = speeds();
      model.shafts.forEach((shaft, index) => { if (shaft.engaged) shaft.angle_deg = (shaft.angle_deg + currentSpeeds[index] + 3600) % 360; });
      draw();
      if (model.tick >= state.physics.max_ticks) {
        clearInterval(model.interval); model.running = false;
        event(model, "timeout", {tick: model.tick});
        submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: false}, "", "");
      }
    };
    const start = () => {
      if (model.running || model.terminal || model.submitting || model.tick >= state.physics.max_ticks) return;
      model.running = true; event(model, "drive", {tick: model.tick, running: true});
      document.getElementById("clutch2-drive").textContent = "DRIVE RUNNING";
      document.getElementById("clutch2-drive").disabled = true;
      if (document.querySelector(".readout")?.dataset.status === "error") setMessage(model, "DRIVE RUNNING", "idle");
      model.interval = setInterval(tick, state.physics.tick_ms);
    };
    const updateClutchControl = (index) => {
      const shaft = model.shafts[index], button = document.querySelector(`[data-clutch="${index}"]`), lever = document.querySelector(`[data-clutch-lever="${index}"]`);
      if (button) {
        button.textContent = `${shaft.engaged ? "RELEASE" : reengagementAllowed ? "ENGAGE" : "RELEASED"} ${state.shafts[index].id.toUpperCase()}`;
        button.disabled = !shaft.engaged && !reengagementAllowed;
      }
      if (lever) {
        lever.dataset.state = shaft.engaged ? "coupled" : "free";
        lever.dataset.locked = String(!shaft.engaged && !reengagementAllowed);
        lever.setAttribute("aria-label", `${state.shafts[index].id} clutch lever: ${shaft.engaged ? "coupled" : "free"}${!shaft.engaged && !reengagementAllowed ? ", irreversible" : ""}`);
        const handle = lever.querySelector(".clutch-lever-handle");
        if (handle) handle.style.left = "";
      }
    };
    const changeClutch = (index, inputSource, gesture = {}) => {
      if (model.terminal || model.submitting || model.tick >= state.physics.max_ticks) return;
      const shaft = model.shafts[index], before = shaft.engaged;
      if (!before && !reengagementAllowed) {
        setMessage(model, `${state.shafts[index].id.toUpperCase()} IS RELEASED · THIS TRIAL DOES NOT PERMIT RE-ENGAGEMENT`, "error");
        updateClutchControl(index);
        return;
      }
      shaft.engaged = !shaft.engaged;
      event(model, "clutch", {tick: model.tick, shaft: index, before, after: shaft.engaged, angle_deg: round(shaft.angle_deg), active_after: model.shafts.filter((item) => item.engaged).length, input_source: inputSource, ...gesture});
      updateClutchControl(index); draw();
    };
    document.getElementById("clutch2-drive").addEventListener("click", start);
    document.querySelectorAll("[data-clutch]").forEach((button) => button.addEventListener("click", () => changeClutch(Number(button.dataset.clutch), "clutch_button")));
    document.querySelectorAll("[data-clutch-lever]").forEach((lever) => {
      const rail = lever.querySelector(".clutch-lever-rail"), handle = lever.querySelector(".clutch-lever-handle");
      lever.addEventListener("pointerdown", (pointerEvent) => {
        if (model.terminal || model.submitting || model.tick >= state.physics.max_ticks || model.clutchDrag || pointerEvent.target !== handle || (!reengagementAllowed && lever.dataset.state === "free")) return;
        const index = Number(lever.dataset.clutchLever), box = rail.getBoundingClientRect(), startProgress = model.shafts[index].engaged ? 0 : 1;
        model.clutchDrag = {index, pointerId: pointerEvent.pointerId, lever, rail, handle, box, startProgress, progress: startProgress, startX: pointerEvent.clientX};
        lever.setPointerCapture(pointerEvent.pointerId); lever.classList.add("is-dragging"); pointerEvent.preventDefault();
      });
      lever.addEventListener("pointermove", (pointerEvent) => {
        const drag = model.clutchDrag;
        if (!drag || drag.pointerId !== pointerEvent.pointerId || drag.lever !== lever) return;
        const handleWidth = drag.handle.getBoundingClientRect().width, travel = Math.max(1, drag.box.width - handleWidth - 8);
        drag.progress = clamp((pointerEvent.clientX - drag.box.left - handleWidth / 2 - 4) / travel, 0, 1);
        drag.handle.style.left = `${4 + drag.progress * travel}px`; pointerEvent.preventDefault();
      });
      const finishLever = (pointerEvent, commit) => {
        const drag = model.clutchDrag;
        if (!drag || drag.pointerId !== pointerEvent.pointerId || drag.lever !== lever) return;
        model.clutchDrag = null; lever.classList.remove("is-dragging");
        try { lever.releasePointerCapture(pointerEvent.pointerId); } catch (_error) {}
        const desiredEngaged = drag.startProgress === 0 && drag.progress >= .72 ? false : drag.startProgress === 1 && drag.progress <= .28 ? true : null;
        if (commit && desiredEngaged !== null && desiredEngaged !== model.shafts[drag.index].engaged) {
          changeClutch(drag.index, "clutch_lever_drag", {lever_from: drag.startProgress, lever_to: desiredEngaged ? 0 : 1, drag_distance_px: round(Math.abs(pointerEvent.clientX - drag.startX), 2)});
        } else updateClutchControl(drag.index);
        pointerEvent.preventDefault();
      };
      lever.addEventListener("pointerup", (pointerEvent) => finishLever(pointerEvent, true));
      lever.addEventListener("pointercancel", (pointerEvent) => finishLever(pointerEvent, false));
    });
    document.getElementById("clutch2-unlock").addEventListener("click", async () => {
      if (model.terminal || model.submitting || model.tick >= state.physics.max_ticks) return;
      const errors = model.shafts.map((shaft) => angleError(shaft.angle_deg, 0));
      const accepted = model.shafts.every((shaft, index) => !shaft.engaged && errors[index] <= state.physics.phase_tolerance_deg);
      event(model, "unlock", {tick: model.tick, angles: model.shafts.map((shaft) => round(shaft.angle_deg)), engaged: model.shafts.map((shaft) => shaft.engaged), accepted});
      // A refused attempt is recorded and leaves the drive running. The
      // grader replays it and requires it to have been genuinely refused.
      if (!accepted) { setMessage(model, `SAFE REFUSES · PHASE ERRORS ${errors.map((value) => value.toFixed(1)).join(" / ")} · CORRECT AND TRY AGAIN`, "error"); return; }
      await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "CLOCKWORK SAFE OPEN", `${state.shafts.length} ${state.shafts.length === 1 ? "SHAFT" : "SHAFTS"} · WOBBLE-DRIVE LOAD REDISTRIBUTION · FINAL PHASE`);
    });
    document.getElementById("clutch2-abandon").addEventListener("click", () => {
      if (model.terminal || model.submitting) return;
      clearInterval(model.interval); model.running = false;
      submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", "");
    });
    draw();
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.clockwork_clutch_safe_v2 = {
    rootSelector: ".ivv2-clockwork-clutch-safe-v2",
    render: async (state, helpers) => {
      const previous = window.clockworkClutchSafeV2Model;
      if (previous) {
        if (previous.keyHandler) document.removeEventListener("keydown", previous.keyHandler);
        if (previous.interval) clearInterval(previous.interval);
        previous.terminal = true;
      }
      return render(state, helpers);
    },
  };
})();
