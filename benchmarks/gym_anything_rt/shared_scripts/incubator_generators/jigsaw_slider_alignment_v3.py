"""Moving image registration with discoverable horizontal drive transmissions."""
from __future__ import annotations

import copy
import hashlib
import math
import random

MECHANIC_ID = "jigsaw_slider_alignment_v3"
PROFILES = {
    1: dict(piece_count=1, position_tolerance=22, angle_tolerance=180, velocity_tolerance=65,
            angular_velocity_tolerance=180, spring=0, stiffness=30, damping=10, span_min_ms=3800, span_max_ms=5400, rotation_amplitude=0),
    2: dict(piece_count=1, position_tolerance=19, angle_tolerance=13, velocity_tolerance=55,
            angular_velocity_tolerance=35, spring=0, stiffness=27, damping=9, span_min_ms=3600, span_max_ms=5200, rotation_amplitude=32),
    3: dict(piece_count=2, position_tolerance=17, angle_tolerance=11, velocity_tolerance=50,
            angular_velocity_tolerance=30, spring=2, stiffness=24, damping=9, span_min_ms=3400, span_max_ms=4900, rotation_amplitude=38),
    4: dict(piece_count=3, position_tolerance=15, angle_tolerance=9, velocity_tolerance=45,
            angular_velocity_tolerance=27, spring=3, stiffness=22, damping=8, span_min_ms=3200, span_max_ms=4600, rotation_amplitude=42),
    5: dict(piece_count=3, position_tolerance=12, angle_tolerance=7, velocity_tolerance=40,
            angular_velocity_tolerance=24, spring=4, stiffness=20, damping=8, span_min_ms=3000, span_max_ms=4400, rotation_amplitude=48),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or task.get("metadata", {}).get("control_condition") or
                              dict(difficulty=5, interaction="full", real_time="live"))
    level = int(condition["difficulty"])
    if level not in PROFILES or condition["interaction"] not in ("full", "simplified"):
        raise ValueError("unsupported registration controls")
    p = copy.deepcopy(PROFILES[level])
    supplied = condition.get("difficulty_parameters", {})
    if supplied and supplied != p:
        raise ValueError("difficulty parameters differ from the registered profile")
    condition["difficulty_parameters"] = p
    rng = random.Random(hashlib.sha256(f"{MECHANIC_ID}|{seed}|{level}".encode()).digest())
    pieces = []
    for index in range(p["piece_count"]):
        knots, t, previous = [], 0, None
        while t <= 130000:
            # Opposite half planes alternate, but direction, span, height and rotation
            # vary independently. There is no repeating path or stationary long plateau.
            side = 1 if len(knots) % 2 else -1
            x = side * rng.uniform(61, 81)
            y = rng.uniform(-51, 51)
            a = rng.uniform(-p["rotation_amplitude"], p["rotation_amplitude"])
            if previous is not None and p["rotation_amplitude"]:
                a = (-1 if previous[2] > 0 else 1) * rng.uniform(.45, 1) * p["rotation_amplitude"]
            knots.append(dict(t_ms=t, x=x, y=y, angle=a))
            previous = (x, y, a)
            t += rng.randint(p["span_min_ms"], p["span_max_ms"])
        polygon = [[-43,-43],[-13,-43],[-15,-56],[0,-63],[15,-56],[13,-43],[43,-43],
                   [43,-13],[56,-15],[63,0],[56,15],[43,13],[43,43],[13,43],
                   [15,30],[0,24],[-15,30],[-13,43],[-43,43],[-43,13],[-30,15],[-24,0],[-30,-15],[-43,-13]]
        pieces.append(dict(id=f"fragment-{index+1}", label=f"{index+1:02d}",
                           color=["#f1b85a", "#66d9c4", "#ee8eaf"][index],
                           motif=rng.randrange(5), polygon=polygon, knots=knots,
                           initial=dict(x=rng.uniform(-42,42), y=105, angle=0)))
    # A separate stream preserves every existing path, motif and initial pose.
    # Neither input mode nor task identity selects the transmission. The sign
    # is runtime render data, concealed from the initial screenshot, not a secret
    # against page-state inspection. A nonzero horizontal command reveals it.
    for index, piece in enumerate(pieces):
        digest = hashlib.sha256(f"{MECHANIC_ID}|drive|{seed}|{level}|{index}".encode()).digest()
        piece["drive_x"] = 1 if digest[0] & 1 else -1
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task["id"],
                  challenge_id=hashlib.sha256(f"{seed}|{task['id']}".encode()).hexdigest()[:20],
                  physics_revision="moving-registration-v3-drive-1", control_condition=condition, parameters=p,
                  stage=dict(width=1080, height=540, center_y=220, dial_y=466, dial_radius=38),
                  step_ms=10, run_limit_ms=120000, weld_ms=6000, max_speed=350, max_acceleration=1400,
                  angular_stiffness=24, angular_damping=9, max_angular_speed=180,
                  preview_ms=1200, trail_ms=300, pieces=pieces,
                  prompt="Restore the moving pictures. Each horizontal drive may follow or reverse your hand. Test a horizontal move and compare HAND X with the destination square; no CLAMP is needed to learn the response. Steer each fragment into its matching aperture"+("; turn its dial to match the angle." if p["rotation_amplitude"] else ". Rotation is locked at zero degrees.")+" When every rim is green, press CLAMP. Keep every fragment registered while the six-second seam closes. A bad clamp or a slipped seam ends this attempt. Coloured dots show the next 1.2 seconds of motion. Carriages have inertia; springs couple neighbouring carriages. Holding the mouse never stops a picture.",
                  asset_manifest="shared_runtime/assets/provenance/jigsaw_slider_alignment_v3_v0.json",
                  generator=dict(name="moving_registration_aperiodic", variant_count=10**18))
    truth = copy.deepcopy(public)
    truth["seed"] = seed
    return public, truth
