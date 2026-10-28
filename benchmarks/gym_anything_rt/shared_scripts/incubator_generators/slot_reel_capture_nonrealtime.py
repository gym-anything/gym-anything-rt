from __future__ import annotations

import copy
import hashlib
import random
from typing import Any


MECHANIC_ID = "slot_reel_capture_nonrealtime"
SLOT_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
SLOT_SYMBOLS = ("◆", "●", "✦", "♢", "▰", "✶")
SLOT_CONTROL_SYMBOLS = SLOT_SYMBOLS + ("✹", "⬟")
SLOT_REEL_VARIANT_COUNT = len(SLOT_ALPHABET) ** 5 * 24


def _seed(seed: str) -> int:
    # Keep the donor's seed namespace so a corresponding seed retains the same
    # sequence, token order, reel ids, intervals, and phases.
    return int.from_bytes(
        hashlib.sha256(f"{seed}|slot-reel-capture".encode("utf-8")).digest()[:8],
        "big",
    )


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    reel_count = int(parameters.get("reel_count", 5))
    token_count = int(parameters.get("token_count", len(SLOT_SYMBOLS) + 1))
    max_strikes = int(parameters.get("max_strikes", 3))
    capture_window_ratio = float(parameters.get("capture_window_ratio", 1.0))
    interval_values = parameters.get("interval_ms_values")
    if not 2 <= reel_count <= 7:
        raise ValueError("slot reel count must be between 2 and 7")
    if not 3 <= token_count <= len(SLOT_CONTROL_SYMBOLS) + 1:
        raise ValueError("slot token count is outside the supported range")
    if not 1 <= max_strikes <= 6:
        raise ValueError("slot strike budget must be between 1 and 6")
    if not 0.4 <= capture_window_ratio <= 1.0:
        raise ValueError("slot capture window ratio must be between 0.4 and 1.0")
    if interval_values is not None:
        if (
            not isinstance(interval_values, list)
            or not interval_values
            or any(not 180 <= int(value) <= 1500 for value in interval_values)
        ):
            raise ValueError("slot interval values are outside the supported range")
        normalized_intervals = [int(value) for value in interval_values]
    else:
        normalized_intervals = list(range(360, 570, 30))

    rng = random.Random(_seed(seed))
    sequence = "".join(rng.choice(SLOT_ALPHABET) for _ in range(reel_count))
    reels: list[dict[str, Any]] = []
    for index, target in enumerate(sequence):
        symbols = list(SLOT_CONTROL_SYMBOLS[: token_count - 1])
        rng.shuffle(symbols)
        insert_at = rng.randrange(1, len(symbols))
        symbols.insert(insert_at, target)
        reels.append(
            {
                "id": f"reel-{hashlib.sha256(f'{seed}|reel|{index}'.encode('utf-8')).hexdigest()[:8]}",
                "target": target,
                "tokens": symbols,
                "interval_ms": rng.choice(normalized_intervals),
                "phase": rng.randrange(len(symbols)),
            }
        )

    difficulty = int((condition or {}).get("difficulty") or 4)
    condition_token = "" if not condition or difficulty == 4 else f"|d{difficulty}"
    challenge_id = hashlib.sha256(
        f"{seed}|slot-reel{condition_token}".encode("utf-8")
    ).hexdigest()[:12]
    variant_count = (
        SLOT_REEL_VARIANT_COUNT
        if not condition or difficulty == 4
        else len(SLOT_ALPHABET) ** reel_count * token_count * len(normalized_intervals)
    )
    public_state: dict[str, Any] = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task["id"],
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language")
        or "Type each letter or number after it settles at center. Capture all five reels.",
        "submit_label": "VERIFY",
        "asset_manifest": "shared_runtime/assets/provenance/interaction_first_five_v0.json",
        "generator": {
            "name": "slot_reel_capture_nonrealtime_v1"
            if not condition or difficulty == 4
            else "slot_reel_capture_nonrealtime_v2",
            "variant_count": variant_count,
        },
        "max_strikes": max_strikes,
        "reels": reels,
    }
    if capture_window_ratio < 1.0:
        public_state["capture_window_ratio"] = capture_window_ratio
    ground_truth: dict[str, Any] = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task["id"],
        "seed": seed,
        "challenge_id": challenge_id,
        "sequence": sequence,
        "reel_ids": [reel["id"] for reel in reels],
        "max_strikes": max_strikes,
        "variant_count": variant_count,
    }
    if capture_window_ratio < 1.0:
        ground_truth["capture_window_ratio"] = capture_window_ratio
    if condition:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    return public_state, ground_truth
