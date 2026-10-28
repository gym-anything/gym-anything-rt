"""Original XART-290 adaptation: a finite clean grid feeding changing island loads."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = 'last_carbon_isles_v2'
REVISION = 'tidal-dispatch-2'
PROFILES = {
    1: dict(island_count=2, amplitude=27, span_s=9.0, battery=58, inertia_s=.20, cross_amplitude=0),
    2: dict(island_count=2, amplitude=32, span_s=7.0, battery=46, inertia_s=.35, cross_amplitude=0),
    3: dict(island_count=3, amplitude=25, span_s=7.0, battery=38, inertia_s=.50, cross_amplitude=0),
    4: dict(island_count=4, amplitude=17, span_s=6.5, battery=29, inertia_s=.65, cross_amplitude=0),
    5: dict(island_count=4, amplitude=18, span_s=5.5, battery=24, inertia_s=.85, cross_amplitude=3),
}
NAMES = [('Cinder Key', '#ffa67c'), ('Morrow Atoll', '#f4d981'),
         ('Vesper Isle', '#92dfb6'), ('Lumen Shoal', '#9cc9ff')]


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition') or {
        'difficulty': 5, 'interaction': 'full', 'real_time': 'live',
        'difficulty_parameters': PROFILES[5]})
    level = int(condition['difficulty'])
    if level not in PROFILES or condition['interaction'] not in ('full', 'simplified'):
        raise ValueError('unsupported carbon-isles condition')
    parameters = dict(PROFILES[level])
    parameters.update(condition.get('difficulty_parameters') or {})
    if parameters != PROFILES[level]:
        raise ValueError('carbon-isles profiles have a fixed physical contract')
    rng = random.Random(hashlib.sha256(f'{seed}|{MECHANIC_ID}|{REVISION}'.encode()).digest())
    n = parameters['island_count']
    names = list(NAMES)
    rng.shuffle(names)
    islands = [dict(id=f'isle-{i}', name=names[i][0], color=names[i][1],
                    initial_share=96/n, battery_capacity=parameters['battery']) for i in range(n)]
    # Each mode transfers demand between isles, conserving the archipelago's 96 MW.
    # Smooth, nonrepeating knots; no jumps, deadline tricks, or hidden random impulses.
    vectors = [[1, -1]] if n == 2 else ([[1, -1, 0], [0, 1, -1]] if n == 3 else
              [[1, -1, 0, 0], [0, 0, 1, -1], [1, 1, -1, -1]])
    modes = []
    for index, vector in enumerate(vectors):
        span = parameters['span_s'] * (1 + index*.23)
        amplitude = parameters['amplitude'] if index < 2 else parameters['cross_amplitude']
        if n == 3:
            amplitude *= .62
        values = []
        times = [0.]
        sign = rng.choice((-1, 1))
        for k in range(16):
            values.append(round(sign*rng.uniform(.78, 1), 6))
            sign *= -1
            times.append(round(times[-1]+span*rng.uniform(.70,1.30),6))
        modes.append(dict(vector=vector, amplitude=amplitude, span_s=span,
                          offset_s=round(rng.uniform(.8, times[1]*.8), 6),
                          knots=values, times=times[:len(values)]))
    condition['difficulty_parameters'] = parameters
    public = dict(benchmark='gym_anything_rt', mechanic_id=MECHANIC_ID,
        task_id=task['id'], challenge_id=hashlib.sha256(
            f'{seed}|{level}|{REVISION}'.encode()).hexdigest()[:16],
        revision=REVISION, control_condition=condition, islands=islands, modes=modes,
        capacity=100., total_load=96., run_seconds=42., step_s=.02,
        parameters=parameters, forecast_s=1.5,
        source_anchors=['XART-290'],
        asset_manifest=f'shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json',
        generator=dict(name=REVISION, variant_count=10**12),
        prompt='Retire every coal works without stopping its crews. Share a 100 MW clean grid '
               'between the changing island loads. Green supply and batteries must cover every '
               'load throughout the transition. An empty battery ends the attempt. '
               'Requests above 100 MW share that same budget proportionally; they create no energy. '
               'Inspect and adjust before launch. Live power corrections remain available until '
               'a battery empties. CERTIFY NOW commits the current transition. The first empty '
               'battery or rejected certification ends the episode.')
    truth = copy.deepcopy(public)
    truth['seed'] = seed
    return public, truth
