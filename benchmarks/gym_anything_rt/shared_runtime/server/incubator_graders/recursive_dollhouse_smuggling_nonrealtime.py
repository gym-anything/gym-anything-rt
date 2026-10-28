"""Independent fixed-step replay; no client outcome, collision, or pose is trusted."""
from __future__ import annotations

import math

MECHANIC_ID = "recursive_dollhouse_smuggling_nonrealtime"
REVISION = "nested-tethers-action-step-1"


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0, ms)/span
    i = math.floor(u)
    f = u-i
    a, b = noise(seed, i), noise(seed, i+1)
    return a+(b-a)*f*f*(3-2*f)


def gate_y(gate, ms):
    return gate["base_y"]+gate["drift"]*motion(gate["motion_seed"], ms, gate["span_ms"])


def clamp(x, a, b):
    return max(a, min(b, x))


class Physics:
    def __init__(self, truth):
        self.truth, self.spec = truth, truth["physics"]
        self.ms, self.active, self.failed = 0, False, ""
        self.action_step_ms = int(self.spec["action_step_ms"])
        if self.action_step_ms <= 0 or self.spec.get("progression") != "after_tether_action":
            raise ValueError("invalid action-triggered physics contract")
        self.parcels = [dict(id=p["id"], x=p["x"], y=p["y"], v=0., target=p["y"],
                             scale=0, transfers=0, delivered=False, wind_seed=p["wind_seed"])
                        for p in truth["parcels"]]

    @property
    def complete(self):
        return all(p["delivered"] for p in self.parcels)

    def advance(self, end):
        while self.ms+10 <= end and not self.failed and not self.complete:
            self.ms += 10
            if not self.active:
                continue
            s = self.spec
            if self.ms > s["play_time_ms"]:
                self.failed = "The conveyor allowance ended."
                break
            for p in self.parcels:
                if p["delivered"]:
                    continue
                wind = s["wind"]*motion(p["wind_seed"], self.ms, s["wind_span_ms"])
                a = clamp((p["target"]-p["y"])*s["stiffness"]-p["v"]*s["damping"]+wind,
                          -s["max_acceleration"], s["max_acceleration"])
                p["v"] = clamp(p["v"]+a*.01, -s["max_speed"], s["max_speed"])
                p["y"] += p["v"]*.01
                p["x"] += s["belt_speed"]*.01
                r = s["radii"][p["scale"]]
                if p["y"]-r < 0 or p["y"]+r > self.truth["room"]["depth"]:
                    self.failed = f'{p["id"]} struck the room edge.'
                    break
                for gate in self.truth["gates"]:
                    if abs(p["x"]-gate["x"]) < r+gate["width"]/2-1e-9:
                        if abs(p["y"]-gate_y(gate, self.ms))+r > gate["opening"]/2+1e-9:
                            self.failed = f'{p["id"]} struck {gate["id"]}.'
                            break
                if self.failed:
                    break
                gate = self.truth["gates"][p["transfers"]]
                next_scale = min(2, p["scale"]+1)
                exit_radius = s["radii"][next_scale]
                if p["x"] > gate["x"]+gate["width"]/2+exit_radius+.01:
                    p["transfers"] += 1
                    if p["transfers"] == 3:
                        p["delivered"] = True
                    else:
                        p["scale"] = next_scale
            # Actual square footprints can collide, even though the generated
            # longitudinal spacing normally keeps them apart.
            for i, p in enumerate(self.parcels):
                for q in self.parcels[i+1:]:
                    extent = s["radii"][p["scale"]]+s["radii"][q["scale"]]-1e-9
                    if not p["delivered"] and not q["delivered"] and abs(p["x"]-q["x"]) < extent and abs(p["y"]-q["y"]) < extent:
                        self.failed = "The parcels collided."

    def snapshot(self):
        return dict(ms=self.ms, active=self.active, failed=self.failed,
                    complete=self.complete, parcels=[dict(p) for p in self.parcels])

    def advance_after_tether_action(self):
        if self.active:
            self.advance(self.ms + self.action_step_ms)


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("finite numeric input required")
    return float(value)


def grade(payload, ground_truth, public_state):
    def fail(text):
        return dict(graded=True, passed=False, score=0, feedback=text)
    try:
        for field in ("mechanic_id", "task_id", "challenge_id"):
            if not ground_truth.get(field) or any(p.get(field) != ground_truth[field] for p in (payload, public_state)):
                return fail("stale or wrong "+field)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for field in ("control_condition", "views", "room", "gates", "parcels", "physics"):
            if public_state.get(field) != ground_truth.get(field):
                return fail("public/replay contract mismatch: "+field)
        mode = ground_truth["control_condition"]["interaction"]
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode or payload.get("physics_revision") != REVISION:
            return fail("wrong interaction or physics revision")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 12000:
            return fail("missing input transcript")
        sim = Physics(ground_truth)
        previous = -1
        hold = None
        for seq, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("sequence") != seq:
                return fail("invalid event sequence")
            t = number(event.get("t_ms"))
            if not 0 <= t <= sim.spec["play_time_ms"] or t < previous:
                return fail("invalid event time")
            # The counterpart has no autonomous clock.  A wall-clock wait or
            # fabricated timestamp cannot advance the replay; only a completed
            # tether target action below advances one fixed logical segment.
            if t != sim.ms:
                return fail("waiting does not advance the action-triggered clock")
            previous = t
            sim.advance(t)
            if sim.failed:
                return fail(sim.failed)
            kind = event.get("kind")
            if kind == "start":
                if sim.active or hold is not None or event.get("input_source") != "start_button":
                    return fail("invalid conveyor start")
                sim.active = True
                # Task-relative epoch begins at the start input. Every input
                # timestamp is already measured from that epoch by the UI.
                if t != 0:
                    return fail("start must establish time zero")
            elif kind in ("hold", "aim", "release", "target"):
                idx = event.get("parcel_index")
                if type(idx) is not int or not 0 <= idx < len(sim.parcels):
                    return fail("unknown tether")
                p = sim.parcels[idx]
                if p["delivered"] and kind != "release":
                    return fail("inactive tether")
                source = "tether_drag" if mode == "full" else "tether_click"
                if event.get("input_source") != source or event.get("view_index") != ground_truth["parcels"][idx]["control_view"]:
                    return fail("wrong input surface or linked view")
                value = number(event.get("value"))
                if not 7 <= value <= 65:
                    return fail("tether leaves its rail")
                if kind == "hold":
                    if mode != "full" or hold is not None or abs(value-p["target"]) > 3.0:
                        return fail("drag must begin on the current handle")
                    hold = idx
                elif kind == "aim":
                    if mode != "full" or hold != idx:
                        return fail("no matching held tether")
                    p["target"] = value
                    sim.advance_after_tether_action()
                elif kind == "release":
                    if mode != "full" or hold != idx or abs(value-p["target"]) > .001:
                        return fail("invalid tether release")
                    hold = None
                elif kind == "target":
                    if mode != "simplified" or hold is not None:
                        return fail("click proxy only")
                    p["target"] = value
                    sim.advance_after_tether_action()
            else:
                return fail("unknown input, reset, or retry")
            if sim.failed:
                return fail(sim.failed)
        final = number(payload.get("final_t_ms"))
        if not previous <= final <= sim.spec["play_time_ms"] or final != sim.ms:
            return fail("invalid final time")
        if sim.failed or not sim.active or not sim.complete or payload.get("completed") is not True:
            return fail(sim.failed or "the complete nested manifest has not reached the exit")
        return dict(graded=True, passed=True, score=100,
                    feedback=f"All {len(sim.parcels)} parcels crossed both growing frames and the drifting exit.",
                    replay=sim.snapshot())
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as exc:
        return fail("invalid nested transcript: "+str(exc))


def cheat(public_state, ground_truth):
    return {"note": "No answer token: steer the moving world.", "gates": ground_truth.get("gates", [])}
