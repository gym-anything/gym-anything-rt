(() => {
  "use strict";

  let model = null;
  let cleanup = null;
  const esc = (value) => String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const interaction = () => model.state.control_condition?.interaction || "full";
  const parameter = (key) => model.state.parameters?.[key];

  function stopMotion() {
    if (model?.motionFrame) cancelAnimationFrame(model.motionFrame);
    if (model) model.motionFrame = 0;
  }

  function record(event) {
    model.events.push({
      sequence: model.events.length + 1,
      task_time_ms: Number(Math.max(0, performance.now() - model.runStartedAt).toFixed(3)),
      ...event,
    });
    if (model.freshFailure) {
      model.freshFailure = false;
      const verdict = document.querySelector(".consent-verdict");
      if (verdict) verdict.className = "consent-verdict";
      model.helpers.setReadout("PRIVACY PACKET ACTIVE", "idle");
    }
  }

  function optionById(id, stage = model.stage) {
    const key = stage === "entry" ? "entry_options" : "final_options";
    return model.surface[key].find((item) => item.id === id) || null;
  }

  function drawerById(id) {
    return model.surface.drawers.find((item) => item.id === id) || null;
  }

  function purposeById(id) {
    return model.surface.purposes.find((item) => item.id === id) || null;
  }

  function finalState() {
    return {
      stage: model.stage,
      current_drawer: model.currentDrawer,
      purpose_states: Object.fromEntries(model.surface.purposes.map((item) => [item.id, item.state])),
    };
  }

  function showVerdict(kind) {
    const verdict = document.querySelector(".consent-verdict");
    if (!verdict) return;
    verdict.className = `consent-verdict is-${kind}`;
    verdict.innerHTML = `<small>PRIVACY PACKET</small><b>${kind.toUpperCase()}</b>`;
  }

  async function submit(completed) {
    if (!model || model.submitting || model.terminal) return;
    const current = model;
    current.submitting = true;
    current.helpers.setReadout("CHECKING CONSENT LEDGER…", "pending");
    try {
      const response = await fetch("/result", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({
          mechanic_id: current.state.mechanic_id,
          task_id: current.state.task_id,
          challenge_id: current.state.challenge_id,
          interaction_mode: interaction(),
          events: current.events,
          final_state: finalState(),
          elapsed_task_ms: Number(Math.max(0, performance.now() - current.runStartedAt).toFixed(3)),
          completed: completed === true,
        }),
      });
      const outcome = await response.json();
      if (outcome.passed === true) {
        current.terminal = true;
        stopMotion();
        current.helpers.setReadout("PASS", "passed");
        showVerdict("pass");
      } else if (outcome.passed === false && outcome.state) {
        const helpers = current.helpers;
        await render(outcome.state, helpers, {freshFailure: true});
        model.helpers.setReadout("FAIL · NEW PACKET LOADED", "error");
        showVerdict("fail");
      } else {
        current.submitting = false;
        current.helpers.setReadout("LEDGER REJECTED", "error");
      }
    } catch (_error) {
      if (model === current) {
        current.submitting = false;
        current.helpers.setReadout("PRIVACY LINK OFFLINE", "error");
      }
    }
  }

  function optionClick(event, option) {
    if (model.submitting || model.terminal) return;
    const source = interaction() === "full" ? "orbit_card" : "option_proxy";
    const proof = {};
    if (interaction() === "full") {
      const rect = event.currentTarget.getBoundingClientRect();
      const orbitRect = event.currentTarget.closest(".consent-orbit").getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const dx = (event.clientX - (rect.left + rect.width / 2)) / Math.max(1, rect.width / 2);
      const dy = (event.clientY - (rect.top + rect.height / 2)) / Math.max(1, rect.height / 2);
      proof.pointer_offset_norm = Number(Math.hypot(dx, dy).toFixed(5));
      proof.phase_deg = Number(currentPhase().toFixed(5));
      proof.pointer_x_norm = Number(((event.clientX - orbitRect.left) / orbitRect.width).toFixed(6));
      proof.pointer_y_norm = Number(((event.clientY - orbitRect.top) / orbitRect.height).toFixed(6));
      proof.card_center_x_norm = Number(((centerX - orbitRect.left) / orbitRect.width).toFixed(6));
      proof.card_center_y_norm = Number(((centerY - orbitRect.top) / orbitRect.height).toFixed(6));
      proof.card_width_norm = Number((rect.width / orbitRect.width).toFixed(6));
      proof.card_height_norm = Number((rect.height / orbitRect.height).toFixed(6));
    }
    record({type: "gateway", id: option.id, input_source: source, ...proof});
    if (model.stage === "entry") {
      if (option.action === "manage") {
        model.stage = "preferences";
        renderStage();
      } else {
        submit(false);
      }
    } else if (option.action === "commit") {
      submit(true);
    } else {
      submit(false);
    }
  }

  function currentPhase() {
    // The counterpart keeps the donor's generated layout and difficulty
    // parameters, but gateway positions are stable until the player acts.
    return model.motionPhase;
  }

  function positionOrbit() {
    const phase = currentPhase();
    document.querySelectorAll("[data-orbit-option]").forEach((node) => {
      const option = optionById(node.dataset.orbitOption);
      if (!option) return;
      const radians = (phase + option.angle_offset_deg) * Math.PI / 180;
      const x = 50 + Math.cos(radians) * 37;
      const y = 50 + Math.sin(radians) * 31;
      node.style.left = `${x}%`;
      node.style.top = `${y}%`;
      node.style.zIndex = String(3 + Math.round((Math.sin(radians) + 1) * 3));
    });
  }

  function gatewayMarkup() {
    const options = model.stage === "entry" ? model.surface.entry_options : model.surface.final_options;
    const heading = model.stage === "entry" ? "THE NOTICE WON'T DISMISS ITSELF" : "SEAL THE PACKET";
    const copy = "Select one packet action.";
    const orbit = options.map((option) => `<button class="consent-orbit-card tone-${esc(option.tone)}" data-orbit-option="${esc(option.id)}" data-option-id="${esc(option.id)}" data-action="${esc(option.action)}">${esc(option.label)}</button>`).join("");
    const proxy = interaction() === "simplified" ? `<aside class="consent-proxy"><small>FIXED DECISION PROXY</small><p>ACTION INDEX</p>${options.map((option, index) => `<button data-proxy-option="${esc(option.id)}" data-option-id="${esc(option.id)}" data-action="${esc(option.action)}"><b>${String(index + 1).padStart(2, "0")}</b>${esc(option.label)}</button>`).join("")}</aside>` : "";
    return `<section class="consent-gateway stage-${model.stage}">
      <div class="consent-gateway-copy"><small>${model.stage === "entry" ? "GATE 01 / DISCLOSURE" : "GATE 03 / COMMIT"}</small><h2>${heading}</h2><p>${copy}</p></div>
      <div class="consent-orbit is-stationary" aria-label="consent decision orbit">
        <div class="consent-orbit-core"><span>OPTIONAL</span><b>PROCESSING</b><i>FIXED LAYOUT</i></div>${orbit}
      </div>${proxy}
      ${model.stage === "final" ? '<button class="consent-back" id="consent-back">← RETURN TO LEDGER</button>' : ""}
    </section>`;
  }

  function linkMarkup(purpose) {
    const outgoing = model.surface.links.filter((item) => item.source_id === purpose.id);
    const incoming = model.surface.links.filter((item) => item.target_id === purpose.id);
    if (!outgoing.length && !incoming.length) return "";
    return `<div class="consent-link-notes">${outgoing.map((item) => `<span class="is-out">↗ ${esc(item.label)}</span>`).join("")}${incoming.map((item) => `<span class="is-in">↘ MOVED BY ${esc(item.source_id.replace("purpose-", "P"))}</span>`).join("")}</div>`;
  }

  function purposeMarkup(purpose) {
    const yes = purpose.state === true;
    const full = interaction() === "full";
    return `<article class="consent-purpose" data-purpose-row="${esc(purpose.id)}">
      <div class="consent-purpose-index">${esc(purpose.id.replace("purpose-", "P"))}</div>
      <div class="consent-purpose-copy"><b>${esc(purpose.label)}</b>${linkMarkup(purpose)}</div>
      <div class="consent-answer ${yes ? "is-yes" : "is-no"}" aria-label="${esc(purpose.label)} answer ${yes ? "YES" : "NO"}">
        <span>NO</span><div class="consent-switch-rail" data-purpose-switch="${esc(purpose.id)}" role="switch" aria-checked="${yes}" aria-label="${esc(purpose.label)}"><i></i></div><span>YES</span>
        ${full ? "" : `<div class="consent-switch-proxy"><button data-purpose-answer="${esc(purpose.id)}:false">SET NO</button><button data-purpose-answer="${esc(purpose.id)}:true">SET YES</button></div>`}
      </div>
    </article>`;
  }

  function trapMarkup(trap) {
    if (interaction() === "full") {
      return `<article class="consent-reset"><div><small>PROVIDER TOOL</small><b>${esc(trap.label)}</b></div><div class="consent-reset-rail" data-reset-slider="${esc(trap.id)}"><i></i><span>DRAG TO APPLY</span></div></article>`;
    }
    return `<article class="consent-reset"><div><small>PROVIDER TOOL</small><b>${esc(trap.label)}</b></div><button data-reset-proxy="${esc(trap.id)}">RESTORE DEFAULTS</button></article>`;
  }

  function preferencesMarkup() {
    const drawer = drawerById(model.currentDrawer);
    const purposes = drawer.purpose_ids.map(purposeById);
    const traps = model.surface.reset_traps.filter((item) => item.drawer_id === drawer.id);
    const tabs = model.surface.drawers.map((item) => `<button data-drawer-tab="${esc(item.id)}" class="${item.id === drawer.id ? "is-active" : ""}">${esc(item.label)}<small>${item.purpose_ids.length}</small></button>`).join("");
    const proxy = interaction() === "simplified" ? `<div class="consent-drawer-proxy"><button data-drawer-prev>← PREVIOUS</button><b>${esc(drawer.label)}</b><button data-drawer-next>NEXT →</button></div>` : "";
    return `<section class="consent-preferences">
      <aside class="consent-receipt"><small>PACKET ${esc(model.state.challenge_id.slice(-7).toUpperCase())}</small><h2>OPTIONAL PROCESSING LEDGER</h2><p>Current packet state.</p><dl><dt>DRAWERS</dt><dd>${model.surface.drawers.length}</dd><dt>PURPOSES</dt><dd>${model.surface.purposes.length}</dd><dt>LINKS</dt><dd>${model.surface.links.length}</dd></dl><footer>NULL CONSENT BUREAU / REVISION 03</footer></aside>
      <main class="consent-ledger"><header><div><small>GATE 02 / PURPOSE LEDGER</small><h2>${esc(drawer.label)} DRAWER</h2></div><div class="consent-tabs">${tabs}</div></header>${proxy}<div class="consent-purpose-list">${purposes.map(purposeMarkup).join("")}</div>${traps.map(trapMarkup).join("")}<button id="consent-review">REVIEW CURRENT CHOICES →</button></main>
    </section>`;
  }

  function renderStage() {
    stopMotion();
    const shell = document.querySelector(".consent-gauntlet");
    if (!shell) return;
    const content = shell.querySelector(".consent-content");
    content.innerHTML = model.stage === "preferences" ? preferencesMarkup() : gatewayMarkup();
    bindStage();
    if (model.stage !== "preferences") {
      model.motionStart = performance.now();
      model.motionPhase = Number(model.surface.phase_deg || 0) + (model.stage === "final" ? 33 : 0);
    }
    positionOrbit();
  }

  function applyLinks(sourceId) {
    const effects = [];
    model.surface.links.filter((item) => item.source_id === sourceId).forEach((link) => {
      const target = purposeById(link.target_id);
      const before = target.state;
      target.state = !before;
      effects.push({link_id: link.id, id: target.id, before, after: target.state});
    });
    return effects;
  }

  function setPurpose(purpose, after, source, gesture = null) {
    const before = purpose.state;
    if (after === before) return;
    purpose.state = after;
    const effects = applyLinks(purpose.id);
    record({type: "purpose", id: purpose.id, before, after, input_source: source, effects, ...(gesture ? {gesture} : {})});
    renderStage();
  }

  function resetDrawer(trap, source, gesture = null) {
    const drawer = drawerById(trap.drawer_id);
    const effects = drawer.purpose_ids.map((id) => {
      const purpose = purposeById(id);
      const before = purpose.state;
      purpose.state = purpose.initial_state;
      return {id, before, after: purpose.state};
    });
    record({type: "trap", id: trap.id, input_source: source, effects, ...(gesture ? {gesture} : {})});
    renderStage();
  }

  function changeDrawer(drawerId, source) {
    if (drawerId === model.currentDrawer) return;
    const before = model.currentDrawer;
    model.currentDrawer = drawerId;
    record({type: "drawer", id: drawerId, before, after: drawerId, input_source: source});
    renderStage();
  }

  function bindDragRail(rail, purpose) {
    let drag = null;
    rail.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const rect = rail.getBoundingClientRect();
      const current = purpose.state ? 0.82 : 0.18;
      const fraction = (event.clientX - rect.left) / rect.width;
      if (Math.abs(fraction - current) * rect.width > 20) return;
      event.preventDefault();
      drag = {start: current, lastX: event.clientX, travel: 0, samples: 0};
      rail.setPointerCapture?.(event.pointerId);
    });
    rail.addEventListener("pointermove", (event) => {
      if (!drag) return;
      drag.travel += Math.abs(event.clientX - drag.lastX);
      drag.lastX = event.clientX;
      drag.samples += 1;
    });
    rail.addEventListener("pointerup", (event) => {
      if (!drag) return;
      const rect = rail.getBoundingClientRect();
      drag.travel += Math.abs(event.clientX - drag.lastX);
      drag.samples += 1;
      const after = (event.clientX - rect.left) / rect.width >= 0.5;
      const proof = {start_fraction: drag.start, end_fraction: after ? 0.82 : 0.18, travel_px: Number(drag.travel.toFixed(3)), sample_count: drag.samples};
      const valid = drag.travel >= 24 && drag.samples >= 2;
      drag = null;
      if (valid) setPurpose(purpose, after, "switch_drag", proof);
    });
    rail.addEventListener("pointercancel", () => { drag = null; });
  }

  function bindResetRail(rail, trap) {
    let drag = null;
    rail.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const rect = rail.getBoundingClientRect();
      const fraction = (event.clientX - rect.left) / rect.width;
      if (Math.abs(fraction - 0.18) * rect.width > 20) return;
      event.preventDefault();
      drag = {lastX: event.clientX, travel: 0, samples: 0};
      rail.setPointerCapture?.(event.pointerId);
    });
    rail.addEventListener("pointermove", (event) => {
      if (!drag) return;
      drag.travel += Math.abs(event.clientX - drag.lastX); drag.lastX = event.clientX; drag.samples += 1;
    });
    rail.addEventListener("pointerup", (event) => {
      if (!drag) return;
      const rect = rail.getBoundingClientRect();
      drag.travel += Math.abs(event.clientX - drag.lastX); drag.samples += 1;
      const fraction = (event.clientX - rect.left) / rect.width;
      const proof = {start_fraction: 0.18, end_fraction: 0.82, travel_px: Number(drag.travel.toFixed(3)), sample_count: drag.samples};
      const valid = fraction >= 0.72 && drag.travel >= 24 && drag.samples >= 2;
      drag = null;
      if (valid) resetDrawer(trap, "trap_slider", proof);
    });
    rail.addEventListener("pointercancel", () => { drag = null; });
  }

  function bindStage() {
    document.querySelectorAll("[data-orbit-option]").forEach((button) => button.addEventListener("click", (event) => optionClick(event, optionById(button.dataset.orbitOption))));
    document.querySelectorAll("[data-proxy-option]").forEach((button) => button.addEventListener("click", (event) => optionClick(event, optionById(button.dataset.proxyOption))));
    document.getElementById("consent-back")?.addEventListener("click", () => {
      record({type: "back", id: "back", input_source: "back_button"}); model.stage = "preferences"; renderStage();
    });
    if (model.stage !== "preferences") return;
    document.querySelectorAll("[data-drawer-tab]").forEach((button) => button.addEventListener("click", () => {
      if (interaction() === "full") changeDrawer(button.dataset.drawerTab, "drawer_tab");
    }));
    const drawers = model.surface.drawers;
    const index = drawers.findIndex((item) => item.id === model.currentDrawer);
    document.querySelector("[data-drawer-prev]")?.addEventListener("click", () => changeDrawer(drawers[(index - 1 + drawers.length) % drawers.length].id, "drawer_navigator"));
    document.querySelector("[data-drawer-next]")?.addEventListener("click", () => changeDrawer(drawers[(index + 1) % drawers.length].id, "drawer_navigator"));
    document.querySelectorAll("[data-purpose-answer]").forEach((button) => button.addEventListener("click", () => {
      const [id, value] = button.dataset.purposeAnswer.split(":"); setPurpose(purposeById(id), value === "true", "switch_direction_button");
    }));
    if (interaction() === "full") document.querySelectorAll("[data-purpose-switch]").forEach((rail) => bindDragRail(rail, purposeById(rail.dataset.purposeSwitch)));
    document.querySelectorAll("[data-reset-proxy]").forEach((button) => button.addEventListener("click", () => resetDrawer(model.surface.reset_traps.find((item) => item.id === button.dataset.resetProxy), "trap_proxy")));
    document.querySelectorAll("[data-reset-slider]").forEach((rail) => bindResetRail(rail, model.surface.reset_traps.find((item) => item.id === rail.dataset.resetSlider)));
    document.getElementById("consent-review")?.addEventListener("click", () => {
      record({type: "review", id: "review", input_source: "review_button"}); model.stage = "final"; renderStage();
    });
  }

  async function render(state, helpers, options = {}) {
    cleanup?.();
    document.body.dataset.mechanic = "consent-gauntlet";
    model = {
      state,
      helpers,
      surface: JSON.parse(JSON.stringify(state.surface)),
      events: [],
      stage: "entry",
      currentDrawer: state.surface.drawers[0].id,
      freshFailure: Boolean(options.freshFailure),
      submitting: false,
      terminal: false,
      motionFrame: 0,
      runStartedAt: performance.now(),
      motionStart: performance.now(),
      motionPhase: Number(state.surface.phase_deg || 0),
    };
    helpers.app.innerHTML = `<section class="consent-gauntlet mode-${interaction()}" data-fresh-failure="${options.freshFailure ? "true" : "false"}">
      <div class="consent-verdict"></div>
      <header class="consent-masthead"><div><small>NULL CONSENT BUREAU / PACKET REVIEW</small><h1>${esc(state.prompt)}</h1></div><div class="consent-mode"><i></i><span>${interaction().toUpperCase()} INPUT</span><b>FIXED GATEWAY LAYOUT</b><em data-packet-time>00:00.00</em></div></header>
      <div class="consent-content"></div>
      <footer class="consent-footer"><span>PACKET DECISION SURFACE</span><div class="readout" data-status="idle">PRIVACY PACKET READY</div><b>${esc(state.challenge_id.slice(-9).toUpperCase())}</b></footer>
      ${helpers.cheatPanelTemplate()}
    </section>`;
    helpers.installCheatPanel();
    renderStage();
    cleanup = () => stopMotion();
    if (options.freshFailure) showVerdict("fail");
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.consent_gauntlet_nonrealtime = {rootSelector: ".consent-gauntlet", render};
})();
