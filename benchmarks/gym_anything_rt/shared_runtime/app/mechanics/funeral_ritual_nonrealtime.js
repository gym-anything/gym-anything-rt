(() => {
  'use strict';
  const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  function noise(seed,index) {
    let x=(seed ^ Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function motion(seed,ms,span) {
    const u=Math.max(0,ms)/span,i=Math.floor(u),f=u-i;
    return noise(seed,i)+(noise(seed,i+1)-noise(seed,i))*f*f*(3-2*f);
  }
  function wind(s,i,ms) { return s.candles[i].x+s.parameters.wind_amplitude*motion(s.candles[i].wind_seed,ms,s.parameters.wind_span_ms); }
  function flowerPoint(s,i,ms) {
    const f=s.flowers[i]; return [f.x+34*motion(f.motion_seed,ms,4700),f.y+18*motion(f.motion_seed+7919,ms,5300)];
  }
  function socketPoint(s,i,ms) {
    const f=s.sockets[i]; return [f.x+s.parameters.socket_amplitude*motion(f.motion_seed,ms,4200),f.y+16*motion(f.motion_seed+7919,ms,5700)];
  }
  const moss=Array.from({length:6},(_,i)=>[414+(i%3)*60,257+Math.floor(i/3)*29,52,23]);
  const inside=(p,r)=>p[0]>=r[0]&&p[0]<=r[0]+r[2]&&p[1]>=r[1]&&p[1]<=r[1]+r[3];
  class Vigil {
    constructor(s) {
      this.s=s; this.ms=0; this.active=false; this.inspected=false; this.moss=new Set();
      this.targets=s.candles.map(c=>c.x);this.x=[...this.targets];this.v=this.x.map(()=>0);this.health=this.x.map(()=>1);
      this.offered=[];this.carried=null;this.hold=null;this.failed='';this.sealed=false;
    }
    advance(end) {
      if(!this.active)return;
      const p=this.s.parameters,r=this.s.ritual;
      while(this.ms+20<=end&&!this.failed&&!this.sealed) {
        this.ms+=20;
        this.s.candles.forEach((c,i)=>{
          if(p.shield_response==='direct'){this.x[i]=this.targets[i];this.v[i]=0;}
          else {
            const a=clamp((this.targets[i]-this.x[i])*25-this.v[i]*10,-p.shield_acceleration,p.shield_acceleration);
            this.v[i]=clamp(this.v[i]+a*.02,-p.shield_speed,p.shield_speed);
            this.x[i]=clamp(this.x[i]+this.v[i]*.02,c.x-130,c.x+130);
            if(this.x[i]===c.x-130||this.x[i]===c.x+130)this.v[i]=0;
          }
          const protectedNow=Math.abs(this.x[i]-wind(this.s,i,this.ms))<=p.shield_width/2;
          this.health[i]=clamp(this.health[i]+.02*(protectedNow?r.flame_recovery_per_s:-r.flame_loss_per_s),0,1);
          if(this.health[i]<=0)this.failed='A candle went out.';
        });
        if(this.ms>=r.max_active_ms)this.failed='The vigil was abandoned.';
      }
    }
    action(kind,point,mode,item=null) {
      if(this.failed||this.sealed)throw Error('terminal episode');
      const s=this.s;
      if(kind==='inspect') {
        if(!inside(point,[380,249,240,89])||this.active)throw Error('inspect the stone');this.inspected=true;
      } else if(kind==='brush'||kind==='clear') {
        if(!this.inspected||this.active)throw Error('inspect before brushing');
        if(kind==='clear') {
          if(mode!=='simplified'||!inside(point,[400,300,200,28]))throw Error('wrong brush proxy');this.moss=new Set([0,1,2,3,4,5]);
        } else {
          if(mode!=='full')throw Error('wrong brush surface');moss.forEach((r,i)=>{if(inside(point,r))this.moss.add(i);});
        }
      } else if(kind==='light') {
        if(this.active||this.moss.size!==6)throw Error('uncover the memorial before lighting');
        if(!s.candles.some(c=>inside(point,[c.x-15,c.y-14,30,38])))throw Error('light a candle');this.active=true;
      } else if(kind==='seal'&&!this.active)this.failed='The vigil was incomplete.';
      else if(!this.active)throw Error('light the candles first');
      else if(kind.startsWith('shield_')) {
        if(!Number.isInteger(item)||item<0||item>=this.x.length)throw Error('unknown shield');
        const c=s.candles[item];
        if(kind==='shield_target') {
          if(mode!=='simplified'||!inside(point,[c.x-130,108,260,34]))throw Error('click this shield rail');
          this.targets[item]=clamp(point[0],c.x-130,c.x+130);
        } else {
          if(mode!=='full')throw Error('wrong shield input');
          if(kind==='shield_start') {
            if(this.hold||this.carried!==null||!inside(point,[this.x[item]-s.parameters.shield_width/2,108,s.parameters.shield_width,34]))throw Error('drag the actual shield');
            this.hold=['shield',item];
          } else if(!this.hold||this.hold[0]!=='shield'||this.hold[1]!==item)throw Error('shield is not held');
          if(kind==='shield_move')this.targets[item]=clamp(point[0],c.x-130,c.x+130);
          if(kind==='shield_end')this.hold=null;
        }
        if((kind==='shield_target'||kind==='shield_move')&&s.parameters.shield_response==='direct'){this.x[item]=this.targets[item];this.v[item]=0;}
      } else if(kind==='pick') {
        if(!Number.isInteger(item)||this.offered.includes(item)||item<0||item>=s.flowers.length||this.carried!==null||this.hold)throw Error('unavailable flower');
        if(Math.hypot(point[0]-flowerPoint(s,item,this.ms)[0],point[1]-flowerPoint(s,item,this.ms)[1])>27)throw Error('pickup misses the visible flower');
        if(item!==s.order[this.offered.length])this.failed='The tribute order was broken.';
        else {this.carried=item;if(mode==='full')this.hold=['flower',item];}
      } else if(kind==='offer'||kind==='cancel') {
        if(this.carried===null)throw Error('no flower is carried');
        if(mode==='full'&&(!this.hold||this.hold[0]!=='flower'||this.hold[1]!==this.carried))throw Error('flower is not held');
        if(kind==='cancel')this.carried=this.hold=null;
        else {
          const p=socketPoint(s,this.offered.length,this.ms);
          if(Math.hypot(point[0]-p[0],point[1]-p[1])+s.ritual.flower_radius>s.parameters.socket_radius)this.failed='A flower fell outside its resting place.';
          else {this.offered.push(this.carried);this.carried=this.hold=null;}
        }
      } else if(kind==='seal') {
        if(this.ms<s.ritual.vigil_ms||this.offered.length!==s.order.length||this.carried!==null||this.hold)this.failed='The vigil was incomplete.';
        else this.sealed=true;
      } else throw Error('unknown action');
    }
  }
  // Read-only planning hooks for diagnostics; they are never exposed as agent actions.
  window.FuneralVigilPhysics={Vigil,wind,flowerPoint,socketPoint,motion};
  let model=null,frame=0;
  const clean=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  // This counterpart has a task-local clock. It advances only after an
  // accepted active control, so an idle live browser cannot move the puzzle.
  const elapsed=()=>model?model.physics.ms:0;
  function sync() {if(model&&!model.terminal&&model.physics.failed)finish();}
  function event(kind,point,item=null) {
    if(!model||model.terminal)return;
    sync();if(model.terminal)return;
    const wasActive=model.physics.active;
    const t=elapsed();
    try {model.physics.action(kind,point,model.mode,item);}catch(error){model.helpers.setReadout(error.message,'idle');draw();return;}
    model.events.push({sequence:model.events.length+1,kind,point:point.map(x=>Math.round(x*1000)/1000),item,t_ms:t,input_source:model.mode});
    const commits=model.mode!=='full'||kind==='shield_end'||kind==='offer'||kind==='cancel';
    if(wasActive&&commits&&!model.physics.failed&&!model.physics.sealed) {
      model.physics.advance(model.physics.ms+model.state.ritual.action_step_ms);
    }
    if(model.physics.failed||model.physics.sealed)finish();draw();
  }
  async function finish() {
    if(model.terminal)return;
    model.terminal=true;
    const p=model.physics;
    model.helpers.setReadout(p.failed?'FAIL · '+p.failed:'VERIFYING THE VIGIL',p.failed?'error':'pending');
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,revision:model.state.revision,interaction_mode:model.mode,events:model.events,final_t_ms:elapsed(),completed:p.sealed&&!p.failed})});
      model.result=await response.json();
      model.helpers.setReadout(model.result.passed?'PASS · THE LIGHT REMAINS':'FAIL · '+(p.failed||'Vigil rejected'),model.result.passed?'passed':'error');
    }catch(error){model.helpers.setReadout('VERIFIER ERROR · '+error.message,'error');}
    draw();
  }
  function point(e) {
    const r=document.querySelector('#vigil-canvas').getBoundingClientRect();
    return [clamp((e.clientX-r.x)*1000/r.width,0,1000),clamp((e.clientY-r.y)*580/r.height,0,580)];
  }
  function down(e) {
    if(e.button!==0||model.terminal)return;e.preventDefault();sync();if(model.terminal)return;
    const p=point(e),v=model.physics,s=model.state;
    model.pointer=p;
    if(!v.active) {
      if(!v.inspected&&inside(p,[380,249,240,89]))event('inspect',p);
      else if(v.moss.size<6) {
        if(model.mode==='simplified') {if(inside(p,[400,300,200,28]))event('clear',p);}
        else if(moss.some(r=>inside(p,r))){model.brushing=true;event('brush',p);e.currentTarget.setPointerCapture(e.pointerId);}
      } else if(s.candles.some(c=>inside(p,[c.x-15,c.y-14,30,38])))event('light',p);
      return;
    }
    const shield=s.candles.findIndex((c,i)=>inside(p,model.mode==='full'?[v.x[i]-s.parameters.shield_width/2,108,s.parameters.shield_width,34]:[c.x-130,108,260,34]));
    if(shield>=0) {
      event(model.mode==='full'?'shield_start':'shield_target',p,shield);
      if(v.hold&&v.hold[0]==='shield')e.currentTarget.setPointerCapture(e.pointerId);
      return;
    }
    if(model.mode==='simplified'&&v.carried!==null){event('offer',p);return;}
    const flower=s.flowers.findIndex(f=>!v.offered.includes(f.id)&&Math.hypot(p[0]-flowerPoint(s,f.id,v.ms)[0],p[1]-flowerPoint(s,f.id,v.ms)[1])<=27);
    if(flower>=0) {event('pick',p,flower);if(v.hold)e.currentTarget.setPointerCapture(e.pointerId);}
  }
  function move(e) {
    if(model.terminal)return;sync();if(model.terminal)return;
    const p=point(e);model.pointer=p;
    if(model.brushing)event('brush',p);
    else if(model.physics.hold?.[0]==='shield')event('shield_move',p,model.physics.hold[1]);
    draw();
  }
  function up(e,cancel=false) {
    model.brushing=false;if(model.terminal)return;
    const p=point(e),hold=model.physics.hold;
    if(hold?.[0]==='shield')event('shield_end',p,hold[1]);
    else if(hold?.[0]==='flower')event(cancel?'cancel':'offer',p);
    try{e.currentTarget.releasePointerCapture(e.pointerId);}catch(_){}
  }
  function flower(ctx,f,p,size=16) {
    ctx.save();ctx.translate(...p);ctx.fillStyle=f.color;
    for(let k=0;k<f.petals;k++){const a=k*2*Math.PI/f.petals;ctx.beginPath();ctx.ellipse(Math.cos(a)*size*.52,Math.sin(a)*size*.52,size*.48,size*.32,a,0,Math.PI*2);ctx.fill();}
    ctx.fillStyle='#f8efc4';ctx.beginPath();ctx.arc(0,0,size*.29,0,Math.PI*2);ctx.fill();ctx.restore();
  }
  function draw() {
    if(!model)return;
    const ctx=document.querySelector('#vigil-canvas').getContext('2d'),s=model.state,v=model.physics,t=v.ms;
    const bg=ctx.createLinearGradient(0,0,0,580);bg.addColorStop(0,'#15242d');bg.addColorStop(1,'#102c2b');ctx.fillStyle=bg;ctx.fillRect(0,0,1000,580);
    ctx.fillStyle='#d0c9ab';ctx.beginPath();ctx.arc(915,40,23,0,Math.PI*2);ctx.fill();ctx.fillStyle='#16262e';ctx.beginPath();ctx.arc(928,31,22,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#20403a';ctx.beginPath();ctx.moveTo(0,350);ctx.bezierCurveTo(220,285,330,350,500,340);ctx.bezierCurveTo(720,315,920,290,1000,350);ctx.lineTo(1000,580);ctx.lineTo(0,580);ctx.fill();
    ctx.strokeStyle='#829a9c22';ctx.lineWidth=1;for(let i=0;i<30;i++){const x=(i*73+t*.012)%1000;ctx.beginPath();ctx.moveTo(x,30);ctx.lineTo(x-11,70);ctx.stroke();}
    ctx.font='13px Georgia';ctx.textAlign='center';ctx.fillStyle='#b8d2ce';ctx.fillText(v.active?(s.flowers.length?'Keep every flame alive; complete the tribute below.':'Keep the flame alive. Follow the changing draft.'):'Grieve. Look closer.',500,22);
    s.candles.forEach((c,i)=>{
      const w=wind(s,i,t),half=s.parameters.shield_width/2;
      ctx.strokeStyle='#699caa';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(c.x-130,125);ctx.lineTo(c.x+130,125);ctx.stroke();
      // The vertical ribbon predicts the same draft that hits the flame. Its last point is +2s.
      ctx.beginPath();for(let k=0;k<=10;k++){const x=wind(s,i,t+k*200),y=95-k*3; k?ctx.lineTo(x,y):ctx.moveTo(x,y);}ctx.strokeStyle='#8fc3d4';ctx.lineWidth=3;ctx.stroke();
      ctx.fillStyle='#8fc3d4';ctx.beginPath();ctx.arc(w,95,5,0,Math.PI*2);ctx.fill();
      ctx.font='11px sans-serif';ctx.fillStyle='#abc3c8';ctx.fillText('DRAFT: ● NOW → TOP +2s',c.x,49);
      ctx.strokeStyle=Math.abs(v.x[i]-w)<=half?'#8bd7c066':'#e5977366';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(w,107);ctx.lineTo(w,143);ctx.lineTo(c.x,178);ctx.stroke();
      ctx.fillStyle='#aab6ae22';ctx.fillRect(v.targets[i]-half,108,2*half,34);
      ctx.fillStyle='#796957';ctx.strokeStyle='#e8c994';ctx.lineWidth=2;ctx.fillRect(v.x[i]-half,108,2*half,34);ctx.strokeRect(v.x[i]-half,108,2*half,34);
      ctx.fillStyle='#e8c994';ctx.fillRect(v.x[i]-13,119,26,3);ctx.fillRect(v.x[i]-13,128,26,3);
      ctx.fillStyle='#e1dbc7';ctx.fillRect(c.x-15,188,30,38);ctx.strokeStyle='#989c87';ctx.strokeRect(c.x-15,188,30,38);
      if(v.active&&v.health[i]>0){const h=26*v.health[i]+4;ctx.fillStyle='#facb79';ctx.shadowBlur=18;ctx.shadowColor='#efa04b';ctx.beginPath();ctx.ellipse(c.x+(w-c.x)*.06,185-h/2,7,h/2,-(w-c.x)/600,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;}
      ctx.fillStyle='#243d3b';ctx.fillRect(c.x-45,235,90,8);ctx.fillStyle=v.health[i]>.4?'#d9c48e':'#f59077';ctx.fillRect(c.x-45,235,90*v.health[i],8);
    });
    ctx.fillStyle='#5b6867';ctx.strokeStyle='#bcc5b0';ctx.lineWidth=2;ctx.beginPath();ctx.roundRect(380,249,240,89,12);ctx.fill();ctx.stroke();
    ctx.fillStyle='#e3ddc2';ctx.font='14px Georgia';ctx.fillText(s.epitaph,500,272);
    if(v.inspected) {
      s.order.forEach((id,i)=>flower(ctx,s.flowers[id],[500+(i-(s.order.length-1)/2)*43,307],12));
      if(model.mode==='simplified'&&v.moss.size<6){ctx.fillStyle='#446754';ctx.fillRect(400,300,200,28);ctx.fillStyle='#edf2d4';ctx.font='14px sans-serif';ctx.fillText('BRUSH THE MOSS',500,319);}
      else moss.forEach((r,i)=>{if(!v.moss.has(i)){ctx.fillStyle='#41604b';ctx.fillRect(...r);ctx.fillStyle='#779566';ctx.fillRect(r[0]+5,r[1]+5,r[2]-10,4);}});
    } else {ctx.fillStyle='#41604b';ctx.fillRect(397,257,206,66);ctx.fillStyle='#99ad86';ctx.font='16px Georgia';ctx.fillText('…',500,292);}
    if(v.moss.size===6&&!v.active){ctx.fillStyle='#dfd7b6';ctx.font='14px Georgia';ctx.fillText('Touch a candle to begin the vigil.',500,355);}
    s.flowers.forEach(f=>{
      if(v.offered.includes(f.id)||v.carried===f.id)return;
      const p=flowerPoint(s,f.id,t);
      ctx.strokeStyle='#719987';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(p[0],p[1]+16);ctx.lineTo(p[0]-5,p[1]+44);ctx.stroke();
      if(v.active){ctx.strokeStyle='#b9d2bf44';ctx.beginPath();ctx.arc(...p,27,0,Math.PI*2);ctx.stroke();}
      flower(ctx,f,p);
    });
    s.sockets.forEach((slot,i)=>{
      const p=socketPoint(s,i,t),r=s.parameters.socket_radius;
      ctx.fillStyle='#152e2c';ctx.strokeStyle=i===v.offered.length?'#efdbaf':'#67877c';ctx.lineWidth=i===v.offered.length?3:1;ctx.beginPath();ctx.arc(...p,r,0,Math.PI*2);ctx.fill();ctx.stroke();
      ctx.font='13px Georgia';ctx.fillStyle='#aac3b2';ctx.fillText(String(i+1),p[0],p[1]+r-8);
      flower(ctx,s.flowers[s.order[i]],p,v.offered.length>i?24:9);
    });
    if(v.carried!==null)flower(ctx,s.flowers[v.carried],model.pointer,s.ritual.flower_radius);
    ctx.fillStyle='#3f5b4e';ctx.fillRect(275,560,450,6);ctx.fillStyle='#e0c98b';ctx.fillRect(275,560,450*Math.min(1,t/s.ritual.vigil_ms),6);
    if(model.terminal){ctx.fillStyle='#102323dd';ctx.fillRect(270,245,460,125);ctx.fillStyle=v.failed?'#f5a58e':'#e1ddb3';ctx.font='38px Georgia';ctx.fillText(model.result?.passed?'PASS':v.failed?'FAIL':'VERIFYING',500,298);ctx.font='17px Georgia';ctx.fillText(v.failed||'The light remains.',500,337);}
    document.querySelector('#vigil-status').textContent=`${v.active?(Math.floor(t/100)/10).toFixed(1)+' / 30 s':'MEMORIAL'} · ${s.flowers.length?`${v.offered.length}/${s.order.length} FLOWERS`:'ONE FLAME'}`;
  }
  function animate(){draw();frame=requestAnimationFrame(animate);}
  async function render(state,helpers) {
    cancelAnimationFrame(frame);document.body.dataset.mechanic='funeral-ritual-v2';
    model={state,helpers,mode:state.control_condition?.interaction||'full',physics:new Vigil(state),events:[],terminal:false,result:null,pointer:[500,350],brushing:false};
    window.funeralVigilModel=model;
    helpers.app.innerHTML=`<section class="funeral-vigil"><header><div><span>THE LAST WATCH</span><h1>Funeral Ritual V2</h1></div><small id="vigil-status"></small></header><main><canvas id="vigil-canvas" width="1000" height="580" aria-label="Memorial, windbreaks, candles and flower offerings"></canvas><aside><h2>Grieve.</h2><p>Uncover the stone. Light the candles. Keep their flames alive for thirty seconds while laying flowers in the stone’s order.</p><p>The blue draft ribbon shows where the breeze meets each windbreak rail: bottom dot now, top end two seconds ahead. Move the brass shield across the draft.</p><p>${model.mode==='full'?'Brush the moss. Drag brass shields along their rails. Drag each flower into the next numbered resting place.':'Use BRUSH THE MOSS. Click a rail to steer its shield. Click a flower, then click inside the next numbered resting place.'}</p><p>Each accepted control advances the vigil by 0.4 seconds. Waiting leaves the visible draft, flames and resting places stable. A lost flame, wrong flower, missed placement, or incomplete farewell ends this vigil.</p><button id="vigil-seal">SAY FAREWELL</button><div class="readout"></div></aside></main></section>`;
    if(!state.flowers.length){
      const paragraphs=helpers.app.querySelectorAll('aside p'),direct=state.parameters.shield_response==='direct';
      paragraphs[0].textContent='Uncover the stone. Light the candle. Keep its flame alive for thirty seconds, then say farewell. There are no flower offerings in this vigil.';
      paragraphs[2].textContent=model.mode==='full'?'Brush the moss. Drag the brass shield along its rail.':'Use BRUSH THE MOSS. Click the rail to position the shield.';
      paragraphs[3].textContent=(direct?'The shield follows your input directly.':'The shield has inertia: aim ahead using the draft ribbon.')+' Each accepted control advances the vigil by 0.4 seconds; waiting leaves the visible state stable. A lost flame or incomplete farewell ends this vigil.';
      document.querySelector('#vigil-canvas').setAttribute('aria-label','Memorial, windbreak and candle');
    }
    const c=document.querySelector('#vigil-canvas');c.addEventListener('pointerdown',down);c.addEventListener('pointermove',move);c.addEventListener('pointerup',e=>up(e));c.addEventListener('pointercancel',e=>up(e,true));
    document.querySelector('#vigil-seal').addEventListener('click',()=>{event('seal',[500,570]);});
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.funeral_ritual_nonrealtime={rootSelector:'.funeral-vigil',render};
})();
