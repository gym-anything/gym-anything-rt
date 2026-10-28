"""Independent fixed-step replay of the moving carbon-copy desk.

Standalone stdlib module, also executable in the browser's Python verifier.
Client coverage, terminal flags and reported pen positions are never trusted.
"""
from __future__ import annotations

import math

MECHANIC_ID = "bureaucratic_signature_trap_v3_nonrealtime"
REVISION = "moving-carbon-v3-registration-2"
ACTION_TICKS = 5  # 5 * world.dt_ms = 100 ms per deliberate control action


def spline(knots, time_ms, span_ms):
    u = max(0, time_ms) / span_ms
    i = min(int(u), len(knots) - 2)
    f = min(1, u - i)
    a, b, c, d = (knots[max(0, i - 1)], knots[i], knots[i + 1], knots[min(len(knots) - 1, i + 2)])
    return [.5 * (2*b[j] + (-a[j]+c[j])*f + (2*a[j]-5*b[j]+4*c[j]-d[j])*f*f
                  + (-a[j]+3*b[j]-3*c[j]+d[j])*f*f*f) for j in (0, 1)]


def target(world, time_ms):
    a = spline(world["knots"], time_ms, world["params"]["knot_ms"])
    b = spline(world["drift_knots"], time_ms, world["params"]["drift_ms"])
    return [a[j] + b[j] for j in (0, 1)]


def hazard_positions(world, time_ms):
    return [spline(h["knots"], time_ms, h["span_ms"]) for h in world["hazards"]]


def transferred_aim(world, point):
    """The input is on the top sheet; replay the actual carbon displacement."""
    return [max(0, min(world[("width", "height")[j]], point[j] + world["carbon_offset"][j]))
            for j in (0, 1)]


def initial(world):
    p = target(world, 0)
    return dict(tick=0, pen=p[:], velocity=[0., 0.], aim=p[:], ink=False,
                copied=0., available=0., missing_run=0., maximum_missing_run=0.,
                terminal="", reason="", active=False)


def move_pen(world, s):
    """Kinematics do not depend on contact, copying or future task grading."""
    dt = world["dt_ms"] / 1000
    desired = [(s["aim"][j] - s["pen"][j]) / world["params"]["response_s"] for j in (0, 1)]
    length = math.hypot(*desired)
    if length > world["pen_speed"]:
        desired = [v * world["pen_speed"] / length for v in desired]
    change = [desired[j] - s["velocity"][j] for j in (0, 1)]
    length = math.hypot(*change)
    scale = min(1, world["pen_acceleration"] * dt / max(length, 1e-12))
    for j in (0, 1):
        s["velocity"][j] += change[j] * scale
        s["pen"][j] += s["velocity"][j] * dt
        s["pen"][j] = max(world["pen_radius"], min(world[("width", "height")[j]] - world["pen_radius"], s["pen"][j]))


def step(world, s):
    if not s["active"] or s["terminal"]:
        return
    previous = target(world, s["tick"] * world["dt_ms"])
    s["tick"] += 1
    t = s["tick"] * world["dt_ms"]
    p = target(world, t)
    move_pen(world, s)
    hazards = hazard_positions(world, t)
    safe = all(math.dist(p, q) > h["radius"] + world["params"]["tolerance"] + 16
               for h, q in zip(world["hazards"], hazards))
    if s["ink"] and any(math.dist(s["pen"], q) <= h["radius"] + world["pen_radius"]
                         for h, q in zip(world["hazards"], hazards)):
        s["terminal"], s["reason"] = "fail", "INK TOUCHED A VOID STAMP"
        return
    distance = math.dist(p, previous)
    if safe:
        s["available"] += distance
        if s["ink"] and math.dist(s["pen"], p) <= world["params"]["tolerance"]:
            s["copied"] += distance
            s["missing_run"] = 0.
        else:
            s["missing_run"] += distance
            s["maximum_missing_run"] = max(s["maximum_missing_run"], s["missing_run"])
            if s["missing_run"] > world["params"]["maximum_gap"]:
                s["terminal"], s["reason"] = "fail", "UNCOPIED STROKE TOO LONG"
                return
    else:
        # The visible excluded VOID region legitimately interrupts the stroke.
        s["missing_run"] = 0.
    if t >= world["params"]["duration_ms"]:
        passed = s["available"] > 0 and s["copied"] / s["available"] >= world["params"]["minimum_coverage"]
        s["terminal"] = "pass" if passed else "fail"
        s["reason"] = "ORIGINAL COUNTERSIGNED" if passed else "INCOMPLETE CARBON COPY"


def advance(world, s, tick):
    while s["tick"] < tick and not s["terminal"]:
        step(world, s)


def advance_action(world, s):
    """Advance one fixed, action-triggered transition; wall time is irrelevant."""
    end = world["params"]["duration_ms"] // world["dt_ms"]
    advance(world, s, min(s["tick"] + ACTION_TICKS, end))


def apply(world, s, event):
    kind = event["kind"]
    if kind == "start":
        if s["active"] or s["terminal"] or event["tick"] != 0:
            raise ValueError("restarting cannot erase this attempt")
        s["active"] = True
    elif kind == "aim":
        point = event["point"]
        if not isinstance(point, list) or len(point) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in point):
            raise ValueError("invalid pen target")
        if not 0 <= point[0] <= world["width"] or not 0 <= point[1] <= world["height"]:
            raise ValueError("pen target outside the desk")
        s["aim"] = transferred_aim(world, point)
    elif kind == "inspect_carbon":
        distance = event.get("pull_px")
        if type(distance) not in (int, float) or not math.isfinite(distance) or not 0 < distance <= world["width"]:
            raise ValueError("invalid carbon inspection distance")
        # Information-only inspection. No quota or change to physics/eligibility.
    elif kind == "ink":
        if type(event["down"]) is not bool:
            raise ValueError("invalid pen contact")
        s["ink"] = event["down"]
        if s["ink"] and any(math.dist(s["pen"], q) <= h["radius"] + world["pen_radius"]
                            for h, q in zip(world["hazards"], hazard_positions(world, s["tick"] * world["dt_ms"]))):
            s["terminal"], s["reason"] = "fail", "INK TOUCHED A VOID STAMP"
    elif kind == "certify":
        if not s["terminal"]:
            s["terminal"], s["reason"] = "fail", "SUBMITTED BEFORE COPY FINISHED"
    else:
        raise ValueError("unknown control")


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(value, dict) for value in (payload, ground_truth, public_state)):
            return fail("invalid carbon-copy result object")
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or ground_truth[key] != payload.get(key) or public_state.get(key) != ground_truth[key]:
                return fail("stale or wrong " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION:
            return fail("unsupported revision")
        if ground_truth["world"] != public_state.get("world") or ground_truth.get("control_condition") != public_state.get("control_condition"):
            return fail("generated world or condition mismatch")
        mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        world = ground_truth["world"]
        events = payload.get("events")
        if not isinstance(events, list) or not 2 <= len(events) <= 12000:
            return fail("missing or excessive input trace")
        s = initial(world)
        sources = {"start": "start_button", "certify": "certify_button",
                   "inspect_carbon": "carbon_registration_tab",
                   "aim": "pen_pointer" if mode == "full" else "pen_position_proxy",
                   "ink": "pen_contact" if mode == "full" else "ink_proxy"}
        certified = False
        end = world["params"]["duration_ms"] // world["dt_ms"]
        i = 0
        while i < len(events):
            e = events[i]
            if not isinstance(e, dict):
                return fail("invalid control event")
            tick = e.get("tick")
            kind = e.get("kind")
            if type(tick) is not int or not 0 <= tick <= end or e.get("sequence") != i + 1:
                return fail("invalid event order or task time")
            if e.get("input_source") != sources.get(kind):
                return fail("wrong input surface")
            if certified or (s["terminal"] and kind != "certify"):
                return fail("terminal attempt cannot be revised")
            if kind == "inspect_carbon":
                # Peeling is an information-only control. It is allowed before
                # START and does not consume a fixed feed quantum.
                if tick != s["tick"] or (not s["active"] and tick != 0):
                    return fail("inspection cannot advance task time")
                apply(world, s, e)
                i += 1
                continue
            if kind == "start":
                if s["active"] or s["terminal"] or tick != s["tick"] or tick != 0:
                    return fail("restarting cannot erase this attempt")
                apply(world, s, e)
                advance_action(world, s)
                i += 1
                continue
            if not s["active"] and kind not in ("certify",):
                return fail("input before the copy feed started")
            if kind == "certify":
                if s["terminal"]:
                    if tick != s["tick"]:
                        return fail("terminal certification must use the current task time")
                    apply(world, s, e)
                    certified = True
                    i += 1
                    continue
                if not s["active"]:
                    if tick != 0:
                        return fail("task time cannot advance before START FEED")
                    apply(world, s, e)
                    certified = True
                    i += 1
                    continue
                expected = min(s["tick"] + ACTION_TICKS, end)
                if tick != expected:
                    return fail("non-real-time actions must advance exactly one fixed quantum")
                advance(world, s, tick)
                apply(world, s, e)
                certified = True
                i += 1
                continue

            if kind not in ("aim", "ink") or tick != s["tick"]:
                return fail("non-real-time actions must advance exactly one fixed quantum")

            # Native full-mode pointer-down emits aim and contact together at
            # one task boundary. Treat that pair as one deliberate action.
            paired = (
                mode == "full" and kind == "aim" and i + 1 < len(events)
                and isinstance(events[i + 1], dict)
                and events[i + 1].get("kind") == "ink"
                and events[i + 1].get("tick") == tick
            )
            if paired:
                contact = events[i + 1]
                if contact.get("sequence") != i + 2 or contact.get("input_source") != sources["ink"]:
                    return fail("invalid same-action pointer contact")
                apply(world, s, e)
                apply(world, s, contact)
                advance_action(world, s)
                i += 2
            else:
                apply(world, s, e)
                advance_action(world, s)
                i += 1
        if type(payload.get("final_tick")) is not int or payload["final_tick"] != s["tick"]:
            return fail("wrong final task time")
        passed = certified and s["terminal"] == "pass"
        coverage = s["copied"] / max(s["available"], 1e-9)
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f'{s["reason"] or "UNFINISHED"}; copied {coverage:.1%} of unobstructed original',
                    coverage=coverage, replay=s)
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as exc:
        return fail("invalid carbon-copy transcript: " + str(exc))
