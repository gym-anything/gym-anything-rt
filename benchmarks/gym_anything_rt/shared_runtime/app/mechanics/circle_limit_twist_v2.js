(() => {
  "use strict";

  const SIZE = 900;
  const ORIGIN = SIZE / 2;
  const DISC_RADIUS = 420;
  // Shared with the Python replay grader: 1/4096 canvas pixel, closed edges,
  // and last-drawn face priority. Hit testing does not depend on Canvas's
  // backend path precision. All integer cross products stay below 2**53.
  const HIT_SCALE = DISC_RADIUS * 4096;
  const IDENTITY = [[1, 0], [0, 0], [0, 0], [1, 0]];
  let model = null, frame = 0;

  const clone = value => JSON.parse(JSON.stringify(value));
  const c = (x, y = 0) => [Number(x), Number(y)];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
  const mul = (a, b) => [a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0]];
  const div = (a, b) => {
    const denominator = b[0] * b[0] + b[1] * b[1];
    return [(a[0] * b[0] + a[1] * b[1]) / denominator, (a[1] * b[0] - a[0] * b[1]) / denominator];
  };
  const conj = z => [z[0], -z[1]];
  const magnitude = z => Math.hypot(z[0], z[1]);
  const scale = (z, amount) => [z[0] * amount, z[1] * amount];
  const multiply = (left, right) => {
    const [a, b, cc, d] = left;
    const [e, f, g, h] = right;
    const product = [add(mul(a, e), mul(b, g)), add(mul(a, f), mul(b, h)), add(mul(cc, e), mul(d, g)), add(mul(cc, f), mul(d, h))];
    // Homogeneous matrix scale has no geometric effect. Keep it bounded so
    // harmless reversible steering cannot underflow the view representation.
    const norm = Math.max(...product.map(magnitude));
    if (!Number.isFinite(norm) || norm === 0) throw new Error("invalid view matrix");
    return product.map(value => scale(value, 1 / norm));
  };
  const applyView = (matrix, point) => div(add(mul(matrix[0], point), matrix[1]), add(mul(matrix[2], point), matrix[3]));
  const phi = point => [c(1), scale(point, -1), scale(conj(point), -1), c(1)];
  const inversePhi = point => [c(1), point.slice(), conj(point), c(1)];
  const translation = (start, end) => multiply(inversePhi(end), phi(start));
  function panView(view, history, start, end) {
    // Exact inverse gestures restore the saved homogeneous representation.
    // This avoids cancellation after long rim excursions without snapping
    // nearby inputs or changing their mathematical transformation.
    const last = history.at(-1), equal = (a,b) => a[0] === b[0] && a[1] === b[1];
    if (last && equal(start,last.end) && equal(end,last.start))
      return {view:clone(last.before),history:history.slice(0,-1)};
    return {view:multiply(translation(start,end),view),
      history:history.concat([{start:start.slice(),end:end.slice(),before:clone(view)}])};
  }
  const toCanvas = point => [ORIGIN + point[0] * DISC_RADIUS, ORIGIN + point[1] * DISC_RADIUS];
  const sameState = (left, right) => JSON.stringify(left) === JSON.stringify(right);
  const escaped = value => String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

  function geodesicPoint(first, second, t) {
    if (t === 0) return first.slice();
    if (t === 1) return second.slice();
    const mapped = applyView(phi(first), second);
    const length = magnitude(mapped);
    if (length < 1e-9) return first.slice();
    const bounded = Math.min(length, 0.999999);
    const radial = Math.tanh(t * Math.atanh(bounded)) / length;
    return applyView(inversePhi(first), scale(mapped, radial));
  }

  const hitPoint = point => point.map(value => Math.floor(value * HIT_SCALE + .5));
  const hitCanvas = point => [ORIGIN + point[0] / 4096, ORIGIN + point[1] / 4096];
  function facePolygon(vertices, view) {
    return vertices.flatMap((first, index) => Array.from({length:8}, (_, step) =>
      hitPoint(applyView(view, geodesicPoint(first, vertices[(index + 1) % vertices.length], step / 8)))));
  }
  function polygonContains(polygon, point) {
    let inside = false;
    for (let i = 0; i < polygon.length; i++) {
      const a = polygon[i], b = polygon[(i + 1) % polygon.length];
      const cross = (b[0]-a[0])*(point[1]-a[1]) - (b[1]-a[1])*(point[0]-a[0]);
      if (cross === 0 && Math.min(a[0],b[0]) <= point[0] && point[0] <= Math.max(a[0],b[0]) &&
          Math.min(a[1],b[1]) <= point[1] && point[1] <= Math.max(a[1],b[1])) return true;
      if ((a[1] > point[1]) !== (b[1] > point[1]) && (cross > 0) === (b[1] > a[1])) inside = !inside;
    }
    return inside;
  }
  function hitFace(polygons, point) {
    const sampled = hitPoint(point);
    for (const face of polygons.slice().reverse())
      if (polygonContains(face.polygon, sampled)) return Number(face.id);
    return null;
  }
  function faceAtPoint(puzzle, view, point) {
    return hitFace(puzzle.faces.map(face => ({id:face.id, polygon:facePolygon(face.vertices,view)})),point);
  }
  function traceGeodesic(path, first, second, firstPoint) {
    for (let step = firstPoint ? 0 : 1; step <= 8; step += 1) {
      const point = hitCanvas(hitPoint(applyView(model.view, geodesicPoint(first, second, step / 8))));
      if (step === 0 && firstPoint) path.moveTo(point[0], point[1]);
      else path.lineTo(point[0], point[1]);
    }
  }

  function polygonPath(vertices, polygon = facePolygon(vertices, model.view)) {
    const path = new Path2D();
    polygon.forEach((point, index) => index ? path.lineTo(...hitCanvas(point)) : path.moveTo(...hitCanvas(point)));
    path.closePath();
    return path;
  }

  function wedgePath(face, sector) {
    const center = face.center;
    const first = face.vertices[sector];
    const second = face.vertices[(sector + 1) % face.vertices.length];
    const path = new Path2D();
    traceGeodesic(path, center, first, true);
    traceGeodesic(path, first, second, false);
    traceGeodesic(path, second, center, false);
    path.closePath();
    return path;
  }

  function motif(ctx, face, sector, path, color) {
    ctx.save();
    ctx.clip(path);
    const center = toCanvas(applyView(model.view, geodesicPoint(face.center, geodesicPoint(face.vertices[sector], face.vertices[(sector + 1) % 7], 0.5), 0.57)));
    ctx.translate(center[0], center[1]);
    ctx.rotate((sector / 7) * Math.PI * 2 + 0.2);
    ctx.globalAlpha = 0.42;
    ctx.strokeStyle = color.glint;
    ctx.lineWidth = 2;
    const motifIndex = Number(color.motif) % 3;
    if (motifIndex === 0) {
      ctx.beginPath(); ctx.moveTo(-14, -4); ctx.lineTo(14, 4); ctx.stroke();
    } else if (motifIndex === 1) {
      ctx.beginPath(); ctx.arc(0, 0, 6, 0, Math.PI * 2); ctx.stroke();
    } else {
      ctx.beginPath(); ctx.moveTo(-9, 5); ctx.lineTo(0, -7); ctx.lineTo(9, 5); ctx.stroke();
    }
    ctx.restore();
  }

  function draw() {
    if (!model?.ctx) return;
    const ctx = model.ctx;
    ctx.clearRect(0, 0, SIZE, SIZE);
    const disc = new Path2D();
    disc.arc(ORIGIN, ORIGIN, DISC_RADIUS, 0, Math.PI * 2);
    ctx.save();
    ctx.clip(disc);

    const sky = ctx.createRadialGradient(ORIGIN - 95, ORIGIN - 140, 25, ORIGIN, ORIGIN, DISC_RADIUS);
    sky.addColorStop(0, "#24313a");
    sky.addColorStop(0.56, "#111b22");
    sky.addColorStop(1, "#060a0d");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, SIZE, SIZE);

    const byTile = new Map(model.puzzle.faces.map(face => [Number(face.tile_id), face]));
    const sortedTiles = model.puzzle.tiles.slice().sort((left, right) => right.depth - left.depth);
    for (const tile of sortedTiles) {
      if (byTile.has(Number(tile.id))) continue;
      const path = polygonPath(tile.vertices);
      const center = applyView(model.view, tile.center);
      const haze = Math.max(0, Math.min(1, 1 - magnitude(center)));
      ctx.fillStyle = `rgba(26, ${31 + Math.round(haze * 13)}, ${35 + Math.round(haze * 16)}, .74)`;
      ctx.fill(path);
      ctx.strokeStyle = tile.depth === 3 ? "rgba(148,117,72,.16)" : "rgba(178,143,88,.25)";
      ctx.lineWidth = tile.depth === 3 ? 1 : 1.6;
      ctx.stroke(path);
    }

    model.facePaths = [];
    for (const face of model.puzzle.faces) {
      const polygon = facePolygon(face.vertices, model.view);
      const facePath = polygonPath(face.vertices, polygon);
      model.facePaths.push({id: Number(face.id), path: facePath, polygon, center: applyView(model.view, face.center)});
      for (let sector = 0; sector < 7; sector += 1) {
        const path = wedgePath(face, sector);
        const color = model.palette[model.current[face.id][sector]];
        const center = toCanvas(applyView(model.view, face.center));
        const edge = toCanvas(applyView(model.view, face.vertices[sector]));
        const glow = Math.max(12, Math.min(180, Math.hypot(edge[0] - center[0], edge[1] - center[1])));
        const gradient = ctx.createRadialGradient(center[0] - glow * .18, center[1] - glow * .22, 1, center[0], center[1], glow);
        gradient.addColorStop(0, color.glint);
        gradient.addColorStop(.42, color.fill);
        gradient.addColorStop(1, color.fill);
        ctx.fillStyle = gradient;
        ctx.fill(path);
        ctx.strokeStyle = "rgba(16,14,13,.72)";
        ctx.lineWidth = 1.5;
        ctx.stroke(path);
        motif(ctx, face, sector, path, color);
      }
      const pointed = Number(face.id) === model.focusedFace || Number(face.id) === model.hoveredFace;
      ctx.strokeStyle = pointed ? "#fff0a6" : "rgba(220,180,102,.74)";
      ctx.lineWidth = pointed ? 4 : 2.2;
      ctx.stroke(facePath);
    }

    // Show the actual permutation cycles, not an inferred adjacency rule.
    // Hovering or selecting reveals the same two cycles in either input mode.
    const previewFace = model.hoveredFace ?? model.focusedFace;
    if (previewFace != null) {
      const definition = model.puzzle.twist_cycles[String(previewFace)];
      for (const name of ["own", "ring"]) {
        const points = [];
        for (const [faceId, sector] of definition[name]) {
          const face = model.puzzle.faces[faceId];
          const path = wedgePath(face, sector);
          ctx.strokeStyle = name === "own" ? "#f8efb4" : "#80f0dc";
          ctx.lineWidth = 3;
          ctx.stroke(path);
          const midpoint = geodesicPoint(face.vertices[sector], face.vertices[(sector + 1) % 7], .5);
          points.push(toCanvas(applyView(model.view, geodesicPoint(face.center, midpoint, .57))));
        }
        ctx.strokeStyle = name === "own" ? "rgba(248,239,180,.75)" : "rgba(128,240,220,.85)";
        ctx.lineWidth = 1.6;
        ctx.setLineDash([5, 6]);
        ctx.beginPath(); points.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p));
        ctx.closePath();ctx.stroke();ctx.setLineDash([]);
        points.forEach((p, i) => {
          const q = points[(i + 1) % points.length];
          const angle = Math.atan2(q[1] - p[1], q[0] - p[0]);
          const x = p[0] * .35 + q[0] * .65, y = p[1] * .35 + q[1] * .65;
          ctx.beginPath();ctx.moveTo(x, y);
          ctx.lineTo(x - 10 * Math.cos(angle - .4), y - 10 * Math.sin(angle - .4));
          ctx.moveTo(x, y);ctx.lineTo(x - 10 * Math.cos(angle + .4), y - 10 * Math.sin(angle + .4));ctx.stroke();
        });
      }
    }
    const aperture = model.puzzle.activation_radius * DISC_RADIUS;
    ctx.setLineDash([8, 9]);
    ctx.strokeStyle = "rgba(255,230,149,.65)";
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(ORIGIN, ORIGIN, aperture, 0, Math.PI * 2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    ctx.strokeStyle = "#9b7742";
    ctx.lineWidth = 14;
    ctx.beginPath(); ctx.arc(ORIGIN, ORIGIN, DISC_RADIUS + 7, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = "rgba(255,226,157,.52)";
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(ORIGIN, ORIGIN, DISC_RADIUS - 2, 0, Math.PI * 2); ctx.stroke();
  }


  function noise(seed, index) {
    let x=(seed ^ Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;
  }
  function flowPoint(spec,time,motor=null) {
    if(motor) {
      const elapsed=Math.max(0,time-motor.anchor_time_ms),pulse=1200;
      const u=elapsed<pulse?elapsed/pulse:1+(elapsed-pulse)/spec.span_ms,n=Math.floor(u),f=u-n,s=f*f*(3-2*f);
      return [0,1].map(axis=> {
        const seed=spec.seed+axis*7919,base=motor.epoch*104729;
        const a=n===0?motor.anchor[axis]:spec.amplitude/Math.sqrt(2)*noise(seed,base+n);
        const b=spec.amplitude/Math.sqrt(2)*noise(seed,base+n+1);
        return a+(b-a)*s;
      });
    }
    const u=Math.max(0,time)/spec.span_ms,n=Math.floor(u),f=u-n,s=f*f*(3-2*f);
    return [0,1].map(axis=> {
      const seed=spec.seed+axis*7919,a=noise(seed,n),b=noise(seed,n+1);
      return spec.amplitude/Math.sqrt(2)*(a+(b-a)*s);
    });
  }
  const flowView=(user,spec,time,motor=null)=>multiply(user,inversePhi(flowPoint(spec,time,motor)));
  const now=()=>Math.min(model.puzzle.play_time_ms,Math.max(0,Math.round(performance.now()-model.startedAt)));
  function canvasPoint(event) {
    const r=model.canvas.getBoundingClientRect();
    return [(event.clientX-r.left)*SIZE/r.width,(event.clientY-r.top)*SIZE/r.height];
  }
  function discPoint(event) {
    const p=canvasPoint(event);return [(p[0]-ORIGIN)/DISC_RADIUS,(p[1]-ORIGIN)/DISC_RADIUS];
  }
  function faceAt(event) {
    return hitFace(model.facePaths,discPoint(event));
  }
  const record=(kind,t,details)=>model.events.push({sequence:model.events.length+1,kind,t_ms:t,...details});
  function drawForecast(time) {
    const ctx=model.flowCtx,W=260,H=170,x=p=>W/2+p[0]*145,y=p=>H/2+p[1]*145;
    ctx.clearRect(0,0,W,H);ctx.fillStyle='#0b151b';ctx.fillRect(0,0,W,H);
    ctx.strokeStyle='#28353c';ctx.lineWidth=1;
    for(let i=-2;i<=2;i++) {
      ctx.beginPath();ctx.moveTo(W/2+i*34,0);ctx.lineTo(W/2+i*34,H);ctx.stroke();
      ctx.beginPath();ctx.moveTo(0,H/2+i*34);ctx.lineTo(W,H/2+i*34);ctx.stroke();
    }
    for(const [from,to,color] of [[Math.max(0,time-500),time,'#82705a'],[time,time+900,'#62e3cc']]) {
      ctx.beginPath();for(let t=from;t<=to;t+=25) {
        const priorMotor=model.motors.slice().reverse().find(m=>m.anchor_time_ms<=t)||null;
        const p=flowPoint(model.puzzle.flow,t,priorMotor); if(t===from)ctx.moveTo(x(p),y(p));else ctx.lineTo(x(p),y(p));
      }
      ctx.lineWidth=2.5;ctx.strokeStyle=color;ctx.stroke();
    }
    // Distinct time markers make the forecast readable even when the path
    // bends back over itself. Both input surfaces get the same prediction.
    for(const offset of [0,450,900]) {
      const p=flowPoint(model.puzzle.flow,time+offset,model.motor),px=x(p),py=y(p);
      ctx.beginPath();
      if(offset===450) {
        ctx.moveTo(px,py-5);ctx.lineTo(px+5,py);ctx.lineTo(px,py+5);ctx.lineTo(px-5,py);ctx.closePath();
      } else ctx.arc(px,py,offset===0?5:7,0,Math.PI*2);
      ctx.fillStyle=offset===0?'#fff0b7':'#62e3cc';ctx.strokeStyle='#62e3cc';ctx.lineWidth=2;
      if(offset===900)ctx.stroke();else ctx.fill();
    }
    ctx.font='12px sans-serif';ctx.fillStyle='#aa9580';ctx.fillText('PAST 0.5 s',9,17);
    ctx.fillStyle='#62e3cc';ctx.fillText('NEXT 0.9 s',170,17);
  }
  function paint(t=now()) {
    if(!model)return;
    model.view=flowView(model.userView,model.puzzle.flow,t,model.motor);
    draw();drawForecast(t);
    const centered=model.facePaths.find(face=>magnitude(face.center)<=model.puzzle.activation_radius);
    const selected=model.focusedFace==null?null:model.facePaths.find(face=>face.id===model.focusedFace);
    document.querySelector('#clt2-position').textContent=selected?(magnitude(selected.center)<=model.puzzle.activation_radius?'SELECTED FACE IN APERTURE':'SELECTED FACE OUTSIDE'):(centered?'FACE IN APERTURE':'STEER A FACE INTO APERTURE');
    document.querySelector('#clt2-detent').textContent=t>=model.readyAt?'DETENT READY':'DETENT SETTLING';
    document.querySelector('#clt2-twists').textContent=`${model.twists} / ${model.puzzle.move_budget}`;
    document.querySelector('#clt2-uniform').textContent=model.current.filter(face=>new Set(face).size===1).length+' / '+model.current.length;
  }
  function animate() {
    if(!model.terminal) {
      paint();
      if(now()>=model.puzzle.play_time_ms) {
        if(model.drag) {model.userView=model.drag.base;model.drag=null;}
        finish(model.current.every(face=>new Set(face).size===1)?'':'TIME ENDED');
      }
    }
    frame=requestAnimationFrame(animate);
  }
  function turn(faceId,direction,source,point,t=now()) {
    if(model.terminal || ![-1,1].includes(direction))return;
    if(t>=model.puzzle.play_time_ms) {finish('TIME ENDED');return;}
    paint(t);
    const distance=magnitude(applyView(model.view,model.puzzle.faces[faceId].center));
    const accepted=distance<=model.puzzle.activation_radius && t>=model.readyAt && model.twists<model.puzzle.move_budget;
    if(accepted) {
      const anchor=flowPoint(model.puzzle.flow,t,model.motor);
      const before=clone(model.current),after=clone(before),cycles=model.puzzle.twist_cycles[String(faceId)];
      for(const name of ['own','ring']) {
        const positions=cycles[name],values=positions.map(([f,s])=>before[f][s]);
        const shifted=direction===1?values.slice(-1).concat(values.slice(0,-1)):values.slice(1).concat(values.slice(0,1));
        positions.forEach(([f,s],i)=>after[f][s]=shifted[i]);
      }
      model.current=after;model.twists++;model.readyAt=t+model.puzzle.twist_settle_ms;
      model.motor={anchor,anchor_time_ms:t,epoch:model.twists};
      model.motors.push(model.motor);
    }
    model.focusedFace=faceId;
    record('turn',t,{input_source:source,face_id:faceId,direction,point,focus_distance:distance,
      accepted,twists_after:model.twists,ready_at_ms:model.readyAt});
    model.helpers.setReadout(accepted?'TURN RECORDED':t<model.readyAt?'NO TURN · DETENT SETTLING':'NO TURN · FACE OUTSIDE APERTURE',accepted?'idle':'pending');
    paint(t);
    if(model.twists===model.puzzle.move_budget && !model.current.every(face=>new Set(face).size===1))finish('TWIST ALLOWANCE SPENT');
  }
  function rememberFailure(reason) {
    model.failure=reason;
    try{sessionStorage.setItem(model.failureKey,reason);}catch(_){}
  }
  async function finish(reason='') {
    if(model.terminal || model.drag)return;
    const completed=model.current.every(face=>new Set(face).size===1) && model.twists<=model.puzzle.move_budget;
    if(reason || !completed)rememberFailure(reason||'INCOMPLETE CERTIFICATION');
    model.terminal=true;
    const payload={mechanic_id:model.state.mechanic_id,task_id:model.state.task_id,challenge_id:model.state.challenge_id,
      interaction_mode:model.interaction,control_condition:model.state.control_condition,events:clone(model.events),
      final_state:clone(model.current),twist_count:model.twists,final_t_ms:now(),completed:completed&&!model.failure,
      terminal_failure:!!model.failure};
    model.result=payload;
    document.querySelector('.clt2-shell').dataset.verdict=model.failure?'fail':'pending';
    document.querySelector('.clt2-verdict strong').textContent=model.failure?'FAIL':'VERIFYING';
    document.querySelector('.clt2-verdict span').textContent=model.failure||'Exact sticker replay';
    model.helpers.setReadout(model.failure?'FAIL · ATTEMPT ENDED':'VERIFYING…',model.failure?'error':'pending');
    try {
      const r=await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      model.outcome=await r.json();
      if(!model.outcome.passed)rememberFailure(model.failure||'CERTIFICATION REJECTED');
      document.querySelector('.clt2-shell').dataset.verdict=model.outcome.passed?'pass':'fail';
      document.querySelector('.clt2-verdict strong').textContent=model.outcome.passed?'PASS':'FAIL';
      document.querySelector('.clt2-verdict span').textContent=model.outcome.passed?'Every heptagon restored':model.failure;
      model.helpers.setReadout(model.outcome.passed?'PASS':'FAIL · ATTEMPT ENDED',model.outcome.passed?'passed':'error');
    } catch(error) {
      model.helpers.setReadout('VERIFIER LINK ERROR','error');
      document.querySelector('.clt2-shell').dataset.verdict='error';
      document.querySelector('.clt2-verdict strong').textContent='LINK ERROR';
    }
  }
  function installCanvas() {
    const canvas=model.canvas;
    canvas.addEventListener('contextmenu',e=>e.preventDefault());
    canvas.addEventListener('pointerdown',e=> {
      if(model.terminal || model.drag || ![0,2].includes(e.button))return;
      const start=discPoint(e);if(magnitude(start)>=.985)return;
      e.preventDefault();canvas.setPointerCapture(e.pointerId);
      model.drag={id:e.pointerId,button:e.button,start,last:start,base:clone(model.userView),startTime:now(),travel:0};
    });
    canvas.addEventListener('pointermove',e=> {
      if(model.terminal)return;
      if(!model.drag) {paint();model.hoveredFace=faceAt(e);return;}
      if(model.drag.id!==e.pointerId)return;
      e.preventDefault();const next=discPoint(e);if(magnitude(next)>=.985)return;
      model.drag.travel+=magnitude(sub(next,model.drag.last));model.drag.last=next;
      if(model.drag.button===0)model.userView=panView(model.drag.base,model.panHistory,model.drag.start,next).view;
      paint();
    });
    function end(e,cancelled=false) {
      if(!model.drag || model.drag.id!==e.pointerId)return;
      const drag=model.drag,t=now();model.drag=null;
      if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);
      if(t>=model.puzzle.play_time_ms) {model.userView=drag.base;finish('TIME ENDED');return;}
      if(cancelled){model.userView=drag.base;paint(t);return;}
      const p=discPoint(e);
      if(magnitude(p)>=.985){model.userView=drag.base;paint(t);return;}
      if(drag.button===0 && magnitude(sub(p,drag.start))>=.001 && drag.travel>=.008) {
        const steered=panView(drag.base,model.panHistory,drag.start,p);
        model.userView=steered.view;model.panHistory=steered.history;
        record('pan',t,{input_source:'disc_drag',start:drag.start,end:p,start_t_ms:drag.startTime});
        paint(t);return;
      }
      model.userView=drag.base;paint(t);
      if(drag.travel>=.008)return;
      const face=faceAt(e);if(face==null)return;
      if(model.interaction==='full')turn(face,drag.button===2?1:-1,'canvas_turn',p,t);
      else if(drag.button===0) {
        model.focusedFace=face;record('select',t,{input_source:'select_click',face_id:face,point:p});paint(t);
      }
    }
    canvas.addEventListener('pointerup',e=>end(e));
    canvas.addEventListener('pointercancel',e=>end(e,true));
    canvas.addEventListener('lostpointercapture',e=>{if(model.drag?.id===e.pointerId)end(e,true);});
  }
  function render(state,helpers) {
    cancelAnimationFrame(frame);
    document.body.dataset.mechanic='circle-limit-twist-v2';
    const interaction=state.control_condition?.interaction||'full';
    helpers.app.innerHTML=`<main class="clt2-shell" data-interaction="${interaction}" data-verdict="idle">
      <header class="circle-header"><div class="circle-title"><span>THE HYPERBOLIC ENGINE / CONTINUOUS FLOW</span><h1>Circle Limit Twist <i>II</i></h1></div><p>One color per heptagon. The aperture stays here.<br>The tiling never stops while you steer or turn.</p></header>
      <section class="circle-stage"><aside class="circle-index"><span class="eyebrow">FLOW FORECAST</span><canvas id="clt2-flow" width="260" height="170" aria-label="Recent flow trace and next 0.9-second path"></canvas>
      <div class="clt2-forecast-legend"><span>● NOW</span><span>◆ +0.45 s</span><span>○ +0.90 s</span></div><p>Turquoise forecasts the next movement. Each turn redirects the motor smoothly.</p><p class="clt2-cycle-legend">Hover a face to see its two sticker cycles. ↷ follows the arrows; ↶ reverses them. Each turn shifts one sticker along each loop.</p><h2>ONE COLOR<br>PER HEPTAGON</h2>
      <div class="registry"><span>UNIFORM FACES</span><b id="clt2-uniform"></b><span>FLOW</span><b>LIVE</b></div></aside>
      <div class="disc-vault"><canvas id="clt2-disc" width="900" height="900" aria-label="Moving hyperbolic heptagon puzzle"></canvas><div class="aperture-label">TURNING APERTURE</div></div>
      <aside class="circle-console"><span class="eyebrow">${interaction.toUpperCase()} CONTROLS</span><div class="clt2-instructions"><b>DRAG DISC</b><span>Steer a face into the aperture.</span>${interaction==='full'?'<b>LEFT / RIGHT CLICK</b><span>Turn counter-clockwise / clockwise.</span>':'<b>CLICK FACE</b><span>Select it, then turn below.<br>Selection does not center it.</span>'}</div>
      ${interaction==='simplified'?'<div class="twist-proxy"><button data-direction="-1"><b>↶</b><span>COUNTER-CLOCKWISE</span></button><button data-direction="1"><b>↷</b><span>CLOCKWISE</span></button></div>':''}
      <div id="clt2-position"></div><div id="clt2-detent"></div><div class="twist-meter"><span>TWISTS USED</span><b id="clt2-twists"></b><p>Each turn settles for 1.2 s.<br>Flow continues throughout.</p></div><div class="readout">STEER AND RESTORE</div><button id="clt2-certify">CERTIFY</button><small>An incomplete certification ends the episode.</small></aside></section>
      <div class="clt2-verdict"><strong></strong><span></span></div></main>`;
    model={state,helpers,interaction,puzzle:state.puzzle,palette:state.puzzle.palette,current:clone(state.puzzle.initial_state),
      userView:clone(IDENTITY),view:clone(IDENTITY),panHistory:[],motor:null,motors:[],events:[],twists:0,readyAt:0,focusedFace:null,hoveredFace:null,
      facePaths:[],drag:null,terminal:false,failure:'',startedAt:performance.now(),
      canvas:document.querySelector('#clt2-disc'),failureKey:`circle_limit_twist_v2:terminal:${state.task_id}:${location.search}`};
    model.ctx=model.canvas.getContext('2d');model.flowCtx=document.querySelector('#clt2-flow').getContext('2d');
    window.circleLimitTwistV2Model=model;
    installCanvas();
    document.querySelectorAll('.twist-proxy button').forEach(button=>button.addEventListener('click',()=> {
      if(model.focusedFace!=null && !model.drag)turn(model.focusedFace,Number(button.dataset.direction),'proxy_turn',null);
    }));
    document.querySelector('#clt2-certify').addEventListener('click',()=>finish());
    paint();
    try {
      const failure=sessionStorage.getItem(model.failureKey);
      if(failure) {
        model.failure=failure;model.terminal=true;model.outcome={passed:false};
        document.querySelector('.clt2-shell').dataset.verdict='fail';
        document.querySelector('.clt2-verdict strong').textContent='FAIL';document.querySelector('.clt2-verdict span').textContent=failure;
        helpers.setReadout('FAIL · ATTEMPT ENDED','error');
      }
    } catch(_){}
    frame=requestAnimationFrame(animate);
  }
  window.circleLimitTwistV2Math={applyView,multiply,phi,inversePhi,translation,panView,flowPoint,flowView,
    hitPoint,facePolygon,polygonContains,hitFace,faceAtPoint};
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.circle_limit_twist_v2={render,rootSelector:'.clt2-shell'};
})();
