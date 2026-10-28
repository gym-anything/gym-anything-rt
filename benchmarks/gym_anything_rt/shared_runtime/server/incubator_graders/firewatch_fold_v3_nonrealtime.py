"""Independent replay of moving fire cores and finite travelling water pulses."""
from __future__ import annotations

import math

MECHANIC_ID = "firewatch_fold_v3_nonrealtime"
DEFAULT_ACTION_TRANSITION_TICKS = 30


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(seed, ms, span):
    u = max(0, ms) / span
    n, f = math.floor(u), u % 1
    a, b = noise(seed, n), noise(seed, n + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def integral(seed, ms, span):
    u = max(0, ms) / span
    n, f = math.floor(u), u % 1
    total = sum((noise(seed, i) + noise(seed, i + 1)) / 2 for i in range(n))
    a, b = noise(seed, n), noise(seed, n + 1)
    return span * (total + a * f + (b - a) * (f ** 3 - f ** 4 / 2))


def fire_x(fire, tick, world):
    ms = tick * world["tick_ms"]
    travel = fire["speed"] * (ms + fire["variation"] * integral(fire["wind_seed"], ms, fire["span_ms"])) / 1000
    return (fire["x"] + fire["direction"] * travel) % (2 * world["width"])


def fire_velocity(fire, tick, world):
    return fire["direction"] * fire["speed"] * (1 + fire["variation"] *
           motion(fire["wind_seed"], tick * world["tick_ms"], fire["span_ms"]))


def distance(a, b, world):
    width = 2 * world["width"]
    return abs((a - b + width / 2) % width - width / 2)


def initial(world):
    return dict(tick=0, started=False, player=list(world["start"]), facing=1,
        view=world["start"][1] // world["width"], surveyed_faces=[], stock=world["stock"], cleared=[],
        pulse=None, last_move=-100, failure=None, rescued=False,
        selected=0, cartridges=list(world["cartridges"]))


def advance(state, world, target):
    while state["tick"] < target and state["started"] and not state["failure"] and not state["rescued"]:
        state["tick"] += 1
        pulse = state["pulse"]
        if pulse:
            travel = min(world["pulse_reach"], (state["tick"] - pulse["tick"]) * world["tick_ms"] / 1000 * world["pulse_speed"])
            x = (pulse["x"] + pulse["direction"] * travel) % (2 * world["width"])
            # A fixed step moves less than .16 cells relatively; the minimum
            # combined collision diameter is .92 cells. No core can tunnel.
            hits = [f for f in world["fires"] if f["floor"] == pulse["floor"] and
                    f["id"] not in state["cleared"] and
                    distance(x, fire_x(f, state["tick"], world), world) <= f["radius"] + world["pulse_radius"]]
            if hits:
                hit = min(hits, key=lambda f: (distance(x, fire_x(f, state["tick"], world), world), f["id"]))
                if hit["color"] != pulse["color"]:
                    state["failure"] = "WRONG CANISTER — FIRST CORE NEEDS ITS MATCHING COLOR"
                else:
                    state["cleared"].append(hit["id"])
                    state["cleared"].sort()
                state["pulse"] = None
            elif travel >= world["pulse_reach"]:
                state["failure"] = "MISSED PULSE — STOCK CANNOT CONTAIN ALL FRONTS"
                state["pulse"] = None
        if state["tick"] >= world["max_ticks"] and not state["rescued"]:
            state["failure"] = "RESCUE WINDOW CLOSED"


def apply(state, world, kind, direction=None):
    if state["failure"] or state["rescued"]:
        return "terminal"
    if kind == "start":
        if state["started"]:
            return "already_started"
        state["started"] = True
        return "started"
    if kind == "inspect":
        state["view"] = 1 - state["view"]
        if state["view"] not in state["surveyed_faces"]:
            state["surveyed_faces"].append(state["view"])
            state["surveyed_faces"].sort()
        return "inspected"
    if kind == "select":
        state["selected"] = direction
        return "selected"
    if not state["started"]:
        return "scouting_only"
    floor, x = state["player"]
    if kind == "move":
        if state["tick"] - state["last_move"] < world["move_cooldown_ticks"]:
            return "cooldown"
        state["last_move"] = state["tick"]
        if direction in ("LEFT", "RIGHT"):
            state["facing"] = -1 if direction == "LEFT" else 1
            state["player"][1] = (x + state["facing"]) % (2 * world["width"])
            state["view"] = state["player"][1] // world["width"]
            return "seam_crossed" if state["view"] != x // world["width"] else "walked"
        lower = floor if direction == "UP" else floor - 1
        if not 0 <= lower < world["floors"] - 1 or x not in world["ladders"][lower]:
            return "no_ladder"
        if any(f["floor"] == lower and f["id"] not in state["cleared"] for f in world["fires"]):
            return "thermal_lock"
        state["player"][0] += 1 if direction == "UP" else -1
        return "climbed"
    if kind == "fire":
        if state["pulse"]:
            return "pulse_in_flight"
        if state["cartridges"][state["selected"]] <= 0:
            return "empty"
        state["stock"] -= 1
        state["cartridges"][state["selected"]] -= 1
        state["pulse"] = dict(tick=state["tick"], floor=floor, x=x + .5, direction=state["facing"],color=state["selected"])
        return "fired"
    raise ValueError("unsupported control")


def snapshot(state):
    return {k: state[k] for k in ("tick", "started", "player", "facing", "view", "surveyed_faces", "stock", "cleared", "failure", "rescued", "selected", "cartridges")}


def grade(payload, ground_truth, public_state):
    def fail(reason):
        return dict(graded=True, passed=False, score=0, feedback=reason)
    try:
        if not all(isinstance(item, dict) for item in (payload, ground_truth, public_state)):
            return fail("malformed firewatch contract")
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("wrong or stale " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("world", "control_condition", "interaction"):
            if ground_truth.get(key) != public_state.get(key):
                return fail("public/replay contract mismatch: " + key)
        mode = ground_truth["interaction"]
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction")
        world = ground_truth["world"]
        events = payload.get("events")
        if not isinstance(events, list) or not events:
            return fail("missing transcript")
        state = initial(world)
        for sequence, event in enumerate(events, 1):
            if not isinstance(event, dict):
                return fail("malformed event")
            tick, kind = event["tick"], event["kind"]
            if (type(tick) is not int or not state["tick"] <= tick <= world["max_ticks"] or
                    type(event.get("sequence")) is not int or event.get("sequence") != sequence or
                    kind not in ("start", "inspect", "move", "fire", "select")):
                return fail("invalid event order, time or kind")
            if not state["started"] and tick != 0:
                return fail("task time before start")
            source = "button" if kind in ("start", "inspect") else ("keyboard" if mode == "full" else "proxy_button")
            if event.get("input_source") != source:
                return fail("wrong input surface")
            if kind == "move" and event.get("direction") not in ("LEFT", "RIGHT", "UP", "DOWN"):
                return fail("invalid movement")
            if kind == "select" and (type(event.get("direction")) is not int or not 0 <= event["direction"] < world["color_count"]):
                return fail("invalid cartridge selection")
            advance(state, world, tick)
            if state["failure"] or state["rescued"]:
                return fail("input after terminal outcome")
            outcome = apply(state, world, kind, event.get("direction"))
            if event.get("outcome") != outcome:
                return fail("control outcome differs from replay")
            # The counterpart has no autonomous clock. A deliberate action
            # settles one fixed transition, then the scene remains stable
            # until the next deliberate action.
            transition_ticks = int(world.get("action_transition_ticks", DEFAULT_ACTION_TRANSITION_TICKS))
            planned_settle = min(world["max_ticks"], state["tick"] + transition_ticks) if state["started"] else state["tick"]
            advance(state, world, planned_settle)
            settle_tick = event.get("settle_tick")
            if type(settle_tick) is not int or settle_tick != state["tick"]:
                return fail("settle time does not equal the fixed action transition")
            if state["failure"] or state["rescued"]:
                # A failed pulse is a valid terminal endpoint for the action;
                # it is not a license for another event.
                continue
        final_tick = payload["final_tick"]
        if type(final_tick) is not int or final_tick != state["tick"]:
            return fail("final time must equal the last settled action tick")
        reached = state["player"] == world["resident"] and len(state["cleared"]) == len(world["fires"]) and state["pulse"] is None
        if payload.get("completed") is True and reached and not state["failure"]:
            state["rescued"] = True
        if payload.get("final_state") != snapshot(state):
            return fail("final state disagrees with replay")
        passed = state["rescued"] and state["started"] and not state["failure"]
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"{len(state['cleared'])}/{len(world['fires'])} fronts contained; " +
                    ("resident rescued" if passed else state["failure"] or "resident not reached"))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return fail("malformed firewatch transcript: " + str(exc))


def cheat(public_state, ground_truth):
    return dict(answers=[], instruction="Read recent fire motion, intercept cores with water pulses, then use clear ladders.")
