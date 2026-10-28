from __future__ import annotations

import copy
import hashlib
import random
from typing import Any


MECHANIC_ID = "lanternwing_roundup"
ASSET_MANIFEST = "shared_runtime/assets/provenance/lanternwing_roundup_v0.json"
DT = 0.08
TICK_MS = 80
WORLD_BOUNDS = {"x_min": -10.0, "x_max": 10.0, "z_min": 2.0, "z_max": 22.0}

PROFILES: dict[int, dict[str, Any]] = {
    1: {
        "target_count": 1, "decoy_count": 0, "obstacle_count": 0,
        "target_speed": 0.006, "vertical_motion": 0.10, "capture_radius": 0.78,
        "ammo": 3, "max_ticks": 230, "projectile_speed": 15.0, "gravity": 8.4,
    },
    2: {
        "target_count": 1, "decoy_count": 1, "obstacle_count": 1,
        "target_speed": 0.011, "vertical_motion": 0.18, "capture_radius": 0.68,
        "ammo": 4, "max_ticks": 250, "projectile_speed": 14.5, "gravity": 8.8,
    },
    3: {
        "target_count": 2, "decoy_count": 1, "obstacle_count": 2,
        "target_speed": 0.017, "vertical_motion": 0.28, "capture_radius": 0.58,
        "ammo": 6, "max_ticks": 285, "projectile_speed": 14.0, "gravity": 9.2,
    },
    4: {
        "target_count": 3, "decoy_count": 2, "obstacle_count": 3,
        "target_speed": 0.023, "vertical_motion": 0.42, "capture_radius": 0.50,
        "ammo": 8, "max_ticks": 320, "projectile_speed": 13.5, "gravity": 9.6,
    },
    5: {
        "target_count": 4, "decoy_count": 3, "obstacle_count": 5,
        "target_speed": 0.032, "vertical_motion": 0.60, "capture_radius": 0.42,
        "ammo": 11, "max_ticks": 360, "projectile_speed": 13.0, "gravity": 10.0,
    },
}

TARGET_WINGS = (
    {"color": "amber", "sigil": "crescent", "accent": "#ffd477"},
    {"color": "violet", "sigil": "fork", "accent": "#e0a5ff"},
    {"color": "cyan", "sigil": "diamond", "accent": "#8df5e8"},
    {"color": "coral", "sigil": "thorn", "accent": "#ff9f8e"},
)
DECOY_WINGS = (
    {"color": "moss", "sigil": "dot", "accent": "#a8c983"},
    {"color": "smoke", "sigil": "bar", "accent": "#b8c3ce"},
    {"color": "plum", "sigil": "ring", "accent": "#c38ba9"},
    {"color": "indigo", "sigil": "slash", "accent": "#8da9e9"},
)


def _seed(seed: str, salt: str = MECHANIC_ID) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}|{salt}".encode()).digest()[:8], "big")


def _round(value: float) -> float:
    return round(float(value), 5)


def _creature_id(seed: str, index: int) -> str:
    return f"wing-{hashlib.sha256(f'{seed}|wing|{index}'.encode()).hexdigest()[:10]}"


def _appearance(group: tuple[dict[str, str], ...], index: int) -> dict[str, str]:
    return dict(group[index % len(group)])


def _position(motion: dict[str, Any], tick: int) -> dict[str, float]:
    phase = float(motion["phase"]) + float(motion["rate"]) * int(tick)
    return {
        "x": _round(float(motion["base_x"]) + float(motion["amp_x"]) * __import__("math").sin(phase)),
        "y": _round(float(motion["base_y"]) + float(motion["amp_y"]) * __import__("math").sin(phase * 1.31)),
        "z": _round(float(motion["base_z"]) + float(motion["amp_z"]) * __import__("math").cos(phase * 0.83)),
    }


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    condition = copy.deepcopy(task.get("_control_condition"))
    difficulty = int((condition or {}).get("difficulty", 4))
    parameters = dict(PROFILES[difficulty])
    parameters.update(dict((condition or {}).get("difficulty_parameters") or {}))
    interaction = str((condition or {}).get("interaction") or "full")
    if interaction not in {"full", "simplified"}:
        raise ValueError("lanternwing interaction must be full or simplified")
    rng = random.Random(_seed(str(seed)))
    task_id = str(task.get("id") or f"{MECHANIC_ID}_seed_0001@0.2")
    condition_token = "" if condition is None or difficulty == 4 else f"|difficulty-{difficulty}"
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}|sanctuary-v1{condition_token}".encode()).hexdigest()[:14]
    target_count = int(parameters["target_count"])
    decoy_count = int(parameters["decoy_count"])

    creatures: list[dict[str, Any]] = []
    target_ids: list[str] = []
    target_appearances: list[dict[str, str]] = []
    for index in range(target_count + decoy_count):
        is_target = index < target_count
        if is_target:
            appearance = _appearance(TARGET_WINGS, index)
            x = (-3.1, 0.0, 3.1, -4.2)[index % 4] + rng.uniform(-0.28, 0.28)
            z = 9.3 + (index % 4) * 2.15 + rng.uniform(-0.25, 0.25)
            y = 2.15 + (index % 2) * 0.48 + rng.uniform(-0.10, 0.10)
            target_ids.append(_creature_id(str(seed), index))
            target_appearances.append(copy.deepcopy(appearance))
        else:
            decoy_index = index - target_count
            appearance = _appearance(DECOY_WINGS, decoy_index)
            x = (-1.8, 2.2, -4.8, 4.8)[decoy_index % 4] + rng.uniform(-0.24, 0.24)
            z = 8.0 + (decoy_index % 4) * 2.45 + rng.uniform(-0.22, 0.22)
            y = 1.9 + (decoy_index % 3) * 0.35 + rng.uniform(-0.08, 0.08)
        motion = {
            "base_x": _round(x), "base_y": _round(y), "base_z": _round(z),
            "amp_x": _round(0.32 + rng.random() * 0.22),
            "amp_y": _round(float(parameters["vertical_motion"]) * (0.72 + rng.random() * 0.35)),
            "amp_z": _round(0.22 + rng.random() * 0.18),
            "phase": _round(rng.uniform(-3.1, 3.1)),
            "rate": _round(float(parameters["target_speed"]) * (0.78 + rng.random() * 0.35)),
        }
        creature = {
            "id": _creature_id(str(seed), index),
            "appearance": appearance,
            "motion": motion,
            "radius": _round(float(parameters["capture_radius"])),
            **_position(motion, 0),
        }
        creatures.append(creature)

    obstacles: list[dict[str, Any]] = []
    obstacle_candidates = ((-5.8, 8.0, 1.1, 1.9), (5.2, 10.8, 1.3, 2.2), (-0.8, 14.0, 1.2, 1.7), (6.0, 16.7, 1.0, 1.8), (-6.4, 18.3, 1.0, 1.6))
    for index in range(int(parameters["obstacle_count"])):
        x, z, width, depth = obstacle_candidates[index]
        obstacles.append({
            "id": f"obelisk-{index + 1}", "x": x, "z": z, "width": width,
            "depth": depth, "y": 0.0, "height": 4.4 + (index % 2) * 0.8,
            "kind": ("monolith", "arch", "monolith")[index % 3],
        })

    world = {
        "bounds": copy.deepcopy(WORLD_BOUNDS),
        "player_start": {"x": 0.0, "y": 1.55, "z": 2.8, "yaw": 0.0, "pitch": 0.0},
        "move_speed": 3.2,
        "eye_height": 0.18,
        "obstacles": obstacles,
        "terraces": [
            {"x": -7.8, "z": 6.1, "width": 4.2, "depth": 3.0, "height": 0.7},
            {"x": 6.3, "z": 11.8, "width": 4.0, "depth": 3.2, "height": 1.4},
            {"x": -6.6, "z": 17.0, "width": 4.6, "depth": 3.3, "height": 2.1},
        ],
    }
    physics = {
        "dt": DT, "tick_ms": TICK_MS, "gravity": float(parameters["gravity"]),
        "projectile_speed": float(parameters["projectile_speed"]), "projectile_radius": 0.17,
        "max_projectile_ticks": 34, "capture_radius": float(parameters["capture_radius"]),
        "max_ticks": int(parameters["max_ticks"]), "ammo": int(parameters["ammo"]),
    }
    wanted = [
        {"slot": index + 1, "appearance": copy.deepcopy(appearance), "label": f"LANTERNWING {index + 1}"}
        for index, appearance in enumerate(target_appearances)
    ]
    public = {
        "benchmark": "gym_anything_rt", "mechanic_id": MECHANIC_ID, "task_id": task_id,
        "challenge_id": challenge_id, "asset_manifest": ASSET_MANIFEST,
        "prompt": task.get("natural_language") or "Round up the wandering lanternwings with gravity-driven capsules.",
        "submit_label": "CERTIFY ROUNDUP", "generator": {"name": "lanternwing_sanctuary_v1", "variant_count": 2**48},
        "world": world, "physics": physics, "creatures": copy.deepcopy(creatures), "wanted": wanted,
        "rules": [
            "Capsules leave the lantern and travel through 3D space under gravity.",
            "The wings continue moving in depth and height while a capsule is in flight.",
            "A contact with a wanted wing is secure; a decoy contact spends ammunition but does not secure a wanted wing.",
        ],
        "palette": rng.choice(("saffron dusk", "violet rain", "copper moon", "cyan garden")),
    }
    truth = {
        "mechanic_id": MECHANIC_ID, "task_id": task_id, "challenge_id": challenge_id,
        "seed": str(seed), "world": copy.deepcopy(world), "physics": copy.deepcopy(physics),
        "initial_creatures": copy.deepcopy(creatures), "target_ids": target_ids,
        "target_appearances": target_appearances, "variant_count": 2**48,
    }
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth
