(() => {
  "use strict";
  const ID = "clockwork_doppelganger_customs_v3";
  const REVISION = "moving-relay-3-inspection-3";
  let model, timer;
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const round = x => Math.round(x*10000)/10000;
  const colors = ["#edb85c", "#73cad2", "#bf9cee"];
  const now = () => Math.max(0, Math.round(performance.now()-model.epoch));
  const clean = x => String(x).replaceAll("&", "&amp;").replaceAll("<", "&lt;");

  function motor(world, i, ms) {
    const u = Math.max(0,ms)/world.spec.motor_span_ms;
    const k = Math.min(Math.floor(u),world.motors[i].length-2), f = clamp(u-k,0,1);
    const [a,b] = world.motors[i].slice(k,k+2);
    return a+(b-a)*f*f*(3-2*f);
  }
  function pathY(path, f) {
    for (let i=1;i<path.length;i++) {
      const a=path[i-1],b=path[i];
      if (a[0]<=f && f<=b[0]) return a[1]+(b[1]-a[1])*(f-a[0])/(b[0]-a[0]);
    }
    return f>1?path.at(-1)[1]:path[0][1];
  }
  function normalize(points, world) {
    const e=world.editor;
    if (points.length<2 || points.length>800 || Math.hypot(points[0][0]-90,points[0][1]-230)>e.radius+.01 || Math.hypot(points.at(-1)[0]-770,points.at(-1)[1]-230)>e.radius+.01) return null;
    const result=[];
    for (const [x,y] of points) {
      if (x<90-e.radius || x>770+e.radius || Math.abs(y-230)>e.max_deviation+.01) return null;
      const f=clamp((x-90)/680,0,1);
      if (result.length && f<=result.at(-1)[0]) {
        if (f<result.at(-1)[0]-.04) return null;
        continue;
      }
      result.push([f,y-230]);
    }
    if (result.length<2) return null;
    result[0][0]=0; result.at(-1)[0]=1;
    return result;
  }
  function schedule(world) {
    const s=world.spec, events=[];
    for(let parcel=0;parcel<s.parcel_count;parcel++) for(let i=0;i<s.workers;i++) {
      const t=s.first_pickup_ms+parcel*s.period_ms+i*(s.travel_ms+s.gap_ms);
      events.push([t,i,parcel,"catch",0],[t+s.travel_ms/2,i,parcel,"seal",.5],[t+s.travel_ms,i,parcel,"pass",1]);
    }
    return events.sort((a,b)=>a[0]-b[0] || a[1]-b[1] || a[2]-b[2] || a[3].localeCompare(b[3]));
  }
  function passportPosition(world,parcel,ms,deliveryTimes) {
    return [world.stations_x.at(-1)+world.collection.travel_x*(ms-deliveryTimes[parcel])/world.spec.collection_ms,
      motor(world,world.spec.workers,ms)];
  }
  class Relay {
    constructor(world,path) {
      this.world=world; this.s=world.spec; this.path=path;
      this.ms=0; this.y=Array(this.s.workers).fill(this.s.initial_y);
      this.v=Array(this.s.workers).fill(0); this.targets=[...this.y];
      this.custody=Array(this.s.parcel_count).fill(0); this.seals=Array(this.s.parcel_count).fill(0);
      this.delivered=0; this.failed=""; this.contact_index=0; this.contacts=schedule(world); this.contact_log=[];
      this.collected=Array(this.s.parcel_count).fill(false);this.delivery_times=Array(this.s.parcel_count).fill(null);this.outgoing=null;
    }
    advance(end) {
      const s=this.s;
      while(this.ms+s.tick_ms<=end && !this.failed && !this.collected.every(Boolean)) {
        this.ms+=s.tick_ms; const dt=s.tick_ms/1000;
        for(let i=0;i<s.workers;i++) {
          const a=clamp(s.kp*(this.targets[i]-this.y[i])-s.kd*this.v[i],-s.acceleration,s.acceleration);
          this.v[i]=clamp(this.v[i]+a*dt,-s.speed,s.speed);
          this.y[i]=clamp(this.y[i]+this.v[i]*dt,s.min_y,s.max_y);
          if(this.y[i]===s.min_y || this.y[i]===s.max_y) this.v[i]=0;
        }
        while(this.contact_index<this.contacts.length && this.contacts[this.contact_index][0]<=this.ms) {
          const [t,i,parcel,kind,f]=this.contacts[this.contact_index++];
          const index=kind==="catch"?i:kind==="seal"?s.workers+1+i:i+1;
          const desired=motor(this.world,index,t),actual=this.y[i]+pathY(this.path,f);
          if(Math.abs(actual-desired)>s.tolerance+1e-7) {this.failed=`Parcel ${parcel+1}: worker ${i+1} missed ${kind}.`;return;}
          if(kind==="catch") {
            if(this.custody[parcel]!==i) {this.failed="Parcel was not on the incoming tray.";return;}
            this.custody[parcel]=-(i+1);
          } else if(kind==="seal") {
            if(this.custody[parcel]!==-(i+1)) {this.failed="Seal has no physical parcel.";return;}
            this.seals[parcel]|=1<<i;
          } else {
            if(this.custody[parcel]!==-(i+1)) {this.failed="Worker released an empty hand.";return;}
            this.custody[parcel]=i+1;
            if(i===s.workers-1) {
              if(this.seals[parcel]!==((1<<s.workers)-1)) {this.failed="Customs seals are incomplete.";return;}
              if(this.outgoing!==null) {this.failed="The output counter is occupied by an uncollected passport.";return;}
              this.delivery_times[parcel]=t;this.outgoing=parcel;
              this.delivered++;
            }
          }
          this.contact_log.push({t_ms:t,worker:i,parcel,kind,hand_y:round(actual),tray_y:round(desired)});
        }
        if(this.outgoing!==null && this.ms-this.delivery_times[this.outgoing]>=s.collection_ms)
          this.failed=`Passport ${this.outgoing+1} left the customs counter.`;
      }
    }
    collect(point) {
      const p=this.outgoing;
      if(p===null || this.failed || this.collected.every(Boolean)) return false;
      const [x,y]=passportPosition(this.world,p,this.ms,this.delivery_times),box=this.world.collection;
      if(Math.abs(point[0]-x)>box.width/2 || Math.abs(point[1]-y)>box.height/2) {
        this.failed="Missed the moving passport.";return false;
      }
      this.collected[p]=true;this.outgoing=null;return true;
    }
    snapshot() {
      return {ms:this.ms,y:this.y.map(round),v:this.v.map(round),targets:this.targets.map(round),
        custody:[...this.custody],seals:[...this.seals],delivered:this.delivered,failed:this.failed,contacts:this.contact_index,
        collected:[...this.collected],delivery_times:[...this.delivery_times],outgoing:this.outgoing};
    }
  }
  // Read-only diagnostics support implementation checks and privileged oracle
  // planning. They are not controls and are forbidden to screenshot-only agents.
  window.ClockworkRelayPhysics={Relay,motor,pathY,normalize,schedule,passportPosition};
  function record(type,details={}) {
    const t=type.startsWith("lever_")||type==="inspect"||type==="collect"||type==="verify"?model.boundary:now();
    const event={seq:model.events.length+1,t_ms:t,type,...details};model.events.push(event);return event;
  }
  function point(event,canvas) {
    const r=canvas.getBoundingClientRect();
    return [round(clamp((event.clientX-r.left)*canvas.width/r.width,0,canvas.width)),
            round(clamp((event.clientY-r.top)*canvas.height/r.height,0,canvas.height))];
  }
  function sync() {
    model.boundary=now();
    if(model.sim && !model.terminal) model.sim.advance(model.boundary-model.deployedAt);
  }
  function hand(i,ms) {
    const s=model.world.spec,first=s.first_pickup_ms+i*(s.travel_ms+s.gap_ms);
    let local=ms-first;
    if(local<0) return [model.world.stations_x[i],model.sim.y[i]+pathY(model.path,0)];
    local%=s.period_ms;
    const f=local<=s.travel_ms?local/s.travel_ms:1-(local-s.travel_ms)/(s.period_ms-s.travel_ms);
    return [model.world.stations_x[i]+f*(model.world.stations_x[i+1]-model.world.stations_x[i]),model.sim.y[i]+pathY(model.path,f)];
  }
  function ring(c,x,y,r,color,label) {
    c.strokeStyle=color;c.fillStyle="#12292b";c.lineWidth=3;
    c.beginPath();c.arc(x,y,r,0,Math.PI*2);c.fill();c.stroke();
    c.fillStyle=color;c.font="bold 12px monospace";c.textAlign="center";c.fillText(label,x,Math.max(72,y-r-12));
  }
  function drawMotor(c,index,x,ms,color,label) {
    const w=model.world,s=w.spec,y=motor(w,index,ms),r=s.tolerance+12;
    c.strokeStyle="#42605b";c.lineWidth=1;c.beginPath();c.moveTo(x,s.min_y);c.lineTo(x,s.max_y);c.stroke();
    c.strokeStyle=color+"70";c.lineWidth=5;c.beginPath();
    for(let age=500;age>=0;age-=50) {const yy=motor(w,index,Math.max(0,ms-age));age===500?c.moveTo(x,yy):c.lineTo(x,yy);}
    c.stroke();ring(c,x,y,r,color,label);
    const v=(motor(w,index,ms+10)-motor(w,index,Math.max(0,ms-10)))/.02;
    c.strokeStyle=color;c.lineWidth=2;c.beginPath();c.moveTo(x+r+7,y);c.lineTo(x+r+7,y+clamp(v*.35,-36,36));c.stroke();
  }
  function drawDrivePins(c,index,x,ms,color) {
    const w=model.world,s=w.spec,k=Math.min(Math.floor(ms/s.motor_span_ms),w.motors[index].length-2);
    const [origin,pin]=w.motors[index].slice(k,k+2),r=s.tolerance+12;
    // Dedicated side markers remain outside the contact ring and the outgoing
    // passport. Drawing them last prevents a hand from hiding the motion cue.
    const side=index===0?1:-1,ox=x+side*(r+24),px=x+side*(r+10);
    c.strokeStyle=color+"77";c.lineWidth=1;c.setLineDash([3,5]);c.beginPath();
    c.moveTo(ox,origin);c.lineTo(px,pin);c.stroke();c.setLineDash([]);
    c.fillStyle="#12292b";c.fillRect(ox-5,origin-5,10,10);c.strokeStyle=color;c.lineWidth=2;c.strokeRect(ox-5,origin-5,10,10);
    c.fillStyle=color;c.beginPath();c.moveTo(px,pin-5);c.lineTo(px+5,pin);c.lineTo(px,pin+5);c.lineTo(px-5,pin);c.closePath();c.fill();
  }
  function driveNames() {
    const n=model.world.spec.workers;
    return ["IN",...Array.from({length:n-1},(_,i)=>`TRAY${i+1}`),"OUT",
      ...Array.from({length:n},(_,i)=>`SEAL${i+1}`)];
  }
  function inspectionBox(index) {
    const n=model.world.spec.workers,width=824/(2*n+1);
    // Headers follow the physical relay: IN, SEAL1, TRAY1, ..., OUT.
    // Motor identities stay unchanged; LIFT ABOVE names the mechanism below.
    const column=index<=n?2*index:2*(index-n-1)+1;
    // The highest output passport starts at y=64. Keep its entire pickup
    // rectangle below the inspection controls, including their border.
    return [18+column*width,30,width-6,32];
  }
  function inspectionAt(point) {
    return model.inspected.findIndex((_,i)=>{
      const [x,y,w,h]=inspectionBox(i);
      return point[0]>=x && point[0]<=x+w && point[1]>=y && point[1]<=y+h;
    });
  }
  function drawInspections(c,ms) {
    const w=model.world,s=w.spec,names=driveNames();
    // Safe bench inspection reveals startup data only. Advancing the bench
    // clock must never disclose a later segment that DEPLOY would replay.
    const segment=model.sim?Math.min(Math.floor(ms/s.motor_span_ms),w.motors[0].length-2):0;
    for(let i=0;i<names.length;i++) {
      const [x,y,width,height]=inspectionBox(i),open=model.inspected[i];
      c.fillStyle=open?"#254b40":"#554c38";c.fillRect(x,y,width,height);
      c.strokeStyle=open?"#a3cebb":"#cfb57d";c.lineWidth=2;c.strokeRect(x,y,width,height);
      c.fillStyle=open?"#c9e4cf":"#f3d69a";c.textAlign="center";c.font="bold 11px monospace";
      c.fillText(open?`${names[i]} · OPEN`:`LIFT ${names[i]}`,x+width/2,y+12);
      if(open) {
        const [a,b]=w.motors[i].slice(segment,segment+2);
        c.font="12px monospace";c.fillText(`${a}>${b}`,x+width/2,y+26);
      } else {c.font="10px monospace";c.fillText("INSPECTION COVER",x+width/2,y+26);}
      if(!model.sim) {
        // Animate only the known startup pair, forwards and backwards. This
        // preview does not traverse the live tape. Later pairs appear only
        // when their segment becomes current in the deployed relay.
        c.fillStyle="#152e2b";c.fillRect(x,84,width,86);
        if(open) {
          const [a,b]=w.motors[i];
          const phase=(ms%(2*s.motor_span_ms))/s.motor_span_ms;
          const f=phase<=1?phase:2-phase;
          const preview=a+(b-a)*f*f*(3-2*f);
          const py=value=>90+(value-s.min_y)*72/(s.max_y-s.min_y),cx=x+width/2;
          c.strokeStyle="#5b8e7b";c.lineWidth=2;c.beginPath();c.moveTo(cx,90);c.lineTo(cx,162);c.stroke();
          c.strokeStyle="#d6be82";c.beginPath();c.moveTo(cx-16,py(a));c.lineTo(cx+16,py(b));c.stroke();
          c.fillStyle="#c9e4cf";c.beginPath();c.arc(cx,py(preview),5,0,Math.PI*2);c.fill();
          c.font="10px monospace";c.fillText("STARTUP ONLY",cx,78);
        } else {c.fillStyle="#9a987d";c.font="11px monospace";c.fillText("CLOSED",x+width/2,130);}
      } else if(!open) {
        // Cover the actual contact mechanism, including its parcel and pins.
        // Hiding only the numeric register would leave the needed motion visible.
        const station=i<=s.workers,px=station?w.stations_x[i]:w.seals_x[i-s.workers-1];
        c.fillStyle="#24332f";c.fillRect(px-48,78,96,332);
        c.strokeStyle="#9b916b";c.lineWidth=2;c.strokeRect(px-48,78,96,332);
        c.fillStyle="#d5c693";c.font="bold 11px monospace";c.fillText(names[i],px,204);
        c.font="10px monospace";c.fillText("COVERED",px,225);c.fillText("LIFT ABOVE",px,244);
      }
    }
  }
  function draw() {
    const canvas=document.getElementById("cd2-stage"),c=canvas.getContext("2d"),w=model.world,s=w.spec;
    // Collection can finish synchronously in the pointer handler. Render the
    // physical count even after finish() marks the episode terminal.
    document.getElementById("cd2-count").textContent=`${model.sim?model.sim.collected.filter(Boolean).length:0} / 3 CLEARED`;
    const gradient=c.createLinearGradient(0,0,0,460);gradient.addColorStop(0,"#112729");gradient.addColorStop(1,"#091718");
    c.fillStyle=gradient;c.fillRect(0,0,860,460);
    c.strokeStyle="#254342";c.lineWidth=1;
    for(let y=64;y<420;y+=32){c.beginPath();c.moveTo(16,y);c.lineTo(844,y);c.stroke();}
    c.fillStyle="#95af9d";c.font="12px monospace";c.textAlign="left";
    if(!model.sim) {
      c.fillText("LIFT DRIVE HOUSINGS · STARTUP PREVIEW ONLY · THEN CUT A CAM",25,22);
      c.fillStyle="#34453a";c.fillRect(90,202,680,56);c.strokeStyle="#c5a66c";c.strokeRect(90,202,680,56);
      ring(c,90,230,28,"#edb85c","CATCH");ring(c,770,230,28,"#73cad2","PASS");
      c.strokeStyle="#e8c684";c.lineWidth=3;c.beginPath();
      (model.recording||model.rawPath||[]).forEach((p,i)=>i?c.lineTo(...p):c.moveTo(...p));c.stroke();
      c.fillStyle="#dfd5b5";c.font="19px Georgia";c.textAlign="center";
      c.fillText("Your recorded sweep becomes every worker’s repeating hand motion.",430,310);
      c.fillStyle="#a6b6a1";c.font="14px monospace";
      c.fillText("Startup preview only. Watch new drive pairs after DEPLOY; covers stay open.",430,342);
      c.fillText("Click each moving passport at OUT before it crosses the exit line.",430,374);
      c.fillText("A missed contact, pickup or departing passport ends the relay.",430,401);
    } else {
      const ms=model.sim.ms;
      if(!model.terminal && !model.sim.failed && !model.sim.collected.every(Boolean)) {
        model.helpers.setReadout(model.sim.outgoing===null
          ?"LIVE RELAY · CORRECT THE HANDS BEFORE EACH CONTACT"
          :"PICK UP THE MOVING PASSPORT AT OUT · WATCH THE EXIT LINE","idle");
      }
      c.fillText("MOVING TRAYS · WATCH THE NEXT CONTACT",25,23);
      c.textAlign="right";
      const clock=(model.terminal?model.finishedAt:model.boundary)-model.deployedAt;
      c.fillText(`DRIVE ${ms%s.motor_span_ms}/${s.motor_span_ms} ms · RELAY ${clock} ms`,844,23);
      for(let i=0;i<=s.workers;i++)if(model.inspected[i])drawMotor(c,i,w.stations_x[i],ms,"#a3cebb",i===0?"IN":i===s.workers?"OUT":`TRAY ${i}`);
      for(let i=0;i<s.workers;i++)if(model.inspected[s.workers+1+i])drawMotor(c,s.workers+1+i,w.seals_x[i],ms,colors[i],`SEAL ${i+1}`);
      c.strokeStyle="#e8c684";c.lineWidth=2;c.setLineDash([4,4]);c.beginPath();
      c.moveTo(w.stations_x.at(-1)+w.collection.travel_x,50);c.lineTo(w.stations_x.at(-1)+w.collection.travel_x,405);c.stroke();c.setLineDash([]);
      for(let i=0;i<s.workers;i++) {
        const [x,y]=hand(i,ms),color=colors[i];
        c.strokeStyle=color+"77";c.lineWidth=2;c.beginPath();c.moveTo(w.stations_x[i],model.sim.y[i]);c.lineTo(w.stations_x[i+1],model.sim.y[i]);c.stroke();
        c.strokeStyle=color;c.lineWidth=2;c.fillStyle="#27352d";c.beginPath();c.arc(x,y,12,0,Math.PI*2);c.fill();c.stroke();
        c.fillStyle=color;c.font="bold 12px monospace";c.textAlign="center";c.fillText(i+1,x,y+4);
        const next=model.sim.contacts.slice(model.sim.contact_index).find(e=>e[1]===i);
        const phase=next?clamp(1-(next[0]-ms)/s.travel_ms,0,1):1;
        const sx=w.seals_x[i];c.fillStyle="#334940";c.fillRect(sx-68,422,136,9);c.fillStyle=color;c.fillRect(sx-68,422,136*phase,9);
        c.fillStyle="#ced9be";c.font="11px monospace";c.fillText(next?`${i+1} · ${next[3].toUpperCase()}`:`${i+1} · DONE`,sx,451);
      }
      for(let p=0;p<s.parcel_count;p++) {
        const cust=model.sim.custody[p];
        if(model.sim.collected[p])continue;
        if(cust>=0 && !model.inspected[cust])continue;
        let pos;
        if(cust===s.workers)pos=passportPosition(w,p,ms,model.sim.delivery_times);
        else if(cust<0)pos=hand(-cust-1,ms);
        else {
          const ready=s.first_pickup_ms+p*s.period_ms;
          if(cust===0 && ms<ready-1000)continue;
          pos=[w.stations_x[cust],motor(w,cust,ms)];
        }
        const outgoing=cust===s.workers,hw=outgoing?w.collection.width/2:11,hh=outgoing?w.collection.height/2:8;
        c.fillStyle="#f2e1b6";c.strokeStyle=outgoing?"#fff2ce":"#403e2b";c.lineWidth=2;
        c.fillRect(pos[0]-hw,pos[1]-hh,hw*2,hh*2);c.strokeRect(pos[0]-hw,pos[1]-hh,hw*2,hh*2);
        for(let i=0;i<s.workers;i++)if(model.sim.seals[p]&(1<<i)){c.fillStyle=colors[i];c.fillRect(pos[0]-8+i*6,pos[1]-3,4,6);}
        if(outgoing){c.fillStyle="#283e34";c.font="bold 11px monospace";c.textAlign="center";c.fillText(`P${p+1}`,pos[0],pos[1]-7);
          c.fillStyle="#f2e1b6";c.fillText("PICK UP",Math.min(811,pos[0]),pos[1]-hh-10);}
      }
      for(let i=0;i<=s.workers;i++)if(model.inspected[i])drawDrivePins(c,i,w.stations_x[i],ms,"#a3cebb");
      for(let i=0;i<s.workers;i++)if(model.inspected[s.workers+1+i])drawDrivePins(c,s.workers+1+i,w.seals_x[i],ms,colors[i]);
    }
    drawInspections(c,model.sim?model.sim.ms:now());
    const lc=document.getElementById("cd2-levers").getContext("2d");lc.fillStyle="#d0bd90";lc.fillRect(0,0,240,460);
    lc.fillStyle="#37463d";lc.font="bold 12px monospace";lc.textAlign="center";lc.fillText("HAND HEIGHT",120,28);
    for(let i=0;i<s.workers;i++) {
      const x=w.lever.xs[i],target=model.sim?model.sim.targets[i]:230,y=model.sim?model.sim.y[i]:230;
      lc.strokeStyle="#8d805e";lc.lineWidth=7;lc.beginPath();lc.moveTo(x,s.min_y);lc.lineTo(x,s.max_y);lc.stroke();
      lc.strokeStyle="#302e23";lc.lineWidth=2;lc.strokeRect(x-25,target-16,50,32);
      lc.fillStyle=colors[i];lc.fillRect(x-24,target-15,48,30);
      lc.fillStyle="#263930";lc.font="bold 14px monospace";lc.fillText(i+1,x,target+5);
      lc.fillStyle="#254f46";lc.beginPath();lc.arc(x+27,y,4,0,Math.PI*2);lc.fill();
      if(model.sim) {lc.strokeStyle="#254f46";lc.lineWidth=2;lc.beginPath();lc.moveTo(x+27,y);lc.lineTo(x+27,y+clamp(model.sim.v[i]*.2,-25,25));lc.stroke();}
      lc.fillStyle="#3c4635";lc.font="11px monospace";lc.fillText(`SELF ${i+1}`,x,432);
    }
  }
  async function finish() {
    if(model.terminal)return;
    sync();record("verify");model.finishedAt=model.boundary;model.terminal=true;
    const sim=model.sim;
    const data={mechanic_id:ID,task_id:model.state.task_id,challenge_id:model.state.challenge_id,revision:REVISION,
      interaction_mode:model.mode,events:model.events,final_state:sim?sim.snapshot():null};
    model.lastPayload=data;
    document.getElementById("cd2-deploy").disabled=true;document.getElementById("cd2-submit").disabled=true;
    model.helpers.setReadout(sim?.failed?`FAIL · ${sim.failed}`:"CHECKING CUSTOMS LOG…","pending");
    try {
      const response=await fetch("/result",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(data)});
      const result=await response.json();model.lastGrade=result;
      const passed=result.passed===true;
      model.helpers.setReadout(passed?"PASS · THREE PASSPORTS CLEARED":`FAIL · ${sim?.failed||"INCOMPLETE RELAY"}`,passed?"passed":"error");
      document.querySelector(".cd2-office").dataset.verdict=passed?"pass":"fail";
      document.getElementById("cd2-verdict").textContent=passed?"PASS":"FAIL";
    } catch(error) {model.helpers.setReadout(`VERIFIER ERROR · ${error.message}`,"error");}
    draw();
  }
  function tick() {
    if(!model)return;
    sync();draw();
    if(model.sim && !model.terminal) {
      if(model.sim.failed)finish();
      else if(model.sim.collected.every(Boolean))finish();
    }
  }
  async function render(state,helpers) {
    clearInterval(timer);
    document.body.dataset.mechanic="clockwork-customs-v3";
    model={state,world:structuredClone(state.world),helpers,mode:state.control_condition.interaction,
      epoch:performance.now(),events:[],path:null,rawPath:null,recording:null,hold:null,sim:null,
      deployedAt:0,boundary:0,finishedAt:null,terminal:false,lastPayload:null,lastGrade:null,
      inspected:Array(2*state.world.spec.workers+1).fill(false)};
    window.clockworkDoppelgangerCustomsV3Model=model;
    const instruction=model.mode==="full"?"DRAG each lever handle to correct its worker":"CLICK a worker’s rail to set its hand height";
    helpers.app.innerHTML=`<section class="cd2-office" data-interaction="${model.mode}" data-verdict="">
      <header class="cd2-head"><div><p>TEMPORAL CUSTOMS BUREAU · RECORDED SELVES</p><h1>Clockwork Doppelgänger Customs V3</h1></div><div class="cd2-badge">THREE<br>PASSPORTS</div></header>
      <div class="cd2-instruction"><span>LIFT drive covers; the safe bench previews only startup motion. Covers stay open. Record CATCH → PASS. Deploy. ${instruction}; rings must contain the hands at each contact. Watch the live drives and CLICK moving passports at OUT. One miss ends the relay.</span><b id="cd2-count">0 / 3 CLEARED</b></div>
      <main><canvas id="cd2-stage" width="860" height="460" aria-label="Recorded customs relay"></canvas><canvas id="cd2-levers" width="240" height="460" aria-label="Clockwork hand height levers"></canvas></main>
      <footer><div class="readout">RECORD A SWEEP THROUGH THE SLOT</div><button id="cd2-deploy" disabled>DEPLOY SELVES</button><button id="cd2-submit">FILE LOG</button></footer>
      <div id="cd2-verdict" aria-live="assertive"></div></section>`;
    const stage=document.getElementById("cd2-stage"),lever=document.getElementById("cd2-levers");
    stage.addEventListener("pointerdown",e=>{
      if(model.terminal||e.button!==0||model.recording)return;
      const p=point(e,stage),inspection=inspectionAt(p);
      if(inspection>=0) {
        if(model.hold!==null || model.inspected[inspection])return;
        sync();if(model.sim?.failed){finish();return;}
        record("inspect",{drive:inspection,point:p,input_source:"housing_click"});
        model.inspected[inspection]=true;e.preventDefault();draw();return;
      }
      if(model.sim) {
        sync();if(model.sim.failed){finish();return;}
        if(model.sim.outgoing===null || model.hold!==null)return;
        record("collect",{point:p,input_source:"passport_click"});
        model.sim.collect(p);e.preventDefault();draw();
        if(model.sim.failed || model.sim.collected.every(Boolean))finish();
        return;
      }
      if(Math.hypot(p[0]-90,p[1]-230)>28)return;
      e.preventDefault();stage.setPointerCapture(e.pointerId);model.recordPointer=e.pointerId;
      model.recording=[p];record("record_start",{point:p,input_source:"record_drag"});draw();
    });
    stage.addEventListener("pointermove",e=>{
      if(!model.recording||model.recordPointer!==e.pointerId)return;
      const p=point(e,stage);model.recording.push(p);record("record_move",{point:p,input_source:"record_drag"});draw();
    });
    const endRecord=e=>{
      if(!model.recording||model.recordPointer!==e.pointerId)return;
      const p=point(e,stage);model.recording.push(p);
      const path=normalize(model.recording,model.world);
      // A canceled gesture ends at its visible last point and is checked by the
      // same normalizer; no cancellation can invent an accepted cam.
      const accepted=path!==null;
      record("record_end",{point:p,input_source:"record_drag",accepted});
      if(accepted){model.path=path;model.rawPath=model.recording;document.getElementById("cd2-deploy").disabled=false;helpers.setReadout("CAM CUT · DEPLOY YOUR RECORDED SELVES","idle");}
      else helpers.setReadout("SWEEP REJECTED · CONNECT BOTH SOCKETS INSIDE THE SLOT","error");
      model.recording=null;stage.releasePointerCapture?.(e.pointerId);draw();
    };
    stage.addEventListener("pointerup",endRecord);stage.addEventListener("pointercancel",endRecord);
    document.getElementById("cd2-deploy").addEventListener("click",()=>{
      if(!model.path||model.sim||model.recording||model.terminal)return;
      model.deployedAt=record("deploy").t_ms;model.sim=new Relay(model.world,model.path);
      document.getElementById("cd2-deploy").disabled=true;helpers.setReadout("LIVE RELAY · CORRECT THE HANDS BEFORE EACH CONTACT","idle");draw();
    });
    lever.addEventListener("pointerdown",e=>{
      if(!model.sim||model.terminal||model.sim.delivered===3||e.button!==0)return;
      sync();if(model.sim.failed){finish();return;}
      if(model.sim.delivered===3)return;
      const p=point(e,lever),ls=model.world.lever;
      const i=ls.xs.findIndex(x=>Math.abs(p[0]-x)<=ls.grip_half_width);
      if(i<0)return;
      if(model.mode==="simplified") {
        record("lever_target",{worker:i,point:p,input_source:"rail_click"});model.sim.targets[i]=clamp(p[1],64,396);
      } else {
        if(model.hold!==null || Math.abs(p[1]-model.sim.targets[i])>ls.grip_half_height+.01)return;
        lever.setPointerCapture(e.pointerId);model.hold=i;model.holdPointer=e.pointerId;
        record("lever_start",{worker:i,point:p,input_source:"lever_drag"});
      }
      e.preventDefault();draw();
    });
    lever.addEventListener("pointermove",e=>{
      if(model.hold===null||model.terminal||model.holdPointer!==e.pointerId)return;
      sync();if(model.sim.failed){finish();return;}
      if(model.sim.delivered===3)return;
      const p=point(e,lever);record("lever_move",{worker:model.hold,point:p,input_source:"lever_drag"});
      model.sim.targets[model.hold]=clamp(p[1],64,396);draw();
    });
    const endLever=e=>{
      if(model.hold===null||model.terminal||model.holdPointer!==e.pointerId)return;
      sync();if(model.sim.failed){finish();return;}
      record("lever_end",{worker:model.hold,point:point(e,lever),input_source:"lever_drag"});
      model.hold=null;lever.releasePointerCapture?.(e.pointerId);draw();
    };
    lever.addEventListener("pointerup",endLever);lever.addEventListener("pointercancel",endLever);
    document.getElementById("cd2-submit").addEventListener("click",finish);
    timer=setInterval(tick,10);draw();
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics[ID]={rootSelector:".cd2-office",render};
})();
