"""Source-derived moving photometry. No changes to the original shadow lab."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "shadow_crime_lab_v3_nonrealtime"
DONOR_MECHANIC_ID = "shadow_crime_lab_v3"
REVISION = "moving-photometry-exploration-1"
WORLD_REVISION = "moving-photometry-1"
PROFILES = {
    1: dict(bench_count=1, objects_per_bench=3, radius=24, angular_speed=.45, lamp_span_ms=7000, lag_ms=1500, damping=22),
    2: dict(bench_count=1, objects_per_bench=3, radius=22, angular_speed=.54, lamp_span_ms=5500, lag_ms=1200, damping=20),
    3: dict(bench_count=1, objects_per_bench=4, radius=20, angular_speed=.62, lamp_span_ms=4200, lag_ms=1000, damping=18),
    4: dict(bench_count=2, objects_per_bench=4, radius=20, angular_speed=.62, lamp_span_ms=4200, lag_ms=1000, damping=18),
    5: dict(bench_count=2, objects_per_bench=5, radius=17, angular_speed=.72, lamp_span_ms=3200, lag_ms=800, damping=15),
}
RULE = ("Test each lamp on its rail; one shadow follows your shift late. "
        "Track its dashed end cap with the aperture. Build all exposures together to 6s; "
        "lost contact fades and can recover. An honest exposure, incomplete filing or the "
        "120s scan limit ends the episode. Accepted controls advance fixed 40ms slices; "
        "idle waiting does not advance the scan.")


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or task.get("metadata", {}).get("control_condition"))
    difficulty = int((condition or {}).get("difficulty", 5))
    mode = (condition or {}).get("interaction", "full")
    if difficulty not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("unsupported shadow-lab condition")
    parameters = copy.deepcopy(PROFILES[difficulty])
    if condition and condition.get("difficulty_parameters") != parameters:
        raise ValueError("condition parameters do not match the selected shadow-lab profile")
    condition = condition or dict(difficulty=5, interaction="full", real_time="live", difficulty_parameters=parameters)
    # Keep corresponding V3 seeds identical to the evaluated donor. The
    # counterpart namespace changes the task identity, not the puzzle draw.
    rng = random.Random(hashlib.sha256(f"{seed}|{DONOR_MECHANIC_ID}|{WORLD_REVISION}".encode()).digest())
    benches = []
    for index in range(parameters["bench_count"]):
        count = parameters["objects_per_bench"]
        objects = []
        for j in range(count):
            objects.append(dict(id=f"{index+1}-{j+1}", x=230+j*500/(count-1), y=92,
                radius=parameters["radius"], height=rng.choice((54, 60, 66)),
                sides=rng.choice((6, 8, 12)), angle=round(rng.random()*6.28, 6),
                phase=round(rng.random()*6.28, 6), seed=rng.getrandbits(32),
                color=rng.choice(("#477e8e", "#b57457", "#83836a", "#766780"))))
        benches.append(dict(id=index, objects=objects, lamp_seed=rng.getrandbits(32),
            lamp_z=300, lamp_x=480, lamp_y=12, forged_index=rng.randrange(count)))
    task_id = task.get("id", "shadow_crime_lab_v3_nonrealtime_seed_0001@0.1")
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task_id,
        challenge_id=hashlib.sha256(f"{seed}|{DONOR_MECHANIC_ID}|{REVISION}|d{difficulty}".encode()).hexdigest()[:16],
        revision=REVISION, prompt=RULE, control_condition=condition,
        parameters=parameters, benches=benches, stage=dict(width=960, height=440, bench_height=220),
        inspection=dict(rail_half_span=60, rail_height=36, lamp_grab_radius=25),
        physics=dict(tick_ms=10, action_step_ms=40, aperture_radius=7, grab_radius=25, speed_limit=340,
            acceleration_limit=1800, spring=100, damping=parameters["damping"],
            exposure_ms=6000, fade_rate=3, time_limit_ms=120000),
        single_attempt=True, asset_manifest="shared_runtime/assets/provenance/shadow_crime_lab_v3_v0.json",
        generator=dict(name=REVISION, variant_count=10**18,
                       variant_count_kind="independent seeded lamp and specimen paths, geometry and forged identities"))
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    # The browser needs the forge rule to draw it. It is not secret from source
    # inspection; downstream agents are limited to visible screenshots/controls.
    truth["forged_ids"] = [b["objects"][b["forged_index"]]["id"] for b in benches]
    return public, truth
