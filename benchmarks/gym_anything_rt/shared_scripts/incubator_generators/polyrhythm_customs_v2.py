"""Original circulating score; Simon pad identities and rhythm timing are sources."""
from __future__ import annotations

import copy
import hashlib
import math
import random

MECHANIC_ID = "polyrhythm_customs_v2"
REVISION = "circulating-score-v2"
PROFILES = {
    1: dict(lane_count=2, notes_per_lane=4, speed=56, speed_variation=.18,
            speed_span_ms=3200, gate_drift=16, gate_span_ms=5200,
            band_half_width=54, hold_fraction=0, hold_length_min=0, hold_length_max=0, miss_allowance=10),
    2: dict(lane_count=2, notes_per_lane=4, speed=64, speed_variation=.25,
            speed_span_ms=2900, gate_drift=20, gate_span_ms=5100,
            band_half_width=49, hold_fraction=.25, hold_length_min=100, hold_length_max=125, miss_allowance=6),
    3: dict(lane_count=3, notes_per_lane=4, speed=70, speed_variation=.30,
            speed_span_ms=2600, gate_drift=25, gate_span_ms=5000,
            band_half_width=44, hold_fraction=.50, hold_length_min=110, hold_length_max=145, miss_allowance=4),
    4: dict(lane_count=4, notes_per_lane=6, speed=77, speed_variation=.36,
            speed_span_ms=2300, gate_drift=30, gate_span_ms=5000,
            band_half_width=40, hold_fraction=.50, hold_length_min=110, hold_length_max=155, miss_allowance=3),
    5: dict(lane_count=4, notes_per_lane=6, speed=84, speed_variation=.42,
            speed_span_ms=2000, gate_drift=34, gate_span_ms=5000,
            band_half_width=36, hold_fraction=.67, hold_length_min=125, hold_length_max=165, miss_allowance=2),
}
LANES = (
    dict(id="a", key="A", label="AMBER", color="#f4bf65", glyph="◆"),
    dict(id="s", key="S", label="SIGNAL", color="#69d7c7", glyph="●"),
    dict(id="d", key="D", label="DOCK", color="#ee8c92", glyph="▰"),
    dict(id="f", key="F", label="FOG", color="#b6a0eb", glyph="✦"),
)


def generate(task, seed):
    condition = task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition")
    level = int((condition or {}).get("difficulty", 5))
    mode = (condition or {}).get("interaction", "full")
    if level not in PROFILES or mode not in {"full", "simplified"}:
        raise ValueError("polyrhythm controls require difficulty 1–5 and full/simplified interaction")
    parameters = copy.deepcopy(PROFILES[level])
    parameters.update((condition or {}).get("difficulty_parameters") or {})
    p = parameters
    if (not 2 <= p["lane_count"] <= 4 or not 4 <= p["notes_per_lane"] <= 6
            or not 45 <= p["speed"] <= 100 or not .1 <= p["speed_variation"] <= .45
            or not 1800 <= p["speed_span_ms"] <= 6000
            or not 10 <= p["gate_drift"] <= 40 or not 4500 <= p["gate_span_ms"] <= 8000
            or not 32 <= p["band_half_width"] <= 60 or not 0 <= p["hold_fraction"] <= .8
            or not 0 <= p["hold_length_min"] <= p["hold_length_max"] <= 180
            or type(p["miss_allowance"]) is not int or not 2 <= p["miss_allowance"] <= 16):
        raise ValueError("polyrhythm profile is outside the visible, controllable range")
    # Even opposing gate motion cannot reverse an inbound note relative to its band.
    if p["speed"] * (1-p["speed_variation"]) <= 3*p["gate_drift"]/(p["gate_span_ms"]/1000):
        raise ValueError("gate motion would overtake the belt")
    rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}".encode()).digest())
    rail = dict(left=132, right=914, radius=22, gate_x=265, width=960, height=456)
    circumference = 2*(rail["right"]-rail["left"]) + 2*math.pi*rail["radius"]
    lanes, notes = [], []
    for i, template in enumerate(LANES[:p["lane_count"]]):
        lane = dict(template, y=54+i*104, speed_seed=rng.getrandbits(32),
                    gate_seed=rng.getrandbits(32), offset_ms=rng.randrange(0,1800))
        lanes.append(lane)
        hold_indexes = set(rng.sample(range(p["notes_per_lane"]), round(p["notes_per_lane"]*p["hold_fraction"])))
        lane_notes = []
        for j in range(p["notes_per_lane"]):
            length = round(rng.uniform(p["hold_length_min"],p["hold_length_max"]),2) if j in hold_indexes else 0
            lane_notes.append(dict(id=f"{template['id']}-{j+1}", lane=template["id"],
                                   phase=j*circumference/p["notes_per_lane"]+rng.uniform(-14,14),
                                   length=length, kind="hold" if length else "tap"))
        # Avoid an unavoidable cold-start miss before the first 240 ms window.
        # Even the worst relative speed leaves 600 ms before the first opening.
        base_gate = rail["right"]-rail["gate_x"]
        max_relative_speed = p["speed"]*(1+p["speed_variation"])+3*p["gate_drift"]/(p["gate_span_ms"]/1000)
        lower = base_gate-p["gate_drift"]-p["band_half_width"]-.6*max_relative_speed
        upper = base_gate+p["gate_drift"]+p["band_half_width"]
        for _ in range(512):
            phase_offset = rng.uniform(0,circumference)
            phases = [round((n["phase"]+phase_offset)%circumference,5) for n in lane_notes]
            if all(not lower <= value <= upper for value in phases):
                break
        else:
            raise ValueError("Cannot construct a safe initial score")
        notes.extend(dict(n,phase=value) for n,value in zip(lane_notes,phases))
    task_id = str(task.get("id") or "polyrhythm_customs_v2_seed_0001@0.1")
    challenge = hashlib.sha256(f"{seed}|{MECHANIC_ID}|d{level}|{REVISION}".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task_id,
                  challenge_id=challenge, revision=REVISION,
                  prompt="Clear every circulating note through its moving gold band.",
                  rail=rail, lanes=lanes, notes=notes, parameters=p,
                  run_limit_ms=120000, single_attempt=True,
                  generator=dict(name=REVISION, variant_count=10**18,
                                 variant_count_kind="independent seeded nonperiodic belt and gate motion"),
                  asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json",
                  render_boundary="Motion seeds and score geometry are browser render data, inspectable in static play. No solution trace is shipped.")
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
