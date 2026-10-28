"""Shared game-clock rate; transport and wall-clock receipts remain unscaled."""
import math
import os


def time_scale() -> float:
    value = float(os.environ.get("GYM_ANYTHING_RT_TIME_SCALE", "1"))
    if not math.isfinite(value) or not 0 < value <= 1:
        raise ValueError("GYM_ANYTHING_RT_TIME_SCALE must be finite and in (0, 1]")
    return value
