"""Original memorial ritual transformed into a windbreak-and-offering vigil."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "funeral_ritual_v2"
REVISION = "windbreak-vigil-v1"
PROFILES = {
    1: dict(candles=1, flowers=0, wind_span_ms=6000, wind_amplitude=95,
            shield_width=94, shield_response="direct"),
    2: dict(candles=1, flowers=0, wind_span_ms=5000, wind_amplitude=108,
            shield_width=70, shield_speed=240, shield_acceleration=900),
    3: dict(candles=2, flowers=3, wind_span_ms=5000, wind_amplitude=108,
            shield_width=70, shield_speed=240, shield_acceleration=900,
            socket_amplitude=40, socket_radius=60),
    4: dict(candles=2, flowers=3, wind_span_ms=4200, wind_amplitude=118,
            shield_width=58, shield_speed=220, shield_acceleration=700,
            socket_amplitude=65, socket_radius=50),
    5: dict(candles=3, flowers=4, wind_span_ms=3600, wind_amplitude=118,
            shield_width=48, shield_speed=210, shield_acceleration=650,
            socket_amplitude=65, socket_radius=44),
}
COLORS = ("#f2b6a5", "#b9b2f0", "#f4d782", "#a7d8cf")


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or
                              task.get("metadata", {}).get("control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    mode = (condition or {}).get("interaction", "full")
    if level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("unsupported vigil condition")
    parameters = copy.deepcopy(PROFILES[level])
    if condition and condition.get("difficulty_parameters") != parameters:
        raise ValueError("vigil parameters must match the selected complete profile")
    revision = "windbreak-vigil-low-v2" if level <= 2 else REVISION
    rng = random.Random(hashlib.sha256(f"{seed}|{revision}".encode()).digest())
    candles = []
    centers = {1: [500], 2: [250, 750], 3: [180, 500, 820]}[parameters["candles"]]
    for i, x in enumerate(centers):
        candles.append(dict(id=i, x=x, y=202, wind_seed=rng.getrandbits(32)))
    flowers = []
    n = parameters["flowers"]
    for i in range(n):
        flowers.append(dict(id=i, color=COLORS[i], petals=5+i,
                            x=125+i*750/(n-1), y=355,
                            motion_seed=rng.getrandbits(32)))
    order = rng.sample(list(range(n)), n)
    sockets = [dict(id=i, x=125+i*750/(n-1), y=490,
                    motion_seed=rng.getrandbits(32)) for i in range(n)]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task["id"],
                  challenge_id=hashlib.sha256(f"{seed}|d{level}|{revision}".encode()).hexdigest()[:16],
                  revision=revision, stage=dict(width=1000, height=580),
                  parameters=parameters, candles=candles, flowers=flowers,
                  sockets=sockets, order=order,
                  epitaph=rng.choice(["SHE KEPT THE LIGHT", "BELOVED BY SMALL THINGS", "HERE, AT LAST"]),
                  ritual=dict(vigil_ms=30000, max_active_ms=90000, tick_ms=20,
                              flame_loss_per_s=.32, flame_recovery_per_s=.12,
                              forecast_ms=2000, flower_radius=16),
                  generator=dict(name=revision, variant_count=10**18,
                                 variant_count_kind="seeded nonperiodic draft" if level <= 2 else "seeded independent nonperiodic drafts and moving offerings"),
                  asset_manifest="shared_runtime/assets/provenance/funeral_ritual_v2_v0.json")
    if condition:
        public["control_condition"] = condition
    return public, dict(copy.deepcopy(public), seed=str(seed))
