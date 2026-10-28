"""Independent, standalone replay of kinematic cube rolls and moving shutters.

This file also executes without repository imports in the static Pyodide worker.
Rendered cube bounds, including their enlargement while tipping, are the bounds
used below. No client completion, reported orientation or capture bit is trusted.
"""
from __future__ import annotations

import math

MECHANIC_ID = "blind_dice_courier_v2"
REVISION = "sliding-shutters-2"
MOVES = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}


def roll(faces, direction):
    t, b, n, s, e, w = faces
    if direction == "N": return [s, n, t, b, e, w]
    if direction == "S": return [n, s, b, t, e, w]
    if direction == "E": return [w, e, n, s, t, b]
    if direction == "W": return [e, w, n, s, b, t]
    raise ValueError("invalid roll direction")


def gate_pose(gate, milliseconds, offset_ms=0):
    time = milliseconds + offset_ms
    track = gate["track"]
    index = next((i for i, s in enumerate(track) if time < s["start_ms"] + s["duration_ms"]), len(track)-1)
    segment = track[index]
    f = max(0, min(1, (time - segment["start_ms"]) / segment["duration_ms"]))
    a, b = segment["a"], segment["b"]
    blend = f*f*(3-2*f)
    return dict(y=a+(b-a)*blend, velocity=(b-a)*6*f*(1-f)*1000/segment["duration_ms"],
                phase=f, a=a, b=b, next=track[min(index+1, len(track)-1)]["b"],
                duration_ms=segment["duration_ms"],
                next_duration_ms=track[min(index+1, len(track)-1)]["duration_ms"], index=index)


class Simulation:
    def __init__(self, contract):
        self.world = contract["world"]
        self.position = list(self.world["start"])
        self.faces = list(contract["initial_orientation"])
        self.ms, self.active, self.pending = 0, False, None
        self.failed, self.delivered, self.crossings = "", False, []
        self.pillars = {tuple(p) for p in self.world["pillars"]}

    def body(self):
        x, y = self.position
        hx = hy = .5
        z = .5
        if self.pending:
            f = min(1, max(0, (self.ms-self.pending["start_ms"])/self.world["roll_ms"]))
            theta = f*math.pi/2
            sine, cosine = math.sin(theta), math.cos(theta)
            shift = .5 + .5*(sine-cosine)
            half = .5*(sine+cosine)
            dx, dy = MOVES[self.pending["direction"]]
            x += dx*shift
            y += dy*shift
            if dx: hx = half
            else: hy = half
            z = half
        return dict(x=x, y=y, hx=hx, hy=hy, z=z)

    def contact(self):
        body = self.body()
        for gate in self.world["gates"]:
            for slat in gate["slats"]:
                if abs(body["x"]-slat["x"]) < body["hx"] + self.world["slat_thickness"]/2 - 1e-9:
                    pose = gate_pose(gate, self.ms, slat["offset_ms"])
                    if abs(body["y"]-pose["y"]) + body["hy"] > gate["gap_height"]/2 + 1e-9:
                        return "The moving shutter struck the die."
        for x, y in self.pillars:
            if abs(body["x"]-x) < body["hx"]+.5-1e-9 and abs(body["y"]-y) < body["hy"]+.5-1e-9:
                return "The tipping die struck a pillar."
        return ""

    def advance(self, end_ms):
        if not self.active: return
        while self.ms+10 <= end_ms and not (self.failed or self.delivered):
            self.ms += 10
            self.failed = self.contact()
            if self.failed: break
            if self.pending and self.ms >= self.pending["start_ms"]+self.world["roll_ms"]:
                previous = self.position
                self.position = self.pending["target"]
                self.faces = roll(self.faces, self.pending["direction"])
                self.pending = None
                gate = next((g for g in self.world["gates"] if g["column"] == self.position[0] and previous[0] != self.position[0]), None)
                if gate:
                    if (gate.get("required_top") is not None and self.faces[0] != gate["required_top"]) or (gate.get("required_east") is not None and self.faces[4] != gate["required_east"]):
                        self.failed = "The arrival faces do not match the gate."
                        break
                    if gate["id"] not in self.crossings:
                        self.crossings.append(gate["id"])
                if self.position == self.world["goal"] and self.crossings == [g["id"] for g in self.world["gates"]]:
                    self.delivered = True
            if self.ms >= self.world["play_time_ms"] and not self.delivered:
                self.failed = "Dispatch time exhausted."

    def move(self, direction):
        if not self.active or self.pending or self.failed or self.delivered:
            raise ValueError("roll while inactive, busy or terminal")
        if direction not in MOVES: raise ValueError("invalid direction")
        dx, dy = MOVES[direction]
        target = [self.position[0]+dx, self.position[1]+dy]
        if not (0 <= target[0] < self.world["columns"] and 0 <= target[1] < self.world["rows"]) or tuple(target) in self.pillars:
            return False
        self.pending = dict(start_ms=self.ms, direction=direction, target=target)
        return True

    def snapshot(self):
        return dict(t_ms=self.ms, position=self.position, orientation=self.faces,
                    crossings=self.crossings, delivered=self.delivered, failed=self.failed)


def grade(payload, ground_truth, public_state):
    def fail(message): return dict(graded=True, passed=False, score=0, feedback=message)
    if not all(isinstance(x, dict) for x in (payload, ground_truth, public_state)):
        return fail("submission and state must be objects")
    for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
        if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
            return fail("stale or mismatched " + key)
    if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION:
        return fail("wrong courier implementation")
    for key in ("world", "initial_orientation", "control_condition"):
        if ground_truth.get(key) != public_state.get(key): return fail("public contract mismatch: " + key)
    mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
    source = {"full": "keyboard", "simplified": "direction_buttons"}.get(mode)
    if source is None or payload.get("interaction_mode") != mode:
        return fail("wrong interaction mode")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) < 2:
        return fail("missing primitive action trace")
    sim = Simulation(ground_truth)
    previous = -1
    try:
        for index, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("sequence") != index:
                return fail("event sequence is not contiguous")
            ms = event.get("t_ms")
            if type(ms) is not int or ms % 10 or not previous <= ms <= sim.world["play_time_ms"]:
                return fail("invalid task-clock timestamp")
            previous = ms
            sim.advance(ms)
            if sim.failed or sim.delivered: return fail("action after terminal outcome")
            if event.get("kind") == "start":
                if index != 1 or ms != 0 or event.get("input_source") != "start_button": return fail("invalid dispatch start")
                sim.active = True
            elif event.get("kind") == "roll":
                if event.get("input_source") != source: return fail("roll from wrong interaction surface")
                accepted = sim.move(event.get("direction"))
                if type(event.get("accepted")) is not bool or event["accepted"] != accepted:
                    return fail("wall response differs from replay")
            elif event.get("kind") == "submit":
                return fail("an incomplete submission ended the attempt")
            else:
                return fail("unknown control; reset and world-stop are unavailable")
        final_ms = payload.get("final_t_ms")
        if type(final_ms) is not int or final_ms % 10 or not previous <= final_ms <= sim.world["play_time_ms"]:
            return fail("invalid final task time")
        sim.advance(final_ms)
        if sim.failed: return fail(sim.failed)
        if sim.ms != final_ms or sim.pending or not sim.delivered or payload.get("completed") is not True:
            return fail("courier has not physically delivered the die")
        if payload.get("final_state") != sim.snapshot(): return fail("final state differs from independent replay")
        accepted_rolls = sum(event.get("kind") == "roll" and event.get("accepted") is True for event in events)
        blocked_inputs = sum(event.get("kind") == "roll" and event.get("accepted") is False for event in events)
        return dict(graded=True, passed=True, score=100,
                    feedback=f"Replayed {accepted_rolls} rolls and {len(sim.crossings)} sliding face gates.",
                    accepted_rolls=accepted_rolls, blocked_inputs=blocked_inputs)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return fail("malformed courier transcript: " + str(exc))


def cheat(public_state, ground_truth):
    return {"static_orientation_route": ground_truth.get("static_orientation_route", []),
            "warning": "This route ignores moving shutters and is not a timed solution."}
