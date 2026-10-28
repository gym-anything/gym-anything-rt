"""Independent fixed-step replay of recorded hands, motors and parcel custody.

Self-contained for the pinned Pyodide exporter. Never accepts a completed flag
instead of a geometric catch, seal and release for each physical parcel.
"""
from __future__ import annotations

import math

MECHANIC_ID = "clockwork_doppelganger_customs_v3_nonrealtime"
REVISION = "moving-relay-3-inspection-3"


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def motor(world, index, ms):
    span = world["spec"]["motor_span_ms"]
    u = max(0, ms)/span
    k = min(int(u), len(world["motors"][index])-2)
    f = clamp(u-k, 0, 1)
    a, b = world["motors"][index][k:k+2]
    return a+(b-a)*f*f*(3-2*f)


def path_y(path, fraction):
    for a, b in zip(path, path[1:]):
        if a[0] <= fraction <= b[0]:
            return a[1]+(b[1]-a[1])*(fraction-a[0])/(b[0]-a[0])
    return path[-1][1] if fraction > 1 else path[0][1]


def normalize_path(points, world):
    e = world["editor"]
    if len(points) < 2 or len(points) > 800:
        raise ValueError("record a sweep between both visible endpoints")
    if math.dist(points[0], e["start"]) > e["radius"]+.01 or math.dist(points[-1], e["end"]) > e["radius"]+.01:
        raise ValueError("recording did not connect the two cam sockets")
    result = []
    for x, y in points:
        if not 90-e["radius"] <= x <= 770+e["radius"] or abs(y-230) > e["max_deviation"]+.01:
            raise ValueError("recorded sweep leaves the visible slot")
        f = clamp((x-90)/680, 0, 1)
        if result and f <= result[-1][0]:
            if f < result[-1][0]-.04:
                raise ValueError("the cam sweep went backwards")
            continue
        result.append([f, y-230])
    if len(result) < 2:
        raise ValueError("empty cam sweep")
    result[0][0], result[-1][0] = 0.0, 1.0
    return result


def schedule(world):
    s = world["spec"]
    events = []
    for parcel in range(s["parcel_count"]):
        for i in range(s["workers"]):
            t = s["first_pickup_ms"] + parcel*s["period_ms"] + i*(s["travel_ms"]+s["gap_ms"])
            events.extend([(t, i, parcel, "catch", 0),
                           (t+s["travel_ms"]//2, i, parcel, "seal", .5),
                           (t+s["travel_ms"], i, parcel, "pass", 1)])
    return sorted(events)


def passport_position(world, parcel, ms, delivery_times):
    """The visible output shuttle; identical geometry for pointer replay."""
    s = world["spec"]
    elapsed = ms-delivery_times[parcel]
    x = world["stations_x"][-1] + world["collection"]["travel_x"] * elapsed/s["collection_ms"]
    return x, motor(world, s["workers"], ms)


class Relay:
    def __init__(self, world, path):
        self.world, self.s, self.path = world, world["spec"], path
        n = self.s["workers"]
        self.ms = 0
        self.y = [self.s["initial_y"]]*n
        self.v = [0.0]*n
        self.targets = self.y[:]
        self.custody = [0]*self.s["parcel_count"]  # tray i or hand encoded -(i+1)
        self.seals = [0]*self.s["parcel_count"]
        self.delivered, self.failed, self.contact_index = 0, "", 0
        self.collected = [False]*self.s["parcel_count"]
        self.delivery_times = [None]*self.s["parcel_count"]
        self.outgoing = None
        self.contacts = schedule(world)
        self.contact_log = []

    def advance(self, end):
        while self.ms + self.s["tick_ms"] <= end and not self.failed and not all(self.collected):
            self.ms += self.s["tick_ms"]
            dt = self.s["tick_ms"]/1000
            for i in range(self.s["workers"]):
                a = clamp(self.s["kp"]*(self.targets[i]-self.y[i])-self.s["kd"]*self.v[i],
                          -self.s["acceleration"], self.s["acceleration"])
                self.v[i] = clamp(self.v[i]+a*dt, -self.s["speed"], self.s["speed"])
                self.y[i] = clamp(self.y[i]+self.v[i]*dt, self.s["min_y"], self.s["max_y"])
                if self.y[i] in (self.s["min_y"], self.s["max_y"]):
                    self.v[i] = 0.0
            while self.contact_index < len(self.contacts) and self.contacts[self.contact_index][0] <= self.ms:
                t, i, parcel, kind, fraction = self.contacts[self.contact_index]
                self.contact_index += 1
                index = i if kind == "catch" else self.s["workers"]+1+i if kind == "seal" else i+1
                desired = motor(self.world, index, t)
                actual = self.y[i]+path_y(self.path, fraction)
                error = abs(actual-desired)
                if error > self.s["tolerance"]+1e-7:
                    self.failed = f"Parcel {parcel+1}: worker {i+1} missed {kind}."
                    return
                if kind == "catch":
                    if self.custody[parcel] != i:
                        self.failed = "Parcel was not on the incoming tray."
                        return
                    self.custody[parcel] = -(i+1)
                elif kind == "seal":
                    if self.custody[parcel] != -(i+1):
                        self.failed = "Seal has no physical parcel."
                        return
                    self.seals[parcel] |= 1 << i
                else:
                    if self.custody[parcel] != -(i+1):
                        self.failed = "Worker released an empty hand."
                        return
                    self.custody[parcel] = i+1
                    if i == self.s["workers"]-1:
                        if self.seals[parcel] != (1 << self.s["workers"])-1:
                            self.failed = "Customs seals are incomplete."
                            return
                        if self.outgoing is not None:
                            self.failed = "The output counter is occupied by an uncollected passport."
                            return
                        self.delivery_times[parcel] = t
                        self.outgoing = parcel
                        self.delivered += 1
                self.contact_log.append(dict(t_ms=t, worker=i, parcel=parcel, kind=kind,
                                             hand_y=round(actual, 4), tray_y=round(desired, 4)))
            if self.outgoing is not None and self.ms-self.delivery_times[self.outgoing] >= self.s["collection_ms"]:
                self.failed = f"Passport {self.outgoing+1} left the customs counter."

    def collect(self, point):
        if self.outgoing is None or self.failed or all(self.collected):
            raise ValueError("no moving passport on the output counter")
        parcel = self.outgoing
        x, y = passport_position(self.world, parcel, self.ms, self.delivery_times)
        box = self.world["collection"]
        if abs(point[0]-x) > box["width"]/2 or abs(point[1]-y) > box["height"]/2:
            self.failed = "Missed the moving passport."
            return
        self.collected[parcel] = True
        self.outgoing = None

    def snapshot(self):
        return dict(ms=self.ms, y=[round(x, 4) for x in self.y], v=[round(x, 4) for x in self.v],
                    targets=[round(x, 4) for x in self.targets], custody=self.custody[:],
                    seals=self.seals[:], delivered=self.delivered, failed=self.failed,
                    collected=self.collected[:], delivery_times=self.delivery_times[:], outgoing=self.outgoing,
                    contacts=self.contact_index)


def _number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError("nonfinite numeric input")
    return float(x)


def _point(x, width, height):
    if not isinstance(x, list) or len(x) != 2:
        raise ValueError("malformed pointer position")
    a, b = map(_number, x)
    if not 0 <= a <= width or not 0 <= b <= height:
        raise ValueError("pointer outside input canvas")
    return [a, b]


def _fail(reason):
    return dict(graded=True, passed=False, score=0, feedback=reason)


def grade(payload, ground_truth, public_state):
    try:
        for key in ("mechanic_id", "task_id", "challenge_id", "revision", "world", "control_condition"):
            if public_state.get(key) != ground_truth.get(key):
                raise ValueError(f"public {key} differs from replay contract")
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key]:
                raise ValueError(f"wrong {key}")
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION:
            raise ValueError("wrong relay implementation")
        world = ground_truth["world"]
        mode = ground_truth["control_condition"]["interaction"]
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            raise ValueError("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list) or not 3 <= len(events) <= 12000:
            raise ValueError("missing or excessive input trace")
        path, recording, sim, hold, deployed_at, verified = None, None, None, None, None, False
        action_step = _number(world["spec"].get("action_step_ms", 60))
        if action_step <= 0:
            raise ValueError("invalid action step")
        next_action_at = None
        previous = -1
        inspected = set()
        for seq, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("seq") != seq or verified:
                raise ValueError("invalid event sequence or event after certification")
            t = _number(event.get("t_ms"))
            if not previous <= t <= 180000:
                raise ValueError("nonmonotone or excessive task time")
            previous = t
            if sim is not None:
                if next_action_at is None or abs(t-next_action_at) > 1e-7:
                    raise ValueError("waiting does not advance the relay; use the next deliberate action")
                sim.advance(t-deployed_at)
                if sim.failed and event.get("type") != "verify":
                    raise ValueError(sim.failed)
            kind = event.get("type")
            if kind == "inspect":
                # Lifting a physical inspection cover is an information probe,
                # never a commitment, quota or prerequisite for deployment.
                i = event.get("drive")
                count = 2*world["spec"]["workers"]+1
                if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < count:
                    raise ValueError("unknown drive housing")
                if recording is not None or hold is not None or i in inspected or event.get("input_source") != "housing_click":
                    raise ValueError("inspection cover unavailable")
                x, y = _point(event.get("point"), 860, 460)
                width = 824/count
                n = world["spec"]["workers"]
                column = 2*i if i <= n else 2*(i-n-1)+1
                if not 18+column*width <= x <= 18+(column+1)*width-6 or not 30 <= y <= 62:
                    raise ValueError("lift the labeled drive housing")
                inspected.add(i)
            elif kind in ("record_start", "record_move", "record_end"):
                if sim is not None or event.get("input_source") != "record_drag":
                    raise ValueError("recording unavailable during relay")
                point = _point(event.get("point"), 860, 460)
                if kind == "record_start":
                    if recording is not None:
                        raise ValueError("overlapping recording holds")
                    recording = [point]
                elif recording is None:
                    raise ValueError("recording pointer is not held")
                else:
                    recording.append(point)
                    if kind == "record_end":
                        try:
                            candidate = normalize_path(recording, world)
                        except ValueError:
                            candidate = None
                        if event.get("accepted") != (candidate is not None):
                            raise ValueError("incorrect recording verdict")
                        if candidate is not None:
                            path = candidate
                        recording = None
            elif kind == "deploy":
                if path is None or recording is not None or sim is not None:
                    raise ValueError("deploy requires one finished sweep and a fresh relay")
                sim, deployed_at = Relay(world, path), t
                next_action_at = t
            elif kind in ("lever_start", "lever_move", "lever_end", "lever_target"):
                if sim is None or sim.failed or (sim.delivered == sim.s["parcel_count"] and kind != "lever_end"):
                    raise ValueError("lever unavailable")
                i = event.get("worker")
                if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < sim.s["workers"]:
                    raise ValueError("unknown worker lever")
                point = _point(event.get("point"), 240, 460)
                lever = world["lever"]
                if event.get("input_source") != ("lever_drag" if mode == "full" else "rail_click"):
                    raise ValueError("input surface does not match interaction mode")
                if kind == "lever_target":
                    if mode != "simplified" or hold is not None or abs(point[0]-lever["xs"][i]) > lever["grip_half_width"]:
                        raise ValueError("click the selected worker's rail")
                elif mode != "full":
                    raise ValueError("drag is full interaction only")
                elif kind == "lever_start":
                    if hold is not None or abs(point[0]-lever["xs"][i]) > lever["grip_half_width"] or abs(point[1]-sim.targets[i]) > lever["grip_half_height"]+.01:
                        raise ValueError("drag must start on the visible lever handle")
                    hold = i
                elif hold != i:
                    raise ValueError("lever is not held")
                if kind in ("lever_move", "lever_target"):
                    sim.targets[i] = clamp(point[1], sim.s["min_y"], sim.s["max_y"])
                if kind == "lever_end":
                    hold = None
                    next_action_at = t+action_step
                elif kind == "lever_target":
                    next_action_at = t+action_step
            elif kind == "collect":
                if sim is None or event.get("input_source") != "passport_click" or hold is not None:
                    raise ValueError("collect a passport with a released pointer")
                sim.collect(_point(event.get("point"), 860, 460))
                if not sim.failed:
                    next_action_at = t+action_step
            elif kind == "verify":
                if sim is None or next_action_at is None or abs(t-next_action_at) > 1e-7:
                    raise ValueError("certification is not at the current logical action boundary")
                verified = True
            else:
                raise ValueError(f"unavailable control {kind}")
        if not verified or sim is None or recording is not None:
            raise ValueError("relay not certified")
        expected = sim.snapshot()
        claim = payload.get("final_state")
        if not isinstance(claim, dict):
            raise ValueError("missing final replay state")
        for key in expected:
            if key in ("y", "v", "targets"):
                values = claim.get(key)
                if not isinstance(values, list) or len(values) != len(expected[key]) or any(abs(_number(a)-b) > .002 for a,b in zip(values, expected[key])):
                    raise ValueError(f"fabricated {key}")
            elif claim.get(key) != expected[key]:
                raise ValueError(f"fabricated {key}")
        passed = not sim.failed and all(sim.collected)
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=sim.failed or f"Physical relay: {sum(sim.collected)}/3 collected passports; {sim.contact_index} geometric contacts.")
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return _fail(str(exc))


def cheat(public_state, ground_truth):
    del public_state, ground_truth
    return {"answers": [], "note": "No precomputed controller; oracle planning is separate."}
