from __future__ import annotations

import copy
import hashlib
import random
from typing import Any


MECHANIC_ID = "anthill_front"


def _stable_rng(seed: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}|{MECHANIC_ID}|v1".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _lane_sequence(raw: list[str], first: str) -> list[str]:
    answer: list[str] = []
    for item in raw:
        if item == "seeded":
            answer.append(first)
        elif item == "opposite":
            answer.append("south" if first == "north" else "north")
        elif item in {"north", "south"}:
            answer.append(item)
        else:
            raise ValueError("unsupported raid lane")
    return answer


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = _stable_rng(seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    level = int((condition or {}).get("difficulty", 3))
    width = int(parameters.get("world_width", 30))
    height = int(parameters.get("world_height", 16))
    worker_count = int(parameters.get("worker_count", 5))
    initial_seeds = int(parameters.get("initial_seeds", 2))
    brood_ready = bool(parameters.get("brood_ready", False))
    dig_workers = int(parameters.get("dig_workers", 2))
    dig_work = int(parameters.get("dig_work", 70))
    hidden_opening = bool(parameters.get("hidden_opening", True))
    scout_ticks = int(parameters.get("scout_ticks", 40))
    raid_counts = [int(value) for value in parameters.get("raid_counts", [4])]
    spawn_ticks = [int(value) for value in parameters.get("raid_spawn_ticks", [180])]
    impact_ticks = [int(value) for value in parameters.get("raid_impact_ticks", [270])]
    first_lane = rng.choice(("north", "south"))
    raid_lanes = _lane_sequence(list(parameters.get("raid_lanes", ["seeded"])), first_lane)
    enemy_queen_hp = int(parameters.get("enemy_queen_hp", 6))
    max_ticks = int(parameters.get("max_ticks", 720))

    if not (18 <= width <= 36 and 10 <= height <= 20):
        raise ValueError("anthill world dimensions are outside supported limits")
    if not (4 <= worker_count <= 7 and 0 <= dig_workers <= worker_count):
        raise ValueError("anthill worker contract is invalid")
    if not (len(raid_lanes) == len(raid_counts) == len(spawn_ticks) == len(impact_ticks) and 1 <= len(raid_lanes) <= 2):
        raise ValueError("anthill raid schedule is malformed")
    if any(spawn + 24 >= impact for spawn, impact in zip(spawn_ticks, impact_ticks)):
        raise ValueError("anthill raid impact must leave a visible response interval")

    task_id = str(task.get("id") or "anthill_front_seed_0001@0.1")
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}|d{level}".encode("utf-8")).hexdigest()[:12]
    palette = rng.choice(("amber", "ochre", "lichen"))
    layout_variant = rng.randrange(1 << 24)
    layout_rng = random.Random(layout_variant)
    center_y = round(height / 2 + layout_rng.uniform(-0.34, 0.34), 2)
    lane_y = {
        "north": round(height * layout_rng.uniform(0.25, 0.31), 2),
        "south": round(height * layout_rng.uniform(0.69, 0.75), 2),
    }
    home_queen = {"x": round(layout_rng.uniform(1.62, 1.98), 2), "y": center_y, "hp": 3}
    enemy_queen = {
        "x": round(width - layout_rng.uniform(1.72, 2.18), 2),
        "y": round(center_y + layout_rng.uniform(-0.38, 0.38), 2),
        "hp": enemy_queen_hp,
    }
    brood_side = -1 if layout_rng.random() < 0.5 else 1
    brood = {
        "x": round(layout_rng.uniform(3.85, 4.75), 2),
        "y": round(center_y + brood_side * layout_rng.uniform(0.9, 1.45), 2),
    }
    seed_pile = {
        "x": round(layout_rng.uniform(6.35, 7.75), 2),
        "y": round(center_y - brood_side * layout_rng.uniform(1.15, 1.85), 2),
    }
    listening_front = {
        "x": round(width * layout_rng.uniform(0.53, 0.60), 2),
        "y": round(center_y + layout_rng.uniform(-0.48, 0.48), 2),
    }
    rally = {
        "x": round(layout_rng.uniform(4.92, 5.42), 2),
        "y": round(center_y + layout_rng.uniform(-0.22, 0.22), 2),
    }
    defense_post_x = round(layout_rng.uniform(8.75, 9.65), 2)
    raids = []
    for index, (lane, count, spawn, impact) in enumerate(zip(raid_lanes, raid_counts, spawn_ticks, impact_ticks)):
        expansion_duration = 54 + level * 3 + index * 5
        expansion_complete = max(1, spawn - 12)
        expansion_start = max(0, expansion_complete - expansion_duration)
        travel_ticks = impact - spawn
        response_open = spawn + max(1, round(travel_ticks * 0.43))
        response_deadline = spawn + max(2, round(travel_ticks * 0.88))
        raids.append(
            {
                "wave": index + 1,
                "lane": lane,
                "count": count,
                "expand_start_tick": expansion_start,
                "expand_complete_tick": expansion_complete,
                "outpost": {
                    "x": round(max(listening_front["x"] + 2.55 + index * 0.8, width - layout_rng.uniform(5.55, 6.95) - index * 1.15), 2),
                    "y": round(center_y + layout_rng.uniform(-0.68, 0.68), 2),
                },
                "motion_phase_offset_ticks": layout_rng.randrange(36),
                "spawn_tick": spawn,
                "response_open_tick": response_open,
                "response_deadline_tick": response_deadline,
                "impact_tick": impact,
            }
        )
    workers = []
    for index in range(worker_count):
        column = index % 3
        row = index // 3
        workers.append(
            {
                "id": f"W{index + 1}",
                "type": "worker",
                "x": round(2.46 + column * 0.68 + layout_rng.uniform(-0.07, 0.07), 2),
                "y": round(center_y - 0.58 + row * 1.12 + layout_rng.uniform(-0.08, 0.08), 2),
            }
        )
    world = {
        "layout_variant": layout_variant,
        "width": width,
        "height": height,
        "viewport_cells": 15,
        "home_queen": home_queen,
        "enemy_queen": enemy_queen,
        "seed_pile": seed_pile,
        "brood": brood,
        "listening_front": listening_front,
        "rally": rally,
        "defense_post_x": defense_post_x,
        "lane_y": lane_y,
        "workers": workers,
        "tick_ms": 100,
        "gather_cycle_ticks": 18,
        "production_ticks": 14,
        "soldier_cost": 2,
        "assault_travel_ticks": 45,
        "initial_seeds": initial_seeds,
        "brood_ready": brood_ready,
        "dig_workers": dig_workers,
        "dig_work": dig_work,
        "hidden_opening": hidden_opening,
        "scout_ticks": scout_ticks,
        "raids": raids,
        "max_ticks": max_ticks,
    }
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Keep your queen alive and destroy the rival queen.",
        "submit_label": "CERTIFY FRONT",
        "asset_manifest": "shared_runtime/assets/provenance/anthill_front_v0.json",
        "generator": {"name": "anthill_fixed_step_v3", "variant_count": 5 * 2 * 3 * (1 << 24)},
        "difficulty_level": level,
        "palette": palette,
        "world": world,
        "rules": {
            "selection": "Select ants, choose an order, then click its visible destination.",
            "economy": "Workers on GATHER complete repeated seed trips. Each soldier costs two seeds.",
            "scouting": "A worker must remain assigned at the visible listening front until contact is acquired.",
            "rival": "Rival formations feint between branches while moving from their outposts toward the colony.",
            "defense": "Use recent motion to read each formation's advance vector, then commit an available soldier group to that branch while it crosses the visible intercept band.",
            "victory": "The rival queen can be assaulted only after every raid is cleared."
        },
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "difficulty_level": level,
        "palette": palette,
        "world": copy.deepcopy(world),
        "opponent_opening": copy.deepcopy(raids),
    }
    if condition:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    return public_state, ground_truth
