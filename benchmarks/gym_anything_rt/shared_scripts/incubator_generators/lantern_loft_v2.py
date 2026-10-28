"""Original sliding stairwalks inspired by PHY-059; no source artwork or layouts."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "lantern_loft_v2"
REVISION = "drifting-stairwalks-v1"
PROFILES = {
    1: dict(moving_decks=2, port_width=104, gust_force=190, gust_span_ms=4200, coupling=0.0, crossing_ms=2800, stair_changes=0, false_ports=False),
    2: dict(moving_decks=2, port_width=94, gust_force=225, gust_span_ms=3800, coupling=0.0, crossing_ms=2700, stair_changes=1, false_ports=False),
    3: dict(moving_decks=3, port_width=84, gust_force=255, gust_span_ms=3400, coupling=0.0, crossing_ms=2600, stair_changes=2, false_ports=True),
    4: dict(moving_decks=3, port_width=76, gust_force=285, gust_span_ms=3000, coupling=0.18, crossing_ms=2500, stair_changes=3, false_ports=True),
    5: dict(moving_decks=4, port_width=68, gust_force=315, gust_span_ms=2600, coupling=0.28, crossing_ms=2400, stair_changes=4, false_ports=True),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    level = (condition or {}).get("difficulty", 5)
    if type(level) is not int or level not in PROFILES:
        raise ValueError("Lantern Loft V2 difficulty must be 1 through 5")
    mode = (condition or {}).get("interaction", "full")
    if mode not in ("full", "simplified"):
        raise ValueError("unsupported interaction")
    params = copy.deepcopy(PROFILES[level])
    overrides = (condition or {}).get("difficulty_parameters", {})
    if overrides and overrides != params:
        raise ValueError("profile differs from the implemented Lantern Loft V2 contract")
    rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}".encode()).digest())
    n = params["moving_decks"]
    heights = [0]
    for i in range(n):
        last = heights[-1]
        heights.append(rng.choice([h for h in (last-1, last+1) if 0 <= h <= 2]) if i < params["stair_changes"] else last)
    decks = []
    for i in range(n+2):
        incoming = rng.choice((-1, 1))
        # Every movable piece changes the route as well as carrying the pawn.
        outgoing = -incoming
        h_in = heights[max(0, i-1)]
        h_out = heights[min(i, n)]
        moving = 0 < i < n+1
        decks.append(dict(id=f"deck-{i}", name=("DOORSTEP" if i == 0 else "BEACON" if i == n+1 else f"LOFT {chr(64+i)}"),
            moving=moving, base_x=0, initial_x=rng.randint(-80, 80) if moving else 0,
            initial_v=rng.uniform(-18, 18) if moving else 0,
            in_x=incoming*68, out_x=outgoing*68, in_height=h_in, out_height=h_out,
            gust_seed=rng.getrandbits(32), y=i*130))
    world = dict(revision=REVISION, parameters=params, decks=decks,
        body_half_width=140, body_half_depth=40, neck_end=65, radius=8,
        rail_limit=168, motor_force=460, spring=1.7, damping=2.2, deck_speed=125,
        walk_acceleration=1000, walk_damping=7, walk_speed=150, tick_ms=20,
        max_ms=180000)
    task_id = task.get("id", f"{MECHANIC_ID}_seed_0001@0.1")
    challenge = hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}|d{level}".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
        task_id=task_id, challenge_id=challenge, world=world, single_attempt=True,
        prompt="Carry the lantern across drifting stairwalks to the beacon. Shift the lofts and steer through the moving connections. A fall or END / CERTIFY before delivery ends the episode; later attempts cannot earn a pass. Inspection and recoverable control feedback remain available.",
        asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json",
        generator=dict(name=REVISION, variant_count=2**64, variant_count_kind="seeded geometry, stair elevations, initial motion and independent nonperiodic gusts"))
    if condition is not None:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
