(() => {
'use strict';
let cleanup=null;
const clone=x=>JSON.parse(JSON.stringify(x));
function bounds(s,w){const a=w.area/s.h;return [s.x-a/2,s.bottom-s.h,a,s.h];}
function overlap(a,b){return a[0]<b[0]+b[2]-1e-8&&a[0]+a[2]>b[0]+1e-8&&a[1]<b[1]+b[3]-1e-8&&a[1]+a[3]>b[1]+1e-8;}
function clear(s,w){const b=bounds(s,w);return b[1]>=0&&!w.solids.some(r=>overlap(b,r));}
function advance(s,c,w){
 if(s.status!=='active')return false;
 if(c[0]===0&&c[1]===0){
  if(!s._has_controlled)return false;
  s._release_settle_ticks=(s._release_settle_ticks||0)+1;
  if(s._release_settle_ticks>12){s._release_settle_ticks=12;return false;}
 }else{s._has_controlled=true;s._release_settle_ticks=0;}
 s.tick++;
 for(let sub=0;sub<4;sub++){
  const h=Math.max(w.min_height,Math.min(w.max_height,s.h+c[1]*.75));
  if(clear({...s,h},w))s.h=h;
  s.vx=Math.max(-4,Math.min(4,(s.vx+c[0]*.35+w.wind[s.tick])*w.parameters.drag**.25));
  if(clear({...s,x:s.x+s.vx/4},w))s.x+=s.vx/4;else s.vx=0;
  s.vy=Math.min(10,s.vy+.25);
  const bottom=s.bottom+s.vy/4;
  if(clear({...s,bottom},w))s.bottom=bottom;
  else {const b=bounds(s,w),land=w.solids.filter(r=>b[0]<r[0]+r[2]-1e-8&&b[0]+b[2]>r[0]+1e-8&&s.bottom<=r[1]+1e-8&&bottom>=r[1]).map(r=>r[1]);if(land.length)s.bottom=Math.min(...land);s.vy=0;}
  const b=bounds(s,w);
  w.seals.forEach(([x,y],i)=>{const dx=x-Math.max(b[0],Math.min(x,b[0]+b[2])),dy=y-Math.max(b[1],Math.min(y,b[1]+b[3]));if(dx*dx+dy*dy<=100&&!s.collected.includes(i))s.collected.push(i);});
 }
 if(c[0]===0&&c[1]===0&&(s._release_settle_ticks||0)>=12){s.vx=0;s.vy=0;}
 const b=bounds(s,w);if(s.bottom>570||b[0]<0||b[0]+b[2]>1000)s.status='fell';else if(s.collected.length===w.seals.length)s.status='solved';else if(s.tick>=w.max_ticks)s.status='timeout';
 return true;
}
async function render(state,helpers){
 if(cleanup)cleanup();document.body.dataset.mechanic='concertina-courier';
 const mode=state.control_condition?.interaction||'full';
 const m={state,sim:clone(state.initial_state),control:[0,0],events:[],activeSince:performance.now(),activeOriginTick:0,terminal:false,submitting:false,mode};window.concertinaCourierV2Model=m;
 helpers.app.innerHTML=`<section class="concertina"><header><span>FOLD / POST<br>DELIVERY OFFICE № 08</span><h1>Concertina Courier V2</h1><b class="cc-count">0 / ${state.seals.length} SEALS</b></header><div class="cc-room"><canvas width="1000" height="580"></canvas><div class="cc-body-controls" ${mode==='full'?'':'hidden'}><button data-c="-1,0" aria-label="Slide left">←</button><button data-c="0,1" aria-label="Morph taller">↥</button><button data-c="1,0" aria-label="Slide right">→</button><button data-c="0,-1" aria-label="Morph wider">↔</button></div><div class="cc-verdict"></div></div><footer><div class="cc-instruction">${mode==='full'?'HOLD BODY ARROWS · RELEASE TO COAST':'CLICK TO ENGAGE · CLICK COAST TO RELEASE'}<small>Collect every gold seal · fixed area · no jumping</small></div><div class="cc-console" ${mode==='simplified'?'':'hidden'}>${[['-1,0','←'],['1,0','→'],['0,1','TALLER'],['0,-1','WIDER'],['0,0','COAST']].map(([c,t])=>`<button data-latch="${c}">${t}</button>`).join('')}</div><div class="readout" data-status="idle">READY</div><button class="cc-submit">CERTIFY</button><button class="cc-new">NEW ROOM</button></footer></section>`;
 const canvas=document.querySelector('.cc-room canvas'),ctx=canvas.getContext('2d');
 function draw(){
  const s=m.sim;ctx.fillStyle='#183f48';ctx.fillRect(0,0,1000,580);
  ctx.strokeStyle='#2c5159';ctx.lineWidth=1;for(let x=0;x<1000;x+=50){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,580);ctx.stroke();}
  ctx.fillStyle='#b3d0c8';ctx.font='14px monospace';ctx.fillText('SORTING HALL / SHAPE IS YOUR TOOL',28,35);
  const draft=state.wind[s.tick];ctx.fillStyle='#f4d89c';ctx.fillText(`${draft===0?'DRAFT STEADY':`DRAFT ${draft<0?'←':'→'}`} · RELEASE SETTLES THEN HOLDS`,500,35);
  ctx.strokeStyle='#ffc88e';ctx.lineWidth=3;ctx.setLineDash([10,7]);ctx.beginPath();ctx.moveTo(3,45);ctx.lineTo(3,580);ctx.moveTo(997,45);ctx.lineTo(997,580);ctx.stroke();ctx.setLineDash([]);
  ctx.fillText('OPEN EDGES · KEEP THE PARCEL INSIDE THE ROOM',500,57);
  state.solids.forEach(([x,y,w,h])=>{ctx.fillStyle='#ba7850';ctx.fillRect(x,y,w,h);ctx.fillStyle='#e6b77c';ctx.fillRect(x,y,w,7);ctx.fillStyle='#8a533f';for(let a=x+8;a<x+w;a+=26)ctx.fillRect(a,y+16,3,Math.max(0,h-20));});
  state.seals.forEach(([x,y],i)=>{ctx.strokeStyle=s.collected.includes(i)?'#39666b':'#789086';ctx.beginPath();ctx.moveTo(x,50);ctx.lineTo(x,y-11);ctx.stroke();ctx.beginPath();ctx.arc(x,y,10,0,Math.PI*2);ctx.fillStyle=s.collected.includes(i)?'#39666b':'#ffdb65';ctx.fill();ctx.strokeStyle='#5e522e';ctx.stroke();if(!s.collected.includes(i)){ctx.fillStyle='#786128';ctx.fillRect(x-3,y-3,6,6);}});
  const [x,y,w,h]=bounds(s,state);ctx.fillStyle='#f4d89c';ctx.fillRect(x,y,w,h);ctx.strokeStyle='#815743';ctx.lineWidth=2;ctx.strokeRect(x+1,y+1,w-2,h-2);
  ctx.strokeStyle='#c19c69';for(let a=1;a<8;a++){ctx.beginPath();ctx.moveTo(x+w*a/8,y+2);ctx.lineTo(x+w*a/8-3,y+h/2);ctx.lineTo(x+w*a/8,y+h-2);ctx.stroke();}
  ctx.fillStyle='#f5efe1';ctx.fillRect(s.x-13,y+h*.4,26,Math.min(24,h*.4));ctx.fillStyle='#314a4a';ctx.fillRect(s.x-7,y+h*.4+5,4,4);ctx.fillRect(s.x+3,y+h*.4+5,4,4);
  const controls=document.querySelector('.cc-body-controls');controls.style.left=`${s.x/10}%`;controls.style.top=`${(y+h/2)/580*100}%`;
  document.querySelector('.cc-count').textContent=`${s.collected.length} / ${state.seals.length} SEALS`;
 }
 function armActiveClock(){m.activeSince=performance.now();m.activeOriginTick=m.sim.tick;}
 function tick(){if(m.terminal||m.submitting)return;const target=m.activeOriginTick+Math.floor((performance.now()-m.activeSince)/state.tick_ms+1e-7);while(m.sim.tick<target&&m.sim.status==='active'){if(!advance(m.sim,m.control,state))break;}draw();if(m.sim.status!=='active'){m.terminal=true;document.querySelector('.cc-verdict').textContent=m.sim.status==='solved'?'ALL SEALS COLLECTED':'FAIL · PARCEL LOST';helpers.setReadout(m.sim.status==='solved'?'READY TO CERTIFY':'FAIL','idle');}}
 function set(c){tick();if(m.terminal||m.submitting)return;document.querySelector('.cc-verdict').textContent='';if(c.every((v,i)=>v===m.control[i]))return;m.control=c;m.events.push({tick:m.sim.tick,control:[...c],input_source:mode==='full'?'body_hold':'console_latch'});armActiveClock();helpers.setReadout(c[0]?'SLIDING':c[1]?'MORPHING':'COAST','idle');}
 async function submit(abandon=false){tick();if(m.submitting)return;set([0,0]);m.submitting=true;const payload={mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,interaction_mode:mode,events:clone(m.events),terminal_tick:m.sim.tick,final_state:clone(m.sim),completed:!abandon&&m.sim.status==='solved'};
  try{const r=await(await fetch('/result',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)})).json();if(r.passed){m.terminal=true;document.querySelector('.cc-verdict').textContent='PASS · DELIVERED';helpers.setReadout('PASS','passed');}else if(r.state){await render(r.state,helpers);document.querySelector('.cc-verdict').textContent='FAIL · FRESH ROOM';helpers.setReadout('FAIL','error');}else{m.submitting=false;helpers.setReadout('FAIL · RETRY','error');}}catch(e){m.submitting=false;helpers.setReadout('LINK UNAVAILABLE · RETRY','error');}}
 let heldPointer=null;
 document.querySelectorAll('[data-c]').forEach(b=>{b.addEventListener('pointerdown',e=>{if(mode!=='full'||e.button!==0||heldPointer!==null)return;e.preventDefault();heldPointer=e.pointerId;b.setPointerCapture(e.pointerId);set(b.dataset.c.split(',').map(Number));});const release=e=>{if(e.pointerId!==heldPointer)return;heldPointer=null;set([0,0]);};b.addEventListener('pointerup',release);b.addEventListener('pointercancel',release);});
 document.querySelectorAll('[data-latch]').forEach(b=>b.addEventListener('click',()=>{if(mode==='simplified')set(b.dataset.latch.split(',').map(Number));}));
 const blur=()=>{if(mode==='full'){heldPointer=null;set([0,0]);}};window.addEventListener('blur',blur);
 document.querySelector('.cc-submit').onclick=()=>submit();document.querySelector('.cc-new').onclick=()=>submit(true);
 let raf;function frame(){tick();raf=requestAnimationFrame(frame);}draw();raf=requestAnimationFrame(frame);
 cleanup=()=>{cancelAnimationFrame(raf);window.removeEventListener('blur',blur);m.terminal=true;};
}
window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};window.GymAnythingRTMechanics.concertina_courier_nonrealtime={rootSelector:'.concertina',render};
})();
