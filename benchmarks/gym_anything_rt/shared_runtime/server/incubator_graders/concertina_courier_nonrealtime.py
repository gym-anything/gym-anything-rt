"""Replay primitive input transitions; never accept client collection claims."""
import copy
import math
MECHANIC_ID='concertina_courier_nonrealtime'
# Deliberate releases retain the donor's short coast, but a parked parcel no
# longer advances because the wall clock kept running.  The browser mechanic
# uses the same fixed settle horizon.
RELEASE_SETTLE_TICKS = 12


def bounds(s,w):
    width=w['area']/s['h']
    return [s['x']-width/2,s['bottom']-s['h'],width,s['h']]


def overlap(a,b):
    return a[0]<b[0]+b[2]-1e-8 and a[0]+a[2]>b[0]+1e-8 and a[1]<b[1]+b[3]-1e-8 and a[1]+a[3]>b[1]+1e-8


def clear(s,w):
    b=bounds(s,w)
    return b[1]>=0 and not any(overlap(b,r) for r in w['solids'])


def advance(s,control,w):
    if s['status']!='active':return False
    if control == [0, 0]:
        if not s.get('_has_controlled', False):
            return False
        settled = int(s.get('_release_settle_ticks', 0))
        if settled >= RELEASE_SETTLE_TICKS:
            return False
        s['_release_settle_ticks'] = settled + 1
    else:
        s['_has_controlled'] = True
        s['_release_settle_ticks'] = 0
    s['tick']+=1
    # Small substeps prevent both morphing and translation tunnelling.
    for _ in range(4):
        h=max(w['min_height'],min(w['max_height'],s['h']+control[1]*.75))
        candidate=dict(s,h=h)
        if clear(candidate,w):s['h']=h
        s['vx']=(s['vx']+control[0]*.35+w['wind'][s['tick']])*w['parameters']['drag']**.25
        s['vx']=max(-4,min(4,s['vx']))
        candidate=dict(s,x=s['x']+s['vx']/4)
        if clear(candidate,w):s['x']=candidate['x']
        else:s['vx']=0.
        s['vy']=min(10,s['vy']+.25)
        candidate=dict(s,bottom=s['bottom']+s['vy']/4)
        if clear(candidate,w):s['bottom']=candidate['bottom']
        else:
            b=bounds(s,w)
            landing=[r[1] for r in w['solids'] if b[0]<r[0]+r[2]-1e-8 and b[0]+b[2]>r[0]+1e-8 and s['bottom']<=r[1]+1e-8 and candidate['bottom']>=r[1]]
            if landing:s['bottom']=min(landing)
            s['vy']=0.
        b=bounds(s,w)
        for i,(x,y) in enumerate(w['seals']):
            # Circular gold seal versus exact rectangular parcel contact.
            dx=x-max(b[0],min(x,b[0]+b[2]));dy=y-max(b[1],min(y,b[1]+b[3]))
            if dx*dx+dy*dy<=100 and i not in s['collected']:s['collected'].append(i)
    if control == [0, 0] and int(s.get('_release_settle_ticks', 0)) >= RELEASE_SETTLE_TICKS:
        s['vx'] = 0.0
        s['vy'] = 0.0
    b=bounds(s,w)
    if s['bottom']>570 or b[0]<0 or b[0]+b[2]>1000:s['status']='fell'
    elif len(s['collected'])==len(w['seals']):s['status']='solved'
    elif s['tick']>=w['max_ticks']:s['status']='timeout'
    return True


def grade(payload,ground_truth,public_state):
    def result(ok,msg):return dict(graded=True,passed=ok,score=100 if ok else 0,feedback=msg)
    if not all(isinstance(value, dict) for value in (payload, ground_truth, public_state)):
        return result(False, 'invalid result envelope')
    w=ground_truth
    if any(payload.get(k)!=w.get(k) or public_state.get(k)!=w.get(k) for k in ['mechanic_id','task_id','challenge_id']):return result(False,'stale identity')
    if w.get('mechanic_id')!=MECHANIC_ID or public_state.get('control_condition')!=w.get('control_condition'):return result(False,'condition mismatch')
    world_keys = ['area', 'min_height', 'max_height', 'tick_ms', 'max_ticks', 'parameters', 'solids', 'seals', 'initial_state', 'wind']
    if any(public_state.get(key) != w.get(key) for key in world_keys):
        return result(False, 'rendered world differs from replay world')
    mode=(w.get('control_condition') or {}).get('interaction','full')
    if payload.get('interaction_mode')!=mode:return result(False,'wrong interaction')
    events=payload.get('events');end=payload.get('terminal_tick')
    if not isinstance(events,list) or len(events)>4000 or type(end)!=int or not 0<=end<=w['max_ticks']:return result(False,'invalid transcript')
    s=copy.deepcopy(w['initial_state']);control=[0,0]
    for e in events:
        if not isinstance(e,dict) or type(e.get('tick'))!=int or not s['tick']<=e['tick']<=end:return result(False,'invalid event time')
        if e.get('input_source')!=('body_hold' if mode=='full' else 'console_latch'):return result(False,'wrong input surface')
        c=e.get('control')
        if not isinstance(c,list) or len(c)!=2 or any(type(v)!=int or v not in [-1,0,1] for v in c):return result(False,'invalid control')
        if sum(abs(v) for v in c) > 1:
            return result(False, 'the selected surface has no diagonal control')
        if mode == 'full' and c != [0, 0] and control != [0, 0]:
            return result(False, 'body hold must be released before another hold')
        while s['tick']<e['tick'] and s['status']=='active':
            if not advance(s,control,w):break
        if s['tick']!=e['tick'] or s['status']!='active':return result(False,'input after terminal state')
        control=c
    while s['tick']<end and s['status']=='active':
        if not advance(s,control,w):break
    final=payload.get('final_state',{})
    if not isinstance(final, dict):return result(False, 'invalid final state')
    for k in ['x','bottom','h','vx','vy']:
        v=final.get(k)
        if type(v) not in (int,float) or not math.isfinite(v) or abs(v-s[k])>1e-6:return result(False,'physical state mismatch')
    ok=s['status']=='solved' and s['tick']==end and payload.get('completed') is True
    return result(ok,f"replayed {len(s['collected'])}/{len(w['seals'])} seals; {s['status']}; tick {s['tick']}")
