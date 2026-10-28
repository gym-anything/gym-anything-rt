(() => {
  'use strict';
  let m, frame;
  const clock = () => m.startedAt === null ? 0 : Math.max(0, performance.now() - m.startedAt);
  function pose(w, ms) {
    const u = (Math.max(0, ms) + w.phase_ms) / w.span_ms;
    const i = Math.min(w.knots.length - 2, Math.floor(u)), f = Math.min(1, u - i);
    const s = f * f * (3 - 2 * f);
    return w.knots[i].map((a, j) => a + (w.knots[i + 1][j] - a) * s);
  }
  function seal(w, ms) {
    const [x, y, rail] = pose(w, ms), p = m.state.world.parameters;
    return [x + w.w - p.seal_size / 2 - 10 - p.rail_travel + rail, y + p.seal_size / 2 + 8];
  }
  function paneAt(p, ms) {
    for (const w of [...m.state.world.windows].sort((a, b) => b.z - a.z)) {
      if (m.closed.has(w.id)) continue;
      const [x, y] = pose(w, ms);
      if (p[0] >= x && p[0] <= x + w.w && p[1] >= y && p[1] <= y + w.h) return w;
    }
    return null;
  }
  function hit(p, ms) {
    const w = paneAt(p, ms), r = m.state.world.parameters.seal_size / 2;
    if (!w) return ['miss', null];
    const s = seal(w, ms);
    return Math.abs(p[0] - s[0]) <= r && Math.abs(p[1] - s[1]) <= r
      ? [w.trusted ? 'trusted' : 'close', w.id] : ['miss', w.id];
  }
  function record(kind, ms, extra = {}) {
    m.events.push({sequence:m.events.length + 1, kind, t_ms:ms, input_source:m.mode, ...extra});
  }
  function start() {
    if (m.startedAt !== null || m.terminal) return;
    m.startedAt = performance.now(); record('start', 0);
    document.querySelector('.pe2-start').disabled = true;
    m.helpers.setReadout('DESKTOP LIVE · INSPECT SEALED NOTICES BEFORE CLOSING', 'active');
  }
  function inspect(point) {
    if (m.terminal || m.startedAt === null || !point) return;
    const ms = clock();
    if (ms >= m.state.world.play_time_ms) { finish('INFESTATION NOT CLEARED'); return; }
    const w = paneAt(point, ms), role = w ? (w.trusted ? 'service' : 'haunt') : 'empty';
    record('inspect', ms, {point:[...point], window_id:w?.id || null, role,
      procedure:m.mode === 'full' ? 'context_inspect' : 'reticle_inspect'});
    if (w) m.inspected.add(w.id);
    m.helpers.setReadout(w ? (w.trusted ? 'INSPECTION · PROTECTED SERVICE · KEEP OPEN' : 'INSPECTION · HAUNTED PROCESS · CLOSE THIS WINDOW') : 'INSPECTION · EMPTY DESKTOP · NO SEAL SPENT', 'active');
  }
  async function finish(reason = '') {
    if (m.terminal) return;
    m.finalMs = Math.min(clock(), m.state.world.play_time_ms);
    m.terminal = true;
    document.querySelector('.pe2-fire').disabled = true;
    document.querySelector('.pe2-inspect').disabled = true;
    document.querySelector('.pe2-submit').disabled = true;
    const overlay = document.querySelector('.pe2-verdict');
    overlay.hidden = false;
    overlay.dataset.status = reason ? 'error' : 'pending';
    overlay.innerHTML = `<strong>${reason ? 'FAIL' : 'CLEAR'}</strong><span>${reason || 'CHECKING THE DESKTOP'}</span>`;
    m.helpers.setReadout(reason ? `FAIL · ${reason}` : 'VERIFYING…', reason ? 'error' : 'pending');
    try {
      const response = await fetch('/result', {method:'POST', headers:{'content-type':'application/json'},
        body:JSON.stringify({mechanic_id:m.state.mechanic_id, task_id:m.state.task_id,
          challenge_id:m.state.challenge_id, interaction_mode:m.mode, events:m.events,
          closed_ids:[...m.closed].sort(), misses:m.misses, final_t_ms:m.finalMs, completed:!reason})});
      const result = await response.json();
      m.serverResult = result;
      overlay.dataset.status = result.passed ? 'passed' : 'error';
      overlay.innerHTML = `<strong>${result.passed ? 'PASS' : 'FAIL'}</strong><span>${result.passed ? 'HAUNTED WINDOWS CLOSED · SERVICES SAFE' : reason || result.feedback || 'INCOMPLETE DESKTOP'}</span>`;
      m.helpers.setReadout(result.passed ? 'PASS · DESKTOP EXORCISED' : 'FAIL · EPISODE ENDED', result.passed ? 'passed' : 'error');
    } catch (error) {
      overlay.innerHTML = '<strong>ERROR</strong><span>VERIFICATION UNAVAILABLE</span>';
      m.helpers.setReadout(`VERIFIER ERROR · ${error.message}`, 'error');
    }
  }
  function fire(point) {
    if (m.terminal || m.startedAt === null || !point) return;
    const ms = clock();
    if (ms >= m.state.world.play_time_ms) { finish('INFESTATION NOT CLEARED'); return; }
    const [outcome, id] = hit(point, ms);
    record('fire', ms, {point:[...point], hit:outcome, window_id:id});
    m.flash = {point:[...point], ms, outcome};
    if (outcome === 'trusted') { finish('LOCKED SERVICE DESTROYED'); return; }
    if (outcome === 'close') m.closed.add(id);
    else m.misses += 1;
    if (m.misses >= m.state.world.miss_limit) { finish('FOUR WASTED SEALS'); return; }
    if (m.closed.size === m.state.world.parameters.haunted_count) finish();
    else m.helpers.setReadout(outcome === 'close' ? 'WINDOW CLOSED · THE STACK HAS CHANGED' : 'SEAL MISSED · CHECK THE CURRENT STACK', 'active');
  }
  function ghost(ctx, x, y, trusted, color) {
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(x, y, 10, Math.PI, 0); ctx.lineTo(x + 10, y + 12);
    ctx.lineTo(x + 5, y + 8); ctx.lineTo(x, y + 12); ctx.lineTo(x - 5, y + 8); ctx.lineTo(x - 10, y + 12); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#171428'; ctx.fillRect(x - 5, y - 1, 3, 5); ctx.fillRect(x + 2, y - 1, 3, 5);
    if (trusted) {ctx.strokeStyle = '#171428'; ctx.lineWidth = 2; ctx.strokeRect(x - 5, y + 3, 10, 7);}
  }
  function draw() {
    if (!m) return;
    const ctx = m.canvas.getContext('2d'), world = m.state.world;
    const ms = m.terminal ? m.finalMs : clock(), active = m.startedAt !== null;
    ctx.clearRect(0, 0, 1040, 460);
    const bg = ctx.createLinearGradient(0, 0, 1040, 460);
    bg.addColorStop(0, '#141728'); bg.addColorStop(1, '#102e36'); ctx.fillStyle = bg; ctx.fillRect(0, 0, 1040, 460);
    ctx.strokeStyle = '#83b6aa13'; ctx.lineWidth = 1;
    for (let x = 0; x < 1040; x += 40) {ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 460); ctx.stroke();}
    for (let y = 0; y < 460; y += 40) {ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(1040, y); ctx.stroke();}
    ctx.fillStyle = '#91a3b2'; ctx.font = '12px monospace'; ctx.fillText('GHOST DESKTOP // INSPECT THE NOTICE · CLOSE HAUNTS · KEEP SERVICES', 18, 23);
    for (const w of [...world.windows].sort((a, b) => a.z - b.z)) {
      if (m.closed.has(w.id)) continue;
      const [x, y] = pose(w, ms), size = world.parameters.seal_size, [sx, sy] = seal(w, ms);
      const known = m.inspected.has(w.id), service = known && w.trusted;
      ctx.shadowColor = '#02020a99'; ctx.shadowBlur = 16; ctx.shadowOffsetY = 5;
      ctx.fillStyle = service ? '#1a3644' : '#28233f'; ctx.fillRect(x, y, w.w, w.h);
      ctx.shadowBlur = 0; ctx.shadowOffsetY = 0;
      ctx.strokeStyle = service ? '#65c6df' : w.color; ctx.lineWidth = 2; ctx.strokeRect(x, y, w.w, w.h);
      ctx.fillStyle = service ? '#254a5b' : '#433653'; ctx.fillRect(x + 1, y + 1, w.w - 2, size + 16);
      ghost(ctx, x + 23, y + size + 35, service, service ? '#78d9ed' : w.color);
      ctx.fillStyle = '#e9e6ef'; ctx.font = 'bold 12px monospace';
      ctx.fillText(known ? (service ? 'KEEP SERVICE' : 'UNINVITED GUEST') : 'SEALED NOTICE', x + 43, y + size + 29);
      ctx.fillStyle = '#abaac0'; ctx.font = '11px monospace';
      ctx.fillText(known ? (service ? 'DO NOT CLOSE' : 'CLOSE THE HAUNT') : 'INSPECT TO IDENTIFY', x + 43, y + size + 47);
      // The full solid square is the exact replay hitbox. A seal slides on its
      // own rail while the entire containing window also moves.
      ctx.fillStyle = known ? (service ? '#143c51' : '#b3efba') : '#c6b98e';
      ctx.fillRect(sx - size / 2, sy - size / 2, size, size);
      ctx.strokeStyle = known ? (service ? '#86e1ef' : '#dcffe0') : '#f0deab'; ctx.lineWidth = 2;
      ctx.strokeRect(sx - size / 2, sy - size / 2, size, size);
      if (!known) {
        ctx.fillStyle = '#332f36'; ctx.font = 'bold 25px monospace'; ctx.textAlign = 'center';
        ctx.fillText('?', sx, sy + 8); ctx.textAlign = 'start';
      } else if (service) {
        ctx.strokeStyle = '#93e3ef'; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.arc(sx, sy - 4, 8, Math.PI, 0); ctx.stroke();
        ctx.fillStyle = '#93e3ef'; ctx.fillRect(sx - 11, sy - 4, 22, 18);
      } else {
        ctx.strokeStyle = '#253943'; ctx.lineWidth = 4;
        ctx.beginPath(); ctx.moveTo(sx - 10, sy - 10); ctx.lineTo(sx + 10, sy + 10); ctx.moveTo(sx + 10, sy - 10); ctx.lineTo(sx - 10, sy + 10); ctx.stroke();
      }
    }
    // Recent trajectory + a short forecast are explicitly visible evidence.
    // All outlines show geometry; the solid top window still owns every click.
    if (active) for (const w of world.windows) {
      if (m.closed.has(w.id)) continue;
      const color = m.inspected.has(w.id) && w.trusted ? '#6ec6e680' : `${w.color}bb`;
      ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.setLineDash([3, 6]);
      ctx.beginPath();
      for (let dt = -600; dt <= 1200; dt += 75) {const p = seal(w, Math.max(0, ms + dt)); if (dt === -600) ctx.moveTo(...p); else ctx.lineTo(...p);}
      ctx.stroke(); ctx.setLineDash([]);
      const p = seal(w, ms + 1200); ctx.strokeRect(p[0] - 5, p[1] - 5, 10, 10);
    }
    if (m.aim) {
      ctx.strokeStyle = '#fff1a8'; ctx.lineWidth = 1.5;
      const [x, y] = m.aim;
      ctx.beginPath(); ctx.arc(x, y, 13, 0, Math.PI * 2); ctx.moveTo(x - 22, y); ctx.lineTo(x + 22, y); ctx.moveTo(x, y - 22); ctx.lineTo(x, y + 22); ctx.stroke();
    }
    if (m.flash && ms - m.flash.ms < 650) {
      ctx.strokeStyle = m.flash.outcome === 'close' ? '#b3efba' : '#ff766f'; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(...m.flash.point, 22, 0, Math.PI * 2); ctx.stroke();
    }
    document.querySelector('.pe2-count').textContent = `${m.closed.size} / ${world.parameters.haunted_count}`;
    document.querySelector('.pe2-misses').textContent = `${m.misses} / ${world.miss_limit}`;
    document.querySelector('.pe2-life i').style.width = `${Math.max(0, 1 - ms / world.play_time_ms) * 100}%`;
    const forecast = document.querySelector('.pe2-forecast').getContext('2d');
    forecast.clearRect(0, 0, 208, 92);
    forecast.fillStyle = '#122332'; forecast.fillRect(0, 0, 208, 92);
    forecast.save(); forecast.scale(.2, .2);
    for (const w of [...world.windows].sort((a,b) => a.z-b.z)) {
      if (m.closed.has(w.id)) continue;
      const known = m.inspected.has(w.id), service = known && w.trusted;
      const future = active ? ms + world.preview_ms : ms;
      const [x,y] = pose(w, future), [sx,sy] = seal(w, future), size = world.parameters.seal_size;
      forecast.fillStyle = service ? '#1a3644' : '#28233f'; forecast.fillRect(x,y,w.w,w.h);
      forecast.lineWidth = 4; forecast.strokeStyle = service ? '#65c6df' : w.color; forecast.strokeRect(x,y,w.w,w.h);
      forecast.fillStyle = known ? (service ? '#70d7ea' : '#b3efba') : '#c6b98e'; forecast.fillRect(sx-size/2,sy-size/2,size,size);
    }
    forecast.restore();
    if (active && !m.terminal && ms >= world.play_time_ms) finish('INFESTATION NOT CLEARED');
    frame = requestAnimationFrame(draw);
  }
  function render(state, helpers) {
    cancelAnimationFrame(frame); document.body.dataset.mechanic = 'popup-exorcist-v2';
    m = {state, helpers, mode:state.control_condition?.interaction || 'full', startedAt:null,
      events:[], closed:new Set(), inspected:new Set(), aim:null, misses:0, terminal:false, armed:false};
    window.popupExorcistV3Model = m;
    helpers.app.innerHTML = `<section class="pe2-root">
      <header class="pe2-head"><div><p>AFTER HOURS / DESKTOP SANITATION</p><h1>Popup Exorcist V3</h1></div><span class="pe2-mark">◈<small>ONE EPISODE</small></span></header>
      <div class="pe2-rules"><b>Identify the sealed notices. Close haunted processes; keep protected services.</b> The top solid window owns each input.<br><span>${m.mode === 'full' ? 'Right-click a window to inspect safely; left-click its moving seal to close.' : 'Click to place a reticle. INSPECT or I identifies; EXORCISE or Space closes at the reticle.'} Inspection spends no seals. Motion continues; discovered roles stay visible.</span></div>
      <div class="pe2-stage"><canvas class="pe2-canvas" width="1040" height="460" aria-label="moving haunted desktop"></canvas><aside class="pe2-lookahead"><b>1.2 s AHEAD</b><canvas class="pe2-forecast" width="208" height="92" aria-label="forecast desktop with the same layers"></canvas><span>Same stack, ahead in time.<br>Trails end 1.2 seconds ahead.<br><br>? Uninspected<br>Green ×: close<br>Blue lock: keep<br><br>Four wasted seals or closing a service ends the episode.</span></aside><div class="pe2-verdict" hidden></div></div>
      <footer class="pe2-controls"><button class="pe2-start">OPEN DESKTOP</button><button class="pe2-inspect" ${m.mode === 'full' ? 'hidden' : ''}>INSPECT</button><button class="pe2-fire" ${m.mode === 'full' ? 'hidden' : ''}>EXORCISE</button><div><small>CLOSED</small><b class="pe2-count"></b></div><div><small>WASTED SEALS</small><b class="pe2-misses"></b></div><div class="pe2-life"><i></i></div><button class="pe2-submit">CERTIFY</button></footer>
      <div class="readout">OPEN THE DESKTOP · ONE FAILED EPISODE STAYS FAILED</div></section>`;
    m.canvas = document.querySelector('.pe2-canvas');
    const point = e => {const r = m.canvas.getBoundingClientRect(); return [(e.clientX - r.left) * 1040 / r.width, (e.clientY - r.top) * 460 / r.height];};
    m.canvas.onpointermove = e => {if (m.mode === 'full' && !m.terminal) m.aim = point(e);};
    m.canvas.onpointerdown = e => {if (e.button === 0 && !m.terminal) {e.preventDefault(); m.armed = true;}};
    m.canvas.onpointerup = e => {
      if (e.button !== 0 || !m.armed || m.terminal) return;
      m.armed = false;
      if (m.startedAt === null) return;
      m.aim = point(e);
      if (m.mode === 'full') fire(m.aim);
      else record('aim', clock(), {point:[...m.aim]});
    };
    m.canvas.onpointercancel = () => {m.armed = false;};
    m.canvas.oncontextmenu = e => {e.preventDefault(); if (m.mode === 'full') inspect(point(e));};
    document.querySelector('.pe2-start').onclick = start;
    document.querySelector('.pe2-inspect').onclick = () => inspect(m.aim);
    document.querySelector('.pe2-fire').onclick = () => fire(m.aim);
    document.querySelector('.pe2-submit').onclick = () => finish('UNCLEARED DESKTOP');
    document.onkeydown = e => {
      if (m.mode !== 'simplified' || e.repeat) return;
      if (e.code === 'Space') {e.preventDefault(); fire(m.aim);}
      if (e.code === 'KeyI') {e.preventDefault(); inspect(m.aim);}
    };
    frame = requestAnimationFrame(draw);
  }
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.popup_exorcist_v3 = {rootSelector:'.pe2-root', render};
})();
