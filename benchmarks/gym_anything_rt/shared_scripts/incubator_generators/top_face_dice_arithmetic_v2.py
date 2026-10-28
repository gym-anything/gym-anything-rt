"""Original, source-derived tumbler/gripper game. No solution plan ships to the UI."""
from __future__ import annotations
import copy
import hashlib
import random

MECHANIC_ID = 'top_face_dice_arithmetic_v2'
REVISION = 'tumbler-gripper-v1'
DEFAULT = dict(dice_count=3,travel=220,drive_speed=.34,spin_speed=.43,variation=.36,
               precession=.18,seal_radius=29,seal_seconds=.95,unload_gain=.08)
FACES = ('east','west','south','north','top','bottom')
COLORS = ['#42c5b4','#f0b74f','#e87771','#9892ec']


def roll(o, direction):
    t,b,n,s,e,w = (o[f] for f in ('top','bottom','north','south','east','west'))
    if direction == 'E': return dict(top=w,bottom=e,north=n,south=s,east=t,west=b)
    return dict(top=s,bottom=n,north=t,south=b,east=e,west=w)


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition') or (task.get('metadata') or {}).get('control_condition'))
    p = dict((condition or {}).get('difficulty_parameters') or DEFAULT)
    mode = (condition or {}).get('interaction','full')
    if mode not in ('full','simplified'): raise ValueError('Unsupported input surface')
    if set(p) != set(DEFAULT): raise ValueError('Incomplete tumbler profile')
    if type(p['dice_count']) is not int or not 2 <= p['dice_count'] <= 4: raise ValueError('Invalid dice count')
    bounds = dict(travel=(100,280),drive_speed=(.2,.55),spin_speed=(.2,.65),variation=(.1,.5),precession=(0,.4),seal_radius=(20,40),seal_seconds=(.5,1.5),unload_gain=(0,.15))
    for key,(low,high) in bounds.items():
        if not low <= p[key] <= high: raise ValueError('Invalid '+key)
    level = int((condition or {}).get('difficulty',3))
    digest=hashlib.sha256(f'{seed}|{MECHANIC_ID}|{REVISION}|d{level}'.encode()).digest()
    rng=random.Random(digest);dice=[]
    for i in range(p['dice_count']):
        o=dict(top=1,bottom=6,north=2,south=5,east=3,west=4)
        for _ in range(rng.randrange(12,30)): o=roll(o,rng.choice(('E','N')))
        dice.append(dict(id=f'die-{i}',label=chr(65+i),color=COLORS[i],faces=[o[f] for f in FACES],
            phase=rng.uniform(0,6.28318530718),spin=rng.uniform(0,6.28318530718),
            yaw=rng.uniform(-.45,.45),drive_seed=rng.getrandbits(32),spin_seed=rng.getrandbits(32),
            tilt_seed=rng.getrandbits(32),row_y=65+(i+.5)*390/p['dice_count']))
    # Four attainable faces per die; target draws only from those. No exact
    # face choice or timed route is exported as an answer.
    target=sum(rng.choice([d['faces'][j] for j in (0,1,4,5)]) for d in dice)
    public=dict(benchmark='gym_anything_rt',mechanic_id=MECHANIC_ID,revision=REVISION,
        task_id=task['id'],challenge_id=digest.hex()[:16],prompt='Track the tumblers. Clamp level top faces to balance the lot.',
        generator=dict(name=REVISION,variant_count=10**24),parameters=p,dice=dice,target_sum=target,
        stage=dict(width=960,height=520),physics=dict(tick_ms=20,gripper_speed=520,gripper_acceleration=2100,
        response=55,damping=14,level_cosine=.82,motor_span_ms=4200,max_ms=180000),
        initial_gripper=[480,490],submit_label='CERTIFY LOT',single_attempt=True,
        asset_manifest='shared_runtime/assets/provenance/top_face_dice_arithmetic_v2_v0.json')
    if condition:public['control_condition']=condition
    truth=copy.deepcopy(public);truth['seed']=str(seed)
    return public,truth
