"""Independent replay of visible borders and moving voter centers, without browser state."""
from __future__ import annotations

import copy
import math

MECHANIC_ID = "charter_of_the_nine_cantons_v3_nonrealtime"


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def center(border, t_ms):
    knots = border["knots"]
    for (start, a), (end, b) in zip(knots, knots[1:]):
        if start <= t_ms <= end:
            f = (t_ms - start) / (end - start)
            return border["base"] + a + (b - a) * f * f * (3 - 2 * f)
    raise ValueError("task time left the generated continuous motion")


def centers(truth, t_ms):
    simulation = truth.get("simulation") or {}
    world_time = 0 if simulation.get("world_time_mode") == "parked_after_open" else t_ms
    return [center(border, world_time) for border in truth["borders"]]


def balanced(truth, boundaries, t_ms):
    # Generation keeps the two migrant pairs on each border between the
    # stationary cores, without crossing each other. Equal population is
    # equivalent to placing the border strictly after the left pair and at or
    # before the right pair. Tests compare this shortcut to full household counts.
    parked_centers = centers(truth, t_ms)
    return all(parked_centers[b["id"]] - b["gap"] / 2 < boundaries[b["id"]]
               <= parked_centers[b["id"]] + b["gap"] / 2 for b in truth["borders"])


def statistics(truth, boundaries, t_ms):
    census = centers(truth, t_ms)
    counts = [dict(gilt=0, tide=0, plum=0) for _ in range(9)]
    for voter in truth["voters"]:
        x = voter.get("x", 0) if "border" not in voter else census[voter["border"]] + voter["offset"]
        row = voter["row"]
        # Half-open districts: a center exactly on a border belongs to its right.
        column = int(x >= boundaries[row * 2]) + int(x >= boundaries[row * 2 + 1])
        counts[row * 3 + column][voter["guild"]] += 1
    holdings = dict(gilt=0, tide=0, plum=0)
    populations, winners = [], []
    for guild_counts in counts:
        populations.append(sum(guild_counts.values()))
        ordered = sorted(guild_counts, key=guild_counts.get, reverse=True)
        winner = ordered[0] if guild_counts[ordered[0]] > guild_counts[ordered[1]] else "tie"
        winners.append(winner)
        if winner != "tie":
            holdings[winner] += 1
    valid = all(p == truth["population"] for p in populations) and holdings == truth["target_split"]
    return dict(populations=populations, winners=winners, holdings=holdings, valid=valid)


class Simulation:
    def __init__(self, truth):
        self.truth = truth
        self.boundaries = [b["initial"] for b in truth["borders"]]
        self.t_ms = 0
        self.charge_ms = 0.0
        self.started = False
        self.status = "ready"
        self.valid_ms = 0

    def advance(self, target):
        if not self.started:
            if target != 0:
                raise ValueError("time progressed before the census opened")
            return
        step = self.truth["simulation"]["tick_ms"]
        while self.t_ms < target and self.status == "active":
            self.t_ms += step
            valid = balanced(self.truth, self.boundaries, self.t_ms)
            self.valid_ms += step if valid else 0
            self.charge_ms = self.charge_ms + step if valid else 0.0
            if self.charge_ms >= self.truth["simulation"]["audit_ms"]:
                self.charge_ms = float(self.truth["simulation"]["audit_ms"])
                self.status = "success"
            elif self.t_ms >= self.truth["simulation"]["deadline_ms"]:
                self.status = "failure"
        if self.t_ms != target:
            raise ValueError("transcript continues after the terminal census")

    def set_border(self, index, x):
        if type(index) is not int or not 0 <= index < 6 or type(x) not in (int, float) or not math.isfinite(x):
            raise ValueError("invalid border coordinate")
        low, high = ((220, 460) if index % 2 == 0 else (580, 820))
        if not low <= x <= high:
            raise ValueError("border left its connected cadastral corridor")
        self.boundaries[index] = float(x)

    def metrics(self):
        return dict(t_ms=self.t_ms, charge_ms=round(self.charge_ms, 3), valid_ms=self.valid_ms,
                    boundaries=[round(x, 3) for x in self.boundaries], status=self.status,
                    census=statistics(self.truth, self.boundaries, self.t_ms))


def grade(payload, truth, public):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "revision", "task_id", "challenge_id"):
            if not truth.get(key) or public.get(key) != truth[key] or payload.get(key) != truth[key]:
                return fail("stale or mismatched " + key)
        if truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("parameters", "borders", "voters", "population", "target_split", "simulation", "inspection", "control_condition"):
            if truth.get(key) != public.get(key):
                return fail("public contract mismatch: " + key)
        mode = (truth.get("control_condition") or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list):
            return fail("invalid action transcript")
        sim = Simulation(truth)
        drag = None
        previous = 0
        for sequence, event in enumerate(events, 1):
            t = event.get("t_ms")
            if type(t) is not int or t < previous or t % 20 or t > 120000 or event.get("sequence") != sequence:
                return fail("invalid event ordering or time")
            sim.advance(t)
            if sim.status in ("success", "failure"):
                return fail("action after terminal state")
            previous = t
            kind = event.get("type")
            if kind == "start":
                if sim.started or t != 0 or drag is not None or event.get("input_source") != "open_census_button":
                    return fail("duplicate or invalid start")
                sim.started, sim.status = True, "active"
            elif kind == "inspect":
                # Inspection is a safe information probe, never a success quota.
                if type(event.get("row")) is not int or not 0 <= event["row"] < 3 or drag is not None or event.get("input_source") != "census_folio_click":
                    return fail("invalid field folio inspection")
            elif kind == "drag_begin":
                index, x = event.get("border"), event.get("x")
                if mode != "full" or drag is not None or event.get("input_source") != "border_handle_drag":
                    return fail("wrong drag surface")
                # The browser admits a 23-unit pickup radius and records X
                # to three decimals. Preserve that geometry in replay.
                if type(index) is not int or not 0 <= index < 6 or type(x) not in (int, float) or not math.isfinite(x):
                    return fail("drag does not start on the visible border handle")
                low, high = (580, 820) if index % 2 else (220, 460)
                if not low <= x <= high or abs(x - sim.boundaries[index]) > 23.001:
                    return fail("drag does not start on the visible border handle")
                drag = index
            elif kind == "target":
                expected = "border_handle_drag" if mode == "full" else "border_ruler_click"
                if event.get("input_source") != expected or (mode == "full" and drag != event.get("border")):
                    return fail("target uses the wrong input surface")
                sim.set_border(event.get("border"), event.get("x"))
            elif kind == "drag_end":
                if mode != "full" or drag is None or event.get("border") != drag or event.get("input_source") != "border_handle_drag":
                    return fail("invalid drag release")
                drag = None
            elif kind == "certify":
                if event.get("input_source") != "seal_charter_button":
                    return fail("invalid certification")
                sim.status = "failure"  # Early certification is an irreversible execution mistake.
            else:
                return fail("unsupported census action")
        final = payload.get("final_t_ms")
        if type(final) is not int or final < previous or final % 20 or final > 120000:
            return fail("invalid final task time")
        sim.advance(final)
        actual = sim.metrics()
        claimed = payload.get("metrics")
        if not isinstance(claimed, dict) or claimed != actual:
            return fail("submitted census metrics disagree with independent replay")
        passed = sim.status == "success" and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"continuous census replay: {actual['charge_ms']:g}/30000 ms ratified; {actual['valid_ms']} ms balanced; status {sim.status}",
                    metrics=actual)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return fail("census replay rejected: " + str(exc))
