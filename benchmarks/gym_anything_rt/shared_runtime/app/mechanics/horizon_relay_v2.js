(() => {
  "use strict";
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};

  const TAU = Math.PI * 2;
  const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[char]));
  const num = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const add = (a, b) => ({x: a.x + b.x, y: a.y + b.y, z: a.z + b.z});
  const sub = (a, b) => ({x: a.x - b.x, y: a.y - b.y, z: a.z - b.z});
  const dot = (a, b) => a.x * b.x + a.y * b.y + a.z * b.z;
  const length = (a) => Math.sqrt(dot(a, a));
  const unit = (a) => { const n = length(a) || 1; return {x: a.x / n, y: a.y / n, z: a.z / n}; };
  const deg = (radians) => radians * 180 / Math.PI;
  const rad = (degrees) => degrees * Math.PI / 180;

  function render(state, helpers) {
    if (window.horizonRelayV2Model?.timer) clearInterval(window.horizonRelayV2Model.timer);
    const interaction = String(state.control_condition?.interaction || state.interaction_mode || "full");
    const root = helpers.app;
    const planetRadius = num(state.planet?.radius, 150);
    const speed = num(state.rotation?.speed_deg_per_tick, 0.4);
    const tolerance = num(state.aim_tolerance_deg, 12);
    const stations = Array.isArray(state.stations) ? state.stations : [];
    const craft = Array.isArray(state.spacecraft) ? state.spacecraft : [];
    const model = {
      state, helpers, interaction, planetRadius, speed, tolerance, stations, craft,
      tick: 0, angle: 0, active: null, aim: null, selectedStation: null,
      progress: Object.fromEntries(craft.map((item) => [String(item.id), 0])),
      completed: new Set(), events: [], seq: 0, timer: null, dragging: null,
      submitted: false, failed: false,
    };

    document.body.dataset.mechanic = "horizon-relay-v2";
    root.innerHTML = `
      <section class="hr-shell" data-interaction="${esc(interaction)}" data-challenge-id="${esc(state.challenge_id)}">
        <header class="hr-header">
          <div><p class="hr-kicker">DEEP SPACE NETWORK / HORIZON RELAY</p><h1>Keep the signal above the curve of Earth.</h1><p class="hr-prompt">${esc(state.prompt)}</p></div>
          <div class="hr-status"><span class="hr-live-dot"></span><b class="hr-status-text">TRACKING GLOBE</b><small>tick <b class="hr-tick">0</b></small></div>
        </header>
        <main class="hr-layout">
          <section class="hr-stage-card">
            <div class="hr-stage-top"><span>ORBITAL VIEW / OUTWARD IS UP</span><span class="hr-mode">${interaction === "full" ? "FULL DISH CONTROL" : "SIMPLIFIED RELAY DESK"}</span></div>
            <div class="hr-stage-wrap"><svg id="horizon-relay-v2-stage" class="hr-stage" viewBox="0 0 800 560" role="img" aria-label="Three-dimensional rotating Earth with ground stations and spacecraft"></svg><div class="hr-stage-note">Front-facing markers are bright. Dim stations and spacecraft are on the far side; the pale horizon line is the local line-of-sight boundary.</div></div>
          </section>
          <aside class="hr-sidebar">
            <section class="hr-card hr-stations"><div class="hr-card-label">GROUND STATIONS <span class="hr-selected-station">NONE SELECTED</span></div><div class="hr-station-list"></div></section>
            <section class="hr-card hr-requests"><div class="hr-card-label">SPACECRAFT REQUESTS <span class="hr-delivery-count">0 / ${craft.length}</span></div><div class="hr-request-list"></div></section>
            <section class="hr-card hr-control-card"><div class="hr-card-label">${interaction === "full" ? "DIRECT DISH" : "PROXY RELAY DESK"}</div>${interaction === "full" ? `<p>Drag a bright station dish to a spacecraft marker. Drag again to refresh the pointing as the planet turns.</p>` : `<p>Select a station, choose a spacecraft above its horizon, then press HOLD LINK. The link stops when the local horizon or aim is lost.</p><div class="hr-proxy-row"><button id="hr-hold" type="button">HOLD LINK</button><button id="hr-stop" type="button">STOP</button></div>`}<div class="hr-link-readout">NO ACTIVE RELAY</div></section>
            <section class="hr-card hr-legend"><div class="hr-card-label">3D CHECK</div><p>Each station sits on the sphere's surface. A spacecraft is reachable only when its sightline leaves the station's outward hemisphere; a flat map would give the wrong handoff.</p><div class="hr-legend-diagram"><span class="hr-dot station-dot"></span><span>station</span><span class="hr-dot craft-dot"></span><span>spacecraft</span><span class="hr-dot horizon-dot"></span><span>above horizon</span></div></section>
          </aside>
        </main>
        <footer class="hr-footer"><div class="hr-readout" data-status="idle">SELECT A BRIGHT STATION AND READ ITS HORIZON.</div><button id="hr-certify" type="button">CERTIFY ALL RELAYS</button></footer>
      </section>`;

    const svg = root.querySelector("#horizon-relay-v2-stage");
    const readout = root.querySelector(".hr-readout");
    const tickNode = root.querySelector(".hr-tick");
    const statusNode = root.querySelector(".hr-status-text");

    function stationAt(station, tick = model.tick) {
      const lat = rad(num(station.latitude));
      const lon = rad(num(station.longitude)) + rad(state.rotation_angles_deg[tick]);
      return {x: planetRadius * Math.cos(lat) * Math.cos(lon), y: planetRadius * Math.sin(lat), z: planetRadius * Math.cos(lat) * Math.sin(lon)};
    }
    function craftAt(item) {
      const p = item.position || [0, 0, 0];
      return {x: num(p[0]), y: num(p[1]), z: num(p[2])};
    }
    function visible(station, item, tick = model.tick) {
      const s = stationAt(station, tick); const c = craftAt(item);
      return dot(s, sub(c, s)) > 0.0001;
    }
    function aimError(station, item, aim, tick = model.tick) {
      if (!aim) return Infinity;
      const target = sub(craftAt(item), stationAt(station, tick));
      const vector = {x: num(aim[0]), y: num(aim[1]), z: num(aim[2])};
      const denominator = length(target) * length(vector);
      if (!denominator) return Infinity;
      return deg(Math.acos(Math.max(-1, Math.min(1, dot(target, vector) / denominator))));
    }
    function project(point) {
      return {x: 400 + point.x * 0.90, y: 280 - point.y * 0.90, depth: point.z};
    }
    function craftById(id) { return craft.find((item) => String(item.id) === String(id)) || null; }
    function stationById(id) { return stations.find((item) => String(item.id) === String(id)) || null; }
    function say(message, status = "idle") { readout.dataset.status = status; readout.textContent = message; }
    function event(type, fields = {}) { model.seq += 1; model.events.push({seq: model.seq, type, tick: model.tick, ...fields}); }
    function clearPartial() {
      if (model.active && !model.completed.has(model.active.craftId)) model.progress[model.active.craftId] = 0;
    }
    function visiblePairs() {
      return stations.flatMap((station) => craft.filter((item) => visible(station, item)).map((item) => [String(station.id), String(item.id)]));
    }
    function snapshot() {
      const stationPoints = Object.fromEntries(stations.map((station) => { const point = project(stationAt(station)); return [String(station.id), point]; }));
      const craftPoints = Object.fromEntries(craft.map((item) => { const point = project(craftAt(item)); return [String(item.id), point]; }));
      return {tick: model.tick, active: model.active ? {...model.active} : null, progress: {...model.progress}, completed: Array.from(model.completed), pairs: visiblePairs(), stationPoints, craftPoints};
    }
    model.snapshot = snapshot;
    model.visible = visible;
    model.project = project;

    function sceneMarkup() {
      const planet = `<circle cx="400" cy="280" r="${planetRadius * .9}" class="hr-planet"/><circle cx="400" cy="280" r="${planetRadius * .9 + 22}" class="hr-atmosphere"/><ellipse cx="400" cy="280" rx="${planetRadius * .9}" ry="${planetRadius * .9 * .31}" class="hr-latitude"/><ellipse cx="400" cy="280" rx="${planetRadius * .9 * .31}" ry="${planetRadius * .9}" class="hr-longitude"/><path d="M 266 280 Q 400 212 534 280 Q 400 348 266 280" class="hr-horizon-line"/>`;
      const craftMarkup = craft.map((item) => {
        const p = project(craftAt(item)); const stationVisible = stations.some((station) => visible(station, item)); const done = model.completed.has(String(item.id));
        const progress = model.progress[item.id] || 0; const required = num(item.required_ticks, 1);
        return `<g class="hr-craft ${stationVisible ? "is-reachable" : "is-hidden"} ${done ? "is-done" : ""}" data-craft="${esc(item.id)}" transform="translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})"><circle r="26" class="hr-craft-halo"/><circle r="13" class="hr-craft-body" fill="${esc(item.color)}"/><text y="4" text-anchor="middle" class="hr-craft-icon">${esc(item.icon)}</text><text y="-25" text-anchor="middle" class="hr-craft-label">${esc(item.label)}</text><rect x="-28" y="31" width="56" height="5" rx="2" class="hr-progress-bg"/><rect x="-28" y="31" width="${(56 * Math.min(1, progress / required)).toFixed(2)}" height="5" rx="2" class="hr-progress"/></g>`;
      }).join("");
      const stationMarkup = stations.map((station) => {
        const p3 = stationAt(station); const p = project(p3); const front = p3.z >= -4; const selected = model.selectedStation === String(station.id); const active = model.active?.stationId === String(station.id);
        return `<g class="hr-station ${front ? "is-front" : "is-back"} ${selected ? "is-selected" : ""} ${active ? "is-active" : ""}" data-station="${esc(station.id)}" transform="translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})"><circle r="${active ? 22 : 18}" class="hr-station-ring"/><path d="M -10 7 L 0 -13 L 10 7 Z" class="hr-dish" fill="${esc(station.color)}"/><circle r="5" class="hr-station-core" fill="${esc(station.color)}"/><text y="-26" text-anchor="middle" class="hr-station-label">${esc(station.label)}</text></g>`;
      }).join("");
      let beam = "";
      if (model.active) {
        const station = stationById(model.active.stationId); const target = craftById(model.active.craftId);
        if (station && target) { const a = project(stationAt(station)); const b = project(craftAt(target)); beam = `<path d="M ${a.x.toFixed(2)} ${a.y.toFixed(2)} L ${b.x.toFixed(2)} ${b.y.toFixed(2)}" class="hr-beam"/>`; }
      }
      const ghost = model.dragging ? `<path d="M ${model.dragging.start.x.toFixed(2)} ${model.dragging.start.y.toFixed(2)} L ${model.dragging.current.x.toFixed(2)} ${model.dragging.current.y.toFixed(2)}" class="hr-ghost-beam"/>` : "";
      return `<defs><radialGradient id="hr-earth"><stop offset="0" stop-color="#2d7184"/><stop offset=".75" stop-color="#184a68"/><stop offset="1" stop-color="#102d4d"/></radialGradient><filter id="hr-glow"><feGaussianBlur stdDeviation="4"/></filter></defs><rect width="800" height="560" class="hr-space"/>${planet}<circle cx="400" cy="280" r="${planetRadius * .9 - 3}" fill="url(#hr-earth)" class="hr-earth-fill"/>${beam}${craftMarkup}${stationMarkup}${ghost}<text x="400" y="514" text-anchor="middle" class="hr-axis-caption">ROTATING Y AXIS · STATION HORIZON IS GEOMETRIC, NOT A MAP EDGE</text>`;
    }

    function renderScene() {
      svg.innerHTML = sceneMarkup();
      tickNode.textContent = String(model.tick);
      statusNode.textContent = model.active ? "RELAY ACTIVE" : "TRACKING GLOBE";
      statusNode.parentElement.classList.toggle("is-relaying", Boolean(model.active));
      root.querySelector(".hr-selected-station").textContent = model.selectedStation ? String(stationById(model.selectedStation)?.label || model.selectedStation) : "NONE SELECTED";
      root.querySelector(".hr-delivery-count").textContent = `${model.completed.size} / ${craft.length}`;
      root.querySelector(".hr-link-readout").textContent = model.active ? `LINK · ${stationById(model.active.stationId)?.label || "?"} → ${craftById(model.active.craftId)?.label || "?"}` : "NO ACTIVE RELAY";
      root.querySelector(".hr-station-list").innerHTML = stations.map((station) => {
        const pairs = craft.filter((item) => visible(station, item)).map((item) => item.label).join(" · ") || "none above horizon";
        const selected = model.selectedStation === String(station.id) ? "is-selected" : "";
        if (interaction === "full") return `<div class="hr-station-info ${selected}" data-station-info="${esc(station.id)}"><span class="hr-station-swatch" style="--swatch:${esc(station.color)}"></span><b>${esc(station.label)}</b><small>${esc(pairs)} · drag the globe dish</small></div>`;
        return `<button type="button" class="hr-station-button ${selected}" data-station-button="${esc(station.id)}"><span class="hr-station-swatch" style="--swatch:${esc(station.color)}"></span><b>${esc(station.label)}</b><small>${esc(pairs)}</small></button>`;
      }).join("");
      root.querySelector(".hr-request-list").innerHTML = craft.map((item) => {
        const done = model.completed.has(String(item.id)); const active = model.active?.craftId === String(item.id); const progress = model.progress[item.id] || 0;
        return `<div class="hr-request ${done ? "is-done" : ""} ${active ? "is-active" : ""}" data-craft-row="${esc(item.id)}"><div class="hr-request-top"><span class="hr-request-icon" style="--craft:${esc(item.color)}">${esc(item.icon)}</span><b>${esc(item.label)}</b><span>${progress}/${num(item.required_ticks)}</span></div><div class="hr-request-bar"><i style="width:${Math.min(100, 100 * progress / Math.max(1, num(item.required_ticks)))}%"></i></div>${interaction === "simplified" ? `<button type="button" class="hr-target-button" data-target-button="${esc(item.id)}" ${done ? "disabled" : ""}>AIM THIS CRAFT</button>` : `<small class="hr-craft-hint">${done ? "DELIVERED" : "drag a bright dish here"}</small>`}</div>`;
      }).join("");
      bindControls();
    }

    function bindControls() {
      root.querySelectorAll("[data-station-button]").forEach((button) => button.addEventListener("click", () => {
        const stationId = String(button.dataset.stationButton);
        if (model.active && model.active.stationId !== stationId) { event("link_stop", {input_source: "station_button"}); clearPartial(); model.active = null; }
        model.selectedStation = stationId; event("select_station", {station_id: stationId, input_source: "station_button"}); say(`${stationById(stationId).label} SELECTED · READ THE BRIGHT HORIZON TARGETS.`); renderScene();
      }));
      root.querySelectorAll("[data-target-button]").forEach((button) => button.addEventListener("click", () => {
        if (model.submitted) return;
        const station = stationById(model.selectedStation); const target = craftById(button.dataset.targetButton);
        if (!station || !target) { say("SELECT A GROUND STATION FIRST.", "error"); return; }
        if (!visible(station, target)) { say("THAT SPACECRAFT IS BELOW THIS STATION'S HORIZON.", "error"); return; }
        const aim = unit(sub(craftAt(target), stationAt(station)));
        if (model.active && model.active.craftId !== String(target.id)) { event("link_stop", {input_source: "target_button"}); clearPartial(); model.active = null; }
        model.aim = {stationId: String(station.id), craftId: String(target.id), vector: [aim.x, aim.y, aim.z]};
        event("aim", {station_id: String(station.id), craft_id: String(target.id), input_source: "target_button", aim_vector: model.aim.vector});
        say(`${station.label} DISH AIMED AT ${target.label} · PRESS HOLD LINK.`); renderScene();
      }));
      root.querySelector("#hr-hold")?.addEventListener("click", () => {
        if (model.submitted) return;
        if (!model.aim || !visible(stationById(model.aim.stationId), craftById(model.aim.craftId))) { say("AIM A VISIBLE SPACECRAFT BEFORE HOLDING.", "error"); return; }
        if (!model.active) { model.active = {stationId: model.aim.stationId, craftId: model.aim.craftId}; event("hold_start", {input_source: "hold_button", station_id: model.aim.stationId, craft_id: model.aim.craftId}); say("LINK HELD · WATCH THE HORIZON.", "active"); renderScene(); }
      });
      root.querySelector("#hr-stop")?.addEventListener("click", () => { if (model.active) { event("link_stop", {input_source: "stop_button"}); clearPartial(); model.active = null; say("LINK STOPPED · PARTIAL TRANSFER CLEARED."); renderScene(); } });
      root.querySelector("#hr-certify")?.addEventListener("click", submit);
      svg.querySelectorAll(".hr-station").forEach((node) => {
        node.addEventListener("pointerdown", (eventObject) => {
          if (interaction !== "full" || model.submitted) return;
          const point = pointerPoint(eventObject); model.dragging = {stationId: String(node.dataset.station), start: point, current: point, moved: false}; svg.setPointerCapture?.(eventObject.pointerId); eventObject.preventDefault();
        });
      });
      if (!svg.dataset.eventsBound) {
        svg.dataset.eventsBound = "true";
        svg.addEventListener("pointermove", (eventObject) => { if (!model.dragging) return; const point = pointerPoint(eventObject); model.dragging.current = point; if (Math.hypot(point.x - model.dragging.start.x, point.y - model.dragging.start.y) > 8) model.dragging.moved = true; renderScene(); });
        svg.addEventListener("pointerup", (eventObject) => {
          if (!model.dragging) return;
          const drag = model.dragging, point = pointerPoint(eventObject);
          model.dragging = null;
          const candidate = craft.find((item) => { const p = project(craftAt(item)); return Math.hypot(p.x - point.x, p.y - point.y) < 48; });
          const target = candidate && !model.completed.has(String(candidate.id)) ? candidate : null;
          if (!drag.moved) {
            if (model.active && model.active.stationId !== drag.stationId) { event("link_stop", {input_source: "station_click"}); clearPartial(); model.active = null; }
            model.selectedStation = drag.stationId;
            event("select_station", {station_id: drag.stationId, input_source: "station_click"});
            say(`${stationById(drag.stationId).label} SELECTED · DRAG ITS DISH TO A BRIGHT SPACECRAFT.`); renderScene(); return;
          }
          if (!target) { say(candidate ? "THAT SPACECRAFT IS ALREADY DELIVERED." : "DROP THE DISH ON A SPACECRAFT MARKER.", "error"); renderScene(); return; }
          const station = stationById(drag.stationId);
          if (!visible(station, target)) { say("THAT SPACECRAFT IS BEHIND THE PLANET FROM THIS STATION.", "error"); renderScene(); return; }
          if (model.active && (model.active.stationId !== drag.stationId || model.active.craftId !== String(target.id))) { event("link_stop", {input_source: "dish_drag"}); clearPartial(); model.active = null; }
          const aim = unit(sub(craftAt(target), stationAt(station)));
          model.selectedStation = drag.stationId;
          model.aim = {stationId: drag.stationId, craftId: String(target.id), vector: [aim.x, aim.y, aim.z]};
          model.active = {stationId: drag.stationId, craftId: String(target.id)};
          event("aim", {station_id: drag.stationId, craft_id: String(target.id), input_source: "dish_drag", aim_vector: model.aim.vector, started: true});
          say(`${station.label} → ${target.label} · RELAY ACTIVE · REFRESH THE AIM AS EARTH TURNS.`, "active"); renderScene();
        });
        svg.addEventListener("pointercancel", () => { if (model.dragging) { model.dragging = null; renderScene(); } });
      }
    }

    function pointerPoint(eventObject) { const rect = svg.getBoundingClientRect(); return {x: (eventObject.clientX - rect.left) * 800 / rect.width, y: (eventObject.clientY - rect.top) * 560 / rect.height}; }

    function step() {
      if (model.submitted) return;
      if (model.tick >= 20000) { submit(); return; }
      model.tick += 1; model.angle = state.rotation_angles_deg[model.tick];
      if (model.active) {
        const station = stationById(model.active.stationId); const target = craftById(model.active.craftId); const good = station && target && visible(station, target) && aimError(station, target, model.aim?.vector, model.tick) <= model.tolerance;
        if (good) {
          model.progress[target.id] += 1; event("sample", {station_id: model.active.stationId, craft_id: model.active.craftId, delivered_after: model.progress[target.id]});
          if (model.progress[target.id] >= num(target.required_ticks, 1)) { event("transfer_complete", {craft_id: model.active.craftId, delivered: model.progress[target.id]}); model.completed.add(String(target.id)); model.active = null; model.aim = null; say(`${target.label} DELIVERY COMPLETE · CHOOSE THE NEXT HORIZON.`, "passed"); }
        } else { event("link_break", {station_id: model.active.stationId, craft_id: model.active.craftId, reason: station && target && !visible(station, target) ? "horizon" : "aim"}); clearPartial(); model.active = null; say("LINK LOST · PARTIAL TRANSFER CLEARED. RECONNECT TO RETRY.", "error"); }
      }
      renderScene();
    }

    async function submit() {
      if (model.submitted) return;
      model.submitted = true; event("submit", {input_source: "certify_button"});
      const payload = {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, interaction_mode: interaction, events: model.events, completed: model.completed.size === craft.length};
      try {
        const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(payload)});
        const outcome = await response.json();
        if (outcome.passed === true) { helpers.setReadout("PASS", "passed"); say("PASS · ALL SPACECRAFT RELAYS DELIVERED.", "passed"); root.querySelector(".hr-shell").classList.add("is-pass"); return; }
        if (outcome.state) { model.failed = true; render(outcome.state, helpers); helpers.setReadout("FAIL · NEW RELAY", "error"); return; }
        model.submitted = false; say("FAIL · RELAY LEDGER REJECTED.", "error");
      } catch (_error) { model.submitted = false; say("SUBMISSION UNAVAILABLE · RETRY.", "error"); }
    }

    renderScene();
    model.timer = setInterval(step, num(state.rotation?.tick_ms, 100));
    window.horizonRelayV2Model = model;
    say(interaction === "full" ? "DRAG A BRIGHT STATION DISH TO A SPACECRAFT." : "SELECT A BRIGHT STATION AND READ ITS HORIZON.");
  }

  window.GymAnythingRTMechanics.horizon_relay_v2 = {rootSelector: ".hr-shell", render};
})();
