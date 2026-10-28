"""Original, source-derived marble cascade; interaction never seeds the world."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import random

MECHANIC_ID = "flip_gate_cascade_v3"
REVISION = "cascade-inspection-3"
PROFILES = {
    1: dict(top_chutes=2, rows=2, marble_count=4, release_gap_ms=4300,
            rail_ms=1700, pocket_width=220, pockets=1, wind_acceleration=200, wind_span_ms=3200),
    2: dict(top_chutes=3, rows=2, marble_count=5, release_gap_ms=3900,
            rail_ms=1600, pocket_width=185, pockets=2, wind_acceleration=200, wind_span_ms=2800),
    3: dict(top_chutes=3, rows=3, marble_count=6, release_gap_ms=3500,
            rail_ms=1500, pocket_width=155, pockets=2, wind_acceleration=200, wind_span_ms=2400),
    4: dict(top_chutes=4, rows=3, marble_count=7, release_gap_ms=3100,
            rail_ms=1400, pocket_width=130, pockets=2, wind_acceleration=200, wind_span_ms=2100),
    5: dict(top_chutes=4, rows=4, marble_count=8, release_gap_ms=2800,
            rail_ms=1300, pocket_width=105, pockets=2, wind_acceleration=200, wind_span_ms=1800),
}


def _first_episode_failure(task):
    """Keep this task's first server-recorded rejection through regeneration.

    The shared server archives committed submissions before generating its
    next state. A refresh alone, another task's journal entry, or a browser
    claim about policy is not evidence that this episode failed.
    """
    path = Path(os.environ.get("GYM_ANYTHING_RT_STATE_DIR", "/tmp/gym_anything_rt")) / "attempts.jsonl"
    try:
        with path.open(encoding="utf-8") as journal:
            for line in journal:
                if not line.strip():
                    continue
                attempt = json.loads(line)
                if not isinstance(attempt, dict):
                    raise ValueError("invalid cascade attempt journal")
                if (attempt.get("mechanic_id") != MECHANIC_ID
                        or attempt.get("task_id") != task["id"]
                        or attempt.get("physics_revision") != REVISION):
                    continue
                decision = attempt.get("server_grade") or {}
                if decision.get("graded") is True and decision.get("passed") is False:
                    return dict(task_id=task["id"], challenge_id=attempt.get("challenge_id"),
                                feedback=str(decision.get("feedback") or "Rejected committed cascade"),
                                failed=attempt.get("failed", ""), final_t_ms=attempt.get("final_t_ms"),
                                attempt_sha256=hashlib.sha256(line.encode()).hexdigest())
    except FileNotFoundError:
        pass
    return None


def generate(task, seed):
    condition = task.get("_control_condition")
    level = int((condition or {}).get("difficulty", 5))
    mode = (condition or {}).get("interaction", "full")
    if level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("unsupported cascade condition")
    params = {**PROFILES[level], **(condition or {}).get("difficulty_parameters", {})}
    # Profiles are a supported contract, not arbitrary unvalidated physics knobs.
    if params != PROFILES[level]:
        raise ValueError("cascade profile parameters must match the declared level")
    # Keep the renamed V2 copy's gates, feed, wind and geometry for a fixed
    # seed. A separate draw adds only the concealed inlet plumbing.
    rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|cascade-latch-2".encode()).digest())
    top, rows = params["top_chutes"], params["rows"]
    spacing = 720 / (top + rows - 1)
    gates, offsets = [], []
    for row in range(rows):
        offsets.append(len(gates))
        for column in range(top + row):
            gates.append(dict(id=len(gates), row=row, column=column,
                              x=480 + (column - (top + row - 1) / 2) * spacing,
                              y=90 + row * 160 / (rows - 1)))
    release = 1200
    marbles = []
    # Alternating extremes prevent a single central ambush from dominating.
    chutes = [0, top - 1] + [rng.randrange(top) for _ in range(params["marble_count"] - 2)]
    for index, chute in enumerate(chutes):
        kind = rng.randrange(params["pockets"])
        marbles.append(dict(id=index, chute=chute, release_ms=release, kind=kind,
                            radius=10, wind_scale=1.0 if kind == 0 else .78))
        release += params["release_gap_ms"] + rng.randrange(-12, 13) * 10
    world = dict(**params, width=960, height=570, gates=gates, offsets=offsets,
                 initial_gates=[rng.randrange(2) for _ in gates], spacing=spacing,
                 marbles=marbles, wind_seed=rng.getrandbits(32), gravity=48,
                 initial_vy=46, exit_vx=65, tick_ms=10, rim_y=520, capture_top=380,
                 wall_left=24, wall_right=936, basket_speed=600,
                 basket_acceleration=2400, divider_width=14, run_limit_ms=80000)
    inlet_rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|inlet-manifold".encode()).digest())
    world["entry_columns"] = inlet_rng.sample(range(top), top)
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  physics_revision=REVISION, task_id=task["id"],
                  challenge_id=hashlib.sha256(f"{seed}|{task['id']}|{REVISION}".encode()).hexdigest()[:16],
                  prompt="Move the pointer to inspect the fall through the smoked chamber. The broad light stays where placed. Inspect the lettered inlet mouths to reveal their concealed connections to the numbered gates. Learned connections remain on the cabinet. Anticipate the route, steer the matching pocket around each falling marble, and latch while the whole marble is inside its outline. Empty or misaligned latches and escaped marbles end the attempt. Gates flip and crosswinds change the fall.",
                  world=world, single_attempt=True,
                  asset_manifest="shared_runtime/assets/provenance/flip_gate_cascade_v3_v0.json",
                  generator=dict(name=REVISION, variant_count=2**32))
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
    failure = _first_episode_failure(task)
    if failure:
        public["episode_failure"] = failure
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
