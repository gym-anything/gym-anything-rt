"""Standalone deterministic replay. No client health, completion or hit claims trusted."""
from __future__ import annotations

import math

MECHANIC_ID = "funeral_ritual_v2"


def clamp(x, a, b):
    return max(a, min(b, x))


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xffffffff
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0, ms)/span
    i = math.floor(u)
    f = u-i
    return noise(seed, i)+(noise(seed, i+1)-noise(seed, i))*f*f*(3-2*f)


def wind(s, i, ms):
    c = s['candles'][i]
    return c['x']+s['parameters']['wind_amplitude']*motion(c['wind_seed'], ms, s['parameters']['wind_span_ms'])


def flower_point(s, i, ms):
    f = s['flowers'][i]
    return [f['x']+34*motion(f['motion_seed'], ms, 4700),
            f['y']+18*motion(f['motion_seed']+7919, ms, 5300)]


def socket_point(s, i, ms):
    f = s['sockets'][i]
    return [f['x']+s['parameters']['socket_amplitude']*motion(f['motion_seed'], ms, 4200),
            f['y']+16*motion(f['motion_seed']+7919, ms, 5700)]


MOSS = [[414+(i % 3)*60, 257+(i//3)*29, 52, 23] for i in range(6)]


def inside(p, r):
    return r[0] <= p[0] <= r[0]+r[2] and r[1] <= p[1] <= r[1]+r[3]


class Vigil:
    def __init__(self, state):
        self.s = state
        self.ms = 0
        self.active = False
        self.inspected = False
        self.moss = set()
        self.targets = [c['x'] for c in state['candles']]
        self.x = self.targets.copy()
        self.v = [0.]*len(self.x)
        self.health = [1.]*len(self.x)
        self.offered = []
        self.carried = None
        self.hold = None
        self.failed = ''
        self.sealed = False

    def advance(self, end):
        if not self.active:
            return
        p, r = self.s['parameters'], self.s['ritual']
        while self.ms+20 <= end and not self.failed and not self.sealed:
            self.ms += 20
            for i, c in enumerate(self.s['candles']):
                if p.get('shield_response') == 'direct':
                    self.x[i] = self.targets[i]
                    self.v[i] = 0
                else:
                    a = clamp((self.targets[i]-self.x[i])*25-self.v[i]*10,
                              -p['shield_acceleration'], p['shield_acceleration'])
                    self.v[i] = clamp(self.v[i]+a*.02, -p['shield_speed'], p['shield_speed'])
                    self.x[i] = clamp(self.x[i]+self.v[i]*.02, c['x']-130, c['x']+130)
                    if self.x[i] in (c['x']-130, c['x']+130):
                        self.v[i] = 0
                protected = abs(self.x[i]-wind(self.s, i, self.ms)) <= p['shield_width']/2
                self.health[i] = clamp(self.health[i]+.02*(r['flame_recovery_per_s'] if protected
                                                          else -r['flame_loss_per_s']), 0, 1)
                if self.health[i] <= 0:
                    self.failed = 'A candle went out.'
            if self.ms >= r['max_active_ms']:
                self.failed = 'The vigil was abandoned.'

    def action(self, kind, point, mode, item=None):
        """Points are in the rendered 1000×580 canvas, including proxy geometry."""
        if self.failed or self.sealed:
            raise ValueError('terminal episode')
        s = self.s
        if kind == 'inspect':
            if not inside(point, [380, 249, 240, 89]) or self.active:
                raise ValueError('inspect the stone')
            self.inspected = True
        elif kind in ('brush', 'clear'):
            if not self.inspected or self.active:
                raise ValueError('inspect before brushing')
            if kind == 'clear':
                if mode != 'simplified' or not inside(point, [400, 300, 200, 28]):
                    raise ValueError('wrong brush proxy')
                self.moss = set(range(6))
            else:
                if mode != 'full':
                    raise ValueError('wrong brush surface')
                for i, rect in enumerate(MOSS):
                    if inside(point, rect):
                        self.moss.add(i)
        elif kind == 'light':
            if self.active or len(self.moss) != 6:
                raise ValueError('uncover the memorial before lighting')
            if not any(inside(point, [c['x']-15, c['y']-14, 30, 38]) for c in s['candles']):
                raise ValueError('light a candle')
            self.active = True
        elif kind == 'seal' and not self.active:
            self.failed = 'The vigil was incomplete.'
        elif not self.active:
            raise ValueError('light the candles first')
        elif kind in ('shield_start', 'shield_move', 'shield_end', 'shield_target'):
            if type(item) is not int or not 0 <= item < len(self.x):
                raise ValueError('unknown shield')
            c = s['candles'][item]
            if kind == 'shield_target':
                if mode != 'simplified' or not inside(point, [c['x']-130, 108, 260, 34]):
                    raise ValueError('click this shield rail')
                self.targets[item] = clamp(point[0], c['x']-130, c['x']+130)
            else:
                if mode != 'full':
                    raise ValueError('wrong shield input')
                if kind == 'shield_start':
                    if self.hold or self.carried is not None or not inside(point, [self.x[item]-s['parameters']['shield_width']/2, 108, s['parameters']['shield_width'], 34]):
                        raise ValueError('drag the actual shield')
                    self.hold = ('shield', item)
                elif self.hold != ('shield', item):
                    raise ValueError('shield is not held')
                if kind == 'shield_move':
                    self.targets[item] = clamp(point[0], c['x']-130, c['x']+130)
                if kind == 'shield_end':
                    self.hold = None
            if kind in ('shield_target', 'shield_move') and s['parameters'].get('shield_response') == 'direct':
                self.x[item] = self.targets[item]
                self.v[item] = 0
        elif kind == 'pick':
            if type(item) is not int or item in self.offered or not 0 <= item < len(s['flowers']) or self.carried is not None or self.hold:
                raise ValueError('unavailable flower')
            if math.dist(point, flower_point(s, item, self.ms)) > 27:
                raise ValueError('pickup misses the visible flower')
            if item != s['order'][len(self.offered)]:
                self.failed = 'The tribute order was broken.'
            else:
                self.carried = item
                if mode == 'full':
                    self.hold = ('flower', item)
        elif kind in ('offer', 'cancel'):
            if self.carried is None:
                raise ValueError('no flower is carried')
            if mode == 'full' and self.hold != ('flower', self.carried):
                raise ValueError('flower is not held')
            if kind == 'cancel':
                self.carried = self.hold = None
            else:
                slot = len(self.offered)
                if math.dist(point, socket_point(s, slot, self.ms))+s['ritual']['flower_radius'] > s['parameters']['socket_radius']:
                    self.failed = 'A flower fell outside its resting place.'
                else:
                    self.offered.append(self.carried)
                    self.carried = self.hold = None
        elif kind == 'seal':
            if self.ms < s['ritual']['vigil_ms'] or self.offered != s['order'] or self.carried is not None or self.hold:
                self.failed = 'The vigil was incomplete.'
            else:
                self.sealed = True
        else:
            raise ValueError('unknown action')


def grade(payload, truth, public):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(x, dict) for x in (payload, truth, public)):
            return fail('invalid result object')
        for k in ('mechanic_id', 'task_id', 'challenge_id', 'revision'):
            if not truth.get(k) or payload.get(k) != truth[k] or public.get(k) != truth[k]:
                return fail('stale or mismatched '+k)
        if truth['mechanic_id'] != MECHANIC_ID:
            return fail('wrong mechanic')
        for k in ('parameters', 'ritual', 'candles', 'flowers', 'sockets', 'order', 'stage', 'control_condition'):
            if truth.get(k) != public.get(k):
                return fail('public contract mismatch: '+k)
        mode = truth.get('control_condition', {}).get('interaction', 'full')
        if mode not in ('full', 'simplified') or payload.get('interaction_mode') != mode:
            return fail('wrong interaction mode')
        events = payload.get('events')
        if not isinstance(events, list) or not 1 <= len(events) <= 15000:
            return fail('missing action transcript')
        v = Vigil(truth)
        last = 0
        for seq, e in enumerate(events, 1):
            if not isinstance(e, dict):
                return fail('invalid event object')
            t = e.get('t_ms')
            if type(t) is not int or not last <= t <= truth['ritual']['max_active_ms'] or e.get('sequence') != seq or e.get('input_source') != mode:
                return fail('invalid event order, time or surface')
            if not v.active and t != 0:
                return fail('preparation has no active task time')
            last = t
            v.advance(t)
            if v.failed:
                return fail(v.failed)
            point = e.get('point')
            if not isinstance(point, list) or len(point) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in point) or not inside(point, [0, 0, 1000, 580]):
                return fail('invalid canvas point')
            v.action(e['kind'], point, mode, e.get('item'))
            if v.failed:
                return fail(v.failed)
        end = payload.get('final_t_ms')
        if type(end) is not int or not last <= end <= truth['ritual']['max_active_ms']:
            return fail('invalid final task time')
        v.advance(end)
        passed = v.sealed and not v.failed and payload.get('completed') is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=v.failed or f'Vigil replay: {len(v.offered)}/{len(truth["order"])} offerings; {v.ms/1000:g}s; '+('sealed' if passed else 'incomplete'))
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as exc:
        return fail('invalid vigil trace: '+str(exc))


def cheat(public_state, ground_truth):
    return {'order': ground_truth.get('order'), 'planning': 'privileged; inputs remain ordinary mouse actions'}
