from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "clockwork_clutch_safe"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _close(first: Any, second: Any, tolerance: float = .025) -> bool:
    try:
        return math.isfinite(float(first)) and abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def _error(angle: float) -> float:
    return abs((angle + 180) % 360 - 180)


def _phase_close(first: Any, second: Any, tolerance: float = .025) -> bool:
    try:
        return math.isfinite(float(first)) and _error(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if any(source.get("mechanic_id") != MECHANIC_ID for source in (payload, truth, public)):
        return _fail("mechanic mismatch")
    if (
        not truth.get("task_id")
        or payload.get("task_id") != truth.get("task_id")
        or public.get("task_id") != truth.get("task_id")
        or not truth.get("challenge_id")
        or payload.get("challenge_id") != truth.get("challenge_id")
        or public.get("challenge_id") != truth.get("challenge_id")
    ):
        return _fail("stale task or challenge")
    truth_condition = truth.get("control_condition")
    if truth_condition != public.get("control_condition"):
        return _fail("public interaction condition differs from clockwork contract")
    interaction = str((truth_condition or {}).get("interaction") or "")
    expected_input_source = {"simplified": "clutch_button", "full": "clutch_lever_drag"}.get(interaction)
    if truth_condition is not None and expected_input_source is None:
        return _fail("clockwork interaction condition is invalid")
    try:
        physics = dict(truth["physics"])
        if public.get("physics") != truth["physics"]:
            raise ValueError("public drive physics differs from the replay contract")
        ratios = list(truth["ratios"])
        initial_angles = list(truth["initial_angles"])
        shafts = [dict(item) for item in public["shafts"]]
        release_schedule = [dict(item) for item in truth["release_schedule"]]
        if not 1 <= len(shafts) <= 4 or len(ratios) != len(shafts) or len(initial_angles) != len(shafts):
            raise ValueError("shaft bank has an invalid size")
        expected_shafts = [
            {"id": f"seal-{index + 1}", "ratio": ratios[index], "angle_deg": initial_angles[index], "engaged": True}
            for index in range(len(shafts))
        ]
        if shafts != expected_shafts:
            raise ValueError("public shafts differ from the generated replay contract")
        if (
            len(release_schedule) != len(shafts)
            or {item.get("shaft") for item in release_schedule} != set(range(len(shafts)))
            or any(
                isinstance(item.get("tick"), bool)
                or not isinstance(item.get("tick"), int)
                for item in release_schedule
            )
            or any(
                first["tick"] >= second["tick"]
                for first, second in zip(release_schedule, release_schedule[1:])
            )
        ):
            raise ValueError("release schedule is malformed")
        tick_ms = int(physics["tick_ms"])
        drive_deg_per_tick = float(physics["drive_deg_per_tick"])
        load_numerator = int(physics["load_numerator"])
        phase_tolerance = float(physics["phase_tolerance_deg"])
        max_ticks = int(physics["max_ticks"])
        show_angle = physics.get("show_angle_readout", True)
        show_speed = physics.get("show_speed_readout", True)
        reengagement_allowed = physics.get("reengagement_allowed", True)
        if (
            not 50 <= tick_ms <= 200
            or not .5 <= drive_deg_per_tick <= 3.0
            or load_numerator != len(shafts)
            or not 3.0 <= phase_tolerance <= 40.0
            or not release_schedule[-1]["tick"] < max_ticks <= 400
            or any(not isinstance(value, bool) for value in (show_angle, show_speed, reengagement_allowed))
        ):
            raise ValueError("drive physics is outside supported limits")
        if truth_condition is not None:
            parameters = truth_condition.get("difficulty_parameters")
            if not isinstance(parameters, dict):
                raise ValueError("difficulty parameters are malformed")
            actual_parameters = {
                "shaft_count": len(shafts),
                "tick_ms": tick_ms,
                "drive_deg_per_tick": drive_deg_per_tick,
                "load_numerator": load_numerator,
                "phase_tolerance_deg": phase_tolerance,
                "max_ticks": max_ticks,
                "show_angle_readout": show_angle,
                "show_speed_readout": show_speed,
                "reengagement_allowed": reengagement_allowed,
            }
            for key, value in actual_parameters.items():
                if parameters.get(key) != value:
                    raise ValueError(f"difficulty parameter {key} differs from generated physics")
            release_ranges = parameters.get("release_tick_ranges")
            if (
                not isinstance(release_ranges, list)
                or len(release_ranges) != len(release_schedule)
                or any(
                    not isinstance(window, list)
                    or len(window) != 2
                    or not int(window[0]) <= int(item["tick"]) <= int(window[1])
                    for window, item in zip(release_ranges, release_schedule)
                )
            ):
                raise ValueError("difficulty release windows differ from the generated schedule")
            ratio_profiles = {
                "single": ((1.0,),),
                "paired": ((1.0, -1.25), (1.25, -1.0), (1.5, -1.25)),
                "legacy_four": (
                    (1.0, -1.25, 1.5, -1.75),
                    (1.25, -1.0, 1.75, -1.5),
                    (1.5, -1.75, 1.0, -1.25),
                ),
                "wide_four": (
                    (1.25, -1.5, 1.75, -2.0),
                    (1.5, -1.25, 2.0, -1.75),
                    (1.75, -2.0, 1.25, -1.5),
                ),
            }
            if tuple(ratios) not in ratio_profiles.get(str(parameters.get("ratio_profile")), ()):
                raise ValueError("difficulty ratio profile differs from the generated shafts")
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"invalid clockwork contract: {exc}")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 1000:
        return _fail("load-coupled clockwork transcript malformed")
    last_tick = 0
    running = False
    unlock = None
    terminal = False

    def advance(target: int) -> bool:
        nonlocal last_tick
        if target < last_tick or target > int(physics["max_ticks"]):
            return False
        delta = target - last_tick
        if delta and not running:
            return False
        active = sum(bool(shaft["engaged"]) for shaft in shafts)
        factor = float(physics["load_numerator"]) / active if active else 0.0
        for shaft in shafts:
            if shaft["engaged"]:
                shaft["angle_deg"] = (float(shaft["angle_deg"]) + delta * float(shaft["ratio"]) * float(physics["drive_deg_per_tick"]) * factor) % 360
        last_tick = target
        return True

    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        if terminal:
            return _fail("clockwork transcript continues after the safe verdict")
        action = item.get("type")
        if action == "abandon":
            return _fail("gear train broken")
        if action not in {"drive", "clutch", "unlock"}:
            return _fail(f"unknown clockwork event {action!r}")
        try:
            tick = int(item["tick"])
        except (KeyError, TypeError, ValueError):
            return _fail("clockwork event missing tick")
        if not advance(tick):
            return _fail("clockwork time advanced while braked or moved backward")
        if action == "drive":
            if not isinstance(item.get("running"), bool):
                return _fail("drive transition is not boolean")
            requested = item["running"]
            if requested == running:
                return _fail("duplicate drive transition")
            if not requested:
                reported = item.get("angles")
                if not isinstance(reported, list) or len(reported) != len(shafts) or any(not _phase_close(value, shafts[index]["angle_deg"]) for index, value in enumerate(reported)):
                    return _fail("brake reports false shaft phases")
            running = requested
        elif action == "clutch":
            index = item.get("shaft")
            if isinstance(index, bool) or not isinstance(index, int) or index not in range(len(shafts)) or item.get("before") is not bool(shafts[index]["engaged"]):
                return _fail("clutch starts from stale active set")
            if expected_input_source is not None and item.get("input_source") != expected_input_source:
                return _fail(f"clutch event {sequence} uses the wrong interaction input")
            if not shafts[index]["engaged"] and not reengagement_allowed:
                return _fail("released clutch cannot be re-engaged in this difficulty profile")
            shafts[index]["engaged"] = not shafts[index]["engaged"]
            if item.get("after") is not bool(shafts[index]["engaged"]) or not _phase_close(item.get("angle_deg"), shafts[index]["angle_deg"]) or item.get("active_after") != sum(bool(shaft["engaged"]) for shaft in shafts):
                return _fail("clutch reports false phase or load redistribution set")
        else:
            if running:
                return _fail("safe tried while master drive still running")
            unlock = item
            terminal = True
    errors = [_error(float(shaft["angle_deg"])) for shaft in shafts]
    accepted = all(not shaft["engaged"] for shaft in shafts) and all(value <= phase_tolerance for value in errors)
    reported_angles = unlock.get("angles") if isinstance(unlock, dict) else None
    if not isinstance(unlock, dict) or not isinstance(reported_angles, list) or len(reported_angles) != len(shafts) or any(not _phase_close(value, shafts[index]["angle_deg"]) for index, value in enumerate(reported_angles)) or unlock.get("engaged") != [bool(shaft["engaged"]) for shaft in shafts] or bool(unlock.get("accepted")) != accepted:
        return _fail("safe verdict disagrees with load-coupled replay")
    passed = accepted and payload.get("completed") is True
    return {
        "graded": True,
        "passed": passed,
        "feedback": (
            f"{len(shafts)} {'phase' if len(shafts) == 1 else 'phases'} accepted under active-set load redistribution"
            if passed
            else f"phase errors {' / '.join(f'{value:.1f}' for value in errors)}"
        ),
    }
