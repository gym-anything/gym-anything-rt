"""Source-derived two-face fire interception; no changes to the original tower."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "firewatch_fold_v3"
REVISION = "gutter-interception-v3-observed-currents"
PROFILES = {
    1: dict(floors=3, fronts=2, ladders=1, speed=.65, variation=.50, reach=4.6, radius=.52, span_ms=3000),
    2: dict(floors=3, fronts=2, ladders=2, speed=.85, variation=.55, reach=4.0, radius=.47, span_ms=3000),
    3: dict(floors=4, fronts=2, ladders=2, speed=1.05, variation=.60, reach=3.6, radius=.42, span_ms=3000),
    4: dict(floors=4, fronts=2, ladders=3, speed=1.25, variation=.65, reach=3.2, radius=.38, span_ms=3000),
    5: dict(floors=5, fronts=3, ladders=3, speed=1.45, variation=.70, reach=2.8, radius=.34, span_ms=3000),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    interaction = (condition or {}).get("interaction", "full")
    if level not in PROFILES or interaction not in ("full", "simplified"):
        raise ValueError("invalid Firewatch Fold V3 condition")
    p = dict(PROFILES[level])
    p.update((condition or {}).get("difficulty_parameters", {}))
    if p != PROFILES[level]:
        raise ValueError("profile must match the documented interception contract")
    rng = random.Random(hashlib.sha256(f"{MECHANIC_ID}|{REVISION}|{seed}".encode()).digest())
    width = 7
    fires = []
    for floor in range(p["floors"] - 1):
        offset = rng.uniform(0, 2 * width)
        for j in range(p["fronts"]):
            fires.append(dict(id=f"f{floor}-{j}", floor=floor, color=j,
                x=round((offset + j * 2 * width / p["fronts"] + rng.uniform(-.3, .3)) % (2 * width), 6),
                direction=1 if j % 2 == 0 else -1,
                speed=round(p["speed"] * rng.uniform(.9, 1.1), 6),
                wind_seed=rng.getrandbits(32), span_ms=p["span_ms"],
                variation=p["variation"], radius=p["radius"]))
    world = dict(revision=REVISION, width=width, floors=p["floors"], parameters=p,
        fires=fires, ladders=[sorted(rng.sample(range(2 * width), p["ladders"]))
                            for _ in range(p["floors"] - 1)],
        start=[0, rng.randrange(width)], resident=[p["floors"] - 1, rng.randrange(2 * width)],
        pulse_speed=5., pulse_radius=.12, pulse_reach=p["reach"],
        tick_ms=20, move_cooldown_ticks=5, max_ticks=9000, stock=len(fires),
        color_count=p["fronts"], cartridges=[p["floors"] - 1] * p["fronts"])
    task_id = str(task.get("id") or f"{MECHANIC_ID}_seed_0001@0.1")
    challenge_id = hashlib.sha256(f"{seed}|{REVISION}|{task_id}|d{level}".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
        task_id=task_id, challenge_id=challenge_id, world=world,
        interaction=interaction, control_condition=condition,
        prompt=task.get("natural_language") or "Contain the moving fire fronts and reach the resident.",
        submit_label="CERTIFY RESCUE",
        asset_manifest="shared_runtime/assets/provenance/firewatch_fold_v3_v0.json",
        generator=dict(name=REVISION, variant_count=10**18,
                       variant_count_kind="independent fire currents, ladder placements and starts"))
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), source_anchors=["TRP-708"])
    return public, truth
