"""Original seeded junction. Interaction never enters the world RNG."""
from __future__ import annotations
import copy
import hashlib
import json
import random

MECHANIC_ID = 'courtesy_junction_nonrealtime'
BASELINE_PARAMETERS = dict(lanes=3,cars_per_lane=3,speed_min=38,speed_max=56,yield_min=0.9,yield_max=2.0,turns=['left','right'],road_half=85)

def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition') or task.get('metadata',{}).get('control_condition'))
    if condition is None:
        condition = dict(difficulty=4,interaction='full',real_time='live',difficulty_parameters=copy.deepcopy(BASELINE_PARAMETERS))
    p = condition['difficulty_parameters']
    if condition['difficulty'] not in range(1,6) or condition['interaction'] not in ('full','simplified'):
        raise ValueError('invalid control condition')
    if set(p)!=set(BASELINE_PARAMETERS) or not 1<=p['lanes']<=3 or not 2<=p['cars_per_lane']<=4 or not 26<=p['speed_min']<=p['speed_max']<=65 or not .7<=p['yield_min']<=p['yield_max']<=2.4 or not 80<=p['road_half']<=100 or not p['turns'] or any(t not in ('left','right') for t in p['turns']):
        raise ValueError('invalid junction parameters')
    rng=random.Random(int(hashlib.sha256(f'{seed}|courtesy-junction-v1'.encode()).hexdigest()[:16],16))
    turn=rng.choice(p['turns']); traffic=[]
    for lane in range(p['lanes']):
        cycle=1500 if lane<2 else 1250
        gap=cycle/p['cars_per_lane']; phase=rng.uniform(-200,150)
        for i in range(p['cars_per_lane']):
            speed=round(rng.uniform(p['speed_min'],p['speed_max']),3)
            traffic.append(dict(id=f'car-{lane}-{i}',lane=lane,s=round(phase+i*gap-300,3),v=speed,cruise=speed,horizon=round(rng.uniform(p['yield_min'],p['yield_max']),3),decel=round(rng.uniform(42,62),3),cycle=cycle,braking=False,color=rng.choice(['#ee8c76','#78b5d8','#bd9be3','#9bce9a'])))
    # Avoid initial body overlap at the crossing as well as on each approach.
    def box(c):
        if c['lane']==0:return (c['s'],290,20,11)
        if c['lane']==1:return (900-c['s'],230,20,11)
        return (420,c['s'],11,20)
    for lane in range(p['lanes']):
        group=[c for c in traffic if c['lane']==lane]
        others=[c for c in traffic if c['lane']<lane]
        for attempt in range(100):
            overlap=False
            for c in group:
                x,y,rx,ry=box(c)
                for o in others:
                    xx,yy,rrx,rry=box(o)
                    if abs(x-xx)<=rx+rrx+15 and abs(y-yy)<=ry+rry+15:overlap=True
            if not overlap:break
            for c in group:c['s']=round(c['s']-70,3)
        else:raise RuntimeError('could not separate initial traffic')
    world=dict(width=900,height=520,road_half=p['road_half'],turn=turn,start=dict(x=480,y=470,a=-1.5707963267948966,v=0),traffic=traffic,physics=dict(tick_ms=20,max_ticks=6000,acceleration=28,brake=70,drag=5,max_speed=65,wheelbase=32,steer_angle=.55,length=40,width=22),goal=dict(x=15 if turn=='left' else 805,y=190 if turn=='left' else 260,width=80,height=70))
    token=json.dumps([str(seed),p],sort_keys=True)
    challenge=hashlib.sha256(token.encode()).hexdigest()[:16]
    common=dict(mechanic_id=MECHANIC_ID,task_id=task['id'],challenge_id=challenge,control_condition=condition,world=world)
    public={**copy.deepcopy(common),'benchmark':'gym_anything_rt','prompt':'Deliver the yellow car to the striped departure road. No contact. Stay on the road.','asset_manifest':'shared_runtime/assets/provenance/courtesy_junction_v0.json','generator':{'name':'responsive_junction_v1','variant_count':1000000000}}
    return public,{**copy.deepcopy(common),'seed':str(seed),'variant_count':1000000000}
