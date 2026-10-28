(() => {
  'use strict';
  let model, raf = 0, keyDown, keyUp;
  const noise = (seed, index) => {
    let x = (seed ^ Math.imul(index + 1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  };
  const motion = (seed, ms, span) => {
    const u = Math.max(0, ms) / span, n = Math.floor(u), f = u - n;
    return noise(seed,n) + (noise(seed,n+1)-noise(seed,n))*f*f*(3-2*f);
  };
  const derivative = (seed, ms, span) => {
    const u = Math.max(0,ms)/span, n = Math.floor(u), f = u-n;
    return (noise(seed,n+1)-noise(seed,n))*6*f*(1-f)*1000/span;
  };
  const angleError = (a,b) => ((a-b+180)%360+360)%360-180;
  function pose(index, tick=model.physics.tick) {
    const s=model.state.slots[index], p=model.state.profile, ms=tick*model.state.tick_ms;
    const span=p.drift_span_ms, seed=s.motion_seed;
    return {x:s.base[0]+p.drift_px*motion(seed,ms,span),
      y:s.base[1]+p.drift_px*motion(seed+7919,ms,span),
      angle:p.angle_amplitude*motion(seed+15838,ms,span),
      vx:p.drift_px*derivative(seed,ms,span), vy:p.drift_px*derivative(seed+7919,ms,span),
      omega:p.angle_amplitude*derivative(seed+15838,ms,span)};
  }
  function initial(state) {
    return {tick:0,running:false,terminal:false,failed:false,held:null,target:null,turn:0,
      placed:{},misses:0,pieces:Object.fromEntries(state.pieces.map(p=>[p.id,
        {x:p.home[0],y:p.home[1],angle:p.angle,vx:0,vy:0}]))};
  }
  function advance(target) {
    const s=model.physics, c=model.state, p=c.profile, dt=c.tick_ms/1000;
    while(s.tick<target && !s.terminal) {
      if(s.held) {
        const b=s.pieces[s.held];
        for(const [axis,vaxis,i] of [['x','vx',0],['y','vy',1]]) {
          const force=p.current_force*motion(c.current_seed+i*7919,s.tick*c.tick_ms,2100);
          b[vaxis]+=(p.spring*(s.target[i]-b[axis])-p.damping*b[vaxis]+force)*dt;
        }
        const speed=Math.hypot(b.vx,b.vy);
        if(speed>p.max_speed) {b.vx*=p.max_speed/speed;b.vy*=p.max_speed/speed;}
        for(const [axis,vaxis,limit] of [['x','vx',970],['y','vy',560]]) {
          b[axis]+=b[vaxis]*dt;
          if(b[axis]<40 || b[axis]>limit-40) {b[axis]=Math.max(40,Math.min(limit-40,b[axis]));b[vaxis]=0;}
        }
        b.angle=angleError(b.angle+s.turn*c.rotation_speed*dt,0);
      }
      s.tick++;
      if(s.tick>=c.max_time_ms/c.tick_ms) {s.terminal=s.failed=true;finish('TIME EXPIRED');}
    }
  }
  function sync() {
    if(!model || !model.physics.running || model.physics.terminal) return;
    advance(Math.min(model.state.max_time_ms/model.state.tick_ms,
      Math.floor(Math.max(0,performance.now()-model.startedAt)/model.state.tick_ms)));
  }
  function record(kind,extra={}) {
    model.events.push({sequence:model.events.length+1,kind,tick:model.physics.tick,
      input_source:kind==='start'?'button':({full:{grab:'drag',aim:'drag',turn:'keys',drop:'release',cancel:'drag'},
        simplified:{grab:'select',aim:'point',turn:'buttons',drop:'stitch',cancel:'button'}})[model.mode][kind],...extra});
  }
  const eligible=()=>model.physics.running && !model.physics.terminal;
  function start() {
    if(model.physics.running || model.physics.terminal) return;
    model.startedAt=performance.now(); model.physics.running=true;record('start');
    document.querySelector('#loom-start').disabled=true;
    model.helpers.setReadout('LOOM RUNNING · MATCH THE MOTION, THEN ALIGN THE FRAME','idle');
    draw();
  }
  function hit(b,point) {
    const a=b.angle*Math.PI/180,x=point[0]-b.x,y=point[1]-b.y,r=model.state.piece_size/2;
    return Math.abs(x*Math.cos(a)+y*Math.sin(a))<=r && Math.abs(-x*Math.sin(a)+y*Math.cos(a))<=r;
  }
  function grab(point) {
    sync(); if(!eligible() || model.physics.held) return false;
    const p=[...model.state.pieces].reverse().find(p=>!(p.id in model.physics.placed) && hit(model.physics.pieces[p.id],point));
    if(!p) return false;
    model.physics.held=p.id;
    const b=model.physics.pieces[p.id]; model.physics.target=[b.x,b.y];
    model.offset=[point[0]-b.x,point[1]-b.y];
    record('grab',{piece_id:p.id,point});draw();return true;
  }
  function aim(point) {
    sync(); if(!eligible() || !model.physics.held) return;
    const clamped=[Math.max(0,Math.min(970,point[0])),Math.max(0,Math.min(560,point[1]))];
    model.physics.target=clamped;record('aim',{point:clamped});
  }
  function turn(direction) {
    sync(); if(!eligible() || model.physics.turn===direction) return;
    model.physics.turn=direction;record('turn',{direction});
  }
  function drop(cancel=false) {
    sync(); const s=model.physics;
    if(!eligible() || !s.held) return;
    record(cancel?'cancel':'drop');
    const id=s.held,b=s.pieces[id],p=model.state.profile;
    const slot=cancel ? -1 : model.state.slots.findIndex((slot,i)=> {
      if(Object.values(s.placed).includes(i)) return false;
      const t=pose(i);
      return Math.hypot(b.x-t.x,b.y-t.y)<=p.position_tolerance+1e-7 && Math.abs(angleError(b.angle,t.angle))<=p.angle_tolerance+1e-7;
    });
    if(slot>=0) {
      if(model.state.pieces.find(p=>p.id===id).source_index!==slot) {
        s.failed=s.terminal=true;
        s.held=null;s.target=null;draw();finish('WRONG FRAGMENT STITCHED');return;
      }
      s.placed[id]=slot;
      model.helpers.setReadout(`STITCHED ${Object.keys(s.placed).length}/${model.state.pieces.length}`,'idle');
    } else {
      s.misses+=Number(!cancel);
      if(!cancel) {s.failed=s.terminal=true;s.held=null;s.target=null;draw();finish('FRAME MISALIGNED');return;}
      const home=model.state.pieces.find(p=>p.id===id).home;
      Object.assign(b,{x:home[0],y:home[1],vx:0,vy:0});
      model.helpers.setReadout(cancel?'FRAGMENT RETURNED':'FRAME MISALIGNED · FRAGMENT RETURNED','idle');
    }
    s.held=null;s.target=null;draw();
    if(Object.keys(s.placed).length===model.state.pieces.length) {s.terminal=true;finish();}
  }
  async function finish(reason='') {
    if(model.submitted) return;
    model.submitted=true;
    if(reason) model.physics.failed=true;
    model.physics.terminal=true;
    const s=model.physics,c=model.state;
    const payload={mechanic_id:c.mechanic_id,task_id:c.task_id,challenge_id:c.challenge_id,
      revision:c.revision,interaction_mode:model.mode,events:model.events,final_tick:s.tick,
      placements:s.placed,misses:s.misses,failed:s.failed,
      completed:!s.failed && Object.keys(s.placed).length===c.pieces.length};
    model.payload=payload;
    const stamp=document.querySelector('.loom-verdict');
    stamp.hidden=false;stamp.dataset.status=reason?'fail':'pending';
    stamp.textContent=reason?'FAIL · '+reason:'VERIFYING';
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const result=await response.json();model.serverGrade=result;
      stamp.dataset.status=result.passed?'pass':'fail';
      stamp.textContent=result.passed?'PASS · GHOST PICTURE RESTORED':'FAIL · '+(reason || 'INCOMPLETE PICTURE');
      model.helpers.setReadout(stamp.textContent,result.passed?'passed':'error');
    } catch(error) {stamp.textContent='VERIFIER ERROR';model.helpers.setReadout(error.message,'error');}
  }
  function mask(index,x,y) {
    const cols=model.state.profile.columns;
    x=(index%cols)*100+x*100;y=Math.floor(index/cols)*100+y*100;
    return model.state.glyphs.some(g=> {
      if(g.kind==='ring') return Math.abs(Math.hypot(x-g.x,y-g.y)-g.radius)<g.width;
      const dx=g.b[0]-g.a[0],dy=g.b[1]-g.a[1];
      const t=Math.max(0,Math.min(1,((x-g.a[0])*dx+(y-g.a[1])*dy)/(dx*dx+dy*dy)));
      return Math.hypot(x-g.a[0]-t*dx,y-g.a[1]-t*dy)<g.width;
    });
  }
  function texture(seed,x,y) {
    const u=x/4,v=y/4,ix=Math.floor(u),iy=Math.floor(v),fx=u-ix,fy=v-iy;
    const value=(a,b)=>noise(seed,Math.imul(a,73856093)^Math.imul(b,19349663));
    return (value(ix,iy)*(1-fx)+value(ix+1,iy)*fx)*(1-fy)+(value(ix,iy+1)*(1-fx)+value(ix+1,iy+1)*fx)*fy;
  }
  function patch(piece,ms,reference=false) {
    const key=piece.id+(reference?'_reference':'');
    const canvas=model.patches[key],ctx=canvas.getContext('2d'),w=canvas.width,img=model.images[key];
    const offset=ms*model.state.noise_speed/1000,bitmap=model.masks[piece.id];
    for(let y=0;y<w;y++) for(let x=0;x<w;x++) {
      const inside=bitmap[y*w+x],gray=Math.round(128+85*texture(piece.noise_seed+(reference?104729:0)+(inside?7919:0),x,y+(inside?-offset:offset)));
      const i=(y*w+x)*4;img.data[i]=gray;img.data[i+1]=gray+2;img.data[i+2]=gray+3;img.data[i+3]=255;
    }
    ctx.putImageData(img,0,0);return canvas;
  }
  function outline(ctx,b,color,tolerance=false) {
    ctx.save();ctx.translate(b.x,b.y);ctx.rotate(b.angle*Math.PI/180);
    ctx.strokeStyle=color;ctx.lineWidth=tolerance?2:2.5;
    ctx.strokeRect(-40,-40,80,80);
    ctx.fillStyle=color;ctx.beginPath();ctx.arc(0,-40,4,0,Math.PI*2);ctx.fill();
    if(tolerance) {
      const p=model.state.profile;
      ctx.strokeStyle=color+'88';ctx.beginPath();ctx.arc(0,0,p.position_tolerance,0,Math.PI*2);ctx.stroke();
      ctx.beginPath();ctx.arc(0,0,36,(-90-p.angle_tolerance)*Math.PI/180,(-90+p.angle_tolerance)*Math.PI/180);ctx.stroke();
    }
    ctx.restore();
  }
  function draw() {
    if(!model) return;
    const canvas=document.querySelector('#loom-canvas'),ctx=canvas.getContext('2d'),s=model.physics;
    ctx.clearRect(0,0,970,560);ctx.fillStyle='#09121c';ctx.fillRect(0,0,970,560);
    ctx.strokeStyle='#284058';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(384,0);ctx.lineTo(384,560);ctx.stroke();
    ctx.fillStyle='#9ab1c7';ctx.font='12px monospace';ctx.fillText('LOOSE FRAGMENTS',24,26);ctx.fillText('DRIFTING FRAME',428,26);
    for(let i=0;i<model.state.slots.length;i++) {
      const t=pose(i),filled=Object.values(s.placed).includes(i);
      outline(ctx,t,filled?'#a3e5d3':'#719bbd',true);
      if(!filled) {
        ctx.strokeStyle='#70c5df';ctx.beginPath();ctx.moveTo(t.x,t.y);ctx.lineTo(t.x+t.vx*.45,t.y+t.vy*.45);ctx.stroke();
        ctx.fillStyle='#70c5df';ctx.beginPath();ctx.arc(t.x+t.vx*.45,t.y+t.vy*.45,2.5,0,Math.PI*2);ctx.fill();
      }
    }
    const ms=s.running?s.tick*model.state.tick_ms:performance.now()-model.previewAt;
    const reference=document.querySelector('#loom-reference'),rctx=reference.getContext('2d');rctx.clearRect(0,0,216,216);
    const rows=model.state.profile.rows,cols=model.state.profile.columns;
    for(const piece of model.state.pieces) {
      const image=patch(piece,ms,true),source=piece.source_index;
      rctx.drawImage(image,source%cols*216/cols,Math.floor(source/cols)*216/rows,216/cols,216/rows);
    }
    rctx.strokeStyle='#f7ddbd88';rctx.lineWidth=1;
    for(let i=1;i<cols;i++) {rctx.beginPath();rctx.moveTo(i*216/cols,0);rctx.lineTo(i*216/cols,216);rctx.stroke();}
    for(let i=1;i<rows;i++) {rctx.beginPath();rctx.moveTo(0,i*216/rows);rctx.lineTo(216,i*216/rows);rctx.stroke();}
    const ordered=[...model.state.pieces].sort((a,b)=>Number(a.id===s.held)-Number(b.id===s.held));
    for(const piece of ordered) {
      const b=piece.id in s.placed?pose(s.placed[piece.id]):s.pieces[piece.id];
      const image=patch(piece,ms);
      ctx.save();ctx.translate(b.x,b.y);ctx.rotate(b.angle*Math.PI/180);
      ctx.globalAlpha=piece.id===s.held?.85:1;ctx.drawImage(image,-40,-40,80,80);ctx.restore();
      outline(ctx,b,piece.id===s.held?'#ffd49a':piece.id in s.placed?'#a3e5d3':'#9db2c4');
      if(piece.id===s.held) {
        ctx.strokeStyle='#ffd49a';ctx.beginPath();ctx.moveTo(b.x,b.y);ctx.lineTo(s.target[0],s.target[1]);ctx.stroke();
        ctx.beginPath();ctx.arc(s.target[0],s.target[1],5,0,Math.PI*2);ctx.stroke();
      }
    }
    document.querySelector('#loom-count').textContent=`${Object.keys(s.placed).length} / ${model.state.pieces.length}`;
    document.querySelector('#loom-clock').textContent=s.running?`${Math.max(0,(model.state.max_time_ms-s.tick*model.state.tick_ms)/1000).toFixed(1)}s`:'READY';
  }
  function animate() {sync();draw();raf=requestAnimationFrame(animate);}
  async function render(state,helpers) {
    cancelAnimationFrame(raf);
    if(keyDown) window.removeEventListener('keydown',keyDown);
    if(keyUp) window.removeEventListener('keyup',keyUp);
    document.body.dataset.mechanic='ghost-loom-v2';
    model={state,helpers,mode:state.control_condition.interaction,physics:initial(state),events:[],submitted:false,
      previewAt:performance.now(),startedAt:0,patches:{},images:{},masks:{},keys:new Set(),pointer:null,offset:[0,0]};
    window.motionOnlyGhostJigsawV2Model=model;
    const full=model.mode==='full';
    helpers.app.innerHTML=`<section class="ghost-loom"><header><div><p>MOTION STUDIES / A DRIFTING LOOM</p><h1>Motion-Only Ghost Jigsaw V2</h1></div><span id="loom-clock">READY</span></header>
      <div class="loom-rules">The picture emerges from opposite-moving grain. Match each fragment to the reference, follow its moving frame, and align the top dots. ${full?'Drag a fragment. Hold A / D to turn it. Release to stitch; ESC cancels.':'Select a fragment, click to steer it, hold the turn buttons, then press STITCH.'} A misaligned or wrong stitch ends the attempt; cancel a carry to return it safely.</div>
      <main><canvas id="loom-canvas" width="970" height="560" aria-label="moving ghost fragments and docking frames"></canvas><aside><label>LIVE REFERENCE</label><canvas id="loom-reference" width="216" height="216"></canvas><div class="loom-score"><b id="loom-count">0 / ${state.pieces.length}</b><span>FRAGMENTS STITCHED</span></div><button id="loom-start">START LOOM</button>
      ${full?'<div class="loom-controls">DRAG to carry<br>Hold A / D to turn<br>RELEASE to stitch<br>ESC to return safely</div>':'<div class="loom-turns"><button id="loom-left">↶ TURN</button><button id="loom-right">TURN ↷</button></div><button id="loom-stitch">STITCH</button><button id="loom-return">RETURN TO TRAY</button>'}
      <p class="loom-legend">Blue trails show frame velocity.<br>Gold tether shows where you steer.<br>The fragment follows with inertia.<br>The circular guide and top arc show the allowed alignment.</p></aside></main>
      <footer><span class="readout">Inspect the moving grain, then start.</span><button id="loom-submit">CERTIFY PICTURE</button></footer><div class="loom-verdict" hidden></div></section>`;
    for(const piece of state.pieces) {
      for(const key of [piece.id,piece.id+'_reference']) {
        const c=document.createElement('canvas');c.width=c.height=72;model.patches[key]=c;
        model.images[key]=c.getContext('2d').createImageData(72,72);
      }
      const bitmap=new Uint8Array(72*72);
      for(let y=0;y<72;y++) for(let x=0;x<72;x++) bitmap[y*72+x]=Number(mask(piece.source_index,x/72,y/72));
      model.masks[piece.id]=bitmap;
    }
    const canvas=document.querySelector('#loom-canvas');
    const point=e=>{const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*970/r.width,(e.clientY-r.top)*560/r.height];};
    if(full) {
      canvas.addEventListener('pointerdown',e=>{if(e.button!==0) return;e.preventDefault();if(grab(point(e))) {model.pointer=e.pointerId;canvas.setPointerCapture(e.pointerId);}});
      canvas.addEventListener('pointermove',e=>{if(model.pointer===e.pointerId) {const p=point(e);aim([p[0]-model.offset[0],p[1]-model.offset[1]]);}});
      canvas.addEventListener('pointerup',e=>{if(model.pointer!==e.pointerId) return;const p=point(e);aim([p[0]-model.offset[0],p[1]-model.offset[1]]);model.pointer=null;drop();canvas.releasePointerCapture(e.pointerId);});
      const cancel=e=>{if(model.pointer===e.pointerId) {model.pointer=null;drop(true);}};
      canvas.addEventListener('pointercancel',cancel);canvas.addEventListener('lostpointercapture',cancel);
      keyDown=e=>{if(e.key==='Escape' && model.physics.held) {e.preventDefault();model.pointer=null;drop(true);return;}
        if(!['a','d'].includes(e.key.toLowerCase()) || e.repeat) return;e.preventDefault();model.keys.add(e.key.toLowerCase());turn(Number(model.keys.has('d'))-Number(model.keys.has('a')));};
      keyUp=e=>{if(!['a','d'].includes(e.key.toLowerCase())) return;e.preventDefault();model.keys.delete(e.key.toLowerCase());turn(Number(model.keys.has('d'))-Number(model.keys.has('a')));};
      window.addEventListener('keydown',keyDown);window.addEventListener('keyup',keyUp);
    } else {
      canvas.addEventListener('click',e=>{if(model.physics.held) aim(point(e));else grab(point(e));});
      for(const [id,direction] of [['loom-left',-1],['loom-right',1]]) {
        const button=document.getElementById(id);
        button.addEventListener('pointerdown',e=>{if(e.button!==0) return;e.preventDefault();button.setPointerCapture(e.pointerId);turn(direction);});
        const release=()=>turn(0);
        for(const event of ['pointerup','pointercancel','lostpointercapture']) button.addEventListener(event,release);
      }
      document.getElementById('loom-stitch').addEventListener('click',()=>drop());
      document.getElementById('loom-return').addEventListener('click',()=>drop(true));
    }
    document.getElementById('loom-start').addEventListener('click',start);
    document.getElementById('loom-submit').addEventListener('click',()=>{sync();finish('INCOMPLETE PICTURE');});
    draw();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.motion_only_ghost_jigsaw_v2={rootSelector:'.ghost-loom',render};
})();
