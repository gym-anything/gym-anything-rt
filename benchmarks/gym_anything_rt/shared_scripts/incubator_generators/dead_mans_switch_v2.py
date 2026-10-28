from __future__ import annotations

import copy
import hashlib
import random
from collections import deque
from typing import Any


MECHANIC_ID = "dead_mans_switch_v2"
VARIANT_COUNT = 18_662_400_000
DEFAULT_COLUMNS = 18
DEFAULT_ROWS = 10
DEFAULT_BARRIER_COLUMNS = (3, 6, 9, 12, 15)
DEFAULT_LOW_GAP_ROWS = (1, 2)
DEFAULT_HIGH_GAP_ROWS = (7, 8)
DEFAULT_START_ROWS = (7, 8)
DEFAULT_GOAL_ROWS = (7, 8)
DEFAULT_PRESSURE_PERIODS = (3_600, 3_800, 4_000)
_DIRECTIONS = (
    ("N", 0, -1),
    ("E", 1, 0),
    ("S", 0, 1),
    ("W", -1, 0),
)


def _seed_int(seed: str, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _shortest_path(
    start: tuple[int, int],
    goal: tuple[int, int],
    walls: set[tuple[int, int]],
    columns: int,
    rows: int,
) -> list[str]:
    queue: deque[tuple[int, int]] = deque([start])
    previous: dict[tuple[int, int], tuple[tuple[int, int], str]] = {}
    seen = {start}
    while queue:
        position = queue.popleft()
        if position == goal:
            break
        for direction, dx, dy in _DIRECTIONS:
            candidate = (position[0] + dx, position[1] + dy)
            if not (0 <= candidate[0] < columns and 0 <= candidate[1] < rows):
                continue
            if candidate in walls or candidate in seen:
                continue
            seen.add(candidate)
            previous[candidate] = (position, direction)
            queue.append(candidate)
    if goal not in seen:
        raise ValueError("generated switch course is not traversable")
    commands: list[str] = []
    cursor = goal
    while cursor != start:
        cursor, direction = previous[cursor]
        commands.append(direction)
    commands.reverse()
    return commands


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed_int(seed, MECHANIC_ID))
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    columns = int(parameters.get("columns", DEFAULT_COLUMNS))
    rows = int(parameters.get("rows", DEFAULT_ROWS))
    barrier_columns = tuple(int(value) for value in parameters.get("barrier_columns", DEFAULT_BARRIER_COLUMNS))
    low_gap_rows = tuple(int(value) for value in parameters.get("low_gap_rows", DEFAULT_LOW_GAP_ROWS))
    high_gap_rows = tuple(int(value) for value in parameters.get("high_gap_rows", DEFAULT_HIGH_GAP_ROWS))
    start_rows = tuple(int(value) for value in parameters.get("start_rows", DEFAULT_START_ROWS))
    goal_rows = tuple(int(value) for value in parameters.get("goal_rows", DEFAULT_GOAL_ROWS))
    minimum_solution_moves = int(parameters.get("minimum_solution_moves", 45))
    maximum_solution_moves = int(parameters.get("maximum_solution_moves", 57))
    pressure_periods = tuple(int(value) for value in parameters.get("pressure_period_ms_values", DEFAULT_PRESSURE_PERIODS))
    x_amplitude_min = int(parameters.get("x_amplitude_milli_min", 245))
    x_amplitude_max = int(parameters.get("x_amplitude_milli_max", 285))
    y_amplitude_min = int(parameters.get("y_amplitude_milli_min", 155))
    y_amplitude_max = int(parameters.get("y_amplitude_milli_max", 190))
    hit_x_milli = int(parameters.get("hit_x_milli", 185))
    hit_y_milli = int(parameters.get("hit_y_milli", 235))
    sample_ms = int(parameters.get("sample_ms", 100))
    maximum_sample_gap_ms = int(parameters.get("maximum_sample_gap_ms", 360))
    outside_grace_ms = int(parameters.get("outside_grace_ms", 310))
    minimum_hold_ms = int(parameters.get("minimum_hold_ms", 5_200))

    if not 8 <= columns <= 24 or not 7 <= rows <= 14:
        raise ValueError("switch course dimensions are outside supported limits")
    if (
        not 1 <= len(barrier_columns) <= 6
        or tuple(sorted(set(barrier_columns))) != barrier_columns
        or any(column < 2 or column > columns - 3 for column in barrier_columns)
        or any(right - left < 2 for left, right in zip(barrier_columns, barrier_columns[1:]))
    ):
        raise ValueError("switch relay columns are malformed")
    all_rows = (*low_gap_rows, *high_gap_rows, *start_rows, *goal_rows)
    if (
        not low_gap_rows
        or not high_gap_rows
        or not start_rows
        or not goal_rows
        or any(row < 1 or row > rows - 2 for row in all_rows)
        or set(low_gap_rows) & set(high_gap_rows)
        or not 1 <= minimum_solution_moves <= maximum_solution_moves <= 160
        or not pressure_periods
        or any(period < 2_400 or period > 5_000 for period in pressure_periods)
        or not 80 <= x_amplitude_min <= x_amplitude_max <= 360
        or not 70 <= y_amplitude_min <= y_amplitude_max <= 280
        or not 120 <= hit_x_milli <= 350
        or not 150 <= hit_y_milli <= 360
        or not 60 <= sample_ms <= maximum_sample_gap_ms <= 650
        or not 150 <= outside_grace_ms <= 600
        or not 2_000 <= minimum_hold_ms <= 9_000
    ):
        raise ValueError("switch difficulty parameters are malformed")

    gaps = [rng.choice(low_gap_rows) if index % 2 == 0 else rng.choice(high_gap_rows) for index in range(len(barrier_columns))]

    start = (1, rng.choice(start_rows))
    goal = (columns - 2, rng.choice(goal_rows))
    walls = {
        (column, row)
        for column, gap in zip(barrier_columns, gaps)
        for row in range(rows)
        if row != gap
    }
    checkpoints = [
        {
            "id": f"checkpoint-{index + 1}",
            "order": index + 1,
            "x": column,
            "y": gap,
        }
        for index, (column, gap) in enumerate(zip(barrier_columns, gaps))
    ]

    waypoints = [(item["x"], item["y"]) for item in checkpoints] + [goal]
    solution_path: list[str] = []
    cursor = start
    for waypoint in waypoints:
        segment = _shortest_path(cursor, waypoint, walls, columns, rows)
        solution_path.extend(segment)
        for direction in segment:
            _, dx, dy = next(item for item in _DIRECTIONS if item[0] == direction)
            cursor = (cursor[0] + dx, cursor[1] + dy)

    condition_token = f"|d{int(condition['difficulty'])}" if condition else ""
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}{condition_token}".encode("utf-8")).hexdigest()[:12]
    task_id = str(task.get("id") or "dead_mans_switch_v2_seed_0001@0.1")
    wall_records = [{"x": x, "y": y} for x, y in sorted(walls, key=lambda item: (item[1], item[0]))]
    board = {
        "columns": columns,
        "rows": rows,
        "start": {"x": start[0], "y": start[1]},
        "goal": {"x": goal[0], "y": goal[1]},
        "walls": wall_records,
        "checkpoints": checkpoints,
    }
    pressure_motion = {
        "period_ms": rng.choice(pressure_periods),
        "motion_seed": rng.getrandbits(32),
        "phase_milliradians": rng.randrange(0, 6_284),
        "x_amplitude_milli": rng.randint(x_amplitude_min, x_amplitude_max),
        "y_amplitude_milli": rng.randint(y_amplitude_min, y_amplitude_max),
        "hit_x_milli": hit_x_milli,
        "hit_y_milli": hit_y_milli,
        "sample_ms": sample_ms,
        "maximum_sample_gap_ms": maximum_sample_gap_ms,
        "outside_grace_ms": outside_grace_ms,
        "minimum_hold_ms": minimum_hold_ms,
    }
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "asset_manifest": 'environments/dead_mans_switch_v2_env/provenance.json',
        "prompt": task.get("natural_language")
        or "Track the moving pressure plate while steering through every numbered checkpoint to the dock.",
        "generator": {"name": "moving_dead_mans_switch_v2_v2", "variant_count": VARIANT_COUNT},
        "board": board,
        "pressure_motion": pressure_motion,
        "controls": {"movement": ["W", "A", "S", "D", "ARROWS"], "pressure": "pointer_hold"},
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "board": board,
        "checkpoint_ids": [item["id"] for item in checkpoints],
        "solution_path": solution_path,
        "minimum_success_moves": len(solution_path),
        "pressure_motion": pressure_motion,
        "variant_count": VARIANT_COUNT,
    }
    if condition:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    if not minimum_solution_moves <= len(solution_path) <= maximum_solution_moves:
        raise ValueError(
            f"generated switch route has {len(solution_path)} moves outside "
            f"{minimum_solution_moves}-{maximum_solution_moves}"
        )
    return public_state, ground_truth
