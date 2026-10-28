from __future__ import annotations

import math
from typing import Any


MECHANIC_ID = "reload_interruption_v2"

def motion_noise(seed, index):
    """Stable 32-bit mixing, independently implemented by the browser."""
    x = (int(seed) + (int(index) + 1) * 0x9E3779B9) & 0xffffffff
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff) / 2147483648 - 1


def motion_value(seed, t_ms, span_ms=1300):
    t = max(0.0, float(t_ms)) / span_ms
    index = int(t)
    u = t - index
    a, b = motion_noise(seed, index), motion_noise(seed, index + 1)
    return a + (b - a) * u * u * (3 - 2 * u)


def motion_integral(seed, t_ms, span_ms=1300):
    """Integral in seconds; a fresh smooth velocity segment follows each one."""
    t = max(0.0, float(t_ms)) / span_ms
    count = int(t)
    total = sum((motion_noise(seed, i) + motion_noise(seed, i + 1)) / 2 for i in range(count))
    u = t - count
    a, b = motion_noise(seed, count), motion_noise(seed, count + 1)
    return span_ms / 1000 * (total + a * u + (b - a) * (u**3 - .5 * u**4))



def _spark(spec: dict[str, Any], elapsed_ms: float) -> tuple[float, float]:
    angle = float(spec["phase"]) + (.75*elapsed_ms+650*motion_integral(spec["motion_seed"],elapsed_ms,1000)) * float(spec["rate"])
    return (
        float(spec["center"][0]) + math.cos(angle) * float(spec["radius_x"]),
        float(spec["center"][1]) + math.sin(angle) * float(spec["radius_y"]),
    )


def _validate_interrupt(event: dict[str, Any], spec: dict[str, Any], interaction: str) -> str | None:
    if str(event.get("surface") or "") != interaction:
        return "overload used the wrong interaction surface"
    samples = event.get("samples")
    try:
        duration = int(event.get("duration_ms"))
    except (TypeError, ValueError):
        return "overload duration is invalid"
    if duration < int(spec["hold_ms"]) or not isinstance(samples, list) or len(samples) < int(spec["min_samples"]) or len(samples) > 120:
        return "overload hold was too short or sparse"
    clean: list[tuple[int, int, tuple[float, float]]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            return "overload sample is malformed"
        try:
            elapsed = int(sample["elapsed_ms"])
            world_elapsed = int(sample["world_elapsed_ms"])
            point = sample["point"]
            x, y = float(point[0]), float(point[1])
        except (KeyError, TypeError, ValueError, IndexError):
            return "overload sample is malformed"
        if elapsed < 0 or world_elapsed < 0 or not math.isfinite(x) or not math.isfinite(y):
            return "overload sample is not finite"
        if clean and (elapsed <= clean[-1][0] or elapsed - clean[-1][0] > int(spec["max_gap_ms"])):
            return "overload tracking samples are not continuous"
        if clean and world_elapsed < clean[-1][1]:
            return "overload world samples moved backward"
        clean.append((elapsed, world_elapsed, (x, y)))
    if interaction == "simplified":
        return None
    # Replay samples from the recorded pointer-down time on the changing path.
    try:
        base_offset = float(event["start_world_elapsed_ms"])
    except (KeyError, TypeError, ValueError):
        return "missing spark hold start"
    if not math.isfinite(base_offset) or base_offset < 0:
        return "invalid spark hold start"
    tolerance = float(spec["tolerance"])
    for _elapsed, world_elapsed, point in clean:
        expected = _spark(spec, world_elapsed + base_offset)
        if math.hypot(point[0] - expected[0], point[1] - expected[1]) > tolerance:
            return "pointer left the moving overload spark"
    if duration - clean[-1][0] > int(spec["max_gap_ms"]) + 90:
        return "overload tracking ended with an unobserved hold gap"
    return None


def grade(payload: dict[str, Any], ground_truth: dict[str, Any], public_state: dict[str, Any]) -> dict[str, Any]:
    challenge_id = str(ground_truth.get("challenge_id") or "")
    if str(payload.get("mechanic_id") or "") != MECHANIC_ID or str(ground_truth.get("mechanic_id") or "") != MECHANIC_ID:
        return {"graded": True, "passed": False, "feedback": "mechanic mismatch"}
    if not challenge_id or str(payload.get("challenge_id") or "") != challenge_id or str(public_state.get("challenge_id") or "") != challenge_id:
        return {"graded": True, "passed": False, "feedback": "stale challenge"}
    events = payload.get("events")
    if not isinstance(events, list):
        return {"graded": True, "passed": False, "feedback": "reload transcript is missing or outside limits"}
    expected = [str(item) for item in ground_truth.get("sequence") or []]
    interrupts = {str(item["id"]): dict(item) for item in ground_truth.get("interruptions") or []}
    interaction = str((ground_truth.get("control_condition") or {}).get("interaction") or "full")
    if str(payload.get("interaction_mode") or "") != interaction:
        return {"graded": True, "passed": False, "feedback": "reload used the wrong interaction surface"}
    expected_event_count = len(expected) + len(interrupts)
    if not expected or not interrupts or len(events) != expected_event_count:
        return {"graded": True, "passed": False, "feedback": "reload transcript is missing or outside limits"}
    gestures: list[str] = []
    cleared: list[str] = []
    for sequence, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("sequence") != sequence:
            return {"graded": True, "passed": False, "feedback": f"event {sequence} sequence mismatch"}
        kind = str(event.get("kind") or "")
        if kind == "abort":
            return {"graded": True, "passed": False, "feedback": "reload was aborted"}
        if kind == "gesture":
            if len(gestures) >= len(expected) or event.get("index") != len(gestures):
                return {"graded": True, "passed": False, "feedback": "gesture index is invalid"}
            if str(event.get("surface") or "") != interaction:
                return {"graded": True, "passed": False, "feedback": "gesture used the wrong interaction surface"}
            direction = str(event.get("direction") or "")
            if direction != expected[len(gestures)]:
                return {"graded": True, "passed": False, "feedback": "remembered gesture was wrong"}
            required_before = [item for item in interrupts.values() if int(item["after_step"]) < len(gestures) + 1]
            if any(item["id"] not in cleared for item in required_before):
                return {"graded": True, "passed": False, "feedback": "reload resumed before clearing an interruption"}
            gestures.append(direction)
            continue
        if kind == "interrupt":
            interrupt_id = str(event.get("interruption_id") or "")
            spec = interrupts.get(interrupt_id)
            if spec is None or interrupt_id in cleared or len(gestures) != int(spec["after_step"]):
                return {"graded": True, "passed": False, "feedback": "overload occurred at the wrong reload state"}
            error = _validate_interrupt(event, spec, interaction)
            if error:
                return {"graded": True, "passed": False, "feedback": error}
            cleared.append(interrupt_id)
            continue
        return {"graded": True, "passed": False, "feedback": f"unknown reload event {kind}"}
    passed = gestures == expected and set(cleared) == set(interrupts)
    return {"graded": True, "passed": passed, "feedback": f"remembered gestures {len(gestures)}/{len(expected)}; overload holds {len(cleared)}/{len(interrupts)}"}
