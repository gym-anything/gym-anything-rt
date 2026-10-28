"""Independent beat-gated replay. No client outcome is trusted."""
from copy import deepcopy
import math
MECHANIC_ID = 'clockbeat_catacomb_v2'

def motion_noise(seed, index):
    """Stable 32-bit mixing, independently implemented by the browser."""
    x = (int(seed) + (int(index) + 1) * 0x9E3779B9) & 0xffffffff
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff) / 2147483648 - 1


def motion_value(seed, t_ms, span_ms=1300):
    t = max(0.0, float(t_ms)) / span_ms
    index = int(t)
    u = t - index
    a, b = motion_noise(seed, index), motion_noise(seed, index + 1)
    return a + (b - a) * u * u * (3 - 2 * u)


def motion_integral(seed, t_ms, span_ms=1300):
    """Integral in seconds; a fresh smooth velocity segment follows each one."""
    t = max(0.0, float(t_ms)) / span_ms
    count = int(t)
    total = sum((motion_noise(seed, i) + motion_noise(seed, i + 1)) / 2 for i in range(count))
    u = t - count
    a, b = motion_noise(seed, count), motion_noise(seed, count + 1)
    return span_ms / 1000 * (total + a * u + (b - a) * (u**3 - .5 * u**4))


DELTAS = {'UP':(0,-1),'RIGHT':(1,0),'DOWN':(0,1),'LEFT':(-1,0),'WAIT':(0,0)}

def initial(b):
    return {'player':b['start'][:], 'hp':b['health'], 'enemies':deepcopy(b['enemies']), 'beat':0, 'used':False, 'won':False}

def phase(e, beat):
    return int((motion_noise(e['phase_seed'], beat) + 1) * 1.5) if e['kind']=='lancer' else int(motion_noise(e['phase_seed'], beat) > 0)

def act(b,s,key):
    if s['won'] or s['hp']<=0 or s['used']: return 'unavailable'
    s['used']=True
    if key=='WAIT': return 'wait'
    dx,dy=DELTAS[key]; p=[s['player'][0]+dx,s['player'][1]+dy]
    if p in b['walls']: return 'wall'
    e=next((e for e in s['enemies'] if e['hp']>0 and e['pos']==p),None)
    if e:
        if e['kind']=='hopper' and phase(e,s['beat'])==1: return 'shield'
        e['hp']-=1
        return 'defeated' if e['hp']==0 else 'hit'
    s['player']=p
    s['won']=p==b['exit'] and all(e['hp']==0 for e in s['enemies'])
    return 'escaped' if s['won'] else 'move'

def advance(b,s):
    if s['won'] or s['hp']<=0:return
    for e in s['enemies']:
        if e['hp']<=0:continue
        ph=phase(e,s['beat'])
        if e['kind'] in ('crawler','hopper') and ph==0:continue
        if e['kind']=='lancer' and ph!=1:continue
        x,y=e['pos']; px,py=s['player']; distance=abs(x-px)+abs(y-py)
        if e['kind']=='lancer':
            # Telegraph is the four adjacent tiles, drawn by the browser.
            if distance==1:s['hp']-=1
            continue
        choices=sorted(enumerate(DELTAS.values()),key=lambda v:(abs(x+v[1][0]-px)+abs(y+v[1][1]-py),v[0]))
        for i,(dx,dy) in choices:
            if i==4:continue
            p=[x+dx,y+dy]
            if abs(p[0]-px)+abs(p[1]-py)>=distance:continue
            if p in b['walls'] or any(o is not e and o['hp']>0 and o['pos']==p for o in s['enemies']):continue
            if p==s['player']:s['hp']-=1
            else:e['pos']=p
            break
    s['beat']+=1;s['used']=False

def grade(payload,ground_truth,public_state):
    def fail(msg):return {'graded':True,'passed':False,'feedback':msg}
    if not all(isinstance(value, dict) for value in (payload, ground_truth, public_state)):
        return fail('invalid document')
    for k in ('mechanic_id','task_id','challenge_id'):
        if not ground_truth.get(k) or payload.get(k)!=ground_truth[k] or public_state.get(k)!=ground_truth[k]:return fail(k+' mismatch')
    if ground_truth['mechanic_id']!=MECHANIC_ID:return fail('wrong mechanic')
    if public_state.get('board')!=ground_truth.get('board') or public_state.get('control_condition')!=ground_truth.get('control_condition'):return fail('contract mismatch')
    b=ground_truth['board'];s=initial(b)
    source='keyboard' if (ground_truth.get('control_condition') or {}).get('interaction','full')=='full' else 'direction_buttons'
    events=payload.get('actions');end=payload.get('final_ms')
    def valid_time(t):return type(t) in (int,float) and math.isfinite(t) and 0<=t<=b['max_beats']*b['beat_ms']
    if not isinstance(events,list) or len(events)>1000 or not valid_time(end):return fail('invalid transcript')
    last=0
    for i,e in enumerate(events):
        if not isinstance(e,dict) or e.get('sequence')!=i+1 or e.get('input_source')!=source or not isinstance(e.get('key'), str) or e['key'] not in DELTAS:return fail('invalid input')
        t=e.get('ms')
        if not valid_time(t) or t<last or t>end:return fail('invalid time')
        if t >= b['max_beats']*b['beat_ms']:return fail('input after clock exhausted')
        if s['won'] or s['hp']<=0:return fail('input after terminal state')
        while s['beat']<int(t//b['beat_ms']) and s['hp']>0:advance(b,s)
        if s['hp']<=0:return fail('input after death')
        outcome='offbeat' if t%b['beat_ms']>=b['open_ms'] else act(b,s,e['key'])
        if e.get('outcome')!=outcome:return fail('action outcome mismatch')
        last=t
    while s['beat']<int(end//b['beat_ms']) and s['hp']>0 and not s['won']:advance(b,s)
    passed=s['won'] and s['hp']>0 and payload.get('final_state')==s
    return {'graded':True,'passed':passed,'feedback':f"{'PASS' if passed else 'FAIL'} · health {s['hp']} · sentries {sum(e['hp']>0 for e in s['enemies'])} · exit {s['won']}"}

import heapq, itertools
def find_route(board,state=None,limit=100000):
    start=deepcopy(state or initial(board));serial=itertools.count()
    def ident(s):return (tuple(s['player']),s['hp'],s['beat'],s['used'],tuple((tuple(e['pos']),e['hp']) for e in s['enemies']))
    def estimate(s):
        live=[e for e in s['enemies'] if e['hp']>0];p=s['player']
        return sum(e['hp'] for e in live)+(min(abs(p[0]-e['pos'][0])+abs(p[1]-e['pos'][1]) for e in live) if live else abs(p[0]-board['exit'][0])+abs(p[1]-board['exit'][1]))
    q=[(0,next(serial),0,start,[])];best={ident(start):0}
    while q and len(best)<limit:
        _,_,cost,s,path=heapq.heappop(q)
        if s['won']:return path
        if cost>60:continue
        for key in DELTAS:
            n=deepcopy(s);out=act(board,n,key)
            if out in ('wall','unavailable','shield'):continue
            if not n['won']:advance(board,n)
            if n['hp']<=0:continue
            nc=cost+1+(s['hp']-n['hp'])*12
            identn=ident(n)
            if nc>=best.get(identn,10**9):continue
            best[identn]=nc;heapq.heappush(q,(nc+3*estimate(n),next(serial),nc,n,path+[key]))
    raise RuntimeError('No route found within planner budget')
