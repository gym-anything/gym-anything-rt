(() => {
  'use strict';
  let model;
  const symbols = ['☽','♧','◇','⌂'];
  const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  const copy = x => JSON.parse(JSON.stringify(x));
  function pose(panel,t) {
    let i=0; while(i<panel.knots.length-2 && panel.knots[i+1][0]<=t) i++;
    const a=panel.knots[i], b=panel.knots[i+1], f=clamp((t-a[0])/(b[0]-a[0]),0,1), s=f*f*(3-2*f);
    return [1,2,3].map(j=>a[j]+(b[j]-a[j])*s);
  }
  function aligned(i,t=model.tick*20) {
    const p=pose(model.state.panels[i],t), w=model.windows[i], rules=model.state.parameters;
    return model.layers[i]===i && Math.hypot(w[0]-p[0],w[1]-p[1])<=rules.position_tolerance && Math.abs(w[2]-p[2])<=rules.radius_tolerance;
  }
  // The counterpart has no autonomous task clock. One deliberate puzzle
  // control advances exactly one donor-sized 20 ms tick; idle time is inert.
  const ACTION_TICKS = 1;
  function advanceAfterAction() {
    if(!model.active || model.terminal) return;
    const goal=model.tick+ACTION_TICKS;
    while(model.tick<goal && !model.terminal) {
      model.tick++;
      const good=model.slots.every((x,j)=>x===model.state.route[j]) && [0,1,2,3].every(i=>aligned(i));
      model.progress=clamp(model.progress+20*(good?1:-model.state.retreat_rate),0,model.state.journey_ms);
      if(model.progress>=model.state.journey_ms) model.terminal='arrived';
      else if(model.tick*20>=model.state.burn_ms) model.terminal='burnt';
    }
    if(model.terminal==='burnt'&&!model.submitting) void seal();
  }
  function record(kind,extra={}) {
    model.events.push({sequence:model.events.length+1,kind,tick:model.tick,...extra});
  }
  function local(event,node) {
    const box=node.getBoundingClientRect();
    return [clamp((event.clientX-box.left)*340/box.width,0,340),clamp((event.clientY-box.top)*220/box.height,0,220)];
  }
  function pan(i,p,extra) {
    if(model.terminal || model.layers[i]===null) return;
    const point=[clamp(p[0],45,295),clamp(p[1],40,180)];
    model.windows[i][0]=point[0]; model.windows[i][1]=point[1];
    record('pan',{panel:i,point,input_source:model.mode,...extra}); advanceAfterAction(); draw();
  }
  function zoom(i,d,extra) {
    if(model.terminal || model.layers[i]===null) return;
    model.windows[i][2]=clamp(model.windows[i][2]+d*2,24,66);
    record('zoom',{panel:i,direction:d,input_source:model.mode,...extra}); advanceAfterAction(); draw();
  }
  function swap(i,slot,gesture) {
    if(model.terminal) return;
    const prev=model.slots.indexOf(i);
    [model.slots[prev],model.slots[slot]]=[model.slots[slot],i];
    record('swap',{panel:i,slot,gesture,input_source:model.mode}); model.selectedHeader=null; layout(); advanceAfterAction(); draw();
  }
  function stack(layer,i,point,gesture) {
    if(model.terminal || model.layers[i]!==null || model.layers.includes(layer)) return;
    model.layers[i]=layer; model.windows[i][0]=clamp(point[0],45,295); model.windows[i][1]=clamp(point[1],40,180);
    record('stack',{panel:i,layer,point,gesture,input_source:model.mode}); model.selectedLayer=null;
    document.querySelector(`[data-layer="${layer}"]`).disabled=true; advanceAfterAction(); draw();
  }
  function peel(i,gesture) {
    if(model.terminal) return;
    if(!model.uncovered[i]) {
      model.uncovered[i]=true;
      record('uncover',{panel:i,gesture,input_source:model.mode}); advanceAfterAction(); draw(); return;
    }
    if(model.layers[i]===null) return;
    const layer=model.layers[i];model.layers[i]=null;
    record('peel',{panel:i,gesture,input_source:model.mode});
    document.querySelector(`[data-layer="${layer}"]`).disabled=false; advanceAfterAction(); draw();
  }
  function begin() {
    if(model.active || model.terminal) return;
    // BEGIN activates the journey; the first active puzzle control consumes
    // the first fixed step, matching the donor grader's event semantics.
    record('begin',{input_source:'begin_button'}); model.active=true; draw();
  }
  async function seal() {
    if(model.submitting) return;
    model.submitting=true;
    const completed=model.terminal==='arrived'; if(!completed) model.terminal=model.terminal || 'sealed_incomplete';
    record('seal',{input_source:'seal_button'}); draw();
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      interaction_mode:model.mode,events:model.events,completed,final_state:{tick:model.tick,progress:model.progress,slots:model.slots,layers:model.layers,windows:model.windows,uncovered:model.uncovered}};
    try {
      const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const outcome=await r.json(); model.grade=outcome;
      model.helpers.setReadout(outcome.passed?'PASS · SHRINE REACHED':'FAIL · PILGRIMAGE ENDED',outcome.passed?'passed':'error');
      document.querySelector('.fpv-verdict').textContent=outcome.passed?'PASS':'FAIL';
      document.querySelector('.fpv-verdict').hidden=false;
    } catch(e) { model.helpers.setReadout('VERIFIER ERROR · '+e.message,'error'); }
  }
  function path(ctx,points,stroke,width=2,fill=null) {
    ctx.beginPath(); points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p)); if(fill){ctx.closePath();ctx.fillStyle=fill;ctx.fill();} if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.stroke();}
  }
  function motif(ctx,i,x,y,r,color,alpha=1) {
    ctx.save();ctx.globalAlpha=alpha;ctx.translate(x,y);ctx.scale(r/44,r/44);ctx.strokeStyle=color;ctx.lineWidth=2;
    ctx.beginPath();ctx.arc(0,0,44,0,Math.PI*2);ctx.stroke();
    const shapes=[[[0,-27],[21,0],[0,27],[-21,0],[0,-27]], [[0,-28],[22,9],[-22,9],[0,-28],[0,28]], [[-22,-22],[22,22],[22,-22],[-22,22],[-22,-22]], [[-23,22],[-23,-7],[0,-28],[23,-7],[23,22],[-23,22]]];
    path(ctx,shapes[i],color,2);ctx.beginPath();ctx.arc(27,-25,4,0,Math.PI*2);ctx.stroke();ctx.restore();
  }
  function scene(ctx,i) {
    const colors=['#c5d4b4','#d2c4a8','#afc8c8','#c8bfd2'];ctx.fillStyle=colors[i];ctx.fillRect(0,0,340,220);
    for(let k=0;k<4;k++){const y=150+k*20;path(ctx,[[0,y],[55,y-32],[135,y-3],[225,y-50],[340,y-10],[340,220],[0,220]],null,1,['#889e89','#758d81','#627b72','#4e665e'][k]);}
    if(i===0){for(let k=0;k<4;k++){const x=32+k*80;path(ctx,[[x,187],[x,92]],'#344b3c',3);path(ctx,[[x-23,110],[x,42],[x+23,110]],'#344b3c',2,'#7e9c76');}}
    if(i===1){path(ctx,[[30,177],[30,61],[62,27],[94,61],[94,177]],'#6b5646',2,'#d6c8ad');path(ctx,[[47,77],[47,65],[77,65],[77,77]],'#6b5646');for(let k=0;k<4;k++)path(ctx,[[35,104+k*18],[88,104+k*18]],'#ae9975',1);}
    if(i===2){ctx.strokeStyle='#435a66';ctx.lineWidth=3;ctx.beginPath();ctx.ellipse(72,172,52,16,0,0,7);ctx.stroke();ctx.beginPath();ctx.ellipse(72,172,40,10,0,0,7);ctx.stroke();path(ctx,[[20,172],[20,193],[124,193],[124,172]],'#435a66',2);}
    if(i===3){path(ctx,[[34,166],[34,86],[91,86],[91,166]],'#5e526e',2,'#ded1d1');path(ctx,[[24,86],[62,54],[101,86]],'#5e526e',2,'#b4a4b7');path(ctx,[[62,56],[62,34]],'#5e526e',2);}
    ctx.strokeStyle='#344b3c';ctx.globalAlpha=.15;for(const [x,y,s] of model.state.panels[i].hatching)path(ctx,[[x,y],[x+s,y-5]],'#344b3c',1);ctx.globalAlpha=1;
  }
  function draw() {
    if(!model) return;
    const time=model.tick*20;
    for(let i=0;i<4;i++) {
      const canvas=document.querySelector(`[data-canvas="${i}"]`),ctx=canvas.getContext('2d');scene(ctx,i);
      // The bounded wake records actual motion, never the hidden future knots.
      if(model.active) for(let ago=600;ago>=100;ago-=100){const p=pose(model.state.panels[i],Math.max(0,time-ago));motif(ctx,model.state.picture_marks[i],...p,'#fbe6b3',.09+(600-ago)/4000);}
      const p=pose(model.state.panels[i],model.active?time:0);
      ctx.fillStyle='#ecd69a';ctx.globalAlpha=.32;ctx.beginPath();ctx.arc(p[0],p[1],p[2],0,7);ctx.fill();ctx.globalAlpha=1;
      motif(ctx,model.state.picture_marks[i],...p,'#51351d');
      const w=model.windows[i],ready=aligned(i,model.active?time:0);
      if(model.layers[i]!==null){const layer=model.layers[i];ctx.fillStyle='#f2eddd';ctx.globalAlpha=.18;ctx.fillRect(w[0]-w[2]-8,w[1]-w[2]-8,2*w[2]+16,2*w[2]+16);ctx.globalAlpha=1;motif(ctx,model.state.picture_marks[layer],...w,ready?'#16614c':'#a1394a');ctx.setLineDash([4,4]);ctx.strokeStyle=ready?'#16614c':'#a1394a';ctx.strokeRect(w[0]-w[2]-8,w[1]-w[2]-8,2*w[2]+16,2*w[2]+16);ctx.setLineDash([]);}
      const node=document.querySelector(`[data-card="${i}"]`);node.dataset.aligned=ready?'true':'false';
      node.dataset.covered=String(!model.uncovered[i]);
      node.querySelector('[data-header] span').textContent=model.uncovered[i]?symbols[model.state.picture_marks[i]]:'▧';
      if(!model.uncovered[i]) {
        // Opaque, task-owned vellum: neither the picture identity nor its
        // matching lantern can be read until the existing lift gesture.
        ctx.fillStyle='#d7c9a6';ctx.fillRect(0,0,340,220);
        ctx.strokeStyle='#aa936a';ctx.strokeRect(10,10,320,200);
        path(ctx,[[300,0],[300,35],[340,35]],'#8c7756',1,'#eee2c7');
        ctx.fillStyle='#584b35';ctx.textAlign='center';ctx.font='18px Georgia';ctx.fillText('LIFT THE VELLUM',170,100);
        ctx.font='12px monospace';ctx.fillText(model.mode==='full'?'RIGHT CLICK TO PEEL':'↥  LIFT BELOW',170,127);ctx.textAlign='start';
      }
      node.querySelector('.fpv-match').textContent=model.layers[i]===null?'NO WINDOW':ready?'LIT':'FADING';
    }
    const route=model.state.route;
    const pathCanvas=document.querySelector('.fpv-road'), ctx=pathCanvas.getContext('2d');ctx.clearRect(0,0,260,140);
    const pts=[[20,110],[90,100],[90,42],[170,42],[170,110],[240,110]];
    const lit=model.slots.every((x,j)=>x===route[j]) && [0,1,2,3].every(i=>aligned(i,model.active?time:0)) && !['burnt','sealed_incomplete'].includes(model.terminal);
    pathCanvas.dataset.lit=String(lit);
    path(ctx,pts,'#575f56',10);path(ctx,pts,lit?'#caa664':'#737b70',3);
    const f=model.progress/model.state.journey_ms*5, k=Math.min(4,Math.floor(f)),frac=f-k;
    const x=pts[k][0]+(pts[k+1][0]-pts[k][0])*frac,y=pts[k][1]+(pts[k+1][1]-pts[k][1])*frac;
    ctx.fillStyle='#f7e7bb';ctx.beginPath();ctx.arc(x,y-12,5,0,7);ctx.fill();path(ctx,[[x,y-7],[x,y+7],[x-7,y+14],[x,y+7],[x+7,y+14]],'#f7e7bb',3);
    ctx.fillStyle='#d5b571';ctx.font='26px Georgia';ctx.fillText('⌂',226,95);
    document.querySelector('.fpv-progress').style.width=`${model.progress/model.state.journey_ms*100}%`;
    document.querySelector('.fpv-time').textContent=model.active?`${Math.ceil(Math.max(0,model.state.burn_ms-time)/1000)}s · ${model.terminal==='arrived'?'AT THE SHRINE':model.terminal?'ENDED':'LIVE'}`:'PREPARE THE FOLIO';
    document.querySelector('.fpv-begin').disabled=model.active||!!model.terminal;
    document.querySelector('.fpv-state').textContent=model.terminal==='arrived'?'SHRINE REACHED · SEAL THE PAGE':model.active?'Keep the ink windows registered.':'Lift the vellum to inspect each picture, then arrange and stack.';
    for(const b of document.querySelectorAll('[data-layer]')) b.dataset.selected=String(Number(b.dataset.layer)===model.selectedLayer);
    for(const h of document.querySelectorAll('[data-header]')) h.dataset.selected=String(Number(h.dataset.header)===model.selectedHeader);
  }
  function layout() {
    for(let slot=0;slot<4;slot++)document.querySelector(`[data-card="${model.slots[slot]}"]`).style.order=slot;
  }
  async function render(state,helpers) {
    document.body.dataset.mechanic='four-pane-pilgrimage-v3-nonrealtime';
    model={state,helpers,mode:state.control_condition?.interaction||'full',events:[],tick:0,progress:0,active:false,terminal:null,slots:[...state.initial_slots],layers:[null,null,null,null],uncovered:[false,false,false,false],windows:[[170,110,44],[170,110,44],[170,110,44],[170,110,44]],drag:null,selectedLayer:null,selectedHeader:null,submitting:false};
   window.fourPanePilgrimageV3NonrealtimeModel=model;
    helpers.app.innerHTML=`<section class="fpv"><header class="fpv-head"><div><small>THE ERRANT FOLIO / LIVING INK</small><h1>Four-Pane Pilgrimage V3</h1></div><div class="fpv-order">${state.route.map(i=>`<span>${symbols[state.picture_marks[i]]}</span>`).join('<b>→</b>')}</div></header><main class="fpv-main"><div class="fpv-board">${[0,1,2,3].map(i=>`<article class="fpv-card" data-card="${i}"><header data-header="${i}"><span>${symbols[state.picture_marks[i]]}</span><b class="fpv-match"></b><em>↔</em></header><canvas width="340" height="220" data-canvas="${i}"></canvas><div class="fpv-scale">${model.mode==='simplified'?`<button data-size="${i},-1">−</button><button data-peel="${i}" aria-label="Lift vellum or window">↥</button><button data-size="${i},1">+</button>`:'<span>DRAG TO PAN · WHEEL TO SCALE · RIGHT CLICK TO LIFT</span>'}</div></article>`).join('')}</div><aside class="fpv-aside"><small>PEELED WINDOWS</small><div class="fpv-tray">${state.tray.map(i=>`<button data-layer="${i}"><span>${symbols[state.picture_marks[i]]}</span><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="37"/><path d="${['M50 27L68 50L50 73L32 50Z','M50 27L69 58H31ZM50 58V73','M31 31L69 69V31L31 69Z','M31 69V45L50 27L69 45V69Z'][state.picture_marks[i]]}"/></svg></button>`).join('')}</div><canvas class="fpv-road" width="260" height="140"></canvas><div class="fpv-meter"><i class="fpv-progress"></i></div><strong class="fpv-time"></strong><p class="fpv-state"></p><p class="fpv-help">${model.mode==='full'?'Drag picture headers into order. Drag a peeled window onto its picture, then pan and wheel.':'Click a header then its destination. Click a window then its picture. Click a chosen position to pan; use −/+ to scale.'} Lift the vellum to reveal each picture’s sigil and lantern. Discovered pictures stay visible. BEGIN activates the journey without consuming a tick. The folio advances one fixed lantern step after each active puzzle control; idle waiting leaves it unchanged. All four matches sustain the illuminated path. A lost match makes the pilgrim retreat. Red windows fade; green windows light. The trail shows the last 0.6 seconds.</p></aside></main><footer><b class="readout"></b><button class="fpv-begin">BEGIN PILGRIMAGE</button><button class="fpv-seal">SEAL THE PAGE</button></footer><div class="fpv-verdict" hidden></div></section>`;
   for(const canvas of document.querySelectorAll('[data-canvas]')) {
      const i=Number(canvas.dataset.canvas);
      canvas.addEventListener('contextmenu',e=>{e.preventDefault();if(model.mode==='full')peel(i,'right_click');});
      canvas.addEventListener('click',e=>{if(model.mode!=='simplified'||model.terminal)return;const p=local(e,canvas);if(model.selectedLayer!==null)stack(model.selectedLayer,i,p,'tray_pair');else pan(i,p,{gesture:'point_click'});});
      canvas.addEventListener('pointerdown',e=>{if(model.mode!=='full'||e.button!==0||model.terminal||model.layers[i]===null)return;e.preventDefault();model.drag={kind:'pan',i,last:local(e,canvas)};canvas.setPointerCapture(e.pointerId);});
      canvas.addEventListener('pointermove',e=>{const d=model.drag;if(d?.kind!=='pan'||d.i!==i)return;const end=local(e,canvas), w=model.windows[i];pan(i,[w[0]+end[0]-d.last[0],w[1]+end[1]-d.last[1]],{start:d.last,end});d.last=end;});
      canvas.addEventListener('wheel',e=>{if(model.mode!=='full'||!e.deltaY)return;e.preventDefault();zoom(i,e.deltaY<0?1:-1,{delta_y:e.deltaY,point:local(e,canvas)});},{passive:false});
      canvas.addEventListener('pointerup',()=>{if(model.drag?.kind==='pan')model.drag=null;});
      canvas.addEventListener('pointercancel',()=>{model.drag=null;});canvas.addEventListener('lostpointercapture',()=>{if(model.drag?.kind==='pan')model.drag=null;});
    }
    for(const head of document.querySelectorAll('[data-header]')) {
      const i=Number(head.dataset.header);
      head.addEventListener('click',()=>{if(model.mode!=='simplified'||model.terminal)return;if(model.selectedHeader===null){model.selectedHeader=i;draw();}else swap(model.selectedHeader,model.slots.indexOf(i),'header_pair');});
      head.addEventListener('pointerdown',e=>{if(model.mode!=='full'||model.terminal||e.button!==0)return;e.preventDefault();model.drag={kind:'header',i};head.setPointerCapture(e.pointerId);});
      head.addEventListener('pointerup',e=>{const d=model.drag;model.drag=null;if(d?.kind!=='header')return;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-header]');if(target)swap(d.i,model.slots.indexOf(Number(target.dataset.header)),'header_drag');});
      head.addEventListener('pointercancel',()=>{model.drag=null;});
    }
    for(const button of document.querySelectorAll('[data-layer]')) {
      const layer=Number(button.dataset.layer);
      button.addEventListener('click',()=>{if(model.mode==='simplified'&&!button.disabled){model.selectedLayer=layer;draw();}});
      button.addEventListener('pointerdown',e=>{if(model.mode!=='full'||model.terminal||button.disabled||e.button!==0)return;e.preventDefault();model.drag={kind:'layer',layer};button.setPointerCapture(e.pointerId);});
      button.addEventListener('pointerup',e=>{const d=model.drag;model.drag=null;if(d?.kind!=='layer')return;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-canvas]');if(target)stack(d.layer,Number(target.dataset.canvas),local(e,target),'tray_drag');});
      button.addEventListener('pointercancel',()=>{model.drag=null;});
    }
    for(const b of document.querySelectorAll('[data-size]'))b.addEventListener('click',()=>{const[i,d]=b.dataset.size.split(',').map(Number);zoom(i,d,{gesture:'scale_button'});});
    for(const b of document.querySelectorAll('[data-peel]'))b.addEventListener('click',()=>peel(Number(b.dataset.peel),'lift_button'));
    document.querySelector('.fpv-begin').addEventListener('click',begin);document.querySelector('.fpv-seal').addEventListener('click',seal);
    layout();draw();
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.four_pane_pilgrimage_v3_nonrealtime={rootSelector:'.fpv',render};
})();
