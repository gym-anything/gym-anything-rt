"""Construction oracle. Privileged read-only scene planning; HTTP inputs only.

The UI object is supplied by the existing native validation recipe. This is not
a model evaluation or evidence of screenshot-only oracle perception.
"""
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.trace_shape_without_walls_v3 import center, wind


def target(world, x, ms):
    # Invert the unchanged critically damped steering response at the middle
    # of a 120ms control interval. Central differences anticipate braking at
    # bends; the inherited backward-only estimate could overshoot V3 seeds.
    h = .04
    at = ms + 60
    xx = min(world['exit_x'], x + world['speed'] * .06)
    previous = center(world, xx-world['speed']*h, at-1000*h)
    current = center(world, xx, at)
    following = center(world, min(world['exit_x'], xx+world['speed']*h), at+1000*h)
    velocity = (following-previous)/(2*h)
    acceleration = (following-2*current+previous)/(h*h)
    return max(0, min(480, current+2/world['response']*velocity
                      +(acceleration-wind(world, at))/world['response']**2))


def box(ui, selector):
    return ui.read(f'(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; }})()')


def solve(ui, truth, *, deadline_seconds=70):
    rect = box(ui, '#trace-v2-scope')
    launch = box(ui, '#trace-v2-launch')
    mode = (truth.get('control_condition') or {}).get('interaction', 'full')
    world = truth['world']
    # Ordinary pointer inspection acquires the concealed geometry in both
    # modes. No private coordinates or scan quota are needed for this sweep.
    for x in range(0, 1001, 100):
        ui.send([{'mouse': {'move': [rect[0]+x*rect[2]/1000,
                                  rect[1]+rect[3]/2]}}])
    ui.send([{'mouse': {'left_click': [launch[0]+launch[2]/2, launch[1]+launch[3]/2]}}])
    held = False
    deadline = time.monotonic()+deadline_seconds
    while time.monotonic() < deadline:
        state = ui.read('({x:traceShapeV3Model.physics.x, y:traceShapeV3Model.physics.y, ms:traceShapeV3Model.physics.ms, done:traceShapeV3Model.physics.done, failed:traceShapeV3Model.physics.failed, verdict:traceShapeV3Model.verdict})')
        if state['failed']:
            raise AssertionError('Native trace failed: '+str(state))
        if state['done']:
            # Automatic certification is asynchronous. Reaching the physical
            # endpoint is not yet an exported grade. Read without sending
            # further inputs: the frozen gateway may already be terminal.
            if state['verdict'] == 'PASS':
                return
            if state['verdict'] in ('FAIL', 'ERROR'):
                raise AssertionError('Native certification failed: '+str(state))
            ui.wait(.1)
            continue
        y = target(world, state['x'], state['ms'])
        point = [rect[0]+500*rect[2]/1000, rect[1]+y*rect[3]/480]
        if mode == 'full':
            mouse = dict(move=point)
            if not held:
                mouse['buttons'] = {'left_down': True}
                held = True
            ui.send([{'mouse': mouse}])
        else:
            ui.send([{'mouse': {'left_click': point}}])
        ui.wait(.12)
    raise AssertionError(f'Native sonar trace exceeded the declared {deadline_seconds}-second controller deadline')
