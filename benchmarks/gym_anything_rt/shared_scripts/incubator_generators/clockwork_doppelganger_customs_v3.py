"""Original clone relay, derived from Pontoco's recorded-action automatons.

Interaction never enters the world RNG. No solutions or control commands are
published: cam trajectories are geometry needed to render and replay motion.
"""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "clockwork_doppelganger_customs_v3"
REVISION = "moving-relay-3-inspection-3"
PROFILES = {
    1: dict(workers=1, period_ms=9000, travel_ms=4600, gap_ms=900,
            amplitude=100, motor_span_ms=5000, tolerance=38, speed=460, acceleration=2200, collection_ms=3000),
    2: dict(workers=1, period_ms=8000, travel_ms=4000, gap_ms=800,
            amplitude=130, motor_span_ms=4200, tolerance=30, speed=460, acceleration=2200, collection_ms=2600),
    3: dict(workers=2, period_ms=7000, travel_ms=3600, gap_ms=600,
            amplitude=140, motor_span_ms=4200, tolerance=27, speed=460, acceleration=2200, collection_ms=2200),
    4: dict(workers=3, period_ms=6400, travel_ms=3200, gap_ms=500,
            amplitude=145, motor_span_ms=3800, tolerance=24, speed=420, acceleration=1800, collection_ms=1800),
    5: dict(workers=3, period_ms=4800, travel_ms=3000, gap_ms=400,
            amplitude=148, motor_span_ms=3400, tolerance=20, speed=390, acceleration=1600, collection_ms=1400),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or
                              task.get("metadata", {}).get("control_condition") or {})
    level = int(condition.get("difficulty", 5))
    if level not in PROFILES:
        raise ValueError("difficulty must be 1 through 5")
    parameters = dict(condition.get("difficulty_parameters") or PROFILES[level])
    if parameters != PROFILES[level]:
        raise ValueError("unknown clone relay difficulty profile")
    interaction = condition.get("interaction", "full")
    if interaction not in ("full", "simplified"):
        raise ValueError("invalid clone interaction")
    condition.setdefault("real_time", "live")
    condition.update(difficulty=level, interaction=interaction,
                     difficulty_parameters=parameters)
    # Preserve the mechanically forked V3 drive tapes. Only their inspection
    # surface changes; the exploration revision must not reroll the physics.
    rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|moving-relay-2".encode()).digest())
    n = parameters["workers"]
    spec = dict(parameters, parcel_count=3, first_pickup_ms=1500, tick_ms=10,
                min_y=64, max_y=396, initial_y=230, kp=45, kd=13)
    end = 1500 + 2*spec["period_ms"] + (n-1)*(spec["travel_ms"]+spec["gap_ms"]) + spec["travel_ms"]
    spec["end_ms"] = end
    # Independent smooth, nonperiodic drive tapes. Every waypoint stays in the
    # rendered enclosure. A visible drive pin identifies the current endpoint.
    motors = []
    for _ in range(2*n+1):
        motors.append([230 + rng.randint(-parameters["amplitude"], parameters["amplitude"])
                       for _ in range(end//spec["motor_span_ms"] + 4)])
    world = dict(stage=dict(width=860, height=460), spec=spec, motors=motors,
                 stations_x=[70+i*720/n for i in range(n+1)],
                 seals_x=[70+(i+.5)*720/n for i in range(n)],
                 editor=dict(start=[90,230], end=[770,230], radius=28, max_deviation=28),
                 collection=dict(width=44, height=36, travel_x=44),
                 lever=dict(width=240, height=460, xs=[120+(i-(n-1)/2)*66 for i in range(n)],
                            grip_half_width=25, grip_half_height=16))
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task["id"], revision=REVISION,
                  challenge_id=hashlib.sha256(f"{seed}|{MECHANIC_ID}|d{level}|{REVISION}".encode()).hexdigest()[:16],
                  prompt="Lift the drive housings to inspect concealed tray and seal motion. Record a sweep, align your clockwork selves, and collect moving passports at OUT.",
                  world=world, control_condition=condition,
                  source_anchors=["https://pontoco.com/the-last-clockwinder"],
                  asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json",
                  generator=dict(name="recorded_sweep_moving_relay_v3", variant_count=10**18,
                                 variant_count_kind="lower bound on independent integer drive waypoints with continuous interpolation"),
                  render_boundary="Drive tapes ship for rendering; public static play is inspectable. Screenshot-only play must lift a housing to reveal that drive. The safe bench previews only its first origin/end pair, irrespective of waiting. Opened housings persist; later pairs, pins and motion appear only when current during the deployed relay.")
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
