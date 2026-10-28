(() => {
  'use strict';
  const TOKENS = ['F','J','D','L','R','G','A','B'];
  const LABELS = {F:'LEVEL',J:'UP',D:'DOWN',L:'LEFT',R:'RIGHT',G:'LIGHT',A:'AMBER',B:'BLUE'};
  const GLYPHS = {F:'→',J:'↗',D:'↘',L:'↶',R:'↷',G:'☀',A:'A',B:'B'};
  const DIRS = [[1,0],[0,1],[-1,0],[0,-1]];
  let model, frame;
  const copy = v => JSON.parse(JSON.stringify(v));
  const esc = v => String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function noise(seed,index) {
    let x=(seed ^ Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  const pairCache=new Map(),inverseCache=new Map();
  const mod=(n,p)=>((n%p)+p)%p;
  function inverse(b,p) {
    const key=`${b}/${p}`;
    if(!inverseCache.has(key)) {
      for(let i=1;i<p;i++)if((i*b)%p===1){inverseCache.set(key,i);break;}
    }
    return inverseCache.get(key);
  }
  function multiply(a,b,p) {
    return [mod(a[0]*b[0]+a[1]*b[2],p),mod(a[0]*b[1]+a[1]*b[3],p),
            mod(a[2]*b[0]+a[3]*b[2],p),mod(a[2]*b[1]+a[3]*b[3],p)];
  }
  function liftPairAt(pair,index,p,a,b) {
    const key=[...pair,index,p,a,b].join('/');
    if(pairCache.has(key))return pairCache.get(key);
    let n=Math.abs(index),m=index<0?[mod(-a*inverse(b,p),p),inverse(b,p),1,0]:[0,1,b,a],r=[1,0,0,1];
    while(n){if(n%2)r=multiply(r,m,p);m=multiply(m,m,p);n=Math.floor(n/2);}
    const result=[mod(r[0]*pair[0]+r[1]*pair[1],p),mod(r[2]*pair[0]+r[3]*pair[1],p)];
    if(pairCache.size>65536)pairCache.clear();pairCache.set(key,result);return result;
  }
  function liftGoal(p,roof,pair) {
    const [h,to]=pair,previous=mod((to-p.lift_coefficient*h)*inverse(p.lift_previous_coefficient,p.lift_modulus),p.lift_modulus);
    const count=Math.round(2*p.sway/p.motion_quantum)+1,q=p.motion_quantum;
    return [roof.cell[0]-p.sway+q*mod(h+2*previous,count),
            roof.cell[1]-p.sway+q*mod(3*h+previous,count),roof.base_z-p.lift+q*h].map(v=>Math.round(v*100)/100);
  }
  function roofPose(world,roof,ms) {
    const p=world.physics, u=(ms+roof.phase_ms)/p.span_ms, n=Math.floor(u), f=u-n;
    const blend=f**3*(10-15*f+6*f*f), derivative=30*f*f*(1-f)**2/(p.span_ms/1000);
    const amplitudes=[p.sway,p.sway,p.lift], base=[...roof.cell,roof.base_z];
    const position=[],velocity=[],start=[],goal=[],next_goal=[];
    const controllerEnds=p.motion_revision==='visible-lift-v1'?[n,n+1,n+2].map(k=>liftGoal(p,roof,liftPairAt(roof.lift_pair,k,p.lift_modulus,p.lift_coefficient,p.lift_previous_coefficient))):null;
    for(let i=0;i<3;i++) {
      const seed=(roof.motion_seed+i*7919)>>>0;
      const ends=controllerEnds?controllerEnds.map(v=>v[i]):[n,n+1,n+2].map(k=>base[i]+amplitudes[i]*noise(seed,k));
      const [a,b,c]=p.motion_quantum?ends.map(v=>Math.floor(v/p.motion_quantum+.5)*p.motion_quantum):ends;
      position.push(a+(b-a)*blend);
      velocity.push((b-a)*derivative);
      start.push(a);goal.push(b); next_goal.push(c);
    }
    return {position,velocity,start,goal,next_goal,phase:f,remaining_ms:(1-f)*p.span_ms};
  }
  function sweptDeckContact(previous,point,a,b,half,radius,thickness) {
    let enter=0,leave=1;
    const bounds=[[-half-radius,half+radius],[-half-radius,half+radius],[-thickness,-1e-8]];
    for(let i=0;i<3;i++) {
      const [low,high]=bounds[i],from=previous[i]-a[i],to=point[i]-b[i],v=to-from;
      if(Math.abs(v)<1e-12) {if(!(low<from && from<high))return false;}
      else {
        const t0=(low-from)/v,t1=(high-from)/v;
        enter=Math.max(enter,Math.min(t0,t1));leave=Math.min(leave,Math.max(t0,t1));
        if(enter>=leave-1e-12)return false;
      }
    }
    return true;
  }
  class Physics {
    constructor(world) {
      this.world=copy(world); this.roofs=Object.fromEntries(world.roofs.map(r=>[r.id,r]));
      this.ms=0; this.roof=world.start_roof; this.heading=world.start_heading;
      this.offset=[0,0]; this.position=roofPose(world,this.roofs[this.roof],0).position;
      this.flight=null; this.busy_until=0; this.pending_light=null; this.queue=[];
      this.lit=new Set(); this.failed=''; this.steps=[]; this.centering=null;
    }
    command(token) {
      if(this.failed || this.flight || this.ms<this.busy_until) throw new Error('robot is busy');
      const p=this.world.physics;
      if(token==='L' || token==='R') {
        this.heading=(this.heading+(token==='L'?3:1))%4; this.busy_until=this.ms+p.command_ms;
      } else if(token==='G') {
        if(!this.roofs[this.roof].lamp) {this.failed='The LIGHT instruction struck an unmarked roof.'; return;}
        this.pending_light=this.roof; this.busy_until=this.ms+p.lamp_ms;
      } else if(['F','J','D'].includes(token)) {
        const pose=roofPose(this.world,this.roofs[this.roof],this.ms);
        const start=pose.position.map((v,i)=>v+(i<2?this.offset[i]:0)), tau=p.nominal_flight_s;
        const dz={F:0,J:p.height_step,D:-p.height_step}[token];
        const velocity=DIRS[this.heading].map((v,i)=>v/tau+p.momentum*pose.velocity[i]);
        velocity.push(dz/tau+.5*p.gravity*tau+p.momentum*pose.velocity[2]);
        this.flight={start_ms:this.ms,start,velocity,source:this.roof}; this.position=start; this.roof=null;
      } else throw new Error('invalid primitive');
      this.steps.push({t_ms:this.ms,token});
    }
    dispatch(commands) {
      if(this.flight || this.ms<this.busy_until || this.queue.length || this.failed) throw new Error('robot is busy or terminal');
      this.queue=[...commands]; if(!this.queue.length) throw new Error('empty routine');
      this.command(this.queue.shift());
      this.advanceAction();
    }
    advanceAction() {
      for(let i=0;i<300000;i++) {
        if(this.failed || (!this.flight && !this.queue.length && !this.pending_light && !this.centering && this.ms>=this.busy_until)) return;
        const before=this.ms;
        this.advance(before+this.world.physics.tick_ms);
        if(this.ms<=before) throw new Error('action transition did not advance');
      }
      throw new Error('action transition exceeded its fixed-step budget');
    }
    advance(target) {
      const p=this.world.physics;
      while(this.ms+p.tick_ms<=target && !this.failed) {
        const before=this.ms; this.ms+=p.tick_ms;
        if(this.flight) {
          const f=this.flight, s=(this.ms-f.start_ms)/1000, previous=[...this.position];
          const point=f.start.map((v,i)=>v+f.velocity[i]*s); point[2]-=.5*p.gravity*s*s; this.position=point;
          const contacts=[];
          for(const r of Object.values(this.roofs)) {
            const a=roofPose(this.world,r,before).position, b=roofPose(this.world,r,this.ms).position;
            const above=previous[2]-a[2], below=point[2]-b[2];
            if(above>1e-9 && below<=0) {
              const fraction=above/(above-below), hit=previous.map((v,i)=>v+fraction*(point[i]-v));
              const center=a.map((v,i)=>v+fraction*(b[i]-v));
              const dx=Math.abs(hit[0]-center[0]),dy=Math.abs(hit[1]-center[1]);
              if(dx<=r.half+p.robot_radius && dy<=r.half+p.robot_radius)
                contacts.push({fraction,id:r.id,hit,center,contained:dx+p.robot_radius<=r.half+1e-8 && dy+p.robot_radius<=r.half+1e-8});
            }
            const solid=p.collision_revision==='swept-deck-v1'?
              sweptDeckContact(previous,point,a,b,r.half,p.robot_radius,p.roof_thickness):
              b[2]-p.roof_thickness<point[2] && point[2]<b[2]-1e-8 && Math.abs(point[0]-b[0])<r.half+p.robot_radius && Math.abs(point[1]-b[1])<r.half+p.robot_radius;
            if(solid && !contacts.some(c=>c.id===r.id)) this.failed='The robot struck a moving roof edge.';
          }
          if(contacts.length && !this.failed) {
            const c=contacts.sort((a,b)=>a.fraction-b.fraction || a.id.localeCompare(b.id))[0];
            if(!c.contained) this.failed='The robot clipped the visible roof edge.';
            else {
              this.roof=c.id; this.offset=c.hit.slice(0,2).map((v,i)=>v-c.center[i]); this.flight=null;
              this.busy_until=this.ms+300; this.centering={start_ms:this.ms,offset:[...this.offset]};
              this.steps.push({t_ms:this.ms,landed:c.id});
            }
          } else if(this.ms-f.start_ms>=p.maximum_flight_ms) this.failed='The robot fell between the roofs.';
        } else {
          if(this.centering) {
            const f=Math.max(0,1-(this.ms-this.centering.start_ms)/300);
            this.offset=this.centering.offset.map(v=>v*f); if(f===0) this.centering=null;
          }
          this.position=roofPose(this.world,this.roofs[this.roof],this.ms).position.map((v,i)=>v+(i<2?this.offset[i]:0));
        }
        if(!this.flight && this.ms>=this.busy_until && !this.failed) {
          if(this.pending_light) {this.lit.add(this.pending_light);this.pending_light=null;}
          if(this.queue.length) this.command(this.queue.shift());
        }
      }
    }
    snapshot() {return {t_ms:this.ms,roof:this.roof,heading:this.heading,offset:[...this.offset],position:[...this.position],flight:copy(this.flight),busy_until:this.busy_until,queue:[...this.queue],lit:[...this.lit].sort(),failed:this.failed,steps:copy(this.steps)};}
  }
  // Read-only diagnostics for oracle planning and cross-language testing. These
  // are not model actions and no success setter or hidden route is exposed.
  window.LampwrightNonRealtimePhysics=Physics; window.LampwrightNonRealtimeRoofPose=roofPose;
  function record(kind,extra={}) {model.events.push({sequence:model.events.length+1,kind,t_ms:model.physics.ms,...extra});}
  function sync() {
    // This action-settled counterpart has no autonomous idle clock. A deliberate dispatch
    // calls advanceAction(), and then the settled state remains unchanged.
    if(!model || !model.started || model.terminal) return;
  }
  function projection(p) {const a=model.projection;return [a.ox+(p[0]-p[1])*a.scale,a.oy+(p[0]+p[1])*a.scale*.50-(p[2]-3)*a.scale*.85];}
  function polygon(c,points,fill,stroke='#527789') {
    c.beginPath(); points.forEach((p,i)=>i?c.lineTo(...p):c.moveTo(...p));c.closePath();c.fillStyle=fill;c.fill();c.strokeStyle=stroke;c.lineWidth=1.5;c.stroke();
  }
  function draw() {
    const canvas=document.querySelector('#lv-world');if(!canvas || !model) return;
    const c=canvas.getContext('2d'),w=model.state.world,ph=model.physics,t=ph.ms;
    const sky=c.createLinearGradient(0,0,0,540);sky.addColorStop(0,'#111e35');sky.addColorStop(.65,'#233e51');sky.addColorStop(1,'#172636');c.fillStyle=sky;c.fillRect(0,0,820,540);
    // Fixed stars, skyline, and wires are original canvas geometry.
    for(let i=0;i<45;i++){c.fillStyle=i%3?'#abc0ce50':'#eecb9a80';c.fillRect((i*193+31)%820,(i*71+17)%160,2,2);}
    c.fillStyle='#0f1c2b';for(let i=0;i<20;i++)c.fillRect(i*44,430-(i*37)%110,38,140);
    const roofs=w.roofs.map(r=>({r,p:roofPose(w,r,t).position})).sort((a,b)=>(a.p[0]+a.p[1])-(b.p[0]+b.p[1]));
    c.strokeStyle='#7395ac40';c.lineWidth=1;
    for(const {r,p} of roofs) {
      const railA=projection([...r.cell,r.base_z-w.physics.lift-.2]),railB=projection([...r.cell,r.base_z+w.physics.lift+.2]);
      c.beginPath();c.moveTo(...railA);c.lineTo(...railB);c.stroke();
      for(let j=0;j<4;j++){const dot=projection([...r.cell,2+j]);c.fillStyle='#9bb1bc60';c.fillRect(dot[0]-2,dot[1]-1,4,2);}
      for(let k=6;k>=1;k--) {
        const past=projection(roofPose(w,r,Math.max(0,t-k*100)).position);
        c.fillStyle=`rgba(110,194,202,${.18*(1-k/8)})`;c.beginPath();c.arc(...past,3,0,Math.PI*2);c.fill();
      }
      const h=r.half;
      const top=[[-h,-h],[h,-h],[h,h],[-h,h]].map(([x,y])=>projection([p[0]+x,p[1]+y,p[2]]));
      const bottom=top.map(v=>[v[0],v[1]+w.physics.roof_thickness*model.projection.scale*.85]);
      polygon(c,[top[1],top[2],bottom[2],bottom[1]],'#19333e');polygon(c,[top[2],top[3],bottom[3],bottom[2]],'#213f48');
      polygon(c,top,ph.lit.has(r.id)?'#907039':r.lamp?'#244f76':'#3a5b64',ph.roof===r.id?'#ffe5a0':'#789ba5');
      const center=projection(p);
      c.fillStyle='#b5c8cf';c.font='11px ui-monospace';c.textAlign='center';c.fillText(String(Number(r.id.split('-')[1])+1).padStart(2,'0'),center[0],center[1]+4);
      if(r.lamp) {
        const light=projection([p[0]-.18,p[1]-.18,p[2]+.16]);
        c.strokeStyle='#ddc68d';c.lineWidth=2;c.beginPath();c.moveTo(light[0],light[1]+12);c.lineTo(...light);c.stroke();
        c.fillStyle=ph.lit.has(r.id)?'#ffe899':'#78c4fa';c.shadowColor=c.fillStyle;c.shadowBlur=ph.lit.has(r.id)?18:6;
        c.beginPath();c.arc(...light,6,0,Math.PI*2);c.fill();c.shadowBlur=0;
      }
      const pose=roofPose(w,r,t),v=pose.velocity;
      const vEnd=projection(p.map((n,i)=>n+(model.started?v[i]*.7:0)));c.strokeStyle='#97d6dd';c.lineWidth=2;c.beginPath();c.moveTo(...center);c.lineTo(...vEnd);c.stroke();
    }
    const rp=projection(ph.position),radius=w.physics.robot_radius*model.projection.scale;
    // The visible footplate has the exact XY half-extent used by collision.
    const foot=w.physics.robot_radius;
    const footprint=[[-foot,-foot],[foot,-foot],[foot,foot],[-foot,foot]].map(([x,y])=>projection([ph.position[0]+x,ph.position[1]+y,ph.position[2]]));
    polygon(c,footprint,'#172129','#f5c574');
    c.fillStyle='#f5c574';c.strokeStyle='#fff0bc';c.lineWidth=1.8;c.beginPath();c.roundRect(rp[0]-radius,rp[1]-21,radius*2,21,5);c.fill();c.stroke();
    c.fillStyle='#1b2834';c.fillRect(rp[0]-radius+2,rp[1]-17,radius*2-4,5);
    const d=DIRS[ph.heading],heading=projection([ph.position[0]+d[0]*.48,ph.position[1]+d[1]*.48,ph.position[2]]);
    c.strokeStyle='#ffe0a2';c.lineWidth=3;c.beginPath();c.moveTo(rp[0],rp[1]+2);c.lineTo(...heading);c.stroke();
    c.fillStyle='#dfdfd0';c.font='12px ui-monospace';c.textAlign='left';c.fillText('BLUE LANTERNS → GOLD · TRAILS: LAST 0.6 s',20,515);
    const source=ph.roof?ph.roofs[ph.roof]:ph.roofs[ph.flight?.source],headingD=DIRS[ph.heading];
    const ahead=source && w.roofs.find(r=>r.cell[0]===source.cell[0]+headingD[0] && r.cell[1]===source.cell[1]+headingD[1]);
    document.querySelector('#lv-count').textContent=`${ph.lit.size} / ${w.roofs.filter(r=>r.lamp).length}`;
    document.querySelector('#lv-live').textContent=ph.failed?'SHIFT LOST':!model.started?'PREPARE ROUTINES':ph.flight?'IN FLIGHT':ph.ms<ph.busy_until||ph.queue.length?'EXECUTING ROUTINE':'AWAITING DISPATCH';
    document.querySelector('#lv-ahead').textContent=ahead?`ROOF ${Number(ahead.id.split('-')[1])+1}`:'OPEN SKY';
    drawGauge(source,ahead);
    drawBoard();
  }
  function drawBoard() {
    const ph=model.physics,w=model.state.world,p=w.physics;
    const receipt=model.lastDispatch;
    document.querySelector('#lv-last-command').textContent=receipt?
      `LAST DISPATCH [${receipt.commands.map(t=>LABELS[t]).join(' ')}] · TIME ${(receipt.t_ms/1000).toFixed(3)} s · FROM ROOF ${String(Number(receipt.source.split('-')[1])+1).padStart(2,'0')} · HEADING ${['+X','+Y','-X','-Y'][receipt.heading]}`:
      'LAST DISPATCH: NONE';
    const status=!model.started?'PREPARING':ph.failed?'LOST':ph.flight?'FLYING':ph.ms<ph.busy_until||ph.queue.length?'BUSY':'READY';
    document.querySelector('#lv-robot').textContent=`TIME ${(ph.ms/1000).toFixed(3)} s   ROOF ${ph.roof?String(Number(ph.roof.split('-')[1])+1).padStart(2,'0'):'--'}   HEADING ${['+X','+Y','-X','-Y'][ph.heading]}   ${status}`;
    const number=v=>v.toFixed(2),triple=v=>v.map(number).join(' ');
    document.querySelector('#lv-board-body').innerHTML=w.roofs.map(r=>{
      const pose=roofPose(w,r,ph.ms),lamp=r.lamp?(ph.lit.has(r.id)?'GOLD':'BLUE'):'--';
      const remain=Math.round(pose.remaining_ms)/1000;
      return `<tr class="${r.id===ph.roof?'lv-here':''}"><td>${String(Number(r.id.split('-')[1])+1).padStart(2,'0')}</td><td>${r.cell.join(' ')}</td><td class="lv-${lamp.toLowerCase()}">${lamp}</td><td>${r.base_z.toFixed(2)}</td>${model.started?`<td>${triple(pose.start)}</td><td>${triple(pose.goal)}</td><td>${triple(pose.next_goal)}</td><td>${remain.toFixed(3)}</td>`:'<td colspan="4">BEGIN SHIFT TO READ THE LIFT TRAJECTORY</td>'}</tr>`;
    }).join('');
    document.querySelector('#lv-board-scale').textContent=`RAMP ${(p.span_ms/1000).toFixed(3)} s   DECK ${(2*w.roofs[0].half).toFixed(2)} m   INHERITED MOTION ${p.momentum.toFixed(2)}`;
    document.querySelector('#lv-controller').textContent=p.motion_revision==='visible-lift-v1'?
      `LIFT CONTROLLER: h = 100 × (height − BASE + ${p.lift.toFixed(2)}). Next h = (${p.lift_coefficient} × TO h + ${p.lift_previous_coefficient} × FROM h) mod ${p.lift_modulus}. XY grid has ${Math.round(2*p.sway/p.motion_quantum)+1} positions, from BAY − ${p.sway.toFixed(2)} in 0.01 m steps: X index = (h + 2 × previous h) mod grid; Y index = (3 × h + previous h) mod grid.`:'';
  }
  function drawGauge(source,ahead) {
    const canvas=document.querySelector('#lv-gauge'),c=canvas.getContext('2d'),w=model.state.world,t=model.physics.ms;
    c.fillStyle='#0e1b2a';c.fillRect(0,0,340,144);c.strokeStyle='#496173';c.lineWidth=1;
    for(let z=1;z<=5;z++){const y=132-(z-1)*25;c.beginPath();c.moveTo(30,y);c.lineTo(325,y);c.stroke();c.fillStyle='#a2b8c5';c.font='10px ui-monospace';c.fillText(z,8,y+4);}
    for(const [r,color,x] of [[source,'#f3d59b',100],[ahead,'#82c9ff',245]]) {
      if(!r) continue; const pose=roofPose(w,r,t),h=z=>132-(z-1)*25;
      c.strokeStyle=color;c.lineWidth=3;c.beginPath();
      for(let i=12;i>=0;i--){const p=roofPose(w,r,Math.max(0,t-i*100)).position;i===12?c.moveTo(x-i*4,h(p[2])):c.lineTo(x-i*4,h(p[2]));}c.stroke();
      c.fillStyle=color;c.beginPath();c.arc(x,h(pose.position[2]),5,0,Math.PI*2);c.fill();
      c.strokeStyle=color;c.lineWidth=1.5;if(model.started)c.strokeRect(x+16,h(pose.goal[2])-4,8,8);
      c.fillStyle=color;c.font='10px ui-monospace';c.fillText(`${pose.position[2].toFixed(2)} ${model.started?(pose.velocity[2]>=0?'↑':'↓'):'·'}`,x-29,13);
    }
    const detail=document.querySelector('#lv-motion');
    detail.textContent=[source,ahead].map(r=>{
      if(!r)return 'NO ROOF';const p=roofPose(w,r,t);
      return `${r===source?'HERE':'AHEAD'} x ${p.position[0].toFixed(2)} y ${p.position[1].toFixed(2)}${model.started?` · lift ${(p.phase*100).toFixed(0)}% → ${p.goal[2].toFixed(2)}`:' · READY'}`;
    }).join('\n');
  }
  function renderSlots() {
    for(const panel of ['A','B']) document.querySelector(`#lv-slots-${panel}`).innerHTML=model.routines[panel].map((t,i)=>`<button class="lv-slot" data-panel="${panel}" data-index="${i}">${t?GLYPHS[t]:'·'}</button>`).join('');
  }
  function place(token,target,details) {
    if(model.terminal) return;sync();if(model.terminal) return;
    const source=model.interaction==='full'?'pointer_drag':'click_place';
    if(target.id==='lv-dispatch') {
      if(!model.started) {model.helpers.setReadout('BEGIN SHIFT FIRST','idle');return;}
      if(model.physics.flight || model.physics.ms<model.physics.busy_until || model.physics.queue.length) return;
      const commands=token==='A'||token==='B'?model.routines[token].filter(Boolean):[token];
      if(!commands.length) {model.helpers.setReadout('ROUTINE IS EMPTY','idle');return;}
      // Keep the accepted command visible. X-server acknowledgement does not
      // tell a player which task tick accepted it, and routine edits may later
      // differ from the already-running literal program.
      model.lastDispatch={t_ms:model.physics.ms,source:model.physics.roof,
        heading:model.physics.heading,commands:[...commands]};
      record('dispatch',{token,input_source:source,...details});model.physics.dispatch(commands);
      if(model.physics.failed) finish(model.physics.failed);
    } else if(target.dataset.panel && !['A','B'].includes(token)) {
      model.routines[target.dataset.panel][Number(target.dataset.index)]=token;
      record('edit',{panel:target.dataset.panel,index:Number(target.dataset.index),token,input_source:source,...details});renderSlots();
    }
    draw();
  }
  async function finish(reason='',administrative=false) {
    if(model.terminal) return;
    if(!administrative && !reason) return;
    record('seal',{input_source:administrative?'certify_button':'automatic_failure'});
    const current=model;current.terminal=true;current.failure=reason;
    const ph=current.physics,targets=current.state.world.roofs.filter(r=>r.lamp).length;
    // Input and collision handlers can advance beyond the last animation paint.
    // Retain the sealed physical scene and board before terminal drawing stops.
    draw();
    const completed=!reason && ph.lit.size===targets && !ph.flight && !ph.queue.length && ph.ms>=ph.busy_until;
    const payload={mechanic_id:current.state.mechanic_id,task_id:current.state.task_id,challenge_id:current.state.challenge_id,
      physics_revision:current.state.physics_revision,world_digest:current.state.world_digest,interaction_mode:current.interaction,
      events:current.events,final_t_ms:ph.ms,completed,lit:[...ph.lit].sort(),steps:ph.steps};
    current.payload=payload;
    const verdict=document.querySelector('#lv-verdict');verdict.hidden=false;
    verdict.innerHTML=`<b>${completed?'VERIFYING':'FAIL'}</b><span>${esc(reason || 'SHIFT SUBMITTED')}</span>`;
    current.helpers.setReadout(completed?'VERIFYING':'FAIL','pending');
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const outcome=await response.json();current.grade=outcome;
      const pass=outcome.passed===true;
      verdict.dataset.kind=pass?'pass':'fail';verdict.innerHTML=`<b>${pass?'PASS':'FAIL'}</b><span>${esc(pass?'EVERY ROOF LANTERN LIT':reason || outcome.feedback || 'SHIFT INCOMPLETE')}</span>`;
      current.helpers.setReadout(pass?'PASS':'FAIL',pass?'passed':'error');
    } catch(error) {
      verdict.dataset.kind='error';verdict.innerHTML='<b>VERIFIER ERROR</b><span>SHIFT RETAINED</span>';current.helpers.setReadout('VERIFIER ERROR','error');current.verifierError=String(error);
    }
  }
  async function render(state,helpers) {
    cancelAnimationFrame(frame);
    const world=state.world;
    model={state:copy(state),helpers,physics:new Physics(world),routines:{A:Array(world.routine_slots).fill(null),B:Array(world.routine_slots).fill(null)},
      events:[],interaction:state.control_condition.interaction,started:false,terminal:false,selected:null,drag:null,lastDispatch:null};
    window.lampwrightNonRealtimeModel=model;document.body.dataset.mechanic='lampwrights-program-nonrealtime';
    const screen=world.roofs.map(r=>[(r.cell[0]-r.cell[1])*58,(r.cell[0]+r.cell[1])*29]);
    const minX=Math.min(...screen.map(p=>p[0])),maxX=Math.max(...screen.map(p=>p[0]));
    const minY=Math.min(...screen.map(p=>p[1])),maxY=Math.max(...screen.map(p=>p[1]));
    model.projection={scale:58,ox:410-(minX+maxX)/2,oy:260-(minY+maxY)/2};
    helpers.app.innerHTML=`<section class="lv-shell"><header><div><small>THE NIGHT SHIFT / DISPATCH-SETTLED ROOFTOPS</small><h1>Lampwrights Program V2</h1><p>Light every blue lantern. A missed landing ends this shift.</p><p id="lv-last-command"></p></div><div class="lv-count"><small>LANTERNS</small><b id="lv-count"></b></div></header>
      <main><section class="lv-scene"><div class="lv-scene-head"><span>ISOMETRIC ROOFWORKS</span><b id="lv-live"></b></div><canvas id="lv-world" width="820" height="540"></canvas><div class="lv-board"><div id="lv-robot"></div><div class="lv-board-heading"><b>LIFT TRAJECTORIES / METRES</b><span id="lv-board-scale"></span></div><table><thead><tr><th>ROOF</th><th>BAY X Y</th><th>LAMP</th><th>BASE Z</th><th>FROM X Y Z</th><th>TO X Y Z</th><th>THEN X Y Z</th><th>TO IN s</th></tr></thead><tbody id="lv-board-body"></tbody></table><p>Each accepted dispatch advances the fixed moving-roof transition to a stable state. Roofs hold while you choose the next action; trails retain the settled motion history. Each bay is 1 metre.</p><p id="lv-controller"></p></div></section>
      <aside><small>ICON PROGRAMMER / ${model.interaction==='full'?'DRAG':'SELECT THEN PLACE'}</small>
      <div class="lv-palette">${TOKENS.map(t=>`<button class="lv-token" data-token="${t}"><b>${GLYPHS[t]}</b><span>${LABELS[t]}</span></button>`).join('')}</div>
      <div class="lv-routine"><span>AMBER ROUTINE · A</span><div id="lv-slots-A"></div></div><div class="lv-routine"><span>BLUE ROUTINE · B</span><div id="lv-slots-B"></div></div>
      <button id="lv-dispatch">LIVE DISPATCH <small>${model.interaction==='full'?'DROP AN ICON HERE':'PLACE SELECTED ICON HERE'}</small></button>
      <div class="lv-lift"><div>HEIGHT / RECENT MOTION <b id="lv-ahead"></b></div><canvas id="lv-gauge" width="340" height="144"></canvas><pre id="lv-motion"></pre></div>
      <p class="lv-rules">→ level launch · ↗ higher arc · ↘ lower arc.<br>Roof height and momentum change the landing distance.<br>↶ / ↷ turn · ☀ lights the blue lantern underfoot.<br>A / B run your routine without waiting for alignment.</p>
      <p class="lv-physics">Launch speed: 1 bay/s forward, 2.6 m/s up.<br>UP / DOWN add +1 / -1 m/s vertically.<br>Gravity: 5.2 m/s² · footplate: 0.13 m.<br>Turns / centering: 0.300 s · LIGHT: 0.500 s.<br>Lifts ease with 10f³ − 15f⁴ + 6f⁵ across each ramp.</p>
      <div class="lv-actions"><button id="lv-start">BEGIN SHIFT</button><button id="lv-certify">CERTIFY SHIFT</button></div></aside></main>
      <footer><div class="readout">PREPARE ROUTINES · THEN BEGIN SHIFT</div><span>Gauges: filled = now · outlines = next lift goals · trails = recent motion</span></footer><div id="lv-verdict" hidden></div><div id="lv-ghost" hidden></div></section>`;
    renderSlots();draw();
    const root=document.querySelector('.lv-shell');
    root.addEventListener('click',e=>{
      if(model.interaction!=='simplified'||model.terminal)return;
      const token=e.target.closest('[data-token]');
      if(token){model.selected=token.dataset.token;document.querySelectorAll('.lv-token').forEach(n=>n.dataset.selected=String(n===token));return;}
      const target=e.target.closest('.lv-slot,#lv-dispatch');if(target && model.selected)place(model.selected,target,{point:[e.clientX,e.clientY]});
    });
    root.addEventListener('pointerdown',e=>{
      const token=e.target.closest('[data-token]');
      if(model.interaction!=='full'||model.terminal||!token||e.button!==0)return;
      e.preventDefault();root.setPointerCapture(e.pointerId);model.drag={token:token.dataset.token,pointer:e.pointerId,start:[e.clientX,e.clientY]};
      const ghost=document.querySelector('#lv-ghost');ghost.hidden=false;ghost.textContent=GLYPHS[model.drag.token];ghost.style.left=`${e.clientX}px`;ghost.style.top=`${e.clientY}px`;
    });
    root.addEventListener('pointermove',e=>{
      if(model.drag?.pointer!==e.pointerId)return;
      const ghost=document.querySelector('#lv-ghost');ghost.style.left=`${e.clientX}px`;ghost.style.top=`${e.clientY}px`;
    });
    const cancel=()=>{model.drag=null;document.querySelector('#lv-ghost').hidden=true;};
    root.addEventListener('pointerup',e=>{
      if(model.drag?.pointer!==e.pointerId)return;
      const d=model.drag,target=document.elementFromPoint(e.clientX,e.clientY)?.closest('.lv-slot,#lv-dispatch');cancel();
      root.releasePointerCapture(e.pointerId);
      if(target && Math.hypot(e.clientX-d.start[0],e.clientY-d.start[1])>=5)place(d.token,target,{start_point:d.start,end_point:[e.clientX,e.clientY]});
    });
    root.addEventListener('pointercancel',cancel);root.addEventListener('lostpointercapture',cancel);
    document.querySelector('#lv-start').addEventListener('click',()=>{
      if(model.started||model.terminal)return;model.started=true;record('start',{input_source:'start_button'});
      document.querySelector('#lv-start').disabled=true;helpers.setReadout('SHIFT READY · DISPATCH TO ADVANCE','idle');
      draw();
    });
    document.querySelector('#lv-certify').addEventListener('click',()=>{sync();finish('',true);});
    function animate(){sync();if(!model.terminal)draw();frame=requestAnimationFrame(animate);}frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.lampwrights_program_nonrealtime={rootSelector:'.lv-shell',render};
})();
