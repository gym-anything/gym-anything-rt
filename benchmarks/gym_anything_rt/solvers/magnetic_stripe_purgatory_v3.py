"""Privileged construction controller, never a screenshot-only model score.

Simulation is diagnostic. ``solve`` sends ordinary mouse actions through its UI
transport, including hood inspection, grips and releases. Native callers can
use the downstream HTTP interface; local tests explicitly use a headless
Playwright adapter. Read-only state supports privileged continuation planning.
No DOM focus, mutation or internal game call supplies an action.
"""
from __future__ import annotations
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.magnetic_stripe_purgatory_v3 import demand,initial,step,command_point,grade

def controller(w,states,t,lead_ms=120):
    p=w["parameters"];targets=[demand(w,i,t+lead_ms) for i in range(len(states))]
    commands=[]
    for i,s in enumerate(states):
        a=demand(w,i,t+lead_ms-20);b=demand(w,i,t+lead_ms+20)
        tau=p["response_ms"]/1000
        # Lead the inertial carriage, compensating the compliant shared drive.
        u=targets[i][0]+tau*(b[0]-a[0])/.04
        if len(states)==2:u-=p["coupling"]*(targets[1-i][0]-targets[i][0])
        q=targets[i][1]+tau*(b[1]-a[1])/.04
        commands.append(dict(u=max(.4,min(1.6,u)),q=max(-1.,min(1.,q))))
    return commands

def inspection_events(w,mode):
    """Diagnostic ordinary-input prefix; inspection has no physical side effect."""
    events=[]
    for i,tab in enumerate(w['cam_inspection']['tabs']):
        point=[tab['x']+tab['width']/2,tab['y']+tab['height']/2]
        if mode=='full':
            events.append(dict(kind='hood_grip',feed=i,point=point))
            events.append(dict(kind='hood_release',feed=i,point=[point[0],point[1]-40],cancelled=False))
        else:events.append(dict(kind='inspect',feed=i,point=point))
    return [dict(e,seq=i,t_ms=0,input_source=mode) for i,e in enumerate(events,1)]

def simulation_trace(public,interval_ms=240,delay_ms=0,policy='feedback',schedule=None,parking=None,inspect=True):
    w=public['world'];mode=public['control_condition']['interaction'];states=initial(w)
    events=inspection_events(w,mode) if inspect else [];plans=[];status='running'
    def add(kind,t,source,**kw):events.append(dict(seq=len(events)+1,kind=kind,t_ms=t,input_source=source,**kw))
    if parking is not None:
        for i,s in enumerate(states):
            old=command_point(w,i,s);new=command_point(w,i,parking[i])
            if mode=='full':add('grip',0,mode,feed=i,point=old)
            add('steer',0,mode,feed=i,point=new)
            if mode=='full':add('release',0,mode,feed=i)
            s.update(parking[i]);s.update(v=s['u'],y=s['q'])
    add('start',0,'launch_button')
    for t in range(0,w['duration_ms']+w['tick_ms'],w['tick_ms']):
        if t>0:status=step(w,states,t)
        if status in ('failed','ready'):break
        if t%interval_ms==0 and policy!='parked':
            if schedule is not None:
                commands=schedule[min(t//interval_ms,len(schedule)-1)]['commands']
            else:commands=controller(w,states,max(0,t-delay_ms),interval_ms/2)
            plans.append(dict(t_ms=t,commands=commands))
            for i,s in enumerate(states):
                if s['done']:continue
                old=command_point(w,i,s);new=command_point(w,i,commands[i])
                if mode=='full':add('grip',t,mode,feed=i,point=old)
                add('steer',t,mode,feed=i,point=new)
                if mode=='full':add('release',t,mode,feed=i)
                s.update(commands[i])
    add('submit',t,'certify_button')
    payload={k:public[k] for k in ('mechanic_id','task_id','challenge_id','control_condition')}
    payload.update(interaction_mode=mode,events=events,final_t_ms=t,completed=status=='ready',
                   feeds=[dict(distance=s['distance'],damage=s['damage']) for s in states])
    return dict(payload=payload,plans=plans,status=status,states=states)

def click_control(ui,selector):
    xy=ui.read(f"(()=>{{const r=document.querySelector({selector!r}).getBoundingClientRect();return[r.x+r.width/2,r.y+r.height/2];}})()")
    return ui.send([{'mouse':{'left_click':xy}}])

def inspect_cams(ui,world,mode):
    """Lift/click the visible housing tabs, through the caller's input transport."""
    rect=ui.read("(()=>{const r=document.querySelector('.ms2-stage').getBoundingClientRect();return[r.x,r.y,r.width,r.height];})()")
    for tab in world['cam_inspection']['tabs']:
        point=[rect[0]+(tab['x']+tab['width']/2)/world['width']*rect[2],
               rect[1]+(tab['y']+tab['height']/2)/world['height']*rect[3]]
        if mode=='full':
            ui.send([{'mouse':{'move':point,'buttons':{'left_down':True}}},
                     {'mouse':{'move':[point[0],point[1]-40/world['height']*rect[3]],'buttons':{'left_up':True}}}])
        else:ui.send([{'mouse':{'left_click':point}}])

def visible_pad_observations(png,rect,difficulty):
    """Locate rendered marks, without reading a model, world, seed or clock.

    ``rect`` is the canvas's screen rectangle. Fixed pad geometry and the
    displayed color legend belong to this task's interface. Accepted readers
    have a green STRIPE READ label in place of their control marks.
    """
    import io
    import numpy as np
    from PIL import Image
    rgb=np.asarray(Image.open(io.BytesIO(png)).convert('RGB')).astype('int16')
    sx,sy=rect['width']/1120,rect['height']/500
    observations=[]
    for i in range(1 if difficulty<3 else 2):
        y=155 if difficulty<3 else 57+i*218
        left,top=round(rect['x']+805*sx),round(rect['y']+y*sy)
        right,bottom=round(rect['x']+1073*sx),round(rect['y']+(y+170)*sy)
        patch=rgb[top:bottom,left:right]
        def locate(mask):
            yy,xx=np.nonzero(mask)
            if not len(xx):return None
            return [(left+(float(xx.min())+float(xx.max()))/2-rect['x'])/sx,
                    (top+(float(yy.min())+float(yy.max()))/2-rect['y'])/sy]
        def colored(color,tolerance=5):
            return np.max(np.abs(patch-np.array(color)),axis=2)<=tolerance
        green=(patch[:,:,1]>=120)&(patch[:,:,1]-patch[:,:,0]>=55)&(patch[:,:,1]-patch[:,:,2]>=20)
        marks=dict(current=locate(green),future=locate(colored((106,188,227))),
                   grip=locate(colored((233,226,197))))
        marks['accepted']=marks['grip'] is None and int(colored((152,228,188)).sum())>20
        observations.append(marks)
    return observations

def visible_commands(observations,difficulty):
    """Lead the exposed window toward its blue forecast using visible marks.

    Public difficulty parameters describe inertia/coupling; no seeded demand
    function or private physical state enters this controller.
    """
    from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.magnetic_stripe_purgatory_v3 import PROFILES
    p=PROFILES[difficulty];gain=(p['response_ms']/1000+.14)/.8
    commands=[]
    for i,marks in enumerate(observations):
        if marks['accepted']:
            commands.append(None);continue
        if any(marks[name] is None for name in ('current','future','grip')):
            raise RuntimeError('read window/forecast/grip not visible; inspect the cam housing first')
        target=[a+gain*(b-a) for a,b in zip(marks['current'],marks['future'])]
        if len(observations)==2 and observations[1-i]['current'] is not None:
            target[0]-=p['coupling']*(observations[1-i]['current'][0]-marks['current'][0])
        pad_y=155 if difficulty<3 else 57+i*218
        commands.append([max(805.,min(1073.,target[0])),max(float(pad_y),min(float(pad_y+170),target[1]))])
    return commands

def solve_visible(ui,capture,rect,difficulty,mode,limit=320):
    """Complete through screenshot feedback and ordinary supplied mouse input.

    Caller opens the visible hoods and engages the readers. ``capture`` returns
    a screenshot; ``ui`` only sends mouse actions or waits. This path never
    reads DOM state or invokes the privileged construction controller.
    """
    import time
    plans=[]
    for _ in range(limit):
        sampled=time.monotonic()
        marks=visible_pad_observations(capture(),rect,difficulty)
        if all(m['accepted'] for m in marks):
            return dict(planning='Screenshot pixels only; ordinary mouse actions through caller transport.',plans=plans)
        commands=visible_commands(marks,difficulty)
        def screen(point):
            return [rect['x']+point[0]/1120*rect['width'],rect['y']+point[1]/500*rect['height']]
        actions=[]
        for m,target in zip(marks,commands):
            if target is None:continue
            if mode=='full':
                actions += [{'mouse':{'move':screen(m['grip']),'buttons':{'left_down':True}}},
                            {'mouse':{'move':screen(target),'buttons':{'left_up':True}}}]
            else:actions.append({'mouse':{'left_click':screen(target)}})
        plans.append(dict(wall_monotonic=sampled,observations=marks,commands=commands,actions=actions))
        ui.send(actions);ui.wait(.12)
    raise RuntimeError('visible construction control budget exhausted')

def solve(ui,truth,limit=280,delay_seconds=0,parked=False):
    w=truth['world'];mode=truth['control_condition']['interaction'];plans=[]
    inspect_cams(ui,w,mode)
    click_control(ui,'.ms2-start')
    for _ in range(limit):
        s=ui.read("(()=>{const m=magneticStripePurgatoryV3Model,r=document.querySelector('.ms2-stage').getBoundingClientRect();return{t:m.t,status:m.status,feeds:m.feeds,rect:[r.x,r.y,r.width,r.height]};})()")
        if s['status']=='failed':raise RuntimeError('stripe damaged during construction control')
        if s['status']=='ready':
            click_control(ui,'.ms2-submit');ui.wait(.15)
            return dict(planning='Privileged read-only reader state and geometry; ordinary mouse actions through the supplied UI transport. Caller records Playwright or native HTTP provenance.',plans=plans)
        commands=controller(w,s['feeds'],s['t'],120)
        if delay_seconds:ui.wait(delay_seconds)
        actions=[];r=s['rect']
        def screen(point):return[r[0]+point[0]/w['width']*r[2],r[1]+point[1]/w['height']*r[3]]
        if not parked:
            for i,feed in enumerate(s['feeds']):
                if feed['done']:continue
                new=screen(command_point(w,i,commands[i]))
                if mode=='full':
                    old=screen(command_point(w,i,feed))
                    # The API moves before applying button transitions. Group
                    # the final motion and release without changing the drag.
                    actions += [{'mouse':{'move':old,'buttons':{'left_down':True}}},
                                {'mouse':{'move':new,'buttons':{'left_up':True}}}]
                else:actions.append({'mouse':{'left_click':new}})
        plans.append(dict(t_ms=s['t'],commands=commands))
        ui.send(actions)
        ui.wait(.16)
    raise RuntimeError('declared construction solution request budget exhausted')
