from __future__ import annotations

import math
from typing import Any


MECHANIC_ID = "three_camera_claw_machine_nonrealtime"


def _round(value: float) -> float:
    return round(float(value), 4)


def _project(camera: dict[str, Any], point: list[float]) -> list[float]:
    matrix = camera["matrix"]
    return [_round(camera["origin"][row] + sum(matrix[row][col] * point[col] for col in range(3))) for row in range(2)]


def _digest(camera: dict[str, Any], claw: list[float], objects: dict[str, dict[str, Any]], captured: str | None) -> str:
    items = [("claw", claw)] + [(key, claw if key == captured else value["center"]) for key, value in sorted(objects.items())]
    return "|".join(f"{key}:{screen[0]:.4f}:{screen[1]:.4f}" for key, point in items for screen in [_project(camera, point)])


def _point_aabb(point: list[float], obstacle: dict[str, Any], radius: float) -> bool:
    return all(abs(point[i] - obstacle["center"][i]) <= obstacle["half"][i] + radius for i in range(3))


def _blocker(start: list[float], end: list[float], contract: dict[str, Any], carried_radius: float) -> str | None:
    distance = math.dist(start, end); steps = max(1, math.ceil(distance / contract["world"]["collision_step"])); bounds = contract["world"]["bounds"]
    for step in range(1, steps + 1):
        t = step / steps; point = [start[i] + (end[i] - start[i]) * t for i in range(3)]
        for i, axis in enumerate(("x", "y", "z")):
            if point[i] - carried_radius < bounds[axis][0] or point[i] + carried_radius > bounds[axis][1]: return "cage-boundary"
        for obstacle in contract["obstacles"]:
            if _point_aabb(point, obstacle, carried_radius): return str(obstacle["id"])
    return None


def _contained(point: list[float], radius: float, box: dict[str, Any]) -> bool:
    return all(abs(point[i] - box["center"][i]) + radius <= box["half"][i] + 1e-6 for i in range(3))


def _frames(tick: int, history: dict[int, tuple[list[float], dict[str, dict[str, Any]], str | None]], cameras: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for view_id, camera in cameras.items():
        visible_tick = max(0, tick - int(camera["delay"])); claw, objects, captured = history[visible_tick]
        result[view_id] = {"tick": visible_tick, "digest": _digest(camera, claw, objects, captured)}
    return result


def _clone_objects(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: {**item, "center": list(item["center"])} for item in items}




# Standalone browser grader: synchronized with realtime_four_motion.py by tests.
def _rt4_noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def _rt4_motion(seed, milliseconds, span=1600):
    u = max(0, milliseconds) / span
    n = math.floor(u)
    f = u - n
    a, b = _rt4_noise(seed, n), _rt4_noise(seed, n + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def _rt4_integral(seed, milliseconds, span=1600):
    u = max(0, milliseconds) / span
    n = math.floor(u)
    f = u - n
    total = sum((_rt4_noise(seed, i) + _rt4_noise(seed, i + 1)) / 2 for i in range(n))
    a, b = _rt4_noise(seed, n), _rt4_noise(seed, n + 1)
    return span * (total + a * f + (b - a) * (f**3 - f**4 / 2))


def _rt4_vector(spec, milliseconds):
    return [a * _rt4_motion(spec['seed'] + i * 7919, milliseconds, spec['span_ms'])
            for i, a in enumerate(spec['amplitude'])]


def moving_center(item, milliseconds):
    return [x + d for x, d in zip(item["center"], _rt4_vector(item["motion"], milliseconds))]


def initial_state(contract):
    return dict(position=list(contract["initial"]["position"]), velocity=[0., 0., 0.],
                held=set(), tick=0, captured=None, gripper="open", delivered=False, collisions=0)


def advance(state, contract, target):
    world = contract["world"]
    while state["tick"] < target:
        wind = _rt4_vector(world["wind"], state["tick"] * world["tick_seconds"] * 1000)
        velocity = state["velocity"]
        for i, axis in enumerate(("x", "y", "z")):
            thrust = int((axis, 1) in state["held"]) - int((axis, -1) in state["held"])
            velocity[i] += thrust * world["acceleration"] + wind[i]
        speed = math.sqrt(sum(v*v for v in velocity))
        if speed > world["max_speed"]:
            velocity = [v * world["max_speed"] / speed for v in velocity]
        start = list(state["position"])
        candidate = [x + v for x, v in zip(start, velocity)]
        radius = world["claw_radius"] if not state["captured"] else max(world["claw_radius"],
                 next(o["radius"] for o in contract["objects"] if o["id"] == state["captured"]))
        if _blocker(start, candidate, contract, radius):
            resolved = list(start)
            for i in range(3):
                trial = list(resolved)
                trial[i] = candidate[i]
                if _blocker(resolved, trial, contract, radius) is None:
                    resolved = trial
                else:
                    velocity[i] = 0
            candidate = resolved
            state["collisions"] += 1
        state["position"] = candidate
        state["velocity"] = [v * world["damping"] for v in velocity]
        state["tick"] += 1


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    for key in ("mechanic_id", "task_id", "challenge_id"):
        if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
            return fail("stale or mismatched " + key)
    if ground_truth["mechanic_id"] != MECHANIC_ID:
        return fail("wrong mechanic")
    for key in ("world", "initial", "objects", "obstacles", "chute", "cameras", "requirements", "control_condition"):
        if ground_truth.get(key) != public_state.get(key):
            return fail("public/private contract mismatch: " + key)
    interaction = (ground_truth.get("control_condition") or {}).get("interaction", "full")
    source = {"full": "keyboard", "simplified": "control_buttons"}.get(interaction)
    if payload.get("interaction_mode") != interaction or source is None:
        return fail("wrong interaction")
    events = payload.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= ground_truth["requirements"]["max_events"]:
        return fail("missing or excessive action trace")
    state = initial_state(ground_truth)
    objects = {o["id"]: o for o in ground_truth["objects"]}
    action_stride = ground_truth["requirements"].get("action_tick_stride")
    if type(action_stride) is not int or action_stride <= 0:
        return fail("missing action-triggered timing contract")
    try:
        for seq, event in enumerate(events, 1):
            tick = event["tick"]
            if (event.get("sequence") != seq or type(tick) is not int or
                tick != state["tick"] + action_stride or
                not tick < ground_truth["requirements"]["max_ticks"] or
                event.get("input_source") != source or state["delivered"]):
                return fail("invalid action-triggered event order, stride or input surface")
            advance(state, ground_truth, tick)
            if event["kind"] == "control":
                axis, direction, held = event.get("axis"), event.get("direction"), event.get("held")
                if axis not in ("x", "y", "z") or direction not in (-1, 1) or type(held) is not bool:
                    return fail("invalid held control")
                key = (axis, direction)
                if held == (key in state["held"]):
                    return fail("duplicate held control")
                if held: state["held"].add(key)
                else: state["held"].remove(key)
            elif event["kind"] == "gripper":
                ms = tick * ground_truth["world"]["tick_seconds"] * 1000
                if state["gripper"] == "open" and event.get("action") == "close":
                    candidates = []
                    for item in objects.values():
                        center = moving_center(item, ms)
                        if (_blocker(center, state["position"], ground_truth, item["radius"]) is None):
                            candidates.append((math.dist(center, state["position"]), item["id"]))
                    candidates.sort()
                    captured = candidates[0][1] if candidates and candidates[0][0] <= ground_truth["world"]["capture_distance"] else None
                    if captured != event.get("captured_id") or captured != ground_truth["target_id"]:
                        return fail("missed grip or wrong cargo ends this attempt")
                    state["captured"], state["gripper"] = captured, "closed"
                elif state["gripper"] == "closed" and event.get("action") == "open":
                    chute = dict(ground_truth["chute"], center=moving_center(ground_truth["chute"], ms))
                    delivered = _contained(state["position"], objects[state["captured"]]["radius"], chute)
                    if not delivered or event.get("delivered") is not True or event.get("released_id") != state["captured"]:
                        return fail("load released outside the moving chute")
                    state.update(captured=None, gripper="open", delivered=True)
                else:
                    return fail("invalid gripper transition")
            else:
                return fail("unknown action; rewinds are unavailable")
        final_tick = payload.get("ticks")
        if type(final_tick) is not int or final_tick != state["tick"]:
            return fail("final tick differs from delivery")
        for key in ("position", "velocity"):
            if len(payload.get(key, [])) != 3 or math.dist(payload[key], state[key]) > .002:
                return fail("final " + key + " disagrees with replay")
        if payload.get("collisions") != state["collisions"] or payload.get("resets") != 0:
            return fail("collision or reset count differs")
        if payload.get("captured_id") != state["captured"] or payload.get("gripper") != state["gripper"]:
            return fail("final gripper differs")
        passed = state["delivered"] and payload.get("delivered") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"continuous claw replay: {state['tick']} ticks; moving cargo {'delivered' if passed else 'pending'}")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return fail("invalid claw transcript: " + str(exc))


def cheat(public_state, ground_truth):
    return {"target_id": ground_truth.get("target_id")}
