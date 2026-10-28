from __future__ import annotations

import copy
import hashlib
import math
import random
from functools import lru_cache
from typing import Any


MECHANIC_ID = "circle_limit_twist_nonrealtime"
# Keep corresponding seeds equivalent to the evaluated V2 donor. The namespace
# changes only in the public contract and dynamic loader identity.
PUZZLE_SEED_MECHANIC_ID = "circle_limit_twist_v2"
SIDES = 7
DEFAULTS = {"face_count": 15, "scramble_length": 8, "move_budget": 16, "flow_amplitude": 0.76, "flow_span_ms": 1800, "activation_radius": 0.16}
ACTIVE_TILE_ORDER = (0, 1, 2, 3, 4, 5, 6, 7, 10, 20, 16, 25, 13, 22, 28)
PALETTE = (
    ("#e84b35", "#ffb199"),
    ("#f5a623", "#ffe08a"),
    ("#f5de51", "#fff6aa"),
    ("#95c94b", "#d9f59c"),
    ("#25a985", "#8fe1cc"),
    ("#35aeca", "#9ce8f6"),
    ("#4678d3", "#a8c5ff"),
    ("#7657c9", "#c5afff"),
    ("#b14eaa", "#eca7e5"),
    ("#d95079", "#ffadc3"),
    ("#d66b32", "#ffbd8b"),
    ("#9b7043", "#e5bd82"),
    ("#617f42", "#b8d995"),
    ("#318c9d", "#a1dae3"),
    ("#9a577d", "#dfacd0"),
)


def _seed(seed: str) -> int:
    digest = hashlib.sha256(f"{seed}|{PUZZLE_SEED_MECHANIC_ID}|v1".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _centroid(polygon: list[complex]) -> complex:
    twice_area = 0.0
    x_sum = 0.0
    y_sum = 0.0
    for first, second in zip(polygon, polygon[1:] + polygon[:1]):
        cross = first.real * second.imag - second.real * first.imag
        twice_area += cross
        x_sum += (first.real + second.real) * cross
        y_sum += (first.imag + second.imag) * cross
    if abs(twice_area) < 1e-12:
        return sum(polygon) / len(polygon)
    return complex(x_sum / (3.0 * twice_area), y_sum / (3.0 * twice_area))


def _reflect_point(point: complex, first: complex, second: complex) -> complex:
    # A Poincare geodesic is a Euclidean circle orthogonal to the unit disc.
    # Reflection in that circle is a hyperbolic reflection. Diameters use the
    # limiting line-reflection form.
    a11, a12 = first.real, first.imag
    a21, a22 = second.real, second.imag
    b1 = (abs(first) ** 2 + 1.0) / 2.0
    b2 = (abs(second) ** 2 + 1.0) / 2.0
    determinant = a11 * a22 - a12 * a21
    if abs(determinant) < 1e-10:
        midpoint = first + second
        angle = math.atan2(midpoint.imag, midpoint.real)
        return complex(math.cos(2.0 * angle), math.sin(2.0 * angle)) * point.conjugate()
    center = complex(
        (b1 * a22 - a12 * b2) / determinant,
        (a11 * b2 - b1 * a21) / determinant,
    )
    radius_squared = abs(center) ** 2 - 1.0
    delta = point - center
    return center + radius_squared * delta / (abs(delta) ** 2)


def _rotate(point: complex, angle: float) -> complex:
    phase = complex(math.cos(angle), math.sin(angle))
    return point * phase


@lru_cache(maxsize=1)
def _base_tiling() -> tuple[dict[str, Any], ...]:
    # For a regular {7,3} tiling, cosh(circumradius) = cot(pi/7)cot(pi/3).
    circumradius = math.acosh(1.0 / (math.tan(math.pi / 7.0) * math.tan(math.pi / 3.0)))
    disc_radius = math.tanh(circumradius / 2.0)
    initial = [
        complex(
            disc_radius * math.cos(-math.pi / 2.0 + 2.0 * math.pi * index / SIDES),
            disc_radius * math.sin(-math.pi / 2.0 + 2.0 * math.pi * index / SIDES),
        )
        for index in range(SIDES)
    ]
    polygons: list[tuple[list[complex], int]] = [(initial, 0)]
    seen = {(0.0, 0.0)}
    frontier = [0]
    for depth in (1, 2, 3):
        next_frontier: list[int] = []
        for tile_index in frontier:
            polygon = polygons[tile_index][0]
            for side in range(SIDES):
                first = polygon[side]
                second = polygon[(side + 1) % SIDES]
                reflected = [_reflect_point(point, first, second) for point in polygon]
                center = _centroid(reflected)
                key = (round(center.real, 5), round(center.imag, 5))
                if key in seen:
                    continue
                seen.add(key)
                polygons.append((reflected, depth))
                next_frontier.append(len(polygons) - 1)
        frontier = next_frontier
    if len(polygons) != 85:
        raise RuntimeError(f"unexpected reflected tiling size: {len(polygons)}")
    result = []
    for tile_id, (polygon, depth) in enumerate(polygons):
        center = _centroid(polygon)
        result.append({
            "id": tile_id,
            "depth": depth,
            "center": [round(center.real, 9), round(center.imag, 9)],
            "vertices": [[round(point.real, 9), round(point.imag, 9)] for point in polygon],
        })
    return tuple(result)


def _hyperbolic_distance(first: complex, second: complex) -> float:
    denominator = (1.0 - abs(first) ** 2) * (1.0 - abs(second) ** 2)
    value = 1.0 + 2.0 * abs(first - second) ** 2 / max(denominator, 1e-12)
    return math.acosh(max(1.0, value))


def _sector_facing(face: dict[str, Any], target: complex) -> int:
    vertices = [complex(*point) for point in face["vertices"]]
    midpoints = [(vertices[index] + vertices[(index + 1) % SIDES]) / 2.0 for index in range(SIDES)]
    return min(range(SIDES), key=lambda index: _hyperbolic_distance(midpoints[index], target))


def _twist_cycles(faces: list[dict[str, Any]]) -> dict[str, dict[str, list[list[int]]]]:
    centers = {int(face["id"]): complex(*face["center"]) for face in faces}
    by_id = {int(face["id"]): face for face in faces}
    result: dict[str, dict[str, list[list[int]]]] = {}
    for face in faces:
        face_id = int(face["id"])
        origin = centers[face_id]
        nearest = sorted(
            (other for other in centers if other != face_id),
            key=lambda other: (_hyperbolic_distance(origin, centers[other]), other),
        )[:SIDES]
        nearest.sort(key=lambda other: math.atan2((centers[other] - origin).imag, (centers[other] - origin).real))
        ring = [[other, _sector_facing(by_id[other], origin)] for other in nearest]
        result[str(face_id)] = {
            "own": [[face_id, sector] for sector in range(SIDES)],
            "ring": ring,
        }
    return result


def apply_twist(
    state: tuple[tuple[int, ...], ...],
    cycles: dict[str, dict[str, list[list[int]]]],
    face_id: int,
    direction: int,
) -> tuple[tuple[int, ...], ...]:
    if direction not in (-1, 1):
        raise ValueError("twist direction must be -1 or 1")
    next_state = [list(face) for face in state]
    for cycle_name in ("own", "ring"):
        positions = cycles[str(face_id)][cycle_name]
        values = [state[face][sector] for face, sector in positions]
        shifted = values[-1:] + values[:-1] if direction == 1 else values[1:] + values[:1]
        for (face, sector), value in zip(positions, shifted):
            next_state[face][sector] = value
    return tuple(tuple(face) for face in next_state)


def is_solved(state: tuple[tuple[int, ...], ...]) -> bool:
    return bool(state) and all(len(set(face)) == 1 for face in state)


def _geometry(face_count: int, rotation_steps: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    angle = rotation_steps * 2.0 * math.pi / SIDES
    active_tiles = ACTIVE_TILE_ORDER[:face_count]
    face_for_tile = {tile_id: face_id for face_id, tile_id in enumerate(active_tiles)}
    tiles: list[dict[str, Any]] = []
    faces: list[dict[str, Any]] = []
    for source in _base_tiling():
        center = _rotate(complex(*source["center"]), angle)
        vertices = [_rotate(complex(*point), angle) for point in source["vertices"]]
        tile = {
            "id": source["id"],
            "depth": source["depth"],
            "center": [round(center.real, 9), round(center.imag, 9)],
            "vertices": [[round(point.real, 9), round(point.imag, 9)] for point in vertices],
            "face_id": face_for_tile.get(source["id"]),
        }
        tiles.append(tile)
        if tile["face_id"] is not None:
            faces.append({
                "id": tile["face_id"],
                "tile_id": tile["id"],
                "center": copy.deepcopy(tile["center"]),
                "vertices": copy.deepcopy(tile["vertices"]),
            })
    faces.sort(key=lambda item: item["id"])
    return tiles, faces


# Local geometry and permutation helpers reuse the evaluated V2 donor's
# reflected {7,3} construction. The counterpart fixes the initial aperture
# transform while retaining the same generated puzzle data.
def generate(task: dict[str, Any], seed: str):
    condition = task.get("_control_condition")
    parameters = {**DEFAULTS, **dict((condition or {}).get("difficulty_parameters") or {})}
    count, length, budget = (int(parameters[k]) for k in ("face_count", "scramble_length", "move_budget"))
    amplitude = float(parameters["flow_amplitude"])
    span = int(parameters["flow_span_ms"])
    aperture = float(parameters["activation_radius"])
    if not 8 <= count <= 15 or not 2 <= length <= 8 or not length <= budget <= 24:
        raise ValueError("invalid face, scramble or budget configuration")
    if not .4 <= amplitude <= .82 or not 1200 <= span <= 10000 or not .1 <= aperture <= .3:
        raise ValueError("invalid flow or aperture configuration")
    rng = random.Random(_seed(str(seed)))
    rotation = rng.randrange(SIDES)
    tiles, faces = _geometry(count, rotation)
    cycles = _twist_cycles(faces)
    palette_values = list(PALETTE)
    rng.shuffle(palette_values)
    palette = [{"id":i, "fill":fill, "glint":glint, "motif":i % 7} for i,(fill,glint) in enumerate(palette_values[:count])]
    solved = tuple(tuple([i]*SIDES) for i in range(count))
    # Distinct, overlapping generators; reject monochrome/one-turn shortcuts.
    for _ in range(256):
        choices = rng.sample(range(count), length)
        if count > 8 and not any(i >= 8 for i in choices):
            choices[-1] = rng.randrange(8, count)
        moves = [{"face_id":i, "direction":rng.choice((-1,1))} for i in choices]
        current = solved
        for move in moves:
            current = apply_twist(current, cycles, move["face_id"], move["direction"])
        if not is_solved(current) and not any(is_solved(apply_twist(current,cycles,i,d)) for i in range(count) for d in (-1,1)):
            break
    else:
        raise RuntimeError("failed to generate a nontrivial scramble")
    puzzle = dict(model="flowing-poincare-aperture-v2", sides=SIDES, tiles=tiles, faces=faces,
        palette=palette, initial_state=[list(face) for face in current], twist_cycles=cycles,
        scramble_length=length, move_budget=budget, activation_radius=aperture,
        twist_settle_ms=1200, motor_reindex_span_ms=1200, play_time_ms=300000,
        flow={"seed":rng.getrandbits(32), "amplitude":amplitude, "span_ms":span},
        rotation_steps=rotation)
    challenge = hashlib.sha256(f"{seed}|{MECHANIC_ID}|{task['id']}|flow-v2".encode()).hexdigest()[:16]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task['id'],
        challenge_id=challenge, prompt="Restore one color per heptagon. Steer the fixed disc and turn only inside the central aperture.",
        submit_label="CERTIFY", asset_manifest="shared_runtime/assets/provenance/circle_limit_twist_v2_v0.json",
        generator={"name":"flowing_heptagonal_permutation_v1", "variant_count":10**12}, puzzle=puzzle)
    truth = dict(mechanic_id=MECHANIC_ID, task_id=task['id'], challenge_id=challenge, seed=str(seed),
        puzzle=copy.deepcopy(puzzle), scramble_moves=moves,
        solution_moves=[{"face_id":m["face_id"],"direction":-m["direction"]} for m in reversed(moves)])
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth
