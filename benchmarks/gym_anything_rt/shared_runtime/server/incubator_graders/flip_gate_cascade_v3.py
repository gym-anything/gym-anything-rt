"""Independent fixed-step replay of rails, rotor flips, wind and catcher contact.

Standalone standard-library module: the exported Pyodide grader loads it unchanged.
No browser-reported paths, catches, gate states or completion flags are trusted.
"""
from __future__ import annotations

import copy
import math

MECHANIC_ID = "flip_gate_cascade_v3"
REVISION = "cascade-inspection-3"


def clamp(value, low, high):
    return max(low, min(high, value))


def noise(seed, index):
    x = (int(seed) ^ ((index + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def wind(world, ms):
    u = max(0, ms) / world["wind_span_ms"]
    n = math.floor(u)
    f = u - n
    a, b = noise(world["wind_seed"], n), noise(world["wind_seed"], n + 1)
    return world["wind_acceleration"] * (a + (b - a) * f * f * (3 - 2 * f))


class Physics:
    def __init__(self, world):
        self.w = copy.deepcopy(world)
        self.ms = 0
        self.run_start = None
        self.x = self.target = 480.0
        self.vx = 0.0
        self.orientation = 0
        self.gates = list(world["initial_gates"])
        self.balls = {}
        self.released = 0
        self.caught = []
        self.contacts = []
        self.flips = []
        self.failed = ""
        self.done = False

    @property
    def width(self):
        return self.w["pockets"] * self.w["pocket_width"] + (self.w["pockets"] - 1) * self.w["divider_width"]

    def pocket_offset(self, kind):
        return 0 if self.w["pockets"] == 1 else (-1 if kind == self.orientation else 1) * (self.w["pocket_width"] + self.w["divider_width"]) / 2

    def start(self):
        if self.run_start is not None:
            raise ValueError("a cascade can start only once")
        self.run_start = self.ms

    def latch(self):
        """Close the visible pocket shutters around the current marble.

        Closure is an immediate physical attempt, like firing at a moving
        target. Steering and swaps remain available; neither can reverse a
        missed closure or retrieve a marble that has already escaped.
        """
        if self.failed or self.done:
            return False
        balls = [b for b in self.balls.values() if b["phase"] == "free"
                 and self.w["capture_top"] <= b["y"] - b["radius"]
                 and b["y"] + b["radius"] <= self.w["rim_y"]]
        if self.run_start is None or not balls:
            self.failed = "EMPTY LATCH"
            return False
        ball = max(balls, key=lambda b: b["y"])
        center = self.x + self.pocket_offset(ball["kind"])
        valid = abs(ball["x"] - center) + ball["radius"] <= self.w["pocket_width"] / 2 + 1e-7
        self.contacts.append(dict(id=ball["id"], t_ms=self.ms, x=ball["x"], y=ball["y"],
                                 catcher=self.x, pocket=ball["kind"], caught=valid, via="latch"))
        if valid:
            self.caught.append(ball["id"])
            del self.balls[ball["id"]]
            self.done = len(self.caught) == len(self.w["marbles"])
        else:
            self.failed = "MISALIGNED OR WRONG-POCKET LATCH"
        return valid

    def _release(self, spec):
        column = self.w["entry_columns"][spec["chute"]]
        first = self.w["gates"][column]
        mouth = self.w["gates"][spec["chute"]]
        self.balls[spec["id"]] = dict(**spec, row=-1, column=column, phase="rail",
            segment_start=self.ms, segment_ms=self.w["rail_ms"],
            ax=mouth["x"], ay=20.0, bx=first["x"], by=first["y"],
            x=mouth["x"], y=20.0, vx=(first["x"]-mouth["x"])*1000/self.w["rail_ms"],
            vy=(first["y"]-20)*1000/self.w["rail_ms"])
        self.released += 1

    def advance(self, end_ms):
        w = self.w
        while self.ms + 10 <= end_ms and not self.failed and not self.done:
            self.ms += 10
            previous_x = self.x
            acceleration = clamp((self.target - self.x) * 60 - self.vx * 14,
                                 -w["basket_acceleration"], w["basket_acceleration"])
            self.vx = clamp(self.vx + acceleration * .01, -w["basket_speed"], w["basket_speed"])
            self.x = clamp(self.x + self.vx * .01, w["wall_left"] + self.width / 2,
                           w["wall_right"] - self.width / 2)
            if self.x in (w["wall_left"] + self.width / 2, w["wall_right"] - self.width / 2):
                self.vx = 0.0
            if self.run_start is None:
                continue
            elapsed = self.ms - self.run_start
            for spec in w["marbles"]:
                if spec["id"] >= self.released and elapsed >= spec["release_ms"]:
                    self._release(spec)
            for identifier, ball in list(self.balls.items()):
                if ball["phase"] == "rail":
                    fraction = min(1, (self.ms - ball["segment_start"]) / ball["segment_ms"])
                    ball["x"] = ball["ax"] + (ball["bx"] - ball["ax"]) * fraction
                    ball["y"] = ball["ay"] + (ball["by"] - ball["ay"]) * fraction
                    if fraction < 1:
                        continue
                    if ball["row"] == w["rows"] - 1:
                        ball.update(phase="free", vx=ball["exit_sign"] * w["exit_vx"], vy=w["initial_vy"])
                        continue
                    row = ball["row"] + 1
                    column = ball["column"]
                    gate_id = w["offsets"][row] + column
                    direction = self.gates[gate_id]
                    self.gates[gate_id] = 1 - direction
                    self.flips.append(dict(id=identifier, gate=gate_id, before=direction, t_ms=self.ms))
                    ball.update(row=row, column=column + direction,
                                segment_start=self.ms, ax=ball["x"], ay=ball["y"])
                    if row + 1 < w["rows"]:
                        destination = w["gates"][w["offsets"][row + 1] + column + direction]
                        ball.update(bx=destination["x"], by=destination["y"], segment_ms=w["rail_ms"])
                    else:
                        sign = 1 if direction else -1
                        ball.update(bx=ball["x"] + sign * w["spacing"] / 2,
                                    by=280.0, segment_ms=600, exit_sign=sign)
                    ball["vx"] = (ball["bx"] - ball["ax"]) * 1000 / ball["segment_ms"]
                    ball["vy"] = (ball["by"] - ball["ay"]) * 1000 / ball["segment_ms"]
                    continue
                old_x, old_y = ball["x"], ball["y"]
                ball["vx"] += (wind(w, elapsed) * ball["wind_scale"] - .12 * ball["vx"]) * .01
                ball["vy"] += w["gravity"] * .01
                ball["x"] += ball["vx"] * .01
                ball["y"] += ball["vy"] * .01
                radius = ball["radius"]
                lo, hi = w["wall_left"] + radius, w["wall_right"] - radius
                if ball["x"] < lo or ball["x"] > hi:
                    # Mirror the overshoot so position remains a swept-wall contact.
                    ball["x"] = 2 * lo - ball["x"] if ball["x"] < lo else 2 * hi - ball["x"]
                    ball["vx"] *= -.65
                if old_y + radius < w["rim_y"] <= ball["y"] + radius:
                    fraction = (w["rim_y"] - radius - old_y) / (ball["y"] - old_y)
                    impact = old_x + (ball["x"] - old_x) * fraction
                    catcher = previous_x + (self.x - previous_x) * fraction
                    self.contacts.append(dict(id=identifier, t_ms=self.ms, x=impact,
                                             y=w["rim_y"]-radius, catcher=catcher,
                                             pocket=ball["kind"], caught=False, via="escape"))
                    ball["x"], ball["y"] = impact, w["rim_y"] - radius
                    self.failed = "MARBLE ESCAPED — LATCH BEFORE THE FLOOR"
                    break
            self.done = len(self.caught) == len(w["marbles"])
            if elapsed > w["run_limit_ms"] and not self.done:
                self.failed = "CASCADE ENDED"

    def claims(self):
        return dict(caught_ids=list(self.caught), final_gates=list(self.gates),
                    completed=self.done and not self.failed, failed=self.failed,
                    physics_ms=self.ms, basket_x=round(self.x, 4), orientation=self.orientation)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def replay(payload, truth, public):
    for key in ("mechanic_id", "task_id", "challenge_id", "physics_revision"):
        if not truth.get(key) or payload.get(key) != truth[key] or public.get(key) != truth[key]:
            raise ValueError("stale or wrong " + key)
    if truth["mechanic_id"] != MECHANIC_ID or truth["physics_revision"] != REVISION:
        raise ValueError("wrong physics")
    if truth["world"] != public.get("world") or truth.get("control_condition") != public.get("control_condition"):
        raise ValueError("public contract mismatch")
    entries = truth["world"].get("entry_columns")
    if (not isinstance(entries, list) or any(type(v) is not int for v in entries)
            or sorted(entries) != list(range(truth["world"]["top_chutes"]))):
        raise ValueError("invalid inlet manifold")
    if truth.get("episode_failure") != public.get("episode_failure"):
        raise ValueError("episode failure evidence mismatch")
    if truth.get("episode_failure"):
        raise ValueError("the first failed committed cascade already ended this episode")
    mode = (truth.get("control_condition") or {}).get("interaction", "full")
    if payload.get("interaction_mode") != mode:
        raise ValueError("wrong interaction")
    events = payload.get("events")
    if not isinstance(events, list) or not events or len(events) > 6000:
        raise ValueError("missing or excessive transcript")
    physics = Physics(truth["world"])
    previous, drag, sealed = -1, False, False
    for sequence, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("sequence") != sequence:
            raise ValueError("invalid sequence")
        t, kind = event.get("t_ms"), event.get("kind")
        if not _number(t) or t < previous or t > 180000 or sealed:
            raise ValueError("invalid time or action after seal")
        previous = t
        physics.advance(t)
        if kind == "seal":
            sealed = True
            continue
        if physics.failed or physics.done:
            raise ValueError("action after terminal contact")
        if kind == "inspect_chamber":
            point = event.get("point")
            if (event.get("input_source") != "inspection_pointer"
                    or not isinstance(point, list) or len(point) != 2
                    or not all(_number(v) for v in point)
                    or not 0 <= point[0] <= 960 or not 0 <= point[1] <= 570):
                raise ValueError("invalid chamber inspection")
            continue
        if kind == "inspect":
            chute, point = event.get("chute"), event.get("point")
            if (event.get("input_source") != "inlet_inspection" or type(chute) is not int
                    or not 0 <= chute < physics.w["top_chutes"]
                    or not isinstance(point, list) or len(point) != 2
                    or not all(_number(v) for v in point)
                    or abs(point[0]-physics.w["gates"][chute]["x"]) > 28
                    or not 0 <= point[1] <= 25
                    or type(event.get("entry_column")) is not int
                    or event.get("entry_column") != entries[chute]):
                raise ValueError("invalid inlet inspection")
            # Inspection reports information only. It never starts, freezes,
            # resets, flips, steers, consumes stock or unlocks the machine.
            continue
        if kind == "start":
            if event.get("input_source") != "start_button":
                raise ValueError("invalid start control")
            physics.start()
            continue
        if kind == "swap":
            if physics.w["pockets"] != 2 or event.get("input_source") not in ("pocket_button", "pocket_key"):
                raise ValueError("invalid pocket swap")
            physics.orientation = 1 - physics.orientation
            continue
        if kind == "latch":
            if event.get("input_source") not in ("latch_button", "latch_key"):
                raise ValueError("invalid latch control")
            physics.latch()
            continue
        point = event.get("point")
        if not isinstance(point, list) or len(point) != 2 or not all(_number(v) for v in point):
            raise ValueError("invalid pointer geometry")
        x, y = point
        if not 0 <= x <= 960 or not 0 <= y <= 570:
            raise ValueError("pointer outside cabinet")
        if mode == "simplified":
            if kind != "target" or event.get("input_source") != "rail_click" or not 495 <= y <= 569:
                raise ValueError("wrong proxy control")
            physics.target = x
        elif mode == "full":
            if event.get("input_source") != "basket_drag":
                raise ValueError("wrong direct control")
            if kind == "drag_start":
                if drag or abs(x - physics.x) > physics.width / 2 or not 520 <= y <= 558:
                    raise ValueError("drag must begin on the moving catcher")
                drag = True
            elif kind == "drag_move" and drag:
                physics.target = x
            elif kind in ("drag_end", "drag_cancel") and drag:
                drag = False
            else:
                raise ValueError("invalid captured drag")
        else:
            raise ValueError("unsupported input mode")
    final = payload.get("final_t_ms")
    if not sealed or not _number(final) or not previous <= final <= 180000:
        raise ValueError("missing final seal")
    physics.advance(final)
    for key, value in physics.claims().items():
        if key == "basket_x":
            if not _number(payload.get(key)) or abs(payload[key] - value) > .001:
                raise ValueError("basket position contradicts replay")
        elif payload.get(key) != value:
            raise ValueError("terminal claims contradict replay: " + key)
    return physics


def grade(payload, ground_truth, public_state):
    try:
        physics = replay(payload, ground_truth, public_state)
        passed = physics.done and not physics.failed
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"cascade replay: {len(physics.caught)}/{len(physics.w['marbles'])} caught; " + ("complete" if passed else physics.failed or "incomplete"))
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        return dict(graded=True, passed=False, score=0, feedback="invalid cascade: " + str(error))


def cheat(ground_truth, public_state):
    del public_state
    return {"world": ground_truth.get("world")}
