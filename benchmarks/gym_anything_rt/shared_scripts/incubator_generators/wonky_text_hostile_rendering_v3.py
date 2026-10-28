"""Continuous color registration with inspectable concealed plate fiducials."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import math
from pathlib import Path
import random

MECHANIC_ID = "wonky_text_hostile_rendering_v3"
REVISION = "drifting-letterpress-inspection-1"
WORLD_NAMESPACE = "wonky_text_hostile_rendering_v2|drifting-letterpress-4"
PROFILES = {
    1: dict(plate_count=1, axes=1, tolerance=23, span_ms=10000, servo_ms=180, warp=0.20),
    2: dict(plate_count=1, axes=2, tolerance=21, span_ms=9400, servo_ms=220, warp=0.30),
    3: dict(plate_count=2, axes=2, tolerance=19, span_ms=9000, servo_ms=260, warp=0.40),
    4: dict(plate_count=3, axes=2, tolerance=17, span_ms=8700, servo_ms=300, warp=0.50),
    5: dict(plate_count=3, axes=2, tolerance=14, span_ms=8200, servo_ms=340, warp=0.65),
}
RULES = ("Each plate has two moving guides, marked with a dot or diamond; one is a reflected ghost. "
         "Sweep the loupe over each covered plate sleeve to find its true registration stamp. Discovered stamps stay visible. "
         "Inspect and prepare before START PRESS; inspection never pauses a running press. "
         "Keep each solid handle's cross inside the guide matching that plate's stamp. "
         "The short trail shows recent drift; the dotted line and small bead show the next 600 ms. "
         "The square is your commanded position: the solid handle follows with inertia. "
         "Clean exposure accumulates only while all crosses are inside their rings; paper keeps feeding otherwise. "
         "Color separation outside a ring permanently spoils the paper. Finish 24 seconds of clean exposure within 40 seconds, before the spoil gauge fills. "
         "There is one attempt; an early submission ends it.")


def episode_status(task_id):
    """Task-local history gate; the world and seeded motion remain unchanged."""
    path = Path(__file__).resolve().parents[2] / "shared_runtime/server/incubator_graders/wonky_text_hostile_rendering_v3.py"
    spec = importlib.util.spec_from_file_location("letterpress_episode_history", path)
    if spec is None or spec.loader is None:
        return dict(episode_failed=False, episode_history_error="Episode failure history is unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failure, error = module.read_episode_failure(task_id)
    return dict(episode_failed=bool(failure), episode_history_error=error or "")


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or task.get("metadata", {}).get("control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    mode = (condition or {}).get("interaction", "full")
    if level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("letterpress needs a difficulty 1–5 and a supported interaction")
    params = copy.deepcopy(PROFILES[level])
    if condition is not None and condition.get("difficulty_parameters") != params:
        raise ValueError("letterpress parameters do not match the selected profile")
    condition = dict(difficulty=level, interaction=mode, real_time="live", difficulty_parameters=params)
    # Keep the frozen V2 physical world exactly, including the token. Concealed
    # printing marks use a separate stream and cannot perturb drift or timing.
    rng = random.Random(hashlib.sha256(f"{seed}|{WORLD_NAMESPACE}|d{level}".encode()).digest())
    inspection_rng = random.Random(hashlib.sha256(f"{seed}|{MECHANIC_ID}|fiducials|d{level}".encode()).digest())
    plates = []
    for index, color in enumerate(("cyan", "magenta", "amber")[:params["plate_count"]]):
        nodes = []
        for _ in range(12):
            # Independent non-repeating displacement: distant successive nodes
            # keep all profiles dynamic, without hidden teleports or periods.
            while True:
                p = [round(rng.uniform(72, 228), 3), round(rng.uniform(48, 152), 3) if params["axes"] == 2 else 100.0]
                if params["axes"] == 1 and 132 < p[0] < 168:
                    # Mid-range one-dimensional points can make the next
                    # 85-pixel displacement impossible to generate.
                    continue
                if not nodes or math.dist(nodes[-1], p) >= 85:
                    nodes.append(p)
                    break
        times = [0]
        for _ in range(len(nodes)-1):
            # The first visible drift cannot reveal later turn times. Wider
            # durations at the single-plate levels defeat a prepared oscillator.
            lower = .45 if level <= 2 else .60
            times.append(times[-1] + round(params["span_ms"] * rng.uniform(lower, 1.50)))
        plates.append(dict(id=f"plate-{index}", color=color, nodes=nodes, node_times_ms=times,
                           phase_ms=rng.randrange(0, 1200), initial=[150.0, 100.0],
                           register_mark=inspection_rng.choice(("dot", "diamond")),
                           stamp_x=inspection_rng.randrange(65, 236)))
    press = dict(revision=REVISION, plates=plates, token="".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5)),
                 **params, tick_ms=10, duration_ms=40000, required_clean_ms=24000, spoil_limit_ms=3600,
                 preview_ms=600, handle_radius=16, bounds=[28, 272, 28, 172],
                 sleeve_size=[300, 64], loupe_radius=30, stamp_radius=10)
    task_id = task["id"]
    identity = hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}|{level}".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task_id,
                  challenge_id=identity, control_condition=condition, prompt=RULES, press=press,
                  single_attempt=True, asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18))
    public.update(episode_status(task_id))
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
