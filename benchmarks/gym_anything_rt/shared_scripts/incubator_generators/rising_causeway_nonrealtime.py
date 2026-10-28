"""Original moving architecture derived from survey VGE-482/483/484.

Generation never depends on the interaction mode. Motion seeds are rendering
data, not an oracle route; the screenshot-only player sees motion and trails.
"""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "rising_causeway_nonrealtime"
DONOR_MECHANIC_ID = "rising_causeway_v2"
REVISION = "visible-contact-measurements-v5"
TIMING_MODE = "action_step"
ACTION_STEP_MS = 400
LAUNCH_SETTLE_MS = 2400
RETRY_POLICY = dict(revision="retry-policy-20261006", classification="retry_exception")
PROFILES = {
    # Low levels retain generous clearance, damping and authority, but their
    # first drift segment must not make the initial chart predict the whole
    # shortest traversal. Later independent knots require fresh announcements.
    1: dict(half_width=1.38, landing_half_width=1.50, sway=2.4, span_ms=5800, wind=0.30, steering=4.8, drag=1.8, cruise=1.10, stair_height=0.90, bend=0.8),
    2: dict(half_width=1.22, landing_half_width=1.32, sway=2.6, span_ms=5800, wind=0.45, steering=4.6, drag=1.7, cruise=1.15, stair_height=1.00, bend=1.0),
    3: dict(half_width=1.06, landing_half_width=1.14, sway=2.8, span_ms=5800, wind=0.65, steering=4.4, drag=1.6, cruise=1.20, stair_height=1.10, bend=1.2),
    4: dict(half_width=0.90, landing_half_width=0.96, sway=3.0, span_ms=5400, wind=0.85, steering=4.2, drag=1.5, cruise=1.25, stair_height=1.20, bend=1.4),
    5: dict(half_width=0.76, landing_half_width=0.82, sway=3.2, span_ms=4600, wind=1.05, steering=4.0, drag=1.4, cruise=1.30, stair_height=1.30, bend=1.6),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    difficulty = int((condition or {}).get("difficulty", 5))
    if difficulty not in PROFILES:
        raise ValueError("difficulty must be 1..5")
    parameters = copy.deepcopy(PROFILES[difficulty])
    overrides = (condition or {}).get("difficulty_parameters", {})
    if set(overrides) - set(parameters):
        raise ValueError("unknown causeway difficulty parameter")
    parameters.update(overrides)
    # Keep corresponding seeds on the evaluated V2 geometry.  The counterpart
    # namespace changes identity and timing only; it must not silently create a
    # second puzzle family.
    rng = random.Random(hashlib.sha256(f"{seed}|{DONOR_MECHANIC_ID}".encode()).digest())
    world = dict(
        revision=REVISION, parameters=parameters, tick_ms=10, radius=0.22,
        timing_mode=TIMING_MODE, action_step_ms=ACTION_STEP_MS,
        launch_settle_ms=LAUNCH_SETTLE_MS,
        start=[1.0, 0.0, 0.0], gravity=3.2, spring_vz=3.84,
        spring_vx=3.5, spring_vy=6.0, air_drag=0.35, air_wind=0.12,
        red_start=4.0, red_end=10.0, stair_end=16.0,
        launch_x=16.25, slab_end=18.0, landing_start=19.4,
        delivery_start=25.8, forecast_ms=6000,
        end_x=31.0, max_time_ms=90000,
        motion_seeds=[rng.getrandbits(32) for _ in range(4)],
        motion_offsets=[round(rng.uniform(-0.8, 0.8), 6) for _ in range(3)],
        bend_points=[round(rng.uniform(-1, 1), 6) for _ in range(3)],
        # The clicked screen end that rises is seeded by the camera mirror.
        mirror=rng.choice([-1, 1]), palette=rng.choice(["tide", "dusk", "copper"]),
    )
    task_id = str(task["id"])
    challenge_id = hashlib.sha256(f"{seed}|{difficulty}|{REVISION}".encode()).hexdigest()[:20]
    public = dict(
        benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
        task_id=task_id, challenge_id=challenge_id, world=world,
        source_anchors=["VGE-482", "VGE-483", "VGE-484"],
        asset_manifest="shared_runtime/assets/provenance/rising_causeway_v2_v0.json",
        generator=dict(name=REVISION, variant_count=10**18),
        prompt="Raise the red bridge, turn the yellow stair toward the far ledge, and prime the blue spring. Each deliberate drive or aim control advances one fixed action step; waiting leaves the visible architecture unchanged. Drive onto the spring, then aim and release into the moving delivery bay. Wheels cannot steer in air. A fall ends the attempt; TRY AGAIN preserves failures.",
        retry_policy=copy.deepcopy(RETRY_POLICY),
    )
    if condition is not None:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
