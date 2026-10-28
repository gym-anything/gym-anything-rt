from __future__ import annotations

import copy
import hashlib
import random
from typing import Any


MECHANIC_ID = "surreal_apple_on_tree_grid_v2"
STAGE = {"width": 960, "height": 520}
VIEW_LIMIT = 62
VARIANT_COUNT = 8_600_000_000


def _seed(seed: str) -> int:
    return int(hashlib.sha256(f"{seed}|{MECHANIC_ID}|parallax-v2".encode()).hexdigest()[:16], 16)


def _project(point: list[float], angle_deg: float) -> list[float]:
    import math

    angle = math.radians(angle_deg)
    x, y, z = point
    return [
        round(430 + x * math.cos(angle) + z * math.sin(angle), 2),
        round(246 + y + 0.10 * z * math.cos(angle) - 0.05 * x * math.sin(angle), 2),
    ]


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed(seed))
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    task_id = str(task.get("id") or "surreal_apple_on_tree_grid_v2_seed_0001@0.1")
    condition_token = f"|d{condition['difficulty']}|{task_id}" if condition else ""
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}{condition_token}|falling-harvest-v1".encode()).hexdigest()[:13]
    fruit_count = int(parameters.get("fruit_count", 5))
    attached_count = int(parameters.get("attached_count", 3))
    depth_gap_min = int(parameters.get("depth_gap_min", 68))
    depth_gap_max = int(parameters.get("depth_gap_max", 112))
    view_limit = int(parameters.get("view_limit_deg", VIEW_LIMIT))
    radius_min = int(parameters.get("fruit_radius_min", 20))
    radius_max = int(parameters.get("fruit_radius_max", 24))
    if not 3 <= fruit_count <= 9 or not 1 <= attached_count < fruit_count:
        raise ValueError("parallax orchard fruit counts are outside supported limits")
    if not 30 <= view_limit <= 80 or not 20 <= depth_gap_min <= depth_gap_max <= 180:
        raise ValueError("parallax orchard geometry is outside supported limits")
    attached_indexes = set(rng.sample(range(fruit_count), attached_count))
    if fruit_count == 5:
        xs = [-250, -132, -8, 126, 248]
        ys = [-64, -134, -164, -118, -54]
    else:
        xs = [round(-270 + index * 540 / (fruit_count - 1)) for index in range(fruit_count)]
        ys = [rng.randint(-168, -52) for _ in range(fruit_count)]
    rng.shuffle(ys)
    apples: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []
    for index, (x, y) in enumerate(zip(xs, ys)):
        z = rng.randint(-125, 125)
        apple_id = f"fruit-{hashlib.sha256(f'{seed}|fruit|{index}'.encode()).hexdigest()[:7]}"
        apples.append({
            "id": apple_id,
            "position": [x + rng.randint(-7, 7), y, z],
            "radius": rng.randint(radius_min, radius_max),
            "hue": rng.choice(("ruby", "gold", "rose")),
            "scar": rng.randint(0, 3),
        })
        fruit = apples[-1]
        fx, fy, fz = fruit["position"]
        tip_z = fz if index in attached_indexes else fz + rng.choice((-1, 1)) * rng.randint(depth_gap_min, depth_gap_max)
        # At the head-on view a detached branch tip has the same projection as
        # the apple stem. Orbiting exposes the real depth separation.
        tip_y = fy - 28 - 0.10 * (tip_z - fz)
        side = -1 if fx < 0 else 1
        branches.append({
            "id": f"limb-{index + 1}",
            "fruit_id": apple_id,
            "points": [
                [side * 18, 92 - index * 15, rng.randint(-35, 35)],
                [fx * 0.40, fy * 0.18 + 42, round((tip_z + fz) * 0.18)],
                [fx * 0.74, fy * 0.63, round((tip_z + fz) * 0.52)],
                [fx, round(tip_y, 2), tip_z],
            ],
        })

    rng.shuffle(apples)
    basket_width = int(parameters.get("basket_width", 172))
    basket_height = int(parameters.get("basket_height", 132))
    basket = {"x": 960 - basket_width - 26, "y": 520 - basket_height - 30, "width": basket_width, "height": basket_height}
    minimum_span = 96 if view_limit == VIEW_LIMIT else min(96, round(view_limit * 1.55))
    requirements = {
        "minimum_orbit_span_deg": minimum_span,
        "minimum_orbit_travel_deg": 155 if view_limit == VIEW_LIMIT else round(minimum_span * 1.62),
        "minimum_view_sectors": 4,
    }
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": "Orbit the impossible orchard. Pluck only fruit whose stem is joined to wood in depth.",
        "submit_label": "SEAL THE HARVEST",
        "asset_manifest": "shared_runtime/assets/provenance/incubator_full_build_v1.json",
        "generator": {"name": "analytic_parallax_orchard_v2", "variant_count": VARIANT_COUNT},
        "stage": STAGE,
        "view_limit_deg": view_limit,
        "initial_angle_deg": 0,
        "apples": copy.deepcopy(apples),
        "branches": copy.deepcopy(branches),
        "basket": basket,
        "requirements": requirements,
    }
    attached_ids = [branch["fruit_id"] for index, branch in enumerate(branches) if index in attached_indexes]
    # Branch order was never shuffled; attached_indexes still binds to the
    # generated limb/fruit pair, while the public fruit draw order is shuffled.
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "stage": STAGE,
        "view_limit_deg": view_limit,
        "apples": copy.deepcopy(apples),
        "branches": copy.deepcopy(branches),
        "basket": basket,
        "attached_ids": attached_ids,
        "requirements": requirements,
        "variant_count": VARIANT_COUNT,
    }
    by_id = {apple["id"]: apple for apple in apples}
    for branch in branches:
        fruit = by_id[branch["fruit_id"]]
        head = _project([fruit["position"][0], fruit["position"][1] - 28, fruit["position"][2]], 0)
        tip = _project(branch["points"][-1], 0)
        assert abs(head[0] - tip[0]) < 0.01 and abs(head[1] - tip[1]) < 0.01
    assert len(attached_ids) == attached_count
    wind = {apple['id']: {'seed': rng.getrandbits(32), 'span_ms': 1450,
                          'amplitude': [85, 32, 50]} for apple in apples}
    flight = {
        'revision': 'falling-harvest-v1', 'seed': rng.getrandbits(32),
        'gravity': float(parameters.get('gravity', 140)),
        'wind_acceleration': float(parameters.get('wind_acceleration', 340)),
        'wind_span_ms': int(parameters.get('wind_span_ms', 900)),
        'basket_speed': 600, 'basket_acceleration': 2400,
        'rim_y': 450, 'tick_ms': 10,
    }
    basket.update(x=(960-basket_width)/2, y=450, height=52)
    for state in (public_state, ground_truth):
        state['wind'] = copy.deepcopy(wind)
        state['flight'] = copy.deepcopy(flight)
        state['basket'] = copy.deepcopy(basket)
        state['single_attempt'] = True
    public_state['prompt'] = 'Find the joined fruit in 3D. Pluck it, then catch it in the wind.'
    if condition:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    return public_state, ground_truth
