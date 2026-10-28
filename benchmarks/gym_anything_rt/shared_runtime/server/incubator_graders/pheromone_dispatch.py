from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "pheromone_dispatch"
MAX_ROUTE_SAMPLE_GAP = 160.0


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        x, y = float(value["x"]), float(value["y"])
    except (KeyError, TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _path(value: Any) -> list[tuple[float, float]] | None:
    if not isinstance(value, list):
        return None
    parsed = [_point(item) for item in value]
    return None if any(item is None for item in parsed) else [item for item in parsed if item is not None]


def _same_path(first: list[tuple[float, float]], second: list[tuple[float, float]]) -> bool:
    return len(first) == len(second) and all(math.dist(a, b) <= .01 for a, b in zip(first, second, strict=True))


def _hits(first: tuple[float, float], second: tuple[float, float], rect: dict[str, Any]) -> bool:
    steps = max(1, math.ceil(math.dist(first, second) / 5))
    for index in range(steps + 1):
        amount = index / steps
        x = first[0] + (second[0] - first[0]) * amount
        y = first[1] + (second[1] - first[1]) * amount
        if rect["x"] - rect["w"] / 2 < x < rect["x"] + rect["w"] / 2 and rect["y"] - rect["h"] / 2 < y < rect["y"] + rect["h"] / 2:
            return True
    return False


def _valid(path: list[tuple[float, float]], field: dict[str, Any], public: dict[str, Any]) -> bool:
    nest, cache, dock = tuple(public["nest"]), tuple(field["cache"]), tuple(public["dock"])
    return (
        len(path) > 5
        and math.dist(path[0], nest) < 38
        and any(math.dist(point, cache) < 38 for point in path)
        and math.dist(path[-1], dock) < 42
        and not any(_hits(path[index - 1], path[index], rect) for index in range(1, len(path)) for rect in public["obstacles"])
    )


def _metrics(path: list[tuple[float, float]], cache: tuple[float, float]) -> tuple[float, float]:
    lengths = [0.0]
    for first, second in zip(path, path[1:]):
        lengths.append(lengths[-1] + math.dist(first, second))
    cache_index = min(range(len(path)), key=lambda index: math.dist(path[index], cache))
    return lengths[-1], lengths[cache_index]


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    events = payload.get("events")
    fields = {item["id"]: item for item in public["fields"]}
    condition = truth.get("control_condition")
    expected_surface = str((condition or {}).get("interaction") or "")
    expected_method = {
        "simplified": "waypoint_clicks",
        "full": "continuous_pointer_trace",
    }.get(expected_surface, "")
    if not isinstance(events, list) or len(events) > 4200 or not 1 <= len(fields) <= 2:
        return _fail("field transcript malformed")
    if condition is not None and (
        public.get("control_condition") != condition
        or expected_surface not in {"simplified", "full"}
        or not expected_method
        or payload.get("interaction_mode") != expected_surface
    ):
        return _fail("controlled interaction surface mismatch")
    working = {field_id: [] for field_id in fields}
    active_field = None
    active_mode = None
    routes: dict[str, list[tuple[float, float]]] | None = None
    refreshes: dict[str, list[tuple[int, list[tuple[float, float]]]]] = {field_id: [] for field_id in fields}
    delivery = None
    last_event_tick = 0
    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        if condition is not None and (
            item.get("input_surface") != expected_surface
            or item.get("input_method") != expected_method
        ):
            return _fail("controlled event used the wrong input procedure")
        action = item.get("type")
        if action == "abandon":
            return _fail("colony fumigated")
        if action in {"clear", "stroke_start", "stroke_point", "stroke_end", "dispatch", "refresh", "delivery"}:
            try:
                tick = int(item["tick"])
            except (KeyError, TypeError, ValueError):
                return _fail("field event missing tick")
            if tick < last_event_tick or tick > 5000:
                return _fail("field time moved backward or beyond replay bounds")
            last_event_tick = tick
        field_id = item.get("field_id")
        if action == "clear":
            if routes is not None or field_id not in fields:
                return _fail("field washed during dispatch or with unknown color")
            working[field_id] = []
        elif action == "stroke_start":
            point = _point(item.get("point"))
            mode = item.get("mode")
            if active_field is not None or field_id not in fields or point is None or mode not in {"route", "refresh"} or (mode == "refresh") != (routes is not None):
                return _fail("colored stroke begins in an invalid mode")
            active_field, active_mode = field_id, mode
            working[field_id] = [point]
        elif action == "stroke_point":
            point = _point(item.get("point"))
            if point is None or field_id != active_field or item.get("mode") != active_mode or not working[field_id] or math.dist(working[field_id][-1], point) > MAX_ROUTE_SAMPLE_GAP:
                return _fail("pheromone brush teleported, switched color, or changed mode")
            working[field_id].append(point)
        elif action == "stroke_end":
            if field_id != active_field or item.get("mode") != active_mode or item.get("samples") != len(working[field_id]):
                return _fail("colored stroke sample count or mode invalid")
            active_field = active_mode = None
        elif action == "dispatch":
            reported = item.get("paths")
            if routes is not None or item.get("tick") != 0 or active_field is not None or not isinstance(reported, dict) or set(reported) != set(fields):
                return _fail("dual dispatch ledger malformed")
            parsed: dict[str, list[tuple[float, float]]] = {}
            for identity, field in fields.items():
                path = _path(reported.get(identity))
                if path is None or not _same_path(path, working[identity]) or not _valid(path, field, public):
                    return _fail(f"{identity} dispatch is not its painted safe cache route")
                parsed[identity] = path
            routes = parsed
        elif action == "refresh":
            path = _path(item.get("path"))
            if routes is None or field_id not in fields or path is None or active_field is not None or not _same_path(path, working[field_id]) or not _valid(path, fields[field_id], public):
                return _fail("field refresh is not a complete route for its selected color")
            refreshes[field_id].append((int(item["tick"]), path))
        elif action == "delivery":
            if delivery is not None:
                return _fail("duplicate dual-swarm delivery")
            delivery = item
        else:
            return _fail(f"unknown swarm event {action!r}")
    if routes is None or delivery is None:
        return _fail("dual routes or delivery missing")
    delivery_tick = delivery.get("tick")
    if not isinstance(delivery_tick, int) or delivery_tick <= 0 or delivery_tick > 5000:
        return _fail("delivery time invalid")

    physics = public["physics"]
    distances = {identity: [-index * float(physics["ant_spacing"]) for index in range(int(public["ant_count"]))] for identity in fields}
    carrying = {identity: [False] * int(public["ant_count"]) for identity in fields}
    done = {identity: [False] * int(public["ant_count"]) for identity in fields}
    delivered = {identity: 0 for identity in fields}
    last_refresh = {identity: 0 for identity in fields}
    refresh_index = {identity: 0 for identity in fields}
    route_metrics = {identity: _metrics(routes[identity], tuple(field["cache"])) for identity, field in fields.items()}
    completion_tick = None
    for tick in range(1, delivery_tick + 1):
        for identity, field in fields.items():
            entries = refreshes[identity]
            while refresh_index[identity] < len(entries) and entries[refresh_index[identity]][0] < tick:
                last_refresh[identity] = entries[refresh_index[identity]][0]
                refresh_index[identity] += 1
            if tick - last_refresh[identity] > int(field["trail_ttl_ticks"]):
                continue
            total, cache_distance = route_metrics[identity]
            for index in range(len(distances[identity])):
                if done[identity][index]:
                    continue
                distances[identity][index] += float(field["speed"])
                if distances[identity][index] < 0:
                    continue
                if distances[identity][index] >= cache_distance:
                    carrying[identity][index] = True
                if distances[identity][index] >= total:
                    done[identity][index] = True
                    if carrying[identity][index]:
                        delivered[identity] += 1
        if all(delivered[identity] >= int(physics["delivery_required"]) for identity in fields):
            completion_tick = tick
            break
    if completion_tick != delivery_tick or delivery.get("delivered") != delivered or delivery.get("last_refresh") != last_refresh:
        return _fail("dual delivery count, time, or independent freshness ledger disagrees with replay")
    passed = payload.get("completed") is True
    field_phrase = "the independent decaying carrier teams" if len(fields) == 2 else "the decaying carrier team"
    return {"graded": True, "passed": passed, "feedback": f"complete refreshes sustained {field_phrase}" if passed else "completion flag missing"}
