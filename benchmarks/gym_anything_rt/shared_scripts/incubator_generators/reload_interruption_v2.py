from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "reload_interruption_v2"
DIRECTIONS = ("up", "right", "down", "left")

DEFAULT_PROFILE = {
    "sequence_length": 7,
    "interruption_steps": [2, 5],
    "preview_step_ms": 420,
    "max_gesture_step": 180,
    "overload_center_jitter_x": 24,
    "overload_center_jitter_y": 18,
    "overload_radius_x_min": 105,
    "overload_radius_x_max": 138,
    "overload_radius_y_min": 58,
    "overload_radius_y_max": 86,
    "overload_rate_min": 0.0048,
    "overload_rate_max": 0.0062,
    "overload_hold_ms": 1150,
    "overload_tolerance": 42,
    "overload_min_samples": 10,
    "overload_max_gap_ms": 180,
}


def _seed(seed: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}|{MECHANIC_ID}|v2".encode()).digest()[:8], "big")


def _profile(task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    condition = task.get("_control_condition")
    if not isinstance(condition, dict):
        return copy.deepcopy(DEFAULT_PROFILE), None
    parameters = condition.get("difficulty_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("reload interruption controls require difficulty parameters")
    profile = copy.deepcopy(DEFAULT_PROFILE)
    profile.update(parameters)
    try:
        profile["sequence_length"] = int(profile["sequence_length"])
        profile["interruption_steps"] = [int(step) for step in profile["interruption_steps"]]
        for name in (
            "preview_step_ms", "max_gesture_step", "overload_center_jitter_x",
            "overload_center_jitter_y", "overload_radius_x_min", "overload_radius_x_max",
            "overload_radius_y_min", "overload_radius_y_max", "overload_hold_ms",
            "overload_tolerance", "overload_min_samples", "overload_max_gap_ms",
        ):
            profile[name] = int(profile[name])
        for name in ("overload_rate_min", "overload_rate_max"):
            profile[name] = float(profile[name])
    except (TypeError, ValueError) as exc:
        raise ValueError("reload interruption controls contain an invalid value") from exc
    if not 3 <= profile["sequence_length"] <= 12:
        raise ValueError("reload interruption sequence length is out of range")
    if not profile["interruption_steps"] or len(set(profile["interruption_steps"])) != len(profile["interruption_steps"]):
        raise ValueError("reload interruption steps must be distinct")
    if any(step < 1 or step >= profile["sequence_length"] for step in profile["interruption_steps"]):
        raise ValueError("reload interruption step is outside the reel")
    if profile["overload_radius_x_min"] > profile["overload_radius_x_max"] or profile["overload_radius_y_min"] > profile["overload_radius_y_max"]:
        raise ValueError("reload interruption radius range is invalid")
    if profile["overload_rate_min"] <= 0 or profile["overload_rate_min"] > profile["overload_rate_max"]:
        raise ValueError("reload interruption rate range is invalid")
    if profile["overload_hold_ms"] <= 0 or profile["overload_min_samples"] < 2 or profile["overload_max_gap_ms"] <= 0:
        raise ValueError("reload interruption hold contract is invalid")
    return profile, copy.deepcopy(condition)


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    profile, condition = _profile(task)
    rng = random.Random(_seed(seed))
    sequence = []
    while len(sequence) < profile["sequence_length"]:
        candidate = rng.choice(DIRECTIONS)
        if not sequence or candidate != sequence[-1]:
            sequence.append(candidate)
    interruptions = []
    for index, after_step in enumerate(profile["interruption_steps"]):
        interruptions.append({
            "id": f"overload-{hashlib.sha256(f'{seed}|overload|{index}'.encode()).hexdigest()[:8]}",
            "after_step": after_step,
            "center": [
                350 + rng.randint(-profile["overload_center_jitter_x"], profile["overload_center_jitter_x"]),
                190 + rng.randint(-profile["overload_center_jitter_y"], profile["overload_center_jitter_y"]),
            ],
            "radius_x": rng.randint(profile["overload_radius_x_min"], profile["overload_radius_x_max"]),
            "radius_y": rng.randint(profile["overload_radius_y_min"], profile["overload_radius_y_max"]),
            "phase": round(rng.uniform(0, math.tau), 5),
            "motion_seed": rng.getrandbits(32),
            "rate": round(rng.uniform(profile["overload_rate_min"], profile["overload_rate_max"]), 6),
            "hold_ms": profile["overload_hold_ms"],
            "tolerance": profile["overload_tolerance"],
            "min_samples": profile["overload_min_samples"],
            "max_gap_ms": profile["overload_max_gap_ms"],
        })
    difficulty_suffix = ""
    if condition is not None and int(condition["difficulty"]) != 4:
        difficulty_suffix = f"|difficulty-{int(condition['difficulty'])}"
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}|challenge{difficulty_suffix}".encode()).hexdigest()[:12]
    public = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task["id"],
        "challenge_id": challenge_id,
        "prompt": "Reload the mechanism.",
        "asset_manifest": 'environments/reload_interruption_v2_env/provenance.json',
        "generator": {"name": "interrupted_gesture_memory_v2", "variant_count": 4 ** profile["sequence_length"] * 2048},
        "sequence": sequence,
        "interruptions": interruptions,
        "preview_step_ms": profile["preview_step_ms"],
        "max_gesture_step": profile["max_gesture_step"],
    }
    truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task["id"],
        "seed": seed,
        "challenge_id": challenge_id,
        "sequence": sequence,
        "interruptions": interruptions,
        "max_gesture_step": profile["max_gesture_step"],
    }
    if condition is not None:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth
