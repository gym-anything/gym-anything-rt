from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "cloudpost_circuit_nonrealtime"
# The counterpart has no new media.  Keep the donor provenance manifest rather
# than inventing a second asset catalog for a namespace-only extraction.
ASSET_MANIFEST = "shared_runtime/assets/provenance/cloudpost_circuit_v0.json"
DONOR_MECHANIC_ID = "cloudpost_circuit"


PROFILES: dict[int, dict[str, Any]] = {
    1: {
        "target_count": 2,
        "spacing": 126,
        "lateral_span": 30,
        "vertical_span": 22,
        "flight_speed": 1.55,
        "turn_step": 0.34,
        "contact_radius": 19,
        "scenery_count": 8,
        "label": "very_easy",
    },
    2: {
        "target_count": 3,
        "spacing": 112,
        "lateral_span": 46,
        "vertical_span": 34,
        "flight_speed": 1.78,
        "turn_step": 0.30,
        "contact_radius": 16,
        "scenery_count": 12,
        "label": "easy",
    },
    3: {
        "target_count": 4,
        "spacing": 101,
        "lateral_span": 63,
        "vertical_span": 47,
        "flight_speed": 2.05,
        "turn_step": 0.27,
        "contact_radius": 14,
        "scenery_count": 17,
        "label": "medium",
    },
    4: {
        "target_count": 5,
        "spacing": 92,
        "lateral_span": 78,
        "vertical_span": 59,
        "flight_speed": 2.30,
        "turn_step": 0.24,
        "contact_radius": 12,
        "scenery_count": 22,
        "label": "hard",
    },
    5: {
        "target_count": 7,
        "spacing": 80,
        "lateral_span": 96,
        "vertical_span": 72,
        "flight_speed": 2.65,
        "turn_step": 0.21,
        "contact_radius": 10,
        "scenery_count": 30,
        "label": "very_hard",
    },
}


def _seed_int(seed: str) -> int:
    # Namespace changes must not change the generated route.  This lets a
    # donor seed and its counterpart seed retain the same visible world.
    return int(hashlib.sha256(f"{seed}|{DONOR_MECHANIC_ID}".encode()).hexdigest()[:16], 16)


def _challenge_id(seed: str, task: dict[str, Any], condition: dict[str, Any] | None) -> str:
    suffix = "baseline" if condition is None else f"d{condition['difficulty']}|{condition['interaction']}|{task.get('id')}"
    return hashlib.sha256(f"{seed}|{MECHANIC_ID}|{suffix}".encode()).hexdigest()[:12]


def _profile(task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    metadata = task.get("metadata") or {}
    raw = metadata.get("control_condition")
    condition = copy.deepcopy(raw) if isinstance(raw, dict) and raw else None
    if condition is None:
        return dict(PROFILES[4]), None
    difficulty = int(condition.get("difficulty"))
    if difficulty not in PROFILES:
        raise ValueError("Cloudpost difficulty must be 1 through 5")
    values = dict(PROFILES[difficulty])
    values.update(dict(condition.get("difficulty_parameters") or {}))
    return values, condition


def _target_position(
    rng: random.Random,
    index: int,
    values: dict[str, Any],
    previous: tuple[float, float] | None = None,
) -> tuple[float, float, float]:
    # The first seal is deliberately allowed to start outside the initial
    # camera frustum.  Every point remains within the steerable yaw/pitch cone.
    spacing = float(values["spacing"])
    z = 68.0 + index * spacing + rng.uniform(-8.0, 8.0)
    lateral = float(values["lateral_span"])
    vertical = float(values["vertical_span"])
    if previous is None:
        x = rng.uniform(-lateral, lateral)
        y = rng.uniform(-vertical, vertical)
    else:
        # Keep successive waypoints inside the plane's turn envelope.  The
        # route still changes heading and depth, but never asks a human to
        # reverse into an unreachable lateral/vertical corner in one tick.
        x = max(-lateral, min(lateral, previous[0] * 0.35 + rng.uniform(-lateral * 0.18, lateral * 0.18)))
        y = max(-vertical, min(vertical, previous[1] * 0.35 + rng.uniform(-vertical * 0.18, vertical * 0.18)))
    if index == 0 and abs(x) < lateral * 0.62:
        x = math.copysign(lateral * 0.86, x or 1.0)
    return round(x, 3), round(y, 3), round(z, 3)


def generate(task: dict[str, Any], seed: str):
    values, condition = _profile(task)
    rng = random.Random(_seed_int(seed))
    task_id = str(task.get("id") or f"{MECHANIC_ID}_seed_0001@0.2")
    challenge_id = _challenge_id(seed, task, condition)
    target_count = int(values["target_count"])
    if not 2 <= target_count <= 8:
        raise ValueError("Cloudpost target count is outside the supported range")

    targets: list[dict[str, Any]] = []
    hues = ("coral", "citron", "aqua", "violet", "rose", "mint", "amber")
    symbols = ("✦", "◇", "✧", "⬡", "✺", "✥", "◈")
    previous_xy: tuple[float, float] | None = None
    for index in range(target_count):
        x, y, z = _target_position(rng, index, values, previous_xy)
        previous_xy = (x, y)
        target_id = f"seal-{index + 1}-{hashlib.sha1(f'{seed}|seal|{index}'.encode()).hexdigest()[:7]}"
        targets.append({
            "id": target_id,
            "x": x,
            "y": y,
            "z": z,
            "radius": int(values["contact_radius"]),
            "hue": hues[index % len(hues)],
            "symbol": symbols[index % len(symbols)],
        })

    scenery: list[dict[str, Any]] = []
    for index in range(int(values["scenery_count"])):
        z = 42.0 + index * max(47.0, float(values["spacing"]) * 0.62) + rng.uniform(-35.0, 35.0)
        scenery.append({
            "id": f"cloud-{index + 1}",
            "x": round(rng.uniform(-260, 260), 2),
            "y": round(rng.uniform(-145, 150), 2),
            "z": round(max(24.0, z), 2),
            "scale": round(rng.uniform(0.65, 1.55), 2),
            "kind": rng.choice(("island", "cloudbank", "spire", "balloon")),
            "tint": rng.randrange(6),
        })

    physics = {
        "tick_ms": 40,
        "action_ticks": 2,
        "flight_speed": float(values["flight_speed"]),
        "turn_step": float(values["turn_step"]),
        "max_yaw": 1.06,
        "max_pitch": 0.68,
        "world_x": 265.0,
        "world_y": 188.0,
        "world_z": round(targets[-1]["z"] + 130.0, 2),
        "contact_radius": int(values["contact_radius"]),
    }
    public = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Fly the airmail plane through every floating delivery seal.",
        "submit_label": "CLOSE FLIGHT LOG",
        "asset_manifest": ASSET_MANIFEST,
        "generator": {
            "name": "cloudpost_circuit_nonrealtime_procedural_v1",
            "variant_count": 10**15,
            "route_contract": "world-space-plane-seal-contact",
        },
        "canvas": {"width": 920, "height": 540},
        "palette": rng.randrange(6),
        "targets": targets,
        "scenery": scenery,
        "physics": physics,
        "initial_plane": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0},
        "remaining_count": target_count,
    }
    truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "targets": targets,
        "physics": physics,
        "control_condition": copy.deepcopy(condition),
        "baseline_interaction": "full",
    }
    if condition is not None:
        public["control_condition"] = copy.deepcopy(condition)
    return public, truth
