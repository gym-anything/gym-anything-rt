"""Privileged oracle planning with literal downstream mouse/keyboard actions.

`ui.send` is the unchanged HTTP gateway in native validation. Headless tests use
an explicitly different Playwright transport, which does not prove native API
parity. `ui.read` diagnoses page state for planning only. No action is injected
by JavaScript and no game function is called to execute a solution.
"""
from __future__ import annotations

import copy
import time

from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.blind_dice_courier_v2 import MOVES, static_route
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.blind_dice_courier_v2 import Simulation

KEYS = {"N": "Up", "E": "Right", "S": "Down", "W": "Left"}


def _click(ui, selector):
    # Diagnostic geometry read, never DOM focus or a DOM action.
    point = ui.read(f"(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()")
    ui.send([{"mouse": {"left_click": point}}])


def read_state(ui):
    return ui.read("({t:blindDiceCourierV2Model.sim.ms, position:blindDiceCourierV2Model.sim.position, faces:blindDiceCourierV2Model.sim.faces, pending:blindDiceCourierV2Model.sim.pending, crossings:blindDiceCourierV2Model.sim.crossings, failed:blindDiceCourierV2Model.sim.failed, delivered:blindDiceCourierV2Model.sim.delivered, terminal:blindDiceCourierV2Model.terminal})")


def group_length(world, point, route):
    """Do not insert observation-free parking while inside a shutter."""
    columns = {g["column"] for g in world["gates"]}
    position = list(point)
    for index, direction in enumerate(route, 1):
        dx, dy = MOVES[direction]
        position = [position[0]+dx, position[1]+dy]
        if position[0] not in columns:
            return index
    return len(route)


def safe_group(contract, state, directions, start_ms, gap_ms=80, reserve_ms=160):
    """Exact geometry forecast, plus transport slack; privileged planning."""
    for offset in (0, reserve_ms):
        sim = Simulation(contract)
        sim.active = True
        sim.ms = state["t"]
        sim.position = list(state["position"])
        sim.faces = list(state["faces"])
        sim.crossings = list(state["crossings"])
        sim.advance(start_ms+offset)
        for direction in directions:
            if sim.failed or sim.delivered:
                break
            sim.move(direction)
            sim.advance(sim.ms+sim.world["roll_ms"])
            if sim.failed: break
            if not sim.delivered: sim.advance(sim.ms+gap_ms)
        if sim.failed: return False
    return True


def forecast_from_display(static_contract, observation_ms, sweeps, horizon_ms):
    """Reconstruct only the current and following sweeps from displayed data.

    ``static_contract`` must contain no motion tracks. ``sweeps`` contains the
    rail endpoints, duration labels and phase bar for each gate, with no seed
    or segment index. The caller must observe again before the horizon expires.
    This is an information-sufficiency diagnostic, not a pixel-reading policy.
    """
    forecast = copy.deepcopy(static_contract)
    for gate in forecast["world"]["gates"]:
        if "track" in gate:
            raise ValueError("display forecast must not receive hidden motion tracks")
        sweep = sweeps[gate["id"]]
        start = observation_ms-sweep["phase"]*sweep["duration_ms"]
        turn = start+sweep["duration_ms"]
        end = turn+sweep["next_duration_ms"]
        latest_offset = max(slat["offset_ms"] for slat in gate["slats"])
        if horizon_ms+latest_offset >= end:
            raise ValueError("forecast exceeds the displayed following sweep")
        gate["track"] = [dict(start_ms=start, duration_ms=sweep["duration_ms"],
                              a=sweep["a"], b=sweep["b"]),
                         dict(start_ms=turn, duration_ms=sweep["next_duration_ms"],
                              a=sweep["b"], b=sweep["next"])]
    return forecast


def solve(ui, truth, *, timeout=300):
    """Complete via the selected visible input surface. No paid model call."""
    mode = (truth.get("control_condition") or {}).get("interaction", "full")
    _click(ui, ".bdc-start")
    route = static_route(truth["world"], truth["initial_orientation"])
    deadline = time.monotonic()+timeout
    while route and time.monotonic() < deadline:
        state = read_state(ui)
        if state["failed"] or state["terminal"]:
            raise AssertionError(state)
        if state["pending"]:
            ui.wait(.025)
            continue
        count = group_length(truth["world"], state["position"], route)
        directions = route[:count]
        if not safe_group(truth, state, directions, state["t"]):
            ui.wait(.05)
            continue
        for direction in directions:
            if mode == "full":
                ui.send([{"keyboard": {"keys": [KEYS[direction]]}}])
            else:
                _click(ui, f'.bdc-direction[data-direction="{direction}"]')
            route.pop(0)
            while time.monotonic() < deadline:
                current = read_state(ui)
                if current["failed"]: raise AssertionError(current)
                if not current["pending"]: break
                ui.wait(.025)
    if route:
        raise AssertionError("courier oracle deadline exhausted")
    ui.wait(.1)
    if not read_state(ui)["delivered"]:
        raise AssertionError("courier not delivered")


def simulate_policy(contract, policy="feedback", *, delay_ms=0):
    """Matched-state mechanics diagnostic, not input-API solvability evidence.

    Feedback observes the state on a 100ms cadence and uses an exact local
    geometry forecast. Delay delivers the chosen group after a stale interval.
    Preplanned prepares the static orientation route, then uses a fixed script.
    Parked sends only the initial start and cannot change the die's position.
    """
    sim = Simulation(contract)
    sim.active = True
    route = static_route(sim.world, sim.faces)
    events = [dict(sequence=1, kind="start", t_ms=0, input_source="start_button")]
    if policy == "parked":
        sim.advance(sim.world["play_time_ms"])
        return dict(passed=False, state=sim.snapshot(), events=events, observations=0)
    source = "keyboard" if (contract.get("control_condition") or {}).get("interaction", "full") == "full" else "direction_buttons"
    observations = 0
    while route and sim.ms < sim.world["play_time_ms"]-1000 and not sim.failed:
        count = group_length(sim.world, sim.position, route)
        directions = route[:count]
        state = dict(t=sim.ms, position=sim.position, faces=sim.faces, crossings=sim.crossings)
        if policy == "feedback":
            observations += 1
            if not safe_group(contract, state, directions, sim.ms, gap_ms=20, reserve_ms=100):
                sim.advance(sim.ms+100)
                continue
            sim.advance(sim.ms+delay_ms)
        elif policy == "preplanned":
            if count > 1: sim.advance(sim.ms+5000)
        else:
            raise ValueError("unknown diagnostic policy")
        for direction in directions:
            if sim.failed or sim.delivered: break
            accepted = sim.move(direction)
            events.append(dict(sequence=len(events)+1,kind="roll",t_ms=sim.ms,direction=direction,input_source=source,accepted=accepted))
            sim.advance(sim.ms+sim.world["roll_ms"])
            route.pop(0)
            if not sim.failed and not sim.delivered: sim.advance(sim.ms+20)
    return dict(passed=sim.delivered and not sim.failed, state=sim.snapshot(), events=events, observations=observations)


def replay_payload(public, result):
    return {**{k: public[k] for k in ("mechanic_id", "task_id", "challenge_id", "revision")},
            "interaction_mode": (public.get("control_condition") or {}).get("interaction", "full"),
            "events": copy.deepcopy(result["events"]), "completed": result["passed"],
            "final_t_ms": result["state"]["t_ms"], "final_state": copy.deepcopy(result["state"])}
