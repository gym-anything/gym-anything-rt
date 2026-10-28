from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "lanternfin_dive_nonrealtime"
SEED_NAMESPACE = "lanternfin_dive_v2"
ACTION_SETTLE_TICKS = 1
ASSET_MANIFEST = "shared_runtime/assets/provenance/lanternfin_dive_v0.json"

DEFAULTS: dict[str, Any] = {
    "target_distance": 1.42,
    "target_height": 0.36,
    "target_depth": 0.58,
    "initial_yaw": -0.28,
    "initial_pitch": 0.2,
    "initial_roll": 0.25,
    "angular_damping": 0.8,
    "linear_damping": 0.92,
    "torque_gain": 0.021,
    "thrust_gain": 0.027,
    "arrival_radius": 0.115,
    "upright_tolerance": 0.155,
    "speed_limit": 0.038,
    "hold_ticks": 12,
}


def _seed(seed: str) -> int:
    # Keep counterpart seeds on the donor's puzzle namespace so corresponding
    # seeds retain the same target geometry, palette, and current anchors.
    return int(hashlib.sha256(f"{seed}|{SEED_NAMESPACE}".encode()).hexdigest()[:16], 16)


def _rounded_state(parameters: dict[str, Any]) -> dict[str, float]:
    return {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "vx": 0.0,
        "vy": 0.0,
        "vz": 0.0,
        "yaw": round(float(parameters["initial_yaw"]), 5),
        "pitch": round(float(parameters["initial_pitch"]), 5),
        "roll": round(float(parameters["initial_roll"]), 5),
        "yaw_rate": 0.0,
        "pitch_rate": 0.0,
        "roll_rate": 0.0,
        "tail_phase": 0.0,
        "fin_phase": 0.0,
    }


def generate(task: dict[str, Any], seed: str):
    condition = copy.deepcopy(task.get("_control_condition"))
    parameters = dict(DEFAULTS)
    if condition:
        parameters.update(dict(condition.get("difficulty_parameters") or {}))
    rng = random.Random(_seed(str(seed)))
    task_id = str(task.get("id") or f"{MECHANIC_ID}_seed_0001@0.2")
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}|{task_id}".encode()).hexdigest()[:12]
    bearing = rng.uniform(-0.36, 0.36)
    distance = float(parameters["target_distance"]) * rng.uniform(0.94, 1.06)
    target = {
        "x": round(distance * math.cos(bearing), 4),
        "y": round(float(parameters["target_height"]) * rng.uniform(0.94, 1.06), 4),
        "z": round(distance * math.sin(bearing) + float(parameters["target_depth"]), 4),
        "radius": round(float(parameters["arrival_radius"]), 4),
    }
    initial = _rounded_state(parameters)
    physics = {
        "dt": 0.08,
        "tick_ms": 80,
        "angular_damping": round(float(parameters["angular_damping"]), 5),
        "linear_damping": round(float(parameters["linear_damping"]), 5),
        "torque_gain": round(float(parameters["torque_gain"]), 5),
        "thrust_gain": round(float(parameters["thrust_gain"]), 5),
        "arrival_radius": round(float(parameters["arrival_radius"]), 5),
        "upright_tolerance": round(float(parameters["upright_tolerance"]), 5),
        "speed_limit": round(float(parameters["speed_limit"]), 5),
        "hold_ticks": int(parameters["hold_ticks"]),
        "replay_tick_limit": int(float(task.get("init", {}).get("timeout_sec", 900)) / 0.08),
        "current_seed": rng.randrange(1, 2**32),
        "current_segment_ticks": 60,
        "current_gain": round(float(parameters["thrust_gain"]) * 0.004, 8),
        "current_roll_gain": round(float(parameters["torque_gain"]) * 0.06, 8),
        "action_settle_ticks": ACTION_SETTLE_TICKS,
    }
    public = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "asset_manifest": ASSET_MANIFEST,
        "prompt": "The water keeps flowing and rolling the fish. " + (task.get("natural_language") or "Navigate the lanternfin to the pearl and arrive upright."),
        "generator": {"name": "lanternfin_fluid_current_v2", "variant_count": 2**48},
        "tank": {"width": 4.4, "height": 2.4, "depth": 4.0},
        "initial": initial,
        "fish": copy.deepcopy(initial),
        "target": target,
        "physics": physics,
        "palette": rng.choice(("biolume", "moonwater", "amberglass")),
        "goal": {
            "arrival_radius": physics["arrival_radius"],
            "upright_tolerance": physics["upright_tolerance"],
            "speed_limit": physics["speed_limit"],
            "hold_ticks": physics["hold_ticks"],
        },
    }
    truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "seed": str(seed),
        "initial": copy.deepcopy(initial),
        "target": copy.deepcopy(target),
        "physics": copy.deepcopy(physics),
    }
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth
