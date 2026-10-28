"""Drifting ceramic crossing with inspectable, batch-specific kiln samples."""
from __future__ import annotations

import copy
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import random

MECHANIC_ID = "crackglaze_crossing_v3_nonrealtime"
SOURCE_MECHANIC_ID = "crackglaze_crossing_v3"
ACTION_SETTLE_MS = 600
SEARCH_STEP_MS = 100
PROFILES = {
    1: dict(columns=4, spurs=1, spur_depth=1, drift_px=18, reach_px=113, span_ms=6500, fuse_ms=[65000, 90000], shadow_count=0, tile_px=54, crossing_ms=500),
    2: dict(columns=5, spurs=2, spur_depth=1, drift_px=21, reach_px=111, span_ms=5900, fuse_ms=[55000, 75000, 90000], shadow_count=0, tile_px=54, crossing_ms=500),
    3: dict(columns=6, spurs=2, spur_depth=2, drift_px=24, reach_px=108, span_ms=5200, fuse_ms=[42000, 60000, 80000], shadow_count=2, tile_px=48, crossing_ms=500),
    4: dict(columns=7, spurs=3, spur_depth=2, drift_px=26, reach_px=105, span_ms=4600, fuse_ms=[34000, 48000, 68000, 85000], shadow_count=3, tile_px=44, crossing_ms=500),
    5: dict(columns=8, spurs=4, spur_depth=2, drift_px=28, reach_px=102, span_ms=4000, fuse_ms=[28000, 38000, 50000, 70000], shadow_count=5, tile_px=44, crossing_ms=500),
}
GLAZES = [dict(name="Celadon", color="#6fb59e", mark="I"), dict(name="Cobalt", color="#496fa9", mark="II"),
          dict(name="Ochre", color="#d39a54", mark="III"), dict(name="Mulberry", color="#ac6076", mark="IV")]


@lru_cache(maxsize=1)
def _grader():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("ceramic_certificate_replay", root / "shared_runtime/server/incubator_graders/crackglaze_crossing_v3_nonrealtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def certificate(world, route, start_ms=0, margin=2, settle_ms=ACTION_SETTLE_MS, lit_at=None):
    """Privileged certificate for deterministic, action-triggered settlement."""
    grader = _grader()
    t = start_ms
    lit = dict(lit_at or {})
    events = []
    by_id = {c["id"]: c for c in world["cells"]}
    for origin, destination in zip(route, route[1:]):
        latest = min(t + 30000, 290000)
        if origin in lit:
            latest = min(latest, lit[origin] + by_id[origin]["fuse_ms"] - 800)
        found = False
        while t <= latest:
            if (not grader.crossing_failure(world, origin, destination, t, lit)
                and max(grader.span_distance(world, origin, destination, t + dt) for dt in (0, 250, 500)) <= world["parameters"]["reach_px"] - margin):
                found = True
                break
            t += SEARCH_STEP_MS
        if not found:
            return None
        lit.setdefault(origin, t)
        events.append(dict(sequence=len(events)+1, kind="cross", t_ms=t, **{"from": origin, "to": destination}))
        t += world["parameters"]["crossing_ms"] + settle_ms
    return dict(route=route, events=events, completion_ms=t, planning="privileged future motion; feasibility only")


def generate(task, seed):
    raw_condition = task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition")
    level = int((raw_condition or {}).get("difficulty", 5))
    mode = (raw_condition or {}).get("interaction", "full")
    if level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("unsupported ceramic condition")
    p = copy.deepcopy(PROFILES[level])
    if raw_condition and raw_condition.get("difficulty_parameters") != p:
        raise ValueError("ceramic profile parameters differ from controls")
    condition = copy.deepcopy(raw_condition or dict(difficulty=level, interaction=mode, real_time="live", difficulty_parameters=p))
    rng = random.Random(hashlib.sha256(f"{SOURCE_MECHANIC_ID}|{seed}|{level}".encode()).digest())
    columns = p["columns"]
    mirror = rng.choice((False, True))
    spur_columns = sorted(rng.sample(list(range(1, columns-1)), p["spurs"]))
    points = {(2, c) for c in range(columns)}
    spurs = {}
    for index, c in enumerate(spur_columns):
        side = -1 if (index + rng.randrange(2)) % 2 else 1
        # Prevent neighbouring long branches overlapping. They remain distinct
        # ceramic objects; graph edges are exactly orthogonal grid neighbours.
        spurs[c] = [(2+side*d, c) for d in range(1, p["spur_depth"]+1)]
        points.update(spurs[c])
    def cell_id(point):
        r,c=point
        return f"r{r}c{columns-1-c if mirror else c}"
    route = [cell_id((2,0))]
    for c in range(1, columns):
        route.append(cell_id((2,c)))
        if c in spurs:
            branch = spurs[c]
            route.extend(cell_id(q) for q in branch)
            route.extend(cell_id(q) for q in reversed(branch[:-1]))
            route.append(cell_id((2,c)))
    lanterns = {cell_id(branch[-1]) for branch in spurs.values()}
    lanterns.update(cell_id((2,c)) for c in rng.sample(list(range(1,columns-1)), min(2,level)))
    shadow_ids = set(rng.sample([cell_id(q) for q in points if cell_id(q) not in (route[0],route[-1])], p["shadow_count"]))
    cells = []
    for r,c in sorted(points):
        visible_c = columns-1-c if mirror else c
        g = rng.randrange(len(p["fuse_ms"]))
        cells.append(dict(id=cell_id((r,c)), row=r, column=visible_c,
            center=[70 + visible_c*104, 54+r*104], glaze=g, fuse_ms=p["fuse_ms"][g],
            lantern=cell_id((r,c)) in lanterns, shadow=cell_id((r,c)) in shadow_ids,
            motion_seed=rng.getrandbits(32), phase_ms=rng.randrange(p["span_ms"]),
            span_ms=p["span_ms"]+rng.randrange(0,900)))
    neighbors = {a["id"]: [b["id"] for b in cells if abs(a["row"]-b["row"])+abs(a["column"]-b["column"])==1] for a in cells}
    # Permute only the visual glaze identities with a separate random stream.
    # Every cell keeps its V2 fuse, geometry and future motion. The sample rack
    # is displayed in mark order, so its position cannot disclose fuse rank.
    palette = copy.deepcopy(GLAZES[:len(p["fuse_ms"])])
    sample_rng = random.Random(hashlib.sha256(f"{SOURCE_MECHANIC_ID}|{seed}|{level}|kiln-samples".encode()).digest())
    sample_rng.shuffle(palette)
    world = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, revision="drifting-rafts-exploration-v3", task_id=task["id"],
        challenge_id=hashlib.sha256(f"{seed}|{level}|drifting-rafts-exploration-v3".encode()).hexdigest()[:16],
        control_condition=condition, parameters=p, stage=dict(width=900,height=560),
        cells=cells, neighbors=neighbors, start_id=route[0], exit_id=route[-1], lantern_ids=sorted(lanterns),
        glazes=[dict(**palette[i],fuse_ms=fuse) for i,fuse in enumerate(p["fuse_ms"])],
        prompt="Gather every lantern, then reach the door. Leaving lights a nonrenewing fuse. Turn kiln samples to inspect this batch's glaze lifetimes; deliberate crossings settle the raft layout before the next choice.",
        asset_manifest="shared_runtime/assets/provenance/crackglaze_crossing_v3_v0.json",
        generator=dict(name="ceramic_drift_collect_and_return",variant_count=10**18,variant_count_kind="seeded branching floor, glaze assignment and nonrepeating smooth drift"), single_attempt=True)
    # Reject genuinely infeasible generated motion, without special-casing
    # evaluation seeds or rendering a solver route. The independent grader
    # still recomputes all crossing geometry and collapse decisions.
    proof = None
    for attempt in range(80):
        if attempt:
            for cell in cells:
                cell["motion_seed"] = rng.getrandbits(32)
        proof = certificate(world,route)
        if proof:
            break
    if proof is None:
        raise ValueError("could not certify a safely reachable ceramic instance")
    truth=copy.deepcopy(world)
    truth.update(seed=str(seed),certificate=proof,source_anchors=["IND-021","VGE-250","VGE-489"])
    return world,truth
