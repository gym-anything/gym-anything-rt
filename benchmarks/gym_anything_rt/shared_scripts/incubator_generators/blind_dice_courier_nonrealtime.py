"""Source-derived rolling freight through fixed action-settled apertures.

Only this new mechanic is implemented here. The original courier is untouched.
The evaluated V2 world and tracks are retained, but aperture rows are frozen
for this non-real-time counterpart. An accepted roll settles through the
existing finite roll transition; waiting between rolls does not move a gate.
No solution route is delivered to the screenshot-only player.
"""
from __future__ import annotations

import copy
import hashlib
import random
from collections import deque

MECHANIC_ID = "blind_dice_courier_nonrealtime"
REVISION = "fixed-apertures-1"
DONOR_MECHANIC_ID = "blind_dice_courier_v2"
DONOR_REVISION = "sliding-shutters-2"
FACES = ("top", "bottom", "north", "south", "east", "west")
CANONICAL = (1, 6, 2, 5, 3, 4)
MOVES = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
PROFILES = {
    1: dict(columns=5, rows=5, gate_columns=[2], gap_height=2.55,
            sweep_ms=6000, roll_ms=400, face_count=0, shutters=1,
            orientation_visibility="always", scanner_count=0, pillar_count=0),
    2: dict(columns=7, rows=5, gate_columns=[3], gap_height=2.45,
            sweep_ms=7000, roll_ms=600, face_count=1, shutters=1,
            orientation_visibility="always", scanner_count=0, pillar_count=0),
    3: dict(columns=15, rows=7, gate_columns=[3, 7, 11], gap_height=2.30,
            sweep_ms=9000, roll_ms=900, face_count=1, shutters=1,
            orientation_visibility="scanners", scanner_count=3, pillar_count=2),
    4: dict(columns=15, rows=7, gate_columns=[3, 7, 11], gap_height=2.25,
            sweep_ms=8500, roll_ms=900, face_count=2, shutters=1,
            orientation_visibility="scanners", scanner_count=2, pillar_count=3),
    5: dict(columns=15, rows=7, gate_columns=[3, 7, 11], gap_height=2.15,
            sweep_ms=8000, roll_ms=900, face_count=2, shutters=2,
            orientation_visibility="scanners", scanner_count=1, pillar_count=4),
}


def roll(faces, direction):
    t, b, n, s, e, w = faces
    return {"N": (s, n, t, b, e, w), "S": (n, s, b, t, e, w),
            "E": (w, e, n, s, t, b), "W": (e, w, n, s, b, t)}[direction]


def orientations():
    found = {CANONICAL}
    queue = [CANONICAL]
    for faces in queue:
        for direction in MOVES:
            candidate = roll(faces, direction)
            if candidate not in found:
                found.add(candidate)
                queue.append(candidate)
    return queue


def static_route(world, initial):
    """Find a valid orientation route before freezing aperture rows."""
    start, goal = tuple(world["start"]), tuple(world["goal"])
    blocked = {tuple(p) for p in world["pillars"]}
    gates = {g["column"]: g for g in world["gates"]}
    root = (start, tuple(initial))
    queue, parent = deque([root]), {root: None}
    final = None
    while queue:
        point, faces = queue.popleft()
        if point == goal:
            final = (point, faces)
            break
        for direction, (dx, dy) in MOVES.items():
            # The proof route leaves each narrow gate straight away. Other
            # physically valid routes remain legal in the actual mechanic.
            if point[0] in gates and dy:
                continue
            target = (point[0] + dx, point[1] + dy)
            if not (0 <= target[0] < world["columns"] and 0 <= target[1] < world["rows"]) or target in blocked:
                continue
            changed = roll(faces, direction)
            gate = gates.get(target[0])
            if gate and not 1 <= target[1] <= world["rows"]-2:
                continue
            if gate and point[0] != target[0]:
                if (gate.get("required_top") is not None and changed[0] != gate["required_top"]) or (gate.get("required_east") is not None and changed[4] != gate["required_east"]):
                    continue
            node = (target, changed)
            if node not in parent:
                parent[node] = ((point, faces), direction)
                queue.append(node)
    if final is None:
        raise ValueError("unreachable orientation-gate course")
    path = []
    while parent[final] is not None:
        final, direction = parent[final]
        path.append(direction)
    return list(reversed(path))


def fixed_gate_rows(world, route):
    """Choose the visible fixed opening row from the valid route geometry.

    This is generation-time solvability repair, not a player-facing solution:
    the route is kept only in truth and the browser renders the resulting
    fixed apertures as ordinary visible obstacles.
    """
    gates = {gate["column"]: gate for gate in world["gates"]}
    rows = {}
    position = list(world["start"])
    for direction in route:
        dx, dy = MOVES[direction]
        target = [position[0] + dx, position[1] + dy]
        gate = gates.get(target[0])
        if gate is not None and position[0] != target[0]:
            rows[gate["id"]] = round(float(target[1]), 6)
        position = target
    if set(rows) != {gate["id"] for gate in world["gates"]}:
        raise ValueError("orientation route did not cross every gate")
    return rows


def _track(rng, rows, span):
    """Nonperiodic C1 sweeps; the UI shows both upcoming endpoints and durations."""
    a = rng.uniform(.85, rows - 1.85)
    start = -rng.randrange(span)
    result = []
    for _ in range(90):
        choices = [rng.uniform(.85, rows - 1.85) for _ in range(50)]
        b = next((v for v in choices if abs(v - a) >= 1.25), max(choices, key=lambda v: abs(v-a)))
        duration = rng.randrange(span, int(span * 1.45), 10)
        result.append(dict(start_ms=start, duration_ms=duration, a=round(a, 6), b=round(b, 6)))
        start += duration
        a = b
    return result


def generate(task, seed):
    condition = task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition")
    level = int((condition or {}).get("difficulty", 5))
    if level not in PROFILES:
        raise ValueError("courier difficulty must be 1 through 5")
    parameters = copy.deepcopy(PROFILES[level])
    if condition:
        if condition.get("interaction") not in ("full", "simplified"):
            raise ValueError("courier interaction must be full or simplified")
        if condition.get("difficulty_parameters") != parameters:
            raise ValueError("courier profile parameters differ from the implemented contract")
    # Keep corresponding seeds byte-for-byte equivalent to the evaluated V2
    # puzzle before applying the explicitly documented timing exception.
    rng = random.Random(hashlib.sha256(f"{seed}|{DONOR_MECHANIC_ID}|d{level}|{DONOR_REVISION}".encode()).digest())
    initial = rng.choice(orientations())
    cols, rows = parameters["columns"], parameters["rows"]
    start, goal = [0, rng.randrange(1, rows-1)], [cols-1, rng.randrange(1, rows-1)]
    if level == 1:
        start, goal = [1, 2], [3, 2]
    scanner_columns = [column - 2 for column in parameters["gate_columns"][:parameters["scanner_count"]]]
    scanners = [[column, rng.randrange(1, rows-1)] for column in scanner_columns]
    candidates = [[x, y] for x in range(cols) for y in range(1, rows-1)
                  if x not in {0, cols-1, *parameters["gate_columns"],
                               *(c-1 for c in parameters["gate_columns"]),
                               *(c+1 for c in parameters["gate_columns"])}
                  and [x, y] not in scanners]
    pillars = rng.sample(candidates, parameters["pillar_count"])
    gates = []
    for index, column in enumerate(parameters["gate_columns"]):
        faces = rng.choice(orientations())
        gate = dict(id=f"gate-{index+1}", column=column,
                    required_top=faces[0] if parameters["face_count"] else None, gap_height=parameters["gap_height"],
                    track=_track(rng, rows, parameters["sweep_ms"]),
                    slats=[dict(x=column, offset_ms=0)] if parameters["shutters"] == 1
                    else [dict(x=column-.12, offset_ms=0), dict(x=column+.12, offset_ms=500)],
                    color=["#f4bd66", "#68dcca", "#d6a0f2"][index])
        if parameters["face_count"] == 2:
            gate["required_east"] = faces[4]
        gates.append(gate)
    world = dict(columns=cols, rows=rows, start=start, goal=goal, pillars=pillars,
                 scanners=scanners, gates=gates, roll_ms=parameters["roll_ms"], tick_ms=10,
                 orientation_visibility=parameters["orientation_visibility"],
                 play_time_ms=360000, cube_side=1.0, slat_thickness=.035)
    # A random pillar arrangement can remove the local cube reorientation
    # paths. Resample terrain rather than emit an unsolvable challenge; every
    # returned world retains the declared pillar count and gate requirements.
    for _ in range(128):
        try:
            route = static_route(world, initial)
            break
        except ValueError:
            world["pillars"] = rng.sample(candidates, parameters["pillar_count"])
    else:
        raise RuntimeError("unable to generate a reachable orientation-gate course")
    rows = fixed_gate_rows(world, route)
    for gate in world["gates"]:
        gate["static_y"] = rows[gate["id"]]
    world["timing_contract"] = "fixed_apertures_action_settled_rolls"
    task_id = task.get("id", "blind_dice_courier_nonrealtime_seed_0001@0.1")
    challenge = hashlib.sha256(f"{seed}|{DONOR_MECHANIC_ID}|d{level}|{DONOR_REVISION}".encode()).hexdigest()[:16]
    if level <= 2:
        challenge = hashlib.sha256(f"{challenge}|difficulty-repair-20261006".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task_id,
                  challenge_id=challenge, revision=REVISION, world=world,
                  initial_orientation=list(initial), prompt="Roll sealed freight through fixed action-settled face gates.",
                  asset_manifest="shared_runtime/assets/provenance/blind_dice_courier_v2_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18),
                  source_anchors=["nextgen-captchas-benchmark/Dice_Roll_Path", "CAPR-025"],
                  single_attempt=True)
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), static_orientation_route=route,
                 oracle="benchmarks.gym_anything_rt.solvers.blind_dice_courier_nonrealtime:solve")
    return public, truth
