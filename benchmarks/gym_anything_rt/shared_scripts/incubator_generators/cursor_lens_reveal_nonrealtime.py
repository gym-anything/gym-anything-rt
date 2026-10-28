from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "cursor_lens_reveal_nonrealtime"
SEED_MECHANIC_ID = "cursor_lens_reveal"
STAGE = {"width": 920, "height": 500}
VARIANT_COUNT = 22_400_000_000


def _seed(seed: str) -> int:
    # Keep counterpart puzzle content aligned with the frozen donor. Namespace
    # identity belongs in task/challenge IDs, not in the random world seed.
    return int(hashlib.sha256(f"{seed}|{SEED_MECHANIC_ID}|palimpsest-v2".encode()).hexdigest()[:16], 16)


def _position(node: dict[str, Any], elapsed_ms: float) -> list[float]:
    motion = node["motion"]
    phase = float(motion["phase"])
    angle = math.tau * elapsed_ms / float(motion["period_ms"]) + phase
    return [
        round(float(node["base"][0]) + float(motion["radius_x"]) * math.sin(angle), 2),
        round(float(node["base"][1]) + float(motion["radius_y"]) * math.cos(angle * float(motion["ratio"])), 2),
    ]


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed(seed))
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    echo_count = int(parameters.get("echo_count", 5))
    clutter_count = int(parameters.get("clutter_count", 145))
    if not 1 <= echo_count <= 5 or not 20 <= clutter_count <= 240:
        raise ValueError("palimpsest counts are outside supported limits")
    task_id = str(task.get("id") or "cursor_lens_reveal_nonrealtime_seed_0001@0.1")
    condition_token = f"|d{condition['difficulty']}|{task_id}" if condition else ""
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}{condition_token}".encode()).hexdigest()[:13]
    bases = [[128, 122], [735, 104], [474, 216], [180, 392], [742, 390], [470, 390]][:echo_count]
    rng.shuffle(bases)
    polarizations: list[int] = []
    for _ in range(echo_count):
        choices = [value for value in (0, 45, 90, 135) if not polarizations or value != polarizations[-1]]
        polarizations.append(rng.choice(choices))
    nodes: list[dict[str, Any]] = []
    glyphs = list("◇△⊕⌁✦⬡")[:echo_count]
    rng.shuffle(glyphs)
    for index, base in enumerate(bases):
        node = {
            "id": f"echo-{hashlib.sha256(f'{seed}|echo|{index}'.encode()).hexdigest()[:7]}",
            "sequence": index,
            "base": base,
            "polarization_deg": polarizations[index],
            "glyph": glyphs[index],
            "motion": {
                "radius_x": rng.randint(int(parameters.get("motion_radius_x_min", 14)), int(parameters.get("motion_radius_x_max", 27))),
                "radius_y": rng.randint(int(parameters.get("motion_radius_y_min", 10)), int(parameters.get("motion_radius_y_max", 22))),
                "period_ms": rng.randint(int(parameters.get("motion_period_ms_min", 5400)), int(parameters.get("motion_period_ms_max", 7600))),
                "phase": round(rng.uniform(0, math.tau), 4),
                "ratio": rng.choice((0.68, 0.82, 1.14)),
            },
        }
        nodes.append(node)
        for sample in range(0, 16_001, 250):
            x, y = _position(node, sample)
            assert 64 <= x <= STAGE["width"] - 64 and 58 <= y <= STAGE["height"] - 58
    clutter = [
        {
            "x": rng.randint(18, STAGE["width"] - 18),
            "y": rng.randint(18, STAGE["height"] - 18),
            "length": rng.randint(5, 24),
            "angle": rng.randint(0, 179),
            "phase": rng.random(),
        }
        for _ in range(clutter_count)
    ]
    requirements = {
        "lock_radius": int(parameters.get("lock_radius", 31)),
        "polarization_tolerance_deg": 10,
        "minimum_hold_ms": int(parameters.get("minimum_hold_ms", 460)),
        "minimum_track_samples": int(parameters.get("minimum_track_samples", 4)),
        "minimum_probe_samples": int(parameters.get("minimum_probe_samples", 32)),
        "minimum_probe_cells": int(parameters.get("minimum_probe_cells", 14)),
        "minimum_tuning_changes": int(parameters.get("minimum_tuning_changes", 4)),
        "maximum_event_time_ms": 180_000,
    }
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": "Tune the glass, scan each echo, and hold it steady before developing the plate.",
        "submit_label": "DEVELOP THE PLATE",
        "asset_manifest": "shared_runtime/assets/provenance/incubator_full_build_v1.json",
        "generator": {"name": "polarized_moving_palimpsest_v3" if condition else "polarized_moving_palimpsest_v2", "variant_count": VARIANT_COUNT},
        "stage": STAGE,
        "lens_radius": int(parameters.get("lens_radius", 72)),
        "nodes": copy.deepcopy(nodes),
        "clutter": clutter,
        "requirements": requirements,
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "stage": STAGE,
        "nodes": copy.deepcopy(nodes),
        "clutter": clutter,
        "requirements": requirements,
        "variant_count": VARIANT_COUNT,
    }
    if condition:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    assert len({node["id"] for node in nodes}) == echo_count
    return public_state, ground_truth
