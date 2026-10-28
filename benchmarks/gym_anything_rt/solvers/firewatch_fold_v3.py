"""Feedback construction oracle. Privileged read-only planning, public inputs.

The supplied transport owns action delivery. Native evidence uses only the
frozen downstream HTTP gateway. A headless Playwright transport is explicitly
an implementation test and does not prove downstream action-space parity.
"""
from __future__ import annotations

import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders import firewatch_fold_v3 as physics


def signed_distance(target, origin, world):
    half = world["width"]
    return (target - origin + half) % (2 * half) - half


def intercept_possible(world, state, direction=None, x=None, *, age_ms=0, exact=False, launch_delay_ms=100):
    """Predict from current drawn position/velocity, or disclosed exact currents.

    The default feature predictor never uses a future wind value. Future state
    readings used by an exact oracle must be identified as privileged evidence.
    """
    direction = state["facing"] if direction is None else direction
    origin = state["player"][1] + .5 if x is None else x + .5
    candidates = [f for f in world["fires"] if f["floor"] == state["player"][0] and f["id"] not in state["cleared"]]
    observed = max(0, state["tick"] - age_ms / world["tick_ms"])
    predictions = []
    # Require the same first-hit color throughout a small delivery interval.
    # This is an oracle safety margin, not a changed game tolerance or auto-aim.
    for delay in (0, launch_delay_ms / 2, launch_delay_ms):
        first = None
        closest = math.inf
        for step in range(1, math.ceil(world["pulse_reach"] / world["pulse_speed"] * 1000 / world["tick_ms"]) + 1):
            seconds = step * world["tick_ms"] / 1000
            water = origin + direction * min(world["pulse_reach"], world["pulse_speed"] * seconds)
            hits = []
            for fire in candidates:
                if exact:
                    future = physics.fire_x(fire, state["tick"] + delay / world["tick_ms"] + step, world)
                else:
                    future = physics.fire_x(fire, observed, world) + physics.fire_velocity(fire, observed, world) * (seconds + (age_ms + delay) / 1000)
                separation = physics.distance(water, future, world)
                if separation <= fire["radius"] + world["pulse_radius"]:
                    hits.append((separation, fire["id"], fire["color"], fire["radius"]))
                if first and fire["id"] == first[1]:
                    closest = min(closest, separation)
            if hits and first is None:
                hits.sort()
                first = hits[0]
                closest = first[0]
        if first is None or closest > first[3] + world["pulse_radius"] - .08:
            return None
        predictions.append(first)
    if len({hit[2] for hit in predictions}) == 1:
        return {"color":predictions[0][2]}
    return None


def choose(world, state, *, age_ms=0, exact=False):
    if state["failure"] or state["rescued"]:
        return "terminal", None
    # Survey the actual concealed plan through the existing eye control.
    # The eye alternates faces; it changes no movement or shot eligibility.
    if len(state["surveyed_faces"]) < 2:
        return "inspect", None
    if not state["started"]:
        return "start", None
    if state["pulse"]:
        return "wait", None
    floor, x = state["player"]
    remaining = [f for f in world["fires"] if f["floor"] == floor and f["id"] not in state["cleared"]]
    if remaining:
        intercept = intercept_possible(world, state, age_ms=age_ms, exact=exact)
        if intercept:
            if state["selected"] != intercept["color"]:
                return "select", intercept["color"]
            return "fire", None
        for direction in (-1, 1):
            dest = (x + direction) % (2 * world["width"])
            if intercept_possible(world, state, direction, dest, age_ms=age_ms, exact=exact):
                return "move", "LEFT" if direction == -1 else "RIGHT"
        observed = max(0, state["tick"] - age_ms / world["tick_ms"])
        targets = [physics.fire_x(f, observed, world) + physics.fire_velocity(f, observed, world) * (age_ms / 1000 + .3) for f in remaining]
        delta = min((signed_distance(t, x + .5, world) for t in targets), key=abs)
        return "move", "RIGHT" if delta >= 0 else "LEFT"
    if floor == world["floors"] - 1:
        if state["player"] == world["resident"]:
            return "certify", None
        target = world["resident"][1]
    else:
        if x in world["ladders"][floor]:
            return "move", "UP"
        target = min(world["ladders"][floor], key=lambda n: abs(signed_distance(n, x, world)))
    return "move", "RIGHT" if signed_distance(target, x, world) >= 0 else "LEFT"


def _button(ui, selector):
    point = ui.read(f'(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }})()')
    ui.send([{"mouse": {"left_click": point}}])


def issue(ui, mode, kind, direction=None):
    if kind in ("start", "inspect", "certify"):
        _button(ui, {"start": "#fw2-start", "inspect": "#fw2-eye", "certify": "#fw2-certify"}[kind])
    elif mode == "full":
        key = str(direction+1) if kind == "select" else "Shift" if kind == "fire" else {"LEFT": "Left", "RIGHT": "Right", "UP": "Up", "DOWN": "Down"}[direction]
        ui.send([{"keyboard": {"keys": [key]}}])
    else:
        _button(ui, f'[data-color="{direction}"]' if kind=="select" else "#fw2-fire" if kind == "fire" else f'[data-dir="{direction}"]')


def _wait_after_action(ui, seconds):
    """Let transports account for the observation already returned by input.

    A native paused input returns a full observation window. The oracle can
    use that observation immediately; it need not request another empty window
    merely to implement its short post-input pacing wait.
    """
    getattr(ui, "wait_after_action", ui.wait)(seconds)


def solve(ui, truth, *, exact=False, max_calls=160):
    world, mode = truth["world"], truth["interaction"]
    deadline = time.monotonic() + 170
    calls = 0
    issue(ui, mode, "inspect"); calls += 1
    while time.monotonic() < deadline and calls < max_calls:
        state = ui.read("JSON.parse(JSON.stringify(firewatchFoldV3Model.sim))")
        if state["failure"]:
            raise AssertionError(state["failure"])
        kind, direction = choose(world, state, exact=exact)
        if kind == "wait":
            ui.wait(.12)
            continue
        if kind == "terminal":
            raise AssertionError("unexpected terminal state")
        if kind in ("move", "fire") and state["tick"] - state["last_move"] < world["move_cooldown_ticks"]:
            ui.wait(.1)
            continue
        issue(ui, mode, kind, direction); calls += 1
        if kind == "certify":
            _wait_after_action(ui, .2)
            return dict(calls=calls, planner="privileged exact currents" if exact else "privileged current position/velocity features; constant-velocity prediction")
        _wait_after_action(ui, .13)
    raise AssertionError(f"oracle exceeded its finite 160-call/170-second budget ({calls})")


def simulate(world, *, seed_policy="feedback", interval_ms=140, age_ms=0, exact=False):
    """Counterfactual diagnostics only. No simulation is claimed as UI evidence."""
    state = physics.initial(world)
    events = []
    step = math.ceil(interval_ms / world["tick_ms"])
    while state["tick"] < world["max_ticks"] and not state["failure"]:
        if seed_policy == "parked":
            kind, direction = ("start", None) if not state["started"] else ("wait", None)
        else:
            kind, direction = choose(world, state, age_ms=age_ms, exact=exact)
        if kind == "certify":
            state["rescued"] = True
            break
        if kind not in ("wait", "terminal"):
            outcome = physics.apply(state, world, kind, direction)
            event = dict(sequence=len(events)+1,tick=state["tick"],kind=kind,input_source="button" if kind in ("start","inspect") else "keyboard",outcome=outcome)
            if kind in ("move", "select"):
                event["direction"] = direction
            events.append(event)
        physics.advance(state, world, min(world["max_ticks"], state["tick"] + step))
    return state, events
