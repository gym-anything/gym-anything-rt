"""Privileged test planner; executes only ordinary UI controls, never edits game state."""
from __future__ import annotations
import copy
import importlib.util
import math
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('courtesy_replay',ROOT/'shared_runtime/server/incubator_graders/courtesy_junction.py')
physics=importlib.util.module_from_spec(spec);spec.loader.exec_module(physics)

def route(world):
    points=[]
    if world['turn']=='right':
        points.extend((480,y) for y in range(470,349,-5))
        points.extend((545+65*math.cos(math.pi+i*math.pi/80),350+65*math.sin(math.pi+i*math.pi/80)) for i in range(41))
        points.extend((x,285) for x in range(550,851,5))
    else:
        points.extend((480,y) for y in range(470,273,-5))
        points.extend((410+70*math.cos(-i*math.pi/80),274+70*math.sin(-i*math.pi/80)) for i in range(41))
        points.extend((x,204+16*max(0,min(1,(250-x)/100))) for x in range(405,29,-5))
    return points

def steering(e,points):
    nearest=min(range(len(points)),key=lambda i:(points[i][0]-e['x'])**2+(points[i][1]-e['y'])**2)
    index=nearest
    while index<len(points)-1 and math.hypot(points[index][0]-e['x'],points[index][1]-e['y'])<30:index+=1
    x,y=points[index];angle=(math.atan2(y-e['y'],x-e['x'])-e['a']+math.pi)%(2*math.pi)-math.pi
    return (1 if angle>.025 else -1 if angle<-.025 else 0),nearest

def choose(state,world,points,horizon=100):
    steer,progress=steering(state['ego'],points)
    # Score candidate speed controls by their physical continuation, including braking drivers.
    best=(-float('inf'),[steer,-1])
    for target in (48,34,20,0):
        s=copy.deepcopy(state);pedal=1 if s['ego']['v']<target-2 else -1 if s['ego']['v']>target+2 else 0
        action=[steer,pedal]
        for tick in range(horizon):
            if tick<20:control=action
            else:
                st,_=steering(s['ego'],points);v=s['ego']['v'];control=[st,1 if v<target-2 else -1 if v>target+2 else 0]
            physics.step(s,control,world)
            if s['status']!='driving':break
        _,advance=steering(s['ego'],points)
        score=advance-progress+.003*s['ego']['v']
        if s['status'] not in ('driving','arrived'):score=-10000+tick
        if s['status']=='arrived':score=10000
        if score>best[0]:best=(score,action)
    return best[1]

def set_input(page,value,mode,current):
    if mode=='simplified':
        for axis in range(2):
            if value[axis]!=current[axis]:page.locator(f'[data-axis="{axis}"][data-value="{value[axis]}"]').click()
    else:
        maps=[{-1:'ArrowLeft',1:'ArrowRight'},{-1:'ArrowDown',1:'ArrowUp'}]
        for axis in range(2):
            if value[axis]==current[axis]:continue
            if current[axis]:page.keyboard.up(maps[axis][current[axis]])
            if value[axis]:page.keyboard.down(maps[axis][value[axis]])
    current[:]=value

def solve(page,state_dir,out_dir,mechanic='courtesy_junction'):
    assert mechanic=='courtesy_junction'
    info=page.evaluate('({world:courtesyJunctionModel.state.world,mode:courtesyJunctionModel.state.control_condition.interaction})')
    world=info['world'];mode=info['mode'];points=route(world);current=[0,0]
    page.locator('#cj-start').click();deadline=time.monotonic()+150
    while time.monotonic()<deadline:
        state=page.evaluate('courtesyJunctionModel.sim')
        if state['status']!='driving':break
        value=choose(state,world,points)
        set_input(page,value,mode,current)
        page.wait_for_timeout(100)
    if mode=='full':
        for key in ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown']:page.keyboard.up(key)
    state=page.evaluate('courtesyJunctionModel.sim')
    if state['status']!='arrived':raise AssertionError(f'Junction drive failed: {state["status"]}, ego={state["ego"]}')
    if out_dir:page.screenshot(path=str(Path(out_dir)/'courtesy_junction-delivered.png'))
    page.locator('#cj-submit').click();page.wait_for_function('courtesyJunctionModel.passed === true')

def fail_once(page,state_dir,out_dir,mechanic='courtesy_junction'):
    before=page.evaluate('courtesyJunctionModel.state.challenge_id')
    page.locator('#cj-submit').click();page.locator('#cj-retry').wait_for(state='visible')
    if out_dir:page.screenshot(path=str(Path(out_dir)/'courtesy_junction-failed.png'))
    page.locator('#cj-retry').click();after=page.evaluate('courtesyJunctionModel.state.challenge_id')
    assert before!=after and page.evaluate('courtesyJunctionModel.events.length')==0
