from __future__ import annotations

import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "letter_rapids_v2"
TICK_MS = 50
COMMIT_UNITS = 10_000
NEUTRAL_X_MILLI = 3_300
PATTERN_TICKS = 2_400
DISPLAY_BAND_FLOOR_MILLI = 340

ALPHABET = "etaoinshrdlucmfwypvbgkqjxz "
BASE_FREQUENCY = {
    " ": 18_200, "e": 10_200, "t": 7_500, "a": 6_500, "o": 6_100,
    "i": 5_600, "n": 5_500, "s": 5_100, "h": 4_900, "r": 4_900,
    "d": 3_400, "l": 3_300, "u": 2_300, "c": 2_200, "m": 2_000,
    "f": 1_800, "w": 1_700, "y": 1_600, "p": 1_500, "v": 900,
    "b": 1_300, "g": 1_300, "k": 650, "q": 170, "j": 150,
    "x": 140, "z": 90,
}
COMMON_FOLLOWERS = {
    "^": "taishw",
    " ": "taishw",
    "a": "nrtls",
    "b": "eral",
    "c": "hoark",
    "d": "eio",
    "e": "rsndal",
    "f": "oril",
    "g": "erhla",
    "h": "eair",
    "i": "nsto",
    "j": "u",
    "k": "eis",
    "l": "eily",
    "m": "eaio",
    "n": "dget",
    "o": "nurf",
    "p": "erhla",
    "q": "u",
    "r": "eait",
    "s": "thet",
    "t": "heoir",
    "u": "rnst",
    "v": "eia",
    "w": "haoe",
    "x": "tcep",
    "y": " st",
    "z": "zea",
}

DEFAULT_PROFILE = {
    "alphabet": ALPHABET,
    "target_pool": ("quartz", "zephyr", "sphinx", "jigsaw", "vexing"),
    "minimum_band_milli": 110,
    "context_boost_milli": 1_950,
    "probability_jitter_milli": 200,
    "dead_zone_half_width_milli": 650,
    "maximum_speed_units_per_second": 7_600,
    "current_amplitude_milli": 340,
    "travel_budget_characters_milli": 10_500,
    "maximum_rewound_characters": 2,
}


def _seed_int(seed: str, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _profile(task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    condition = task.get("_control_condition")
    if not isinstance(condition, dict):
        return dict(DEFAULT_PROFILE), None
    parameters = condition.get("difficulty_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("Letter Rapids control profile is missing its parameters")
    profile = dict(DEFAULT_PROFILE)
    profile.update(parameters)
    try:
        alphabet = str(profile["alphabet"])
        targets = tuple(str(item) for item in profile["target_pool"])
        minimum_band = int(profile["minimum_band_milli"])
        context_boost = int(profile["context_boost_milli"])
        jitter = int(profile["probability_jitter_milli"])
        dead_zone = int(profile["dead_zone_half_width_milli"])
        maximum_speed = int(profile["maximum_speed_units_per_second"])
        current_amplitude = int(profile["current_amplitude_milli"])
        budget_milli = int(profile["travel_budget_characters_milli"])
        maximum_rewinds = int(profile["maximum_rewound_characters"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Letter Rapids control profile has an invalid parameter") from exc
    if not 8 <= len(alphabet) <= 27 or len(set(alphabet)) != len(alphabet):
        raise ValueError("Letter Rapids alphabet is malformed")
    if any(char not in ALPHABET for char in alphabet):
        raise ValueError("Letter Rapids alphabet contains an unsupported symbol")
    if not targets or any(not target or any(char not in alphabet for char in target) for target in targets):
        raise ValueError("Letter Rapids target pool is incompatible with its alphabet")
    if minimum_band * len(alphabet) >= COMMIT_UNITS:
        raise ValueError("Letter Rapids minimum bands leave no probability mass")
    if not 50 <= minimum_band <= 900 or not 500 <= context_boost <= 3_000 or not 0 <= jitter <= 500:
        raise ValueError("Letter Rapids probability controls are outside supported limits")
    if not 350 <= dead_zone <= 1_300 or not 3_000 <= maximum_speed <= 10_000:
        raise ValueError("Letter Rapids steering controls are outside supported limits")
    if not 0 <= current_amplitude <= 500 or not 4_000 <= budget_milli <= 20_000:
        raise ValueError("Letter Rapids flow controls are outside supported limits")
    if not 1 <= maximum_rewinds <= 6:
        raise ValueError("Letter Rapids rewind budget is outside supported limits")
    profile.update(
        alphabet=alphabet,
        target_pool=targets,
        minimum_band_milli=minimum_band,
        context_boost_milli=context_boost,
        probability_jitter_milli=jitter,
        dead_zone_half_width_milli=dead_zone,
        maximum_speed_units_per_second=maximum_speed,
        current_amplitude_milli=current_amplitude,
        travel_budget_characters_milli=budget_milli,
        maximum_rewound_characters=maximum_rewinds,
    )
    return profile, condition


def _row(seed: str, context: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    alphabet = str(profile["alphabet"])
    rng = random.Random(_seed_int(seed, f"row|{context}"))
    boost = int(profile["context_boost_milli"])
    jitter = int(profile["probability_jitter_milli"])
    followers = COMMON_FOLLOWERS.get(context, "")
    weights: list[int] = []
    for symbol in alphabet:
        weight = int(BASE_FREQUENCY[symbol])
        if symbol in followers:
            weight = weight * (1_000 + boost) // 1_000
        if jitter:
            weight = weight * (1_000 + rng.randint(-jitter, jitter)) // 1_000
        weights.append(max(1, weight))
    floor = int(profile["minimum_band_milli"])
    free = COMMIT_UNITS - floor * len(alphabet)
    total = sum(weights)
    raw = [free * weight for weight in weights]
    widths = [floor + value // total for value in raw]
    remainder = COMMIT_UNITS - sum(widths)
    order = sorted(range(len(alphabet)), key=lambda index: (-(raw[index] % total), alphabet[index]))
    for index in order[:remainder]:
        widths[index] += 1
    cursor = 0
    result: list[dict[str, Any]] = []
    for symbol, width in zip(alphabet, widths):
        result.append({"symbol": symbol, "start_milli": cursor, "end_milli": cursor + width})
        cursor += width
    assert cursor == COMMIT_UNITS
    return result


def _current_pattern(seed: str, amplitude: int) -> list[int]:
    rng = random.Random(_seed_int(seed, "current"))
    pattern: list[int] = []
    current = 1000
    while len(pattern) < PATTERN_TICKS:
        target = rng.randint(1000 - amplitude, 1000 + amplitude)
        duration = rng.randint(18, 55)
        for offset in range(duration):
            fraction = offset / duration
            eased = fraction * fraction * (3 - 2 * fraction)
            pattern.append(round(current + (target - current) * eased))
            if len(pattern) == PATTERN_TICKS:
                break
        current = target
    return pattern


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    profile, condition = _profile(task)
    rng = random.Random(_seed_int(seed, MECHANIC_ID))
    target = rng.choice(tuple(profile["target_pool"]))
    alphabet = str(profile["alphabet"])
    contexts = "^" + alphabet
    rows = {context: _row(seed, context, profile) for context in contexts}
    pattern = _current_pattern(seed, int(profile["current_amplitude_milli"]))
    challenge_salt = MECHANIC_ID if condition is None else f"{MECHANIC_ID}|d{int(condition['difficulty'])}"
    challenge_id = hashlib.sha256(f"{seed}|{challenge_salt}".encode("utf-8")).hexdigest()[:12]
    task_id = str(task.get("id") or "letter_rapids_v2_seed_0001@0.1")
    simulation = {
        "tick_ms": TICK_MS,
        "commit_units": COMMIT_UNITS,
        "neutral_x_milli": NEUTRAL_X_MILLI,
        "dead_zone_half_width_milli": int(profile["dead_zone_half_width_milli"]),
        "maximum_speed_units_per_second": int(profile["maximum_speed_units_per_second"]),
        "travel_budget_units": int(profile["travel_budget_characters_milli"]) * 10,
        "maximum_rewound_characters": int(profile["maximum_rewound_characters"]),
        "display_band_floor_milli": DISPLAY_BAND_FLOOR_MILLI,
        "minimum_flow_milli": 250,
    }
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Steer through the letter canyon until the output matches the target.",
        "asset_manifest": "shared_runtime/assets/provenance/letter_rapids_v0.json",
        "generator": {"name": "letter_rapids_v2_probability_canyon_v1", "variant_count": 9_000_000_000},
        "alphabet": alphabet,
        "target": target,
        "probability_rows": rows,
        "current_pattern_milli": pattern,
        "simulation": simulation,
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "alphabet": alphabet,
        "target": target,
        "probability_rows": rows,
        "current_pattern_milli": pattern,
        "simulation": simulation,
        "variant_count": 9_000_000_000,
    }
    if condition is not None:
        public_state["control_condition"] = condition
        ground_truth["control_condition"] = condition
    return public_state, ground_truth
