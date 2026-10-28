"""Privileged interception planner with literal downstream-shaped inputs.

The supplied transport determines whether these are actual native HTTP inputs
or separately labelled headless Playwright diagnostics. Planning reads exact
motion and courier state; it is not a screenshot-only model policy.
"""
from __future__ import annotations

import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.hearthlift_courier_v3 import center, velocity, chart_point


class ObservedRail:
    """Interpolate measured UI samples, without motor programs or extrapolation.

    Each support has twenty xyz samples at -600, -400, ..., 3200 ms
    relative to the last observation. Acquisition/measurement is deliberately
    separate: supplying exact projected coordinates is still privileged, and
    this class does not claim to decode a screenshot. Four nearby samples
    estimate curvature and inherited velocity, rather than treating each
    200-ms segment as constant-velocity motion.
    """
    def __init__(self, samples):
        self.samples = {}
        for identity, points in samples.items():
            if len(points) != 20 or any(len(p) != 3 for p in points):
                raise ValueError('Expected twenty observed xyz rail samples')
            values = [[float(x) for x in p] for p in points]
            if any(not math.isfinite(x) for p in values for x in p):
                raise ValueError('Non-finite observed rail coordinate')
            self.samples[identity] = values
        self.last_requested_ms = -600

    def position(self, identity, offset_ms):
        if not -600 <= offset_ms <= 3200:
            raise ValueError('Position is outside the observed rail')
        self.last_requested_ms = max(self.last_requested_ms, offset_ms)
        points = self.samples[identity]
        u = (offset_ms + 600) / 200
        first = max(0, min(16, math.floor(u) - 1))
        x = u - first
        # Lagrange interpolation at local sample indices 0, 1, 2, 3.
        weights = [-(x-1)*(x-2)*(x-3)/6, x*(x-2)*(x-3)/2,
                   -x*(x-1)*(x-3)/2, x*(x-1)*(x-2)/6]
        return [sum(weights[j] * points[first+j][axis] for j in range(4))
                for axis in range(3)]

    def velocity(self, identity, offset_ms):
        # Match the physics' centered 20-ms velocity measurement. Samples at
        # the boundary lack that interval, so do not invent a future tail.
        if not -590 <= offset_ms <= 3190:
            raise ValueError('Velocity is outside the observed rail')
        a = self.position(identity, offset_ms-10)
        b = self.position(identity, offset_ms+10)
        return [(y-x)*50 for x, y in zip(a, b)]


def observed_intercept(geometry, snapshot, rail, target_id, *,
                       delivery_delay_ms=600, landing_offset=(0., 0.)):
    """Plan a literal coordinate hop from a bounded measured rail.

    geometry must contain support ids/half-extents, physics and chart mapping,
    with motor programs removed. snapshot supplies observed courier position
    and support. A target offset permits edge landings, backward hops and
    skips; the actual replay decides which top is contacted first. This is a
    feasible interception planner, not a globally optimal continuation policy.
    None means no supported candidate in this forecast, not unsolvability.
    """
    if not isinstance(rail, ObservedRail):
        raise TypeError('Use an ObservedRail with bounded visible samples')
    platforms = {p['id']:p for p in geometry['platforms']}
    if any('motion' in p for p in platforms.values()):
        raise ValueError('Observed planning must not receive motor programs')
    support = snapshot['support']
    if support is None:
        return None
    if not 0 <= delivery_delay_ms <= 3190:
        raise ValueError('Delivery is outside the observed rail')
    target = platforms[target_id]
    s = geometry['physics']
    if (len(landing_offset) != 2 or
        any(not math.isfinite(x) for x in landing_offset)):
        raise ValueError('Invalid landing offset')
    if any(abs(x)+s['radius'] > half for x, half in
           zip(landing_offset, target['half'])):
        return None
    old = rail.position(support, 0)
    current = rail.position(support, delivery_delay_ms)
    p = [snapshot['position'][0]+current[0]-old[0], current[1],
         snapshot['position'][2]+current[2]-old[2]]
    pv = rail.velocity(support, delivery_delay_ms)
    vy = s['jump_speed'] + pv[1]*s['inherit']
    previous = p[1]-rail.position(target_id, delivery_delay_ms)[1]
    limit = math.floor((3200-delivery_delay_ms)/10)
    for k in range(1, limit+1):
        seconds = k*.01
        c = rail.position(target_id, delivery_delay_ms+k*10)
        delta = p[1]+vy*seconds-s['gravity']*.00005*k*(k+1)-c[1]
        if previous >= 0 and delta < 0 and vy-s['gravity']*seconds < 0:
            vx = (c[0]+landing_offset[0]-p[0])/seconds
            vz = (c[2]+landing_offset[1]-p[2])/seconds
            aim = [p[0]+(vx-pv[0]*s['inherit'])*s['aim_seconds'],
                   p[2]+(vz-pv[2]*s['inherit'])*s['aim_seconds']]
            point = chart_point(geometry, aim)
            chart = geometry['chart']
            if (math.hypot(vx, vz) <= s['speed_limit']*.96 and
                0 <= point[0] <= chart['width'] and
                0 <= point[1] <= chart['height']):
                return dict(aim=aim, point=point,
                    selection=chart_point(geometry, [p[0], p[2]]),
                    target=target_id, landing_offset=list(landing_offset),
                    contact_seconds=seconds,
                    last_forecast_query_ms=rail.last_requested_ms)
        previous = delta
    return None


def intercept(world, snapshot, target_id, delivery_delay_ms=0):
    """Compute a coordinate aim, never an object-target/autocatch command."""
    s=world["physics"]; platforms={p["id"]:p for p in world["platforms"]}
    if snapshot["support"] is None: return None
    t=(snapshot["tick"]*10)+delivery_delay_ms
    support=platforms[snapshot["support"]]
    old=center(support,snapshot["tick"]*10); current=center(support,t)
    p=[snapshot["position"][0]+current[0]-old[0],current[1],
       snapshot["position"][2]+current[2]-old[2]]
    pv=velocity(support,t); vy=s["jump_speed"]+s["inherit"]*pv[1]
    previous=p[1]-center(platforms[target_id],t)[1]
    for k in range(1,350):
        h=.01*k; target=center(platforms[target_id],t+k*10)
        y=p[1]+vy*h-s["gravity"]*.00005*k*(k+1)
        delta=y-target[1]
        if previous>=0 and delta<0 and vy-s["gravity"]*h<0:
            vx=(target[0]-p[0])/h; vz=(target[2]-p[2])/h
            if math.hypot(vx,vz)>s["speed_limit"]*.96: return None
            aim=[p[0]+(vx-pv[0]*s["inherit"])*s["aim_seconds"],
                 p[2]+(vz-pv[2]*s["inherit"])*s["aim_seconds"]]
            point=chart_point(world,aim);chart=world['chart']
            if not 0<=point[0]<=chart['width'] or not 0<=point[1]<=chart['height']:
                return None
            return aim
        previous=delta
    return None


def _box(ui,selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def _click(ui,selector):
    r=_box(ui,selector);ui.send([{'mouse':{'left_click':[r[0]+r[2]/2,r[1]+r[3]/2]}}])


def inspect_lift(ui, world, identity):
    """Click a visible lift top; exact coordinates are privileged diagnostics."""
    snap=ui.read('hearthliftCourierV3Model.sim.snapshot()')
    platform=next(p for p in world['platforms'] if p['id']==identity)
    c=center(platform,snap['tick']*10)
    point=chart_point(world,[c[0],c[2]])
    r=_box(ui,'#hc-chart')
    ui.send([{'mouse':{'left_click':[r[0]+point[0]*r[2]/1000,r[1]+point[1]*r[3]/290]}}])


def solve(ui,truth,*,delivery_delay_ms=40,timeout_seconds=120):
    world=truth['world'];mode=truth['control_condition']['interaction']
    rect=_box(ui,'#hc-chart')
    def screen(point):return [rect[0]+point[0]*rect[2]/1000,rect[1]+point[1]*rect[3]/290]
    _click(ui,'#hc-start');deadline=time.monotonic()+timeout_seconds
    sequence=[p['id'] for p in world['platforms']][1:]
    for target in sequence:
        if ui.read('hearthliftCourierV3Model.sim.support')==target:
            continue
        inspect_lift(ui,world,target)
        while time.monotonic()<deadline:
            snap=ui.read('hearthliftCourierV3Model.sim.snapshot()')
            assert not snap['failed'],snap
            if snap['support']==target:break
            if snap['support']:
                aim=intercept(world,snap,target,delivery_delay_ms)
                if aim is not None:
                    here=screen(chart_point(world,[snap['position'][0],snap['position'][2]]))
                    there=screen(chart_point(world,aim))
                    if mode=='full':
                        ui.send([{'mouse':{'move':here,'buttons':{'left_down':True}}},
                                 {'mouse':{'move':there}}, {'mouse':{'buttons':{'left_up':True}}}])
                    else:ui.send([{'mouse':{'left_click':here}},{'mouse':{'left_click':there}}])
            ui.wait(.08)
        else:raise AssertionError('Courier oracle timed out waiting for '+target)
    if mode=='full':ui.send([{'keyboard':{'keys':['e']}}])
    else:_click(ui,'#hc-burn')
    _click(ui,'#hc-seal')


def simulation_trace(public,truth,*,seed_policy='observed',staleness_ms=0):
    """Exact-state simulation diagnostic, not a browser/API success trace."""
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.hearthlift_courier_v3 import Physics
    sim=Physics(truth['world']);events=[];mode=truth['control_condition']['interaction']
    source='courier_drag' if mode=='full' else 'chart_click'
    def record(kind,**kw):events.append(dict(seq=len(events)+1,tick=sim.tick,kind=kind,input_source=source,**kw))
    events.append(dict(seq=1,tick=0,kind='start',input_source='start_button'));sim.start()
    for target in sim.world['platforms'][1:]:
        for _ in range(1000):
            snapshot=sim.snapshot();aim=intercept(sim.world,snapshot,target['id'])
            if aim is not None:break
            sim.advance(sim.tick+10)
        else:break
        if seed_policy=='nominal':aim=[target['center'][0],target['center'][2]]
        # With stale observations, actions use the old coordinate plan while
        # the complete same world continues evolving during the delay.
        sim.advance(sim.tick+staleness_ms//10)
        record('aim_start' if mode=='full' else 'select',point=chart_point(sim.world,[sim.p[0],sim.p[2]]))
        record('launch',point=chart_point(sim.world,aim))
        try:sim.launch(aim)
        except ValueError:
            events[-1]['kind']='cancel';break
        while sim.support is None and not sim.failed:sim.advance(sim.tick+10)
        if sim.failed or sim.support!=target['id']:break
    if not sim.failed and sim.support=='hearth':
        events.append(dict(seq=len(events)+1,tick=sim.tick,kind='burn',input_source='keyboard_e' if mode=='full' else 'burn_button'));sim.burn()
    events.append(dict(seq=len(events)+1,tick=sim.tick,kind='seal',input_source='certify_button'))
    result={k:public[k] for k in ['mechanic_id','task_id','challenge_id','control_condition']}
    result.update(physics_revision='moving-crate-hops-v2',interaction_mode=mode,events=events,
                  final_state=sim.snapshot(),completed=sim.delivered and not sim.failed)
    return result
