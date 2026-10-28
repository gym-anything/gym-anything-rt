from __future__ import annotations

import math
from typing import Any


MECHANIC_ID = "microgame_gauntlet"


def _close(first: Any, second: Any, tolerance: float = 0.04) -> bool:
    try:
        return abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def _angle_delta(current: float, previous: float) -> float:
    return (current - previous + 540.0) % 360.0 - 180.0


def _angle_distance(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _close_angle(first: Any, second: Any, tolerance: float = 0.04) -> bool:
    try:
        return _angle_distance(float(first), float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def _events(record: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw = record.get("events")
    if not isinstance(raw, list) or not raw:
        return None
    for sequence, event in enumerate(raw, start=1):
        if not isinstance(event, dict) or event.get("sequence") != sequence or not event.get("action"):
            return None
    return raw


def _grade_pressure(round_data: dict[str, Any], events: list[dict[str, Any]]) -> str | None:
    pulse_ids = [str(pulse["id"]) for pulse in round_data.get("pulses") or []]
    expected_actions = ["space_down", *("pulse_click" for _ in pulse_ids), "space_up"]
    if [event.get("action") for event in events] != expected_actions:
        return "pressure transcript does not preserve the continuous hold"
    if [str(event.get("pulse_id") or "") for event in events[1:-1]] != pulse_ids:
        return "pressure pulses were not clicked in order"
    return None


def _grade_chord(round_data: dict[str, Any], events: list[dict[str, Any]]) -> str | None:
    chords = [
        {str(key).upper() for key in chord}
        for chord in round_data.get("chords") or []
    ]
    if not chords or any(len(chord) != 2 for chord in chords):
        return "magnetic chord contract is malformed"
    stage = 0
    held: set[str] = set()
    tick_count = 0
    for event in events:
        if stage >= len(chords) or event.get("chord_index") != stage:
            return "chord event targets the wrong stage"
        required = chords[stage]
        action = event.get("action")
        key = str(event.get("key") or "").upper()
        if action == "key_down":
            if key not in required or key in held:
                return "chord key-down sequence is invalid"
            held.add(key)
        elif action == "hold_tick":
            if held != required or sorted(str(key).upper() for key in event.get("keys") or []) != sorted(required):
                return "chord tick occurred without both keys held"
            tick_count += 1
        elif action == "key_up":
            if key not in held:
                return "chord key-up sequence is invalid"
            held.remove(key)
            if not held:
                if tick_count < int(round_data.get("required_ticks") or 0):
                    return "magnetic chord was released before it charged"
                stage += 1
                tick_count = 0
        else:
            return "chord transcript has an unknown action"
    if held or stage != len(chords):
        return "all three magnetic chords were not held and released completely"
    return None


def _grade_dial(round_data: dict[str, Any], events: list[dict[str, Any]]) -> str | None:
    if events[0].get("action") != "drag_start" or events[-1].get("action") != "brake":
        return "dial transcript must start with a drag and end with the brake"
    try:
        angle = float(events[0]["angle"]) % 360.0
    except (KeyError, TypeError, ValueError):
        return "dial start angle is invalid"
    move_count = 0
    tick_count = 0
    velocity = 0.0
    drag_ended = False
    friction = float(round_data.get("friction") or 0.92)
    for event in events[1:]:
        action = event.get("action")
        if action == "drag_move" and not drag_ended:
            try:
                next_angle = float(event["angle"]) % 360.0
                claimed_delta = float(event["delta"])
            except (KeyError, TypeError, ValueError):
                return "dial drag event is malformed"
            delta = _angle_delta(next_angle, angle)
            if not _close(claimed_delta, delta):
                return "dial drag delta disagrees with pointer geometry"
            angle = next_angle
            velocity = max(-18.0, min(18.0, delta))
            move_count += 1
        elif action == "drag_end" and not drag_ended:
            drag_ended = True
            if not _close_angle(event.get("angle"), angle) or not _close(event.get("velocity"), velocity):
                return "dial release state disagrees with drag replay"
            if abs(velocity) < 2.5:
                return "dial was released without meaningful inertia"
        elif action == "dial_tick" and drag_ended:
            angle = (angle + velocity) % 360.0
            velocity *= friction
            if not _close_angle(event.get("angle"), angle) or not _close(event.get("velocity"), velocity):
                return "dial coast tick disagrees with inertia replay"
            tick_count += 1
        elif action == "brake" and drag_ended:
            if event is not events[-1] or not _close_angle(event.get("angle"), angle):
                return "dial brake angle disagrees with replay"
        else:
            return "dial transcript contains an invalid state transition"
    if move_count < 2 or tick_count < 1:
        return "dial needs a real multi-sample drag and coast"
    if _angle_distance(angle, float(round_data["target_angle"])) > float(round_data["target_tolerance"]):
        return "dial was braked outside the target sector"
    return None


def _grade_intercept(round_data: dict[str, Any], events: list[dict[str, Any]]) -> str | None:
    packets = [dict(packet) for packet in round_data.get("packets") or []]
    if not packets or events[0].get("action") != "arm":
        return "moving intercept transcript must begin with one arm action"
    position = 8.0
    direction = 1
    tick_count = 0
    packet_index = 0
    for event in events[1:]:
        if packet_index >= len(packets):
            return "intercept transcript continues after the final packet"
        packet = packets[packet_index]
        if event.get("packet_index") != packet_index or event.get("packet_id") != packet.get("id"):
            return "intercept event targets the wrong moving packet"
        if event.get("action") == "intercept_tick":
            position += float(packet["speed"]) * direction
            if position >= 92:
                position, direction = 92.0, -1
            elif position <= 8:
                position, direction = 8.0, 1
            if not _close(event.get("position"), position) or int(event.get("direction") or 0) != direction:
                return "moving packet tick disagrees with deterministic track"
            tick_count += 1
        elif event.get("action") == "intercept_click":
            if not _close(event.get("position"), position):
                return "intercept click position disagrees with the moving packet"
            if tick_count < 2:
                return "moving packet was clicked without observation ticks"
            if abs(position - float(packet["gate_center"])) > float(packet["gate_half_width"]):
                return "moving packet was outside its capture gate"
            packet_index += 1
            position, direction, tick_count = 8.0, 1, 0
        else:
            return "intercept transcript contains an unknown action"
    if packet_index != len(packets):
        return "all moving packets were not intercepted"
    return None


def _distance_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    amount = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + amount * dx), py - (ay + amount * dy))


def _grade_route(round_data: dict[str, Any], events: list[dict[str, Any]]) -> str | None:
    if events[0].get("action") != "route_start" or events[-1].get("action") != "route_end":
        return "route transcript must include pointer down and pointer up"
    points = [(float(point["x"]), float(point["y"])) for point in round_data.get("points") or []]
    if len(points) < 4:
        return "route contract is malformed"
    radius = float(round_data.get("checkpoint_radius") or 8)
    corridor = float(round_data.get("corridor_radius") or 13)
    checkpoint = 0
    move_count = 0
    previous: tuple[float, float] | None = None
    # Browser route handlers resample each physical pointer segment or each
    # simplified hoop command at this interval. Requiring the same bound in
    # the server replay prevents a transcript from jumping over the corridor.
    max_sample_gap = max(1.0, min(radius, corridor) / 2.0) + 0.12
    for event in events:
        if event.get("action") not in {"route_start", "route_move", "route_end"}:
            return "route transcript contains an unknown action"
        try:
            x, y = float(event["x"]), float(event["y"])
        except (KeyError, TypeError, ValueError):
            return "route coordinates are malformed"
        if not (0 <= x <= 100 and 0 <= y <= 100):
            return "route coordinates leave the board"
        if previous is not None and math.hypot(x - previous[0], y - previous[1]) > max_sample_gap:
            return "route transcript skips unsampled corridor geometry"
        if min(_distance_to_segment(x, y, *points[index], *points[index + 1]) for index in range(len(points) - 1)) > corridor:
            return "capsule left the visible route corridor"
        if checkpoint < len(points) and math.hypot(x - points[checkpoint][0], y - points[checkpoint][1]) <= radius:
            checkpoint += 1
        if event.get("action") == "route_move":
            move_count += 1
        previous = (x, y)
    if checkpoint != len(points) or move_count < len(points):
        return "route checkpoints were not physically traversed"
    return None


VALIDATORS = {
    "pressure": _grade_pressure,
    "chord": _grade_chord,
    "dial": _grade_dial,
    "intercept": _grade_intercept,
    "route": _grade_route,
}


def grade(payload: dict[str, Any], ground_truth: dict[str, Any], public_state: dict[str, Any]) -> dict[str, Any]:
    challenge_id = str(ground_truth.get("challenge_id") or "")
    if str(payload.get("mechanic_id") or "") != MECHANIC_ID or str(ground_truth.get("mechanic_id") or "") != MECHANIC_ID:
        return {"graded": True, "passed": False, "feedback": "mechanic mismatch"}
    if not challenge_id or str(payload.get("challenge_id") or "") != challenge_id:
        return {"graded": True, "passed": False, "feedback": "stale challenge"}
    if str(public_state.get("challenge_id") or "") != challenge_id:
        return {"graded": True, "passed": False, "feedback": "public-state challenge mismatch"}
    task_id = str(ground_truth.get("task_id") or "")
    if not task_id or str(payload.get("task_id") or "") != task_id or str(public_state.get("task_id") or "") != task_id:
        return {"graded": True, "passed": False, "feedback": "task identity mismatch"}
    condition = ground_truth.get("control_condition")
    if condition is not None:
        expected_mode = str(condition.get("interaction") or "")
        if (
            expected_mode not in {"simplified", "full"}
            or public_state.get("control_condition") != condition
            or payload.get("interaction_mode") != expected_mode
        ):
            return {"graded": True, "passed": False, "feedback": "interaction condition mismatch"}
    rounds = ground_truth.get("rounds")
    records = payload.get("round_records")
    if not isinstance(rounds, list) or not isinstance(records, list) or len(records) != len(rounds) or len(rounds) != 5:
        return {"graded": True, "passed": False, "feedback": "all five round records are required"}

    resource_events = payload.get("resource_events")
    if not isinstance(resource_events, list) or len(resource_events) > 80:
        return {"graded": True, "passed": False, "feedback": "stability transcript is missing or too long"}
    energy = int(ground_truth.get("starting_energy") or 0)
    completed_ids: list[str] = []
    for sequence, event in enumerate(resource_events, start=1):
        if not isinstance(event, dict) or event.get("sequence") != sequence:
            return {"graded": True, "passed": False, "feedback": f"stability event {sequence} has invalid sequence"}
        if event.get("energy_before") != energy:
            return {"graded": True, "passed": False, "feedback": f"stability event {sequence} disagrees before replay"}
        kind = str(event.get("kind") or "")
        if kind == "fault":
            energy -= int(ground_truth.get("fault_penalty") or 0)
        elif kind == "reset":
            energy -= int(ground_truth.get("reset_penalty") or 0)
        elif kind == "round_complete":
            round_index = len(completed_ids)
            if round_index >= len(rounds) or event.get("round_id") != rounds[round_index].get("id"):
                return {"graded": True, "passed": False, "feedback": "round completion order is invalid"}
            energy -= int(rounds[round_index].get("energy_cost") or 0)
            completed_ids.append(str(event.get("round_id")))
        else:
            return {"graded": True, "passed": False, "feedback": f"stability event {sequence} has invalid kind"}
        energy = max(0, energy)
        if event.get("energy_after") != energy:
            return {"graded": True, "passed": False, "feedback": f"stability event {sequence} disagrees after replay"}

    for index, (record, round_data) in enumerate(zip(records, rounds), start=1):
        if not isinstance(record, dict) or record.get("round_id") != round_data.get("id") or record.get("type") != round_data.get("type"):
            return {"graded": True, "passed": False, "feedback": f"round {index} identity mismatch"}
        if condition is not None and record.get("interaction_mode") != expected_mode:
            return {"graded": True, "passed": False, "feedback": f"round {index} used the wrong interaction surface"}
        round_events = _events(record)
        if round_events is None:
            return {"graded": True, "passed": False, "feedback": f"round {index} event transcript is malformed"}
        if condition is not None and any(event.get("input_surface") != expected_mode for event in round_events):
            return {"graded": True, "passed": False, "feedback": f"round {index} does not record the selected interaction surface"}
        error = VALIDATORS[str(round_data["type"])](round_data, round_events)
        if error:
            return {"graded": True, "passed": False, "feedback": f"round {index}: {error}"}
    if completed_ids != [str(round_data["id"]) for round_data in rounds]:
        return {"graded": True, "passed": False, "feedback": "stability replay does not complete all rounds"}
    if payload.get("final_energy") != energy:
        return {"graded": True, "passed": False, "feedback": "claimed final stability does not match replay"}
    passed = energy > 0
    return {"graded": True, "passed": passed, "feedback": f"reactor rounds 5/5; stability {energy}/100; resource events {len(resource_events)}"}


def cheat(public_state: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    del public_state
    return {"rounds": ground_truth.get("rounds") or [], "round_order": ground_truth.get("round_order") or [], "answers": []}
