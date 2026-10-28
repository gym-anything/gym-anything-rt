(() => {
  "use strict";
  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const clamp = (value, low = -1, high = 1) => Math.max(low, Math.min(high, value));
  const round = (value, places = 3) => Math.round(Number(value) * 10 ** places) / 10 ** places;
  const channels = ["tail", "yaw", "pitch", "roll"];
  const labels = {tail: "TAIL BEAT", yaw: "YAW FIN", pitch: "PITCH FIN", roll: "ROLL FIN"};
  const keyMap = {
    KeyA: ["tail", -1], KeyD: ["tail", 1],
    KeyJ: ["yaw", -1], KeyL: ["yaw", 1],
    KeyI: ["pitch", 1], KeyK: ["pitch", -1],
    KeyQ: ["roll", -1], KeyE: ["roll", 1],
  };

  function current(tick, physics) {
    const anchor = (segment) => {
      let value = (Number(physics.current_seed) ^ Math.imul(segment, 0x9E3779B1)) >>> 0;
      value = Math.imul(value ^ (value >>> 16), 0x85EBCA6B) >>> 0;
      value = Math.imul(value ^ (value >>> 13), 0xC2B2AE35) >>> 0;
      return ((value ^ (value >>> 16)) >>> 0) / 4294967296;
    };
    const width = Number(physics.current_segment_ticks), segment = Math.floor(tick / width);
    const f = (tick % width) / width, blend = f ** 3 * (f * (6 * f - 15) + 10);
    const a = anchor(segment) * Math.PI * 2, b = anchor(segment + 1) * Math.PI * 2;
    const delta = ((b-a+Math.PI) % (Math.PI*2) + Math.PI*2) % (Math.PI*2) - Math.PI;
    const angle = a + delta * blend, gain = Number(physics.current_gain);
    return {x: Math.cos(angle) * gain, z: Math.sin(angle) * gain,
      roll: Number(physics.current_roll_gain) * (0.7 + 0.3 * Math.sin(angle))};
  }

  function step(fish, controls, physics, tick) {
    const dt = Number(physics.dt);
    const tail = clamp(Number(controls.tail));
    const yaw = clamp(Number(controls.yaw));
    const pitch = clamp(Number(controls.pitch));
    const roll = clamp(Number(controls.roll));
    fish.tail_phase += dt * (3.2 + 0.8 * Math.abs(tail));
    fish.fin_phase += dt * (2.0 + 0.35 * (Math.abs(pitch) + Math.abs(roll)));
    fish.yaw_rate = fish.yaw_rate * Number(physics.angular_damping) + yaw * Number(physics.torque_gain);
    fish.pitch_rate = fish.pitch_rate * Number(physics.angular_damping) + pitch * Number(physics.torque_gain);
    const flow = current(tick, physics);
    fish.roll_rate = fish.roll_rate * Number(physics.angular_damping) + roll * Number(physics.torque_gain) + flow.roll;
    fish.yaw += fish.yaw_rate;
    fish.pitch = clamp(fish.pitch + fish.pitch_rate, -1.2, 1.2);
    fish.roll = clamp(fish.roll + fish.roll_rate, -1.2, 1.2);
    const forward = {
      x: Math.cos(fish.pitch) * Math.cos(fish.yaw),
      y: Math.sin(fish.pitch),
      z: Math.cos(fish.pitch) * Math.sin(fish.yaw),
    };
    const stroke = tail * (0.56 + 0.44 * Math.sin(fish.tail_phase));
    const thrust = Number(physics.thrust_gain) * 0.1 * stroke;
    const lift = Number(physics.thrust_gain) * 0.018 * Math.sin(fish.fin_phase);
    fish.vx = fish.vx * Number(physics.linear_damping) + forward.x * thrust + flow.x;
    fish.vy = fish.vy * Number(physics.linear_damping) + forward.y * thrust + pitch * lift;
    fish.vz = fish.vz * Number(physics.linear_damping) + forward.z * thrust + roll * lift + flow.z;
    fish.x += fish.vx;
    fish.y += fish.vy;
    fish.z += fish.vz;
  }

  function distance(fish, target) {
    return Math.hypot(fish.x - target.x, fish.y - target.y, fish.z - target.z);
  }

  function arrival(fish, target, physics) {
    return distance(fish, target) <= Number(physics.arrival_radius)
      && Math.hypot(fish.vx, fish.vy, fish.vz) <= Number(physics.speed_limit)
      && Math.abs(fish.pitch) <= Number(physics.upright_tolerance)
      && Math.abs(fish.roll) <= Number(physics.upright_tolerance);
  }

  function project(point, camera, width, height) {
    let x = Number(point.x) - camera.focus.x;
    let y = Number(point.y) - camera.focus.y;
    let z = Number(point.z) - camera.focus.z;
    const cy = Math.cos(camera.yaw), sy = Math.sin(camera.yaw);
    const rotatedX = cy * x + sy * z;
    const rotatedZ = -sy * x + cy * z;
    const cp = Math.cos(camera.pitch), sp = Math.sin(camera.pitch);
    const vertical = cp * y - sp * rotatedZ;
    const depth = sp * y + cp * rotatedZ + 3.8;
    const scale = 230 / Math.max(1.0, depth);
    return {x: width * 0.5 + rotatedX * scale, y: height * 0.56 - vertical * scale, depth, scale};
  }

  function fishBasis(fish) {
    const forward = {x: Math.cos(fish.pitch) * Math.cos(fish.yaw), y: Math.sin(fish.pitch), z: Math.cos(fish.pitch) * Math.sin(fish.yaw)};
    const right = {x: -Math.sin(fish.yaw), y: 0, z: Math.cos(fish.yaw)};
    const up = {x: -Math.sin(fish.pitch) * Math.cos(fish.yaw), y: Math.cos(fish.pitch), z: -Math.sin(fish.pitch) * Math.sin(fish.yaw)};
    const cosine = Math.cos(fish.roll), sine = Math.sin(fish.roll);
    const bankedRight = {}, bankedUp = {};
    for (const axis of ["x", "y", "z"]) {
      bankedRight[axis] = right[axis] * cosine - up[axis] * sine;
      bankedUp[axis] = up[axis] * cosine + right[axis] * sine;
    }
    return {forward, right: bankedRight, up: bankedUp};
  }

  function renderFish(ctx, fish, camera, width, height) {
    const basis = fishBasis(fish);
    const add = (scale, direction = basis.forward) => ({x: fish.x + direction.x * scale, y: fish.y + direction.y * scale, z: fish.z + direction.z * scale});
    const nose = project(add(0.23), camera, width, height);
    const tail = project(add(-0.24), camera, width, height);
    const body = project({x: fish.x, y: fish.y, z: fish.z}, camera, width, height);
    const finLeft = project({x: fish.x + basis.right.x * 0.22, y: fish.y + basis.right.y * 0.22, z: fish.z + basis.right.z * 0.22}, camera, width, height);
    const finRight = project({x: fish.x - basis.right.x * 0.22, y: fish.y - basis.right.y * 0.22, z: fish.z - basis.right.z * 0.22}, camera, width, height);
    ctx.save();
    ctx.shadowBlur = 25;
    ctx.shadowColor = "#7cf7e8";
    const gradient = ctx.createLinearGradient(tail.x, tail.y, nose.x, nose.y);
    gradient.addColorStop(0, "#4c78cf");
    gradient.addColorStop(0.52, "#42ddd0");
    gradient.addColorStop(1, "#fff1a8");
    ctx.strokeStyle = gradient;
    ctx.lineWidth = Math.max(18, body.scale * 0.085);
    ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(tail.x, tail.y); ctx.lineTo(nose.x, nose.y); ctx.stroke();
    ctx.shadowBlur = 10;
    ctx.strokeStyle = "#bbfff2";
    ctx.lineWidth = Math.max(6, body.scale * 0.035);
    ctx.beginPath(); ctx.moveTo(finLeft.x, finLeft.y); ctx.lineTo(body.x, body.y); ctx.lineTo(finRight.x, finRight.y); ctx.stroke();
    const dorsal = project(add(.25, basis.up), camera, width, height);
    const back = project(add(-.1), camera, width, height);
    ctx.fillStyle = "#72b9e9";
    ctx.beginPath(); ctx.moveTo(back.x, back.y); ctx.lineTo(dorsal.x, dorsal.y); ctx.lineTo(nose.x, nose.y); ctx.closePath(); ctx.fill();
    ctx.strokeStyle = "#d6e7ff";
    ctx.lineWidth = Math.max(4, body.scale * 0.022);
    const tailBase = add(-.42);
    const sway = .10 * Math.sin(fish.tail_phase);
    const tailTip = project({x: tailBase.x + basis.right.x * sway, y: tailBase.y + basis.right.y * sway, z: tailBase.z + basis.right.z * sway}, camera, width, height);
    ctx.beginPath(); ctx.moveTo(tail.x, tail.y); ctx.lineTo(tailTip.x, tailTip.y); ctx.stroke();
    ctx.fillStyle = "#fff6c5"; ctx.beginPath(); ctx.arc(nose.x, nose.y, Math.max(4, body.scale * 0.027), 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }

  function shell(state, body, controls) {
    const condition = state.control_condition || {};
    const interaction = condition.interaction || "full";
    return `<section class="lanternfin" data-interaction="${esc(interaction)}" data-challenge-id="${esc(state.challenge_id)}">
      <header class="lanternfin-head"><div><span>ABYSSAL NAVIGATION AUTHORITY</span><h1>LANTERNFIN DIVE V2</h1></div><p>${esc(state.prompt)}</p></header>
      <main class="lanternfin-main">${body}<aside class="lanternfin-console">${controls}</aside></main>
      <footer class="lanternfin-foot"><span>${esc(state.challenge_id.toUpperCase())} · ${esc(interaction.toUpperCase())} INPUT SURFACE</span><div id="lanternfin-readout" class="readout" data-status="idle">OBSERVE THE WATER</div></footer>
    </section>`;
  }

  function controlMarkup(interaction) {
    if (interaction === "simplified") {
      return `<h2>JOINT TORQUES</h2><p class="lf-help">Each detent persists until you reverse or neutralize it. Watch the next frame before choosing the next stroke.</p><div class="lf-buttons">${channels.map((channel) => `<div class="lf-row"><b>${labels[channel]}</b><button data-channel="${channel}" data-value="-1">−</button><button data-channel="${channel}" data-value="0">NEUTRAL</button><button data-channel="${channel}" data-value="1">+</button></div>`).join("")}</div><p class="lf-help">The canvas is also an orbit camera: drag it to inspect the pearl's depth.</p>`;
    }
    return `<h2>HELD TORQUE KEYS</h2><p class="lf-help">Hold a key pair and release to neutral. A, D tail · J, L yaw · K, I pitch · Q, E roll.</p><div class="lf-keybank">${[["A / D", "TAIL BEAT"], ["J / L", "YAW FIN"], ["K / I", "PITCH FIN"], ["Q / E", "ROLL FIN"]].map((item) => `<div><kbd>${item[0]}</kbd><span>${item[1]}</span></div>`).join("")}</div><p class="lf-help">Drag the aquarium view to inspect the fish against the far wall and pearl.</p>`;
  }

  function render(state, helpers) {
    if (window.lanternfinDiveV2Model?.cleanup) window.lanternfinDiveV2Model.cleanup();
    document.body.dataset.mechanic = "lanternfin-dive-v2";
    const condition = state.control_condition || {};
    const interaction = condition.interaction || "full";
    const model = {
      state, helpers, interaction, fish: copy(state.initial), controls: {tail: 0, yaw: 0, pitch: 0, roll: 0},
      events: [], tick: 0, hold: 0, terminal: false, submitting: false, timer: null,
      camera: {yaw: -0.48, pitch: 0.22, focus: {x: 0, y: 0, z: 0}}, drag: null, keys: new Map(),
    };
    window.lanternfinDiveV2Model = model;
    const buttons = controlMarkup(interaction);
    helpers.app.innerHTML = shell(state, `<div class="lanternfin-tank"><canvas id="lanternfin-canvas" width="760" height="520" aria-label="3D aquarium showing the lanternfin fish and destination pearl"></canvas><div class="lanternfin-legend"><i></i>PEARL · <b>amber</b> = depth cue · <b>cyan</b> = body orientation</div></div>`, buttons + `<div class="lf-telemetry"><div><span>POSITION</span><b id="lf-pos">0.00 / 0.00 / 0.00</b></div><div><span>ATTITUDE</span><b id="lf-att">ROLL 0° · PITCH 0°</b></div><div><span>PEARL RANGE</span><b id="lf-range">—</b></div><div><span>UPRIGHT HOLD</span><b id="lf-hold">0 / ${Number(state.physics.hold_ticks)}</b></div></div><button id="lf-certify" class="lf-primary">CERTIFY PEARL ARRIVAL</button><button id="lf-abandon" class="lf-danger">ABANDON / FRESH DIVE</button>`);
    const canvas = document.getElementById("lanternfin-canvas");
    const readout = document.getElementById("lanternfin-readout");
    const setMessage = (message, status = "idle") => { if (model.terminal && message !== "PASS") return; readout.textContent = message; readout.dataset.status = status; };
    const event = (type, details = {}) => { model.events.push({seq: model.events.length + 1, type, ...details}); };
    const stateSnapshot = () => copy(model.fish);
    const draw = () => {
      const ctx = canvas.getContext("2d");
      const width = canvas.width, height = canvas.height;
      ctx.clearRect(0, 0, width, height);
      const background = ctx.createLinearGradient(0, 0, width, height);
      background.addColorStop(0, state.palette === "amberglass" ? "#081c2c" : "#061d2b");
      background.addColorStop(1, "#122b3c"); ctx.fillStyle = background; ctx.fillRect(0, 0, width, height);
      ctx.strokeStyle = "rgba(96,205,217,.19)"; ctx.lineWidth = 1;
      for (let i = -2; i <= 2; i += 0.5) { const a = project({x: i, y: -0.78, z: -1.6}, model.camera, width, height); const b = project({x: i, y: -0.78, z: 1.8}, model.camera, width, height); ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
      for (let z = -1.6; z <= 1.8; z += 0.5) { const a = project({x: -2.0, y: -0.78, z}, model.camera, width, height); const b = project({x: 2.0, y: -0.78, z}, model.camera, width, height); ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
      const targetPoint = project(state.target, model.camera, width, height);
      ctx.save(); ctx.shadowBlur = 24; ctx.shadowColor = "#ffcc66"; ctx.strokeStyle = "#ffd477"; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(targetPoint.x, targetPoint.y, Math.max(11, targetPoint.scale * state.target.radius), 0, Math.PI * 2); ctx.stroke(); ctx.fillStyle = "rgba(255,190,82,.2)"; ctx.fill(); ctx.restore();
      const targetLabel = project({x: state.target.x, y: state.target.y + 0.16, z: state.target.z}, model.camera, width, height); ctx.fillStyle = "#ffe7a3"; ctx.font = "700 12px ui-monospace, monospace"; ctx.fillText("DESTINATION PEARL", targetLabel.x - 54, targetLabel.y);
      renderFish(ctx, model.fish, model.camera, width, height);
      const flow = current(model.tick, state.physics);
      const origin = project({x: model.fish.x, y: model.fish.y - .25, z: model.fish.z}, model.camera, width, height);
      const tip = project({x: model.fish.x + flow.x / state.physics.current_gain * .6, y: model.fish.y - .25, z: model.fish.z + flow.z / state.physics.current_gain * .6}, model.camera, width, height);
      const direction = Math.atan2(tip.y-origin.y, tip.x-origin.x);
      ctx.strokeStyle = "#9fc5ff"; ctx.fillStyle = "#9fc5ff"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(origin.x, origin.y); ctx.lineTo(tip.x, tip.y); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(tip.x, tip.y); ctx.lineTo(tip.x-8*Math.cos(direction-.5), tip.y-8*Math.sin(direction-.5)); ctx.lineTo(tip.x-8*Math.cos(direction+.5), tip.y-8*Math.sin(direction+.5)); ctx.closePath(); ctx.fill();
      ctx.font = "700 11px ui-monospace, monospace"; ctx.fillText("WATER CURRENT · ROLLING RIGHT", 18, 45);
      ctx.fillStyle = "rgba(198,246,243,.75)"; ctx.font = "700 12px ui-monospace, monospace"; ctx.fillText(`TANK TIME ${model.tick} · VIEW ${Math.round(model.camera.yaw * 57.3)}°`, 18, 24);
      document.getElementById("lf-pos").textContent = `${model.fish.x.toFixed(2)} / ${model.fish.y.toFixed(2)} / ${model.fish.z.toFixed(2)}`;
      document.getElementById("lf-att").textContent = `ROLL ${(model.fish.roll * 57.3).toFixed(0)}° · PITCH ${(model.fish.pitch * 57.3).toFixed(0)}°`;
      document.getElementById("lf-range").textContent = `${distance(model.fish, state.target).toFixed(3)} m`;
      document.getElementById("lf-hold").textContent = `${model.hold} / ${Number(state.physics.hold_ticks)}`;
      channels.forEach((channel) => document.querySelector(`[data-value-for="${channel}"]`)?.replaceChildren(document.createTextNode(model.controls[channel] === 0 ? "NEUTRAL" : model.controls[channel] > 0 ? "+1" : "−1")));
    };
    const setTorque = (channel, value, inputSource) => {
      if (model.terminal || model.submitting || !channels.includes(channel)) return;
      value = Number(value);
      if (![-1, 0, 1].includes(value)) return;
      if (model.controls[channel] === value) { draw(); return; }
      event("torque", {tick: model.tick, channel, value, before: {[channel]: model.controls[channel]}, after: value, input_source: inputSource});
      model.controls[channel] = value;
      setMessage(`${labels[channel]} ${value === 0 ? "NEUTRAL" : value > 0 ? "+1" : "−1"}`, "active"); draw();
    };
    const tick = () => {
      if (model.terminal || model.submitting) return;
      step(model.fish, model.controls, state.physics, model.tick); model.tick += 1;
      model.hold = arrival(model.fish, state.target, state.physics) ? model.hold + 1 : 0;
      if (model.hold > 0) setMessage(`PEARL WINDOW · UPRIGHT ${model.hold}/${Number(state.physics.hold_ticks)}`, "passed");
      draw();
    };
    const submit = async (payload) => {
      if (model.submitting || model.terminal) return;
      model.submitting = true; setMessage("INDEPENDENT 3D REPLAY IN PROGRESS…", "pending");
      try {
        const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(payload)});
        const result = await response.json();
        if (result.passed === true) {
          model.terminal = true; setMessage("PASS", "passed");
          helpers.app.querySelector(".lanternfin")?.insertAdjacentHTML("beforeend", `<div class="lf-verdict is-pass"><strong>PEARL ARRIVAL ACCEPTED</strong><span>3D FLUID REPLAY · UPRIGHT HOLD · ORDINARY INPUT TRANSCRIPT</span></div>`);
        } else if (result.passed === false && result.state) {
          await helpers.render(result.state);
          helpers.app.querySelector(".lanternfin")?.insertAdjacentHTML("beforeend", `<div class="lf-verdict is-fresh"><strong>FAIL · FRESH DIVE</strong><span>${esc(result.feedback || "The failed dive was replaced")}</span></div>`);
          const notice = helpers.app.querySelector(".lf-verdict.is-fresh");
          setTimeout(() => notice?.remove(), 1800);
        } else { model.submitting = false; setMessage(`FAIL · ${result.feedback || result.error || "NO AUTHORITATIVE GRADE"}`, "error"); }
      } catch (error) { model.submitting = false; setMessage(`FAIL · VERIFIER OFFLINE · ${error.message}`, "error"); }
    };
    if (interaction === "simplified") {
      document.querySelectorAll("[data-channel]").forEach((button) => button.addEventListener("click", () => setTorque(button.dataset.channel, Number(button.dataset.value), Number(button.dataset.value) === 0 ? "torque_neutral_button" : "torque_button")));
    } else {
      model.keyHandler = (keyboardEvent) => {
        const mapped = keyMap[keyboardEvent.code]; if (!mapped || keyboardEvent.repeat || model.terminal || model.submitting) return;
        keyboardEvent.preventDefault(); model.keys.set(keyboardEvent.code, true); setTorque(mapped[0], mapped[1], "torque_keyboard");
      };
      model.keyUpHandler = (keyboardEvent) => {
        const mapped = keyMap[keyboardEvent.code]; if (!mapped || !model.keys.has(keyboardEvent.code)) return;
        keyboardEvent.preventDefault(); model.keys.delete(keyboardEvent.code); setTorque(mapped[0], 0, "torque_neutral_keyboard");
      };
      document.addEventListener("keydown", model.keyHandler); document.addEventListener("keyup", model.keyUpHandler);
    }
    canvas.addEventListener("pointerdown", (pointerEvent) => { if (model.terminal || model.submitting) return; model.drag = {id: pointerEvent.pointerId, x: pointerEvent.clientX, y: pointerEvent.clientY}; canvas.setPointerCapture(pointerEvent.pointerId); });
    canvas.addEventListener("pointermove", (pointerEvent) => { if (!model.drag || model.drag.id !== pointerEvent.pointerId) return; const dx = pointerEvent.clientX - model.drag.x, dy = pointerEvent.clientY - model.drag.y; model.drag.x = pointerEvent.clientX; model.drag.y = pointerEvent.clientY; model.camera.yaw += dx * 0.008; model.camera.pitch = clamp(model.camera.pitch + dy * 0.006, -0.55, 0.65); draw(); });
    canvas.addEventListener("pointerup", (pointerEvent) => { if (!model.drag || model.drag.id !== pointerEvent.pointerId) return; model.drag = null; if (canvas.hasPointerCapture(pointerEvent.pointerId)) canvas.releasePointerCapture(pointerEvent.pointerId); });
    document.getElementById("lf-certify").addEventListener("click", () => {
      const accepted = model.hold >= Number(state.physics.hold_ticks) && arrival(model.fish, state.target, state.physics);
      event("certify", {tick: model.tick, state: stateSnapshot(), hold_ticks: model.hold, accepted, input_source: "certify_button"});
      if (!accepted) { void submit({mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: false}); return; }
      void submit({mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: model.events, completed: true});
    });
    document.getElementById("lf-abandon").addEventListener("click", () => void submit({mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id, events: [...model.events, {seq: model.events.length + 1, type: "abandon"}], completed: false}));
    model.timer = setInterval(tick, Number(state.physics.tick_ms));
    model.cleanup = () => { if (model.timer) clearInterval(model.timer); if (model.keyHandler) document.removeEventListener("keydown", model.keyHandler); if (model.keyUpHandler) document.removeEventListener("keyup", model.keyUpHandler); model.terminal = true; };
    draw();
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.lanternfin_dive_v2 = {rootSelector: ".lanternfin", render};
})();
