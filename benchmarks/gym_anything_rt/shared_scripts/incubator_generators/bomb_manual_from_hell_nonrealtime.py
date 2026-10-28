"""Source-derived action-settled acetate defusal; the evaluated donor is preserved."""
from __future__ import annotations

import copy
import hashlib
import math
import random

MECHANIC_ID = "bomb_manual_from_hell_nonrealtime"
DONOR_MECHANIC_ID = "bomb_manual_from_hell_v2"
REVISION = "live-acetate-drums-v3"
PROFILES = {
    1: dict(modules=3, layers=1, fuse_speed=.36, guard_speed=.12, aperture_half_deg=85, rate_variation=.65, load_coupling=.04),
    2: dict(modules=3, layers=2, fuse_speed=.38, guard_speed=.17, aperture_half_deg=78, rate_variation=.65, load_coupling=.07),
    3: dict(modules=3, layers=2, fuse_speed=.40, guard_speed=.22, aperture_half_deg=70, rate_variation=.65, load_coupling=.10),
    4: dict(modules=4, layers=2, fuse_speed=.42, guard_speed=.28, aperture_half_deg=63, rate_variation=.65, load_coupling=.14),
    5: dict(modules=4, layers=3, fuse_speed=.44, guard_speed=.34, aperture_half_deg=57, rate_variation=.65, load_coupling=.18),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or task.get("metadata", {}).get("control_condition"))
    level = (condition or {}).get("difficulty", 5)
    mode = (condition or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("invalid acetate control condition")
    parameters = copy.deepcopy((condition or {}).get("difficulty_parameters") or PROFILES[level])
    if parameters != PROFILES[level]:
        raise ValueError("acetate profile must match its declared difficulty")
    condition = dict(difficulty=level, interaction=mode, real_time="live", difficulty_parameters=parameters)
    # Keep corresponding seeds aligned with the evaluated donor after the
    # public mechanic is renamed for the counterpart.
    seed_key = f"{seed}|{DONOR_MECHANIC_ID}|{level}|{REVISION}"
    rng = random.Random(hashlib.sha256(seed_key.encode()).digest())
    centers = [(225, 135), (675, 135), (225, 415), (675, 415)]
    modules = []
    for i in range(parameters["modules"]):
        def motor(speed):
            return dict(phase=rng.uniform(-math.pi, math.pi), speed=speed*rng.choice((-1, 1))*rng.uniform(.85, 1.15),
                        seed=rng.getrandbits(32), span_ms=rng.randrange(1800, 3001, 20))
        modules.append(dict(id=f"drum-{i}", center=list(centers[i]), label=f"{i+1:02d}",
                            fuse=motor(parameters["fuse_speed"]),
                            guards=[motor(parameters["guard_speed"]*(1+.12*j)) for j in range(parameters["layers"])]))
    world = dict(revision=REVISION, parameters=parameters, modules=modules,
                 width=900, height=560, orbit_radius=72, fuse_radius=17,
                 guard_radii=[82, 89, 96], knob_radius=23, knob_step_deg=15,
                 forecast_ms=1200, tick_ms=20, max_active_ms=180000,
                 cutter_recharge_ms=4000)
    identity = hashlib.sha256(seed_key.encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task["id"],
                  challenge_id=identity, world=world, control_condition=condition,
                  prompt="Expose each fuse through every acetate guard, then snip its collar. Positions hold between deliberate controls; a failed snip, incomplete seal, or action-count engine expiry ends the episode. Inspection and manual-leaf adjustments remain allowed.",
                  # Reuse the existing donor manifest because the counterpart
                  # keeps the donor's procedural artwork and CSS.
                  asset_manifest="shared_runtime/assets/provenance/bomb_manual_from_hell_v2_v0.json",
                  generator=dict(name=REVISION, variation="donor-seeded independent motor rates and initial phases; action-settled counterpart"))
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
