"""Independent replay with one deliberate-control step per fixed 20 ms tick."""
import bisect
import copy
import math

MECHANIC_ID = 'four_pane_pilgrimage_v3_nonrealtime'
ACTION_TICKS = 1


def pose(panel, t):
    knots = panel['knots']
    i = min(len(knots)-2, max(0, bisect.bisect_right([k[0] for k in knots], t)-1))
    a, b = knots[i:i+2]
    f = max(0, min(1, (t-a[0])/(b[0]-a[0])))
    s = f*f*(3-2*f)
    return [a[j]+(b[j]-a[j])*s for j in range(1, 4)]


def initial(world):
    # Acetates are separate from their pictures until physically stacked.
    return dict(tick=0, active=False, slots=world['initial_slots'].copy(), layers=[None]*4, uncovered=[False]*4,
                windows=[[170., 110., 44.] for _ in range(4)], progress=0., terminal=None)


def registered(world, state, index, t=None):
    target = pose(world['panels'][index], state['tick']*world['tick_ms'] if t is None else t)
    window = state['windows'][index]
    return (state['layers'][index] == index and
            math.hypot(window[0]-target[0], window[1]-target[1]) <= world['parameters']['position_tolerance'] and
            abs(window[2]-target[2]) <= world['parameters']['radius_tolerance'])


def advance(world, state, tick):
    if tick < state['tick'] or tick > state['tick'] + ACTION_TICKS:
        raise ValueError('autonomous task clock advance')
    while state['tick'] < tick and state['active'] and state['terminal'] is None:
        state['tick'] += 1
        good = state['slots'] == world['route'] and all(registered(world, state, i) for i in range(4))
        state['progress'] = max(0., min(world['journey_ms'], state['progress'] + world['tick_ms'] * (1 if good else -world['retreat_rate'])))
        if state['progress'] >= world['journey_ms']: state['terminal'] = 'arrived'
        elif state['tick']*world['tick_ms'] >= world['burn_ms']: state['terminal'] = 'burnt'
    return state


def finite(v):
    return type(v) in (int, float) and math.isfinite(v)


def point(v):
    return isinstance(v, list) and len(v) == 2 and all(finite(n) for n in v) and 0 <= v[0] <= 340 and 0 <= v[1] <= 220


def apply(world, state, e, mode):
    kind = e['kind']
    if kind == 'begin':
        if state['active'] or state['terminal'] is not None or e.get('input_source') != 'begin_button': raise ValueError('duplicate or invalid begin')
        state['active'] = True
        return
    if kind == 'seal':
        if e.get('input_source') != 'seal_button': raise ValueError('invalid seal')
        if state['terminal'] != 'arrived': state['terminal'] = 'sealed_incomplete'
        return
    if state['terminal'] is not None: raise ValueError('input after terminal outcome')
    if e.get('input_source') != mode: raise ValueError('wrong interaction surface')
    i = e.get('panel')
    if type(i) is not int or i not in range(4): raise ValueError('unknown picture')
    if kind == 'uncover':
        if state['uncovered'][i]: raise ValueError('vellum already lifted')
        if e.get('gesture') != ('right_click' if mode == 'full' else 'lift_button'): raise ValueError('wrong lift surface')
        state['uncovered'][i] = True
    elif kind == 'swap':
        slot = e.get('slot')
        if type(slot) is not int or slot not in range(4): raise ValueError('bad slot')
        if mode == 'full' and e.get('gesture') != 'header_drag': raise ValueError('missing header drag')
        if mode == 'simplified' and e.get('gesture') != 'header_pair': raise ValueError('missing header pair')
        prev = state['slots'].index(i); state['slots'][prev], state['slots'][slot] = state['slots'][slot], i
    elif kind == 'stack':
        layer = e.get('layer')
        if type(layer) is not int or layer not in range(4) or layer in state['layers']: raise ValueError('invalid or already used acetate')
        if state['layers'][i] is not None or not point(e.get('point')): raise ValueError('invalid stack pose')
        if mode == 'full' and e.get('gesture') != 'tray_drag': raise ValueError('missing tray drag')
        if mode == 'simplified' and e.get('gesture') != 'tray_pair': raise ValueError('missing tray pair')
        state['layers'][i] = layer; state['windows'][i][:2] = [max(world['bounds'][a][0], min(world['bounds'][a][1], n)) for a,n in zip(('x','y'),e['point'])]
    elif kind == 'peel':
        if not state['uncovered'][i]: raise ValueError('lift the vellum before the acetate')
        if state['layers'][i] is None: raise ValueError('no acetate to lift')
        if e.get('gesture') != ('right_click' if mode == 'full' else 'lift_button'): raise ValueError('wrong lift surface')
        state['layers'][i] = None
    elif kind == 'pan':
        if state['layers'][i] is None or not point(e.get('point')): raise ValueError('unstacked window or invalid point')
        dest = e['point']
        if mode == 'full':
            start, end = e.get('start'), e.get('end')
            if not point(start) or not point(end): raise ValueError('missing direct pan coordinates')
            expected = [max(world['bounds'][a][0], min(world['bounds'][a][1], state['windows'][i][j]+end[j]-start[j])) for j,a in enumerate(('x','y'))]
            if math.dist(expected,dest) > .025: raise ValueError('pan differs from physical displacement')
        elif e.get('gesture') != 'point_click': raise ValueError('missing chosen-position click')
        state['windows'][i][:2] = [max(world['bounds'][a][0], min(world['bounds'][a][1], n)) for a,n in zip(('x','y'),dest)]
    elif kind == 'zoom':
        direction = e.get('direction')
        if state['layers'][i] is None or type(direction) is not int or direction not in (-1,1): raise ValueError('invalid scale')
        if mode == 'full' and (not finite(e.get('delta_y')) or e['delta_y']*direction >= 0 or not point(e.get('point'))): raise ValueError('invalid wheel evidence')
        if mode == 'simplified' and e.get('gesture') != 'scale_button': raise ValueError('invalid scale button')
        state['windows'][i][2] = max(24, min(66, state['windows'][i][2]+direction*world['radius_step']))
    else: raise ValueError('unavailable control '+str(kind))


def grade(payload, ground_truth, public_state):
    fail = lambda msg: dict(graded=True, passed=False, score=0, feedback=str(msg))
    try:
        if not all(isinstance(x,dict) for x in (payload, ground_truth, public_state)): return fail('invalid objects')
        for k in public_state:
            if ground_truth.get(k) != public_state[k]: return fail('public/truth mismatch '+k)
        for k in ('mechanic_id','task_id','challenge_id'):
            if not ground_truth.get(k) or payload.get(k) != ground_truth[k]: return fail('wrong or stale '+k)
        if ground_truth['mechanic_id'] != MECHANIC_ID: return fail('wrong game')
        mode = (public_state.get('control_condition') or {}).get('interaction','full')
        if mode not in ('full','simplified') or payload.get('interaction_mode') != mode: return fail('wrong mode')
        events=payload.get('events')
        if not isinstance(events,list) or not 2 <= len(events) <= 15000: return fail('empty or excessive transcript')
        s = initial(public_state); sealed = False; prev = 0
        for n,e in enumerate(events,1):
            if not isinstance(e,dict) or e.get('sequence') != n or sealed: return fail('invalid event sequence')
            tick=e.get('tick')
            if type(tick) is not int or not prev <= tick <= public_state['burn_ms']//public_state['tick_ms']: return fail('invalid task tick')
            if not s['active'] and tick != 0: return fail('clock before begin')
            advance(public_state,s,tick)
            # A terminal arrival/burn freezes world time. A later seal uses that exact tick.
            if s['tick'] != tick: return fail('event beyond frozen terminal tick')
            apply(public_state,s,e,mode); prev=tick
            sealed=e['kind']=='seal'
        if not sealed or s['terminal'] != 'arrived' or payload.get('completed') is not True: return fail('pilgrim did not arrive')
        f=payload.get('final_state')
        if not isinstance(f,dict) or f.get('slots') != s['slots'] or f.get('layers') != s['layers'] or f.get('tick') != s['tick']: return fail('final state mismatch')
        if f.get('uncovered') != s['uncovered'] or any(type(x) is not bool for x in f['uncovered']): return fail('vellum state mismatch')
        if not finite(f.get('progress')) or abs(f['progress']-s['progress']) > .01 or f.get('windows') != s['windows']: return fail('final geometry mismatch')
        return dict(graded=True,passed=True,score=100,feedback='Independent registration and light-path replay: shrine reached',ticks=s['tick'])
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as exc:
        return fail('Invalid registration replay: '+str(exc))


def cheat(public_state, ground_truth):
    return {'note':'No solution injection. Use mouse and keyboard.'}
