"""Privileged construction oracle; every input goes through the caller's API.

Reads state and geometry solely for planning. HTTPUI is the frozen downstream
gateway transport in native evidence. Headless Playwright is a distinct wiring
check and never supplies action-space parity evidence.
"""
import time
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.minecraft_block_grid_v2 import faces, find_point, rack_x


def box(ui, selector):
    return ui.read(f'(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; }})()')


def click(ui, p):
    return ui.send([{'mouse':{'left_click':p}}])


def center(rect):
    return [rect[0]+rect[2]/2,rect[1]+rect[3]/2]


def snapshot(ui):
    return ui.read('({ms:quarryV2Model.currentMs,view:quarryV2Model.view,removed:[...quarryV2Model.removed],terminal:quarryV2Model.terminal,launched:quarryV2Model.launchAt!==null,failed:quarryV2Model.failed})')


def candidate(truth, ms, view, removed):
    """Choose an exposed safe surface, preferring ore and the earliest rack."""
    shown = {f['voxel_id'] for f in faces(truth, ms, view, removed)}
    racks = {r['id']:r for r in truth['racks']}
    items = [v for v in truth['voxels'] if v['id'] in shown and v['material'] in ('ore','stone')]
    items.sort(key=lambda v:(0 if v['material']=='ore' else 1,-rack_x(truth,racks[v['rack']],ms),v['id']))
    for v in items:
        point = find_point(truth,ms,view,removed,v['id'],margin=4)
        if point:
            return v, point
    return None


def solve(ui, truth, deadline_seconds=180, observation_delay=0):
    rect=box(ui,'#quarry-canvas')
    def screen(p):
        return [rect[0]+p[0]*rect[2]/1080,rect[1]+p[1]*rect[3]/530]
    click(ui,center(box(ui,'#quarry-launch')))
    deadline=time.monotonic()+deadline_seconds
    target_count=truth['target_count']
    while time.monotonic()<deadline:
        state=snapshot(ui)
        assert not state['terminal'],state
        count=sum(v['material']=='ore' and v['id'] in state['removed'] for v in truth['voxels'])
        if count==target_count:
            click(ui,center(box(ui,'#quarry-exit')))
            return
        if observation_delay:
            ui.wait(observation_delay)
        # Native direct transport is short; use a conservative 35 ms forecast.
        # It does not inject a state or assume the visible block is stationary.
        selected=candidate(truth,state['ms']+35,state['view'],state['removed'])
        if selected:
            click(ui,screen(selected[1]))
            continue
        alternative=next((v for v in ((state['view']+1)%4,(state['view']-1)%4,(state['view']+2)%4)
                          if candidate(truth,state['ms']+35,v,state['removed'])),None)
        if alternative is not None:
            delta=1 if alternative!=(state['view']-1)%4 else -1
            if truth['control_condition']['interaction']=='simplified':
                click(ui,center(box(ui,'#quarry-right' if delta==1 else '#quarry-left')))
            else:
                a,b=screen([640,460]),screen([640-delta*110,460])
                ui.send([{'mouse':{'move':a,'buttons':{'right_down':True}}},
                         {'mouse':{'move':b}},{'mouse':{'buttons':{'right_up':True}}}])
            continue
        ui.send([])
        ui.wait(.18)
    raise AssertionError('quarry oracle exceeded its declared wall-time budget')
