from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


ASSET_MANIFEST = "shared_runtime/assets/provenance/elastic_membrane_sorter_v2.json"


def _seed(seed: str, mechanic: str) -> int:
    return int(hashlib.sha256(f"{seed}|{mechanic}".encode()).hexdigest()[:16], 16)


def _identity(mechanic: str, task: dict[str, Any], seed: str) -> tuple[random.Random, dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed(seed, mechanic))
    task_id = str(task.get("id") or f"{mechanic}_seed_0001@0.1")
    challenge_id = hashlib.sha256(f"{seed}|{mechanic}".encode()).hexdigest()[:12]
    public = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": mechanic,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "asset_manifest": ASSET_MANIFEST,
        "prompt": task.get("natural_language") or "Complete the physical verification.",
    }
    truth = {
        "mechanic_id": mechanic,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "seed": seed,
    }
    return rng, public, truth


def generate(task: dict[str, Any], seed: str):
    mechanic = "elastic_membrane_sorter_v2"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{mechanic}|d{condition['difficulty']}|{condition['interaction']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id
    round_count = int(parameters.get("round_count", 3))
    checkpoints_per_round = int(parameters.get("checkpoints_per_round", 2))
    if not 1 <= round_count <= 3 or not 1 <= checkpoints_per_round <= 3:
        raise ValueError("elastic membrane profile is outside supported course limits")
    initial_height_low = float(parameters.get("initial_height_low", 0.42))
    initial_height_high = float(parameters.get("initial_height_high", 0.58))
    if not 0 <= initial_height_low <= initial_height_high <= 1:
        raise ValueError("elastic membrane post-height range is invalid")
    wells = ((125, 115), (775, 120), (450, 385))
    rounds = []
    courses = (
        [[355, 175], [235, 108], [155, 150]],
        [[545, 175], [665, 110], [745, 155]],
        [[365, 305], [515, 355], [455, 410]],
    )
    order = list(range(3))
    rng.shuffle(order)
    for index, target in enumerate(order[:round_count]):
        initial = [round(rng.uniform(initial_height_low, initial_height_high), 2) for _ in range(4)]
        rounds.append({
            "id": f"marble-{index + 1}", "target_well": target,
            "start": [450, 230], "post_heights": initial,
            "wells": [list(item) for item in wells],
            "checkpoints": courses[target][:checkpoints_per_round],
        })
    public.update({
        "generator": {"name": "live_steered_membrane_course_v2", "variant_count": 10**9},
        "canvas": {"width": 900, "height": 480},
        "rounds": rounds,
        "post_positions": [[70, 55], [830, 55], [70, 425], [830, 425]],
        "physics": {
            "tick_ms": 35,
            "slope_accel": float(parameters.get("slope_accel", 0.10)),
            "drag": float(parameters.get("drag", 0.955)),
            "well_radius": int(parameters.get("well_radius", 30)),
            "capture_speed": float(parameters.get("capture_speed", 2.8)),
            "checkpoint_radius": int(parameters.get("checkpoint_radius", 34)),
            "max_ticks": int(parameters.get("max_ticks", 720)),
            "boundary_restitution": 0.55,
            "post_drift": {
                "amplitude": 0.18,
                "segment_ticks": 96,
                "seed": _seed(seed + "|post-drift", mechanic) & 0xFFFFFFFF,
            },
        },
    })
    truth.update({"rounds": rounds, "physics": public["physics"]})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth
