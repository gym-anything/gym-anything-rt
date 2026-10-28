"""Source-derived quadruped escape; no dependency on the original game."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random

MECHANIC_ID = "crater_walker_v3"
REVISION = "drifting-supports-2"
SURVEY_REVISION = "dust-survey-1"
LEGS = ("FL", "FR", "RL", "RR")
PROFILES = {
    1: dict(terraces=2, pad_radius=.68, drift=.78, span_ms=5200, rise=.20,
            heave=.08, guided_legs=["FL"], stride=3.0),
    2: dict(terraces=2, pad_radius=.57, drift=.88, span_ms=4500, rise=.25,
            heave=.13, guided_legs=["FL", "FR"], stride=3.0),
    3: dict(terraces=3, pad_radius=.48, drift=.95, span_ms=3900, rise=.30,
            heave=.20, wind=.45, body_response=12., tip_ms=1000, stride=3.0),
    4: dict(terraces=3, pad_radius=.40, drift=1.02, span_ms=3300, rise=.35,
            heave=.28, wind=.65, body_response=10., tip_ms=850, stride=3.0),
    5: dict(terraces=3, pad_radius=.33, drift=1.10, span_ms=2900, rise=.40,
            heave=.36, wind=.85, body_response=8., tip_ms=700, stride=3.0),
}


def episode_failure():
    directory = os.environ.get("GYM_ANYTHING_RT_STATE_DIR")
    if not directory:
        return ""
    try:
        with (Path(directory) / "attempts.jsonl").open(encoding="utf-8") as journal:
            for line in journal:
                if line.strip() and not json.loads(line).get("server_grade", {}).get("passed"):
                    return "A failed submission already ended this episode."
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError, ValueError, AttributeError):
        return "Episode failure history is unavailable."
    return ""


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or
                              (task.get("metadata") or {}).get("control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    mode = (condition or {}).get("interaction", "full")
    if level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("unsupported crater walker condition")
    parameters = copy.deepcopy(PROFILES[level])
    parameters.update((condition or {}).get("difficulty_parameters") or {})
    if parameters != PROFILES[level]:
        raise ValueError("profile parameters must match the declared difficulty")
    if condition is None:
        condition = dict(difficulty=level, interaction=mode, real_time="live",
                         difficulty_parameters=copy.deepcopy(parameters))
    revision = "guided-supports-1" if parameters.get("guided_legs") else REVISION
    rng = random.Random(hashlib.sha256(f"{str(seed).split('::', 1)[0]}|{MECHANIC_ID}|{revision}".encode()).digest())
    pads = []
    offsets = ((.90, -1.6), (.90, 1.6), (-.90, -3.4), (-.90, 3.4))
    for terrace in range(parameters["terraces"] + 1):
        bend = rng.uniform(-.05, .05) if terrace else 0
        for leg, (x, y) in zip(LEGS, offsets):
            if parameters.get("guided_legs") and leg not in parameters["guided_legs"] and terrace != parameters["terraces"]:
                continue
            pads.append(dict(id=f"{leg}-{terrace}", leg=leg, terrace=terrace,
                             base=[round(x + terrace * parameters["stride"], 4),
                                   round(y + bend, 4), round(.35 + terrace * parameters["rise"], 4)],
                             radius=parameters["pad_radius"],
                             # Home plates also evolve; the rim is a solid final dock.
                             amplitude=[parameters["drift"], parameters["drift"] * .12,
                                        parameters["heave"]] if terrace < parameters["terraces"] else [0, 0, 0]))
    tail_rng = random.Random(hashlib.sha256(f"{seed}|independent-tail|{revision}".encode()).digest())
    for pad in pads:
        count = math.ceil((180000 + 3000) / parameters["span_ms"]) + 2
        announced = math.ceil(3000 / parameters["span_ms"])
        pad["knots"] = [[round((rng if k <= announced else tail_rng).uniform(-1, 1), 7)
                          for _ in range(3)] for k in range(count)]
    wind_count = math.ceil((180000+3000)/3700)+2
    wind = dict(span_ms=3700, knots=[[round((rng if k <= 1 else tail_rng).uniform(-1,1),7) for _ in range(2)] for k in range(wind_count)])
    world = dict(revision=revision, parameters=parameters, pads=pads, legs=list(LEGS),
                 tick_ms=10, swing_ms=1000, toe_radius=.09, lift_clearance=1.8,
                 max_leg_reach=8.5, ballast_limit=1.25, wind=wind,
                 max_ms=180000, preview_ms=3000,
                 chart=dict(width=860, height=500, scale=52, origin=[130, 250]),
                 balance_chart=dict(width=280, height=240, scale=30, origin=[140, 120]))
    if parameters.get("guided_legs"):
        # A visible fixed gantry carries the chassis at the footprint center.
        # Landing remains a commanded coordinate on a moving plate, not an assist.
        world["guide"] = dict(x_min=-2, x_max=9, y_min=-4.2, y_max=4.2)
    task_id = str(task.get("id") or "crater_walker_v3_seed_0001@0.1")
    # Keep the mechanically forked V2 motion tapes and all profile geometry.
    # Only the information contract (and therefore challenge identity) changes.
    cid = hashlib.sha256(f"{seed}|{MECHANIC_ID}|{revision}|{SURVEY_REVISION}|d{level}".encode()).hexdigest()[:16]
    guided = parameters.get("guided_legs")
    survey = dict(revision=SURVEY_REVISION, radius=.70,
                  initially_known=[f"{leg}-{parameters['terraces'] if guided and leg not in guided else 0}"
                                   for leg in LEGS])
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task_id, challenge_id=cid, world=world, survey=survey,
                  prompt="Escape on four feet. Shift your weight, then step onto the drifting plates.",
                  submit_label="CERTIFY ESCAPE", single_attempt=True,
                  control_condition=condition,
                  generator=dict(name=revision, variant_count=10**18),
                  asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json")
    if parameters.get("guided_legs"):
        public["prompt"] = "The guide carries the chassis. Land the undocked toes on their moving plates, then the rim."
    failure = episode_failure()
    public["episode_failed"] = bool(failure)
    public["episode_feedback"] = failure
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
