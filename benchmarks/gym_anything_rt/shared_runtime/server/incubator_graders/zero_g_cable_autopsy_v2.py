"""Independent fixed-step Verlet/PBD replay. Standard library only for Pyodide."""
from __future__ import annotations

import copy
import math

MECHANIC_ID = "zero_g_cable_autopsy_v2"


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(spec, ms):
    u = max(0, ms) / spec["span_ms"]
    i, f = math.floor(u), u % 1
    return spec["center"] + spec["amplitude"] * (
        noise(spec["seed"], i) + (noise(spec["seed"], i + 1) - noise(spec["seed"], i)) * f * f * (3 - 2 * f))


def closest(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    u = max(0., min(1., ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / den)) if den else 0.
    return [a[0] + u * dx, a[1] + u * dy], u


def initial_state(w):
    return dict(tick=0, nodes=copy.deepcopy(w["nodes"]), previous=copy.deepcopy(w["nodes"]),
                grips=[dict(y=210., v=0., target=210.) for _ in range(2)],
                removed=[], failed="", complete=False, started=False, energy=1.)


def collar(w, s, spec):
    u = motion(spec, s["tick"] * w["tick_ms"]) * (len(s["nodes"]) - 1)
    i = max(0, min(len(s["nodes"]) - 2, math.floor(u)))
    f = u - i
    a, b = s["nodes"][i:i + 2]
    return [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])], i


def isolated(w, s):
    return all(abs(g["y"] - motion(p, s["tick"] * w["tick_ms"])) + w["grip_radius"] <= p["radius"] + 1e-7
               for g, p in zip(s["grips"], w["ports"]))


def stretch(w, s):
    return max(math.dist(a, b) / r for a, b, r in zip(s["nodes"], s["nodes"][1:], w["rest_lengths"]))


def _constraint(nodes, i, j, rest, strength=1.):
    a, b = nodes[i], nodes[j]
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy)
    if d < 1e-10:
        return
    wa, wb = int(i != 0), int(j != len(nodes) - 1)
    if not wa + wb:
        return
    q = (d - rest) / d * strength / (wa + wb)
    if wa:
        a[0] += dx * q
        a[1] += dy * q
    if wb:
        b[0] -= dx * q
        b[1] -= dy * q


def _peg(nodes, peg, radius):
    center = [peg["x"], peg["y"]]
    for i in range(len(nodes) - 1):
        p, f = closest(center, nodes[i], nodes[i + 1])
        dx, dy = p[0] - center[0], p[1] - center[1]
        d = math.hypot(dx, dy)
        if d >= radius:
            continue
        if d < 1e-10:
            dx, dy, d = 0., 1., 1.
        wa = (1 - f) if i > 0 else 0.
        wb = f if i + 1 < len(nodes) - 1 else 0.
        if wa + wb < 1e-9:
            continue
        scale = (radius - d) / d / (wa * wa + wb * wb)
        nodes[i][0] += dx * scale * wa
        nodes[i][1] += dy * scale * wa
        nodes[i + 1][0] += dx * scale * wb
        nodes[i + 1][1] += dy * scale * wb


def step(w, s):
    if not s["started"] or s["failed"] or s["complete"]:
        return
    dt = w["tick_ms"] / 1000
    s["tick"] += 1
    for g in s["grips"]:
        a = max(-w["servo_acceleration"], min(w["servo_acceleration"],
                    w["servo_gain"] ** 2 * (g["target"] - g["y"]) - 2 * w["servo_gain"] * g["v"]))
        g["v"] = max(-w["servo_speed"], min(w["servo_speed"], g["v"] + dt * a))
        g["y"] = max(w["rail_bounds"][0], min(w["rail_bounds"][1], g["y"] + dt * g["v"]))
    nodes = s["nodes"]
    old = copy.deepcopy(nodes)
    force = motion(dict(seed=w["flow_seed"], center=0, amplitude=w["parameters"]["flow_acceleration"], span_ms=2300), s["tick"] * w["tick_ms"])
    for i in range(1, len(nodes) - 1):
        nodes[i][0] += (nodes[i][0] - s["previous"][i][0]) * w["damping"]
        nodes[i][1] += (nodes[i][1] - s["previous"][i][1]) * w["damping"] + force * dt * dt
    nodes[0] = [w["ports"][0]["x"], s["grips"][0]["y"]]
    nodes[-1] = [w["ports"][1]["x"], s["grips"][1]["y"]]
    active = [c for c in w["collars"] if c["id"] not in s["removed"]]
    braces = {collar(w, s, c)[1] for c in active}
    for _ in range(w["constraint_iterations"]):
        for i, r in enumerate(w["rest_lengths"]):
            _constraint(nodes, i, i + 1, r)
        for i in braces:
            if i + 2 < len(nodes):
                _constraint(nodes, i, i + 2, w["bend_lengths"][i], w["clamp_stiffness"])
        _peg(nodes, w["peg"], w["peg"]["radius"] + w["cable_radius"])
    for node in nodes[1:-1]:
        node[0] = max(35, min(w["width"] - 35, node[0]))
        node[1] = max(35, min(w["height"] - 35, node[1]))
    s["previous"] = old
    safe = isolated(w, s) and stretch(w, s) <= w["max_stretch"]
    s["energy"] = max(0., min(1., s["energy"] + dt * (-w["discharge_rate"] if safe else w["recharge_rate"])))
    for contact in w["contacts"]:
        if any(math.dist(closest([contact["x"], contact["y"]], a, b)[0], [contact["x"], contact["y"]]) <= contact["radius"] + w["cable_radius"]
               for a, b in zip(nodes, nodes[1:])):
            s["failed"] = "RED CONTACT"
    if s["tick"] * w["tick_ms"] >= w["max_time_ms"]:
        s["failed"] = "AUTOPSY EXPIRED"


def advance(w, s, tick):
    while s["tick"] < tick and s["started"] and not s["failed"] and not s["complete"]:
        step(w, s)


def cut(w, s, a, b):
    """A blade stroke is evaluated against the current finite cable and collar geometry."""
    if not isolated(w, s) or stretch(w, s) > w["max_stretch"]:
        s["failed"] = "CABLE NOT ISOLATED"
        return []
    if s["energy"] > w["cut_energy_limit"] + 1e-9:
        s["failed"] = "COLLAR STILL ENERGIZED"
        return []
    hits = [c["id"] for c in w["collars"] if c["id"] not in s["removed"] and
            math.dist(closest(collar(w, s, c)[0], a, b)[0], collar(w, s, c)[0]) <= c["radius"]]
    if not hits or math.dist(a, b) < 8:
        s["failed"] = "BARE WIRE / MISSED COLLAR"
        return []
    # Sample the blade at 2 px spacing. Its complete visible path must avoid bare
    # wire and red contacts; collar masks use their actual rendered circular radius.
    masks = [(collar(w, s, c)[0], c["radius"]) for c in w["collars"] if c["id"] in hits]
    for j in range(math.ceil(math.dist(a, b) / 2) + 1):
        f = j / max(1, math.ceil(math.dist(a, b) / 2))
        point = [a[k] + f * (b[k] - a[k]) for k in (0, 1)]
        if any(math.dist(point, [c["x"], c["y"]]) <= c["radius"] for c in w["contacts"]):
            s["failed"] = "BLADE TOUCHED RED CONTACT"
            return []
        if any(math.dist(closest(point, x, y)[0], point) <= w["cable_radius"] + 2 for x, y in zip(s["nodes"], s["nodes"][1:])) and not any(math.dist(point, p) <= r + 2 for p, r in masks):
            s["failed"] = "BARE WIRE CUT"
            return []
    s["removed"] = sorted(set(s["removed"] + hits))
    s["complete"] = len(s["removed"]) == len(w["collars"])
    if not s["complete"]:
        s["energy"] = min(1., s["energy"] + w["exposed_energy"])
    return hits


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or public_state.get(key) != ground_truth[key] or payload.get(key) != ground_truth[key]:
                return fail("stale or mismatched " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        if any(ground_truth.get(k) != public_state.get(k) for k in ("world", "control_condition")):
            return fail("public/private world or condition mismatch")
        mode = ground_truth["control_condition"]["interaction"]
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction")
        w = ground_truth["world"]
        s = initial_state(w)
        events = payload.get("events")
        if not isinstance(events, list) or not 2 <= len(events) <= 5000:
            return fail("missing or excessive action transcript")
        dragging = None
        for seq, e in enumerate(events, 1):
            tick = e["tick"]
            if e.get("seq") != seq or type(tick) is not int or not s["tick"] <= tick <= w["max_time_ms"] // w["tick_ms"]:
                return fail("invalid action order/time")
            advance(w, s, tick)
            if s["failed"] or s["complete"]:
                return fail("action after terminal state")
            kind = e.get("kind")
            if kind == "start":
                if seq != 1 or tick or s["started"] or e.get("surface") != "start_button":
                    return fail("invalid start")
                s["started"] = True
                continue
            if not s["started"]:
                return fail("input before start")
            point = e.get("point")
            if kind in ("grip_begin", "target", "cut"):
                points = [point] if kind != "cut" else [e.get("a"), e.get("b")]
                if any(not isinstance(p, list) or len(p) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in p) or not (0 <= p[0] <= w["width"] and 0 <= p[1] <= w["height"]) for p in points):
                    return fail("nonfinite or off-canvas input")
            if kind == "grip_begin":
                i = e.get("grip")
                if mode != "full" or e.get("surface") != "gripper_drag" or i not in (0, 1) or dragging is not None or math.dist(point, [w["ports"][i]["x"], s["grips"][i]["y"]]) > 26:
                    return fail("drag does not pick the rendered gripper")
                dragging = i
            elif kind == "target":
                i = e.get("grip")
                if i not in (0, 1) or abs(point[0] - w["ports"][i]["x"]) > 38:
                    return fail("target outside selected rail")
                if e.get("surface") != ("gripper_drag" if mode == "full" else "rail_click") or (mode == "full" and dragging != i):
                    return fail("target through wrong input surface")
                s["grips"][i]["target"] = max(w["rail_bounds"][0], min(w["rail_bounds"][1], point[1]))
            elif kind == "grip_end":
                if mode != "full" or dragging != e.get("grip") or e.get("surface") != "gripper_drag":
                    return fail("invalid drag release")
                dragging = None
            elif kind == "cut":
                if dragging is not None or e.get("surface") != ("knife_drag" if mode == "full" else "knife_two_clicks"):
                    return fail("cut through wrong input surface or held gripper")
                hit = cut(w, s, e["a"], e["b"])
                if s["failed"]:
                    return fail(s["failed"])
                if e.get("removed") != hit:
                    return fail("cut claim disagrees with geometry")
            elif kind == "seal":
                return fail("premature seal")
            else:
                return fail("unknown action / stop, reset and rewind are unavailable")
        final = payload.get("final_state", {})
        if final.get("tick") != s["tick"] or final.get("removed") != s["removed"] or final.get("failed") != s["failed"] or final.get("complete") != s["complete"]:
            return fail("final outcome disagrees with replay")
        if type(final.get("energy")) not in (int, float) or not math.isfinite(final["energy"]) or abs(final["energy"] - s["energy"]) > 1e-7:
            return fail("final capacitor energy disagrees with replay")
        nodes = final.get("nodes", [])
        if (not isinstance(nodes, list) or len(nodes) != len(s["nodes"])
                or any(not isinstance(a, list) or len(a) != 2
                       or any(type(v) not in (int, float) or not math.isfinite(v) for v in a)
                       or math.dist(a, b) > .025 for a, b in zip(nodes, s["nodes"]))):
            return fail("final cable geometry disagrees with replay")
        passed = s["complete"] and not s["failed"] and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"independent flexible-cable replay: {len(s['removed'])}/{len(w['collars'])} collars; {s['tick']} ticks")
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as exc:
        return fail("invalid cable transcript: " + str(exc))


def cheat(public_state, ground_truth):
    return {"oracle": "privileged planning only; all execution must use model HTTP input"}
