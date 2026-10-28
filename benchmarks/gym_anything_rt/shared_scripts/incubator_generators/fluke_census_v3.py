"""Moving-camera census with a seed-specific, camera-inspected field key."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import importlib.util
from pathlib import Path
import random

MECHANIC_ID = "fluke_census_v3"
REVISION = "moving-camera-landmarks-v3-sampled-field-key"
WORLD_REVISION = "moving-camera-landmarks-v2-early-opportunities"
SEED_REVISION = "moving-camera-landmarks-v1"
SOURCE_ANCHORS = ["GWP-156", "COG-237", "COG-114", "XCOG-100", "XCOG-101"]
PROFILES = {
    1: dict(animal_count=3, frame_width=208, frame_height=164, motion_rate=.16, turn_degrees=8, notch_difference=15, scale_variation=.02, landmark_tolerance=11),
    2: dict(animal_count=6, frame_width=196, frame_height=158, motion_rate=.20, turn_degrees=14, notch_difference=13, scale_variation=.04, landmark_tolerance=10),
    3: dict(animal_count=6, frame_width=184, frame_height=150, motion_rate=.25, turn_degrees=24, notch_difference=11, scale_variation=.08, landmark_tolerance=9),
    4: dict(animal_count=9, frame_width=172, frame_height=142, motion_rate=.30, turn_degrees=34, notch_difference=9, scale_variation=.10, landmark_tolerance=8),
    5: dict(animal_count=12, frame_width=162, frame_height=132, motion_rate=.36, turn_degrees=48, notch_difference=7, scale_variation=.12, landmark_tolerance=8),
}
BASELINE_LEVEL = 4


def generate(task, seed):
    condition = task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition")
    level = (condition or {}).get("difficulty", BASELINE_LEVEL)
    if type(level) is not int or level not in PROFILES:
        raise ValueError("difficulty must be 1 through 5")
    mode = (condition or {}).get("interaction", "full")
    if mode not in ("full", "simplified"):
        raise ValueError("unsupported interaction")
    params = dict(PROFILES[level])
    supplied = (condition or {}).get("difficulty_parameters") or {}
    if supplied and supplied != params:
        raise ValueError("profile parameters must match the selected difficulty")
    rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|{SEED_REVISION}".encode()).digest())
    for generation_attempt in range(128):
        world = _draw_world(rng,params)
        if _has_early_clear_opportunities(world):break
    else:
        raise ValueError("No fair early framing opportunities found within generation limit")
    task_id = task["id"]
    # Use a separate stream: the optical field key must not redraw trajectories,
    # scars, framing geometry, or the accepted early-opportunity world.
    guide_rng = random.Random(hashlib.sha256(f"{seed}|fluke-census-v3-field-key".encode()).digest())
    names = ["Crescent", "Harbour", "Deepwater"]
    guide_rng.shuffle(names)
    world["field_key"] = dict(species_names=names, overview_ink="#9db6b4")
    identity = dict(mechanic_id=MECHANIC_ID, task_id=task_id,
                    challenge_id=hashlib.sha256(f"{seed}|{task_id}|{json.dumps(condition,sort_keys=True)}|{REVISION}".encode()).hexdigest()[:20],
                    control_condition=copy.deepcopy(condition))
    public = dict(**identity, **copy.deepcopy(world), title="Fluke Census V3",
                  prompt="Click a live camera specimen to identify its species safely. Photograph every WANTED individual once; mark its two tips and V.",
                  asset_manifest="shared_runtime/assets/provenance/fluke_census_v3_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18), source_anchors=SOURCE_ANCHORS)
    truth = dict(**identity, world=copy.deepcopy(world), seed=str(seed),
                 required_ids=[a["id"] for a in world["animals"] if a["species"] in world["listed_species"]],
                 generation_attempts=generation_attempt+1)
    return public, truth


def _draw_world(rng,params):
    animals = []
    for species in range(3):
        # Individual tail scars are geometry, not labels or hidden answer keys.
        base = [rng.choice((2, 5, 8)) for _ in range(6)]
        for scar in rng.sample(range(6), params["animal_count"] // 3):
            notches = base.copy()
            notches[scar] += params["notch_difference"]
            rate = params["motion_rate"] * rng.uniform(.90, 1.10)
            animals.append(dict(
                id=f"fluke-{rng.getrandbits(48):012x}", species=species,
                notches=notches, scale=rng.uniform(1-params["scale_variation"], 1+params["scale_variation"]),
                motion=dict(
                    cx=rng.uniform(360, 500), cy=rng.uniform(220, 240),
                    ax=rng.uniform(175, 200), bx=rng.uniform(25, 40),
                    ay=rng.uniform(90, 100), by=rng.uniform(14, 20),
                    rate=rate, phase=[rng.uniform(0, math.tau) for _ in range(5)],
                    base_angle=rng.uniform(-.35, .35), turn=math.radians(params["turn_degrees"]),
                )))
    rng.shuffle(animals)
    listed = sorted(rng.sample(range(3), 2))
    world = dict(stage=dict(width=860, height=460), animals=animals, listed_species=listed,
                 parameters=params,
                 camera=dict(width=params["frame_width"], height=params["frame_height"],
                             initial=[430,230], speed=720, acceleration=2400, tick_ms=10),
                 play_time_ms=240000, wake_window_ms=600, revision=WORLD_REVISION)
    return world


_GEOMETRY = None


def _has_early_clear_opportunities(world):
    """Reject worlds whose required flukes cannot appear in an early survey.

    This is generation feasibility, not a player action quota. Both input
    variants receive the same accepted world. The task/grader physics is intact.
    """
    global _GEOMETRY
    if _GEOMETRY is None:
        path=Path(__file__).resolve().parents[2]/"shared_runtime/server/incubator_graders/fluke_census_v3.py"
        spec=importlib.util.spec_from_file_location("fluke_census_v3_generation_geometry",path)
        _GEOMETRY=importlib.util.module_from_spec(spec);spec.loader.exec_module(_GEOMETRY)
    g=_GEOMETRY;c=world['camera']
    for animal in world['animals']:
        if animal['species'] not in world['listed_species']:continue
        count=0
        for ms in range(600,30001,600):
            poly=g.polygon(animal,ms)
            low=[max(p[i] for p in poly)-c[k]/2 for i,k in enumerate(('width','height'))]
            high=[min(p[i] for p in poly)+c[k]/2 for i,k in enumerate(('width','height'))]
            if any(a>b for a,b in zip(low,high)):continue
            interior=g.transform([[0,18]],g.pose(animal,ms))[0]
            points=[interior,[(a+b)/2 for a,b in zip(low,high)],
                    [max(a,min(b,v)) for a,b,v in zip(low,high,interior)]]
            if any(g.inside(point,poly) and g.framed(world,point,ms)[0]==animal['id'] for point in points):
                count+=1
                if count>=2:break
        if count<2:return False
    return True
