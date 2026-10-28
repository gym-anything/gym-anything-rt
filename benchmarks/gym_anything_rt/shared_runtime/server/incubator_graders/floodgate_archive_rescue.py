from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "floodgate_archive_rescue"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _close(first: Any, second: Any, tolerance: float = .006) -> bool:
    try:
        return math.isfinite(float(first)) and abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def _levels(first: Any, second: list[float]) -> bool:
    return isinstance(first, list) and len(first) == len(second) and all(_close(value, second[index]) for index, value in enumerate(first))


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    condition = truth.get("control_condition")
    if public.get("control_condition") != condition:
        return _fail("public interaction condition differs from floodgate contract")
    interaction = str((condition or {}).get("interaction") or "")
    sources = {
        "simplified": {
            "pump": "circuit_button",
            "gate": "lock_button",
            "transfer": "transfer_button",
            "certify": "certify_button",
        },
        "full": {
            "pump": "water_drag",
            "gate": "lock_direct",
            "transfer": "capsule_drag",
            "certify": "certify_button",
        },
    }.get(interaction)
    if condition is not None and sources is None:
        return _fail("floodgate interaction condition is invalid")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 900:
        return _fail("conserved flood transcript malformed")
    levels = [float(item["level"]) for item in public["chambers"]]
    level_precision = int(public.get("level_precision", 2))
    if level_precision not in {2, 3}:
        return _fail("archive level precision is invalid")
    initial_total = sum(levels)
    gates = [False] * len(public["gates"])
    capsules = [dict(item) for item in public["capsules"]]
    certify = None
    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        action = item.get("type")
        if action == "abandon":
            return _fail("archive drained")
        if action == "pump":
            if sources is not None and item.get("input_source") != sources["pump"]:
                return _fail("pump uses the wrong interaction input")
            circuit_index, direction = item.get("circuit"), item.get("direction")
            if circuit_index not in range(len(public["circuits"])) or direction not in {-1, 1} or not _levels(item.get("before"), levels):
                return _fail("pump starts from stale levels or an invalid circuit")
            first, second = public["circuits"][circuit_index]["between"]
            source, destination = (first, second) if direction == 1 else (second, first)
            if item.get("source") != source or item.get("destination") != destination:
                return _fail("pump reports the wrong conserved transfer direction")
            step = float(public["pump_step"])
            if levels[source] - step < float(public["chambers"][source]["safe_min"]) - 1e-6 or levels[destination] + step > float(public["chambers"][destination]["safe_max"]) + 1e-6:
                return _fail("pump crossed a visible safe band")
            levels[source] = round(levels[source] - step, level_precision)
            levels[destination] = round(levels[destination] + step, level_precision)
            if not _levels(item.get("after"), levels) or not _close(item.get("total_after"), initial_total):
                return _fail("pump report violates level replay or conservation")
        elif action == "gate":
            if sources is not None and item.get("input_source") != sources["gate"]:
                return _fail("lock uses the wrong interaction input")
            gate = item.get("gate")
            if gate not in range(len(gates)) or not _levels(item.get("levels"), levels):
                return _fail("lock event malformed")
            opening = not gates[gate]
            gates = [opening if index == gate else False for index in range(len(gates))]
            if bool(item.get("open")) != opening or item.get("gates") != gates:
                return _fail("lock exclusivity ledger disagrees with replay")
        elif action == "transfer":
            if sources is not None and item.get("input_source") != sources["transfer"]:
                return _fail("capsule transfer uses the wrong interaction input")
            try:
                gate = gates.index(True)
            except ValueError:
                return _fail("capsule transfer requested with no open lock")
            if item.get("gate") != gate or not _levels(item.get("levels"), levels) or item.get("before_capsules") != capsules:
                return _fail("capsule transfer starts from stale lock state")
            moved: list[str] = []
            if abs(levels[gate] - levels[gate + 1]) <= float(public["equal_tolerance"]):
                for capsule in capsules:
                    if capsule["direction"] == 1 and capsule["chamber"] == gate:
                        capsule["chamber"] += 1
                        moved.append(capsule["id"])
                    elif capsule["direction"] == -1 and capsule["chamber"] == gate + 1:
                        capsule["chamber"] -= 1
                        moved.append(capsule["id"])
            if item.get("moved") != moved or item.get("after_capsules") != capsules:
                return _fail("opposing capsule movement disagrees with equalized-lock replay")
        elif action == "certify":
            if sources is not None and item.get("input_source") != sources["certify"]:
                return _fail("archive certificate uses the wrong interaction input")
            certify = item
        else:
            return _fail(f"unknown archive event {action!r}")
        if not _close(sum(levels), initial_total):
            return _fail("water mass changed during archive replay")
    accepted = all(capsule["chamber"] == capsule["dock_chamber"] for capsule in capsules)
    if not isinstance(certify, dict) or not _levels(certify.get("levels"), levels) or certify.get("capsules") != capsules or bool(certify.get("accepted")) != accepted:
        return _fail("dual archive certificate disagrees with conserved replay")
    passed = accepted and payload.get("completed") is True
    return {"graded": True, "passed": passed, "feedback": "water mass conserved and both opposing capsules crossed four equalized locks" if passed else f"capsules at {[item['chamber'] + 1 for item in capsules]}"}
