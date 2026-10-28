"""Seeded kinetic smithing. The private inverse deformation route proves volume reachability."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path
import random

MECHANIC_ID = 'ember_anvil_v3'
REVISION = 'kinetic-smithing-1'
N = 5
DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))
PROFILES = {
    1: dict(cap=2, relief=False, scramble=3, excess=1, travel_x=65, travel_y=25, rotation=.10, motion_span_ms=4300, heat_span_ms=6500, workable=.40),
    2: dict(cap=2, relief=False, scramble=6, excess=1, travel_x=85, travel_y=35, rotation=.20, motion_span_ms=3800, heat_span_ms=5500, workable=.48),
    3: dict(cap=3, relief=True, scramble=10, excess=1, travel_x=105, travel_y=42, rotation=.32, motion_span_ms=3100, heat_span_ms=4700, workable=.54),
    4: dict(cap=3, relief=True, scramble=15, excess=0, travel_x=120, travel_y=45, rotation=.42, motion_span_ms=2700, heat_span_ms=4100, workable=.60),
    5: dict(cap=4, relief=True, scramble=22, excess=0, travel_x=135, travel_y=48, rotation=.52, motion_span_ms=2300, heat_span_ms=3600, workable=.66),
}


def episode_status(task_id):
    """Carry verified first failure through the existing /state regeneration."""
    path = Path(__file__).resolve().parents[2] / 'shared_runtime/server/incubator_graders/ember_anvil_v3.py'
    spec = importlib.util.spec_from_file_location('ember_anvil_episode_policy', path)
    if spec is None or spec.loader is None:
        return dict(episode_failed=False, episode_history_error='Cannot load episode policy.')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failure, error = module.read_episode_failure(task_id)
    return dict(episode_failed=bool(failure), episode_history_error=error or '')


def neighbor(i, d):
    x, y = i % N + DIRS[d][0], i // N + DIRS[d][1]
    return y * N + x if 0 <= x < N and 0 <= y < N else None


def deform(h, i, tool, d, cap):
    if not 0 <= i < N*N or not h[i]:
        return None
    out = h[:]
    if tool == 'split':
        out[i] -= 1
        return out
    j = neighbor(i, d)
    if j is None or h[j] >= cap:
        return None
    if tool == 'draw' and h[j] >= h[i]:
        return None
    if tool == 'upset' and h[j] != h[i]:
        return None
    if tool not in ('draw', 'upset'):
        return None
    out[i] -= 1
    out[j] += 1
    return out


def connected(h):
    occupied = {i for i, value in enumerate(h) if value}
    if not occupied:
        return False
    found = {min(occupied)}
    todo = list(found)
    while todo:
        i = todo.pop()
        for d in range(4):
            j = neighbor(i, d)
            if j in occupied and j not in found:
                found.add(j)
                todo.append(j)
    return found == occupied


def generate(task, seed):
    condition = task.get('_control_condition') or (task.get('metadata') or {}).get('control_condition')
    level = int((condition or {}).get('difficulty', 5))
    mode = (condition or {}).get('interaction', 'full')
    if level not in PROFILES or mode not in ('full', 'simplified'):
        raise ValueError('unsupported kinetic smithing condition')
    p = dict(PROFILES[level])
    p.update((condition or {}).get('difficulty_parameters') or {})
    if p != PROFILES[level]:
        raise ValueError('profile differs from the declared kinetic smithing revision')
    rng = random.Random(hashlib.sha256(f'{seed}|{MECHANIC_ID}|{REVISION}|{level}'.encode()).digest())
    target = [0] * (N*N)
    # Connected tool heads, with a socket shoulder, tapered edge and through-eye.
    for y in range(1, 4):
        for x in range(1, 4):
            target[y*N+x] = 1
    target[2*N+4] = 1
    target[rng.choice((1, 3))*N+4] = 1
    if p['relief']:
        for y in range(1, 4):
            target[y*N+1] = p['cap']-1
        target[2*N+1] = 0
        target[rng.choice((1, 3))*N+2] = p['cap']
    for _ in range(rng.randrange(4)):
        target = [target[(N-1-x)*N+y] for y in range(N) for x in range(N)]
    h = target[:]
    excess = []
    for _ in range(p['excess']):
        i = rng.choice([i for i, v in enumerate(h) if 0 < v < p['cap']])
        h[i] += 1
        excess.append(i)
    seen, undo = {tuple(h)}, []
    for _ in range(p['scramble']):
        choices = []
        for i in range(N*N):
            for d in range(4):
                for tool in ('draw', 'upset'):
                    after = deform(h, i, tool, d, p['cap'])
                    if after is None or tuple(after) in seen or not connected(after):
                        continue
                    j = neighbor(i, d)
                    reverse = 'draw' if after[i] < after[j] else 'upset'
                    if deform(after, j, reverse, (d+2)%4, p['cap']) == h:
                        choices.append((sum(abs(a-b) for a,b in zip(after,target))+rng.random()*4,
                                        after, dict(cell=j, tool=reverse, direction=(d+2)%4)))
        if not choices:
            raise ValueError('no reversible connected deformation')
        _, h, action = max(choices, key=lambda c: c[0])
        seen.add(tuple(h))
        undo.append(action)
    solution = list(reversed(undo)) + [dict(cell=i, tool='split', direction=0) for i in reversed(excess)]
    check = h[:]
    for a in solution:
        check = deform(check, a['cell'], a['tool'], a['direction'], p['cap'])
    assert check == target and h != target
    world = dict(revision=REVISION, size=N, cell_px=44, face_inset=2, initial=h,
                 target=target, cap=p['cap'], stage=[860,450], origin=[475,205],
                 travel=[p['travel_x'], p['travel_y'], p['rotation']],
                 motion_span_ms=p['motion_span_ms'], motion_seed=rng.getrandbits(32),
                 heat_span_ms=p['heat_span_ms'], heat_seeds=[rng.getrandbits(32) for _ in range(N*N)],
                 workable=p['workable'], run_ms=180000, preview_ms=1200,
                 hammer_box=[25,390,120,44], title='Socket hatchet' if p['relief'] else 'Tapered blade')
    task_id = task['id']
    challenge_id = hashlib.sha256(f'{seed}|{task_id}|{REVISION}|{level}|{mode}'.encode()).hexdigest()[:18]
    public = dict(benchmark='gym_anything_rt', mechanic_id=MECHANIC_ID, task_id=task_id,
                  challenge_id=challenge_id, prompt='Gauge the concealed target die, then shape the moving billet while the metal glows.',
                  world=world, single_attempt=True, asset_manifest='shared_runtime/assets/provenance/ember_anvil_v3_v0.json',
                  generator=dict(name=REVISION, variant_count=10**18))
    truth = dict(mechanic_id=MECHANIC_ID, task_id=task_id, challenge_id=challenge_id,
                 seed=seed, world=copy.deepcopy(world), solution=solution, single_attempt=True)
    episode = episode_status(task_id)
    public.update(episode)
    truth.update(episode)
    if condition:
        public['control_condition'] = copy.deepcopy(condition)
        truth['control_condition'] = copy.deepcopy(condition)
    return public, truth
