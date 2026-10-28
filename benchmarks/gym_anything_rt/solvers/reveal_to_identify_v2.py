"""Privileged geometry oracle. Every input is a downstream HTTP action payload.

The caller supplies send(actions), read(expression) and wait(seconds). `read`
is privileged, read-only planning and must be disclosed; it never mutates state.
A Playwright transport can test wiring but cannot prove native action parity.
"""
from __future__ import annotations

import copy
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.reveal_to_identify_v2 import Simulation

MECHANIC_ID = "reveal_to_identify_v2"


def box(ui, selector):
    return ui.read("(() => { const r=document.querySelector("+repr(selector)+
                   ").getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}; })()")


def click(ui, rect):
    ui.send([{"mouse": {"left_click": [round(rect["x"]+rect["width"]/2),
                                       round(rect["y"]+rect["height"]/2)]}}])


def snapshot(ui):
    return ui.read("(() => { const m=revealScannerModel,s=m.sim; return {tick:s.tick,items:s.items,"
                   "aim:s.aim,velocity:s.velocity,target:s.target,tagged:[...s.tagged],"
                   "flow_state:s.flow_state,valve_history:s.valve_history,scanned:[...s.scanned],armed:s.armed,last_fire:s.last_fire,"
                   "pulses:s.pulses,terminal:m.terminal,failed:s.failed,active:m.active}; })()")


def predicted(contract, state, ticks):
    sim = Simulation(contract)
    sim.tick = state["tick"]; sim.items = copy.deepcopy(state["items"])
    sim.aim = list(state["aim"]); sim.velocity = list(state["velocity"]); sim.target = list(state["target"])
    sim.tagged = set(state["tagged"])
    sim.flow_state = list(state["flow_state"])
    sim.scanned = set(state.get("scanned", []))
    sim.advance(sim.tick+ticks)
    return sim.items


def visible_mean_position(item, world, horizon_seconds):
    """Local constant-current approximation, deliberately omitting contacts.

    This is a limited visual extrapolator for diagnostics. It is not the exact
    state-based flow forecast and does not establish optimal continuation.
    """
    t = max(0, horizon_seconds)
    k = world["current_response"]
    v_weight = (1-math.exp(-k*t))/k
    c_weight = t-v_weight
    return [item["x"]+item["vx"]*v_weight+item["cx"]*c_weight,
            item["y"]+item["vy"]*v_weight+item["cy"]*c_weight]


def forecast_instruments(world, state, ticks):
    """Predict unforced motion from currently visible instruments only.

    No existing pulse may be pending: its impact can reveal a new valve choice.
    A proposed pulse has not yet changed the flow before its own impact, so this
    forecast is exact through that impact, including walls/circle contacts.
    It does not compute optimal multi-target continuation or read its cartridge.
    """
    if state.get("pulses"):
        raise ValueError("pending impact requires the visible finite-branch belief")
    visible_world = copy.deepcopy(world)
    visible_world.pop("valve_program", None)
    visible_world["flow_initial"] = list(state["flow_state"])
    visible_world["valve_program"] = []
    contract = dict(world=visible_world,carriers=copy.deepcopy(state["items"]),wanted=[])
    return predicted(contract,state,ticks)


def solve_http(ui, truth, max_seconds=140):
    mode = truth["control_condition"]["interaction"]
    paused = ui.read("GymAnythingRTTime.status().mode") == "paused"

    def observe_progress(seconds):
        # The downstream HTTP transport returns an observation after each send.
        # In paused mode only that capture window advances asynchronous effects;
        # sleeping the client cannot progress a pulse that is still in flight.
        if paused:
            ui.send([])
        else:
            ui.wait(seconds)

    tank = box(ui, "#rti2-tank")
    def screen(point):
        return [round(tank["x"]+point[0]*tank["width"]/900),
                round(tank["y"]+point[1]*tank["height"]/500)]
    click(ui, box(ui, "#rti2-start"))
    held = False
    deadline = time.monotonic()+max_seconds
    iterations = 0
    scan_goal = None
    while time.monotonic() < deadline:
        state = snapshot(ui)
        if state["terminal"]:
            if state["failed"]:
                raise AssertionError("oracle terminal failure: "+state["failed"])
            break
        remaining = [item for item in state["items"] if item["id"] in truth["wanted_ids"] and item["id"] not in state["tagged"]]
        if not remaining:
            observe_progress(.1); continue
        if state["pulses"]:
            observe_progress(.1); continue
        # Fully expose every identity before arming. The physical optical rule is
        # independently replayed; the oracle cannot bypass it with private IDs.
        unscanned = [item for item in state["items"] if item["id"] not in state["scanned"]]
        if unscanned:
            if scan_goal not in [item["id"] for item in unscanned]:
                scan_goal = min(unscanned,key=lambda item:math.hypot(item["x"]-state["aim"][0],item["y"]-state["aim"][1]))["id"]
            goal = next(item for item in unscanned if item["id"] == scan_goal)
        else:
            goal = min(remaining, key=lambda item: math.hypot(item["x"]-state["aim"][0], item["y"]-state["aim"][1]))
        # Exact replay is privileged oracle planning, not agent observation.
        future = next(item for item in predicted(truth, state, truth["world"]["pulse_lag_ms"]//10+3) if item["id"] == goal["id"])
        margin = truth["world"]["carrier_radius"]+truth["world"]["pulse_radius"]-14
        can_fire = state["armed"] and state["tick"]*10-state["last_fire"]>=truth["world"]["pulse_cooldown_ms"] and math.hypot(future["x"]-state["aim"][0], future["y"]-state["aim"][1]) < margin
        # Search and steering use the same dynamically limited scanner in both modes.
        steer_ticks = 30 if unscanned else truth["world"]["pulse_lag_ms"]//10+25
        steer = next(item for item in predicted(truth, state, steer_ticks) if item["id"] == goal["id"])
        target = screen([steer["x"],steer["y"]])
        actions = []
        if mode == "full":
            if not held:
                actions.append({"mouse":{"move":screen(state["aim"]),"buttons":{"left_down":True}}})
                held = True
            actions.append({"mouse":{"move":target}})
            if can_fire:
                actions.append({"keyboard":{"keys":["Space"]}})
        else:
            actions.append({"mouse":{"left_click":target}})
            if can_fire:
                pulse = box(ui,"#rti2-pulse")
                actions.append({"mouse":{"left_click":[round(pulse["x"]+pulse["width"]/2),round(pulse["y"]+pulse["height"]/2)]}})
        ui.send(actions)
        iterations += 1
        if not paused:
            ui.wait(.16)
    else:
        raise AssertionError("scanner oracle budget expired")
    if held:
        ui.send([{"mouse":{"buttons":{"left_up":True}}}])
    ui.wait(.15)
    decision=ui.read("revealScannerModel.result || null")
    # The static browser initializes pinned Pyodide asynchronously after a valid
    # terminal hit. Waiting for grading does not deliver any further game action.
    verification_deadline=time.monotonic()+30
    while decision is None and time.monotonic()<verification_deadline:
        ui.wait(.1)
        decision=ui.read("revealScannerModel.result || null")
    if not decision or not decision.get("passed"):
        raise AssertionError("oracle did not receive independent server pass: "+str(decision))
    return dict(iterations=iterations,mode=mode,planning="privileged read-only geometry and deterministic future replay",actions="HTTP mouse/keyboard payloads supplied to the caller's transport")
