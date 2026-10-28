(() => {
  'use strict';

  function motionNoise(seed, index) {
    let x = (Number(seed) + Math.imul(index + 1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 2147483648 - 1;
  }
  function motionValue(seed, tMs, spanMs=1300) {
    const t = Math.max(0, tMs) / spanMs, i = Math.floor(t), u = t-i;
    const a = motionNoise(seed,i), b = motionNoise(seed,i+1);
    return a+(b-a)*u*u*(3-2*u);
  }
  function motionIntegral(seed, tMs, spanMs=1300) {
    const t = Math.max(0,tMs)/spanMs, n = Math.floor(t), u=t-n;
    let sum=0;
    for(let i=0;i<n;i++) sum+=(motionNoise(seed,i)+motionNoise(seed,i+1))/2;
    const a=motionNoise(seed,n), b=motionNoise(seed,n+1);
    return spanMs/1000*(sum+a*u+(b-a)*(u**3-.5*u**4));
  }

  const ID = 'elbow_engine_v2';
  let cleanup = null;
  function derivative(s, torque, p) {
    const [a,b,va,vb]=s, {mass1:m1,mass2:m2,length1:l1,length2:l2}=p;
    const c1=l1/2,c2=l2/2,coupling=m2*l1*c2;
    const d11=p.inertia1+p.inertia2+m1*c1*c1+m2*(l1*l1+c2*c2+2*l1*c2*Math.cos(b));
    const d12=p.inertia2+m2*(c2*c2+l1*c2*Math.cos(b)),d22=p.inertia2+m2*c2*c2;
    const g2=m2*c2*p.gravity*Math.sin(a+b),g1=(m1*c1+m2*l1)*p.gravity*Math.sin(a)+g2;
    const r1=coupling*Math.sin(b)*(2*va*vb+vb*vb)-g1-p.damping*va;
    const r2=torque-coupling*Math.sin(b)*va*va-g2-p.damping*vb,det=d11*d22-d12*d12;
    return [va,vb,(r1*d22-r2*d12)/det,(r2*d11-r1*d12)/det];
  }
  function step(s,u,p) {
    const dt=p.tick_ms/1000*p.time_scale, add=(k,f)=>s.map((v,i)=>v+dt*k[i]*f);
    const a=derivative(s,u,p), b=derivative(add(a,.5),u,p), c=derivative(add(b,.5),u,p),d=derivative(add(c,1),u,p);
    return s.map((v,i)=>v+dt*(a[i]+2*b[i]+2*c[i]+d[i])/6);
  }
  async function render(state,helpers,freshFailure=false) {
    if(cleanup)cleanup();
    const p=state.physics, full=(state.control_condition?.interaction||'full')==='full';
    const m={s:[...state.initial],tick:0,u:0,events:[],heldMs:0,running:false,finished:false,won:false,busy:false,startTime:null};
    // Read-only instrumentation is for wiring tests; solvers still deliver real input.
    window.elbowEngineModel=m;
    document.body.dataset.mechanic=ID;
    helpers.app.innerHTML=`<section class="elbow-engine" data-challenge-id="${state.challenge_id}">
      <header><div><small>KINETIC WORKSHOP / EXPERIMENT 03</small><h1>Elbow Engine V2</h1></div><div class="ee-badge">ONE MOTOR<br><b>TWO ARMS</b></div></header>
      <div class="ee-layout"><div class="ee-stage"><svg id="ee-scene" viewBox="0 0 850 510" role="img" aria-label="Two brass arms with a passive ceiling pivot and powered elbow">
      <defs><pattern id="ee-grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="#29403f" stroke-width=".6"/></pattern><linearGradient id="ee-brass" x2="0" y2="1"><stop stop-color="#ffe5a3"/><stop offset=".45" stop-color="#c6994f"/><stop offset="1" stop-color="#745429"/></linearGradient><filter id="ee-glow"><feGaussianBlur stdDeviation="4"/></filter></defs>
      <rect width="850" height="510" fill="url(#ee-grid)"/><circle cx="425" cy="255" r="224" fill="none" stroke="#36514b" stroke-dasharray="2 9"/>
      <path d="M350 22H500M425 22V255" stroke="#354643" stroke-width="8"/><path d="M350 18H500" stroke="#96a598" stroke-width="3"/>
      <path id="ee-height-line" d="M72 ${255-p.target_height*110}H778" stroke="#a7f3bc" stroke-width="2" stroke-dasharray="12 6"/>
      <text x="75" y="${242-p.target_height*110}" fill="#bafacb" font-size="14" letter-spacing="2">HOLD ABOVE THIS HEIGHT</text>
      <g id="ee-arms"><line id="ee-link1" stroke="#483820" stroke-width="26" stroke-linecap="round"/><line id="ee-inlay1" stroke="url(#ee-brass)" stroke-width="18" stroke-linecap="round"/><line id="ee-link2" stroke="#483820" stroke-width="22" stroke-linecap="round"/><line id="ee-inlay2" stroke="url(#ee-brass)" stroke-width="14" stroke-linecap="round"/>
      <circle cx="425" cy="255" r="17" fill="#738078" stroke="#d5dccc" stroke-width="3"/><circle cx="425" cy="255" r="6" fill="#202f2b"/>
      <g id="ee-elbow"><circle r="21" fill="#243732" stroke="#efc67e" stroke-width="4"/><path d="M-12 0H12M0 -12V12" stroke="#efc67e" stroke-width="3"/><circle r="5" fill="#f7db8f"/></g>
      <circle id="ee-tip-glow" r="17" fill="#8cf7d4" opacity=".55" filter="url(#ee-glow)"/><circle id="ee-tip" r="9" fill="#c0ffdd" stroke="#f5fff6" stroke-width="2"/></g>
      <text x="443" y="235" fill="#afbeb2" font-size="12">PASSIVE PIVOT</text><text x="30" y="480" fill="#809b8d" font-size="12">OFFSET ARMS · FREE TO ROTATE PAST EACH OTHER</text>
      </svg><div class="ee-verdict" hidden><b></b><span></span></div></div>
      <aside><small>HEIGHT TRIAL</small><h2>Make the tip<br>stay above<br>the green line.</h2><p>Only the elbow is powered.<br>The ceiling hinge swings freely.</p>
      <div class="ee-time"><span>HEIGHT HOLD</span><b id="ee-hold">0%</b><small>1.2 s continuously · resets below line</small></div><div class="ee-time"><span>RUN TIME</span><b id="ee-seconds">0.00</b><small>/ 180 s</small></div>
      <div class="ee-motor"><span>ELBOW TORQUE</span><strong id="ee-torque">0</strong><small id="ee-draft"></small><div class="ee-controls"><button data-u="-1" aria-label="Negative torque">↶<small>${full?'HOLD ←':'SET −'}</small></button><button data-u="0" aria-label="Neutral torque">○<small>${full?'RELEASE':'SET 0'}</small></button><button data-u="1" aria-label="Positive torque">↷<small>${full?'HOLD →':'SET +'}</small></button></div><p>${full?'Hold an arrow key or torque pad. Release to coast.':'Click a torque state. It stays on until you choose another.'}</p></div>
      <button id="ee-start">START ENGINE</button></aside></div>
      <footer><div class="readout" data-status="idle">READY · HOLD THE TIP ABOVE THE MARKER</div><button id="ee-submit">SUBMIT TRIAL</button></footer></section>`;
    const $=s=>helpers.app.querySelector(s), keys=new Set();
    const record=(type,more={})=>m.events.push({seq:m.events.length+1,type,tick:m.tick,...more});
    function paint(){
      const [a,b]=m.s, x1=425+p.length1*110*Math.sin(a), y1=255+p.length1*110*Math.cos(a),x2=x1+p.length2*110*Math.sin(a+b), y2=y1+p.length2*110*Math.cos(a+b);
      for(const id of ['ee-link1','ee-inlay1']){const e=$('#'+id);for(const [k,v] of Object.entries({x1:425,y1:255,x2:x1,y2:y1}))e.setAttribute(k,v);}
      for(const id of ['ee-link2','ee-inlay2']){const e=$('#'+id);for(const [k,v] of Object.entries({x1,y1,x2,y2}))e.setAttribute(k,v);}
      $('#ee-elbow').setAttribute('transform',`translate(${x1} ${y1}) rotate(${(a+b)*180/Math.PI})`);
      for(const id of ['ee-tip','ee-tip-glow']){ $('#'+id).setAttribute('cx',x2);$('#'+id).setAttribute('cy',y2); }
      $('#ee-hold').textContent=`${Math.floor(100*m.heldMs/p.hold_ms)}%`;
      const load=p.disturbance_fraction*motionValue(p.disturbance_seed,m.tick*p.tick_ms,1500);
      $('#ee-draft').textContent=`EXTERNAL LOAD ${load<0?'↶':'↷'} ${Math.round(Math.abs(load)*100)}%`;
      $('#ee-seconds').textContent=(m.tick*p.tick_ms/1000).toFixed(2);
      $('#ee-torque').textContent=m.u>0?'+':m.u<0?'−':'0';
      for(const e of helpers.app.querySelectorAll('[data-u]')){e.dataset.active=String(+e.dataset.u===m.u);e.disabled=!m.running||m.finished;}
      $('#ee-start').disabled=m.running||m.finished;$('#ee-submit').disabled=m.busy;
    }
    function finish(){
      if(m.finished)return;
      m.finished=true;m.running=false;
      record('finish',{state:[...m.s]});
      const v=$('.ee-verdict');v.hidden=false;v.dataset.won=String(m.won);
      v.querySelector('b').textContent=m.won?'HEIGHT HOLD COMPLETE':'FAIL';
      v.querySelector('span').textContent=m.won?'Submit your successful swing.':'The height hold was incomplete. Submit to try a fresh engine.';
      helpers.setReadout(m.won?'HEIGHT HOLD COMPLETE · SUBMIT TRIAL':'FAIL · SUBMIT FOR A FRESH ENGINE',m.won?'idle':'error');paint();
    }
    function torque(u){
      advancePhysics();
      if(!m.running||m.finished||m.u===u)return;
      m.u=u;record('torque',{value:u,input_source:full?'held_torque':'latched_torque'});paint();
    }
    $('#ee-start').onclick=()=>{if(m.running||m.finished)return;record('start');m.startTime=performance.now();m.running=true;$('.ee-verdict').hidden=true;helpers.setReadout('ENGINE RUNNING','idle');paint();};
    let pointer=null;
    for(const e of helpers.app.querySelectorAll('[data-u]')){
      const u=+e.dataset.u;
      if(!full){e.onclick=()=>torque(u);continue;}
      e.onpointerdown=event=>{if(event.button!==0||!m.running)return;event.preventDefault();pointer=event.pointerId;e.setPointerCapture(pointer);torque(u);};
      const release=event=>{if(event.pointerId===pointer){pointer=null;torque(0);}};
      e.onpointerup=release;e.onpointercancel=release;e.onlostpointercapture=release;
    }
    const keydown=e=>{if(!full||!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();if(e.repeat)return;keys.add(e.key);torque(keys.size===2?0:e.key==='ArrowLeft'?-1:1);};
    const keyup=e=>{if(!full||!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();keys.delete(e.key);torque(keys.size===0?0:keys.has('ArrowLeft')?-1:1);};
    const blur=()=>{keys.clear();pointer=null;if(full)torque(0);};
    window.addEventListener('keydown',keydown);window.addEventListener('keyup',keyup);window.addEventListener('blur',blur);
    function advancePhysics(){
      if(!m.running||m.finished||m.busy)return;
      // Timers/frames may be late under capture load. Integrate every fixed
      // step owed by the shared virtual clock, including its pause endpoint.
      const target=Math.min(p.max_ticks,Math.floor((performance.now()-m.startTime+1e-7)/p.tick_ms));
      while(m.tick<target&&!m.finished){
        const load=p.torque*p.disturbance_fraction*motionValue(p.disturbance_seed,m.tick*p.tick_ms,1500);
        m.s=step(m.s,m.u*p.torque+load,p);m.tick++;
        const high=-p.length1*Math.cos(m.s[0])-p.length2*Math.cos(m.s[0]+m.s[1])>p.target_height;
        m.heldMs=high?m.heldMs+p.tick_ms:0;m.won=m.heldMs>=p.hold_ms;
        if(m.won||m.tick>=p.max_ticks)finish();
      }
      paint();
    }
    let frame;
    function animate(){advancePhysics();frame=requestAnimationFrame(animate);}
    frame=requestAnimationFrame(animate);
    $('#ee-submit').onclick=async()=>{
      if(m.busy)return;
      advancePhysics();
      if(!m.events.length)record('start');
      finish();m.busy=true;paint();
      try{
        const r=await (await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mechanic_id:ID,task_id:state.task_id,challenge_id:state.challenge_id,control_condition:state.control_condition,events:m.events,completed:m.won})})).json();
        if(r.passed){$('.ee-verdict b').textContent='PASS';$('.ee-verdict span').textContent='The engine earned its wings.';helpers.setReadout('PASS','passed');}
        else if(r.state){await render(r.state,helpers,true);helpers.setReadout('FAIL · FRESH ENGINE READY','error');}
        else{m.busy=false;helpers.setReadout('SUBMISSION REJECTED · RETRY','error');paint();}
      }catch(e){m.busy=false;helpers.setReadout('SUBMISSION UNAVAILABLE · RETRY','error');paint();}
    };
    cleanup=()=>{cancelAnimationFrame(frame);window.removeEventListener('keydown',keydown);window.removeEventListener('keyup',keyup);window.removeEventListener('blur',blur);};
    paint();
    if(freshFailure){const v=$('.ee-verdict');v.hidden=false;v.dataset.won='false';v.querySelector('b').textContent='FAIL';v.querySelector('span').textContent='Fresh engine ready. Press Start to try again.';}
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.elbow-engine',render};
})();
