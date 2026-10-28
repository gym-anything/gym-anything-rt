from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from collections import deque
from typing import Any


MECHANIC_ID = "tiny_fps_customs_v2"
CREATURE_RADIUS = 0.27
PLAYER_RADIUS = 0.18
MOVE_STEP = 0.25
AMMO = 11
WANTED_COUNT = 4
MAP_WIDTH = 17
MAP_HEIGHT = 13

_PALETTES = (
    ("verdigris", "#43d6b1", "#123f43", "#ffe26c"),
    ("ember", "#ff6b45", "#5a1929", "#ffe9b0"),
    ("ultraviolet", "#a98cff", "#30205f", "#76ffe4"),
    ("brine", "#59b8ff", "#15385f", "#ffb85c"),
    ("lichen", "#b2dc54", "#344b18", "#f8f1cb"),
    ("orchid", "#f06eb7", "#53234b", "#9effee"),
)
_HORNS = ("fork", "spiral", "blade", "antenna")
_MARKS = ("ring", "chevron", "triple-dot", "split-bar")
_STRIPES = ("shoulder", "belly", "none")


def _seed_int(seed: str, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _challenge_id(seed: str, difficulty: int | None = None) -> str:
    # L4 is the historical reference condition, so its visible manifest ID is
    # deliberately the same as the uncontrolled task for a fixed seed. The
    # other profiles need distinct identities because their generated worlds
    # differ while retaining the same runtime seed.
    suffix = "" if difficulty in {None, 4} else f"|difficulty-{difficulty}"
    return hashlib.sha256(f"{seed}|{MECHANIC_ID}|v2{suffix}".encode("utf-8")).hexdigest()[:14]


def _creature_id(seed: str, index: int) -> str:
    return f"traveller-{hashlib.sha256(f'{seed}|creature|{index}'.encode('utf-8')).hexdigest()[:10]}"


def _open_cells(rows: tuple[str, ...]) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y, row in enumerate(rows)
        for x, value in enumerate(row)
        if value == "."
    }


def _maze_layout(
    rng: random.Random,
    width: int = MAP_WIDTH,
    height: int = MAP_HEIGHT,
    spawn_count: int = 12,
) -> tuple[tuple[str, ...], tuple[int, int], tuple[tuple[int, int], ...]]:
    grid = [["#" for _ in range(width)] for _ in range(height)]
    start = (1, 1)
    grid[start[1]][start[0]] = "."
    visited = {start}
    stack = [start]
    while stack:
        current = stack[-1]
        directions = [(2, 0), (0, 2), (-2, 0), (0, -2)]
        rng.shuffle(directions)
        candidates = []
        for dx, dy in directions:
            target = (current[0] + dx, current[1] + dy)
            if 1 <= target[0] < width - 1 and 1 <= target[1] < height - 1 and target not in visited:
                candidates.append((target, (current[0] + dx // 2, current[1] + dy // 2)))
        if not candidates:
            stack.pop()
            continue
        target, between = rng.choice(candidates)
        grid[between[1]][between[0]] = "."
        grid[target[1]][target[0]] = "."
        visited.add(target)
        stack.append(target)
    rows = tuple("".join(row) for row in grid)
    open_cells = _open_cells(rows)
    queue: deque[tuple[int, int]] = deque([start])
    distance = {start: 0}
    while queue:
        cell = queue.popleft()
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            candidate = (cell[0] + dx, cell[1] + dy)
            if candidate in open_cells and candidate not in distance:
                distance[candidate] = distance[cell] + 1
                queue.append(candidate)
    nodes = [cell for cell in visited if cell != start and distance.get(cell, 0) >= 7]
    nodes.sort(key=lambda cell: distance[cell], reverse=True)
    pool = nodes[: min(30, len(nodes))]
    if len(pool) < 12:
        pool = nodes
    if len(pool) < spawn_count:
        raise AssertionError("generated maze has too few distant traveller cells")
    spawn_cells = tuple(rng.sample(pool, spawn_count))
    return rows, start, spawn_cells


def _layout_variant(
    rows: tuple[str, ...], start: tuple[int, int], spawn_cells: tuple[tuple[int, int], ...], variant: str,
) -> tuple[tuple[str, ...], tuple[int, int], int, tuple[tuple[int, int], ...]]:
    width = len(rows[0])
    height = len(rows)

    def transform_cell(cell: tuple[int, int]) -> tuple[int, int]:
        x, y = cell
        if variant == "mirror_x":
            return width - 1 - x, y
        if variant == "mirror_y":
            return x, height - 1 - y
        if variant == "rotate_180":
            return width - 1 - x, height - 1 - y
        return x, y

    if variant == "mirror_x":
        transformed = tuple(row[::-1] for row in rows)
    elif variant == "mirror_y":
        transformed = tuple(reversed(rows))
    elif variant == "rotate_180":
        transformed = tuple(row[::-1] for row in reversed(rows))
    else:
        transformed = rows
    transformed_start = transform_cell(start)
    first_neighbor = next(
        (candidate for candidate in ((transformed_start[0] + 1, transformed_start[1]), (transformed_start[0], transformed_start[1] + 1), (transformed_start[0] - 1, transformed_start[1]), (transformed_start[0], transformed_start[1] - 1)) if transformed[candidate[1]][candidate[0]] == "."),
        None,
    )
    if first_neighbor is None:
        raise AssertionError("generated maze start has no corridor")
    angle_mdeg = _angle_mdeg(transformed_start, first_neighbor)
    return transformed, transformed_start, angle_mdeg, tuple(transform_cell(cell) for cell in spawn_cells)


def _reachable(start: tuple[int, int], open_cells: set[tuple[int, int]]) -> set[tuple[int, int]]:
    queue: deque[tuple[int, int]] = deque([start])
    visited = {start}
    while queue:
        cell = queue.popleft()
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            candidate = (cell[0] + dx, cell[1] + dy)
            if candidate in open_cells and candidate not in visited:
                visited.add(candidate)
                queue.append(candidate)
    return visited


def _bfs(
    start: tuple[int, int],
    goal: tuple[int, int],
    open_cells: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    queue: deque[tuple[int, int]] = deque([start])
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while queue:
        cell = queue.popleft()
        if cell == goal:
            break
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            candidate = (cell[0] + dx, cell[1] + dy)
            if candidate in open_cells and candidate not in previous:
                previous[candidate] = cell
                queue.append(candidate)
    if goal not in previous:
        raise AssertionError(f"unreachable customs cell {goal}")
    path: list[tuple[int, int]] = []
    cursor: tuple[int, int] | None = goal
    while cursor is not None:
        path.append(cursor)
        cursor = previous[cursor]
    path.reverse()
    return path


def _traits(rng: random.Random, index: int) -> dict[str, Any]:
    palette = _PALETTES[index % len(_PALETTES)]
    return {
        "palette_name": palette[0],
        "body": palette[1],
        "shadow": palette[2],
        "accent": palette[3],
        "horn": _HORNS[(index + rng.randrange(len(_HORNS))) % len(_HORNS)],
        "eyes": 1 + ((index + rng.randrange(3)) % 3),
        "mark": _MARKS[(index * 2 + rng.randrange(len(_MARKS))) % len(_MARKS)],
        "stripe": _STRIPES[(index + rng.randrange(len(_STRIPES))) % len(_STRIPES)],
    }


def _decoy_traits(target: dict[str, Any], pair_index: int, trait_differences: int = 1) -> dict[str, Any]:
    decoy = dict(target)
    # Each protected traveller is a close visual relative. One prominent trait
    # changes, rather than the palette, so a glance at colour alone is unsafe.
    traits = ("eyes", "mark", "horn", "stripe")
    if not 1 <= trait_differences <= len(traits):
        raise ValueError("customs decoys must differ in one through four visible traits")
    for offset in range(trait_differences):
        trait = traits[(pair_index + offset) % len(traits)]
        if trait == "eyes":
            decoy[trait] = 1 + (int(target[trait]) % 3)
        elif trait == "mark":
            mark_index = _MARKS.index(str(target[trait]))
            decoy[trait] = _MARKS[(mark_index + 1) % len(_MARKS)]
        elif trait == "horn":
            horn_index = _HORNS.index(str(target[trait]))
            decoy[trait] = _HORNS[(horn_index + 1) % len(_HORNS)]
        else:
            stripe_index = _STRIPES.index(str(target[trait]))
            decoy[trait] = _STRIPES[(stripe_index + 1) % len(_STRIPES)]
    return decoy


def _approach_cell(
    target: tuple[int, int],
    open_cells: set[tuple[int, int]],
    occupied: set[tuple[int, int]],
) -> tuple[int, int]:
    for dx, dy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
        candidate = (target[0] + dx, target[1] + dy)
        if candidate in open_cells and candidate not in occupied:
            return candidate
    for dx, dy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
        candidate = (target[0] + dx, target[1] + dy)
        if candidate in open_cells:
            return candidate
    raise AssertionError(f"no firing position for creature at {target}")


def _angle_mdeg(origin: tuple[int, int], target: tuple[int, int]) -> int:
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    if (dx, dy) == (1, 0):
        return 0
    if (dx, dy) == (0, 1):
        return 90_000
    if (dx, dy) == (-1, 0):
        return 180_000
    if (dx, dy) == (0, -1):
        return 270_000
    raise AssertionError("solver aim must be cardinal")


def _ray_wall_distance(rows: tuple[str, ...], x: float, y: float, angle_mdeg: int) -> float:
    angle = math.radians(angle_mdeg / 1000)
    dx, dy = math.cos(angle), math.sin(angle)
    map_x, map_y = int(math.floor(x)), int(math.floor(y))
    delta_x = abs(1 / dx) if abs(dx) > 1e-12 else 1e30
    delta_y = abs(1 / dy) if abs(dy) > 1e-12 else 1e30
    if dx < 0:
        step_x, side_x = -1, (x - map_x) * delta_x
    else:
        step_x, side_x = 1, (map_x + 1 - x) * delta_x
    if dy < 0:
        step_y, side_y = -1, (y - map_y) * delta_y
    else:
        step_y, side_y = 1, (map_y + 1 - y) * delta_y
    for _ in range(128):
        if side_x < side_y:
            distance = side_x
            side_x += delta_x
            map_x += step_x
        else:
            distance = side_y
            side_y += delta_y
            map_y += step_y
        if rows[map_y][map_x] == "#":
            return distance
    raise AssertionError("customs ray escaped its bounded map")


def _ray_creature_distance(x: float, y: float, angle_mdeg: int, creature: dict[str, Any]) -> float | None:
    angle = math.radians(angle_mdeg / 1000)
    dx, dy = math.cos(angle), math.sin(angle)
    offset_x = x - float(creature["x"])
    offset_y = y - float(creature["y"])
    b = dx * offset_x + dy * offset_y
    c = offset_x * offset_x + offset_y * offset_y - CREATURE_RADIUS * CREATURE_RADIUS
    discriminant = b * b - c
    if discriminant < 0:
        return None
    distance = -b - math.sqrt(discriminant)
    return distance if distance >= 0.04 else None


def _nearest_hit(
    rows: tuple[str, ...],
    creatures: list[dict[str, Any]],
    alive: set[str],
    x: float,
    y: float,
    angle_mdeg: int,
) -> str | None:
    wall_distance = _ray_wall_distance(rows, x, y, angle_mdeg)
    nearest_id: str | None = None
    nearest_distance = wall_distance
    for creature in creatures:
        creature_id = str(creature["id"])
        if creature_id not in alive:
            continue
        distance = _ray_creature_distance(x, y, angle_mdeg, creature)
        if distance is not None and distance < nearest_distance - 1e-8:
            nearest_distance = distance
            nearest_id = creature_id
    return nearest_id


def _solver_segment(
    current: tuple[int, int],
    creature: dict[str, Any],
    open_cells: set[tuple[int, int]],
    occupied: set[tuple[int, int]],
) -> tuple[dict[str, Any], tuple[int, int]]:
    target = (int(math.floor(float(creature["x"]))), int(math.floor(float(creature["y"]))))
    approach = _approach_cell(target, open_cells, occupied)
    route = _bfs(current, approach, open_cells)
    return ({
        "target_id": creature["id"],
        "route_cells": [{"x": x, "y": y} for x, y in route],
        "approach": {"x": approach[0], "y": approach[1]},
        "aim_mdeg": _angle_mdeg(approach, target),
    }, approach)


def _manifest_digest(
    rows: tuple[str, ...],
    initial_pose: dict[str, Any],
    creatures: list[dict[str, Any]],
    ammo: int,
) -> str:
    encoded = json.dumps(
        {"map": list(rows), "initial_pose": initial_pose, "creatures": creatures, "ammo": ammo},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed_int(seed, MECHANIC_ID))
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    width = int(parameters.get("map_width", MAP_WIDTH))
    height = int(parameters.get("map_height", MAP_HEIGHT))
    wanted_count = int(parameters.get("wanted_count", WANTED_COUNT))
    trait_differences = int(parameters.get("decoy_trait_differences", 1))
    ammo = int(parameters.get("ammo", AMMO))
    move_step = float(parameters.get("move_step", MOVE_STEP))
    if (
        width < 11
        or height < 9
        or width > 25
        or height > 19
        or width % 2 != 1
        or height % 2 != 1
        or not 2 <= wanted_count <= 5
        or not 1 <= trait_differences <= 4
        or not wanted_count + 4 <= ammo <= 16
        or not math.isclose(move_step, MOVE_STEP, rel_tol=0, abs_tol=1e-12)
    ):
        raise ValueError("tiny FPS customs control condition is outside the supported contract")

    # The historical level-four generator sampled twelve distant spawn cells
    # before assigning its eight travellers. Retain that sample size whenever
    # possible so L4's fixed-seed world is byte-for-byte unchanged.
    spawn_count = max(12, wanted_count * 2)
    base_rows, base_start, base_spawns = _maze_layout(rng, width, height, spawn_count)
    layout_variant = rng.choice(("identity", "mirror_x", "mirror_y", "rotate_180"))
    rows, start_cell, initial_angle, spawn_cells = _layout_variant(base_rows, base_start, base_spawns, layout_variant)
    open_cells = _open_cells(rows)
    initial_pose = {"x": start_cell[0] + 0.5, "y": start_cell[1] + 0.5, "angle_mdeg": initial_angle}

    selected_cells = list(spawn_cells)
    rng.shuffle(selected_cells)
    selected_cells = selected_cells[: wanted_count * 2]
    occupied = set(selected_cells)

    wanted_traits = [_traits(rng, index) for index in range(wanted_count)]
    # Repair the extremely unlikely possibility that randomized feature choices
    # create identical warrants.
    for index in range(1, len(wanted_traits)):
        while wanted_traits[index] in wanted_traits[:index]:
            horn_index = _HORNS.index(str(wanted_traits[index]["horn"]))
            wanted_traits[index]["horn"] = _HORNS[(horn_index + 1) % len(_HORNS)]

    creatures: list[dict[str, Any]] = []
    wanted_ids: list[str] = []
    protected_ids: list[str] = []
    for pair_index in range(wanted_count):
        wanted_id = _creature_id(seed, pair_index * 2)
        protected_id = _creature_id(seed, pair_index * 2 + 1)
        wanted_cell = selected_cells[pair_index * 2]
        protected_cell = selected_cells[pair_index * 2 + 1]
        creatures.append({
            "id": wanted_id,
            "x": wanted_cell[0] + 0.5,
            "y": wanted_cell[1] + 0.5,
            "traits": dict(wanted_traits[pair_index]),
            "pose": rng.choice(("alert", "stooped", "side-eye")),
        })
        creatures.append({
            "id": protected_id,
            "x": protected_cell[0] + 0.5,
            "y": protected_cell[1] + 0.5,
            "traits": _decoy_traits(wanted_traits[pair_index], pair_index, trait_differences),
            "pose": rng.choice(("alert", "stooped", "side-eye")),
        })
        wanted_ids.append(wanted_id)
        protected_ids.append(protected_id)

    rng.shuffle(creatures)
    posters = [{"warrant": f"W-{index + 1}", "traits": dict(traits)} for index, traits in enumerate(wanted_traits)]
    rng.shuffle(posters)

    by_id = {str(creature["id"]): creature for creature in creatures}
    current = start_cell
    solver_plan: list[dict[str, Any]] = []
    alive = {str(creature["id"]) for creature in creatures}
    for wanted_id in wanted_ids:
        segment, current = _solver_segment(current, by_id[wanted_id], open_cells, occupied)
        solver_plan.append(segment)
        approach = segment["approach"]
        hit_id = _nearest_hit(
            rows,
            creatures,
            alive,
            float(approach["x"]) + 0.5,
            float(approach["y"]) + 0.5,
            int(segment["aim_mdeg"]),
        )
        assert hit_id == wanted_id, f"solver ray reaches {hit_id}, expected {wanted_id}"
        alive.remove(wanted_id)

    protected_plan, _ = _solver_segment(start_cell, by_id[protected_ids[0]], open_cells, occupied)
    protected_approach = protected_plan["approach"]
    assert _nearest_hit(
        rows,
        creatures,
        {str(creature["id"]) for creature in creatures},
        float(protected_approach["x"]) + 0.5,
        float(protected_approach["y"]) + 0.5,
        int(protected_plan["aim_mdeg"]),
    ) == protected_ids[0]

    challenge_id = _challenge_id(seed, int(condition["difficulty"]) if condition is not None else None)
    task_id = str(task.get("id") or "")
    digest = _manifest_digest(rows, initial_pose, creatures, ammo)
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Clear four warrants through the generated maze. Protected travellers must survive.",
        "asset_manifest": "shared_runtime/assets/provenance/incubator_puzzles_v1.json",
        "generator": {"name": "moving_tiny_fps_customs_v2", "variant_count": 10**18},
        "layout_variant": layout_variant,
        "topology_id": hashlib.sha256("\n".join(rows).encode()).hexdigest()[:12],
        "map": list(rows),
        "initial_pose": initial_pose,
        "player_radius": PLAYER_RADIUS,
        "creature_radius": CREATURE_RADIUS,
        "move_step": move_step,
        "ammo": ammo,
        "creatures": creatures,
        "wanted_posters": posters,
        "manifest_digest": digest,
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "layout_variant": layout_variant,
        "map": list(rows),
        "initial_pose": initial_pose,
        "player_radius": PLAYER_RADIUS,
        "creature_radius": CREATURE_RADIUS,
        "move_step": move_step,
        "ammo": ammo,
        "creatures": creatures,
        "wanted_ids": wanted_ids,
        "protected_ids": protected_ids,
        "initial_geometry_plan": solver_plan,
        "initial_protected_geometry_plan": protected_plan,
        "oracle": "gym_anything_rt.tools.nonrealtime_four_v2_oracle:fps",
        "manifest_digest": digest,
        "variant_count": 10**18,
    }

    assert _reachable(start_cell, open_cells) == open_cells
    if condition is not None:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)

    assert len(creatures) == wanted_count * 2
    assert len(wanted_ids) == len(protected_ids) == wanted_count
    assert not (set(wanted_ids) & set(protected_ids))
    assert all("id" not in poster and "wanted" not in poster for poster in posters)
    assert all(len(segment["route_cells"]) >= 1 for segment in solver_plan)
    # Independent non-repeating corridor walks. The same positions are used by
    # rendering, occlusion and the independent ballistic replay.
    walks = {}
    for creature in creatures:
        cell = (int(creature['x']), int(creature['y']))
        previous = None
        path = [list(cell)]
        for _ in range(2400):
            neighbors = [(cell[0] + dx, cell[1] + dy) for dx, dy in ((1,0),(-1,0),(0,1),(0,-1))
                         if (cell[0] + dx, cell[1] + dy) in open_cells]
            choices = [p for p in neighbors if p != previous] or neighbors
            nxt = rng.choice(choices)
            previous, cell = cell, nxt
            path.append(list(cell))
        walks[creature['id']] = {'cells': path, 'step_ms': rng.randint(630, 850),
                                 'offset_ms': rng.randint(0, 400)}
    for state in (public_state, ground_truth):
        state['walks'] = copy.deepcopy(walks)
        state['single_attempt'] = True
    public_state['prompt'] = 'Track the moving travellers and clear every warrant. Protect all look-alikes. A missed shot or protected hit ends the attempt.'
    return public_state, ground_truth
