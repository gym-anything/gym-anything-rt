"""Source-derived powered gimbal; interaction never enters world generation."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import random
from pathlib import Path

MECHANIC_ID = "rotate_wrong_thing_upright_v3_nonrealtime"
DONOR_WINDING_NAMESPACE = "rotate_wrong_thing_upright_v3"
REVISION = "wind-gimbal-3-inspection"
PROFILES = {
    1: dict(axes=1, tolerance_deg=14, speed_tolerance=10, response_s=.4, coupling=0., gust_rate=28, gust_span_ms=2600),
    2: dict(axes=2, tolerance_deg=12, speed_tolerance=9, response_s=.5, coupling=.12, gust_rate=30, gust_span_ms=2300),
    3: dict(axes=3, tolerance_deg=10, speed_tolerance=8, response_s=.55, coupling=.18, gust_rate=32, gust_span_ms=2100),
    4: dict(axes=3, tolerance_deg=8, speed_tolerance=7, response_s=.7, coupling=.22, gust_rate=34, gust_span_ms=1900),
    5: dict(axes=3, tolerance_deg=6, speed_tolerance=6, response_s=.85, coupling=.28, gust_rate=36, gust_span_ms=1750),
}


def _episode_failure(task_id):
    """Retain this task's server-verified failures across shared regeneration.

    The shared server owns the episode's current_task.json and writes its grade
    into attempts.jsonl before calling the generator. Submitted identities and
    policy claims cannot select which failures count. Reversible motor edits
    never enter this ledger.
    """
    state_dir = Path(os.environ.get("GYM_ANYTHING_RT_STATE_DIR", "/tmp/gym_anything_rt"))
    ledger = state_dir / "attempts.jsonl"
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return False, ""
    except (OSError, UnicodeError) as exc:
        return False, "Cannot read episode failure history: " + str(exc)
    if not any(line.strip() for line in lines):
        return False, ""
    try:
        current = json.loads((state_dir / "current_task.json").read_text(encoding="utf-8"))
        bound = current.get("task") if isinstance(current, dict) else None
        if not isinstance(bound, dict) or not bound.get("id") or not isinstance(bound.get("metadata"), dict):
            raise ValueError("missing bound task for archived attempts")
        if bound["id"] != task_id or bound["metadata"].get("mechanic_id") != MECHANIC_ID:
            # Offline generation for another task must not inherit this
            # episode's failures. This comparison uses server-owned binding.
            return False, ""
        failed = False
        for line in lines:
            if not line.strip():
                continue
            attempt = json.loads(line)
            if not isinstance(attempt, dict):
                raise ValueError("invalid archived attempt")
            decision = attempt.get("server_grade")
            if not isinstance(decision, dict) or decision.get("graded") is not True or decision.get("passed") is not False:
                raise ValueError("archived attempt lacks a verified failure")
            failed = True
        return failed, ""
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return False, "Cannot verify episode failure history: " + str(exc)


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    if level not in PROFILES:
        raise ValueError("gimbal difficulty must be 1 through 5")
    parameters = dict(PROFILES[level])
    parameters.update((condition or {}).get("difficulty_parameters", {}))
    if parameters != PROFILES[level]:
        raise ValueError("profile parameters do not match the declared gimbal level")
    if (condition or {}).get("interaction", "full") not in ("full", "simplified"):
        raise ValueError("unsupported gimbal input surface")
    # Preserve V2's geometry, initial pose and nonperiodic wind for a fixed
    # seed. A separate stream varies only the inspectable motor windings.
    rng = random.Random(hashlib.sha256(f"rotate_wrong_thing_upright_v2|wind-gimbal-2|{seed}".encode()).digest())
    count = parameters["axes"]
    initial = [rng.choice((-1, 1)) * rng.randint(35, 65) if i < count else 0 for i in range(3)]
    c = parameters["coupling"]
    matrix = [[1, -c if count > 1 else 0, 0], [0, 1, c if count > 2 else 0], [c if count > 2 else 0, 0, 1]]
    contract = dict(parameters=parameters, initial=initial, initial_velocity=[0, 0, 0],
                    wind_seeds=[rng.getrandbits(32) for _ in range(3)], matrix=matrix,
                    motor_rate=65, tick_ms=10, action_step_ms=200, hold_ms=10000, run_limit_ms=90000,
                    stop_deg=150, forecast_ms=2000, history_ms=600,
                    sculpture=dict(mast_height=rng.randint(90, 110), wing_width=rng.randint(50, 70),
                                   crown=rng.choice(("fork", "diamond", "lantern"))))
    # Keep V3's signed winding stream stable while the public task identity
    # remains task-local to this counterpart.
    winding_rng = random.Random(hashlib.sha256(f"{DONOR_WINDING_NAMESPACE}|windings|{seed}".encode()).digest())
    polarities = [winding_rng.choice((-1, 1)) if i < count else 1 for i in range(3)]
    contract["matrix"] = [[value * polarities[j] for j, value in enumerate(row)] for row in matrix]
    identity = hashlib.sha256(f"{MECHANIC_ID}|{REVISION}|{seed}|d{level}".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task["id"], challenge_id=identity, revision=REVISION,
                  prompt="Rotate The Wrong Thing Upright V3", single_attempt=True,
                  gimbal=contract, asset_manifest="shared_runtime/assets/provenance/rotate_wrong_thing_upright_v3_v0.json",
                  generator=dict(name="seeded_wind_loaded_gimbal", variant_count=2**(32*count),
                                 variant_count_kind=f"{count} active 32-bit disturbance seeds; geometry and initial orientation also vary"))
    if condition:
        public["control_condition"] = condition
    public["episode_failed"], public["episode_history_error"] = _episode_failure(task["id"])
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
