"""Standalone independent fixed-step membrane replay, including browser export."""
from __future__ import annotations
import math

MECHANIC_ID = "cell_gatekeeper_v2"
REVISION = "atp-stroke-v2"


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def position(particle, milliseconds, world):
    u = max(0, milliseconds+particle["motion_offset_ms"])/particle["span_ms"]
    index, fraction = math.floor(u), u-math.floor(u)
    a, b = noise(particle["motion_seed"], index), noise(particle["motion_seed"], index+1)
    blend = fraction*fraction*(3-2*fraction)
    direction = world["lanes"][particle["lane"]]["direction"]
    return [world["stage"]["membrane_x"] + direction*particle["speed"]*(milliseconds-particle["arrival_ms"])/1000,
            particle["base_y"]+particle["drift"]*(a+(b-a)*blend)]


def initial_state(world):
    return dict(tick=0, started=False, status="ready", failure="", resolved=[], caught=[], blocked=[],
                pumps=[dict(y=l["initial_y"], target=l["initial_y"], velocity=0., open=False, atp=l["atp"], stroke_start=None, stroke_target=l["initial_y"]) for l in world["lanes"]], hold=None)


def advance(state, world, target):
    p = world["parameters"]
    while state["tick"] < target and state["status"] == "running":
        state["tick"] += 1
        ms = state["tick"]*10
        for lane, pump in zip(world["lanes"], state["pumps"]):
            if pump["stroke_start"] is not None:
                elapsed = ms-pump["stroke_start"]
                pump["open"] = p["stroke_arm_ms"] <= elapsed < p["stroke_arm_ms"]+p["stroke_open_ms"]
                if elapsed >= p["stroke_arm_ms"]+p["stroke_open_ms"]+p["stroke_recovery_ms"]:
                    pump.update(stroke_start=None, open=False)
            drive = pump["target"] if pump["stroke_start"] is None else pump["stroke_target"]
            acc = (drive-pump["y"])*p["spring"]-pump["velocity"]*p["damping"]
            pump["velocity"] = max(-p["pump_speed"], min(p["pump_speed"], pump["velocity"]+acc*.01))
            half = p["aperture"]/2
            pump["y"] = max(lane["low"]+half, min(lane["high"]-half, pump["y"]+pump["velocity"]*.01))
            if pump["y"] in (lane["low"]+half, lane["high"]-half):
                pump["velocity"] = 0.
        for particle in world["particles"]:
            if particle["id"] in state["resolved"] or ms < particle["arrival_ms"]:
                continue
            # Interpolate the pump at the exact contact instant, so an ion's
            # displayed crossing and physical acceptance use the same plane.
            pump = state["pumps"][particle["lane"]]
            contact_y = pump["y"]-pump["velocity"]*(ms-particle["arrival_ms"])/1000
            ion_y = position(particle, particle["arrival_ms"], world)[1]
            opened = pump["stroke_start"] is not None and p["stroke_arm_ms"] <= particle["arrival_ms"]-pump["stroke_start"] < p["stroke_arm_ms"]+p["stroke_open_ms"]
            enters = opened and abs(ion_y-contact_y)+particle["radius"] <= p["aperture"]/2 + 1e-7
            state["resolved"].append(particle["id"])
            if enters and particle["kind"] == "inhibitor":
                state.update(status="failed", failure="An inhibitor entered the cell.")
                break
            if particle["kind"] == "nutrient":
                if not enters:
                    state.update(status="failed", failure="A required solute was lost at the membrane.")
                    break
                state["caught"].append(particle["id"])
            else:
                state["blocked"].append(particle["id"])
        if state["status"] == "running" and len(state["resolved"]) == len(world["particles"]):
            state["status"] = "complete"


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("nonfinite coordinate")
    return value


def apply_event(state, world, event, mode):
    kind = event["kind"]
    if kind == "start":
        if state["status"] != "ready" or state["started"] or state["tick"] != 0 or event.get("input_source") != "start_button":
            raise ValueError("invalid start")
        state.update(started=True, status="running")
        return
    if kind == "certify":
        if event.get("input_source") != "certify_button":
            raise ValueError("wrong certification control")
        if state["status"] != "complete":
            state.update(status="failed", failure="Transfer certified before completion.")
        return
    # A held pump does not stop perfusion. The normal pointer release at the
    # completed crossing is valid and cannot change the physical outcome.
    releasing_complete = state["status"] == "complete" and kind == "drag_end"
    if state["status"] not in ("ready", "running") and not releasing_complete:
        raise ValueError("input after terminal outcome")
    lane_index = event.get("lane")
    if type(lane_index) is not int or lane_index not in range(len(world["lanes"])):
        raise ValueError("invalid pump")
    lane, pump = world["lanes"][lane_index], state["pumps"][lane_index]
    half = world["parameters"]["aperture"]/2
    source = event.get("input_source")
    if kind == "stroke":
        if source != ("pump_key" if mode == "full" else "pump_button"):
            raise ValueError("wrong gate input surface")
        at_ms = number(event.get("at_ms"))
        if not state["tick"]*10 <= at_ms < state["tick"]*10+10:
            raise ValueError("stroke time outside the physical input tick")
        # ATP powers an irreversible conformational cycle. Later steering is
        # queued for the next cycle; it cannot move this committed aperture.
        if state["started"] and pump["stroke_start"] is None and pump["atp"] > 0:
            pump.update(stroke_start=at_ms, stroke_target=pump["target"], open=False, atp=pump["atp"]-1)
        return
    point = event.get("point")
    if not isinstance(point, list) or len(point) != 2:
        raise ValueError("missing pointer point")
    x, y = map(number, point)
    if not 0 <= x <= 960 or not 0 <= y <= 450:
        raise ValueError("pointer outside chamber")
    if kind == "drag_start":
        if mode != "full" or source != "pump_drag" or state["hold"] is not None or abs(x-480) > 27 or abs(y-pump["y"]) > half+8:
            raise ValueError("drag must start on the pump body")
        state["hold"] = lane_index
    elif kind in ("drag_move", "drag_end"):
        if mode != "full" or source != "pump_drag" or state["hold"] != lane_index:
            raise ValueError("pump is not held")
        if kind == "drag_end":
            state["hold"] = None
    elif kind == "target":
        if mode != "simplified" or source != "rail_click" or not 519 <= x <= 549 or not lane["low"] <= y <= lane["high"]:
            raise ValueError("click the selected pump's rail")
    else:
        raise ValueError("unknown membrane action")
    if kind in ("drag_move", "target"):
        pump["target"] = max(lane["low"]+half, min(lane["high"]-half, y))
        if not state["started"]:
            pump.update(y=pump["target"], velocity=0.)


def grade(payload, truth, public):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(item, dict) for item in (payload, truth, public)):
            return fail("invalid result envelope")
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not truth.get(key) or payload.get(key) != truth[key] or public.get(key) != truth[key]:
                return fail("stale identity or revision: "+key)
        if truth["mechanic_id"] != MECHANIC_ID or truth["revision"] != REVISION:
            return fail("wrong membrane mechanic")
        for key in ("parameters", "stage", "lanes", "particles", "duration_ms", "control_condition"):
            if truth.get(key) != public.get(key):
                return fail("public contract mismatch: "+key)
        mode = (truth.get("control_condition") or {}).get("interaction", "full")
        if payload.get("interaction_mode") != mode or mode not in ("full", "simplified"):
            return fail("wrong interaction mode")
        events = payload.get("events")
        end = payload.get("final_tick")
        if not isinstance(events, list) or not 1 <= len(events) <= 6000 or type(end) is not int or not 0 <= end <= math.ceil(truth["duration_ms"]/10):
            return fail("invalid membrane transcript size or endpoint")
        state = initial_state(truth)
        prior = 0
        certified = False
        for seq, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("sequence") != seq:
                return fail("invalid sequence")
            tick = event.get("tick")
            if type(tick) is not int or not prior <= tick <= end or certified or (not state["started"] and tick != 0):
                return fail("invalid event time or terminal input")
            advance(state, truth, tick)
            if state["tick"] != tick:
                return fail("action arrived after terminal crossing")
            apply_event(state, truth, event, mode)
            prior = tick
            certified = event["kind"] == "certify"
        advance(state, truth, end)
        if state["tick"] != end or state["status"] != "complete" or state["hold"] is not None:
            return fail(state["failure"] or "transfer incomplete or pump still held")
        reported = payload.get("final_state")
        if not isinstance(reported, dict):
            return fail("missing final state")
        for key in ("tick", "started", "status", "failure", "caught", "blocked", "resolved", "hold"):
            if reported.get(key) != state[key]:
                return fail("final replay differs: "+key)
        if len(reported.get("pumps", [])) != len(state["pumps"]):
            return fail("wrong final pumps")
        for a, b in zip(reported["pumps"], state["pumps"]):
            for key in ("open", "atp", "stroke_start"):
                if type(a.get(key)) is not type(b[key]) or a[key] != b[key]:
                    return fail("final pump resource differs")
            for key in ("y", "target", "velocity", "stroke_target"):
                if abs(number(a.get(key))-b[key]) > .002:
                    return fail("final pump motion differs")
        if payload.get("completed") is not True:
            return fail("no complete transfer")
        return dict(graded=True, passed=True, score=100, feedback=f"Membrane replay: {len(state['caught'])} solutes transferred; inhibitors excluded.")
    except (TypeError, ValueError, KeyError, IndexError, OverflowError, AttributeError) as exc:
        return fail("invalid membrane replay: "+str(exc))
