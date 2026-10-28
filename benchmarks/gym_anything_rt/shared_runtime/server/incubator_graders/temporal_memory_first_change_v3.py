"""Independent replay of lens motion, change identity and optical exposure.

This module is standalone for the existing Pyodide exporter. It does not trust
reported carrier hits, lens locations, charge, completion, or failure flags.
"""
from __future__ import annotations

import math

MECHANIC_ID = "temporal_memory_first_change_v3"
REVISION = "live-evidence-optical-inspection-v3"


def noise(seed, index):
    x = (seed ^ ((index + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def integral(seed, milliseconds, span):
    u = max(0, milliseconds) / span
    n = math.floor(u)
    f = u - n
    total = sum((noise(seed, i) + noise(seed, i + 1)) / 2 for i in range(n))
    a, b = noise(seed, n), noise(seed, n + 1)
    return span * (total + a * f + (b - a) * (f**3 - f**4 / 2))


def reflect(value, lo, hi):
    width = hi - lo
    z = (value - lo) % (2 * width)
    return lo + (z if z <= width else 2 * width - z)


def carrier_position(world, carrier, milliseconds):
    p, bounds = world["parameters"], world["bounds"]
    sx = p["speed"] * (milliseconds + .22 * integral(carrier["seed_x"], milliseconds, p["motion_span_ms"])) / 1000
    sy = p["speed"] * .58 * (milliseconds + .32 * integral(carrier["seed_y"], milliseconds, p["motion_span_ms"] + 700)) / 1000
    return [reflect(carrier["x0"] + carrier["direction_x"]*sx, bounds[0], bounds[1]),
            reflect(carrier["y0"] + carrier["direction_y"]*sy, bounds[2], bounds[3])]


def initial_state(world):
    return dict(tick=0, active=False, lenses=[dict(position=list(point), velocity=[0., 0.], target=list(point), bound=None)
        for point in world["initial_lenses"]], charge=0., terminal="", failed="", selected=0, hold=None, discoveries={})


def inspect_lens(state, world, index):
    """Read only fully framed negatives; no future information or probe quota.

    The film records each carrier's reversal. A later optical inspection can
    recover that past fact without replaying or stopping the moving world.
    Empty inspections and re-inspection are noncommitting information probes.
    """
    milliseconds = state["tick"] * 20
    lens = state["lenses"][index]
    revealed = []
    for carrier in world["carriers"]:
        if math.dist(lens["position"], carrier_position(world, carrier, milliseconds)) + carrier["radius"] > world["parameters"]["lens_radius"] + 1e-8:
            continue
        change = next(e for e in world["changes"] if e["object_id"] == carrier["id"])
        state["discoveries"][carrier["id"]] = dict(pattern=carrier["pattern"], inspected_at_ms=milliseconds,
            reversal_at_ms=change["at_ms"] if milliseconds >= change["at_ms"] else None)
        revealed.append(carrier["id"])
    return revealed


def advance(state, world, target_tick):
    if not state["active"]:
        if target_tick != 0:
            raise ValueError("unstarted film cannot advance")
        return
    p = world["parameters"]
    while state["tick"] < target_tick and not state["terminal"]:
        state["tick"] += 1
        for lens in state["lenses"]:
            acceleration = [(lens["target"][i]-lens["position"][i])*45-lens["velocity"][i]*world["camera_damping"] for i in range(2)]
            length = math.hypot(*acceleration)
            if length > p["camera_acceleration"]:
                acceleration = [v*p["camera_acceleration"]/length for v in acceleration]
            lens["velocity"] = [v+a*.02 for v, a in zip(lens["velocity"], acceleration)]
            length = math.hypot(*lens["velocity"])
            if length > p["camera_speed"]:
                lens["velocity"] = [v*p["camera_speed"]/length for v in lens["velocity"]]
            for i in range(2):
                lens["position"][i] = max(0, min(world[["width", "height"][i]], lens["position"][i]+lens["velocity"][i]*.02))
        framed = all(lens["bound"] is not None for lens in state["lenses"])
        if framed:
            objects = {o["id"]: o for o in world["carriers"]}
            framed = all(math.dist(lens["position"], carrier_position(world, objects[lens["bound"]], state["tick"]*20)) + objects[lens["bound"]]["radius"] <= p["lens_radius"] + 1e-8 for lens in state["lenses"])
        state["charge"] = min(world["exposure_ms"], max(0., state["charge"] + (20 if framed else -20*world["exposure_loss_rate"])))
        if state["charge"] >= world["exposure_ms"]:
            state["terminal"] = "pass"
        elif state["tick"]*20 >= world["max_ms"]:
            state["failed"] = "film exhausted"
            state["terminal"] = "fail"


def point(value, world):
    if not isinstance(value, list) or len(value) != 2 or any(type(v) not in {int, float} or not math.isfinite(v) for v in value):
        raise ValueError("invalid pointer point")
    if not 0 <= value[0] <= world["width"] or not 0 <= value[1] <= world["height"]:
        raise ValueError("point outside scene")
    return value


def apply(state, world, event, interaction, target_ids):
    kind = event.get("kind")
    if state["terminal"]:
        raise ValueError("input after terminal result")
    source = event.get("input_source")
    if kind == "start":
        if source != "start_button" or state["active"]:
            raise ValueError("invalid film start")
        state["active"] = True
    elif kind in {"drag_start", "drag_move", "drag_end", "aim", "select"}:
        if source != ("lens_drag" if interaction == "full" else "lens_controls"):
            raise ValueError("wrong lens interaction surface")
        index = event.get("lens")
        if type(index) is not int or not 0 <= index < len(state["lenses"]):
            raise ValueError("unknown lens")
        lens = state["lenses"][index]
        if kind == "select":
            if interaction != "simplified":
                raise ValueError("proxy lens selector in full mode")
            state["selected"] = index
            return
        xy = point(event.get("point"), world)
        if kind == "drag_start":
            if interaction != "full" or state["hold"] is not None or math.dist(xy, lens["position"]) > world["parameters"]["lens_radius"]:
                raise ValueError("drag must start on the physical lens")
            closest = min(range(len(state["lenses"])), key=lambda i: (math.dist(xy, state["lenses"][i]["position"]), i))
            if index != closest:
                raise ValueError("drag must select the closest physical lens")
            state["hold"] = index
            state["selected"] = index
        elif kind in {"drag_move", "drag_end"}:
            if interaction != "full" or state["hold"] != index:
                raise ValueError("no matching held lens")
            if kind == "drag_end":
                state["hold"] = None
            else:
                lens["target"] = list(xy)
        elif kind == "aim":
            if interaction != "simplified" or state["selected"] != index:
                raise ValueError("aim through the selected proxy lens")
            lens["target"] = list(xy)
    elif kind == "inspect":
        if source != ("lens_inspection" if interaction == "full" else "inspect_button"):
            raise ValueError("wrong inspection surface")
        index = event.get("lens")
        if type(index) is not int or not 0 <= index < len(state["lenses"]):
            raise ValueError("unknown inspection lens")
        if interaction == "full":
            xy = point(event.get("point"), world)
            closest = min(range(len(state["lenses"])), key=lambda i: (math.dist(xy, state["lenses"][i]["position"]), i))
            if closest != index or math.dist(xy, state["lenses"][index]["position"]) > world["parameters"]["lens_radius"]:
                raise ValueError("inspect through the physical lens")
        state["selected"] = index
        inspect_lens(state, world, index)
    elif kind == "bind":
        if not state["active"] or source != ("space_key" if interaction == "full" else "bind_button"):
            raise ValueError("wrong binding surface or film not started")
        index = event.get("lens")
        if type(index) is not int or index != state["selected"] or state["lenses"][index]["bound"] is not None:
            raise ValueError("invalid binding order")
        candidates = [(math.dist(lens_position := state["lenses"][index]["position"], carrier_position(world, o, state["tick"]*20)), o["id"])
            for o in world["carriers"]]
        distance, hit = min(candidates)
        observed = next(e for e in world["changes"] if e["object_id"] == target_ids[index])
        if distance > world["bind_radius"] or hit != target_ids[index] or state["tick"]*20 < observed["at_ms"]:
            state["terminal"] = "fail"
            state["failed"] = "wrong carrier or empty binding"
        else:
            state["lenses"][index]["bound"] = hit
    elif kind == "submit":
        if source != "certify_button":
            raise ValueError("wrong certification surface")
        state["terminal"] = "fail"
        state["failed"] = "incomplete exposure"
    else:
        raise ValueError("unknown film input")


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "revision", "task_id", "challenge_id"):
            if not ground_truth.get(key) or any(obj.get(key) != ground_truth[key] for obj in (public_state, payload)):
                return fail("stale or mismatched " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION:
            return fail("unknown mechanic revision")
        for key in ("world", "control_condition"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public/private contract mismatch: " + key)
        world = ground_truth["world"]
        targets = [e["object_id"] for e in sorted(world["changes"], key=lambda e: e["at_ms"])][:len(world["initial_lenses"])]
        if ground_truth.get("target_ids") != targets:
            return fail("invalid first-change truth")
        interaction = (ground_truth.get("control_condition") or {}).get("interaction", "full")
        if payload.get("interaction_mode") != interaction:
            return fail("interaction mismatch")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 6000:
            return fail("missing or excessive input transcript")
        state = initial_state(world)
        for sequence, event in enumerate(events, 1):
            tick = event.get("tick")
            if event.get("sequence") != sequence or type(tick) is not int or not state["tick"] <= tick <= world["max_ms"]//20:
                return fail("invalid input time or sequence")
            advance(state, world, tick)
            apply(state, world, event, interaction, targets)
        final_tick = payload.get("final_tick")
        if type(final_tick) is not int or not state["tick"] <= final_tick <= world["max_ms"]//20:
            return fail("invalid final time")
        advance(state, world, final_tick)
        reported_charge = payload.get("charge_ms")
        if type(reported_charge) not in {int, float} or not math.isfinite(reported_charge):
            return fail("reported exposure must be a finite number")
        if state["tick"] != final_tick or abs(reported_charge - state["charge"]) > .001:
            return fail("reported exposure or terminal time differs from replay")
        passed = state["terminal"] == "pass" and payload.get("completed") is True and not state["failed"]
        return dict(graded=True, passed=passed, score=100 if passed else 0,
            feedback=f"First-change exposure {state['charge']:.0f}/{world['exposure_ms']} ms; {state['failed'] or state['terminal'] or 'pending'}.")
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return fail("invalid first-change replay: " + str(exc))
