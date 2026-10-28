from __future__ import annotations

import math
from typing import Any

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


def fruit_position(truth, apple, ms):
    return [p + d for p, d in zip(apple['position'], _rt4_vector(truth['wind'][apple['id']], ms))]


class HarvestPhysics:
    """Fixed-step gravity, wind and a speed-limited basket, replayed from input."""
    def __init__(self, truth):
        self.truth, self.spec = truth, truth['flight']
        self.ms = 0
        self.x = truth['basket']['x'] + truth['basket']['width']/2
        self.target, self.velocity = self.x, 0.0
        self.falling, self.released, self.caught = {}, set(), set()
        self.failed = ''

    def release(self, apple, angle, ms):
        center = _project(fruit_position(self.truth, apple, ms), angle)
        before = _project(fruit_position(self.truth, apple, max(0, ms-20)), angle)
        self.released.add(apple['id'])
        if apple['id'] not in self.truth['attached_ids']:
            self.failed = 'A false stem was plucked.'
        self.falling[apple['id']] = dict(x=center[0], y=center[1],
            vx=max(-190, min(190, (center[0]-before[0])*50)), vy=0.0, radius=apple['radius'])

    def advance(self, end_ms):
        while self.ms + 10 <= end_ms and not self.failed:
            self.ms += 10
            previous_x = self.x
            a = max(-self.spec['basket_acceleration'], min(self.spec['basket_acceleration'],
                (self.target-self.x)*60-self.velocity*14))
            self.velocity = max(-self.spec['basket_speed'], min(self.spec['basket_speed'], self.velocity+a*.01))
            half = self.truth['basket']['width']/2
            self.x = max(half+12, min(948-half, self.x+self.velocity*.01))
            if self.x in (half+12, 948-half):
                self.velocity = 0
            wind = self.spec['wind_acceleration']*_rt4_motion(
                self.spec['seed'], self.ms, self.spec['wind_span_ms'])
            for key, fruit in list(self.falling.items()):
                x, y, r = fruit['x'], fruit['y'], fruit['radius']
                fruit['vx'] += (wind-.1*fruit['vx'])*.01
                fruit['vy'] += self.spec['gravity']*.01
                fruit['x'] += fruit['vx']*.01
                fruit['y'] += fruit['vy']*.01
                if fruit['x'] < r+12 or fruit['x'] > 948-r:
                    fruit['x'] = max(r+12, min(948-r, fruit['x']))
                    fruit['vx'] *= -.6
                rim = self.spec['rim_y']
                if y+r < rim <= fruit['y']+r:
                    fraction = (rim-r-y)/(fruit['y']-y)
                    impact = x+(fruit['x']-x)*fraction
                    basket = previous_x+(self.x-previous_x)*fraction
                    if abs(impact-basket)+r <= half:
                        self.caught.add(key)
                        del self.falling[key]
                    else:
                        self.failed = 'A falling fruit missed the basket.'
                        break


MECHANIC_ID = "surreal_apple_on_tree_grid_nonrealtime"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "score": 0, "feedback": message}


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} is not finite")
    return float(value)


def _point(value: Any, width: int, height: int, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} is malformed")
    x, y = _number(value[0], f"{label} x"), _number(value[1], f"{label} y")
    if not 0 <= x <= width or not 0 <= y <= height:
        raise ValueError(f"{label} leaves the orchard")
    return x, y


def _project(point: list[float], angle_deg: float) -> tuple[float, float]:
    angle = math.radians(angle_deg)
    x, y, z = (float(item) for item in point)
    return 430 + x * math.cos(angle) + z * math.sin(angle), 246 + y + 0.10 * z * math.cos(angle) - 0.05 * x * math.sin(angle)


def _inside(point: tuple[float, float], rect: dict[str, Any]) -> bool:
    return (
        float(rect["x"]) <= point[0] <= float(rect["x"]) + float(rect["width"])
        and float(rect["y"]) <= point[1] <= float(rect["y"]) + float(rect["height"])
    )


def _sector(angle: float) -> int:
    if angle < -36: return 0
    if angle < -12: return 1
    if angle < 12: return 2
    if angle < 36: return 3
    return 4


def _explored(angles: list[float], sectors: set[int], requirements: dict[str, Any]) -> bool:
    return (
        max(angles) - min(angles) >= float(requirements["minimum_orbit_span_deg"])
        and sum(abs(b - a) for a, b in zip(angles, angles[1:])) >= float(requirements["minimum_orbit_travel_deg"])
        and len(sectors) >= int(requirements["minimum_view_sectors"])
    )


def grade(payload: dict[str, Any], ground_truth: dict[str, Any], public_state: dict[str, Any]) -> dict[str, Any]:
    challenge = str(ground_truth.get("challenge_id") or "")
    task_id = str(ground_truth.get("task_id") or "")
    if any(str(item.get("mechanic_id") or "") != MECHANIC_ID for item in (payload, ground_truth, public_state)):
        return _fail("mechanic mismatch")
    if not challenge or str(payload.get("challenge_id") or "") != challenge or str(public_state.get("challenge_id") or "") != challenge:
        return _fail("stale orchard challenge")
    if not task_id or str(payload.get("task_id") or "") != task_id or str(public_state.get("task_id") or "") != task_id:
        return _fail("task identity mismatch")
    try:
        condition = dict(ground_truth.get("control_condition") or {})
        if dict(public_state.get("control_condition") or {}) != condition:
            raise ValueError("public control condition differs from replay contract")
        interaction = str(condition.get("interaction") or "full")
        if interaction not in {"simplified", "full"}:
            raise ValueError("interaction condition is unsupported")
        stage = dict(ground_truth["stage"])
        width, height = int(stage["width"]), int(stage["height"])
        limit = float(ground_truth["view_limit_deg"])
        basket = dict(ground_truth["basket"])
        requirements = dict(ground_truth["requirements"])
        apples = [dict(item) for item in ground_truth["apples"]]
        apple_by_id = {str(item["id"]): item for item in apples}
        attached = {str(item) for item in ground_truth["attached_ids"]}
        if not 3 <= len(apples) <= 9 or len(apple_by_id) != len(apples) or not 1 <= len(attached) < len(apples) or not attached <= set(apple_by_id):
            raise ValueError("fruit contract is incomplete")
        for key in ("stage", "basket", "requirements", "apples", "branches", "wind", "flight"):
            if public_state.get(key) != ground_truth.get(key):
                raise ValueError(f"public {key} differs from replay contract")
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"invalid parallax contract: {exc}")

    events = payload.get("events")
    if not isinstance(events, list) or not (1 <= len(events) <= 1600):
        return _fail("orchard transcript is missing or outside limits")
    angle = float(public_state.get("initial_angle_deg") or 0)
    angles = [angle]
    sectors = {_sector(angle)}
    orbit_samples = 0
    orbit: dict[str, Any] | None = None
    basket_hold = False
    physics = HarvestPhysics(ground_truth)
    if payload.get('physics_revision') != 'falling-harvest-v1':
        return _fail('wrong harvest physics revision')
    invalid_plucks = reset_count = seal_count = 0
    strike_active = False
    previous_ms = -1

    for sequence, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("sequence") != sequence:
            return _fail(f"event {sequence} has invalid sequence")
        kind = str(event.get("kind") or "")
        try:
            ms = _number(event.get('t_ms'), 'event time')
            if not previous_ms <= ms <= 600000:
                return _fail('invalid event time')
            previous_ms = ms
            physics.advance(ms)
            if physics.failed:
                return _fail(physics.failed)
            if kind == "orbit_start":
                if interaction != "full" or event.get("input_source") != "canvas_drag":
                    return _fail(f"event {sequence} uses the wrong orbit interaction")
                if orbit is not None or basket_hold or physics.falling:
                    return _fail(f"event {sequence} overlaps a pointer hold")
                point = _point(event.get("point"), width, height, "orbit start")
                before = _number(event.get("angle_before"), "orbit angle")
                if abs(before - angle) > 0.02:
                    return _fail(f"event {sequence} starts from a stale view")
                orbit = {"start": point, "angle": angle, "last": point}
            elif kind == "orbit_move":
                if interaction != "full" or event.get("input_source") != "canvas_drag":
                    return _fail(f"event {sequence} uses the wrong orbit interaction")
                if orbit is None or basket_hold or physics.falling:
                    return _fail(f"event {sequence} moves no active orbit")
                point = _point(event.get("point"), width, height, "orbit move")
                expected = max(-limit, min(limit, orbit["angle"] + (point[0] - orbit["start"][0]) * 0.24))
                after = _number(event.get("angle_after"), "orbit result")
                if abs(after - expected) > 0.03:
                    return _fail(f"event {sequence} reports false parallax")
                angle = after
                orbit["last"] = point
                orbit_samples += 1
                angles.append(angle)
                sectors.add(_sector(angle))
            elif kind == "orbit_end":
                if interaction != "full" or event.get("input_source") != "canvas_drag":
                    return _fail(f"event {sequence} uses the wrong orbit interaction")
                if orbit is None:
                    return _fail(f"event {sequence} ends no active orbit")
                _point(event.get("point"), width, height, "orbit end")
                if abs(_number(event.get("angle"), "final orbit angle") - angle) > 0.03:
                    return _fail(f"event {sequence} ends at a false view")
                orbit = None
            elif kind == "orbit_step":
                if interaction != "simplified" or event.get("input_source") != "orbit_buttons":
                    return _fail(f"event {sequence} uses the wrong orbit interaction")
                if orbit is not None or basket_hold or physics.falling:
                    return _fail(f"event {sequence} overlaps a pointer hold")
                before = _number(event.get("angle_before"), "orbit angle")
                after = _number(event.get("angle_after"), "orbit result")
                if abs(before - angle) > 0.02:
                    return _fail(f"event {sequence} starts from a stale view")
                possible = {max(-limit, min(limit, angle - 6)), max(-limit, min(limit, angle + 6))}
                if not any(abs(after - candidate) <= 0.03 for candidate in possible):
                    return _fail(f"event {sequence} reports a false orbit button step")
                angle = after
                orbit_samples += 1
                angles.append(angle)
                sectors.add(_sector(angle))
            elif kind == 'release':
                source = 'fruit_pluck' if interaction == 'full' else 'fruit_click'
                if event.get('input_source') != source or orbit or basket_hold:
                    return _fail('wrong plucking interaction')
                if not _explored(angles, sectors, requirements):
                    return _fail('inspect the orchard before harvesting')
                apple_id = str(event.get('apple_id') or '')
                if apple_id not in apple_by_id or apple_id in physics.released:
                    return _fail('fruit is unavailable')
                point = _point(event.get('point'), width, height, 'pluck point')
                candidates = []
                radians = math.radians(angle)
                for apple in apples:
                    if apple['id'] in physics.released:
                        continue
                    position = fruit_position(ground_truth, apple, ms)
                    if math.dist(point, _project(position, angle)) <= apple['radius']+8.01:
                        candidates.append((position[2]*math.cos(radians)-position[0]*math.sin(radians), apple['id']))
                if not candidates or max(candidates)[1] != apple_id:
                    return _fail('pluck does not hit the frontmost visible fruit')
                physics.release(apple_by_id[apple_id], angle, ms)
                if physics.failed:
                    return _fail(physics.failed)
            elif kind in ('basket_start', 'basket_move', 'basket_end', 'basket_target'):
                point = _point(event.get('point'), width, height, 'basket control')
                source = 'basket_drag' if interaction == 'full' else 'basket_click'
                if orbit or event.get('input_source') != source:
                    return _fail('wrong basket interaction')
                if kind == 'basket_target':
                    if interaction != 'simplified' or point[1] < 430:
                        return _fail('click the basket rail')
                elif interaction != 'full':
                    return _fail('basket drag is full interaction only')
                elif kind == 'basket_start':
                    if basket_hold or not _inside(point, dict(basket, x=physics.x-basket['width']/2)):
                        return _fail('drag must start on the basket')
                    basket_hold = True
                elif not basket_hold:
                    return _fail('basket is not held')
                if kind in ('basket_move', 'basket_target'):
                    physics.target = point[0]
                if kind == 'basket_end':
                    basket_hold = False
            elif kind == "reset":
                return _fail('harvest resets are unavailable')
            elif kind == "seal":
                if orbit is not None:
                    return _fail(f"event {sequence} seals during a pointer hold")
                seal_count += 1
            else:
                return _fail(f"event {sequence} has unknown kind {kind!r}")
        except (TypeError, ValueError) as exc:
            return _fail(f"event {sequence}: {exc}")

    travel = round(sum(abs(b - a) for a, b in zip(angles, angles[1:])), 2)
    span = round(max(angles) - min(angles), 2)
    expected = {
        "final_angle_deg": round(angle, 2),
        "orbit_samples": orbit_samples,
        "orbit_span_deg": span,
        "orbit_travel_deg": travel,
        "view_sector_count": len(sectors),
        "plucked_ids": sorted(physics.caught),
        "invalid_plucks": invalid_plucks,
        "reset_count": reset_count,
        "seal_count": seal_count,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            return _fail(f"submitted {key} does not match orchard replay")
    passed = (
        payload.get("completed") is True
        and orbit is None
        and not strike_active
        and physics.caught == attached
        and not physics.falling
        and seal_count >= 1
        and _explored(angles, sectors, requirements)
    )
    return {
        "graded": True,
        "passed": passed,
        "score": 100 if passed else 0,
        "feedback": f"falling harvest replay: caught {len(physics.caught)}/{len(attached)}; span {span}°; bad plucks {invalid_plucks}; resets {reset_count}",
    }


def cheat(public_state: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    del public_state
    return {"attached_ids": ground_truth.get("attached_ids") or [], "answers": []}
