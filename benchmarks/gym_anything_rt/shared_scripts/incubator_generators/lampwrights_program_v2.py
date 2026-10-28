"""Original TAE-280 transformation: dispatch icon routines across moving roofs."""
from __future__ import annotations

import copy
import hashlib
import json
import random

MECHANIC_ID = "lampwrights_program_v2"
REVISION = "moving-roofs-v5"
# Retain layouts, lamp placements and motion seeds across the separation fix.
SEED_REVISION = "moving-roofs-v1"
PROFILES = {
    1: dict(roof_count=6, lamp_count=2, half_width=.48, sway=.01, lift=1.05, span_ms=8500, momentum=0., routine_slots=4),
    2: dict(roof_count=7, lamp_count=2, half_width=.45, sway=.04, lift=1.11, span_ms=7400, momentum=.25, routine_slots=4),
    3: dict(roof_count=10, lamp_count=3, half_width=.42, sway=.07, lift=1.16, span_ms=6300, momentum=.50, routine_slots=4),
    4: dict(roof_count=13, lamp_count=4, half_width=.39, sway=.10, lift=1.20, span_ms=5500, momentum=.75, routine_slots=4),
    5: dict(roof_count=16, lamp_count=5, half_width=.36, sway=.13, lift=1.25, span_ms=4700, momentum=1., routine_slots=4),
}
DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))
# Primitive companion matrices. Every nonzero pair has order p*p-1;
# even D5's 63,000 ramps cannot repeat in a 600-second shift. The current
# FROM/TO pair is the whole controller state, rather than a hidden noise seed.
LIFT_CONTROLLERS = {1: (211, 1, 4), 2: (223, 2, 9), 3: (233, 1, 5),
                    4: (241, 1, 14), 5: (251, 1, 7)}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or task.get("metadata", {}).get("control_condition"))
    level = (condition or {}).get("difficulty", 5)
    if type(level) is not int or level not in PROFILES:
        raise ValueError("difficulty must be 1 through 5")
    profile = copy.deepcopy(PROFILES[level])
    supplied = (condition or {}).get("difficulty_parameters", {})
    if supplied and supplied != profile:
        raise ValueError("difficulty parameters must match the versioned profile")
    if condition is None:
        condition = dict(difficulty=5, interaction="full", real_time="live", difficulty_parameters=profile)
    if condition.get("interaction") not in ("full", "simplified"):
        raise ValueError("invalid interaction")
    # A declared ~ suffix varies actuator initialization while preserving the
    # root's map/lamps/phases. It supplies generated, rather than injected,
    # matched-motion cases for the exact control analysis.
    layout_seed = str(seed).split('~', 1)[0]
    rng = random.Random(hashlib.sha256(f"{layout_seed}|{MECHANIC_ID}|{SEED_REVISION}".encode()).digest())
    # A three-edge spine is present even at D1; later branches introduce route
    # choice and backtracking rather than independent repetitions of a round.
    cells = [(0, 0), (1, 0), (2, 0), (3, 0)]
    while len(cells) < profile["roof_count"]:
        options = sorted({(x+dx, y+dy) for x, y in cells for dx, dy in DIRS
                          if 0 <= x+dx <= 4 and 0 <= y+dy <= 4 and (x+dx, y+dy) not in cells})
        cells.append(rng.choice(options))
    # Quarter-turning the whole connected geometry alters spatial decisions.
    rotation = rng.randrange(4)
    def rotate(x, y):
        for _ in range(rotation):
            x, y = -y, x
        return x, y
    roofs = []
    for index, cell in enumerate(cells):
        x, y = rotate(*cell)
        roofs.append(dict(id=f"roof-{index}", cell=[x, y], base_z=3+rng.choice((-.35, 0, .35)),
                          half=profile["half_width"], motion_seed=rng.getrandbits(32),
                          phase_ms=(rng.randrange(profile["span_ms"])//10)*10, lamp=False))
    by_cell = {tuple(r["cell"]): r["id"] for r in roofs}
    distances, queue = {roofs[0]["id"]: 0}, [roofs[0]]
    while queue:
        r = queue.pop(0)
        for dx, dy in DIRS:
            neighbor = by_cell.get((r["cell"][0]+dx, r["cell"][1]+dy))
            if neighbor is not None and neighbor not in distances:
                distances[neighbor] = distances[r["id"]]+1
                queue.append(next(a for a in roofs if a["id"] == neighbor))
    distant = sorted(roofs[1:], key=lambda r: (-distances[r["id"]], r["id"]))
    chosen = [distant[0]]
    rng.shuffle(distant)
    for r in distant:
        if r not in chosen:
            chosen.append(r)
        if len(chosen) == profile["lamp_count"]:
            break
    chosen = chosen[:profile["lamp_count"]]
    for r in chosen:
        r["lamp"] = True
    assert max(distances[r["id"]] for r in chosen) >= 3
    modulus, coefficient, previous_coefficient = LIFT_CONTROLLERS[level]
    for r in roofs:
        entropy = hashlib.sha256(f"{seed}|{r['id']}|visible-lift-v1".encode()).digest()
        first = int.from_bytes(entropy[:8], 'big') % modulus
        second = int.from_bytes(entropy[8:16], 'big') % modulus
        r['lift_pair'] = [first, second] if first or second else [0, 1]
    physics = dict(tick_ms=10, gravity=5.2, nominal_flight_s=1., robot_radius=.065,
                   roof_thickness=.10, maximum_flight_ms=2000, command_ms=300,
                   lamp_ms=500, height_step=1., max_task_ms=600000,
                   sway=profile["sway"], lift=profile["lift"], span_ms=profile["span_ms"],
                   momentum=profile["momentum"], motion_quantum=.01,
                   collision_revision="swept-deck-v1", motion_revision="visible-lift-v1",
                   lift_modulus=modulus, lift_coefficient=coefficient,
                   lift_previous_coefficient=previous_coefficient)
    geometry = dict(roofs=roofs, start_roof="roof-0", start_heading=rotation, physics=physics,
                    routine_slots=profile["routine_slots"])
    digest = hashlib.sha256(json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task["id"],
                  challenge_id=hashlib.sha256(f"{seed}|{digest}|{REVISION}".encode()).hexdigest()[:16],
                  physics_revision=REVISION, world=geometry, world_digest=digest,
                  control_condition=condition, single_attempt=True,
                  source_anchors=["TAE-280"],
                  prompt="Light every blue roof lantern. Dispatch your icon routines while the roofs keep moving.",
                  submit_label="CERTIFY SHIFT", generator=dict(name=REVISION, variant_count=2**32),
                  asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json")
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
