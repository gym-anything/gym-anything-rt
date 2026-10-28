(() => {
  'use strict';
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  function noise(seed,i){let x=(seed^Math.imul(i+1,0x9e3779b9))>>>0;x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;return ((x^(x>>>16))>>>0)/4294967295*2-1;}
  function motion(seed,ms,span){const u=Math.max(0,ms)/span,i=Math.floor(u),f=u-i;return noise(seed,i)+(noise(seed,i+1)-noise(seed,i))*f*f*(3-2*f);}
  function initial(w){return {tick:0,failed:false,reason:'',bridges:w.lanes.map(l=>({theta:0,target:0,s:l.initial_s,v:l.initial_v,length:w.initial_length,fed:false,docked:false,dock_tick:null}))};}
  const wind=(w,i,t)=>w.parameters.wind*motion(w.lanes[i].wind_seed,t,w.parameters.wind_span_ms);
  const blossom=(w,i,t)=>[w.anchor_x+w.final_length-7,w.lanes[i].anchor_y+w.lanes[i].blossom_offset+w.parameters.blossom_sway*motion(w.lanes[i].blossom_seed,t,w.parameters.blossom_span_ms)];
  const point=(w,i,s,a,o=0)=>[w.anchor_x+s*Math.cos(a)+o*Math.sin(a),w.lanes[i].anchor_y+s*Math.sin(a)-o*Math.cos(a)];
  function sheathHit(w,i,angle,pt){
    const centre=point(w,i,44,angle,w.radius+w.skin_radius),dx=pt[0]-centre[0],dy=pt[1]-centre[1];
    const x=dx*Math.cos(angle)+dy*Math.sin(angle),y=-dx*Math.sin(angle)+dy*Math.cos(angle);
    return (x/57)**2+(y/25)**2<=1;
  }
  function advance(s,w,end){const p=w.parameters,dt=w.dt_ms/1000;
    while(s.tick<end&&!s.failed&&!s.bridges.every(b=>b.docked)){
      const old=s.bridges.map(b=>b.docked?0:b.theta);
      for(let i=0;i<s.bridges.length;i++){
        const b=s.bridges[i];if(b.docked)continue;
        const others=old.filter((a,j)=>i!==j),recoil=p.coupling*others.reduce((a,b)=>a+b,0)/Math.max(1,others.length);
        const goal=clamp(b.target-recoil,-w.max_angle,w.max_angle),change=clamp(goal-b.theta,-p.slew*dt,p.slew*dt);b.theta+=change;
        const omega=change/dt;b.length=Math.min(w.final_length,b.length+(b.fed?w.growth_speed*dt:0));
        const t=s.tick*w.dt_ms;
        const a=5/7*(p.gravity*Math.sin(b.theta)+wind(w,i,t)*Math.cos(b.theta))+b.s*omega*omega-w.drag*b.v;
        b.v+=a*dt;b.s+=b.v*dt;
        if(!b.fed&&Math.abs(b.s-w.lanes[i].feed_s)<=w.radius+9)b.fed=true;
        const pod=point(w,i,b.s,b.theta,w.radius+w.skin_radius),mouth=blossom(w,i,t+w.dt_ms);
        if(b.fed&&b.length===w.final_length&&Math.hypot(pod[0]-mouth[0],pod[1]-mouth[1])+w.radius<=p.blossom_radius&&Math.abs(b.v)<=w.capture_speed){b.docked=true;b.dock_tick=s.tick+1;}
        else if(b.s< -w.radius||b.s>b.length+w.radius){s.failed=true;s.reason=`Bridge ${i+1}: pod fell`;break;}
      }
      s.tick++;
      if(s.tick*w.dt_ms>=w.max_ms&&!s.bridges.every(b=>b.docked)){s.failed=true;s.reason='Garden run ended incomplete';}
    }
    return s;
  }
  // Test access contains equations only. It never exposes a gameplay mutation.
  window.LivingScaffoldV3Physics={initial,advance,wind,blossom,point,motion};
  let frame=0,cleanup=()=>{};
  async function render(publicState,helpers){
    cleanup();cancelAnimationFrame(frame);
    const w=publicState.world,mode=publicState.control_condition?.interaction||'full',s=initial(w);
    const inspected=w.lanes.map(()=>false);
    let started=false,terminal=false,submitted=false,drag=null,events=[],history=[];
    document.body.dataset.mechanic='living-scaffold-v3';
    helpers.app.innerHTML=`<section class="lsv-shell"><header><div><small>THE SUSPENDED GARDEN · WIND STUDY</small><h1>Living Scaffold V3</h1></div><span class="lsv-count">${w.lanes.length} living ${w.lanes.length===1?'bridge':'bridges'}<br><b>ONE GARDEN / ONE ATTEMPT</b></span></header>
      <p class="lsv-rules">Restore every moving blossom. Click a leaf sheath to inspect what its living bridge needs. Keep every pod on a body. ${mode==='full'?'Drag a creature’s head up or down.':'Click a height on each control rail.'} The body follows at a limited speed.</p>
      <div class="lsv-stage"><div class="lsv-feedback" aria-label="Live bridge feedback">${w.lanes.map((l,i)=>`<div class="lsv-bridge-feedback" data-bridge="${i}" style="--bridge-color:${l.color}" aria-label="${['AMBER','JADE','LILAC'][i]} bridge feedback"><div><b>${['AMBER','JADE','LILAC'][i]}</b><span class="lsv-growth"></span></div><div><span class="lsv-speed-length"></span><span class="lsv-wind">Wind <svg width="94" height="14" viewBox="0 0 94 14" aria-label="Wind direction and strength"><line x1="47" y1="7" x2="47" y2="7" /></svg></span></div></div>`).join('')}</div><canvas class="lsv-world" width="${w.width}" height="${w.height}" aria-label="Growing living bridges with rolling pods and moving blossoms"></canvas><div class="lsv-verdict" aria-live="assertive"></div></div>
      <footer><button class="lsv-start">Wake garden</button><div class="readout">Inspect before waking, or between deliberate controls. Open sheaths stay open. Blossoms accept a whole pod below ${w.capture_speed} px/s. ${w.parameters.coupling?'The shared root bends under moving bridges; restored blossoms brace them.':''}</div><button class="lsv-submit">Check garden</button></footer></section>`;
    const canvas=helpers.app.querySelector('canvas'),ctx=canvas.getContext('2d'),root=helpers.app.querySelector('.lsv-shell');
    function record(kind,extra={}){events.push({seq:events.length+1,tick:s.tick,kind,...extra});}
    function payload(){return {mechanic_id:publicState.mechanic_id,task_id:publicState.task_id,challenge_id:publicState.challenge_id,control_condition:publicState.control_condition,events:structuredClone(events),final_tick:s.tick,completed:!s.failed&&s.bridges.every(b=>b.docked),dock_ticks:s.bridges.map(b=>b.dock_tick)};}
    async function finish(){
      if(submitted)return;terminal=true;submitted=true;drag=null;
      const complete=!s.failed&&s.bridges.every(b=>b.docked);
      const v=root.querySelector('.lsv-verdict');v.textContent=complete?'GARDEN RESTORED':'FAIL';v.dataset.kind=complete?'pass':'fail';
      root.querySelectorAll('button').forEach(b=>b.disabled=true);
      helpers.setReadout(complete?'Checking living supports…':`FAIL · ${s.reason||'Garden incomplete'}`,'pending');
      try{const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
        if(!response.ok)throw Error(`HTTP ${response.status}`);
        const result=await response.json();
        v.textContent=result.passed?'PASS · GARDEN RESTORED':'FAIL';v.dataset.kind=result.passed?'pass':'fail';
        helpers.setReadout(result.passed?'PASS · Every living bridge and blossom verified':`FAIL · ${s.reason||'Garden incomplete'}`,result.passed?'passed':'error');
      }catch(e){v.textContent='VERIFICATION UNAVAILABLE';helpers.setReadout(e.message,'error');}
    }
    // Non-real-time rule: only a deliberate target sample advances the
    // fixed-step physics. Wall-clock idle, animation frames, inspection,
    // wake-up, and pointer release leave the decision state unchanged.
    function actionAdvance(){
      if(!started||terminal)return;
      const ticks=Math.max(1,Number(w.action_ticks||4));
      advance(s,w,Math.min(s.tick+ticks,w.max_ms/w.dt_ms));
      if(s.failed||s.bridges.every(b=>b.docked))finish();
    }
    function setTarget(i,pt){
      record('target',{bridge:i,point:pt,input_source:mode==='full'?'head_drag':'rail_click'});
      s.bridges[i].target=clamp((pt[1]-(mode==='full'?w.lanes[i].anchor_y:300))/530,-w.max_angle,w.max_angle);
      if(!started)s.bridges[i].theta=s.bridges[i].target;
    }
    function local(e){const r=canvas.getBoundingClientRect();return [(e.clientX-r.x)*w.width/r.width,(e.clientY-r.y)*w.height/r.height];}
    function input(e){if(terminal||s.failed||s.bridges.every(b=>b.docked)){if(started)finish();return false;}return true;}
    canvas.addEventListener('pointerdown',e=>{if(e.button!==0||!input(e))return;
      const pt=local(e);
      // A physical leaf sheath, identical in both modes, conceals the fruit.
      // Opening it is an information probe and never moves or pauses a bridge.
      const leaf=s.bridges.findIndex((b,i)=>!inspected[i]&&sheathHit(w,i,b.theta,pt));
      if(leaf>=0&&!drag){inspected[leaf]=true;record('inspect',{bridge:leaf,point:pt,input_source:'sheath_click'});draw();return;}
      if(mode==='simplified'){
        const i=w.lanes.findIndex((l,j)=>Math.abs(pt[1]-300)<=145&&pt[0]>=735+j*70&&pt[0]<=785+j*70);
        if(i>=0&&!s.bridges[i].docked){setTarget(i,pt);actionAdvance();}
      }else{
        const i=s.bridges.findIndex((b,j)=>!b.docked&&Math.hypot(...point(w,j,b.length,b.theta).map((v,k)=>v-pt[k]))<=28);
        if(i>=0){e.preventDefault();canvas.setPointerCapture(e.pointerId);drag={i,id:e.pointerId};record('down',{bridge:i,point:pt,input_source:'head_drag'});}
      }
      draw();
    });
    canvas.addEventListener('pointermove',e=>{if(drag&&input(e)){setTarget(drag.i,local(e));actionAdvance();draw();}});
    const release=e=>{if(!drag)return;if(!terminal&&!s.failed&&!s.bridges.every(b=>b.docked))record('up',{bridge:drag.i,input_source:'head_drag'});drag=null;};
    canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);canvas.addEventListener('lostpointercapture',release);
    root.querySelector('.lsv-start').onclick=()=>{if(started||terminal||drag)return;record('start');started=true;root.querySelector('.lsv-start').disabled=true;helpers.setReadout('Garden awake · choose a bridge control','idle');};
    root.querySelector('.lsv-submit').onclick=()=>{if(!s.bridges.every(b=>b.docked))s.failed=true;s.reason=s.reason||'Garden incomplete';finish();};
    function circle(x,y,r,fill,stroke=null,lw=1){ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();if(stroke){ctx.lineWidth=lw;ctx.strokeStyle=stroke;ctx.stroke();}}
    function draw(){
      const t=s.tick*w.dt_ms;ctx.clearRect(0,0,w.width,w.height);
      const bg=ctx.createLinearGradient(0,0,0,w.height);bg.addColorStop(0,'#edf1dc');bg.addColorStop(1,'#bed7ca');ctx.fillStyle=bg;ctx.fillRect(0,0,w.width,w.height);
      ctx.fillStyle='#53796b22';for(let x=0;x<w.width;x+=40)for(let y=0;y<w.height;y+=40)circle(x+10,y+12,1.4,'#53796b22');
      ctx.fillStyle='#344f46';ctx.fillRect(38,0,42,w.height);
      const spacing=w.height/w.lanes.length;
      for(let i=0;i<w.lanes.length;i++){
        const l=w.lanes[i],b=s.bridges[i],head=point(w,i,b.length,b.theta),mouth=blossom(w,i,t);
        ctx.strokeStyle='#688c7833';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(90,spacing*(i+1));ctx.lineTo(950,spacing*(i+1));ctx.stroke();
        ctx.font='bold 14px sans-serif';ctx.fillStyle='#315647';ctx.fillText(['AMBER','JADE','LILAC'][i],102,Math.max(18,l.anchor_y-49));
        // Past positions are visible evidence, sampled from the shared task clock.
        ctx.strokeStyle=l.color+'60';ctx.lineWidth=5;ctx.beginPath();
        for(let k=0;k<6;k++){const past=blossom(w,i,Math.max(0,t-800+k*160));if(k===0)ctx.moveTo(...past);else ctx.lineTo(...past);}ctx.stroke();
        for(let a=0;a<6;a++){const r=w.parameters.blossom_radius+11;circle(mouth[0]+Math.cos(a*Math.PI/3)*r,mouth[1]+Math.sin(a*Math.PI/3)*r,14,l.color+'b0');}
        circle(...mouth,w.parameters.blossom_radius,'#f8efcb','#687c51',2);circle(...mouth,w.parameters.blossom_radius-w.radius,'#a9b99244');
        ctx.strokeStyle='#43604a';ctx.lineWidth=22;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(w.anchor_x,l.anchor_y);ctx.lineTo(...head);ctx.stroke();
        ctx.strokeStyle=l.color;ctx.lineWidth=19;ctx.stroke();
        for(let q=0;q<=b.length;q+=27){const pt=point(w,i,q,b.theta);circle(...pt,9,l.color,'#fff8de55',1);}
        circle(w.anchor_x,l.anchor_y,17,'#466850','#bfd3a3',3);
        circle(...head,25,l.color,'#fff3c5',3);circle(head[0]-7,head[1]-4,5,'#fff7e4');circle(head[0]+7,head[1]-4,5,'#fff7e4');circle(head[0]-6,head[1]-3,2,'#233e33');circle(head[0]+8,head[1]-3,2,'#233e33');
        if(!inspected[i]){
          const leaf=point(w,i,44,b.theta,w.radius+w.skin_radius);
          ctx.save();ctx.translate(...leaf);ctx.rotate(b.theta);ctx.fillStyle='#48774d';ctx.strokeStyle='#d7e5b0';ctx.lineWidth=2;
          ctx.beginPath();ctx.ellipse(0,0,57,25,0,0,Math.PI*2);ctx.fill();ctx.stroke();
          ctx.beginPath();ctx.moveTo(-45,0);ctx.lineTo(45,0);ctx.stroke();
          ctx.fillStyle='#315647';ctx.font='bold 11px sans-serif';ctx.fillText('INSPECT LEAF',20,-31);ctx.restore();
        }else if(!b.fed){const food=point(w,i,l.feed_s,b.theta,w.radius+w.skin_radius);circle(...food,9,'#edc452','#927538',2);ctx.strokeStyle='#608142';ctx.beginPath();ctx.moveTo(food[0],food[1]-7);ctx.lineTo(food[0]+7,food[1]-16);ctx.stroke();}
        if(!b.docked){
          const recent=history.filter(h=>h.tick>=s.tick-80),pts=recent.map(h=>point(w,i,h.bridges[i].s,h.bridges[i].theta,w.radius+w.skin_radius));
          ctx.strokeStyle='#fcf8dbaa';ctx.lineWidth=3;ctx.beginPath();pts.forEach((pt,k)=>k?ctx.lineTo(...pt):ctx.moveTo(...pt));ctx.stroke();
          const pod=point(w,i,b.s,b.theta,w.radius+w.skin_radius);circle(...pod,w.radius,'#f6eecb','#425e43',2);ctx.strokeStyle=l.color;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(pod[0]-6,pod[1]);ctx.lineTo(pod[0]+6,pod[1]);ctx.stroke();
        }else{circle(...mouth,11,l.color);ctx.fillStyle='#315647';ctx.font='bold 12px sans-serif';ctx.fillText('RESTORED',mouth[0]+48,mouth[1]+5);}
        const feedback=root.querySelector(`.lsv-bridge-feedback[data-bridge="${i}"]`);
        feedback.querySelector('.lsv-growth').textContent=b.docked?'RESTORED':b.fed?'GROWN':inspected[i]?'GOLD FRUIT → GROWTH':'LEAF SHEATH CLOSED';
        feedback.querySelector('.lsv-speed-length').textContent=`Pod ${Math.round(b.v)} px/s · ${Math.round(b.length)} px`;
        feedback.querySelector('line').setAttribute('x2',47+wind(w,i,t)*1.2);
        // The exact same rails and target markers provide information in both modes.
        const rx=760+i*70,ry=300,low=155,high=445;
        ctx.fillStyle='#f6f5e7b8';ctx.fillRect(rx-25,low,50,high-low);ctx.strokeStyle='#7a947a';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(rx,low);ctx.lineTo(rx,high);ctx.stroke();
        const ty=clamp(ry+b.target*530,low,high);circle(rx,ty,9,l.color,'#fff9dd',2);
        ctx.font='11px sans-serif';ctx.fillStyle='#315647';ctx.fillText(['AMBER','JADE','LILAC'][i],rx-20,low-12);
        ctx.fillText(mode==='full'?'HEAD':'CLICK',rx-19,high+22);
      }
    }
    function animate(){history.push(structuredClone(s));history=history.filter(h=>h.tick>=s.tick-90).slice(-60);draw();frame=requestAnimationFrame(animate);}
    window.livingScaffoldV3Model={snapshot:()=>structuredClone(s),world:w,get inspected(){return [...inspected];},get events(){return structuredClone(events);},get started(){return started;},payload};
    cleanup=()=>{cancelAnimationFrame(frame);terminal=true;};draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.living_scaffold_v3_nonrealtime={rootSelector:'.lsv-shell',render};
})();
