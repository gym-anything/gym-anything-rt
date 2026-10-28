from __future__ import annotations

import copy
import hashlib
import json
import random
from typing import Any


MECHANIC_ID = "five_second_rule"
COLORS = (
    ("CORAL", "#f36f5b"),
    ("TEAL", "#37c7b3"),
    ("AMBER", "#f0bb4f"),
    ("VIOLET", "#9178e8"),
    ("ICE", "#73c8e8"),
    ("LIME", "#a8d95e"),
    ("ROSE", "#e7789f"),
)
SHAPES = ("RING", "KITE", "BOLT", "CROWN", "BLOOM", "CHEVRON", "MOON")
MARKS = ("PLAIN", "STRIPED", "DOTTED", "SPLIT", "HATCHED", "RINGED")
TOKEN_ACTION_WIDTH = 86
TOKEN_ACTION_HEIGHT = 92
DIRECTIONS = {
    "NORTH": (0, -1, 0),
    "EAST": (1, 0, 90),
    "SOUTH": (0, 1, 180),
    "WEST": (-1, 0, 270),
}


def _condition(task: dict[str, Any]) -> dict[str, Any] | None:
    value = task.get("_control_condition")
    return copy.deepcopy(value) if isinstance(value, dict) else None


def _parameters(task: dict[str, Any]) -> dict[str, Any]:
    condition = _condition(task)
    if condition:
        return copy.deepcopy(condition["difficulty_parameters"])
    return {
        "round_duration_ms": 5000,
        "object_count": 6,
        "gate_half_width": 35,
        "motion_speed": 132,
        "vertical_amplitude": 27,
        "hold_duration_ms": 610,
        "hold_tolerance_ms": 150,
        "flick_angle_tolerance_deg": 21,
        "flick_min_travel_px": 54,
        "relay_relation_depth": 3,
        "bay_open_ms": 840,
        "bay_period_ms": 2000,
        "bay_radius": 49,
    }


def _validate(parameters: dict[str, Any]) -> None:
    bounds = {
        "round_duration_ms": (5000, 5000),
        "object_count": (3, 7),
        "gate_half_width": (24, 70),
        "motion_speed": (80, 170),
        "vertical_amplitude": (8, 40),
        "hold_duration_ms": (420, 720),
        "hold_tolerance_ms": (90, 330),
        "flick_angle_tolerance_deg": (12, 48),
        "flick_min_travel_px": (30, 70),
        "relay_relation_depth": (0, 4),
        "bay_open_ms": (620, 1500),
        "bay_period_ms": (1800, 2400),
        "bay_radius": (38, 82),
    }
    if set(parameters) != set(bounds):
        raise ValueError("five-second parameter set is incomplete")
    for key, (low, high) in bounds.items():
        value = parameters[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{key} must be an integer in [{low}, {high}]")
    if parameters["bay_open_ms"] >= parameters["bay_period_ms"]:
        raise ValueError("bay open interval must be shorter than its period")


def _tokens(rng: random.Random, count: int, *, shared_mark_pair: bool = False) -> list[dict[str, Any]]:
    colors = rng.sample(list(COLORS), count)
    shapes = rng.sample(list(SHAPES), count)
    positions = [
        (150, 128), (330, 115), (510, 132), (690, 116),
        (220, 300), (420, 305), (620, 292),
    ]
    rng.shuffle(positions)
    marks = list(MARKS)
    rng.shuffle(marks)
    output = []
    for index in range(count):
        color_name, color_hex = colors[index]
        x, y = positions[index]
        output.append({
            "id": f"token-{index + 1}",
            "color": color_name,
            "color_hex": color_hex,
            "shape": shapes[index],
            "mark": marks[index % len(marks)],
            "x": x,
            "y": y,
        })
    if shared_mark_pair and count >= 2:
        # Relay wording asks for THE other token with the first token's mark.
        # There must therefore be exactly one such token even at L5, where
        # seven tokens otherwise cycle through the six available marks.
        pair_mark = marks[0]
        output[0]["mark"] = pair_mark
        output[1]["mark"] = pair_mark
        for index in range(2, count):
            output[index]["mark"] = marks[index - 1]
    return output


def _label(token: dict[str, Any]) -> str:
    return f'{token["color"]} {token["shape"]}'


def _gate_round(rng: random.Random, parameters: dict[str, Any]) -> dict[str, Any]:
    tokens = _tokens(rng, parameters["object_count"])
    target = rng.choice(tokens)
    gate_x = rng.choice((382, 410, 438))
    direction = rng.choice((-1, 1))
    target_speed = parameters["motion_speed"] * direction
    target_cross_ms = rng.randint(1450, 1680)
    target_y = rng.randint(180, 266)
    safe_cross_positions = iter((60, 150, 240, 600, 690, 780))
    for index, token in enumerate(tokens):
        if token is target:
            speed = target_speed
            x0 = gate_x - speed * target_cross_ms / 1000
            y0 = target_y
        else:
            # Keep every distractor moving and initially visible, but place it
            # away from the capture gate at the target's crossing instant.
            # Otherwise a later-painted distractor can cover the instructed
            # token and receive a physically correct center click.
            cross_x = next(safe_cross_positions)
            sign = -1 if cross_x < gate_x else 1
            speed = parameters["motion_speed"] * rng.uniform(.78, 1.12) * sign
            x0 = cross_x - speed * target_cross_ms / 1000
            y0 = rng.randint(112, 330)
        token["motion"] = {
            "x0": round(x0, 3),
            "y0": y0,
            "vx": round(speed, 3),
            "amplitude": parameters["vertical_amplitude"],
            "period_ms": rng.randint(1250, 1950),
            "phase": round(rng.uniform(0, 6.283185), 6),
        }
    return {
        "family": "gate_tag",
        "instruction": [f"FOLLOW THE {_label(target)}.", "TAG IT WHILE ITS CENTER IS INSIDE THE WHITE GATE."],
        "tokens": tokens,
        "gate": {"x": gate_x, "half_width": parameters["gate_half_width"]},
        "predicate": {"target_id": target["id"]},
    }


def _hold_round(rng: random.Random, parameters: dict[str, Any]) -> dict[str, Any]:
    tokens = _tokens(rng, parameters["object_count"])
    target = rng.choice(tokens)
    cue_start = rng.randint(1420, 1570)
    cue_end = cue_start + parameters["hold_duration_ms"]
    return {
        "family": "sync_hold",
        "instruction": [f"HOLD THE {_label(target)} WHEN BOTH NEEDLES ENTER THE NOTCH.", "RELEASE WHEN THE NOTCH FLASHES AMBER."],
        "tokens": tokens,
        "cue": {"start_ms": cue_start, "end_ms": cue_end, "tolerance_ms": parameters["hold_tolerance_ms"]},
        "predicate": {"target_id": target["id"]},
    }


def _opposite(direction: str) -> str:
    names = list(DIRECTIONS)
    return names[(names.index(direction) + 2) % 4]


def _flick_round(rng: random.Random, parameters: dict[str, Any]) -> dict[str, Any]:
    tokens = _tokens(rng, parameters["object_count"])
    target = rng.choice(tokens)
    face_direction = rng.choice(tuple(DIRECTIONS))
    direct_direction = rng.choice(tuple(DIRECTIONS))
    nested = parameters["relay_relation_depth"] >= 4
    flick_direction = _opposite(face_direction) if nested else direct_direction
    angular_speed = round(parameters["motion_speed"] * rng.uniform(.76, .94), 3)
    face_angle = DIRECTIONS[face_direction][2]
    angle_zero = (face_angle - angular_speed * 1.72) % 360
    second_line = "FLICK IT OPPOSITE THAT HEADING BEFORE THE RING CLOSES." if nested else f"FLICK IT {flick_direction} BEFORE THE RING CLOSES."
    return {
        "family": "vector_flick",
        "instruction": [f"WAIT UNTIL THE {_label(target)} POINTER FACES {face_direction}.", second_line],
        "tokens": tokens,
        "flick": {
            "face_direction": face_direction,
            "face_angle_deg": face_angle,
            "flick_direction": flick_direction,
            "angle_zero_deg": round(angle_zero, 4),
            "angular_speed_deg_s": angular_speed,
            "angle_tolerance_deg": parameters["flick_angle_tolerance_deg"],
            "min_travel_px": parameters["flick_min_travel_px"],
        },
        "predicate": {"target_id": target["id"]},
    }


def _relay_first_candidates(
    tokens: list[dict[str, Any]],
    first: dict[str, Any],
    anchor: dict[str, Any],
    depth: int,
) -> list[dict[str, Any]]:
    if depth < 2:
        return [token for token in tokens if _label(token) == _label(first)]
    if depth == 2:
        return [
            token
            for token in tokens
            if token["x"] < anchor["x"] and token["y"] == anchor["y"]
        ]
    if depth == 3:
        return [
            token
            for token in tokens
            if token["x"] < anchor["x"] and token["y"] > anchor["y"]
        ]
    return [
        token
        for token in tokens
        if token["x"] < anchor["x"]
        and token["y"] > anchor["y"]
        and abs((anchor["x"] - token["x"]) - (token["y"] - anchor["y"])) <= 1
    ]


def _relay_second_candidates(
    tokens: list[dict[str, Any]],
    first: dict[str, Any],
    second: dict[str, Any],
    depth: int,
) -> list[dict[str, Any]]:
    if depth == 0:
        return [token for token in tokens if _label(token) == _label(second)]
    return [
        token
        for token in tokens
        if token["id"] != first["id"] and token["mark"] == first["mark"]
    ]


def _assert_relay_visible_contract(
    tokens: list[dict[str, Any]],
    first: dict[str, Any],
    second: dict[str, Any],
    anchor: dict[str, Any],
    depth: int,
) -> float:
    first_candidates = _relay_first_candidates(tokens, first, anchor, depth)
    second_candidates = _relay_second_candidates(tokens, first, second, depth)
    if [token["id"] for token in first_candidates] != [first["id"]]:
        raise AssertionError(
            f"relay first instruction is not visibly unique at depth {depth}: "
            f"{[token['id'] for token in first_candidates]}"
        )
    if [token["id"] for token in second_candidates] != [second["id"]]:
        raise AssertionError(
            f"relay second instruction is not visibly unique at depth {depth}: "
            f"{[token['id'] for token in second_candidates]}"
        )
    minimum_distance = float("inf")
    for index, left in enumerate(tokens):
        for right in tokens[index + 1 :]:
            dx = abs(float(left["x"]) - float(right["x"]))
            dy = abs(float(left["y"]) - float(right["y"]))
            minimum_distance = min(minimum_distance, (dx * dx + dy * dy) ** .5)
            if dx < TOKEN_ACTION_WIDTH and dy < TOKEN_ACTION_HEIGHT:
                raise AssertionError(
                    "relay action boxes overlap: "
                    f"{left['id']} at ({left['x']}, {left['y']}) and "
                    f"{right['id']} at ({right['x']}, {right['y']})"
                )
    return round(minimum_distance, 3)


def _relay_round(rng: random.Random, parameters: dict[str, Any]) -> dict[str, Any]:
    count = parameters["object_count"]
    tokens = _tokens(rng, count, shared_mark_pair=True)
    first, second = tokens[0], tokens[1]
    others = tokens[2:]
    depth = parameters["relay_relation_depth"]
    anchor = others[0] if others else second
    relation_key = "explicit_identity"
    if depth >= 2:
        if depth == 2:
            relation_positions = [
                (280, 220), (460, 220),
                (120, 105), (300, 105), (630, 105), (700, 220), (120, 325),
            ]
            relation = "IMMEDIATELY LEFT OF"
            relation_key = "same_row_immediately_left"
        elif depth == 3:
            relation_positions = [
                (300, 290), (450, 145),
                (110, 100), (270, 100), (630, 100), (700, 235), (590, 325),
            ]
            relation = "DOWN-LEFT OF"
            relation_key = "unique_down_left_quadrant"
        else:
            relation_positions = [
                (300, 305), (475, 130),
                (110, 100), (285, 100), (650, 100), (710, 235), (610, 325),
            ]
            relation = "ON THE 45° DIAGONAL DOWN-LEFT OF"
            relation_key = "unique_45_degree_down_left"
        role_order = [first, anchor, second, *others[1:]]
        for token, (x, y) in zip(
            role_order, relation_positions[: len(role_order)], strict=True
        ):
            token.update({"x": x, "y": y})
        first_line = f"FIRST TAP THE TOKEN {relation} THE {_label(anchor)}."
    else:
        first_line = f"FIRST TAP THE {_label(first)}."
    second_line = f"THEN TAP THE {_label(second)}." if depth == 0 else f'THEN TAP THE OTHER TOKEN WITH ITS {first["mark"]} MARK.'
    minimum_center_distance = _assert_relay_visible_contract(
        tokens, first, second, anchor, depth
    )
    return {
        "family": "relay_pair",
        "instruction": [first_line, second_line],
        "tokens": tokens,
        "relay": {
            "relation_depth": depth,
            "relation_key": relation_key,
            "anchor_id": anchor["id"] if depth >= 2 else None,
            "minimum_center_distance": minimum_center_distance,
        },
        "predicate": {"first_id": first["id"], "second_id": second["id"]},
    }


def _bay_round(rng: random.Random, parameters: dict[str, Any]) -> dict[str, Any]:
    tokens = _tokens(rng, parameters["object_count"])
    target = rng.choice(tokens)
    target.update({"x": 170, "y": 238})
    bay_count = 3 if parameters["object_count"] <= 4 else 4
    bay_colors = rng.sample(list(COLORS), bay_count)
    target_bay_index = rng.randrange(bay_count)
    bays = []
    period = parameters["bay_period_ms"]
    open_ms = parameters["bay_open_ms"]
    for index, (color_name, color_hex) in enumerate(bay_colors):
        if index == target_bay_index:
            offset = int((open_ms / 2 - 1580) % period)
        else:
            offset = int((index * period / bay_count + rng.randint(60, 180)) % period)
        bays.append({
            "id": f"bay-{index + 1}",
            "color": color_name,
            "color_hex": color_hex,
            "x": 590 + (index % 2) * 175,
            "y": 145 + (index // 2) * 190,
            "phase_offset_ms": offset,
            "period_ms": period,
            "open_ms": open_ms,
            "radius": parameters["bay_radius"],
        })
    target_bay = bays[target_bay_index]
    return {
        "family": "shutter_drop",
        "instruction": [f"MOVE THE {_label(target)} INTO THE {target_bay['color']} BAY.", "RELEASE WHILE THAT BAY'S SHUTTER IS OPEN."],
        "tokens": tokens,
        "bays": bays,
        "predicate": {"target_id": target["id"], "bay_id": target_bay["id"]},
    }


def generate(task: dict[str, Any], seed: str):
    parameters = _parameters(task)
    _validate(parameters)
    parameter_token = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    stable = hashlib.sha256(
        f"{MECHANIC_ID}:{seed}:{parameter_token}".encode("utf-8")
    ).hexdigest()
    rng = random.Random(int(stable[:16], 16))
    task_id = str(task.get("id") or "five_second_rule")
    challenge_id = f"fsr-{stable[:18]}"
    rounds = [
        _gate_round(rng, parameters),
        _hold_round(rng, parameters),
        _flick_round(rng, parameters),
        _relay_round(rng, parameters),
        _bay_round(rng, parameters),
    ]
    rng.shuffle(rounds)
    for index, round_spec in enumerate(rounds, 1):
        round_spec["id"] = f"dispatch-{index}-{round_spec['family']}"
        round_spec["duration_ms"] = parameters["round_duration_ms"]
    fingerprint_source = json.dumps(rounds, sort_keys=True, separators=(",", ":"))
    world_fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    condition = _condition(task)
    public_state = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "world_fingerprint": world_fingerprint,
        "prompt": "READ TWO LINES. ACT BEFORE FIVE SECONDS EXPIRE.",
        "rounds": copy.deepcopy(rounds),
        "parameters": copy.deepcopy(parameters),
        "asset_manifest": str((task.get("metadata") or {}).get("asset_manifest") or "shared_runtime/assets/provenance/five_second_rule_v0.json"),
        "status": "ready",
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "world_fingerprint": world_fingerprint,
        "rounds": copy.deepcopy(rounds),
        "parameters": copy.deepcopy(parameters),
    }
    if condition is not None:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    return public_state, ground_truth
