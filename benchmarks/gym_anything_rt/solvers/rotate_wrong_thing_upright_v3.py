"""Privileged gimbal planning; every actual input uses the caller's action API.

This is an implementation oracle, not a screenshot-only model or human score.
It reads diagnostic physical state and layout, then produces literal mouse
gestures. Load prediction stays inside the visible two-second forecast horizon.
Native validation supplies the frozen persistent same-machine HTTP transport.
"""
from __future__ import annotations

import math
import re

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.rotate_wrong_thing_upright_v3 import wind


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


def commands(contract, snapshot, forecast_ms=100, cadence_ms=250):
    # Bound derivative feedback for the observed command interval. The
    # original 1.5 gain can oscillate when D1's 0.4s motor is sampled at the
    # configured 0.6s observation interval. This changes only oracle steering.
    derivative_gain = min(1.5, contract['parameters']['response_s']*1000/max(10, cadence_ms))
    rates = [-wind(contract, i, snapshot['tick']*10+forecast_ms)
             -1.8*snapshot['angles'][i]-derivative_gain*snapshot['velocity'][i] for i in range(3)]
    result = _inverse_drive(contract['matrix'], rates, contract['motor_rate'])
    return [v if i < contract['parameters']['axes'] else 0. for i, v in enumerate(result)]


def matrix_from_engravings(engravings):
    """Read the visible +DIAL/ALSO inscriptions, without a private contract.

    Callers may supply screenshot OCR or manually transcribed visible text.
    Missing covers, ambiguous numbers and incomplete linkage text are errors;
    this never fills an unread value from generator settings or ground truth.
    """
    axes = ('ROLL', 'PITCH', 'YAW')
    if not 1 <= len(engravings) <= 3:
        raise ValueError('one engraving is needed per active motor')
    matrix = [[float(i == j) for j in range(3)] for i in range(3)]
    for column, text in enumerate(engravings):
        if not isinstance(text, str) or 'DIAL' not in text.upper():
            raise ValueError('lift the gear cover before reading its winding')
        pairs = re.findall(r'\b(ROLL|PITCH|YAW)\s*([+−-])\s*(\d+)\s*%', text.upper())
        if len(pairs) not in (1, 2) or len({p[0] for p in pairs}) != len(pairs):
            raise ValueError('unreadable or repeated gear percentages')
        if pairs[0][0] != axes[column] or int(pairs[0][2]) != 100:
            raise ValueError('unreadable main winding engraving')
        if len(pairs) == 1 and 'NO CROSS-AXIS GEAR' not in text.upper():
            raise ValueError('cross-axis engraving was not read')
        if len(pairs) == 2 and 'ALSO' not in text.upper():
            raise ValueError('cross-axis gear label was not read')
        for row in range(3):
            matrix[row][column] = 0.
        for name, sign, magnitude in pairs:
            if axes.index(name) >= len(engravings):
                raise ValueError('engraving refers to an inactive axis')
            matrix[axes.index(name)][column] = (1 if sign == '+' else -1) * int(magnitude)/100
    return matrix


READ = '''(() => {
 const m=window.rotateWrongV3Model;
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


def solve(ui, truth, *, max_rounds=350, interval=.04, read_inspection=None):
    """Budget <=352 action requests; no focus, script input, navigation or mutation."""
    contract = {k: v for k, v in truth['gimbal'].items() if k != 'matrix'}
    view = ui.read(READ)
    # Use the ordinary, shared inspection affordance before steering. Private
    # state is still used for planning; this is not a screenshot-only solver.
    rect = view['controls']
    ui.send([{'mouse': {'left_click': [rect[0]+(150+axis*300)*rect[2]/900,
                                     rect[1]+118*rect[3]/152]}}
             for axis in range(contract['parameters']['axes'])])
    # The visible-inspection path works even when truth['gimbal'] has no
    # matrix. Physical-state/wind diagnostics remain disclosed oracle inputs.
    contract['matrix'] = read_inspection() if read_inspection else truth['gimbal']['matrix']
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
            values = commands(contract, view['snapshot'],forecast_ms=min(900,max(100,.75*cadence_ms)),cadence_ms=cadence_ms)
            if not set_drives(ui, view, values):
                # Observation-only requests are part of the existing action
                # API. They advance its paused window when no correction is
                # needed, and supply a fresh frame in live execution.
                ui.send([])
        ui.wait(interval)
    raise AssertionError('Gimbal oracle exceeded its declared controller budget')
