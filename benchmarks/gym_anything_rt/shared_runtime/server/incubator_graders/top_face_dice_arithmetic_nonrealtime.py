"""Independent replay for the stable-between-actions V2 counterpart.

The virtual physics clock advances only as the result of a recorded steering
gesture.  A wall-clock delay therefore cannot create an unrecorded state
change, while each deliberate pulse still uses the donor's geometry, motion,
seal, level and failure rules.
"""
from __future__ import annotations
import math

MECHANIC_ID='top_face_dice_arithmetic_nonrealtime'
NORMALS=((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))


def noise(seed,index):
    x=(int(seed)^((int(index)+1)*0x9E3779B9))&0xffffffff
    x=((x^(x>>16))*0x85EBCA6B)&0xffffffff
    x=((x^(x>>13))*0xC2B2AE35)&0xffffffff
    return ((x^(x>>16))&0xffffffff)/4294967295*2-1


def motor(seed,ms,span=4200):
    u=max(0,ms)/span;n=math.floor(u);f=u-n
    a,b=noise(seed,n),noise(seed,n+1)
    return a+(b-a)*f*f*(3-2*f)


def transform(point,spin,tilt,yaw):
    x,y,z=point;c,s=math.cos(spin),math.sin(spin)
    x,z=c*x+s*z,-s*x+c*z
    c,s=math.cos(tilt),math.sin(tilt);y,z=c*y-s*z,s*y+c*z
    c,s=math.cos(yaw),math.sin(yaw)
    return [c*x-s*y,s*x+c*y,z]


def pose(contract,state,index):
    d=contract['dice'][index];p=contract['parameters'];q=state['dice'][index]
    tilt=p['precession']*motor(d['tilt_seed'],state['tick']*20,6500)
    normals=[transform(v,q['spin'],tilt,d['yaw']) for v in NORMALS]
    face=max(range(6),key=lambda k:normals[k][2])
    return dict(x=480+p['travel']*math.sin(q['phase']),y=d['row_y']+14*math.sin(q['phase']*1.7),
                top=d['faces'][face],level=normals[face][2],spin=q['spin'],tilt=tilt,yaw=d['yaw'])


def initial_state(contract):
    return dict(tick=0,gripper=list(contract['initial_gripper']),velocity=[0.,0.],target=list(contract['initial_gripper']),
                dice=[dict(phase=d['phase'],spin=d['spin'],captured=False,value=None,seal=0.) for d in contract['dice']],
                captured=[],sum=0,failed='',terminal=False,dragging=False)


def advance(s,c,target_tick):
    p=c['parameters'];f=c['physics'];dt=.02
    while s['tick']<target_tick and not s['terminal']:
        s['tick']+=1;ms=s['tick']*20;gain=1+p['unload_gain']*len(s['captured'])
        for d,q in zip(c['dice'],s['dice']):
            if q['captured']: continue
            q['phase']+=p['drive_speed']*gain*(1+p['variation']*motor(d['drive_seed'],ms,f['motor_span_ms']))*dt
            q['spin']+=p['spin_speed']*gain*(1+p['variation']*motor(d['spin_seed'],ms,f['motor_span_ms']))*dt
        for axis in (0,1):
            a=(s['target'][axis]-s['gripper'][axis])*f['response']-s['velocity'][axis]*f['damping']
            a=max(-f['gripper_acceleration'],min(f['gripper_acceleration'],a))
            s['velocity'][axis]+=a*dt
        speed=math.hypot(*s['velocity'])
        if speed>f['gripper_speed']:s['velocity']=[v*f['gripper_speed']/speed for v in s['velocity']]
        s['gripper']=[max(35,min((925,495)[j],v+s['velocity'][j]*dt)) for j,v in enumerate(s['gripper'])]
        for i,q in enumerate(s['dice']):
            if q['captured']:continue
            v=pose(c,s,i);distance=math.dist(s['gripper'],[v['x'],v['y']])
            q['seal']=min(p['seal_seconds'],q['seal']+dt) if distance<=p['seal_radius'] else max(0.,q['seal']-2*dt)
        if ms>=f['max_ms']:s.update(failed='TIME LIMIT',terminal=True)


def action_pulse(s,c):
    """Finish one fixed, action-triggered transition before the next decision."""
    physics=c['physics']
    if physics.get('motion_mode')!='action_pulses' or physics.get('autonomous_motion') is not False:
        s.update(failed='INVALID MOTION CONTRACT',terminal=True)
        return
    steps=physics.get('action_step_ticks')
    if type(steps) is not int or steps<1:
        s.update(failed='INVALID ACTION STEP',terminal=True)
        return
    advance(s,c,s['tick']+steps)


def clamp(s,c):
    candidates=[]
    for i,q in enumerate(s['dice']):
        if not q['captured']:
            v=pose(c,s,i);distance=math.dist(s['gripper'],[v['x'],v['y']])
            if distance<=c['parameters']['seal_radius']:candidates.append((distance,i,v))
    if not candidates:s.update(failed='EMPTY CLAMP',terminal=True);return
    _,i,v=min(candidates);q=s['dice'][i]
    if q['seal']+1e-9<c['parameters']['seal_seconds']:s.update(failed='SEAL INCOMPLETE',terminal=True);return
    if v['level']+1e-9<c['physics']['level_cosine']:s.update(failed='FACE NOT LEVEL',terminal=True);return
    q.update(captured=True,value=v['top']);s['captured'].append(c['dice'][i]['id']);s['sum']+=v['top']
    remaining=len(s['dice'])-len(s['captured'])
    # Fail only outcomes that cannot be achieved even using attainable faces.
    minimum=sum(min(c['dice'][j]['faces'][k] for k in (0,1,4,5)) for j,qj in enumerate(s['dice']) if not qj['captured'])
    maximum=sum(max(c['dice'][j]['faces'][k] for k in (0,1,4,5)) for j,qj in enumerate(s['dice']) if not qj['captured'])
    if not s['sum']+minimum<=c['target_sum']<=s['sum']+maximum:s.update(failed='LOT CANNOT BALANCE',terminal=True)
    if not remaining:s['terminal']=True


def grade(payload,ground_truth,public_state):
    def fail(msg):return dict(graded=True,passed=False,score=0,feedback=msg)
    try:
        for k in ('mechanic_id','task_id','challenge_id','revision'):
            if not ground_truth.get(k) or payload.get(k)!=ground_truth[k] or public_state.get(k)!=ground_truth[k]:return fail('Stale or mismatched '+k)
        if ground_truth['mechanic_id']!=MECHANIC_ID:return fail('Wrong mechanic')
        for k in ('dice','parameters','physics','stage','initial_gripper','target_sum','control_condition'):
            if public_state.get(k)!=ground_truth.get(k):return fail('Contract mismatch '+k)
        c=ground_truth;mode=(c.get('control_condition') or {}).get('interaction','full')
        if payload.get('interaction_mode')!=mode or mode not in ('full','simplified'):return fail('Wrong interaction')
        events=payload.get('events')
        if not isinstance(events,list) or not 1<=len(events)<=6000:return fail('Missing or excessive trace')
        s=initial_state(c);started=False
        for seq,e in enumerate(events,1):
            tick=e['tick']
            if e.get('sequence')!=seq or type(tick) is not int or not s['tick']==tick or not 0<=tick<=9000 or s['terminal']:return fail('Invalid sequence/time or continued terminal attempt')
            if not started:
                if seq!=1 or e['kind']!='start' or tick!=0 or e.get('input_source')!='start_button':return fail('Run must start once')
                started=True;continue
            kind=e['kind'];point=e.get('point')
            if kind in ('drag_start','target','drag_end'):
                if not isinstance(point,list) or len(point)!=2 or any(type(v) not in (float,int) or not math.isfinite(v) for v in point):return fail('Invalid pointer geometry')
                if not 0<=point[0]<=960 or not 0<=point[1]<=520:return fail('Pointer outside stage')
                if kind=='drag_start':
                    if mode!='full' or e.get('input_source')!='gripper_drag' or s['dragging'] or math.dist(point,s['gripper'])>30:return fail('Drag did not start on gripper')
                    s['dragging']=True
                elif kind=='target':
                    if e.get('input_source')!=('gripper_drag' if mode=='full' else 'target_click') or mode=='full' and not s['dragging']:return fail('Wrong steering surface')
                    s['target']=point[:]
                    action_pulse(s,c)
                else:
                    if mode!='full' or e.get('input_source')!='gripper_drag' or not s['dragging']:return fail('Invalid drag release')
                    s['dragging']=False
            elif kind=='clamp':
                if e.get('input_source') not in ('clamp_button','space_key'):return fail('Wrong clamp surface')
                clamp(s,c)
            elif kind=='certify':
                if e.get('input_source')!='certify_button':return fail('Wrong certification surface')
                s.update(failed='INCOMPLETE LOT',terminal=True)
            else:return fail('Unknown control; no stop/reset/retry exists')
        end=payload.get('final_tick')
        if type(end) is not int or end!=s['tick'] or not 0<=end<=9000:return fail('Invalid final time')
        passed=s['terminal'] and not s['failed'] and len(s['captured'])==len(c['dice']) and s['sum']==c['target_sum']
        if payload.get('completed') is not passed or payload.get('captured_ids')!=s['captured'] or payload.get('top_sum')!=s['sum'] or payload.get('failure')!=s['failed']:return fail('Claimed outcome disagrees with independent replay')
        return dict(graded=True,passed=passed,score=100 if passed else 0,feedback=s['failed'] or f"Replayed {len(s['captured'])} physical catches; top sum {s['sum']}/{c['target_sum']}")
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as exc:return fail('Malformed transcript: '+str(exc))


def cheat(public_state,ground_truth):
    return dict(target_sum=ground_truth.get('target_sum'),dice=ground_truth.get('dice'))
