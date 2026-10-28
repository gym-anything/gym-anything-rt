from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "impossible_ecology_nonrealtime"
DONOR_MECHANIC_ID = "impossible_ecology_v2"
FIELDS = ("CLIMATE", "FOOD", "LIGHT")
SIGNATURES = tuple((field, sign) for field in FIELDS for sign in (-1, 1))
COLORS = ("#9dff70", "#63e7ff", "#ffcc63", "#ff7aa8", "#c499ff")
EXTENDED_COLORS = COLORS + ("#ff9f66",)
PALETTES = (
    {"name": "moss", "paper": "#08120c", "grid": "#244b31", "ink": "#dff3d5", "danger": "#ff5f56"},
    {"name": "brine", "paper": "#071319", "grid": "#255063", "ink": "#d8f5f4", "danger": "#ff6a65"},
    {"name": "ember", "paper": "#171008", "grid": "#694426", "ink": "#f5e8cf", "danger": "#ff5d51"},
    {"name": "violet", "paper": "#100b18", "grid": "#533769", "ink": "#eee1f7", "danger": "#ff6573"},
)


def _seed_int(seed: str, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _round(value: float) -> float:
    return round(float(value) + 1e-12, 5)


def _difficulty_parameters(task: dict[str, Any]) -> dict[str, Any]:
    """Return the selected profile without changing the uncontrolled task."""
    condition = task.get("_control_condition")
    if condition is None:
        return {}
    parameters = condition.get("difficulty_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("impossible ecology control condition has no parameter object")
    return dict(parameters)


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    # Keep corresponding seeds byte-for-byte aligned with the evaluated V2
    # donor.  The namespace changes, but the puzzle layout does not.
    rng = random.Random(_seed_int(seed, DONOR_MECHANIC_ID))
    condition = task.get("_control_condition")
    parameters = _difficulty_parameters(task)
    field_count = int(parameters.get("field_count", len(FIELDS)))
    organism_count = int(parameters.get("organism_count", 5))
    primary_min = float(parameters.get("primary_response_min", 1.18))
    primary_max = float(parameters.get("primary_response_max", 1.34))
    secondary_min = float(parameters.get("secondary_response_min", .11))
    secondary_max = float(parameters.get("secondary_response_max", .19))
    initial_radius_min = float(parameters.get("initial_radius_min", 78))
    initial_radius_max = float(parameters.get("initial_radius_max", 96))
    target_radius_min = float(parameters.get("target_radius_min", 164))
    target_radius_max = float(parameters.get("target_radius_max", 174))
    sanctuary_radius = parameters.get("sanctuary_radius", 38)
    obstacle_radius = parameters.get("obstacle_radius", 48)
    damping = float(parameters.get("damping", .83))
    max_speed = float(parameters.get("max_speed", 4.8))
    capture_speed = float(parameters.get("capture_speed", 5.0))
    capture_margin = float(parameters.get("capture_margin", 1.0))
    current_acceleration = float(parameters.get("current_acceleration", .18))
    current_segment_ticks = int(parameters.get("current_segment_ticks", 80))
    calibration_field_ms = int(parameters.get("calibration_field_ms", 620))
    if (
        not 2 <= field_count <= len(FIELDS)
        or not 2 <= organism_count <= field_count * 2
        or primary_min <= 0 or primary_min > primary_max
        or secondary_min < 0 or secondary_min > secondary_max or secondary_max >= primary_min
        or initial_radius_min > initial_radius_max
        or target_radius_min > target_radius_max
        or not 30 <= float(sanctuary_radius) <= 56
        or not 28 <= float(obstacle_radius) <= 68
        or not .76 <= damping <= .91
        or not 3.5 <= max_speed <= 6.0
        or not 2.5 <= capture_speed <= 6.0
        or not .5 <= capture_margin <= 3.0
        or not .08 <= current_acceleration <= .3
        or not 50 <= current_segment_ticks <= 120
        or not 420 <= calibration_field_ms <= 900
    ):
        raise ValueError("impossible ecology difficulty parameters are malformed")
    active_fields = FIELDS[:field_count]
    arena = {"width": 1000, "height": 430, "margin": 24}
    center = [arena["width"] / 2, arena["height"] / 2]
    rotation = rng.uniform(-math.pi, math.pi)
    signatures = [(field, sign) for field in active_fields for sign in (-1, 1)]
    rng.shuffle(signatures)
    selected = signatures[:organism_count]
    # Keep the original five-colour shuffle byte-for-byte equivalent at the
    # preserved baseline; only the six-organism profile needs an extra colour.
    colors = list(COLORS if organism_count <= len(COLORS) else EXTENDED_COLORS)
    rng.shuffle(colors)

    organisms: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for index in range(organism_count):
        angle = rotation + index * math.tau / organism_count
        tangent = [-math.sin(angle), math.cos(angle)]
        radial = [math.cos(angle), math.sin(angle)]
        initial_radius = rng.uniform(initial_radius_min, initial_radius_max)
        tangential_jitter = rng.uniform(-14, 14)
        position = [
            center[0] + radial[0] * initial_radius + tangent[0] * tangential_jitter,
            center[1] + radial[1] * initial_radius + tangent[1] * tangential_jitter,
        ]
        target_radius = rng.uniform(target_radius_min, target_radius_max)
        target = [center[0] + radial[0] * target_radius, center[1] + radial[1] * target_radius]
        primary_field, primary_sign = selected[index]
        responses: dict[str, float] = {}
        for field in active_fields:
            if field == primary_field:
                responses[field] = _round(primary_sign * rng.uniform(primary_min, primary_max))
            else:
                responses[field] = _round(rng.choice((-1, 1)) * rng.uniform(secondary_min, secondary_max))
        organism_id = f"organism-{index + 1}"
        organisms.append({
            "id": organism_id,
            "label": chr(65 + index),
            "color": colors[index],
            "radius": 14,
            "initial_position": [_round(value) for value in position],
            "responses": responses,
            "current_seed": rng.randrange(1, 2**31),
        })
        targets.append({
            "id": f"sanctuary-{index + 1}",
            "organism_id": organism_id,
            "label": chr(65 + index),
            "color": colors[index],
            "center": [_round(value) for value in target],
            "radius": sanctuary_radius,
        })

    controls = {
        "tick_ms": 50,
        "damping": damping,
        "max_speed": max_speed,
        "capture_speed": capture_speed,
        "capture_margin": capture_margin,
        "pointer_sample_distance": 3.0,
        "current_acceleration": current_acceleration,
        "current_segment_ticks": current_segment_ticks,
        "calibration_field_ms": calibration_field_ms,
    }
    obstacle = {"id": "nursery", "center": center, "radius": obstacle_radius}
    condition_token = ""
    if condition is not None:
        condition_token = f"|d{int(condition['difficulty'])}|{str(condition['interaction'])}"
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}{condition_token}".encode("utf-8")).hexdigest()[:12]
    task_id = str(task.get("id") or "impossible_ecology_nonrealtime_seed_0001@0.1")
    completion_rule = {
        2: "A matching sanctuary locks an organism permanently. Stabilize both organisms.",
        3: "A matching sanctuary locks an organism permanently. Stabilize all three organisms.",
        4: "A matching sanctuary locks an organism permanently. Stabilize all four organisms.",
        # Preserve the exact original uncontrolled L4 rule text.
        5: "A matching sanctuary locks an organism permanently. Stabilize all five.",
        6: "A matching sanctuary locks an organism permanently. Stabilize all six organisms.",
    }[organism_count]
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Learn the coupled field responses, then shepherd every organism into its matching sanctuary.",
        "submit_label": "CERTIFY STABLE ECOLOGY",
        "asset_manifest": "shared_runtime/assets/provenance/incubator_full_build_v1.json",
        "generator": {"name": "coupled_field_ecology_nonrealtime_v1", "variant_count": 24_000_000_000},
        "palette": rng.choice(PALETTES),
        "arena": arena,
        "fields": list(active_fields),
        "organisms": organisms,
        "targets": targets,
        "obstacle": obstacle,
        "controls": controls,
        "rules": [
            "Select one global field, then hold the pointer inside the arena.",
            "Each uncaptured organism is attracted or repelled differently; all move at once.",
            "Each deliberate field-lure pointer action advances the ambient current one physics step.",
            completion_rule,
        ],
        "render_boundary": "The static browser receives response coefficients to run the local simulation. They are never rendered numerically; the independent grader replays every field, pointer action, and physics tick.",
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "arena": arena,
        "fields": list(active_fields),
        "organisms": organisms,
        "targets": targets,
        "obstacle": obstacle,
        "controls": controls,
        "variant_count": public_state["generator"]["variant_count"],
    }
    if condition is not None:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    for organism, target in zip(organisms, targets):
        assert organism["id"] == target["organism_id"]
        assert max(abs(value) for value in organism["responses"].values()) >= primary_min - 1e-5
        assert math.dist(organism["initial_position"], center) > obstacle["radius"] + organism["radius"] + 12
        assert math.dist(target["center"], center) > 150
    assert len({(max(item["responses"], key=lambda field: abs(item["responses"][field])), 1 if item["responses"][max(item["responses"], key=lambda field: abs(item["responses"][field]))] > 0 else -1) for item in organisms}) == organism_count
    return public_state, ground_truth
