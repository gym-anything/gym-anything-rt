"""Privileged read-only planning; every solution input goes through ui.send.

The native validator supplies the frozen Codex HTTP action gateway. A headless
Playwright transport is separately identified and proves implementation only.
This oracle is not a screenshot-only agent and produces no model score.
"""
from __future__ import annotations

import copy
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.bomb_manual_from_hell_v2 import Physics, knob, wrap

STATE = """(() => {const s=bombManualFromHellV2Model.physics;
return {ms:s.ms,armed:s.armed,start_ms:s.start_ms,failed:s.failed,
cut:s.cut,charge:s.charge,fuses:s.fuses,guards:s.guards,offsets:s.offsets};})()"""


def rect(ui, selector):
    return ui.read(f"(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()")


def click(point):
    return {'mouse': {'left_click': list(point)}}


def drag(a, b):
    return [{'mouse': {'move': list(a), 'buttons': {'left_down': True}}},
            {'mouse': {'move': list(b)}}, {'mouse': {'buttons': {'left_up': True}}}]


def send_and_observe_effect(ui, actions, expected, *, deadline_sec=5):
    """Task-private read-only planning barrier; the HTTP API stays unchanged.

    An X-server acknowledgement does not establish that all task handlers have
    run. Do not plan a contradictory second registration from that old state.
    This privileged oracle waits for the first intended visible effect without
    repeating uncertain input or mutating the task through the planning reader.
    """
    ui.send(actions)
    deadline = time.monotonic() + deadline_sec
    while True:
        state = ui.read(STATE)
        if expected(state) or state['failed']:
            return state
        if time.monotonic() >= deadline:
            raise AssertionError('task input effect not observed; no uncertain-input replay')
        ui.wait(.01)


def solve(ui, truth, *, execution_mode='live', observation_delay_ms=0, parked=False):
    w = truth['world']
    simple = truth['control_condition']['interaction'] == 'simplified'
    r = rect(ui, '#bomb-v2-canvas')
    def screen(p):
        return [r[0]+p[0]*r[2]/900, r[1]+p[1]*r[3]/560]
    b = rect(ui, '#bomb-v2-arm')
    send_and_observe_effect(ui, [click([b[0]+b[2]/2, b[1]+b[3]/2])], lambda s: s['armed'])
    if parked:
        ui.wait(.8)
        b = rect(ui, '#bomb-v2-seal')
        ui.send([click([b[0]+b[2]/2, b[1]+b[3]/2])])
        return dict(planning='privileged read-only state', policy='activation then no control, administrative seal', model_calls=0)
    deadline = time.monotonic()+120
    observations = []
    while time.monotonic() < deadline:
        state = ui.read(STATE)
        observations.append(state['ms'])
        if state['failed'] or len(state['cut']) == len(w['modules']):
            return dict(planning='privileged current-state read and generated geometry; exact visual forecast horizon only',
                        policy='delayed' if observation_delay_ms else 'timely', observation_delay_ms=observation_delay_ms,
                        observation_times_ms=observations, model_calls=0,
                        input_effect_observation='privileged read-only task feedback after each input batch; no input replay or harness change')
        s = Physics(w)
        for key, value in copy.deepcopy(state).items():
            setattr(s, key, value)
        if s.charge < 1-1e-9:
            if execution_mode=='live':
                ui.wait(.15)
            ui.send([])
            continue
        i = next(k for k in range(len(s.fuses)) if k not in s.cut)
        # Prediction stays within the 1.2s forecast shown on the game surface.
        predicted = Physics(w)
        for key, value in copy.deepcopy(state).items():
            setattr(predicted, key, value)
        predicted.advance(predicted.ms+(0 if execution_mode=='paused' else 200))
        horizon = [predicted] if execution_mode=='paused' else []
        if execution_mode=='live':
            for dt in (0,80,160,240,320,400):
                future=Physics(w)
                for key,value in copy.deepcopy(state).items():
                    setattr(future,key,value)
                future.advance(future.ms+dt)
                horizon.append(future)
        actions = []
        intended_offsets = {}
        for j, g in enumerate(predicted.guards[i]):
            delta = wrap(predicted.fuses[i]-g-s.offsets[i][j]*math.pi/12)
            # Use the whole visible aperture. Chasing its exact center every
            # frame can oscillate indefinitely at the loaded D5 rates.
            clearance = math.radians(w['parameters']['aperture_half_deg'])-math.asin(w['fuse_radius']/w['orbit_radius'])
            worst=max(abs(wrap(future.fuses[i]-future.guards[i][j]-s.offsets[i][j]*math.pi/12)) for future in horizon)
            if worst <= clearance-math.radians(3):
                continue
            steps = math.floor(delta/(math.pi/12)+.5)
            if not steps:
                continue
            c = knob(w, i, j)
            if simple:
                p = [c[0]+(28 if steps>0 else -28), c[1]]
                actions += [click(screen(p)) for _ in range(abs(steps))]
            else:
                # Use a <=165-degree rim arc. Split the half-turn to avoid the
                # ambiguous +/-pi branch and native pixel rounding at a detent.
                steps = max(-11, min(11, steps))
                a = [c[0]+23, c[1]]
                angle = steps*math.pi/12
                b = [c[0]+23*math.cos(angle), c[1]+23*math.sin(angle)]
                actions += drag(screen(a), screen(b))
            intended_offsets[j] = s.offsets[i][j] + steps
        if observation_delay_ms:
            ui.wait(observation_delay_ms/1000)
        if actions:
            send_and_observe_effect(ui, actions,
                lambda current: all(current['offsets'][i][j] == value for j, value in intended_offsets.items()))
            continue
        # Latest observation controls both opening containment and physical aim.
        # A tangential stroke avoids another knob and spans the whole collar.
        if predicted.safe(i):
            p = predicted.fuse_point(i)
            a = predicted.fuses[i]
            tangent = [-math.sin(a), math.cos(a)]
            start = [p[k]-28*tangent[k] for k in range(2)]
            end = [p[k]+28*tangent[k] for k in range(2)]
            send_and_observe_effect(ui,
                [click(screen(start)), click(screen(end))] if simple else drag(screen(start), screen(end)),
                lambda current: i in current['cut'])
        else:
            # A screenshot-only request advances the normal fixed paused window.
            ui.send([])
    raise AssertionError('live acetate HTTP oracle exceeded its declared wall budget')
