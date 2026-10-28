"""Action-clock counterpart of the evaluated kinetic gesture gallery."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = 'museum_of_lost_gestures_nonrealtime'
DONOR_MECHANIC_ID = 'museum_of_lost_gestures_v2'
REVISION = 'kinetic-traces-2'
ACTION_STEP_MS = 20
PROFILES = {
    1: dict(tools=1, radius=68, span_ms=4000, changing_grip=True),
    2: dict(tools=1, radius=62, span_ms=3800, changing_grip=True),
    3: dict(tools=2, radius=56, span_ms=3600, changing_grip=True),
    4: dict(tools=2, radius=48, span_ms=3000, changing_grip=True),
    5: dict(tools=3, radius=44, span_ms=2500, changing_grip=True),
}
SETTINGS = dict(play_time_seconds=90, observation_window_ms=240, frames_per_observation=4)


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition') or task.get('metadata', {}).get('control_condition'))
    level = (condition or {}).get('difficulty', 5)
    params = copy.deepcopy((condition or {}).get('difficulty_parameters') or PROFILES[level])
    if level not in PROFILES or params != PROFILES[level]:
        raise ValueError('unsupported kinetic gallery profile')
    mode = (condition or {}).get('interaction', 'full')
    if mode not in ('full', 'simplified'):
        raise ValueError('unsupported gallery interaction')
    # Keep counterpart seeds paired with the evaluated donor's puzzle content.
    rng = random.Random(hashlib.sha256(f'{seed}|{DONOR_MECHANIC_ID}|{REVISION}|{level}'.encode()).digest())
    tracks = []
    for index in range(params['tools']):
        left = 20 + (3 - params['tools']) * 174 + index * 348
        knots, t = [], 0
        side = rng.randrange(2)
        for k in range(70):
            x = rng.uniform(64, 76) if (k + side) % 2 == 0 else rng.uniform(260, 272)
            y = rng.uniform(90, 320)
            grip = rng.choice((0, 2)) if params['changing_grip'] else 0
            knots.append(dict(t_ms=t, point=[round(x, 3), round(y, 3)], grip=grip))
            t += round(params['span_ms'] * rng.uniform(.85, 1.15))
        tracks.append(dict(id=f'trace-{index+1}', name=['Lingering Touch', 'Other Hand', 'Together Apart'][index],
                           rect=[left, 60, 336, 390], knots=knots,
                           initial_point=[168, 210], initial_grip=0))
    world = dict(revision=REVISION, parameters=params, width=1084, height=520, tracks=tracks,
                 tick_ms=20, action_step_ms=ACTION_STEP_MS, tip_radius=8, pickup_radius=22, charge_seconds=6,
                 charge_cap=6.5, decay=1.5, speed=480, acceleration=2400,
                 spring=110, damping=20, guide_ms=1200, deadline_ms=80000)
    task_id = task.get('id', MECHANIC_ID + '_seed_0001@0.1')
    challenge = hashlib.sha256(f'{seed}|{task_id}|{condition}|{REVISION}'.encode()).hexdigest()[:18]
    common = dict(mechanic_id=MECHANIC_ID, task_id=task_id, challenge_id=challenge, world=world)
    public = dict(copy.deepcopy(common), benchmark='gym_anything_rt',
                  prompt='Keep the whole dark tip inside every moving memory ring, with the shown hand. Fill all traces together. The gallery advances by one fixed simulation slice after each deliberate input; idle waiting leaves it unchanged.',
                  submit_label='Close the exhibition', single_attempt=True,
                  asset_manifest='shared_runtime/assets/provenance/museum_of_lost_gestures_v2_v0.json',
                  generator=dict(name=MECHANIC_ID, version=REVISION))
    truth = dict(copy.deepcopy(common), seed=seed)
    if condition:
        public['control_condition'] = copy.deepcopy(condition)
        truth['control_condition'] = copy.deepcopy(condition)
    return public, truth
