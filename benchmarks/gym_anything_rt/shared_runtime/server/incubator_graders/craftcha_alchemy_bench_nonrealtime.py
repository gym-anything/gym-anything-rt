"""Independent material/geometry/time replay. No completed bit is authoritative.

Only standard-library imports so the same file runs in pinned Pyodide.
"""
from __future__ import annotations
import math

MECHANIC_ID = "craftcha_alchemy_bench_nonrealtime"
SURFACES = {"full": ("pointer_down", "pointer_up"), "simplified": ("select_click", "place_click")}


def noise(seed, index):
    value = (int(seed) ^ ((index + 1) * 0x9E3779B9)) & 0xffffffff
    value = ((value ^ (value >> 16)) * 0x85EBCA6B) & 0xffffffff
    value = ((value ^ (value >> 13)) * 0xC2B2AE35) & 0xffffffff
    return ((value ^ (value >> 16)) & 0xffffffff) / 4294967295 * 2 - 1


def position(lot, milliseconds):
    phase = max(0, milliseconds) / lot["span_ms"]
    knot = math.floor(phase)
    f = phase - knot
    smooth = f*f*(3-2*f)
    return [center + amplitude * (noise(lot["motion_seed"] + axis*7919, knot) * (1-smooth)
            + noise(lot["motion_seed"] + axis*7919, knot+1) * smooth)
            for axis, (center, amplitude) in enumerate(zip(lot["center"], lot["amplitude"]))]


def _point(value, stage):
    return (isinstance(value, list) and len(value) == 2 and
            all(type(v) in (int, float) and math.isfinite(v) for v in value) and
            0 <= value[0] <= stage["width"] and 0 <= value[1] <= stage["height"])


def hit(items, point, t, contract, exclude=None):
    radius = contract["parameters"]["radius"]
    matches = [item["id"] for item in items.values() if item["id"] != exclude and
               math.dist(point, position(contract["lots"][item["lot"]], t)) <= radius + 1e-7]
    return matches[0] if len(matches) == 1 else None


def expired(items, time, contract):
    return next((item["id"] for item in items.values() if contract["materials"][item["id"]]["hot"] and
                 time - item["born_ms"] > contract["parameters"]["hot_lifetime_ms"]), None)


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    if not all(isinstance(x, dict) for x in (payload, ground_truth, public_state)):
        return fail("Missing alchemy contract")
    for key in ("mechanic_id", "task_id", "challenge_id", "revision"):
        if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
            return fail("Stale or mismatched " + key)
    if ground_truth["mechanic_id"] != MECHANIC_ID:
        return fail("Wrong mechanic")
    for key in ("parameters", "lots", "materials", "initial", "recipes", "goal", "stage", "forecast_ms", "trail_ms", "formation_ms", "action_step_ms", "play_time_ms", "max_events", "control_condition"):
        if public_state.get(key) != ground_truth.get(key):
            return fail("Public/private alchemy mismatch: " + key)
    mode = ground_truth.get("control_condition", {}).get("interaction")
    if mode not in SURFACES or payload.get("interaction_mode") != mode:
        return fail("Wrong interaction mode")
    events = payload.get("events")
    if not isinstance(events, list) or not 2 <= len(events) <= ground_truth["max_events"]:
        return fail("Missing or excessive input trace")
    items = {i["id"]: dict(i) for i in ground_truth["initial"]}
    held, previous, clock, started, submitted, won = None, -1, 0, False, False, False
    recipe_map = {tuple(sorted(r["inputs"])): r["output"] for r in ground_truth["recipes"]}
    try:
        for sequence, event in enumerate(events, 1):
            if not isinstance(event, dict):
                return fail("Malformed input event")
            t = event.get("t_ms")
            if (event.get("sequence") != sequence or type(t) not in (int, float) or not math.isfinite(t) or
                not previous <= t <= ground_truth["play_time_ms"] or t != clock or submitted):
                return fail("Invalid event order or task clock")
            previous = t
            kind = event.get("kind")
            if kind == "start":
                if started or sequence != 1 or t != 0 or event.get("input_surface") != "start_button":
                    return fail("Invalid active-run boundary")
                started = True
                continue
            if not started:
                return fail("Crafting before starting is unavailable")
            if expired(items, t, ground_truth):
                return fail("A hot intermediate crystallized; this attempt ended")
            if kind in ("pick", "probe"):
                point = event.get("point")
                if held is not None or won or event.get("input_surface") != SURFACES[mode][0] or not _point(point, ground_truth["stage"]):
                    return fail("Invalid reagent selection")
                selected = hit(items, point, t, ground_truth)
                if selected != event.get("material_id") or (kind == "probe") != (selected is None):
                    return fail("Selection disagrees with the moving visible circle")
                held = selected
            elif kind == "drop":
                point = event.get("point")
                if held is None or event.get("input_surface") != SURFACES[mode][1] or not _point(point, ground_truth["stage"]):
                    return fail("Invalid placement surface")
                target = hit(items, point, t, ground_truth, held)
                if target is None or target != event.get("target_id"):
                    return fail("Spill: release missed the moving reagent")
                if any(ground_truth["materials"][key]["hot"] and t-items[key]["born_ms"] < ground_truth["formation_ms"] for key in (held,target)):
                    return fail("Premature merge shattered a forming blend")
                output = recipe_map.get(tuple(sorted((held, target))))
                if output is None or event.get("output_id") != output:
                    return fail("Wrong mixture destroyed material lineage")
                lot = items[target]["lot"]
                del items[held]
                del items[target]
                items[output] = dict(id=output, lot=lot, born_ms=t)
                held = None
                won = len(items) == 1 and output == ground_truth["goal"]
                if not won:
                    clock = min(ground_truth["play_time_ms"], t + ground_truth["action_step_ms"])
            elif kind == "submit":
                if event.get("input_surface") != "certify_button":
                    return fail("Invalid certification surface")
                submitted = True
                if not won or held is not None:
                    return fail("Heart not crafted")
            else:
                return fail("Terminal failure or unsupported control")
        final = payload.get("final_t_ms")
        if type(final) not in (int, float) or not math.isfinite(final) or final != previous:
            return fail("Final task time differs from the final input")
        expected = sorted(items.values(), key=lambda i: i["id"])
        if payload.get("final_inventory") != expected:
            return fail("Claimed lineage differs from independent replay")
        if not submitted or not won or payload.get("completed") is not True:
            return fail("Heart not certified")
        return dict(graded=True, passed=True, score=100, feedback="Stormglass heart certified by coordinate, lifetime and recipe replay")
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as error:
        return fail("Invalid alchemy transcript: " + str(error))


def cheat(public_state, ground_truth):
    return {"recipes": ground_truth.get("recipes", [])}
