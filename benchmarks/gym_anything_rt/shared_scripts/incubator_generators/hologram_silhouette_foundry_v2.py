"""Source-derived moving three-view casting; no dependency on the old foundry."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "hologram_silhouette_foundry_v2"
REVISION = "moving-three-die-v2-separated-motion"
SOURCE_ANCHORS = ["nextgen-captchas/3D_Viewpoint", "nextgen-captchas/Layered_Stack", "captcha-royale/cubefolding"]
PROFILES = {
    1: dict(rod_count=3, active_axes=2, tolerance=.35, span_ms=6000, translation_amplitude=1.2, yaw_amplitude=0, pitch_amplitude=0, servo_speed=3.0, servo_acceleration=18., shared_speed=9., fusion_seconds=7., leak_rate=1.5),
    2: dict(rod_count=4, active_axes=3, tolerance=.32, span_ms=5600, translation_amplitude=1.2, yaw_amplitude=0, pitch_amplitude=0, servo_speed=3.0, servo_acceleration=16., shared_speed=8., fusion_seconds=7., leak_rate=1.5),
    3: dict(rod_count=5, active_axes=4, tolerance=.29, span_ms=5200, translation_amplitude=1.2, yaw_amplitude=.55, pitch_amplitude=0, servo_speed=2.8, servo_acceleration=14., shared_speed=7., fusion_seconds=7., leak_rate=1.5),
    4: dict(rod_count=6, active_axes=5, tolerance=.26, span_ms=4800, translation_amplitude=1.2, yaw_amplitude=.55, pitch_amplitude=.45, servo_speed=2.6, servo_acceleration=12., shared_speed=6., fusion_seconds=7., leak_rate=1.5),
    5: dict(rod_count=7, active_axes=5, tolerance=.22, span_ms=4400, translation_amplitude=1.3, yaw_amplitude=.65, pitch_amplitude=.55, servo_speed=2.4, servo_acceleration=10., shared_speed=4.5, fusion_seconds=7., leak_rate=1.5),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or dict(difficulty=5, interaction="full", difficulty_parameters=PROFILES[5]))
    level = int(condition["difficulty"])
    p = dict(PROFILES[level])
    p.update(condition.get("difficulty_parameters") or {})
    if p != PROFILES[level] or condition["interaction"] not in ("full", "simplified"):
        raise ValueError("unsupported foundry control profile")
    condition["difficulty_parameters"] = copy.deepcopy(p)
    rng = random.Random(hashlib.sha256(f"{MECHANIC_ID}|{REVISION}|{seed}".encode()).digest())
    colors = ["#ff8269", "#70dbc9", "#eac868", "#b493f4", "#79baff", "#e397c9", "#b4d77c"]
    # A rigid, asymmetric 3D sculpture. Rods occupy separate boxes; rotation
    # preserves their separation. Projected rods can genuinely occlude each other.
    bases = [(-.66, -.54, -.48), (.53, -.48, .52), (-.5, .58, .48), (.61, .51, -.53), (0, .07, -.68), (.03, -.7, .02), (-.7, .01, .05)]
    rods = []
    for i in range(p["rod_count"]):
        center = [round(v + rng.uniform(-.055, .055), 6) for v in bases[i]]
        axis = i % 3
        length = rng.uniform(.6, .83)
        ends = [list(center), list(center)]
        ends[0][axis] -= length / 2
        ends[1][axis] += length / 2
        rods.append(dict(id=f"rod-{i+1}", color=colors[i], ends=ends, radius=.07))
    amplitudes = [p["translation_amplitude"] if i < min(3, p["active_axes"]) else 0 for i in range(3)] + [p["yaw_amplitude"], p["pitch_amplitude"]]
    knots = []
    for _ in range(25):
        # Reject near-stationary stretches, not valid player solutions. A smooth
        # trip always crosses at least 1.6 world units in its visible XY plane.
        # Directions, lengths, depth and rotations remain independently varied.
        for _attempt in range(10000):
            candidate = [rng.uniform(-a,a) if a else 0. for a in amplitudes]
            if not knots or sum((candidate[i]-knots[-1][i])**2 for i in (0,1)) >= 1.6**2:
                knots.append(candidate)
                break
        else:
            raise RuntimeError("failed to generate a moving die trajectory")
    motion = dict(span_ms=p["span_ms"], amplitudes=amplitudes, waypoints=knots,
                  minimum_xy_travel=1.6, interpolation="continuous-cubic-smoothstep")
    task_id = task["id"]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, revision=REVISION,
        task_id=task_id, challenge_id=hashlib.sha256(f"{seed}|{task_id}|{REVISION}|{level}".encode()).hexdigest()[:18],
        control_condition=condition, rods=rods, motion=motion, parameters=p,
        initial_pose=[0.] * 5, limits=[1.6, 1.6, 1.6, .95, .8], tick_ms=20,
        run_limit_ms=90000, stage=dict(width=1120, height=570),
        prompt="Keep every colored tip inside its matching moving die ring in FRONT, SIDE and TOP. All three fits together fuse the casting; lost fit drains fusion.",
        asset_manifest="shared_runtime/assets/provenance/hologram_silhouette_foundry_v2_v0.json",
        generator=dict(name="moving_three_die_foundry", variant_count=10**15), single_attempt=True)
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
