"""Independent continuous-time replay. Browser outcome flags are never sufficient."""
from __future__ import annotations

import math

MECHANIC_ID = "collision_chimes_v2"
SIDES = ("top", "right", "bottom", "left")


def _noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def _motion(seed, t, span):
    u = max(0, t) / span
    index, f = math.floor(u), u % 1
    a, b = _noise(seed, index), _noise(seed, index + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def pulse_position(world, note, t):
    p, n = world["parameters"], world["grid_size"] - 1
    x = note["slot"] + p["drift"] * (_motion(note["drift_seed"], t, p["drift_span_ms"])
             - _motion(note["drift_seed"], note["born_ms"], p["drift_span_ms"]))
    x %= 2 * n
    return .5 + (x if x <= n else 2 * n - x)


def _number(x):
    return type(x) in (int, float) and math.isfinite(x)


def replay(world, events, mode, final_t):
    p = world["parameters"]
    half, size = p["pickup_width"] / 2, world["grid_size"]
    positions = {side: size / 2 for side in SIDES}
    targets, grabbed = dict(positions), None
    notes = sorted(world["notes"], key=lambda n: (n["deadline_ms"], n["id"]))
    current, caught, next_note, ended = 0.0, [], 0, None

    def move(time):
        nonlocal current
        travel = p["pickup_speed"] * (time - current) / 1000
        for side in SIDES:
            gap = targets[side] - positions[side]
            positions[side] += max(-travel, min(travel, gap))
        current = time

    def advance(time):
        nonlocal next_note, ended
        escaped = [n for n in notes if n["id"] not in caught and n["deadline_ms"] <= time]
        if escaped:
            note = escaped[0]
            move(note["deadline_ms"])
            ended = "pulse " + str(note["id"] + 1) + " escaped without a strike"
            return
        move(time)

    if not isinstance(events, list) or not events or len(events) > 4000:
        return dict(passed=False, feedback="missing or excessive input transcript")
    previous = 0.0
    for seq, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("sequence") != seq:
            return dict(passed=False, feedback="invalid sequence")
        t = event.get("t_ms")
        if not _number(t) or not previous <= t <= final_t or event.get("input_source") != mode:
            return dict(passed=False, feedback="invalid input time or surface")
        previous = t
        if seq == 1:
            if event.get("kind") != "start" or t != 0:
                return dict(passed=False, feedback="one initial start required")
            continue
        advance(t)
        if ended:
            return dict(passed=False, feedback=ended, caught=caught, positions=positions)
        kind, side = event.get("kind"), event.get("side")
        if kind == "abandon":
            return dict(passed=False, feedback="attempt abandoned", caught=caught)
        if side not in SIDES:
            return dict(passed=False, feedback="invalid wall")
        u = event.get("u")
        if not _number(u) or not 0 <= u <= size:
            return dict(passed=False, feedback="invalid rail coordinate")
        if kind == "strike":
            if grabbed is not None:
                return dict(passed=False, feedback="release the held receiver before striking")
            active = [n for n in notes if n["id"] not in caught and n["side"] == side and n["born_ms"] <= t]
            if not active:
                return dict(passed=False, feedback="no visible pulse to strike")
            impact = active[0]["deadline_ms"]
            group = [n for n in active if n["deadline_ms"] == impact]
            if (impact - t) / p["flight_ms"] * 66 > p["pickup_depth_px"] + 1e-7:
                return dict(passed=False, feedback="pulse centre has not entered the receiver depth")
            if event.get("note_ids") != [n["id"] for n in group] or abs(u - positions[side]) > 1e-7:
                return dict(passed=False, feedback="strike differs from the actual receiver or arrival group")
            if any(abs(positions[side] - pulse_position(world, n, t)) > half + 1e-7 for n in group):
                return dict(passed=False, feedback="strike missed a moving pulse", caught=caught)
            caught.extend(n["id"] for n in group)
            continue
        if kind == "grab" and mode == "full" and grabbed is None:
            if abs(u - positions[side]) > half + 1e-7:
                return dict(passed=False, feedback="grab did not hit the visible resonator")
            grabbed = side
        elif kind == "target" and (mode == "simplified" or grabbed == side):
            targets[side] = max(half, min(size - half, u))
        elif kind == "release" and mode == "full" and grabbed == side:
            grabbed = None
        else:
            return dict(passed=False, feedback="invalid drag/control transition")
    advance(final_t)
    return dict(passed=not ended and len(caught) == len(notes),
                feedback=ended or ("all wall chimes captured" if len(caught) == len(notes) else "chime run incomplete"),
                caught=caught, positions=positions)


def grade(payload, ground_truth, public_state):
    def fail(reason):
        return dict(graded=True, passed=False, score=0, feedback=reason)
    if not all(isinstance(x, dict) for x in (payload, ground_truth, public_state)):
        return fail("malformed submission")
    for key in ("mechanic_id", "task_id", "challenge_id"):
        if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
            return fail("stale or wrong " + key)
    if ground_truth["mechanic_id"] != MECHANIC_ID:
        return fail("wrong mechanic")
    if ground_truth.get("world") != public_state.get("world") or ground_truth.get("control_condition") != public_state.get("control_condition"):
        return fail("public/grading contract mismatch")
    world = ground_truth.get("world")
    if not isinstance(world, dict):
        return fail("invalid world contract")
    condition = ground_truth.get("control_condition")
    if condition is not None:
        if (not isinstance(condition, dict) or type(condition.get("difficulty")) is not int
                or condition["difficulty"] not in range(1, 6)
                or condition.get("real_time") not in ("live", "paused")):
            return fail("invalid control condition")
        if condition.get("difficulty_parameters") != world.get("parameters"):
            return fail("selected parameters differ from active physics")
    mode = (condition or {}).get("interaction", "full")
    if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
        return fail("wrong interaction mode")
    time = payload.get("final_t_ms")
    if not _number(time) or not 0 <= time <= 120000:
        return fail("invalid final task time")
    try:
        replayed = replay(ground_truth["world"], payload.get("events"), mode, time)
    except (TypeError, KeyError, ValueError, OverflowError) as exc:
        return fail("invalid chime transcript: " + str(exc))
    if payload.get("completed") is not True:
        return fail("terminal failure or incomplete run: " + replayed["feedback"])
    if not replayed["passed"]:
        return fail(replayed["feedback"])
    expected = replayed["caught"]
    if payload.get("caught") != expected:
        return fail("visible capture ledger differs from replay")
    return dict(graded=True, passed=True, score=100, feedback="replayed all " + str(len(expected)) + " drifting wall chimes")


def cheat(public_state, ground_truth):
    return {"world": ground_truth.get("world")}
