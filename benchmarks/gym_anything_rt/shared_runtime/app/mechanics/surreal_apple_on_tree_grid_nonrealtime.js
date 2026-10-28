(() => {
  "use strict";

  let model = null;
  const motionUrl = new URL('realtime_four_motion.js', document.currentScript.src).href;
  const DEFAULT_ACTION_STEP_MS = 120;
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const round2 = (value) => Math.round(Number(value) * 100) / 100;
  const clean = (value) => String(value == null ? "" : value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const sector = (angle) => angle < -36 ? 0 : angle < -12 ? 1 : angle < 12 ? 2 : angle < 36 ? 3 : 4;
  class HarvestPhysics {
    constructor(state) {
      this.state = state; this.spec = state.flight; this.ms = 0;
      this.x = state.basket.x + state.basket.width / 2; this.target = this.x; this.velocity = 0;
      this.falling = {}; this.released = new Set(); this.caught = new Set(); this.failed = '';
    }
    release(apple, point, previous) {
      this.released.add(apple.id);
      this.falling[apple.id] = {x: point[0], y: point[1], vx: clamp((point[0]-previous[0])*50,-190,190), vy: 0, radius: apple.radius};
    }
    advance(end) {
      while (this.ms + 10 <= end && !this.failed) {
        this.ms += 10;
        const before = this.x, s = this.spec, half = this.state.basket.width/2;
        const acceleration = clamp((this.target-this.x)*60-this.velocity*14,-s.basket_acceleration,s.basket_acceleration);
        this.velocity = clamp(this.velocity+acceleration*.01,-s.basket_speed,s.basket_speed);
        this.x = clamp(this.x+this.velocity*.01,half+12,948-half);
        if (this.x === half+12 || this.x === 948-half) this.velocity = 0;
        const wind = s.wind_acceleration * RealtimeFourMotion.motion(s.seed,this.ms,s.wind_span_ms);
        for (const [id,f] of Object.entries(this.falling)) {
          const x=f.x, y=f.y, r=f.radius;
          f.vx += (wind-.1*f.vx)*.01; f.vy += s.gravity*.01;
          f.x += f.vx*.01; f.y += f.vy*.01;
          if (f.x < r+12 || f.x > 948-r) { f.x=clamp(f.x,r+12,948-r); f.vx *= -.6; }
          if (y+r < s.rim_y && f.y+r >= s.rim_y) {
            const fraction=(s.rim_y-r-y)/(f.y-y);
            const impact=x+(f.x-x)*fraction, basket=before+(this.x-before)*fraction;
            if (Math.abs(impact-basket)+r <= half) { this.caught.add(id); delete this.falling[id]; }
            else { this.failed='A falling fruit missed the basket.'; break; }
          }
        }
      }
    }
  }
  window.OrchardHarvestPhysics = HarvestPhysics;
  function record(kind, details = {}) { const event = {sequence: model.events.length + 1, kind, t_ms: model.currentMs, ...details}; model.events.push(event); return event; }
  function syncScene() {
    for (const apple of model.state.apples) {
      const offset = RealtimeFourMotion.vector(model.state.wind[apple.id], model.currentMs);
      apple.position = model.baseApples[apple.id].position.map((x, i) => x + offset[i]);
      const branch = model.state.branches.find(b => b.fruit_id === apple.id);
      branch.points = model.baseBranches[apple.id].points.map((point, j) => point.map((x, i) => x + offset[i] * j / 3));
    }
    model.physics.advance(model.currentMs);
    model.state.basket = {...model.baseBasket, x: model.physics.x-model.baseBasket.width/2};
    model.plucked = model.physics.caught;
  }
  function advanceForAction() {
    if (!model.harvestStarted) { syncScene(); return true; }
    model.currentMs += Number(model.state.flight.action_step_ms || DEFAULT_ACTION_STEP_MS);
    syncScene();
    if (model.physics.failed && !model.strikeActive) {
      model.strikeActive = true; model.hold = null;
      model.helpers.setReadout(model.physics.failed, 'error');
      updateInterface(); submit();
      return false;
    }
    return true;
  }
  function stagePoint(event) { const rect = document.getElementById("orchard-canvas").getBoundingClientRect(); return [round2(clamp((event.clientX - rect.left) / rect.width * model.state.stage.width, 0, model.state.stage.width)), round2(clamp((event.clientY - rect.top) / rect.height * model.state.stage.height, 0, model.state.stage.height))]; }

  function project(point, angle = model.angle) {
    const radians = angle * Math.PI / 180, [x, y, z] = point;
    return [430 + x * Math.cos(radians) + z * Math.sin(radians), 246 + y + .10 * z * Math.cos(radians) - .05 * x * Math.sin(radians)];
  }
  function depth(point, angle = model.angle) { const radians = angle * Math.PI / 180; return point[2] * Math.cos(radians) - point[0] * Math.sin(radians); }
  function exploredEnough() {
    const r = model.state.requirements;
    const span = Math.max(...model.angles) - Math.min(...model.angles);
    const travel = model.angles.slice(1).reduce((sum, angle, index) => sum + Math.abs(angle - model.angles[index]), 0);
    return span >= r.minimum_orbit_span_deg && travel >= r.minimum_orbit_travel_deg && model.sectors.size >= r.minimum_view_sectors;
  }
  function stats() {
    const span = round2(Math.max(...model.angles) - Math.min(...model.angles));
    const travel = round2(model.angles.slice(1).reduce((sum, angle, index) => sum + Math.abs(angle - model.angles[index]), 0));
    return {span, travel};
  }

  function drawBranch(context, branch) {
    const points = branch.points.map((point) => project(point));
    context.beginPath(); context.moveTo(points[0][0], points[0][1]); points.slice(1).forEach((point) => context.lineTo(point[0], point[1]));
    context.strokeStyle = "#3e241b"; context.lineWidth = 13; context.lineCap = "round"; context.lineJoin = "round"; context.stroke();
    context.strokeStyle = "#9a6040"; context.lineWidth = 4; context.stroke();
  }
  function drawFruit(context, apple) {
    if (model.physics.released.has(apple.id)) return;
    const center = project(apple.position), stemTop = project([apple.position[0], apple.position[1] - 28, apple.position[2]]), radius = Number(apple.radius);
    context.beginPath(); context.moveTo(center[0], center[1] - radius * .45); context.lineTo(stemTop[0], stemTop[1]); context.strokeStyle = "#3a2718"; context.lineWidth = 5; context.lineCap = "round"; context.stroke();
    const palette = apple.hue === "gold" ? ["#ffd569", "#bf6a24"] : apple.hue === "rose" ? ["#ff7b82", "#9b273d"] : ["#ec4150", "#741d2a"];
    const gradient = context.createRadialGradient(center[0] - radius * .32, center[1] - radius * .36, 2, center[0], center[1], radius * 1.25);
    gradient.addColorStop(0, palette[0]); gradient.addColorStop(1, palette[1]);
    context.beginPath(); context.ellipse(center[0], center[1], radius, radius * .92, 0, 0, Math.PI * 2); context.fillStyle = gradient; context.shadowColor = "rgba(48,12,18,.45)"; context.shadowBlur = 12; context.fill(); context.shadowBlur = 0;
    context.beginPath(); context.ellipse(center[0] - radius * .25, center[1] - radius * .28, radius * .16, radius * .25, -.6, 0, Math.PI * 2); context.fillStyle = "rgba(255,255,255,.34)"; context.fill();
    if (apple.scar) { context.fillStyle = "rgba(74,22,22,.62)"; context.fillRect(center[0] + radius * .25, center[1] + radius * .05, 3 + apple.scar, 2); }
  }
  function drawBasket(context) {
    const basket = model.state.basket;
    context.save(); context.fillStyle = "rgba(73,41,23,.88)"; context.strokeStyle = "#e4ad64"; context.lineWidth = 4;
    context.beginPath(); context.moveTo(basket.x, basket.y); context.lineTo(basket.x + basket.width, basket.y); context.lineTo(basket.x + basket.width - 14, basket.y + basket.height); context.lineTo(basket.x + 14, basket.y + basket.height); context.closePath(); context.fill(); context.stroke();
    context.strokeStyle = "rgba(248,203,126,.48)"; context.lineWidth = 2; for (let y = basket.y + 43; y < basket.y + basket.height; y += 20) { context.beginPath(); context.moveTo(basket.x + 20, y); context.lineTo(basket.x + basket.width - 20, y); context.stroke(); }
    context.fillStyle = "#f1c177"; context.font = "900 10px Courier New"; context.textAlign = "center"; context.fillText(`CAUGHT ${model.plucked.size}/${model.attached.size}`, basket.x + basket.width / 2, basket.y + 28); context.restore();
  }
  function draw() {
    if (!model) return;
    const canvas = document.getElementById("orchard-canvas"), context = canvas?.getContext("2d"); if (!canvas || !context) return;
    const sky = context.createLinearGradient(0, 0, 0, canvas.height); sky.addColorStop(0, "#101c30"); sky.addColorStop(.62, "#273d3b"); sky.addColorStop(1, "#17251e"); context.fillStyle = sky; context.fillRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "rgba(172,218,190,.10)"; context.lineWidth = 1; const shift = model.angle * 2.2; for (let x = -220; x < canvas.width + 220; x += 55) { context.beginPath(); context.moveTo(x + shift, 368); context.lineTo(430 + (x - 430) * .2, 246); context.stroke(); }
    context.beginPath(); context.ellipse(430, 430, 410, 58, 0, 0, Math.PI * 2); context.fillStyle = "rgba(7,15,14,.42)"; context.fill();
    context.beginPath(); context.moveTo(396, 390); context.bezierCurveTo(402, 302, 388, 218, 418, 132); context.bezierCurveTo(451, 216, 445, 314, 468, 390); context.closePath(); context.fillStyle = "#54301f"; context.fill(); context.strokeStyle = "#a0633f"; context.lineWidth = 5; context.stroke();
    const items = [];
    model.state.branches.forEach((branch) => items.push({kind: "branch", depth: branch.points.reduce((sum, p) => sum + depth(p), 0) / branch.points.length, value: branch}));
    model.state.apples.forEach((apple) => items.push({kind: "fruit", depth: depth(apple.position), value: apple}));
    items.sort((a, b) => a.depth - b.depth).forEach((item) => item.kind === "branch" ? drawBranch(context, item.value) : drawFruit(context, item.value));
    context.strokeStyle='#68857a'; context.lineWidth=3;
    context.strokeRect(12,36,936,478);
    context.beginPath(); context.moveTo(14,506); context.lineTo(946,506); context.stroke();
    for (const [id,f] of Object.entries(model.physics.falling)) {
      context.strokeStyle='rgba(245,232,177,.5)'; context.lineWidth=3;
      context.beginPath(); context.moveTo(f.x-f.vx*.10,f.y-f.vy*.10); context.lineTo(f.x,f.y); context.stroke();
      context.fillStyle=model.appleMap[id].hue==='gold'?'#f5b946':'#e94d61';
      context.beginPath(); context.arc(f.x,f.y,f.radius,0,Math.PI*2); context.fill();
    }
    drawBasket(context);
    const wind=RealtimeFourMotion.motion(model.state.flight.seed,model.currentMs,model.state.flight.wind_span_ms);
    context.strokeStyle='#afdad1'; context.lineWidth=4;
    context.beginPath(); context.moveTo(810,52); context.lineTo(810+wind*85,52); context.stroke();
    context.fillStyle='#afdad1'; context.font='12px Courier New'; context.fillText('WIND',780,35);
    context.fillStyle = "rgba(219,239,224,.76)"; context.font = "800 9px Courier New"; context.textAlign = "left"; context.fillText(`ORBIT ${model.angle > 0 ? "+" : ""}${Math.round(model.angle)}°`, 22, 28);
  }

  function updateInterface() {
    if (!model) return; const root = document.querySelector(".parallax-orchard"), s = stats(), ready = exploredEnough();
    root.dataset.ready = ready ? "true" : "false"; root.dataset.strike = model.strikeActive ? "true" : "false"; root.dataset.completed = model.plucked.size === model.attached.size ? "true" : "false";
    document.getElementById("orchard-angle").textContent = `${model.angle > 0 ? "+" : ""}${Math.round(model.angle)}°`;
    document.getElementById("orchard-span").textContent = `${Math.round(s.span)}°`;
    document.getElementById("orchard-views").textContent = `${model.sectors.size}/5`;
    document.getElementById("orchard-count").textContent = `${model.plucked.size}/${model.attached.size}`;
    const instruction = document.getElementById("orchard-status");
    if (model.strikeActive) instruction.textContent = "FAIL — HARVEST ENDED";
    else if (model.plucked.size === model.attached.size) instruction.textContent = "ALL TRUE STEMS HARVESTED";
    else if (Object.keys(model.physics.falling).length) instruction.textContent = "FRUIT FALLING — STEER THE BASKET";
    else if (ready) instruction.textContent = "PLUCK A JOINED FRUIT — CATCH IT BEFORE IT HITS THE GROUND";
    else instruction.textContent = model.interaction === "simplified" ? "USE ORBIT BUTTONS TO EXPOSE DEPTH" : "DRAG THE ORCHARD LEFT AND RIGHT TO EXPOSE DEPTH";
    draw();
  }

  function hitApple(point) {
    const candidates = model.state.apples.filter((apple) => !model.physics.released.has(apple.id)).map((apple) => ({apple, center: project(apple.position), depth: depth(apple.position)})).filter((item) => distance(point, item.center) <= Number(item.apple.radius) + 8).sort((a, b) => b.depth - a.depth);
    return candidates[0]?.apple || null;
  }
  function pointerDown(event) {
    if (!model || model.submitting || model.terminal || model.hold) return;
    if (!advanceForAction() || model.strikeActive) return;
    const point=stagePoint(event), b=model.state.basket;
    if (model.interaction==='simplified' && point[1]>=430) {
      model.physics.target=point[0];
      record('basket_target',{point,input_source:'basket_click'});
    } else if (model.interaction==='full' && point[0]>=b.x && point[0]<=b.x+b.width && point[1]>=b.y && point[1]<=b.y+b.height) {
      model.hold={kind:'basket',pointerId:event.pointerId};
      record('basket_start',{point,input_source:'basket_drag'});
    } else {
      const apple=exploredEnough()?hitApple(point):null;
      if (apple) {
        const offset=RealtimeFourMotion.vector(model.state.wind[apple.id],Math.max(0,model.currentMs-20));
        const previous=project(model.baseApples[apple.id].position.map((x,i)=>x+offset[i]));
        record('release',{apple_id:apple.id,point,input_source:model.interaction==='full'?'fruit_pluck':'fruit_click'});
        model.physics.release(apple,project(apple.position),previous);
        model.harvestStarted = true;
        if (!model.attached.has(apple.id)) {
          model.physics.failed='A false stem was plucked.'; model.strikeActive=true;
          updateInterface(); submit(); return;
        }
      } else if (model.interaction==='full' && !Object.keys(model.physics.falling).length) {
        model.hold={kind:'orbit',pointerId:event.pointerId,start:point,last:point,baseAngle:model.angle};
        record('orbit_start',{point,angle_before:model.angle,input_source:'canvas_drag'});
      }
    }
    if (model.hold) event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault(); updateInterface();
  }
  function pointerMove(event) {
    if (!model?.hold || model.hold.pointerId!==event.pointerId || model.submitting || model.terminal) return;
    const point=stagePoint(event);
    if (model.hold.kind==='orbit' && distance(point,model.hold.last)<2) return;
    if (!advanceForAction() || !model.hold) return;
    if (model.hold.kind==='basket') {
      model.physics.target=point[0];
      record('basket_move',{point,input_source:'basket_drag'});
    } else {
      model.angle=round2(clamp(model.hold.baseAngle+(point[0]-model.hold.start[0])*.24,-model.state.view_limit_deg,model.state.view_limit_deg));
      model.hold.last=point; model.orbitSamples+=1; model.angles.push(model.angle); model.sectors.add(sector(model.angle));
      record('orbit_move',{point,angle_after:model.angle,input_source:'canvas_drag'});
    }
    updateInterface(); event.preventDefault();
  }
  function pointerUp(event) {
    if (!model?.hold || model.hold.pointerId!==event.pointerId || model.submitting || model.terminal) return;
    if (!advanceForAction() || !model.hold) return;
    const point=stagePoint(event), hold=model.hold; model.hold=null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    if (hold.kind==='basket') record('basket_end',{point,input_source:'basket_drag'});
    else record('orbit_end',{point,angle:model.angle,input_source:'canvas_drag'});
    updateInterface();
  }
  function orbitStep(delta) {
    if (!model || model.interaction !== "simplified" || model.hold || model.submitting || model.terminal || Object.keys(model.physics.falling).length) return;
    const before = model.angle; model.angle = round2(clamp(before + Number(delta), -model.state.view_limit_deg, model.state.view_limit_deg)); model.orbitSamples += 1; model.angles.push(model.angle); model.sectors.add(sector(model.angle)); record("orbit_step", {angle_before: before, angle_after: model.angle, input_source: "orbit_buttons"}); model.helpers.setReadout(exploredEnough() ? "DEPTH BASELINE ACQUIRED" : "PARALLAX SWEEP IN PROGRESS", exploredEnough() ? "idle" : "pending"); updateInterface();
  }
  function payload() { const s = stats(); return {physics_revision:'falling-harvest-v1', mechanic_id: model.state.mechanic_id, task_id: model.state.task_id, challenge_id: model.state.challenge_id, events: model.events, final_angle_deg: model.angle, orbit_samples: model.orbitSamples, orbit_span_deg: s.span, orbit_travel_deg: s.travel, view_sector_count: model.sectors.size, plucked_ids: [...model.plucked].sort(), invalid_plucks: model.invalidPlucks, reset_count: model.resetCount, seal_count: model.sealCount, completed: model.plucked.size === model.attached.size && !model.strikeActive}; }
  async function submit() {
    if (!model || model.submitting || model.terminal || model.hold?.kind==='orbit') return; record("seal"); model.sealCount += 1; const current = model; current.submitting = true; current.helpers.setReadout("REPLAYING CAMERA PARALLAX AND HARVEST GEOMETRY…", "pending");
    try { const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(payload())}); const outcome = await response.json(); if (outcome.passed === true) { current.terminal = true; current.helpers.setReadout("PASS", "passed"); const verdict = document.querySelector(".orchard-verdict"); if (verdict) verdict.innerHTML = "<b>PASS</b><span>TRUE DEPTH CONTACTS VERIFIED</span>"; document.querySelector(".parallax-orchard")?.setAttribute("data-verdict", "pass"); } else if (outcome.passed === false) { current.terminal = true; document.querySelector(".parallax-orchard").dataset.verdict = "fail"; current.helpers.setReadout("FAIL · ATTEMPT ENDED", "error"); document.querySelector(".orchard-verdict").innerHTML = "<b>FAIL</b><span>HARVEST ENDED</span>"; } else { current.submitting = false; current.helpers.setReadout("HARVEST REJECTED", "error"); } } catch (_error) { if (model === current) { current.submitting = false; current.helpers.setReadout("ORCHARD VERIFIER OFFLINE", "error"); } }
  }

  async function render(state, helpers, options = {}) {
    await import(motionUrl);
    document.body.dataset.mechanic = "parallax-orchard"; document.body.dataset.cheatMode = helpers.isCheatMode() ? "true" : "false";
    const interaction = state.control_condition?.interaction || "full";
    model = {state, helpers, interaction, appleMap: Object.fromEntries(state.apples.map((apple) => [apple.id, apple])), attached: new Set(), angle: Number(state.initial_angle_deg), angles: [Number(state.initial_angle_deg)], sectors: new Set([sector(Number(state.initial_angle_deg))]), orbitSamples: 0, events: [], hold: null, plucked: new Set(), invalidPlucks: 0, strikeActive: false, resetCount: 0, sealCount: 0, submitting: false, terminal: false, harvestStarted: false, currentMs: 0}; window.parallaxOrchardModel = model;
    model.baseApples = Object.fromEntries(state.apples.map(a => [a.id, structuredClone(a)]));
    model.baseBranches = Object.fromEntries(state.branches.map(b => [b.fruit_id, structuredClone(b)]));
    model.baseBasket = structuredClone(state.basket);
    model.physics = new HarvestPhysics(structuredClone(state));
    // Attachment is derived from exact 3-D branch/stem contact, not a public
    // answer flag. This is also what the player sees after orbiting.
    const branchByFruit = Object.fromEntries(state.branches.map((branch) => [branch.fruit_id, branch])); state.apples.forEach((apple) => { const tip = branchByFruit[apple.id].points.at(-1); if (Math.abs(tip[2] - apple.position[2]) < .01) model.attached.add(apple.id); });
    const gesture = interaction === "simplified" ? "CLICK FRUIT TO PLUCK<br>CLICK RAIL TO STEER" : "CLICK FRUIT TO PLUCK<br>DRAG BASKET TO CATCH";
    const orbitControls = interaction === "simplified" ? `<div class="orchard-orbit-controls"><button id="orchard-orbit-left">ORBIT LEFT</button><button id="orchard-orbit-right">ORBIT RIGHT</button></div>` : "";
    helpers.app.innerHTML = `<section class="parallax-orchard" data-interaction="${clean(interaction)}" data-fresh-failure="${options.freshFailure ? "true" : "false"}" data-verdict=""><div class="orchard-verdict"><b>${options.freshFailure ? "FAIL" : ""}</b><span>${options.freshFailure ? "FRESH ORCHARD ISSUED" : ""}</span></div><header class="orchard-head"><div><span>PARALLAX ORCHARD / ${clean(state.challenge_id)}</span><h1>${clean(state.prompt)}</h1></div><div class="orchard-dial"><span>VIEW</span><b id="orchard-angle">0°</b><i></i></div></header><main class="orchard-main"><section class="orchard-stage"><canvas id="orchard-canvas" width="${state.stage.width}" height="${state.stage.height}"></canvas><div class="orbit-gesture"><i>↔</i><span>${gesture}</span></div></section><aside class="orchard-console"><span>DEPTH NOTE</span><h2>Projection lies.<br>Parallax does not.</h2><div class="orchard-rule"></div><dl><div><dt>BASELINE</dt><dd id="orchard-span">0°</dd></div><div><dt>VIEWS</dt><dd id="orchard-views">1/5</dd></div><div><dt>CAUGHT</dt><dd id="orchard-count">0/${model.attached.size}</dd></div></dl><p>Inspect from several angles. Click a joined fruit to release it. Wind changes its fall. ${interaction === "full" ? "Drag the basket" : "Click the bottom rail"} to catch it.</p><p>A false stem or missed catch ends the harvest. The basket takes time to move. The view stays fixed while fruit falls.</p>${orbitControls}</aside></main><footer class="orchard-foot"><div><span id="orchard-status">${interaction === "simplified" ? "USE ORBIT BUTTONS TO EXPOSE DEPTH" : "DRAG THE ORCHARD LEFT AND RIGHT TO EXPOSE DEPTH"}</span><div class="readout" data-status="idle">ORBIT LOCK RELEASED</div></div><button id="orchard-submit">${clean(state.submit_label)}</button></footer>${helpers.cheatPanelTemplate()}</section>`;
    const canvas = document.getElementById("orchard-canvas"); canvas.addEventListener("pointerdown", pointerDown); canvas.addEventListener("pointermove", pointerMove); canvas.addEventListener("pointerup", pointerUp); canvas.addEventListener("pointercancel", pointerUp); document.getElementById("orchard-orbit-left")?.addEventListener("click", () => orbitStep(-6)); document.getElementById("orchard-orbit-right")?.addEventListener("click", () => orbitStep(6)); document.getElementById("orchard-submit").addEventListener("click", submit); helpers.installCheatPanel(); updateInterface();
    syncScene(); updateInterface();
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.surreal_apple_on_tree_grid_nonrealtime = {rootSelector: ".parallax-orchard", render};
})();
