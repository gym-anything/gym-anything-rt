(() => {
  "use strict";

  const DISC_IDS = ["north", "southwest", "southeast"];
  const DISC_SLOTS = [[3, 7, 6, 0, 5, 4], [3, 10, 9, 1, 8, 7], [3, 4, 12, 2, 11, 10]];
  let model = null, animationFrame = 0;
  const noise = (seed,n) => {let x=(seed ^ Math.imul(n+1,0x9e3779b9))>>>0; x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0; x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0; return ((x^(x>>>16))>>>0)/4294967295*2-1;};
  function integral(seed,t,span) {const u=Math.max(0,t)/span,n=Math.floor(u),f=u-n; let total=0; for(let k=0;k<n;k++) total+=(noise(seed,k)+noise(seed,k+1))/2; const a=noise(seed,n),b=noise(seed,n+1);return span*(total+a*f+(b-a)*(f**3-f**4/2));}
  const now = () => model.started ? Math.max(0,Math.round(performance.now()-model.startedAt)) : 0;
  function phase(d,t) {const r=model.state.rose,c=r.collars[d],raw=c.phase+c.direction*(r.collar_speed*t/1000+r.collar_amplitude*integral(c.seed,t,r.collar_span_ms)/1000);return ((raw+Math.PI)%(2*Math.PI)+2*Math.PI)%(2*Math.PI)-Math.PI;}
  function arc(cx,cy,r,a,b) {let delta=b-a;while(delta>Math.PI)delta-=2*Math.PI;while(delta<-Math.PI)delta+=2*Math.PI;return `M${cx+Math.cos(a)*r} ${cy+Math.sin(a)*r} A${r} ${r} 0 0 ${delta>=0?1:0} ${cx+Math.cos(b)*r} ${cy+Math.sin(b)*r}`;}
  function collarsMarkup() {return model.state.rose.discs.map((disc,d)=>{const [cx,cy]=disc.center,base=disc.handle_angle*Math.PI/180,h=model.state.rose.notch_half_width,r=disc.radius+8;return `<g class="moving-collar" data-collar="${d}"><circle cx="${cx}" cy="${cy}" r="${r}"/><path class="collar-notch" d="${arc(cx,cy,r,base-h,base+h)}"/><path class="collar-tail"/></g><path class="fixed-pin" d="M${cx+Math.cos(base)*(r-14)} ${cy+Math.sin(base)*(r-14)} L${cx+Math.cos(base)*(r+14)} ${cy+Math.sin(base)*(r+14)}"/>`;}).join('');}
  function refreshCollars() {const t=now(),r=model.state.rose;for(let d=0;d<3;d++){const disc=r.discs[d],[cx,cy]=disc.center,p=phase(d,t),base=disc.handle_angle*Math.PI/180,c=document.querySelector(`[data-collar="${d}"]`); if(c){c.querySelector('.collar-notch').setAttribute('d',arc(cx,cy,disc.radius+8,base+p-r.notch_half_width,base+p+r.notch_half_width));c.querySelector('.collar-tail').setAttribute('d',arc(cx,cy,disc.radius+8,base+phase(d,Math.max(0,t-600)),base+p));c.dataset.open=Math.abs(p)<=r.notch_half_width?'true':'false';}
      const dial=document.querySelector(`[data-dial="${d}"]`);if(dial){dial.querySelector('.dial-notch').setAttribute('d',arc(42,42,30,p-r.notch_half_width,p+r.notch_half_width));dial.querySelector('.dial-tail').setAttribute('d',arc(42,42,30,phase(d,Math.max(0,t-600)),p));dial.dataset.open=Math.abs(p)<=r.notch_half_width?'true':'false';dial.querySelector('text').textContent=r.collars[d].direction>0?'↻':'↺';}
    }const status=document.querySelector('#rose-status');if(status)status.textContent=model.cracked?'GLASS CRACKED':model.ready?'RESTORED — SEAL':!model.started?'INSPECT, THEN START':t-model.lastTurn<r.cooldown_ms?'DETENT SETTLING':'COLLARS RUNNING';
    const remain=document.querySelector('#rose-time');if(remain)remain.textContent=`${Math.max(0,Math.ceil((r.play_time_ms-t)/1000))}s`;
    if(model.started && !model.terminal && t>r.play_time_ms)submit('TIME EXPIRED');
  }
  function animate(){if(model){refreshCollars(); if(!model.terminal)animationFrame=requestAnimationFrame(animate);}}
  function start(){if(model.started||model.terminal)return;model.startedAt=performance.now();model.started=true;model.events.push({sequence:model.events.length+1,kind:'start',t_ms:0,input_source:'start_button'});document.querySelector('#rose-start').disabled=true;}


  const esc = value => String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const same = (left, right) => left.length === right.length && left.every((value, index) => value === right[index]);

  function legal(state, discIndex) {
    const slots = DISC_SLOTS[discIndex];
    const heartSlot = state.indexOf(3);
    return slots.includes(heartSlot) && [0, 1, 2].every(point => point === discIndex || !slots.includes(state.indexOf(point)));
  }

  function turn(state, discIndex, direction) {
    const slots = DISC_SLOTS[discIndex];
    const values = slots.map(slot => state[slot]);
    const shifted = direction === 1 ? values.slice(-1).concat(values.slice(0, -1)) : values.slice(1).concat(values.slice(0, 1));
    const next = state.slice();
    slots.forEach((slot, index) => { next[slot] = shifted[index]; });
    return next;
  }

  function pieceMarkup(piece, slot, compact = false) {
    const [x, y] = slot.center;
    const scale = compact ? 0.41 : 1;
    const lead = compact ? 4 : 5;
    const cls = `glass-piece piece-${piece.kind}`;
    let shape;
    if (piece.kind === "heart") {
      shape = `<path d="M0 31 C-43 4 -45 -32 -18 -39 C-2 -43 0 -27 0 -19 C0 -27 2 -43 18 -39 C45 -32 43 4 0 31 Z"/>`;
    } else if (piece.kind === "point") {
      shape = `<path d="M0 -49 L30 13 L0 43 L-30 13 Z"/>`;
    } else {
      shape = `<path d="M-36 -38 Q0 -54 36 -38 L31 15 Q24 41 0 50 Q-24 41 -31 15 Z"/>`;
    }
    const motif = Number(piece.motif || 0);
    const decoration = motif % 3 === 0
      ? `<path class="glass-vein" d="M-20 -20 L20 24 M18 -24 L-17 20"/>`
      : motif % 3 === 1
        ? `<circle class="glass-jewel" cx="0" cy="4" r="11"/><path class="glass-vein" d="M0 -31 V-8 M0 16 V35"/>`
        : `<path class="glass-vein" d="M-25 7 Q0 -17 25 7 Q0 31 -25 7 Z"/>`;
    return `<g class="${cls}" data-piece="${piece.id}" transform="translate(${x} ${y}) scale(${scale})" style="--glass:${esc(piece.glass)};--lead:${lead}px">${shape}${decoration}<text class="glass-id" x="0" y="9" text-anchor="middle">${piece.id < 3 ? ["N","W","E"][piece.id] : piece.id === 3 ? "♥" : ["","","","","✦","◈","✿","☽","◇","✣","✧","⊙","❖"][piece.id]}</text></g>`;
  }

  function patchMarkup(slot) {
    const [x,y] = slot.center;
    // Every cover has the same silhouette and paint: no underlying identity
    // is rendered until the player inspects this particular piece of glass.
    return `<g class="conservation-patch" data-slot="${slot.id}" transform="translate(${x} ${y})" role="button" aria-label="Lift conservation patch to inspect glass"><rect x="-39" y="-49" width="78" height="98" rx="8"/><path class="paper-fold" d="M18 -49 H39 V-28 Z"/><path class="paper-seam" d="M-30 -28 L28 24 M-28 24 L26 -28"/><text x="0" y="9" text-anchor="middle">?</text><text class="patch-label" x="0" y="35" text-anchor="middle">LIFT</text></g>`;
  }

  function glassFor(state, target = false) {
    const byId = new Map(model.state.rose.pieces.map(piece => [Number(piece.id), piece]));
    return state.map((pieceId, slotIndex) => target || model.revealed.has(pieceId)
      ? pieceMarkup(byId.get(Number(pieceId)), model.state.rose.slots[slotIndex], false)
      : patchMarkup(model.state.rose.slots[slotIndex])).join("");
  }

  function inspect(slotId) {
    if (model.terminal || model.submitting) return;
    const t=now();
    if(t>model.state.rose.play_time_ms){submit('TIME EXPIRED');return;}
    const pieceId=model.current[slotId];
    if (!Number.isInteger(slotId) || slotId<0 || slotId>=13 || model.revealed.has(pieceId)) return;
    model.revealed.add(pieceId);
    model.events.push({sequence:model.events.length+1,kind:'inspect',t_ms:t,input_source:'glass_patch',slot_id:slotId,piece_id:pieceId});
    updateVisible();
    refreshCollars();
  }

  function discRings(target = false) {
    return model.state.rose.discs.map(disc => `<circle class="disc-ring" data-disc-ring="${esc(disc.id)}" cx="${disc.center[0]}" cy="${disc.center[1]}" r="${disc.radius}"/>`).join("");
  }

  function handleMarkup(disc) {
    const angle = Number(disc.handle_angle) * Math.PI / 180;
    const radius = Number(disc.handle_radius || disc.radius);
    const x = Number(disc.center[0]) + Math.cos(angle) * radius;
    const y = Number(disc.center[1]) + Math.sin(angle) * radius;
    return `<g class="rose-handle" data-disc="${esc(disc.id)}" transform="translate(${x} ${y})"><circle r="20"/><circle r="9"/><path d="M-7 0 H7 M0 -7 V7"/></g>`;
  }

  function roseSvg(state, target = false) {
    return `<svg class="rose-svg${target ? " target-svg" : ""}" viewBox="180 18 640 510" role="img" aria-label="${target ? "Reference rose arrangement" : "Current bandaged rose"}">
      <defs><filter id="roseGlow"><feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
      <path class="stone-tracery" d="M500 25 C696 25 807 176 807 349 C807 482 695 520 500 520 C305 520 193 482 193 349 C193 176 304 25 500 25 Z"/>
      ${discRings(target)}
      ${target ? "" : collarsMarkup()}
      ${glassFor(state, target)}
      <circle class="rose-boss" cx="500" cy="300" r="15"/>
      ${target || model.interaction !== "full" ? "" : model.state.rose.discs.map(handleMarkup).join("")}
    </svg>`;
  }

  function controlsMarkup() {return `<div class="rose-button-bank">${model.state.rose.discs.map((disc,d)=>`<div class="collar-card"><div class="collar-title">${esc(disc.label)}</div><svg data-dial="${d}" viewBox="0 0 84 84"><circle cx="42" cy="42" r="30"/><path class="dial-notch"/><path class="dial-tail"/><path class="fixed-pin" d="M65 42 H81"/><text x="42" y="51" text-anchor="middle"></text></svg>${model.interaction==='simplified'?`<div class="disc-buttons"><button class="rose-turn-button" type="button" data-disc="${disc.id}" data-direction="-1">↶</button><button class="rose-turn-button" type="button" data-disc="${disc.id}" data-direction="1">↷</button></div>`:'<span class="rim-label">DRAG RIM ↶ ↷</span>'}</div>`).join('')}</div>`;}

  function updateVisible() {
    const mount = document.querySelector(".current-rose");
    if (mount) mount.innerHTML = roseSvg(model.current, false);
    model.ready = same(model.current, model.state.rose.solved_state);
    document.querySelectorAll('.conservation-patch').forEach(patch => patch.addEventListener('click', () => inspect(Number(patch.dataset.slot))));
    installHandles();
  }

  function attempt(discId, direction, inputSource, geometry={}) {
    if (!model.started || model.terminal || model.submitting) return;
    const d=DISC_IDS.indexOf(discId),t=now(); if(d<0||![-1,1].includes(direction))return;
    if(t>model.state.rose.play_time_ms){submit('TIME EXPIRED');return;}
    const before=model.current.slice();let outcome;
    if(!legal(before,d)){outcome='refused';model.refused++;}
    else if(t-model.lastTurn<model.state.rose.cooldown_ms){outcome='settling';model.refused++;}
    else if(Math.abs(phase(d,t))>model.state.rose.notch_half_width){outcome='cracked';model.cracked=true;}
    else{outcome='turned';model.current=turn(before,d,direction);model.successful++;model.lastTurn=t;}
    model.events.push({sequence:model.events.length+1,kind:'turn',t_ms:t,disc_id:discId,direction,input_source:inputSource,outcome,before_state:before,after_state:model.current.slice(),turns_after:model.successful,...geometry});
    if(outcome==='turned')updateVisible();
    refreshCollars(); if(model.cracked)submit('COLLAR CLOSED — GLASS CRACKED');
  }

  function svgPoint(svg, event) {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(svg.getScreenCTM().inverse());
  }

  function installHandles() {
    if (!model || model.interaction !== "full") return;
    document.querySelectorAll(".rose-handle").forEach(handle => {
      handle.addEventListener("pointerdown", event => {
        event.preventDefault();
        const svg = handle.closest("svg");
        const disc = model.state.rose.discs.find(item => item.id === handle.dataset.disc);
        if (!svg || !disc || !model.started || model.terminal || event.button !== 0) return;
        handle.setPointerCapture(event.pointerId);
        const start = svgPoint(svg, event);
        const initialAngle = Math.atan2(start.y - disc.center[1], start.x - disc.center[0]);
        const initialTransform = handle.getAttribute("transform");
        handle.classList.add("is-dragging");
        const move = moveEvent => {
          if (moveEvent.pointerId !== event.pointerId) return;
          moveEvent.preventDefault();
          const point = svgPoint(svg, moveEvent);
          const angle = Math.atan2(point.y - disc.center[1], point.x - disc.center[0]);
          const radius = Number(disc.handle_radius || disc.radius);
          const x = Number(disc.center[0]) + Math.cos(angle) * radius;
          const y = Number(disc.center[1]) + Math.sin(angle) * radius;
          handle.setAttribute("transform", `translate(${x} ${y})`);
        };
        const finish = (endEvent, cancelled) => {
          if (endEvent.pointerId !== event.pointerId) return;
          handle.removeEventListener("pointermove", move);
          handle.removeEventListener("pointerup", up);
          handle.removeEventListener("pointercancel", cancel);
          handle.classList.remove("is-dragging");
          handle.setAttribute("transform", initialTransform);
          if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
          if (cancelled) return;
          const end = svgPoint(svg, endEvent);
          let delta = Math.atan2(end.y - disc.center[1], end.x - disc.center[0]) - initialAngle;
          while (delta > Math.PI) delta -= Math.PI * 2;
          while (delta < -Math.PI) delta += Math.PI * 2;
          if (Math.abs(delta) >= 0.45) attempt(disc.id, delta > 0 ? 1 : -1, "rim_drag", {start_point:[start.x,start.y],end_point:[end.x,end.y]});
        };
        const up = endEvent => finish(endEvent, false);
        const cancel = endEvent => finish(endEvent, true);
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", up);
        handle.addEventListener("pointercancel", cancel);
      });
    });
  }

  async function submit(reason='') {
    if(model.terminal||model.submitting)return;model.submitting=true;model.terminal=true;
    const t=now(),completed=model.started&&!model.cracked&&same(model.current,model.state.rose.solved_state)&&t<=model.state.rose.play_time_ms;
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,interaction_mode:model.interaction,events:model.events,final_t_ms:t,final_state:model.current.slice(),successful_turns:model.successful,refused_turns:model.refused,cracked:model.cracked,completed};
    model.payload=payload;
    const root=document.querySelector('.bandaged-rose-captcha');
    if(reason || !completed){try{sessionStorage.setItem(model.failureKey,reason||'WINDOW INCOMPLETE');}catch(_){}}
    if(reason || !completed){root.classList.add('is-failed');document.querySelector('#rose-fail-reason').textContent=reason||'WINDOW INCOMPLETE';}
    try {const response=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)}),outcome=await response.json();model.serverGrade=outcome;
      if(outcome.passed!==true){try{sessionStorage.setItem(model.failureKey,'CERTIFICATION FAILED');}catch(_){}}
      root.classList.add(outcome.passed===true?'is-passed':'is-failed');model.helpers.setReadout(outcome.passed===true?'PASS':'FAIL',outcome.passed===true?'passed':'error');
    }catch(error){document.querySelector('#rose-fail-reason').textContent='VERIFIER ERROR';root.classList.add('is-failed');model.helpers.setReadout(`VERIFIER ERROR: ${error.message}`,'error');}
  }

  async function render(state, helpers) {
    cancelAnimationFrame(animationFrame);
    document.body.dataset.mechanic = "bandaged-rose-window-v3";
    const interaction = state.control_condition?.interaction || "full";
    model = {state, helpers, interaction, current: state.rose.initial_state.slice(), revealed:new Set(), successful: 0, refused: 0, events: [], ready: false, submitting: false, pendingState: null, started:false, startedAt:performance.now(), lastTurn:-1e9, terminal:false, cracked:false, failureKey:`bandaged_rose_window_v3:terminal:${state.task_id}:${location.search}`};
    helpers.app.innerHTML = `<main class="bandaged-rose-captcha" data-interaction="${esc(interaction)}">
      <header class="rose-header"><h1>Bandaged Rose Window V3</h1><p>Click paper patches to inspect glass; exposed pieces stay visible. Restore the reference; align each moving notch with its pin before turning.</p></header>
      <section class="rose-workbench">
        <aside class="reference-panel"><span class="panel-label">REFERENCE</span><div class="reference-rose">${roseSvg(state.rose.solved_state, true)}</div><p>A disc needs the heart and no foreign point.<br>N • W • E stay in their home circles.</p><p>Green notch at the pin: turn. Red: wait.<br>Hold and inspection never stop the collars.<br>One crack ends the episode.</p></aside>
        <section class="window-panel"><div class="arch-glow"></div><div class="current-rose">${roseSvg(model.current, false)}</div></section>
        <aside class="control-panel">${controlsMarkup()}<div class="readout" data-status="idle"></div><b id="rose-status">INSPECT, THEN START</b><small id="rose-time">300s</small><button id="rose-start">START COLLARS</button><button id="rose-certify" type="button">${esc(state.submit_label || "SEAL")}</button></aside>
      </section>
      <div class="rose-fail-card"><b>FAIL</b><span id="rose-fail-reason">WINDOW INCOMPLETE</span></div>
      <div class="rose-pass-card"><b>PASS</b></div>
    </main>`;
    document.querySelectorAll(".rose-turn-button").forEach(button => button.addEventListener("click", () => attempt(button.dataset.disc, Number(button.dataset.direction), "proxy_buttons")));
    document.querySelector("#rose-certify").addEventListener("click", () => submit());
    document.querySelector("#rose-start").addEventListener("click", start);
    updateVisible();
    window.bandagedRoseWindowV3Model = model;
    try{const failure=sessionStorage.getItem(model.failureKey);if(failure){model.terminal=true;document.querySelector('.bandaged-rose-captcha').classList.add('is-failed');document.querySelector('#rose-fail-reason').textContent=failure;}}catch(_){}
    refreshCollars();if(!model.terminal)animationFrame=requestAnimationFrame(animate);
  }

  window.bandagedRoseWindowV3Math={noise,integral,phase,legal,turn};
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.bandaged_rose_window_v3 = {render, rootSelector: ".bandaged-rose-captcha"};
})();
