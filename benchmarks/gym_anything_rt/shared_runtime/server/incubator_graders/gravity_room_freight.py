from __future__ import annotations

from typing import Any

MECHANIC_ID = "gravity_room_freight"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _slide(board: dict[str, Any], position: list[int], direction: int, collected: int) -> tuple[list[int], int]:
    vectors = ((1, 0), (0, 1), (-1, 0), (0, -1))
    dx, dy = vectors[direction % 4]
    walls = {tuple(point) for point in board["walls"]}
    x, y = position
    while (x + dx, y + dy) not in walls:
        x += dx
        y += dy
        if collected < len(board["gates"]) and [x, y] == board["gates"][collected]:
            collected += 1
    return [x, y], collected


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    if truth.get("board") != public.get("board"):
        return _fail("public freight geometry differs from the replay contract")
    condition = truth.get("control_condition")
    if public.get("control_condition") != condition:
        return _fail("public interaction condition differs from freight contract")
    expected_rotation_source = {
        "simplified": "rotation_button",
        "full": "gimbal_drag",
    }.get(str((condition or {}).get("interaction") or ""))
    if condition is not None and expected_rotation_source is None:
        return _fail("gravity room interaction condition is invalid")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 240:
        return _fail("dual gravity transcript malformed")
    board = public["board"]
    cargo = list(board["cargo_start"])
    counter = list(board["counter_start"])
    orientation = int(public["initial_orientation"])
    collected = 0
    certify = None
    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        action = item.get("type")
        if action == "abandon":
            return _fail("gravity room ejected")
        if action == "rotate":
            if expected_rotation_source is not None and item.get("input_source") != expected_rotation_source:
                return _fail("room rotation uses the wrong interaction input")
            before = {"cargo": cargo, "counter": counter, "orientation": orientation, "collected": collected}
            if item.get("before") != before or item.get("direction") not in {"cw", "ccw"}:
                return _fail("room rotation starts from stale dual-body state")
            orientation = (orientation + (1 if item["direction"] == "cw" else -1)) % 4
            cargo, collected = _slide(board, cargo, orientation, collected)
            counter, _ignored = _slide(board, counter, orientation, 0)
            after = {"cargo": cargo, "counter": counter, "orientation": orientation, "collected": collected}
            if item.get("after") != after:
                return _fail("room rotation reports false settling contacts")
        elif action == "certify":
            if expected_rotation_source is not None and item.get("input_source") != "certify_button":
                return _fail("delivery certificate uses the wrong interaction input")
            certify = item
        else:
            return _fail(f"unknown gravity event {action!r}")
    accepted = collected == len(board["gates"]) and cargo == board["cargo_target"] and counter == board["counter_target"]
    if not isinstance(certify, dict) or certify.get("cargo") != cargo or certify.get("counter") != counter or certify.get("orientation") != orientation or certify.get("collected") != collected or bool(certify.get("accepted")) != accepted:
        return _fail("dual delivery certificate disagrees with joint replay")
    passed = accepted and payload.get("completed") is True
    seal_count = len(board["gates"])
    return {"graded": True, "passed": passed, "feedback": f"joint replay cleared {seal_count} seals and docked cargo plus isolated counterweight" if passed else f"seals={collected}/{seal_count}; cargo={cargo}; counter={counter}"}
