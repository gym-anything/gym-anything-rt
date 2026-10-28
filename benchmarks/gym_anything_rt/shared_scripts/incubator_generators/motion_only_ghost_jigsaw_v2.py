"""Original procedural motion-contrast fragments in a continuously drifting loom."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "motion_only_ghost_jigsaw_v2"
REVISION = "drifting-loom-v3"
PROFILES = {
    1: dict(rows=2, columns=2, drift_px=32, drift_span_ms=2400, angle_amplitude=18,
            position_tolerance=20, angle_tolerance=16, spring=30, damping=11,
            max_speed=620, current_force=12, initial_turns=[0]),
    2: dict(rows=2, columns=3, drift_px=32, drift_span_ms=2300, angle_amplitude=26,
            position_tolerance=20, angle_tolerance=16, spring=27, damping=10,
            max_speed=580, current_force=20, initial_turns=[-30, 0, 30]),
    3: dict(rows=3, columns=3, drift_px=32, drift_span_ms=2200, angle_amplitude=34,
            position_tolerance=20, angle_tolerance=16, spring=24, damping=9,
            max_speed=540, current_force=30, initial_turns=[-45, 0, 45]),
    4: dict(rows=3, columns=3, drift_px=33, drift_span_ms=2000, angle_amplitude=48,
            position_tolerance=17, angle_tolerance=13, spring=21, damping=8,
            max_speed=500, current_force=42, initial_turns=[-60, -30, 0, 30, 60]),
    5: dict(rows=3, columns=3, drift_px=34, drift_span_ms=1800, angle_amplitude=65,
            position_tolerance=14, angle_tolerance=10, spring=18, damping=7,
            max_speed=460, current_force=55, initial_turns=[-90, -60, -30, 0, 30, 60, 90]),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or {})
    level = int(condition.get("difficulty", 5))
    mode = condition.get("interaction", "full")
    if level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("Ghost Jigsaw V2 requires D1–D5 and full/simplified interaction")
    profile = copy.deepcopy(PROFILES[level])
    supplied = condition.get("difficulty_parameters") or profile
    if supplied != profile:
        raise ValueError("difficulty parameters differ from the frozen loom profile")
    condition.update(difficulty=level, interaction=mode, difficulty_parameters=profile)
    rng = random.Random(hashlib.sha256(f"{MECHANIC_ID}|{REVISION}|{seed}|{level}".encode()).digest())
    rows, columns = profile["rows"], profile["columns"]
    count = rows * columns
    # Disjoint 184px cells leave every rotated 80px fragment and its 34px drift
    # inside its cell; slot selection is never stolen by a neighbour.
    slots = [dict(id=f"socket-{i}", source_index=i,
                  base=[490 + (i % columns) * 184, 92 + (i // columns) * 184],
                  motion_seed=rng.getrandbits(32)) for i in range(count)]
    pieces = [dict(id="shard-" + hashlib.sha256(f"{seed}|{level}|{i}".encode()).hexdigest()[:10],
                   source_index=i, noise_seed=rng.getrandbits(32),
                   angle=rng.choice(profile["initial_turns"])) for i in range(count)]
    rng.shuffle(pieces)
    for i, piece in enumerate(pieces):
        piece["home"] = [66 + i % 3 * 114, 92 + i // 3 * 184]
    # Original, connected linework crosses crop boundaries. Unique local ring
    # placements prevent blank or indistinguishable crops at every difficulty.
    glyphs = []
    for i in range(count):
        x, y = (i % columns) * 100, (i // columns) * 100
        glyphs.append(dict(kind="ring", x=x+rng.randint(28, 72), y=y+rng.randint(27, 73),
                           radius=rng.randint(13, 25), width=rng.randint(4, 7)))
        glyphs.append(dict(kind="segment", a=[x+10, y+rng.randint(15, 85)],
                          b=[x+90, y+rng.randint(15, 85)], width=5))
    for row in range(rows):
        vertices = [[-10, row*100+50]]
        vertices += [[col*100+50, row*100+rng.randint(18, 82)] for col in range(columns)]
        vertices.append([columns*100+10, row*100+50])
        glyphs += [dict(kind="segment", a=a, b=b, width=4) for a, b in zip(vertices, vertices[1:])]
    task_id = task["id"]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task_id, challenge_id=hashlib.sha256(f"{seed}|{level}|{REVISION}|{task_id}".encode()).hexdigest()[:16],
                  revision=REVISION, prompt=task.get("natural_language", "Restore the moving ghost picture."),
                  control_condition=condition, profile=profile, stage=dict(width=970, height=560),
                  piece_size=80, slots=slots, pieces=pieces, glyphs=glyphs,
                  current_seed=rng.getrandbits(32), noise_speed=42, tick_ms=10,
                  rotation_speed=100, max_time_ms=180000, max_events=18000,
                  asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18,
                                 variant_count_kind="seeded linework, shuffle, poses, and nonrepeating smooth drift"),
                  render_boundary="Procedural masks and motion seeds ship for honest rendering; browser internals are inspectable and forbidden to screenshot-only agents.")
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), expected_positions={p["id"]:p["source_index"] for p in pieces})
    return public, truth
