(() => {
  "use strict";
  let model, raf = 0;
  const colors = {cyan:"#0788a2", magenta:"#bc346f", amber:"#b98213"};
  const esc = x => String(x).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll('"',"&quot;");
  const distance = (a,b) => Math.hypot(a[0]-b[0],a[1]-b[1]);
  const symbol = mark => mark==="dot"?"●":"◆";
  function target(plate,t) {
    const u=Math.max(0,t)+plate.phase_ms,times=plate.node_times_ms;
    let i=0;while(i<times.length-2 && u>=times[i+1])i++;
    const f=Math.min(1,(u-times[i])/(times[i+1]-times[i])),s=f*f*(3-2*f);
    return plate.nodes[i].map((v,j)=>v+(plate.nodes[i+1][j]-v)*s);
  }
  function time() {return model.started ? Math.min(model.state.press.duration_ms,Math.max(0,Math.floor(performance.now()-model.startedAt))) : 0;}
  function record(kind,details={}) {model.events.push({sequence:model.events.length+1,kind,t_ms:time(),input_source:model.mode,...details});}
  function advance() {
    if (!model.started || model.ended) return;
    const p=model.state.press, end=Math.floor(time()/p.tick_ms)*p.tick_ms;
    while (!model.ended && model.t_ms<end) {
      model.t_ms+=p.tick_ms;
      let worst=0;
      p.plates.forEach((plate,i)=>{
        const alpha=1-Math.exp(-p.tick_ms/p.servo_ms);
        for(let j=0;j<2;j++) model.positions[i][j]+=(model.goals[i][j]-model.positions[i][j])*alpha;
        const error=distance(model.positions[i],target(plate,model.t_ms));
        worst=Math.max(worst,Math.min(1,Math.max(0,(error-p.tolerance)/p.tolerance)));
      });
      model.spoil_ms+=worst*p.tick_ms;
      if(worst===0)model.clean_ms+=p.tick_ms;
      if(model.spoil_ms>=p.spoil_limit_ms) {model.ended=true;model.failed=true;model.failureReason="PAPER SPOILED";}
      else if(model.clean_ms>=p.required_clean_ms)model.ended=true;
      else if(model.t_ms===p.duration_ms){model.ended=true;model.failed=true;model.failureReason="PRESS TIME EXPIRED";}
    }
  }
  function mark(c,kind,x,y,r) {
    c.beginPath();
    if(kind==="dot")c.arc(x,y,r,0,Math.PI*2);
    else{c.moveTo(x,y-r);c.lineTo(x+r,y);c.lineTo(x,y+r);c.lineTo(x-r,y);c.closePath();}
    c.fill();
  }
  function guide(plate,kind,t) {
    const q=target(plate,t);
    return kind===plate.register_mark?q:[300-q[0],200-q[1]];
  }
  function drawSleeve(plate,i) {
    const canvas=document.querySelector(`[data-sleeve="${plate.id}"]`),c=canvas.getContext("2d"),p=model.state.press;
    c.fillStyle="#b2a78d";c.fillRect(0,0,300,64);
    c.strokeStyle="#817860";c.lineWidth=1;
    for(let x=-64;x<364;x+=12){c.beginPath();c.moveTo(x,0);c.lineTo(x+64,64);c.stroke();}
    const reveal=()=>{c.fillStyle="#f4ecd6";c.fillRect(0,0,300,64);c.fillStyle="#243b34";mark(c,plate.register_mark,plate.stamp_x,32,p.stamp_radius);};
    if(model.inspected[i])reveal();
    else if(model.loupe?.i===i){c.save();c.beginPath();c.arc(...model.loupe.point,p.loupe_radius,0,Math.PI*2);c.clip();reveal();c.restore();
      c.strokeStyle="#fff7db";c.lineWidth=2;c.beginPath();c.arc(...model.loupe.point,p.loupe_radius,0,Math.PI*2);c.stroke();}
    const label=canvas.parentNode.querySelector(".sleeve-status");
    label.textContent=model.inspected[i]?`${symbol(plate.register_mark)} REGISTER STAMP · KEEP THIS GUIDE`:"COVERED PLATE SLEEVE · SWEEP LOUPE";
  }
  function draw() {
    const p=model.state.press;
    p.plates.forEach((plate,i)=>{
      const canvas=document.querySelector(`[data-pad="${plate.id}"]`),c=canvas.getContext("2d"),q=target(plate,model.t_ms),pos=model.positions[i],goal=model.goals[i];
      c.clearRect(0,0,300,200);c.fillStyle="#eee9dc";c.fillRect(0,0,300,200);
      c.strokeStyle="#c5bcac";c.lineWidth=1;
      for(let x=30;x<=270;x+=30){c.beginPath();c.moveTo(x,28);c.lineTo(x,172);c.stroke();}
      for(let y=40;y<=160;y+=30){c.beginPath();c.moveTo(28,y);c.lineTo(272,y);c.stroke();}
      c.strokeStyle="#847969";c.strokeRect(28,28,244,144);
      c.strokeStyle="#52483c";c.lineWidth=2;c.strokeRect(goal[0]-5,goal[1]-5,10,10);
      c.beginPath();c.moveTo(...pos);c.lineTo(...goal);c.strokeStyle="#52483c80";c.stroke();
      c.beginPath();c.arc(...pos,p.handle_radius,0,Math.PI*2);c.fillStyle=colors[plate.color];c.fill();
      c.strokeStyle="#fff8e8";c.lineWidth=2;c.beginPath();c.moveTo(pos[0]-7,pos[1]);c.lineTo(pos[0]+7,pos[1]);c.moveTo(pos[0],pos[1]-7);c.lineTo(pos[0],pos[1]+7);c.stroke();
      // Both guides have identical cues. Only sleeve inspection distinguishes
      // the ink-side fiducial from its reflected ghost; draw order is fixed.
      for(const kind of ["dot","diamond"]){
        const q=guide(plate,kind,model.t_ms);
        c.strokeStyle="#53665c";c.lineWidth=2;c.globalAlpha=.6;c.beginPath();
        for(let dt=-600;dt<=0;dt+=50){const a=guide(plate,kind,Math.max(0,model.t_ms+dt));dt===-600?c.moveTo(...a):c.lineTo(...a);}c.stroke();c.globalAlpha=1;
        c.setLineDash([3,5]);c.beginPath();
        for(let dt=0;dt<=p.preview_ms;dt+=50){const a=guide(plate,kind,model.t_ms+dt);dt===0?c.moveTo(...a):c.lineTo(...a);}
        c.strokeStyle="#fff9e7";c.lineWidth=3;c.stroke();c.strokeStyle="#173934";c.lineWidth=1;c.stroke();c.setLineDash([]);
        c.beginPath();c.arc(...q,p.tolerance,0,Math.PI*2);c.strokeStyle="#173934";c.lineWidth=3;c.stroke();c.strokeStyle="#fff9e7";c.lineWidth=1;c.stroke();
        c.beginPath();c.arc(...guide(plate,kind,model.t_ms+p.preview_ms),4,0,Math.PI*2);c.fillStyle="#fff9e7";c.fill();c.strokeStyle="#173934";c.lineWidth=2;c.stroke();
        c.fillStyle="#fff9e7";c.fillRect(q[0]-9,q[1]-p.tolerance-24,18,18);c.fillStyle="#173934";mark(c,kind,q[0],q[1]-p.tolerance-15,5);
      }
      const label=canvas.parentNode.querySelector(".plate-status");
      label.textContent=model.inspected[i]?(distance(pos,q)<=p.tolerance?"IN REGISTER":"COLOR SEPARATING"):"REGISTER STAMP STILL CONCEALED";
      label.dataset.good=String(model.inspected[i]&&distance(pos,q)<=p.tolerance);
      drawSleeve(plate,i);
    });
    const c=document.querySelector(".wth-proof").getContext("2d");
    c.fillStyle="#f3ecd9";c.fillRect(0,0,920,180);c.font="bold 90px Georgia,serif";c.textAlign="center";c.textBaseline="middle";
    c.strokeStyle="#c1b8a4";c.lineWidth=1;[...p.token].forEach((letter,k)=>c.strokeText(letter,280+k*90,90));
    c.globalCompositeOperation="multiply";
    p.plates.forEach((plate,i)=>{if(!model.inspected[i])return;const q=target(plate,model.t_ms),a=model.positions[i],ex=a[0]-q[0],ey=a[1]-q[1];c.fillStyle=colors[plate.color];c.globalAlpha=.7;
      [...p.token].forEach((letter,k)=>{c.save();c.translate(280+k*90+ex,90+ey+p.warp*ex*Math.sin(k*.9));c.rotate(p.warp*ey*.002);c.fillText(letter,0,0);c.restore();});});
    c.globalCompositeOperation="source-over";c.globalAlpha=1;
    const covered=model.inspected.filter(x=>!x).length;
    if(covered){c.fillStyle="#eee6ce";c.fillRect(0,142,920,38);c.fillStyle="#31443a";c.font="16px ui-monospace,monospace";c.fillText(`${covered} PLATE PROOF${covered===1?"":"S"} COVERED · INSPECT SLEEVES BELOW`,460,160);}
    document.querySelector(".wth-paper i").style.width=`${100*model.clean_ms/p.required_clean_ms}%`;
    document.querySelector(".wth-spoil i").style.width=`${Math.min(100,100*model.spoil_ms/p.spoil_limit_ms)}%`;
    document.querySelector(".wth-spoil b").textContent=`${Math.min(100,100*model.spoil_ms/p.spoil_limit_ms).toFixed(0)}%`;
    document.querySelector(".wth-paper b").textContent=`${(Math.ceil(Math.max(0,p.required_clean_ms-model.clean_ms)/100)/10).toFixed(1)} s`;
    document.querySelector(".wth-clock b").textContent=`${(Math.ceil(Math.max(0,p.duration_ms-model.t_ms)/100)/10).toFixed(1)} s`;
    document.querySelector(".wth-start").disabled=model.started||model.ended;
    document.querySelector(".wth-submit").disabled=model.submitted;
  }
  async function finish() {
    if(model.submitted)return;
    advance();model.submitted=true;
    if(!model.ended){model.failed=true;model.failureReason="ENDED EARLY";}
    model.ended=true;
    document.querySelector(".wth-start").disabled=true;
    document.querySelector(".wth-submit").disabled=true;
    record("finish");
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      interaction_mode:model.mode,events:model.events,completed:!model.failed,final_t_ms:model.events[model.events.length-1].t_ms};
    const failureLabel=`FAIL · ${model.failureReason||"PRINT REJECTED"}`;
    model.helpers.setReadout(model.failed?failureLabel:"VERIFYING PRINT",model.failed?"error":"pending");
    try {
      const response=await fetch("/result",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
      const outcome=await response.json();model.outcome=outcome;
      const passed=outcome.passed===true;model.helpers.setReadout(passed?"PASS · CLEAN PRINT":"FAIL · PRINT REJECTED",passed?"passed":"error");
      const stamp=document.querySelector(".wth-stamp");stamp.hidden=false;stamp.dataset.passed=String(passed);
      stamp.textContent=passed?"PASS · CLEAN PRINT":failureLabel;
      document.querySelector(".wth-submit").disabled=true;
    }catch(error){model.helpers.setReadout("VERIFIER ERROR", "error");model.error=String(error);}
  }
  function coordinate(event,canvas) {
    const r=canvas.getBoundingClientRect(),p=model.state.press;
    return [Math.max(p.bounds[0],Math.min(p.bounds[1],(event.clientX-r.left)*300/r.width)),Math.max(p.bounds[2],Math.min(p.bounds[3],(event.clientY-r.top)*200/r.height))].map(v=>Math.round(v*10000)/10000);
  }
  function set(i,point) {
    if(model.state.press.axes===1)point=[point[0],100];
    model.goals[i]=point;record("set",{plate_id:model.state.press.plates[i].id,point});
    if(!model.started)model.positions[i]=point.slice();
  }
  function animate() {
    if(!model)return;advance();draw();
    if(model.ended&&!model.submitted)finish();
    raf=requestAnimationFrame(animate);
  }
  function render(state,helpers) {
    cancelAnimationFrame(raf);document.body.dataset.mechanic="drifting-letterpress";
    const press=state.press;
    model={state,helpers,mode:state.control_condition.interaction,events:[],started:false,ended:false,failed:false,submitted:false,drag:null,t_ms:0,spoil_ms:0,clean_ms:0,
      positions:press.plates.map(p=>p.initial.slice()),goals:press.plates.map(p=>p.initial.slice()),inspected:press.plates.map(()=>false),loupe:null};
    window.wonkyTextHostileRenderingV3Model=model;
    helpers.app.innerHTML=`<section class="wth-game"><header><small>ANAMORPHIC TYPE FOUNDRY · LIVE REGISTRATION</small><h1>Wonky Text Under Hostile Rendering V3</h1></header>
      <p class="wth-rules">${esc(state.prompt)} ${model.mode==="full"?"Drag each solid handle to steer its plate.":"Click a plate pad to command its handle position."}</p>
      <div class="wth-proof-wrap"><canvas class="wth-proof" width="920" height="180"></canvas><span>LIVE COLOR IMPRESSION · ALIGN THE COLORS, NO TYPING</span></div>
      <div class="wth-plates">${press.plates.map(p=>`<article style="--ink:${colors[p.color]}"><h2>${esc(p.color.toUpperCase())} PLATE</h2><canvas width="300" height="200" data-pad="${p.id}" aria-label="${p.color} registration control"></canvas><p class="plate-status"></p><canvas class="wth-sleeve" width="300" height="64" data-sleeve="${p.id}" aria-label="Inspect ${p.color} plate sleeve with loupe"></canvas><p class="sleeve-status"></p></article>`).join("")}</div>
      <div class="wth-gauges"><div class="wth-paper"><span>CLEAN EXPOSURE LEFT</span><div><i></i></div><b>${press.required_clean_ms/1000} s</b></div><div class="wth-spoil"><span>PERMANENT SPOIL</span><div><i></i></div><b>0%</b></div><div class="wth-clock"><span>PRESS TIME LEFT</span><b>${press.duration_ms/1000} s</b></div></div>
      <footer><button class="wth-start">START PRESS</button><div class="readout">PREPARE YOUR PLATES</div><button class="wth-submit">END & CERTIFY</button></footer>
      <div class="wth-stamp" hidden></div></section>`;
    press.plates.forEach((plate,i)=>{
      const canvas=document.querySelector(`[data-pad="${plate.id}"]`);
      const sleeve=document.querySelector(`[data-sleeve="${plate.id}"]`);
      sleeve.addEventListener("pointermove",event=>{
        advance();if(model.ended)return;
        const r=sleeve.getBoundingClientRect(),point=[(event.clientX-r.left)*300/r.width,(event.clientY-r.top)*64/r.height].map(v=>Math.round(v*10000)/10000);
        model.loupe={i,point};
        if(!model.inspected[i]&&distance(point,[plate.stamp_x,32])<=press.loupe_radius-press.stamp_radius){model.inspected[i]=true;record("inspect",{plate_id:plate.id,point});}
        draw();
      });
      sleeve.addEventListener("pointerleave",()=>{model.loupe=null;draw();});
      canvas.addEventListener("pointerdown",event=>{
        if(event.button!==0||model.ended)return;advance();if(model.ended)return;
        const point=coordinate(event,canvas);
        if(model.mode==="simplified"){set(i,point);draw();return;}
        if(model.drag!==null||distance(point,model.positions[i])>press.handle_radius)return;
        event.preventDefault();canvas.setPointerCapture(event.pointerId);model.drag={i,pointer:event.pointerId};
        record("down",{plate_id:plate.id,point});
      });
      canvas.addEventListener("pointermove",event=>{
        if(model.ended||model.drag?.i!==i||model.drag.pointer!==event.pointerId)return;
        advance();if(model.ended)return;set(i,coordinate(event,canvas));draw();
      });
      const release=event=>{
        if(model.drag?.i!==i||model.drag.pointer!==event.pointerId)return;
        advance();if(!model.ended){
          const point=coordinate(event,canvas);
          if(event.type==="pointerup"&&distance(point,model.goals[i])>.001)set(i,point);
          record("up",{plate_id:plate.id,point});
        }
        model.drag=null;try{canvas.releasePointerCapture(event.pointerId);}catch(_){}draw();
      };
      canvas.addEventListener("pointerup",release);canvas.addEventListener("pointercancel",release);canvas.addEventListener("lostpointercapture",release);
    });
    document.querySelector(".wth-start").addEventListener("click",()=>{
      if(model.started||model.ended||model.drag)return;
      record("start");model.started=true;model.startedAt=performance.now();helpers.setReadout("PRESS RUNNING · TRACK ALL PLATES","active");
    });
    document.querySelector(".wth-submit").addEventListener("click",()=>finish());
    if(state.episode_failed || state.episode_history_error){
      model.ended=true;model.failed=true;model.submitted=true;
      model.failureReason=state.episode_history_error||"FIRST FAILURE ALREADY RECORDED";
      helpers.setReadout(model.failureReason,"error");
      const stamp=document.querySelector(".wth-stamp");stamp.hidden=false;stamp.dataset.passed="false";
      stamp.textContent=state.episode_history_error?"FAIL · HISTORY UNAVAILABLE":"FAIL · EPISODE ENDED";
    }
    draw();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.wonky_text_hostile_rendering_v3={render,rootSelector:".wth-game"};
})();
