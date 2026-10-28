(() => {
  "use strict";

  const MECHANIC_ID = "reverse_identity_gate_nonrealtime";
  let bridge = null;
  let cleanupActive = null;

  const esc = (value) => String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const angle = (value) => ((value % 360) + 360) % 360;
  const error = (first, second) => Math.abs(((first - second + 540) % 360) - 180);
  const sign = (value) => value > 0 ? 1 : value < 0 ? -1 : 0;

  function record(type, details = {}) {
    bridge.events.push({seq: bridge.events.length + 1, type, ...details});
  }

  function clearFreshFailure() {
    const root = document.querySelector(".robot-master");
    if (root?.dataset.freshFailure === "true") root.dataset.freshFailure = "false";
  }

  function noteFocus(stationId) {
    if (!bridge || bridge.lastFocusedStation === stationId || !bridge.deployed.has(stationId)) return;
    bridge.lastFocusedStation = stationId;
    record("focus", {station: stationId});
  }

  function stage() {
    return bridge.state.stages[bridge.stageIndex] || null;
  }

  function stationMeta(stationId) {
    return bridge.state.stations.find((item) => Number(item.id) === Number(stationId));
  }

  function stationStatus(stationId) {
    if (!bridge.deployed.has(stationId)) return "UNDEPLOYED";
    if (bridge.stageIndex >= bridge.state.stages.length) return "HANDSHAKE SEALED";
    if (Number(stage().station) === stationId) return "LIVE RELAY";
    const completedForStation = bridge.state.stages.slice(0, bridge.stageIndex).filter((item) => Number(item.station) === stationId).length;
    return completedForStation >= stationRelayCount(stationId) ? "SEALED" : "STANDBY";
  }

  function stationRelayCount(stationId) {
    return bridge.state.stages.filter((item) => Number(item.station) === stationId).length;
  }

  function relayPhrase(count) {
    return count === 8 ? "EIGHT RELAYS" : `ALL ${count} RELAYS`;
  }

  function mainPaint() {
    if (!bridge) return;
    const current = stage();
    document.querySelectorAll("[data-deploy]").forEach((button) => {
      const id = Number(button.dataset.deploy);
      const known = bridge.deployed.has(id);
      const deployed = known && bridge.tabs.get(id) && !bridge.tabs.get(id).closed;
      button.dataset.deployed = String(Boolean(deployed));
      button.disabled = Boolean(deployed) || bridge.submitting || bridge.terminal || (!known && bridge.deployed.size !== id);
      const status = button.querySelector("em");
      if (status) status.textContent = deployed ? "TAB ONLINE" : known ? "REOPEN TAB" : bridge.deployed.size === id ? "DEPLOY TAB" : "INTERLOCKED";
    });
    document.querySelectorAll("[data-limb]").forEach((limb) => {
      const id = Number(limb.dataset.limb);
      const configured = bridge.state.stations.some((station) => Number(station.id) === id);
      limb.hidden = !configured;
      limb.dataset.deployed = String(configured && bridge.deployed.has(id));
      limb.dataset.active = String(configured && Boolean(current && Number(current.station) === id));
      limb.dataset.sealed = String(configured && bridge.state.stages.slice(0, bridge.stageIndex).filter((item) => Number(item.station) === id).length >= stationRelayCount(id));
    });
    const glyph = document.getElementById("robot-next-glyph");
    const station = current ? stationMeta(Number(current.station)) : null;
    if (glyph) {
      glyph.textContent = station ? station.glyph : "✓";
      glyph.style.setProperty("--station-color", station ? station.color : "#b8ff58");
    }
    const stageLabel = document.getElementById("robot-stage-label");
    if (stageLabel) stageLabel.textContent = current ? `RELAY ${bridge.stageIndex + 1} / ${bridge.state.stages.length}` : "IDENTITY COMPLETE";
    const deployment = document.getElementById("robot-deployment-count");
    if (deployment) deployment.textContent = `${bridge.deployed.size}/${bridge.state.stations.length}`;
    const relays = document.getElementById("robot-relay-count");
    if (relays) relays.textContent = `${bridge.stageIndex}/${bridge.state.stages.length}`;
    const master = document.querySelector(".robot-master");
    if (master) master.dataset.ready = String(bridge.stageIndex === bridge.state.stages.length);
    const verify = document.getElementById("robot-verify");
    if (verify) verify.disabled = bridge.submitting || bridge.terminal;
  }

  function tabPaint(stationId) {
    if (!bridge) return;
    const tab = bridge.tabs.get(stationId);
    if (!tab || tab.closed) return;
    let doc;
    try { doc = tab.document; } catch (_error) { return; }
    const current = stage();
    const isActive = Boolean(current && Number(current.station) === stationId);
    const root = doc.querySelector(".robot-station");
    if (!root) return;
    root.dataset.active = String(isActive);
    root.dataset.status = stationStatus(stationId).toLowerCase().replaceAll(" ", "-");
    const status = doc.getElementById("station-status");
    if (status) status.textContent = stationStatus(stationId);
    const stageLabel = doc.getElementById("station-stage");
    if (stageLabel) {
      const sealed = bridge.state.stages.slice(0, bridge.stageIndex).filter((item) => Number(item.station) === stationId).length;
      stageLabel.textContent = isActive ? `RELAY ${bridge.stageIndex + 1} / ${bridge.state.stages.length}` : `SEALED ${sealed} / ${stationRelayCount(stationId)}`;
    }
    const pulse = doc.getElementById("station-pulse");
    const receiver = doc.getElementById("station-receiver");
    const errorLabel = doc.getElementById("station-error");
    const chargeLabel = doc.getElementById("station-charge-label");
    const chargeFill = doc.getElementById("station-charge-fill");
    const timer = doc.getElementById("station-tick");
    const direction = doc.getElementById("station-direction");
    const contact = doc.getElementById("station-contact");
    if (pulse) pulse.style.transform = `rotate(${bridge.pulse}deg)`;
    if (receiver) receiver.style.transform = `rotate(${bridge.receiver}deg)`;
    const phaseError = error(bridge.receiver, bridge.pulse);
    if (errorLabel) errorLabel.textContent = isActive ? `${phaseError}°` : "—";
    if (chargeLabel) chargeLabel.textContent = `${bridge.charge}/${Number(bridge.state.physics.hold_ticks)}`;
    if (chargeFill) chargeFill.style.width = `${bridge.charge / Number(bridge.state.physics.hold_ticks) * 100}%`;
    if (timer) timer.textContent = String(bridge.stageTick).padStart(3, "0");
    if (direction) direction.textContent = bridge.direction < 0 ? "A / CCW" : bridge.direction > 0 ? "D / CW" : "NEUTRAL";
    if (contact) {
      contact.disabled = !isActive || bridge.submitting || bridge.terminal;
      contact.dataset.contact = String(bridge.contact && isActive);
    }
    doc.querySelectorAll("[data-station-drive]").forEach((button) => {
      button.disabled = !isActive || bridge.submitting || bridge.terminal;
      button.dataset.active = String(Number(button.dataset.stationDrive) === bridge.direction && isActive);
    });
    root.dataset.locked = String(bridge.locked && isActive);
    root.dataset.direction = String(bridge.direction);
  }

  function paintAll() {
    mainPaint();
    for (const stationId of bridge?.deployed || []) tabPaint(stationId);
  }

  function setDirection(stationId, next, inputSource) {
    const current = stage();
    if (!bridge || !current || Number(current.station) !== stationId || bridge.submitting || bridge.terminal) return;
    if (![-1, 0, 1].includes(next) || next === bridge.direction) return;
    noteFocus(stationId);
    const before = bridge.direction;
    bridge.direction = next;
    record("key", {stage: bridge.stageIndex, station: stationId, before, after: next, input_source: inputSource});
    tabPaint(stationId);
    if (bridge.contact) startActionWindow(stationId);
  }

  function setContact(stationId, next, inputSource) {
    const current = stage();
    if (!bridge || !current || Number(current.station) !== stationId || bridge.submitting || bridge.terminal) return;
    if (Boolean(next) === bridge.contact) return;
    const before = bridge.contact;
    bridge.contact = Boolean(next);
    record("contact", {stage: bridge.stageIndex, station: stationId, before, after: bridge.contact, input_source: inputSource});
    tabPaint(stationId);
    if (bridge.contact) startActionWindow(stationId);
  }

  function relay() {
    if (bridge.settleDriver) {
      bridge.settleDriver.cancelled = true;
      bridge.settleDriver = null;
    }
    const completed = stage();
    const completedIndex = bridge.stageIndex;
    record("relay", {
      stage: completedIndex,
      station: Number(completed.station),
      tick: bridge.stageTick,
      charge: bridge.charge,
      next_station: bridge.state.stages[completedIndex + 1]?.station ?? null,
    });
    bridge.stageIndex += 1;
    bridge.stageTick = 0;
    bridge.direction = 0;
    bridge.contact = false;
    bridge.charge = 0;
    bridge.locked = false;
    const next = stage();
    if (next) {
      bridge.pulse = Number(next.pulse_start_deg);
      bridge.receiver = Number(next.receiver_initial_deg);
      const target = stationMeta(Number(next.station));
      bridge.helpers.setReadout(`RELAY ${completedIndex + 1} SEALED · SWITCH TO ${target.glyph} TAB`, "passed");
      try { bridge.tabs.get(Number(next.station))?.focus(); } catch (_error) { /* browser may refuse programmatic focus */ }
    } else {
      bridge.helpers.setReadout(`${relayPhrase(bridge.state.stages.length)} SEALED · RETURN TO MASTER TAB`, "passed");
      try { window.focus(); } catch (_error) { /* best effort only */ }
    }
    paintAll();
  }

  function tickActive() {
    if (!bridge || bridge.submitting || bridge.terminal) return;
    mainPaint();
    if (bridge.deployed.size !== bridge.state.stations.length) return;
    const current = stage();
    if (!current) return;
    bridge.stageTick += 1;
    bridge.totalTicks += 1;
    bridge.pulse = angle(bridge.pulse + Number(current.pulse_speed_deg_per_tick));
    bridge.receiver = angle(bridge.receiver + bridge.direction * Number(bridge.state.physics.receiver_control_deg_per_tick));
    let phaseError = error(bridge.receiver, bridge.pulse);
    bridge.locked = bridge.contact
      && bridge.direction === sign(Number(current.pulse_speed_deg_per_tick))
      && phaseError <= Number(bridge.state.physics.capture_tolerance_deg);
    if (bridge.locked) {
      bridge.receiver = bridge.pulse;
      phaseError = 0;
      bridge.charge += 1;
    } else {
      bridge.charge = Math.max(0, bridge.charge - Number(bridge.state.physics.charge_decay_per_tick));
    }
    record("tick", {
      stage: bridge.stageIndex,
      station: Number(current.station),
      tick: bridge.stageTick,
      state: {
        pulse_deg: bridge.pulse,
        receiver_deg: bridge.receiver,
        error_deg: phaseError,
        charge: bridge.charge,
        locked: bridge.locked,
        direction: bridge.direction,
        contact: bridge.contact,
      },
    });
    tabPaint(Number(current.station));
    mainPaint();
    if (bridge.charge >= Number(bridge.state.physics.hold_ticks)) relay();
  }

  function actionWindowTicks() {
    const physics = bridge.state.physics;
    return Math.min(
      Number(physics.maximum_ticks_per_stage),
      Math.max(Number(physics.hold_ticks) * 6, 420),
    );
  }

  function startActionWindow(stationId) {
    if (!bridge || bridge.submitting || bridge.terminal || bridge.settleDriver) return;
    if (bridge.deployed.size !== bridge.state.stations.length) return;
    const current = stage();
    const tab = bridge.tabs.get(stationId);
    if (!current || Number(current.station) !== stationId || !tab || tab.closed) return;
    const remaining = Math.min(
      actionWindowTicks(),
      Number(bridge.state.physics.maximum_ticks_per_stage) - bridge.stageTick,
    );
    if (remaining <= 0) return;
    const driver = {owner: tab, frame: 0, cancelled: false, remaining};
    const pump = () => {
      if (driver.cancelled || !bridge || bridge.terminal || bridge.submitting) return;
      if (driver.remaining <= 0 || !stage()) {
        if (bridge.settleDriver === driver) bridge.settleDriver = null;
        tabPaint(stationId);
        return;
      }
      tickActive();
      driver.remaining -= 1;
      if (driver.cancelled || bridge.settleDriver !== driver || !stage()) return;
      driver.frame = tab.requestAnimationFrame(pump);
    };
    bridge.settleDriver = driver;
    driver.frame = tab.requestAnimationFrame(pump);
  }

  function clearTickDrivers(current) {
    if (!current) return;
    if (current.settleDriver) {
      current.settleDriver.cancelled = true;
      try { current.settleDriver.owner.cancelAnimationFrame(current.settleDriver.frame); } catch (_error) { /* closed tab */ }
      current.settleDriver = null;
    }
  }

  function stationDocument(station) {
    const stylesheet = new URL("mechanics/reverse_identity_gate_nonrealtime.css", window.location.href).href;
    const simplified = bridge.interaction === "simplified";
    return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(station.glyph)} ${esc(station.name)}</title><link rel="stylesheet" href="${esc(stylesheet)}"></head><body class="robot-station-body"><main class="robot-station" data-station-page="${station.id}" data-active="false" data-status="standby" data-locked="false" style="--station-color:${esc(station.color)}">
      <header><div><span>DISTRIBUTED IDENTITY LIMB / 0${station.id + 1}</span><h1>${esc(station.glyph)} ${esc(station.name)}</h1></div><b id="station-status">STANDBY</b></header>
      <section class="station-bench">
        <div class="phase-apparatus">
          <div class="phase-orbit"><div id="station-pulse" class="phase-pulse"><i></i></div><div id="station-receiver" class="phase-receiver"><i></i></div><div class="phase-core"><span>PHASE<br>LOCK</span><b id="station-error">—</b></div></div>
          <div class="phase-scale">${Array.from({length:36},(_,index)=>`<i style="--n:${index}"></i>`).join("")}</div>
        </div>
        <aside class="station-console">
          <div class="station-stage"><span id="station-stage">SEALED 0 / 2</span><b>TICK <i id="station-tick">000</i></b></div>
          <div class="drive-readout"><span>RECEIVER DRIVE</span><b id="station-direction">NEUTRAL</b><small>${simplified ? "VISIBLE DIRECTION CONTROLS" : "A / D"}</small></div>
          ${simplified ? `<div class="station-drive-buttons"><button type="button" data-station-drive="-1">CCW</button><button type="button" data-station-drive="0">NEUTRAL</button><button type="button" data-station-drive="1">CW</button></div>` : ""}
          <button type="button" id="station-contact" class="station-contact" data-contact="false"><i></i><span>${simplified ? "TOGGLE CONTACT" : "HOLD CONTACT"}</span><small>${simplified ? "CLICK TO LOCK / RELEASE" : "MOUSE PRESS"}</small></button>
          <div class="station-charge"><header><span>RELAY CHARGE</span><b id="station-charge-label">0/${bridge.state.physics.hold_ticks}</b></header><div><i id="station-charge-fill"></i></div></div>
          <p>DIRECTIONAL PHASE BUS / CONTACT DECAYS OUTSIDE CAPTURE APERTURE</p>
        </aside>
      </section>
      <footer><span>${simplified ? "CCW / NEUTRAL / CW" : "A ← RECEIVER → D"}</span><b>KEEP THIS REAL TAB OPEN</b><span>CONTACT DRAINS ON PHASE LOSS</span></footer>
    </main></body></html>`;
  }

  function installTab(stationId, tab) {
    const station = stationMeta(stationId);
    const doc = tab.document;
    doc.open();
    doc.write(stationDocument(station));
    doc.close();
    const focus = () => {
      if (!bridge || bridge.terminal || bridge.submitting) return;
      noteFocus(stationId);
      tabPaint(stationId);
    };
    tab.addEventListener("focus", focus);
    const contact = doc.getElementById("station-contact");
    if (bridge.interaction === "simplified") {
      doc.querySelectorAll("[data-station-drive]").forEach((button) => button.addEventListener("click", () => {
        setDirection(stationId, Number(button.dataset.stationDrive), "direction_button");
      }));
      contact.addEventListener("click", () => setContact(stationId, !bridge.contact, "contact_toggle"));
    } else {
      doc.addEventListener("keydown", (event) => {
        if (event.repeat) return;
        if (event.key.toLowerCase() === "a" || event.key === "ArrowLeft") {
          event.preventDefault();
          setDirection(stationId, -1, "keyboard");
        } else if (event.key.toLowerCase() === "d" || event.key === "ArrowRight") {
          event.preventDefault();
          setDirection(stationId, 1, "keyboard");
        }
      }, true);
      doc.addEventListener("keyup", (event) => {
        if ((event.key.toLowerCase() === "a" || event.key === "ArrowLeft") && bridge?.direction === -1) {
          event.preventDefault();
          setDirection(stationId, 0, "keyboard");
        } else if ((event.key.toLowerCase() === "d" || event.key === "ArrowRight") && bridge?.direction === 1) {
          event.preventDefault();
          setDirection(stationId, 0, "keyboard");
        }
      }, true);
      contact.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        contact.setPointerCapture(event.pointerId);
        setContact(stationId, true, "pointer_hold");
      });
      const release = (event) => {
        event?.preventDefault();
        setContact(stationId, false, "pointer_hold");
      };
      contact.addEventListener("pointerup", release);
      contact.addEventListener("pointercancel", release);
      contact.addEventListener("lostpointercapture", release);
    }
    tabPaint(stationId);
  }

  function deploy(stationId) {
    if (!bridge || bridge.submitting || bridge.terminal) return;
    const known = bridge.deployed.has(stationId);
    const existing = bridge.tabs.get(stationId);
    if ((!known && stationId !== bridge.deployed.size) || (known && existing && !existing.closed)) return;
    clearFreshFailure();
    const name = `robot-handshake-${bridge.state.challenge_id}-${stationId}`;
    const tab = window.open("about:blank", name);
    if (!tab) {
      bridge.helpers.setReadout("POP-UP BLOCKED · ALLOW THIS EXPLICIT TAB", "error");
      return;
    }
    bridge.tabs.set(stationId, tab);
    if (!known) {
      bridge.deployed.add(stationId);
      record("deploy", {station: stationId, deployed_count: bridge.deployed.size});
    }
    installTab(stationId, tab);
    const station = stationMeta(stationId);
    const allDeployed = bridge.deployed.size === bridge.state.stations.length;
    bridge.helpers.setReadout(known ? `${station.glyph} LIMB RESTORED · RELAY STATE PRESERVED` : allDeployed ? `${bridge.state.stations.length === 4 ? "FOUR" : bridge.state.stations.length} LIMBS ONLINE · FOLLOW THE MASTER GLYPH` : `${station.glyph} TAB ONLINE · DEPLOY NEXT LIMB`, "idle");
    if (!known && allDeployed) {
      const first = stage();
      try { bridge.tabs.get(Number(first.station))?.focus(); } catch (_error) { /* best effort */ }
    }
    paintAll();
  }

  async function verify() {
    if (!bridge || bridge.submitting || bridge.terminal) return;
    record("verify", {completed_stages: bridge.stageIndex, deployed: [...bridge.deployed].sort((a,b) => a-b)});
    const current = bridge;
    current.submitting = true;
    current.helpers.setReadout("MERGING FOUR TAB LEDGERS…", "pending");
    paintAll();
    try {
      const response = await fetch("/result", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({
          mechanic_id: MECHANIC_ID,
          task_id: current.state.task_id,
          challenge_id: current.state.challenge_id,
          events: current.events,
          completed: current.stageIndex === current.state.stages.length,
        }),
      });
      const outcome = await response.json();
      if (outcome.passed === true) {
        current.terminal = true;
        clearTickDrivers(current);
        current.helpers.setReadout("PASS", "passed");
        document.querySelector(".robot-master")?.setAttribute("data-verdict", "pass");
        paintAll();
      } else if (outcome.passed === false && outcome.state) {
        const helpers = current.helpers;
        await render(outcome.state, helpers, {freshFailure: true});
        bridge.helpers.setReadout("FAIL · DISTRIBUTED IDENTITY RESET", "error");
      } else {
        current.submitting = false;
        current.helpers.setReadout("LEDGER REJECTED", "error");
        paintAll();
      }
    } catch (_error) {
      if (bridge === current) {
        current.submitting = false;
        current.helpers.setReadout("IDENTITY BUS OFFLINE", "error");
        paintAll();
      }
    }
  }

  async function render(state, helpers, options = {}) {
    if (cleanupActive) cleanupActive();
    document.body.dataset.mechanic = "distributed-robot-handshake";
    document.body.dataset.cheatMode = helpers.isCheatMode() ? "true" : "false";
    bridge = {
      state,
      helpers,
      interaction: state.control_condition?.interaction || "full",
      events: [],
      tabs: new Map(),
      deployed: new Set(),
      stageIndex: 0,
      stageTick: 0,
      totalTicks: 0,
      pulse: Number(state.stages[0].pulse_start_deg),
      receiver: Number(state.stages[0].receiver_initial_deg),
      direction: 0,
      contact: false,
      charge: 0,
      locked: false,
      lastFocusedStation: null,
      submitting: false,
      terminal: false,
      settleDriver: null,
    };
    window.robotHandshakeBridge = bridge;
    helpers.app.innerHTML = `<section class="robot-master palette-${esc(state.palette)}" data-interaction="${esc(bridge.interaction)}" data-fresh-failure="${options.freshFailure ? "true" : "false"}" data-verdict="" data-ready="false">
      <div class="robot-verdict"><b>${options.freshFailure ? "IDENTITY FAIL" : ""}</b><span>${options.freshFailure ? "ALL LIMBS RECALLED" : ""}</span></div>
      <header class="robot-master-head"><div><span>NON-HUMAN ACCESS AUTHORITY / ${esc(state.challenge_id)}</span><h1>${esc(state.prompt)}</h1></div><aside><i id="robot-next-glyph">${esc(state.stations[Number(state.stages[0].station)].glyph)}</i><span id="robot-stage-label">RELAY 1 / 8</span></aside></header>
      <main class="robot-master-bench">
        <section class="robot-figure-panel">
          <div class="robot-figure">
            <div class="robot-limb robot-head" data-limb="1"><i>◇</i><span>OPTIC HEAD</span></div>
            <div class="robot-limb robot-left" data-limb="0"><i>◢</i><span>PORT ARM</span></div>
            <div class="robot-limb robot-core" data-limb="2"><i>⌁</i><span>DRIVE CORE</span></div>
            <div class="robot-limb robot-right" data-limb="3"><i>◩</i><span>STARBOARD ARM</span></div>
            <svg viewBox="0 0 640 420" aria-hidden="true"><path d="M319 87v52M195 194h92M353 194h92M320 256v78M320 334l-72 61M320 334l72 61"/><circle cx="320" cy="210" r="102"/><circle cx="320" cy="210" r="70"/></svg>
            <div class="robot-next"><span>NEXT TAB</span><b>FOLLOW THE PULSING GLYPH</b></div>
          </div>
          <div class="robot-master-stats"><span>LIMBS <b id="robot-deployment-count">0/${state.stations.length}</b></span><span>RELAYS <b id="robot-relay-count">0/${state.stages.length}</b></span><span>TOPOLOGY <b>REAL TABS</b></span></div>
        </section>
        <aside class="robot-deployment-rack"><header><span>DEPLOYMENT INTERLOCK</span><p>SEQUENTIAL LIMB BUS / ${state.stations.length === 4 ? "FOUR" : state.stations.length} LIVE TABS REQUIRED</p></header>
          ${state.stations.map((station) => `<button type="button" data-deploy="${station.id}" data-deployed="false" style="--station-color:${esc(station.color)}"><i>${esc(station.glyph)}</i><span><b>${esc(station.name)}</b><small>LIMB 0${station.id + 1}</small></span><em>${station.id === 0 ? "DEPLOY TAB" : "INTERLOCKED"}</em></button>`).join("")}
          <div class="robot-seal"><i>${state.stations.length}×</i><span>ONE IDENTITY<br><b>${state.stations.length === 4 ? "FOUR WINDOWS" : `${state.stations.length} WINDOWS`}</b></span></div>
        </aside>
      </main>
      <footer class="robot-master-foot"><div class="readout" data-status="idle">DEPLOY LIMB 01</div><button type="button" id="robot-verify">${esc(state.submit_label || "VERIFY IDENTITY")}</button></footer>
      ${helpers.cheatPanelTemplate()}
    </section>`;
    document.querySelectorAll("[data-deploy]").forEach((button) => button.addEventListener("click", () => deploy(Number(button.dataset.deploy))));
    document.getElementById("robot-verify").addEventListener("click", verify);
    cleanupActive = () => {
      clearTickDrivers(bridge);
      for (const tab of bridge?.tabs?.values() || []) {
        try { if (!tab.closed) tab.close(); } catch (_error) { /* no-op */ }
      }
      cleanupActive = null;
    };
    mainPaint();
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics[MECHANIC_ID] = {rootSelector: ".robot-master", render};
  window.addEventListener("beforeunload", () => { if (cleanupActive) cleanupActive(); });
})();
