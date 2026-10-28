(() => {
  'use strict';
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const dist = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1]);
  const cross = (a,b,c) => (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
  const clean = s => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index+1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0)/4294967295*2-1;
  }
  function motion(seed, ms, span) {
    const u = Math.max(0,ms)/span, i = Math.floor(u), f = u-i;
    return noise(seed,i)+(noise(seed,i+1)-noise(seed,i))*f*f*(3-2*f);
  }
  function integral(seed, ms, span) {
    const u = Math.max(0,ms)/span, i = Math.floor(u), f = u-i;
    let whole = 0;
    for (let j=0;j<i;j++) whole += (noise(seed,j)+noise(seed,j+1))/2;
    const a=noise(seed,i), b=noise(seed,i+1);
    return span*(whole+a*f+(b-a)*(f**3-f**4/2));
  }
  function lampAt(s, b, ms) {
    return [b.lamp_x+120*motion(b.lamp_seed,ms,s.parameters.lamp_span_ms),
            b.lamp_y+8*motion(b.lamp_seed+7919,ms,s.parameters.lamp_span_ms)];
  }
  function objectAt(s, o, ms) {
    const a=o.phase+s.parameters.angular_speed*(ms+.4*integral(o.seed,ms,4700))/1000;
    return [o.x+35*Math.cos(a),o.y+24*Math.sin(a)];
  }
  function hull(points) {
    points=[...points].sort((a,b)=>a[0]-b[0] || a[1]-b[1]);
    const lower=[], upper=[];
    for (const p of points) { while(lower.length>=2 && cross(lower.at(-2),lower.at(-1),p)<=0) lower.pop(); lower.push(p); }
    for (const p of [...points].reverse()) { while(upper.length>=2 && cross(upper.at(-2),upper.at(-1),p)<=0) upper.pop(); upper.push(p); }
    return [...lower.slice(0,-1),...upper.slice(0,-1)];
  }
  function lampShiftAt(history,ms) {
    for(let i=(history||[]).length-1;i>=0;i--) if(history[i][0]<=ms) return history[i][1];
    return 0;
  }
  function polygons(s,b,ms,lampShifts=[]) {
    return b.objects.map((o,index)=>{
      const position=objectAt(s,o,ms), lamp=lampAt(s,b,ms);
      const t=index===b.forged_index?ms-s.parameters.lag_ms:ms;
      lamp[0]+=lampShiftAt(lampShifts,t);
      const scale=b.lamp_z/(b.lamp_z-o.height), base=[];
      for(let i=0;i<o.sides;i++) base.push([position[0]+o.radius*Math.cos(o.angle+i*2*Math.PI/o.sides),position[1]+o.radius*Math.sin(o.angle+i*2*Math.PI/o.sides)]);
      const top=base.map(p=>p.map((v,k)=>lamp[k]+scale*(v-lamp[k])));
      return {id:o.id,base,top,shadow:hull([...base,...top]),center:position.map((v,k)=>lamp[k]+scale*(v-lamp[k]))};
    });
  }
  function diskInside(point, polygon, radius) {
    return polygon.every((p,i)=>cross(p,polygon[(i+1)%polygon.length],point)>=radius*dist(p,polygon[(i+1)%polygon.length])-1e-7);
  }
  function diskOverlap(point, polygon, radius) {
    if(diskInside(point,polygon,0)) return true;
    return polygon.some((a,i)=>{
      const b=polygon[(i+1)%polygon.length], dx=b[0]-a[0],dy=b[1]-a[1];
      const u=clamp(((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy),0,1);
      return dist(point,[a[0]+u*dx,a[1]+u*dy])<radius-1e-7;
    });
  }
  function sampleHit(s,b,ms,point,lampShifts=[]) {
    const radius=s.physics.aperture_radius, scene=polygons(s,b,ms,lampShifts);
    for(let i=scene.length-1;i>=0;i--) {
      const e=scene[i];
      if(diskInside(point,e.top,radius)) {
        if(scene.slice(i+1).some(front=>diskOverlap(point,front.shadow,radius))) return null;
        if(scene.some(item=>diskOverlap(point,item.base,radius))) return null;
        return e.id;
      }
    }
    return null;
  }
  class Simulation {
    constructor(state) {
      this.state=state; this.ms=0; this.active=false; this.terminal='';
      this.lampShifts=state.benches.map(()=>[]);
      this.cameras=state.benches.map(()=>({position:[480,194],velocity:[0,0],target:[480,194],charge:0,sample:null,hit:null}));
    }
    advance(end) {
      const spec=this.state.physics;
      while(this.active && !this.terminal && this.ms+10<=end) {
        this.ms+=10;
        this.cameras.forEach((cam,i)=>{
          for(let k=0;k<2;k++) {
            const a=clamp((cam.target[k]-cam.position[k])*spec.spring-cam.velocity[k]*spec.damping,-spec.acceleration_limit,spec.acceleration_limit);
            cam.velocity[k]+=a*.01;
          }
          const speed=Math.hypot(...cam.velocity);
          if(speed>spec.speed_limit) cam.velocity=cam.velocity.map(v=>v*spec.speed_limit/speed);
          for(let k=0;k<2;k++) {
            const limit=k===0?960:220;
            cam.position[k]=clamp(cam.position[k]+cam.velocity[k]*.01,7,limit-7);
            if(cam.position[k]===7 || cam.position[k]===limit-7) cam.velocity[k]=0;
          }
          const bench=this.state.benches[i], hit=sampleHit(this.state,bench,this.ms,cam.position,this.lampShifts[i]);
          cam.hit=hit;
          if(hit) {
            if(cam.sample!==hit) cam.charge=0;
            cam.sample=hit; cam.charge=Math.min(spec.exposure_ms,cam.charge+10);
          } else cam.charge=Math.max(0,cam.charge-10*spec.fade_rate);
          if(cam.charge>=spec.exposure_ms && cam.sample!==bench.objects[bench.forged_index].id) this.terminal='honest shadow developed';
        });
        if(!this.terminal && this.cameras.every(c=>c.charge>=spec.exposure_ms)) this.terminal='pass';
        if(!this.terminal && this.ms>=spec.time_limit_ms) this.terminal='exposure time exhausted';
      }
    }
    snapshot() {
      return {t_ms:this.ms,active:this.active,terminal:this.terminal,lamp_shifts:this.lampShifts.map(h=>h.map(p=>[...p])),cameras:this.cameras.map(c=>({
        position:c.position.map(v=>Number(v.toFixed(4))),velocity:c.velocity.map(v=>Number(v.toFixed(4))),
        target:[...c.target],charge:c.charge,sample:c.sample}))};
    }
  }
  window.ShadowCrimeLabV3NonRealtime={Simulation,polygons,lampAt,lampShiftAt,objectAt,sampleHit};
  let model=null, raf=0;
  const offset = i => model.state.benches.length===1 ? 110 : 220*i;
  function actionStep() {
    if(!model || model.submitted || !model.sim.active) return true;
    const step=model.state.physics.action_step_ms;
    model.sim.advance(model.sim.ms+step);
    if(model.sim.terminal) { finish(); return false; }
    return true;
  }
  function record(kind,details={}) { model.events.push({seq:model.events.length+1,t_ms:model.sim.ms,kind,...details}); }
  function point(event,bench) {
    const r=document.querySelector('#scv2-canvas').getBoundingClientRect();
    return [Number(clamp((event.clientX-r.left)*960/r.width,0,960).toFixed(4)),
            Number(clamp((event.clientY-r.top)*440/r.height-offset(bench),0,220).toFixed(4))];
  }
  function benchAt(event) {
    const r=document.querySelector('#scv2-canvas').getBoundingClientRect(), y=(event.clientY-r.top)*440/r.height;
    if(model.state.benches.length===1) return y>=110 && y<=330 ? 0 : -1;
    return y>=0 && y<=440 ? Math.min(1,Math.floor(y/220)) : -1;
  }
  function shiftLamp(bench,p,kind,shiftOverride=undefined) {
    const base=lampAt(model.state,model.state.benches[bench],model.sim.ms);
    const shift=shiftOverride===undefined
      ? Number(clamp(p[0]-base[0],-model.state.inspection.rail_half_span,model.state.inspection.rail_half_span).toFixed(4))
      : shiftOverride;
    const history=model.sim.lampShifts[bench];
    const previous=lampShiftAt(history,model.sim.ms),records=model.probes[bench];
    let active=model.mode==='full'?model.drag.probe:undefined;
    if(active===undefined && Math.abs(shift-previous)>1e-4) {
      active=records.length;
      records.push({start:model.sim.ms,end:model.sim.ms,baseline:previous});
      if(model.mode==='full') model.drag.probe=active;
      model.probeSelection[bench]=active;
      const select=document.querySelector(`#scv3-record-${bench}`);
      if(active===0) select.replaceChildren();
      select.add(new Option(`LAMP TEST ${active+1}`,String(active)));
      select.disabled=false;select.value=String(active);
    }
    if(active!==undefined) records[active].end=model.sim.ms;
    history.push([model.sim.ms,shift]);
    record(kind,{surface:model.mode==='full'?'lamp_drag':'lamp_click',bench,point:p});
  }
  function down(event) {
    if(event.button!==0 || !model || model.submitted || model.sim.terminal) return;
    const bench=benchAt(event); if(bench<0) return;
    const p=point(event,bench), cam=model.sim.cameras[bench];
    const base=lampAt(model.state,model.state.benches[bench],model.sim.ms),spec=model.state.inspection;
    const lamp=[base[0]+lampShiftAt(model.sim.lampShifts[bench],model.sim.ms),base[1]];
    if(model.sim.active && model.mode==='simplified' && p[1]<=spec.rail_height && Math.abs(p[0]-base[0])<=spec.rail_half_span) {
      const shift=Number(clamp(p[0]-base[0],-spec.rail_half_span,spec.rail_half_span).toFixed(4));
      if(!actionStep()) return;
      shiftLamp(bench,p,'lamp_shift',shift);
    } else if(model.sim.active && model.mode==='full' && dist(p,lamp)<=spec.lamp_grab_radius) {
      if(!actionStep()) return;
      model.drag={bench,id:event.pointerId,lamp:true};event.currentTarget.setPointerCapture(event.pointerId);
      record('lamp_grab',{surface:'lamp_drag',bench,point:p});
    } else if(model.mode==='simplified') {
      if(!actionStep()) return;
      cam.target=p; record('target',{surface:'camera_click',bench,point:p});
    } else if(dist(p,cam.position)<=model.state.physics.grab_radius) {
      if(!actionStep()) return;
      model.drag={bench,id:event.pointerId}; event.currentTarget.setPointerCapture(event.pointerId);
      record('grab',{surface:'camera_drag',bench,point:p});
    }
    event.preventDefault(); draw();
  }
  function move(event) {
    if(!model?.drag || model.submitted || model.sim.terminal) return;
    const bench=model.drag.bench,p=point(event,bench);
    if(model.drag.lamp) {
      const base=lampAt(model.state,model.state.benches[bench],model.sim.ms);
      const shift=Number(clamp(p[0]-base[0],-model.state.inspection.rail_half_span,model.state.inspection.rail_half_span).toFixed(4));
      if(!actionStep()) return;
      shiftLamp(bench,p,'lamp_aim',shift);
    } else {
      if(!actionStep()) return;
      model.sim.cameras[bench].target=p;record('aim',{surface:'camera_drag',bench,point:p});
    }
    event.preventDefault(); draw();
  }
  function up(event) {
    if(!model?.drag || model.submitted || model.sim.terminal) return;
    const bench=model.drag.bench,p=point(event,bench);
    if(model.drag.lamp) {
      const base=lampAt(model.state,model.state.benches[bench],model.sim.ms);
      const shift=Number(clamp(p[0]-base[0],-model.state.inspection.rail_half_span,model.state.inspection.rail_half_span).toFixed(4));
      if(!actionStep()) return;
      shiftLamp(bench,p,'lamp_release',shift);
    } else {
      if(!actionStep()) return;
      model.sim.cameras[bench].target=p;record('release',{surface:'camera_drag',bench,point:p});
    }
    model.drag=null; event.currentTarget.releasePointerCapture(event.pointerId); draw();
  }
  function cancel(event) {
    if(!model?.drag || model.submitted || model.sim.terminal) return;
    const bench=model.drag.bench;
    const p=point(event,bench);
    if(model.drag.lamp) {
      const base=lampAt(model.state,model.state.benches[bench],model.sim.ms);
      const shift=Number(clamp(p[0]-base[0],-model.state.inspection.rail_half_span,model.state.inspection.rail_half_span).toFixed(4));
      if(!actionStep()) return;
      shiftLamp(bench,p,'lamp_cancel',shift);
    } else {
      if(!actionStep()) return;
      record('cancel',{surface:'camera_drag',bench,point:p});
    }
    model.drag=null;
    draw();
  }
  function path(c,p) { c.beginPath(); c.moveTo(...p[0]); p.slice(1).forEach(v=>c.lineTo(...v)); c.closePath(); }
  function drawProbe(bench,index) {
    const c=document.querySelector(`#scv3-probe-${index}`).getContext('2d'),s=model.state;
    const selection=model.probeSelection[index],probe=model.probes[index][selection];
    const history=model.sim.lampShifts[index],start=probe?.start;
    const end=probe?probe.end+s.parameters.lag_ms+600:0;
    const progress=model.sim.ms>=end?'complete':Math.floor(model.sim.ms/50);
    const stamp=probe?`${selection}:${end}:${history.length}:${progress}`:'empty';
    if(model.probeStamps[index]===stamp) return;
    model.probeStamps[index]=stamp;
    c.fillStyle='#eee7d3';c.fillRect(0,0,220,88);c.font='10px ui-monospace,monospace';c.textAlign='left';
    c.fillStyle='#534b3c';
    if(!probe) { c.fillText('NO LAMP TEST RECORDED',8,28);c.fillText('Move the lamp on its rail.',8,46);return; }
    const begin=Math.max(0,start-200);
    const range=Math.max(60,...history.filter(([t])=>t>=start && t<=end).map(([,shift])=>Math.abs(shift-probe.baseline)));
    // Every test remains selectable, including inconclusive calibration.
    // The solid line is the
    // measured shadow displacement after subtracting the moving specimen and
    // autonomous light projection, converted to equivalent lamp displacement.
    // No specimen is labelled honest/forged; both modes get the same traces.
    const rows=bench.objects.length,step=68/rows;
    bench.objects.forEach((o,j)=>{
      const y=11+j*step;
      c.fillStyle='#534b3c';c.fillText(o.id,3,y+3);
      for(const measured of [false,true]) {
        c.beginPath();
        let first=true;
        for(let t=begin;t<=Math.min(end,model.sim.ms);t+=20) {
          let value=lampShiftAt(history,t);
          if(measured) {
            const center=polygons(s,bench,t,history)[j].center[0],p=objectAt(s,o,t)[0],lamp=lampAt(s,bench,t)[0];
            const scale=bench.lamp_z/(bench.lamp_z-o.height);
            value=(center-(lamp+scale*(p-lamp)))/(1-scale);
          }
          const x=35+177*(t-begin)/(end-begin),v=y-(value-probe.baseline)/range*step*.34;
          if(first) { c.moveTo(x,v);first=false; } else c.lineTo(x,v);
        }
        c.strokeStyle=measured?'#a13e24':'#817966';c.lineWidth=measured?2:1;c.setLineDash(measured?[]:[3,3]);c.stroke();c.setLineDash([]);
      }
    });
    c.fillStyle='#534b3c';c.fillText('dashed: lamp / red: shadow',3,84);
  }
  function draw() {
    if(!model) return;
    const canvas=document.querySelector('#scv2-canvas'),c=canvas.getContext('2d'),s=model.state;
    c.fillStyle='#293337'; c.fillRect(0,0,960,440);
    c.font='14px ui-monospace,monospace'; c.textAlign='left'; c.fillStyle='#c7c8bf';
    if(s.benches.length===1) { c.fillText('SINGLE OPTICAL TABLE / LIVE RESPONSE',28,58); c.fillText('LIGHT → OBJECT → SHADOW',28,396); }
    s.benches.forEach((b,i)=>{
      c.save(); c.translate(0,offset(i));
      c.fillStyle='#ded6bd'; c.fillRect(0,0,960,220);
      c.strokeStyle='#aaa69344'; c.lineWidth=1;
      for(let x=0;x<960;x+=40) { c.beginPath();c.moveTo(x,0);c.lineTo(x,220);c.stroke(); }
      for(let y=0;y<220;y+=40) { c.beginPath();c.moveTo(0,y);c.lineTo(960,y);c.stroke(); }
      const history=model.sim.lampShifts[i],scene=polygons(s,b,model.sim.ms,history);
      scene.forEach((e,j)=>{
        path(c,e.shadow);c.fillStyle='#243034';c.fill();
        path(c,e.top); c.strokeStyle='#b8bca6';c.setLineDash([4,4]);c.lineWidth=1.5;c.stroke();c.setLineDash([]);
        c.fillStyle='#dadac7';c.font='12px ui-monospace,monospace';c.textAlign='center';
        c.fillText(e.id,...e.center);
      });
      // Only the recent 800 ms of measured end-cap motion is left on the film.
      b.objects.forEach((o,j)=>{
        c.beginPath();
        for(let back=800;back>=0;back-=100) {
          const e=polygons(s,b,Math.max(0,model.sim.ms-back),history)[j];
          if(back===800) c.moveTo(...e.center);else c.lineTo(...e.center);
        }
        c.strokeStyle='#746d5955'; c.lineWidth=1.4;c.stroke();
      });
      scene.forEach((e,j)=>{
        const o=b.objects[j]; path(c,e.base); c.fillStyle=o.color;c.fill();c.strokeStyle='#fbf2d4';c.lineWidth=2;c.stroke();
        const p=objectAt(s,o,model.sim.ms);c.fillStyle='#eee8d3';c.font='11px ui-monospace,monospace';c.textAlign='center';c.fillText(e.id,p[0],p[1]+4);
        c.fillStyle='#473e35';c.fillText(`h${o.height}`,p[0],p[1]-o.radius-6);
      });
      const l=lampAt(s,b,model.sim.ms),span=s.inspection.rail_half_span;
      c.strokeStyle='#8b7139';c.lineWidth=3;c.beginPath();c.moveTo(l[0]-span,l[1]);c.lineTo(l[0]+span,l[1]);c.stroke();
      c.lineWidth=1;c.strokeRect(l[0]-span,1,span*2,34);
      l[0]+=lampShiftAt(history,model.sim.ms);
      c.beginPath();c.arc(...l,9,0,Math.PI*2);c.fillStyle='#ffe192';c.fill();c.strokeStyle='#8b7139';c.lineWidth=3;c.stroke();
      c.fillStyle='#645941';c.font='11px ui-monospace,monospace';c.fillText('TEST RAIL · LAMP z300',l[0],l[1]+23);
      const cam=model.sim.cameras[i],col=i===0?'#ec754e':'#447dd1';
      c.strokeStyle=col;c.lineWidth=1;c.setLineDash([3,5]);c.beginPath();c.moveTo(...cam.position);c.lineTo(...cam.target);c.stroke();c.setLineDash([]);
      c.beginPath();c.arc(...cam.target,3,0,Math.PI*2);c.stroke();
      c.beginPath();c.arc(...cam.position,25,0,Math.PI*2);c.lineWidth=3;c.stroke();
      c.beginPath();c.arc(...cam.position,s.physics.aperture_radius,0,Math.PI*2);c.lineWidth=2;c.stroke();
      if(cam.hit) { c.fillStyle=col+'55';c.fill(); }
      c.beginPath();c.moveTo(cam.position[0]-32,cam.position[1]);c.lineTo(cam.position[0]-19,cam.position[1]);c.moveTo(cam.position[0]+19,cam.position[1]);c.lineTo(cam.position[0]+32,cam.position[1]);c.stroke();
      c.font='12px ui-monospace,monospace';c.fillStyle=col;c.textAlign='left';c.fillText(`CAMERA ${i+1}`,22,203);
      c.restore();
      const meter=document.querySelector(`#scv2-meter-${i}`);
      meter.querySelector('i').style.width=`${cam.charge/s.physics.exposure_ms*100}%`;
      meter.querySelector('b').textContent=`${(cam.charge/1000).toFixed(1)} / 6.0 s`;
      meter.querySelector('small').textContent=cam.hit?`EXPOSING ${cam.hit}`:cam.charge?'CONTACT LOST · FADING':'NO CONTACT';
      drawProbe(b,i);
    });
    document.querySelector('#scv2-time').textContent=`${(model.sim.ms/1000).toFixed(1)} s / 120`;
  }
  function start() {
    if(model.sim.active || model.submitted) return;
    record('start',{surface:'start_button'}); model.sim.active=true;
    document.querySelector('#scv2-start').disabled=true;model.helpers.setReadout('LIVE · TRACK THE LATE SHADOW END CAPS','idle');
  }
  async function finish(file=false) {
    if(!model || model.submitted) return;
    if(file) { if(model.submitted) return; record('file',{surface:'file_button'});model.sim.terminal='incomplete filing'; }
    const current=model;current.submitted=true;
    const passing=current.sim.terminal==='pass';
    const payload={mechanic_id:current.state.mechanic_id,task_id:current.state.task_id,challenge_id:current.state.challenge_id,
      revision:current.state.revision,interaction_mode:current.mode,events:current.events,
      completed:passing,final_t_ms:current.sim.ms,final_state:current.sim.snapshot()};
    document.querySelector('#scv2-file').disabled=true;
    document.querySelector('#scv2-start').disabled=true;
    const verdict=document.querySelector('.scv2-verdict');
    verdict.dataset.visible='true';verdict.innerHTML=`<b>${passing?'DEVELOPING':'FAIL'}</b><span>${passing?'EXPOSURES COMPLETE':clean(current.sim.terminal.toUpperCase())}</span>`;
    try {
      const response=await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const result=await response.json();
      const pass=result.passed===true;
      verdict.dataset.pass=String(pass); verdict.innerHTML=`<b>${pass?'PASS':'FAIL'}</b><span>${pass?'IMPOSSIBLE RESPONSES PRESERVED':clean(current.sim.terminal==='pass'?'REPLAY REJECTED':current.sim.terminal.toUpperCase())}</span>`;
      current.helpers.setReadout(pass?'PASS · FORENSIC FILM VERIFIED':'FAIL · EPISODE ENDED',pass?'passed':'error');
      current.outcome=result;
    } catch(error) { verdict.innerHTML='<b>ERROR</b><span>EVIDENCE SERVICE UNAVAILABLE</span>';current.helpers.setReadout('VERIFICATION ERROR','error');current.error=String(error); }
  }
  function animate() { if(model) draw(); raf=requestAnimationFrame(animate); }
  async function render(state,helpers) {
    cancelAnimationFrame(raf);document.body.dataset.mechanic='shadow-crime-lab-v3-nonrealtime';
    model={state,helpers,sim:new Simulation(state),mode:state.control_condition.interaction,
      events:[],drag:null,probes:state.benches.map(()=>[]),probeSelection:state.benches.map(()=>-1),probeStamps:state.benches.map(()=>null),submitted:false};
    window.shadowCrimeLabV3NonRealtimeModel=model;
    helpers.app.innerHTML=`<section class="scv2" data-interaction="${model.mode}">
      <header><div><p>PHOTOMETRIC EVIDENCE UNIT / MOVING LIGHT DIVISION</p><h1>Shadow Crime Lab V3</h1></div><span>CASE<br>${clean(state.challenge_id.slice(0,6).toUpperCase())}</span></header>
      <div class="scv2-rules">${clean(state.prompt)}</div>
      <main><div class="scv2-stage"><canvas id="scv2-canvas" width="960" height="440" aria-label="moving lamp, specimen shadows and draggable camera apertures"></canvas><div class="scv2-verdict" data-visible="false"></div></div>
      <aside><p>NEGATIVE FILM</p><h2>Catch the lie<br>while it moves.</h2>
      ${state.benches.map((b,i)=>`<div class="scv2-meter" id="scv2-meter-${i}" data-camera="${i}"><label>CAMERA ${i+1}</label><div><i></i></div><b>0.0 / 6.0 s</b><small>NO CONTACT</small><select id="scv3-record-${i}" class="scv3-record" aria-label="table ${i+1} saved lamp tests" disabled><option>NO SAVED TESTS</option></select><canvas id="scv3-probe-${i}" class="scv3-probe" width="220" height="88" aria-label="table ${i+1} saved lamp test response record"></canvas></div>`).join('')}
      <div class="scv2-instruction">${model.mode==='full'?'Drag a lamp along its rail to test; drag a camera ring to aim.':'Click a lamp rail to test; click elsewhere in a table to aim its camera.'}<br>The small centre is the aperture; the ring has inertia.<br>Accepted controls advance fixed 40ms slices; idle waiting leaves the scene unchanged. Repeat tests freely; earlier records stay selectable.</div>
      <button id="scv2-start">START LIVE SCAN</button><p id="scv2-time">0.0 s / 120</p></aside></main>
      <footer><div class="readout">READY · COMPARE LAMP AND SHADOW RESPONSES</div><button id="scv2-file">FILE EVIDENCE</button></footer></section>`;
    const canvas=document.querySelector('#scv2-canvas');
    canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerup',up);
    canvas.addEventListener('pointercancel',cancel);canvas.addEventListener('lostpointercapture',cancel);
    document.querySelector('#scv2-start').addEventListener('click',start);
    document.querySelector('#scv2-file').addEventListener('click',()=>finish(true));
    state.benches.forEach((b,i)=>document.querySelector(`#scv3-record-${i}`).addEventListener('change',event=>{
      model.probeSelection[i]=Number(event.target.value);model.probeStamps[i]=null;draw();
    }));
    draw();raf=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.shadow_crime_lab_v3_nonrealtime={rootSelector:'.scv2',render};
})();
