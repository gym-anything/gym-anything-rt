"""Source-derived moving braid; no interaction-dependent random draws."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "ribbon_switchboard_v3_nonrealtime"
DONOR_MECHANIC_ID = "ribbon_switchboard_v3"
REVISION = "moving-braid-local-light-v3"
ACTION_STEP_MS = 400
# Preserve the mechanically forked V2 world's random stream. Inspection adds
# no random draws and changes neither geometry nor the five servo profiles.
WORLD_REVISION = "moving-braid-servo-v2"
PROFILES = {
    1: dict(heads=1, ribbons=2, columns=4, amplitude=30, wind_span_ms=6200,
            tolerance=18, burn_ms=1600, travel_ms=28000, servo_tau_ms=110),
    2: dict(heads=1, ribbons=3, columns=5, amplitude=32, wind_span_ms=5200,
            tolerance=16, burn_ms=1400, travel_ms=28000, servo_tau_ms=140),
    3: dict(heads=2, ribbons=3, columns=5, amplitude=34, wind_span_ms=4400,
            tolerance=14, burn_ms=1300, travel_ms=30000, servo_tau_ms=170),
    4: dict(heads=2, ribbons=4, columns=6, amplitude=36, wind_span_ms=3600,
            tolerance=12, burn_ms=1200, travel_ms=32000, servo_tau_ms=210),
    5: dict(heads=3, ribbons=5, columns=7, amplitude=38, wind_span_ms=3000,
            tolerance=10, burn_ms=1100, travel_ms=34000, servo_tau_ms=250),
}
COLORS = ["#f1b868", "#79cfc9", "#b4a4e4", "#ed9398", "#aac685"]


def generate(task, seed):
    condition = task.get("_control_condition")
    level = int((condition or {}).get("difficulty", 5))
    if level not in PROFILES:
        raise ValueError("difficulty must be 1..5")
    p = dict(PROFILES[level])
    if condition and condition.get("difficulty_parameters") != p:
        raise ValueError("profile does not match moving-braid revision")
    if condition and condition.get("interaction") not in ("full", "simplified"):
        raise ValueError("invalid interaction")
    # Keep corresponding seeds on the frozen V3 donor's world stream. The
    # counterpart changes only the timing rule and public namespace.
    rng = random.Random(hashlib.sha256(f"{seed}|{DONOR_MECHANIC_ID}|d{level}|{WORLD_REVISION}".encode()).digest())
    lanes = []
    for i in range(p["heads"]):
        n = p["ribbons"]
        # Every target traverses both upper and lower parts of its lane. This
        # changes the control problem, rather than relying on a deadline.
        orders = []
        for col in range(p["columns"]):
            order = list(range(n))
            rng.shuffle(order)
            orders.append(order)
        target = rng.randrange(n)
        orders[1].remove(target); orders[1].insert(0, target)
        orders[2].remove(target); orders[2].append(target)
        ribbons = []
        for j in range(n):
            knots = [-24 + 48 * orders[c].index(j) / (n-1) for c in range(p["columns"])]
            ribbons.append(dict(id=j, color=COLORS[j], knots=knots,
                wind_seed=rng.getrandbits(32), phase_ms=rng.randrange(0, p["wind_span_ms"]),
                depth=rng.random()))
        lanes.append(dict(id=i, target=target, ribbons=ribbons))
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
        task_id=task["id"], challenge_id=hashlib.sha256(f"{seed}|{task['id']}|{REVISION}".encode()).hexdigest()[:16],
        revision=REVISION, lanes=lanes, parameters=p, step_ms=20,
        action_step_ms=ACTION_STEP_MS,
        stage=dict(width=1100, height=450, lane_height=150, rail_x=44, start_x=140, end_x=1040),
        inspection=dict(radius=100, persistent=True),
        prompt="Illuminate the unlit weave to discover each source ribbon's path and crossings. Inspected spans stay lit. Energize the loom, then keep every contact head inside its source ribbon's glowing band until it reaches the terminal. Idle time holds the loom; each completed rail adjustment or newly revealing inspection advances one fixed 0.4-second slice. The servos have inertia. A full HEAT bar burns the loom permanently.",
        asset_manifest="shared_runtime/assets/provenance/ribbon_switchboard_v3_v0.json",
        generator=dict(name=REVISION, variant_count=10**24))
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
