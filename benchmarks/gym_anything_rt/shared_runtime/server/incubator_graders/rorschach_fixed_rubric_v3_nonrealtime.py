"""Independent fixed-step replay of geometry, apertures, deposition and spillage."""
from __future__ import annotations

import bisect
import copy
import math

MECHANIC_ID = "rorschach_fixed_rubric_v3_nonrealtime"
REVISION = "living-ink-press-5-inspection"
ACTION_EVENTS = {"begin", "release", "place"}


def channel(knots, t):
    index = max(0, min(len(knots)-2, bisect.bisect_right([p[0] for p in knots], t)-1))
    a, b = knots[index:index+2]
    f = max(0., min(1., (t-a[0])/(b[0]-a[0])))
    return a[1]+(b[1]-a[1]) * f*f*(3-2*f)


def ink_centres(state, t):
    q = {k:channel(v,t) for k,v in state["channels"].items()}
    x, y, span, angle = 460+q["x"], 210+q["y"], 190+q["spread"], q["twist"]
    points = [[x-span*math.cos(angle), y-span*math.sin(angle)],
              [x+span*math.cos(angle), y+span*math.sin(angle)]]
    if state["parameters"]["landmarks"] == 3:
        points.append([x+q["flex"], y+110])
    return points


def finite_point(point, state):
    if (not isinstance(point, list) or len(point)!=2 or
            any(type(v) not in (int,float) or not math.isfinite(v) for v in point) or
            not 0<=point[0]<=state["stage"]["width"] or not 0<=point[1]<=state["stage"]["height"]):
        raise ValueError("point outside the ink field")
    return list(point)


def pad_targets(state, t):
    """The sheet's uncovered registration marks identify these contacts."""
    points = ink_centres(state, t)
    return [points[index] for index in state["registration"]]


class Press:
    def __init__(self, state):
        self.state = state
        self.t_ms = 0
        self.started = False
        self.pads = [dict(p=p[:], v=[0.,0.], aim=p[:]) for p in ink_centres(state, 0)]
        self.developed = self.spilled = 0.
        self.terminal = ""
        self.drag = None
        self.selected = None
        self.inspected = set()

    def advance(self, until):
        if not self.started:
            if until != 0:
                raise ValueError("preparation cannot advance the active flow clock")
            return
        step = self.state["dt_ms"]
        while self.t_ms+step<=until and not self.terminal:
            self.t_ms += step
            h = step/1000
            for pad in self.pads:
                a = [self.state["parameters"]["spring"]*(pad["aim"][i]-pad["p"][i])
                     - self.state["parameters"]["damping"]*pad["v"][i] for i in range(2)]
                magnitude = math.hypot(*a)
                scale = min(1.,self.state["acceleration_limit"]/max(magnitude,1e-12))
                for i in range(2): pad["v"][i] += a[i]*scale*h
                magnitude = math.hypot(*pad["v"])
                scale = min(1.,self.state["speed_limit"]/max(magnitude,1e-12))
                for i,limit in enumerate((self.state["stage"]["width"],self.state["stage"]["height"])):
                    pad["v"][i] *= scale
                    pad["p"][i] += pad["v"][i]*h
                    if not 0<=pad["p"][i]<=limit:
                        pad["p"][i]=max(0.,min(limit,pad["p"][i])); pad["v"][i]=0.
            fits = [math.dist(pad["p"],ink)<=self.state["parameters"]["tolerance"]
                    for pad,ink in zip(self.pads,pad_targets(self.state,self.t_ms))]
            if all(fits):
                self.developed = min(self.state["development_seconds"],self.developed+h)
            else:
                self.developed = max(0.,self.developed-self.state["fade_rate"]*h)
                self.spilled += h*sum(not fit for fit in fits)/len(fits)
            if self.spilled >= self.state["spill_limit"]-1e-9: self.terminal="spill"
            elif self.developed >= self.state["development_seconds"]-1e-9: self.terminal="printed"
            elif self.t_ms >= self.state["duration_ms"]: self.terminal="expired"

    def place(self, index, point):
        self.pads[index]["aim"] = finite_point(point,self.state)
        if not self.started:
            self.pads[index]["p"] = point[:]
            self.pads[index]["v"] = [0.,0.]

    def event(self, event, mode):
        kind = event["kind"]
        if self.terminal:
            raise ValueError("input after a terminal outcome")
        if kind == "begin":
            if self.started: raise ValueError("flow cannot restart")
            self.started=True
        elif kind == "inspect":
            index = event.get("contact")
            point = finite_point(event.get("point"), self.state)
            if (type(index) is not int or not 0 <= index < len(self.pads) or
                    math.dist(point, ink_centres(self.state, self.t_ms)[index]) > self.state["inspection_radius"]):
                raise ValueError("inspection missed the visible ink centre")
            self.inspected.add(index)
        elif mode=="full" and kind=="grab":
            point=finite_point(event.get("point"),self.state)
            index=event.get("pad")
            if type(index) is not int or not 0<=index<len(self.pads) or self.drag is not None:
                raise ValueError("invalid aperture grab")
            if math.dist(point,self.pads[index]["p"]) > self.state["ink_radius"]+self.state["parameters"]["tolerance"]+10:
                raise ValueError("grab missed the visible aperture")
            nearest=min(range(len(self.pads)),key=lambda i:math.dist(point,self.pads[i]["p"]))
            if index!=nearest:
                raise ValueError("grab targets an aperture behind the nearest visible hit")
            self.drag=dict(index=index,offset=[self.pads[index]["p"][i]-point[i] for i in range(2)])
        elif mode=="full" and kind in ("move","release"):
            point=finite_point(event.get("point"),self.state)
            if self.drag is None: raise ValueError("motion without an aperture grab")
            index=self.drag["index"]
            if event.get("pad")!=index: raise ValueError("drag changed aperture identity")
            aim=[max(0.,min(limit,point[i]+self.drag["offset"][i])) for i,limit in
                 enumerate((self.state["stage"]["width"],self.state["stage"]["height"]))]
            self.place(index,aim)
            if kind=="release": self.drag=None
        elif mode=="full" and kind=="cancel":
            if self.drag is None: raise ValueError("cancel without an aperture grab")
            self.drag=None
        elif mode=="simplified" and kind=="select":
            index=event.get("pad")
            if type(index) is not int or not 0<=index<len(self.pads): raise ValueError("invalid proxy selection")
            self.selected=index
        elif mode=="simplified" and kind=="place":
            if self.selected is None or event.get("pad")!=self.selected: raise ValueError("place without a selected aperture")
            self.place(self.selected,event.get("point"))
        else:
            raise ValueError("operation unavailable in this interaction mode")

    def snapshot(self):
        return dict(t_ms=self.t_ms,started=self.started,pads=copy.deepcopy(self.pads),
                    developed=self.developed,spilled=self.spilled,terminal=self.terminal,
                    inspected=sorted(self.inspected))


def grade(payload, ground_truth, public_state):
    def fail(message): return dict(graded=True,passed=False,score=0,feedback=message)
    try:
        if not all(isinstance(x,dict) for x in (payload,ground_truth,public_state)):
            return fail("invalid ink result")
        for key in ("mechanic_id","task_id","challenge_id","revision"):
            if not ground_truth.get(key) or payload.get(key)!=ground_truth[key] or public_state.get(key)!=ground_truth[key]:
                return fail("stale or wrong "+key)
        if ground_truth["mechanic_id"]!=MECHANIC_ID or ground_truth["revision"]!=REVISION:
            return fail("wrong ink revision")
        mapping=ground_truth.get("registration")
        if (not isinstance(mapping,list) or any(type(i) is not int for i in mapping) or
                sorted(mapping)!=list(range(ground_truth["parameters"]["landmarks"]))):
            return fail("invalid ink registration")
        if public_state!={k:v for k,v in ground_truth.items() if k!="seed"}:
            return fail("public ink geometry or control condition differs from the replay contract")
        mode=(ground_truth.get("control_condition") or {}).get("interaction","full")
        if mode not in ("full","simplified") or payload.get("interaction")!=mode:
            return fail("wrong ink interaction mode")
        events=payload.get("events")
        if not isinstance(events,list) or not events:
            return fail("missing ink transcript")
        press=Press(ground_truth)
        action_window=ground_truth.get("action_window_ms")
        if (type(action_window) is not int or action_window <= 0 or
                action_window % ground_truth["dt_ms"]):
            return fail("invalid action transition window")
        previous=0
        for index,event in enumerate(events,1):
            t=event.get("t_ms")
            if (event.get("sequence")!=index or event.get("input_source")!=mode or type(t) is not int or
                    not previous<=t<=ground_truth["duration_ms"] or t%ground_truth["dt_ms"] or
                    t != press.t_ms):
                return fail("event was not delivered at the current stable action boundary")
            previous=t
            press.event(event,mode)
            if press.started and event["kind"] in ACTION_EVENTS:
                press.advance(min(ground_truth["duration_ms"], t+action_window))
        final=payload.get("final_t_ms")
        if (type(final) is not int or not previous<=final<=ground_truth["duration_ms"] or
                final%ground_truth["dt_ms"] or final != press.t_ms):
            return fail("terminal ink time differs from the action replay")
        for key in ("developed","spilled"):
            value=payload.get(key)
            if type(value) not in (int,float) or not math.isfinite(value) or abs(value-getattr(press,key))>1e-6:
                return fail("claimed "+key+" differs from replay")
        passed=press.terminal=="printed" and payload.get("completed") is True
        return dict(graded=True,passed=passed,score=100 if passed else 0,
                    feedback=f"Living ink replay: {press.terminal or 'incomplete'}; print {press.developed:.2f}/9; spill {press.spilled:.2f}/14")
    except (TypeError,KeyError,ValueError,OverflowError,IndexError,AttributeError) as exc:
        return fail("invalid ink replay: "+str(exc))


def cheat(public_state, ground_truth):
    del public_state
    return {"channels":ground_truth["channels"]}
