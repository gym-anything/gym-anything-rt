"""Original, seeded moving carbon-copy desk. No third-party assets."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "bureaucratic_signature_trap_v3_nonrealtime"
REVISION = "moving-carbon-v3-registration-2"
# Retain the earlier seeded physical paths while revising copying rules/display.
TRAJECTORY_REVISION = "moving-carbon-v1"
# The counterpart's renamed mechanic must not redraw V3's concealed fact.
# Keep the donor's registration namespace so corresponding seeds expose the
# same pointer-to-nib displacement.
CARBON_REGISTRATION_NAMESPACE = "bureaucratic_signature_trap_v3"
TRAJECTORY_MECHANIC_ID = "bureaucratic_signature_trap_v2"
PROFILES = {
    1: dict(duration_ms=20000, knot_ms=4000, tolerance=48, drift=12, drift_ms=3000, hazards=1, hazard_radius=30, response_s=.10, minimum_coverage=.80, maximum_gap=240),
    2: dict(duration_ms=22000, knot_ms=3200, tolerance=42, drift=20, drift_ms=2600, hazards=1, hazard_radius=34, response_s=.12, minimum_coverage=.82, maximum_gap=220),
    3: dict(duration_ms=24000, knot_ms=2600, tolerance=36, drift=28, drift_ms=2200, hazards=1, hazard_radius=38, response_s=.14, minimum_coverage=.84, maximum_gap=200),
    4: dict(duration_ms=24000, knot_ms=2200, tolerance=30, drift=34, drift_ms=1800, hazards=2, hazard_radius=38, response_s=.16, minimum_coverage=.86, maximum_gap=180),
    5: dict(duration_ms=24000, knot_ms=1800, tolerance=24, drift=40, drift_ms=1500, hazards=2, hazard_radius=42, response_s=.18, minimum_coverage=.88, maximum_gap=160),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or {})
    level = int(condition.get("difficulty", 4))
    if level not in PROFILES:
        raise ValueError("difficulty must be 1..5")
    params = dict(PROFILES[level])
    params.update(condition.get("difficulty_parameters") or {})
    if params != PROFILES[level]:
        raise ValueError("use the declared profile without overriding physical rules")
    rng = random.Random(hashlib.sha256(f"{seed}|{TRAJECTORY_MECHANIC_ID}|{TRAJECTORY_REVISION}".encode()).digest())
    count = params["duration_ms"] // params["knot_ms"] + 4
    # A different handwritten curve, with changing vertical turns and lateral
    # excursions; no repeating patrol and no wrap at the end of the sheet.
    knots = [[round(480 + (-1 if i % 2 else 1) * rng.uniform(135, 225), 3),
              round(rng.uniform(160, 340), 3)] for i in range(count)]
    drift = [[round(rng.uniform(-params["drift"], params["drift"]), 3),
              round(rng.uniform(-params["drift"], params["drift"]), 3)]
             for _ in range(params["duration_ms"] // params["drift_ms"] + 4)]
    hazards = []
    for i in range(params["hazards"]):
        span = 4000 + rng.randrange(800)
        points = [[round(rng.uniform(240, 730), 3), round(rng.uniform(135, 370), 3)]
                  for _ in range(params["duration_ms"] // span + 4)]
        hazards.append(dict(id=f"void-{i}", radius=params["hazard_radius"], span_ms=span, knots=points))
    world = dict(width=960, height=480, dt_ms=20, params=params, knots=knots,
                 drift_knots=drift, hazards=hazards, preview_ms=1400,
                 pen_radius=3, pen_speed=650, pen_acceleration=3600, lead_ms=200)
    # An independent draw preserves every frozen V2 trajectory and profile.
    # The top-sheet pointer transfers to the duplicate at this displacement.
    # Its registration coupon is physically covered until the corner is pulled.
    registration = random.Random(hashlib.sha256(f"{seed}|{CARBON_REGISTRATION_NAMESPACE}|carbon-registration".encode()).digest())
    world["carbon_offset"] = [registration.choice((-1, 1)) * registration.choice((72, 88, 104)),
                              registration.choice((-1, 1)) * registration.choice((56, 72, 88))]
    identity = hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}|d{level}".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  revision=REVISION, task_id=task["id"], challenge_id=identity,
                  prompt="Inspect the carbon registration, then countersign the moving original. Lift clear of VOID stamps; avoid long uncovered stretches of unobstructed original.",
                  world=world, generator=dict(name=REVISION, variant_count=10**18),
                  asset_manifest="environments/bureaucratic_signature_trap_v3_nonrealtime_env/assets_provenance.json")
    if condition:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
