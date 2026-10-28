(() => {
  'use strict';
  let model = null, frame = 0;
  const copy = x => JSON.parse(JSON.stringify(x));
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const rounded = x => Number(x.toFixed(3));
  const romans = ['I','II','III','IV','V','VI','VII','VIII','IX'];
  const escape = x => String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function center(border, t) {
    for(let index=0;index<border.knots.length-1;index++) {
      const [start,a]=border.knots[index], [end,b]=border.knots[index+1];
      if(start<=t && t<=end) {
        const f=(t-start)/(end-start);
        return border.base+a+(b-a)*f*f*(3-2*f);
      }
    }
    throw new Error('Task time left the generated census motion');
  }
  function worldTime(t) {
    return model.state.simulation.world_time_mode === 'parked_after_open' ? 0 : t;
  }
  function voterX(voter,t) {
    return voter.border === undefined ? voter.x : center(model.state.borders[voter.border],worldTime(t))+voter.offset;
  }
  function statistics() {
    const counts = Array.from({length:9}, () => ({gilt:0,tide:0,plum:0}));
    for (const voter of model.state.voters) {
      const x = voterX(voter,model.t_ms), row = voter.row;
      const column = Number(x >= model.boundaries[2*row]) + Number(x >= model.boundaries[2*row+1]);
      counts[row*3+column][voter.guild]++;
    }
    const populations = [], winners = [], holdings = {gilt:0,tide:0,plum:0};
    for (const values of counts) {
      populations.push(Object.values(values).reduce((a,b)=>a+b,0));
      const ordered = Object.keys(values).sort((a,b)=>values[b]-values[a]);
      const winner = values[ordered[0]] > values[ordered[1]] ? ordered[0] : 'tie';
      winners.push(winner); if (winner !== 'tie') holdings[winner]++;
    }
    const valid = populations.every(p=>p===model.state.population) && Object.keys(holdings).every(g=>holdings[g]===model.state.target_split[g]);
    return {populations,winners,holdings,valid};
  }
  function metrics() {
    return {t_ms:model.t_ms,charge_ms:rounded(model.charge_ms),valid_ms:model.valid_ms,
      boundaries:model.boundaries.map(rounded),status:model.status,census:statistics()};
  }
  function record(type, extra={}) {
    model.events.push({sequence:model.events.length+1,type,t_ms:model.t_ms,...extra});
  }
  function advance() {
    if (!model?.started || model.status !== 'active') return;
    const target = Math.floor((performance.now()-model.startedAt)/20)*20;
    while (model.t_ms < target && model.status === 'active') {
      model.t_ms += 20;
      const valid = statistics().valid;
      model.valid_ms += valid ? 20 : 0;
      model.charge_ms = valid ? model.charge_ms+20 : 0;
      if (model.charge_ms >= model.state.simulation.audit_ms) {
        model.charge_ms = model.state.simulation.audit_ms; model.status = 'success'; finish();
      } else if (model.t_ms >= model.state.simulation.deadline_ms) {
        model.status = 'failure'; finish('CENSUS EXPIRED');
      }
    }
  }
  async function finish(reason='') {
    if (model.submitted) return;
    model.submitted = true; model.drag = null;
    draw();
    document.querySelector('.census-verdict').textContent = reason ? `FAIL · ${reason}` : 'RATIFIED · VERIFYING';
    document.querySelector('.census-verdict').hidden = false;
    try {
      const response = await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({
        mechanic_id:model.state.mechanic_id,revision:model.state.revision,
        task_id:model.state.task_id,challenge_id:model.state.challenge_id,
        interaction_mode:model.mode,events:model.events,final_t_ms:model.t_ms,
        metrics:metrics(),completed:model.status==='success'})});
      const result = await response.json();
      model.serverGrade = result;
      document.querySelector('.census-verdict').textContent = result.passed ? 'PASS · CHARTER RATIFIED' : `FAIL · ${reason || 'ATTEMPT ENDED'}`;
      document.querySelector('.census-verdict').dataset.outcome = result.passed ? 'pass' : 'fail';
      model.helpers.setReadout(result.passed ? 'PASS' : 'FAIL',result.passed ? 'passed' : 'error');
    } catch (error) {
      document.querySelector('.census-verdict').textContent = 'VERIFIER ERROR';
      model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`,'error');
    }
  }
  function setBorder(index, x) {
    advance();
    if (model.submitted) return;
    const low = index%2 ? 580 : 220, high = index%2 ? 820 : 460;
    x = rounded(clamp(x,low,high));
    if (x === model.boundaries[index]) return;
    record('target',{border:index,x,input_source:model.mode==='full'?'border_handle_drag':'border_ruler_click'});
    model.boundaries[index] = x; draw();
  }
  function inspectRow(row) {
    advance();
    if (model.submitted || model.drag || model.inspected[row]) return;
    record('inspect',{row,input_source:'census_folio_click'});
    model.inspected[row] = true;
    draw();
  }
  function coordinates(event) {
    const rect = document.querySelector('#census-map').getBoundingClientRect();
    return [(event.clientX-rect.left)*1040/rect.width,(event.clientY-rect.top)*570/rect.height];
  }
  function draw() {
    if (!model) return;
    const svg = document.querySelector('#census-map'); if (!svg) return;
    const state = model.state, stats = statistics();
    let markup = `<defs><pattern id="census-paper" width="26" height="26" patternUnits="userSpaceOnUse"><path d="M26 0H0V26" fill="none" stroke="#71684a" opacity=".12"/></pattern></defs>`;
    for (let row=0;row<3;row++) {
      const cuts = [0,model.boundaries[2*row],model.boundaries[2*row+1],1040];
      for (let column=0;column<3;column++) {
        const canton = row*3+column, x = cuts[column], width = cuts[column+1]-x;
        markup += `<rect x="${x}" y="${row*190}" width="${width}" height="190" fill="${state.colors[canton]}" fill-opacity=".62" stroke="#474a40" stroke-width="1.5"/><text x="${x+width/2}" y="${row*190+26}" text-anchor="middle" class="census-label">${romans[canton]}</text>`;
      }
    }
    markup += `<rect width="1040" height="570" fill="url(#census-paper)" pointer-events="none"/>`;
    for (const voter of state.voters) {
      // The field folio contains the migrating households' locations and
      // affiliations. Once inspected, its live map stays visible permanently.
      if (voter.border !== undefined && !model.inspected[voter.row]) continue;
      const x = voterX(voter,model.t_ms), y = voter.row*190+voter.y;
      const color = state.guilds.find(g=>g.id===voter.guild).color;
      if (voter.border !== undefined) {
        const past = voterX(voter,Math.max(0,model.t_ms-500));
        const recent = voterX(voter,Math.max(0,model.t_ms-200));
        markup += `<line x1="${past}" y1="${y}" x2="${x}" y2="${y}" stroke="${color}" stroke-width="4" opacity=".25"/>`;
        const delta = x-recent;
        if (Math.abs(delta)>0.4) {
          const end = x + clamp(delta*2,-32,32);
          markup += `<path d="M${x} ${y} H${end} l${delta>0?-5:5} -4 m${delta>0?5:-5} 4 l${delta>0?-5:5} 4" fill="none" stroke="${color}" stroke-width="2"/>`;
        }
      }
      markup += `<g data-house="${escape(voter.id)}" transform="translate(${x} ${y})" pointer-events="none"><circle r="10" fill="${color}" stroke="#fff7df" stroke-width="2"/><path d="M-5 0L0-5L5 0V5H-5Z" fill="#fff4d2"/><circle r="2" fill="${color}"/></g>`;
    }
    for (const border of state.borders) {
      const index = border.id, y = border.row*190, x = model.boundaries[index];
      const low=index%2?580:220, high=index%2?820:460;
      markup += `<line x1="${x}" y1="${y+32}" x2="${x}" y2="${y+142}" stroke="#153a45" stroke-width="4"/><line x1="${low}" y1="${y+164}" x2="${high}" y2="${y+164}" stroke="#8b7650" stroke-width="2"/><rect data-ruler="${index}" x="${low}" y="${y+146}" width="${high-low}" height="38" fill="transparent"/><g data-handle="${index}" transform="translate(${x} ${y+164})"><circle r="17" fill="#193c48" stroke="#f3d895" stroke-width="3"/><path d="M-8 0H8M-8 0l4-4M-8 0l4 4M8 0l-4-4M8 0l-4 4" stroke="#f9e5b9" stroke-width="2" fill="none"/></g>`;
    }
    for (let row=0;row<3;row++) {
      const filed = model.inspected[row];
      markup += `<g class="census-folio" data-folio="${row}" data-filed="${filed}" transform="translate(12 ${row*190+145})" role="img" aria-label="${filed?'Inspected':'Folded'} census folio ${romans[row*3]} to ${romans[row*3+2]}"><path d="M0 0H148L160 12V34H0Z"/><path d="M148 0V12H160" fill="none"/><text x="8" y="14">${filed?'FILED':'CENSUS FOLIO'} · ${romans[row*3]}–${romans[row*3+2]}</text><text x="8" y="27">${filed?'LIVE HOUSEHOLD MAP':'CLICK TO INSPECT'}</text></g>`;
    }
    svg.innerHTML = markup;
    for(let canton=0;canton<9;canton++) {
      const cell = document.querySelector(`[data-ledger="${canton}"]`);
      const visible = model.inspected[Math.floor(canton/3)];
      cell.dataset.valid = visible ? String(stats.populations[canton]===state.population) : 'unknown';
      cell.querySelector('b').textContent = `${visible?stats.populations[canton]:'?'} / ${state.population}`;
      cell.querySelector('em').textContent = visible ? stats.winners[canton].toUpperCase() : 'SEALED';
      cell.querySelector('em').style.color = visible ? (state.guilds.find(g=>g.id===stats.winners[canton])?.color || '#a44232') : '#806d44';
    }
    document.querySelector('#census-seats').textContent = model.inspected.every(Boolean) ? `${stats.holdings.gilt} GILT / ${stats.holdings.tide} TIDE / ${stats.holdings.plum} PLUM` : 'FIELD FOLIOS NOT YET INSPECTED';
    document.querySelector('#census-progress').style.width = `${100*model.charge_ms/30000}%`;
    document.querySelector('#census-charge').textContent = `${(model.charge_ms/1000).toFixed(1)} / 30.0 s`;
    document.querySelector('#census-phase').textContent = model.status==='ready' ? 'INSPECTION · CENSUS NOT OPEN' : model.status==='active' ? (stats.valid?'BALANCED · RATIFYING':'UNBALANCED · AUDIT STREAK RESET') : model.status.toUpperCase();
    document.querySelector('#census-time').textContent = `${Math.max(0,(120000-model.t_ms)/1000).toFixed(1)} s`;
    document.querySelector('#census-start').disabled = model.started || model.submitted;
    document.querySelector('#census-seal').disabled = model.submitted;
  }
  function animate() { advance(); draw(); frame=requestAnimationFrame(animate); }
  async function render(state,helpers) {
    cancelAnimationFrame(frame);
    document.body.dataset.mechanic = 'charter-census-v2';
    model = {state:copy(state),helpers,mode:state.control_condition?.interaction || 'full',
      boundaries:state.borders.map(b=>b.initial),events:[],t_ms:0,charge_ms:0,valid_ms:0,
      started:false,status:'ready',startedAt:0,drag:null,submitted:false,serverGrade:null,inspected:[false,false,false]};
    // Privileged diagnostics are read-only oracle planning; screenshot players never use this.
    window.charterCensusV3Model = model;
    helpers.app.innerHTML = `<section class="charter-census-v2" data-mode="${model.mode}">
      <header><div><small>OFFICE OF THE LIVING CADASTRE</small><h1>Charter of the Nine Cantons</h1><p>Connected regions · Equal populations · 5 Gilt / 2 Tide / 2 Plum</p></div><div class="census-seal-art">IX<br><small>CANTONS</small></div></header>
      <div class="census-rules">${model.mode==='full'?'Drag border handles along their rails.':'Click border rails to set their positions.'} Inspect folded folios for household maps and registers; they stay visible. Centers set canton membership; trails span 0.5 s. Open the census: balance populations and holdings for 30 continuous seconds. Imbalance resets the streak; correct it to recover. Early sealing or 120 s expiry ends the attempt.</div>
      <main><div class="census-atlas"><svg id="census-map" viewBox="0 0 1040 570" preserveAspectRatio="none" role="application" aria-label="Connected canton map and six border rails"></svg><div class="census-legend"><span style="color:#ad7714">● GILT</span><span style="color:#14778c">● TIDE</span><span style="color:#963c68">● PLUM</span><span>Each house = one household</span></div></div>
      <aside><small>HOUSEHOLD REGISTER</small><div class="census-ledger">${romans.map((name,index)=>`<article data-ledger="${index}"><span>${name}</span><b></b><em></em></article>`).join('')}</div><div class="census-seat-panel"><small>CURRENT HOLDINGS</small><b id="census-seats"></b><small>REQUIRED: 5 / 2 / 2</small></div><small id="census-phase"></small><div class="census-progress"><i id="census-progress"></i></div><b id="census-charge"></b></aside></main>
      <footer><span>CENSUS ALLOWANCE <b id="census-time"></b></span><strong class="readout"></strong><button id="census-start">OPEN CENSUS</button><button id="census-seal">SEAL CHARTER</button></footer><div class="census-verdict" hidden></div></section>`;
    const svg = document.querySelector('#census-map');
    svg.addEventListener('pointerdown',event=>{
      if(model.submitted || event.button!==0) return;
      advance(); if(model.submitted) return;
      const [x,y] = coordinates(event);
      const row = Math.floor(y/190), localY=y-row*190;
      if(row>=0&&row<3&&x>=12&&x<=172&&localY>=145&&localY<=179) {inspectRow(row);return;}
      if(row<0||row>2||localY<146||localY>184) return;
      const index = row*2+(x>520?1:0), low=index%2?580:220, high=index%2?820:460;
      if(x<low||x>high) return;
      if(model.mode==='simplified') {setBorder(index,x);return;}
      if(Math.hypot(x-model.boundaries[index],localY-164)>23) return;
      event.preventDefault(); svg.setPointerCapture(event.pointerId);
      model.drag={index,pointer:event.pointerId};
      record('drag_begin',{border:index,x:rounded(x),input_source:'border_handle_drag'});
    });
    svg.addEventListener('pointermove',event=>{
      if(model.drag?.pointer===event.pointerId && !model.submitted) setBorder(model.drag.index,coordinates(event)[0]);
    });
    function release(event) {
      if(model.drag?.pointer!==event.pointerId || model.submitted) return;
      setBorder(model.drag.index,coordinates(event)[0]);
      if(model.submitted) return;
      record('drag_end',{border:model.drag.index,input_source:'border_handle_drag'});model.drag=null;
      if(svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    }
    svg.addEventListener('pointerup',release);svg.addEventListener('pointercancel',release);
    svg.addEventListener('lostpointercapture',event=>{
      if(model.drag?.pointer===event.pointerId && !model.submitted) {record('drag_end',{border:model.drag.index,input_source:'border_handle_drag'});model.drag=null;}
    });
    document.querySelector('#census-start').addEventListener('click',()=>{
      if(model.started||model.submitted||model.drag) return;
      record('start',{input_source:'open_census_button'});model.started=true;model.status='active';model.startedAt=performance.now();draw();
    });
    document.querySelector('#census-seal').addEventListener('click',()=>{
      advance(); if(model.submitted) return;
      record('certify',{input_source:'seal_charter_button'});model.status='failure';finish('INCOMPLETE CHARTER');
    });
    draw();frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.charter_of_the_nine_cantons_v3_nonrealtime={rootSelector:'.charter-census-v2',render};
})();
