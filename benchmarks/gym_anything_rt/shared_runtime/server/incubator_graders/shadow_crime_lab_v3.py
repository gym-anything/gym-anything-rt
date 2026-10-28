"""Standalone Python geometry and fixed-step optical/camera replay (Pyodide safe)."""
from __future__ import annotations
import math

MECHANIC_ID = "shadow_crime_lab_v3"


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0, ms)/span
    i = math.floor(u)
    f = u-i
    return noise(seed, i)+(noise(seed, i+1)-noise(seed, i))*f*f*(3-2*f)


def integral(seed, ms, span):
    u = max(0, ms)/span
    i = math.floor(u)
    f = u-i
    whole = sum((noise(seed, j)+noise(seed, j+1))/2 for j in range(i))
    a, b = noise(seed, i), noise(seed, i+1)
    return span*(whole+a*f+(b-a)*(f**3-f**4/2))


def lamp_at(state, bench, ms):
    span = state["parameters"]["lamp_span_ms"]
    return [bench["lamp_x"]+120*motion(bench["lamp_seed"], ms, span),
            bench["lamp_y"]+8*motion(bench["lamp_seed"]+7919, ms, span)]


def object_at(state, obj, ms):
    a = obj["phase"]+state["parameters"]["angular_speed"]*(ms+.4*integral(obj["seed"], ms, 4700))/1000
    return [obj["x"]+35*math.cos(a), obj["y"]+24*math.sin(a)]


def cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def hull(points):
    points = sorted(points)
    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1]+upper[:-1]


def lamp_shift_at(history, ms):
    """The manual rail drive is neutral before its first actual input."""
    return next((shift for t, shift in reversed(history or []) if t <= ms), 0)


def polygons(state, bench, ms, lamp_shifts=None):
    result = []
    for index, obj in enumerate(bench["objects"]):
        position = object_at(state, obj, ms)
        # Autonomous light/specimen motion stays live. Only an intervention on
        # the lamp rail exposes the counterfeit's delayed causal response.
        t = ms-state["parameters"]["lag_ms"] if index == bench["forged_index"] else ms
        lamp = lamp_at(state, bench, ms)
        lamp[0] += lamp_shift_at(lamp_shifts, t)
        scale = bench["lamp_z"]/(bench["lamp_z"]-obj["height"])
        base = [[position[0]+obj["radius"]*math.cos(obj["angle"]+i*2*math.pi/obj["sides"]),
                 position[1]+obj["radius"]*math.sin(obj["angle"]+i*2*math.pi/obj["sides"])] for i in range(obj["sides"])]
        top = [[lamp[k]+scale*(p[k]-lamp[k]) for k in (0, 1)] for p in base]
        result.append(dict(id=obj["id"], base=base, top=top, shadow=hull(base+top),
            center=[lamp[k]+scale*(position[k]-lamp[k]) for k in (0, 1)]))
    return result


def disk_inside(point, polygon, radius):
    return all(cross(p, polygon[(i+1) % len(polygon)], point) >=
               radius*math.dist(p, polygon[(i+1) % len(polygon)])-1e-7 for i, p in enumerate(polygon))


def disk_overlap(point, polygon, radius):
    if disk_inside(point, polygon, 0):
        return True
    for i, a in enumerate(polygon):
        b = polygon[(i+1) % len(polygon)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        u = max(0, min(1, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
        if math.dist(point, [a[0]+u*dx, a[1]+u*dy]) < radius-1e-7:
            return True
    return False


def sample_hit(state, bench, ms, point, lamp_shifts=None):
    radius = state["physics"]["aperture_radius"]
    scene = polygons(state, bench, ms, lamp_shifts)
    # The same draw order defines occlusion. No covered pixel is attributed to
    # a rear shadow, and an aperture straddling two films collects neither.
    for index in range(len(scene)-1, -1, -1):
        entry = scene[index]
        if disk_inside(point, entry["top"], radius):
            if any(disk_overlap(point, front["shadow"], radius) for front in scene[index+1:]):
                return None
            if any(disk_overlap(point, item["base"], radius) for item in scene):
                return None
            return entry["id"]
    return None


class Simulation:
    def __init__(self, state):
        self.state = state
        self.ms = 0
        self.active = False
        self.terminal = ""
        self.lamp_shifts = [[] for _ in state["benches"]]
        self.cameras = [dict(position=[480., 194.], velocity=[0., 0.], target=[480., 194.],
                             charge=0, sample=None, hit=None) for _ in state["benches"]]

    def advance(self, end):
        spec = self.state["physics"]
        while self.active and not self.terminal and self.ms+10 <= end:
            self.ms += 10
            for i, (bench, cam) in enumerate(zip(self.state["benches"], self.cameras)):
                for k in (0, 1):
                    a = max(-spec["acceleration_limit"], min(spec["acceleration_limit"],
                        (cam["target"][k]-cam["position"][k])*spec["spring"]-cam["velocity"][k]*spec["damping"]))
                    cam["velocity"][k] += a*.01
                speed = math.hypot(*cam["velocity"])
                if speed > spec["speed_limit"]:
                    cam["velocity"] = [v*spec["speed_limit"]/speed for v in cam["velocity"]]
                for k, limit in ((0, 960), (1, 220)):
                    cam["position"][k] = max(7, min(limit-7, cam["position"][k]+cam["velocity"][k]*.01))
                    if cam["position"][k] in (7, limit-7):
                        cam["velocity"][k] = 0
                hit = sample_hit(self.state, bench, self.ms, cam["position"], self.lamp_shifts[i])
                cam["hit"] = hit
                if hit:
                    if cam["sample"] != hit:
                        cam["charge"] = 0
                    cam["sample"] = hit
                    cam["charge"] = min(spec["exposure_ms"], cam["charge"]+10)
                else:
                    cam["charge"] = max(0, cam["charge"]-10*spec["fade_rate"])
                if cam["charge"] >= spec["exposure_ms"] and cam["sample"] != bench["objects"][bench["forged_index"]]["id"]:
                    self.terminal = "honest shadow developed"
            if not self.terminal and all(c["charge"] >= spec["exposure_ms"] for c in self.cameras):
                self.terminal = "pass"
            if not self.terminal and self.ms >= spec["time_limit_ms"]:
                self.terminal = "exposure time exhausted"

    def snapshot(self):
        return dict(t_ms=self.ms, active=self.active, terminal=self.terminal,
            lamp_shifts=self.lamp_shifts,
            cameras=[dict(position=[round(v, 4) for v in c["position"]],
                velocity=[round(v, 4) for v in c["velocity"]], target=c["target"],
                charge=c["charge"], sample=c["sample"]) for c in self.cameras])


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("non-finite numeric input")
    return value


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    if not all(isinstance(x, dict) for x in (payload, ground_truth, public_state)):
        return fail("malformed submission or contract")
    try:
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or mismatched "+key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("parameters", "physics", "benches", "stage", "inspection", "control_condition"):
            if ground_truth[key] != public_state.get(key):
                return fail("public contract mismatch: "+key)
        mode = ground_truth["control_condition"]["interaction"]
        if payload.get("interaction_mode") != mode or mode not in ("full", "simplified"):
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 6000:
            return fail("missing or oversized camera transcript")
        sim = Simulation(ground_truth)
        drag = None
        previous = 0
        for sequence, event in enumerate(events, 1):
            if not isinstance(event, dict):
                return fail("malformed event")
            t = finite(event["t_ms"])
            if event.get("seq") != sequence or t < previous or t % 10 or t > 120000:
                return fail("invalid event sequence or time")
            previous = t
            sim.advance(t)
            if sim.terminal:
                return fail("input after terminal outcome")
            if not sim.active and t:
                return fail("inactive time cannot advance")
            kind = event["kind"]
            if not isinstance(kind, str):
                return fail("malformed event kind")
            if kind == "start":
                if sim.active or t != 0 or event.get("surface") != "start_button":
                    return fail("invalid start")
                sim.active = True
                continue
            if kind == "file":
                return fail("incomplete filing ended the attempt")
            if kind.startswith("lamp_"):
                bench = event["bench"]
                if type(bench) is not int or not 0 <= bench < len(sim.cameras):
                    return fail("invalid lamp table")
                point = event["point"]
                if not isinstance(point, list) or len(point) != 2 or not 0 <= finite(point[0]) <= 960 or not 0 <= finite(point[1]) <= 220:
                    return fail("lamp point outside table")
                if not sim.active:
                    return fail("lamp tests require a live scan")
                spec = ground_truth["inspection"]
                lamp = lamp_at(ground_truth, ground_truth["benches"][bench], t)
                actual = [lamp[0]+lamp_shift_at(sim.lamp_shifts[bench], t), lamp[1]]
                if mode == "full":
                    if event.get("surface") != "lamp_drag":
                        return fail("wrong lamp input surface")
                    if kind == "lamp_grab":
                        if drag is not None or math.dist(point, actual) > spec["lamp_grab_radius"]+.02:
                            return fail("drag did not start on the visible lamp")
                        drag = ("lamp", bench)
                        continue
                    if kind not in ("lamp_aim", "lamp_release", "lamp_cancel") or drag != ("lamp", bench):
                        return fail("lamp is not held")
                    if kind in ("lamp_release", "lamp_cancel"):
                        drag = None
                    if kind == "lamp_cancel":
                        continue
                elif kind != "lamp_shift" or event.get("surface") != "lamp_click" or point[1] > spec["rail_height"] or abs(point[0]-lamp[0]) > spec["rail_half_span"]+.02:
                    return fail("wrong lamp input surface")
                shift = round(max(-spec["rail_half_span"], min(spec["rail_half_span"], point[0]-lamp[0])), 4)
                sim.lamp_shifts[bench].append([t, shift])
                continue
            if mode == "full" and kind not in ("grab", "aim", "release", "cancel") or mode == "simplified" and kind != "target":
                return fail("wrong input surface")
            if event.get("surface") != ("camera_drag" if mode == "full" else "camera_click"):
                return fail("wrong input surface")
            bench = event["bench"]
            if type(bench) is not int or not 0 <= bench < len(sim.cameras):
                return fail("invalid table")
            cam = sim.cameras[bench]
            point = event["point"]
            if not isinstance(point, list) or len(point) != 2 or not 0 <= finite(point[0]) <= 960 or not 0 <= finite(point[1]) <= 220:
                return fail("camera point outside table")
            if kind == "grab":
                if drag is not None or math.dist(point, cam["position"]) > ground_truth["physics"]["grab_radius"]+.02:
                    return fail("drag did not start on the visible camera")
                drag = bench
            elif kind in ("aim", "release", "cancel"):
                if drag != bench:
                    return fail("camera is not held")
                if kind != "cancel":
                    cam["target"] = point
                if kind in ("release", "cancel"):
                    drag = None
            elif kind == "target":
                cam["target"] = point
        end = finite(payload["final_t_ms"])
        if end < previous or end > 120000 or end % 10:
            return fail("invalid endpoint")
        sim.advance(end)
        if payload.get("completed") is not True or sim.terminal != "pass" or sim.ms != end:
            return fail("exposures incomplete or failed: "+sim.terminal)
        snapshot = sim.snapshot()
        claimed = payload.get("final_state")
        if not isinstance(claimed, dict) or any(claimed.get(k) != snapshot[k] for k in ("t_ms", "active", "terminal", "lamp_shifts")):
            return fail("false endpoint claim")
        if len(claimed.get("cameras", [])) != len(sim.cameras):
            return fail("false camera count")
        for actual, supplied in zip(snapshot["cameras"], claimed["cameras"]):
            if not isinstance(supplied, dict):
                return fail("malformed camera claim")
            for k in ("charge", "sample", "target"):
                if actual[k] != supplied.get(k):
                    return fail("false camera "+k)
            for k in ("position", "velocity"):
                if not isinstance(supplied.get(k), list) or len(supplied[k]) != 2 or any(abs(finite(a)-finite(b)) > .001 for a, b in zip(actual[k], supplied[k])):
                    return fail("false camera "+k)
        return dict(graded=True, passed=True, score=100,
                    feedback=f"independent optical replay: {len(sim.cameras)} concurrent forged exposures at {end/1000:g}s")
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as error:
        return fail("invalid shadow transcript: "+str(error))


def cheat(public_state, ground_truth):
    return dict(forged_ids=ground_truth["forged_ids"])
