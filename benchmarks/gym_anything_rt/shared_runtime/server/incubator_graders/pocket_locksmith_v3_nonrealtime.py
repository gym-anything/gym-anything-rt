"""Independent fixed-step replay. No browser completion flags establish a fit."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path

MECHANIC_ID = "pocket_locksmith_v3_nonrealtime"
ACTION_STEP_MS = 100


def episode_failure(task_id):
    """Use the server archive, never a policy or counter supplied by the UI."""
    directory = os.environ.get("GYM_ANYTHING_RT_STATE_DIR", "/tmp/gym_anything_rt")
    try:
        with (Path(directory) / "attempts.jsonl").open(encoding="utf-8") as journal:
            # The server archive belongs to its bound episode. Identity fields
            # inside a rejected payload are client input, not archive scope.
            current_path = Path(directory) / "current_task.json"
            if current_path.exists():
                current = json.loads(current_path.read_text(encoding="utf-8"))
                bound = current.get("task") if isinstance(current, dict) else None
                metadata = bound.get("metadata") if isinstance(bound, dict) else None
                if (not isinstance(bound, dict) or not bound.get("id")
                        or not isinstance(metadata, dict) or not metadata.get("mechanic_id")):
                    raise ValueError("invalid bound task record")
                if bound["id"] != task_id or metadata["mechanic_id"] != MECHANIC_ID:
                    return ""
            for line in journal:
                if not line.strip():
                    continue
                attempt = json.loads(line)
                if not isinstance(attempt, dict):
                    raise ValueError("invalid attempt record")
                decision = attempt.get("server_grade")
                if not isinstance(decision, dict) or decision.get("graded") is not True:
                    raise ValueError("invalid failed-submission grade")
                if decision.get("passed") is False:
                    return "A failed submission already ended this episode."
                if decision.get("passed") is not True:
                    raise ValueError("missing failed-submission verdict")
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError, ValueError, TypeError):
        return "Episode failure history is unavailable."
    return ""


def rotate(point, origin, axis, angle):
    v = [point[i]-origin[i] for i in range(3)]
    cross = [axis[1]*v[2]-axis[2]*v[1], axis[2]*v[0]-axis[0]*v[2], axis[0]*v[1]-axis[1]*v[0]]
    dot = sum(axis[i]*v[i] for i in range(3))
    c, s = math.cos(angle), math.sin(angle)
    return [origin[i]+v[i]*c+cross[i]*s+axis[i]*dot*(1-c) for i in range(3)]


def points(base, angles):
    p = [list(v) for v in base]
    for j, angle in enumerate(angles):
        origin = p[j]
        axis = [p[j+1][i]-origin[i] for i in range(3)]
        length = math.sqrt(sum(v*v for v in axis))
        axis = [v/length for v in axis]
        for k in range(j+2, len(p)):
            p[k] = rotate(p[k], origin, axis, math.radians(angle))
    return p


def target_angles(world, ms):
    result = []
    for path in world["paths"]:
        times = path["times_ms"]
        n = next((i for i in range(len(times)-1) if ms < times[i+1]), len(times)-2)
        f = max(0, min(1, (ms-times[n])/(times[n+1]-times[n])))
        a, b = path["knots"][n:n+2]
        result.append(a+(b-a)*f*f*(3-2*f))
    return result


class Physics:
    def __init__(self, world):
        self.world, self.p = world, world["parameters"]
        self.ms = 0
        self.angles = list(world["initial_angles"])
        self.command = self.angles.copy()
        self.velocity = [0.] * len(self.angles)
        self.bound_ms = 0
        self.outage_ms = 0
        self.worst_outage_ms = 0
        self.site_ms = [0] * len(self.angles)
        self.failed = ""
        self.done = False
        self.errors = [0.] * len(self.angles)

    def advance(self, end_ms):
        dt = self.world["tick_ms"]/1000
        while self.ms + self.world["tick_ms"] <= end_ms and not self.done:
            self.ms += self.world["tick_ms"]
            for j in range(len(self.angles)):
                a = (self.command[j]-self.angles[j])*self.p["servo_gain"]-self.velocity[j]*self.p["servo_damping"]
                a = max(-self.p["max_acceleration"], min(self.p["max_acceleration"], a))
                self.velocity[j] = max(-self.p["max_speed"], min(self.p["max_speed"], self.velocity[j]+a*dt))
                self.angles[j] += self.velocity[j]*dt
            key = points(self.world["base_points"], self.angles)[2:]
            pocket = points(self.world["base_points"], target_angles(self.world, self.ms))[2:]
            self.errors = [math.dist(a,b) for a,b in zip(key,pocket)]
            seated = [e <= self.p["clearance"]+1e-9 for e in self.errors]
            for j, hit in enumerate(seated):
                self.site_ms[j] += self.world["tick_ms"] * int(hit)
            if all(seated):
                self.bound_ms += self.world["tick_ms"]
                self.outage_ms = 0
            else:
                self.outage_ms += self.world["tick_ms"]
                self.worst_outage_ms = max(self.worst_outage_ms, self.outage_ms)
            if self.outage_ms > self.p["max_outage_ms"]:
                self.failed = "The key dissociated after prolonged contact loss."
                self.done = True
            elif self.bound_ms >= self.p["required_fraction"] * self.p["run_ms"]:
                self.done = True
            elif self.ms >= self.p["run_ms"]:
                self.failed = "Insufficient simultaneous binding contact."
                self.done = True

    def advance_action(self):
        """Advance one fixed virtual slice after a deliberate torsion commit."""
        self.advance(min(self.p["run_ms"], self.ms + ACTION_STEP_MS))


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("nonfinite number")
    return float(value)


def _point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("invalid pointer point")
    return [_number(x) for x in value]


def command_point(angle):
    radians = math.radians(angle-90)
    return [110+40*math.cos(radians), 67+40*math.sin(radians)]


def command_from_point(point, mode):
    if mode == "simplified":
        if not 20 <= point[0] <= 200 or not 49 <= point[1] <= 85:
            raise ValueError("pointer missed command rail")
        return (point[0]-110)*85/90
    angle = math.degrees(math.atan2(point[1]-67, point[0]-110))+90
    if angle > 180:
        angle -= 360
    return max(-85, min(85, angle))


def grade(payload, truth, public):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if not truth.get(key) or payload.get(key) != truth[key] or public.get(key) != truth[key]:
                return fail("stale or mismatched " + key)
        if truth["mechanic_id"] != MECHANIC_ID or public.get("world") != truth["world"]:
            return fail("wrong pocket contract")
        for key in ("single_attempt", "episode_failed", "episode_failure_reason"):
            if public.get(key) != truth.get(key):
                return fail("wrong episode contract: " + key)
        if truth.get("single_attempt") is not True:
            return fail("wrong first-failure policy")
        if truth.get("episode_failed"):
            return fail(truth.get("episode_failure_reason") or "A failed submission already ended this episode.")
        failure = episode_failure(truth["task_id"])
        if failure:
            return fail(failure)
        condition = truth.get("control_condition")
        if public.get("control_condition") != condition:
            return fail("wrong control condition")
        mode = (condition or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction surface")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 15000:
            return fail("missing or excessive action trace")
        sim = Physics(truth["world"])
        linkages = truth["world"]["drive_linkages"]
        if (not isinstance(linkages, list) or len(linkages) != len(sim.angles)
                or sorted(link["joint"] for link in linkages) != list(range(len(sim.angles)))
                or any(type(link["joint"]) is not int or type(link["direction"]) is not int
                       or link["direction"] not in (-1, 1) for link in linkages)):
            return fail("invalid drive linkages")
        held = None
        armed = False
        previous = 0
        finished = False
        for seq, e in enumerate(events, 1):
            if not isinstance(e, dict) or e.get("sequence") != seq:
                return fail("invalid event order")
            t = _number(e.get("t_ms"))
            if t != int(t) or not previous <= t <= sim.p["run_ms"] or t % sim.world["tick_ms"]:
                return fail("invalid event time")
            previous = t
            if armed:
                if t != sim.ms:
                    return fail("task time changes only after a committed torsion action")
            elif t:
                return fail("task time before arm")
            if finished:
                return fail("input after terminal result")
            kind = e.get("kind")
            if kind == "arm":
                if armed or held is not None or e.get("input_source") != "start_button":
                    return fail("duplicate or invalid trial start")
                armed = True
            elif kind in ("dial_start", "dial_move", "dial_end", "rail_set"):
                if sim.done:
                    return fail("control after dissociation or completion")
                j = e.get("joint")
                if type(j) is not int or not 0 <= j < len(sim.angles):
                    return fail("unknown rotatable bond")
                bond, direction = linkages[j]["joint"], linkages[j]["direction"]
                point = _point(e.get("point"))
                if e.get("input_source") != {"full":"torsion_ring_drag", "simplified":"torsion_rail_click"}[mode]:
                    return fail("wrong bond input surface")
                if kind == "rail_set":
                    if mode != "simplified" or held is not None:
                        return fail("rail control requires simplified interaction")
                    sim.command[bond] = direction * command_from_point(point, mode)
                elif mode != "full":
                    return fail("ring control requires full interaction")
                elif kind == "dial_start":
                    if held is not None or math.dist(point, command_point(direction * sim.command[bond])) > 14:
                        return fail("drag did not start on command bead")
                    held = j
                elif held != j:
                    return fail("torsion ring is not held")
                elif kind == "dial_move":
                    sim.command[bond] = direction * command_from_point(point, mode)
                else:
                    held = None
                if not armed:
                    sim.angles = sim.command.copy()
                elif kind == "rail_set" or kind == "dial_end":
                    sim.advance_action()
            elif kind == "orbit":
                if e.get("input_source") != "camera_drag":
                    return fail("wrong camera input")
                _point(e.get("start")); _point(e.get("end"))
            elif kind == "finish":
                if not armed or not sim.done or e.get("input_source") != "physical_trial":
                    return fail("premature binding claim")
                finished = True
            elif kind == "abort":
                return fail("Trial abandoned or submitted before completion.")
            else:
                return fail("unknown pocket action")
        if not finished or not sim.done or sim.failed or payload.get("completed") is not True:
            return fail(sim.failed or "binding trial incomplete")
        if payload.get("final_t_ms") != sim.ms or payload.get("bound_ms") != sim.bound_ms:
            return fail("reported contact time disagrees with physical replay")
        if payload.get("site_ms") != sim.site_ms or payload.get("worst_outage_ms") != sim.worst_outage_ms:
            return fail("reported binding contacts disagree with physical replay")
        for name, actual in (("angles",sim.angles), ("velocity",sim.velocity)):
            claimed = payload.get(name)
            if not isinstance(claimed, list) or len(claimed) != len(actual) or any(abs(_number(a)-b) > .001 for a,b in zip(claimed,actual)):
                return fail("reported key state differs from replay")
        return dict(graded=True, passed=True, score=100,
                    feedback="Connected key maintained all moving contacts through the binding trial.",
                    metrics=dict(bound_ms=sim.bound_ms, site_ms=sim.site_ms, worst_outage_ms=sim.worst_outage_ms,
                                 simultaneous_fraction=sim.bound_ms/sim.p["run_ms"], ticks=sim.ms//sim.world["tick_ms"]))
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as error:
        return fail("invalid pocket transcript: " + str(error))
