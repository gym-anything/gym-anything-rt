(() => {
  'use strict';
  const LEGS = ['FL','FR','RL','RR'];
  const COLORS = {FL:'#ffcc73', FR:'#7ce8d4', RL:'#bfa0ff', RR:'#ff8d9c'};
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  const copy = v => JSON.parse(JSON.stringify(v));
  const dist = (a,b) => Math.hypot(a[0]-b[0],a[1]-b[1]);
  function noise(seed,index) {
    let x = (seed ^ Math.imul(index+1,0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16),0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13),0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function motion(seed,ms,span) {
    const u=Math.max(0,ms)/span,n=Math.floor(u),f=u-n,a=noise(seed,n),b=noise(seed,n+1);
    return a+(b-a)*f*f*(3-2*f);
  }
  function tapePosition(knots,ms,span) {
    const u=Math.max(0,ms)/span,n=Math.floor(u),f=u-n,blend=f*f*(3-2*f);
    return knots[n].map((x,i)=>x+(knots[n+1][i]-x)*blend);
  }
  function padPosition(w,p,ms) {
    const v=tapePosition(p.knots,ms,w.parameters.span_ms);
    return p.base.map((x,i)=>x+p.amplitude[i]*v[i]);
  }
  function hull(points) {
    const sorted=points.map(p=>p.slice(0,2)).sort((a,b)=>a[0]-b[0] || a[1]-b[1]);
    const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
    const lower=[],upper=[];
    for(const p of sorted) {while(lower.length>=2 && cross(lower.at(-2),lower.at(-1),p)<=0) lower.pop();lower.push(p);}
    for(const p of [...sorted].reverse()) {while(upper.length>=2 && cross(upper.at(-2),upper.at(-1),p)<=0) upper.pop();upper.push(p);}
    return lower.slice(0,-1).concat(upper.slice(0,-1));
  }
  function margin(point,polygon) {
    if(polygon.length<3) return -100;
    let inside=true,distance=Infinity;
    polygon.forEach((a,i)=>{
      const b=polygon[(i+1)%polygon.length],dx=b[0]-a[0],dy=b[1]-a[1];
      inside &&= dx*(point[1]-a[1])-dy*(point[0]-a[0])>=-1e-10;
      const t=clamp(((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy),0,1);
      distance=Math.min(distance,Math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy));
    });
    return inside ? distance : -distance;
  }
  class Simulation {
    constructor(w) {
      this.world=w;this.pads=Object.fromEntries(w.pads.map(p=>[p.id,p]));
      this.ms=0;this.active=false;this.failed='';this.complete=false;
      const guided=w.parameters.guided_legs;
      this.contacts=Object.fromEntries(LEGS.map(l=>[l,`${l}-${guided && !guided.includes(l)?w.parameters.terraces:0}`]));
      this.offsets=Object.fromEntries(LEGS.map(l=>[l,[0,0]]));
      this.swing=null;this.ballast=[0,0];this.body=this.center(0);this.body[2]+=.95;this.velocity=[0,0];
      this.unstable_ms=0;this.landings=[];
    }
    feet(ms=this.ms) {
      const result={};
      for(const leg of LEGS) {
        if(this.swing?.leg===leg) {
          const s=this.swing,f=clamp((ms-s.start_ms)/this.world.swing_ms,0,1),blend=f*f*(3-2*f);
          const p=s.start.map((x,i)=>x+(s.end[i]-x)*blend);
          const z=padPosition(this.world,this.pads[s.destination],ms)[2];
          p[2]=s.start[2]+(z-s.start[2])*blend+this.world.lift_clearance*4*f*(1-f);
          result[leg]=p;
        } else {
          const p=padPosition(this.world,this.pads[this.contacts[leg]],ms);
          result[leg]=[p[0]+this.offsets[leg][0],p[1]+this.offsets[leg][1],p[2]];
        }
      }
      return result;
    }
    center(ms=this.ms) {const f=Object.values(this.feet(ms));return [0,1,2].map(i=>f.reduce((s,p)=>s+p[i],0)/4);}
    polygon() {return hull(Object.entries(this.feet()).filter(([l])=>this.swing?.leg!==l).map(([,p])=>p));}
    launch() {if(this.active) throw Error('Already started');this.active=true;}
    setBallast(target) {if(this.world.guide)throw Error('The guide carries the chassis; ballast is unavailable.');this.ballast=[...target];}
    step(leg,target) {
      if(!this.active || this.swing || this.failed || this.complete) throw Error('Foot stroke unavailable');
      const old=this.pads[this.contacts[leg]],p=this.pads[`${leg}-${old.terrace+1}`];
      if(!p) throw Error('Foot already on rim');
      const start=this.feet()[leg],end=[...target,p.base[2]];
      if(dist(start,end)>5.5) {this.failed='Foot stroke exceeded its extension range.';return;}
      this.swing={leg,start:[...start],end,start_ms:this.ms,destination:p.id};
    }
    advance(end) {
      if(!this.active) return;
      const w=this.world,p=w.parameters,dt=w.tick_ms/1000,k=p.body_response;
      while(this.ms+w.tick_ms<=end && !this.failed && !this.complete) {
        this.ms+=w.tick_ms;
        const c=this.center();
        for(let i=0;i<2;i++) {
          if(w.guide) {this.velocity[i]=(c[i]-this.body[i])/dt;this.body[i]=c[i];}
          else {
            const wind=p.wind*tapePosition(w.wind.knots,this.ms,w.wind.span_ms)[i];
            const a=k*(c[i]+this.ballast[i]-this.body[i])-2*Math.sqrt(k)*this.velocity[i]+wind;
            this.velocity[i]+=a*dt;this.body[i]+=this.velocity[i]*dt;
          }
        }
        this.body[2]=c[2]+.95;
        if(this.swing && this.ms-this.swing.start_ms>=w.swing_ms) {
          const s=this.swing,pad=this.pads[s.destination],pos=padPosition(w,pad,this.ms);
          if(dist(s.end,pos)+w.toe_radius>pad.radius+1e-8) {this.failed='A foot missed the drifting plate.';break;}
          this.contacts[s.leg]=pad.id;this.offsets[s.leg]=s.end.slice(0,2).map((v,i)=>v-pos[i]);
          this.landings.push({ms:this.ms,leg:s.leg,pad:pad.id,point:this.feet()[s.leg]});this.swing=null;
        }
        const feet=this.feet();
        if(Object.values(feet).some(f=>dist(this.body,f)>w.max_leg_reach)) {this.failed='A planted leg ran out of extension.';break;}
        if(!w.guide) {
          const balance=margin(this.body,this.polygon())+w.toe_radius;
          this.unstable_ms=balance<0 ? this.unstable_ms+w.tick_ms : 0;
          if(this.unstable_ms>=p.tip_ms) {this.failed='The body toppled outside its support polygon.';break;}
        }
        if(!this.swing && LEGS.every(l=>this.pads[this.contacts[l]].terrace===p.terraces)) this.complete=true;
        else if(this.ms>=w.max_ms) this.failed='Traverse time exhausted.';
      }
    }
    snapshot() {return {ms:this.ms,active:this.active,failed:this.failed,complete:this.complete,
      body:[...this.body],velocity:[...this.velocity],ballast:[...this.ballast],contacts:copy(this.contacts),
      offsets:copy(this.offsets),swing:copy(this.swing),unstable_ms:this.unstable_ms,landings:copy(this.landings)};}
  }
  window.CraterWalkerV3Physics={Simulation,padPosition,tapePosition,hull,margin};
  let model,raf=0,escapeHandler;
  const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function record(kind,extra={}) {model.events.push({seq:model.events.length+1,kind,t_ms:model.sim.ms,...extra});}
  function sync() {
    if(!model || model.terminal || !model.sim.active) return;
    model.sim.advance(Math.floor((performance.now()-model.startedAt)/10)*10);
    if(model.sim.complete && model.hold) {
      const pointer=model.hold.pointer;
      model.hold=null;model.aim=null;
      for(const canvas of document.querySelectorAll('.cw-map,.cw-balance'))
        if(pointer!==undefined && canvas.hasPointerCapture(pointer)) canvas.releasePointerCapture(pointer);
    }
    if(model.sim.failed && !model.submitting) submit();
  }
  function chartPoint(p) {const c=model.state.world.chart;return [c.origin[0]+p[0]*c.scale,c.origin[1]+p[1]*c.scale];}
  function knownPad(pad) {return model.surveyed.has(pad.id) || Object.values(model.sim.contacts).includes(pad.id);}
  function surveyAt(point) {
    if(model.terminal || model.sim.complete || model.hold)return;
    sync();if(model.terminal || model.sim.complete)return;
    model.lens=point;
    const revealed=model.state.world.pads.filter(p=>!knownPad(p) &&
      dist(point,padPosition(model.sim.world,p,model.sim.ms))<=model.state.survey.radius).map(p=>p.id);
    if(revealed.length) {
      revealed.forEach(id=>model.surveyed.add(id));
      record('survey',{point,revealed,input_source:'survey_pointer'});
      model.surveyNote=`SURVEYED ${revealed.join(' / ')} · LIVE FORECAST RETAINED`;
    }
    draw();
  }
  function pointerPoint(canvas,e) {const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height];}
  function worldPoint(p) {const c=model.state.world.chart;return [(p[0]-c.origin[0])/c.scale,(p[1]-c.origin[1])/c.scale];}
  function balancePoint(p) {const c=model.state.world.balance_chart,lim=model.state.world.ballast_limit;return p.map((x,i)=>clamp((x-c.origin[i])/c.scale,-lim,lim));}
  function polygon(ctx,points,fill,stroke) {
    if(!points.length) return;
    ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();
    if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.stroke();}
  }
  function circle(ctx,p,r,color,stroke) {ctx.beginPath();ctx.arc(...p,r,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.stroke();}}
  function label(ctx,text,p,color='#cfdbd8',size=11) {ctx.fillStyle=color;ctx.font=`bold ${size}px monospace`;ctx.fillText(text,...p);}
  function drawMap() {
    const canvas=document.querySelector('.cw-map'),ctx=canvas.getContext('2d'),s=model.sim,w=s.world;
    ctx.fillStyle='#0c2027';ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.lineWidth=1;ctx.strokeStyle='#b4cabd15';
    for(let x=26;x<canvas.width;x+=52) {ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,canvas.height);ctx.stroke();}
    for(let y=2;y<canvas.height;y+=52) {ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(canvas.width,y);ctx.stroke();}
    const dock=w.pads.filter(p=>p.terrace===w.parameters.terraces && knownPad(p)).map(p=>padPosition(w,p,s.ms));
    ctx.lineWidth=2;polygon(ctx,hull(dock).map(chartPoint),'#e5b86b12','#e5b86b50');
    label(ctx,'RIM DOCKS',[704,210],'#eebf67');
    const poly=s.polygon().map(chartPoint);ctx.lineWidth=2;
    if(w.guide) {
      const g=w.guide,a=chartPoint([g.x_min,g.y_min]),b=chartPoint([g.x_max,g.y_max]);
      ctx.strokeStyle='#7cabb0';ctx.lineWidth=3;ctx.strokeRect(a[0],a[1],b[0]-a[0],b[1]-a[1]);
      const carriage=chartPoint(s.body);ctx.strokeStyle='#7cabb088';ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(a[0],carriage[1]);ctx.lineTo(b[0],carriage[1]);ctx.stroke();
      label(ctx,'FIXED CHASSIS GUIDE',[a[0]+8,b[1]-9],'#9dc3c6',10);
    } else polygon(ctx,poly,'#62ddcb14','#74bdb177');
    for(const pad of w.pads) {
      if(!knownPad(pad)) {
        // Dust marks only the broad survey area, never the actual seeded
        // position or motion. The same mask applies to the perspective view.
        const p=chartPoint(pad.base),rx=(pad.amplitude[0]+pad.radius)*w.chart.scale,
          ry=(pad.amplitude[1]+pad.radius)*w.chart.scale;
        ctx.fillStyle='#6a6e6324';ctx.strokeStyle='#b8b49a60';ctx.lineWidth=1;ctx.setLineDash([3,5]);
        ctx.beginPath();ctx.ellipse(...p,rx,ry,0,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.setLineDash([]);
        ctx.textAlign='center';label(ctx,'?',[p[0],p[1]+4],'#d1c7a2',13);ctx.textAlign='left';continue;
      }
      const pos=padPosition(w,pad,s.ms),p=chartPoint(pos),r=pad.radius*w.chart.scale;
      const planted=Object.values(s.contacts).includes(pad.id) && s.swing?.destination!==pad.id;
      const preview=()=>{if(pad.amplitude[0]) {
        ctx.strokeStyle=COLORS[pad.leg]+'60';ctx.lineWidth=1;ctx.setLineDash([3,4]);ctx.beginPath();
        for(let dt=0;dt<=3000;dt+=100){const q=chartPoint(padPosition(w,pad,s.ms+dt));dt?ctx.lineTo(...q):ctx.moveTo(...q);}ctx.stroke();ctx.setLineDash([]);
        for(const dt of [1000,2000,3000]) {const q=chartPoint(padPosition(w,pad,s.ms+dt));circle(ctx,q,3,COLORS[pad.leg]+'99');label(ctx,String(dt/1000),[q[0]+4,q[1]-(w.guide?10+9*(dt/1000-1):4)],COLORS[pad.leg]+'bb',8);}
      }};
      if(!w.guide)preview();
      ctx.lineWidth=2;circle(ctx,p,r,planted?'#415151':'#172d33',COLORS[pad.leg]);
      ctx.textAlign='center';label(ctx,`${pad.leg}·${pad.terrace}`,[p[0],p[1]+(w.guide?15:4)],COLORS[pad.leg],10);ctx.textAlign='left';
      if(w.guide)preview();
    }
    const feet=s.feet(),body=chartPoint(s.body);
    for(const leg of LEGS) {
      const p=chartPoint(feet[leg]);ctx.strokeStyle=COLORS[leg];ctx.lineWidth=4;
      ctx.beginPath();ctx.moveTo(...body);ctx.lineTo(...p);ctx.stroke();
      circle(ctx,p,12,'#091b20',COLORS[leg]);circle(ctx,p,w.toe_radius*w.chart.scale,COLORS[leg]);
    }
    const trail=chartPoint([s.body[0]-s.velocity[0]*.8,s.body[1]-s.velocity[1]*.8]);
    ctx.strokeStyle='#ffe6a2';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(...trail);ctx.lineTo(...body);ctx.stroke();
    circle(ctx,body,13,'#dfaa58','#fff0b9');circle(ctx,body,4,'#1c2b30');
    if(model.hold?.kind==='foot') {
      const leg=model.hold.leg,other=hull(Object.entries(feet).filter(([l])=>l!==leg).map(([,p])=>p)).map(chartPoint);
      if(!w.guide) {ctx.setLineDash([5,4]);polygon(ctx,other,'#ffd98d09','#ffd98dbb');ctx.setLineDash([]);}
      if(model.aim) {const p=chartPoint(model.aim);ctx.strokeStyle=COLORS[leg];ctx.beginPath();ctx.moveTo(p[0]-9,p[1]);ctx.lineTo(p[0]+9,p[1]);ctx.moveTo(p[0],p[1]-9);ctx.lineTo(p[0],p[1]+9);ctx.stroke();}
    }
    if(model.lens && !model.hold) {
      ctx.strokeStyle='#e6d6a077';ctx.lineWidth=1;ctx.beginPath();
      ctx.arc(...chartPoint(model.lens),model.state.survey.radius*w.chart.scale,0,Math.PI*2);ctx.stroke();
    }
    label(ctx,'OVERHEAD / HOVER OVER ? DUST TO SURVEY · SOLID RINGS = CHARTED PLATES',[16,20]);
    label(ctx,'DASHED TRAILS: NEXT 1 / 2 / 3 SECONDS · FOOT STROKE: 1 SECOND',[16,canvas.height-13],'#8eb1b4',10);
  }
  function drawScene() {
    const canvas=document.querySelector('.cw-scene'),ctx=canvas.getContext('2d'),s=model.sim,w=s.world;
    const bg=ctx.createLinearGradient(0,0,0,canvas.height);bg.addColorStop(0,'#142e3a');bg.addColorStop(1,'#2f263a');ctx.fillStyle=bg;ctx.fillRect(0,0,canvas.width,canvas.height);
    const proj=p=>[170+p[0]*50-p[1]*12,125+p[1]*9-p[2]*28];
    for(let i=0;i<30;i++) {const x=(i*137)%860,y=100+(i*29)%65;polygon(ctx,[[x,y],[x+55,y+25],[x-32,y+20]],i%2?'#46505b':'#303c4b','#77857a22');}
    for(const pad of [...w.pads].sort((a,b)=>padPosition(w,a,s.ms)[1]-padPosition(w,b,s.ms)[1])) {
      if(!knownPad(pad)) {
        const q=proj(pad.base);ctx.fillStyle='#97a79828';ctx.beginPath();
        ctx.ellipse(q[0],q[1],(pad.amplitude[0]+pad.radius)*50,12+pad.radius*14,0,0,Math.PI*2);ctx.fill();continue;
      }
      const p=padPosition(w,pad,s.ms),q=proj(p),r=pad.radius;
      ctx.fillStyle='#1b242c';ctx.beginPath();ctx.ellipse(q[0],q[1]+8,r*50,r*14,0,0,Math.PI*2);ctx.fill();
      ctx.fillStyle='#627275';ctx.strokeStyle=COLORS[pad.leg];ctx.lineWidth=2;ctx.beginPath();ctx.ellipse(q[0],q[1],r*50,r*14,0,0,Math.PI*2);ctx.fill();ctx.stroke();
    }
    const b=[...s.body];
    if(w.guide) {
      const g=w.guide,z=3,left=proj([g.x_min,0,z]),right=proj([g.x_max,0,z]),carriage=proj([b[0],b[1],z]),chassis=proj(b);
      ctx.strokeStyle='#80a7ae';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(...left);ctx.lineTo(...right);ctx.stroke();
      ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(...carriage);ctx.lineTo(...chassis);ctx.stroke();
      circle(ctx,carriage,7,'#96c8c9','#d2f1ed');
    }
    for(const leg of LEGS) {
      const f=s.feet()[leg],hip=[b[0]+(leg[0]==='F'?.32:-.32),b[1]+(leg[1]==='L'?-.3:.3),b[2]],knee=[(hip[0]+f[0])/2,(hip[1]+f[1])/2,Math.max(hip[2]-.25,f[2]+.6)];
      const pts=[hip,knee,f].map(proj);ctx.strokeStyle='#0d1820';ctx.lineWidth=9;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(...pts[0]);ctx.lineTo(...pts[1]);ctx.lineTo(...pts[2]);ctx.stroke();ctx.strokeStyle=COLORS[leg];ctx.lineWidth=5;ctx.stroke();circle(ctx,pts[1],4,'#d0a46c');
    }
    const p=proj(b);polygon(ctx,[[p[0]-26,p[1]-7],[p[0]+16,p[1]-14],[p[0]+28,p[1]+5],[p[0]-15,p[1]+12]],'#d2a35c','#ffe4a1');
    circle(ctx,[p[0]+10,p[1]-5],4,'#92e9d5');label(ctx,'CRATER WALKER / TELESCOPIC CONTACT RIG',[17,24],'#e3c994',12);
    label(ctx,w.guide?'The fixed guide carries the chassis; you place the undocked toes.':'Raised plates carry the feet; the body keeps its momentum.',[17,canvas.height-14],'#a5bdba',10);
  }
  function drawBalance() {
    const cv=document.querySelector('.cw-balance'),ctx=cv.getContext('2d'),s=model.sim,c=s.world.balance_chart,center=s.center();
    const project=p=>[c.origin[0]+p[0]*c.scale,c.origin[1]+p[1]*c.scale];
    ctx.fillStyle='#0c2027';ctx.fillRect(0,0,cv.width,cv.height);
    if(s.world.guide) {
      ctx.strokeStyle='#80a7ae';ctx.lineWidth=4;ctx.beginPath();ctx.moveTo(24,65);ctx.lineTo(256,65);ctx.moveTo(140,65);ctx.lineTo(140,132);ctx.stroke();
      circle(ctx,[140,65],10,'#96c8c9');circle(ctx,[140,132],17,'#dfaa58','#fff0b9');
      label(ctx,'GUIDE SUPPORT',[12,19],'#a3d1d3',12);
      label(ctx,'CHASSIS CARRIED',[65,175],'#a3d1d3',12);
      label(ctx,'NO WEIGHT CONTROL',[56,cv.height-18],'#9cb7b6',10);return;
    }
    polygon(ctx,s.polygon().map(p=>project([p[0]-center[0],p[1]-center[1]])),'#8de8d512','#8bd3c8');
    const lim=s.world.ballast_limit*c.scale;ctx.strokeStyle='#e4c07388';ctx.setLineDash([4,5]);ctx.strokeRect(c.origin[0]-lim,c.origin[1]-lim,2*lim,2*lim);ctx.setLineDash([]);
    const bead=project(s.ballast),com=project([s.body[0]-center[0],s.body[1]-center[1]]);
    circle(ctx,bead,12,'#ecc47b','#fff3ca');circle(ctx,com,5,'#75e6d6');
    ctx.strokeStyle='#75e6d6';ctx.beginPath();ctx.moveTo(...com);ctx.lineTo(com[0]+s.velocity[0]*c.scale*.8,com[1]+s.velocity[1]*c.scale*.8);ctx.stroke();
    label(ctx,'WEIGHT SHIFT',[12,19],'#e4c073',12);label(ctx,'GOLD HANDLE / CYAN BODY',[12,cv.height-12],'#9cb7b6',9);
  }
  function draw() {
    if(!model)return;drawMap();drawScene();drawBalance();
    const s=model.sim,root=document.querySelector('.cw-root');
    root.dataset.phase=s.failed?'failed':s.complete?'escaped':s.active?'active':'ready';
    document.querySelector('.cw-feet-status').textContent=LEGS.map(l=>`${l} ${s.pads[s.contacts[l]].terrace}/${s.world.parameters.terraces}`).join(' · ');
    document.querySelector('.cw-survey').textContent=model.surveyNote;
    document.querySelector('.cw-tip i').style.width=`${s.unstable_ms/(s.world.parameters.tip_ms || 1)*100}%`;
    document.querySelector('.cw-status').textContent=s.failed ? `FAIL · ${s.failed}` : s.complete ? 'ALL FOUR FEET ON THE RIM · CERTIFY ESCAPE' : s.swing ? `${s.swing.leg} IN FLIGHT · KEEP THE BODY INSIDE THE TRIANGLE` : s.active ? 'SHIFT WEIGHT · AIM FOR WHERE THE NEXT PLATE WILL BE' : 'INSPECT THE CRATER · WAKE THE SUPPORT PLATES';
    if(s.world.guide && !s.failed && !s.complete) document.querySelector('.cw-status').textContent=s.swing?`${s.swing.leg} IN FLIGHT · GUIDE CARRIES THE CHASSIS`:s.active?'AIM FOR THE MOVING PLATE · GUIDE SUPPORT ACTIVE':'INSPECT THE MOVING-PLATE PATH · CHASSIS GUIDE ATTACHED';
    document.querySelector('.cw-launch').disabled=s.active || model.terminal;
    document.querySelector('.cw-cancel').disabled=!model.hold || model.terminal;
  }
  function payload() {const s=model.sim;return {mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,
    challenge_id:model.state.challenge_id,interaction_mode:model.mode,events:model.events,completed:s.complete&&!s.failed,
    final_ms:s.ms,contacts:copy(s.contacts),landings:s.landings.map(({ms,leg,pad})=>({ms,leg,pad}))};}
  async function submit() {
    if(model.terminal || model.submitting)return;
    // Synchronise once; avoid recursion when this was called by a physics failure.
    model.submitting=true;sync();model.terminal=true;
    const request=payload();model.lastPayload=request;
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(request)}),result=await response.json();
      model.outcome=result;
      const v=document.querySelector('.cw-verdict');v.hidden=false;v.dataset.passed=result.passed?'true':'false';
      v.innerHTML=`<b>${result.passed?'PASS':'FAIL'}</b><span>${result.passed?'FOUR FEET ESCAPED':esc(model.sim.failed || 'TRAVERSE INCOMPLETE')}</span>`;
      model.helpers.setReadout(result.passed?'PASS · ESCAPE VERIFIED':'FAIL · EPISODE ENDED',result.passed?'passed':'error');
    } catch(e) {model.helpers.setReadout(`VERIFIER ERROR · ${e.message}`,'error');}
    draw();
  }
  async function render(state,helpers) {
    cancelAnimationFrame(raf);document.body.dataset.mechanic='crater_walker_v3';
    model={state,helpers,sim:new Simulation(state.world),mode:state.control_condition?.interaction || 'full',
      events:[],hold:null,aim:null,lens:null,surveyed:new Set(state.survey.initially_known),
      surveyNote:'HOVER OVER ? DUST TO SURVEY · SAFE BEFORE WAKE',
      terminal:false,submitting:false,startedAt:0};window.craterWalkerV3Model=model;
    const full=model.mode==='full';
    helpers.app.innerHTML=`<section class="cw-root"><header class="cw-head"><div><small>FIELD UNIT 04 / SHIFTING CRATER</small><h1>Crater Walker V3</h1></div><p>Four feet. Three supports during a step.<br><b>Escape without losing your footing.</b></p><span class="cw-badge">CW<br>V3</span></header>
      <main class="cw-main"><section class="cw-world"><canvas class="cw-scene" width="860" height="180"></canvas><canvas class="cw-map" width="860" height="500" aria-label="Overhead foot placement chart"></canvas></section><aside class="cw-console"><h2>Keep your balance.</h2><p>${full?'Drag the gold weight handle. Drag a colored toe to a landing coordinate.':'Click the weight chart to shift. Click a colored toe, then a landing coordinate.'} The toe takes one second to arrive. Its height follows the next terrace; you control its horizontal landing.</p><p class="cw-survey" aria-live="polite"></p><canvas class="cw-balance" width="280" height="240" aria-label="Ballast weight shift"></canvas><div class="cw-tip"><i></i><span>TOPPLE</span></div><p class="cw-feet-status"></p><button class="cw-launch">WAKE THE CRATER</button><button class="cw-cancel">CANCEL AIM · ESC</button><button class="cw-submit">CERTIFY ESCAPE</button><small>Hover over ? dust to survey plates and live forecasts. Findings stay visible. Survey safely before WAKE; afterward time keeps running. Fit the whole toe inside its next ring. Escape cancels aim. A miss or full TOPPLE bar ends the episode.</small></aside></main><footer class="cw-foot"><strong class="cw-status"></strong><span class="readout">READY</span></footer><div class="cw-verdict" hidden></div></section>`;
    const map=document.querySelector('.cw-map'),balance=document.querySelector('.cw-balance');
    if(state.world.guide) {
      document.querySelector('.cw-head p').innerHTML='Fixed guide support.<br><b>Place the undocked toes on the rim.</b>';
      document.querySelector('.cw-console h2').textContent='Aim the moving toe.';
      document.querySelector('.cw-console p').textContent=`The guide carries the chassis; the other feet are already docked. ${full?'Drag':'Click, then place'} ${state.world.parameters.guided_legs.join(' and ')} on each next plate. The stroke takes one second. Use the numbered forecast to choose its future horizontal position.`;
      document.querySelector('.cw-console small').textContent='Hover over ? dust to survey plates and live forecasts. Findings stay visible. Survey safely before WAKE; afterward plates keep moving. Fit the whole toe inside its next ring. Escape cancels aim. A miss ends the episode.';
      document.querySelector('.cw-tip').hidden=true;
      balance.setAttribute('aria-label','Fixed chassis guide support; no ballast control');
    }
    document.querySelector('.cw-launch').onclick=()=>{if(model.sim.active || model.terminal)return;model.sim.launch();model.startedAt=performance.now();record('launch',{input_source:'launch_button'});draw();};
    document.querySelector('.cw-submit').onclick=submit;
    function cancelAim(source) {
      if(!model.hold || model.terminal || model.sim.complete)return;
      sync();if(model.terminal || model.sim.complete)return;
      const pointer=model.hold.pointer;
      record('cancel',{input_source:source});model.hold=null;model.aim=null;
      for(const canvas of [map,balance]) if(pointer!==undefined && canvas.hasPointerCapture(pointer)) canvas.releasePointerCapture(pointer);
      draw();
    }
    document.querySelector('.cw-cancel').onclick=()=>cancelAim('cancel_button');
    if(escapeHandler)document.removeEventListener('keydown',escapeHandler);
    escapeHandler=e=>{if(e.key==='Escape' && model.hold){e.preventDefault();cancelAim('cancel_key');}};
    document.addEventListener('keydown',escapeHandler);
    function startFoot(e) {
      if(model.terminal || model.sim.complete || model.sim.swing || !model.sim.active)return;sync();if(model.terminal || model.sim.complete)return;
      const p=worldPoint(pointerPoint(map,e)),source=full?'foot_drag':'foot_click';
      if(!full && model.hold?.kind==='foot') {const leg=model.hold.leg;record('step',{leg,target:p,input_source:source});model.sim.step(leg,p);model.hold=null;model.aim=null;draw();return;}
      if(model.hold)return;
      const feet=model.sim.feet(),leg=LEGS.find(l=>dist(p,feet[l])<=.23 && model.sim.pads[model.sim.contacts[l]].terrace<state.world.parameters.terraces);
      if(!leg)return;model.hold={kind:'foot',leg,pointer:e.pointerId};model.aim=p;
      record('aim_start',{leg,point:p,input_source:source});if(full)map.setPointerCapture(e.pointerId);e.preventDefault();draw();
    }
    map.addEventListener('pointerdown',startFoot);
    map.addEventListener('pointermove',e=>{if(!e.buttons)surveyAt(worldPoint(pointerPoint(map,e)));});
    map.addEventListener('pointerleave',()=>{model.lens=null;draw();});
    map.addEventListener('pointermove',e=>{if(full && model.hold?.kind==='foot' && !model.terminal && !model.sim.complete){sync();if(model.terminal || model.sim.complete)return;model.aim=worldPoint(pointerPoint(map,e));draw();}});
    map.addEventListener('pointerup',e=>{if(!full || model.hold?.kind!=='foot' || model.terminal || model.sim.complete)return;sync();if(model.terminal || model.sim.complete)return;const p=worldPoint(pointerPoint(map,e)),leg=model.hold.leg;record('step',{leg,target:p,input_source:'foot_drag'});model.hold=null;model.aim=null;model.sim.step(leg,p);map.releasePointerCapture(e.pointerId);draw();});
    const cancelPointer=e=>{if(model.hold && !model.terminal && !model.sim.complete){sync();if(model.terminal || model.sim.complete)return;record('cancel',{input_source:'cancel_button'});model.hold=null;model.aim=null;draw();}};
    map.addEventListener('pointercancel',cancelPointer);
    balance.addEventListener('pointerdown',e=>{
      if(state.world.guide)return;
      if(model.hold || model.terminal || model.sim.complete)return;sync();if(model.terminal || model.sim.complete)return;
      const local=pointerPoint(balance,e),c=state.world.balance_chart;
      const raw=local.map((x,i)=>(x-c.origin[i])/c.scale),p=balancePoint(local);
      if(full) {if(dist(raw,model.sim.ballast)>.40)return;model.hold={kind:'ballast',pointer:e.pointerId};balance.setPointerCapture(e.pointerId);record('ballast_start',{point:raw,input_source:'ballast_drag'});}
      else {model.sim.setBallast(p);record('ballast',{target:p,input_source:'ballast_click'});}
      e.preventDefault();draw();
    });
    balance.addEventListener('pointermove',e=>{if(!full || model.hold?.kind!=='ballast' || model.terminal || model.sim.complete)return;sync();if(model.terminal || model.sim.complete)return;const p=balancePoint(pointerPoint(balance,e));model.sim.setBallast(p);record('ballast',{target:p,input_source:'ballast_drag'});draw();});
    balance.addEventListener('pointerup',e=>{if(!full || model.hold?.kind!=='ballast' || model.terminal || model.sim.complete)return;sync();if(model.terminal || model.sim.complete)return;const p=balancePoint(pointerPoint(balance,e));model.sim.setBallast(p);record('ballast',{target:p,input_source:'ballast_drag'});record('release',{input_source:'ballast_drag'});model.hold=null;balance.releasePointerCapture(e.pointerId);draw();});
    balance.addEventListener('pointercancel',cancelPointer);
    if(state.episode_failed) {
      model.terminal=true;model.sim.failed=state.episode_feedback || 'This episode has ended.';
      const v=document.querySelector('.cw-verdict');v.hidden=false;v.dataset.passed='false';
      v.innerHTML='<b>FAIL</b><span>EPISODE ENDED</span>';
      helpers.setReadout('FAIL · EPISODE ENDED','error');
    }
    const animate=()=>{sync();draw();raf=requestAnimationFrame(animate);};draw();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.crater_walker_v3={rootSelector:'.cw-root',render};
})();
