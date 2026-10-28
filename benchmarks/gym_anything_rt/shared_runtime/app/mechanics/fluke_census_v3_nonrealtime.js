(() => {
  'use strict';
  let current;
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  function outline(a) {
    const n=3+a.species*5, points=[[-58,-28]];
    for(let side=0;side<2;side++) {
      const from=side===0?[-58,-28]:[0,n], to=side===0?[0,n]:[58,-28];
      for(let i=0;i<3;i++)for(const [f,d] of [[.18,0],[.48,a.notches[side*3+i]],[.78,0]]) {
        const u=(i+f)/3;points.push([from[0]+(to[0]-from[0])*u,from[1]+(to[1]-from[1])*u+d]);
      }
      points.push(to);
    }
    return points.concat([[52,4],[38,26],[14,38],[0,31],[-14,38],[-38,26],[-52,4]]);
  }
  function pose(a,ms) {
    const s=a.motion,p=s.phase,u=ms/1000*s.rate;
    return [s.cx+s.ax*Math.sin(u+p[0])+s.bx*Math.sin(u*Math.sqrt(2)+p[1]),
      s.cy+s.ay*Math.sin(u*Math.sqrt(.7)+p[2])+s.by*Math.sin(u*Math.sqrt(3)+p[3]),
      s.base_angle+s.turn*Math.sin(u*Math.sqrt(1.3)+p[4]),a.scale];
  }
  function transform(points,p) {
    const [x,y,a,s]=p,c=Math.cos(a),sn=Math.sin(a);
    return points.map(([u,v])=>[x+s*(u*c-v*sn),y+s*(u*sn+v*c)]);
  }
  function inside([x,y],poly) {
    let hit=false;
    for(let i=0;i<poly.length;i++){const [ax,ay]=poly[i],[bx,by]=poly[(i+poly.length-1)%poly.length];if((ay>y)!=(by>y)&&x<(bx-ax)*(y-ay)/(by-ay)+ax)hit=!hit;}
    return hit;
  }
  function overlaps(a,b) {
    if(a.some(p=>inside(p,b))||b.some(p=>inside(p,a)))return true;
    const cross=(p,q,r)=>(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]);
    for(let i=0;i<a.length;i++)for(let j=0;j<b.length;j++) {
      const p=a[i],q=a[(i+a.length-1)%a.length],r=b[j],s=b[(j+b.length-1)%b.length];
      if(cross(p,q,r)*cross(p,q,s)<0&&cross(r,s,p)*cross(r,s,q)<0)return true;
    }
    return false;
  }
  class Camera {
    constructor(world){this.world=world;this.ms=0;this.point=[...world.camera.initial];this.target=[...this.point];this.velocity=[0,0];}
    clamp(p){const c=this.world.camera,s=this.world.stage;return [clamp(p[0],c.width/2,s.width-c.width/2),clamp(p[1],c.height/2,s.height-c.height/2)];}
    advance(ms){
      const c=this.world.camera;
      while(this.ms+10<=ms){
        this.ms+=10;
        let a=this.point.map((v,i)=>(this.target[i]-v)*64-this.velocity[i]*16),mag=Math.hypot(...a);
        if(mag>c.acceleration)a=a.map(v=>v*c.acceleration/mag);
        this.velocity=this.velocity.map((v,i)=>v+a[i]*.01);mag=Math.hypot(...this.velocity);
        if(mag>c.speed)this.velocity=this.velocity.map(v=>v*c.speed/mag);
        const raw=this.point.map((v,i)=>v+this.velocity[i]*.01);this.point=this.clamp(raw);
        raw.forEach((v,i)=>{if(v!==this.point[i])this.velocity[i]=0;});
      }
    }
  }
  // Read-only diagnostic access is evidence tooling, never a model action.
  window.FlukeCensusV3Geometry={outline,pose,transform,inside,overlaps,Camera};
  function render(state,helpers) {
    if(current){current.dead=true;window.removeEventListener('keydown',current.key);cancelAnimationFrame(current.frame);}
    const mode=state.control_condition?.interaction||'full';
    const m={state,mode,helpers,started:performance.now(),ms:0,phase_ms:0,events:[],camera:new Camera(state),drag:null,pin:null,
      archived:[],shot:null,marks:{},selected:'a',fieldNotes:new Set(),terminal:false,dead:false,frame:0};
    current=m;window.flukeCensusV3Model=m;
    document.body.dataset.mechanic='fluke-census-v2';
    helpers.app.innerHTML=`<main class="fluke-census-v2" data-interaction="${mode}">
      <header><div><small>NORTH SOUND / INDIVIDUAL SURVEY</small><h1>Fluke Census <em>III</em></h1></div><div class="fc2-total"><b id="fc2-count">0</b><span>INDIVIDUALS<br>ARCHIVED</span><strong id="fc2-time">4:00</strong></div></header>
      <div class="fc2-work"><section class="fc2-water"><canvas id="fc2-sea" width="860" height="460" aria-label="Stable-phase whale flukes and camera frame"></canvas><div class="fc2-water-label">NORTH SOUND <span>STABLE PHASE · 0.6 s AIM STEP</span></div></section>
      <aside><small id="fc2-view-label">LIVE CAMERA / CLICK A SPECIMEN TO IDENTIFY</small><canvas id="fc2-photo" width="324" height="264" aria-label="Click a live specimen to identify it; mark landmarks on a photograph"></canvas>
      <div id="fc3-inspection-result" aria-live="polite">NO SAMPLE YET</div>
      <div class="fc2-pins"><button data-pin="a">● <span>TIP A</span></button><button data-pin="v">● <span>V NOTCH</span></button><button data-pin="b">● <span>TIP B</span></button></div>
      <button id="fc2-archive" disabled>Archive photograph</button><div class="fc2-list"><small>CENSUS LIST / INSPECT TO BUILD FIELD KEY</small><div id="fc2-species"></div></div>
      <p>Click a whole, clear fluke in the live camera to identify it safely. The field key keeps learned species. Photograph each WANTED individual once; tail scars distinguish individuals.</p></aside></div>
      <footer><div><b>${mode==='full'?'DRAG FRAME · SPACE TO SHOOT':'CLICK WATER TO AIM · SHUTTER TO SHOOT'}</b><span>${mode==='full'?'Drag the three pins onto the photo.':'Select each pin, then click its landmark.'} The survey view advances only after a completed aim.</span></div>${mode==='simplified'?'<button id="fc2-shutter">Shutter</button>':''}<button id="fc2-submit">Census complete →</button></footer>
      <div class="fc2-bottom"><span id="fc2-note">A clipped, covered, duplicate or off-list fluke ends this survey.</span><div class="readout" data-status="idle"></div></div>
      <div class="fc2-verdict" hidden><strong></strong><p></p></div></main>`;
    const root=helpers.app.querySelector('.fluke-census-v2'),sea=root.querySelector('#fc2-sea'),photo=root.querySelector('#fc2-photo');
    const ctx=sea.getContext('2d'),pc=photo.getContext('2d'),byId=new Map(state.animals.map(a=>[a.id,a]));
    const camera=state.camera,required=state.animals.filter(a=>state.listed_species.includes(a.species)).length;
    function sync(){if(!m.terminal){m.ms=Math.min(state.play_time_ms,Math.max(0,Math.floor((performance.now()-m.started)/10)*10));m.camera.advance(m.ms);}}
    function record(kind,source,extra={}){m.events.push({seq:m.events.length+1,kind,source,t_ms:m.ms,...extra});}
    function poly(a,t=m.phase_ms){return transform(outline(a),pose(a,t));}
    function shape(g,points){g.beginPath();points.forEach(([x,y],i)=>i?g.lineTo(x,y):g.moveTo(x,y));g.closePath();}
    function animal(g,a,t,inspection=false) {
      const p=pose(a,t),points=poly(a,t);shape(g,points);
      // The survey shows exact outlines, without the close-view pigmentation
      // and species markings. The camera samples the same moving geometry.
      g.fillStyle=inspection?['#e2e6cc','#7dbbb8','#c4a9c7'][a.species]:state.field_key.overview_ink;g.strokeStyle='#193a44';g.lineWidth=2;g.fill();g.stroke();
      g.save();g.translate(p[0],p[1]);g.rotate(p[2]);g.scale(p[3],p[3]);
      g.strokeStyle='#1d485955';g.lineWidth=1.4;g.beginPath();g.moveTo(-49,4);g.quadraticCurveTo(-30,26,-3,26);g.moveTo(49,4);g.quadraticCurveTo(30,26,3,26);g.stroke();
      g.fillStyle='#214958';
      if(inspection)for(let k=0;k<=a.species;k++){g.beginPath();g.arc((k-a.species/2)*8,26,2.2,0,Math.PI*2);g.fill();}
      g.restore();
    }
    function water(g,w,h,t) {
      const gradient=g.createLinearGradient(0,0,w,h);gradient.addColorStop(0,'#225264');gradient.addColorStop(1,'#0e303f');g.fillStyle=gradient;g.fillRect(0,0,w,h);
      g.lineWidth=1;g.strokeStyle='#9ac5ca12';
      for(let y=26;y<h;y+=38){g.beginPath();for(let x=0;x<=w;x+=12){const yy=y+3*Math.sin(x/55+t/1700);x?g.lineTo(x,yy):g.moveTo(x,yy);}g.stroke();}
    }
    function drawPhoto() {
      water(pc,photo.width,photo.height,m.shot?.phase_ms??m.phase_ms);
      const point=m.shot?.camera??m.camera.point,ms=m.shot?.phase_ms??m.phase_ms;
      pc.save();pc.scale(photo.width/camera.width,photo.height/camera.height);pc.translate(camera.width/2-point[0],camera.height/2-point[1]);
      state.animals.forEach(a=>animal(pc,a,ms,true));pc.restore();
      if(m.shot)for(const [pin,p] of Object.entries(m.marks)) {
        const x=p[0]/camera.width*photo.width,y=p[1]/camera.height*photo.height;
        pc.strokeStyle=pin==='v'?'#faaf63':'#f6ecbf';pc.lineWidth=2;pc.beginPath();pc.arc(x,y,7,0,Math.PI*2);pc.stroke();
        pc.beginPath();pc.moveTo(x-10,y);pc.lineTo(x+10,y);pc.moveTo(x,y-10);pc.lineTo(x,y+10);pc.stroke();
        pc.font='bold 11px monospace';pc.fillStyle=pc.strokeStyle;pc.fillText(pin.toUpperCase(),x+9,y-9);
      }
      root.querySelector('#fc2-view-label').textContent=m.shot?'PHOTOGRAPH / MARK THREE LANDMARKS':'LIVE CAMERA / CLICK A SPECIMEN TO IDENTIFY';
      root.querySelector('#fc2-archive').disabled=!m.shot;
      root.querySelectorAll('[data-pin]').forEach(b=>{b.disabled=!m.shot;b.dataset.selected=m.selected===b.dataset.pin?'true':'false';});
    }
    function draw() {
      water(ctx,860,460,m.phase_ms);
      for(const a of state.animals){
        ctx.strokeStyle='#b4d8d578';ctx.lineWidth=2;ctx.beginPath();
        for(let dt=600;dt>=0;dt-=100){const p=pose(a,Math.max(0,m.phase_ms-dt));dt===600?ctx.moveTo(p[0],p[1]):ctx.lineTo(p[0],p[1]);}ctx.stroke();
        const past=pose(a,Math.max(0,m.phase_ms-600));ctx.fillStyle='#b4d8d580';ctx.beginPath();ctx.arc(past[0],past[1],3,0,Math.PI*2);ctx.fill();
      }
      state.animals.forEach(a=>animal(ctx,a,m.phase_ms));
      const [x,y]=m.camera.point;
      ctx.strokeStyle=m.shot?'#779394':'#f4c87e';ctx.lineWidth=2;
      ctx.strokeRect(x-camera.width/2,y-camera.height/2,camera.width,camera.height);
      ctx.beginPath();ctx.moveTo(x-10,y);ctx.lineTo(x+10,y);ctx.moveTo(x,y-10);ctx.lineTo(x,y+10);ctx.stroke();
      ctx.setLineDash([3,5]);ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(...m.camera.target);ctx.stroke();ctx.setLineDash([]);
      drawPhoto();root.querySelector('#fc2-count').textContent=`${m.archived.length}/${required}`;
      const remain=Math.max(0,Math.ceil((state.play_time_ms-m.ms)/1000));root.querySelector('#fc2-time').textContent=`${Math.floor(remain/60)}:${String(remain%60).padStart(2,'0')}`;
    }
    function note(s){root.querySelector('#fc2-note').textContent=s;}
    function inspect(p) {
      // Sampling is an information action, independent of the shutter. A miss,
      // clipped specimen or occlusion gives harmless, repeatable feedback.
      const point=p.map((v,i)=>v+m.camera.point[i]-(i===0?camera.width:camera.height)/2);
      const polys=state.animals.map(a=>poly(a));
      const index=polys.findLastIndex(polygon=>inside(point,polygon));
      const clear=index>=0&&polys[index].every(([x,y])=>Math.abs(x-m.camera.point[0])<=camera.width/2+1e-6&&Math.abs(y-m.camera.point[1])<=camera.height/2+1e-6)&&!polys.some((polygon,i)=>i>index&&overlaps(polys[index],polygon));
      const a=clear?state.animals[index]:null,name=a?state.field_key.species_names[a.species]:null,listed=a?state.listed_species.includes(a.species):null;
      record('inspect','camera_click',{point:p,animal_id:a?.id??null,species_name:name,listed});
      root.querySelector('#fc3-inspection-result').textContent=a?`LAST SAMPLE: ${name} / ${listed?'WANTED':'OFF LIST'}`:'NO CLEAR SPECIMEN / REFRAME AND INSPECT';
      if(a){m.fieldNotes.add(a.species);drawFieldKey();}
      draw();
    }
    function coords(e,canvas,w,h){const r=canvas.getBoundingClientRect();return [clamp((e.clientX-r.left)*w/r.width,0,w),clamp((e.clientY-r.top)*h/r.height,0,h)];}
    function verdict(label,message) {const v=root.querySelector('.fc2-verdict');v.hidden=false;v.querySelector('strong').textContent=label;v.querySelector('p').textContent=message;root.dataset.verdict=label==='PASS'?'pass':'fail';}
    async function close(reason='') {
      if(m.terminal)return;sync();record(reason?'failure':'submit',reason?'world':'census_button',{reason});m.terminal=true;
      if(reason)verdict('FAIL',reason);else verdict('CHECKING','Census submitted.');
      const payload={mechanic_id:state.mechanic_id,task_id:state.task_id,challenge_id:state.challenge_id,control_condition:state.control_condition,interaction_mode:mode,events:m.events};
      try{const r=await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),result=await r.json();m.outcome=result;helpers.setReadout(result.passed?'PASS':'FAIL',result.passed?'passed':'error');verdict(result.passed?'PASS':'FAIL',result.passed?'Every listed individual was photographed and landmarked once.':reason||'Incomplete census or invalid photograph. This attempt has ended.');}
      catch(error){m.transportError=String(error);helpers.setReadout('VERIFIER ERROR','error');verdict('ERROR','Census could not be verified.');}
      draw();
    }
    function shutter() {
      if(m.terminal||m.shot||m.pin)return;
      if(m.drag){note('Release the camera frame before taking a photograph.');return;}
      sync();
      const polys=state.animals.map(a=>poly(a)),center=m.camera.point;
      let index=-1;for(let i=polys.length-1;i>=0;i--)if(inside(center,polys[i])){index=i;break;}
      let reason='';
      if(index<0)reason='The crosshair missed a fluke.';
      else if(polys[index].some(([x,y])=>Math.abs(x-center[0])>camera.width/2+1e-6||Math.abs(y-center[1])>camera.height/2+1e-6))reason='A fluke edge was clipped by the frame.';
      else if(polys.some((p,i)=>i>index&&overlaps(polys[index],p)))reason='Another fluke covered the photograph.';
      const a=index<0?null:state.animals[index];
      if(!reason&&m.archived.includes(a.id))reason='A duplicate individual ended the census.';
      if(!reason&&!state.listed_species.includes(a.species))reason='An off-list individual ended the census.';
      record('shutter',mode==='full'?'space':'shutter_button',{animal_id:a?.id??null});
      if(reason){close(reason);return;}
      m.shot={id:a.id,phase_ms:m.phase_ms,camera:[...m.camera.point]};m.marks={};m.selected='a';note('Mark both outer tips and the central V. Reposition inaccurate pins before archiving.');draw();
    }
    function annotationValid() {
      if(!m.shot||!['a','v','b'].every(k=>m.marks[k]))return false;
      const a=byId.get(m.shot.id),p=transform([[-58,-28],[0,3+a.species*5],[58,-28]],pose(a,m.shot.phase_ms));
      const e=p.map(([x,y])=>[x-m.shot.camera[0]+camera.width/2,y-m.shot.camera[1]+camera.height/2]),d=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]),t=state.parameters.landmark_tolerance;
      return d(m.marks.v,e[1])<=t&&((d(m.marks.a,e[0])<=t&&d(m.marks.b,e[2])<=t)||(d(m.marks.b,e[0])<=t&&d(m.marks.a,e[2])<=t));
    }
    sea.onpointerdown=e=>{
      if(m.terminal||m.shot||e.button!==0)return;sync();const p=coords(e,sea,860,460);
      if(mode==='simplified'){m.camera.target=m.camera.clamp(p);record('aim_click','aim_click',{point:p});m.phase_ms=Math.min(state.phase_max_ms,m.phase_ms+state.phase_step_ms);}
      else if(Math.abs(p[0]-m.camera.point[0])<=camera.width/2&&Math.abs(p[1]-m.camera.point[1])<=camera.height/2){m.drag={pointer:e.pointerId,offset:p.map((v,i)=>v-m.camera.point[i])};sea.setPointerCapture(e.pointerId);record('aim_start','frame_drag',{point:p});}
      e.preventDefault();draw();
    };
    sea.onpointermove=e=>{if(m.terminal||m.shot||!m.drag||m.drag.pointer!==e.pointerId)return;sync();const p=coords(e,sea,860,460);m.camera.target=m.camera.clamp(p.map((v,i)=>v-m.drag.offset[i]));record('aim_move','frame_drag',{point:p});draw();};
    function endAim(e){if(!m.drag||m.drag.pointer!==e.pointerId)return;sync();const p=coords(e,sea,860,460);m.camera.target=m.camera.clamp(p.map((v,i)=>v-m.drag.offset[i]));record('aim_end','frame_drag',{point:p});m.drag=null;m.phase_ms=Math.min(state.phase_max_ms,m.phase_ms+state.phase_step_ms);if(sea.hasPointerCapture(e.pointerId))sea.releasePointerCapture(e.pointerId);draw();}
    sea.onpointerup=endAim;sea.onpointercancel=endAim;
    sea.onlostpointercapture=e=>{if(m.drag)endAim(e);};
    for(const button of root.querySelectorAll('[data-pin]')) {
      button.onpointerdown=e=>{
        if(m.terminal||!m.shot||e.button!==0)return;sync();
        if(mode==='full'){m.pin={id:button.dataset.pin,pointer:e.pointerId};button.setPointerCapture(e.pointerId);record('pin_start','pin_drag',{pin:m.pin.id});e.preventDefault();}
      };
      button.onclick=()=>{if(mode==='simplified'&&!m.terminal&&m.shot){sync();m.selected=button.dataset.pin;record('tool','tool_button',{pin:m.selected});draw();}};
      button.onpointerup=e=>{
        if(!m.pin||m.pin.pointer!==e.pointerId)return;sync();const r=photo.getBoundingClientRect(),id=m.pin.id;
        if(e.clientX>=r.left&&e.clientX<=r.right&&e.clientY>=r.top&&e.clientY<=r.bottom){const p=coords(e,photo,camera.width,camera.height);m.marks[id]=p;record('pin_end','pin_drag',{pin:id,point:p});}
        else record('pin_cancel','pin_drag',{pin:id});
        m.pin=null;if(button.hasPointerCapture(e.pointerId))button.releasePointerCapture(e.pointerId);draw();
      };
      const cancel=e=>{if(m.pin&&m.pin.id===button.dataset.pin&&m.pin.pointer===e.pointerId){sync();record('pin_cancel','pin_drag',{pin:m.pin.id});m.pin=null;draw();}};
      button.onpointercancel=cancel;button.onlostpointercapture=cancel;
    }
    photo.onclick=e=>{
      if(m.terminal||m.pin||m.drag||e.button!==0)return;sync();const p=coords(e,photo,camera.width,camera.height);
      if(!m.shot){inspect(p);return;}
      if(mode==='simplified'){m.marks[m.selected]=p;record('mark','photo_click',{pin:m.selected,point:p});draw();}
    };
    root.querySelector('#fc2-archive').onclick=()=>{
      if(m.terminal||!m.shot||m.pin)return;sync();const accepted=annotationValid();record('archive','archive_button',{accepted});
      if(accepted){m.archived.push(m.shot.id);m.shot=null;m.marks={};note('Photograph archived. Find an individual you have not photographed.');}
      else note('Landmarks incomplete or misplaced. Put the tip pins at the two outer tips and V at the central notch.');
      draw();
    };
    root.querySelector('#fc2-shutter')?.addEventListener('click',shutter);
    root.querySelector('#fc2-submit').onclick=()=>close();
    m.key=e=>{if(mode==='full'&&e.code==='Space'&&!e.repeat){e.preventDefault();shutter();}};window.addEventListener('keydown',m.key);
    function drawFieldKey(){
      const key=root.querySelector('#fc2-species');key.replaceChildren();
      // Card position must not encode the concealed shape/species index.
      const species=state.field_key.species_names.map((name,s)=>({name,s})).sort((a,b)=>a.name<b.name?-1:1);
      for(const {s} of species){
        const row=document.createElement('div'),cv=document.createElement('canvas');cv.width=100;cv.height=62;const g=cv.getContext('2d');
        if(m.fieldNotes.has(s)){
          g.translate(50,26);g.scale(.72,.72);shape(g,outline({species:s,notches:Array(6).fill(0)}));g.fillStyle=['#e2e6cc','#7dbbb8','#c4a9c7'][s];g.fill();g.strokeStyle='#193a44';g.stroke();
        }else{g.fillStyle='#526d71';g.font='11px monospace';g.fillText('INSPECT',23,33);}
        const name=document.createElement('span'),status=document.createElement('small');name.textContent=state.field_key.species_names[s];status.textContent=state.listed_species.includes(s)?'WANTED':'OFF LIST';
        row.append(cv,name,status);key.append(row);
      }
    }
    drawFieldKey();
    function animate(){if(m.dead)return;sync();if(!m.terminal&&m.ms>=state.play_time_ms){close('The survey expired.');}draw();if(!m.terminal)m.frame=requestAnimationFrame(animate);}
    helpers.setReadout('','idle');draw();m.frame=requestAnimationFrame(animate);
  }
  window.GymAnythingRTMechanics=window.GymAnythingRTMechanics||{};
  window.GymAnythingRTMechanics.fluke_census_v3_nonrealtime={render,rootSelector:'.fluke-census-v2'};
})();
