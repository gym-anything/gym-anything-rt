from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "specular_lighthouse_relay"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _close(first: Any, second: Any, tolerance: float = .025) -> bool:
    try:
        return math.isfinite(float(first)) and abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def _angle_error(first: float, second: float) -> float:
    return abs((first - second + 90) % 180 - 90)


def _receiver(round_data: dict[str, Any], tick: int) -> tuple[float, float]:
    receiver = round_data["receiver"]
    x, y = (float(value) for value in receiver["center"])
    displacement = float(receiver.get("amplitude", 0)) * math.sin(
        tick * float(receiver.get("angular_rate", 0)) + float(receiver.get("phase", 0))
    )
    if receiver.get("motion_axis") == "x":
        x += displacement
    else:
        y += displacement
    return x, y


def _intersection(origin, direction, first, second):
    sx, sy = second[0] - first[0], second[1] - first[1]
    denominator = direction[0] * sy - direction[1] * sx
    if abs(denominator) < 1e-8:
        return None
    qx, qy = first[0] - origin[0], first[1] - origin[1]
    distance = (qx * sy - qy * sx) / denominator
    segment = (qx * direction[1] - qy * direction[0]) / denominator
    if distance <= .001 or not 0 <= segment <= 1:
        return None
    return origin[0] + direction[0] * distance, origin[1] + direction[1] * distance


def _trace_hit(round_data: dict[str, Any], angles: list[float], tick: int) -> bool:
    origin = tuple(float(value) for value in round_data["emitter"])
    first_center = round_data["mirrors"][0]["center"]
    dx, dy = float(first_center[0]) - origin[0], float(first_center[1]) - origin[1]
    length = math.hypot(dx, dy)
    direction = (dx / length, dy / length)
    for mirror, angle in zip(round_data["mirrors"], angles, strict=True):
        radians = float(angle) * math.pi / 180
        half = float(mirror["length"]) / 2
        tangent = (math.cos(radians), math.sin(radians))
        center = tuple(float(value) for value in mirror["center"])
        ends = (
            (center[0] - tangent[0] * half, center[1] - tangent[1] * half),
            (center[0] + tangent[0] * half, center[1] + tangent[1] * half),
        )
        contact = _intersection(origin, direction, ends[0], ends[1])
        if contact is None:
            return False
        dot = direction[0] * tangent[0] + direction[1] * tangent[1]
        direction = (2 * dot * tangent[0] - direction[0], 2 * dot * tangent[1] - direction[1])
        origin = (contact[0] + direction[0] * .01, contact[1] + direction[1] * .01)
    receiver = _receiver(round_data, tick)
    projection = (receiver[0] - origin[0]) * direction[0] + (receiver[1] - origin[1]) * direction[1]
    closest = (origin[0] + direction[0] * projection, origin[1] + direction[1] * projection)
    return projection > 0 and math.dist(receiver, closest) <= float(round_data["tolerance_px"])


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    condition = truth.get("control_condition")
    if public.get("control_condition") != condition:
        return _fail("public interaction condition differs from lighthouse contract")
    interaction = str((condition or {}).get("interaction") or "")
    expected_source = {"simplified": "gimbal_buttons", "full": "mirror_drag"}.get(interaction)
    if condition is not None and expected_source is None:
        return _fail("lighthouse interaction condition is invalid")
    events = payload.get("events")
    rounds = public.get("rounds") or []
    if not isinstance(events, list) or len(events) > 5000 or not 1 <= len(rounds) <= 5:
        return _fail("live optical transcript malformed")
    round_index = 0
    angles = [float(item["angle_deg"]) for item in rounds[0]["mirrors"]]
    tick = charge = 0
    shutter = False
    charged: list[str] = []
    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        if item.get("type") == "abandon":
            return _fail("relay abandoned")
        if round_index >= len(rounds):
            return _fail("events continue after final receiver")
        current = rounds[round_index]
        action = item.get("type")
        if item.get("round_id") != current["id"]:
            return _fail("optical event bound to wrong receiver")
        if action == "mirror_adjust":
            if expected_source is not None and item.get("input_source") != expected_source:
                return _fail("mirror adjustment uses the wrong interaction input")
            if item.get("tick") != tick:
                return _fail("gimbal adjustment has a false tracking tick")
            try:
                index = [mirror["id"] for mirror in current["mirrors"]].index(item.get("mirror_id"))
            except ValueError:
                return _fail("unknown mirror adjusted")
            if not _close(item.get("before"), angles[index]):
                return _fail("gimbal adjustment starts from stale geometry")
            after = float(item.get("after")) % 180
            step = float(current.get("angle_step_deg") or 1)
            if min(_angle_error(after, (angles[index] + step) % 180), _angle_error(after, (angles[index] - step) % 180)) > .03:
                return _fail("gimbal moved by an impossible step")
            angles[index] = after
        elif action == "shutter":
            if item.get("tick") != tick or bool(item.get("open")) == shutter:
                return _fail("shutter transition is stale or duplicated")
            shutter = bool(item["open"])
        elif action == "charge_sample":
            if not shutter or item.get("tick") != tick + 1:
                return _fail("charge sample occurred outside sequential open-shutter time")
            tick += 1
            reported_angles = item.get("angles")
            if not isinstance(reported_angles, list) or len(reported_angles) != len(current["mirrors"]) or any(not _close(value, angles[index]) for index, value in enumerate(reported_angles)):
                return _fail("charge sample reports false mirror geometry")
            hit = _trace_hit(current, angles, tick)
            if bool(item.get("hit")) != hit:
                return _fail("reported contact disagrees with moving analytic ray replay")
            charge = charge + 1 if hit else max(0, charge - int(current["miss_decay_ticks"]))
            if item.get("charge_after") != charge:
                return _fail("charge meter disagrees with hit/leak replay")
        elif action == "receiver_charged":
            if shutter or item.get("tick") != tick or charge < int(current["required_charge_ticks"]) or int(item.get("charge_ticks", 0)) != charge:
                return _fail("receiver authenticated without sufficient live tracking charge")
            charged.append(current["id"])
            round_index += 1
            tick = charge = 0
            if round_index < len(rounds):
                angles = [float(mirror["angle_deg"]) for mirror in rounds[round_index]["mirrors"]]
        else:
            return _fail(f"unknown optical event {action!r}")
    passed = charged == [item["id"] for item in rounds] and payload.get("completed") is True
    return {"graded": True, "passed": passed, "feedback": f"{len(rounds)} moving receivers sustained independently replayed reflected-beam charge" if passed else f"charged {len(charged)}/{len(rounds)} moving receivers"}
