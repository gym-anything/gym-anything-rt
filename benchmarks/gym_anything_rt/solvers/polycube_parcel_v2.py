"""Privileged packing plan, current-state feedback, literal public inputs only.

The transport must implement read(expression), send(native_actions), wait(seconds).
Production evidence uses the unchanged persistent same-machine HTTP gateway.
Read-only diagnostics reveal current motor/cradle state and DOM rectangles, and
the private exact cover supplies planning. This is NOT screenshot-only agent data.
No future motion samples, browser actions or DOM mutations are used by this solver.
"""
from collections import deque
import json
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.polycube_parcel_v2 import ROTATIONS, matmul, normalized


def box(ui, selector):
    return ui.read('(() => {const r=document.querySelector('+json.dumps(selector)+').getBoundingClientRect();return [r.x,r.y,r.width,r.height];})()')


def click(ui, selector):
    r = box(ui, selector)
    ui.send([{'mouse': {'left_click': [round(r[0] + r[2]/2), round(r[1] + r[3]/2)]}}])


def turns(shape, current, desired):
    target = sorted(normalized(dict(shape=shape, orientation=desired)))
    queue = deque([(current, [])])
    seen = set()
    while queue:
        matrix, path = queue.popleft()
        key = tuple(map(tuple, matrix))
        if key in seen:
            continue
        seen.add(key)
        if sorted(normalized(dict(shape=shape, orientation=matrix))) == target:
            return path
        for axis, options in ROTATIONS.items():
            for direction, rotation in options.items():
                queue.append((matmul(rotation, matrix), path + [(axis, direction)]))
    raise ValueError('piece cannot reach its certified orientation by rigid rotations')


def aim_actions(rect_xy, rect_z, target, position, full):
    lo, span = -1.25, 5.5
    def xy(v):
        return [round(rect_xy[0] + (v[0]-lo)/span*rect_xy[2]),
                round(rect_xy[1] + (1-(v[1]-lo)/span)*rect_xy[3])]
    def z(v):
        return [round(rect_z[0]+rect_z[2]/2), round(rect_z[1]+(1-(v[2]-lo)/span)*rect_z[3])]
    target = [max(-1.20, min(4.20, v)) for v in target]
    if not full:
        return [{'mouse': {'left_click': xy(target)}}, {'mouse': {'left_click': z(target)}}]
    actions = []
    for start, end in [(xy(position), xy(target)), (z(position), z(target))]:
        actions.extend([{'mouse': {'move': start, 'buttons': {'left_down': True}}},
                        {'mouse': {'move': end}}, {'mouse': {'buttons': {'left_up': True}}}])
    return actions


def solve(ui, truth, *, observation_delay_ms=0, parked=False, deadline_seconds=180):
    """Matched delayed/parked policies use the same cover and initial conditions."""
    full = truth['control_condition']['interaction'] == 'full'
    xy, zr = box(ui, '.pv-xy'), box(ui, '.pv-z')
    initial = ui.read('window.__polycubeParcelV2Diagnostic')
    first_offset = initial['offset']
    click(ui, '.pv-start')
    samples, errors, seating_errors = deque(), [], []
    deadline = time.monotonic() + deadline_seconds
    for pid, plan in truth['solution_placements'].items():
        current = ui.read('window.__polycubeParcelV2Diagnostic')
        if current['pieces'][pid]['placed']:
            continue
        click(ui, f'[data-piece="{pid}"]')
        for axis, direction in turns(current['pieces'][pid]['shape'], current['pieces'][pid]['orientation'], plan['orientation']):
            click(ui, f'[data-turn="{axis}"][data-direction="{direction}"]')
        while time.monotonic() < deadline:
            state = ui.read('window.__polycubeParcelV2Diagnostic')
            if state['failed']:
                return dict(completed=False, failed=state['failed'], ms=state['ms'], policy='parked' if parked else 'delayed' if observation_delay_ms else 'timely')
            if state['pieces'][pid]['placed']:
                break
            samples.append((state['ms'], state['offset'], state['position']))
            while len(samples)>2 and samples[1][0] < state['ms']-max(1500,observation_delay_ms+500):
                samples.popleft()
            observation = next((x for x in reversed(samples) if x[0]<=state['ms']-observation_delay_ms), samples[0])
            prior = next((x for x in reversed(samples) if x[0]<=observation[0]-240), observation)
            elapsed = max(.001, (observation[0]-prior[0])/1000)
            velocity = [(a-b)/elapsed for a,b in zip(observation[1],prior[1])] if elapsed>.05 else [0,0,0]
            # Feed-forward compensates the visible motor's 250-ms group delay.
            desired = [plan['origin'][i] + (first_offset[i] if parked else observation[1][i]+velocity[i]*.30) for i in range(3)]
            ui.send(aim_actions(xy,zr,desired,observation[2] if observation_delay_ms else state['position'],full))
            state = ui.read('window.__polycubeParcelV2Diagnostic')
            actual_error = max(abs(state['position'][i]-state['offset'][i]-plan['origin'][i]) for i in range(3))
            errors.append(actual_error)
            if state['docking']:
                seating_errors.append(actual_error)
            # Delayed controls also decide whether to commit using the delayed
            # motor and cradle sample; fresh state is only diagnostic here.
            error = max(abs(observation[2][i]-observation[1][i]-plan['origin'][i]) for i in range(3)) if observation_delay_ms else actual_error
            if not state['docking'] and error < truth['world']['profile']['tolerance']*.38:
                if full:
                    ui.send([{'keyboard': {'keys': ['Space']}}])
                else:
                    click(ui, '.pv-seat')
            if getattr(ui, 'execution_mode', 'live') != 'paused':
                ui.wait(.045)
        else:
            return dict(completed=False, failed='oracle time budget exhausted', ms=state['ms'])
    state = ui.read('window.__polycubeParcelV2Diagnostic')
    if state['completed']:
        click(ui, '.pv-submit')
        ui.wait(.4)
    return dict(completed=bool(state['completed']), failed=state['failed'], ms=state['ms'],
                policy='parked' if parked else 'delayed' if observation_delay_ms else 'timely',
                max_motor_error_including_transfers=max(errors,default=0),
                max_observed_seating_error=max(seating_errors,default=0), observation_delay_ms=observation_delay_ms)
