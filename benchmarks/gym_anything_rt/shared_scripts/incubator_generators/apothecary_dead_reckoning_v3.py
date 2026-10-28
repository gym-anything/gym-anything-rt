"""Original live alchemical navigation, derived from VGE-704/705.

No solver route is sent to the browser. Interaction never affects world RNG.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random

MECHANIC_ID = "apothecary_dead_reckoning_v3"
REVISION = "living-atlas-1"
DISCOVERY_REVISION = "mortar-course-1"
PROFILES = {
    1: dict(seal_count=2, seal_radius=48, target_sway=18, target_span_ms=10000,
            current_speed=7, current_span_ms=9000, inertia_seconds=.35,
            bone_count=1, bone_sway=8, vortex_count=0, relative_speed_limit=22, dwell_ms=1000),
    2: dict(seal_count=2, seal_radius=44, target_sway=24, target_span_ms=8500,
            current_speed=10, current_span_ms=7500, inertia_seconds=.5,
            bone_count=2, bone_sway=12, vortex_count=0, relative_speed_limit=20, dwell_ms=1200),
    3: dict(seal_count=3, seal_radius=40, target_sway=29, target_span_ms=7000,
            current_speed=13, current_span_ms=6000, inertia_seconds=.7,
            bone_count=3, bone_sway=16, vortex_count=1, relative_speed_limit=18, dwell_ms=1400),
    4: dict(seal_count=3, seal_radius=36, target_sway=34, target_span_ms=6000,
            current_speed=17, current_span_ms=4500, inertia_seconds=.9,
            bone_count=4, bone_sway=20, vortex_count=1, relative_speed_limit=16, dwell_ms=1600),
    5: dict(seal_count=3, seal_radius=32, target_sway=38, target_span_ms=5200,
            current_speed=22, current_span_ms=3500, inertia_seconds=1.1,
            bone_count=5, bone_sway=24, vortex_count=2, relative_speed_limit=14, dwell_ms=1800),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or
                              (task.get("metadata") or {}).get("control_condition"))
    level = (condition or {}).get("difficulty", 4)
    mode = (condition or {}).get("interaction", "full")
    execution = (condition or {}).get("real_time", "live")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified") or execution not in ("live", "paused"):
        raise ValueError("invalid apothecary control condition")
    parameters = copy.deepcopy((condition or {}).get("difficulty_parameters") or PROFILES[level])
    if parameters != PROFILES[level]:
        raise ValueError("parameters must match the declared living-atlas profile")
    condition = dict(difficulty=level, interaction=mode, real_time=execution,
                     difficulty_parameters=parameters)
    stable = hashlib.sha256(f"{MECHANIC_ID}|{REVISION}|{seed}|{level}".encode()).hexdigest()
    rng = random.Random(int(stable, 16))
    count = parameters["seal_count"]
    xs = [330, 700] if count == 2 else [290, 510, 740]
    if count == 2:
        # A broad, gentle dogleg still requires changing course. Near-collinear
        # low-level goals admitted preparation-only constant-thrust solutions.
        # This is visible geometry, with the same physics and tolerances.
        side = rng.choice((-1, 1))
        target_y = [230 + side * rng.uniform(78, 92),
                    230 - side * rng.uniform(78, 92)]
    else:
        target_y = [rng.uniform(155, 305) for _ in xs]
    glyphs = [("moth", "Moth fire", "#ab5431"), ("eye", "Glass sleep", "#476e9b"),
              ("thorn", "Thorn voice", "#4a714c")]
    rng.shuffle(glyphs)
    effects = []
    for i, (x, y) in enumerate(zip(xs, target_y)):
        glyph, name, color = glyphs[i]
        effects.append(dict(id=f"seal-{i}", center=[x, round(y, 4)], radius=parameters["seal_radius"],
                            glyph=glyph, name=name, color=color, seed=rng.getrandbits(32),
                            sway=parameters["target_sway"], span_ms=parameters["target_span_ms"]))
    origin = [80., 230.]
    bones = []
    # Expanded swept envelopes remain separated from target envelopes. Both
    # upper and lower bypasses stay wide enough for a flask and human drift.
    candidates = [(185, (230 + target_y[0]) / 2),
                  (400, (target_y[0] + target_y[-1 if count == 2 else 1]) / 2),
                  (625, (target_y[-2] + target_y[-1]) / 2), (405, 105), (625, 355)]
    for i, (x, y) in enumerate(candidates[:parameters["bone_count"]]):
        if count == 2 and i == 1:
            x = 510
        bones.append(dict(id=f"bone-{i}", center=[x, round(y + rng.uniform(-12, 12), 4)],
                          radius=19 + rng.randrange(4), seed=rng.getrandbits(32),
                          sway=parameters["bone_sway"], span_ms=6500))
    ingredient_catalog = [("ashfern", "Ashfern", "#678259"), ("cinder", "Cinder cap", "#b96145"),
                          ("moonreed", "Moon reed", "#688da0"), ("saltbloom", "Salt bloom", "#978052")]
    rng.shuffle(ingredient_catalog)
    ingredients = [dict(id=record[0], name=record[1], color=record[2], angle_deg=i * 90)
                   for i, record in enumerate(ingredient_catalog)]
    vortices = [dict(center=[390 + i * 160, 230], strength=7 + 2 * i, radius=170,
                     spin=rng.choice((-1, 1)), seed=rng.getrandbits(32))
                for i in range(parameters["vortex_count"])]
    task_id = task["id"]
    shared = dict(mechanic_id=MECHANIC_ID, revision=REVISION, task_id=task_id,
                  challenge_id=hashlib.sha256(f"{stable}|{task_id}|{mode}|{DISCOVERY_REVISION}".encode()).hexdigest()[:20],
                  control_condition=condition, parameters=parameters,
                  stage=dict(width=840, height=460), origin=origin, effects=effects,
                  bones=bones, ingredients=ingredients, vortices=vortices,
                  flow_seed=rng.getrandbits(32),
                  mechanics=dict(tick_ms=20, flask_radius=8, drive_speed=68,
                                 water_speed=40, max_time_ms=140000, charge_leak=2,
                                 preview_seconds=2, trace_window_ms=800))
    # Preserve the V2 physics recipe and every preceding RNG draw. Shelf order
    # must not disclose the four courses: inspect a jar in the existing mortar.
    # The same independent permutation is used by both interaction modes.
    random.Random(f"{stable}|{DISCOVERY_REVISION}").shuffle(shared["ingredients"])
    shared["discovery"] = dict(revision=DISCOVERY_REVISION,
                               course_reveal="mortar_sample_or_propulsion_preview",
                               retain_learned_courses=True)
    public = dict(copy.deepcopy(shared), benchmark="gym_anything_rt",
                  prompt=task.get("natural_language", "Brew the three seals of the living atlas."),
                  generator=dict(name=REVISION, variant_count=10**18,
                                 variant_count_kind="continuous layouts and independent nonperiodic flow/target/bone seeds"),
                  asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json")
    truth = dict(copy.deepcopy(shared), seed=str(seed))
    return public, truth
