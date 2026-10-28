"""Seeded living bridges. Interaction and execution mode never sample the world."""
import copy
import hashlib
import random

MECHANIC_ID = 'living_scaffold_v3'
PROFILES = {
    1: dict(bridges=1, gravity=400, wind=18, wind_span_ms=6500, blossom_radius=38, blossom_sway=10, blossom_span_ms=7000, coupling=0, slew=.48),
    2: dict(bridges=1, gravity=450, wind=25, wind_span_ms=6000, blossom_radius=34, blossom_sway=16, blossom_span_ms=6200, coupling=0, slew=.42),
    3: dict(bridges=2, gravity=450, wind=28, wind_span_ms=5700, blossom_radius=32, blossom_sway=18, blossom_span_ms=5800, coupling=0, slew=.42),
    4: dict(bridges=2, gravity=500, wind=34, wind_span_ms=5200, blossom_radius=30, blossom_sway=20, blossom_span_ms=5200, coupling=.16, slew=.38),
    5: dict(bridges=3, gravity=550, wind=40, wind_span_ms=4800, blossom_radius=28, blossom_sway=22, blossom_span_ms=4800, coupling=.24, slew=.34),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition'))
    level = int((condition or {}).get('difficulty', 5))
    mode = (condition or {}).get('interaction', 'full')
    if level not in PROFILES or mode not in ('full', 'simplified'):
        raise ValueError('Unsupported living bridge condition')
    p = copy.deepcopy((condition or {}).get('difficulty_parameters') or PROFILES[level])
    if p != PROFILES[level]:
        raise ValueError('Living bridge profile differs from its declared level')
    rng = random.Random(hashlib.sha256(f'{MECHANIC_ID}|{seed}|{level}|v1'.encode()).digest())
    # Separate sampling preserves every pre-repair wind, blossom and pod value.
    discovery = random.Random(hashlib.sha256(f'{MECHANIC_ID}|{seed}|{level}|fruit'.encode()).digest())
    world = dict(dt_ms=10, max_ms=180000, width=960, height=700, anchor_x=105,
                 initial_length=350, final_length=530, growth_speed=100, radius=13,
                 skin_radius=10, max_angle=.27, drag=.12,
                 capture_speed=210, parameters=p, lanes=[])
    anchors = {1:[270], 2:[200,470], 3:[170,345,520]}[p['bridges']]
    for i in range(p['bridges']):
        world['lanes'].append(dict(id=i, anchor_y=anchors[i],
            initial_s=rng.uniform(95, 220), initial_v=rng.uniform(-7, 7),
            wind_seed=rng.getrandbits(32), blossom_seed=rng.getrandbits(32),
            blossom_offset=92 + rng.uniform(-2, 2),
            color=['#df815d', '#65a995', '#a58cc3'][i]))
        # Both are behind every starting pod. Their contact bands are disjoint;
        # inspecting the sheath changes where the player must brake and reverse.
        world['lanes'][-1]['feed_s'] = discovery.choice([20, 68])
    public = dict(benchmark='gym_anything_rt', mechanic_id=MECHANIC_ID,
        task_id=task['id'], challenge_id=hashlib.sha256(f'{MECHANIC_ID}|{seed}|d{level}|v1'.encode()).hexdigest()[:16],
        world=world, control_condition=condition,
        prompt='Restore every moving blossom. Inspect the leaf sheaths to learn what each living bridge needs. A fallen pod ends this attempt.',
        asset_manifest='shared_runtime/assets/provenance/living_scaffold_v3_v0.json',
        generator=dict(name='living_scaffold_v3_inspectable_growing_bridges_v1', variant_count=10**18))
    return public, dict(copy.deepcopy(public), seed=seed, source_anchors=['IND-082', 'VGE-543'])
