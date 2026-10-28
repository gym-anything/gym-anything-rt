(() => {
  'use strict';
  const ID = 'pearl_lattice_v2', clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  const key = c => c.join(','), distance = (a,b) => Math.hypot(a[0]-b[0],a[1]-b[1]);
  const clean = s => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  let model, frame = 0;
  function rememberFailure() {
    if(!model.physics.failed)return;
    try {sessionStorage.setItem(model.failureKey,model.physics.failed);} catch(_){}
  }
  function noise(seed,index) {
    let n = (seed ^ Math.imul(index+1,0x9e3779b9)) >>> 0;
    n = Math.imul(n ^ (n>>>16),0x85ebca6b) >>> 0;
    n = Math.imul(n ^ (n>>>13),0xc2b2ae35) >>> 0;
    return ((n ^ (n>>>16))>>>0)/4294967295*2-1;
  }
  function motion(seed,ms,span) {
    const u = Math.max(0,ms)/span, i = Math.floor(u), f = u-i, a = noise(seed,i), b = noise(seed,i+1);
    return a+(b-a)*f*f*(3-2*f);
  }
  function gateCenter(c,layer,col,ms) {
    const g = c.physics.collars[layer];
    return [160+96*col[0]+g.offset[0]+g.amplitude[0]*motion(g.seed,ms,g.span_ms),
      96+96*col[1]+g.offset[1]+g.amplitude[1]*motion(g.seed+7919,ms,g.span_ms)];
  }
  function current(c,ms) {
    const s = c.physics;
    return [0,1].map(i => s.wind_acceleration*motion(s.wind_seed+7919*i,ms,s.wind_span_ms));
  }
  const lines = [];
  for (let x=0;x<4;x++) for (let y=0;y<4;y++) for (let z=0;z<4;z++) {
    for (let dx=-1;dx<=1;dx++) for (let dy=-1;dy<=1;dy++) for (let dz=-1;dz<=1;dz++) {
      if (!(dx || dy || dz)) continue;
      const end = [x+3*dx,y+3*dy,z+3*dz], before = [x-dx,y-dy,z-dz];
      if (end.some(n=>n<0||n>3) || before.every(n=>n>=0&&n<=3)) continue;
      lines.push([0,1,2,3].map(i=>[x+i*dx,y+i*dy,z+i*dz]));
    }
  }
  const hasLine = (board,mark) => lines.some(l=>l.every(c=>board[key(c)]===mark));
  function height(board,col) { for (let y=0;y<4;y++) if (!board[key([col[0],y,col[1]])]) return y; return 4; }
  function legal(board) { const out=[]; for(let z=0;z<4;z++)for(let x=0;x<4;x++)if(height(board,[x,z])<4)out.push([x,z]); return out; }
  function drop(board,col,mark) { const y=height(board,col); if(y===4)return null; const c=[col[0],y,col[1]]; board[key(c)]=mark; return c; }
  function immediate(board,mark) {
    return legal(board).filter(col=> { const c=drop(board,col,mark), won=hasLine(board,mark); delete board[key(c)]; return won; });
  }
  class CastingPhysics {
    constructor(contract) {
      this.contract=contract; this.s=contract.physics; this.tick=0;
      this.head=[...this.s.initial_magnet]; this.hv=[0,0]; this.target=[...this.head];
      this.ball=null; this.board={...contract.initial_board}; this.pressureIndex=0; this.moves=0;
      this.won=false; this.failed=''; this.landings=[];
    }
    launch() {
      if(this.ball||this.won||this.failed)return false;
      this.ball={p:[...this.head],v:[...this.hv],depth:0,vy:0,gate:0,channel:null}; return true;
    }
    rival() {
      const c=this.contract, own=immediate(this.board,-1);
      if(own.length)return own[0];
      const block=c.control_condition.difficulty_parameters.opponent_policy==='threat_then_block'?immediate(this.board,1):[];
      if(block.length)return block[0];
      for(let i=0;i<c.pressure_columns.length;i++) {
        const col=c.pressure_columns[(this.pressureIndex+i)%c.pressure_columns.length];
        if(height(this.board,col)<4) { this.pressureIndex+=i+1; return col; }
      }
      this.pressureIndex++; return legal(this.board)[0]||null;
    }
    advance(endTick) {
      const s=this.s;
      while(this.tick<endTick && !this.won && !this.failed) {
        this.tick++; const ms=this.tick*10;
        for(let i=0;i<2;i++) {
          const a=clamp((this.target[i]-this.head[i])*s.magnet_spring-this.hv[i]*s.magnet_damping,-s.magnet_acceleration,s.magnet_acceleration);
          this.hv[i]=clamp(this.hv[i]+a*.01,-s.magnet_speed,s.magnet_speed);
          this.head[i]=clamp(this.head[i]+this.hv[i]*.01,24,s.field[i]-24);
          if(this.head[i]===24||this.head[i]===s.field[i]-24)this.hv[i]=0;
        }
        if(!this.ball)continue;
        const b=this.ball, oldP=[...b.p], oldDepth=b.depth, wind=current(this.contract,ms);
        for(let i=0;i<2;i++) {
          const a=clamp((this.head[i]-b.p[i])*s.steering_spring-b.v[i]*s.steering_damping+wind[i],-s.pearl_acceleration,s.pearl_acceleration);
          b.v[i]=clamp(b.v[i]+a*.01,-s.pearl_speed,s.pearl_speed); b.p[i]+=b.v[i]*.01;
          if(b.p[i]<s.pearl_radius||b.p[i]>s.field[i]-s.pearl_radius) { this.failed='The pearl struck the outer glass.'; break; }
        }
        if(this.failed)break;
        b.vy+=s.gravity*.01; b.depth+=b.vy*.01;
        const layer=b.gate, rim=s.collars[layer].depth;
        if(oldDepth<rim && rim<=b.depth) {
          const f=(rim-oldDepth)/(b.depth-oldDepth), p=oldP.map((v,i)=>v+f*(b.p[i]-v)), t=ms-10+10*f;
          const candidates=layer===0?legal(this.board):[b.channel];
          const hit=candidates.find(col=>distance(p,gateCenter(this.contract,layer,col,t))+s.pearl_radius<=s.mouth_radius+1e-9);
          if(!hit) { this.failed=`The pearl struck the ${layer===0?'upper':'lower'} collar.`; break; }
          if(layer===0) { b.gate=1; b.channel=[...hit]; }
          else {
            const cell=drop(this.board,hit,1);
            if(!cell) { this.failed='The column is full.'; break; }
            this.moves++;
            const landing={tick:this.tick,column:[...hit],height:cell[1],rival:null};
            this.ball=null; this.won=hasLine(this.board,1);
            if(!this.won) {
              if(this.moves>=this.contract.control_condition.difficulty_parameters.max_player_moves)this.failed='No jade line remains within the placement limit.';
              else {
                const col=this.rival();
                if(!col)this.failed='The glass lattice is full.';
                else { landing.rival=drop(this.board,col,-1); if(hasLine(this.board,-1))this.failed='The coral rival completed four.'; }
              }
            }
            this.landings.push(landing);
          }
        }
      }
    }
    snapshot() {
      return {tick:this.tick,head:this.head,hv:this.hv,target:this.target,ball:this.ball,
        board:this.board,moves:this.moves,won:this.won,failed:this.failed,landings:this.landings};
    }
  }
  // Exposed only for implementation diagnostics; downstream players use pixels.
  window.PearlLatticeCasting={noise,motion,gateCenter,current,CastingPhysics,lines};
  function record(kind,details={}) { model.events.push({seq:model.events.length+1,tick:model.physics.tick,kind,...details}); }
  function sync() {
    if(model.submitted||model.physics.won||model.physics.failed)return;
    model.physics.advance(Math.min(18000,Math.floor((performance.now()-model.startedAt)/10)));
    if(model.physics.tick===18000 && !model.physics.won)model.physics.failed='The casting session ended without a jade line.';
    if(model.physics.failed&&!model.submitted)seal();
  }
  function point(event) {
    const r=document.querySelector('.plv-field').getBoundingClientRect();
    return [clamp((event.clientX-r.left)/r.width*640,0,640),clamp((event.clientY-r.top)/r.height*480,0,480)].map(x=>Math.round(x*1000)/1000);
  }
  function down(event) {
    if(event.button!==0||model.submitted)return;
    sync(); if(model.physics.won||model.physics.failed)return;
    const p=point(event);
    if(model.mode==='simplified') { model.physics.target=p;record('aim_target',{source:'magnet_click',point:p}); }
    else if(!model.hold && distance(p,model.physics.head)<=model.state.physics.magnet_radius) {
      model.hold=event.pointerId; event.currentTarget.setPointerCapture(event.pointerId);
      record('aim_start',{source:'magnet_drag',point:p});
    }
    event.preventDefault(); draw();
  }
  function move(event) {
    if(model.hold!==event.pointerId||model.submitted)return;
    sync(); if(model.physics.won||model.physics.failed)return;
    const p=point(event); model.physics.target=p; record('aim_move',{source:'magnet_drag',point:p});
    event.preventDefault(); draw();
  }
  function up(event) {
    if(model.hold!==event.pointerId)return;
    sync();
    if(!model.submitted)record('aim_end',{source:'magnet_drag',point:point(event)});
    model.hold=null;
    try {event.currentTarget.releasePointerCapture(event.pointerId);} catch(_){}
    draw();
  }
  function circle(ctx,p,r,color,fill=false) {
    ctx.beginPath();ctx.arc(p[0],p[1],r,0,Math.PI*2);ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();
    if(fill) {ctx.fillStyle=color;ctx.fill();}
  }
  function arrow(ctx,start,end,color) {
    const angle=Math.atan2(end[1]-start[1],end[0]-start[0]);
    ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(...start);ctx.lineTo(...end);
    ctx.moveTo(end[0]-7*Math.cos(angle-.5),end[1]-7*Math.sin(angle-.5));ctx.lineTo(...end);ctx.lineTo(end[0]-7*Math.cos(angle+.5),end[1]-7*Math.sin(angle+.5));ctx.stroke();
  }
  function drawField() {
    const canvas=document.querySelector('.plv-field'), ctx=canvas.getContext('2d'), p=model.physics, ms=p.tick*10,s=model.state.physics;
    ctx.clearRect(0,0,640,480);ctx.fillStyle='#081e27';ctx.fillRect(0,0,640,480);
    ctx.strokeStyle='#183c47';ctx.lineWidth=1;
    for(let x=16;x<640;x+=32) {ctx.beginPath();ctx.moveTo(x,12);ctx.lineTo(x,468);ctx.stroke();}
    for(let y=16;y<480;y+=32) {ctx.beginPath();ctx.moveTo(12,y);ctx.lineTo(628,y);ctx.stroke();}
    ctx.strokeStyle='#7fa7a2';ctx.lineWidth=2;ctx.strokeRect(7,7,626,466);
    const active=p.ball?.gate||0;
    for(const layer of [1-active,active]) {
      for(let z=0;z<4;z++)for(let x=0;x<4;x++) {
        const col=[x,z], center=gateCenter(model.state,layer,col,ms), closed=height(p.board,col)===4 || (layer===1&&p.ball?.channel&&key(col)!==key(p.ball.channel));
        const selected=layer===active&&!closed, color=selected?(layer===0?'#efc578':'#7dedcd'):'#47757a';
        ctx.globalAlpha=selected?1:.35;
        const past=gateCenter(model.state,layer,col,Math.max(0,ms-600));
        ctx.strokeStyle=color;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(...past);ctx.lineTo(...center);ctx.stroke();
        ctx.fillStyle=selected?'#102c34':'#0a2028';ctx.beginPath();ctx.arc(...center,s.mouth_radius,0,Math.PI*2);ctx.fill();
        circle(ctx,center,s.mouth_radius,color);
        if(closed) {ctx.beginPath();ctx.moveTo(center[0]-12,center[1]-12);ctx.lineTo(center[0]+12,center[1]+12);ctx.moveTo(center[0]+12,center[1]-12);ctx.lineTo(center[0]-12,center[1]+12);ctx.stroke();}
        else {ctx.fillStyle=color;ctx.font='bold 14px ui-monospace,monospace';ctx.textAlign='center';ctx.fillText(`${'ABCD'[x]}${z+1}`,center[0],center[1]+5);}
        ctx.globalAlpha=1;
      }
    }
    const wind=current(model.state,ms); arrow(ctx,[570,46],[570+wind[0]*.22,46+wind[1]*.22],'#8ec3d1');
    ctx.fillStyle='#9abec5';ctx.font='11px ui-monospace,monospace';ctx.textAlign='center';ctx.fillText('CURRENT',570,18);
    ctx.strokeStyle='#dc8af055';ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(...p.head);ctx.lineTo(...p.target);ctx.stroke();ctx.setLineDash([]);
    circle(ctx,p.target,5,'#dc8af0');circle(ctx,p.head,24,'#df89ed');
    circle(ctx,p.head,19,'#6f315e',true);ctx.fillStyle='#ffd3fc';ctx.font='bold 15px Georgia';ctx.fillText('M',p.head[0],p.head[1]+5);
    if(p.ball) {
      arrow(ctx,p.ball.p.map((v,i)=>v-p.ball.v[i]*.2),p.ball.p,'#f5fbde');
      circle(ctx,p.ball.p,12,'#fffde833');circle(ctx,p.ball.p,7,'#fffdeb',true);
      const y=100+Math.min(800,p.ball.depth)/800*300;
      ctx.fillStyle='#06151c';ctx.fillRect(605,95,18,312);ctx.strokeStyle='#779b9c';ctx.strokeRect(605,95,18,312);
      for(const g of s.collars) {ctx.fillStyle='#efc578';ctx.fillRect(603,100+g.depth/800*300,22,3);}
      ctx.fillStyle='#fffdeb';ctx.beginPath();ctx.arc(614,y,6,0,Math.PI*2);ctx.fill();
    }
  }
  function project(c) {
    const a=model.yaw*Math.PI/180, x=(c[0]-1.5)*69,z=(c[2]-1.5)*69;
    return {x:240+x*Math.cos(a)-z*Math.sin(a),y:245-(c[1]-1.5)*62+(x*Math.sin(a)+z*Math.cos(a))*.45,depth:x*Math.sin(a)+z*Math.cos(a)};
  }
  function drawBoard() {
    const canvas=document.querySelector('.plv-volume'), ctx=canvas.getContext('2d'), board=model.physics.board;
    ctx.fillStyle='#0b222a';ctx.fillRect(0,0,480,480);
    ctx.strokeStyle='#416e7370';ctx.lineWidth=1;
    for(let x=0;x<4;x++)for(let y=0;y<4;y++)for(let z=0;z<4;z++) {
      const c=[x,y,z],p=project(c);
      for(const v of [[1,0,0],[0,1,0],[0,0,1]]) {
        const d=c.map((n,i)=>n+v[i]);if(d.some(n=>n>3))continue;
        const q=project(d);ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke();
      }
    }
    const balls=Object.entries(board).map(([k,v])=>({c:k.split(',').map(Number),v})).map(o=>({...o,p:project(o.c)})).sort((a,b)=>a.p.depth-b.p.depth);
    for(const {c,v,p} of balls) {
      const g=ctx.createRadialGradient(p.x-5,p.y-6,1,p.x,p.y,18);
      g.addColorStop(0,v===1?'#e0fff1':'#ffe6db');g.addColorStop(.45,v===1?'#68d9b8':'#ed947e');g.addColorStop(1,v===1?'#185d56':'#733744');
      ctx.fillStyle=g;ctx.beginPath();ctx.arc(p.x,p.y,17,0,Math.PI*2);ctx.fill();ctx.strokeStyle=v===1?'#a5ffe1':'#ffc9b8';ctx.lineWidth=1.5;ctx.stroke();
      ctx.fillStyle='#051e24';ctx.font='bold 12px ui-monospace,monospace';ctx.textAlign='center';ctx.fillText(String(c[1]+1),p.x,p.y+4);
    }
    for(let x=0;x<4;x++)for(let z=0;z<4;z++) {const p=project([x,-.6,z]);ctx.fillStyle='#b4d3cb';ctx.font='12px ui-monospace,monospace';ctx.textAlign='center';ctx.fillText(`${'ABCD'[x]}${z+1}`,p.x,p.y);}
    if(model.physics.won) {
      const line=lines.find(l=>l.every(c=>board[key(c)]===1));
      const a=project(line[0]),b=project(line[3]);ctx.lineWidth=5;ctx.strokeStyle='#d6ffae';ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
    }
  }
  function draw() {
    if(!model)return;
    drawField();drawBoard();
    const p=model.physics, root=document.querySelector('.plv-shell');
    root.dataset.status=p.failed?'failed':p.won?'won':p.ball?'casting':'ready';
    document.querySelector('.plv-phase').textContent=p.failed?'CASTING ENDED':p.won?'JADE LINE COMPLETE':p.ball?(p.ball.gate===0?'UPPER COLLAR • STEER':'LOWER COLLAR • STEER'):'AIM • RELEASE • STEER';
    document.querySelector('.plv-moves').textContent=`${p.moves} / ${model.state.control_condition.difficulty_parameters.max_player_moves}`;
    document.querySelector('.plv-channel').textContent=p.ball?.channel?`${'ABCD'[p.ball.channel[0]]}${p.ball.channel[1]+1} • lower collar only`:'Upper amber → lower jade';
    document.querySelector('.plv-release').disabled=!!p.ball||p.won||!!p.failed||model.submitted;
    document.querySelector('.plv-seal').disabled=model.submitted;
    if(p.failed)document.querySelector('.plv-verdict').innerHTML=`<strong>FAIL</strong><span>${clean(p.failed)}</span>`;
  }
  function animate() {sync();draw();frame=requestAnimationFrame(animate);}
  async function seal() {
    if(model.submitted)return;
    if(!model.physics.failed&&!model.physics.won)model.physics.failed='Incomplete casting was certified.';
    rememberFailure();
    model.submitted=true;record('seal',{source:'seal_button'});draw();
    const p=model.physics, payload={mechanic_id:ID,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      control_condition:model.state.control_condition,events:model.events,final_tick:p.tick,final_board:p.board,
      landings:p.landings,completed:p.won&&!p.failed};
    model.result=payload;
    try {
      const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)}), outcome=await r.json();
      model.outcome=outcome;
      document.querySelector('.plv-verdict').innerHTML=outcome.passed?'<strong>PASS</strong><span>Four jade pearls • one volumetric line</span>':`<strong>FAIL</strong><span>${clean(p.failed||outcome.feedback||'Casting rejected.')}</span>`;
      document.querySelector('.plv-shell').dataset.verdict=outcome.passed?'pass':'fail';
      model.helpers.setReadout(outcome.passed?'PASS':'FAIL • ATTEMPT ENDED',outcome.passed?'passed':'error');
    } catch(error) {model.helpers.setReadout('VERIFIER LINK ERROR','error');document.querySelector('.plv-shell').dataset.verdict='fail';}
  }
  function render(state,helpers) {
    cancelAnimationFrame(frame);
    document.body.dataset.mechanic='pearl-lattice-v2';
    model={state,helpers,physics:new CastingPhysics(state),events:[],mode:state.control_condition.interaction,hold:null,yaw:32,startedAt:performance.now(),submitted:false,
      failureKey:`${ID}:terminal:${state.task_id}:${location.search}`};
    // Reload is prohibited during evaluation. Retain the visible terminal state
    // anyway; the independent exported verifier also checks the server ledger.
    try {
      const priorFailure=sessionStorage.getItem(model.failureKey);
      if(priorFailure) {model.physics.failed=priorFailure;model.submitted=true;model.outcome={passed:false};}
    } catch(_){}
    window.pearlLatticeV2Model=model;
    helpers.app.innerHTML=`<section class="plv-shell" data-interaction="${model.mode}"><header class="plv-header"><div><span>THE GLASSHOUSE / CONTINUOUS CASTING</span><h1>Pearl Lattice <i>II</i></h1></div><p>Four jade pearls. One line through the volume.<br><b>The coral rival moves after each delivery.</b></p><div class="plv-chip">PLACEMENTS<strong class="plv-moves">0</strong></div></header>
      <main class="plv-main"><section class="plv-casting"><header><b>OVERHEAD CASTING FIELD</b><span class="plv-phase"></span></header><canvas class="plv-field" width="640" height="480" aria-label="Moving collar field with draggable magnet and falling pearl"></canvas><div class="plv-caption"><span class="plv-channel"></span><span>Trails show the last 0.6 seconds.</span></div></section>
      <section class="plv-lattice"><header><b>4 × 4 × 4 / GRAVITY LATTICE</b><div><button class="plv-view-left" aria-label="Turn lattice view left">↶</button><button class="plv-view-right" aria-label="Turn lattice view right">↷</button></div></header><canvas class="plv-volume" width="480" height="480" aria-label="Jade and coral pearls in the volumetric gravity board"></canvas><div class="plv-caption"><span>Jade = you · Coral = rival</span><span>Pearl numbers = layer</span></div></section></main>
      <footer class="plv-footer"><button class="plv-release">RELEASE PEARL <span>Confirm below the field</span></button><div><p>${model.mode==='full'?'Drag the violet magnet':'Click to set the violet magnet target'}. Pass amber, then the same jade channel.</p><p>The magnet pulls; it does not carry. A collar impact ends the attempt.</p><div class="readout" data-status="idle">Inspect the lattice before casting.</div></div><button class="plv-seal">CERTIFY LINE</button></footer><div class="plv-verdict"></div></section>`;
    const field=document.querySelector('.plv-field');
    field.addEventListener('pointerdown',down);field.addEventListener('pointermove',move);
    field.addEventListener('pointerup',up);field.addEventListener('pointercancel',up);
    field.addEventListener('lostpointercapture',event=> {if(model.hold===event.pointerId)up(event);});
    document.querySelector('.plv-release').addEventListener('click',()=> {sync();if(!model.hold&&!model.submitted&&model.physics.launch())record('launch',{source:'release_button'});draw();});
    document.querySelector('.plv-seal').addEventListener('click',()=> {sync();if(!model.hold)seal();});
    document.querySelector('.plv-view-left').addEventListener('click',()=> {model.yaw-=25;draw();});
    document.querySelector('.plv-view-right').addEventListener('click',()=> {model.yaw+=25;draw();});
    draw();
    if(model.submitted) {document.querySelector('.plv-shell').dataset.verdict='fail';helpers.setReadout('FAIL • ATTEMPT ENDED','error');}
    frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.plv-shell',render};
})();
