(() => {
  "use strict";
  let model, raf;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function motion(seed, ms, span) {
    const u = Math.max(0, ms) / span, i = Math.floor(u), f = u - i;
    const a = noise(seed, i), b = noise(seed, i + 1);
    return a + (b - a) * f * f * (3 - 2 * f);
  }
  const gateY = (g, ms) => g.base_y + g.drift * motion(g.motion_seed, ms, g.span_ms);
  const complete = () => model.parcels.every(p => p.delivered);
  const clock = () => model.active ? Math.max(0, Math.floor(performance.now() - model.epoch)) : 0;
  function record(kind, extra = {}) {
    model.events.push({sequence: model.events.length + 1, kind, t_ms: clock(), ...extra});
  }
  function advance(end) {
    const s = model.state.physics;
    while (model.ms + 10 <= end && !model.failed && !complete()) {
      model.ms += 10;
      if (!model.active) continue;
      if (model.ms > s.play_time_ms) { model.failed = "The conveyor allowance ended."; break; }
      for (const p of model.parcels) {
        if (p.delivered) continue;
        const wind = s.wind * motion(p.wind_seed, model.ms, s.wind_span_ms);
        const a = clamp((p.target - p.y) * s.stiffness - p.v * s.damping + wind, -s.max_acceleration, s.max_acceleration);
        p.v = clamp(p.v + a * .01, -s.max_speed, s.max_speed);
        p.y += p.v * .01; p.x += s.belt_speed * .01;
        const r = s.radii[p.scale];
        if (p.y - r < 0 || p.y + r > model.state.room.depth) { model.failed = `${p.id} struck the room edge.`; break; }
        for (const g of model.state.gates) {
          if (Math.abs(p.x - g.x) < r + g.width / 2 - 1e-9 && Math.abs(p.y - gateY(g, model.ms)) + r > g.opening / 2 + 1e-9) {
            model.failed = `${p.id} struck ${g.id}.`; break;
          }
        }
        if (model.failed) break;
        const g = model.state.gates[p.transfers], next = Math.min(2, p.scale + 1);
        if (p.x > g.x + g.width / 2 + s.radii[next] + .01) {
          p.transfers += 1;
          if (p.transfers === 3) p.delivered = true;
          else p.scale = next;
        }
      }
      for (let i = 0; i < model.parcels.length; i++) for (const q of model.parcels.slice(i + 1)) {
        const p = model.parcels[i];
        const extent=s.radii[p.scale]+s.radii[q.scale]-1e-9;
        if (!p.delivered && !q.delivered && Math.abs(p.x-q.x)<extent && Math.abs(p.y-q.y)<extent) model.failed = "The parcels collided.";
      }
    }
  }
  function sync() { if (model.active && !model.ended) advance(clock()); }
  function point(view, x, y, z = 0) {
    return [view.origin[0] + view.matrix[0][0] * x + view.matrix[0][1] * y,
            view.origin[1] + view.matrix[1][0] * x + view.matrix[1][1] * y - z];
  }
  function polygon(ctx, points, fill, stroke) {
    ctx.beginPath(); points.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.closePath();
    ctx.fillStyle = fill; ctx.fill(); ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke();
  }
  function floorRect(ctx, view, x, y, w, h, color, height = 0) {
    const corners = [[x-w/2,y-h/2],[x+w/2,y-h/2],[x+w/2,y+h/2],[x-w/2,y+h/2]];
    const base = corners.map(p => point(view, ...p)), top = corners.map(p => point(view, ...p, height));
    if (height) for (let i = 0; i < 4; i++) polygon(ctx, [base[i],base[(i+1)%4],top[(i+1)%4],top[i]], "#353852", "#798093");
    polygon(ctx, top, color, "#9ca3b2");
  }
  function aperture(ctx, view, g, y, future = false) {
    const a = point(view,g.x,Math.max(0,y-g.opening/2)), b = point(view,g.x,Math.min(model.state.room.depth,y+g.opening/2));
    ctx.save(); ctx.strokeStyle = future ? "#f4df9877" : "#ffe9a7";
    ctx.lineWidth = future ? 1.5 : 2.5; if (future) ctx.setLineDash([3,3]);
    ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
    for (const p of [a,b]) { ctx.beginPath(); ctx.arc(...p,3,0,Math.PI*2); ctx.stroke(); }
    ctx.restore();
  }
  function draw(view) {
    const c = document.querySelector(`.rd-world[data-view="${view.index}"]`), ctx = c.getContext("2d");
    ctx.clearRect(0,0,c.width,c.height);
    const room = model.state.room, ms = model.ms;
    floorRect(ctx,view,room.width/2,room.depth/2,room.width,room.depth,"#20283d");
    ctx.strokeStyle = "#8aa0b522";
    for (let x=0;x<=room.width;x+=10) { const a=point(view,x,0),b=point(view,x,room.depth); ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke(); }
    for (let y=0;y<=room.depth;y+=12) { const a=point(view,0,y),b=point(view,room.width,y);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke(); }
    // The same canonical rectangles are used for collision and wall rendering.
    for (const g of model.state.gates) {
      const y = gateY(g,ms), lo = Math.max(0,y-g.opening/2), hi = Math.min(room.depth,y+g.opening/2);
      if (lo>0) floorRect(ctx,view,g.x,lo/2,g.width,lo,"#686075",8);
      if (hi<room.depth) floorRect(ctx,view,g.x,(hi+room.depth)/2,g.width,room.depth-hi,"#686075",8);
      aperture(ctx,view,g,y);
      aperture(ctx,view,g,gateY(g,ms+model.state.physics.preview_ms),true);
      const label=point(view,g.x,room.depth+8);
      ctx.fillStyle="#e6d9bb";ctx.font="bold 10px sans-serif";ctx.fillText(g.from_scale===2?"EXIT":`${g.from_scale+1} → ${g.to_scale+1}`,label[0]-10,label[1]);
    }
    for (const p of model.parcels) {
      const meta=model.state.parcels.find(a=>a.id===p.id), r=model.state.physics.radii[p.scale];
      ctx.save();ctx.globalAlpha=p.delivered?.4:view.index===p.scale?1:.38;
      const q=point(view,p.x,p.y), vx=point(view,p.x,p.y+p.v*.5);
      ctx.strokeStyle=meta.color;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(...q);ctx.lineTo(...vx);ctx.stroke();
      // Draw the actual square collision footprint and its finite crate height.
      floorRect(ctx,view,p.x,p.y,2*r,2*r,meta.color,5+r);
      const top=point(view,p.x,p.y,5+r);
      ctx.fillStyle="#101b2a";ctx.font="bold 9px sans-serif";ctx.fillText(String(meta.label[0]),top[0]-3,top[1]+3);
      ctx.restore();
    }
    // An original miniature of the three-room machine communicates recursion.
    const inset=[point(view,108,10),point(view,120,10),point(view,120,22),point(view,108,22)];
    polygon(ctx,inset,"#141927","#8b91b6");
    ctx.fillStyle="#939cae";ctx.font="10px sans-serif";ctx.fillText("ONE ROOM · LINKED COPIES",12,305);
  }
  function paint() {
    model.state.views.forEach(draw);
    model.parcels.forEach((p,i) => {
      const rail=document.querySelector(`.rd-rail[data-index="${i}"]`), knob=rail.querySelector(".rd-handle");
      knob.style.left=`${(p.target-7)/58*100}%`;
      rail.dataset.delivered=String(p.delivered);
      const state=document.querySelector(`.rd-cargo-state[data-index="${i}"]`);
      state.textContent=p.delivered?"DELIVERED":`${["MINIATURE","HUMAN","GIANT"][p.scale]} · ${p.transfers}/3 FRAMES`;
      const wind=model.state.physics.wind*motion(p.wind_seed,model.ms,model.state.physics.wind_span_ms);
      const needle=document.querySelector(`.rd-wind[data-index="${i}"] i`);
      needle.style.transform=`rotate(${wind/model.state.physics.wind*65}deg)`;
    });
    document.querySelector("#rd-start").disabled=model.active||model.ended;
  }
  function payload() {
    return {mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
            interaction_mode:model.mode,physics_revision:model.state.physics.revision,events:model.events,
            final_t_ms:model.active?Math.max(model.ms,model.events.at(-1)?.t_ms||0):0,completed:complete()&&!model.failed};
  }
  async function finish(reason = "") {
    if (model.ended) return;
    sync();model.ended=true;model.outcome=reason||model.failed||(complete()?"delivered":"The manifest ended before delivery.");
    model.helpers.setReadout(model.outcome==="delivered"?"VERIFYING MANIFEST…":`FAIL · ${model.outcome}`,model.outcome==="delivered"?"pending":"error");
    const stamp=document.querySelector(".rd-verdict");stamp.hidden=false;
    stamp.querySelector("strong").textContent=model.outcome==="delivered"?"DELIVERED":"FAIL";
    stamp.querySelector("span").textContent=model.outcome==="delivered"?"All parcels clear of the three moving frames.":model.outcome;
    try {
      const response=await fetch("/result",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload())});
      model.result=await response.json();
      stamp.dataset.passed=String(model.result.passed===true);stamp.querySelector("strong").textContent=model.result.passed?"PASS":"FAIL";
      model.helpers.setReadout(model.result.passed?"PASS · NESTED MANIFEST SEALED":`FAIL · ${model.outcome}`,model.result.passed?"passed":"error");
    } catch (error) { model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`,"error"); }
  }
  function sample(rail,event) {
    const rect=rail.getBoundingClientRect();
    return Math.round(clamp(7+(event.clientX-rect.left)/rect.width*58,7,65)*10000)/10000;
  }
  function input(kind,i,value) {
    sync();
    if (model.ended||model.failed||(model.parcels[i].delivered&&kind!=="release")) return false;
    record(kind,{parcel_index:i,view_index:model.state.parcels[i].control_view,
                 input_source:model.mode==="full"?"tether_drag":"tether_click",value});
    if (kind==="aim"||kind==="target") model.parcels[i].target=value;
    paint();
    return true;
  }
  function animate() {
    sync();paint();
    if (!model.ended&&(model.failed||complete())) finish();
    raf=requestAnimationFrame(animate);
  }
  async function render(state,helpers) {
    cancelAnimationFrame(raf);
    model={state,helpers,mode:state.control_condition.interaction,ms:0,epoch:0,active:false,ended:false,failed:"",outcome:null,result:null,events:[],hold:null,
           parcels:state.parcels.map(p=>({...p,v:0,target:p.y,scale:0,transfers:0,delivered:false}))};
    window.recursiveDollhouseSmugglingV2Model=model;
    document.body.dataset.mechanic="recursive-dollhouse-v2";
    helpers.app.innerHTML=`<section class="rd-game"><header class="rd-head"><div><p>THE CONTRABAND CABINET / A ROOM INSIDE A ROOM</p><h1>Recursive Dollhouse Smuggling V2</h1></div><div class="rd-badge">D${state.control_condition.difficulty}<small>${model.mode.toUpperCase()}</small></div></header>
      <div class="rd-rule">${state.prompt}<br><span>The belt never stops. Rings pull sideways with inertia. Faint apertures show the drift ½ second ahead.</span></div>
      <main class="rd-rooms">${state.views.map(v=>`<article class="rd-room"><header><b>0${v.index+1}</b><h2>${v.label}</h2><span>${v.index===0?"small parcels":v.index===1?"after first frame":"after second frame"}</span></header><canvas class="rd-world" data-view="${v.index}" width="350" height="320"></canvas></article>`).join("")}</main>
      <div class="rd-controls">${state.parcels.map((p,i)=>`<article class="rd-tether" style="--cargo:${p.color}"><div class="rd-control-title"><b>${p.label}</b><span>LINKED HAND IN ${state.views[p.control_view].label}</span><span class="rd-wind" data-index="${i}" title="Current sideways wind"><i></i></span></div><div class="rd-rail" data-index="${i}"><div class="rd-handle" tabindex="-1"></div></div><div class="rd-ends"><span>BACK EDGE</span><span>FRONT EDGE</span></div><div class="rd-cargo-state" data-index="${i}"></div></article>`).join("")}</div>
      <footer class="rd-foot"><div><p>${model.mode==="full"?"Drag each colored ring along its tether rail.":"Click each tether rail to choose the same pull position."} Moving or holding a ring never stops the shutters.</p><div class="readout">Inspect and position the rings, then start the belt. One collision ends the episode.</div></div><button id="rd-start">START THE BELT</button><button id="rd-submit">SEAL MANIFEST</button></footer>
      <div class="rd-verdict" hidden><strong></strong><span></span></div></section>`;
    for (const rail of document.querySelectorAll(".rd-rail")) {
      const i=Number(rail.dataset.index);
      rail.addEventListener("pointerdown",event=>{
        if (model.ended||event.button!==0) return;
        if (model.mode==="simplified") { input("target",i,sample(rail,event));return; }
        if (!event.target.closest(".rd-handle")||model.hold!==null) return;
        event.preventDefault();if (!input("hold",i,model.parcels[i].target)) return;
        model.hold=i;rail.setPointerCapture(event.pointerId);
      });
      rail.addEventListener("pointermove",event=>{
        if (model.mode==="full"&&model.hold===i) input("aim",i,sample(rail,event));
      });
      const release=event=>{
        if (model.hold!==i) return;
        input("release",i,model.parcels[i].target);model.hold=null;
        try { rail.releasePointerCapture(event.pointerId); } catch (_) {}
      };
      rail.addEventListener("pointerup",release);rail.addEventListener("pointercancel",release);
      rail.addEventListener("lostpointercapture",release);
    }
    document.querySelector("#rd-start").addEventListener("click",()=>{
      if (model.active||model.ended||model.hold!==null) return;
      model.epoch=performance.now();model.active=true;model.ms=0;record("start",{input_source:"start_button",t_ms:0});
      helpers.setReadout("BELT RUNNING · KEEP THE COMPLETE FOOTPRINT INSIDE EACH OPENING","pending");
    });
    document.querySelector("#rd-submit").addEventListener("click",()=>finish());
    paint();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.recursive_dollhouse_smuggling_v2={rootSelector:".rd-game",render};
})();
