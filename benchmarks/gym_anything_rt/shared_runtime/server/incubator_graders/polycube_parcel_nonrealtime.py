"""Standalone independent tick replay, suitable for the pinned browser Python VM."""
from __future__ import annotations

import copy
import math

MECHANIC_ID = 'polycube_parcel_nonrealtime'
ROTATIONS = {
    'x': {1: [[1, 0, 0], [0, 0, -1], [0, 1, 0]], -1: [[1, 0, 0], [0, 0, 1], [0, -1, 0]]},
    'y': {1: [[0, 0, 1], [0, 1, 0], [-1, 0, 0]], -1: [[0, 0, -1], [0, 1, 0], [1, 0, 0]]},
    'z': {1: [[0, -1, 0], [1, 0, 0], [0, 0, 1]], -1: [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]},
}


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(spec, ms):
    if spec.get('mode') == 'fixed':
        ms = 0
    u = max(0, ms) / spec['span_ms']
    n, f = math.floor(u), u % 1
    h = f * f * (3 - 2 * f)
    return [a * (noise(spec['seed'] + i * 7919, n) * (1 - h) + noise(spec['seed'] + i * 7919, n + 1) * h)
            for i, a in enumerate(spec['amplitude'])]


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def normalized(piece):
    cells = [[sum(row[j] * c[j] for j in range(3)) for row in piece['orientation']] for c in piece['shape']]
    low = [min(c[i] for c in cells) for i in range(3)]
    return [[c[i] - low[i] for i in range(3)] for c in cells]


def cells(piece, origin):
    return [tuple(c[i] + origin[i] for i in range(3)) for c in normalized(piece)]


def occupied(state):
    return {c for p in state['pieces'].values() if p['placed'] for c in cells(p, p['origin'])}


def valid_origin(state, piece, origin):
    cover = cells(piece, origin)
    taken = occupied(state)
    return all(all(0 <= v < 3 for v in c) and c not in taken for c in cover)


def initial_state(contract):
    return dict(ms=0, started=False, selected=None, pieces={p['id']: copy.deepcopy(p) for p in contract['world']['pieces']},
                position=list(contract['world']['initial_position']), velocity=[0., 0., 0.],
                target=list(contract['world']['initial_position']), docking=None,
                failed=None, completed=False, placements=[], dragging=None)


def advance(state, contract, target_ms):
    if target_ms < state['ms']:
        raise ValueError('time moved backwards')
    # Wall-clock waiting is intentionally inert. Action handlers call
    # action_advance for the finite transitions that still use the donor's
    # motor and docking physics.
    state['ms'] = target_ms


def action_advance(state, contract, duration_ms):
    w = contract['world']
    target_ms = min(w['max_ms'], state['ms'] + duration_ms)
    dt = w['tick_ms'] / 1000
    while state['ms'] < target_ms and not state['failed'] and not state['completed']:
        if not state['started']:
            raise ValueError('action transition before launch')
        for i in range(3):
            acceleration = max(-w['max_acceleration'], min(w['max_acceleration'],
                               w['gain'] * (state['target'][i] - state['position'][i]) - w['damping'] * state['velocity'][i]))
            state['velocity'][i] = max(-w['max_speed'], min(w['max_speed'], state['velocity'][i] + acceleration * dt))
            state['position'][i] += state['velocity'][i] * dt
        state['ms'] += w['tick_ms']
        dock = state['docking']
        if dock:
            offset = motion(w['motion'], state['ms'])
            err = max(abs(state['position'][i] - offset[i] - dock['origin'][i]) for i in range(3))
            if err > w['profile']['tolerance'] + 1e-8:
                state['failed'] = 'alignment lost during seating'
            elif state['ms'] - dock['started_ms'] >= w['profile']['dock_ms']:
                piece = state['pieces'][dock['piece_id']]
                piece['placed'], piece['origin'] = True, list(dock['origin'])
                state['placements'].append(dict(piece_id=piece['id'], origin=list(dock['origin']), ms=state['ms']))
                state['docking'], state['selected'] = None, None
                if len(occupied(state)) == 27:
                    state['completed'] = True
        if state['ms'] >= w['max_ms'] and not state['completed']:
            state['failed'] = 'active time exhausted'


def apply_event(state, contract, event):
    """Only controls can affect the model. Seating success is never a trace input."""
    kind = event['kind']
    mode = contract['control_condition']['interaction']
    source = event.get('input_source')
    expected = {'start': 'start_button', 'select': 'piece_button', 'rotate': 'rotation_button',
                'camera': 'camera_button', 'abort': 'abort_button', 'submit': 'submit_button',
                'aim_xy': 'gantry_drag' if mode == 'full' else 'gantry_click',
                'aim_z': 'depth_drag' if mode == 'full' else 'depth_click',
                'seat': 'space_key' if mode == 'full' else 'seat_button'}
    if mode == 'full':
        expected.update(grab_xy='gantry_drag', release_xy='gantry_drag', grab_z='depth_drag', release_z='depth_drag')
    if kind not in expected or source != expected[kind]:
        raise ValueError('wrong control surface')
    if state['failed'] or state['completed']:
        if kind != 'submit':
            raise ValueError('input after terminal state')
        return
    if kind == 'start':
        if state['started'] or state['ms']:
            raise ValueError('duplicate launch')
        state['started'] = True
    elif kind == 'select':
        piece = state['pieces'][event['piece_id']]
        if piece['placed'] or state['docking']:
            raise ValueError('cannot select a seated or docking piece')
        state['selected'] = piece['id']
    elif kind == 'rotate':
        if state['docking'] or state['selected'] is None:
            raise ValueError('cannot turn an active seat or no piece')
        axis, direction = event['axis'], event['direction']
        if type(direction) is not int or direction not in (-1, 1) or axis not in ROTATIONS:
            raise ValueError('invalid turn')
        piece = state['pieces'][state['selected']]
        piece['orientation'] = matmul(ROTATIONS[axis][direction], piece['orientation'])
    elif kind in ('grab_xy', 'grab_z'):
        axes = [0, 1] if kind == 'grab_xy' else [2]
        values = event['values']
        if state['dragging'] is not None or len(values) != len(axes) or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('invalid handle grab')
        if math.dist(values, [state['position'][i] for i in axes]) > 22 / 320 * 5.5 + 1e-6:
            raise ValueError('drag did not begin on the visible gripper handle')
        state['dragging'] = 'xy' if len(axes) == 2 else 'z'
    elif kind in ('release_xy', 'release_z'):
        axis = 'xy' if kind == 'release_xy' else 'z'
        if state['dragging'] != axis:
            raise ValueError('release without a handle grab')
        state['dragging'] = None
    elif kind in ('aim_xy', 'aim_z'):
        axes = [0, 1] if kind == 'aim_xy' else [2]
        if mode == 'full' and state['dragging'] != ('xy' if len(axes) == 2 else 'z'):
            raise ValueError('full aiming requires a grabbed handle')
        values = event['values']
        if len(values) != len(axes) or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('invalid motor target')
        lo, hi = contract['world']['motor_bounds']
        if any(not lo <= v <= hi for v in values):
            raise ValueError('motor target outside rail')
        for axis, value in zip(axes, values):
            state['target'][axis] = float(value)
        # Preflight may position a motor; the cradle does not move until launch.
        if not state['started']:
            state['position'] = list(state['target'])
        else:
            action_advance(state, contract, contract['world']['action_motor_ms'])
    elif kind == 'seat':
        if not state['started'] or state['selected'] is None or state['docking']:
            raise ValueError('seat requires launch and a free selected piece')
        offset = motion(contract['world']['motion'], state['ms'])
        origin = [math.floor(state['position'][i] - offset[i] + .5) for i in range(3)]
        error = max(abs(state['position'][i] - offset[i] - origin[i]) for i in range(3))
        if error > contract['world']['profile']['tolerance'] + 1e-8:
            state['failed'] = 'seat initiated outside alignment halo'
        elif not valid_origin(state, state['pieces'][state['selected']], origin):
            state['failed'] = 'seat collides or protrudes outside parcel'
        else:
            state['docking'] = dict(piece_id=state['selected'], origin=origin, started_ms=state['ms'])
            action_advance(state, contract, contract['world']['profile']['dock_ms'])
    elif kind == 'camera':
        if event.get('direction') not in ('left', 'right', 'up', 'down'):
            raise ValueError('invalid camera orbit')
    elif kind == 'abort':
        state['failed'] = 'abandoned attempt'
    elif kind == 'submit':
        state['failed'] = 'submitted incomplete parcel'


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ('mechanic_id', 'task_id', 'challenge_id'):
            if payload.get(key) != ground_truth.get(key) or public_state.get(key) != ground_truth.get(key):
                return fail('stale or mismatched ' + key)
        if ground_truth.get('mechanic_id') != MECHANIC_ID:
            return fail('wrong mechanic')
        for key in ('world', 'control_condition'):
            if ground_truth.get(key) != public_state.get(key):
                return fail('public/private contract mismatch: ' + key)
        if payload.get('interaction_mode') != ground_truth['control_condition']['interaction']:
            return fail('wrong interaction mode')
        events = payload.get('events')
        if not isinstance(events, list) or not events:
            return fail('missing action trace')
        state = initial_state(ground_truth)
        for sequence, event in enumerate(events, 1):
            ms = event['ms']
            if (type(ms) is not int or not state['ms'] <= ms <= ground_truth['world']['max_ms']
                    or ms % ground_truth['world']['tick_ms'] or event.get('sequence') != sequence):
                return fail('invalid event order or tick')
            advance(state, ground_truth, ms)
            if state['ms'] != ms:
                return fail('action after terminal physics')
            apply_event(state, ground_truth, event)
        end = payload['ms']
        if type(end) is not int or end < state['ms'] or end % ground_truth['world']['tick_ms'] or end > ground_truth['world']['max_ms']:
            return fail('invalid final tick')
        advance(state, ground_truth, end)
        if state['ms'] != end:
            return fail('final tick after terminal physics')
        for key in ('position', 'velocity', 'target'):
            actual = payload.get(key)
            if not isinstance(actual, list) or len(actual) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in actual):
                return fail('invalid final ' + key)
            if max(abs(a - b) for a, b in zip(actual, state[key])) > .00002:
                return fail('final ' + key + ' differs from replay')
        if payload.get('placements') != state['placements']:
            return fail('seated placements differ from replay')
        if payload.get('completed') is not state['completed'] or payload.get('failed') != state['failed']:
            return fail('claimed outcome differs from replay')
        if not events or events[-1]['kind'] != 'submit':
            return fail('missing certification')
        passed = state['completed'] and state['failed'] is None and len(occupied(state)) == 27
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"{'Exact 27-cell cover and action-settled seating verified' if passed else state['failed'] or 'Incomplete parcel'}; {end} active ms; {len(state['placements'])} pieces seated")
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as exc:
        return fail('invalid packing transcript: ' + str(exc))


def cheat(public_state, ground_truth):
    return {'note': 'No UI solution overlay. Oracle planning is a separately disclosed validation activity.'}
