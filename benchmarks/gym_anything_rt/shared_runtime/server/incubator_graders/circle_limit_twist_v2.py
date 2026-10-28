from __future__ import annotations

import math
from typing import Any


MECHANIC_ID = "circle_limit_twist_v2"
# The renderer uses this same 1/4096-canvas-pixel grid. Closed edges belong
# to the last drawn face; integer cross products avoid Canvas backend rounding.
HIT_SCALE = 420 * 4096


def _fail(feedback: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": feedback}


def _matrix_multiply(
    left: tuple[complex, complex, complex, complex],
    right: tuple[complex, complex, complex, complex],
) -> tuple[complex, complex, complex, complex]:
    a, b, c, d = left
    e, f, g, h = right
    product = (a * e + b * g, a * f + b * h, c * e + d * g, c * f + d * h)
    # A Mobius matrix and any nonzero scalar multiple describe the same map.
    # Reversible drags otherwise accumulate an arbitrary shrinking scale and
    # can trigger the singular-view guard despite leaving the view unchanged.
    norm = max(abs(value) for value in product)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("invalid view matrix")
    return tuple(value / norm for value in product)


def _apply_view(matrix: tuple[complex, complex, complex, complex], point: complex) -> complex:
    a, b, c, d = matrix
    denominator = c * point + d
    if abs(denominator) < 1e-12:
        raise ValueError("singular view")
    return (a * point + b) / denominator


def _pan_view(view, history, start, end):
    # T(end,start) is exactly the inverse of T(start,end). Restore the saved
    # representation rather than subtracting nearly equal coefficients after
    # a long excursion toward the disk rim. No input tolerance is introduced.
    if history and start == history[-1][1] and end == history[-1][0]:
        return history.pop()[2]
    history.append((start, end, view))
    return _matrix_multiply(_translation(start, end), view)


def _phi(point: complex) -> tuple[complex, complex, complex, complex]:
    return (1.0 + 0.0j, -point, -point.conjugate(), 1.0 + 0.0j)


def _inverse_phi(point: complex) -> tuple[complex, complex, complex, complex]:
    return (1.0 + 0.0j, point, point.conjugate(), 1.0 + 0.0j)


def _translation(start: complex, end: complex) -> tuple[complex, complex, complex, complex]:
    return _matrix_multiply(_inverse_phi(end), _phi(start))


def _point(value: Any) -> complex:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("point must have two coordinates")
    point = complex(float(value[0]), float(value[1]))
    if not math.isfinite(point.real) or not math.isfinite(point.imag):
        raise ValueError("point must be finite")
    return point


def _state(value: Any, face_count: int, sides: int) -> tuple[tuple[int, ...], ...]:
    if not isinstance(value, list) or len(value) != face_count:
        raise ValueError("state has wrong face count")
    parsed = tuple(tuple(int(color) for color in face) for face in value)
    if any(len(face) != sides for face in parsed):
        raise ValueError("state has wrong sticker count")
    if any(color < 0 or color >= face_count for face in parsed for color in face):
        raise ValueError("state has invalid color")
    return parsed


def _apply_twist(
    state: tuple[tuple[int, ...], ...],
    cycles: dict[str, Any],
    face_id: int,
    direction: int,
) -> tuple[tuple[int, ...], ...]:
    next_state = [list(face) for face in state]
    definition = cycles.get(str(face_id))
    if not isinstance(definition, dict):
        raise ValueError("unknown twist face")
    for cycle_name in ("own", "ring"):
        positions = definition.get(cycle_name)
        if not isinstance(positions, list) or len(positions) != 7:
            raise ValueError("invalid twist cycle")
        parsed = [(int(position[0]), int(position[1])) for position in positions]
        values = [state[face][sector] for face, sector in parsed]
        shifted = values[-1:] + values[:-1] if direction == 1 else values[1:] + values[:1]
        for (face, sector), color in zip(parsed, shifted):
            next_state[face][sector] = color
    return tuple(tuple(face) for face in next_state)


def _solved(state: tuple[tuple[int, ...], ...]) -> bool:
    return bool(state) and all(len(set(face)) == 1 for face in state)


def noise(seed: int, index: int) -> float:
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def flow_point(spec: dict[str, Any], milliseconds: float, motor=None) -> complex:
    if motor is not None:
        elapsed=max(0.0,milliseconds-motor['anchor_time_ms'])
        pulse=1200
        if elapsed<pulse:
            n,fraction=0,elapsed/pulse
        else:
            u=(elapsed-pulse)/spec['span_ms']
            n,fraction=1+math.floor(u),u%1
        blend=fraction*fraction*(3-2*fraction)
        values=[]
        for axis in (0,1):
            seed=int(spec['seed'])+axis*7919
            base=motor['epoch']*104729
            a=motor['anchor'][axis] if n==0 else spec['amplitude']/math.sqrt(2)*noise(seed,base+n)
            b=spec['amplitude']/math.sqrt(2)*noise(seed,base+n+1)
            values.append(a+(b-a)*blend)
        return complex(*values)
    u = max(0.0, milliseconds) / spec["span_ms"]
    n, fraction = math.floor(u), u % 1
    f = fraction * fraction * (3 - 2 * fraction)
    components = []
    for dimension in (0, 1):
        seed = int(spec["seed"]) + dimension * 7919
        a, b = noise(seed, n), noise(seed, n + 1)
        components.append(spec["amplitude"] / math.sqrt(2) * (a + (b-a) * f))
    return complex(*components)


def flow_view(user_view, spec, milliseconds, motor=None):
    # The autonomous map acts in world coordinates. User steering never changes
    # the flow process and cannot stop it; every hit and aperture check uses both.
    return _matrix_multiply(user_view, _inverse_phi(flow_point(spec, milliseconds, motor)))


def _geodesic(a: complex, b: complex, f: float) -> complex:
    if f == 0:
        return a
    if f == 1:
        return b
    mapped = _apply_view(_phi(a), b)
    length = abs(mapped)
    if length < 1e-9:
        return a
    return _apply_view(_inverse_phi(a), mapped * math.tanh(f * math.atanh(min(length,.999999))) / length)


def hit_point(point):
    return (math.floor(point.real * HIT_SCALE + .5),
            math.floor(point.imag * HIT_SCALE + .5))


def face_polygon(face, view):
    vertices = [_point(p) for p in face["vertices"]]
    return [hit_point(_apply_view(view, _geodesic(a,b,k/8)))
            for a,b in zip(vertices,vertices[1:]+vertices[:1]) for k in range(8)]


def polygon_contains(polygon, point):
    inside = False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        cross = (b[0]-a[0])*(point[1]-a[1]) - (b[1]-a[1])*(point[0]-a[0])
        if (cross == 0 and min(a[0],b[0]) <= point[0] <= max(a[0],b[0])
                and min(a[1],b[1]) <= point[1] <= max(a[1],b[1])):
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            if (cross > 0) == (b[1] > a[1]):
                inside = not inside
    return inside


def face_at(puzzle, view, point):
    sampled = hit_point(point)
    for face in reversed(puzzle["faces"]):
        if polygon_contains(face_polygon(face,view),sampled):
            return int(face["id"])
    return None


def _finite_time(value, maximum):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError("invalid task time")
    return float(value)


def grade(payload: dict[str, Any], ground_truth: dict[str, Any], public_state: dict[str, Any]):
    for key in ("mechanic_id","task_id","challenge_id"):
        if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
            return _fail("stale or wrong " + key)
    if ground_truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("wrong mechanic")
    puzzle = ground_truth.get("puzzle") or {}
    if public_state.get("puzzle") != puzzle or public_state.get("control_condition") != ground_truth.get("control_condition"):
        return _fail("public contract mismatch")
    mode = (ground_truth.get("control_condition") or {}).get("interaction","full")
    if payload.get("interaction_mode") != mode or payload.get("control_condition") != ground_truth.get("control_condition"):
        return _fail("wrong interaction or control condition")
    events = payload.get("events")
    if not isinstance(events,list):
        return _fail("missing transcript")
    try:
        count = len(puzzle["faces"])
        state = _state(puzzle["initial_state"],count,7)
        user_view = (1+0j,0j,0j,1+0j)
        pan_history = []
        previous, ready, twists, selected = 0.0, 0.0, 0, None
        spent, motor = False, None
        for index,event in enumerate(events,1):
            if not isinstance(event,dict) or event.get("sequence") != index or spent:
                return _fail("invalid sequence or input after terminal failure")
            t = _finite_time(event.get("t_ms"),puzzle["play_time_ms"])
            if t >= puzzle["play_time_ms"]:
                return _fail("input at or after task time limit")
            if t < previous:
                return _fail("task clock moved backwards")
            view = flow_view(user_view,puzzle["flow"],t,motor)
            kind = event.get("kind")
            if kind == "pan":
                start_t = _finite_time(event.get("start_t_ms"),puzzle["play_time_ms"])
                a,b = _point(event["start"]),_point(event["end"])
                if (event.get("input_source") != "disc_drag" or not previous <= start_t <= t or
                    abs(a) >= .985 or abs(b) >= .985 or abs(a-b) < .001):
                    return _fail("invalid disc drag")
                user_view = _pan_view(user_view,pan_history,a,b)
            elif kind == "select":
                if mode != "simplified" or event.get("input_source") != "select_click":
                    return _fail("wrong selection surface")
                selected = face_at(puzzle,view,_point(event["point"]))
                if selected is None or event.get("face_id") != selected:
                    return _fail("selection differs from visible geometry")
            elif kind == "turn":
                face_id,direction = event.get("face_id"),event.get("direction")
                if type(face_id) is not int or not 0 <= face_id < count or type(direction) is not int or direction not in (-1,1):
                    return _fail("invalid turn")
                if mode == "full":
                    if event.get("input_source") != "canvas_turn" or face_at(puzzle,view,_point(event["point"])) != face_id:
                        return _fail("turn differs from visible geometry or input surface")
                elif mode == "simplified":
                    if event.get("input_source") != "proxy_turn" or selected != face_id:
                        return _fail("turn uses wrong selection or input surface")
                else:
                    return _fail("unknown interaction")
                distance = abs(_apply_view(view,_point(puzzle["faces"][face_id]["center"])))
                reported = float(event["focus_distance"])
                if not math.isfinite(reported) or abs(reported-distance) > 1e-5:
                    return _fail("forged aperture distance")
                accepted = distance <= puzzle["activation_radius"] and t >= ready and twists < puzzle["move_budget"]
                if event.get("accepted") is not accepted:
                    return _fail("turn acceptance contradicts aperture or detent")
                if accepted:
                    anchor=flow_point(puzzle['flow'],t,motor)
                    state = _apply_twist(state,puzzle["twist_cycles"],face_id,direction)
                    twists += 1
                    motor=dict(anchor=[anchor.real,anchor.imag],anchor_time_ms=t,epoch=twists)
                    ready = t + puzzle["twist_settle_ms"]
                    spent = twists == puzzle["move_budget"] and not _solved(state)
                if event.get("twists_after") != twists or event.get("ready_at_ms") != ready:
                    return _fail("forged actuator state")
            else:
                return _fail("unknown event")
            previous = t
        final = _finite_time(payload.get("final_t_ms"),puzzle["play_time_ms"])
        if final < previous or _state(payload.get("final_state"),count,7) != state or payload.get("twist_count") != twists:
            return _fail("final state or clock differs from replay")
        solved = _solved(state) and twists <= puzzle["move_budget"] and not spent
        if payload.get("completed") is not solved or payload.get("terminal_failure") is not (not solved):
            return _fail("terminal claim differs from replay")
        return dict(graded=True,passed=solved,score=100 if solved else 0,
            feedback=f"flowing-aperture replay {'restored' if solved else 'incomplete'}; {twists}/{puzzle['move_budget']} turns")
    except (KeyError,IndexError,ValueError,TypeError,OverflowError,ZeroDivisionError) as exc:
        return _fail(f"invalid flowing-aperture transcript: {exc}")


def cheat(public_state, ground_truth):
    del public_state
    return {"solution_moves":ground_truth.get("solution_moves",[])}
