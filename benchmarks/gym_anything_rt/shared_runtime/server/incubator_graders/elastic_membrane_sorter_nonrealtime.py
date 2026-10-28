from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "elastic_membrane_sorter_nonrealtime"
ACTION_TICKS = 8


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _close(first: Any, second: Any, tolerance: float = .035) -> bool:
    try:
        return math.isfinite(float(first)) and abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def _force(heights: list[float], acceleration: float) -> tuple[float, float]:
    left = (heights[0] + heights[2]) / 2
    right = (heights[1] + heights[3]) / 2
    top = (heights[0] + heights[1]) / 2
    bottom = (heights[2] + heights[3]) / 2
    return (left - right) * acceleration, (top - bottom) * acceleration


def _same_ball(reported: Any, ball: dict[str, float]) -> bool:
    return isinstance(reported, dict) and all(_close(reported.get(key), ball[key], .05) for key in ("x", "y", "vx", "vy"))


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if not all(isinstance(item,dict) for item in (payload,truth,public)):
        return _fail("malformed membrane submission")
    if any(item.get("mechanic_id") != MECHANIC_ID for item in (payload,truth,public)):
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or public.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    truth_condition = truth.get("control_condition")
    if truth_condition != public.get("control_condition"):
        return _fail("public control condition differs from membrane contract")
    interaction = str((truth_condition or {}).get("interaction") or "")
    expected_input_source = {
        "simplified": "tension_slider",
        "full": "membrane_post_drag",
    }.get(interaction)
    if truth_condition is not None and expected_input_source is None:
        return _fail("membrane interaction condition is invalid")
    events = payload.get("events")
    rounds = public.get("rounds")
    physics = public.get("physics")
    if not isinstance(events, list) or len(events) > 2200:
        return _fail("live membrane transcript malformed")
    try:
        if truth.get("rounds") != rounds or truth.get("physics") != physics:
            raise ValueError("public membrane state differs from replay contract")
        if not 1 <= len(rounds) <= 3 or any(
            not 1 <= len(item.get("checkpoints") or []) <= 3
            for item in rounds
        ):
            raise ValueError("membrane course count is outside supported limits")
        if not (
            0.05 <= float(physics["slope_accel"]) <= 0.14
            and 0.93 <= float(physics["drag"]) <= 0.98
            and 24 <= float(physics["well_radius"]) <= 45
            and 1.8 <= float(physics["capture_speed"]) <= 4.5
            and 24 <= float(physics["checkpoint_radius"]) <= 55
            and 500 <= int(physics["max_ticks"]) <= 800
            and float(physics["boundary_restitution"]) == 0.55
            and int(physics["action_ticks"]) == ACTION_TICKS
        ):
            raise ValueError("membrane physics is outside supported limits")
        if truth_condition is not None:
            parameters = truth_condition.get("difficulty_parameters")
            if not isinstance(parameters, dict):
                raise ValueError("difficulty parameters are malformed")
            expected_parameters = {
                "round_count": len(rounds),
                "checkpoints_per_round": len(rounds[0]["checkpoints"]),
                "slope_accel": float(physics["slope_accel"]),
                "drag": float(physics["drag"]),
                "well_radius": int(physics["well_radius"]),
                "capture_speed": float(physics["capture_speed"]),
                "checkpoint_radius": int(physics["checkpoint_radius"]),
                "max_ticks": int(physics["max_ticks"]),
            }
            for key, value in expected_parameters.items():
                if parameters.get(key) != value:
                    raise ValueError(f"difficulty parameter {key} differs from generated state")
            if any(len(item["checkpoints"]) != expected_parameters["checkpoints_per_round"] for item in rounds):
                raise ValueError("rounds use inconsistent checkpoint counts")
            low = float(parameters.get("initial_height_low"))
            high = float(parameters.get("initial_height_high"))
            if not 0 <= low <= high <= 1 or any(
                any(not low <= float(value) <= high for value in item["post_heights"])
                for item in rounds
            ):
                raise ValueError("initial post heights differ from the difficulty profile")
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"invalid membrane contract: {exc}")

    action_budget_until: int | None = None
    action_ticks = int(physics["action_ticks"])
    round_index = 0
    elapsed_ticks = 0
    captured: list[str] = []

    def fresh() -> dict[str, Any]:
        current = rounds[round_index]
        return {
            "heights": [float(value) for value in current["post_heights"]],
            "ball": {"x": float(current["start"][0]), "y": float(current["start"][1]), "vx": 0.0, "vy": 0.0},
            "tick": 0, "checkpoint": 0, "running": False, "crossings": [], "capture_tick": None, "fall_tick": None,
        }

    motion = fresh()

    def advance(target: int) -> str | None:
        nonlocal action_budget_until
        if target < motion["tick"] or target > int(physics["max_ticks"]):
            return "membrane time moved backward or beyond the visible limit"
        if target > motion["tick"]:
            if action_budget_until is None:
                return "membrane time advanced without a deliberate post correction"
            if target > action_budget_until:
                return "membrane action segment exceeded its finite step limit"
        if not motion["running"] and target != motion["tick"]:
            return "membrane time advanced while the marble was paused"
        if target > motion["tick"]:
            if target == action_budget_until:
                action_budget_until = None
        current = rounds[round_index]
        while motion["tick"] < target:
            if motion["capture_tick"] is not None or motion["fall_tick"] is not None:
                return "events continue after the physical capture moment"
            ax, ay = _force(motion["heights"], float(physics["slope_accel"]))
            ball = motion["ball"]
            ball["vx"] = (ball["vx"] + ax) * float(physics["drag"])
            ball["vy"] = (ball["vy"] + ay) * float(physics["drag"])
            ball["x"] += ball["vx"]
            ball["y"] += ball["vy"]
            motion["tick"] += 1
            if ball["x"] < 28 or ball["x"] > 872 or ball["y"] < 28 or ball["y"] > 452:
                motion["fall_tick"] = motion["tick"]
                continue
            if motion["checkpoint"] < len(current["checkpoints"]):
                point = current["checkpoints"][motion["checkpoint"]]
                if math.hypot(ball["x"] - point[0], ball["y"] - point[1]) <= float(physics["checkpoint_radius"]):
                    index = motion["checkpoint"]
                    motion["checkpoint"] += 1
                    motion["crossings"].append({"index": index, "tick": motion["tick"], "ball": dict(ball)})
            well = current["wells"][current["target_well"]]
            speed = math.hypot(ball["vx"], ball["vy"])
            if motion["checkpoint"] == len(current["checkpoints"]) and math.hypot(ball["x"] - well[0], ball["y"] - well[1]) < float(physics["well_radius"]) and speed <= float(physics["capture_speed"]):
                motion["capture_tick"] = motion["tick"]
        return None

    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        if item.get("type") == "abandon":
            return _fail("membrane cut")
        if round_index >= len(rounds):
            return _fail("events continue after final marble")
        current = rounds[round_index]
        action = item.get("type")
        if item.get("round_id") != current["id"]:
            return _fail("membrane event bound to wrong marble")
        if type(item.get("tick")) is not int:
            return _fail("membrane event missing tick")
        event_tick = item["tick"]
        error = advance(event_tick)
        if error:
            return _fail(error)
        if action == "post":
            post = item.get("post")
            if type(post) is not int or post not in range(4) or not _close(item.get("before"), motion["heights"][post]):
                return _fail("tension change starts from stale post height")
            if expected_input_source is not None and item.get("input_source") != expected_input_source:
                return _fail(f"tension change {sequence} uses the wrong interaction input")
            try:
                after = float(item.get("after"))
            except (TypeError,ValueError):
                return _fail("tension value is invalid")
            if not 0 <= after <= 1:
                return _fail("tension exceeds post travel")
            motion["heights"][post] = after
            action_budget_until = motion["tick"] + action_ticks if motion["running"] else None
        elif action == "release":
            if motion["running"] or not isinstance(item.get("heights"), list) or len(item["heights"]) != 4 or any(not _close(value, motion["heights"][index]) for index, value in enumerate(item["heights"])):
                return _fail("release reports false live membrane")
            motion["running"] = True
            action_budget_until = None
        elif action == "checkpoint":
            if not motion["crossings"]:
                return _fail("inspection ring reported without a physical crossing")
            crossing = motion["crossings"].pop(0)
            if item.get("index") != crossing["index"] or item.get("tick") != crossing["tick"] or not _same_ball(item.get("ball"), crossing["ball"]):
                return _fail("inspection ring ledger disagrees with trajectory replay")
        elif action == "capture":
            ball = motion["ball"]
            speed = math.hypot(ball["vx"], ball["vy"])
            if motion["capture_tick"] != event_tick or motion["crossings"] or item.get("well") != current["target_well"] or item.get("checkpoints") != len(current["checkpoints"]) or not _same_ball(item.get("ball"), ball) or not _close(item.get("speed"), speed):
                return _fail("capture disagrees with ordered-ring damped trajectory")
            captured.append(current["id"])
            elapsed_ticks += motion["tick"]
            round_index += 1
            if round_index < len(rounds):
                motion = fresh()
                action_budget_until = None
        elif action == "stall":
            if event_tick != int(physics["max_ticks"]) or motion["capture_tick"] is not None or item.get("checkpoints") != motion["checkpoint"] or not _same_ball(item.get("ball"), motion["ball"]):
                return _fail("stall report disagrees with the visible simulation limit")
            elapsed_ticks += motion["tick"]
            motion = fresh()
            action_budget_until = None
        elif action == "fall":
            if motion["fall_tick"] != event_tick or not _same_ball(item.get("ball"),motion["ball"]):
                return _fail("fall report disagrees with the open membrane edge")
            elapsed_ticks += motion["tick"]
            motion = fresh()
            action_budget_until = None
        elif action == "reset":
            elapsed_ticks += motion["tick"]
            motion = fresh()
            action_budget_until = None
        else:
            return _fail(f"unknown membrane event {action!r}")
    passed = captured == [item["id"] for item in rounds] and payload.get("completed") is True
    required_rings = sum(len(item["checkpoints"]) for item in rounds)
    return {
        "graded": True,
        "passed": passed,
        "feedback": (
            f"{len(rounds)} fixed-post trajectories cleared {required_rings} ordered rings and slow-capture wells"
            if passed
            else f"captured {len(captured)}/{len(rounds)} marbles"
        ),
    }
