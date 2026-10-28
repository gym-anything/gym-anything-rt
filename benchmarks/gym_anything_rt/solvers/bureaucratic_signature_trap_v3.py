"""Privileged planning oracle; all actual inputs use the supplied UI transport.

Native validation supplies the frozen downstream HTTP gateway. Headless input
tests are separately labelled and do not establish native action-space parity.
"""
from __future__ import annotations

import copy
import math
import re
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.bureaucratic_signature_trap_v3 import (
    apply, initial, step, move_pen, target, hazard_positions,
)


def command(world, tick, interval_ms=100, observation_delay_ms=0):
    """Exact local curve forecast compensates pen response and sample holding.

    Used as privileged implementation/solvability evidence. It is not a
    screenshot vision algorithm and is not a downstream model evaluation.
    """
    t=max(0, tick*world['dt_ms']-observation_delay_ms)
    mid=min(world['params']['duration_ms'],t+interval_ms/2)
    base=target(world,mid)
    a=target(world,max(0,mid-10));b=target(world,min(world['params']['duration_ms'],mid+10))
    velocity=[(b[j]-a[j])/.02 for j in (0,1)]
    p=[max(0,min(world[('width','height')[j]],base[j]+world['params']['response_s']*velocity[j])) for j in (0,1)]
    # The lift reserve covers the physical nib's lead and the next command's
    # arrival, rather than changing the game's actual collision geometry.
    ink=True
    for offset in (0, interval_ms/2, interval_ms, interval_ms+100):
        q=target(world,min(world['params']['duration_ms'],t+offset))
        hp=hazard_positions(world,t+offset)
        if any(math.dist(q,h) <= spec['radius']+world['pen_radius']+12
               for spec,h in zip(world['hazards'],hp)):
            ink=False
    return p,ink


def pointer_for_aim(world, aim):
    """Apply the registration learned from the visible carbon coupon."""
    return [aim[j] - world['carbon_offset'][j] for j in (0, 1)]


def diagnostic(public, policy='feedback', interval_ms=100, delay_ms=0, template_world=None, parked_point=None):
    world=public['world'];s=initial(world);events=[]
    mode=public.get('control_condition',{}).get('interaction','full')
    sources=dict(start='start_button',certify='certify_button',aim='pen_pointer' if mode=='full' else 'pen_position_proxy',ink='pen_contact' if mode=='full' else 'ink_proxy')
    def event(kind,**detail):
        e=dict(sequence=len(events)+1,tick=s['tick'],kind=kind,input_source=sources[kind],**detail)
        events.append(e);apply(world,s,e)
    event('start')
    while not s['terminal']:
        if s['tick'] % max(1,round(interval_ms/world['dt_ms']))==0:
            if policy=='parked':p,ink=parked_point or target(world,0),True
            else:p,ink=command(template_world or world,s['tick'],interval_ms,delay_ms)
            event('aim',point=pointer_for_aim(world,p))
            if ink != s['ink']:event('ink',down=ink)
        step(world,s)
    event('certify')
    payload={k:public[k] for k in ('mechanic_id','task_id','challenge_id','revision')}
    payload.update(interaction_mode=mode,events=events,final_tick=s['tick'])
    return payload,s


def box(ui,selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height]}})()')


def center(ui,selector):
    x,y,w,h=box(ui,selector);return [round(x+w/2),round(y+h/2)]


def contact_clear(world, state, aim, horizon_ms=500, delivery_delay_ms=40):
    """Forecast the actual inertial nib, including its previous held aim.

    This oracle guard changes only its contact choice. The world's collision
    geometry, copy tolerance and acceptance threshold are unchanged.
    """
    trial = copy.deepcopy(state)
    trial['ink'] = False
    if any(math.dist(trial['pen'], h) <= spec['radius']+world['pen_radius']+8
           for spec,h in zip(world['hazards'],hazard_positions(world,trial['tick']*world['dt_ms']))):
        return False
    delay_ticks = math.ceil(delivery_delay_ms/world['dt_ms'])
    for n in range(math.ceil(horizon_ms/world['dt_ms'])):
        if n == delay_ticks:
            trial['aim'] = aim[:]
        # Forecast only kinematics. A hypothetical lifted path's copy gap is
        # not a collision and must not truncate the nib forecast.
        trial['tick'] += 1
        move_pen(world, trial)
        hp = hazard_positions(world, trial['tick']*world['dt_ms'])
        if any(math.dist(trial['pen'], h) <= spec['radius']+world['pen_radius']+8
               for spec,h in zip(world['hazards'],hp)):
            return False
    return True


def bounded_contact_action(observation):
    """A delayed contact choice from already rendered forecast glyphs only.

    Exact glyph coordinates are gifted perception in construction diagnostics.
    This is not image recognition or privileged future-curve planning. The
    existing aim is held for the first physical step. Contact is independent
    of the motor: a safe inked step can only improve copied arc / shorten a
    gap; unsafe contact is irreversible. Actual case optimality additionally
    requires a passing continuation, recorded independently in the evidence.
    """
    clear = all(math.dist(p,q)>radius for p,centers in (
        (observation['pen'],observation['voids']),
        (observation['pen_next'],observation['voids_next']))
        for q,radius in zip(centers,observation['void_radii']))
    return observation['aim'][:],clear


def solve(ui,truth,max_seconds=270,registration=None):
    world=truth['world'];mode=truth.get('control_condition',{}).get('interaction','full')
    paused=getattr(ui,'execution_mode','live')=='paused'
    rect=box(ui,'#bst-canvas');toggle=center(ui,'#bst-ink') if mode=='simplified' else None
    # Pull the physical coupon cover using the same ordinary pointer transport.
    if not ui.read('document.querySelector("#bst-registration").classList.contains("is-open")'):
        tab=center(ui,'#bst-carbon-tab')
        width=box(ui,'#bst-registration')[2]
        ui.send([{'mouse':{'move':tab}}, {'mouse':{'buttons':{'left_down':True}}},
                 {'mouse':{'move':[round(tab[0]+width+10),tab[1]]}},
                 {'mouse':{'buttons':{'left_up':True}}}])
    if registration is None:
        # Automated oracle tests can gift text perception. Image-discovery
        # evidence instead supplies the numbers read from the captured PNG.
        visible=ui.read('document.querySelector("#bst-registration-details").innerText')
        match=re.search(r'X ([+-]\d+) px\s+Y ([+-]\d+) px',visible)
        if match is None:
            raise ValueError('Read the exposed carbon registration before signing')
        registration=[int(match[1]),int(match[2])]
        perception='exposed DOM text (gifted perception)'
    else:
        if not isinstance(registration,list) or len(registration)!=2 or any(type(v) is not int for v in registration):
            raise ValueError('registration must contain the two observed integer offsets')
        perception='captured registration PNG, read with view_image'
    ui.send([{'mouse':{'left_click':center(ui,'#bst-start')}}])
    cycles=0;deadline=time.monotonic()+max_seconds
    while time.monotonic()<deadline:
        s=ui.read('bureaucraticSignatureV3Model.sim')
        if s['terminal']:
            assert s['terminal']=='pass',s
            return dict(cycles=cycles,task_ms=s['tick']*20,coverage=s['copied']/max(1,s['available']),
                        registration_used=registration,
                        registration_perception=perception,
                        planning='Observed registration supplies the transfer. Generated curves, pen state and DOM bounds are privileged read-only planning. Actual inputs use caller transport.')
        p,ink=command(world,s['tick'],100)
        ink = ink and contact_clear(world,s,p)
        pointer=[p[j]-registration[j] for j in (0,1)]
        point=[round(rect[0]+pointer[0]*rect[2]/960),round(rect[1]+pointer[1]*rect[3]/480)]
        actions=[]
        if mode=='full':
            if not ink and s['ink']:actions.append({'mouse':{'buttons':{'left_up':True}}})
            actions.append({'mouse':{'move':point}})
            if ink and not s['ink']:actions.append({'mouse':{'buttons':{'left_down':True}}})
        else:
            # Lift before a new target; lower only after setting its coordinates.
            if not ink and s['ink']:actions.append({'mouse':{'left_click':toggle}})
            actions.append({'mouse':{'left_click':point}})
            if ink and not s['ink']:actions.append({'mouse':{'left_click':toggle}})
        ui.send(actions);cycles+=1
        if not paused:ui.wait(.05)
    raise TimeoutError('Carbon-copy oracle exceeded its declared wall allowance')
