"""Task-specific feedback oracle. Privileged state is used ONLY for planning.

solve_http takes the frozen downstream gateway interface; every input uses
ui.send(mouse actions). This is not a screenshot-only model result.
"""
from __future__ import annotations

import heapq
import math

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.apothecary_dead_reckoning_v3 import center, flow, target_velocity

ID = "apothecary_dead_reckoning_v3"
# Leave primitive-input margin for full-mode drags at fast native delivery.
# This controls oracle feedback only; the world keeps its existing 20-ms ticks.
HTTP_FEEDBACK_INTERVAL_MS = 700


def waypoint(world, position, goal):
    """A* around whole swept bone envelopes, followed by line-of-sight smoothing."""
    grid = 16
    inflated = [(b["center"], b["radius"] + 8 + b["sway"] * math.sqrt(2) + 5)
                for b in world["bones"]]
    def safe(p):
        return 20 <= p[0] <= 820 and 20 <= p[1] <= 440 and all(math.dist(p, c) > r for c, r in inflated)
    def node(p):
        raw = (round(p[0] / grid), round(p[1] / grid))
        nearby = [(raw[0] + x, raw[1] + y) for x in range(-3, 4) for y in range(-3, 4)]
        valid = [v for v in nearby if safe([v[0] * grid, v[1] * grid])]
        return min(valid, key=lambda v: math.dist([v[0] * grid, v[1] * grid], p)) if valid else raw
    def clear(a, b):
        steps = max(1, math.ceil(math.dist(a, b) / 8))
        return all(safe([a[i] + (b[i] - a[i]) * j / steps for i in range(2)]) for j in range(1, steps + 1))
    if clear(position, goal):
        return list(goal)
    start, end = node(position), node(goal)
    queue = [(math.dist(start, end), 0., start)]
    cost = {start:0.}
    parent = {}
    while queue:
        _, g, v = heapq.heappop(queue)
        if v == end:
            route = [v]
            while v != start:
                v = parent[v]; route.append(v)
            points = [[v[0] * grid, v[1] * grid] for v in reversed(route)]
            if safe(goal):
                points.append(list(goal))
            return next((p for p in reversed(points) if clear(position, p)), points[min(2, len(points)-1)])
        if g != cost.get(v):
            continue
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            n = (v[0] + dx, v[1] + dy)
            p = [n[0] * grid, n[1] * grid]
            if not safe(p) or not clear([v[0] * grid, v[1] * grid], p):
                continue
            ng = g + math.hypot(dx, dy)
            if ng < cost.get(n, float('inf')):
                cost[n] = ng; parent[n] = v
                heapq.heappush(queue, (ng + math.dist(n, end), ng, n))
    return list(goal)


def controls(world, observed):
    target = world["effects"][min(observed["progress"], len(world["effects"]) - 1)]
    ms = observed["tick"] * 20
    pos, velocity = observed["position"], observed["velocity"]
    target_pos = center(target, ms)
    tv = target_velocity(target, ms)
    aim = waypoint(world, pos, target_pos)
    tracking = math.dist(aim, target_pos) < 2
    err = [aim[i] - pos[i] for i in range(2)]
    desired = [(tv[i] if tracking else 0) + 1.1 * err[i] - .8 * (velocity[i] - (tv[i] if tracking else 0)) for i in range(2)]
    length = math.hypot(*desired)
    cap = 40 if not tracking or math.dist(pos, target_pos) > 55 else 28
    if length > cap:
        desired = [v * cap / length for v in desired]
    current = flow(world, pos, ms)
    thrust = [desired[i] - current[i] for i in range(2)]
    angle = math.degrees(math.atan2(thrust[1], thrust[0])) % 360
    base_angle = min(3, int(angle // 90)) * 90
    ingredient = next(i for i, herb in enumerate(world['ingredients']) if herb['angle_deg'] == base_angle)
    return dict(ingredient=ingredient, grind=(angle - base_angle) / 90,
                stir=min(1., math.hypot(*thrust) / world["mechanics"]["drive_speed"]), water=0.)


def simulated_solution(world, interval_ms=400, stale_ms=0):
    """Matched-state diagnostic, not an action-space solution demonstration."""
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.apothecary_dead_reckoning_v3 import Simulation
    sim = Simulation(world)
    events = []
    mode = world["control_condition"]["interaction"]
    def apply(kind, value=None):
        source = 'common_button' if kind == 'begin' else 'direct_drag' if mode == 'full' else 'proxy_click'
        event = dict(sequence=len(events)+1, tick=sim.tick, kind=kind, input_source=source)
        if value is not None:
            event['value'] = value
        if source == 'direct_drag':
            event.update(start=[.5,.5] if kind == 'ingredient' else [getattr(sim,kind),.5],
                         end=[.5,.5] if kind == 'ingredient' else [value,.5])
        sim.apply(event); events.append(event)
    apply('begin')
    history = [sim.snapshot()]
    while not (sim.failure or sim.done):
        available = [s for s in history if s['tick'] * 20 <= sim.tick * 20 - stale_ms]
        observed = available[-1] if available else history[0]
        values = controls(world, observed)
        for kind, value in values.items():
            if abs(getattr(sim,kind) - value) > 1e-5:
                apply(kind,value)
        sim.advance(sim.tick + max(1, interval_ms // 20))
        history.append(sim.snapshot())
    payload = dict(mechanic_id=ID,task_id=world['task_id'],challenge_id=world['challenge_id'],
                   interaction_mode=mode,events=events,final_tick=sim.tick,position=sim.position,
                   velocity=sim.velocity,progress=sim.progress,failure=sim.failure,completed=sim.done)
    return payload


def solve_http(ui, world, *, execution='live', interval_ms=HTTP_FEEDBACK_INTERVAL_MS):
    """ui.read is read-only privileged planning; ui.send is the sole input path."""
    expression = '''(() => {
      const m = window.apothecaryLivingAtlasModel, r = node => { const b = node.getBoundingClientRect(); return [b.left,b.top,b.width,b.height]; };
      return {state:m.physics.snapshot(), terminal:m.terminal, decision:m.decision || null,
        jars:[...document.querySelectorAll('[data-ingredient]')].map(r), mortar:r(document.querySelector('.apoth2-mortar')),
        course_marks:[...document.querySelectorAll('[data-ingredient] i')].map(n => n.textContent),
        tracks:Object.fromEntries([...document.querySelectorAll('[data-track]')].map(n => [n.dataset.track,r(n)])),
        begin:r(document.querySelector('#apoth2-begin'))};
    })()'''
    def point(rect, x=.5, y=.5):
        return [round(rect[0] + rect[2] * x), round(rect[1] + rect[3] * y)]
    def click(p):
        return [{'mouse':{'left_click':p}}]
    def drag(a,b):
        return [{'mouse':{'move':a,'buttons':{'left_down':True}}},
                {'mouse':{'move':b}}, {'mouse':{'buttons':{'left_up':True}}}]
    scene = ui.read(expression)
    # Obtain the botanical mapping from its revealed visible labels. Atlas
    # geometry and dynamic feedback remain privileged oracle planning inputs.
    for index, jar in enumerate(scene['jars']):
        if scene['course_marks'][index] != '?':
            continue
        a, b = point(jar), point(scene['mortar'])
        ui.send(drag(a, b) if world['control_condition']['interaction'] == 'full' else click(a))
    scene = ui.read(expression)
    marks = {'→': 0, '↓': 90, '←': 180, '↑': 270}
    if any(mark not in marks for mark in scene['course_marks']):
        raise ValueError('The visible mortar samples did not reveal all botanical courses')
    world = dict(world, ingredients=[dict(herb, angle_deg=marks[mark])
        for herb, mark in zip(world['ingredients'], scene['course_marks'])])
    if not scene['state']['active']:
        ui.send(click(point(scene['begin'])))
    limit = world['mechanics']['max_time_ms'] / 1000 + 30
    import time
    started = time.monotonic()
    while time.monotonic() - started < limit:
        scene = ui.read(expression)
        if scene['terminal']:
            if scene['decision'] is None:
                ui.wait(.05)
                continue
            return scene
        s = scene['state']
        wanted = controls(world, s)
        actions = []
        for kind, value in wanted.items():
            if kind == 'ingredient':
                if value == s[kind]:
                    continue
                a = point(scene['jars'][value]); b = point(scene['mortar'])
                actions.extend(drag(a,b) if world['control_condition']['interaction'] == 'full' else click(a))
            elif abs(s[kind] - value) > .018:
                rect = scene['tracks'][kind]
                # In both modes the effect is the exact same normalized endpoint.
                b = point(rect,value)
                actions.extend(drag(point(rect,s[kind]),b) if world['control_condition']['interaction'] == 'full' else click(b))
        ui.send(actions)
        if execution == 'live':
            ui.wait(interval_ms / 1000)
    raise TimeoutError('Apothecary oracle exceeded its declared active-time allowance')
