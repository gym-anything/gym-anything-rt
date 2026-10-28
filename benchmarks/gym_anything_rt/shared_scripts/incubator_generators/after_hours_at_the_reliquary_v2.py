"""Source-derived articulated ward key; generation is independent of input mode."""
from __future__ import annotations
import copy
import hashlib
import json
import random

MECHANIC_ID = 'after_hours_at_the_reliquary_v2'
BASE = dict(sockets=2,vertical=True,angle=True,span=True,radius=32,scan_speed=105,rate_amplitude=.35,rate_span_ms=2300,charge_ms=6500,lag_s=.09,view_count=5,loupe=True)


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition'))
    p = copy.deepcopy((condition or {}).get('difficulty_parameters') or BASE)
    if p['sockets'] not in (1,2) or not 3 <= p['view_count'] <= 5 or p['radius'] < 30:
        raise ValueError('invalid ward geometry')
    stable = hashlib.sha256((str(seed)+'|'+MECHANIC_ID+'|'+json.dumps(p,sort_keys=True)).encode()).hexdigest()
    rng = random.Random(int(stable,16))
    roles = ['door','cabinet','desk','gallery','radiator'][:p['view_count']]
    # Clearances use the generated artwork's actual bounds, including opened lids.
    targets = [dict(id='handle',view=1,rect=[180+rng.randrange(-20,21),290,150,80],item='handle'),
               dict(id='wire',view=2 if p['view_count']<5 else 4,rect=[670+rng.randrange(-20,21),210,130,110],item='wire')]
    if p['loupe']:
        targets += [dict(id='frame',view=2,rect=[620,110,160,85],item='frame'),
                    dict(id='glass',view=1,rect=[590,270,160,90],item='glass')]
    recipes = [dict(inputs=['handle','wire'],output='key')]
    if p['loupe']: recipes += [dict(inputs=['frame','glass'],output='loupe')]
    world = dict(width=1000,height=500,tick_ms=20,run_ms=90000,leak=3,
                 x_bounds=[300,700],y_bounds=[210,290],
                 seeds=[rng.getrandbits(32) for _ in range(4)],
                 phase_x=rng.uniform(0,800),phase_y=rng.uniform(0,160),
                 offset_ms=rng.randrange(0,12000),
                 initial=dict(x=500.,y=400.,angle=0.,span=320.),
                 speed=650.,angle_speed=180.,span_speed=450.)
    public=dict(benchmark='gym_anything_rt',mechanic_id=MECHANIC_ID,task_id=task['id'],
                challenge_id='rel2-'+stable[:18],parameters=p,world=world,views=roles,targets=targets,recipes=recipes,
                mural=dict(view=3 if p['view_count']>=4 else 2,rect=[350,110,240,180]),
                ignition=dict(view=0,rect=[455,270,90,95]),
                tray=dict(left=.02,width=.14,gap=.02,top=.08,height=.84),
                asset_manifest='shared_runtime/assets/provenance/'+MECHANIC_ID+'_v0.json',
                prompt='AFTER HOURS AT THE RELIQUARY V2',
                generator=dict(name='articulated_ward_key_v1',variant_count=10**18),
                physics_revision='articulated-ward-v1')
    if condition: public['control_condition']=condition
    truth=copy.deepcopy(public);truth['seed']=str(seed)
    return public,truth
