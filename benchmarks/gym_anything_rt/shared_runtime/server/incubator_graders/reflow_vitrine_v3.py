"""Independent fixed-step layout replay, also executable in pinned Pyodide."""
from __future__ import annotations

import math

MECHANIC_ID = "reflow_vitrine_v3"
REVISION = "kinetic-registration-1"
LINKAGE_REVISION = "frame-linkage-inspection-1"


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    raw = ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1
    return math.copysign(.28 + .72 * abs(raw), raw)


def wind(world, i, ms):
    u = ms / world["parameters"]["gust_span_ms"]
    n = math.floor(u)
    f = u - n
    a, b = noise(world["gust_seeds"][i], n), noise(world["gust_seeds"][i], n + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def spans(world):
    s = world["stage"]
    return [s["w"], s["h"], s["h"], s["w"] * (1 - world["target"][0])]


def seam_pixels(world, positions):
    s = world["stage"]
    a = s["x"] + s["w"] * positions[0]
    return [a, s["y"] + s["h"] * positions[1], s["y"] + s["h"] * positions[2],
            a + s["w"] * (1 - positions[0]) * positions[3]]


class Physics:
    def __init__(self, world):
        self.world = world
        self.ms = 0
        self.p = list(world["initial"])
        self.v = [0.] * 4
        self.trim = [0.] * 4
        self.blur_ms = 0
        self.terminal = ""
        self.started = False
        self.scale = spans(world)
        self.targets = seam_pixels(world, world["target"])

    def errors(self):
        return [abs(a - b) for a, b in zip(seam_pixels(self.world, self.p), self.targets)]

    def advance(self, end_ms):
        w, parameters = self.world, self.world["parameters"]
        if not self.started:
            return
        while self.ms + w["tick_ms"] <= end_ms and not self.terminal:
            self.ms += w["tick_ms"]
            dt = w["tick_ms"] / 1000
            for i in range(parameters["seam_count"]):
                desired = (w["motor_speed"] * w["linkages"][i]["sign"] * self.trim[i] + parameters["wind_speed"] * wind(w, i, self.ms)) / self.scale[i]
                self.v[i] += (desired - self.v[i]) * dt / parameters["inertia_s"]
                self.p[i] += self.v[i] * dt
                low, high = w["limits"]
                if self.p[i] < low or self.p[i] > high:
                    self.p[i] = max(low, min(high, self.p[i]))
                    self.v[i] = 0.
            # Grading uses the very same rendered seam locations, including D's
            # dependency on the root split. There are no hidden action quotas.
            if max(self.errors()[:parameters["seam_count"]]) > parameters["tolerance_px"]:
                self.blur_ms += w["tick_ms"]
            if self.blur_ms > w["blur_budget_ms"]:
                self.terminal = "fail"
            elif self.ms >= w["duration_ms"]:
                self.terminal = "pass"

    def summary(self):
        return dict(t_ms=self.ms, positions=self.p[:], velocities=self.v[:], trims=self.trim[:],
                    blur_ms=self.blur_ms, terminal=self.terminal)


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _fail(message):
    return dict(graded=True, passed=False, score=0, feedback=message)


def replay(payload, truth, public):
    for key in ("mechanic_id", "task_id", "challenge_id"):
        if not truth.get(key) or any(obj.get(key) != truth[key] for obj in (public, payload)):
            raise ValueError(f"stale or mismatched {key}")
    if truth["mechanic_id"] != MECHANIC_ID or truth["world"]["revision"] != REVISION:
        raise ValueError("wrong mechanic revision")
    if truth["world"] != public.get("world") or truth.get("control_condition") != public.get("control_condition"):
        raise ValueError("render/replay contract disagreement")
    interaction = (truth.get("control_condition") or {}).get("interaction", "full")
    if interaction not in ("full", "simplified") or payload.get("interaction_mode") != interaction:
        raise ValueError("wrong interaction mode")
    world = truth["world"]
    count = world["parameters"]["seam_count"]
    links = world.get("linkages")
    if (world.get("linkage_revision") != LINKAGE_REVISION or not isinstance(links, list)
            or len(links) != count or any(not isinstance(link, dict) for link in links)):
        raise ValueError("invalid frame linkage contract")
    if (any(type(link.get("rail")) is not int or type(link.get("sign")) is not int
            or link["sign"] not in (-1, 1) for link in links)
            or sorted(link["rail"] for link in links) != list(range(1, count + 1))):
        raise ValueError("invalid frame linkage contract")
    sim = Physics(world)
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("missing primitive control transcript")
    active = None
    previous = 0
    for sequence, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("sequence") != sequence:
            raise ValueError("invalid event sequence")
        ms = _integer(event.get("t_ms"), "event time")
        if ms < previous or ms % world["tick_ms"] or ms > world["duration_ms"]:
            raise ValueError("invalid event time")
        previous = ms
        sim.advance(ms)
        if sim.terminal:
            raise ValueError("input after terminal inspection")
        kind, source = event.get("kind"), event.get("input_source")
        if kind == "start":
            if sim.started or ms != 0 or source != "inspection_button":
                raise ValueError("inspection cannot restart")
            sim.started = True
            continue
        if not sim.started and ms != 0:
            raise ValueError("preparation advanced inspection time")
        i = _integer(event.get("seam"), "seam")
        if not 0 <= i < count:
            raise ValueError("unavailable seam")
        if kind == "inspect":
            # A read-only frame inspection is never a task commitment, an
            # action quota, or a prerequisite for grading an otherwise valid run.
            if source != "seam_inspection" or active is not None or "u" in event:
                raise ValueError("invalid frame inspection")
            continue
        u = _number(event.get("u"), "lever position")
        if not 0 <= u <= 1:
            raise ValueError("lever left its rail")
        if interaction == "simplified":
            if kind != "trim" or source != "rail_click" or active is not None:
                raise ValueError("wrong simplified input surface")
            sim.trim[i] = 2 * u - 1
        else:
            if source != "lever_drag":
                raise ValueError("wrong full input surface")
            if kind == "grip":
                if active is not None or abs(u - (sim.trim[i] + 1) / 2) > .075:
                    raise ValueError("drag did not begin on the visible thumb")
                active = i
            elif kind in ("trim", "release"):
                if active != i:
                    raise ValueError("drag lost its captured thumb")
                sim.trim[i] = 2 * u - 1
                if kind == "release":
                    active = None
            else:
                raise ValueError("unknown full control event")
    final_ms = _integer(payload.get("final_t_ms"), "final time")
    if final_ms < previous or final_ms > world["duration_ms"] or final_ms % world["tick_ms"]:
        raise ValueError("invalid final inspection time")
    sim.advance(final_ms)
    claimed = payload.get("summary")
    actual = sim.summary()
    if not isinstance(claimed, dict):
        raise ValueError("missing physical summary")
    for key in ("positions", "velocities", "trims"):
        if not isinstance(claimed.get(key), list) or len(claimed[key]) != 4:
            raise ValueError("malformed physical summary")
        if any(abs(_number(a, key) - b) > .00001 for a, b in zip(claimed[key], actual[key])):
            raise ValueError(f"{key} differ from independent replay")
    for key in ("t_ms", "blur_ms", "terminal"):
        if claimed.get(key) != actual[key]:
            raise ValueError(f"{key} differs from independent replay")
    if payload.get("completed") is not (sim.terminal == "pass"):
        raise ValueError("completion claim differs from physical outcome")
    return sim


def grade(payload, truth, public):
    try:
        sim = replay(payload, truth, public)
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        return _fail(f"reflow replay rejected: {error}")
    passed = sim.started and sim.terminal == "pass"
    return dict(graded=True, passed=passed, score=100 if passed else 0,
                feedback=f"Lighting inspection {sim.ms}/20000 ms; out of register {sim.blur_ms}/{sim.world['blur_budget_ms']} ms; {sim.terminal or 'incomplete'}.")
