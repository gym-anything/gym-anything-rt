(() => {
  'use strict';
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  function noise(seed,index){let x=(seed^Math.imul(index+1,0x9e3779b9))>>>0;x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;return ((x^(x>>>16))>>>0)/4294967295*2-1;}
  function motion(seed,ms,span){const u=Math.max(0,ms)/span,n=Math.floor(u),f=u-n;return noise(seed,n)+(noise(seed,n+1)-noise(seed,n))*f*f*(3-2*f);}
  function center(g,ms){const m=g.motion;return [0,1].map(i=>g.center[i]+m.amplitude[i]*motion(m.seed+i*7919,ms,m.span_ms)).concat(g.center[2]);}
  function velocity(g,ms){const a=center(g,Math.max(0,ms-10)),b=center(g,ms+10),dt=(ms+10-Math.max(0,ms-10))/1000;return [0,1].map(i=>(b[i]-a[i])/dt);}
  function wind(w,ms){const s=w.physics;return [0,1].map(i=>s.wind*motion(s.wind_seed+i*7919,ms,s.wind_span_ms));}
  class Physics {
    constructor(world){this.world=world;this.tick=0;this.active=false;this.failed='';this.sunk=false;this.greens=Object.fromEntries(world.greens.map(g=>[g.id,g]));this.cards=Object.fromEntries(world.cards.map(c=>[c.id,c]));this.support=world.tee;this.p=center(this.greens[this.support],0);this.v=[0,0,0];this.used=[];this.flight=null;}
    snapshot(){return {tick:this.tick,active:this.active,failed:this.failed,sunk:this.sunk,support:this.support,p:this.p.map(x=>Math.round(x*1e6)/1e6),v:this.v.map(x=>Math.round(x*1e6)/1e6),used:[...this.used]};}
    shot(cardId,aim){
      if(!this.active||this.failed||this.sunk||!this.support)throw Error('No active stroke opportunity');
      const c=this.cards[cardId],g=this.greens[this.support];
      if(!c||this.used.includes(cardId))throw Error('Card unavailable');
      if(g.surface==='sand'&&c.kind!=='loft')throw Error('Sand needs a loft card');
      if(aim.length!==2||!aim.every(Number.isFinite)||aim[0]<0||aim[0]>1000||aim[1]<0||aim[1]>540)throw Error('Aim outside map');
      const v=[0,1].map(i=>(aim[i]-this.p[i])/c.seconds);
      if(Math.hypot(...v)>c.max_speed)throw Error('Aim exceeds card reach');
      const inherited=velocity(g,this.tick*10);this.v=v.map((x,i)=>x+this.world.physics.inherit*inherited[i]).concat(c.vz);
      this.used.push(cardId);this.flight={origin:this.support,start:this.tick};this.support=null;
      // A deliberate stroke is the only source of task-clock progress.  The
      // fixed card flight resolves synchronously into the next stable state.
      this.actionTransition=true;
      try{this.advance(this.tick+Math.round(c.seconds*100));}
      finally{this.actionTransition=false;}
      if(!this.failed&&!this.sunk&&this.support===null)this.failed='Missed landing';
    }
    advance(end){
      if(!this.actionTransition){if(end!==this.tick)throw Error('Waiting cannot advance task time');return;}
      const s=this.world.physics,r=s.radius;
      while(this.tick<end&&!this.failed&&!this.sunk){
        const before=[...this.p],old=this.tick*10;this.tick++;const ms=this.tick*10;
        if(this.active&&ms>=s.play_time_ms){this.failed='Course time exhausted';break;}
        if(this.support){const a=center(this.greens[this.support],old),b=center(this.greens[this.support],ms);this.p=this.p.map((x,i)=>x+b[i]-a[i]);continue;}
        const w=wind(this.world,ms);for(const i of [0,1]){this.v[i]+=w[i]*.01;this.p[i]+=this.v[i]*.01;}
        this.v[2]-=s.gravity*.01;this.p[2]+=this.v[2]*.01;
        const hits=[];
        if(this.v[2]<0)for(const g of Object.values(this.greens)){
          const z=g.center[2];if(before[2]>=z&&this.p[2]<=z){const f=(before[2]-z)/(before[2]-this.p[2]),c=center(g,old+f*10),p=[0,1].map(i=>before[i]+(this.p[i]-before[i])*f);
            if(p.every((x,i)=>Math.abs(x-c[i])<=g.half[i]+r))hits.push({f,g,p,c});}
        }
        if(hits.length){
          const first=hits.reduce((a,b)=>a.f<=b.f?a:b);
          // Match the visible terrain order at the first contacted height.
          // An overlapping coplanar edge cannot invalidate a whole-ball fit.
          const fits=hits.filter(h=>h.g.center[2]===first.g.center[2]&&h.p.every((x,i)=>Math.abs(x-h.c[i])+r<=h.g.half[i]));
          if(!fits.length){this.failed='Ball clipped the green edge';break;}
          const {g,p,c}=fits[fits.length-1];
          this.p=[...p,g.center[2]];this.support=g.id;this.v=[0,0,0];this.flight=null;
          if(g.id===this.world.cup&&Math.hypot(p[0]-c[0],p[1]-c[1])+r<=this.world.cup_radius){if(this.used.length===Object.keys(this.cards).length)this.sunk=true;else this.failed='Cup reached with unspent cards';}
          else if(this.used.length===Object.keys(this.cards).length)this.failed='Hand exhausted outside the cup';
          else if(g.surface==='sand'&&!Object.values(this.cards).some(c=>c.kind==='loft'&&!this.used.includes(c.id)))this.failed='No LOFT cards remain on sand';
          break;
        }
        if(this.p[2]<-180||this.p[0]<-100||this.p[0]>1100||this.p[1]<-100||this.p[1]>640)this.failed='Ball fell into the clouds';
      }
    }
  }
  let model=null,raf=0;
  const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const record=(kind,extra={})=>model.events.push({seq:model.events.length+1,tick:model.sim.tick,kind,...extra});
  function sync(){if(!model||model.terminal)return;if(model.sim.failed)finish(model.sim.failed);}
  const projection=p=>[180+.55*p[0]-.22*p[1],25+.10*p[0]+.24*p[1]-.30*p[2]];
  function polygon(ctx,ps,color){ctx.beginPath();ps.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#3d6663';ctx.lineWidth=1;ctx.stroke();}
  function draw(){
    if(!model)return;
    const w=model.state.world,t=model.sim.tick*10;
    const map=document.querySelector('#cc-map').getContext('2d'),iso=document.querySelector('#cc-iso').getContext('2d');
    for(const [ctx,width,height] of [[map,1000,540],[iso,800,260]]){const grad=ctx.createLinearGradient(0,0,0,height);grad.addColorStop(0,'#b9d7de');grad.addColorStop(1,'#e3ebe2');ctx.fillStyle=grad;ctx.fillRect(0,0,width,height);ctx.strokeStyle='#ffffff44';ctx.lineWidth=1;for(let x=0;x<width;x+=50){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}}
    for(const g of w.greens){
      const c=center(g,t),[hx,hy]=g.half,color=g.surface==='cup'?'#edcf82':g.surface==='sand'?'#ead3b0':'#77b89b';
      map.fillStyle=color;map.fillRect(c[0]-hx,c[1]-hy,hx*2,hy*2);map.strokeStyle='#315c60';map.lineWidth=2;map.strokeRect(c[0]-hx,c[1]-hy,hx*2,hy*2);
      // Draw tracks above the solid terrain so the bounded recent history
      // remains visible even when movement stays inside a green's footprint.
      map.strokeStyle='#975f3f';map.lineWidth=3;map.setLineDash([]);map.beginPath();for(let dt=-240;dt<=0;dt+=60){const q=center(g,t+dt);dt===-240?map.moveTo(q[0],q[1]):map.lineTo(q[0],q[1]);}map.stroke();
      map.strokeStyle='#36596b99';map.lineWidth=2;map.setLineDash([4,7]);map.beginPath();for(let dt=0;dt<=w.forecast_ms;dt+=60){const q=center(g,t+dt);dt===0?map.moveTo(q[0],q[1]):map.lineTo(q[0],q[1]);}map.stroke();map.setLineDash([]);
      map.fillStyle='#304f52';map.font='bold 22px sans-serif';map.fillText(`h${g.center[2]}`,c[0]-hx,Math.min(534,c[1]+hy+25));
      // Forecast markers stay above the turf instead of being hidden by it.
      map.strokeStyle='#fdf7df';map.lineWidth=3;for(let dt=200;dt<=w.forecast_ms;dt+=200){const p=center(g,t+dt);map.beginPath();map.arc(p[0],p[1],dt%1000===0?7:4,0,Math.PI*2);map.stroke();if(dt%1000===0){map.fillStyle='#27484e';map.font='bold 20px sans-serif';map.fillText(`+${dt/1000}`,p[0]+9,p[1]-8);}}
      const top=[[-hx,-hy],[hx,-hy],[hx,hy],[-hx,hy]].map(([x,y])=>projection([c[0]+x,c[1]+y,c[2]]));
      const low=top.map(p=>[p[0],p[1]+18+c[2]*.12]);polygon(iso,[top[1],top[2],low[2],low[1]],'#559080');polygon(iso,[top[2],top[3],low[3],low[2]],'#426f70');polygon(iso,top,color);
      const p=projection(c);iso.fillStyle='#26484c';iso.font='bold 11px sans-serif';iso.fillText(`h${g.center[2]}`,p[0]-8,p[1]+4);
      if(g.id===w.cup){map.strokeStyle='#805833';map.lineWidth=3;map.beginPath();map.arc(c[0],c[1],w.cup_radius,0,Math.PI*2);map.stroke();iso.strokeStyle='#855736';iso.beginPath();for(let i=0;i<=64;i++){const a=i*Math.PI/32,q=projection([c[0]+w.cup_radius*Math.cos(a),c[1]+w.cup_radius*Math.sin(a),c[2]]);i?iso.lineTo(...q):iso.moveTo(...q);}iso.stroke();iso.strokeStyle='#884831';iso.lineWidth=2;iso.beginPath();iso.moveTo(p[0],p[1]);iso.lineTo(p[0],p[1]-32);iso.stroke();polygon(iso,[[p[0],p[1]-32],[p[0]+20,p[1]-25],[p[0],p[1]-18]],'#d36b4d');}
    }
    // The same physical projectile in both cameras, with altitude separated
    // from its ground shadow in the side view.
    const b=model.sim.p,p=projection(b);iso.fillStyle='#28444a33';const sh=projection([b[0],b[1],0]);iso.beginPath();iso.ellipse(sh[0],sh[1]+7,10,4,0,0,Math.PI*2);iso.fill();
    for(const [ctx,q,r] of [[map,b,7],[iso,p,7]]){ctx.fillStyle='#fffaf0';ctx.strokeStyle='#815036';ctx.lineWidth=2;ctx.beginPath();ctx.arc(q[0],q[1],r,0,Math.PI*2);ctx.fill();ctx.stroke();}
    // Forecasted horizontal acceleration, independent of card choice.
    const wc=document.querySelector('#cc-wind').getContext('2d');wc.fillStyle='#f4f3e7';wc.fillRect(0,0,300,110);wc.strokeStyle='#9eaaa2';wc.beginPath();wc.moveTo(20,55);wc.lineTo(290,55);wc.stroke();
    ['#32789d','#bd6949'].forEach((color,i)=>{wc.strokeStyle=color;wc.lineWidth=2;wc.beginPath();for(let dt=-240;dt<=w.forecast_ms;dt+=30){const x=20+(dt+240)/(w.forecast_ms+240)*270,y=55-wind(w,t+dt)[i]/Math.max(1,w.physics.wind)*38;dt===-240?wc.moveTo(x,y):wc.lineTo(x,y);}wc.stroke();});
    wc.fillStyle='#45605d';wc.font='11px sans-serif';wc.fillText(`±${w.physics.wind} acceleration · X blue / Y rust`,12,14);for(const dt of [0,1000,2000]){const x=20+(dt+240)/(w.forecast_ms+240)*270;wc.fillText(dt?`+${dt/1000}s`:'now',x-12,104);}
    document.querySelector('#cc-counter').textContent=`${model.sim.used.length} / ${w.cards.length}`;
    document.querySelector('#cc-status').textContent=model.terminal?'COURSE ENDED':model.sim.sunk?'BALL SUNK · CERTIFY':model.sim.failed?'FAIL · '+model.sim.failed:model.sim.support?(model.sim.active?'ON '+model.sim.greens[model.sim.support].surface.toUpperCase():'READY ON THE TEE'):'BALL IN FLIGHT';
    document.querySelector('#cc-start').disabled=model.sim.active||model.terminal;
    document.querySelector('#cc-seal').disabled=model.terminal;
    for(const c of w.cards){const node=document.querySelector(`[data-card="${c.id}"]`);node.disabled=model.sim.used.includes(c.id)||model.terminal;node.classList.toggle('selected',model.selected===c.id||model.drag===c.id);}
  }
  function animate(){sync();draw();raf=requestAnimationFrame(animate);}
  function mapPoint(e){const r=document.querySelector('#cc-map').getBoundingClientRect();return [(e.clientX-r.left)*1000/r.width,(e.clientY-r.top)*540/r.height].map(x=>Math.round(x*1000)/1000);}
  function shot(card,p){
    if(model.terminal)return;sync();if(model.terminal)return;
    const shotTick=model.sim.tick;
    try{model.sim.shot(card,p);model.events.push({seq:model.events.length+1,tick:shotTick,kind:'shot',card_id:card,point:p,input_source:model.source});model.selected=model.drag=null;if(model.sim.failed)finish(model.sim.failed);}
    catch(e){record('cancel',{input_source:model.source});model.selected=model.drag=null;model.helpers.setReadout(e.message,'idle');}
    draw();
  }
  async function finish(reason=''){
    if(model.terminal)return;
    model.terminal=true;model.drag=model.selected=null;
    record('seal',{input_source:'certify_button'});
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,physics_revision:model.state.physics_revision,control_condition:model.state.control_condition,interaction_mode:model.mode,events:model.events,final_state:model.sim.snapshot(),completed:model.sim.sunk&&!model.sim.failed&&!reason};
    model.payload=payload;
    document.querySelector('#cc-verdict').textContent=reason?'FAIL · '+reason:'VERIFYING';
    document.querySelector('#cc-verdict').hidden=false;
    try{const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)}),g=await r.json();model.grade=g;document.querySelector('#cc-verdict').textContent=g.passed?'PASS · EXACT HAND / BALL SUNK':'FAIL · '+(reason||'Certification rejected');model.helpers.setReadout(g.passed?'PASS':'FAIL',g.passed?'passed':'error');}
    catch(e){document.querySelector('#cc-verdict').textContent='VERIFIER ERROR';model.helpers.setReadout(e.message,'error');}
    draw();
  }
  async function render(state,helpers){
    cancelAnimationFrame(raf);const mode=state.control_condition.interaction;
    model={state,helpers,mode,source:mode==='full'?'card_drag':'card_click',sim:new Physics(state.world),events:[],selected:null,drag:null,terminal:false};window.cloudstepCaddieNonRealtimeModel=model;
    document.body.dataset.mechanic='cloudstep-caddie-nonrealtime';
    helpers.app.innerHTML=`<section class="cc-game"><header><div><span>THE ACTION LINKS</span><h1>Cloudstep Caddie V2</h1></div><div>EXACT HAND <b id="cc-counter"></b></div></header><main><section class="cc-cameras"><canvas id="cc-iso" width="800" height="260"></canvas><div class="cc-map-label">AIM MAP · stable between strokes / forecast during next card flight</div><canvas id="cc-map" width="1000" height="540" aria-label="golf bearing and landing map"></canvas></section><aside><p>${state.world.cards.length===1?'Use the single CHIP to land inside the cup. This level course has no wind or departure momentum. Its fixed flight resolves when you release the stroke.':`Land on the greens, then sink the ball with every card spent. Sand needs LOFT. Higher landings shorten the flight. Wind and ${Math.round(state.world.physics.inherit*100)}% of the departing green's velocity carry the ball sideways during the next stroke.`}</p><p>${mode==='full'?'Drag a card onto a coordinate in the aim map; release to strike.':'Click a card, then click a coordinate in the aim map to strike.'} The coordinate sets a bearing and speed, not a tracked destination. Greens hold their current positions while you choose; each deliberate stroke resolves one fixed flight.</p><div class="cc-hand">${state.world.cards.map(c=>`<button data-card="${c.id}"><b>${esc(c.label)}</b><strong>${c.seconds.toFixed(1)}s</strong><small>apex ${Math.round(c.vz*c.vz/800)}<br>reach ${Math.round(c.max_speed*c.seconds)}</small></button>`).join('')}</div><div class="cc-wind-label">WIND · NEXT STROKE FORECAST</div><canvas id="cc-wind" width="300" height="110"></canvas><button id="cc-start">START COURSE</button><button id="cc-seal">CERTIFY SUNKEN BALL</button><p class="cc-warning">A miss, premature cup or empty hand outside the cup ends this episode. No reset or stop.</p></aside></main><footer><span id="cc-status"></span><span>Same-height overlaps allow any whole-ball fit.</span><div class="readout">Read the stable state and choose a stroke.</div></footer><div id="cc-verdict" hidden></div></section>`;
    document.querySelector('#cc-start').onclick=()=>{sync();if(!model.sim.active&&!model.terminal){model.sim.active=true;record('start',{input_source:'start_button'});document.querySelector('#cc-start').disabled=true;draw();}};
    document.querySelector('#cc-seal').onclick=()=>{sync();finish(model.sim.sunk?'':'Incomplete certification');};
    for(const c of state.world.cards){const button=document.querySelector(`[data-card="${c.id}"]`);
      button.addEventListener('pointerdown',e=>{sync();if(e.button!==0||!model.sim.active||!model.sim.support||model.terminal||model.sim.sunk||button.disabled||mode!=='full')return;e.preventDefault();button.setPointerCapture(e.pointerId);model.drag=c.id;record('drag_start',{card_id:c.id,input_source:model.source});draw();});
      button.addEventListener('pointerup',e=>{if(model.drag!==c.id)return;sync();if(model.terminal)return;const p=mapPoint(e);if(p[0]>=0&&p[0]<=1000&&p[1]>=0&&p[1]<=540)shot(c.id,p);else{record('cancel',{input_source:model.source});model.drag=null;draw();}});
      button.addEventListener('pointercancel',()=>{if(model.drag===c.id&&!model.terminal){sync();record('cancel',{input_source:model.source});model.drag=null;draw();}});
      button.addEventListener('click',()=>{sync();if(mode!=='simplified'||!model.sim.active||!model.sim.support||model.terminal||model.sim.sunk||button.disabled)return;model.selected=c.id;record('select',{card_id:c.id,input_source:model.source});draw();});
    }
    document.addEventListener('pointerup',e=>{if(mode!=='full'||!model.drag||model.terminal)return;const card=model.drag;const p=mapPoint(e);if(p[0]>=0&&p[0]<=1000&&p[1]>=0&&p[1]<=540)shot(card,p);else{record('cancel',{input_source:model.source});model.drag=null;draw();}});
    document.querySelector('#cc-map').addEventListener('click',e=>{if(mode==='simplified'&&model.selected)shot(model.selected,mapPoint(e));});
    draw();raf=requestAnimationFrame(animate);
  }
  window.CloudstepCaddieNonRealtimePhysics=Physics;
  window.CloudstepCaddieNonRealtimeMotion={center,velocity,wind};
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};window.GymAnythingRTMechanics.cloudstep_caddie_nonrealtime={rootSelector:'.cc-game',render};
})();
