"""Independent fixed-step replay of motor settings, inertia, and visible wind."""
from __future__ import annotations

import math

MECHANIC_ID = "rotate_wrong_thing_upright_v3"
REVISION = "wind-gimbal-3-inspection"


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xffffffff
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff) / 4294967295 * 2 - 1


def wind(contract, axis, milliseconds):
    if axis >= contract["parameters"]["axes"]:
        return 0.
    span = contract["parameters"]["gust_span_ms"]
    u = max(0, milliseconds) / span
    n, f = math.floor(u), u % 1
    a, b = noise(contract["wind_seeds"][axis], n), noise(contract["wind_seeds"][axis], n+1)
    return contract["parameters"]["gust_rate"] * (a+(b-a)*f*f*(3-2*f))


class Physics:
    def __init__(self, contract):
        self.c = contract
        self.x = list(contract["initial"])
        self.v = list(contract["initial_velocity"])
        self.u = [0., 0., 0.]
        self.tick = 0
        self.dwell = 0
        self.best = 0
        self.started = False
        self.solved = False
        self.failed = ""

    def advance(self, target):
        if not self.started:
            return
        p = self.c["parameters"]
        while self.tick < target and not self.solved and not self.failed:
            self.tick += 1
            ms = self.tick*self.c["tick_ms"]
            for i in range(p["axes"]):
                drive = self.c["motor_rate"]*sum(self.c["matrix"][i][j]*self.u[j] for j in range(3))
                self.v[i] += (drive+wind(self.c, i, ms)-self.v[i])*.01/p["response_s"]
                self.x[i] += self.v[i]*.01
                if abs(self.x[i]) >= self.c["stop_deg"]:
                    self.x[i] = math.copysign(self.c["stop_deg"], self.x[i])
                    self.v[i] = 0.
            aligned = all(abs(self.x[i]) <= p["tolerance_deg"] and abs(self.v[i]) <= p["speed_tolerance"] for i in range(p["axes"]))
            self.dwell = self.dwell+self.c["tick_ms"] if aligned else 0
            self.best = max(self.best, self.dwell)
            if self.dwell >= self.c["hold_ms"]:
                self.solved = True
            elif ms >= self.c["run_limit_ms"]:
                self.failed = "Alignment run expired."

    def snapshot(self):
        return dict(tick=self.tick, angles=self.x[:], velocity=self.v[:], drive=self.u[:],
                    dwell_ms=self.dwell, best_ms=self.best, started=self.started,
                    solved=self.solved, failed=self.failed)


def full_handle(axis, value):
    """Canvas regulator handwheel: zero at twelve o'clock, signed ±110°."""
    phi = math.radians(value*110)
    return [150+axis*300+60*math.sin(phi), 76-60*math.cos(phi)]


def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("non-finite numeric input")
    return float(value)


def _point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("malformed pointer")
    p = [_finite(v) for v in value]
    if not 0 <= p[0] <= 900 or not 0 <= p[1] <= 152:
        raise ValueError("pointer outside motor panel")
    return p


def pointer_value(axis, point):
    angle = math.degrees(math.atan2(point[0]-(150+axis*300), 76-point[1]))
    return max(-1., min(1., angle/110))


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or mismatched "+key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION:
            return fail("unsupported gimbal revision")
        for key in ("gimbal", "control_condition"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public replay contract differs: "+key)
        for key in ("single_attempt", "episode_failed", "episode_history_error"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public episode policy differs: "+key)
        if ground_truth.get("single_attempt") is not True:
            return fail("gimbal requires the first-failure episode policy")
        if ground_truth.get("episode_history_error"):
            return fail("episode failure history could not be verified")
        if ground_truth.get("episode_failed"):
            return fail("A failed alignment attempt already ended this episode.")
        mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 6000:
            return fail("missing or excessive motor transcript")
        sim = Physics(ground_truth["gimbal"])
        held = None
        sealed = False
        for index, e in enumerate(events, 1):
            tick = e.get("tick")
            if (not isinstance(e, dict) or e.get("sequence") != index or type(tick) is not int or
                not sim.tick <= tick <= sim.c["run_limit_ms"]//10 or sealed):
                return fail("invalid event order or clock")
            if not sim.started and tick != 0:
                return fail("preparation cannot advance the run")
            sim.advance(tick)
            if tick != sim.tick:
                return fail("event occurs after physical termination")
            kind = e.get("kind")
            if kind == "start":
                if sim.started or held or e.get("input_source") != "begin_button":
                    return fail("invalid run start")
                sim.started = True
            elif kind == "seal":
                if e.get("input_source") != "certify_button" or held:
                    return fail("invalid certification")
                sealed = True
            elif kind == "capture_cancel":
                if (mode != "full" or held is None or e.get("axis") != held or
                    e.get("input_source") != "physical_termination" or not (sim.solved or sim.failed)):
                    return fail("invalid automatic terminal capture cancellation")
                held = None
            elif kind == "inspect_motor":
                axis = e.get("axis")
                if (type(axis) is not int or not 0 <= axis < sim.c["parameters"]["axes"] or
                    held is not None or sim.solved or sim.failed or e.get("input_source") != "gear_cover"):
                    return fail("invalid motor inspection")
                point = _point(e.get("point"))
                if not 16+axis*300 <= point[0] <= 284+axis*300 or not 104 <= point[1] <= 132:
                    return fail("inspection misses the visible gear cover")
            else:
                # A captured pointer can be released after the physics ends.
                # Release changes no motor setting and cannot undo termination.
                if (sim.solved or sim.failed) and kind != "drive_up":
                    return fail("control after terminal state")
                axis = e.get("axis")
                if type(axis) is not int or not 0 <= axis < sim.c["parameters"]["axes"]:
                    return fail("inactive axis input")
                point = _point(e.get("point"))
                if mode == "simplified":
                    if kind != "drive_click" or e.get("input_source") != "motor_rail" or held:
                        return fail("wrong simplified motor surface")
                    if not 48+axis*300 <= point[0] <= 252+axis*300 or not 53 <= point[1] <= 99:
                        return fail("click misses the visible rail")
                    sim.u[axis] = max(-1., min(1., (point[0]-(150+axis*300))/100))
                else:
                    if e.get("input_source") != "handwheel_drag":
                        return fail("wrong full motor surface")
                    if kind == "drive_down":
                        if held is not None or math.dist(point, full_handle(axis, sim.u[axis])) > 20:
                            return fail("handwheel must be grabbed at its visible handle")
                        held = axis
                    elif kind == "drive_move":
                        if held != axis:
                            return fail("no captured handwheel")
                        sim.u[axis] = pointer_value(axis, point)
                    elif kind == "drive_up":
                        if held != axis:
                            return fail("wrong handwheel release")
                        held = None
                    else:
                        return fail("unknown motor input")
        if not sealed or held is not None:
            return fail("unsealed gimbal run")
        snapshot = payload.get("final")
        if not isinstance(snapshot, dict):
            return fail("missing final physical state")
        expected = sim.snapshot()
        for key in ("tick", "dwell_ms", "best_ms", "started", "solved", "failed"):
            if snapshot.get(key) != expected[key]:
                return fail("final state disagrees: "+key)
        for key in ("angles", "velocity", "drive"):
            values = snapshot.get(key)
            if not isinstance(values, list) or len(values) != 3 or any(abs(_finite(a)-b) > .0001 for a,b in zip(values,expected[key])):
                return fail("final physics disagrees: "+key)
        passed = sim.solved and not sim.failed and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback="Ten seconds of simultaneous world-plumb orientation verified." if passed else "Gimbal never completed its alignment run.")
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        return fail("invalid gimbal transcript: "+str(exc))
