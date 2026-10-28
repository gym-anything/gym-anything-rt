from __future__ import annotations

import hashlib
import random
import copy
from typing import Any


MECHANIC_ID = "microgame_gauntlet"
ROUND_TYPES = ("pressure", "chord", "dial", "intercept", "route")
CHORDS = (("A", "L"), ("D", "K"), ("F", "J"), ("Q", "P"), ("S", "K"))
PULSE_POSITIONS = ((14, 25), (34, 18), (59, 22), (83, 30), (20, 70), (45, 79), (70, 72), (88, 62), (12, 49), (88, 47))
ROUTE_TEMPLATES = (
    ((8, 75), (19, 55), (29, 29), (42, 48), (53, 73), (64, 42), (73, 18), (84, 39), (92, 16)),
    ((8, 22), (18, 46), (29, 73), (40, 52), (51, 25), (62, 48), (72, 76), (83, 55), (93, 79)),
    ((8, 52), (18, 23), (30, 42), (41, 74), (52, 49), (63, 20), (74, 43), (84, 74), (93, 48)),
)
HARD_ROUTE_TEMPLATES = (
    ((7, 75), (15, 61), (22, 37), (30, 23), (39, 44), (47, 70), (55, 76), (63, 54), (71, 30), (82, 18), (93, 39)),
    ((7, 23), (15, 38), (22, 62), (31, 77), (40, 55), (48, 28), (57, 23), (66, 45), (75, 72), (85, 80), (93, 57)),
)


def _seed_int(seed: str, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _condition(task: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    condition = task.get("_control_condition")
    if not isinstance(condition, dict):
        return None, {}
    parameters = condition.get("difficulty_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("microgame gauntlet difficulty parameters are malformed")
    try:
        difficulty = int(condition.get("difficulty"))
    except (TypeError, ValueError) as exc:
        raise ValueError("microgame gauntlet difficulty is malformed") from exc
    if difficulty not in {1, 2, 3, 4, 5}:
        raise ValueError("microgame gauntlet difficulty is outside supported limits")
    return condition, dict(parameters)


def _profile_int(parameters: dict[str, Any], key: str, default: int) -> int:
    value = parameters.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"microgame gauntlet parameter {key} must be an integer") from exc


def _profile_float(parameters: dict[str, Any], key: str, default: float) -> float:
    value = parameters.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"microgame gauntlet parameter {key} must be numeric") from exc


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    condition, parameters = _condition(task)
    difficulty = int(condition["difficulty"]) if condition else 4
    # The historical task and its controlled D4 counterpart deliberately keep
    # the original seed stream and draw order.  That is the preservation
    # contract for the current configuration.
    baseline_stream = condition is None or difficulty == 4
    rng = random.Random(_seed_int(seed, MECHANIC_ID if baseline_stream else f"{MECHANIC_ID}|d{difficulty}"))
    if baseline_stream:
        # Preserve the historical output exactly, including visible wording
        # and integer-versus-float JSON representation. The controlled L4
        # profile describes these values but must not regenerate equivalents
        # through a different code path.
        pulse_min, pulse_max = 7, 8
        chord_count, required_ticks, chord_tick_ms = 3, 4, 145
        dial_tolerance, dial_friction, dial_tick_ms = 13, 0.945, 95
        packet_count, packet_speed_min, packet_speed_max = 3, 4.4, 6.0
        gate_half_width_min, gate_half_width_max, intercept_tick_ms = 5, 6, 105
        route_point_count, checkpoint_radius, corridor_radius = 9, 6, 8
    else:
        pulse_min = _profile_int(parameters, "pulse_count_min", 7)
        pulse_max = _profile_int(parameters, "pulse_count_max", 8)
        chord_count = _profile_int(parameters, "chord_count", 3)
        required_ticks = _profile_int(parameters, "required_ticks", 4)
        chord_tick_ms = _profile_int(parameters, "chord_tick_ms", 145)
        dial_tolerance = _profile_float(parameters, "dial_target_tolerance", 13)
        dial_friction = _profile_float(parameters, "dial_friction", 0.945)
        dial_tick_ms = _profile_int(parameters, "dial_tick_ms", 95)
        packet_count = _profile_int(parameters, "packet_count", 3)
        packet_speed_min = _profile_float(parameters, "packet_speed_min", 4.4)
        packet_speed_max = _profile_float(parameters, "packet_speed_max", 6.0)
        gate_half_width_min = _profile_int(parameters, "gate_half_width_min", 5)
        gate_half_width_max = _profile_int(parameters, "gate_half_width_max", 6)
        intercept_tick_ms = _profile_int(parameters, "intercept_tick_ms", 105)
        route_point_count = _profile_int(parameters, "route_point_count", 9)
        checkpoint_radius = _profile_float(parameters, "checkpoint_radius", 6)
        corridor_radius = _profile_float(parameters, "corridor_radius", 8)
    if not 3 <= pulse_min <= pulse_max <= len(PULSE_POSITIONS):
        raise ValueError("microgame gauntlet pulse profile is outside supported limits")
    if not 1 <= chord_count <= len(CHORDS) or required_ticks < 1 or chord_tick_ms < 40:
        raise ValueError("microgame gauntlet chord profile is outside supported limits")
    if not 4 <= dial_tolerance <= 45 or not 0.80 <= dial_friction <= 0.98 or dial_tick_ms < 40:
        raise ValueError("microgame gauntlet dial profile is outside supported limits")
    if not 1 <= packet_count <= 4 or not 1.5 <= packet_speed_min <= packet_speed_max <= 10:
        raise ValueError("microgame gauntlet intercept speed profile is outside supported limits")
    if not 3 <= gate_half_width_min <= gate_half_width_max <= 14 or intercept_tick_ms < 40:
        raise ValueError("microgame gauntlet intercept gate profile is outside supported limits")
    if not 4 <= route_point_count <= 11 or not 3 <= checkpoint_radius <= 12 or not 4 <= corridor_radius <= 16:
        raise ValueError("microgame gauntlet route profile is outside supported limits")
    order = list(ROUND_TYPES)
    rng.shuffle(order)
    pulse_positions = list(PULSE_POSITIONS[:8] if baseline_stream else PULSE_POSITIONS)
    rng.shuffle(pulse_positions)
    # Keep this exact call for the reference configuration.  Substituting
    # randint changes the subsequent historical random draws.
    pulse_count = rng.choice((7, 8)) if baseline_stream else rng.randint(pulse_min, pulse_max)
    pulse_ids = [f"P{index + 1}-{rng.randint(20, 98)}" for index in range(pulse_count)]
    chord_sequence = rng.sample(CHORDS, chord_count)
    dial_start = rng.randrange(0, 360, 30)
    dial_target = (dial_start + rng.choice((120, 150, 180, 210, 240))) % 360
    route_template = rng.choice(HARD_ROUTE_TEMPLATES if route_point_count > 9 else ROUTE_TEMPLATES)
    if route_point_count <= 9:
        route_template = route_template[:route_point_count]
    route_points = [
        {"x": max(7, min(93, x + rng.randint(-2, 2))), "y": max(12, min(82, y + rng.randint(-2, 2))), "index": index}
        for index, (x, y) in enumerate(route_template)
    ]
    rounds: list[dict[str, Any]] = []
    for sequence, round_type in enumerate(order):
        base: dict[str, Any] = {
            "id": f"R{sequence + 1}-{hashlib.sha256(f'{seed}|{round_type}'.encode()).hexdigest()[:5]}",
            "type": round_type,
            "sequence": sequence,
            "energy_cost": 8,
        }
        if round_type == "pressure":
            base.update({
                "title": "PRESSURE / PULSE BANK",
                "instruction": "Hold SPACE continuously. While held, click the lit pulse sockets in order; release only after the bank is dark.",
                "pulses": [
                    {"id": pulse_ids[index], "x": pulse_positions[index][0], "y": pulse_positions[index][1], "order": index}
                    for index in range(pulse_count)
                ],
            })
        elif round_type == "chord":
            base.update({
                "title": "THREE-STAGE MAGNETIC CHORD",
                "instruction": (
                    "Charge and release all three two-key chords in the displayed order. An early release discharges the bank."
                    if baseline_stream
                    else f"Charge and release all {len(chord_sequence)} two-key chords in the displayed order. An early release discharges the bank."
                ),
                "chords": [list(chord) for chord in chord_sequence],
                "required_ticks": required_ticks,
                "tick_ms": chord_tick_ms,
            })
        elif round_type == "dial":
            base.update({
                "title": "INERTIAL BRAKE DIAL",
                "instruction": "Drag around the flywheel to spin it. Release, let it coast, then brake inside the striped target sector.",
                "start_angle": dial_start,
                "target_angle": dial_target,
                "target_tolerance": dial_tolerance,
                "friction": dial_friction,
                "tick_ms": dial_tick_ms,
            })
        elif round_type == "intercept":
            if baseline_stream:
                packets = [
                    {
                        "id": f"PK-{index + 1}",
                        "speed": round(rng.uniform(4.4 + index * .45, 6.0 + index * .55), 2),
                        "gate_center": rng.randint(30, 70),
                        "gate_half_width": rng.choice((5, 6)),
                    }
                    for index in range(3)
                ]
            else:
                packets = [
                    {
                        "id": f"PK-{index + 1}",
                        "speed": round(rng.uniform(packet_speed_min + index * .25, packet_speed_max + index * .35), 2),
                        "gate_center": rng.randint(26, 74),
                        "gate_half_width": rng.randint(gate_half_width_min, gate_half_width_max),
                    }
                    for index in range(packet_count)
                ]
            base.update({
                "title": "TRIPLE MOVING-PACKET INTERCEPT" if baseline_stream else f"{len(packets)}-PACKET MOVING INTERCEPT",
                "instruction": (
                    "Arm once, then catch three packets. The capture gate and packet speed change after every hit."
                    if baseline_stream
                    else f"Arm once, then catch {len(packets)} packets. The capture gate and packet speed change after every hit."
                ),
                "packets": packets,
                "tick_ms": intercept_tick_ms,
            })
        else:
            base.update({
                "title": "BALANCE-ROUTE COURIER",
                "instruction": "Drag the reactor capsule through every numbered hoop without leaving the visible route corridor.",
                "points": route_points,
                "checkpoint_radius": checkpoint_radius,
                "corridor_radius": corridor_radius,
            })
        rounds.append(base)

    challenge_token = f"{seed}|{MECHANIC_ID}" if baseline_stream else f"{seed}|{MECHANIC_ID}|d{difficulty}"
    challenge_id = hashlib.sha256(challenge_token.encode("utf-8")).hexdigest()[:12]
    task_id = str(task.get("id") or "")
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Complete all five reactor trials without exhausting stability.",
        "asset_manifest": "shared_runtime/assets/provenance/incubator_full_build_v1.json",
        "generator": {"name": "mixed_input_verification_reactor_v2", "variant_count": 19_000_000_000},
        "reactor_id": f"VR-{challenge_id.upper()}",
        "rounds": rounds,
        "starting_energy": 100,
        "fault_penalty": 12,
        "reset_penalty": 4,
        "submit_label": "CERTIFY REACTOR",
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "rounds": rounds,
        "round_order": [round_data["id"] for round_data in rounds],
        "starting_energy": 100,
        "fault_penalty": 12,
        "reset_penalty": 4,
        "variant_count": 8_000_000_000,
    }
    if condition:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    assert {round_data["type"] for round_data in rounds} == set(ROUND_TYPES)
    assert len({round_data["id"] for round_data in rounds}) == 5
    return public_state, ground_truth
