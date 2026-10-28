"""PHY-038: genuine connected Soma pieces in a stable, action-settled cradle.

The exact cover certifies attainability, not the only accepted arrangement.
Interaction never enters generation; both surfaces operate the same motor.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import random
from functools import lru_cache

MECHANIC_ID = "polycube_parcel_nonrealtime"
IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
SHAPES = {
    "V": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    "L": [[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0]],
    "T": [[0, 0, 0], [1, 0, 0], [2, 0, 0], [1, 1, 0]],
    "Z": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [2, 1, 0]],
    "A": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1]],
    "B": [[0, 0, 1], [1, 0, 1], [1, 1, 1], [1, 1, 0]],
    "P": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
}
COLORS = ["#ffb65d", "#56d7c2", "#b39aff", "#ff7399", "#65baff", "#ede071", "#ec92ec"]
PROFILES = {
    1: dict(preplaced_count=5, tolerance=.40, dock_ms=1700, span_ms=4200,
            amplitude=[.85, .72, .78], motor_gain=64., motor_damping=16.),
    2: dict(preplaced_count=4, tolerance=.37, dock_ms=1900, span_ms=3900,
            amplitude=[.90, .78, .82], motor_gain=64., motor_damping=16.),
    3: dict(preplaced_count=2, tolerance=.33, dock_ms=2100, span_ms=3500,
            amplitude=[.94, .82, .87], motor_gain=64., motor_damping=16.),
    4: dict(preplaced_count=0, tolerance=.30, dock_ms=2300, span_ms=3200,
            amplitude=[.97, .85, .90], motor_gain=64., motor_damping=16.),
    5: dict(preplaced_count=0, tolerance=.27, dock_ms=2500, span_ms=2900,
            amplitude=[1., .90, .95], motor_gain=64., motor_damping=16.),
}


def matvec(matrix, vector):
    return [sum(row[j] * vector[j] for j in range(3)) for row in matrix]


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def determinant(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def rotations():
    result = []
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1, 1), repeat=3):
            matrix = [[0] * 3 for _ in range(3)]
            for i in range(3):
                matrix[i][permutation[i]] = signs[i]
            if determinant(matrix) == 1:
                result.append(matrix)
    return result


ORIENTATIONS = rotations()


def normalized(shape, orientation):
    cells = [matvec(orientation, cell) for cell in shape]
    low = [min(cell[i] for cell in cells) for i in range(3)]
    return sorted([[cell[i] - low[i] for i in range(3)] for cell in cells])


@lru_cache(maxsize=1)
def candidates():
    result = {}
    for piece_id, shape in SHAPES.items():
        seen, options = set(), []
        for rotation in ORIENTATIONS:
            cells = normalized(shape, rotation)
            key = tuple(map(tuple, cells))
            if key in seen:
                continue
            seen.add(key)
            size = [max(c[i] for c in cells) + 1 for i in range(3)]
            for origin in itertools.product(*(range(4 - s) for s in size)):
                covered = [tuple(c[i] + origin[i] for i in range(3)) for c in cells]
                mask = sum(1 << (c[0] * 9 + c[1] * 3 + c[2]) for c in covered)
                options.append(dict(orientation=rotation, origin=list(origin), cells=covered, mask=mask))
        result[piece_id] = options
    return result


@lru_cache(maxsize=256)
def exact_cover(seed):
    """Randomized exact cover with cell and piece constraints; no reflections."""
    rng = random.Random(int.from_bytes(hashlib.sha256((str(seed) + '|cover-v2').encode()).digest()[:8], 'big'))
    options = {p: rng.sample(xs, len(xs)) for p, xs in candidates().items()}
    full = (1 << 27) - 1

    def visit(occupied, remaining, chosen):
        if not remaining:
            return chosen if occupied == full else None
        viable = {p: [o for o in options[p] if not o['mask'] & occupied] for p in remaining}
        if any(not xs for xs in viable.values()):
            return None
        branches = [[(p, o) for o in xs] for p, xs in viable.items()]
        for cell in range(27):
            bit = 1 << cell
            if not occupied & bit:
                branches.append([(p, o) for p, xs in viable.items() for o in xs if o['mask'] & bit])
        branch = min(branches, key=len)
        for p, option in branch:
            found = visit(occupied | option['mask'], [x for x in remaining if x != p], {**chosen, p: option})
            if found:
                return found
        return None

    found = visit(0, list(SHAPES), {})
    if not found:
        raise ValueError('Soma cover search failed')
    return {p: {k: copy.deepcopy(v) for k, v in o.items() if k != 'mask'} for p, o in found.items()}


def generate(task, seed):
    raw = task.get('_control_condition') or (task.get('metadata') or {}).get('control_condition')
    level = int((raw or {}).get('difficulty', 5))
    if level not in PROFILES:
        raise ValueError('difficulty must be 1 through 5')
    profile = copy.deepcopy(PROFILES[level])
    if raw is not None:
        if raw.get('interaction') not in ('full', 'simplified'):
            raise ValueError('unsupported interaction')
        parameters = raw.get('difficulty_parameters')
        if parameters != profile:
            raise ValueError('difficulty parameters differ from the declared profile')
    interaction = (raw or {}).get('interaction', 'full')
    condition = copy.deepcopy(raw or dict(difficulty=level, interaction=interaction, real_time='live', difficulty_parameters=profile))
    rng = random.Random(int.from_bytes(hashlib.sha256((str(seed) + '|parcel-v2').encode()).digest()[:8], 'big'))
    solution = copy.deepcopy(exact_cover(str(seed)))
    order = list(SHAPES)
    rng.shuffle(order)
    preplaced = set(order[:profile['preplaced_count']])
    pieces = []
    for index, (pid, shape) in enumerate(SHAPES.items()):
        seated = pid in preplaced
        pieces.append(dict(id=pid, shape=copy.deepcopy(shape), color=COLORS[index],
                           orientation=copy.deepcopy(solution[pid]['orientation'] if seated else rng.choice(ORIENTATIONS)),
                           origin=copy.deepcopy(solution[pid]['origin']) if seated else None,
                           placed=seated, locked=seated))
    world = dict(grid_size=3, pieces=pieces, profile=profile,
                 motion=dict(seed=rng.getrandbits(32), span_ms=profile['span_ms'], amplitude=profile['amplitude'],
                              mode='fixed'),
                 tick_ms=10, gain=profile['motor_gain'], damping=profile['motor_damping'],
                 max_acceleration=30., max_speed=4., motor_bounds=[-1.25, 4.25],
                 initial_position=[-.75, -.75, -.75], camera_yaw=35, camera_pitch=.52,
                 max_ms=600000, action_motor_ms=800, timing_mode='action_triggered')
    task_id = str(task.get('id') or f'{MECHANIC_ID}_seed_0001@0.1')
    challenge = hashlib.sha256(f'{seed}|{MECHANIC_ID}|{level}|packing-cradle-1'.encode()).hexdigest()[:16]
    public = dict(benchmark='gym_anything_rt', mechanic_id=MECHANIC_ID, task_id=task_id,
                  challenge_id=challenge, prompt=task.get('natural_language', 'Pack the moving 3×3×3 parcel.'),
                  submit_label='CERTIFY PARCEL', control_condition=condition, interaction=interaction,
                  world=world, generator=dict(name='soma_drifting_cradle_v2', variant_count=1024,
                  variant_count_is_lower_bound=True,
                  variant_count_kind='measured lower bound: 1024 distinct worlds per difficulty on seeds 0 through 1023; total space not enumerated'),
                  asset_manifest='shared_runtime/assets/provenance/polycube_parcel_v2_v0.json',
                  render_boundary='Browser play ships geometry and the fixed layout seed. It is an inspectable exploration surface. The canonical exact cover is not sent to the browser.')
    truth = {**copy.deepcopy(public), 'seed': str(seed), 'solution_placements': solution, 'difficulty': level}
    return public, truth


__all__ = ['MECHANIC_ID', 'PROFILES', 'SHAPES', 'ORIENTATIONS', 'normalized', 'matmul', 'exact_cover', 'generate']
