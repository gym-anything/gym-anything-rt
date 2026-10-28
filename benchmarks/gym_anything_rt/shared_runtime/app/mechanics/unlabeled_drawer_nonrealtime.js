(() => {
  'use strict';
  let model, frame = 0;
  const palettes = ['#de8c63','#7fb5ae','#b298c5','#c7ad68'];
  const clean = x => String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  // Wall time may pass between actions, but the counterpart has no
  // autonomous task clock: every event lands at the same stable state.
  const now = () => 0;
  const inside = (p,c,w,h) => Math.abs(p[0]-c[0])<=w/2 && Math.abs(p[1]-c[1])<=h/2;
  function noise(seed,index) {
    let x=(seed ^ Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function drawerPosition(d,t) { return [480+d.amplitude*noise(d.seed,0),d.y]; }
  function cargoPosition(s,t) { return s.stable_center; }
  const age = () => 0;
  function record(kind,more={}) { model.events.push({sequence:model.events.length+1,kind,t_ms:model.ms,...more}); }
  function activeCargo() {
    return model.state.cargo.filter(s => !(s.id in model.filed));
  }
  function sync() {
    if (model.terminal) return;
    model.ms=now();
    // Specimens do not expire and the page does not advance task time.
  }
  function specimenArt(c,s,x,y,scale=1) {
    const [hollow,spined,paired,crossed]=s.features;
    c.save();c.translate(x,y);c.rotate(s.style.angle*Math.PI/180);c.scale(scale*s.style.scale,scale*s.style.scale);
    c.fillStyle=palettes[s.style.palette];c.strokeStyle='#172d2e';c.lineWidth=2.5;
    c.beginPath();
    if (spined) for(let i=0;i<24;i++) {const a=i*Math.PI/12,r=i%2?23:29;const px=Math.cos(a)*r,py=Math.sin(a)*r;i?c.lineTo(px,py):c.moveTo(px,py);}
    else c.ellipse(0,0,27,24,0,0,Math.PI*2);
    c.closePath();c.fill();c.stroke();
    c.strokeStyle='#1a3535';c.lineWidth=3;
    c.beginPath();
    if(crossed) {c.moveTo(-17,-15);c.lineTo(17,15);c.moveTo(17,-15);c.lineTo(-17,15);}
    else {c.moveTo(-17,-11);c.lineTo(17,-11);c.moveTo(-17,11);c.lineTo(17,11);}
    c.stroke();
    c.fillStyle='#f1d68d';c.strokeStyle='#172d2e';c.beginPath();c.arc(0,0,11,0,Math.PI*2);c.fill();c.stroke();
    if(hollow) {c.fillStyle='#183436';c.beginPath();c.arc(0,0,6,0,Math.PI*2);c.fill();}
    c.fillStyle='#f1d68d';
    for(const dx of paired?[-39,39]:[-39]) {c.beginPath();c.arc(dx,0,6.5,0,Math.PI*2);c.fill();c.stroke();}
    c.restore();
  }
  function card(c,s,center,selected=false) {
    c.fillStyle=selected?'#f3d48b':'#eadcbb';c.strokeStyle=selected?'#f3dc9c':'#8e7651';c.lineWidth=selected?3:1;
    c.fillRect(center[0]-s.width/2,center[1]-s.height/2,s.width,s.height);
    c.strokeRect(center[0]-s.width/2,center[1]-s.height/2,s.width,s.height);
    specimenArt(c,s,center[0],center[1]-3,s.height===64?.82:1);
    c.fillStyle='#173537';c.font='bold 10px monospace';c.textAlign='center';c.fillText(s.id,center[0],center[1]+s.height/2-5);
  }
  function draw() {
    const c=model.canvas.getContext('2d'),s=model.state;
    c.fillStyle='#123032';c.fillRect(0,0,960,560);
    c.strokeStyle='#ffffff09';c.lineWidth=1;
    for(let x=20;x<960;x+=32) {c.beginPath();c.moveTo(x,0);c.lineTo(x,560);c.stroke();}
    c.font='bold 11px monospace';c.textAlign='left';c.fillStyle='#b2c5b6';
    if(model.runAt===null) {
      c.fillText('CALIBRATION BANK · TEST ANY SPECIMEN',48,12);
      for(const p of s.probes) card(c,p,p.center,model.selected===p.id);
      const [x,y,w,h]=s.probe_slot;
      c.fillStyle='#091f22';c.fillRect(x-w/2,y-h/2,w,h);c.strokeStyle='#c9a767';c.strokeRect(x-w/2,y-h/2,w,h);
      c.textAlign='center';c.fillStyle='#e4c782';c.font='bold 15px monospace';c.fillText('TEST SLOT',x,y-12);
      c.font='12px monospace';c.fillText(model.mode==='full'?'DROP FILING TAB':'CLICK AFTER SELECTING',x,y+17);
      c.fillStyle='#afc7bf';c.font='11px monospace';c.fillText('The cabinet returns a drawer letter.',x,y+42);
    } else {
      c.fillText('STABLE BELT · HOLDING A TAB DOES NOT CHANGE THE LAYOUT',48,12);
      for(let lane=0;lane<s.parameters.lanes;lane++) {
        const y=70+90*lane;c.fillStyle='#234649';c.fillRect(16,y-43,910,86);
        c.strokeStyle='#758c7650';c.beginPath();c.moveTo(18,y+40);c.lineTo(924,y+40);c.stroke();
        c.fillStyle='#74908b';c.font='18px monospace';c.textAlign='left';c.fillText('→',26,y+7);
      }
      c.fillStyle='#8da69a';c.fillRect(946,26,3,263);c.font='bold 10px monospace';c.textAlign='right';c.fillText('BELT EDGE',940,285);
      for(const item of activeCargo()) card(c,item,cargoPosition(item,age()),model.selected===item.id);
    }
    // Seeded geometry is intentionally held at the donor's first position.
    for(const d of s.drawers) {
      const p=drawerPosition(d,age());
      c.strokeStyle='#69817b';c.lineWidth=2;c.beginPath();c.moveTo(80,d.y);c.lineTo(900,d.y);c.stroke();
      c.fillStyle='#091d1f';c.fillRect(p[0]-d.width/2,p[1]-d.height/2,d.width,d.height);
      c.strokeStyle='#dfbd78';c.lineWidth=3;c.strokeRect(p[0]-d.width/2,p[1]-d.height/2,d.width,d.height);
      c.fillStyle='#f3daa0';c.font='bold 22px Georgia';c.textAlign='center';c.fillText(d.label,p[0],p[1]+8);
      c.fillStyle='#b6cbb7';c.font='11px monospace';c.textAlign='left';c.fillText('DRAWER '+d.label,20,d.y+4);
    }
    if(model.hold) {
      const p=model.pointer,item=[...s.probes,...s.cargo].find(v=>v.id===model.selected);
      const anchor=model.runAt===null?item.center:cargoPosition(item,age());
      c.strokeStyle='#f2cb7a';c.setLineDash([5,5]);c.beginPath();c.moveTo(...anchor);c.lineTo(...p);c.stroke();c.setLineDash([]);
      c.fillStyle='#f2cb7a';c.fillRect(p[0]-27,p[1]-14,54,28);c.fillStyle='#1a3434';c.textAlign='center';c.font='bold 12px monospace';c.fillText(item.id,p[0],p[1]+4);
    }
    if(model.terminal) {
      c.fillStyle='#07191ce0';c.fillRect(0,0,960,560);c.textAlign='center';c.fillStyle=model.completed?'#aadeba':'#f3aa83';
      c.font='bold 76px Georgia';c.fillText(model.completed?'FILED':'FAIL',480,252);
      c.font='bold 16px monospace';c.fillText(model.reason || 'ALL SPECIMENS IN THEIR DRAWERS',480,302);
      c.font='13px monospace';c.fillText('CASE CLOSED',480,340);
    }
    document.getElementById('ud2-progress').textContent=`${Object.keys(model.filed).length} / ${s.cargo.length} FILED`;
  }
  function updateLedger() {
    const container=document.getElementById('ud2-ledger');container.replaceChildren();
    for(const p of model.state.probes) if(p.id in model.tested) {
      const article=document.createElement('article'),canvas=document.createElement('canvas');canvas.width=100;canvas.height=64;
      const c=canvas.getContext('2d');c.fillStyle='#efe0bc';c.fillRect(0,0,100,64);specimenArt(c,p,50,30,.8);
      const label=document.createElement('b');label.textContent=`${p.id} → ${String.fromCharCode(65+model.tested[p.id])}`;
      article.append(canvas,label);container.append(article);
    }
  }
  async function finish(completed,reason='') {
    if(model.terminal) return;
    model.ms=now();model.terminal=true;model.completed=completed;model.reason=reason;model.hold=null;model.selected=null;
    if(!completed) sessionStorage.setItem('ud2-failed:'+model.state.task_id,'true');
    document.getElementById('ud2-start').disabled=true;
    document.getElementById('ud2-seal').disabled=true;
    model.helpers.setReadout(completed?'VERIFYING FILES…':`FAIL · ${reason}` ,completed?'pending':'error');draw();
    const payload={mechanic_id:model.state.mechanic_id,revision:model.state.revision,task_id:model.state.task_id,
      challenge_id:model.state.challenge_id,interaction_mode:model.mode,events:model.events,filed:model.filed,tested:model.tested,
      completed,final_t_ms:model.ms};
    model.payload=payload;
    try {
      const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const verdict=await r.json();model.verdict=verdict;
      if(verdict.passed===true) model.helpers.setReadout('PASS · CABINET VERIFIED','passed');
      else {model.completed=false;model.reason ||= 'CABINET REJECTED THE RECORD';sessionStorage.setItem('ud2-failed:'+model.state.task_id,'true');model.helpers.setReadout('FAIL · '+model.reason,'error');}
      draw();
    } catch(e) {model.helpers.setReadout('VERIFIER UNAVAILABLE','error');}
  }
  function point(e) {
    const r=model.canvas.getBoundingClientRect();return [Math.round((e.clientX-r.x)*960/r.width*1000)/1000,Math.round((e.clientY-r.y)*560/r.height*1000)/1000];
  }
  function choose(p) {
    const items=model.runAt===null?model.state.probes:activeCargo();
    const item=items.find(s=>inside(p,model.runAt===null?s.center:cargoPosition(s,age()),s.width,s.height));
    if(!item) return false;
    model.selected=item.id;record(model.mode==='full'?'grab':'select',{specimen_id:item.id,point:p,input_source:model.mode==='full'?'tab_drag':'specimen_click'});
    return true;
  }
  function release(p) {
    const identifier=model.selected;
    if(!identifier) return;
    const source=model.mode==='full'?'tab_release':'destination_click';
    const details={specimen_id:identifier,point:p,input_source:source};
    if(model.runAt===null) {
      const q=model.state.probe_slot;
      if(inside(p,q,q[2],q[3])) {
        const drawer=model.state.runtime_probe_answers[identifier];
        record('probe',{...details,drawer_id:drawer});model.tested[identifier]=drawer;updateLedger();
        model.helpers.setReadout(`${identifier} → DRAWER ${String.fromCharCode(65+drawer)}`,'idle');
      } else record('cancel',details);
    } else {
      const drawer=model.state.drawers.find(d=>inside(p,drawerPosition(d,0),d.width,d.height));
      if(drawer) {
        record('file',{...details,drawer_id:drawer.id});
        if(model.state.runtime_final_answers[identifier]!==drawer.id) {finish(false,`${identifier} FILED IN THE WRONG DRAWER`);return;}
        model.filed[identifier]=drawer.id;model.helpers.setReadout(`${identifier} FILED · KEEP TRACKING`,'idle');
      } else if(p[1]>=296) {record('miss',details);finish(false,`${identifier} MISSED THE CABINET MOUTH`);return;}
      else {record('cancel',details);model.helpers.setReadout('TAB RETURNED TO BELT · BELT STILL RUNNING','idle');}
    }
    model.selected=null;model.hold=null;
    if(Object.keys(model.filed).length===model.state.cargo.length) finish(true);
  }
  async function render(state,helpers) {
    cancelAnimationFrame(frame);
    document.body.dataset.mechanic='unlabeled-drawer-v2';
    const mode=state.control_condition?.interaction || 'full';
    const family={literal:'One attribute chooses between two drawers.',relation:'One unknown pair chooses by MATCH versus DIFFER.',
      two_bits:'Two unknown attributes jointly choose four drawers.',two_relations:'Four attributes form two unknown pairs. Their MATCH / DIFFER relations jointly choose four drawers.'}[state.parameters.family];
    helpers.app.innerHTML=`<section class="ud2-root" data-interaction="${mode}"><header class="ud2-head"><div class="ud2-emblem">UD</div><div><small>DEPARTMENT OF IMPOSSIBLE NATURAL HISTORY</small><h1>The Unlabeled Drawer V2</h1></div><div><b>ANNEX IV</b><small>${mode.toUpperCase()} · D${state.control_condition?.difficulty || 5}</small></div></header>
      <main class="ud2-main"><canvas id="ud2-stage" width="960" height="560" aria-label="Specimen bank, stable belt and fixed drawer mouths"></canvas>
      <aside class="ud2-archive"><h2>THE CABINET'S RULE</h2><p>${family} Learn the drawer assignment by testing specimens before starting.</p><p>Colour, scale and rotation do not affect filing. After START BELT, every specimen and drawer mouth stays at a stable visible position until you act.</p><p>A release into the cabinet must hit the correct mouth. A miss ends the case. Release back onto the belt to cancel safely.</p><div class="ud2-legend">${state.feature_legend.map((text,i)=>`<span>${['CORE','RIM','SATELLITES','VEINS'][i]} · ${clean(text)}</span>`).join('')}</div><h2>CALIBRATION RECORDS</h2><div id="ud2-ledger"></div></aside></main>
      <footer class="ud2-foot"><div><b id="ud2-progress">0 / 8 FILED</b><small>${mode==='full'?'DRAG A FILING TAB INTO A MOUTH':'CLICK A SPECIMEN, THEN A MOUTH'} · RETURN TO BELT TO CANCEL</small></div><div class="readout">TEST THE RULE BEFORE STARTING</div><button id="ud2-start">START BELT</button><button id="ud2-seal">SEAL CASE</button></footer></section>`;
    model={state,helpers,mode,canvas:document.getElementById('ud2-stage'),ms:0,runAt:null,
      events:[],tested:{},filed:{},selected:null,hold:null,pointer:[0,0],terminal:false,completed:false,reason:''};
    window.unlabeledDrawerV2Model=model;
    model.canvas.addEventListener('pointerdown',e=>{
      if(e.button!==0 || model.terminal || model.hold) return;sync();if(model.terminal)return;e.preventDefault();
      const p=point(e);
      if(model.mode==='full') {if(choose(p)) {model.hold=e.pointerId;model.pointer=p;model.canvas.setPointerCapture(e.pointerId);}}
      else {
        const items=model.runAt===null?state.probes:activeCargo();
        if(items.some(s=>inside(p,model.runAt===null?s.center:cargoPosition(s,age()),s.width,s.height))) choose(p);
        else release(p);
      }
      draw();
    });
    model.canvas.addEventListener('pointermove',e=>{if(model.hold!==e.pointerId || model.terminal)return;sync();if(model.terminal)return;model.pointer=point(e);draw();});
    model.canvas.addEventListener('pointerup',e=>{
      if(model.hold!==e.pointerId || model.terminal)return;sync();if(model.terminal)return;
      release(point(e));model.canvas.releasePointerCapture(e.pointerId);draw();
    });
    const interruptDrag=e=>{
      if(model.hold!==e.pointerId || model.terminal)return;sync();if(model.terminal)return;
      record('abort',{specimen_id:model.selected,point:model.pointer,input_source:'tab_release'});
      model.selected=null;model.hold=null;
      helpers.setReadout(model.runAt===null?'TAB RETURNED TO CALIBRATION BANK':'TAB RETURNED TO BELT · BELT IS STABLE','idle');draw();
    };
    model.canvas.addEventListener('pointercancel',interruptDrag);
    // Capture loss delivers no committed tab release. Normal pointerup has
    // already cleared the held tab, so its implicit capture loss is a no-op.
    model.canvas.addEventListener('lostpointercapture',interruptDrag);
    document.getElementById('ud2-start').addEventListener('click',()=>{
      if(model.terminal || model.runAt!==null || model.selected)return;sync();if(model.terminal)return;
      record('start',{input_source:'start_button'});model.runAt=model.ms;document.getElementById('ud2-start').disabled=true;
      helpers.setReadout('BELT SET · MISS OR WRONG FILE ENDS THE CASE','idle');draw();
    });
    document.getElementById('ud2-seal').addEventListener('click',()=>{if(!model.terminal) {sync();finish(false,'CASE SEALED BEFORE ALL FILES ARRIVED');}});
    if(state.episode_failed || state.episode_history_error || sessionStorage.getItem('ud2-failed:'+state.task_id)==='true') {
      model.terminal=true;model.reason=state.episode_history_error || 'PRIOR FAILURE · CASE REMAINS CLOSED';helpers.setReadout(state.episode_history_error || 'FAIL · CASE CLOSED','error');
      document.getElementById('ud2-start').disabled=true;document.getElementById('ud2-seal').disabled=true;
    }
    function animate() {sync();draw();frame=requestAnimationFrame(animate);} draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.unlabeled_drawer_nonrealtime={rootSelector:'.ud2-root',render};
  window.UnlabeledDrawerV2Geometry={noise,drawerPosition,cargoPosition};
})();
