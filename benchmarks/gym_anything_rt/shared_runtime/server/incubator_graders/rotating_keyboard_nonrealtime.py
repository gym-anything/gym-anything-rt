"""Grader for the fixed-layout rotating-keyboard counterpart.

The donor uses a seeded, continuously changing key plane. This counterpart
keeps the donor's generated target, rows, motion metadata, input surfaces,
ordering rules, exact-string result, erase behavior, and retry behavior, but
uses a fixed zero-rotation layout. Event timestamps are retained as truthful
transcript metadata and are checked for ordering only; they do not affect the
result or close an action opportunity.
"""
from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "rotating_keyboard_nonrealtime"

# Diagnostic tolerance for the fixed transform. This is not a hitbox
# tolerance: ordinary browser button hit testing remains authoritative.
ANGLE_TOLERANCE_DEG = 0.75

# Parser protection only. This is far beyond the runner budget and is not a
# gameplay timer or a limit on how long the player may wait.
MAX_EVENT_ELAPSED_MS = 7 * 24 * 3600 * 1000.0

MOTION_BOUND_KEYS = (
    "segment_ms_min", "segment_ms_max",
    "yaw_rate_min_deg_s", "yaw_rate_max_deg_s",
    "roll_rate_min_deg_s", "roll_rate_max_deg_s",
    "pitch_max_deg",
)

_MASK = 0xFFFFFFFF


def valid_motion(motion: Any) -> bool:
    """Validate retained donor metadata without replaying autonomous motion."""
    if not isinstance(motion, dict):
        return False
    seed = motion.get("seed")
    if type(seed) is not int or not 0 <= seed <= _MASK:
        return False
    for key in MOTION_BOUND_KEYS:
        value = motion.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            return False
    if not 0.0 < float(motion["segment_ms_min"]) <= float(motion["segment_ms_max"]):
        return False
    if not 0.0 <= float(motion["yaw_rate_min_deg_s"]) <= float(motion["yaw_rate_max_deg_s"]):
        return False
    if not 0.0 <= float(motion["roll_rate_min_deg_s"]) <= float(motion["roll_rate_max_deg_s"]):
        return False
    return 0.0 <= float(motion["pitch_max_deg"]) <= 60.0


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def grade(payload: dict, truth: dict, public: dict) -> dict:
    def fail(reason: str) -> dict:
        return {"graded": True, "passed": False, "feedback": reason}

    try:
        if any(not isinstance(value, dict) for value in (payload, truth, public)):
            return fail("Malformed rotating-keyboard counterpart contract")
        if any(value.get("mechanic_id") != MECHANIC_ID for value in (payload, truth, public)):
            return fail("Mechanic mismatch")
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if not truth.get(key) or any(state.get(key) != truth[key] for state in (payload, public)):
                return fail("Stale challenge or task")
        if truth.get("control_condition") != public.get("control_condition"):
            return fail("Condition mismatch between truth and public state")

        target = str(truth.get("target") or "")
        if not target:
            return fail("No target code recorded")
        mode = str((truth.get("control_condition") or {}).get("interaction") or "full")
        expected_source = {"simplified": "physical_keyboard", "full": "onscreen_keys"}.get(mode)
        if expected_source is None:
            return fail("Unknown interaction mode")
        if str(payload.get("interaction_mode") or "") != mode:
            return fail("Wrong interaction mode")
        if str(payload.get("input_source") or "") != expected_source:
            return fail("rotating-keyboard counterpart uses the wrong interaction input")

        submitted = str(payload.get("text") or "").upper()
        correct = sum(1 for left, right in zip(submitted, target) if left == right)
        if submitted != target:
            return fail(f"characters {correct}/{len(target)} correct")

        # The donor's seeded metadata remains part of the generated challenge,
        # but no dynamic replay is used by this fixed-layout counterpart.
        motion = truth.get("motion")
        if not valid_motion(motion):
            return fail("Missing retained motion specification")
        if motion != (public.get("keyboard") or {}).get("motion"):
            return fail("Motion specification mismatch between truth and public state")

        events = payload.get("events")
        if not isinstance(events, list) or len(events) != len(target):
            return fail("Event transcript does not match the submitted code length")

        previous_elapsed = 0.0
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                return fail("Malformed keypress event")
            if str(event.get("key") or "") != target[index]:
                return fail("Event key does not match the accepted character at that position")
            if str(event.get("input_source") or "") != expected_source:
                return fail("Keypress came from the wrong input surface")
            elapsed = event.get("schedule_elapsed_ms")
            if not _is_number(elapsed):
                return fail("Invalid event timing metadata")
            elapsed = float(elapsed)
            if elapsed < 0.0:
                return fail("Event timing precedes the start of the attempt")
            if elapsed > MAX_EVENT_ELAPSED_MS:
                return fail("Event timing exceeds the transcript guard")
            if elapsed < previous_elapsed:
                return fail("Event timestamps are not in order")
            previous_elapsed = elapsed

            # A full-mode click reports the fixed layout's transform. Keeping
            # these fields preserves the donor transcript shape while making
            # the browser result and independent verifier agree on the new
            # timing rule.
            if mode == "full":
                for field in ("observed_yaw_deg", "observed_roll_deg", "observed_pitch_deg"):
                    observed = event.get(field)
                    if not _is_number(observed):
                        return fail("Missing fixed-layout rotation state")
                    if abs(float(observed)) > ANGLE_TOLERANCE_DEG:
                        return fail("Reported rotation state disagrees with the fixed layout")

        return {
            "graded": True,
            "passed": True,
            "score": 100,
            "feedback": f"code confirmed through the fixed-layout {mode} interaction",
        }
    except (KeyError, TypeError, ValueError, OverflowError, IndexError, MemoryError):
        return fail("Malformed rotating-keyboard counterpart transcript")
