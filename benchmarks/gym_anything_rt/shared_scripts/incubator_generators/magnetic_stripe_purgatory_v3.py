"""Continuous card feeds with inspectable cam housings; mode never seeds the world."""
from __future__ import annotations
import copy
import hashlib
import json
import random

MECHANIC_ID = "magnetic_stripe_purgatory_v3"
REVISION = "moving-reader-1"
PROFILES = {
    1: dict(feeds=1, height_amplitude=.62, speed_amplitude=.28, span_ms=5600, height_tolerance=.19, speed_tolerance=.18, response_ms=300, coupling=0., stripe_length=24.),
    2: dict(feeds=1, height_amplitude=.66, speed_amplitude=.40, span_ms=4500, height_tolerance=.16, speed_tolerance=.14, response_ms=350, coupling=0., stripe_length=24.),
    3: dict(feeds=2, height_amplitude=.66, speed_amplitude=.40, span_ms=5000, height_tolerance=.17, speed_tolerance=.15, response_ms=350, coupling=.08, stripe_length=24.),
    4: dict(feeds=2, height_amplitude=.76, speed_amplitude=.46, span_ms=4100, height_tolerance=.15, speed_tolerance=.13, response_ms=400, coupling=.16, stripe_length=26.),
    5: dict(feeds=2, height_amplitude=.83, speed_amplitude=.50, span_ms=3600, height_tolerance=.13, speed_tolerance=.115, response_ms=480, coupling=.25, stripe_length=28.),
}

def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or task.get("metadata", {}).get("control_condition") or
                              dict(difficulty=5, interaction="full", difficulty_parameters=PROFILES[5]))
    d = condition.get("difficulty")
    if type(d) is not int or d not in PROFILES or condition.get("interaction") not in ("full", "simplified"):
        raise ValueError("invalid moving-reader condition")
    if condition.get("difficulty_parameters") != PROFILES[d]:
        raise ValueError("profile must equal the declared configuration")
    rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}".encode()).digest())
    p = PROFILES[d]
    feeds = []
    for i in range(p["feeds"]):
        feeds.append(dict(id=f"feed-{i}", badge=["◇", "✳"][i], color=["#eebc68", "#80d3ce"][i],
                          height_seed=rng.getrandbits(32), speed_seed=rng.getrandbits(32),
                          phase_ms=rng.randrange(400, 3000),
                          pad=dict(x=805, y=57+i*218 if p["feeds"]==2 else 155, width=268, height=170)))
    world = dict(revision=REVISION, width=1120, height=500, parameters=copy.deepcopy(p), feeds=feeds,
                 tick_ms=20, duration_ms=90000, damage_limit=2.6, forecast_ms=800, trace_ms=600,
                 minimum_speed=.4, maximum_speed=1.6, knob_radius=20)
    # Preserve all V2 feed geometry, trajectories and physics. Only the access
    # to the live cam observation changes; it is not a certification quota.
    world['cam_inspection'] = dict(revision='service-hood-1', lift_px=32,
        tabs=[dict(x=568, y=(244 if p['feeds']==1 else 135+i*218)-94,
                   width=166, height=32) for i in range(p['feeds'])])
    challenge = hashlib.sha256((f"{seed}|{REVISION}|service-hood-1|"+json.dumps(p,sort_keys=True)).encode()).hexdigest()[:18]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task["id"],
                  challenge_id=challenge, control_condition=condition, world=world, single_attempt=True,
                  prompt="Inspect each reader's cam housing, then feed every card through its drifting read head. Match height and roller speed; damaged stripe cannot be repaired.",
                  submit_label="CERTIFY READ", source_anchors=["captchaware/cardSwipe"],
                  asset_manifest="shared_runtime/assets/provenance/magnetic_stripe_purgatory_v3_v0.json",
                  generator=dict(name=REVISION,variant_count=10**18,
                                 variant_count_kind="independently seeded, nonperiodic continuous reader trajectories"))
    truth=copy.deepcopy(public); truth["seed"]=str(seed)
    return public,truth
