"""Independent primitive-input replay. No browser success flag is authoritative."""
from __future__ import annotations

import copy
import math

MECHANIC_ID = "bomb_manual_from_hell_v2"
TAU = 2*math.pi


def wrap(x):
    return (x+math.pi) % TAU-math.pi


def noise(seed, index):
    x = (int(seed) ^ ((index+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def drive(motor, elapsed, variation):
    u = elapsed/motor["span_ms"]
    n = math.floor(u)
    f = u-n
    return motor["speed"]*(1+variation*(noise(motor["seed"], n)+(noise(motor["seed"], n+1)-noise(motor["seed"], n))*f*f*(3-2*f)))


def knob(world, i, j):
    count = len(world["modules"][i]["guards"])
    cx, cy = world["modules"][i]["center"]
    return [cx if count == 1 else cx-86+172*j/(count-1), cy+119]


def point(value):
    if not isinstance(value, list) or len(value) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError("invalid finite pointer point")
    if not 0 <= value[0] <= 900 or not 0 <= value[1] <= 560:
        raise ValueError("pointer outside workbench")
    return value


def segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    f = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(p[0]-a[0]-f*dx, p[1]-a[1]-f*dy)


class Physics:
    def __init__(self, world):
        self.world = world
        self.ms = 0
        self.armed = False
        self.start_ms = None
        self.failed = ""
        self.cut = []
        self.charge = 1.0
        self.fuses = [m["fuse"]["phase"] for m in world["modules"]]
        self.guards = [[g["phase"] for g in m["guards"]] for m in world["modules"]]
        self.offsets = [[0 for _ in m["guards"]] for m in world["modules"]]

    @property
    def solved(self):
        return len(self.cut) == len(self.fuses)

    def advance(self, target):
        if type(target) is not int or target % 20 or not self.ms <= target <= 600000:
            raise ValueError("nonmonotonic or off-grid task time")
        p = self.world["parameters"]
        while self.ms < target and not self.failed and not self.solved:
            if self.armed:
                elapsed = self.ms-self.start_ms
                if elapsed >= self.world["max_active_ms"]:
                    self.failed = "FUSE ENGINE EXPIRED"
                    break
                self.charge = min(1.0, self.charge+20/self.world['cutter_recharge_ms'])
                for i, m in enumerate(self.world["modules"]):
                    if i in self.cut:
                        continue
                    self.fuses[i] = wrap(self.fuses[i]+.02*drive(m["fuse"], elapsed, p["rate_variation"])*(1+p["load_coupling"]*len(self.cut)))
                    for j, g in enumerate(m["guards"]):
                        self.guards[i][j] = wrap(self.guards[i][j]+.02*drive(g, elapsed, p["rate_variation"])*(1+.55*p["load_coupling"]*len(self.cut)))
            self.ms += 20
        if self.armed and not self.failed and not self.solved and self.ms-self.start_ms >= self.world['max_active_ms']:
            self.failed = "FUSE ENGINE EXPIRED"

    def fuse_point(self, i):
        cx, cy = self.world["modules"][i]["center"]
        r = self.world["orbit_radius"]
        return [cx+r*math.cos(self.fuses[i]), cy+r*math.sin(self.fuses[i])]

    def safe(self, i):
        # Entire 34px collar must fit in every visible radial aperture.
        margin = math.asin(self.world["fuse_radius"]/self.world["orbit_radius"])
        half = math.radians(self.world["parameters"]["aperture_half_deg"])
        return all(abs(wrap(self.fuses[i]-g-self.offsets[i][j]*math.pi/12))+margin <= half+1e-9
                   for j, g in enumerate(self.guards[i]))

    def snip(self, a, b):
        if not self.armed:
            raise ValueError("snip before engine activation")
        if self.charge < 1-1e-9:
            raise ValueError("snip while cutter is recharging")
        length = math.dist(a, b)
        if not 30 <= length <= 100:
            self.failed = "CUTTER STROKE MUST BE 30–100 PX"
            return
        hits = [i for i in range(len(self.fuses)) if i not in self.cut and segment_distance(self.fuse_point(i), a, b) <= self.world["fuse_radius"]]
        if len(hits) != 1:
            self.failed = "CUTTER MISSED THE LIVE COLLAR"
        elif not self.safe(hits[0]):
            self.failed = "CUT THROUGH AN ACETATE GUARD"
        else:
            self.cut.append(hits[0])
            self.charge = 0.0

    def snapshot(self):
        return dict(ms=self.ms, armed=self.armed, start_ms=self.start_ms, failed=self.failed,
                    cut=list(self.cut), charge=self.charge, fuses=list(self.fuses), guards=copy.deepcopy(self.guards), offsets=copy.deepcopy(self.offsets))


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(x, dict) for x in (payload, ground_truth, public_state)):
            return fail("malformed submission")
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or wrong "+key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("world", "control_condition"):
            if ground_truth.get(key) != public_state.get(key):
                return fail("public commitment mismatch: "+key)
        mode = ground_truth["control_condition"]["interaction"]
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 6000:
            return fail("missing or oversized primitive trace")
        s = Physics(ground_truth["world"])
        drag = cutter = None
        finished = False
        for seq, e in enumerate(events, 1):
            if not isinstance(e, dict) or e.get("sequence") != seq or finished or s.failed or s.solved:
                return fail("events after terminal state or invalid sequence")
            s.advance(e["t_ms"])
            if s.failed:
                return fail(s.failed)
            kind, source = e.get("kind"), e.get("input_source")
            if kind == "arm":
                if source != "arm_button" or s.armed or drag or cutter:
                    return fail("invalid engine activation")
                s.armed, s.start_ms = True, s.ms
            elif kind.startswith("knob_") or kind == "nudge":
                i, j = e["module"], e["layer"]
                if type(i) is not int or type(j) is not int or not 0 <= i < len(s.fuses) or not 0 <= j < len(s.guards[i]) or i in s.cut or cutter:
                    return fail("invalid manual leaf")
                p = point(e["point"])
                c = knob(s.world, i, j)
                if kind == "nudge":
                    direction = e["direction"]
                    if mode != "simplified" or source != "manual_buttons" or drag or type(direction) is not int or direction not in (-1, 1):
                        return fail("wrong nudge input surface")
                    if abs(p[0]-(c[0]+direction*28)) > 15 or abs(p[1]-c[1]) > 15:
                        return fail("nudge missed its visible button")
                    s.offsets[i][j] += direction
                else:
                    if mode != "full" or source != "manual_knob_drag" or not 12 <= math.dist(p, c) <= 50:
                        return fail("wrong knob input surface or geometry")
                    angle = math.atan2(p[1]-c[1], p[0]-c[0])
                    if kind == "knob_begin":
                        if math.dist(p, c) > 31:
                            return fail("knob hold missed its visible rim")
                        if drag:
                            return fail("nested knob drag")
                        drag = (i, j, angle, s.offsets[i][j])
                    elif kind in ("knob_move", "knob_end"):
                        if not drag or drag[:2] != (i, j):
                            return fail("knob move without matching hold")
                        s.offsets[i][j] = drag[3]+math.floor(wrap(angle-drag[2])/(math.pi/12)+.5)
                        if kind == "knob_end":
                            drag = None
                    else:
                        return fail("unknown knob input")
            elif kind in ("cut_begin", "cut_end"):
                if source != ("cutter_drag" if mode == "full" else "cutter_endpoint_clicks") or drag or not s.armed:
                    return fail("wrong cutter surface or activation")
                p = point(e["point"])
                if kind == "cut_begin":
                    if s.charge < 1-1e-9:
                        return fail("cutter unavailable while recharging")
                    if cutter:
                        return fail("nested cutter stroke")
                    cutter = p
                else:
                    if cutter is None:
                        return fail("cutter closed without an origin")
                    s.snip(cutter, p)
                    cutter = None
            elif kind == "cancel":
                if source != "pointer_cancel" or not (drag or cutter):
                    return fail("invalid cancel")
                drag = cutter = None
            elif kind == "seal":
                if source != "seal_button":
                    return fail("wrong seal surface")
                finished = True
                s.failed = "INCOMPLETE DEVICE SEALED"
            else:
                return fail("unknown primitive input")
        claimed = payload.get("physics")
        if not isinstance(claimed, dict):
            return fail("missing final physical state")
        # A terminal idle expiry need not have a final mouse event. Integrate
        # its declared final time independently before comparing every field.
        if not s.failed and not s.solved:
            s.advance(claimed['ms'])
        def equal(a, b):
            if isinstance(b, dict):
                return isinstance(a, dict) and set(a) == set(b) and all(equal(a[k], v) for k, v in b.items())
            if isinstance(b, list):
                return isinstance(a, list) and len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
            if type(b) is float:
                return type(a) in (int, float) and math.isfinite(a) and abs(a-b) <= .00001
            return type(a) is type(b) and a == b
        if not equal(claimed, s.snapshot()):
            return fail("final physical state disagrees with replay")
        passed = s.solved and not s.failed and drag is None and cutter is None and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=s.failed or f"independent live acetate replay: {len(s.cut)}/{len(s.fuses)} collars severed")
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError, IndexError) as exc:
        return fail("invalid acetate transcript: "+str(exc))


def cheat(public_state, ground_truth):
    return {"note": "No static defusal answer: moving collar positions and manual leaves require fresh control."}
