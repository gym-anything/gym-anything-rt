"""Original, source-derived kinetic layout registration game."""
from __future__ import annotations

import copy
import hashlib
import random

# Keep the V3 seed stream independent of the counterpart namespace. The public
# mechanic id is renamed below, but corresponding seeds retain V3 content.
MECHANIC_ID = "reflow_vitrine_v3_nonrealtime"
SOURCE_MECHANIC_ID = "reflow_vitrine_v3"
REVISION = "kinetic-registration-1"
LINKAGE_REVISION = "frame-linkage-inspection-1"
PROFILES = {
    1: dict(seam_count=1, tolerance_px=18, wind_speed=26, gust_span_ms=4200, inertia_s=.18),
    2: dict(seam_count=2, tolerance_px=15, wind_speed=30, gust_span_ms=3900, inertia_s=.23),
    3: dict(seam_count=3, tolerance_px=13, wind_speed=34, gust_span_ms=3600, inertia_s=.30),
    4: dict(seam_count=3, tolerance_px=10, wind_speed=38, gust_span_ms=3300, inertia_s=.40),
    5: dict(seam_count=4, tolerance_px=8.5, wind_speed=42, gust_span_ms=3000, inertia_s=.48),
}
DEFAULT_LEVEL = 4
STAGE = dict(width=800, height=376, x=38, y=24, w=724, h=320)


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    level = int((condition or {}).get("difficulty", DEFAULT_LEVEL))
    if level not in PROFILES:
        raise ValueError("reflow difficulty must be 1 through 5")
    parameters = copy.deepcopy((condition or {}).get("difficulty_parameters", PROFILES[level]))
    if parameters != PROFILES[level]:
        raise ValueError("difficulty parameters do not match the kinetic layout profile")
    mode = (condition or {}).get("interaction", "full")
    if mode not in ("full", "simplified"):
        raise ValueError("unknown reflow interaction surface")
    stable = hashlib.sha256(f"{SOURCE_MECHANIC_ID}|{REVISION}|{seed}|d{level}".encode()).hexdigest()
    rng = random.Random(int(stable[:16], 16))
    target = [round(rng.uniform(.39, .56), 5) for _ in range(4)]
    # Positions are fractions inside their parent frame; D is nested inside A/B.
    # The initial display is in register. Starting the lighting inspection turns
    # on the fans; preparation can set trims but cannot pre-run the inspection.
    world = dict(revision=REVISION, parameters=parameters, stage=copy.deepcopy(STAGE),
                 target=target, initial=target[:], gust_seeds=[rng.getrandbits(32) for _ in range(4)],
                 motor_speed=96, tick_ms=10, action_step_ms=100, duration_ms=20000, blur_budget_ms=1800,
                 limits=[.22, .78], trail_ms=600)
    kinds = ["coat", "vase", "lamp", "shoe", "orb"]
    rng.shuffle(kinds)
    world["merchandise"] = kinds
    # Keep the existing geometry/gust stream intact. Only the trim linkage is
    # new: selecting a frame exposes its rail and direction, as V1's frame
    # inspector exposed the selected frame's layout rules. Both modes share it.
    linkage_rng = random.Random(int(hashlib.sha256(f"{stable}|{LINKAGE_REVISION}".encode()).hexdigest(), 16))
    rails = list(range(1, parameters["seam_count"] + 1))
    linkage_rng.shuffle(rails)
    world["linkage_revision"] = LINKAGE_REVISION
    world["linkages"] = [dict(rail=rail, sign=linkage_rng.choice((-1, 1))) for rail in rails]
    challenge = hashlib.sha256(f"{stable}|{LINKAGE_REVISION}".encode()).hexdigest()
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task["id"], challenge_id=f"rv3-{challenge[:18]}", world=world,
                  prompt="Inspect the frame linkages, then keep the moving display registered throughout the lighting inspection.",
                  asset_manifest="shared_runtime/assets/provenance/reflow_vitrine_v3_v0.json",
                  generator=dict(name="kinetic_nested_layout", variant_count=10**18,
                                 variant_count_kind="seeded frame proportions, merchandise and independent nonperiodic gusts"))
    if condition:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
