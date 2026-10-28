(() => {
  'use strict';
  let model, frame=0, keyHandler=null;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const clone=v=>JSON.parse(JSON.stringify(v));
  function noise(seed,index) {
    let x=(seed ^ Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function position(p,ms,world) {
    const u=Math.max(0,ms+p.motion_offset_ms)/p.span_ms,i=Math.floor(u),f=u-i;
    const a=noise(p.motion_seed,i),b=noise(p.motion_seed,i+1),blend=f*f*(3-2*f);
    return [480+world.lanes[p.lane].direction*p.speed*(ms-p.arrival_ms)/1000,p.base_y+p.drift*(a+(b-a)*blend)];
  }
  function initial(world) {
    return {tick:0,started:false,status:'ready',failure:'',resolved:[],caught:[],blocked:[],
      pumps:world.lanes.map(l=>({y:l.initial_y,target:l.initial_y,velocity:0,open:false,atp:l.atp,stroke_start:null,stroke_target:l.initial_y})),hold:null};
  }
  function advance(sim,world,end) {
    const p=world.parameters;
    while (sim.tick<end && sim.status==='running') {
      sim.tick++; const ms=sim.tick*10;
      world.lanes.forEach((lane,index)=>{
        const pump=sim.pumps[index],half=p.aperture/2;
        if (pump.stroke_start!==null) {
          const elapsed=ms-pump.stroke_start;
          pump.open=elapsed>=p.stroke_arm_ms && elapsed<p.stroke_arm_ms+p.stroke_open_ms;
          if(elapsed>=p.stroke_arm_ms+p.stroke_open_ms+p.stroke_recovery_ms){pump.stroke_start=null;pump.open=false;}
        }
        const drive=pump.stroke_start===null?pump.target:pump.stroke_target,acc=(drive-pump.y)*p.spring-pump.velocity*p.damping;
        pump.velocity=clamp(pump.velocity+acc*.01,-p.pump_speed,p.pump_speed);
        pump.y=clamp(pump.y+pump.velocity*.01,lane.low+half,lane.high-half);
        if (pump.y===lane.low+half || pump.y===lane.high-half) pump.velocity=0;
      });
      for (const ion of world.particles) {
        if (sim.resolved.includes(ion.id) || ms<ion.arrival_ms) continue;
        const pump=sim.pumps[ion.lane],contact=pump.y-pump.velocity*(ms-ion.arrival_ms)/1000;
        const ionY=position(ion,ion.arrival_ms,world)[1];
        const opened=pump.stroke_start!==null && ion.arrival_ms-pump.stroke_start>=p.stroke_arm_ms && ion.arrival_ms-pump.stroke_start<p.stroke_arm_ms+p.stroke_open_ms;
        const enters=opened && Math.abs(ionY-contact)+ion.radius<=p.aperture/2+1e-7;
        sim.resolved.push(ion.id);
        if (enters && ion.kind==='inhibitor') {sim.status='failed';sim.failure='An inhibitor entered the cell.';break;}
        if (ion.kind==='nutrient') {
          if (!enters) {sim.status='failed';sim.failure='A required solute was lost at the membrane.';break;}
          sim.caught.push(ion.id);
        } else sim.blocked.push(ion.id);
      }
      if (sim.status==='running' && sim.resolved.length===world.particles.length) sim.status='complete';
    }
  }
  // Exposed solely for deterministic implementation tests and disclosed oracle
  // reads. Task controls never call an internal success or state-injection API.
  window.CellGatekeeperV2Physics={noise,position,initial,advance};
  function record(kind,data={}) {
    const timing=kind==='stroke'?{at_ms:model.sim.started?Math.round((performance.now()-model.start)*1000)/1000:0}:{};
    model.events.push({sequence:model.events.length+1,kind,tick:model.sim.tick,...timing,...data});
  }
  function sync() {
    if (!model || model.terminal || !model.sim.started) return;
    advance(model.sim,model.world,Math.min(Math.ceil(model.world.duration_ms/10),Math.floor((performance.now()-model.start)/10+1e-8)));
    if (model.sim.status==='complete' || model.sim.status==='failed') {
      // A pointer capture is a control affordance, not a stop-world control.
      // Finishing while held requires the normal release before certification.
      if (model.sim.hold===null || model.sim.status==='failed') finish();
    }
  }
  function start() {
    if (model.terminal || model.sim.started) return;
    record('start',{input_source:'start_button'});
    model.sim.started=true;model.sim.status='running';model.start=performance.now();
    document.querySelector('[data-start]').disabled=true;
    model.helpers.setReadout('FLOW ACTIVE · ALIGN SOLUTES AND EXCLUDE INHIBITORS','active');
    paint();
  }
  function stroke(index,source) {
    sync();if (model.terminal || !['ready','running'].includes(model.sim.status)) return;
    record('stroke',{lane:index,input_source:source});const p=model.sim.pumps[index];
    if(model.sim.started && p.stroke_start===null && p.atp>0){p.stroke_start=model.events[model.events.length-1].at_ms;p.stroke_target=p.target;p.open=false;p.atp--;}paint();
  }
  function point(event) {
    const rect=document.querySelector('.cgv2-canvas').getBoundingClientRect();
    return [Math.round(clamp((event.clientX-rect.left)*960/rect.width,0,960)*1000)/1000,
      Math.round(clamp((event.clientY-rect.top)*450/rect.height,0,450)*1000)/1000];
  }
  function target(index,pt,kind) {
    const lane=model.world.lanes[index],pump=model.sim.pumps[index],half=model.world.parameters.aperture/2;
    record(kind,{lane:index,point:pt,input_source:kind==='target'?'rail_click':'pump_drag'});
    pump.target=clamp(pt[1],lane.low+half,lane.high-half);
    if (!model.sim.started) {pump.y=pump.target;pump.velocity=0;}
  }
  function pointerDown(event) {
    if (event.button!==0) return;sync();if (model.terminal || !['ready','running'].includes(model.sim.status)) return;
    const pt=point(event),half=model.world.parameters.aperture/2;
    if (model.mode==='simplified') {
      const lane=model.world.lanes.find(l=>pt[0]>=519 && pt[0]<=549 && pt[1]>=l.low && pt[1]<=l.high);
      if (lane) target(lane.id,pt,'target');
    } else {
      const lane=model.world.lanes.find(l=>Math.abs(pt[0]-480)<=27 && Math.abs(pt[1]-model.sim.pumps[l.id].y)<=half+8);
      if (lane && model.sim.hold===null) {
        model.sim.hold=lane.id;model.pointer=event.pointerId;event.currentTarget.setPointerCapture(event.pointerId);
        record('drag_start',{lane:lane.id,point:pt,input_source:'pump_drag'});
      }
    }
    event.preventDefault();paint();
  }
  function pointerMove(event) {
    if (model.mode!=='full' || model.sim.hold===null || event.pointerId!==model.pointer) return;
    sync();if (model.terminal || model.sim.status!=='ready' && model.sim.status!=='running') return;
    target(model.sim.hold,point(event),'drag_move');event.preventDefault();paint();
  }
  function pointerUp(event) {
    if (model.mode!=='full' || model.sim.hold===null || event.pointerId!==model.pointer || model.terminal) return;
    sync();if (model.terminal) return;
    const lane=model.sim.hold;
    record('drag_end',{lane,point:point(event),input_source:'pump_drag'});model.sim.hold=null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    model.pointer=null;paint();sync();
  }
  function payload() {
    return {mechanic_id:model.world.mechanic_id,revision:model.world.revision,task_id:model.world.task_id,
      challenge_id:model.world.challenge_id,interaction_mode:model.mode,events:clone(model.events),final_tick:model.sim.tick,
      completed:model.sim.status==='complete',final_state:clone(model.sim)};
  }
  async function finish(manual=false) {
    if (model.terminal) return;
    if (manual) {
      sync();if (model.terminal) return;
      if (model.sim.status!=='complete') {model.sim.status='failed';model.sim.failure='Transfer certified before completion.';}
    }
    record('certify',{input_source:'certify_button'});model.terminal=true;
    model.lastPayload=payload();paint();
    const current=model;
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(current.lastPayload)});
      const decision=await response.json();current.decision=decision;
      current.helpers.setReadout(decision.passed?'PASS · SELECTIVE TRANSFER VERIFIED':`FAIL · ${current.sim.failure || decision.feedback || 'TRANSFER ENDED'}`,decision.passed?'passed':'error');
    } catch(error) {current.helpers.setReadout('VERIFICATION UNAVAILABLE','error');current.verificationError=String(error);}
    if (model===current) paint();
  }
  function shape(ctx,x,y,r,kind) {
    ctx.beginPath();
    if (kind==='circle') ctx.arc(x,y,r,0,Math.PI*2);
    else {
      const n=kind==='diamond'?4:6;
      for (let i=0;i<n;i++) {const a=-Math.PI/2+i*Math.PI*2/n;const px=x+Math.cos(a)*r,py=y+Math.sin(a)*r;i?ctx.lineTo(px,py):ctx.moveTo(px,py);}
      ctx.closePath();
    }
  }
  function paint() {
    if (!model) return;
    const canvas=document.querySelector('.cgv2-canvas'),ctx=canvas.getContext('2d'),w=model.world,sim=model.sim,ms=sim.tick*10;
    ctx.fillStyle='#091d2a';ctx.fillRect(0,0,960,450);
    const sea=ctx.createLinearGradient(0,0,960,0);sea.addColorStop(0,'#103347');sea.addColorStop(.48,'#0b202b');sea.addColorStop(1,'#182f35');ctx.fillStyle=sea;ctx.fillRect(12,10,936,420);
    for (const lane of w.lanes) {
      const pump=sim.pumps[lane.id],half=w.parameters.aperture/2;
      ctx.strokeStyle='#315765';ctx.lineWidth=1;ctx.strokeRect(12,lane.low,936,140);
      ctx.fillStyle=lane.color;ctx.font='bold 13px ui-monospace, monospace';ctx.textAlign='left';
      ctx.fillText(`${lane.label}   ${lane.direction===1?'OUTSIDE → INSIDE':'OUTSIDE ← INSIDE'}`,26,lane.low+18);
      // Phospholipid bilayer, with the pump's physical aperture cut from it.
      ctx.fillStyle='#b79966';ctx.fillRect(467,lane.low,26,140);
      for (let y=lane.low+5;y<lane.high;y+=11) {ctx.fillStyle='#efd49a';ctx.beginPath();ctx.arc(465,y,4,0,Math.PI*2);ctx.arc(495,y,4,0,Math.PI*2);ctx.fill();}
      ctx.fillStyle=pump.open?'#143f40':'#486068';ctx.fillRect(457,pump.y-half,46,half*2);
      ctx.strokeStyle=pump.open?lane.color:'#80969a';ctx.lineWidth=3;ctx.strokeRect(457,pump.y-half-7,46,half*2+14);
      if (!pump.open) {ctx.strokeStyle='#a4bac0';ctx.lineWidth=3;for(let y=pump.y-half+3;y<pump.y+half;y+=8){ctx.beginPath();ctx.moveTo(459,y);ctx.lineTo(501,y+5);ctx.stroke();}}
      ctx.strokeStyle=lane.color;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(457,pump.y-half);ctx.lineTo(503,pump.y-half);ctx.moveTo(457,pump.y+half);ctx.lineTo(503,pump.y+half);ctx.stroke();
      ctx.strokeStyle=model.mode==='simplified'?'#9cb6bc':'#476671';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(534,lane.low);ctx.lineTo(534,lane.high);ctx.stroke();
      ctx.fillStyle=lane.color;ctx.beginPath();ctx.moveTo(546,pump.target);ctx.lineTo(553,pump.target-6);ctx.lineTo(553,pump.target+6);ctx.closePath();ctx.fill();
      ctx.fillStyle='#bed1cd';ctx.font='11px ui-monospace,monospace';ctx.fillText(model.mode==='simplified'?'CLICK RAIL':'DRAG PUMP',565,lane.low+18);
    }
    for (const ion of w.particles) {
      const lane=w.lanes[ion.lane],resolved=sim.resolved.includes(ion.id),caught=sim.caught.includes(ion.id),blocked=sim.blocked.includes(ion.id);
      if (resolved && !caught && !blocked && sim.status!=='failed') continue;
      let pos=position(ion,ms,w);
      if (blocked) pos=[480-lane.direction*ion.speed*(ms-ion.arrival_ms)/1000,position(ion,ion.arrival_ms,w)[1]];
      if (resolved && !caught && !blocked) pos=position(ion,ion.arrival_ms,w);
      if (pos[0]<24 || pos[0]>936) continue;
      ctx.strokeStyle=ion.kind==='nutrient'?lane.color:'#ff78be';ctx.lineWidth=2;ctx.globalAlpha=resolved?.45:.72;
      ctx.beginPath();
      for (let dt=600;dt>=0;dt-=60) {const q=position(ion,Math.max(0,ms-dt),w);dt===600?ctx.moveTo(q[0],q[1]):ctx.lineTo(q[0],q[1]);}
      if (!resolved) ctx.stroke();ctx.globalAlpha=1;
      shape(ctx,pos[0],pos[1],ion.radius,ion.kind==='inhibitor'?'hexagon':lane.shape);
      ctx.fillStyle=ion.kind==='nutrient'?lane.color:'#112b38';ctx.fill();ctx.lineWidth=ion.kind==='inhibitor'?3:2;ctx.stroke();
      if (ion.kind==='nutrient') {ctx.fillStyle='#eafff7';ctx.beginPath();ctx.arc(pos[0]-3,pos[1]-3,2,0,Math.PI*2);ctx.fill();}
      else {ctx.strokeStyle='#ff78be';ctx.beginPath();ctx.moveTo(pos[0]-4,pos[1]-4);ctx.lineTo(pos[0]+4,pos[1]+4);ctx.moveTo(pos[0]+4,pos[1]-4);ctx.lineTo(pos[0]-4,pos[1]+4);ctx.stroke();}
    }
    w.lanes.forEach(l=>{
      const p=sim.pumps[l.id],card=document.querySelector(`[data-lane="${l.id}"]`);
      const count=sim.caught.filter(id=>w.particles.find(i=>i.id===id).lane===l.id).length;
      card.querySelector('.cgv2-count').textContent=`${count} / ${l.goal}`;
      card.querySelector('.cgv2-fuel').textContent=`ATP ${p.atp}`;
      const elapsed=p.stroke_start===null?null:ms-p.stroke_start;
      const phase=elapsed===null?'READY':elapsed<w.parameters.stroke_arm_ms?'EXTENDING':p.open?'TRANSFERRING':'RECOVERING';
      card.querySelector('.cgv2-gate').textContent=phase;card.dataset.open=String(p.open);
      const button=card.querySelector('[data-toggle]');if(button){button.textContent=elapsed===null?'FIRE · 1 ATP':phase;button.disabled=!sim.started || model.terminal || elapsed!==null || p.atp===0;}
      if(elapsed!==null){
        ctx.strokeStyle='#ffe3a0';ctx.lineWidth=3;ctx.strokeRect(451,p.stroke_target-w.parameters.aperture/2-12,58,w.parameters.aperture+24);
        const fraction=Math.min(1,elapsed/(w.parameters.stroke_arm_ms+w.parameters.stroke_open_ms+w.parameters.stroke_recovery_ms));
        ctx.fillStyle='#ffe3a0';ctx.fillRect(457,p.y+w.parameters.aperture/2+11,46*fraction,4);
        ctx.fillStyle='#ffe3a0';ctx.font='10px ui-monospace,monospace';ctx.fillText('COMMITTED',565,l.low+34);
      }
    });
    const phase=document.querySelector('.cgv2-phase');phase.textContent=sim.status==='ready'?'READY TO PERFUSE':sim.status==='running'?'PERFUSION ACTIVE':sim.status==='complete'?'TRANSFER COMPLETE':'TRANSFER LOST';
    const stamp=document.querySelector('.cgv2-verdict');
    if (model.terminal) {
      const rejected=sim.status==='failed' || model.decision?.passed===false;
      stamp.hidden=false;stamp.dataset.outcome=rejected?'failed':sim.status;
      stamp.innerHTML=`<strong>${rejected?'FAIL':model.decision?.passed?'PASS':'VERIFYING'}</strong><span>${sim.failure || (rejected?'Transfer verification failed.':'All solutes delivered. Inhibitors excluded.')}</span>`;
    }
    document.querySelector('[data-start]').disabled=model.terminal || sim.started;
    document.querySelector('[data-certify]').disabled=model.terminal;
  }
  function animate(){sync();paint();if(!model.terminal)frame=requestAnimationFrame(animate);}
  function render(world,helpers) {
    cancelAnimationFrame(frame);if(keyHandler)window.removeEventListener('keydown',keyHandler);
    const mode=world.control_condition?.interaction || 'full';
    model={world,helpers,mode,sim:initial(world),events:[],terminal:false,start:0,pointer:null,decision:null};
    window.cellGatekeeperV2Model=model;document.body.dataset.mechanic='cell-gatekeeper-v2';
    helpers.app.innerHTML=`<section class="cgv2" data-interaction="${mode}"><header class="cgv2-head"><div><p>MEMBRANE LAB / SELECTIVE TRANSPORT</p><h1>Cell Gatekeeper V2</h1></div><span class="cgv2-phase">READY TO PERFUSE</span></header><div class="cgv2-rules"><b>Transfer every solid solute. Exclude hollow magenta inhibitors.</b><span>${mode==='full'?'Drag a pump up or down. Keys 1–3 fire the matching ATP stroke.':'Click a vertical rail to move its pump. Use FIRE to power its ATP stroke.'} Each stroke spends 1 ATP, locks the selected height, extends for 0.4s, then opens briefly. Steering during a stroke queues the next height; flow continues.</span></div><main class="cgv2-main"><div class="cgv2-chamber"><canvas class="cgv2-canvas" width="960" height="450"></canvas><div class="cgv2-legend"><span><i class="solid"></i> SOLUTE</span><span><i class="hollow"></i> INHIBITOR</span><span>TRAILS 0.6s · OPEN ${world.parameters.stroke_open_ms/1000}s · RECOVERY 0.3s</span></div><div class="cgv2-verdict" hidden></div></div><aside>${world.lanes.map(l=>`<article data-lane="${l.id}" style="--ion:${l.color}"><div class="cgv2-species"><span>${l.label}</span><small>${l.direction===1?'IMPORT':'EXPORT'}</small></div><div class="cgv2-count">0 / 4</div><p>SELECTIVE TRANSFERS</p><div class="cgv2-resources"><span class="cgv2-fuel">ATP 4</span><b class="cgv2-gate">CLOSED</b></div>${mode==='simplified'?`<button data-toggle="${l.id}">FIRE · 1 ATP</button>`:`<div class="cgv2-key"><kbd>${l.id+1}</kbd> FIRE · 1 ATP</div>`}</article>`).join('')}<div class="cgv2-note">Four ATP strokes per pump. A stroke cannot be cancelled. A lost solute, admitted inhibitor or early certification ends the episode.<br>Inspect first; start when ready.</div></aside></main><footer><div class="readout">READY</div><button data-start>START PERFUSION</button><button data-certify>CERTIFY TRANSFER</button></footer></section>`;
    const canvas=document.querySelector('.cgv2-canvas');canvas.addEventListener('pointerdown',pointerDown);canvas.addEventListener('pointermove',pointerMove);
    for (const event of ['pointerup','pointercancel','lostpointercapture']) canvas.addEventListener(event,pointerUp);
    document.querySelector('[data-start]').addEventListener('click',start);document.querySelector('[data-certify]').addEventListener('click',()=>finish(true));
    document.querySelectorAll('[data-toggle]').forEach(b=>b.addEventListener('click',()=>stroke(Number(b.dataset.toggle),'pump_button')));
    keyHandler=event=>{const i=Number(event.key)-1;if(mode==='full'&&!event.repeat&&Number.isInteger(i)&&i>=0&&i<world.lanes.length){event.preventDefault();stroke(i,'pump_key');}};
    window.addEventListener('keydown',keyHandler);helpers.setReadout('READY · INSPECT THEN START','idle');paint();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.cell_gatekeeper_v2={rootSelector:'.cgv2',render};
})();
