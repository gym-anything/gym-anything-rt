(() => {
  "use strict";

  const sparkLayerStyle=document.createElement("style");sparkLayerStyle.textContent=".reload-overload .overload-spark{z-index:1}";document.head.append(sparkLayerStyle);
  let model=null;
  const esc=value=>String(value==null?"":value).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");
  const vector={up:[0,-1],right:[1,0],down:[0,1],left:[-1,0]};
  function interaction(){return model.state.control_condition?.interaction||"full";}
  function record(kind,details={}){const event={sequence:model.events.length+1,kind,...details};model.events.push(event);return event;}
  function moveLever(direction,preview=false){const lever=document.querySelector(".reload-v2-lever");if(!lever)return;const [x,y]=vector[direction];lever.style.setProperty("--lever-x",`${x*46}px`);lever.style.setProperty("--lever-y",`${y*46}px`);lever.dataset.preview=String(preview);setTimeout(()=>{lever.style.setProperty("--lever-x","0px");lever.style.setProperty("--lever-y","0px");},260);}
  async function fail(reason){if(model.submitting)return;model.submitting=true;record("abort",{reason});await submit();}
  async function submit(){try{const response=await fetch("/result",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({mechanic_id:model.state.mechanic_id,challenge_id:model.state.challenge_id,interaction_mode:interaction(),events:model.events})});const outcome=await response.json();if(outcome.passed===true){model.helpers.setReadout("PASS","passed");document.querySelector(".reload-v2").classList.add("is-passed");}else{model.helpers.setReadout("FAIL","error");setTimeout(()=>outcome.state&&model.helpers.render(outcome.state),850);}}catch(_error){model.submitting=false;model.helpers.setReadout("FAIL","error");}}
  function staticSparkPoint(spec){const angle=Number(spec.phase);return [Number(spec.center[0])+Math.cos(angle)*Number(spec.radius_x),Number(spec.center[1])+Math.sin(angle)*Number(spec.radius_y)];}
  function clearInterruption(spec,samples,duration){record("interrupt",{interruption_id:spec.id,surface:interaction(),samples,duration_ms:Math.round(duration)});model.activeInterruption=null;document.querySelector(".reload-overload").remove();document.querySelector(".reload-machine").classList.remove("is-obscured");model.helpers.setReadout("","idle");}
  function beginHold(target,spec,samplePoint){target.addEventListener("pointerdown",event=>{if(event.button!==0||model.activePointerCleanup)return;event.preventDefault();target.setPointerCapture(event.pointerId);const pointerId=event.pointerId,startedInput=model.helpers.interactionNow(),startedWorld=performance.now(),samples=[];let finished=false;target.dataset.held="true";const appendSample=moveEvent=>samples.push({elapsed_ms:Math.round(model.helpers.interactionNow()-startedInput),world_elapsed_ms:Math.round(performance.now()-startedWorld),point:samplePoint(moveEvent)});const sample=moveEvent=>{if(moveEvent.pointerId!==pointerId)return;appendSample(moveEvent);};sample(event);const interval=setInterval(()=>appendSample(event),90);const cleanup=()=>{if(finished)return false;finished=true;clearInterval(interval);target.removeEventListener("pointermove",sample);target.removeEventListener("pointerup",up);target.removeEventListener("pointercancel",cancel);target.removeEventListener("lostpointercapture",cancel);window.removeEventListener("pointerup",up,true);window.removeEventListener("pointercancel",cancel,true);target.dataset.held="false";if(model?.activePointerCleanup===cleanup)model.activePointerCleanup=null;try{if(target.hasPointerCapture(pointerId))target.releasePointerCapture(pointerId);}catch(_){}return true;};const up=upEvent=>{if(upEvent.pointerId!==pointerId||!cleanup())return;const duration=model.helpers.interactionNow()-startedInput;if(duration>=Number(spec.hold_ms)&&samples.length>=Number(spec.min_samples))clearInterruption(spec,samples,duration,startedWorld-model.overlayStartedAt);else fail("overload_released");};const cancel=cancelEvent=>{if(cancelEvent.pointerId===pointerId)cleanup();};model.activePointerCleanup=cleanup;target.addEventListener("pointermove",sample);target.addEventListener("pointerup",up);target.addEventListener("pointercancel",cancel);target.addEventListener("lostpointercapture",cancel);window.addEventListener("pointerup",up,true);window.addEventListener("pointercancel",cancel,true);});}
  function beginFullHold(spark,spec){
    spark.addEventListener("pointerdown",event=>{
      if(event.button!==0||model.activePointerCleanup)return;
      event.preventDefault();
      const pointerId=event.pointerId,startedInput=model.helpers.interactionNow(),startedWorld=performance.now(),samples=[];
      let finished=false;
      spark.dataset.held="true";
      const stage=document.querySelector(".reload-v2-stage");
      let lastPoint=[0,0];
      const pointFromEvent=moveEvent=>{
        const rect=stage.getBoundingClientRect();
        return [Math.round(moveEvent.clientX-rect.left),Math.round(moveEvent.clientY-rect.top)];
      };
      const appendSample=(moveEvent=null)=>{
        if(moveEvent)lastPoint=pointFromEvent(moveEvent);
        const elapsed=Math.round(model.helpers.interactionNow()-startedInput),worldElapsed=Math.round(performance.now()-startedWorld);
        if(samples.length&&elapsed<=samples[samples.length-1].elapsed_ms)return;
        const previous=samples[samples.length-1];
        if(previous&&worldElapsed===previous.world_elapsed_ms){
          for(let filled=previous.elapsed_ms+90;filled<elapsed;filled+=90){
            samples.push({elapsed_ms:filled,world_elapsed_ms:previous.world_elapsed_ms,point:[...previous.point]});
          }
        }
        samples.push({elapsed_ms:elapsed,world_elapsed_ms:worldElapsed,point:[...lastPoint]});
      };
      const sample=moveEvent=>{
        if(moveEvent.pointerId!==pointerId)return;
        appendSample(moveEvent);
      };
      sample(event);
      const interval=setInterval(appendSample,90);
      const cleanup=()=>{
        if(finished)return false;
        finished=true;
        clearInterval(interval);
        window.removeEventListener("pointermove",sample,true);
        window.removeEventListener("pointerup",up,true);
        window.removeEventListener("pointercancel",cancel,true);
        spark.dataset.held="false";
        if(model?.activePointerCleanup===cleanup)model.activePointerCleanup=null;
        return true;
      };
      const up=upEvent=>{
        if(upEvent.pointerId!==pointerId)return;
        sample(upEvent);
        if(!cleanup())return;
        const duration=model.helpers.interactionNow()-startedInput;
        if(duration>=Number(spec.hold_ms)&&samples.length>=Number(spec.min_samples))clearInterruption(spec,samples,duration);
        else fail("overload_released");
      };
      const cancel=cancelEvent=>{if(cancelEvent.pointerId===pointerId&&cleanup())model.helpers.setReadout("HOLD INTERRUPTED · RETRY","error");};
      model.activePointerCleanup=cleanup;
      window.addEventListener("pointermove",sample,true);
      window.addEventListener("pointerup",up,true);
      window.addEventListener("pointercancel",cancel,true);
    });
  }
  function showInterruption(spec){model.activeInterruption=spec;document.querySelector(".reload-machine").classList.add("is-obscured");const proxy=interaction()==="simplified"?'<button type="button" class="overload-proxy" aria-label="Hold stabilizer">HOLD STABILIZER</button>':"";const [x,y]=staticSparkPoint(spec);document.querySelector(".reload-v2-stage").insertAdjacentHTML("beforeend",`<div class="reload-overload"><div class="overload-grid"></div><div class="overload-orbit" style="left:${spec.center[0]-spec.radius_x}px;top:${spec.center[1]-spec.radius_y}px;width:${spec.radius_x*2}px;height:${spec.radius_y*2}px"></div><button type="button" class="overload-spark" aria-label="Unstable spark" style="left:${x}px;top:${y}px"><i></i></button>${proxy}</div>`);const spark=document.querySelector(".overload-spark");if(interaction()==="full"){beginFullHold(spark,spec);}else{beginHold(document.querySelector(".overload-proxy"),spec,()=>[0,0]);}}
  function acceptedGesture(direction){record("gesture",{index:model.step,direction,surface:interaction()});moveLever(direction,false);model.step+=1;const interruption=model.state.interruptions.find(item=>Number(item.after_step)===model.step);if(interruption){setTimeout(()=>showInterruption(interruption),300);return;}if(model.step>=model.state.sequence.length){model.submitting=true;setTimeout(submit,450);}}
  function attemptGesture(direction){if(!model.ready||model.activeInterruption||model.submitting)return;if(direction!==model.state.sequence[model.step]){record("gesture",{index:model.step,direction,surface:interaction()});fail("wrong_gesture");return;}acceptedGesture(direction);}
  function installLever(){const lever=document.querySelector(".reload-v2-lever");if(interaction()!=="full")return;lever.addEventListener("pointerdown",event=>{if(event.button!==0||!model.ready||model.activeInterruption||model.submitting||model.activePointerCleanup)return;event.preventDefault();lever.setPointerCapture(event.pointerId);const pointerId=event.pointerId,start=[event.clientX,event.clientY];let finished=false;lever.dataset.dragging="true";const move=moveEvent=>{if(moveEvent.pointerId!==pointerId)return;const dx=Math.max(-70,Math.min(70,moveEvent.clientX-start[0])),dy=Math.max(-70,Math.min(70,moveEvent.clientY-start[1]));lever.style.setProperty("--lever-x",`${dx}px`);lever.style.setProperty("--lever-y",`${dy}px`);};const cleanup=()=>{if(finished)return false;finished=true;lever.removeEventListener("pointermove",move);lever.removeEventListener("pointerup",up);lever.removeEventListener("pointercancel",cancel);lever.removeEventListener("lostpointercapture",cancel);lever.dataset.dragging="false";lever.style.setProperty("--lever-x","0px");lever.style.setProperty("--lever-y","0px");if(model?.activePointerCleanup===cleanup)model.activePointerCleanup=null;try{if(lever.hasPointerCapture(pointerId))lever.releasePointerCapture(pointerId);}catch(_){}return true;};const up=upEvent=>{if(upEvent.pointerId!==pointerId||!cleanup())return;const dx=upEvent.clientX-start[0],dy=upEvent.clientY-start[1],distance=Math.hypot(dx,dy);if(distance<38){fail("short_gesture");return;}attemptGesture(Math.abs(dx)>Math.abs(dy)?(dx>0?"right":"left"):(dy>0?"down":"up"));};const cancel=cancelEvent=>{if(cancelEvent.pointerId===pointerId)cleanup();};model.activePointerCleanup=cleanup;lever.addEventListener("pointermove",move);lever.addEventListener("pointerup",up);lever.addEventListener("pointercancel",cancel);lever.addEventListener("lostpointercapture",cancel);});}
  function installProxies(){if(interaction()!=="simplified")return;document.querySelectorAll("[data-reload-direction]").forEach(button=>button.addEventListener("click",()=>attemptGesture(button.dataset.reloadDirection)));}
  function preview(){model.ready=false;model.helpers.setReadout("","idle");document.querySelector(".reload-v2").classList.add("is-previewing");let index=0;const run=()=>{if(index>=model.state.sequence.length){document.querySelector(".reload-v2").classList.remove("is-previewing");model.ready=true;document.querySelector(".reload-v2").classList.add("is-ready");return;}moveLever(model.state.sequence[index],true);const chamber=document.querySelector(".reload-chamber");chamber.style.setProperty("--preview-turn",`${index*51}deg`);index+=1;setTimeout(run,Number(model.state.preview_step_ms));};setTimeout(run,700);}
  async function render(state,helpers){document.body.dataset.mechanic="reload-interruption-nonrealtime";if(model?.activePointerCleanup)model.activePointerCleanup();model={state,helpers,events:[],step:0,ready:false,activeInterruption:null,submitting:false,activePointerCleanup:null};const proxies=interaction()==="simplified"?'<div class="reload-proxy-controls" aria-label="Reload direction controls"><button type="button" data-reload-direction="up">↑</button><button type="button" data-reload-direction="left">←</button><button type="button" data-reload-direction="down">↓</button><button type="button" data-reload-direction="right">→</button></div>':"";helpers.app.innerHTML=`<section class="reload-v2" data-interaction="${interaction()}"><header><span>INTERRUPTED ORDNANCE / MEMORY DRUM</span><h1>${esc(state.prompt)}</h1></header><section class="reload-v2-stage"><div class="reload-machine"><div class="reload-chamber"><i></i><i></i><i></i><b></b></div><div class="reload-plunger"></div><button type="button" class="reload-v2-lever" aria-label="Reload lever"><i></i><b></b></button><div class="reload-bolts">${Array.from({length:7},()=>"<i></i>").join("")}</div></div>${proxies}</section><footer><div class="readout" data-status="idle"></div><div class="reload-wave"><i></i></div><span>WATCH ONCE · THEN OPERATE</span></footer></section>`;installLever();installProxies();preview();}
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};window.GymAnythingRTMechanics.reload_interruption_nonrealtime={render,rootSelector:".reload-v2"};
})();
