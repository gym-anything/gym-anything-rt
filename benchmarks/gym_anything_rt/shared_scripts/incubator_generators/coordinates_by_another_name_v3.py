"""Symbolic chart with addressed sonar discovery and the unchanged V2 drift."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random

MECHANIC_ID = "coordinates_by_another_name_v3"
REVISION = "drifting-sonar-compartments-v1"
PROFILES = {
    1: dict(rows=4, columns=7, hostile=2, protected=0, compartments=2, radius=29,
            displacement=65, span_ms=3600, flight_ms=1400, blast_radius=18,
            reverse=False, holes=0, echo_ms=10000),
    2: dict(rows=5, columns=8, hostile=2, protected=1, compartments=2, radius=26,
            displacement=85, span_ms=3300, flight_ms=1500, blast_radius=16,
            reverse=False, holes=0, echo_ms=9000),
    3: dict(rows=5, columns=8, hostile=3, protected=1, compartments=2, radius=23,
            displacement=100, span_ms=3000, flight_ms=1600, blast_radius=14,
            reverse=True, holes=0, echo_ms=8000),
    4: dict(rows=6, columns=9, hostile=3, protected=2, compartments=3, radius=21,
            displacement=115, span_ms=2800, flight_ms=1700, blast_radius=13,
            reverse=True, holes=2, echo_ms=7500),
    5: dict(rows=6, columns=10, hostile=4, protected=2, compartments=3, radius=20,
            displacement=130, span_ms=2600, flight_ms=1800, blast_radius=12,
            reverse=True, holes=4, echo_ms=7000),
}


def episode_failure():
    directory = os.environ.get("GYM_ANYTHING_RT_STATE_DIR")
    if directory:
        try:
            if any(line.strip() for line in (Path(directory) / "attempts.jsonl").read_text().splitlines()):
                return True
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError):
            return True
    return False


def _reflect(value, lo, hi):
    value = (value - lo) % (2 * (hi - lo))
    return lo + (value if value <= hi - lo else 2 * (hi - lo) - value)


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or task.get("metadata", {}).get("control_condition"))
    level = (condition or {}).get("difficulty", 5)
    mode = (condition or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("unsupported symbolic sonar condition")
    p = copy.deepcopy(PROFILES[level])
    if condition and condition.get("difficulty_parameters") != p:
        raise ValueError("profile differs from controls.json")
    condition = condition or dict(difficulty=level, interaction=mode, real_time="live", difficulty_parameters=p)
    prefix = str(seed).split("::", 1)[0]
    rng = random.Random(hashlib.sha256(f"{prefix}|{MECHANIC_ID}|{REVISION}".encode()).digest())
    bands = rng.sample(range(1, 10), p["rows"])
    holes = set(rng.sample([(r, c) for r in range(p["rows"]) for c in range(p["columns"])], p["holes"]))
    cells, runs = [], []
    for row, band in enumerate(bands):
        cuts = sorted(rng.sample(range(2, p["columns"] - 1), 2))
        blocks = rng.sample(list("ABC"), 3)
        for start, end, block in zip([0] + cuts, cuts + [p["columns"]], blocks):
            reverse = bool(p["reverse"] and rng.randrange(2))
            runs.append(dict(row=row, band=band, block=block, start=start, width=end-start, reverse=reverse))
            for col in range(start, end):
                if (row, col) not in holes:
                    cells.append(dict(row=row, column=col, band=band, block=block,
                                      count=end-col if reverse else col-start+1,
                                      x=48+(col+.5)*768/p["columns"],
                                      y=24+(row+.5)*312/p["rows"]))
    if p["reverse"] and not any(r["reverse"] for r in runs):
        runs[0]["reverse"] = True
        for c in cells:
            if c["row"] == 0 and c["block"] == runs[0]["block"]:
                c["count"] = runs[0]["width"] - c["column"]
    fleet = []
    total = p["hostile"] + p["protected"]
    for index in range(total):
        angle = rng.choice([0, math.pi/2, math.pi/4, -math.pi/4])
        separation = 2*p["radius"] + 6
        half = separation*(p["compartments"]-1)/2
        offsets = [[round((i-(p["compartments"]-1)/2)*separation*math.cos(angle), 8),
                    round((i-(p["compartments"]-1)/2)*separation*math.sin(angle), 8)]
                   for i in range(p["compartments"])]
        extent = [max(abs(o[a]) for o in offsets)+p["radius"]+3 for a in range(2)]
        lo = [48+extent[0], 24+extent[1]]
        hi = [816-extent[0], 336-extent[1]]
        # All initial hulls are separated. Later crossing contacts are deliberate,
        # shown with outlines and protected cross emblems, never invisible colliders.
        for _ in range(10000):
            first = [rng.uniform(lo[a], hi[a]) for a in range(2)]
            if all(math.dist([first[a]+o[a] for a in range(2)],
                             [s["knots"][0][a]+old[a] for a in range(2)]) > 2*p["radius"]+8
                   for o in offsets for s in fleet for old in s["offsets"]):
                break
        else:
            raise ValueError("could not construct separated initial hulls")
        knots = [first]
        for k in range(1, math.ceil(240000/p["span_ms"])+4):
            key_seed = prefix if k*p["span_ms"] <= 4000 else str(seed)
            draw = random.Random(hashlib.sha256(f"{key_seed}|{MECHANIC_ID}|{index}|{k}|tail".encode()).digest())
            delta = [draw.uniform(-p["displacement"], p["displacement"]) for _ in range(2)]
            if math.hypot(*delta) < p["displacement"]*.45:
                delta[0] = p["displacement"]*.65 * draw.choice([-1, 1])
            knots.append([_reflect(knots[-1][a]+delta[a], lo[a], hi[a]) for a in range(2)])
        fleet.append(dict(id=f"hull-{index+1}", protected=index >= p["hostile"],
                          offsets=offsets, half=half, radius=p["radius"], knots=knots))
    world = dict(revision=REVISION, parameters=p, rows=p["rows"], columns=p["columns"],
                 bands=bands, runs=runs, cells=cells, fleet=fleet, chart=dict(width=840, height=370),
                 preview_ms=3200, trail_ms=600, play_time_ms=240000)
    task_id = task.get("id", f"{MECHANIC_ID}_seed_0001@0.1")
    failed = episode_failure()
    digest = hashlib.sha256(json.dumps([str(seed), task_id, world, condition, failed], sort_keys=True).encode()).hexdigest()[:20]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task_id,
                  challenge_id=digest, control_condition=condition, world=world, single_attempt=True,
                  episode_failed=failed, prompt="Search band by block with sonar. Speak the fleet's future coordinates.",
                  asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18),
                  render_boundary="Replay geometry is inspectable in browser state. Screenshot play discovers hulls by inspecting the selected band/block sector. Found identities persist in the log; any scan refreshes discovered tracks with the unchanged 600ms wake and rolling 3.2s forecast. No solver plan is shipped.")
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
