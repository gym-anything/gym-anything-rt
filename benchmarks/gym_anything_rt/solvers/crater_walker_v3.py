"""Privileged quadruped planner; every execution input uses ui.send(mouse actions).

Planning reads physical state and motor programs. This is an oracle, not a
screenshot-only agent. The planner never calls browser functions to take an
action or changes DOM/game state. Browser-only adapters establish wiring only.
"""
from __future__ import annotations

import copy
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.crater_walker_v3 import (
    Simulation, LEGS, pad_position, margin, hull,
)


def restore(world, snapshot):
    sim = Simulation(world)
    for key in ("ms", "active", "failed", "complete", "contacts", "offsets", "swing",
                "ballast", "body", "velocity", "unstable_ms", "landings"):
        setattr(sim, key, copy.deepcopy(snapshot[key]))
    return sim


def incenter(points):
    a, b, c = points
    weights = [math.dist(b[:2], c[:2]), math.dist(a[:2], c[:2]), math.dist(a[:2], b[:2])]
    return [sum(p[i]*v for p, v in zip(points, weights))/sum(weights) for i in range(2)]


def plan(world, snapshot, *, delivery_delay_ms=0):
    """Find a robust next stroke with a constant weight shift, then re-observe.

    All prediction horizons are below the visible three-second forecast.
    The implementation uses exact motor positions instead of decoding pixels.
    """
    current = restore(world, snapshot)
    if current.failed or current.complete or current.swing:
        return None
    current.advance(current.ms + delivery_delay_ms)
    if current.failed:
        return None
    unfinished = [l for l in LEGS if current.pads[current.contacts[l]]["terrace"] < world["parameters"]["terraces"]]
    if world.get("guide"):
        leg = min(unfinished, key=lambda l: current.pads[current.contacts[l]]["terrace"])
        destination = current.pads[f"{leg}-{current.pads[current.contacts[leg]]['terrace']+1}"]
        return dict(leg=leg, ballast=None, prep_ms=0,
                    target=pad_position(world, destination, current.ms+world["swing_ms"])[:2],
                    destination=destination["id"], forecast_horizon_ms=delivery_delay_ms+world["swing_ms"])
    terrace = min(current.pads[current.contacts[l]]["terrace"] for l in unfinished)
    candidates = []
    for leg in sorted(unfinished,key=lambda l:current.pads[current.contacts[l]]["terrace"]):
        leg_terrace=current.pads[current.contacts[leg]]["terrace"]
        destination = current.pads[f"{leg}-{leg_terrace+1}"]
        for prep in (700, 1100, 1500):
            end_ms = current.ms + prep + world["swing_ms"]
            landing = pad_position(world, destination, end_ms)[:2]
            feet = current.feet(end_ms)
            other = [p for l, p in feet.items() if l != leg]
            centroid = [sum(p[i] for p in other)/3 for i in range(2)]
            middle = incenter(other)
            future_center = [(sum(p[i] for p in other)+landing[i])/4 for i in range(2)]
            for anchor in (centroid, middle):
                for dx in (0, -.22, .22, .55, .85, 1.1):
                    ballast = [max(-world["ballast_limit"], min(world["ballast_limit"],
                               anchor[i]-future_center[i]+(dx if i == 0 else 0))) for i in range(2)]
                    trial = restore(world, current.snapshot())
                    trial.set_ballast(ballast)
                    trial.advance(current.ms+prep)
                    if trial.failed:
                        continue
                    trial.step(leg, landing)
                    smallest = float("inf")
                    while not trial.failed and not trial.complete and trial.swing:
                        trial.advance(trial.ms+10)
                        smallest = min(smallest, margin(trial.body, trial.polygon())+world["toe_radius"])
                    if trial.failed or trial.contacts[leg] != destination["id"]:
                        continue
                    score = smallest - prep*.000015
                    choice = dict(leg=leg, ballast=ballast, prep_ms=prep,
                                  target=landing, destination=destination["id"],
                                  forecast_horizon_ms=delivery_delay_ms+prep+world["swing_ms"])
                    if smallest > .12:
                        return choice
                    candidates.append((score, choice))
    return max(candidates, key=lambda x:x[0])[1] if candidates else None


def simulation_trace(public, *, stale_ms=0, fixed_program=None):
    """Independent diagnostic; no claim that synthetic events prove HTTP parity."""
    sim = Simulation(public["world"])
    mode = public["control_condition"]["interaction"]
    events, program = [], []
    source = "foot_drag" if mode == "full" else "foot_click"
    def record(kind, **kw):
        events.append(dict(seq=len(events)+1, t_ms=sim.ms, kind=kind, **kw))
    def ballast(target):
        if sim.world.get("guide"):
            return
        if mode == "full":
            record("ballast_start", point=list(sim.ballast), input_source="ballast_drag")
        sim.set_ballast(target)
        record("ballast", target=list(target), input_source="ballast_drag" if mode == "full" else "ballast_click")
        if mode == "full":
            record("release", input_source="ballast_drag")
    sim.launch();record("launch", input_source="launch_button")
    for ordinal in range(4*sim.world["parameters"]["terraces"]):
        choice = copy.deepcopy(fixed_program[ordinal]) if fixed_program else plan(sim.world, sim.snapshot())
        if not choice:
            sim.failed = "Diagnostic planner found no safe next stroke."
            break
        program.append(copy.deepcopy(choice))
        sim.advance(sim.ms+stale_ms)
        if sim.failed:
            break
        ballast(choice["ballast"])
        sim.advance(sim.ms+choice["prep_ms"])
        if sim.failed:
            break
        leg = choice["leg"]
        record("aim_start", leg=leg, point=sim.feet()[leg][:2], input_source=source)
        record("step", leg=leg, target=choice["target"], input_source=source)
        sim.step(leg, choice["target"])
        sim.advance(sim.ms+sim.world["swing_ms"])
        if sim.failed or sim.complete:
            break
        ballast([0., 0.]);sim.advance(sim.ms+450)
    payload = dict(mechanic_id=public["mechanic_id"],task_id=public["task_id"],
        challenge_id=public["challenge_id"], interaction_mode=mode, events=events,
        final_ms=sim.ms, completed=sim.complete and not sim.failed,
        contacts=sim.contacts, landings=[{k:x[k] for k in ("ms","leg","pad")} for x in sim.landings])
    return dict(payload=payload, state=sim.snapshot(), program=program,
                planning="privileged exact state and bounded motor preview; synthetic replay")


def _box(ui, selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def click(ui, selector):
    r = _box(ui, selector)
    ui.send([{"mouse":{"left_click":[r[0]+r[2]/2,r[1]+r[3]/2]}}])


def coordinate(rect, chart, point):
    return [rect[i]+(chart["origin"][i]+point[i]*chart["scale"])*rect[i+2]/chart[("width","height")[i]] for i in range(2)]


def stroke(ui, start, end, mode):
    if mode == "full":
        ui.send([{"mouse":{"move":start,"buttons":{"left_down":True}}},
                 {"mouse":{"move":end}}, {"mouse":{"buttons":{"left_up":True}}}])
    else:
        ui.send([{"mouse":{"left_click":start}}, {"mouse":{"left_click":end}}])


def survey(ui, *, x_max=850):
    """Sweep the visible chart with ordinary unheld pointer moves.

    This raster uses canvas bounds only, with no pad coordinates, identities,
    motion tapes, or discovery-state reads. Discovery is safe before WAKE.
    It also works after WAKE; no action here pauses task time.
    """
    rect = _box(ui, '.cw-map')
    # 35 chart pixels is below the 36.4-pixel survey radius. Each pad center
    # therefore lies inside the footprint of at least one raster sample.
    for row, y in enumerate(range(35, 477, 35)):
        xs = list(range(10, x_max+1, 35))
        for x in (xs if row % 2 == 0 else reversed(xs)):
            ui.send([{"mouse": {"move": [rect[0]+x*rect[2]/860, rect[1]+y*rect[3]/500]}}])


def solve(ui, truth, *, delivery_delay_ms=40, timeout_seconds=150):
    world, mode = truth["world"], truth["control_condition"]["interaction"]
    chart_rect = _box(ui,'.cw-map')
    balance_rect = None if world.get("guide") else _box(ui,'.cw-balance')
    def ballast(target):
        if world.get("guide"):
            return
        current = ui.read('craterWalkerV3Model.sim.ballast')
        start = coordinate(balance_rect,world["balance_chart"],current)
        end = coordinate(balance_rect,world["balance_chart"],target)
        if mode == "full":
            stroke(ui,start,end,mode)
        else:
            ui.send([{"mouse":{"left_click":end}}])
    survey(ui)
    click(ui,'.cw-launch')
    deadline = time.monotonic()+timeout_seconds
    plans = []
    for _ in range(4*world["parameters"]["terraces"]):
        snap = ui.read('craterWalkerV3Model.sim.snapshot()')
        assert not snap['failed'], snap
        if snap['complete']:
            break
        planned_at = time.monotonic()
        choice = plan(world,snap,delivery_delay_ms=delivery_delay_ms)
        assert choice, 'No safe next stroke in bounded forecast'
        # In live mode numerical planning takes time. Rebase the chosen target
        # to the measured current clock immediately before sending each stroke.
        ballast(choice['ballast']);ui.wait(choice['prep_ms']/1000)
        now = ui.read('craterWalkerV3Model.sim.snapshot()')
        assert not now['failed'], now
        leg = choice['leg'];sim = restore(world,now)
        feet = sim.feet()
        target = pad_position(world, sim.pads[choice['destination']],now['ms']+world['swing_ms']+delivery_delay_ms)[:2]
        stroke(ui,coordinate(chart_rect,world['chart'],feet[leg]),coordinate(chart_rect,world['chart'],target),mode)
        # Exercise a real held weight handle through the final landing. All
        # actual inputs still use the supplied UI action interface.
        held_at_goal = not world.get('guide') and mode == 'full' and all(
            other == leg or sim.pads[sim.contacts[other]]['terrace'] == world['parameters']['terraces']
            for other in world['legs'])
        if held_at_goal:
            current = ui.read('craterWalkerV3Model.sim.ballast')
            handle = coordinate(balance_rect,world['balance_chart'],current)
            ui.send([{'mouse':{'move':handle,'buttons':{'left_down':True}}}])
        ui.wait((world['swing_ms']+80)/1000)
        if held_at_goal:
            ui.send([{'mouse':{'buttons':{'left_up':True}}}])
        finished = ui.read('craterWalkerV3Model.sim.snapshot()')
        plans.append(dict(choice, observed_ms=now['ms'], execution_target=target,
                          held_weight_through_final_landing=held_at_goal,
                          planning_wall_ms=(time.monotonic()-planned_at)*1000))
        assert not finished['failed'], finished
        if finished['complete']:
            break
        ballast([0.,0.]);ui.wait(.45)
        assert time.monotonic()<deadline,'oracle deadline exceeded'
    final=ui.read('craterWalkerV3Model.sim.snapshot()')
    assert final['complete'] and not final['failed'],final
    click(ui,'.cw-submit')
    # Certification is an asynchronous HTTP request. A fixed task-time wait
    # can finish before the response (especially with a paused diagnostic
    # clock). Poll without advancing or changing the game until it arrives.
    verdict_deadline = time.monotonic()+10
    outcome = ui.read('craterWalkerV3Model.outcome')
    while outcome is None:
        assert time.monotonic()<verdict_deadline, 'Certification response timed out'
        time.sleep(.03)
        outcome = ui.read('craterWalkerV3Model.outcome')
    assert outcome['passed'], outcome
    return dict(calls=ui.calls,actions=ui.actions,plans=plans,
                outcome=outcome,
                final=ui.read('craterWalkerV3Model.lastPayload'),
                privileged_planning=True)
