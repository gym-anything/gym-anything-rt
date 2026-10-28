"""Independent fixed-step replay; never accepts a browser success claim."""
from __future__ import annotations

import math

MECHANIC_ID = "tomographic_baggage_surgery_v3"


def motion(spec, t):
    u = max(0, t)/spec["span_ms"]
    n = min(int(u), len(spec["knots"])-2)
    f = min(1, u-n)
    h = f*f*(3-2*f)
    return [a+(b-a)*h for a,b in zip(spec["knots"][n],spec["knots"][n+1])]


def initial(c):
    return dict(t=0, x=c["physics"]["entry_x"], yz=[0.,0.], velocity=[0.,0.], command=[0.,0.],
                phase="ready", held=False, failure=None, crossed=[], drag=False, scanned=[])


def advance(c, s, end):
    p=c["physics"]; dt=p["dt_ms"]/1000; params=c["parameters"]
    while s["t"] < end:
        s["t"] += p["dt_ms"]
        if s["phase"] in ("failed","complete"):
            continue
        if s["phase"] == "ready":
            continue
        for i in range(2):
            a=max(-p["max_accel"],min(p["max_accel"], params["gain"]*(s["command"][i]-s["yz"][i])-params["damping"]*s["velocity"][i]))
            s["velocity"][i]=max(-p["max_speed"],min(p["max_speed"],s["velocity"][i]+a*dt))
            s["yz"][i]+=s["velocity"][i]*dt
        old=s["x"]
        if s["phase"] == "inbound":
            s["x"]=min(p["target_x"],s["x"]+params["speed"]*dt)
            if s["x"] == p["target_x"]: s["phase"]="grip"
        elif s["phase"] == "outbound":
            s["x"]=max(p["entry_x"],s["x"]-params["speed"]*dt)
        r=p["load_radius"] if s["held"] else p["tool_radius"]
        # The rendered body is an axial cylinder of half-depth and transverse
        # radius r. Its exact plate overlap is a 1D interval and a 2D disk.
        if any(abs(v)+r>p["bounds"] for v in s["yz"]):
            s["failure"]="case wall"
        for g in c["gates"]:
            if abs(s["x"]-g["x"]) <= g["half"]+r:
                center=motion(g["motion"],s["t"])
                if math.dist(s["yz"],center)+r > g["radius"]:
                    s["failure"]=f"layer {g['id']} contact"
            if (old-g["x"])*(s["x"]-g["x"]) <= 0 and old != s["x"]:
                tag=f"{g['id']}:{'out' if s['held'] else 'in'}"
                if tag not in s["crossed"]: s["crossed"].append(tag)
        if s["t"] >= p["max_ms"]: s["failure"]="time allowance exhausted"
        if s["failure"]: s["phase"]="failed"
        elif s["held"] and s["x"] <= p["entry_x"]: s["phase"]="complete"
    return s


def apply(c, s, e):
    """Primitive pad events and grip. Called only after monotone time validation."""
    mode=c["control_condition"]["interaction"]
    if s["phase"] in ("failed","complete"): raise ValueError("action after terminal outcome")
    kind=e["kind"]
    if kind == "slice_scan":
        layer=e.get("layer_id")
        if (e.get("input_source") != c["sensing"]["input_source"] or type(layer) is not int
                or layer not in {g["id"] for g in c["gates"]}):
            raise ValueError("invalid transverse scan")
        if layer not in s["scanned"]: s["scanned"].append(layer)
    elif kind == "start":
        if s["phase"] != "ready": raise ValueError("duplicate start")
        s["phase"]="inbound"
    elif kind in ("pad_down","pad_move","pad_up","pad_click"):
        if e.get("input_source") != ("drag_pad" if mode=="full" else "click_pad"):
            raise ValueError("wrong interaction surface")
        point=e.get("point")
        if not isinstance(point,list) or len(point)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point):
            raise ValueError("invalid pad point")
        v=c["views"]
        command=[(point[0]-v["pad_origin"][0])/v["pad_scale"],(v["pad_origin"][1]-point[1])/v["pad_scale"]]
        if any(abs(a)>v["pad_extent"]+1e-9 for a in command): raise ValueError("pad point outside surface")
        if mode=="full":
            if kind=="pad_down":
                if s["drag"] or math.dist(command,s["command"])*v["pad_scale"]>v["handle_radius"]:
                    raise ValueError("drag missed command handle")
                s["drag"]=True
            elif kind=="pad_move":
                if not s["drag"]: raise ValueError("orphan drag move")
                s["command"]=command
            elif kind=="pad_up":
                if not s["drag"]: raise ValueError("orphan drag release")
                s["command"]=command; s["drag"]=False
            else: raise ValueError("full mode requires dragging")
        elif kind=="pad_click": s["command"]=command
        else: raise ValueError("simplified mode requires a click")
    elif kind=="grip":
        if e.get("input_source") != ("space_key" if mode=="full" else "grip_button"):
            raise ValueError("wrong grip surface")
        if s["phase"] != "grip" or math.dist(s["yz"], motion(c["target"]["motion"],s["t"]))>c["physics"]["grip_distance"]:
            s["failure"]="empty grip";s["phase"]="failed"
        else: s["held"]=True;s["phase"]="outbound"
    else: raise ValueError("unknown event")
    return s


def grade(payload, ground_truth, public_state):
    def fail(message): return dict(graded=True,passed=False,score=0,feedback=message)
    try:
        for k in ("mechanic_id","task_id","challenge_id","revision"):
            if not ground_truth.get(k) or payload.get(k)!=ground_truth[k] or public_state.get(k)!=ground_truth[k]:
                return fail("stale or mismatched "+k)
        if ground_truth["mechanic_id"] != MECHANIC_ID: return fail("wrong mechanic")
        for k in ("gates","target","physics","parameters","views","sensing","control_condition"):
            if public_state.get(k)!=ground_truth[k]: return fail("contract mismatch: "+k)
        if payload.get("interaction")!=ground_truth["control_condition"]["interaction"]: return fail("wrong interaction")
        events=payload.get("events")
        if not isinstance(events,list) or not 1<=len(events)<=12000: return fail("missing action trace")
        s=initial(ground_truth); previous=0
        dt=ground_truth["physics"]["dt_ms"]
        for seq,e in enumerate(events,1):
            t=e["t_ms"]
            if type(t) is not int or t%dt or not previous<=t<=ground_truth["physics"]["max_ms"] or e.get("sequence")!=seq:
                return fail("nonmonotone, nonfinite or invalid action time")
            advance(ground_truth,s,t); apply(ground_truth,s,e);previous=t
        end=payload.get("final_t_ms")
        if type(end) is not int or end%dt or not previous<=end<=ground_truth["physics"]["max_ms"]: return fail("invalid final time")
        advance(ground_truth,s,end)
        required={f"{g['id']}:{direction}" for g in ground_truth["gates"] for direction in ("in","out")}
        passed=s["phase"]=="complete" and s["held"] and not s["failure"] and set(s["crossed"])==required
        # Crossings are physical consequences, never a minimum input count.
        return dict(graded=True,passed=passed,score=100 if passed else 0,
                    feedback=s["failure"] or ("clean 3D extraction" if passed else "extraction incomplete"),
                    replay={k:s[k] for k in ("t","x","yz","phase","held","failure","crossed","scanned")})
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as exc:
        return fail("invalid extraction trace: "+str(exc))


def cheat(public_state, ground_truth):
    return dict(note="No automatic intervention. Geometry is available for privileged construction diagnostics only.")
