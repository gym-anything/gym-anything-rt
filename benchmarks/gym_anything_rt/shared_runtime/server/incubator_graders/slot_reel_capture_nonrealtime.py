from __future__ import annotations

import math
from typing import Any


MECHANIC_ID = "slot_reel_capture_nonrealtime"
EXPECTED_SOURCES = {"simplified": "capture_button", "full": "physical_keyboard"}
EXPECTED_SURFACES = {"simplified": "capture_button_click", "full": "keyboard_keydown"}


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "score": 0, "feedback": message}


def _contract_error(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> str | None:
    if {payload.get("mechanic_id"), truth.get("mechanic_id"), public.get("mechanic_id")} != {MECHANIC_ID}:
        return "mechanic identity mismatch"
    for key in ("task_id", "challenge_id"):
        values = {str(payload.get(key) or ""), str(truth.get(key) or ""), str(public.get(key) or "")}
        if len(values) != 1 or "" in values:
            return f"{key.replace('_', ' ')} mismatch"
    condition = truth.get("control_condition")
    if condition is not None and public.get("control_condition") != condition:
        return "public interaction condition differs from the nonrealtime contract"
    return None


def _normalized_reels(truth: dict[str, Any], public: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    sequence = str(truth.get("sequence") or "").upper()
    reel_ids = [str(item) for item in truth.get("reel_ids") or []]
    reels = public.get("reels")
    if not sequence or len(sequence) != len(reel_ids) or not isinstance(reels, list) or len(reels) != len(reel_ids):
        return None, "slot-reel challenge geometry is invalid"
    normalized: list[dict[str, Any]] = []
    for index, (raw, reel_id, target) in enumerate(zip(reels, reel_ids, sequence), start=1):
        if not isinstance(raw, dict):
            return None, "slot-reel challenge geometry is invalid"
        try:
            interval_ms = int(raw["interval_ms"])
            phase = int(raw.get("phase") or 0)
        except (KeyError, TypeError, ValueError):
            return None, "slot-reel challenge timing is invalid"
        tokens = raw.get("tokens")
        if (
            str(raw.get("id") or "") != reel_id
            or str(raw.get("target") or "").upper() != target
            or not isinstance(tokens, list)
            or not tokens
            or any(not isinstance(token, str) or not token for token in tokens)
            or tokens.count(target) != 1
            or interval_ms <= 0
            or not 0 <= phase < len(tokens)
        ):
            return None, f"slot-reel {index} contract is invalid"
        normalized.append({"id": reel_id, "target": target, "tokens": tokens, "interval_ms": interval_ms, "phase": phase})
    return normalized, None


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    error = _contract_error(payload, truth, public)
    if error:
        return _fail(error)
    reels, error = _normalized_reels(truth, public)
    if error or reels is None:
        return _fail(error or "slot-reel challenge geometry is invalid")
    condition = truth.get("control_condition") or {}
    interaction = str(condition.get("interaction") or "full")
    expected_source = EXPECTED_SOURCES.get(interaction)
    expected_surface = EXPECTED_SURFACES.get(interaction)
    if expected_source is None or expected_surface is None:
        return _fail("slot-reel interaction condition is invalid")

    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        return _fail("slot-reel interaction transcript is missing")
    active_index = 0
    rejected_count = 0
    previous_elapsed = -1.0
    for sequence, action in enumerate(actions, start=1):
        if not isinstance(action, dict) or action.get("sequence") != sequence:
            return _fail("slot-reel action sequence is invalid")
        if active_index >= len(reels):
            return _fail("slot-reel transcript continues after completion")
        try:
            elapsed_ms = float(action.get("elapsed_ms"))
        except (TypeError, ValueError):
            return _fail("slot-reel action timing evidence is invalid")
        if not math.isfinite(elapsed_ms) or elapsed_ms < previous_elapsed:
            return _fail("slot-reel action timing evidence is invalid")
        previous_elapsed = elapsed_ms
        reel = reels[active_index]
        if (
            str(action.get("reel_id") or "") != reel["id"]
            or action.get("input_source") != expected_source
            or action.get("event_surface") != expected_surface
        ):
            return _fail("slot-reel action does not describe the held decision state")
        observed_token = action.get("observed_token")
        decision_state = action.get("decision_state")
        if observed_token not in reel["tokens"]:
            return _fail("slot-reel observed symbol is not part of the visible reel")
        if decision_state not in {"held", "revealing"}:
            return _fail("slot-reel decision state is invalid")
        entered_key = action.get("entered_key")
        if interaction == "simplified":
            if entered_key not in {None, ""}:
                return _fail("slot-reel capture button transcript contains a typed key")
            key_matches = True
        else:
            normalized_key = str(entered_key or "").upper()
            if len(normalized_key) != 1 or not normalized_key.isascii() or not normalized_key.isalnum():
                return _fail("slot-reel keyboard action is invalid")
            key_matches = normalized_key == reel["target"]
        accepted = decision_state == "held" and observed_token == reel["target"] and key_matches
        if not isinstance(action.get("accepted"), bool) or action["accepted"] is not accepted:
            return _fail("slot-reel accepted outcome disagrees with the held-state replay")
        if accepted:
            active_index += 1
        else:
            rejected_count += 1

    expected_sequence = str(truth["sequence"]).upper()
    frozen = [str(item) for item in payload.get("frozen_reel_ids") or []]
    submitted = str(payload.get("captured_sequence") or "").upper()
    try:
        wrong_keys = int(payload.get("wrong_keys"))
        max_strikes = int(truth.get("max_strikes"))
    except (TypeError, ValueError):
        return _fail("slot-reel strike transcript is invalid")
    if active_index != len(reels) or rejected_count != wrong_keys:
        return _fail("slot-reel capture or strike transcript is inconsistent")
    passed = (
        submitted == expected_sequence
        and frozen == [reel["id"] for reel in reels]
        and wrong_keys < max_strikes
    )
    return {
        "graded": True,
        "passed": passed,
        "score": 100 if passed else 0,
        "feedback": f"held-state replay captured {len(submitted)}/{len(expected_sequence)}; strikes {wrong_keys}/{max_strikes}",
    }
