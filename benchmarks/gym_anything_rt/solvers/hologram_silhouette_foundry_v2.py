"""Privileged solvability oracle; every input goes through the supplied UI API.

This reads generator motion and browser pose for planning. It is not a
screenshot-only model policy. HTTPUI supplies the frozen downstream mouse API;
local Playwright adapters are wiring diagnostics only.
"""
from __future__ import annotations

import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.hologram_silhouette_foundry_v2 import target


def solve(ui, truth, cadence=.16, lookahead_ms=260, wall_timeout_seconds=500):
    rect = ui.read("(() => {const r=document.querySelector('.hsf2-canvas').getBoundingClientRect();return [r.x,r.y,r.width,r.height];})()")
    simple = truth["control_condition"]["interaction"] == "simplified"

    def point(x,y):
        return [round(rect[0]+x*rect[2]/1120), round(rect[1]+y*rect[3]/570)]

    def button(name):
        return ui.read("(() => {const r=document.querySelector('.hsf2-"+name+"').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()")

    def commands(values, current):
        actions=[]
        for i in range(truth['parameters']['active_axes']):
            y=148+i*69
            limit=truth['limits'][i]
            end=point(1019+max(-limit,min(limit,values[i]))/limit*69,y)
            if simple:
                actions.append({'mouse':{'left_click':end}})
            else:
                start=point(1019+current[i]/limit*69,y)
                actions += [{'mouse':{'move':start,'buttons':{'left_down':True}}},
                            {'mouse':{'move':end}}, {'mouse':{'buttons':{'left_up':True}}}]
        return actions

    current=ui.read('hologramSilhouetteFoundryV2Model.command')
    ui.send(commands(target(truth,0),current))
    ui.wait(.8)
    ui.send([{'mouse':{'left_click':button('start')}}])
    deadline=time.monotonic()+wall_timeout_seconds
    while time.monotonic()<deadline:
        status=ui.read('({t:hologramSilhouetteFoundryV2Model.t,start:hologramSilhouetteFoundryV2Model.startTime,phase:hologramSilhouetteFoundryV2Model.phase,command:hologramSilhouetteFoundryV2Model.command,terminal:hologramSilhouetteFoundryV2Model.terminal,grade:hologramSilhouetteFoundryV2Model.grade})')
        if status['terminal']:
            if not status.get('grade'):
                ui.wait(.05)
                continue
            assert status['grade']['passed'],status
            return status
        if status['phase']=='fused':
            ui.send([{'mouse':{'left_click':button('submit')}}])
            continue
        assert status['phase']=='active',status
        future=status['t']-status['start']+lookahead_ms
        ui.send(commands(target(truth,future),status['command']))
        ui.wait(cadence)
    raise AssertionError('Finite foundry oracle deadline exceeded')
