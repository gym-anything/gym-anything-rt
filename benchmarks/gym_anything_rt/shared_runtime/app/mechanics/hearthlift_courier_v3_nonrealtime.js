(() => {
  'use strict';
  const ID='hearthlift_courier_v3_nonrealtime', REV='moving-crate-hops-v2';
  const clone=x=>JSON.parse(JSON.stringify(x));
  const clean=x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function noise(seed,index) {
    let x=(seed^Math.imul(index+1,0x9E3779B9))>>>0;
    x=Math.imul(x^(x>>>16),0x85EBCA6B)>>>0;
    x=Math.imul(x^(x>>>13),0xC2B2AE35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function center(platform,ms) {
    const s=platform.motion;
    if (!s) return [...platform.center];
    const u=(Math.max(0,ms)+s.offset_ms)/s.span_ms,n=Math.floor(u),f=u-n,b=f*f*f*(10+f*(-15+6*f));
    if(s.knots){const a=s.knots[n],z=s.knots[n+1];return platform.center.map((p,i)=>p+s.amplitude[i]*(a[i]+(z[i]-a[i])*b));}
    return platform.center.map((p,i)=>p+s.amplitude[i]*(noise(s.seed+i*7919,n)+(noise(s.seed+i*7919,n+1)-noise(s.seed+i*7919,n))*b));
  }
  const velocity=(platform,ms)=>center(platform,ms+10).map((v,i)=>(v-center(platform,Math.max(0,ms-10))[i])*50);
  const forecast=(platform,ms)=>Array.from({length:17},(_,i)=>center(platform,ms+i*200));
  function chartPoint(w,p) {const c=w.chart,m=c.margin;return [m+(p[0]-c.x_min)/(c.x_max-c.x_min)*(c.width-2*m),m+(p[1]-c.z_min)/(c.z_max-c.z_min)*(c.height-2*m)];}
  function chartWorld(w,p) {const c=w.chart,m=c.margin;return [c.x_min+(p[0]-m)/(c.width-2*m)*(c.x_max-c.x_min),c.z_min+(p[1]-m)/(c.height-2*m)*(c.z_max-c.z_min)];}
  class Physics {
    constructor(w) {this.world=w;this.spec=w.physics;this.tick=0;this.p=[...w.platforms[0].center];this.v=[0,0,0];this.support='quay';this.offset=[0,0];this.active=false;this.loaded=false;this.delivered=false;this.failed='';this.landings=[];}
    platform(id) {return this.world.platforms.find(p=>p.id===id);}
    start() {if(this.active)throw Error('Lifts already awake.');this.active=true;this.loaded=true;}
    launch(aim) {
      if(!this.active||!this.support||this.failed||this.delivered)throw Error('Wait until the courier is supported.');
      const pv=velocity(this.platform(this.support),this.tick*10),s=this.spec;
      const vx=(aim[0]-this.p[0])/s.aim_seconds+pv[0]*s.inherit,vz=(aim[1]-this.p[2])/s.aim_seconds+pv[2]*s.inherit;
      if(Math.hypot(vx,vz)>s.speed_limit+1e-8)throw Error('Aim is beyond the jump range.');
      this.v=[vx,s.jump_speed+pv[1]*s.inherit,vz];this.support=null;
      if(s.timing_mode==='action_triggered'){
        const limit=Math.floor(s.play_time_ms/s.tick_ms);
        while(this.support===null&&!this.failed&&!this.delivered&&this.tick<limit)this.advance(this.tick+1,true);
      }
    }
    burn() {if(this.delivered)return;if(!this.active||this.support!=='hearth'||!this.loaded)this.failed='The crate was released away from the hearth.';else{this.loaded=false;this.delivered=true;}}
    advance(end,actionPhase=false) {
      if(!this.active)return;
      if(this.spec.timing_mode==='action_triggered'&&end!==this.tick&&!actionPhase)throw Error('Task time advances only after a deliberate hop.');
      while(this.tick<end&&!this.failed&&!this.delivered){
        const t=this.tick*10;this.tick++;
        if(this.support){const c=center(this.platform(this.support),t+10);this.p=[c[0]+this.offset[0],c[1],c[2]+this.offset[1]];this.v=velocity(this.platform(this.support),t+10);}
        else {
          const before=[...this.p];this.v[1]-=this.spec.gravity*.01;
          let after=before.map((p,i)=>p+this.v[i]*.01),contacts=[];
          for(const platform of this.world.platforms){
            const old=center(platform,t),next=center(platform,t+10),d0=before[1]-old[1],d1=after[1]-next[1];
            if(d0>=-1e-9&&d1<=0&&d1<d0){
              const f=d0/(d0-d1),p=before.map((a,i)=>a+(after[i]-a)*f),c=old.map((a,i)=>a+(next[i]-a)*f);
              if(Math.abs(p[0]-c[0])+this.spec.radius<=platform.half[0]+1e-9&&Math.abs(p[2]-c[2])+this.spec.radius<=platform.half[1]+1e-9)contacts.push({f,id:platform.id,p,c});
            }
          }
          if(contacts.length){
            contacts.sort((a,b)=>a.f-b.f||a.id.localeCompare(b.id));const hit=contacts[0];
            this.offset=[hit.p[0]-hit.c[0],hit.p[2]-hit.c[2]];this.support=hit.id;
            const c=center(this.platform(hit.id),t+10);after=[c[0]+this.offset[0],c[1],c[2]+this.offset[1]];this.v=velocity(this.platform(hit.id),t+10);
            this.landings.push({tick:this.tick,platform:hit.id});
          }
          this.p=after;
        }
        if(this.p[1]<this.spec.fall_y)this.failed='Courier and crate fell into the ravine.';
        if(this.tick*10>=this.spec.play_time_ms)this.failed='The delivery shift ended.';
      }
    }
    snapshot(){return {tick:this.tick,position:[...this.p],velocity:[...this.v],support:this.support,loaded:this.loaded,delivered:this.delivered,failed:this.failed,landings:clone(this.landings)};}
  }
  window.HearthliftCourierV3NonrealtimePhysics={Physics,center,velocity,chartPoint,chartWorld};
  let model=null,frame=0,keyHandler=null;
  function record(kind,source,extra={}){model.events.push({seq:model.events.length+1,tick:model.sim.tick,kind,input_source:source,...extra});}
  function sync(){
    if(!model?.sim.active||model.terminal)return;
    if(model.sim.failed&&!model.submitting){model.selection=null;record('seal','certify_button');submit();}
  }
  function message(text,status='idle'){model.helpers.setReadout(text,status);}
  function point(e){const r=model.chart.getBoundingClientRect();return [(e.clientX-r.x)*1000/r.width,(e.clientY-r.y)*290/r.height];}
  function source(){return model.mode==='full'?'courier_drag':'chart_click';}
  function inspect(p){
    sync();if(model.terminal||model.submitting||model.selection||model.sim.delivered)return false;
    // Read the selected lift's motor survey, without moving the courier or
    // advancing the resolved task tick. The retained survey remains visible.
    const w=model.world,t=model.sim.tick*10;
    const platform=w.platforms.find(platform=>{
      if(!platform.motion)return false;
      const c=center(platform,t),a=chartPoint(w,[c[0]-platform.half[0],c[2]-platform.half[1]]),b=chartPoint(w,[c[0]+platform.half[0],c[2]+platform.half[1]]);
      return p[0]>=a[0]-6&&p[0]<=b[0]+6&&p[1]>=a[1]-6&&p[1]<=b[1]+6;
    });
    if(!platform)return false;
    model.surveyed.add(platform.id);
    record('inspect','lift_inspection',{point:p,platform:platform.id,forecast:forecast(platform,t)});
    message(`${platform.id.toUpperCase()} SURVEY · DOTTED RAIL RETAINED UNTIL NEXT HOP`);draw();return true;
  }
  function select(p,pointer=null){
    sync();if(model.terminal||model.submitting||!model.sim.active||!model.sim.support||model.sim.delivered||model.selection)return;
    const courier=chartPoint(model.world,[model.sim.p[0],model.sim.p[2]]);
    if(Math.hypot(p[0]-courier[0],p[1]-courier[1])>16)return;
    model.selection={point:p,pointer};record(model.mode==='full'?'aim_start':'select',source(),{point:p});message('AIM AHEAD · NEXT HOP RESOLVES THE REPLAY');
  }
  function launch(p){
    sync();if(!model.selection||model.terminal||model.submitting)return;
    model.selection=null;
    try{
      if(p[0]<0||p[0]>1000||p[1]<0||p[1]>290)throw Error('Release inside the aim chart. Aiming canceled.');
      record('launch',source(),{point:p});model.sim.launch(chartWorld(model.world,p));
      message(model.sim.failed?'IN FLIGHT · COURIER LOST':model.sim.support?`LANDED ON ${model.sim.support.toUpperCase()} · PLAN THE NEXT HOP`:'IN FLIGHT · WAIT FOR CONTACT',model.sim.failed?'error':'idle');
      sync();}
    catch(error){if(model.events.at(-1)?.kind==='launch')model.events.pop();record('cancel',source());message(error.message,'error');}
    draw();
  }
  function cancel(){if(!model.selection||model.terminal)return;sync();record('cancel',source());model.selection=null;draw();}
  function burn(){sync();if(model.terminal||model.submitting||model.selection||!model.sim.active||model.sim.delivered)return;record('burn',model.mode==='full'?'keyboard_e':'burn_button');model.sim.burn();message(model.sim.failed||'EMBER CRATE BURNED · CERTIFY DELIVERY',model.sim.failed?'error':'passed');sync();draw();}
  function start(){if(model.sim.active||model.terminal)return;model.sim.start();record('start','start_button');model.root.querySelector('#hc-start').disabled=true;message('HOPS ARMED · DELIBERATE HOPS RESOLVE THE LIFTS');draw();}
  function staticFailureKey(url=new URL(location.href)){
    const parameters=new URLSearchParams(url.search);parameters.delete('time_mode');parameters.sort();
    const query=parameters.toString();
    return `hearthlift-episode-failed:${url.pathname}${query?'?'+query:''}`;
  }
  function staticFailure(){
    if(!window.GYM_ANYTHING_RT_BROWSER_PLAY)return false;
    try{
      const key=staticFailureKey();if(sessionStorage.getItem(key)==='true')return true;
      // Retain failures written by earlier exports, including before a visible
      // observation-mode change. Reading them must not erase the old record.
      const prefix='hearthlift-episode-failed:';
      for(let index=0;index<sessionStorage.length;index++){
        const previous=sessionStorage.key(index);
        if(previous?.startsWith(prefix)&&sessionStorage.getItem(previous)==='true'&&
          staticFailureKey(new URL(previous.slice(prefix.length),location.origin))===key)return true;
      }
    }catch(_){}
    return false;
  }
  function rememberFailure(){if(window.GYM_ANYTHING_RT_BROWSER_PLAY)try{sessionStorage.setItem(staticFailureKey(),'true');}catch(_){}}
  function payload(){return {mechanic_id:ID,physics_revision:REV,task_id:model.state.task_id,challenge_id:model.state.challenge_id,control_condition:clone(model.state.control_condition),interaction_mode:model.mode,events:clone(model.events),final_state:model.sim.snapshot(),completed:model.sim.delivered&&!model.sim.failed,episode_failed:model.episodeFailed};}
  async function submit(){
    if(model.submitting||model.terminal)return;
    model.submitting=true;model.terminal=true;model.selection=null;
    const failed=model.sim.failed||!model.sim.delivered;if(failed)rememberFailure();
    model.root.dataset.verdict=failed?'fail':'pending';
    model.root.querySelector('.hc-verdict').textContent=failed?'FAIL · DELIVERY ENDED':'VERIFYING DELIVERY';
    draw();
    try{
      const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())}),result=await r.json();
      if(result.passed===false)rememberFailure();
      model.root.dataset.verdict=result.passed===true?'pass':'fail';
      model.root.querySelector('.hc-verdict').textContent=result.passed===true?'PASS · EMBER DELIVERED':'FAIL · DELIVERY ENDED';
      message(result.passed===true?'PASS':'FAIL · ATTEMPT ENDED',result.passed===true?'passed':'error');
    }catch(error){model.root.dataset.verdict='error';model.root.querySelector('.hc-verdict').textContent='VERIFIER UNAVAILABLE';message('Verifier unavailable.','error');}
  }
  function seal(){sync();if(model.terminal||model.submitting)return;if(model.selection)cancel();record('seal','certify_button');submit();}
  function path(ctx,points,color,width=2,dash=[]){ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);}
  function polygon(ctx,points,fill,stroke){ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fillStyle=fill;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=1.5;ctx.stroke();}}
  function aimArc(){
    if(!model.selection||!model.sim.support)return [];
    const s=model.sim.spec,p=model.sim.p,pv=velocity(model.sim.platform(model.sim.support),model.sim.tick*10),aim=chartWorld(model.world,model.selection.point);
    const v=[(aim[0]-p[0])/s.aim_seconds+pv[0]*s.inherit,s.jump_speed+pv[1]*s.inherit,(aim[1]-p[2])/s.aim_seconds+pv[2]*s.inherit];
    if(Math.hypot(v[0],v[2])>s.speed_limit+1e-8)return [];
    // Cover the same 3.2 seconds as the announced lift rails. An elevated
    // downward hop can last longer than the nominal 1.6-second aim scale.
    return Array.from({length:41},(_,i)=>{const k=i*8,h=k*.01;return [p[0]+v[0]*h,p[1]+v[1]*h-s.gravity*.00005*k*(k+1),p[2]+v[2]*h];}).filter(p=>p[1]>=s.fall_y);
  }
  function drawChart(){
    const ctx=model.chart.getContext('2d'),w=model.world,t=model.sim.tick*10;
    ctx.fillStyle='#122625';ctx.fillRect(0,0,1000,290);
    ctx.strokeStyle='#29413c';ctx.lineWidth=1;
    for(let x=25;x<1000;x+=40){ctx.beginPath();ctx.moveTo(x,22);ctx.lineTo(x,268);ctx.stroke();}
    for(let y=25;y<290;y+=40){ctx.beginPath();ctx.moveTo(25,y);ctx.lineTo(975,y);ctx.stroke();}
    for(const platform of w.platforms){
      const c=center(platform,t),s=chartPoint(w,[c[0],c[2]]),a=chartPoint(w,[c[0]-platform.half[0],c[2]-platform.half[1]]),b=chartPoint(w,[c[0]+platform.half[0],c[2]+platform.half[1]]);
      if(platform.motion){
        const trail=[],future=[];
        for(let dt=-600;dt<=0;dt+=100){const p=center(platform,Math.max(0,t+dt));trail.push(chartPoint(w,[p[0],p[2]]));}
        path(ctx,trail,'#f7e0aa',3);
        if(model.surveyed.has(platform.id)){
          for(let dt=0;dt<=w.preview_ms;dt+=200){const p=center(platform,t+dt);future.push(chartPoint(w,[p[0],p[2]]));}
          path(ctx,future,platform.color,2,[3,5]);
          [800,1600,2400,3200].forEach((dt,i)=>{const p=center(platform,t+dt),q=chartPoint(w,[p[0],p[2]]);ctx.strokeStyle=platform.color;ctx.beginPath();ctx.arc(...q,4+i,0,Math.PI*2);ctx.stroke();});
        }
      }
      ctx.fillStyle=platform.color+'66';ctx.fillRect(...a,b[0]-a[0],b[1]-a[1]);ctx.strokeStyle=platform.color;ctx.lineWidth=2;ctx.strokeRect(...a,b[0]-a[0],b[1]-a[1]);
      ctx.fillStyle='#eee5cc';ctx.font='bold 12px ui-monospace,monospace';ctx.textAlign='center';ctx.fillText(platform.id==='quay'?'QUAY':platform.id==='hearth'?'FIRE':platform.id.slice(5),s[0],a[1]-9);
      if(platform.motion&&!model.surveyed.has(platform.id)){
        ctx.fillStyle='#ffe4a6';ctx.font='bold 11px ui-monospace,monospace';ctx.fillText('SURVEY ?',s[0],s[1]+4);
      }
    }
    const p=chartPoint(w,[model.sim.p[0],model.sim.p[2]]);
    if(model.selection){
      path(ctx,[p,model.selection.point],'#ffe6a5',2);const arc=aimArc();path(ctx,arc.map(a=>chartPoint(w,[a[0],a[2]])),'#fff4cd',2,[8,4]);
      [10,20,30,40].forEach((k,i)=>{if(!arc[k])return;const q=chartPoint(w,[arc[k][0],arc[k][2]]);ctx.strokeStyle='#fff4cd';ctx.beginPath();ctx.arc(...q,4+i,0,Math.PI*2);ctx.stroke();});
    }
    ctx.fillStyle='#fff3c6';ctx.strokeStyle='#e99c53';ctx.lineWidth=3;ctx.beginPath();ctx.arc(...p,13,0,Math.PI*2);ctx.fill();ctx.stroke();
    ctx.fillStyle='#56371c';ctx.font='bold 12px ui-monospace';ctx.textAlign='center';ctx.fillText('◆',p[0],p[1]+4);
    // This small outlined footprint is the physical collision extent. The
    // larger white circle is a selectable courier marker for readable input.
    const boot=chartPoint(w,[model.sim.p[0]+model.sim.spec.radius,model.sim.p[2]+model.sim.spec.radius]);
    ctx.strokeStyle='#fff7d9';ctx.lineWidth=1.5;ctx.beginPath();ctx.ellipse(...p,boot[0]-p[0],boot[1]-p[1],0,0,Math.PI*2);ctx.stroke();
  }
  function drawScene(){
    const canvas=model.scene,ctx=canvas.getContext('2d'),w=model.world,t=model.sim.tick*10;
    const horizon=ctx.createLinearGradient(0,0,0,330);horizon.addColorStop(0,'#1d3037');horizon.addColorStop(.8,'#37443c');horizon.addColorStop(1,'#1b2925');ctx.fillStyle=horizon;ctx.fillRect(0,0,1000,330);
    // One affine orthographic projection for all visible physical surfaces.
    const sx=820/(w.chart.x_max-w.chart.x_min), project=p=>[70+(p[0]-w.chart.x_min)*sx+p[2]*9,263-p[1]*24+p[2]*8];
    ctx.fillStyle='#bdc4a522';for(let i=0;i<8;i++){ctx.beginPath();ctx.moveTo(i*170-150,235);ctx.lineTo(i*170-40,40+(i%3)*30);ctx.lineTo(i*170+150,260);ctx.fill();}
    const objects=w.platforms.map(p=>({p,c:center(p,t)})).sort((a,b)=>a.c[2]-b.c[2]);
    for(const {p,c} of objects){
      const rim=[[-p.half[0],-p.half[1]],[p.half[0],-p.half[1]],[p.half[0],p.half[1]],[-p.half[0],p.half[1]]].map(([x,z])=>project([c[0]+x,c[1],c[2]+z]));
      const base=project([p.center[0],-3.4,p.center[2]]),s=project(c);
      path(ctx,[base,[s[0],s[1]+8]],'#ad9a74',4);
      // Open lattice lift: downward boot contact catches the top plane. Open
      // sides/undersides are intentionally passable, not solid cube colliders.
      polygon(ctx,rim,p.color+'bb','#ecd9ac');
      for(let n=1;n<4;n++){const f=n/4;path(ctx,[[rim[0][0]+(rim[1][0]-rim[0][0])*f,rim[0][1]+(rim[1][1]-rim[0][1])*f],[rim[3][0]+(rim[2][0]-rim[3][0])*f,rim[3][1]+(rim[2][1]-rim[3][1])*f]],'#243830',2);}
      const trail=[];for(let dt=-600;dt<=0;dt+=100)trail.push(project(center(p,Math.max(0,t+dt))));path(ctx,trail,'#ffd99588',2);
      if(model.surveyed.has(p.id)){
        const future=[];for(let dt=0;dt<=w.preview_ms;dt+=200)future.push(project(center(p,t+dt)));path(ctx,future,p.color,2,[3,6]);
        [800,1600,2400,3200].forEach((dt,i)=>{const q=project(center(p,t+dt));ctx.strokeStyle=p.color;ctx.beginPath();ctx.arc(...q,3+i,0,Math.PI*2);ctx.stroke();});
      }
      ctx.textAlign='center';ctx.fillStyle='#f3e9c9';ctx.font='bold 11px ui-monospace';ctx.fillText(p.kind==='quay'?'QUAY':p.kind==='hearth'?'HEARTH':p.id.toUpperCase(),s[0],s[1]+26);
      if(p.kind==='hearth'){polygon(ctx,[[s[0]-13,s[1]-1],[s[0]-9,s[1]-21],[s[0]-1,s[1]-13],[s[0]+4,s[1]-32],[s[0]+14,s[1]-10],[s[0]+10,s[1]+2]],'#ffc769','#eb824c');}
    }
    const arc=aimArc();path(ctx,arc.map(project),'#fff4cd',3,[8,4]);
    [10,20,30,40].forEach((k,i)=>{if(!arc[k])return;const q=project(arc[k]);ctx.strokeStyle='#fff4cd';ctx.beginPath();ctx.arc(...q,3+i,0,Math.PI*2);ctx.stroke();});
    const a=project(model.sim.p);ctx.fillStyle='#f9e9bd';ctx.beginPath();ctx.arc(a[0],a[1]-26,7,0,Math.PI*2);ctx.fill();ctx.fillStyle='#eaaf61';ctx.fillRect(a[0]-7,a[1]-21,14,19);ctx.strokeStyle='#efe1bd';ctx.lineWidth=3;path(ctx,[[a[0]-5,a[1]-2],[a[0]-6,a[1]+1],[a[0]+5,a[1]-2],[a[0]+6,a[1]+1]],'#efe1bd',3);
    if(!model.sim.delivered){ctx.fillStyle='#ffd780';ctx.strokeStyle='#956537';ctx.lineWidth=2;ctx.fillRect(a[0]+4,a[1]-32,17,15);ctx.strokeRect(a[0]+4,a[1]-32,17,15);ctx.fillStyle='#8c532a';ctx.fillText('◆',a[0]+12,a[1]-20);}
    ctx.fillStyle='#eddfc5';ctx.textAlign='left';ctx.font='13px ui-monospace';ctx.fillText('LIFT TOPS CATCH DESCENDING BOOTS · OPEN LATTICE SIDES',22,22);
  }
  function draw(){
    if(!model)return;drawScene();drawChart();
    model.root.querySelector('#hc-cargo').textContent=model.sim.delivered?'BURNED':model.sim.active?'IN HAND':'READY';
    model.root.querySelector('#hc-support').textContent=model.sim.support?model.sim.support.toUpperCase():'AIRBORNE';
    model.root.querySelector('#hc-height').textContent=model.sim.p[1].toFixed(1);
    model.root.dataset.support=model.sim.support||'air';
    const cancelButton=model.root.querySelector('#hc-cancel');if(cancelButton)cancelButton.disabled=!model.selection||model.terminal||model.submitting;
    model.root.querySelector('#hc-start').disabled=model.sim.active||model.terminal;
    model.root.querySelector('#hc-seal').disabled=model.terminal;
    const burnButton=model.root.querySelector('#hc-burn');if(burnButton){burnButton.disabled=model.sim.delivered||model.terminal;burnButton.setAttribute('aria-disabled',burnButton.disabled?'true':'false');}
  }
  function animate(){draw();frame=requestAnimationFrame(animate);}
  function render(state,helpers){
    cancelAnimationFrame(frame);if(keyHandler)window.removeEventListener('keydown',keyHandler);
    document.body.dataset.mechanic=ID;
    const mode=state.control_condition.interaction;
    helpers.app.innerHTML=`<section class="hc-shell" data-interaction="${mode}" data-verdict=""><header><div><small>RAVINE POST / ${clean(state.challenge_id)}</small><h1>Hearthlift Courier V3</h1><p>Carry the ember crate across the moving stacks. Burn it at the hearth.</p></div><button id="hc-start">LOAD CRATE & ARM HOPS</button></header><main><div class="hc-world"><canvas id="hc-scene" width="1000" height="330" aria-label="Three dimensional lift garden"></canvas><div class="hc-chart-label"><b>OVERHEAD AIM CHART</b><span>Click a lift top marked SURVEY ? to inspect its motor<br>retained rail = next 3.2s · rings = 0.8 · 1.6 · 2.4 · 3.2s</span></div><canvas id="hc-chart" width="1000" height="290" aria-label="Overhead courier aim chart"></canvas></div><aside><small>SPRING BOOTS / EMBER POST</small><h2>Carry a little fire<br>over a resolved world.</h2><dl><dt>CARGO</dt><dd id="hc-cargo">READY</dd><dt>UNDERFOOT</dt><dd id="hc-support">QUAY</dd><dt>HEIGHT</dt><dd id="hc-height">0.0</dd></dl><div class="hc-instructions"><p>${mode==='full'?'Drag the white courier on the aim chart toward your intended landing spot. Release to hop.':'Click the white courier on the aim chart, then click your intended landing spot to hop.'}</p><p>Click each moving top in the overhead chart to read its concealed motor survey. The survey reveals its next 3.2s of motion in both views and remains retained while you decide. Inspect safely from the quay before hopping; inspection never launches the courier, and each deliberate hop resolves the next replay.</p><p>The aim vector sets speed for a nominal 1.6s hop. Height changes the actual landing time. Boots inherit lift motion. While aiming, the pale arc previews your chosen velocity. Its rings and the lift rings mark matching future times; it never snaps to a lift. Later turns enter the dotted rail in the next resolved replay. Aim ahead; the chart does not follow a selected lift.</p><p>Land with both boots inside a lift top. Open lattice sides allow upward passage. Falling, releasing away from the hearth, or rejected certification ends the episode. Aim previews, canceled aims and out-of-range feedback remain recoverable.</p><p>${mode==='full'?'E releases the crate. Escape cancels aiming.':'Use BURN CRATE to release. CANCEL AIM cancels aiming.'}</p></div><div class="hc-controls">${mode==='simplified'?'<button id="hc-cancel">CANCEL AIM</button><button id="hc-burn">BURN CRATE</button>':''}<button id="hc-seal">CERTIFY DELIVERY</button><div class="readout" data-status="idle">READY AT THE QUAY</div></div></aside></main><div class="hc-verdict"></div></section>`;
    model={state,helpers,mode,world:state.world,sim:new Physics(clone(state.world)),events:[],surveyed:new Set(),inspectionDown:null,selection:null,terminal:false,submitting:false,root:helpers.app.querySelector('.hc-shell'),chart:document.getElementById('hc-chart'),scene:document.getElementById('hc-scene')};
    model.episodeFailed=state.episode_failed===true||staticFailure();
    if(model.episodeFailed){model.terminal=true;model.root.dataset.verdict='fail';model.root.querySelector('.hc-verdict').textContent='FAIL · EPISODE ENDED';message(state.episode_feedback||'A failed submission already ended this episode.','error');}
    window.hearthliftCourierV3NonrealtimeModel=model;
    document.getElementById('hc-start').addEventListener('click',start);document.getElementById('hc-seal').addEventListener('click',seal);document.getElementById('hc-burn')?.addEventListener('click',burn);document.getElementById('hc-cancel')?.addEventListener('click',cancel);
    model.chart.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();if(mode==='full'){model.inspectionDown={point:point(e),pointer:e.pointerId};select(point(e),e.pointerId);if(model.selection)model.chart.setPointerCapture(e.pointerId);}});
    model.chart.addEventListener('pointermove',e=>{sync();if(model.selection&&(mode==='simplified'||model.selection.pointer===e.pointerId)){model.selection.point=point(e);draw();}});
    model.chart.addEventListener('pointerup',e=>{if(e.button!==0)return;if(mode==='simplified'){if(model.selection)launch(point(e));else{select(point(e));if(!model.selection)inspect(point(e));}draw();return;}if(model.selection?.pointer!==e.pointerId){if(model.inspectionDown?.pointer===e.pointerId&&Math.hypot(...point(e).map((x,i)=>x-model.inspectionDown.point[i]))<=8)inspect(point(e));model.inspectionDown=null;return;}model.inspectionDown=null;launch(point(e));try{model.chart.releasePointerCapture(e.pointerId);}catch(_){}});
    model.chart.addEventListener('pointercancel',cancel);model.chart.addEventListener('lostpointercapture',()=>{if(mode==='full'&&model.selection)cancel();});
    keyHandler=e=>{if(mode!=='full'||e.repeat)return;if(e.key.toLowerCase()==='e'){e.preventDefault();burn();}if(e.key==='Escape'){e.preventDefault();cancel();}};window.addEventListener('keydown',keyHandler);
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.hc-shell',render};
})();
