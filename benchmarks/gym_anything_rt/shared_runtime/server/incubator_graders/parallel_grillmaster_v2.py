from __future__ import annotations
import math

MECHANIC_ID = "parallel_grillmaster_v2"
# Standalone browser grader: synchronized with realtime_four_motion.py by tests.
def _rt4_noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def _rt4_motion(seed, milliseconds, span=1600):
    u = max(0, milliseconds) / span
    n = math.floor(u)
    f = u - n
    a, b = _rt4_noise(seed, n), _rt4_noise(seed, n + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def _rt4_integral(seed, milliseconds, span=1600):
    u = max(0, milliseconds) / span
    n = math.floor(u)
    f = u - n
    total = sum((_rt4_noise(seed, i) + _rt4_noise(seed, i + 1)) / 2 for i in range(n))
    a, b = _rt4_noise(seed, n), _rt4_noise(seed, n + 1)
    return span * (total + a * f + (b - a) * (f**3 - f**4 / 2))


def _rt4_vector(spec, milliseconds):
    return [a * _rt4_motion(spec['seed'] + i * 7919, milliseconds, spec['span_ms'])
            for i, a in enumerate(spec['amplitude'])]


def heat(food, time):
    return time + food["heat_amplitude"] * _rt4_integral(food["heat_seed"], time, food["heat_span_ms"])


def progress(food, start, time):
    return heat(food, time) - heat(food, start)


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    for key in ("mechanic_id", "task_id", "challenge_id"):
        if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
            return fail("stale or wrong " + key)
    if ground_truth["mechanic_id"] != MECHANIC_ID:
        return fail("wrong mechanic")
    for key in ("foods", "parallel_count", "parallel_window_ms", "control_condition"):
        if ground_truth.get(key) != public_state.get(key):
            return fail("public contract mismatch: " + key)
    mode = (ground_truth.get("control_condition") or {}).get("interaction", "full")
    if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode:
        return fail("wrong interaction")
    foods = {f["id"]: f for f in ground_truth["foods"]}
    events = payload.get("events")
    if not isinstance(events, list) or len(events) != 2 * len(foods):
        return fail("every food requires one start and one serve")
    starts, served, previous = {}, set(), -1
    try:
        for index, event in enumerate(events, 1):
            t = event["t_ms"]
            if (type(t) not in (int, float) or not math.isfinite(t) or
                not previous <= t <= 600000 or event.get("sequence") != index or
                event.get("input_source") != mode or event.get("food_id") not in foods):
                return fail("invalid action sequence, time or input")
            previous = t
            for food_id, start in starts.items():
                if food_id not in served and progress(foods[food_id], start, t) > foods[food_id]["target_ms"] + foods[food_id]["tolerance_ms"]:
                    return fail("a burnt food ended this attempt")
            if starts and len(starts) < ground_truth["parallel_count"] and t-min(starts.values()) > ground_truth["parallel_window_ms"]:
                return fail("concurrent start window missed")
            food_id = event["food_id"]
            if mode == "full":
                a, b = event.get("start_point"), event.get("end_point")
                if not isinstance(a, list) or not isinstance(b, list) or len(a) != 2 or len(b) != 2 or math.dist(a,b) < 5:
                    return fail("food transfer requires a drag")
            if event["kind"] == "start" and food_id not in starts:
                starts[food_id] = t
            elif event["kind"] == "serve" and food_id in starts and food_id not in served:
                food = foods[food_id]
                if abs(progress(food, starts[food_id], t) - food["target_ms"]) > food["tolerance_ms"]:
                    return fail("food served outside golden window")
                served.add(food_id)
            else:
                return fail("reset, duplicate or invalid food transfer")
        earliest = sorted(starts.values())[:ground_truth["parallel_count"]]
        if len(earliest) > 1 and earliest[-1] - earliest[0] > ground_truth["parallel_window_ms"]:
            return fail("concurrent start window missed")
        if served != set(foods) or payload.get("completed") is not True:
            return fail("dinner rush incomplete")
        return dict(graded=True, passed=True, score=100, feedback=f"variable-heat replay: all {len(foods)} foods served")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return fail("invalid grill transcript: " + str(exc))


def cheat(public_state, ground_truth):
    return {"foods": ground_truth.get("foods", [])}
