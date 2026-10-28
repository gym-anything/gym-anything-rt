"""Original moving crate-support courier, grounded in survey IND-068.

Only geometry and the reproducible motor program enter public state. No route,
interception coordinates or solution transcript is supplied to the browser.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random

MECHANIC_ID = "hearthlift_courier_v3_nonrealtime"
SOURCE_MECHANIC_ID = "hearthlift_courier_v2"
REVISION = "moving-crate-hops-v2"
INSPECTION_REVISION = "retained-lift-surveys-v3"
MOTOR_REVISION = "announced-independent-knots-v1"
PROFILES = {
    1: dict(lift_count=3, gap=5.3, deck_width=2.8, depth_width=2.8, lateral_amplitude=1.7,
            height_amplitude=.35, motor_span_ms=2400, rise=.35, depth_turn=0., inherit=.35),
    2: dict(lift_count=3, gap=5.3, deck_width=2.5, depth_width=2.5, lateral_amplitude=1.9,
            height_amplitude=.5, motor_span_ms=2350, rise=.45, depth_turn=.7, inherit=.5),
    3: dict(lift_count=3, gap=5.3, deck_width=2.2, depth_width=2.2, lateral_amplitude=2.,
            height_amplitude=.65, motor_span_ms=2300, rise=.55, depth_turn=1., inherit=.65),
    4: dict(lift_count=4, gap=5.3, deck_width=1.95, depth_width=2., lateral_amplitude=2.1,
            height_amplitude=.8, motor_span_ms=2250, rise=.65, depth_turn=1.2, inherit=.8),
    5: dict(lift_count=5, gap=5.3, deck_width=1.8, depth_width=1.85, lateral_amplitude=2.2,
            height_amplitude=.95, motor_span_ms=2200, rise=.7, depth_turn=1.4, inherit=1.),
}


def episode_failure():
    """Read this runtime's existing failure journal, without modifying it."""
    directory = os.environ.get("GYM_ANYTHING_RT_STATE_DIR")
    if not directory:
        return ""
    try:
        with (Path(directory) / "attempts.jsonl").open(encoding="utf-8") as journal:
            if any(line.strip() for line in journal):
                return "A failed submission already ended this episode."
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError):
        return "Episode failure history is unavailable."
    return ""


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or
                              (task.get("metadata") or {}).get("control_condition"))
    level = (condition or {}).get("difficulty", 5)
    mode = (condition or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("unsupported Hearthlift difficulty or interaction")
    parameters = copy.deepcopy(PROFILES[level])
    if condition and condition.get("difficulty_parameters") != parameters:
        raise ValueError("Hearthlift profile must match its controls.json parameters")
    condition = condition or dict(difficulty=level, interaction=mode, real_time="live",
                                  difficulty_parameters=copy.deepcopy(parameters))
    # A suffix provides coupled, reproducible seeds for prediction diagnostics:
    # identical initial geometry/rails, independently drawn unannounced tails.
    # Ordinary seeds retain their original initial geometry and motion.
    prefix_seed = str(seed).split("::", 1)[0]
    # Retain the frozen V2 physical world, including its random motor tape.
    # V3 changes access to information, not geometry or difficulty parameters.
    rng = random.Random(hashlib.sha256(f"{prefix_seed}|{SOURCE_MECHANIC_ID}|{REVISION}".encode()).digest())
    n = parameters["lift_count"]
    side = rng.choice((-1, 1))
    platforms = [dict(id="quay", center=[0., 0., 0.], half=[1.65, 1.65],
                      thickness=.42, motion=None, kind="quay", color="#82a997")]
    for i in range(n):
        platforms.append(dict(
            id=f"lift-{i+1}", center=[parameters["gap"]*(i+1), parameters["rise"]*(i+1),
                                     side*parameters["depth_turn"]*((i%2)*2-1)],
            half=[parameters["deck_width"]/2, parameters["depth_width"]/2],
            thickness=.65, kind="lift", color=["#83b9aa", "#d3a16b", "#a4a9ce"][i%3],
            motion=dict(seed=rng.getrandbits(32), span_ms=parameters["motor_span_ms"],
                        offset_ms=rng.randrange(parameters["motor_span_ms"]),
                        amplitude=[.28+level*.035, parameters["height_amplitude"],
                                   parameters["lateral_amplitude"]])))
    # The final hearth also moves: arriving once is insufficient; the carried
    # load must be released while the courier is actually supported by it.
    platforms.append(dict(id="hearth", center=[parameters["gap"]*(n+1), parameters["rise"]*(n+1),0.],
                          half=[1.2, 1.2], thickness=.6, kind="hearth", color="#dd875c",
                          motion=dict(seed=rng.getrandbits(32), span_ms=parameters["motor_span_ms"]+700,
                                      offset_ms=rng.randrange(4000),
                                      amplitude=[.3, parameters["height_amplitude"]*.6,
                                                 parameters["lateral_amplitude"]*.65])))
    for platform in platforms:
        spec = platform["motion"]
        if not spec:
            continue
        initial_last = math.ceil((spec["offset_ms"] + 3200) / spec["span_ms"])
        count = math.ceil((240000 + 3200 + spec["offset_ms"] + 10) / spec["span_ms"]) + 2
        knots = []
        for index in range(count):
            if index <= initial_last:
                # Preserve the old initial 3.2 s rail exactly. It is safe to
                # reconstruct this prefix; it no longer determines the tail.
                point = []
                for axis in range(3):
                    x = ((spec["seed"] + axis*7919) ^ ((index+1)*0x9E3779B9)) & 0xffffffff
                    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xffffffff
                    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xffffffff
                    point.append(((x ^ (x >> 16)) & 0xffffffff)/4294967295*2-1)
            else:
                # Separately keyed draws have no exposed linear/invertible
                # motor recurrence. Future knots are ordinary replay geometry,
                # announced by the same rolling rail before they affect play.
                draw = random.Random(hashlib.sha256(
                    f"{seed}|{SOURCE_MECHANIC_ID}|{MOTOR_REVISION}|{platform['id']}|{index}".encode()).digest())
                point = [draw.uniform(-1., 1.) for _ in range(3)]
                while point[0] == knots[-1][0]:
                    point = [draw.uniform(-1., 1.) for _ in range(3)]
            knots.append(point)
        del spec["seed"]
        spec["knots"] = knots
    world = dict(revision=REVISION, motor_revision=MOTOR_REVISION, platforms=platforms, parameters=parameters,
                 physics=dict(tick_ms=10, gravity=8., jump_speed=6.8, aim_seconds=1.6,
                              speed_limit=5.2, radius=.18, inherit=parameters["inherit"],
                              fall_y=-4., play_time_ms=240000, timing_mode="action_triggered"),
                 chart=dict(width=1000,height=290,x_min=-2.8,x_max=parameters["gap"]*(n+1)+3.,
                            z_min=-5.2,z_max=5.2,margin=25),
                 preview_ms=3200, trail_ms=600)
    task_id = task.get("id") or f"{MECHANIC_ID}_seed_0001@0.1"
    failure = episode_failure()
    token=json.dumps(dict(seed=str(seed), world=world, task_id=task_id, condition=condition,
                         episode_failed=bool(failure), inspection_revision=INSPECTION_REVISION),
                     sort_keys=True,separators=(",",":"))
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task_id,
                  challenge_id=hashlib.sha256(token.encode()).hexdigest()[:20],
                  control_condition=condition, world=world, inspection_revision=INSPECTION_REVISION,
                  prompt="Carry the ember crate across the moving lift stacks. Burn it at the hearth.",
                  submit_label="CERTIFY DELIVERY", single_attempt=True,
                  episode_failed=bool(failure), episode_feedback=failure,
                  asset_manifest="shared_runtime/assets/provenance/hearthlift_courier_v3_v0.json",
                  generator=dict(name=MOTOR_REVISION, variant_count=10**18),
                  render_boundary="Motor knots are browser-inspectable replay geometry. Recent trails are visible initially. Direct lift inspection reveals and retains that lift's rolling 3.2-second rail in both views; a deliberate hop resolves the next fixed replay; no oracle route or invertible motor key is shipped.")
    truth=copy.deepcopy(public)
    truth["seed"]=str(seed)
    return public,truth
