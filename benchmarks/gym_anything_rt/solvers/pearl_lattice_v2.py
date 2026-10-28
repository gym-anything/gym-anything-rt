"""Privileged state planning; all execution through the caller's mouse API.

HTTPUI is the native downstream transport. A separately labelled Playwright
transport may test event wiring, but is never claimed as native API evidence.
No state setters or internal game calls occur in this oracle.
"""
from __future__ import annotations
import math
import time

MECHANIC_ID = 'pearl_lattice_v2'
READ = "({physics:pearlLatticeV2Model.physics.snapshot(),submitted:pearlLatticeV2Model.submitted,outcome:pearlLatticeV2Model.outcome||null})"


def steering_target(contract, snapshot, column):
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.pearl_lattice_v2 import gate_center, current
    ball=snapshot.get('ball')
    layer=ball['gate'] if ball else 0
    ms=snapshot['tick']*10
    gate=gate_center(contract,layer,column,ms)
    previous=gate_center(contract,layer,column,max(0,ms-150))
    velocity=[(gate[i]-previous[i])/.15 if ms>=150 else 0 for i in range(2)]
    wind=current(contract,ms)
    spring=contract['physics']['steering_spring']
    if ball:
        target=[gate[i]+velocity[i]*.50-wind[i]/spring+
                .30*(gate[i]-ball['p'][i])-.12*(ball['v'][i]-velocity[i]) for i in range(2)]
    else:target=gate
    return [max(24,min(contract['physics']['field'][i]-24,n)) for i,n in enumerate(target)]


def click(ui, point):
    return ui.send([{'mouse':{'left_click':list(point)}}])


def rectangle(ui, selector):
    return ui.read(f'(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; }})()')


def midpoint(rect):return [rect[0]+rect[2]/2,rect[1]+rect[3]/2]


def solve_api(ui, truth, update_seconds=.20):
    mode=truth['control_condition']['interaction']
    rect=rectangle(ui,'.plv-field')
    def screen(point):return [rect[0]+point[0]*rect[2]/640,rect[1]+point[1]*rect[3]/480]
    release=midpoint(rectangle(ui,'.plv-release'))
    seal=midpoint(rectangle(ui,'.plv-seal'))
    deadline=time.monotonic()+170
    held=False
    for column in truth['solution_moves']:
        state=ui.read(READ)['physics']
        assert not state['failed'] and not state['won'],state
        target=steering_target(truth,state,column)
        if mode=='full':
            ui.send([{'mouse':{'move':screen(state['head']),'buttons':{'left_down':True}}},
                     {'mouse':{'move':screen(target)}}])
            held=True
        else:click(ui,screen(target))
        ui.wait(.75)
        state=ui.read(READ)['physics']
        target=steering_target(truth,state,column)
        if mode=='full':
            ui.send([{'mouse':{'move':screen(target)}},{'mouse':{'buttons':{'left_up':True}}}]);held=False
        else:click(ui,screen(target))
        ui.wait(.35)
        click(ui,release)
        state=ui.read(READ)['physics']
        assert state['ball'] and not state['failed'],state
        if mode=='full':
            ui.send([{'mouse':{'move':screen(state['head']),'buttons':{'left_down':True}}}]);held=True
        while state['ball'] and not state['failed'] and not state['won']:
            assert time.monotonic()<deadline,'oracle exceeded the declared deadline'
            target=steering_target(truth,state,column)
            if mode=='full':ui.send([{'mouse':{'move':screen(target)}}])
            else:click(ui,screen(target))
            ui.wait(update_seconds)
            state=ui.read(READ)['physics']
        if held:
            ui.send([{'mouse':{'buttons':{'left_up':True}}}]);held=False
        assert not state['failed'],state
    state=ui.read(READ)['physics']
    assert state['won'],state
    click(ui,seal)
    ui.wait(.3)
    return ui.read(READ)


def solve(page,state_dir,out_dir,mechanic=MECHANIC_ID,advance=None):
    """Existing browser-solver plugin compatibility; evidence remains Playwright."""
    import json
    from pathlib import Path
    truth=json.loads((Path(state_dir)/'ground_truth.json').read_text())
    class BrowserUI:
        def read(self,expression):return page.evaluate(expression)
        def wait(self,seconds):
            if advance is not None:advance(page,max(300,math.ceil(seconds*1000/300)*300))
            else:page.wait_for_timeout(seconds*1000)
        def send(self,actions):
            for action in actions:
                mouse=action['mouse']
                if 'move' in mouse:page.mouse.move(*mouse['move'])
                for name in mouse.get('buttons',{}):
                    button,transition=name.rsplit('_',1)
                    getattr(page.mouse,transition)(button=button)
                if 'left_click' in mouse:page.mouse.click(*mouse['left_click'])
    result=solve_api(BrowserUI(),truth)
    Path(out_dir).mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(Path(out_dir)/'pearl-lattice-v2-pass.png'))
    return result
