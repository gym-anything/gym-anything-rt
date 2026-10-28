"""Source-derived 3D gravity puzzles and action-stepped collar casting worlds.

Board construction uses the preserved benchmark's original Pearl Lattice helpers.
No JS1k code/assets are copied. The new physics is independently replayed.
"""
from __future__ import annotations
import copy
import hashlib
import random
import itertools
from collections import deque
from typing import Any
MECHANIC_ID = "pearl_lattice_nonrealtime"
PUZZLE_SALT = "pearl_lattice_v2"
SIZE, PLAYER, OPPONENT, EMPTY = 4, 1, -1, 0
Coord = tuple[int, int, int]
Column = tuple[int, int]
def _seed_int(seed, salt):
    return int.from_bytes(hashlib.sha256(f"{seed}|{salt}".encode()).digest()[:8], "big")
def _line(start: Coord, direction: Coord) -> list[Coord]:
    return [tuple(start[index] + step * direction[index] for index in range(3)) for step in range(4)]


def _transform(coord: Coord, *, flip_x: bool, flip_z: bool, swap_xz: bool) -> Coord:
    x, y, z = coord
    if flip_x:
        x = SIZE - 1 - x
    if flip_z:
        z = SIZE - 1 - z
    if swap_xz:
        x, z = z, x
    return x, y, z


def _layout(parameters: dict[str, Any], seed: str) -> tuple[list[list[Coord]], list[Coord]]:
    geometry = parameters["geometry"]
    if geometry == "planar_easy":
        shared = (0, 1, 0)
        targets = [
            _line(shared, (1, 0, 0)),
        ]
        opponent = _line(shared, (0, 0, 1))
    elif geometry == "cross_fork":
        shared = (0, 1, 0)
        targets = [
            _line(shared, (1, 0, 1)),
            _line(shared, (1, 0, 0)),
        ]
        opponent = _line(shared, (0, 0, 1))
    elif geometry == "raised_fork":
        shared = (0, 2, 0)
        targets = [
            _line(shared, (1, 0, 1)),
            _line(shared, (1, 0, 0)),
        ]
        opponent = _line(shared, (0, 0, 1))
    else:
        shared = (0, 0, 0)
        targets = [
            _line(shared, (1, 1, 1)),
            _line(shared, (0, 0, 1)),
        ]
        opponent = _line(shared, (1, 0, 0))

    rng = random.Random(_seed_int(seed, "orientation"))
    flags = {
        "flip_x": rng.randrange(2) == 1,
        "flip_z": rng.randrange(2) == 1,
        "swap_xz": rng.randrange(2) == 1,
    }
    transformed_targets = [[_transform(coord, **flags) for coord in line] for line in targets]
    transformed_opponent = [_transform(coord, **flags) for coord in opponent]
    return transformed_targets, transformed_opponent


def _all_lines() -> list[list[Coord]]:
    lines: list[list[Coord]] = []
    directions = [direction for direction in itertools.product((-1, 0, 1), repeat=3) if direction != (0, 0, 0)]
    for x, y, z in itertools.product(range(SIZE), repeat=3):
        for dx, dy, dz in directions:
            end = (x + 3 * dx, y + 3 * dy, z + 3 * dz)
            if not all(0 <= value < SIZE for value in end):
                continue
            previous = (x - dx, y - dy, z - dz)
            if all(0 <= value < SIZE for value in previous):
                continue
            lines.append(_line((x, y, z), (dx, dy, dz)))
    return lines


ALL_LINES = _all_lines()


def _has_line(board: dict[Coord, int], mark: int) -> bool:
    return any(all(board.get(cell, EMPTY) == mark for cell in line) for line in ALL_LINES)


def _legal_columns(board: dict[Coord, int]) -> list[Column]:
    return [
        (x, z)
        for z in range(SIZE)
        for x in range(SIZE)
        if board.get((x, SIZE - 1, z), EMPTY) == EMPTY
    ]


def _height(board: dict[Coord, int], column: Column) -> int:
    x, z = column
    for y in range(SIZE):
        if board.get((x, y, z), EMPTY) == EMPTY:
            return y
    return SIZE


def _drop(board: dict[Coord, int], column: Column, mark: int) -> Coord | None:
    y = _height(board, column)
    if y >= SIZE:
        return None
    cell = (column[0], y, column[1])
    board[cell] = mark
    return cell


def _copy_board(board: dict[Coord, int]) -> dict[Coord, int]:
    return dict(board)


def _immediate_columns(board: dict[Coord, int], mark: int) -> list[Column]:
    legal = _legal_columns(board)
    if _has_line(board, mark):
        return legal
    landing_cells = {(x, _height(board, (x, z)), z) for x, z in legal}
    winning = set()
    for line in ALL_LINES:
        missing = [cell for cell in line if board.get(cell, EMPTY) != mark]
        if len(missing) == 1 and missing[0] in landing_cells:
            winning.add((missing[0][0], missing[0][2]))
    return [column for column in legal if column in winning]


def _opponent_column(board: dict[Coord, int], pressure_columns: list[Column], pressure_index: int, policy: str = "threat_then_block") -> tuple[Column | None, int]:
    own_wins = _immediate_columns(board, OPPONENT)
    if own_wins:
        return own_wins[0], pressure_index
    player_wins = _immediate_columns(board, PLAYER) if policy == "threat_then_block" else []
    if player_wins:
        return player_wins[0], pressure_index
    legal = set(_legal_columns(board))
    for offset in range(len(pressure_columns)):
        column = pressure_columns[(pressure_index + offset) % len(pressure_columns)]
        if column in legal:
            return column, pressure_index + offset + 1
    return (next((column for column in _legal_columns(board) if column in legal), None), pressure_index + 1)


def _solution_moves(
    initial: dict[Coord, int],
    pressure_columns: list[Column],
    max_moves: int,
    target_lines: list[list[Coord]],
    policy: str = "threat_then_block",
) -> list[Column]:
    target_columns = {(x, z) for line in target_lines for x, _, z in line}
    queue = deque([(initial, 0, [], 0)])
    visited: set[tuple[tuple[tuple[int, int, int], int], int]] = set()
    while queue:
        board, pressure_index, moves, depth = queue.popleft()
        if depth >= max_moves:
            continue
        legal = _legal_columns(board)
        forced = _immediate_columns(board, OPPONENT)
        preferred = [column for column in legal if column in target_columns]
        candidates = list(dict.fromkeys(forced + preferred)) or legal
        for column in candidates:
            next_board = _copy_board(board)
            placed = _drop(next_board, column, PLAYER)
            if placed is None:
                continue
            next_moves = moves + [column]
            if _has_line(next_board, PLAYER):
                return next_moves
            opponent_column, next_pressure = _opponent_column(next_board, pressure_columns, pressure_index, policy)
            if opponent_column is None:
                continue
            _drop(next_board, opponent_column, OPPONENT)
            if _has_line(next_board, OPPONENT):
                continue
            signature = (tuple(sorted(next_board.items())), next_pressure)
            if signature in visited:
                continue
            visited.add(signature)
            queue.append((next_board, next_pressure, next_moves, depth + 1))
    raise RuntimeError("pearl lattice generator could not find a winning continuation")


def _build_board(parameters: dict[str, Any], seed: str) -> tuple[dict[Coord, int], list[list[Coord]], list[Coord], list[Column], list[Column]]:
    targets, opponent_line = _layout(parameters, seed)
    target_cells = {cell for line in targets for cell in line}
    opponent_cells = set(opponent_line)
    shared = targets[0][0]
    if shared != opponent_line[0] or target_cells & opponent_cells - {shared}:
        raise RuntimeError("pearl lattice layout has inconsistent shared lines")
    prefill = int(parameters["prefill_player"])
    roles: dict[Coord, int] = {}
    if parameters["geometry"] == "planar_easy":
        prefill = 3
    for line in targets:
        for cell in line[1 : 1 + prefill]:
            roles[cell] = PLAYER
    for cell in opponent_line[1:]:
        roles[cell] = OPPONENT

    support_cells: set[Coord] = set()
    for x, y, z in target_cells | opponent_cells:
        support_cells.update((x, below, z) for below in range(y))
    if target_cells & support_cells or opponent_cells & support_cells:
        raise RuntimeError("pearl lattice line layout violates gravity")

    shared_column = (shared[0], shared[2])
    reserved_columns = {(x, z) for x, _, z in target_cells | opponent_cells}
    noise_rng = random.Random(_seed_int(seed, "noise"))
    desired_noise = int(parameters["extra_noise"])

    def fill(candidate: dict[Coord, int]) -> bool:
        # A support colouring can make the requested fillers impossible. Search
        # a bounded number of distinct partial boards, then resample supports;
        # never silently emit an under-filled configuration.
        visited = set()
        nodes = 0

        def place_noise(remaining: int) -> bool:
            nonlocal nodes
            if remaining == 0:
                return True
            signature = tuple(sorted(candidate.items()))
            if signature in visited or nodes >= 256:
                return False
            visited.add(signature)
            choices = [(column, mark) for column in _legal_columns(candidate)
                       if column not in reserved_columns for mark in (PLAYER, OPPONENT)]
            noise_rng.shuffle(choices)
            for column, mark in choices:
                nodes += 1
                if nodes > 256:
                    return False
                cell = (column[0], _height(candidate, column), column[1])
                candidate[cell] = mark
                shortcut = parameters["geometry"] != "planar_easy" and bool(_immediate_columns(candidate, PLAYER))
                if not _has_line(candidate, mark) and not shortcut and _immediate_columns(candidate, OPPONENT) == [shared_column]:
                    defended = _copy_board(candidate)
                    _drop(defended, shared_column, PLAYER)
                    if not _immediate_columns(defended, OPPONENT) and place_noise(remaining - 1):
                        return True
                candidate.pop(cell)
            return False

        return place_noise(desired_noise)

    ordered_supports = sorted(support_cells, key=lambda item: (item[1], item[2], item[0]))
    board: dict[Coord, int] | None = None
    support_rng = random.Random(_seed_int(seed, "supports"))
    for _attempt in range(4096):
        candidate_board = {
            cell: support_rng.choice((PLAYER, OPPONENT))
            for cell in ordered_supports
        }
        if any(_has_line(candidate_board, mark) for mark in (PLAYER, OPPONENT)):
            continue
        valid = True
        for cell, mark in sorted(roles.items(), key=lambda item: (item[0][1], item[0][2], item[0][0])):
            if cell in candidate_board:
                valid = False
                break
            candidate_board[cell] = mark
            if _has_line(candidate_board, mark):
                valid = False
                break
        if not valid:
            continue
        if _immediate_columns(candidate_board, OPPONENT) != [shared_column]:
            continue
        if parameters["geometry"] != "planar_easy" and _immediate_columns(candidate_board, PLAYER):
            continue
        defense_board = _copy_board(candidate_board)
        if _drop(defense_board, shared_column, PLAYER) is None or _immediate_columns(defense_board, OPPONENT):
            continue
        if not fill(candidate_board):
            continue
        board = candidate_board
        break
    if board is None:
        raise RuntimeError("pearl lattice could not construct safe supports and the exact configured filler count")

    safe_columns = [column for column in _legal_columns(board) if column not in reserved_columns]
    if not safe_columns:
        safe_columns = _legal_columns(board)
    solution = _solution_moves(board, safe_columns, int(parameters["max_player_moves"]), targets, parameters["opponent_policy"])
    return board, targets, opponent_line, safe_columns, solution


def _cells(board: dict[Coord, int]) -> list[dict[str, int]]:
    return [
        {"x": x, "y": y, "z": z, "value": int(board.get((x, y, z), EMPTY))}
        for z in range(SIZE)
        for y in range(SIZE)
        for x in range(SIZE)
    ]


DEFAULT_PARAMETERS = {
    'geometry': 'spatial_fork', 'prefill_player': 2, 'extra_noise': 12,
    'opponent_policy': 'threat_then_block', 'max_player_moves': 10,
    'mouth_radius': 26, 'drift_amplitude': 32, 'drift_vertical_amplitude': 24, 'drift_span_ms': 1800,
    'gravity': 72, 'wind_acceleration': 165,
    'steering_spring': 17, 'steering_damping': 6,
}


def generate(task, seed):
    raw = task.get('_control_condition') or (task.get('metadata') or {}).get('control_condition')
    condition = copy.deepcopy(raw or dict(difficulty=5, interaction='full', real_time='live', difficulty_parameters=DEFAULT_PARAMETERS))
    parameters = condition.get('difficulty_parameters')
    if not isinstance(parameters, dict) or set(parameters) != set(DEFAULT_PARAMETERS):
        raise ValueError('incomplete pearl casting profile')
    if type(condition.get('difficulty')) is not int or condition['difficulty'] not in range(1, 6):
        raise ValueError('invalid casting difficulty')
    if condition.get('interaction') not in ('full', 'simplified') or condition.get('real_time') not in ('live', 'paused'):
        raise ValueError('invalid casting control condition')
    if parameters['geometry'] not in ('planar_easy','cross_fork','raised_fork','spatial_fork') or parameters['opponent_policy'] not in ('threat_then_block','win_then_pressure'):
        raise ValueError('invalid gravity-board profile')
    for name, lo, hi in [('prefill_player',2,3),('extra_noise',0,12),('max_player_moves',3,10),('mouth_radius',26,30),('drift_amplitude',32,43),('drift_vertical_amplitude',24,32),('drift_span_ms',1800,3200),('gravity',26,72),('wind_acceleration',60,165),('steering_spring',17,36),('steering_damping',6,12)]:
        if type(parameters[name]) not in (int,float) or not lo <= parameters[name] <= hi:
            raise ValueError('invalid ' + name)
    board, _targets, _opponent, pressure, solution = _build_board(parameters, str(seed))
    # Keep corresponding seeds aligned with the evaluated V2 donor.  The
    # namespace changes, but the puzzle and motion RNG must not change merely
    # because this counterpart has a different mechanic id.
    rng = random.Random(_seed_int(str(seed), PUZZLE_SALT))
    physics = dict(revision='double-collar-v2', tick_ms=10, field=[640,480],
        # The live page is idle-stable.  Each existing aim/release/certify
        # action advances this many fixed physics ticks; no wall-clock work
        # advances the casting state.
        action_step_ticks=10,
        pearl_radius=7, magnet_radius=24, magnet_spring=55, magnet_damping=14,
        magnet_acceleration=2200, magnet_speed=420, pearl_acceleration=1100, pearl_speed=340,
        gravity=parameters['gravity'], steering_spring=parameters['steering_spring'],
        steering_damping=parameters['steering_damping'], mouth_radius=parameters['mouth_radius'],
        wind_acceleration=parameters['wind_acceleration'], wind_span_ms=parameters['drift_span_ms'],
        wind_seed=rng.getrandbits(32), initial_magnet=[320,240],
        collars=[dict(depth=180, offset=[80,24], seed=rng.getrandbits(32), span_ms=parameters['drift_span_ms'], amplitude=[parameters['drift_amplitude'],parameters['drift_vertical_amplitude']]),
                 dict(depth=800, offset=[-80,-24], seed=rng.getrandbits(32), span_ms=parameters['drift_span_ms']+310, amplitude=[parameters['drift_amplitude'],parameters['drift_vertical_amplitude']])])
    token = hashlib.sha256(f'{seed}|{PUZZLE_SALT}|{condition["difficulty"]}|double-collar-v2'.encode()).hexdigest()[:16]
    public = dict(benchmark='gym_anything_rt', mechanic_id=MECHANIC_ID,
        task_id=task['id'], challenge_id=token, control_condition=condition,
        source_anchors=['ART-336'], single_attempt=True,
        prompt='Cast four jade pearls into a line through the glass.',
        physics=physics, initial_board={'%d,%d,%d'%cell:value for cell,value in board.items()},
        pressure_columns=[list(c) for c in pressure],
        asset_manifest='shared_runtime/assets/provenance/pearl_lattice_v2_v0.json',
        generator=dict(name='pearl_lattice_double_collar_v2_action_stepped', variant_count=2**64,
                       variant_count_kind='nominal 64-bit motion RNG seed space; distinct world count not enumerated, with additional board variation'))
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), solution_moves=[list(c) for c in solution])
    return public, truth
