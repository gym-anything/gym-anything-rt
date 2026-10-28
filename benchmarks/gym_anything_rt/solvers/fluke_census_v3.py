"""Privileged geometric planner using the caller's mouse/keyboard input API.

V3 headless Playwright checks are implementation evidence. Native action-API
equivalence requires its own execution evidence and is not established here.
No read expression below mutates a page or dispatches an input.
"""
from __future__ import annotations

import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.fluke_census_v3 import (
    Camera, framed, inside, landmarks, polygon, pose, transform,
)

MECHANIC_ID="fluke_census_v3"


def rectangle(ui,selector):
    return ui.read(f'(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; }})()')


def center(rect):return [rect[0]+rect[2]/2,rect[1]+rect[3]/2]


def click(point):return {"mouse":{"left_click":point}}


def drag(start,end):
    # Release uses its actual endpoint, including when intermediate moves coalesce.
    return [{"mouse":{"move":start,"buttons":{"left_down":True}}},
            {"mouse":{"move":end}}, {"mouse":{"buttons":{"left_up":True}}}]


def snapshot(ui):
    return ui.read('({ms:flukeCensusV3Model.ms,point:flukeCensusV3Model.camera.point,velocity:flukeCensusV3Model.camera.velocity,target:flukeCensusV3Model.camera.target,archived:flukeCensusV3Model.archived,shot:flukeCensusV3Model.shot,terminal:flukeCensusV3Model.terminal,events:flukeCensusV3Model.events.length})')


def aim_point(world, animal, ms):
    """Choose an interior crosshair that balances the whole rotated silhouette."""
    poly=polygon(animal,ms); c=world['camera']
    low=[max(p[i] for p in poly)-c[k]/2 for i,k in enumerate(('width','height'))]
    high=[min(p[i] for p in poly)+c[k]/2 for i,k in enumerate(('width','height'))]
    if any(a>b for a,b in zip(low,high)):return None
    middle=[(a+b)/2 for a,b in zip(low,high)]
    interior=transform([[0,18]],pose(animal,ms))[0]
    points=[interior,middle,[max(a,min(b,v)) for a,b,v in zip(low,high,interior)]]
    points += [[low[0]+(high[0]-low[0])*x,low[1]+(high[1]-low[1])*y]
               for x,y in ((.5,.75),(.25,.5),(.75,.5),(.5,.25),(.25,.75),(.75,.75))]
    for point in points:
        if inside(point,poly) and framed(world,point,ms)[0]==animal['id']:
            return point
    return None


def solve(ui,truth,after_shot=None,after_inspection=None,read_inspection=None):
    """Plan camera geometry privately; choose photographs from query feedback.

    read_inspection receives no species/ground truth and returns wanted,
    off_list or unclear. Evidence checks supply a reader of screenshot pixels.
    The default reads the same visible response text for solver diagnostics.
    """
    world=truth["world"]; mode=(truth.get("control_condition") or {}).get("interaction","full")
    sea=rectangle(ui,'#fc2-sea'); photo=rectangle(ui,'#fc2-photo')
    archive=center(rectangle(ui,'#fc2-archive')); submit=center(rectangle(ui,'#fc2-submit'))
    pins={k:center(rectangle(ui,f'[data-pin="{k}"]')) for k in ('a','v','b')}
    shutter=center(rectangle(ui,'#fc2-shutter')) if mode=='simplified' else None
    def sea_point(p):return [sea[0]+p[0]*sea[2]/860,sea[1]+p[1]*sea[3]/460]
    def photo_point(p):return [photo[0]+p[0]*photo[2]/world['camera']['width'],photo[1]+p[1]*photo[3]/world['camera']['height']]
    by_id={a['id']:a for a in world['animals']}
    window_ms=int(getattr(ui,'observation_window_ms',0))
    aim_horizon=max(260,window_ms)
    shutter_margin=(40,80) if not window_ms else ()
    # The oracle can plan from privileged seeded trajectories. Reserve
    # scarce clear windows before common ones, while every move and observation
    # still goes through the caller's unchanged input interface. This schedule
    # is not available to a screenshot-only player or used as model evidence.
    opportunities={}
    for identity in by_id:
        opportunities[identity]=[(ms,p) for ms in range(600,60001,600)
            if (p:=aim_point(world,by_id[identity],ms)) is not None]
    deadline=time.monotonic()+220
    chosen=None
    last_plan=None
    decisions={}
    required_count=len(truth['required_ids'])  # Also displayed by the census counter.
    def visible_decision():
        if read_inspection:return read_inspection()
        label=ui.read('document.querySelector("#fc3-inspection-result").textContent')
        return 'wanted' if '/ WANTED' in label else 'off_list' if '/ OFF LIST' in label else 'unclear'
    while time.monotonic()<deadline:
        s=snapshot(ui)
        if s['terminal']:raise AssertionError('Census ended before completion: '+str(s))
        remaining=set(by_id)-set(s['archived'])-{identity for identity,decision in decisions.items() if decision=='off_list'}
        if len(s['archived'])==required_count:
            ui.send([click(submit)]);return
        if s['shot']:
            shot=s['shot']; marks=landmarks(by_id[shot['id']],shot['ms'])
            positions=[[x-shot['camera'][0]+world['camera']['width']/2,y-shot['camera'][1]+world['camera']['height']/2] for x,y in marks]
            if after_shot:after_shot(shot)
            for pin,p in zip(('a','v','b'),positions):
                actions=drag(pins[pin],photo_point(p)) if mode=='full' else [click(pins[pin]),click(photo_point(p))]
                ui.send(actions)
                if not window_ms:ui.wait(.05)
            ui.send([click(archive)])
            if not window_ms:ui.wait(.10)
            chosen=None;last_plan=None;continue
        planned=None
        if s['ms']<60000:
            feasible=[]
            for identity in remaining:
                future=[(ms,p) for ms,p in opportunities[identity] if ms>s['ms']]
                for ms,p in future:
                    c=Camera(world);c.ms=s['ms'];c.point=list(s['point']);c.velocity=list(s['velocity']);c.target=c.clamp(p)
                    c.advance(ms)
                    if framed(world,c.point,ms)[0]==identity:
                        feasible.append((len(future),ms,identity,p));break
            if feasible:
                _,_,chosen,target=min(feasible)
                planned=(chosen,target)
        # Choose a clear fluke with feasible framing now and shortly ahead.
        candidates=[]
        for identity in remaining:
            a=by_id[identity]
            target=aim_point(world,a,s['ms']+aim_horizon)
            if target is not None:
                candidates.append((math.dist(target,s['point']),identity,target))
        # Refresh after candidate search. Accept a shutter only while the same
        # clear silhouette remains framed throughout the read-to-input margin.
        # Planning is privileged; execution remains a literal public input.
        fresh=snapshot(ui)
        current_id=framed(world,fresh['point'],fresh['ms'])[0]
        c=Camera(world);c.ms=fresh['ms'];c.point=fresh['point'];c.target=fresh['target'];c.velocity=fresh['velocity']
        stable=current_id in remaining and (not planned or current_id==chosen)
        for dt in shutter_margin:
            c.advance(fresh['ms']+dt)
            if framed(world,c.point,fresh['ms']+dt)[0]!=current_id:
                stable=False;break
        if stable:
            if current_id not in decisions:
                ui.send([click(center(photo))])
                decision=visible_decision()
                # Geometry diagnostics bind the screenshot response to the
                # specimen actually sampled, rather than a stale aim target.
                sample=ui.read('flukeCensusV3Model.events.filter(e=>e.kind==="inspect").at(-1)')
                if sample and sample['animal_id'] and decision in ('wanted','off_list'):
                    decisions[sample['animal_id']]=decision
                    if after_inspection:after_inspection(sample['animal_id'])
                # The query/screenshot does not stop the sea. Recheck geometry
                # on the next iteration before committing a photograph.
                continue
            if decisions[current_id]!='wanted':continue
            ui.send([{"keyboard":{"keys":["Space"]}}] if mode=='full' else [click(shutter)])
            if not window_ms:ui.wait(.10)
            continue
        if planned:
            s=snapshot(ui)
            # Native coordinates are integer pixels, and an inertial full-mode
            # grab can acquire a small pointer offset during HTTP delivery.
            # Repeating an identical destination cannot remove that offset.
            # Wait for the issued plan, then judge the actual framing before
            # the shutter. A materially changed plan still needs new input.
            same_plan=last_plan is not None and last_plan[0]==planned[0] and math.dist(last_plan[1],planned[1])<.5
            if not window_ms and same_plan and math.dist(s['target'],planned[1])<=8:
                ui.wait(.06)
            else:
                ui.send(drag(sea_point(s['point']),sea_point(planned[1])) if mode=='full' else [click(sea_point(planned[1]))])
                last_plan=(planned[0],list(planned[1]))
            continue
        if not candidates:
            ui.wait(.10);continue
        selected=next((row for row in candidates if row[1]==chosen),None) or min(candidates)
        _,chosen,target=selected
        # The camera continues moving during geometric planning. Start a full
        # drag on its actual current center so its pointer offset is zero.
        s=snapshot(ui)
        target=aim_point(world,by_id[chosen],s['ms']+aim_horizon)
        if target is None:
            chosen=None;ui.wait(.10);continue
        target=Camera(world).clamp(target)
        ui.send(drag(sea_point(s['point']),sea_point(target)) if mode=='full' else [click(sea_point(target))])
        # A paused API response has already advanced its observation window.
        # Asking for another empty observation here would skip a second window
        # and spend another request before inspecting the resulting frame.
        if not window_ms:ui.wait(.36)
    raise AssertionError('Moving census oracle exhausted its finite time budget.')
