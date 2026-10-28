"""Privileged coordinate planner. Transport owns all actual mouse/keyboard input.

Exact current state and seeded motion are read for planning; these are not model
scores or screenshot-only policy demonstrations. No success or physics mutation.
"""
from __future__ import annotations

import copy
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.cloudstep_caddie_v2 import Physics,center,velocity,wind


def intercept(world, snapshot, card, target_id, delay_ms=0):
    if not snapshot['support']:return None
    greens={g['id']:g for g in world['greens']};origin=greens[snapshot['support']];target=greens[target_id]
    ms=snapshot['tick']*10+delay_ms
    before=center(origin,snapshot['tick']*10);now=center(origin,ms)
    p=[snapshot['p'][i]+now[i]-before[i] for i in range(3)]
    inherited=velocity(origin,ms);s=world['physics'];wx=[0.,0.];displacement=[0.,0.]
    previous=p[2]
    for k in range(1,301):
        h=k*.01;z=p[2]+card['vz']*h-s['gravity']*.00005*k*(k+1)
        w=wind(world,ms+k*10)
        for i in (0,1):wx[i]+=w[i]*.01;displacement[i]+=wx[i]*.01
        if previous>=target['center'][2] and z<=target['center'][2] and card['vz']-s['gravity']*h<0:
            f=(previous-target['center'][2])/(previous-z)
            seconds=(k-1+f)*.01;landing=center(target,ms+(k-1+f)*10)
            # Fractional last integration step agrees with swept plane contact.
            drift=[displacement[i]-wx[i]*.01*(1-f) for i in (0,1)]
            v=[(landing[i]-p[i]-drift[i])/seconds-s['inherit']*inherited[i] for i in (0,1)]
            aim=[p[i]+v[i]*card['seconds'] for i in (0,1)]
            if math.hypot(*v)>card['max_speed']*.99 or not 0<=aim[0]<=1000 or not 0<=aim[1]<=540:return None
            return aim
        previous=z
    return None


def simulation_trace(public,truth,policy='timely',delay_ms=0):
    sim=Physics(truth['world']);mode=public['control_condition']['interaction'];source='card_drag' if mode=='full' else 'card_click';events=[]
    def record(k,**kw):events.append(dict(seq=len(events)+1,tick=sim.tick,kind=k,**kw))
    sim.active=True;record('start',input_source='start_button')
    for i,target in enumerate(truth['oracle_route'][1:]):
        card=sim.cards[f'card-{i}']
        if policy=='parked':break
        if policy=='nominal':aim=sim.greens[target]['center'][:2]
        else:aim=intercept(sim.world,sim.snapshot(),card,target)
        if aim is None:break
        sim.advance(sim.tick+delay_ms//10)
        if sim.failed:break
        record('drag_start' if mode=='full' else 'select',card_id=card['id'],input_source=source)
        record('shot',card_id=card['id'],point=aim,input_source=source)
        try:sim.shot(card['id'],aim)
        except ValueError:events.pop();record('cancel',input_source=source);break
        while not sim.support and not sim.failed:sim.advance(sim.tick+10)
        if sim.failed or sim.support!=target:break
    record('seal',input_source='certify_button')
    result={k:copy.deepcopy(public[k]) for k in ['mechanic_id','task_id','challenge_id','physics_revision','control_condition']}
    result.update(interaction_mode=mode,events=events,final_state=sim.snapshot(),completed=sim.sunk and not sim.failed)
    return result


def box(ui,selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def solve(ui,truth,*,delay_ms=40,timeout_seconds=160):
    mode=truth['control_condition']['interaction'];world=truth['world'];rect=box(ui,'#cc-map')
    def screen(p):return [rect[0]+p[0]*rect[2]/1000,rect[1]+p[1]*rect[3]/540]
    r=box(ui,'#cc-start');ui.send([{'mouse':{'left_click':[r[0]+r[2]/2,r[1]+r[3]/2]}}])
    deadline=time.monotonic()+timeout_seconds
    for i,target in enumerate(truth['oracle_route'][1:]):
        while time.monotonic()<deadline:
            snap=ui.read('cloudstepCaddieV2Model.sim.snapshot()')
            if snap['failed']:raise AssertionError(snap)
            if snap['support']==target or snap['sunk']:break
            if snap['support']:
                card=next(c for c in world['cards'] if c['id']==f'card-{i}')
                aim=intercept(world,snap,card,target,delay_ms)
                if aim is not None:
                    r=box(ui,f'[data-card="{card["id"]}"]');start=[r[0]+r[2]/2,r[1]+r[3]/2];end=screen(aim)
                    if mode=='full':actions=[{'mouse':{'move':start,'buttons':{'left_down':True}}},{'mouse':{'move':end}},{'mouse':{'buttons':{'left_up':True}}}]
                    else:actions=[{'mouse':{'left_click':start}},{'mouse':{'left_click':end}}]
                    ui.send(actions)
            ui.wait(.10)
        else:raise AssertionError('No reachable stroke before deadline')
    r=box(ui,'#cc-seal');ui.send([{'mouse':{'left_click':[r[0]+r[2]/2,r[1]+r[3]/2]}}])
