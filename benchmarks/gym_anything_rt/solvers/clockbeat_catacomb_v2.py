"""Wiring solver, not a screenshot-only agent evaluation. Sends ordinary inputs."""
from copy import deepcopy
import heapq,itertools,json,time
from pathlib import Path
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.clockbeat_catacomb_v2 import initial,act,advance,DELTAS

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.clockbeat_catacomb_v2 import find_route as plan

def fail_once(page,state_dir,out_dir,mechanic='clockbeat_catacomb_v2'):
    from playwright.sync_api import expect
    before=json.loads((Path(state_dir)/'ground_truth.json').read_text())['challenge_id']
    page.locator('.cc-submit').click()
    expect(page.locator('.readout')).to_contain_text('FAIL')
    deadline=time.monotonic()+10
    while json.loads((Path(state_dir)/'ground_truth.json').read_text())['challenge_id']==before:
        if time.monotonic()>deadline:raise AssertionError('fresh catacomb was not received')
        page.wait_for_timeout(20)
    page.screenshot(path=str(Path(out_dir)/f'{mechanic}-failure-fresh.png'))

def solve(page,state_dir,out_dir=None,mechanic='clockbeat_catacomb_v2'):
    public=json.loads((Path(state_dir)/'public_state.json').read_text());b=public['board'];mode=(public.get('control_condition') or {}).get('interaction','full')
    route=plan(b);page.locator('.cc-start').click();beat=0
    for key in route:
        page.wait_for_function('(beat)=>Number(document.querySelector(".cc").dataset.beat)>=beat',arg=beat,timeout=10000)
        page.wait_for_timeout(80)
        root=page.locator('.cc');actual=int(root.get_attribute('data-beat'));ms=int(root.get_attribute('data-ms'))
        if actual!=beat or ms%b['beat_ms']>b['open_ms']-200:raise RuntimeError('solver missed beat; no hidden clock changes permitted')
        if mode=='full':page.keyboard.press({'UP':'ArrowUp','RIGHT':'ArrowRight','DOWN':'ArrowDown','LEFT':'ArrowLeft','WAIT':'Space'}[key])
        else:page.locator(f'[data-cc-key="{key}"]').click()
        if out_dir and beat in (0,3):page.screenshot(path=str(Path(out_dir)/f'active-{beat}.png'))
        beat+=1
    assert page.locator('.cc').get_attribute('data-won')=='true'
    if out_dir:page.screenshot(path=str(Path(out_dir)/'solved.png'))
    page.locator('.cc-submit').click();page.wait_for_function('document.querySelector(".cc-verdict").textContent.includes("PASS")')
    return route
