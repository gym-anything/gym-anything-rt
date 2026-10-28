"""Independent fixed-step replay; never accepts a client-reported placement."""
from __future__ import annotations

import math

MECHANIC_ID = "motion_only_ghost_jigsaw_nonrealtime"
REVISION = "drifting-loom-v3"


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0, ms)/span
    n, f = math.floor(u), u % 1
    a, b = noise(seed, n), noise(seed, n+1)
    return a+(b-a)*f*f*(3-2*f)


def derivative(seed, ms, span):
    u = max(0, ms)/span
    n, f = math.floor(u), u % 1
    return (noise(seed, n+1)-noise(seed, n))*6*f*(1-f)*1000/span


def socket_pose(contract, index, tick):
    slot, p = contract["slots"][index], contract["profile"]
    ms = tick*contract["tick_ms"]
    seed, span = slot["motion_seed"], p["drift_span_ms"]
    return dict(x=slot["base"][0]+p["drift_px"]*motion(seed, ms, span),
                y=slot["base"][1]+p["drift_px"]*motion(seed+7919, ms, span),
                angle=p["angle_amplitude"]*motion(seed+15838, ms, span),
                vx=p["drift_px"]*derivative(seed, ms, span),
                vy=p["drift_px"]*derivative(seed+7919, ms, span),
                omega=p["angle_amplitude"]*derivative(seed+15838, ms, span))


def angle_error(a, b):
    return (a-b+180) % 360-180


def initial_state(contract):
    return dict(tick=0, running=False, terminal=False, failed=False,
                held=None, target=None, turn=0, placed={}, misses=0,
                pieces={p["id"]:dict(x=p["home"][0], y=p["home"][1],
                                     angle=p["angle"], vx=0., vy=0.) for p in contract["pieces"]})


def advance(state, contract, target):
    if not state["running"]:
        if target != 0:
            raise ValueError("pre-run task cannot advance")
        return
    if target < state["tick"] or target > contract["max_time_ms"]//contract["tick_ms"]:
        raise ValueError("task tick outside the episode")
    p, dt = contract["profile"], contract["tick_ms"]/1000
    while state["tick"] < target and not state["terminal"]:
        if state["held"]:
            body = state["pieces"][state["held"]]
            for axis, vaxis, index in (("x", "vx", 0), ("y", "vy", 1)):
                force = p["current_force"]*motion(contract["current_seed"]+index*7919,
                                                 state["tick"]*contract["tick_ms"], 2100)
                body[vaxis] += (p["spring"]*(state["target"][index]-body[axis])-p["damping"]*body[vaxis]+force)*dt
            speed = math.hypot(body["vx"], body["vy"])
            if speed > p["max_speed"]:
                body["vx"] *= p["max_speed"]/speed
                body["vy"] *= p["max_speed"]/speed
            for axis, vaxis, limit in (("x", "vx", 970), ("y", "vy", 560)):
                body[axis] += body[vaxis]*dt
                if not 40 <= body[axis] <= limit-40:
                    body[axis] = max(40, min(limit-40, body[axis]))
                    body[vaxis] = 0.
            body["angle"] = (body["angle"]+state["turn"]*contract["rotation_speed"]*dt+180) % 360-180
        state["tick"] += 1
        if state["tick"] >= contract["max_time_ms"]//contract["tick_ms"]:
            state.update(terminal=True, failed=True)


def advance_action(state, contract):
    """Advance only the fixed transition caused by the current input."""
    step = contract.get("action_step_ticks")
    if type(step) is not int or step <= 0:
        raise ValueError("invalid action transition step")
    advance(state, contract, min(contract["max_time_ms"] // contract["tick_ms"], state["tick"] + step))


def hit_piece(body, point, size):
    angle = math.radians(body["angle"])
    x, y = point[0]-body["x"], point[1]-body["y"]
    return abs(x*math.cos(angle)+y*math.sin(angle)) <= size/2 and abs(-x*math.sin(angle)+y*math.cos(angle)) <= size/2


def apply_event(state, contract, event):
    """Apply canonical primitives, with each interaction surface explicitly bound."""
    kind = event["kind"]
    mode = contract["control_condition"]["interaction"]
    surfaces = {"full": {"grab":"drag", "aim":"drag", "turn":"keys", "drop":"release", "cancel":"drag"},
                "simplified": {"grab":"select", "aim":"point", "turn":"buttons", "drop":"stitch", "cancel":"button"}}
    source = "button" if kind == "start" else surfaces[mode].get(kind)
    if event.get("input_source") != source or source is None or state["terminal"]:
        raise ValueError("wrong input surface or terminal action")
    if kind == "start":
        if state["running"] or event["tick"] != 0:
            raise ValueError("duplicate or late start")
        state["running"] = True
        return
    if not state["running"]:
        raise ValueError("no pre-run placements")
    if kind in ("grab", "aim"):
        point = event.get("point")
        if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point):
            raise ValueError("invalid pointer point")
        if not 0 <= point[0] <= 970 or not 0 <= point[1] <= 560:
            raise ValueError("pointer outside loom")
        if kind == "grab":
            piece = event.get("piece_id")
            if state["held"] or piece not in state["pieces"] or piece in state["placed"] or not hit_piece(state["pieces"][piece], point, contract["piece_size"]):
                raise ValueError("piece was not grabbed through its visible geometry")
            state["held"] = piece
            # Off-centre pickup cannot teleport a fragment. The aim point is
            # its centre; both controls use the exact same centre convention.
            state["target"] = [state["pieces"][piece]["x"], state["pieces"][piece]["y"]]
        elif not state["held"]:
            raise ValueError("aim without fragment")
        else:
            state["target"] = point
            advance_action(state, contract)
            return
    elif kind == "turn":
        direction = event.get("direction")
        if type(direction) is not int or direction not in (-1,0,1):
            raise ValueError("invalid angular control")
        state["turn"] = direction
        advance_action(state, contract)
        return
    elif kind in ("drop", "cancel"):
        if not state["held"]:
            raise ValueError("no held fragment")
        piece = state["held"]
        body = state["pieces"][piece]
        candidates = []
        if kind == "drop":
            for i in range(len(contract["slots"])):
                if i in state["placed"].values():
                    continue
                pose = socket_pose(contract, i, state["tick"])
                if (math.hypot(body["x"]-pose["x"], body["y"]-pose["y"]) <= contract["profile"]["position_tolerance"]+1e-7
                    and abs(angle_error(body["angle"], pose["angle"])) <= contract["profile"]["angle_tolerance"]+1e-7):
                    candidates.append(i)
        if candidates:
            slot = candidates[0]
            if contract["expected_positions"].get(piece) != slot:
                state.update(terminal=True, failed=True)
            else:
                state["placed"][piece] = slot
        else:
            state["misses"] += int(kind == "drop")
            if kind == "drop":
                state.update(terminal=True, failed=True)
            else:
                original = next(p for p in contract["pieces"] if p["id"] == piece)
                body.update(x=original["home"][0], y=original["home"][1], vx=0., vy=0.)
        state.update(held=None, target=None)
        if len(state["placed"]) == len(contract["pieces"]):
            state["terminal"] = True
    else:
        raise ValueError("unknown game action")


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not isinstance(payload, dict):
            return fail("submission must be an object")
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or wrong "+key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION:
            return fail("wrong loom revision")
        for key in ("profile", "stage", "piece_size", "slots", "pieces", "glyphs", "current_seed", "tick_ms", "rotation_speed", "max_time_ms", "action_step_ticks", "control_condition"):
            if ground_truth.get(key) != public_state.get(key):
                return fail("render/replay contract mismatch: "+key)
        mode = ground_truth["control_condition"]["interaction"]
        if payload.get("interaction_mode") != mode:
            return fail("wrong interaction")
        events = payload.get("events")
        if not isinstance(events,list) or not 1 <= len(events) <= ground_truth["max_events"]:
            return fail("missing or excessive action trace")
        state = initial_state(ground_truth)
        for sequence, event in enumerate(events,1):
            if not isinstance(event, dict) or event.get("sequence") != sequence or type(event.get("tick")) is not int:
                return fail("invalid sequence or tick")
            if event["tick"] != state["tick"]:
                return fail("waiting cannot advance the action clock")
            advance(state,ground_truth,event["tick"])
            apply_event(state,ground_truth,event)
        final = payload.get("final_tick")
        if type(final) is not int:
            return fail("missing final tick")
        if final != state["tick"]:
            return fail("final tick contains uncaused autonomous progress")
        advance(state,ground_truth,final)
        if state["failed"] or payload.get("failed") is not False:
            return fail("wrong stitch or expired episode")
        if payload.get("placements") != state["placed"] or payload.get("misses") != state["misses"]:
            return fail("reported outcome disagrees with independent replay")
        passed = len(state["placed"]) == len(ground_truth["pieces"]) and payload.get("completed") is True and state["held"] is None
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback="Ghost loom replay: "+str(len(state["placed"]))+"/"+str(len(ground_truth["pieces"]))+" fragments stitched")
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as exc:
        return fail("invalid loom transcript: "+str(exc))


def cheat(public_state, ground_truth):
    return {"positions":ground_truth.get("expected_positions",{})}
