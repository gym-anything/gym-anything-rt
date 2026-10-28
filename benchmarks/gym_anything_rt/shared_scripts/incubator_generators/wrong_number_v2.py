from __future__ import annotations

import hashlib
import random
from typing import Any


MECHANIC_ID = "wrong_number_v2"
PHASE_STEPS = 32
SKEW_MIN = -6
SKEW_MAX = 6
LINE_COUNT = 7
TONES = ("mint", "amber", "violet", "coral", "ice", "lime", "rose")

# These are the historical, uncontrolled parameters.  The L4 control profile
# repeats them exactly so that the pre-control task remains the reference
# configuration for a fixed seed.
DEFAULT_PROFILE = {
    "line_count": LINE_COUNT,
    "phase_steps": PHASE_STEPS,
    "skew_min": SKEW_MIN,
    "skew_max": SKEW_MAX,
    "initial_skew_min": -5,
    "initial_skew_max": 5,
    "drift_milli_values": (-1680, -1510, -1340, -1180, 1180, 1340, 1510, 1680),
    "impostor_distortion_min_milli": 1380,
    "impostor_distortion_max_milli": 2120,
    "phase_tolerance_milli_steps": 1150,
    "skew_tolerance_milli_steps": 720,
    "trial_ms": 4_800,
    "sample_ms": 120,
    "minimum_lock_samples": 30,
    "final_window_samples": 10,
    "minimum_final_lock_samples": 7,
    "maximum_sample_gap_ms": 175,
}


def _seed_int(seed: str, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _line_id(seed: str, slot: int) -> str:
    digest = hashlib.sha256(f"{seed}|carrier|{slot}".encode("utf-8")).hexdigest()[:9]
    return f"line-{slot + 1}-{digest}"


def _profile(task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    condition = task.get("_control_condition")
    if not isinstance(condition, dict):
        return dict(DEFAULT_PROFILE), None
    parameters = condition.get("difficulty_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("Wrong Number control profile is missing its parameters")
    profile = dict(DEFAULT_PROFILE)
    profile.update(parameters)
    try:
        line_count = int(profile["line_count"])
        phase_steps = int(profile["phase_steps"])
        skew_min = int(profile["skew_min"])
        skew_max = int(profile["skew_max"])
        initial_skew_min = int(profile["initial_skew_min"])
        initial_skew_max = int(profile["initial_skew_max"])
        drift_values = tuple(int(value) for value in profile["drift_milli_values"])
        distortion_min = int(profile["impostor_distortion_min_milli"])
        distortion_max = int(profile["impostor_distortion_max_milli"])
        trial_ms = int(profile["trial_ms"])
        sample_ms = int(profile["sample_ms"])
        minimum_lock_samples = int(profile["minimum_lock_samples"])
        final_window_samples = int(profile["final_window_samples"])
        minimum_final_lock_samples = int(profile["minimum_final_lock_samples"])
        maximum_sample_gap_ms = int(profile["maximum_sample_gap_ms"])
        phase_tolerance = int(profile["phase_tolerance_milli_steps"])
        skew_tolerance = int(profile["skew_tolerance_milli_steps"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Wrong Number control profile has an invalid parameter") from exc
    if not 3 <= line_count <= len(TONES) + 1:
        raise ValueError("Wrong Number line count is outside supported limits")
    if not 12 <= phase_steps <= 48 or not skew_min < skew_max:
        raise ValueError("Wrong Number tuning range is outside supported limits")
    if not skew_min <= initial_skew_min <= initial_skew_max <= skew_max:
        raise ValueError("Wrong Number initial skew range is invalid")
    if not drift_values or distortion_min <= 1000 or distortion_max < distortion_min:
        raise ValueError("Wrong Number carrier separation is invalid")
    if min(trial_ms, sample_ms, minimum_lock_samples, final_window_samples, minimum_final_lock_samples, maximum_sample_gap_ms, phase_tolerance, skew_tolerance) <= 0:
        raise ValueError("Wrong Number qualification values must be positive")
    if minimum_final_lock_samples > final_window_samples:
        raise ValueError("Wrong Number final lock requirement exceeds its window")
    return profile, condition


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed_int(seed, MECHANIC_ID))
    profile, condition = _profile(task)
    line_count = int(profile["line_count"])
    phase_steps = int(profile["phase_steps"])
    target_slot = rng.randrange(line_count)
    tone_pool = TONES if line_count <= len(TONES) else (*TONES, "azure")
    tones = list(tone_pool)
    rng.shuffle(tones)
    lines: list[dict[str, Any]] = []
    for slot in range(line_count):
        phase_offset = rng.randrange(phase_steps)
        skew_offset = rng.randint(int(profile["initial_skew_min"]), int(profile["initial_skew_max"]))
        drift_milli = rng.choice(tuple(int(value) for value in profile["drift_milli_values"]))
        distortion_milli = 0 if slot == target_slot else rng.randint(
            int(profile["impostor_distortion_min_milli"]),
            int(profile["impostor_distortion_max_milli"]),
        )
        lines.append(
            {
                "id": _line_id(seed, slot),
                "slot": slot,
                "tone": tones[slot],
                "phase_offset_steps": phase_offset,
                "skew_offset_steps": skew_offset,
                "drift_milli_steps_per_second": drift_milli,
                "distortion_milli": distortion_milli,
                "motion_seed": rng.getrandbits(32),
                "waveform_seed": rng.randrange(1_000, 9_999),
            }
        )

    target = lines[target_slot]
    challenge_salt = MECHANIC_ID if condition is None else f"{MECHANIC_ID}|d{int(condition['difficulty'])}"
    challenge_id = hashlib.sha256(f"{seed}|{challenge_salt}".encode("utf-8")).hexdigest()[:12]
    task_id = str(task.get("id") or "wrong_number_v2_seed_0001@0.1")
    qualification = {
        "phase_steps": phase_steps,
        "phase_tolerance_milli_steps": int(profile["phase_tolerance_milli_steps"]),
        "skew_min": int(profile["skew_min"]),
        "skew_max": int(profile["skew_max"]),
        "skew_tolerance_milli_steps": int(profile["skew_tolerance_milli_steps"]),
        "trial_ms": int(profile["trial_ms"]),
        "sample_ms": int(profile["sample_ms"]),
        "minimum_lock_samples": int(profile["minimum_lock_samples"]),
        "final_window_samples": int(profile["final_window_samples"]),
        "minimum_final_lock_samples": int(profile["minimum_final_lock_samples"]),
        "maximum_sample_gap_ms": int(profile["maximum_sample_gap_ms"]),
    }
    waveform = {
        "base_harmonic_milli": rng.randint(280, 380),
        "reference_twist_milli_radians": rng.randint(220, 520),
        "distortion_gain_milli": 115,
    }
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language")
        or "Phase-lock the authorized carrier. The impostor lines never hold sync.",
        "asset_manifest": 'environments/wrong_number_v2_env/provenance.json',
        "generator": {"name": "wrong_number_v2_active_tracking_v3", "variant_count": 64_800_000_000},
        "lines": lines,
        "qualification": qualification,
        "waveform": waveform,
        "submit_label": "TEST THIS LINE",
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "lines": lines,
        "qualification": qualification,
        "waveform": waveform,
        "target_line_id": target["id"],
        "target_slot": target_slot,
        "solution_phase_step": (-int(target["phase_offset_steps"])) % phase_steps,
        "solution_skew_step": -int(target["skew_offset_steps"]),
        "variant_count": 64_800_000_000,
    }
    assert len(lines) == line_count
    assert len({line["id"] for line in lines}) == line_count
    assert sum(int(line["distortion_milli"]) == 0 for line in lines) == 1
    assert int(profile["skew_min"]) <= int(ground_truth["solution_skew_step"]) <= int(profile["skew_max"])
    if condition is not None:
        public_state["control_condition"] = condition
        ground_truth["control_condition"] = condition
    return public_state, ground_truth
