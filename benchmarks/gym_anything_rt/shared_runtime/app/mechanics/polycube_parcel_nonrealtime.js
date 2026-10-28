(() => {
  'use strict';
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  let model, frame = 0, keyHandler;
  const clone = x => JSON.parse(JSON.stringify(x));
  const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const ROTATIONS = {
    x: {1:[[1,0,0],[0,0,-1],[0,1,0]], '-1':[[1,0,0],[0,0,1],[0,-1,0]]},
    y: {1:[[0,0,1],[0,1,0],[-1,0,0]], '-1':[[0,0,-1],[0,1,0],[1,0,0]]},
    z: {1:[[0,-1,0],[1,0,0],[0,0,1]], '-1':[[0,1,0],[-1,0,0],[0,0,1]]},
  };
  function mul(a, b) { return a.map((r,i) => r.map((_,j) => a[i].reduce((s,v,k) => s + v*b[k][j], 0))); }
  function normalized(p) {
    const cs = p.shape.map(c => p.orientation.map(row => row.reduce((s,v,i) => s+v*c[i],0)));
    const low = [0,1,2].map(i => Math.min(...cs.map(c => c[i])));
    return cs.map(c => c.map((v,i) => v-low[i]));
  }
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index+1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function motion(ms) {
    const spec = model.world.motion;
    if(spec.mode==='fixed') ms=0;
    const u = Math.max(0,ms)/spec.span_ms, n = Math.floor(u), f=u-n, h=f*f*(3-2*f);
    return spec.amplitude.map((a,i) => a*(noise(spec.seed+i*7919,n)*(1-h)+noise(spec.seed+i*7919,n+1)*h));
  }
  function occupied() {
    return new Set(Object.values(model.pieces).filter(p=>p.placed).flatMap(p=>normalized(p).map(c=>c.map((v,i)=>v+p.origin[i]).join(','))));
  }
  function validOrigin(p, origin) {
    const taken=occupied();
    return normalized(p).every(c=>{const cell=c.map((v,i)=>v+origin[i]); return cell.every(v=>v>=0&&v<3)&&!taken.has(cell.join(','));});
  }
  function record(kind, source, data={}) { model.events.push({sequence:model.events.length+1,kind,ms:model.ms,input_source:source,...data}); }
  function say(text,status='idle') { model.message=text; model.helpers.setReadout(text,status); }
  function physicsTick() {
    const w=model.world, dt=w.tick_ms/1000;
    for(let i=0;i<3;i++) {
      const a=clamp(w.gain*(model.target[i]-model.position[i])-w.damping*model.velocity[i],-w.max_acceleration,w.max_acceleration);
      model.velocity[i]=clamp(model.velocity[i]+a*dt,-w.max_speed,w.max_speed);
      model.position[i]+=model.velocity[i]*dt;
    }
    model.ms+=w.tick_ms;
    const d=model.docking;
    if(d) {
      const offset=motion(model.ms), error=Math.max(...model.position.map((v,i)=>Math.abs(v-offset[i]-d.origin[i])));
      if(error>w.profile.tolerance+1e-8) model.failed='alignment lost during seating';
      else if(model.ms-d.started_ms>=w.profile.dock_ms) {
        const piece=model.pieces[d.piece_id]; piece.placed=true; piece.origin=[...d.origin];
        model.placements.push({piece_id:piece.id,origin:[...d.origin],ms:model.ms});
        model.docking=null; model.selected=null;
        say(`${piece.id} SEATED · SELECT THE NEXT PIECE.`);
        if(occupied().size===27) {model.completed=true; say('ALL 27 CELLS FILLED · CERTIFY THE PARCEL.', 'passed');}
      }
    }
    if(model.ms>=w.max_ms&&!model.completed) model.failed='active time exhausted';
  }
  function actionAdvance(duration) {
    const goal=Math.min(model.world.max_ms,model.ms+duration);
    while(model.ms<goal&&!model.failed&&!model.completed) physicsTick();
  }
  function sync() { return; }
  function usable() { return !model.failed&&!model.completed&&!model.submitting; }
  function select(id) {
    if(!usable()||model.docking||model.pieces[id].placed) return;
    model.selected=id; record('select','piece_button',{piece_id:id});
    say(`${id} LOADED · TURN THE PIECE, AIM AT AN EMPTY LATTICE ORIGIN.`); draw();
  }
  function rotate(axis,direction) {
    if(!usable()||model.docking||!model.selected) return;
    const p=model.pieces[model.selected]; p.orientation=mul(ROTATIONS[axis][direction],p.orientation);
    record('rotate','rotation_button',{axis,direction}); draw();
  }
  function aim(axes,values,source) {
    if(!usable()) return;
    const [lo,hi]=model.world.motor_bounds;
    values=values.map(v=>Math.round(clamp(v,lo,hi)*1000000)/1000000);
    axes.forEach((axis,i)=>model.target[axis]=values[i]);
    if(!model.started) model.position=[...model.target];
    record(axes.length===2?'aim_xy':'aim_z',source,{values});
    if(model.started) actionAdvance(model.world.action_motor_ms);
    draw();
  }
  function start() {
    if(!usable()||model.started) return;
    model.started=true; record('start','start_button');
    say('CRADLE RELEASED · THE LAYOUT STAYS FIXED WHILE YOU AIM, TURN OR DRAG.'); draw();
  }
  function seat(source) {
    if(!usable()||!model.started||!model.selected||model.docking) return;
    const off=motion(model.ms), origin=model.position.map((v,i)=>Math.floor(v-off[i]+.5));
    const error=Math.max(...model.position.map((v,i)=>Math.abs(v-off[i]-origin[i])));
    record('seat',source);
    if(error>model.world.profile.tolerance+1e-8) model.failed='seat initiated outside alignment halo';
    else if(!validOrigin(model.pieces[model.selected],origin)) model.failed='seat collides or protrudes outside parcel';
    else {
      model.docking={piece_id:model.selected,origin,started_ms:model.ms};
      say('SEATING · ACTION-TRIGGERED DOCKING TRANSITION.', 'pending');
      actionAdvance(model.world.profile.dock_ms);
    }
    draw(); if(model.failed) {say(`FAIL · ${model.failed.toUpperCase()}`, 'error'); submit();}
  }
  function orbit(direction) {
    if(!usable()) return;
    if(direction==='left') model.yaw-=25;
    if(direction==='right') model.yaw+=25;
    if(direction==='up') model.pitch=clamp(model.pitch+.12,.15,.95);
    if(direction==='down') model.pitch=clamp(model.pitch-.12,.15,.95);
    record('camera','camera_button',{direction}); draw();
  }
  async function submit() {
    if(model.submitting) return;
    if(model.submitting) return;
    if(!model.completed&&!model.failed) model.failed='submitted incomplete parcel';
    record('submit','submit_button'); model.submitting=true; draw();
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      interaction_mode:model.interaction,events:clone(model.events),ms:model.ms,position:[...model.position],
      velocity:[...model.velocity],target:[...model.target],placements:clone(model.placements),completed:model.completed,failed:model.failed};
    model.lastPayload=payload;
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const outcome=await response.json(); model.verdict=outcome; model.submitting=false; model.certified=true;
      if(outcome.passed===true) say('PASS · EXACT COVER AND ACTION-SETTLED ALIGNMENT VERIFIED.', 'passed');
      else {model.failed=model.failed||'independent replay rejected the parcel'; say(`FAIL · ${model.failed.toUpperCase()}`, 'error');}
      // Failure is terminal. A fresh server challenge never erases this episode.
      draw();
    } catch(error) {model.submitting=false; say('RESULT LINK UNAVAILABLE · CERTIFY AGAIN TO RESEND THIS ATTEMPT.', 'error');}
  }
  function project(c,scale=70,origin=[320,260],yaw=model.yaw,pitch=model.pitch) {
    const a=yaw*Math.PI/180, rx=c[0]*Math.cos(a)-c[2]*Math.sin(a), rz=c[0]*Math.sin(a)+c[2]*Math.cos(a);
    return [origin[0]+rx*scale,origin[1]-(c[1]*Math.cos(pitch)-rz*Math.sin(pitch))*scale,c[1]*Math.sin(pitch)+rz*Math.cos(pitch)];
  }
  function wire(ctx,cell,scale,origin,yaw,pitch,color) {
    const [x,y,z]=cell, pts=[[x,y,z],[x+1,y,z],[x+1,y+1,z],[x,y+1,z],[x,y,z+1],[x+1,y,z+1],[x+1,y+1,z+1],[x,y+1,z+1]].map(c=>project(c,scale,origin,yaw,pitch));
    ctx.strokeStyle=color; ctx.lineWidth=1;
    for(const [a,b] of [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]]) {ctx.beginPath();ctx.moveTo(...pts[a].slice(0,2));ctx.lineTo(...pts[b].slice(0,2));ctx.stroke();}
  }
  function solids(ctx,items,scale,origin,yaw,pitch,alpha=1) {
    const faces=[[0,1,2,3],[4,7,6,5],[0,4,5,1],[3,2,6,7],[0,3,7,4],[1,5,6,2]];
    const normals=[[0,0,-1],[0,0,1],[0,-1,0],[0,1,0],[-1,0,0],[1,0,0]], a=yaw*Math.PI/180;
    const depthVector=[Math.sin(a)*Math.cos(pitch),Math.sin(pitch),Math.cos(a)*Math.cos(pitch)];
    const all=[];
    for(const item of items) {
      const [x,y,z]=item.cell, cs=[[x,y,z],[x+1,y,z],[x+1,y+1,z],[x,y+1,z],[x,y,z+1],[x+1,y,z+1],[x+1,y+1,z+1],[x,y+1,z+1]].map(c=>project(c,scale,origin,yaw,pitch));
      faces.forEach((face,k)=>{if(normals[k].reduce((s,v,i)=>s+v*depthVector[i],0)>0) all.push({pts:face.map(i=>cs[i]),depth:face.reduce((s,i)=>s+cs[i][2],0)/4,color:item.color,k});});
    }
    all.sort((a,b)=>a.depth-b.depth);
    ctx.globalAlpha=alpha;
    for(const face of all) {
      ctx.beginPath();face.pts.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();
      ctx.fillStyle=face.color;ctx.fill();ctx.fillStyle=face.k===3?'#ffffff':face.k===5?'#071820':'#28414b';ctx.globalAlpha=alpha*.18;ctx.fill();ctx.globalAlpha=alpha;
      ctx.strokeStyle='#11262d';ctx.lineWidth=1.1;ctx.stroke();
    }
    ctx.globalAlpha=1;
  }
  function drawScene() {
    const canvas=model.app.querySelector('.pv-scene'),ctx=canvas.getContext('2d'),off=motion(model.ms);
    ctx.clearRect(0,0,640,440); ctx.fillStyle='#0a202b';ctx.fillRect(0,0,640,440);
    ctx.strokeStyle='#294654';ctx.lineWidth=1;
    for(let i=0;i<18;i++){ctx.beginPath();ctx.moveTo(i*40,0);ctx.lineTo(i*40,440);ctx.stroke();}
    for(let i=0;i<12;i++){ctx.beginPath();ctx.moveTo(0,i*40);ctx.lineTo(640,i*40);ctx.stroke();}
    const shift=c=>c.map((v,i)=>v+off[i]-1.5), items=[];
    Object.values(model.pieces).filter(p=>p.placed).forEach(p=>normalized(p).forEach(c=>items.push({cell:shift(c.map((v,i)=>v+p.origin[i])),color:p.color})));
    solids(ctx,items,65,[320,238],model.yaw,model.pitch);
    for(let x=0;x<3;x++)for(let y=0;y<3;y++)for(let z=0;z<3;z++) wire(ctx,shift([x,y,z]),65,[320,238],model.yaw,model.pitch,'#bcecd750');
    if(model.selected) {
      const piece=model.pieces[model.selected];
      normalized(piece).forEach(c=>wire(ctx,c.map((v,i)=>v+model.position[i]-1.5),65,[320,238],model.yaw,model.pitch,piece.color));
    }
    const point=project(model.position.map(v=>v-1.5),65,[320,238]);
    ctx.strokeStyle='#ffffff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(point[0],point[1],7,0,Math.PI*2);ctx.stroke();
    ctx.fillStyle='#d6eee7';ctx.font='13px monospace';ctx.fillText('RIGID PACKING VOLUME · 3 × 3 × 3',18,27);
    ctx.fillText('Outline = placement preview; only SEAT makes it solid.',18,420);
    const p=model.selected?model.pieces[model.selected]:null;
    const preview=model.app.querySelector('.pv-preview'), pc=preview.getContext('2d');pc.clearRect(0,0,200,130);
    if(p) {
      const cs=normalized(p),mid=[0,1,2].map(i=>(Math.max(...cs.map(c=>c[i]))+1)/2);
      solids(pc,cs.map(c=>({cell:c.map((v,i)=>v-mid[i]),color:p.color})),31,[100,66],35,.52);
    }
  }
  function drawXY() {
    const canvas=model.app.querySelector('.pv-xy'),ctx=canvas.getContext('2d'),off=motion(model.ms),lo=-1.25,span=5.5;
    const point=p=>[(p[0]-lo)/span*320,320-(p[1]-lo)/span*320];
    ctx.fillStyle='#091e27';ctx.fillRect(0,0,320,320);ctx.strokeStyle='#345762';ctx.lineWidth=1;
    for(let v=-1;v<=4;v++){const x=point([v,0])[0],y=point([0,v])[1];ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,320);ctx.moveTo(0,y);ctx.lineTo(320,y);ctx.stroke();}
    const tol=model.world.profile.tolerance*320/span;
    for(let x=0;x<3;x++)for(let y=0;y<3;y++) {
      const p=point([x+off[0],y+off[1]]);ctx.strokeStyle='#85dcc774';ctx.strokeRect(p[0]-tol,p[1]-tol,2*tol,2*tol);
      ctx.fillStyle='#95d8ca';ctx.beginPath();ctx.arc(p[0],p[1],3,0,Math.PI*2);ctx.fill();
      ctx.font='10px monospace';ctx.fillText(`${x},${y}`,p[0]+5,p[1]-5);
    }
    // This short trace is past evidence, not a supplied interception point.
    ctx.fillStyle='#dfbe72';ctx.font='11px monospace';ctx.fillText('FIXED LAYOUT',10,17);
    if(model.docking) {
      const p=point([off[0]+model.docking.origin[0],off[1]+model.docking.origin[1]]);ctx.strokeStyle='#ffcb73';ctx.lineWidth=3;ctx.strokeRect(p[0]-tol,p[1]-tol,2*tol,2*tol);
    }
    const t=point(model.target),p=point(model.position);ctx.strokeStyle='#b6c6ca';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(t[0]-8,t[1]);ctx.lineTo(t[0]+8,t[1]);ctx.moveTo(t[0],t[1]-8);ctx.lineTo(t[0],t[1]+8);ctx.stroke();
    ctx.strokeStyle='#ffffff60';ctx.lineWidth=1;ctx.setLineDash([3,3]);ctx.beginPath();ctx.arc(p[0],p[1],22,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);
    ctx.strokeStyle='#fff';ctx.lineWidth=3;ctx.beginPath();ctx.arc(p[0],p[1],8,0,Math.PI*2);ctx.stroke();
    ctx.fillStyle='#e4efe8';ctx.font='12px monospace';ctx.fillText('X →   Y ↑',10,304);
    const zc=model.app.querySelector('.pv-z'),z=zc.getContext('2d'),py=v=>320-(v-lo)/span*320;
    z.fillStyle='#091e27';z.fillRect(0,0,72,320);
    for(let v=-1;v<=4;v++){z.strokeStyle='#345762';z.beginPath();z.moveTo(0,py(v));z.lineTo(72,py(v));z.stroke();}
    for(let v=0;v<3;v++){const y=py(v+off[2]);z.fillStyle='#82d8c430';z.fillRect(5,y-tol,62,2*tol);z.strokeStyle='#82d8c4';z.strokeRect(5,y-tol,62,2*tol);z.fillStyle='#d7eee7';z.font='12px monospace';z.fillText(`Z${v}`,8,y+4);}
    if(model.docking){z.strokeStyle='#ffcb73';z.lineWidth=3;z.strokeRect(4,py(off[2]+model.docking.origin[2])-tol,64,2*tol);}
    z.strokeStyle='#aaa';z.lineWidth=1;z.beginPath();z.moveTo(2,py(model.target[2]));z.lineTo(70,py(model.target[2]));z.stroke();
    z.strokeStyle='#ffffff60';z.lineWidth=1;z.setLineDash([3,3]);z.strokeRect(1,py(model.position[2])-22,70,44);z.setLineDash([]);
    z.strokeStyle='#fff';z.lineWidth=4;z.beginPath();z.moveTo(0,py(model.position[2]));z.lineTo(72,py(model.position[2]));z.stroke();
    z.fillStyle='#e4efe8';z.font='12px monospace';z.fillText('Z ↑',20,17);
  }
  function drawSlices() {
    const canvas=model.app.querySelector('.pv-slices'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,330,112);
    const lookup=new Map();Object.values(model.pieces).filter(p=>p.placed).forEach(p=>normalized(p).forEach(c=>lookup.set(c.map((v,i)=>v+p.origin[i]).join(','),p)));
    for(let z=0;z<3;z++) {
      ctx.fillStyle='#acd6cd';ctx.font='11px monospace';ctx.fillText(`Z = ${z}`,z*110+10,13);
      for(let x=0;x<3;x++)for(let y=0;y<3;y++) {
        const piece=lookup.get([x,y,z].join(',')),px=z*110+x*28+10,py=(2-y)*28+22;
        ctx.fillStyle=piece?piece.color:'#213e49';ctx.fillRect(px,py,26,26);ctx.fillStyle=piece?'#09222b':'#86a39f';ctx.font='12px monospace';ctx.fillText(piece?piece.id:'·',px+9,py+17);
      }
    }
  }
  function draw() {
    if(!model) return;
    drawScene();drawXY();drawSlices();
    model.app.querySelector('.pv-cell-count').textContent=occupied().size;
    model.app.querySelector('.pv-phase').textContent=model.failed?'FAIL':model.certified?'PASS':model.completed?'PACKED':model.started?'FREE FLIGHT':'PREFLIGHT';
    model.app.querySelector('.pv-selected').textContent=model.failed?(model.selected?`${model.selected} · FAILED`:'EPISODE ENDED'):model.selected?`${model.selected} · ${model.docking?'SEATING':'LOADED'}`:'SELECT A LOOSE PIECE';
    const off=motion(model.ms),local=model.position.map((v,i)=>v-off[i]);
    model.app.querySelector('.pv-local').textContent=local.map(v=>v.toFixed(2)).join(' / ');
    model.app.querySelector('.pv-active').textContent=(model.ms/1000).toFixed(2)+' s';
    model.app.querySelector('.pv-progress').style.width=model.docking?Math.min(100,(model.ms-model.docking.started_ms)/model.world.profile.dock_ms*100)+'%':'0%';
    model.app.querySelectorAll('[data-piece]').forEach(b=>{const p=model.pieces[b.dataset.piece];b.disabled=p.placed||!!model.docking||!!model.failed||model.completed;b.classList.toggle('selected',model.selected===p.id);b.dataset.placed=String(p.placed);});
    model.app.querySelector('.pv-start').disabled=model.started||!!model.failed||model.completed;
    model.app.querySelectorAll('[data-turn]').forEach(b=>b.disabled=!model.selected||!!model.docking||!!model.failed||model.completed);
    model.app.querySelectorAll('[data-camera]').forEach(b=>b.disabled=!!model.failed||model.completed||model.submitting);
    const seatButton=model.app.querySelector('.pv-seat');if(seatButton)seatButton.disabled=!model.started||!model.selected||!!model.docking||!!model.failed||model.completed;
    model.app.querySelector('.pv-submit').disabled=model.submitting||model.certified;
    model.app.querySelector('.pv-abort').disabled=!!model.failed||model.completed||model.submitting;
    model.app.querySelector('.pv-shell').dataset.phase=model.failed?'failed':model.completed?'completed':model.started?'active':'preflight';
  }
  function animate(){sync();draw();frame=requestAnimationFrame(animate);}
  function render(state,helpers) {
    cancelAnimationFrame(frame);if(keyHandler)window.removeEventListener('keydown',keyHandler);
    const interaction=state.control_condition?.interaction||'full';
    if(!['full','simplified'].includes(interaction))throw new Error('Unsupported packing control surface');
    model={state,helpers,world:state.world,app:helpers.app,interaction,pieces:Object.fromEntries(state.world.pieces.map(p=>[p.id,clone(p)])),
      ms:0,started:false,selected:null,position:[...state.world.initial_position],velocity:[0,0,0],target:[...state.world.initial_position],
      docking:null,failed:null,completed:false,submitting:false,certified:false,events:[],placements:[],yaw:state.world.camera_yaw,pitch:state.world.camera_pitch};
    document.body.dataset.mechanic='polycube-parcel-nonrealtime';
    const instruction=interaction==='full'?'Grab the white handles and drag in the X/Y plane and depth rail. Space begins SEAT.':'Click the X/Y plane and depth rail. The SEAT button begins seating.';
    helpers.app.innerHTML=`<section class="pv-shell" data-interaction="${interaction}" data-challenge-id="${esc(state.challenge_id)}">
      <header class="pv-head"><div><span>ORBITAL POST / POLYCUBE PARCEL · STABLE MODE</span><h1>Pack a parcel with time to think.</h1></div><div class="pv-badge"><b class="pv-cell-count">0</b><span>/ 27 CELLS</span><strong class="pv-phase">PREFLIGHT</strong></div></header>
      <p class="pv-rules">Fill the 3 × 3 × 3 cradle with all seven rigid pieces. White ring center and white depth mark = gripper; gray cross = motor target. Mint boxes are the alignment halos. ${instruction} Each deliberate target action runs a fixed motor settle; the cradle layout stays fixed while you consider the next action. Keep the gripper center inside the chosen halo on all three axes for ${(state.world.profile.dock_ms/1000).toFixed(1)} seconds of the action-triggered seating transition. The first seating or certification failure ends the episode.</p>
      <main class="pv-main"><article class="pv-volume"><div class="pv-label">01 / INSPECT THE 3D VOLUME</div><canvas class="pv-scene" width="640" height="440" aria-label="3D packing cradle and selected rigid piece"></canvas><div class="pv-camera">${['left','right','up','down'].map((d,i)=>`<button data-camera="${d}">${['↶ ORBIT','ORBIT ↷','TILT ↑','TILT ↓'][i]}</button>`).join('')}</div><div class="pv-label">EXACT OCCUPANCY · Y ↑ · X →</div><canvas class="pv-slices" width="330" height="112" aria-label="Three depth slices showing exact occupied cells"></canvas></article>
      <article class="pv-tracking"><div class="pv-label">02 / ALIGN THE MOTOR</div><div class="pv-monitors"><canvas class="pv-xy" width="320" height="320" aria-label="X Y motor targeting plane"></canvas><canvas class="pv-z" width="72" height="320" aria-label="Z motor targeting rail"></canvas></div><div class="pv-coordinate"><span>GRIPPER IN CRADLE COORDINATES</span><b class="pv-local">0 / 0 / 0</b><small>Tolerance ±${state.world.profile.tolerance.toFixed(2)} cell on EACH axis · origin of selected shape</small></div><div class="pv-seat-progress"><div class="pv-progress"></div></div><p class="pv-hint">The cradle layout remains fixed while waiting. Motor targets and seating use deterministic action-triggered transitions.</p><button class="pv-start">RELEASE CRADLE</button><span class="pv-clock">ACTION TIME <b class="pv-active">0 s</b></span></article>
      <aside class="pv-tools"><div class="pv-label">03 / LOAD & TURN</div><div class="pv-rack">${Object.values(model.pieces).map(p=>`<button data-piece="${p.id}" style="--piece-color:${p.color}"><i></i><b>${p.id}</b><span>${p.shape.length} cells</span></button>`).join('')}</div><div class="pv-selected">SELECT A LOOSE PIECE</div><canvas class="pv-preview" width="200" height="130" aria-label="Selected piece orientation"></canvas><div class="pv-turns">${['x','y','z'].flatMap(axis=>[-1,1].map(direction=>`<button data-turn="${axis}" data-direction="${direction}">${axis.toUpperCase()} ${direction<0?'−':'+'}90°</button>`)).join('')}</div>${interaction==='simplified'?'<button class="pv-seat">SEAT · COMMIT ALIGNMENT</button>':'<p class="pv-key">SPACE · COMMIT SEAT<br><small>Release Space before seating the next piece.</small></p>'}<button class="pv-submit">CERTIFY PARCEL</button><button class="pv-abort">ABANDON ATTEMPT</button></aside></main>
      <footer><div class="readout" data-status="idle">INSPECT AND AIM SAFELY, THEN RELEASE THE CRADLE.</div></footer></section>`;
    const app=model.app;
    app.querySelectorAll('[data-piece]').forEach(b=>b.addEventListener('click',()=>select(b.dataset.piece)));
    app.querySelectorAll('[data-turn]').forEach(b=>b.addEventListener('click',()=>rotate(b.dataset.turn,Number(b.dataset.direction))));
    app.querySelectorAll('[data-camera]').forEach(b=>b.addEventListener('click',()=>orbit(b.dataset.camera)));
    app.querySelector('.pv-start').addEventListener('click',start);app.querySelector('.pv-submit').addEventListener('click',submit);
    app.querySelector('.pv-abort').addEventListener('click',()=>{if(!usable())return;record('abort','abort_button');model.failed='abandoned attempt';submit();});
    app.querySelector('.pv-seat')?.addEventListener('click',()=>seat('seat_button'));
    for(const [selector,axes] of [['.pv-xy',[0,1]],['.pv-z',[2]]]) {
      const canvas=app.querySelector(selector);let dragging=false,grabPoint=null,moved=false;
      const locate=e=>{const r=canvas.getBoundingClientRect();return axes.length===2?[-1.25+(e.clientX-r.left)/r.width*5.5,-1.25+(1-(e.clientY-r.top)/r.height)*5.5]:[-1.25+(1-(e.clientY-r.top)/r.height)*5.5];};
      canvas.addEventListener('pointerdown',e=>{
        if(e.button!==0)return;
        if(interaction==='full') {
          if(!usable())return;
          const values=locate(e),position=axes.map(axis=>model.position[axis]);
          if(Math.hypot(...values.map((v,i)=>v-position[i]))>22/320*5.5){say('GRAB THE WHITE HANDLE BEFORE DRAGGING.');return;}
          dragging=true;grabPoint=[e.clientX,e.clientY];moved=false;canvas.setPointerCapture(e.pointerId);
          record(axes.length===2?'grab_xy':'grab_z',axes.length===2?'gantry_drag':'depth_drag',{values});
        }
      });
      canvas.addEventListener('pointermove',e=>{if(dragging&&interaction==='full'){
        moved ||= Math.hypot(e.clientX-grabPoint[0],e.clientY-grabPoint[1])>3;
        if(moved)aim(axes,locate(e),axes.length===2?'gantry_drag':'depth_drag');
      }});
      const release=e=>{if(dragging){
        if(moved)aim(axes,locate(e),axes.length===2?'gantry_drag':'depth_drag');
        if(usable())record(axes.length===2?'release_xy':'release_z',axes.length===2?'gantry_drag':'depth_drag');
        dragging=false;canvas.releasePointerCapture?.(e.pointerId);
      }};
      canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',()=>{
        if(dragging&&usable())record(axes.length===2?'release_xy':'release_z',axes.length===2?'gantry_drag':'depth_drag');
        dragging=false;
      });
      if(interaction==='simplified')canvas.addEventListener('click',e=>aim(axes,locate(e),axes.length===2?'gantry_click':'depth_click'));
    }
    keyHandler=e=>{if(interaction==='full'&&e.code==='Space'&&!e.repeat){e.preventDefault();seat('space_key');}};
    window.addEventListener('keydown',keyHandler);
    Object.defineProperty(window,'__polycubeParcelNonrealtimeDiagnostic',{configurable:true,get:()=>clone({ms:model.ms,started:model.started,
      selected:model.selected,position:model.position,velocity:model.velocity,target:model.target,docking:model.docking,failed:model.failed,
      completed:model.completed,certified:model.certified,pieces:model.pieces,events:model.events,placements:model.placements,
      world:model.world,offset:motion(model.ms),verdict:model.verdict||null,lastPayload:model.lastPayload||null})});
    say('INSPECT AND AIM SAFELY, THEN RELEASE THE CRADLE.');draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics.polycube_parcel_nonrealtime={rootSelector:'.pv-shell',render};
})();
