"""Independent replay of drifting ceramic rafts and finite crossing spans.

No browser outcome flag, path certificate or client collision decision is trusted.
Units are logical canvas pixels and integer milliseconds of the shared clock.
"""
from __future__ import annotations

import math

MECHANIC_ID = "crackglaze_crossing_v3"
REVISION = "drifting-rafts-exploration-v3"


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(seed, t, span):
    u = max(0, t) / span
    n = math.floor(u)
    f = u - n
    return noise(seed, n) + (noise(seed, n + 1) - noise(seed, n)) * f * f * (3 - 2 * f)


def center(cell, t, parameters):
    return [cell["center"][i] + parameters["drift_px"] * motion(
        cell["motion_seed"] + 7919 * i, t + cell["phase_ms"], cell["span_ms"])
        for i in range(2)]


def span_distance(world, origin, destination, t):
    cells = {c["id"]: c for c in world["cells"]}
    return math.dist(center(cells[origin], t, world["parameters"]),
                     center(cells[destination], t, world["parameters"]))


def crossing_failure(world, origin, destination, t, lit_at):
    cells = {c["id"]: c for c in world["cells"]}
    p = world["parameters"]
    end = t + p["crossing_ms"]
    # The occupied departing raft is no longer needed after launch. The landing
    # raft must exist on arrival. Fuses never restart when a raft is revisited.
    if destination in lit_at and end >= lit_at[destination] + cells[destination]["fuse_ms"]:
        return "collapsed_landing"
    if span_distance(world, origin, destination, t) > p["reach_px"] + 1e-6:
        return "gap_too_wide"
    for tick in range(t, end + 1, 10):
        if span_distance(world, origin, destination, tick) > p["reach_px"] + 1e-6:
            return "span_broke"
    if span_distance(world, origin, destination, end) > p["reach_px"] + 1e-6:
        return "span_broke"
    return ""


def direction(cells, a, b):
    dr = cells[b]["row"] - cells[a]["row"]
    dc = cells[b]["column"] - cells[a]["column"]
    return {(-1, 0): "up", (1, 0): "down", (0, -1): "left", (0, 1): "right"}.get((dr, dc), "")


def _finite(x):
    return type(x) in (int, float) and math.isfinite(x)


def grade(payload, truth, public):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
            if not truth.get(key) or payload.get(key) != truth[key] or public.get(key) != truth[key]:
                return fail("stale or mismatched " + key)
        if truth["mechanic_id"] != MECHANIC_ID or truth["revision"] != REVISION:
            return fail("wrong ceramic physics revision")
        for key in ("parameters", "cells", "neighbors", "start_id", "exit_id", "lantern_ids", "glazes", "control_condition"):
            if public.get(key) != truth.get(key):
                return fail("public world disagrees: " + key)
        mode = truth["control_condition"]["interaction"]
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 160:
            return fail("missing or oversized crossing transcript")
        cells = {c["id"]: c for c in truth["cells"]}
        position, lit_at, collected = truth["start_id"], {}, set()
        available = 0
        for sequence, event in enumerate(events, 1):
            t = event.get("t_ms")
            if event.get("sequence") != sequence or event.get("kind") != "cross":
                return fail("unknown crossing event or bad sequence")
            if type(t) is not int or not available <= t <= 300000:
                return fail("invalid, overlapping or reversed action time")
            if position in lit_at and t >= lit_at[position] + cells[position]["fuse_ms"]:
                return fail("the occupied raft collapsed before the next input")
            destination = event.get("to")
            if event.get("from") != position or destination not in truth["neighbors"][position]:
                return fail("crossing is not an adjacent raft")
            if mode == "full":
                point = event.get("point")
                if event.get("input_source") != "raft_click" or not isinstance(point, list) or len(point) != 2 or not all(_finite(x) for x in point):
                    return fail("missing physical raft click")
                c = center(cells[destination], t, truth["parameters"])
                if any(abs(point[i] - c[i]) > truth["parameters"]["tile_px"] / 2 + .04 for i in range(2)):
                    return fail("click misses rendered ceramic face")
            elif event.get("input_source") != "direction_button" or "point" in event or event.get("direction") != direction(cells, position, destination):
                return fail("wrong simplified control surface")
            error = crossing_failure(truth, position, destination, t, lit_at)
            if error:
                return fail("terminal ceramic failure: " + error)
            lit_at.setdefault(position, t)
            position = destination
            available = t + truth["parameters"]["crossing_ms"]
            if position in truth["lantern_ids"]:
                collected.add(position)
            if position == truth["exit_id"] and len(collected) == len(truth["lantern_ids"]) and sequence != len(events):
                return fail("input after terminal success")
        final = payload.get("final_t_ms")
        if type(final) is not int or not available <= final <= 300000:
            return fail("invalid final crossing time")
        # Inspection reveals information, never unlocks travel or supplies a
        # probe-count goal. Check recorded stamps without requiring any quota.
        inspections = payload.get("inspections", [])
        if not isinstance(inspections, list) or len(inspections) > len(truth["glazes"]):
            return fail("malformed kiln inspection transcript")
        seen, previous = set(), 0
        for sequence, inspection in enumerate(inspections, 1):
            if not isinstance(inspection, dict):
                return fail("malformed kiln inspection")
            glaze, at = inspection.get("glaze"), inspection.get("t_ms")
            if (type(glaze) is not int or not 0 <= glaze < len(truth["glazes"])
                or glaze in seen or type(at) is not int or not previous <= at <= final
                or inspection.get("sequence") != sequence
                or inspection.get("input_source") != "sample_turn"
                or type(inspection.get("fuse_ms")) is not int
                or inspection["fuse_ms"] != truth["glazes"][glaze]["fuse_ms"]):
                return fail("invalid kiln stamp or inspection time")
            seen.add(glaze)
            previous = at
        if position in lit_at and final >= lit_at[position] + cells[position]["fuse_ms"]:
            return fail("occupied raft collapsed before certification")
        if payload.get("failure") or payload.get("completed") is not True:
            return fail("attempt was incomplete or terminally failed")
        expected = dict(position=position, collected=sorted(collected), lit_at=lit_at)
        if payload.get("final_state") != expected:
            return fail("final ceramic state does not match independent replay")
        if position != truth["exit_id"] or set(truth["lantern_ids"]) != collected:
            return fail("collect every lantern and reach the exit")
        return dict(graded=True, passed=True, score=100,
                    feedback=f"replayed {len(events)} moving-span crossings; {len(collected)} lanterns; exit reached")
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        return fail("malformed ceramic transcript: " + str(error))


def cheat(public_state, ground_truth):
    del public_state
    return {"privileged_certificate": ground_truth.get("certificate"), "planning_only": True}
