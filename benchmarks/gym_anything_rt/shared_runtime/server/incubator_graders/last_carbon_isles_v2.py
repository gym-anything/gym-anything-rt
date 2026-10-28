"""Independent fixed-step conservation replay. Client completion flags are not evidence."""
from __future__ import annotations

import copy
import bisect
import math

MECHANIC_ID = 'last_carbon_isles_v2'


def loads(spec, t):
    result = [spec['total_load']/len(spec['islands'])]*len(spec['islands'])
    for mode in spec['modes']:
        time = t+mode['offset_s']
        k = bisect.bisect_right(mode['times'],time)-1
        f = (time-mode['times'][k])/(mode['times'][k+1]-mode['times'][k])
        a, b = mode['knots'][k:k+2]
        value = mode['amplitude']*(a+(b-a)*f*f*(3-2*f))
        for i, coefficient in enumerate(mode['vector']):
            result[i] += value*coefficient
    return result


class Simulation:
    def __init__(self, spec):
        self.spec = spec
        self.tick = 0
        self.targets = [s['initial_share'] for s in spec['islands']]
        self.supply = list(self.targets)
        self.battery = [s['battery_capacity'] for s in spec['islands']]
        self.minimum = list(self.battery)
        self.energy = [0.]*len(self.targets)
        self.failure = None
        self.done = False

    @property
    def time(self):
        return self.tick*self.spec['step_s']

    def advance(self, until):
        dt = self.spec['step_s']
        end = min(math.floor((until+1e-8)/dt), round(self.spec['run_seconds']/dt))
        while self.tick < end and not self.failure and not self.done:
            demand = loads(self.spec, (self.tick+.5)*dt)
            total = sum(self.targets)
            factor = min(1., self.spec['capacity']/total) if total else 1.
            alpha = 1-math.exp(-dt/self.spec['parameters']['inertia_s'])
            for i, target in enumerate(self.targets):
                self.supply[i] += (target*factor-self.supply[i])*alpha
                self.battery[i] = min(self.spec['islands'][i]['battery_capacity'],
                                      self.battery[i]+(self.supply[i]-demand[i])*dt)
                self.minimum[i] = min(self.minimum[i], self.battery[i])
                self.energy[i] += demand[i]*dt
                if self.battery[i] <= 0:
                    self.failure = f"{self.spec['islands'][i]['name']}: battery empty, crews stopped"
            self.tick += 1
            self.done = not self.failure and self.tick >= round(self.spec['run_seconds']/dt)

    def set(self, index, value):
        self.targets[index] = value

    def snapshot(self):
        return dict(time=self.time, targets=list(self.targets), supply=list(self.supply),
                    battery=list(self.battery), minimum=list(self.minimum), energy=list(self.energy),
                    failure=self.failure, done=self.done)


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ('mechanic_id', 'task_id', 'challenge_id', 'revision'):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail('stale or wrong '+key)
        if ground_truth['mechanic_id'] != MECHANIC_ID:
            return fail('wrong mechanic')
        for key in ('islands','modes','parameters','capacity','total_load','run_seconds','step_s','control_condition','forecast_s'):
            if public_state.get(key) != ground_truth.get(key):
                return fail('public contract differs: '+key)
        mode = ground_truth['control_condition']['interaction']
        if payload.get('interaction_mode') != mode:
            return fail('wrong interaction')
        events = payload.get('events')
        if not isinstance(events, list) or len(events) < 2:
            return fail('missing dispatch transcript')
        sim = Simulation(ground_truth)
        started = finished = False
        held = None
        previous = -1.
        for sequence, event in enumerate(events, 1):
            t = event['t_s']
            if (type(t) not in (int,float) or not math.isfinite(t) or t < previous or
                t < 0 or t > ground_truth['run_seconds']+5 or event.get('sequence') != sequence):
                return fail('invalid sequence or time')
            previous = t
            if event.get('kind') == 'start':
                if started or t != 0 or event.get('input_source') != 'launch_button':
                    return fail('invalid launch')
                started = True
                continue
            preparing = event.get('kind') == 'prepare' and not started and t == 0
            gesture = event.get('kind') in ('grab','release') and mode == 'full' and (started or t == 0)
            if (not started and not preparing and not gesture) or finished:
                return fail('action outside transition')
            sim.advance(t)
            if sim.failure:
                return fail(sim.failure)
            if gesture:
                i = event.get('island')
                point,size=event.get('point'),event.get('rail_size')
                if type(i) is not int or not 0<=i<len(sim.targets) or event.get('input_source')!='policy_drag':
                    return fail('invalid held policy')
                if not isinstance(point,list) or len(point)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point):
                    return fail('invalid held-pointer geometry')
                if not isinstance(size,list) or len(size)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in size) or not 100<=size[0]<=2000 or size[1]!=47:
                    return fail('invalid held rail dimensions')
                if event['kind']=='grab':
                    if held is not None or abs(point[0]-sim.targets[i]/100)>26/size[0]+1e-6 or not 17/size[1]-.5<=point[1]<=.5+1/size[1]:
                        return fail('grab missed the current visible policy card')
                    held=i
                else:
                    if held!=i:return fail('release without matching held card')
                    held=None
                continue
            if event.get('kind') == 'dispatch' or preparing:
                if sim.done:
                    return fail('dispatch after completed transition')
                i, value = event['island'], event['share']
                if type(i) is not int or not 0 <= i < len(sim.targets) or type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 100:
                    return fail('invalid grid share')
                expected = 'policy_drag' if mode == 'full' else 'rail_click'
                if event.get('input_source') != expected:
                    return fail('wrong dispatch surface')
                # Geometry is normalized to the actual rendered rail: [0,1] x [-.5,.5].
                point = event['point']
                if not isinstance(point,list) or len(point) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point):
                    return fail('invalid dispatch geometry')
                if abs(point[0]*100-value) > 1e-5 or not 0 <= point[0] <= 1 or abs(point[1]) > .5:
                    return fail('dispatch outside visible rail')
                size = event.get('rail_size')
                if not isinstance(size,list) or len(size)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in size) or not 100 <= size[0] <= 2000 or size[1]!=47:
                    return fail('invalid rendered rail dimensions')
                if mode == 'full':
                    if held != i:
                        return fail('dispatch without the matching physical policy hold')
                sim.set(i,value)
            elif event.get('kind') == 'finish':
                if sequence != len(events) or not sim.done or payload.get('completed') is not True:
                    return fail('coal transition incomplete')
                finished = True
            else:
                return fail('unknown action; restart cannot erase an outage')
        if not finished:
            return fail('transition never certified')
        return dict(graded=True, passed=True, score=100,
                    feedback='all coal works retired; every crew powered; conserved clean-grid replay',
                    final=sim.snapshot())
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        return fail('invalid dispatch transcript: '+str(exc))


def cheat(public_state, ground_truth):
    return dict(note='Privileged motion planning is not a screenshot-only solution.',
                modes=copy.deepcopy(ground_truth.get('modes')))
