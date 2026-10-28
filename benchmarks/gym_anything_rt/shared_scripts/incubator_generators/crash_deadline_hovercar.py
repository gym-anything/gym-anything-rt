from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "crash_deadline_hovercar"
STAGE = {"width": 980, "height": 480}

_BASE_WINDOWS = ((18, 62), (59, 107), (104, 152), (149, 198), (195, 248))
_BASE_TARGET_POSITIONS = ((650, 92), (795, 175), (870, 82), (690, 360), (835, 315), (760, 236))
_BASE_OBSTACLES = (
    {"id": "barrier-a", "world_x": 280, "lane_offset": -28, "width": 48, "height": 34},
    {"id": "barrier-b", "world_x": 500, "lane_offset": 30, "width": 52, "height": 34},
    {"id": "barrier-c", "world_x": 720, "lane_offset": -30, "width": 46, "height": 36},
    {"id": "barrier-d", "world_x": 930, "lane_offset": 27, "width": 54, "height": 32},
    {"id": "barrier-e", "world_x": 1140, "lane_offset": -29, "width": 48, "height": 36},
    {"id": "barrier-f", "world_x": 1320, "lane_offset": 28, "width": 50, "height": 34},
    {"id": "barrier-g", "world_x": 1510, "lane_offset": -31, "width": 54, "height": 36},
    {"id": "barrier-h", "world_x": 1690, "lane_offset": 30, "width": 50, "height": 34},
)


def _windows(parameters: dict[str, Any], count: int) -> list[tuple[int, int]]:
    if str(parameters.get("window_profile", "current")) == "current":
        if count != len(_BASE_WINDOWS):
            raise ValueError("the current hovercar window profile requires five checks")
        return list(_BASE_WINDOWS)
    first = int(parameters.get("first_window_tick", 22))
    duration = int(parameters.get("window_duration_ticks", 55))
    stride = int(parameters.get("window_stride_ticks", 58))
    if not (0 <= first and 8 <= duration and duration >= int(parameters.get("required_tick_max", 1))):
        raise ValueError("hovercar inspection windows are outside supported limits")
    return [(first + index * stride, first + index * stride + duration) for index in range(count)]


def _seed_int(seed: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}|{MECHANIC_ID}".encode()).digest()[:8], "big")


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed_int(seed))
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    check_count = int(parameters.get("check_count", 5))
    obstacle_count = int(parameters.get("obstacle_count", 6))
    if not (2 <= check_count <= len(_BASE_TARGET_POSITIONS)):
        raise ValueError("hovercar check count is outside supported limits")
    if not (2 <= obstacle_count <= len(_BASE_OBSTACLES)):
        raise ValueError("hovercar obstacle count is outside supported limits")
    phase = round(rng.uniform(-1.5, 1.5), 6)
    amplitude = rng.randint(int(parameters.get("road_amplitude_min", 38)), int(parameters.get("road_amplitude_max", 52)))
    period = rng.randint(int(parameters.get("road_period_min", 165)), int(parameters.get("road_period_max", 195)))
    hues = rng.sample(["#b8ff58", "#60e6ff", "#ffcb66", "#ff7699", "#b995ff", "#77f2b3"], check_count)
    motif_pool = ("ring-notch", "split-kite", "triple-fin", "hollow-cross", "offset-orbit")
    if check_count > len(motif_pool):
        motif_pool = (*motif_pool, "split-arc")
    motifs = rng.sample(motif_pool, check_count)
    windows = _windows(parameters, check_count)
    orbit_scale = float(parameters.get("target_orbit_scale", 1.0))
    motion_scale = float(parameters.get("target_motion_scale", 1.0))
    required_ticks = tuple(int(value) for value in parameters.get("required_ticks", (11, 12, 13)))
    if not required_ticks or min(required_ticks) < 4 or max(required_ticks) > 20:
        raise ValueError("hovercar dwell requirement is outside supported limits")
    targets = []
    for index, (start, end) in enumerate(windows):
        orbit_x = rng.randint(34, 54)
        orbit_y = rng.randint(22, 36)
        target = {
            "id": f"check-{index + 1}", "motif": motifs[index], "color": hues[index],
            "window_start": start, "window_end": end,
            "base_x": _BASE_TARGET_POSITIONS[index][0], "base_y": _BASE_TARGET_POSITIONS[index][1],
            "orbit_x": orbit_x if orbit_scale == 1 else round(orbit_x * orbit_scale, 6),
            "orbit_y": orbit_y if orbit_scale == 1 else round(orbit_y * orbit_scale, 6),
            "phase": round(rng.uniform(0, math.tau), 6), "radius": int(parameters.get("target_radius", 29)),
            "required_ticks": rng.choice(required_ticks),
        }
        if motion_scale != 1:
            target["motion_scale"] = motion_scale
        targets.append(target)
    obstacles = [copy.deepcopy(item) for item in _BASE_OBSTACLES[:obstacle_count]]
    task_id = str(task.get("id") or "crash_deadline_hovercar_seed_0001@0.1")
    level = int((condition or {}).get("difficulty", 4))
    condition_token = f"|d{level}|{task_id}" if condition else ""
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}{condition_token}".encode()).hexdigest()[:12]
    physics = {
        "tick_ms": 50, "start_speed": 30.0, "min_speed": 18.0, "max_speed": 86.0,
        "acceleration": float(parameters.get("acceleration", 3.4)), "brake": float(parameters.get("brake", 6.0)), "drag": float(parameters.get("drag", 0.72)),
        "steer_gain": float(parameters.get("steer_gain", 2.35)), "lateral_damping": float(parameters.get("lateral_damping", 0.84)),
        "road_half_width": int(parameters.get("road_half_width", 110)), "car_half_width": 24, "car_half_height": 14,
        "finish_progress": int(parameters.get("finish_progress", 1400)), "deadline_tick": int(parameters.get("deadline_tick", 330)),
        "road_amplitude": amplitude, "road_period": period, "road_phase": phase,
    }
    full_throttle_speed = physics["start_speed"]
    full_throttle_progress = 0.0
    earliest_finish = 0
    while full_throttle_progress < physics["finish_progress"]:
        earliest_finish += 1
        full_throttle_speed = min(physics["max_speed"], full_throttle_speed + physics["acceleration"] - physics["drag"])
        full_throttle_progress += full_throttle_speed / 10
    public = {
        "benchmark": "gym_anything_rt", "mechanic_id": MECHANIC_ID, "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Complete each hover check while keeping the vehicle from crashing.",
        "submit_label": "TRANSMIT FLIGHT RECORD", "stage": STAGE, "physics": physics,
        "targets": targets, "obstacles": obstacles,
        "generator": {"name": "fixed_step_divided_attention_course_v2", "variant_count": 88_400_000_000},
        "requirements": {"check_count": len(targets), "minimum_motion_during_dwell": float(parameters.get("minimum_motion_during_dwell", 1.5))},
        "clearance_audit": {"road_margin": int(parameters.get("road_margin", 56)), "target_window_slack_ticks": int(parameters.get("target_window_slack_ticks", 25)), "obstacle_bypass_margin": int(parameters.get("obstacle_bypass_margin", 24)),
                            "full_throttle_finish_tick": earliest_finish, "final_window_start": windows[-1][0]},
        "asset_manifest": "shared_runtime/assets/provenance/incubator_full_build_v1.json",
    }
    truth = {**public, "seed": seed}
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    assert all(item["window_end"] - item["window_start"] >= item["required_ticks"] + int(parameters.get("minimum_window_slack_ticks", 12)) for item in targets)
    assert physics["finish_progress"] > max(item["world_x"] for item in obstacles)
    assert earliest_finish < windows[-1][0], "full throttle must force a braking/coast tradeoff before the final inspection"
    return public, truth
