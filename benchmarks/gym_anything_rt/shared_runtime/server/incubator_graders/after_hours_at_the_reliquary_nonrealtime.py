"""Independent replay for the settled-action counterpart.

The donor's generated socket motion is sampled at its initial pose, but it is
never advanced by elapsed wall time here.  Each deliberate aim/release action
gets one fixed settling transition, which keeps browser and verifier outcomes
independent of waiting, screenshots, and model latency.
"""
from __future__ import annotations
import math

MECHANIC_ID='after_hours_at_the_reliquary_nonrealtime'


def noise(seed,n):
    x=(int(seed)^((n+1)*0x9e3779b9))&0xffffffff
    x=((x^(x>>16))*0x85ebca6b)&0xffffffff
    x=((x^(x>>13))*0xc2b2ae35)&0xffffffff
    return ((x^(x>>16))&0xffffffff)/4294967295*2-1


def motion(seed,t,span):
    u=max(0,t)/span;n=math.floor(u);f=u-n
    a,b=noise(seed,n),noise(seed,n+1)
    return a+(b-a)*f*f*(3-2*f)


def integral(seed,t,span):
    u=max(0,t)/span;n=math.floor(u);f=u-n
    a,b=noise(seed,n),noise(seed,n+1)
    return span*(sum((noise(seed,i)+noise(seed,i+1))/2 for i in range(n))+a*f+(b-a)*(f**3-f**4/2))


def triangle(value,lo,hi):
    width=hi-lo
    return lo+width-abs((value%(2*width))-width)


def socket_pose(c,t):
    w,p=c['world'],c['parameters'];s=w['seeds'];off=w['offset_ms'];span=p['rate_span_ms']
    def travel(seed,speed):
        return speed*(t+p['rate_amplitude']*(integral(seed,t+off,span)-integral(seed,off,span)))/1000
    return dict(x=triangle(w['phase_x']+travel(s[0],p['scan_speed']),*w['x_bounds']),
                y=triangle(w['phase_y']+travel(s[1],26),*w['y_bounds']) if p['vertical'] else 250.,
                angle=35*motion(s[2],t+off,4200) if p['angle'] else 0.,
                span=320+110*motion(s[3],t+off,3600) if p['span'] else 320.)


def tips(p,count):
    if count==1:return [[p['x'],p['y']]]
    a=math.radians(p['angle']);dx=math.cos(a)*p['span']/2;dy=math.sin(a)*p['span']/2
    return [[p['x']-dx,p['y']-dy],[p['x']+dx,p['y']+dy]]


def initial(c):
    return dict(tick=0,start=None,pose=dict(c['world']['initial']),target=dict(c['world']['initial']),charge=0.,unsealed=False,opening_tick=None,failed=False,drag=None)


def advance(s,c,end):
    """Validate an event timestamp without advancing the settled world."""
    if end != s['tick']:
        raise ValueError('settled ward advances only from deliberate controls')


def settle(s,c):
    """Run the fixed, action-triggered transition after an aim/release."""
    w,p=c['world'],c['parameters'];dt=w['tick_ms']/1000
    steps=max(1,int(round(w.get('settle_ms',400)/w['tick_ms'])))
    goal=socket_pose(c,w.get('static_time_ms',0))
    for _ in range(steps):
        if s['failed'] or s['unsealed']:
            break
        s['tick']+=1
        for key,speed in [('x',w['speed']),('y',w['speed']),('angle',w['angle_speed']),('span',w['span_speed'])]:
            delta=(s['target'][key]-s['pose'][key])*(1-math.exp(-dt/p['lag_s']))
            s['pose'][key]+=max(-speed*dt,min(speed*dt,delta))
        if s['start'] is not None:
            aligned=all(math.dist(a,b)<=p['radius']+1e-9 for a,b in zip(tips(s['pose'],p['sockets']),tips(goal,p['sockets'])))
            s['charge']=max(0.,s['charge']+(w['tick_ms'] if aligned else -w['leak']*w['tick_ms']))
            if s['charge']>=p['charge_ms']:s['unsealed']=True;s['opening_tick']=s['tick']
            elif (s['tick']-s['start'])*w['tick_ms']>=w['run_ms']:s['failed']=True


def point(value):
    if not isinstance(value,list) or len(value)!=2 or any(type(x) not in (float,int) or not math.isfinite(x) for x in value):raise ValueError('malformed point')
    return value


def inside(pt,r):
    return r[0]<=pt[0]<=r[0]+r[2] and r[1]<=pt[1]<=r[1]+r[3]


def card(c,inventory,item):
    i=inventory.index(item);r=c['tray']
    return [r['left']+i*(r['width']+r['gap']),r['top'],r['width'],r['height']]


def handle(s,axis):
    if axis=='position':return [s['pose']['x'],s['pose']['y']]
    if axis=='angle':
        a=math.radians(s['target']['angle']);return [90+58*math.cos(a),80+58*math.sin(a)]
    return [20+(s['target']['span']-180)/380*240,40]


def aim(s,c,axis,pt):
    p=c['parameters'];point(pt)
    if axis=='position':
        if not inside(pt,[80,40,840,420]):raise ValueError('carrier outside surface')
        s['target']['x']=pt[0];s['target']['y']=pt[1]
    elif axis=='angle' and p['angle']:
        if not inside(pt,[0,0,280,160]):raise ValueError('angle dial outside surface')
        s['target']['angle']=max(-50,min(50,math.degrees(math.atan2(pt[1]-80,pt[0]-90))))
    elif axis=='span' and p['span']:
        if not inside(pt,[0,0,280,80]):raise ValueError('span rail outside surface')
        s['target']['span']=max(180,min(560,180+(pt[0]-20)/240*380))
    else:raise ValueError('inactive control')


def grade(payload,truth,public):
    def fail(m):return dict(graded=True,passed=False,score=0,feedback=m)
    try:
        if not isinstance(payload,dict):raise ValueError('payload is not an object')
        for k in ['mechanic_id','task_id','challenge_id']:
            if not truth.get(k) or payload.get(k)!=truth[k] or public.get(k)!=truth[k]:raise ValueError('identity mismatch: '+k)
        if truth['mechanic_id']!=MECHANIC_ID:raise ValueError('wrong mechanic')
        for k in ['world','parameters','targets','recipes','views','mural','ignition','tray','control_condition','physics_revision']:
            if truth.get(k)!=public.get(k):raise ValueError('contract mismatch: '+k)
        mode=(truth.get('control_condition') or {}).get('interaction','full')
        if mode not in ['full','simplified'] or payload.get('interaction_mode')!=mode:raise ValueError('wrong interaction mode')
        events=payload.get('events');s=initial(truth);inventory=[];opened=set();collected=set();revealed=not truth['parameters']['loupe'];view=0;escaped=False
        if not isinstance(events,list) or not 1<=len(events)<=5000:raise ValueError('missing or excessive events')
        for seq,e in enumerate(events,1):
            if not isinstance(e,dict):raise ValueError('action is not an object')
            tick=e.get('tick')
            if e.get('sequence')!=seq or type(tick) is not int or not s['tick']<=tick<=12000 or e.get('input_source')!=mode or s['failed'] or escaped:raise ValueError('invalid ordered action or terminal continuation')
            advance(s,truth,tick)
            if s['failed']:raise ValueError('spring exhausted')
            kind=e['kind']
            if kind=='view':
                if type(e.get('view')) is not int or not 0<=e['view']<len(truth['views']):raise ValueError('unknown room')
                view=e['view']
            elif kind in ['inspect','collect']:
                obj=next(x for x in truth['targets'] if x['id']==e['id'])
                if view!=obj['view'] or not inside(point(e['point']),obj['rect']):raise ValueError('missed room geometry')
                if kind=='inspect':opened.add(obj['id'])
                elif obj['id'] not in opened or obj['item'] in collected:raise ValueError('unavailable object')
                else:inventory.append(obj['item']);collected.add(obj['item'])
            elif kind in ['combine','use']:
                item=e['item'];start=point(e['start'])
                if item not in inventory or not inside(start,card(truth,inventory,item)):raise ValueError('object source misses tray')
                if kind=='combine':
                    mate=e['mate'];end=point(e['point'])
                    if mate==item or mate not in inventory or not inside(end,card(truth,inventory,mate)):raise ValueError('object mate misses tray')
                    recipe=next((r for r in truth['recipes'] if set(r['inputs'])=={item,mate}),None)
                    if not recipe:raise ValueError('unmatched recipe')
                    inventory.remove(item);inventory.remove(mate);inventory.append(recipe['output'])
                else:
                    dest=truth['mural'] if item=='loupe' else truth['ignition'] if item=='key' else None
                    if not dest or view!=dest['view'] or not inside(point(e['point']),dest['rect']):raise ValueError('wrong tool or scene geometry')
                    if item=='loupe':revealed=True
                    elif not revealed or s['start'] is not None:raise ValueError('unread ward or duplicate activation')
                    else:s['start']=tick;inventory.remove('key')
                if mode=='full' and e.get('gesture')!='drag':raise ValueError('full inventory action needs direct drag')
                if mode=='simplified' and e.get('gesture')!='select':raise ValueError('simplified inventory action needs selection')
            elif kind in ['grab','aim','release']:
                if s['start'] is None or view!=0 or s['unsealed']:raise ValueError('inactive ward controls')
                axis=e['axis']
                if kind=='grab':
                    if mode!='full' or s['drag'] is not None or axis not in ['position','angle','span'] or math.dist(point(e['point']),handle(s,axis))>25:raise ValueError('drag must start on current visible handle')
                    if axis=='angle' and not truth['parameters']['angle'] or axis=='span' and not truth['parameters']['span']:raise ValueError('inactive handle')
                    s['drag']=axis
                elif kind=='aim':
                    if mode=='full' and s['drag']!=axis:raise ValueError('aim lacks captured drag')
                    aim(s,truth,axis,e['point'])
                    settle(s,truth)
                else:
                    if mode!='full' or s['drag']!=axis:raise ValueError('unmatched release')
                    settle(s,truth)
                    s['drag']=None
            elif kind=='exit':
                if view!=0 or not s['unsealed'] or not inside(point(e['point']),[860,140,110,240]):raise ValueError('door still warded or handle missed')
                escaped=True
            elif kind=='submit':s['failed']=not escaped
            elif kind=='probe':point(e['point'])
            else:raise ValueError('unknown action')
        final_tick=payload.get('final_tick')
        if type(final_tick) is not int or not s['tick']<=final_tick<=12000:raise ValueError('invalid final clock')
        advance(s,truth,final_tick)
        passed=escaped and not s['failed'] and payload.get('completed') is True
        if payload.get('unsealed') is not s['unsealed'] or payload.get('failed') is not s['failed']:raise ValueError('reported outcome differs from replay')
        return dict(graded=True,passed=passed,score=100 if passed else 0,feedback=f'ward replay: {s["charge"]:.0f} ms contact; exit {escaped}',charge_ms=s['charge'],opening_tick=s['opening_tick'],final_tick=s['tick'])
    except (KeyError,TypeError,ValueError,StopIteration,OverflowError) as exc:return fail('ward replay rejected: '+str(exc))


def cheat(public_state,ground_truth):
    return dict(targets=ground_truth.get('targets'),recipes=ground_truth.get('recipes'))
