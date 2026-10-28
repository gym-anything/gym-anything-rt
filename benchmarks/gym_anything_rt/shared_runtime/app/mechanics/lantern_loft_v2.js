(() => {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const copy = x => structuredClone(x);
  let model = null, cleanup = null, frame = 0;
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function gust(d, ms, w) {
    const u = Math.max(0, ms) / w.parameters.gust_span_ms, i = Math.floor(u), f = u - i, blend = f*f*(3-2*f);
    return w.parameters.gust_force * (noise(d.gust_seed, i)*(1-blend) + noise(d.gust_seed, i+1)*blend);
  }
  class LoftPhysics {
    constructor(w) {
      this.world = w; this.ms = 0; this.active = false; this.failed = ''; this.solved = false; this.deck = 0;
      this.local_x = w.decks[0].in_x; this.x = this.local_x; this.vx = 0; this.walk = new Set();
      this.positions = w.decks.map(d => d.initial_x); this.velocities = w.decks.map(d => d.initial_v);
      this.commands = w.decks.map(() => 0); this.crossing = null;
    }
    start() { if (this.active || this.failed || this.solved) throw new Error('launch once'); this.active = true; }
    setMotor(i, value) { this.commands[i] = value; }
    setWalk(direction, held) { if (held) this.walk.add(direction); else this.walk.delete(direction); }
    cross() {
      if (!this.active || this.crossing || this.failed || this.solved) return false;
      const d = this.world.decks[this.deck], half = this.world.parameters.port_width/2 - this.world.radius;
      const ports = [[d.out_x, d.out_height]];
      if (this.world.parameters.false_ports && d.in_height !== d.out_height) ports.push([d.in_x, d.in_height]);
      const hit = ports.find(p => Math.abs(this.local_x-p[0]) <= half);
      if (!hit) return false;
      this.crossing = {start_ms: this.ms, port_x: hit[0], height: hit[1]};
      this.x = this.positions[this.deck] + this.local_x; this.vx += this.velocities[this.deck]; return true;
    }
    advance(end) {
      const w = this.world;
      while (this.active && this.ms + 20 <= end && !this.failed && !this.solved) {
        this.ms += 20;
        for (let i=0; i<w.decks.length; i++) {
          const d = w.decks[i]; if (!d.moving) continue;
          const motor = this.commands[i] - w.parameters.coupling*(this.commands[i-1]+this.commands[i+1]);
          const a = w.motor_force*motor + gust(d, this.ms, w) - w.spring*this.positions[i] - w.damping*this.velocities[i];
          this.velocities[i] = clamp(this.velocities[i]+a*.02, -w.deck_speed, w.deck_speed);
          this.positions[i] = clamp(this.positions[i]+this.velocities[i]*.02, -w.rail_limit, w.rail_limit);
          if (Math.abs(this.positions[i]) === w.rail_limit) this.velocities[i] = 0;
        }
        const thrust = Number(this.walk.has(1))-Number(this.walk.has(-1));
        this.vx = clamp(this.vx+(thrust*w.walk_acceleration-w.walk_damping*this.vx)*.02, -w.walk_speed, w.walk_speed);
        if (!this.crossing) {
          this.local_x = clamp(this.local_x+this.vx*.02, -w.body_half_width+w.radius, w.body_half_width-w.radius);
          if (Math.abs(this.local_x) === w.body_half_width-w.radius) this.vx = 0;
          this.x = this.positions[this.deck]+this.local_x;
        } else {
          this.x += this.vx*.02;
          const f = (this.ms-this.crossing.start_ms)/w.parameters.crossing_ms, y=130*f;
          const dst=w.decks[this.deck+1], r=w.radius;
          let safe = true;
          if (y-r < 65) {
            const center=this.positions[this.deck]+(y+r>40?this.crossing.port_x:0), half=y+r>40?w.parameters.port_width/2:w.body_half_width;
            safe=Math.abs(this.x-center)+r <= half;
          }
          if (y+r > 65) {
            const center=this.positions[this.deck+1]+(y-r<90?dst.in_x:0), half=y-r<90?w.parameters.port_width/2:w.body_half_width;
            safe = safe && Math.abs(this.x-center)+r <= half && this.crossing.height === dst.in_height;
          }
          if (!safe) this.failed = 'The lantern fell from an unsupported edge.';
          else if (f >= 1) {
            this.deck++; this.local_x = this.x-this.positions[this.deck]; this.vx -= this.velocities[this.deck];
            this.crossing = null; this.solved = this.deck === w.decks.length-1;
          }
        }
        if (this.ms >= w.max_ms && !this.solved) this.failed = 'The flight ended before the beacon was reached.';
      }
    }
    snapshot() { return {ms:this.ms, active:this.active, failed:this.failed, solved:this.solved, deck:this.deck, local_x:this.local_x,
      x:this.x, vx:this.vx, positions:[...this.positions], velocities:[...this.velocities], commands:[...this.commands], walk:[...this.walk].sort(), crossing:copy(this.crossing)}; }
  }
  window.LanternLoftV2Physics = LoftPhysics;
  window.LanternLoftV2Gust = gust;
  function record(kind, details) { model.events.push({seq:model.events.length+1, kind, t_ms:model.sim.ms, ...details}); }
  function sync() {
    if (model.terminal || !model.sim.active) return;
    model.sim.advance(Math.floor((performance.now()-model.epoch)/20)*20);
    if (model.sim.failed || model.sim.solved) finish('terminal_contact');
  }
  function act(kind, details, effect) { sync(); if (model.terminal) return; effect(); record(kind, details); draw(); }
  function launch() {
    if (model.sim.active || model.terminal) return;
    act('start', {input_source:'launch_button'}, () => {model.epoch=performance.now(); model.sim.start();});
    document.querySelector('#loft-v2-start').disabled = true;
  }
  function walk(direction, held, source) {
    sync(); if (model.terminal || !model.sim.active || model.sim.walk.has(direction) === held) return;
    act('walk', {direction, held, input_source:source}, () => model.sim.setWalk(direction, held));
  }
  function cross(source) {
    sync(); if (model.terminal || !model.sim.active) return;
    const accepted = model.sim.cross(); record('cross', {accepted, input_source:source});
    if (!accepted) model.helpers.setReadout('No forward plank underfoot. Move along this loft to an opening.', 'idle');
    draw();
  }
  async function finish(source) {
    if (model.terminal) return;
    if (source === 'seal_button') { sync(); if (model.terminal) return; }
    model.terminal = true;
    document.querySelector('#loft-v2-start').disabled = true;
    record('seal', {input_source:source});
    const sim=model.sim, success=sim.solved && !sim.failed;
    const verdict=document.querySelector('.loft-v2-verdict');
    verdict.dataset.visible='true'; verdict.dataset.pass=String(success);
    verdict.innerHTML=`<strong>${success?'BEACON REACHED':'EPISODE ENDED'}</strong><span>${success?'LANTERN DELIVERED':sim.failed || 'The beacon was not reached.'}</span>`;
    document.querySelector('.loft-v2-phase').textContent=success?'BEACON REACHED':'EPISODE ENDED';
    model.helpers.setReadout(success?'VERIFYING LANTERN DELIVERY…':'FAIL · EPISODE ENDED',success?'pending':'error');
    const payload={mechanic_id:model.state.mechanic_id, task_id:model.state.task_id, challenge_id:model.state.challenge_id,
      revision:model.state.world.revision, interaction_mode:model.interaction, events:copy(model.events),
      final_t_ms:sim.ms, completed:success, final_state:sim.snapshot()};
    model.submission=payload;
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const result=await response.json(); model.grade=result;
      verdict.querySelector('strong').textContent=result.passed?'PASS · BEACON REACHED':'FAIL · EPISODE ENDED';
      verdict.dataset.pass=String(result.passed === true);
      model.helpers.setReadout(result.passed?'PASS · LANTERN DELIVERED':'FAIL · EPISODE ENDED',result.passed?'passed':'error');
    } catch (e) { verdict.querySelector('strong').textContent='VERIFIER UNAVAILABLE'; model.helpers.setReadout(`VERIFIER ERROR · ${e.message}`,'error'); }
  }
  function heightAt(d, x) {
    const f=clamp((x+16)/32,0,1);
    return d.in_x < 0 ? d.in_height+(d.out_height-d.in_height)*f : d.out_height+(d.in_height-d.out_height)*f;
  }
  function project(x,y,z) { return [430+x*.88+y*.24,470-y*.43-z*28]; }
  function polygon(ctx, points, color, stroke='#554864') {
    ctx.beginPath(); points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.strokeStyle=stroke;ctx.lineWidth=1;ctx.stroke();
  }
  function patch(ctx,x0,x1,y0,y1,z0,z1,color) {
    const p=[project(x0,y0,z0),project(x1,y0,z1),project(x1,y1,z1),project(x0,y1,z0)];
    polygon(ctx,[p[0],p[1],[p[1][0],p[1][1]+9],[p[0][0],p[0][1]+9]],'#805e62');
    polygon(ctx,p,color);return p;
  }
  function draw() {
    if (!model) return;
    const canvas=document.querySelector('#loft-v2-canvas'), ctx=canvas.getContext('2d'), s=model.sim, w=s.world;
    const bg=ctx.createLinearGradient(0,0,0,540);bg.addColorStop(0,'#151d38');bg.addColorStop(.58,'#55506b');bg.addColorStop(1,'#d3917f');
    ctx.fillStyle=bg;ctx.fillRect(0,0,900,540);
    ctx.fillStyle='#fff0c0';ctx.beginPath();ctx.arc(98,86,38,0,Math.PI*2);ctx.fill();
    for (let i=0;i<26;i++) {
      const x=i*37-15, h=35+((i*67)%103);ctx.fillStyle=i%2?'#352f50':'#403755';ctx.fillRect(x,540-h,31,h);
      ctx.fillStyle='#e6ae8299';for(let yy=550-h;yy<540;yy+=20)for(let xx=x+5;xx<x+27;xx+=11)ctx.fillRect(xx,yy,4,7);
    }
    for (let i=w.decks.length-1;i>=0;i--) {
      const d=w.decks[i], x=s.positions[i], y=d.y;
      ctx.strokeStyle='#ecd8b93d';ctx.lineWidth=3;
      ctx.beginPath();ctx.moveTo(...project(-w.rail_limit-155,y,0));ctx.lineTo(...project(w.rail_limit+155,y,0));ctx.stroke();
      const left=d.in_x<0?d.in_height:d.out_height, right=d.in_x<0?d.out_height:d.in_height;
      patch(ctx,x-140,x-16,y-40,y+40,left,left,'#dbb897');
      patch(ctx,x-16,x+16,y-40,y+40,left,right,'#efcfab');
      patch(ctx,x+16,x+140,y-40,y+40,right,right,'#c9a68e');
      for(let t=0;t<=1;t+=.125) { const xx=x-16+32*t, zz=left+(right-left)*t;ctx.strokeStyle='#645566';ctx.beginPath();ctx.moveTo(...project(xx,y-40,zz));ctx.lineTo(...project(xx,y+40,zz));ctx.stroke(); }
      const ph=w.parameters.port_width/2;
      if(i>0)patch(ctx,x+d.in_x-ph,x+d.in_x+ph,y-65,y-40,d.in_height,d.in_height,'#9ac3b5');
      if(i<w.decks.length-1)patch(ctx,x+d.out_x-ph,x+d.out_x+ph,y+40,y+65,d.out_height,d.out_height,'#f1d38f');
      if(i<w.decks.length-1 && w.parameters.false_ports && d.in_height!==d.out_height)patch(ctx,x+d.in_x-ph,x+d.in_x+ph,y+40,y+65,d.in_height,d.in_height,'#f1d38f');
      // Parapets agree with the broad standing surface; necks remain unrailed.
      ctx.strokeStyle='#5b4665';ctx.lineWidth=4;
      for(const edge of [-140,140]) {ctx.beginPath();ctx.moveTo(...project(x+edge,y-40,edge<0?left:right));ctx.lineTo(...project(x+edge,y+40,edge<0?left:right));ctx.stroke();}
      const p=project(x,y,Math.max(left,right));ctx.textAlign='center';ctx.fillStyle='#33253f';ctx.font='bold 13px ui-monospace';ctx.fillText(d.name,p[0],p[1]+5);
      for (const [px,h] of [[d.in_x,d.in_height],[d.out_x,d.out_height]]) {const q=project(x+px,y,h);ctx.fillStyle='#483447';ctx.font='bold 12px ui-monospace';ctx.fillText(`Z${h}`,q[0],q[1]+6);}
      if (i===w.decks.length-1) {const q=project(x+d.in_x,y,d.in_height);ctx.fillStyle='#ffeea2';ctx.shadowColor='#ffe395';ctx.shadowBlur=20;ctx.beginPath();ctx.arc(q[0],q[1]-25,12,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;ctx.strokeStyle='#ffecb6';ctx.lineWidth=3;ctx.strokeRect(q[0]-16,q[1]-41,32,52);}
    }
    // Wind evidence belongs above the geometry, so raised lofts cannot hide it.
    // Fixed row labels associate each flag/forecast with its physical winch.
    for(let i=1;i<w.decks.length-1;i++) {
      const d=w.decks[i], py=470-d.y*.43, px=112;
      ctx.fillStyle='#17223dcc';ctx.fillRect(12,py-42,152,43);
      ctx.textAlign='left';ctx.fillStyle='#e8d4b4';ctx.font='11px ui-monospace';ctx.fillText(d.name,20,py-13);
      ctx.strokeStyle='#8ebfa9';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(px,py-25);ctx.lineTo(px,py-2);ctx.stroke();
      const force=gust(d,s.ms,w)/w.parameters.gust_force, soon=gust(d,s.ms+1200,w)/w.parameters.gust_force;
      polygon(ctx,[[px,py-25],[px+force*40,py-18],[px,py-10]],'#9ee4c2','#d6ffe5');
      ctx.strokeStyle='#fde6a8';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(px,py-34);ctx.lineTo(px+soon*40,py-34);ctx.stroke();
      ctx.fillStyle='#94dac3';
      for(const old of model.trails[i]){const q=project(old.x,d.y-53,0);ctx.globalAlpha=.12+.3*(old.ms-(s.ms-600))/600;ctx.beginPath();ctx.arc(q[0],q[1],2.5,0,Math.PI*2);ctx.fill();}ctx.globalAlpha=1;
    }
    const d=w.decks[s.deck];let y=d.y, z=heightAt(d,s.local_x);
    if(s.crossing){y += 130*clamp((s.ms-s.crossing.start_ms)/w.parameters.crossing_ms,0,1);z=s.crossing.height;}
    const p=project(s.x,y,z);
    polygon(ctx,[project(s.x-8,y-8,z),project(s.x+8,y-8,z),project(s.x+8,y+8,z),project(s.x-8,y+8,z)],'#29344f','#21263c');
    ctx.strokeStyle='#20273e';ctx.lineWidth=4;ctx.beginPath();ctx.moveTo(p[0]-4,p[1]-2);ctx.lineTo(p[0]-3,p[1]-17);ctx.lineTo(p[0]+4,p[1]-1);ctx.stroke();
    ctx.fillStyle='#568b90';ctx.fillRect(p[0]-7,p[1]-23,13,16);ctx.fillStyle='#eec3a0';ctx.beginPath();ctx.arc(p[0]-1,p[1]-29,6,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#fce095';ctx.shadowBlur=16;ctx.shadowColor='#ffc375';ctx.fillRect(p[0]+9,p[1]-24,9,14);ctx.shadowBlur=0;
    ctx.strokeStyle='#5d435b';ctx.lineWidth=2;ctx.strokeRect(p[0]+9,p[1]-24,9,14);
    for (let i=1;i<w.decks.length-1;i++) { const knob=document.querySelector(`[data-lever="${i}"] .loft-v2-knob`);if(knob)knob.style.left=`${(80+s.commands[i]*48)/160*100}%`; }
    document.querySelector('.loft-v2-location').textContent=d.name;
    const root=document.querySelector('.loft-v2');root.dataset.active=String(s.active);root.dataset.crossing=String(Boolean(s.crossing));
    if(!model.terminal)document.querySelector('.loft-v2-phase').textContent=!s.active?'INSPECT · LAUNCH WHEN READY':s.crossing?'CROSSING · KEEP YOUR FEET ON THE PLANKS':'WALK · SHIFT · WATCH THE CONNECTION';
  }
  function animate() {
    sync();const s=model.sim;
    for(let i=1;i<s.positions.length-1;i++) {let trail=model.trails[i];if(!trail.length || s.ms-trail.at(-1).ms>=80)trail.push({ms:s.ms,x:s.positions[i]});model.trails[i]=trail.filter(p=>p.ms>=s.ms-600);}
    draw();frame=requestAnimationFrame(animate);
  }
  function render(state, helpers) {
    cleanup?.();cancelAnimationFrame(frame);document.body.dataset.mechanic='lantern-loft-v2';
    const interaction=state.control_condition?.interaction || 'full';
    model={state,helpers,interaction,sim:new LoftPhysics(copy(state.world)),events:[],terminal:false,epoch:0,
      trails:state.world.decks.map(()=>[]),hold:null,submission:null};window.lanternLoftV2Model=model;
    const full=interaction==='full';
    helpers.app.innerHTML=`<section class="loft-v2" data-interaction="${interaction}"><header><div><small>THE ROOFTOP POST / DRIFTING STAIRWALKS</small><h1>Lantern Loft V2</h1></div><div class="loft-v2-location">DOORSTEP</div></header><main><div class="loft-v2-stage"><canvas id="loft-v2-canvas" width="900" height="540" aria-label="Sliding lofts, physical stairs and a lantern courier"></canvas><div class="loft-v2-verdict" data-visible="false"></div><div class="loft-v2-legend">GREEN · INCOMING PLANK &nbsp; GOLD · FORWARD PLANK<br>FLAGS · GUST NOW &nbsp; PALE LINE · GUST IN 1.2s &nbsp; DOTS · RECENT DRIFT</div></div><aside><h2>Shift the path.<br>Keep the lantern.</h2><p>Move along each loft to a forward plank. Cross to the next loft through matching heights. The lofts drift while you walk and cross.</p><div class="loft-v2-winches">${state.world.decks.filter(d=>d.moving).map(d=>{const i=Number(d.id.split('-')[1]);return `<div class="loft-v2-winch"><b>${d.name}${state.world.parameters.coupling?' · SHARED ROPE':''}</b><div class="loft-v2-lever" data-lever="${i}"><span>←</span><span>○</span><span>→</span><i class="loft-v2-knob" style="left:80px"></i></div>${full?'':`<div class="loft-v2-detents">${[-1,0,1].map(v=>`<button data-motor="${i}" data-value="${v}">${v<0?'LEFT':v?'RIGHT':'NEUTRAL'}</button>`).join('')}</div>`}</div>`;}).join('')}</div><p class="loft-v2-controls">${full?'Drag a winch handle to a detent.<br>Hold ← / → to walk. SPACE to cross.':'Click a winch detent.<br>Hold WALK buttons to steer, including while crossing.'}<br>Neutral releases motor force; gusts continue.${state.world.parameters.coupling?'<br>A winch also pulls neighboring lofts in the opposite direction.':''}</p>${full?'':`<div class="loft-v2-walk"><button data-walk="-1">WALK ←</button><button data-walk="1">WALK →</button></div><button id="loft-v2-cross">CROSS FORWARD</button>`}<button id="loft-v2-start">LAUNCH FLIGHT</button></aside></main><footer><div><b class="loft-v2-phase">INSPECT · LAUNCH WHEN READY</b><div class="readout">A fall or END / CERTIFY before delivery ends the episode.</div></div><button id="loft-v2-seal">END / CERTIFY</button></footer></section>`;
    document.querySelector('#loft-v2-start').addEventListener('click',launch);
    document.querySelector('#loft-v2-seal').addEventListener('click',()=>finish('seal_button'));
    document.querySelector('#loft-v2-cross')?.addEventListener('click',()=>cross('cross_button'));
    document.querySelectorAll('[data-motor]').forEach(b=>b.addEventListener('click',()=>act('motor',{deck:Number(b.dataset.motor),value:Number(b.dataset.value),input_source:'winch_buttons'},()=>model.sim.setMotor(Number(b.dataset.motor),Number(b.dataset.value)))));
    document.querySelectorAll('[data-walk]').forEach(b=>{
      b.addEventListener('pointerdown',e=>{if(e.button!==0)return;b.setPointerCapture(e.pointerId);walk(Number(b.dataset.walk),true,'walk_buttons');e.preventDefault();});
      for(const type of ['pointerup','pointercancel','lostpointercapture'])b.addEventListener(type,()=>walk(Number(b.dataset.walk),false,'walk_buttons'));
    });
    document.querySelectorAll('[data-lever]').forEach(lever=>{
      const point=e=>{const r=lever.getBoundingClientRect();return [(e.clientX-r.left)*160/r.width,(e.clientY-r.top)*40/r.height];};
      lever.addEventListener('pointerdown',e=>{if(!full||e.button!==0||model.terminal)return;sync();if(model.terminal)return;const p=point(e),i=Number(lever.dataset.lever);if(Math.abs(p[0]-(80+model.sim.commands[i]*48))>19)return;model.hold=i;lever.setPointerCapture(e.pointerId);record('lever_down',{deck:i,point:p,input_source:'lever_drag'});e.preventDefault();});
      lever.addEventListener('pointermove',e=>{if(model.hold!==Number(lever.dataset.lever)||model.terminal)return;const p=point(e),i=model.hold,value=p[0]<56?-1:p[0]>104?1:0;act('lever_move',{deck:i,point:p,input_source:'lever_drag'},()=>model.sim.setMotor(i,value));});
      const up=e=>{if(model.hold!==Number(lever.dataset.lever))return;sync();if(!model.terminal)record('lever_up',{deck:model.hold,point:point(e),input_source:'lever_drag'});model.hold=null;try{lever.releasePointerCapture(e.pointerId);}catch{}};
      lever.addEventListener('pointerup',up);lever.addEventListener('pointercancel',up);lever.addEventListener('lostpointercapture',up);
    });
    const down=e=>{if(!full||e.repeat||e.altKey||e.ctrlKey||e.metaKey)return;if(['ArrowLeft','ArrowRight','Space'].includes(e.code))e.preventDefault();if(e.code==='ArrowLeft')walk(-1,true,'keyboard');if(e.code==='ArrowRight')walk(1,true,'keyboard');if(e.code==='Space')cross('keyboard');};
    const up=e=>{if(!full)return;if(e.code==='ArrowLeft')walk(-1,false,'keyboard');if(e.code==='ArrowRight')walk(1,false,'keyboard');};
    const blur=()=>{if(model.terminal)return;for(const direction of [...model.sim.walk])walk(direction,false,full?'keyboard':'walk_buttons');if(model.hold!==null){sync();if(!model.terminal)record('lever_up',{deck:model.hold,point:[80+model.sim.commands[model.hold]*48,20],input_source:'lever_drag'});model.hold=null;}};
    window.addEventListener('keydown',down);window.addEventListener('keyup',up);window.addEventListener('blur',blur);
    cleanup=()=>{window.removeEventListener('keydown',down);window.removeEventListener('keyup',up);window.removeEventListener('blur',blur);};
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.lantern_loft_v2={rootSelector:'.loft-v2',render};
})();
