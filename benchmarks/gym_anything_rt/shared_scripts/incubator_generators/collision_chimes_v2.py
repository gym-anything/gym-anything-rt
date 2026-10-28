"""Otomata-derived live wall resonators; all generation is interaction-independent."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random

MECHANIC_ID = "collision_chimes_v2"
REVISION = "drifting-wall-pulses-v2-strike"
WORLD_RANDOMIZATION = "drifting-wall-pulses-v1"
SIDES = ("top", "right", "bottom", "left")
DELTAS = ((-1, 0), (0, 1), (1, 0), (0, -1))
PROFILES = {
    1: dict(cell_count=2, beat_ms=2600, beats=28, note_count=5, flight_ms=6400,
            pickup_width=2.1, pickup_speed=6.0, drift=2.8, drift_span_ms=4200, pickup_depth_px=24),
    2: dict(cell_count=3, beat_ms=2350, beats=30, note_count=8, flight_ms=6000,
            pickup_width=1.85, pickup_speed=6.0, drift=3.0, drift_span_ms=4000, pickup_depth_px=24),
    3: dict(cell_count=4, beat_ms=2100, beats=28, note_count=12, flight_ms=5600,
            pickup_width=1.6, pickup_speed=6.0, drift=3.2, drift_span_ms=3800, pickup_depth_px=24),
    4: dict(cell_count=5, beat_ms=1850, beats=30, note_count=15, flight_ms=5000,
            pickup_width=1.35, pickup_speed=6.0, drift=3.4, drift_span_ms=3600, pickup_depth_px=24),
    5: dict(cell_count=6, beat_ms=1650, beats=32, note_count=18, flight_ms=4400,
            pickup_width=1.15, pickup_speed=6.0, drift=3.6, drift_span_ms=3400, pickup_depth_px=24),
}


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(seed, t_ms, span):
    u = max(0, t_ms) / span
    i, f = math.floor(u), u % 1
    a, b = noise(seed, i), noise(seed, i + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def pulse_position(world, note, time):
    """Continuous rail reflection, with no discontinuous jumps or periodic replay."""
    p = world["parameters"]
    raw = note["slot"] + .5 + p["drift"] * (
        motion(note["drift_seed"], time, p["drift_span_ms"])
        - motion(note["drift_seed"], note["born_ms"], p["drift_span_ms"]))
    # Rail end stops reflect the same visible bead; there is no hidden wrap.
    width = world["grid_size"] - 1
    folded = (raw - .5) % (2 * width)
    return .5 + (folded if folded <= width else 2 * width - folded)


def cellular_film(cells, size, beats):
    state = copy.deepcopy(cells)
    frames, wall_hits, encounters = [copy.deepcopy(state)], [], 0
    for beat in range(1, beats + 1):
        occupied = {(c["row"], c["col"]) for c in state}
        destinations = [(c["row"] + DELTAS[c["direction"]][0],
                         c["col"] + DELTAS[c["direction"]][1]) for c in state]
        counts = {x: destinations.count(x) for x in destinations}
        fresh = []
        for c, dest in zip(state, destinations):
            updated = dict(c)
            if not (0 <= dest[0] < size and 0 <= dest[1] < size):
                side = SIDES[c["direction"]]
                wall_hits.append(dict(beat=beat, side=side, slot=c["col"] if side in
                                      ("top", "bottom") else c["row"], cell_id=c["id"]))
                updated["direction"] = (c["direction"] + 2) % 4
            elif dest in occupied or counts[dest] > 1:
                updated["direction"] = (c["direction"] + 1) % 4
                encounters += 1
            else:
                updated.update(row=dest[0], col=dest[1])
            fresh.append(updated)
        state = fresh
        frames.append(copy.deepcopy(state))
    return frames, wall_hits, encounters


def static_pickups_possible(world):
    half = world["parameters"]["pickup_width"] / 2
    return all(max([pulse_position(world, n, n["deadline_ms"]) - half
                    for n in world["notes"] if n["side"] == side] or [0]) <=
               min([pulse_position(world, n, n["deadline_ms"]) + half
                    for n in world["notes"] if n["side"] == side] or [world["grid_size"]])
               for side in SIDES)


def reachable(world):
    """A generous physical reserve between incompatible same-wall arrivals.

    This construction predicate is not a grader action quota. Closely spaced
    arrivals are allowed when their visible capture intervals overlap.
    """
    p = world["parameters"]
    for side in SIDES:
        notes = [n for n in world["notes"] if n["side"] == side]
        groups = {}
        for note in notes:
            groups.setdefault(note["deadline_ms"], []).append(
                pulse_position(world, note, note["deadline_ms"]))
        # Adjacent pairs do not establish one common capture interval for
        # three or more simultaneous pulses. Reserve visible aiming room for
        # the whole group, including native pointer quantization.
        if any(max(xs) - min(xs) > p["pickup_width"] * .82 for xs in groups.values()):
            return False
        # A 400-ms paused observation must expose a usable simultaneous catch,
        # rather than only a common interval at an inaccessible instant. Keep
        # a visible aiming reserve throughout the last 600 ms of each group.
        for end in groups:
            group = [n for n in notes if n["deadline_ms"] == end]
            if len(group) < 2:
                continue
            for time in range(int(end) - 600, int(end) + 1, 10):
                xs = [pulse_position(world, n, time) for n in group]
                if max(xs) - min(xs) > p["pickup_width"] * .65:
                    return False
        for a, b in zip(notes, notes[1:]):
            distance = abs(pulse_position(world, a, a["deadline_ms"]) -
                           pulse_position(world, b, b["deadline_ms"]))
            required = max(0, distance - p["pickup_width"] * .82) / p["pickup_speed"] * 1000
            if distance > p["pickup_width"] * .82 and b["deadline_ms"] - a["deadline_ms"] < required + 1000:
                return False
    return True


def generate(task, seed):
    condition = task.get("_control_condition") or task.get("metadata", {}).get("control_condition")
    level = int((condition or {}).get("difficulty", 5))
    p = {**PROFILES[level], **(condition or {}).get("difficulty_parameters", {})}
    # Profiles are explicit; reject accidental unsupported changes rather than degrade.
    if p != PROFILES[level]:
        raise ValueError("unsupported Collision Chimes V2 profile")
    rng = random.Random(hashlib.sha256(f"{MECHANIC_ID}|{WORLD_RANDOMIZATION}|{seed}|{level}".encode()).digest())
    size = 9
    for attempt in range(20000):
        positions = rng.sample([(r, c) for r in range(size) for c in range(size)], p["cell_count"])
        cells = [dict(id=i, row=r, col=c, direction=rng.randrange(4))
                 for i, (r, c) in enumerate(positions)]
        frames, hits, collisions = cellular_film(cells, size, p["beats"])
        if len(hits) < p["note_count"] or collisions < (1 if level < 3 else 3):
            continue
        notes = []
        for i, hit in enumerate(hits[:p["note_count"]]):
            born = hit["beat"] * p["beat_ms"]
            notes.append(dict(hit, id=i, born_ms=born, deadline_ms=born + p["flight_ms"],
                              drift_seed=rng.getrandbits(32)))
        world = dict(grid_size=size, parameters=p, cells=cells, notes=notes)
        if len({n["side"] for n in notes}) < 3 or static_pickups_possible(world) or not reachable(world):
            continue
        break
    else:
        raise ValueError("could not construct reachable, non-parkable chimes")
    digest = hashlib.sha256(json.dumps(world, sort_keys=True).encode()).hexdigest()[:20]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task["id"], challenge_id=digest, world=copy.deepcopy(world),
                  prompt="Catch every pulse: steer each brass resonator and STRIKE while the pulse centre is inside. One attempt only: a wrong strike, escaped pulse or END ATTEMPT ends this episode.",
                  revision=REVISION, source_anchors=["ART-271"],
                  asset_manifest="shared_runtime/assets/provenance/collision_chimes_v2_v0.json",
                  generator=dict(name=REVISION))
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
    truth = copy.deepcopy(public)
    truth.update(seed=seed, generation_attempt=attempt)
    return public, truth
