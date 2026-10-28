(() => {
'use strict';

  function motionNoise(seed, index) {
    let x = (Number(seed) + Math.imul(index + 1, 0x9E3779B9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85EBCA6B) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xC2B2AE35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 2147483648 - 1;
  }
  function motionValue(seed, tMs, spanMs=1300) {
    const t = Math.max(0, tMs) / spanMs, i = Math.floor(t), u = t-i;
    const a = motionNoise(seed,i), b = motionNoise(seed,i+1);
    return a+(b-a)*u*u*(3-2*u);
  }
  function motionIntegral(seed, tMs, spanMs=1300) {
    const t = Math.max(0,tMs)/spanMs, n = Math.floor(t), u=t-n;
    let sum=0;
    for(let i=0;i<n;i++) sum+=(motionNoise(seed,i)+motionNoise(seed,i+1))/2;
    const a=motionNoise(seed,n), b=motionNoise(seed,n+1);
    return spanMs/1000*(sum+a*u+(b-a)*(u**3-.5*u**4));
  }

const D={UP:[0,-1],RIGHT:[1,0],DOWN:[0,1],LEFT:[-1,0],WAIT:[0,0]}, glyph={UP:'↑',RIGHT:'→',DOWN:'↓',LEFT:'←',WAIT:'·'};
let timer, handler;
const equal=(a,b)=>a[0]===b[0]&&a[1]===b[1];
function render(state,h){
 document.body.dataset.mechanic="clockbeat_catacomb_nonrealtime";
 if(timer)clearInterval(timer);if(handler)window.removeEventListener('keydown',handler);
 const b=state.board, mode=state.control_condition?.interaction||'full';
 const s={player:[...b.start],hp:b.health,enemies:structuredClone(b.enemies),beat:0,used:false,won:false};
 let started=false,events=[],submitted=false,message='Wind the clock when ready.';
 const ph=e=>e.kind==='lancer'?Math.floor((motionNoise(e.phase_seed,s.beat)+1)*1.5):Number(motionNoise(e.phase_seed,s.beat)>0);
 const solid=p=>b.walls.some(q=>equal(p,q));
 function act(key){
  if(s.won||s.hp<=0||s.used)return 'unavailable';s.used=true;
  if(key==='WAIT')return 'wait';
  const [dx,dy]=D[key],p=[s.player[0]+dx,s.player[1]+dy];if(solid(p))return 'wall';
  const e=s.enemies.find(e=>e.hp>0&&equal(e.pos,p));
  if(e){if(e.kind==='hopper'&&ph(e)===1)return 'shield';e.hp--;return e.hp===0?'defeated':'hit';}
  s.player=p;s.won=equal(p,b.exit)&&s.enemies.every(e=>e.hp===0);return s.won?'escaped':'move';
 }
 function step(){
  if(s.won||s.hp<=0)return;
  for(const e of s.enemies){
   if(e.hp<=0)continue;const phase=ph(e);
   if((e.kind==='crawler'||e.kind==='hopper')&&phase===0)continue;if(e.kind==='lancer'&&phase!==1)continue;
   const [x,y]=e.pos,[px,py]=s.player,dist=Math.abs(x-px)+Math.abs(y-py);
   if(e.kind==='lancer'){if(dist===1)s.hp--;continue;}
   const choices=Object.values(D).map((d,i)=>({d,i,dist:Math.abs(x+d[0]-px)+Math.abs(y+d[1]-py)})).sort((a,b)=>a.dist-b.dist||a.i-b.i);
   for(const {d,i,dist:nd} of choices){if(i===4||nd>=dist)continue;const p=[x+d[0],y+d[1]];
    if(solid(p)||s.enemies.some(o=>o!==e&&o.hp>0&&equal(o.pos,p)))continue;
    if(equal(p,s.player))s.hp--;else e.pos=p;break;
   }
  }s.beat++;s.used=false;
 }
 const logicalMs=()=>events.length?events[events.length-1].ms:0;
 h.app.innerHTML=`<section class="cc" tabindex="0"><header><div><small>THE UNDERGROUND HOROLOGICAL SOCIETY</small><h1>Clockbeat Catacomb V2</h1></div><div class="cc-health"></div></header><main><div class="cc-chamber"><div class="cc-board" style="--n:${b.size}"></div><div class="cc-verdict"></div></div><aside><small>SHARED TURN</small><div class="cc-pulse"><i></i></div><h2 class="cc-beat">CLOCK AT REST</h2><p class="cc-window">Your action stays available until you use it. Sentries act after each deliberate input.</p><div class="cc-roster"></div><p class="cc-rule">Move into a sentry to attack. Their current intentions are shown each turn. After your input, sentries act in numbered order. Chasers favor ↑ → ↓ ← on ties; blocked paths do not detour. Clear every sentry, then enter the stair.</p>${mode==='full'?'<div class="cc-keys">← ↑ ↓ →<small>ARROWS / WASD · SPACE TO WAIT</small></div>':`<div class="cc-buttons">${Object.keys(D).map(k=>`<button data-cc-key="${k}" aria-label="${k}">${glyph[k]}</button>`).join('')}</div>`}</aside></main><footer><button class="cc-start">WIND THE CLOCK</button><div class="cc-message"></div><button class="cc-submit">SUBMIT EXPEDITION</button></footer><div class="readout" data-status="idle"></div></section>`;
 const root=h.app.querySelector('.cc'),board=root.querySelector('.cc-board');
 function draw(){
  root.querySelector('.cc-health').textContent='LANTERN '+ '♥'.repeat(Math.max(0,s.hp))+'♡'.repeat(Math.max(0,b.health-s.hp));
  root.querySelector('.cc-beat').textContent=!started?'CLOCK AT REST':s.beat>=b.max_beats?'CLOCK EXHAUSTED':`TURN ${s.beat+1} · YOUR MOVE`;
  const pulse=root.querySelector('.cc-pulse');pulse.style.setProperty('--progress','0%');pulse.classList.remove('closed');
  root.querySelector('.cc-message').textContent=message;
  root.querySelector('.cc-roster').innerHTML=s.enemies.map(e=>`<div class="cc-entry ${e.kind}"><b>${e.id} · ${{crawler:'Brass Mite',hopper:'Vault Beetle',lancer:'Chime Thorn'}[e.kind]}</b><span>${e.hp<=0?'DISMANTLED':e.kind==='crawler'?(ph(e)===0?'RESTING THIS BEAT':'CHASE AT BEAT END'):e.kind==='hopper'?(ph(e)===0?'RESTING / ARMOR OPEN':'SHIELDED / CHASE AT BEAT END'):['RESTING THIS BEAT','STRIKE AT BEAT END','RESTING THIS BEAT'][ph(e)]}</span><small>${e.kind==='lancer'?'Strikes four adjacent tiles; stays rooted.':e.kind==='hopper'?'Armored during chase. Attack while resting.':'Chases one tile; contact costs one heart.'}</small></div>`).join('');
  let cells='';for(let y=0;y<b.size;y++)for(let x=0;x<b.size;x++){
   const p=[x,y],wall=solid(p),e=s.enemies.find(e=>e.hp>0&&equal(e.pos,p)),player=equal(s.player,p),exit=equal(b.exit,p);
   const danger=s.enemies.some(e=>e.hp>0&&e.kind==='lancer'&&ph(e)===1&&Math.abs(x-e.pos[0])+Math.abs(y-e.pos[1])===1);
   cells+=`<div class="cc-tile ${wall?'wall':''} ${danger&&!wall?'danger':''}">${exit?`<span class="cc-stair ${s.enemies.every(e=>e.hp===0)?'unlocked':''}">≋</span>`:''}${e?`<span class="cc-enemy ${e.kind} ${e.kind==='hopper'&&ph(e)===1?'shield':''}"><b>${e.id}</b><i>${'•'.repeat(e.hp)}</i></span>`:''}${player?'<span class="cc-player"><i></i></span>':''}</div>`;
  }board.innerHTML=cells;
  root.querySelector('.cc-verdict').textContent=s.won?'STAIR OPEN · ESCAPED':s.hp<=0?'LANTERN OUT · FAILED':'';
  root.querySelector('.cc-verdict').classList.toggle('visible',s.won||s.hp<=0);
  root.dataset.beat=String(s.beat);root.dataset.used=String(s.used);root.dataset.ms=String(logicalMs());root.dataset.won=String(s.won);
 }
 function input(key,source){
  if(!started||submitted||s.won||s.hp<=0||s.beat>=b.max_beats||s.used)return;
  const ms=s.beat*b.beat_ms+100,outcome=act(key);
  events.push({sequence:events.length+1,ms,key,input_source:source,outcome});
  if(!s.won&&s.hp>0)step();
  message={unavailable:'TURN ALREADY PLAYED.',shield:'ARMORED · Attack blocked.',wall:'WALL · Turn spent.',defeated:'SENTRY DISMANTLED',hit:'HIT · Sentry damaged.',move:'STEP ACCEPTED',wait:'WAIT ACCEPTED',escaped:'ESCAPED · Submit expedition.'}[outcome]||'TURN RESOLVED.';draw();
 }
 root.querySelector('.cc-start').onclick=()=>{if(started)return;h.setReadout('', 'idle');started=true;message='Clock wound. Your move is ready.';root.querySelector('.cc-start').disabled=true;draw();};
 root.querySelectorAll('[data-cc-key]').forEach(el=>el.onclick=()=>input(el.dataset.ccKey,'direction_buttons'));
 handler=e=>{if(mode!=='full'||e.repeat)return;const key={ArrowUp:'UP',ArrowRight:'RIGHT',ArrowDown:'DOWN',ArrowLeft:'LEFT',w:'UP',d:'RIGHT',s:'DOWN',a:'LEFT',' ':'WAIT'}[e.key];if(key){e.preventDefault();input(key,'keyboard');}};window.addEventListener('keydown',handler);
 root.querySelector('.cc-submit').onclick=async()=>{
  if(submitted)return;submitted=true;
  const payload={mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,actions:events,final_ms:logicalMs(),final_state:structuredClone(s)};
  try{const response=await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const out=await response.json();
   if(out.passed){root.querySelector('.cc-verdict').textContent='PASS · EXPEDITION VERIFIED';root.querySelector('.cc-verdict').classList.add('visible');h.setReadout('PASS','passed');}
   else if(out.state){await h.render(out.state);h.setReadout('FAIL · Fresh catacomb ready','error');}
   else{submitted=false;message='Submission unavailable. Try again.';draw();}
  }catch(e){submitted=false;message='Submission unavailable. Try again.';draw();}
 };
 draw();root.focus();
}
window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};window.GymAnythingRTMechanics.clockbeat_catacomb_nonrealtime={rootSelector:'.cc',render};
})();
