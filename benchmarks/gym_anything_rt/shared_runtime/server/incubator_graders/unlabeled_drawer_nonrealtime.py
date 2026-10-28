"""Independent concept and stable-geometry replay. Pyodide-safe."""
from __future__ import annotations
import math

MECHANIC_ID = "unlabeled_drawer_nonrealtime"
REVISION = "moving-cabinet-3"


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def drawer_position(drawer, milliseconds):
    del milliseconds
    return [480 + drawer["amplitude"] * noise(drawer["seed"], 0), drawer["y"]]


def drawer_velocity(drawer, milliseconds):
    del drawer, milliseconds
    return 0


def cargo_position(cargo, milliseconds):
    del milliseconds
    return cargo["stable_center"]


def classify(features, rule):
    values = [int(features[i]) for i in rule["indices"]]
    if rule["family"] == "literal": code = values[0]
    elif rule["family"] == "relation": code = int(values[0] != values[1])
    elif rule["family"] == "two_bits": code = values[0]*2+values[1]
    elif rule["family"] == "two_relations": code = int(values[0] != values[1])*2+int(values[2] != values[3])
    else: raise ValueError("invalid concept")
    return rule["mapping"][code]


def inside(point, center, width, height):
    # Only representation error is allowed, never a widened visible target.
    return abs(point[0]-center[0]) <= width/2+.002 and abs(point[1]-center[1]) <= height/2+.002


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("non-finite numeric field")
    return value


def _point(value, *, allow_outside=False):
    if not isinstance(value, list) or len(value) != 2: raise ValueError("missing point")
    point = [_number(v) for v in value]
    if not allow_outside and not (0 <= point[0] <= 960 and 0 <= point[1] <= 560):
        raise ValueError("point outside task surface")
    return point


def grade(payload, truth, public):
    def fail(message): return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        if not all(isinstance(v, dict) for v in (payload, truth, public)): return fail("malformed result")
        for key in ("mechanic_id", "revision", "task_id", "challenge_id"):
            if not truth.get(key) or truth[key] != public.get(key) or truth[key] != payload.get(key):
                return fail("stale or wrong "+key)
        if truth["mechanic_id"] != MECHANIC_ID or truth["revision"] != REVISION: return fail("wrong contract")
        for key, default in (("single_attempt", None), ("episode_failed", False),
                             ("episode_failure_reason", ""), ("episode_history_error", "")):
            if public.get(key, default) != truth.get(key, default):
                return fail("public episode contract mismatch: "+key)
        if truth.get("single_attempt") is not True: return fail("wrong first-failure policy")
        if truth.get("episode_failed", False): return fail("A failed committed filing case already ended this episode.")
        if truth.get("episode_history_error", ""): return fail(str(truth["episode_history_error"]))
        for key in ("parameters", "stage", "probes", "cargo", "drawers", "probe_slot", "control_condition", "play_time_ms"):
            if truth.get(key) != public.get(key): return fail("public contract mismatch: "+key)
        mode = (truth.get("control_condition") or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode: return fail("wrong interaction")
        probes, cargo = ({v["id"]: v for v in truth[k]} for k in ("probes", "cargo"))
        drawers = {d["id"]: d for d in truth["drawers"]}
        answers = {p["id"]: classify(p["features"], truth["rule"]) for p in truth["probes"]}
        finals = {p["id"]: classify(p["features"], truth["rule"]) for p in truth["cargo"]}
        if public.get("runtime_probe_answers") != answers or public.get("runtime_final_answers") != finals:
            return fail("browser concept differs from independent rule")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 500: return fail("missing or oversized transcript")
        run_at, held, previous = None, None, -1
        filed, tested = {}, {}

        for i, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get("sequence") != i: return fail("invalid event sequence")
            time = _number(event.get("t_ms"))
            if not previous <= time <= truth["play_time_ms"]: return fail("invalid task time")
            previous = time
            kind = event.get("kind")
            if kind == "start":
                if run_at is not None or held is not None or event.get("input_source") != "start_button": return fail("invalid run start")
                run_at = time
            elif kind in ("grab", "select"):
                if event.get("input_source") != ("tab_drag" if mode == "full" else "specimen_click"):
                    return fail("wrong source input surface")
                if kind != ("grab" if mode == "full" else "select") or (mode == "full" and held is not None):
                    return fail("invalid selection gesture")
                identifier = event.get("specimen_id")
                items = probes if run_at is None else cargo
                if identifier not in items or identifier in filed: return fail("unavailable specimen")
                item = items[identifier]
                if run_at is None: center = item["center"]
                else:
                    center = cargo_position(item, 0)
                if not inside(_point(event.get("point")), center, item["width"], item["height"]):
                    return fail("selection misses visible specimen")
                held = identifier
            elif kind in ("probe", "file", "cancel", "miss", "abort"):
                expected = "tab_release" if mode == "full" else "destination_click"
                if event.get("input_source") != expected or event.get("specimen_id") != held or held is None:
                    return fail("release without matching selected specimen")
                # Pointer capture delivers releases outside the canvas. Returning
                # a tab there is harmless; successful filing still requires the
                # visible mouth and a point on the task surface.
                point = _point(event.get("point"), allow_outside=kind in ("cancel", "abort"))
                if kind == "abort":
                    if mode != "full": return fail("only a held drag can be interrupted")
                    # Pointer interruption delivers no committed release. The
                    # specimen remains on the belt and its deadline still runs.
                    held = None
                    continue
                if kind == "miss": return fail("a filing tab missed the moving cabinet")
                if kind == "cancel":
                    if run_at is not None and point[1] >= 296:
                        return fail("a cabinet release cannot be cancelled after missing a mouth")
                    held = None
                    continue
                if kind == "probe":
                    if run_at is not None or held not in probes: return fail("calibration unavailable during run")
                    slot = truth["probe_slot"]
                    if not inside(point, slot[:2], slot[2], slot[3]): return fail("probe misses visible calibration slot")
                    if event.get("drawer_id") != answers[held]: return fail("forged calibration feedback")
                    tested[held] = answers[held]
                else:
                    if run_at is None or held not in cargo: return fail("run not active")
                    target = event.get("drawer_id")
                    if type(target) is not int or target not in drawers: return fail("unknown drawer")
                    drawer = drawers[target]
                    if not inside(point, drawer_position(drawer, 0), drawer["width"], drawer["height"]):
                        return fail("release misses the stable drawer mouth")
                    if target != finals[held]: return fail("specimen filed under the wrong concept")
                    filed[held] = target
                held = None
            else: return fail("unknown control; reset and stop are unavailable")
        final_time = _number(payload.get("final_t_ms"))
        if not previous <= final_time <= truth["play_time_ms"]: return fail("invalid final time")
        if payload.get("filed") != filed or payload.get("tested") != tested: return fail("reported filing/feedback differs from replay")
        passed = (payload.get("completed") is True and run_at is not None and held is None and len(filed) == len(cargo))
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"stable-cabinet replay: {len(filed)}/{len(cargo)} specimens correctly filed")
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as error:
        return fail("invalid cabinet transcript: "+str(error))


def cheat(public_state, ground_truth):
    return dict(rule=ground_truth.get("rule"))
