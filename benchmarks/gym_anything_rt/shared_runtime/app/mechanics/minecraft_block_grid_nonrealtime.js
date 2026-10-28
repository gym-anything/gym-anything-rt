(() => {
  'use strict';
  let model;
  const ACTION_STEP_MS=240;
  function rackX(state,r,ms) {
    void ms;
    const parts=String(r.id||'').split('-'),wave=Number.parseInt(parts[1],10);
    return state.travel.entry_x+1.2+Math.min(Math.max(Number.isFinite(wave)?wave:0,0),1)*2.4;
  }
  const rotate=(x,y,v)=>[[x,y],[-y,x],[-x,-y],[y,-x]][v];
  function project(x,y,z,v) {const [a,b]=rotate(x,y,v);return [540+(a-b)*34,274+(a+b)*16-z*34];}
  function faces(state,ms,view,removed) {
    const racks=new Map(state.racks.filter(r=>rackX(state,r,ms)<state.travel.exit_x).map(r=>[r.id,r]));
    const cubes=state.voxels.filter(v=>racks.has(v.rack) && !removed.has(v.id));
    const occupied=new Set(cubes.map(v=>[v.rack,...v.local].join('|')));
    const located=cubes.map(v=>{const r=racks.get(v.rack);const x=v.local[0]+rackX(state,r,ms), y=v.local[1]+r.y;
      const [rx,ry]=rotate(x,y,view);return {v,x,y,z:v.local[2],sum:rx+ry,rx};});
    located.sort((a,b)=>a.sum-b.sum || a.z-b.z || a.rx-b.rx || a.v.id.localeCompare(b.v.id));
    const nx=[[1,0],[0,-1],[-1,0],[0,1]][view], ny=[[0,1],[1,0],[0,-1],[-1,0]][view], result=[];
    for (const {v,x,y,z} of located) {
      const [sx,sy]=project(x,y,z,view),[lx,ly,lz]=v.local;
      const candidates=[['right',...nx,0,[[sx+34,sy+16],[sx,sy+32],[sx,sy+66],[sx+34,sy+50]]],
        ['left',...ny,0,[[sx-34,sy+16],[sx,sy+32],[sx,sy+66],[sx-34,sy+50]]],
        ['top',0,0,1,[[sx,sy],[sx+34,sy+16],[sx,sy+32],[sx-34,sy+16]]]];
      for (const [label,dx,dy,dz,points] of candidates) {
        if (!occupied.has([v.rack,lx+dx,ly+dy,lz+dz].join('|')))
          result.push({voxel_id:v.id,material:v.material,face:label,points});
      }
    }
    return result;
  }
  function inside(p,poly) {
    let hit=false;
    for(let i=0;i<poly.length;i++) {const [xi,yi]=poly[i], [xj,yj]=poly[(i+poly.length-1)%poly.length];
      if((yi>p[1])!==(yj>p[1]) && p[0]<(xj-xi)*(p[1]-yi)/(yj-yi)+xi) hit=!hit;}
    return hit;
  }
  function raycast(state,ms,view,removed,p) {return faces(state,ms,view,removed).reverse().find(f=>inside(p,f.points)) || null;}
  function time() {return model.currentMs;}
  function advance() {model.currentMs+=ACTION_STEP_MS;}
  function record(kind,t,extra={}) {model.events.push({sequence:model.events.length+1,kind,t_ms:t,...extra});}
  function drawPoly(ctx,points) {ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();}
  function draw() {
    const ctx=document.getElementById('quarry-canvas').getContext('2d'),s=model.state, ms=model.currentMs;
    const bg=ctx.createLinearGradient(0,0,0,530);bg.addColorStop(0,'#142a32');bg.addColorStop(1,'#050d13');
    ctx.fillStyle=bg;ctx.fillRect(0,0,1080,530);
    ctx.strokeStyle='#44616a';ctx.lineWidth=2;
    const laneY=[...new Set(s.racks.map(r=>r.y))];
    for (const y of laneY) {
      ctx.strokeStyle='#44616a';ctx.lineWidth=2;
      for (const offset of [-.7,.7]) {const a=project(-6.5,y+offset,-.25,model.view), b=project(6.5,y+offset,-.25,model.view);
        ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();}
      for(let x=-6;x<=6;x+=.6) {const a=project(x,y-.85,-.25,model.view),b=project(x,y+.85,-.25,model.view);
        ctx.strokeStyle='#243e48';ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();}
      const limitA=project(s.travel.exit_x,y-.95,-.25,model.view),limitB=project(s.travel.exit_x,y+.95,-.25,model.view);
      ctx.strokeStyle='#ee7754';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(...limitA);ctx.lineTo(...limitB);ctx.stroke();
      for(const [x,label] of [[s.travel.entry_x,'FEED'],[s.travel.exit_x,'CRUSHER GATE']]) {const p=project(x,y,0,model.view);
        ctx.fillStyle=label==='FEED'?'#88a8ac':'#ee7754';ctx.font='bold 11px monospace';ctx.textAlign='center';ctx.fillText(label,p[0],p[1]+40);}
    }
    // The donor's trajectory cue remains as a settled rail marker. It is
    // diagnostic scenery only and never changes while the user is idle.
    for(const r of s.racks) {
      const x=rackX(s,r,ms), a=project(x-.7,r.y,-.12,model.view), b=project(x,r.y,-.12,model.view);
      ctx.strokeStyle='#9be2e9';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();
    }
    const colors={support:['#d7ae58','#785626','#ad7b35'],stone:['#a3b8b5','#506b70','#6b8588'],ore:['#9dfff2','#20b8bd','#44d9ce']};
    for (const f of faces(s,ms,model.view,model.removed)) {
      const shade={top:0,right:1,left:2}[f.face];drawPoly(ctx,f.points);ctx.fillStyle=colors[f.material][shade];ctx.fill();
      ctx.strokeStyle=f.material==='ore'?'#d6fff9':'#173238';ctx.lineWidth=f.material==='ore'?2:1;ctx.stroke();
      const cx=f.points.reduce((n,p)=>n+p[0],0)/4,cy=f.points.reduce((n,p)=>n+p[1],0)/4;
      ctx.save();drawPoly(ctx,f.points);ctx.clip();
      if (f.material==='support') {
        ctx.strokeStyle='#392e20';ctx.lineWidth=4;
        for(let k=-40;k<60;k+=16){ctx.beginPath();ctx.moveTo(cx-36,cy+k);ctx.lineTo(cx+36,cy+k+28);ctx.stroke();}
      } else if (f.material==='stone') {
        ctx.strokeStyle='#70dfd6';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(cx-13,cy+6);ctx.lineTo(cx-3,cy-2);ctx.lineTo(cx+5,cy+2);ctx.lineTo(cx+13,cy-7);ctx.stroke();
      } else {
        ctx.fillStyle='#e0fff7';ctx.beginPath();ctx.moveTo(cx,cy-8);ctx.lineTo(cx+8,cy);ctx.lineTo(cx,cy+8);ctx.lineTo(cx-8,cy);ctx.closePath();ctx.fill();
      }
      ctx.restore();
    }
    ctx.textAlign='left';ctx.fillStyle='#d5e6df';ctx.font='12px monospace';
    ctx.fillText(model.launchAt===null?'MAGLEV QUARRY / READY':`SETTLED RACKS · VIEW ${model.view+1}/4`,22,26);
    document.getElementById('quarry-count').textContent=model.state.voxels.filter(v=>v.material==='ore' && model.removed.has(v.id)).length+' / '+s.target_count;
  }
  function payload(completed) {return {mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,
    challenge_id:model.state.challenge_id,revision:model.state.revision,interaction_mode:model.mode,
    events:model.events,final_t_ms:model.currentMs,final_view:model.view,removed_ids:[...model.removed].sort(),completed};}
  async function submit(reason='') {
    if(model.terminal) return;
    record(reason?'failure':'seal',model.currentMs,{input_source:reason?'action_failure':'exit_button',reason});
    const completed=!reason && model.state.voxels.filter(v=>v.material==='ore').every(v=>model.removed.has(v.id));
    model.terminal=true;model.failed=reason;model.lastPayload=payload(completed);
    document.getElementById('quarry-launch').disabled=true;document.getElementById('quarry-exit').disabled=true;
    const stamp=document.getElementById('quarry-verdict');stamp.hidden=false;
    stamp.textContent=reason?'FAIL · '+reason:'VERIFYING';
    model.helpers.setReadout(reason?'FAIL · '+reason:'VERIFYING EXCAVATION',reason?'error':'pending');
    try {
      const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(model.lastPayload)});
      const outcome=await r.json();model.outcome=outcome;
      stamp.dataset.verdict=outcome.passed?'pass':'fail';
      stamp.textContent=outcome.passed?'PASS · ORE RECOVERED':'FAIL · '+(reason || 'INCOMPLETE EXCAVATION');
      model.helpers.setReadout(outcome.passed?'PASS · ORE RECOVERED':'FAIL · '+(reason || 'INCOMPLETE EXCAVATION'),outcome.passed?'passed':'error');
    } catch(error) {stamp.textContent='VERIFICATION ERROR';model.helpers.setReadout('VERIFICATION ERROR','error');}
  }
  function turn(delta,details) {
    if(model.terminal || model.launchAt===null) return;
    advance();
    model.view=(model.view+delta+4)%4;
    record('rotate',model.currentMs,{delta,view:model.view,...details});draw();
  }
  function mine(point) {
    if(model.terminal || model.launchAt===null) return;
    advance();
    const f=raycast(model.state,model.currentMs,model.view,model.removed,point);
    record('mine',model.currentMs,{point,view:model.view,input_source:'canvas_pick',voxel_id:f?.voxel_id || null,face:f?.face || null});
    if (f?.material==='support') {submit('PROTECTED SUPPORT FRACTURED');return;}
    if(f) model.removed.add(f.voxel_id);
    model.helpers.setReadout(f?(f.material==='ore'?'ORE EXTRACTED':'STONE CLEARED'):'PICK MISSED',f?'idle':'pending');draw();
  }
  function render(state,helpers) {
    document.body.dataset.mechanic='action-locked-quarry';
    model={state,helpers,mode:state.control_condition.interaction,view:0,removed:new Set(),events:[],launchAt:null,
      currentMs:0,terminal:false,drag:null,failed:'',outcome:null};window.quarryV2Model=model;
    const buttons=model.mode==='simplified'?'<button id="quarry-left">↶ VIEW</button><button id="quarry-right">VIEW ↷</button>':'';
    helpers.app.innerHTML=`<section class="quarry-v2"><header><div><small>THE MAGLEV QUARRY</small><h1>Isometric Voxel Extraction Mine V2</h1></div><div class="quarry-count"><span>ORE RECOVERED</span><b id="quarry-count">0 / ${state.target_count}</b></div></header>
      <main><div class="quarry-scene"><canvas id="quarry-canvas" width="1080" height="530"></canvas><div id="quarry-verdict" hidden></div></div>
      <aside><span class="quarry-kicker">FIELD NOTES</span><p>Excavate every cyan core from the ore racks, preserve their supports, and exit with all ore.</p><div class="quarry-material stone">Teal-seamed rock<br><b>REMOVE</b></div><div class="quarry-material ore">Cyan ore core<br><b>COLLECT</b></div><div class="quarry-material support">Gold striped support<br><b>LEAVE INTACT</b></div>
      <p>${model.mode==='full'?'Right-drag horizontally to turn the view.':'Use VIEW buttons to turn the view.'} Left-click a visible face to mine.</p><p>Racks settle after each deliberate input and remain unchanged while you wait. A broken support or rejected EXIT ends the episode. EXIT is final. Missed picks and view changes remain allowed.</p>${buttons}<button id="quarry-launch">START THE QUARRY</button></aside></main>
      <footer><div class="readout">Inspect the materials, then start.</div><button id="quarry-exit">EXIT WITH THE ORE →</button></footer></section>`;
    const canvas=document.getElementById('quarry-canvas');
    const point=e=>{const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*1080/r.width,(e.clientY-r.top)*530/r.height].map(x=>Math.round(x*1000)/1000);};
    canvas.addEventListener('contextmenu',e=>e.preventDefault());
    canvas.addEventListener('pointerdown',e=>{
      e.preventDefault();if(model.terminal)return;
      if(e.button===2 && model.mode==='full') {model.drag={pointer:e.pointerId,start:point(e)};canvas.setPointerCapture(e.pointerId);}
      else if(e.button===0) mine(point(e));
    });
    canvas.addEventListener('pointerup',e=>{
      if(!model.drag || model.drag.pointer!==e.pointerId) return;
      const start=model.drag.start,end=point(e);model.drag=null;
      if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);
      if(Math.abs(end[0]-start[0])>=48 && Math.abs(end[0]-start[0])>Math.abs(end[1]-start[1]))
        turn(end[0]<start[0]?1:-1,{start,end,input_source:'canvas_drag'});
    });
    for(const e of ['pointercancel','lostpointercapture']) canvas.addEventListener(e,()=>{model.drag=null;});
    document.getElementById('quarry-left')?.addEventListener('click',()=>turn(-1,{input_source:'rotation_buttons'}));
    document.getElementById('quarry-right')?.addEventListener('click',()=>turn(1,{input_source:'rotation_buttons'}));
    document.getElementById('quarry-launch').addEventListener('click',()=>{
      if(model.launchAt!==null || model.terminal)return;
      model.launchAt=0;model.currentMs=0;record('launch',0,{input_source:'launch_button'});
      document.getElementById('quarry-launch').disabled=true;helpers.setReadout('QUARRY RUNNING','idle');draw();
    });
    document.getElementById('quarry-exit').addEventListener('click',()=>{if(model.launchAt!==null){advance();submit();}});draw();
  }
  // Pure geometry is inspectable for implementation tests. No task mutation or
  // solving action is exported. The downstream player uses the visible UI only.
  window.quarryV2Geometry={rackX,faces,project};
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.minecraft_block_grid_nonrealtime={rootSelector:'.quarry-v2',render};
})();
