"""Privileged planning witness using the input transport supplied by the caller.

The simulation helper is only a reproducible implementation diagnostic. It
cannot establish action-space parity or a screenshot-only agent score. The
headless tests supply Playwright, not the downstream native HTTP action API.
"""
from __future__ import annotations

import math

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.facet_lantern_v3 import hit, project, required_edges, score


def aim(world, vertex, t):
    scene = project(world, t)["studs"]
    p = next(p for p in scene if p["id"] == vertex)
    if not p["visible"]:
        return None
    point = [p["x"],p["y"]]
    if hit(world,t,point) != vertex:
        return None
    clearance = min((math.dist(point,[q["x"],q["y"]]) for q in scene if q["visible"] and q["id"]!=vertex),default=1000)
    return point if clearance > 2*world["stud_radius"]+6 else None


def simulation_trace(public, delay_ms=0, step_ms=240, schedule=None):
    """Causal current-state control vs stale coordinates vs another-seed schedule."""
    w = public["world"]
    mode = public["control_condition"]["interaction"]
    events = [dict(seq=1,kind="start",t_ms=0,input_source="launch_button")]
    edges = {tuple(sorted(e)) for e in w["initial_edges"]}
    todo = required_edges(w)-edges
    t = 0
    plans=[]
    def add(kind, when, **kw):
        events.append(dict(seq=len(events)+1,kind=kind,t_ms=when,input_source=mode,**kw))
    inspected=set()
    def inspect(vertex, when, point):
        if vertex is None or vertex in inspected:
            return
        inspected.add(vertex)
        label=next(v["label"] for v in w["vertices"] if v["id"]==vertex)
        events.append(dict(seq=len(events)+1,kind="inspect",t_ms=when,input_source="hover",
                           point=point,hit_id=vertex,label=label))
    if schedule is not None:
        for plan in schedule:
            t = plan["t_ms"]
            a,b = plan["a"],plan["b"]
            i,j = hit(w,t,a),hit(w,t+step_ms,b)
            inspect(i,t,a)
            add("pick",t,point=a,hit_id=i)
            if i is not None:
                inspect(j,t+step_ms,b)
                add("release",t+step_ms,point=b,hit_id=j)
                if j is not None and i!=j and tuple(sorted((i,j))) not in required_edges(w): break
                if j is not None and i!=j:edges.add(tuple(sorted((i,j))))
            t+=step_ms
    else:
        while todo and t+step_ms+delay_ms < w["duration_ms"]:
            candidate=None
            for a,b in sorted(todo):
                x=aim(w,a,t)
                y=aim(w,b,t+step_ms)
                if x is not None and y is not None:
                    candidate=(a,b,x,y);break
            if candidate is None:
                t+=step_ms;continue
            a,b,x,y=candidate
            plans.append(dict(t_ms=t,a=x,b=y,ids=[a,b]))
            i,j=hit(w,t+delay_ms,x),hit(w,t+step_ms+delay_ms,y)
            inspect(i,t+delay_ms,x)
            add("pick",t+delay_ms,point=x,hit_id=i)
            if i is not None:
                inspect(j,t+step_ms+delay_ms,y)
                add("release",t+step_ms+delay_ms,point=y,hit_id=j)
                if j is not None and i!=j:
                    e=tuple(sorted((i,j)))
                    if e not in required_edges(w):break
                    edges.add(e);todo.discard(e)
                elif mode=="simplified" and j is None:
                    events.append(dict(seq=len(events)+1,kind="cancel",t_ms=t+step_ms+delay_ms,input_source="cancel_button"))
            t+=step_ms*2+delay_ms
    final=events[-1]["t_ms"]
    events.append(dict(seq=len(events)+1,kind="submit",t_ms=final,input_source="certify_button"))
    payload={k:public[k] for k in ("mechanic_id","task_id","challenge_id","control_condition")}
    payload.update(events=events,edges=[list(e) for e in sorted(edges)],reported_score=score(w,edges)[0],completed=True,final_t_ms=final)
    return dict(payload=payload,plans=plans)


def click_control(ui, selector):
    p=ui.read(f"(()=>{{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()")
    return ui.send([{"mouse":{"left_click":p}}])


def read_state(ui):
    return ui.read("(()=>{const m=facetLanternV3Model,r=document.querySelector('.fl2-stage').getBoundingClientRect();return {t:m.finalT ?? (m.startedAt===null?0:performance.now()-m.startedAt),selected:m.selected,edges:[...m.edges],terminal:m.terminal,rect:[r.x,r.y,r.width,r.height],clock:GymAnythingRTTime.status()};})()")


def solve(ui, truth, limit=285):
    w=truth["world"];mode=truth["control_condition"]["interaction"]
    plans=[]
    click_control(ui,".fl2-start")
    for _ in range(limit):
        s=read_state(ui)
        if s["terminal"]:raise RuntimeError("lantern ended before certification")
        todo=required_edges(w)-{tuple(e.split("|")) for e in s["edges"]}
        if not todo:
            click_control(ui,".fl2-submit");ui.wait(.15)
            return dict(planning="privileged geometry, seed and read-only page diagnostics; input transport supplied by caller",plans=plans)
        # Live input transport is a short positive delay. Paused inputs land
        # at the existing clock boundary, before their next observation window.
        lead=0 if s["clock"].get("state")=="paused" else 15
        t=s["t"]+lead
        chosen=None
        if s["selected"] is not None:
            a=s["selected"]
            for x,y in sorted(todo):
                b=y if x==a else x if y==a else None
                p=aim(w,b,t) if b else None
                if p is not None:chosen=("release",b,p);break
        else:
            for a,b in sorted(todo):
                p,q=aim(w,a,t),aim(w,b,t+240)
                if p is not None and q is not None:chosen=("pick",a,p);break
        if chosen is None:
            ui.wait(.12);ui.send([]);continue
        kind,vertex,p=chosen;r=s["rect"]
        xy=[r[0]+p[0]/w["width"]*r[2],r[1]+p[1]/w["height"]*r[3]]
        plans.append(dict(task_ms=s["t"],kind=kind,vertex=vertex,local=p,screen=xy))
        if mode=="simplified":ui.send([{"mouse":{"left_click":xy}}])
        elif kind=="pick":ui.send([{"mouse":{"move":xy,"buttons":{"left_down":True}}}])
        else:ui.send([{"mouse":{"move":xy}},{"mouse":{"buttons":{"left_up":True}}}])
        after=read_state(ui)
        # A full miss is safe. Release a held pointer before trying again.
        if mode=="full" and kind=="pick" and after["selected"] is None:
            ui.send([{"mouse":{"buttons":{"left_up":True}}}])
    raise RuntimeError("lantern solver input budget exhausted")
