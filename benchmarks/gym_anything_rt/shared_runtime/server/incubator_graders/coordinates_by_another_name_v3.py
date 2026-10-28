"""Independent replay of addressed sonar inspections and timed torpedo impacts."""
from __future__ import annotations
import math

MECHANIC_ID = "coordinates_by_another_name_v3"


def position(world, ship, time):
    u = max(0, time) / world["parameters"]["span_ms"]
    n = min(math.floor(u), len(ship["knots"])-2)
    f = min(1, u-n)
    f = f*f*(3-2*f)
    return [a+(b-a)*f for a, b in zip(ship["knots"][n], ship["knots"][n+1])]


def options(world):
    return [sorted(world["bands"]), list("ABC"), list(range(1,world["columns"]+1))]


def resolve(world, indices):
    opts = options(world)
    designation = [opts[a][indices[a]] for a in range(3)]
    return next((c for c in world["cells"] if [c["band"], c["block"], c["count"]] == designation), None)


def sonar_sector(world, band, block):
    """The whole labelled bracket, including voids; COUNT only aims torpedoes."""
    run = next(r for r in world["runs"] if r["band"] == band and r["block"] == block)
    cw, rh = 768 / world["columns"], 312 / world["rows"]
    return [48 + run["start"] * cw, 24 + run["row"] * rh,
            run["width"] * cw, rh]


def sonar_contacts(world, band, block, time):
    """Return hulls whose visible compartment circles touch this sector now."""
    x, y, width, height = sonar_sector(world, band, block)
    contacts = []
    for ship in world["fleet"]:
        center = position(world, ship, time)
        for offset in ship["offsets"]:
            px, py = [center[a] + offset[a] for a in range(2)]
            closest = [min(x + width, max(x, px)), min(y + height, max(y, py))]
            if math.dist([px, py], closest) <= ship["radius"]:
                contacts.append(ship["id"])
                break
    return sorted(contacts)


def impact(world, cell, time, damaged):
    hits, protected = [], False
    radius = world["parameters"]["blast_radius"]
    for ship in world["fleet"]:
        center = position(world, ship, time)
        for part, offset in enumerate(ship["offsets"]):
            key = f'{ship["id"]}:{part}'
            # Flooded compartments cease to be targets, but a protected hull
            # always remains a physical obstacle even beneath hostile outlines.
            if key in damaged:
                continue
            point = [center[a]+offset[a] for a in range(2)]
            if math.dist(point, [cell["x"], cell["y"]]) <= radius+ship["radius"]:
                if ship["protected"]:
                    protected = True
                else:
                    hits.append(key)
    return sorted(hits), protected


def target_parts(world):
    return {f'{s["id"]}:{i}' for s in world["fleet"] if not s["protected"] for i in range(len(s["offsets"]))}


def _point(value):
    return isinstance(value, list) and len(value) == 2 and all(type(x) in (int, float) and math.isfinite(x) for x in value)


def valid_drag(event, count, index):
    a, b = event.get("start"), event.get("release")
    if not _point(a) or not _point(b) or math.hypot(a[0]-84, a[1]-84) > 43 or math.dist(a, b) < 8:
        return False
    delta = (math.degrees(math.atan2(b[1]-84, b[0]-84))+210) % 360
    half = 120/(count-1)
    if not 24 <= math.hypot(b[0]-84, b[1]-84) <= 86 or 240+half < delta < 360-half:
        return False
    delta = 0 if delta >= 360-half else min(240, delta)
    return int(math.floor(delta/240*(count-1)+.5)) == index


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(x, dict) for x in (payload, ground_truth, public_state)):
            return fail("malformed envelope")
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("identity mismatch: " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("world", "control_condition", "episode_failed"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("world/condition commitment mismatch")
        if ground_truth.get("episode_failed"):
            return fail("a failed submission already ended this episode")
        world = ground_truth["world"]
        mode = ground_truth["control_condition"]["interaction"]
        if payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 4000:
            return fail("invalid action tape")
        final_t = payload.get("final_t_ms")
        if type(final_t) not in (int, float) or not math.isfinite(final_t) or not 0 <= final_t <= world["play_time_ms"]:
            return fail("invalid final time")
        indices = [0, 0, 0]
        opts = options(world)
        previous = 0
        started, pending, failed = False, None, False
        damaged = set()
        shots = 0

        def settle(time):
            nonlocal pending, failed
            if pending and pending["at"] <= time:
                hits, protected = impact(world, pending["cell"], pending["at"], damaged)
                if protected or not hits:
                    failed = True
                else:
                    damaged.update(hits)
                pending = None

        for sequence, e in enumerate(events, 1):
            if not isinstance(e, dict):
                return fail("invalid event: expected an object")
            t = e.get("t_ms")
            if (e.get("sequence") != sequence or type(t) not in (int, float) or not math.isfinite(t)
                    or not previous <= t <= final_t):
                return fail("invalid event sequence/time")
            previous = t
            if not started and t != 0:
                return fail("preparation time must be frozen")
            settle(t)
            if failed or damaged == target_parts(world):
                return fail("input after terminal impact")
            if started and t >= world["play_time_ms"]:
                return fail("input after watch timeout")
            kind = e.get("action")
            if kind == "select":
                axis, index = e.get("axis"), e.get("index")
                if type(axis) is not int or axis not in range(3) or type(index) is not int or index not in range(len(opts[axis])):
                    return fail("invalid selector")
                if e.get("input_source") != ("rotary_drag" if mode == "full" else "value_button"):
                    return fail("wrong selection surface")
                if mode == "full" and not valid_drag(e, len(opts[axis]), index):
                    return fail("rotary geometry mismatch")
                indices[axis] = index
            elif kind == "scan":
                if e.get("input_source") != "scan_button":
                    return fail("wrong sonar surface")
                sector = [opts[a][indices[a]] for a in range(2)]
                if e.get("sector") != sector:
                    return fail("sonar sector differs from console designation")
                if e.get("contacts") != sonar_contacts(world, *sector, t):
                    return fail("sonar contacts differ from physical inspection")
            elif kind == "start":
                if started or e.get("input_source") != "start_button" or t != 0:
                    return fail("invalid start/restart")
                started = True
            elif kind == "fire":
                if not started or pending or e.get("input_source") != "fire_button":
                    return fail("torpedo launcher unavailable")
                cell = resolve(world, indices)
                if cell is None:
                    return fail("shot at void chart cell")
                if e.get("designation") != [opts[a][indices[a]] for a in range(3)]:
                    return fail("shot differs from console designation")
                # Scanning is an information affordance, never a mandatory quota.
                pending = dict(cell=cell, at=t+world["parameters"]["flight_ms"])
                shots += 1
            else:
                return fail("unknown input")
        settle(final_t)
        timed_out = started and final_t == world["play_time_ms"] and damaged != target_parts(world)
        failed = failed or timed_out
        final = dict(damaged=sorted(damaged), shots=shots, failed=failed)
        if payload.get("final") != final:
            return fail("final claim differs from physical replay")
        passed = started and not failed and pending is None and damaged == target_parts(world) and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"{len(damaged)}/{len(target_parts(world))} hostile compartments flooded; {shots} torpedoes" + ("; watch timeout" if timed_out else "; terminal miss/protected hit" if failed else ""))
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as error:
        return fail("invalid sonar transcript: " + str(error))
