(() => {
  'use strict';
  const ID='crackglaze_crossing_v3';
  let model, frame=0;
  const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function noise(seed,index) {
    let x=(seed^Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function motion(seed,t,span) {
    const u=Math.max(0,t)/span,n=Math.floor(u),f=u-n;
    return noise(seed,n)+(noise(seed,n+1)-noise(seed,n))*f*f*(3-2*f);
  }
  function center(cell,t) {
    return cell.center.map((x,i)=>x+model.state.parameters.drift_px*motion(cell.motion_seed+i*7919,t+cell.phase_ms,cell.span_ms));
  }
  const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
  const now=()=>Math.max(0,Math.round(performance.now()-model.startedAt));
  const collapsed=(id,t)=>model.litAt[id]!==undefined && t>=model.litAt[id]+model.cells[id].fuse_ms;
  function span(a,b,t) {return distance(center(model.cells[a],t),center(model.cells[b],t));}
  function snapshot() {return {position:model.position,collected:[...model.collected].sort(),lit_at:{...model.litAt}};}
  async function finish(reason='') {
    if(model.terminal)return;
    model.terminal=true;model.failure=reason;model.finalMs=model.currentMs;
    draw();
    model.helpers.setReadout(reason?'FAIL · '+reason.toUpperCase():'VERIFYING CROSSING…',reason?'error':'pending');
    const payload={mechanic_id:ID,revision:model.state.revision,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      interaction_mode:model.mode,events:model.events,inspections:model.inspections,final_t_ms:model.finalMs,final_state:snapshot(),failure:reason,completed:!reason};
    model.payload=payload;
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const result=await response.json();model.serverGrade=result;
      model.passed=result.passed===true;
      model.helpers.setReadout(model.passed?'PASS · ALL LANTERNS HOME':'FAIL · CROSSING ENDED',model.passed?'passed':'error');
      document.querySelector('.crackglaze-v2').dataset.terminal=model.passed?'passed':'failed';
      draw();
    } catch(error) {model.helpers.setReadout('VERIFIER ERROR · '+error.message,'error');}
  }
  function sync() {
    if(!model || model.terminal)return;
    const end=now();
    if(model.flight) {
      const flight=model.flight, stop=Math.min(end,flight.end);
      for(let t=flight.checked;t<=stop;t+=10) {
        if(span(flight.from,flight.to,t)>model.state.parameters.reach_px+1e-6) {
          model.currentMs=t;finish('span_broke');return;
        }
        flight.checked=t+10;
      }
      if(end>=flight.end) {
        model.currentMs=flight.end;
        if(span(flight.from,flight.to,flight.end)>model.state.parameters.reach_px+1e-6) {finish('span_broke');return;}
        if(collapsed(flight.to,flight.end)) {finish('collapsed_landing');return;}
        model.position=flight.to;model.flight=null;
        if(model.state.lantern_ids.includes(model.position))model.collected.add(model.position);
        if(model.position===model.state.exit_id && model.collected.size===model.state.lantern_ids.length){finish();return;}
      }
    }
    if(!model.flight && collapsed(model.position,end)) {
      model.currentMs=model.litAt[model.position]+model.cells[model.position].fuse_ms;
      finish('occupied_raft_collapsed');return;
    }
    model.currentMs=end;
    if(end>=300000)finish('crossing_time_expired');
  }
  function cross(destination,source,point=null,direction='') {
    sync();
    if(model.terminal || model.flight || !model.state.neighbors[model.position].includes(destination))return;
    const t=model.currentMs,origin=model.position;
    const event={sequence:model.events.length+1,kind:'cross',t_ms:t,from:origin,to:destination,input_source:source};
    if(point)event.point=point;
    else event.direction=direction;
    model.events.push(event);
    if(span(origin,destination,t)>model.state.parameters.reach_px+1e-6) {finish('gap_too_wide');return;}
    const end=t+model.state.parameters.crossing_ms;
    if(collapsed(destination,end)) {finish('collapsed_landing');return;}
    if(model.litAt[origin]===undefined)model.litAt[origin]=t;
    model.flight={from:origin,to:destination,start:t,end,checked:t};
    draw();
  }
  function inspect(glaze,button) {
    sync();
    if(model.terminal || model.inspected.has(glaze))return;
    model.inspected.add(glaze);
    const sample=model.state.glazes[glaze];
    model.inspections.push({sequence:model.inspections.length+1,t_ms:model.currentMs,
      glaze,input_source:'sample_turn',fuse_ms:sample.fuse_ms});
    button.dataset.inspected='true';
    button.querySelector('b').textContent=`${sample.fuse_ms/1000}s after leaving`;
    button.setAttribute('aria-label',`${sample.name} kiln stamp: ${sample.fuse_ms/1000} seconds after leaving`);
    // Do not pause, restart a fuse, move the player, or erase a learned stamp.
  }
  function plate(ctx,cell,t) {
    const [x,y]=center(cell,t),half=model.state.parameters.tile_px/2;
    const age=model.litAt[cell.id]===undefined?0:(t-model.litAt[cell.id])/cell.fuse_ms;
    const fallen=collapsed(cell.id,t),glaze=model.state.glazes[cell.glaze];
    if(fallen){ctx.fillStyle='#020407';ctx.fillRect(x-half,y-half,2*half,2*half);ctx.strokeStyle='#4b3540';ctx.strokeRect(x-half,y-half,2*half,2*half);return;}
    ctx.fillStyle='rgba(0,0,0,.55)';ctx.fillRect(x-half+3,y-half+7,2*half,2*half);
    const gradient=ctx.createLinearGradient(x-half,y-half,x+half,y+half);
    gradient.addColorStop(0,glaze.color);gradient.addColorStop(1,'#172931');
    ctx.fillStyle=gradient;ctx.fillRect(x-half,y-half,2*half,2*half);
    ctx.strokeStyle=cell.shadow?'#8198a3':'#f1deb0';ctx.lineWidth=2;ctx.strokeRect(x-half,y-half,2*half,2*half);
    ctx.strokeStyle='rgba(224,234,219,.3)';ctx.lineWidth=1;ctx.strokeRect(x-half+5,y-half+5,2*half-10,2*half-10);
    if(cell.shadow){ctx.fillStyle='rgba(3,7,19,.67)';ctx.fillRect(x-half+2,y-half+2,2*half-4,2*half-4);}
    if(age>0 && !cell.shadow){
      ctx.strokeStyle=age>.8?'#ff926f':'#ffe1ab';ctx.lineWidth=2;ctx.beginPath();
      ctx.moveTo(x-half,y+6);ctx.lineTo(x-4,y-9);ctx.lineTo(x+half,y-16);ctx.stroke();
      if(age>.45){ctx.beginPath();ctx.moveTo(x-4,y-9);ctx.lineTo(x+3,y+half);ctx.stroke();}
      ctx.strokeStyle='#ffc08a';ctx.lineWidth=3;ctx.beginPath();ctx.arc(x,y,half+5,-Math.PI/2,-Math.PI/2+Math.PI*2*Math.max(0,1-age));ctx.stroke();
    }
    ctx.fillStyle=cell.shadow?'#a8b2c4':'#f3dfb0';ctx.font='10px serif';ctx.textAlign='left';ctx.fillText(glaze.mark,x-half+7,y-half+15);
    if(cell.lantern && !model.collected.has(cell.id)) {
      ctx.shadowColor='#ffb85e';ctx.shadowBlur=14;ctx.fillStyle='#ffc660';ctx.fillRect(x-6,y-6,12,15);ctx.shadowBlur=0;
      ctx.strokeStyle='#ffda85';ctx.lineWidth=2;ctx.strokeRect(x-8,y-8,16,20);
      ctx.beginPath();ctx.arc(x,y-10,6,Math.PI,0);ctx.stroke();
    }
    if(cell.id===model.state.exit_id){
      ctx.fillStyle=model.collected.size===model.state.lantern_ids.length?'#ffe7aa':'#261b26';
      ctx.fillRect(x-10,y-17,20,34);ctx.strokeStyle='#e2af69';ctx.lineWidth=3;ctx.strokeRect(x-10,y-17,20,34);
    }
  }
  function motionArrow(ctx,cell,t) {
    if(collapsed(cell.id,t))return;
    const q=center(cell,t),past=center(cell,Math.max(0,t-150));
    const v=q.map((x,i)=>(x-past[i])*4),length=Math.hypot(...v);
    if(length<.25)return;
    // The arrow is outside the face: drawing a centre trail underneath an
    // opaque plate would erase the very evidence it is supposed to show.
    const x=q[0],half=model.state.parameters.tile_px/2;
    let y=q[1]-half-12;
    // Keep the arrowhead visible when an upper raft approaches the board edge.
    if(Math.min(y,y+v[1])<6)y=q[1]+half+12;
    ctx.strokeStyle='#e3e4bc';ctx.fillStyle='#e3e4bc';ctx.lineWidth=2;
    ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+v[0],y+v[1]);ctx.stroke();
    const a=Math.atan2(v[1],v[0]);ctx.beginPath();ctx.moveTo(x+v[0],y+v[1]);
    ctx.lineTo(x+v[0]-5*Math.cos(a-.6),y+v[1]-5*Math.sin(a-.6));ctx.lineTo(x+v[0]-5*Math.cos(a+.6),y+v[1]-5*Math.sin(a+.6));ctx.closePath();ctx.fill();
  }
  function draw() {
    if(!model)return;
    const canvas=document.getElementById('crack-v2-canvas'),ctx=canvas?.getContext('2d');if(!ctx)return;
    const t=model.currentMs;
    const bg=ctx.createLinearGradient(0,0,0,560);bg.addColorStop(0,'#142632');bg.addColorStop(1,'#061118');ctx.fillStyle=bg;ctx.fillRect(0,0,900,560);
    ctx.strokeStyle='rgba(118,152,162,.09)';ctx.lineWidth=1;
    for(let y=30;y<560;y+=35){ctx.beginPath();ctx.moveTo(30,y);ctx.bezierCurveTo(230,y-20,630,y+20,870,y);ctx.stroke();}
    ctx.fillStyle='rgba(207,152,89,.15)';ctx.fillRect(20,14,860,5);ctx.fillRect(20,541,860,5);
    const painted=new Set();
    for(const a of model.state.cells)for(const b of model.state.neighbors[a.id]){
      const key=[a.id,b].sort().join('|');if(painted.has(key))continue;painted.add(key);
      if(collapsed(a.id,t)||collapsed(b,t))continue;
      const ca=center(a,t),cb=center(model.cells[b],t),open=distance(ca,cb)<=model.state.parameters.reach_px;
      ctx.strokeStyle=open?'#b9c5a2':'rgba(174,106,111,.5)';ctx.lineWidth=open?7:2;
      ctx.setLineDash(open?[]:[5,6]);ctx.beginPath();ctx.moveTo(...ca);ctx.lineTo(...cb);ctx.stroke();ctx.setLineDash([]);
      if(open){ctx.strokeStyle='#384343';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(...ca);ctx.lineTo(...cb);ctx.stroke();}
    }
    model.state.cells.forEach(c=>plate(ctx,c,t));
    model.state.cells.forEach(c=>motionArrow(ctx,c,t));
    let pawn=center(model.cells[model.position],t);
    if(model.flight){const f=model.flight,u=Math.max(0,Math.min(1,(t-f.start)/(f.end-f.start))),a=center(model.cells[f.from],t),b=center(model.cells[f.to],t);pawn=a.map((v,i)=>v+(b[i]-v)*u);}
    ctx.fillStyle='#f2e7c5';ctx.strokeStyle='#442e28';ctx.lineWidth=2;ctx.beginPath();ctx.arc(...pawn,9,0,Math.PI*2);ctx.fill();ctx.stroke();
    ctx.strokeStyle='#ffda8b';ctx.lineWidth=2;ctx.beginPath();ctx.arc(...pawn,15,0,Math.PI*2);ctx.stroke();
    document.getElementById('crack-v2-count').textContent=`${model.collected.size} / ${model.state.lantern_ids.length}`;
    document.querySelector('.crackglaze-v2').dataset.position=model.position;
    if(model.terminal){
      ctx.fillStyle='rgba(3,10,17,.86)';ctx.fillRect(225,175,450,120);
      ctx.strokeStyle=model.passed?'#afddc2':'#d5a766';ctx.lineWidth=2;ctx.strokeRect(225,175,450,120);
      ctx.textAlign='center';ctx.fillStyle=model.passed?'#b9e6c6':model.failure?'#ffc0a5':'#ecd39e';ctx.font='32px Georgia';ctx.fillText(model.passed?'ALL LANTERNS HOME':model.failure?'CROSSING LOST':'CROSSING COMPLETE',450,227);
      ctx.font='14px sans-serif';ctx.fillText(model.failure?model.failure.replaceAll('_',' ').toUpperCase():'CERAMIC ARCHIVE / THE DOOR IS OPEN',450,259);
    }
  }
  function animate(){sync();draw();frame=requestAnimationFrame(animate);}
  async function render(state,helpers) {
    cancelAnimationFrame(frame);document.body.dataset.mechanic='crackglaze-crossing-v2';
    model={state,helpers,mode:state.control_condition.interaction,cells:Object.fromEntries(state.cells.map(c=>[c.id,c])),startedAt:performance.now(),currentMs:0,
      position:state.start_id,litAt:{},collected:new Set(),events:[],inspections:[],inspected:new Set(),flight:null,terminal:false,passed:false,failure:''};
    window.crackglazeV3Model=model;
    helpers.app.innerHTML=`<section class="crackglaze-v2" data-terminal="active" data-interaction="${model.mode}">
      <header><div class="cc-v2-seal">CC <span>III</span></div><div><small>CERAMIC ARCHIVE / NIGHT CROSSING</small><h1>Crackglaze Crossing V3</h1></div><div class="cc-v2-count"><small>LANTERNS</small><strong id="crack-v2-count"></strong></div></header>
      <div class="cc-v2-rules">${esc(state.prompt)}</div>
      <div class="cc-v2-stage"><canvas id="crack-v2-canvas" width="900" height="560" aria-label="Drifting ceramic rafts, lanterns and exit door"></canvas>
        <aside><small>KILN SAMPLES</small>${state.glazes.map((g,i)=>({...g,index:i})).sort((a,b)=>['I','II','III','IV'].indexOf(a.mark)-['I','II','III','IV'].indexOf(b.mark)).map(g=>`<button class="cc-v2-glaze cc-v3-sample" data-glaze="${g.index}" data-inspected="false" aria-label="Turn ${esc(g.name)} kiln sample"><i style="background:${g.color}">${g.mark}</i><span>${g.name}<b>Turn sample ↶</b></span></button>`).join('')}
          <p>Solid spans connect nearby rafts. Watch their motion before crossing. A span must stay connected for half a second.</p>
          <p>Dark faces hide cracks; outlines and motion arrows stay visible.</p>
          ${model.mode==='simplified'?`<p>Click a compass arrow to cross.</p><div class="cc-v2-pad">${['up','left','right','down'].map((d,i)=>`<button data-direction="${d}" aria-label="Cross ${d}">${['↑','←','→','↓'][i]}</button>`).join('')}</div>`:'<p>Click an adjacent ceramic raft to cross to it.</p>'}
        </aside></div><footer><div class="readout">Gallery closes after five minutes. Gather every lantern and reach the door. Failed crossings and early seals end the episode.</div><button id="crack-v2-seal">SEAL CROSSING</button></footer></section>`;
    const canvas=document.getElementById('crack-v2-canvas');
    for(const button of document.querySelectorAll('.cc-v3-sample'))button.addEventListener('click',()=>inspect(Number(button.dataset.glaze),button));
    canvas.addEventListener('pointerup',e=>{
      if(e.button!==0 || model.mode!=='full')return;
      sync();const r=canvas.getBoundingClientRect(),p=[(e.clientX-r.left)*900/r.width,(e.clientY-r.top)*560/r.height].map(v=>Math.round(v*100)/100);
      const hit=model.state.cells.find(c=>{const q=center(c,model.currentMs);return p.every((v,i)=>Math.abs(v-q[i])<=state.parameters.tile_px/2);});
      if(hit)cross(hit.id,'raft_click',p);
    });
    for(const button of document.querySelectorAll('.cc-v2-pad button'))button.addEventListener('click',()=>{
      const d=button.dataset.direction,delta={up:[-1,0],left:[0,-1],right:[0,1],down:[1,0]}[d],c=model.cells[model.position];
      const to=model.state.neighbors[model.position].find(id=>model.cells[id].row===c.row+delta[0]&&model.cells[id].column===c.column+delta[1]);
      if(to)cross(to,'direction_button',null,d);
    });
    document.getElementById('crack-v2-seal').addEventListener('click',()=>{sync();if(!model.terminal)finish('incomplete_submission');});
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.crackglaze-v2',render};
})();
