from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "board_game_captcha_nonrealtime"
DONOR_MECHANIC_ID = "board_game_captcha_v2"
STAGE = {"width": 900, "height": 520}
VARIANT_COUNT = 14_800_000_000


def _seed(seed: str) -> int:
    # Keep geometry/physics generation stable across the renamed counterpart.
    return int(hashlib.sha256(f"{seed}|{DONOR_MECHANIC_ID}|tilt-v2".encode()).hexdigest()[:16], 16)


def _mirror_point(point: list[float], mirror: bool) -> list[float]:
    return [STAGE["width"] - point[0], point[1]] if mirror else list(point)


def _mirror_rect(rect: dict[str, Any], mirror: bool) -> dict[str, Any]:
    if not mirror:
        return copy.deepcopy(rect)
    return {**rect, "x": STAGE["width"] - rect["x"] - rect["width"]}


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed(seed))
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if "external_tilt" in parameters or "hole_gravity" in parameters:
        raise ValueError("the counterpart uses its fixed half-strength board tilt")
    lamp_count = int(parameters.get("lamp_count", 3))
    wall_count = int(parameters.get("wall_count", 3))
    hazard_count = int(parameters.get("hazard_count", 3))
    if not 1 <= lamp_count <= 5 or not 0 <= wall_count <= 5 or not 0 <= hazard_count <= 5:
        raise ValueError("tilt board counts are outside supported limits")
    task_id = str(task.get("id") or "board_game_captcha_nonrealtime_seed_0001@0.1")
    condition_token = f"|d{condition['difficulty']}|{task.get('id')}" if condition else ""
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}{condition_token}".encode()).hexdigest()[:13]
    mirror = rng.choice((False, True))
    start = _mirror_point([88, 438], mirror)
    goal = {"id": "goal-cup", "position": _mirror_point([824, 112], mirror), "radius": int(parameters.get("goal_radius", 28))}
    switch_points = [[205, 392], [410, 208], [656, 350], [760, 400], [790, 210]]
    switch_colors = ("#ef6c72", "#f1c665", "#68d8c1", "#8fb5ff", "#dc8cf2")
    switches = [
        {"id": f"gate-{index + 1}", "sequence": index, "position": _mirror_point(point, mirror), "radius": int(parameters.get("lamp_radius", 24)), "color": switch_colors[index]}
        for index, point in enumerate(switch_points[:lamp_count])
    ]
    walls = [
        {"id": "wall-a", "x": 292, "y": 270, "width": 28, "height": 250},
        {"id": "wall-b", "x": 534, "y": 0, "width": 28, "height": 300},
        {"id": "wall-c", "x": 708, "y": 210, "width": 24, "height": 165},
        {"id": "wall-d", "x": 790, "y": 250, "width": 22, "height": 120},
        {"id": "wall-e", "x": 120, "y": 0, "width": 24, "height": 180},
    ][:wall_count]
    walls = [_mirror_rect(wall, mirror) for wall in walls]
    hazards = [
        {"id": "well-1", "position": _mirror_point([250, 160], mirror), "radius": 20},
        {"id": "well-2", "position": _mirror_point([585, 445], mirror), "radius": 22},
        {"id": "well-3", "position": _mirror_point([720, 160], mirror), "radius": 18},
        {"id": "well-4", "position": _mirror_point([360, 430], mirror), "radius": 19},
        {"id": "well-5", "position": _mirror_point([770, 470], mirror), "radius": 17},
    ][:hazard_count]
    if lamp_count <= 2:
        waypoints = [[205, 392], [250, 235], [410, 208], [600, 200], [760, 160], [824, 112]][: 2 * lamp_count]
        waypoints.append([824, 112])
        switch_waypoint_indices = list(range(0, lamp_count * 2, 2))
    elif lamp_count == 3:
        waypoints = [[205, 392], [246, 215], [410, 208], [478, 340], [656, 350], [765, 392], [824, 112]]
        switch_waypoint_indices = [0, 2, 4]
    else:
        waypoints = [[205, 392], [246, 215], [410, 208], [478, 340], [656, 350], [760, 400], [760, 400], [760, 230]]
        switch_waypoint_indices = [0, 2, 4, 5]
        if lamp_count == 5:
            waypoints.append([790, 210])
            switch_waypoint_indices.append(8)
        waypoints.append([824, 112])
    waypoints = [_mirror_point(point, mirror) for point in waypoints]
    fixed_tilt_phase = rng.uniform(0, math.tau)
    physics = {
        "tick_ms": int(parameters.get("tick_ms", 50)),
        "acceleration": float(parameters.get("acceleration", 190.0)),
        "friction": float(parameters.get("friction", 0.958)),
        "maximum_speed": float(parameters.get("maximum_speed", 178.0)),
        "bounce": float(parameters.get("bounce", 0.42)),
        "ball_radius": float(parameters.get("ball_radius", 13.0)),
        # The donor's initial 50% tilt is retained, but it no longer changes
        # autonomously while the player studies the board.
        "fixed_tilt": [
            0.5 * math.cos(fixed_tilt_phase),
            0.5 * math.sin(fixed_tilt_phase),
        ],
    }
    requirements = {
        "maximum_events": 6500,
        "maximum_event_time_ms": 300_000,
        "ticks_per_action": 8,
    }
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or f"Roll through {lamp_count} lamps in order, avoid the wells and open edges, then reach the cup. Counter the fixed board tilt shown by the red arrow; each deliberate tilt action settles a short roll.",
        "submit_label": "CERTIFY THE RUN",
        "asset_manifest": "shared_runtime/assets/provenance/board_game_captcha_v2.json",
        "generator": {"name": "gyroscopic_tilt_board_v2_action_settled_fixed_tilt", "variant_count": VARIANT_COUNT},
        "stage": STAGE,
        "theme": rng.choice(("oxidized_arcade", "night_fair", "municipal_lab")),
        "start": start,
        "goal": goal,
        "switches": switches,
        "walls": walls,
        "hazards": hazards,
        "physics": physics,
        "requirements": requirements,
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "stage": STAGE,
        "start": start,
        "goal": goal,
        "switches": switches,
        "walls": walls,
        "hazards": hazards,
        "physics": physics,
        "requirements": requirements,
        "solver_waypoints": waypoints,
        "solver_switch_waypoint_indices": switch_waypoint_indices,
        "variant_count": VARIANT_COUNT,
    }
    if condition:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    assert [switch["sequence"] for switch in switches] == list(range(lamp_count))
    return public_state, ground_truth
