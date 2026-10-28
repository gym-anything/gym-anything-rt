"""Independent replay of kinematic motor rails and their coupled translations.

This module is standalone for the existing Pyodide export. It imports neither
the generator nor browser code and never trusts a submitted completed flag.
"""
from __future__ import annotations

import copy
import math

MECHANIC_ID = "relation_prompt_grounding_v3"


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def drift(body, parameters, milliseconds):
    u = (milliseconds+body["phase_ms"])/parameters["drift_span_ms"]
    k = math.floor(u)
    f = u-k
    h = f*f*(3-2*f)
    return [parameters["drift_amplitude"]*(noise(body["motor_seed"]+i*7919, k)*(1-h)+noise(body["motor_seed"]+i*7919, k+1)*h) for i in range(3)]


def positions(world, commands, t):
    return [[max(24, min(size-24, q[j]+d[j])) for j, size in enumerate(world["world_size"])] for q, d in zip(commands, [drift(b, world["parameters"], t) for b in world["objects"]])]


def shift(world, commands, index, view, delta):
    axes = (0, 1) if view == "front" else (2, 1)
    coupling = world["parameters"]["coupling"]
    lo, hi = world["command_bounds"]
    for i, q in enumerate(commands):
        weight = 1 if i == index else coupling
        for axis, amount in zip(axes, delta):
            q[axis] = max(lo, min(hi, q[axis]+weight*amount))


def hull(points):
    points = sorted(set(tuple(p) for p in points))
    if len(points) <= 2:
        return points
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lower, upper = [], []
    for seq, out in ((points, lower), (reversed(points), upper)):
        for point in seq:
            while len(out) >= 2 and cross(out[-2], out[-1], point) <= 0:
                out.pop()
            out.append(point)
    return lower[:-1]+upper[:-1]


def contains(body, center, view, point):
    axis = 0 if view == "front" else 2
    x, y = point[0]-center[axis], point[1]-center[1]
    if body["shape"] == "sphere":
        return math.hypot(x, y) <= body["radius"]
    polygon = hull([[v[axis], v[1]] for v in body["vertices"]])
    return all((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]) >= -1e-7 for a, b in zip(polygon, polygon[1:]+polygon[:1]))


def fit(world, commands, stage, t):
    return all(abs(a-b) <= world["parameters"]["tolerance"]+1e-7 for p, target in zip(positions(world, commands, t), world["plates"][stage]["targets"]) for a, b in zip(p, target))


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or wrong "+key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("objects", "plates", "parameters", "duration_ms", "world_size", "command_bounds", "control_condition"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public contract mismatch: "+key)
        mode = ground_truth["control_condition"]["interaction"]
        if payload.get("interaction") != mode or mode not in ("full", "simplified"):
            return fail("wrong interaction")
        events = payload.get("events")
        if not isinstance(events, list) or not events:
            return fail("missing primitive transcript")
        commands = [copy.copy(b["initial"]) for b in ground_truth["objects"]]
        stage, active, hold, previous = 0, False, None, 0
        terminal = ""
        end_time = payload.get("final_t_ms")
        if type(end_time) not in (float, int) or not math.isfinite(end_time) or end_time < 0 or end_time > ground_truth["duration_ms"]+1000:
            return fail("invalid final task time")
        for number, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("sequence") != number or terminal:
                return fail("invalid sequence or input after terminal outcome")
            t, kind = event.get("t_ms"), event.get("kind")
            if type(t) not in (float, int) or not math.isfinite(t) or not previous <= t <= end_time:
                return fail("invalid event task time")
            if active and t >= ground_truth["duration_ms"] and kind != "timeout":
                return fail("expired inspection")
            previous = t
            if kind == "start" and not active and number == 1:
                active = True
                if t != 0:
                    return fail("motor run must start at zero")
                continue
            if not active:
                return fail("input outside active inspection")
            if kind in ("select", "drag_start"):
                index, view, point = event.get("body"), event.get("view"), event.get("point")
                if type(index) is not int or not 0 <= index < len(commands) or view not in ("front", "side") or hold is not None:
                    return fail("invalid or overlapping selection")
                if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
                    return fail("invalid pointer geometry")
                pos = positions(ground_truth, commands, t)
                # Rendering and hit testing use the same projected mesh and
                # ascending depth order. The frontmost containing body owns it.
                order = sorted(range(len(commands)), key=lambda i: pos[i][2 if view == "front" else 0])
                hits = [i for i in order if contains(ground_truth["objects"][i], pos[i], view, point)]
                if not hits or hits[-1] != index:
                    return fail("pointer missed visible body")
                if event.get("input_source") != ("direct_drag" if kind == "drag_start" else "proxy_click") or kind != ("drag_start" if mode == "full" else "select"):
                    return fail("wrong selection surface")
                hold = dict(body=index, view=view, point=point)
            elif kind in ("drag_move", "drag_end", "place"):
                if not hold or event.get("body") != hold["body"] or event.get("view") != hold["view"]:
                    return fail("unpaired manipulation")
                point = event.get("point")
                if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in point) or not (0 <= point[0] <= 400 and 0 <= point[1] <= 340):
                    return fail("placement leaves projection field")
                if event.get("input_source") != ("direct_drag" if mode == "full" else "proxy_click") or mode == "simplified" and kind != "place" or mode == "full" and kind == "place":
                    return fail("wrong translation surface")
                origin = hold["point"]
                shift(ground_truth, commands, hold["body"], hold["view"], [a-b for a, b in zip(point, origin)])
                hold["point"] = point
                if kind in ("drag_end", "place"):
                    hold = None
            elif kind == "cancel":
                if hold is None:
                    return fail("cancel without selection")
                hold = None
            elif kind == "expose":
                if hold is not None or stage >= len(ground_truth["plates"]) or not fit(ground_truth, commands, stage, t):
                    terminal = "fail"
                else:
                    stage += 1
            elif kind == "certify":
                terminal = "pass" if stage == len(ground_truth["plates"]) and hold is None else "fail"
            elif kind == "timeout":
                if t < ground_truth["duration_ms"]:
                    return fail("premature timeout")
                terminal = "fail"
            else:
                return fail("unknown action")
        if payload.get("plates") != stage or payload.get("terminal") != terminal:
            return fail("reported outcome differs from geometric replay")
        if len(payload.get("commands", [])) != len(commands) or any(len(q) != 3 for q in payload["commands"]):
            return fail("missing final carriage commands")
        if any(type(a) not in (int, float) or not math.isfinite(a) or abs(a-b) > 0.001 for q, r in zip(payload["commands"], commands) for a, b in zip(q, r)):
            return fail("tampered carriage commands")
        passed = terminal == "pass"
        return dict(graded=True, passed=passed, score=100 if passed else 0, feedback=f"dual-projection motor replay: {stage}/{len(ground_truth['plates'])} plates; {terminal or 'incomplete'}")
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        return fail("invalid rig transcript: "+str(exc))


def cheat(public_state, ground_truth):
    return dict(plates=ground_truth.get("plates"), planning="private oracle planning only")
