"""Privileged construction oracle; every input uses the caller's mouse HTTP API.

Read-only DOM geometry and task-clock diagnostics plus the private inverse
deformation certificate support planning. This is not a screenshot-only model.
The same adapter can use isolated Playwright for separately labelled wiring tests.
"""
from __future__ import annotations
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.ember_anvil_v3 import heat, project
from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.ember_anvil_v3 import deform

MECHANIC_ID = 'ember_anvil_v3'


def box(ui,selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def center(r):
    return [r[0]+r[2]/2,r[1]+r[3]/2]


def click(p):
    return {'mouse':{'left_click':list(p)}}


def wait_for_strike(ui,previous_seq):
    """Observe handler completion without replaying an acknowledged input.

    The frozen native API acknowledges X-server processing. Browser dispatch
    can finish later; read-only planning must wait for the actual strike.
    """
    deadline=time.monotonic()+2
    while True:
        state=ui.read('({last:emberAnvilV3Model.events.at(-1),terminal:emberAnvilV3Model.terminal})')
        event=state['last']
        if state['terminal'] or (event and event['seq']>previous_seq and event['kind']=='strike'):
            return state
        assert time.monotonic()<deadline,'Browser did not dispatch the acknowledged hammer release'
        ui.wait(.005)


def reachable_next(w,h,remaining):
    """Moves that can be taken now without breaking the remaining certificate.

    Reorder a prefix only when both legal orderings reach exactly the same
    solid. This supports privileged planning; it supplies no actual input.
    """
    prefix=h[:]
    for index,a in enumerate(remaining):
        prefix=deform(prefix,a['cell'],a['tool'],a['direction'],w['cap'])
        if prefix is None:return
        early=deform(h,a['cell'],a['tool'],a['direction'],w['cap'])
        if early is None:continue
        reordered=early
        for prior in remaining[:index]:
            reordered=deform(reordered,prior['cell'],prior['tool'],prior['direction'],w['cap'])
            if reordered is None:break
        if reordered==prefix:yield index,a,early


def solve(ui,truth, *, paused=False, delay_ms=0, preplanned=False):
    w=truth['world'];mode=(truth.get('control_condition') or {}).get('interaction','full')
    rect=box(ui,'#eav-work')
    def screen(p):
        return [rect[0]+p[0]*rect[2]/860,rect[1]+p[1]*rect[3]/450]
    hammer=screen([w['hammer_box'][0]+60,w['hammer_box'][1]+22])
    controls={tool:center(box(ui,f'[data-tool="{tool}"]')) for tool in ('draw','upset','split')}
    directions=[center(box(ui,f'[data-dir="{i}"]')) for i in range(4)]
    # Read the visible feedback from each ordinary measurement. The private
    # inverse route remains privileged planning, but its goal and the order of
    # ready, commuting moves are checked against the die actually inspected.
    gauge=box(ui,'#eav-target')
    measured=[];readouts=[]
    for i in range(25):
        ui.send([click([gauge[0]+(69+(i%5)*28)*gauge[2]/250,
                        gauge[1]+(147+(i//5)*28)*gauge[3]/308])])
        prefix=f'DIE GAUGE · column {i%5+1}, row {i//5+1}: '
        deadline=time.monotonic()+2
        while True:
            readout=ui.read("document.querySelector('#eav-message').textContent")
            if readout.startswith(prefix):break
            assert time.monotonic()<deadline,'The die gauge did not acknowledge its measurement'
            ui.wait(.005)
        layers=int(readout[len(prefix):].split(' ')[0])
        assert 0<=layers<=w['cap'],readout
        measured.append(layers);readouts.append(readout)
    certificate=w['initial'][:]
    for a in truth['solution']:
        certificate=deform(certificate,a['cell'],a['tool'],a['direction'],w['cap'])
        assert certificate is not None,'Invalid inverse deformation certificate'
    assert certificate==measured,'The route does not reach the visibly measured die'
    ui.send([click(center(box(ui,'#eav-begin')))])
    deadline=time.monotonic()+240
    observed=0;recoverable_contacts=0;remaining=list(truth['solution']);expected=w['initial'][:]
    while remaining:
        while True:
            assert time.monotonic()<deadline,'kinetic forge oracle exceeded its finite deadline'
            state=ui.read('({t:emberAnvilV3Model.currentMs,h:emberAnvilV3Model.h,terminal:emberAnvilV3Model.terminal,seq:emberAnvilV3Model.events.length})')
            assert not state['terminal'],state
            observed+=1
            t=state['t']
            lead=0 if paused else 70
            predicted=t+lead
            # A 160-ms safety neighborhood avoids strikes across a heating boundary.
            choices=[(0,remaining[0],None)] if preplanned or delay_ms else list(reachable_next(w,state['h'],remaining))
            if not choices:
                ui.send([click(center(box(ui,'#eav-stamp')))])
                return dict(observations=observed,recoverable_contacts=recoverable_contacts,terminal=True)
            ready=[choice for choice in choices if preplanned or min(heat(w,choice[1]['cell'],predicted+d) for d in (0,80,160))>=w['workable']+.025]
            if ready:
                if not preplanned and not delay_ms:
                    ready.sort(key=lambda choice:sum(abs(h-target) for h,target in zip(choice[2],measured)))
                index,a,expected=ready[0];break
            ui.wait(.12 if not paused else .01)
            ui.send([])
        p=project(w,a['cell'],0 if preplanned else predicted)
        if delay_ms:
            ui.wait(delay_ms/1000)
        actions=[click(controls[a['tool']]),click(directions[a['direction']])]
        if mode=='full':
            actions += [{'mouse':{'move':hammer,'buttons':{'left_down':True}}},
                        {'mouse':{'move':screen(p)}},{'mouse':{'buttons':{'left_up':True}}}]
        else:
            actions += [click(screen(p))]
        ui.send(actions)
        # Keep every attempted contact in the browser transcript. Air, cold and
        # blocked strikes are explicitly recoverable when replay confirms that
        # no metal changed. Reobserve and re-aim without consuming the planned
        # move; never conceal a wrong deformation or retry a terminal failure.
        after=wait_for_strike(ui,state['seq'])
        if after['terminal']:
            return dict(observations=observed,recoverable_contacts=recoverable_contacts,terminal=True)
        if not preplanned and not delay_ms:
            event=after['last']
            if event['kind']=='strike' and event['outcome'] in ('air','cold','blocked') and event['heights']==state['h']:
                recoverable_contacts+=1
                continue
            assert event['kind']=='strike' and event['cell']==a['cell'] and event['outcome'] in ('moved','split'),event
            assert event['heights']==expected,'The reordered deformation differs from its certificate'
        remaining.pop(index)
    ui.send([click(center(box(ui,'#eav-stamp')))])
    return dict(observations=observed,recoverable_contacts=recoverable_contacts,terminal=True,
                die_measurements=measured,target_readouts=readouts)
