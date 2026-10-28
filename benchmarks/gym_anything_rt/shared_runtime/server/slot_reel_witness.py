from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any

try:
    from . import grillmaster_witness as witness_crypto
except ImportError:
    import grillmaster_witness as witness_crypto


MECHANIC_ID = "slot_reel_capture"
PUBLIC_KEY_FIELD = "slot_reel_interaction_public_key"
KEY_FILE = "slot_reel_witness_key.json"
LEDGER_FILE = "slot_reel_witness_ledger.json"
CLOCK_FILE = "slot_reel_witness_clock.json"
MAX_ELAPSED_MS = 90_000.0
EXPECTED_SOURCES = {
    "simplified": "capture_button",
    "full": "physical_keyboard",
}
EVENT_SURFACES = {
    "simplified": "capture_button_click",
    "full": "keyboard_keydown",
}


def reset(state_dir: Path) -> None:
    for name in (KEY_FILE, LEDGER_FILE, CLOCK_FILE):
        try:
            (state_dir / name).unlink()
        except FileNotFoundError:
            pass


def _identity_error(
    payload: dict[str, Any],
    ground_truth: dict[str, Any],
) -> str | None:
    if str(ground_truth.get("mechanic_id") or "") != MECHANIC_ID:
        return "slot-reel witness is unavailable for this mechanic"
    for key in ("task_id", "challenge_id"):
        expected = str(ground_truth.get(key) or "")
        if not expected or str(payload.get(key) or "") != expected:
            return f"{key.replace('_', ' ')} mismatch"
    return None


def _interaction(ground_truth: dict[str, Any]) -> str:
    condition = ground_truth.get("control_condition")
    if condition is None:
        return "full"
    return str((condition or {}).get("interaction") or "")


def _clock_default(ground_truth: dict[str, Any]) -> dict[str, Any]:
    start_paused = os.environ.get("GYM_ANYTHING_RT_START_PAUSED") == "1"
    mode = str(os.environ.get("GYM_ANYTHING_RT_TIME_MODE") or "live")
    now_ns = time.monotonic_ns()
    return {
        "version": 1,
        "challenge_id": str(ground_truth.get("challenge_id") or ""),
        "mode": mode,
        "time_scale": witness_crypto.time_scale(),
        "state": "paused" if start_paused else "running",
        "elapsed_ms": 0.0,
        "running_since_ns": None if start_paused else now_ns,
        "pending_run_for": None,
        "updated_wall_ns": time.time_ns(),
    }


def _load_clock(
    state_dir: Path,
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    path = state_dir / CLOCK_FILE
    clock = witness_crypto._read_json(path)
    if clock.get("challenge_id") != ground_truth.get("challenge_id"):
        clock = _clock_default(ground_truth)
        witness_crypto._write_json(path, clock)
    return clock


def _accrue(clock: dict[str, Any], now_ns: int | None = None) -> None:
    now_ns = time.monotonic_ns() if now_ns is None else now_ns
    if clock.get("state") == "running":
        started = int(clock.get("running_since_ns") or now_ns)
        clock["elapsed_ms"] = float(clock.get("elapsed_ms") or 0.0) + max(
            0.0,
            (now_ns - started) / 1_000_000 * float(clock.get("time_scale", 1.0)),
        )
        clock["running_since_ns"] = now_ns
    clock["updated_wall_ns"] = time.time_ns()


def task_time_ms(
    state_dir: Path,
    ground_truth: dict[str, Any],
) -> float:
    clock = _load_clock(state_dir, ground_truth)
    _accrue(clock)
    witness_crypto._write_json(state_dir / CLOCK_FILE, clock)
    return round(float(clock.get("elapsed_ms") or 0.0), 3)


def apply_time_command(
    state_dir: Path,
    ground_truth: dict[str, Any],
    command: dict[str, Any],
) -> None:
    if str(ground_truth.get("mechanic_id") or "") != MECHANIC_ID:
        return
    clock = _load_clock(state_dir, ground_truth)
    _accrue(clock)
    kind = str(command.get("command") or "")
    if kind == "resume":
        clock["state"] = "running"
        clock["running_since_ns"] = time.monotonic_ns()
        clock["pending_run_for"] = None
    elif kind in {"pause", "settle_pause"}:
        clock["state"] = "paused"
        clock["running_since_ns"] = None
        clock["pending_run_for"] = None
    elif kind == "run_for":
        clock["state"] = "paused"
        clock["running_since_ns"] = None
        clock["pending_run_for"] = {
            "sequence": int(command.get("sequence") or 0),
            "milliseconds": float(command.get("milliseconds") or 0.0),
        }
    witness_crypto._write_json(state_dir / CLOCK_FILE, clock)


def apply_time_status(
    state_dir: Path,
    ground_truth: dict[str, Any],
    status: dict[str, Any],
) -> None:
    if (
        str(ground_truth.get("mechanic_id") or "") != MECHANIC_ID
    ):
        return
    clock = _load_clock(state_dir, ground_truth)
    if "task_origin_ms" in clock:
        if status.get("client_id") != clock.get("client_id"):
            return
        task_ms = float(status.get("task_time_ms") or 0.0)
        if not math.isfinite(task_ms) or task_ms < clock.get("last_task_ms", 0.0):
            return
        clock["last_task_ms"] = task_ms
        clock["elapsed_ms"] = max(0.0, task_ms - clock["task_origin_ms"])
        clock["state"] = status.get("state")
        clock["running_since_ns"] = time.monotonic_ns() if clock["state"] == "running" else None
        if status.get("phase") == "completed":
            clock["pending_run_for"] = None
        witness_crypto._write_json(state_dir / CLOCK_FILE, clock)
        return
    if status.get("phase") != "completed":
        return
    pending = clock.get("pending_run_for")
    if not isinstance(pending, dict):
        return
    if int(status.get("sequence") or -1) != int(
        pending.get("sequence") or -2
    ):
        return
    clock["elapsed_ms"] = float(clock.get("elapsed_ms") or 0.0) + float(
        pending.get("milliseconds") or 0.0
    )
    clock["state"] = "paused"
    clock["running_since_ns"] = None
    clock["pending_run_for"] = None
    clock["updated_wall_ns"] = time.time_ns()
    witness_crypto._write_json(state_dir / CLOCK_FILE, clock)


def start_controlled_clock(
    state_dir: Path, ground_truth: dict[str, Any], payload: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Bind this challenge to the evaluator clock at its first browser render."""
    error = _identity_error(payload, ground_truth)
    if error:
        return {"error": error}, 400
    try:
        origin = float(payload["task_time_ms"])
    except (KeyError, TypeError, ValueError):
        return {"error": "invalid task clock origin"}, 400
    client = payload.get("client_id")
    if not math.isfinite(origin) or origin < 0 or not isinstance(client, str) or not client:
        return {"error": "invalid task clock origin"}, 400
    clock = _load_clock(state_dir, ground_truth)
    if "task_origin_ms" in clock:
        if clock["task_origin_ms"] != origin or clock.get("client_id") != client:
            return {"error": "challenge clock is already initialized"}, 409
        return {"ok": True}, 200
    clock.update(task_origin_ms=origin, last_task_ms=origin, client_id=client,
                 elapsed_ms=0.0, state="paused", running_since_ns=None)
    witness_crypto._write_json(state_dir / CLOCK_FILE, clock)
    apply_time_status(state_dir, ground_truth, witness_crypto._read_json(state_dir / "time_status.json"))
    return {"ok": True}, 200


def _ensure_key(
    state_dir: Path,
    ground_truth: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    challenge_id = str(ground_truth.get("challenge_id") or "")
    key_path = state_dir / KEY_FILE
    key = witness_crypto._read_json(key_path)
    if key.get("challenge_id") != challenge_id:
        key = witness_crypto._generate_key(challenge_id)
        witness_crypto._write_json(key_path, key)
    public_key = witness_crypto._public_key(key)
    if ground_truth.get(PUBLIC_KEY_FIELD) != public_key:
        ground_truth = dict(ground_truth)
        ground_truth[PUBLIC_KEY_FIELD] = public_key
        witness_crypto._write_json(
            state_dir / "ground_truth.json",
            ground_truth,
        )
    return key, ground_truth


def _load_ledger(
    state_dir: Path,
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    path = state_dir / LEDGER_FILE
    challenge_id = str(ground_truth.get("challenge_id") or "")
    ledger = witness_crypto._read_json(path)
    if ledger.get("challenge_id") != challenge_id:
        ledger = {
            "version": 1,
            "mechanic_id": MECHANIC_ID,
            "task_id": str(ground_truth.get("task_id") or ""),
            "challenge_id": challenge_id,
            "interaction": _interaction(ground_truth),
            "clock_source": "server_active_task_clock_v1",
            "actions": [],
        }
        witness_crypto._write_json(path, ledger)
    return ledger


def initialize(
    state_dir: Path,
    ground_truth: dict[str, Any],
) -> None:
    if str(ground_truth.get("mechanic_id") or "") != MECHANIC_ID:
        return
    _key, ground_truth = _ensure_key(state_dir, ground_truth)
    _load_clock(state_dir, ground_truth)
    _load_ledger(state_dir, ground_truth)


def _frame_at(
    reel: dict[str, Any],
    elapsed_ms: float,
    capture_window_ratio: float,
) -> tuple[str, bool]:
    tokens = reel["tokens"]
    interval_ms = int(reel["interval_ms"])
    token_index = (
        math.floor(elapsed_ms / interval_ms) + int(reel.get("phase") or 0)
    ) % len(tokens)
    cycle_position = (elapsed_ms % interval_ms) / interval_ms
    capture_ready = (
        capture_window_ratio >= 1.0
        or abs(cycle_position - 0.5) <= capture_window_ratio / 2.0
    )
    return str(tokens[token_index]), capture_ready


def record_action(
    state_dir: Path,
    payload: dict[str, Any],
    ground_truth: dict[str, Any],
    public_state: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    error = _identity_error(payload, ground_truth)
    if error:
        return {"ok": False, "error": error}, 400
    if public_state.get("control_condition") != ground_truth.get(
        "control_condition"
    ):
        return {
            "ok": False,
            "error": "public interaction condition differs from slot-reel contract",
        }, 400
    interaction = _interaction(ground_truth)
    expected_source = EXPECTED_SOURCES.get(interaction)
    expected_surface = EVENT_SURFACES.get(interaction)
    if expected_source is None or expected_surface is None:
        return {"ok": False, "error": "interaction condition is invalid"}, 400
    if (
        payload.get("is_trusted") is not True
        or str(payload.get("input_source") or "") != expected_source
        or str(payload.get("event_surface") or "") != expected_surface
    ):
        return {"ok": False, "error": "slot-reel event surface is invalid"}, 400

    _key, ground_truth = _ensure_key(state_dir, ground_truth)
    ledger = _load_ledger(state_dir, ground_truth)
    actions = ledger.get("actions") or []
    accepted_count = sum(
        1 for action in actions if action.get("accepted") is True
    )
    rejected_count = len(actions) - accepted_count
    expected_reel_ids = [
        str(reel_id) for reel_id in ground_truth.get("reel_ids") or []
    ]
    public_reels = public_state.get("reels") or []
    if (
        accepted_count >= len(expected_reel_ids)
        or accepted_count >= len(public_reels)
    ):
        return {"ok": False, "error": "slot-reel challenge is complete"}, 400
    if rejected_count >= int(ground_truth.get("max_strikes") or 3):
        return {"ok": False, "error": "slot-reel strike budget is exhausted"}, 400

    reel = public_reels[accepted_count]
    reel_id = expected_reel_ids[accepted_count]
    target = str(ground_truth.get("sequence") or "")[accepted_count]
    if (
        not isinstance(reel, dict)
        or str(reel.get("id") or "") != reel_id
        or str(reel.get("target") or "") != target
    ):
        return {"ok": False, "error": "slot-reel challenge geometry is invalid"}, 400

    entered_key = payload.get("entered_key")
    if interaction == "simplified":
        if entered_key not in {None, ""}:
            return {"ok": False, "error": "capture button included a key"}, 400
        normalized_key = None
        key_matches = True
    else:
        normalized_key = str(entered_key or "").upper()
        if (
            len(normalized_key) != 1
            or not normalized_key.isascii()
            or not normalized_key.isalnum()
        ):
            return {"ok": False, "error": "keyboard action is invalid"}, 400
        key_matches = normalized_key == target

    witnessed_time = task_time_ms(state_dir, ground_truth)
    if not 0.0 <= witnessed_time <= MAX_ELAPSED_MS:
        return {"ok": False, "error": "slot-reel task time is exhausted"}, 400
    try:
        client_elapsed_ms = float(payload.get("client_elapsed_ms"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "slot-reel client clock evidence is invalid"}, 400
    if (
        not math.isfinite(client_elapsed_ms)
        or abs(client_elapsed_ms - witnessed_time) > 250.0
    ):
        return {"ok": False, "error": "slot-reel client/server clocks disagree"}, 400
    observed_token, capture_ready = _frame_at(
        reel,
        witnessed_time,
        float(
            public_state.get(
                "capture_window_ratio",
                ground_truth.get("capture_window_ratio", 1.0),
            )
        ),
    )
    accepted = (
        observed_token == target
        and capture_ready
        and key_matches
    )
    action = {
        "sequence": len(actions) + 1,
        "reel_id": reel_id,
        "elapsed_ms": witnessed_time,
        "client_elapsed_ms": client_elapsed_ms,
        "server_task_time_ms": witnessed_time,
        "observed_token": observed_token,
        "entered_key": normalized_key,
        "accepted": accepted,
        "input_source": expected_source,
        "event_surface": expected_surface,
        "server_received_wall_ns": time.time_ns(),
    }
    ledger.setdefault("actions", []).append(action)
    witness_crypto._write_json(state_dir / LEDGER_FILE, ledger)
    return {"ok": True, "witness_action": action}, 200


def finalize(
    state_dir: Path,
    ground_truth: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    key = witness_crypto._read_json(state_dir / KEY_FILE)
    ledger = _load_ledger(state_dir, ground_truth)
    if (
        key.get("challenge_id") != ground_truth.get("challenge_id")
        or not ledger.get("actions")
    ):
        return None, "server-witnessed slot-reel actions are missing"
    public_key = witness_crypto._public_key(key)
    if ground_truth.get(PUBLIC_KEY_FIELD) != public_key:
        return None, "server witness key is not bound to the slot-reel challenge"
    witnessed = {
        "version": 1,
        "mechanic_id": MECHANIC_ID,
        "task_id": ledger["task_id"],
        "challenge_id": ledger["challenge_id"],
        "interaction": ledger["interaction"],
        "clock_source": ledger["clock_source"],
        "public_key": public_key,
        "actions": ledger["actions"],
        "finalized_wall_ns": time.time_ns(),
    }
    modulus = int(key["n_hex"], 16)
    private = int(key["d_hex"], 16)
    size = (modulus.bit_length() + 7) // 8
    encoded = witness_crypto._encoded_message(witnessed, size)
    signature = pow(int.from_bytes(encoded, "big"), private, modulus)
    return {
        **witnessed,
        "signature_hex": signature.to_bytes(size, "big").hex(),
    }, None
