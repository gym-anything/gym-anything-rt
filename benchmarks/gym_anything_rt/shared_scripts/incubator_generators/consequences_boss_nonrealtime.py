"""Source-derived covenant combat with action-triggered decision snapshots."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "consequences_boss_nonrealtime"
# Keep corresponding seeds on the evaluated V2 geometry.  The namespace is
# changed only in the public task identity; it must not change the puzzle.
SEED_MECHANIC_ID = "consequences_boss_v2"
REVISION = "covenant-echoes-v1"
DECISION_STEP_MS = 700
PREVIEW_OFFSET_MS = 1200
PROFILES = {
    1: dict(witness_count=2, echo_count=4, lifetime_ms=14000, spawn_gap_ms=15000, radius=48, drift=170, bend_ms=4200, protected_count=0),
    2: dict(witness_count=3, echo_count=6, lifetime_ms=13000, spawn_gap_ms=6500, radius=45, drift=210, bend_ms=3800, protected_count=1),
    3: dict(witness_count=4, echo_count=8, lifetime_ms=12000, spawn_gap_ms=4000, radius=42, drift=250, bend_ms=3400, protected_count=2),
    4: dict(witness_count=5, echo_count=10, lifetime_ms=11000, spawn_gap_ms=2900, radius=39, drift=280, bend_ms=2900, protected_count=3),
    5: dict(witness_count=6, echo_count=12, lifetime_ms=10000, spawn_gap_ms=2100, radius=36, drift=300, bend_ms=2500, protected_count=4),
}
GLYPHS = ["✦", "◇", "☘", "☀", "△", "☾"]
COLORS = ["#f9bf68", "#94d9e7", "#d4a7f2", "#ed9ca8", "#a9d795", "#e9d68a"]


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    parameters = dict(PROFILES[level])
    parameters.update((condition or {}).get("difficulty_parameters") or {})
    if parameters != PROFILES[level]:
        raise ValueError("unsupported covenant profile")
    rng = random.Random(hashlib.sha256(f"{seed}|{SEED_MECHANIC_ID}|{level}|{REVISION}".encode()).digest())
    n = parameters["witness_count"]
    symbols = list(zip(GLYPHS, COLORS))
    rng.shuffle(symbols)
    witnesses = [dict(id=f"witness-{i}", glyph=g, color=c, x=260+i*720/max(1,n-1), y=460)
                 for i,(g,c) in enumerate(symbols[:n])]
    order = list(range(n))*2
    rng.shuffle(order)
    echoes = []
    spawn = 1200
    for i, witness in enumerate(order[:parameters["echo_count"]]):
        lifetime = parameters["lifetime_ms"] + rng.randint(-350, 350)
        echoes.append(dict(id=f"echo-{i}", witness_id=witnesses[witness]["id"],
            spawn_ms=spawn, lifetime_ms=lifetime, radius=parameters["radius"],
            motion_seed=rng.getrandbits(32), bend_ms=parameters["bend_ms"],
            drift=parameters["drift"], protected=False))
        spawn += parameters["spawn_gap_ms"] + rng.randint(-220, 220)
    # Independent white-ring wisps share the same motion law and real hit area.
    # They render beneath judgments so a visibly exposed judgment stays hittable.
    wisps = [dict(id=f"wisp-{i}", witness_id=witnesses[i % n]["id"], spawn_ms=0,
        lifetime_ms=200000, radius=parameters["radius"], motion_seed=rng.getrandbits(32),
        bend_ms=parameters["bend_ms"]*1.15, drift=parameters["drift"], protected=True,
        y_phase=rng.uniform(0,6.28)) for i in range(parameters["protected_count"])]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
        revision=REVISION, task_id=task["id"],
        challenge_id=hashlib.sha256(f"{seed}|{SEED_MECHANIC_ID}|d{level}|{REVISION}".encode()).hexdigest()[:16],
        prompt="Choose each witness's covenant. Keep it when judgment returns.",
        asset_manifest="shared_runtime/assets/provenance/consequences_boss_v2_v0.json",
        generator=dict(name=REVISION, variant_count=2**64),
        stage=dict(width=1100,height=500), witnesses=witnesses, echoes=echoes, wisps=wisps,
        seals=[dict(id="mercy", x=80,y=100,radius=32,glyph="◯"),
               dict(id="rebuke",x=80,y=235,radius=32,glyph="↑")],
        parameters=parameters, forecast_ms=1200, trail_ms=600,
        max_run_ms=120000, single_attempt=True,
        nonrealtime=dict(action_triggered=True, decision_step_ms=DECISION_STEP_MS,
                         preview_offset_ms=PREVIEW_OFFSET_MS,
                         waiting_preserves_snapshot=True))
    if condition:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
