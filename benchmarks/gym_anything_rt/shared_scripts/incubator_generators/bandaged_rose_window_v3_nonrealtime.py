from __future__ import annotations

import copy
import hashlib
import math
import random
from collections import deque
from functools import lru_cache
from typing import Any


MECHANIC_ID = "bandaged_rose_window_v3_nonrealtime"
# Keep spatial puzzle generation aligned with the frozen V3 donor.  The
# public identity and challenge id remain counterpart-local.
SEED_MECHANIC_ID = "bandaged_rose_window_v3"
DISC_IDS = ("north", "southwest", "southeast")
DISC_SLOTS = (
    (3, 7, 6, 0, 5, 4),
    (3, 10, 9, 1, 8, 7),
    (3, 4, 12, 2, 11, 10),
)
DISC_GEOMETRY = (
    {"id": "north", "label": "NORTH", "center": [500, 190], "radius": 150, "handle_radius": 175, "handle_angle": -60},
    {"id": "southwest", "label": "SOUTHWEST", "center": [405, 355], "radius": 150, "handle_radius": 175, "handle_angle": 120},
    {"id": "southeast", "label": "SOUTHEAST", "center": [595, 355], "radius": 150, "handle_radius": 175, "handle_angle": 60},
)
SLOT_GEOMETRY = (
    [500, 80], [310, 410], [690, 410], [500, 300], [595, 245], [595, 135], [405, 135],
    [405, 245], [310, 300], [405, 465], [500, 410], [595, 465], [690, 300],
)
DEFAULTS = {'scramble_depth': 14, 'collar_speed': 0.46, 'collar_amplitude': 0.4, 'collar_span_ms': 3500, 'notch_half_width': 0.62}
ACTION_WINDOW_TURNS = 14
GLASS = ("#e8b33a", "#54b8c8", "#d76555", "#aa4d86", "#78a85d", "#d5853d", "#557bb3", "#c64b59", "#57a38f", "#a66bb1")


def _seed(seed: str) -> int:
    digest = hashlib.sha256(f"{seed}|{SEED_MECHANIC_ID}|v1".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def legal(state: tuple[int, ...], disc: int) -> bool:
    slots = DISC_SLOTS[disc]
    if state.index(3) not in slots:
        return False
    return all(point == disc or state.index(point) not in slots for point in range(3))


def turn(state: tuple[int, ...], disc: int, direction: int) -> tuple[int, ...]:
    slots = DISC_SLOTS[disc]
    values = [state[index] for index in slots]
    values = values[-1:] + values[:-1] if direction == 1 else values[1:] + values[:1]
    result = list(state)
    for slot, value in zip(slots, values):
        result[slot] = value
    return tuple(result)


@lru_cache(maxsize=1)
def _state_graph() -> tuple[dict[tuple[int, ...], int], dict[tuple[int, ...], tuple[tuple[int, ...], int, int]], dict[int, tuple[tuple[int, ...], ...]]]:
    solved = tuple(range(13))
    distance = {solved: 0}
    parent: dict[tuple[int, ...], tuple[tuple[int, ...], int, int]] = {}
    frontier: dict[int, list[tuple[int, ...]]] = {0: [solved]}
    queue = deque([solved])
    while queue:
        state = queue.popleft()
        depth = distance[state]
        if depth >= 14:
            continue
        for disc in range(3):
            if not legal(state, disc):
                continue
            for direction in (-1, 1):
                nxt = turn(state, disc, direction)
                if nxt in distance:
                    continue
                distance[nxt] = depth + 1
                parent[nxt] = (state, disc, direction)
                frontier.setdefault(depth + 1, []).append(nxt)
                queue.append(nxt)
    frozen = {depth: tuple(states) for depth, states in frontier.items()}
    return distance, parent, frozen


def _solution(state: tuple[int, ...], parent: dict[tuple[int, ...], tuple[tuple[int, ...], int, int]]) -> list[dict[str, Any]]:
    moves: list[dict[str, Any]] = []
    while state != tuple(range(13)):
        previous, disc, direction_from_previous = parent[state]
        moves.append({"disc_id": DISC_IDS[disc], "direction": -direction_from_previous})
        state = previous
    return moves


def _pieces(rng: random.Random) -> list[dict[str, Any]]:
    palette = list(GLASS)
    rng.shuffle(palette)
    pieces = []
    for piece_id in range(13):
        if piece_id < 3:
            kind = "point"
        elif piece_id == 3:
            kind = "heart"
        else:
            kind = "shield"
        pieces.append({
            "id": piece_id,
            "kind": kind,
            "home_disc": DISC_IDS[piece_id] if piece_id < 3 else None,
            "glass": palette[piece_id % len(palette)],
            "motif": (piece_id * 5 + 2) % 7,
        })
    return pieces


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    condition = task.get("_control_condition")
    parameters = {**DEFAULTS, **dict((condition or {}).get("difficulty_parameters") or {})}
    depth = int(parameters["scramble_depth"])
    if not 1 <= depth <= 14:
        raise ValueError("rose scramble depth must be between 1 and 14")
    distance, parent, frontier = _state_graph()
    choices = [state for state in frontier[depth] if sum(not legal(state, disc) for disc in range(3)) >= 1]
    if not choices:
        raise RuntimeError(f"no bandaged rose states at depth {depth}")
    rng = random.Random(_seed(seed))
    initial = choices[rng.randrange(len(choices))]
    pieces = _pieces(rng)
    # Action-triggered fixed layout: all collars remain open while waiting,
    # dragging, or inspecting, then the existing closed-collar consequence is
    # available after the finite action window.  This is independent of the
    # hidden solution path.
    stable_collar_phases = [[0.0, 0.0, 0.0] for _ in range(ACTION_WINDOW_TURNS)]
    stable_collar_phases.append([math.pi, math.pi, math.pi])
    token = f"|d{condition['difficulty']}|{task.get('id')}" if condition else ""
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}|challenge{token}".encode()).hexdigest()[:12]
    contract = {
        "discs": copy.deepcopy(DISC_GEOMETRY),
        "slots": [{"id": index, "center": center} for index, center in enumerate(SLOT_GEOMETRY)],
        "pieces": pieces,
        "initial_state": list(initial),
        "solved_state": list(range(13)),
        "optimal_distance": distance[initial],
        "collars": [{"phase": rng.uniform(-3.14, 3.14), "seed": rng.getrandbits(32), "direction": rng.choice([-1, 1])} for _ in range(3)],
        "collar_speed": float(parameters["collar_speed"]),
        "collar_amplitude": float(parameters["collar_amplitude"]),
        "collar_span_ms": int(parameters["collar_span_ms"]),
        "notch_half_width": float(parameters["notch_half_width"]),
        "stable_collar_phases": stable_collar_phases,
        "cooldown_ms": 1200,
        "play_time_ms": 300000,
    }
    public = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task["id"],
        "challenge_id": challenge_id,
        "prompt": 'Click the conservation patches on the current window to inspect the hidden glass pieces; each exposed piece stays visible when it moves. Restore the thirteen glass pieces to the reference. Start the collars. A disc may turn only when it contains the heart and no foreign point. Turn while its fixed notch straddles the fixed brass pin. The fixed open decision layout stays unchanged while waiting, dragging, holding, or inspecting and advances after each accepted turn; after the finite action window, the closed guard is shown. A closed-collar turn cracks the window. Shape-blocked probes are harmless. Seal only the restored window.',
        "submit_label": "SEAL",
        "asset_manifest": "shared_runtime/assets/provenance/bandaged_rose_window_v3_v0.json",
        "generator": {"name": "exact_bandaged_disc_bfs_v1", "frontier_size": len(frontier[depth]), "variant_count": len(choices)},
        "rose": contract,
    }
    truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task["id"],
        "seed": seed,
        "challenge_id": challenge_id,
        "rose": copy.deepcopy(contract),
        "solution_moves": _solution(initial, parent),
    }
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth
