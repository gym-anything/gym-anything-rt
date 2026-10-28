"""Independent stable-checkpoint replay. No browser-reported closes are trusted."""
from __future__ import annotations

import math

MECHANIC_ID = "popup_exorcist_v3_nonrealtime"


def pose(window, ms):
    u = (max(0, ms) + window["phase_ms"]) / window["span_ms"]
    i = min(len(window["knots"]) - 2, int(u))
    f = min(1, u - i)
    s = f * f * (3 - 2 * f)
    return [a + (b - a) * s for a, b in zip(window["knots"][i], window["knots"][i + 1])]


def seal(window, world, ms):
    x, y, rail = pose(window, ms)
    size = world["parameters"]["seal_size"]
    return [x + window["w"] - size / 2 - 10 - world["parameters"]["rail_travel"] + rail, y + size / 2 + 8]


def pane_at(world, closed, point, ms):
    """Return the same solid foreground pane for inspection and firing."""
    px, py = point
    for window in sorted(world["windows"], key=lambda w: w["z"], reverse=True):
        if window["id"] in closed:
            continue
        x, y, _ = pose(window, ms)
        if x <= px <= x + window["w"] and y <= py <= y + window["h"]:
            return window
    return None


def hit(world, closed, point, ms):
    window = pane_at(world, closed, point, ms)
    if window is None:
        return "miss", None
    sx, sy = seal(window, world, ms)
    r = world["parameters"]["seal_size"] / 2
    if abs(point[0] - sx) <= r and abs(point[1] - sy) <= r:
        return "trusted" if window["trusted"] else "close", window["id"]
    return "miss", window["id"]


def _decision_schedule(world):
    schedule = world.get("decision_times_ms")
    if (not isinstance(schedule, list) or not schedule
            or any(type(item) not in (int, float) or not math.isfinite(item)
                   or item <= 0 or item > world["play_time_ms"] for item in schedule)
            or any(not before < after for before, after in zip(schedule, schedule[1:]))):
        return None
    if schedule[0] != world.get("decision_grid_ms", 600) or schedule[-1] != world["play_time_ms"]:
        return None
    return schedule


def grade(payload, ground_truth, public_state):
    def fail(reason):
        return dict(graded=True, passed=False, score=0, feedback=reason)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or wrong " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("control_condition", "world"):
            if ground_truth.get(key) != public_state.get(key):
                return fail("public contract mismatch: " + key)
        mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction")
        world = ground_truth["world"]
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 500:
            return fail("missing or excessive transcript")
        started, closed, aim, misses, action_index = False, set(), None, 0, 0
        required = {w["id"] for w in world["windows"] if not w["trusted"]}
        schedule = _decision_schedule(world)
        if schedule is None:
            return fail("missing stable action schedule")
        logical_ms = 0
        for seq, e in enumerate(events, 1):
            if not isinstance(e, dict):
                return fail("invalid event")
            t = e.get("t_ms")
            expected_t = 0 if not started else logical_ms
            if (e.get("sequence") != seq or type(t) not in (int, float) or not math.isfinite(t)
                    or t != expected_t or e.get("input_source") != mode):
                return fail("invalid event identity, clock or input surface")
            if e["kind"] == "start":
                if started or seq != 1 or t != 0:
                    return fail("a challenge may start once")
                started = True
                logical_ms = schedule[0]
                continue
            if not started or closed == required:
                return fail("action outside the active episode")
            if e["kind"] in ("aim", "fire", "inspect"):
                p = e.get("point")
                if not isinstance(p, list) or len(p) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in p):
                    return fail("invalid point")
                if not (0 <= p[0] <= world["width"] and 0 <= p[1] <= world["height"]):
                    return fail("point outside desktop")
                if e["kind"] == "aim":
                    if mode != "simplified":
                        return fail("wrong aim procedure")
                    aim = p
                    continue
                if e["kind"] == "inspect":
                    if t >= world["play_time_ms"]:
                        return fail("active desktop deadline ended this episode")
                    procedure = "context_inspect" if mode == "full" else "reticle_inspect"
                    if e.get("procedure") != procedure or (mode == "simplified" and p != aim):
                        return fail("wrong inspection procedure")
                    window = pane_at(world, closed, p, t)
                    role = ("service" if window["trusted"] else "haunt") if window else "empty"
                    if e.get("window_id") != (window["id"] if window else None) or e.get("role") != role:
                        return fail("inspection disagrees with visible foreground pane")
                    # An information probe never spends a seal or closes a pane.
                    # There is no inspection quota or prerequisite for closing.
                    action_index += 1
                    if action_index >= len(schedule):
                        return fail("stable action schedule ended before completion")
                    logical_ms = schedule[action_index]
                    continue
                # The UI ends an uncleared desktop before firing at this
                # existing deadline. Replay must not accept that final shot.
                if t >= world["play_time_ms"]:
                    return fail("active desktop deadline ended this episode")
                if mode == "simplified" and p != aim:
                    return fail("proxy fired without its positioned reticle")
                outcome, window_id = hit(world, closed, p, t)
                if e.get("hit") != outcome or e.get("window_id") != window_id:
                    return fail("hit claim disagrees with visible geometry")
                if outcome == "trusted":
                    return fail("a locked service was destroyed")
                if outcome == "close":
                    closed.add(window_id)
                else:
                    misses += 1
                    if misses >= world["miss_limit"]:
                        return fail("four wasted seals ended this episode")
                if closed != required:
                    action_index += 1
                    if action_index >= len(schedule):
                        return fail("stable action schedule ended before completion")
                    logical_ms = schedule[action_index]
            else:
                return fail("unknown action; reset and retry cannot erase failure")
        final = payload.get("final_t_ms")
        if type(final) not in (int, float) or not math.isfinite(final) or final != logical_ms:
            return fail("invalid final clock")
        if sorted(closed) != payload.get("closed_ids") or misses != payload.get("misses"):
            return fail("final outcome disagrees with replay")
        passed = closed == required and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"closed {len(closed)}/{len(required)} haunted panes; {misses} wasted seals; locked services intact")
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        return fail("malformed popup transcript: " + str(exc))
