(() => {
  "use strict";
  let model = null;
  let keyHandler = null;
  let keyUpHandler = null;
  let animationFrame = 0;
  const motionUrl = new URL('realtime_four_motion.js', document.currentScript.src).href;
  const clean = (value) =>
    String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const round = (value) => Math.round(Number(value) * 10000) / 10000;
  function record(kind, details = {}) {
    const event = { sequence: model.events.length + 1, kind, tick: model.tick, ...details };
    model.events.push(event);
    return event;
  }
  function cloneObjects(objects = model.objects) {
    return Object.fromEntries(
      Object.entries(objects).map((
        [id, obj],
      ) => [id, { ...obj, center: [...obj.center] }]),
    );
  }
  function project(camera, point) {
    return camera.matrix.map((row, index) =>
      round(
        camera.origin[index] +
          row.reduce((sum, value, column) => sum + value * point[column], 0),
      )
    );
  }
  function digest(camera, claw, objects, captured) {
    const items = [
      ["claw", claw],
      ...Object.entries(objects).sort().map((
        [id, obj],
      ) => [id, id === captured ? claw : obj.center]),
    ];
    return items.map(([id, point]) => {
      const p = project(camera, point);
      return `${id}:${p[0].toFixed(4)}:${p[1].toFixed(4)}`;
    }).join("|");
  }
  function pointAabb(point, obstacle, radius) {
    return point.every((value, index) =>
      Math.abs(value - obstacle.center[index]) <= obstacle.half[index] + radius
    );
  }
  function blocker(start, end, radius) {
    const distance = Math.hypot(...end.map((v, i) => v - start[i])),
      steps = Math.max(
        1,
        Math.ceil(distance / model.state.world.collision_step),
      ),
      bounds = model.state.world.bounds;
    for (let n = 1; n <= steps; n++) {
      const t = n / steps, p = start.map((v, i) => v + (end[i] - v) * t);
      for (const [i, axis] of ["x", "y", "z"].entries()) {
        if (
          p[i] - radius < bounds[axis][0] || p[i] + radius > bounds[axis][1]
        ) return "cage-boundary";
      }
      for (const obstacle of model.state.obstacles) {
        if (pointAabb(p, obstacle, radius)) return obstacle.id;
      }
    }
    return null;
  }
  function contained(point, radius, box) {
    return point.every((v, i) =>
      Math.abs(v - box.center[i]) + radius <= box.half[i] + 1e-6
    );
  }
  function snapshot() {
    return {
      position: [...model.position],
      objects: cloneObjects(),
      captured: model.captured,
      chute: structuredClone(model.chute),
    };
  }
  function frameState(viewId) {
    const camera = model.state.cameras[viewId],
      visibleTick = Math.max(0, model.tick - camera.delay),
      snap = model.history[visibleTick];
    return {
      tick: visibleTick,
      digest: digest(camera, snap.position, snap.objects, snap.captured),
      snapshot: snap,
    };
  }
  function updateHistory() {
    const ms = model.tick * model.state.world.tick_seconds * 1000;
    for (const original of model.state.objects) {
      if (original.id !== model.captured) {
        const offset = RealtimeFourMotion.vector(original.motion, ms);
        model.objects[original.id].center = original.center.map((v, i) => v + offset[i]);
      }
    }
    const offset = RealtimeFourMotion.vector(model.state.chute.motion, ms);
    model.chute = {...model.state.chute, center: model.state.chute.center.map((v, i) => v + offset[i])};
    if (model.captured) {
      model.objects[model.captured].center = [...model.position];
    }
    model.history[model.tick] = snapshot();
  }
  function clearFresh() {
    const root = document.querySelector(".claw-captcha"),
      wasFresh = root?.dataset.freshFailure === "true";
    document.querySelector(".claw-fresh")?.remove();
    root?.removeAttribute("data-fresh-failure");
    if (wasFresh && model && !model.terminal && !model.delivered) {
      setMessage("FRESH CAGE ACTIVE · TRIANGULATE THE MARKED ARTIFACT");
    }
  }
  function setMessage(message, status = "idle") {
    model.helpers.setReadout(message, status);
  }
  function applyControl(axis, direction, held, inputSource) {
    if (model.terminal || model.submitting || model.delivered) return;
    clearFresh();
    syncWorld();
    const key = `${axis}:${direction}`;
    if (model.held.has(key) === held) return;
    if (held) model.held.add(key); else model.held.delete(key);
    record('control', {axis, direction, held, input_source: inputSource});
  }
  function syncWorld() {
    if (!model || model.terminal || model.submitting) return;
    const target = Math.min(model.state.requirements.max_ticks,
      Math.floor((performance.now() - model.startedAt) / (1000 * model.state.world.tick_seconds)));
    while (model.tick < target) physicsTick();
    if (model.tick >= model.state.requirements.max_ticks) {
      model.terminal = true; model.failed = true; submit();
    }
  }
  function animate() {
    syncWorld();
    if (model) { drawFeeds(); updateHUD(); }
    animationFrame = requestAnimationFrame(animate);
  }
  function physicsTick() {
    const world = model.state.world;
    const wind = RealtimeFourMotion.vector(world.wind, model.tick * world.tick_seconds * 1000);
    for (let i = 0; i < 3; i++) {
      const axis = ['x', 'y', 'z'][i];
      const thrust = Number(model.held.has(`${axis}:1`)) - Number(model.held.has(`${axis}:-1`));
      model.velocity[i] += thrust * world.acceleration + wind[i];
    }
    const speed = Math.hypot(...model.velocity);
    if (speed > world.max_speed) model.velocity = model.velocity.map(v => v * world.max_speed / speed);
    const start = [...model.position],
      candidate = model.position.map((v, i) => v + model.velocity[i]),
      radius = model.captured
        ? Math.max(
          model.state.world.claw_radius,
          model.objects[model.captured].radius,
        )
        : model.state.world.claw_radius,
      contact = blocker(start, candidate, radius);
    let resolution = "full", resolved = candidate;
    if (contact) {
      resolved = [...start];
      let moved = false;
      for (let index = 0; index < 3; index++) {
        const trial = [...resolved];
        trial[index] = candidate[index];
        if (!blocker(resolved, trial, radius)) {
          resolved = trial;
          moved ||= Math.abs(trial[index] - start[index]) > 1e-9;
        } else model.velocity[index] = 0;
      }
      resolution = moved ? "slide" : "blocked";
      model.collisions++;
      const alert = document.querySelector(".claw-impact");
      alert.dataset.visible = "true";
      alert.querySelector("span").textContent =
        `${contact.toUpperCase()} · ${resolution.toUpperCase()}`;
      setMessage(
        `RIGID CONTACT · ${contact.toUpperCase()} · RECOVER WITH BRAKE / REVERSE`,
        "error",
      );
    } else document.querySelector(".claw-impact").dataset.visible = "false";
    model.position = resolved;
    model.velocity = model.velocity.map((v) => v * model.state.world.damping);
    model.tick++;
    updateHistory();
  }
  function grip(inputSource = "control_buttons") {
    if (model.terminal || model.submitting || model.delivered) return;
    clearFresh();
    syncWorld();
    if (model.gripper === "open") {
      const candidates = Object.entries(model.objects).map((
        [id, obj],
      ) => [
        Math.hypot(...obj.center.map((v, i) => v - model.position[i])),
        id,
      ]).sort((a, b) => a[0] - b[0]);
      let captured = null;
      for (const [distance, id] of candidates) {
        const obj = model.objects[id];
        if (
          distance <= model.state.world.capture_distance &&
          !blocker(obj.center, model.position, obj.radius)
        ) {
          captured = id;
          break;
        }
      }
      model.gripper = "closed";
      model.captured = captured;
      record("gripper", { action: "close", captured_id: captured, input_source: inputSource });
      if (captured) {
        model.objects[captured].center = [...model.position];
        setMessage(
          "GRIPPER LOAD DETECTED · LIFT ABOVE THE CAGE BAFFLES",
          "pending",
        );
      } else setMessage("GRIPPER CLOSED ON EMPTY AIR", "error");
    } else {
      const released = model.captured,
        delivered = Boolean(
          released && model.objects[released].marked &&
            contained(
              model.position,
              model.objects[released].radius,
              model.chute,
            ),
        );
      record("gripper", { action: "open", released_id: released, delivered, input_source: inputSource });
      model.gripper = "open";
      model.captured = null;
      if (delivered) {
        model.delivered = model.terminal = true;
        document.querySelector(".claw-complete").dataset.visible = "true";
        setMessage("MARKED ARTIFACT CONTAINED IN DELIVERY CHUTE", "passed");
      } else {setMessage(
          released
            ? "LOAD RELEASED OUTSIDE CERTIFIED CHUTE"
            : "EMPTY GRIPPER OPENED",
          released ? "error" : "idle",
        );}
    }
    updateHistory();
    drawFeeds();
    updateHUD();
    const last = model.events.at(-1);
    if ((last.action === 'close' && (!model.captured || !model.objects[model.captured].marked)) ||
        (last.action === 'open' && !model.delivered)) {
      model.failed = true;
      model.terminal = true;
      setMessage('FAIL · MISSED GRIP OR LOST ARTIFACT', 'error');
      submit();
    }
  }
  function drawFeed(viewId) {
    const canvas = document.querySelector(`.claw-feed[data-view='${viewId}']`),
      ctx = canvas.getContext("2d"),
      camera = model.state.cameras[viewId],
      frame = frameState(viewId),
      snap = frame.snapshot;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#0a100e";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#90ad9640";
    ctx.lineWidth = 1;
    for (let i = 0; i < 12; i++) {
      ctx.beginPath();
      ctx.moveTo(i * canvas.width / 11, 0);
      ctx.lineTo(i * canvas.width / 11, canvas.height);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, i * canvas.height / 11);
      ctx.lineTo(canvas.width, i * canvas.height / 11);
      ctx.stroke();
    }
    function drawBox(center, half, color) {
      const p = project(camera, center),
        hx = Math.max(
          5,
          Math.abs(camera.matrix[0][0]) * half[0] +
            Math.abs(camera.matrix[0][1]) * half[1] +
            Math.abs(camera.matrix[0][2]) * half[2],
        ),
        hy = Math.max(
          5,
          Math.abs(camera.matrix[1][0]) * half[0] +
            Math.abs(camera.matrix[1][1]) * half[1] +
            Math.abs(camera.matrix[1][2]) * half[2],
        );
      ctx.fillStyle = color;
      ctx.strokeStyle = color;
      ctx.fillRect(p[0] - hx, p[1] - hy, hx * 2, hy * 2);
      ctx.strokeRect(p[0] - hx, p[1] - hy, hx * 2, hy * 2);
    }
    const scale = Math.max(...camera.matrix.flat().map(Math.abs));
    const primitives = [
      ...model.state.obstacles.map((obstacle) => ({
        kind: "box",
        center: obstacle.center,
        half: obstacle.half,
        color: "#303a35",
        priority: 2,
      })),
      {
        kind: "box",
        center: snap.chute.center,
        half: snap.chute.half,
        color: model.state.palette.chute,
        priority: 1,
      },
      ...Object.entries(snap.objects).map(([id, obj]) => ({
        kind: "object",
        center: id === snap.captured ? snap.position : obj.center,
        obj,
        priority: 3,
      })),
      { kind: "claw", center: snap.position, priority: 4 },
    ];
    primitives.sort((a, b) =>
      (a.center[camera.depth_axis] * camera.depth_sign) -
        (b.center[camera.depth_axis] * camera.depth_sign) ||
      a.priority - b.priority
    );
    primitives.forEach((primitive) => {
      if (primitive.kind === "box") {
        drawBox(primitive.center, primitive.half, primitive.color);
        return;
      }
      const p = project(camera, primitive.center);
      if (primitive.kind === "object") {
        const obj = primitive.obj;
        ctx.fillStyle = obj.color;
        ctx.strokeStyle = obj.marked ? "#fff" : "#18231e";
        ctx.lineWidth = obj.marked ? 3 : 1;
        ctx.beginPath();
        ctx.arc(p[0], p[1], Math.max(5, obj.radius * scale), 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        if (obj.marked) {
          const radius = obj.radius * scale;
          ctx.beginPath();
          ctx.moveTo(p[0], p[1] - radius - 4);
          ctx.lineTo(p[0] - 6, p[1] - radius - 12);
          ctx.lineTo(p[0] + 6, p[1] - radius - 12);
          ctx.closePath();
          ctx.fillStyle = "#fff";
          ctx.fill();
        }
        return;
      }
      const radius = model.state.world.claw_radius * scale;
      ctx.strokeStyle = model.state.palette.claw;
      ctx.fillStyle = model.state.palette.claw;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(p[0], p[1], Math.max(5, radius), 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(p[0] - radius - 4, p[1] + radius + 5);
      ctx.lineTo(p[0], p[1] + 3);
      ctx.lineTo(p[0] + radius + 4, p[1] + radius + 5);
      ctx.stroke();
    });
    ctx.fillStyle = "#d8eadc";
    ctx.font = "700 10px ui-monospace";
    ctx.fillText(
      `${camera.label} · FRAME T${frame.tick} · DELAY ${camera.delay}`,
      10,
      15,
    );
    document.querySelector(`.claw-feed-tick[data-view='${viewId}']`)
      .textContent = `T${frame.tick}`;
  }
  function drawFeeds() {
    Object.keys(model.state.cameras).forEach(drawFeed);
  }
  function updateHUD() {
    document.querySelector(".claw-speed").textContent = Math.hypot(
      ...model.velocity,
    ).toFixed(2);
    document.querySelector(".claw-grip-state").textContent = model.gripper
      .toUpperCase();
    document.querySelector(".claw-load-state").textContent = model.captured
      ? "LOAD"
      : "EMPTY";
    document.querySelector(".claw-tick").textContent = String(model.tick);
    const gripButton = document.querySelector(".claw-grip");
    if (gripButton) {
      gripButton.textContent = model.gripper === "open"
        ? "CLOSE GRIPPER"
        : "OPEN / RELEASE";
    }
  }
  async function submit() {
    if (model.submitting) return;
    syncWorld();
    model.submitting = true;
    setMessage(
      "REPLAYING INERTIAL TICKS, SWEPT CAGE CONTACTS, AND STAGGERED FEEDS…",
      "pending",
    );
    const payload = {
      mechanic_id: model.state.mechanic_id,
      task_id: model.state.task_id,
      challenge_id: model.state.challenge_id,
      interaction_mode: model.interaction,
      events: model.events,
      delivered: model.delivered,
      position: model.position.map(round),
      velocity: model.velocity.map(round),
      captured_id: model.captured,
      gripper: model.gripper,
      ticks: model.tick,
      collisions: model.collisions,
      resets: model.resets,
      feeds_seen: Object.keys(model.state.cameras).sort(),
    };
    try {
      const response = await fetch("/result", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        }),
        outcome = await response.json();
      if (outcome.passed === true) {
        model.terminal = true;
        document.querySelector(".claw-captcha").insertAdjacentHTML(
          "beforeend",
          '<div class="claw-verdict"><small>STAGGERED CCTV CHAIN VERIFIED</small><strong>PASS</strong><span>INERTIA · MULTI-VIEW PROJECTION · GEOMETRIC DELIVERY</span></div>',
        );
        setMessage("PASS", "passed");
      } else if (outcome.passed === false) {
        model.terminal = true;
        setMessage('FAIL · ATTEMPT ENDED', 'error');
      } else {
        model.submitting = false;
        setMessage("FAIL · NO AUTHORITATIVE CLAW GRADE", "error");
      }
    } catch (_) {
      model.submitting = false;
      setMessage("FAIL · CLAW VERIFIER OFFLINE", "error");
    }
  }
  async function render(state, helpers) {
    await import(motionUrl);
    cancelAnimationFrame(animationFrame);
    if (keyUpHandler) window.removeEventListener('keyup', keyUpHandler);
    document.body.dataset.mechanic = "three-camera-claw-machine";
    if (keyHandler) window.removeEventListener("keydown", keyHandler);
    const interaction = state.control_condition?.interaction || "simplified";
    if (!["simplified", "full"].includes(interaction)) {
      throw new Error("three-camera claw interaction is invalid");
    }
    const consoleControls = interaction === "simplified"
      ? `<div class="claw-controls">${
        ["x", "y", "z"].map((axis) =>
          `<div><b>${axis.toUpperCase()} AXIS</b><button class="claw-control" data-axis="${axis}" data-direction="-1">${axis.toUpperCase()}−</button><button class="claw-control" data-axis="${axis}" data-direction="1">${axis.toUpperCase()}+</button></div>`
        ).join("")
      }</div><button class="claw-grip">CLOSE GRIPPER</button>`
      : `<div class="claw-direct-controls"><b>HOLD TO THRUST · RELEASE TO COAST</b><span>A / D · X− / X+</span><span>W / S · Y+ / Y−</span><span>Q / E · Z− / Z+</span><span>F · CLOSE / RELEASE</span><span>Cargo, chute and wind keep moving.</span><span>Missed grip or lost load ends the attempt.</span></div>`;
    helpers.app.innerHTML = `<section class="claw-captcha" data-interaction="${
      clean(interaction)
    }" data-challenge-id="${
      clean(state.challenge_id)
    }"><header class="claw-head"><div><span>REMOTE RECOVERY CELL / ${
      clean(state.challenge_id)
    }</span><h1>${
      clean(state.prompt)
    }</h1></div><p>NO DIRECT WINDOW<br><b>THREE DELAYED CAMERA CLOCKS</b></p></header><main class="claw-main"><section class="claw-feeds">${
      Object.entries(state.cameras).map(([id, camera]) =>
        `<article><header><b>${
          clean(camera.label)
        }</b><span class="claw-feed-tick" data-view="${id}">T0</span></header><canvas class="claw-feed" data-view="${id}" width="340" height="230"></canvas></article>`
      ).join("")
    }</section><aside class="claw-console"><span class="claw-kicker">SIX-AXIS INERTIAL GANTRY</span><h2>Correct what the cameras have not shown you yet.</h2>${
      consoleControls
    }<div class="claw-stats"><span>SPEED<b class="claw-speed">0.00</b></span><span>GRIP<b class="claw-grip-state">OPEN</b></span><span>LOAD<b class="claw-load-state">EMPTY</b></span><span>TICK<b class="claw-tick">0</b></span></div></aside><div class="claw-impact" data-visible="false"><b>CAGE CONTACT</b><span>RECOVER</span></div><div class="claw-complete" data-visible="false"><b>DELIVERY CONTAINED</b><span>MARKED LOAD IN CHUTE</span></div></main><footer class="claw-foot"><div><span>DELAY-AWARE PHYSICS REPLAY</span><div class="readout" data-status="idle">TRIANGULATE THE MARKED ARTIFACT</div></div><button class="claw-submit">${
      clean(state.submit_label)
    }</button></footer>${helpers.cheatPanelTemplate()}</section>`;
    model = {
      state,
      helpers,
      interaction,
      events: [],
      position: [...state.initial.position],
      velocity: [...state.initial.velocity],
      objects: Object.fromEntries(
        state.objects.map(
          (obj) => [obj.id, { ...obj, center: [...obj.center] }],
        ),
      ),
      gripper: "open",
      captured: null,
      delivered: false,
      terminal: false,
      submitting: false,
      tick: 0,
      collisions: 0,
      resets: 0,
      history: {},
      held: new Set(),
      startedAt: performance.now(),
      chute: structuredClone(state.chute),
    };
    updateHistory();
    window.threeCameraClawMachineModel = model;
    document.querySelectorAll('.claw-control').forEach(button => {
      button.addEventListener('pointerdown', e => {
        button.setPointerCapture(e.pointerId);
        applyControl(button.dataset.axis, Number(button.dataset.direction), true, 'control_buttons');
      });
      for (const event of ['pointerup', 'pointercancel', 'lostpointercapture'])
        button.addEventListener(event, () => applyControl(button.dataset.axis, Number(button.dataset.direction), false, 'control_buttons'));
    });
    document.querySelector(".claw-grip")?.addEventListener("click", () => grip("control_buttons"));
    document.querySelector(".claw-submit").addEventListener("click", submit);
    keyHandler = (event) => {
      if (event.repeat || model?.interaction !== "full" || model.submitting || model.terminal) return;
      const key = event.key.toLowerCase();
      const directions = {
        a: ["x", -1], d: ["x", 1], w: ["y", 1], s: ["y", -1],
        q: ["z", -1], e: ["z", 1],
      };
      if (directions[key]) {
        event.preventDefault();
        applyControl(...directions[key], true, "keyboard");
      } else if (key === "f") {
        event.preventDefault();
        grip("keyboard");
      }
    };
    keyUpHandler = event => {
      if (model?.interaction !== 'full') return;
      const direction = {a:['x',-1], d:['x',1], w:['y',1], s:['y',-1], q:['z',-1], e:['z',1]}[event.key.toLowerCase()];
      if (direction) { event.preventDefault(); applyControl(...direction, false, 'keyboard'); }
    };
    window.addEventListener("keydown", keyHandler);
    window.addEventListener('keyup', keyUpHandler);
    helpers.installCheatPanel();
    drawFeeds();
    updateHUD();
    animationFrame = requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.three_camera_claw_machine_v2 = {
    rootSelector: ".claw-captcha",
    render,
  };
})();
