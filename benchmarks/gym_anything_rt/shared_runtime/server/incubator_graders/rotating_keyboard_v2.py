"""Rotating On-Screen Keyboard V2: nonperiodic seeded key-plane motion, replayed.

Provenance: this mechanic is a separate, additive V2 of ``rotating_keyboard``
(the original pack-one "Rotating On-Screen Keyboard", inspired by
``RotatingEmail``). The original mechanic drove the key plane with a single
fixed CSS ``@keyframes`` cycle repeated with ``animation: ... linear
infinite``: one duration, one direction, exactly periodic. V2 changes only
that motion driver. It never touches ``rotating_keyboard_env`` or any shared
file used by the original mechanic.

How nonperiodic change enters the state update
------------------------------------------------
The public motion spec is a 32-bit seed plus per-difficulty bounds. A
cross-language PRNG (mulberry32, 32-bit integer arithmetic that JavaScript and
Python evaluate identically) turns that seed into an unbounded stream of
waypoints ``{t, yaw_rate, roll_rate, pitch}``. Each waypoint's gap
(``segment_ms_min..segment_ms_max``), target yaw/roll angular velocity
(magnitude and independently drawn sign) and target pitch are independent
draws, so neither the timing nor the direction of change has a period.
Between waypoints the yaw/roll angular *velocity* is a cubic smoothstep ramp
(continuous acceleration, smooth reversals); pitch is a smoothstep-interpolated
bounded tilt. The yaw/roll angle at any elapsed task time is the closed-form
integral of that ramp, accumulated waypoint by waypoint in the same order in
both languages. The stream is extended lazily for as long as an attempt runs:
there is no finite horizon, no constant-speed tail and no return to a
periodic cycle. The browser mechanic implements the identical arithmetic
separately (``shared_runtime/app/mechanics/rotating_keyboard_v2.js``), so
rendering, hit-testing time stamps and this independent replay agree.

Grading deliberately imposes no speed quota, no minimum gap between inputs,
no maximum attempt duration and no limit on same-instant inputs: real fast
input batches and paused-mode inputs delivered at one frozen task time are
legitimate. Accepted events must simply be nondecreasing in task time, name
the characters of the target in order, come from the interaction mode's input
surface, and (for the full mode) report a rotation state that this module can
recompute from the seed at the same task time.

This module is self-contained (also imported by the generator) so it can be
shipped to the exported/WebAssembly verifier path unchanged.
"""
from __future__ import annotations

import math
from typing import Any

MECHANIC_ID = "rotating_keyboard_v2"

# Explicit floating-point contract: both languages use IEEE-754 doubles and
# the same operation order, so agreement is normally exact; the tolerance only
# keeps the check from being a brittle bitwise comparison across engines.
ANGLE_TOLERANCE_DEG = 0.75

# Computational guard only (memory/CPU for replaying an absurd timestamp),
# not a gameplay limit: seven days of motion is orders of magnitude beyond
# any runner budget, and legitimate multi-hour live attempts replay normally.
MAX_REPLAY_ELAPSED_MS = 7 * 24 * 3600 * 1000.0

MOTION_BOUND_KEYS = (
    "segment_ms_min", "segment_ms_max",
    "yaw_rate_min_deg_s", "yaw_rate_max_deg_s",
    "roll_rate_min_deg_s", "roll_rate_max_deg_s",
    "pitch_max_deg",
)

_MASK = 0xFFFFFFFF


def mulberry32_step(state: int) -> tuple[int, float]:
    """One mulberry32 step; mirrors the JavaScript implementation bit for bit."""
    state = (state + 0x6D2B79F5) & _MASK
    t = state
    t = ((t ^ (t >> 15)) * (1 | t)) & _MASK
    t = ((t + (((t ^ (t >> 7)) * (61 | t)) & _MASK)) ^ t) & _MASK
    return state, ((t ^ (t >> 14)) & _MASK) / 4294967296.0


def _smoothstep(u: float) -> float:
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    return u * u * (3.0 - 2.0 * u)


def _smoothstep_integral(u: float) -> float:
    """Closed form of the integral of ``_smoothstep`` from 0 to ``u``."""
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    return u ** 3 - 0.5 * u ** 4


class MotionSchedule:
    """Lazily extended, seed-reproducible waypoint stream with prefix sums."""

    def __init__(self, motion: dict[str, Any]):
        self.seg_min = float(motion["segment_ms_min"])
        self.seg_max = float(motion["segment_ms_max"])
        self.yaw_min = float(motion["yaw_rate_min_deg_s"])
        self.yaw_max = float(motion["yaw_rate_max_deg_s"])
        self.roll_min = float(motion["roll_rate_min_deg_s"])
        self.roll_max = float(motion["roll_rate_max_deg_s"])
        self.pitch_max = float(motion["pitch_max_deg"])
        self.state = int(motion["seed"]) & _MASK
        # Waypoint 0 already carries a nonzero yaw/roll rate so an immediate
        # start profile moves from its first frame; pitch begins flat.
        yaw0 = self._rate(self.yaw_min, self.yaw_max)
        roll0 = self._rate(self.roll_min, self.roll_max)
        self.times = [0.0]
        self.gaps = [0.0]
        self.yaw_rates = [yaw0]
        self.roll_rates = [roll0]
        self.pitches = [0.0]
        self.cum_yaw = [0.0]
        self.cum_roll = [0.0]

    def _draw(self) -> float:
        self.state, unit = mulberry32_step(self.state)
        return unit

    def _rate(self, low: float, high: float) -> float:
        magnitude = low + self._draw() * (high - low)
        sign = -1.0 if self._draw() < 0.5 else 1.0
        return magnitude * sign

    def _append(self) -> None:
        gap = self.seg_min + self._draw() * (self.seg_max - self.seg_min)
        yaw = self._rate(self.yaw_min, self.yaw_max)
        roll = self._rate(self.roll_min, self.roll_max)
        pitch = -self.pitch_max + self._draw() * (2.0 * self.pitch_max)
        duration_s = gap / 1000.0
        self.cum_yaw.append(self.cum_yaw[-1] + duration_s * 0.5 * (self.yaw_rates[-1] + yaw))
        self.cum_roll.append(self.cum_roll[-1] + duration_s * 0.5 * (self.roll_rates[-1] + roll))
        self.times.append(self.times[-1] + gap)
        self.gaps.append(gap)
        self.yaw_rates.append(yaw)
        self.roll_rates.append(roll)
        self.pitches.append(pitch)

    def ensure(self, elapsed_ms: float) -> None:
        while self.times[-1] <= elapsed_ms:
            self._append()

    def waypoint(self, index: int) -> dict[str, float]:
        while len(self.times) <= index:
            self._append()
        return {
            "t": self.times[index],
            "yaw_rate": self.yaw_rates[index],
            "roll_rate": self.roll_rates[index],
            "pitch": self.pitches[index],
        }

    def angles_at(self, elapsed_ms: float) -> dict[str, float]:
        elapsed = max(0.0, float(elapsed_ms))
        self.ensure(elapsed)
        low, high = 0, len(self.times) - 1
        while high - low > 1:
            mid = (low + high) // 2
            if self.times[mid] <= elapsed:
                low = mid
            else:
                high = mid
        index = low
        gap = self.gaps[index + 1]
        duration_s = gap / 1000.0
        u = (elapsed - self.times[index]) / gap
        yaw_left = self.yaw_rates[index]
        yaw_right = self.yaw_rates[index + 1]
        roll_left = self.roll_rates[index]
        roll_right = self.roll_rates[index + 1]
        yaw = self.cum_yaw[index] + duration_s * (yaw_left * u + (yaw_right - yaw_left) * _smoothstep_integral(u))
        roll = self.cum_roll[index] + duration_s * (roll_left * u + (roll_right - roll_left) * _smoothstep_integral(u))
        pitch = self.pitches[index] + (self.pitches[index + 1] - self.pitches[index]) * _smoothstep(u)
        return {"yaw": yaw, "roll": roll, "pitch": pitch}


def angles_at(motion: dict[str, Any], elapsed_ms: float) -> dict[str, float]:
    """Independently replay the rotation state at ``elapsed_ms`` of motion."""
    return MotionSchedule(motion).angles_at(elapsed_ms)


def valid_motion(motion: Any) -> bool:
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
            return fail("Malformed rotating-keyboard-v2 contract")
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
            return fail("rotating-keyboard-v2 code uses the wrong interaction input")

        submitted = str(payload.get("text") or "").upper()
        correct = sum(1 for left, right in zip(submitted, target) if left == right)
        if submitted != target:
            return fail(f"characters {correct}/{len(target)} correct")

        motion = truth.get("motion")
        if not valid_motion(motion):
            return fail("Missing motion specification")
        if motion != (public.get("keyboard") or {}).get("motion"):
            return fail("Motion specification mismatch between truth and public state")

        events = payload.get("events")
        if not isinstance(events, list) or len(events) != len(target):
            return fail("Event transcript does not match the submitted code length")

        schedule = MotionSchedule(motion)
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
                return fail("Invalid event timing")
            elapsed = float(elapsed)
            if elapsed < 0.0:
                return fail("Event timing precedes the start of the attempt")
            if elapsed > MAX_REPLAY_ELAPSED_MS:
                return fail("Event timing exceeds the replay guard")
            if elapsed < previous_elapsed:
                return fail("Event timestamps are not in order")
            previous_elapsed = elapsed
            if mode == "full":
                replay = schedule.angles_at(elapsed)
                for axis, field in (
                    ("yaw", "observed_yaw_deg"),
                    ("roll", "observed_roll_deg"),
                    ("pitch", "observed_pitch_deg"),
                ):
                    observed = event.get(field)
                    if not _is_number(observed):
                        return fail("Missing independently replayable rotation state")
                    if abs(float(observed) - replay[axis]) > ANGLE_TOLERANCE_DEG:
                        return fail("Reported rotation state disagrees with the independent replay")

        return {
            "graded": True,
            "passed": True,
            "score": 100,
            "feedback": f"code confirmed through the {mode} interaction",
        }
    except (KeyError, TypeError, ValueError, OverflowError, IndexError, MemoryError):
        return fail("Malformed rotating-keyboard-v2 transcript")
