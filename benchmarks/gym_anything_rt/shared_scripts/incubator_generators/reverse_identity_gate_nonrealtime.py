from __future__ import annotations

import hashlib
import random
from typing import Any


MECHANIC_ID = "reverse_identity_gate_nonrealtime"
STATIONS = (
    {"id": 0, "glyph": "◢", "name": "PORT ARM", "color": "#ff684d"},
    {"id": 1, "glyph": "◇", "name": "OPTIC HEAD", "color": "#65ddc4"},
    {"id": 2, "glyph": "⌁", "name": "DRIVE CORE", "color": "#f6c453"},
    {"id": 3, "glyph": "◩", "name": "STARBOARD ARM", "color": "#78a8ff"},
)
PALETTES = ("carbon", "bone", "oxide", "midnight")
VARIANT_COUNT = 24 * 18 * 4**8 * 360**8


def _control_condition(task: dict[str, Any]) -> dict[str, Any] | None:
    condition = task.get("_control_condition")
    if not isinstance(condition, dict):
        return None
    parameters = condition.get("difficulty_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("controlled reverse identity gate requires difficulty parameters")
    return condition


def _active_sequence(rng: random.Random, parameters: dict[str, Any]) -> list[int]:
    station_count = int(parameters["station_count"])
    station_relays = [int(value) for value in parameters["station_relays"]]
    if not 1 <= station_count <= len(STATIONS) or len(station_relays) != station_count:
        raise ValueError("reverse identity gate station profile is invalid")
    if any(value < 1 for value in station_relays):
        raise ValueError("every active reverse identity gate limb needs a relay")

    first = list(range(station_count))
    rng.shuffle(first)
    remaining = [station for station, count in enumerate(station_relays) for _ in range(count - 1)]
    sequence = list(first)
    while remaining:
        eligible = [station for station in remaining if station != sequence[-1]] or list(remaining)
        station = rng.choice(eligible)
        remaining.remove(station)
        sequence.append(station)
    return sequence


def _angular_error(first: int, second: int) -> int:
    return abs((first - second + 180) % 360 - 180)


def _receiver_angle(rng: random.Random, pulse: int) -> int:
    for _ in range(100):
        candidate = rng.randrange(0, 360, 5)
        if _angular_error(candidate, pulse) >= 90:
            return candidate
    raise ValueError("could not generate a separated receiver phase")


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    # Keep corresponding seeds identical to the frozen donor despite the
    # counterpart's distinct runtime namespace.
    digest = hashlib.sha256(f"{seed}|reverse_identity_gate".encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    condition = _control_condition(task)
    parameters = dict(condition["difficulty_parameters"]) if condition else None
    task_id = str(task.get("id") or "reverse_identity_gate_nonrealtime_seed_0001@0.1")
    condition_identity = f"|difficulty-{condition['difficulty']}" if condition else ""
    challenge_id = hashlib.sha256(f"{seed}|distributed-robot-handshake-v2{condition_identity}".encode("utf-8")).hexdigest()[:12]
    if parameters is None or int(condition["difficulty"]) == 4:
        # Keep the historical sequence-generation draws verbatim for the
        # uncontrolled task and the L4 fixed-seed preservation profile.  L4
        # still reads its declared physics and pulse parameters below.
        first = list(range(4))
        second = list(range(4))
        rng.shuffle(first)
        for _ in range(50):
            rng.shuffle(second)
            if second[0] != first[-1]:
                break
        sequence = first + second
        active_stations = list(STATIONS)
        if parameters is None:
            physics = {
                "tick_ms": 50,
                "receiver_control_deg_per_tick": 5,
                "capture_tolerance_deg": 13,
                "hold_ticks": 16,
                "charge_decay_per_tick": 2,
                "maximum_ticks_per_stage": 900,
            }
        else:
            physics = {
                "tick_ms": int(parameters["tick_ms"]),
                "receiver_control_deg_per_tick": int(parameters["receiver_control_deg_per_tick"]),
                "capture_tolerance_deg": int(parameters["capture_tolerance_deg"]),
                "hold_ticks": int(parameters["hold_ticks"]),
                "charge_decay_per_tick": int(parameters["charge_decay_per_tick"]),
                "maximum_ticks_per_stage": int(parameters["maximum_ticks_per_stage"]),
            }
    else:
        sequence = _active_sequence(rng, parameters)
        active_stations = list(STATIONS[:int(parameters["station_count"])])
        physics = {
            "tick_ms": int(parameters["tick_ms"]),
            "receiver_control_deg_per_tick": int(parameters["receiver_control_deg_per_tick"]),
            "capture_tolerance_deg": int(parameters["capture_tolerance_deg"]),
            "hold_ticks": int(parameters["hold_ticks"]),
            "charge_decay_per_tick": int(parameters["charge_decay_per_tick"]),
            "maximum_ticks_per_stage": int(parameters["maximum_ticks_per_stage"]),
        }
    stages = []
    for index, station in enumerate(sequence):
        pulse_start = rng.randrange(0, 360)
        speed_choices = (-3, -2, 2, 3) if parameters is None else tuple(int(value) for value in parameters["pulse_speed_choices"])
        speed = rng.choice(speed_choices)
        stages.append({
            "index": index,
            "station": station,
            "pulse_start_deg": pulse_start,
            "pulse_speed_deg_per_tick": speed,
            "receiver_initial_deg": _receiver_angle(rng, pulse_start),
            "load": rng.randrange(2, 10),
        })

    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Prove you are a robot.",
        "submit_label": "VERIFY IDENTITY",
        "asset_manifest": "shared_runtime/assets/provenance/revived_pilots_v2.json",
        "generator": {
            "name": "distributed_four_tab_robot_handshake_v2",
            "variant_count": VARIANT_COUNT,
            "variant_count_kind": "station-order/load/phase/direction space",
        },
        "stations": active_stations,
        "stages": stages,
        "physics": physics,
        "palette": rng.choice(PALETTES),
        "rules": {
            "deployment": "Each limb is an explicit same-origin browser tab created from the loaded challenge.",
            "relay": "Drive the receiver with A/D and hold the mouse contact while the phases overlap; deliberate contact advances a finite fixed-step window.",
            "recovery": "Broken phase contact visibly drains charge but does not silently fail the challenge.",
            "timing": "The phase apparatus holds between deliberate inputs; a contact action starts a finite visible fixed-step window.",
        },
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "stations": active_stations,
        "stages": stages,
        "physics": physics,
        "palette": public_state["palette"],
        "variant_count": VARIANT_COUNT,
        "variant_count_kind": public_state["generator"]["variant_count_kind"],
    }
    if condition:
        public_state["control_condition"] = condition
        ground_truth["control_condition"] = condition
    return public_state, ground_truth
