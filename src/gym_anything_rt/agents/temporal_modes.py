"""Temporal-mode contract shared by the Gym-Anything-RT evaluator and agents."""

from __future__ import annotations

import math
from typing import Any


TEMPORAL_MODES = (
    "paused",
    "live",
    "live_timestamped",
    "live_timestamped_execution",
)


def validate_temporal_mode(mode: str) -> str:
    if mode not in TEMPORAL_MODES:
        choices = ", ".join(TEMPORAL_MODES)
        raise ValueError(f"temporal mode must be one of {choices}; got {mode!r}")
    return mode


def world_time_mode(mode: str) -> str:
    return "paused" if validate_temporal_mode(mode) == "paused" else "live"


def timestamps_enabled(mode: str) -> bool:
    return validate_temporal_mode(mode) in {
        "live_timestamped",
        "live_timestamped_execution",
    }


def scheduled_execution_enabled(mode: str) -> bool:
    return validate_temporal_mode(mode) == "live_timestamped_execution"


def episode_clock_origin_ms(observation: dict[str, Any]) -> float:
    """Return the live episode's fixed wall-clock origin from an observation."""
    timing = observation.get("time") if isinstance(observation, dict) else None
    raw = timing.get("episode_started_wall_ms") if isinstance(timing, dict) else None
    try:
        origin = float(raw)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "timestamped live observation is missing episode_started_wall_ms"
        ) from error
    if not math.isfinite(origin) or origin < 0:
        raise RuntimeError(
            "timestamped live observation has an invalid episode_started_wall_ms"
        )
    return origin
