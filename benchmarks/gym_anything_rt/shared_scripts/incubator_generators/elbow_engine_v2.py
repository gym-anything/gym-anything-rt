"""Seeded, planar underactuated swing-up. Original art; no source assets."""
from __future__ import annotations
import copy
import hashlib
import random

MECHANIC_ID = 'elbow_engine_v2'
BASELINE = {'target_height': 1.0, 'torque': 1.5, 'time_scale': 0.5}


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition') or task.get('metadata', {}).get('control_condition'))
    params = dict(condition['difficulty_parameters'] if condition else BASELINE)
    if set(params) != set(BASELINE) or not -.8 <= params['target_height'] <= 1.7 or not 1 <= params['torque'] <= 3 or not .25 <= params['time_scale'] <= .7:
        raise ValueError('unsupported elbow physics profile')
    rng = random.Random(int(hashlib.sha256(f'{seed}|elbow_engine_v2'.encode()).hexdigest(), 16))
    physics = {**params, 'length1': 1.0, 'length2': 1.0, 'mass1': 1.0,
               'mass2': round(rng.uniform(.9, 1.1), 5), 'inertia1': 1.0, 'inertia2': 1.0,
               'gravity': 9.8, 'disturbance_seed': rng.getrandbits(32), 'disturbance_fraction': .25, 'hold_ms': 1200, 'damping': .02, 'tick_ms': 20, 'max_ticks': 9000}
    initial = [round(rng.uniform(-.18, .18), 6) for _ in range(4)]
    identity = {'mechanic_id': MECHANIC_ID, 'task_id': task['id'],
                'challenge_id': hashlib.sha256(f'{seed}|{task["id"]}|{params}'.encode()).hexdigest()[:16]}
    shared = {**identity, 'physics': physics, 'initial': initial}
    if condition:
        shared['control_condition'] = condition
    public = {**copy.deepcopy(shared), 'benchmark': 'gym_anything_rt',
              'prompt': 'Keep the glowing tip above the height marker until the hold meter fills.',
              'generator': {'name': 'elbow_engine_v2_v0', 'variant_count': 10**12},
              'asset_manifest': 'environments/elbow_engine_v2_env/provenance.json'}
    truth = {**copy.deepcopy(shared), 'seed': seed}
    return public, truth
