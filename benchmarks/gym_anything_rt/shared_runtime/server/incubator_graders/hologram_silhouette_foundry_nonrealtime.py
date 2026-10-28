"""Independent fixed-step optical/servo replay, also executable in Pyodide."""
from __future__ import annotations

import math

MECHANIC_ID = "hologram_silhouette_foundry_nonrealtime"
REVISION = "moving-three-die-v2-separated-motion-action-stepped"
TIMING_RULE = {
    "mode": "action_stepped",
    "action_tick_ms": 20,
    "wait_behavior": "stable_until_deliberate_control",
    "advances_on": "accepted_gantry_action",
}


def noise(seed, index):
    x = (int(seed) ^ ((index + 1) * 0x9E3779B9)) & 0xffffffff
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff) / 4294967295 * 2 - 1


def target(state, ms):
    spec = state["motion"]
    u = max(0, ms) / spec["span_ms"]
    n, f = math.floor(u), u % 1
    smooth = f * f * (3 - 2 * f)
    n = min(n,len(spec["waypoints"])-2)
    a,b = spec["waypoints"][n:n+2]
    return [x*(1-smooth)+y*smooth for x,y in zip(a,b)]


def transform(point, pose):
    x, y, z = point
    yaw, pitch = pose[3:]
    x, z = x*math.cos(yaw)+z*math.sin(yaw), -x*math.sin(yaw)+z*math.cos(yaw)
    y, z = y*math.cos(pitch)-z*math.sin(pitch), y*math.sin(pitch)+z*math.cos(pitch)
    return [x+pose[0], y+pose[1], z+pose[2]]


def projection_errors(state, pose, goal):
    errors = [0., 0., 0.]
    for rod in state["rods"]:
        for point in rod["ends"]:
            a, b = transform(point, pose), transform(point, goal)
            d = [a[i]-b[i] for i in range(3)]
            for i, (u,v) in enumerate(((0,1),(2,1),(0,2))):
                errors[i] = max(errors[i], math.hypot(d[u], d[v]))
    return errors


class Simulation:
    def __init__(self, state):
        self.state = state
        self.ms = 0
        self.pose = list(state["initial_pose"])
        self.command = list(self.pose)
        self.velocity = [0.] * 5
        self.start_ms = None
        self.fusion = 0.
        self.phase = "prepare"
        self.errors = projection_errors(state, self.pose, target(state, 0))

    def ignite(self):
        if self.phase != "prepare":
            raise ValueError("one ignition per episode")
        self.phase = "active"
        self.start_ms = self.ms

    def advance_action(self):
        p = self.state["parameters"]
        if self.phase in ("fused", "failed"):
            return
        self.ms += self.state["timing_rule"]["action_tick_ms"]
        for i in range(5):
            delta = self.command[i] - self.pose[i]
            a = max(-p["servo_acceleration"], min(p["servo_acceleration"], delta*64-self.velocity[i]*16))
            self.velocity[i] = max(-p["servo_speed"], min(p["servo_speed"], self.velocity[i]+a*.02))
        speed = sum(abs(v) for v in self.velocity)
        if speed > p["shared_speed"]:
            self.velocity = [v*p["shared_speed"]/speed for v in self.velocity]
        for i in range(5):
            self.pose[i] += self.velocity[i]*.02
            self.pose[i] = max(-self.state["limits"][i], min(self.state["limits"][i], self.pose[i]))
        goal = target(self.state, self.ms-self.start_ms if self.start_ms is not None else 0)
        self.errors = projection_errors(self.state, self.pose, goal)
        if self.phase == "active":
            matched = max(self.errors) <= p["tolerance"]
            self.fusion = max(0., min(p["fusion_seconds"], self.fusion + (.02 if matched else -.02*p["leak_rate"])))
            if self.fusion >= p["fusion_seconds"] - 1e-8:
                self.phase = "fused"
            elif self.ms-self.start_ms >= self.state["run_limit_ms"]:
                self.phase = "failed"


def number(x):
    if type(x) not in (int, float) or not math.isfinite(x):
        raise ValueError("non-finite coordinate or time")
    return x


def rail_point(point, axis):
    if not isinstance(point, list) or len(point) != 2:
        raise ValueError("invalid pointer coordinate")
    x,y = [number(v) for v in point]
    if not 938 <= x <= 1100 or abs(y-(148+axis*69)) > 23:
        raise ValueError("input is outside its visible gantry rail")
    return max(950, min(1088, x))


def command_x(state, command, axis):
    return 1019 + command[axis]/state["limits"][axis]*69


def grade(payload, truth, public):
    def fail(reason):
        return dict(graded=True, passed=False, score=0, feedback=reason)
    try:
        for k in ("mechanic_id", "revision", "task_id", "challenge_id"):
            if not truth.get(k) or payload.get(k) != truth[k] or public.get(k) != truth[k]:
                return fail("stale or wrong " + k)
        if truth["mechanic_id"] != MECHANIC_ID or truth["revision"] != REVISION:
            return fail("wrong casting revision")
        for k in ("control_condition", "rods", "motion", "parameters", "timing_rule", "initial_pose", "limits", "tick_ms", "run_limit_ms", "stage"):
            if truth.get(k) != public.get(k):
                return fail("public contract differs: " + k)
        if truth.get("timing_rule") != TIMING_RULE:
            return fail("wrong action-stepped timing rule")
        mode = truth["control_condition"]["interaction"]
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 8000:
            return fail("missing or oversized transcript")
        sim = Simulation(truth)
        previous, held, sealed = -1, None, False
        for seq, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("sequence") != seq:
                return fail("event ordering is invalid")
            ms = number(event["t_ms"])
            if not previous <= ms <= 360000 or ms % 20 != 0:
                return fail("invalid fixed-step event time")
            previous = ms
            kind = event["kind"]
            if sealed:
                return fail("events after terminal submission")
            if kind == "timeout":
                if event.get("input_source") != "clock" or sim.phase != "failed" or ms != sim.ms:
                    return fail("invalid action-triggered timeout")
                sealed = True
                continue
            if kind == "ignite":
                if event.get("input_source") != "button" or held is not None or sim.phase != "prepare" or ms != sim.ms:
                    return fail("invalid ignition")
                sim.ignite()
                continue
            if kind in ("drag_start", "drag_move", "drag_end", "set"):
                if sim.phase in ("failed", "fused"):
                    return fail("control after terminal casting")
                sim.advance_action()
                if sim.phase in ("failed", "fused") or ms != sim.ms:
                    return fail("control is not available after its action tick")
                axis = event["axis"]
                if type(axis) is not int or not 0 <= axis < truth["parameters"]["active_axes"]:
                    return fail("inactive gantry axis")
                source = "gantry_drag" if mode == "full" else "rail_click"
                if event.get("input_source") != source:
                    return fail("wrong control surface")
                x = rail_point(event["point"], axis)
                if kind == "drag_start":
                    if mode != "full" or held is not None or abs(x-command_x(truth,sim.command,axis)) > 18:
                        return fail("drag must start on the visible handle")
                    held = axis
                elif kind == "set":
                    if mode != "simplified" or held is not None:
                        return fail("click proxy unavailable in full interaction")
                    sim.command[axis] = (x-1019)/69*truth["limits"][axis]
                else:
                    if mode != "full" or held != axis:
                        return fail("no corresponding gantry drag")
                    sim.command[axis] = (x-1019)/69*truth["limits"][axis]
                    if kind == "drag_end":
                        held = None
            elif kind == "submit":
                if event.get("input_source") != "button":
                    return fail("invalid certification input")
                phase_before_action = sim.phase
                if sim.phase not in ("fused", "failed"):
                    sim.advance_action()
                    if phase_before_action == "active" and sim.phase == "failed":
                        return fail("terminal action must be recorded as timeout")
                if ms != sim.ms:
                    return fail("submission time does not match action step")
                sealed = True
                if sim.phase != "fused":
                    sim.phase = "failed"
            else:
                return fail("unknown or reset event")
        if payload.get("final_t_ms") != sim.ms or payload.get("phase") != sim.phase:
            return fail("terminal report disagrees with replay")
        if abs(number(payload.get("fusion_seconds"))-sim.fusion) > 1e-5:
            return fail("reported fusion disagrees with replay")
        passed = sealed and sim.phase == "fused" and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"Three-die replay: {sim.phase}, {sim.fusion:.2f}/{truth['parameters']['fusion_seconds']:.2f}s fusion")
    except (KeyError, ValueError, TypeError, OverflowError, IndexError) as exc:
        return fail("invalid foundry transcript: " + str(exc))


def cheat(public, truth):
    return {"motion": truth.get("motion"), "rods": truth.get("rods")}
