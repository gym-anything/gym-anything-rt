(() => {
  "use strict";

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  const MECHANIC_ID = "cloudpost_circuit_nonrealtime";
  const model = {
    state: null,
    helpers: null,
    interaction: "full",
    control: [0, 0],
    cursor: [460, 270],
    plane: null,
    tick: 0,
    events: [],
    collected: [],
    terminal: false,
    submitting: false,
    destroyed: false,
    cleanup: [],
  };

  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const esc = (value) => String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

  function record(type, details = {}) {
    const event = {seq: model.events.length + 1, type, ...details};
    model.events.push(event);
    return event;
  }

  function interactionCondition() {
    return model.state?.control_condition?.interaction || "full";
  }

  function planeSnapshot() {
    return Object.fromEntries(["x", "y", "z", "yaw", "pitch"].map((key) => [key, Number(model.plane[key].toFixed(4))]));
  }

  function setReadout(text, status = "idle") {
    model.helpers?.setReadout(text, status);
    const node = document.querySelector(".cloudpost-readout");
    if (node) {
      node.textContent = text;
      node.dataset.status = status;
    }
  }

  function palette() {
    return [
      ["#101c33", "#24375c", "#f6c85f", "#72dfcf"],
      ["#1b1839", "#3e366e", "#ff9d8f", "#a7f06c"],
      ["#0c2834", "#2d5e68", "#ffd17d", "#f183b5"],
      ["#241536", "#5b3d70", "#7ce4ff", "#ffe39a"],
      ["#132c2b", "#35685d", "#ffb26b", "#c6f27d"],
      ["#202336", "#515a78", "#e7a8ff", "#7ff4df"],
    ][Number(model.state?.palette || 0) % 6];
  }

  function cameraBasis() {
    const yaw = model.plane.yaw;
    const pitch = model.plane.pitch;
    const cp = Math.cos(pitch);
    const f = [Math.sin(yaw) * cp, Math.sin(pitch), Math.cos(yaw) * cp];
    const r = [Math.cos(yaw), 0, -Math.sin(yaw)];
    const u = [-Math.sin(yaw) * Math.sin(pitch), Math.cos(pitch), -Math.cos(yaw) * Math.sin(pitch)];
    return {f, r, u};
  }

  function project(point) {
    const basis = cameraBasis();
    const v = [point.x - model.plane.x, point.y - model.plane.y, point.z - model.plane.z];
    const depth = v[0] * basis.f[0] + v[1] * basis.f[1] + v[2] * basis.f[2];
    if (depth <= 2) return null;
    const sx = v[0] * basis.r[0] + v[1] * basis.r[1] + v[2] * basis.r[2];
    const sy = v[0] * basis.u[0] + v[1] * basis.u[1] + v[2] * basis.u[2];
    const focal = 500;
    return {
      x: 460 + sx / depth * focal,
      y: 270 - sy / depth * focal,
      depth,
    };
  }

  function trimControl(yawDelta, pitchDelta, label) {
    if (model.terminal || model.interaction !== "simplified") return;
    model.control[0] = clamp(model.control[0] + yawDelta, -1, 1);
    model.control[1] = clamp(model.control[1] + pitchDelta, -1, 1);
    record("steer", {tick: model.tick, yaw: Number(model.control[0].toFixed(4)), pitch: Number(model.control[1].toFixed(4)), input_source: "trim_button"});
    setReadout(`${label} · KEEP WATCHING THE FLIGHT FIELD`, "pending");
    advanceAfterAction();
  }

  function pointerControl(event) {
    if (model.terminal || model.interaction !== "full") return;
    const canvas = event.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const x = clamp(event.clientX - rect.left, 0, rect.width);
    const y = clamp(event.clientY - rect.top, 0, rect.height);
    model.cursor = [x / rect.width * 920, y / rect.height * 540];
    const yaw = clamp((x / rect.width * 2 - 1), -1, 1);
    const pitch = clamp((0.5 - y / rect.height) * 2, -1, 1);
    if (Math.abs(yaw - model.control[0]) < 0.004 && Math.abs(pitch - model.control[1]) < 0.004) return;
    model.control = [yaw, pitch];
    // Keep the replay control at pointer precision.  The canvas still shows
    // the same visible vector, while the independent grader can reproduce
    // the browser's world-space trajectory without accumulating four-decimal
    // rounding error across a long route.
    record("steer", {tick: model.tick, yaw: Number(yaw), pitch: Number(pitch), input_source: "pointer_steer"});
    setReadout("POINTER VECTOR SET · CORRECT FROM THE NEXT FRAME", "pending");
    advanceAfterAction();
  }

  function updateCounters() {
    const count = document.querySelector(".cloudpost-count");
    if (count) count.textContent = `${model.collected.length} / ${model.state.targets.length} SEALED`;
    const tick = document.querySelector(".cloudpost-tick");
    if (tick) tick.textContent = `FLIGHT ${String(model.tick).padStart(3, "0")} · WORLD CORRIDOR`;
  }

  function distance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
  }

  function step() {
    if (model.terminal || model.destroyed) return;
    model.tick += 1;
    const physics = model.state.physics;
    const desiredYaw = clamp(model.control[0], -1, 1) * Number(physics.max_yaw);
    const desiredPitch = clamp(model.control[1], -1, 1) * Number(physics.max_pitch);
    const turnStep = Number(physics.turn_step);
    model.plane.yaw += clamp(desiredYaw - model.plane.yaw, -turnStep, turnStep);
    model.plane.pitch += clamp(desiredPitch - model.plane.pitch, -turnStep, turnStep);
    const cp = Math.cos(model.plane.pitch);
    model.plane.x += Math.sin(model.plane.yaw) * cp * Number(physics.flight_speed);
    model.plane.y += Math.sin(model.plane.pitch) * Number(physics.flight_speed);
    model.plane.z += Math.cos(model.plane.yaw) * cp * Number(physics.flight_speed);
    const contacts = [];
    for (const target of model.state.targets) {
      if (model.collected.includes(target.id)) continue;
      const d = distance(model.plane, target);
      if (d <= Number(physics.contact_radius)) {
        model.collected.push(target.id);
        const contact = {tick: model.tick, target_id: target.id, distance: Number(d.toFixed(4)), plane: planeSnapshot()};
        record("contact", contact);
        contacts.push(contact);
      }
    }
    updateCounters();
    if (model.collected.length === model.state.targets.length) {
      finish(true, "ALL DELIVERY SEALS CONTACTED IN WORLD SPACE");
      return;
    }
    if (Math.abs(model.plane.x) > Number(physics.world_x) || Math.abs(model.plane.y) > Number(physics.world_y) || model.plane.z > Number(physics.world_z)) {
      finish(false, contacts.length ? "FLIGHT CORRIDOR LOST" : "THE FLIGHT LOG LEFT THE CORRIDOR");
    }
  }

  // The donor's frame loop advances flight continuously.  This counterpart
  // advances only after an existing visible control is used, so idle wall
  // time cannot move the plane, contact a seal, or trigger corridor failure.
  function advanceAfterAction() {
    if (model.terminal || model.destroyed) return;
    const actionTicks = Number(model.state.physics.action_ticks);
    for (let index = 0; index < actionTicks && !model.terminal; index += 1) step();
    if (!model.terminal) drawScene();
  }

  function drawSeal(ctx, target, point, colors) {
    // Three projected great circles show the same world-space sphere used by
    // contact detection. The central stamp remains an identifying marker.
    ctx.save(); ctx.strokeStyle=colors[3]; ctx.lineWidth=1; ctx.globalAlpha=.55;
    for(let axis=0;axis<3;axis+=1) {
      ctx.beginPath(); let drawing=false;
      for(let i=0;i<=48;i+=1) {
        const theta=i*Math.PI/24, offset=[0,0,0];
        offset[(axis+1)%3]=Number(target.radius)*Math.cos(theta);
        offset[(axis+2)%3]=Number(target.radius)*Math.sin(theta);
        const p=project({x:target.x+offset[0],y:target.y+offset[1],z:target.z+offset[2]});
        if(!p) {drawing=false;continue;}
        if(drawing) ctx.lineTo(p.x,p.y); else ctx.moveTo(p.x,p.y);
        drawing=true;
      }
      ctx.stroke();
    }
    ctx.restore();
    const scale = clamp(38 / point.depth, 0.42, 2.2);
    const radius = Number(target.radius) * scale;
    ctx.save();
    ctx.translate(point.x, point.y);
    ctx.globalAlpha = 0.18;
    ctx.fillStyle = colors[3];
    ctx.beginPath(); ctx.arc(0, 0, radius * 2.6, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 0.9;
    ctx.strokeStyle = colors[2];
    ctx.lineWidth = Math.max(1.5, radius * 0.12);
    ctx.beginPath();
    for (let index = 0; index < 6; index += 1) {
      const angle = index * Math.PI / 3 - Math.PI / 6;
      const x = Math.cos(angle) * radius;
      const y = Math.sin(angle) * radius;
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath(); ctx.stroke();
    ctx.fillStyle = colors[2]; ctx.globalAlpha = 0.78;
    ctx.font = `${Math.max(10, radius * 0.9)}px Georgia`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(target.symbol, 0, 1);
    ctx.restore();
  }

  function drawScene() {
    const canvas = document.querySelector(".cloudpost-canvas");
    if (!canvas || !model.state || !model.plane) return;
    const ctx = canvas.getContext("2d");
    const colors = palette();
    const gradient = ctx.createLinearGradient(0, 0, 0, 540);
    gradient.addColorStop(0, colors[0]); gradient.addColorStop(0.68, colors[1]); gradient.addColorStop(1, "#07101f");
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, 920, 540);
    ctx.fillStyle = "rgba(255,239,189,.78)";
    for (let index = 0; index < 46; index += 1) {
      const x = (index * 191 + Number(model.state.palette) * 67) % 920;
      const y = (index * 73 + Number(model.state.palette) * 31) % 285;
      const radius = 0.6 + (index % 3) * 0.55;
      ctx.globalAlpha = 0.18 + (index % 5) * 0.08; ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = "rgba(7,15,30,.58)";
    ctx.beginPath(); ctx.moveTo(0, 356); ctx.quadraticCurveTo(210, 321, 420, 360); ctx.quadraticCurveTo(670, 402, 920, 345); ctx.lineTo(920, 540); ctx.lineTo(0, 540); ctx.fill();
    const objects = (model.state.scenery || []).map((item) => ({item, point: project(item)})).filter((item) => item.point).sort((a, b) => b.point.depth - a.point.depth);
    for (const {item, point} of objects) {
      if (point.x < -160 || point.x > 1080 || point.y < -100 || point.y > 650) continue;
      const size = clamp(160 / point.depth, 0.5, 5) * Number(item.scale);
      ctx.save(); ctx.translate(point.x, point.y);
      ctx.globalAlpha = clamp(1.1 - point.depth / 900, 0.2, 0.86);
      if (item.kind === "spire") {
        ctx.fillStyle = ["#6b7596", "#738ca5", "#536780"][Number(item.tint) % 3];
        ctx.beginPath(); ctx.moveTo(-size * 2, size); ctx.lineTo(0, -size * 3.2); ctx.lineTo(size * 2, size); ctx.closePath(); ctx.fill();
      } else if (item.kind === "island") {
        ctx.fillStyle = ["#49706c", "#5c7b6d", "#6e7a67"][Number(item.tint) % 3];
        ctx.beginPath(); ctx.ellipse(0, 0, size * 3.6, size * 1.05, -0.16, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = "#b1c48e"; ctx.beginPath(); ctx.ellipse(-size * .4, -size * .45, size * 2.1, size * .5, -0.14, 0, Math.PI * 2); ctx.fill();
      } else if (item.kind === "balloon") {
        ctx.fillStyle = ["#d48482", "#c493d1", "#dfb36d"][Number(item.tint) % 3];
        ctx.beginPath(); ctx.arc(0, 0, size * 1.35, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "rgba(242,222,183,.55)"; ctx.beginPath(); ctx.moveTo(0, size * 1.2); ctx.lineTo(0, size * 3.4); ctx.stroke();
      } else {
        ctx.fillStyle = "rgba(228,240,225,.52)";
        ctx.beginPath(); ctx.ellipse(-size, 0, size * 2.2, size * .7, 0, 0, Math.PI * 2); ctx.ellipse(size * .8, -size * .3, size * 1.7, size * .64, 0, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();
    }
    const targetObjects = model.state.targets.map((target) => ({target, point: project(target)})).filter(({target}) => !model.collected.includes(target.id));
    for (const {target, point} of targetObjects) {
      if (point && point.x > -80 && point.x < 1000 && point.y > -70 && point.y < 610) drawSeal(ctx, target, point, colors);
    }
    // The plane is a fixed cockpit marker over the world camera; collection is
    // still computed from the plane's 3D pose and not from this drawing.
    ctx.save(); ctx.translate(460, 445); ctx.globalAlpha = 0.96;
    ctx.fillStyle = "#e8e0c1"; ctx.strokeStyle = "#2a3550"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(0, -24); ctx.lineTo(12, 18); ctx.lineTo(0, 11); ctx.lineTo(-12, 18); ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.fillStyle = colors[2]; ctx.beginPath(); ctx.moveTo(-35, 7); ctx.lineTo(-4, 4); ctx.lineTo(-2, 14); ctx.lineTo(-30, 19); ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(35, 7); ctx.lineTo(4, 4); ctx.lineTo(2, 14); ctx.lineTo(30, 19); ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.restore();
    if (model.interaction === "full") {
      ctx.save(); ctx.strokeStyle = "rgba(255,238,186,.55)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(model.cursor[0], model.cursor[1], 12, 0, Math.PI * 2); ctx.moveTo(model.cursor[0] - 18, model.cursor[1]); ctx.lineTo(model.cursor[0] + 18, model.cursor[1]); ctx.moveTo(model.cursor[0], model.cursor[1] - 18); ctx.lineTo(model.cursor[0], model.cursor[1] + 18); ctx.stroke(); ctx.restore();
    }
  }

  async function finish(completed, reason) {
    if (model.submitting) return;
    model.submitting = true; model.terminal = true;
    record("terminal", {tick: model.tick, completed, collected: [...model.collected], plane: planeSnapshot(), reason});
    setReadout(completed ? "FLIGHT LOG CLOSING · VERIFYING CONTACTS…" : `FAIL · ${reason} · REISSUING ROUTE…`, completed ? "pending" : "error");
    try {
      const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({
        mechanic_id: model.state.mechanic_id,
        task_id: model.state.task_id,
        challenge_id: model.state.challenge_id,
        interaction: model.interaction,
        events: model.events,
        contacts: model.events.filter((event) => event.type === "contact"),
        completed,
      })});
      const outcome = await response.json();
      if (outcome.passed === true) {
        document.querySelector(".cloudpost-shell")?.classList.add("is-pass");
        document.querySelector(".cloudpost-verdict").textContent = "PASS · ALL SEALS CONTACTED";
        setReadout("PASS · WORLD-SPACE DELIVERY CONFIRMED", "passed");
      } else if (outcome.state) {
        document.querySelector(".cloudpost-shell")?.classList.add("is-fail");
        setReadout("FAIL RECORDED · FRESH CLOUDPOST ISSUED", "error");
        window.setTimeout(() => { if (!model.destroyed) model.helpers.render(outcome.state); }, 520);
      } else {
        setReadout("FAIL · THE FLIGHT LOG WAS REJECTED", "error");
      }
    } catch (_error) {
      setReadout("FAIL · FLIGHT LOG COULD NOT BE SUBMITTED", "error");
      model.submitting = false;
    }
  }

  function cleanup() {
    model.destroyed = true;
    for (const item of model.cleanup) item();
    model.cleanup = [];
  }

  async function render(state, helpers) {
    cleanup();
    model.destroyed = false; model.state = state; model.helpers = helpers; model.interaction = interactionCondition();
    model.control = [0, 0]; model.cursor = [460, 270]; model.plane = {...state.initial_plane}; model.tick = 0; model.events = []; model.collected = []; model.terminal = false; model.submitting = false;
    document.body.dataset.mechanic = MECHANIC_ID;
    const simplified = model.interaction === "simplified";
    const controls = simplified ? `<div class="cloudpost-trims"><button data-trim="left">◀ TURN</button><button data-trim="up">▲ CLIMB</button><button data-trim="level">LEVEL</button><button data-trim="down">▼ DIVE</button><button data-trim="right">TURN ▶</button></div><p class="cloudpost-control-note">Each trim changes the same flight vector that the full pointer controls. Correct from the next observation.</p>` : `<p class="cloudpost-control-note"><span class="control-chip">FULL POINTER FLIGHT</span> Move across the flight field to bend the heading. The last vector persists until you correct it.</p>`;
    helpers.app.innerHTML = `<section class="cloudpost-shell ${simplified ? "is-simplified" : "is-full"}">
      <header class="cloudpost-header"><div><span class="cloudpost-kicker">CLOUDPOST CIRCUIT / AIRMAIL ROUTE</span><h1>Deliver the seals. Find the depth.</h1><p>${esc(state.prompt)}</p></div><div class="cloudpost-stats"><b class="cloudpost-count">0 / ${state.targets.length} SEALED</b><span class="cloudpost-tick">FLIGHT 000 · WORLD CORRIDOR</span></div></header>
      <div class="cloudpost-stage"><canvas class="cloudpost-canvas" width="920" height="540" aria-label="3D cloudpost flight field"></canvas><div class="cloudpost-hud"><span>WORLD CONTACT / NOT SCREEN OVERLAP</span><span class="cloudpost-readout" data-status="idle">STUDY THE HORIZON · STEER THE PLANE</span></div><div class="cloudpost-verdict"></div></div>
      <aside class="cloudpost-controls"><div class="cloudpost-control-head"><span>FLIGHT CONTROL</span><strong>${simplified ? "TRIM CONSOLE" : "POINTER VECTOR"}</strong></div>${controls}<div class="cloudpost-legend"><span><i class="legend-seal"></i> delivery seal</span><span><i class="legend-plane"></i> plane / camera</span><span><i class="legend-depth"></i> depth changes size</span></div><p class="cloudpost-warning">Targets may be beyond the current view. A glowing pass is not a delivery until the plane reaches the seal in 3D space.</p></aside>
      <footer class="cloudpost-footer"><span>SEALS REMAIN VISIBLE ONLY WHEN THEY ARE IN THE CAMERA FRUSTUM</span><span>ROUTE / ${esc(state.challenge_id)}</span></footer>
    </section>`;
    const canvas = document.querySelector(".cloudpost-canvas");
    if (simplified) {
      const actions = {left: [-0.12, 0, "TRIM LEFT"], right: [0.12, 0, "TRIM RIGHT"], up: [0, 0.10, "CLIMB VECTOR"], down: [0, -0.10, "DIVE VECTOR"], level: [0, 0, "LEVEL VECTOR"]};
      for (const button of document.querySelectorAll("[data-trim]")) {
        const handler = () => {
          if (model.terminal) return;
          const [yaw, pitch, label] = actions[button.dataset.trim];
          if (button.dataset.trim === "level") { model.control = [0, 0]; record("steer", {tick: model.tick, yaw: 0, pitch: 0, input_source: "trim_button"}); setReadout("LEVEL VECTOR · WATCH THE NEXT FRAME", "pending"); advanceAfterAction(); return; }
          trimControl(yaw, pitch, label);
        };
        button.addEventListener("click", handler); model.cleanup.push(() => button.removeEventListener("click", handler));
      }
    } else {
      canvas.addEventListener("pointermove", pointerControl); model.cleanup.push(() => canvas.removeEventListener("pointermove", pointerControl));
    }
    updateCounters(); drawScene();
  }

  window.GymAnythingRTMechanics.cloudpost_circuit_nonrealtime = {rootSelector: ".cloudpost-shell", render,
    // Read-only diagnostics for privileged construction checks. No setter,
    // clock control, action, hidden target or solution is exposed here.
    snapshot: () => JSON.parse(JSON.stringify({plane:model.plane, control:model.control, tick:model.tick,
      collected:model.collected, terminal:model.terminal, challenge_id:model.state?.challenge_id}))};
})();
