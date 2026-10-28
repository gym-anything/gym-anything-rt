(() => {
  "use strict";
  const noise = (seed, i) => {
    let x = (seed ^ Math.imul(i + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  };
  function integral(seed, t, span) {
    const u = Math.max(0, t) / span, n = Math.floor(u), f = u - n;
    let total = 0;
    for (let i = 0; i < n; i++) total += (noise(seed, i) + noise(seed, i + 1)) / 2;
    const a = noise(seed, n), b = noise(seed, n + 1);
    return span * (total + a * f + (b - a) * (f ** 3 - f ** 4 / 2));
  }
  function angles(w, t) {
    const m = w.motion;
    return m.angles.map((a, i) => a + m.rates[i] * (t + m.gust * integral(m.seed + i * 7919, t, m.span_ms)) / 1000);
  }
  function rotate(point, a) {
    let [x, y, z] = point;
    const [yaw, pitch, roll] = a;
    [x, z] = [x * Math.cos(yaw) - z * Math.sin(yaw), x * Math.sin(yaw) + z * Math.cos(yaw)];
    [y, z] = [y * Math.cos(pitch) - z * Math.sin(pitch), y * Math.sin(pitch) + z * Math.cos(pitch)];
    [x, y] = [x * Math.cos(roll) - y * Math.sin(roll), x * Math.sin(roll) + y * Math.cos(roll)];
    return [x, y, z];
  }
  function project(w, t) {
    const a = angles(w, t), points = Object.fromEntries(w.vertices.map(v => [v.id, rotate(v.position, a)]));
    const visible = new Set();
    const faces = w.faces.map(ids => {
      const [p, q, r] = ids.map(k => points[k]);
      const front = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]) >= -1e-9;
      if (front) ids.forEach(id => visible.add(id));
      return {ids, front, depth: ids.reduce((s, id) => s + points[id][2], 0) / 3};
    });
    return {studs: w.vertices.map(v => ({id: v.id, label: v.label,
      x: w.center[0] + w.scale * points[v.id][0], y: w.center[1] - w.scale * points[v.id][1],
      depth: points[v.id][2], visible: visible.has(v.id)})), faces, angles: a};
  }
  function hit(w, t, point) {
    if (!point || point.some(x => !Number.isFinite(x)) || point[0] < 0 || point[0] > w.width || point[1] < 0 || point[1] > w.height) return null;
    const candidates = project(w, t).studs.filter(p => p.visible && Math.hypot(p.x - point[0], p.y - point[1]) <= w.stud_radius + 1e-7);
    candidates.sort((a, b) => a.depth - b.depth || a.id.localeCompare(b.id));
    return candidates.at(-1)?.id ?? null;
  }
  const edge = (a, b) => [a, b].sort().join("|");
  function score(w, edges) {
    const complete = w.targets.filter(f => f.vertices.every((a, i) => edges.has(edge(a, f.vertices[(i + 1) % 3])))).length;
    const used = new Set([...edges].flatMap(e => e.split("|")));
    return {value: 10 * edges.size + 30 * complete - (w.vertices.length - used.size), complete};
  }
  let model, raf = 0;
  const time = () => model.startedAt === null ? 0 : Math.max(0, performance.now() - model.startedAt);
  const esc = s => String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");
  function render(state, helpers) {
    cancelAnimationFrame(raf);
    const w = state.world, mode = state.control_condition.interaction;
    const required = new Set(w.targets.flatMap(f => f.vertices.map((v, i) => edge(v, f.vertices[(i + 1) % 3]))));
    model = {state, helpers, mode, w, required, edges: new Set(w.initial_edges.map(e => edge(...e))),
      revealed: new Set(), events: [], startedAt: null, selected: null, dragging: false, pointer: null, terminal: false, submitted: false, finalT: null};
    window.facetLanternV3Model = model;
    document.body.dataset.mechanic = "facet-lantern-v3";
    const names = Object.fromEntries(w.vertices.map(v => [v.id, v.label]));
    const knownName = id => model.revealed.has(id) ? names[id] : "?";
    helpers.app.innerHTML = `<section class="fl2-shell" data-interaction="${mode}">
      <header class="fl2-head"><div><p>THE WIND GLASS WORKSHOP · COMMISSION ${state.control_condition.difficulty}</p><h1>Facet Lantern V3</h1></div>
      <div class="fl2-score"><small>LIGHT SCORE</small><strong>0</strong><span class="fl2-count"></span></div></header>
      <div class="fl2-main"><div class="fl2-stage-card"><div class="fl2-stage-title"><span>WIND-DRIVEN WIREWORK</span><span class="fl2-phase">READY TO LAUNCH</span></div>
      <canvas class="fl2-stage" width="860" height="550" aria-label="Turning three-dimensional lantern; hover over gold studs to inspect their concealed letters"></canvas>
      <div class="fl2-caption">Launch, then hover over a gold stud to read its etching. Learned letters stay visible. Pale rings: 0.6 s ago; cyan diamonds: 0.8 s ahead.</div></div>
      <aside class="fl2-side"><p class="fl2-label">COMMISSIONED PANES</p><div class="fl2-panes">${w.targets.map(f => `<div data-pane="${f.id}" class="fl2-pane"><b>${f.vertices.map(id => names[id]).join(" · ")}</b><span>OPEN</span></div>`).join("")}</div>
      <div class="fl2-inspection" aria-live="polite">ETCHINGS UNREAD · ?</div>
      <div class="fl2-selection">NO WIRE HELD</div><p class="fl2-rules">Inspect with the pointer, without pressing a button; the wind keeps turning. ${mode === "full" ? "Drag a wire from one gold stud to another." : "Click a gold stud, then click its partner."} Close the listed triangles. Shared edges need one wire. A wrong wire ends the attempt; empty-space misses are safe.</p>
      <button class="fl2-start">LAUNCH INTO THE WIND</button><button class="fl2-cancel">CANCEL WIRE · ESC</button><button class="fl2-submit">CERTIFY LANTERN</button>
      <div class="readout fl2-readout">Inspect the commission, then launch.</div></aside></div><div class="fl2-verdict" hidden></div></section>`;
    const canvas = helpers.app.querySelector("canvas"), ctx = canvas.getContext("2d");
    const say = (s, status = "idle") => helpers.setReadout(s, status);
    const record = (kind, t, source, extra = {}) => model.events.push({seq: model.events.length + 1, kind, t_ms: t, input_source: source, ...extra});
    const local = e => { const r = canvas.getBoundingClientRect(); return [(e.clientX - r.x) * w.width / r.width, (e.clientY - r.y) * w.height / r.height]; };
    function line(a, b, color, width = 1, dash = []) {
      ctx.beginPath(); ctx.setLineDash(dash); ctx.strokeStyle = color; ctx.lineWidth = width;
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); ctx.setLineDash([]);
    }
    function draw() {
      const t = model.finalT ?? time(), scene = project(w, t), byId = Object.fromEntries(scene.studs.map(p => [p.id, p]));
      ctx.clearRect(0, 0, w.width, w.height);
      const glow = ctx.createRadialGradient(430, 275, 20, 430, 275, 290); glow.addColorStop(0, "#403041"); glow.addColorStop(1, "#101a23");
      ctx.fillStyle = glow; ctx.fillRect(0, 0, w.width, w.height);
      ctx.strokeStyle = "#8eaaa41b"; ctx.lineWidth = 1;
      for (let i = 0; i < 7; i++) { ctx.beginPath(); ctx.ellipse(430, 275, 260 + i * 18, 65 + i * 21, -.15, 0, 2 * Math.PI); ctx.stroke(); }
      for (const f of [...scene.faces].sort((a, b) => a.depth - b.depth)) {
        if (!f.front) continue;
        ctx.beginPath(); f.ids.forEach((id, i) => { const p = byId[id]; i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y); }); ctx.closePath();
        const done = f.ids.every((id, i) => model.edges.has(edge(id, f.ids[(i + 1) % 3])));
        ctx.fillStyle = done ? "#e6b96c55" : "#59677444"; ctx.fill(); ctx.strokeStyle = "#adb7ba50"; ctx.lineWidth = 1.5; ctx.stroke();
      }
      for (const key of model.edges) {
        const [a, b] = key.split("|").map(id => byId[id]);
        if (a.visible && b.visible) line(a, b, "#f5c877", 4);
      }
      const live = scene.studs.filter(p => p.visible).sort((a, b) => a.depth - b.depth || a.id.localeCompare(b.id));
      for (const p of live) {
        ctx.beginPath(); ctx.arc(p.x, p.y, w.stud_radius, 0, 2 * Math.PI); ctx.fillStyle = model.selected === p.id ? "#38695f" : "#4a382b"; ctx.fill();
        ctx.strokeStyle = model.selected === p.id ? "#abffe5" : "#f3cc88"; ctx.lineWidth = 2; ctx.stroke();
      }
      // These bounded records are visible temporal evidence, not clickable
      // forecasts. No proxy targets or automatic interceptions are installed.
      if (model.startedAt !== null && !model.terminal) {
        const past = project(w, Math.max(0, t - w.trace_ms)), future = project(w, t + w.forecast_ms);
        for (const p of scene.studs.filter(p => p.visible)) {
          const a = past.studs.find(x => x.id === p.id), b = future.studs.find(x => x.id === p.id);
          // Cues sit above stud fills so slow motion remains observable.
          // Labels are drawn last. These are timestamped position markers,
          // never enlarged hit regions or automatic wire catches.
          line(a, p, "#e9d7afaa", 2);
          ctx.beginPath(); ctx.arc(a.x, a.y, 4, 0, 2 * Math.PI); ctx.strokeStyle = "#e9d7afbb"; ctx.lineWidth = 1.5; ctx.stroke();
          if (b.visible) {
            line(p, b, "#9fe8e5bb", 1.5, [4, 5]);
            ctx.beginPath(); ctx.moveTo(b.x, b.y - 6); ctx.lineTo(b.x + 6, b.y); ctx.lineTo(b.x, b.y + 6); ctx.lineTo(b.x - 6, b.y); ctx.closePath();
            ctx.strokeStyle = "#9fe8e5"; ctx.lineWidth = 1.7; ctx.stroke();
          }
        }
      }
      if (model.selected && model.pointer) line(byId[model.selected], {x: model.pointer[0], y: model.pointer[1]}, "#8fe5d5", 2);
      for (let i = 0; i < live.length; i++) {
        const p = live[i];
        // A label's center must identify the same depth winner as input.
        // Rear labels wait until their stud emerges from a nearer disk.
        if (live.slice(i + 1).some(q => Math.hypot(q.x - p.x, q.y - p.y) <= w.stud_radius + 1e-7)) continue;
        ctx.fillStyle = model.revealed.has(p.id) ? "#fff2cb" : "#9cc7ca"; ctx.font = "bold 17px ui-monospace, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(knownName(p.id), p.x, p.y + 1);
      }
      const stats = score(w, model.edges);
      helpers.app.querySelector(".fl2-score strong").textContent = stats.value;
      helpers.app.querySelector(".fl2-count").textContent = `${stats.complete} / ${w.targets.length} PANES LIT`;
      helpers.app.querySelector(".fl2-selection").textContent = model.selected ? `WIRE FROM ${knownName(model.selected)}` : "NO WIRE HELD";
      helpers.app.querySelector(".fl2-phase").textContent = model.startedAt === null ? "READY TO LAUNCH" : model.terminal ? "ATTEMPT ENDED" : `${Math.max(0, Math.ceil((w.duration_ms - t) / 1000))} s · WIND ACTIVE`;
      for (const f of w.targets) {
        const node = helpers.app.querySelector(`[data-pane="${f.id}"]`), done = f.vertices.every((v, i) => model.edges.has(edge(v, f.vertices[(i + 1) % 3])));
        node.classList.toggle("is-done", done); node.querySelector("span").textContent = done ? "LIT" : "OPEN";
      }
    }
    async function finish(failure = "") {
      if (model.terminal) return;
      model.finalT = Math.min(time(), w.duration_ms); model.terminal = true; model.dragging = false;
      record(failure ? "failure" : "submit", model.finalT, failure ? "failure" : "certify_button", failure ? {reason: failure} : {});
      draw();
      const verdict = helpers.app.querySelector(".fl2-verdict"); verdict.hidden = false;
      verdict.innerHTML = `<strong>${failure ? "FAIL" : "VERIFYING"}</strong><span>${esc(failure || "CERTIFYING THE LANTERN")}</span>`;
      helpers.app.querySelectorAll("button").forEach(b => b.disabled = true);
      const stats = score(w, model.edges);
      const payload = {mechanic_id: state.mechanic_id, task_id: state.task_id, challenge_id: state.challenge_id,
        control_condition: state.control_condition, events: model.events,
        edges: [...model.edges].map(x => x.split("|")).sort((a, b) => {
          const i = a[0] === b[0] ? 1 : 0;
          return a[i] < b[i] ? -1 : a[i] > b[i] ? 1 : 0;
        }),
        completed: !failure, final_t_ms: model.finalT, reported_score: stats.value};
      model.submitted = true;
      try {
        const response = await fetch("/result", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(payload)});
        const result = await response.json();
        const passed = result.passed === true;
        verdict.dataset.status = passed ? "passed" : "error";
        verdict.innerHTML = `<strong>${passed ? "PASS" : "FAIL"}</strong><span>${esc(passed ? "ALL COMMISSIONED PANES ARE LIT" : failure || "INCOMPLETE COMMISSION")}</span>`;
        say(passed ? "PASS · LANTERN CERTIFIED" : `FAIL · ${failure || "INCOMPLETE COMMISSION"}`, passed ? "passed" : "error");
      } catch (e) { say(`VERIFIER ERROR · ${e.message}`, "error"); verdict.innerHTML = "<strong>VERIFIER ERROR</strong>"; }
    }
    function active() {
      if (model.terminal || model.startedAt === null) return false;
      if (time() >= w.duration_ms) { finish("WIND SHIFT ENDED · COMMISSION INCOMPLETE"); return false; }
      return true;
    }
    function pick(point) {
      if (!active() || model.selected !== null) return;
      const t = time(), id = hit(w, t, point);
      record("pick", t, mode, {point, hit_id: id}); model.selected = id;
      say(id ? `WIRE FROM ${knownName(id)} · FOLLOW THE MOVING PARTNER` : "EMPTY SPACE · NO STUD SELECTED"); draw();
    }
    function release(point) {
      if (!active() || model.selected === null) return;
      const t = time(), id = hit(w, t, point), from = model.selected;
      record("release", t, mode, {point, hit_id: id});
      if (id !== null && id !== from) {
        const key = edge(from, id);
        if (!required.has(key)) { finish(`WRONG WIRE · ${names[from]} TO ${names[id]}`); return; }
        model.edges.add(key); say(`CONNECTED ${knownName(from)} TO ${knownName(id)}`);
      } else say(id === null ? "EMPTY SPACE · WIRE MISSED" : "WIRE CANCELLED");
      if (mode === "full" || id !== null) model.selected = null;
      draw();
    }
    function cancel(source) {
      if (!active()) return;
      record("cancel", time(), source); model.selected = null; model.dragging = false; model.pointer = null; say("WIRE CANCELLED · WIND CONTINUES"); draw();
    }
    function inspect(point) {
      if (!active()) return;
      const t = time(), id = hit(w, t, point);
      if (id === null || model.revealed.has(id)) return;
      // Inspection shares the actual visible stud hit test with wirework.
      // It never arms a wire, consumes stock, or pauses the turning solid.
      model.revealed.add(id);
      record("inspect", t, "hover", {point, hit_id: id, label: names[id]});
      helpers.app.querySelector(".fl2-inspection").textContent = `ETCHING READ · ${names[id]} · LETTER RETAINED`;
      draw();
    }
    canvas.addEventListener("pointerdown", e => {
      if (mode !== "full" || e.button !== 0 || !active()) return;
      e.preventDefault(); canvas.setPointerCapture(e.pointerId); model.dragging = true; model.pointer = local(e); pick(model.pointer);
    });
    canvas.addEventListener("pointermove", e => {
      const point = local(e);
      if (model.dragging || model.selected) model.pointer = point;
      inspect(point);
    });
    canvas.addEventListener("pointerup", e => {
      if (mode !== "full" || !model.dragging) return;
      model.dragging = false; release(local(e)); if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointercancel", () => { if (model.dragging) cancel("cancel_button"); });
    canvas.addEventListener("lostpointercapture", () => { if (model.dragging) cancel("cancel_button"); });
    canvas.addEventListener("click", e => {
      if (mode !== "simplified" || !active()) return;
      const point = local(e); model.pointer = point; model.selected === null ? pick(point) : release(point);
    });
    const escape = e => { if (e.key === "Escape" && !e.repeat && model?.state === state) cancel("escape_key"); };
    if (window.facetLanternV3Escape) window.removeEventListener("keydown", window.facetLanternV3Escape);
    window.facetLanternV3Escape = escape; window.addEventListener("keydown", escape);
    helpers.app.querySelector(".fl2-cancel").addEventListener("click", () => cancel("cancel_button"));
    helpers.app.querySelector(".fl2-start").addEventListener("click", () => {
      if (model.startedAt !== null || model.terminal) return;
      model.startedAt = performance.now(); record("start", 0, "launch_button"); helpers.app.querySelector(".fl2-start").disabled = true;
      say("WIND ACTIVE · CLOSE THE COMMISSIONED PANES"); draw();
    });
    helpers.app.querySelector(".fl2-submit").addEventListener("click", () => {
      if (model.startedAt === null) { model.startedAt = performance.now(); record("start", 0, "launch_button"); }
      if (active()) finish();
    });
    function animate() { if (!model.terminal) { active(); draw(); raf = requestAnimationFrame(animate); } }
    draw(); raf = requestAnimationFrame(animate);
  }
  window.FacetLanternV3 = {noise, integral, angles, rotate, project, hit, score};
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.facet_lantern_v3 = {rootSelector: ".fl2-shell", render};
})();
