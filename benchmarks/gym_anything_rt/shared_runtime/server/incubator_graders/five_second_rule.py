from __future__ import annotations

import copy
import math
from typing import Any


MECHANIC_ID = "five_second_rule"
FULL_SOURCES = {
    "gate_tag": "direct_tag",
    "sync_hold": "direct_hold",
    "vector_flick": "direct_flick",
    "relay_pair": "direct_tap",
    "shutter_drop": "direct_drag",
}
SIMPLIFIED_SOURCES = {
    "gate_tag": "proxy_tag",
    "sync_hold": "proxy_hold",
    "vector_flick": "proxy_flick",
    "relay_pair": "proxy_tap",
    "shutter_drop": "proxy_drop",
}
DIRECTION_ANGLES = {"NORTH": -90.0, "EAST": 0.0, "SOUTH": 90.0, "WEST": 180.0}


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _bind(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> str | None:
    if any(str(item.get("mechanic_id") or "") != MECHANIC_ID for item in (payload, truth, public)):
        return "mechanic mismatch"
    for key in ("task_id", "challenge_id", "world_fingerprint"):
        expected = str(truth.get(key) or "")
        if not expected or str(payload.get(key) or "") != expected or str(public.get(key) or "") != expected:
            return f"stale or mismatched {key}"
    return None


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _point(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is missing")
    return _number(value.get("x"), f"{label}.x"), _number(value.get("y"), f"{label}.y")


def _token(round_spec: dict[str, Any], token_id: str) -> dict[str, Any]:
    token = next((item for item in round_spec.get("tokens") or [] if str(item.get("id")) == token_id), None)
    if not isinstance(token, dict):
        raise ValueError("event names an unknown token")
    return token


def _motion_position(token: dict[str, Any], elapsed_ms: float) -> tuple[float, float]:
    motion = token.get("motion")
    if not isinstance(motion, dict):
        return float(token["x"]), float(token["y"])
    seconds = elapsed_ms / 1000.0
    x = float(motion["x0"]) + float(motion["vx"]) * seconds
    y = float(motion["y0"]) + float(motion["amplitude"]) * math.sin(
        elapsed_ms / float(motion["period_ms"]) * 2 * math.pi + float(motion["phase"])
    )
    return x, y


def _angle_diff(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _event_time(event: dict[str, Any], duration_ms: int) -> float:
    value = _number(event.get("t_ms"), "event time")
    if not 0 <= value < duration_ms:
        raise ValueError("event falls outside the five-second round")
    return value


def _check_point_near(event: dict[str, Any], key: str, expected: tuple[float, float], radius: float) -> None:
    actual = _point(event.get(key), key)
    if math.hypot(actual[0] - expected[0], actual[1] - expected[1]) > radius:
        raise ValueError(f"{key} misses visible geometry")


def _check_source(event: dict[str, Any], family: str, interaction: str) -> None:
    expected = (FULL_SOURCES if interaction == "full" else SIMPLIFIED_SOURCES)[family]
    if event.get("input_source") != expected:
        raise ValueError("event uses the wrong interaction surface")


def _gate(round_spec: dict[str, Any], events: list[dict[str, Any]], interaction: str) -> None:
    if len(events) != 1 or events[0].get("type") != "tag":
        raise ValueError("gate dispatch requires one tag")
    event = events[0]
    _check_source(event, "gate_tag", interaction)
    elapsed = _event_time(event, round_spec["duration_ms"])
    target_id = str(round_spec["predicate"]["target_id"])
    if str(event.get("target_id") or "") != target_id:
        raise ValueError("wrong moving token tagged")
    token = _token(round_spec, target_id)
    position = _motion_position(token, elapsed)
    gate = round_spec["gate"]
    if abs(position[0] - float(gate["x"])) > float(gate["half_width"]):
        raise ValueError("tag lands outside the visible gate")
    if interaction == "full":
        _check_point_near(event, "point", position, 37.0)


def _hold(round_spec: dict[str, Any], events: list[dict[str, Any]], interaction: str) -> None:
    if len(events) != 1 or events[0].get("type") != "hold":
        raise ValueError("synchronization dispatch requires one hold")
    event = events[0]
    _check_source(event, "sync_hold", interaction)
    target_id = str(round_spec["predicate"]["target_id"])
    if str(event.get("target_id") or "") != target_id:
        raise ValueError("wrong synchronization pad held")
    start = _number(event.get("start_ms"), "hold start")
    end = _number(event.get("end_ms"), "hold end")
    if not 0 <= start < end < round_spec["duration_ms"]:
        raise ValueError("hold interval falls outside the round")
    cue = round_spec["cue"]
    tolerance = float(cue["tolerance_ms"])
    if abs(start - float(cue["start_ms"])) > tolerance:
        raise ValueError("hold did not begin as both needles entered")
    if abs(end - float(cue["end_ms"])) > tolerance:
        raise ValueError("hold did not release on the amber cue")
    minimum_duration = float(cue["end_ms"] - cue["start_ms"]) - tolerance * 2
    if end - start < minimum_duration:
        raise ValueError("hold duration is too short")
    if interaction == "full":
        token = _token(round_spec, target_id)
        _check_point_near(event, "start_point", (float(token["x"]), float(token["y"])), 42.0)


def _flick(round_spec: dict[str, Any], events: list[dict[str, Any]], interaction: str) -> None:
    if len(events) != 1 or events[0].get("type") != "flick":
        raise ValueError("vector dispatch requires one flick")
    event = events[0]
    _check_source(event, "vector_flick", interaction)
    elapsed = _event_time(event, round_spec["duration_ms"])
    target_id = str(round_spec["predicate"]["target_id"])
    if str(event.get("target_id") or "") != target_id:
        raise ValueError("wrong pointer token flicked")
    flick = round_spec["flick"]
    pointer_angle = (float(flick["angle_zero_deg"]) + float(flick["angular_speed_deg_s"]) * elapsed / 1000.0) % 360.0
    if _angle_diff(pointer_angle, float(flick["face_angle_deg"])) > float(flick["angle_tolerance_deg"]):
        raise ValueError("pointer was outside the requested orientation sector")
    direction = str(flick["flick_direction"])
    if interaction == "full":
        start = _point(event.get("start_point"), "start_point")
        end = _point(event.get("end_point"), "end_point")
        token = _token(round_spec, target_id)
        if math.hypot(start[0] - float(token["x"]), start[1] - float(token["y"])) > 42:
            raise ValueError("flick did not start on the target token")
        dx, dy = end[0] - start[0], end[1] - start[1]
        travel = math.hypot(dx, dy)
        if travel < float(flick["min_travel_px"]):
            raise ValueError("flick travel is too short")
        actual_angle = math.degrees(math.atan2(dy, dx))
        if _angle_diff(actual_angle, DIRECTION_ANGLES[direction]) > 20:
            raise ValueError("flick vector has the wrong direction")
    elif str(event.get("direction") or "") != direction:
        raise ValueError("proxy flick has the wrong direction")


def _relay(round_spec: dict[str, Any], events: list[dict[str, Any]], interaction: str) -> None:
    if len(events) != 2 or any(event.get("type") != "tap" for event in events):
        raise ValueError("relay dispatch requires two taps")
    expected = [str(round_spec["predicate"]["first_id"]), str(round_spec["predicate"]["second_id"])]
    for event, target_id in zip(events, expected):
        _check_source(event, "relay_pair", interaction)
        _event_time(event, round_spec["duration_ms"])
        if str(event.get("target_id") or "") != target_id:
            raise ValueError("relay taps are not in the requested order")
        if interaction == "full":
            token = _token(round_spec, target_id)
            _check_point_near(event, "point", (float(token["x"]), float(token["y"])), 38.0)


def _bay_open(bay: dict[str, Any], elapsed_ms: float) -> bool:
    phase = (elapsed_ms + float(bay["phase_offset_ms"])) % float(bay["period_ms"])
    return phase < float(bay["open_ms"])


def _drop(round_spec: dict[str, Any], events: list[dict[str, Any]], interaction: str) -> None:
    if len(events) != 1 or events[0].get("type") != "drop":
        raise ValueError("shutter dispatch requires one drop")
    event = events[0]
    _check_source(event, "shutter_drop", interaction)
    elapsed = _event_time(event, round_spec["duration_ms"])
    target_id = str(round_spec["predicate"]["target_id"])
    bay_id = str(round_spec["predicate"]["bay_id"])
    if str(event.get("target_id") or "") != target_id or str(event.get("bay_id") or "") != bay_id:
        raise ValueError("cargo or receiving bay is wrong")
    bay = next((item for item in round_spec.get("bays") or [] if str(item.get("id")) == bay_id), None)
    if not isinstance(bay, dict) or not _bay_open(bay, elapsed):
        raise ValueError("cargo reached a closed shutter")
    if interaction == "full":
        token = _token(round_spec, target_id)
        _check_point_near(event, "start_point", (float(token["x"]), float(token["y"])), 42.0)
        _check_point_near(event, "end_point", (float(bay["x"]), float(bay["y"])), float(bay["radius"]))
        start = _point(event.get("start_point"), "start_point")
        end = _point(event.get("end_point"), "end_point")
        if math.hypot(end[0] - start[0], end[1] - start[1]) < 120:
            raise ValueError("cargo drag path is too short")


def _contract(truth: dict[str, Any], public: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    rounds = copy.deepcopy(truth.get("rounds"))
    if not isinstance(rounds, list) or len(rounds) != 5 or public.get("rounds") != rounds:
        raise ValueError("public dispatch deck differs from replay contract")
    parameters = truth.get("parameters")
    if not isinstance(parameters, dict) or public.get("parameters") != parameters:
        raise ValueError("difficulty parameters differ from replay contract")
    condition = truth.get("control_condition")
    if condition != public.get("control_condition"):
        raise ValueError("public control condition differs from replay contract")
    if condition is not None and condition.get("difficulty_parameters") != parameters:
        raise ValueError("condition parameters differ from generated deck")
    interaction = str((condition or {}).get("interaction") or "full")
    if interaction not in {"simplified", "full"}:
        raise ValueError("interaction mode is invalid")
    if {str(item.get("family")) for item in rounds} != {"gate_tag", "sync_hold", "vector_flick", "relay_pair", "shutter_drop"}:
        raise ValueError("dispatch family set is incomplete")
    if any(item.get("duration_ms") != 5000 or len(item.get("instruction") or []) != 2 for item in rounds):
        raise ValueError("every dispatch must carry two lines and a five-second duration")
    return rounds, interaction


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    binding = _bind(payload, truth, public)
    if binding:
        return _fail(binding)
    try:
        expected_rounds, interaction = _contract(truth, public)
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"invalid five-second contract: {exc}")
    if payload.get("interaction_mode") != interaction:
        return _fail("submitted interaction mode differs from task condition")
    records = payload.get("rounds")
    if not isinstance(records, list) or len(records) != len(expected_rounds):
        return _fail("all five dispatches must be completed")
    sequence = 0
    validators = {
        "gate_tag": _gate,
        "sync_hold": _hold,
        "vector_flick": _flick,
        "relay_pair": _relay,
        "shutter_drop": _drop,
    }
    try:
        for expected, record in zip(expected_rounds, records):
            if not isinstance(record, dict) or record.get("round_id") != expected["id"] or record.get("family") != expected["family"]:
                raise ValueError("dispatch order or identity is stale")
            events = record.get("events")
            if not isinstance(events, list):
                raise ValueError("dispatch event list is missing")
            previous_time = -1.0
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError("dispatch event must be an object")
                sequence += 1
                if event.get("sequence") != sequence:
                    raise ValueError("global event sequence is invalid")
                event_time = event.get("t_ms", event.get("end_ms"))
                value = _number(event_time, "event chronology")
                if value < previous_time:
                    raise ValueError("dispatch events are not chronological")
                previous_time = value
            validators[expected["family"]](expected, events, interaction)
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"five-second replay rejected: {exc}")
    passed = payload.get("completed") is True and sequence == 6
    return {
        "graded": True,
        "passed": passed,
        "feedback": f"{len(records)}/5 dispatch predicates replayed across {sequence} visible control events",
    }
