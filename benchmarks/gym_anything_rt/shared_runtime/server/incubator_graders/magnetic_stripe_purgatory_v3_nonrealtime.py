"""Independent fixed-step replay of the physical feed, not a completion claim."""
from __future__ import annotations
import math

MECHANIC_ID = "magnetic_stripe_purgatory_v3_nonrealtime"

def noise(seed, index):
    x=(int(seed)^((int(index)+1)*0x9E3779B9))&0xFFFFFFFF
    x=((x^(x>>16))*0x85EBCA6B)&0xFFFFFFFF
    x=((x^(x>>13))*0xC2B2AE35)&0xFFFFFFFF
    return ((x^(x>>16))&0xFFFFFFFF)/4294967295*2-1

def motion(seed,t,span):
    u=max(0,t)/span; n=math.floor(u); f=u-n
    a,b=noise(seed,n),noise(seed,n+1)
    return a+(b-a)*f*f*(3-2*f)

def demand(w,i,t):
    f=w["feeds"][i]; p=w["parameters"]; t+=f["phase_ms"]
    return [1+p["speed_amplitude"]*motion(f["speed_seed"],t,p["span_ms"]),
            p["height_amplitude"]*motion(f["height_seed"],t,p["span_ms"])]

def initial(w):
    return [dict(u=demand(w,i,0)[0],q=demand(w,i,0)[1],v=demand(w,i,0)[0],y=demand(w,i,0)[1],
                 distance=0.,damage=0.,done=False) for i in range(len(w["feeds"]))]

def step(w,states,t):
    p=w["parameters"]; dt=w["tick_ms"]/1000; tau=p["response_ms"]/1000
    velocities=[s["v"] for s in states]
    for i,s in enumerate(states):
        if s["done"]: continue
        other=velocities[1-i] if len(states)==2 else velocities[i]
        # A compliant shared drive pulls the two running rollers toward one another.
        s["v"]+=(s["u"]-s["v"]+p["coupling"]*(other-s["v"]))*dt/tau
        s["y"]+=(s["q"]-s["y"])*dt/tau
        v,y=demand(w,i,t)
        error=max(0.,abs(s["y"]-y)/p["height_tolerance"]-1,
                  abs(s["v"]-v)/p["speed_tolerance"]-1)
        distance=min(s["v"]*dt,p["stripe_length"]-s["distance"])
        s["damage"]+=distance*min(1.,error)
        s["distance"]+=distance
        s["done"]=s["distance"]>=p["stripe_length"]-1e-9
    return "failed" if any(s["damage"]>w["damage_limit"]+1e-9 for s in states) else "ready" if all(s["done"] for s in states) else "running"

def point_command(w,i,point):
    p=w["feeds"][i]["pad"];x,y=point
    return [max(.4,min(1.6,.4+(x-p["x"])/p["width"]*1.2)),
            max(-1.,min(1.,1-(y-p["y"])/p["height"]*2))]

def command_point(w,i,s):
    p=w["feeds"][i]["pad"]
    return [p["x"]+(s["u"]-.4)/1.2*p["width"],p["y"]+(1-s["q"])/2*p["height"]]

def finite_point(x):
    return isinstance(x,list) and len(x)==2 and all(type(v) in (int,float) and math.isfinite(v) for v in x)

def inside(point,rect):
    return finite_point(point) and rect['x']<=point[0]<=rect['x']+rect['width'] and rect['y']<=point[1]<=rect['y']+rect['height']

def replay(w,events,mode,final):
    states=initial(w);held=None;started=False;t=0;status="staged";submitted=False
    opened=[False]*len(states);hood_hold=None
    action_step=int(w.get("action_step_ms",w["tick_ms"]))
    if action_step<=0 or action_step%w["tick_ms"]:
        raise ValueError("invalid action step")
    previous=0
    for seq,e in enumerate(events,1):
        if not isinstance(e,dict):raise ValueError("event must be an object")
        et=e.get("t_ms")
        if (type(et) is not int or et%w["tick_ms"] or not previous<=et<=final or e.get("seq")!=seq):
            raise ValueError("invalid event order or task-clock tick")
        previous=et
        if not started and et!=0: raise ValueError("staged events must have zero task time")
        kind=e.get("kind");source=e.get("input_source")
        was_running=started and status=="running"
        steer_was_done=False
        if kind=="steer" and type(e.get("feed")) is int and 0<=e["feed"]<len(states):
            steer_was_done=states[e["feed"]]["done"]
        if was_running:
            if kind=="steer":
                terminal_step = action_step > w["tick_ms"] and et == t + w["tick_ms"]
                if et!=t+action_step and not terminal_step:
                    raise ValueError("waiting is not a task action")
                while t<et and status=="running":
                    t+=w["tick_ms"];status=step(w,states,t)
                if terminal_step and status=="running":
                    raise ValueError("steering input must consume a full action step")
            elif et!=t:
                raise ValueError("non-steering input cannot advance task time")
        if status=="failed": raise ValueError("damaged stripe ended this attempt")
        if submitted: raise ValueError("input after certification")
        if kind=="start":
            if started or source!="launch_button":raise ValueError("restart is forbidden")
            started=True;status="running"
            for s in states:s.update(y=s["q"],v=s["u"])
        elif kind in ('inspect','hood_grip','hood_release'):
            i=e.get('feed');point=e.get('point');inspection=w['cam_inspection']
            if type(i) is not int or not 0<=i<len(states) or source!=mode or held is not None:
                raise ValueError('wrong cam inspection surface')
            tab=inspection['tabs'][i]
            if kind=='hood_release':
                if mode!='full' or hood_hold is None or hood_hold[0]!=i or not finite_point(point):
                    raise ValueError('hood release without physical grip')
                if e.get('cancelled',False) not in (True,False):raise ValueError('invalid hood cancellation')
                if not e.get('cancelled',False) and point[1]<=hood_hold[1][1]-inspection['lift_px']:
                    opened[i]=True
                hood_hold=None
            else:
                if opened[i] or hood_hold is not None or not inside(point,tab):raise ValueError('inspection missed closed cam tab')
                if kind=='inspect':
                    if mode!='simplified':raise ValueError('inspection proxy in full mode')
                    opened[i]=True
                else:
                    if mode!='full':raise ValueError('direct hood grip in proxy mode')
                    hood_hold=(i,point)
        elif kind in ("grip","steer","release"):
            i=e.get("feed")
            if type(i) is not int or not 0<=i<len(states) or source!=mode or hood_hold is not None:raise ValueError("wrong control surface")
            if states[i]["done"] and kind!="release" and not (kind=="steer" and not steer_was_done):raise ValueError("control on an accepted card")
            if kind=="grip":
                if mode!="full" or held is not None or not finite_point(e.get("point")):raise ValueError("invalid grip")
                if math.dist(e["point"],command_point(w,i,states[i]))>w["knob_radius"]:raise ValueError("grip missed visible handle")
                held=i
            elif kind=="release":
                if mode!="full" or held!=i:raise ValueError("release without grip")
                held=None
            else:
                if not finite_point(e.get("point")) or (mode=="full" and held!=i):raise ValueError("steer without physical input")
                if mode=="simplified":
                    pad=w["feeds"][i]["pad"];x,y=e["point"]
                    if not pad["x"]<=x<=pad["x"]+pad["width"] or not pad["y"]<=y<=pad["y"]+pad["height"]:raise ValueError("proxy missed control pad")
                states[i]["u"],states[i]["q"]=point_command(w,i,e["point"])
                if not started:states[i].update(v=states[i]["u"],y=states[i]["q"])
        elif kind=="submit":
            if source!="certify_button" or status!="ready":raise ValueError("incomplete or early certification")
            submitted=True
        else:raise ValueError("unknown input")
    if final!=t:
        raise ValueError("final time must be the last action time")
    return dict(states=states,status=status,submitted=submitted,started=started,t_ms=t,cam_opened=opened)

def grade(payload,ground_truth,public_state):
    def fail(s):return dict(graded=True,passed=False,score=0,feedback=s)
    if not isinstance(payload,dict):return fail("reader submission must be an object")
    try:
        for k in ("mechanic_id","task_id","challenge_id","world","control_condition"):
            if ground_truth.get(k)!=public_state.get(k):return fail("public contract mismatch: "+k)
        for k in ("mechanic_id","task_id","challenge_id","control_condition"):
            if payload.get(k)!=ground_truth.get(k):return fail("stale or wrong "+k)
        if ground_truth["mechanic_id"]!=MECHANIC_ID:return fail("wrong mechanic")
        mode=ground_truth["control_condition"]["interaction"]
        if payload.get("interaction_mode")!=mode:return fail("wrong interaction")
        w=ground_truth["world"];final=payload.get("final_t_ms");events=payload.get("events")
        if (type(final) is not int or not 0<=final<=w["duration_ms"] or final%w["tick_ms"] or
            not isinstance(events,list) or not 1<=len(events)<=15000):return fail("invalid transcript")
        r=replay(w,events,mode,final)
        if r["status"]!="ready" or not r["submitted"] or payload.get("completed") is not True:return fail("reader not certified")
        reported=payload.get("feeds")
        if not isinstance(reported,list) or len(reported)!=len(r["states"]):return fail("missing visible outcomes")
        for a,b in zip(reported,r["states"]):
            if not isinstance(a,dict):return fail("visible outcome must be an object")
            for k in ("distance","damage"):
                if type(a.get(k)) not in (int,float) or not math.isfinite(a[k]) or abs(a[k]-b[k])>.00001:return fail("outcome disagrees with replay")
        return dict(graded=True,passed=True,score=100,feedback="All card stripes independently replayed and certified.",
                    metrics=dict(damage=[round(s["damage"],6) for s in r["states"]],task_ms=r["t_ms"]))
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as e:
        return fail("invalid reader transcript: "+str(e))

def cheat(public_state,ground_truth):
    return dict(world=ground_truth.get("world"),planning="privileged geometry only; use HTTP mouse input")
