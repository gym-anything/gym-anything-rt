"""Independent fixed-step replay of primitive optical controls; Pyodide-safe."""
from __future__ import annotations

import copy
import math

MECHANIC_ID = "cursor_constellation_hunt_v3"


def target_at(field, ms):
    u = max(0., ms)/field["span_ms"]
    index = min(int(u), len(field["path"])-2)
    f = min(1., u-index)
    blend = f*f*(3-2*f)
    a, b = field["path"][index:index+2]
    return [a[i]+(b[i]-a[i])*blend for i in (0,1)]


def target_velocity(field, ms):
    u = max(0., ms)/field["span_ms"]
    index = min(int(u), len(field["path"])-2)
    f = min(1., u-index)
    a,b = field["path"][index:index+2]
    return [(b[i]-a[i])*6*f*(1-f)*1000/field["span_ms"] for i in (0,1)]


def clamp(v, a, b):
    return max(a, min(b, v))


class Replay:
    def __init__(self, world):
        self.world = world
        self.ms = 0
        self.origin = None
        self.passed = False
        self.failed = ""
        self.lenses = [dict(p=list(f["initial_lens"]), v=list(f["initial_velocity"]),
                            target=list(f["initial_lens"]), charge=0.) for f in world["fields"]]
        self.drag = None

    def advance(self, absolute_ms):
        if self.origin is None: return
        end = absolute_ms-self.origin
        w = self.world
        dt = w["tick_ms"]/1000
        while self.ms+w["tick_ms"] <= end and not self.failed and not self.passed:
            self.ms += w["tick_ms"]
            for lens, field in zip(self.lenses, w["fields"]):
                for axis in (0,1):
                    force = clamp((lens["target"][axis]-lens["p"][axis])*w["spring"] -
                                  lens["v"][axis]*w["damping"], -w["acceleration_cap"],w["acceleration_cap"])
                    lens["v"][axis] = clamp(lens["v"][axis]+force*dt,-w["max_speed"],w["max_speed"])
                    lens["p"][axis] = clamp(lens["p"][axis]+lens["v"][axis]*dt,16.,304.)
                    if lens["p"][axis] in (16.,304.): lens["v"][axis]=0.
                good = math.dist(lens["p"],target_at(field,self.ms)) <= w["tolerance"]
                lens["charge"] = clamp(lens["charge"]+w["tick_ms"]*(1 if good else -w["fade_rate"]),0.,w["exposure_ms"])
            self.passed = all(l["charge"] >= w["exposure_ms"] for l in self.lenses)
            if self.ms >= w["max_active_ms"] and not self.passed:
                self.failed = "EXPOSURE EXPIRED"

    def snapshot(self):
        return dict(ms=self.ms, origin=self.origin, passed=self.passed, failed=self.failed,
                    lenses=copy.deepcopy(self.lenses), drag=self.drag)


def _fail(message):
    return dict(graded=True,passed=False,score=0,feedback=message)


def _point(value):
    return isinstance(value,list) and len(value)==2 and all(
        type(x) in (float,int) and math.isfinite(x) and 0 <= x <= 320 for x in value)


def grade(payload, ground_truth, public_state):
    try:
        if not all(isinstance(value,dict) for value in (payload,ground_truth,public_state)):
            return _fail("invalid constellation contract")
        for key in ("mechanic_id","task_id","challenge_id"):
            if not ground_truth.get(key) or payload.get(key)!=ground_truth[key] or public_state.get(key)!=ground_truth[key]:
                return _fail("stale or wrong "+key)
        if ground_truth["mechanic_id"]!=MECHANIC_ID: return _fail("wrong mechanic")
        for key in ("control_condition","world"):
            if public_state.get(key)!=ground_truth.get(key): return _fail("public contract mismatch: "+key)
        mode = ground_truth["control_condition"]["interaction"]
        if mode not in ("full","simplified") or payload.get("interaction_mode")!=mode:
            return _fail("wrong interaction")
        events=payload.get("events")
        if not isinstance(events,list) or not 2 <= len(events) <= 10000:
            return _fail("missing or excessive controls")
        sim=Replay(ground_truth["world"])
        previous=-1
        sealed=False
        for index,e in enumerate(events,1):
            if not isinstance(e,dict): return _fail("invalid control event")
            t=e.get("t_ms")
            if type(t) not in (int,float) or not math.isfinite(t) or not previous<=t<=600000 or type(e.get("sequence")) is not int or e.get("sequence")!=index or sealed:
                return _fail("invalid event ordering or time")
            previous=t
            sim.advance(t)
            k=e.get("kind")
            if k=="seal":
                sealed=True
                if index!=len(events): return _fail("input after final seal")
                continue
            if sim.failed or sim.passed: return _fail("input after terminal exposure")
            if e.get("input_source")!=mode: return _fail("wrong input surface")
            if k=="start":
                if sim.origin is not None or sim.drag is not None: return _fail("duplicate or held start")
                sim.origin=t
                continue
            field=e.get("field")
            point=e.get("point")
            if type(field) is not int or not 0<=field<len(sim.lenses) or not _point(point):
                return _fail("invalid field or geometry")
            lens=sim.lenses[field]
            if k=="down" and mode=="full" and sim.drag is None:
                if math.dist(point,lens["p"])>22: return _fail("drag did not start on visible lens")
                sim.drag=field
            elif k=="move" and mode=="full" and sim.drag==field:
                lens["target"]=[clamp(x,16.,304.) for x in point]
                if sim.origin is None: lens["p"]=list(lens["target"])
            elif k=="up" and mode=="full" and sim.drag==field:
                sim.drag=None
            elif k=="aim" and mode=="simplified" and sim.drag is None:
                lens["target"]=[clamp(x,16.,304.) for x in point]
                if sim.origin is None: lens["p"]=list(lens["target"])
            else:
                return _fail("illegal or mismatched control")
        if not sealed or sim.origin is None or payload.get("completed") is not True or not sim.passed or sim.failed:
            return _fail(sim.failed or "all constellations must be exposed together")
        final=payload.get("final")
        if not isinstance(final,dict) or final.get("ms")!=sim.ms:
            return _fail("final clock mismatch")
        lenses=final.get("lenses")
        if not isinstance(lenses,list) or len(lenses)!=len(sim.lenses): return _fail("missing lens")
        for got,expected in zip(lenses,sim.lenses):
            if not isinstance(got,dict): return _fail("invalid lens")
            charge=got.get("charge")
            if not _point(got.get("p")) or type(charge) not in (int,float) or not math.isfinite(charge) or math.dist(got["p"],expected["p"])>.03 or abs(charge-expected["charge"])>.001:
                return _fail("final optical state mismatch")
        return dict(graded=True,passed=True,score=100,
                    feedback=f"Independent exposure replay: {len(sim.lenses)} constellations aligned together at {sim.ms} ms.")
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as exc:
        return _fail("invalid constellation transcript: "+str(exc))


def cheat(public_state, ground_truth):
    return dict(planning="privileged initial focus points",points=[target_at(f,0) for f in ground_truth["world"]["fields"]])
