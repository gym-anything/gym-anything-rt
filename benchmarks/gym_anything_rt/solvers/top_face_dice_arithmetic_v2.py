"""Privileged feedback oracle. Gameplay actions use the caller's action API.

The native caller is frozen HTTP POST /act. State and DOM reads are read-only
planning, not a screenshot-only model. No mutation, direct game calls or focus.
"""
from __future__ import annotations
import copy
import itertools
import math
import time
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.top_face_dice_arithmetic_v2 import advance,pose


def center(ui,selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()')


def click(ui,point):return ui.send([{'mouse':{'left_click':[round(point[0]),round(point[1])]}}])


def feasible(c,s,index,value):
    rest=[sorted({c['dice'][j]['faces'][k] for k in (0,1,4,5)}) for j,q in enumerate(s['dice']) if j!=index and not q['captured']]
    return any(s['sum']+value+sum(v)==c['target_sum'] for v in itertools.product(*rest))


def solve(ui,truth):
    paused=getattr(ui,'execution_mode','live')=='paused';mode=truth['control_condition']['interaction']
    rect=ui.read('(() => {const r=document.querySelector("#tfd-canvas").getBoundingClientRect();return [r.x,r.y,r.width,r.height];})()')
    def screen(p):return [round(rect[0]+p[0]*rect[2]/960),round(rect[1]+p[1]*rect[3]/520)]
    def state():return ui.read('({s:topFaceDiceV2Model.sim,grade:topFaceDiceV2Model.serverGrade,terminal:topFaceDiceV2Model.terminal})')
    click(ui,center(ui,'#tfd-start'))
    deadline=time.monotonic()+190;held=False;chosen=None;calls=0
    while time.monotonic()<deadline:
        row=state();s=row['s']
        if s['terminal']:
            assert not s['failed'],row
            break
        if chosen is None or s['dice'][chosen]['captured']:
            # Independent replay predicts the next attainable orientation solely
            # for privileged planning. Actual tracking still uses fresh state.
            chosen=None;best=math.inf
            for i,q in enumerate(s['dice']):
                if q['captured']:continue
                future=copy.deepcopy(s)
                for k in range(s['tick']+60,s['tick']+1501,10):
                    advance(future,truth,k);v=pose(truth,future,i)
                    if v['level']>.91 and feasible(truth,s,i,v['top']):
                        cost=k-s['tick']+math.dist(s['gripper'],[v['x'],v['y']])*.12
                        if cost<best:chosen,best=i,cost
                        break
            assert chosen is not None,'No observable reachable capture within 30 seconds'
            if mode=='full' and not held:
                ui.send([{'mouse':{'move':screen(s['gripper']),'buttons':{'left_down':True}}}]);held=True
                continue
        v=pose(truth,s,chosen);q=s['dice'][chosen]
        if q['seal']+1e-8>=truth['parameters']['seal_seconds'] and v['level']>.87 and feasible(truth,s,chosen,v['top']):
            ui.send([{'keyboard':{'keys':['Space']}}]);calls+=1;chosen=None
            continue
        # Predict the moving set point to compensate the visible gripper's
        # finite response. Paused native clicks land at the final frame.
        future=copy.deepcopy(s);advance(future,truth,s['tick']+(18 if paused else 13))
        goal=pose(truth,future,chosen);point=screen([goal['x'],goal['y']])
        if mode=='full':ui.send([{'mouse':{'move':point}}])
        else:click(ui,point)
        calls+=1
        if not paused:ui.wait(.14)
    else:raise AssertionError('Oracle exceeded declared 180 s task allowance')
    # Terminal final catch automatically submits; do not inject another input.
    if held:ui.send([{'mouse':{'buttons':{'left_up':True}}}])
    for _ in range(80):
        row=state()
        if row['grade'] is not None:break
        ui.wait(.05)
    assert row['grade'] and row['grade']['passed'],row
    return dict(captured=row['s']['captured'],top_sum=row['s']['sum'],ticks=row['s']['tick'],feedback_requests=calls,planning='Privileged state and deterministic future replay; fresh tracking; HTTP inputs only in native validation')
