"""Standalone independent fixed-step replay, also shipped to Pyodide."""
from __future__ import annotations

import math

MECHANIC_ID = "lantern_loft_v2"
REVISION = "drifting-stairwalks-v1"


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def gust(deck, ms, world):
    u = max(0, ms)/world["parameters"]["gust_span_ms"]
    i = math.floor(u)
    f = u-i
    return world["parameters"]["gust_force"]*(noise(deck["gust_seed"], i)*(1-f*f*(3-2*f)) + noise(deck["gust_seed"], i+1)*f*f*(3-2*f))


class LoftPhysics:
    def __init__(self, world):
        self.world = world
        self.ms = 0
        self.active = False
        self.failed = ""
        self.solved = False
        self.deck = 0
        self.local_x = world["decks"][0]["in_x"]
        self.x = self.local_x
        self.vx = 0.0
        self.walk = set()
        self.positions = [float(d["initial_x"]) for d in world["decks"]]
        self.velocities = [float(d["initial_v"]) for d in world["decks"]]
        self.commands = [0]*len(self.positions)
        self.crossing = None

    def start(self):
        if self.active or self.failed or self.solved:
            raise ValueError("launch is only available once")
        self.active = True

    def set_motor(self, index, value):
        if type(index) is not int or not 0 < index < len(self.positions)-1 or type(value) is not int or value not in (-1, 0, 1):
            raise ValueError("invalid winch detent")
        self.commands[index] = value

    def set_walk(self, direction, held):
        if direction not in (-1, 1) or type(direction) is not int or type(held) is not bool or (direction in self.walk) == held:
            raise ValueError("invalid or duplicate walk transition")
        if held:
            self.walk.add(direction)
        else:
            self.walk.remove(direction)

    def cross(self):
        if not self.active or self.crossing or self.failed or self.solved:
            return False
        d = self.world["decks"][self.deck]
        half = self.world["parameters"]["port_width"]/2-self.world["radius"]
        ports = [(d["out_x"], d["out_height"])]
        if self.world["parameters"]["false_ports"] and d["in_height"] != d["out_height"]:
            ports.append((d["in_x"], d["in_height"]))
        hit = next((p for p in ports if abs(self.local_x-p[0]) <= half), None)
        if hit is None:
            return False  # Safe probe: there is a parapet here, not a path.
        self.crossing = dict(start_ms=self.ms, port_x=hit[0], height=hit[1])
        self.x = self.positions[self.deck]+self.local_x
        self.vx += self.velocities[self.deck]
        return True

    def advance(self, end_ms):
        w = self.world
        while self.active and self.ms+20 <= end_ms and not (self.failed or self.solved):
            self.ms += 20
            dt = .02
            for i, d in enumerate(w["decks"]):
                if not d["moving"]:
                    continue
                motor = self.commands[i]
                motor -= w["parameters"]["coupling"]*(self.commands[i-1]+self.commands[i+1])
                a = w["motor_force"]*motor+gust(d, self.ms, w)-w["spring"]*self.positions[i]-w["damping"]*self.velocities[i]
                self.velocities[i] = clamp(self.velocities[i]+a*dt, -w["deck_speed"], w["deck_speed"])
                self.positions[i] = clamp(self.positions[i]+self.velocities[i]*dt, -w["rail_limit"], w["rail_limit"])
                if abs(self.positions[i]) == w["rail_limit"]:
                    self.velocities[i] = 0.0
            thrust = int(1 in self.walk)-int(-1 in self.walk)
            self.vx = clamp(self.vx+(thrust*w["walk_acceleration"]-w["walk_damping"]*self.vx)*dt, -w["walk_speed"], w["walk_speed"])
            if not self.crossing:
                self.local_x = clamp(self.local_x+self.vx*dt, -w["body_half_width"]+w["radius"], w["body_half_width"]-w["radius"])
                if abs(self.local_x) == w["body_half_width"]-w["radius"]:
                    self.vx = 0.0
                self.x = self.positions[self.deck]+self.local_x
            else:
                self.x += self.vx*dt
                f = (self.ms-self.crossing["start_ms"])/w["parameters"]["crossing_ms"]
                y = 130*f
                src = w["decks"][self.deck]
                dst = w["decks"][self.deck+1]
                radius = w["radius"]
                # A rectangular 16x16 sole must be supported on both sides of
                # a seam. These are exactly the body and neck rectangles drawn.
                safe = True
                if y-radius < 65:
                    center = self.positions[self.deck]
                    half = w["body_half_width"]
                    if y+radius > 40:
                        center += self.crossing["port_x"]
                        half = w["parameters"]["port_width"]/2
                    safe = abs(self.x-center)+radius <= half
                if y+radius > 65:
                    center = self.positions[self.deck+1]
                    half = w["body_half_width"]
                    if y-radius < 90:
                        center += dst["in_x"]
                        half = w["parameters"]["port_width"]/2
                    safe = safe and abs(self.x-center)+radius <= half and self.crossing["height"] == dst["in_height"]
                if not safe:
                    self.failed = "The lantern fell from an unsupported edge."
                elif f >= 1:
                    self.deck += 1
                    self.local_x = self.x-self.positions[self.deck]
                    self.vx -= self.velocities[self.deck]
                    self.crossing = None
                    self.solved = self.deck == len(w["decks"])-1
            if self.ms >= w["max_ms"] and not self.solved:
                self.failed = "The flight ended before the beacon was reached."

    def snapshot(self):
        return dict(ms=self.ms, active=self.active, failed=self.failed, solved=self.solved, deck=self.deck,
            local_x=self.local_x, x=self.x, vx=self.vx, positions=list(self.positions), velocities=list(self.velocities),
            commands=list(self.commands), walk=sorted(self.walk), crossing=self.crossing)


def grade(payload, ground_truth, public_state):
    def fail(text):
        return dict(graded=True, passed=False, score=0, feedback=text)
    try:
        if any(v.get("mechanic_id") != MECHANIC_ID for v in (payload, ground_truth, public_state)):
            return fail("wrong mechanic")
        for k in ("task_id", "challenge_id"):
            if not ground_truth.get(k) or payload.get(k) != ground_truth[k] or public_state.get(k) != ground_truth[k]:
                return fail("stale or wrong "+k)
        for k in ("world", "control_condition", "single_attempt"):
            if public_state.get(k) != ground_truth.get(k):
                return fail("public contract mismatch: "+k)
        w = ground_truth["world"]
        if w["revision"] != REVISION or payload.get("revision") != REVISION:
            return fail("wrong physics revision")
        mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction")
        events = payload.get("events")
        if not isinstance(events, list) or not events:
            return fail("missing input trace")
        sim = LoftPhysics(w)
        held = None
        sealed = False
        previous_ms = -1
        for seq, e in enumerate(events, 1):
            ms = e["t_ms"]
            if type(ms) is not int or ms % 20 or not previous_ms <= ms <= w["max_ms"] or e.get("seq") != seq or sealed:
                return fail("invalid input order or task time")
            previous_ms = ms
            if not sim.active and ms != 0:
                return fail("task time before launch")
            sim.advance(ms)
            if sim.ms != ms or sim.failed:
                return fail(sim.failed or "input after terminal state")
            kind = e["kind"]
            if kind == "start":
                if e.get("input_source") != "launch_button":
                    return fail("wrong launch input")
                sim.start()
            elif kind == "motor" and mode == "simplified":
                if e.get("input_source") != "winch_buttons":
                    return fail("wrong winch input")
                sim.set_motor(e["deck"], e["value"])
            elif kind in ("lever_down", "lever_move", "lever_up") and mode == "full":
                if e.get("input_source") != "lever_drag":
                    return fail("wrong lever input")
                p = e.get("point")
                if not isinstance(p, list) or len(p) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in p):
                    return fail("invalid lever point")
                i = e["deck"]
                if type(i) is not int or not 0 < i < len(sim.positions)-1:
                    return fail("invalid lever")
                if kind == "lever_down":
                    if held is not None or abs(p[0]-(80+sim.commands[i]*48)) > 19 or not 0 <= p[1] <= 40:
                        return fail("drag must begin on the visible lever handle")
                    held = i
                else:
                    if held != i:
                        return fail("lever is not held")
                    if kind == "lever_move":
                        value = -1 if p[0] < 56 else 1 if p[0] > 104 else 0
                        sim.set_motor(i, value)
                    else:
                        held = None
            elif kind == "walk":
                source = "keyboard" if mode == "full" else "walk_buttons"
                if not sim.active or sim.solved or e.get("input_source") != source:
                    return fail("wrong walk input")
                sim.set_walk(e["direction"], e["held"])
            elif kind == "cross":
                source = "keyboard" if mode == "full" else "cross_button"
                if sim.solved or e.get("input_source") != source or type(e.get("accepted")) is not bool or sim.cross() != e["accepted"]:
                    return fail("false crossing or wrong input surface")
            elif kind == "seal":
                if e.get("input_source") not in ("seal_button", "terminal_contact"):
                    return fail("wrong certification input")
                sealed = True
            else:
                return fail("unsupported input or reset")
        if not sealed or payload.get("final_t_ms") != sim.ms or payload.get("completed") is not True or not sim.solved or sim.failed:
            return fail("the lantern has not reached the beacon")
        final = payload.get("final_state", {})
        for key in ("x", "local_x", "vx"):
            x = final.get(key)
            if type(x) not in (int, float) or not math.isfinite(x) or abs(x-getattr(sim, key)) > .005:
                return fail("false final "+key)
        if final.get("deck") != sim.deck or final.get("positions") is None or len(final["positions"]) != len(sim.positions) or any(type(a) not in (int, float) or not math.isfinite(a) or abs(a-b) > .005 for a, b in zip(final["positions"], sim.positions)):
            return fail("false final physical state")
        return dict(graded=True, passed=True, score=100, feedback=f"fixed-step stairwalk replay reached the beacon at {sim.ms} ms")
    except (AttributeError, KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        return fail("invalid stairwalk transcript: "+str(exc))
