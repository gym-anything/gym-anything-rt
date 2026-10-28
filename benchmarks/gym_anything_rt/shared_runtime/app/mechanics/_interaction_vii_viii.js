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

  function lineIntersection(origin, direction, first, second) {
    const sx = second.x - first.x, sy = second.y - first.y;
    const denominator = direction.x * sy - direction.y * sx;
    if (Math.abs(denominator) < 1e-8) return null;
    const qx = first.x - origin.x, qy = first.y - origin.y;
    const t = (qx * sy - qy * sx) / denominator;
    const u = (qx * direction.y - qy * direction.x) / denominator;
    return t > .001 && u >= 0 && u <= 1 ? {x: origin.x + direction.x * t, y: origin.y + direction.y * t, t} : null;
  }
  function mirrorSegment(mirror, angle) {
    const radians = angle * Math.PI / 180, half = Number(mirror.length) / 2;
    const dx = Math.cos(radians) * half, dy = Math.sin(radians) * half;
    return [{x: mirror.center[0] - dx, y: mirror.center[1] - dy}, {x: mirror.center[0] + dx, y: mirror.center[1] + dy}];
  }
  function receiverAt(roundData, tick = 0) {
    const receiver = roundData.receiver, center = {x: Number(receiver.center[0]), y: Number(receiver.center[1])};
    const displacement = Number(receiver.amplitude || 0) * Math.sin(Number(tick) * Number(receiver.angular_rate || 0) + Number(receiver.phase || 0));
    if (receiver.motion_axis === "x") center.x += displacement; else center.y += displacement;
    return center;
  }
  function traceBeam(roundData, angles, tick = 0) {
    let origin = {x: roundData.emitter[0], y: roundData.emitter[1]};
    const first = roundData.mirrors[0].center;
    let direction = (() => { const dx = first[0] - origin.x, dy = first[1] - origin.y, length = Math.hypot(dx, dy); return {x: dx / length, y: dy / length}; })();
    const points = [{...origin}];
    for (let index = 0; index < roundData.mirrors.length; index++) {
      const mirror = roundData.mirrors[index], segment = mirrorSegment(mirror, angles[index]);
      const hit = lineIntersection(origin, direction, segment[0], segment[1]);
      if (!hit) return {points: [...points, {x: origin.x + direction.x * 1100, y: origin.y + direction.y * 1100}], hit: false};
      points.push({x: hit.x, y: hit.y});
      const tangent = angles[index] * Math.PI / 180;
      const dot = direction.x * Math.cos(tangent) + direction.y * Math.sin(tangent);
      direction = {x: 2 * dot * Math.cos(tangent) - direction.x, y: 2 * dot * Math.sin(tangent) - direction.y};
      origin = {x: hit.x + direction.x * .01, y: hit.y + direction.y * .01};
    }
    const receiver = receiverAt(roundData, tick);
    const projection = (receiver.x - origin.x) * direction.x + (receiver.y - origin.y) * direction.y;
    const closest = {x: origin.x + direction.x * projection, y: origin.y + direction.y * projection};
    const hit = projection > 0 && Math.hypot(receiver.x - closest.x, receiver.y - closest.y) <= Number(roundData.tolerance_px);
    points.push(hit ? closest : {x: origin.x + direction.x * 1100, y: origin.y + direction.y * 1100});
    return {points, hit};
  }

  registry.specular_lighthouse_relay = async (state, helpers) => {
    document.body.dataset.mechanic = "specular-lighthouse-relay";
    const interaction = state.control_condition?.interaction || "simplified";
    const model = {state, helpers, interaction, events: [], roundIndex: 0, angles: state.rounds[0].mirrors.map((item) => Number(item.angle_deg)), charge: 0, tick: 0, shutterOpen: false, chargedPending: false, terminal: false, submitting: false, timer: null, mirrorDrag: null};
    window.specularLighthouseRelayModel = model;
    helpers.app.innerHTML = shell(state, "COASTAL OPTICS AUTHORITY", "SPECULAR LIGHTHOUSE RELAY", `Build the ${state.rounds[0].mirrors.length}-mirror path, open the shutter, then keep steering the live receiver while charge leaks on every miss.`, `<canvas id="specular-canvas" width="900" height="480"></canvas>`, `
      <h2>GIMBAL BANK</h2><div id="specular-controls"></div>
      <button id="specular-charge" class="ivv-primary">OPEN TRACKING SHUTTER</button>
      <div class="ivv-meter"><i id="specular-meter"></i></div>
      <button id="specular-abandon" class="ivv-danger">ABANDON / FRESH RELAY</button>`);
    const current = () => state.rounds[model.roundIndex];
    const adjustMirror = (index, delta, inputSource) => {
      if (model.terminal) return;
      const before = model.angles[index];
      model.angles[index] = (before + Number(delta) + 180) % 180;
      event(model, "mirror_adjust", {round_id: current().id, tick: model.tick, mirror_id: current().mirrors[index].id, before: round(before, 2), after: round(model.angles[index], 2), input_source: inputSource});
    };
    const updateAngleDisplays = () => document.querySelectorAll("[data-specular-angle]").forEach((node) => {
      node.textContent = `${model.angles[Number(node.dataset.specularAngle)].toFixed(0)}°`;
    });
    const renderControls = () => {
      const step = Number(current().angle_step_deg || 1); document.getElementById("specular-controls").innerHTML = interaction === "simplified" ? current().mirrors.map((mirror, index) => `<div class="ivv-control-row"><b>${esc(mirror.id.toUpperCase())}</b><button data-mirror="${index}" data-delta="${-step}">−${step}°</button><span data-specular-angle="${index}">${model.angles[index].toFixed(0)}°</span><button data-mirror="${index}" data-delta="${step}">+${step}°</button></div>`).join("") : `<p class="specular-drag-note">DRAG EACH MIRROR LEFT OR RIGHT ON THE OPTICAL BENCH.</p>${current().mirrors.map((mirror, index) => `<div class="specular-angle-row"><b>${esc(mirror.id.toUpperCase())}</b><span data-specular-angle="${index}">${model.angles[index].toFixed(0)}°</span></div>`).join("")}`;
      document.querySelectorAll("[data-mirror]").forEach((button) => button.addEventListener("click", () => {
        const index = Number(button.dataset.mirror);
        adjustMirror(index, Number(button.dataset.delta), "gimbal_buttons");
        updateAngleDisplays(); draw();
      }));
    };
    const draw = () => {
      const canvas = document.getElementById("specular-canvas"), ctx = canvas.getContext("2d"), data = current(), receiver = receiverAt(data, model.tick), beam = traceBeam(data, model.angles, model.tick);
      ctx.clearRect(0, 0, 900, 480); ctx.fillStyle = "#06161a"; ctx.fillRect(0, 0, 900, 480);
      ctx.strokeStyle = "#12343a"; ctx.lineWidth = 1; for (let x = 0; x < 900; x += 30) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 480); ctx.stroke(); }
      ctx.shadowBlur = 18; ctx.shadowColor = beam.hit ? "#d8ff5b" : "#58dfe8"; ctx.strokeStyle = beam.hit ? "#ecff87" : "#79e7ef"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(beam.points[0].x, beam.points[0].y); beam.points.slice(1).forEach((point) => ctx.lineTo(point.x, point.y)); ctx.stroke(); ctx.shadowBlur = 0;
      data.mirrors.forEach((mirror, index) => { const segment = mirrorSegment(mirror, model.angles[index]); ctx.strokeStyle = "#f2d5a0"; ctx.lineWidth = 9; ctx.beginPath(); ctx.moveTo(segment[0].x, segment[0].y); ctx.lineTo(segment[1].x, segment[1].y); ctx.stroke(); ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke(); });
      ctx.fillStyle = "#ffcd55"; ctx.beginPath(); ctx.arc(data.emitter[0], data.emitter[1], 18, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = beam.hit ? "#dfff5b" : "#ff6f61"; ctx.lineWidth = 6; ctx.beginPath(); ctx.arc(receiver.x, receiver.y, Number(data.receiver.radius), 0, Math.PI * 2); ctx.stroke();
      ctx.strokeStyle = "rgba(216,255,91,.28)"; ctx.setLineDash([4,7]); ctx.beginPath(); ctx.moveTo(receiver.x, Number(data.receiver.center[1]) - Number(data.receiver.amplitude)); ctx.lineTo(receiver.x, Number(data.receiver.center[1]) + Number(data.receiver.amplitude)); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = "#b8c7c6"; ctx.font = "700 12px Courier New"; ctx.fillText(`SHUTTER ${model.roundIndex + 1} / ${state.round_count} · TRACK ${model.tick}`, 18, 26);
      model.beamHit = beam.hit;
    };
    async function advanceChargedReceiver() {
      event(model, "receiver_charged", {round_id: current().id, tick: model.tick, angles: model.angles.map((value) => round(value, 2)), charge_ticks: model.charge});
      model.charge = 0; model.chargedPending = false;
      if (model.roundIndex + 1 < state.round_count) { model.roundIndex += 1; model.tick = 0; model.angles = current().mirrors.map((item) => Number(item.angle_deg)); document.getElementById("specular-meter").style.width = "0%"; renderControls(); setMessage(model, `SHUTTER ${model.roundIndex} CHARGED · NEXT MOVING RECEIVER`, "passed"); draw(); }
      else await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "LIGHTHOUSE RELAY AUTHENTICATED", "LIVE RECEIVER TRACKING · LEAKING CHARGE · ANALYTIC REFLECTION REPLAY");
    }
    const closeShutter = (reason = "operator") => { if (!model.shutterOpen) return; model.shutterOpen = false; clearInterval(model.timer); model.timer = null; const button = document.getElementById("specular-charge"); button?.classList.remove("is-live"); if (button) button.textContent = "OPEN TRACKING SHUTTER"; event(model, "shutter", {round_id: current().id, tick: model.tick, open: false, reason}); if (model.chargedPending) void advanceChargedReceiver(); };
    const openShutter = () => {
      if (model.shutterOpen || model.terminal) return; model.shutterOpen = true; const button = document.getElementById("specular-charge"); button.classList.add("is-live"); button.textContent = "CLOSE TRACKING SHUTTER";
      event(model, "shutter", {round_id: current().id, tick: model.tick, open: true});
      model.timer = setInterval(async () => {
        model.tick += 1; draw(); model.charge = model.beamHit ? model.charge + 1 : Math.max(0, model.charge - Number(current().miss_decay_ticks));
        event(model, "charge_sample", {round_id: current().id, tick: model.tick, hit: Boolean(model.beamHit), angles: model.angles.map((value) => round(value, 2)), charge_after: model.charge});
        document.getElementById("specular-meter").style.width = `${Math.min(100, model.charge / current().required_charge_ticks * 100)}%`;
        if (model.charge < current().required_charge_ticks) return;
        model.chargedPending = true; clearInterval(model.timer); model.timer = null;
        setMessage(model, "RECEIVER CHARGED · CLOSE SHUTTER TO SEAL", "passed");
      }, 80);
    };
    document.getElementById("specular-charge").addEventListener("click", () => model.shutterOpen ? closeShutter() : openShutter());
    document.getElementById("specular-abandon").addEventListener("click", () => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", ""));
    const opticalCanvas = document.getElementById("specular-canvas");
    opticalCanvas.addEventListener("pointerdown", (pointerEvent) => {
      if (interaction !== "full" || model.terminal) return;
      const box = opticalCanvas.getBoundingClientRect();
      const x = (pointerEvent.clientX - box.left) / box.width * opticalCanvas.width;
      const y = (pointerEvent.clientY - box.top) / box.height * opticalCanvas.height;
      const distances = current().mirrors.map((mirror) => Math.hypot(x - Number(mirror.center[0]), y - Number(mirror.center[1])));
      const index = distances.indexOf(Math.min(...distances));
      if (distances[index] > 72) return;
      pointerEvent.preventDefault(); opticalCanvas.setPointerCapture(pointerEvent.pointerId);
      model.mirrorDrag = {index, lastX: pointerEvent.clientX, accumulator: 0};
    });
    opticalCanvas.addEventListener("pointermove", (pointerEvent) => {
      if (!model.mirrorDrag) return;
      model.mirrorDrag.accumulator += pointerEvent.clientX - model.mirrorDrag.lastX;
      model.mirrorDrag.lastX = pointerEvent.clientX;
      const step = Number(current().angle_step_deg || 1);
      while (Math.abs(model.mirrorDrag.accumulator) >= 8) {
        const direction = Math.sign(model.mirrorDrag.accumulator);
        adjustMirror(model.mirrorDrag.index, direction * step, "mirror_drag");
        model.mirrorDrag.accumulator -= direction * 8;
      }
      updateAngleDisplays(); draw();
    });
    const endMirrorDrag = () => { model.mirrorDrag = null; };
    opticalCanvas.addEventListener("pointerup", endMirrorDrag);
    opticalCanvas.addEventListener("pointercancel", endMirrorDrag);
    renderControls(); draw(); model.animation = setInterval(draw, 90);
  };

  const windGateY = (slot, tick) => Number(slot.base_y) + Number(slot.amplitude) * Math.sin(tick * Number(slot.angular_rate) + Number(slot.phase));
  function windStep(model) {
    const p = model.state.physics, fans = model.state.fans;
    const accelerations = model.pods.map((pod) => .006 * Math.sin(model.tick * .083 + Number(p.phase) + Number(pod.gust_phase))), trip = {index: -1};
    fans.forEach((fan, index) => {
      model.heat[index] = Math.max(0, model.heat[index] + (model.powers[index] ? Number(p.heat_rate) : -Number(p.cool_rate)));
      if (model.heat[index] >= Number(p.trip_heat)) trip.index = index;
      model.actual[index] += (model.powers[index] - model.actual[index]) * Number(p.spool_rate);
      model.pods.forEach((pod, podIndex) => { if (pod.docked) return; const influence = Math.max(0, 1 - Math.abs(pod.x - fan.x) / fan.radius); accelerations[podIndex] += model.actual[index] * Number(p.fan_accel) * Number(pod.response) * influence; });
    });
    model.pods.forEach((pod, index) => { if (pod.docked) return; pod.vy = (pod.vy + accelerations[index]) * Number(p.drag); pod.y = clamp(pod.y + pod.vy, 35, 441); pod.x += pod.vx; }); model.tick += 1;
    return trip.index;
  }
  registry.wind_tunnel_seed_courier = async (state, helpers) => {
    document.body.dataset.mechanic = "wind-tunnel-seed-courier";
    const interaction = state.control_condition?.interaction || "simplified";
    const model = {state, helpers, interaction, events: [], pods: copy(state.pods).map((pod) => ({...pod, docked:false})), powers: state.fans.map(() => 0), actual: state.fans.map(() => 0), heat: state.fans.map(() => 0), tick: 0, passed: Object.fromEntries(state.pods.map((pod) => [pod.id, []])), running: false, failing: false, terminal: false, submitting: false, interval: null, fanDrag: null};
    window.windTunnelSeedCourierModel = model;
    const launchLabel = state.pods.length === 1 ? "LAUNCH POD" : "LAUNCH BOTH PODS";
    const proxyNote = state.pods.length === 1 ? "This pod responds to the shared spool and heat. Watch its colored slot while correcting only near a fan." : "Both pods inherit spool and heat. Watch both colored slots: a correction for one changes the field waiting for the other.";
    const directControls = `<h2>SHARED FAN WALL</h2><p class="wind-direct-note">GRIP A VISIBLE FAN LEVER IN THE TUNNEL. DRAG UP FOR LIFT, CENTER FOR COAST, OR DOWN FOR PRESS. THE ${state.fans.length} LEVER${state.fans.length === 1 ? "" : "S"} SHARE SPOOL AND HEAT.</p>`;
    const proxyControls = `<h2>SHARED FAN WALL</h2><p>${proxyNote}</p><div class="wind-bank">${state.fans.map((fan, index) => `<div><b>${esc(fan.id.toUpperCase())}</b><button data-fan="${index}" data-power="-1">↑ LIFT</button><button data-fan="${index}" data-power="0">COAST</button><button data-fan="${index}" data-power="1">↓ PRESS</button><span id="wind-power-${index}">COAST · HEAT 0%</span></div>`).join("")}</div>`;
    helpers.app.innerHTML = shell(state, "BOTANICAL AIRMAIL / TEST CHAMBER 7", "WIND-TUNNEL SEED COURIER", state.prompt || "Steer the seed pods through their colored moving apertures using one shared, heat-limited fan plant.", `<canvas id="wind-canvas" width="900" height="480"></canvas>`, `
      ${interaction === "simplified" ? proxyControls : directControls}
      <button id="wind-launch" class="ivv-primary">${launchLabel}</button><button id="wind-abandon" class="ivv-danger">VENT / FRESH TUNNEL</button>`);
    const draw = () => {
      const ctx = document.getElementById("wind-canvas").getContext("2d"); ctx.clearRect(0, 0, 900, 480); const gradient = ctx.createLinearGradient(0, 0, 900, 0); gradient.addColorStop(0, "#dce7d0"); gradient.addColorStop(1, "#7fb7a4"); ctx.fillStyle = gradient; ctx.fillRect(0, 0, 900, 480);
      ctx.strokeStyle = "rgba(255,255,255,.22)"; for (let y = 30; y < 470; y += 35) { ctx.beginPath(); ctx.moveTo(0, y); ctx.bezierCurveTo(280, y - 12, 620, y + 12, 900, y); ctx.stroke(); }
      state.fans.forEach((fan, index) => { const direction = model.actual[index] || model.powers[index]; ctx.save(); ctx.translate(fan.x, direction < 0 ? 460 : 20); ctx.fillStyle = model.powers[index] ? `hsl(${12 + model.heat[index] * 32} 88% 58%)` : "#526b64"; ctx.beginPath(); ctx.arc(0, 0, 18, 0, Math.PI * 2); ctx.fill(); ctx.strokeStyle = "rgba(239,107,71,.25)"; ctx.setLineDash([6, 8]); ctx.beginPath(); ctx.arc(0, direction < 0 ? -70 : 70, fan.radius, 0, Math.PI * 2); ctx.stroke(); ctx.restore(); const readout = document.getElementById(`wind-power-${index}`); if (readout) readout.textContent = `${model.powers[index] < 0 ? "LIFT" : model.powers[index] > 0 ? "PRESS" : "COAST"} · HEAT ${Math.round(model.heat[index] * 100)}%`; if (interaction === "full") { const railTop = 401, railHeight = 68, handleY = 435 + model.powers[index] * 22; ctx.fillStyle = "#162b29dd"; ctx.fillRect(fan.x - 17, railTop, 34, railHeight); ctx.strokeStyle = "#d7e5c2"; ctx.lineWidth = 1; ctx.strokeRect(fan.x - 17, railTop, 34, railHeight); ctx.strokeStyle = "#8eb7a4"; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(fan.x - 12, 435); ctx.lineTo(fan.x + 12, 435); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = model.powers[index] ? "#ef6b47" : "#dce7d0"; ctx.fillRect(fan.x - 13, handleY - 7, 26, 14); ctx.fillStyle = "#e8f5de"; ctx.font = "700 8px Courier New"; ctx.fillText(String(index + 1), fan.x - 3, railTop + 11); } });
      state.gates.forEach((gate, index) => { ctx.fillStyle = "#263d3b"; ctx.fillRect(gate.x - 7, 0, 14, 480); gate.slots.forEach((slot) => { const podSpec = state.pods.find((pod) => pod.id === slot.pod_id), center = windGateY(slot, model.tick); ctx.clearRect(gate.x - 8, center - slot.half_gap, 16, slot.half_gap * 2); ctx.strokeStyle = podSpec.color; ctx.lineWidth = 3; ctx.strokeRect(gate.x - 10, center - slot.half_gap, 20, slot.half_gap * 2); }); ctx.fillStyle = "#f7f0d6"; ctx.font = "700 10px Courier New"; ctx.fillText(String(index + 1).padStart(2, "0"), gate.x - 7, 14); });
      state.docks.forEach((dock) => { const pod = state.pods.find((item) => item.id === dock.pod_id); ctx.strokeStyle = pod.color; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(dock.x, dock.y, dock.radius, 0, Math.PI * 2); ctx.stroke(); });
      model.pods.forEach((pod) => { ctx.save(); ctx.translate(pod.x, pod.y); ctx.rotate(Math.atan2(pod.vy, pod.vx)); ctx.fillStyle = pod.color; ctx.beginPath(); ctx.ellipse(0, 0, pod.id === "acorn" ? 15 : 18, pod.id === "acorn" ? 11 : 8, 0, 0, Math.PI * 2); ctx.fill(); ctx.strokeStyle = "#4f3f22"; ctx.stroke(); ctx.restore(); });
      const progress = model.pods.map((pod) => `${pod.id.toUpperCase()} ${model.passed[pod.id].length}/${state.gates.length}`).join(" · "); ctx.fillStyle = "#223b36"; ctx.font = "800 11px Courier New"; ctx.fillText(`TICK ${String(model.tick).padStart(3, "0")} · ${progress}`, 18, 24);
    };
    const fail = async (reason) => { if (model.failing) return; model.failing = true; clearInterval(model.interval); model.running = false; event(model, "terminal", {tick: model.tick, passed: false, reason, pods: copy(model.pods), gates: copy(model.passed)}); document.querySelector(".ivv")?.insertAdjacentHTML("beforeend", verdict("fail", "COURIER LOST", reason)); setTimeout(() => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: false}, "", ""), 900); };
    const setFan = (index, power, inputSource) => { if (model.terminal || model.failing) return; model.powers[index] = power; event(model, "fan_control", {tick: model.tick, fan: index, power, input_source: inputSource}); draw(); };
    const launch = () => {
      if (model.running || model.terminal) return; model.running = true; document.getElementById("wind-launch").disabled = true; event(model, "launch", {tick: 0, powers: [...model.powers]});
      model.interval = setInterval(async () => {
        const beforeX = Object.fromEntries(model.pods.map((pod) => [pod.id, pod.x])), tripped = windStep(model);
        if (tripped >= 0) { await fail(`FAN ${tripped + 1} THERMAL TRIP · ARM ONLY INSIDE ITS LOCAL WINDOW`); return; }
        for (const pod of model.pods) { if (pod.docked) continue; const nextGate = state.gates[model.passed[pod.id].length]; if (nextGate && beforeX[pod.id] < nextGate.x && pod.x >= nextGate.x) { const slot = nextGate.slots.find((item) => item.pod_id === pod.id), center = windGateY(slot, model.tick); if (Math.abs(pod.y - center) + state.physics.pod_radius > slot.half_gap) { await fail(`${pod.id.toUpperCase()} COLLIDED AT MOVING AIR GATE ${model.passed[pod.id].length + 1}`); return; } model.passed[pod.id].push(nextGate.id); event(model, "gate_pass", {tick: model.tick, pod_id: pod.id, gate_id: nextGate.id, gate_y: round(center), y: round(pod.y), vy: round(pod.vy)}); } const dock = state.docks.find((item) => item.pod_id === pod.id); if (beforeX[pod.id] < dock.x && pod.x >= dock.x) { if (model.passed[pod.id].length !== state.gates.length || Math.hypot(pod.x - dock.x, pod.y - dock.y) > dock.radius + 4) { await fail(`${pod.id.toUpperCase()} MISSED ITS RECEIVING FUNNEL`); return; } pod.docked = true; pod.x = dock.x; event(model, "dock", {tick: model.tick, pod_id: pod.id, pod: copy(pod), gates: [...model.passed[pod.id]]}); } }
        draw(); if (!model.pods.every((pod) => pod.docked) && model.tick < state.physics.ticks) return; if (!model.pods.every((pod) => pod.docked)) { await fail("THE DELAYED POD DID NOT REACH ITS FUNNEL"); return; } clearInterval(model.interval); model.running = false; event(model, "terminal", {tick: model.tick, passed: true, pods: copy(model.pods), gates: copy(model.passed)}); await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, state.pods.length === 1 ? "AIRMAIL DELIVERED" : "DUAL AIRMAIL DELIVERED", `${state.pods.length} POD${state.pods.length === 1 ? "" : "S"} · SHARED SPOOL / HEAT · ${state.pods.length * state.gates.length} MOVING APERTURES`);
      }, state.physics.tick_ms);
    };
    document.querySelectorAll("[data-fan]").forEach((button) => button.addEventListener("click", () => setFan(Number(button.dataset.fan), Number(button.dataset.power), "fan_button")));
    if (interaction === "full") {
      const canvas = document.getElementById("wind-canvas");
      const point = (pointerEvent) => { const box = canvas.getBoundingClientRect(); return {x: (pointerEvent.clientX - box.left) * 900 / box.width, y: (pointerEvent.clientY - box.top) * 480 / box.height}; };
      const fanAt = ({x, y}) => y >= 396 && y <= 480 ? state.fans.findIndex((fan) => Math.abs(x - fan.x) <= 25) : -1;
      const powerAt = (y) => y < 423 ? -1 : y > 447 ? 1 : 0;
      canvas.addEventListener("pointerdown", (pointerEvent) => { if (model.terminal || model.failing) return; const location = point(pointerEvent), index = fanAt(location); if (index < 0) return; model.fanDrag = {index, y: location.y, pointerId: pointerEvent.pointerId}; canvas.setPointerCapture(pointerEvent.pointerId); pointerEvent.preventDefault(); });
      canvas.addEventListener("pointermove", (pointerEvent) => { if (!model.fanDrag || model.fanDrag.pointerId !== pointerEvent.pointerId) return; model.fanDrag.y = point(pointerEvent).y; pointerEvent.preventDefault(); });
      const finishFanDrag = (pointerEvent) => { if (!model.fanDrag || model.fanDrag.pointerId !== pointerEvent.pointerId) return; model.fanDrag.y = point(pointerEvent).y; const {index, y} = model.fanDrag; model.fanDrag = null; if (canvas.hasPointerCapture(pointerEvent.pointerId)) canvas.releasePointerCapture(pointerEvent.pointerId); setFan(index, powerAt(y), "fan_lever_drag"); pointerEvent.preventDefault(); };
      canvas.addEventListener("pointerup", finishFanDrag);
      canvas.addEventListener("pointercancel", finishFanDrag);
    }
    document.getElementById("wind-launch").addEventListener("click", launch); document.getElementById("wind-abandon").addEventListener("click", () => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon", tick: model.tick}], completed: false}, "", "")); draw();
  };

  function rodCells(item) { const center = item.center.map(Number), axis = "xyz".indexOf(item.axis), cells = []; [-1, 0, 1].forEach((offset) => { const point = [...center]; point[axis] += offset; cells.push(point); }); return cells; }
  function masks(objects) { const views = {front:{pair:([x,_y,z])=>[x,z],depth:([_x,y])=>y},side:{pair:([_x,y,z])=>[y,z],depth:([x])=>x},top:{pair:([x,y])=>[x,y],depth:([_x,_y,z])=>z}}, result={}; Object.entries(views).forEach(([view,spec])=>{const nearest=new Map();objects.forEach((item)=>rodCells(item).forEach((cell)=>{const pair=spec.pair(cell),key=pair.join(":"),depth=spec.depth(cell),before=nearest.get(key);if(!before||depth<before.depth)nearest.set(key,{depth,color:item.color});}));result[view]=[...nearest.entries()].map(([key,value])=>`${key}:${value.color}`).sort();});return result; }
  function maskEqual(first, second) { return ["front", "side", "top"].every((view) => JSON.stringify([...first[view]].sort()) === JSON.stringify([...second[view]].sort())); }
  function validRods(objects, gridSize) { const cells=objects.flatMap(rodCells); return cells.every((cell)=>cell.every((value)=>value>=0&&value<gridSize))&&new Set(cells.map((cell)=>cell.join(":"))).size===cells.length; }
  registry.hologram_silhouette_foundry = async (state, helpers) => {
    document.body.dataset.mechanic = "hologram-silhouette-foundry";
    const interaction = state.control_condition?.interaction || "simplified";
    const model = {state, helpers, interaction, events: [], objects: copy(state.objects), selected: state.objects[0].id, terminal: false, submitting: false, gizmoGesture: null}; window.hologramSilhouetteFoundryModel = model;
    const proxyControls = `<div class="holo-moves">${["x-","x+","y-","y+","z-","z+"].map((move) => `<button data-move="${move}">${move.toUpperCase()}</button>`).join("")}</div><button id="holo-rotate">CYCLE AXIS X/Y/Z</button>`;
    const directControls = `<p class="holo-gizmo-note">DRAG ONE AXIS HANDLE OUTWARD THROUGH A DETENT TO TRANSLATE. DRAG THE RING TO CYCLE THE ROD AXIS.</p><canvas id="holo-gizmo" width="264" height="176" aria-label="Direct rod transformation gizmo"></canvas>`;
    helpers.app.innerHTML = shell(state, "MINISTRY OF IMPOSSIBLE CASTINGS", "HOLOGRAM SILHOUETTE FOUNDRY", `Place ${state.objects.length} colored rods in a ${state.grid_size}³ volume. Match the frontmost color in every ray of all three occluding dies.`, `<div class="holo-views">${state.views.map((view) => `<article><header>${esc(view.toUpperCase())} / NEAREST-COLOR DIE</header><canvas id="holo-${view}" width="260" height="360"></canvas></article>`).join("")}</div>`, `
      <h2>ROD MANIPULATOR</h2><div id="holo-rods" class="holo-rods"></div>${interaction === "simplified" ? proxyControls : directControls}<button id="holo-cast" class="ivv-primary">CAST THREE SHADOWS</button><button id="holo-abandon" class="ivv-danger">SCRAP / FRESH FOUNDRY</button>`);
    const drawView = (view) => {
      const canvas = document.getElementById(`holo-${view}`), ctx = canvas.getContext("2d"), size = 36, offsetX = 4, offsetY = 54; ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.fillStyle = "#07090d"; ctx.fillRect(0, 0, canvas.width, canvas.height);
      const parse=(items)=>new Map(items.map((item)=>{const [a,b,...color]=item.split(":");return[`${a}:${b}`,color.join(":")];})),target=parse(state.target_masks[view]),actual=parse(masks(model.objects)[view]); for (let a = 0; a < state.grid_size; a++) for (let b = 0; b < state.grid_size; b++) { const key = `${a}:${b}`,x=offsetX+a*size,y=offsetY+(state.grid_size-1-b)*size; ctx.strokeStyle = target.get(key) || "#283044"; ctx.lineWidth = target.has(key) ? 4 : 1; ctx.strokeRect(x + 2, y + 2, size - 4, size - 4); if(actual.has(key)){ctx.fillStyle=actual.get(key)+"bb";ctx.fillRect(x+8,y+8,size-16,size-16);} }
    };
    const gizmoHandles = [{axis:"x",delta:1,x:205,y:88,label:"X+",color:"#ff6d4a"},{axis:"x",delta:-1,x:59,y:88,label:"X−",color:"#ff6d4a"},{axis:"y",delta:1,x:132,y:28,label:"Y+",color:"#5bd8c8"},{axis:"y",delta:-1,x:132,y:148,label:"Y−",color:"#5bd8c8"},{axis:"z",delta:1,x:188,y:42,label:"Z+",color:"#a983ff"},{axis:"z",delta:-1,x:76,y:134,label:"Z−",color:"#a983ff"}];
    const drawGizmo = () => { if (interaction !== "full") return; const canvas=document.getElementById("holo-gizmo"),ctx=canvas.getContext("2d"),center={x:132,y:88},item=model.objects.find((candidate)=>candidate.id===model.selected); ctx.clearRect(0,0,canvas.width,canvas.height); ctx.fillStyle="#070a11";ctx.fillRect(0,0,canvas.width,canvas.height);ctx.strokeStyle="#817998";ctx.lineWidth=2;ctx.beginPath();ctx.arc(center.x,center.y,54,0,Math.PI*2);ctx.stroke();ctx.fillStyle="#b8b1ce";ctx.font="700 8px Courier New";ctx.fillText("DRAG RING · CYCLE AXIS",75,171);gizmoHandles.forEach((handle)=>{ctx.strokeStyle=handle.color;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(center.x,center.y);ctx.lineTo(handle.x,handle.y);ctx.stroke();ctx.fillStyle=handle.color;ctx.beginPath();ctx.arc(handle.x,handle.y,11,0,Math.PI*2);ctx.fill();ctx.fillStyle="#081017";ctx.font="900 8px Courier New";ctx.textAlign="center";ctx.fillText(handle.label,handle.x,handle.y+3);});ctx.fillStyle=item.color;ctx.beginPath();ctx.arc(center.x,center.y,20,0,Math.PI*2);ctx.fill();ctx.strokeStyle="#f3efff";ctx.lineWidth=4;ctx.beginPath();if(item.axis==="x"){ctx.moveTo(center.x-14,center.y);ctx.lineTo(center.x+14,center.y);}else if(item.axis==="y"){ctx.moveTo(center.x,center.y-14);ctx.lineTo(center.x,center.y+14);}else{ctx.moveTo(center.x-10,center.y+10);ctx.lineTo(center.x+10,center.y-10);}ctx.stroke();ctx.textAlign="left";ctx.fillStyle="#f3efff";ctx.font="700 9px Courier New";ctx.fillText(`${item.id.toUpperCase()} · ${item.axis.toUpperCase()} · ${item.center.join(",")}`,8,14); };
    const update = () => { state.views.forEach(drawView); document.getElementById("holo-rods").innerHTML = model.objects.map((item) => `<button data-rod="${item.id}" class="${item.id === model.selected ? "is-selected" : ""}" style="--rod:${item.color}">${esc(item.id.toUpperCase())}<span>${item.axis.toUpperCase()} · ${item.center.join(",")}</span></button>`).join(""); document.querySelectorAll("[data-rod]").forEach((button) => button.addEventListener("click", () => { model.selected = button.dataset.rod; update(); })); drawGizmo(); const exact = validRods(model.objects,state.grid_size)&&maskEqual(masks(model.objects), state.target_masks); document.getElementById("holo-cast").dataset.ready = String(exact); setMessage(model, exact ? "ALL THREE DEPTH DIES COINCIDE · CAST READY" : validRods(model.objects,state.grid_size)?"MATCH OCCUPANCY, COLOR, AND NEAREST DEPTH IN ALL THREE DIES":"RODS OVERLAP · SOLID CASTING IMPOSSIBLE", exact ? "passed" : "idle"); };
    const act = (kind, details, mutation) => { const item = model.objects.find((candidate) => candidate.id === model.selected), before = copy(item); mutation(item); event(model, kind, {object_id: item.id, before, after: copy(item), ...details}); update(); };
    document.querySelectorAll("[data-move]").forEach((button) => button.addEventListener("click", () => { const axis = "xyz".indexOf(button.dataset.move[0]), delta = button.dataset.move[1] === "+" ? 1 : -1; act("translate", {axis: button.dataset.move[0], delta, input_source:"transform_button"}, (item) => { item.center[axis] = clamp(item.center[axis] + delta, 1, state.grid_size-2); }); }));
    document.getElementById("holo-rotate")?.addEventListener("click", () => act("rotate", {input_source:"transform_button"}, (item) => { item.axis = "xyz"[("xyz".indexOf(item.axis) + 1) % 3]; }));
    const gizmo = document.getElementById("holo-gizmo");
    const gizmoPoint = (pointerEvent) => { const box=gizmo.getBoundingClientRect(); return {x:(pointerEvent.clientX-box.left)/box.width*gizmo.width,y:(pointerEvent.clientY-box.top)/box.height*gizmo.height}; };
    gizmo?.addEventListener("pointerdown", (pointerEvent) => { if (model.terminal || model.submitting) return; const point=gizmoPoint(pointerEvent),center={x:132,y:88},handle=gizmoHandles.find((candidate)=>Math.hypot(point.x-candidate.x,point.y-candidate.y)<=17),radius=Math.hypot(point.x-center.x,point.y-center.y); if (!handle && Math.abs(radius-54)>12) return; gizmo.setPointerCapture(pointerEvent.pointerId); model.gizmoGesture={pointerId:pointerEvent.pointerId,kind:handle?"translate":"rotate",handle,start:point,applied:false};pointerEvent.preventDefault(); });
    gizmo?.addEventListener("pointermove", (pointerEvent) => { const gesture=model.gizmoGesture;if(!gesture||gesture.pointerId!==pointerEvent.pointerId||gesture.applied)return;const point=gizmoPoint(pointerEvent);if(gesture.kind==="translate"){const dx=gesture.handle.x-132,dy=gesture.handle.y-88,progress=(point.x-gesture.start.x)*dx+(point.y-gesture.start.y)*dy;if(progress<1100)return;gesture.applied=true;const index="xyz".indexOf(gesture.handle.axis);act("translate",{axis:gesture.handle.axis,delta:gesture.handle.delta,input_source:"gizmo_drag"},(item)=>{item.center[index]=clamp(item.center[index]+gesture.handle.delta,1,state.grid_size-2);});}else{const center={x:132,y:88},start=Math.atan2(gesture.start.y-center.y,gesture.start.x-center.x),now=Math.atan2(point.y-center.y,point.x-center.x);if(Math.abs(angleError(now*180/Math.PI,start*180/Math.PI))<30)return;gesture.applied=true;act("rotate",{input_source:"gizmo_drag"},(item)=>{item.axis="xyz"[("xyz".indexOf(item.axis)+1)%3];});} });
    const finishGizmo = (pointerEvent) => { if (!model.gizmoGesture || model.gizmoGesture.pointerId !== pointerEvent.pointerId) return; if (gizmo.hasPointerCapture(pointerEvent.pointerId)) gizmo.releasePointerCapture(pointerEvent.pointerId); model.gizmoGesture=null; }; gizmo?.addEventListener("pointerup",finishGizmo);gizmo?.addEventListener("pointercancel",finishGizmo);
    document.getElementById("holo-cast").addEventListener("click", async () => { const valid=validRods(model.objects,state.grid_size), exact = valid&&maskEqual(masks(model.objects), state.target_masks); event(model, "cast", {objects: copy(model.objects), masks: masks(model.objects), valid, exact}); if (!exact) { document.querySelector(".ivv")?.insertAdjacentHTML("beforeend", verdict("local", "CAST REJECTED", valid?"ONE OR MORE COLORED DEPTH DIES STILL DISAGREE":"TWO SOLID RODS OCCUPY THE SAME CELL")); setTimeout(() => document.querySelector(".ivv-verdict.is-local")?.remove(), 1100); return; } await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "CASTING AUTHENTICATED", `${state.objects.length} SOLID RODS · THREE FRONTMOST-COLOR PROJECTIONS`); });
    document.getElementById("holo-abandon").addEventListener("click", () => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", "")); update();
  };

  registry.orbital_docking_customs = async (state, helpers) => {
    document.body.dataset.mechanic = "orbital-docking-customs";
    const interaction = state.control_condition?.interaction || "simplified";
    const movingPort = Number(state.station.y_amplitude) > 0 || Number(state.station.rotation_deg_per_tick) !== 0;
    const historicalContract = state.debris.length === 2 && state.beacons.length === 2 && movingPort;
    const instruction = historicalContract
      ? "Fly the S-corridor through both scan beacons, avoid both debris fields, and match the moving rotating customs port."
      : `Clear ${state.beacons.length} ordered customs ${state.beacons.length === 1 ? "scan" : "scans"}, avoid ${state.debris.length} debris ${state.debris.length === 1 ? "field" : "fields"}, cancel relative speed, and match the ${movingPort ? "moving " : ""}port.`;
    const model = {state, helpers, interaction, events: [], ship: copy(state.ship), fuel: state.physics.fuel, ticks: 0, scans: [], collision: null, terminal: false, submitting: false}; window.orbitalDockingCustomsModel = model;
    const buttonDesk = `<div class="orbital-pad"><button data-orbit="rotate-left">↶ 15°</button><button data-orbit="thrust">MAIN +</button><button data-orbit="rotate-right">↷ 15°</button><button data-orbit="strafe-up">RCS ↑</button><button data-orbit="coast">COAST 10</button><button data-orbit="coast-long">COAST 30</button><button data-orbit="strafe-down">RCS ↓</button><button data-orbit="retro">RETRO −</button><button id="orbital-dock" class="ivv-primary">REQUEST HARD DOCK</button></div>`;
    const keyboardDesk = `<p class="orbital-keyboard-note">W MAIN + · S RETRO − · A RCS ↑ · D RCS ↓ · Q/E ATTITUDE · SPACE COAST 10 · SHIFT+SPACE COAST 30 · ENTER HARD DOCK</p>`;
    helpers.app.innerHTML = shell(state, "INERTIAL BORDER CONTROL", "ORBITAL DOCKING CUSTOMS", instruction, `<canvas id="orbital-canvas" width="900" height="480"></canvas>`, `
      <h2>${interaction === "simplified" ? "RCS IMPULSE DESK" : "DIRECT FLIGHT KEYS"}</h2>${interaction === "simplified" ? buttonDesk : keyboardDesk}<div id="orbital-telemetry" class="ivv-telemetry"></div><button id="orbital-abandon" class="ivv-danger">ABORT / FRESH ORBIT</button>`);
    const portAngle = () => (Number(state.station.angle_deg) + model.ticks * Number(state.station.rotation_deg_per_tick) + 36000) % 360;
    const stationY = () => Number(state.station.base_y) + Number(state.station.y_amplitude) * Math.sin(model.ticks * Number(state.station.y_rate) + Number(state.station.y_phase));
    const draw = () => { const ctx = document.getElementById("orbital-canvas").getContext("2d"); ctx.fillStyle = "#030712"; ctx.fillRect(0, 0, 900, 480); for (let i = 0; i < 100; i++) { const x = (i * 83 + 17) % 900, y = (i * 47 + 31) % 480; ctx.fillStyle = i % 7 ? "#52627f" : "#e8f2ff"; ctx.fillRect(x, y, 1.4, 1.4); } state.debris.forEach((debris)=>{ctx.fillStyle="#303746";ctx.beginPath();ctx.arc(debris.x,debris.y,debris.radius,0,Math.PI*2);ctx.fill();ctx.strokeStyle="#ff775f";ctx.setLineDash([5,8]);ctx.beginPath();ctx.arc(debris.x,debris.y,debris.radius+state.ship.radius,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);});state.beacons.forEach((beacon,index)=>{ctx.strokeStyle=index<model.scans.length?"#d8ff5b":"#e674ff";ctx.lineWidth=4;ctx.beginPath();ctx.arc(beacon.x,beacon.y,beacon.radius,0,Math.PI*2);ctx.stroke();ctx.fillStyle=ctx.strokeStyle;ctx.font="800 9px Courier New";ctx.fillText(`SCAN ${index+1}`,beacon.x-22,beacon.y-34);}); const station = state.station, currentPortAngle = portAngle(), currentStationY=stationY(); ctx.save(); ctx.translate(station.x, currentStationY); ctx.rotate(currentPortAngle * Math.PI / 180); ctx.strokeStyle = "#8ce4ff"; ctx.lineWidth = 8; ctx.strokeRect(-36, -52, 72, 104); ctx.fillStyle = "#d7ff5f"; ctx.fillRect(-8, -58, 16, 15); ctx.restore(); ctx.save(); ctx.translate(model.ship.x, model.ship.y); ctx.rotate(model.ship.angle_deg * Math.PI / 180); ctx.fillStyle = model.collision?"#ff6655":"#f6d37a"; ctx.beginPath(); ctx.moveTo(22, 0); ctx.lineTo(-15, -12); ctx.lineTo(-10, 0); ctx.lineTo(-15, 12); ctx.closePath(); ctx.fill(); ctx.restore(); ctx.strokeStyle = "#f6d37a55"; ctx.beginPath(); ctx.moveTo(model.ship.x, model.ship.y); ctx.lineTo(model.ship.x + model.ship.vx * 40, model.ship.y + model.ship.vy * 40); ctx.stroke(); document.getElementById("orbital-telemetry").innerHTML = `<span>FUEL <b>${model.fuel}</b></span><span>REL SPEED <b>${Math.hypot(model.ship.vx, model.ship.vy).toFixed(2)}</b></span><span>SCANS <b>${model.scans.length}/${state.beacons.length}</b></span><span>PORT / COAST <b>${currentPortAngle.toFixed(0)}° · ${model.ticks}</b></span>`; };
    const apply = (action, inputSource) => { if (model.terminal || model.submitting || model.collision) return; const before = copy(model.ship), p = state.physics, radians = model.ship.angle_deg * Math.PI / 180; if (["thrust", "retro", "strafe-up", "strafe-down"].includes(action)) { if (model.fuel <= 0) { setMessage(model, "FUEL MANIFOLD EMPTY", "error"); return; } model.fuel -= 1; const sign = action === "retro" ? -1 : 1; if (action === "thrust" || action === "retro") { model.ship.vx += Math.cos(radians) * p.impulse * sign; model.ship.vy += Math.sin(radians) * p.impulse * sign; } else { const side = action === "strafe-up" ? -1 : 1; model.ship.vx += Math.cos(radians + Math.PI / 2) * p.impulse * side; model.ship.vy += Math.sin(radians + Math.PI / 2) * p.impulse * side; } } else if (action === "rotate-left") model.ship.angle_deg = (model.ship.angle_deg - p.rotation_step_deg + 360) % 360; else if (action === "rotate-right") model.ship.angle_deg = (model.ship.angle_deg + p.rotation_step_deg) % 360; else if (["coast","coast-long"].includes(action)) { const coastTicks=action==="coast-long"?p.coast_long_ticks:p.coast_step_ticks; for (let tick = 0; tick < coastTicks && model.ticks<p.max_ticks; tick++) { model.ship.x += model.ship.vx; model.ship.y += model.ship.vy; model.ticks += 1; const debris = state.debris.find((item)=>Math.hypot(model.ship.x-item.x,model.ship.y-item.y)<model.ship.radius+item.radius); if(debris){model.collision=debris.id;setMessage(model,`HULL CONTACT · ${debris.id.toUpperCase()} · ABORT THIS TRIAL`,"error");break;}const beacon=state.beacons[model.scans.length];if(beacon&&Math.hypot(model.ship.x-beacon.x,model.ship.y-beacon.y)<=beacon.radius){model.scans.push(beacon.id);setMessage(model,`${beacon.id.toUpperCase()} CLEARED · CONTINUE RENDEZVOUS`,"passed");} } } event(model, "control", {action, before, after: copy(model.ship), fuel_after: model.fuel, ticks_after: model.ticks, scans_after:[...model.scans], collision:model.collision, input_source: inputSource}); draw(); };
    const requestDock = async (inputSource) => { const sy=stationY(),distance = Math.hypot(model.ship.x - state.station.x, model.ship.y - sy), speed = Math.hypot(model.ship.vx, model.ship.vy), target_angle = portAngle(), aligned = angleError(model.ship.angle_deg, target_angle) <= state.physics.angle_tolerance_deg, accepted = !model.collision&&model.scans.length===state.beacons.length&&distance <= state.physics.dock_distance && speed <= state.physics.dock_speed && aligned; event(model, "dock", {ship: copy(model.ship), ticks: model.ticks, station_y:round(sy), scans:[...model.scans], collision:model.collision, target_angle: round(target_angle), distance: round(distance), speed: round(speed), aligned, accepted, fuel_after: model.fuel, input_source: inputSource}); if (!accepted) { setMessage(model, `DOCK DENIED · SCANS ${model.scans.length}/${state.beacons.length} · RANGE ${distance.toFixed(1)} · SPEED ${speed.toFixed(2)} · PORT ${target_angle.toFixed(0)}°`, "error"); return; } await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "HARD DOCK AUTHENTICATED", `${state.beacons.length} ORDERED SCANS · SWEPT DEBRIS AVOIDANCE · ${movingPort ? "MOVING PORT" : "FIXED PORT"}`); };
    document.querySelectorAll("[data-orbit]").forEach((button) => button.addEventListener("click", () => apply(button.dataset.orbit, "rcs_button")));
    document.getElementById("orbital-dock")?.addEventListener("click", () => requestDock("dock_button"));
    if (interaction === "full") {
      const keys = {KeyW:"thrust", KeyS:"retro", KeyA:"strafe-up", KeyD:"strafe-down", KeyQ:"rotate-left", KeyE:"rotate-right", Space:"coast"};
      model.keyHandler = (keyboardEvent) => { if (keyboardEvent.repeat || model.terminal || model.submitting) return; if (keyboardEvent.code === "Enter") { keyboardEvent.preventDefault(); requestDock("dock_keyboard"); return; } const action = keyboardEvent.shiftKey && keyboardEvent.code === "Space" ? "coast-long" : keys[keyboardEvent.code]; if (!action) return; keyboardEvent.preventDefault(); apply(action, "rcs_keyboard"); };
      document.addEventListener("keydown", model.keyHandler);
    }
    document.getElementById("orbital-abandon").addEventListener("click", () => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", "")); draw();
  };

  function gravitySlide(board, position, direction, collected) { const vectors = [[1,0],[0,1],[-1,0],[0,-1]], [dx, dy] = vectors[(direction % 4 + 4) % 4], walls = new Set(board.walls.map((point) => point.join(":"))), gates = board.gates; let [x, y] = position; while (!walls.has(`${x + dx}:${y + dy}`)) { x += dx; y += dy; if (collected < gates.length && x === gates[collected][0] && y === gates[collected][1]) collected += 1; } return {position: [x, y], collected}; }
  registry.gravity_room_freight = async (state, helpers) => {
    document.body.dataset.mechanic = "gravity-room-freight";
    const interaction = state.control_condition?.interaction || "simplified";
    const sealCount = state.board.gates.length;
    const model = {
      state, helpers, interaction, events: [], cargo: [...state.board.cargo_start],
      counter: [...state.board.counter_start], orientation: state.initial_orientation,
      collected: 0, terminal: false, submitting: false, rotating: false, directGesture: null,
    };
    window.gravityRoomFreightModel = model;
    const goalCopy = sealCount === 4
      ? "Every quarter-turn moves the archive capsule and its isolated under-deck counterweight. Clear four seals and dock both bodies together."
      : `Every quarter-turn moves the archive capsule and its isolated under-deck counterweight. Clear ${sealCount} seals and dock both bodies together.`;
    const proxyControls = `<button data-gravity="ccw">↶ ROTATE ROOM</button><button data-gravity="cw">ROTATE ROOM ↷</button>`;
    const directControls = `<p class="gravity-direct-note">DRAG HORIZONTALLY ACROSS THE VISIBLE GIMBAL. RIGHT IS CLOCKWISE; LEFT IS COUNTER-CLOCKWISE.</p>`;
    helpers.app.innerHTML = shell(
      state,
      "ROTATING FREIGHT AUTHORITY",
      "GRAVITY-ROOM FREIGHT",
      goalCopy,
      `<div class="gravity-frame"><canvas id="gravity-canvas" width="520" height="520" aria-label="direct gravity room gimbal"></canvas></div>`,
      `<h2>ROOM GIMBAL</h2><p>The cyan diamond runs on an isolated rail layer: it shares walls and gravity but cannot collide with the amber capsule.</p>${interaction === "simplified" ? proxyControls : directControls}<div id="gravity-ledger" class="ivv-telemetry"></div><button id="gravity-certify" class="ivv-primary">CERTIFY DUAL DELIVERY</button><button id="gravity-abandon" class="ivv-danger">EJECT / FRESH ROOM</button>`,
    );
    const canvas = document.getElementById("gravity-canvas");
    const draw = () => {
      const ctx = canvas.getContext("2d"), board = state.board;
      const cell = Math.floor(496 / board.size), offset = (520 - cell * board.size) / 2;
      const cargoRadius = Math.max(12, Math.round(cell * .29));
      const inset = Math.max(7, Math.round(cell * .15));
      ctx.fillStyle = "#12100e";
      ctx.fillRect(0, 0, 520, 520);
      ctx.save();
      ctx.translate(260, 260);
      ctx.rotate(model.orientation * Math.PI / 2);
      ctx.translate(-260, -260);
      board.walls.forEach(([x, y]) => {
        ctx.fillStyle = "#564735";
        ctx.fillRect(offset + x * cell, offset + y * cell, cell - 2, cell - 2);
      });
      board.gates.forEach(([x, y], index) => {
        ctx.strokeStyle = index < model.collected ? "#baff63" : "#f2b957";
        ctx.lineWidth = Math.max(3, Math.round(cell * .08));
        ctx.strokeRect(offset + x * cell + inset, offset + y * cell + inset, cell - inset * 2, cell - inset * 2);
        ctx.fillStyle = ctx.strokeStyle;
        ctx.font = `900 ${Math.max(11, Math.round(cell * .24))}px Courier New`;
        ctx.fillText(String(index + 1), offset + x * cell + cell * .42, offset + y * cell + cell * .63);
      });
      ctx.fillStyle = "#6fdba0";
      ctx.fillRect(offset + board.cargo_target[0] * cell + inset + 4, offset + board.cargo_target[1] * cell + inset + 4, cell - inset * 2 - 8, cell - inset * 2 - 8);
      ctx.strokeStyle = "#5bd8e8";
      ctx.lineWidth = Math.max(3, Math.round(cell * .08));
      ctx.strokeRect(offset + board.counter_target[0] * cell + inset + 5, offset + board.counter_target[1] * cell + inset + 5, cell - inset * 2 - 10, cell - inset * 2 - 10);
      ctx.fillStyle = "#ff6b4a";
      ctx.beginPath();
      ctx.arc(offset + model.cargo[0] * cell + cell / 2, offset + model.cargo[1] * cell + cell / 2, cargoRadius, 0, Math.PI * 2);
      ctx.fill();
      ctx.save();
      ctx.translate(offset + model.counter[0] * cell + cell / 2, offset + model.counter[1] * cell + cell / 2);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = "#5bd8e8";
      const diamondSize = Math.max(10, Math.round(cell * .21));
      ctx.fillRect(-diamondSize, -diamondSize, diamondSize * 2, diamondSize * 2);
      ctx.restore();
      ctx.restore();
      document.getElementById("gravity-ledger").innerHTML = `<span>SEALS <b>${model.collected}/${sealCount}</b></span><span>ROOM FRAME <b>${model.orientation * 90}°</b></span><span>COUNTERWEIGHT <b>${model.counter.join(",")}</b></span>`;
    };
    const rotateRoom = (label, inputSource) => {
      if (model.rotating || model.terminal || model.submitting) return;
      model.rotating = true;
      const transition = helpers.beginAction?.("gravity_room_rotation");
      const before = {cargo: [...model.cargo], counter: [...model.counter], orientation: model.orientation, collected: model.collected};
      model.orientation = (model.orientation + (label === "cw" ? 1 : -1) + 4) % 4;
      const settledCargo = gravitySlide(state.board, model.cargo, model.orientation, model.collected);
      const settledCounter = gravitySlide(state.board, model.counter, model.orientation, 0);
      model.cargo = settledCargo.position;
      model.counter = settledCounter.position;
      model.collected = settledCargo.collected;
      event(model, "rotate", {
        direction: label,
        before,
        after: {cargo: [...model.cargo], counter: [...model.counter], orientation: model.orientation, collected: model.collected},
        input_source: inputSource,
      });
      document.querySelector(".gravity-frame").classList.add("is-rotating");
      setTimeout(() => {
        model.rotating = false;
        document.querySelector(".gravity-frame")?.classList.remove("is-rotating");
        draw();
        transition?.settle();
      }, state.rotation_ms);
      draw();
    };
    if (interaction === "simplified") {
      document.querySelectorAll("[data-gravity]").forEach((button) => button.addEventListener("click", () => rotateRoom(button.dataset.gravity, "rotation_button")));
    } else {
      canvas.classList.add("is-direct-gimbal");
      canvas.addEventListener("pointerdown", (pointerEvent) => {
        if (model.rotating || model.terminal || model.submitting) return;
        model.directGesture = {pointerId: pointerEvent.pointerId, x: pointerEvent.clientX, y: pointerEvent.clientY};
        canvas.setPointerCapture(pointerEvent.pointerId);
        pointerEvent.preventDefault();
      });
      const finishDirectGesture = (pointerEvent) => {
        const gesture = model.directGesture;
        if (!gesture || gesture.pointerId !== pointerEvent.pointerId) return;
        model.directGesture = null;
        if (canvas.hasPointerCapture(pointerEvent.pointerId)) canvas.releasePointerCapture(pointerEvent.pointerId);
        const dx = pointerEvent.clientX - gesture.x;
        const dy = pointerEvent.clientY - gesture.y;
        if (Math.abs(dx) < 48 || Math.abs(dx) < Math.abs(dy) * 1.2) {
          setMessage(model, "SWEEP HORIZONTALLY THROUGH THE GIMBAL TO APPLY ONE QUARTER-TURN", "error");
          return;
        }
        rotateRoom(dx > 0 ? "cw" : "ccw", "gimbal_drag");
      };
      canvas.addEventListener("pointerup", finishDirectGesture);
      canvas.addEventListener("pointercancel", () => { model.directGesture = null; });
    }
    document.getElementById("gravity-certify").addEventListener("click", async () => {
      const accepted = model.collected === sealCount
        && model.cargo[0] === state.board.cargo_target[0] && model.cargo[1] === state.board.cargo_target[1]
        && model.counter[0] === state.board.counter_target[0] && model.counter[1] === state.board.counter_target[1];
      event(model, "certify", {cargo: [...model.cargo], counter: [...model.counter], orientation: model.orientation, collected: model.collected, accepted, input_source: "certify_button"});
      if (!accepted) {
        setMessage(model, `DELIVERY DENIED · ${sealCount}-SEAL CAPSULE AND UNDER-DECK COUNTERWEIGHT MUST BOTH DOCK`, "error");
        return;
      }
      await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "DUAL GRAVITY FREIGHT ACCEPTED", `SHARED ROTATIONS · TWO SLIDING BODIES · ${sealCount} ORDERED SEALS`);
    });
    document.getElementById("gravity-abandon").addEventListener("click", () => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", ""));
    draw();
  };

  registry.floodgate_archive_rescue = async (state, helpers) => {
    document.body.dataset.mechanic = "floodgate-archive-rescue";
    const interaction = state.control_condition?.interaction || "simplified";
    const levelPrecision = Number(state.level_precision || 2);
    const model = {state, helpers, interaction, events: [], levels: state.chambers.map((item) => Number(item.level)), gates: state.gates.map(() => false), capsules: copy(state.capsules), terminal: false, submitting: false, directGesture: null};
    window.floodgateArchiveRescueModel = model;
    const manifold = state.circuits.map((circuit, index) => `C${index + 1}: V${circuit.between[0] + 1} ⇄ V${circuit.between[1] + 1}`).join(" · ");
    const directControls = `<p class="flood-direct-note">Drag water from one connected vault to the other. Click a physical lock to open it, then drag the capsule through that adjacent lock.</p><div class="flood-circuit-map">${esc(manifold)}</div>`;
    const proxyControls = `<div class="flood-controls">${state.circuits.map((circuit, index) => `<div><b>C${index + 1} · V${circuit.between[0] + 1}⇄V${circuit.between[1] + 1}</b><button data-circuit="${index}" data-direction="1">V${circuit.between[0] + 1} → V${circuit.between[1] + 1}</button><button data-circuit="${index}" data-direction="-1">V${circuit.between[1] + 1} → V${circuit.between[0] + 1}</button></div>`).join("")}</div><div class="flood-gates">${state.gates.map((_item, index) => `<button data-lock="${index}">TOGGLE LOCK ${index + 1}</button>`).join("")}</div><button id="flood-flow">TRANSFER THROUGH OPEN EQUALIZED LOCK</button>`;
    helpers.app.innerHTML = shell(
      state,
      "SUBMERGED RECORDS OFFICE",
      "FLOODGATE ARCHIVE RESCUE",
      "Use conserved transfer circuits to equalize locks while amber and cyan archive capsules travel in opposite directions.",
      `<div class="flood-vaults" style="grid-template-columns:repeat(${state.gates.length},minmax(0,1fr) 36px) minmax(0,1fr)">${state.chambers.map((chamber, index) => `<article data-vault="${index}"><b>${esc(chamber.id.toUpperCase())}</b><div class="flood-tank" data-vault="${index}"><i id="flood-water-${index}"></i><em class="flood-limit" style="bottom:${chamber.safe_max * 100}%"></em>${state.capsules.map((capsule) => `<span class="flood-capsule" data-capsule-id="${capsule.id}" id="flood-capsule-${capsule.id}-${index}" style="color:${capsule.color}">●</span>`).join("")}</div></article>${index < state.gates.length ? `<div class="flood-lock" data-physical-lock="${index}" id="flood-lock-${index}">LOCK ${index + 1}</div>` : ""}`).join("")}</div>`,
      `<h2>CONSERVATION MANIFOLD</h2><p>Every pump moves ${Number(state.pump_step).toFixed(levelPrecision)} from one visible vault to another; total water never changes.</p>${interaction === "simplified" ? proxyControls : directControls}<button id="flood-certify" class="ivv-primary">SEAL BOTH EVIDENCE DOCKS</button><button id="flood-abandon" class="ivv-danger">DRAIN / FRESH ARCHIVE</button>`,
    );
    const roundLevel = (value) => round(value, levelPrecision);
    const draw = () => {
      model.levels.forEach((level, index) => {
        document.getElementById(`flood-water-${index}`).style.height = `${level * 100}%`;
        model.capsules.forEach((capsule, capsuleIndex) => {
          const marker = document.getElementById(`flood-capsule-${capsule.id}-${index}`);
          marker.style.display = capsule.chamber === index ? "block" : "none";
          marker.style.bottom = `${Math.max(5, level * 100 - 9 - capsuleIndex * 8)}%`;
        });
      });
      model.gates.forEach((open, index) => document.getElementById(`flood-lock-${index}`).classList.toggle("is-open", open));
      const total = model.levels.reduce((sum, value) => sum + value, 0);
      const lastVault = state.chambers.length;
      setMessage(model, `AMBER V${model.capsules[0].chamber + 1} → V${lastVault} · CYAN V${model.capsules[1].chamber + 1} → V1 · TOTAL ${total.toFixed(levelPrecision)}`, "idle");
    };
    const pump = (circuitIndex, direction, inputSource) => {
      const circuit = state.circuits[circuitIndex];
      const source = direction === 1 ? circuit.between[0] : circuit.between[1];
      const destination = direction === 1 ? circuit.between[1] : circuit.between[0];
      const step = Number(state.pump_step);
      const before = [...model.levels];
      if (model.levels[source] - step < state.chambers[source].safe_min - 1e-6 || model.levels[destination] + step > state.chambers[destination].safe_max + 1e-6) {
        setMessage(model, "TRANSFER BLOCKED · A VAULT WOULD LEAVE ITS VISIBLE SAFE BAND", "error");
        return;
      }
      model.levels[source] = roundLevel(model.levels[source] - step);
      model.levels[destination] = roundLevel(model.levels[destination] + step);
      event(model, "pump", {circuit: circuitIndex, direction, source, destination, before, after: [...model.levels], total_after: roundLevel(model.levels.reduce((sum, value) => sum + value, 0)), input_source: inputSource});
      draw();
    };
    const toggleGate = (index, inputSource) => {
      const opening = !model.gates[index];
      model.gates = model.gates.map((_value, gate) => gate === index ? opening : false);
      event(model, "gate", {gate: index, open: opening, levels: [...model.levels], gates: [...model.gates], input_source: inputSource});
      draw();
    };
    const transfer = (gate, inputSource) => {
      const before = copy(model.capsules);
      const moved = [];
      if (gate < 0 || !model.gates[gate]) {
        setMessage(model, "OPEN ONE LOCK BEFORE TRANSFER", "error");
        return;
      }
      if (Math.abs(model.levels[gate] - model.levels[gate + 1]) <= state.equal_tolerance) {
        model.capsules.forEach((capsule) => {
          if (capsule.direction === 1 && capsule.chamber === gate) {
            capsule.chamber += 1;
            moved.push(capsule.id);
          } else if (capsule.direction === -1 && capsule.chamber === gate + 1) {
            capsule.chamber -= 1;
            moved.push(capsule.id);
          }
        });
      }
      event(model, "transfer", {gate, levels: [...model.levels], before_capsules: before, after_capsules: copy(model.capsules), moved, input_source: inputSource});
      setMessage(model, moved.length ? `${moved.map((id) => id.toUpperCase()).join(" + ")} CROSSED LOCK ${gate + 1}` : "NO CAPSULE CROSSED · LOCK LEVELS OR APPROACH SIDE DO NOT MATCH", moved.length ? "passed" : "error");
      draw();
    };
    if (interaction === "simplified") {
      document.querySelectorAll("[data-circuit]").forEach((button) => button.addEventListener("click", () => pump(Number(button.dataset.circuit), Number(button.dataset.direction), "circuit_button")));
      document.querySelectorAll("[data-lock]").forEach((button) => button.addEventListener("click", () => toggleGate(Number(button.dataset.lock), "lock_button")));
      document.getElementById("flood-flow").addEventListener("click", () => transfer(model.gates.findIndex(Boolean), "transfer_button"));
    } else {
      document.querySelectorAll("[data-physical-lock]").forEach((lock) => lock.addEventListener("click", () => toggleGate(Number(lock.dataset.physicalLock), "lock_direct")));
      const vaults = document.querySelector(".flood-vaults");
      const vaultAt = (clientX, clientY) => {
        const target = document.elementFromPoint(clientX, clientY);
        const vault = target?.closest("[data-vault]");
        return vault ? Number(vault.dataset.vault) : null;
      };
      vaults.addEventListener("pointerdown", (pointerEvent) => {
        if (model.terminal || model.submitting) return;
        const vault = pointerEvent.target.closest("[data-vault]");
        if (!vault) return;
        const capsule = pointerEvent.target.closest(".flood-capsule");
        model.directGesture = {kind: capsule ? "capsule" : "water", source: Number(vault.dataset.vault), capsule_id: capsule?.dataset.capsuleId || null, pointer_id: pointerEvent.pointerId};
        vaults.setPointerCapture(pointerEvent.pointerId);
        pointerEvent.preventDefault();
      });
      const finishDirectGesture = (pointerEvent) => {
        const gesture = model.directGesture;
        if (!gesture || gesture.pointer_id !== pointerEvent.pointerId) return;
        model.directGesture = null;
        if (vaults.hasPointerCapture(pointerEvent.pointerId)) vaults.releasePointerCapture(pointerEvent.pointerId);
        const destination = vaultAt(pointerEvent.clientX, pointerEvent.clientY);
        if (destination === null || destination === gesture.source) {
          setMessage(model, gesture.kind === "water" ? "DRAG WATER TO A CONNECTED VAULT" : "DRAG THE CAPSULE THROUGH ITS ADJACENT OPEN LOCK", "error");
          return;
        }
        if (gesture.kind === "water") {
          const circuitIndex = state.circuits.findIndex((circuit) => circuit.between.includes(gesture.source) && circuit.between.includes(destination));
          if (circuitIndex < 0) {
            setMessage(model, "NO VISIBLE MANIFOLD CIRCUIT CONNECTS THOSE VAULTS", "error");
            return;
          }
          const direction = state.circuits[circuitIndex].between[0] === gesture.source ? 1 : -1;
          pump(circuitIndex, direction, "water_drag");
          return;
        }
        const capsule = model.capsules.find((item) => item.id === gesture.capsule_id);
        const gate = Math.min(gesture.source, destination);
        if (!capsule || capsule.chamber !== gesture.source || destination !== gesture.source + capsule.direction || gate < 0 || gate >= state.gates.length) {
          setMessage(model, "CAPSULES CAN ONLY CROSS THEIR ADJACENT LOCK IN THE MARKED DIRECTION", "error");
          return;
        }
        transfer(gate, "capsule_drag");
      };
      vaults.addEventListener("pointerup", finishDirectGesture);
      vaults.addEventListener("pointercancel", () => { model.directGesture = null; });
    }
    document.getElementById("flood-certify").addEventListener("click", async () => {
      const accepted = model.capsules.every((capsule) => capsule.chamber === capsule.dock_chamber);
      event(model, "certify", {levels: [...model.levels], capsules: copy(model.capsules), accepted, input_source: "certify_button"});
      if (!accepted) {
        setMessage(model, "BOTH OPPOSING CAPSULES MUST REACH THEIR MARKED DOCKS", "error");
        return;
      }
      await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "ARCHIVE RESCUE AUTHENTICATED", "CONSERVED WATER · COUPLED LOCK LEVELS · OPPOSING CAPSULES");
    });
    document.getElementById("flood-abandon").addEventListener("click", () => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", ""));
    draw();
  };

  function membraneForce(heights, accel) { const left = (heights[0] + heights[2]) / 2, right = (heights[1] + heights[3]) / 2, top = (heights[0] + heights[1]) / 2, bottom = (heights[2] + heights[3]) / 2; return {x: (left - right) * Number(accel), y: (top - bottom) * Number(accel)}; }
  registry.elastic_membrane_sorter = async (state, helpers) => {
    document.body.dataset.mechanic = "elastic-membrane-sorter";
    const interaction = state.control_condition?.interaction || "simplified";
    const model = {state, helpers, interaction, events: [], roundIndex: 0, heights: [...state.rounds[0].post_heights], ball: {x: 450, y: 230, vx: 0, vy: 0}, running: false, checkpoint: 0, captured: [], terminal: false, submitting: false, interval: null, ticks: 0, postDrag: null};
    window.elasticMembraneSorterModel = model;
    const sliderControls = `<div class="membrane-sliders">${[0, 1, 2, 3].map((index) => `<label>P${index + 1}<input data-post="${index}" type="range" min="0" max="100" value="50"><span id="post-value-${index}">.50</span></label>`).join("")}</div>`;
    const directControls = `<p class="membrane-direct-note">DRAG A GLOWING POST MARKER UP OR DOWN ON THE MEMBRANE. ITS TRACK AND POSITION SHOW THE CURRENT TENSION.</p>`;
    helpers.app.innerHTML = shell(
      state,
      "SOFT-MATTER SORTING OFFICE",
      "ELASTIC MEMBRANE SORTER",
      "Release each marble, then steer the live membrane through the numbered rings before entering its highlighted well below the visible capture-speed limit.",
      `<canvas id="membrane-canvas" width="900" height="480"></canvas>`,
      `<h2>LIVE TENSION POSTS</h2><p>${interaction === "simplified" ? "Use the labelled tension sliders; all four posts remain live in flight." : "Use direct membrane-post dragging; all four markers remain live in flight."} Momentum persists after every correction.</p>${interaction === "simplified" ? sliderControls : directControls}<button id="membrane-release" class="ivv-primary">RELEASE MARBLE</button><button id="membrane-reset">RESET THIS MARBLE</button><button id="membrane-abandon" class="ivv-danger">CUT MEMBRANE / FRESH SORT</button>`,
    );
    const canvas = document.getElementById("membrane-canvas");
    const current = () => state.rounds[model.roundIndex];
    const postMarker = (index) => {
      const point = state.post_positions[index];
      return {x: point[0], y: clamp(point[1] + (.5 - model.heights[index]) * 80, 14, 466)};
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
      draw();
    };
    const resetRound = () => {
      clearInterval(model.interval);
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
      ctx.fillStyle = "#100e1d";
      ctx.fillRect(0, 0, 900, 480);
      for (let y = 0; y <= 12; y++) {
        ctx.beginPath();
        for (let x = 0; x <= 20; x++) {
          const px = x / 20 * 760 + 70, py = y / 12 * 370 + 55, u = x / 20, v = y / 12;
          const h = (1 - u) * (1 - v) * model.heights[0] + u * (1 - v) * model.heights[1] + (1 - u) * v * model.heights[2] + u * v * model.heights[3];
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
        ctx.fillStyle = `hsl(${220 + model.heights[index] * 90} 70% 62%)`; ctx.beginPath(); ctx.arc(marker.x, marker.y, 13, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "#f5edff"; ctx.lineWidth = 2; ctx.stroke(); ctx.fillStyle = "#f5edff"; ctx.font = "800 9px Courier New"; ctx.fillText(`P${index + 1}`, point[0] - 7, point[1] + 4);
      });
      ctx.fillStyle = "#ffcf63"; ctx.beginPath(); ctx.arc(model.ball.x, model.ball.y, 14, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#e8e1ff"; ctx.font = "800 11px Courier New";
      ctx.fillText(`MARBLE ${model.roundIndex + 1}/${state.rounds.length} · RINGS ${model.checkpoint}/${current().checkpoints.length} · SPEED ${Math.hypot(model.ball.vx, model.ball.vy).toFixed(2)} · TICK ${model.ticks}/${state.physics.max_ticks}`, 18, 24);
    };
    const release = () => {
      if (model.running || model.terminal) return;
      model.running = true;
      event(model, "release", {round_id: current().id, tick: model.ticks, heights: model.heights.map((value) => round(value, 2))});
      model.interval = setInterval(async () => {
        const force = membraneForce(model.heights, state.physics.slope_accel);
        model.ball.vx = (model.ball.vx + force.x) * state.physics.drag;
        model.ball.vy = (model.ball.vy + force.y) * state.physics.drag;
        model.ball.x += model.ball.vx; model.ball.y += model.ball.vy;
        if (model.ball.x < 28 || model.ball.x > 872) { model.ball.x = clamp(model.ball.x, 28, 872); model.ball.vx *= -state.physics.boundary_restitution; }
        if (model.ball.y < 28 || model.ball.y > 452) { model.ball.y = clamp(model.ball.y, 28, 452); model.ball.vy *= -state.physics.boundary_restitution; }
        model.ticks += 1;
        const checkpoint = current().checkpoints[model.checkpoint];
        if (checkpoint && Math.hypot(model.ball.x - checkpoint[0], model.ball.y - checkpoint[1]) <= state.physics.checkpoint_radius) {
          model.checkpoint += 1;
          event(model, "checkpoint", {round_id: current().id, tick: model.ticks, index: model.checkpoint - 1, ball: {x: round(model.ball.x), y: round(model.ball.y), vx: round(model.ball.vx), vy: round(model.ball.vy)}});
          setMessage(model, `INSPECTION RING ${model.checkpoint}/${current().checkpoints.length} CLEARED · KEEP STEERING`, "passed");
        }
        const well = current().wells[current().target_well], distance = Math.hypot(model.ball.x - well[0], model.ball.y - well[1]), speed = Math.hypot(model.ball.vx, model.ball.vy);
        if (model.checkpoint === current().checkpoints.length && distance < state.physics.well_radius && speed <= state.physics.capture_speed) {
          clearInterval(model.interval); model.running = false; model.captured.push(current().id);
          event(model, "capture", {round_id: current().id, tick: model.ticks, well: current().target_well, checkpoints: model.checkpoint, speed: round(speed), ball: {x: round(model.ball.x), y: round(model.ball.y), vx: round(model.ball.vx), vy: round(model.ball.vy)}, heights: model.heights.map((value) => round(value, 2))});
          if (model.roundIndex < state.rounds.length - 1) { model.roundIndex += 1; resetRound(); setMessage(model, "MARBLE CAPTURED · NEXT LIVE COURSE READY", "passed"); }
          else await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "MEMBRANE SORT AUTHENTICATED", "LIVE POST CHANGES · ORDERED RINGS · DAMPED CAPTURE");
          return;
        }
        if (model.ticks >= state.physics.max_ticks) {
          clearInterval(model.interval); model.running = false;
          event(model, "stall", {round_id: current().id, tick: model.ticks, ball: copy(model.ball), checkpoints: model.checkpoint});
          setMessage(model, "MOTION PAUSED AT THE VISIBLE SIMULATION LIMIT · RESET THIS MARBLE", "error");
        }
        draw();
      }, state.physics.tick_ms);
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
    document.getElementById("membrane-reset").addEventListener("click", () => { event(model, "reset", {round_id: current().id, tick: model.ticks}); resetRound(); });
    document.getElementById("membrane-abandon").addEventListener("click", () => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", ""));
    resetRound();
  };

  function segmentHitsRect(a,b,rect){const steps=Math.max(1,Math.ceil(Math.hypot(b.x-a.x,b.y-a.y)/5));for(let i=0;i<=steps;i++){const t=i/steps,x=a.x+(b.x-a.x)*t,y=a.y+(b.y-a.y)*t;if(x>rect.x-rect.w/2&&x<rect.x+rect.w/2&&y>rect.y-rect.h/2&&y<rect.y+rect.h/2)return true;}return false;}
  registry.pheromone_dispatch_v1 = async (state, helpers) => {
    document.body.dataset.mechanic="pheromone-dispatch";
    const model={state,helpers,events:[],path:[],activeStroke:[],route:[],drawing:false,ants:[],running:false,terminal:false,submitting:false,delivered:0,tick:0,lastRefreshTick:0,interval:null};
    window.pheromoneDispatchModel=model;
    helpers.app.innerHTML=shell(state,"MYRMECID LOGISTICS UNION","PHEROMONE DISPATCH","Paint nest → key → dock, release the carriers, then keep repainting the whole field before it evaporates.",`<canvas id="pheromone-canvas" width="900" height="480"></canvas>`,`<h2>TRAIL CONTROL</h2><p>Black salt blocks pheromone. During dispatch the field decays; retrace a complete safe route whenever freshness runs low.</p><button id="pheromone-dispatch" class="ivv-primary">RELEASE CARRIER SWARM</button><button id="pheromone-clear">WASH TRAIL</button><button id="pheromone-abandon" class="ivv-danger">FUMIGATE / FRESH COLONY</button><div id="pheromone-count" class="ivv-telemetry"></div>`);
    const canvas=document.getElementById("pheromone-canvas");
    const point=(e)=>{const r=canvas.getBoundingClientRect();return{x:round((e.clientX-r.left)/r.width*900,2),y:round((e.clientY-r.top)/r.height*480,2)}};
    const validPath=(path)=>path.length>5&&Math.hypot(path[0].x-state.nest[0],path[0].y-state.nest[1])<38&&path.some(p=>Math.hypot(p.x-state.key[0],p.y-state.key[1])<38)&&Math.hypot(path.at(-1).x-state.dock[0],path.at(-1).y-state.dock[1])<42&&!path.slice(1).some((p,i)=>state.obstacles.some(rect=>segmentHitsRect(path[i],p,rect)));
    const metrics=(path)=>{const lengths=[0];for(let i=1;i<path.length;i++)lengths.push(lengths[i-1]+Math.hypot(path[i].x-path[i-1].x,path[i].y-path[i-1].y));const keyIndex=path.reduce((best,p,i)=>Math.hypot(p.x-state.key[0],p.y-state.key[1])<Math.hypot(path[best].x-state.key[0],path[best].y-state.key[1])?i:best,0);return{lengths,total:lengths.at(-1),keyDistance:lengths[keyIndex]};};
    const stroke=(ctx,path,color,width)=>{if(path.length<2)return;ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap="round";ctx.lineJoin="round";ctx.beginPath();ctx.moveTo(path[0].x,path[0].y);path.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));ctx.stroke();};
    const draw=()=>{const ctx=canvas.getContext("2d");ctx.fillStyle="#e9dfbd";ctx.fillRect(0,0,900,480);ctx.fillStyle="#c8bd96";for(let i=0;i<130;i++)ctx.fillRect((i*73)%900,(i*41)%480,2,2);state.obstacles.forEach(rect=>{ctx.fillStyle="#27241f";ctx.fillRect(rect.x-rect.w/2,rect.y-rect.h/2,rect.w,rect.h);ctx.fillStyle="#f4dd87";ctx.font="800 9px Courier New";ctx.fillText("SALT",rect.x-13,rect.y);});const route=model.running?model.route:model.path,age=model.running?model.tick-model.lastRefreshTick:0,freshness=clamp(1-age/state.physics.trail_ttl_ticks,0,1);stroke(ctx,route,`rgba(189,58,91,${.16+.66*freshness})`,state.physics.brush_radius);stroke(ctx,route,`rgba(134,33,63,${.2+.8*freshness})`,2);if(model.running&&model.activeStroke.length>1)stroke(ctx,model.activeStroke,"rgba(255,89,130,.82)",8);[[state.nest,"NEST","#6a3d24"],[state.key,"KEY","#e39b25"],[state.dock,"DOCK","#467d52"]].forEach(([p,label,color])=>{ctx.fillStyle=color;ctx.beginPath();ctx.arc(p[0],p[1],24,0,Math.PI*2);ctx.fill();ctx.fillStyle="#fff";ctx.font="800 9px Courier New";ctx.fillText(label,p[0]-14,p[1]+3);});model.ants.forEach(ant=>{ctx.save();ctx.translate(ant.x,ant.y);ctx.rotate(ant.angle);ctx.fillStyle=ant.carrying?"#f4c352":"#261a16";ctx.beginPath();ctx.ellipse(0,0,7,3,0,0,Math.PI*2);ctx.fill();ctx.restore();});document.getElementById("pheromone-count").innerHTML=`<span>FIELD FRESH <b>${Math.round(freshness*100)}%</b></span><span>KEYS DELIVERED <b>${model.delivered}/${state.physics.delivery_required}</b></span>`;};
    canvas.addEventListener("pointerdown",e=>{if(model.terminal)return;model.drawing=true;model.activeStroke=[point(e)];if(!model.running)model.path=model.activeStroke;canvas.setPointerCapture(e.pointerId);event(model,"stroke_start",{tick:model.tick,mode:model.running?"refresh":"route",point:model.activeStroke[0]});draw();});
    canvas.addEventListener("pointermove",e=>{if(!model.drawing)return;const p=point(e),last=model.activeStroke.at(-1);if(Math.hypot(p.x-last.x,p.y-last.y)>=6){model.activeStroke.push(p);event(model,"stroke_point",{tick:model.tick,mode:model.running?"refresh":"route",point:p});draw();}});
    const endStroke=e=>{if(!model.drawing)return;model.drawing=false;event(model,"stroke_end",{tick:model.tick,mode:model.running?"refresh":"route",point:model.activeStroke.at(-1),samples:model.activeStroke.length});if(model.running){if(validPath(model.activeStroke)){model.lastRefreshTick=model.tick;event(model,"refresh",{tick:model.tick,path:model.activeStroke.map(copy)});setMessage(model,"FIELD REFRESHED · CARRIERS CONTINUE","passed");}else setMessage(model,"REFRESH REJECTED · RETRACE NEST → KEY → DOCK AROUND SALT","error");model.activeStroke=[];}try{canvas.releasePointerCapture(e.pointerId);}catch(_){}draw();};
    canvas.addEventListener("pointerup",endStroke);canvas.addEventListener("pointercancel",endStroke);
    document.getElementById("pheromone-clear").addEventListener("click",()=>{if(model.running)return;model.path=[];model.activeStroke=[];event(model,"clear",{tick:model.tick});draw();});
    document.getElementById("pheromone-dispatch").addEventListener("click",()=>{if(model.running||!validPath(model.path)){setMessage(model,"TRAIL REJECTED · CONNECT NEST → KEY → DOCK WITHOUT CROSSING SALT","error");return;}model.running=true;model.route=model.path.map(copy);model.activeStroke=[];model.lastRefreshTick=0;model.tick=0;event(model,"dispatch",{tick:0,path:model.route.map(copy)});const routeMetrics=metrics(model.route);model.ants=Array.from({length:state.ant_count},(_,index)=>({distance:-index*16,x:state.nest[0],y:state.nest[1],angle:0,carrying:false,done:false}));model.interval=setInterval(async()=>{model.tick+=1;const fresh=model.tick-model.lastRefreshTick<=state.physics.trail_ttl_ticks;if(fresh){for(const ant of model.ants){if(ant.done)continue;ant.distance+=state.physics.speed;if(ant.distance<0)continue;if(ant.distance>=routeMetrics.keyDistance)ant.carrying=true;if(ant.distance>=routeMetrics.total){ant.done=true;if(ant.carrying)model.delivered+=1;continue;}let segment=1;while(segment<routeMetrics.lengths.length&&routeMetrics.lengths[segment]<ant.distance)segment++;const a=model.route[segment-1],b=model.route[segment],span=routeMetrics.lengths[segment]-routeMetrics.lengths[segment-1]||1,t=(ant.distance-routeMetrics.lengths[segment-1])/span;ant.x=a.x+(b.x-a.x)*t;ant.y=a.y+(b.y-a.y)*t;ant.angle=Math.atan2(b.y-a.y,b.x-a.x);}}else setMessage(model,"FIELD EVAPORATED · CARRIERS WAITING FOR A COMPLETE REFRESH","error");draw();if(model.delivered>=state.physics.delivery_required){clearInterval(model.interval);event(model,"delivery",{tick:model.tick,delivered:model.delivered,path:model.route.map(copy),refresh_tick:model.lastRefreshTick});await submit(model,{mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,events:model.events,completed:true},"SWARM DISPATCH AUTHENTICATED","DECAYING FIELD · REPEATED FULL-STROKE REFRESH · KEY DELIVERY");return;}if(model.tick>=state.physics.max_ticks){clearInterval(model.interval);event(model,"timeout",{tick:model.tick,delivered:model.delivered});await submit(model,{mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,events:model.events,completed:false},"","");}},state.physics.tick_ms);});
    document.getElementById("pheromone-abandon").addEventListener("click",()=>submit(model,{mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,events:[...model.events,{seq:model.events.length+1,type:"abandon",tick:model.tick}],completed:false},"",""));draw();
  };

  registry.pheromone_dispatch = async (state, helpers) => {
    document.body.dataset.mechanic = "pheromone-dispatch";
    const interaction = state.control_condition?.interaction || "full";
    const MAX_ROUTE_SAMPLE_GAP = 160;
    const swarmCount = state.fields.length;
    const swarmLabel = swarmCount === 1 ? "CARRIER SWARM" : "BOTH SWARMS";
    const paths = Object.fromEntries(state.fields.map((field) => [field.id, []]));
    const model = {
      state, helpers, interaction, events: [], paths, routes: {}, activeField: state.fields[0].id,
      activeStroke: [], activeStrokeRejected: false, drawing: false, ants: {}, running: false, terminal: false,
      submitting: false, delivered: Object.fromEntries(state.fields.map((field) => [field.id, 0])),
      lastRefresh: Object.fromEntries(state.fields.map((field) => [field.id, 0])), tick: 0, interval: null,
    };
    window.pheromoneDispatchModel = model;
    const record = (type, details = {}) => event(model, type, {
      ...details,
      input_surface: interaction,
      input_method: interaction === "simplified" ? "waypoint_clicks" : "continuous_pointer_trace",
    });
    const fieldControls = `<div class="pheromone-fields">${state.fields.map((field, index) => `<button data-field="${field.id}" class="${index === 0 ? "is-selected" : ""}" style="--field:${field.color}">${interaction === "simplified" ? `PLOT ${esc(field.id).toUpperCase()} FIELD` : esc(field.label)}</button>`).join("")}</div>`;
    const fieldInstruction = interaction === "simplified"
      ? "Select a colored field, click its ordered route vertices on the habitat, then commit the plotted field. Begin at the nest, visit that color's cache, end at the dock, and route around every black salt block."
      : swarmCount === 1
        ? "Select the colored brush and trace its complete field directly. Black salt blocks pheromone; renew the route before it evaporates."
        : "Select a colored brush and trace each complete field directly. Black salt blocks both colors; refreshing amber never refreshes violet.";
    helpers.app.innerHTML = shell(
      state, "MYRMECID LOGISTICS UNION", "PHEROMONE DISPATCH",
      swarmCount === 1
        ? "Paint one colored nest→cache→dock field, release its team, then renew the complete route before it evaporates."
        : "Paint two colored nest→cache→dock fields, release both teams, then alternate full refresh strokes as each field decays independently.",
      `<canvas id="pheromone-canvas" width="900" height="480"></canvas>`,
      `<h2>${interaction === "simplified" ? "WAYPOINT FIELD PLOTTER" : swarmCount === 1 ? "FIELD CONTROL" : "DUAL FIELD CONTROL"}</h2><p>${fieldInstruction}</p>
       ${fieldControls}
       ${interaction === "simplified" ? '<button id="pheromone-commit">COMMIT PLOTTED FIELD</button>' : ""}
       <button id="pheromone-dispatch" class="ivv-primary">RELEASE ${swarmLabel}</button><button id="pheromone-clear">WASH ACTIVE FIELD</button><button id="pheromone-abandon" class="ivv-danger">FUMIGATE / FRESH COLONY</button><div id="pheromone-count" class="ivv-telemetry"></div>`,
    );
    const canvas = document.getElementById("pheromone-canvas");
    const fieldById = (id) => state.fields.find((field) => field.id === id);
    const canvasPoint = (e) => { const rect = canvas.getBoundingClientRect(); return {x: round((e.clientX - rect.left) / rect.width * 900, 2), y: round((e.clientY - rect.top) / rect.height * 480, 2)}; };
    const hasSamplingGap = (path) => path.slice(1).some((point, index) => Math.hypot(point.x - path[index].x, point.y - path[index].y) > MAX_ROUTE_SAMPLE_GAP);
    const rejectSamplingGap = () => setMessage(model, interaction === "simplified" ? "PLOT GAP TOO LARGE · WASH AND ADD INTERMEDIATE WAYPOINTS" : "BRUSH GAP TOO LARGE · RETRACE WITH CONTINUOUS MOTION", "error");
    const validPath = (path, field) => path.length > 5
      && Math.hypot(path[0].x - state.nest[0], path[0].y - state.nest[1]) < 38
      && path.some((point) => Math.hypot(point.x - field.cache[0], point.y - field.cache[1]) < 38)
      && Math.hypot(path.at(-1).x - state.dock[0], path.at(-1).y - state.dock[1]) < 42
      && !hasSamplingGap(path)
      && !path.slice(1).some((point, index) => state.obstacles.some((rect) => segmentHitsRect(path[index], point, rect)));
    const metrics = (path, field) => {
      const lengths = [0];
      for (let index = 1; index < path.length; index++) lengths.push(lengths[index - 1] + Math.hypot(path[index].x - path[index - 1].x, path[index].y - path[index - 1].y));
      const cacheIndex = path.reduce((best, point, index) => Math.hypot(point.x - field.cache[0], point.y - field.cache[1]) < Math.hypot(path[best].x - field.cache[0], path[best].y - field.cache[1]) ? index : best, 0);
      return {lengths, total: lengths.at(-1), cacheDistance: lengths[cacheIndex]};
    };
    const paint = (ctx, path, color, width) => { if (path.length < 2) return; ctx.strokeStyle = color; ctx.lineWidth = width; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.beginPath(); ctx.moveTo(path[0].x, path[0].y); path.slice(1).forEach((point) => ctx.lineTo(point.x, point.y)); ctx.stroke(); };
    const draw = () => {
      const ctx = canvas.getContext("2d"); ctx.fillStyle = "#e9dfbd"; ctx.fillRect(0, 0, 900, 480); ctx.fillStyle = "#c8bd96";
      for (let index = 0; index < 130; index++) ctx.fillRect((index * 73) % 900, (index * 41) % 480, 2, 2);
      state.obstacles.forEach((rect) => { ctx.fillStyle = "#27241f"; ctx.fillRect(rect.x - rect.w / 2, rect.y - rect.h / 2, rect.w, rect.h); ctx.fillStyle = "#f4dd87"; ctx.font = "800 9px Courier New"; ctx.fillText("SALT", rect.x - 13, rect.y); });
      state.fields.forEach((field) => {
        const route = model.running ? model.routes[field.id] : model.paths[field.id];
        const freshness = clamp(1 - (model.running ? model.tick - model.lastRefresh[field.id] : 0) / field.trail_ttl_ticks, 0, 1);
        const alpha = Math.round((.18 + .66 * freshness) * 255).toString(16).padStart(2, "0");
        paint(ctx, route, field.color + alpha, state.physics.brush_radius); paint(ctx, route, field.color, 2);
      });
      if (model.activeStroke.length > 1) paint(ctx, model.activeStroke, fieldById(model.activeField).color, 8);
      [[state.nest, "NEST", "#6a3d24"], [state.dock, "DOCK", "#467d52"]].forEach(([point, label, color]) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(point[0], point[1], 24, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = "#fff"; ctx.font = "800 9px Courier New"; ctx.fillText(label, point[0] - 14, point[1] + 3); });
      state.fields.forEach((field) => {
        ctx.fillStyle = field.color; ctx.beginPath(); ctx.arc(field.cache[0], field.cache[1], 24, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = "#fff"; ctx.font = "800 8px Courier New"; ctx.fillText(`${field.id.toUpperCase()} CACHE`, field.cache[0] - 32, field.cache[1] + 3);
        (model.ants[field.id] || []).forEach((ant) => { ctx.save(); ctx.translate(ant.x, ant.y); ctx.rotate(ant.angle); ctx.fillStyle = ant.carrying ? field.color : "#261a16"; ctx.beginPath(); ctx.ellipse(0, 0, 7, 3, 0, 0, Math.PI * 2); ctx.fill(); ctx.restore(); });
      });
      document.getElementById("pheromone-count").innerHTML = state.fields.map((field) => { const freshness = clamp(1 - (model.running ? model.tick - model.lastRefresh[field.id] : 0) / field.trail_ttl_ticks, 0, 1); return `<span style="color:${field.color}">${field.id.toUpperCase()} FRESH <b>${Math.round(freshness * 100)}%</b> · KEYS <b>${model.delivered[field.id]}/${state.physics.delivery_required}</b></span>`; }).join("");
    };
    canvas.addEventListener("pointerdown", (e) => { if (interaction !== "full" || model.terminal) return; model.drawing = true; model.activeStrokeRejected = false; model.activeStroke = [canvasPoint(e)]; canvas.setPointerCapture(e.pointerId); record("stroke_start", {tick: model.tick, field_id: model.activeField, mode: model.running ? "refresh" : "route", point: model.activeStroke[0]}); draw(); });
    canvas.addEventListener("pointermove", (e) => { if (interaction !== "full" || !model.drawing) return; const point = canvasPoint(e), last = model.activeStroke.at(-1), distance = Math.hypot(point.x - last.x, point.y - last.y); if (distance > MAX_ROUTE_SAMPLE_GAP) { model.activeStrokeRejected = true; rejectSamplingGap(); draw(); return; } if (distance >= 6) { model.activeStroke.push(point); record("stroke_point", {tick: model.tick, field_id: model.activeField, mode: model.running ? "refresh" : "route", point}); draw(); } });
    const endStroke = (e) => {
      if (interaction !== "full" || !model.drawing) return; model.drawing = false; const field = fieldById(model.activeField);
      record("stroke_end", {tick: model.tick, field_id: field.id, mode: model.running ? "refresh" : "route", point: model.activeStroke.at(-1), samples: model.activeStroke.length});
      const accepted = !model.activeStrokeRejected && validPath(model.activeStroke, field);
      if (model.running) { if (accepted) { model.lastRefresh[field.id] = model.tick; record("refresh", {tick: model.tick, field_id: field.id, path: model.activeStroke.map(copy)}); setMessage(model, `${field.id.toUpperCase()} FIELD REFRESHED · OTHER COLOR UNCHANGED`, "passed"); } else if (model.activeStrokeRejected) rejectSamplingGap(); else setMessage(model, `REFRESH REJECTED · RETRACE ${field.id.toUpperCase()} NEST → CACHE → DOCK`, "error"); model.activeStroke = []; model.activeStrokeRejected = false; }
      else { model.paths[field.id] = model.activeStroke.map(copy); if (accepted) setMessage(model, `${field.id.toUpperCase()} FIELD TRACED`, "passed"); else if (model.activeStrokeRejected) rejectSamplingGap(); else setMessage(model, `FIELD REJECTED · TRACE ${field.id.toUpperCase()} NEST → CACHE → DOCK AROUND SALT`, "error"); model.activeStroke = []; model.activeStrokeRejected = false; }
      try { canvas.releasePointerCapture(e.pointerId); } catch (_) {} draw();
    };
    canvas.addEventListener("pointerup", endStroke); canvas.addEventListener("pointercancel", endStroke);
    const selectField = (fieldId) => {
      if (model.drawing || (interaction === "simplified" && model.activeStroke.length)) { setMessage(model, "COMMIT THE CURRENT PLOTTED FIELD BEFORE CHANGING COLOR", "error"); return; }
      model.activeField = fieldId;
      document.querySelectorAll("[data-field]").forEach((item) => item.classList.toggle("is-selected", item.dataset.field === model.activeField));
      setMessage(model, `${model.activeField.toUpperCase()} ${interaction === "simplified" ? "PLOT SELECTED" : "BRUSH SELECTED"}`, "idle"); draw();
    };
    document.querySelectorAll("[data-field]").forEach((button) => button.addEventListener("click", () => selectField(button.dataset.field)));
    canvas.addEventListener("click", (e) => {
      if (interaction !== "simplified" || model.terminal || model.submitting) return;
      const point = canvasPoint(e), field = fieldById(model.activeField), mode = model.running ? "refresh" : "route";
      if (!model.activeStroke.length) {
        model.activeStrokeRejected = false;
        model.activeStroke = [point];
        record("stroke_start", {tick: model.tick, field_id: field.id, mode, point});
      } else if (Math.hypot(point.x - model.activeStroke.at(-1).x, point.y - model.activeStroke.at(-1).y) > MAX_ROUTE_SAMPLE_GAP) {
        model.activeStrokeRejected = true; rejectSamplingGap();
      } else if (Math.hypot(point.x - model.activeStroke.at(-1).x, point.y - model.activeStroke.at(-1).y) >= 6) {
        model.activeStroke.push(point);
        record("stroke_point", {tick: model.tick, field_id: field.id, mode, point});
      }
      draw();
    });
    document.getElementById("pheromone-commit")?.addEventListener("click", () => {
      if (interaction !== "simplified" || model.terminal || model.submitting) return;
      const field = fieldById(model.activeField), mode = model.running ? "refresh" : "route";
      if (!model.activeStroke.length) { setMessage(model, "CLICK ROUTE VERTICES ON THE HABITAT BEFORE COMMITTING", "error"); return; }
      record("stroke_end", {tick: model.tick, field_id: field.id, mode, point: model.activeStroke.at(-1), samples: model.activeStroke.length});
      const accepted = !model.activeStrokeRejected && validPath(model.activeStroke, field);
      if (model.running) {
        if (accepted) { model.lastRefresh[field.id] = model.tick; record("refresh", {tick: model.tick, field_id: field.id, path: model.activeStroke.map(copy)}); setMessage(model, `${field.id.toUpperCase()} FIELD REFRESHED · OTHER COLOR UNCHANGED`, "passed"); }
        else if (model.activeStrokeRejected) rejectSamplingGap(); else setMessage(model, `REFRESH REJECTED · PLOT ${field.id.toUpperCase()} NEST → CACHE → DOCK AROUND SALT`, "error");
      } else { model.paths[field.id] = model.activeStroke.map(copy); if (accepted) setMessage(model, `${field.id.toUpperCase()} FIELD PLOTTED`, "passed"); else if (model.activeStrokeRejected) rejectSamplingGap(); else setMessage(model, `PLOT REJECTED · TRACE ${field.id.toUpperCase()} NEST → CACHE → DOCK AROUND SALT`, "error"); }
      model.activeStroke = []; model.activeStrokeRejected = false; draw();
    });
    document.getElementById("pheromone-clear").addEventListener("click", () => {
      if (model.running) return;
      if (interaction === "simplified" && model.activeStroke.length) { setMessage(model, "COMMIT THE PLOTTED FIELD BEFORE WASHING IT", "error"); return; }
      model.paths[model.activeField] = []; model.activeStroke = []; model.activeStrokeRejected = false; record("clear", {tick: model.tick, field_id: model.activeField}); draw();
    });
    document.getElementById("pheromone-dispatch").addEventListener("click", () => {
      if (model.running || state.fields.some((field) => !validPath(model.paths[field.id], field))) { setMessage(model, `${swarmCount === 1 ? "THE COLORED TRAIL" : "BOTH COLORED TRAILS"} MUST CONNECT ${swarmCount === 1 ? "THE" : "THEIR OWN"} CACHE WITHOUT CROSSING SALT`, "error"); return; }
      model.running = true; model.routes = Object.fromEntries(state.fields.map((field) => [field.id, model.paths[field.id].map(copy)])); model.activeStroke = []; model.tick = 0; model.lastRefresh = Object.fromEntries(state.fields.map((field) => [field.id, 0])); record("dispatch", {tick: 0, paths: copy(model.routes)});
      const routeMetrics = Object.fromEntries(state.fields.map((field) => [field.id, metrics(model.routes[field.id], field)]));
      state.fields.forEach((field) => { model.ants[field.id] = Array.from({length: state.ant_count}, (_, index) => ({distance: -index * state.physics.ant_spacing, x: state.nest[0], y: state.nest[1], angle: 0, carrying: false, done: false})); });
      model.interval = setInterval(async () => {
        model.tick += 1;
        state.fields.forEach((field) => {
          if (model.tick - model.lastRefresh[field.id] > field.trail_ttl_ticks) return;
          const route = model.routes[field.id], info = routeMetrics[field.id];
          for (const ant of model.ants[field.id]) { if (ant.done) continue; ant.distance += field.speed; if (ant.distance < 0) continue; if (ant.distance >= info.cacheDistance) ant.carrying = true; if (ant.distance >= info.total) { ant.done = true; if (ant.carrying) model.delivered[field.id] += 1; continue; } let segment = 1; while (segment < info.lengths.length && info.lengths[segment] < ant.distance) segment++; const first = route[segment - 1], second = route[segment], span = info.lengths[segment] - info.lengths[segment - 1] || 1, amount = (ant.distance - info.lengths[segment - 1]) / span; ant.x = first.x + (second.x - first.x) * amount; ant.y = first.y + (second.y - first.y) * amount; ant.angle = Math.atan2(second.y - first.y, second.x - first.x); }
        });
        draw();
        if (state.fields.every((field) => model.delivered[field.id] >= state.physics.delivery_required)) { clearInterval(model.interval); record("delivery", {tick: model.tick, delivered: copy(model.delivered), last_refresh: copy(model.lastRefresh)}); await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, interaction_mode: interaction, events: model.events, completed: true}, `${state.fields.length === 2 ? "DUAL" : "SINGLE"} SWARM DISPATCH AUTHENTICATED`, `${state.fields.length === 2 ? "INDEPENDENT DECAY FIELDS" : "DECAYING FIELD"} · COMPLETE-ROUTE REFRESH · KEY DELIVERY`); }
      }, state.physics.tick_ms);
    });
    document.getElementById("pheromone-abandon").addEventListener("click", () => { record("abandon", {tick: model.tick}); submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, interaction_mode: interaction, events: model.events, completed: false}, "", ""); }); draw();
  };

  registry.clockwork_clutch_safe_v1 = async (state, helpers) => {
    document.body.dataset.mechanic="clockwork-clutch-safe";const model={state,helpers,events:[],shafts:copy(state.shafts),tick:0,running:false,terminal:false,submitting:false,interval:null};window.clockworkClutchSafeModel=model;
    helpers.app.innerHTML=shell(state,"HOROLOGICAL CRIME UNIT","CLOCKWORK CLUTCH SAFE","Run the drive and release each live clutch exactly as its seal crosses the witness mark. Brake all three together at zero.",`<div class="clutch-bank">${state.shafts.map((shaft,index)=>`<article><canvas id="clutch-${index}" width="230" height="230"></canvas><button data-clutch="${index}">RELEASE ${esc(shaft.id.toUpperCase())}</button></article>`).join("")}</div>`,`<h2>MASTER DRIVE</h2><button id="clutch-drive" class="ivv-primary">START DRIVE</button><button id="clutch-brake">BRAKE / STOP DRIVE</button><button id="clutch-unlock">TRY SAFE</button><div id="clutch-tick" class="ivv-telemetry"></div><button id="clutch-abandon" class="ivv-danger">BREAK TRAIN / FRESH SAFE</button>`);
    const draw=()=>{model.shafts.forEach((shaft,index)=>{const ctx=document.getElementById(`clutch-${index}`).getContext("2d");ctx.clearRect(0,0,230,230);ctx.fillStyle="#13110d";ctx.fillRect(0,0,230,230);ctx.save();ctx.translate(115,115);ctx.rotate(shaft.angle_deg*Math.PI/180);ctx.strokeStyle=shaft.engaged?"#e5ad4b":"#70d39b";ctx.lineWidth=12;ctx.beginPath();ctx.arc(0,0,78,0,Math.PI*2);ctx.stroke();for(let tooth=0;tooth<18;tooth++){ctx.rotate(Math.PI*2/18);ctx.fillStyle=ctx.strokeStyle;ctx.fillRect(72,-5,18,10);}ctx.fillStyle="#f7ead0";ctx.fillRect(-5,-82,10,28);ctx.restore();ctx.fillStyle="#ff5d4e";ctx.fillRect(111,8,8,28);ctx.fillStyle="#c4b9a5";ctx.font="800 10px Courier New";ctx.fillText(`${shaft.angle_deg.toFixed(1)}° · ${shaft.engaged?"COUPLED":"FREE"}`,62,214);});document.getElementById("clutch-tick").innerHTML=`<span>DRIVE TICK <b>${model.tick}</b></span><span>COUPLED <b>${model.shafts.filter(s=>s.engaged).length}</b></span>`;};
    const tick=()=>{model.tick+=1;model.shafts.forEach(shaft=>{if(shaft.engaged)shaft.angle_deg=(shaft.angle_deg+shaft.ratio*state.physics.drive_deg_per_tick+360)%360;});draw();if(model.tick>=state.physics.max_ticks){clearInterval(model.interval);model.running=false;document.getElementById("clutch-drive").textContent="RESTART DRIVE";setMessage(model,"MAXIMUM WIND REACHED · RE-ENGAGE AND CORRECT","error");}};const start=()=>{if(model.running)return;model.running=true;event(model,"drive",{tick:model.tick,running:true});document.getElementById("clutch-drive").textContent="DRIVE RUNNING";model.interval=setInterval(tick,state.physics.tick_ms);};const stop=()=>{if(!model.running)return;clearInterval(model.interval);model.running=false;event(model,"drive",{tick:model.tick,running:false,angles:model.shafts.map(s=>round(s.angle_deg))});document.getElementById("clutch-drive").textContent="START DRIVE";draw();};document.getElementById("clutch-drive").addEventListener("click",start);document.getElementById("clutch-brake").addEventListener("click",stop);document.querySelectorAll("[data-clutch]").forEach(button=>button.addEventListener("click",()=>{const index=Number(button.dataset.clutch),shaft=model.shafts[index],before=shaft.engaged;shaft.engaged=!shaft.engaged;event(model,"clutch",{tick:model.tick,shaft:index,before,after:shaft.engaged,angle_deg:round(shaft.angle_deg)});button.textContent=`${shaft.engaged?"RELEASE":"ENGAGE"} ${state.shafts[index].id.toUpperCase()}`;draw();}));document.getElementById("clutch-unlock").addEventListener("click",async()=>{stop();const errors=model.shafts.map(s=>angleError(s.angle_deg,0)),accepted=model.shafts.every((s,i)=>!s.engaged&&errors[i]<=state.physics.phase_tolerance_deg);event(model,"unlock",{tick:model.tick,angles:model.shafts.map(s=>round(s.angle_deg)),engaged:model.shafts.map(s=>s.engaged),accepted});if(!accepted){setMessage(model,`SAFE REFUSES · PHASE ERRORS ${errors.map(v=>v.toFixed(1)).join(" / ")}`,"error");return;}await submit(model,{mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,events:model.events,completed:true},"CLOCKWORK SAFE OPEN","COUPLED RATIOS · RELEASE TICKS · FINAL PHASE");});document.getElementById("clutch-abandon").addEventListener("click",()=>submit(model,{mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,events:[...model.events,{seq:model.events.length+1,type:"abandon"}],completed:false},"",""));draw();
  };

  registry.clockwork_clutch_safe = async (state, helpers) => {
    document.body.dataset.mechanic = "clockwork-clutch-safe";
    const interaction = state.control_condition?.interaction || "simplified";
    const model = {state, helpers, interaction, events: [], shafts: copy(state.shafts), tick: 0, running: false, terminal: false, submitting: false, interval: null, clutchDrag: null};
    const showAngleReadout = state.physics.show_angle_readout !== false;
    const showSpeedReadout = state.physics.show_speed_readout !== false;
    const reengagementAllowed = state.physics.reengagement_allowed !== false;
    const shaftCountWord = ({1: "one", 2: "two", 3: "three", 4: "four"})[state.shafts.length] || String(state.shafts.length);
    window.clockworkClutchSafeModel = model;
    const clutchControl = (shaft, index) => interaction === "simplified"
      ? `<button data-clutch="${index}">RELEASE ${esc(shaft.id.toUpperCase())}</button>`
      : `<div class="clutch-lever" data-clutch-lever="${index}" data-state="coupled" aria-label="${esc(shaft.id)} clutch lever: coupled">
          <span>COUPLED</span><div class="clutch-lever-rail"><i class="clutch-lever-handle"></i></div><span>FREE</span>
        </div>`;
    helpers.app.innerHTML = shell(
      state, "HOROLOGICAL CRIME UNIT", "CLOCKWORK CLUTCH SAFE",
      `Release ${shaftCountWord} ${state.shafts.length === 1 ? "seal" : "seals"} at the witness mark. Every clutch change redistributes load and changes every shaft still coupled to the drive.`,
      `<div class="clutch-bank">${state.shafts.map((shaft, index) => `<article><canvas id="clutch-${index}" width="230" height="230"></canvas>${clutchControl(shaft, index)}</article>`).join("")}</div>`,
      `<h2>LOAD-COUPLED MASTER DRIVE</h2><p>Fewer engaged shafts run faster. ${reengagementAllowed ? "Re-engagement is legal for recovery." : "Released clutches are irreversible in this trial."}</p><button id="clutch-drive" class="ivv-primary">START DRIVE</button><button id="clutch-brake">BRAKE / STOP DRIVE</button><button id="clutch-unlock">TRY SAFE</button><div id="clutch-tick" class="ivv-telemetry"></div><button id="clutch-abandon" class="ivv-danger">BREAK TRAIN / FRESH SAFE</button>`,
    );
    const speeds = () => { const active = model.shafts.filter((shaft) => shaft.engaged).length, factor = active ? Number(state.physics.load_numerator) / active : 0; return model.shafts.map((shaft) => shaft.engaged ? Number(shaft.ratio) * Number(state.physics.drive_deg_per_tick) * factor : 0); };
    const draw = () => {
      const currentSpeeds = speeds();
      model.shafts.forEach((shaft, index) => {
        const ctx = document.getElementById(`clutch-${index}`).getContext("2d");
        ctx.clearRect(0, 0, 230, 230); ctx.fillStyle = "#13110d"; ctx.fillRect(0, 0, 230, 230); ctx.save(); ctx.translate(115, 115); ctx.rotate(shaft.angle_deg * Math.PI / 180); ctx.strokeStyle = shaft.engaged ? "#e5ad4b" : "#70d39b"; ctx.lineWidth = 12; ctx.beginPath(); ctx.arc(0, 0, 78, 0, Math.PI * 2); ctx.stroke(); for (let tooth = 0; tooth < 18; tooth++) { ctx.rotate(Math.PI * 2 / 18); ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(72, -5, 18, 10); } ctx.fillStyle = "#f7ead0"; ctx.fillRect(-5, -82, 10, 28); ctx.restore(); ctx.fillStyle = "#ff5d4e"; ctx.fillRect(111, 8, 8, 28); ctx.fillStyle = "#c4b9a5"; ctx.font = "800 10px Courier New";
        const currentTelemetry = showAngleReadout && showSpeedReadout
          ? `${shaft.angle_deg.toFixed(1)}° · ${shaft.engaged ? `${currentSpeeds[index].toFixed(1)}°/T` : "FREE"}`
          : [
              shaft.id.toUpperCase(),
              showAngleReadout ? `${shaft.angle_deg.toFixed(1)}°` : null,
              shaft.engaged ? (showSpeedReadout ? `${currentSpeeds[index].toFixed(1)}°/T` : "COUPLED") : "FREE",
            ].filter(Boolean).join(" · ");
        ctx.fillText(currentTelemetry, showAngleReadout && showSpeedReadout ? 52 : 48, 214);
      });
      document.getElementById("clutch-tick").innerHTML = `<span>DRIVE TICK <b>${model.tick}/${state.physics.max_ticks}</b></span><span>COUPLED <b>${model.shafts.filter((shaft) => shaft.engaged).length}</b></span><span>LOAD FACTOR <b>${model.shafts.some((shaft) => shaft.engaged) ? (state.physics.load_numerator / model.shafts.filter((shaft) => shaft.engaged).length).toFixed(2) : "0"}×</b></span>`;
    };
    const tick = () => { model.tick += 1; const currentSpeeds = speeds(); model.shafts.forEach((shaft, index) => { if (shaft.engaged) shaft.angle_deg = (shaft.angle_deg + currentSpeeds[index] + 3600) % 360; }); draw(); if (model.tick >= state.physics.max_ticks) { clearInterval(model.interval); model.running = false; document.getElementById("clutch-drive").textContent = "DRIVE LIMIT REACHED"; setMessage(model, "VISIBLE WIND LIMIT REACHED · BRAKE AND TRY THE SAFE OR START A FRESH TRIAL", "error"); } };
    const start = () => { if (model.running || model.tick >= state.physics.max_ticks) return; model.running = true; event(model, "drive", {tick: model.tick, running: true}); document.getElementById("clutch-drive").textContent = "DRIVE RUNNING"; model.interval = setInterval(tick, state.physics.tick_ms); };
    const stop = () => { if (!model.running) return; clearInterval(model.interval); model.running = false; event(model, "drive", {tick: model.tick, running: false, angles: model.shafts.map((shaft) => round(shaft.angle_deg))}); document.getElementById("clutch-drive").textContent = "START DRIVE"; draw(); };
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
      if (model.terminal || model.submitting) return;
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
    document.getElementById("clutch-drive").addEventListener("click", start); document.getElementById("clutch-brake").addEventListener("click", stop);
    document.querySelectorAll("[data-clutch]").forEach((button) => button.addEventListener("click", () => changeClutch(Number(button.dataset.clutch), "clutch_button")));
    document.querySelectorAll("[data-clutch-lever]").forEach((lever) => {
      const rail = lever.querySelector(".clutch-lever-rail"), handle = lever.querySelector(".clutch-lever-handle");
      lever.addEventListener("pointerdown", (pointerEvent) => {
        if (model.terminal || model.submitting || model.clutchDrag || pointerEvent.target !== handle || (!reengagementAllowed && lever.dataset.state === "free")) return;
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
    document.getElementById("clutch-unlock").addEventListener("click", async () => { stop(); const errors = model.shafts.map((shaft) => angleError(shaft.angle_deg, 0)), accepted = model.shafts.every((shaft, index) => !shaft.engaged && errors[index] <= state.physics.phase_tolerance_deg); event(model, "unlock", {tick: model.tick, angles: model.shafts.map((shaft) => round(shaft.angle_deg)), engaged: model.shafts.map((shaft) => shaft.engaged), accepted}); if (!accepted) { setMessage(model, `SAFE REFUSES · PHASE ERRORS ${errors.map((value) => value.toFixed(1)).join(" / ")}`, "error"); return; } await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "CLOCKWORK SAFE OPEN", `${state.shafts.length} ${state.shafts.length === 1 ? "SHAFT" : "SHAFTS"} · ACTIVE-SET LOAD REDISTRIBUTION · FINAL PHASE`); });
    document.getElementById("clutch-abandon").addEventListener("click", () => { stop(); submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", ""); }); draw();
  };

  function puppetPoints(lengths){const [lh,rh,lf,rf]=lengths;return{left_hand:[330-(lh-50)*2+(lf-50)*.35,220+(lh-50)*2.05],right_hand:[570+(rh-50)*2-(rf-50)*.35,220+(rh-50)*2.05],left_foot:[410-(lf-50)*1.25+(lh-50)*.28,365+(lf-50)*1.55],right_foot:[490+(rf-50)*1.25-(rh-50)*.28,365+(rf-50)*1.55]};}
  registry.marionette_checkpoint_v1 = async (state, helpers) => {
    document.body.dataset.mechanic="marionette-checkpoint";const model={state,helpers,events:[],poseIndex:0,lengths:[...state.initial_lengths],hold:0,tick:0,terminal:false,submitting:false};window.marionetteCheckpointModel=model;
    helpers.app.innerHTML=shell(state,"THEATRE BORDER INSPECTION","MARIONETTE CHECKPOINT","Pull four coupled strings until every hand and foot remains inside the moving inspection rings. Clear four poses.",`<canvas id="marionette-canvas" width="900" height="480"></canvas>`,`<h2>STRING RACK</h2><div class="marionette-rack">${["LEFT HAND","RIGHT HAND","LEFT FOOT","RIGHT FOOT"].map((label,index)=>`<label>${label}<input data-string="${index}" type="range" min="20" max="80" value="50"><span id="string-${index}">50</span></label>`).join("")}</div><div class="ivv-meter"><i id="marionette-meter"></i></div><button id="marionette-reset">CENTER ALL STRINGS</button><button id="marionette-abandon" class="ivv-danger">CUT STRINGS / FRESH STAGE</button>`);
    const current=()=>state.poses[model.poseIndex];const draw=()=>{const ctx=document.getElementById("marionette-canvas").getContext("2d"),points=puppetPoints(model.lengths),sway=4*Math.sin(model.tick*.14+current().frame_phase);ctx.fillStyle="#170c12";ctx.fillRect(0,0,900,480);ctx.fillStyle="#3a1521";for(let x=0;x<900;x+=80){ctx.fillRect(x,0,40,480);}Object.entries(current().target_points).forEach(([id,target])=>{ctx.strokeStyle="#d8ff64";ctx.lineWidth=4;ctx.beginPath();ctx.arc(target[0]+sway,target[1],17,0,Math.PI*2);ctx.stroke();ctx.fillStyle="#d8ff64";ctx.font="700 8px Courier New";ctx.fillText(id.replace("_"," ").toUpperCase(),target[0]-25+sway,target[1]-23);});const shoulderL=[390,150],shoulderR=[510,150],hip=[450,280];ctx.strokeStyle="#f2d7b5";ctx.lineWidth=8;ctx.lineCap="round";[[shoulderL,points.left_hand],[shoulderR,points.right_hand],[hip,points.left_foot],[hip,points.right_foot],[[390,150],[510,150]],[[450,150],hip]].forEach(([a,b])=>{ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();});Object.values(points).forEach(p=>{ctx.fillStyle="#f2b35d";ctx.beginPath();ctx.arc(p[0],p[1],9,0,Math.PI*2);ctx.fill();});ctx.strokeStyle="#8db7c4";ctx.lineWidth=1;[points.left_hand,points.right_hand,points.left_foot,points.right_foot].forEach((p,index)=>{const anchorX=290+index*105;ctx.beginPath();ctx.moveTo(anchorX,0);ctx.lineTo(p[0],p[1]);ctx.stroke();});ctx.fillStyle="#f5dfc5";ctx.font="800 11px Courier New";ctx.fillText(`INSPECTION ${model.poseIndex+1}/4 · HOLD ${model.hold}/${current().hold_ticks}`,18,24);};
    const inside=()=>{const points=puppetPoints(model.lengths),sway=4*Math.sin(model.tick*.14+current().frame_phase);return Object.entries(current().target_points).every(([id,target])=>Math.hypot(points[id][0]-(target[0]+sway),points[id][1]-target[1])<=14);};model.interval=setInterval(async()=>{model.tick+=1;if(inside())model.hold+=1;else model.hold=0;document.getElementById("marionette-meter").style.width=`${Math.min(100,model.hold/current().hold_ticks*100)}%`;draw();if(model.hold<current().hold_ticks)return;event(model,"pose_clear",{pose_id:current().id,tick:model.tick,lengths:[...model.lengths],hold_ticks:model.hold});model.hold=0;if(model.poseIndex<state.poses.length-1){model.poseIndex+=1;setMessage(model,"POSE ACCEPTED · INSPECTION FRAME ADVANCED","passed");}else{clearInterval(model.interval);await submit(model,{mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,events:model.events,completed:true},"MARIONETTE AUTHENTICATED","COUPLED KINEMATICS · FOUR SUSTAINED POSES");}},state.tick_ms);
    document.querySelectorAll("[data-string]").forEach(input=>input.addEventListener("input",()=>{const index=Number(input.dataset.string),before=model.lengths[index];model.lengths[index]=Number(input.value);model.hold=0;document.getElementById("marionette-meter").style.width="0%";event(model,"string",{pose_id:current().id,tick:model.tick,string:index,before,after:model.lengths[index],lengths:[...model.lengths]});document.getElementById(`string-${index}`).textContent=String(model.lengths[index]);draw();}));document.getElementById("marionette-reset").addEventListener("click",()=>{const before=[...model.lengths];model.lengths=[...state.initial_lengths];model.hold=0;document.getElementById("marionette-meter").style.width="0%";document.querySelectorAll("[data-string]").forEach((input,index)=>{input.value=String(model.lengths[index]);document.getElementById(`string-${index}`).textContent=String(model.lengths[index]);});event(model,"reset",{pose_id:current().id,tick:model.tick,before,after:[...model.lengths]});draw();});document.getElementById("marionette-abandon").addEventListener("click",()=>submit(model,{mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,events:[...model.events,{seq:model.events.length+1,type:"abandon"}],completed:false},"",""));draw();
  };

  const puppetTargetLengths = (pose, tick) => pose.base_lengths.map((base, index) => Number(base) + Number(pose.amplitudes[index]) * Math.sin(Number(tick) * Number(pose.angular_rate) + Number(pose.phases[index])));
  registry.marionette_checkpoint = async (state, helpers) => {
    document.body.dataset.mechanic = "marionette-checkpoint";
    const interaction = state.control_condition?.interaction || "simplified";
    const activeIndices = state.active_string_indices || [0, 1, 2, 3];
    const labels = ["LEFT HAND", "RIGHT HAND", "LEFT FOOT", "RIGHT FOOT"];
    const count = (amount, singular, plural = `${singular}s`) => `${amount} ${amount === 1 ? singular : plural}`;
    // Keep the uncontrolled three-act/four-limb wording byte-for-byte. Other
    // profiles expose fewer active strings or acts, so their visible contract
    // must describe the generated state rather than the historical baseline.
    const historicalContract = activeIndices.length === 4 && state.poses.length === 3;
    const instruction = historicalContract
      ? "Continuously track four moving inspection rings with coupled strings. Progress grows only while every limb is inside and leaks on misses."
      : `Continuously track ${count(activeIndices.length, "moving inspection ring")} with ${count(activeIndices.length, "active string")} through ${count(state.poses.length, "moving act")}. Progress grows only while ${activeIndices.length === 1 ? "the active limb is" : "every active limb is"} inside and leaks on misses.`;
    const completionNote = historicalContract
      ? "THREE MOVING ACTS · COUPLED STRINGS · LEAKING TRACK PROGRESS"
      : `${count(state.poses.length, "MOVING ACT").toUpperCase()} · ${count(activeIndices.length, "ACTIVE STRING").toUpperCase()} · LEAKING TRACK PROGRESS`;
    const model = {state, helpers, events: [], poseIndex: 0, lengths: [...state.initial_lengths], progress: 0, tick: 0, terminal: false, submitting: false, interval: null, stringDrag: null, interaction, activeIndices};
    window.marionetteCheckpointModel = model;
    helpers.app.innerHTML = shell(
      state, "THEATRE BORDER INSPECTION", "MARIONETTE CHECKPOINT",
      instruction,
      `<canvas id="marionette-canvas" width="900" height="480"></canvas>`,
      interaction === "simplified"
        ? `<h2>LIVE STRING RACK</h2><div class="marionette-rack">${activeIndices.map((index) => `<label>${labels[index]}<input data-string="${index}" type="range" min="20" max="80" step="1" value="50"><span id="string-${index}">50</span></label>`).join("")}</div><div class="ivv-meter"><i id="marionette-meter"></i></div><button id="marionette-reset">CENTER ALL STRINGS</button><button id="marionette-abandon" class="ivv-danger">CUT STRINGS / FRESH STAGE</button>`
        : `<h2>DIRECT STRING PULLS</h2><p>Drag the glowing handles at the top of each active string up or down. The handle position is the string length.</p><div class="ivv-meter"><i id="marionette-meter"></i></div><button id="marionette-reset">CENTER ALL STRINGS</button><button id="marionette-abandon" class="ivv-danger">CUT STRINGS / FRESH STAGE</button>`,
    );
    const current = () => state.poses[model.poseIndex];
    const targetPoints = () => puppetPoints(puppetTargetLengths(current(), model.tick));
    const inside = () => { const points = puppetPoints(model.lengths), targets = targetPoints(), allowance = Number(state.ring_radius) - 7, names = ["left_hand", "right_hand", "left_foot", "right_foot"]; return activeIndices.every((index) => Math.hypot(points[names[index]][0] - targets[names[index]][0], points[names[index]][1] - targets[names[index]][1]) <= allowance); };
    const draw = () => {
      const ctx = document.getElementById("marionette-canvas").getContext("2d"), points = puppetPoints(model.lengths), targets = targetPoints(); ctx.fillStyle = "#170c12"; ctx.fillRect(0, 0, 900, 480); ctx.fillStyle = "#3a1521"; for (let x = 0; x < 900; x += 80) ctx.fillRect(x, 0, 40, 480);
      const names = ["left_hand", "right_hand", "left_foot", "right_foot"]; activeIndices.forEach((index) => { const name = names[index], target = targets[name]; ctx.strokeStyle = "#d8ff64"; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(target[0], target[1], state.ring_radius, 0, Math.PI * 2); ctx.stroke(); ctx.fillStyle = "#d8ff64"; ctx.font = "700 8px Courier New"; ctx.fillText(name.replace("_", " ").toUpperCase(), target[0] - 25, target[1] - state.ring_radius - 7); });
      const shoulderL = [390, 150], shoulderR = [510, 150], hip = [450, 280]; ctx.strokeStyle = "#f2d7b5"; ctx.lineWidth = 8; ctx.lineCap = "round"; [[shoulderL, points.left_hand], [shoulderR, points.right_hand], [hip, points.left_foot], [hip, points.right_foot], [[390,150],[510,150]], [[450,150],hip]].forEach(([first, second]) => { ctx.beginPath(); ctx.moveTo(first[0], first[1]); ctx.lineTo(second[0], second[1]); ctx.stroke(); }); Object.values(points).forEach((point) => { ctx.fillStyle = "#f2b35d"; ctx.beginPath(); ctx.arc(point[0], point[1], 9, 0, Math.PI * 2); ctx.fill(); });
      ctx.strokeStyle = "#8db7c4"; ctx.lineWidth = 1; [points.left_hand, points.right_hand, points.left_foot, points.right_foot].forEach((point, index) => { const anchorX = 290 + index * 105; ctx.beginPath(); ctx.moveTo(anchorX, 0); ctx.lineTo(point[0], point[1]); ctx.stroke(); if (interaction === "full" && activeIndices.includes(index)) { const handleY = 22 + (model.lengths[index] - 20) * 1.8; ctx.fillStyle = "#d8ff64"; ctx.fillRect(anchorX - 22, handleY - 8, 44, 16); ctx.fillStyle = "#15201c"; ctx.font = "900 8px Courier New"; ctx.fillText("PULL", anchorX - 12, handleY + 3); } }); ctx.fillStyle = "#f5dfc5"; ctx.font = "800 11px Courier New"; ctx.fillText(`ACT ${model.poseIndex + 1}/${state.poses.length} · TRACK ${model.progress}/${current().tracking_ticks} · FRAME ${model.tick}`, 18, 24);
    };
    model.interval = setInterval(async () => {
      model.tick += 1; const accepted = inside(); model.progress = accepted ? model.progress + 1 : Math.max(0, model.progress - Number(current().miss_decay_ticks)); event(model, "track_sample", {pose_id: current().id, tick: model.tick, inside: accepted, progress_after: model.progress, lengths: [...model.lengths]}); document.getElementById("marionette-meter").style.width = `${Math.min(100, model.progress / current().tracking_ticks * 100)}%`; draw();
      if (model.progress < current().tracking_ticks) return;
      event(model, "act_clear", {pose_id: current().id, tick: model.tick, lengths: [...model.lengths], progress: model.progress}); model.progress = 0; model.tick = 0;
      if (model.poseIndex < state.poses.length - 1) { model.poseIndex += 1; document.getElementById("marionette-meter").style.width = "0%"; setMessage(model, "MOVING ACT ACCEPTED · NEXT INSPECTION CHOREOGRAPHY", "passed"); draw(); }
      else { clearInterval(model.interval); await submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true}, "MARIONETTE AUTHENTICATED", completionNote); }
    }, state.tick_ms);
    const setString = (index, value, inputSource) => { const before = model.lengths[index], after = Math.round(clamp(value, 20, 80)); if (after === before) return; model.lengths[index] = after; event(model, "string", {pose_id: current().id, tick: model.tick, string: index, before, after, lengths: [...model.lengths], input_source: inputSource}); const readout = document.getElementById(`string-${index}`); if (readout) readout.textContent = String(after); draw(); };
    document.querySelectorAll("[data-string]").forEach((input) => input.addEventListener("input", () => setString(Number(input.dataset.string), Number(input.value), "string_slider")));
    if (interaction === "full") { const canvas = document.getElementById("marionette-canvas"); const point = (pointerEvent) => { const box = canvas.getBoundingClientRect(); return {x: (pointerEvent.clientX - box.left) * 900 / box.width, y: (pointerEvent.clientY - box.top) * 480 / box.height}; }; const indexAt = (where) => activeIndices.find((index) => Math.abs(where.x - (290 + index * 105)) <= 28 && Math.abs(where.y - (22 + (model.lengths[index] - 20) * 1.8)) <= 20); canvas.addEventListener("pointerdown", (pointerEvent) => { const index = indexAt(point(pointerEvent)); if (index === undefined) return; model.stringDrag = {pointerId: pointerEvent.pointerId, index}; canvas.setPointerCapture(pointerEvent.pointerId); pointerEvent.preventDefault(); }); canvas.addEventListener("pointermove", (pointerEvent) => { if (!model.stringDrag || model.stringDrag.pointerId !== pointerEvent.pointerId) return; setString(model.stringDrag.index, 20 + (point(pointerEvent).y - 22) / 1.8, "string_drag"); pointerEvent.preventDefault(); }); const release = (pointerEvent) => { if (!model.stringDrag || model.stringDrag.pointerId !== pointerEvent.pointerId) return; model.stringDrag = null; try { canvas.releasePointerCapture(pointerEvent.pointerId); } catch (_error) {} }; canvas.addEventListener("pointerup", release); canvas.addEventListener("pointercancel", release); }
    document.getElementById("marionette-reset").addEventListener("click", () => { const before = [...model.lengths]; model.lengths = [...state.initial_lengths]; model.progress = 0; document.getElementById("marionette-meter").style.width = "0%"; document.querySelectorAll("[data-string]").forEach((input, index) => { input.value = String(model.lengths[index]); document.getElementById(`string-${index}`).textContent = String(model.lengths[index]); }); event(model, "reset", {pose_id: current().id, tick: model.tick, before, after: [...model.lengths], progress_after: 0}); draw(); });
    document.getElementById("marionette-abandon").addEventListener("click", () => submit(model, {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}, "", "")); draw();
  };

  const modelGlobals = [
    "specularLighthouseRelayModel", "windTunnelSeedCourierModel",
    "hologramSilhouetteFoundryModel", "orbitalDockingCustomsModel",
    "gravityRoomFreightModel", "floodgateArchiveRescueModel",
    "elasticMembraneSorterModel", "pheromoneDispatchModel",
    "clockworkClutchSafeModel", "marionetteCheckpointModel",
  ];
  const cleanup = () => modelGlobals.forEach((name) => {
    const previous = window[name];
    if (!previous) return;
    if (previous.keyHandler) document.removeEventListener("keydown", previous.keyHandler);
    ["interval", "timer", "animation"].forEach((field) => {
      if (previous[field]) clearInterval(previous[field]);
    });
    previous.terminal = true;
  });
  window.GymAnythingRTInteractionViiViii = {render: (mechanic, state, helpers) => { cleanup(); return registry[mechanic](state, helpers); }, registry, cleanup};
})();
