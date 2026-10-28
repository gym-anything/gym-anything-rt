"""Privileged gimbal planning; every actual input uses the caller's action API.

This is an implementation oracle, not a screenshot-only model or human score.
It reads diagnostic physical state and layout, then produces literal mouse
gestures. Load prediction stays inside the visible two-second forecast horizon.
Native validation supplies the frozen persistent same-machine HTTP transport.
"""
from __future__ import annotations

import math

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.rotate_wrong_thing_upright_v2 import wind


def _inverse_drive(matrix, rates, motor_rate=65):
    rows = [list(row) + [rates[i]/motor_rate] for i, row in enumerate(matrix)]
    for i in range(3):
        divisor = rows[i][i]
        rows[i] = [x/divisor for x in rows[i]]
        for j in range(3):
            if i != j:
                factor = rows[j][i]
                rows[j] = [x-factor*y for x, y in zip(rows[j], rows[i])]
    return [max(-1., min(1., row[-1])) for row in rows]


def commands(contract, snapshot, forecast_ms=100):
    rates = [-wind(contract, i, snapshot['tick']*10+forecast_ms)
             -1.8*snapshot['angles'][i]-1.5*snapshot['velocity'][i] for i in range(3)]
    result = _inverse_drive(contract['matrix'], rates, contract['motor_rate'])
    return [v if i < contract['parameters']['axes'] else 0. for i, v in enumerate(result)]


READ = '''(() => {
 const m=window.rotateWrongV2Model;
 const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return [r.x,r.y,r.width,r.height];};
 return {snapshot:{tick:m.sim.tick,angles:[...m.sim.x],velocity:[...m.sim.v],drive:[...m.sim.u],
   dwell_ms:m.sim.dwell,started:m.sim.started,solved:m.sim.solved,failed:m.sim.failed},
   verdict:m.verdict,terminal:m.terminal,submitting:m.submitting,interaction:m.interaction,
   controls:rect('#rw-controls'),begin:rect('#rw-begin'),certify:rect('#rw-certify')};
})()'''


def _center(rect):
    return [rect[0]+rect[2]/2, rect[1]+rect[3]/2]


def set_drives(ui, view, values):
    rect = view['controls']
    def screen(point):
        return [rect[0]+point[0]*rect[2]/900, rect[1]+point[1]*rect[3]/152]
    def handle(axis, value):
        phi = math.radians(value*110)
        return screen([150+axis*300+60*math.sin(phi), 76-60*math.cos(phi)])
    actions = []
    for i, value in enumerate(values):
        if abs(value-view['snapshot']['drive'][i]) < .006:
            continue
        if view['interaction'] == 'simplified':
            actions.append({'mouse': {'left_click': screen([150+i*300+100*value, 76])}})
        else:
            actions.extend([
                {'mouse': {'move': handle(i, view['snapshot']['drive'][i]), 'buttons': {'left_down': True}}},
                {'action': 'wait', 'time': .02},
                {'mouse': {'move': handle(i, value)}},
                {'action': 'wait', 'time': .02},
                {'mouse': {'buttons': {'left_up': True}}},
                {'action': 'wait', 'time': .02},
            ])
    if actions:
        ui.send(actions)
        return True
    return False


def solve(ui, truth, *, max_rounds=350, interval=.04):
    """Budget <=352 action requests; no focus, script input, navigation or mutation."""
    contract = truth['gimbal']
    view = ui.read(READ)
    ui.send([{'mouse': {'left_click': _center(view['begin'])}}])
    previous_tick = None
    cadence_ms = 250.
    for _ in range(max_rounds):
        view = ui.read(READ)
        if previous_tick is not None:
            cadence_ms = .7*cadence_ms + .3*max(10,(view['snapshot']['tick']-previous_tick)*10)
        previous_tick = view['snapshot']['tick']
        if view['terminal']:
            if view['verdict'] != 'pass':
                raise AssertionError('Native gimbal execution failed: '+str(view))
            return view
        if view['snapshot']['failed']:
            raise AssertionError(view['snapshot']['failed'])
        if not view['submitting'] and not view['snapshot']['solved']:
            # Anticipate the upcoming gesture and hold interval from recent
            # observed cadence, within the visible load-forecast horizon.
            values = commands(contract, view['snapshot'],forecast_ms=min(900,max(100,.75*cadence_ms)))
            if not set_drives(ui, view, values):
                # Observation-only requests are part of the existing action
                # API. They advance its paused window when no correction is
                # needed, and supply a fresh frame in live execution.
                ui.send([])
        ui.wait(interval)
    raise AssertionError('Gimbal oracle exceeded its declared controller budget')
