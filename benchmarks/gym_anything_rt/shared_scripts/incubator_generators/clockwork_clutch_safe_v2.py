from __future__ import annotations

import copy
import hashlib
import random
from typing import Any


# Clockwork Clutch Safe V2
# ------------------------
# Provenance: additive V2 of the existing `clockwork_clutch_safe` mechanic
# (shared_scripts/incubator_generators/clockwork_clutch_safe.py, which
# delegates to `_interaction_vii_viii_common.py::_clutch`). The V1 world
# (coupled shafts, gear ratios, active-set load redistribution, release
# windows, phase tolerance, difficulty telemetry/re-engagement flags) is
# reproduced here. The master drive no
# longer turns every engaged shaft at an exactly constant angular speed
# between release events. Its instantaneous speed is multiplied every tick
# by a seeded, bounded, smoothly-interpolated, non-periodic "wobble" curve
# (see `_wobble_anchors` / `_wobble_at` below), so a fixed linear
# extrapolation from a few observed frames no longer predicts later ticks.
# Once started, the drive runs continuously until the trial ends.
#
# This file, its browser mechanic, grader, and solver are new and do not
# modify `clockwork_clutch_safe` or any file it depends on.

MECHANIC_ID = "clockwork_clutch_safe_v2"

CLUTCH_RATIO_PROFILES = {
    "single": (
        (1.0,),
    ),
    "paired": (
        (1.0, -1.25),
        (1.25, -1.0),
        (1.5, -1.25),
    ),
    "legacy_four": (
        (1.0, -1.25, 1.5, -1.75),
        (1.25, -1.0, 1.75, -1.5),
        (1.5, -1.75, 1.0, -1.25),
    ),
    "wide_four": (
        (1.25, -1.5, 1.75, -2.0),
        (1.5, -1.25, 2.0, -1.75),
        (1.75, -2.0, 1.25, -1.5),
    ),
}


def _seed(seed: str) -> int:
    return int(hashlib.sha256(f"{seed}|{MECHANIC_ID}".encode()).hexdigest()[:16], 16)


def _wobble_anchors(
    rng: random.Random,
    *,
    max_ticks: int,
    min_mult: float,
    max_mult: float,
    segment_min_ticks: int,
    segment_max_ticks: int,
) -> list[dict[str, float]]:
    """Build a seeded, bounded, non-periodic drive-speed curve.

    Anchors are generated on demand from the seeded stream until the tick
    axis is fully covered through ``max_ticks``; nothing is drawn from a
    fixed-length table that could be exhausted and looped. Consecutive
    anchors are spaced by an independently random number of ticks
    (``segment_min_ticks``..``segment_max_ticks``), so the resulting curve
    has irregular, non-periodic intervals. Each anchor's multiplier is an
    independent draw within ``[min_mult, max_mult]``. The curve is
    evaluated with smootherstep interpolation between anchors, which is
    zero-derivative at every anchor, so speed changes are smooth rather
    than sudden jumps.
    """
    anchors = [{"tick": 0, "mult": 1.0}]
    tick = 0
    while tick < max_ticks:
        tick += rng.randint(segment_min_ticks, segment_max_ticks)
        anchors.append({"tick": tick, "mult": round(rng.uniform(min_mult, max_mult), 4)})
    return anchors


def _wobble_at(tick: int, anchors: list[dict[str, Any]]) -> float:
    if not anchors:
        return 1.0
    if tick <= anchors[0]["tick"]:
        return float(anchors[0]["mult"])
    for first, second in zip(anchors, anchors[1:]):
        if first["tick"] <= tick <= second["tick"]:
            span = second["tick"] - first["tick"]
            t = 0.0 if span <= 0 else (tick - first["tick"]) / span
            eased = t * t * t * (t * (t * 6 - 15) + 10)
            return float(first["mult"]) + (float(second["mult"]) - float(first["mult"])) * eased
    return float(anchors[-1]["mult"])


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed(seed))
    task_id = str(task.get("id") or f"{MECHANIC_ID}_seed_0001@0.1")
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})

    challenge_id = hashlib.sha256(
        (f"{seed}|{MECHANIC_ID}|d{condition['difficulty']}|{task.get('id')}" if condition else f"{seed}|{MECHANIC_ID}").encode()
    ).hexdigest()[:12]

    public: dict[str, Any] = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "asset_manifest": "shared_runtime/assets/provenance/interaction_vii_viii_v0.json",
        "prompt": task.get("natural_language") or "Complete the physical verification.",
    }
    truth: dict[str, Any] = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "seed": seed,
    }

    shaft_count = int(parameters.get("shaft_count", 4))
    ratio_profile = str(parameters.get("ratio_profile", "legacy_four"))
    ratio_bank = CLUTCH_RATIO_PROFILES.get(ratio_profile)
    if not 1 <= shaft_count <= 4 or ratio_bank is None or any(len(profile) != shaft_count for profile in ratio_bank):
        raise ValueError("clockwork shaft count and ratio profile do not agree")
    ratios = rng.choice(ratio_bank)

    raw_ranges = parameters.get(
        "release_tick_ranges",
        ((31, 38), (56, 65), (84, 94), (116, 128)),
    )
    if not isinstance(raw_ranges, (list, tuple)) or len(raw_ranges) != shaft_count:
        raise ValueError("clockwork release window count does not match the shaft count")
    release_tick_ranges: list[tuple[int, int]] = []
    for value in raw_ranges:
        if not isinstance(value, (list, tuple)) or len(value) != 2 or any(isinstance(item, bool) for item in value):
            raise ValueError("clockwork release window is malformed")
        start, end = int(value[0]), int(value[1])
        if start < 1 or end < start:
            raise ValueError("clockwork release window is inverted")
        release_tick_ranges.append((start, end))
    if any(previous[1] >= following[0] for previous, following in zip(release_tick_ranges, release_tick_ranges[1:])):
        raise ValueError("clockwork release windows must be strictly ordered and disjoint")

    tick_ms = int(parameters.get("tick_ms", 85))
    drive_deg = float(parameters.get("drive_deg_per_tick", 1.8))
    load_numerator = int(parameters.get("load_numerator", 4))
    tolerance = float(parameters.get("phase_tolerance_deg", 13.0))
    max_ticks = int(parameters.get("max_ticks", 170))
    show_angle_readout = parameters.get("show_angle_readout", True)
    show_speed_readout = parameters.get("show_speed_readout", True)
    reengagement_allowed = parameters.get("reengagement_allowed", True)
    wobble_min_mult = float(parameters.get("wobble_min_mult", 0.68))
    wobble_max_mult = float(parameters.get("wobble_max_mult", 1.32))
    wobble_segment_min_ticks = int(parameters.get("wobble_segment_min_ticks", 12))
    wobble_segment_max_ticks = int(parameters.get("wobble_segment_max_ticks", 22))
    if not 50 <= tick_ms <= 200 or not .5 <= drive_deg <= 3.0:
        raise ValueError("clockwork drive timing is outside supported limits")
    if load_numerator != shaft_count or not 3.0 <= tolerance <= 40.0:
        raise ValueError("clockwork load or phase tolerance is outside supported limits")
    if not release_tick_ranges[-1][1] < max_ticks <= 400:
        raise ValueError("clockwork wind limit must follow every release window")
    if any(not isinstance(value, bool) for value in (show_angle_readout, show_speed_readout, reengagement_allowed)):
        raise ValueError("clockwork telemetry and recovery policies must be boolean")
    if not 0.1 <= wobble_min_mult < 1.0 <= wobble_max_mult <= 2.2:
        raise ValueError("clockwork wobble multiplier bounds are outside supported limits")
    if not 2 <= wobble_segment_min_ticks <= wobble_segment_max_ticks <= 60:
        raise ValueError("clockwork wobble segment length is outside supported limits")

    anchors = _wobble_anchors(
        rng,
        max_ticks=max_ticks,
        min_mult=wobble_min_mult,
        max_mult=wobble_max_mult,
        segment_min_ticks=wobble_segment_min_ticks,
        segment_max_ticks=wobble_segment_max_ticks,
    )

    order = list(range(shaft_count))
    rng.shuffle(order)
    moments = [rng.randint(start, end) for start, end in release_tick_ranges]
    release_schedule = sorted(({"tick": tick, "shaft": shaft} for tick, shaft in zip(moments, order)), key=lambda item: item["tick"])
    accumulated = [0.0] * shaft_count
    active = set(range(shaft_count))
    by_tick = {item["tick"]: item["shaft"] for item in release_schedule}
    for tick in range(1, max(moments) + 1):
        wobble = _wobble_at(tick, anchors)
        factor = load_numerator / len(active)
        for shaft in active:
            accumulated[shaft] += ratios[shaft] * drive_deg * wobble * factor
        if tick in by_tick:
            active.remove(by_tick[tick])
    initial = [round((-value) % 360.0, 3) for value in accumulated]

    physics = {
        "tick_ms": tick_ms,
        "drive_can_stop": False,
        "drive_deg_per_tick": drive_deg,
        "load_numerator": load_numerator,
        "phase_tolerance_deg": tolerance,
        "max_ticks": max_ticks,
        "wobble_min_mult": wobble_min_mult,
        "wobble_max_mult": wobble_max_mult,
        "wobble_segment_min_ticks": wobble_segment_min_ticks,
        "wobble_segment_max_ticks": wobble_segment_max_ticks,
        "wobble_anchors": anchors,
    }
    if not show_angle_readout:
        physics["show_angle_readout"] = False
    if not show_speed_readout:
        physics["show_speed_readout"] = False
    if not reengagement_allowed:
        physics["reengagement_allowed"] = False

    public.update({
        "generator": {"name": "wobble_drive_clutch_safe_v2", "variant_count": 10 ** (shaft_count + 8)},
        "shafts": [{"id": f"seal-{i + 1}", "ratio": ratio, "angle_deg": initial[i], "engaged": True} for i, ratio in enumerate(ratios)],
        "physics": physics,
    })
    truth.update({
        "release_schedule": release_schedule,
        "ratios": ratios,
        "initial_angles": initial,
        "physics": public["physics"],
    })
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth
