"""Privileged wiring solver; all task actions use visible native controls.

Not a screenshot-only benchmark policy. Reads current pose for energy feedback,
never writes simulation state. Clock scheduling belongs to the capture harness.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
_spec=importlib.util.spec_from_file_location('elbow_solver_physics',ROOT/'shared_runtime/server/incubator_graders/elbow_engine_v2.py')
physics=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(physics)


def choose_torque(s,p,tick=0,held_ms=0):
    # Energy feedback pumps the early swing. A bounded predictive recovery
    # compares legal next torques if prolonged elbow rotation stalls ascent.
    if tick < 2500:
        return 1 if s[3]*(25-physics.energy(s,p))>=0 else -1
    choices=[]
    for first in (-1,0,1):
        predicted=list(s);peak=-2.0;u=first;held=held_ms;best_hold=held_ms
        for n in range(300):
            if n and n%12==0:
                u=1 if predicted[3]*(25-physics.energy(predicted,p))>=0 else -1
            predicted=physics.step(predicted,u*p['torque']+physics.disturbance(p,tick+n),p)
            peak=max(peak,physics.height(predicted,p))
            held=held+p['tick_ms'] if physics.height(predicted,p)>p['target_height'] else 0
            best_hold=max(best_hold,held)
        choices.append((best_hold,peak,first))
    return max(choices)[2]


def set_torque(page,u,full,current):
    if u==current:return current
    if full:
        if current:page.keyboard.up('ArrowRight' if current>0 else 'ArrowLeft')
        if u:page.keyboard.down('ArrowRight' if u>0 else 'ArrowLeft')
    else:
        page.locator(f'[data-u="{u}"]').click(force=True)
    return u


def fail_once(page,state_dir,out_dir,mechanic='elbow_engine_v2'):
    from playwright.sync_api import expect
    old=page.locator('.elbow-engine').get_attribute('data-challenge-id')
    page.locator('#ee-submit').click()
    expect(page.locator('.elbow-engine')).not_to_have_attribute('data-challenge-id',old)
    page.screenshot(path=str(out_dir/'elbow_engine_v2-failure-fresh.png'))
    assert page.evaluate('elbowEngineModel.tick===0 && elbowEngineModel.events.length===0')


def solve(page,state_dir,out_dir,mechanic='elbow_engine_v2',advance=None):
    from playwright.sync_api import expect
    state=json.loads((state_dir/'public_state.json').read_text())
    p=state['physics'];full=(state.get('control_condition') or {}).get('interaction','full')=='full'
    page.locator('#ee-start').click(force=True);current=0;shot=False
    for _ in range(850):
        m=page.evaluate('({s:elbowEngineModel.s,tick:elbowEngineModel.tick,heldMs:elbowEngineModel.heldMs,finished:elbowEngineModel.finished,won:elbowEngineModel.won})')
        if m['finished']:break
        u=choose_torque(m['s'],p,m['tick'],m['heldMs']);current=set_torque(page,u,full,current)
        if advance:advance(240)
        else:page.wait_for_timeout(240)
        if not shot and m['tick']>200:
            page.screenshot(path=str(out_dir/'elbow_engine_v2-active.png'));shot=True
    if full and current:page.keyboard.up('ArrowRight' if current>0 else 'ArrowLeft')
    assert page.evaluate('elbowEngineModel.won'), 'feedback controller failed to sustain the height hold'
    page.screenshot(path=str(out_dir/'elbow_engine_v2-solved.png'))
    page.locator('#ee-submit').click(force=True)
    expect(page.locator('.readout')).to_have_attribute('data-status','passed',timeout=30000)
