(() => {
  'use strict';
  let model = null, frame = 0;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const q = x => Math.round(x * 1e6) / 1e6;
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295;
  }
  function speed(state, channel, tick) {
    const p = state.parameters, u = tick * 10 / p.speed_span_ms, k = Math.floor(u), f = u-k;
    const a = noise(channel.motion_seed, k), b = noise(channel.motion_seed, k+1);
    return p.speed_min + (p.speed_max-p.speed_min)*(a+(b-a)*f*f*(3-2*f));
  }
  function beamY(state, angle) {
    return (state.optics.receiver_x-state.optics.mirror_x)*Math.tan(2*angle*Math.PI/180);
  }
  function trimPoint(state, i, angle) {
    const o = state.optics;
    return [o.trim_left+(angle/o.mirror_limit_deg+1)/2*(o.trim_right-o.trim_left), o.row_centers[i]+69];
  }
  function trimAngle(state, point) {
    const o = state.optics;
    return clamp((point[0]-o.trim_left)/(o.trim_right-o.trim_left)*2-1,-1,1)*o.mirror_limit_deg;
  }
  class Physics {
    constructor(state) {
      this.state = state; this.tick = this.active_tick = 0;
      this.started = this.ready = this.complete = false; this.failed = '';
      const n = state.channels.length;
      this.angles = Array(n).fill(0); this.velocities = Array(n).fill(0); this.targets = Array(n).fill(0);
      this.positions = state.channels.map(c => c.initial_y); this.directions = state.channels.map(c => c.direction);
      this.charges = Array(n).fill(0); this.heat = Array(n).fill(0); this.hits = Array(n).fill(false);
      this.trails = state.channels.map(c => [c.initial_y]);
    }
    advance(target) {
      const p = this.state.parameters, r = this.state.requirements, o = this.state.optics;
      while (this.tick < target && !this.failed && !this.complete) {
        this.tick++;
        const v = this.angles.map((angle, i) => {
          const acceleration = clamp((this.targets[i]-angle)*100-this.velocities[i]*20,-p.servo_acceleration,p.servo_acceleration);
          return clamp(this.velocities[i]+acceleration*.01,-p.servo_speed,p.servo_speed);
        });
        const total = v.reduce((a, b) => a+Math.abs(b), 0), scale = total ? Math.min(1,p.shared_slew_budget/total) : 1;
        this.velocities = v.map(x => x*scale);
        this.angles = this.angles.map((angle, i) => {
          const a = clamp(angle+this.velocities[i]*.01,-o.mirror_limit_deg,o.mirror_limit_deg);
          if (Math.abs(a) === o.mirror_limit_deg) this.velocities[i] = 0;
          return a;
        });
        if (!this.started) {
          if (this.tick >= r.max_ticks) this.failed = 'The optical supply expired.';
          continue;
        }
        this.active_tick++;
        this.state.channels.forEach((channel, i) => {
          this.positions[i] += this.directions[i]*speed(this.state,channel,this.active_tick)*.01;
          const bound = o.rail_half_span;
          if (this.positions[i] > bound) { this.positions[i] = 2*bound-this.positions[i]; this.directions[i] = -1; }
          else if (this.positions[i] < -bound) { this.positions[i] = -2*bound-this.positions[i]; this.directions[i] = 1; }
          this.hits[i] = Math.abs(beamY(this.state,this.angles[i])-this.positions[i])+o.beam_width/2 <= p.receiver_height/2;
          if (!this.ready) {
            this.charges[i] = clamp(this.charges[i]+(this.hits[i] ? .01 : -.01*r.charge_leak),0,p.charge_seconds);
            this.heat[i] = clamp(this.heat[i]+(this.hits[i] ? -.01*r.cooling_rate : .01),0,p.heat_limit_seconds);
          }
          this.trails[i].push(this.positions[i]); if (this.trails[i].length > 25) this.trails[i].shift();
        });
        if (this.heat.some(h => h >= p.heat_limit_seconds-1e-9)) this.failed = 'A receiver overheated.';
        else if (this.charges.every(c => c >= p.charge_seconds-1e-9)) this.ready = true;
        if (this.active_tick >= r.active_limit_ticks || this.tick >= r.max_ticks) this.failed = 'The optical supply expired.';
      }
    }
    placeKey(point) {
      const o=this.state.optics,p=this.state.parameters,radius=o.seal_key_radius;
      if (!this.ready || this.failed || this.complete) throw new Error('The seal key is not available');
      const center=o.row_centers[0]+this.positions[0];
      if (Math.abs(point[0]-o.receiver_x)+radius <= o.receiver_width/2 && Math.abs(point[1]-center)+radius <= p.receiver_height/2) this.complete=true;
      else this.failed="The seal key missed AMBER's moving opening.";
    }
    snapshot() {
      const result = {tick:this.tick,active_tick:this.active_tick,started:this.started,ready:this.ready,complete:this.complete,failed:this.failed};
      for (const key of ['angles','velocities','targets','positions','directions','charges','heat']) result[key] = this[key].map(q);
      return result;
    }
  }
  // Read-only diagnostics for implementation validation, never an input API.
  window.RayglassVaultV2Physics = Physics;
  window.RayglassVaultV2Math = {noise, speed, beamY, trimPoint, trimAngle};
  function sync() {
    if (!model || model.terminal) return;
    model.sim.advance(Math.min(model.state.requirements.max_ticks,Math.max(0,Math.floor((performance.now()-model.createdAt+1e-7)/10))));
    if (model.sim.failed || model.sim.complete) finish();
  }
  function record(kind, details = {}) {
    model.events.push({sequence:model.events.length+1,kind,tick:model.sim.tick,...details});
  }
  function point(event, canvas) {
    const rect = canvas.getBoundingClientRect();
    return [Math.round(clamp((event.clientX-rect.left)*canvas.width/rect.width,0,canvas.width)*1000)/1000,
            Math.round(clamp((event.clientY-rect.top)*canvas.height/rect.height,0,canvas.height)*1000)/1000];
  }
  function sealPoint(event) {
    // Cross-canvas pointer capture must preserve out-of-bounds releases.
    // Clamping them onto the receiver could turn a visible miss into a pass.
    const canvas=document.getElementById('rgv-optics'),rect=canvas.getBoundingClientRect();
    return [Math.round((event.clientX-rect.left)*canvas.width/rect.width*1000)/1000,
            Math.round((event.clientY-rect.top)*canvas.height/rect.height*1000)/1000];
  }
  function inside(p, box) {
    return Math.abs(p[0]-box.x) <= (box.width || box.size)/2 && Math.abs(p[1]-box.y) <= (box.height || box.size)/2;
  }
  function probe(port, p) {
    const response = model.state.sensor_responses[port];
    model.shots[port] = response; model.last = port;
    record('probe',{port,point:p,response,input_surface:'port_probe'});
    document.getElementById('rgv-reading').textContent = typeof response === 'number'
      ? `BEAM ${port+1} ↔ ${response+1}` : `BEAM ${port+1} · ${response === 'H' ? 'H / ABSORBED' : 'R / REFLECTED'}`;
  }
  function cabinetDown(event) {
    if (event.button !== 0 || model.terminal || model.hold || model.sealSelected) return;
    sync(); if (model.terminal) return;
    const p = point(event,event.currentTarget), cabinet = model.state.cabinet;
    if (model.sim.ready && inside(p,cabinet.seal_key)) {
      if (model.mode === 'full') {
        model.hold={kind:'seal',pointer:event.pointerId,point:sealPoint(event)};
        record('seal_start',{point:p,input_surface:'seal_drag'});
        event.currentTarget.setPointerCapture(event.pointerId);
      } else {
        model.sealSelected=true;
        record('seal_select',{point:p,input_surface:'seal_click'});
      }
      event.preventDefault();draw();return;
    }
    if (model.sim.started) return;
    const channel = cabinet.sockets.findIndex(c => inside(p,c));
    if (channel >= 0) {
      if (model.mode === 'full') {
        model.hold = {kind:'patch',channel,pointer:event.pointerId,point:p};
        record('patch_start',{channel,point:p,input_surface:'patch_drag'});
        event.currentTarget.setPointerCapture(event.pointerId);
      } else {
        model.selected = channel;
        record('select_socket',{channel,point:p,input_surface:'patch_click'});
      }
    } else {
      const port = cabinet.ports.findIndex(c => inside(p,c));
      if (port >= 0) {
        if (model.mode === 'simplified' && model.selected !== null) {
          const channel = model.selected;
          model.routes[channel] = port; model.selected = null;
          record('patch_click',{channel,port,point:p,input_surface:'patch_click'});
        } else if (model.selected === null) probe(port,p);
      }
    }
    event.preventDefault(); draw();
  }
  function cabinetMove(event) {
    if (!model.terminal && model.hold?.kind === 'seal' && model.hold.pointer === event.pointerId) {
      sync();if(model.terminal)return;model.hold.point=sealPoint(event);draw();return;
    }
    if (model.terminal || model.hold?.kind !== 'patch' || model.hold.pointer !== event.pointerId) return;
    model.hold.point = point(event,event.currentTarget); draw();
  }
  function cabinetUp(event) {
    if (!model.terminal && model.hold?.kind === 'seal' && model.hold.pointer === event.pointerId) {
      sync();if(model.terminal)return;
      const p=sealPoint(event),cancel=event.type==='pointercancel';
      model.hold=null;record(cancel?'seal_cancel':'seal_end',{point:p,input_surface:'seal_drag'});
      if(cancel)model.sim.failed='The seal key was dropped outside the receiver.';else model.sim.placeKey(p);
      try { event.currentTarget.releasePointerCapture(event.pointerId); } catch (_) {}
      finish();draw();return;
    }
    if (model.terminal || model.hold?.kind !== 'patch' || model.hold.pointer !== event.pointerId) return;
    sync(); if (model.terminal) return;
    const p = point(event,event.currentTarget), channel = model.hold.channel;
    const found = event.type === 'pointercancel' ? -1 : model.state.cabinet.ports.findIndex(c => inside(p,c));
    const port = found < 0 ? null : found;
    if (port !== null) model.routes[channel] = port;
    model.hold = null; record('patch_end',{channel,port,point:p,input_surface:'patch_drag'});
    try { event.currentTarget.releasePointerCapture(event.pointerId); } catch (_) {}
    draw();
  }
  function opticsDown(event) {
    if (event.button !== 0 || model.terminal || model.hold) return;
    sync(); if (model.terminal) return;
    const p = point(event,event.currentTarget), o = model.state.optics;
    if (model.mode === 'simplified' && model.sealSelected) {
      model.sealSelected=false;record('seal_click',{point:p,input_surface:'seal_click'});
      model.sim.placeKey(p);finish();draw();event.preventDefault();return;
    }
    const channel = o.row_centers.findIndex(y => Math.abs(p[1]-(y+69)) <= 19 && p[0] >= o.trim_left-19 && p[0] <= o.trim_right+19);
    if (channel < 0) return;
    if (model.mode === 'simplified') {
      model.sim.targets[channel] = trimAngle(model.state,p);
      record('trim_target',{channel,point:p,input_surface:'trim_click'});
    } else {
      const handle = trimPoint(model.state,channel,model.sim.targets[channel]);
      if (Math.hypot(p[0]-handle[0],p[1]-handle[1]) > 19) return;
      model.hold = {kind:'trim',channel,pointer:event.pointerId};
      record('trim_start',{channel,point:p,input_surface:'trim_drag'});
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    event.preventDefault(); draw();
  }
  function opticsMove(event) {
    if (model.terminal || model.hold?.kind !== 'trim' || model.hold.pointer !== event.pointerId) return;
    sync(); if (model.terminal) return;
    const p = point(event,event.currentTarget), channel = model.hold.channel;
    model.sim.targets[channel] = trimAngle(model.state,p);
    record('trim_move',{channel,point:p,input_surface:'trim_drag'});
    event.preventDefault(); draw();
  }
  function opticsUp(event) {
    if (model.terminal || model.hold?.kind !== 'trim' || model.hold.pointer !== event.pointerId) return;
    sync(); if (model.terminal) return;
    const p = point(event,event.currentTarget), channel = model.hold.channel;
    // Use the actual release coordinate even with coalesced native movement.
    model.sim.targets[channel] = trimAngle(model.state,p);
    model.hold = null; record('trim_end',{channel,point:p,input_surface:'trim_drag'});
    try { event.currentTarget.releasePointerCapture(event.pointerId); } catch (_) {}
    draw();
  }
  function line(ctx, a, b, color, width=1) {
    ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();
  }
  function drawCabinet() {
    const canvas = document.getElementById('rgv-cabinet'), ctx = canvas.getContext('2d'), s = model.state, g = s.cabinet;
    ctx.clearRect(0,0,canvas.width,canvas.height);
    const glass = ctx.createLinearGradient(50,50,290,290);glass.addColorStop(0,'#193e40');glass.addColorStop(.6,'#0a1c26');glass.addColorStop(1,'#23464b');
    ctx.fillStyle='#aa8959';ctx.fillRect(42,42,256,256);ctx.fillStyle=glass;ctx.fillRect(48,48,244,244);
    const step = 240/s.parameters.size;
    ctx.strokeStyle='#b6dac21e';ctx.lineWidth=1;
    for (let i=0;i<=s.parameters.size;i++) {line(ctx,[50+i*step,50],[50+i*step,290],'#b6dac225');line(ctx,[50,50+i*step],[290,50+i*step],'#b6dac225');}
    ctx.fillStyle='#86afab';ctx.font='12px Georgia';ctx.textAlign='center';ctx.fillText('OPAQUE OPTICAL ARENA',170,165);
    ctx.font='10px monospace';ctx.fillStyle='#779397';ctx.fillText(`${s.parameters.bead_count} HIDDEN BEADS`,170,187);
    if (model.sim.ready) {
      const key=g.seal_key,held=model.sealSelected||model.hold?.kind==='seal';
      ctx.fillStyle=held?'#3c5142':'#182d36';ctx.strokeStyle='#efbc6b';ctx.lineWidth=2;
      ctx.fillRect(key.x-key.width/2,key.y-key.height/2,key.width,key.height);ctx.strokeRect(key.x-key.width/2,key.y-key.height/2,key.width,key.height);
      ctx.fillStyle='#efbc6b';ctx.beginPath();ctx.arc(key.x-36,key.y,s.optics.seal_key_radius,0,Math.PI*2);ctx.fill();
      ctx.font='bold 11px monospace';ctx.fillText(held?'KEY HELD':'SEAL KEY',key.x+8,key.y+4);
      ctx.font='10px monospace';ctx.fillText('PLACE INSIDE AMBER',key.x,key.y+32);
    }
    for (let i=0;i<s.channels.length;i++) {
      const socket=g.sockets[i],port=model.routes[i] === null ? null : g.ports[model.routes[i]];
      if (port) {ctx.beginPath();ctx.moveTo(socket.x,socket.y-28);ctx.bezierCurveTo(socket.x,335,port.x,335,port.x,port.y);ctx.lineWidth=3;ctx.strokeStyle=s.channels[i].color;ctx.stroke();}
    }
    g.ports.forEach((p,i) => {
      const active = model.last === i || (model.last !== null && model.shots[model.last] === i);
      ctx.fillStyle=active?'#36786f':'#182d36';ctx.strokeStyle=active?'#c1ead2':'#8f7c58';ctx.lineWidth=1.5;
      ctx.fillRect(p.x-16,p.y-16,32,32);ctx.strokeRect(p.x-16,p.y-16,32,32);
      ctx.fillStyle='#e8d5a6';ctx.font='bold 12px monospace';ctx.textAlign='center';
      const r=model.shots[i];ctx.fillText(r===undefined?`${i+1}`:typeof r==='number'?`${i+1}↔`:`${i+1}${r}`,p.x,p.y+4);
    });
    g.sockets.forEach((p,i) => {
      const c=s.channels[i];ctx.fillStyle=model.selected===i?'#31564c':'#142930';ctx.strokeStyle=c.color;ctx.lineWidth=model.selected===i?3:1;
      ctx.fillRect(p.x-47,p.y-30,94,60);ctx.strokeRect(p.x-47,p.y-30,94,60);
      ctx.fillStyle=c.color;ctx.font='bold 11px monospace';ctx.fillText(c.label,p.x,p.y-12);
      ctx.font='12px Georgia';ctx.fillText(`EXIT ${c.exit_port+1}`,p.x,p.y+5);
      ctx.font='10px monospace';ctx.fillStyle='#d3d6c6';ctx.fillText(model.routes[i]===null?'UNPATCHED':`INLET ${model.routes[i]+1}`,p.x,p.y+21);
    });
    if (model.hold?.kind==='patch') line(ctx,[g.sockets[model.hold.channel].x,g.sockets[model.hold.channel].y],model.hold.point,s.channels[model.hold.channel].color,3);
    document.getElementById('rgv-start').disabled=model.terminal||model.sim.started||model.routes.some(r=>r===null)||Boolean(model.hold);
    document.getElementById('rgv-probe-mode').disabled=model.terminal||model.sim.started||model.mode==='full';
  }
  function drawOptics() {
    const canvas=document.getElementById('rgv-optics'),ctx=canvas.getContext('2d'),s=model.state,o=s.optics,p=s.parameters,sim=model.sim;
    ctx.clearRect(0,0,canvas.width,canvas.height);
    const wash=ctx.createLinearGradient(0,0,680,490);wash.addColorStop(0,'#142a33');wash.addColorStop(1,'#08151e');ctx.fillStyle=wash;ctx.fillRect(0,0,680,490);
    s.channels.forEach((channel,i) => {
      const cy=o.row_centers[i],y=cy+sim.positions[i],out=cy+beamY(s,sim.angles[i]),color=channel.color;
      ctx.fillStyle='#213b4160';ctx.fillRect(18,cy-74,644,151);ctx.strokeStyle='#779b9140';ctx.strokeRect(18,cy-74,644,151);
      ctx.font='bold 11px monospace';ctx.fillStyle=color;ctx.textAlign='left';ctx.fillText(channel.label+' / EXIT '+(channel.exit_port+1),32,cy-56);
      line(ctx,[o.receiver_x,cy-o.rail_half_span],[o.receiver_x,cy+o.rail_half_span],'#627e80',8);
      for (let offset=-60;offset<=60;offset+=20) line(ctx,[o.receiver_x-6,cy+offset],[o.receiver_x+6,cy+offset],'#839d93',1);
      for (const age of [24,16,8]) {
        const sample=sim.trails[i][Math.max(0,sim.trails[i].length-1-age)];
        // Beside the rail: the receiver must not occlude its own recent trace.
        ctx.fillStyle=color+(age===24?'55':age===16?'88':'bb');ctx.fillRect(o.receiver_x+39,cy+sample-3,12,6);
      }
      const live=sim.started&&!sim.ready;
      line(ctx,[o.mirror_x,cy-43],[o.mirror_x,cy],live?color:'#546d76',o.beam_width);
      line(ctx,[o.mirror_x,cy],[o.receiver_x,out],live?color:'#546d76',o.beam_width);
      const a=(45+sim.angles[i])*Math.PI/180;
      line(ctx,[o.mirror_x-Math.cos(a)*25,cy-Math.sin(a)*25],[o.mirror_x+Math.cos(a)*25,cy+Math.sin(a)*25],'#f3ead0',6);
      ctx.fillStyle='#d1b17b';ctx.beginPath();ctx.arc(o.mirror_x,cy,5,0,Math.PI*2);ctx.fill();
      ctx.fillStyle='#08151e';ctx.fillRect(o.receiver_x-o.receiver_width/2,y-p.receiver_height/2,o.receiver_width,p.receiver_height);
      ctx.strokeStyle=sim.hits[i]||sim.ready?color:'#83a29b';ctx.lineWidth=2;ctx.strokeRect(o.receiver_x-o.receiver_width/2,y-p.receiver_height/2,o.receiver_width,p.receiver_height);
      // Inner opening has exactly the geometry used for whole-beam contact.
      ctx.fillStyle=sim.hits[i]||sim.ready?color+'55':color+'18';ctx.fillRect(o.receiver_x-o.receiver_width/2+1,y-p.receiver_height/2,o.receiver_width-2,p.receiver_height);
      const direction=sim.directions[i];line(ctx,[o.receiver_x+26,y-direction*9],[o.receiver_x+26,y+direction*9],color,2);
      line(ctx,[o.receiver_x+26,y+direction*9],[o.receiver_x+21,y+direction*3],color,2);
      line(ctx,[o.receiver_x+26,y+direction*9],[o.receiver_x+31,y+direction*3],color,2);
      const railY=cy+69;
      line(ctx,[o.trim_left,railY],[o.trim_right,railY],'#708e87',3);
      for(let x=o.trim_left;x<=o.trim_right;x+=(o.trim_right-o.trim_left)/8) line(ctx,[x,railY-5],[x,railY+5],'#708e87',1);
      const handle=trimPoint(s,i,sim.targets[i]);ctx.fillStyle='#172b33';ctx.strokeStyle=color;ctx.lineWidth=2;
      ctx.beginPath();ctx.arc(...handle,17,0,Math.PI*2);ctx.fill();ctx.stroke();
      ctx.fillStyle=color;ctx.fillRect(handle[0]-2,handle[1]-8,4,16);
      const actual=trimPoint(s,i,sim.angles[i]);ctx.fillStyle='#f5edcc';ctx.fillRect(actual[0]-1,railY-24,2,5);
      ctx.textAlign='left';ctx.font='10px monospace';ctx.fillStyle='#b9cbbf';ctx.fillText('↑ TRIM ↓',32,railY+3);
      const bx=548,bw=94;
      ctx.fillStyle='#092025';ctx.fillRect(bx,cy-32,bw,12);ctx.fillRect(bx,cy+6,bw,8);
      ctx.fillStyle=color;ctx.fillRect(bx,cy-32,bw*sim.charges[i]/p.charge_seconds,12);
      ctx.fillStyle='#e38668';ctx.fillRect(bx,cy+6,bw*sim.heat[i]/p.heat_limit_seconds,8);
      ctx.fillStyle='#b9cbbf';ctx.font='10px monospace';ctx.fillText('CHARGE',bx,cy-39);ctx.fillText('HEAT',bx,cy+1);
      ctx.fillStyle=sim.hits[i]?'#cfefc7':'#99b0a9';ctx.fillText(sim.ready?'CHARGE STORED':!live?'READY':sim.hits[i]?'LIGHT HELD':'LIGHT MISSED',bx,cy+33);
    });
    if(model.hold?.kind==='seal'){
      ctx.fillStyle='#efbc6b';ctx.beginPath();ctx.arc(...model.hold.point,o.seal_key_radius,0,Math.PI*2);ctx.fill();
    }
    if (s.channels.length < 3) {
      const y=s.channels.length*160+14;
      ctx.fillStyle='#7ea29d';ctx.font='16px Georgia';ctx.textAlign='left';ctx.fillText('Charge the bank. Insert the seal key.',35,y+45);
      ctx.font='12px Arial';ctx.fillText('Every receiver must hold a full charge at the same time.',35,y+75);
      ctx.fillText('A missed beam drains charge. A full heat bar ends the run.',35,y+96);
    }
  }
  function draw() {
    if (!model) return;
    drawCabinet();drawOptics();
    document.querySelector('.rayglass-vault-v2').dataset.phase=model.terminal?'terminal':model.sim.ready?'seal':model.sim.started?'active':'preparation';
    if(model.sim.ready&&!model.terminal)model.helpers.setReadout(`${model.mode==='full'?'DRAG':'SELECT'} SEAL KEY → AMBER'S MOVING OPENING · A MISS ENDS THE ATTEMPT`,'idle');
  }
  function payload() {
    const s=model.state;
    return {mechanic_id:s.mechanic_id,task_id:s.task_id,challenge_id:s.challenge_id,physics_revision:s.physics_revision,
            control_condition:s.control_condition,interaction_mode:model.mode,events:model.events,
            routes:model.routes,final_tick:model.sim.tick,final_state:model.sim.snapshot(),completed:model.sim.complete&&!model.sim.failed};
  }
  async function finish() {
    if (!model || model.terminal) return;
    model.terminal=true;
    const current=model,verdict=document.getElementById('rgv-verdict');
    const passed=current.sim.complete&&!current.sim.failed;
    const goalFeedback=current.sim.failed||(current.sim.ready?"Place the seal key inside AMBER's moving opening.":'Charge every receiver before sealing the vault.');
    verdict.hidden=false;verdict.dataset.result=passed?'pending':'fail';
    verdict.innerHTML=`<small>OPTICAL ARCHIVE</small><b>${passed?'VERIFYING':'FAIL'}</b><span>${passed?'Checking the optical replay…':goalFeedback}</span>`;
    current.helpers.setReadout(passed?'VERIFYING OPTICAL SEAL…':'FAIL · ATTEMPT ENDED',passed?'pending':'error');draw();
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
      if(!response.ok)throw new Error('HTTP '+response.status);
      const result=await response.json();
      if(model!==current)return;
      if(result.passed===true){verdict.dataset.result='pass';verdict.innerHTML='<small>OPTICAL ARCHIVE</small><b>PASS</b><span>Receiver bank charged and seal key inserted. Vault opened.</span>';current.helpers.setReadout('PASS · VAULT OPEN','passed');}
      else if(result.passed===false){verdict.dataset.result='fail';current.helpers.setReadout('FAIL · ATTEMPT ENDED','error');verdict.querySelector('b').textContent='FAIL';verdict.querySelector('span').textContent=passed?'The optical seal could not be verified.':goalFeedback;}
      else throw new Error('No authoritative grade');
    } catch(error){verdict.dataset.result='error';verdict.querySelector('b').textContent='LINK ERROR';verdict.querySelector('span').textContent='No verified outcome: '+error.message;current.helpers.setReadout('VERIFIER LINK ERROR','error');}
  }
  function animate() {sync();draw();if(!model.terminal)frame=requestAnimationFrame(animate);}
  async function render(state,helpers) {
    cancelAnimationFrame(frame);document.body.dataset.mechanic='rayglass-vault-v2';
    const mode=state.control_condition?.interaction||'full';
    model={state,helpers,mode,createdAt:performance.now(),sim:new Physics(state),events:[],routes:Array(state.channels.length).fill(null),shots:{},last:null,selected:null,sealSelected:false,hold:null,terminal:false};
    window.rayglassVaultV2Model=model;
    helpers.app.innerHTML=`<section class="rayglass-vault-v2" data-interaction="${mode}">
      <header class="rgv-head"><div><small>THE OPTICAL ARCHIVE / LIVE RECEIVER BANK</small><h1>Rayglass Vault V2</h1><p>Charge every receiver, then ${mode==='full'?'drag':'click'} the seal key into AMBER. Ghost marks: 80 / 160 / 240 ms ago.</p><p>Drift ${state.parameters.speed_min}–${state.parameters.speed_max} px/s · rail ±${state.optics.rail_half_span} px · opening ${state.optics.receiver_width} × ${state.parameters.receiver_height} px · key radius ${state.optics.seal_key_radius} px</p></div><div class="rgv-seal">◈<span>PROBE<br>TRACK<br>SEAL</span></div></header>
      <main class="rgv-work"><section class="rgv-source"><div class="rgv-caption">DARK GLASS / ${state.parameters.size} × ${state.parameters.size}<span>PORTS ${state.parameters.size*4}</span></div>
        <canvas id="rgv-cabinet" width="340" height="430" aria-label="Opaque cabinet ports and colored lamp sockets"></canvas>
        <div id="rgv-reading">PROBE A BORDER PORT · H absorbed · R reflected</div>
        <div class="rgv-patch-hint">${mode==='full'?'Drag a lamp plug onto an inlet port.':'Click a lamp, then its inlet port.'} Each lamp must reach its numbered EXIT.</div>
      </section><section class="rgv-bank"><div class="rgv-caption">REFLECTED LIGHT / ${state.channels.length} RECEIVERS<span>${mode==='full'?'DRAG TRIM HANDLES':'CLICK TRIM RAILS'}</span></div>
        <canvas id="rgv-optics" width="680" height="490" aria-label="Mirror rays, moving receivers, trim rails, optical charge and heat"></canvas>
      </section></main>
      <footer class="rgv-foot"><div class="readout" data-status="idle">PROBE & PATCH BEFORE START · ALL RECEIVERS MUST CHARGE TOGETHER</div><button id="rgv-probe-mode">PROBE MODE</button><button id="rgv-start">START LIGHT →</button><button id="rgv-submit">SEAL VAULT</button></footer>
      <div id="rgv-verdict" hidden></div></section>`;
    const cabinet=document.getElementById('rgv-cabinet'),optics=document.getElementById('rgv-optics');
    cabinet.addEventListener('pointerdown',cabinetDown);cabinet.addEventListener('pointermove',cabinetMove);cabinet.addEventListener('pointerup',cabinetUp);cabinet.addEventListener('pointercancel',cabinetUp);
    optics.addEventListener('pointerdown',opticsDown);optics.addEventListener('pointermove',opticsMove);optics.addEventListener('pointerup',opticsUp);optics.addEventListener('pointercancel',opticsUp);
    document.getElementById('rgv-probe-mode').onclick=()=>{if(model.terminal||model.sim.started||model.mode!=='simplified')return;sync();if(model.terminal)return;model.selected=null;record('clear_selection',{input_surface:'patch_click'});draw();};
    document.getElementById('rgv-start').onclick=()=>{
      if(model.terminal||model.sim.started||model.hold||model.routes.some(r=>r===null))return;
      sync();if(model.terminal)return;record('start',{input_surface:'start_button'});model.sim.started=true;
      if(model.routes.some((r,i)=>state.sensor_responses[r]!==state.channels[i].exit_port)){model.sim.failed='An optical cable feeds the wrong exit.';finish();}
      else helpers.setReadout('KEEP EVERY BEAM INSIDE ITS MOVING RECEIVER','idle');draw();
    };
    document.getElementById('rgv-submit').onclick=()=>{sync();finish();};
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.rayglass_vault_v2={rootSelector:'.rayglass-vault-v2',render};
})();
