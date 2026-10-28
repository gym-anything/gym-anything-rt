from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "marionette_checkpoint"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _points(lengths: list[float]) -> dict[str, tuple[float, float]]:
    left_hand, right_hand, left_foot, right_foot = lengths
    return {
        "left_hand": (330 - (left_hand - 50) * 2 + (left_foot - 50) * .35, 220 + (left_hand - 50) * 2.05),
        "right_hand": (570 + (right_hand - 50) * 2 - (right_foot - 50) * .35, 220 + (right_hand - 50) * 2.05),
        "left_foot": (410 - (left_foot - 50) * 1.25 + (left_hand - 50) * .28, 365 + (left_foot - 50) * 1.55),
        "right_foot": (490 + (right_foot - 50) * 1.25 - (right_hand - 50) * .28, 365 + (right_foot - 50) * 1.55),
    }


def _target_lengths(pose: dict[str, Any], tick: int) -> list[float]:
    return [
        float(base) + float(pose["amplitudes"][index]) * math.sin(tick * float(pose["angular_rate"]) + float(pose["phases"][index]))
        for index, base in enumerate(pose["base_lengths"])
    ]


def _inside(lengths: list[float], pose: dict[str, Any], tick: int, radius: float, active_indices: list[int]) -> bool:
    points = _points(lengths)
    targets = _points(_target_lengths(pose, tick))
    allowance = radius - 7
    names = ("left_hand", "right_hand", "left_foot", "right_foot")
    return all(math.dist(points[names[index]], targets[names[index]]) <= allowance for index in active_indices)


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    events = payload.get("events")
    poses = public["poses"]
    active_indices = [int(value) for value in public.get("active_string_indices", (0, 1, 2, 3))]
    condition = public.get("control_condition") or truth.get("control_condition") or {}
    expected_source = {"simplified": "string_slider", "full": "string_drag"}.get(condition.get("interaction"))
    if not isinstance(events, list) or len(events) > 3600:
        return _fail("moving marionette transcript malformed")
    pose_index = 0
    lengths = [float(value) for value in public["initial_lengths"]]
    tick = progress = 0
    cleared: list[str] = []
    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        if item.get("type") == "abandon":
            return _fail("strings cut")
        if pose_index >= len(poses):
            return _fail("events continue after final moving act")
        pose = poses[pose_index]
        if item.get("pose_id") != pose["id"]:
            return _fail("string event bound to wrong moving act")
        action = item.get("type")
        if action == "string":
            index = item.get("string")
            if index not in active_indices or item.get("tick") != tick or float(item.get("before")) != lengths[index]:
                return _fail("string control starts from stale rack or time")
            if expected_source and item.get("input_source") != expected_source:
                return _fail(f"string control {sequence} uses the wrong interaction input")
            after = float(item.get("after"))
            if not float(public["length_range"][0]) <= after <= float(public["length_range"][1]):
                return _fail("string exceeds pulley travel")
            lengths[index] = after
            if item.get("lengths") != lengths:
                return _fail("string event reports false coupled rack")
        elif action == "reset":
            if item.get("tick") != tick or item.get("before") != lengths or item.get("after") != public["initial_lengths"] or item.get("progress_after") != 0:
                return _fail("rack reset ledger is false")
            lengths = [float(value) for value in public["initial_lengths"]]
            progress = 0
        elif action == "track_sample":
            if item.get("tick") != tick + 1 or item.get("lengths") != lengths:
                return _fail("tracking sample skipped time or reports false strings")
            tick += 1
            inside = _inside(lengths, pose, tick, float(public["ring_radius"]), active_indices)
            progress = progress + 1 if inside else max(0, progress - int(pose["miss_decay_ticks"]))
            if bool(item.get("inside")) != inside or item.get("progress_after") != progress:
                return _fail("tracking progress disagrees with moving coupled geometry")
        elif action == "act_clear":
            if item.get("tick") != tick or item.get("lengths") != lengths or item.get("progress") != progress or progress < int(pose["tracking_ticks"]):
                return _fail("moving act cleared without sufficient replayed tracking")
            cleared.append(pose["id"])
            pose_index += 1
            tick = progress = 0
        else:
            return _fail(f"unknown marionette event {action!r}")
    passed = cleared == [pose["id"] for pose in poses] and payload.get("completed") is True
    act_noun = "act" if len(poses) == 1 else "acts"
    if passed:
        feedback = f"{len(poses)} moving {act_noun} sustained coupled {len(active_indices)}-limb tracking with visible miss decay"
    else:
        feedback = f"cleared {len(cleared)}/{len(poses)} {act_noun}"
    return {"graded": True, "passed": passed, "feedback": feedback}
