"""Original card-golf transformation of survey IND-070; no source assets copied."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "cloudstep_caddie_v2"
PHYSICS_REVISION = "drifting-golf-v2"
PROFILES = {
    1: dict(greens=2, course_width=360, half_width=64, half_depth=52, motion_x=32, motion_y=42, motion_span_ms=4000, wind=0, inherit=0, elevation=0, decoys=0, cup_radius=32),
    2: dict(greens=4, half_width=57, half_depth=46, motion_x=32, motion_y=42, motion_span_ms=3200, wind=5, inherit=.15, elevation=20, decoys=1, cup_radius=28),
    3: dict(greens=5, half_width=48, half_depth=39, motion_x=38, motion_y=51, motion_span_ms=2700, wind=10, inherit=.3, elevation=35, decoys=2, cup_radius=26),
    4: dict(greens=6, half_width=41, half_depth=34, motion_x=44, motion_y=60, motion_span_ms=2500, wind=16, inherit=.45, elevation=45, decoys=2, cup_radius=24),
    5: dict(greens=6, half_width=35, half_depth=29, motion_x=50, motion_y=68, motion_span_ms=2300, wind=24, inherit=.6, elevation=60, decoys=3, cup_radius=22),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition') or task.get('metadata', {}).get('control_condition'))
    difficulty = int((condition or {}).get('difficulty', 5))
    if difficulty not in PROFILES:
        raise ValueError('difficulty must be 1..5')
    profile = copy.deepcopy(PROFILES[difficulty])
    profile.update((condition or {}).get('difficulty_parameters', {}))
    mode = (condition or {}).get('interaction', 'full')
    if mode not in ('full', 'simplified'):
        raise ValueError('invalid interaction')
    if condition is None:
        condition = dict(difficulty=difficulty, interaction=mode, real_time='live', difficulty_parameters=copy.deepcopy(profile))
    # Retain the original world salt so collision repairs preserve seed worlds.
    rng = random.Random(hashlib.sha256(f'{seed}|{MECHANIC_ID}|drifting-golf-v1'.encode()).digest())
    count = profile['greens']
    mirror = rng.choice((False, True))
    greens, route = [], []
    for i in range(count):
        width = profile.get('course_width', 780)
        x = (1000 - width) / 2 + width * i / (count - 1)
        y = 260 if i == 0 else (360 if i % 2 else 180)
        z = (i // 2) * profile['elevation']
        if mirror:
            x = 1000 - x
        item = dict(id=f'green-{i}', center=[round(x, 3), y, z],
                    half=[profile['half_width'], profile['half_depth']],
                    surface='cup' if i == count-1 else ('sand' if i % 2 else 'fairway'),
                    motion=dict(seed=rng.getrandbits(32), span_ms=profile['motion_span_ms'],
                                amplitude=[profile['motion_x'] if i else 0, profile['motion_y'] if i else 0]))
        greens.append(item); route.append(item['id'])
    # Readable off-route sand banks: geometric choices, never hidden target flags.
    for i in range(profile['decoys']):
        x = 265 + i * 190
        if mirror: x = 1000-x
        greens.append(dict(id=f'bank-{i}', center=[x, 60 if i % 2 == 0 else 470, profile['elevation']],
                           half=[profile['half_width'], profile['half_depth']], surface='sand',
                           motion=dict(seed=rng.getrandbits(32), span_ms=profile['motion_span_ms']+300,
                                       amplitude=[profile['motion_x'], profile['motion_y']*.35])))
    cards = []
    for i in range(count-1):
        # Low chips from turf; sand needs a loft to get out. The hand constrains
        # both elevation and the order of terrain transitions.
        kind = 'loft' if i % 2 else 'chip'
        cards.append(dict(id=f'card-{i}', kind=kind, label='LOFT' if kind=='loft' else 'CHIP',
                          vz=300 if kind=='loft' else 240, seconds=1.5 if kind=='loft' else 1.2,
                          max_speed=440 if count<=3 else 380))
    rng.shuffle(cards)
    world = dict(greens=greens, cards=cards, tee=route[0], cup=route[-1], cup_radius=profile['cup_radius'],
                 physics=dict(tick_ms=10, gravity=400, radius=7, wind=profile['wind'],
                              wind_seed=rng.getrandbits(32), wind_span_ms=2400, inherit=profile['inherit'],
                              play_time_ms=180000), map=dict(width=1000, height=540), forecast_ms=2160)
    task_id = task.get('id', MECHANIC_ID+'_seed_0001@0.1')
    challenge_revision = 'drifting-golf-v2-low-profile-20261006' if difficulty <= 2 else PHYSICS_REVISION
    public = dict(benchmark='gym_anything_rt', mechanic_id=MECHANIC_ID, task_id=task_id,
                  challenge_id=hashlib.sha256(f'{seed}|d{difficulty}|{challenge_revision}'.encode()).hexdigest()[:20],
                  physics_revision=PHYSICS_REVISION, world=world, control_condition=condition,
                  prompt=('Use the single chip to intercept the drifting cup.' if count == 2 else
                          'Spend the exact hand. Land on drifting greens, then sink the ball.'),
                  single_attempt=True, asset_manifest='shared_runtime/assets/provenance/cloudstep_caddie_v2_v0.json',
                  generator=dict(name='drifting_card_golf_v1', variant_count=10**18))
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), oracle_route=route)
    return public, truth
