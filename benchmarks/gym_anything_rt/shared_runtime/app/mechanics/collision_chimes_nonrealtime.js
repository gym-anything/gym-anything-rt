(() => {
  'use strict';
  const SIDES = ['top','right','bottom','left'], D = [[-1,0],[0,1],[1,0],[0,-1]];
  const COLORS = ['#f4b65b','#65d6c4','#f28ca6','#93baf5','#c8a3f4','#e3d88a'];
  const G = {x:270,y:96,s:360,top:30,right:696,bottom:522,left:204};
  let model;
  const STRIKE_LEAD_MS = 500, AIM_STEP_MS = 1500;
  const esc = v => String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  function noise(seed, i) {
    let x = (seed ^ Math.imul(i+1,0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x>>>16),0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x>>>13),0xc2b2ae35) >>> 0;
    return ((x ^ (x>>>16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function motion(seed,t,span) {
    const u=Math.max(0,t)/span, i=Math.floor(u), f=u-i;
    const a=noise(seed,i), b=noise(seed,i+1);
    return a+(b-a)*f*f*(3-2*f);
  }
  function pulseU(note,t) {
    const p=model.world.parameters, n=model.world.grid_size-1;
    const raw=note.slot+p.drift*(motion(note.drift_seed,t,p.drift_span_ms)-motion(note.drift_seed,note.born_ms,p.drift_span_ms));
    const f=((raw%(2*n))+2*n)%(2*n);
    return .5+(f<=n?f:2*n-f);
  }
  function railXY(side,u) {
    const along=u/model.world.grid_size*G.s;
    return side==='top'?[G.x+along,G.top]:side==='bottom'?[G.x+along,G.bottom]:
      side==='left'?[G.left,G.y+along]:[G.right,G.y+along];
  }
  function pulseXY(note,t) {
    const u=pulseU(note,t), f=clamp((t-note.born_ms)/model.world.parameters.flight_ms,0,1);
    const along=u/model.world.grid_size*G.s;
    return note.side==='top'?[G.x+along,G.y+(G.top-G.y)*f]:
      note.side==='bottom'?[G.x+along,G.y+G.s+(G.bottom-G.y-G.s)*f]:
      note.side==='left'?[G.x+(G.left-G.x)*f,G.y+along]:
      [G.x+G.s+(G.right-G.x-G.s)*f,G.y+along];
  }
  function film(cells,size,beats) {
    let state=cells.map(c=>({...c})); const frames=[state];
    for(let beat=1;beat<=beats;beat++) {
      const occupied=new Set(state.map(c=>`${c.row},${c.col}`));
      const destinations=state.map(c=>[c.row+D[c.direction][0],c.col+D[c.direction][1]]);
      const counts={}; for(const pos of destinations) { const k=pos.join(','); counts[k]=(counts[k]||0)+1; }
      state=state.map((c,i)=> {
        const [r,col]=destinations[i];
        if(r<0||r>=size||col<0||col>=size) return {...c,direction:(c.direction+2)%4};
        if(occupied.has(`${r},${col}`)||counts[`${r},${col}`]>1) return {...c,direction:(c.direction+1)%4};
        return {...c,row:r,col};
      }); frames.push(state);
    } return frames;
  }
  function record(kind,extra={}) {
    model.events.push({sequence:model.events.length+1,kind,t_ms:model.time,input_source:model.mode,...extra});
  }
  function decisionTime() {
    const next=model.notes.find(n=>!model.caught.includes(n.id));
    return next ? Math.max(0,next.deadline_ms-STRIKE_LEAD_MS) : model.time;
  }
  function moveReceiver(side,u) {
    const p=model.world.parameters, half=p.pickup_width/2;
    const targetU=clamp(u,half,model.world.grid_size-half);
    const travel=p.pickup_speed*AIM_STEP_MS/1000;
    model.targets[side]=targetU;
    model.pickups[side]+=clamp(targetU-model.pickups[side],-travel,travel);
    record('target',{side,u:targetU,pickup_u:model.pickups[side]});
  }
  async function finish(reason='') {
    if(model.terminal) return;
    model.terminal=true; model.phase=reason?'failed':'complete'; model.reason=reason;
    document.querySelector('#cc2-start').disabled=true;
    document.querySelector('#cc2-abandon').disabled=true;
    model.helpers.setReadout(reason?`FAIL · ${reason}`:'VERIFYING CHIME PERFORMANCE…',reason?'error':'pending');
    draw();
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({
        mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
        interaction_mode:model.mode,events:model.events,final_t_ms:model.time,caught:model.caught,completed:!reason})});
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      const decision=await response.json(); model.decision=decision;
      model.phase=decision.passed?'passed':'failed';
      model.helpers.setReadout(decision.passed?'PASS · EVERY WALL CHIME CAUGHT':`FAIL · ${reason||decision.feedback||'REPLAY REJECTED'}`,decision.passed?'passed':'error');
      draw();
    } catch(error) {
      model.phase='error'; model.reason=error.message;
      model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`,'error'); draw();
    }
  }
  function pointer(event) {
    const rect=model.canvas.getBoundingClientRect();
    return [(event.clientX-rect.left)*950/rect.width,(event.clientY-rect.top)*552/rect.height];
  }
  function railAt(x,y) {
    for(const side of SIDES) {
      const horizontal=side==='top'||side==='bottom';
      const axis=horizontal?x:y, base=horizontal?G.x:G.y;
      if(axis>=base&&axis<=base+G.s&&Math.abs((horizontal?y:x)-G[side])<=model.world.parameters.pickup_depth_px)
        return {side,u:clamp((axis-base)/G.s*model.world.grid_size,0,model.world.grid_size)};
    } return null;
  }
  function target(side,u) {
    moveReceiver(side,u);
  }
  function installInput() {
    const canvas=model.canvas;
    canvas.addEventListener('pointerdown',e=> {
      if(e.button!==0||model.phase!=='running'||model.terminal) return;
      const [x,y]=pointer(e), rail=railAt(x,y); if(!rail) return;
      if(model.mode==='simplified') {target(rail.side,rail.u); draw(); return;}
      if(Math.abs(rail.u-model.pickups[rail.side])>model.world.parameters.pickup_width/2) return;
      e.preventDefault(); canvas.setPointerCapture(e.pointerId);
      model.drag={side:rail.side,pointerId:e.pointerId}; record('grab',rail); draw();
    });
    canvas.addEventListener('pointermove',e=> {
      if(!model.drag||model.terminal) return;
      const [x,y]=pointer(e), side=model.drag.side, base=side==='top'||side==='bottom'?G.x:G.y;
      const along=side==='top'||side==='bottom'?x:y;
      target(side,clamp((along-base)/G.s*model.world.grid_size,0,model.world.grid_size)); draw();
    });
    const release=e=> {
      if(!model.drag) return;
      if(!model.terminal) {
        record('release',{side:model.drag.side,u:model.pickups[model.drag.side]});
      }
      const id=model.drag.pointerId; model.drag=null;
      if(canvas.hasPointerCapture(id)) canvas.releasePointerCapture(id);
      draw();
    };
    canvas.addEventListener('pointerup',release);
    canvas.addEventListener('pointercancel',release);
    canvas.addEventListener('lostpointercapture',release);
    document.querySelector('#cc2-start').addEventListener('click',()=> {
      if(model.phase!=='ready') return;
      model.phase='running'; model.time=decisionTime(); record('start',{t_ms:0});
      document.querySelector('#cc2-start').disabled=true; document.querySelector('#cc2-abandon').disabled=false;
      model.helpers.setReadout('ACTION SNAPSHOT · WAITING DOES NOT ADVANCE · END ATTEMPT IS FINAL','idle');
      draw();
    });
    document.querySelector('#cc2-abandon').addEventListener('click',()=> {
      if(model.terminal||model.phase!=='running') return;
      record('abandon'); finish('ATTEMPT ENDED');
    });
    for(const side of SIDES) document.querySelector(`#cc2-strike-${side}`).addEventListener('click',()=> {
      if(model.phase!=='running'||model.terminal||model.drag) return;
      const active=model.notes.filter(n=>n.side===side&&!model.caught.includes(n.id)&&n.born_ms<=model.time);
      if(!active.length) return;
      const impact=active[0].deadline_ms, p=model.world.parameters;
      if((impact-model.time)/p.flight_ms*66>p.pickup_depth_px+1e-7) return;
      const group=active.filter(n=>n.deadline_ms===impact), ids=group.map(n=>n.id);
      record('strike',{side,u:model.pickups[side],note_ids:ids});
      if(group.some(n=>Math.abs(model.pickups[side]-pulseU(n,model.time))>p.pickup_width/2+1e-7)) {
        finish(`STRIKE MISSED AT ${side.toUpperCase()}`);return;
      }
      model.caught.push(...ids);
      if(model.caught.length===model.notes.length) finish(); else draw();
      if(!model.terminal) { model.time=decisionTime(); draw(); }
    });
  }
  function draw() {
    const ctx=model.ctx, t=model.time, p=model.world.parameters, size=model.world.grid_size;
    ctx.clearRect(0,0,950,552); ctx.fillStyle='#122629';ctx.fillRect(0,0,950,552);
    ctx.fillStyle='#203b3c';ctx.fillRect(G.x,G.y,G.s,G.s);
    ctx.strokeStyle='#355051';ctx.lineWidth=1;
    for(let i=0;i<=size;i++) {
      ctx.beginPath();ctx.moveTo(G.x+i/size*G.s,G.y);ctx.lineTo(G.x+i/size*G.s,G.y+G.s);ctx.stroke();
      ctx.beginPath();ctx.moveTo(G.x,G.y+i/size*G.s);ctx.lineTo(G.x+G.s,G.y+i/size*G.s);ctx.stroke();
    }
    ctx.font='11px ui-monospace,monospace';ctx.textAlign='center';ctx.textBaseline='middle';
    for(const side of SIDES) {
      const horizontal=side==='top'||side==='bottom', a=railXY(side,0), b=railXY(side,size);
      ctx.strokeStyle='#4a7473';ctx.lineWidth=6;ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();
      for(let i=0;i<size;i++) {
        const [x,y]=railXY(side,i+.5);ctx.fillStyle='#8da9a2';ctx.fillText(String(i+1),x+(horizontal?0:(side==='left'?-24:24)),y+(horizontal?(side==='top'?-17:17):0));
      }
      const [x,y]=railXY(side,model.pickups[side]), w=p.pickup_width/size*G.s;
      ctx.fillStyle=model.drag?.side===side?'#f3d997':'#bf954e';
      const depth=p.pickup_depth_px;
      ctx.fillRect(x-(horizontal?w/2:depth),y-(horizontal?depth:w/2),horizontal?w:2*depth,horizontal?2*depth:w);
      ctx.strokeStyle='#f8e1a2';ctx.lineWidth=2;ctx.strokeRect(x-(horizontal?w/2:depth),y-(horizontal?depth:w/2),horizontal?w:2*depth,horizontal?2*depth:w);
      ctx.fillStyle='#17302f';ctx.fillText(horizontal?'↔':'↕',x,y);
      const goal=railXY(side,model.targets[side]);ctx.strokeStyle='#e3c882';ctx.lineWidth=1;
      ctx.beginPath();ctx.arc(...goal,4,0,Math.PI*2);ctx.stroke();
    }
    const beat=Math.min(model.frames.length-1,Math.floor(t/p.beat_ms)), f=(t%p.beat_ms)/p.beat_ms;
    const a=model.frames[beat], b=model.frames[Math.min(beat+1,model.frames.length-1)];
    a.forEach((cell,i)=> {
      const c=b[i], x=G.x+(cell.col+(c.col-cell.col)*f+.5)/size*G.s,
        y=G.y+(cell.row+(c.row-cell.row)*f+.5)/size*G.s;
      ctx.fillStyle=COLORS[cell.id%COLORS.length];ctx.beginPath();ctx.roundRect(x-13,y-13,26,26,6);ctx.fill();
      ctx.save();ctx.translate(x,y);ctx.rotate(cell.direction*Math.PI/2);ctx.strokeStyle='#163032';ctx.lineWidth=3;
      ctx.beginPath();ctx.moveTo(0,7);ctx.lineTo(0,-7);ctx.lineTo(-5,-2);ctx.moveTo(0,-7);ctx.lineTo(5,-2);ctx.stroke();ctx.restore();
    });
    const active=model.notes.filter(n=>!model.caught.includes(n.id)&&n.born_ms<=t&&n.deadline_ms>t);
    for(const note of active) {
      const color=COLORS[note.cell_id%COLORS.length];ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.setLineDash([2,4]);ctx.beginPath();
      let first=true;
      for(let dt=-600;dt<=1600;dt+=100) {
        const sample=clamp(t+dt,note.born_ms,note.deadline_ms), xy=pulseXY(note,sample);
        if(first) {ctx.moveTo(...xy);first=false;} else ctx.lineTo(...xy);
      } ctx.stroke();ctx.setLineDash([]);
      const [x,y]=pulseXY(note,t);ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,6,0,Math.PI*2);ctx.fill();
      ctx.strokeStyle='#fff4d7';ctx.lineWidth=1;ctx.stroke();
      ctx.fillStyle='#edf2dd';ctx.font='bold 11px ui-monospace,monospace';ctx.fillText(String(note.id+1),x+13,y-10);
    }
    ctx.textAlign='left';ctx.fillStyle='#f3e0af';ctx.font='bold 20px Georgia,serif';ctx.fillText('Wall choir',20,38);
    ctx.font='11px ui-monospace,monospace';ctx.fillStyle='#90b6ab';ctx.fillText('ARROWS MOVE · WALLS CHIME',20,65);
    ctx.fillText('ENCOUNTERS TURN CLOCKWISE',20,82);
    ctx.fillStyle='#d6dfcd';ctx.font='15px ui-monospace,monospace';ctx.fillText(`CAUGHT  ${model.caught.length} / ${model.notes.length}`,20,140);
    ctx.font='12px ui-monospace,monospace';ctx.fillStyle='#91b6ad';ctx.fillText(`BEAT ${String(beat).padStart(2,'0')}`,20,167);
    ctx.fillText(`ACTIVE ${active.length} PULSES`,20,188);
    ctx.font='12px Georgia,serif';
    ['Slide the brass resonators.','STRIKE when a pulse centre','is inside the brass rectangle.','A wrong strike ends this episode.','Dotted paths show the recent','trail and next 1.6 seconds.','Release a held receiver','before striking. Each action','settles into a fixed snapshot;','waiting does not advance.'].forEach((s,i)=>ctx.fillText(s,20,270+i*20));
    ctx.fillStyle='#91b6ad';ctx.fillText('ARRIVING CHIMES',754,40);ctx.font='12px ui-monospace,monospace';
    active.sort((a,b)=>a.deadline_ms-b.deadline_ms).slice(0,8).forEach((n,i)=> {
      ctx.fillStyle=COLORS[n.cell_id%COLORS.length];ctx.fillText(`${String(n.id+1).padStart(2,'0')}  ${n.side.toUpperCase()}`,754,70+i*26);
      ctx.fillStyle='#aec1b4';ctx.fillText(`${((n.deadline_ms-t)/1000).toFixed(1)}s TO RAIL`,754,82+i*26);
    });
    ctx.fillStyle='#d6dfcd';ctx.font='10px ui-monospace,monospace';ctx.fillText('STRIKE WHEN CENTRE ENTERS BRASS',754,292);
    for(const side of SIDES) {
      const button=document.querySelector(`#cc2-strike-${side}`), next=active.find(n=>n.side===side);
      const enabled=model.phase==='running'&&!model.terminal&&!model.drag&&next&&(next.deadline_ms-t)/p.flight_ms*66<=p.pickup_depth_px+1e-7;
      button.disabled=!enabled;
      const ids=next?active.filter(n=>n.side===side&&n.deadline_ms===next.deadline_ms).map(n=>n.id+1):[];
      button.textContent=`${side.toUpperCase()} · ${enabled?'STRIKE '+ids.join('+'):'WAIT'}`;
    }
    if(model.terminal) {
      const pass=model.phase==='passed'||model.phase==='complete';
      ctx.fillStyle='rgba(11,27,28,.86)';ctx.fillRect(G.x-12,G.y+100,G.s+24,158);
      ctx.fillStyle=pass?'#9be4c2':'#ff9b86';ctx.font='bold 38px Georgia,serif';ctx.textAlign='center';
      ctx.fillText(model.phase==='error'?'VERIFIER ERROR':pass?'CHOIR COMPLETE':'CHIME LOST',G.x+G.s/2,G.y+149);
      ctx.font='13px ui-monospace,monospace';ctx.fillText(pass?`${model.caught.length} / ${model.notes.length} CAPTURED`:model.reason,G.x+G.s/2,G.y+194);
      ctx.fillText('ONE ATTEMPT · RESULT PRESERVED',G.x+G.s/2,G.y+224);
    }
  }
  function render(state,helpers) {
    document.body.dataset.mechanic='collision-chimes-nonrealtime';
    const world=state.world, mode=state.control_condition?.interaction||'full';
    model={state,helpers,world,mode,phase:'ready',time:0,terminal:false,events:[],caught:[],nextNote:0,
      notes:[...world.notes].sort((a,b)=>a.deadline_ms-b.deadline_ms||a.id-b.id),
      frames:film(world.cells,world.grid_size,world.parameters.beats),pickups:{},targets:{},drag:null};
    for(const side of SIDES) model.pickups[side]=model.targets[side]=world.grid_size/2;
    helpers.app.innerHTML=`<section class="cc2" data-interaction="${esc(mode)}"><header class="cc2-head"><div><small>CELLULAR MUSIC / LIVE RESONANCE</small><h1>Collision Chimes V2</h1></div><p>${esc(state.prompt)}</p><b>D${state.control_condition?.difficulty||5} · ${mode.toUpperCase()}</b></header><div class="cc2-stage"><canvas id="cc2-canvas" width="950" height="552" aria-label="live arrow board and four sliding brass receiver rectangles"></canvas>${SIDES.map((side,i)=>`<button class="cc2-strike" id="cc2-strike-${side}" style="top:${(306+i*48)/552*100}%" disabled>${side.toUpperCase()} · WAIT</button>`).join('')}</div><footer class="cc2-foot"><button id="cc2-start">▶ START CHOIR</button><button id="cc2-abandon" disabled>END ATTEMPT</button><span>${mode==='full'?'Drag a brass resonator along its rail.':'Click a rail position to move its resonator.'} Strike while each pulse centre is inside it.</span></footer><div class="readout">READY · INSPECT, THEN START · ONE ATTEMPT; END ATTEMPT IS FINAL</div></section>`;
    model.canvas=document.querySelector('#cc2-canvas');model.ctx=model.canvas.getContext('2d');
    window.collisionChimesNonrealtimeModel=model; installInput();draw();
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.collision_chimes_nonrealtime={rootSelector:'.cc2',render};
})();
