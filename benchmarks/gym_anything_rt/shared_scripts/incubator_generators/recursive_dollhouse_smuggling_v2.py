"""Original cross-scale conveyor, derived from the selected recursive-room idea."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "recursive_dollhouse_smuggling_v2"
REVISION = "nested-tethers-1"
PROFILES = {
    1: dict(parcel_count=1, opening=28, belt_speed=1.5, drift=11, wind=2, stiffness=7, damping=4),
    2: dict(parcel_count=1, opening=27, belt_speed=1.8, drift=11, wind=3, stiffness=7, damping=4),
    3: dict(parcel_count=2, opening=27, belt_speed=2, drift=11, wind=4, stiffness=6, damping=3.5),
    4: dict(parcel_count=2, opening=24, belt_speed=2.2, drift=13, wind=5, stiffness=5.5, damping=3.2),
    5: dict(parcel_count=3, opening=22, belt_speed=2.3, drift=14, wind=6, stiffness=5, damping=2.8),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or {
        "difficulty": 5, "interaction": "full", "real_time": "live",
        "difficulty_parameters": PROFILES[5],
    })
    level = condition.get("difficulty")
    if type(level) is not int or level not in PROFILES or condition.get("interaction") not in ("full", "simplified"):
        raise ValueError("invalid nested-tether control condition")
    parameters = dict(condition.get("difficulty_parameters") or {})
    if parameters != PROFILES[level]:
        raise ValueError("use the documented complete difficulty profile")
    # Interaction mode and task slug never enter this stream or challenge ID.
    rng = random.Random(hashlib.sha256(f"{MECHANIC_ID}|{REVISION}|{seed}|{level}".encode()).digest())
    flip = rng.choice((-1, 1))
    bases = [23, 49, 23] if flip == 1 else [49, 23, 49]
    gates = [dict(id=f"frame-{i}", x=x, base_y=bases[i], width=2.4,
                  opening=parameters["opening"], drift=parameters["drift"],
                  motion_seed=rng.getrandbits(32), span_ms=rng.randint(4200, 6200),
                  from_scale=i, to_scale=min(i+1, 2))
             for i, x in enumerate((47, 78, 109))]
    colors = ["#ffd071", "#85e4d0", "#e6a5ff"]
    parcels = [dict(id=f"parcel-{i}", label=("AMBER", "JADE", "LILAC")[i],
                    color=colors[i], x=8+i*14, y=bases[0], wind_seed=rng.getrandbits(32),
                    control_view=(2, 0, 1)[i]) for i in range(parameters["parcel_count"])]
    motion = dict(parameters, revision=REVISION, tick_ms=10, wind_span_ms=3700,
                  max_acceleration=28, max_speed=14, radii=[2.4, 3.6, 4.8],
                  preview_ms=500, play_time_ms=120000)
    views = [dict(id=name, label=label, index=i, origin=[140, 25],
                  matrix=[[1.55, -1.55], [1.22, 1.22]], width=350, height=320)
             for i, (name, label) in enumerate(zip(("mini", "human", "giant"),
                                                  ("MINIATURE", "HUMAN", "GIANT")))]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task["id"], challenge_id=hashlib.sha256(
                      f"{seed}|{MECHANIC_ID}|{REVISION}|{level}".encode()).hexdigest()[:16],
                  prompt="Smuggle every parcel through the two growing frames and the drifting exit. Keep the whole parcel clear of the shutters.",
                  control_condition=condition, views=views, room=dict(width=124, depth=72),
                  gates=gates, parcels=parcels, physics=motion,
                  asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json",
                  generator=dict(name=REVISION, variant_count=2**96), single_attempt=True)
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
