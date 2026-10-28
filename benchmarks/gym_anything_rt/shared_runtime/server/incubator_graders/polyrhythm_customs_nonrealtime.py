"""Standalone Python replay, also shipped unchanged to the Pyodide verifier."""
from __future__ import annotations

import math

MECHANIC_ID = "polyrhythm_customs_nonrealtime"
REVISION = "circulating-score-v2"


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xffffffff
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0,ms)/span
    n = math.floor(u)
    f = u-n
    a,b = noise(seed,n),noise(seed,n+1)
    return a+(b-a)*f*f*(3-2*f)


def integral(seed, ms, span):
    u = max(0,ms)/span
    n = math.floor(u)
    f = u-n
    a,b = noise(seed,n),noise(seed,n+1)
    return span*(sum((noise(seed,i)+noise(seed,i+1))/2 for i in range(n))
                 + a*f+(b-a)*(f**3-f**4/2))


def circumference(world):
    r = world["rail"]
    return 2*(r["right"]-r["left"])+2*math.pi*r["radius"]


def travel(world, lane, ms):
    p = world["parameters"]
    offset = lane["offset_ms"]
    variation = integral(lane["speed_seed"],ms+offset,p["speed_span_ms"])-integral(lane["speed_seed"],offset,p["speed_span_ms"])
    return p["speed"]*(ms+p["speed_variation"]*variation)/1000


def gate(world, lane, ms):
    p = world["parameters"]
    return world["rail"]["right"]-world["rail"]["gate_x"]-p["gate_drift"]*motion(lane["gate_seed"],ms+lane["offset_ms"],p["gate_span_ms"])


def phase(world, note, ms):
    lane = next(l for l in world["lanes"] if l["id"] == note["lane"])
    return note["phase"]+travel(world,lane,ms)


def decision_candidates(replay, ms):
    half = replay.world["parameters"]["band_half_width"]
    c = circumference(replay.world)
    return [n for n in replay.notes.values()
            if n["id"] not in replay.cleared and n["lane"] not in replay.held
            and abs(phase(replay.world, n, ms) % c
                    - gate(replay.world, replay.lanes[n["lane"]], ms)) <= half + 1e-7]


def next_decision(replay, after_ms):
    if decision_candidates(replay, after_ms):
        return after_ms
    limit = replay.world["run_limit_ms"]
    for ms in range(math.floor(after_ms) + 1, limit + 1):
        if decision_candidates(replay, ms):
            return ms
    return None


def release_time(replay, note):
    half = replay.world["parameters"]["band_half_width"]
    cycle = replay.held[note["lane"]]["cycle"]
    lane = replay.lanes[note["lane"]]
    limit = min(replay.world["run_limit_ms"], int(replay.ms) + 10000)
    for ms in range(math.floor(replay.ms) + 1, limit + 1):
        if abs(phase(replay.world, note, ms) - note["length"] - cycle * circumference(replay.world)
               - gate(replay.world, lane, ms)) <= half + 1e-7:
            return ms
    return None


def rail_point(world, phase_value, lane_y):
    """True closed stadium path: left-going inbound, then right-going return."""
    r = world["rail"]
    length, radius = r["right"]-r["left"],r["radius"]
    s = phase_value%circumference(world)
    if s <= length:
        return [r["right"]-s,lane_y]
    if s <= length+math.pi*radius:
        angle = (s-length)/radius
        return [r["left"]-radius*math.sin(angle),lane_y+radius-radius*math.cos(angle)]
    if s <= 2*length+math.pi*radius:
        return [r["left"]+s-length-math.pi*radius,lane_y+2*radius]
    angle = (s-2*length-math.pi*radius)/radius
    return [r["right"]+radius*math.sin(angle),lane_y+radius+radius*math.cos(angle)]


class Replay:
    def __init__(self, world):
        self.world = world
        self.notes = {n["id"]:n for n in world["notes"]}
        self.lanes = {l["id"]:l for l in world["lanes"]}
        self.held = {}
        self.cleared = set()
        self.ms = 0.
        self.failed = ""
        self.started = False
        self.missed = 0
        self.missed_notes = {}
        c = circumference(world)
        self.c = c
        half = world["parameters"]["band_half_width"]
        self.next_pass = {n["id"]: math.ceil((n["phase"]-gate(world,self.lanes[n["lane"]],0)-half)/c)
                          for n in world["notes"]}

    def advance(self, ms, enforce_held=True, count_misses=True):
        self.ms = ms
        if self.failed:
            return
        half = self.world["parameters"]["band_half_width"]
        c = circumference(self.world)
        for lane_id, held in self.held.items():
            if enforce_held and held["kind"] == "hold":
                n = self.notes[held["note"]]
                tail = phase(self.world,n,ms)-n["length"]
                # Relative travel is strictly increasing, so checking the endpoint
                # cannot miss a transient torn-ribbon failure during a host stall.
                if tail > held["cycle"]*c+gate(self.world,self.lanes[lane_id],ms)+half+1e-7:
                    self.failed = "A held ribbon passed the release band."
                    return
        for note in self.notes.values():
            if note["id"] in self.cleared or self.held.get(note["lane"],{}).get("note") == note["id"]:
                continue
            head = phase(self.world,note,ms)
            center = gate(self.world,self.lanes[note["lane"]],ms)
            while head > self.next_pass[note["id"]]*c+center+half+1e-7:
                self.next_pass[note["id"]] += 1
                self.missed += 1
                if count_misses:
                    self.missed_notes[note["id"]] = self.missed_notes.get(note["id"],0)+1
                    if self.missed > self.world["parameters"]["miss_allowance"]:
                        self.failed = "Too many missed passes."
                        return
                else:
                    self.missed -= 1

    def settle_start(self):
        target = next_decision(self, 0)
        if target is None:
            self.failed = "The inspection shift ended."
        else:
            self.advance(target, enforce_held=False, count_misses=False)

    def settle_after_action(self, kind, lane_id):
        if self.failed:
            return
        if len(self.cleared) == len(self.notes) and not self.held:
            return
        target = self.ms
        held = self.held.get(lane_id)
        if kind == "down" and held and held["kind"] == "hold":
            target = release_time(self, self.notes[held["note"]])
            if target is None:
                self.failed = "The inspection shift ended."
                return
        elif kind == "down":
            # A tap remains held until the ordinary keyup/pad toggle.
            return
        elif not decision_candidates(self, target):
            target = next_decision(self, target)
            if target is None:
                self.failed = "The inspection shift ended."
                return
        if target > self.ms:
            self.advance(target, enforce_held=False, count_misses=False)

    def action(self, kind, lane_id=""):
        if self.failed:
            return
        if kind == "start":
            if self.started or self.ms != 0:
                self.failed = "Invalid start or restart."
            self.started = True
            return
        if not self.started or lane_id not in self.lanes:
            self.failed = "Input outside the active score."
            return
        c = circumference(self.world)
        half = self.world["parameters"]["band_half_width"]
        lane = self.lanes[lane_id]
        center = gate(self.world,lane,self.ms)
        if kind == "down":
            if lane_id in self.held:
                self.failed = "Duplicate press."
                return
            candidates = [n for n in self.notes.values() if n["lane"] == lane_id and n["id"] not in self.cleared
                          and abs(phase(self.world,n,self.ms)%c-center) <= half+1e-7]
            if len(candidates) != 1:
                self.failed = "A stamp missed the moving gold band."
                return
            note = candidates[0]
            self.held[lane_id] = dict(note=note["id"],kind=note["kind"],cycle=math.floor(phase(self.world,note,self.ms)/c))
            if note["kind"] == "tap":
                self.cleared.add(note["id"])
        elif kind == "up":
            held = self.held.get(lane_id)
            if not held:
                self.failed = "Release without a press."
                return
            note = self.notes[held["note"]]
            if held["kind"] == "hold" and abs(phase(self.world,note,self.ms)-note["length"]-held["cycle"]*c-center) > half+1e-7:
                self.failed = "A ribbon was released outside the moving gold band."
                return
            self.cleared.add(note["id"])
            del self.held[lane_id]
        else:
            self.failed = "Unknown input; resets and world stops are unavailable."


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True,passed=False,score=0,feedback=message)
    if not all(isinstance(v,dict) for v in (payload,ground_truth,public_state)):
        return fail("Malformed result or world.")
    for key in ("mechanic_id","task_id","challenge_id","revision"):
        if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
            return fail("Stale or mismatched "+key)
    if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION:
        return fail("Wrong mechanic revision.")
    for key in ("rail","lanes","notes","parameters","run_limit_ms","control_condition"):
        if public_state.get(key) != ground_truth.get(key):
            return fail("Public replay contract differs: "+key)
    mode = (ground_truth.get("control_condition") or {}).get("interaction","full")
    source = {"full":"keyboard","simplified":"pad_toggle"}.get(mode)
    if source is None or payload.get("interaction_mode") != mode:
        return fail("Wrong interaction mode.")
    events = payload.get("events")
    if not isinstance(events,list) or not 1 <= len(events) <= 1000:
        return fail("Missing or excessive input trace.")
    try:
        replay = Replay(ground_truth)
        previous = -1.
        for sequence,event in enumerate(events,1):
            if not isinstance(event,dict):
                return fail("Malformed input event.")
            ms = event.get("t_ms")
            if type(ms) not in (int,float) or not math.isfinite(ms) or not 0 <= ms <= ground_truth["run_limit_ms"] or ms < previous or event.get("sequence") != sequence:
                return fail("Invalid event time or order.")
            kind = event.get("kind")
            if (sequence == 1 and (kind != "start" or event.get("input_source") != "begin_button" or ms != 0)) or (sequence > 1 and event.get("input_source") != source):
                return fail("Wrong input surface or start.")
            replay.advance(ms)
            replay.action(kind,event.get("lane",""))
            if replay.failed:
                return fail(replay.failed)
            if sequence == 1:
                replay.settle_start()
            else:
                replay.settle_after_action(kind,event.get("lane",""))
            if replay.failed:
                return fail(replay.failed)
            previous = ms
        final = payload.get("final_t_ms")
        if type(final) not in (int,float) or not math.isfinite(final) or not previous <= final <= ground_truth["run_limit_ms"]:
            return fail("Invalid final task time.")
        replay.advance(final)
        if replay.failed:
            return fail(replay.failed)
        if payload.get("cleared_ids") != sorted(replay.cleared):
            return fail("Claimed clearance differs from replay.")
        if payload.get("missed_passes") != replay.missed:
            return fail("Claimed missed-pass count differs from replay.")
        passed = (payload.get("completed") is True and replay.started and not replay.held
                  and replay.cleared == set(replay.notes))
        return dict(graded=True,passed=passed,score=100 if passed else 0,
                    feedback=f"Circulating score replay: {len(replay.cleared)}/{len(replay.notes)} notes; {replay.missed} missed passes; {'clear' if passed else 'incomplete'}.")
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        return fail("Invalid score transcript: "+str(exc))


def cheat(public_state, ground_truth):
    return {"note_count":len(ground_truth.get("notes",[]))}
