(() => {
  'use strict';
  const ID = 'flip_gate_cascade_v3', REVISION = 'cascade-inspection-3';
  const clamp = (x, low, high) => Math.max(low, Math.min(high, x));
  const esc = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  let model, frame = 0;
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function wind(w, ms) {
    const u = Math.max(0, ms) / w.wind_span_ms, n = Math.floor(u), f = u - n;
    const a = noise(w.wind_seed, n), b = noise(w.wind_seed, n + 1);
    return w.wind_acceleration * (a + (b - a) * f * f * (3 - 2 * f));
  }
  class Physics {
    constructor(w) {
      this.w = structuredClone(w); this.ms = 0; this.run_start = null;
      this.x = this.target = 480; this.vx = 0; this.orientation = 0; this.gates = w.initial_gates.slice();
      this.balls = {}; this.released = 0; this.caught = []; this.contacts = [];
      this.flips = []; this.failed = ''; this.done = false;
    }
    get width() { return this.w.pockets * this.w.pocket_width + (this.w.pockets - 1) * this.w.divider_width; }
    pocket_offset(kind) { return this.w.pockets === 1 ? 0 : (kind === this.orientation ? -1 : 1) * (this.w.pocket_width + this.w.divider_width) / 2; }
    start() {
      if (this.run_start !== null) throw new Error('A cascade can start only once');
      this.run_start = this.ms;
    }
    latch() {
      if (this.failed || this.done) return false;
      const w=this.w, balls=Object.values(this.balls).filter(b=>b.phase==='free'&&w.capture_top<=b.y-b.radius&&b.y+b.radius<=w.rim_y);
      if(this.run_start===null||!balls.length) {this.failed='EMPTY LATCH';return false;}
      const b=balls.sort((a,b)=>b.y-a.y)[0], center=this.x+this.pocket_offset(b.kind);
      const valid=Math.abs(b.x-center)+b.radius<=w.pocket_width/2+1e-7;
      this.contacts.push({id:b.id,t_ms:this.ms,x:b.x,y:b.y,catcher:this.x,pocket:b.kind,caught:valid,via:'latch'});
      if(valid) {this.caught.push(b.id);delete this.balls[b.id];this.done=this.caught.length===w.marbles.length;}
      else this.failed='MISALIGNED OR WRONG-POCKET LATCH';
      return valid;
    }
    release(spec) {
      const column = this.w.entry_columns[spec.chute], first = this.w.gates[column], mouth = this.w.gates[spec.chute];
      this.balls[spec.id] = {...spec, row:-1, column, phase:'rail',
        segment_start:this.ms, segment_ms:this.w.rail_ms, ax:mouth.x, ay:20,
        bx:first.x, by:first.y, x:mouth.x, y:20, vx:(first.x-mouth.x)*1000/this.w.rail_ms,
        vy:(first.y-20)*1000/this.w.rail_ms, trail:[]};
      this.released++;
    }
    advance(end) {
      const w = this.w;
      while (this.ms + 10 <= end && !this.failed && !this.done) {
        this.ms += 10;
        const before = this.x;
        const a = clamp((this.target-this.x)*60-this.vx*14,-w.basket_acceleration,w.basket_acceleration);
        this.vx = clamp(this.vx+a*.01,-w.basket_speed,w.basket_speed);
        this.x = clamp(this.x+this.vx*.01,w.wall_left+this.width/2,w.wall_right-this.width/2);
        if (this.x === w.wall_left+this.width/2 || this.x === w.wall_right-this.width/2) this.vx = 0;
        if (this.run_start === null) continue;
        const elapsed = this.ms-this.run_start;
        for (const spec of w.marbles) if (spec.id >= this.released && elapsed >= spec.release_ms) this.release(spec);
        for (const [id, b] of Object.entries(this.balls)) {
          if (this.ms % 50 === 0) { b.trail.push([this.ms,b.x,b.y]); b.trail = b.trail.filter(p => p[0] >= this.ms-300); }
          if (b.phase === 'rail') {
            const fraction = Math.min(1,(this.ms-b.segment_start)/b.segment_ms);
            b.x = b.ax+(b.bx-b.ax)*fraction; b.y = b.ay+(b.by-b.ay)*fraction;
            if (fraction < 1) continue;
            if (b.row === w.rows-1) { Object.assign(b,{phase:'free',vx:b.exit_sign*w.exit_vx,vy:w.initial_vy}); continue; }
            const row = b.row+1, column = b.column, gate = w.offsets[row]+column, direction = this.gates[gate];
            this.gates[gate] = 1-direction;
            this.flips.push({id:Number(id),gate,before:direction,t_ms:this.ms});
            Object.assign(b,{row,column:column+direction,segment_start:this.ms,ax:b.x,ay:b.y});
            if (row+1 < w.rows) {
              const dest = w.gates[w.offsets[row+1]+column+direction];
              Object.assign(b,{bx:dest.x,by:dest.y,segment_ms:w.rail_ms});
            } else {
              const sign = direction ? 1 : -1;
              Object.assign(b,{bx:b.x+sign*w.spacing/2,by:280,segment_ms:600,exit_sign:sign});
            }
            b.vx = (b.bx-b.ax)*1000/b.segment_ms; b.vy = (b.by-b.ay)*1000/b.segment_ms;
            continue;
          }
          const oldX = b.x, oldY = b.y, r = b.radius;
          b.vx += (wind(w,elapsed)*b.wind_scale-.12*b.vx)*.01;
          b.vy += w.gravity*.01; b.x += b.vx*.01; b.y += b.vy*.01;
          const lo = w.wall_left+r, hi = w.wall_right-r;
          if (b.x < lo || b.x > hi) { b.x = b.x < lo ? 2*lo-b.x : 2*hi-b.x; b.vx *= -.65; }
          if (oldY+r < w.rim_y && b.y+r >= w.rim_y) {
            const f = (w.rim_y-r-oldY)/(b.y-oldY), impact = oldX+(b.x-oldX)*f;
            const catcher = before+(this.x-before)*f;
            this.contacts.push({id:Number(id),t_ms:this.ms,x:impact,y:w.rim_y-r,catcher,pocket:b.kind,caught:false,via:'escape'});
            b.x = impact; b.y = w.rim_y-r; this.failed = 'MARBLE ESCAPED — LATCH BEFORE THE FLOOR'; break;
          }
        }
        this.done = this.caught.length === w.marbles.length;
        if (elapsed > w.run_limit_ms && !this.done) this.failed = 'CASCADE ENDED';
      }
    }
    claims() { return {caught_ids:this.caught.slice(),final_gates:this.gates.slice(),
      completed:this.done&&!this.failed,failed:this.failed,physics_ms:this.ms,basket_x:Math.round(this.x*10000)/10000,orientation:this.orientation}; }
  }
  // Read-only oracle/test planning surface; UI actions never call a solver.
  window.FlipGateCascadeV3Physics = Physics;
  window.FlipGateCascadeV3Wind = wind;
  function time() { return Math.max(0,Math.round(performance.now()-model.startedAt)); }
  function record(kind, input_source, details={}) {
    model.events.push({sequence:model.events.length+1,kind,input_source,t_ms:model.physics.ms,...details});
  }
  function sync() {
    if (!model.terminal) model.physics.advance(time());
    draw();
    if (!model.terminal && (model.physics.done || model.physics.failed)) finish();
  }
  function point(event) {
    const r = model.canvas.getBoundingClientRect();
    return [Math.round(clamp((event.clientX-r.left)*960/r.width,0,960)*1000)/1000,
      Math.round(clamp((event.clientY-r.top)*570/r.height,0,570)*1000)/1000];
  }
  function inspect(p) {
    // A broad movable inspection light exposes the smoked wind chamber.
    // It retains its position when the pointer leaves or a drag is released.
    if(model.inspectionX!==p[0]) {
      model.inspectionX = p[0];
      record('inspect_chamber','inspection_pointer',{point:p});
    }
    const w = model.state.world;
    const chute = w.gates.slice(0,w.top_chutes).findIndex(g=>Math.abs(p[0]-g.x)<=28&&p[1]>=0&&p[1]<=25);
    if(chute<0 || model.inspected.has(chute))return;
    model.inspected.add(chute);
    record('inspect','inlet_inspection',{point:p,chute,entry_column:w.entry_columns[chute]});
  }
  function down(event) {
    if (event.button !== 0 || model.terminal || model.hold !== null) return;
    sync(); if (model.terminal) return;
    const p = point(event), phys = model.physics;
    inspect(p);
    if (model.interaction === 'simplified' && p[1] >= 495 && p[1] <= 569) {
      phys.target = p[0]; record('target','rail_click',{point:p});
    } else if (model.interaction === 'full' && Math.abs(p[0]-phys.x) <= phys.width/2 && p[1] >= 520 && p[1] <= 558) {
      model.hold = event.pointerId; model.canvas.setPointerCapture(event.pointerId);
      record('drag_start','basket_drag',{point:p});
    }
    event.preventDefault(); draw();
  }
  function move(event) {
    if (model.terminal) return;
    sync(); if (model.terminal) return;
    const p = point(event); inspect(p);
    if(model.hold !== event.pointerId){draw();return;}
    model.physics.target = p[0];
    record('drag_move','basket_drag',{point:p}); event.preventDefault(); draw();
  }
  function up(event, cancel=false) {
    if (model.hold !== event.pointerId) return;
    sync();
    if (!model.terminal) record(cancel?'drag_cancel':'drag_end','basket_drag',{point:point(event)});
    model.hold = null;
    if (model.canvas.hasPointerCapture(event.pointerId)) model.canvas.releasePointerCapture(event.pointerId);
    draw();
  }
  function start() {
    if (model.terminal || model.physics.run_start !== null) return;
    sync(); if (model.terminal) return;
    record('start','start_button'); model.physics.start();
    document.querySelector('#fcv2-start').disabled = true; draw();
  }
  function swap(source='pocket_button') {
    if (model.terminal || model.state.world.pockets !== 2) return;
    sync(); if (model.terminal) return;
    record('swap',source); model.physics.orientation = 1-model.physics.orientation; draw();
  }
  function latch(source='latch_button') {
    if(model.terminal || model.physics.run_start===null) return;
    sync(); if(model.terminal) return;
    record('latch',source);model.physics.latch();draw();
    if(model.physics.done||model.physics.failed)finish();
  }
  async function finish() {
    if (model.terminal) return;
    model.physics.advance(time()); model.terminal = true;
    record('seal','seal_button');
    const payload = {mechanic_id:ID,physics_revision:REVISION,task_id:model.state.task_id,
      challenge_id:model.state.challenge_id,interaction_mode:model.interaction,events:model.events,
      final_t_ms:model.physics.ms,...model.physics.claims()};
    model.payload = payload;
    const local = model.physics.done ? 'CAUGHT THEM ALL' : (model.physics.failed || 'INCOMPLETE CASCADE');
    showVerdict('VERIFYING',local); draw();
    try {
      const response = await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      model.grade = await response.json();
      showVerdict(model.grade.passed ? 'PASS' : 'FAIL',local);
      model.helpers.setReadout(model.grade.passed ? 'PASS' : 'FAIL',model.grade.passed?'passed':'error');
    } catch (error) { showVerdict('VERIFIER ERROR',error.message); model.grade = {error:error.message}; }
  }
  function showVerdict(word, reason) {
    const overlay = document.querySelector('.fcv2-verdict'); overlay.hidden = false;
    overlay.dataset.verdict = word; overlay.querySelector('b').textContent = word;
    overlay.querySelector('span').textContent = reason;
  }
  const colors = ['#f1b950','#60d0c9'];
  function circle(ctx,x,y,r,fill,stroke='') {
    ctx.beginPath(); ctx.arc(x,y,r,0,Math.PI*2); ctx.fillStyle=fill; ctx.fill();
    if (stroke) { ctx.strokeStyle=stroke; ctx.stroke(); }
  }
  function line(ctx,a,b,color,width) {
    ctx.strokeStyle=color; ctx.lineWidth=width; ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();
  }
  function draw() {
    if (!model?.canvas) return;
    const c = model.canvas.getContext('2d'), p = model.physics, w = p.w;
    const bg = c.createLinearGradient(0,0,0,570); bg.addColorStop(0,'#12272c');bg.addColorStop(1,'#09181d');
    c.fillStyle=bg;c.fillRect(0,0,960,570);c.lineCap='round';
    // Every displayed rail terminates at the actual simulated gate/guide point.
    for (const g of w.gates) {
      const ends = g.row+1 < w.rows ? [w.gates[w.offsets[g.row+1]+g.column],w.gates[w.offsets[g.row+1]+g.column+1]] :
        [{x:g.x-w.spacing/2,y:280},{x:g.x+w.spacing/2,y:280}];
      for (const e of ends) { line(c,[g.x,g.y],[e.x,e.y],'#364d51',12);line(c,[g.x,g.y],[e.x,e.y],'#718285',2); }
    }
    // The inlet pipes are physically concealed, as in V1. Only inspection
    // exposes their connections; no straight pipe is drawn over a cross-feed.
    c.fillStyle='#263b3e';c.fillRect(24,26,912,39);c.strokeStyle='#a08552';c.lineWidth=2;c.strokeRect(24,26,912,39);
    c.fillStyle='#d4bc86';c.font='11px monospace';c.textAlign='center';c.fillText('SEALED INLET MANIFOLD — HOVER LETTERED MOUTHS TO INSPECT',480,53);
    for(let chute=0;chute<w.top_chutes;chute++) {
      const mouth=w.gates[chute], known=model.inspected.has(chute), gate=w.gates[w.entry_columns[chute]];
      if(known)line(c,[mouth.x,20],[gate.x,gate.y],'#f6d08c',3);
      c.fillStyle=known?'#e8cc8c':'#698488';c.fillRect(mouth.x-27,0,54,25);
      c.fillStyle='#0a1d22';c.font='bold 14px monospace';c.fillText(String.fromCharCode(65+chute),mouth.x,17);
    }
    for (const g of w.gates) {
      c.lineWidth=2;circle(c,g.x,g.y,21,'#0a1417','#a08552');
      const right = p.gates[g.id] === 1, sign = right ? 1 : -1;
      line(c,[g.x-sign*15,g.y-9],[g.x+sign*15,g.y+9],right?colors[1]:colors[0],8);
      circle(c,g.x,g.y,5,'#f1d69d');
      c.fillStyle=right?colors[1]:colors[0];c.beginPath();c.moveTo(g.x+sign*19,g.y+11);c.lineTo(g.x+sign*9,g.y+10);c.lineTo(g.x+sign*14,g.y+1);c.closePath();c.fill();
      if(g.row===0){c.fillStyle='#d4bc86';c.font='11px monospace';c.textAlign='right';c.fillText(`G${g.column+1}`,g.x-25,g.y+4);}
    }
    line(c,[w.wall_left,287],[w.wall_left,519],'#b49b63',3);line(c,[w.wall_right,287],[w.wall_right,519],'#b49b63',3);
    c.fillStyle='#8aa8af';c.font='11px monospace';c.textAlign='left';c.fillText('CROSSWIND CHAMBER',40,314);
    const elapsed = p.run_start === null ? 0 : p.ms-p.run_start;
    const gust = wind(w,elapsed)/w.wind_acceleration;
    line(c,[815,307],[815+gust*80,307],'#a4d9d7',4);circle(c,815+gust*80,307,4,'#a4d9d7');
    if(model.inspectionX!==null){
      c.fillStyle='#e3d5a00b';c.fillRect(model.inspectionX-220,287,440,232);
      c.strokeStyle='#9ba88d88';c.lineWidth=1;c.setLineDash([3,6]);
      c.strokeRect(model.inspectionX-220,287,440,232);c.setLineDash([]);
    }
    c.fillStyle='#bdc6ab';c.font='11px monospace';c.textAlign='left';c.fillText('SMOKED GLASS: MOVE POINTER TO INSPECT THE FALL',40,339);
    const left = p.x-p.width/2;
    for(let k=0;k<w.pockets;k++) {
      const x=left+k*(w.pocket_width+w.divider_width),kind=w.pockets===1?0:k^p.orientation;
      c.fillStyle=colors[kind]+'0d';c.fillRect(x,w.capture_top,w.pocket_width,w.rim_y-w.capture_top);
      c.strokeStyle=colors[kind]+'aa';c.lineWidth=2;c.setLineDash([5,5]);
      c.strokeRect(x,w.capture_top,w.pocket_width,w.rim_y-w.capture_top);c.setLineDash([]);
    }
    c.fillStyle='#abc7bf';c.font='11px monospace';c.textAlign='left';c.fillText('ENTER: LATCH A MARBLE INSIDE ITS MATCHING OUTLINE',40,365);
    for (const b of Object.values(p.balls)) {
      if(b.row===-1&&b.y>25&&b.y<65&&!model.inspected.has(b.chute))continue;
      c.save();
      if(b.phase==='free'){
        c.beginPath();c.rect(model.inspectionX===null?-1000:model.inspectionX-220,287,model.inspectionX===null?0:440,232);c.clip();
      }
      c.strokeStyle=colors[b.kind]+'88';c.lineWidth=3;c.beginPath();
      b.trail.forEach((q,i)=>i?c.lineTo(q[1],q[2]):c.moveTo(q[1],q[2]));c.lineTo(b.x,b.y);c.stroke();
      c.lineWidth=2;circle(c,b.x,b.y,b.radius,colors[b.kind],'#fff1c9');circle(c,b.x-3,b.y-3,2,'#fff5cf');
      c.fillStyle='#092027'; c.font='bold 11px sans-serif';c.textAlign='center';c.fillText(b.kind?'◒':'◆',b.x,b.y+4);
      c.restore();
    }
    line(c,[24,561],[936,561],'#57656b',6);
    for (let k=0;k<w.pockets;k++) {
      const x=left+k*(w.pocket_width+w.divider_width);
      const kind = w.pockets === 1 ? 0 : k ^ p.orientation;
      c.fillStyle='#263a3e';c.fillRect(x,520,w.pocket_width,38);
      c.fillStyle=colors[kind];c.fillRect(x,520,4,38);c.fillRect(x+w.pocket_width-4,520,4,38);c.fillRect(x,551,w.pocket_width,7);
      c.fillStyle=colors[kind];c.font='bold 13px monospace';c.textAlign='center';c.fillText(kind?'◒ AQUA':'◆ AMBER',x+w.pocket_width/2,543);
    }
    if (w.pockets===2) { c.fillStyle='#b49b63';c.fillRect(left+w.pocket_width,520,w.divider_width,38); }
    if (model.hold!==null) { c.strokeStyle='#f9e7b8';c.lineWidth=2;c.strokeRect(left-4,516,p.width+8,46); }
    const count = document.querySelector('#fcv2-count');if(count)count.textContent=`${p.caught.length} / ${w.marbles.length}`;
    for(const node of document.querySelectorAll('[data-marble-id]')) { const id=Number(node.dataset.marbleId);node.dataset.phase=p.caught.includes(id)?'caught':id<p.released?'active':'queued'; }
    const map=document.querySelector('#fcv3-inlets');
    if(map)map.textContent='INLETS '+Array.from({length:w.top_chutes},(_,i)=>`${String.fromCharCode(65+i)}→${model.inspected.has(i)?'G'+(w.entry_columns[i]+1):'?'}`).join(' · ');
  }
  function animate() { if(model&&!model.terminal) sync(); frame=requestAnimationFrame(animate); }
  async function render(state,helpers) {
    cancelAnimationFrame(frame); if(model?.keyHandler)window.removeEventListener('keydown',model.keyHandler); document.body.dataset.mechanic=ID;
    const interaction=state.control_condition?.interaction||'full';
    model={state,helpers,interaction,physics:new Physics(state.world),startedAt:performance.now(),events:[],inspected:new Set(),inspectionX:null,hold:null,terminal:false,grade:null};
    window.flipGateCascadeV3Model=model;
    helpers.app.innerHTML=`<main class="fcv2"><header><div><small>THE CASCADE WORKSHOP / ${esc(state.challenge_id)}</small><h1>Flip-Gate Cascade V3</h1></div><div class="fcv2-counter"><small>SAFE IN THE CATCHER</small><b id="fcv2-count">0 / ${state.world.marbles.length}</b></div></header><section class="fcv2-main"><div class="fcv2-cabinet"><canvas id="fcv2-canvas" width="960" height="570" aria-label="Live marble cascade and catcher"></canvas></div><aside><small>AUTOMATIC FEED</small><div class="fcv2-queue">${state.world.marbles.map(b=>`<div data-marble-id="${b.id}" data-phase="queued"><i style="--marble:${colors[b.kind]}">${b.kind?'◒':'◆'}</i><span>INLET ${String.fromCharCode(65+b.chute)}</span><b>${b.id+1}</b></div>`).join('')}</div><p>Inspect mouths for routes. Vanes flip after each marble.</p><p>Steer the matching outline around a whole falling marble. Press ENTER to latch it. Empty, wrong or late latches end the attempt.</p><p class="fcv2-gesture">${interaction==='full'?'DRAG THE CATCHER':'CLICK THE BOTTOM RAIL'}<br><span>The catcher takes time to move.</span></p>${state.world.pockets===2?'<button id="fcv2-swap">SWAP POCKETS ↔</button>':''}<button id="fcv2-start">RELEASE THE STREAM</button></aside></section><footer><span id="fcv3-inlets"></span><div class="readout" data-status="idle">READY</div><button id="fcv2-latch">LATCH POCKETS / ENTER</button><button id="fcv2-seal">SEAL THE CATCH</button></footer><div class="fcv2-verdict" hidden><b></b><span></span></div></main>`;
    model.canvas=document.querySelector('#fcv2-canvas');
    model.canvas.addEventListener('pointerdown',down);model.canvas.addEventListener('pointermove',move);
    model.canvas.addEventListener('pointerup',event=>up(event));model.canvas.addEventListener('pointercancel',event=>up(event,true));
    model.canvas.addEventListener('lostpointercapture',event=>{if(model.hold===event.pointerId)up(event,true);});
    document.querySelector('#fcv2-start').addEventListener('click',start);
    const swapButton = document.querySelector('#fcv2-swap');
    if(swapButton) { swapButton.textContent='SWAP POCKETS / SPACE'; swapButton.addEventListener('click',()=>swap()); }
    model.keyHandler=event=>{if(event.repeat)return;if(event.code==='Space'&&state.world.pockets===2){event.preventDefault();swap('pocket_key');}if(event.code==='Enter'){event.preventDefault();latch('latch_key');}};
    window.addEventListener('keydown',model.keyHandler);
    document.querySelector('#fcv2-latch').addEventListener('click',()=>latch());
    document.querySelector('#fcv2-seal').addEventListener('click',finish);
    // The task-owned generator retains a committed failure when the shared
    // runtime supplies a fresh state. It never opens another playable attempt.
    if(state.episode_failure) {
      model.terminal=true;
      for(const button of helpers.app.querySelectorAll('button'))button.disabled=true;
      showVerdict('FAIL','THE FIRST FAILED CASCADE ENDED THIS EPISODE');
      helpers.setReadout('FAIL','error');
    }
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.fcv2',render};
})();
