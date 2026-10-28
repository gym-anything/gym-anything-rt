from __future__ import annotations

import math


MECHANIC_ID = "parallel_grillmaster_nonrealtime"


def _valid_point(value):
    return isinstance(value, list) and len(value) == 2 and all(
        isinstance(item, (int, float)) and math.isfinite(item) for item in value
    )


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)

    for key in ("mechanic_id", "task_id", "challenge_id"):
        if (not ground_truth.get(key) or payload.get(key) != ground_truth[key]
                or public_state.get(key) != ground_truth[key]):
            return fail("stale or wrong " + key)
    if ground_truth["mechanic_id"] != MECHANIC_ID:
        return fail("wrong mechanic")
    for key in ("foods", "parallel_count", "parallel_window_ms", "control_condition"):
        if ground_truth.get(key) != public_state.get(key):
            return fail("public contract mismatch: " + key)

    mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
    if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
        return fail("wrong interaction")
    foods = {food["id"]: food for food in ground_truth["foods"]}
    events = payload.get("events")
    if not isinstance(events, list) or len(events) != 2 * len(foods):
        return fail("every food requires one start and one serve")

    starts, served, previous = {}, set(), -1
    try:
        for index, event in enumerate(events, 1):
            t = event["t_ms"]
            if (type(t) not in (int, float) or not math.isfinite(t) or not previous <= t <= 600000
                    or event.get("sequence") != index or event.get("input_source") != mode
                    or event.get("food_id") not in foods):
                return fail("invalid action sequence, time or input")
            previous = t
            if starts and len(starts) < ground_truth["parallel_count"]:
                if t - min(start["t_ms"] for start in starts.values()) > ground_truth["parallel_window_ms"]:
                    return fail("concurrent start window missed")

            food_id = event["food_id"]
            if mode == "full" and not (_valid_point(event.get("start_point")) and _valid_point(event.get("end_point"))
                                        and math.dist(event["start_point"], event["end_point"]) >= 5):
                return fail("food transfer requires a drag")
            if event["kind"] == "start" and food_id not in starts:
                starts[food_id] = event
            elif event["kind"] == "serve" and food_id in starts and food_id not in served:
                food = foods[food_id]
                cook_ms = event.get("cook_ms")
                if (event.get("ready") is not True or type(cook_ms) not in (int, float)
                        or not math.isfinite(cook_ms)
                        or abs(cook_ms - food["target_ms"]) > food["tolerance_ms"]):
                    return fail("food served outside golden window")
                served.add(food_id)
            else:
                return fail("reset, duplicate or invalid food transfer")

        earliest = sorted(start["t_ms"] for start in starts.values())[:ground_truth["parallel_count"]]
        if len(earliest) > 1 and earliest[-1] - earliest[0] > ground_truth["parallel_window_ms"]:
            return fail("concurrent start window missed")
        if served != set(foods) or payload.get("completed") is not True:
            return fail("dinner rush incomplete")
        return dict(graded=True, passed=True, score=100,
                    feedback=f"action-triggered replay: all {len(foods)} foods served")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return fail("invalid grill transcript: " + str(exc))


def cheat(public_state, ground_truth):
    return {"foods": ground_truth.get("foods", [])}
