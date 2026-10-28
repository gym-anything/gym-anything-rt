"""Independent replay of the action-clock gesture gallery."""
from __future__ import annotations

import math

MECHANIC_ID = 'museum_of_lost_gestures_nonrealtime'
ACTION_KINDS = frozenset(('grip', 'aim', 'down', 'move', 'up', 'cancel'))


def target(track, milliseconds):
    knots = track['knots']
    i = 0
    while i + 1 < len(knots) - 1 and knots[i+1]['t_ms'] <= milliseconds:
        i += 1
    a, b = knots[i:i+2]
    f = max(0, min(1, (milliseconds-a['t_ms'])/(b['t_ms']-a['t_ms'])))
    s = f*f*(3-2*f)
    return [a['point'][j]+(b['point'][j]-a['point'][j])*s for j in (0, 1)], a['grip']


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('non-finite number')
    return value


class Simulation:
    def __init__(self, world):
        self.w = world
        self.ms = 0
        self.started = False
        self.done = False
        self.failed = ''
        self.held = None
        self.tools = [dict(point=t['initial_point'][:], velocity=[0., 0.], aim=t['initial_point'][:],
                           grip=t['initial_grip'], charge=0.) for t in world['tracks']]

    def advance(self, end):
        while self.started and not self.done and not self.failed and self.ms + self.w['tick_ms'] <= end:
            self.ms += self.w['tick_ms']
            dt = self.w['tick_ms']/1000
            for tool, track in zip(self.tools, self.w['tracks']):
                for axis, limit in enumerate((336, 390)):
                    acceleration = max(-self.w['acceleration'], min(self.w['acceleration'],
                        self.w['spring']*(tool['aim'][axis]-tool['point'][axis]) - self.w['damping']*tool['velocity'][axis]))
                    tool['velocity'][axis] = max(-self.w['speed'], min(self.w['speed'], tool['velocity'][axis]+acceleration*dt))
                    tool['point'][axis] = max(8, min(limit-8, tool['point'][axis]+tool['velocity'][axis]*dt))
                    if tool['point'][axis] in (8, limit-8):
                        tool['velocity'][axis] = 0
                point, grip = target(track, self.ms)
                good = math.dist(point, tool['point']) + self.w['tip_radius'] <= self.w['parameters']['radius'] and grip == tool['grip']
                tool['charge'] = max(0, min(self.w['charge_cap'], tool['charge'] + dt*(1 if good else -self.w['decay'])))
            if all(t['charge'] >= self.w['charge_seconds'] - 1e-9 for t in self.tools):
                self.done = True
            elif self.ms >= self.w['deadline_ms']:
                self.failed = 'The traces faded before the exhibition closed.'

    def advance_action(self):
        """Advance exactly one task-local slice after a deliberate input."""
        self.advance(min(self.ms + self.w['action_step_ms'], self.w['deadline_ms']))

    def event(self, e, mode):
        if self.done or self.failed:
            raise ValueError('input after terminal outcome')
        kind = e['kind']
        if kind == 'start':
            if self.started or e['t_ms'] != 0 or self.held is not None:
                raise ValueError('invalid or repeated start')
            self.started = True
            return
        if kind == 'close':
            self.failed = 'The exhibition was closed before every trace was restored.'
            return
        index = e.get('tool')
        if type(index) is not int or not 0 <= index < len(self.tools):
            raise ValueError('unknown tool')
        tool = self.tools[index]
        if kind == 'grip':
            if mode != 'simplified' or e.get('grip') not in (0, 2):
                raise ValueError('wrong grip input surface')
            tool['grip'] = e['grip']
            return
        p = e.get('point')
        if not isinstance(p, list) or len(p) != 2:
            raise ValueError('malformed point')
        x, y = (number(v) for v in p)
        bounds = (0, 336, 0, 390) if kind == 'down' else (8, 328, 8, 382)
        if not bounds[0] <= x <= bounds[1] or not bounds[2] <= y <= bounds[3]:
            raise ValueError('aim outside the chamber')
        if kind == 'aim':
            if mode != 'simplified':
                raise ValueError('wrong aim input surface')
            tool['aim'] = p[:]
        elif kind == 'down':
            if mode != 'full' or self.held is not None or e.get('button') not in (0, 2):
                raise ValueError('invalid drag start')
            if math.dist(p, tool['point']) > self.w['pickup_radius'] + .001:
                raise ValueError('drag must start on the brass handle')
            self.held = (index, e['button'])
            tool['grip'] = e['button']
        elif kind in ('move', 'up', 'cancel'):
            if mode != 'full' or self.held is None or self.held[0] != index:
                raise ValueError('unpaired drag')
            tool['aim'] = p[:]
            if kind != 'move':
                self.held = None
        else:
            raise ValueError('unknown input kind')

    def snapshot(self):
        return dict(ms=self.ms, started=self.started, done=self.done, failed=self.failed,
                    held=list(self.held) if self.held else None, tools=self.tools)


def grade(payload, ground_truth, public_state):
    def fail(text):
        return dict(graded=True, passed=False, score=0, feedback=text)
    try:
        if not all(isinstance(x, dict) for x in (payload, ground_truth, public_state)):
            return fail('invalid envelope')
        for key in ('mechanic_id', 'task_id', 'challenge_id'):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail('stale or wrong ' + key)
        if ground_truth['mechanic_id'] != MECHANIC_ID:
            return fail('wrong mechanic')
        for key in ('world', 'control_condition'):
            if public_state.get(key) != ground_truth.get(key):
                return fail('public contract mismatch')
        condition = ground_truth.get('control_condition')
        if payload.get('control_condition') != condition:
            return fail('condition mismatch')
        mode = (condition or {}).get('interaction', 'full')
        if mode not in ('full', 'simplified'):
            return fail('wrong interaction')
        events = payload.get('events')
        if not isinstance(events, list) or not 1 <= len(events) <= 15000:
            return fail('missing or excessive input trace')
        sim = Simulation(ground_truth['world'])
        for sequence, e in enumerate(events, 1):
            if not isinstance(e, dict) or e.get('sequence') != sequence or e.get('input_source') != mode:
                return fail('invalid sequence or input surface')
            t = number(e.get('t_ms'))
            if t != sim.ms or (not sim.started and t != 0):
                return fail('task time must equal the action clock')
            sim.event(e, mode)
            if e.get('kind') in ACTION_KINDS:
                sim.advance_action()
        final = number(payload.get('final_t_ms'))
        if final != sim.ms:
            return fail('final task time must equal the action clock')
        charges = payload.get('charges')
        if not isinstance(charges, list) or len(charges) != len(sim.tools):
            return fail('missing trace charges')
        if any(abs(number(c)-t['charge']) > .0001 for c, t in zip(charges, sim.tools)):
            return fail('forged trace charges')
        if payload.get('completed') is not sim.done:
            return fail('forged restoration')
        passed = sim.done and not sim.failed
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback='All fading traces restored together.' if passed else sim.failed or 'Traces are still incomplete.')
    except (ValueError, KeyError, TypeError, OverflowError, IndexError) as exc:
        return fail('invalid kinetic trace: ' + str(exc))


def cheat(public_state, ground_truth):
    return dict(instruction='Track all memory rings with the shown grip; planning is privileged.', world=ground_truth['world'])
