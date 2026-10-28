"""Original maglev quarry: continuously moving, geometrically sealed ore racks."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "minecraft_block_grid_v2"
REVISION = "moving-quarry-4"
PROFILES = {
    1: dict(lanes=1, waves=2, speed=.34, speed_variation=.24, velocity_span_ms=6000, plug_depth=1, wave_gap_ms=40000),
    2: dict(lanes=1, waves=2, speed=.48, speed_variation=.35, velocity_span_ms=5000, plug_depth=1, wave_gap_ms=30000),
    3: dict(lanes=2, waves=2, speed=.58, speed_variation=.40, velocity_span_ms=4200, plug_depth=1, wave_gap_ms=27000),
    4: dict(lanes=2, waves=2, speed=.70, speed_variation=.45, velocity_span_ms=3500, plug_depth=2, wave_gap_ms=24000),
    5: dict(lanes=3, waves=2, speed=.82, speed_variation=.50, velocity_span_ms=3000, plug_depth=2, wave_gap_ms=22000),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition') or (task.get('metadata') or {}).get('control_condition'))
    if condition is None:
        condition = dict(difficulty=3, interaction='full', real_time='live', difficulty_parameters=PROFILES[3])
    level = condition.get('difficulty')
    if type(level) is not int or level not in PROFILES or condition.get('interaction') not in ('full', 'simplified'):
        raise ValueError('invalid quarry condition')
    p = dict(condition['difficulty_parameters'])
    if p != PROFILES[level]:
        raise ValueError('quarry parameters must match a declared difficulty profile')
    rng = random.Random(hashlib.sha256(f'{seed}|{MECHANIC_ID}|{REVISION}|d{level}'.encode()).digest())
    racks, voxels = [], []
    for wave in range(p['waves']):
        for lane in range(p['lanes']):
            name = f'rack-{wave}-{lane}'
            # Racks are disjoint in world space. Their isometric projections can
            # occlude one another; the same sorted polygons resolve those hits.
            y = (lane-(p['lanes']-1)/2)*5.2
            direction = rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
            rack = dict(id=name, lane=lane, y=y, spawn_ms=wave*p['wave_gap_ms']+rng.randint(0, 1400),
                        velocity_seed=rng.getrandbits(32), speed=p['speed']*rng.uniform(.93, 1.07),
                        speed_variation=p['speed_variation'], velocity_span_ms=p['velocity_span_ms'])
            racks.append(rack)
            def add(local, material, tag):
                voxels.append(dict(id=f'{name}-{tag}', rack=name, local=list(local), material=material))
            add((0, 0, 1), 'ore', 'ore')
            add((0, 0, 0), 'support', 'foot')
            add((0, 0, 2), 'support', 'roof')
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                add((dx, dy, 1), 'stone' if (dx, dy) == direction else 'support', f'side-{dx}-{dy}')
            if p['plug_depth'] == 2:
                add((direction[0]*2, direction[1]*2, 1), 'stone', 'outer-plug')
                # A removable casing seals every face of the inner plug.
                # Excavation opens a physical viewing path through both layers.
                dx, dy = direction
                add((dx, dy, 0), 'stone', 'casing-foot')
                add((dx, dy, 2), 'stone', 'casing-roof')
                for sign in (-1, 1):
                    add((dx-sign*dy, dy+sign*dx, 1), 'stone', f'casing-wall-{sign}')
    public = dict(benchmark='gym_anything_rt', mechanic_id=MECHANIC_ID, revision=REVISION,
                  task_id=task['id'], challenge_id=hashlib.sha256(f'{seed}|{REVISION}|d{level}'.encode()).hexdigest()[:16],
                  prompt='Excavate every cyan ore core from the moving racks. Preserve the gold supports.',
                  stage=dict(width=1080, height=530), racks=racks, voxels=voxels,
                  travel=dict(entry_x=-5.6, exit_x=5.6), control_condition=condition,
                  target_count=len(racks), single_attempt=True,
                  asset_manifest='shared_runtime/assets/provenance/minecraft_block_grid_v2_v0.json',
                  generator=dict(name=REVISION, variant_count=10**18))
    truth = copy.deepcopy(public)
    truth['seed'] = str(seed)
    return public, truth
