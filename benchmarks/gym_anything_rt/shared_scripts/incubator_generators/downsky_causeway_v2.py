"""Independent skymaze-inspired descending terraces; no source assets or code."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import random

MECHANIC_ID = 'downsky_causeway_v2'
REVISION = 'drifting-descent-v1'
PROFILES = {
    1: dict(half_width=1.75, lateral_offset=2.2, drift=.60, span_ms=6500, wind=.4, response=6., acceleration=18.),
    2: dict(half_width=1.60, lateral_offset=2.0, drift=.70, span_ms=5700, wind=.6, response=5.3, acceleration=16.),
    3: dict(half_width=1.45, lateral_offset=1.8, drift=.80, span_ms=5000, wind=.9, response=4.6, acceleration=14.),
    4: dict(half_width=1.30, lateral_offset=1.65, drift=.90, span_ms=4400, wind=1.2, response=4., acceleration=12.),
    5: dict(half_width=1.15, lateral_offset=1.5, drift=1., span_ms=3800, wind=1.6, response=3.4, acceleration=10.),
}


def episode_failure():
    directory = os.environ.get('GYM_ANYTHING_RT_STATE_DIR', '/tmp/gym_anything_rt')
    try:
        with (Path(directory)/'attempts.jsonl').open(encoding='utf-8') as journal:
            for line in journal:
                if line.strip() and not json.loads(line).get('server_grade', {}).get('passed'):
                    return 'A failed submission already ended this episode.'
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError, ValueError, AttributeError):
        return 'Episode failure history is unavailable.'
    return ''


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition') or task.get('metadata', {}).get('control_condition') or {})
    level = int(condition.get('difficulty', 5))
    if level not in PROFILES or condition.get('interaction', 'full') not in ('full', 'simplified'):
        raise ValueError('Unsupported Downsky condition.')
    parameters = dict(PROFILES[level])
    parameters.update(condition.get('difficulty_parameters') or {})
    if parameters != PROFILES[level]:
        raise ValueError('Parameters must match the declared difficulty profile.')
    rng = random.Random(int(hashlib.sha256(f'{MECHANIC_ID}|{seed}'.encode()).hexdigest()[:16], 16))
    decks = []
    x = 0.
    handedness = rng.choice([-1, 1])
    for i in range(7):
        length = 7.6 if i == 0 else 7.2
        base = 0. if i in (0, 6) else handedness * (1 if i % 2 else -1) * parameters['lateral_offset']
        decks.append(dict(id=i, x0=round(x, 4), x1=round(x+length, 4), z=round((6-i)*1.8, 4),
                          base_y=base, half_width=parameters['half_width'],
                          motion_seed=rng.getrandbits(32), amplitude=0. if i == 0 else parameters['drift'],
                          span_ms=parameters['span_ms'] + rng.randrange(-300, 301)))
        x += length + .16
    world = dict(revision=REVISION, parameters=parameters, decks=decks, tick_ms=10,
                 forward_speed=1.8, max_lateral_speed=5.2, gravity=5.5, radius=.18,
                 response=parameters['response'], acceleration=parameters['acceleration'],
                 wind_seed=rng.getrandbits(32), wind=parameters['wind'], wind_span_ms=3100,
                 max_ms=300000, crossing_limit_ms=65000, finish_x=decks[-1]['x1']-1.,
                 finish_half_width=parameters['half_width']-.22,
                 initial=dict(x=.7, y=0., z=decks[0]['z']))
    challenge_id = hashlib.sha256(f'{seed}|{MECHANIC_ID}|d{level}|{REVISION}'.encode()).hexdigest()[:16]
    common = dict(mechanic_id=MECHANIC_ID, task_id=task['id'], challenge_id=challenge_id,
                  world=world, control_condition=condition, single_attempt=True,
                  episode_failed=bool(episode_failure()))
    public = dict(common, benchmark='gym_anything_rt', prompt='Downsky Causeway V2',
                  submit_label='CERTIFY ARRIVAL', stage=dict(width=1100, height=610),
                  generator=dict(name=REVISION, variant_count=2**32))
    truth = dict(common, seed=str(seed))
    return copy.deepcopy(public), copy.deepcopy(truth)
