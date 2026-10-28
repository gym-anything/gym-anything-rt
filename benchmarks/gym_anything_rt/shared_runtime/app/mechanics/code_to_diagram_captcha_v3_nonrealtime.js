(() => {
  'use strict';
  const ID = 'code_to_diagram_captcha_v3_nonrealtime';
  const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  const distance = (a,b) => Math.hypot(a[0]-b[0],a[1]-b[1]);
  const esc = x => String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  let model, frame = 0;

  function noise(seed,index) {
    let n = (seed ^ Math.imul(index+1,0x9E3779B9)) >>> 0;
    n = Math.imul(n ^ (n >>> 16),0x85EBCA6B) >>> 0;
    n = Math.imul(n ^ (n >>> 13),0xC2B2AE35) >>> 0;
    return ((n ^ (n >>> 16)) >>> 0)/4294967295;
  }
  function nodePosition(c,node,ms) {
    const s=c.physics, u=(Math.max(0,ms)+node.phase_ms)/s.motion_span_ms;
    const index=Math.floor(u), fraction=u%1, blend=fraction*fraction*(3-2*fraction);
    const offset = axis => {
      const knot = i => node.motion_knots[i][axis];
      return knot(index)+(knot(index+1)-knot(index))*blend;
    };
    return [node.center[0]+s.amplitude_x*offset(0),node.center[1]+s.amplitude_y*offset(1)];
  }
  function motionPreview(c,node,ms) {
    const s=c.physics,span=s.motion_span_ms,u=(Math.max(0,ms)+node.phase_ms)/span,index=Math.floor(u);
    const knots=[index,index+1,index+2].map(i=>[0,1].map(axis=>node.center[axis]+
      [s.amplitude_x,s.amplitude_y][axis]*node.motion_knots[i][axis]));
    return {knots,remaining_ms:(1-u%1)*span,span_ms:span};
  }
  function weldPosition(c,node,ms) {
    const p=nodePosition(c,node,ms);return [p[0]+c.physics.weld_offset,p[1]];
  }
  function successor(c,p) {
    const n=c.nodes.find(n=>n.id===p.node);
    if(n.kind==='exit')return null;
    if(n.kind==='branch')return (n.predicate==='equal' ? p.sun===p.diamond : p[n.predicate]) ? n.yes : n.no;
    if(n.feedback && p.repeat)return c.first_gate;
    return n.next;
  }
  class FlowPhysics {
    constructor(c) {
      this.contract=c;this.s=c.physics;this.tick=0;this.running=false;this.failed='';this.won=false;
      this.time_ms=0;this.completed_at_ms=null;
      this.streams=c.streams.map(p=>({...structuredClone(p),node:c.entry_id,tip:[...p.home],velocity:[0,0],
        target:[...p.home],candidate:null,charge:0,armed:false,ready_tick:0,done:false,visits:[]}));
      this.byNode=Object.fromEntries(c.nodes.map(n=>[n.id,n]));
    }
    start() {if(this.running || this.failed || this.won)return;this.running=true;}
    advance(end) {this.advanceTime(end*10);}
    advanceTime(endMs) {
      if(!Number.isFinite(endMs) || endMs<this.time_ms)throw Error('time must be finite and nondecreasing');
      if(!this.running)return;
      while((this.tick+1)*10<=endMs && !this.failed && !this.won) {
        this.tick++;const s=this.s,ms=this.tick*10;
        this.time_ms=ms;
        const positions=Object.fromEntries(this.contract.nodes.map(n=>[n.id,nodePosition(this.contract,n,ms)]));
        for(const p of this.streams) {
          if(p.done)continue;
          for(let i=0;i<2;i++) {
            const a=clamp((p.target[i]-p.tip[i])*s.spring-p.velocity[i]*s.damping,-s.tip_acceleration,s.tip_acceleration);
            p.velocity[i]=clamp(p.velocity[i]+a*.01,-s.tip_speed,s.tip_speed);
            p.tip[i]=clamp(p.tip[i]+p.velocity[i]*.01,s.tip_radius,s.field[i]-s.tip_radius);
          }
          if(this.tick<p.ready_tick)continue;
          if(ms-p.ready_tick*10>s.buffer_ms) {this.failed=`${p.id} execution buffer overflowed.`;break;}
          if(p.armed)continue;
          const hits=Object.entries(positions).map(([id,xy])=>[distance(p.tip,xy),id])
            .filter(([d,id])=>id!==p.node && d+s.tip_radius<=s.contact_radius+1e-9)
            .sort((a,b)=>a[0]-b[0] || a[1].localeCompare(b[1]));
          const hit=hits.length ? hits[0][1] : null;
          if(hit===null) {
            p.charge=Math.max(0,p.charge-10*s.charge_decay);if(!p.charge)p.candidate=null;
          } else {
            if(p.candidate!==hit) {p.candidate=hit;p.charge=0;}
            p.charge+=10;
            if(p.charge>=s.charge_ms) {
              if(hit!==successor(this.contract,p)) {this.failed=`${p.id} committed an invalid edge ${p.node} → ${hit}.`;break;}
              p.charge=s.charge_ms;p.armed=true;
            }
          }
        }
        this.won=this.streams.every(p=>p.done) && !this.failed;
        if(ms>=s.session_ms && !this.won && !this.failed)this.failed='The live program was not completed.';
      }
      if(!this.failed && !this.won)this.time_ms=endMs;
    }
    pulse(p,point) {
      if(!this.running || this.failed || this.won || p.done || !p.armed)throw Error('weld requires an armed active probe');
      const hit=successor(this.contract,p),xy=weldPosition(this.contract,this.byNode[hit],this.time_ms);
      if(distance(point,xy)+this.s.weld_tip_radius>this.s.weld_radius+1e-9) {
        this.failed=`${p.id} weld missed ${hit}; the live wire shorted.`;return;
      }
      const arrival=this.byNode[hit],departure=this.byNode[p.node];
      p.visits.push({tick:this.tick,time_ms:this.time_ms,source:p.node,destination:hit,sun:p.sun,diamond:p.diamond,repeat:p.repeat});
      if(departure.feedback && p.repeat)p.repeat--;
      p.node=hit;p.candidate=null;p.charge=0;p.armed=false;
      if(arrival.operation)p[arrival.operation]=!p[arrival.operation];
      p.done=arrival.kind==='exit';p.ready_tick=Math.ceil((this.time_ms+this.s.process_ms)/10);
      this.won=this.streams.every(p=>p.done) && !this.failed;
      if(this.won)this.completed_at_ms=this.time_ms;
    }
    snapshot() {return structuredClone({tick:this.tick,time_ms:this.time_ms,completed_at_ms:this.completed_at_ms,
      running:this.running,failed:this.failed,won:this.won,streams:this.streams});}
  }
  // Implementation diagnostics are privileged evidence, never a player control.
  window.LiveFlowV3={noise,nodePosition,motionPreview,weldPosition,successor,FlowPhysics};
  const record=(kind,details={})=>model.events.push({sequence:model.events.length+1,tick:model.physics.tick,time_ms:model.physics.time_ms,kind,...details});
  function actionStep() {
    if(model.submitted || !model.physics.running || model.physics.failed || model.physics.won)return;
    const step=Number(model.state.physics.action_step_ms);
    if(!Number.isInteger(step) || step<=0 || step%10)throw Error('invalid input-step timing contract');
    model.physics.advanceTime(Math.min(model.state.physics.session_ms,model.physics.time_ms+step));
  }
  function point(event) {
    const r=document.querySelector('.lfv-field').getBoundingClientRect();
    return [clamp((event.clientX-r.left)*880/r.width,0,880),clamp((event.clientY-r.top)*470/r.height,0,470)]
      .map(v=>Math.round(v*1000)/1000);
  }
  function down(event) {
    if(event.button!==0 || model.submitted || !model.physics.running)return;
    if(model.submitted || model.physics.won)return;
    const xy=point(event);
    if(model.mode==='simplified') {
      const p=model.physics.streams.find(p=>p.id===model.selected);
      if(!p || p.done)return;
      if(model.weldMode) {model.physics.pulse(p,xy);model.weldMode=false;actionStep();record('pulse',{stream_id:p.id,point:xy,input_source:'probe_click'});}
      else {if(!p.armed)p.target=xy;actionStep();record('target',{stream_id:p.id,point:xy,input_source:'probe_click'});}
    } else if(!model.hold) {
      const p=model.physics.streams.filter(p=>!p.done && distance(p.tip,xy)<=model.state.physics.tip_radius+6)
        .sort((a,b)=>distance(a.tip,xy)-distance(b.tip,xy))[0];
      if(!p)return;
      const tool=p.armed?'weld':'heat';
      model.hold={stream:p.id,pointer:event.pointerId,aim:xy,tool};
      event.currentTarget.setPointerCapture(event.pointerId);
      actionStep();
      record('grab',{stream_id:p.id,point:xy,tool,input_source:'probe_drag'});
    }
    if(model.physics.failed)finish(true);
    event.preventDefault();draw();
  }
  function move(event) {
    if(model.submitted)return;
    model.hover=point(event);
    if(model.hold?.pointer!==event.pointerId) {draw();return;}
    if(model.submitted || model.physics.won)return;
    const p=model.physics.streams.find(p=>p.id===model.hold.stream),xy=point(event);
    if(!p.done) {model.hold.aim=xy;if(model.hold.tool==='heat' && !p.armed)p.target=xy;actionStep();record('move',{stream_id:p.id,point:xy,input_source:'probe_drag'});if(model.physics.failed && !model.submitted)finish(true);}
    event.preventDefault();draw();
  }
  function release(event) {
    if(model.hold?.pointer!==event.pointerId)return;
    const hold=model.hold;model.hold=null;
    if(!model.submitted) {
      const p=model.physics.streams.find(p=>p.id===hold.stream),xy=point(event);
      if(hold.tool==='weld') {model.physics.pulse(p,xy);actionStep();record('pulse',{stream_id:p.id,point:xy,input_source:'probe_drag'});}
      else {actionStep();record('release',{stream_id:hold.stream,point:xy,input_source:'probe_drag'});}
    }
    if(event.currentTarget.hasPointerCapture?.(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
    if(model.physics.failed && !model.submitted)finish(true);
    draw();
  }
  function listing(n) {
    if(n.kind==='exit')return 'HALT';
    const revealed=model.inspected.has(n.id);
    if(n.kind==='branch') {
      const predicate={sun:'☀',diamond:'◆',equal:'☀ = ◆'}[n.predicate];
      return revealed ? `if ${predicate} → ${n.yes}<br><span>else → ${n.no}</span>` :
        `if ${predicate}<br><span>dispatch targets concealed</span>`;
    }
    const toggle=n.operation ? `flip ${n.operation==='sun'?'☀':'◆'}; ` : '';
    if(!revealed)return toggle+'<span>dispatch target concealed</span>';
    const loop=n.feedback ? `if ↺: consume ↺, → ${model.state.first_gate}<br><span>else → ${n.next}</span>` : `→ ${n.next}`;
    return toggle+loop;
  }
  function draw() {
    if(!model)return;
    const canvas=document.querySelector('.lfv-field'),ctx=canvas?.getContext('2d');if(!ctx)return;
    const sim=model.physics,s=model.state.physics,ms=sim.time_ms;
    ctx.fillStyle='#101e27';ctx.fillRect(0,0,880,470);
    ctx.strokeStyle='#243843';ctx.lineWidth=1;
    for(let x=0;x<880;x+=20) {ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,470);ctx.stroke();}
    for(let y=0;y<470;y+=20) {ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(880,y);ctx.stroke();}
    const positions=Object.fromEntries(model.state.nodes.map(n=>[n.id,nodePosition(model.state,n,ms)]));
    // Only inspected dispatches expose outgoing topology. Drawing concealed
    // edges here would reveal the very information the debugger must discover.
    for(const n of model.state.nodes) {
      if(!model.inspected.has(n.id))continue;
      for(const next of [n.next,n.yes,n.no,n.feedback ? model.state.first_gate : null].filter(Boolean)) {
        const a=positions[n.id],b=positions[next];
        ctx.strokeStyle='#d9e4e511';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();
        const f=.61,x=a[0]+(b[0]-a[0])*f,y=a[1]+(b[1]-a[1])*f,angle=Math.atan2(b[1]-a[1],b[0]-a[0]);
        ctx.beginPath();ctx.moveTo(x-8*Math.cos(angle-.5),y-8*Math.sin(angle-.5));ctx.lineTo(x,y);
        ctx.lineTo(x-8*Math.cos(angle+.5),y-8*Math.sin(angle+.5));ctx.stroke();
      }
    }
    for(const n of model.state.nodes) {
      const xy=positions[n.id];
      // Every contact announces its current and next segment. The preview is
      // always at least one full segment ahead, including at a motion knot.
      const preview=motionPreview(model.state,n,ms);
      ctx.strokeStyle='#78b6d077';ctx.lineWidth=1;ctx.setLineDash([4,4]);
      ctx.beginPath();ctx.moveTo(...preview.knots[0]);ctx.lineTo(...preview.knots[1]);ctx.lineTo(...preview.knots[2]);ctx.stroke();ctx.setLineDash([]);
      preview.knots.forEach((p,i)=>{ctx.strokeStyle=i===1?'#a3e2ef':'#7898aa';ctx.lineWidth=1.5;
        ctx.strokeRect(p[0]-3,p[1]-3,6,6);});
      ctx.font='10px ui-monospace';ctx.textAlign='center';ctx.fillStyle='#b8d6e3';
      ctx.fillText(`${(preview.remaining_ms/1000).toFixed(2)}s → ${(preview.span_ms/1000).toFixed(1)}s`,n.center[0],n.center[1]+s.amplitude_y+19);
      ctx.beginPath();
      for(let age=650;age>=0;age-=65) {
        const p=nodePosition(model.state,n,Math.max(0,ms-age));if(age===650)ctx.moveTo(...p);else ctx.lineTo(...p);
      }
      ctx.strokeStyle='#a4b5c766';ctx.lineWidth=3;ctx.stroke();
      ctx.fillStyle='#152b38';ctx.strokeStyle=n.kind==='branch'?'#f3b75e':n.kind==='exit'?'#90ead5':'#88aabd';
      ctx.lineWidth=2;ctx.beginPath();ctx.arc(...xy,s.contact_radius,0,Math.PI*2);ctx.fill();ctx.stroke();
      // The inner line is the exact allowed tip-center locus: outer contact
      // radius minus the rendered probe radius. Whole-tip containment is graded.
      ctx.setLineDash([2,4]);ctx.strokeStyle='#88aabd44';ctx.beginPath();ctx.arc(...xy,s.contact_radius-s.tip_radius,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);
      ctx.font='bold 14px ui-monospace, monospace';ctx.textAlign='center';ctx.fillStyle='#eff5e8';
      ctx.fillText(n.id,xy[0],xy[1]-s.contact_radius-9);
      ctx.font='13px sans-serif';ctx.fillStyle='#a4b8c5';ctx.fillText(n.kind==='branch'?'◇':n.kind==='exit'?'■':'→',xy[0],xy[1]+4);
      const socket=weldPosition(model.state,n,ms);
      ctx.strokeStyle='#89e9de';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(xy[0]+s.contact_radius-2,xy[1]);ctx.lineTo(socket[0],socket[1]);ctx.stroke();
      ctx.fillStyle='#152f35';ctx.beginPath();ctx.arc(...socket,s.weld_radius,0,Math.PI*2);ctx.fill();ctx.stroke();
      ctx.setLineDash([2,3]);ctx.strokeStyle='#aafdf077';ctx.beginPath();ctx.arc(...socket,s.weld_radius-s.weld_tip_radius,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);
      ctx.fillStyle='#b4f3e8';ctx.font='11px sans-serif';ctx.fillText('⚡',socket[0],socket[1]+4);
      const annotation=document.querySelector(`[data-motion="${n.id}"]`);
      annotation.textContent=`${(preview.remaining_ms/1000).toFixed(2)}s → (${preview.knots[1].map(v=>v.toFixed(1)).join(',')}) → (${preview.knots[2].map(v=>v.toFixed(1)).join(',')})`;
    }
    for(const p of sim.streams) {
      if(p.done)continue;
      const a=positions[p.node];ctx.strokeStyle=p.color;ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(...a);ctx.bezierCurveTo(a[0]-35,a[1]-25,p.tip[0]-35,p.tip[1]+25,...p.tip);ctx.stroke();
      ctx.setLineDash([3,6]);ctx.globalAlpha=.4;ctx.beginPath();ctx.moveTo(...p.tip);ctx.lineTo(...p.target);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;
      ctx.strokeStyle=p.color;ctx.fillStyle='#101e27';ctx.lineWidth=3;
      ctx.beginPath();ctx.arc(...p.tip,s.tip_radius,0,Math.PI*2);ctx.fill();ctx.stroke();
      ctx.font='bold 11px ui-monospace';ctx.textAlign='center';ctx.fillStyle=p.color;ctx.fillText(p.id,p.tip[0],p.tip[1]+4);
      ctx.strokeStyle=p.color;ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(...p.tip);
      ctx.lineTo(p.tip[0]+p.velocity[0]*.12,p.tip[1]+p.velocity[1]*.12);ctx.stroke();
      if(p.armed) {
        ctx.lineWidth=2;ctx.beginPath();ctx.arc(...p.tip,s.tip_radius+5,0,Math.PI*2);ctx.stroke();
        if((model.hold?.stream===p.id && model.hold.tool==='weld') || (model.mode==='simplified' && model.weldMode && model.selected===p.id && model.hover)) {
          const aim=model.hold?.stream===p.id?model.hold.aim:model.hover;ctx.setLineDash([6,4]);ctx.beginPath();ctx.moveTo(...p.tip);ctx.lineTo(...aim);ctx.stroke();ctx.setLineDash([]);
          // A weld is a 6 px solder spot; its whole circle must fit the socket.
          ctx.beginPath();ctx.arc(...aim,s.weld_tip_radius,0,Math.PI*2);ctx.stroke();
        }
      }
      if(p.charge) {ctx.lineWidth=5;ctx.beginPath();ctx.arc(...positions[p.candidate],s.contact_radius+4,-Math.PI/2,-Math.PI/2+Math.PI*2*p.charge/s.charge_ms);ctx.stroke();}
    }
    for(const p of sim.streams) {
      const card=document.querySelector(`[data-stream="${p.id}"]`);
      card.classList.toggle('is-selected',model.selected===p.id || model.hold?.stream===p.id);
      card.querySelector('.lfv-flags').textContent=`${p.sun?'☀':'☾'} ${p.diamond?'◆':'○'}${p.repeat?' ↺':''}`;
      card.querySelector('.lfv-current').textContent=p.done?'HALTED':p.armed?`${p.node} · ARMED`:p.node+(sim.tick<p.ready_tick?' · processing':'');
      card.dataset.armed=String(p.armed);
      card.querySelector('.lfv-buffer i').style.width=`${p.done?100:clamp(100*(1-(ms-p.ready_tick*10)/s.buffer_ms),0,100)}%`;
      card.dataset.done=String(p.done);
      // A different probe's full arc can cover this probe's partial arc.
      // Keep each execution's current state independently visible; these are
      // measurements of the drawn probe, not predictions or successor hints.
      card.querySelector('.lfv-heat').textContent=`HEAT ${p.candidate || '—'} ${p.charge}/${s.charge_ms} ms · ready ${Math.max(0,p.ready_tick*10-ms).toFixed(1)} ms`;
      card.querySelector('.lfv-pose').textContent=`tip (${p.tip.map(v=>v.toFixed(3)).join(',')}) · v (${p.velocity.map(v=>v.toFixed(3)).join(',')})`;
      card.querySelector('.lfv-aim').textContent=`aim (${p.target.map(v=>v.toFixed(3)).join(',')}) · buffer ${Math.max(0,s.buffer_ms-(ms-p.ready_tick*10)).toFixed(1)} ms`;
      if(model.mode==='simplified')card.disabled=model.submitted || p.done || !sim.running;
    }
    document.querySelector('.lfv-phase').textContent=model.submitted && !sim.won?(model.state.episode_history_error?'EPISODE HISTORY UNAVAILABLE':'EPISODE ENDED'):sim.won?'ALL EXECUTIONS HALTED':!sim.running?'INSPECTION / SAFE TO READ':'INPUT-STEPPED / CONTACTS HOLD BETWEEN INPUTS';
    document.querySelector('.lfv-run').disabled=sim.running || model.submitted;
    document.querySelector('.lfv-seal').disabled=model.submitted;
    document.querySelectorAll('.lfv-inspect').forEach(button=>button.disabled=model.submitted || sim.won);
    const chosen=sim.streams.find(p=>p.id===model.selected),weld=document.querySelector('.lfv-weld-tool');
    weld.disabled=model.submitted || !chosen?.armed;
    weld.textContent=model.weldMode?'WELD SELECTED ⚡':'SELECT WELD TOOL ⚡';
  }
  async function finish(skipSync=false) {
    if(model.submitted)return;
    void skipSync;
    // Finish while held is ignored; failure always terminates immediately.
    if(model.hold && !model.physics.failed)return;
    model.submitted=true;record('seal',{input_source:'seal_button'});
    model.result={mechanic_id:ID,task_id:model.state.task_id,challenge_id:model.state.challenge_id,revision:model.state.revision,
      interaction_mode:model.mode,events:structuredClone(model.events),final_tick:model.physics.tick,
      final_time_ms:model.physics.time_ms,
      final_state:model.physics.snapshot(),completed:model.physics.won && !model.physics.failed};
    if(!model.result.completed) {
      try {sessionStorage.setItem(model.failureKey,model.physics.failed || 'Incomplete execution certified.');}catch(_){}
    }
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(model.result)});
      model.outcome=await response.json();
      const passed=model.outcome.passed===true;
      if(!passed)try {sessionStorage.setItem(model.failureKey,model.physics.failed || 'The execution was rejected.');}catch(_){}
      document.querySelector('.lfv-lab').dataset.verdict=passed?'pass':'fail';
      document.querySelector('.lfv-verdict').innerHTML=`<strong>${passed?'PASS':'FAIL'}</strong><span>${passed?'Every live control-flow execution halted.':esc(model.physics.failed || 'Execution ended incomplete.')}</span>`;
      model.helpers.setReadout(passed?'PASS · PROGRAM EXECUTED':'FAIL · ATTEMPT ENDED',passed?'passed':'error');
    } catch(error) {
      model.outcome={passed:false,infrastructure_error:String(error)};
      model.helpers.setReadout('VERIFIER UNAVAILABLE · EXECUTION RETAINED','error');
    }
    draw();
  }
  function animate() {draw();frame=requestAnimationFrame(animate);}
  async function render(state,helpers) {
    cancelAnimationFrame(frame);document.body.dataset.mechanic='live-flow-v3-nonrealtime';
    model={state,helpers,physics:new FlowPhysics(state),events:[],mode:state.control_condition.interaction,
      selected:null,weldMode:false,hold:null,inspected:new Set(),submitted:false,failureKey:`${ID}:terminal:${state.task_id}:${location.search}`};
    window.liveFlowV3Model=model;
    const cards=state.streams.map(p=>`<${model.mode==='simplified'?'button':'div'} class="lfv-card" data-stream="${p.id}" style="--probe:${p.color}"><b>${p.id}</b><span class="lfv-flags"></span><span class="lfv-current"></span><span class="lfv-heat"></span><span class="lfv-pose"></span><span class="lfv-aim"></span><span class="lfv-buffer"><i></i></span></${model.mode==='simplified'?'button':'div'}>`).join('');
    helpers.app.innerHTML=`<section class="lfv-lab" data-interaction="${model.mode}"><header class="lfv-head"><div><span>THE HOT PATCH / CONTROL-FLOW LAB</span><h1>Live Control-Flow Wiring Lab <i>III</i></h1></div><p>One program. ${state.streams.length} execution${state.streams.length>1?'s':''}.<br><b>Contacts advance one fixed step after each deliberate input.</b></p></header>
      <main class="lfv-main"><aside class="lfv-program"><header><b>PROGRAM / INSPECT DISPATCHES</b></header><ol>${[...state.nodes].sort((a,b)=>a.id.localeCompare(b.id)).map(n=>`<li data-program-node="${esc(n.id)}"><div><b>${esc(n.id)}</b>${n.kind==='exit'?'':`<button class="lfv-inspect" data-inspect="${esc(n.id)}" aria-label="Inspect dispatch for ${esc(n.id)}">INSPECT<br>DISPATCH</button>`}</div><code><span class="lfv-dispatch">${listing(n)}</span><span class="lfv-motion" data-motion="${n.id}"></span></code></li>`).join('')}</ol><div class="lfv-legend"><b>DISPATCH DEBUGGER</b><span>Inspect a block to reveal its directed targets. Discovered routes stay visible. Inspection never heats or welds; contacts hold between inputs.</span><b>HEAT → WELD</b><span>Large contact: heat with the whole probe.</span><span>Small ⚡ socket on its right: fire the armed weld.</span><b>FLAGS</b><span>☀ on / ☾ off · ◆ on / ○ off</span><span>↺ one feedback lap remains</span><p>${model.mode==='full'?'Drag a cold probe to heat; release parks its target. When ARMED, let go and grab the charged probe again. Drag its small weld spot and release inside the ⚡ socket.':'Select an execution and click to aim the heater. Once ARMED, select WELD TOOL, then click the ⚡ socket to fire. Heating clicks never fire a weld.'}</p><p>A wrong heated edge, a missed weld or an empty buffer ends the attempt.</p><p>Rails announce this and the next segment. The listing repeats their endpoints and turn time. Segment length: ${(state.physics.motion_span_ms/1000).toFixed(1)} s; motion eases between endpoints.</p></div></aside>
      <section class="lfv-rig"><div class="lfv-cards">${cards}</div><div class="lfv-stage"><canvas class="lfv-field" width="880" height="470" aria-label="Moving program contacts, announced motion rails and colored execution probes"></canvas></div><div class="lfv-caption"><span class="lfv-phase"></span><button class="lfv-weld-tool">SELECT WELD TOOL ⚡</button><span>HEAT → ARMED → AIM & WELD</span></div></section></main>
      <footer class="lfv-foot"><button class="lfv-run">RUN PROGRAM →</button><div class="readout" data-status="idle">Inspect dispatches before choosing a route.</div><button class="lfv-seal">${state.submit_label}</button></footer><div class="lfv-verdict"></div></section>`;
    document.querySelectorAll('.lfv-inspect').forEach(button=>button.addEventListener('click',()=> {
      if(model.submitted || model.physics.won)return;
      const node=state.nodes.find(n=>n.id===button.dataset.inspect);
      model.inspected.add(node.id);record('inspect',{node_id:node.id,input_source:'dispatch_inspection'});
      button.closest('li').querySelector('.lfv-dispatch').innerHTML=listing(node);
      button.textContent='INSPECTED';button.setAttribute('aria-expanded','true');
      helpers.setReadout(`${node.id} DISPATCH REVEALED · ${model.physics.running?'CONTACTS HOLD BETWEEN INPUTS':'SAFE TO READ'}`,'idle');draw();
    }));
    const canvas=document.querySelector('.lfv-field');
    canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);
    canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);
    canvas.addEventListener('lostpointercapture',release);
    document.querySelectorAll('button.lfv-card').forEach(card=>card.addEventListener('click',()=> {
      const p=model.physics.streams.find(p=>p.id===card.dataset.stream);
      if(model.submitted || !model.physics.running || p.done)return;
      model.selected=p.id;model.weldMode=false;actionStep();record('select',{stream_id:p.id,input_source:'probe_click'});if(model.physics.failed)finish(true);draw();
    }));
    document.querySelector('.lfv-weld-tool').addEventListener('click',()=> {
      const p=model.physics.streams.find(p=>p.id===model.selected);
      if(model.submitted || !p?.armed)return;
      model.weldMode=true;actionStep();record('weld_select',{stream_id:p.id,input_source:'probe_click'});if(model.physics.failed)finish(true);draw();
    });
    document.querySelector('.lfv-run').addEventListener('click',()=> {
      if(model.submitted || model.physics.running)return;
      model.physics.start();record('run',{input_source:'run_button'});
      helpers.setReadout('INPUT-STEPPED · FOLLOW EACH EXECUTION','idle');draw();
    });
    document.querySelector('.lfv-seal').addEventListener('click',()=>finish());
    let prior=state.episode_failed?'A failed submission already ended this episode.':state.episode_history_error || '';
    if(!prior)try {prior=sessionStorage.getItem(model.failureKey) || '';}catch(_){}
    if(prior) {
      model.physics.failed=prior;model.submitted=true;model.outcome={passed:false};
      document.querySelector('.lfv-lab').dataset.verdict='fail';
      document.querySelector('.lfv-verdict').innerHTML=`<strong>${state.episode_history_error?'VERIFICATION UNAVAILABLE':'FAIL'}</strong><span>${esc(prior)}</span>`;
      helpers.setReadout(state.episode_history_error?'VERIFIER UNAVAILABLE · HISTORY RETAINED':'FAIL · EPISODE ENDED','error');
    }
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.lfv-lab',render};
})();
