from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import time
from pathlib import Path
from typing import Any

try:
    from .task_clock import time_scale
except ImportError:
    from task_clock import time_scale


MECHANIC_ID = "parallel_grillmaster"
PUBLIC_KEY_FIELD = "trusted_interaction_public_key"
ALGORITHM = "rsa-sha256-pkcs1-v1_5"
KEY_FILE = "parallel_grillmaster_witness_key.json"
LEDGER_FILE = "parallel_grillmaster_witness_ledger.json"
CLOCK_FILE = "parallel_grillmaster_witness_clock.json"
EXPECTED_SOURCES = {
    "simplified": "grill_proxy_controls",
    "full": "food_drag",
}
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex(
    "3031300d060960864801650304020105000420"
)
_SMALL_PRIMES = (
    3,
    5,
    7,
    11,
    13,
    17,
    19,
    23,
    29,
    31,
    37,
    41,
    43,
    47,
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


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
        return "witness is unavailable for this mechanic"
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


def _valid_point(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(
            isinstance(item, (int, float))
            and math.isfinite(float(item))
            for item in value
        )
    )


def _clock_default(ground_truth: dict[str, Any]) -> dict[str, Any]:
    start_paused = os.environ.get("GYM_ANYTHING_RT_START_PAUSED") == "1"
    mode = str(os.environ.get("GYM_ANYTHING_RT_TIME_MODE") or "live")
    now_ns = time.monotonic_ns()
    return {
        "version": 1,
        "challenge_id": str(ground_truth.get("challenge_id") or ""),
        "mode": mode,
        "time_scale": time_scale(),
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
    clock = _read_json(path)
    if clock.get("challenge_id") != ground_truth.get("challenge_id"):
        clock = _clock_default(ground_truth)
        _write_json(path, clock)
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
    _write_json(state_dir / CLOCK_FILE, clock)
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
    _write_json(state_dir / CLOCK_FILE, clock)


def apply_time_status(
    state_dir: Path,
    ground_truth: dict[str, Any],
    status: dict[str, Any],
) -> None:
    if (
        str(ground_truth.get("mechanic_id") or "") != MECHANIC_ID
        or status.get("phase") != "completed"
    ):
        return
    clock = _load_clock(state_dir, ground_truth)
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
    _write_json(state_dir / CLOCK_FILE, clock)


def _probably_prime(value: int, rounds: int = 18) -> bool:
    if value < 2:
        return False
    for prime in _SMALL_PRIMES:
        if value == prime:
            return True
        if value % prime == 0:
            return False
    exponent = value - 1
    shifts = 0
    while exponent % 2 == 0:
        shifts += 1
        exponent //= 2
    for _ in range(rounds):
        base = secrets.randbelow(value - 3) + 2
        candidate = pow(base, exponent, value)
        if candidate in (1, value - 1):
            continue
        for _ in range(shifts - 1):
            candidate = pow(candidate, 2, value)
            if candidate == value - 1:
                break
        else:
            return False
    return True


def _prime(bits: int) -> int:
    while True:
        candidate = secrets.randbits(bits)
        candidate |= 1 | (1 << (bits - 1))
        if _probably_prime(candidate):
            return candidate


def _generate_key(challenge_id: str) -> dict[str, Any]:
    exponent = 65537
    while True:
        left = _prime(512)
        right = _prime(512)
        if left == right:
            continue
        phi = (left - 1) * (right - 1)
        if math.gcd(exponent, phi) == 1:
            break
    modulus = left * right
    private = pow(exponent, -1, phi)
    return {
        "version": 1,
        "challenge_id": challenge_id,
        "algorithm": ALGORITHM,
        "n_hex": format(modulus, "x"),
        "e": exponent,
        "d_hex": format(private, "x"),
        "created_wall_ns": time.time_ns(),
    }


def _public_key(key: dict[str, Any]) -> dict[str, Any]:
    return {
        "algorithm": ALGORITHM,
        "n_hex": str(key["n_hex"]),
        "e": int(key["e"]),
    }


def _ensure_key(
    state_dir: Path,
    ground_truth: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    challenge_id = str(ground_truth.get("challenge_id") or "")
    key_path = state_dir / KEY_FILE
    key = _read_json(key_path)
    if key.get("challenge_id") != challenge_id:
        key = _generate_key(challenge_id)
        _write_json(key_path, key)
    public_key = _public_key(key)
    if ground_truth.get(PUBLIC_KEY_FIELD) != public_key:
        ground_truth = dict(ground_truth)
        ground_truth[PUBLIC_KEY_FIELD] = public_key
        _write_json(state_dir / "ground_truth.json", ground_truth)
    return key, ground_truth


def _load_ledger(
    state_dir: Path,
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    path = state_dir / LEDGER_FILE
    challenge_id = str(ground_truth.get("challenge_id") or "")
    interaction = _interaction(ground_truth)
    ledger = _read_json(path)
    if ledger.get("challenge_id") != challenge_id:
        ledger = {
            "version": 1,
            "mechanic_id": MECHANIC_ID,
            "task_id": str(ground_truth.get("task_id") or ""),
            "challenge_id": challenge_id,
            "interaction": interaction,
            "clock_source": "server_active_task_clock_v1",
            "placements": {},
            "pending_gestures": {},
            "actions": [],
        }
        _write_json(path, ledger)
    return ledger


def begin_gesture(
    state_dir: Path,
    payload: dict[str, Any],
    ground_truth: dict[str, Any],
    witnessed_route: str,
) -> tuple[dict[str, Any], int]:
    error = _identity_error(payload, ground_truth)
    if error:
        return {"ok": False, "error": error}, 400
    interaction = _interaction(ground_truth)
    expected_route = (
        "simplified_selection"
        if interaction == "simplified"
        else "full_drag_begin"
    )
    if witnessed_route != expected_route:
        return {"ok": False, "error": "gesture surface does not match interaction"}, 400
    food_id = str(payload.get("food_id") or "")
    targets = ground_truth.get("targets") or {}
    if food_id not in targets:
        return {"ok": False, "error": "gesture food is not in this challenge"}, 400
    evidence = payload.get("event_evidence")
    if not isinstance(evidence, dict):
        return {"ok": False, "error": "gesture event evidence is missing"}, 400
    point = (
        evidence.get("point")
        if interaction == "simplified"
        else evidence.get("start_point")
    )
    if not _valid_point(point):
        return {"ok": False, "error": "gesture pointer geometry is incomplete"}, 400
    key, ground_truth = _ensure_key(state_dir, ground_truth)
    del key
    ledger = _load_ledger(state_dir, ground_truth)
    token = secrets.token_urlsafe(24)
    ledger["pending_gestures"][token] = {
        "food_id": food_id,
        "witnessed_route": witnessed_route,
        "created_task_time_ms": task_time_ms(state_dir, ground_truth),
        "created_wall_ns": time.time_ns(),
        "event_evidence_sha256": hashlib.sha256(
            json.dumps(
                evidence,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    _write_json(state_dir / LEDGER_FILE, ledger)
    return {"ok": True, "gesture_token": token}, 200


def record_action(
    state_dir: Path,
    payload: dict[str, Any],
    ground_truth: dict[str, Any],
    witnessed_route: str,
) -> tuple[dict[str, Any], int]:
    error = _identity_error(payload, ground_truth)
    if error:
        return {"ok": False, "error": error}, 400
    interaction = _interaction(ground_truth)
    expected_source = EXPECTED_SOURCES.get(interaction)
    if expected_source is None:
        return {"ok": False, "error": "interaction condition is invalid"}, 400
    food_id = str(payload.get("food_id") or "")
    kind = str(payload.get("kind") or "")
    destination = str(payload.get("destination") or "")
    expected_destination = {"start": "grill", "serve": "tray"}.get(kind)
    if expected_destination is None or destination != expected_destination:
        return {"ok": False, "error": "grill action destination is invalid"}, 400
    token = str(payload.get("gesture_token") or "")
    ledger = _load_ledger(state_dir, ground_truth)
    gesture = (ledger.get("pending_gestures") or {}).pop(token, None)
    if not isinstance(gesture, dict) or gesture.get("food_id") != food_id:
        return {"ok": False, "error": "grill action has no matching gesture"}, 400
    expected_gesture_route = (
        "simplified_selection"
        if interaction == "simplified"
        else "full_drag_begin"
    )
    if gesture.get("witnessed_route") != expected_gesture_route:
        return {"ok": False, "error": "grill action used the wrong gesture"}, 400
    event_evidence = payload.get("event_evidence")
    if not isinstance(event_evidence, dict):
        return {"ok": False, "error": "grill action lacks event evidence"}, 400
    if interaction == "full":
        if witnessed_route != "full_drop":
            return {"ok": False, "error": "full interaction requires the drop route"}, 400
        if (
            str(event_evidence.get("drop_zone") or "") != destination
        ):
            return {"ok": False, "error": "full interaction requires a matching drop event"}, 400
        start_point = event_evidence.get("start_point")
        end_point = event_evidence.get("end_point")
        if not (
            _valid_point(start_point)
            and _valid_point(end_point)
        ):
            return {"ok": False, "error": "drop event geometry is incomplete"}, 400
        event_surface = "pointer_drag"
    else:
        if witnessed_route != "simplified_proxy":
            return {"ok": False, "error": "simplified interaction requires the proxy route"}, 400
        expected_control = (
            "grill-start-selected" if kind == "start" else "grill-serve-selected"
        )
        if (
            str(event_evidence.get("control_id") or "") != expected_control
            or not _valid_point(event_evidence.get("point"))
        ):
            return {"ok": False, "error": "simplified interaction requires the matching proxy control"}, 400
        event_surface = "selection_plus_proxy_button"

    placements = ledger.get("placements") or {}
    prior = str(placements.get(food_id) or "prep")
    if (kind, prior) not in {("start", "prep"), ("serve", "grill")}:
        return {"ok": False, "error": "server grill state rejects this transition"}, 400
    witnessed_time = task_time_ms(state_dir, ground_truth)
    placements[food_id] = destination
    action = {
        "sequence": len(ledger.get("actions") or []) + 1,
        "kind": kind,
        "food_id": food_id,
        "input_source": expected_source,
        "event_surface": event_surface,
        "witnessed_route": witnessed_route,
        "task_time_ms": witnessed_time,
        "server_received_wall_ns": time.time_ns(),
        "gesture_created_wall_ns": int(gesture["created_wall_ns"]),
        "gesture_evidence_sha256": str(gesture["event_evidence_sha256"]),
        "action_evidence_sha256": hashlib.sha256(
            json.dumps(
                event_evidence,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    ledger["placements"] = placements
    ledger.setdefault("actions", []).append(action)
    ledger["pending_gestures"] = ledger.get("pending_gestures") or {}
    _write_json(state_dir / LEDGER_FILE, ledger)
    return {"ok": True, "witness_action": action}, 200


def _encoded_message(value: dict[str, Any], size: int) -> bytes:
    digest_info = _SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).digest()
    padding = b"\xff" * (size - len(digest_info) - 3)
    if len(padding) < 8:
        raise ValueError("RSA key is too short for SHA-256 attestation")
    return b"\x00\x01" + padding + b"\x00" + digest_info


def finalize(
    state_dir: Path,
    ground_truth: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    key = _read_json(state_dir / KEY_FILE)
    ledger = _load_ledger(state_dir, ground_truth)
    if (
        key.get("challenge_id") != ground_truth.get("challenge_id")
        or not ledger.get("actions")
    ):
        return None, "server-witnessed grill actions are missing"
    public_key = _public_key(key)
    if ground_truth.get(PUBLIC_KEY_FIELD) != public_key:
        return None, "server witness key is not bound to the hidden challenge"
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
    encoded = _encoded_message(witnessed, size)
    signature = pow(int.from_bytes(encoded, "big"), private, modulus)
    return {
        **witnessed,
        "signature_hex": signature.to_bytes(size, "big").hex(),
    }, None
