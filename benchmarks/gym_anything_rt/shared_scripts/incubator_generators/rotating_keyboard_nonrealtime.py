"""Rotating On-Screen Keyboard non-real-time counterpart generator.

The V2 donor's seeded motion specification is retained in the generated
challenge so corresponding seeds keep the same target, rows, and public
difficulty data. The counterpart browser deliberately does not consume that
schedule: its key plane stays in one fixed layout while the player decides.
The timing-dependent motion is therefore removed at the browser/grader
boundary without changing puzzle generation or the two input surfaces.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import random
from pathlib import Path
from typing import Any

MECHANIC_ID = "rotating_keyboard_nonrealtime"
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

BASELINE_PARAMETERS: dict[str, Any] = {
    "key_count": 32,
    "code_length": 5,
    "key_width": 38,
    "key_height": 45,
    "spin_after_characters": 1,
    "segment_ms_min": 900.0,
    "segment_ms_max": 2200.0,
    "yaw_rate_min_deg_s": 24.0,
    "yaw_rate_max_deg_s": 56.0,
    "roll_rate_min_deg_s": 10.0,
    "roll_rate_max_deg_s": 24.0,
    "pitch_max_deg": 18.0,
}


def dynamics():
    path = Path(__file__).resolve().parents[2] / "shared_runtime/server/incubator_graders/rotating_keyboard_nonrealtime.py"
    spec = importlib.util.spec_from_file_location("rotating_keyboard_nonrealtime_dynamics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_int(seed: str, salt: str) -> int:
    return int(hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()[:16], 16)


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    module = dynamics()
    condition = copy.deepcopy(task.get("_control_condition"))
    parameters = copy.deepcopy(condition["difficulty_parameters"]) if condition else copy.deepcopy(BASELINE_PARAMETERS)

    key_count = int(parameters.get("key_count", 32))
    code_length = int(parameters.get("code_length", 5))
    if not 8 <= key_count <= len(ALPHABET):
        raise ValueError("rotating_keyboard_nonrealtime key_count is outside the supported range")
    if not 2 <= code_length <= 12:
        raise ValueError("rotating_keyboard_nonrealtime code_length is outside the supported range")
    for motion_key in module.MOTION_BOUND_KEYS:
        if motion_key not in parameters:
            raise ValueError(f"rotating_keyboard_nonrealtime is missing difficulty parameter {motion_key}")

    motion = {"seed": int(hashlib.sha256(f"{seed}|rotating-keyboard-v2|motion".encode("utf-8")).hexdigest()[:8], 16)}
    for motion_key in module.MOTION_BOUND_KEYS:
        motion[motion_key] = float(parameters[motion_key])
    if not module.valid_motion(motion):
        raise ValueError("rotating_keyboard_nonrealtime motion bounds are invalid")

    rng = random.Random(_seed_int(seed, "rotating-keyboard-v2"))
    alphabet = ALPHABET[:key_count]
    target = "".join(rng.choice(alphabet) for _ in range(code_length))

    row_count = 2 if key_count <= 20 else 3
    base, extra = divmod(key_count, row_count)
    rows = []
    offset = 0
    for index in range(row_count):
        size = base + (1 if index < extra else 0)
        rows.append(alphabet[offset:offset + size])
        offset += size

    keyboard = {
        "target": target,
        "rows": rows,
        "motion": motion,
        "spin_after_characters": int(parameters.get("spin_after_characters", 1)),
        "key_width": int(parameters.get("key_width", 38)),
        "key_height": int(parameters.get("key_height", 45)),
    }
    challenge_id = hashlib.sha256(
        (str(seed) + "|rotating-keyboard-v2|" + json.dumps(keyboard, sort_keys=True)).encode("utf-8")
    ).hexdigest()[:16]

    common = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task["id"],
        "challenge_id": challenge_id,
    }
    if condition:
        common["control_condition"] = condition

    public_state = dict(
        common,
        benchmark="gym_anything_rt",
        prompt=task.get("natural_language") or f"Confirm code {target} using the on-screen keyboard.",
        submit_label="CONFIRM",
        asset_manifest="environments/rotating_keyboard_nonrealtime_env/provenance.json",
        generator={"name": "rotating_keyboard_nonrealtime", "variant_count": len(alphabet) ** code_length},
        keyboard=keyboard,
    )
    ground_truth = dict(
        common,
        seed=seed,
        target=target,
        motion=copy.deepcopy(motion),
        spin_after_characters=keyboard["spin_after_characters"],
    )
    return public_state, ground_truth
