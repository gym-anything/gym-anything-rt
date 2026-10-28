from __future__ import annotations

import copy
import math
from typing import Any


MECHANIC_ID = "lanternfin_dive_nonrealtime"
CHANNELS = ("tail", "yaw", "pitch", "roll")
ACTION_SETTLE_TICKS = 1


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _close(first: Any, second: Any, tolerance: float = 0.012) -> bool:
    try:
        return math.isfinite(float(first)) and math.isfinite(float(second)) and abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def _same_state(first: dict[str, Any], second: dict[str, Any], tolerance: float = 0.012) -> bool:
    return all(_close(first.get(key), second.get(key), tolerance) for key in second)


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _current(tick: int, physics: dict[str, Any]) -> tuple[float, float, float]:
    def anchor(segment):
        value = (int(physics["current_seed"]) ^ ((segment * 0x9E3779B1) & 0xffffffff)) & 0xffffffff
        value = ((value ^ (value >> 16)) * 0x85EBCA6B) & 0xffffffff
        value = ((value ^ (value >> 13)) * 0xC2B2AE35) & 0xffffffff
        return ((value ^ (value >> 16)) & 0xffffffff) / 4294967296
    segment, within = divmod(tick, int(physics["current_segment_ticks"]))
    f = within / int(physics["current_segment_ticks"])
    blend = f**3 * (f * (6*f - 15) + 10)
    a, b = anchor(segment) * math.tau, anchor(segment + 1) * math.tau
    angle = a + ((b-a+math.pi) % math.tau-math.pi) * blend
    strength = float(physics["current_gain"])
    roll = float(physics["current_roll_gain"]) * (0.7 + 0.3 * math.sin(angle))
    return math.cos(angle) * strength, math.sin(angle) * strength, roll


def _step(state: dict[str, float], controls: dict[str, float], physics: dict[str, Any], tick: int) -> None:
    dt = float(physics["dt"])
    tail = _clamp(float(controls["tail"]))
    yaw = _clamp(float(controls["yaw"]))
    pitch = _clamp(float(controls["pitch"]))
    roll = _clamp(float(controls["roll"]))
    state["tail_phase"] += dt * (3.2 + 0.8 * abs(tail))
    state["fin_phase"] += dt * (2.0 + 0.35 * (abs(pitch) + abs(roll)))
    angular_damping = float(physics["angular_damping"])
    torque_gain = float(physics["torque_gain"])
    state["yaw_rate"] = state["yaw_rate"] * angular_damping + yaw * torque_gain
    state["pitch_rate"] = state["pitch_rate"] * angular_damping + pitch * torque_gain
    flow_x, flow_z, flow_roll = _current(tick, physics)
    state["roll_rate"] = state["roll_rate"] * angular_damping + roll * torque_gain + flow_roll
    state["yaw"] += state["yaw_rate"]
    state["pitch"] = max(-1.2, min(1.2, state["pitch"] + state["pitch_rate"]))
    state["roll"] = max(-1.2, min(1.2, state["roll"] + state["roll_rate"]))
    forward_x = math.cos(state["pitch"]) * math.cos(state["yaw"])
    forward_y = math.sin(state["pitch"])
    forward_z = math.cos(state["pitch"]) * math.sin(state["yaw"])
    stroke = tail * (0.56 + 0.44 * math.sin(state["tail_phase"]))
    thrust = float(physics["thrust_gain"]) * 0.1 * stroke
    # Fins make a small fluid-relative lift contribution as well as changing
    # attitude. This keeps all four visible channels coupled to the 3D motion.
    lift = float(physics["thrust_gain"]) * 0.018 * math.sin(state["fin_phase"])
    state["vx"] = state["vx"] * float(physics["linear_damping"]) + forward_x * thrust + flow_x
    state["vy"] = state["vy"] * float(physics["linear_damping"]) + forward_y * thrust + pitch * lift
    state["vz"] = state["vz"] * float(physics["linear_damping"]) + forward_z * thrust + roll * lift + flow_z
    state["x"] += state["vx"]
    state["y"] += state["vy"]
    state["z"] += state["vz"]


def _arrival(state: dict[str, float], target: dict[str, Any], physics: dict[str, Any]) -> bool:
    distance = math.sqrt(sum((state[axis] - float(target[axis])) ** 2 for axis in ("x", "y", "z")))
    speed = math.sqrt(sum(state[axis] ** 2 for axis in ("vx", "vy", "vz")))
    return (
        distance <= float(physics["arrival_radius"])
        and speed <= float(physics["speed_limit"])
        and abs(state["pitch"]) <= float(physics["upright_tolerance"])
        and abs(state["roll"]) <= float(physics["upright_tolerance"])
    )


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    for key in ("initial", "target", "physics"):
        if public.get(key) != truth.get(key):
            return _fail(f"public {key} differs from the challenge contract")
    condition = truth.get("control_condition")
    if condition is not None and public.get("control_condition") != condition:
        return _fail("Lanternfin control condition mismatch")
    interaction = str((condition or {}).get("interaction") or "")
    expected_sources = None if condition is None else {
        "simplified": {"torque_button", "torque_neutral_button"},
        "full": {"torque_keyboard", "torque_neutral_keyboard"},
    }.get(interaction)
    if condition is not None and expected_sources is None:
        return _fail("Lanternfin interaction mode is invalid")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 7000:
        return _fail("Lanternfin transcript malformed")
    state = {key: float(value) for key, value in truth["initial"].items()}
    controls = {channel: 0.0 for channel in CHANNELS}
    physics = truth["physics"]
    target = truth["target"]
    tick = 0
    hold = 0
    terminal = None
    last_physical_kind = None
    for sequence, item in enumerate(events, 1):
        if not isinstance(item, dict) or item.get("seq") != sequence:
            return _fail(f"event {sequence} sequence invalid")
        kind = item.get("type")
        if terminal is not None:
            return _fail("events appeared after pearl certification")
        if kind == "abandon":
            return _fail("dive abandoned")
        if kind == "camera":
            continue
        if kind not in {"torque", "certify"}:
            return _fail(f"unknown Lanternfin event {kind!r}")
        try:
            event_tick = int(item.get("tick"))
        except (TypeError, ValueError):
            return _fail("Lanternfin event has no physical tick")
        if event_tick < tick or event_tick > int(physics["replay_tick_limit"]):
            return _fail("Lanternfin event time moved backward or beyond the dive")
        action_settle_ticks = int(physics.get("action_settle_ticks", ACTION_SETTLE_TICKS))
        if action_settle_ticks != ACTION_SETTLE_TICKS:
            return _fail("Lanternfin action-settle contract is invalid")
        if last_physical_kind is None:
            expected_tick = 0
        elif last_physical_kind == "torque":
            expected_tick = tick + action_settle_ticks
        else:
            expected_tick = tick
        if event_tick != expected_tick:
            return _fail("Lanternfin event time does not match the fixed action settle")
        for replay_tick in range(tick, event_tick):
            _step(state, controls, physics, replay_tick)
            hold = hold + 1 if _arrival(state, target, physics) else 0
        tick = event_tick
        if kind == "torque":
            channel = str(item.get("channel") or "")
            if channel not in CHANNELS:
                return _fail("unknown torque channel")
            if expected_sources is not None and item.get("input_source") not in expected_sources:
                return _fail("torque used the wrong interaction input")
            if not _same_state(item.get("before") or {}, {channel: controls[channel]}, 0.02):
                return _fail("torque event started from a stale control value")
            try:
                value = float(item.get("value"))
            except (TypeError, ValueError):
                return _fail("torque value is not numeric")
            if value not in {-1.0, 0.0, 1.0}:
                return _fail("torque value is outside the visible detents")
            controls[channel] = value
            try:
                after = float(item.get("after"))
            except (TypeError, ValueError):
                return _fail("torque event has no after detent")
            if after != value:
                return _fail("torque event reports a false detent")
            last_physical_kind = "torque"
        else:
            terminal = item
            if not _same_state(terminal.get("state") or {}, state, 0.018):
                return _fail("certification state disagrees with fluid replay")
            if int(terminal.get("hold_ticks", -1)) != hold:
                return _fail("upright arrival hold disagrees with replay")
            accepted = hold >= int(physics["hold_ticks"]) and _arrival(state, target, physics)
            if bool(terminal.get("accepted")) != accepted:
                return _fail("visible arrival verdict disagrees with replay")
            last_physical_kind = "certify"
    if not isinstance(terminal, dict):
        return _fail("no pearl certification")
    accepted = bool(terminal.get("accepted"))
    passed = accepted and payload.get("completed") is True
    distance = math.sqrt(sum((state[axis] - float(target[axis])) ** 2 for axis in ("x", "y", "z")))
    speed = math.sqrt(sum(state[axis] ** 2 for axis in ("vx", "vy", "vz")))
    return {
        "graded": True,
        "passed": passed,
        "feedback": (
            f"3D fluid replay reached pearl: distance={distance:.3f}, speed={speed:.3f}, upright hold={hold}"
            if passed
            else f"pearl not held: distance={distance:.3f}, speed={speed:.3f}, upright hold={hold}/{physics['hold_ticks']}"
        ),
    }
