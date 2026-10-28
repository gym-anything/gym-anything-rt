from __future__ import annotations

import math
from typing import Any


MECHANIC_ID = "cloudpost_circuit"
CONTACT_TICK_TOLERANCE = 1
REPLAY_POSE_TOLERANCE = 1.5
REPLAY_LEDGER_LIMIT = 10000


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _close(first: Any, second: Any, tolerance: float = 0.06) -> bool:
    return _finite(first) and _finite(second) and abs(float(first) - float(second)) <= tolerance


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _step_plane(plane: dict[str, float], control: tuple[float, float], physics: dict[str, Any]) -> None:
    yaw_control, pitch_control = control
    max_yaw = float(physics["max_yaw"])
    max_pitch = float(physics["max_pitch"])
    desired_yaw = _clamp(float(yaw_control), -1.0, 1.0) * max_yaw
    desired_pitch = _clamp(float(pitch_control), -1.0, 1.0) * max_pitch
    turn_step = float(physics["turn_step"])
    plane["yaw"] += _clamp(desired_yaw - plane["yaw"], -turn_step, turn_step)
    plane["pitch"] += _clamp(desired_pitch - plane["pitch"], -turn_step, turn_step)
    cos_pitch = math.cos(plane["pitch"])
    plane["x"] += math.sin(plane["yaw"]) * cos_pitch * float(physics["flight_speed"])
    plane["y"] += math.sin(plane["pitch"]) * float(physics["flight_speed"])
    plane["z"] += math.cos(plane["yaw"]) * cos_pitch * float(physics["flight_speed"])


def _plane_copy(public: dict[str, Any]) -> dict[str, float]:
    initial = public.get("initial_plane") or {}
    return {key: float(initial.get(key, 0.0)) for key in ("x", "y", "z", "yaw", "pitch")}


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    if public.get("challenge_id") != truth.get("challenge_id") or public.get("task_id") != truth.get("task_id"):
        return _fail("public challenge is not the submitted challenge")

    condition = truth.get("control_condition")
    if public.get("control_condition") != condition or public.get("physics") != truth.get("physics") or public.get("targets") != truth.get("targets"):
        return _fail("visible flight geometry or condition differs from the authoritative world")
    expected_interaction = "full" if condition is None else str(condition.get("interaction") or "")
    if payload.get("interaction") != expected_interaction:
        return _fail("wrong interaction mode for this task")
    expected_source = "pointer_steer" if expected_interaction == "full" else "trim_button"

    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 6000:
        return _fail("flight ledger malformed")
    physics = public.get("physics") or {}
    try:
        world_x = float(physics["world_x"])
        world_y = float(physics["world_y"])
        world_z = float(physics["world_z"])
    except (KeyError, TypeError, ValueError):
        return _fail("flight physics malformed")

    schedule: dict[int, tuple[float, float]] = {}
    contacts_reported: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    last_tick = 0
    prior_control = (0.0, 0.0)
    for sequence, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        kind = str(event.get("type") or "")
        if terminal is not None:
            return _fail("flight ledger continues after terminal state")
        try:
            tick = int(event.get("tick"))
        except (TypeError, ValueError):
            return _fail(f"event {sequence} has no tick")
        if tick < 0 or tick > REPLAY_LEDGER_LIMIT or tick < last_tick:
            return _fail("flight event time moved backward or beyond the route")
        last_tick = tick
        if kind == "steer":
            if event.get("input_source") != expected_source:
                return _fail("steering event came from the wrong interaction surface")
            if not _finite(event.get("yaw")) or not _finite(event.get("pitch")):
                return _fail("steering control is not finite")
            yaw, pitch = float(event["yaw"]), float(event["pitch"])
            if not -1 <= yaw <= 1 or not -1 <= pitch <= 1:
                return _fail("steering vector exceeds the visible control range")
            if expected_interaction == "simplified":
                py, pp = prior_control
                legal = [(0.0,0.0), (_clamp(py-.12,-1,1),pp), (_clamp(py+.12,-1,1),pp),
                         (py,_clamp(pp-.10,-1,1)), (py,_clamp(pp+.10,-1,1))]
                if not any(abs(yaw-ly)<1e-7 and abs(pitch-lp)<1e-7 for ly,lp in legal):
                    return _fail("trim event is not one visible button increment or LEVEL")
            prior_control = (yaw,pitch)
            schedule[tick] = (yaw, pitch)
        elif kind == "contact":
            contacts_reported.append(event)
        elif kind == "terminal":
            if terminal is not None:
                return _fail("duplicate flight terminal")
            terminal = event
        else:
            return _fail(f"unknown flight event {kind!r}")

    targets = [dict(item) for item in (public.get("targets") or [])]
    if not targets or len({str(item.get("id")) for item in targets}) != len(targets):
        return _fail("target geometry is malformed")
    target_by_id = {str(item["id"]): item for item in targets}
    plane = _plane_copy(public)
    control = (0.0, 0.0)
    collected: set[str] = set()
    replay_contacts: list[dict[str, Any]] = []
    completion_tick: int | None = None
    replay_end_tick = terminal.get("tick") if terminal is not None else last_tick
    if not isinstance(replay_end_tick, int) or replay_end_tick < 0 or replay_end_tick > REPLAY_LEDGER_LIMIT:
        return _fail("flight terminal time is malformed")
    for tick in range(replay_end_tick + 1):
        if tick > 0:
            _step_plane(plane, control, physics)
        if abs(plane["x"]) > world_x or abs(plane["y"]) > world_y or plane["z"] > world_z:
            return _fail("plane left the visible flight corridor")
        for target in targets:
            target_id = str(target["id"])
            if target_id in collected:
                continue
            distance = math.sqrt(
                (plane["x"] - float(target["x"])) ** 2
                + (plane["y"] - float(target["y"])) ** 2
                + (plane["z"] - float(target["z"])) ** 2
            )
            if distance <= float(physics["contact_radius"]):
                collected.add(target_id)
                replay_contacts.append({
                    "tick": tick,
                    "target_id": target_id,
                    "distance": round(distance, 4),
                    "plane": {key: round(value, 4) for key, value in plane.items()},
                })
        if len(collected) == len(targets):
            completion_tick = tick
            break
        # Browser pointer events are recorded after the current physics tick
        # and steer the following tick.  Keep that event ordering in the
        # independent replay; applying it before the same-numbered tick shifts
        # every later waypoint by one frame.
        if tick in schedule:
            control = schedule[tick]

    if len(contacts_reported) != len(replay_contacts):
        return _fail("seal contact ledger disagrees with world-space replay")
    for reported, replayed in zip(contacts_reported, replay_contacts, strict=True):
        if reported.get("tick") != replayed["tick"] or str(reported.get("target_id")) != replayed["target_id"]:
            return _fail("seal identity or contact tick disagrees with replay")
        if abs(int(reported.get("tick", -10**9)) - int(replayed["tick"])) > CONTACT_TICK_TOLERANCE:
            return _fail("seal contact timing disagrees with replay")
        if not _close(reported.get("distance"), replayed["distance"], REPLAY_POSE_TOLERANCE):
            return _fail("reported contact distance disagrees with replay")

    if completion_tick is None:
        if terminal is not None and terminal.get("completed") is True:
            return _fail("flight claimed completion before every seal was contacted")
        return _fail("flight ended before every seal was collected")
    if terminal is None or terminal.get("completed") is not True or terminal.get("tick") != completion_tick:
        return _fail("successful terminal flight ledger missing")
    if terminal.get("collected") != [item["target_id"] for item in replay_contacts]:
        return _fail("terminal collection order disagrees with replay")
    final_plane = terminal.get("plane") or {}
    if any(not _close(final_plane.get(key), value, 0.08) for key, value in plane.items()):
        return _fail("terminal plane pose disagrees with replay")
    if payload.get("completed") is not True:
        return _fail("completion flag missing")
    return {
        "graded": True,
        "passed": True,
        "feedback": f"world-space replay contacted {len(replay_contacts)} delivery seals at tick {completion_tick}",
    }
