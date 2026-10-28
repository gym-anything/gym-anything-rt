from __future__ import annotations

import math
from typing import Any


MECHANIC_ID = "board_game_captcha_nonrealtime"
COMPASS_TILTS = {
    (-0.71, -0.71), (0.0, -1.0), (0.71, -0.71),
    (-1.0, 0.0), (0.0, 0.0), (1.0, 0.0),
    (-0.71, 0.71), (0.0, 1.0), (0.71, 0.71),
}


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "score": 0, "feedback": message}


def _round(value: float) -> float:
    return math.floor(float(value) * 100.0 + 0.5) / 100.0


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} is not finite")
    return float(value)


def _pair(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} is malformed")
    return [_round(_number(value[0], f"{label} x")), _round(_number(value[1], f"{label} y"))]


def _same_pair(value: Any, expected: list[float]) -> bool:
    try:
        actual = _pair(value, "reported vector")
    except ValueError:
        return False
    return all(abs(a - b) <= 0.011 for a, b in zip(actual, expected))


def _external_tilt(contract: dict[str, Any], tick_index: int) -> list[float]:
    del tick_index
    fixed = contract["physics"].get("fixed_tilt")
    if fixed is not None:
        return [_round(value) for value in fixed]
    return [0.0, 0.0]


def _hole_gravity(contract: dict[str, Any], position: list[float]) -> tuple[list[float], str | None]:
    strength = contract["physics"].get("hole_gravity")
    if strength is None:
        return [0.0, 0.0], None
    # Stable list order breaks exact distance ties, matching the browser.
    nearest = min(contract["hazards"], key=lambda well: math.dist(position, well["position"]))
    dx, dy = nearest["position"][0] - position[0], nearest["position"][1] - position[1]
    distance = math.hypot(dx, dy)
    vector = [strength * dx / distance, strength * dy / distance] if distance else [0.0, 0.0]
    return vector, nearest["id"]


def _tick(state: dict[str, Any], tilt: list[float], contract: dict[str, Any], *, tick_index: int = 0) -> dict[str, Any]:
    physics = contract["physics"]
    external = _external_tilt(contract, tick_index)
    gravity, _ = _hole_gravity(contract, state["position"])
    tilt = [tilt[0] + external[0] + gravity[0], tilt[1] + external[1] + gravity[1]]
    dt = float(physics["tick_ms"]) / 1000.0
    velocity = state["velocity"][:]
    position = state["position"][:]
    velocity[0] = _round((velocity[0] + tilt[0] * float(physics["acceleration"]) * dt) * float(physics["friction"]))
    velocity[1] = _round((velocity[1] + tilt[1] * float(physics["acceleration"]) * dt) * float(physics["friction"]))
    speed = math.hypot(*velocity)
    maximum = float(physics["maximum_speed"])
    if speed > maximum:
        velocity = [_round(velocity[0] / speed * maximum), _round(velocity[1] / speed * maximum)]
    candidate = [_round(position[0] + velocity[0] * dt), _round(position[1] + velocity[1] * dt)]
    radius = float(physics["ball_radius"])
    bounce = float(physics["bounce"])
    hits: list[str] = []
    width, height = float(contract["stage"]["width"]), float(contract["stage"]["height"])
    edge_id = None
    if candidate[0] < radius:
        edge_id = "edge-left"
    elif candidate[0] > width - radius:
        edge_id = "edge-right"
    elif candidate[1] < radius:
        edge_id = "edge-top"
    elif candidate[1] > height - radius:
        edge_id = "edge-bottom"

    for wall in contract["walls"]:
        left, right = float(wall["x"]) - radius, float(wall["x"]) + float(wall["width"]) + radius
        top, bottom = float(wall["y"]) - radius, float(wall["y"]) + float(wall["height"]) + radius
        if not left <= candidate[0] <= right or not top <= candidate[1] <= bottom:
            continue
        if position[0] < left:
            candidate[0], velocity[0] = left, _round(-abs(velocity[0]) * bounce)
        elif position[0] > right:
            candidate[0], velocity[0] = right, _round(abs(velocity[0]) * bounce)
        elif position[1] < top:
            candidate[1], velocity[1] = top, _round(-abs(velocity[1]) * bounce)
        elif position[1] > bottom:
            candidate[1], velocity[1] = bottom, _round(abs(velocity[1]) * bounce)
        else:
            options = [(candidate[0] - left, "left"), (right - candidate[0], "right"), (candidate[1] - top, "top"), (bottom - candidate[1], "bottom")]
            side = min(options, key=lambda item: item[0])[1]
            if side == "left": candidate[0], velocity[0] = left, _round(-abs(velocity[0]) * bounce)
            elif side == "right": candidate[0], velocity[0] = right, _round(abs(velocity[0]) * bounce)
            elif side == "top": candidate[1], velocity[1] = top, _round(-abs(velocity[1]) * bounce)
            else: candidate[1], velocity[1] = bottom, _round(abs(velocity[1]) * bounce)
        hits.append(str(wall["id"]))

    hazard_id = edge_id
    for hazard in contract["hazards"]:
        if math.hypot(candidate[0] - float(hazard["position"][0]), candidate[1] - float(hazard["position"][1])) <= radius + float(hazard["radius"]):
            hazard_id = str(hazard["id"])
            break
    activated_id = None
    completed = False
    if hazard_id:
        candidate = [_round(value) for value in contract["start"]]
        velocity = [0.0, 0.0]
        state["switch_index"] = 0
        state["deaths"] += 1
    else:
        if state["switch_index"] < len(contract["switches"]):
            switch = contract["switches"][state["switch_index"]]
            if math.hypot(candidate[0] - float(switch["position"][0]), candidate[1] - float(switch["position"][1])) <= radius + float(switch["radius"]):
                activated_id = str(switch["id"])
                state["switch_index"] += 1
        if state["switch_index"] == len(contract["switches"]):
            goal = contract["goal"]
            if math.hypot(candidate[0] - float(goal["position"][0]), candidate[1] - float(goal["position"][1])) <= radius + float(goal["radius"]):
                completed = True
                velocity = [0.0, 0.0]
    state["position"] = [_round(value) for value in candidate]
    state["velocity"] = [_round(value) for value in velocity]
    state["collisions"] += len(hits)
    state["completed"] = completed
    return {"wall_hits": hits, "hazard_id": hazard_id, "activated_id": activated_id, "completed": completed}


def grade(payload: dict[str, Any], ground_truth: dict[str, Any], public_state: dict[str, Any]) -> dict[str, Any]:
    challenge = str(ground_truth.get("challenge_id") or "")
    task_id = str(ground_truth.get("task_id") or "")
    if any(str(item.get("mechanic_id") or "") != MECHANIC_ID for item in (payload, ground_truth, public_state)):
        return _fail("mechanic mismatch")
    if not challenge or str(payload.get("challenge_id") or "") != challenge or str(public_state.get("challenge_id") or "") != challenge:
        return _fail("stale tilt-board challenge")
    if not task_id or str(payload.get("task_id") or "") != task_id or str(public_state.get("task_id") or "") != task_id:
        return _fail("task identity mismatch")
    truth_condition = ground_truth.get("control_condition")
    public_condition = public_state.get("control_condition")
    if truth_condition != public_condition:
        return _fail("public interaction condition differs from replay contract")
    interaction = str((truth_condition or {}).get("interaction") or "")
    if truth_condition is not None and interaction not in {"simplified", "full"}:
        return _fail("tilt-board interaction condition is invalid")
    expected_input_source = {"simplified": "compass_button", "full": "analog_drag"}.get(interaction)
    try:
        contract = {key: ground_truth[key] for key in ("stage", "start", "goal", "switches", "walls", "hazards", "physics", "requirements")}
        for key in contract:
            if public_state.get(key) != contract[key]:
                raise ValueError(f"public {key} differs from replay contract")
        if not 1 <= len(contract["switches"]) <= 5 or not 20 <= int(contract["physics"]["tick_ms"]) <= 100:
            raise ValueError("board physics contract is incomplete")
        action_ticks = int(contract["requirements"]["ticks_per_action"])
        if not 1 <= action_ticks <= 32:
            raise ValueError("action settlement batch is outside supported limits")
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"invalid tilt-board contract: {exc}")
    events = payload.get("events")
    if not isinstance(events, list) or not (1 <= len(events) <= int(contract["requirements"]["maximum_events"])):
        return _fail("tilt-board transcript is missing or outside limits")
    state = {"position": [_round(value) for value in contract["start"]], "velocity": [0.0, 0.0], "switch_index": 0, "deaths": 0, "collisions": 0, "completed": False}
    tilt = [0.0, 0.0]
    ticks = controls = manual_resets = seal_count = 0
    last_time = -1.0
    pending_ticks = 0

    for sequence, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("sequence") != sequence:
            return _fail(f"event {sequence} has invalid sequence")
        kind = str(event.get("kind") or "")
        try:
            event_time = _number(event.get("t_ms"), "event time")
            if event_time < last_time or event_time > float(contract["requirements"]["maximum_event_time_ms"]):
                return _fail(f"event {sequence} has impossible time")
            last_time = event_time
            if state["completed"] and kind != "seal":
                return _fail(f"event {sequence} continues physics after the cup locked")
            if kind == "tilt_change":
                if pending_ticks:
                    return _fail(f"event {sequence} changes tilt before the prior action settled")
                before, after = _pair(event.get("from"), "old tilt"), _pair(event.get("to"), "new tilt")
                if before != tilt or math.hypot(*after) > 1.011:
                    return _fail(f"event {sequence} reports an invalid tilt vector")
                if expected_input_source is not None and event.get("input_source") != expected_input_source:
                    return _fail(f"event {sequence} uses the wrong interaction input")
                if interaction == "simplified" and tuple(after) not in COMPASS_TILTS:
                    return _fail(f"event {sequence} reports a non-compass simplified tilt")
                tilt = after
                controls += 1
                pending_ticks = action_ticks
            elif kind == "physics_tick":
                if pending_ticks <= 0:
                    return _fail(f"event {sequence} contains physics without a deliberate tilt action")
                if int(event.get("dt_ms")) != int(contract["physics"]["tick_ms"]) or not _same_pair(event.get("tilt"), tilt):
                    return _fail(f"event {sequence} changes the physics clock or control")
                before = event.get("before") or {}
                if not _same_pair(before.get("position"), state["position"]) or not _same_pair(before.get("velocity"), state["velocity"]):
                    return _fail(f"event {sequence} begins from fabricated ball state")
                if "fixed_tilt" in contract["physics"] and not _same_pair(event.get("external_tilt"), _external_tilt(contract, ticks)):
                    return _fail(f"event {sequence} misreports fixed board tilt")
                if "hole_gravity" in contract["physics"]:
                    gravity, well_id = _hole_gravity(contract, state["position"])
                    if event.get("gravity_well_id") != well_id or not _same_pair(event.get("gravity_tilt"), gravity):
                        return _fail(f"event {sequence} misreports hole gravity")
                outcome = _tick(state, tilt, contract, tick_index=ticks)
                after = event.get("after") or {}
                if not _same_pair(after.get("position"), state["position"]) or not _same_pair(after.get("velocity"), state["velocity"]):
                    return _fail(f"event {sequence} disagrees with deterministic collision physics")
                for key in ("wall_hits", "hazard_id", "activated_id", "completed"):
                    if event.get(key) != outcome[key]:
                        return _fail(f"event {sequence} misreports {key}")
                ticks += 1
                pending_ticks -= 1
                if outcome["completed"]:
                    pending_ticks = 0
            elif kind == "manual_reset":
                if pending_ticks:
                    return _fail(f"event {sequence} resets before the prior action settled")
                state = {"position": [_round(value) for value in contract["start"]], "velocity": [0.0, 0.0], "switch_index": 0, "deaths": state["deaths"], "collisions": state["collisions"], "completed": False}
                tilt = [0.0, 0.0]
                manual_resets += 1
            elif kind == "seal":
                if pending_ticks:
                    return _fail(f"event {sequence} seals before the prior action settled")
                seal_count += 1
            else:
                return _fail(f"event {sequence} has unknown kind {kind!r}")
        except (TypeError, ValueError) as exc:
            return _fail(f"event {sequence}: {exc}")
    if pending_ticks:
        return _fail("transcript ends before a deliberate action settled")
    expected = {
        "final_position": state["position"], "final_velocity": state["velocity"], "switch_index": state["switch_index"],
        "deaths": state["deaths"], "collisions": state["collisions"], "manual_resets": manual_resets,
        "tick_count": ticks, "control_changes": controls, "seal_count": seal_count,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            return _fail(f"submitted {key} does not match tilt-board replay")
    lamp_count = len(contract["switches"])
    passed = payload.get("completed") is True and state["completed"] and state["switch_index"] == lamp_count and seal_count >= 1
    return {"graded": True, "passed": passed, "score": 100 if passed else 0, "feedback": f"tilt replay: ticks {ticks}; controls {controls}; lamps {state['switch_index']}/{lamp_count}; wall contacts {state['collisions']}; wells {state['deaths']}; manual resets {manual_resets}; cup={state['completed']}"}


def cheat(public_state: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    del public_state
    return {"waypoints": ground_truth.get("solver_waypoints") or [], "answers": []}
