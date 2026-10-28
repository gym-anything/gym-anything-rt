(() => {
  'use strict';
  let model, raf;
  const esc = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const distance = (a,b) => Math.hypot(a[0]-b[0],a[1]-b[1]);
  function noise(seed,index) {
    let x=(seed^Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function position(item,time) {
    const age=Math.max(0,time-item.spawn_ms), u=age/item.bend_ms, i=Math.floor(u), f=u-i;
    const a=noise(item.motion_seed,i),b=noise(item.motion_seed,i+1);
    return [640+item.drift*(a+(b-a)*(1-Math.cos(f*Math.PI))/2),
      item.protected ? 238+115*Math.sin(age/3100+item.y_phase) : 70+(425-item.radius-70)*age/item.lifetime_ms];
  }
  function snapshotTime(item,step) {
    const n=model.state.nonrealtime;
    const offset=n.preview_offset_ms, advance=n.decision_step_ms;
    return item.protected ? offset+step*advance : item.spawn_ms+offset+step*advance;
  }
  function snapshotPosition(item,step) { return position(item,snapshotTime(item,step)); }
  const active=(item,time) => item.spawn_ms<=time && time<item.spawn_ms+item.lifetime_ms;
  const now=() => Math.round(performance.now()-model.epoch);
  const elapsed=() => model.started===null ? 0 : now()-model.started;
  const source=() => model.mode==='full' ? 'seal_drag' : 'seal_proxy';
  function record(kind,extra={}) { model.events.push({sequence:model.events.length+1,kind,t_ms:now(),input_source:source(),decision_step:model.step,...extra}); }
  function hit(point,step) {
    return [...model.state.wisps,...model.state.echoes].reverse().find(item =>
      !model.saved.has(item.id) && active(item,snapshotTime(item,step)) &&
      distance(point,snapshotPosition(item,step))<=item.radius);
  }
  function sync() {
    // Non-real-time rule: waiting never advances the court.  The only
    // transition is the fixed snapshot step after a deliberate successful
    // cast, so no render loop can expire an opportunity while idle.
  }
  async function finish(reason='') {
    if (model.terminal) return;
    model.terminal=reason ? 'fail' : 'pending'; model.reason=reason; model.finalTime=now();
    model.hold=null; model.selected=null;
    document.querySelector('#cb-judgment').disabled=true;
    document.querySelector('#cb-submit').disabled=true;
    const payload={mechanic_id:model.state.mechanic_id,revision:model.state.revision,
      task_id:model.state.task_id,challenge_id:model.state.challenge_id,interaction_mode:model.mode,
      events:model.events,vows:model.vows,saved_ids:[...model.saved].sort(),completed:!reason,
      failure_reason:reason,final_t_ms:model.finalTime};
    model.payload=payload;
    model.helpers.setReadout(reason ? `FAIL · ${reason}` : 'VERIFYING COVENANTS…',reason?'error':'pending');
    document.querySelector('.cb-v2').dataset.terminal=model.terminal; draw();
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const result=await response.json(); model.grade=result;
      model.terminal=result.passed ? 'pass' : 'fail';
      if (!result.passed && !reason) model.reason=result.feedback || 'Covenant replay failed.';
      document.querySelector('.cb-v2').dataset.terminal=model.terminal;
      model.helpers.setReadout(result.passed ? 'PASS · EVERY COVENANT KEPT' : `FAIL · ${model.reason}`,result.passed?'passed':'error');
      draw();
    } catch(error) {
      model.terminal='error'; model.reason='Verification unavailable.';
      document.querySelector('.cb-v2').dataset.terminal='error';
      model.helpers.setReadout(model.reason,'error'); draw();
    }
  }
  function stagePoint(event) {
    const b=model.canvas.getBoundingClientRect();
    return [(event.clientX-b.left)*1100/b.width,(event.clientY-b.top)*500/b.height];
  }
  function acquire(point,kind) {
    const seal=model.state.seals.find(s => distance(point,[s.x,s.y])<=s.radius);
    if (!seal) return false;
    model.selected=seal.id; record(kind,{point,seal:seal.id}); return true;
  }
  function apply(point,kind) {
    if (!model.selected || model.terminal) return;
    // Captured pointer releases can land beyond the canvas. Preparation is
    // reversible: cancel the drag before recording a geometric application.
    // Active judgment releases still record and fail their actual missed aim.
    if (model.started===null && model.mode==='full' &&
        (point[0]<0 || point[0]>1100 || point[1]<0 || point[1]>500)) {
      record('cancel',{reason:'outside_court'});model.hold=null;model.selected=null;
      model.helpers.setReadout('DRAG CANCELLED · CHOOSE A SEAL AGAIN','idle');draw();return;
    }
    const seal=model.selected;
    record(kind,{point,seal}); model.hold=null; model.selected=null;
    if (model.started===null) {
      const w=model.state.witnesses.find(w => distance(point,[w.x,w.y])<=34);
      if (w) model.vows[w.id]=seal;
      model.helpers.setReadout(`COVENANTS CHOSEN · ${Object.keys(model.vows).length}/${model.state.witnesses.length}`,'idle');
    } else {
      const item=hit(point,model.step);
      if (!item) { finish('Cast missed the current judgment snapshot.'); return; }
      if (item.protected) { finish('A protected white-ring wisp was struck.'); return; }
      if (model.vows[item.witness_id]!==seal) { finish('The cast broke an earlier covenant.'); return; }
      model.saved.add(item.id); model.step+=1;
      model.flash={point,at:now(),seal};
      model.helpers.setReadout(`JUDGMENTS INTERCEPTED · ${model.saved.size}/${model.state.echoes.length}`,'idle');
      if (model.saved.size===model.state.echoes.length) finish();
      else if (model.state.echoes.some(e => !model.saved.has(e.id) && !active(e,snapshotTime(e,model.step)))) {
        finish('A judgment reached the court boundary after the cast.'); return;
      }
    }
    draw();
  }
  function circle(ctx,x,y,r,fill,stroke,width=2) {
    ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();
    if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.stroke();}
  }
  function glyph(ctx,text,x,y,size,color) {
    ctx.fillStyle=color;ctx.font=`${size}px Georgia,serif`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,x,y);
  }
  function draw() {
    if (!model) return;
    const ctx=model.context, step=model.step;
    const s=model.state;
    const bg=ctx.createLinearGradient(0,0,1100,500);bg.addColorStop(0,'#17152c');bg.addColorStop(.6,'#22233b');bg.addColorStop(1,'#152535');
    ctx.fillStyle=bg;ctx.fillRect(0,0,1100,500);
    ctx.strokeStyle='#665b7240';ctx.lineWidth=1;
    for(let x=210;x<1100;x+=90){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,425);ctx.stroke();}
    ctx.fillStyle='#0f1024';ctx.fillRect(0,0,165,500);
    glyph(ctx,'SEALS',80,26,14,'#cfbda9');
    for(const seal of s.seals){
      const color=seal.id==='mercy'?'#97e3e5':'#f5b68a';
      circle(ctx,seal.x,seal.y,seal.radius,'#292c43',color,model.selected===seal.id?5:2);
      glyph(ctx,seal.glyph,seal.x,seal.y,35,color);
      glyph(ctx,seal.id.toUpperCase(),seal.x,seal.y+54,14,color);
    }
    glyph(ctx,'SOLID: LAST 0.6s',80,344,11,'#c4c4d2');
    glyph(ctx,'DASH: NEXT 1.2s',80,365,11,'#c4c4d2');
    glyph(ctx,'DOTS: EACH 0.3s',80,386,11,'#c4c4d2');
    // The boss and architecture are original vector artwork; only moving circles are hit surfaces.
    circle(ctx,640,13,51,'#3c3048','#a78c9a',3);
    glyph(ctx,'◈',620,13,19,'#edcb8d');glyph(ctx,'◈',660,13,19,'#edcb8d');
    ctx.strokeStyle='#e1c5aa';ctx.beginPath();ctx.arc(640,16,26,.12,Math.PI-.12);ctx.stroke();
    if(model.started===null){
      glyph(ctx,'The boss will remember your choices.',640,182,24,'#ead9b8');
      glyph(ctx,'Choose MERCY or REBUKE for every witness below.',640,228,18,'#b8bfd0');
      glyph(ctx,'Their covenants disappear when judgment starts.',640,264,18,'#b8bfd0');
      glyph(ctx,'Match each returning rune with the seal you chose.',640,300,18,'#b8bfd0');
    } else {
      const items=[...s.wisps,...s.echoes];
      for(const item of items){
        const drawTime=snapshotTime(item,step);
        if(model.saved.has(item.id)||!active(item,drawTime)) continue;
        const w=s.witnesses.find(w=>w.id===item.witness_id),p=position(item,drawTime);
        ctx.beginPath();ctx.strokeStyle=item.protected?'#dfedf350':w.color+'65';ctx.lineWidth=3;
        for(let j=0;j<=12;j++){const q=position(item,Math.max(item.spawn_ms,drawTime-s.trail_ms+j*s.trail_ms/12));j?ctx.lineTo(...q):ctx.moveTo(...q);}ctx.stroke();
        // Fine intent thread: the upcoming 1.2 seconds of the same analytic trajectory.
        ctx.beginPath();ctx.setLineDash([4,6]);ctx.lineWidth=2;ctx.strokeStyle=item.protected?'#e0eef344':w.color+'99';
        ctx.moveTo(...p);
        for(let j=1;j<=12;j++){const future=drawTime+j*s.forecast_ms/12;ctx.lineTo(...position(item,future));}
        ctx.stroke();ctx.setLineDash([]);
        for(let j=3;j<=12;j+=3){const future=drawTime+j*s.forecast_ms/12;circle(ctx,...position(item,future),2.5,item.protected?'#edf6ff':w.color);}
        circle(ctx,...p,item.radius,item.protected?'#202d42':'#312738',item.protected?'#edf6ff':w.color,3);
        glyph(ctx,w.glyph,...p,37,item.protected?'#edf6ff':w.color);
        if(item.protected){circle(ctx,...p,item.radius+7,'transparent','#edf6ff',2);}
        else {
          ctx.strokeStyle='#f47885';ctx.lineWidth=3;ctx.beginPath();
          ctx.arc(...p,item.radius-6,-Math.PI/2,-Math.PI/2+2*Math.PI*Math.max(0,1-(drawTime-item.spawn_ms)/item.lifetime_ms));ctx.stroke();
        }
      }
    }
    ctx.fillStyle='#1a1428';ctx.fillRect(165,425,935,75);
    ctx.strokeStyle='#c89879';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(165,425);ctx.lineTo(1100,425);ctx.stroke();
    for(const w of s.witnesses){
      circle(ctx,w.x,w.y,34,'#302537',w.color,2);glyph(ctx,w.glyph,w.x,w.y,31,w.color);
      if(model.started===null && model.vows[w.id]) glyph(ctx,model.vows[w.id]==='mercy'?'◯':'↑',w.x,w.y-59,27,'#f3edd9');
    }
    if(model.hold && model.pointer){circle(ctx,...model.pointer,21,'#e5d6bb66','#f4e4c6',2);glyph(ctx,model.selected==='mercy'?'◯':'↑',...model.pointer,25,'#fff3d6');}
    if(model.flash && now()-model.flash.at<400) circle(ctx,...model.flash.point,40,'#a0f2df22','#a0f2df',2);
    if(model.terminal){
      ctx.fillStyle='#0c101bdf';ctx.fillRect(275,162,735,146);
      glyph(ctx,model.terminal==='pass'?'COVENANTS KEPT':model.terminal==='pending'?'VERIFYING':model.terminal==='fail'?'EPISODE ENDED':'VERIFICATION ERROR',640,205,30,model.terminal==='pass'?'#a8efd2':'#ffb2ad');
      glyph(ctx,model.terminal==='pass'?'PASS':model.reason || 'Judgment complete.',640,263,20,'#ead8c5');
    }
  }
  function animate(){sync();draw();}
  async function render(state,helpers){
    cancelAnimationFrame(raf);
    document.body.dataset.mechanic='consequences-boss-nonrealtime';
    model={state,helpers,mode:state.control_condition?.interaction||'full',epoch:performance.now(),started:null,
      events:[],vows:{},saved:new Set(),selected:null,hold:null,terminal:null,reason:'',pointer:null,step:0};
    window.consequencesBossNonRealtimeModel=model;
    helpers.app.innerHTML=`<section class="cb-v2" data-interaction="${esc(model.mode)}" data-terminal="active">
      <header class="cb-head"><div><p>THE COVENANT COURT / ONE JUDGMENT</p><h1>Consequences Boss V2</h1></div><span class="cb-mode">${esc(model.mode.toUpperCase())}</span></header>
      <p class="cb-rules">${model.mode==='full'?'Drag a seal to a witness, then drag that seal onto each matching judgment rune.':'Click a seal, then a witness; during judgment, select the seal and click the matching rune.'}<br>Keep your choice. Protect white-ring wisps. Each successful cast advances one fixed court snapshot; waiting preserves the current snapshot. A missed cast, broken covenant, protected-wisp strike, action-triggered impact or rejected SUBMIT ends the episode. Threads forecast the analytic path.</p>
      <canvas id="cb-arena" width="1100" height="500" aria-label="Covenant court and moving judgment echoes"></canvas>
      <footer class="cb-foot"><div class="readout">CHOOSE EVERY COVENANT</div><button id="cb-judgment" type="button">START JUDGMENT</button><button id="cb-submit" type="button">SUBMIT</button></footer></section>`;
    model.canvas=document.querySelector('#cb-arena');model.context=model.canvas.getContext('2d');
    model.canvas.addEventListener('pointerdown',event=>{
      sync();if(model.terminal||event.button!==0||model.mode!=='full')return;
      const p=stagePoint(event);if(acquire(p,'seal_down')){model.hold=event.pointerId;model.pointer=p;model.canvas.setPointerCapture(event.pointerId);event.preventDefault();draw();}
    });
    model.canvas.addEventListener('pointermove',event=>{if(model.hold===event.pointerId){model.pointer=stagePoint(event);draw();}});
    model.canvas.addEventListener('pointerup',event=>{
      sync();if(model.terminal||model.hold!==event.pointerId)return;
      model.canvas.releasePointerCapture(event.pointerId);apply(stagePoint(event),'seal_up');event.preventDefault();
    });
    const cancel=event=>{if(model.hold!==null&&!model.terminal){record('cancel');model.hold=null;model.selected=null;draw();}};
    model.canvas.addEventListener('pointercancel',cancel);
    model.canvas.addEventListener('lostpointercapture',()=>{
      // Normal release clears the hold synchronously before this deferred event.
      if(model.hold!==null&&!model.terminal){record('cancel');model.hold=null;model.selected=null;draw();}
    });
    model.canvas.addEventListener('click',event=>{
      sync();if(model.terminal||model.mode!=='simplified')return;
      const p=stagePoint(event);if(!acquire(p,'select'))apply(p,'apply');draw();
    });
    document.querySelector('#cb-judgment').addEventListener('click',()=>{
      if(model.terminal||model.started!==null)return;
      if(model.hold!==null||Object.keys(model.vows).length!==state.witnesses.length){helpers.setReadout('CHOOSE A COVENANT FOR EVERY WITNESS','pending');return;}
      record('start',{input_source:'judgment_button'});model.started=now();model.step=0;model.selected=null;
      document.querySelector('#cb-judgment').disabled=true;helpers.setReadout('JUDGMENT SNAPSHOT READY','idle');draw();
    });
    document.querySelector('#cb-submit').addEventListener('click',()=>{sync();if(!model.terminal)finish('Judgment incomplete.');});
    draw();
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.consequences_boss_nonrealtime={rootSelector:'.cb-v2',render};
})();
