(() => {
  "use strict";
  let model = null;
  const clean = (value) => String(value == null ? "" : value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const countWord = (count) => ({1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE"}[count] || String(count));
  function record(kind, details = {}) { const event = {sequence: model.events.length + 1, kind, ...details}; model.events.push(event); return event; }
  function inputDetails(source) { return model.controlled ? {input_source: source} : {}; }
  function shellMarkup(shellId) { return `<button type="button" class="shell-piece" data-shell-id="${clean(shellId)}" disabled><i></i><b>${clean(shellId.replace("shell-", ""))}</b><span>SELECT</span></button>`; }
  function setShellPosition(shell, position) { shell.style.left = `${position.x / model.state.stage.width * 100}%`; shell.style.top = `${position.y / model.state.stage.height * 100}%`; shell.style.rotate = `${position.angle || 0}deg`; }
  function stagePoint(event) { const rect = document.querySelector(".shell-stage").getBoundingClientRect(); return [Math.max(0, Math.min(model.state.stage.width, Math.round((event.clientX - rect.left) / rect.width * model.state.stage.width))), Math.max(0, Math.min(model.state.stage.height, Math.round((event.clientY - rect.top) / rect.height * model.state.stage.height)))]; }
  function relayPorts(round) { return [{occluder_id: round.inspection.occluder_id, port: round.inspection.port}, ...(round.decoy_ports || [])]; }
  function renderRelayChoices(round) {
    const controls = document.querySelector(".shell-relay-controls");
    if (!controls) return;
    controls.innerHTML = relayPorts(round).map((item) => `<button type="button" class="shell-inspection-relay" data-cover-id="${clean(item.occluder_id)}" disabled>ARM ${clean(item.occluder_id).toUpperCase()} RELAY</button>`).join("");
  }

  function renderRound() {
    const round = model.state.rounds[model.roundIndex], stage = document.querySelector(".shell-stage"), inspection = round.inspection; model.mode = "ready"; model.tick = 0; model.roundInspection = new Set(); model.roundInspectionSamples = 0; model.lens = null; model.relayPort = null;
    const initial = Object.fromEntries(round.start_positions.map((item) => [item.id, item]));
    const decoyPorts = (round.decoy_ports || []).map((item) => `<div class="shell-inspection-port shell-decoy-port" data-decoy-port="${clean(item.occluder_id)}" data-alert="false" style="left:${item.port[0]/model.state.stage.width*100}%;top:${item.port[1]/model.state.stage.height*100}%"><em>PEEP</em><div><b>?</b><i><u></u></i><b>?</b></div></div>`).join("");
    stage.innerHTML = `<div class="shell-floor-lines"></div>${round.shell_ids.map(shellMarkup).join("")}${round.occluders.map((item) => `<div class="shell-occluder shell-cover-${clean(item.style)}" data-cover-id="${clean(item.id)}" style="left:${item.x/model.state.stage.width*100}%;top:${item.y/model.state.stage.height*100}%;width:${item.width/model.state.stage.width*100}%;height:${item.height/model.state.stage.height*100}%"><i></i><b>SEALED COVER</b><span>${clean(item.id)}</span></div>`).join("")}<div class="shell-inspection-port" data-alert="false" data-revealed="false" style="left:${inspection.port[0]/model.state.stage.width*100}%;top:${inspection.port[1]/model.state.stage.height*100}%"><em>PEEP</em><div><b class="port-from">?</b><i><u></u></i><b class="port-to">?</b></div></div>${decoyPorts}<div class="shell-lens" data-visible="false"></div><div class="shell-token" data-visible="true"><i></i><b>MARKED TOKEN</b></div><div class="shell-stop-banner" data-visible="false"><b>SHUFFLE STOPPED</b><span>SELECT THE TRUE CARRIER</span></div>`;
    round.shell_ids.forEach((shellId) => setShellPosition(stage.querySelector(`.shell-piece[data-shell-id="${CSS.escape(shellId)}"]`), {...initial[shellId], angle: 0}));
    const carrier = stage.querySelector(`.shell-piece[data-shell-id="${CSS.escape(round.initial_carrier)}"]`), token = stage.querySelector(".shell-token"), position = initial[round.initial_carrier]; token.style.left = `${position.x / model.state.stage.width * 100}%`; token.style.top = `${(position.y - 66) / model.state.stage.height * 100}%`; carrier.dataset.marked = "true";
    document.querySelector(".shell-round-label").textContent = round.label; document.querySelector(".shell-duration").textContent = `${((round.preview_ms + round.duration_ms) / 1000).toFixed(1)} SEC`; document.querySelector(".shell-rounds-value").textContent = `${model.roundIndex}/${model.state.rounds.length}`; document.querySelector(".shell-ticks-value").textContent = `0/${round.frame_count}`; document.querySelector(".shell-port-value").textContent = `0/${inspection.minimum_samples}`; document.querySelector(".shell-timeline i").style.width = "0";
    renderRelayChoices(round); document.querySelectorAll(".shell-inspection-relay").forEach((button) => { button.disabled = true; }); document.querySelectorAll(".shell-proxy-select").forEach((button) => { button.disabled = true; });
    const start = document.querySelector(".shell-start-round"); start.disabled = false; start.textContent = `BEGIN ROUND ${model.roundIndex + 1}`; const instruction = document.querySelector(".shell-mode"); instruction.dataset.mode = "preview"; instruction.textContent = "MARK VISIBLE · MEMORIZE ITS CARRIER"; model.helpers.setReadout(`ROUND ${model.roundIndex + 1} READY · MARKED TOKEN VISIBLE`, "idle");
  }
  function applyFrame(frame) { frame.shells.forEach((position) => { const shell = document.querySelector(`.shell-piece[data-shell-id="${CSS.escape(position.id)}"]`); if (shell) setShellPosition(shell, position); }); }
  function updateInspection(round) {
    const spec = round.inspection, port = document.querySelector(".shell-inspection-port:not([data-decoy-port])"); if (!port) return; const nearWindow = model.tick >= spec.window_start - 5 && model.tick <= spec.window_end + 1, insideWindow = model.tick >= spec.window_start && model.tick <= spec.window_end, decisionWindow = model.mode === "select"; port.dataset.alert = String(nearWindow || decisionWindow);
    document.querySelectorAll(".shell-decoy-port").forEach((decoy) => { decoy.dataset.alert = String(nearWindow); });
    const lensPoint = model.interaction === "simplified" && model.relayPort ? model.relayPort.port : model.lens;
    const lensInside = Boolean(lensPoint) && distance(lensPoint, spec.port) <= spec.radius; port.dataset.revealed = String((insideWindow || decisionWindow) && lensInside); if (!((insideWindow || decisionWindow) && lensInside)) return;
    port.querySelector(".port-from").textContent = spec.from_shell.replace("shell-", ""); port.querySelector(".port-to").textContent = spec.to_shell.replace("shell-", ""); const amount = insideWindow ? (model.tick - spec.window_start) / Math.max(1, spec.window_end - spec.window_start) : 1; port.querySelector("u").style.left = `${10 + amount * 80}%`; port.dataset.transfer = String(spec.from_shell !== spec.to_shell);
    const newPhysicalSample = insideWindow && !model.roundInspection.has(model.tick), lateSample = decisionWindow && !insideWindow && model.roundInspectionSamples < spec.minimum_samples; if (newPhysicalSample || lateSample) { const point = [...lensPoint]; record("inspection_sample", {round: model.roundIndex, tick: model.tick, point, from_shell: spec.from_shell, to_shell: spec.to_shell, late: decisionWindow && !insideWindow, late_sample_index: decisionWindow && !insideWindow ? model.roundInspectionSamples + 1 : undefined, ...inputDetails(model.interaction === "simplified" ? "peephole_relay_choice" : "direct_cursor")}); if (insideWindow) model.roundInspection.add(model.tick); model.roundInspectionSamples += 1; model.inspectionSamples += 1; document.querySelector(".shell-port-value").textContent = `${model.roundInspectionSamples}/${spec.minimum_samples}`; if (decisionWindow && model.roundInspectionSamples >= spec.minimum_samples) enableSelection(round); }
  }
  function enableSelection(round) {
    if (model.mode !== "select" || model.roundInspectionSamples < round.inspection.minimum_samples) return;
    if (model.interaction === "simplified") { document.querySelectorAll(".shell-proxy-select").forEach((button) => { button.disabled = false; }); } else { document.querySelectorAll(".shell-piece").forEach((shell) => { shell.disabled = false; shell.dataset.selectable = "true"; }); }
    const instruction = document.querySelector(".shell-mode"); instruction.dataset.mode = "select"; instruction.textContent = "STOP · SELECT THE TRUE CARRIER"; model.helpers.setReadout("SHUFFLE STOPPED · SELECT THE TRUE CARRIER", "pending");
  }
  function finishRound(startedAt) {
    const round = model.state.rounds[model.roundIndex]; if (model.interval) clearInterval(model.interval); model.interval = null; const elapsed = Math.round(performance.now() - startedAt); record("round_stop", {round: model.roundIndex, elapsed_ms: elapsed}); model.observedMs += elapsed; const banner = document.querySelector(".shell-stop-banner"); banner.dataset.visible = "true"; const instruction = document.querySelector(".shell-mode");
    model.mode = "select"; banner.querySelector("b").textContent = "SHUFFLE STOPPED"; banner.querySelector("span").textContent = "SELECT THE TRUE CARRIER"; instruction.dataset.mode = "select"; instruction.textContent = "STOP · SELECT THE TRUE CARRIER"; model.helpers.setReadout("SHUFFLE STOPPED · SELECT THE TRUE CARRIER", "pending"); enableSelection(round);
  }
  function startRound() {
    if (model.mode !== "ready" || model.submitting || model.terminal) return; document.querySelector(".shell-failure-stamp")?.remove(); const round = model.state.rounds[model.roundIndex]; record("round_start", {round: model.roundIndex}); model.mode = "preview"; const startedAt = performance.now(), start = document.querySelector(".shell-start-round"); start.disabled = true; document.querySelectorAll(".shell-inspection-relay").forEach((button) => { button.disabled = false; }); const mode = document.querySelector(".shell-mode"); mode.dataset.mode = "shuffle"; mode.textContent = "TOKEN ENTERING · TRACK CONTINUOUSLY"; const token = document.querySelector(".shell-token"), carrierStart = round.start_positions.find((item) => item.id === round.initial_carrier); token.dataset.entering = "true"; token.style.top = `${carrierStart.y / model.state.stage.height * 100}%`; model.helpers.setReadout("MARKED TOKEN ENTERING CARRIER…", "pending");
    model.previewTimer = setTimeout(() => { model.previewTimer = null; const token = document.querySelector(".shell-token"); token.dataset.visible = "false"; document.querySelectorAll(".shell-piece").forEach((shell) => shell.removeAttribute("data-marked")); model.mode = "shuffle"; model.helpers.setReadout("SHUFFLE ACTIVE · WATCH FOR THE PEEPHOLE PULSE", "pending"); model.interval = setInterval(() => { model.tick += 1; const frame = round.frames[model.tick - 1]; applyFrame(frame); const elapsed = Math.round(performance.now() - startedAt); record("round_tick", {round: model.roundIndex, tick: model.tick, elapsed_ms: elapsed, shells: frame.shells}); model.totalTicks += 1; updateInspection(round); document.querySelector(".shell-ticks-value").textContent = `${model.tick}/${round.frame_count}`; document.querySelector(".shell-timeline i").style.width = `${model.tick / round.frame_count * 100}%`; if (model.tick >= round.frame_count) finishRound(startedAt); }, round.tick_ms); }, round.preview_ms);
  }
  function selectShell(shellId, inputSource) {
    if (model.mode !== "select" || model.submitting || model.terminal) return;
    const round = model.state.rounds[model.roundIndex];
    if (!round.shell_ids.includes(shellId)) return;
    const expectedSource = model.interaction === "simplified" ? "carrier_controls" : "direct_shell";
    if (model.controlled && inputSource !== expectedSource) return;
    record("round_select", {round: model.roundIndex, shell_id: shellId, ...inputDetails(expectedSource)});
    model.choices.push({round: model.roundIndex, shell_id: shellId});
    model.mode = "transition";
    document.querySelectorAll(".shell-piece").forEach((shell) => { shell.disabled = true; shell.dataset.selectable = "false"; shell.dataset.chosen = shell.dataset.shellId === shellId ? "true" : "false"; });
    document.querySelectorAll(".shell-proxy-select").forEach((button) => { button.disabled = true; });
    const banner = document.querySelector(".shell-stop-banner");
    banner.querySelector("b").textContent = "TRACK RECORDED";
    banner.querySelector("span").textContent = "IDENTITY HISTORY ERASING";
    model.helpers.setReadout(`ROUND ${model.roundIndex + 1} TRACK RECORDED`, "idle");
    setTimeout(() => {
      if (model.roundIndex < model.state.rounds.length - 1) {
        model.roundIndex += 1;
        renderRound();
        return;
      }
      const completedRounds = model.state.rounds.length;
      model.roundIndex = completedRounds;
      model.mode = "certify";
      document.querySelector(".shell-stage").innerHTML = `<div class="shell-erased"><b>${completedRounds} TRACKS SEALED</b><span>PATHS AND INSPECTION WINDOWS ERASED</span><i></i></div>`;
      document.querySelector(".shell-rounds-value").textContent = `${completedRounds}/${completedRounds}`;
      const mode = document.querySelector(".shell-mode");
      mode.dataset.mode = "certify";
      mode.textContent = `${countWord(completedRounds)} SEALED TRACKS · READY TO CERTIFY`;
      const start = document.querySelector(".shell-start-round");
      start.disabled = true;
      start.textContent = "ROUNDS COMPLETE";
      model.helpers.setReadout(`${countWord(completedRounds)} TRACKS SEALED · CERTIFY THE RECORD`, "passed");
    }, 480);
  }
  function armRelay(coverId) {
    if (model.interaction !== "simplified" || !["preview", "shuffle", "select"].includes(model.mode) || model.relayPort || model.submitting || model.terminal) return;
    const round = model.state.rounds[model.roundIndex], selected = relayPorts(round).find((item) => item.occluder_id === coverId); if (!selected) return;
    const point = [...selected.port]; model.relayPort = {occluder_id: selected.occluder_id, port: point}; model.lens = point; record("inspection_relay_arm", {round: model.roundIndex, occluder_id: selected.occluder_id, point, ...inputDetails("peephole_relay_choice")}); const lens = document.querySelector(".shell-lens"); if (lens) { lens.dataset.visible = "true"; lens.style.left = `${point[0] / model.state.stage.width * 100}%`; lens.style.top = `${point[1] / model.state.stage.height * 100}%`; } const cover = document.querySelector(`.shell-occluder[data-cover-id="${CSS.escape(selected.occluder_id)}"]`); if (cover) cover.dataset.relay = "true"; document.querySelectorAll(".shell-inspection-relay").forEach((button) => { button.disabled = true; }); model.helpers.setReadout("PEEPHOLE RELAY FIXED TO SELECTED COVER · WATCH THE PHYSICAL SHUTTLE", "pending"); if (model.mode === "select") updateInspection(round);
  }
  async function submit() {
    if (model.submitting || model.terminal) return;
    model.submitting = true;
    model.helpers.setReadout("RECONSTRUCTING PATHS, PEEPHOLE SAMPLES, AND SHUTTLE STATE…", "pending");
    try {
      const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({mechanic_id: model.state.mechanic_id, challenge_id: model.state.challenge_id, events: model.events, choices: model.choices, total_ticks: model.totalTicks, observed_ms: model.observedMs, rounds_completed: model.roundIndex, inspection_samples: model.inspectionSamples, rewind_count: model.rewindCount, completed: model.roundIndex === model.state.rounds.length})});
      const outcome = await response.json();
      if (outcome.passed === true) {
        model.terminal = true;
        document.querySelector(".occlusion-shell-v2-captcha")?.insertAdjacentHTML("beforeend", `<div class="shell-verdict"><span>${countWord(model.state.rounds.length)} PHYSICAL CARRIER HISTORIES AUTHENTICATED</span><strong>PASS</strong><small>PATH · PEEPHOLE · SHUTTLE REPLAY VERIFIED</small></div>`);
        model.helpers.setReadout("PASS", "passed");
      } else if (outcome.passed === false && outcome.state) {
        await model.helpers.render(outcome.state);
        const shell = document.querySelector(".occlusion-shell-v2-captcha");
        shell?.setAttribute("data-fresh-failure", "true");
        shell?.insertAdjacentHTML("afterbegin", '<div class="shell-failure-stamp"><b>FAIL</b><span>TRACK REJECTED · FRESH SWINDLE ISSUED</span></div>');
        const readout = document.querySelector(".readout");
        readout.textContent = model.state.rounds.length === 3 ? "FAIL · FRESH THREE-ROUND SWINDLE ISSUED" : "FAIL · FRESH TRACKING SWINDLE ISSUED";
        readout.dataset.status = "error";
      } else {
        model.submitting = false;
        model.helpers.setReadout("FAIL · NO AUTHORITATIVE GRADE", "error");
      }
    } catch (_error) {
      model.submitting = false;
      model.helpers.setReadout("FAIL · TRACKING VERIFIER OFFLINE", "error");
    }
  }
  async function render(state, helpers) {
    if (model?.interval) clearInterval(model.interval); if (model?.previewTimer) clearTimeout(model.previewTimer); document.body.dataset.mechanic = "occlusion-shell-v2"; document.body.dataset.cheatMode = helpers.isCheatMode() ? "true" : "false"; const interaction = state.control_condition?.interaction || "full"; model = {state, helpers, interaction, controlled: Boolean(state.control_condition), events: [], roundIndex: 0, mode: "ready", tick: 0, interval: null, previewTimer: null, choices: [], totalTicks: 0, observedMs: 0, inspectionSamples: 0, rewindCount: 0, roundInspection: new Set(), roundInspectionSamples: 0, lens: null, relayPort: null, submitting: false, terminal: false}; window.occlusionShellV2Model = model;
    const roundCount = state.rounds.length;
    const proxyControls = interaction === "simplified" ? `<section class="shell-proxy-controls" aria-label="Shell interaction controls"><div class="shell-relay-controls" aria-label="Visible peephole relay choices"></div><div class="shell-carrier-controls" aria-label="Carrier selection">${state.rounds[0].shell_ids.map((shellId) => `<button type="button" class="shell-proxy-select" data-shell-id="${clean(shellId)}" disabled>SELECT ${clean(shellId.replace("shell-", ""))}</button>`).join("")}</div></section>` : "";
    helpers.app.innerHTML = `<section class="occlusion-shell-v2-captcha" data-challenge-id="${clean(state.challenge_id)}" data-interaction="${clean(interaction)}"><header class="shell-head"><div><span>OCCLUSION AUDIT / SWINDLE ${clean(state.challenge_id)}</span><h1>${clean(state.prompt)}</h1></div><div class="shell-round-strip"><div><b>01</b><span>MARK ENTERS</span></div><div><b>02</b><span>TRACK + PEEP</span></div><div><b>03</b><span>CHOOSE AT STOP</span></div></div></header><main class="shell-main"><section class="shell-stage"></section><aside class="shell-console"><p>CONTINUITY LEDGER</p><h2>The cover is opaque.<br>The shuttle is not.</h2><div class="shell-round-card"><span class="shell-round-label">TRACKING ROUND 1 / ${roundCount}</span><b class="shell-duration">8.0 SEC</b><i>LIVE PHYSICAL TIMELINE</i></div><div class="shell-stats"><div><span>SEALED ROUNDS</span><b class="shell-rounds-value">0/${roundCount}</b></div><div><span>OBSERVED FRAMES</span><b class="shell-ticks-value">0/60</b></div><div><span>PEEPHOLE SAMPLES</span><b class="shell-port-value">0/3</b></div></div><div class="shell-timeline"><span>ROUND TIMELINE</span><b><i></i></b></div><div class="shell-mode" data-mode="preview">MARK VISIBLE · MEMORIZE ITS CARRIER</div><button type="button" class="shell-start-round">BEGIN ROUND 1</button>${proxyControls}<ol><li><b>1</b><span>Follow the marked carrier through the shuffle.</span></li><li><b>2</b><span>When the brass peephole pulses, inspect its physical shuttle.</span></li><li><b>3</b><span>The bead shows which engraved rail exits with the token.</span></li></ol></aside></main><footer class="shell-foot"><div><span>ROUND SECURITY</span><b>INSPECTION REQUIRED</b></div><div><span>TRACKING RECORD</span><div class="readout" data-status="idle">ROUND 1 READY · MARKED TOKEN VISIBLE</div></div><button type="button" class="shell-certify">${clean(state.submit_label)}</button></footer>${helpers.cheatPanelTemplate()}</section>`;
    const stage = document.querySelector(".shell-stage");
    if (interaction === "full") {
      stage.addEventListener("click", (event) => { const shell = event.target.closest(".shell-piece"); if (shell) selectShell(shell.dataset.shellId, "direct_shell"); });
      stage.addEventListener("pointermove", (event) => { model.lens = stagePoint(event); const lens = document.querySelector(".shell-lens"); if (lens) { lens.dataset.visible = "true"; lens.style.left = `${model.lens[0]/model.state.stage.width*100}%`; lens.style.top = `${model.lens[1]/model.state.stage.height*100}%`; } updateInspection(model.state.rounds[model.roundIndex]); });
    } else {
      document.querySelector(".shell-relay-controls").addEventListener("click", (event) => { const relay = event.target.closest(".shell-inspection-relay"); if (relay) armRelay(relay.dataset.coverId); });
      document.querySelectorAll(".shell-proxy-select").forEach((button) => button.addEventListener("click", () => selectShell(button.dataset.shellId, "carrier_controls")));
      stage.addEventListener("pointermove", () => { if (model.mode === "select") updateInspection(model.state.rounds[model.roundIndex]); });
    }
    document.querySelector(".shell-start-round").addEventListener("click", startRound); document.querySelector(".shell-certify").addEventListener("click", submit); renderRound(); helpers.installCheatPanel();
  }
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.occlusion_shell_swindle_nonrealtime = {rootSelector: ".occlusion-shell-v2-captcha", render};
})();
