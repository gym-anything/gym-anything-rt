"""TRG-088: original moving LiDAR/camera annotation game.

Interaction never participates in random generation. No old environment is used
as a game or modified. The finite trajectory is render data, not secret state.
"""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "surveyors_toybox_nonrealtime"
DONOR_MECHANIC_ID = "surveyors_toybox_v2"
REVISION = "live-cuboid-survey-v2"
PROFILES = {
    1: dict(target_count=1, distractor_count=1, moving_axes=2, yaw_amplitude=0,
            span_ms=22000, center_tolerance=.60, extent_tolerance=.18, yaw_tolerance=24, iou_min=.55, point_count=52, forecast_ms=2400),
    2: dict(target_count=1, distractor_count=2, moving_axes=3, yaw_amplitude=0,
            span_ms=19000, center_tolerance=.54, extent_tolerance=.16, yaw_tolerance=20, iou_min=.55, point_count=44, forecast_ms=1600),
    3: dict(target_count=2, distractor_count=2, moving_axes=3, yaw_amplitude=0,
            span_ms=18500, center_tolerance=.48, extent_tolerance=.14, yaw_tolerance=18, iou_min=.55, point_count=36, forecast_ms=1000),
    4: dict(target_count=2, distractor_count=3, moving_axes=3, yaw_amplitude=30,
            span_ms=16000, center_tolerance=.43, extent_tolerance=.12, yaw_tolerance=16, iou_min=.55, point_count=30, forecast_ms=800),
    5: dict(target_count=3, distractor_count=4, moving_axes=3, yaw_amplitude=55,
            span_ms=14500, center_tolerance=.38, extent_tolerance=.10, yaw_tolerance=12, iou_min=.55, point_count=24, forecast_ms=800),
}


def generate(task, seed):
    condition = task.get("_control_condition")
    level = (condition or {}).get("difficulty", 5)
    mode = (condition or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("Surveyor's Toybox V2 requires difficulty 1–5 and full/simplified interaction")
    profile = copy.deepcopy(PROFILES[level])
    supplied = (condition or {}).get("difficulty_parameters", {})
    if supplied and supplied != profile:
        raise ValueError("unsupported survey difficulty parameters")
    # Corresponding seeds retain the evaluated donor's puzzle content even
    # though the counterpart has its own mechanic namespace.
    rng = random.Random(hashlib.sha256(f"{DONOR_MECHANIC_ID}|{REVISION}|{seed}|d{level}".encode()).digest())
    colors = ["#f6ba68", "#5bd3bf", "#be9df3", "#f78b8e"]
    objects, targets, annotations = [], [], {}
    for index in range(profile["target_count"] + profile["distractor_count"]):
        target = index < profile["target_count"]
        slot = index if target else (index - profile["target_count"]) % profile["target_count"]
        shape = "tug" if target else "pallet"
        object_id = f"toy-{rng.getrandbits(40):010x}"
        half = [round(rng.uniform(.42, .61), 4), round(rng.uniform(.28, .42), 4), round(rng.uniform(.32, .46), 4)]
        base_y, base_z = rng.uniform(1.3, 3.1), rng.uniform(-1.6, 1.6)
        yaw = rng.uniform(-35, 35)
        sign = rng.choice((-1, 1))
        knots = []
        for knot in range(12):
            knots.append([
                round(sign * (-1 if knot % 2 else 1) * rng.uniform(2.4, 2.7), 5),
                round(rng.uniform(1.15, 3.35) if profile["moving_axes"] == 3 else base_y, 5),
                round(rng.uniform(-1.65, 1.65) if profile["moving_axes"] >= 2 else base_z, 5),
                round(yaw + rng.uniform(-profile["yaw_amplitude"], profile["yaw_amplitude"]), 5),
            ])
        # Separate in 3D, with intentional projected crossings at higher levels.
        offset = rng.randint(profile["span_ms"] // 5, profile["span_ms"] // 2)
        span = profile["span_ms"] + rng.randint(-900, 900)
        # C1 local steering changes velocity independently of the long sweep.
        # It is continuous, nonperiodic during an episode, and drawn by the
        # recent motion trail plus a difficulty-specific forecast. A fixed
        # nominal sweep cannot know the next correction from input times alone.
        steering_span = profile.get("steering_span_ms", 6000)
        steering = dict(knots=[round(rng.uniform(-.80, .80), 5) for _ in range(32)],
                        span_ms=rng.randint(round(.9*steering_span), round(1.1*steering_span)), offset_ms=rng.randint(0, 5000))
        points = []
        # Include all eight physical corners, then sparse returns on all faces.
        for x in (-1, 1):
            for y in (-1, 1):
                for z in (-1, 1):
                    points.append([x * half[0], y * half[1], z * half[2]])
        for point in range(profile["point_count"] - 8):
            local = [rng.uniform(-h, h) for h in half]
            face = point % 6
            local[face // 2] = half[face // 2] * (1 if face % 2 else -1)
            points.append([round(v, 5) for v in local])
        obj = dict(id=object_id, half=half, color=colors[slot], shape=shape,
                   local_points=points, motion=dict(knots=knots, span_ms=span, offset_ms=offset, steering=steering))
        objects.append(obj)
        if target:
            label = f"volume-{len(targets) + 1}"
            targets.append(dict(id=label, color=colors[slot], shape="tug", label=f"TUG {len(targets)+1}"))
            # Initial volumes are rough suggestions, not already fitted truth.
            u = offset / span
            f = u * u * (3 - 2 * u)
            center = [knots[0][i] + (knots[1][i] - knots[0][i]) * f for i in range(3)]
            annotations[label] = dict(center=[round(v + rng.choice((-1, 1)) * .50, 4) for v in center],
                                      half=[round(h * rng.uniform(.7, 1.3), 4) for h in half], yaw=round(yaw + 20, 4))
            obj["_target_label"] = label
    target_map = {obj.pop("_target_label"): obj["id"] for obj in objects if "_target_label" in obj}
    rng.shuffle(objects)
    public = dict(
        benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, physics_revision=REVISION,
        task_id=task["id"], challenge_id=hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}|d{level}".encode()).hexdigest()[:16],
        prompt="Link the tug portraits to the camera, fit their 3D volumes, then keep every volume on its moving tug.",
        submit_label="CERTIFY SURVEY", objects=objects, targets=targets, initial_annotations=annotations,
        world=dict(bounds=[[-3.85, 3.85], [.45, 4.0], [-2.25, 2.25]], tick_ms=20,
                   trail_ms=1000, forecast_ms=profile["forecast_ms"], turnaround_fraction=.06),
        views=dict(plan=dict(width=440, height=420, origin=[220, 210], scale=52, axes=[0, 2], signs=[1, 1]),
                   front=dict(width=440, height=420, origin=[220, 360], scale=52, axes=[0, 1], signs=[1, -1])),
        requirements=dict(center_tolerance=profile["center_tolerance"], extent_tolerance=profile["extent_tolerance"],
                          yaw_tolerance=profile["yaw_tolerance"], iou_min=profile["iou_min"],
                          charge_ms=8000, charge_leak=.5, lost_limit_ms=10000,
                          max_run_ms=90000, max_events=18000),
        timing=dict(mode="action_step", action_step_ms=20,
                    idle_behavior="stable_between_completed_controls"),
        difficulty_profile=profile, interaction_mode=mode, single_attempt=True,
        asset_manifest="shared_runtime/assets/provenance/surveyors_toybox_v2_v0.json",
        generator=dict(name=REVISION, variant_count=10**18, variant_count_kind="seeded cuboid sizes, sparse returns, nonrepeating 3D steering and headings"),
        render_boundary="The browser receives the geometry and finite motion paths needed to render the scene. Only the last second and the labelled difficulty-specific forecast are drawn. Future paths and object IDs are not secret from page internals; screenshot-only play is required.",
    )
    if condition is not None:
        public["control_condition"] = copy.deepcopy(condition)
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), target_map=target_map)
    return public, truth
