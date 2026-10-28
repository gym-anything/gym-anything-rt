(() => {
  "use strict";

  const MECHANIC_ID = "ballast_lantern_nonrealtime";
  const TRACK_UNITS = 10000;
  const ACTION_WINDOW_MS = 600;
  let activeCleanup = null;

  const clone = (value) => JSON.parse(JSON.stringify(value));
  const truncDiv = (numerator, denominator) => numerator >= 0 ? Math.floor(numerator / denominator) : -Math.floor(-numerator / denominator);

  function advanceSpecimen(sim, motion) {
    const tick = sim.tick;
    const law = motion.law;
    let velocity = sim.specimen_velocity;
    if (law === "darter" && (tick - 1) % motion.darter_interval === 0) {
      const index = Math.floor((tick - 1) / motion.darter_interval) % motion.darter_velocities.length;
      velocity = motion.darter_velocities[index];
    } else if (law === "steady_sinker") {
      velocity = Math.max(-motion.speed, velocity - motion.acceleration);
    } else if (law === "floater") {
      velocity = Math.min(motion.speed, velocity + motion.acceleration);
    }
    let position = sim.specimen_y + velocity;
    if (position <= motion.min_y) {
      position = motion.min_y;
      velocity = law === "steady_sinker" ? motion.boundary_burst : Math.abs(velocity);
    } else if (position >= motion.max_y) {
      position = motion.max_y;
      velocity = law === "floater" ? -motion.boundary_burst : -Math.abs(velocity);
    }
    sim.specimen_y = position;
    sim.specimen_velocity = velocity;
  }

  function advance(model) {
    const {sim, state, engaged} = model;
    const p = state.parameters;
    const motion = state.motion;
    const crate = state.crate;
    if (sim.status !== "active") return;
    sim.tick += 1;
    let velocity = sim.cage_velocity + (engaged ? p.thrust_accel : -p.gravity_accel);
    velocity = truncDiv(velocity * p.drag_numerator, p.drag_denominator);
    let position = sim.cage_y + velocity;
    const lower = p.cage_half_height;
    const upper = TRACK_UNITS - p.cage_half_height;
    if (position <= lower) {
      position = lower;
      velocity = truncDiv(Math.abs(velocity) * p.boundary_restitution_numerator, p.boundary_restitution_denominator);
    } else if (position >= upper) {
      position = upper;
      velocity = -truncDiv(Math.abs(velocity) * p.boundary_restitution_numerator, p.boundary_restitution_denominator);
    }
    sim.cage_y = position;
    sim.cage_velocity = velocity;
    advanceSpecimen(sim, motion);
    sim.crate_spawned = sim.tick >= state.crate.spawn_tick;
    sim.specimen_inside = Math.abs(sim.cage_y - sim.specimen_y) <= p.cage_half_height - p.specimen_half_height;
    sim.crate_inside = Boolean(sim.crate_spawned && Math.abs(sim.cage_y - state.crate.y) <= p.cage_half_height - p.crate_half_height);
    sim.capture_meter = sim.specimen_inside
      ? Math.min(p.capture_max, sim.capture_meter + p.capture_fill_per_tick)
      : Math.max(0, sim.capture_meter - p.capture_drain_per_tick);
    if (sim.crate_inside) sim.crate_meter = Math.min(p.crate_meter_max, sim.crate_meter + p.crate_fill_per_tick);
    if (sim.capture_meter <= 0) sim.status = "escaped";
    else if (sim.capture_meter >= p.capture_max) sim.status = sim.crate_meter >= p.crate_meter_max ? "secured" : "specimen_only";
    else if (sim.tick >= p.max_ticks) sim.status = "timeout";
  }

  function recordWinch(model, engaged, inputSource, phase) {
    if (model.sim.status !== "active" || model.submitting) return;
    const action = model.helpers.beginAction?.("ballast-winch-transition");
    model.engaged = engaged;
    model.events.push({
      sequence: model.events.length + 1,
      type: "winch",
      tick: model.sim.tick,
      engaged,
      input_source: inputSource,
      phase,
    });
    const actionTicks = Math.max(1, Math.floor(ACTION_WINDOW_MS / Number(model.state.parameters.tick_ms)));
    for (let index = 0; index < actionTicks && model.sim.status === "active"; index += 1) {
      advance(model);
      model.trail.unshift(model.sim.specimen_y);
      model.trail = model.trail.slice(0, model.state.parameters.trail_samples);
    }
    model.helpers.setReadout(engaged ? "HAUL" : "COAST", "idle");
    updateControls(model);
    action?.settle();
    draw(model);
    if (model.sim.status !== "active") terminal(model);
  }

  function snapshot(sim) {
    return Object.fromEntries([
      "tick", "cage_y", "cage_velocity", "specimen_y", "specimen_velocity", "capture_meter",
      "crate_meter", "crate_spawned", "specimen_inside", "crate_inside", "status",
    ].map((key) => [key, sim[key]]));
  }

  function payload(model) {
    return {
      mechanic_id: model.state.mechanic_id,
      task_id: model.state.task_id,
      challenge_id: model.state.challenge_id,
      interaction_mode: model.interaction,
      events: clone(model.events),
      terminal_tick: model.sim.tick,
      final_state: snapshot(model.sim),
      completed: model.sim.status === "secured",
    };
  }

  function setVerdict(model, kind, title) {
    const root = document.querySelector(".ballast-lantern");
    const node = document.querySelector(".ballast-verdict");
    if (!root || !node) return;
    root.classList.toggle("is-passed", kind === "pass");
    root.classList.toggle("is-failed", kind === "fail");
    node.innerHTML = `<b>${model.helpers.text(title)}</b>`;
  }

  async function postPayload(model, outgoing) {
    if (model.submitting) return;
    model.submitting = true;
    model.pendingPayload = outgoing;
    updateControls(model);
    try {
      const response = await fetch("/result", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify(outgoing),
      });
      const outcome = await response.json();
      if (outcome.passed === true) {
        model.completed = true;
        setVerdict(model, "pass", "PASS");
        model.helpers.setReadout("PASS", "passed");
        updateControls(model);
        return;
      }
      if (outcome.state) {
        await render(outcome.state, model.helpers, {freshFailure: true});
        const fresh = window.ballastLanternModel;
        setVerdict(fresh, "fail", "FAIL");
        fresh.helpers.setReadout("FAIL", "error");
      } else {
        model.submitting = false;
        model.helpers.setReadout("FAIL", "error");
        document.querySelector(".ballast-retry")?.removeAttribute("hidden");
        updateControls(model);
      }
    } catch (_error) {
      model.submitting = false;
      model.helpers.setReadout("FAIL", "error");
      document.querySelector(".ballast-retry")?.removeAttribute("hidden");
      updateControls(model);
    }
  }

  function terminal(model) {
    if (model.terminal) return;
    model.terminal = true;
    const title = model.sim.status === "secured" ? "PASS" : "FAIL";
    setVerdict(model, model.sim.status === "secured" ? "pass" : "fail", title);
    model.helpers.setReadout(title, model.sim.status === "secured" ? "passed" : "error");
    void postPayload(model, payload(model));
  }

  function pct(value) { return `${(Number(value) / TRACK_UNITS * 100).toFixed(3)}%`; }

  function updateControls(model) {
    const root = document.querySelector(".ballast-lantern");
    if (!root) return;
    root.dataset.engaged = String(model.engaged);
    root.dataset.terminal = String(model.terminal);
    root.dataset.interaction = model.interaction;
    document.querySelectorAll(".ballast-controls button").forEach((button) => { button.disabled = model.terminal || model.submitting; });
    const haul = document.querySelector(".ballast-haul");
    const coast = document.querySelector(".ballast-coast");
    if (haul) haul.dataset.active = String(model.engaged);
    if (coast) coast.dataset.active = String(!model.engaged);
  }

  function draw(model) {
    const {sim, state} = model;
    const p = state.parameters;
    const cage = document.querySelector(".ballast-cage");
    const specimen = document.querySelector(".ballast-specimen");
    const crate = document.querySelector(".ballast-crate");
    const cable = document.querySelector(".ballast-cable");
    if (!cage || !specimen || !crate || !cable) return;
    cage.style.bottom = pct(sim.cage_y);
    cage.style.height = pct(p.cage_half_height * 2);
    cage.dataset.specimen = String(sim.specimen_inside);
    cage.dataset.crate = String(sim.crate_inside);
    specimen.style.bottom = pct(sim.specimen_y);
    specimen.style.height = pct(p.specimen_half_height * 2);
    specimen.dataset.inside = String(sim.specimen_inside);
    crate.style.bottom = pct(state.crate.y);
    crate.style.height = pct(p.crate_half_height * 2);
    crate.dataset.spawned = String(sim.crate_spawned);
    crate.dataset.inside = String(sim.crate_inside);
    cable.style.height = pct(TRACK_UNITS - sim.cage_y);
    const trend = document.querySelector(".ballast-trend");
    if (trend) trend.dataset.direction = sim.specimen_velocity >= 0 ? "up" : "down";
    const reel = document.querySelector(".ballast-reel");
    reel.style.transform = `rotate(${(sim.tick * (model.engaged ? 9 : -5)) % 360}deg)`;
    document.querySelectorAll(".ballast-wake-dot").forEach((dot, index) => {
      dot.style.bottom = pct(model.trail[index] ?? sim.specimen_y);
      dot.style.opacity = String(Math.max(.08, .5 - index * .08));
    });
    updateControls(model);
  }

  async function abandon(model) {
    if (model.submitting || model.completed) return;
    model.terminal = true;
    model.helpers.setReadout("…", "pending");
    await postPayload(model, {
      mechanic_id: model.state.mechanic_id,
      task_id: model.state.task_id,
      challenge_id: model.state.challenge_id,
      interaction_mode: model.interaction,
      events: [],
      terminal_tick: 0,
      final_state: snapshot(model.sim),
      completed: false,
    });
  }

  async function render(state, helpers, options = {}) {
    if (activeCleanup) activeCleanup();
    document.body.dataset.mechanic = "ballast-lantern";
    const interaction = state.control_condition?.interaction || "full";
    const trailCount = Number(state.parameters.trail_samples);
    const model = {
      state,
      helpers,
      interaction,
      events: [],
      sim: clone(state.initial_state),
      engaged: false,
      terminal: false,
      completed: false,
      submitting: false,
      pendingPayload: null,
      trail: Array.from({length: trailCount}, () => state.initial_state.specimen_y),
      keydown: null,
      keyup: null,
      blur: null,
    };
    window.ballastLanternModel = model;
    const wake = Array.from({length: trailCount}, (_, index) => `<i class="ballast-wake-dot" data-wake="${index}"></i>`).join("");
    const controls = interaction === "simplified"
      ? `<div class="ballast-controls"><button type="button" class="ballast-haul">HAUL</button><button type="button" class="ballast-coast" data-active="true">COAST</button></div>`
      : `<div class="ballast-spacebar"><b>SPACE</b></div>`;
    helpers.app.innerHTML = `
      <section class="ballast-lantern" data-engaged="false" data-terminal="false" data-interaction="${helpers.text(interaction)}" data-challenge-id="${helpers.text(state.challenge_id)}">
        <div class="ballast-verdict" aria-live="assertive"></div>
        <header class="ballast-head">
          <div class="ballast-mark"><i></i><span>BL<br>17</span></div>
          <div><small>PELAGIC RECOVERY OFFICE / NIGHT SHIFT</small><h1>Cage both signals. Ballast first.</h1></div>
        </header>
        <main class="ballast-workbench">
          <section class="ballast-shaft-shell">
            <div class="ballast-reel-house"><div class="ballast-reel"><i></i><b></b></div><span>ONE-CHANNEL WINCH</span></div>
            <div class="ballast-shaft" aria-label="Flooded vertical salvage shaft">
              <div class="ballast-depths"><span>00</span><span>25</span><span>50</span><span>75</span><span>100</span></div>
              <div class="ballast-cable"></div>
              ${wake}
              <div class="ballast-specimen" aria-label="moving luminous specimen"><i></i><b></b><span></span></div>
              <div class="ballast-crate" aria-label="ballast salvage crate"><i></i><b></b><span>Ⅱ</span></div>
              <div class="ballast-cage" aria-label="lantern capture cage"><i></i><b></b><span></span></div>
              <div class="ballast-waterline"></div>
            </div>
            ${state.parameters.show_trend_beacon ? `<div class="ballast-trend" data-direction="up" aria-label="specimen drift beacon"><i></i></div>` : ""}
          </section>
          <aside class="ballast-console">
            <div class="ballast-console-title"><small>WINCH TELEGRAPH</small><b>BL-17</b></div>
            <div class="ballast-dial"><div class="ballast-dial-hand"></div><strong>WINCH</strong></div>
            ${controls}
          </aside>
        </main>
        <footer class="ballast-foot"><div class="readout" data-status="idle">COAST</div><button type="button" class="ballast-retry" hidden>RETRY</button><button type="button" class="ballast-abandon">NEW SHAFT</button></footer>
        ${helpers.cheatPanelTemplate()}
      </section>`;

    model.keydown = (event) => {
      if (interaction !== "full" || event.code !== "Space" || event.repeat || model.terminal) return;
      event.preventDefault();
      if (event.shiftKey) {
        // A modified Space keydown is still the same keyboard surface.  It
        // deliberately repeats the currently selected settled segment,
        // which has no equivalent in the donor's continuously ticking loop.
        recordWinch(model, model.engaged, "keyboard_hold", model.engaged ? "keydown" : "keyup");
        return;
      }
      recordWinch(model, true, "keyboard_hold", "keydown");
    };
    model.keyup = (event) => {
      if (interaction !== "full" || event.code !== "Space" || model.terminal) return;
      if (event.shiftKey) return;
      event.preventDefault();
      recordWinch(model, false, "keyboard_hold", "keyup");
    };
    model.blur = () => { if (interaction === "full" && model.engaged && !model.terminal) recordWinch(model, false, "keyboard_hold", "keyup"); };
    document.addEventListener("keydown", model.keydown);
    document.addEventListener("keyup", model.keyup);
    window.addEventListener("blur", model.blur);
    document.querySelector(".ballast-haul")?.addEventListener("click", () => recordWinch(model, true, "winch_button", "haul"));
    document.querySelector(".ballast-coast")?.addEventListener("click", () => recordWinch(model, false, "winch_button", "coast"));
    document.querySelector(".ballast-abandon")?.addEventListener("click", () => void abandon(model));
    document.querySelector(".ballast-retry")?.addEventListener("click", () => {
      document.querySelector(".ballast-retry")?.setAttribute("hidden", "");
      void postPayload(model, model.pendingPayload || payload(model));
    });
    if (helpers.isCheatMode()) helpers.installCheatPanel?.();
    draw(model);
    if (options.freshFailure) {
      window.setTimeout(() => document.querySelector(".ballast-lantern")?.classList.remove("is-failed"), 1450);
    }
    activeCleanup = () => {
      document.removeEventListener("keydown", model.keydown);
      document.removeEventListener("keyup", model.keyup);
      window.removeEventListener("blur", model.blur);
      model.terminal = true;
    };
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics[MECHANIC_ID] = {rootSelector: ".ballast-lantern", render};
})();
