"""Independent fixed-step replay. Self-contained for the existing Pyodide exporter."""
from __future__ import annotations

import copy
import math

MECHANIC_ID = "unwatched_wing_v3"
REVISION = "lantern-survey-v3"


def coordinate(value):
    return math.floor(value * 1000 + .5) / 1000


def phase_y(obj):
    return coordinate(obj["baseline"] + obj["amplitude"] * math.sin(obj["phase_code"] * math.pi / 180000))


def free_vertical(obj):
    future = dict(obj, phase_code=(obj["phase_code"] + obj["rate_code"] * 2) % 360000)
    return (phase_y(future) - obj["y"]) / .02


def noise(seed, index):
    x = (int(seed) ^ ((index + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(seed, ms, span):
    n = math.floor(ms / span)
    f = ms / span - n
    a, b = noise(seed, n), noise(seed, n + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def circle_rect(x, y, radius, left, top, right, bottom):
    if bottom < top:
        return False
    dx = x - max(left, min(x, right))
    dy = y - max(top, min(y, bottom))
    # Tangency is permitted; positive-area contact is a collision.
    return dx * dx + dy * dy < radius * radius - 1e-9


class Transit:
    def __init__(self, truth):
        self.world = truth["world"]
        self.gates = copy.deepcopy(self.world["gates"])
        self.cargo = copy.deepcopy(self.world["cargo"])
        self.ms = 0
        self.started = False
        self.active = False
        self.goal = list(self.world["initial_lens"])
        self.lens = list(self.goal)
        self.pinned = None
        self.photo_id = None
        self.photo_until_ms = 0
        self.failed = ""
        self.impact = None
        self.passed = False
        self.inspected = set()
        for g in self.gates:
            g.update(y=phase_y(g), age_ms=0, vy=0.)
        for c in self.cargo:
            c.update(delivered=False, vx=0., vy=0., age_ms=0)

    def rates(self):
        if self.ms % self.world["rate_update_ms"]:
            return
        def step(obj, prefix):
            value = obj[prefix+"_code"] + obj[prefix+"_direction"]*obj[prefix+"_step"]
            low, high = obj[prefix+"_min"], obj[prefix+"_max"]
            if value <= low:
                value=2*low-value; obj[prefix+"_direction"]=1
            elif value >= high:
                value=2*high-value; obj[prefix+"_direction"]=-1
            obj[prefix+"_code"] = value
        for g in self.gates:
            step(g, "rate")
        for c in self.cargo:
            step(c, "rate");step(c, "speed")

    def observed(self):
        if not self.active:
            return None
        objects = [(g["id"], [g["x"] + 26, g["y"]]) for g in self.gates]
        objects += [(c["id"], [c["x"], c["y"]]) for c in self.cargo if not c["delivered"]]
        candidates = [(math.dist(self.lens, point), ident) for ident, point in objects
                      if math.dist(self.lens, point) <= self.world["focus_radius"]]
        return min(candidates)[1] if candidates else None

    def advance(self, end_ms):
        if not self.started:
            return
        step = self.world["tick_ms"]
        dt = step / 1000
        while self.ms + step <= end_ms and not self.failed and not self.passed:
            self.ms += step
            self.rates()
            if self.photo_id is not None and self.ms >= self.photo_until_ms:
                self.photo_id = None
            dx, dy = self.goal[0] - self.lens[0], self.goal[1] - self.lens[1]
            distance = math.hypot(dx, dy)
            fraction = min(1., self.world["aim_speed"] * dt / distance) if distance else 0.
            self.lens = [coordinate(self.lens[0] + dx * fraction), coordinate(self.lens[1] + dy * fraction)]
            if self.active:
                for g in self.gates:
                    if math.dist(self.lens, [g["x"] + 26, g["baseline"]]) <= self.world["focus_radius"]:
                        self.inspected.add(g["id"])
            self.pinned = self.observed()
            for g in self.gates:
                before = g["y"]
                if g["id"] not in (self.pinned, self.photo_id):
                    g["age_ms"] += step
                    g["phase_code"] = (g["phase_code"] + g["rate_code"] * 2) % 360000
                    g["phase"] = g["phase_code"] * math.pi / 180000
                    g["y"] = phase_y(g)
                g["vy"] = (g["y"] - before) / dt
            for c in self.cargo:
                before_y = c["y"]
                c["vx"] = c["vy"] = 0.
                if c["delivered"]:
                    continue
                if c["id"] not in (self.pinned, self.photo_id):
                    c["vx"] = c["speed_code"] / 20
                    c["x"] = coordinate(c["x"] + c["vx"] * dt)
                    c["age_ms"] += step
                    c["phase_code"] = (c["phase_code"] + c["rate_code"] * 2) % 360000
                    c["phase"] = c["phase_code"] * math.pi / 180000
                    c["y"] = phase_y(c)
                    c["vy"] = (c["y"] - before_y) / dt
                for g in self.gates:
                    if g["lane"] != c["lane"]:
                        continue
                    left, right = g["x"] - g["width"] / 2, g["x"] + g["width"] / 2
                    top, bottom = g["baseline"] - 104, g["baseline"] + 104
                    if (circle_rect(c["x"], c["y"], c["radius"], left, top, right, g["y"] - g["half"])
                        or circle_rect(c["x"], c["y"], c["radius"], left, g["y"] + g["half"], right, bottom)):
                        self.failed = "A courier touched a closed shutter."
                        self.impact = dict(courier=c["id"], shutter=g["id"], t_ms=self.ms,
                                           x=c["x"], y=c["y"], aperture_y=g["y"])
                        return
                if c["x"] - c["radius"] >= self.world["dock_x"]:
                    c["delivered"] = True
            self.passed = all(c["delivered"] for c in self.cargo)
            if self.ms >= self.world["max_active_ms"] and not self.passed:
                self.failed = "The night transfer ended before every courier arrived."

    def snapshot(self):
        return dict(t_ms=self.ms, started=self.started, lamp_active=self.active,
            inspected=sorted(self.inspected),
            lens=self.lens, goal=self.goal, pinned=self.pinned, failed=self.failed, passed=self.passed,
            impact=self.impact, photo_id=self.photo_id, photo_until_ms=self.photo_until_ms,
            gates=[dict(id=g["id"], y=g["y"], phase=g["phase"], phase_code=g["phase_code"], rate_code=g["rate_code"], rate_direction=g["rate_direction"], age_ms=g["age_ms"]) for g in self.gates],
            cargo=[dict(id=c["id"], x=c["x"], y=c["y"], phase=c["phase"], phase_code=c["phase_code"], rate_code=c["rate_code"], rate_direction=c["rate_direction"], speed_code=c["speed_code"], speed_direction=c["speed_direction"], age_ms=c["age_ms"], delivered=c["delivered"]) for c in self.cargo])


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def point(value, world):
    if (not isinstance(value, list) or len(value) != 2 or not all(finite(x) for x in value)
        or not 0 <= value[0] <= world["width"] or not 0 <= value[1] <= world["height"]):
        raise ValueError("invalid lamp point")
    return list(value)


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(v, dict) for v in (payload, ground_truth, public_state)):
            return fail("transit documents must be objects")
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or wrong " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION:
            return fail("wrong transit implementation")
        for key in ("world", "parameters", "control_condition", "single_attempt"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public replay contract differs: " + key)
        mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list) or not 2 <= len(events) <= 12000:
            return fail("missing or excessive transit input trace")
        sim = Transit(ground_truth)
        previous, held, ended = 0, False, False
        for seq, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("sequence") != seq or ended:
                return fail("invalid input sequence or input after submission")
            ms = event.get("t_ms")
            if not finite(ms) or not previous <= ms <= sim.world["max_active_ms"] + 20:
                return fail("invalid transit time")
            previous = ms
            kind = event.get("kind")
            sim.advance(ms)
            if kind == "start":
                if sim.started or ms != 0 or event.get("input_source") != "start_button":
                    return fail("transit may start only once")
                sim.started = True
            elif kind == "submit":
                if event.get("input_source") not in ("submit_button", "terminal_auto"):
                    return fail("wrong submit surface")
                ended = True
            elif sim.failed or sim.passed or not sim.started:
                return fail("lamp input outside an active transit")
            elif kind == "lamp_down":
                if mode != "full" or held or event.get("input_source") != "lantern_drag":
                    return fail("invalid lantern hold")
                held = sim.active = True
                sim.goal = point(event.get("point"), sim.world)
            elif kind == "lamp_move":
                if mode != "full" or not held or event.get("input_source") != "lantern_drag":
                    return fail("move without holding the lantern")
                sim.goal = point(event.get("point"), sim.world)
            elif kind == "lamp_up":
                if mode != "full" or not held or event.get("input_source") != "lantern_drag":
                    return fail("release without holding the lantern")
                held = sim.active = False
            elif kind == "lamp_target":
                if mode != "simplified" or event.get("input_source") != "lantern_click":
                    return fail("wrong lamp target surface")
                sim.active = True
                sim.goal = point(event.get("point"), sim.world)
            elif kind == "lamp_off":
                if mode != "simplified" or event.get("input_source") != "lamp_off_button":
                    return fail("wrong lamp release surface")
                sim.active = False
            elif kind == "photo":
                source = "camera_key" if mode == "full" else "camera_button"
                if event.get("input_source") != source or event.get("object_id") != sim.observed() or sim.observed() is None:
                    return fail("photograph does not show the illuminated object")
                sim.photo_id = sim.observed()
                sim.photo_until_ms = sim.ms + sim.world["photo_lifetime_ms"]
            elif kind == "photo_clear":
                source = "viewer_key" if mode == "full" else "viewer_button"
                if event.get("input_source") != source or sim.photo_id is None:
                    return fail("wrong or empty image-viewer release")
                sim.photo_id = None
            else:
                return fail("unknown input; reset and world-stop controls are unavailable")
        final_ms = payload.get("final_t_ms")
        if not finite(final_ms) or final_ms != previous or not ended:
            return fail("submission boundary is missing")
        # Compare the replayed physical outcome, including exact failure contact.
        snapshot = payload.get("final_state")
        expected = sim.snapshot()
        def agree(a, b):
            if isinstance(b, dict):
                return isinstance(a, dict) and set(a) == set(b) and all(agree(a[k], b[k]) for k in b)
            if isinstance(b, list):
                return isinstance(a, list) and len(a) == len(b) and all(agree(x, y) for x, y in zip(a, b))
            if type(b) is float:
                return finite(a) and abs(a - b) <= 1e-6
            return type(a) is type(b) and a == b
        if not agree(snapshot, expected):
            return fail("reported transit outcome disagrees with independent replay")
        passed = sim.passed and not sim.failed and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback="Every courier reached the archive." if passed else sim.failed or "The archive transfer is incomplete.")
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        return fail("invalid transit transcript: " + str(exc))


def cheat(public_state, ground_truth):
    return {"answers": [], "boundary": "No precomputed solution; use feedback against the moving geometry."}
