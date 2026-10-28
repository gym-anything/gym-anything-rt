from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "wind_tunnel_seed_courier"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _close(first: Any, second: Any, tolerance: float = .025) -> bool:
    try:
        return math.isfinite(float(first)) and abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def _gate_y(slot: dict[str, Any], tick: int) -> float:
    return float(slot["base_y"]) + float(slot["amplitude"]) * math.sin(tick * float(slot["angular_rate"]) + float(slot["phase"]))


def _same_pod(first: dict[str, Any], second: dict[str, Any], tolerance: float = .004) -> bool:
    return all(_close(first.get(key), second.get(key), tolerance) for key in ("x", "y", "vx", "vy")) and bool(first.get("docked")) == bool(second.get("docked"))


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    condition = truth.get("control_condition")
    expected_input_source = None
    if condition is not None:
        if public.get("control_condition") != condition:
            return _fail("public wind control condition differs from the replay contract")
        if not isinstance(condition, dict):
            return _fail("wind control condition is malformed")
        interaction = str(condition.get("interaction") or "")
        expected_input_source = {
            "simplified": "fan_button",
            "full": "fan_lever_drag",
        }.get(interaction)
        if expected_input_source is None:
            return _fail("wind interaction mode is unsupported")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 1800:
        return _fail("dual wind transcript malformed")
    schedule: dict[int, list[tuple[int, int]]] = {}
    gate_reports: list[dict[str, Any]] = []
    dock_reports: list[dict[str, Any]] = []
    terminal = None
    launched = False
    last_time = 0
    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        action = item.get("type")
        if action == "abandon":
            return _fail("tunnel abandoned")
        if action in {"fan_control", "launch", "gate_pass", "dock", "terminal"}:
            try:
                event_tick = int(item["tick"])
            except (KeyError, TypeError, ValueError):
                return _fail("wind event missing physical tick")
            if event_tick < last_time or event_tick > int(public["physics"]["ticks"]):
                return _fail("wind event time moved backward or beyond the plant")
            last_time = event_tick
        if action == "fan_control":
            fan, power = item.get("fan"), item.get("power")
            if fan not in range(len(public["fans"])) or power not in {-1, 0, 1}:
                return _fail("fan control outside physical stops")
            if expected_input_source is not None and item.get("input_source") != expected_input_source:
                return _fail("fan control uses the wrong interaction input")
            schedule.setdefault(int(item["tick"]), []).append((int(fan), int(power)))
        elif action == "launch":
            if launched or item.get("tick") != 0:
                return _fail("dual launch duplicated or late")
            launched = True
        elif action == "gate_pass":
            gate_reports.append(item)
        elif action == "dock":
            dock_reports.append(item)
        elif action == "terminal":
            if terminal is not None:
                return _fail("duplicate wind terminal")
            terminal = item
        else:
            return _fail(f"unknown wind event {action!r}")
    if not launched:
        return _fail("pods were never launched")

    physics = public["physics"]
    powers = [0 for _ in public["fans"]]
    actual = [0.0 for _ in public["fans"]]
    heat = [0.0 for _ in public["fans"]]
    pods = [{**item, "x": float(item["x"]), "y": float(item["y"]), "vx": float(item["vx"]), "vy": float(item["vy"]), "docked": False} for item in public["pods"]]
    passed = {pod["id"]: [] for pod in pods}
    replay_gates: list[dict[str, Any]] = []
    replay_docks: list[dict[str, Any]] = []
    completion_tick = None
    for tick in range(int(physics["ticks"])):
        for fan, power in schedule.get(tick, []):
            powers[fan] = power
        before_x = {pod["id"]: pod["x"] for pod in pods}
        accelerations = [
            .006 * math.sin(tick * .083 + float(physics["phase"]) + float(pod["gust_phase"]))
            for pod in pods
        ]
        for index, fan in enumerate(public["fans"]):
            heat[index] = max(0.0, heat[index] + (float(physics["heat_rate"]) if powers[index] else -float(physics["cool_rate"])))
            if heat[index] >= float(physics["trip_heat"]):
                return _fail(f"thermal trip at fan-{index + 1}")
            actual[index] += (powers[index] - actual[index]) * float(physics["spool_rate"])
            for pod_index, pod in enumerate(pods):
                if pod["docked"]:
                    continue
                influence = max(0.0, 1.0 - abs(pod["x"] - float(fan["x"])) / float(fan["radius"]))
                accelerations[pod_index] += actual[index] * float(physics["fan_accel"]) * float(pod["response"]) * influence
        current_tick = tick + 1
        for pod_index, pod in enumerate(pods):
            if pod["docked"]:
                continue
            pod["vy"] = (pod["vy"] + accelerations[pod_index]) * float(physics["drag"])
            pod["y"] = max(35.0, min(441.0, pod["y"] + pod["vy"]))
            pod["x"] += pod["vx"]
            next_gate = public["gates"][len(passed[pod["id"]])] if len(passed[pod["id"]]) < len(public["gates"]) else None
            if next_gate and before_x[pod["id"]] < float(next_gate["x"]) <= pod["x"]:
                slot = next(item for item in next_gate["slots"] if item["pod_id"] == pod["id"])
                center = _gate_y(slot, current_tick)
                if abs(pod["y"] - center) + float(physics["pod_radius"]) > float(slot["half_gap"]):
                    return _fail(f"{pod['id']} collided at {next_gate['id']}")
                passed[pod["id"]].append(next_gate["id"])
                replay_gates.append({"tick": current_tick, "pod_id": pod["id"], "gate_id": next_gate["id"], "gate_y": center, "y": pod["y"], "vy": pod["vy"]})
            dock = next(item for item in public["docks"] if item["pod_id"] == pod["id"])
            if before_x[pod["id"]] < float(dock["x"]) <= pod["x"]:
                if len(passed[pod["id"]]) != len(public["gates"]) or math.hypot(pod["x"] - float(dock["x"]), pod["y"] - float(dock["y"])) > float(dock["radius"]) + 4:
                    return _fail(f"{pod['id']} missed its dock")
                pod["docked"] = True
                pod["x"] = float(dock["x"])
                replay_docks.append({"tick": current_tick, "pod_id": pod["id"], "pod": dict(pod), "gates": list(passed[pod["id"]])})
        if all(pod["docked"] for pod in pods):
            completion_tick = current_tick
            break
    if completion_tick is None:
        return _fail("one or both pods never docked")
    if len(gate_reports) != len(replay_gates) or len(dock_reports) != len(replay_docks):
        return _fail("visible crossing ledger disagrees with dual-body replay")
    for reported, replayed in zip(gate_reports, replay_gates, strict=True):
        if reported.get("tick") != replayed["tick"] or reported.get("pod_id") != replayed["pod_id"] or reported.get("gate_id") != replayed["gate_id"]:
            return _fail("gate report bound to wrong pod, gate, or tick")
        if any(not _close(reported.get(key), replayed[key]) for key in ("gate_y", "y", "vy")):
            return _fail("gate telemetry disagrees with replay")
    for reported, replayed in zip(dock_reports, replay_docks, strict=True):
        if reported.get("tick") != replayed["tick"] or reported.get("pod_id") != replayed["pod_id"] or reported.get("gates") != replayed["gates"] or not _same_pod(reported.get("pod") or {}, replayed["pod"]):
            return _fail("dock ledger disagrees with replay")
    expected_gates = {pod["id"]: list(passed[pod["id"]]) for pod in pods}
    if not isinstance(terminal, dict) or terminal.get("passed") is not True or terminal.get("tick") != completion_tick or terminal.get("gates") != expected_gates:
        return _fail("successful terminal ledger missing or false")
    reported_pods = terminal.get("pods")
    if not isinstance(reported_pods, list) or len(reported_pods) != len(pods) or any(not _same_pod(first, second) for first, second in zip(reported_pods, pods, strict=True)):
        return _fail("terminal pod states disagree with replay")
    accepted = payload.get("completed") is True
    return {"graded": True, "passed": accepted, "feedback": "shared thermal plant replay cleared eight apertures and both differentiated pod docks" if accepted else "completion flag missing"}
