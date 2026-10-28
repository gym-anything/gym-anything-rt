"""Privileged planning oracle; every input uses the frozen native HTTP gateway.

This is a solvability demonstration, not a screenshot-only agent policy. Read-only
diagnostics supply the current joint commands, task clock and canvas rectangles.
The generated path supports planning within the visibly drawn 800 ms forecast.
"""
import math
import time


def _target(world, ms):
    values = []
    for path in world['paths']:
        times = path['times_ms']
        n = next((i for i in range(len(times)-1) if ms < times[i+1]), len(times)-2)
        f = max(0, min(1, (ms-times[n])/(times[n+1]-times[n])))
        values.append(path['knots'][n]+(path['knots'][n+1]-path['knots'][n])*f*f*(3-2*f))
    return values


def _ring(angle):
    a = math.radians(angle-90)
    return [110+40*math.cos(a), 67+40*math.sin(a)]


def _screen(rect, point):
    return [rect[0]+point[0]*rect[2]/220, rect[1]+point[1]*rect[3]/115]


def tracking_commands(state, world, horizon_ms=240, delivery_ms=0):
    """Fit a held command to the existing servo response and visible forecast.

    This oracle uses private joint state for planning. Unlike a constant time
    lead, it accounts for current velocity and curved socket trajectories.
    It neither changes task time nor writes a browser state variable.
    """
    tick = world['tick_ms']
    delivery = max(0, round((state.get('nowMs', state['ms'])-state['ms']+delivery_ms)/tick)*tick)
    steps = max(2, round(horizon_ms/tick))
    if delivery + steps*tick > world['forecast_ms']:
        raise ValueError('servo planning exceeds the visible forecast')
    p = world['parameters']
    dt = tick/1000
    goals = [_target(world, state['ms']+delivery+i*tick) for i in range(1, steps+1)]
    response, x, velocity = [], 0., 0.
    for _ in range(steps):
        velocity += (p['servo_gain']*(1-x)-p['servo_damping']*velocity)*dt
        x += velocity*dt
        response.append(x)
    denominator = sum(x*x for x in response)
    commands = []
    for joint, angle in enumerate(state['angles']):
        velocity = state['velocity'][joint]
        for _ in range(delivery//tick):
            acceleration = max(-p['max_acceleration'], min(p['max_acceleration'],
                p['servo_gain']*(state['command'][joint]-angle)-p['servo_damping']*velocity))
            velocity = max(-p['max_speed'], min(p['max_speed'], velocity+acceleration*dt))
            angle += velocity*dt
        numerator = 0.
        for goal, coefficient in zip(goals, response):
            velocity += (-p['servo_gain']*angle-p['servo_damping']*velocity)*dt
            angle += velocity*dt
            numerator += coefficient*(goal[joint]-angle)
        limit = world['command_limit_deg']
        commands.append(max(-limit, min(limit, numerator/denominator)))
    return commands


def linkage_from_image(path):
    """Read an actual control screenshot, without page state or seed data.

    The visible numbered atoms define four colors. A learned caption shares
    its atom's color; SAME and REVERSED have different visible word extents.
    Gray UNKNOWN captions produce no linkage. This task-specific visual reader
    supports discovery evidence, not a claim about the full tracking policy.
    """
    from PIL import Image

    colors = ((255, 186, 112), (121, 223, 206), (186, 161, 255), (251, 135, 177))
    background = (11, 25, 40)
    with Image.open(path) as screenshot:
        width, height = screenshot.size
        matches = []
        for color in colors:
            vector = [a-b for a, b in zip(color, background)]
            denominator = sum(a*a for a in vector)
            xs = []
            for x in range(round(width*16/220), round(width*204/220)):
                for y in range(round(height*82/115), round(height*96/115)):
                    pixel = screenshot.getpixel((x, y))
                    relative = [pixel[i]-background[i] for i in range(3)]
                    alpha = sum(a*b for a, b in zip(relative, vector))/denominator
                    if (.25 < alpha < 1.1
                            and max(abs(relative[i]-alpha*vector[i]) for i in range(3)) < 4):
                        xs.append(x*220/width)
            matches.append(xs)
    winners = [i for i, xs in enumerate(matches) if len(xs) >= 30]
    if not winners:
        return None
    if len(winners) != 1:
        raise ValueError('ambiguous visible linkage caption')
    joint = winners[0]
    right_edge = max(matches[joint])
    if not (95 <= right_edge <= 115 or 128 <= right_edge <= 145):
        raise ValueError('unrecognized visible direction word')
    return dict(joint=joint, direction=-1 if right_edge >= 128 else 1)


def drive_actions(state, world, mode, desired):
    """Translate physical joint goals through the same seeded transmissions."""
    actions = []
    for drive, link in enumerate(world['drive_linkages']):
        bond, direction = link['joint'], link['direction']
        rect = state['controls'][drive]
        angle = direction * desired[bond]
        if mode == 'simplified':
            actions.append({'mouse': {'left_click': _screen(rect, [110+angle*90/85, 67])}})
        else:
            start = _screen(rect, _ring(direction * state['command'][bond]))
            end = _screen(rect, _ring(angle))
            actions.extend([{'mouse': {'move': start, 'buttons': {'left_down': True}}},
                            {'mouse': {'move': end}},
                            {'mouse': {'buttons': {'left_up': True}}}])
    return actions


READ = """(() => {
 const m=window.pocketLocksmithV3Model;
 const rect=n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height];};
 return {ms:m.physics.ms, nowMs:m.armed?Math.floor((performance.now()-m.startedAt)/20)*20:0,
   command:m.physics.command, angles:m.physics.angles, velocity:m.physics.velocity,
   terminal:m.terminal, failed:m.physics.failed,
   boundMs:m.physics.boundMs, done:m.physics.done,
   controls:[...document.querySelectorAll('.pk-dial')].map(rect),
   start:rect(document.querySelector('#pk-start')),
   submit:rect(document.querySelector('#pk-submit')), result:m.result||null};
})()"""


def solve(ui, truth, execution_mode='live', observation_delay_ms=0, parked=False):
    assert getattr(ui, 'native_http_action_api', False), 'Only the verified native HTTP UI can execute this oracle'
    state = ui.read(READ)
    world = truth['world']
    mode = (truth.get('control_condition') or {}).get('interaction', 'full')
    # Safe ordinary inputs reveal the linkage labels, then restore neutral.
    # Planning remains privileged; this is not a screenshot-only policy.
    if not parked:
        ui.send(drive_actions(state, world, mode, [8.] * len(world['paths'])))
        state = ui.read(READ)
        ui.send(drive_actions(state, world, mode, [0.] * len(world['paths'])))
        state = ui.read(READ)
    ui.send([{'mouse': {'left_click': [state['start'][0]+state['start'][2]/2, state['start'][1]+state['start'][3]/2]}}])
    # Paused observations advance 240 ms of task time but can take several
    # seconds of wall time. Keep a finite limit inside the episode's 600 s budget.
    wall_limit = 540 if execution_mode == 'paused' else 150
    deadline = time.monotonic()+wall_limit
    samples = []
    while time.monotonic() < deadline:
        began = time.monotonic()
        state = ui.read(READ)
        samples.append(state)
        if state['terminal']:
            # The automatic physical completion submits once. Result grading is asynchronous.
            if state['result'] is None:
                ui.wait(.05)
                continue
            return dict(samples=samples, successful=state['result'].get('passed') is True,
                        privileged_planning=True, source='current model state and generated path within visible forecast')
        if parked:
            ui.send([])
        else:
            observed = dict(state, ms=max(0, state['ms']-observation_delay_ms),
                            nowMs=max(0, state['nowMs']-observation_delay_ms))
            desired = tracking_commands(observed, world)
            ui.send(drive_actions(state, world, mode, desired))
        if execution_mode == 'live':
            ui.wait(max(0, .24-(time.monotonic()-began)))
    raise TimeoutError('Pocket binding trial did not terminate within the declared oracle budget')
