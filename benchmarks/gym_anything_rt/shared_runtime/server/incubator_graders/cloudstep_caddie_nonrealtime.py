"""Independent fixed-step projectile replay. Completion flags cannot award a pass."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

MECHANIC_ID = 'cloudstep_caddie_nonrealtime'
PHYSICS_REVISION = 'drifting-golf-v2-action-triggered'


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xffffffff
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0, ms)/span; n = math.floor(u); f = u-n
    return noise(seed, n)+(noise(seed, n+1)-noise(seed, n))*f*f*(3-2*f)


def center(green, ms):
    m = green['motion']
    return [green['center'][i]+m['amplitude'][i]*motion(m['seed']+i*7919, ms, m['span_ms']) for i in (0, 1)]+[green['center'][2]]


def velocity(green, ms):
    a, b = center(green, max(0, ms-10)), center(green, ms+10)
    dt = (ms+10-max(0, ms-10))/1000
    return [(b[i]-a[i])/dt for i in (0, 1)]


def wind(world, ms):
    s = world['physics']
    return [s['wind']*motion(s['wind_seed']+i*7919, ms, s['wind_span_ms']) for i in (0, 1)]


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('non-finite input')
    return float(value)


def point(value):
    if not isinstance(value, list) or len(value)!=2:
        raise ValueError('invalid aim point')
    x, y = map(number, value)
    if not 0<=x<=1000 or not 0<=y<=540:
        raise ValueError('aim outside map')
    return [x,y]


def _episode_failure(ground_truth, public_state):
    """Enforce first failure using the existing server's durable attempt ledger.

    Offline replays have no server episode; their exported verifier checks the
    trusted failure counter. In the server, resolve its actual --state-dir,
    bind both saved states, and trust server grades rather than browser flags.
    """
    if not sys.argv or Path(sys.argv[0]).name != 'minigame_server.py':
        return None
    state_dir = Path('/tmp/gym_anything_rt')
    for index, argument in enumerate(sys.argv[1:], 1):
        if argument == '--state-dir':
            state_dir = Path(sys.argv[index+1])
        elif argument.startswith('--state-dir='):
            state_dir = Path(argument.split('=', 1)[1])
    try:
        saved_truth = json.loads((state_dir/'ground_truth.json').read_text())
        saved_public = json.loads((state_dir/'public_state.json').read_text())
        if saved_truth != ground_truth or saved_public != public_state:
            return 'Episode state does not match the bound task.'
        attempts = state_dir/'attempts.jsonl'
        if not attempts.exists():
            return None
        for line in attempts.read_text().splitlines():
            if not line.strip():
                continue
            attempt = json.loads(line)
            decision = attempt.get('server_grade') if isinstance(attempt, dict) else None
            if (isinstance(decision, dict) and decision.get('graded') is True
                    and decision.get('passed') is False):
                return 'A failed submission already ended this episode.'
    except (OSError, ValueError):
        return 'Cannot verify the saved episode history.'
    return None


class Physics:
    def __init__(self, world):
        self.world=world; self.tick=0; self.active=False; self.failed=''; self.sunk=False
        self.greens={g['id']:g for g in world['greens']}; self.cards={c['id']:c for c in world['cards']}
        self.support=world['tee']; self.p=center(self.greens[self.support], 0); self.v=[0.,0.,0.]
        self.used=[]; self.flight=None; self._action_transition=False

    def snapshot(self):
        return dict(tick=self.tick, active=self.active, failed=self.failed, sunk=self.sunk,
                    support=self.support, p=[round(x,6) for x in self.p], v=[round(x,6) for x in self.v], used=list(self.used))

    def shot(self, card_id, aim):
        if not self.active or self.failed or self.sunk or self.support is None:
            raise ValueError('no active stroke opportunity')
        if card_id not in self.cards or card_id in self.used:
            raise ValueError('card unavailable')
        c=self.cards[card_id]; origin=self.greens[self.support]; aim=point(aim)
        if origin['surface']=='sand' and c['kind']!='loft':
            raise ValueError('sand needs a loft card')
        v=[(aim[i]-self.p[i])/c['seconds'] for i in (0,1)]
        if math.hypot(*v)>c['max_speed']:
            raise ValueError('aim exceeds card reach')
        inherited=velocity(origin,self.tick*10)
        self.v=[v[i]+self.world['physics']['inherit']*inherited[i] for i in (0,1)]+[c['vz']]
        self.used.append(card_id); self.flight=dict(origin=self.support, start=self.tick); self.support=None
        # The only task-clock progress is the fixed flight deliberately
        # started by this stroke.  Once it lands, the next decision is stable.
        self._action_transition=True
        try:
            self.advance(self.tick + round(c['seconds'] * 100))
        finally:
            self._action_transition=False
        if not self.failed and not self.sunk and self.support is None:
            self.failed='Missed landing'

    def advance(self, end):
        if not self._action_transition:
            if end != self.tick:
                raise ValueError('waiting cannot advance task time')
            return
        s=self.world['physics']; r=s['radius']
        while self.tick<end and not self.failed and not self.sunk:
            before=self.p[:]; old_ms=self.tick*10; self.tick+=1; ms=self.tick*10
            if self.active and ms>=s['play_time_ms']:
                self.failed='Course time exhausted';break
            if self.support:
                a=center(self.greens[self.support],old_ms); b=center(self.greens[self.support],ms)
                self.p=[self.p[i]+b[i]-a[i] for i in range(3)]
                continue
            w=wind(self.world,ms)
            for i in (0,1):self.v[i]+=w[i]*.01;self.p[i]+=self.v[i]*.01
            self.v[2]-=s['gravity']*.01;self.p[2]+=self.v[2]*.01
            hits=[]
            if self.v[2]<0:
                for g in self.greens.values():
                    z=g['center'][2]
                    if before[2]>=z and self.p[2]<=z:
                        f=(before[2]-z)/(before[2]-self.p[2]); c=center(g,old_ms+f*10)
                        impact=[before[i]+(self.p[i]-before[i])*f for i in (0,1)]
                        # Contact anywhere on the visible top. An edge hit is a
                        # failure when the whole ball is not contained.
                        if all(abs(impact[i]-c[i])<=g['half'][i]+r for i in (0,1)):
                            hits.append((f,g,impact,c))
            if hits:
                first=min(hits,key=lambda x:x[0])
                # Only the earliest height can support the descending ball.
                # Coplanar overlapping turf is not a new exposed edge: a full
                # fit on any green at that height is valid. Resolve multiple
                # full fits in the same order as the canvas (last drawn wins).
                fits=[h for h in hits if h[1]['center'][2]==first[1]['center'][2]
                      and all(abs(h[2][i]-h[3][i])+r<=h[1]['half'][i] for i in (0,1))]
                if not fits:
                    self.failed='Ball clipped the green edge';break
                _,g,p,c=fits[-1]
                self.p=p+[g['center'][2]];self.support=g['id'];self.v=[0.,0.,0.];self.flight=None
                if g['id']==self.world['cup'] and math.dist(p,c[:2])+r<=self.world['cup_radius']:
                    if len(self.used)==len(self.cards):self.sunk=True
                    else:self.failed='Cup reached with unspent cards'
                elif len(self.used)==len(self.cards):
                    self.failed='Hand exhausted outside the cup'
                elif g['surface']=='sand' and not any(
                        card['kind']=='loft' and card_id not in self.used
                        for card_id,card in self.cards.items()):
                    # The landing commits the loss; an airborne last LOFT can
                    # still reach turf, and a blocked CHIP with LOFT stock is
                    # recoverable feedback inside the attempt.
                    self.failed='No LOFT cards remain on sand'
                # A landing is the stable endpoint of this deliberate action.
                break
            if self.p[2]<-180 or not -100<=self.p[0]<=1100 or not -100<=self.p[1]<=640:
                self.failed='Ball fell into the clouds'


def grade(payload, ground_truth, public_state):
    def fail(message):return dict(graded=True,passed=False,score=0,feedback=message)
    for key in ('mechanic_id','task_id','challenge_id','physics_revision','control_condition','world'):
        if public_state.get(key)!=ground_truth.get(key):return fail('public/private skew: '+key)
    for key in ('mechanic_id','task_id','challenge_id','physics_revision','control_condition'):
        if not ground_truth.get(key) or payload.get(key)!=ground_truth[key]:return fail('wrong or stale '+key)
    if ground_truth['mechanic_id']!=MECHANIC_ID:return fail('wrong mechanic')
    if ground_truth['physics_revision']!=PHYSICS_REVISION:return fail('unsupported physics revision')
    mode=ground_truth['control_condition']['interaction'];source='card_drag' if mode=='full' else 'card_click'
    if payload.get('interaction_mode')!=mode:return fail('wrong interaction')
    events=payload.get('events')
    if not isinstance(events,list) or not 2<=len(events)<=1000:return fail('missing or excessive transcript')
    sim=Physics(ground_truth['world']);hold=None;selected=None;sealed=False
    try:
        for seq,e in enumerate(events,1):
            tick=e['tick']
            if type(tick) is not int or not sim.tick<=tick<=18000 or e.get('seq')!=seq or sealed:
                return fail('invalid event order')
            if tick != sim.tick:
                return fail('waiting cannot advance task time')
            sim.advance(tick)
            if sim.failed:return fail(sim.failed)
            k=e.get('kind')
            if k=='start':
                if sim.active or e.get('input_source')!='start_button':return fail('duplicate or false start')
                sim.active=True
            elif k in ('select','drag_start'):
                if e.get('input_source')!=source or not sim.active or sim.support is None or sim.sunk:return fail('wrong card input surface')
                card=e.get('card_id')
                if card not in sim.cards or card in sim.used:return fail('unavailable card')
                if k=='drag_start':
                    if mode!='full' or hold is not None:return fail('invalid card hold')
                    hold=card
                else:
                    if mode!='simplified':return fail('selection requires simplified input')
                    selected=card
            elif k=='cancel':
                if e.get('input_source')!=source:return fail('wrong cancellation surface')
                hold=selected=None
            elif k=='shot':
                if e.get('input_source')!=source:return fail('wrong stroke input')
                card=hold if mode=='full' else selected
                if card is None or e.get('card_id')!=card:return fail('stroke has no selected card')
                sim.shot(card,e['point']);hold=selected=None
            elif k=='seal':
                if e.get('input_source')!='certify_button':return fail('wrong certificate')
                sealed=True
            else:return fail('unknown input')
        if not sealed:return fail('missing certificate')
        final=payload.get('final_state')
        if not isinstance(final,dict):return fail('missing final state')
        snap=sim.snapshot()
        for key in ('tick','active','failed','sunk','support','used'):
            if final.get(key)!=snap[key]:return fail('false final '+key)
        for key in ('p','v'):
            vals=final.get(key)
            if not isinstance(vals,list) or len(vals)!=3 or any(abs(number(a)-b)>.002 for a,b in zip(vals,snap[key])):
                return fail('false final '+key)
        passed=sim.sunk and not sim.failed and payload.get('completed') is True and hold is None
        if passed:
            previous_failure = _episode_failure(ground_truth, public_state)
            if previous_failure:
                return fail(previous_failure)
        return dict(graded=True,passed=bool(passed),score=100 if passed else 0,
                    feedback=f'Projectile replay: {len(sim.used)}/{len(sim.cards)} cards; '+('ball sunk' if passed else 'incomplete course'))
    except (KeyError,TypeError,ValueError,OverflowError) as exc:return fail('invalid transcript: '+str(exc))
