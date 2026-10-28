"""Privileged oracle planning; every real input goes through the supplied UI API.

`ui.send` uses the frozen downstream HTTP /act contract in native validation.
An explicitly labelled Playwright adapter is allowed only for implementation
checks. It establishes no native action-space evidence. No DOM mutations,
focus calls, internal input calls, or success setters are used by this solver.
"""
from __future__ import annotations

import copy
import math
import time
import heapq
import itertools
from collections import deque
from functools import lru_cache

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.lampwrights_program_v2 import Physics, DIRS, roof_pose, lift_pair_at, lift_goal


def trajectory_pose(span_ms, start, goal, next_goal, remaining_ms, observed_ms, query_ms):
    """Forecast from visible trajectory-board values; no seed or hidden state.

    The board shows exact centimetre endpoints and millisecond ramp remainder.
    The displayed easing law supplies position and velocity through the current
    and following ramp. This helper intentionally accepts only those two ramps.
    In visible-lift-v1, world_from_visible_board also uses the printed recurrence
    and can predict beyond that helper horizon without another observation.
    """
    if not 0 < remaining_ms <= span_ms:
        raise ValueError("invalid displayed ramp remainder")
    dt = query_ms-observed_ms
    if not 0 <= dt <= remaining_ms+span_ms:
        raise ValueError("query outside the displayed trajectory horizon")
    if dt <= remaining_ms:
        a, b, f = start, goal, 1-(remaining_ms-dt)/span_ms
    else:
        a, b, f = goal, next_goal, (dt-remaining_ms)/span_ms
    s = f**3*(10-15*f+6*f*f)
    derivative = 30*f*f*(1-f)**2/(span_ms/1000)
    return {"position": [a[i]+(b[i]-a[i])*s for i in range(3)],
            "velocity": [(b[i]-a[i])*derivative for i in range(3)]}


def world_from_visible_board(rows, physics, observed_ms, start_heading=None):
    """Reconstruct the whole trajectory from current printed board values.

    rows contain only BAY, BASE Z, FROM/TO xyz and TO IN. No original seed,
    initial lift_pair, old frame, motion_seed, or page state is accepted.
    Inverting the displayed recurrence recovers the same initialization at t=0.
    Thus this world supports exact replay of I_t and arbitrary continuation,
    rather than just the next safe landing or a greedy route.
    """
    p = copy.deepcopy(physics)
    if p.get('motion_revision') != 'visible-lift-v1':
        raise ValueError('visible recurrence required')
    roofs = []
    for row in rows:
        remainder = row['remaining_ms']
        if not 0 < remainder <= p['span_ms']:
            raise ValueError('invalid visible ramp remainder')
        phase = (p['span_ms']-remainder-observed_ms) % p['span_ms']
        n = (observed_ms+phase)//p['span_ms']
        low = row['base_z']-p['lift']
        pair = [round((row[key][2]-low)/p['motion_quantum']) for key in ('start','goal')]
        if not all(0 <= k < p['lift_modulus'] for k in pair) or pair == [0, 0]:
            raise ValueError('invalid visible lift pair')
        initial = lift_pair_at(*pair,-n,p['lift_modulus'],p['lift_coefficient'],p['lift_previous_coefficient'])
        roof = dict(id=row['id'], cell=list(row['cell']),base_z=row['base_z'],
                    half=row['half'],phase_ms=phase,lift_pair=list(initial),lamp=row['lamp'])
        if any(abs(a-b)>1e-8 for key,offset in (('start',0),('goal',1))
               for a,b in zip(row[key], lift_goal(p,roof,lift_pair_at(*initial,n+offset,
                    p['lift_modulus'],p['lift_coefficient'],p['lift_previous_coefficient'])))):
            raise ValueError('inconsistent visible controller endpoints')
        roofs.append(roof)
    if start_heading is None:
        # The first two numbered bays are the visible starting spine. Their
        # direction is also the robot's initial heading, in every generated map.
        by_id={r['id']:r for r in roofs}
        start_heading=DIRS.index(tuple(b-a for a,b in zip(by_id['roof-0']['cell'],by_id['roof-1']['cell'])))
    return dict(roofs=roofs,start_roof='roof-0',start_heading=start_heading,
                physics=p,routine_slots=4)


def replay_visible_inputs(rows, physics, observed_ms, events):
    """Recover physical state from a current board and actual own input times.

    This consumes the public board fields, not a seed or a private snapshot.
    Events are the player's complete input record, including preparation edits.
    Actual browser dispatch times are required; requested HTTP timestamps or
    X-server acknowledgements alone do not specify the handler's task tick.
    It supports busy, flight, centering, LIGHT and pending routine states.
    """
    world = world_from_visible_board(rows, physics, observed_ms)
    ph = Physics(world)
    routines = {name: [None] * world['routine_slots'] for name in ('A', 'B')}
    started = False
    previous = 0
    for event in events:
        ms = event['t_ms']
        if (type(ms) is not int or ms % physics['tick_ms'] or
                not previous <= ms <= observed_ms):
            raise ValueError('own input times must be ordered actual task ticks')
        if not started and ms != 0:
            raise ValueError('preparation cannot consume active task time')
        ph.advance(ms)
        kind = event['kind']
        if kind == 'start':
            if started:
                raise ValueError('repeated start')
            started = True
        elif kind == 'edit':
            panel, index, token = event['panel'], event['index'], event['token']
            if (panel not in routines or type(index) is not int or
                    not 0 <= index < world['routine_slots'] or token not in 'FJDLRG'):
                raise ValueError('invalid literal routine edit')
            routines[panel][index] = token
        elif kind == 'dispatch':
            if not started:
                raise ValueError('dispatch before start')
            token = event['token']
            commands = [v for v in routines[token] if v] if token in routines else [token]
            ph.dispatch(commands)
        elif kind == 'seal':
            raise ValueError('sealed histories have no active control opportunity')
        else:
            raise ValueError('unknown own input event')
        previous = ms
    if not started:
        raise ValueError('an active board requires BEGIN SHIFT')
    ph.advance(observed_ms)
    return ph, routines


def physics_from_visible_receipt(rows, physics, observed_ms, receipt, lit):
    """Recover current actor state from the board and visible last dispatch.

    No accepted-event history, seed, private snapshot or HTTP-to-browser timing
    assumption is used. A dispatch starts only from a settled, centred robot;
    its at-most-four literal commands and starting roof/heading/tick reproduce
    flight, centering, pending LIGHT and the immutable active queue. Earlier
    lights are represented by the current visible lamp marks. Historical steps
    are not reconstructed: they do not affect future physical transitions and
    remain automatically recorded by the webpage for grading.
    """
    tick = physics['tick_ms']
    if type(observed_ms) is not int or observed_ms % tick or not 0 <= observed_ms <= physics['max_task_ms']:
        raise ValueError('observation requires the printed task tick')
    world = world_from_visible_board(rows, physics, observed_ms)
    ph = Physics(world)
    targets = {r['id'] for r in world['roofs'] if r['lamp']}
    if not isinstance(lit, (list, tuple, set)) or not set(lit) <= targets:
        raise ValueError('invalid visible lamp marks')
    if receipt is None:
        if lit:
            raise ValueError('a lit lamp requires a visible accepted dispatch')
        ph.advance(observed_ms)
        return ph
    ms, source, heading, commands = (receipt[k] for k in ('t_ms', 'source', 'heading', 'commands'))
    if (type(ms) is not int or ms % tick or not 0 <= ms <= observed_ms or
            source not in ph.roofs or type(heading) is not int or not 0 <= heading < 4 or
            not isinstance(commands, list) or not 1 <= len(commands) <= world['routine_slots'] or
            any(token not in ('F','J','D','L','R','G') for token in commands)):
        raise ValueError('invalid printed dispatch receipt')
    ph.ms, ph.roof, ph.heading = ms, source, heading
    ph.position = roof_pose(world, ph.roofs[source], ms)['position']
    ph.lit = set(lit)
    ph.dispatch(commands)
    ph.advance(observed_ms)
    return ph


def preplanned_visible_solution(rows, physics, observed_ms, events, *,
                               first_delay_ms=800, dispatch_gap_ms=160,
                               robust_ms=160, max_dispatches=1190):
    """Challenge the one-board shortcut without further task observations.

    This is an oracle plan, not a native execution or an optimality certificate.
    The only kinematic input is one current printed board. Native transport can
    use each absolute dispatch time through the frozen execute_at_s contract.
    The existing crossing search and safety margins are retained. Failed or
    late delivery must be recorded rather than repaired using later page state.
    """
    if any(type(v) is not int or v < 0 for v in
           (first_delay_ms, dispatch_gap_ms, robust_ms, max_dispatches)):
        raise ValueError('planning times and budget must be nonnegative integers')
    ph, routines = replay_visible_inputs(rows, physics, observed_ms, events)
    # Planning candidates revisit identical roof/tick pairs. Cache the existing
    # exact pose function; this changes neither trajectories nor acceptance.
    recovered_world = ph.world
    recovered_roofs = ph.roofs

    @lru_cache(maxsize=65536)
    def cached_pose(roof_id, ms):
        return roof_pose(recovered_world, recovered_roofs[roof_id], ms)

    ph.pose = lambda _world, roof, ms: cached_pose(roof['id'], ms)
    targets = {r['id'] for r in ph.world['roofs'] if r['lamp']}
    deadline = physics['max_task_ms']
    dispatches = []

    def settle():
        while (ph.flight or ph.queue or ph.pending_light or ph.ms < ph.busy_until):
            if ph.failed or ph.ms >= deadline:
                return False
            ph.advance(min(deadline, ph.ms + physics['tick_ms']))
        return not ph.failed

    if not settle():
        raise ValueError('initial history is not physically recoverable')
    minimum = max(ph.ms, observed_ms + first_delay_ms)
    while ph.lit != targets:
        if len(dispatches) >= max_dispatches or minimum >= deadline:
            raise ValueError('one-board plan exceeds the existing episode budget')
        ph.advance(((minimum + 9) // 10) * 10)
        if ph.roof in targets - ph.lit:
            token = 'G'
        else:
            destination = route(ph.world, ph.roof, targets - ph.lit)[1]
            vector = tuple(b-a for a, b in zip(ph.roofs[ph.roof]['cell'],
                                               ph.roofs[destination]['cell']))
            heading = DIRS.index(vector)
            if ph.heading != heading:
                token = 'L' if (heading-ph.heading) % 4 == 3 else 'R'
            else:
                try:
                    ms, token = next_jump(ph, destination, minimum,
                                          robust_ms=robust_ms)
                except AssertionError:
                    minimum = min(deadline, ph.ms + 15000)
                    continue
                if ms >= deadline:
                    raise ValueError('one-board launch exceeds the active allowance')
                ph.advance(ms)
        dispatches.append(dict(t_ms=ph.ms, token=token))
        ph.dispatch([token])
        if not settle():
            raise ValueError('one-board plan failed: ' + (ph.failed or 'active budget'))
        minimum = ph.ms + dispatch_gap_ms
    seal = ph.ms + dispatch_gap_ms
    if seal > deadline:
        raise ValueError('one-board certification exceeds the active allowance')
    ph.advance(seal)
    return dict(dispatches=dispatches, seal_t_ms=ph.ms, snapshot=ph.snapshot(),
                observed_ms=observed_ms, first_delay_ms=first_delay_ms,
                dispatch_gap_ms=dispatch_gap_ms, robust_ms=robust_ms,
                routines=routines, task_state_observations_after_plan=0,
                native_execution=False, optimality_certified=False)


def earliest_completion(physics, horizon_ms, *, first_commands=None, first_wait_ms=0):
    """Exact finite search of semantic continuation, including every wait tick.

    This diagnostic optimizes physical completion time within the supplied
    horizon. It searches all six primitives on every reachable ready state and
    every 10-ms no-action continuation. Literal routines are exactly primitive
    chains at busy endpoints; their input delivery/batch costs are outside this
    semantic search. It is NOT native HTTP execution or a proof of its timing.
    A short witness uses fewer than the declared input budget, so primitive
    continuation is sufficient there. General protocol optimality is separate.
    """
    ph=copy.deepcopy(physics)
    @lru_cache(maxsize=262144)
    def cached_pose(roof_id, ms):
        return roof_pose(ph.world,ph.roofs[roof_id],ms)
    ph.pose=lambda _world,roof,ms:cached_pose(roof['id'],ms)
    ph.advance(ph.ms+first_wait_ms)
    if first_commands:
        try:ph.dispatch(first_commands)
        except ValueError:pass # Unavailable controls have the no-action effect.
    targets={r['id'] for r in ph.world['roofs'] if r['lamp']}
    serial=itertools.count();queue=[];seen=set();expanded=0
    tick=ph.world['physics']['tick_ms']
    def settle(state):
        while (state.flight or state.queue or state.ms<state.busy_until or state.pending_light) and not state.failed and state.ms<horizon_ms:
            state.advance(min(horizon_ms,state.ms+tick))
        return state
    ph=settle(ph)
    heapq.heappush(queue,(ph.ms,next(serial),ph,[]))
    while queue:
        _,_,state,actions=heapq.heappop(queue)
        if state.failed or state.ms>horizon_ms:continue
        if state.flight or state.queue or state.ms<state.busy_until or state.pending_light:continue
        key=(state.ms,state.roof,state.heading,tuple(sorted(state.lit)))
        if key in seen:continue
        seen.add(key);expanded+=1
        if state.lit==targets:
            return dict(passed=True,completion_ms=state.ms,actions=actions,expanded=expanded)
        if state.ms+500*len(targets-state.lit)>horizon_ms:continue
        if state.ms+tick<=horizon_ms:
            waiting=copy.deepcopy(state);waiting.steps=[];waiting.advance(state.ms+tick)
            heapq.heappush(queue,(waiting.ms,next(serial),waiting,actions))
        for token in 'FJDLRG':
            trial=copy.deepcopy(state);trial.steps=[]
            trial.dispatch([token]);settle(trial)
            if not trial.failed and trial.ms<=horizon_ms:
                heapq.heappush(queue,(trial.ms,next(serial),trial,actions+[dict(t_ms=state.ms,token=token)]))
    return dict(passed=False,expanded=expanded,reason='no successful continuation within horizon')


def route(world, start, goals):
    roofs = {r["id"]: r for r in world["roofs"]}
    by_cell = {tuple(r["cell"]): r["id"] for r in world["roofs"]}
    queue, previous = deque([start]), {start: None}
    end = None
    while queue:
        current = queue.popleft()
        if current in goals:
            end = current
            break
        x, y = roofs[current]["cell"]
        for dx, dy in DIRS:
            neighbor = by_cell.get((x+dx, y+dy))
            if neighbor is not None and neighbor not in previous:
                previous[neighbor] = current
                queue.append(neighbor)
    if end is None:
        raise AssertionError("lamp unreachable in generated topology")
    result = [end]
    while previous[result[-1]] is not None:
        result.append(previous[result[-1]])
    return list(reversed(result))


def _possible_landing(physics, destination, ms, token):
    """Cheap conservative planning filter, never an acceptance rule."""
    world=physics.world;spec=world['physics']
    source=physics.pose(world,physics.roofs[physics.roof],ms)
    roof=physics.roofs[destination]
    tau=spec['nominal_flight_s']
    start=[source['position'][i]+(physics.offset[i] if i<2 else 0) for i in range(3)]
    velocity=[DIRS[physics.heading][i]/tau+spec['momentum']*source['velocity'][i] for i in range(2)]
    velocity.append({'F':0,'J':1,'D':-1}[token]/tau+.5*spec['gravity']*tau+spec['momentum']*source['velocity'][2])
    previous=None
    for dt in range(0,2001,50):
        s=dt/1000
        point=[start[i]+velocity[i]*s for i in range(3)]
        point[2]-=.5*spec['gravity']*s*s
        center=physics.pose(world,roof,ms+dt)['position']
        delta=point[2]-center[2]
        if previous is not None and previous[2]>0 and delta<=0:
            old_point,old_center,old_delta=previous
            f=old_delta/(old_delta-delta)
            hit=[old_point[i]+f*(point[i]-old_point[i]) for i in range(2)]
            goal=[old_center[i]+f*(center[i]-old_center[i]) for i in range(2)]
            if max(abs(a-b) for a,b in zip(hit,goal))<roof['half']-spec['robot_radius']+.03:
                return True
        previous=(point,center,delta)
    return False


def candidate(physics, destination, ms, token):
    if not _possible_landing(physics,destination,ms,token):
        return None
    trial = copy.deepcopy(physics)
    trial.advance(ms)
    trial.dispatch([token])
    deadline = ms+trial.world["physics"]["maximum_flight_ms"]
    while trial.flight and not trial.failed and trial.ms < deadline:
        trial.advance(trial.ms+10)
    if trial.failed or trial.roof != destination:
        return None
    half = trial.roofs[destination]["half"]
    margin = half-trial.world["physics"]["robot_radius"]-max(abs(v) for v in trial.offset)
    return trial, margin


def next_jump(physics, destination, minimum_ms=None, lookahead_ms=15000, robust_ms=0, step_ms=80):
    start = max(physics.ms, physics.busy_until, minimum_ms or 0)
    start = ((start+9)//10)*10
    for ms in range(start, start+lookahead_ms+1, step_ms):
        source = physics.pose(physics.world, physics.roofs[physics.roof], ms)
        target = physics.pose(physics.world, physics.roofs[destination], ms+1000)
        expected_delta = target["position"][2]-source["position"][2]-physics.world["physics"]["momentum"]*source["velocity"][2]
        tokens = sorted(("F", "J", "D"), key=lambda t: abs(expected_delta-{"F":0,"J":1,"D":-1}[t]))
        for token in tokens:
            checked = candidate(physics, destination, ms, token)
            if checked is None or checked[1] < .055:
                continue
            if robust_ms:
                neighbors = [candidate(physics, destination, ms+d, token) for d in range(-robust_ms, robust_ms+1, 20) if ms+d >= start]
                if any(v is None or v[1] < .02 for v in neighbors):
                    continue
            return ms, token
    raise AssertionError(f"no robust crossing found within {lookahead_ms} ms: {physics.roof} -> {destination}")


def center(ui, selector):
    return ui.read(f'(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }})()')


def click(ui, point):
    ui.send([{"mouse": {"left_click": point}}])


def place(ui, token, destination, mode):
    start, end = center(ui, f'[data-token="{token}"]'), center(ui, destination)
    if mode == "simplified":
        ui.send([{"mouse": {"left_click": start}}, {"mouse": {"left_click": end}}])
    else:
        ui.send([{"mouse": {"move": start, "buttons": {"left_down": True}}},
                 {"mouse": {"move": end}}, {"mouse": {"buttons": {"left_up": True}}}])


def visible_plan_mouse_batches(plan, points, socket_point, seal_point, mode):
    """Translate a plan into ordinary mouse batches, without executing them."""
    if mode not in ('full', 'simplified'):
        raise ValueError('unknown interaction surface')
    batches = []
    for dispatch in plan['dispatches']:
        first = points[dispatch['token']]
        if mode == 'simplified':
            actions = [{'mouse': {'left_click': first}}, {'mouse': {'left_click': socket_point}}]
        else:
            actions = [{'mouse': {'move': first, 'buttons': {'left_down': True}}},
                       {'mouse': {'move': socket_point}}, {'mouse': {'buttons': {'left_up': True}}}]
        batches.append(dict(t_ms=dispatch['t_ms'], actions=actions))
    batches.append(dict(t_ms=plan['seal_t_ms'], actions=[{'mouse': {'left_click': seal_point}}]))
    return batches


def compile_native_wait_batch(batches):
    """One exact-API batch using supported wait actions between mouse gestures.

    Waits begin after the preceding X-server fence, so injection overhead can
    accumulate. This is deliberately a separate shortcut policy, with no silent
    switch from absolute scheduling. It does not stop or mutate the task clock.
    """
    if not batches:
        raise ValueError('empty scheduled batch')
    first = previous = batches[0]['t_ms']
    actions = []
    for batch in batches:
        ms = batch['t_ms']
        if type(ms) is not int or ms < previous:
            raise ValueError('batch times must be ordered task ticks')
        if ms > previous:
            actions.append({'action': 'wait', 'seconds': (ms-previous)/1000})
        actions.extend(copy.deepcopy(batch['actions']))
        previous = ms
    return dict(start_t_ms=first, actions=actions, requested_wait_seconds=(previous-first)/1000,
                injection_overhead_compensation_ms=0, native_execution=False)


def solve_single_observation(ui, truth, *, first_delay_ms=5000, one_http_batch=False):
    """Native shortcut experiment: one active board, no later planning reads.

    Read-only DOM text/geometry and the declared physics constants are privileged
    aids. This is not a screenshot-only controller. send_at must deliver the
    normal HTTP mouse batch using the frozen sandbox-clock execute_at_s route.
    Observations returned by later requests are saved but do not change inputs.
    The enclosing validator may inspect state after the final certification.
    """
    if getattr(ui, 'paused', False):
        raise ValueError('this shortcut experiment is declared for live mode')
    if not callable(getattr(ui, 'send_at', None)):
        raise ValueError('absolute native HTTP scheduling adapter required')
    mode = truth['control_condition']['interaction']
    points = {token: center(ui, f'[data-token="{token}"]') for token in 'FJDLRG'}
    socket_point = center(ui, '#lv-dispatch')
    start_point, seal_point = center(ui, '#lv-start'), center(ui, '#lv-certify')
    click(ui, start_point)
    ui.wait(.6)
    board = ui.read('''(() => {
      const rows = [...document.querySelectorAll('#lv-board-body tr')].map(tr => {
        const c = [...tr.children].map(td => td.textContent.trim());
        const vector = text => text.split(/\\s+/).map(Number);
        return {id:'roof-'+(Number(c[0])-1),cell:vector(c[1]),lamp:c[2]!=='--',
          base_z:Number(c[3]),start:vector(c[4]),goal:vector(c[5]),
          remaining_ms:Math.round(Number(c[7])*1000)};
      });
      const observed_ms = Math.round(Number(document.querySelector('#lv-robot')
        .textContent.match(/TIME ([0-9.]+)/)[1])*1000);
      return {rows,observed_ms,native_date_ms:GymAnythingRTTime.status().native_date_ms,
        game_ms:performance.now()-lampwrightV2Model.epoch,
        half:Number(document.querySelector('#lv-board-scale').textContent
          .match(/DECK ([0-9.]+)/)[1])/2};
    })()''')
    p = copy.deepcopy(truth['world']['physics'])
    for row in board['rows']:
        row['half'] = board['half']
    events = [dict(kind='start', t_ms=0)]
    started = time.monotonic()
    plan = preplanned_visible_solution(board['rows'], p, board['observed_ms'], events,
                                      first_delay_ms=first_delay_ms)
    plan['planning_wall_seconds'] = time.monotonic()-started
    plan['observation_transport'] = 'read-only printed DOM table; native JPEG retained separately'
    plan['actual_native_execution_pending'] = True
    plan['input_packaging'] = 'one-native-wait-batch' if one_http_batch else 'absolute-dispatch-requests'
    ui.record_one_board_plan(board, plan)
    batches = visible_plan_mouse_batches(plan, points, socket_point, seal_point, mode)
    if one_http_batch:
        compiled = compile_native_wait_batch(batches)
        # Retain the frozen client's 60-second per-request timeout. Do not
        # lengthen it or silently split a batch to manufacture a success.
        if compiled['requested_wait_seconds'] >= 55:
            raise ValueError('one-batch plan exceeds the declared HTTP deadline reserve')
        ui.send_at(compiled['actions'], compiled['start_t_ms'], board)
    else:
        for batch in batches:
            ui.send_at(batch['actions'], batch['t_ms'], board)
    return plan


def solve(ui, truth, *, lead_ms=160, robust_ms=160):
    """Read-only page diagnostics and literal HTTP mouse primitives.

    Planning knows the seed's entire kinematics. This proves wiring/solvability,
    never screenshot-only policy competence or downstream model difficulty.
    """
    world = truth["world"]
    mode = truth["control_condition"]["interaction"]
    if getattr(ui, "paused", False):
        lead_ms = robust_ms = 0
    place(ui, "G", '[data-panel="A"][data-index="0"]', mode)
    place(ui, "R", '[data-panel="B"][data-index="0"]', mode)
    click(ui, center(ui, "#lv-start"))
    targets = {r["id"] for r in world["roofs"] if r["lamp"]}
    deadline = time.monotonic()+650
    while time.monotonic() < deadline:
        state = ui.read('({snapshot:lampwrightV2Model.physics.snapshot(),terminal:lampwrightV2Model.terminal})')
        s = state["snapshot"]
        assert not s["failed"] and not state["terminal"], state
        if s["flight"] or s["queue"] or s["t_ms"] < s["busy_until"]:
            ui.wait(.06)
            continue
        remaining = targets-set(s["lit"])
        if not remaining:
            click(ui, center(ui, "#lv-certify"))
            return
        if s["roof"] in remaining:
            place(ui, "A", "#lv-dispatch", mode)
            continue
        path = route(world, s["roof"], remaining)
        destination = path[1]
        roofs = {r["id"]: r for r in world["roofs"]}
        vector = tuple(b-a for a, b in zip(roofs[s["roof"]]["cell"], roofs[destination]["cell"]))
        desired_heading = DIRS.index(vector)
        if s["heading"] != desired_heading:
            delta = (desired_heading-s["heading"]) % 4
            place(ui, "L" if delta == 3 else "B", "#lv-dispatch", mode)
            continue
        physics = Physics(world)
        for k in ("roof", "heading", "offset", "position", "flight", "busy_until", "queue", "failed", "steps"):
            setattr(physics, k, copy.deepcopy(s[k]))
        physics.ms = s["t_ms"]
        physics.lit = set(s["lit"])
        try:
            ms, token = next_jump(physics, destination, s["t_ms"]+lead_ms, robust_ms=robust_ms,
                                  step_ms=600 if getattr(ui, "paused", False) else 80)
        except AssertionError:
            # A search horizon ending is not a physical terminal failure.
            # Observe again as the independent lifts expose another crossing.
            ui.wait(.6 if getattr(ui, "paused", False) else 1.)
            continue
        actual_ms = ui.read('lampwrightV2Model.physics.ms')
        if actual_ms > ms+40:
            continue
        if ms-actual_ms > lead_ms:
            ui.wait((ms-actual_ms-lead_ms)/1000)
            # Keep the planned future crossing; rereading cannot inject input.
            actual_ms = ui.read('lampwrightV2Model.physics.ms')
        if actual_ms > ms+40:
            continue
        place(ui, token, "#lv-dispatch", mode)
    raise AssertionError("lampwright oracle exceeded declared active budget")


def simulation_solution(world, *, delay_ms=0, fixed=False):
    """Mechanism diagnostic only. Direct simulator control is not UI evidence."""
    ph = Physics(world)
    targets = {r["id"] for r in world["roofs"] if r["lamp"]}
    actions = []
    max_ms = world["physics"]["max_task_ms"]
    while ph.lit != targets and not ph.failed and ph.ms < max_ms:
        ph.advance(max(ph.ms, ph.busy_until)+10)
        if ph.roof in targets-ph.lit:
            ph.dispatch(["G"])
            actions.append(dict(t_ms=ph.ms, token="G"))
            ph.advance(ph.busy_until)
            continue
        path = route(world, ph.roof, targets-ph.lit)
        destination = path[1]
        vector = tuple(b-a for a,b in zip(ph.roofs[ph.roof]["cell"], ph.roofs[destination]["cell"]))
        heading = DIRS.index(vector)
        while ph.heading != heading:
            token = "L" if (heading-ph.heading)%4 == 3 else "R"
            actions.append(dict(t_ms=ph.ms, token=token))
            ph.dispatch([token]); ph.advance(ph.busy_until)
        if fixed:
            token = "F"; ms = ph.ms
        else:
            try:
                ms, token = next_jump(ph, destination)
            except AssertionError:
                ph.advance(min(max_ms, ph.ms+15000))
                continue
        actions.append(dict(t_ms=ms+delay_ms, token=token))
        ph.advance(ms+delay_ms)
        ph.dispatch([token])
        ph.advance(ms+delay_ms+2200)
    return dict(passed=not ph.failed and ph.lit==targets, t_ms=ph.ms, actions=actions,
                failure=ph.failed, lit=sorted(ph.lit), steps=ph.steps)
