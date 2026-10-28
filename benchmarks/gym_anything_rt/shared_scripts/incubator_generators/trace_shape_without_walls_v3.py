"""Source-derived sonar tracing, with autonomous deforming walls and inertia."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "trace_shape_without_walls_v3"
REVISION = "deforming-channel-v2"
PROFILES = {
    1: dict(radius=56, speed=27, amplitude=85, span_ms=9200, bends=6, curve=55, sonar=230, wind=15, response=8),
    2: dict(radius=56, speed=29, amplitude=90, span_ms=8500, bends=6, curve=62, sonar=210, wind=22, response=7.5),
    3: dict(radius=47, speed=31, amplitude=95, span_ms=7800, bends=7, curve=68, sonar=190, wind=30, response=7),
    4: dict(radius=39, speed=33, amplitude=100, span_ms=7200, bends=8, curve=74, sonar=175, wind=38, response=6.5),
    5: dict(radius=33, speed=35, amplitude=108, span_ms=6600, bends=9, curve=78, sonar=160, wind=46, response=6),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    mode = (condition or {}).get("interaction", "full")
    if level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("unsupported difficulty or interaction")
    p = dict(PROFILES[level])
    provided = (condition or {}).get("difficulty_parameters", {})
    if provided and provided != p:
        raise ValueError("profile parameters must match the declared channel revision")
    rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}".encode()).digest())
    nodes = []
    sign = rng.choice((-1, 1))
    for i in range(p["bends"]):
        nodes.append(dict(x=round(40 + i * 920 / (p["bends"] - 1), 4),
                          y=240 + sign * (-1)**i * rng.uniform(p["curve"] * .7, p["curve"]),
                          seed=rng.getrandbits(32)))
    world = dict(stage=dict(width=1000, height=480), nodes=nodes,
                 **p, probe_radius=8, start_x=70, exit_x=930,
                 wall_seed=rng.getrandbits(32), coherence=.85,
                 wind_seed=rng.getrandbits(32), max_velocity=170,
                 max_acceleration=480, tick_ms=10, max_ms=180000)
    task_id = task.get("id", MECHANIC_ID + "_seed_0001@0.1")
    identity = hashlib.sha256(f"{seed}|d{level}|{MECHANIC_ID}|{REVISION}".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, revision=REVISION,
                  task_id=task_id, challenge_id=identity, world=world,
                  prompt="Scan the concealed channel, then keep the green probe between its moving walls all the way to EXIT.",
                  submit_label="CERTIFY TRACE", single_attempt=True,
                  asset_manifest="shared_runtime/assets/provenance/trace_shape_without_walls_v3_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18))
    if condition:
        public["control_condition"] = condition
    return public, dict(copy.deepcopy(public), seed=str(seed))
