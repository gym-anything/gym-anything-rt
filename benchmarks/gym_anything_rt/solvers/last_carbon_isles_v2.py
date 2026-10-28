"""Privileged read-only planner; every actual input uses the caller's HTTP action API.

This is implementation evidence, not a screenshot-only policy or a model score.
The planner reads the generated load curve and battery state. It does not mutate
DOM/state, invoke game functions, focus elements, or inject input via Playwright.
"""
from __future__ import annotations

import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.last_carbon_isles_v2 import loads

MECHANIC_ID = 'last_carbon_isles_v2'
READ = '''(() => {
 const m=window.lastCarbonIslesV2Model;
 const box=s=>{const r=document.querySelector(s).getBoundingClientRect();return [r.x,r.y,r.width,r.height];};
 return {time:m.tick*m.state.step_s,targets:m.targets,battery:m.battery,supply:m.supply,
 terminal:m.terminal,failure:m.failure,result:m.result||null,
 rails:[...document.querySelectorAll('.ci-rail')].map(r=>{const b=r.getBoundingClientRect();return [b.x,b.y,b.width,b.height];}),
 launch:box('.ci-launch')};
})()'''


def planned_shares(spec, t, battery, interval=.8, stale=0.):
    future=max(0,t-stale)+spec['parameters']['inertia_s']+interval/2
    return [min(100,max(0,value+(s['battery_capacity']-stored)*.2))
            for value,s,stored in zip(loads(spec,future),spec['islands'],battery)]


def actions_for(state, shares, interaction):
    actions=[]
    for i,(rect,value) in enumerate(zip(state['rails'],shares)):
        x,y,w,h=rect
        # Full input starts at the actual visible policy card, which straddles the rail.
        point=[round(x+w*value/100),round(y+h*.72)]
        if interaction=='full':
            start=[round(x+w*state['targets'][i]/100),point[1]]
            if start[0]==point[0]:
                continue
            # The downstream API supplies this ordinary two-endpoint drag.
            # One command avoids three separate input deliveries, especially
            # when the frozen paused runner holds the world during input.
            actions.append({'mouse':{'left_click_drag':[start,point]}})
        else:
            actions.append({'mouse':{'left_click':point}})
    return actions


def solve(ui, truth, *, interval=.8, wall_deadline_s=180):
    state=ui.read(READ)
    x,y,w,h=state['launch']
    ui.send([{'mouse':{'left_click':[round(x+w/2),round(y+h/2)]}}])
    deadline=time.monotonic()+wall_deadline_s
    while time.monotonic()<deadline:
        state=ui.read(READ)
        if state['terminal']:
            if state['failure']:
                raise AssertionError(state['failure'])
            return state
        shares=planned_shares(truth,state['time'],state['battery'],interval)
        ui.send(actions_for(state,shares,truth['control_condition']['interaction']))
        ui.wait(interval)
    raise AssertionError('dispatch controller exceeded its declared wall deadline')
