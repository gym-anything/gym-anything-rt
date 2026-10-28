(() => {
  'use strict';
  const ID = 'two_lamp_dyeworks_v3', REVISION = 'flow-spectrum-v3-stock-sampling';
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  const quantize = v => Math.round(clamp(v,0,1)*100)/100;
  const clone = v => JSON.parse(JSON.stringify(v));
  let model = null, frame = 0;

  function colors(density,pigments,spectrum) {
    const reflectance = spectrum.base.map((base,b) => base*Math.exp(-spectrum.strength*
      density.reduce((sum,d,i) => sum+d*pigments[i].absorption[b],0)));
    const out = {};
    for (const [lamp,power] of Object.entries(spectrum.lamps)) {
      const white = spectrum.cie.map(row => row.reduce((sum,c,b) => sum+c*power[b],0));
      const rel = spectrum.cie.map((row,i) => row.reduce((sum,c,b) => sum+c*power[b]*reflectance[b],0)/white[i]);
      const f = v => v > (6/29)**3 ? v**(1/3) : v/(3*(6/29)**2)+4/29;
      const [fx,fy,fz] = rel.map(f), lab = [116*fy-16,500*(fx-fy),200*(fy-fz)];
      const inv = v => v > 6/29 ? v**3 : 3*(6/29)**2*(v-4/29);
      const [x,y,z] = [.95047*inv(fx),inv(fy),1.08883*inv(fz)];
      const linear = [3.2406*x-1.5372*y-.4986*z,-.9689*x+1.8758*y+.0415*z,.0557*x-.204*y+1.057*z];
      const rgb = linear.map((v,i) => {
        v = clamp(v,0,1);
        const encoded = v <= .0031308 ? 12.92*v : 1.055*v**(1/2.4)-.055;
        return Math.round(255*clamp(encoded*spectrum.casts[lamp][i],0,1));
      });
      out[lamp] = {lab,rgb};
    }
    return out;
  }
  function stockStrength(nodes,ms) {
    if (ms <= 0) return nodes[0].strength;
    for (let i=1;i<nodes.length;i++) {
      if (ms <= nodes[i].t_ms) {
        const a=nodes[i-1],b=nodes[i],u=(ms-a.t_ms)/(b.t_ms-a.t_ms);
        return a.strength+(b.strength-a.strength)*u*u*(3-2*u);
      }
    }
    return nodes.at(-1).strength;
  }
  function rail(c,v,i) {return [c.vats.length===2 ? 152+v*560 : 412,282+i*44,302];}

  class Plant {
    constructor(c) {
      this.c=c;this.p=c.physics;this.tick=0;this.start_tick=null;
      this.n=c.pigments.length;this.m=c.vats.length;
      const empty=()=>Array.from({length:this.m},()=>Array(this.n).fill(0));
      this.targets=empty();this.valves=empty();this.density=empty();
      this.pipe=Array.from({length:this.p.pipe_ms/this.p.tick_ms},empty);
      this.bad_mm=Array(this.m).fill(0);this.errors=Array(this.m).fill(0);
      this.produced_mm=0;this.status='preparation';this.failure='';this.samples=[];
      for (let v=0;v<this.m;v++) {
        const current=colors(this.density[v],c.pigments,c.spectrum);
        this.errors[v]=Math.max(...['north','sodium'].map(lamp=>Math.hypot(...current[lamp].lab.map((x,i)=>x-c.vats[v].target[lamp].lab[i]))));
      }
    }
    begin() {
      if (this.start_tick!==null || this.status!=='preparation') return false;
      this.start_tick=this.tick;this.status='running';return true;
    }
    advance(target) {
      const dt=this.p.tick_ms/1000,slew=this.p.valve_speed*dt,blend=1-Math.exp(-this.p.tick_ms/this.p.mixing_ms);
      while (this.tick<target && !['failed','complete'].includes(this.status)) {
        this.tick++;
        for (let v=0;v<this.m;v++) for (let i=0;i<this.n;i++)
          this.valves[v][i]+=clamp(this.targets[v][i]-this.valves[v][i],-slew,slew);
        const gain=1/(1+this.p.coupling*this.valves.reduce((sum,row)=>sum+row.reduce((a,b)=>a+b,0),0));
        const ms=this.start_tick===null?0:(this.tick-this.start_tick)*this.p.tick_ms;
        const strengths=this.c.pigments.map(p=>stockStrength(this.c.stock[p.id],ms));
        this.pipe.push(this.valves.map(row=>row.map((value,i)=>this.p.supply_scale*strengths[i]*value*gain)));
        const delayed=this.pipe.shift();
        for (let v=0;v<this.m;v++) {
          for (let i=0;i<this.n;i++) this.density[v][i]+=(delayed[v][i]-this.density[v][i])*blend;
          const current=colors(this.density[v],this.c.pigments,this.c.spectrum);
          this.errors[v]=Math.max(...['north','sodium'].map(lamp=>Math.hypot(...current[lamp].lab.map((x,i)=>x-this.c.vats[v].target[lamp].lab[i]))));
        }
        if (this.start_tick!==null && ms>this.p.leader_ms) {
          const length=this.p.cloth_speed_mm_s*dt;this.produced_mm+=length;
          for (let v=0;v<this.m;v++) {
            if (this.errors[v]>this.p.tolerance) this.bad_mm[v]+=length;
            if (this.bad_mm[v]>this.p.waste_mm+1e-7) {
              this.status='failed';this.failure=`${this.c.vats[v].name} spoiled too much cloth`;
            }
          }
        }
        if (this.status!=='failed' && this.start_tick!==null && ms>=this.p.leader_ms+this.p.run_ms) this.status='complete';
        if (this.tick%4===0) {
          this.samples.push({tick:this.tick,errors:[...this.errors],density:clone(this.density),produced:this.produced_mm});
          if (this.samples.length>350) this.samples.shift();
        }
      }
    }
    summary() {
      return {tick:this.tick,start_tick:this.start_tick,status:this.status,density:clone(this.density),
        valves:clone(this.valves),targets:clone(this.targets),bad_mm:[...this.bad_mm],produced_mm:this.produced_mm};
    }
  }
  // Read-only development diagnostics are disclosed in every oracle report.
  // There is no task control that freezes, resets, or injects a plant outcome.
  window.TwoLampDyeworksV3 = {Plant,colors,stockStrength,rail};
  function record(kind,extra={}) {model.events.push({sequence:model.events.length+1,kind,tick:model.sim.tick,...extra});}
  function sync() {
    if (!model || model.terminal) return;
    model.sim.advance(Math.max(0,Math.floor((performance.now()-model.epoch)/model.state.physics.tick_ms)));
    if (model.sim.status==='failed') finish();
  }
  function point(e) {
    const r=model.canvas.getBoundingClientRect();
    return [Math.round(clamp((e.clientX-r.left)/r.width*1120,0,1120)*1000)/1000,
            Math.round(clamp((e.clientY-r.top)/r.height*500,0,500)*1000)/1000];
  }
  function pointerDown(e) {
    if (e.button!==0 || model.terminal || model.drag) return;
    sync();if (model.terminal || model.sim.status==='complete') return;
    const p=point(e),s=model.sim;
    // Metered inlet sampling reveals the anonymous lot's spectral response.
    // Sampling does not alter valves or consume production cloth.
    const panel=1080/s.n;
    for (let i=0;i<s.n;i++) {
      const x=28+i*panel;
      if (p[0]>=x && p[0]<=x+panel-72 && p[1]>=3 && p[1]<=23) {
        const pigment=model.state.pigments[i];
        const ms=s.start_tick===null?0:(s.tick-s.start_tick)*s.p.tick_ms;
        const strength=stockStrength(model.state.stock[pigment.id],ms);
        const density=Array(s.n).fill(0);density[i]=model.state.inspection.sample_density*strength;
        const measured=colors(density,model.state.pigments,model.state.spectrum);
        const sample={pigment_id:pigment.id,strength,rgb:{north:measured.north.rgb,sodium:measured.sodium.rgb}};
        model.spotSamples[i]=sample;
        record('stock_sample',{pigment:i,point:p,input_source:'stock_spot_test',sample:clone(sample)});
        model.helpers.setReadout(`LOT ${'ABCD'[i]} spot test: ${pigment.name} · NORTH-LIGHT / SODIUM proof clipped. Lot identity stays visible.`,'idle');
        draw();e.preventDefault();return;
      }
    }
    for (let v=0;v<s.m;v++) for (let i=0;i<s.n;i++) {
      const [x,y,w]=rail(model.state,v,i);
      if (model.interaction==='simplified' && p[0]>=x-16 && p[0]<=x+w+16 && Math.abs(p[1]-y)<=16) {
        record('valve_click',{vat:v,pigment:i,point:p,input_source:'rail_click'});
        s.targets[v][i]=quantize((p[0]-x)/w);draw();e.preventDefault();return;
      }
      if (model.interaction==='full' && Math.hypot(p[0]-x-w*s.targets[v][i],p[1]-y)<=16) {
        model.drag={v,i,id:e.pointerId,offsetX:p[0]-x-w*s.targets[v][i]};model.canvas.setPointerCapture(e.pointerId);
        record('drag_start',{vat:v,pigment:i,point:p,input_source:'valve_drag'});e.preventDefault();return;
      }
    }
  }
  function pointerMove(e) {
    if (!model.drag || e.pointerId!==model.drag.id || model.terminal) return;
    sync();if (model.terminal || model.sim.status==='complete') return;
    const {v,i,offsetX}=model.drag,p=point(e),[x,,w]=rail(model.state,v,i);
    model.sim.targets[v][i]=quantize((p[0]-x-offsetX)/w);
    record('drag_move',{vat:v,pigment:i,point:p,input_source:'valve_drag'});draw();e.preventDefault();
  }
  function pointerEnd(e,cancel=false) {
    if (!model.drag || e.pointerId!==model.drag.id) return;
    sync();const {v,i,offsetX}=model.drag;model.drag=null;
    if (!model.terminal && model.sim.status!=='complete') {
      const p=point(e),[x,,w]=rail(model.state,v,i);
      if (!cancel) model.sim.targets[v][i]=quantize((p[0]-x-offsetX)/w);
      record(cancel?'drag_cancel':'drag_end',{vat:v,pigment:i,point:p,input_source:'valve_drag'});
    }
    if (model.canvas.hasPointerCapture(e.pointerId)) model.canvas.releasePointerCapture(e.pointerId);
    draw();
  }
  function begin() {
    if (model.terminal || model.drag) return;
    sync();if (!model.sim.begin()) return;
    record('begin',{input_source:'start_button'});
    model.helpers.setReadout('Production is running. Follow the incoming dye and keep both lamps matched.','pending');draw();
  }
  function payload() {return {mechanic_id:ID,revision:REVISION,task_id:model.state.task_id,
    challenge_id:model.state.challenge_id,control_condition:model.state.control_condition||null,
    interaction_mode:model.interaction,events:model.events,completed:model.sim.status==='complete',final_state:model.sim.summary()};}
  function verdict(kind,detail) {
    const root=document.querySelector('.dye-v2');root.dataset.verdict=kind;
    root.querySelector('.dye-v2-verdict').innerHTML=`<small>DYER'S CERTIFICATE</small><strong>${kind.toUpperCase()}</strong><span></span>`;
    root.querySelector('.dye-v2-verdict span').textContent=detail;
  }
  async function finish() {
    if (model.terminal || model.submitting) return;
    // Sync before latching. Certification cannot pause an ongoing roll and
    // hide the later defects: an early submission is an irreversible failure.
    model.sim.advance(Math.max(0,Math.floor((performance.now()-model.epoch)/model.state.physics.tick_ms)));
    if (model.sim.status!=='complete' && model.sim.status!=='failed') {
      model.sim.status='failed';model.sim.failure='Rolls certified before production finished';
    }
    model.terminal=true;model.submitting=true;record('submit');
    draw();verdict(model.sim.status==='complete'?'checking':'fail',model.sim.failure||'Checking both cloth rolls');
    model.helpers.setReadout(model.sim.failure?'FAIL · '+model.sim.failure:'VERIFYING ROLLS…',model.sim.failure?'error':'pending');
    const result=payload();model.lastPayload=clone(result);
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(result)});
      const outcome=await response.json();
      model.outcome=outcome;
      if (outcome.passed===true) {
        const s=model.sim,yieldPercent=100*(s.produced_mm*s.m-s.bad_mm.reduce((a,b)=>a+b,0))/(s.produced_mm*s.m);
        verdict('pass',`Both lamps matched · usable yield ${yieldPercent.toFixed(2)}%`);
        model.helpers.setReadout(`PASS · ROLLS CERTIFIED · ${yieldPercent.toFixed(2)}% USABLE YIELD`,'passed');
      }
      else {verdict('fail',model.sim.failure||'Cloth replay rejected');model.helpers.setReadout('FAIL · ATTEMPT ENDED','error');}
    } catch(error) {
      verdict('error','Verifier unavailable — attempt retained');model.helpers.setReadout('VERIFIER ERROR · '+error.message,'error');
    }
  }
  function text(ctx,value,x,y,color='#d8d3c1',size=12) {
    ctx.fillStyle=color;ctx.font=`${size}px ui-monospace, monospace`;ctx.fillText(value,x,y);
  }
  const rgb = value => `rgb(${value.join(',')})`;
  function cloth(ctx,color,x,y,w,h) {
    ctx.fillStyle=color;ctx.fillRect(x,y,w,h);
    ctx.strokeStyle='#ffffff20';ctx.lineWidth=1;
    for (let n=3;n<w;n+=6) {ctx.beginPath();ctx.moveTo(x+n,y);ctx.lineTo(x+n,y+h);ctx.stroke();}
    ctx.strokeStyle='#00000018';
    for (let n=3;n<h;n+=6) {ctx.beginPath();ctx.moveTo(x,y+n);ctx.lineTo(x+w,y+n);ctx.stroke();}
  }
  function fiberStrip(ctx,reflectance,x,y) {
    const width=104/9;
    reflectance.forEach((value,band)=>{
      const brightness=Math.round(255*clamp(value,0,1));
      ctx.fillStyle=`rgb(${brightness},${brightness},${brightness})`;
      ctx.fillRect(x+band*width,y,width-1,9);
    });
  }
  function drawStock(ctx) {
    const s=model.sim,c=model.state,ms=s.start_tick===null?0:(s.tick-s.start_tick)*c.physics.tick_ms;
    const width=1080/c.pigments.length;
    c.pigments.forEach((p,i)=>{
      const x=20+i*width,nodes=c.stock[p.id],current=stockStrength(nodes,ms);
      const sample=model.spotSamples[i],ink=sample?p.color:'#9eabb5';
      ctx.fillStyle='#20323d';ctx.fillRect(x+8,3,width-72,20);
      ctx.strokeStyle=ink;ctx.lineWidth=1;ctx.strokeRect(x+8,3,width-72,20);
      ctx.fillStyle=sample?'#b8dfb9':'#d7bc83';ctx.fillRect(x+11,9,7,7);
      text(ctx,sample?p.name:`LOT ${'ABCD'[i]} · SPOT TEST`,x+23,18,ink,11);
      if(sample) {
        ctx.fillStyle=rgb(sample.rgb.north);ctx.fillRect(x+width-112,5,18,16);
        ctx.fillStyle=rgb(sample.rgb.sodium);ctx.fillRect(x+width-90,5,18,16);
      }
      text(ctx,`${Math.round(current*100)}%`,x+width-54,19,ink,12);
      ctx.fillStyle='#090f19';ctx.fillRect(x+8,25,width-18,48);
      ctx.strokeStyle='#ffffff1c';ctx.strokeRect(x+8,25,width-18,48);
      ctx.strokeStyle=ink;ctx.lineWidth=2;ctx.beginPath();
      for (let j=0;j<=80;j++) {
        const dt=-800+(800+c.physics.preview_ms)*j/80,t=s.start_tick===null?0:Math.max(0,ms+dt);
        const px=x+8+(width-18)*j/80,py=71-(stockStrength(nodes,t)-.5)/1.1*43;
        if (!j) ctx.moveTo(px,py);else ctx.lineTo(px,py);
      }
      ctx.stroke();const nowX=x+8+(width-18)*800/(800+c.physics.preview_ms);
      ctx.strokeStyle='#f9e6b0';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(nowX,25);ctx.lineTo(nowX,73);ctx.stroke();
      text(ctx,'PAST',x+8,87,'#8898aa',9);text(ctx,'NOW',nowX-9,87,'#ead0a0',9);
      text(ctx,`INCOMING ${c.physics.preview_ms/1000}s →`,x+width-104,87,'#8898aa',9);
    });
  }
  function drawVat(ctx,v) {
    const s=model.sim,c=model.state,left=s.m===2?20+v*560:280,target=c.vats[v].target;
    ctx.fillStyle='#18232d';ctx.fillRect(left,106,520,351);ctx.strokeStyle='#71808b';ctx.lineWidth=1;ctx.strokeRect(left,106,520,351);
    text(ctx,c.vats[v].name,left+16,130,'#edce96',17);
    text(ctx,s.errors[v]<=c.physics.tolerance?'● BOTH LIGHTS MATCH':'○ ADJUST THE MIX',left+223,128,s.errors[v]<=c.physics.tolerance?'#b8dfb9':'#e9b48b',12);
    const current=colors(s.density[v],c.pigments,c.spectrum);
    ['north','sodium'].forEach((lamp,j)=>{
      const x=left+16+j*250;
      text(ctx,lamp==='north'?'NORTH-LIGHT':'SODIUM',x,151,lamp==='north'?'#afdbef':'#eec087',10);
      cloth(ctx,rgb(current[lamp].rgb),x+110,159,104,58);
      // Nine visible reflectance bands distinguish mixtures whose rounded
      // display colours alone can be ambiguous. Both input modes see them.
      const wetSpectrum=c.spectrum.base.map((base,band)=>base*Math.exp(-c.spectrum.strength*
        s.density[v].reduce((sum,d,i)=>sum+d*c.pigments[i].absorption[band],0)));
      cloth(ctx,rgb(target[lamp].rgb),x,159,104,58);
      if(c.vats[v].fiber_spectrum) fiberStrip(ctx,c.vats[v].fiber_spectrum,x,220);
      fiberStrip(ctx,wetSpectrum,x+110,220);
      const error=Math.hypot(...current[lamp].lab.map((a,i)=>a-target[lamp].lab[i]));
      ctx.strokeStyle=error<=c.physics.tolerance?'#b8dfb9':'#e9b48b';ctx.lineWidth=3;ctx.strokeRect(x+110,159,104,70);
      text(ctx,'PINNED',x+26,244,'#c0c6c5',10);text(ctx,'WET CLOTH',x+131,244,'#c0c6c5',10);
    });
    text(ctx,'INLET → BATH',left+16,261,'#8898aa',9);
    for(let j=0;j<s.pipe.length;j++) {
      // The FIFO's newest liquid enters at the left and its oldest liquid
      // reaches the bath at the right, matching the visible flow arrow.
      const piped=colors(s.pipe[s.pipe.length-1-j][v],c.pigments,c.spectrum);
      ctx.fillStyle=rgb(piped.north.rgb);ctx.fillRect(left+104+j*(295/s.pipe.length),252,295/s.pipe.length+1,10);
    }
    text(ctx,`${c.physics.pipe_ms/1000}s →`,left+416,261,'#a6b7ba',10);
    c.pigments.forEach((p,i)=>{
      const ink=model.spotSamples[i]?p.color:'#9eabb5';
      const [x,y,w]=rail(c,v,i);text(ctx,model.spotSamples[i]?p.name:`LOT ${'ABCD'[i]}`,left+16,y+4,ink,12);
      if(model.interaction==='simplified') {
        // This rectangle shows the complete clickable surface, including
        // the endpoint allowance used by both pointer dispatch and replay.
        ctx.fillStyle='#243641';ctx.fillRect(x-16,y-16,w+32,32);
        ctx.strokeStyle='#50616a';ctx.lineWidth=1;ctx.strokeRect(x-16,y-16,w+32,32);
      }
      ctx.strokeStyle='#7d898d';ctx.lineWidth=4;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+w,y);ctx.stroke();
      ctx.strokeStyle='#7d898d';ctx.lineWidth=1;
      for(let j=0;j<=10;j++){ctx.beginPath();ctx.moveTo(x+w*j/10,y-7);ctx.lineTo(x+w*j/10,y+7);ctx.stroke();}
      // The full hitbox is precisely the visible 16px circular handle.
      const handle=x+w*s.targets[v][i];
      ctx.fillStyle='#263c47';ctx.strokeStyle=ink;ctx.lineWidth=2;
      ctx.beginPath();ctx.arc(handle,y,16,0,2*Math.PI);ctx.fill();ctx.stroke();
      ctx.fillStyle='#edf1e0';ctx.fillRect(handle-4,y-6,8,12);
      ctx.fillStyle=ink;ctx.beginPath();ctx.moveTo(x+w*s.valves[v][i],y+18);ctx.lineTo(x+w*s.valves[v][i]-5,y+25);ctx.lineTo(x+w*s.valves[v][i]+5,y+25);ctx.fill();
      text(ctx,`${Math.round(s.targets[v][i]*100)}%`,left+457,y+4,ink,12);
    });
    if(s.n<4) {
      const y=282+s.n*44;
      text(ctx,'ADJUST VALVES · WATCH THE CLOTH',left+25,y+6,'#94a9ad',12);
      text(ctx,'Triangle = valve opening; handle = setting',left+25,y+29,'#94a9ad',11);
    }
    const y=474;
    text(ctx,`SPOILED ${s.bad_mm[v].toFixed(1)} / ${c.physics.waste_mm} mm`,left+12,y,'#e2b498',11);
    ctx.fillStyle='#09121a';ctx.fillRect(left+251,y-11,248,14);
    ctx.fillStyle='#d48b69';ctx.fillRect(left+251,y-11,248*clamp(s.bad_mm[v]/c.physics.waste_mm,0,1),14);
    ctx.strokeStyle='#a6b7ba';ctx.strokeRect(left+251,y-11,248,14);
  }
  function draw() {
    if (!model?.canvas) return;
    const ctx=model.canvas.getContext('2d'),s=model.sim,c=model.state;
    ctx.fillStyle='#111c26';ctx.fillRect(0,0,1120,500);
    drawStock(ctx);for(let v=0;v<s.m;v++) drawVat(ctx,v);
    const start=document.getElementById('dye-v2-start'),seal=document.getElementById('dye-v2-seal');
    start.disabled=s.start_tick!==null||model.terminal;
    seal.disabled=model.terminal;
    const activeMs=s.start_tick===null?0:(s.tick-s.start_tick)*c.physics.tick_ms;
    document.getElementById('dye-v2-progress').textContent=c.episode_history_error?'VERIFIER ERROR':s.status==='failed'?'EPISODE ENDED':s.start_tick===null?'PREPARATION':s.status==='complete'?'ROLLS COMPLETE':
      activeMs<c.physics.leader_ms?`LEADER CLOTH · ${((c.physics.leader_ms-activeMs)/1000).toFixed(1)}s`:`CLOTH ${s.produced_mm.toFixed(0)} / ${c.physics.run_ms*c.physics.cloth_speed_mm_s/1000} mm`;
    document.getElementById('dye-v2-fill').style.width=`${100*clamp(s.produced_mm/(c.physics.run_ms*c.physics.cloth_speed_mm_s/1000),0,1)}%`;
    document.querySelector('.dye-v2').dataset.plantStatus=s.status;
  }
  function animate(){sync();draw();frame=requestAnimationFrame(animate);}
  function render(state,helpers) {
    cancelAnimationFrame(frame);document.body.dataset.mechanic='two-lamp-dyeworks-v2';
    const interaction=state.control_condition?.interaction||'full';
    model={state,helpers,interaction,sim:new Plant(state),spotSamples:state.pigments.map(()=>null),events:[],drag:null,epoch:performance.now(),terminal:false,submitting:false};
    window.twoLampDyeworksV3Model=model;
    helpers.app.innerHTML=`<section class="dye-v2" data-interaction="${interaction}" data-verdict="">
      <header><div class="dye-v2-emblem">◒<span>DYER'S GUILD</span></div><div><p>CONTINUOUS COLOUR / ONE ATTEMPT</p><h1>Two-Lamp Dyeworks V3</h1></div>
      <div class="dye-v2-lot"><b id="dye-v2-progress">PREPARATION</b><div><i id="dye-v2-fill"></i></div></div></header>
      <p class="dye-v2-rules">Spot-test the anonymous dye lots to identify their two-light response. The test clips stay visible. Traces preview supply; fibre strips show the mix, and triangles show valve lag. Prepare freely, then start. Stay within spoil limits.</p>
      <canvas id="dye-v2-canvas" width="1120" height="500" aria-label="two lamp dye workbench with anonymous inlet lots, spot tests, stock strength plots and graduated valves"></canvas>
      <footer><div><b>${interaction==='full'?'DRAG THE ROUND VALVE HANDLES':'CLICK A VALVE RAIL TO SET ITS OPENING'}</b><div class="readout">Click a LOT · SPOT TEST inlet to sample its dye under both lamps. Prepare freely before START ROLLS.</div></div><button id="dye-v2-start">START ROLLS</button><button id="dye-v2-seal">CERTIFY ROLLS</button></footer>
      <div class="dye-v2-verdict"></div></section>`;
    model.canvas=document.getElementById('dye-v2-canvas');
    model.canvas.addEventListener('pointerdown',pointerDown);model.canvas.addEventListener('pointermove',pointerMove);
    model.canvas.addEventListener('pointerup',e=>pointerEnd(e));model.canvas.addEventListener('pointercancel',e=>pointerEnd(e,true));
    model.canvas.addEventListener('lostpointercapture',e=>{if(model.drag?.id===e.pointerId)pointerEnd(e,true);});
    document.getElementById('dye-v2-start').addEventListener('click',begin);
    document.getElementById('dye-v2-seal').addEventListener('click',finish);
    if (state.episode_history_error) {
      model.terminal=true;
      verdict('error','Retained failure history is unavailable.');
      helpers.setReadout('VERIFIER ERROR · RETAINED HISTORY UNAVAILABLE','error');
    } else if (state.episode_failed) {
      model.terminal=true;model.sim.status='failed';
      model.sim.failure='First committed failure retained; this episode has ended.';
      verdict('fail',model.sim.failure);
      helpers.setReadout('FAIL · EPISODE ENDED · FIRST FAILURE RETAINED','error');
    }
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.dye-v2',render};
})();
