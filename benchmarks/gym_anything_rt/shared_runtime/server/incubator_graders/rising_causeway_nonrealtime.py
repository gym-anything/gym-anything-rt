"""Independent fixed-step replay of action-stepped support and contact.

No client completion, ticks, landing coordinates or collision claims are
accepted as truth. This file is standalone for the existing Pyodide export.
"""
from __future__ import annotations

import math

MECHANIC_ID = "rising_causeway_nonrealtime"
TIMING_MODE = "action_step"
ACTION_KINDS = {"steer", "aim", "launch"}


def allows_episode_retries(ground_truth, public_state):
    """The audited ten configurations, derived from the bound replay world.

    The browser's policy flag never grants eligibility. Unknown versions or
    configurations retain first-failure rejection until separately assessed.
    Per-attempt terminal physics and transcript validation remain in grade().
    """
    world = ground_truth.get("world") or {}
    condition = ground_truth.get("control_condition") or {}
    difficulty = condition.get("difficulty", 5)
    mode = condition.get("interaction", "full")
    return (
        ground_truth.get("mechanic_id") == MECHANIC_ID
        and public_state.get("mechanic_id") == MECHANIC_ID
        and world.get("revision") == "visible-contact-measurements-v5"
        and world.get("timing_mode") == TIMING_MODE
        and world.get("action_step_ms") == 400
        and world.get("launch_settle_ms") == 2400
        and world == public_state.get("world")
        and ground_truth.get("control_condition") == public_state.get("control_condition")
        and type(difficulty) is int and difficulty in range(1, 6)
        and mode in ("full", "simplified")
    )


def noise(seed, index):
    value = (int(seed) ^ ((index + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    value = ((value ^ (value >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    value = ((value ^ (value >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((value ^ (value >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(seed, milliseconds, span):
    u = max(0, milliseconds) / span
    index = int(u)
    f = u - index
    a, b = noise(seed, index), noise(seed, index + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def centres(world, time):
    p = world["parameters"]
    return [world["motion_offsets"][i] + p["sway"] * motion(world["motion_seeds"][i], time, p["span_ms"] + i * 731) for i in range(3)]


def wind(world, time):
    return world["parameters"]["wind"] * motion(world["motion_seeds"][3], time, 3100)


def bend(world, x):
    u = min(1.999999, max(0, (x - world["landing_start"]) / (world["end_x"] - world["landing_start"]) * 2))
    i, f = int(u), u % 1
    a, b = world["bend_points"][i:i + 2]
    return world["parameters"]["bend"] * (a + (b - a) * f * f * (3 - 2 * f))


def support(world, s, x, time):
    """Centre, half width, surface height, kind; top mesh equals collision."""
    p, c = world["parameters"], centres(world, time)
    if 0 <= x < world["red_start"]:
        return 0.0, 2.4, 0.0, "apron"
    if world["red_start"] <= x < world["red_end"]:
        if x > world["red_start"] + s["red"] * 2:
            return None
        f = (x - world["red_start"]) / 6
        return c[0] * f, p["half_width"], 0.0, "red"
    if world["red_end"] <= x < world["stair_end"]:
        f = (x - world["red_end"]) / 6
        if s["stair"] is None:
            return None
        # Each of the three pillars has an integral approach ramp. There is
        # no invisible traversable surface over an unraised stair.
        height = p["stair_height"] * (f if s["stair"] == "far" else 1 - f)
        return c[0] + (c[1] - c[0]) * f, p["half_width"], height, "yellow"
    if world["stair_end"] <= x <= world["slab_end"]:
        return c[1], p["half_width"], p["stair_height"], "blue"
    if world["landing_start"] <= x <= world["end_x"] + 0.8:
        return c[2] + bend(world, x), p["landing_half_width"], p["stair_height"], "terrace"
    return None


def initial(world):
    return dict(t=0, x=world["start"][0], y=0.0, z=0.0, vx=0.0, vy=0.0, vz=0.0,
                ux=0.0, uy=0.0, red=0, stair=None, primed=False,
                active=False, flight=False, launched=False, landed=False, loaded=False, aim=0.0,
                completed=False, failed=False, reason="", launch_t=None)


def step(world, s):
    if not s["active"] or s["failed"] or s["completed"]:
        return
    p, dt = world["parameters"], world["tick_ms"] / 1000
    s["t"] += world["tick_ms"]
    if s["flight"]:
        # The wheels have no contact in flight. No later pointer operation can
        # undo a released spring impulse or change the landing trajectory.
        s["vy"] += (world["air_wind"] * wind(world, s["t"]) - world["air_drag"] * s["vy"]) * dt
    else:
        desired_speed = p["cruise"] + s["ux"] * 0.48
        s["vx"] += (desired_speed - s["vx"]) * min(1, dt * 3)
        s["vy"] += (p["steering"] * s["uy"] + wind(world, s["t"]) - p["drag"] * s["vy"]) * dt
    s["x"] += s["vx"] * dt
    s["y"] += s["vy"] * dt
    previous_z = s["z"]
    if s["flight"]:
        s["vz"] -= world["gravity"] * dt
        s["z"] += s["vz"] * dt
        if s["vz"] < 0 and s["z"] <= p["stair_height"]:
            s["flight"] = False
            s["landed"] = True
            s["z"] = p["stair_height"]
    if not s["flight"]:
        tile = support(world, s, s["x"], s["t"])
        if tile is None:
            s["failed"], s["reason"] = True, "The courier fell through a gap."
        elif abs(s["y"] - tile[0]) + world["radius"] > tile[1] + 1e-9:
            s["failed"], s["reason"] = True, "The courier rolled off the visible edge."
        elif abs(tile[2] - previous_z) > 0.24:
            s["failed"], s["reason"] = True, "The stair's high face blocked the courier."
        else:
            s["z"] = tile[2]
            s["loaded"] = not s["launched"] and tile[3] == "blue" and s["x"] >= world["launch_x"]
            if s["landed"]:
                if tile[3] == "terrace" and world["delivery_start"] + world["radius"] <= s["x"] <= world["end_x"] + .8 - world["radius"]:
                    s["completed"] = True
                else:
                    s["failed"], s["reason"] = True, "The courier missed the delivery bay."
    if s["t"] >= world["max_time_ms"] and not s["completed"]:
        s["failed"], s["reason"] = True, "The run ended."


def advance(world, s, end):
    if end % world["tick_ms"]:
        raise ValueError("action time must be a fixed-step boundary")
    while s["t"] < end and s["active"] and not (s["failed"] or s["completed"]):
        step(world, s)


def advance_after_action(world, s, event):
    """Advance only the fixed transition caused by a deliberate control.

    Idle time is intentionally absent from the transcript contract.  A spring
    release settles its finite flight in one fixed transaction; steering and
    aiming each commit one ordinary action step.
    """
    if not s["active"] or event.get("kind") not in ACTION_KINDS:
        return
    duration = world["action_step_ms"]
    if event.get("kind") == "launch" and s["launched"]:
        duration = world["launch_settle_ms"]
    advance(world, s, s["t"] + duration)


def apply(s, event, world=None):
    kind = event["kind"]
    if kind == "red":
        value = event["value"]
        if type(value) is not int or value not in (-1, 1):
            raise ValueError("red must move one extrusion stage")
        s["red"] = min(3, max(0, s["red"] + value))
    elif kind == "stair":
        if event["value"] not in ("near", "far"):
            raise ValueError("invalid high end")
        s["stair"] = event["value"]
    elif kind == "prime":
        s["primed"] = not s["primed"]
    elif kind == "steer":
        for key in ("ux", "uy"):
            value = event[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not -1 <= value <= 1:
                raise ValueError("invalid steering thrust")
            s[key] = value
    elif kind in ("aim", "launch"):
        value = event["value"]
        if type(value) not in (int, float) or not math.isfinite(value) or not -1 <= value <= 1:
            raise ValueError("invalid spring aim")
        s["aim"] = value
        if kind == "launch" and s["active"] and s["loaded"] and s["primed"] and not s["launched"]:
            if world is None:
                raise ValueError("launch requires the replay world")
            s.update(flight=True, launched=True, loaded=False, vz=world["spring_vz"], launch_t=s["t"])
            s["vx"] += world["spring_vx"]
            s["vy"] += world["spring_vy"] * value
    elif kind == "start":
        if s["active"]:
            raise ValueError("a run cannot be restarted")
        s["active"] = True
    elif kind == "submit":
        if not s["completed"]:
            s["failed"], s["reason"] = True, "The terminal has not been reached."
    elif kind == "abandon":
        s["failed"], s["reason"] = True, "The run was abandoned."
    else:
        raise ValueError("unknown action")


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if payload.get(key) != ground_truth.get(key) or public_state.get(key) != ground_truth.get(key) or not ground_truth.get(key):
                return fail("stale or incorrect " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        if ground_truth["world"] != public_state["world"] or ground_truth.get("control_condition") != public_state.get("control_condition"):
            return fail("public world or condition differs from replay")
        mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction") != mode:
            return fail("wrong interaction")
        world = ground_truth["world"]
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 20000:
            return fail("missing or excessive action trace")
        s, previous = initial(world), 0
        for seq, event in enumerate(events, 1):
            t = event["t_ms"]
            if type(t) is not int or t != s["t"] or t > world["max_time_ms"] or event.get("seq") != seq:
                return fail("invalid action order/time")
            if not s["active"] and t != 0:
                return fail("preparation cannot advance run time")
            if s["failed"]:
                return fail("terminal failure persists")
            advance(world, s, t)
            if s["failed"]:
                return fail(s["reason"])
            if s["completed"] and event["kind"] != "submit":
                return fail("input follows terminal arrival")
            if event["kind"] in ("aim", "launch"):
                expected_source = "launch_drag" if mode == "full" else "launch_click"
            else:
                expected_source = "common_button" if event["kind"] in ("start", "submit", "abandon") else ("stick_drag" if event["kind"] == "steer" and mode == "full" else "scene_click" if mode == "full" else "proxy_click")
            if event.get("input_source") != expected_source:
                return fail("action uses the other interaction surface")
            apply(s, event, world)
            advance_after_action(world, s, event)
            if s["failed"]:
                return fail(s["reason"])
            previous = t
        final_t = payload["final_t_ms"]
        if type(final_t) is not int or not previous <= final_t <= world["max_time_ms"]:
            return fail("invalid final time")
        advance(world, s, final_t)
        if s["failed"] or not s["completed"] or not s["launched"] or not s["landed"] or payload.get("completed") is not True:
            return fail(s["reason"] or "causeway traversal incomplete")
        if final_t != s["t"]:
            return fail("final time differs from terminal physics boundary")
        return dict(graded=True, passed=True, score=100, feedback="Moving support, contact spring, ballistic landing and terminal independently replayed.", terminal_state=s)
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as exc:
        return fail("invalid causeway trace: " + str(exc))


def cheat(public_state, ground_truth):
    return {"world": ground_truth.get("world"), "planning": "privileged physics data; inputs still required"}
