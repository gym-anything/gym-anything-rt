"""Privileged oracle planning; solve() emits only literal downstream HTTP inputs.

simulation_trace is a separate exact-state diagnostic and cannot establish
action-space parity. It never drives a browser or claims a model score.
"""
from __future__ import annotations
import math
import time
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.coordinates_by_another_name_v3 import (
    impact, options, position, sonar_contacts, target_parts,
)


def choose(world, t, damaged, delivery_ms=0, uncertainty_ms=0):
    """Candidate using only the rolling forecast, with a transport margin."""
    if delivery_ms+uncertainty_ms+world["parameters"]["flight_ms"] > world["preview_ms"]:
        raise ValueError("candidate requires information outside the visible forecast")
    best = None
    for cell in world["cells"]:
        times = [t+world["parameters"]["flight_ms"]+delivery_ms+dt for dt in (-uncertainty_ms,0,uncertainty_ms)]
        results = [impact(world,cell,at,damaged) for at in times]
        if any(protected or not hits for hits,protected in results):
            continue
        common = set.intersection(*(set(hits) for hits,_ in results))
        if not common:
            continue
        margin = math.inf
        for at in times:
            for ship in world["fleet"]:
                center=position(world,ship,at)
                for part,offset in enumerate(ship["offsets"]):
                    key=f'{ship["id"]}:{part}'
                    distance=math.dist([cell["x"],cell["y"]],[center[a]+offset[a] for a in range(2)])
                    tolerance=ship["radius"]+world["parameters"]["blast_radius"]
                    if key in common:
                        margin=min(margin,tolerance-distance)
                    elif ship["protected"]:
                        margin=min(margin,distance-tolerance)
        score=(len(common),margin)
        if best is None or score>best[0]:
            best=(score,cell)
    return best[1] if best and best[0][1]>=3 else None


def indices_for(world,cell):
    return [values.index(cell[key]) for values,key in zip(options(world),("band","block","count"))]


def drag_event(axis,index,n):
    angle=math.radians(-210+240*index/(n-1))
    return dict(axis=axis,index=index,input_source="rotary_drag",start=[84,84],
                release=[84+69*math.cos(angle),84+69*math.sin(angle)])


def _box(ui,selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def _click(ui,selector):
    r=_box(ui,selector);return ui.send([{"mouse":{"left_click":[r[0]+r[2]/2,r[1]+r[3]/2]}}])


def _set_indices(ui, world, mode, wanted):
    """Use the existing knobs/buttons for preparation inspections."""
    opts = options(world)
    current = ui.read('coordinatesByAnotherNameV3Model.indices')
    actions = []
    for axis, index in enumerate(wanted):
        if index == current[axis]:
            continue
        if mode == 'simplified':
            r = _box(ui, f'.cv-values button[data-axis="{axis}"][data-index="{index}"]')
            actions.append({'mouse': {'left_click': [r[0]+r[2]/2, r[1]+r[3]/2]}})
        else:
            r = _box(ui, f'.cv-dial[data-axis="{axis}"]')
            x, y = drag_event(axis, index, len(opts[axis]))['release']
            actions.extend([{'mouse': {'move': [r[0]+r[2]/2, r[1]+r[3]/2], 'buttons': {'left_down': True}}},
                            {'mouse': {'move': [r[0]+x*r[2]/168, r[1]+y*r[3]/168]}},
                            {'mouse': {'buttons': {'left_up': True}}}])
    if actions:
        ui.send(actions)


def solve(ui,truth,*,delivery_ms=80,uncertainty_ms=80,timeout_seconds=180):
    """Works with native HTTPUI; read-only state supplies oracle planning only."""
    world=truth['world'];mode=truth['control_condition']['interaction'];opts=options(world)
    # Systematic search uses the visible band/block chart, without an oracle
    # location shortcut. There is no minimum scan count in the game or grader.
    for band_index in range(len(opts[0])):
        for block_index in range(len(opts[1])):
            _set_indices(ui, world, mode, [band_index, block_index, 0])
            _click(ui, '#cv-scan')
    _click(ui,'#cv-start')
    deadline=time.monotonic()+timeout_seconds
    while time.monotonic()<deadline:
        snap=ui.read('({t:coordinatesByAnotherNameV3Model.t,terminal:coordinatesByAnotherNameV3Model.terminal,failed:coordinatesByAnotherNameV3Model.failed,pending:!!coordinatesByAnotherNameV3Model.pending,damaged:[...coordinatesByAnotherNameV3Model.damaged],echoUntil:coordinatesByAnotherNameV3Model.echoUntil,indices:coordinatesByAnotherNameV3Model.indices})')
        if snap['terminal']:
            assert not snap['failed'],snap
            assert set(snap['damaged'])==target_parts(world),snap
            return
        if snap['echoUntil']-snap['t']<delivery_ms+world['parameters']['flight_ms']+500:
            _click(ui,'#cv-scan')
            # A scan request advances the frozen evaluator's observation
            # window. Re-read that post-request state before choosing a shot.
            continue
        if snap['pending']:
            ui.wait(.1);continue
        cell=choose(world,snap['t'],set(snap['damaged']),delivery_ms,uncertainty_ms)
        if cell is None:
            ui.wait(.1);continue
        actions=[]
        for axis,index in enumerate(indices_for(world,cell)):
            if index==snap['indices'][axis]:continue
            if mode=='simplified':
                r=_box(ui,f'.cv-values button[data-axis="{axis}"][data-index="{index}"]')
                actions.append({'mouse':{'left_click':[r[0]+r[2]/2,r[1]+r[3]/2]}})
            else:
                r=_box(ui,f'.cv-dial[data-axis="{axis}"]')
                x,y=drag_event(axis,index,len(opts[axis]))['release']
                actions.extend([{'mouse':{'move':[r[0]+r[2]/2,r[1]+r[3]/2],'buttons':{'left_down':True}}},
                                {'mouse':{'move':[r[0]+x*r[2]/168,r[1]+y*r[3]/168]}},
                                {'mouse':{'buttons':{'left_up':True}}}])
        r=_box(ui,'#cv-fire');actions.append({'mouse':{'left_click':[r[0]+r[2]/2,r[1]+r[3]/2]}})
        ui.send(actions)
        ui.wait(.12)
    raise AssertionError('Symbolic sonar oracle timed out')


def simulation_trace(public,truth,*,policy='feedback',staleness_ms=0):
    """Matched-world diagnostic with exact geometry; no input-parity claim."""
    w=truth['world'];mode=truth['control_condition']['interaction'];events=[];damaged=set();t=0;failed=False;shots=0
    def event(action,source,**extra):events.append(dict(sequence=len(events)+1,t_ms=t,action=action,input_source=source,**extra))
    for band_index, band in enumerate(options(w)[0]):
        for block_index, block in enumerate(options(w)[1]):
            for axis, index in enumerate([band_index, block_index]):
                extra = (drag_event(axis,index,len(options(w)[axis])) if mode=='full'
                         else dict(axis=axis,index=index,input_source='value_button'))
                source=extra.pop('input_source');event('select',source,**extra)
            event('scan','scan_button',sector=[band,block],contacts=sonar_contacts(w,band,block,t))
    event('start','start_button');initial=[]
    for ship in w['fleet']:
        if ship['protected']:continue
        for o in ship['offsets']:
            center=position(w,ship,0)
            initial.append(min(w['cells'],key=lambda c:math.dist([c['x'],c['y']],[center[a]+o[a] for a in range(2)])))
    while t<w['play_time_ms'] and damaged!=target_parts(w):
        if policy=='feedback':cell=choose(w,t,damaged)
        elif policy=='parked':cell=initial[0]
        elif policy=='initial_script':cell=initial[min(shots,len(initial)-1)]
        elif policy=='preparation_only':break
        else:raise ValueError(policy)
        if cell is None:t+=100;continue
        t+=staleness_ms
        for axis,index in enumerate(indices_for(w,cell)):
            extra=drag_event(axis,index,len(options(w)[axis])) if mode=='full' else dict(axis=axis,index=index,input_source='value_button')
            source=extra.pop('input_source');event('select',source,**extra)
        event('fire','fire_button',designation=[cell[k] for k in ('band','block','count')]);shots+=1
        t+=w['parameters']['flight_ms']
        hits,protected=impact(w,cell,t,damaged)
        if not hits or protected:failed=True;break
        damaged.update(hits)
        if damaged!=target_parts(w):t+=100
    return dict(mechanic_id=MECHANIC_ID,task_id=truth['task_id'],challenge_id=truth['challenge_id'],interaction_mode=mode,
                events=events,final_t_ms=min(t,w['play_time_ms']),completed=damaged==target_parts(w) and not failed,
                final=dict(damaged=sorted(damaged),shots=shots,failed=failed))


MECHANIC_ID='coordinates_by_another_name_v3'
