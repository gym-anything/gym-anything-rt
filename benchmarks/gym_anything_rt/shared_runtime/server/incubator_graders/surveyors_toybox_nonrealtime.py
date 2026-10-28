"""Independent geometric replay; also executes unchanged in Pyodide.

Only public mouse gesture coordinates, selections and their task times change
annotations. Client completion, fit, links and charge claims are checked by replay.
"""
from __future__ import annotations

import copy
import math

MECHANIC_ID = "surveyors_toybox_nonrealtime"
REVISION = "live-cuboid-survey-v2"
ACTION_STEP_MS = 20


def sweep_fraction(u):
    """C1 position with short finite acceleration at sweep turnarounds."""
    u = max(0., min(1., u))
    a = .06
    if u < a:
        return u*u / (2*a*(1-a))
    if u > 1-a:
        return 1-(1-u)**2 / (2*a*(1-a))
    return (u-a/2)/(1-a)


def pose(obj, ms):
    m = obj["motion"]
    u = (max(0, ms) + m["offset_ms"]) / m["span_ms"]
    i = min(len(m["knots"]) - 2, int(u))
    f = sweep_fraction(u - i)
    a, b = m["knots"][i:i + 2]
    p = [a[j] + (b[j] - a[j]) * f for j in range(4)]
    steering = m["steering"]
    su = (max(0, ms)+steering["offset_ms"])/steering["span_ms"]
    si = min(len(steering["knots"])-2, int(su))
    sf = min(1., su-si)
    sf = sf*sf*(3-2*sf)
    p[0] += steering["knots"][si] + (steering["knots"][si+1]-steering["knots"][si])*sf
    return dict(center=p[:3], half=list(obj["half"]), yaw=p[3])


def project(view, point):
    return [view["origin"][j] + view["scale"] * view["signs"][j] * point[view["axes"][j]] for j in range(2)]


def corners(box):
    c, h = box["center"], box["half"]
    a = math.radians(box["yaw"])
    co, si = math.cos(a), math.sin(a)
    return [[c[0] + x * h[0] * co - z * h[2] * si, c[1] + y * h[1], c[2] + x * h[0] * si + z * h[2] * co]
            for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]


def footprint(box):
    c, h = box["center"], box["half"]
    a = math.radians(box["yaw"])
    co, si = math.cos(a), math.sin(a)
    return [(c[0] + x * h[0] * co - z * h[2] * si, c[2] + x * h[0] * si + z * h[2] * co)
            for x, z in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def _clip(poly, a, b):
    if not poly:
        return []
    out = []
    p = poly[-1]
    before = _cross(a, b, p) >= -1e-10
    for q in poly:
        after = _cross(a, b, q) >= -1e-10
        if before != after:
            d, e = (q[0]-p[0], q[1]-p[1]), (b[0]-a[0], b[1]-a[1])
            den = d[0]*e[1] - d[1]*e[0]
            if abs(den) > 1e-12:
                t = ((a[0]-p[0])*e[1] - (a[1]-p[1])*e[0]) / den
                out.append((p[0]+t*d[0], p[1]+t*d[1]))
        if after:
            out.append(q)
        p, before = q, after
    return out


def iou(a, b):
    polygon, boundary = footprint(a), footprint(b)
    for j in range(4):
        polygon = _clip(polygon, boundary[j], boundary[(j+1) % 4])
    area = abs(sum(polygon[j][0]*polygon[(j+1) % len(polygon)][1] - polygon[(j+1) % len(polygon)][0]*polygon[j][1]
                   for j in range(len(polygon))) / 2) if polygon else 0
    vertical = max(0., min(a["center"][1]+a["half"][1], b["center"][1]+b["half"][1]) -
                   max(a["center"][1]-a["half"][1], b["center"][1]-b["half"][1]))
    intersection = area * vertical
    union = 8 * math.prod(a["half"]) + 8 * math.prod(b["half"]) - intersection
    return intersection / union if union > 0 else 0


def fit(annotation, expected, rules):
    return (math.dist(annotation["center"], expected["center"]) <= rules["center_tolerance"] + 1e-9
            and max(abs(a-b) for a, b in zip(annotation["half"], expected["half"])) <= rules["extent_tolerance"] + 1e-9
            and abs((annotation["yaw"] - expected["yaw"] + 90) % 180 - 90) <= rules["yaw_tolerance"] + 1e-9
            and iou(annotation, expected) >= rules["iou_min"] - 1e-9)


def hit_object(contract, view_id, point, ms):
    """The camera is a transparent wireframe plate: nearest projected center wins.

    The selection discs (radius 14) are explicitly drawn in both camera plates;
    no invisible inflated object hitbox is used.
    """
    view = contract["views"][view_id]
    candidates = [(math.dist(point, project(view, pose(obj, ms)["center"])), obj["id"]) for obj in contract["objects"]]
    distance, object_id = min(candidates)
    return object_id if distance <= 14.01 else None


def handle(contract, annotation, tool):
    if tool == "plan":
        return project(contract["views"]["plan"], annotation["center"])
    if tool == "height":
        p = project(contract["views"]["front"], annotation["center"])
        return [p[0]-22, p[1]]
    if tool == "yaw":
        a = math.radians(annotation["yaw"])
        return [115+56*math.cos(a), 80+56*math.sin(a)]
    if tool.startswith("extent"):
        axis = int(tool[-1])
        return [20+160*annotation["half"][axis], 25+40*axis]
    raise ValueError("unknown manipulation handle")


def manipulate(contract, annotation, tool, point, start=None, base=None):
    if tool == "plan":
        v = contract["views"]["plan"]
        if start is None:
            annotation["center"][0] = (point[0]-v["origin"][0]) / v["scale"]
            annotation["center"][2] = (point[1]-v["origin"][1]) / v["scale"]
        else:
            annotation["center"][0] = base["center"][0] + (point[0]-start[0]) / v["scale"]
            annotation["center"][2] = base["center"][2] + (point[1]-start[1]) / v["scale"]
    elif tool == "height":
        v = contract["views"]["front"]
        annotation["center"][1] = ((v["origin"][1]-point[1]) / v["scale"] if start is None
                                     else base["center"][1] - (point[1]-start[1]) / v["scale"])
    elif tool == "yaw":
        if math.dist(point, [115, 80]) < 12:
            return
        annotation["yaw"] = math.degrees(math.atan2(point[1]-80, point[0]-115))
    elif tool.startswith("extent"):
        axis = int(tool[-1])
        annotation["half"][axis] = max(.18, min(1., (point[0]-20)/160 if start is None
                                                   else base["half"][axis] + (point[0]-start[0])/160))
    else:
        raise ValueError("unknown tool")
    for j, bound in enumerate(contract["world"]["bounds"]):
        annotation["center"][j] = max(bound[0], min(bound[1], annotation["center"][j]))


class Survey:
    def __init__(self, contract):
        self.contract = contract
        self.annotations = copy.deepcopy(contract["initial_annotations"])
        self.objects = {o["id"]: o for o in contract["objects"]}
        self.links = {}
        self.ms, self.charge = 0, 0
        self.lost = dict.fromkeys(self.annotations, 0)
        self.active = False
        self.completed = False
        self.failed = ""

    def start(self):
        if self.active or self.completed or self.failed:
            raise ValueError("the scan cannot be restarted")
        if self.links != self.contract["target_map"]:
            self.failed = "Camera links identify the wrong toys."
        else:
            self.active = True

    def advance(self, end_ms):
        r = self.contract["requirements"]
        tick = self.contract["world"]["tick_ms"]
        while self.active and not self.completed and not self.failed and self.ms + tick <= end_ms:
            self.ms += tick
            all_fit = True
            for label, object_id in self.links.items():
                good = fit(self.annotations[label], pose(self.objects[object_id], self.ms), r)
                self.lost[label] = 0 if good else self.lost[label] + tick
                all_fit = all_fit and good
                if self.lost[label] >= r["lost_limit_ms"]:
                    self.failed = "A tug left its survey volume for too long."
            self.charge = min(r["charge_ms"], max(0, self.charge + (tick if all_fit else -tick*r["charge_leak"])))
            if self.charge >= r["charge_ms"] and not self.failed:
                self.completed = True
            if self.ms >= r["max_run_ms"] and not self.completed:
                self.failed = "The scan ended before all volumes were tracked."


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("non-finite coordinate or time")
    return value


def _point(value, width, height):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("missing pointer point")
    p = [_number(x) for x in value]
    if not 0 <= p[0] <= width or not 0 <= p[1] <= height:
        raise ValueError("pointer point outside its visible surface")
    return p


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id", "physics_revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or mismatched " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["physics_revision"] != REVISION:
            return fail("wrong survey revision")
        for key in ("objects", "targets", "initial_annotations", "world", "views", "requirements", "timing", "difficulty_profile", "control_condition", "interaction_mode"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public/private contract differs: " + key)
        if ground_truth.get("timing") != {
            "mode": "action_step",
            "action_step_ms": ACTION_STEP_MS,
            "idle_behavior": "stable_between_completed_controls",
        }:
            return fail("wrong counterpart timing contract")
        mode = ground_truth["interaction_mode"]
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= ground_truth["requirements"]["max_events"]:
            return fail("missing or oversized action trace")
        sim = Survey(ground_truth)
        selected = ground_truth["targets"][0]["id"]
        tool, hold, previous = "plan", None, 0
        certified = False
        tools = ("plan", "height", "yaw", "extent0", "extent1", "extent2", "link")
        for sequence, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("sequence") != sequence or event.get("input_source") != mode:
                return fail("event order or input surface differs")
            t = _number(event.get("t_ms"))
            if type(t) is not int or t != sim.ms or not 0 <= t <= ground_truth["requirements"]["max_run_ms"] or t % ACTION_STEP_MS:
                return fail("invalid task time")
            if certified or sim.failed or (sim.completed and event.get("kind") != "certify"):
                return fail("action follows a terminal survey")
            kind = event.get("kind")
            if kind in ("select", "tool", "start") and hold is not None:
                return fail("action overlaps a captured pointer")
            if kind == "select":
                if event.get("target_id") not in sim.annotations:
                    return fail("unknown volume")
                selected = event["target_id"]
            elif kind == "tool":
                if event.get("tool") not in tools:
                    return fail("unknown tool")
                tool = event["tool"]
            elif kind == "start":
                sim.start()
                # The browser silently leaves LINK for the first editable
                # surface when START is pressed; this is administrative and
                # does not consume a separate action-step.
                if tool == "link":
                    tool = "plan"
            elif kind == "certify":
                certified = True
                if not sim.completed or sim.failed:
                    return fail(sim.failed or "survey incomplete")
                # The world may finish while a pointer is still held. Closing
                # the completed scan does not change any outcome geometry.
                hold = None
            elif kind in ("link_start", "link_click"):
                if tool != "link" or sim.active or hold:
                    return fail("links can only be prepared before the scan")
                if (kind == "link_start") != (mode == "full"):
                    return fail("wrong linking procedure")
                view = event.get("view")
                if view not in ("plan", "front"):
                    return fail("unknown camera")
                v = ground_truth["views"][view]
                p = _point(event.get("point"), v["width"], v["height"])
                object_id = hit_object(ground_truth, view, p, 0)
                if object_id is None:
                    return fail("link does not hit a visible selection disc")
                if mode == "full":
                    hold = dict(kind="link", object_id=object_id)
                else:
                    sim.links[selected] = object_id
            elif kind == "link_end":
                if mode != "full" or hold is None or hold["kind"] != "link":
                    return fail("no camera link is held")
                _point(event.get("socket_point"), 100, 100)
                sim.links[selected] = hold["object_id"]
                hold = None
            elif kind == "link_cancel":
                if mode != "full" or hold is None or hold["kind"] != "link":
                    return fail("no camera link is held")
                hold = None
            elif kind in ("down", "click", "move", "up", "cancel"):
                if tool == "link":
                    return fail("wrong link event")
                if (kind == "click") != (mode == "simplified"):
                    return fail("wrong manipulation procedure")
                surface = "plan" if tool == "plan" else "front" if tool == "height" else "dial" if tool == "yaw" else "extent"
                if event.get("surface") != surface:
                    return fail("tool uses the wrong visible surface")
                size = (440, 420) if surface in ("plan", "front") else (230, 160) if surface == "dial" else (230, 130)
                p = _point(event.get("point"), *size)
                annotation = sim.annotations[selected]
                if kind == "down":
                    if hold or math.dist(p, handle(ground_truth, annotation, tool)) > 14.01:
                        return fail("drag must begin on its drawn handle")
                    hold = dict(kind="edit", start=p, base=copy.deepcopy(annotation))
                elif kind == "click":
                    if hold:
                        return fail("click overlaps a pointer hold")
                    manipulate(ground_truth, annotation, tool, p)
                elif hold is None or hold["kind"] != "edit":
                    return fail("no annotation handle is held")
                elif kind == "move":
                    manipulate(ground_truth, annotation, tool, p, hold["start"], hold["base"])
                else:
                    if kind == "up":
                        manipulate(ground_truth, annotation, tool, p, hold["start"], hold["base"])
                    hold = None
            else:
                return fail("unknown action; reset and stop controls do not exist")
            if sim.failed:
                return fail(sim.failed)
            # The counterpart is stable while idle. A completed existing
            # control advances one fixed simulation tick; pointer moves inside
            # a held drag wait until release before advancing.
            advances = (
                kind in {"select", "tool", "click", "up"} and sim.active
            ) or (kind == "start" and sim.active)
            if advances:
                sim.advance(sim.ms + ACTION_STEP_MS)
                if sim.failed:
                    return fail(sim.failed)
            previous = sim.ms
        if sim.failed:
            return fail(sim.failed)
        final = _number(payload.get("final_t_ms"))
        if final != sim.ms or payload.get("completed") is not True or not certified or hold:
            return fail("incomplete or inconsistent final state")
        for key, value in (("links", sim.links), ("charge_ms", sim.charge), ("lost_ms", sim.lost)):
            if payload.get(key) != value:
                return fail("submitted " + key + " differs from replay")
        actual = payload.get("annotations")
        if not isinstance(actual, dict) or set(actual) != set(sim.annotations):
            return fail("missing final volumes")
        for label, expected in sim.annotations.items():
            for field in ("center", "half"):
                values = actual[label].get(field)
                if not isinstance(values, list) or len(values) != 3 or any(abs(_number(a)-b) > 1e-5 for a, b in zip(values, expected[field])):
                    return fail("final cuboid differs from gesture replay")
            if abs(_number(actual[label].get("yaw"))-expected["yaw"]) > 1e-5:
                return fail("final heading differs from gesture replay")
        return dict(graded=True, passed=True, score=100, feedback=f"3D IoU, camera identity and live survey replay: {len(sim.links)} volumes; {sim.ms} ms; {sim.charge:g} ms simultaneous fit")
    except (KeyError, TypeError, ValueError, OverflowError, IndexError, AttributeError) as exc:
        return fail("invalid survey transcript: " + str(exc))


def cheat(public_state, ground_truth):
    del public_state
    return dict(target_map=ground_truth.get("target_map", {}))
