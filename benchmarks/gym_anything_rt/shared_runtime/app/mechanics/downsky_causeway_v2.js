(() => {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function motion(seed, ms, span) {
    const u = Math.max(0, ms) / span, n = Math.floor(u), f = u - n;
    return noise(seed, n) + (noise(seed, n + 1) - noise(seed, n)) * f * f * (3 - 2 * f);
  }
  const deckY = (d, ms) => d.base_y + d.amplitude * motion(d.motion_seed, ms, d.span_ms);
  const deckVelocity = (d, ms) => (deckY(d, ms + 10) - deckY(d, Math.max(0, ms - 10))) / (ms >= 10 ? .02 : .01);
  class Simulation {
    constructor(world) {
      this.world = world; this.ms = 0; this.active = false; this.complete = false; this.failed = '';
      this.x = world.initial.x; this.y = world.initial.y; this.z = world.initial.z;
      this.vy = 0; this.vz = 0; this.u = 0; this.support = 0; this.landings = []; this.start_ms = null;
    }
    start() { if (this.active || this.complete || this.failed) return false; this.active = true; this.start_ms = this.ms; return true; }
    steer(u) { this.u = clamp(u, -1, 1); }
    contained(d, x, y, ms) {
      const r = this.world.radius;
      return d.x0 + r - 1e-9 <= x && x <= d.x1 - r + 1e-9 && Math.abs(y - deckY(d, ms)) + r <= d.half_width + 1e-9;
    }
    advance(end) {
      const w = this.world;
      while (this.ms + 10 <= end && !this.failed && !this.complete) {
        const before = this.ms; this.ms += 10;
        if (!this.active) continue;
        const ox = this.x, oy = this.y, oz = this.z, previous = this.support;
        const wind = w.wind * motion(w.wind_seed, this.ms, w.wind_span_ms);
        const acc = clamp(w.response * (this.u * w.max_lateral_speed - this.vy) + wind, -w.acceleration, w.acceleration);
        this.vy = clamp(this.vy + acc * .01, -w.max_lateral_speed, w.max_lateral_speed);
        this.x += w.forward_speed * .01; this.y += this.vy * .01;
        if (previous !== null) {
          const d = w.decks[previous], carry = deckY(d, this.ms) - deckY(d, before);
          this.y += carry;
          if (this.contained(d, this.x, this.y, this.ms)) { this.z = d.z; this.vz = 0; }
          else { this.support = null; this.vy += carry / .01; this.vz = 0; }
        }
        if (this.support === null) {
          this.vz -= w.gravity * .01; this.z += this.vz * .01;
          for (const d of w.decks) {
            if (oz > d.z + 1e-9 && this.z <= d.z) {
              const f = (oz - d.z) / (oz - this.z), ix = ox + (this.x - ox) * f, iy = oy + (this.y - oy) * f;
              if (this.contained(d, ix, iy, before + 10 * f)) {
                this.support = d.id; this.z = d.z; this.vz = 0; this.vy -= deckVelocity(d, this.ms);
                this.landings.push({deck: d.id, ms: this.ms, x: ix, y: iy}); break;
              }
            }
          }
        }
        if (this.z < -2.4) this.failed = 'The walker fell below the causeway.';
        else if (this.ms - this.start_ms >= w.crossing_limit_ms) this.failed = 'The crossing ended without an arrival.';
        else if (this.support === 6 && this.x >= w.finish_x &&
                 Math.abs(this.y - deckY(w.decks[6], this.ms)) + w.radius <= w.finish_half_width) this.complete = true;
      }
    }
    snapshot() {
      const state=Object.fromEntries(['ms', 'active', 'complete', 'failed', 'x', 'y', 'z', 'vy', 'vz', 'u', 'support', 'landings', 'start_ms'].map(k => [k, this[k]]));
      state.landings=this.landings.map(item=>({...item}));return state;
    }
  }
  window.DownskyCausewayV2Physics = {Simulation, noise, motion, deckY, deckVelocity};
  let model = null, raf = 0;
  const project = (x, y, z) => [65 + x * 18 + y * 13, 330 - x * 1.2 + y * 34 - z * 12];
  const record = (kind, details = {}) => model.events.push({sequence: model.events.length + 1, t_ms: model.sim.ms, kind, ...details});
  function sync() { model.sim.advance(Math.max(0, performance.now() - model.epoch)); }
  function point(event) {
    const r = document.querySelector('.dc-canvas').getBoundingClientRect();
    return [(event.clientX-r.left)/r.width*1100, (event.clientY-r.top)/r.height*610];
  }
  function polygon(ctx, points, fill, stroke) {
    ctx.beginPath(); points.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.stroke(); }
  }
  function corners(d, ms, height = d.z) {
    const y = deckY(d, ms), b = d.half_width;
    return [[d.x0,y-b],[d.x1,y-b],[d.x1,y+b],[d.x0,y+b]].map(([x,y]) => project(x,y,height));
  }
  function draw() {
    const canvas = document.querySelector('.dc-canvas'), ctx = canvas.getContext('2d'), s = model.sim, w = s.world;
    ctx.clearRect(0, 0, 1100, 610);
    const sky = ctx.createLinearGradient(0,0,0,610); sky.addColorStop(0,'#10283c'); sky.addColorStop(.75,'#396978'); sky.addColorStop(1,'#122b3d');
    ctx.fillStyle = sky; ctx.fillRect(0,0,1100,610);
    ctx.fillStyle = '#b0d2cc20';
    for (let i=0; i<9; i++) { ctx.beginPath(); ctx.ellipse(90+i*131, 380+(i%3)*28, 118, 19, -.1, 0, Math.PI*2); ctx.fill(); }
    ctx.fillStyle = '#c7e9e7'; ctx.font='13px monospace'; ctx.fillText('ONE WAY DOWN / NO JUMP / STEER THE GOLD TILLER', 34, 37);
    ctx.fillStyle = '#86b4c3'; ctx.fillText('Dashed blue outlines: deck position 0.9 seconds ahead. White streaks: recent drift.',34,59);
    for (const d of w.decks) {
      const top=corners(d,s.ms), bottom=corners(d,s.ms,d.z-.48);
      polygon(ctx,[top[2],top[3],bottom[3],bottom[2]],'#1a343a','#65919b');
      polygon(ctx,[top[1],top[2],bottom[2],bottom[1]],'#193039','#65919b');
      polygon(ctx,top,s.support===d.id?'#63847d':'#4a6568','#8eb8b6');
      ctx.lineWidth=2;
      const r=w.radius, cy=deckY(d,s.ms);
      const safe=[[d.x0+r,cy-d.half_width+r],[d.x1-r,cy-d.half_width+r],[d.x1-r,cy+d.half_width-r],[d.x0+r,cy+d.half_width-r]].map(([x,y])=>project(x,y,d.z));
      ctx.setLineDash([5,4]); polygon(ctx,safe,null,'#c8d8b076'); ctx.setLineDash([]);
      const center=project((d.x0+d.x1)/2,cy,d.z), previous=project((d.x0+d.x1)/2,deckY(d,Math.max(0,s.ms-800)),d.z);
      ctx.strokeStyle='#e4ece7'; ctx.lineWidth=3; ctx.beginPath(); ctx.moveTo(...previous); ctx.lineTo(...center); ctx.stroke();
      ctx.fillStyle='#e2e9d8'; ctx.font='bold 15px monospace'; ctx.fillText(String(d.id+1),center[0]-5,center[1]-8);
      ctx.font='11px monospace'; ctx.fillStyle='#a3c8cb'; ctx.fillText(`↓ ${d.z.toFixed(1)}`,top[3][0]+5,top[3][1]+19);
      if (d.id>0 && (s.support===null || d.id===s.support+1 || !s.active)) {
        ctx.setLineDash([4,6]); ctx.lineWidth=1.5; polygon(ctx,corners(d,s.ms+900),null,'#66daf4'); ctx.setLineDash([]);
      }
    }
    const last=w.decks[6], fy=deckY(last,s.ms), fx=w.finish_x;
    const goal=[[fx,fy-w.finish_half_width],[last.x1,fy-w.finish_half_width],[last.x1,fy+w.finish_half_width],[fx,fy+w.finish_half_width]].map(([x,y])=>project(x,y,last.z));
    polygon(ctx,goal,'#f0c75d99','#ffe6a2');
    const light=project(fx+.25,fy,0); ctx.fillStyle='#ffe6a2'; ctx.fillRect(light[0]-3,light[1]-33,6,27); ctx.beginPath();ctx.arc(light[0],light[1]-36,8,0,Math.PI*2);ctx.fill();
    const foot=project(s.x,s.y,s.z);
    ctx.save();ctx.translate(...foot);ctx.transform(18, -1.2, 13, 34, 0, 0);
    ctx.beginPath();ctx.arc(0,0,w.radius,0,Math.PI*2);ctx.fillStyle='#ffdb6d';ctx.fill();ctx.lineWidth=.04;ctx.strokeStyle='#372e1d';ctx.stroke();ctx.restore();
    ctx.strokeStyle='#e2bf60';ctx.lineWidth=4;ctx.beginPath();ctx.moveTo(...foot);ctx.lineTo(foot[0],foot[1]-22);ctx.stroke();
    ctx.fillStyle='#f9da78';ctx.beginPath();ctx.arc(foot[0],foot[1]-26,7,0,Math.PI*2);ctx.fill();
    const v=project(s.x+.4,s.y+s.vy*.4,s.z);
    ctx.strokeStyle='#ffecbb';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(...foot);ctx.lineTo(...v);ctx.stroke();
    // The side section shows the same x/z geometry and footprint, not a
    // separate collision surface. It makes the height loss and fall legible.
    ctx.fillStyle='#0a223a99';ctx.fillRect(26,430,1048,67);
    ctx.fillStyle='#a0c6cd';ctx.font='11px monospace';ctx.fillText('SIDE SECTION · gravity carries you to the next lower terrace',40,445);
    for (const d of w.decks) { ctx.strokeStyle='#80a6a1';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(60+d.x0*18,490-d.z*3);ctx.lineTo(60+d.x1*18,490-d.z*3);ctx.stroke(); }
    ctx.fillStyle='#ffe596';ctx.beginPath();ctx.arc(60+s.x*18,490-s.z*3,4,0,Math.PI*2);ctx.fill();
    const wind=w.wind*motion(w.wind_seed,s.ms,w.wind_span_ms);
    ctx.fillStyle='#aacbd0';ctx.font='12px monospace';ctx.fillText('WIND',864,99);ctx.strokeStyle='#c7ebeb';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(927,95);ctx.lineTo(927+wind*37,95+wind*8);ctx.stroke();
    ctx.fillText(`${Math.round(s.u*100)}% STEER · ${s.vy.toFixed(1)} lateral speed`,35,523);
    ctx.fillText(model.interaction==='full'?'DRAG THE GOLD HANDLE · RELEASE KEEPS ITS SETTING':'CLICK THE TILLER RAIL · SETTING STAYS UNTIL CHANGED',35,594);
    ctx.strokeStyle='#a3c2c6';ctx.lineWidth=8;ctx.beginPath();ctx.moveTo(160,565);ctx.lineTo(940,565);ctx.stroke();
    ctx.strokeStyle='#f0c866';ctx.lineWidth=9;ctx.beginPath();ctx.moveTo(550,565);ctx.lineTo(550+s.u*390,565);ctx.stroke();
    ctx.fillStyle='#dce8e1';ctx.font='12px monospace';ctx.fillText('← LEFT',96,570);ctx.fillText('RIGHT →',951,570);ctx.fillText('0',546,551);
    ctx.beginPath();ctx.arc(550+s.u*390,565,20,0,Math.PI*2);ctx.fillStyle='#ffe29a';ctx.fill();ctx.lineWidth=2;ctx.strokeStyle='#72572a';ctx.stroke();
  }
  function payload() {
    return {mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
            interaction_mode:model.interaction,events:model.events,completed:model.sim.complete,final:model.sim.snapshot()};
  }
  async function submit() {
    if (!model || model.submitting || model.terminal) return;
    sync();record('seal',{input_source:'submit_button'});model.submitting=true;
    const current=model;current.helpers.setReadout('VERIFYING THE PHYSICAL DESCENT…','pending');
    try {
      const r=await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
      const verdict=await r.json();current.terminal=true;current.passed=verdict.passed===true;
      current.helpers.setReadout(current.passed?'PASS':'FAIL · CROSSING ENDED',current.passed?'passed':'error');
      document.querySelector('.dc-verdict').textContent=current.passed?'PASS · PAVILION REACHED':'FAIL · CROSSING ENDED';
      document.querySelector('.downsky-causeway-v2').dataset.verdict=current.passed?'pass':'fail';
    } catch (e) { current.submitting=false;current.helpers.setReadout('VERIFIER UNAVAILABLE','error'); }
    update();
  }
  function update() {
    draw();
    const s=model.sim;
    document.querySelector('.dc-status').textContent=model.terminal?(model.passed?'ARRIVAL VERIFIED':'ATTEMPT ENDED'):s.failed?s.failed:s.complete?'PAVILION REACHED · CERTIFY ARRIVAL':!s.active?'INSPECT THE DRIFT · START WHEN READY':s.support===null?'IN FREE FALL · STEER FOR THE LOWER DECK':`TERRACE ${s.support+1} / 7 · THE NEXT LANDING KEEPS MOVING`;
    document.querySelector('.dc-start').disabled=s.active||model.terminal||model.submitting;
    document.querySelector('.dc-submit').disabled=model.terminal||model.submitting;
  }
  function animate() {
    if (model && !model.terminal && !model.submitting) {
      sync();update();if (model.sim.failed) submit();
    }
    raf=requestAnimationFrame(animate);
  }
  function steer(p) {
    const u=clamp((p[0]-550)/390,-1,1);model.sim.steer(u);
    record('steer',{u,point:p,input_source:model.interaction==='full'?'tiller_drag':'tiller_click'});
  }
  function down(event) {
    if (model.terminal||model.submitting||model.sim.complete||model.sim.failed||model.hold) return;
    sync();
    if (model.sim.complete||model.sim.failed) { event.preventDefault();update();return; }
    const p=point(event);
    if (model.interaction==='simplified' && p[1]>=540 && p[1]<=590 && p[0]>=140 && p[0]<=960) steer(p);
    if (model.interaction==='full' && Math.hypot(p[0]-(550+model.sim.u*390),p[1]-565)<=25) {
      model.hold=event.pointerId;record('steer_start',{point:p,input_source:'tiller_drag'});event.currentTarget.setPointerCapture(event.pointerId);
    }
    event.preventDefault();update();
  }
  function move(event) {
    if (model.hold!==event.pointerId||model.terminal||model.submitting||model.sim.complete||model.sim.failed) return;
    sync();if (!model.sim.complete&&!model.sim.failed) steer(point(event));update();event.preventDefault();
  }
  function up(event) {
    if (model.hold!==event.pointerId) return;
    sync();record('steer_end',{input_source:'tiller_drag'});model.hold=null;event.currentTarget.releasePointerCapture?.(event.pointerId);update();
  }
  function render(state, helpers, options={}) {
    cancelAnimationFrame(raf);
    model={state,helpers,interaction:state.control_condition?.interaction||'full',sim:new Simulation(state.world),epoch:performance.now(),events:[],hold:null,terminal:Boolean(state.episode_failed||options.freshFailure),submitting:false,passed:false};
    window.downskyCausewayV2Model=model;
    document.body.dataset.mechanic='downsky-causeway-v2';
    helpers.app.innerHTML=`<section class="downsky-causeway-v2" data-interaction="${model.interaction}"><header class="dc-head"><div><span>SKYMAZE / IRREVERSIBLE DESCENT</span><h1>Downsky Causeway V2</h1></div><div class="dc-verdict">${model.terminal?'FAIL · EPISODE ENDED':'SEVEN DRIFTING TERRACES'}</div></header><main class="dc-main"><canvas class="dc-canvas" width="1100" height="610"></canvas><aside><span>THE WALKER</span><h2>No jump.<br>No way back.</h2><p>START sends the walker forward. The tiller sets lateral speed. Momentum takes time to reverse.</p><p>Fit the whole gold footprint on each deck. At an edge, gravity takes over. Lower decks keep drifting during the fall.</p><p>Blue outlines show positions 0.9 seconds ahead; white streaks show recent drift.</p><p>Reach the light on terrace 7, then certify. Falling below the causeway or certifying early ends the episode.</p><p>${model.interaction==='full'?'Grab and drag the gold handle.':'Click the rail to set the gold handle.'} Releasing keeps its setting. The world keeps moving.</p><button class="dc-start">START CROSSING</button></aside></main><footer><div><b class="dc-status"></b><div class="readout" data-status="idle">INSPECT THE LANDINGS</div></div><button class="dc-submit">CERTIFY ARRIVAL</button></footer></section>`;
    const canvas=document.querySelector('.dc-canvas');canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',up);
    document.querySelector('.dc-start').addEventListener('click',()=>{if(model.terminal||model.submitting)return;sync();if(model.sim.start())record('start',{input_source:'start_button'});update();});
    document.querySelector('.dc-submit').addEventListener('click',submit);update();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.downsky_causeway_v2={rootSelector:'.downsky-causeway-v2',render};
})();
