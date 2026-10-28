"""Privileged read-only planner. All actual input is supplied by HTTPUI.send.

The same planner can be used by the clearly labelled isolated headless transport
for wiring checks. That transport never establishes native action-space parity.
"""
from __future__ import annotations

import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.museum_of_lost_gestures_v2 import target

MECHANIC_ID = 'museum_of_lost_gestures_v2'


def _box(ui, selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def _click(point):
    return {'mouse': {'left_click': point}}


def solve(ui, truth, step_seconds=.16, max_requests=285):
    world = truth['world']
    mode = truth.get('control_condition', {}).get('interaction', 'full')
    box = _box(ui, '#mg-start')
    ui.send([_click([box[0]+box[2]/2, box[1]+box[3]/2])])
    grips = {}
    if mode == 'simplified':
        for i in range(len(world['tracks'])):
            for grip in (0, 2):
                b = _box(ui, f'[data-tool="{i}"][data-grip="{grip}"]')
                grips[i, grip] = [b[0]+b[2]/2, b[1]+b[3]/2]
    plans = []
    deadline = time.monotonic()+180
    for request in range(max_requests):
        assert time.monotonic() < deadline, 'oracle wall deadline exceeded'
        view = ui.read('museumGesturesV2Model.view()')
        if view['done']:
            ui.wait(.15)
            return plans
        assert not view['failed'], view
        rect = view['rect']
        def screen(i, point):
            r = world['tracks'][i]['rect']
            return [rect['x']+(r[0]+point[0])*rect['width']/world['width'],
                    rect['y']+(r[1]+point[1])*rect['height']/world['height']]
        actions = []
        for i, track in enumerate(world['tracks']):
            # Account for the physical nib's lag, never change its physics.
            p, _ = target(track, view['ms']+200)
            _, grip = target(track, view['ms']+35)
            plans.append(dict(request=request, t_ms=view['ms'], tool=i, aim=p, grip=grip,
                              information='privileged read-only current tool state and generated future path'))
            if mode == 'simplified':
                actions.append(_click(screen(i, p)))
                if view['tools'][i]['grip'] != grip:
                    actions.append(_click(grips[i, grip]))
            else:
                button = 'left' if grip == 0 else 'right'
                actions.extend([{'mouse': {'move': screen(i, view['tools'][i]['point']), 'buttons': {button+'_down': True}}},
                                {'mouse': {'move': screen(i, p)}},
                                {'mouse': {'buttons': {button+'_up': True}}}])
        ui.send(actions)
        ui.wait(step_seconds)
    raise AssertionError('oracle request budget exceeded')
