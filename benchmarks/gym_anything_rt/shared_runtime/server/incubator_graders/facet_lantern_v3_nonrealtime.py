"""Independent, stdlib-only replay for settled V3 wirework."""
from __future__ import annotations

import math

MECHANIC_ID = "facet_lantern_v3_nonrealtime"


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x>>16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x>>13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x>>16)) & 0xFFFFFFFF)/4294967295*2-1


def integral(seed, t, span):
    u = max(0., t)/span
    n = math.floor(u)
    f = u-n
    total = sum((noise(seed,i)+noise(seed,i+1))/2 for i in range(n))
    a,b = noise(seed,n),noise(seed,n+1)
    return span*(total+a*f+(b-a)*(f**3-f**4/2))


def angles(world, t):
    m = world["motion"]
    return [m["angles"][i]+m["rates"][i]*(t+m["gust"]*integral(m["seed"]+i*7919,t,m["span_ms"]))/1000 for i in range(3)]


def rotate(point, a):
    x,y,z = point
    yaw,pitch,roll = a
    x,z = x*math.cos(yaw)-z*math.sin(yaw),x*math.sin(yaw)+z*math.cos(yaw)
    y,z = y*math.cos(pitch)-z*math.sin(pitch),y*math.sin(pitch)+z*math.cos(pitch)
    x,y = x*math.cos(roll)-y*math.sin(roll),x*math.sin(roll)+y*math.cos(roll)
    return [x,y,z]


def project(world, t):
    a = angles(world,t)
    points = {v["id"]:rotate(v["position"],a) for v in world["vertices"]}
    visible = set()
    faces = []
    for ids in world["faces"]:
        p,q,r = [points[k] for k in ids]
        normal_z = (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
        front = normal_z >= -1e-9
        if front:
            visible.update(ids)
        faces.append(dict(ids=ids, front=front, depth=sum(points[k][2] for k in ids)/3))
    studs = []
    for v in world["vertices"]:
        x,y,z = points[v["id"]]
        studs.append(dict(id=v["id"],label=v["label"],x=world["center"][0]+world["scale"]*x,
                          y=world["center"][1]-world["scale"]*y,depth=z,visible=v["id"] in visible))
    return dict(studs=studs, faces=faces, angles=a)


def hit(world, t, point):
    if not isinstance(point,list) or len(point)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) for x in point):
        raise ValueError("nonfinite or malformed pointer coordinates")
    if not 0 <= point[0] <= world["width"] or not 0 <= point[1] <= world["height"]:
        return None
    candidates = [p for p in project(world,t)["studs"] if p["visible"] and math.dist([p["x"],p["y"]],point) <= world["stud_radius"]+1e-7]
    return max(candidates,key=lambda p:(p["depth"],p["id"]))["id"] if candidates else None


def required_edges(world):
    return {tuple(sorted((a,b))) for f in world["targets"] for a,b in zip(f["vertices"],f["vertices"][1:]+f["vertices"][:1])}


def score(world, edges):
    complete = sum(all(tuple(sorted((a,b))) in edges for a,b in zip(f["vertices"],f["vertices"][1:]+f["vertices"][:1])) for f in world["targets"])
    used = {x for e in edges for x in e}
    return 10*len(edges)+30*complete-(len(world["vertices"])-len(used)),complete


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True,passed=False,score=0,feedback=message)
    if not all(isinstance(x,dict) for x in (payload,ground_truth,public_state)):
        return fail("malformed submission")
    for k in ("mechanic_id","task_id","challenge_id","control_condition","world"):
        if ground_truth.get(k) != public_state.get(k):
            return fail("public/truth contract mismatch: "+k)
    for k in ("mechanic_id","task_id","challenge_id","control_condition"):
        if not ground_truth.get(k) or payload.get(k)!=ground_truth[k]:
            return fail("stale or mismatched "+k)
    if ground_truth["mechanic_id"]!=MECHANIC_ID:
        return fail("wrong mechanic")
    mode = ground_truth["control_condition"].get("interaction")
    if mode not in ("full","simplified"):
        return fail("invalid interaction")
    world = ground_truth["world"]
    events = payload.get("events")
    if not isinstance(events,list) or not 2 <= len(events) <= 4000:
        return fail("missing or excessive transcript")
    edges = {tuple(sorted(x)) for x in world["initial_edges"]}
    required = required_edges(world)
    if not edges < required or {tuple(x) for x in ground_truth.get("required_edges",[])} != required:
        return fail("invalid generated commission")
    selected = None
    started = submitted = False
    previous = 0.
    stage_t = 0.
    try:
        for seq,e in enumerate(events,1):
            if not isinstance(e,dict):
                return fail("malformed event")
            t=e.get("t_ms")
            if (not isinstance(e,dict) or e.get("seq")!=seq or type(t) not in (int,float) or
                not math.isfinite(t) or not previous <= t < world["duration_ms"] or submitted):
                return fail("invalid sequence or action time")
            step = float(world.get("decision_step_ms", 700))
            if t != (0.0 if not started else stage_t):
                return fail("action time does not match the settled decision state")
            previous=t
            kind=e.get("kind")
            if kind=="start":
                if started or seq!=1 or t!=0 or e.get("input_source")!="launch_button":
                    return fail("invalid launch")
                started=True
                stage_t = 0.0
                continue
            if not started:
                return fail("wirework before launch")
            if kind=="inspect":
                actual=hit(world,t,e.get("point"))
                label=next((v["label"] for v in world["vertices"] if v["id"]==actual),None)
                if (e.get("input_source")!="hover" or actual is None or actual!=e.get("hit_id") or
                    e.get("label")!=label):
                    return fail("inspection does not match visible stud etching")
            elif kind in ("pick","release"):
                if e.get("input_source")!=mode:
                    return fail("wrong interaction surface")
                actual=hit(world,t,e.get("point"))
                if actual!=e.get("hit_id"):
                    return fail("endpoint does not match visible geometry")
                if kind=="pick":
                    if selected is not None:
                        return fail("wire already armed")
                    selected=actual
                    if actual is None:
                        stage_t += step
                elif selected is None:
                    if mode=="full" and actual is None:
                        continue
                    return fail("release without source stud")
                elif actual is None:
                    if mode=="full": selected=None
                    stage_t += step
                elif actual==selected:
                    selected=None
                    stage_t += step
                else:
                    edge=tuple(sorted((selected,actual)))
                    if edge not in required:
                        return fail("wrong wire broke the lantern")
                    edges.add(edge)
                    selected=None
                    stage_t += step
            elif kind=="cancel":
                if e.get("input_source") not in ("cancel_button","escape_key"):
                    return fail("invalid cancel")
                selected=None
            elif kind=="submit":
                if e.get("input_source")!="certify_button":
                    return fail("invalid certification")
                submitted=True
            else:
                return fail("unknown action or terminal failure")
        final=payload.get("final_t_ms")
        if type(final) not in (int,float) or not math.isfinite(final) or final!=previous:
            return fail("final time differs from final input")
        expected_score,complete=score(world,edges)
        if (not submitted or selected is not None or edges!=required or payload.get("completed") is not True or
            payload.get("edges")!=[list(x) for x in sorted(edges)] or payload.get("reported_score")!=expected_score):
            return fail("commission incomplete or claimed outcome differs from replay")
        return dict(graded=True,passed=True,score=100,
                    feedback=f"3D wirework replay: {len(edges)} wires; {complete} closed panes; score {expected_score}")
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        return fail("malformed wirework: "+str(exc))


def cheat(public_state, ground_truth):
    return dict(required_edges=ground_truth.get("required_edges"))
