"""Privileged planning oracle; actual inputs are literal public HTTP mouse actions.

Simulation traces are implementation diagnostics, not action-space evidence.
``solve`` expects the frozen native HTTP UI's read/send/wait interface.
"""
from __future__ import annotations

import math
import time
import json
from pathlib import Path

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.downsky_causeway_v2 import Simulation, clamp, deck_y, motion


def reference(world, snapshot, future_ms=0):
    ms = snapshot['ms']+future_ms
    x = snapshot['x']+world['forward_speed']*future_ms/1000
    support = snapshot['support']
    if support is None:
        support = snapshot['landings'][-1]['deck'] if snapshot['landings'] else 0
    d = world['decks'][support]
    current = deck_y(d, ms)
    if support == 6:
        return current
    nxt = world['decks'][support+1]
    remaining = (d['x1']-world['radius']-x)/world['forward_speed']
    fall = math.sqrt(2*(d['z']-nxt['z'])/world['gravity'])
    if snapshot['support'] is None:
        # In free fall, the descent already observed determines the remaining
        # flight. Do not slide the arrival forecast forward on every frame.
        elapsed = -snapshot['vz']/world['gravity']+future_ms/1000
        departed_ms = snapshot['ms']+snapshot['vz']/world['gravity']*1000
        arrival_ms = departed_ms+fall*1000
        current = deck_y(d, departed_ms)
    else:
        elapsed = max(0, -remaining)
        arrival_ms = ms + remaining*1000 + fall*1000
    next_y = deck_y(nxt, arrival_ms)
    direction = 1 if next_y > current else -1
    edge = current + direction*(d['half_width']-world['radius']-.22)
    landing = next_y-direction*(nxt['half_width']-world['radius']-.38)
    # Anticipate the finite fall instead of following a moving marker blindly.
    if snapshot['support'] is not None and remaining > 1.35:
        return current
    if snapshot['support'] is not None and remaining >= 0:
        f = clamp(1-remaining/1.35, 0, 1)
        return current+(edge-current)*(f*f*(3-2*f))
    f = clamp(elapsed/fall, 0, 1)
    return edge+(landing-edge)*f


def command(world, snapshot, lead_ms=75, damping=0.):
    target = reference(world, snapshot, lead_ms)
    ahead = reference(world, snapshot, lead_ms+30)
    reference_speed = (ahead-target)/.03
    if snapshot['support'] is not None:
        d = world['decks'][snapshot['support']]
        reference_speed -= (deck_y(d,snapshot['ms']+30)-deck_y(d,snapshot['ms']))/.03
    desired_speed = reference_speed+3.2*(target-snapshot['y'])+damping*(reference_speed-snapshot['vy'])
    # Tiller selects a speed; the modelled motor and air retain inertia.
    wind = world['wind']*motion(world['wind_seed'],snapshot['ms'],world['wind_span_ms'])
    desired_speed -= wind/world['response']
    return clamp(desired_speed/world['max_lateral_speed'], -1, 1)


def native_command(world, snapshot):
    # Build lateral velocity before the edge rather than asking the motor to
    # produce an instantaneous speed change in flight. Preparation phases can
    # change a landing's displacement substantially while the walker is idle.
    return command(world, snapshot, lead_ms=275, damping=.5)


def simulation_trace(public, step_ms=100, delay_ms=0, policy=None):
    sim = Simulation(public['world'])
    mode = (public.get('control_condition') or {}).get('interaction', 'full')
    events = []
    def add(kind, **details):
        events.append(dict(sequence=len(events)+1,t_ms=sim.ms,kind=kind,**details))
    sim.start();add('start',input_source='start_button')
    history = [sim.snapshot()]
    while not sim.failed and not sim.complete and sim.ms < public['world']['max_ms']:
        source = history[max(0,len(history)-1-math.ceil(delay_ms/step_ms))]
        u = policy(source) if policy else command(public['world'],source)
        if mode=='full':
            add('steer_start',point=[550+sim.u*390,565],input_source='tiller_drag')
        sim.steer(u);add('steer',u=u,point=[550+u*390,565],input_source='tiller_drag' if mode=='full' else 'tiller_click')
        if mode=='full':add('steer_end',input_source='tiller_drag')
        sim.advance(sim.ms+step_ms)
        history.append(sim.snapshot())
    add('seal',input_source='submit_button')
    payload={k:public[k] for k in ('mechanic_id','task_id','challenge_id')}
    payload.update(interaction_mode=mode,events=events,completed=sim.complete,final=sim.snapshot())
    return dict(payload=payload,history=history)


def click(ui, selector):
    rect=ui.read(f"(()=>{{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()")
    return ui.send([{'mouse':{'left_click':[rect[0]+rect[2]/2,rect[1]+rect[3]/2]}}])


def steer(ui, mode, value, previous, continuing_drag=False):
    r=ui.read("(()=>{const r=document.querySelector('.dc-canvas').getBoundingClientRect();return [r.x,r.y,r.width,r.height];})()")
    def screen(u):return [r[0]+(550+u*390)/1100*r[2],r[1]+565/610*r[3]]
    if mode=='simplified':
        return ui.send([{'mouse':{'left_click':screen(value)}}])
    if continuing_drag:
        return ui.send([{'mouse':{'move':screen(value)}}])
    return ui.send([{'mouse':{'move':screen(previous),'buttons':{'left_down':True}}},
                    {'mouse':{'move':screen(value)}}])


def solve(ui, truth, step_seconds=.14):
    world=truth['world'];mode=(truth.get('control_condition') or {}).get('interaction','full')
    click(ui,'.dc-start')
    plans=[]
    holding=False
    for _ in range(290):
        s=ui.read('downskyCausewayV2Model.sim.snapshot()')
        if s['failed']:raise RuntimeError(s['failed'])
        if s['complete']:
            if holding:
                ui.send([{'mouse':{'buttons':{'left_up':True}}}])
            click(ui,'.dc-submit');ui.wait(.15)
            return dict(planning='privileged state and seed; no input outside HTTP',plans=plans,final=s)
        paused=getattr(ui,'mode','live')=='paused'
        u=native_command(world,s)
        plan=dict(ms=s['ms'],u=u,x=s['x'],y=s['y'],support=s['support'],paused_observation_feedback=paused,lead_ms=275,damping=.5)
        plans.append(plan)
        if getattr(ui,'evidence',None) is not None:
            with (Path(ui.evidence)/'oracle-plans.jsonl').open('a') as output:
                output.write(json.dumps(plan)+'\n')
        # The public input service supports a held mouse button. Keep the full
        # tiller grabbed across corrections, then release before certification.
        # This uses the same native API and observation schedule in every mode.
        steer(ui,mode,u,s['u'],continuing_drag=holding)
        holding=mode=='full'
        ui.wait(step_seconds)
    raise RuntimeError('Declared native control-call budget exhausted')
