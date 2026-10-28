"""Independent finite-footprint, inertial and ballistic replay of the UI trace."""
from __future__ import annotations

import math
import json
import os
from pathlib import Path

MECHANIC_ID = 'downsky_causeway_v2'


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xffffffff
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff) / 4294967295 * 2 - 1


def motion(seed, ms, span):
    u = max(0, ms) / span
    n = math.floor(u)
    f = u-n
    a, b = noise(seed, n), noise(seed, n+1)
    return a+(b-a)*f*f*(3-2*f)


def deck_y(deck, ms):
    return deck['base_y']+deck['amplitude']*motion(deck['motion_seed'], ms, deck['span_ms'])


def deck_velocity(deck, ms):
    return (deck_y(deck, ms+10)-deck_y(deck, max(0, ms-10))) / (.02 if ms >= 10 else .01)


class Simulation:
    def __init__(self, world):
        self.world = world
        self.ms = 0
        self.active = False
        self.complete = False
        self.failed = ''
        self.x, self.y, self.z = (world['initial'][k] for k in ('x', 'y', 'z'))
        self.vy = self.vz = self.u = 0.
        self.support = 0
        self.landings = []
        self.start_ms = None

    def start(self):
        if self.active or self.complete or self.failed:
            return False
        self.active = True
        self.start_ms = self.ms
        return True

    def steer(self, u):
        self.u = clamp(u, -1., 1.)

    def contained(self, deck, x, y, ms):
        r = self.world['radius']
        return (deck['x0']+r-1e-9 <= x <= deck['x1']-r+1e-9 and
                abs(y-deck_y(deck, ms))+r <= deck['half_width']+1e-9)

    def advance(self, end):
        w = self.world
        while self.ms+10 <= end and not self.failed and not self.complete:
            before = self.ms
            self.ms += 10
            if not self.active:
                continue
            old_x, old_y, old_z = self.x, self.y, self.z
            previous_support = self.support
            wind = w['wind']*motion(w['wind_seed'], self.ms, w['wind_span_ms'])
            acc = clamp(w['response']*(self.u*w['max_lateral_speed']-self.vy)+wind,
                        -w['acceleration'], w['acceleration'])
            self.vy = clamp(self.vy+acc*.01, -w['max_lateral_speed'], w['max_lateral_speed'])
            self.x += w['forward_speed']*.01
            self.y += self.vy*.01
            if previous_support is not None:
                deck = w['decks'][previous_support]
                carry = deck_y(deck, self.ms)-deck_y(deck, before)
                self.y += carry
                if self.contained(deck, self.x, self.y, self.ms):
                    self.z, self.vz = deck['z'], 0.
                else:
                    self.support = None
                    self.vy += carry/.01
                    self.vz = 0.
            if self.support is None:
                self.vz -= w['gravity']*.01
                self.z += self.vz*.01
                for deck in w['decks']:
                    if old_z > deck['z']+1e-9 and self.z <= deck['z']:
                        f = (old_z-deck['z'])/(old_z-self.z)
                        impact_x = old_x+(self.x-old_x)*f
                        impact_y = old_y+(self.y-old_y)*f
                        if self.contained(deck, impact_x, impact_y, before+10*f):
                            self.support = deck['id']
                            self.z, self.vz = deck['z'], 0.
                            self.vy -= deck_velocity(deck, self.ms)
                            self.landings.append(dict(deck=deck['id'], ms=self.ms,
                                                      x=impact_x, y=impact_y))
                            break
            if self.z < -2.4:
                self.failed = 'The walker fell below the causeway.'
            elif self.ms-self.start_ms >= w['crossing_limit_ms']:
                self.failed = 'The crossing ended without an arrival.'
            elif (self.support == 6 and self.x >= w['finish_x'] and
                  abs(self.y-deck_y(w['decks'][6], self.ms))+w['radius'] <= w['finish_half_width']):
                self.complete = True

    def snapshot(self):
        return dict(ms=self.ms, active=self.active, complete=self.complete, failed=self.failed,
                    x=self.x, y=self.y, z=self.z, vy=self.vy, vz=self.vz, u=self.u,
                    support=self.support, landings=[dict(item) for item in self.landings], start_ms=self.start_ms)


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    if not all(isinstance(v, dict) for v in (payload, ground_truth, public_state)):
        return fail('Missing UI result.')
    if ground_truth.get('episode_failed') or public_state.get('episode_failed'):
        return fail('A failed submission already ended this episode.')
    directory = os.environ.get('GYM_ANYTHING_RT_STATE_DIR', '/tmp/gym_anything_rt')
    if directory:
        try:
            with (Path(directory)/'attempts.jsonl').open(encoding='utf-8') as journal:
                for line in journal:
                    if line.strip() and not json.loads(line).get('server_grade', {}).get('passed'):
                        return fail('A failed submission already ended this episode.')
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError, ValueError, AttributeError):
            return fail('Episode failure history is unavailable.')
    for key in ('mechanic_id', 'task_id', 'challenge_id'):
        if (not ground_truth.get(key) or payload.get(key) != ground_truth[key] or
                public_state.get(key) != ground_truth[key]):
            return fail('Stale or mismatched '+key)
    if ground_truth['mechanic_id'] != MECHANIC_ID:
        return fail('Wrong mechanic.')
    for key in ('world', 'control_condition', 'single_attempt'):
        if ground_truth.get(key) != public_state.get(key):
            return fail('Public/private contract mismatch: '+key)
    interaction = (ground_truth.get('control_condition') or {}).get('interaction', 'full')
    if payload.get('interaction_mode') != interaction:
        return fail('Wrong interaction mode.')
    events = payload.get('events')
    if not isinstance(events, list) or not 2 <= len(events) <= 12000:
        return fail('Missing or excessive action trace.')
    try:
        sim = Simulation(ground_truth['world'])
    except (KeyError, TypeError, ValueError):
        return fail('Invalid world contract.')
    held = False
    sealed = False
    try:
        for seq, event in enumerate(events, 1):
            if not isinstance(event, dict):
                return fail('Malformed event.')
            t = event.get('t_ms')
            if (event.get('sequence') != seq or type(t) is not int or
                    t < sim.ms or t > ground_truth['world']['max_ms'] or sealed):
                return fail('Invalid event order or time.')
            sim.advance(t)
            # Every event uses the quantized shared game clock. A terminal
            # simulation may stop before a later administrative submission.
            if not sim.complete and not sim.failed and sim.ms != t:
                return fail('Event is not on the physics clock.')
            kind = event.get('kind')
            if kind == 'start':
                if event.get('input_source') != 'start_button' or not sim.start():
                    return fail('Invalid or repeated start.')
            elif kind == 'steer_start':
                if interaction != 'full' or held or event.get('input_source') != 'tiller_drag':
                    return fail('Invalid tiller capture.')
                point = event.get('point')
                if (not isinstance(point, list) or len(point) != 2 or
                        not all(type(v) in (int, float) and math.isfinite(v) for v in point) or
                        math.dist(point, [550+sim.u*390, 565]) > 25):
                    return fail('The drag did not begin on the visible tiller.')
                held = True
            elif kind == 'steer':
                source = 'tiller_drag' if interaction == 'full' else 'tiller_click'
                u = event.get('u')
                point = event.get('point')
                if (event.get('input_source') != source or (interaction == 'full' and not held) or
                        type(u) not in (int, float) or not math.isfinite(u) or not -1 <= u <= 1 or
                        sim.failed or sim.complete):
                    return fail('Invalid steering surface or value.')
                if (not isinstance(point, list) or len(point) != 2 or
                        not all(type(v) in (int, float) and math.isfinite(v) for v in point) or
                        abs(clamp((point[0]-550)/390, -1, 1)-u) > 1e-9 or
                        (interaction == 'simplified' and not (140 <= point[0] <= 960 and 540 <= point[1] <= 590))):
                    return fail('Steering coordinates do not match the visible tiller.')
                sim.steer(u)
            elif kind == 'steer_end':
                if interaction != 'full' or not held or event.get('input_source') != 'tiller_drag':
                    return fail('Invalid tiller release.')
                held = False
            elif kind == 'seal':
                if event.get('input_source') != 'submit_button':
                    return fail('Invalid submission surface.')
                sealed = True
            else:
                return fail('Unknown event kind.')
    except (KeyError, ValueError, TypeError, OverflowError):
        return fail('Malformed physics transcript.')
    if not sealed or not sim.complete or sim.failed or payload.get('completed') is not True:
        return fail(sim.failed or 'The walker has not reached the lit pavilion.')
    final = payload.get('final')
    if not isinstance(final, dict):
        return fail('Missing final physical state.')
    for key in ('ms', 'support', 'active', 'complete', 'failed', 'start_ms'):
        if final.get(key) != sim.snapshot()[key]:
            return fail('Final state mismatch: '+key)
    for key in ('x', 'y', 'z', 'vy', 'vz', 'u'):
        v = final.get(key)
        if type(v) not in (int, float) or not math.isfinite(v) or abs(v-getattr(sim, key)) > 1e-7:
            return fail('Final physics mismatch: '+key)
    reported = final.get('landings')
    if not isinstance(reported, list) or len(reported) != len(sim.landings):
        return fail('Landing trace mismatch.')
    for actual, expected in zip(reported, sim.landings):
        if not isinstance(actual, dict):
            return fail('Malformed landing record.')
        if actual.get('deck') != expected['deck'] or actual.get('ms') != expected['ms']:
            return fail('Landing order or time mismatch.')
        if any(type(actual.get(k)) not in (int, float) or not math.isfinite(actual[k]) or
               abs(actual[k]-expected[k]) > 1e-7 for k in ('x', 'y')):
            return fail('Landing geometry mismatch.')
    return dict(graded=True, passed=True, score=100, feedback='Physical descent and pavilion arrival verified.')
