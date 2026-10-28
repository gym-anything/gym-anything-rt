(() => {
  'use strict';
  const ID = 'coordinates_by_another_name_v3_nonrealtime';
  let m, h, frame = 0;
  const $ = s => document.querySelector(s);
  const angle = (i,n) => (-210+240*i/(n-1))*Math.PI/180;
  const dialPoint = (i,n,r) => [84+Math.cos(angle(i,n))*r,84+Math.sin(angle(i,n))*r];
  // The decision surface is stable while the player is idle.  Logical task
  // time advances only at a deliberate selector/scan action; a launched
  // torpedo has one finite, action-triggered flight before the next decision.
  const clock = () => m ? m.t : 0;
  const decisionStep = () => m.state.world.nonrealtime.decision_step_ms;
  function position(ship,t) {
    const u=Math.max(0,t)/m.state.world.parameters.span_ms, n=Math.min(Math.floor(u),ship.knots.length-2);
    let f=Math.min(1,u-n);f=f*f*(3-2*f);
    return ship.knots[n].map((v,a)=>v+(ship.knots[n+1][a]-v)*f);
  }
  function record(action,input_source,extra={}) {
    const t=clock();
    m.events.push({sequence:m.events.length+1,t_ms:t,action,input_source,...extra});
    return t;
  }
  function resolve() {
    const address=m.indices.map((v,a)=>m.options[a][v]);
    return m.state.world.cells.find(c=>c.band===address[0]&&c.block===address[1]&&c.count===address[2]);
  }
  function sector() {
    const w=m.state.world,band=m.options[0][m.indices[0]],block=m.options[1][m.indices[1]];
    const r=w.runs.find(r=>r.band===band&&r.block===block),cw=768/w.columns,rh=312/w.rows;
    return {address:[band,block],x:48+r.start*cw,y:24+r.row*rh,width:r.width*cw,height:rh};
  }
  function contacts(area,t) {
    return m.state.world.fleet.filter(s=>{
      const p=position(s,t);
      return s.offsets.some(o=>{
        const x=p[0]+o[0],y=p[1]+o[1];
        return Math.hypot(x-Math.max(area.x,Math.min(area.x+area.width,x)),
          y-Math.max(area.y,Math.min(area.y+area.height,y)))<=s.radius;
      });
    }).map(s=>s.id).sort();
  }
  function contactName(id) {
    const s=m.state.world.fleet.find(s=>s.id===id);
    return s.protected?`SAFE ${+id.split('-')[1]-m.state.world.parameters.hostile}`:id.replace('hull-','H');
  }
  function hit(cell,t) {
    const hits=[];let protectedHit=false;
    for(const s of m.state.world.fleet) {
      const p=position(s,t);
      s.offsets.forEach((o,i)=>{
        const key=`${s.id}:${i}`;
        if(m.damaged.has(key))return;
        if(Math.hypot(p[0]+o[0]-cell.x,p[1]+o[1]-cell.y)<=s.radius+m.state.world.parameters.blast_radius) {
          if(s.protected)protectedHit=true;else hits.push(key);
        }
      });
    }
    return {hits:hits.sort(),protectedHit};
  }
  function settlePending() {
    if(m.terminal||!m.pending)return;
    const p=m.pending, result=hit(p.cell,p.at);
    m.pending=null;m.t=p.at;m.bursts.push({cell:p.cell,at:p.at});
    if(p.at>m.state.world.play_time_ms) {
      m.t=m.state.world.play_time_ms;m.doneAt=m.t;m.failed=true;m.reason='WATCH ENDED';finish();return;
    }
    if(result.protectedHit||!result.hits.length) {
      m.failed=true;m.doneAt=p.at;m.reason=result.protectedHit?'PROTECTED HULL HIT':'TORPEDO MISSED';
      finish();return;
    }
    result.hits.forEach(k=>m.damaged.add(k));
    m.last=`HIT · ${result.hits.length} COMPARTMENT${result.hits.length>1?'S':''} FLOODED`;
    if(m.damaged.size===m.targets.length){m.doneAt=p.at;finish();return;}
    draw();
  }
  function advanceDecision() {
    if(m.terminal||m.pending)return false;
    if(!m.started)return true;
    const next=m.t+decisionStep();
    if(next>=m.state.world.play_time_ms) {
      m.t=m.state.world.play_time_ms;m.failed=true;m.doneAt=m.t;m.reason='WATCH ENDED';finish();return false;
    }
    m.t=next;return true;
  }
  function selectors() {
    $('.cv-selectors').innerHTML=m.options.map((vals,a)=>{
      const name=['BAND','BLOCK','COUNT'][a];
      if(m.mode==='simplified')return `<section><label>${name}</label><div class="cv-values">${vals.map((v,i)=>`<button data-axis="${a}" data-index="${i}" aria-pressed="${m.indices[a]===i}">${v}</button>`).join('')}</div></section>`;
      const [x,y]=dialPoint(m.indices[a],vals.length,43);
      return `<section><label>${name}</label><svg class="cv-dial" data-axis="${a}" viewBox="0 0 168 168" aria-label="${name}: drag knob to a label"><path d="M28 116 A65 65 0 1 1 140 116" stroke="#62857b" fill="none"/>${vals.map((v,i)=>{const [tx,ty]=dialPoint(i,vals.length,69);return `<text x="${tx}" y="${ty+5}" text-anchor="middle" class="${m.indices[a]===i?'chosen':''}">${v}</text>`;}).join('')}<circle cx="84" cy="84" r="43" fill="#203d38" stroke="#82a599"/><line x1="84" y1="84" x2="${x}" y2="${y}" stroke="#ffd379" stroke-width="5"/><circle cx="84" cy="84" r="8" fill="#e5d5b0"/><text x="84" y="158" text-anchor="middle" class="cv-drag-text">DRAG TO SET</text></svg></section>`;
    }).join('');
    $('.cv-address').textContent=m.indices.map((v,a)=>m.options[a][v]).join(' · ');
    document.querySelectorAll('.cv-values button').forEach(b=>b.onclick=()=>select(+b.dataset.axis,+b.dataset.index,'value_button'));
    document.querySelectorAll('.cv-dial').forEach(d=>{
      let start=null;
      const xy=e=>{const r=d.getBoundingClientRect();return [168*(e.clientX-r.left)/r.width,168*(e.clientY-r.top)/r.height];};
      d.onpointerdown=e=>{
        if(e.button!==0||m.terminal)return;
        const p=xy(e);if(Math.hypot(p[0]-84,p[1]-84)>43)return;
        start=p;d.setPointerCapture(e.pointerId);e.preventDefault();
      };
      d.onpointerup=e=>{
        if(!start)return;const a=+d.dataset.axis,begin=start;start=null;const end=xy(e);
        if(Math.hypot(end[0]-begin[0],end[1]-begin[1])<8)return;
        let delta=((Math.atan2(end[1]-84,end[0]-84)*180/Math.PI+210)%360+360)%360;
        const half=120/(m.options[a].length-1),radius=Math.hypot(end[0]-84,end[1]-84);
        if(radius<24||radius>86||(delta>240+half&&delta<360-half))return;
        delta=delta>=360-half?0:Math.min(240,delta);
        select(a,Math.round(delta/240*(m.options[a].length-1)),'rotary_drag',{start:begin,release:end});
      };
      d.onpointercancel=()=>{start=null;};
      d.onlostpointercapture=()=>{start=null;};
    });
  }
  function select(axis,index,source,gesture={}) {
    if(!advanceDecision())return;
    record('select',source,{axis,index,...gesture});m.indices[axis]=index;selectors();draw();
  }
  function scan() {
    if(!advanceDecision())return;
    const area=sector(),t=clock(),found=contacts(area,t);
    record('scan','scan_button',{t_ms:t,sector:area.address,contacts:found});
    found.forEach(id=>m.discovered.add(id));
    m.soundings.set(area.address.join(' '),{t,contacts:found});
    m.echoUntil=t+m.state.world.parameters.echo_ms;
    m.last=`SECTOR ${area.address.join(' · ')} / ${found.length?found.map(contactName).join(', '):'NO CONTACTS'} · ${m.discovered.size} TRACKED`;
    draw();
  }
  function start() {
    if(m.started||m.terminal)return;
    record('start','start_button');m.started=true;m.last='FLEET UNDER WAY';draw();
  }
  function fire() {
    if(m.terminal||!m.started||m.pending)return;
    const cell=resolve();if(!cell){m.last='VOID ADDRESS · NO TORPEDO LAUNCHED';draw();return;}
    const t=record('fire','fire_button',{designation:m.indices.map((v,a)=>m.options[a][v])});
    m.pending={cell,launched:t,at:t+m.state.world.parameters.flight_ms};m.shots++;m.last='TORPEDO RUNNING';draw();
    m.flightTimer=setTimeout(()=>{m.flightTimer=null;settlePending();},m.state.world.parameters.flight_ms);
  }
  function payload() {
    return {mechanic_id:ID,task_id:m.state.task_id,challenge_id:m.state.challenge_id,interaction_mode:m.mode,
      events:m.events,final_t_ms:m.doneAt??clock(),completed:!m.failed&&m.damaged.size===m.targets.length,
      final:{damaged:[...m.damaged].sort(),shots:m.shots,failed:m.failed}};
  }
  async function finish(manual=false) {
    if(m.terminal)return;
    if(manual&&m.flightTimer){clearTimeout(m.flightTimer);m.flightTimer=null;}
    m.doneAt=m.doneAt??clock();m.terminal=true;draw();
    const won=!m.failed&&m.damaged.size===m.targets.length;
    $('.cv-verdict').innerHTML=`<strong>${won?'VERIFYING…':'FAIL'}</strong><span>${m.reason||'FLEET INCOMPLETE'}</span>`;
    h.setReadout(won?'VERIFYING FLEET…':`FAIL · ${m.reason||'FLEET INCOMPLETE'}`,won?'pending':'error');
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
      if(!response.ok)throw Error(`HTTP ${response.status}`);
      const result=await response.json();
      $('.cv-verdict').innerHTML=`<strong>${result.passed?'PASS':'FAIL'}</strong><span>${result.passed?'HOSTILE FLEET SUNK · PROTECTED FLEET SAFE':m.reason||'FLEET INCOMPLETE'}</span>`;
      h.setReadout(result.passed?'PASS · FLEET ACCOUNTED FOR':`FAIL · ${m.reason||'ATTEMPT ENDED'}`,result.passed?'passed':'error');
    } catch(error) { $('.cv-verdict').innerHTML=`<strong>SUBMISSION ERROR</strong><span>${String(error.message)}</span>`;h.setReadout('SUBMISSION ERROR','error'); }
  }
  function draw() {
    const w=m.state.world,t=m.doneAt??clock(),echo=t<=m.echoUntil;
    const ctx=$('#cv-chart').getContext('2d');ctx.clearRect(0,0,840,370);
    ctx.fillStyle='#0d292a';ctx.fillRect(0,0,840,370);
    const cw=768/w.columns,rh=312/w.rows;
    for(const c of w.cells) {
      ctx.strokeStyle='#38514a';ctx.lineWidth=1;ctx.strokeRect(48+c.column*cw,24+c.row*rh,cw,rh);
    }
    const area=sector();
    ctx.fillStyle='#71b8bc16';ctx.fillRect(area.x,area.y,area.width,area.height);
    ctx.strokeStyle='#71b8bc';ctx.lineWidth=2;ctx.setLineDash([3,5]);
    ctx.strokeRect(area.x+1,area.y+1,area.width-2,area.height-2);ctx.setLineDash([]);
    ctx.font='bold 17px ui-monospace,monospace';ctx.textAlign='center';ctx.fillStyle='#d8cb99';
    w.bands.forEach((b,i)=>ctx.fillText(b,25,24+(i+.5)*rh+6));
    ctx.font='12px ui-monospace,monospace';
    for(const r of w.runs) {
      const x=48+r.start*cw,y=24+(r.row+1)*rh-4;
      ctx.fillStyle='#092626';ctx.fillRect(x+2,y-10,r.width*cw-4,13);
      ctx.fillStyle='#b1b794';ctx.fillText(`${r.block} ${r.reverse?'←':'→'}`,x+r.width*cw/2,y+1);
    }
    const selected=resolve();
    if(selected) {
      ctx.strokeStyle='#ffd379';ctx.lineWidth=2;ctx.setLineDash([5,4]);
      ctx.beginPath();ctx.arc(selected.x,selected.y,w.parameters.blast_radius,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);
      ctx.beginPath();ctx.moveTo(selected.x-8,selected.y);ctx.lineTo(selected.x+8,selected.y);ctx.moveTo(selected.x,selected.y-8);ctx.lineTo(selected.x,selected.y+8);ctx.stroke();
    }
    if(echo) for(const s of w.fleet) {
      if(!m.discovered.has(s.id))continue;
      if(!s.protected&&s.offsets.every((_,i)=>m.damaged.has(`${s.id}:${i}`)))continue;
      const color=s.protected?'#b9d7d1':'#ffbd72';
      // Rolling preview, drawn in 400ms time marks. It is visible planning
      // information, not an automatically chosen firing coordinate.
      ctx.strokeStyle=color;ctx.globalAlpha=.48;ctx.lineWidth=2;ctx.setLineDash([5,6]);ctx.beginPath();
      for(let dt=0;dt<=w.preview_ms;dt+=80){const p=position(s,t+dt);if(dt===0)ctx.moveTo(...p);else ctx.lineTo(...p);}
      ctx.stroke();ctx.setLineDash([]);
      for(let dt=400;dt<=w.preview_ms;dt+=400) {const p=position(s,t+dt);ctx.beginPath();ctx.arc(...p,dt===w.preview_ms?5:2.5,0,Math.PI*2);ctx.stroke();}
      ctx.globalAlpha=.26;ctx.beginPath();for(let dt=-Math.min(t,600);dt<=0;dt+=30){const p=position(s,t+dt);if(dt===-Math.min(t,600))ctx.moveTo(...p);else ctx.lineTo(...p);}ctx.stroke();ctx.globalAlpha=1;
      const p=position(s,t);
      ctx.strokeStyle=color;ctx.fillStyle='#214443';ctx.lineWidth=2;
      s.offsets.forEach((o,i)=> {
        const x=p[0]+o[0],y=p[1]+o[1],flooded=m.damaged.has(`${s.id}:${i}`);
        ctx.globalAlpha=flooded?.30:1;ctx.beginPath();ctx.arc(x,y,s.radius,0,Math.PI*2);ctx.fill();ctx.stroke();
        ctx.lineWidth=3;ctx.beginPath();
        if(s.protected||flooded){ctx.moveTo(x-7,y-7);ctx.lineTo(x+7,y+7);ctx.moveTo(x-7,y+7);ctx.lineTo(x+7,y-7);}
        else {ctx.moveTo(x-7,y);ctx.lineTo(x+7,y);ctx.moveTo(x,y-7);ctx.lineTo(x,y+7);}
        ctx.stroke();ctx.lineWidth=2;ctx.globalAlpha=1;
      });
      ctx.fillStyle=color;ctx.font='11px ui-monospace,monospace';ctx.fillText(contactName(s.id),p[0],p[1]-s.radius-7);
    }
    if(m.pending) {
      const ratio=Math.max(0,Math.min(1,(t-m.pending.launched)/w.parameters.flight_ms));
      const target=m.pending.cell,x=48+(target.x-48)*ratio,y=354+(target.y-354)*ratio;
      ctx.strokeStyle='#ffe7a4';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(48,354);ctx.lineTo(x,y);ctx.stroke();ctx.fillStyle='#ffe7a4';ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill();
    }
    for(const b of m.bursts)if(t-b.at<700){ctx.strokeStyle='#ffd379';ctx.lineWidth=3;ctx.beginPath();ctx.arc(b.cell.x,b.cell.y,w.parameters.blast_radius,0,Math.PI*2);ctx.stroke();}
    $('#cv-start').disabled=m.started||m.terminal;$('#cv-scan').disabled=m.terminal;
    $('#cv-fire').disabled=!m.started||!!m.pending||m.terminal;$('#cv-submit').disabled=m.terminal;
    $('.cv-status').textContent=m.terminal?'WATCH CLOSED':m.started?'FLEET UNDER WAY':'PREPARATION';
    $('.cv-contact').textContent=echo?'SONAR CONTACTS LIVE':'SONAR DARK · SCAN';
    $('.cv-flight').textContent=m.pending?`${(Math.max(0,m.pending.at-t)/1000).toFixed(1)}s IN FLIGHT`:`${w.parameters.flight_ms/1000}s FLIGHT`;
    $('.cv-last').textContent=m.last;
    $('.cv-sector').textContent=`SCAN SECTOR ${area.address.join(' · ')} · COUNT IGNORED`;
    const known=[...m.discovered].sort().map(contactName).join(', ')||'NONE';
    const soundings=[...m.soundings].map(([key,value])=>`${key}: ${value.contacts.length?value.contacts.map(contactName).join(', '):'EMPTY'} @ ${(value.t/1000).toFixed(1)}s`).join(' | ')||'NO SECTORS INSPECTED';
    $('.cv-soundings').textContent=`KNOWN: ${known} / ${soundings}`;
    $('.cv-safe').textContent=`${w.fleet.filter(s=>s.protected&&m.discovered.has(s.id)).length} / ${w.parameters.protected} SAFE HULLS LOCATED`;
    $('.cv-fleet').innerHTML=w.fleet.filter(s=>!s.protected).map(s=>`<div><b>${s.id.replace('hull-','H')}</b><span>${s.offsets.map((_,i)=>`<i class="${m.damaged.has(`${s.id}:${i}`)?'flooded':''}"></i>`).join('')}</span><em>${s.offsets.every((_,i)=>m.damaged.has(`${s.id}:${i}`))?'SUNK':m.discovered.has(s.id)?'AFLOAT':'UNLOCATED'}</em></div>`).join('');
  }
  async function render(state,helpers) {
    cancelAnimationFrame(frame);h=helpers;document.body.dataset.mechanic=ID;
    const w=state.world;
    m={state,mode:state.control_condition.interaction,options:[[...w.bands].sort((a,b)=>a-b),['A','B','C'],Array.from({length:w.columns},(_,i)=>i+1)],indices:[0,0,0],
      started:false,startedAt:0,t:0,events:[],pending:null,shots:0,damaged:new Set(),targets:w.fleet.filter(s=>!s.protected).flatMap(s=>s.offsets.map((_,i)=>`${s.id}:${i}`)),
      echoUntil:-1,discovered:new Set(),soundings:new Map(),bursts:[],failed:!!state.episode_failed,terminal:false,doneAt:null,last:'SELECT A BAND + BLOCK TO INSPECT',reason:''};
    // Read-only diagnostic consumers may inspect this object for oracle planning;
    // player input is always mouse/keyboard, never object mutation or functions.
    window.coordinatesByAnotherNameV3Model=m;
    h.app.innerHTML=`<article class="cv-root"><header><div><p>HYDROGRAPHIC OFFICE / ACTION-STEPPED SONAR WATCH</p><h1>Coordinates by Another Name V3</h1></div><aside><b class="cv-status"></b><span class="cv-contact"></span></aside></header><main><section class="cv-map"><canvas id="cv-chart" width="840" height="370" aria-label="Sonar chart, symbolic rows and block brackets; cyan bracket is the selected scan sector"></canvas><div class="cv-key"><span>+ HOSTILE COMPARTMENT</span><span>× PROTECTED HULL</span><span>··· FORECAST: DOTS 0.4s / END 3.2s</span></div><div class="cv-last"></div></section><aside class="cv-right"><p>HOSTILE FLEET</p><div class="cv-fleet"></div><small class="cv-safe"></small><div class="cv-legend"><b>SEARCH BEFORE LAUNCH</b><span>Inspect BAND + BLOCK in cyan.</span><span>Only touching hulls are found.</span><span>Any scan refreshes found tracks.</span><span>Safe before WAKE; actions advance.</span><span>Miss / protected hit ends watch.</span></div><small class="cv-sector"></small><button id="cv-start">WAKE FLEET →</button><button id="cv-scan">SONAR SCAN</button></aside></main><div class="cv-soundings" aria-label="Persistent sonar inspection log"></div><footer><div class="cv-selectors"></div><section class="cv-launch"><small>DESIGNATION</small><b class="cv-address"></b><span class="cv-flight"></span><button id="cv-fire">FIRE TORPEDO</button><button id="cv-submit">END WATCH</button></section></footer><div class="cv-verdict"></div></article>`;
    selectors();$('#cv-start').onclick=start;$('#cv-scan').onclick=scan;$('#cv-fire').onclick=fire;$('#cv-submit').onclick=()=>finish(true);
    if(state.episode_failed){m.reason='THIS EPISODE HAS ALREADY FAILED';finish();}
    else {draw();}
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.cv-root',render};
})();
