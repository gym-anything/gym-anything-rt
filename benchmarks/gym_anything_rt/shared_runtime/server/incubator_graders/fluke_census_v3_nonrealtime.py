"""Independent replay of camera inertia, fluke geometry and landmark annotation.

Standalone standard-library module, also executed unchanged by Pyodide.
"""
from __future__ import annotations

import math

MECHANIC_ID = "fluke_census_v3_nonrealtime"
TIMING_MODE = "action_stepped"


def outline(animal):
    """The two outer tips and central V belong to the rendered polygon."""
    notch_y = 3 + animal["species"] * 5
    points = [[-58,-28]]
    for side in range(2):
        a, b = ([-58,-28], [0,notch_y]) if side == 0 else ([0,notch_y], [58,-28])
        for i in range(3):
            for f, depth in ((.18,0), (.48,animal["notches"][side*3+i]), (.78,0)):
                u=(i+f)/3
                points.append([a[0]+(b[0]-a[0])*u, a[1]+(b[1]-a[1])*u+depth])
        points.append(b)
    return points + [[52,4],[38,26],[14,38],[0,31],[-14,38],[-38,26],[-52,4]]


def pose(animal, ms):
    s=animal["motion"]; p=s["phase"]; u=ms/1000*s["rate"]
    return [s["cx"]+s["ax"]*math.sin(u+p[0])+s["bx"]*math.sin(u*math.sqrt(2)+p[1]),
            s["cy"]+s["ay"]*math.sin(u*math.sqrt(.7)+p[2])+s["by"]*math.sin(u*math.sqrt(3)+p[3]),
            s["base_angle"]+s["turn"]*math.sin(u*math.sqrt(1.3)+p[4]), animal["scale"]]


def transform(points, p):
    x,y,a,s=p; c=math.cos(a); sn=math.sin(a)
    return [[x+s*(u*c-v*sn),y+s*(u*sn+v*c)] for u,v in points]


def polygon(animal, ms):
    return transform(outline(animal),pose(animal,ms))


def landmarks(animal, ms):
    return transform([[-58,-28],[0,3+animal["species"]*5],[58,-28]],pose(animal,ms))


def inside(point, poly):
    x,y=point; hit=False
    for i,(ax,ay) in enumerate(poly):
        bx,by=poly[i-1]
        if (ay>y)!=(by>y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            hit=not hit
    return hit


def overlaps(a,b):
    if any(inside(p,b) for p in a) or any(inside(p,a) for p in b):
        return True
    def cross(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    for i,p in enumerate(a):
        q=a[i-1]
        for j,r in enumerate(b):
            s=b[j-1]
            if cross(p,q,r)*cross(p,q,s)<0 and cross(r,s,p)*cross(r,s,q)<0:
                return True
    return False


def framed(world, camera, ms):
    """Crosshair selects the visibly frontmost fluke; all of it must fit."""
    polys=[polygon(a,ms) for a in world["animals"]]
    target=next((i for i in range(len(polys)-1,-1,-1) if inside(camera,polys[i])),None)
    if target is None:return None,"The crosshair missed a fluke."
    cam=world["camera"]; x,y=camera; poly=polys[target]
    if any(abs(px-x)>cam["width"]/2+1e-6 or abs(py-y)>cam["height"]/2+1e-6 for px,py in poly):
        return None,"A fluke edge was clipped by the frame."
    if any(overlaps(poly,p) for i,p in enumerate(polys) if i>target):
        return None,"Another fluke covered the photograph."
    # Earlier flukes are behind the selected silhouette, so cannot occlude it.
    return world["animals"][target]["id"],""


def inspected(world, camera, ms, point):
    """Identify only the whole, clear specimen clicked in the live camera.

    A rejected sample is harmless. No sample count gates a valid census.
    """
    c=world["camera"]
    sample=[point[0]+camera[0]-c["width"]/2, point[1]+camera[1]-c["height"]/2]
    polys=[polygon(a,ms) for a in world["animals"]]
    target=next((i for i in range(len(polys)-1,-1,-1) if inside(sample,polys[i])),None)
    if target is None:return None
    if any(abs(x-camera[0])>c["width"]/2+1e-6 or abs(y-camera[1])>c["height"]/2+1e-6 for x,y in polys[target]):return None
    if any(overlaps(polys[target],p) for i,p in enumerate(polys) if i>target):return None
    return world["animals"][target]


class Camera:
    def __init__(self,world):
        self.world=world; self.ms=0
        self.point=list(world["camera"]["initial"]); self.target=self.point.copy(); self.velocity=[0.,0.]

    def clamp(self,point):
        c=self.world["camera"]; st=self.world["stage"]
        return [max(c["width"]/2,min(st["width"]-c["width"]/2,point[0])),
                max(c["height"]/2,min(st["height"]-c["height"]/2,point[1]))]

    def advance(self,ms):
        c=self.world["camera"]
        while self.ms+10<=ms:
            self.ms+=10
            acceleration=[(self.target[i]-self.point[i])*64-self.velocity[i]*16 for i in range(2)]
            mag=math.hypot(*acceleration)
            if mag>c["acceleration"]:acceleration=[v*c["acceleration"]/mag for v in acceleration]
            self.velocity=[v+a*.01 for v,a in zip(self.velocity,acceleration)]
            mag=math.hypot(*self.velocity)
            if mag>c["speed"]:self.velocity=[v*c["speed"]/mag for v in self.velocity]
            raw=[x+v*.01 for x,v in zip(self.point,self.velocity)]
            self.point=self.clamp(raw)
            for i in range(2):
                if raw[i]!=self.point[i]:self.velocity[i]=0


def annotation_valid(world, animal, ms, camera, marks):
    if any(k not in marks for k in ("a","v","b")):return False
    c=world["camera"]; x,y=camera
    expected=[[px-x+c["width"]/2,py-y+c["height"]/2] for px,py in landmarks(animal,ms)]
    tol=world["parameters"]["landmark_tolerance"]
    tips=(math.dist(marks["a"],expected[0])<=tol and math.dist(marks["b"],expected[2])<=tol or
          math.dist(marks["a"],expected[2])<=tol and math.dist(marks["b"],expected[0])<=tol)
    return bool(tips and math.dist(marks["v"],expected[1])<=tol)


def grade(payload,truth,public):
    def fail(message):return dict(graded=True,passed=False,score=0,feedback=message)
    if not all(isinstance(v,dict) for v in (payload,truth,public)):return fail("Malformed census.")
    for k in ("mechanic_id","task_id","challenge_id","control_condition"):
        if public.get(k)!=truth.get(k) or payload.get(k)!=truth.get(k):return fail("Stale task or condition.")
    if truth.get("mechanic_id")!=MECHANIC_ID or not truth.get("challenge_id"):return fail("Wrong mechanic.")
    world=truth.get("world")
    if not isinstance(world,dict) or any(public.get(k)!=v for k,v in world.items()):return fail("World differs from replay.")
    if world.get("timing_mode") != TIMING_MODE:
        return fail("Wrong timing mode.")
    phase_step=world.get("phase_step_ms")
    phase_max=world.get("phase_max_ms")
    if type(phase_step) is not int or phase_step <= 0 or type(phase_max) is not int or phase_max < phase_step:
        return fail("Malformed action-stepped timing.")
    mode=(truth.get("control_condition") or {}).get("interaction","full")
    if mode not in ("full","simplified") or payload.get("interaction_mode")!=mode:return fail("Wrong interaction.")
    events=payload.get("events")
    if not isinstance(events,list) or not 1<=len(events)<=30000:return fail("Missing or oversized transcript.")
    cam=Camera(world); animals={a["id"]:a for a in world["animals"]}
    previous=0; drag=None; pin=None; selected="a"; shot=None; marks={}; archived=[]; closed=False
    phase_ms=0
    def point(e,width,height):
        p=e.get("point")
        if not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p):raise ValueError("Malformed point.")
        if not (0<=p[0]<=width and 0<=p[1]<=height):raise ValueError("Point outside visible surface.")
        return p
    try:
        for seq,e in enumerate(events,1):
            if not isinstance(e,dict) or e.get("seq")!=seq or closed:return fail("Input after terminal census or wrong sequence.")
            ms=e.get("t_ms"); kind=e.get("kind"); source=e.get("source")
            if type(ms) is not int or not previous<=ms<=world["play_time_ms"] or ms%10:return fail("Invalid task time.")
            previous=ms; cam.advance(ms)
            if ms>=world["play_time_ms"]:return fail("The survey expired.")
            if kind in ("aim_start","aim_move","aim_end","aim_click"):
                if shot or pin:return fail("Camera unavailable during photograph annotation.")
                p=point(e,world["stage"]["width"],world["stage"]["height"])
                if source!=("frame_drag" if mode=="full" else "aim_click"):return fail("Wrong aiming surface.")
                if kind=="aim_click":
                    if mode!="simplified" or drag:return fail("Wrong aiming gesture.")
                    cam.target=cam.clamp(p)
                    phase_ms=min(phase_max,phase_ms+phase_step)
                elif mode!="full":return fail("Drag requires full interaction.")
                elif kind=="aim_start":
                    if drag or abs(p[0]-cam.point[0])>world["camera"]["width"]/2 or abs(p[1]-cam.point[1])>world["camera"]["height"]/2:return fail("Drag did not start on the frame.")
                    drag=[p[i]-cam.point[i] for i in range(2)]
                elif drag is None:return fail("No active frame drag.")
                else:
                    cam.target=cam.clamp([p[i]-drag[i] for i in range(2)])
                    if kind=="aim_end":
                        drag=None
                        phase_ms=min(phase_max,phase_ms+phase_step)
            elif kind=="inspect":
                if source!="camera_click" or shot or pin or drag is not None:return fail("Wrong inspection surface or active photograph/drag.")
                sample=inspected(world,cam.point,phase_ms,point(e,world["camera"]["width"],world["camera"]["height"]))
                identity=sample["id"] if sample else None
                name=world["field_key"]["species_names"][sample["species"]] if sample else None
                listed=sample["species"] in world["listed_species"] if sample else None
                if e.get("animal_id")!=identity or e.get("species_name")!=name or e.get("listed") is not listed:return fail("Inspection feedback differs from visible geometry.")
            elif kind=="shutter":
                if source!=("space" if mode=="full" else "shutter_button") or shot or pin or drag is not None:return fail("Wrong shutter surface or active photograph/drag.")
                identity,error=framed(world,cam.point,phase_ms)
                if error:return fail(error)
                if identity in archived:return fail("A duplicate individual ended the census.")
                if identity not in truth["required_ids"]:return fail("An off-list individual ended the census.")
                if e.get("animal_id")!=identity:return fail("Photograph identity differs from geometry.")
                shot=dict(id=identity,phase_ms=phase_ms,camera=cam.point.copy()); marks={}; selected="a"
            elif kind=="pin_start":
                if mode!="full" or source!="pin_drag" or not shot or pin or e.get("pin") not in ("a","v","b"):return fail("Wrong landmark drag.")
                pin=e["pin"]
            elif kind=="pin_end":
                if mode!="full" or source!="pin_drag" or not shot or pin is None or e.get("pin")!=pin:return fail("No held landmark pin.")
                marks[pin]=point(e,world["camera"]["width"],world["camera"]["height"]);pin=None
            elif kind=="pin_cancel":
                if mode!="full" or source!="pin_drag" or pin is None:return fail("No landmark drag to cancel.")
                pin=None
            elif kind=="tool":
                if mode!="simplified" or source!="tool_button" or not shot or e.get("pin") not in ("a","v","b"):return fail("Wrong landmark tool.")
                selected=e["pin"]
            elif kind=="mark":
                if mode!="simplified" or source!="photo_click" or not shot or e.get("pin")!=selected:return fail("Wrong annotation surface.")
                marks[selected]=point(e,world["camera"]["width"],world["camera"]["height"])
            elif kind=="archive":
                if source!="archive_button" or not shot or pin:return fail("No photograph to archive.")
                valid=annotation_valid(world,animals[shot["id"]],shot["phase_ms"],shot["camera"],marks)
                if e.get("accepted") is not valid:return fail("Annotation feedback differs from replay.")
                if valid:archived.append(shot["id"]);shot=None;marks={}
            elif kind=="submit":
                if source!="census_button":return fail("Wrong census control.")
                closed=True
            elif kind=="failure":return fail("The attempt ended in visible failure.")
            else:return fail("Unknown control; resets are unavailable.")
        passed=closed and shot is None and pin is None and drag is None and set(archived)==set(truth["required_ids"])
        return dict(graded=True,passed=passed,score=100 if passed else 0,coverage=len(archived),required=len(truth["required_ids"]),
                    feedback=f"Census replay: {len(archived)}/{len(truth['required_ids'])} distinct listed individuals, complete flukes and landmarks.")
    except (KeyError,TypeError,ValueError,IndexError,OverflowError) as exc:return fail("Malformed census: "+str(exc))
