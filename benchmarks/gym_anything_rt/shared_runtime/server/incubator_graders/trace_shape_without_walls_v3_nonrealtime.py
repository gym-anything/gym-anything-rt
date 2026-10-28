"""Independent fixed-step physical replay; no client completion is trusted.

Standalone imports deliberately support the existing Pyodide export contract.
"""
from __future__ import annotations
import math

MECHANIC_ID = "trace_shape_without_walls_v3_nonrealtime"
REVISION = "deforming-channel-v2"
ACTION_STEP_MS = 240


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def smooth(value):
    return value * value * (3 - 2 * value)


def motion(seed, ms, span):
    u = max(0, ms) / span
    i = math.floor(u)
    return noise(seed, i) + (noise(seed, i + 1) - noise(seed, i)) * smooth(u-i)


def center(world, x, ms):
    nodes = world["nodes"]
    i = next((j for j in range(len(nodes)-1) if x <= nodes[j+1]["x"]), len(nodes)-2)
    a, b = nodes[i:i+2]
    f = smooth(max(0, min(1, (x-a["x"])/(b["x"]-a["x"]))))
    common = world["coherence"] * motion(world["wall_seed"], ms, world["span_ms"])
    local = 1-world["coherence"]
    ay = a["y"] + world["amplitude"] * (common + local*motion(a["seed"], ms, world["span_ms"]))
    by = b["y"] + world["amplitude"] * (common + local*motion(b["seed"], ms, world["span_ms"]))
    return ay + (by-ay)*f


def wind(world, ms):
    return world["wind"] * motion(world["wind_seed"], ms, 4300)


def clearance(world, x, y, ms):
    """Circle contained between the same polylines drawn by the renderer.

    Distance to each wall segment in the circle's x-neighbourhood, rather than
    vertical distance alone, accounts for oblique channel walls.
    """
    best = math.inf
    for xx in range(max(0, math.floor((x-12)/4)*4), min(996, math.ceil((x+12)/4)*4)+1, 4):
        for side in (-1, 1):
            a = (xx, center(world, xx, ms) + side*world["radius"])
            b = (xx+4, center(world, xx+4, ms) + side*world["radius"])
            dx, dy = b[0]-a[0], b[1]-a[1]
            f = max(0, min(1, ((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
            best = min(best, math.hypot(x-a[0]-f*dx, y-a[1]-f*dy))
    inside = abs(y-center(world, x, ms)) <= world["radius"]
    return best if inside else -best


class Physics:
    def __init__(self, world):
        self.world = world
        self.ms = 0
        self.x = world["start_x"]
        self.y = center(world, self.x, 0)
        self.v = 0.0
        self.target = self.y
        self.active = self.done = False
        self.failed = ""

    def launch(self):
        if self.active or self.done or self.failed:
            raise ValueError("launch unavailable")
        self.active = True
        self.y = center(self.world, self.x, self.ms)
        self.target = self.y

    def advance(self, end):
        w = self.world
        while self.ms + 10 <= end and not self.failed and not self.done:
            self.ms += 10
            if not self.active:
                self.y = center(w, self.x, self.ms)
                self.target = self.y
                if self.ms >= w["max_ms"]:
                    self.failed = "TRACE TIME EXHAUSTED"
                continue
            acceleration = (self.target-self.y)*w["response"]**2 - 2*w["response"]*self.v + wind(w, self.ms)
            acceleration = max(-w["max_acceleration"], min(w["max_acceleration"], acceleration))
            self.v = max(-w["max_velocity"], min(w["max_velocity"], self.v + acceleration*.01))
            self.x = min(w["exit_x"], self.x + w["speed"]*.01)
            self.y += self.v*.01
            if clearance(w, self.x, self.y, self.ms) < w["probe_radius"] - 1e-7:
                self.failed = "WALL CONTACT"
            elif self.x >= w["exit_x"]:
                self.done = True
            elif self.ms >= w["max_ms"]:
                self.failed = "TRACE TIME EXHAUSTED"


def number(v):
    if type(v) not in (int, float) or not math.isfinite(v):
        raise ValueError("non-finite number")
    return float(v)


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(v, dict) for v in (payload, ground_truth, public_state)):
            return fail("invalid objects")
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or wrong " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION:
            return fail("wrong physics revision")
        for key in ("world", "control_condition"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public replay contract mismatch")
        mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        source = "pen_drag" if mode == "full" else "height_click"
        physics = Physics(ground_truth["world"])
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 6000:
            return fail("missing or excessive input trace")
        previous = 0
        held = launched = False
        for seq, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("sequence") != seq:
                return fail("invalid event sequence")
            t = number(event.get("t_ms"))
            if not previous <= t <= ground_truth["world"]["max_ms"]:
                return fail("invalid event time")
            # The counterpart has no autonomous clock.  Every event is
            # delivered at the current stable state; only a deliberate
            # steering control advances the fixed logical slice below.
            if t != physics.ms:
                return fail("event is not delivered at the current stable state")
            if physics.failed or physics.done:
                return fail("input after terminal trace")
            kind = event.get("kind")
            if kind == "scan":
                p = event.get("point")
                if (event.get("input_source") != "pointer_sonar" or not isinstance(p, list)
                        or len(p) != 2 or not 0 <= number(p[0]) <= 1000
                        or not 0 <= number(p[1]) <= 480):
                    return fail("invalid sonar scan")
                # Information-only inspection. It changes no physics, consumes
                # no resource and imposes no scan-count/coverage requirement.
            elif kind == "launch":
                if launched or event.get("input_source") != "launch_button":
                    return fail("invalid launch")
                physics.launch()
                launched = True
            elif kind in ("hold", "steer", "release"):
                if not launched or event.get("input_source") != source:
                    return fail("wrong steering input surface")
                p = event.get("point")
                if not isinstance(p, list) or len(p) != 2 or not 0 <= number(p[0]) <= 1000 or not 0 <= number(p[1]) <= 480:
                    return fail("steering point outside scope")
                if kind == "hold":
                    if mode != "full" or held:
                        return fail("invalid pen hold")
                    held = True
                elif kind == "release":
                    if mode != "full" or not held:
                        return fail("invalid pen release")
                    held = False
                elif mode == "full" and not held:
                    return fail("steering without dragging the pen")
                if kind != "release":
                    physics.target = p[1]
                physics.advance(min(ground_truth["world"]["max_ms"], t + ACTION_STEP_MS))
            else:
                return fail("unavailable control")
            previous = t
        end = number(payload.get("final_t_ms"))
        if not previous <= end <= ground_truth["world"]["max_ms"] or end != physics.ms:
            return fail("invalid final time")
        claimed = payload.get("final")
        if not isinstance(claimed, dict) or any(abs(number(claimed.get(k))-getattr(physics,k)) > .02 for k in ("x", "y", "v", "ms")):
            return fail("final state disagrees with physical replay")
        if claimed.get("failed") != physics.failed or claimed.get("done") != physics.done:
            return fail("terminal state disagrees with physical replay")
        passed = launched and physics.done and not physics.failed and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"Sonar trace: {physics.x-physics.world['start_x']:.1f}/860 px; {physics.failed or ('EXIT' if physics.done else 'INCOMPLETE')}")
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        return fail("invalid trace: " + str(exc))


def cheat(public_state, ground_truth):
    return {"world": ground_truth.get("world")}
