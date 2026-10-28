from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "three_camera_claw_machine_nonrealtime"
# Keep the renamed counterpart's seed stream aligned with the evaluated V2
# donor.  The mechanic name is a contract identity, not a puzzle-layout seed.
SEED_NAMESPACE = "three_camera_claw_machine_v2"


def _seed(seed: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}|{SEED_NAMESPACE}".encode()).digest()[:8], "big")


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    level = int((condition or {}).get("difficulty", 4))
    if condition is not None and level not in {1, 2, 3, 4, 5}:
        raise ValueError("three-camera claw difficulty must be 1 through 5")
    interaction = str((condition or {}).get("interaction") or "simplified")
    if interaction not in {"simplified", "full"}:
        raise ValueError("three-camera claw interaction must be simplified or full")

    # Keep this sequence intact for the uncontrolled task and the controlled
    # L4 reference.  The exact current generator is the L4 world, rather than
    # a new configuration that happens to be labelled L4.
    rng = random.Random(_seed(seed)); mirror = rng.choice((-1, 1))
    palettes = (
        {"cage": "#2a2c2f", "feed": "#d7ead0", "artifact": "#f3a447", "claw": "#d64c43", "chute": "#60c7a0"},
        {"cage": "#202c35", "feed": "#cce7e1", "artifact": "#ffb35c", "claw": "#ef626c", "chute": "#5ac4d8"},
        {"cage": "#342b28", "feed": "#e7ddc4", "artifact": "#eaa645", "claw": "#d84d63", "chute": "#70c497"},
    )
    palette = rng.choice(palettes)
    target_center = [round((2.35 + rng.choice((-.15, 0, .15))) * mirror, 3), .95, round(1.8 + rng.choice((-.2, 0, .2)), 3)]
    objects = [
        {"id": "artifact-a", "center": target_center, "radius": .43, "marked": True, "color": palette["artifact"]},
        {"id": "artifact-b", "center": [round((-2.3 + rng.choice((-.2, 0, .2))) * mirror, 3), .9, 1.8], "radius": .43, "marked": False, "color": "#7c91a3"},
        {"id": "artifact-c", "center": [round(2.15 * mirror, 3), .9, round(-1.35 + rng.choice((-.2, 0, .2)), 3)], "radius": .43, "marked": False, "color": "#8b7aa1"},
    ]
    # Keep the entire moving cargo volume clear of the floor and front baffle.
    target_center[1] = 1.2
    target_center[2] += .55
    obstacles = [
        {"id": "crossbar", "center": [0, 2.55, round(.15 + rng.choice((-.15, 0, .15)), 3)], "half": [2.15, .38, .5]},
        {"id": "post", "center": [round(-1.15 * mirror, 3), 2.05, round(-1.55 + rng.choice((-.15, 0, .15)), 3)], "half": [.42, 1.55, .42]},
        {"id": "baffle", "center": [round(2.8 * mirror, 2), 2.0, round(-.35 + rng.choice((-.15, 0, .15)), 3)], "half": [.38, 1.35, 1.0]},
    ]
    chute = {"center": [round((-3.65 + rng.choice((-.1, 0, .1))) * mirror, 3), 1.0, round(-3.55 + rng.choice((-.1, 0, .1)), 3)], "half": [.78, .8, .78]}
    camera_scale = rng.choice((20, 21, 22))
    cameras = {
        "top": {"matrix": [[camera_scale, 0, 0], [0, 0, camera_scale]], "origin": [170, 115], "delay": 0, "label": "OVERHEAD", "depth_axis": 1, "depth_sign": 1},
        "front": {"matrix": [[camera_scale, 0, 0], [0, -camera_scale, 0]], "origin": [170, 218], "delay": 2, "label": "FRONT", "depth_axis": 2, "depth_sign": -1},
        "side": {"matrix": [[0, 0, camera_scale], [0, -camera_scale, 0]], "origin": [170, 218], "delay": 4, "label": "SIDE", "depth_axis": 0, "depth_sign": -1},
    }
    world = {"bounds": {"x": [-5, 5], "y": [.45, 6], "z": [-5, 5]}, "claw_radius": .28, "tick_seconds": .12,
             "acceleration": rng.choice((.26, .28, .3)), "max_speed": .72, "damping": rng.choice((.8, .82, .84)), "collision_step": .06, "capture_distance": .78}

    if condition is not None and level != 4:
        try:
            distractor_count = int(parameters["distractor_count"])
            obstacle_profile = str(parameters["obstacle_profile"])
            camera_delays = [int(value) for value in parameters["camera_delay_ticks"]]
            controlled_scale = float(parameters["camera_scale"])
            controlled_acceleration = float(parameters["acceleration"])
            controlled_damping = float(parameters["damping"])
            controlled_capture_distance = float(parameters["capture_distance"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("three-camera claw controlled profile is incomplete") from exc
        if not 0 <= distractor_count <= 4:
            raise ValueError("three-camera claw distractor_count must be 0 through 4")
        if len(camera_delays) != 3 or any(delay < 0 for delay in camera_delays):
            raise ValueError("three-camera claw camera_delay_ticks must contain three nonnegative delays")
        if obstacle_profile not in {"open", "crossbar", "crossbar_post", "dense"}:
            raise ValueError("three-camera claw obstacle_profile is invalid")

        distractors = objects[1:]
        extra_distractors = [
            {"id": "artifact-d", "center": [round(-.55 * mirror, 3), .9, round(-2.55 + rng.choice((-.15, 0, .15)), 3)], "radius": .43, "marked": False, "color": "#638e88"},
            {"id": "artifact-e", "center": [round(-3.1 * mirror, 3), .9, round(.55 + rng.choice((-.15, 0, .15)), 3)], "radius": .43, "marked": False, "color": "#a68167"},
        ]
        objects = [objects[0], *(distractors + extra_distractors)[:distractor_count]]
        if obstacle_profile == "open":
            obstacles = []
        elif obstacle_profile == "crossbar":
            obstacles = obstacles[:1]
        elif obstacle_profile == "crossbar_post":
            obstacles = obstacles[:2]
        else:
            obstacles = [
                *obstacles,
                {"id": "midrail", "center": [0, 3.05, -2.15], "half": [1.9, .3, .45]},
            ]
        for view_id, delay in zip(("top", "front", "side"), camera_delays):
            cameras[view_id]["delay"] = delay
        for view in cameras.values():
            view["matrix"] = [[controlled_scale * value / camera_scale for value in row] for row in view["matrix"]]
        world.update({
            "acceleration": controlled_acceleration,
            "damping": controlled_damping,
            "capture_distance": controlled_capture_distance,
        })
    world.update(tick_seconds=.04, acceleration=.009, max_speed=.085, damping=.94,
                 capture_distance=.56)
    world['wind'] = {'seed': rng.getrandbits(32), 'span_ms': 1900,
                     'amplitude': [.0017, .0008, .0017]}
    for obj in objects:
        obj['motion'] = {'seed': rng.getrandbits(32), 'span_ms': 1700,
                         'amplitude': [.58, .12, .48]}
    chute['motion'] = {'seed': rng.getrandbits(32), 'span_ms': 1800,
                       'amplitude': [.38, .12, .45]}
    chute['half'] = [.78, .8, .78]
    initial = {"position": [0, 5.25, -3.85], "velocity": [0, 0, 0], "gripper": "open"}
    task_id = str(task.get("id") or "three_camera_claw_machine_nonrealtime_seed_0001@0.1")
    # The controlled suite needs a distinct replay identity per difficulty,
    # while the uncontrolled task retains its historical identity.  Interaction
    # intentionally does not enter this token: full and simplified render the
    # same generated world and differ only in their bound visible input surface.
    condition_token = f"|d{level}" if condition is not None else ""
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}{condition_token}".encode()).hexdigest()[:12]
    public = {
        "benchmark": "gym_anything_rt", "mechanic_id": MECHANIC_ID, "task_id": task_id, "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Retrieve the marked artifact using only the three camera feeds.",
        "submit_label": "CERTIFY CCTV RETRIEVAL", "world": world, "initial": initial, "objects": objects,
        "obstacles": obstacles, "chute": chute, "cameras": cameras, "palette": palette,
        # Non-real-time progression is task-local and action-triggered.  A
        # valid input edge advances one fixed physics tick; no browser
        # clock or render loop may advance the world while the player waits.
        "requirements": {"max_ticks": 15000, "max_events": 6000,
                          "action_tick_stride": 1,
                          "required_feeds": ["top", "front", "side"]},
        "generator": {"name": "continuous_cctv_moving_cargo_v2", "variant_count": 10**18,
                      "variant_count_kind": "bounded layouts and independent seeded cargo, chute and wind trajectories"},
        "asset_manifest": "shared_runtime/assets/provenance/incubator_full_build_v1.json",
        "render_boundary": "The browser necessarily receives cage/object geometry and the marked visual flag used by CCTV rendering, so page internals can identify the target. It receives no safe waypoint route or privileged world-control action.",
    }
    safe_y = 5.25
    truth = {**public, "seed": seed, "mirror": mirror, "target_id": "artifact-a",
             "oracle": "gym_anything_rt.tools.nonrealtime_four_v2_oracle:claw"}
    if condition is not None:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    for obstacle in obstacles:
        assert obstacle["center"][1] + obstacle["half"][1] + world["claw_radius"] < safe_y
    assert math.dist(target_center, chute["center"]) > 4
    return public, truth
