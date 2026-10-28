from __future__ import annotations

import math
from typing import Any


MECHANIC_ID = "horizon_relay_v2"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _rotate_y(point: list[float], angle_deg: float) -> tuple[float, float, float]:
    angle = math.radians(float(angle_deg))
    x, y, z = (float(value) for value in point)
    return (x * math.cos(angle) - z * math.sin(angle), y, x * math.sin(angle) + z * math.cos(angle))


def _station_at(station: dict[str, Any], tick: int, speed: float | list[float], radius: float) -> tuple[float, float, float]:
    lat = math.radians(float(station["latitude"]))
    angle = speed[tick] if isinstance(speed, list) else float(tick) * speed
    lon = math.radians(float(station["longitude"])) + math.radians(angle)
    return (radius * math.cos(lat) * math.cos(lon), radius * math.sin(lat), radius * math.cos(lat) * math.sin(lon))


def _dot(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return sum(a * b for a, b in zip(first, second))


def _sub(first: tuple[float, float, float], second: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(a - b for a, b in zip(first, second))


def _norm(value: tuple[float, float, float]) -> float:
    return math.sqrt(_dot(value, value))


def _visible(station: dict[str, Any], craft: dict[str, Any], tick: int, speed: float, radius: float) -> bool:
    station_point = _station_at(station, tick, speed, radius)
    craft_point = tuple(float(value) for value in craft["position"])
    line = _sub(craft_point, station_point)
    return _dot(station_point, line) > 1e-6


def _aim_error(station: dict[str, Any], craft: dict[str, Any], tick: int, speed: float, radius: float, aim: Any) -> float:
    try:
        vector = tuple(float(value) for value in aim)
    except (TypeError, ValueError):
        return math.inf
    station_point = _station_at(station, tick, speed, radius)
    craft_point = tuple(float(value) for value in craft["position"])
    target = _sub(craft_point, station_point)
    if _norm(vector) <= 1e-8 or _norm(target) <= 1e-8:
        return math.inf
    cosine = max(-1.0, min(1.0, _dot(vector, target) / (_norm(vector) * _norm(target))))
    return math.degrees(math.acos(cosine))


def _contract_matches(truth: dict[str, Any], public: dict[str, Any]) -> bool:
    fields = (
        "task_id", "challenge_id", "planet_radius", "tick_ms",
        "rotation_speed_deg_per_tick", "aim_tolerance_deg", "stations", "spacecraft",
        "control_condition", "interaction_mode",
        "rotation_angles_deg",
    )
    return all(truth.get(field) == public.get(field) for field in fields)


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID or public.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    if not _contract_matches(truth, public):
        return _fail("public/private horizon relay geometry differs")
    condition = truth.get("control_condition")
    interaction = str((condition or {}).get("interaction") or truth.get("interaction_mode") or "")
    if interaction not in {"simplified", "full"} or payload.get("interaction_mode") != interaction:
        return _fail("submitted interaction surface does not match the selected relay contract")
    expected_sources = {
        "simplified": {"station": "station_button", "aim": "target_button", "hold": "hold_button"},
        "full": {"station": "station_click", "aim": "dish_drag"},
    }[interaction]
    events = payload.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= 60000:
        return _fail("relay transcript missing or outside limits")
    stations = {str(item["id"]): item for item in truth.get("stations") or [] if isinstance(item, dict)}
    spacecraft = {str(item["id"]): item for item in truth.get("spacecraft") or [] if isinstance(item, dict)}
    if not stations or not spacecraft:
        return _fail("relay world is empty")
    radius = float(truth.get("planet_radius") or 0)
    speed = truth.get("rotation_angles_deg")
    if not isinstance(speed, list) or len(speed) != 20001 or not all(isinstance(a, (int, float)) and math.isfinite(a) for a in speed):
        return _fail("missing finite nonperiodic rotation")
    tolerance = float(truth.get("aim_tolerance_deg") or 0)
    current_station: str | None = None
    current_craft: str | None = None
    aim: Any = None
    active = False
    last_sample_tick: int | None = None
    progress = {craft_id: 0 for craft_id in spacecraft}
    completed: list[str] = []
    submitted = False
    previous_seq = 0
    previous_tick = 0
    for event in events:
        if not isinstance(event, dict) or event.get("seq") != previous_seq + 1:
            return _fail("event sequence is not contiguous")
        previous_seq += 1
        kind = str(event.get("type") or "")
        try:
            tick = int(event.get("tick"))
        except (TypeError, ValueError):
            return _fail(f"event {previous_seq} has no integer tick")
        if tick < previous_tick or tick > 20000:
            return _fail("event tick is outside the finite relay clock")
        previous_tick = tick
        if submitted:
            return _fail("event after terminal submission")
        # Every active tick must appear as a sample or a geometrically checked
        # link break. An aim cannot conceal an unobserved interruption.
        if active and last_sample_tick is not None:
            allowed_tick = last_sample_tick + (1 if kind in {"sample", "link_break"} else 0)
            if tick != allowed_tick:
                return _fail("active link contains an unrecorded task tick")
        if kind == "select_station":
            if event.get("input_source") != expected_sources["station"] or str(event.get("station_id")) not in stations:
                return _fail("station selection used the wrong input surface")
            if active and current_station != str(event["station_id"]):
                progress[current_craft] = 0
                active = False
                last_sample_tick = None
            current_station = str(event["station_id"])
        elif kind == "aim":
            station_id, craft_id = str(event.get("station_id")), str(event.get("craft_id"))
            if event.get("input_source") != expected_sources["aim"] or station_id not in stations or craft_id not in spacecraft:
                return _fail("dish aim used the wrong interaction input")
            if craft_id in completed:
                return _fail("dish aim reopened an already delivered spacecraft")
            if interaction == "simplified" and current_station != station_id:
                return _fail("target button aimed a station that was not selected")
            if interaction == "full" and event.get("input_source") != "dish_drag":
                return _fail("full relay aim was not a dish drag")
            if not _visible(stations[station_id], spacecraft[craft_id], tick, speed, radius):
                return _fail("dish was aimed at a spacecraft below the selected station horizon")
            error = _aim_error(stations[station_id], spacecraft[craft_id], tick, speed, radius, event.get("aim_vector"))
            if error > 2.0:
                return _fail(f"dish aim vector disagrees with the visible 3D target ({error:.2f} degrees)")
            if current_craft is not None and current_craft not in completed and (not active or current_craft != craft_id or current_station != station_id):
                progress[current_craft] = 0
            continuing = active and current_craft == craft_id and current_station == station_id
            current_station, current_craft, aim = station_id, craft_id, event.get("aim_vector")
            if interaction == "full":
                active = True
                if not continuing:
                    last_sample_tick = tick
        elif kind == "hold_start":
            if active:
                return _fail("duplicate hold start")
            if interaction != "simplified" or event.get("input_source") != expected_sources["hold"]:
                return _fail("hold control does not match simplified relay input")
            if current_station not in stations or current_craft not in spacecraft or aim is None:
                return _fail("hold started without an aimed station and spacecraft")
            if not _visible(stations[current_station], spacecraft[current_craft], tick, speed, radius):
                return _fail("hold started below the station horizon")
            active = True
            last_sample_tick = tick
        elif kind == "sample":
            if not active or current_station not in stations or current_craft not in spacecraft or aim is None:
                return _fail("transfer sample occurred without an active link")
            if tick != int(last_sample_tick) + 1:
                return _fail("transfer samples skip or repeat task ticks")
            visible = _visible(stations[current_station], spacecraft[current_craft], tick, speed, radius)
            error = _aim_error(stations[current_station], spacecraft[current_craft], tick, speed, radius, aim)
            if not visible or error > tolerance:
                return _fail("browser reported transfer while the replayed line of sight or aim was invalid")
            expected_after = progress[current_craft] + 1
            if progress[current_craft] >= int(spacecraft[current_craft]["required_ticks"]):
                return _fail("transfer sample exceeds the requested amount")
            if event.get("station_id") != current_station or event.get("craft_id") != current_craft or event.get("delivered_after") != expected_after:
                return _fail("transfer progress does not match the replayed link")
            progress[current_craft] = expected_after
            last_sample_tick = tick
        elif kind == "transfer_complete":
            if not active or current_craft not in spacecraft or current_craft in completed or progress[current_craft] != int(spacecraft[current_craft]["required_ticks"]):
                return _fail("transfer was marked complete before its samples")
            if event.get("craft_id") != current_craft or event.get("delivered") != int(spacecraft[current_craft]["required_ticks"]):
                return _fail("completion names the wrong spacecraft")
            completed.append(current_craft)
            active = False
            last_sample_tick = None
            current_craft = None
        elif kind == "link_break":
            if not active or current_station not in stations or current_craft not in spacecraft:
                return _fail("link break occurred without an active link")
            visible = _visible(stations[current_station], spacecraft[current_craft], tick, speed, radius)
            error = _aim_error(stations[current_station], spacecraft[current_craft], tick, speed, radius, aim)
            if visible and error <= tolerance:
                return _fail("link break was reported while the link was still valid")
            progress[current_craft] = 0
            active = False
            last_sample_tick = None
        elif kind == "link_stop":
            if not active:
                return _fail("duplicate link stop")
            progress[current_craft] = 0
            active = False
            last_sample_tick = None
        elif kind == "submit":
            submitted = True
        else:
            return _fail(f"unknown relay event {kind!r}")
    expected_completed = set(spacecraft)
    passed = submitted and payload.get("completed") is True and set(completed) == expected_completed and len(completed) == len(expected_completed) and all(progress[key] == int(value["required_ticks"]) for key, value in spacecraft.items())
    return {
        "graded": True,
        "passed": passed,
        "feedback": f"delivered {len(completed)}/{len(spacecraft)} spacecraft requests; replayed 3D horizon visibility and dish aiming",
    }
