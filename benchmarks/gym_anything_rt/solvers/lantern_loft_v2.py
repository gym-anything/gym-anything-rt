"""Privileged feedback oracle; every UI action goes through the supplied transport.

``read`` is read-only privileged planning, explicitly disclosed in evidence.
``send`` takes the frozen model HTTP mouse/keyboard schema. A Playwright adapter
is useful for implementation tests but cannot establish native API parity.
"""
from __future__ import annotations

import time

import copy
import hashlib
import itertools
import json
import math
import random
from unittest.mock import patch

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.lantern_loft_v2 import gust, clamp


def visible_rules(world):
    """Rule knowledge and drawn geometry only, without seeded motion state.

    This is an ideal perceptual-feature oracle, not a screenshot parser. Its
    measurement adapter must disclose that distinction. The allowlist keeps
    initial velocities, random keys and hidden future trajectories out of the
    predictor, even when a diagnostic starts from an authoritative instance.
    """
    keys = ('revision', 'parameters', 'body_half_width', 'body_half_depth',
            'neck_end', 'radius', 'rail_limit', 'motor_force', 'spring', 'damping',
            'deck_speed', 'walk_acceleration', 'walk_damping', 'walk_speed',
            'tick_ms', 'max_ms')
    rules = {key: copy.deepcopy(world[key]) for key in keys}
    rules['decks'] = [{key: d[key] for key in
                      ('id', 'name', 'moving', 'in_x', 'out_x', 'in_height', 'out_height', 'y')}
                     for d in world['decks']]
    return rules


def _linear_fit(rows, values):
    """Small least-squares system; unconstrained coefficients remain unknown."""
    n = len(rows[0])
    matrix = [[sum(r[i]*r[j] for r in rows) for j in range(n)] +
              [sum(r[i]*v for r, v in zip(rows, values))] for i in range(n)]
    pivot_cols = []
    for col in range(n):
        k = len(pivot_cols)
        pivot = max(range(k, n), key=lambda i: abs(matrix[i][col]), default=k)
        if abs(matrix[pivot][col]) < 1e-12:
            continue
        matrix[k], matrix[pivot] = matrix[pivot], matrix[k]
        scale = matrix[k][col]
        matrix[k] = [v/scale for v in matrix[k]]
        for i in range(n):
            if i != k:
                scale = matrix[i][col]
                matrix[i] = [a-scale*b for a, b in zip(matrix[i], matrix[k])]
        pivot_cols.append(col)
    # A pivot coupled to a free variable is not an identified coefficient.
    free = set(range(n))-set(pivot_cols)
    return {col: matrix[i][-1] for i, col in enumerate(pivot_cols)
            if all(abs(matrix[i][j]) < 1e-8 for j in free)}


class VisibleWind:
    """Conditional wind model fitted exclusively to visible flag/line samples.

    Smoothstep knot values that are not identified by the window are independent
    uniform draws, using a planning RNG unrelated to the environment seed. All
    competing actions share each draw. No call to the instance's gust() occurs.
    """
    def __init__(self, rules, frames, sample=0, bounded_fit=False):
        self.span = rules['parameters']['gust_span_ms']
        self.force = rules['parameters']['gust_force']
        self.sample = sample
        times = [ms for f in frames for ms in (f['ms'], f['ms']+1200)]
        indices = sorted({i for ms in times for i in
                          (math.floor(ms/self.span), math.floor(ms/self.span)+1)})
        rows = []
        for ms in times:
            row = [0.0]*len(indices)
            i = math.floor(ms/self.span)
            q = ms/self.span-i
            blend = q*q*(3-2*q)
            row[indices.index(i)] = 1-blend
            row[indices.index(i+1)] = blend
            rows.append(row)
        self.knots = {}
        for deck in range(len(rules['decks'])):
            values = [v for f in frames for v in
                      (f['flags'][deck], f['forecast_1200ms'][deck])]
            self.knots[deck] = {indices[col]: value for col, value in _linear_fit(rows, values).items()}
            if bounded_fit:
                self.knots[deck] = {i: clamp(v, -self.force, self.force)
                                    for i, v in self.knots[deck].items()}

    def __call__(self, deck, ms, _world):
        deck_index = int(deck['id'].split('-')[1])
        if not deck['moving']:
            return 0.0
        def knot(i):
            known = self.knots[deck_index].get(i)
            if known is not None:
                return known
            # Stateless common random numbers allow counterfactual order changes.
            key = f'visible-window-independent-wind|{self.sample}|{deck_index}|{i}'
            value = random.Random(hashlib.sha256(key.encode()).digest()).uniform(-self.force, self.force)
            self.knots[deck_index][i] = value
            return value
        i = math.floor(ms/self.span)
        q = ms/self.span-i
        blend = q*q*(3-2*q)
        return knot(i)*(1-blend)+knot(i+1)*blend


def _held_at(history, ms):
    own = next((h for h in reversed(history) if h['ms'] <= ms), None)
    if own is None:
        raise ValueError('missing prior input state')
    return own


def reconstruct_visible(rules, frames, history, wind, *, sampled_window=False):
    """Infer velocity from displacement over the bounded recent window.

    Frames contain drawn positions and courier (x, y, height), not simulation
    velocities or a crossing object. Crossing progress is recovered from y.
    Bisection inverts the known 20-ms acceleration/drag response, including rail
    and parapet contacts. The agent's own held inputs supply motor/walk forces.
    """
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders import lantern_loft_v2 as physics
    times = [f['ms'] for f in frames]
    if sampled_window:
        # Native live requests each deliver one frame. A recent sequence of
        # those requests can have fewer than four samples and uneven spacing.
        # Keep the same 240-ms information boundary; do not invent missing
        # pictures or interpolate observations from a private trajectory.
        if (not 2 <= len(times) <= 4 or times != sorted(set(times))
                or not 0 < times[-1]-times[0] <= 240
                or any(not isinstance(ms, int) or ms < 0 or ms % 20 for ms in times)):
            raise ValueError('two to four actual samples within 240 ms are required')
    else:
        if len(times) != 4 or times[-1]-times[0] != 240:
            raise ValueError('exactly four chronological frames over 240 ms are required')
        if times != list(range(times[0], times[-1]+1, 80)):
            raise ValueError('nonchronological visible window')
    allowed = {'ms', 'positions', 'courier', 'deck', 'flags', 'forecast_1200ms'}
    if any(set(f) != allowed for f in frames):
        raise ValueError('nonvisual state in measurement packet')
    if any(set(h) != {'ms', 'commands', 'walk', 'cross'} for h in history):
        raise ValueError('history must contain only the agent\'s own control states')
    if any(h['ms'] > frames[-1]['ms'] for h in history):
        raise ValueError('executed input history cannot contain future actions')
    if any('gust_seed' in d or 'initial_v' in d or 'initial_x' in d for d in rules['decks']):
        raise ValueError('private motion state in rule model')
    first, last = frames[0], frames[-1]
    # Dummy zero initial values are only constructor placeholders. The actual
    # recent positions/estimated velocities below replace them before planning.
    world = copy.deepcopy(rules)
    for d in world['decks']:
        d.update(initial_x=0, initial_v=0, gust_seed=0)
    sim = physics.LoftPhysics(world)
    sim.start()
    sim.ms = last['ms']
    sim.deck = last['deck']
    sim.positions = list(last['positions'])
    sim.commands = list(_held_at(history, sim.ms)['commands'])
    sim.walk = set(_held_at(history, sim.ms)['walk'])
    sim.x = last['courier']['x']
    sim.local_x = sim.x-sim.positions[sim.deck]
    y = last['courier']['y']-world['decks'][sim.deck]['y']
    if y > 1e-7:
        sim.crossing = dict(start_ms=int(round(sim.ms-y/130*world['parameters']['crossing_ms'])),
                            port_x=world['decks'][sim.deck]['out_x'], height=last['courier']['height'])

    def infer(integrate, target, bound):
        lo, hi = -bound, bound
        for _ in range(48):
            mid = (lo+hi)/2
            end, _ = integrate(mid)
            if end < target:
                lo = mid
            else:
                hi = mid
        return (lo+hi)/2

    # Each inverse fit revisits the same known inputs and visible wind at many
    # candidate velocities. Compute those terms once per observed tick; only
    # candidate position and velocity vary. No extra observation is introduced.
    observed_ticks = list(range(first['ms']+20, last['ms']+1, 20))
    inputs_by_tick = {ms: _held_at(history, ms-20) for ms in observed_ticks}
    crossed_ticks = {h['ms']+20 for h in history if h['cross']}
    sim.velocities = []
    deck_paths = []
    for i, d in enumerate(world['decks']):
        if not d['moving']:
            sim.velocities.append(0.0)
            deck_paths.append({ms: (first['positions'][i], 0.0)
                               for ms in range(first['ms'], last['ms']+1, 20)})
            continue
        forcing = []
        for ms in observed_ticks:
            own = inputs_by_tick[ms]['commands']
            motor = own[i]-world['parameters']['coupling']*(own[i-1]+own[i+1])
            forcing.append((ms, world['motor_force']*motor+wind(d, ms, world)))
        def deck_motion(v, trace=None):
            x = first['positions'][i]
            if trace is not None:
                trace[first['ms']] = (x, v)
            for ms, force in forcing:
                a = force-world['spring']*x-world['damping']*v
                v = clamp(v+a*.02, -world['deck_speed'], world['deck_speed'])
                x = clamp(x+v*.02, -world['rail_limit'], world['rail_limit'])
                if abs(x) == world['rail_limit']:
                    v = 0.0
                if trace is not None:
                    trace[ms] = (x, v)
            return x, v
        initial_v = (0.0 if abs(first['positions'][i]) == world['rail_limit'] else
                     infer(deck_motion, last['positions'][i], world['deck_speed']))
        trace = {}
        final_v = deck_motion(initial_v, trace)[1]
        def fit_error(v):
            path = {}
            deck_motion(v, path)
            return sum((path[f['ms']][0]-f['positions'][i])**2 for f in frames)
        if fit_error(initial_v) > 1e-12:
            # A rail hit followed by reversal makes endpoint displacement
            # nonmonotone in initial velocity. Fit all four observed positions
            # instead of choosing the wrong endpoint root across that contact.
            bound = world['deck_speed']
            grid = list(range(-int(bound), int(bound)+1, 5))
            center = min(grid, key=fit_error)
            lo, hi = max(-bound, center-5), min(bound, center+5)
            for _ in range(64):
                a, b = lo+(hi-lo)/3, hi-(hi-lo)/3
                if fit_error(a) < fit_error(b):
                    hi = b
                else:
                    lo = a
            initial_v = (lo+hi)/2
            trace = {}
            final_v = deck_motion(initial_v, trace)[1]
        # At the visible end stop the physics resets velocity exactly. A
        # numerical root infinitesimally short of that stop must not preserve
        # a spurious velocity from the unconstrained side of the contact.
        if abs(last['positions'][i]) == world['rail_limit']:
            final_v = 0.0
            trace[last['ms']] = (last['positions'][i], final_v)
        sim.velocities.append(final_v)
        deck_paths.append(trace)

    first_crossing = first['courier']['y'] > world['decks'][first['deck']]['y']+1e-7
    def courier_motion(v):
        deck = first['deck']
        x = first['courier']['x']
        local_x = x-first['positions'][deck]
        crossing_start = (first['ms']-(first['courier']['y']-world['decks'][deck]['y'])/130*
                          world['parameters']['crossing_ms']) if first_crossing else None
        for ms in observed_ticks:
            # CROSS is an own input, so a start inside the recent window can be
            # reconstructed without a remembered private crossing object.
            if crossing_start is None and ms in crossed_ticks:
                ports = [world['decks'][deck]['out_x']]
                if world['parameters']['false_ports']:
                    ports.append(world['decks'][deck]['in_x'])
                if any(abs(local_x-p) <= world['parameters']['port_width']/2-world['radius'] for p in ports):
                    crossing_start = ms-20
                    v += deck_paths[deck][ms-20][1]
            walk = inputs_by_tick[ms]['walk']
            thrust = int(1 in walk)-int(-1 in walk)
            v = clamp(v+(thrust*world['walk_acceleration']-world['walk_damping']*v)*.02,
                      -world['walk_speed'], world['walk_speed'])
            if crossing_start is None:
                local_x = clamp(local_x+v*.02, -world['body_half_width']+world['radius'], world['body_half_width']-world['radius'])
                if abs(local_x) == world['body_half_width']-world['radius']:
                    v = 0.0
                x = deck_paths[deck][ms][0]+local_x
            else:
                x += v*.02
                if ms-crossing_start >= world['parameters']['crossing_ms']-1e-6:
                    deck += 1
                    local_x = x-deck_paths[deck][ms][0]
                    v -= deck_paths[deck][ms][1]
                    crossing_start = None
        return x, v
    initial_v = infer(courier_motion, sim.x, world['walk_speed']+world['deck_speed'])
    sim.vx = courier_motion(initial_v)[1]
    return sim


def apply_controls(sim, action):
    for i in range(1, len(sim.positions)-1):
        sim.set_motor(i, action['commands'][i])
    for direction in (-1, 1):
        held = direction in action['walk']
        if (direction in sim.walk) != held:
            sim.set_walk(direction, held)
    if action.get('cross'):
        sim.cross()


def candidate_controls(sim):
    """All physically distinct detent/steering batches during a crossing.

    Holding both directions is equivalent to neutral. CROSS has no effect
    during a committed crossing; END is terminal failure. Both interfaces can
    express these batches, releasing simplified WALK before clicking winches.
    """
    for motors in itertools.product((-1, 0, 1), repeat=len(sim.positions)-2):
        for walk in ([-1], [], [1]):
            yield dict(commands=[0, *motors, 0], walk=walk, cross=False)


def feedback_continuation(sim, wind, interval_ms=80, limit_ms=60000):
    start = sim.ms
    while not (sim.failed or sim.solved) and sim.ms-start < limit_ms:
        snap = sim.snapshot()
        snap['visible_gusts'] = [wind(d, sim.ms, sim.world) for d in sim.world['decks']]
        apply_controls(sim, policy(sim.world, snap))
        sim.advance(sim.ms+interval_ms)
    return dict(passed=bool(sim.solved and not sim.failed), task_ms=sim.ms,
                continuation_ms=sim.ms-start, failure=sim.failed or ('' if sim.solved else 'continuation limit'))


def select_delayed(rules, frames, history, delta_ms=240, hold_ms=80, samples=4,
                   measurement_precision=None, continuation_interval_ms=80):
    """Commit a delayed choice from allowed observations, before real advance.

    Empirical action values are success frequency, then mean successful
    task-active continuation time after delivery, under the declared
    feedback continuation. This is a finite conditional planning diagnostic;
    it does not assert exhaustive global optimality or native transport parity.
    ``hold_ms`` is an experimental first-action duration, never a game lockout.
    Use one tick and a one-tick continuation when testing unrestricted recovery.
    """
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders import lantern_loft_v2 as physics
    if (hold_ms < rules['tick_ms'] or hold_ms % rules['tick_ms']
            or continuation_interval_ms < rules['tick_ms']
            or continuation_interval_ms % rules['tick_ms']):
        raise ValueError('action/correction durations must be positive physics ticks')
    packet = dict(rules=rules, frames=frames, history=history, delta_ms=delta_ms,
                  first_action_ms=hold_ms, continuation_interval_ms=continuation_interval_ms)
    if measurement_precision:
        packet['measurement_precision'] = measurement_precision
    packet_hash = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()
    nominal_wind = VisibleWind(rules, frames)
    observed = reconstruct_visible(rules, frames, history, nominal_wind)
    if not observed.crossing:
        raise ValueError('delayed comparison requires an active crossing opportunity')
    candidates = list(candidate_controls(observed))
    outcomes = [[] for _ in candidates]
    predictions = []
    for sample in range(samples):
        measured = copy.deepcopy(frames)
        if measurement_precision:
            # Finite sensor-uncertainty sensitivity model, not an exact Bayesian
            # posterior or an image parser. Use independent draws within each
            # stated rounding bin and respect the physical rail/force bounds.
            rng = random.Random(f'visible-measurement-uncertainty|{sample}')
            px = measurement_precision['geometry_world_px']/2
            force = rules['parameters']['gust_force']*measurement_precision['flag_normalized']/2
            for f in measured:
                f['positions'] = [clamp(x+rng.uniform(-px, px), -rules['rail_limit'], rules['rail_limit'])
                                  if d['moving'] else x for d, x in zip(rules['decks'], f['positions'])]
                f['courier']['x'] += rng.uniform(-px, px)
                for key in ('flags', 'forecast_1200ms'):
                    f[key] = [clamp(v+rng.uniform(-force, force), -rules['parameters']['gust_force'], rules['parameters']['gust_force'])
                              if d['moving'] else 0.0 for d, v in zip(rules['decks'], f[key])]
        wind = VisibleWind(rules, measured, sample, bounded_fit=bool(measurement_precision))
        branch = reconstruct_visible(rules, measured, history, wind)
        with patch.object(physics, 'gust', wind):
            branch.advance(branch.ms+delta_ms)
            predictions.append(branch.snapshot())
            for i, candidate in enumerate(candidates):
                sim = copy.deepcopy(branch)
                delivered_at = sim.ms
                if not (sim.failed or sim.solved):
                    apply_controls(sim, candidate)
                    sim.advance(sim.ms+hold_ms)
                    hold_end = sim.snapshot()
                    result = feedback_continuation(sim, wind, interval_ms=continuation_interval_ms)
                else:
                    hold_end = sim.snapshot()
                    result = dict(passed=bool(sim.solved), task_ms=sim.ms, failure=sim.failed)
                result['continuation_ms'] = sim.ms-delivered_at
                result['failed_during_hold'] = bool(hold_end['failed'])
                result['hold_end_ms'] = hold_end['ms']
                outcomes[i].append(result)
    def value(results):
        times = [r['continuation_ms'] for r in results if r['passed']]
        return (len(times)/samples, -sum(times)/len(times) if times else -math.inf)
    values = [value(o) for o in outcomes]
    best = max(values)
    choices = [i for i, v in enumerate(values) if v == best]
    # Prefer fewer changed controls only after terminal/time equality.
    index = min(choices, key=lambda i: (sum(a != b for a, b in zip(candidates[i]['commands'], observed.commands))
                                       +int(set(candidates[i]['walk']) != observed.walk), i))
    return dict(action=copy.deepcopy(candidates[index]), chosen_index=index, input_sha256=packet_hash,
                selection_boundary='Only the rule allowlist, own inputs and four past visual measurements',
                delta_ms=delta_ms, hold_ms=hold_ms, samples=samples, future_instance_seed_access=False,
                continuation_interval_ms=continuation_interval_ms,
                optimal_continuation_certified=False,
                measurement_precision=measurement_precision,
                reconstructed=observed.snapshot(), predictions=predictions,
                candidates=[dict(action=a, value=dict(success_rate=v[0],
                                 mean_success_continuation_ms=-v[1] if math.isfinite(v[1]) else None), outcomes=o)
                            for a, v, o in zip(candidates, values, outcomes)])


def plan_visible_controls(rules, frames, history, pending=(), delta_ms=240,
                          duration_ms=480, interval_ms=80, *, sampled_window=False,
                          control_policy='feedback'):
    """Plan corrections before delivery, using only the bounded visual packet.

    Pending inputs are a previous, already committed plan, not observations of
    future physics. A new 480-ms plan overlaps the next 240-ms observation window
    and its 240-ms delay. Its 80-ms corrections are selected here; execution must
    never consult a later private snapshot to amend them. This nominal buffered
    schedule still needs exact native queue/capture validation. It does not claim
    to be a serialized model request, a screenshot parser, or an optimal policy.
    """
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders import lantern_loft_v2 as physics
    if control_policy not in ('feedback', 'support_midpoint'):
        raise ValueError('unknown bounded control policy')
    now = frames[-1]['ms']
    delay_grid = rules['tick_ms'] if sampled_window else interval_ms
    if (interval_ms != 80 or delta_ms <= 0 or delta_ms % delay_grid
            or duration_ms < delta_ms or duration_ms % interval_ms
            or delta_ms+duration_ms > 1200):
        raise ValueError('plan must fit the visible forecast and 80-ms control grid')
    allowed = {'ms', 'committed_at_ms', 'commands', 'walk', 'cross'}
    if any(set(row) != allowed or row['committed_at_ms'] > now
           or not now <= row['ms'] < now+delta_ms for row in pending):
        raise ValueError('pending controls must be previously committed own inputs')
    times = [row['ms'] for row in pending]
    pending_grid = rules['tick_ms'] if sampled_window else interval_ms
    if times != sorted(set(times)) or any((ms-now) % pending_grid for ms in times):
        raise ValueError('pending control times must be unique and chronological')
    packet = dict(rules=rules, frames=frames, history=history, pending=list(pending),
                  delta_ms=delta_ms, duration_ms=duration_ms, interval_ms=interval_ms,
                  **({'sampled_window': True} if sampled_window else {}),
                  **({'control_policy': control_policy} if control_policy != 'feedback' else {}))
    wind = VisibleWind(rules, frames, bounded_fit=sampled_window)
    identified = copy.deepcopy(wind.knots)
    sim = reconstruct_visible(rules, frames, history, wind, sampled_window=sampled_window)
    pending_by_time = {row['ms']: row for row in pending}
    delivery = now+delta_ms
    steps = []
    with patch.object(physics, 'gust', wind):
        for ms in range(now, delivery, pending_grid):
            if ms in pending_by_time:
                apply_controls(sim, pending_by_time[ms])
            sim.advance(ms+pending_grid)
        delivery_prediction = sim.snapshot()
        for ms in range(delivery, delivery+duration_ms, interval_ms):
            if sim.failed or sim.solved:
                break
            state = sim.snapshot()
            state['visible_gusts'] = [wind(d, ms, rules) for d in rules['decks']]
            target = (native_support_policy(rules, state) if control_policy == 'support_midpoint'
                      else policy(rules, state))
            steps.append(dict(ms=ms, committed_at_ms=now, **copy.deepcopy(target)))
            apply_controls(sim, target)
            sim.advance(ms+interval_ms)
    drawn_future_unidentified = {i: sorted(set(wind.knots[i])-set(identified[i]))
                                 for i in wind.knots if rules['decks'][i]['moving']}
    return dict(controller_revision=('visible-buffered-support-interval-v3'
                if control_policy == 'support_midpoint' else 'visible-buffered-v1'), observation_ms=now,
                delivery_ms=delivery, delta_ms=delta_ms, duration_ms=duration_ms,
                control_interval_ms=interval_ms, steps=steps,
                input_sha256=hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest(),
                selection_boundary='Rule allowlist, own executed/committed inputs, past visual measurements within 240 ms',
                observation_sample_times_ms=[f['ms'] for f in frames],
                future_instance_seed_access=False, native_schedule_verified=False,
                unidentified_wind_knots_used=drawn_future_unidentified,
                delivery_prediction=delivery_prediction, prediction_end=sim.snapshot())


def native_support_policy(world, state):
    """Choose a literal WALK detent over the whole 80-ms correction interval.

    The prediction uses only the allowed force/position/velocity reconstruction.
    Score left, neutral and right under 0/20/40-ms input-transition uncertainty,
    rather than alternating thrust from an instantaneous velocity error. Penalize
    low whole-sole clearance and track the joint-support midpoint/velocity.
    The six-pixel planning margin does not change a collision or verifier rule.
    No private future gust or actual simulation state is read here.
    """
    if 'visible_gusts' not in state:
        raise ValueError('native support policy requires the bounded wind prediction')
    target=policy(world,state)
    if not state['crossing']:
        return target
    d=state['deck']; radius=world['radius']; half=world['parameters']['port_width']/2
    def candidate(thrust, delay):
        x,v=state['x'],state['vx']
        positions=list(state['positions']); velocities=list(state['velocities'])
        minimum=float('inf')
        for offset in range(20,101,20):
            commands=state['commands'] if offset <= delay else target['commands']
            for i,deck in enumerate(world['decks']):
                if not deck['moving']:continue
                motor=commands[i]-world['parameters']['coupling']*(commands[i-1]+commands[i+1])
                force=world['motor_force']*motor+state['visible_gusts'][i]-world['spring']*positions[i]-world['damping']*velocities[i]
                velocities[i]=clamp(velocities[i]+force*.02,-world['deck_speed'],world['deck_speed'])
                positions[i]=clamp(positions[i]+velocities[i]*.02,-world['rail_limit'],world['rail_limit'])
                if abs(positions[i])==world['rail_limit']:velocities[i]=0.
            own=int(1 in state['walk'])-int(-1 in state['walk'])
            walk=own if offset <= delay else thrust
            v=clamp(v+(walk*world['walk_acceleration']-world['walk_damping']*v)*.02,-world['walk_speed'],world['walk_speed'])
            x+=v*.02
            y=130*(state['ms']+offset-state['crossing']['start_ms'])/world['parameters']['crossing_ms']
            source=positions[d]+state['crossing']['port_x']
            destination=positions[d+1]+world['decks'][d+1]['in_x']
            if y-radius<65:
                center=source if y+radius>40 else positions[d]
                width=half if y+radius>40 else world['body_half_width']
                minimum=min(minimum,width-radius-abs(x-center))
            if y+radius>65:
                center=destination if y-radius<90 else positions[d+1]
                width=half if y-radius<90 else world['body_half_width']
                minimum=min(minimum,width-radius-abs(x-center))
        if y-radius<90:
            desired=(source+destination)/2
            support_velocity=(velocities[d]+velocities[d+1])/2
        else:
            desired=destination;support_velocity=velocities[d+1]
        return (desired-x)**2+(.14*(support_velocity-v))**2+1000*max(0.,6.-minimum)**2
    costs={direction:max(candidate(direction,delay) for delay in (0,20,40)) for direction in (-1,0,1)}
    chosen=min(costs,key=lambda direction:(costs[direction],abs(direction)))
    target['walk']=[chosen] if chosen else []
    return target


def policy(world, s):
    """Position/velocity feedback, with no access to future motion or a route tape."""
    d = s['deck']
    decks = world['decks']
    last = len(decks)-1
    seam = decks[0]['out_x'] if d == 0 else decks[last]['in_x'] if d+1 == last else 0
    targets = [0.0]*len(decks)
    targets[d] = seam-decks[d]['out_x']
    targets[d+1] = seam-decks[d+1]['in_x']
    commands = [0]*len(decks)
    # Work the two lofts bordering this crossing. Future lofts keep drifting;
    # keeping every unused winch busy only delays the actual steering input.
    for i in (d, d+1):
        if not 0 < i < last:
            continue
        force = s['visible_gusts'][i] if 'visible_gusts' in s else gust(decks[i], s['ms'], world)
        desired = (20*(targets[i]-s['positions'][i])-7*s['velocities'][i]
                   +world['spring']*s['positions'][i]+world['damping']*s['velocities'][i]
                   -force)/world['motor_force']
        desired += world['parameters']['coupling']*(s['commands'][i-1]+s['commands'][i+1])
        commands[i] = -1 if desired < -.24 else 1 if desired > .24 else 0
    a = s['positions'][d]+decks[d]['out_x']
    b = s['positions'][d+1]+decks[d+1]['in_x']
    if s['crossing']:
        f=(s['ms']-s['crossing']['start_ms'])/world['parameters']['crossing_ms']
        blend=clamp((f-.25)/.5,0,1)
        target=a*(1-blend)+b*blend
        error=target-s['x']
        desired_velocity=error*5+s['velocities'][d]*(1-blend)+s['velocities'][d+1]*blend
    else:
        error=decks[d]['out_x']-s['local_x']
        desired_velocity=error*4
    steering=desired_velocity-s['vx']
    walk = [1] if steering > 40 else [-1] if steering < -40 else []
    cross = (not s['crossing'] and abs(error) < 12 and abs(s['vx']) < 24
             and abs(a-b) < 14 and abs(s['velocities'][d]) < 24 and abs(s['velocities'][d+1]) < 24)
    return dict(commands=commands, walk=walk, cross=cross)


def _rect(ui, selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def _center(rect):
    return [rect[0]+rect[2]/2, rect[1]+rect[3]/2]


def run(ui, truth, budget=500, interval=.04):
    world=truth['world']
    simple=(truth.get('control_condition') or {}).get('interaction')=='simplified'
    rects={i:_rect(ui,f'[data-lever="{i}"]') for i in range(1,len(world['decks'])-1)}
    if simple:
        motors={(i,v):_center(_rect(ui,f'[data-motor="{i}"][data-value="{v}"]')) for i in rects for v in (-1,0,1)}
        walk_points={v:_center(_rect(ui,f'[data-walk="{v}"]')) for v in (-1,1)}
        cross_point=_center(_rect(ui,'#loft-v2-cross'))
    click=lambda p:{'mouse':{'left_click':p}}
    ui.send([click(_center(_rect(ui,'#loft-v2-start')))])
    held=[]
    deadline=time.monotonic()+190
    calls=1
    while time.monotonic()<deadline and calls < budget:
        state=ui.read('lanternLoftV2Model.sim.snapshot()')
        if state['solved']:
            return dict(calls=calls, elapsed_task_ms=state['ms'])
        assert not state['failed'], state
        desired=policy(world,state)
        actions=[]
        # Simplified uses one pointer: release the walk hold before winch work.
        changes=[i for i in rects if desired['commands'][i] != state['commands'][i]]
        if simple and held and (changes or desired['walk'] != held or desired['cross']):
            actions.append({'mouse':{'buttons':{'left_up':True}}});held=[]
        if not simple:
            for v in held:
                if v not in desired['walk']:actions.append({'keyboard':{'keys_up':['Right' if v==1 else 'Left']}})
            for v in desired['walk']:
                if v not in held:actions.append({'keyboard':{'keys_down':['Right' if v==1 else 'Left']}})
            held=desired['walk']
        for i in changes:
            value=desired['commands'][i]
            if simple:
                actions.append(click(motors[(i,value)]))
            else:
                x,y,width,height=rects[i]
                start=[x+(80+state['commands'][i]*48)/160*width,y+height/2]
                end=[x+(80+value*48)/160*width,y+height/2]
                actions += [{'mouse':{'move':start,'buttons':{'left_down':True}}},
                            {'mouse':{'move':end}}, {'mouse':{'buttons':{'left_up':True}}}]
        if desired['cross']:
            actions.append(click(cross_point) if simple else {'keyboard':{'keys':['Space']}})
        if simple and desired['walk'] and not held:
            actions.append({'mouse':{'move':walk_points[desired['walk'][0]],'buttons':{'left_down':True}}})
            held=desired['walk']
        if actions:
            ui.send(actions);calls+=1
        ui.wait(interval)
    raise AssertionError(f'Lantern Loft oracle exceeded {budget} calls or 190 seconds')


def solve(page, state_dir, out_dir, mechanic):
    """Compatibility with the existing headless solver machinery only."""
    import json
    from pathlib import Path
    if mechanic!='lantern_loft_v2':raise ValueError(mechanic)
    ui=HeadlessImplementationUI(page)
    outcome=run(ui,json.loads((Path(state_dir)/'ground_truth.json').read_text()))
    page.wait_for_timeout(250)
    page.screenshot(path=str(Path(out_dir)/'lantern_loft_v2-pass.png'))
    return outcome


class HeadlessImplementationUI:
    """Literal event-wiring adapter. This is NOT the downstream HTTP transport."""
    def __init__(self, page):
        self.page, self.calls, self.actions, self.trace = page, 0, 0, []

    def read(self, expression):
        return self.page.evaluate(expression)

    def wait(self, seconds):
        self.page.wait_for_timeout(seconds*1000)

    def send(self, actions):
        from gym_anything_rt.agents.codex_actions import native_action
        self.calls += 1
        self.actions += len(actions)
        self.trace.append(dict(wall_monotonic=time.monotonic(), task_ms=self.read('lanternLoftV2Model.sim.ms'), actions=actions))
        for action in actions:
            # Schema validation is useful, but does not establish native parity.
            native_action(action, (1, 1))
            mouse = action.get('mouse', {})
            if 'move' in mouse:
                self.page.mouse.move(*mouse['move'])
            for field, enabled in mouse.get('buttons', {}).items():
                button, transition = field.rsplit('_', 1)
                if enabled:
                    getattr(self.page.mouse, transition)(button=button)
            if 'left_click' in mouse:
                self.page.mouse.click(*mouse['left_click'])
            for field, method in [('keys_down', 'down'), ('keys_up', 'up'), ('keys', 'press')]:
                for key in action.get('keyboard', {}).get(field, []):
                    key = {'Right': 'ArrowRight', 'Left': 'ArrowLeft'}.get(key, key)
                    getattr(self.page.keyboard, method)(key)


# Keep the original reader as historical evidence. The corrected reader lives
# in this task's allowed solver file and is selected explicitly by the new
# native oracle entry point; previous staged drivers remain unchanged.
import io
from benchmarks.gym_anything_rt.environments.lantern_loft_v2_env.oracle.pixels import MotionPixels as _LegacyMotionPixels


class OcclusionMotionPixels(_LegacyMotionPixels):
    """Measure deck edges after masking geometry drawn in front of them.

    Foreground positions come from the same delivered picture. Hidden edges
    supply no measurements; their pixels cannot be assigned to a rear deck.
    The geometry allowlist and original JPEG are the only inputs.
    """
    def _patch_polygons(self, deck, x):
        y = deck['y']
        left = deck['in_height'] if deck['in_x'] < 0 else deck['out_height']
        right = deck['out_height'] if deck['in_x'] < 0 else deck['in_height']
        def patch(x0, x1, y0, y1, z0, z1):
            points = [self.project(x0, y0, z0), self.project(x1, y0, z1),
                      self.project(x1, y1, z1), self.project(x0, y1, z0)]
            return [points, [points[0], points[1],
                    (points[1][0], points[1][1]+9*self.sy),
                    (points[0][0], points[0][1]+9*self.sy)]]
        polygons = []
        for values in [(x-140,x-16,y-40,y+40,left,left),
                       (x-16,x+16,y-40,y+40,left,right),
                       (x+16,x+140,y-40,y+40,right,right)]:
            polygons.extend(patch(*values))
        half = self.rules['parameters']['port_width']/2
        i = int(deck['id'].split('-')[1])
        if i > 0:
            polygons.extend(patch(x+deck['in_x']-half,x+deck['in_x']+half,
                                 y-65,y-40,deck['in_height'],deck['in_height']))
        if i < len(self.rules['decks'])-1:
            polygons.extend(patch(x+deck['out_x']-half,x+deck['out_x']+half,
                                 y+40,y+65,deck['out_height'],deck['out_height']))
            if self.rules['parameters']['false_ports'] and deck['in_height'] != deck['out_height']:
                polygons.extend(patch(x+deck['in_x']-half,x+deck['in_x']+half,
                                     y+40,y+65,deck['in_height'],deck['in_height']))
        return polygons

    def extract(self, original_bytes):
        from PIL import Image
        np = self.np
        with Image.open(io.BytesIO(original_bytes)) as decoded:
            image = np.asarray(decoded.convert('RGB'))
        height, width = image.shape[:2]
        def sample(x, y):
            return image[np.clip(np.rint(y).astype(int),0,height-1),
                         np.clip(np.rint(x).astype(int),0,width-1)]
        def hidden(x, y, polygons):
            mask = np.zeros(np.broadcast_shapes(x.shape,y.shape), dtype=bool)
            bounds = float(np.min(x)),float(np.max(x)),float(np.min(y)),float(np.max(y))
            for polygon in polygons:
                # Most foreground decks are below this parapet's sample band.
                # Reject disjoint boxes before testing every candidate point.
                if (max(p[0] for p in polygon) < bounds[0]
                        or min(p[0] for p in polygon) > bounds[1]
                        or max(p[1] for p in polygon) < bounds[2]
                        or min(p[1] for p in polygon) > bounds[3]):
                    continue
                cross = [(x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])
                         for a,b in zip(polygon,polygon[1:]+polygon[:1])]
                mask |= np.all(np.asarray(cross)>=0,axis=0) | np.all(np.asarray(cross)<=0,axis=0)
            return mask
        positions, qualities = [0.0]*len(self.rules['decks']), []
        foreground = []
        offsets = np.arange(-self.rules['rail_limit'],self.rules['rail_limit']+.25,.25)
        along = np.linspace(-32,32,17)
        dark = np.array([91,70,101])
        for deck in self.rules['decks']:
            if not deck['moving']:
                qualities.append(None)
                foreground.extend(self._patch_polygons(deck,0))
                continue
            zleft = deck['in_height'] if deck['in_x'] < 0 else deck['out_height']
            zright = deck['out_height'] if deck['in_x'] < 0 else deck['in_height']
            numerator, denominator = np.zeros(len(offsets)), np.zeros(len(offsets))
            for sign,z,color in [(-1,zleft,[219,184,151]),(1,zright,[201,166,142])]:
                px,py = self.project(offsets[:,None]+sign*140,deck['y']+along[None,:],z)
                stroke = sample(px,py)
                inside = sample(px-sign*6*self.sx*.88,py)
                outside = sample(px+sign*6*self.sx*.88,py)
                line_fit = np.exp(-np.sum((stroke-dark)**2,axis=-1)/35**2)
                inner_fit = np.exp(-np.sum((inside-np.array(color))**2,axis=-1)/35**2)
                outer_fit = np.exp(-np.sum((outside-np.array(color))**2,axis=-1)/35**2)
                visible = ~(hidden(px,py,foreground) |
                            hidden(px-sign*6*self.sx*.88,py,foreground) |
                            hidden(px+sign*6*self.sx*.88,py,foreground))
                numerator += np.sum((line_fit+.8*inner_fit-.6*outer_fit)*visible,axis=1)
                denominator += np.sum(visible,axis=1)
            score = np.where(denominator>=8,numerator/np.maximum(1,denominator),-np.inf)
            best = int(np.argmax(score))
            if not np.isfinite(score[best]):
                raise ValueError('No visible parapet measurements for '+deck['name'])
            near = np.flatnonzero((score>=score[best]-.0125)&(np.abs(offsets-offsets[best])<3))
            estimate = float(np.mean(offsets[near]))
            i = int(deck['id'].split('-')[1])
            positions[i] = estimate
            qualities.append(dict(score=float(score[best]),plateau_world_px=float(np.ptp(offsets[near])),
                                  unoccluded_samples=int(denominator[best]),occlusion_considered=True))
            foreground.extend(self._patch_polygons(deck,estimate))

        # Preserve the legacy flag and courier measurements, without a second
        # JPEG decode or an unused unmasked search of the platform edges.
        flags, forecasts = [0.0]*len(positions), [0.0]*len(positions)
        for i, deck in enumerate(self.rules['decks']):
            if not deck['moving']:
                continue
            py = 470-deck['y']*.43
            baseline = self.left+112*self.sx
            x0 = max(0,int(self.left+66*self.sx))
            x1 = min(width,int(self.left+158*self.sx)+1)
            cy = self.top+(py-18)*self.sy
            y0,y1 = max(0,int(cy)),min(height,int(cy)+2)
            colors = image[y0:y1,x0:x1].astype(np.int16)
            green = ((np.min(colors,axis=-1)>90) & (np.max(colors,axis=-1)>140) &
                     (colors[...,1]>colors[...,0]-10))
            columns = np.flatnonzero(np.any(green,axis=0))+x0
            if len(columns):
                lo,hi = float(columns.min()),float(columns.max())
                tip = lo if baseline-lo>hi-baseline else hi
                flags[i] = float(np.clip((tip-baseline)/(40*self.sx),-1,1))*self.rules['parameters']['gust_force']
            cy = self.top+(py-34)*self.sy
            y0,y1 = max(0,int(cy-1.5*self.sy)),min(height,int(cy+1.5*self.sy)+1)
            colors = image[y0:y1,x0:x1]
            pale = (np.min(colors,axis=-1)>90) & (np.max(colors,axis=-1)>140)
            columns = np.flatnonzero(np.any(pale,axis=0))+x0
            if len(columns):
                lo,hi = float(columns.min()),float(columns.max())
                tip = lo if baseline-lo>hi-baseline else hi
                forecasts[i] = float(np.clip((tip-baseline)/(40*self.sx),-1,1))*self.rules['parameters']['gust_force']
        x0,x1 = max(0,int(self.left)),min(width,int(self.left+900*self.sx))
        y0,y1 = max(0,int(self.top)),min(height,int(self.top+540*self.sy))
        coat = image[y0:y1,x0:x1].astype(np.int16)
        delta = coat-np.array([86,139,144],dtype=np.int16)
        yy,xx = np.nonzero(np.sum(delta*delta,axis=-1)<19**2)
        courier = (None if len(xx)<20 else
                   dict(canvas_x=float((np.median(xx)+x0-self.left)/self.sx+.5),
                        canvas_y=float((np.median(yy)+y0-self.top)/self.sy+15),coat_pixels=len(xx)))
        return dict(positions=positions,flags=flags,forecast_1200ms=forecasts,
                    courier_projection=courier,deck_matches=qualities,
                    original_resolution=[width,height],image_resized=False,image_reencoded=False)


def run_native_buffered(ui, rules, interaction, **kwargs):
    """Use corrected visual measurements through the unchanged native adapter.

    This changes task-specific read-only oracle planning only. The supplied
    HTTP transport, action encoding, scheduler, clocks and captures are kept.
    A new staged driver must opt into this entry point and bind its hashes.
    """
    from benchmarks.gym_anything_rt.environments.lantern_loft_v2_env.oracle import native as adapter
    with patch.object(adapter, "MotionPixels", OcclusionMotionPixels):
        return adapter.run_buffered(ui, rules, interaction, **kwargs)
