from __future__ import annotations

import math
from typing import Any


MECHANIC_ID = "impossible_ecology_nonrealtime"


def _round(value: float, digits: int = 6) -> float:
    return round(float(value) + 1e-12, digits)


def _point(value: Any, arena: dict[str, Any]) -> list[float]:
    if not isinstance(value, list) or len(value) != 2 or any(isinstance(item, bool) for item in value):
        raise ValueError("field point is malformed")
    point = [float(value[0]), float(value[1])]
    if not (math.isfinite(point[0]) and math.isfinite(point[1]) and 0 <= point[0] <= float(arena["width"]) and 0 <= point[1] <= float(arena["height"])):
        raise ValueError("field point leaves arena")
    return point


def _initial_organisms(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    fields = set(contract["fields"])
    for raw in contract["organisms"]:
        organism_id = str(raw["id"])
        responses = {str(key): float(value) for key, value in raw["responses"].items()}
        if not organism_id or organism_id in result or set(responses) != fields:
            raise ValueError("organism response contract is malformed")
        result[organism_id] = {
            "id": organism_id,
            "radius": float(raw["radius"]),
            "responses": responses,
            "current_seed": int(raw["current_seed"]),
            "x": float(raw["initial_position"][0]), "y": float(raw["initial_position"][1]),
            "vx": 0.0, "vy": 0.0, "captured": False,
        }
    if not 2 <= len(result) <= 6:
        raise ValueError("coupled ecology must contain two through six organisms")
    return result


def _targets(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {str(item["organism_id"]): item for item in contract["targets"]}
    if len(result) != len(contract["organisms"]):
        raise ValueError("sanctuary contract is malformed")
    return result


def _resolve_obstacle(organism: dict[str, Any], next_point: list[float], obstacle: dict[str, Any]) -> list[float]:
    dx = next_point[0] - float(obstacle["center"][0]); dy = next_point[1] - float(obstacle["center"][1])
    size = math.hypot(dx, dy); minimum = float(obstacle["radius"]) + organism["radius"]
    if size >= minimum:
        return next_point
    ux, uy = (dx / size, dy / size) if size > 1e-9 else (1.0, 0.0)
    inward = organism["vx"] * ux + organism["vy"] * uy
    if inward < 0:
        organism["vx"] -= 1.55 * inward * ux
        organism["vy"] -= 1.55 * inward * uy
    return [float(obstacle["center"][0]) + ux * minimum, float(obstacle["center"][1]) + uy * minimum]


def _current(seed: int, tick: int, controls: dict[str, Any]) -> tuple[float, float]:
    """Smooth seeded current with no finite motion tape or replay period."""
    segment = int(controls["current_segment_ticks"])
    index, offset = divmod(tick, segment)

    def direction(k: int) -> float:
        value = (seed ^ ((k + 1) * 0x9E3779B1)) & 0xFFFFFFFF
        value = ((value ^ (value >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
        value = ((value ^ (value >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
        value ^= value >> 16
        return value / 4294967296 * math.tau

    start, finish = direction(index), direction(index + 1)
    delta = (finish - start + math.pi) % math.tau - math.pi
    fraction = offset / segment
    blend = fraction**3 * (10 + fraction * (-15 + 6 * fraction))
    angle = start + delta * blend
    magnitude = float(controls["current_acceleration"])
    return magnitude * math.cos(angle), magnitude * math.sin(angle)


def _advance(organisms: dict[str, dict[str, Any]], targets: dict[str, dict[str, Any]], contract: dict[str, Any], active: bool, selected: str | None, lure: list[float], tick: int) -> None:
    controls, arena, obstacle = contract["controls"], contract["arena"], contract["obstacle"]
    for organism in organisms.values():
        if organism["captured"]:
            continue
        ax, ay = _current(organism["current_seed"], tick, controls)
        organism["vx"] += ax
        organism["vy"] += ay
        if active and selected:
            dx, dy = lure[0] - organism["x"], lure[1] - organism["y"]
            size = math.hypot(dx, dy)
            if size > 1e-9:
                acceleration = organism["responses"][selected]
                organism["vx"] += dx / size * acceleration
                organism["vy"] += dy / size * acceleration
        organism["vx"] *= float(controls["damping"])
        organism["vy"] *= float(controls["damping"])
        speed = math.hypot(organism["vx"], organism["vy"])
        if speed > float(controls["max_speed"]):
            organism["vx"] = organism["vx"] / speed * float(controls["max_speed"])
            organism["vy"] = organism["vy"] / speed * float(controls["max_speed"])
        next_point = _resolve_obstacle(organism, [organism["x"] + organism["vx"], organism["y"] + organism["vy"]], obstacle)
        low = float(arena["margin"]) + organism["radius"]
        high_x = float(arena["width"]) - float(arena["margin"]) - organism["radius"]
        high_y = float(arena["height"]) - float(arena["margin"]) - organism["radius"]
        if next_point[0] < low or next_point[0] > high_x:
            next_point[0] = max(low, min(high_x, next_point[0])); organism["vx"] *= -.35
        if next_point[1] < low or next_point[1] > high_y:
            next_point[1] = max(low, min(high_y, next_point[1])); organism["vy"] *= -.35
        organism["x"] = _round(next_point[0]); organism["y"] = _round(next_point[1])
        organism["vx"] = _round(organism["vx"]); organism["vy"] = _round(organism["vy"])
        target = targets[organism["id"]]
        capture_radius = float(target["radius"]) - organism["radius"] - float(controls["capture_margin"])
        if math.dist([organism["x"], organism["y"]], [float(value) for value in target["center"]]) <= capture_radius and math.hypot(organism["vx"], organism["vy"]) <= float(controls["capture_speed"]):
            organism["x"], organism["y"] = [float(value) for value in target["center"]]
            organism["vx"] = organism["vy"] = 0.0; organism["captured"] = True


def _snapshot(organisms: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": item["id"], "position": [_round(item["x"], 3), _round(item["y"], 3)], "velocity": [_round(item["vx"], 3), _round(item["vy"], 3)], "captured": item["captured"]} for item in sorted(organisms.values(), key=lambda value: value["id"])]


def _snapshot_matches(claimed: Any, expected: list[dict[str, Any]], tolerance: float = .035) -> bool:
    if not isinstance(claimed, list) or len(claimed) != len(expected):
        return False
    for actual, wanted in zip(claimed, expected):
        if not isinstance(actual, dict) or actual.get("id") != wanted["id"] or actual.get("captured") is not wanted["captured"]:
            return False
        for field in ("position", "velocity"):
            values = actual.get(field)
            if not isinstance(values, list) or len(values) != 2 or any(isinstance(item, bool) or not math.isfinite(float(item)) for item in values):
                return False
            if math.dist([float(item) for item in values], wanted[field]) > tolerance:
                return False
    return True


def grade(payload: dict[str, Any], ground_truth: dict[str, Any], public_state: dict[str, Any]) -> dict[str, Any]:
    challenge_id, task_id = str(ground_truth.get("challenge_id") or ""), str(ground_truth.get("task_id") or "")
    if str(payload.get("mechanic_id") or "") != MECHANIC_ID or str(ground_truth.get("mechanic_id") or "") != MECHANIC_ID:
        return {"graded": True, "passed": False, "feedback": "mechanic mismatch"}
    if not challenge_id or str(payload.get("challenge_id") or "") != challenge_id or str(public_state.get("challenge_id") or "") != challenge_id:
        return {"graded": True, "passed": False, "feedback": "stale challenge"}
    if not task_id or str(payload.get("task_id") or "") != task_id:
        return {"graded": True, "passed": False, "feedback": "task identity mismatch"}
    for field in ("arena", "fields", "organisms", "targets", "obstacle", "controls"):
        if public_state.get(field) != ground_truth.get(field):
            return {"graded": True, "passed": False, "feedback": f"public/private ecology {field} contract skew"}
    condition = ground_truth.get("control_condition")
    if condition != public_state.get("control_condition"):
        return {"graded": True, "passed": False, "feedback": "public/private ecology control condition skew"}
    interaction = str((condition or {}).get("interaction") or "full")
    expected_input_source = {"simplified": "coordinate_pad", "full": "arena_pointer"}.get(interaction)
    if expected_input_source is None:
        return {"graded": True, "passed": False, "feedback": "ecology interaction condition is invalid"}
    if condition is not None:
        if payload.get("control_condition") != condition:
            return {"graded": True, "passed": False, "feedback": "submitted ecology control condition differs from the task"}
        if str(payload.get("interaction") or "") != interaction:
            return {"graded": True, "passed": False, "feedback": "submitted ecology interaction differs from the task"}
    try:
        organisms = _initial_organisms(ground_truth)
        targets = _targets(ground_truth)
        arena = ground_truth["arena"]
        fields = [str(item) for item in ground_truth["fields"]]
    except (KeyError, TypeError, ValueError) as exc:
        return {"graded": True, "passed": False, "feedback": f"invalid ecology contract: {exc}"}

    events = payload.get("events")
    if not isinstance(events, list) or not (1 <= len(events) <= 250000):
        return {"graded": True, "passed": False, "feedback": "ecology transcript is missing or outside limits"}
    selected: str | None = None
    lure = [float(arena["width"]) / 2, float(arena["height"]) / 2]
    active = completed = terminal = False
    tick = field_selections = pointer_drags = calibration_runs = resets = 0
    step_pending = False

    for sequence, event in enumerate(events, start=1):
        if terminal:
            return {"graded": True, "passed": False, "feedback": "interaction continued after all sanctuaries locked"}
        if not isinstance(event, dict) or event.get("sequence") != sequence:
            return {"graded": True, "passed": False, "feedback": f"event {sequence} sequence mismatch"}
        kind = str(event.get("kind") or "")
        if kind == "calibration":
            if active or step_pending or event.get("tick") != tick or event.get("fields") != fields:
                return {"graded": True, "passed": False, "feedback": "calibration film event is malformed"}
            calibration_runs += 1
            continue
        if kind == "field_select":
            field = str(event.get("field") or "")
            if active or step_pending or field not in fields or event.get("tick") != tick:
                return {"graded": True, "passed": False, "feedback": "field selection is malformed"}
            selected = field; field_selections += 1
            continue
        if kind in {"pointer_down", "pointer_move", "pointer_up"}:
            if step_pending:
                return {"graded": True, "passed": False, "feedback": "pointer event arrived before its physics tick"}
            try:
                point = _point(event.get("point"), arena)
            except ValueError as exc:
                return {"graded": True, "passed": False, "feedback": f"event {sequence}: {exc}"}
            if event.get("tick") != tick or str(event.get("field") or "") != selected or selected not in fields:
                return {"graded": True, "passed": False, "feedback": f"event {sequence} uses stale field/tick state"}
            if condition is not None and event.get("input_source") != expected_input_source:
                return {"graded": True, "passed": False, "feedback": f"event {sequence} uses the wrong interaction input"}
            if event.get("proxy") is not None:
                return {"graded": True, "passed": False, "feedback": "field-lure coordinates cannot use a guidance proxy"}
            if kind == "pointer_down":
                if active:
                    return {"graded": True, "passed": False, "feedback": "pointer field was pressed twice"}
                active = True; pointer_drags += 1; step_pending = True
            elif kind == "pointer_move":
                if not active:
                    return {"graded": True, "passed": False, "feedback": "field pointer moved while released"}
                step_pending = True
            else:
                if not active:
                    return {"graded": True, "passed": False, "feedback": "field pointer released while inactive"}
                active = False; step_pending = True
            lure = point
            continue
        if kind == "reset":
            if active or step_pending or completed:
                return {"graded": True, "passed": False, "feedback": "ecology reset during active/terminal field"}
            organisms = _initial_organisms(ground_truth); selected = None
            lure = [float(arena["width"]) / 2, float(arena["height"]) / 2]; tick = 0; resets += 1; step_pending = False
            continue
        if kind == "physics_tick":
            if not step_pending:
                return {"graded": True, "passed": False, "feedback": "physics tick was not caused by a deliberate pointer action"}
            if event.get("tick") != tick + 1:
                return {"graded": True, "passed": False, "feedback": "physics tick skipped or reversed"}
            if event.get("active") is not active or event.get("field") != (selected if active else None):
                return {"graded": True, "passed": False, "feedback": "physics tick field state disagrees with replay"}
            try:
                claimed_lure = _point(event.get("lure"), arena)
            except ValueError:
                return {"graded": True, "passed": False, "feedback": "physics tick lure is malformed"}
            if active and math.dist(claimed_lure, lure) > .01:
                return {"graded": True, "passed": False, "feedback": f"physics tick {tick + 1} lure moved without a pointer event: claimed={claimed_lure}, replay={lure}, event={sequence}"}
            if not active:
                # Hover motion is visually useful while inertia decays but has
                # no physical effect until the next recorded pointer-down.
                lure = claimed_lure
            tick += 1
            step_pending = False
            _advance(organisms, targets, ground_truth, active, selected, lure, tick)
            if not _snapshot_matches(event.get("organisms"), _snapshot(organisms)):
                return {"graded": True, "passed": False, "feedback": f"physics tick {tick} fabricates coupled organism motion"}
            continue
        if kind == "complete":
            if completed or event.get("tick") != tick or not all(item["captured"] for item in organisms.values()):
                return {"graded": True, "passed": False, "feedback": "completion lacks physically captured organisms"}
            completed = terminal = True
            continue
        return {"graded": True, "passed": False, "feedback": f"event {sequence} has unknown kind"}

    expected = _snapshot(organisms)
    if not _snapshot_matches(payload.get("final_organisms"), expected):
        return {"graded": True, "passed": False, "feedback": "submitted final organisms disagree with physics replay"}
    expected_scalars = {"tick": tick, "completed": completed, "field_selections": field_selections, "pointer_drags": pointer_drags, "calibration_runs": calibration_runs, "resets": resets}
    for field, value in expected_scalars.items():
        if payload.get(field) != value:
            return {"graded": True, "passed": False, "feedback": f"submitted {field} disagrees with ecology replay"}
    captured = sum(item["captured"] for item in organisms.values())
    passed = completed and captured == len(organisms) and pointer_drags > 0
    return {
        "graded": True,
        "passed": passed,
        "score": 100 if passed else 0,
        "feedback": f"coupled ecology replay: sanctuaries {captured}/{len(organisms)}; field selections {field_selections}; pointer interventions {pointer_drags}; ticks {tick}; resets {resets}",
    }


def cheat(public_state: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    del public_state
    return {"organisms": ground_truth.get("organisms") or [], "targets": ground_truth.get("targets") or [], "answers": []}
