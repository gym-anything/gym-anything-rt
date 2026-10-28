"""CAPTCHaStar-derived moving, cursor-conditioned exposure fields.

No interaction-dependent randomness. Geometry supplied to the browser is also
the independent replay contract; it is not secret from browser inspection.
"""
from __future__ import annotations

import copy
import hashlib
import math
import random

MECHANIC_ID = "cursor_constellation_hunt_v3_nonrealtime"
REVISION = "drifting-exposure-1"
DISCOVERY_REVISION = "probe-gold-response-1"
ACTION_STEP_MS = 20
PROFILES = {
    1: dict(field_count=1, tolerance=38, span_ms=7500, noise_count=0, spring=70, damping=17),
    2: dict(field_count=1, tolerance=32, span_ms=6500, noise_count=8, spring=65, damping=16),
    3: dict(field_count=2, tolerance=32, span_ms=6500, noise_count=8, spring=65, damping=16),
    4: dict(field_count=2, tolerance=27, span_ms=5500, noise_count=16, spring=55, damping=15),
    5: dict(field_count=3, tolerance=24, span_ms=4500, noise_count=22, spring=50, damping=14),
}


def shape_points(shape, count=30):
    """Original, procedural constellation outlines; no source artwork."""
    result = []
    for i in range(count):
        a = math.tau * i / count
        if shape == "heart":
            x = 16 * math.sin(a)**3 * 3.4
            y = -(13*math.cos(a)-5*math.cos(2*a)-2*math.cos(3*a)-math.cos(4*a))*3.4
        elif shape == "fish":
            x, y = 67*math.cos(a), 39*math.sin(a)
            if i in (0, 1, count-1): x += 28
        else:
            radius = 66 if i % 6 < 3 else 39
            x, y = radius*math.cos(a), radius*math.sin(a)
        result.append([round(160+x, 4), round(160+y, 4)])
    return result


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or
                               task.get("metadata", {}).get("control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    mode = (condition or {}).get("interaction", "full")
    if level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("invalid constellation condition")
    parameters = copy.deepcopy(PROFILES[level])
    parameters.update((condition or {}).get("difficulty_parameters", {}))
    if parameters != PROFILES[level]:
        raise ValueError("profile parameters must match a documented difficulty")
    condition = condition or dict(difficulty=level, interaction=mode, real_time="live",
                                 difficulty_parameters=copy.deepcopy(parameters))
    rng = random.Random(hashlib.sha256(f"{REVISION}|{seed}|d{level}".encode()).digest())
    fields = []
    shapes = ["heart", "fish", "star"]
    rng.shuffle(shapes)
    for index in range(parameters["field_count"]):
        # A separate seed stream preserves every V2 drift path, shape, noise
        # point and non-guide transform. A screenshot reveals the guide's
        # offset, but a reversible lens probe reveals how to change it.
        response = hashlib.sha256(
            f"{DISCOVERY_REVISION}|{seed}|d{level}|field{index}".encode()).digest()[0] % 4
        path = []
        angle = rng.uniform(0, math.tau)
        # Each segment crosses a substantial fraction of the field. The next
        # arc direction and endpoint are independently varied, never a loop.
        for j in range(24):
            if j:
                angle += rng.choice((-1, 1))*rng.uniform(2.0, 3.65)
            path.append([round(160+100*math.cos(angle), 6),
                         round(160+100*math.sin(angle), 6)])
        points = shape_points(shapes[index])
        stars = []
        for i, point in enumerate(points):
            # Orthogonal transforms preserve error length exactly. Thus the
            # visible acceptance halo and the grader's lens radius agree.
            theta = response * math.pi / 2 if i == 0 else rng.uniform(-math.pi, math.pi)
            stars.append(dict(anchor=point, angle=theta, guide=i == 0))
        fields.append(dict(id=f"field-{index}", shape=shapes[index], path=path,
                           span_ms=parameters["span_ms"]+index*173,
                           stars=stars,
                           noise=[[rng.uniform(22,298), rng.uniform(22,298)]
                                  for _ in range(parameters["noise_count"])],
                           initial_lens=[160.,160.], initial_velocity=[0.,0.]))
    world = dict(revision=REVISION, discovery_revision=DISCOVERY_REVISION,
                 clock_mode="action_triggered", action_step_ms=ACTION_STEP_MS,
                 tick_ms=20, field_size=320,
                 fields=fields, tolerance=parameters["tolerance"],
                 spring=parameters["spring"], damping=parameters["damping"],
                 max_speed=420., acceleration_cap=2200.,
                 exposure_ms=8000, fade_rate=2., max_active_ms=90000,
                 trail_window_ms=800, trail_samples=5)
    task_id = task["id"]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task_id,
                  challenge_id=hashlib.sha256(f"{REVISION}|{DISCOVERY_REVISION}|{seed}|{task_id}".encode()).hexdigest()[:20],
                  control_condition=condition, world=world,
                  prompt="Keep every constellation sharp until all exposures fill together.",
                  asset_manifest="shared_runtime/assets/provenance/cursor_constellation_hunt_v3_v0.json",
                  generator=dict(name=f"{REVISION}+{DISCOVERY_REVISION}", variant_count=10**18,
                                 variant_count_kind="seeded shapes, gold response directions, star transforms and nonrepeating drift paths"),
                  render_boundary="Paths and star geometry ship for rendering and replay; page inspection is outside the model policy.")
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
