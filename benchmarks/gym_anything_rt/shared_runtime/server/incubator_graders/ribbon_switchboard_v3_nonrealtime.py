"""Independent fixed-step replay of the visible ribbon and servo geometry.

No client-reported heat, terminal, contact position or success is accepted.
Standalone imports support the existing Pyodide export contract.
"""
from __future__ import annotations

import math

MECHANIC_ID = "ribbon_switchboard_v3_nonrealtime"


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def wind(ribbon, t, p):
    u = (t + ribbon["phase_ms"]) / p["wind_span_ms"]
    i = math.floor(u)
    f = u - i
    return noise(ribbon["wind_seed"], i) + (noise(ribbon["wind_seed"], i+1) - noise(ribbon["wind_seed"], i)) * f*f*(3-2*f)


def ribbon_y(ribbon, x, t, p):
    z = clamp(x, 0, 1) * (len(ribbon["knots"])-1)
    i = min(len(ribbon["knots"])-2, math.floor(z))
    f = z-i
    base = ribbon["knots"][i] + (ribbon["knots"][i+1]-ribbon["knots"][i]) * f*f*(3-2*f)
    # Fixed anchors and continuous, nonperiodic, independently changing wind.
    return base + p["amplitude"] * math.sin(math.pi*x) * wind(ribbon, t, p)


def initial(state):
    return [dict(y=l["ribbons"][l["target"]]["knots"][0],
                 aim=l["ribbons"][l["target"]]["knots"][0], v=0., heat=0., peak=0.)
            for l in state["lanes"]]


def tick(state, bodies, t):
    p = state["parameters"]
    dt = state["step_ms"]/1000
    x = min(1., t/p["travel_ms"])
    for lane, b in zip(state["lanes"], bodies):
        # Damped actuator; the click/drag changes only its setpoint.
        desired = clamp((b["aim"]-b["y"])*6, -130, 130)
        b["v"] += clamp(desired-b["v"], -520*dt, 520*dt) * min(1., state["step_ms"]/p["servo_tau_ms"]*4)
        b["y"] = clamp(b["y"]+b["v"]*dt, -72, 72)
        error = abs(b["y"]-ribbon_y(lane["ribbons"][lane["target"]], x, t, p))
        b["heat"] = max(0., b["heat"] + state["step_ms"] * (1 if error > p["tolerance"] else -2))
        b["peak"] = max(b["peak"], b["heat"])
        if b["heat"] >= p["burn_ms"]:
            return lane["id"]
    return None


def replay(state, events, final_t):
    mode = (state.get("control_condition") or {}).get("interaction", "full")
    p = state["parameters"]
    bodies, t, held, started = initial(state), 0, None, False
    step = state["step_ms"]
    action_step = state["action_step_ms"]

    def advance(end):
        nonlocal t
        while t < end:
            t += step
            burned = tick(state, bodies, t)
            if burned is not None:
                raise ValueError(f"terminal burn in lane {burned+1} at {t} ms")

    def point(value, inspecting=False):
        if not isinstance(value, list) or len(value) != 2 or any(type(a) not in (int,float) or not math.isfinite(a) for a in value):
            raise ValueError("malformed point")
        lo, hi = (140, 1040) if inspecting else (14, 74)
        if not lo <= value[0] <= hi or not -72 <= value[1] <= 72:
            raise ValueError("point outside visible weave" if inspecting else "point outside visible servo rail")
        return value

    for i, e in enumerate(events, 1):
        if not isinstance(e, dict):
            raise ValueError("malformed event")
        et = e.get("t_ms")
        if type(et) is not int or et % step or not 0 <= et <= p["travel_ms"] or e.get("sequence") != i:
            raise ValueError("invalid time or sequence")
        if e.get("input_source") != mode:
            raise ValueError("wrong interaction input surface")
        if e.get("kind") == "inspect":
            if held is not None or (not started and et != 0) or (started and et != t):
                raise ValueError("invalid inspection boundary")
            lane = e.get("lane")
            if type(lane) is not int or not 0 <= lane < len(bodies):
                raise ValueError("invalid inspection lane")
            point(e.get("point"), inspecting=True)
            # A pre-energize probe is free. During a run, the deliberate probe
            # is an input action and settles one fixed slice just like a
            # completed rail adjustment; idle time never advances the loom.
            if started:
                advance(min(t + action_step, p["travel_ms"]))
            continue
        if not started:
            if e.get("kind") != "start" or et != 0:
                raise ValueError("first action must start this loom")
            started = True
            continue
        if et != t:
            raise ValueError("action was delivered after an unrecorded transition")
        lane = e.get("lane")
        if type(lane) is not int or not 0 <= lane < len(bodies):
            raise ValueError("invalid lane")
        b, kind = bodies[lane], e.get("kind")
        q = point(e.get("point"))
        if mode == "simplified":
            if kind != "click" or held is not None:
                raise ValueError("simplified input must click the rail")
            b["aim"] = q[1]
            advance(min(t + action_step, p["travel_ms"]))
        elif kind == "down":
            if held is not None or math.hypot(q[0]-44, q[1]-b["aim"]) > 22:
                raise ValueError("drag must begin on the visible setpoint knob")
            held = lane
        elif kind in ("move", "up"):
            if held != lane:
                raise ValueError("drag is not held in this lane")
            b["aim"] = q[1]
            if kind == "up":
                held = None
                advance(min(t + action_step, p["travel_ms"]))
        else:
            raise ValueError("reset or unsupported control")
    if not started or type(final_t) is not int or final_t % step or not 0 <= final_t <= p["travel_ms"]:
        raise ValueError("invalid final time")
    if final_t != t:
        raise ValueError("final time does not match action-triggered replay")
    return dict(bodies=bodies, complete=final_t == p["travel_ms"], t_ms=t)


def grade(payload, ground_truth, public_state):
    def fail(msg):
        return dict(graded=True, passed=False, score=0, feedback=msg)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or wrong " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("lanes", "parameters", "stage", "step_ms", "action_step_ms", "inspection", "control_condition"):
            if ground_truth.get(key) != public_state.get(key):
                return fail("world or control mismatch: " + key)
        mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
        if payload.get("interaction_mode") != mode:
            return fail("wrong interaction")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 6000:
            return fail("missing or excessive primitive input record")
        outcome = replay(ground_truth, events, payload.get("final_t_ms"))
        if payload.get("completed") is not True or not outcome["complete"]:
            return fail("loom did not reach every terminal")
        return dict(graded=True, passed=True, score=100, feedback="All ribbon contacts survived independent servo replay.",
                    peak_heat_ms=[round(b["peak"]) for b in outcome["bodies"]])
    except (ValueError, KeyError, TypeError, OverflowError) as e:
        return fail(str(e))
