"""Independent fixed-step ballistic/support replay. Standalone for Pyodide."""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path

MECHANIC_ID="hearthlift_courier_v3_nonrealtime"
REVISION="moving-crate-hops-v2"


def noise(seed, index):
    x=(int(seed)^((int(index)+1)*0x9E3779B9)) & 0xffffffff
    x=((x^(x>>16))*0x85EBCA6B)&0xffffffff
    x=((x^(x>>13))*0xC2B2AE35)&0xffffffff
    return ((x^(x>>16))&0xffffffff)/4294967295*2-1


def center(platform, ms):
    spec=platform["motion"]
    if not spec: return list(platform["center"])
    u=(max(0,ms)+spec["offset_ms"])/spec["span_ms"]
    n=math.floor(u); f=u-n; blend=f*f*f*(10+f*(-15+6*f))
    if "knots" in spec:
        a, b = spec["knots"][n:n+2]
        return [p+scale*(x+(y-x)*blend)
                for p,scale,x,y in zip(platform["center"],spec["amplitude"],a,b)]
    # Read-only compatibility with retained, source-bound historical worlds.
    return [p+a*(noise(spec["seed"]+i*7919,n)+
                  (noise(spec["seed"]+i*7919,n+1)-noise(spec["seed"]+i*7919,n))*blend)
            for i,(p,a) in enumerate(zip(platform["center"],spec["amplitude"]))]


def velocity(platform, ms):
    return [(b-a)*50 for a,b in zip(center(platform,max(0,ms-10)),center(platform,ms+10))]


def chart_point(world, point):
    c=world["chart"]; x,z=point; m=c["margin"]
    return [m+(x-c["x_min"])/(c["x_max"]-c["x_min"])*(c["width"]-2*m),
            m+(z-c["z_min"])/(c["z_max"]-c["z_min"])*(c["height"]-2*m)]


def chart_world(world, point):
    c=world["chart"]; m=c["margin"]; x,z=point
    return [c["x_min"]+(x-m)/(c["width"]-2*m)*(c["x_max"]-c["x_min"]),
            c["z_min"]+(z-m)/(c["height"]-2*m)*(c["z_max"]-c["z_min"])]


class Physics:
    def __init__(self, world):
        self.world=world; self.spec=world["physics"]; self.tick=0
        self.p=list(world["platforms"][0]["center"]); self.v=[0.,0.,0.]
        self.support="quay"; self.offset=[0.,0.]; self.active=False
        self.loaded=False; self.delivered=False; self.failed=""; self.landings=[]
    def platform(self, identity):
        return next(p for p in self.world["platforms"] if p["id"]==identity)
    def start(self):
        if self.active: raise ValueError("lifts already awake")
        self.active=True; self.loaded=True
    def launch(self, aim):
        if not self.active or not self.support or self.failed or self.delivered:
            raise ValueError("hop requires a supported active courier")
        ms=self.tick*10; pv=velocity(self.platform(self.support),ms)
        vx=(aim[0]-self.p[0])/self.spec["aim_seconds"]+pv[0]*self.spec["inherit"]
        vz=(aim[1]-self.p[2])/self.spec["aim_seconds"]+pv[2]*self.spec["inherit"]
        if math.hypot(vx,vz)>self.spec["speed_limit"]+1e-8:
            raise ValueError("aim exceeds the visible jump range")
        self.v=[vx,self.spec["jump_speed"]+pv[1]*self.spec["inherit"],vz]
        self.support=None
        if self.spec.get("timing_mode") == "action_triggered":
            limit=math.floor(self.spec["play_time_ms"]/self.spec["tick_ms"])
            while self.support is None and not self.failed and not self.delivered and self.tick<limit:
                self.advance(self.tick+1, action_phase=True)
    def burn(self):
        if self.delivered:
            return
        if not self.active or self.support!="hearth" or not self.loaded:
            self.failed="The crate was released away from the hearth."
        else:
            self.loaded=False; self.delivered=True
    def advance(self, end_tick, *, action_phase=False):
        if not self.active: return
        if (self.spec.get("timing_mode") == "action_triggered" and
                end_tick != self.tick and not action_phase):
            raise ValueError("task time advances only after a deliberate hop")
        while self.tick<end_tick and not self.failed and not self.delivered:
            t=self.tick*10; self.tick+=1
            if self.support:
                c=center(self.platform(self.support),t+10)
                self.p=[c[0]+self.offset[0],c[1],c[2]+self.offset[1]]
                self.v=velocity(self.platform(self.support),t+10)
            else:
                before=list(self.p); self.v[1]-=self.spec["gravity"]*.01
                after=[p+v*.01 for p,v in zip(before,self.v)]
                contacts=[]
                for platform in self.world["platforms"]:
                    old=center(platform,t); new=center(platform,t+10)
                    d0=before[1]-old[1]; d1=after[1]-new[1]
                    if d0>=-1e-9 and d1<=0 and d1<d0:
                        f=d0/(d0-d1); p=[a+(b-a)*f for a,b in zip(before,after)]
                        c=[a+(b-a)*f for a,b in zip(old,new)]
                        if (abs(p[0]-c[0])+self.spec["radius"]<=platform["half"][0]+1e-9
                            and abs(p[2]-c[2])+self.spec["radius"]<=platform["half"][1]+1e-9):
                            contacts.append((f,platform["id"],p,c))
                if contacts:
                    _,identity,p,c=min(contacts)
                    self.offset=[p[0]-c[0],p[2]-c[2]]; self.support=identity
                    c=center(self.platform(identity),t+10)
                    after=[c[0]+self.offset[0],c[1],c[2]+self.offset[1]]
                    self.v=velocity(self.platform(identity),t+10)
                    self.landings.append(dict(tick=self.tick,platform=identity))
                self.p=after
            if self.p[1]<self.spec["fall_y"]:
                self.failed="Courier and crate fell into the ravine."
            if self.tick*10>=self.spec["play_time_ms"]:
                self.failed="The delivery shift ended."
    def snapshot(self):
        return dict(tick=self.tick,position=list(self.p),velocity=list(self.v),support=self.support,
                    loaded=self.loaded,delivered=self.delivered,failed=self.failed,landings=copy.deepcopy(self.landings))


def _number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError("non-finite coordinate")
    return float(value)


def _point(world, value):
    c=world["chart"]
    if not isinstance(value,list) or len(value)!=2: raise ValueError("invalid chart point")
    x,z=map(_number,value)
    if not 0<=x<=c["width"] or not 0<=z<=c["height"]:
        raise ValueError("point outside chart")
    return [x,z]


def grade(payload, truth, public):
    def fail(message): return dict(graded=True,passed=False,score=0,feedback=message)
    try:
        if not all(isinstance(x,dict) for x in (payload,truth,public)): return fail("invalid payload")
        for state in (truth, public, payload):
            if type(state.get("episode_failed", False)) is not bool:
                return fail("invalid episode status")
        if truth.get("episode_failed", False) != public.get("episode_failed", False):
            return fail("public episode status differs")
        if any(state.get("episode_failed", False) for state in (truth, public, payload)):
            return fail("A failed submission already ended this episode.")
        # The target runtime hook exports the established state-directory
        # setting. Offline/Pyodide replays remain standalone when it is absent.
        # A server cannot accept a cached clean challenge after another page
        # already ended the same episode; client flags cannot clear this check.
        directory = os.environ.get("GYM_ANYTHING_RT_STATE_DIR")
        if directory:
            try:
                with (Path(directory) / "attempts.jsonl").open(encoding="utf-8") as journal:
                    if any(line.strip() for line in journal):
                        return fail("A failed submission already ended this episode.")
            except FileNotFoundError:
                pass
            except (OSError, UnicodeError):
                return fail("Episode failure history is unavailable.")
        for k in ("mechanic_id","task_id","challenge_id","control_condition","world","inspection_revision"):
            if truth.get(k)!=public.get(k): return fail("public replay contract differs: "+k)
        for k in ("mechanic_id","task_id","challenge_id","control_condition"):
            if not truth.get(k) or payload.get(k)!=truth[k]: return fail("wrong or stale "+k)
        if (truth["mechanic_id"]!=MECHANIC_ID or payload.get("physics_revision")!=REVISION or
            truth.get("inspection_revision")!="retained-lift-surveys-v3" or
            truth["world"]["physics"].get("timing_mode") != "action_triggered"):
            return fail("wrong mechanic revision")
        mode=truth["control_condition"]["interaction"]
        if mode not in ("full","simplified") or payload.get("interaction_mode")!=mode:
            return fail("wrong input surface")
        events=payload.get("events")
        if not isinstance(events,list) or not 1<=len(events)<=1200: return fail("missing or excessive trace")
        sim=Physics(truth["world"]); selection=None; previous=0; submitted=False; start_seen=False
        for seq,event in enumerate(events,1):
            if not isinstance(event,dict) or type(event.get("tick")) is not int or event.get("seq")!=seq:
                return fail("invalid event sequence")
            tick=event["tick"]
            if not previous<=tick<=24000 or submitted: return fail("invalid action time or event after submit")
            previous=tick; sim.advance(tick)
            if sim.failed: return fail(sim.failed)
            kind=event.get("kind"); source=event.get("input_source")
            if kind=="start":
                if source!="start_button" or tick!=0 or start_seen: return fail("invalid start")
                sim.start(); start_seen=True
            elif kind=="inspect":
                if source!="lift_inspection" or selection or sim.delivered:
                    return fail("invalid lift inspection")
                platform=sim.platform(event.get("platform"))
                if not platform["motion"]: return fail("no motor survey on the quay")
                point=_point(sim.world,event.get("point"))
                c=center(platform,tick*10)
                a=chart_point(sim.world,[c[0]-platform["half"][0],c[2]-platform["half"][1]])
                b=chart_point(sim.world,[c[0]+platform["half"][0],c[2]+platform["half"][1]])
                if not all(lo-6<=x<=hi+6 for x,lo,hi in zip(point,a,b)):
                    return fail("inspection missed visible lift top")
                samples=event.get("forecast")
                if not isinstance(samples,list) or len(samples)!=17:
                    return fail("missing motor survey")
                for index,sample in enumerate(samples):
                    if (not isinstance(sample,list) or len(sample)!=3 or
                        math.dist([_number(x) for x in sample],center(platform,tick*10+index*200))>1e-7):
                        return fail("motor survey disagrees with live rail")
            elif kind in ("aim_start","select"):
                expected="courier_drag" if mode=="full" else "chart_click"
                if kind!=("aim_start" if mode=="full" else "select") or source!=expected or selection is not None or not sim.active or not sim.support or sim.delivered:
                    return fail("invalid courier selection or wrong interaction")
                point=_point(sim.world,event.get("point")); pos=chart_point(sim.world,[sim.p[0],sim.p[2]])
                if math.dist(point,pos)>16.01: return fail("selection missed visible courier")
                selection=mode
            elif kind in ("launch","cancel"):
                if selection!=mode or source!=("courier_drag" if mode=="full" else "chart_click"):
                    return fail("launch lacks matching input gesture")
                selection=None
                if kind=="launch": sim.launch(chart_world(sim.world,_point(sim.world,event.get("point"))))
            elif kind=="burn":
                if source!=("keyboard_e" if mode=="full" else "burn_button") or selection:
                    return fail("wrong crate release input")
                sim.burn()
                if sim.failed: return fail(sim.failed)
            elif kind=="seal":
                if source!="certify_button" or selection: return fail("invalid certification")
                submitted=True
            else: return fail("unknown action or reset")
        final=payload.get("final_state")
        if not isinstance(final,dict): return fail("missing final state")
        expected=sim.snapshot()
        for k in ("tick","support","loaded","delivered","failed","landings"):
            if final.get(k)!=expected[k]: return fail("final "+k+" disagrees with replay")
        for k in ("position","velocity"):
            reported=final.get(k)
            if not isinstance(reported,list) or len(reported)!=3 or math.dist([_number(x) for x in reported],expected[k])>1e-5:
                return fail("final "+k+" disagrees with replay")
        passed=submitted and start_seen and sim.delivered and not sim.failed and payload.get("completed") is True
        return dict(graded=True,passed=passed,score=100 if passed else 0,
                    feedback="Moving-support ballistic replay delivered the ember crate." if passed else "Delivery incomplete.")
    except (KeyError,TypeError,ValueError,OverflowError,StopIteration) as exc:
        return fail("invalid courier replay: "+str(exc))


def cheat(public_state,ground_truth):
    return dict(challenge_id=ground_truth.get("challenge_id"),answers=[],note="Use privileged geometry for planning only.")
