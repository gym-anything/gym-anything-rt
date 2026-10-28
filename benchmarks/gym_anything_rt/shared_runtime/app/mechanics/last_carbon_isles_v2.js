(() => {
  'use strict';
  const ID = 'last_carbon_isles_v2';
  let m, frame;
  const esc = x => String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function loads(spec,t) {
    const out = spec.islands.map(() => spec.total_load/spec.islands.length);
    for (const v of spec.modes) {
      const time=t+v.offset_s;
      let k=0; while (k+1<v.times.length && v.times[k+1]<=time) k++;
      const f=(time-v.times[k])/(v.times[k+1]-v.times[k]);
      const value=v.amplitude*(v.knots[k]+(v.knots[k+1]-v.knots[k])*f*f*(3-2*f));
      v.vector.forEach((a,i) => out[i]+=a*value);
    }
    return out;
  }
  function time() { return m.startedAt===null ? 0 : Math.max(0,(performance.now()-m.startedAt)/1000); }
  function record(kind, fields={}) {
    // Inputs change the target for the next fixed physics step. Replay the
    // last completed step exactly, rather than rounding across its boundary.
    m.events.push({sequence:m.events.length+1,kind,t_s:m.tick*m.state.step_s,...fields});
  }
  function advance() {
    if (!m || m.startedAt===null || m.terminal) return;
    const s=m.state, dt=s.step_s, end=Math.min(Math.floor((time()+1e-8)/dt),Math.round(s.run_seconds/dt));
    while (m.tick<end && !m.failure) {
      const demand=loads(s,(m.tick+.5)*dt), total=m.targets.reduce((a,b)=>a+b,0);
      const factor=total>0 ? Math.min(1,s.capacity/total) : 1;
      const alpha=1-Math.exp(-dt/s.parameters.inertia_s);
      m.targets.forEach((a,i)=> {
        m.supply[i]+=(a*factor-m.supply[i])*alpha;
        m.battery[i]=Math.min(s.islands[i].battery_capacity,m.battery[i]+(m.supply[i]-demand[i])*dt);
        m.minimum[i]=Math.min(m.minimum[i],m.battery[i]);
        m.energy[i]+=demand[i]*dt;
        if (m.battery[i]<=0) m.failure=`${s.islands[i].name}: battery empty, crews stopped`;
      });
      m.tick++;
    }
    if (m.failure) finish(false,m.failure);
    else if (m.tick>=Math.round(s.run_seconds/dt)) finish(true,'All coal works retired. Every crew stayed powered.');
  }
  function paint() {
    const t=m.tick*m.state.step_s, demand=loads(m.state,t), forecast=loads(m.state,t+m.state.forecast_s);
    const used=m.supply.reduce((a,b)=>a+b,0), requested=m.targets.reduce((a,b)=>a+b,0);
    document.querySelector('.ci-budget b').textContent=`${used.toFixed(1)} / 100 MW`;
    document.querySelector('.ci-budget small').textContent=requested>100 ? `Requested ${requested.toFixed(1)} · all shares scaled to fit` : `Requested ${requested.toFixed(1)} · ${Math.max(0,100-used).toFixed(1)} spare`;
    document.querySelector('.ci-progress i').style.width=`${100*Math.min(1,t/m.state.run_seconds)}%`;
    document.querySelector('.ci-progress span').textContent=`${Math.round(100*(1-t/m.state.run_seconds))}% COAL WORKS LEFT`;
    m.state.islands.forEach((s,i)=> {
      const row=document.querySelector(`[data-island="${i}"]`), rail=row.querySelector('.ci-rail');
      rail.querySelector('.ci-policy').style.left=`${m.targets[i]}%`;
      rail.querySelector('.ci-supply').style.width=`${m.supply[i]}%`;
      rail.querySelector('.ci-demand').style.left=`${demand[i]}%`;
      rail.querySelector('.ci-forecast').style.left=`${forecast[i]}%`;
      const rate=(loads(m.state,t+.1)[i]-demand[i])/.1;
      row.querySelector('.ci-load').textContent=`LOAD ${demand[i].toFixed(1)} MW ${rate>=0?'↗':'↘'} ${Math.abs(rate).toFixed(1)}/s`;
      row.querySelector('.ci-energy').textContent=`CLEAN ${m.supply[i].toFixed(1)} · REQUEST ${m.targets[i].toFixed(1)} MW`;
      row.querySelector('.ci-cell i').style.height=`${Math.max(0,100*m.battery[i]/s.battery_capacity)}%`;
      row.querySelector('.ci-cell').classList.toggle('ci-low',m.battery[i]<s.battery_capacity*.3);
      row.querySelector('.ci-cell b').textContent=`${Math.max(0,m.battery[i]).toFixed(1)}`;
      row.querySelector('.ci-smoke').style.opacity=`${.15+.65*(1-t/m.state.run_seconds)}`;
      const trail=rail.querySelectorAll('.ci-trail');
      trail.forEach((node,k)=>node.style.left=`${loads(m.state,Math.max(0,t-(k+1)*.2))[i]}%`);
    });
  }
  function animate() {
    advance();
    if (m && document.querySelector('.ci-game')) paint();
    frame=requestAnimationFrame(animate);
  }
  function launch() {
    if (m.startedAt!==null || m.terminal) return;
    m.startedAt=performance.now();
    record('start',{input_source:'launch_button'});
    document.querySelector('.ci-launch').disabled=true;
    document.querySelector('.ci-status').textContent='TRANSITION ACTIVE · GRID AND LOADS CONTINUE DURING INPUT';
  }
  async function finish(completed,reason) {
    if (m.terminal) return;
    m.terminal=true;
    document.querySelector('.ci-certify').disabled=true;
    record('finish',{input_source:completed?'automatic_completion':'terminal_failure'});
    const payload={mechanic_id:ID,task_id:m.state.task_id,challenge_id:m.state.challenge_id,
      revision:m.state.revision,interaction_mode:m.interaction,events:m.events,completed};
    m.payload=payload;
    const verdict=document.querySelector('.ci-verdict');
    verdict.hidden=false;
    verdict.className=`ci-verdict ${completed?'ci-pass':'ci-fail'}`;
    verdict.querySelector('strong').textContent=completed?'COAL RETIRED':'CREWS STOPPED';
    verdict.querySelector('p').textContent=reason+(completed?'':' This first failure ends the episode.');
    m.helpers.setReadout(completed?'VERIFYING':'FAIL',completed?'pending':'error');
    try {
      const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      const result=await response.json(); m.result=result;
      const passed=result.passed===true;
      verdict.className=`ci-verdict ${passed?'ci-pass':'ci-fail'}`;
      verdict.querySelector('strong').textContent=passed?'PASS':'FAIL';
      verdict.querySelector('p').textContent=(result.feedback||reason)+(passed?'':' This first failure ends the episode.');
      m.helpers.setReadout(passed?'PASS':'FAIL',passed?'passed':'error');
    } catch (error) {
      verdict.querySelector('strong').textContent='SUBMISSION ERROR';
      verdict.querySelector('p').textContent=error.message;
      m.helpers.setReadout('SUBMISSION ERROR','error');
    }
  }
  function point(rail,e) {
    const r=rail.getBoundingClientRect();
    return [(e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height-.5];
  }
  function dispatch(i,p,start) {
    advance();
    if (m.terminal || Math.abs(p[1])>.5) return;
    const share=Math.max(0,Math.min(100,p[0]*100));
    const rect=document.querySelectorAll('.ci-rail')[i].getBoundingClientRect();
    const fields={island:i,share,point:[share/100,p[1]],rail_size:[rect.width,rect.height],input_source:m.interaction==='full'?'policy_drag':'rail_click'};
    if (m.interaction==='full') fields.start=start;
    record(m.startedAt===null?'prepare':'dispatch',fields); m.targets[i]=share; paint();
  }
  async function render(state,helpers) {
    cancelAnimationFrame(frame);
    document.body.dataset.mechanic='last-carbon-isles-v2';
    m={state,helpers,interaction:state.control_condition.interaction,startedAt:null,tick:0,events:[],
      targets:state.islands.map(s=>s.initial_share),supply:state.islands.map(s=>s.initial_share),
      battery:state.islands.map(s=>s.battery_capacity),minimum:state.islands.map(s=>s.battery_capacity),
      energy:state.islands.map(()=>0),terminal:false,failure:null,drag:null};
    // Validation-only read access. Inputs remain ordinary visible controls.
    window.lastCarbonIslesV2Model=m;
    helpers.app.innerHTML=`<section class="ci-game" data-interaction="${m.interaction}" data-count="${state.islands.length}">
      <header><div><span class="ci-kicker">A CLEAN GRID / A CHANGING SEA</span><h1>The Last Carbon Isles V2</h1><p>Retire the coal works. Keep every crew working.</p></div>
      <div class="ci-budget"><span>ONE SHARED CLEAN-ENERGY BUDGET</span><b></b><small></small></div></header>
      <div class="ci-rules"><b>${m.interaction==='full'?'Drag each green GRID SHARE card along its island rail.':'Click each island rail to set its requested GRID SHARE.'}</b>
        <span>Gold diamond = load · cyan ring = load in 1.5 s · green = actual supply. Batteries cover shortages. Empty battery = FAIL.</span></div>
      <main class="ci-ocean">${state.islands.map((s,i)=>`<article class="ci-island" data-island="${i}" style="--island-color:${s.color}">
        <div class="ci-land"><div class="ci-smoke">♧ ♧</div><div class="ci-factory">▥</div><div class="ci-turbine">✣</div><h2>${esc(s.name)}</h2><span>100 CREWS · COAL → CLEAN</span></div>
        <div class="ci-dispatch"><div class="ci-values"><b class="ci-load"></b><span class="ci-energy"></span></div>
          <div class="ci-rail" aria-label="${esc(s.name)} clean-grid share"><div class="ci-supply"></div>
            ${[0,25,50,75,100].map(v=>`<i class="ci-tick" style="left:${v}%"><span>${v}</span></i>`).join('')}
            ${[0,1,2,3].map(()=>'<i class="ci-trail"></i>').join('')}
            <div class="ci-demand">◆</div><div class="ci-forecast">◯<small>+1.5s</small></div>
            <button class="ci-policy" type="button" aria-label="${esc(s.name)} grid share">GRID<br>SHARE</button>
          </div></div>
        <div class="ci-battery"><span>BATTERY</span><div class="ci-cell"><i></i><b></b></div><small>MJ</small></div>
        </article>`).join('')}</main>
      <footer><div class="ci-progress"><i></i><span></span></div><div class="ci-actions"><button class="ci-launch">LAUNCH TRANSITION →</button><button class="ci-certify">CERTIFY NOW</button></div><p class="ci-status">Inspect and adjust before launch. First empty battery or rejected certification ends the episode.</p></footer>
      <section class="ci-verdict" hidden><span>THE ARCHIPELAGO / FINAL LEDGER</span><strong></strong><p></p></section>
    </section>`;
    document.querySelector('.ci-launch').addEventListener('click',launch);
    document.querySelector('.ci-certify').addEventListener('click',()=> {
      if (m.startedAt===null) launch();
      advance(); if (!m.terminal) finish(false,'Certification before the clean transition finished.');
    });
    document.querySelectorAll('.ci-rail').forEach((rail,i)=> {
      rail.addEventListener('pointerdown',e=> {
        if (e.button!==0 || m.terminal) return;
        advance(); if (m.terminal) return;
        if (m.interaction==='simplified') {e.preventDefault(); dispatch(i,point(rail,e));return;}
        if (!e.target.closest('.ci-policy')) return;
        e.preventDefault(); rail.setPointerCapture(e.pointerId);
        m.drag={i,pointer:e.pointerId,last:point(rail,e)};
        const r=rail.getBoundingClientRect();
        record('grab',{island:i,point:m.drag.last,rail_size:[r.width,r.height],input_source:'policy_drag'});
      });
      rail.addEventListener('pointermove',e=> {
        if (!m.drag || m.drag.i!==i || m.drag.pointer!==e.pointerId) return;
        const p=point(rail,e), old=m.drag.last;
        if (Math.abs(p[1])<=.5) {dispatch(i,p,old);m.drag.last=[m.targets[i]/100,p[1]];}
      });
      const release=e=> {
        if (!m.drag || m.drag.i!==i || m.drag.pointer!==e.pointerId) return;
        advance();
        const p=point(rail,e);
        if (Math.abs(p[1])<=.5 && Math.abs(p[0]*100-m.targets[i])>.00001) dispatch(i,p,m.drag.last);
        if (!m.terminal) {
          const r=rail.getBoundingClientRect();
          record('release',{island:i,point:p,rail_size:[r.width,r.height],input_source:'policy_drag'});
        }
        m.drag=null; if (rail.hasPointerCapture(e.pointerId)) rail.releasePointerCapture(e.pointerId);
      };
      rail.addEventListener('pointerup',release);
      rail.addEventListener('pointercancel',release);
      rail.addEventListener('lostpointercapture',release);
    });
    paint(); frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:'.ci-game',render};
})();
