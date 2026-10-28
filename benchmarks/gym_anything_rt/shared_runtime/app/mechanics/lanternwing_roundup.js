(() => {
  "use strict";

  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const round = (value) => Math.round(Number(value) * 100000) / 100000;
  const dt = 0.08;
  const keys = new Set(["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright"]);

  const model = {
    state: null, helpers: null, interaction: "full", player: null, creatures: [], projectile: null,
    held: new Set(), pendingMove: null, tick: 0, ammo: 0, captures: [], events: [], trail: [],
    timer: null, raf: null, drag: null, terminal: false, submitting: false,
  };

  function record(type, details = {}) {
    model.events.push({seq: model.events.length + 1, type, ...details});
  }

  function sameAppearance(left, right) {
    return left && right && left.color === right.color && left.sigil === right.sigil;
  }

  function wantedIds() {
    const wanted = model.state.wanted || [];
    return new Set(model.creatures.filter((item) => wanted.some((cue) => sameAppearance(item.appearance, cue.appearance))).map((item) => item.id));
  }

  function direction(yaw, pitch) {
    const cp = Math.cos(pitch);
    return [Math.sin(yaw) * cp, Math.sin(pitch), Math.cos(yaw) * cp];
  }

  function position(motion, tick) {
    const phase = Number(motion.phase) + Number(motion.rate) * Number(tick);
    return {
      x: round(Number(motion.base_x) + Number(motion.amp_x) * Math.sin(phase)),
      y: round(Number(motion.base_y) + Number(motion.amp_y) * Math.sin(phase * 1.31)),
      z: round(Number(motion.base_z) + Number(motion.amp_z) * Math.cos(phase * 0.83)),
    };
  }

  function insideObstacle(point, obstacle) {
    return Number(obstacle.x) - Number(obstacle.width) / 2 <= point.x
      && point.x <= Number(obstacle.x) + Number(obstacle.width) / 2
      && Number(obstacle.z) - Number(obstacle.depth) / 2 <= point.z
      && point.z <= Number(obstacle.z) + Number(obstacle.depth) / 2
      && Number(obstacle.y) <= point.y
      && point.y <= Number(obstacle.y) + Number(obstacle.height);
  }

  function movePlayer(command = null) {
    const active = command ? new Set([command]) : model.held;
    const yaw = Number(model.player.yaw);
    const forward = [Math.sin(yaw), Math.cos(yaw)];
    const right = [Math.cos(yaw), -Math.sin(yaw)];
    let dx = 0, dz = 0;
    if (active.has("w") || active.has("arrowup") || active.has("forward")) { dx += forward[0]; dz += forward[1]; }
    if (active.has("s") || active.has("arrowdown") || active.has("back")) { dx -= forward[0]; dz -= forward[1]; }
    if (active.has("d") || active.has("arrowright") || active.has("right")) { dx += right[0]; dz += right[1]; }
    if (active.has("a") || active.has("arrowleft") || active.has("left")) { dx -= right[0]; dz -= right[1]; }
    const length = Math.hypot(dx, dz);
    if (length) {
      const distance = Number(model.state.world.move_speed) * dt;
      model.player.x += dx / length * distance;
      model.player.z += dz / length * distance;
    }
    const bounds = model.state.world.bounds;
    model.player.x = clamp(model.player.x, Number(bounds.x_min) + .45, Number(bounds.x_max) - .45);
    model.player.z = clamp(model.player.z, Number(bounds.z_min) + .45, Number(bounds.z_max) - .45);
  }

  function snapshot() {
    return {
      tick: model.tick,
      player: Object.fromEntries(Object.entries(model.player).map(([key, value]) => [key, round(value)])),
      creatures: model.creatures.map((item) => ({id: item.id, x: round(item.x), y: round(item.y), z: round(item.z)})),
      projectile: model.projectile ? Object.fromEntries(["x", "y", "z", "vx", "vy", "vz", "age"].map((key) => [key, key === "age" ? Number(model.projectile[key]) : round(model.projectile[key])])) : null,
      captures: [...model.captures], ammo: model.ammo,
    };
  }

  function step() {
    if (model.terminal || model.submitting) return;
    if (model.tick >= Number(model.state.physics.max_ticks)) { finish(false, "THE SANCTUARY CLOCK CLOSED"); return; }
    model.tick += 1;
    const command = model.pendingMove;
    model.pendingMove = null;
    movePlayer(command);
    model.creatures.forEach((item) => Object.assign(item, position(item.motion, model.tick)));
    let resolution = null;
    if (model.projectile) {
      const p = model.projectile;
      p.x += p.vx * dt;
      p.y += p.vy * dt - .5 * Number(model.state.physics.gravity) * dt * dt;
      p.z += p.vz * dt;
      p.vy -= Number(model.state.physics.gravity) * dt;
      p.age += 1;
      model.trail.push({x: p.x, y: p.y, z: p.z, until: performance.now() + 900});
      const blocked = p.y <= 0 || p.age >= Number(model.state.physics.max_projectile_ticks)
        || model.state.world.obstacles.some((obstacle) => insideObstacle(p, obstacle));
      if (blocked) { resolution = "miss"; model.projectile = null; }
      else {
        const hit = model.creatures.find((item) => Math.hypot(p.x - item.x, p.y - item.y, p.z - item.z) <= Number(item.radius) + Number(model.state.physics.projectile_radius));
        if (hit) {
          resolution = wantedIds().has(hit.id) ? "target" : "decoy";
          model.captures.push(hit.id);
          model.creatures = model.creatures.filter((item) => item.id !== hit.id);
          model.projectile = null;
        }
      }
    }
    record("tick", {snapshot: snapshot(), resolution});
    updatePanels();
    if ([...wantedIds()].every((id) => model.captures.includes(id))) { finish(true, "ALL WANTED WINGS SECURED"); return; }
    if (model.ammo <= 0 && !model.projectile) finish(false, "CAPSULES SPENT · RECOVER AND RETRY");
  }

  function resetListeners() {
    if (model.timer) window.clearInterval(model.timer);
    if (model.raf) window.cancelAnimationFrame(model.raf);
    if (model.keyDown) document.removeEventListener("keydown", model.keyDown);
    if (model.keyUp) document.removeEventListener("keyup", model.keyUp);
    model.timer = null; model.raf = null;
  }

  async function submit(completed, reason) {
    if (model.submitting) return;
    model.submitting = true; model.terminal = true; resetListeners();
    const accepted = completed && [...wantedIds()].every((id) => model.captures.includes(id));
    record("certify", {accepted, input_source: "certify_button", reason});
    model.helpers.setReadout("INDEPENDENT 3D REPLAY IN PROGRESS…", "pending");
    try {
      const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({
        mechanic_id: model.state.mechanic_id, task_id: model.state.task_id, challenge_id: model.state.challenge_id,
        interaction: model.interaction, events: model.events, completed,
      })});
      const result = await response.json();
      if (result.passed === true) {
        model.helpers.setReadout("PASS · 3D CONTACTS VERIFIED", "passed");
        document.querySelector(".lanternwing")?.insertAdjacentHTML("beforeend", '<div class="lw-verdict is-pass"><strong>ROUNDUP PASS</strong><span>GRAVITY FLIGHT · MOVING TARGET CONTACT · REPLAY ACCEPTED</span></div>');
      } else if (result.passed === false && result.state) {
        await model.helpers.render(result.state);
        document.querySelector(".lanternwing")?.insertAdjacentHTML("beforeend", `<div class="lw-verdict is-fresh"><strong>FAIL · FRESH SANCTUARY</strong><span>${esc(result.feedback || "The failed run was replaced")}</span></div>`);
      } else {
        model.submitting = false; model.terminal = false; model.helpers.setReadout(`FAIL · ${result.feedback || "AUTHORITATIVE GRADE REJECTED"}`, "error");
      }
    } catch (error) {
      model.submitting = false; model.terminal = false; model.helpers.setReadout(`FAIL · VERIFIER OFFLINE · ${error.message}`, "error");
    }
  }

  function finish(completed, reason) { if (!model.terminal && !model.submitting) void submit(completed, reason); }

  function throwCapsule(inputSource) {
    if (model.terminal || model.submitting || model.projectile || model.ammo <= 0) return;
    const [dx, dy, dz] = direction(Number(model.player.yaw), Number(model.player.pitch));
    const origin = {x: model.player.x, y: model.player.y + Number(model.state.world.eye_height), z: model.player.z};
    model.projectile = {
      x: origin.x, y: origin.y, z: origin.z,
      vx: dx * Number(model.state.physics.projectile_speed), vy: dy * Number(model.state.physics.projectile_speed), vz: dz * Number(model.state.physics.projectile_speed), age: 0,
    };
    model.ammo -= 1;
    record("throw", {tick: model.tick, input_source: inputSource, origin_x: round(origin.x), origin_y: round(origin.y), origin_z: round(origin.z), dir_x: round(dx), dir_y: round(dy), dir_z: round(dz)});
    updatePanels();
  }

  function proxyMove(directionName) {
    if (model.interaction !== "simplified" || model.terminal) return;
    record("input", {action: "step", move: directionName, input_source: "move_button"});
    model.pendingMove = directionName;
  }

  function proxyLook(axis, delta) {
    if (model.interaction !== "simplified" || model.terminal) return;
    if (axis === "yaw") model.player.yaw = clamp(model.player.yaw + delta, -Math.PI, Math.PI);
    else model.player.pitch = clamp(model.player.pitch + delta, -1.15, 1.15);
    record("look", {yaw: round(model.player.yaw), pitch: round(model.player.pitch), input_source: "look_button"});
    draw();
  }

  function bindFullControls(canvas) {
    model.keyDown = (event) => {
      const key = String(event.key || "").toLowerCase();
      if (!keys.has(key) || event.repeat || model.terminal) return;
      event.preventDefault(); model.held.add(key); record("input", {action: "key_down", key, input_source: "move_keydown"});
    };
    model.keyUp = (event) => {
      const key = String(event.key || "").toLowerCase();
      if (!keys.has(key)) return;
      event.preventDefault(); model.held.delete(key); record("input", {action: "key_up", key, input_source: "move_keyup"});
    };
    document.addEventListener("keydown", model.keyDown); document.addEventListener("keyup", model.keyUp);
    canvas.addEventListener("pointerdown", (event) => {
      if (model.terminal) return;
      model.drag = {id: event.pointerId, x: event.clientX, y: event.clientY, moved: false};
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!model.drag || model.drag.id !== event.pointerId) return;
      const dx = event.clientX - model.drag.x, dy = event.clientY - model.drag.y;
      if (dx || dy) model.drag.moved = true;
      model.drag.x = event.clientX; model.drag.y = event.clientY;
      model.player.yaw = clamp(model.player.yaw + dx * .008, -Math.PI, Math.PI);
      model.player.pitch = clamp(model.player.pitch + dy * .006, -1.15, 1.15);
      record("look", {yaw: round(model.player.yaw), pitch: round(model.player.pitch), input_source: "mouse_drag"});
      draw();
    });
    canvas.addEventListener("pointerup", (event) => {
      if (!model.drag || model.drag.id !== event.pointerId) return;
      const wasDrag = model.drag.moved; model.drag = null;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      if (!wasDrag) throwCapsule("canvas_throw");
    });
  }

  function project(point, width, height) {
    const dx = Number(point.x) - model.player.x, dy = Number(point.y) - model.player.y, dz = Number(point.z) - model.player.z;
    const yaw = Number(model.player.yaw), pitch = Number(model.player.pitch);
    const side = dx * Math.cos(yaw) - dz * Math.sin(yaw);
    const depth0 = dx * Math.sin(yaw) + dz * Math.cos(yaw);
    const vertical = dy * Math.cos(pitch) - depth0 * Math.sin(pitch);
    const depth = depth0 * Math.cos(pitch) + dy * Math.sin(pitch);
    const scale = 520 / Math.max(.8, depth);
    return {x: width / 2 + side * scale, y: height * .56 - vertical * scale, depth, scale};
  }

  function poly(context, points, fill, stroke = null) {
    const visible = points.filter((point) => point.depth > .2);
    if (visible.length < 2) return;
    context.beginPath(); context.moveTo(visible[0].x, visible[0].y); visible.slice(1).forEach((point) => context.lineTo(point.x, point.y)); context.closePath();
    context.fillStyle = fill; context.fill(); if (stroke) { context.strokeStyle = stroke; context.stroke(); }
  }

  function drawBox(context, box, width, height, fill) {
    const x = Number(box.x), z = Number(box.z), w = Number(box.width || box.w), d = Number(box.depth || box.d), y = Number(box.y || 0), h = Number(box.height || 1);
    const corners = [[x-w/2,y,z-d/2],[x+w/2,y,z-d/2],[x+w/2,y,z+d/2],[x-w/2,y,z+d/2],[x-w/2,y+h,z-d/2],[x+w/2,y+h,z-d/2],[x+w/2,y+h,z+d/2],[x-w/2,y+h,z+d/2]].map(([cx,cy,cz]) => project({x:cx,y:cy,z:cz}, width, height));
    poly(context, [corners[4],corners[5],corners[6],corners[7]], fill, "rgba(255,240,181,.25)");
    poly(context, [corners[0],corners[1],corners[5],corners[4]], "rgba(39,33,55,.78)");
    poly(context, [corners[1],corners[2],corners[6],corners[5]], "rgba(79,56,74,.78)");
  }

  function drawCreature(context, item, width, height) {
    const point = project(item, width, height); if (point.depth <= .2) return;
    const r = clamp(point.scale * .26, 7, 48); const color = item.appearance.accent;
    context.save(); context.translate(point.x, point.y); context.shadowBlur = 20; context.shadowColor = color;
    context.fillStyle = color; context.globalAlpha = .82;
    context.beginPath(); context.moveTo(-r*.2, 0); context.lineTo(-r*1.55, -r*.65); context.lineTo(-r*1.05, r*.35); context.closePath(); context.fill();
    context.beginPath(); context.moveTo(r*.2, 0); context.lineTo(r*1.55, -r*.65); context.lineTo(r*1.05, r*.35); context.closePath(); context.fill();
    context.globalAlpha = 1; context.fillStyle = "#fff4c1"; context.beginPath(); context.arc(0, 0, r*.38, 0, Math.PI*2); context.fill();
    context.strokeStyle = color; context.lineWidth = Math.max(1, r*.08); context.stroke();
    context.fillStyle = "#352e4c"; context.font = `bold ${Math.max(8, r*.52)}px Georgia`; context.textAlign = "center"; context.textBaseline = "middle";
    context.fillText(item.appearance.sigil === "crescent" ? "☾" : item.appearance.sigil === "diamond" ? "◇" : item.appearance.sigil === "thorn" ? "†" : item.appearance.sigil === "fork" ? "Y" : "·", 0, 0);
    context.restore();
  }

  function draw(timestamp) {
    const canvas = document.getElementById("lw-canvas"); if (!canvas || !model.state) return;
    const context = canvas.getContext("2d"), width = canvas.width, height = canvas.height;
    const sky = context.createLinearGradient(0, 0, 0, height); sky.addColorStop(0, "#171a3b"); sky.addColorStop(.55, "#493a63"); sky.addColorStop(1, "#b87970"); context.fillStyle = sky; context.fillRect(0, 0, width, height);
    context.fillStyle = "rgba(255,220,146,.72)"; context.beginPath(); context.arc(width*.78, height*.17, 43, 0, Math.PI*2); context.fill();
    context.strokeStyle = "rgba(255,241,183,.18)"; context.lineWidth = 1;
    for (let z = 2; z < 25; z += 1.4) { const a = project({x:-13,y:0,z},width,height), b = project({x:13,y:0,z},width,height); if (a.depth>.1 && b.depth>.1) { context.beginPath(); context.moveTo(a.x,a.y); context.lineTo(b.x,b.y); context.stroke(); } }
    for (let x = -12; x <= 12; x += 1.4) { const a = project({x,y:0,z:2},width,height), b = project({x,y:0,z:25},width,height); if (a.depth>.1 && b.depth>.1) { context.beginPath(); context.moveTo(a.x,a.y); context.lineTo(b.x,b.y); context.stroke(); } }
    model.state.world.terraces.forEach((box) => drawBox(context, {...box, width:box.width, depth:box.depth, height:.45, y:box.height-.45}, width, height, "rgba(90,198,174,.32)"));
    model.state.world.obstacles.forEach((box) => drawBox(context, box, width, height, "rgba(31,27,51,.84)"));
    model.trail = model.trail.filter((item) => item.until > performance.now());
    model.trail.forEach((item, index) => { const p = project(item,width,height); if (p.depth > .2) { context.globalAlpha = .08 + index / Math.max(1,model.trail.length)*.5; context.fillStyle="#ffd477"; context.beginPath(); context.arc(p.x,p.y,Math.max(2,p.scale*.05),0,Math.PI*2); context.fill(); } }); context.globalAlpha=1;
    [...model.creatures].sort((a,b) => project(a,width,height).depth - project(b,width,height).depth).forEach((item) => drawCreature(context,item,width,height));
    if (model.projectile) { const p=project(model.projectile,width,height); if(p.depth>.2){context.save();context.shadowBlur=18;context.shadowColor="#ffe39c";context.fillStyle="#fff1b1";context.beginPath();context.arc(p.x,p.y,Math.max(4,p.scale*.13),0,Math.PI*2);context.fill();context.strokeStyle="#d77c9b";context.stroke();context.restore();} }
    context.fillStyle="rgba(255,244,200,.9)"; context.font="700 12px ui-monospace,monospace"; context.fillText(`SANCTUARY TICK ${model.tick} · AMMO ${model.ammo}`,18,24);
    const reticleX=width/2, reticleY=height*.56; context.strokeStyle="rgba(255,245,197,.8)"; context.beginPath();context.moveTo(reticleX-10,reticleY);context.lineTo(reticleX+10,reticleY);context.moveTo(reticleX,reticleY-10);context.lineTo(reticleX,reticleY+10);context.stroke();
    model.raf = requestAnimationFrame(draw);
  }

  function updatePanels() {
    const wanted = wantedIds(), secured = [...wanted].filter((id) => model.captures.includes(id)).length;
    document.getElementById("lw-clock")?.replaceChildren(document.createTextNode(`${model.tick} / ${model.state.physics.max_ticks}`));
    document.getElementById("lw-ammo")?.replaceChildren(document.createTextNode(`${model.ammo} CAPSULE${model.ammo===1?"":"S"}`));
    document.getElementById("lw-secured")?.replaceChildren(document.createTextNode(`${secured} / ${wanted.size} WANTED WINGS`));
    const note = model.projectile ? "CAPSULE IN FLIGHT · WATCH THE ARC" : model.interaction === "full" ? "MOVE · LOOK · CLICK TO THROW" : "USE PROXY CONTROLS · WATCH THE ARC";
    if (!model.terminal) model.helpers?.setReadout(note, model.projectile ? "pending" : "idle");
  }

  function markup(state, interaction, helpers) {
    const cues = (state.wanted || []).map((cue) => `<li><i style="--wing:${esc(cue.appearance.accent)}"></i><span>${esc(cue.label)}</span><b>${esc(cue.appearance.color)} · ${esc(cue.appearance.sigil)}</b></li>`).join("");
    const proxy = interaction === "simplified" ? `<section class="lw-proxy"><small>PROXY MOVEMENT / LOOK</small><div class="lw-pad"><button data-move="forward">↑</button><button data-move="left">←</button><button data-move="back">↓</button><button data-move="right">→</button></div><div class="lw-look"><button data-look="yaw" data-delta="-.08">TURN LEFT</button><button data-look="yaw" data-delta=".08">TURN RIGHT</button><button data-look="pitch" data-delta="-.06">LOOK DOWN</button><button data-look="pitch" data-delta=".06">LOOK UP</button></div><button id="lw-throw-proxy" class="lw-primary">THROW CAPSULE</button></section>` : `<section class="lw-full"><small>FULL INPUT SURFACE</small><p><kbd>W A S D</kbd> walk · drag the sanctuary to look · click the scene to release a capsule.</p></section>`;
    return `<section class="lanternwing" data-interaction="${esc(interaction)}" data-challenge-id="${esc(state.challenge_id)}"><header class="lw-head"><div><span>THE LANTERNWING ROUNDUP / TERRACE SANCTUARY</span><h1>Catch what moves between the terraces.</h1></div><aside><small>INPUT SURFACE</small><b>${esc(interaction.toUpperCase())}</b><i>${esc(state.palette)}</i></aside></header><main class="lw-main"><section class="lw-stage"><canvas id="lw-canvas" width="820" height="500" aria-label="first-person 3D sanctuary with moving lanternwing creatures"></canvas><div class="lw-legend"><span>◆</span> flight arc is physical · wings keep moving during flight · depth is not screen position</div></section><aside class="lw-console"><div class="lw-console-title"><span>WANTED WINGS</span><b id="lw-secured">0 / ${state.wanted.length} WANTED WINGS</b></div><p class="lw-prompt">${esc(state.prompt)}</p><ul class="lw-wanted">${cues}</ul>${proxy}<dl class="lw-stats"><div><dt>SANCTUARY CLOCK</dt><dd id="lw-clock">0 / ${state.physics.max_ticks}</dd></div><div><dt>CAPSULES</dt><dd id="lw-ammo">${state.physics.ammo} CAPSULES</dd></div><div><dt>CONTACT MODEL</dt><dd>3 AXES + GRAVITY</dd></div></dl><button id="lw-submit" class="lw-submit">${esc(state.submit_label)}</button><p class="lw-note">A direct crosshair hit is not a capture. Release from a useful position, lead the moving wing, and inspect the next frame.</p></aside></main><footer class="lw-foot"><div><span>${esc(state.challenge_id.toUpperCase())} · ${esc(interaction.toUpperCase())} MODE</span><div id="lw-readout" class="readout" data-status="idle">OBSERVE THE TERRACES</div></div><div class="lw-rule">GRAVITY-DRIVEN CAPSULE CONTACT</div></footer>${helpers.cheatPanelTemplate()}</section>`;
  }

  function render(state, helpers) {
    resetListeners();
    document.body.dataset.mechanic = "lanternwing-roundup";
    const interaction = String(state.control_condition?.interaction || "full");
    Object.assign(model, {state, helpers, interaction, player: copy(state.world.player_start), creatures: copy(state.creatures), projectile: null, held: new Set(), pendingMove: null, tick: 0, ammo: Number(state.physics.ammo), captures: [], events: [], trail: [], terminal: false, submitting: false, drag: null});
    helpers.app.innerHTML = markup(state, interaction, helpers);
    const readout = document.getElementById("lw-readout");
    const localHelpers = {...helpers, setReadout: (message, status="idle") => { if (readout) { readout.textContent=message; readout.dataset.status=status; } helpers.setReadout(message,status); }};
    model.helpers = localHelpers;
    if (interaction === "simplified") {
      document.querySelectorAll("[data-move]").forEach((button) => button.addEventListener("click", () => proxyMove(button.dataset.move)));
      document.querySelectorAll("[data-look]").forEach((button) => button.addEventListener("click", () => proxyLook(button.dataset.look, Number(button.dataset.delta))));
      document.getElementById("lw-throw-proxy")?.addEventListener("click", () => throwCapsule("throw_button"));
    } else bindFullControls(document.getElementById("lw-canvas"));
    document.getElementById("lw-submit")?.addEventListener("click", () => finish(false, "manual certification before all wanted contacts"));
    model.timer = window.setInterval(step, Number(state.physics.tick_ms));
    window.lanternwingRoundupModel = model;
    updatePanels(); draw(0);
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.lanternwing_roundup = {rootSelector: ".lanternwing", render};
})();
