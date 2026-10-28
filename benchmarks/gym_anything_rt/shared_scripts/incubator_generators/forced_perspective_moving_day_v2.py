from __future__ import annotations

import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "forced_perspective_moving_day_v2"


def _seed(seed: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}|{MECHANIC_ID}".encode()).digest()[:8], "big")


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed(seed))
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    mirror = rng.choice((-1, 1))
    focal_choices = tuple(int(value) for value in parameters.get("focal_choices", (460, 500, 540)))
    if not focal_choices:
        raise ValueError("forced perspective requires at least one focal-length choice")
    yaw_min = float(parameters.get("yaw_abs_min", 0.018))
    yaw_max = float(parameters.get("yaw_abs_max", 0.042))
    if yaw_min < 0 or yaw_max < yaw_min:
        raise ValueError("forced perspective yaw bounds are invalid")
    focal = rng.choice(focal_choices)
    yaw = 0.0 if yaw_max == 0 else round(rng.choice((-1, 1)) * rng.uniform(yaw_min, yaw_max), 6)
    palettes = (
        {"sky": "#d9ecda", "floor": "#d0c9b4", "wall": "#27332b", "sign": "#f5cf58", "crate": "#8ce67f", "void": "#151421", "alert": "#e85b54"},
        {"sky": "#dbe5ef", "floor": "#c9c2af", "wall": "#24323c", "sign": "#ffb85e", "crate": "#72ddc6", "void": "#121521", "alert": "#f06465"},
        {"sky": "#eee3cf", "floor": "#c9bba5", "wall": "#382d28", "sign": "#f1d565", "crate": "#91e27b", "void": "#17131d", "alert": "#e75d58"},
    )
    palette = rng.choice(palettes)
    camera = {"x": 0.0, "y": 1.6, "z": 2.0, "yaw": yaw, "focal": focal, "center": [490, 165], "near": 0.6}
    objects = [
        {"id": "sign", "role": "bridge", "center": [-2.2 * mirror, 1.1, 6.5], "scale": 1.0, "base_size": [1.3, 2.2, 0.18], "reference_size": 1.3, "orientation": "upright"},
        {"id": "crate", "role": "key", "center": [2.4 * mirror, 0.7, 8.0], "scale": 1.0, "base_size": [1.4, 1.4, 1.4], "reference_size": 1.4, "orientation": "box"},
    ]
    slot = {
        "id": "key-slot",
        "center": [1.75 * mirror, 4.65],
        "size": [float(value) for value in parameters.get("slot_size", (1.6, 1.7))],
        "max_scale": float(parameters.get("slot_max_scale", 0.56)),
    }
    world = {
        "x_bounds": [-6, 6], "z_bounds": [0, 24],
        "gap": [float(value) for value in parameters.get("gap", (11.5, 15.0))],
        "door": {"z": 19, "thickness": 0.65, "half_gap": float(parameters.get("door_half_gap", 1.25))}, "exit_z": 22.4,
        "avatar_radius": float(parameters.get("avatar_radius", 0.34)),
        "move_step": float(parameters.get("move_step", 0.32)), "tick_ms": 50,
    }
    world["door"]["motion"] = {
        "seed": rng.randrange(1, 2**32),
        "extent": float(parameters.get("door_motion_extent", 2.2)),
        "minimum_segment_ticks": int(parameters.get("door_motion_segment_ticks", 90)),
        "segment_tick_variation": 61,
    }
    world["dolly_drift"] = {
        "seed": rng.randrange(1, 2**32),
        "extent": float(parameters.get("dolly_drift_speed", 1.25)),
        "minimum_segment_ticks": 50,
        "segment_tick_variation": 91,
    }
    bridge_zone = {
        "id": "void-bridge",
        "center": [0, sum(world["gap"]) / 2],
        # This guide is derived from the active void, rather than pretending
        # to be a separately graded difficulty knob.  L4 remains the original
        # 3.4 by 3.5 guide at z=13.25.
        "size": [3.4, world["gap"][1] - world["gap"][0]],
        "min_scale": float(parameters.get("bridge_min_scale", 2.0)),
    }
    depth_controls = {
        "minimum": float(parameters.get("depth_minimum", 2.0)),
        "maximum": float(parameters.get("depth_maximum", 13.5)),
        "step": float(parameters.get("depth_step", 0.5)),
    }
    task_id = str(task.get("id") or "forced_perspective_moving_day_v2_seed_0001@0.1")
    condition_token = (
        f"|d{condition['difficulty']}|{condition['interaction']}|{task_id}"
        if condition else ""
    )
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}{condition_token}".encode()).hexdigest()[:12]
    public = {
        "benchmark": "gym_anything_rt", "mechanic_id": MECHANIC_ID, "task_id": task_id, "challenge_id": challenge_id,
        "prompt": (task.get("natural_language") or "Resize the available objects through perspective and move the shipment through the impossible doorway.") + " Steer against the camera dolly's sideways drift and follow the sliding doorway. Sliding off the bridge returns you to the near bank.",
        "submit_label": "CERTIFY IMPOSSIBLE MOVE", "stage": {"width": 980, "height": 480},
        "camera": camera, "world": world, "objects": objects, "slot": slot, "bridge_zone": bridge_zone, "palette": palette,
        "depth_controls": depth_controls,
        "requirements": {
            "pick_radius_px": int(parameters.get("pick_radius_px", 34)),
            "projection_tolerance": float(parameters.get("projection_tolerance", 0.08)),
        },
        "clearance_audit": {"bridge_required_depth": 4.38, "bridge_worst_case_length": 5.1, "bridge_width_margin": 0.5, "door_gap_margin": 0.57, "slot_scale_margin": 0.04},
        "generator": {"name": "ray_plane_apparent_scale_sliding_door_v2", "variant_count": 11_600_000_000},
        "asset_manifest": "shared_runtime/assets/provenance/incubator_full_build_v1.json",
    }
    truth = {**public, "seed": seed, "mirror": mirror,
             "solver_targets": {"crate": [slot["center"][0], slot["center"][1]], "sign": [bridge_zone["center"][0], bridge_zone["center"][1]]}}
    if condition:
        public["control_condition"] = condition.copy()
        truth["control_condition"] = condition.copy()
    sign_depth = math.cos(yaw) * (bridge_zone["center"][1] - camera["z"]) + math.sin(yaw) * (bridge_zone["center"][0] - camera["x"])
    sign_initial_depth = math.cos(yaw) * (objects[0]["center"][2] - camera["z"]) + math.sin(yaw) * (objects[0]["center"][0] - camera["x"])
    resulting_scale = sign_depth / sign_initial_depth
    # These are generator reachability checks, not difficulty controls.  The
    # active acceptance thresholds above remain the visible bridge/slot rules.
    assert resulting_scale >= bridge_zone["min_scale"] + 0.05
    worst_rounded_scale = (sign_depth - depth_controls["step"] / 2) / sign_initial_depth
    required_support_length = world["gap"][1] - world["gap"][0] + 2 * world["avatar_radius"] + 0.20 + depth_controls["step"]
    assert objects[0]["base_size"][1] * worst_rounded_scale >= required_support_length
    crate_depth = math.cos(yaw) * (slot["center"][1] - camera["z"]) + math.sin(yaw) * (slot["center"][0] - camera["x"])
    crate_initial_depth = math.cos(yaw) * (objects[1]["center"][2] - camera["z"]) + math.sin(yaw) * (objects[1]["center"][0] - camera["x"])
    assert crate_depth / crate_initial_depth <= slot["max_scale"] - 0.05
    return public, truth
