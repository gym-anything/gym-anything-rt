"""Live first-change photography. Original artwork; no imported game assets."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "temporal_memory_first_change_v3"
REVISION = "live-evidence-optical-inspection-v3"
# Preserve the mechanically copied V2 world's seeded trajectories and profiles.
WORLD_REVISION = "live-evidence-lenses-v1"
PROFILES = {
    1: dict(carriers=3, lenses=1, speed=45, lens_radius=82, change_ms=3200, motion_span_ms=4800, camera_acceleration=2200, camera_speed=520),
    2: dict(carriers=4, lenses=1, speed=55, lens_radius=72, change_ms=2800, motion_span_ms=4000, camera_acceleration=2000, camera_speed=480),
    3: dict(carriers=5, lenses=1, speed=65, lens_radius=64, change_ms=2400, motion_span_ms=3400, camera_acceleration=1800, camera_speed=440),
    4: dict(carriers=7, lenses=2, speed=70, lens_radius=68, change_ms=2200, motion_span_ms=3200, camera_acceleration=1600, camera_speed=400),
    5: dict(carriers=8, lenses=2, speed=88, lens_radius=60, change_ms=2000, motion_span_ms=2800, camera_acceleration=1400, camera_speed=360),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition"))
    level = (condition or {}).get("difficulty", 5)
    mode = (condition or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in {"full", "simplified"}:
        raise ValueError("invalid first-change difficulty or interaction")
    params = copy.deepcopy(PROFILES[level])
    if condition and condition.get("difficulty_parameters") != params:
        raise ValueError("first-change profile parameters do not match the supported profile")
    rng = random.Random(int(hashlib.sha256(f"{seed}|{MECHANIC_ID}|{WORLD_REVISION}|d{level}".encode()).hexdigest()[:16], 16))
    objects = []
    patterns = rng.sample(list(range(8)), params["carriers"])
    for i in range(params["carriers"]):
        # Distinct initial positions; independent continuous trajectories thereafter.
        objects.append(dict(id=f"emulsion-{rng.getrandbits(40):010x}", pattern=patterns[i],
            x0=110+i*730/max(1, params["carriers"]-1), y0=rng.uniform(95, 335),
            direction_x=rng.choice([-1, 1]), direction_y=rng.choice([-1, 1]),
            seed_x=rng.getrandbits(32), seed_y=rng.getrandbits(32), radius=21))
    order = rng.sample([o["id"] for o in objects], len(objects))
    onset = rng.randrange(3000, 3801, 100)
    changes = []
    for i, oid in enumerate(order):
        changes.append(dict(object_id=oid, at_ms=onset,
            duration_ms=params["change_ms"], effect="reverse-petals"))
        onset += rng.randrange(2200, 3201, 100)
    world = dict(width=960, height=440, bounds=[45, 915, 45, 395], tick_ms=20,
        parameters=params, carriers=objects, changes=changes,
        initial_lenses=[[150, 385], [810, 385]][:params["lenses"]],
        exposure_ms=6500, exposure_loss_rate=1.5, max_ms=75000,
        bind_radius=30, camera_damping=12)
    challenge = hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}|d{level}".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
        revision=REVISION, task_id=task["id"], challenge_id=challenge, world=world,
        prompt="Inspect the carriers' concealed negatives to find the first reversal" + (" and the second" if params["lenses"] == 2 else "") + ". Bind each to its lens, then keep every bound carrier wholly framed together until the exposure fills.",
        asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json",
        generator=dict(name=REVISION, variant_count=10**18),
        render_boundary="The renderer receives trajectories and reversible changes. These are inspectable browser data, not secrets; evaluation policies use visible screenshots and task controls only.")
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), target_ids=order[:params["lenses"]])
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth
