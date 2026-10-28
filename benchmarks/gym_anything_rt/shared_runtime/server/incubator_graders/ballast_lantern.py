from __future__ import annotations

from typing import Any


MECHANIC_ID = "ballast_lantern"
TRACK_UNITS = 10_000


def _fail(message: str, score: int = 0) -> dict[str, Any]:
    return {"graded": True, "passed": False, "score": score, "feedback": message}


def _integer(value: Any, label: str, lower: int | None = None, upper: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} is not an integer")
    if lower is not None and value < lower:
        raise ValueError(f"{label} is below its bound")
    if upper is not None and value > upper:
        raise ValueError(f"{label} is above its bound")
    return value


def _trunc_div(numerator: int, denominator: int) -> int:
    return numerator // denominator if numerator >= 0 else -((-numerator) // denominator)


def _identity(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> str | None:
    if any(str(value.get("mechanic_id") or "") != MECHANIC_ID for value in (payload, truth, public)):
        return "mechanic mismatch"
    for key in ("task_id", "challenge_id"):
        expected = str(truth.get(key) or "")
        if not expected or str(payload.get(key) or "") != expected or str(public.get(key) or "") != expected:
            return f"stale or mismatched {key}"
    return None


def _contract(truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    for key in ("track_units", "parameters", "motion", "crate", "initial_state"):
        if truth.get(key) != public.get(key):
            raise ValueError(f"public and hidden {key} disagree")
    if truth.get("control_condition") != public.get("control_condition"):
        raise ValueError("control condition disagrees")
    if truth.get("track_units") != TRACK_UNITS:
        raise ValueError("shaft scale is malformed")
    p = truth.get("parameters")
    motion = truth.get("motion")
    crate = truth.get("crate")
    initial = truth.get("initial_state")
    if not all(isinstance(value, dict) for value in (p, motion, crate, initial)):
        raise ValueError("world records are missing")
    condition = truth.get("control_condition")
    if condition is not None and condition.get("difficulty_parameters") != p:
        raise ValueError("condition parameters disagree")
    interaction = str((condition or {}).get("interaction") or "full")
    if interaction not in {"simplified", "full"}:
        raise ValueError("interaction mode is invalid")

    integer_bounds = {
        "tick_ms": (40, 100), "max_ticks": (500, 1500), "cage_half_height": (600, 1400),
        "specimen_half_height": (120, 260), "crate_half_height": (180, 400),
        "thrust_accel": (3, 8), "gravity_accel": (2, 7), "drag_numerator": (85, 99),
        "drag_denominator": (100, 100), "boundary_restitution_numerator": (0, 3),
        "boundary_restitution_denominator": (2, 5), "specimen_speed_min": (14, 52),
        "specimen_speed_max": (18, 64), "specimen_accel": (1, 4),
        "darter_interval_min": (14, 50), "darter_interval_max": (18, 60),
        "capture_initial": (2500, 5500), "capture_max": (8000, 12000),
        "capture_fill_per_tick": (16, 40), "capture_drain_per_tick": (5, 24),
        "crate_meter_max": (1800, 4500), "crate_fill_per_tick": (24, 64),
        "crate_spawn_tick_min": (60, 150), "crate_spawn_tick_max": (70, 170),
        "crate_min_separation": (600, 3500), "trail_samples": (1, 6),
    }
    for key, bounds in integer_bounds.items():
        _integer(p.get(key), key, *bounds)
    laws = p.get("motion_law_pool")
    if not isinstance(laws, list) or not laws or len(laws) != len(set(laws)) or not set(laws) <= {"steady_sinker", "darter", "floater", "oscillator"}:
        raise ValueError("motion-law pool is malformed")
    if not isinstance(p.get("show_trend_beacon"), bool):
        raise ValueError("trend-beacon condition is malformed")
    if p["capture_fill_per_tick"] <= p["capture_drain_per_tick"] or p["capture_initial"] >= p["capture_max"]:
        raise ValueError("capture meter condition is malformed")
    if p["cage_half_height"] <= max(p["specimen_half_height"], p["crate_half_height"]):
        raise ValueError("cage geometry is malformed")
    if p["specimen_speed_min"] > p["specimen_speed_max"] or p["darter_interval_min"] > p["darter_interval_max"]:
        raise ValueError("motion parameter range is inverted")
    if p["crate_spawn_tick_min"] > p["crate_spawn_tick_max"]:
        raise ValueError("crate spawn range is inverted")
    if p["boundary_restitution_numerator"] >= p["boundary_restitution_denominator"]:
        raise ValueError("shaft restitution must lose energy")

    law = str(motion.get("law") or "")
    if law not in laws:
        raise ValueError("generated drift law is outside the active pool")
    motion_keys = ("min_y", "max_y", "start_y", "start_velocity", "speed", "acceleration", "boundary_burst", "darter_interval")
    for key in motion_keys:
        _integer(motion.get(key), f"motion {key}")
    if not 0 < motion["min_y"] < motion["start_y"] < motion["max_y"] < TRACK_UNITS:
        raise ValueError("specimen track is malformed")
    velocities = motion.get("darter_velocities")
    if not isinstance(velocities, list) or len(velocities) != 40 or any(isinstance(value, bool) or not isinstance(value, int) for value in velocities):
        raise ValueError("darter schedule is malformed")
    spawn_tick = _integer(crate.get("spawn_tick"), "crate spawn", p["crate_spawn_tick_min"], p["crate_spawn_tick_max"])
    crate_y = _integer(crate.get("y"), "crate position", p["cage_half_height"], TRACK_UNITS - p["cage_half_height"])
    if spawn_tick >= p["max_ticks"] or not 0 < crate_y < TRACK_UNITS:
        raise ValueError("crate contract is malformed")
    expected_initial = {
        "tick": 0, "cage_y": max(p["cage_half_height"], 1850), "cage_velocity": 0,
        "specimen_y": motion["start_y"], "specimen_velocity": motion["start_velocity"],
        "capture_meter": p["capture_initial"], "crate_meter": 0, "crate_spawned": False,
        "specimen_inside": False, "crate_inside": False, "status": "active",
    }
    if initial != expected_initial:
        raise ValueError("initial simulation state is malformed")
    return {"parameters": p, "motion": motion, "crate": crate, "initial": initial, "interaction": interaction}


def _advance_specimen(sim: dict[str, Any], motion: dict[str, Any]) -> None:
    tick = sim["tick"]
    law = motion["law"]
    velocity = sim["specimen_velocity"]
    if law == "darter" and (tick - 1) % motion["darter_interval"] == 0:
        index = ((tick - 1) // motion["darter_interval"]) % len(motion["darter_velocities"])
        velocity = motion["darter_velocities"][index]
    elif law == "steady_sinker":
        velocity = max(-motion["speed"], velocity - motion["acceleration"])
    elif law == "floater":
        velocity = min(motion["speed"], velocity + motion["acceleration"])
    position = sim["specimen_y"] + velocity
    if position <= motion["min_y"]:
        position = motion["min_y"]
        velocity = motion["boundary_burst"] if law == "steady_sinker" else abs(velocity)
    elif position >= motion["max_y"]:
        position = motion["max_y"]
        velocity = -motion["boundary_burst"] if law == "floater" else -abs(velocity)
    sim["specimen_y"], sim["specimen_velocity"] = position, velocity


def _advance(sim: dict[str, Any], engaged: bool, p: dict[str, Any], motion: dict[str, Any], crate: dict[str, Any]) -> None:
    if sim["status"] != "active":
        return
    sim["tick"] += 1
    velocity = sim["cage_velocity"] + (p["thrust_accel"] if engaged else -p["gravity_accel"])
    velocity = _trunc_div(velocity * p["drag_numerator"], p["drag_denominator"])
    position = sim["cage_y"] + velocity
    lower, upper = p["cage_half_height"], TRACK_UNITS - p["cage_half_height"]
    if position <= lower:
        position = lower
        velocity = _trunc_div(abs(velocity) * p["boundary_restitution_numerator"], p["boundary_restitution_denominator"])
    elif position >= upper:
        position = upper
        velocity = -_trunc_div(abs(velocity) * p["boundary_restitution_numerator"], p["boundary_restitution_denominator"])
    sim["cage_y"], sim["cage_velocity"] = position, velocity
    _advance_specimen(sim, motion)
    sim["crate_spawned"] = sim["tick"] >= crate["spawn_tick"]
    sim["specimen_inside"] = abs(sim["cage_y"] - sim["specimen_y"]) <= p["cage_half_height"] - p["specimen_half_height"]
    sim["crate_inside"] = bool(sim["crate_spawned"] and abs(sim["cage_y"] - crate["y"]) <= p["cage_half_height"] - p["crate_half_height"])
    if sim["specimen_inside"]:
        sim["capture_meter"] = min(p["capture_max"], sim["capture_meter"] + p["capture_fill_per_tick"])
    else:
        sim["capture_meter"] = max(0, sim["capture_meter"] - p["capture_drain_per_tick"])
    if sim["crate_inside"]:
        sim["crate_meter"] = min(p["crate_meter_max"], sim["crate_meter"] + p["crate_fill_per_tick"])
    if sim["capture_meter"] <= 0:
        sim["status"] = "escaped"
    elif sim["capture_meter"] >= p["capture_max"]:
        sim["status"] = "secured" if sim["crate_meter"] >= p["crate_meter_max"] else "specimen_only"
    elif sim["tick"] >= p["max_ticks"]:
        sim["status"] = "timeout"


def _snapshot(sim: dict[str, Any]) -> dict[str, Any]:
    return {key: sim[key] for key in (
        "tick", "cage_y", "cage_velocity", "specimen_y", "specimen_velocity", "capture_meter",
        "crate_meter", "crate_spawned", "specimen_inside", "crate_inside", "status",
    )}


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    identity_error = _identity(payload, truth, public)
    if identity_error:
        return _fail(identity_error)
    try:
        contract = _contract(truth, public)
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"invalid Ballast Lantern contract: {exc}")
    interaction = contract["interaction"]
    if payload.get("interaction_mode") != interaction:
        return _fail("submitted interaction mode differs from task condition")
    events = payload.get("events")
    if not isinstance(events, list) or not events or len(events) > 10_000:
        return _fail("winch transcript is missing or oversized")
    terminal_tick = payload.get("terminal_tick")
    try:
        terminal_tick = _integer(terminal_tick, "terminal tick", 1, contract["parameters"]["max_ticks"])
    except ValueError as exc:
        return _fail(str(exc))
    previous_event_tick = -1
    for sequence, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("sequence") != sequence or event.get("type") != "winch":
            return _fail(f"event {sequence} has invalid identity")
        event_tick = event.get("tick")
        if isinstance(event_tick, bool) or not isinstance(event_tick, int) or not previous_event_tick <= event_tick < terminal_tick:
            return _fail(f"event {sequence} has an invalid tick")
        previous_event_tick = event_tick
    expected_source = "keyboard_hold" if interaction == "full" else "winch_button"
    sim = dict(contract["initial"])
    engaged = False
    next_event = 0
    try:
        while sim["tick"] < terminal_tick and sim["status"] == "active":
            while next_event < len(events) and events[next_event].get("tick") == sim["tick"]:
                event = events[next_event]
                sequence = next_event + 1
                if event.get("input_source") != expected_source:
                    raise ValueError(f"event {sequence} uses the wrong interaction input")
                if not isinstance(event.get("engaged"), bool) or event["engaged"] == engaged:
                    raise ValueError(f"event {sequence} does not change the winch state")
                phase = event.get("phase")
                expected_phase = ("keydown" if event["engaged"] else "keyup") if interaction == "full" else ("haul" if event["engaged"] else "coast")
                if phase != expected_phase:
                    raise ValueError(f"event {sequence} reports the wrong control phase")
                engaged = event["engaged"]
                next_event += 1
            _advance(sim, engaged, contract["parameters"], contract["motion"], contract["crate"])
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"Ballast replay rejected: {exc}")
    if next_event != len(events):
        return _fail("winch transcript contains events after the submitted terminal state")
    if sim["tick"] != terminal_tick or sim["status"] == "active":
        return _fail("submitted run did not reach a terminal simulation state")
    if payload.get("final_state") != _snapshot(sim):
        return _fail("submitted final shaft state does not match replay")
    completed = sim["status"] == "secured"
    if payload.get("completed") is not completed:
        return _fail("submitted completion flag does not match replay")
    if completed:
        score = 100
    elif sim["status"] == "specimen_only":
        score = 65
    else:
        specimen = round(50 * sim["capture_meter"] / contract["parameters"]["capture_max"])
        crate = round(30 * sim["crate_meter"] / contract["parameters"]["crate_meter_max"])
        score = min(80, specimen + crate)
    return {
        "graded": True,
        "passed": completed,
        "score": score,
        "feedback": (
            f"replayed {sim['tick']} shaft ticks; specimen {sim['capture_meter']}/{contract['parameters']['capture_max']}; "
            f"crate {sim['crate_meter']}/{contract['parameters']['crate_meter_max']}; {sim['status']}"
        ),
    }


def cheat(public_state: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    del public_state
    return {
        "reference_schedule": ground_truth.get("reference_schedule"),
        "reference_final_state": ground_truth.get("reference_final_state"),
        "reference_metrics": ground_truth.get("reference_metrics"),
    }
