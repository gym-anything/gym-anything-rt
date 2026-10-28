(() => {
  "use strict";

  let helpersCache = null;
  let model = null;
  let keyHandler = null;
  let animationFrame = null;
  const TARGET_RADIUS_PX = Object.freeze({seed: 12, brood: 15, front: 16, queen: 18});
  const TUNNEL_HALF_WIDTH_PX = 8;
  const ANT_HIT_RADIUS_PX = 12;

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function livingIds() { return [...model.sim.workers, ...model.sim.soldiers]; }

  function interceptLane(raid, tick) {
    const phase = Number(raid.motion_phase_offset_ticks || 0) * Math.PI * 2 / 36;
    const seededSign = raid.lane === "south" ? 1 : -1;
    return seededSign * Math.cos(phase) >= 0 ? "south" : "north";
  }

  function initialSimulation(world) {
    const workers = (world.workers || []).map((unit) => String(unit.id));
    const orders = {};
    const orderStarted = {};
    workers.forEach((unitId) => { orders[unitId] = "idle"; orderStarted[unitId] = 0; });
    return {
      tick: 0,
      seeds: Number(world.initial_seeds),
      brood_ready: Boolean(world.brood_ready),
      brood_progress: world.brood_ready ? Number(world.dig_work) : 0,
      queen_hp: Number(world.home_queen.hp),
      enemy_queen_hp: Number(world.enemy_queen.hp),
      workers,
      soldiers: [],
      orders,
      order_started: orderStarted,
      scout_id: null,
      scout_started: null,
      opening_revealed: !world.hidden_opening,
      production: [],
      next_soldier: 1,
      assault_at: {},
      attacked: [],
      rival_outposts_ready: [],
      defense_commitments: {},
      successful_intercepts: [],
      resolved_waves: [],
      units_lost: 0,
      terminal: false,
      won: false,
    };
  }

  function stepSimulation() {
    const sim = model.sim;
    const world = model.world;
    if (sim.terminal) return;
    sim.tick += 1;
    const tick = sim.tick;
    if (!sim.opening_revealed && sim.scout_started !== null) {
      const scoutId = sim.scout_id;
      if (!sim.workers.includes(scoutId) || sim.orders[scoutId] !== "scout") {
        sim.scout_id = null; sim.scout_started = null;
      } else if (tick - sim.scout_started >= Number(world.scout_ticks)) {
        sim.opening_revealed = true;
        sim.orders[scoutId] = "gather"; sim.order_started[scoutId] = tick;
        sim.scout_id = null; sim.scout_started = null;
      }
    }

    if (!sim.brood_ready) {
      const diggers = sim.workers.filter((unitId) => sim.orders[unitId] === "dig");
      if (diggers.length === Number(world.dig_workers)) sim.brood_progress += diggers.length;
      if (sim.brood_progress >= Number(world.dig_work)) {
        sim.brood_progress = Number(world.dig_work);
        sim.brood_ready = true;
        diggers.forEach((unitId) => { sim.orders[unitId] = "gather"; sim.order_started[unitId] = tick; });
      }
    }

    const cycle = Number(world.gather_cycle_ticks);
    sim.workers.forEach((unitId) => {
      if (sim.orders[unitId] !== "gather") return;
      const elapsed = tick - Number(sim.order_started[unitId] || 0);
      if (elapsed > 0 && elapsed % cycle === 0) sim.seeds += 1;
    });

    const ready = sim.production.filter((item) => Number(item.ready_tick) <= tick);
    sim.production = sim.production.filter((item) => Number(item.ready_tick) > tick);
    ready.forEach(() => {
      const unitId = `S${sim.next_soldier}`;
      sim.next_soldier += 1;
      sim.soldiers.push(unitId);
      sim.orders[unitId] = "rally";
      sim.order_started[unitId] = tick;
    });

    world.raids.forEach((raid) => {
      const wave = Number(raid.wave);
      if (!sim.rival_outposts_ready.includes(wave) && tick >= Number(raid.expand_complete_tick)) sim.rival_outposts_ready.push(wave);
    });

    world.raids.forEach((raid) => {
      const wave = Number(raid.wave);
      if (sim.resolved_waves.includes(wave) || tick < Number(raid.impact_tick) || sim.terminal) return;
      const commitment = sim.defense_commitments[wave];
      if (!commitment || tick < Number(commitment.resolve_tick || raid.impact_tick)) return;
      if (!sim.rival_outposts_ready.includes(wave)) throw new Error("rival raid reached impact before its outpost was completed");
      const defenders = commitment && commitment.correct
        ? commitment.unit_ids.filter((unitId) => sim.soldiers.includes(unitId) && sim.orders[unitId] === commitment.lane).sort()
        : [];
      const count = Number(raid.count);
      const stopped = Math.min(defenders.length, count);
      const losses = Math.min(stopped, Math.floor((count + 2) / 3));
      defenders.slice(0, losses).forEach((unitId) => {
        sim.soldiers = sim.soldiers.filter((item) => item !== unitId);
        delete sim.orders[unitId]; delete sim.order_started[unitId]; delete sim.assault_at[unitId];
        sim.units_lost += 1;
        model.selected.delete(unitId);
      });
      sim.queen_hp -= count - stopped;
      if (stopped === count) sim.successful_intercepts.push(wave);
      sim.resolved_waves.push(wave);
      if (sim.queen_hp <= 0) { sim.queen_hp = 0; sim.terminal = true; sim.won = false; }
    });

    [...sim.soldiers].sort().forEach((unitId) => {
      const due = sim.assault_at[unitId];
      if (due === undefined || sim.attacked.includes(unitId) || tick < Number(due) || sim.terminal) return;
      sim.attacked.push(unitId);
      sim.enemy_queen_hp -= 1;
      if (sim.enemy_queen_hp <= 0) {
        sim.enemy_queen_hp = 0;
        sim.terminal = true;
        sim.won = sim.successful_intercepts.length === world.raids.length;
      }
    });
    if (tick >= Number(world.max_ticks) && !sim.terminal) { sim.terminal = true; sim.won = false; }
  }

  function applyAction(action, unitIds, target, inputSource) {
    advanceToNow();
    if (!model || model.sim.terminal || model.submitting) return false;
    const sim = model.sim;
    const world = model.world;
    const workers = new Set(sim.workers);
    const soldiers = new Set(sim.soldiers);
    const ids = [...new Set(unitIds)].filter((unitId) => livingIds().includes(unitId));
    const tick = sim.tick;
    let valid = false;
    let detail = "";
    const cancelSelectedScout = () => {
      if (sim.scout_id !== null && ids.includes(sim.scout_id) && sim.orders[sim.scout_id] === "scout") {
        sim.scout_id = null; sim.scout_started = null; detail = " · SCOUT ABORTED";
      }
    };
    if (action === "GATHER" && target === "seed" && ids.length && ids.every((id) => workers.has(id))) {
      cancelSelectedScout();
      ids.forEach((id) => { sim.orders[id] = "gather"; sim.order_started[id] = tick; }); valid = true;
    } else if (action === "SCOUT" && target === "front" && ids.length === 1 && workers.has(ids[0])) {
      if (!sim.opening_revealed && sim.scout_id === null) {
        sim.orders[ids[0]] = "scout"; sim.order_started[ids[0]] = tick; sim.scout_id = ids[0]; sim.scout_started = tick; valid = true;
      }
    } else if (action === "DIG" && target === "brood" && Number(world.dig_workers) > 0 && ids.length === Number(world.dig_workers) && ids.every((id) => workers.has(id))) {
      cancelSelectedScout();
      sim.workers.forEach((id) => {
        if (sim.orders[id] === "dig" && !ids.includes(id)) { sim.orders[id] = "gather"; sim.order_started[id] = tick; }
      });
      ids.forEach((id) => { sim.orders[id] = "dig"; sim.order_started[id] = tick; }); valid = true;
    } else if (action === "RAISE" && target === "brood" && ids.length === 0 && sim.brood_ready && sim.seeds >= Number(world.soldier_cost)) {
      sim.seeds -= Number(world.soldier_cost); sim.production.push({ready_tick: tick + Number(world.production_ticks)}); valid = true;
    } else if (action === "MARCH" && ["north", "south", "enemy"].includes(target) && ids.length && ids.every((id) => soldiers.has(id))) {
      const allCleared = sim.resolved_waves.length === world.raids.length;
      if (target === "enemy") {
        if (allCleared) valid = true;
      } else if (sim.opening_revealed) {
        const active = world.raids
          .filter((raid) => !sim.resolved_waves.includes(Number(raid.wave))
            && !Object.prototype.hasOwnProperty.call(sim.defense_commitments, Number(raid.wave))
            && tick >= Number(raid.response_open_tick))
          .sort((a, b) => Number(a.wave) - Number(b.wave));
        if (active.length) {
          const reserved = new Set();
          Object.entries(sim.defense_commitments).forEach(([wave, commitment]) => {
            if (!sim.resolved_waves.includes(Number(wave))) commitment.unit_ids.forEach((id) => reserved.add(id));
          });
          if (!ids.some((id) => reserved.has(id))) {
            const raid = active[0];
            sim.defense_commitments[Number(raid.wave)] = {
              tick,
              lane: target,
              unit_ids: [...ids],
              correct: target === interceptLane(raid, tick),
              resolve_tick: Math.max(Number(raid.impact_tick), tick + 1),
            };
            detail = ` · W${raid.wave} COMMITTED`;
            valid = true;
          }
        }
      }
      if (valid) ids.forEach((id) => {
        sim.orders[id] = target; sim.order_started[id] = tick;
        if (target === "enemy") sim.assault_at[id] = tick + Number(world.assault_travel_ticks); else delete sim.assault_at[id];
      });
    }
    if (!valid) { setReadout("ORDER REJECTED · CHECK SELECTION / DESTINATION", "error"); return false; }
    model.events.push({sequence: model.events.length + 1, tick, action, unit_ids: ids, target, input_source: inputSource});
    setReadout(`${action} → ${target.toUpperCase()} · ${ids.length || 1} ORDERED${detail}`, "idle");
    updateHud(); draw();
    return true;
  }

  function finalSummary() {
    const sim = model.sim;
    return {
      tick: sim.tick, seeds: sim.seeds, brood_ready: sim.brood_ready, brood_progress: sim.brood_progress,
      queen_hp: sim.queen_hp, enemy_queen_hp: sim.enemy_queen_hp, worker_count: sim.workers.length,
      soldier_count: sim.soldiers.length, units_lost: sim.units_lost, waves_cleared: sim.resolved_waves.length,
      scout_active: sim.scout_id !== null, intercepts_committed: Object.keys(sim.defense_commitments).length,
      waves_intercepted: sim.successful_intercepts.length,
      rival_outposts_ready: sim.rival_outposts_ready.length,
      opening_revealed: sim.opening_revealed, production_queued: sim.production.length,
      terminal: sim.terminal, won: sim.won,
    };
  }

  function setReadout(message, status) {
    const node = document.getElementById("anthill-readout");
    if (node) { node.textContent = message; node.dataset.status = status || "idle"; }
  }

  function unitWorldPosition(unitId) {
    const sim = model.sim, world = model.world;
    if (unitId.startsWith("W")) {
      const index = Number(unitId.slice(1)) - 1;
      const worker = world.workers.find((item) => String(item.id) === unitId);
      const startX = Number(worker.x);
      const startY = Number(worker.y);
      const order = sim.orders[unitId] || "idle";
      const elapsed = sim.tick - Number(sim.order_started[unitId] || 0);
      if (order === "gather") {
        const phase = (elapsed % Number(world.gather_cycle_ticks)) / Number(world.gather_cycle_ticks);
        const travel = phase < .5 ? phase * 2 : (1 - phase) * 2;
        return [startX + (Number(world.seed_pile.x) - startX) * travel, startY + (Number(world.seed_pile.y) - startY) * travel];
      }
      if (order === "dig") return [Number(world.brood.x) + (index % 2) * .32, Number(world.brood.y) + Math.floor(index / 2) * .28];
      if (order === "scout") {
        const progress = clamp(elapsed / Math.max(1, Number(world.scout_ticks)), 0, 1);
        return [startX + (Number(world.listening_front.x) - startX) * progress, startY + (Number(world.listening_front.y) - startY) * progress];
      }
      return [startX, startY];
    }
    const index = Number(unitId.slice(1)) - 1;
    const order = sim.orders[unitId] || "rally";
    if (order === "north" || order === "south") return [Number(world.defense_post_x) + (index % 4) * .38, Number(world.lane_y[order]) + (Math.floor(index / 4) - .5) * .22];
    if (order === "enemy") {
      const elapsed = sim.tick - Number(sim.order_started[unitId] || 0);
      const progress = clamp(elapsed / Number(world.assault_travel_ticks), 0, 1);
      return [Number(world.rally.x) + (Number(world.enemy_queen.x) - Number(world.rally.x)) * progress, Number(world.rally.y) + (Number(world.enemy_queen.y) - Number(world.rally.y)) * progress + ((index % 3) - 1) * .28];
    }
    return [Number(world.rally.x) + (index % 5) * .35, Number(world.rally.y) - .8 + Math.floor(index / 5) * .32];
  }

  function raidWorldPosition(raid, tick) {
    const start = Number(raid.spawn_tick), impact = Number(raid.impact_tick);
    const progress = clamp((tick - start) / Math.max(1, impact - start), 0, 1);
    const x = Number(raid.outpost.x) + (2.8 - Number(raid.outpost.x)) * progress;
    const open = Number(raid.response_open_tick);
    const center = Number(model.world.home_queen.y);
    const amplitude = (Number(model.world.lane_y.south) - Number(model.world.lane_y.north)) * .42;
    const seededSign = raid.lane === "south" ? 1 : -1;
    const holdProgress = clamp((open - start) / Math.max(1, impact - start), 0, 1);
    const holdX = Number(raid.outpost.x) + (2.8 - Number(raid.outpost.x)) * holdProgress;
    const holdY = Number(model.world.lane_y[interceptLane(raid, open)]);
    if (tick >= open) {
      const commitment = model.sim.defense_commitments[Number(raid.wave)];
      if (!commitment) {
        const revealProgress = clamp((tick - open) / 36, 0, 1);
        if (revealProgress < 1) {
          const phase = (tick - open + Number(raid.motion_phase_offset_ticks || 0)) * Math.PI * 2 / 36;
          const movingY = center + seededSign * amplitude * Math.sin(phase);
          return [holdX, movingY + (holdY - movingY) * revealProgress, holdProgress];
        }
        return [holdX, holdY, holdProgress];
      }
      const settleTick = Number(commitment.resolve_tick || impact);
      const actionTick = Number(commitment.tick);
      const settleProgress = clamp((tick - actionTick) / Math.max(1, settleTick - actionTick), 0, 1);
      const targetY = Number(model.world.lane_y[interceptLane(raid, actionTick)]);
      return [holdX, holdY + (targetY - holdY) * settleProgress, holdProgress];
    }
    let y;
    const approach = clamp((tick - start) / Math.max(1, open - start), 0, 1);
    if (tick < open) {
      y = Number(raid.outpost.y) + (center - Number(raid.outpost.y)) * approach;
    }
    return [x, y, progress];
  }

  function worldToScreen(x, y, rect) {
    const viewWidth = Math.min(Number(model.world.viewport_cells), Number(model.world.width));
    return [(x - model.cameraX) / viewWidth * rect.width, y / Number(model.world.height) * rect.height];
  }
  function laneScreenY(lane, screenX, rect) {
    const base = worldToScreen(0, Number(model.world.lane_y[lane]), rect)[1];
    const phase = screenX / Math.max(1, rect.width) * Math.PI * 2 + (lane === "south" ? .45 : 0);
    return base + Math.sin(phase) * 4;
  }

  function drawAnt(ctx, x, y, color, soldier, selected, scale) {
    ctx.save(); ctx.translate(x, y); ctx.strokeStyle = selected ? "#fff4b0" : color; ctx.fillStyle = color; ctx.lineWidth = selected ? 2.2 : 1.3;
    const r = soldier ? 4.3 : 3.6;
    [[-r * 1.6, 0], [0, 0], [r * 1.55, 0]].forEach(([dx, dy], index) => { ctx.beginPath(); ctx.ellipse(dx, dy, r * (index === 1 ? 1.05 : .85), r * .78, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); });
    ctx.beginPath(); ctx.moveTo(-3, -2); ctx.lineTo(-8, -7); ctx.moveTo(1, -2); ctx.lineTo(7, -8); ctx.moveTo(-3, 2); ctx.lineTo(-8, 7); ctx.moveTo(1, 2); ctx.lineTo(7, 8); ctx.stroke();
    if (soldier) { ctx.fillStyle = "#fff0b2"; ctx.fillRect(3, -5, 6, 2); }
    if (selected) { ctx.strokeStyle = "#fff7bf"; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.arc(0, 0, 12 * scale, 0, Math.PI * 2); ctx.stroke(); }
    ctx.restore();
  }

  function resizeCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(rect.width * ratio) || canvas.height !== Math.round(rect.height * ratio)) {
      canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
    }
    const ctx = canvas.getContext("2d"); ctx.setTransform(ratio, 0, 0, ratio, 0, 0); return [ctx, rect];
  }

  function draw() {
    if (!model) return;
    const canvas = document.getElementById("anthill-world"); if (!canvas) return;
    const [ctx, rect] = resizeCanvas(canvas); const world = model.world, sim = model.sim;
    const viewWidth = Math.min(Number(world.viewport_cells), Number(world.width));
    const cellW = rect.width / viewWidth, cellH = rect.height / Number(world.height);
    const soil = ctx.createLinearGradient(0, 0, 0, rect.height); soil.addColorStop(0, "#6b4229"); soil.addColorStop(.55, "#4e2e20"); soil.addColorStop(1, "#352117"); ctx.fillStyle = soil; ctx.fillRect(0, 0, rect.width, rect.height);
    ctx.strokeStyle = "rgba(246,211,154,.08)"; ctx.lineWidth = 1;
    for (let x = Math.floor(model.cameraX); x <= model.cameraX + viewWidth; x += 1) { const sx = (x - model.cameraX) * cellW; ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, rect.height); ctx.stroke(); }
    for (let y = 0; y <= world.height; y += 1) { ctx.beginPath(); ctx.moveTo(0, y * cellH); ctx.lineTo(rect.width, y * cellH); ctx.stroke(); }

    ["north", "south"].forEach((lane) => {
      ctx.strokeStyle = lane === "north" ? "rgba(238,196,121,.42)" : "rgba(199,155,101,.42)"; ctx.lineWidth = 16;
      ctx.beginPath();
      for (let x = 0; x <= rect.width; x += 12) { const y = laneScreenY(lane, x, rect); if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); }
      ctx.lineTo(rect.width, laneScreenY(lane, rect.width, rect)); ctx.stroke();
      ctx.strokeStyle = "rgba(40,21,14,.7)"; ctx.lineWidth = 2; ctx.setLineDash([10, 10]); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = "rgba(255,235,191,.8)"; ctx.font = "bold 8px Courier New"; ctx.textAlign = "left";
      ctx.fillText(`${lane.toUpperCase()} TUNNEL`, 12, laneScreenY(lane, 12, rect) - 12);
    });
    const branchY = worldToScreen(0, Number(world.home_queen.y), rect)[1]; ctx.strokeStyle = "rgba(226,182,111,.28)"; ctx.lineWidth = 12; ctx.beginPath(); ctx.moveTo(0, branchY); ctx.lineTo(rect.width, branchY); ctx.stroke();

    function marker(item, radius, fill, stroke, label) {
      const [x, y] = worldToScreen(Number(item.x), Number(item.y), rect); if (x < -35 || x > rect.width + 35) return;
      ctx.fillStyle = fill; ctx.strokeStyle = stroke; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#fff2c5"; ctx.font = "bold 8px Courier New"; ctx.textAlign = "center"; ctx.fillText(label, x, y + radius + 12);
    }
    marker(world.seed_pile, TARGET_RADIUS_PX.seed, "#c7963d", "#f7d881", "SEEDS");
    marker(world.brood, TARGET_RADIUS_PX.brood, sim.brood_ready ? "#759a58" : "#493023", sim.brood_ready ? "#b6e28d" : "#c49a70", sim.brood_ready ? `BROOD READY · RAISE ${world.soldier_cost} SEEDS` : "EXCAVATE");
    marker(world.home_queen, TARGET_RADIUS_PX.queen, "#d9a33e", "#ffe4a0", `QUEEN ${sim.queen_hp}`);
    if (!world.hidden_opening || sim.opening_revealed) marker(world.enemy_queen, TARGET_RADIUS_PX.queen, "#a94435", "#f68a72", `RIVAL ${sim.enemy_queen_hp}`);
    marker(world.listening_front, TARGET_RADIUS_PX.front, "#30464b", "#8fd7d2", "LISTENING FRONT");

    world.raids.forEach((raid) => {
      if ((world.hidden_opening && !sim.opening_revealed) || sim.tick < Number(raid.expand_start_tick)) return;
      const start = Number(raid.expand_start_tick), complete = Number(raid.expand_complete_tick);
      const progress = clamp((sim.tick - start) / Math.max(1, complete - start), 0, 1);
      const [x, y] = worldToScreen(Number(raid.outpost.x), Number(raid.outpost.y), rect);
      if (x < -35 || x > rect.width + 35) return;
      const radius = 7 + progress * 7;
      ctx.fillStyle = `rgba(126,45,35,${.28 + progress * .5})`; ctx.strokeStyle = progress >= 1 ? "#f17a60" : "#cf8b69"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.strokeStyle = "rgba(255,190,139,.65)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, radius + 4, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress); ctx.stroke();
      ctx.fillStyle = "#ffd1ad"; ctx.font = "bold 7px Courier New"; ctx.textAlign = "center"; ctx.fillText(progress >= 1 ? `OUTPOST W${raid.wave}` : `BUILD ${Math.floor(progress * 100)}%`, x, y + radius + 11);
    });

    world.raids.forEach((raid, raidIndex) => {
      if ((world.hidden_opening && !sim.opening_revealed) || sim.resolved_waves.includes(Number(raid.wave)) || sim.tick < Number(raid.spawn_tick)) return;
      const [formationX, formationY] = raidWorldPosition(raid, sim.tick);
      const [formationSx, formationSy] = worldToScreen(formationX, formationY, rect);
      const [interceptX, interceptY] = raidWorldPosition(raid, Number(raid.response_open_tick));
      const [interceptSx, interceptSy] = worldToScreen(interceptX, interceptY, rect);
      if (interceptSx > 0 && interceptSx < rect.width) {
        const active = sim.tick >= Number(raid.response_open_tick) && !Object.prototype.hasOwnProperty.call(sim.defense_commitments, Number(raid.wave));
        ctx.strokeStyle = active ? "#fff0a8" : "rgba(255,240,168,.35)"; ctx.lineWidth = active ? 3 : 1; ctx.setLineDash([5, 5]);
        ctx.beginPath(); ctx.moveTo(interceptSx, 18); ctx.lineTo(interceptSx, rect.height - 18); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = active ? "#fff0a8" : "#a78f6f"; ctx.font = "bold 7px Courier New"; ctx.textAlign = "center"; ctx.fillText(`W${raid.wave} INTERCEPT`, interceptSx, 12 + raidIndex * 10);
      }
      for (let i = 0; i < Number(raid.count); i += 1) {
        const xw = formationX + (i % 3) * .24;
        const yw = formationY + (Math.floor(i / 3) - .3) * .35;
        const [x, y] = worldToScreen(xw, yw, rect); if (x > -20 && x < rect.width + 20) drawAnt(ctx, x, y, "#d65b43", true, false, 1);
      }
    });

    livingIds().forEach((unitId) => {
      const [wx, wy] = unitWorldPosition(unitId); const [x, y] = worldToScreen(wx, wy, rect);
      if (x > -20 && x < rect.width + 20) {
        drawAnt(ctx, x, y, unitId.startsWith("W") ? "#e4bd68" : "#f1a932", unitId.startsWith("S"), model.selected.has(unitId), 1);
        if (unitId.startsWith("W") && sim.orders[unitId] === "gather") {
          const elapsed = sim.tick - Number(sim.order_started[unitId] || 0);
          const phase = (elapsed % Number(world.gather_cycle_ticks)) / Number(world.gather_cycle_ticks);
          if (phase >= .5) { ctx.fillStyle = "#ffe076"; ctx.strokeStyle = "#7b5123"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y - 10, 3.2, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); }
        }
      }
    });
    if (model.pendingAction) { ctx.strokeStyle = "#ffeaa7"; ctx.lineWidth = 2; ctx.setLineDash([6,4]); ctx.strokeRect(4,4,rect.width-8,rect.height-8); ctx.setLineDash([]); }
    drawMinimap();
  }

  function drawMinimap() {
    const canvas = document.getElementById("anthill-minimap"); if (!canvas || !model) return;
    const [ctx, rect] = resizeCanvas(canvas); const world = model.world, sim = model.sim;
    ctx.fillStyle = "#3a2418"; ctx.fillRect(0, 0, rect.width, rect.height);
    ["north", "south"].forEach((lane) => { const y = Number(world.lane_y[lane]) / world.height * rect.height; ctx.strokeStyle = "#856043"; ctx.lineWidth = 5; ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(rect.width,y); ctx.stroke(); });
    const point = (x, y, color, size=3) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x/world.width*rect.width,y/world.height*rect.height,size,0,Math.PI*2); ctx.fill(); };
    point(world.home_queen.x, world.home_queen.y, "#f1bb51", 5); point(world.listening_front.x, world.listening_front.y, "#8fd7d2", 4);
    if (!world.hidden_opening || sim.opening_revealed) point(world.enemy_queen.x, world.enemy_queen.y, "#d85a45", 5);
    world.raids.forEach((raid) => { if ((!world.hidden_opening || sim.opening_revealed) && sim.tick >= Number(raid.expand_start_tick)) point(raid.outpost.x, raid.outpost.y, sim.tick >= Number(raid.expand_complete_tick) ? "#f36d54" : "#b87754", 3); });
    livingIds().forEach((id) => { const [x,y] = unitWorldPosition(id); point(x,y,id.startsWith("S") ? "#ffd275" : "#e8c98b",2); });
    world.raids.forEach((raid) => { if ((!world.hidden_opening || sim.opening_revealed) && !sim.resolved_waves.includes(Number(raid.wave)) && sim.tick >= Number(raid.spawn_tick)) { const [x,y]=raidWorldPosition(raid,sim.tick); point(x,y,"#ef604b",3); } });
    const viewWidth = Math.min(Number(world.viewport_cells), Number(world.width)); ctx.strokeStyle = "#fff0b0"; ctx.lineWidth = 1.5; ctx.strokeRect(model.cameraX/world.width*rect.width, 1, viewWidth/world.width*rect.width, rect.height-2);
  }

  function updateRoster() {
    const roster = document.getElementById("anthill-roster");
    if (!roster) return;
    const ids = livingIds();
    const signature = ids.map((id) => `${id}:${model.selected.has(id) ? 1 : 0}:${model.sim.orders[id] || "idle"}`).join("|");
    if (signature === model.rosterSignature) return;
    model.rosterSignature = signature;
    roster.innerHTML = ids.map((id) => {
      const content = `<b>${helpersCache.text(id)}</b><span>${helpersCache.text(model.sim.orders[id] || "idle")}</span>`;
      if (model.interaction === "simplified") return `<button type="button" data-roster-unit="${helpersCache.text(id)}" class="${model.selected.has(id) ? "is-selected" : ""}">${content}</button>`;
      return `<div class="anthill-unit-chip ${model.selected.has(id) ? "is-selected" : ""}">${content}</div>`;
    }).join("");
    if (model.interaction === "simplified") roster.querySelectorAll("[data-roster-unit]").forEach((button) => button.addEventListener("click", () => {
        const id = button.dataset.rosterUnit;
        if (model.selected.has(id)) model.selected.delete(id); else model.selected.add(id);
        model.rosterSignature = null; updateHud(); draw();
      }));
  }

  function updateHud() {
    if (!model) return; const sim=model.sim, world=model.world;
    const set = (id, text) => { const node=document.getElementById(id); if (node) node.textContent=String(text); };
    set("anthill-tick", `${String(sim.tick).padStart(3,"0")} / ${world.max_ticks}`); set("anthill-seeds", sim.seeds); set("anthill-workers", sim.workers.length); set("anthill-soldiers", `${sim.soldiers.length} +${sim.production.length}`); set("anthill-queen", `${sim.queen_hp} HP`); set("anthill-rival", world.hidden_opening && !sim.opening_revealed ? "? HP" : `${sim.enemy_queen_hp} HP`); set("anthill-losses", sim.units_lost);
    const brood = document.getElementById("anthill-brood-state"); if (brood) brood.textContent = sim.brood_ready ? "READY" : `${Math.floor(sim.brood_progress/Math.max(1,world.dig_work)*100)}% DUG`;
    const selection=document.getElementById("anthill-selection"); if(selection) selection.innerHTML=`SELECTED <b>${model.selected.size ? [...model.selected].join(" · ") : "NONE"}</b>`;
    const intel=document.getElementById("anthill-intel-body");
    if (intel) {
      if (!sim.opening_revealed) {
        const progress = sim.scout_started === null ? 0 : clamp((sim.tick - sim.scout_started) / Math.max(1, Number(world.scout_ticks)), 0, 1);
        intel.innerHTML=`<p class="unknown">LISTENING FRONT OFFLINE</p><strong>${sim.scout_id ? `SCOUT ${helpersCache.text(sim.scout_id)} DEPLOYED · ${Math.floor(progress * 100)}%` : "NO CONTACT"}</strong>`;
      } else intel.innerHTML=world.raids.map((raid)=>{
        const wave=Number(raid.wave); let status="SIGNAL QUIET";
        if(sim.resolved_waves.includes(wave)) status="CLEARED";
        else if(Object.prototype.hasOwnProperty.call(sim.defense_commitments,wave)) status="INTERCEPT COMMITTED";
        else if(sim.tick>=Number(raid.response_open_tick)) status="CONTACT READY · HOLDING";
        else if(sim.tick>=Number(raid.spawn_tick)) status="CONTACT APPROACHING";
        else if(sim.tick>=Number(raid.expand_start_tick)) status="OUTPOST BUILDING";
        return `<div class="anthill-wave"><b>W${raid.wave}</b><em>${status}</em><span>${sim.tick>=Number(raid.response_open_tick)&&!sim.resolved_waves.includes(wave)?"VECTOR HELD":"—"}</span></div>`;
      }).join("");
    }
    const cursor=document.getElementById("anthill-command-cursor"); if(cursor) cursor.textContent=model.pendingAction ? `${model.pendingAction}: CLICK DESTINATION` : "";
    const verdict=document.getElementById("anthill-verdict"); const shell=document.querySelector(".anthill-console");
    if(verdict) verdict.textContent=sim.terminal ? (sim.won ? "VICTORY · CERTIFY" : "QUEEN LOST · CERTIFY") : "FRONT LIVE";
    shell?.classList.toggle("is-pass", Boolean(model.passed)); shell?.classList.toggle("is-fail", sim.terminal && !sim.won);
    const certify=document.getElementById("anthill-certify"); certify?.classList.toggle("is-ready", sim.terminal && sim.won);
    updateRoster();
  }

  function markerContains(item, radius, x, y, rect) {
    const [screenX, screenY] = worldToScreen(Number(item.x), Number(item.y), rect);
    return Math.hypot(x - screenX, y - screenY) <= radius + 1;
  }

  function commandFromScreen(action, x, y, rect) {
    const world=model.world;
    if(action === "GATHER" && markerContains(world.seed_pile, TARGET_RADIUS_PX.seed, x, y, rect)) return "seed";
    if(action === "DIG" && markerContains(world.brood, TARGET_RADIUS_PX.brood, x, y, rect)) return "brood";
    if(action === "SCOUT" && markerContains(world.listening_front, TARGET_RADIUS_PX.front, x, y, rect)) return "front";
    if(action === "MARCH") {
      if((!world.hidden_opening || model.sim.opening_revealed) && markerContains(world.enemy_queen, TARGET_RADIUS_PX.queen, x, y, rect)) return "enemy";
      for (const lane of ["north", "south"]) if (Math.abs(y - laneScreenY(lane, x, rect)) <= TUNNEL_HALF_WIDTH_PX) return lane;
    }
    return null;
  }

  function unitAtScreen(x,y,rect) {
    let best=null, distance=ANT_HIT_RADIUS_PX;
    livingIds().forEach((id)=>{ const [wx,wy]=unitWorldPosition(id); const [sx,sy]=worldToScreen(wx,wy,rect); const d=Math.hypot(x-sx,y-sy); if(d<distance){best=id;distance=d;} }); return best;
  }

  function bindCanvas() {
    const canvas=document.getElementById("anthill-world"), box=document.getElementById("anthill-selection-box"); if(!canvas) return;
    let start=null;
    canvas.addEventListener("pointerdown",(event)=>{
      advanceToNow();
      if(model.interaction!=="full"||model.sim.terminal) return;
      const rect=canvas.getBoundingClientRect(), x=event.clientX-rect.left,y=event.clientY-rect.top;
      if(model.pendingAction){
        const target=commandFromScreen(model.pendingAction,x,y,rect);
        const selected=[...model.selected];
        if(target) applyAction(model.pendingAction,selected,target,"direct_map"); else setReadout("INVALID TARGET · ORDER STILL ARMED","error");
        model.pendingAction=null; updateHud(); draw(); return;
      }
      start={x,y,shift:event.shiftKey}; canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove",(event)=>{ if(!start||!box) return; const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top; box.style.display="block"; box.style.left=`${Math.min(x,start.x)}px`;box.style.top=`${Math.min(y,start.y)}px`;box.style.width=`${Math.abs(x-start.x)}px`;box.style.height=`${Math.abs(y-start.y)}px`; });
    canvas.addEventListener("pointerup",(event)=>{
      advanceToNow();
      if(!start) return; const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top; const moved=Math.hypot(x-start.x,y-start.y)>5;
      if(!start.shift) model.selected.clear();
      if(moved){ const left=Math.min(x,start.x),right=Math.max(x,start.x),top=Math.min(y,start.y),bottom=Math.max(y,start.y); livingIds().forEach((id)=>{ const [wx,wy]=unitWorldPosition(id),[sx,sy]=worldToScreen(wx,wy,rect); if(sx>=left&&sx<=right&&sy>=top&&sy<=bottom) model.selected.add(id); }); }
      else { const id=unitAtScreen(x,y,rect); if(id){ if(start.shift&&model.selected.has(id)) model.selected.delete(id); else model.selected.add(id); } }
      start=null; if(box) box.style.display="none"; updateHud(); draw();
    });
    document.getElementById("anthill-minimap")?.addEventListener("click",(event)=>{ const rect=event.currentTarget.getBoundingClientRect(); const x=(event.clientX-rect.left)/rect.width*model.world.width; const view=Math.min(model.world.viewport_cells,model.world.width); model.cameraX=clamp(x-view/2,0,model.world.width-view); draw(); });
  }

  async function certify() {
    advanceToNow();
    if(!model||model.submitting||model.passed) return; model.submitting=true; const button=document.getElementById("anthill-certify"); if(button)button.disabled=true; setReadout("REPLAYING COMMAND LEDGER…","idle");
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,events:model.events,final_tick:model.sim.tick,final_state:finalSummary()};
    try { const response=await fetch("/result",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)}); const outcome=await response.json();
      if(outcome.passed===true){model.passed=true;model.sim.terminal=true;updateHud();setReadout("PASS · RIVAL QUEEN DESTROYED / OWN QUEEN HOLDS","passed");if(button)button.disabled=true;}
      else if(outcome.passed===false){if(outcome.state)await helpersCache.render(outcome.state);setReadout("FAIL · FRONT REJECTED / FRESH COLONY","error");}
      else {model.submitting=false;if(button)button.disabled=false;setReadout("VERIFIER UNAVAILABLE","error");}
    } catch(_error){model.submitting=false;if(button)button.disabled=false;setReadout("VERIFIER LINK OFFLINE","error");}
  }

  function arm(action){ if(model.interaction!=="full"||model.sim.terminal)return; if(action==="RAISE"){applyAction("RAISE",[],"brood","direct_map");return;} model.pendingAction=action;updateHud();draw(); }

  async function render(state,helpers){
    helpersCache=helpers||helpersCache;if(!helpersCache)throw new Error("anthill_front_nonrealtime requires runtime helpers");
    if(animationFrame)cancelAnimationFrame(animationFrame);if(keyHandler)window.removeEventListener("keydown",keyHandler);
    document.body.dataset.mechanic="anthill-front";document.body.dataset.anthillPalette=state.palette||"amber";
    const interaction=state.control_condition?.interaction||"full"; const world=clone(state.world);
    model={state,world,interaction,sim:initialSimulation(world),events:[],selected:new Set(),pendingAction:null,cameraX:0,started:performance.now(),submitting:false,passed:false,rosterSignature:null};window.anthillFrontModel=model;
    const rosterTools=interaction==="simplified"?`<div class="anthill-roster-tools"><button data-select-role="workers">WORKERS</button><button data-select-role="soldiers">SOLDIERS</button><button data-select-role="clear">CLEAR</button></div>`:"";
    const actionControls=interaction==="simplified"?`<div class="anthill-order-grid">
      <button data-simple="gather"><b>GATHER</b>SELECTED → SEEDS</button>${world.hidden_opening ? `<button data-simple="scout"><b>SCOUT</b>SELECTED → FRONT</button>` : ""}
      ${Number(world.dig_workers) > 0 ? `<button data-simple="dig"><b>EXCAVATE</b>SELECTED → BROOD</button>` : ""}<button data-simple="raise"><b>RAISE</b>2 SEEDS → SOLDIER</button>
      <button data-simple="north"><b>MARCH NORTH</b>SELECTED SOLDIERS</button><button data-simple="south"><b>MARCH SOUTH</b>SELECTED SOLDIERS</button>
      <button class="is-wide" data-simple="enemy"><b>ASSAULT RIVAL</b>SELECTED → ENEMY QUEEN</button>
    </div>`:`<div class="anthill-direct" aria-label="direct command keys"><div class="anthill-key-grid">
      <div><kbd>G</kbd><b>GATHER</b><span>SEEDS</span></div>${world.hidden_opening ? `<div><kbd>S</kbd><b>SCOUT</b><span>FRONT</span></div>` : ""}
      ${Number(world.dig_workers) > 0 ? `<div><kbd>D</kbd><b>EXCAVATE</b><span>BROOD</span></div>` : ""}<div><kbd>R</kbd><b>RAISE</b><span>2 SEEDS</span></div>
      <div class="is-wide"><kbd>M</kbd><b>MARCH</b><span>NORTH · SOUTH · RIVAL</span></div>
    </div><div class="anthill-pan-keys"><kbd>←</kbd><kbd>→</kbd><b>PAN</b><span>MINIMAP</span></div></div>`;
    const controls=`${rosterTools}<div class="anthill-roster" id="anthill-roster"></div>${actionControls}`;
    helpersCache.app.innerHTML=`<section class="anthill-console" data-interaction="${helpersCache.text(interaction)}" tabindex="0">
      <header class="anthill-topbar"><div><span class="anthill-eyebrow">SUBTERRANEAN COMMAND / COLONY A</span><h1>Keep the amber queen alive. Break the rival queen.</h1></div><div class="anthill-live"><i class="anthill-pulse"></i><div class="anthill-clock"><small>MATCH CLOCK</small><b id="anthill-tick">000</b></div></div></header>
      <section class="anthill-statusbar"><div class="anthill-stat"><i>●</i><small>SEEDS</small><b id="anthill-seeds">0</b></div><div class="anthill-stat"><i>♟</i><small>WORKERS</small><b id="anthill-workers">0</b></div><div class="anthill-stat"><i>⚔</i><small>SOLDIERS + QUEUE</small><b id="anthill-soldiers">0</b></div><div class="anthill-stat"><i>⌂</i><small>BROOD</small><b id="anthill-brood-state">—</b></div><div class="anthill-stat good"><i>♛</i><small>OUR QUEEN</small><b id="anthill-queen">3 HP</b></div><div class="anthill-stat danger"><i>◆</i><small>RIVAL QUEEN / LOST</small><b><span id="anthill-rival">?</span> · <span id="anthill-losses">0</span></b></div></section>
      <main class="anthill-main"><section class="anthill-stage"><div class="anthill-map-head"><span class="anthill-map-title">LIVE TUNNEL SECTION</span><span class="anthill-coords">MAP ${helpersCache.text(state.challenge_id).toUpperCase()}</span></div><div class="anthill-canvas-wrap"><canvas id="anthill-world" aria-label="scrollable live anthill battlefield"></canvas><div class="anthill-selection-box" id="anthill-selection-box"></div><div class="anthill-command-cursor" id="anthill-command-cursor"></div><div class="anthill-verdict" id="anthill-verdict">FRONT LIVE</div></div>
      <div class="anthill-minimap-row"><canvas id="anthill-minimap" aria-label="anthill minimap"></canvas><div class="anthill-map-legend"><b>MINIMAP</b><br>AMBER = COLONY · RED = RIVAL<br>WHITE FRAME = VIEWPORT</div><div class="anthill-pan"><button data-pan="-1" aria-label="pan left">◀</button><button data-pan="1" aria-label="pan right">▶</button></div></div></section>
      <aside class="anthill-sidebar"><section class="anthill-intel"><h2>Scout wire / rival contact</h2><div class="anthill-intel-body" id="anthill-intel-body"></div></section><section class="anthill-orders"><div class="anthill-order-title">Colony orders / ${helpersCache.text(interaction)}</div>${controls}<div class="anthill-selection" id="anthill-selection">SELECTED <b>NONE</b></div></section></aside></main>
      <footer class="anthill-footer"><div class="anthill-readout"><span>COMMAND LEDGER / DETERMINISTIC REPLAY</span><b class="readout" id="anthill-readout" data-status="idle">COLONY LINK READY</b></div><button class="anthill-certify" id="anthill-certify" type="button">CERTIFY FRONT →</button></footer>
    </section>`;
    bindCanvas();
    document.querySelectorAll("[data-pan]").forEach((button)=>button.addEventListener("click",()=>{const view=Math.min(world.viewport_cells,world.width);model.cameraX=clamp(model.cameraX+Number(button.dataset.pan)*view*.72,0,world.width-view);draw();}));
    document.querySelectorAll("[data-select-role]").forEach((button)=>button.addEventListener("click",()=>{const role=button.dataset.selectRole;model.selected.clear();if(role==="workers")model.sim.workers.forEach((id)=>model.selected.add(id));else if(role==="soldiers")model.sim.soldiers.forEach((id)=>model.selected.add(id));model.rosterSignature=null;updateHud();draw();}));
    document.querySelectorAll("[data-simple]").forEach((button)=>button.addEventListener("click",()=>{const command=button.dataset.simple;const selected=[...model.selected];if(command==="gather")applyAction("GATHER",selected,"seed","command_panel");else if(command==="scout")applyAction("SCOUT",selected,"front","command_panel");else if(command==="dig")applyAction("DIG",selected,"brood","command_panel");else if(command==="raise")applyAction("RAISE",[],"brood","command_panel");else if(command==="north"||command==="south")applyAction("MARCH",selected,command,"command_panel");else if(command==="enemy")applyAction("MARCH",selected,"enemy","command_panel");}));
    document.getElementById("anthill-certify")?.addEventListener("click",certify);
    keyHandler=(event)=>{if(event.repeat||model.interaction!=="full"||model.submitting)return;const key=event.key.toLowerCase();if({g:1,s:1,d:1,m:1,r:1}[key]){event.preventDefault();arm({g:"GATHER",s:"SCOUT",d:"DIG",m:"MARCH",r:"RAISE"}[key]);}else if(key==="arrowleft"||key==="arrowright"){event.preventDefault();const view=Math.min(world.viewport_cells,world.width);model.cameraX=clamp(model.cameraX+(key==="arrowleft"?-1:1)*view*.5,0,world.width-view);draw();}else if(key==="escape"){model.pendingAction=null;updateHud();draw();}};window.addEventListener("keydown",keyHandler);
    updateHud();draw();document.querySelector(".anthill-console")?.focus();
    const loop=()=>{advanceToNow();updateHud();draw();animationFrame=requestAnimationFrame(loop);}; animationFrame=requestAnimationFrame(loop);
  }

  function advanceToNow() {
    if (!model || model.submitting || model.passed) return;
    const target = Math.floor((performance.now() - model.started) / Number(model.world.tick_ms) + 1e-7);
    while (model.sim.tick < target && !model.sim.terminal) stepSimulation();
  }

  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};window.GymAnythingRTMechanics.anthill_front_nonrealtime={rootSelector:".anthill-console",render};
})();
