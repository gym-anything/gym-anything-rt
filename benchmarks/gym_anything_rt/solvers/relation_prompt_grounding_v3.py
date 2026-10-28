"""Privileged feedback oracle; the native caller supplies frozen HTTP input.

Only state/geometry reads plan the solution. There are no game function calls,
page mutations, DOM focus, or direct Playwright actions in the native solver.
The local HeadlessUI adapter is separate implementation evidence.
"""
from __future__ import annotations
import copy
import math
import time
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.relation_prompt_grounding_v3 import contains, positions, shift, fit


def center(ui, selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()')


def click(ui, point):
    return ui.send([{'mouse': {'left_click': [round(point[0]), round(point[1])]}}])


def snapshot(ui):
    return ui.read('({commands:sculptureRigV3Model.commands,inspected:[...sculptureRigV3Model.inspected],stage:sculptureRigV3Model.stage,hold:sculptureRigV3Model.hold,t:sculptureRigV3Model.active&&!sculptureRigV3Model.terminal?Math.round(performance.now()-sculptureRigV3Model.startedAt):sculptureRigV3Model.t,terminal:sculptureRigV3Model.terminal,grade:sculptureRigV3Model.serverGrade})')


def correction_actions(truth, row, rect, paused=False):
    """Solve the symmetric carriage coupling, then create literal mouse inputs."""
    q = copy.deepcopy(row['commands'])
    c = truth['parameters']['coupling']
    n = len(q)
    t = row['t']
    future = t+(400 if paused else 120)
    # Inspect through the ordinary selection surface before planning from the
    # seals. Zero-displacement release is safe and has no probe quota. Replay
    # fixtures without a browser inspection state retain their oracle contract.
    discovering = 'inspected' in row and len(row['inspected']) < n
    target = truth['plates'][row['stage']]['targets'] if not discovering else None
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.relation_prompt_grounding_v3 import drift
    desired = [[0, 0, 0] for _ in q] if discovering else [[p[j]-drift(body, truth['parameters'], future)[j]-q[i][j] for j in range(3)] for i,(body,p) in enumerate(zip(truth['objects'],target))]
    total = [sum(p[j] for p in desired) for j in range(3)]
    delta = [[(p[j]-c*total[j]/(1+(n-1)*c))/(1-c) for j in range(3)] for p in desired]
    def screen(view, p):
        return [round(rect[0]+((40 if view=='front' else 520)+p[0])*rect[2]/960), round(rect[1]+(45+p[1])*rect[3]/410)]
    def local(view, p):
        return [(p[0]-rect[0])*960/rect[2]-(40 if view=='front' else 520), (p[1]-rect[1])*410/rect[3]-45]
    actions=[]
    for view in ['front','side']:
        axis=0 if view=='front' else 2
        for i in range(n):
            ps=positions(truth,q,t)
            order=sorted(range(n),key=lambda k:ps[k][2 if view=='front' else 0])
            # Choose an actually visible point inside the mesh, respecting the
            # same depth order and quantized desktop coordinates as hit testing.
            start=None
            for dx,dy in [(0,0),(-9,0),(9,0),(0,-9),(0,9),(-15,0),(15,0),(0,-15),(0,15)]:
                a=screen(view,[ps[i][axis]+dx,ps[i][1]+dy]);p=local(view,a)
                hits=[k for k in order if contains(truth['objects'][k],ps[k],view,p)]
                if hits and hits[-1]==i:start=a;break
            if start is None:
                continue # Another correction or fresh motion will expose it.
            amount=[delta[i][axis],delta[i][1] if view=='front' else 0]
            origin=local(view,start)
            destination=screen(view,[max(0,min(400,origin[0]+amount[0])),max(0,min(340,origin[1]+amount[1]))])
            endpoint=local(view,destination)
            if truth['control_condition']['interaction']=='full':
                actions.extend([{'mouse':{'move':start,'buttons':{'left_down':True}}},{'mouse':{'move':destination}},{'mouse':{'buttons':{'left_up':True}}}])
            else:
                actions.extend([{'mouse':{'left_click':start}},{'mouse':{'left_click':destination}}])
            shift(truth,q,i,view,[a-b for a,b in zip(endpoint,origin)])
    return actions


def solve(ui, truth):
    paused=getattr(ui,'execution_mode','live')=='paused'
    rect=ui.read('(() => {const r=document.querySelector("#rig-canvas").getBoundingClientRect();return [r.x,r.y,r.width,r.height];})()')
    click(ui,center(ui,'#rig-start'))
    calls=0;deadline=time.monotonic()+170
    while time.monotonic()<deadline:
        row=snapshot(ui)
        assert row['terminal']!='fail',row
        if row['stage']==3:break
        # Motion can make a click miss between planning and dispatch. Finish
        # any surviving visible selection through its normal input surface
        # before constructing another batch; never mutate game state to reset it.
        if row['hold']:
            if truth['control_condition']['interaction']=='full':
                ui.send([{'mouse':{'buttons':{'left_up':True}}}])
            else:
                hold=row['hold'];p=hold['point']
                click(ui,[rect[0]+((40 if hold['view']=='front' else 520)+p[0])*rect[2]/960,rect[1]+(45+p[1])*rect[3]/410])
            calls+=1
            continue
        actions=correction_actions(truth,row,rect,paused)
        ui.send(actions);calls+=1
        row=snapshot(ui)
        if fit(truth,row['commands'],row['stage'],row['t']) and (paused or fit(truth,row['commands'],row['stage'],row['t']+120)):
            click(ui,center(ui,'#rig-expose'));calls+=1
            if not paused:ui.wait(.6)
        elif not paused:
            ui.wait(.05)
    else:raise AssertionError('Oracle exceeded 180 s task allowance')
    click(ui,center(ui,'#rig-certify'))
    for _ in range(100):
        row=snapshot(ui)
        if row['grade'] is not None:break
        ui.wait(.05)
    assert row['grade'] and row['grade']['passed'],row
    return dict(plates=row['stage'],task_active_ms=row['t'],feedback_calls=calls,planning='Privileged fresh carriage state, target geometry and analytic drift prediction; literal mouse inputs through caller API')


class HeadlessUI:
    """Fresh isolated headless browser only; does not prove native API parity."""
    execution_mode='live'
    def __init__(self,page):self.page=page
    def read(self,expression):return self.page.evaluate(expression)
    def wait(self,seconds):self.page.wait_for_timeout(seconds*1000)
    def send(self,actions):
        for action in actions:
            mouse=action['mouse']
            if 'move' in mouse:self.page.mouse.move(*mouse['move'])
            if 'left_click' in mouse:self.page.mouse.click(*mouse['left_click'])
            if mouse.get('buttons',{}).get('left_down'):self.page.mouse.down()
            if mouse.get('buttons',{}).get('left_up'):self.page.mouse.up()
