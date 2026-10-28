from __future__ import annotations

import hashlib
import math
import random
import copy
from typing import Any


MECHANIC_ID = "photograph_eats_the_room_v2"
WORLD_WIDTH = 24.0
WORLD_HEIGHT = 14.0
FOV_DEG = 76.0
VARIANT_COUNT = 3 * 2 * 2 * 10_000_000_000
PALETTES = ("coral-darkroom", "silver-lavender", "cyanotype-peach", "oxide-polaroid")


def _seed_int(seed: str, salt: str) -> int:
    return int(hashlib.sha256(f"{seed}|{salt}".encode()).hexdigest()[:16], 16)


def _angle_error(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _projection(camera: dict[str, Any], source: dict[str, Any], frustum_margin: float = 0.04) -> dict[str, Any] | None:
    yaw = math.radians(float(camera["yaw_deg"]))
    cosine, sine = math.cos(yaw), math.sin(yaw)
    projected: list[dict[str, float]] = []
    for endpoint in source["endpoints"]:
        dx = float(endpoint["x"]) - float(camera["x"])
        dy = float(endpoint["y"]) - float(camera["y"])
        forward = dx * cosine + dy * sine
        side = -dx * sine + dy * cosine
        if forward <= 0.2:
            return None
        u = 0.5 + side / (2.0 * forward * math.tan(math.radians(FOV_DEG / 2.0)))
        projected.append({"u": round(u, 4), "depth": round(forward, 4)})
    midpoint = source["midpoint"]
    distance = math.hypot(float(midpoint["x"]) - float(camera["x"]), float(midpoint["y"]) - float(camera["y"]))
    if distance > 4.6 or any(not frustum_margin <= item["u"] <= 1.0 - frustum_margin for item in projected):
        return None
    return {"endpoints": projected, "distance": round(distance, 4)}


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed_int(seed, MECHANIC_ID))
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    stage_count = int(parameters.get("stage_count", 2))
    if stage_count not in {1, 2}:
        raise ValueError("photograph room stage_count must be one or two")
    condition_token = f"|d{int(condition['difficulty'])}" if condition else ""
    world_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}".encode()).hexdigest()[:12]
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}{condition_token}".encode()).hexdigest()[:12]
    task_id = str(task.get("id") or "photograph_eats_the_room_v2_seed_0001@0.1")
    lane_y = rng.choice((5.5, 7.0, 8.5))
    source_side = rng.choice((-1, 1))
    source_y = lane_y + source_side * float(parameters.get("source_offset", 2.25))
    capture_yaw = 90 if source_side > 0 else 270
    pit_left = rng.choice((8.0, 8.25))
    pit_width_choices = tuple(float(value) for value in parameters.get("pit_width_choices", (3.0, 3.25)))
    if not pit_width_choices or any(not 1.5 <= value <= 4.0 for value in pit_width_choices):
        raise ValueError("photograph room pit widths are outside supported limits")
    pit_right = pit_left + rng.choice(pit_width_choices)
    wall_x = 16.0 + rng.choice((0.0, 0.25))
    bridge_center = (pit_left + pit_right) / 2.0

    sources = [
        {
            "id": f"beam-{world_id[:5]}", "kind": "beam", "midpoint": {"x": 4.0, "y": source_y},
            "endpoints": [{"x": 3.0, "y": source_y}, {"x": 5.0, "y": source_y}], "length": 2.0,
            "height": 0.75, "tone": rng.randrange(3),
        }
    ]
    if stage_count == 2:
        sources.append({
            "id": f"aperture-{world_id[5:10]}", "kind": "opening", "midpoint": {"x": 13.25, "y": source_y},
            "endpoints": [{"x": 12.5, "y": source_y}, {"x": 14.0, "y": source_y}], "length": 1.5,
            "height": 1.8, "tone": rng.randrange(3),
        })
    sockets = [
        {
            "id": "void-bridge", "operation": "add_walkway", "source_kind": "beam",
            "center": {"x": round(bridge_center, 2), "y": lane_y}, "angle_deg": 0,
            "minimum_length": round(pit_right - pit_left + 0.5, 2), "tolerance": float(parameters.get("socket_tolerance", 0.52)),
        }
    ]
    if stage_count == 2:
        sockets.append({
            "id": "terminal-door", "operation": "carve_opening", "source_kind": "opening",
            "center": {"x": wall_x, "y": lane_y}, "angle_deg": 90,
            "minimum_length": 2.0, "tolerance": float(parameters.get("socket_tolerance", 0.52)),
        })
    room = {
        "width": WORLD_WIDTH, "height": WORLD_HEIGHT, "lane_y": lane_y,
        "void": {"x1": pit_left, "x2": pit_right, "y1": 0.6, "y2": WORLD_HEIGHT - 0.6},
        "divider": {"x": wall_x, "y1": 0.35, "y2": WORLD_HEIGHT - 0.35},
        "terminal": {"x": float(parameters.get("terminal_x", 21.1)), "y": lane_y, "radius": 0.78},
        "capture_marks": [{"x": 4.0, "y": lane_y, "yaw_deg": capture_yaw}],
        "placement_marks": [{"x": round(pit_left - 1.05, 2), "y": lane_y, "yaw_deg": 0}],
    }
    room["camera_sway"] = {
        "seed": rng.randrange(1, 2**32), "tick_ms": 50,
        "extent_deg": float(parameters.get("camera_sway_extent_deg", 12)),
        "minimum_segment_ticks": int(parameters.get("camera_sway_segment_ticks", 100)),
        "segment_tick_variation": 81,
    }
    if stage_count == 2:
        room["capture_marks"].append({"x": 13.25, "y": lane_y, "yaw_deg": capture_yaw})
        room["placement_marks"].append({"x": round(wall_x - 2.45, 2), "y": lane_y, "yaw_deg": 0})
    controls = {
        "move_speed": 2.35, "move_tick_ms": 70, "turn_step_deg": 15,
        "plane_lateral_min": -2.0, "plane_lateral_max": 2.0,
        "plane_depth_min": 1.0, "plane_depth_max": 4.5,
        "plane_rotation_step_deg": int(parameters.get("plane_rotation_step_deg", 15)), "plane_scale_step": float(parameters.get("plane_scale_step", 0.1)),
        "plane_scale_min": 0.6, "plane_scale_max": 2.4,
        "fov_deg": FOV_DEG,
    }
    qualification = {
        "capture_range": float(parameters.get("capture_range", 4.6)), "minimum_move_samples": 30, "minimum_travel": 12.0,
        "maximum_move_sample_gap_ms": 135,
        "collision_radius": 0.23, "bridge_half_width": float(parameters.get("bridge_half_width", 0.48)),
    }
    initial_camera = {"x": 2.0, "y": lane_y, "yaw_deg": 0}
    public_state = {
        "benchmark": "gym_anything_rt", "mechanic_id": MECHANIC_ID, "task_id": task_id,
        "challenge_id": challenge_id, "asset_manifest": "shared_runtime/assets/provenance/incubator_full_build_v1.json",
        "prompt": (task.get("natural_language") or "Photograph useful geometry, place the print in the room, develop it into reality, and reach the terminal.") + " The camera keeps swaying. Correct its view as you frame, place, and walk.",
        "generator": {"name": "perspective_photo_geometry_swaying_camera_v2", "variant_count": VARIANT_COUNT},
        "plate_id": f"VF-{world_id[:4].upper()}-{rng.randint(100, 999)}", "palette": rng.choice(PALETTES),
        "room": room, "sources": sources, "sockets": sockets, "initial_camera": initial_camera,
        "controls": controls, "qualification": qualification, "submit_label": "VERIFY ROOM",
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID, "task_id": task_id, "seed": seed, "challenge_id": challenge_id,
        "room": room, "sources": sources, "sockets": sockets, "initial_camera": initial_camera,
        "controls": controls, "qualification": qualification,
        "solution": {
            "captures": [{"camera": room["capture_marks"][0], "source_id": sources[0]["id"]}],
            "placements": [{"camera": room["placement_marks"][0], "socket_id": sockets[0]["id"], "rotation_deg": 0, "scale": float(parameters.get("bridge_scale", 1.9))}],
            "terminal": room["terminal"],
        },
        "variant_count": VARIANT_COUNT,
    }
    if stage_count == 2:
        ground_truth["solution"]["captures"].append({"camera": room["capture_marks"][1], "source_id": sources[1]["id"]})
        ground_truth["solution"]["placements"].append({"camera": room["placement_marks"][1], "socket_id": sockets[1]["id"], "rotation_deg": 90, "scale": float(parameters.get("opening_scale", 1.5))})
    for capture, source in zip(room["capture_marks"], sources):
        assert _projection(capture, source, float(parameters.get("frustum_margin", 0.04))) is not None
    assert sockets[0]["minimum_length"] <= sources[0]["length"] * float(parameters.get("bridge_scale", 1.9))
    if stage_count == 2:
        assert sockets[1]["minimum_length"] <= sources[1]["length"] * float(parameters.get("opening_scale", 1.5))
        assert pit_right < room["placement_marks"][1]["x"] < wall_x
    if condition:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    return public_state, ground_truth
