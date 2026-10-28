"""Source-derived moving dual-projection sculpture, separate from the original."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "relation_prompt_grounding_v3"
REVISION = "moving-projection-rig-v3-inspection"
RANDOM_WORLD_VERSION = "moving-projection-rig-v1"
SOURCE_ANCHORS = ["logic-captcha-media-examples-2024", "visual-reasoning-captcha-vtt", "arkose-funcaptcha-internals-crawlex"]
PROFILES = {
    1: dict(object_count=2, drift_amplitude=28, drift_span_ms=4500, tolerance=26, coupling=0.0),
    2: dict(object_count=3, drift_amplitude=36, drift_span_ms=4000, tolerance=24, coupling=0.04),
    3: dict(object_count=3, drift_amplitude=44, drift_span_ms=3500, tolerance=20, coupling=0.08),
    4: dict(object_count=4, drift_amplitude=55, drift_span_ms=3200, tolerance=18, coupling=0.12),
    5: dict(object_count=5, drift_amplitude=65, drift_span_ms=2800, tolerance=14, coupling=0.18),
}
COLORS = ["#e6ad52", "#74d6dc", "#e98fa8", "#a9b8f6", "#aecc81"]
# All projected silhouettes come from these actual 3-D vertices. Spheres use
# their analytic orthographic disk; other bodies use the convex projected hull.
MESHES = [
    None,
    [[x, y, z] for x in (-18, 18) for y in (-18, 18) for z in (-18, 18)],
    [[22, 0, 0], [-22, 0, 0], [0, 22, 0], [0, -22, 0], [0, 0, 22], [0, 0, -22]],
    [[-21, 18, -18], [21, 18, -18], [0, -23, -18], [-21, 18, 18], [21, 18, 18], [0, -23, 18]],
    [[-22, -12, -16], [22, -12, -16], [-22, 12, -16], [22, 12, -16], [-22, -12, 16], [22, -12, 16], [-22, 12, 16], [22, 12, 16]],
]


def generate(task, seed):
    raw = task.get("_control_condition")
    level = (raw or {}).get("difficulty", 4)
    mode = (raw or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("invalid sculpture control condition")
    parameters = copy.deepcopy(PROFILES[level])
    if raw and raw.get("difficulty_parameters") != parameters:
        raise ValueError("sculpture parameters must match the declared profile")
    condition = copy.deepcopy(raw) if raw else dict(difficulty=level, interaction=mode, real_time="live", difficulty_parameters=parameters)
    rng = random.Random(hashlib.sha256(f"{seed}|{RANDOM_WORLD_VERSION}|d{level}".encode()).digest())
    count = parameters["object_count"]
    # Separated two-view target centers; depth and x order vary independently.
    slots = [(96, 94), (292, 94), (194, 169), (96, 250), (292, 250)]
    picked = [slots[i] for i in ([0, 4] if count == 2 else [0, 2, 4] if count == 3 else [0, 1, 3, 4] if count == 4 else range(5))]
    objects = [dict(id=f"body-{i}", color=COLORS[i], shape=["sphere", "cube", "octahedron", "prism", "bar"][i], radius=22 if i == 0 else None, vertices=copy.deepcopy(MESHES[i]), motor_seed=rng.getrandbits(32), phase_ms=rng.randrange(parameters["drift_span_ms"]), initial=[x+rng.randint(-12, 12), y+rng.randint(-8, 8), 400-x+rng.randint(-12, 12)]) for i, (x, y) in enumerate(picked)]
    plates = []
    for plate in range(3):
        front = list(picked)
        rng.shuffle(front)
        depth = [75, 135, 200, 265, 325][:count] if count >= 4 else [96, 200, 304][:count]
        rng.shuffle(depth)
        # SIDE shares each body's true y, but depth is independently assigned.
        targets = [[x+rng.randint(-7, 7), y+rng.randint(-5, 5), depth[i]+rng.randint(-5, 5)] for i, (x, y) in enumerate(front)]
        # Avoid identical arrangements without relying on round count as level.
        plates.append(dict(name=f"PLATE {plate+1}", targets=targets))
    task_id = task.get("id", "relation_prompt_grounding_v3_seed_0001@0.1")
    world = dict(revision=REVISION, objects=objects, plates=plates, parameters=parameters, duration_ms=180000, world_size=[400, 340, 400], command_bounds=[-80, 480])
    world_hash = hashlib.sha256(__import__("json").dumps(world, sort_keys=True).encode()).hexdigest()
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task_id, challenge_id=hashlib.sha256(f"{seed}|{world_hash}".encode()).hexdigest()[:16], asset_manifest="shared_runtime/assets/provenance/relation_prompt_grounding_v3_v0.json", source_anchors=SOURCE_ANCHORS, generator=dict(name=REVISION, variant_count=10**18, variant_count_kind=f"lower bound from {count} independently seeded motor drives and target arrangements"), control_condition=condition, prompt="Select each sculpture to inspect its paired projection seals, then reconstruct three moving sculptures and expose the aligned plates.", **world)
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    truth["world_sha256"] = world_hash
    return public, truth
