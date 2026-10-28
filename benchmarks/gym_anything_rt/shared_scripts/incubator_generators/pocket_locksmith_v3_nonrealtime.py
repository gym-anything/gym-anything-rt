"""Moving molecular pocket with safely discoverable drive linkages."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import random

MECHANIC_ID = "pocket_locksmith_v3_nonrealtime"
# Keep corresponding seeds identical to the evaluated V3 donor. The public
# mechanic namespace changes, but seeded geometry, paths and linkages do not.
PUZZLE_NAMESPACE = "pocket_locksmith_v3"
REVISION = "moving-pocket-2"
DEFAULT = dict(joints=4, amplitude_deg=50, span_ms=3200, clearance=.17,
               servo_gain=65, servo_damping=15, max_acceleration=480,
               max_speed=125, run_ms=24000, required_fraction=.82, max_outage_ms=4500)


def episode_failure(task_id):
    """Read the existing archive without clearing or rewriting earlier attempts."""
    directory = os.environ.get("GYM_ANYTHING_RT_STATE_DIR", "/tmp/gym_anything_rt")
    try:
        with (Path(directory) / "attempts.jsonl").open(encoding="utf-8") as journal:
            # The server archive belongs to its bound episode. Identity fields
            # inside a rejected payload are client input, not archive scope.
            current_path = Path(directory) / "current_task.json"
            if current_path.exists():
                current = json.loads(current_path.read_text(encoding="utf-8"))
                bound = current.get("task") if isinstance(current, dict) else None
                metadata = bound.get("metadata") if isinstance(bound, dict) else None
                if (not isinstance(bound, dict) or not bound.get("id")
                        or not isinstance(metadata, dict) or not metadata.get("mechanic_id")):
                    raise ValueError("invalid bound task record")
                if bound["id"] != task_id or metadata["mechanic_id"] != MECHANIC_ID:
                    return ""
            for line in journal:
                if not line.strip():
                    continue
                attempt = json.loads(line)
                if not isinstance(attempt, dict):
                    raise ValueError("invalid attempt record")
                decision = attempt.get("server_grade")
                if not isinstance(decision, dict) or decision.get("graded") is not True:
                    raise ValueError("invalid failed-submission grade")
                if decision.get("passed") is False:
                    return "A failed submission already ended this episode."
                if decision.get("passed") is not True:
                    raise ValueError("missing failed-submission verdict")
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError, ValueError, TypeError):
        return "Episode failure history is unavailable."
    return ""


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    parameters = dict(DEFAULT)
    if condition is not None:
        if condition.get("difficulty") not in range(1, 6) or condition.get("interaction") not in ("full", "simplified"):
            raise ValueError("invalid pocket control condition")
        parameters.update(condition.get("difficulty_parameters") or {})
    if not 1 <= parameters["joints"] <= 4 or not 30 <= parameters["amplitude_deg"] <= 65:
        raise ValueError("unsupported key articulation")
    if not 2400 <= parameters["span_ms"] <= 6000 or not .10 <= parameters["clearance"] <= .26:
        raise ValueError("unsupported pocket dynamics")
    if parameters["run_ms"] != 24000 or not .7 <= parameters["required_fraction"] <= .95:
        raise ValueError("unsupported binding trial")
    rng = random.Random(hashlib.sha256(f"{seed}|{PUZZLE_NAMESPACE}|{REVISION}".encode()).digest())
    count = parameters["joints"]
    # Every subsequent bond axis is transported with the upstream chain.
    # The scaffold has separated atoms and noncollinear bond axes.
    base = [[round((i-(count+1)/2)*.82, 5),
             round((.55 if i % 2 else -.18) + rng.uniform(-.06, .06), 5),
             round((.48 if i % 3 == 2 else -.22) + rng.uniform(-.05, .05), 5)]
            for i in range(count + 2)]
    paths = []
    for joint in range(count):
        span = parameters["span_ms"]
        sign = rng.choice((-1, 1))
        knots = [0.0]
        times = [0]
        for index in range(1, 16):
            # Alternating extrema prevent a static pose from holding all contacts.
            # Independent heights and spans remove an exactly repeating trajectory.
            knots.append(round(sign * (-1)**(index-1) * parameters["amplitude_deg"] * rng.uniform(.74, 1), 5))
            times.append(times[-1] + round(span * rng.uniform(.75, 1.25)))
        paths.append(dict(times_ms=times, knots=knots))
    level = (condition or {}).get("difficulty", 5)
    world = dict(revision=REVISION, base_points=base, paths=paths, parameters=parameters,
                 completion_rule="earn simultaneous contact quota before deadline",
                 tick_ms=20, atom_radius=.10, command_limit_deg=85, forecast_ms=800,
                 initial_angles=[0.] * count, colors=["#ffba70", "#79dfce", "#baa1ff", "#fb87b1"][:count])
    # Separate randomness preserves the V3 scaffold, motion and information
    # mechanics exactly. Neutral drive labels do not reveal these connections
    # before a test turn.
    # Neutral drive labels do not reveal these connections before a test turn.
    linkage_rng = random.Random(hashlib.sha256(f"{seed}|{PUZZLE_NAMESPACE}|drive-linkages-1".encode()).digest())
    joints = list(range(count))
    linkage_rng.shuffle(joints)
    world["drive_linkages"] = [dict(joint=j, direction=linkage_rng.choice((-1, 1))) for j in joints]
    world["linkage_revision"] = "drive-linkages-1"
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task["id"], challenge_id=hashlib.sha256(f"{seed}|{PUZZLE_NAMESPACE}|{REVISION}|drive-linkages-1|d{level}".encode()).hexdigest()[:16],
                  prompt="Keep the articulated key inside its moving sockets.",
                  world=world, single_attempt=True,
                  display=dict(title="Pocket Locksmith V3", pocket_name=rng.choice(("NACRE", "ORCHID", "LANTERN", "LAPIS"))),
                  generator=dict(name=REVISION, variant_count=2**64),
                  asset_manifest="shared_runtime/assets/provenance/pocket_locksmith_v3_v0.json")
    failure = episode_failure(task["id"])
    public.update(episode_failed=bool(failure), episode_failure_reason=failure)
    if condition is not None:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
