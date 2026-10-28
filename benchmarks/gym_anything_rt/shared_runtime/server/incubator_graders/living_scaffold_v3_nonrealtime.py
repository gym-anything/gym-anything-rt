"""Independent fixed-step mechanics and primitive-gesture replay; no client outcome trust."""
import math

MECHANIC_ID = 'living_scaffold_v3_nonrealtime'


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def noise(seed, i):
    x = (int(seed) ^ ((int(i)+1)*0x9E3779B9)) & 0xffffffff
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0, ms)/span
    i = math.floor(u)
    f = u-i
    a, b = noise(seed, i), noise(seed, i+1)
    return a+(b-a)*f*f*(3-2*f)


def wind(world, i, ms):
    p = world['parameters']
    return p['wind']*motion(world['lanes'][i]['wind_seed'], ms, p['wind_span_ms'])


def blossom(world, i, ms):
    lane = world['lanes'][i]
    p = world['parameters']
    return [world['anchor_x']+world['final_length']-7,
            lane['anchor_y']+lane['blossom_offset']+p['blossom_sway']*motion(lane['blossom_seed'], ms, p['blossom_span_ms'])]


def point(world, i, s, angle, offset=0):
    return [world['anchor_x']+s*math.cos(angle)+offset*math.sin(angle),
            world['lanes'][i]['anchor_y']+s*math.sin(angle)-offset*math.cos(angle)]


def sheath_hit(world, i, angle, position):
    centre=point(world,i,44,angle,world['radius']+world['skin_radius'])
    dx,dy=position[0]-centre[0],position[1]-centre[1]
    x=dx*math.cos(angle)+dy*math.sin(angle)
    y=-dx*math.sin(angle)+dy*math.cos(angle)
    return (x/57)**2+(y/25)**2 <= 1+1e-9


def initial(world):
    return dict(tick=0, failed=False, reason='', bridges=[dict(theta=0., target=0.,
        s=lane['initial_s'], v=lane['initial_v'], length=world['initial_length'],
        fed=False, docked=False, dock_tick=None) for lane in world['lanes']])


def advance(state, world, target_tick):
    dt = world['dt_ms']/1000
    p = world['parameters']
    while state['tick'] < target_tick and not state['failed'] and not all(b['docked'] for b in state['bridges']):
        # A restored blossom braces its completed support. Completed bridges
        # cannot leave an uncontrollable residual load on the remaining roots.
        old_angles = [0. if b['docked'] else b['theta'] for b in state['bridges']]
        for i, b in enumerate(state['bridges']):
            if b['docked']:
                continue
            others = [a for j, a in enumerate(old_angles) if j != i]
            recoil = p['coupling']*sum(others)/max(1,len(others))
            goal = clamp(b['target']-recoil, -world['max_angle'], world['max_angle'])
            change = clamp(goal-b['theta'], -p['slew']*dt, p['slew']*dt)
            b['theta'] += change
            omega = change/dt
            b['length'] = min(world['final_length'], b['length'] + (world['growth_speed']*dt if b['fed'] else 0))
            t = state['tick']*world['dt_ms']
            a = (5/7)*(p['gravity']*math.sin(b['theta']) + wind(world,i,t)*math.cos(b['theta']))
            a += b['s']*omega*omega - world['drag']*b['v']
            b['v'] += a*dt
            b['s'] += b['v']*dt
            if not b['fed'] and abs(b['s']-world['lanes'][i]['feed_s']) <= world['radius']+9:
                b['fed'] = True
            pod = point(world,i,b['s'],b['theta'],world['radius']+world['skin_radius'])
            mouth = blossom(world,i,t+world['dt_ms'])
            if b['fed'] and b['length'] == world['final_length'] and math.dist(pod,mouth)+world['radius'] <= p['blossom_radius'] and abs(b['v']) <= world['capture_speed']:
                b['docked'] = True
                b['dock_tick'] = state['tick']+1
            elif b['s'] < -world['radius'] or b['s'] > b['length']+world['radius']:
                state.update(failed=True, reason=f'Bridge {i+1}: pod fell')
                break
        state['tick'] += 1
        if state['tick']*world['dt_ms'] >= world['max_ms'] and not all(b['docked'] for b in state['bridges']):
            state.update(failed=True, reason='Garden run ended incomplete')
    return state


def set_target(state, world, i, angle):
    state['bridges'][i]['target'] = clamp(angle, -world['max_angle'], world['max_angle'])


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    if not all(isinstance(x,dict) for x in (payload,ground_truth,public_state)):
        return fail('Malformed result')
    for key in ('mechanic_id','task_id','challenge_id','control_condition'):
        if payload.get(key) != ground_truth.get(key) or public_state.get(key) != ground_truth.get(key):
            return fail('Stale identity or condition: '+key)
    if ground_truth.get('mechanic_id') != MECHANIC_ID or ground_truth.get('world') != public_state.get('world'):
        return fail('Wrong mechanic or geometry')
    mode = (ground_truth.get('control_condition') or {}).get('interaction','full')
    source = 'head_drag' if mode == 'full' else 'rail_click'
    events = payload.get('events')
    if not isinstance(events,list) or not 1 <= len(events) <= 10000:
        return fail('Missing or oversized transcript')
    w = ground_truth['world']
    state = initial(w)
    started = False
    held = None
    action_ticks = max(1, int(w.get('action_ticks', 4)))
    try:
        for seq,e in enumerate(events,1):
            tick=e['tick']
            if type(tick) is not int or tick != state['tick'] or not 0 <= tick <= w['max_ms']//w['dt_ms'] or e.get('seq') != seq:
                return fail('Invalid action order or stable decision tick')
            if state['failed'] or all(b['docked'] for b in state['bridges']):
                return fail('Input after terminal outcome')
            if e['kind']=='inspect':
                i=e['bridge']
                if type(i) is not int or not 0 <= i < len(state['bridges']) or e.get('input_source') != 'sheath_click' or held is not None:
                    return fail('Invalid sheath inspection')
                pos=e['point']
                if len(pos)!=2 or not all(type(v) in (int,float) and math.isfinite(v) for v in pos) or not sheath_hit(w,i,state['bridges'][i]['theta'],pos):
                    return fail('Inspection did not hit the visible leaf sheath')
                # Information probe only: no clock, physical state or quota effect.
            elif e['kind']=='start':
                if started or held is not None:
                    return fail('Duplicate start or held pre-run gesture')
                started=True
            elif e['kind'] in ('down','target','up'):
                i=e['bridge']
                if type(i) is not int or not 0 <= i < len(state['bridges']) or e.get('input_source') != source:
                    return fail('Wrong input surface or bridge')
                if state['bridges'][i]['docked'] and e['kind']!='up':
                    return fail('Cannot move a docked bridge')
                if e['kind']=='down':
                    if mode!='full' or held is not None:
                        return fail('Invalid head grab')
                    pos=e['point']
                    head=point(w,i,state['bridges'][i]['length'],state['bridges'][i]['theta'])
                    if len(pos)!=2 or not all(type(v) in (int,float) and math.isfinite(v) for v in pos) or math.dist(pos,head)>28.01:
                        return fail('Grab did not hit the visible head')
                    held=i
                elif e['kind']=='up':
                    if mode!='full' or held!=i:
                        return fail('Head release without grab')
                    held=None
                else:
                    pos=e['point']
                    if len(pos)!=2 or not all(type(v) in (int,float) and math.isfinite(v) for v in pos):
                        return fail('Invalid target point')
                    if mode=='full' and held!=i:
                        return fail('Target without a held head')
                    if mode=='simplified' and not (735+i*70<=pos[0]<=785+i*70 and abs(pos[1]-300)<=145):
                        return fail('Click outside visible rail')
                    origin=w['lanes'][i]['anchor_y'] if mode=='full' else 300
                    angle=clamp((pos[1]-origin)/530, -w['max_angle'],w['max_angle'])
                    set_target(state,w,i,angle)
                    if not started:
                        state['bridges'][i]['theta']=angle
                    elif mode in ('full','simplified'):
                        advance(state,w,min(state['tick']+action_ticks,w['max_ms']//w['dt_ms']))
            else:
                return fail('Unknown control; resets and brakes are unavailable')
        final=payload.get('final_tick')
        if not started or type(final) is not int or final != state['tick'] or not 0 <= final <= w['max_ms']//w['dt_ms']:
            return fail('Invalid final clock')
        if state['failed']:
            return fail(state['reason'])
        passed=all(b['docked'] for b in state['bridges']) and payload.get('completed') is True
        if not passed:
            return fail('Every pod must feed its bridge and physically enter its moving blossom')
        if payload.get('dock_ticks') != [b['dock_tick'] for b in state['bridges']]:
            return fail('Docking ledger differs from independent physics')
        return dict(graded=True,passed=True,score=100,feedback='PASS — growing supports, rolling gravity, wind and moving blossom contacts replayed')
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as exc:
        return fail('Invalid bridge transcript: '+str(exc))


def cheat(public_state,ground_truth):
    return {'note':'Oracle planning uses current physical state; no answer token.'}
