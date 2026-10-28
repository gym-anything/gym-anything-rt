"""Seeded 3D wirework in a continuously turning, source-derived lantern.

Interaction changes only input gestures. No game-time-mode branch exists.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random

MECHANIC_ID = "facet_lantern_v3"
REVISION = "wind-wirework-1"
PROFILES = {
    1: dict(ring_vertices=4, facets=2, initial_edges=0, yaw_rate=.11, pitch_rate=.025, roll_rate=0., gust=.25, span_ms=6500, stud_radius=19),
    2: dict(ring_vertices=6, facets=3, initial_edges=1, yaw_rate=.14, pitch_rate=.045, roll_rate=.012, gust=.35, span_ms=6000, stud_radius=19),
    3: dict(ring_vertices=6, facets=4, initial_edges=1, yaw_rate=.18, pitch_rate=.07, roll_rate=.025, gust=.45, span_ms=5500, stud_radius=18),
    4: dict(ring_vertices=8, facets=5, initial_edges=2, yaw_rate=.22, pitch_rate=.09, roll_rate=.045, gust=.55, span_ms=5000, stud_radius=18),
    5: dict(ring_vertices=10, facets=6, initial_edges=2, yaw_rate=.26, pitch_rate=.12, roll_rate=.07, gust=.65, span_ms=4500, stud_radius=18),
}


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def generate(task, seed):
    raw = task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition")
    if raw is None:
        raw = dict(difficulty=5, interaction="full", difficulty_parameters=PROFILES[5])
    condition = copy.deepcopy(raw)
    level = condition.get("difficulty")
    if type(level) is not int or level not in PROFILES or condition.get("interaction") not in ("full", "simplified"):
        raise ValueError("invalid lantern condition")
    p = copy.deepcopy(condition.get("difficulty_parameters"))
    if p != PROFILES[level]:
        raise ValueError("lantern profile differs from its five declared configurations")
    rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}".encode()).digest())
    n = p["ring_vertices"]
    labels = list("ABCDEFGHJKLMNPQRSTUVWXYZ"[:n+2])
    rng.shuffle(labels)
    vertices = [dict(id="v0", label=labels[0], position=[0, 1.20, 0])]
    phase = rng.uniform(-.12, .12)
    for i in range(n):
        a = phase + 2*math.pi*i/n
        vertices.append(dict(id=f"v{i+1}", label=labels[i+1], position=[round(math.cos(a), 8), 0., round(math.sin(a), 8)]))
    vertices.append(dict(id=f"v{n+1}", label=labels[n+1], position=[0, -1.20, 0]))
    faces = []
    for i in range(n):
        for pole in (0, n+1):
            ids = [pole, i+1, (i+1)%n+1]
            coords = [vertices[k]["position"] for k in ids]
            normal = _cross([coords[1][k]-coords[0][k] for k in range(3)], [coords[2][k]-coords[0][k] for k in range(3)])
            if sum(normal[k]*sum(c[k] for c in coords) for k in range(3)) < 0:
                ids.reverse()
            faces.append([f"v{k}" for k in ids])
    # Spread commissions around the complete circumference. Even the easiest
    # world needs rear-side studs; an instantaneous initial-screen batch cannot
    # wire the entire commission. Panes share moving pole and ring vertices.
    offset = rng.randrange(n)
    indices = [(offset + (i*n)//p["facets"])%n for i in range(p["facets"])]
    targets = [dict(id=f"pane-{i+1}", vertices=faces[2*k+(i%2)]) for i,k in enumerate(indices)]
    required = sorted({tuple(sorted((a,b))) for f in targets for a,b in zip(f["vertices"],f["vertices"][1:]+f["vertices"][:1])})
    initial = rng.sample(required, p["initial_edges"])
    world = dict(revision=REVISION, width=860, height=550, center=[430, 275], scale=185,
                 vertices=vertices, faces=faces, targets=targets, initial_edges=[list(x) for x in initial],
                 stud_radius=p["stud_radius"], duration_ms=180000,
                 motion=dict(seed=rng.getrandbits(32), span_ms=p["span_ms"], gust=p["gust"],
                             rates=[p["yaw_rate"],p["pitch_rate"],p["roll_rate"]],
                             angles=[math.pi/2-phase-2*math.pi*rng.randrange(n)/n+rng.uniform(-.1,.1),
                                     rng.uniform(-.08,.08), rng.uniform(-.18,.18)]),
                 trace_ms=600, forecast_ms=800)
    challenge = hashlib.sha256((f"{seed}|{REVISION}|"+json.dumps(p,sort_keys=True)).encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task["id"],
                  challenge_id=challenge, control_condition=condition, world=world,
                  prompt="Launch, then hover over moving gold studs to read their concealed etchings. Learned letters stay visible. Close the commissioned panes; a wrong wire breaks the lantern.",
                  submit_label="CERTIFY LANTERN", single_attempt=True,
                  generator=dict(name=REVISION, variant_count=10**12,
                                 variant_count_kind="seeded labels, facets, orientation and nonrepeating smooth angular trajectories"),
                  asset_manifest="shared_runtime/assets/provenance/facet_lantern_v3_v0.json")
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), required_edges=[list(x) for x in required])
    return public, truth
