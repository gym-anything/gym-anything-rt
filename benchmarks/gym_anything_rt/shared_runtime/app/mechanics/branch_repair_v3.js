(() => {
  'use strict';
  let frame = 0;
  const clean = s => String(s).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const dist = (a,b) => Math.hypot(a[0]-b[0],a[1]-b[1]);
  const CANCEL_RADIUS = 6;
  // Stable correspondence colours identify lane/glyph, never correct depth.
  const PORT_COLOURS=[['#f7d789','#aacddd','#76b4ed','#a2a5df','#d79dce'],
    ['#e9df86','#9ed3ac','#55bfa2','#62c5d8','#839ddb'],
    ['#ffc49b','#d4b396','#dda178','#dd898d','#bd93bc']];
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index+1,0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16),0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13),0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0)/4294967295*2-1;
  }
  function motion(seed,ms,span) {
    const u=Math.max(0,ms)/span,n=Math.floor(u),f=u-n;
    return noise(seed,n)+(noise(seed,n+1)-noise(seed,n))*f*f*(3-2*f);
  }
  function motionClock(ms,recoils=[]) {
    let clock=0,previous=0,heading=1;
    for(const at of recoils){if(at>ms)break;clock+=heading*(at-previous);previous=at;heading=-heading;}
    return clock+heading*(ms-previous);
  }
  function reflected(seed,ms,amplitude,span) {
    const start=(Math.imul(seed,2654435761)>>>0)%amplitude*4;
    const period=4*amplitude,phase=((start+2*amplitude*ms/span)%period+period)%period;
    return phase<2*amplitude?[phase-amplitude,1]:[3*amplitude-phase,-1];
  }
  function position(c,st,port,ms,recoils=[]) {
    const p=c.parameters,s=st.motion_seed;
    if(c.revision==='living-fibre-7') {
      const x=reflected(s,motionClock(ms,recoils),p.drift_px,p.span_ms)[0];
      const y=reflected(s+7919,ms,14,p.span_ms)[0];
      const flex=port.glyph?reflected(s+port.glyph*1327,ms,24,p.span_ms+317)[0]:0;
      return [port.p[0]+x+flex,port.p[1]+y+flex/16,port.p[2]+18*y/14+flex/16];
    }
    const d=[p.drift_px*motion(s,ms,p.span_ms),14*motion(s+7919,ms,p.span_ms),18*motion(s+15838,ms,p.span_ms)];
    return port.p.map((v,i)=>v+d[i]+(port.glyph ? (i===0?p.outlet_flex_px:1.5)*motion(s+port.glyph*1327+i*29,ms,p.span_ms+317):0));
  }
  function segmentDistance(p,a,b) {
    const dx=b[0]-a[0],dy=b[1]-a[1],v=dx*dx+dy*dy;
    const f=v ? Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/v)):0;
    return [Math.hypot(p[0]-a[0]-f*dx,p[1]-a[1]-f*dy),f];
  }
  function intersects(a,b,c,d) {
    const cross=(p,q,r)=>(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]);
    return Math.max(Math.min(a[0],b[0]),Math.min(c[0],d[0]))<=Math.min(Math.max(a[0],b[0]),Math.max(c[0],d[0])) &&
      Math.max(Math.min(a[1],b[1]),Math.min(c[1],d[1]))<=Math.min(Math.max(a[1],b[1]),Math.max(c[1],d[1])) &&
      cross(a,b,c)*cross(a,b,d)<=0 && cross(c,d,a)*cross(c,d,b)<=0;
  }
  function segmentSeparation(a,b,c,d) {
    if(intersects(a,b,c,d))return 0;
    return Math.min(segmentDistance(a,c,d)[0],segmentDistance(b,c,d)[0],segmentDistance(c,a,b)[0],segmentDistance(d,a,b)[0]);
  }
  class Simulation {
    constructor(c) {
      this.c=c;this.ms=0;this.started=false;this.failed='';this.done=false;
      this.x=c.fronts.map(f=>f.start_x);this.xUnits=c.fronts.map(f=>f.start_x*100000);this.open=new Set();this.cut=new Set();this.join={};this.crossed=new Set();
      this.tool='stitch';this.hold=null;this.selected=null;this.recoils=[];this.inspected=new Set();
    }
    advance(target) {
      if(!this.started)return;
      const p=this.c.parameters;
      while(this.ms<target && !this.failed && !this.done) {
        this.ms+=10;
        this.c.fronts.forEach((f,i)=>{if(this.c.revision==='living-fibre-7'){const sealed=this.c.stations.filter(s=>s.lane===i&&this.cut.has(s.id)&&s.id in this.join).length;this.xUnits[i]+=p.signal_speed*(78+22*(f.speed_seed%3))*(10+sealed);this.x[i]=this.xUnits[i]/100000;}else this.x[i]+=p.signal_speed*(1+.22*motion(f.speed_seed,this.ms,3700))*.01;});
        for(const st of this.c.stations) {
          const k=st.id;
          if(this.x[st.lane]+p.lead_px>=st.material_x)this.open.add(k);
          if(this.x[st.lane]>=st.material_x && !this.crossed.has(k)) {
            if(!this.cut.has(k) || !(k in this.join)) {this.failed='A signal escaped at an unrepaired lesion.';return;}
            this.crossed.add(k);
          }
        }
        this.done=this.x.every(x=>x>=this.c.finish_x);
        if(this.done){this.hold=null;this.selected=null;}
        if(this.ms>=this.c.max_ms && !this.done)this.failed='Signal delivery did not finish.';
      }
    }
    inspectHit(point) {
      const hits=[];
      for(const st of this.c.stations)for(const port of [st.source,...st.candidates]) {
        hits.push([dist(point,position(this.c,st,port,this.ms,this.recoils)),st.lane,st.column,st.id]);
      }
      hits.sort((a,b)=>a[0]-b[0]||a[1]-b[1]||a[2]-b[2]);
      return hits[0][0]<=this.c.parameters.port_radius?hits[0][3]:null;
    }
    portHit(point) {
      const hits=[];
      for(const st of this.c.stations) {
        if(!this.open.has(st.id) || st.id in this.join)continue;
        for(const port of [st.source,...st.candidates]) {
          const distance=dist(point,position(this.c,st,port,this.ms,this.recoils));
          if(distance<=this.c.parameters.port_radius)hits.push([distance,st.id,port.id,st.lane,st.column,port.glyph]);
        }
      }
      hits.sort((a,b)=>a[0]-b[0] || (this.c.revision==='living-fibre-7'?a[3]-b[3] || a[4]-b[4] || a[5]-b[5]:a[1].localeCompare(b[1]) || a[2].localeCompare(b[2])));
      return hits.length ? hits[0].slice(1,3):null;
    }
    bridge(st) {
      return [position(this.c,st,st.source,this.ms,this.recoils).slice(0,2),position(this.c,st,st.candidates.find(p=>p.id===st.bridge_to),this.ms,this.recoils).slice(0,2)];
    }
    cutHit(point,end=null) {
      const hits=[];
      for(const st of this.c.stations) {
        if(!this.open.has(st.id) || this.cut.has(st.id))continue;
        const [a,b]=this.bridge(st);
        if(end) {const d=segmentSeparation(point,end,a,b);if(dist(point,end)>=12 && d<=6)hits.push([d,st.id,st.lane,st.column]);}
        else {const [d]=segmentDistance(point,a,b);if(d<=6)hits.push([d,st.id,st.lane,st.column]);}
      }
      hits.sort((a,b)=>a[0]-b[0] || (this.c.revision==='living-fibre-7'?a[2]-b[2] || a[3]-b[3]:a[1].localeCompare(b[1])));
      return hits.length ? hits[0][1]:null;
    }
    stitch(first,second) {
      if(!first || !second){this.failed='A released stitch missed its moving continuation.';return;}
      if(JSON.stringify(first)===JSON.stringify(second)){this.failed='A stitch must connect two distinct ports.';return;}
      const st=this.c.stations.find(s=>s.id===first[0]);
      const expected=st.candidates.find(p=>p.p[2]===st.source.p[2]).id;
      const ports=[first[1],second[1]].sort().join('|');
      if(first[0]!==second[0] || ports!==[st.source.id,expected].sort().join('|')) {this.failed='A stitch fused neighbouring fibres.';return;}
      this.join[st.id]=expected;
      if(this.c.revision==='living-fibre-7')this.recoils.push(this.ms);
    }
    input(kind,point=null,mode='full',tool=null) {
      if(this.failed || this.done)return;
      if(kind==='inspect' && this.c.inspection_model) {const hit=this.inspectHit(point);if(hit)this.inspected.add(hit);return;}
      if(kind==='begin') {if(this.started)throw Error('episode cannot restart');this.started=true;
        for(const s of this.c.stations)if(this.x[s.lane]+this.c.parameters.lead_px>=s.material_x)this.open.add(s.id);return;}
      if(kind==='tool') {if(!['stitch','cut'].includes(tool))throw Error('unknown tool');this.tool=tool;this.selected=null;return;}
      if(!this.started)return;
      if(kind==='down' && mode==='full')this.hold=[this.tool,point,this.tool==='stitch'?this.portHit(point):null];
      else if(kind==='up' && mode==='full') {
        if(this.hold) {const [active,start,first]=this.hold;this.hold=null;
          if(active==='stitch'){if(dist(start,point)>CANCEL_RADIUS)this.stitch(first,this.portHit(point));}
          else {const cut=this.cutHit(start,point);if(cut)this.cut.add(cut);}
        }
      } else if(kind==='click' && mode==='simplified') {
        if(this.tool==='cut') {const cut=this.cutHit(point);if(cut)this.cut.add(cut);}
        else {const hit=this.portHit(point);if(this.selected){const preview=this.selected;this.selected=null;if(dist(preview.point,point)>CANCEL_RADIUS)this.stitch(preview.port,hit);}else this.selected={point,port:hit};}
      } else if(kind==='cancel') {this.hold=null;this.selected=null;}
      else throw Error('wrong input surface');
    }
    summary() {
      const result={t_ms:this.ms,signal_x:this.x.map(x=>Math.round(x*10000)/10000),opened:[...this.open].sort(),cut:[...this.cut].sort(),
        joins:Object.fromEntries(Object.entries(this.join).sort()),crossed:[...this.crossed].sort(),failed:this.failed,delivered:this.done};
      if(this.c.revision==='living-fibre-7'){result.motion_clock_ms=motionClock(this.ms,this.recoils);result.recoil_t_ms=[...this.recoils];result.signal_units=[...this.xUnits];}
      if(this.c.inspection_model)result.inspected=[...this.inspected].sort();
      return result;
    }
  }
  window.BranchRepairV3={Simulation,position,motion,motionClock,reflected};
  function render(state,helpers) {
    cancelAnimationFrame(frame);
    document.body.dataset.mechanic='branch-repair-v2';
    const mode=state.interaction,sim=new Simulation(state),observable=state.revision==='living-fibre-7';
    const model={state,sim,events:[],epoch:null,terminal:false,submitting:false,pointer:null,inspecting:false};
    window.branchRepairV3Model=model;
    helpers.app.innerHTML=`<section class="br2"><header><div><span>LIVING CONNECTOME / VOLUME REPAIR</span><h1>Branch Repair V3</h1></div><div class="br2-badge">${state.fronts.length} SIGNAL${state.fronts.length>1?'S':''}<br><b>KEEP FIBRES SEPARATE</b></div></header>
      <p class="br2-rules">${state.inspection_model?'Use SECTION LENS on any XY port to reveal its bridge path and linked depth views. Inspected sections stay visible. ':''}Match depth in XZ. Cut the pink bridge and stitch its outlet. ${observable?'Joins reverse tissue drift; sealed repairs accelerate their signal.':'Pale damage fronts open lesions ahead of the gold signals.'}</p>
      <main><article class="br2-main"><div class="br2-caption">XY / OPERATING PLANE <span>RECENT MOTION LEAVES A TRACE</span></div><canvas id="br2-xy" width="960" height="490" aria-label="moving fibre operating plane"></canvas></article>
      <aside>${['xz','yz','mesh'].map(v=>`<article><div class="br2-caption">${{xz:'XZ / DEPTH',yz:'YZ / END VIEW',mesh:'3D / RECONSTRUCTION'}[v]}</div><canvas data-view="${v}" width="260" height="145"></canvas></article>`).join('')}</aside></main>
      <footer><div class="br2-tools"><button id="br2-begin">BEGIN SIGNAL FLOW</button><button id="br2-stitch" class="active">STITCH</button><button id="br2-cut">CUT</button>${state.inspection_model?'<button id="br2-inspect">SECTION LENS</button>':''}<button id="br2-submit">CERTIFY DELIVERY</button></div><div class="br2-control">${mode==='full'?'STITCH: drag between matching open ports. CUT: drag across the bridge.':'STITCH: click two matching open ports. CUT: click the bridge.'} ${state.inspection_model?'LENS: click any port; safe before BEGIN, flow continues during live inspection. ':''}ESC cancels; ${mode==='full'?'release':'click'} inside the small preview ring to cancel. Missed endpoints, same-port stitches, wrong fusions and escaped signals fail.</div>${observable?'<div class="br2-flow" aria-label="flow and tissue instruments"></div>':''}<div class="readout">INSPECT THE VOLUME · START WHEN READY</div></footer><div class="br2-verdict" hidden><strong></strong><p></p></div></section>`;
    const root=helpers.app.querySelector('.br2'),canvas=root.querySelector('#br2-xy');
    const coordinate=e=>{const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*960/r.width,(e.clientY-r.top)*490/r.height];};
    function record(kind,point=null,tool=null) {
      model.events.push({sequence:model.events.length+1,t_ms:kind==='begin'?0:sim.ms,kind,input_source:['begin','tool','submit'].includes(kind)?'button':mode,
        ...(point?{point}:{}),...(tool?{tool}:{})});
    }
    function sync() {
      // Subtraction of the shared clock's floating base can place an exact
      // 10-ms endpoint a few ulps below its tick. This numerical tolerance is
      // 0.1 nanosecond; it does not add an input or timing grace period.
      if(model.epoch!==null && !model.terminal)sim.advance(Math.floor((performance.now()-model.epoch+1e-7)/10)*10);
      if(sim.failed && !model.terminal)finish(sim.failed);
    }
    const pose=(st,port,ms=sim.ms)=>position(state,st,port,ms,sim.recoils);
    function project(p,v,lane=0) {
      if(v==='xy')return p.slice(0,2);
      if(v==='xz')return [p[0]*.25+10,observable?(lane+.5)*145/state.fronts.length+(p[2]-state.fronts[lane].z)*({1:.45,2:.32,3:.22}[state.fronts.length]):72+p[2]*.45];
      if(v==='yz')return [p[1]*.46+15,72+p[2]*.45];
      return [18+p[0]*.22+p[2]*.18,16+p[1]*.23-p[2]*.16];
    }
    function drawPane(node,v) {
      const ctx=node.getContext('2d'),big=v==='xy',scale=big?1:.5;
      ctx.fillStyle='#091821';ctx.fillRect(0,0,node.width,node.height);
      ctx.strokeStyle='#24414a';ctx.lineWidth=.6;
      for(let x=15;x<node.width;x+=big?30:26){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,node.height);ctx.stroke();}
      for(let y=15;y<node.height;y+=big?30:24){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(node.width,y);ctx.stroke();}
      let currentLane=0;
      const line=(a,b,color,width=3)=>{const q=project(a,v,currentLane),r=project(b,v,currentLane);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(...q);ctx.lineTo(...r);ctx.stroke();};
      for(const st of state.stations) {
        if(!big && state.inspection_model && !sim.inspected.has(st.id))continue;
        currentLane=st.lane;
        const a=pose(st,st.source),open=sim.open.has(st.id),joined=st.id in sim.join;
        const revealed=!state.inspection_model || sim.inspected.has(st.id);
        const expected=st.candidates.find(p=>p.p[2]===st.source.p[2]);
        if(st.column===0)line([12,state.fronts[st.lane].y,state.fronts[st.lane].z],a,open?'#b1c9c6':'#506d72',big?5:2);
        const next=state.stations.find(s=>s.lane===st.lane && s.column===st.column+1);
        const far=next?pose(next,next.source):[945,state.fronts[st.lane].y,state.fronts[st.lane].z];
        for(const port of st.candidates) {
          const b=pose(st,port);
          // Every branch has the same downstream XY destination. In depth,
          // neighbouring fibres pass above or below the next source. The
          // correct outlet cannot be identified from a uniquely long XY line.
          line(b,[far[0],far[1],far[2]+port.p[2]-st.source.p[2]],'#688991',big?4:2);
          if(!observable && !open && port.id===expected.id)line(a,b,'#506d72',big?5:2);
          if(revealed && observable && port.id===st.bridge_to && (!open || sim.cut.has(st.id))) {ctx.setLineDash([3,6]);line(a,b,'#566a78',big?2:1);ctx.setLineDash([]);}
          if(revealed && open && !sim.cut.has(st.id) && port.id===st.bridge_to)line(a,b,'#d7a1a4',big?12:3);
          if(joined && sim.join[st.id]===port.id)line(a,b,'#8becb7',big?5:2);
        }
        if(big && !revealed) {
          ctx.strokeStyle='#566a78';ctx.lineWidth=2;ctx.setLineDash([4,4]);
          ctx.strokeRect(a[0]+24,a[1]-16,28,32);ctx.setLineDash([]);
          ctx.fillStyle='#afcccb';ctx.font='13px monospace';ctx.textAlign='center';ctx.fillText('?',a[0]+38,a[1]+4);
        }
        if(big && (observable || open && !joined)) {
          for(const port of [st.source,...st.candidates]) {
            const p=project(pose(st,port),v,st.lane),r=state.parameters.port_radius;
            ctx.strokeStyle='rgba(165,221,231,.35)';ctx.lineWidth=1.5;ctx.beginPath();
            for(let dt=600;dt>=0;dt-=100){const q=pose(st,port,Math.max(0,sim.ms-dt));dt===600?ctx.moveTo(q[0],q[1]):ctx.lineTo(q[0],q[1]);}ctx.stroke();
            ctx.fillStyle='#112f3d';ctx.strokeStyle=PORT_COLOURS[st.lane][port.glyph];ctx.lineWidth=2;
            ctx.beginPath();ctx.arc(p[0],p[1],r,0,Math.PI*2);ctx.fill();ctx.stroke();
            ctx.fillStyle='#e5f2ed';ctx.font='12px monospace';ctx.textAlign='center';ctx.fillText(port.glyph?'·'.repeat(port.glyph):'◇',p[0],p[1]+4);
            if(sim.selected?.port?.[1]===port.id || sim.hold?.[2]?.[1]===port.id){ctx.strokeStyle='#fff4b7';ctx.beginPath();ctx.arc(p[0],p[1],r+4,0,Math.PI*2);ctx.stroke();}
          }
        } else if(big) {
          for(const port of [st.source,...st.candidates]) {const p=project(position(state,st,port,sim.ms),v);ctx.fillStyle=joined?'#8becb7':'#a6c4ca';ctx.beginPath();ctx.arc(p[0],p[1],3*scale+1,0,Math.PI*2);ctx.fill();
          }
        }
      }
      for(const [i,f] of state.fronts.entries()) {
        if(!big && state.inspection_model)continue;
        currentLane=i;
        const route=(x)=>{
          const expectedPort=st=>st.candidates.find(p=>p.p[2]===st.source.p[2]).id;
          const row=state.stations.filter(s=>s.lane===i).sort((a,b)=>a.material_x-b.material_x);
          const points=[[12,f.y,f.z]];
          for(const st of row){
            points.push(pose(st,st.source));
            // An unrepaired front must not disclose the hidden continuation
            // by following its outlet. Flow uses the neutral tissue centreline
            // until the player has actually joined the fibre.
            points.push(state.inspection_model && !(st.id in sim.join)
              ? [pose(st,st.source)[0]+76,pose(st,st.source)[1],pose(st,st.source)[2]]
              : pose(st,st.candidates.find(p=>p.id===(sim.join[st.id]||expectedPort(st)))));
          }
          points.push([945,f.y,f.z]);
          const base=[12,...row.flatMap(s=>[s.material_x,s.material_x+76]),945];
          let j=base.findIndex(q=>q>=x);if(j<1)j=j===0?1:base.length-1;
          const t=Math.max(0,Math.min(1,(x-base[j-1])/(base[j]-base[j-1])));
          return points[j-1].map((q,k)=>q+(points[j][k]-q)*t);
        };
        if(sim.started) {
          const p=project(route(sim.x[i]),v,i),lead=project(route(Math.min(940,sim.x[i]+state.parameters.lead_px)),v,i);
          ctx.fillStyle='#c8eeee';ctx.globalAlpha=.35;ctx.beginPath();ctx.arc(lead[0],lead[1],big?12:4,0,Math.PI*2);ctx.fill();ctx.globalAlpha=1;
          ctx.shadowColor='#ffe1a3';ctx.shadowBlur=big?15:4;ctx.fillStyle='#ffdd86';ctx.beginPath();ctx.arc(p[0],p[1],big?8:3,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;
        }
        const source=project([12,f.y,f.z],v,i),end=project([945,f.y,f.z],v,i);
        ctx.fillStyle='#f5d391';ctx.fillRect(source[0]-4,source[1]-8,8,16);
        ctx.strokeStyle='#97c8bd';ctx.strokeRect(end[0]-5,end[1]-9,10,18);
      }
      // Endpoint correspondence must remain visible when projected fibres
      // or a signal overlap it. These are the same geometric ports, painted
      // above the reconstruction; colour identifies the incoming end only.
      if(!big)for(const incoming of [false,true])for(const st of state.stations)for(const port of incoming?[st.source]:st.candidates) {
        if(state.inspection_model && !sim.inspected.has(st.id))continue;
        const p=project(pose(st,port),v,st.lane),joined=st.id in sim.join;
        if(observable){ctx.fillStyle='#e5f2ed';ctx.font='10px monospace';ctx.textAlign='left';ctx.fillText(port.glyph?'·'.repeat(port.glyph):'◇',p[0]+4,p[1]-5);}
        ctx.fillStyle=joined?'#8becb7':PORT_COLOURS[st.lane][port.glyph];
        ctx.beginPath();ctx.arc(p[0],p[1],port.glyph===0?3.5:2.5,0,Math.PI*2);ctx.fill();
        if(!observable){ctx.fillStyle='#e5f2ed';ctx.font='10px monospace';ctx.textAlign='left';ctx.fillText(port.glyph?'·'.repeat(port.glyph):'◇',p[0]+4,p[1]-3);}
      }
      if(!big && state.inspection_model && sim.inspected.size===0) {
        ctx.fillStyle='#65757b';ctx.font='12px monospace';ctx.textAlign='center';
        ctx.fillText('SECTION LENS → XY PORT',node.width/2,node.height/2);
      }
      if(big && observable) {
        const arrow=(x,y,dx,dy)=>{ctx.strokeStyle='#66e7ef';ctx.lineWidth=1.7;ctx.beginPath();ctx.moveTo(x-dx*3,y-dy*3);ctx.lineTo(x+dx*3,y+dy*3);ctx.moveTo(x+dx*3-dx*2+dy*2,y+dy*3-dy*2-dx*2);ctx.lineTo(x+dx*3,y+dy*3);ctx.lineTo(x+dx*3-dx*2-dy*2,y+dy*3-dy*2+dx*2);ctx.stroke();};
        const direction=sim.recoils.length%2?-1:1;
        for(const st of state.stations) {
          const a=pose(st,st.source),r=state.parameters.port_radius,p=state.parameters;
          const hx=reflected(st.motion_seed,motionClock(sim.ms,sim.recoils),p.drift_px,p.span_ms)[1]*direction;
          const hy=reflected(st.motion_seed+7919,sim.ms,14,p.span_ms)[1];
          for(const offset of [-1,1]){arrow(a[0]+offset*(r+13),a[1]-7,hx,0);arrow(a[0]+offset*(r+13),a[1]+7,0,hy);}
          for(const port of st.candidates){const q=pose(st,port),h=reflected(st.motion_seed+port.glyph*1327,sim.ms,24,p.span_ms+317)[1];for(const offset of [-1,1])arrow(q[0]+offset*(r+13),q[1],h,0);}
        }
      }
      if(big && sim.hold && model.pointer) {
        const first=sim.hold[2],st=first?state.stations.find(s=>s.id===first[0]):null;
        const port=st?[st.source,...st.candidates].find(p=>p.id===first[1]):null;
        currentLane=st?.lane||0;
        const a=port?pose(st,port):sim.hold[1];
        line([a[0],a[1],0],[...model.pointer,0],sim.hold[0]==='cut'?'#f0a8ae':'#fff1ba',2);
      }
      if(big && (sim.selected || sim.hold?.[0]==='stitch')) {
        const preview=sim.selected || {point:sim.hold[1],port:sim.hold[2]};
        const [x,y]=preview.point;
        ctx.strokeStyle=preview.port?'#fff1ba':'#ff939e';ctx.lineWidth=2;
        ctx.beginPath();ctx.arc(x,y,CANCEL_RADIUS,0,Math.PI*2);ctx.stroke();
        if(!preview.port){ctx.beginPath();ctx.moveTo(x-4,y-4);ctx.lineTo(x+4,y+4);ctx.moveTo(x-4,y+4);ctx.lineTo(x+4,y-4);ctx.stroke();}
      }
    }
    function draw() {
      drawPane(canvas,'xy');for(const node of root.querySelectorAll('canvas[data-view]'))drawPane(node,node.dataset.view);
      for(const tool of ['stitch','cut'])root.querySelector('#br2-'+tool).classList.toggle('active',!model.inspecting && sim.tool===tool);
      if(state.inspection_model)root.querySelector('#br2-inspect').classList.toggle('active',model.inspecting);
      root.dataset.state=sim.failed?'failed':sim.done?'delivered':sim.started?'active':'ready';
      if(observable) {
        const text=`t ${sim.ms} ms · drift ${motionClock(sim.ms,sim.recoils)} ms ${sim.recoils.length%2?'←':'→'} · `+state.fronts.map((f,i)=>{const sealed=state.stations.filter(s=>s.lane===i&&sim.cut.has(s.id)&&s.id in sim.join).length;return `${i+1}: ${sim.x[i].toFixed(5)} / ${(state.parameters.signal_speed*(78+22*(f.speed_seed%3))*(10+sealed)/1000).toFixed(3)}`;}).join(' · ');
        const labels=state.fronts.map((_,lane)=>`${lane+1} [${state.stations.filter(s=>s.lane===lane).sort((a,b)=>a.column-b.column).map(s=>!sim.open.has(s.id)?'closed':`${sim.cut.has(s.id)?'cut':'CUT'}+${s.id in sim.join?'joined':'JOIN'}`).join(' / ')}]`).join(' · ');
        root.querySelector('.br2-flow').textContent=text+' · '+labels;
        root.querySelector('.br2-badge').textContent=text+` · tissue ±${state.parameters.drift_px} / ${state.parameters.span_ms} ms · flex ±24 / ${state.parameters.span_ms+317} ms · 4-unit calibration`;
      }
      if(!model.terminal)helpers.setReadout((sim.done?'ALL SIGNALS DELIVERED · CERTIFY':sim.started?'LIVE FLOW · '+sim.crossed.size+'/'+state.stations.length+' LESIONS PASSED':'INSPECT THE VOLUME · START WHEN READY')+(state.inspection_model?' · SECTIONS '+sim.inspected.size+' RETAINED':''),sim.done?'passed':'idle');
    }
    async function finish(reason='') {
      if(model.terminal)return;
      model.terminal=true;record('submit');draw();
      const verdict=root.querySelector('.br2-verdict');verdict.hidden=false;verdict.querySelector('strong').textContent=reason?'FAIL':'VERIFYING';verdict.querySelector('p').textContent=reason||'Signal delivery';
      const payload={mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,revision:state.revision,
        interaction:mode,events:model.events,summary:sim.summary(),completed:sim.done && !sim.failed};
      try {const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});const grade=await response.json();
        if(!response.ok)throw Error('HTTP '+response.status);
        verdict.querySelector('strong').textContent=grade.passed?'PASS':'FAIL';root.dataset.verdict=grade.passed?'pass':'fail';
        verdict.querySelector('p').textContent=grade.passed?'Every signal stayed in its fibre.':reason||'Signal delivery incomplete.';helpers.setReadout(grade.passed?'PASS':'FAIL',grade.passed?'passed':'error');
      } catch(error) {verdict.querySelector('strong').textContent='VERIFIER ERROR';verdict.querySelector('p').textContent=error.message;helpers.setReadout('VERIFIER ERROR','error');}
    }
    function input(kind,point=null,tool=null) {
      sync();if(model.terminal || sim.done)return;
      if(model.epoch===null && !['begin','inspect'].includes(kind))return;
      if(kind==='begin') {model.epoch=performance.now();root.querySelector('#br2-begin').disabled=true;}
      record(kind,point,tool);sim.input(kind,point,mode,tool);draw();if(sim.failed)finish(sim.failed);
    }
    root.querySelector('#br2-begin').addEventListener('click',()=>{if(model.epoch===null)input('begin');});
    for(const tool of ['stitch','cut'])root.querySelector('#br2-'+tool).addEventListener('click',()=>{model.inspecting=false;input('tool',null,tool);draw();});
    if(state.inspection_model)root.querySelector('#br2-inspect').addEventListener('click',()=>{if(model.terminal || sim.done)return;if(sim.hold || sim.selected)input('cancel');model.inspecting=true;draw();});
    root.querySelector('#br2-submit').addEventListener('click',()=>{sync();if(!model.terminal)finish(sim.done?'':'Signal delivery incomplete.');});
    canvas.addEventListener('pointerdown',e=>{if(e.button!==0 || mode!=='full' || model.inspecting)return;canvas.setPointerCapture(e.pointerId);model.pointer=coordinate(e);input('down',model.pointer);e.preventDefault();});
    canvas.addEventListener('pointermove',e=>{if(sim.hold){model.pointer=coordinate(e);sync();draw();}});
    canvas.addEventListener('pointerup',e=>{if(mode!=='full' || model.inspecting)return;input('up',coordinate(e));model.pointer=null;canvas.releasePointerCapture?.(e.pointerId);});
    for(const type of ['pointercancel','lostpointercapture'])canvas.addEventListener(type,()=>{if(sim.hold)input('cancel');model.pointer=null;});
    canvas.addEventListener('click',e=>{if(model.inspecting)input('inspect',coordinate(e));else if(mode==='simplified')input('click',coordinate(e));});
    window.addEventListener('keydown',e=>{if(root.isConnected && e.key==='Escape'){input('cancel');model.pointer=null;e.preventDefault();}});
    const animate=()=>{sync();draw();if(!model.terminal)frame=requestAnimationFrame(animate);};
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.branch_repair_v3={rootSelector:'.br2',render};
})();
