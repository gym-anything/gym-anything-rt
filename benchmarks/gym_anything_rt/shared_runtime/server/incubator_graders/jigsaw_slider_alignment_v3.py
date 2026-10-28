"""Independent fixed-step physical replay; usable by the Python/WASM verifier."""
from __future__ import annotations

import math

MECHANIC_ID = "jigsaw_slider_alignment_v3"


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def target(piece, t_ms):
    knots = piece["knots"]
    i = next((i for i in range(len(knots)-1) if t_ms < knots[i+1]["t_ms"]), len(knots)-2)
    a, b = knots[i:i+2]
    span = b["t_ms"]-a["t_ms"]
    u = clamp((t_ms-a["t_ms"])/span, 0, 1)
    s = u*u*u*(10+u*(-15+6*u))
    ds = 30*u*u*(1-u)*(1-u)*1000/span
    return {**{k: a[k]+(b[k]-a[k])*s for k in ("x", "y", "angle")},
            **{k: (b[q]-a[q])*ds for k,q in (("vx","x"),("vy","y"),("omega","angle"))}}


def initial(truth):
    return dict(tick=0, phase="ready", clamp_tick=None, failure="", hold=None, bodies=[
        dict(**p["initial"], vx=0., vy=0., omega=0., cx=p["initial"]["x"],
             cy=p["initial"]["y"], ca=p["initial"]["angle"]) for p in truth["pieces"]])


def errors(truth, sim):
    out = []
    p = truth["parameters"]
    for piece, b in zip(truth["pieces"], sim["bodies"]):
        q = target(piece, sim["tick"]*truth["step_ms"])
        out.append(dict(position=math.hypot(b["x"]-q["x"], b["y"]-q["y"]),
                        angle=abs(b["angle"]-q["angle"]),
                        velocity=math.hypot(b["vx"]-q["vx"],b["vy"]-q["vy"]),
                        angular_velocity=abs(b["omega"]-q["omega"])))
    return out


def registered(truth, sim):
    p = truth["parameters"]
    return all(e["position"] <= p["position_tolerance"] and e["angle"] <= p["angle_tolerance"] and
               e["velocity"] <= p["velocity_tolerance"] and
               e["angular_velocity"] <= p["angular_velocity_tolerance"] for e in errors(truth,sim))


def step(truth, sim):
    if sim["phase"] not in ("running", "welding"):
        return
    dt = truth["step_ms"]/1000
    p = truth["parameters"]
    old = [dict(b) for b in sim["bodies"]]
    for i,b in enumerate(sim["bodies"]):
        for axis, vel, command in (("x","vx","cx"),("y","vy","cy")):
            spring = sum((old[j][axis]-old[i][axis]) for j in (i-1,i+1) if 0 <= j < len(old))*p["spring"]
            acc = clamp(p["stiffness"]*(b[command]-b[axis])-p["damping"]*b[vel]+spring,
                        -truth["max_acceleration"],truth["max_acceleration"])
            b[vel] = clamp(b[vel]+acc*dt,-truth["max_speed"],truth["max_speed"])
            b[axis] += b[vel]*dt
        if p["rotation_amplitude"]:
            acc = truth["angular_stiffness"]*(b["ca"]-b["angle"])-truth["angular_damping"]*b["omega"]
            b["omega"] = clamp(b["omega"]+acc*dt,-truth["max_angular_speed"],truth["max_angular_speed"])
            b["angle"] += b["omega"]*dt
        else:
            b.update(angle=0.,omega=0.,ca=0.)
    sim["tick"] += 1
    if sim["phase"] == "welding":
        if not registered(truth,sim):
            sim.update(phase="failed", failure="seam slipped")
        elif (sim["tick"]-sim["clamp_tick"])*truth["step_ms"] >= truth["weld_ms"]:
            sim["phase"] = "passed"
    if sim["tick"]*truth["step_ms"] >= truth["run_limit_ms"] and sim["phase"] not in ("passed","failed"):
        sim.update(phase="failed",failure="run expired")


def advance(truth, sim, tick):
    while sim["tick"] < tick and sim["phase"] in ("running","welding"):
        step(truth,sim)
    if sim["tick"] != tick:
        raise ValueError("event or result after a terminal state")


def inside_polygon(point, polygon):
    x,y=point
    inside=False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        if (a[1]>y)!=(b[1]>y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside=not inside
    return inside


def finite_point(point):
    return isinstance(point,list) and len(point)==2 and all(type(v) in (int,float) and math.isfinite(v) for v in point)


def in_lane(truth, piece, x):
    half_width = truth["stage"]["width"]/len(truth["pieces"])/2
    return -half_width <= x and (x <= half_width if piece == len(truth["pieces"])-1 else x < half_width)


def dial_hit(truth, piece, point):
    # Match the visible semicircle's padded hit surface and lane ownership.
    return bool(truth["parameters"]["rotation_amplitude"]) and finite_point(point) and in_lane(truth,piece,point[0]) and 24 <= math.hypot(*point) <= 52 and point[1] <= 11


def fragment_hit(truth, piece, body, point):
    if not finite_point(point) or not in_lane(truth,piece,point[0]):
        return False
    y = point[1]+truth["stage"]["center_y"]
    if not 0 <= y <= 430:
        return False
    # A dial takes precedence where its hit surface overlaps the picture.
    if dial_hit(truth,piece,[point[0],y-truth["stage"]["dial_y"]]):
        return False
    theta=-body["angle"]*math.pi/180
    dx,dy=point[0]-body["x"],point[1]-body["y"]
    local=[dx*math.cos(theta)-dy*math.sin(theta),dx*math.sin(theta)+dy*math.cos(theta)]
    return inside_polygon(local,truth["pieces"][piece]["polygon"])


def apply_event(truth, sim, event, mode):
    kind=event["kind"]
    if sim["phase"] in ("failed","passed"):
        raise ValueError("input after terminal result")
    if kind=="start":
        if sim["phase"]!="ready" or event["tick"]!=0: raise ValueError("duplicate start")
        sim["phase"]="running"
    elif kind=="clamp":
        if sim["phase"]!="running": raise ValueError("duplicate or premature clamp")
        if registered(truth,sim): sim.update(phase="welding",clamp_tick=sim["tick"])
        else: sim.update(phase="failed",failure="bad clamp")
    elif kind in ("grab","dial_grab"):
        i=event["piece"]
        start=event.get("point")
        if mode!="full" or sim["hold"] is not None or type(i) is not int or not 0 <= i < len(sim["bodies"]) or not finite_point(start):
            raise ValueError("invalid drag begin")
        b=sim["bodies"][i]
        if kind=="grab":
            if not fragment_hit(truth,i,b,start): raise ValueError("drag missed visible fragment")
        elif not dial_hit(truth,i,start):
            raise ValueError("dial drag missed ring")
        sim["hold"]={"piece":i,"kind":"position" if kind=="grab" else "angle"}
    elif kind=="release":
        if mode!="full" or sim["hold"] is None: raise ValueError("release without drag")
        sim["hold"]=None
    elif kind in ("position","angle"):
        i=event["piece"]
        if type(i) is not int or not 0 <= i < len(sim["bodies"]): raise ValueError("invalid fragment")
        b=sim["bodies"][i]
        if kind=="angle" and not truth["parameters"]["rotation_amplitude"]:
            raise ValueError("rotation is locked at this difficulty")
        if mode=="full" and sim["hold"]!={"piece":i,"kind":kind}:
            raise ValueError("command requires the matching held control")
        if kind=="position":
            if not finite_point(event.get("point")): raise ValueError("invalid carriage command")
            x,y=event["point"]
            if not -120 <= x <= 120 or not -145 <= y <= 150: raise ValueError("outside carriage travel")
            b.update(cx=x*truth["pieces"][i]["drive_x"],cy=y)
        else:
            angle=event["angle"]
            if type(angle) not in (float,int) or not math.isfinite(angle) or not -90 <= angle <= 90:
                raise ValueError("invalid dial angle")
            b["ca"]=angle
    else:
        raise ValueError("unknown control")


def grade(payload, ground_truth, public_state):
    def fail(message): return dict(graded=True,passed=False,score=0,feedback=message)
    if not isinstance(payload,dict): return fail("missing registration transcript")
    for key in ("mechanic_id","task_id","challenge_id","physics_revision","control_condition","parameters","pieces","stage","step_ms","weld_ms","run_limit_ms","max_speed","max_acceleration","angular_stiffness","angular_damping","max_angular_speed","preview_ms","trail_ms"):
        if public_state.get(key)!=ground_truth.get(key): return fail("public world mismatch: "+key)
    for key in ("mechanic_id","task_id","challenge_id","physics_revision"):
        if payload.get(key)!=ground_truth.get(key): return fail("challenge mismatch: "+key)
    mode=ground_truth["control_condition"]["interaction"]
    if payload.get("interaction_mode")!=mode: return fail("wrong interaction mode")
    events=payload.get("events")
    if not isinstance(events,list) or not 1 <= len(events) <= 15000: return fail("missing or oversized events")
    sim=initial(ground_truth)
    previous=0
    try:
        for n,event in enumerate(events,1):
            tick=event["tick"]
            if type(tick) is not int or not previous <= tick <= ground_truth["run_limit_ms"]//ground_truth["step_ms"]:
                raise ValueError("invalid event time")
            if event.get("sequence")!=n or event.get("input_source")!=mode: raise ValueError("event order or input surface mismatch")
            advance(ground_truth,sim,tick)
            apply_event(ground_truth,sim,event,mode)
            previous=tick
        final=payload["final_tick"]
        if type(final) is not int or not previous <= final <= ground_truth["run_limit_ms"]//ground_truth["step_ms"]:
            raise ValueError("invalid final tick")
        advance(ground_truth,sim,final)
        if sim["phase"]!="passed" or payload.get("completed") is not True: return fail(sim["failure"] or "registration unfinished")
        return dict(graded=True,passed=True,score=100,feedback="independent physical replay: all moving seams registered",final_tick=final)
    except (KeyError,TypeError,ValueError,OverflowError) as error:
        return fail("invalid registration transcript: "+str(error))


def cheat(public_state, ground_truth):
    return {"pieces":ground_truth.get("pieces",[])}
