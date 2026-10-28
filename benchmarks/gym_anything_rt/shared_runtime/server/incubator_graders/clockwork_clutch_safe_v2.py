from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "clockwork_clutch_safe_v2"

CLUTCH_RATIO_PROFILES = {
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


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _error(angle: float) -> float:
    return abs((angle + 180) % 360 - 180)


def _phase_close(first: Any, second: Any, tolerance: float = .025) -> bool:
    try:
        return math.isfinite(float(first)) and _error(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def _wobble_at(tick: int, anchors: list[dict[str, Any]]) -> float:
    if not anchors:
        return 1.0
    if tick <= anchors[0]["tick"]:
        return float(anchors[0]["mult"])
    for first, second in zip(anchors, anchors[1:]):
        if first["tick"] <= tick <= second["tick"]:
            span = second["tick"] - first["tick"]
            t = 0.0 if span <= 0 else (tick - first["tick"]) / span
            eased = t * t * t * (t * (t * 6 - 15) + 10)
            return float(first["mult"]) + (float(second["mult"]) - float(first["mult"])) * eased
    return float(anchors[-1]["mult"])


def _valid_anchors(anchors: Any, *, max_ticks: int, min_mult: float, max_mult: float, segment_min: int, segment_max: int) -> bool:
    if not isinstance(anchors, list) or len(anchors) < 2 or len(anchors) > 200:
        return False
    previous_tick = None
    for index, item in enumerate(anchors):
        if not isinstance(item, dict):
            return False
        tick = item.get("tick")
        mult = item.get("mult")
        if isinstance(tick, bool) or not isinstance(tick, int) or not isinstance(mult, (int, float)) or isinstance(mult, bool):
            return False
        if index == 0:
            if tick != 0 or abs(float(mult) - 1.0) > 1e-9:
                return False
        else:
            gap = tick - previous_tick
            if gap < segment_min or gap > segment_max:
                return False
            if not min_mult - 1e-6 <= float(mult) <= max_mult + 1e-6:
                return False
        previous_tick = tick
    if anchors[-1]["tick"] < max_ticks:
        return False
    return True


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
        if physics.get("drive_can_stop") is not False:
            raise ValueError("drive must run continuously once started")
        show_angle = physics.get("show_angle_readout", True)
        show_speed = physics.get("show_speed_readout", True)
        reengagement_allowed = physics.get("reengagement_allowed", True)
        wobble_min_mult = float(physics["wobble_min_mult"])
        wobble_max_mult = float(physics["wobble_max_mult"])
        wobble_segment_min_ticks = int(physics["wobble_segment_min_ticks"])
        wobble_segment_max_ticks = int(physics["wobble_segment_max_ticks"])
        anchors = physics["wobble_anchors"]
        if (
            not 50 <= tick_ms <= 200
            or not .5 <= drive_deg_per_tick <= 3.0
            or load_numerator != len(shafts)
            or not 3.0 <= phase_tolerance <= 40.0
            or not release_schedule[-1]["tick"] < max_ticks <= 400
            or any(not isinstance(value, bool) for value in (show_angle, show_speed, reengagement_allowed))
        ):
            raise ValueError("drive physics is outside supported limits")
        if not 0.1 <= wobble_min_mult < 1.0 <= wobble_max_mult <= 2.2:
            raise ValueError("wobble multiplier bounds are outside supported limits")
        if not 2 <= wobble_segment_min_ticks <= wobble_segment_max_ticks <= 60:
            raise ValueError("wobble segment length is outside supported limits")
        if not _valid_anchors(
            anchors,
            max_ticks=max_ticks,
            min_mult=wobble_min_mult,
            max_mult=wobble_max_mult,
            segment_min=wobble_segment_min_ticks,
            segment_max=wobble_segment_max_ticks,
        ):
            raise ValueError("wobble anchor curve is malformed or forged")
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
                "wobble_min_mult": wobble_min_mult,
                "wobble_max_mult": wobble_max_mult,
                "wobble_segment_min_ticks": wobble_segment_min_ticks,
                "wobble_segment_max_ticks": wobble_segment_max_ticks,
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
            ratio_profiles = CLUTCH_RATIO_PROFILES
            if tuple(ratios) not in ratio_profiles.get(str(parameters.get("ratio_profile")), ()):
                raise ValueError("difficulty ratio profile differs from the generated shafts")
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"invalid clockwork contract: {exc}")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 1000:
        return _fail("wobble-drive clockwork transcript malformed")
    last_tick = 0
    running = False
    unlock = None
    terminal = False
    refused_attempts = 0

    def advance(target: int) -> bool:
        nonlocal last_tick
        if target < last_tick or target > int(physics["max_ticks"]):
            return False
        delta = target - last_tick
        if delta and not running:
            return False
        active = sum(bool(shaft["engaged"]) for shaft in shafts)
        factor = float(physics["load_numerator"]) / active if active else 0.0
        for tick in range(last_tick + 1, target + 1):
            wobble = _wobble_at(tick, anchors)
            for shaft in shafts:
                if shaft["engaged"]:
                    shaft["angle_deg"] = (
                        float(shaft["angle_deg"])
                        + float(shaft["ratio"]) * float(physics["drive_deg_per_tick"]) * wobble * factor
                    ) % 360
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
        if action not in {"drive", "clutch", "unlock", "timeout"}:
            return _fail(f"unknown clockwork event {action!r}")
        try:
            tick = int(item["tick"])
        except (KeyError, TypeError, ValueError):
            return _fail("clockwork event missing tick")
        if not advance(tick):
            return _fail("clockwork time advanced before start, beyond the wind limit, or moved backward")
        if action == "timeout":
            if not running or tick != max_ticks:
                return _fail("invalid wind-limit timeout")
            return _fail("wind limit reached before the safe opened")
        if tick >= max_ticks:
            return _fail("wind limit reached before the safe opened")
        if action == "drive":
            if not isinstance(item.get("running"), bool):
                return _fail("drive transition is not boolean")
            requested = item["running"]
            if not requested:
                return _fail("the drive cannot be stopped")
            if requested == running:
                return _fail("duplicate drive transition")
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
            replay_errors = [_error(float(shaft["angle_deg"])) for shaft in shafts]
            replay_accepted = all(not shaft["engaged"] for shaft in shafts) and all(value <= phase_tolerance for value in replay_errors)
            reported_angles = item.get("angles")
            if (
                not isinstance(reported_angles, list)
                or len(reported_angles) != len(shafts)
                or any(not _phase_close(value, shafts[index]["angle_deg"]) for index, value in enumerate(reported_angles))
                or item.get("engaged") != [bool(shaft["engaged"]) for shaft in shafts]
                or not isinstance(item.get("accepted"), bool)
                or item["accepted"] != replay_accepted
            ):
                return _fail("safe verdict disagrees with wobble-drive replay")
            if replay_accepted:
                # Only an accepted unlock ends the attempt. A refused TRY SAFE
                # is recorded and replayed, but the player may keep correcting.
                unlock = item
                terminal = True
            else:
                refused_attempts += 1
    errors = [_error(float(shaft["angle_deg"])) for shaft in shafts]
    accepted = unlock is not None
    passed = accepted and payload.get("completed") is True
    return {
        "graded": True,
        "passed": passed,
        "feedback": (
            f"{len(shafts)} {'phase' if len(shafts) == 1 else 'phases'} accepted under non-periodic wobble-drive load redistribution"
            + (f" after {refused_attempts} refused {'attempt' if refused_attempts == 1 else 'attempts'}" if refused_attempts else "")
            if passed
            else (
                f"safe never opened; final phase errors {' / '.join(f'{value:.1f}' for value in errors)}"
                if unlock is None
                else f"phase errors {' / '.join(f'{value:.1f}' for value in errors)}"
            )
        ),
    }
