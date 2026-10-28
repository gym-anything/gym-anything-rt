"""Original selective-pump control game derived from survey record XUIF-224."""
from __future__ import annotations

import copy
import hashlib
import json
import random

MECHANIC_ID = "cell_gatekeeper_v2"
REVISION = "atp-stroke-v2"
PROFILES = {
    1: dict(lanes=1, aperture=56, drift=32, drift_span_ms=4000, speed=46, gap_ms=6500, toxin_gap_ms=2200, spring=70, damping=18, pump_speed=240, opposing=False),
    2: dict(lanes=2, aperture=54, drift=32, drift_span_ms=3600, speed=50, gap_ms=6200, toxin_gap_ms=1800, spring=65, damping=17, pump_speed=220, opposing=False),
    3: dict(lanes=2, aperture=52, drift=32, drift_span_ms=3200, speed=54, gap_ms=5900, toxin_gap_ms=1400, spring=60, damping=16, pump_speed=210, opposing=True),
    4: dict(lanes=3, aperture=50, drift=32, drift_span_ms=2900, speed=58, gap_ms=5600, toxin_gap_ms=1100, spring=55, damping=15, pump_speed=200, opposing=True),
    5: dict(lanes=3, aperture=46, drift=32, drift_span_ms=2600, speed=62, gap_ms=5300, toxin_gap_ms=850, spring=50, damping=14, pump_speed=190, opposing=True),
}
for level, hold in enumerate((1200, 1000, 800, 650, 550), 1):
    PROFILES[level].update(stroke_arm_ms=400, stroke_open_ms=hold, stroke_recovery_ms=300)
SOLUTES = (("potassium", "K+", "#76e4cb", "diamond"), ("sodium", "Na+", "#ffb578", "circle"), ("glucose", "GLU", "#a5a4ff", "hexagon"))


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    if level not in PROFILES or (condition or {}).get("interaction", "full") not in ("full", "simplified"):
        raise ValueError("unsupported membrane control condition")
    parameters = copy.deepcopy(PROFILES[level])
    if condition and condition.get("difficulty_parameters") != parameters:
        raise ValueError("profile parameters differ from the task's control contract")
    rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}".encode()).digest())
    lanes, particles = [], []
    for lane in range(parameters["lanes"]):
        sid, label, color, shape = SOLUTES[lane]
        center = 80 + lane * 140
        direction = -1 if parameters["opposing"] and sid == "sodium" else 1
        lanes.append(dict(id=lane, species=sid, label=label, color=color, shape=shape,
                          center=center, low=center-70, high=center+70, direction=direction,
                          initial_y=center, initial_open=False, atp=4, goal=4))
        arrival = 8300 + lane * 1000 + rng.randrange(500)
        polarity = rng.choice((-1, 1))
        for index in range(4):
            if index:
                arrival += parameters["gap_ms"] + rng.randrange(-400, 401)
            # All levels have separated arrivals that defeat fixed parking.
            base_offset = 28 * polarity * (-1 if index % 2 else 1)
            spec = dict(id=f"ion-{lane}-{index}", lane=lane, kind="nutrient", radius=10,
                        arrival_ms=arrival, speed=parameters["speed"] + rng.randrange(-4, 5),
                        base_y=center+base_offset, motion_seed=rng.getrandbits(32),
                        motion_offset_ms=rng.randrange(5000), drift=parameters["drift"],
                        span_ms=parameters["drift_span_ms"])
            particles.append(spec)
            # Contaminants are spatially close to the nutrient, but have their
            # own continuous trajectories. They are hollow magenta bodies.
            toxin = copy.deepcopy(spec)
            toxin.update(id=f"inhibitor-{lane}-{index}", kind="inhibitor",
                         arrival_ms=arrival + parameters["toxin_gap_ms"] + rng.randrange(-120, 121),
                         motion_seed=rng.getrandbits(32), motion_offset_ms=rng.randrange(5000))
            particles.append(toxin)
    particles.sort(key=lambda item: item["arrival_ms"])
    identity = hashlib.sha256(json.dumps([str(seed), REVISION, parameters], sort_keys=True).encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, revision=REVISION,
                  task_id=task["id"], challenge_id=identity, parameters=parameters,
                  stage=dict(width=960, height=450, membrane_x=480, rail_x=534, tick_ms=10),
                  lanes=lanes, particles=particles, duration_ms=max(p["arrival_ms"] for p in particles)+500,
                  prompt="Align each pump, then spend ATP on a committed transport stroke. Keep hollow inhibitors out.",
                  submit_label="CERTIFY TRANSFER", single_attempt=True,
                  source_anchors=["XUIF-224"],
                  asset_manifest="shared_runtime/assets/provenance/cell_gatekeeper_v2_v0.json",
                  generator=dict(name=REVISION, variant_count=1000000,
                                 variant_count_kind="declared seed space; not a measured uniqueness count"))
    if condition:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
