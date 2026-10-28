"""Standalone independent replay; also shipped unchanged to the Pyodide grader."""
from __future__ import annotations

import math

MECHANIC_ID = "branch_repair_v3"
REVISION = "living-fibre-7"
CANCEL_RADIUS = 6


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0, ms)/span
    n = math.floor(u)
    f = u-n
    return noise(seed, n)+(noise(seed, n+1)-noise(seed, n))*f*f*(3-2*f)


def motion_clock(ms, recoils=()):
    """Signed tissue time. Each successful join reverses horizontal drift."""
    clock, previous, heading = 0, 0, 1
    for at in recoils:
        if at > ms:
            break
        clock += heading * (at-previous)
        previous, heading = at, -heading
    return clock + heading * (ms-previous)


def reflected(seed, ms, amplitude, span):
    phase = ((int(seed)*2654435761) & 0xFFFFFFFF) % int(amplitude) * 4
    phase = (phase + 2*amplitude*ms/span) % (4*amplitude)
    return (phase-amplitude, 1) if phase < 2*amplitude else (3*amplitude-phase, -1)


def position(contract, station, port, ms, recoils=()):
    p = contract["parameters"]
    if contract["revision"] == REVISION:
        s = station["motion_seed"]
        x = reflected(s, motion_clock(ms, recoils), p["drift_px"], p["span_ms"])[0]
        y = reflected(s+7919, ms, 14, p["span_ms"])[0]
        flex = reflected(s+port["glyph"]*1327, ms, 24, p["span_ms"]+317)[0] if port["glyph"] else 0
        return [port["p"][0]+x+flex, port["p"][1]+y+flex/16,
                port["p"][2]+18*y/14+flex/16]
    # The tissue translates in 3D. Outlet-local flex is bounded to preserve
    # readable, non-overlapping targets in the operated XY pane.
    s = station["motion_seed"]
    common = [p["drift_px"]*motion(s, ms, p["span_ms"]),
              14*motion(s+7919, ms, p["span_ms"]),
              18*motion(s+15838, ms, p["span_ms"])]
    local = port["glyph"]
    return [port["p"][i]+common[i]+(0 if not local else (p["outlet_flex_px"] if i == 0 else 1.5)*
            motion(s+local*1327+i*29, ms, p["span_ms"]+317)) for i in range(3)]


def segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    v = dx*dx+dy*dy
    f = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/v)) if v else 0
    return math.hypot(p[0]-a[0]-f*dx, p[1]-a[1]-f*dy), f


def intersects(a, b, c, d):
    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    return (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0]))
            and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))
            and cross(a, b, c)*cross(a, b, d) <= 0 and cross(c, d, a)*cross(c, d, b) <= 0)


def segment_separation(a, b, c, d):
    if intersects(a, b, c, d):
        return 0.0
    return min(segment_distance(a, c, d)[0], segment_distance(b, c, d)[0],
               segment_distance(c, a, b)[0], segment_distance(d, a, b)[0])


class Simulation:
    def __init__(self, contract):
        self.c = contract
        self.ms = 0
        self.started = False
        self.failed = ""
        self.done = False
        self.x = [f["start_x"] for f in contract["fronts"]]
        self.x_units = [f["start_x"]*100000 for f in contract["fronts"]]
        self.open = set()
        self.cut = set()
        self.join = {}
        self.crossed = set()
        self.tool = "stitch"
        self.hold = None
        self.selected = None
        self.recoils = []
        self.inspected = set()

    def position(self, station, port, ms=None):
        return position(self.c, station, port, self.ms if ms is None else ms, self.recoils)

    def inspect_hit(self, point):
        """The section lens can inspect closed scars as well as open ports."""
        hits = [(math.dist(point, self.position(st, port)[:2]), st["lane"], st["column"], st["id"])
                for st in self.c["stations"] for port in [st["source"], *st["candidates"]]]
        hit = min(hits)
        return hit[3] if hit[0] <= self.c["parameters"]["port_radius"] else None

    def advance(self, target):
        if not self.started:
            return
        p = self.c["parameters"]
        while self.ms < target and not self.failed and not self.done:
            self.ms += 10
            for i, f in enumerate(self.c["fronts"]):
                if self.c["revision"] == REVISION:
                    sealed = sum(s["lane"] == i and s["id"] in self.cut and s["id"] in self.join for s in self.c["stations"])
                    # Integer material microunits keep displayed progress a
                    # lossless task state, including arbitrarily late cases.
                    self.x_units[i] += p["signal_speed"]*(78+22*(f["speed_seed"] % 3))*(10+sealed)
                    self.x[i] = self.x_units[i]/100000
                else:
                    self.x[i] += p["signal_speed"]*(1+.22*motion(f["speed_seed"], self.ms, 3700))*.01
            for st in self.c["stations"]:
                key = st["id"]
                if self.x[st["lane"]]+p["lead_px"] >= st["material_x"]:
                    self.open.add(key)
                if self.x[st["lane"]] >= st["material_x"] and key not in self.crossed:
                    if key not in self.cut or key not in self.join:
                        self.failed = "A signal escaped at an unrepaired lesion."
                        return
                    self.crossed.add(key)
            self.done = all(x >= self.c["finish_x"] for x in self.x)
            if self.done:
                self.hold = None
                self.selected = None
            if self.ms >= self.c["max_ms"] and not self.done:
                self.failed = "Signal delivery did not finish."

    def port_hit(self, point):
        hits = []
        for st in self.c["stations"]:
            if st["id"] not in self.open or st["id"] in self.join:
                continue
            for port in [st["source"], *st["candidates"]]:
                distance = math.dist(point, self.position(st, port)[:2])
                if distance <= self.c["parameters"]["port_radius"]:
                    visible = (st["lane"], st["column"], port["glyph"]) if self.c["revision"] == REVISION else ()
                    hits.append((distance, visible, st["id"], port["id"]))
        return min(hits)[2:] if hits else None

    def bridge(self, st):
        dest = next(p for p in st["candidates"] if p["id"] == st["bridge_to"])
        return self.position(st, st["source"])[:2], self.position(st, dest)[:2]

    def cut_hit(self, point, end=None):
        hits = []
        for st in self.c["stations"]:
            if st["id"] not in self.open or st["id"] in self.cut:
                continue
            a, b = self.bridge(st)
            if end is None:
                distance, _ = segment_distance(point, a, b)
                if distance <= 6:
                    hits.append((distance, (st["lane"], st["column"]) if self.c["revision"] == REVISION else (), st["id"]))
            elif math.dist(point, end) >= 12:
                distance = segment_separation(point, end, a, b)
                # The visible bridge is a round-capped 12-unit stroke. Both
                # surfaces cut the same capsule; full uses a knife stroke.
                if distance <= 6:
                    hits.append((distance, (st["lane"], st["column"]) if self.c["revision"] == REVISION else (), st["id"]))
        return min(hits)[2] if hits else None

    def stitch(self, first, second):
        if not first or not second:
            self.failed = "A released stitch missed its moving continuation."
            return
        if first == second:
            self.failed = "A stitch must connect two distinct ports."
            return
        st = next(s for s in self.c["stations"] if s["id"] == first[0])
        expected = next(p["id"] for p in st["candidates"] if p["p"][2] == st["source"]["p"][2])
        if first[0] != second[0] or {first[1], second[1]} != {st["source"]["id"], expected}:
            self.failed = "A stitch fused neighbouring fibres."
            return
        self.join[st["id"]] = expected
        if self.c["revision"] == REVISION:
            self.recoils.append(self.ms)

    def input(self, kind, point=None, mode="full", tool=None):
        if self.failed or self.done:
            return
        if kind == "inspect" and self.c.get("inspection_model"):
            hit = self.inspect_hit(point)
            if hit:
                self.inspected.add(hit)
            return
        if kind == "begin":
            if self.started:
                raise ValueError("episode cannot restart")
            self.started = True
            self.open.update(s["id"] for s in self.c["stations"]
                             if self.x[s["lane"]]+self.c["parameters"]["lead_px"] >= s["material_x"])
            return
        if kind == "tool":
            if tool not in ("stitch", "cut"):
                raise ValueError("unknown tool")
            self.tool = tool
            self.selected = None
            return
        if not self.started:
            return
        if kind == "down" and mode == "full":
            self.hold = (self.tool, point, self.port_hit(point) if self.tool == "stitch" else None)
        elif kind == "up" and mode == "full":
            if self.hold:
                active, start, first = self.hold
                self.hold = None
                if active == "stitch":
                    if math.dist(start, point) > CANCEL_RADIUS:
                        self.stitch(first, self.port_hit(point))
                else:
                    cut = self.cut_hit(start, point)
                    if cut:
                        self.cut.add(cut)
        elif kind == "click" and mode == "simplified":
            if self.tool == "cut":
                cut = self.cut_hit(point)
                if cut:
                    self.cut.add(cut)
            else:
                hit = self.port_hit(point)
                if self.selected is not None:
                    preview = self.selected
                    self.selected = None
                    if math.dist(preview["point"], point) > CANCEL_RADIUS:
                        self.stitch(preview["port"], hit)
                else:
                    self.selected = dict(point=point, port=hit)
        elif kind == "cancel":
            self.hold = None
            self.selected = None
        else:
            raise ValueError("wrong input surface")

    def summary(self):
        result = dict(t_ms=self.ms, signal_x=[round(x, 4) for x in self.x],
                    opened=sorted(self.open), cut=sorted(self.cut), joins=dict(sorted(self.join.items())),
                    crossed=sorted(self.crossed), failed=self.failed, delivered=self.done)
        if self.c["revision"] == REVISION:
            result.update(motion_clock_ms=motion_clock(self.ms, self.recoils), recoil_t_ms=list(self.recoils), signal_units=list(self.x_units))
        if self.c.get("inspection_model"):
            result["inspected"] = sorted(self.inspected)
        return result


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(v, dict) for v in (payload, ground_truth, public_state)):
            return fail("malformed contract")
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or mismatched " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] not in ("living-fibre-6", REVISION):
            return fail("unsupported mechanic revision")
        for key in ("fronts", "stations", "parameters", "interaction", "control_condition", "stage", "finish_x", "tick_ms", "max_ms", "motion_model", "inspection_model"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public/private contract differs: " + key)
        mode = ground_truth["interaction"]
        if payload.get("interaction") != mode or mode not in ("full", "simplified"):
            return fail("wrong interaction mode")
        events = payload["events"]
        if not isinstance(events, list) or not 2 <= len(events) <= 4000:
            return fail("missing or oversized trace")
        sim, previous, submitted = Simulation(ground_truth), -1, False
        for sequence, event in enumerate(events, 1):
            t = event["t_ms"]
            if type(t) is not int or t % 10 or not previous <= t <= ground_truth["max_ms"] or event.get("sequence") != sequence or submitted:
                return fail("invalid sequence or task time")
            kind = event["kind"]
            if kind not in ("begin", "tool", "submit", "down", "up", "click", "cancel", "inspect") or (sim.done and kind != "submit"):
                return fail("invalid event or input after delivery")
            source = "button" if kind in ("begin", "tool", "submit") else mode
            if event.get("input_source") != source:
                return fail("wrong input source")
            if kind == "inspect" and not ground_truth.get("inspection_model"):
                return fail("section lens unavailable in this revision")
            if not sim.started and ((kind not in ("begin", "inspect")) or t != 0):
                return fail("start the active run before editing")
            if kind == "begin" and t != 0:
                return fail("signal flow must begin at task time zero")
            sim.advance(t)
            previous = t
            if sim.failed:
                return fail(sim.failed)
            if kind == "submit":
                submitted = True
                if sequence != len(events) or sim.hold:
                    return fail("submission must follow released input")
            else:
                point = event.get("point")
                if kind in ("down", "up", "click", "inspect"):
                    if not isinstance(point, list) or len(point) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in point):
                        return fail("invalid pointer point")
                    # Pointer capture delivers a full drag's release even when
                    # it leaves the canvas. Replay the actual release point:
                    # a knife stroke can still cross a visible bridge, while
                    # an armed stitch outside every port remains a fatal miss.
                    # Acquisition and simplified clicks originate on canvas.
                    if (kind != "up" or mode != "full") and not (
                        0 <= point[0] <= 960 and 0 <= point[1] <= 490
                    ):
                        return fail("pointer leaves the specimen")
                sim.input(kind, point, mode, event.get("tool"))
                if sim.failed:
                    return fail(sim.failed)
        if not submitted or not sim.done or not sim.started:
            return fail("signals have not all reached their terminals")
        if payload.get("summary") != sim.summary() or payload.get("completed") is not True:
            return fail("reported outcome differs from replay")
        return dict(graded=True, passed=True, score=100, feedback=f"All {len(sim.x)} signals delivered through {len(sim.join)} repaired lesions.")
    except (KeyError, TypeError, ValueError, OverflowError, StopIteration, IndexError) as exc:
        return fail("invalid branch repair trace: " + str(exc))


def cheat(public_state, ground_truth):
    del public_state
    return dict(answers=ground_truth.get("answers", {}))
