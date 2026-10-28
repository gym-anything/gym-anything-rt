from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = 'parallel_grillmaster_v2'
KINDS = ('steak', 'egg', 'chicken', 'potato', 'sausage', 'naan', 'corn', 'fish')


def generate(task, seed):
    rng = random.Random(hashlib.sha256(f'{seed}|{MECHANIC_ID}'.encode()).digest())
    condition = task.get('_control_condition')
    parameters = (condition or {}).get('difficulty_parameters', {})
    count = int(parameters.get('food_count', 8))
    if not 3 <= count <= 8:
        raise ValueError('food count must be between three and eight')
    times = list(parameters.get('target_times_ms', range(8000, 16000, 1000)))
    if len(times) != count:
        raise ValueError('one cooking target is required per food')
    rng.shuffle(times)
    foods = []
    for index, kind in enumerate(KINDS[:count]):
        foods.append(dict(id=f'food-{index}', kind=kind, target_ms=times[index],
            tolerance_ms=min(parameters.get('tolerance_ms_values', [550])),
            heat_seed=rng.getrandbits(32), heat_span_ms=1400, heat_amplitude=.65))
    rng.shuffle(foods)
    parallel_count = int(parameters.get('parallel_start_count', count))
    window_ms = int(parameters.get('parallel_start_window_ms') or 3200)
    start_rule = f'Start at least {parallel_count} foods within {window_ms / 1000:g} seconds. ' if parallel_count > 1 else ''
    public = dict(benchmark='gym_anything_rt', mechanic_id=MECHANIC_ID,
        task_id=task['id'], challenge_id=hashlib.sha256(f'{seed}|{task["id"]}'.encode()).hexdigest()[:14],
        prompt=start_rule+'Watch the changing heat and serve each during its golden window. One spoiled item ends the attempt.',
        foods=foods, parallel_count=parallel_count,
        parallel_window_ms=window_ms,
        asset_manifest='shared_runtime/assets/provenance/interaction_first_five_v0.json',
        generator=dict(name='parallel_grillmaster_v2_variable_heat', variant_count=10**18))
    if condition:
        public['control_condition'] = copy.deepcopy(condition)
    truth = copy.deepcopy(public)
    truth['seed'] = seed
    return public, truth
