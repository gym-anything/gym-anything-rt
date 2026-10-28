"""Task-local oracle and pixel controllers using literal mouse/keyboard actions.

Oracle functions disclose privileged reads through read(expression). The pixel
controller uses screenshots for puzzle observations and reads only visible
control rectangles. Neither calls or mutates a game method. Headless evidence
uses a labelled Playwright adapter and does not establish native API parity.
"""
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.temporal_memory_first_change_v3 import carrier_position

MECHANIC_ID = "temporal_memory_first_change_v3"


def box(ui, selector):
    return ui.read(f'(() => {{ const b=document.querySelector({selector!r}).getBoundingClientRect(); return [b.x,b.y,b.width,b.height]; }})()')


def center(ui, selector):
    x,y,w,h=box(ui,selector)
    return [round(x+w/2),round(y+h/2)]


def click(ui, selector):
    ui.send([{"mouse":{"left_click":center(ui,selector)}}])


def snapshot(ui):
    return ui.read('({sim:firstChangeEvidenceV3Model.sim,grade:firstChangeEvidenceV3Model.serverGrade,clock:GymAnythingRTTime.status()})')


def inspect(ui, index=0):
    """Use the visible optical control, never call the browser game method."""
    view=snapshot(ui)
    if ui.read('firstChangeEvidenceV3Model.interaction')=='simplified':
        click(ui,f'#fce-lens-{index} .fce-inspect')
    else:
        world=ui.read('firstChangeEvidenceV3Model.state.world')
        x,y,w,h=box(ui,'#fce-canvas')
        point=view['sim']['lenses'][index]['position']
        ui.send([{'mouse':{'right_click':[round(x+point[0]*w/world['width']),round(y+point[1]*h/world['height'])]}}])


def discover_targets(ui, world, max_seconds=180):
    """Inspect unknown negatives, then choose order from the visible notebook.

    Carrier geometry/kinematics are privileged oracle planning. Event order and
    target_ids are never read here. The read-only discoveries mirror the drawn
    motif/time cards. All sensory and steering actions use visible input.
    """
    mode=ui.read('firstChangeEvidenceV3Model.interaction')
    rect=box(ui,'#fce-canvas')
    def screen(point):
        return [round(rect[0]+point[0]*rect[2]/world['width']),round(rect[1]+point[1]*rect[3]/world['height'])]
    if not snapshot(ui)['sim']['active']:
        click(ui,'#fce-start')
    deadline=time.monotonic()+max_seconds
    cycles=0
    while time.monotonic()<deadline:
        sim=snapshot(ui)['sim']
        assert not sim['terminal'],sim
        entries=sim['discoveries']
        reversed_entries=sorted(((v['reversal_at_ms'],oid) for oid,v in entries.items() if v['reversal_at_ms'] is not None))
        needed=len(world['initial_lenses'])
        threshold=reversed_entries[needed-1][0] if len(reversed_entries)>=needed else math.inf
        unknown=[o for o in world['carriers'] if o['id'] not in entries or
            (entries[o['id']]['reversal_at_ms'] is None and entries[o['id']]['inspected_at_ms']<threshold)]
        if not unknown:
            return dict(target_ids=[oid for _,oid in reversed_entries[:needed]],readings=entries,cycles=cycles,
                planning='Order chosen from optically revealed notebook; privileged carrier coordinates and motion for steering, no private event order.')
        carrier=min(unknown,key=lambda o:(entries.get(o['id'],{}).get('inspected_at_ms',-1),o['pattern']))
        while time.monotonic()<deadline:
            sim=snapshot(ui)['sim'];ms=sim['tick']*20
            assert not sim['terminal'],sim
            lens=sim['lenses'][0]
            actual=carrier_position(world,carrier,ms)
            if math.dist(lens['position'],actual)+carrier['radius']<world['parameters']['lens_radius']-5:
                inspect(ui)
                break
            aim=carrier_position(world,carrier,ms+(500 if ui.execution_mode=='paused' else 220))
            if mode=='full':
                ui.send([{'mouse':{'move':screen(lens['position']),'buttons':{'left_down':True}}},
                    {'mouse':{'move':screen(aim)}},{'mouse':{'buttons':{'left_up':True}}}])
            else:
                ui.send([{'mouse':{'left_click':center(ui,'#fce-lens-0 .fce-select')}},
                    {'mouse':{'left_click':screen(aim)}}])
            cycles+=1
            if ui.execution_mode!='paused':ui.wait(.18)
    raise TimeoutError('Optical discovery did not complete within the declared budget')


def solve(ui, truth, max_seconds=480):
    """Feedback every ~200 ms live / one declared native window paused.

    Motion and selected identity are privileged. Forecasts use the local exact
    generated curve at a lead appropriate to the caller's observation schedule,
    not a screen-only vision algorithm. The wall allowance stays below the
    declared 600-second native episode budget.
    """
    world=truth['world']; mode=truth.get('control_condition',{}).get('interaction','full')
    paused=getattr(ui,'execution_mode','live')=='paused'
    # A paused waypoint remains fixed over the entire 400-ms observation window.
    # Compensate for that sample interval and the inertial camera response.
    lead_ms=500 if paused else 220
    rect=box(ui,'#fce-canvas')
    def screen(point):
        return [round(rect[0]+point[0]*rect[2]/world['width']),round(rect[1]+point[1]*rect[3]/world['height'])]
    buttons={i:center(ui,f'#fce-lens-{i} .fce-select') for i in range(len(world['initial_lenses']))} if mode=='simplified' else {}
    bind_buttons={i:center(ui,f'#fce-lens-{i} .fce-bind') for i in range(len(world['initial_lenses']))} if mode=='simplified' else {}
    objects={o['id']:o for o in world['carriers']}
    onsets={e['object_id']:e['at_ms'] for e in world['changes']}
    if not snapshot(ui)['sim']['active']:
        click(ui,'#fce-start')
    deadline=time.monotonic()+max_seconds
    cycles=0
    while time.monotonic()<deadline:
        view=snapshot(ui);sim=view['sim'];ms=sim['tick']*20
        if sim['terminal']:
            assert sim['terminal']=='pass',sim
            return dict(cycles=cycles,task_ms=ms,charge_ms=sim['charge'],planning='privileged read-only truth, camera kinematics and generated local motion; every input through caller transport')
        actions=[]
        for i,oid in enumerate(truth['target_ids']):
            if ms<onsets[oid]:
                continue
            lens=sim['lenses'][i]
            actual=carrier_position(world,objects[oid],ms)
            # Reticle is an inertial camera, so aim slightly along current motion.
            aim=carrier_position(world,objects[oid],ms+lead_ms)
            if mode=='full':
                actions.extend([{'mouse':{'move':screen(lens['position']),'buttons':{'left_down':True}}},
                    {'mouse':{'move':screen(aim)}},{'mouse':{'buttons':{'left_up':True}}}])
            else:
                actions.extend([{'mouse':{'left_click':buttons[i]}},{'mouse':{'left_click':screen(aim)}}])
            # Bind only after the camera actually reaches the carrier. No snapping.
            nearest=min(objects.values(),key=lambda o:math.dist(carrier_position(world,o,ms),lens['position']))
            if lens['bound'] is None and nearest['id']==oid and math.dist(lens['position'],actual)<17:
                actions.append({'keyboard':{'keys':['Space']}} if mode=='full' else {'mouse':{'left_click':bind_buttons[i]}})
        ui.send(actions)
        cycles+=1
        if not paused: ui.wait(.18)
    raise TimeoutError('First-change oracle did not complete within the declared wall budget')


class HeadlessUI:
    """Implementation check only. Does not establish native action-space parity."""
    def __init__(self,page,execution_mode='live'):
        self.page=page;self.execution_mode=execution_mode;self.rows=[]
    def read(self,expression):return self.page.evaluate(expression)
    def wait(self,seconds):self.page.wait_for_timeout(seconds*1000)
    def send(self,actions):
        self.rows.append(actions)
        for action in actions:
            if 'mouse' in action:
                m=action['mouse']
                if 'move' in m:self.page.mouse.move(*m['move'])
                if m.get('buttons',{}).get('left_down'):self.page.mouse.down()
                if m.get('buttons',{}).get('left_up'):self.page.mouse.up()
                if 'left_click' in m:self.page.mouse.click(*m['left_click'])
                if 'right_click' in m:self.page.mouse.click(*m['right_click'],button='right')
            if 'keyboard' in action:
                for key in action['keyboard']['keys']:self.page.keyboard.press(key)
        if self.execution_mode=='paused':
            self.page.evaluate('GymAnythingRTTime.runFor(400)')
            deadline=time.monotonic()+3
            while self.page.evaluate('GymAnythingRTTime.status().phase')!='completed':
                assert time.monotonic()<deadline
                time.sleep(.015)


class ScreenshotLensController:
    """Task-specific pixel controller for optical discovery evidence.

    Only screenshots supply carrier, lens, motif and reversal observations.
    DOM access is limited to visible control rectangles. The headless adapter
    advances the existing 400-ms paused observation clock after each batch.
    This establishes browser evidence, not native action-API equivalence.
    """
    def __init__(self, ui, level, interaction, output):
        import numpy as np
        from pathlib import Path
        from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.temporal_memory_first_change_v3 import PROFILES
        self.np=np;self.ui=ui;self.level=level;self.mode=interaction
        self.profile=PROFILES[level]  # public configuration, never a seeded world
        self.output=Path(output);self.output.mkdir(parents=True,exist_ok=False)
        self.rect=box(ui,'#fce-canvas');self.scale=self.rect[2]/960
        self.book=box(ui,'#fce-notebook');self.steps=0;self.frames=[];self.previous=[];self.previous_step=0
        self.controls={name:center(ui,name) for name in ['#fce-start']}
        if interaction=='simplified':
            for i in range(self.profile['lenses']):
                for control in ['select','inspect','bind']:
                    key=f'#fce-lens-{i} .fce-{control}';self.controls[key]=center(ui,key)

    def send(self, actions):
        self.ui.send(actions);self.steps+=1

    @staticmethod
    def _components(mask):
        import numpy as np
        points=set(zip(*np.nonzero(mask)));result=[]
        while points:
            y,x=points.pop();stack=[(y,x)];x0=x1=x;y0=y1=y;count=0
            while stack:
                y,x=stack.pop();count+=1;x0=min(x0,x);x1=max(x1,x);y0=min(y0,y);y1=max(y1,y)
                for p in [(y-1,x),(y+1,x),(y,x-1),(y,x+1)]:
                    if p in points:points.remove(p);stack.append(p)
            result.append((x0,y0,x1,y1,count))
        return result

    def _glyph(self, image, point):
        x,y=map(round,point);a=self.np.asarray(image.crop((x-20,y-20,x+21,y+21)).convert('RGB'))
        mask=(a[:,:,0]>=130)&(a[:,:,1]>=180)&(a[:,:,2]>=180)
        ys,xs=self.np.nonzero(mask)
        if len(xs):
            dx=round(20-(int(xs.min())+int(xs.max()))/2)
            dy=round(20-(int(ys.min())+int(ys.max()))/2)
            mask=self.np.roll(self.np.roll(mask,dx,axis=1),dy,axis=0)
        return mask

    def view(self):
        import io,hashlib
        from PIL import Image
        data=self.ui.page.screenshot();path=self.output/f'frame-{len(self.frames):04d}.png';path.write_bytes(data)
        image=Image.open(io.BytesIO(data)).convert('RGB')
        x,y,w,h=self.rect;a=self.np.asarray(image.crop((round(x),round(y),round(x+w),round(y+h))))
        r,g,b=[a[:,:,i].astype(int) for i in range(3)]
        terminal='pass' if ((r>150)&(g>210)&(b<215)&(g-r>20)).sum()>1500 else ''
        if ((r>230)&(g>=130)&(g<175)&(b>=85)&(b<145)).sum()>1500:terminal='fail'
        bodies=[]
        mask=((r>=23)&(r<=50)&(g>=55)&(g<=95)&(b>=65)&(b<=110))|((r>=65)&(r<=105)&(g>=45)&(g<=85)&(b>=22)&(b<=60))
        for x0,y0,x1,y1,count in self._components(mask):
            if not (31<=x1-x0<=45 and 31<=y1-y0<=45 and count>=500):continue
            point=[x+(x0+x1)/2,y+(y0+y1)/2]
            glyph=self._glyph(image,point)
            bodies.append(dict(point=point,unknown=int(glyph.sum())<15,glyph=glyph))
        lenses=[]
        radius=self.profile['lens_radius']*self.scale
        for color in [[119,216,229],[255,191,113]][:self.profile['lenses']]:
            if terminal:break
            ink=self.np.all(self.np.abs(a.astype(int)-self.np.array(color))<=45,axis=2)
            score=self.np.zeros(ink.shape,dtype=int)
            for offset in [-6,-3,0,3,6]:
                score+=self.np.roll(ink,offset,axis=0);score+=self.np.roll(ink,offset,axis=1)
            candidates=self.np.argwhere(score>=7)
            best=None
            for cy,cx in candidates:
                ring=0
                for j in range(24):
                    theta=j*math.tau/24;px=round(cx+math.cos(theta)*radius);py=round(cy+math.sin(theta)*radius)
                    if 2<=px<ink.shape[1]-2 and 2<=py<ink.shape[0]-2:
                        ring+=bool(ink[py-2:py+3,px-2:px+3].any())
                if best is None or ring>best[0]:best=(ring,cx,cy)
            assert best and best[0]>=9,('lens not found in screenshot',color,path)
            lenses.append([x+int(best[1]),y+int(best[2])])
        dt=max(.4,(self.steps-self.previous_step)*.4)
        for body in bodies:
            old=min(self.previous,key=lambda o:math.dist(o['point'],body['point']),default=None)
            body['velocity']=[(body['point'][i]-old['point'][i])/dt for i in range(2)] if old and math.dist(old['point'],body['point'])<60 else [0,0]
        self.previous=bodies;self.previous_step=self.steps
        self.frames.append(dict(file=path.name,sha256=hashlib.sha256(data).hexdigest(),step=self.steps,
            bodies=[{k:v for k,v in o.items() if k!='glyph'} for o in bodies],lenses=lenses,terminal=terminal))
        (self.output/'observations.json').write_text(__import__('json').dumps(self.frames,indent=2)+'\n')
        return image,bodies,lenses,terminal

    def cards(self,image):
        import io,re,subprocess,hashlib,collections
        from PIL import Image,ImageOps
        x,y,w,h=self.book;result=[]
        for row in range(self.profile['carriers']):
            point=[x+19,y+row*43+21.5];glyph=self._glyph(image,point)
            if glyph.sum()<15:continue
            crop=image.crop((round(x+43),round(y+row*43),round(x+w),round(y+(row+1)*43)))
            gray=crop.convert('L');observations=[]
            for prepared in [gray.point(lambda value:0 if value>80 else 255),gray.point(lambda value:0 if value>100 else 255),ImageOps.invert(gray)]:
                payload=io.BytesIO();prepared.resize((crop.width*4,crop.height*4),Image.Resampling.LANCZOS).save(payload,format='PNG')
                completed=subprocess.run(['tesseract','stdin','stdout','--psm','7'],input=payload.getvalue(),capture_output=True,timeout=15)
                assert completed.returncode==0,completed.stderr
                text=completed.stdout.decode().strip();match=re.search(r'(\d+[.,]\d)\s*[sS]?',text)
                if 'REVER' in text.upper() and match:
                    observations.append((float(match[1].replace(',','.')),text))
            if not observations:continue
            value=collections.Counter(v for v,_ in observations).most_common(1)[0][0]
            result.append(dict(row=row,reversal_seconds=value,ocr=[text for _,text in observations],glyph=glyph,
                motif_sha256=hashlib.sha256(glyph.tobytes()).hexdigest()))
        return result

    def steer(self,index,lens,body):
        aim=list(map(round,self.forecast(body['point'],body['velocity'],.5)))
        if self.mode=='full':
            return [{'mouse':{'move':list(map(round,lens)),'buttons':{'left_down':True}}},
                {'mouse':{'move':aim}},{'mouse':{'buttons':{'left_up':True}}}]
        return [{'mouse':{'left_click':self.controls[f'#fce-lens-{index} .fce-select']}},{'mouse':{'left_click':aim}}]

    def forecast(self,point,velocity,seconds):
        # The visible border and carrier radius define the reflecting field.
        x,y,w,h=self.rect;result=[]
        for i,(origin,length) in enumerate([(x,w),(y,h)]):
            low=origin+45*self.scale;high=origin+length-45*self.scale
            span=high-low;z=(point[i]+velocity[i]*seconds-low)%(2*span)
            result.append(low+(z if z<=span else 2*span-z))
        return result

    def _inspect(self,lens):
        return [{'mouse':{'right_click':list(map(round,lens))}}] if self.mode=='full' else [
            {'mouse':{'left_click':self.controls['#fce-lens-0 .fce-inspect']}}]

    def _similarity(self, glyph, template):
        best=0
        for dx in [-2,-1,0,1,2]:
            for dy in [-2,-1,0,1,2]:
                mask=self.np.roll(self.np.roll(glyph,dx,axis=1),dy,axis=0)
                best=max(best,(mask&template).sum()/max(1,(mask|template).sum()))
        return float(best)

    def run(self,max_steps=250):
        import json
        self.send([{'mouse':{'left_click':self.controls['#fce-start']}}])
        # Observe past every transient event, then recover history by inspection.
        # This uses the configured time bound, never a seeded event schedule.
        for _ in range(67):self.send([])
        cards=[]
        while self.steps<max_steps:
            image,bodies,lenses,terminal=self.view()
            assert not terminal,terminal
            unknown=[o for o in bodies if o['unknown']]
            if not unknown:
                cards=self.cards(image)
                if len(cards)==self.profile['carriers']:break
                self.send([]);continue
            target=min(unknown,key=lambda o:math.dist(o['point'],lenses[0]))
            if math.dist(target['point'],lenses[0])<(self.profile['lens_radius']-29)*self.scale:
                self.send(self._inspect(lenses[0]))
            else:self.send(self.steer(0,lenses[0],target))
        assert len(cards)==self.profile['carriers'],('incomplete pixel discovery',self.steps)
        chosen=sorted(cards,key=lambda c:c['reversal_seconds'])[:self.profile['lenses']]
        decision=dict(chosen=[{k:v for k,v in c.items() if k!='glyph'} for c in chosen],
            all_cards=[{k:v for k,v in c.items() if k!='glyph'} for c in cards],frame=self.frames[-1]['file'],
            observation='OCR of captured notebook pixels; motif templates cropped from the same screenshot. No puzzle state, world, object IDs, event schedule or sensor records were read.')
        (self.output/'decision.json').write_text(json.dumps(decision,indent=2)+'\n')
        bound=[False]*len(chosen)
        tracks=[None]*len(chosen)
        while self.steps<max_steps:
            image,bodies,lenses,terminal=self.view()
            if terminal:
                assert terminal=='pass',terminal
                result=dict(decision=decision,steps=self.steps,bound=bound,frames=self.frames,actions=self.ui.rows,
                    evidence_type='Screenshot observations, visible-control rectangles and Playwright inputs; paused 400-ms windows; no native action API parity.')
                (self.output/'pixel-controller.json').write_text(json.dumps(result,indent=2)+'\n')
                return result
            actions=[]
            # Compare each sprite with every discovered motif. A high overlap
            # with one chosen template alone can mistake another star for it.
            classified=[]
            for body in bodies:
                if body['unknown']:continue
                scores=sorted([(self._similarity(body['glyph'],c['glyph']),c['row']) for c in cards],reverse=True)
                confidence,row=scores[0]
                margin=confidence-scores[1][0] if len(scores)>1 else confidence
                if confidence>=.45 and margin>=.035:
                    classified.append((row,confidence,margin,body))
            for i,card in enumerate(chosen):
                scored=[]
                track=tracks[i]
                dt=max(.4,(self.steps-track['step'])*.4) if track else .4
                expected=self.forecast(track['point'],track['velocity'],dt) if track else None
                for row,confidence,margin,body in classified:
                    if row!=card['row']:continue
                    temporal=1.1*max(0,1-math.dist(expected,body['point'])/(80*self.scale)) if expected else 0
                    scored.append((confidence+temporal,confidence,margin,body))
                scored.sort(key=lambda item:item[0],reverse=True)
                if not scored:
                    if track:
                        actions+=self.steer(i,lenses[i],dict(point=expected,velocity=track['velocity']))
                    continue
                _,confidence,margin,target=scored[0]
                target=dict(target)
                if track:
                    target['velocity']=[(target['point'][j]-track['point'][j])/dt for j in range(2)]
                    speed=math.hypot(*target['velocity']);limit=self.profile['speed']*1.8*self.scale
                    if speed>limit:target['velocity']=[v*limit/speed for v in target['velocity']]
                tracks[i]=dict(point=target['point'],velocity=target['velocity'],step=self.steps)
                actions+=self.steer(i,lenses[i],target)
                if not bound[i] and confidence>.5 and margin>.06 and len(bodies)==self.profile['carriers'] and math.dist(lenses[i],target['point'])<12*self.scale:
                    others=[o for o in bodies if o['point']!=target['point']]
                    if others and min(math.dist(lenses[i],o['point']) for o in others)<25*self.scale:continue
                    actions.append({'keyboard':{'keys':['Space']}} if self.mode=='full' else
                        {'mouse':{'left_click':self.controls[f'#fce-lens-{i} .fce-bind']}})
                    bound[i]=True
            self.frames[-1]['tracked_targets']=tracks.copy()
            self.send(actions)
        raise TimeoutError('Pixel controller exceeded its task-local step allowance')
