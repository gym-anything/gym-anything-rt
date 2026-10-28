from __future__ import annotations

from typing import Any


MECHANIC_ID = "letter_rapids_v2"


def _failure(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "score": 0, "feedback": message}


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _identity_error(payload: dict[str, Any], ground_truth: dict[str, Any], public_state: dict[str, Any]) -> str | None:
    if {
        str(payload.get("mechanic_id") or ""),
        str(ground_truth.get("mechanic_id") or ""),
        str(public_state.get("mechanic_id") or ""),
    } != {MECHANIC_ID}:
        return "mechanic identity mismatch"
    challenges = {
        str(payload.get("challenge_id") or ""),
        str(ground_truth.get("challenge_id") or ""),
        str(public_state.get("challenge_id") or ""),
    }
    if len(challenges) != 1 or "" in challenges:
        return "challenge identity mismatch"
    tasks = {
        str(payload.get("task_id") or ""),
        str(ground_truth.get("task_id") or ""),
        str(public_state.get("task_id") or ""),
    }
    if len(tasks) != 1 or "" in tasks:
        return "task identity mismatch"
    return None


def _display_row(row: list[dict[str, Any]], floor: int) -> list[tuple[dict[str, Any], int, int]]:
    free = 10_000 - floor * len(row)
    widths = [
        floor + free * (int(band["end_milli"]) - int(band["start_milli"])) // 10_000
        for band in row
    ]
    remainder = 10_000 - sum(widths)
    for index in range(remainder):
        widths[index] += 1
    cursor = 0
    result = []
    for band, width in zip(row, widths):
        result.append((band, cursor, cursor + width))
        cursor += width
    return result


def _symbol_at(rows: dict[str, Any], output: str, y_milli: int, display_floor: int) -> str | None:
    context = output[-1] if output else "^"
    row = rows.get(context)
    if not isinstance(row, list):
        return None
    for band, start, end in _display_row(row, display_floor):
        if not isinstance(band, dict):
            return None
        if start <= y_milli < end:
            return str(band.get("symbol") or " ")
    return None


def _flow_delta(x_milli: int, current_milli: int, simulation: dict[str, Any]) -> tuple[int, int]:
    neutral = int(simulation["neutral_x_milli"])
    dead = int(simulation["dead_zone_half_width_milli"])
    speed = int(simulation["maximum_speed_units_per_second"])
    tick_ms = int(simulation["tick_ms"])
    minimum = max(1, speed * tick_ms * int(simulation["minimum_flow_milli"]) * current_milli // 1_000_000_000)
    forward_edge = neutral + dead
    reverse_edge = neutral - dead
    if x_milli > forward_edge:
        distance = x_milli - forward_edge
        extent = 10_000 - forward_edge
        delta = speed * tick_ms * distance * current_milli // (1_000 * extent * 1_000)
        return 1, max(minimum, delta)
    if x_milli < reverse_edge:
        distance = reverse_edge - x_milli
        extent = reverse_edge
        delta = speed * tick_ms * distance * current_milli // (1_000 * extent * 1_000)
        return -1, max(minimum, delta)
    return 1, minimum


def _contract_error(ground_truth: dict[str, Any], public_state: dict[str, Any]) -> str | None:
    keys = ("alphabet", "target", "probability_rows", "current_pattern_milli", "simulation")
    if any(public_state.get(key) != ground_truth.get(key) for key in keys):
        return "public canyon commitment disagrees with hidden state"
    alphabet = ground_truth.get("alphabet")
    target = ground_truth.get("target")
    rows = ground_truth.get("probability_rows")
    pattern = ground_truth.get("current_pattern_milli")
    simulation = ground_truth.get("simulation")
    if not isinstance(alphabet, str) or not alphabet or not isinstance(target, str) or not target:
        return "hidden letter contract is malformed"
    if not isinstance(rows, dict) or set(rows) != set("^" + alphabet):
        return "hidden probability model is malformed"
    expected_symbols = list(alphabet)
    for row in rows.values():
        if not isinstance(row, list) or [str(item.get("symbol") or " ") for item in row if isinstance(item, dict)] != expected_symbols:
            return "hidden probability row has the wrong alphabet"
        cursor = 0
        for band in row:
            if _integer(band.get("start_milli")) != cursor:
                return "hidden probability row has a gap"
            cursor = _integer(band.get("end_milli")) or -1
        if cursor != 10_000:
            return "hidden probability row does not fill the canyon"
    if not isinstance(pattern, list) or len(pattern) < 100 or any(_integer(value) is None for value in pattern):
        return "hidden current trace is malformed"
    required = {
        "tick_ms", "commit_units", "neutral_x_milli", "dead_zone_half_width_milli",
        "maximum_speed_units_per_second", "travel_budget_units", "maximum_rewound_characters",
        "display_band_floor_milli",
        "minimum_flow_milli",
    }
    if not isinstance(simulation, dict) or not required.issubset(simulation):
        return "hidden simulation contract is malformed"
    display_floor = _integer(simulation.get("display_band_floor_milli"))
    if display_floor is None or not 200 <= display_floor <= 350 or display_floor * len(alphabet) >= 10_000:
        return "hidden display geometry is malformed"
    return None


def grade(payload: dict[str, Any], ground_truth: dict[str, Any], public_state: dict[str, Any]) -> dict[str, Any]:
    identity_error = _identity_error(payload, ground_truth, public_state)
    if identity_error:
        return _failure(identity_error)
    contract_error = _contract_error(ground_truth, public_state)
    if contract_error:
        return _failure(contract_error)

    condition = ground_truth.get("control_condition")
    interaction = "full"
    if condition is not None:
        if public_state.get("control_condition") != condition:
            return _failure("controlled canyon condition mismatch")
        interaction = str(condition.get("interaction") or "")
    if interaction not in {"full", "simplified"} or payload.get("interaction_mode") != interaction:
        return _failure("wrong canyon interaction mode")
    expected_source = {"full": "canyon_pointer", "simplified": "axis_proxy"}[interaction]

    events = payload.get("events")
    # Permit dense ordinary pointer motion (500 Hz across the 120-second session).
    if not isinstance(events, list) or not events or len(events) > 60_000:
        return _failure("pointer transcript is missing or oversized")
    parsed_events: list[tuple[int, int, int]] = []
    previous_tick = -1
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict) or _integer(event.get("seq")) != index:
            return _failure("pointer sequence is not contiguous")
        if event.get("type") != "pointer":
            return _failure("unknown canyon transcript event")
        tick = _integer(event.get("tick"))
        x_milli = _integer(event.get("x_milli"))
        y_milli = _integer(event.get("y_milli"))
        if tick is None or tick < previous_tick or x_milli is None or y_milli is None:
            return _failure("pointer event coordinates are malformed")
        if not 0 <= x_milli <= 10_000 or not 0 <= y_milli < 10_000:
            return _failure("pointer left the physical canyon range")
        if event.get("input_source") != expected_source:
            return _failure("pointer used the wrong interaction input")
        previous_tick = tick
        parsed_events.append((tick, x_milli, y_milli))

    terminal_tick = _integer(payload.get("terminal_tick"))
    pattern = ground_truth["current_pattern_milli"]
    if terminal_tick is None or not 1 <= terminal_tick <= len(pattern):
        return _failure("terminal simulation tick is invalid")
    if parsed_events[-1][0] >= terminal_tick:
        return _failure("pointer transcript continues beyond the terminal tick")

    simulation = ground_truth["simulation"]
    display_floor = int(simulation["display_band_floor_milli"])
    rows = ground_truth["probability_rows"]
    target = str(ground_truth["target"])
    x_milli = int(simulation["neutral_x_milli"])
    y_milli = 5_000
    output = ""
    selected_symbol: str | None = None
    progress = 0
    rewind_progress = 0
    travel_used = 0
    committed = 0
    rewound = 0
    terminal_reason: str | None = None
    event_index = 0

    for tick in range(terminal_tick):
        while event_index < len(parsed_events) and parsed_events[event_index][0] == tick:
            _, x_milli, y_milli = parsed_events[event_index]
            event_index += 1
        direction, delta = _flow_delta(x_milli, int(pattern[tick]), simulation)
        if direction > 0 and delta:
            symbol = _symbol_at(rows, output, y_milli, display_floor)
            if symbol is None:
                return _failure("probability hit test could not resolve a channel")
            if symbol != selected_symbol:
                selected_symbol = symbol
                progress = 0
            rewind_progress = 0
            progress += delta
            travel_used += delta
            if progress >= int(simulation["commit_units"]):
                output += symbol
                committed += 1
                progress = 0
                selected_symbol = None
                if output == target:
                    terminal_reason = "target"
        elif direction < 0 and delta:
            travel_used += delta
            remaining = delta
            cancelled = min(progress, remaining)
            progress -= cancelled
            remaining -= cancelled
            if remaining:
                rewind_progress += remaining
            while rewind_progress >= int(simulation["commit_units"]) and output:
                rewind_progress -= int(simulation["commit_units"])
                output = output[:-1]
                rewound += 1
                selected_symbol = None
            if rewound > int(simulation["maximum_rewound_characters"]):
                terminal_reason = "rewind_budget"
        if terminal_reason is None and travel_used >= int(simulation["travel_budget_units"]):
            terminal_reason = "travel_budget"
        if terminal_reason is not None and tick != terminal_tick - 1:
            return _failure("submission continued after the replay reached a terminal state")

    if terminal_reason is None:
        return _failure("submission stopped before a terminal state")
    if event_index != len(parsed_events):
        return _failure("unreplayed pointer events remain")

    claims = {
        "output": output,
        "terminal_reason": terminal_reason,
        "travel_used_units": travel_used,
        "committed_characters": committed,
        "rewound_characters": rewound,
        "progress_units": progress,
    }
    for key, expected in claims.items():
        actual = payload.get(key)
        if isinstance(expected, int):
            actual = _integer(actual)
        if actual != expected:
            return _failure(f"submitted {key.replace('_', ' ')} disagrees with replay")
    passed = payload.get("completed") is True and terminal_reason == "target" and output == target
    if payload.get("completed") is not (terminal_reason == "target"):
        return _failure("submitted completion flag disagrees with replay")
    return {
        "graded": True,
        "passed": passed,
        "score": 100 if passed else 0,
        "feedback": (
            f"replayed {terminal_tick} current ticks; output {output!r}/{target!r}; "
            f"commits {committed}; rewinds {rewound}; travel {travel_used}/{int(simulation['travel_budget_units'])}; "
            f"terminal {terminal_reason}"
        ),
    }


def cheat(public_state: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    del public_state
    return {"target": ground_truth.get("target")}
