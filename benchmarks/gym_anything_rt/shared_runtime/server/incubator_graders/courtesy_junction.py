"""Independent fixed-step bicycle and responsive-driver replay. No claimed win is trusted."""
from __future__ import annotations
import copy
import math

MECHANIC_ID='courtesy_junction'

def q(x):
    return math.floor(x*1e6+.5)/1e6

def pose(car):
    lane,s=car['lane'],car['s']
    if lane==0:return dict(x=s,y=290,a=0,v=car['v'])
    if lane==1:return dict(x=900-s,y=230,a=math.pi,v=car['v'])
    return dict(x=420,y=s,a=math.pi/2,v=car['v'])

def corners(car,length=40,width=22):
    c,s=math.cos(car['a']),math.sin(car['a'])
    return [(car['x']+u*c-v*s,car['y']+u*s+v*c) for u,v in [(-length/2,-width/2),(length/2,-width/2),(length/2,width/2),(-length/2,width/2)]]

def intersect(a,b):
    for polygon in (a,b):
        for i in range(4):
            p,r=polygon[i],polygon[(i+1)%4];axis=(p[1]-r[1],r[0]-p[0])
            aa=[x*axis[0]+y*axis[1] for x,y in a];bb=[x*axis[0]+y*axis[1] for x,y in b]
            if max(aa)<min(bb) or max(bb)<min(aa):return False
    return True

def rect(x,y,w,h):return [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]

def initial(world):
    return dict(ego=copy.deepcopy(world['start']),traffic=copy.deepcopy(world['traffic']),tick=0,status='driving',contact=None)

def conflict(a,b,horizon):
    dx,dy=b['x']-a['x'],b['y']-a['y']
    vx=b['v']*math.cos(b['a'])-a['v']*math.cos(a['a']);vy=b['v']*math.sin(b['a'])-a['v']*math.sin(a['a'])
    vv=vx*vx+vy*vy
    t=max(0,min(horizon,-(dx*vx+dy*vy)/vv)) if vv>1e-9 else 0
    ahead=dx*math.cos(a['a'])+dy*math.sin(a['a'])
    return ahead>-10 and math.hypot(dx+vx*t,dy+vy*t)<45

def step(state,control,world):
    if state['status']!='driving':return
    dt=.02;e=state['ego'];ph=world['physics'];steer,pedal=control
    # Policies observe the same pre-tick state, so iteration order cannot move a car early.
    targets=[]
    for car in state['traffic']:
        a=pose(car);braking=conflict(a,e,car['horizon'])
        for other in state['traffic']:
            if other['id']==car['id']:continue
            b=pose(other)
            if other['lane']==car['lane']:
                gap=(other['s']-car['s'])%car['cycle']
                if 0<gap<52+car['v']*.8:braking=True
            elif other['lane']<car['lane'] and conflict(a,b,2.4):braking=True
        targets.append(braking)
    e['v']=q(max(0,min(ph['max_speed'],e['v']+(ph['acceleration'] if pedal==1 else -ph['brake'] if pedal==-1 else -ph['drag'])*dt)))
    e['a']=q(e['a']+e['v']/ph['wheelbase']*math.tan(steer*ph['steer_angle'])*dt)
    e['x']=q(e['x']+e['v']*math.cos(e['a'])*dt);e['y']=q(e['y']+e['v']*math.sin(e['a'])*dt)
    for car,braking in zip(state['traffic'],targets):
        car['braking']=braking
        car['v']=q(max(0,min(car['cruise'],car['v']+(-car['decel'] if braking else 18)*dt)))
        car['s']=q(car['s']+car['v']*dt)
        limit=1150 if car['lane']<2 else 770
        if car['s']>limit:car['s']=q(car['s']-car['cycle'])
    state['tick']+=1
    body=corners(e);r=world['road_half'];left,right=450-r,450+r;top,bottom=260-r,260+r
    lawns=[rect(-1000,-1000,left+1000,top+1000),rect(right,-1000,2000,top+1000),rect(-1000,bottom,left+1000,2000),rect(right,bottom,2000,2000)]
    for car in state['traffic']:
        if intersect(body,corners(pose(car))):state['status']='collision';state['contact']=car['id'];break
    if state['status']=='driving' and (any(intersect(body,lawn) for lawn in lawns) or any(x<0 or x>900 or y<0 or y>520 for x,y in body)):
        state['status']='offroad';state['contact']='road edge'
    goal=world['goal']
    if state['status']=='driving' and all(goal['x']<=x<=goal['x']+goal['width'] and goal['y']<=y<=goal['y']+goal['height'] for x,y in body):state['status']='arrived'
    if state['status']=='driving' and state['tick']>=ph['max_ticks']:state['status']='timeout'

def snapshot(s):
    return dict(tick=s['tick'],ego=copy.deepcopy(s['ego']),traffic=[dict(id=c['id'],s=c['s'],v=c['v'],braking=c['braking']) for c in s['traffic']],status=s['status'],contact=s['contact'])

def close(a,b):
    if isinstance(b,bool) or b is None or isinstance(b,str):return a==b and type(a)==type(b)
    if isinstance(b,(float,int)):return not isinstance(a,bool) and isinstance(a,(float,int)) and math.isfinite(a) and abs(a-b)<=.00002
    if isinstance(b,list):return isinstance(a,list) and len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))
    if isinstance(b,dict):return isinstance(a,dict) and set(a)==set(b) and all(close(a[k],v) for k,v in b.items())
    return False

def grade(payload,truth,public):
    def fail(message):return dict(graded=True,passed=False,score=0,feedback=message)
    if not all(isinstance(x,dict) for x in (payload,truth,public)):return fail('Malformed envelope')
    for key in ['mechanic_id','task_id','challenge_id','control_condition']:
        if not truth.get(key) or payload.get(key)!=truth[key] or public.get(key)!=truth[key]:return fail('Stale identity or wrong condition: '+key)
    if truth['mechanic_id']!=MECHANIC_ID or public.get('world')!=truth.get('world'):return fail('World contract mismatch')
    events=payload.get('events');world=truth['world'];mode=truth['control_condition']['interaction'];source={'full':'held_keys','simplified':'panel_buttons'}.get(mode)
    if source is None or not isinstance(events,list) or not 1<=len(events)<=15000:return fail('Missing or invalid transcript')
    state=initial(world);control=[0,0];started=False;submitted=False
    try:
        for seq,event in enumerate(events,1):
            if not isinstance(event,dict) or event.get('seq')!=seq or submitted:return fail('Invalid event sequence')
            kind=event.get('type')
            if kind=='start':
                if started or seq!=1:return fail('Invalid ignition')
                started=True
            elif not started:return fail('No ignition')
            elif kind=='control':
                value=event.get('value')
                if state['status']!='driving' or event.get('tick')!=state['tick'] or event.get('input_source')!=source or not isinstance(value,list) or len(value)!=2 or any(type(v)!=int or v not in (-1,0,1) for v in value):return fail('Invalid control surface or boundary')
                control=value
            elif kind=='tick':
                if state['status']!='driving':return fail('Physics after terminal state')
                step(state,control,world)
                if not close(event.get('state'),snapshot(state)):return fail(f'Physics replay mismatch at tick {state["tick"]}')
            elif kind=='submit':
                if event.get('tick')!=state['tick']:return fail('Invalid submission boundary')
                submitted=True
            else:return fail('Unknown event')
    except (KeyError,TypeError,ValueError,OverflowError) as exc:return fail('Malformed replay: '+str(exc))
    if not submitted or not close(payload.get('final'),snapshot(state)):return fail('Missing or fabricated final state')
    passed=state['status']=='arrived'
    return dict(graded=True,passed=passed,score=100 if passed else 0,feedback=f'{state["status"]}; {state["tick"]} physical ticks; contact={state["contact"]}')
