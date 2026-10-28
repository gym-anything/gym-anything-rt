"""Independent fixed-step replay of the robot's kinematic feet and inertial body.

This is a reduced contact model, not a MuJoCo rigid-body simulation. A planted
toe sticks to its plate, a commanded stroke lifts and extends a single foot,
and the body follows a damped second-order actuator under lateral disturbance.
Support is the convex hull of finite-radius planted toes.
"""
from __future__ import annotations

import copy
import math
import os
import json
from pathlib import Path

MECHANIC_ID = "crater_walker_v3"
LEGS = ("FL", "FR", "RL", "RR")


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(seed, ms, span):
    u = max(0, ms) / span
    n, f = math.floor(u), u - math.floor(u)
    a, b = noise(seed, n), noise(seed, n + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def tape_position(knots, ms, span):
    u = max(0, ms)/span
    n, f = math.floor(u), u - math.floor(u)
    a, b = knots[n:n+2]
    blend = f*f*(3-2*f)
    return [x+(y-x)*blend for x,y in zip(a,b)]


def pad_position(world, pad, ms):
    values = tape_position(pad["knots"], ms, world["parameters"]["span_ms"])
    return [x + amp * value for x,amp,value in zip(pad["base"],pad["amplitude"],values)]


def hull(points):
    points = sorted(set((p[0], p[1]) for p in points))
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def margin(point, polygon):
    if len(polygon) < 3:
        return -100.
    inside, distance = True, float("inf")
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        inside &= dx*(point[1]-a[1]) - dy*(point[0]-a[0]) >= -1e-10
        t = max(0, min(1, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
        distance = min(distance, math.hypot(point[0]-a[0]-t*dx, point[1]-a[1]-t*dy))
    return distance if inside else -distance


class Simulation:
    def __init__(self, world):
        self.world = world
        self.pads = {p["id"]: p for p in world["pads"]}
        self.ms, self.active, self.failed, self.complete = 0, False, "", False
        guided = world["parameters"].get("guided_legs")
        self.contacts = {leg: f"{leg}-{world['parameters']['terraces'] if guided and leg not in guided else 0}" for leg in LEGS}
        self.offsets = {leg: [0., 0.] for leg in LEGS}
        self.swing = None
        self.ballast = [0., 0.]
        self.body = self.center(0)
        self.body[2] += .95
        self.velocity = [0., 0.]
        self.unstable_ms = 0
        self.landings = []

    def feet(self, ms=None):
        ms = self.ms if ms is None else ms
        result = {}
        for leg in LEGS:
            if self.swing and self.swing["leg"] == leg:
                s = self.swing
                f = max(0, min(1, (ms-s["start_ms"])/self.world["swing_ms"]))
                blend = f*f*(3-2*f)
                result[leg] = [s["start"][i]+(s["end"][i]-s["start"][i])*blend for i in range(3)]
                surface = pad_position(self.world, self.pads[s["destination"]], ms)[2]
                result[leg][2] = s["start"][2] + (surface-s["start"][2])*blend
                result[leg][2] += self.world["lift_clearance"] * 4*f*(1-f)
            else:
                p = pad_position(self.world, self.pads[self.contacts[leg]], ms)
                result[leg] = [p[0]+self.offsets[leg][0], p[1]+self.offsets[leg][1], p[2]]
        return result

    def center(self, ms=None):
        f = self.feet(ms)
        return [sum(p[i] for p in f.values())/4 for i in range(3)]

    def polygon(self):
        return hull([p for leg, p in self.feet().items() if not self.swing or leg != self.swing["leg"]])

    def launch(self):
        if self.active:
            raise ValueError("the traverse already started")
        self.active = True

    def set_ballast(self, target):
        if self.world.get("guide"):
            raise ValueError("the guide carries the chassis; ballast is unavailable")
        if any(abs(v) > self.world["ballast_limit"] + 1e-6 for v in target):
            raise ValueError("ballast outside actuator range")
        self.ballast = list(target)

    def step(self, leg, target):
        if not self.active or self.swing or self.failed or self.complete:
            raise ValueError("foot stroke unavailable")
        if leg not in LEGS:
            raise ValueError("unknown leg")
        old = self.pads[self.contacts[leg]]
        if old["terrace"] == self.world["parameters"]["terraces"]:
            raise ValueError("foot already on the rim")
        destination = self.pads[f"{leg}-{old['terrace']+1}"]
        # A robot stroke follows a commanded endpoint, not a pad identity.
        # Vertical actuator aims at the known next terrace's nominal height.
        start = self.feet()[leg]
        end = [target[0], target[1], destination["base"][2]]
        if math.dist(start[:2], end[:2]) > 5.5:
            self.failed = "Foot stroke exceeded its extension range."
            return
        self.swing = dict(leg=leg, start=list(start), end=end, start_ms=self.ms,
                          destination=destination["id"])

    def advance(self, end_ms):
        if not self.active:
            return
        w, p = self.world, self.world["parameters"]
        while self.ms + w["tick_ms"] <= end_ms and not self.failed and not self.complete:
            self.ms += w["tick_ms"]
            dt = w["tick_ms"]/1000
            center = self.center()
            if w.get("guide"):
                for i in range(2):
                    self.velocity[i] = (center[i]-self.body[i])/dt
                    self.body[i] = center[i]
            else:
                k = p["body_response"]
                for i in range(2):
                    wind = p["wind"] * tape_position(w["wind"]["knots"], self.ms, w["wind"]["span_ms"])[i]
                    a = k*(center[i]+self.ballast[i]-self.body[i]) - 2*math.sqrt(k)*self.velocity[i] + wind
                    self.velocity[i] += a*dt
                    self.body[i] += self.velocity[i]*dt
            self.body[2] = center[2] + .95
            if self.swing and self.ms - self.swing["start_ms"] >= w["swing_ms"]:
                s = self.swing
                pad = self.pads[s["destination"]]
                pos = pad_position(w, pad, self.ms)
                # Entire circular toe must fit on the visible circular top.
                if math.dist(s["end"][:2], pos[:2]) + w["toe_radius"] > pad["radius"] + 1e-8:
                    self.failed = "A foot missed the drifting plate."
                    break
                # Telescopic vertical compliance is visible in the leg, not a
                # point below an unrelated decorative surface.
                leg = s["leg"]
                self.contacts[leg] = pad["id"]
                self.offsets[leg] = [s["end"][i]-pos[i] for i in range(2)]
                self.landings.append(dict(ms=self.ms, leg=leg, pad=pad["id"], point=self.feet()[leg]))
                self.swing = None
            feet = self.feet()
            if any(math.dist(self.body[:2], f[:2]) > w["max_leg_reach"] for f in feet.values()):
                self.failed = "A planted leg ran out of extension."
                break
            if not w.get("guide"):
                balance = margin(self.body, self.polygon()) + w["toe_radius"]
                self.unstable_ms = self.unstable_ms + w["tick_ms"] if balance < 0 else 0
                if self.unstable_ms >= p["tip_ms"]:
                    self.failed = "The body toppled outside its support polygon."
                    break
            if not self.swing and all(self.pads[self.contacts[leg]]["terrace"] == p["terraces"] for leg in LEGS):
                self.complete = True
            elif self.ms >= w["max_ms"]:
                self.failed = "Traverse time exhausted."

    def snapshot(self):
        return dict(ms=self.ms, active=self.active, failed=self.failed, complete=self.complete,
                    body=list(self.body), velocity=list(self.velocity), ballast=list(self.ballast),
                    contacts=copy.deepcopy(self.contacts), offsets=copy.deepcopy(self.offsets),
                    swing=copy.deepcopy(self.swing), unstable_ms=self.unstable_ms,
                    landings=copy.deepcopy(self.landings))


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("nonfinite or nonnumeric input")
    return value


def point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("coordinate pair required")
    return [number(x) for x in value]


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(x, dict) for x in (payload, ground_truth, public_state)):
            return fail("invalid replay objects")
        for state in (payload, ground_truth, public_state):
            if type(state.get("episode_failed", False)) is not bool or state.get("episode_failed", False):
                return fail("A failed submission already ended this episode.")
        directory = os.environ.get("GYM_ANYTHING_RT_STATE_DIR")
        if directory:
            try:
                with (Path(directory) / "attempts.jsonl").open(encoding="utf-8") as journal:
                    for line in journal:
                        if line.strip() and not json.loads(line).get("server_grade", {}).get("passed"):
                            return fail("A failed submission already ended this episode.")
            except FileNotFoundError:
                pass
            except (OSError, UnicodeError, ValueError, AttributeError):
                return fail("Episode failure history is unavailable.")
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or mismatched " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("world", "control_condition", "survey"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public contract mismatch: " + key)
        mode = ground_truth["control_condition"]["interaction"]
        if payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 5000:
            return fail("missing or excessive input trace")
        sim = Simulation(ground_truth["world"])
        survey = ground_truth["survey"]
        surveyed = set(survey["initially_known"])
        hold = None
        previous = 0
        for seq, e in enumerate(events, 1):
            if not isinstance(e, dict):
                return fail("input event must be an object")
            ms = e.get("t_ms")
            if type(ms) is not int or not previous <= ms <= sim.world["max_ms"] or ms % 10 or e.get("seq") != seq:
                return fail("invalid event ordering or time")
            previous = ms
            sim.advance(ms)
            if sim.failed or sim.complete:
                return fail("input after terminal physics")
            kind, source = e.get("kind"), e.get("input_source")
            if kind == "launch":
                if ms != 0 or source != "launch_button":
                    return fail("invalid launch")
                sim.launch()
            elif kind == "survey":
                if hold or source != "survey_pointer":
                    return fail("survey must use an unheld chart pointer")
                location = point(e.get("point"))
                known = surveyed | set(sim.contacts.values())
                revealed = [p["id"] for p in sim.world["pads"] if p["id"] not in known
                            and math.dist(location, pad_position(sim.world, p, sim.ms)[:2]) <= survey["radius"]]
                if not revealed or e.get("revealed") != revealed:
                    return fail("survey observation disagrees with pointer and live plates")
                surveyed.update(revealed)
            elif kind == "ballast":
                if source != ("ballast_drag" if mode == "full" else "ballast_click"):
                    return fail("wrong ballast surface")
                if mode == "full" and (not hold or hold["kind"] != "ballast"):
                    return fail("ballast drag without pointer hold")
                sim.set_ballast(point(e.get("target")))
            elif kind == "aim_start":
                if hold or source != ("foot_drag" if mode == "full" else "foot_click"):
                    return fail("invalid foot selection")
                leg = e.get("leg")
                if leg not in LEGS or sim.swing:
                    return fail("unavailable foot")
                # Selection is a real hit on the current visible toe.
                if math.dist(point(e.get("point")), sim.feet()[leg][:2]) > .23:
                    return fail("foot selection misses the visible toe")
                hold = dict(kind="foot", leg=leg)
            elif kind == "ballast_start":
                if sim.world.get("guide") or mode != "full" or source != "ballast_drag" or hold:
                    return fail("invalid ballast hold")
                if math.dist(point(e.get("point")), sim.ballast) > .40:
                    return fail("ballast hold misses the handle")
                hold = dict(kind="ballast")
            elif kind == "release":
                if not hold or hold["kind"] != "ballast" or source != "ballast_drag":
                    return fail("invalid handle release")
                hold = None
            elif kind == "step":
                if not hold or hold["kind"] != "foot" or source != ("foot_drag" if mode == "full" else "foot_click"):
                    return fail("step without bound foot selection")
                if e.get("leg") != hold["leg"]:
                    return fail("selected leg mismatch")
                sim.step(hold["leg"], point(e.get("target")))
                hold = None
            elif kind == "cancel":
                if source not in ("cancel_button", "cancel_key") or not hold:
                    return fail("invalid cancellation")
                hold = None
            else:
                return fail("unknown input; reset and stop are unavailable")
        final = payload.get("final_ms")
        if type(final) is not int or not previous <= final <= sim.world["max_ms"] or final % 10:
            return fail("invalid final time")
        sim.advance(final)
        if payload.get("completed") is not True or not sim.complete or sim.failed:
            return fail(sim.failed or "all four feet have not reached the rim")
        # Reaching the rim ends physics and releases a UI grip. A player may
        # still be holding the weight handle through the final landing.
        if hold and hold["kind"] != "ballast":
            return fail("unfinished pointer interaction")
        if payload.get("contacts") != sim.contacts or payload.get("landings") != [{"ms":x["ms"], "leg":x["leg"], "pad":x["pad"]} for x in sim.landings]:
            return fail("final contact ledger disagrees with replay")
        return dict(graded=True, passed=True, score=100,
                    feedback=f"replayed {len(sim.landings)} moving-plate landings; four feet escaped at {sim.ms}ms")
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        return fail("invalid crater transcript: " + str(exc))


def cheat(public_state, ground_truth):
    return {"notice": "No static solution. Read current plate motion and support geometry."}
