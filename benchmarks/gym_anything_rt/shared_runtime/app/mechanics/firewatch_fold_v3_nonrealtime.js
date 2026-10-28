(() => {
  'use strict';
  let model, frame, keyHandler;
  const W = 1200, H = 560, left = 56, cell = 76, faceGap = 56;
  const noise = (seed, index) => {
    let x = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  };
  function motion(seed, ms, span) {
    const u = Math.max(0, ms) / span, n = Math.floor(u), f = u - n;
    const a = noise(seed, n), b = noise(seed, n + 1);
    return a + (b - a) * f * f * (3 - 2 * f);
  }
  function integral(seed, ms, span) {
    const u = Math.max(0, ms) / span, n = Math.floor(u), f = u - n;
    let total = 0;
    for (let i = 0; i < n; i++) total += (noise(seed, i) + noise(seed, i + 1)) / 2;
    const a = noise(seed, n), b = noise(seed, n + 1);
    return span * (total + a * f + (b - a) * (f ** 3 - f ** 4 / 2));
  }
  const mod = (x, w) => ((x % w) + w) % w;
  function fireX(f, tick) {
    const w = model.state.world, ms = tick * w.tick_ms;
    return mod(f.x + f.direction * f.speed * (ms + f.variation * integral(f.wind_seed, ms, f.span_ms)) / 1000, 2 * w.width);
  }
  function velocity(f, tick) {
    const w = model.state.world;
    return f.direction * f.speed * (1 + f.variation * motion(f.wind_seed, tick * w.tick_ms, f.span_ms));
  }
  const dist = (a, b) => {
    const w = model.state.world.width;
    return Math.abs(mod(a - b + w, 2 * w) - w);
  };
  function advance(target) {
    const s = model.sim, w = model.state.world;
    while (s.tick < target && s.started && !s.failure && !s.rescued) {
      s.tick++;
      if (s.pulse) {
        const p = s.pulse, travel = Math.min(w.pulse_reach, (s.tick - p.tick) * w.tick_ms / 1000 * w.pulse_speed);
        const x = mod(p.x + p.direction * travel, 2 * w.width);
        const hits = w.fires.filter(f => f.floor === p.floor && !s.cleared.includes(f.id) && dist(x, fireX(f, s.tick)) <= f.radius + w.pulse_radius);
        hits.sort((a, b) => dist(x, fireX(a, s.tick)) - dist(x, fireX(b, s.tick)) || a.id.localeCompare(b.id));
        if (hits.length) {
          if(hits[0].color!==p.color)s.failure='WRONG CANISTER — FIRST CORE NEEDS ITS MATCHING COLOR';
          else{s.cleared.push(hits[0].id);s.cleared.sort();}s.pulse=null;
        }
        else if (travel >= w.pulse_reach) { s.failure = 'MISSED PULSE — STOCK CANNOT CONTAIN ALL FRONTS'; s.pulse = null; }
      }
      if (s.tick >= w.max_ticks && !s.rescued) s.failure = 'RESCUE WINDOW CLOSED';
    }
  }
  const DEFAULT_ACTION_TRANSITION_TICKS = 30;
  function update() {
    if (!model || model.terminal) return;
    if (model.sim.failure) finish(false);
  }
  function action(kind, direction, source) {
    if (model.terminal) return;
    const s = model.sim, w = model.state.world;
    let outcome;
    if (kind === 'start') {
      if (s.started) outcome = 'already_started';
      else { s.started = true; outcome = 'started'; }
    } else if (kind === 'inspect') {
      s.view = 1 - s.view;
      if (!s.surveyed_faces.includes(s.view)) {
        s.surveyed_faces.push(s.view); s.surveyed_faces.sort();
      }
      outcome = 'inspected';
    }
    else if(kind==='select'){s.selected=direction;outcome='selected';}
    else if (!s.started) outcome = 'scouting_only';
    else if (kind === 'move') {
      if (s.tick - s.last_move < w.move_cooldown_ticks) outcome = 'cooldown';
      else {
        s.last_move = s.tick;
        const [floor, x] = s.player;
        if (direction === 'LEFT' || direction === 'RIGHT') {
          s.facing = direction === 'LEFT' ? -1 : 1;
          s.player[1] = mod(x + s.facing, 2 * w.width); s.view = Math.floor(s.player[1] / w.width);
          outcome = s.view !== Math.floor(x / w.width) ? 'seam_crossed' : 'walked';
        } else {
          const lower = direction === 'UP' ? floor : floor - 1;
          if (lower < 0 || lower >= w.floors - 1 || !w.ladders[lower].includes(x)) outcome = 'no_ladder';
          else if (w.fires.some(f => f.floor === lower && !s.cleared.includes(f.id))) outcome = 'thermal_lock';
          else { s.player[0] += direction === 'UP' ? 1 : -1; outcome = 'climbed'; }
        }
      }
    } else if (kind === 'fire') {
      if (s.pulse) outcome = 'pulse_in_flight';
      else if (s.cartridges[s.selected] <= 0) outcome = 'empty';
      else { s.stock--;s.cartridges[s.selected]--; s.pulse = {tick:s.tick, floor:s.player[0], x:s.player[1] + .5, direction:s.facing,color:s.selected}; outcome = 'fired'; }
    }
    const event = {sequence:model.events.length + 1, tick:s.tick, kind, input_source:source, outcome};
    if (kind === 'move'||kind==='select') event.direction = direction;
    // Counterpart timing rule: a deliberate action settles one fixed
    // transition. Nothing advances between actions or during observation.
    const transitionTicks = Number.isInteger(w.action_transition_ticks)
      ? w.action_transition_ticks : DEFAULT_ACTION_TRANSITION_TICKS;
    if (s.started && !s.failure && !s.rescued) {
      advance(Math.min(w.max_ticks, s.tick + transitionTicks));
    }
    event.settle_tick = s.tick;
    model.events.push(event);
    model.message = ({inspected:`${s.view===0?'COPPER':'INDIGO'} PLAN REVEALED · LADDER AND RESIDENT LOCATIONS SAVED`, thermal_lock:'LADDER LOCKED · CONTAIN THIS FLOOR', no_ladder:'NO LADDER HERE', scouting_only:'SCOUTING · START TO MOVE', fired:'WATER IN FLIGHT', pulse_in_flight:'WAIT FOR THE PULSE', climbed:'LADDER CLEAR', seam_crossed:'CROSSED THE FOLD'}[outcome] || outcome.replaceAll('_',' ').toUpperCase());
    if (s.failure) finish(false);
    draw();
  }
  function snapshot() {
    const s = model.sim;
    return Object.fromEntries(['tick','started','player','facing','view','surveyed_faces','stock','cleared','failure','rescued','selected','cartridges'].map(k => [k, s[k]]));
  }
  async function finish(completed) {
    if (model.terminal) return;
    model.terminal = true;
    const s = model.sim, w = model.state.world;
    const reached = JSON.stringify(s.player) === JSON.stringify(w.resident) && s.cleared.length === w.fires.length && !s.pulse;
    s.rescued = completed && reached && !s.failure;
    const payload = {mechanic_id:model.state.mechanic_id, task_id:model.state.task_id,
      challenge_id:model.state.challenge_id, interaction_mode:model.interaction, events:model.events,
      final_tick:s.tick, final_state:snapshot(), completed:s.rescued};
    model.payload = payload;
    document.getElementById('fw2-verdict').textContent = s.rescued ? 'RESCUE COMPLETE' : 'FAIL · ' + (s.failure || 'RESIDENT NOT REACHED');
    document.getElementById('fw2-verdict').className = s.rescued ? 'passed' : 'failed';
    draw();
    try {
      const response = await fetch('/result', {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const result = await response.json(); model.grade = result;
      model.helpers.setReadout(result.passed ? 'PASS · RESCUE VERIFIED' : 'FAIL · ATTEMPT ENDED', result.passed ? 'passed' : 'error');
      document.getElementById('fw2-verdict').textContent = result.passed ? 'PASS · RESIDENT RESCUED' : 'FAIL · ' + (s.failure || 'RESCUE INCOMPLETE');
      document.getElementById('fw2-verdict').className = result.passed ? 'passed' : 'failed';
      // Deliberately retain the terminal scene. A server-issued replacement
      // does not erase the episode failure ledger or reopen this attempt.
    } catch (error) { model.helpers.setReadout('VERIFIER UNAVAILABLE · ' + error.message, 'error'); }
  }
  function floorY(floor) { return 516 - floor * (450 / (model.state.world.floors - 1)); }
  function label(ctx, text, x, y, color='#f4dbc0', font='12px sans-serif') {
    ctx.fillStyle=color; ctx.font=font; ctx.fillText(text,x,y);
  }
  function drawFace(ctx, face) {
    const s = model.sim, w = model.state.world, base = face * w.width;
    const paneLeft = left + face * (w.width * cell + faceGap);
    const focused = s.view === face;
    const surveyed = s.surveyed_faces.includes(face);
    ctx.strokeStyle = focused ? '#e4bb76' : '#4b6874'; ctx.lineWidth = focused ? 3 : 1;
    ctx.strokeRect(paneLeft-2,24,w.width*cell+4,H-32);
    label(ctx, (face===0?'COPPER FACE':'INDIGO FACE')+(focused?' · HIGHLIGHTED':'')+(surveyed?' · PLAN SAVED':' · PLAN CONCEALED'),paneLeft+9,18,focused?'#ffce91':'#94c2d5','bold 15px sans-serif');
    ctx.strokeStyle='#4a5c60'; ctx.lineWidth=2;
    for (let i=0;i<=w.width;i++) {ctx.beginPath();ctx.moveTo(paneLeft+i*cell,24);ctx.lineTo(paneLeft+i*cell,H-14);ctx.stroke();}
    for (let floor=0;floor<w.floors;floor++) {
      const y=floorY(floor), clear=!w.fires.some(f => f.floor===floor && !s.cleared.includes(f.id));
      ctx.fillStyle='#34444a';ctx.fillRect(paneLeft,y+12,w.width*cell,10);
      ctx.fillStyle='#1a272e';ctx.fillRect(paneLeft,y-28,w.width*cell,54);
      ctx.fillStyle=clear?'#72cdb5':'#d77c4e';ctx.fillRect(paneLeft,y+12,w.width*cell,4);
      label(ctx, `${floor+1}F`, paneLeft-44,y+6, '#b8c5ca','bold 16px sans-serif');
      label(ctx, clear?'OPEN':'LOCK', paneLeft-48,y+23,clear?'#8fddbd':'#efa766','9px monospace');
      for (const x of surveyed ? w.ladders[floor] || [] : []) {
        if (Math.floor(x/w.width)!==face) continue;
        const xx=paneLeft+(x-base+.5)*cell, yy=floorY(floor+1);
        ctx.strokeStyle=clear?'#93d8bb':'#95584e';ctx.lineWidth=3;
        ctx.beginPath();ctx.moveTo(xx-13,y+8);ctx.lineTo(xx-13,yy+26);ctx.moveTo(xx+13,y+8);ctx.lineTo(xx+13,yy+26);ctx.stroke();
        for(let rung=yy+30;rung<y;rung+=12){ctx.beginPath();ctx.moveTo(xx-13,rung);ctx.lineTo(xx+13,rung);ctx.stroke();}
      }
      for(let x=0;x<w.width;x++) label(ctx,`${x+1}`,paneLeft+(x+.5)*cell-3,y+37,'#7d989f','10px monospace');
      if (!surveyed) label(ctx, floor===w.floors-1?'RESIDENT LOCATION CONCEALED · ◉ INSPECT FACE':'LADDER PLAN CONCEALED · ◉ INSPECT FACE',paneLeft+12,y-10,'#bed4da','bold 12px sans-serif');
    }
    // Flames circulate in the exterior fire gutter; the shielded catwalk is
    // separate. The bright core circle is exactly the collision geometry.
    ctx.save();ctx.beginPath();ctx.rect(paneLeft,0,w.width*cell,H);ctx.clip();
    for (const f of w.fires) {
      if (s.cleared.includes(f.id)) continue;
      const y=floorY(f.floor)-58;
      for(let age=600;age>=120;age-=120){
        const px=fireX(f,Math.max(0,s.tick-age/w.tick_ms));
        if(Math.floor(px/w.width)===face){const rgb=[[235,130,60],[70,186,203],[220,108,170]][f.color];ctx.fillStyle=`rgba(${rgb.join(',')},${.08+(600-age)/1800})`;ctx.beginPath();ctx.arc(paneLeft+(px-base)*cell,y,f.radius*cell*.45,0,Math.PI*2);ctx.fill();}
      }
      const core=fireX(f,s.tick);
      for(const x of [core-2*w.width,core,core+2*w.width]){
      if(x+f.radius<base || x-f.radius>base+w.width)continue;
      const xx=paneLeft+(x-base)*cell, r=f.radius*cell;
      const glow=ctx.createRadialGradient(xx,y,0,xx,y,r*1.8);glow.addColorStop(0,'#ffcb70');glow.addColorStop(.6,'#ea713344');glow.addColorStop(1,'#ea713300');ctx.fillStyle=glow;ctx.fillRect(xx-r*1.8,y-r*1.8,r*3.6,r*3.6);
      ctx.fillStyle=['#eb823c','#46bacb','#dc6caa'][f.color];ctx.beginPath();ctx.arc(xx,y,r,0,Math.PI*2);ctx.fill();
      ctx.strokeStyle='#ffe1a0';ctx.lineWidth=2;ctx.stroke();
      ctx.fillStyle='#ffdfa8';ctx.beginPath();ctx.moveTo(xx-r*.4,y+r*.3);ctx.quadraticCurveTo(xx-r*.7,y-r*.25,xx,y-r*.6);ctx.quadraticCurveTo(xx+r*.7,y+r*.4,xx-r*.4,y+r*.3);ctx.fill();
      const v=velocity(f,s.tick), dx=v*24;
      ctx.strokeStyle='#fff0cb';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(xx,y+2);ctx.lineTo(xx+dx,y+2);ctx.lineTo(xx+dx-Math.sign(dx)*7,y-4);ctx.moveTo(xx+dx,y+2);ctx.lineTo(xx+dx-Math.sign(dx)*7,y+8);ctx.stroke();
      const cruise=f.direction*f.speed*24;ctx.strokeStyle='#bde9ed';ctx.lineWidth=2;ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(xx,y+14);ctx.lineTo(xx+cruise,y+14);ctx.stroke();ctx.setLineDash([]);
      }
    }
    // Show the full next-pulse reach on the same folded ring as its physics.
    // A guide crossing an edge continues on the adjoining face.
    const origin=s.player[1]+.5, gutterY=floorY(s.player[0])-58;
    ctx.setLineDash([5,5]);ctx.strokeStyle='#70d9e47a';ctx.lineWidth=2;
    for(const lap of [-1,0,1]){
      const start=origin+lap*2*w.width, end=start+s.facing*w.pulse_reach;
      const low=Math.max(base,Math.min(start,end)), high=Math.min(base+w.width,Math.max(start,end));
      if(high>low){ctx.beginPath();ctx.moveTo(paneLeft+(low-base)*cell,gutterY);ctx.lineTo(paneLeft+(high-base)*cell,gutterY);ctx.stroke();}
    }
    ctx.setLineDash([]);
    if(s.pulse){const p=s.pulse, d=Math.min(w.pulse_reach,(s.tick-p.tick)*w.tick_ms/1000*w.pulse_speed), x=mod(p.x+p.direction*d,2*w.width);
      for(const px of [x-2*w.width,x,x+2*w.width])if(px+w.pulse_radius>=base&&px-w.pulse_radius<=base+w.width){ctx.fillStyle='#a9f6ff';ctx.beginPath();ctx.arc(paneLeft+(px-base)*cell,floorY(p.floor)-58,w.pulse_radius*cell,0,Math.PI*2);ctx.fill();}}
    ctx.restore();
    if(surveyed&&Math.floor(w.resident[1]/w.width)===face){const x=paneLeft+(w.resident[1]-base+.5)*cell,y=floorY(w.resident[0]);
      ctx.fillStyle='#77dbb5';ctx.fillRect(x-23,y-30,46,45);ctx.fillStyle='#163c38';ctx.beginPath();ctx.arc(x,y-15,7,0,Math.PI*2);ctx.fill();ctx.fillRect(x-6,y-6,12,17);label(ctx,'RESIDENT',x-31,y-37,'#a0f1cb','11px sans-serif');}
    if(Math.floor(s.player[1]/w.width)===face){const x=paneLeft+(s.player[1]-base+.5)*cell,y=floorY(s.player[0]);
      ctx.fillStyle='#97d3df';ctx.fillRect(x-22,y-22,44,44);ctx.fillStyle='#163b4c';ctx.fillRect(x-17,y-17,34,34);
      label(ctx,s.facing===1?'→':'←',x-16,y+11,'#f4e8cd','bold 35px sans-serif');
      ctx.strokeStyle='#86b8c3';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x,y-22);ctx.lineTo(x,y-58);ctx.stroke();ctx.fillStyle='#86b8c3';ctx.beginPath();ctx.arc(x,y-58,4,0,Math.PI*2);ctx.fill();
    }
  }
  function draw() {
    if (!model) return;
    const ctx = document.getElementById('fw2-canvas')?.getContext('2d'); if (!ctx) return;
    const s = model.sim, w = model.state.world;
    ctx.clearRect(0,0,W,H);
    const sky = ctx.createLinearGradient(0,0,0,H); sky.addColorStop(0,'#101b29'); sky.addColorStop(1,'#263132'); ctx.fillStyle=sky; ctx.fillRect(0,0,W,H);
    drawFace(ctx,0); drawFace(ctx,1);
    document.getElementById('fw2-face').textContent = s.view===0?'COPPER HIGHLIGHTED · BOTH FACES VISIBLE':'INDIGO HIGHLIGHTED · BOTH FACES VISIBLE';
    document.getElementById('fw2-eye').textContent = `◉ INSPECT ${s.view===0?'INDIGO':'COPPER'} PLAN`;
    document.getElementById('fw2-position').textContent = `${s.player[0]+1}F · ${Math.floor(s.player[1]/w.width)===0?'COPPER':'INDIGO'} ${s.player[1]%w.width+1}`;
    document.getElementById('fw2-stock').textContent = `${s.stock}`;
    document.getElementById('fw2-contained').textContent = `${s.cleared.length} / ${w.fires.length}`;
    document.querySelectorAll('[data-color-readout]').forEach(n=>{const c=Number(n.dataset.colorReadout);n.textContent=`${['AMBER','TEAL','ROSE'][c]} ${s.cartridges[c]}`;n.classList.toggle('selected',s.selected===c);});
    document.getElementById('fw2-start').disabled = s.started || model.terminal;
    const pulseNote = model.terminal
      ? (s.rescued ? 'RESCUE COMPLETE · ALL FRONTS CONTAINED' : 'ATTEMPT ENDED · ' + (s.failure || 'RESIDENT NOT REACHED'))
      : s.pulse ? 'WATER IN FLIGHT'
      : ['WATER IN FLIGHT', 'WAIT FOR THE PULSE'].includes(model.message) ? 'PULSE COMPLETE · CORE CONTAINED'
      : model.message || 'Inspect the concealed face plans with ◉. Fire gutters stay visible.';
    document.getElementById('fw2-note').textContent = pulseNote;
    if (!model.terminal) {
      const secondsLeft = Math.max(0, (w.max_ticks - s.tick) * w.tick_ms / 1000);
      document.querySelector('.fw2 .readout').textContent = s.started ? `RESCUE ACTIVE · ${secondsLeft.toFixed(1)} s LEFT · TRACK THE CORES` : `SCOUTING · ${secondsLeft.toFixed(0)} s AFTER START`;
    }
  }
  function animate(){draw();frame=requestAnimationFrame(animate);}
  async function render(state, helpers) {
    cancelAnimationFrame(frame);if(keyHandler)window.removeEventListener('keydown',keyHandler);
    const w=state.world;
    model={state, helpers, interaction:state.interaction, events:[], terminal:false,
      sim:{tick:0,started:false,player:[...w.start],facing:1,view:Math.floor(w.start[1]/w.width),surveyed_faces:[],stock:w.stock,cleared:[],pulse:null,last_move:-100,failure:null,rescued:false,selected:0,cartridges:[...w.cartridges]}};
    window.firewatchFoldV3Model=model;
    document.body.dataset.mechanic='firewatch-fold-v2';
    helpers.app.innerHTML=`<section class="fw2"><header><div><small>FOLDED CITY / RESCUE SERVICE</small><h1>Firewatch <i>Fold V3</i></h1></div><p>Intercept moving fire cores with finite water pulses.<br>Clear the floor to unlock its ladders. Reach the resident.</p></header>
      <main><article><div class="fw2-maphead"><b id="fw2-face"></b><span>EXTERIOR FIRE GUTTER · SHIELDED CATWALK</span></div><canvas id="fw2-canvas" width="1200" height="560"></canvas><div class="fw2-legend"><span>◯ bright core = water contact</span><span>colored trails + white arrows = current · dots = cruise</span><span>dashed line = pulse reach · outer edges connect</span></div></article>
      <aside><div class="fw2-stat"><small>YOUR POSITION</small><b id="fw2-position"></b></div><div class="fw2-cans"><div><small>CANISTERS</small><b id="fw2-stock"></b></div><div><small>CONTAINED</small><b id="fw2-contained"></b></div></div>
      <div class="fw2-cartridges">${w.cartridges.map((_,c)=>state.interaction==='full'?`<span data-color-readout="${c}"></span>`:`<button data-color="${c}" data-color-readout="${c}"></button>`).join('')}</div>
      <button id="fw2-eye">◉ INSPECT OTHER PLAN</button><button id="fw2-start">START RESCUE</button>
      ${state.interaction==='full'?'<div class="fw2-keyguide"><b>← ↑ ↓ → / WASD</b><span>Move one bay / climb a ladder</span><b>SHIFT</b><span>Water pulse in last horizontal direction</span></div>':'<div class="fw2-pad"><button data-dir="UP">↑</button><button data-dir="LEFT">←</button><button data-dir="DOWN">↓</button><button data-dir="RIGHT">→</button></div><button id="fw2-fire">WATER PULSE → / ←</button>'}
      <p class="fw2-risk">${state.interaction==='full'?'1 / 2 / 3 select AMBER / TEAL / ROSE. ':''}Match the first core hit. One canister per front. A miss or wrong color ends the attempt. Each deliberate action settles one fixed transition; waiting leaves the scene stable.</p></aside></main>
      <footer><div><b id="fw2-note"></b><div class="readout">SCOUTING</div></div><button id="fw2-certify">CERTIFY RESCUE</button></footer><div id="fw2-verdict"></div></section>`;
    document.getElementById('fw2-eye').onclick=()=>action('inspect',null,'button');
    document.getElementById('fw2-start').onclick=()=>action('start',null,'button');
    document.getElementById('fw2-certify').onclick=()=>finish(true);
    document.querySelectorAll('[data-dir]').forEach(b=>b.onclick=()=>action('move',b.dataset.dir,'proxy_button'));
    document.querySelectorAll('[data-color]').forEach(b=>b.onclick=()=>action('select',Number(b.dataset.color),'proxy_button'));
    const fire=document.getElementById('fw2-fire');if(fire)fire.onclick=()=>action('fire',null,'proxy_button');
    keyHandler=e=>{if(model.interaction!=='full'||e.repeat||model.terminal)return;
      const direction={ArrowLeft:'LEFT',ArrowRight:'RIGHT',ArrowUp:'UP',ArrowDown:'DOWN',a:'LEFT',d:'RIGHT',w:'UP',s:'DOWN'}[e.key];
      if(direction){e.preventDefault();action('move',direction,'keyboard');}else if(e.key==='Shift'){e.preventDefault();action('fire',null,'keyboard');}
      else if(['1','2','3'].includes(e.key)&&Number(e.key)<=w.color_count){e.preventDefault();action('select',Number(e.key)-1,'keyboard');}};
    window.addEventListener('keydown',keyHandler);draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.firewatch_fold_v3_nonrealtime={rootSelector:'.fw2',render};
})();
