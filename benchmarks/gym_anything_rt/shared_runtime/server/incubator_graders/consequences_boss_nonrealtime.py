"""Independent analytic motion and action-triggered snapshot replay."""
from __future__ import annotations

import math

MECHANIC_ID = "consequences_boss_nonrealtime"
REVISION = "covenant-echoes-v1"
DECISION_STEP_MS = 700
PREVIEW_OFFSET_MS = 1200


def noise(seed, index):
    x = (int(seed) ^ ((index+1)*0x9e3779b9)) & 0xffffffff
    x = ((x ^ (x >> 16))*0x85ebca6b) & 0xffffffff
    x = ((x ^ (x >> 13))*0xc2b2ae35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff)/4294967295*2-1


def position(item, time_ms):
    age = max(0, time_ms-item["spawn_ms"])
    u = age/item["bend_ms"]
    i, f = math.floor(u), u % 1
    a, b = noise(item["motion_seed"], i), noise(item["motion_seed"], i+1)
    x = 640 + item["drift"]*(a+(b-a)*(1-math.cos(f*math.pi))/2)
    y = (238+115*math.sin(age/3100+item["y_phase"]) if item["protected"] else
         70 + (425-item["radius"]-70)*age/item["lifetime_ms"])
    return [x,y]


def snapshot_time(item, step, world):
    """Return the stable court snapshot for one action-triggered step."""
    config = world["nonrealtime"]
    offset = int(config["preview_offset_ms"])
    advance = int(config["decision_step_ms"])
    if item["protected"]:
        return offset + step * advance
    return item["spawn_ms"] + offset + step * advance


def snapshot_position(item, step, world):
    return position(item, snapshot_time(item, step, world))


def active(item, time_ms):
    return item["spawn_ms"] <= time_ms < item["spawn_ms"]+item["lifetime_ms"]


def hit(world, point, step, saved):
    # Mirrors painting: white wisps first, judgments last; latest draw wins.
    items = world["wisps"] + world["echoes"]
    for item in reversed(items):
        if (item["id"] not in saved and active(item,snapshot_time(item,step,world)) and
                math.dist(point,snapshot_position(item,step,world)) <= item["radius"]):
            return item
    return None


def number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError("non-finite number")
    return value


def point(value, world):
    if not isinstance(value,list) or len(value)!=2:
        raise ValueError("invalid point")
    x,y = map(number,value)
    if not 0<=x<=world["stage"]["width"] or not 0<=y<=world["stage"]["height"]:
        raise ValueError("point outside stage")
    return [x,y]


def replay(payload, world):
    mode = (world.get("control_condition") or {}).get("interaction","full")
    if mode not in ("full","simplified") or payload.get("interaction_mode")!=mode:
        raise ValueError("wrong interaction mode")
    source = "seal_drag" if mode=="full" else "seal_proxy"
    events = payload.get("events")
    if not isinstance(events,list) or not events:
        raise ValueError("missing action transcript")
    config = world.get("nonrealtime")
    if not isinstance(config,dict) or config.get("action_triggered") is not True:
        raise ValueError("missing action-triggered snapshot contract")
    if config.get("decision_step_ms") != DECISION_STEP_MS or config.get("preview_offset_ms") != PREVIEW_OFFSET_MS:
        raise ValueError("unsupported snapshot timing contract")
    vows, saved, hold, selected, started = {}, set(), None, None, None
    step = 0
    previous = 0
    terminal = False
    for seq,e in enumerate(events,1):
        if not isinstance(e,dict) or e.get("sequence")!=seq:
            raise ValueError("invalid sequence")
        t = number(e.get("t_ms"))
        if not previous<=t<=600000 or terminal:
            raise ValueError("invalid event time or action after completion")
        previous = t
        kind = e.get("kind")
        if kind in ("select","seal_down"):
            if e.get("input_source")!=source or kind!=("seal_down" if mode=="full" else "select") or hold:
                raise ValueError("wrong seal input surface or overlapping drag")
            p=point(e.get("point"),world)
            seal=next((s for s in world["seals"] if math.dist(p,[s["x"],s["y"]])<=s["radius"]),None)
            if seal is None or e.get("seal")!=seal["id"]:
                raise ValueError("seal acquisition missed its visible geometry")
            selected=seal["id"]
            if mode=="full": hold=True
        elif kind in ("apply","seal_up"):
            if e.get("input_source")!=source or kind!=("seal_up" if mode=="full" else "apply"):
                raise ValueError("wrong application input surface")
            if selected is None or mode=="full" and not hold:
                raise ValueError("seal was not acquired")
            if e.get("seal")!=selected:
                raise ValueError("seal changed during gesture")
            p=point(e.get("point"),world)
            if started is None:
                witness=next((w for w in world["witnesses"] if math.dist(p,[w["x"],w["y"]])<=34),None)
                if witness:
                    vows[witness["id"]]=selected
            else:
                item=hit(world,p,step,saved)
                if item is None:
                    raise ValueError("cast missed the current judgment snapshot")
                if item["protected"]:
                    raise ValueError("protected white-ring wisp was struck")
                if vows[item["witness_id"]]!=selected:
                    raise ValueError("the cast broke an earlier covenant")
                saved.add(item["id"])
                step += 1
                if any(e["id"] not in saved and not active(e,snapshot_time(e,step,world)) for e in world["echoes"]):
                    raise ValueError("a judgment reached the court boundary after the cast")
            hold=None
            selected=None
            terminal=len(saved)==len(world["echoes"])
        elif kind=="cancel":
            if mode!="full" or e.get("input_source")!=source or not hold:
                raise ValueError("invalid cancellation")
            hold=None; selected=None
        elif kind=="start":
            if e.get("input_source")!="judgment_button" or started is not None or hold or len(vows)!=len(world["witnesses"]):
                raise ValueError("judgment requires every covenant; cannot restart")
            started=t
        else:
            raise ValueError("unknown action or unavailable reset/stop")
    final=number(payload.get("final_t_ms"))
    if not previous<=final<=600000 or started is None:
        raise ValueError("invalid final time or judgment never started")
    if payload.get("saved_ids")!=sorted(saved) or payload.get("vows")!=vows:
        raise ValueError("claimed outcome differs from replay")
    if not terminal or hold or payload.get("completed") is not True or payload.get("failure_reason"):
        raise ValueError("judgment incomplete or failed")
    return vows,saved


def grade(payload,ground_truth,public_state):
    try:
        if not all(isinstance(x,dict) for x in (payload,ground_truth,public_state)):
            raise ValueError("invalid envelope")
        for key in ("mechanic_id","revision","task_id","challenge_id"):
            if not ground_truth.get(key) or payload.get(key)!=ground_truth[key] or public_state.get(key)!=ground_truth[key]:
                raise ValueError("stale/mismatched "+key)
        if ground_truth["mechanic_id"]!=MECHANIC_ID or ground_truth["revision"]!=REVISION:
            raise ValueError("wrong mechanic revision")
        for key in ("stage","witnesses","echoes","wisps","seals","parameters","control_condition","max_run_ms","nonrealtime"):
            if public_state.get(key)!=ground_truth.get(key):
                raise ValueError("public/private contract mismatch: "+key)
        vows,saved=replay(payload,ground_truth)
        return dict(graded=True,passed=True,score=100,feedback=f"Covenants preserved; {len(saved)} judgments intercepted.")
    except (KeyError,TypeError,ValueError,OverflowError,StopIteration) as error:
        return dict(graded=True,passed=False,score=0,feedback=str(error))


def cheat(public_state,ground_truth):
    return {"notice":"No automatic solution; judgment requires visible seal casts."}
