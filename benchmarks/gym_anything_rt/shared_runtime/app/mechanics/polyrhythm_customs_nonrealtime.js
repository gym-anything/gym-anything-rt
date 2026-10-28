(() => {
  "use strict";
  const mod = (a,b) => ((a%b)+b)%b;
  const noise = (seed,index) => {
    let x = (seed ^ Math.imul(index+1,0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x>>>16),0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x>>>13),0xc2b2ae35) >>> 0;
    return ((x ^ (x>>>16))>>>0)/4294967295*2-1;
  };
  function motion(seed,ms,span) {
    const u = Math.max(0,ms)/span, n = Math.floor(u), f = u-n;
    return noise(seed,n)+(noise(seed,n+1)-noise(seed,n))*f*f*(3-2*f);
  }
  function integral(seed,ms,span) {
    const u = Math.max(0,ms)/span, n = Math.floor(u), f = u-n;
    let total = 0;
    for (let i=0;i<n;i++) total += (noise(seed,i)+noise(seed,i+1))/2;
    const a = noise(seed,n), b = noise(seed,n+1);
    return span*(total+a*f+(b-a)*(f**3-f**4/2));
  }
  function derivative(seed,ms,span) {
    const u = Math.max(0,ms)/span, n = Math.floor(u), f = u-n;
    return (noise(seed,n+1)-noise(seed,n))*6*f*(1-f)/span*1000;
  }
  class Rail {
    constructor(world) {
      this.world = world; this.ms = 0; this.started = false; this.failed = "";
      this.cleared = new Set(); this.held = new Map();
      this.notes = Object.fromEntries(world.notes.map(n => [n.id,n]));
      this.lanes = Object.fromEntries(world.lanes.map(l => [l.id,l]));
      this.c = 2*(world.rail.right-world.rail.left)+2*Math.PI*world.rail.radius;
      this.missed = 0; this.missedNotes = new Map();
      this.nextPass = Object.fromEntries(world.notes.map(n => [n.id,Math.ceil((n.phase-this.gate(this.lanes[n.lane],0)-world.parameters.band_half_width)/this.c)]));
    }
    travel(lane,ms) {
      const p = this.world.parameters, offset = lane.offset_ms;
      return p.speed*(ms+p.speed_variation*(integral(lane.speed_seed,ms+offset,p.speed_span_ms)-integral(lane.speed_seed,offset,p.speed_span_ms)))/1000;
    }
    gate(lane,ms) {
      const w = this.world, p = w.parameters;
      return w.rail.right-w.rail.gate_x-p.gate_drift*motion(lane.gate_seed,ms+lane.offset_ms,p.gate_span_ms);
    }
    phase(note,ms) { return note.phase+this.travel(this.lanes[note.lane],ms); }
    point(value,y) {
      const r = this.world.rail, length = r.right-r.left, radius = r.radius, s = mod(value,this.c);
      if (s<=length) return [r.right-s,y];
      if (s<=length+Math.PI*radius) {
        const a = (s-length)/radius;
        return [r.left-radius*Math.sin(a),y+radius-radius*Math.cos(a)];
      }
      if (s<=2*length+Math.PI*radius) return [r.left+s-length-Math.PI*radius,y+2*radius];
      const a = (s-2*length-Math.PI*radius)/radius;
      return [r.right+radius*Math.sin(a),y+radius+radius*Math.cos(a)];
    }
    advance(ms,enforceHeld=true,countMisses=true) {
      this.ms = ms;
      if (this.failed) return;
      for (const [id,h] of this.held) {
        const n = this.notes[h.note];
        if (enforceHeld && h.kind === "hold" && this.phase(n,ms)-n.length > h.cycle*this.c+this.gate(this.lanes[id],ms)+this.world.parameters.band_half_width+1e-7) {
          this.failed = "A held ribbon passed the release band."; return;
        }
      }
      for (const n of Object.values(this.notes)) {
        if (this.cleared.has(n.id) || this.held.get(n.lane)?.note === n.id) continue;
        const head = this.phase(n,ms), center = this.gate(this.lanes[n.lane],ms);
        while (head > this.nextPass[n.id]*this.c+center+this.world.parameters.band_half_width+1e-7) {
          this.nextPass[n.id]++; this.missed++;
          if (countMisses) {
            this.missedNotes.set(n.id,(this.missedNotes.get(n.id)||0)+1);
            if (this.missed > this.world.parameters.miss_allowance) { this.failed = "Too many missed passes."; return; }
          } else this.missed--;
        }
      }
    }
    decisionCandidates(ms=this.ms) {
      const centerFor = lane => this.gate(this.lanes[lane],ms), half = this.world.parameters.band_half_width;
      return Object.values(this.notes).filter(n => !this.cleared.has(n.id) && !this.held.has(n.lane) &&
        Math.abs(mod(this.phase(n,ms),this.c)-centerFor(n.lane)) <= half+1e-7);
    }
    nextDecision(afterMs=this.ms) {
      if (this.decisionCandidates(afterMs).length) return afterMs;
      const limit = this.world.run_limit_ms;
      for (let t=Math.floor(afterMs)+1;t<=limit;t++) if (this.decisionCandidates(t).length) return t;
      return null;
    }
    releaseTime(note) {
      const lane = this.lanes[note.lane], half = this.world.parameters.band_half_width;
      const cycle = Math.floor(this.phase(note,this.ms)/this.c);
      const limit = this.world.run_limit_ms;
      for (let t=Math.floor(this.ms)+1;t<=Math.min(limit,this.ms+10000);t++) {
        if (Math.abs(this.phase(note,t)-note.length-cycle*this.c-this.gate(lane,t)) <= half+1e-7) return t;
      }
      return null;
    }
    settleStart() {
      const target = this.nextDecision(0);
      if (target === null) this.failed = "The inspection shift ended.";
      else this.advance(target,false,false);
    }
    settleAfterAction(kind,id) {
      if (this.failed) return;
      if (this.cleared.size === Object.keys(this.notes).length && this.held.size === 0) return;
      let target = this.ms;
      const held = this.held.get(id);
      if (kind === "down" && held?.kind === "hold") {
        target = this.releaseTime(this.notes[held.note]);
        if (target === null) { this.failed = "The inspection shift ended."; return; }
      } else if (kind === "down") {
        // A tap still uses the donor's physical keydown/keyup pair.  Keep
        // that lane stable until its ordinary keyup/pad toggle arrives.
        return;
      } else if (!this.decisionCandidates(target).length) {
        target = this.nextDecision(target);
        if (target === null) { this.failed = "The inspection shift ended."; return; }
      }
      if (target > this.ms) this.advance(target,false,false);
    }
    action(kind,id="") {
      if (this.failed) return;
      if (kind === "start") {
        if (this.started || this.ms !== 0) this.failed = "Invalid start or restart.";
        this.started = true; return;
      }
      if (!this.started || !this.lanes[id]) { this.failed = "Input outside the active score."; return; }
      const center = this.gate(this.lanes[id],this.ms), half = this.world.parameters.band_half_width;
      if (kind === "down") {
        if (this.held.has(id)) { this.failed = "Duplicate press."; return; }
        const candidates = Object.values(this.notes).filter(n => n.lane === id && !this.cleared.has(n.id) && Math.abs(mod(this.phase(n,this.ms),this.c)-center)<=half+1e-7);
        if (candidates.length !== 1) { this.failed = "A stamp missed the moving gold band."; return; }
        const n = candidates[0];
        this.held.set(id,{note:n.id,kind:n.kind,cycle:Math.floor(this.phase(n,this.ms)/this.c)});
        if (n.kind === "tap") this.cleared.add(n.id);
      } else if (kind === "up") {
        const h = this.held.get(id);
        if (!h) { this.failed = "Release without a press."; return; }
        const n = this.notes[h.note];
        if (h.kind === "hold" && Math.abs(this.phase(n,this.ms)-n.length-h.cycle*this.c-center)>half+1e-7) {
          this.failed = "A ribbon was released outside the moving gold band."; return;
        }
        this.cleared.add(n.id); this.held.delete(id);
      } else this.failed = "Unknown input; resets and world stops are unavailable.";
    }
    snapshot(ms=this.ms) {
      const p = this.world.parameters;
      return {t_ms:ms, failed:this.failed, held:Object.fromEntries(this.held), cleared:[...this.cleared].sort(),missed:this.missed,missed_notes:Object.fromEntries(this.missedNotes),
        lanes:this.world.lanes.map(l => ({id:l.id,gate:this.gate(l,ms),
          speed:p.speed*(1+p.speed_variation*motion(l.speed_seed,ms+l.offset_ms,p.speed_span_ms)),
          gate_speed:-p.gate_drift*derivative(l.gate_seed,ms+l.offset_ms,p.gate_span_ms)})),
        notes:this.world.notes.map(n => ({...n, phase:this.phase(n,ms), head:mod(this.phase(n,ms),this.c),
          tail:mod(this.phase(n,ms)-n.length,this.c)}))};
    }
  }
  // Exposed only for implementation parity tests and explicitly privileged oracles.
  window.PolyrhythmRail = Rail;
  let model = null, frame = 0, keyDown = null, keyUp = null;
  const clean = v => String(v).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll('"',"&quot;");
  function record(kind,lane,input_source,tOverride=null) {
    // Replay must receive the same Number used for hit testing. Rounding a
    // legal boundary stamp can move it outside the band during verification.
    model.events.push({sequence:model.events.length+1,kind,lane,t_ms:tOverride === null ? model.sim.ms : tOverride,input_source});
  }
  function input(kind,lane,source) {
    if (!model.active || model.terminal || model.submitting) return;
    record(kind,lane,source); model.sim.action(kind,lane);
    if (!model.sim.failed) model.sim.settleAfterAction(kind,lane);
    draw();
    if (model.sim.failed) finish(model.sim.failed);
    else if (model.sim.cleared.size === model.state.notes.length && model.sim.held.size === 0) finish();
  }
  function begin() {
    if (model.active || model.terminal) return;
    model.active = true; model.sim.action("start"); model.sim.settleStart();
    record("start","","begin_button",0);
    document.querySelector(".pc-welcome").hidden = true;
    document.querySelector("#pc-begin").disabled = true;
    model.helpers.setReadout("READY · ONE INSPECTION", "idle");
    document.querySelector(".pc-root").focus(); draw();
  }
  async function finish(reason="") {
    if (model.terminal) return;
    if (!model.active) reason = "The score has not started.";
    if (!reason && (model.sim.cleared.size !== model.state.notes.length || model.sim.held.size)) reason = "The manifest is incomplete.";
    model.terminal = true; model.submitting = true; model.failure = reason;
    const completed = !reason;
    const payload = {...Object.fromEntries(["mechanic_id","task_id","challenge_id","revision"].map(k => [k,model.state[k]])),
      interaction_mode:model.mode,events:model.events,final_t_ms:model.sim.ms,
      cleared_ids:[...model.sim.cleared].sort(),missed_passes:model.sim.missed,completed};
    document.querySelectorAll(".pc-root button").forEach(b => { b.disabled = true; });
    model.helpers.setReadout(reason ? `FAIL · ${reason}` : "VERIFYING CLEARANCE…",reason ? "error" : "pending");
    draw();
    try {
      const response = await fetch("/result",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
      const outcome = await response.json();
      model.verdict = outcome.passed === true && completed ? "pass" : outcome.passed === false ? "fail" : "error";
      model.helpers.setReadout(model.verdict === "pass" ? "PASS · ALL NOTES CLEARED" : model.verdict === "fail" ? `FAIL · ${reason || outcome.feedback || 'CLEARANCE REJECTED'}` : "VERIFIER ERROR",model.verdict === "pass" ? "passed" : "error");
    } catch (error) {
      model.verdict = "error"; model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`,"error");
    }
    const overlay = document.querySelector(".pc-verdict");
    overlay.hidden = false; overlay.dataset.status = model.verdict;
    overlay.querySelector("strong").textContent = model.verdict.toUpperCase();
    overlay.querySelector("span").textContent = model.verdict === "pass" ? "MANIFEST CLEARED" : reason || "INSPECTION ENDED";
    model.submitting = false;
  }
  function dot(ctx,x,y,r,color,fill=true) {
    ctx.beginPath(); ctx.arc(x,y,r,0,Math.PI*2); ctx.fillStyle=color; ctx.strokeStyle=color;
    if (fill) ctx.fill(); else { ctx.lineWidth=3; ctx.stroke(); }
  }
  function draw() {
    if (!model) return;
    const canvas = document.querySelector("#pc-rail"), ctx = canvas.getContext("2d"), w = model.state, sim = model.sim;
    ctx.fillStyle = "#12262c"; ctx.fillRect(0,0,960,456);
    const p = w.parameters, r = w.rail, length = r.right-r.left, ms = sim.ms;
    for (const lane of w.lanes) {
      const y = lane.y, gateX = r.right-sim.gate(lane,ms);
      ctx.strokeStyle = "#355159"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(r.right,y); ctx.lineTo(r.left,y);
      ctx.arc(r.left,y+r.radius,r.radius,-Math.PI/2,-3*Math.PI/2,true);
      ctx.lineTo(r.right,y+2*r.radius);
      ctx.arc(r.right,y+r.radius,r.radius,Math.PI/2,-Math.PI/2,true); ctx.stroke();
      ctx.strokeStyle = "#29464c"; ctx.lineWidth = 1;
      for (let x=r.left+50;x<r.right;x+=60) {
        ctx.beginPath(); ctx.moveTo(x,y-7); ctx.lineTo(x-7,y); ctx.lineTo(x,y+7); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(x,y+2*r.radius-5); ctx.lineTo(x+5,y+2*r.radius); ctx.lineTo(x,y+2*r.radius+5); ctx.stroke();
      }
      ctx.fillStyle = "#daba6730"; ctx.fillRect(gateX-p.band_half_width,y-24,2*p.band_half_width,48);
      ctx.strokeStyle = "#e5c783"; ctx.lineWidth = 2; ctx.strokeRect(gateX-p.band_half_width,y-24,2*p.band_half_width,48);
      ctx.strokeStyle = "#e5c78388"; ctx.beginPath(); ctx.moveTo(gateX,y-24); ctx.lineTo(gateX,y+24); ctx.stroke();
      ctx.fillStyle = lane.color; ctx.font = "bold 24px Georgia"; ctx.textAlign = "left"; ctx.fillText(lane.key,22,y+5);
      ctx.font = "10px ui-monospace,monospace"; ctx.fillText(lane.label,22,y+26);
      const speed = p.speed*(1+p.speed_variation*motion(lane.speed_seed,ms+lane.offset_ms,p.speed_span_ms));
      ctx.fillStyle = "#9bb7b9"; ctx.fillText(`← ${(speed/p.speed).toFixed(2)}×`,22,y+46);
      for (const note of w.notes.filter(n => n.lane === lane.id && !sim.cleared.has(n.id))) {
        const head = sim.phase(note,ms), at = mod(head,sim.c), inbound = at<=length;
        ctx.globalAlpha = inbound ? 1 : .45;
        if (note.length) {
          ctx.beginPath();
          for (let j=0;j<=24;j++) { const q = sim.point(head-note.length+j*note.length/24,y); if (!j) ctx.moveTo(...q); else ctx.lineTo(...q); }
          ctx.strokeStyle = lane.color; ctx.lineWidth = 8; ctx.stroke();
          const tail = sim.point(head-note.length,y); dot(ctx,...tail,9,lane.color,false);
        }
        for (const age of [240,160,80]) {
          const q = sim.point(sim.phase(note,Math.max(0,ms-age)),y);
          ctx.globalAlpha = (inbound ? 1 : .45)*(1-age/320)*.45; dot(ctx,...q,3,lane.color);
        }
        ctx.globalAlpha = inbound ? 1 : .45;
        const q = sim.point(head,y); dot(ctx,...q,15,lane.color);
        if (sim.missedNotes.has(note.id)) { ctx.strokeStyle="#f6a397";ctx.lineWidth=2;ctx.beginPath();ctx.arc(q[0],q[1],20,0,Math.PI*2);ctx.stroke(); }
        ctx.fillStyle = "#12262c"; ctx.textAlign = "center"; ctx.font = "bold 16px Georgia"; ctx.fillText(lane.glyph,q[0],q[1]+5);
        if (sim.held.get(lane.id)?.note === note.id) { ctx.strokeStyle="#fff6df";ctx.lineWidth=3;ctx.strokeRect(q[0]-19,q[1]-19,38,38); }
        ctx.globalAlpha = 1;
      }
      const button = document.querySelector(`#pc-pad-${lane.id}`), h = sim.held.has(lane.id);
      button.dataset.held = String(h);
      button.querySelector("small").textContent = model.mode === "simplified" ? h ? "RELEASE" : "PRESS" : "KEY DOWN / UP";
    }
    document.querySelector("#pc-count").textContent = `${sim.cleared.size} / ${w.notes.length}`;
    document.querySelector("#pc-progress").style.width = `${100*sim.cleared.size/w.notes.length}%`;
    document.querySelector("#pc-misses").textContent = `${sim.missed} / ${p.miss_allowance}`;
  }
  function animate() { draw(); if (!model.terminal) frame=requestAnimationFrame(animate); }
  function render(state,helpers) {
    cancelAnimationFrame(frame);
    if (keyDown) window.removeEventListener("keydown",keyDown);
    if (keyUp) window.removeEventListener("keyup",keyUp);
    document.body.dataset.mechanic = "polyrhythm-customs-nonrealtime";
    model = {state,helpers,mode:state.control_condition?.interaction || "full",sim:new Rail(state),
      events:[],active:false,terminal:false,submitting:false,verdict:"",failure:""};
    window.polyrhythmCustomsNonRealtimeModel = model;
    helpers.app.innerHTML = `<section class="pc-root" tabindex="0" data-interaction="${model.mode}">
      <header class="pc-head"><div><p>PORT AUTHORITY / SONIC CLEARANCE</p><h1>Polyrhythm Customs V2</h1></div><aside><span>MANIFEST</span><b id="pc-count">0 / ${state.notes.length}</b><div><i id="pc-progress"></i></div></aside></header>
      <main class="pc-main"><div class="pc-stage"><div class="pc-stage-title"><span>INBOUND ← · STAMP INSIDE GOLD</span><span>RETURN → · WAIT FOR ANOTHER PASS</span></div><canvas id="pc-rail" width="960" height="456"></canvas>
      <div class="pc-welcome"><p>THE SCORE REWARDS<br>COORDINATION.</p><span>Study the notes and their moving bands.<br>Tap each head and release each ribbon at its tail.</span><button id="pc-begin">BEGIN INSPECTION</button></div></div>
      <aside class="pc-desk"><span class="pc-kicker">INSPECTOR'S KEY</span><div class="pc-legend"><b>● TAP</b><p>Press as the filled head enters gold. Release the key.</p><b>●━━○ HOLD</b><p>Press on the filled head. Keep holding until the hollow tail enters gold, then release.</p></div>
      <p class="pc-input-note">${model.mode === "full" ? "Use physical A / S / D / F keys. Hold keys together for overlapping ribbons." : "Click a pad to press it; click again to release. Several pads can stay pressed."}</p>
      <div class="pc-pad-bank">${state.lanes.map(l => `<${model.mode === "simplified" ? 'button type="button"' : 'div'} id="pc-pad-${l.id}" class="pc-pad" style="--lane:${l.color}" data-held="false"><b>${clean(l.glyph)} ${l.key}</b><small>${model.mode === "full" ? 'KEY DOWN / UP' : 'PRESS'}</small></${model.mode === "simplified" ? 'button' : 'div'}>`).join("")}</div>
      <p class="pc-failure-rule">Wrong stamp or mistimed release ends the inspection. More than ${state.parameters.miss_allowance} missed passes also ends it.</p></aside></main>
      <footer class="pc-foot"><div><div class="readout" data-status="idle">READY · ONE INSPECTION</div><div class="pc-skip-count">MISSED PASSES <b id="pc-misses">0 / ${state.parameters.miss_allowance}</b></div></div><button id="pc-seal">SEAL MANIFEST</button></footer>
      <div class="pc-verdict" hidden><strong></strong><span></span></div></section>`;
    document.querySelector("#pc-begin").addEventListener("click",begin);
    document.querySelector("#pc-seal").addEventListener("click",() => finish());
    for (const lane of state.lanes) if (model.mode === "simplified") document.querySelector(`#pc-pad-${lane.id}`).addEventListener("pointerdown",e => {
      if (e.button !== 0 || !e.isTrusted) return;
      e.preventDefault(); input(model.sim.held.has(lane.id) ? "up" : "down",lane.id,"pad_toggle");
    });
    keyDown = e => {
      if (model.mode !== "full" || !e.isTrusted || e.repeat) return;
      const lane = state.lanes.find(l => l.key.toLowerCase() === e.key.toLowerCase());
      if (!lane) return; e.preventDefault(); input("down",lane.id,"keyboard");
    };
    keyUp = e => {
      if (model.mode !== "full" || !e.isTrusted) return;
      const lane = state.lanes.find(l => l.key.toLowerCase() === e.key.toLowerCase());
      if (!lane || !model.sim.held.has(lane.id)) return; e.preventDefault(); input("up",lane.id,"keyboard");
    };
    window.addEventListener("keydown",keyDown); window.addEventListener("keyup",keyUp);
    draw(); frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.polyrhythm_customs_nonrealtime = {rootSelector:".pc-root",render};
})();
