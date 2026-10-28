/* Source-derived fixed apertures. Waiting never advances task state. */
(() => {
  "use strict";
  const ID = "blind_dice_courier_nonrealtime", REVISION = "fixed-apertures-1";
  const DELTAS = {N:[0,-1], E:[1,0], S:[0,1], W:[-1,0]};
  const KEYS = {w:"N", arrowup:"N", d:"E", arrowright:"E", s:"S", arrowdown:"S", a:"W", arrowleft:"W"};
  let model, frame = 0, keyHandler;
  const clone = value => structuredClone(value);
  const esc = value => String(value).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll('"',"&quot;");
  function roll(o, d) {
    const [t,b,n,s,e,w] = o;
    return {N:[s,n,t,b,e,w], S:[n,s,b,t,e,w], E:[w,e,n,s,t,b], W:[e,w,n,s,b,t]}[d];
  }
  function gatePose(gate, ms, offset = 0) {
    void ms; void offset;
    const row = Number(gate.static_y);
    return {y:row, velocity:0, phase:0, a:row, b:row, next:row,
      duration_ms:0, next_duration_ms:0, index:0};
  }
  class Simulation {
    constructor(state) {
      this.world = state.world; this.position = [...this.world.start]; this.faces = [...state.initial_orientation];
      this.ms=0; this.active=false; this.pending=null; this.failed=""; this.delivered=false; this.crossings=[];
    }
    body() {
      let [x,y] = this.position, hx=.5, hy=.5, z=.5;
      if (this.pending) {
        const f=Math.max(0,Math.min(1,(this.ms-this.pending.start_ms)/this.world.roll_ms));
        const s=Math.sin(f*Math.PI/2), c=Math.cos(f*Math.PI/2), shift=.5+.5*(s-c), half=.5*(s+c);
        const [dx,dy]=DELTAS[this.pending.direction]; x+=dx*shift; y+=dy*shift;
        if (dx) hx=half; else hy=half; z=half;
      }
      return {x,y,hx,hy,z};
    }
    contact() {
      const p=this.body();
      for (const gate of this.world.gates) for (const slat of gate.slats) {
        if (Math.abs(p.x-slat.x)<p.hx+this.world.slat_thickness/2-1e-9) {
          const pose=gatePose(gate,this.ms,slat.offset_ms);
          if (Math.abs(p.y-pose.y)+p.hy>gate.gap_height/2+1e-9) return "The fixed shutter struck the die.";
        }
      }
      for (const [x,y] of this.world.pillars) {
        if (Math.abs(p.x-x)<p.hx+.5-1e-9 && Math.abs(p.y-y)<p.hy+.5-1e-9) return "The tipping die struck a pillar.";
      }
      return "";
    }
    advance(end) {
      if (!this.active || !this.pending) return;
      const settleAt=this.pending.start_ms+this.world.roll_ms, target=Math.min(end,settleAt);
      while (this.ms+10<=target && !this.failed && !this.delivered) {
        this.ms+=10; this.failed=this.contact(); if (this.failed) break;
        if (this.pending && this.ms>=this.pending.start_ms+this.world.roll_ms) {
          const previous=this.position;
          this.position=this.pending.target; this.faces=roll(this.faces,this.pending.direction); this.pending=null;
          const gate=this.world.gates.find(g=>g.column===this.position[0] && previous[0]!==this.position[0]);
          if (gate) {
            if ((gate.required_top!=null && this.faces[0]!==gate.required_top) || (gate.required_east!=null && this.faces[4]!==gate.required_east)) {
              this.failed="The arrival faces do not match the gate."; break;
            }
            if (!this.crossings.includes(gate.id)) this.crossings.push(gate.id);
          }
          if (this.position.every((v,i)=>v===this.world.goal[i]) && this.crossings.join()===this.world.gates.map(g=>g.id).join()) this.delivered=true;
        }
        if (this.ms>=this.world.play_time_ms && !this.delivered) this.failed="Dispatch time exhausted.";
      }
    }
    move(direction) {
      const [dx,dy]=DELTAS[direction], target=[this.position[0]+dx,this.position[1]+dy];
      if (target[0]<0 || target[1]<0 || target[0]>=this.world.columns || target[1]>=this.world.rows || this.world.pillars.some(p=>p.every((v,i)=>v===target[i]))) return false;
      this.pending={start_ms:this.ms,direction,target}; return true;
    }
    snapshot() {
      return clone({t_ms:this.ms,position:this.position,orientation:this.faces,crossings:this.crossings,delivered:this.delivered,failed:this.failed});
    }
  }
  // Read-only diagnostic seam for implementation tests / privileged oracles.
  // Downstream screenshot-only agents are forbidden to inspect it.
  window.BlindDiceCourierNonRealtimePhysics={Simulation,gatePose,roll};
  function record(kind, extra={}) { model.events.push({sequence:model.events.length+1,kind,t_ms:model.sim.ms,...extra}); }
  function revealed() {
    const sim=model.sim;
    return !sim.active || sim.world.orientation_visibility==="always" || (!sim.pending && sim.world.scanners.some(p=>p.every((v,i)=>v===sim.position[i])));
  }
  function sync() {
    return;
  }
  function start() {
    if (model.sim.active || model.terminal) return;
    model.sim.active=true;
    record("start",{input_source:"start_button"});
    document.querySelector(".bdc-start").disabled=true;
    model.helpers.setReadout("DISPATCH ACTIVE · FIXED APERTURES", "idle"); draw();
  }
  function move(direction, source) {
    if (model.terminal || !model.sim.active) return;
    sync(); if (model.terminal) return;
    if (model.sim.pending) { model.helpers.setReadout("ROLL IN PROGRESS", "idle"); return; }
    const accepted=model.sim.move(direction);
    record("roll",{direction,input_source:source,accepted});
    if (accepted) {
      // The existing quarter-roll remains a deterministic, action-triggered
      // transition. It settles immediately and never depends on wall time.
      model.sim.advance(model.sim.ms + model.sim.world.roll_ms);
      if (model.sim.failed || model.sim.delivered) { finish(); return; }
    }
    model.helpers.setReadout(accepted ? "ROLL SETTLED · CHOOSE THE NEXT ROLL" : "AISLE BLOCKED · DIE UNCHANGED", accepted ? "idle" : "error"); draw();
  }
  function payload() {
    return {mechanic_id:ID,revision:REVISION,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      interaction_mode:model.mode,events:clone(model.events),completed:model.sim.delivered && !model.sim.failed,
      final_t_ms:model.sim.ms,final_state:model.sim.snapshot()};
  }
  function verdict(kind, detail) {
    const root=document.querySelector(".bdc-v2"); root.dataset.verdict=kind;
    document.querySelector(".bdc-verdict").innerHTML=`<b>${kind.toUpperCase()}</b><span>${esc(detail)}</span>`;
  }
  async function finish(submitted=false) {
    if (model.terminal) return;
    model.terminal=true;
    if (submitted) record("submit",{input_source:"submit_button"});
    const failed=!model.sim.delivered || Boolean(model.sim.failed);
    // Persist the terminal outcome before awaiting transport, including reloads.
    sessionStorage.setItem(model.episodeKey, failed ? "failed" : "delivered");
    if (failed) verdict("fail",model.sim.failed || "Incomplete dispatch. Attempt ended.");
    model.helpers.setReadout(failed ? "FAIL · ATTEMPT ENDED" : "VERIFYING DISPATCH…",failed ? "error" : "pending");
    model.lastPayload=payload(); draw();
    try {
      const response=await fetch("/result",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(model.lastPayload)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result=await response.json(); model.serverGrade=result;
      if (result.passed===true && !failed) {
        verdict("pass","SEALED FREIGHT DELIVERED"); model.helpers.setReadout("PASS · DISPATCH ACCEPTED","passed");
      } else {
        sessionStorage.setItem(model.episodeKey,"failed"); verdict("fail",model.sim.failed || "Dispatch rejected. Attempt ended.");
        model.helpers.setReadout("FAIL · ATTEMPT ENDED","error");
      }
    } catch (error) {
      verdict("error",`Verification unavailable: ${error.message}`);
      model.helpers.setReadout("VERIFIER ERROR · RESULT UNCONFIRMED","error");
    }
  }
  const PIPS={1:[[0,0]],2:[[-.23,-.23],[.23,.23]],3:[[-.23,-.23],[0,0],[.23,.23]],4:[[-.23,-.23],[.23,-.23],[-.23,.23],[.23,.23]],5:[[-.23,-.23],[.23,-.23],[-.23,.23],[.23,.23],[0,0]],6:[[-.23,-.23],[-.23,0],[-.23,.23],[.23,-.23],[.23,0],[.23,.23]]};
  function drawCube(ctx, map) {
    const sim=model.sim,p=sim.body(),pending=sim.pending;
    const theta=pending ? Math.max(0,Math.min(1,(sim.ms-pending.start_ms)/sim.world.roll_ms))*Math.PI/2 : 0;
    const direction=pending?.direction, sine=Math.sin(theta),cosine=Math.cos(theta),shown=revealed();
    function transform(point) {
      let [x,y,z]=point;
      if (direction==="E") [x,z]=[x*cosine+z*sine,-x*sine+z*cosine];
      if (direction==="W") [x,z]=[x*cosine-z*sine,x*sine+z*cosine];
      if (direction==="N") [y,z]=[y*cosine-z*sine,y*sine+z*cosine];
      if (direction==="S") [y,z]=[y*cosine+z*sine,-y*sine+z*cosine];
      return [map.x(p.x+x),map.y(p.y+y),p.z+z];
    }
    const definitions=[
      {i:0,n:[0,0,1],p:(u,v)=>[u,v,.5]}, {i:1,n:[0,0,-1],p:(u,v)=>[-u,v,-.5]},
      {i:2,n:[0,-1,0],p:(u,v)=>[u,-.5,v]}, {i:3,n:[0,1,0],p:(u,v)=>[u,.5,-v]},
      {i:4,n:[1,0,0],p:(u,v)=>[.5,u,v]}, {i:5,n:[-1,0,0],p:(u,v)=>[-.5,-u,v]}
    ];
    ctx.save(); ctx.fillStyle="#050d16aa"; ctx.fillRect(map.x(p.x-p.hx)+5,map.y(p.y-p.hy)+8,2*p.hx*map.cell,2*p.hy*map.cell);
    for (const face of definitions) {
      const nz=transform(face.n.map(v=>v*.5))[2]-p.z; if (nz<1e-8) continue;
      const corners=[[-.5,-.5],[.5,-.5],[.5,.5],[-.5,.5]].map(q=>transform(face.p(...q)));
      ctx.beginPath(); corners.forEach((q,i)=>i?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1])); ctx.closePath();
      ctx.fillStyle=shown ? (face.i===0?"#fcf1d6":"#bfcbbd") : "#26394d"; ctx.fill();
      ctx.strokeStyle=shown?"#d9c094":"#7891a4";ctx.lineWidth=2;ctx.stroke();
      if (shown) {
        ctx.fillStyle="#233342";
        for (const uv of PIPS[sim.faces[face.i]]) { const q=transform(face.p(...uv));ctx.beginPath();ctx.ellipse(q[0],q[1],map.cell*.06,map.cell*.06*Math.max(.18,nz*2),0,0,Math.PI*2);ctx.fill(); }
      } else {const q=transform(face.p(0,0));ctx.fillStyle="#c3d4dd";ctx.font=`bold ${map.cell*.45}px Georgia`;ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText("?",q[0],q[1]);}
    }
    ctx.restore();
  }
  function draw() {
    if (!model) return;
    const sim=model.sim,world=sim.world,canvas=document.querySelector(".bdc-canvas"),ctx=canvas.getContext("2d");
    const cell=Math.min(55, (canvas.width-70)/world.columns, (canvas.height-140)/world.rows);
    const left=(canvas.width-world.columns*cell)/2,top=(canvas.height-world.rows*cell)/2+20;
    const map={cell,x:v=>left+(v+.5)*cell,y:v=>top+(v+.5)*cell}; model.map=map;
    const wash=ctx.createLinearGradient(0,0,canvas.width,canvas.height);wash.addColorStop(0,"#162b3a");wash.addColorStop(1,"#07151f");ctx.fillStyle=wash;ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.strokeStyle="#7b99ac";ctx.lineWidth=2;ctx.strokeRect(left,top,world.columns*cell,world.rows*cell);
    for (let y=0;y<world.rows;y++) for (let x=0;x<world.columns;x++) {
      ctx.fillStyle=(x+y)%2?"#1c3443":"#213b4b";ctx.fillRect(map.x(x)-cell/2+1,map.y(y)-cell/2+1,cell-2,cell-2);
      ctx.fillStyle="#8ca8b544";ctx.font="10px monospace";ctx.textAlign="left";ctx.fillText(`${x+1}.${y+1}`,map.x(x)-cell/2+4,map.y(y)-cell/2+12);
    }
    for (const [x,y] of world.scanners) {
      ctx.fillStyle="#62d8ca22";ctx.fillRect(map.x(x)-cell/2,map.y(y)-cell/2,cell,cell);
      ctx.strokeStyle="#69e4d3";ctx.lineWidth=2;ctx.strokeRect(map.x(x)-cell/2+6,map.y(y)-cell/2+6,cell-12,cell-12);
      ctx.fillStyle="#8ee8da";ctx.textAlign="center";ctx.font="bold 10px monospace";ctx.fillText("SCAN",map.x(x),map.y(y)+4);
    }
    for (const [x,y] of world.pillars) {ctx.fillStyle="#070f18";ctx.fillRect(map.x(x)-cell/2,map.y(y)-cell/2,cell,cell);ctx.strokeStyle="#698292";ctx.lineWidth=2;ctx.strokeRect(map.x(x)-cell/2+1,map.y(y)-cell/2+1,cell-2,cell-2);ctx.fillStyle="#587585";ctx.fillRect(map.x(x)-cell/2+6,map.y(y)-cell/2+6,cell-12,5);}
    const [gx,gy]=world.goal;ctx.fillStyle="#5ad5a533";ctx.fillRect(map.x(gx)-cell/2,map.y(gy)-cell/2,cell,cell);ctx.fillStyle="#92ecc4";ctx.font="bold 10px monospace";ctx.textAlign="center";ctx.fillText("DOCK",map.x(gx),map.y(gy)+4);
    for (const gate of world.gates) {
      for (const slat of gate.slats) {
        const pose=gatePose(gate,sim.ms,slat.offset_ms),x=map.x(slat.x),a=map.y(pose.y-gate.gap_height/2),b=map.y(pose.y+gate.gap_height/2),half=world.slat_thickness*cell/2;
        // A narrow stroke is the actual collider; the dashed rail behind it is a guide.
        ctx.strokeStyle=`${gate.color}50`;ctx.lineWidth=1;ctx.setLineDash([3,5]);ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,top+world.rows*cell);ctx.stroke();ctx.setLineDash([]);
        ctx.fillStyle=gate.color;ctx.fillRect(x-half,top,half*2,Math.max(0,a-top));ctx.fillRect(x-half,Math.min(top+world.rows*cell,b),half*2,Math.max(0,top+world.rows*cell-b));
        ctx.strokeStyle=`${gate.color}80`;ctx.lineWidth=2;ctx.beginPath();
        for (let dt=-600;dt<=0;dt+=50) {const q=gatePose(gate,sim.ms,slat.offset_ms); if(dt===-600)ctx.moveTo(x-13,map.y(q.y));else ctx.lineTo(x-13,map.y(q.y));}ctx.stroke();
        ctx.fillStyle=gate.color;ctx.beginPath();ctx.arc(x-13,map.y(pose.y),3,0,Math.PI*2);ctx.fill();
      }
      const pose=gatePose(gate,sim.ms),x=map.x(gate.column),labelY=top-31;
      ctx.fillStyle=gate.color;ctx.textAlign="center";ctx.font="bold 13px monospace";ctx.fillText(`${gate.required_top==null?"ANY FACE":`T${gate.required_top}`}${gate.required_east==null?"":` · E${gate.required_east}`}`,x,labelY);
      ctx.font="10px monospace";ctx.fillText(sim.crossings.includes(gate.id)?"STAMPED":"ON ARRIVAL",x,labelY+15);
      // The donor track remains in the contract, but this counterpart exposes
      // only the fixed collision row to avoid implying autonomous motion.
      const hud=document.querySelector(`[data-gate="${gate.id}"]`);
      hud.querySelector(".bdc-sweep").textContent=`FIXED ROW ${pose.y.toFixed(2)} · ACTION-SETTLED`;
      const rail=hud.querySelector(".bdc-rail");
      for (const [name,value] of [["from",pose.a],["to",pose.b],["next",pose.next],["now",pose.y]]) rail.querySelector(`[data-mark="${name}"]`).style.left=`${(value+.5)/world.rows*100}%`;
      hud.querySelector(".bdc-phase i").style.width=`${pose.phase*100}%`;
      hud.dataset.stamped=String(sim.crossings.includes(gate.id));
    }
    drawCube(ctx,map);
    const labels=["TOP","BOTTOM","NORTH","SOUTH","EAST","WEST"],show=revealed();
    document.querySelector(".bdc-net").innerHTML=labels.map((label,i)=>`<span>${label}<b>${show?sim.faces[i]:"?"}</b></span>`).join("");
    document.querySelector(".bdc-seal-status").textContent=!sim.active?"INITIAL SEAL OPEN":world.orientation_visibility==="always"?"FACES VISIBLE":show?"SCANNER LIVE":"SEALED · TRACK THE ROLLS";
    document.querySelector(".bdc-count").textContent=`${sim.crossings.length}/${world.gates.length}`;
    document.querySelector(".bdc-position").textContent=`${sim.position[0]+1}.${sim.position[1]+1}`;
    document.querySelectorAll(".bdc-direction").forEach(b=>b.disabled=!sim.active || model.terminal);
    document.querySelector(".bdc-start").disabled=sim.active || model.terminal;
    document.querySelector(".bdc-submit").disabled=model.terminal;
    document.querySelector(".bdc-v2").dataset.active=String(sim.active);
  }
  function animate() { draw(); frame=requestAnimationFrame(animate); }
  async function render(state, helpers) {
    cancelAnimationFrame(frame);if(keyHandler)window.removeEventListener("keydown",keyHandler);
    document.body.dataset.mechanic=ID;
    const mode=state.control_condition?.interaction || "full";
    model={state:clone(state),helpers,mode,sim:new Simulation(state),events:[],terminal:false,
      episodeKey:`${ID}:episode:${state.task_id}`};
    window.blindDiceCourierNonRealtimeModel=model;
    helpers.app.innerHTML=`<section class="bdc-v2" data-interaction="${mode}" data-verdict=""><header><div><small>ORIENTATION-SEALED FREIGHT / FIXED APERTURES</small><h1>Blind Dice Courier V2</h1></div><div class="bdc-badge">D6<br><b>COURIER</b></div></header>
      <div class="bdc-main"><div class="bdc-floor"><canvas class="bdc-canvas" width="920" height="520"></canvas><div class="bdc-controls">${mode==="simplified"?Object.keys(DELTAS).map(d=>`<button class="bdc-direction" data-direction="${d}">${{N:"↑ NORTH",E:"→ EAST",S:"↓ SOUTH",W:"← WEST"}[d]}</button>`).join(""):"<b>WASD / ARROWS</b><span>One press = one roll. Release between rolls.</span>"}</div></div>
      <aside><h2>DISPATCH RULES</h2><p>Cross every gate, then reach <b>DOCK</b>. ${state.world.gates.some(g=>g.required_top!=null)?`Match <b>${state.world.gates.some(g=>g.required_east!=null)?"TOP / EAST":"TOP"} on arrival</b>. Fixed shutter contact or a wrong face ends the dispatch.`:"Any face is accepted. Fixed shutter contact ends the dispatch."}</p><p>One press settles a <b>${state.world.roll_ms/1000}s</b> quarter-roll. Waiting between rolls leaves the fixed apertures unchanged. ${state.world.orientation_visibility==="always"?"Faces stay visible.":"Scanners reveal faces."}</p>
      <small class="bdc-seal-status"></small><div class="bdc-net"></div><div class="bdc-ledger"><span>GATES <b class="bdc-count"></b></span><span>POSITION <b class="bdc-position"></b></span></div>
      <div class="bdc-departure">DEPARTURE SEAL: T${state.initial_orientation[0]} N${state.initial_orientation[2]} E${state.initial_orientation[4]}<small>Fixed aperture rows are visible. Opposites sum to 7.</small></div>
      <div class="bdc-gates">${state.world.gates.map(g=>`<article data-gate="${g.id}" style="--gate:${g.color}"><b>GATE ${g.id.split("-")[1]} · ${g.required_top==null?"ANY FACE":`TOP ${g.required_top}`}${g.required_east==null?"":` / EAST ${g.required_east}`}</b><small class="bdc-sweep"></small><div class="bdc-rail"><i data-mark="from"></i><i data-mark="to"></i><i data-mark="next"></i><i data-mark="now"></i></div><div class="bdc-phase"><i></i></div></article>`).join("")}</div>
      <div class="bdc-legend">● fixed row.<br>Action-settled quarter-rolls; waiting is inert.<br>Solid = shutter; dashed = guide.${state.world.gates.some(g=>g.slats.length>1)?"<br>Two offset shutter slats remain part of the gate.":""}</div></aside></div>
      <footer><div class="readout">Inspect the faces and route, then start dispatch.</div><button class="bdc-start">START DISPATCH</button><button class="bdc-submit">SUBMIT</button></footer><div class="bdc-verdict" aria-live="assertive"></div></section>`;
    document.querySelector(".bdc-start").addEventListener("click",start);
    document.querySelector(".bdc-submit").addEventListener("click",()=>{sync();if(!model.terminal)finish(true);});
    document.querySelectorAll(".bdc-direction").forEach(b=>b.addEventListener("click",()=>move(b.dataset.direction,"direction_buttons")));
    keyHandler=event=>{if(mode!=="full" || event.repeat || event.ctrlKey || event.metaKey || event.altKey)return;const d=KEYS[event.key.toLowerCase()];if(d){event.preventDefault();move(d,"keyboard");}};
    window.addEventListener("keydown",keyHandler);
    if(sessionStorage.getItem(model.episodeKey)) {
      model.terminal=true;verdict("fail","This browser episode has ended. Reload cannot reset the dispatch.");helpers.setReadout("FAIL · EPISODE ALREADY ENDED","error");
    }
    draw();
    frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics[ID]={rootSelector:".bdc-v2",render};
})();
