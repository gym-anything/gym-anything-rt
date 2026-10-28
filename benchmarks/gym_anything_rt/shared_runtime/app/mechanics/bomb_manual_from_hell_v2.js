(() => {
  'use strict';
  const TAU=2*Math.PI, STEP=Math.PI/12;
  const wrap=x=>((x+Math.PI)%TAU+TAU)%TAU-Math.PI;
  const noise=(seed,index)=>{
    let x=(seed^Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  };
  function drive(motor,elapsed,variation){
    const u=elapsed/motor.span_ms,n=Math.floor(u),f=u-n;
    return motor.speed*(1+variation*(noise(motor.seed,n)+(noise(motor.seed,n+1)-noise(motor.seed,n))*f*f*(3-2*f)));
  }
  function knob(w,i,j){
    const [x,y]=w.modules[i].center,n=w.modules[i].guards.length;
    return [n===1?x:x-86+172*j/(n-1),y+119];
  }
  function distance(p,a,b){
    const dx=b[0]-a[0],dy=b[1]-a[1];
    const f=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)));
    return Math.hypot(p[0]-a[0]-f*dx,p[1]-a[1]-f*dy);
  }
  class Physics{
    constructor(w){
      this.world=w;this.ms=0;this.armed=false;this.start_ms=null;this.failed='';this.cut=[];this.charge=1;
      this.fuses=w.modules.map(m=>m.fuse.phase);
      this.guards=w.modules.map(m=>m.guards.map(g=>g.phase));
      this.offsets=w.modules.map(m=>m.guards.map(()=>0));
    }
    get solved(){return this.cut.length===this.fuses.length;}
    advance(target){
      const p=this.world.parameters;
      while(this.ms<target&&!this.failed&&!this.solved){
        if(this.armed){
          const elapsed=this.ms-this.start_ms;
          if(elapsed>=this.world.max_active_ms){this.failed='FUSE ENGINE EXPIRED';break;}
          this.charge=Math.min(1,this.charge+20/this.world.cutter_recharge_ms);
          this.world.modules.forEach((m,i)=>{
            if(this.cut.includes(i))return;
            this.fuses[i]=wrap(this.fuses[i]+.02*drive(m.fuse,elapsed,p.rate_variation)*(1+p.load_coupling*this.cut.length));
            m.guards.forEach((g,j)=>{this.guards[i][j]=wrap(this.guards[i][j]+.02*drive(g,elapsed,p.rate_variation)*(1+.55*p.load_coupling*this.cut.length));});
          });
        }
        this.ms+=20;
      }
      if(this.armed&&!this.failed&&!this.solved&&this.ms-this.start_ms>=this.world.max_active_ms)this.failed='FUSE ENGINE EXPIRED';
    }
    fusePoint(i){const [cx,cy]=this.world.modules[i].center,r=this.world.orbit_radius;return [cx+r*Math.cos(this.fuses[i]),cy+r*Math.sin(this.fuses[i])];}
    safe(i){
      const margin=Math.asin(this.world.fuse_radius/this.world.orbit_radius),half=this.world.parameters.aperture_half_deg*Math.PI/180;
      return this.guards[i].every((g,j)=>Math.abs(wrap(this.fuses[i]-g-this.offsets[i][j]*STEP))+margin<=half+1e-9);
    }
    snip(a,b){
      if(!this.armed||this.charge<1-1e-9)throw new Error('Cutter is unavailable');
      const length=Math.hypot(a[0]-b[0],a[1]-b[1]);
      if(length<30||length>100){this.failed='CUTTER STROKE MUST BE 30–100 PX';return;}
      const hits=this.fuses.map((_,i)=>i).filter(i=>!this.cut.includes(i)&&distance(this.fusePoint(i),a,b)<=this.world.fuse_radius);
      if(hits.length!==1)this.failed='CUTTER MISSED THE LIVE COLLAR';
      else if(!this.safe(hits[0]))this.failed='CUT THROUGH AN ACETATE GUARD';
      else {this.cut.push(hits[0]);this.charge=0;}
    }
    snapshot(){return {ms:this.ms,armed:this.armed,start_ms:this.start_ms,failed:this.failed,cut:[...this.cut],charge:this.charge,fuses:[...this.fuses],guards:this.guards.map(a=>[...a]),offsets:this.offsets.map(a=>[...a])};}
    forecast(delta){const next=new Physics(this.world);Object.assign(next,this.snapshot());next.advance(this.ms+delta);return next;}
  }
  window.BombManualFromHellV2Physics={Physics,drive,noise,wrap,knob,distance};
  let model,frame=0;
  const colors=['#51decd','#edb956','#df83db'];
  const clean=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  function now(){return Math.floor((performance.now()-model.startedAt)/20)*20;}
  function record(kind,details={}){model.events.push({sequence:model.events.length+1,kind,t_ms:model.physics.ms,...details});}
  function point(e){const r=model.canvas.getBoundingClientRect();return [Math.max(0,Math.min(900,(e.clientX-r.x)*900/r.width)),Math.max(0,Math.min(560,(e.clientY-r.y)*560/r.height))];}
  function sync(){
    if(!model||model.terminal)return;
    model.physics.advance(now());
    if(model.physics.failed)finish();
  }
  function draw(){
    if(!model)return;
    const s=model.physics,w=s.world,c=model.ctx;
    c.clearRect(0,0,900,560);c.fillStyle='#141918';c.fillRect(0,0,900,560);
    c.strokeStyle='#ffffff07';c.lineWidth=1;
    for(let x=0;x<900;x+=30){c.beginPath();c.moveTo(x,0);c.lineTo(x,560);c.stroke();}
    const future=s.armed&&!s.failed&&!s.solved?s.forecast(1200):s;
    w.modules.forEach((module,i)=>{
      const [cx,cy]=module.center,cut=s.cut.includes(i),half=w.parameters.aperture_half_deg*Math.PI/180;
      c.fillStyle='#202a27';c.strokeStyle='#596963';c.lineWidth=2;
      c.beginPath();c.roundRect(cx-192,cy-125,384,270,14);c.fill();c.stroke();
      c.fillStyle='#c2cfc6';c.textAlign='left';c.font='bold 14px ui-monospace,monospace';c.fillText(`DRUM ${module.label}`,cx-175,cy-103);
      c.textAlign='right';c.fillStyle=cut?'#86ecb0':s.safe(i)?'#86ecb0':'#eda486';
      c.fillText(cut?'ISOLATED':s.safe(i)?'EXPOSED':'GUARDED',cx+174,cy-103);
      c.save();c.translate(cx,cy);
      c.fillStyle='#0b110f';c.beginPath();c.arc(0,0,92,0,TAU);c.fill();
      // A transparent radial channel in each concentric leaf. Its etched
      // boundaries use the same angle and complete-collar margin as replay.
      s.guards[i].forEach((g,j)=>{
        const angle=g+s.offsets[i][j]*STEP,r=w.guard_radii[j];
        c.fillStyle=colors[j]+'13';c.beginPath();c.moveTo(0,0);c.arc(0,0,r,angle+half,angle+TAU-half);c.closePath();c.fill();
        c.strokeStyle=colors[j];c.lineWidth=4;c.beginPath();c.arc(0,0,r,angle+half,angle+TAU-half);c.stroke();
        c.lineWidth=1.5;
        for(const a of [angle-half,angle+half]){c.beginPath();c.moveTo(42*Math.cos(a),42*Math.sin(a));c.lineTo((r+3)*Math.cos(a),(r+3)*Math.sin(a));c.stroke();}
        if(s.armed&&!cut){
          const a=future.guards[i][j]+s.offsets[i][j]*STEP;
          c.strokeStyle=colors[j]+'99';c.setLineDash([2,5]);c.lineWidth=2;c.beginPath();c.arc(0,0,r+3,a-half,a+half);c.stroke();c.setLineDash([]);
        }
      });
      c.strokeStyle='#998664';c.lineWidth=5;c.beginPath();c.arc(0,0,72,0,TAU);c.stroke();
      c.fillStyle='#d8c59c';c.beginPath();c.arc(0,0,19,0,TAU);c.fill();c.fillStyle='#1b221e';c.font='bold 13px ui-monospace,monospace';c.textAlign='center';c.fillText(module.label,0,5);
      c.restore();
      const p=s.fusePoint(i);
      c.strokeStyle=cut?'#576f61':'#d9b67a';c.lineWidth=7;c.beginPath();c.moveTo(cx,cy);c.lineTo(p[0],p[1]);c.stroke();
      if(s.armed&&!cut){
        c.strokeStyle='#e4e0d0a0';c.lineWidth=1.5;c.setLineDash([2,3]);
        c.beginPath();c.moveTo(...p);
        for(let t=240;t<=1200;t+=240){const q=s.forecast(t).fusePoint(i);c.lineTo(...q);}
        c.stroke();c.setLineDash([]);
        const q=future.fusePoint(i);c.beginPath();c.arc(...q,w.fuse_radius,0,TAU);c.stroke();
      }
      c.fillStyle=cut?'#3e6450':s.safe(i)?'#a5eab2':'#eaa76f';c.strokeStyle='#101812';c.lineWidth=3;
      c.beginPath();c.arc(...p,w.fuse_radius,0,TAU);c.fill();c.stroke();
      c.strokeStyle='#1c271f';c.lineWidth=3;c.beginPath();c.moveTo(p[0]-8,p[1]);c.lineTo(p[0]+8,p[1]);c.stroke();
      if(cut){c.strokeStyle='#95e4ac';c.beginPath();c.moveTo(p[0]-7,p[1]-7);c.lineTo(p[0]+7,p[1]+7);c.moveTo(p[0]-7,p[1]+7);c.lineTo(p[0]+7,p[1]-7);c.stroke();}
      module.guards.forEach((_,j)=>{
        const [x,y]=knob(w,i,j);c.fillStyle=colors[j];c.textAlign='center';c.font='bold 12px ui-monospace,monospace';
        if(model.mode==='full'){
          c.strokeStyle=colors[j];c.lineWidth=3;c.fillStyle='#101a16';c.beginPath();c.arc(x,y,23,0,TAU);c.fill();c.stroke();
          const a=s.offsets[i][j]*STEP;c.beginPath();c.moveTo(x+10*Math.cos(a),y+10*Math.sin(a));c.lineTo(x+22*Math.cos(a),y+22*Math.sin(a));c.stroke();
          c.fillStyle=colors[j];c.fillText(['A','B','C'][j],x,y+4);
        }else{
          for(const d of [-1,1]){c.fillStyle='#24352e';c.strokeStyle=colors[j];c.lineWidth=1.5;c.fillRect(x+d*28-15,y-15,30,30);c.strokeRect(x+d*28-15,y-15,30,30);c.fillStyle=colors[j];c.font='bold 21px sans-serif';c.fillText(d<0?'↶':'↷',x+d*28,y+7);}
          c.font='bold 12px ui-monospace,monospace';c.fillText(['A','B','C'][j],x,y+4);
        }
      });
    });
    const stroke=model.cutter;
    if(stroke){c.strokeStyle='#f0ede0';c.lineWidth=2;c.setLineDash([4,3]);c.beginPath();c.moveTo(...stroke);c.lineTo(...(model.pointer||stroke));c.stroke();c.setLineDash([]);c.beginPath();c.arc(...stroke,6,0,TAU);c.stroke();}
    document.querySelector('#bomb-v2-count').textContent=`${s.cut.length} / ${w.modules.length}`;
    document.querySelector('#bomb-v2-load').textContent=`${(1+w.parameters.load_coupling*s.cut.length).toFixed(2)}×`;
    document.querySelector('#bomb-v2-charge-fill').style.width=`${s.charge*100}%`;
    document.querySelector('#bomb-v2-charge-label').textContent=s.charge>=1-1e-9?'CUTTER READY':`CUTTER RECHARGING · ${Math.ceil((1-s.charge)*4)}s`;
    document.querySelector('#bomb-v2-time').textContent=s.armed?`ENGINE · ${Math.max(0,Math.ceil((w.max_active_ms-(s.ms-s.start_ms))/1000))}s LEFT`:'ENGINE ALLOWANCE · 180s';
    document.querySelector('#bomb-v2-arm').disabled=s.armed||model.terminal;
  }
  function payload(){return {mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,interaction_mode:model.mode,events:model.events,physics:model.physics.snapshot(),completed:model.physics.solved&&!model.physics.failed};}
  async function finish(){
    if(model.terminal)return;
    model.terminal=true;model.drag=null;model.cutter=null;
    const s=model.physics,passed=s.solved&&!s.failed;
    model.helpers.setReadout(passed?'DEVICE ISOLATED · VERIFYING…':`FAIL · ${s.failed} · EPISODE ENDED` ,passed?'pending':'error');
    const root=document.querySelector('.bomb-live-v2');
    root.insertAdjacentHTML('beforeend',`<div class="bomb-v2-verdict" data-pass="${passed}"><small>ACETATE DEFUSAL</small><strong>${passed?'VERIFYING':'FAIL'}</strong><span>${clean(s.failed||'ALL LIVE FUSES ISOLATED')}${passed?'':' · EPISODE ENDED'}</span></div>`);
    draw();
    try{
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
      model.result=await response.json();
      const ok=model.result.passed===true;
      root.querySelector('.bomb-v2-verdict strong').textContent=ok?'PASS':'FAIL';
      root.querySelector('.bomb-v2-verdict').dataset.pass=String(ok);
      const feedback=s.failed||model.result.feedback||'REPLAY REJECTED';
      root.querySelector('.bomb-v2-verdict span').textContent=ok?'ALL LIVE FUSES ISOLATED':`${feedback} · EPISODE ENDED`;
      model.helpers.setReadout(ok?'PASS · DEVICE SAFE':`FAIL · ${feedback} · EPISODE ENDED`,ok?'passed':'error');
    }catch(error){model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`,'error');root.querySelector('.bomb-v2-verdict strong').textContent='ERROR';}
  }
  function animate(){sync();draw();frame=requestAnimationFrame(animate);}
  function matchKnob(p){
    const s=model.physics;
    for(let i=0;i<s.fuses.length;i++)if(!s.cut.includes(i))for(let j=0;j<s.guards[i].length;j++){
      const c=knob(s.world,i,j),r=Math.hypot(p[0]-c[0],p[1]-c[1]);
      if(model.mode==='full'&&r>=12&&r<=31)return {i,j,c};
      if(model.mode==='simplified')for(const d of [-1,1])if(Math.abs(p[0]-c[0]-d*28)<=15&&Math.abs(p[1]-c[1])<=15)return {i,j,c,d};
    }
    return null;
  }
  function manualMove(p,end=false){
    const d=model.drag,c=knob(model.physics.world,d.i,d.j),r=Math.hypot(p[0]-c[0],p[1]-c[1]);
    if(r<12||r>50){if(end){record('cancel',{input_source:'pointer_cancel'});model.drag=null;}return;}
    const angle=Math.atan2(p[1]-c[1],p[0]-c[0]);
    model.physics.offsets[d.i][d.j]=d.base+Math.floor(wrap(angle-d.angle)/STEP+.5);
    record(end?'knob_end':'knob_move',{module:d.i,layer:d.j,point:p,input_source:'manual_knob_drag'});
    if(end)model.drag=null;
  }
  function beginCut(p){
    if(!model.physics.armed||model.physics.charge<1-1e-9)return;
    model.cutter=p;model.pointer=p;record('cut_begin',{point:p,input_source:model.mode==='full'?'cutter_drag':'cutter_endpoint_clicks'});
  }
  function endCut(p){
    record('cut_end',{point:p,input_source:model.mode==='full'?'cutter_drag':'cutter_endpoint_clicks'});
    model.physics.snip(model.cutter,p);model.cutter=null;
    if(model.physics.failed||model.physics.solved)finish();
  }
  async function render(state,helpers){
    cancelAnimationFrame(frame);
    document.body.dataset.mechanic='bomb-manual-from-hell-v2';
    model={state,helpers,mode:state.control_condition.interaction,physics:new Physics(state.world),events:[],startedAt:performance.now(),terminal:false,drag:null,cutter:null,pointer:null,result:null};
    window.bombManualFromHellV2Model=model;
    helpers.app.innerHTML=`<section class="bomb-live-v2" data-interaction="${model.mode}"><header><div><small>LIVE ACETATE / ONE DEVICE</small><h1>Bomb Manual From Hell V2</h1></div><div class="bomb-v2-counter"><span>FUSES ISOLATED</span><b id="bomb-v2-count">0 / ${state.world.modules.length}</b></div></header><main><canvas id="bomb-v2-canvas" width="900" height="560" aria-label="Live fuse drums and moving acetate guards"></canvas><aside><small>FIELD MANUAL</small><h2>The manual<br>won’t sit still.</h2><div class="bomb-v2-diagram"><span>◉</span><i>↔</i><b>✂</b></div><p>Fit the <b>whole collar</b> inside every colored opening. Rotate its matching leaf with the controls below that drum.</p><p>${model.mode==='full'?'Drag the rim of a manual knob. Snip with a short drag across a collar.':'Nudge a manual leaf with ↶ / ↷. Click two endpoints across a collar to snip.'}</p><p>A snip is <b>30–100 px</b>. A miss or a guarded cut ends the device.</p><p class="bomb-v2-forecast">Dotted ghosts show <b>the next 1.2 seconds</b> under the current load. Cutting changes that load.</p><div class="bomb-v2-load">REMAINING MOTOR LOAD <b id="bomb-v2-load">1.00×</b></div><button id="bomb-v2-arm">ACTIVATE ENGINE</button><span class="bomb-v2-note">Inspect safely before activation.</span></aside></main><footer><div class="readout">Inspect safely. First failure ends this episode.</div><button id="bomb-v2-seal">SEAL DEVICE</button></footer></section>`;
    document.querySelector('.bomb-v2-load').insertAdjacentHTML('beforebegin','<div class="bomb-v2-charge"><span id="bomb-v2-charge-label">CUTTER READY</span><div><i id="bomb-v2-charge-fill"></i></div><small>4s recharge after each cut. Drums keep moving.</small></div>');
    document.querySelector('#bomb-v2-seal').insertAdjacentHTML('beforebegin','<span id="bomb-v2-time" style="font:11px ui-monospace,monospace;color:#b8c9af">ENGINE ALLOWANCE · 180s</span>');
    model.canvas=document.querySelector('#bomb-v2-canvas');model.ctx=model.canvas.getContext('2d');
    document.querySelector('#bomb-v2-arm').addEventListener('click',()=>{sync();if(model.terminal||model.physics.armed||model.drag||model.cutter)return;model.physics.armed=true;model.physics.start_ms=model.physics.ms;record('arm',{input_source:'arm_button'});helpers.setReadout('ENGINE LIVE · HOLDING A CONTROL DOES NOT STOP THE DRUMS','idle');draw();});
    document.querySelector('#bomb-v2-seal').addEventListener('click',()=>{sync();if(model.terminal)return;record('seal',{input_source:'seal_button'});model.physics.failed='INCOMPLETE DEVICE SEALED';finish();});
    const canvas=model.canvas;
    canvas.addEventListener('pointerdown',e=>{
      sync();if(model.terminal||e.button!==0||model.mode!=='full')return;
      e.preventDefault();const p=point(e),k=matchKnob(p);
      canvas.setPointerCapture(e.pointerId);
      if(k){model.drag={...k,base:model.physics.offsets[k.i][k.j],angle:Math.atan2(p[1]-k.c[1],p[0]-k.c[0])};record('knob_begin',{module:k.i,layer:k.j,point:p,input_source:'manual_knob_drag'});}
      else beginCut(p);
      draw();
    });
    canvas.addEventListener('pointermove',e=>{
      sync();if(model.terminal)return;const p=point(e);model.pointer=p;
      if(model.drag)manualMove(p);draw();
    });
    canvas.addEventListener('pointerup',e=>{
      sync();if(model.terminal||e.button!==0||model.mode!=='full')return;
      const p=point(e);if(model.drag)manualMove(p,true);else if(model.cutter)endCut(p);
      if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);draw();
    });
    for(const name of ['pointercancel','lostpointercapture'])canvas.addEventListener(name,()=>{if(!model.terminal&&(model.drag||model.cutter)){sync();record('cancel',{input_source:'pointer_cancel'});model.drag=null;model.cutter=null;draw();}});
    canvas.addEventListener('click',e=>{
      sync();if(model.terminal||model.mode!=='simplified')return;
      const p=point(e),k=matchKnob(p);
      if(k&&!model.cutter){model.physics.offsets[k.i][k.j]+=k.d;record('nudge',{module:k.i,layer:k.j,direction:k.d,point:p,input_source:'manual_buttons'});}
      else if(model.cutter)endCut(p);else beginCut(p);draw();
    });
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.bomb_manual_from_hell_v2={rootSelector:'.bomb-live-v2',render};
})();
