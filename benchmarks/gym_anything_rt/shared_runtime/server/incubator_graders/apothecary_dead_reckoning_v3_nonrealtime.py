"""Independent fixed-step replay; no client success claims are authoritative."""
from __future__ import annotations

import math

MECHANIC_ID = "apothecary_dead_reckoning_v3_nonrealtime"
SHARED = ("revision", "parameters", "stage", "origin", "effects", "bones", "ingredients",
          "vortices", "flow_seed", "mechanics", "control_condition", "discovery")


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(seed, milliseconds, span):
    u = max(0, milliseconds) / span
    n = math.floor(u)
    f = u - n
    return noise(seed, n) + (noise(seed, n + 1) - noise(seed, n)) * f * f * (3 - 2 * f)


def center(item, ms):
    return [item["center"][i] + item["sway"] * motion(item["seed"] + i * 7919, ms, item["span_ms"])
            for i in range(2)]


def target_velocity(item, ms):
    # Exact derivative of the rendered smooth trajectory, also shown as an arrow.
    u = max(0, ms) / item["span_ms"]
    n = math.floor(u)
    f = u - n
    return [item["sway"] * (noise(item["seed"] + i * 7919, n + 1) - noise(item["seed"] + i * 7919, n)) *
            6 * f * (1 - f) * 1000 / item["span_ms"] for i in range(2)]


def flow(world, point, ms):
    p = world["parameters"]
    seed = world["flow_seed"]
    value = [p["current_speed"] * motion(seed + i * 7919, ms, p["current_span_ms"]) for i in range(2)]
    for vortex in world["vortices"]:
        dx, dy = point[0] - vortex["center"][0], point[1] - vortex["center"][1]
        length = math.hypot(dx, dy)
        gain = vortex["strength"] * vortex["spin"] * math.exp(-length**2 / vortex["radius"]**2)
        gain *= .7 + .3 * motion(vortex["seed"], ms, p["current_span_ms"])
        value[0] -= gain * dy / max(30, length)
        value[1] += gain * dx / max(30, length)
    return value


class Simulation:
    def __init__(self, world):
        self.world = world
        self.tick = 0
        self.position = list(world["origin"])
        self.velocity = [0., 0.]
        self.ingredient = 0
        self.grind = self.stir = self.water = 0.
        self.active = False
        self.progress = 0
        self.charge = 0.
        self.failure = ""

    @property
    def done(self):
        return self.progress == len(self.world["effects"])

    def advance(self, target_tick):
        if not self.active:
            if target_tick:
                raise ValueError("preparation cannot advance active time")
            return
        w = self.world
        p = w["parameters"]
        m = w["mechanics"]
        dt = m["tick_ms"] / 1000
        while self.tick < target_tick and not (self.failure or self.done):
            self.tick += 1
            ms = self.tick * m["tick_ms"]
            angle = math.radians(w["ingredients"][self.ingredient]["angle_deg"] + 90 * self.grind)
            current = flow(w, self.position, ms)
            dx, dy = w["origin"][0] - self.position[0], w["origin"][1] - self.position[1]
            distance = math.hypot(dx, dy)
            desired = [m["drive_speed"] * self.stir * q + current[i] +
                       m["water_speed"] * self.water * (dx if i == 0 else dy) / max(40, distance)
                       for i, q in enumerate((math.cos(angle), math.sin(angle)))]
            for i in range(2):
                self.velocity[i] += (desired[i] - self.velocity[i]) * dt / p["inertia_seconds"]
                self.position[i] += self.velocity[i] * dt
            r = m["flask_radius"]
            if any(not r <= self.position[i] <= w["stage"][axis] - r for i, axis in enumerate(("width", "height"))):
                self.failure = "The flask struck the atlas rim."
            for bone in w["bones"]:
                if math.dist(self.position, center(bone, ms)) <= r + bone["radius"]:
                    self.failure = "Bone contact spoiled the brew."
                    break
            if self.failure:
                break
            target = w["effects"][self.progress]
            inside = math.dist(self.position, center(target, ms)) + r <= target["radius"]
            slow = math.dist(self.velocity, target_velocity(target, ms)) <= p["relative_speed_limit"]
            self.charge = min(p["dwell_ms"], self.charge + m["tick_ms"]) if inside and slow else max(0., self.charge - m["tick_ms"] * m["charge_leak"])
            if self.charge >= p["dwell_ms"]:
                self.progress += 1
                self.charge = 0.
            if ms >= m["max_time_ms"] and not self.done:
                self.failure = "The brew exhausted its active time."

    def apply(self, event):
        kind = event["kind"]
        if self.failure or self.done:
            raise ValueError("action after terminal outcome")
        if kind == "begin":
            if self.active:
                raise ValueError("duplicate begin")
            self.active = True
        elif kind == "ingredient":
            index = event.get("value")
            if type(index) is not int or not 0 <= index < len(self.world["ingredients"]):
                raise ValueError("invalid ingredient")
            self.ingredient = index
        elif kind in ("grind", "stir", "water"):
            value = event.get("value")
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("invalid control value")
            setattr(self, kind, float(value))
        elif kind == "submit":
            self.failure = "Submitted an incomplete brew."
        else:
            raise ValueError("unknown action")

    def snapshot(self):
        return dict(tick=self.tick, position=list(self.position), velocity=list(self.velocity),
                    ingredient=self.ingredient, grind=self.grind, stir=self.stir, water=self.water,
                    active=self.active, progress=self.progress, charge=self.charge,
                    failure=self.failure, done=self.done)


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(value, dict) for value in (payload, ground_truth, public_state)):
            return fail("invalid apothecary result/world object")
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if not ground_truth.get(key) or ground_truth[key] != public_state.get(key) or ground_truth[key] != payload.get(key):
                return fail("stale or wrong " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != "living-atlas-1":
            return fail("wrong mechanic revision")
        if ground_truth.get("discovery") != dict(revision="mortar-course-1",
                course_reveal="mortar_sample_or_propulsion_preview", retain_learned_courses=True):
            return fail("wrong discovery revision")
        if any(ground_truth.get(k) != public_state.get(k) for k in SHARED):
            return fail("render/replay contract mismatch")
        mode = ground_truth["control_condition"]["interaction"]
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 6000:
            return fail("missing or excessive input transcript")
        action_step = ground_truth.get("mechanics", {}).get("action_step_ticks")
        if type(action_step) is not int or action_step < 1:
            return fail("invalid action transition contract")
        sim = Simulation(ground_truth)
        for seq, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("kind") not in ("begin", "submit", "ingredient", "grind", "stir", "water"):
                return fail("unknown or malformed input")
            tick = event.get("tick")
            if type(tick) is not int or not sim.tick <= tick <= ground_truth["mechanics"]["max_time_ms"] // 20 or event.get("sequence") != seq:
                return fail("invalid input time/order")
            kind = event.get("kind")
            expected = "common_button" if kind in ("begin", "submit") else ("direct_drag" if mode == "full" else "proxy_click")
            if event.get("input_source") != expected:
                return fail("wrong input surface")
            if expected == "direct_drag":
                a, b = event.get("start"), event.get("end")
                if not isinstance(a, list) or not isinstance(b, list) or len(a) != 2 or len(b) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in a + b):
                    return fail("missing physical drag endpoints")
                # Gesture endpoints are normalized to their actual rendered input
                # element, avoiding dependence on browser chrome or viewport size.
                if kind == "ingredient":
                    if not (0 <= a[0] <= 1 and 0 <= a[1] <= 1 and 0 <= b[0] <= 1 and 0 <= b[1] <= 1):
                        return fail("jar drag missed its jar/mortar")
                else:
                    current = getattr(sim, kind)
                    # The visible handle extends slightly above/below its rail.
                    if abs(a[0] - current) > .085 or not -.1 <= a[1] <= 1.1 or not 0 <= b[1] <= 1 or abs(b[0] - event.get("value", -10)) > .001:
                        return fail("drag does not start on current handle/end on value")
            if kind in ("ingredient", "grind", "stir", "water"):
                expected_tick = sim.tick + (action_step if sim.active else 0)
                if tick != expected_tick:
                    return fail("control action does not use the fixed transition step")
            elif tick != sim.tick:
                return fail("administrative action cannot advance active time")
            sim.advance(tick)
            sim.apply(event)
        final = payload.get("final_tick")
        if type(final) is not int or not sim.tick <= final <= ground_truth["mechanics"]["max_time_ms"] // 20:
            return fail("invalid final time")
        final_transition_start = sim.tick
        if final != final_transition_start:
            # A terminal collision/seal can occur part-way through the last
            # fixed transition; the browser reports that exact terminal tick.
            if not sim.active or final > sim.tick + action_step:
                return fail("final time is not a fixed action transition")
        sim.advance(final)
        if sim.tick != final:
            return fail("final time extends past terminal physics")
        if final != final_transition_start and not (sim.failure or sim.done):
            return fail("unrecorded final transition did not reach a terminal outcome")
        for key in ("position", "velocity"):
            values = payload.get(key)
            if not isinstance(values, list) or len(values) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values) or math.dist(values, getattr(sim, key)) > .002:
                return fail("final " + key + " differs from independent replay")
        if payload.get("progress") != sim.progress or payload.get("failure") != sim.failure:
            return fail("terminal outcome differs from replay")
        passed = sim.active and sim.done and not sim.failure and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=sim.failure or f"Living atlas: {sim.progress}/{len(ground_truth['effects'])} seals brewed.",
                    metrics=dict(active_time_ms=sim.tick * 20, sealed=sim.progress))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return fail("invalid apothecary transcript: " + str(exc))


def cheat(public_state, ground_truth):
    return {"note": "Use the task-specific feedback oracle; no precomputed solution is exported."}
