"""Independent fixed-step replay of scanner inputs and delayed pulse geometry.

The browser's hit reports, completion bit and final positions cannot award a pass.
This module is standalone so the exact grader can also run in pinned Pyodide.
"""
from __future__ import annotations

import copy
import math

MECHANIC_ID = "reveal_to_identify_v2"


def quantize(value, precision=1000):
    """One explicit rounding rule, shared with JS and its visible instruments."""
    return math.floor(value * precision + .5) / precision


def clamp(x, a, b):
    return max(a, min(b, x))


class Simulation:
    def __init__(self, contract):
        self.world = contract["world"]
        self.items = copy.deepcopy(contract["carriers"])
        self.wanted = contract["wanted"]
        self.tick = 0
        self.aim = [450., 250.]; self.velocity = [0., 0.]; self.target = list(self.aim)
        self.tagged = set(); self.pulses = []; self.hits = []
        self.last_fire = -1000; self.failed = ""; self.drag = False
        self.flow_state = list(self.world["flow_initial"])
        self.scanned = set()
        self.valve_history = []
        self.certify_exposure()

    def certify_exposure(self):
        for item in self.items:
            if math.dist(self.aim, [item["x"], item["y"]]) + self.world["carrier_radius"] <= self.world["lens_radius"]:
                self.scanned.add(item["id"])

    @property
    def armed(self):
        return len(self.scanned) == len(self.items)

    def desired_current(self, item, axis):
        w = self.world
        direction = 1 if item["plate"] % (2 if axis == 0 else 3) else -1
        desired = w["speed"] * direction * (self.flow_state[axis] / (18 if axis == 0 else 24)
                   + ((item["y"]-250)/500 if axis == 0 else -(item["x"]-450)/900)*.4)
        limit = w["speed"]*w["current_limit_multiplier"]
        return clamp(desired, -limit, limit)

    def advance(self, end):
        w = self.world
        end = min(end, w["duration_ms"] // 10)
        while self.tick < end and not self.failed:
            self.tick += 1; ms = self.tick * 10
            x, y, z = self.flow_state
            h = w["flow_dt"]
            self.flow_state = [quantize(x+h*w["flow_sigma"]*(y-x), w["flow_precision"]),
                               quantize(y+h*(x*(w["flow_rho"]-z)-y), w["flow_precision"]),
                               quantize(z+h*(x*y-w["flow_beta"]*z), w["flow_precision"])]
            for axis in range(2):
                acc = clamp((self.target[axis]-self.aim[axis])*w["scanner_spring"]
                            -self.velocity[axis]*w["scanner_damping"],
                            -w["scanner_acceleration"], w["scanner_acceleration"])
                self.velocity[axis] = quantize(clamp(self.velocity[axis]+acc*.01,
                                            -w["scanner_speed"], w["scanner_speed"]))
                self.aim[axis] = quantize(clamp(self.aim[axis]+self.velocity[axis]*.01,
                                       24, (w["width"] if axis == 0 else w["height"])-24))
            active = [item for item in self.items if item["id"] not in self.tagged]
            for item in active:
                for axis, pos, vel in ((0, "x", "vx"), (1, "y", "vy")):
                    current = "cx" if axis == 0 else "cy"
                    memory = w["current_memory_ms"] / 1000
                    limit = w["speed"] * w["current_limit_multiplier"]
                    item[current] = clamp(item[current]+(self.desired_current(item,axis)-item[current])*.01/memory, -limit, limit)
                    item[vel] += (item[current]-item[vel])*.01*w["current_response"]
                    item[pos] += item[vel]*.01
                    low = w["carrier_radius"]+8
                    high = (w["width"] if axis == 0 else w["height"])-low
                    if item[pos] < low or item[pos] > high:
                        item[pos] = clamp(item[pos], low, high); item[vel] *= -.9
            # Finite circles collide symmetrically; tagged carriers leave the tank.
            # Resolve joint circle/wall contacts, including separation that pushes
            # a neighbouring carrier into a wall. Keep positions inside the tank.
            for _ in range(8):
                changed = False
                for i, a in enumerate(active):
                    for b in active[i+1:]:
                        dx, dy = b["x"]-a["x"], b["y"]-a["y"]
                        distance = math.hypot(dx, dy); diameter = 2*w["carrier_radius"]
                        if 0 < distance < diameter-1e-8:
                            changed = True
                            nx, ny = dx/distance, dy/distance
                            shift = (diameter-distance)/2
                            a["x"] -= nx*shift; a["y"] -= ny*shift
                            b["x"] += nx*shift; b["y"] += ny*shift
                            relative = (b["vx"]-a["vx"])*nx+(b["vy"]-a["vy"])*ny
                            if relative < 0:
                                impulse = -.9*relative
                                a["vx"] -= impulse*nx; a["vy"] -= impulse*ny
                                b["vx"] += impulse*nx; b["vy"] += impulse*ny
                for item in active:
                    for pos, vel, extent in (("x", "vx", w["width"]), ("y", "vy", w["height"])):
                        low = w["carrier_radius"]+8; high = extent-low
                        if item[pos] < low or item[pos] > high:
                            changed = True
                            if (item[pos] < low and item[vel] < 0) or (item[pos] > high and item[vel] > 0):
                                item[vel] *= -.9
                            item[pos] = clamp(item[pos], low, high)
                if not changed:
                    break
            for item in active:
                for key in ("x", "y", "vx", "vy", "cx", "cy"):
                    item[key] = quantize(item[key])
            self.certify_exposure()
            for pulse in list(self.pulses):
                if ms >= pulse["due_ms"]:
                    self.pulses.remove(pulse)
                    candidates = [(math.hypot(item["x"]-pulse["point"][0], item["y"]-pulse["point"][1]), item)
                                  for item in active if item["id"] not in self.tagged]
                    candidates.sort(key=lambda pair: (pair[0], pair[1]["id"]))
                    hit = candidates[0][1] if candidates and candidates[0][0] <= w["carrier_radius"]+w["pulse_radius"] else None
                    self.hits.append(dict(tick=self.tick, point=list(pulse["point"]),
                                          carrier_id=hit["id"] if hit else None))
                    if hit is None:
                        self.failed = "PULSE MISSED"
                    elif hit["glyph"] not in self.wanted:
                        self.failed = "PROTECTED SPECIMEN TAGGED"
                    else:
                        self.tagged.add(hit["id"])
                        if len(self.tagged) < w["targets"]:
                            code = w["valve_program"][len(self.tagged)-1]
                            self.flow_state = list(w["valve_presets"][code])
                            self.valve_history.append(dict(tick=self.tick, code=code))
                            for body in active:
                                if body["id"] not in self.tagged:
                                    body["cx"] = quantize(self.desired_current(body,0))
                                    body["cy"] = quantize(self.desired_current(body,1))
                    if self.failed:
                        break
            if ms >= w["duration_ms"] and len(self.tagged) < w["targets"]:
                self.failed = "TANK CLOSED"

    def fire(self):
        ms = self.tick*10
        if not self.armed or self.failed or ms-self.last_fire < self.world["pulse_cooldown_ms"]:
            return False
        self.last_fire = ms
        self.pulses.append(dict(point=list(self.aim), due_ms=ms+self.world["pulse_lag_ms"]))
        return True


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    if not all(isinstance(x, dict) for x in (payload, ground_truth, public_state)):
        return fail("malformed bundle")
    for key in ("mechanic_id", "revision", "task_id", "challenge_id"):
        if not ground_truth.get(key) or any(x.get(key) != ground_truth[key] for x in (payload, public_state)):
            return fail("stale or wrong "+key)
    if ground_truth["mechanic_id"] != MECHANIC_ID:
        return fail("wrong mechanic")
    for key in ("world", "carriers", "wanted", "control_condition"):
        if public_state.get(key) != ground_truth.get(key):
            return fail("render/replay mismatch: "+key)
    mode = (ground_truth.get("control_condition") or {}).get("interaction")
    if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
        return fail("wrong interaction")
    events = payload.get("events")
    if not isinstance(events, list) or not 2 <= len(events) <= 12000:
        return fail("missing or excessive trace")
    sim = Simulation(ground_truth)
    try:
        for seq, event in enumerate(events, 1):
            tick = event["tick"]; kind = event["kind"]
            if type(tick) is not int or not sim.tick <= tick <= 15000 or event.get("sequence") != seq:
                return fail("invalid event ordering/time")
            if event.get("input_source") != ("start_button" if kind == "start" else
                                            "certify_button" if kind == "certify" else
                                            "scanner_drag" if mode == "full" and kind != "fire" else
                                            "pulse_key" if mode == "full" else
                                            "aim_click" if kind == "aim" else "pulse_button"):
                return fail("wrong input surface")
            if seq == 1:
                if kind != "start" or tick != 0:
                    return fail("run must start once at zero")
                continue
            sim.advance(tick)
            if sim.failed:
                return fail("terminal failure: "+sim.failed)
            if kind in ("aim", "drag_start", "drag_move", "drag_end"):
                point = event["point"]
                if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point):
                    return fail("invalid aim coordinate")
                if not 0 <= point[0] <= 900 or not 0 <= point[1] <= 500:
                    return fail("aim outside the tank")
                if mode == "simplified" and kind != "aim":
                    return fail("drag on simplified surface")
                if mode == "full":
                    if kind == "drag_start":
                        if sim.drag or math.dist(point, sim.aim) > sim.world["scanner_handle_radius"]+.02:
                            return fail("scanner was not grabbed by its visible handle")
                        sim.drag = True
                    elif kind == "drag_end" and sim.drag:
                        sim.drag = False
                    elif kind != "drag_move" or not sim.drag:
                        return fail("invalid scanner drag")
                sim.target = list(point)
            elif kind == "fire":
                if not sim.fire():
                    return fail("pulse fired before optical certification or recharge")
            elif kind == "certify":
                if seq != len(events):
                    return fail("certification must end the trace")
            else:
                return fail("reset, hold-world or unknown action")
        final = payload.get("final_tick")
        if type(final) is not int or not sim.tick <= final <= 15000:
            return fail("invalid final time")
        sim.advance(final)
        wanted_ids = {x["id"] for x in ground_truth["carriers"] if x["glyph"] in ground_truth["wanted"]}
        if sim.failed:
            return fail("terminal failure: "+sim.failed)
        if sim.tagged != wanted_ids or sim.pulses or payload.get("completed") is not True:
            return fail("requested specimens remain untagged")
        if payload.get("tagged_ids") != sorted(sim.tagged):
            return fail("claimed tags disagree with independent replay")
        return dict(graded=True, passed=True, score=100,
                    feedback=f"scanner replay: {len(sim.tagged)} requested specimens tagged; {final*10} ms")
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        return fail("invalid scanner trace: "+str(exc))


def cheat(public_state, ground_truth):
    return dict(wanted_ids=ground_truth.get("wanted_ids", []))
