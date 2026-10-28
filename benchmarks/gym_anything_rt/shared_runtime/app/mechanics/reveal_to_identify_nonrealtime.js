(() => {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const clean = x => String(x).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  const quantize=(value,precision=1000)=>Math.floor(value*precision+.5)/precision;
  class Simulation {
    constructor(state) {
      this.world = state.world; this.items = structuredClone(state.carriers); this.wanted = state.wanted;
      this.tick = 0; this.aim = [450,250]; this.velocity = [0,0]; this.target = [...this.aim];
      this.tagged = new Set(); this.pulses = []; this.hits = []; this.last_fire = -1000;
      this.failed = ''; this.drag = false; this.history = [];
      this.flow_state=[...this.world.flow_initial];this.scanned=new Set();this.valve_history=[];this.certifyExposure();
    }
    certifyExposure() {
      for(const item of this.items) if(Math.hypot(item.x-this.aim[0],item.y-this.aim[1])+this.world.carrier_radius<=this.world.lens_radius) this.scanned.add(item.id);
    }
    get armed(){return this.scanned.size===this.items.length;}
    desiredCurrent(item,axis) {
      const w=this.world,direction=item.plate%(axis===0?2:3)?1:-1,limit=w.speed*w.current_limit_multiplier;
      return clamp(w.speed*direction*(this.flow_state[axis]/(axis===0?18:24)+(axis===0?(item.y-250)/500:-(item.x-450)/900)*.4),-limit,limit);
    }
    advance(end) {
      const w = this.world;
      end = Math.min(end, w.duration_ms/10);
      while (this.tick < end && !this.failed) {
        this.tick++; const ms = this.tick*10;
        const [x,y,z]=this.flow_state,h=w.flow_dt;
        this.flow_state=[quantize(x+h*w.flow_sigma*(y-x),w.flow_precision),
          quantize(y+h*(x*(w.flow_rho-z)-y),w.flow_precision),quantize(z+h*(x*y-w.flow_beta*z),w.flow_precision)];
        for (let axis=0; axis<2; axis++) {
          const acc = clamp((this.target[axis]-this.aim[axis])*w.scanner_spring-this.velocity[axis]*w.scanner_damping,
            -w.scanner_acceleration, w.scanner_acceleration);
          this.velocity[axis] = quantize(clamp(this.velocity[axis]+acc*.01, -w.scanner_speed, w.scanner_speed));
          this.aim[axis] = quantize(clamp(this.aim[axis]+this.velocity[axis]*.01,24,(axis===0?w.width:w.height)-24));
        }
        const active = this.items.filter(item => !this.tagged.has(item.id));
        for (const item of active) {
          for (const [axis,pos,vel] of [[0,'x','vx'],[1,'y','vy']]) {
            const current=axis===0?'cx':'cy',memory=w.current_memory_ms/1000;
            const limit=w.speed*w.current_limit_multiplier;
            item[current]=clamp(item[current]+(this.desiredCurrent(item,axis)-item[current])*.01/memory,-limit,limit);
            item[vel] += (item[current]-item[vel])*.01*w.current_response; item[pos] += item[vel]*.01;
            const low=w.carrier_radius+8, high=(axis===0?w.width:w.height)-low;
            if (item[pos]<low || item[pos]>high) { item[pos]=clamp(item[pos],low,high); item[vel]*=-.9; }
          }
        }
        for (let pass=0;pass<8;pass++) {
          let changed=false;
          for (let i=0;i<active.length;i++) for (const b of active.slice(i+1)) {
            const a=active[i], dx=b.x-a.x, dy=b.y-a.y, d=Math.hypot(dx,dy), diameter=2*w.carrier_radius;
            if (d>0 && d<diameter-1e-8) {
              changed=true;
              const nx=dx/d, ny=dy/d, shift=(diameter-d)/2;
              a.x-=nx*shift; a.y-=ny*shift; b.x+=nx*shift; b.y+=ny*shift;
              const relative=(b.vx-a.vx)*nx+(b.vy-a.vy)*ny;
              if (relative<0) { const impulse=-.9*relative; a.vx-=impulse*nx; a.vy-=impulse*ny; b.vx+=impulse*nx; b.vy+=impulse*ny; }
            }
          }
          for (const item of active) for (const [pos,vel,extent] of [['x','vx',w.width],['y','vy',w.height]]) {
            const low=w.carrier_radius+8,high=extent-low;
            if (item[pos]<low || item[pos]>high) {
              changed=true;
              if ((item[pos]<low && item[vel]<0) || (item[pos]>high && item[vel]>0)) item[vel]*=-.9;
              item[pos]=clamp(item[pos],low,high);
            }
          }
          if (!changed) break;
        }
        for(const item of active) for(const key of ['x','y','vx','vy','cx','cy']) item[key]=quantize(item[key]);
        this.certifyExposure();
        for (const pulse of [...this.pulses]) if (ms>=pulse.due_ms) {
          this.pulses.splice(this.pulses.indexOf(pulse),1);
          const candidates=active.filter(item=>!this.tagged.has(item.id)).map(item=>[Math.hypot(item.x-pulse.point[0],item.y-pulse.point[1]),item]);
          candidates.sort((a,b)=>a[0]-b[0] || a[1].id.localeCompare(b[1].id));
          const hit=candidates.length && candidates[0][0]<=w.carrier_radius+w.pulse_radius ? candidates[0][1] : null;
          this.hits.push({tick:this.tick,point:[...pulse.point],carrier_id:hit?.id || null});
          if (!hit) this.failed='PULSE MISSED';
          else if (!this.wanted.some(g=>JSON.stringify(g)===JSON.stringify(hit.glyph))) this.failed='PROTECTED SPECIMEN TAGGED';
          else {
            this.tagged.add(hit.id);
            if(this.tagged.size<w.targets) {
              const code=w.valve_program[this.tagged.size-1];
              this.flow_state=[...w.valve_presets[code]];this.valve_history.push({tick:this.tick,code});
              for(const body of active) if(!this.tagged.has(body.id)) {
                body.cx=quantize(this.desiredCurrent(body,0));body.cy=quantize(this.desiredCurrent(body,1));
              }
            }
          }
          if (this.failed) break;
        }
        if (ms>=w.duration_ms && this.tagged.size<w.targets) this.failed='TANK CLOSED';
        if (this.tick%5===0) this.history.push({tick:this.tick,items:active.map(a=>({id:a.id,x:a.x,y:a.y}))});
        while (this.history.length && this.history[0].tick<this.tick-80) this.history.shift();
      }
    }
    fire() {
      const ms=this.tick*10;
      if (!this.armed || this.failed || ms-this.last_fire<this.world.pulse_cooldown_ms) return false;
      this.last_fire=ms; this.pulses.push({point:[...this.aim],due_ms:ms+this.world.pulse_lag_ms}); return true;
    }
  }
  window.RevealScannerPhysics={Simulation,quantize};
  let model, keyHandler;
  const record=(kind,source,extra={})=>model.events.push({sequence:model.events.length+1,kind,tick:model.sim.tick,input_source:source,...extra});
  function glyph(ctx,g,x,y,size,color='#fae9bc') {
    ctx.save(); ctx.translate(x,y); ctx.scale(size/30,size/30);
    ctx.strokeStyle=color; ctx.fillStyle=color; ctx.lineWidth=3; ctx.lineCap='round'; ctx.lineJoin='round';
    ctx.beginPath();
    if (g.family===0) { // winged seed
      ctx.moveTo(-23,4); ctx.quadraticCurveTo(-28,-22,0,-7); ctx.quadraticCurveTo(28,-22,23,4);
      ctx.lineTo(0,16); ctx.closePath();
    } else if (g.family===1) { // little vessel
      ctx.ellipse(-3,4,15,14,0,0,Math.PI*2); ctx.moveTo(10,0); ctx.lineTo(25,-8); ctx.lineTo(13,9);
      ctx.moveTo(-15,-1); ctx.bezierCurveTo(-30,-20,-31,18,-15,14);
    } else if (g.family===2) { // four vanes
      for (let i=0;i<4;i++) { const a=i*Math.PI/2; ctx.moveTo(Math.cos(a)*5,Math.sin(a)*5);
        ctx.lineTo(Math.cos(a+.25)*25,Math.sin(a+.25)*25); ctx.lineTo(Math.cos(a+.6)*18,Math.sin(a+.6)*18); ctx.closePath(); }
    } else if (g.family===3) { // parasol
      ctx.arc(0,0,23,Math.PI,Math.PI*2); ctx.lineTo(-23,0); ctx.moveTo(0,-20); ctx.lineTo(0,18); ctx.quadraticCurveTo(0,28,12,18);
    } else if (g.family===4) { // binocular body
      ctx.ellipse(-13,4,9,16,.15,0,Math.PI*2); ctx.moveTo(22,4); ctx.ellipse(13,4,9,16,-.15,0,Math.PI*2);
      ctx.moveTo(-6,-3);ctx.lineTo(6,-3);
    } else { // lamp
      ctx.rect(-13,-10,26,31); ctx.moveTo(-19,-10);ctx.lineTo(19,-10); ctx.moveTo(-9,-11);ctx.arc(0,-11,9,Math.PI,0);
      ctx.moveTo(-18,22);ctx.lineTo(18,22);
    }
    ctx.stroke();
    // Diagnostic differences are large physical pieces of the silhouette, not text.
    ctx.beginPath(); ctx.moveTo(-9,-28);ctx.lineTo(-9,-20);ctx.moveTo(9,-28);ctx.lineTo(9,-20);
    if (g.crown===1) { ctx.moveTo(-9,-28);ctx.lineTo(0,-33);ctx.lineTo(9,-28); } else { ctx.moveTo(-9,-28);ctx.lineTo(9,-28); }
    ctx.stroke(); ctx.beginPath();
    if (g.eye===0) ctx.arc(0,5,4,0,Math.PI*2);
    else {ctx.moveTo(-5,5);ctx.lineTo(0,0);ctx.lineTo(5,5);ctx.lineTo(0,10);ctx.closePath();}
    ctx.fill(); ctx.restore();
  }
  function sync() {
    if (!model?.active || model.terminal) return;
    if (model.sim.failed) void finish(model.sim.failed);
    else if (model.sim.tagged.size===model.state.world.targets && !model.sim.pulses.length) void finish('');
  }
  function advanceAction() {
    model.sim.advance(model.sim.tick+model.state.world.action_step_ticks);
    sync();
  }
  function settlePulse() {
    model.sim.advance(model.sim.tick+model.state.world.pulse_settle_ticks);
    sync();
  }
  async function finish(reason) {
    if (model.terminal) return;
    model.terminal=true; model.active=false;
    record('certify','certify_button');
    const completed=!reason && model.sim.tagged.size===model.state.world.targets;
    const payload={mechanic_id:model.state.mechanic_id,revision:model.state.revision,task_id:model.state.task_id,
      challenge_id:model.state.challenge_id,interaction_mode:model.mode,events:model.events,
      final_tick:model.sim.tick,tagged_ids:[...model.sim.tagged].sort(),completed};
    model.payload=payload;
    document.querySelector('.rti2-verdict').textContent=reason?`FAIL · ${reason}`:'VERIFYING…';
    document.querySelector('.rti2-verdict').hidden=false;
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const result=await response.json(); model.result=result;
      document.querySelector('.rti2-verdict').textContent=result.passed?'PASS · SPECIMENS TAGGED':`FAIL · ${reason || 'INCOMPLETE SURVEY'}`;
      document.querySelector('.rti2').dataset.verdict=result.passed?'pass':'fail';
      model.helpers.setReadout(result.passed?'PASS':'FAIL',result.passed?'passed':'error');
    } catch (error) {
      document.querySelector('.rti2-verdict').textContent='VERIFIER CONNECTION ERROR';
      model.helpers.setReadout('VERIFIER ERROR','error');
    }
    draw();
  }
  function draw() {
    if (!model) return;
    const canvas=document.getElementById('rti2-tank'),ctx=canvas.getContext('2d'),s=model.sim,w=s.world;
    ctx.fillStyle='#101e2a';ctx.fillRect(0,0,900,500);
    ctx.strokeStyle='#203545';ctx.lineWidth=1;
    for(let x=50;x<900;x+=50){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,500);ctx.stroke();}
    for(let y=50;y<500;y+=50){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(900,y);ctx.stroke();}
    ctx.strokeStyle='#56757e';ctx.lineWidth=4;ctx.strokeRect(8,8,884,484);
    // Recent traces remain visible outside the lens. They expose motion, not identity.
    for(const item of s.items) if(!s.tagged.has(item.id)) {
      const trail=s.history.map(h=>h.items.find(a=>a.id===item.id)).filter(Boolean);
      ctx.beginPath(); trail.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));
      ctx.strokeStyle='#79a5b4';ctx.lineWidth=2;ctx.stroke();
      ctx.fillStyle='#273b4a';ctx.strokeStyle='#b4c9c8';ctx.lineWidth=2;
      ctx.beginPath();ctx.arc(item.x,item.y,w.carrier_radius,0,Math.PI*2);ctx.fill();ctx.stroke();
      ctx.fillStyle='#e5ede1';ctx.font='bold 12px monospace';ctx.textAlign='center';
      const labelY=item.y+w.carrier_radius+17<w.height-6?item.y+w.carrier_radius+17:item.y-w.carrier_radius-10;
      ctx.fillText(String(item.plate).padStart(2,'0'),item.x,labelY);
      ctx.strokeStyle='#e5ede1';ctx.beginPath();ctx.moveTo(item.x,item.y);
      ctx.lineTo(item.x+item.vx*.45,item.y+item.vy*.45);ctx.stroke();
      ctx.strokeStyle='#57d3dd';ctx.beginPath();ctx.moveTo(item.x,item.y);
      ctx.lineTo(item.x+item.cx*.25,item.y+item.cy*.25);ctx.stroke();
    }
    ctx.save();ctx.beginPath();ctx.arc(...s.aim,w.lens_radius,0,Math.PI*2);ctx.clip();
    ctx.fillStyle='rgba(151,217,200,.10)';ctx.fillRect(0,0,900,500);
    for(const item of s.items) if(!s.tagged.has(item.id)) {
      ctx.fillStyle='#182c36';ctx.beginPath();ctx.arc(item.x,item.y,w.carrier_radius-1,0,Math.PI*2);ctx.fill();
      glyph(ctx,item.glyph,item.x,item.y,w.carrier_radius*.72);
    }
    ctx.restore();
    // A physical contact sheet accumulates only pixels exposed by the lens.
    // Its numbered plates keep every old identity observation in the current UI.
    for(const item of s.items) {
      const photo=document.getElementById(`rti2-photo-${item.plate}`),pctx=photo.getContext('2d');
      if(!s.tagged.has(item.id)) {
        const magnification=22/(w.carrier_radius*.72);
        pctx.save();pctx.beginPath();
        pctx.arc(48+(s.aim[0]-item.x)*magnification,40+(s.aim[1]-item.y)*magnification,w.lens_radius*magnification,0,Math.PI*2);
        pctx.clip();glyph(pctx,item.glyph,48,40,22,'#31484b');pctx.restore();
        if(s.scanned.has(item.id)) glyph(pctx,item.glyph,48,40,22,'#31484b');
      }
      photo.parentElement.dataset.tagged=s.tagged.has(item.id)?'true':'false';
      photo.parentElement.dataset.scanned=s.scanned.has(item.id)?'true':'false';
      const initial=model.state.carriers.find(a=>a.id===item.id);
      document.getElementById(`rti2-motion-${item.plate}`).innerHTML=`<span data-field="P">${item.x.toFixed(3)},${item.y.toFixed(3)}</span><span data-field="V">${item.vx.toFixed(3)},${item.vy.toFixed(3)}</span><span data-field="C">${item.cx.toFixed(3)},${item.cy.toFixed(3)}</span><span data-field="I" class="rti2-calibration">${initial.x.toFixed(3)},${initial.y.toFixed(3)}</span><span data-field="V₀" class="rti2-calibration">${initial.vx.toFixed(3)},${initial.vy.toFixed(3)}</span>`;
    }
    // Optical masking never hides the motion instruments.
    for(const item of s.items) if(!s.tagged.has(item.id)) {
      ctx.strokeStyle='#e5ede1';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(item.x,item.y);
      ctx.lineTo(item.x+item.vx*.45,item.y+item.vy*.45);ctx.stroke();
      ctx.strokeStyle='#57d3dd';ctx.beginPath();ctx.moveTo(item.x,item.y);
      ctx.lineTo(item.x+item.cx*.25,item.y+item.cy*.25);ctx.stroke();
    }
    ctx.strokeStyle='#dcebad';ctx.lineWidth=2;ctx.beginPath();ctx.arc(...s.aim,w.lens_radius,0,Math.PI*2);ctx.stroke();
    ctx.fillStyle='rgba(220,235,173,.18)';ctx.strokeStyle='#eef0c8';ctx.beginPath();ctx.arc(...s.aim,24,0,Math.PI*2);ctx.fill();ctx.stroke();
    ctx.beginPath();ctx.moveTo(s.aim[0]-15,s.aim[1]);ctx.lineTo(s.aim[0]+15,s.aim[1]);
    ctx.moveTo(s.aim[0],s.aim[1]-15);ctx.lineTo(s.aim[0],s.aim[1]+15);ctx.stroke();
    ctx.strokeStyle='#e5ede1';ctx.beginPath();ctx.moveTo(...s.aim);
    ctx.lineTo(s.aim[0]+s.velocity[0]*.18,s.aim[1]+s.velocity[1]*.18);ctx.stroke();
    ctx.strokeStyle='#e8ba6b';ctx.setLineDash([5,5]);ctx.beginPath();ctx.arc(...s.target,9,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);
    for(const pulse of s.pulses) {
      const remaining=Math.max(0,(pulse.due_ms-s.tick*10)/w.pulse_lag_ms);
      ctx.strokeStyle='#ffd178';ctx.lineWidth=3;ctx.beginPath();ctx.arc(...pulse.point,w.pulse_radius+remaining*24,0,Math.PI*2);ctx.stroke();
      ctx.fillStyle='#ffd178';ctx.beginPath();ctx.arc(...pulse.point,w.pulse_radius,0,Math.PI*2);ctx.fill();
    }
    for(const hit of s.hits) if(s.tick-hit.tick<110) {
      ctx.strokeStyle=s.failed?'#f58e91':'#a9e8bf';ctx.lineWidth=4;ctx.beginPath();ctx.arc(...hit.point,35,0,Math.PI*2);ctx.stroke();
    }
    document.getElementById('rti2-count').textContent=`${s.tagged.size} / ${w.targets}`;
    document.getElementById('rti2-time').textContent=`${Math.max(0,150-s.tick/100).toFixed(1)}s`;
    document.getElementById('rti2-scanner-velocity').textContent=`${s.velocity[0].toFixed(3)},${s.velocity[1].toFixed(3)}`;
    document.getElementById('rti2-scanner-position').textContent=`${s.aim[0].toFixed(3)},${s.aim[1].toFixed(3)}`;
    document.getElementById('rti2-scanner-target').textContent=`${s.target[0].toFixed(2)},${s.target[1].toFixed(2)}`;
    document.getElementById('rti2-flow').textContent=s.flow_state.map((x,i)=>`${'XYZ'[i]} ${x.toFixed(6)}`).join(' · ');
    document.getElementById('rti2-tick').textContent=`${s.tick*10} ms`;
    document.getElementById('rti2-valves').textContent=s.valve_history.length?s.valve_history.map(v=>`${'ABCD'[v.code]} @ ${v.tick*10}`).join(' · '):'NONE';
    document.getElementById('rti2-inspected').textContent=`${s.scanned.size}/${s.items.length} · ${s.armed?'ARMED':'SCAN ALL'}`;
    document.getElementById('rti2-flight').textContent=s.pulses.length?`${s.pulses[0].point.map(x=>x.toFixed(3)).join(',')} · ${s.pulses[0].due_ms-s.tick*10} ms`:'—';
    const recharge=Math.max(0,w.pulse_cooldown_ms-(s.tick*10-s.last_fire));
    document.getElementById('rti2-charge').textContent=recharge?`${recharge} ms`:'READY';
    document.getElementById('rti2-pulse').disabled=!model.active || model.terminal || !s.armed || s.tick*10-s.last_fire<w.pulse_cooldown_ms;
    const cards=document.querySelectorAll('.rti2-card');
    cards.forEach((card,i)=>card.dataset.tagged=s.items.some(a=>s.tagged.has(a.id)&&JSON.stringify(a.glyph)===JSON.stringify(model.state.wanted[i]))?'true':'false');
  }
  function point(event) {
    const rect=document.getElementById('rti2-tank').getBoundingClientRect();
    return [Math.round(clamp((event.clientX-rect.left)/rect.width*900,0,900)*100)/100,
      Math.round(clamp((event.clientY-rect.top)/rect.height*500,0,500)*100)/100];
  }
  function fire() {
    sync();if(!model.active || model.terminal)return;
    if(model.sim.fire()) {
      record('fire',model.mode==='full'?'pulse_key':'pulse_button');
      settlePulse();
    }
    draw();
  }
  async function render(state,helpers) {
    if(keyHandler)window.removeEventListener('keydown',keyHandler);
    model={state,helpers,mode:state.control_condition.interaction,sim:new Simulation(state),events:[],active:false,terminal:false,pointer:null};
    model.scanned=model.sim.scanned;
    window.revealScannerModel=model; document.body.dataset.mechanic='reveal-to-identify-v2';
    helpers.app.innerHTML=`<section class="rti2" data-interaction="${model.mode}" data-verdict="">
      <header><div><span>DARKROOM / MOVING SPECIMENS</span><h1>Reveal to Identify V2</h1></div><button id="rti2-guide-button">FLOW GUIDE</button><div class="rti2-badge">SURVEY 02<br><b>ONE ATTEMPT</b></div></header>
      <div id="rti2-guide" hidden><h2>Flow and calibration guide</h2><p>Every plate stores the exposed shape and its original calibration. Rows P, V, C are current position, velocity and current; I and V₀ are initial position and velocity. All pairs are x,y in tank pixels and seconds. White arrows are velocity; blue arrows are current. Fully illuminate every shell before emitting.</p><p>Removing a wanted load selects a sealed valve preset: A=(10,16,20), B=(-10,-16,20), C=(16,-12,30), D=(-16,12,30). The switch changes the flow and current, while position and velocity remain continuous. Each actual switch and its time are stamped below the tank. The next preset is not disclosed.</p><p>The flow evolves in 10-ms steps: X′=X+0.005·10(Y−X); Y′=Y+0.005[X(28−Z)−Y]; Z′=Z+0.005[XY−(8/3)Z]. Values round to six decimals. Current tends toward speed·sign·(X/18+0.4(y−250)/500) horizontally and speed·sign·(Y/24−0.4(x−450)/900) vertically. Horizontal sign is negative on even plates; vertical sign is negative on plates divisible by three. Current memory is ${state.world.current_memory_ms} ms; current is limited to ±1.8·speed. Velocity follows current at 1.5/s. Motion and contacts round to 0.001; circles reflect and collide. Speed parameter: ${state.world.speed} px/s; shell radius: ${state.world.carrier_radius}; lens radius: ${state.world.lens_radius}.</p><p>The scanner uses spring 36, acceleration limit ${state.world.scanner_acceleration}, speed limit ${state.world.scanner_speed}, and damping ${state.world.scanner_damping}. It rounds position and velocity to 0.001. A pulse remains at its origin, takes ${state.world.pulse_lag_ms} ms to arrive, and hits the nearest untagged shell within shell radius + 6. Recharge is 1000 ms.</p><button id="rti2-guide-close">CLOSE GUIDE</button></div><div class="rti2-main"><div class="rti2-stage"><canvas id="rti2-tank" width="900" height="500"></canvas><div class="rti2-verdict" hidden></div>
      <div class="rti2-scanner-line">SCANNER P <b id="rti2-scanner-position"></b> · V <b id="rti2-scanner-velocity"></b> · DEST <b id="rti2-scanner-target"></b> · PULSE <b id="rti2-flight"></b></div></div>
      <aside><span class="rti2-label">TAG THESE / LEAVE THE OTHERS</span><div class="rti2-cards">${state.wanted.map((g,i)=>`<div class="rti2-card"><canvas id="rti2-card-${i}" width="104" height="104"></canvas></div>`).join('')}</div>
      <dl><div><dt>TAGGED</dt><dd id="rti2-count"></dd></div><div><dt>REMAINING</dt><dd id="rti2-time"></dd></div><div><dt>PLATES</dt><dd id="rti2-inspected"></dd></div><div><dt>PULSE TRAVEL</dt><dd>${(state.world.pulse_lag_ms/1000).toFixed(2)}s</dd></div><div><dt>RECHARGE</dt><dd id="rti2-charge"></dd></div></dl>
      <p>Fully illuminate every shell. Certified glyphs stay on the plates; all plates must be certified before firing.</p>
      <p>${model.mode==='full'?'Drag the crosshair; SPACE emits.':'Click the tank to steer; PULSE emits.'} The scanner has inertia. Pulses strike their fixed origin after travel. Tags switch the flow. Misses, protected tags or incomplete certification fail.</p>
      <div class="rti2-actions"><button id="rti2-start">START SURVEY</button><button id="rti2-certify">CERTIFY</button><button id="rti2-pulse" ${model.mode==='full'?'hidden':''}>PULSE</button></div></aside></div>
      <div class="rti2-photos">${state.carriers.map(item=>`<div class="rti2-photo"><span>PLATE ${String(item.plate).padStart(2,'0')}</span><canvas id="rti2-photo-${item.plate}" width="96" height="68"></canvas><div class="rti2-motion" id="rti2-motion-${item.plate}"></div></div>`).join('')}</div>
      <footer><div><span>ROWS P/V/C: POSITION/VELOCITY/CURRENT · I/V₀: INITIAL CALIBRATION · X,Y · TRACES 0.8s</span><div class="rti2-flowline">FLOW <b id="rti2-flow"></b> · TIME <b id="rti2-tick"></b></div><div class="rti2-flowline">INITIAL ${state.world.flow_initial.map((x,i)=>`${'XYZ'[i]} ${x.toFixed(6)}`).join(' · ')} · SWITCHES <b id="rti2-valves"></b></div></div><div class="readout">Inspect the requested shapes. Start when ready.</div></footer></section>`;
    state.wanted.forEach((g,i)=>glyph(document.getElementById(`rti2-card-${i}`).getContext('2d'),g,52,58,32,'#283e42'));
    document.getElementById('rti2-guide').insertAdjacentHTML('afterbegin','<p><b>NON-REAL-TIME COUNTERPART:</b> waiting does not advance carriers, flow, recharge, or pulse opportunities. Scanner controls advance one fixed action step; a pulse action settles its fixed flight before the next decision.</p>');
    document.getElementById('rti2-start').addEventListener('click',()=>{
      if(model.active||model.terminal)return;model.active=true;record('start','start_button');
      document.getElementById('rti2-guide').hidden=true;document.getElementById('rti2-start').disabled=true;document.getElementById('rti2-guide-button').disabled=true;helpers.setReadout('SURVEY READY · ACTION STEPS ONLY','idle');draw();
    });
    document.getElementById('rti2-guide-button').addEventListener('click',()=>{if(!model.active&&!model.terminal)document.getElementById('rti2-guide').hidden=false;});
    document.getElementById('rti2-guide-close').addEventListener('click',()=>document.getElementById('rti2-guide').hidden=true);
    const tank=document.getElementById('rti2-tank');
    tank.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;sync();if(!model.active||model.terminal)return;
      const p=point(event);
      if(model.mode==='simplified') { model.sim.target=p;record('aim','aim_click',{point:p});advanceAction(); }
      else if(Math.hypot(p[0]-model.sim.aim[0],p[1]-model.sim.aim[1])<=24) {
        model.pointer=event.pointerId;model.sim.drag=true;tank.setPointerCapture(event.pointerId);
        model.sim.target=p;record('drag_start','scanner_drag',{point:p});advanceAction();
      }
      event.preventDefault();draw();
    });
    tank.addEventListener('pointermove',event=>{
      sync();if(!model.active||model.terminal||model.pointer!==event.pointerId||!model.sim.drag)return;
      const p=point(event);model.sim.target=p;record('drag_move','scanner_drag',{point:p});advanceAction();draw();
    });
    const release=event=>{
      sync();if(model.pointer!==event.pointerId||!model.sim.drag||model.terminal)return;
      const p=point(event);model.sim.target=p;record('drag_end','scanner_drag',{point:p});model.sim.drag=false;model.pointer=null;advanceAction();
      if(tank.hasPointerCapture(event.pointerId))tank.releasePointerCapture(event.pointerId);draw();
    };
    tank.addEventListener('pointerup',release);tank.addEventListener('pointercancel',release);
    tank.addEventListener('lostpointercapture',event=>{if(model.sim.drag)release(event);});
    keyHandler=event=>{if(model.mode==='full'&&event.code==='Space'&&!event.repeat){event.preventDefault();fire();}};
    window.addEventListener('keydown',keyHandler);
    document.getElementById('rti2-pulse').addEventListener('click',()=>{if(model.mode==='simplified')fire();});
    document.getElementById('rti2-certify').addEventListener('click',()=>{sync();if(!model.terminal)void finish('INCOMPLETE SURVEY');});
    draw();
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.reveal_to_identify_nonrealtime={rootSelector:'.rti2',render};
})();
