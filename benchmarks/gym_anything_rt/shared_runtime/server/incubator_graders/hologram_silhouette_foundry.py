from __future__ import annotations

from typing import Any, Callable

MECHANIC_ID = "hologram_silhouette_foundry"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _cells(item: dict[str, Any]) -> set[tuple[int, int, int]]:
    center = [int(value) for value in item["center"]]
    axis = "xyz".index(str(item["axis"]))
    result = set()
    for offset in (-1, 0, 1):
        point = center.copy()
        point[axis] += offset
        result.add(tuple(point))
    return result


def _valid(objects: list[dict[str, Any]], size: int) -> bool:
    cells = [cell for item in objects for cell in _cells(item)]
    return len(cells) == len(set(cells)) and all(all(0 <= value < size for value in cell) for cell in cells)


def _masks(objects: list[dict[str, Any]]) -> dict[str, list[str]]:
    views: dict[str, tuple[Callable, Callable]] = {
        "front": (lambda cell: (cell[0], cell[2]), lambda cell: cell[1]),
        "side": (lambda cell: (cell[1], cell[2]), lambda cell: cell[0]),
        "top": (lambda cell: (cell[0], cell[1]), lambda cell: cell[2]),
    }
    result: dict[str, list[str]] = {}
    for name, (project, depth) in views.items():
        nearest: dict[tuple[int, int], tuple[int, str]] = {}
        for item in objects:
            for cell in _cells(item):
                key = project(cell)
                candidate = (depth(cell), str(item["color"]))
                if key not in nearest or candidate[0] < nearest[key][0]:
                    nearest[key] = candidate
        result[name] = sorted(f"{u}:{v}:{color}" for (u, v), (_distance, color) in nearest.items())
    return result


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    condition = truth.get("control_condition")
    if public.get("control_condition") != condition:
        return _fail("public interaction condition differs from foundry contract")
    interaction = str((condition or {}).get("interaction") or "")
    expected_source = {"simplified": "transform_button", "full": "gizmo_drag"}.get(interaction)
    if condition is not None and expected_source is None:
        return _fail("foundry interaction condition is invalid")
    if condition is not None:
        parameters = condition.get("difficulty_parameters")
        if not isinstance(parameters, dict) or parameters.get("rod_count") != len(public.get("objects") or []) or parameters.get("grid_size") != public.get("grid_size"):
            return _fail("foundry difficulty parameters differ from generated casting")
    objects = {item["id"]: dict(item, center=list(item["center"])) for item in public.get("objects") or []}
    events = payload.get("events")
    if not 3 <= len(objects) <= 7 or not isinstance(events, list) or len(events) > 1800:
        return _fail("foundry transcript malformed")
    cast = None
    limit = int(public["grid_size"]) - 2
    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        action = item.get("type")
        if action == "abandon":
            return _fail("casting abandoned")
        if action in {"translate", "rotate"}:
            current = objects.get(item.get("object_id"))
            before, after = item.get("before"), item.get("after")
            if current is None or before != current or not isinstance(after, dict):
                return _fail("rod transform starts from stale geometry")
            if expected_source is not None and item.get("input_source") != expected_source:
                return _fail("rod transform uses the wrong interaction input")
            expected = dict(current, center=list(current["center"]))
            if action == "translate":
                axis, delta = str(item.get("axis")), item.get("delta")
                if axis not in "xyz" or delta not in {-1, 1}:
                    return _fail("invalid rod translation")
                index = "xyz".index(axis)
                expected["center"][index] = max(1, min(limit, expected["center"][index] + int(delta)))
            else:
                expected["axis"] = "xyz"[("xyz".index(expected["axis"]) + 1) % 3]
            if after != expected:
                return _fail("rod reports an impossible transform")
            objects[current["id"]] = after
        elif action == "cast":
            cast = item
        else:
            return _fail(f"unknown foundry event {action!r}")
    arranged = list(objects.values())
    valid = _valid(arranged, int(public["grid_size"]))
    current_masks = _masks(arranged)
    exact = valid and current_masks == public.get("target_masks")
    if not isinstance(cast, dict) or cast.get("objects") != arranged or cast.get("masks") != current_masks or bool(cast.get("valid")) != valid or bool(cast.get("exact")) != exact:
        return _fail("cast report disagrees with solid colored projection replay")
    passed = exact and payload.get("completed") is True
    return {"graded": True, "passed": passed, "feedback": f"{len(objects)} non-overlapping rods match all three frontmost-color dies" if passed else "occupancy, color, or depth order still disagrees"}
