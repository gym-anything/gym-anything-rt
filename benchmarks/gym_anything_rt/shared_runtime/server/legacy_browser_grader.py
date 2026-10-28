from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Callable


ACCEPTS_BROWSER_RUNTIME_CONTEXT = True
SLOT_REEL_PUBLIC_KEY_FIELD = "slot_reel_interaction_public_key"
SLOT_REEL_ALGORITHM = "rsa-sha256-pkcs1-v1_5"
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex(
    "3031300d060960864801650304020105000420"
)


def _ghost(result: dict[str, Any], truth: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    expected = {str(key): int(value) for key, value in (truth.get("expected_positions") or {}).items()}
    try:
        placements = {str(key): int(value) for key, value in (result.get("placements") or {}).items()}
    except (TypeError, ValueError):
        placements = {}
    condition = truth.get("control_condition")
    if condition is not None:
        if state.get("control_condition") != condition:
            return {"graded": True, "passed": False, "feedback": "public interaction condition differs from ghost-jigsaw contract"}
        expected_source = {"simplified": "piece_slot_clicks", "full": "piece_drag"}.get(str(condition.get("interaction") or ""))
        if expected_source is None:
            return {"graded": True, "passed": False, "feedback": "ghost-jigsaw interaction condition is invalid"}
        sources = result.get("placement_sources") or {}
        if not isinstance(sources, dict) or any(sources.get(piece_id) != expected_source for piece_id in expected):
            return {"graded": True, "passed": False, "feedback": "ghost-jigsaw placement uses the wrong interaction input"}
    correct = sum(1 for key, value in expected.items() if placements.get(key) == value)
    passed = bool(expected) and placements == expected
    return {"graded": True, "passed": passed, "feedback": f"pieces {correct}/{len(expected)}"}


def _constellation(result: dict[str, Any], truth: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    condition = truth.get("control_condition")
    if condition is not None:
        if state.get("control_condition") != condition:
            return {"graded": True, "passed": False, "feedback": "public interaction condition differs from constellation contract"}
        interaction = str(condition.get("interaction") or "")
        expected_source = {"simplified": "coordinate_controls", "full": "canvas_pointer"}.get(interaction)
        if expected_source is None:
            return {"graded": True, "passed": False, "feedback": "constellation interaction condition is invalid"}
        if result.get("input_source") != expected_source:
            return {"graded": True, "passed": False, "feedback": "constellation submission uses the wrong interaction input"}
    expected = truth.get("expected_click") or {}
    click = result.get("click") or {}
    try:
        distance = math.hypot(
            float(click.get("x")) - float(expected.get("x")),
            float(click.get("y")) - float(expected.get("y")),
        )
        radius = float(expected.get("radius"))
    except (TypeError, ValueError):
        distance = math.inf
        radius = 0.0
    passed = distance <= radius
    return {"graded": True, "passed": passed, "feedback": f"click distance {distance:.2f}px"}


def _grillmaster(result: dict[str, Any], truth: dict[str, Any], _state: dict[str, Any]) -> dict[str, Any]:
    targets = truth.get("targets") or {}
    durations = result.get("durations_ms") or {}
    correct = 0
    for food_id, target in targets.items():
        try:
            elapsed = float(durations.get(food_id))
            target_ms = float(target.get("target_ms"))
            tolerance_ms = float(target.get("tolerance_ms"))
        except (TypeError, ValueError):
            continue
        if abs(elapsed - target_ms) <= tolerance_ms:
            correct += 1
    passed = bool(targets) and correct == len(targets) and set(durations) == set(targets)
    return {"graded": True, "passed": passed, "feedback": f"foods {correct}/{len(targets)}"}


def _rotating_keyboard(result: dict[str, Any], truth: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    expected = str(truth.get("target") or "")
    submitted = str(result.get("text") or "").upper()
    condition = truth.get("control_condition")
    if condition is not None:
        if state.get("control_condition") != condition:
            return {"graded": True, "passed": False, "feedback": "public interaction condition differs from rotating-keyboard contract"}
        expected_source = {"simplified": "physical_keyboard", "full": "onscreen_keys"}.get(str(condition.get("interaction") or ""))
        if expected_source is None or result.get("input_source") != expected_source:
            return {"graded": True, "passed": False, "feedback": "rotating-keyboard code uses the wrong interaction input"}
    passed = bool(expected) and submitted == expected
    return {"graded": True, "passed": passed, "feedback": "code accepted" if passed else "code rejected"}


SLOT_REEL_MAX_ELAPSED_MS = 90_000.0


def _slot_reel_encoded_message(
    value: dict[str, Any],
    size: int,
) -> bytes:
    digest_info = _SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).digest()
    padding = b"\xff" * (size - len(digest_info) - 3)
    if len(padding) < 8:
        raise ValueError("slot-reel witness key is too short")
    return b"\x00\x01" + padding + b"\x00" + digest_info


def _slot_reel_witness(
    result: dict[str, Any],
    truth: dict[str, Any],
    runtime_context: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if (
        isinstance(runtime_context, dict)
        and runtime_context.get("surface")
        == "static_browser_nonauthoritative"
    ):
        witness = runtime_context.get("witness")
        if not isinstance(witness, dict):
            return None, "static browser slot-reel witness is missing"
        if str(witness.get("clock_source") or "") != "static_browser_task_clock_v1":
            return None, "static browser slot-reel clock source is invalid"
    else:
        witness = result.get("trusted_witness")
        if not isinstance(witness, dict):
            return None, "server-witnessed slot-reel actions are missing"
        expected_key = truth.get(SLOT_REEL_PUBLIC_KEY_FIELD)
        if not isinstance(expected_key, dict):
            return None, "slot-reel witness key is not bound to the hidden challenge"
        if witness.get("public_key") != expected_key:
            return None, "slot-reel witness public key differs from the hidden challenge"
        signature_hex = str(witness.get("signature_hex") or "")
        signed = dict(witness)
        signed.pop("signature_hex", None)
        try:
            modulus = int(str(expected_key["n_hex"]), 16)
            exponent = int(expected_key["e"])
            if expected_key.get("algorithm") != SLOT_REEL_ALGORITHM:
                raise ValueError("unexpected algorithm")
            signature = int(signature_hex, 16)
            size = (modulus.bit_length() + 7) // 8
            expected = _slot_reel_encoded_message(signed, size)
            actual = pow(signature, exponent, modulus).to_bytes(size, "big")
        except (KeyError, TypeError, ValueError, OverflowError):
            return None, "slot-reel witness signature is malformed"
        if actual != expected:
            return None, "slot-reel witness signature is invalid"
        if str(witness.get("clock_source") or "") != "server_active_task_clock_v1":
            return None, "slot-reel server witness clock source is invalid"
    if (
        str(witness.get("mechanic_id") or "") != "slot_reel_capture"
        or str(witness.get("task_id") or "") != str(truth.get("task_id") or "")
        or str(witness.get("challenge_id") or "")
        != str(truth.get("challenge_id") or "")
    ):
        return None, "slot-reel witness identity is invalid"
    expected_interaction = str(
        (truth.get("control_condition") or {}).get("interaction")
        or "full"
    )
    if str(witness.get("interaction") or "") != expected_interaction:
        return None, "slot-reel witness interaction is invalid"
    return witness, None


def _slot_reel_replay(
    result: dict[str, Any],
    truth: dict[str, Any],
    state: dict[str, Any],
    *,
    require_server_evidence: bool,
) -> tuple[bool, str, int]:
    expected = str(truth.get("sequence") or "")
    expected_reels = [str(item) for item in truth.get("reel_ids") or []]
    public_reels = state.get("reels")
    if (
        not expected
        or len(expected) != len(expected_reels)
        or not isinstance(public_reels, list)
        or len(public_reels) != len(expected_reels)
    ):
        return False, "slot-reel challenge geometry is invalid", 0
    condition = truth.get("control_condition")
    if condition is not None:
        if state.get("control_condition") != condition:
            return False, "public interaction condition differs from slot-reel contract", 0
        interaction = str(condition.get("interaction") or "")
    else:
        interaction = "full"
    expected_source = {
        "simplified": "capture_button",
        "full": "physical_keyboard",
    }.get(interaction)
    expected_surface = {
        "simplified": "capture_button_click",
        "full": "keyboard_keydown",
    }.get(interaction)
    actions = result.get("actions")
    if (
        expected_source is None
        or expected_surface is None
        or not isinstance(actions, list)
    ):
        return False, "slot-reel interaction transcript is invalid", 0

    capture_window_ratio = float(
        state.get(
            "capture_window_ratio",
            truth.get("capture_window_ratio", 1.0),
        )
    )
    if not math.isfinite(capture_window_ratio) or not 0.0 < capture_window_ratio <= 1.0:
        return False, "slot-reel capture window is invalid", 0

    normalized_reels = []
    for index, (raw_reel, reel_id, target) in enumerate(
        zip(public_reels, expected_reels, expected)
    ):
        if not isinstance(raw_reel, dict):
            return False, "slot-reel challenge geometry is invalid", 0
        tokens = raw_reel.get("tokens")
        try:
            interval_ms = int(raw_reel.get("interval_ms"))
            phase = int(raw_reel.get("phase") or 0)
        except (TypeError, ValueError):
            return False, "slot-reel challenge timing is invalid", 0
        if (
            str(raw_reel.get("id") or "") != reel_id
            or str(raw_reel.get("target") or "").upper() != target
            or not isinstance(tokens, list)
            or not tokens
            or any(not isinstance(token, str) or not token for token in tokens)
            or tokens.count(target) != 1
            or interval_ms <= 0
            or not 0 <= phase < len(tokens)
        ):
            return False, f"slot-reel {index + 1} contract is invalid", 0
        normalized_reels.append(
            {
                "id": reel_id,
                "target": target,
                "tokens": tokens,
                "interval_ms": interval_ms,
                "phase": phase,
            }
        )

    active_index = 0
    rejected_count = 0
    previous_elapsed = -1.0
    previous_server_elapsed = -1.0
    previous_wall_ns = -1
    for sequence, action in enumerate(actions, start=1):
        if not isinstance(action, dict) or action.get("sequence") != sequence:
            return False, "slot-reel action sequence is invalid", rejected_count
        elapsed_raw = action.get("elapsed_ms")
        if (
            isinstance(elapsed_raw, bool)
            or not isinstance(elapsed_raw, (int, float))
        ):
            return False, "slot-reel action is missing timing evidence", rejected_count
        elapsed_ms = float(elapsed_raw)
        if (
            not math.isfinite(elapsed_ms)
            or elapsed_ms < 0.0
            or elapsed_ms > SLOT_REEL_MAX_ELAPSED_MS
            or elapsed_ms < previous_elapsed
        ):
            return False, "slot-reel action timing is invalid", rejected_count
        previous_elapsed = elapsed_ms
        if require_server_evidence:
            server_elapsed_raw = action.get("server_task_time_ms")
            client_elapsed_raw = action.get("client_elapsed_ms")
            wall_raw = action.get("server_received_wall_ns")
            if (
                isinstance(server_elapsed_raw, bool)
                or not isinstance(server_elapsed_raw, (int, float))
                or isinstance(client_elapsed_raw, bool)
                or not isinstance(client_elapsed_raw, (int, float))
            ):
                return False, "slot-reel server timing evidence is missing", rejected_count
            try:
                server_elapsed = float(server_elapsed_raw)
                client_elapsed = float(client_elapsed_raw)
                wall_ns = int(wall_raw)
            except (TypeError, ValueError):
                return False, "slot-reel server timing evidence is invalid", rejected_count
            if (
                not math.isfinite(server_elapsed)
                or not math.isfinite(client_elapsed)
                or server_elapsed < previous_server_elapsed
                or wall_ns <= previous_wall_ns
                or abs(server_elapsed - elapsed_ms) > 0.001
                or abs(client_elapsed - server_elapsed) > 250.0
            ):
                return False, "slot-reel server timing evidence is invalid", rejected_count
            previous_server_elapsed = server_elapsed
            previous_wall_ns = wall_ns
        if active_index >= len(normalized_reels):
            return False, "slot-reel transcript continues after completion", rejected_count

        reel = normalized_reels[active_index]
        if str(action.get("reel_id") or "") != reel["id"]:
            return False, "slot-reel action targets the wrong active reel", rejected_count
        if action.get("input_source") != expected_source:
            return False, "slot-reel capture uses the wrong interaction input", rejected_count
        if action.get("event_surface") != expected_surface:
            return False, "slot-reel action uses the wrong event surface", rejected_count

        entered_key = action.get("entered_key")
        if expected_source == "capture_button":
            if entered_key not in {None, ""}:
                return False, "slot-reel capture button transcript contains a typed key", rejected_count
            normalized_key = ""
            key_matches = True
        else:
            normalized_key = str(entered_key or "").upper()
            if (
                len(normalized_key) != 1
                or not normalized_key.isascii()
                or not normalized_key.isalnum()
            ):
                return False, "slot-reel keyboard action is invalid", rejected_count
            key_matches = normalized_key == reel["target"]

        token_index = (
            math.floor(elapsed_ms / reel["interval_ms"]) + reel["phase"]
        ) % len(reel["tokens"])
        expected_token = reel["tokens"][token_index]
        cycle_position = (elapsed_ms % reel["interval_ms"]) / reel["interval_ms"]
        capture_ready = (
            capture_window_ratio >= 1.0
            or abs(cycle_position - 0.5) <= capture_window_ratio / 2.0
        )
        expected_accepted = (
            expected_token == reel["target"]
            and capture_ready
            and key_matches
        )
        if str(action.get("observed_token") or "") != expected_token:
            return False, "slot-reel observed symbol disagrees with task-time replay", rejected_count
        if not isinstance(action.get("accepted"), bool) or action["accepted"] != expected_accepted:
            return False, "slot-reel accepted outcome disagrees with task-time replay", rejected_count
        if expected_accepted:
            active_index += 1
        else:
            rejected_count += 1

    if active_index != len(normalized_reels):
        return False, "slot-reel transcript does not capture every reel", rejected_count
    return True, "slot-reel task-time replay accepted", rejected_count


def _slot_reel(
    result: dict[str, Any],
    truth: dict[str, Any],
    state: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if str(result.get("challenge_id") or "") != str(truth.get("challenge_id") or ""):
        return {"graded": True, "passed": False, "feedback": "stale challenge"}
    witness, witness_error = _slot_reel_witness(
        result,
        truth,
        runtime_context,
    )
    if witness_error or witness is None:
        return {
            "graded": True,
            "passed": False,
            "feedback": witness_error or "slot-reel witness is missing",
        }
    witnessed_result = dict(result)
    witnessed_result["actions"] = witness.get("actions")
    expected = str(truth.get("sequence") or "")
    submitted = str(result.get("captured_sequence") or "").upper()
    expected_reels = [str(item) for item in truth.get("reel_ids") or []]
    raw_frozen_reels = result.get("frozen_reel_ids")
    if not isinstance(raw_frozen_reels, list):
        return {"graded": True, "passed": False, "feedback": "slot-reel frozen-reel transcript is invalid"}
    frozen_reels = [str(item) for item in raw_frozen_reels]
    try:
        wrong_keys = int(result.get("wrong_keys") or 0)
        max_strikes = int(truth.get("max_strikes") or 3)
    except (TypeError, ValueError):
        return {"graded": True, "passed": False, "feedback": "slot-reel strike transcript is invalid"}
    replay_ok, replay_feedback, replay_wrong_keys = _slot_reel_replay(
        witnessed_result,
        truth,
        state,
        require_server_evidence=(
            witness.get("clock_source")
            == "server_active_task_clock_v1"
        ),
    )
    if not replay_ok:
        return {"graded": True, "passed": False, "feedback": replay_feedback}
    if replay_wrong_keys != wrong_keys:
        return {"graded": True, "passed": False, "feedback": "slot-reel strike transcript is invalid"}
    passed = (
        bool(expected)
        and submitted == expected
        and frozen_reels == expected_reels
        and wrong_keys < max_strikes
    )
    return {
        "graded": True,
        "passed": passed,
        "feedback": f"captured {len(submitted)}/{len(expected)}; strikes {wrong_keys}/{max_strikes}",
    }


def _domino_axis_angle(angle_degrees: float) -> float:
    return (angle_degrees + 90.0) % 180.0 - 90.0


def _domino_replay(
    result: dict[str, Any],
    truth: dict[str, Any],
) -> tuple[bool, str, float, set[tuple[str, str]]]:
    loose_ids = {str(item) for item in truth.get("loose_ids") or []}
    raw = result.get("placements") or {}
    if not isinstance(raw, dict) or {str(key) for key in raw} != loose_ids:
        return False, "not all loose dominoes were placed", 0.0, set()

    poses: list[dict[str, float | str]] = []
    for item in truth.get("fixed_dominoes") or []:
        try:
            poses.append({
                "id": str(item["id"]),
                "x": float(item["x"]),
                "y": float(item["y"]),
                "axis": _domino_axis_angle(float(item.get("angle") or 0.0)),
            })
        except (KeyError, TypeError, ValueError):
            return False, "hidden fixed-domino geometry is invalid", 0.0, set()
    for domino_id in loose_ids:
        item = raw.get(domino_id)
        if not isinstance(item, dict):
            return False, "domino placement is invalid", 0.0, set()
        try:
            x = float(item.get("x"))
            y = float(item.get("y"))
            angle = float(item.get("angle"))
        except (TypeError, ValueError):
            return False, "domino placement is invalid", 0.0, set()
        if not all(math.isfinite(value) for value in (x, y, angle)):
            return False, "domino placement is non-finite", 0.0, set()
        axis = _domino_axis_angle(angle)
        if not 18.0 <= x <= 702.0:
            return False, f"domino {domino_id} lies outside the physics board", 0.0, set()
        if abs(axis) > 10.0:
            return False, f"domino {domino_id} is not standing on its physical axis", 0.0, set()
        radians = math.radians(axis)
        bottom_extent = abs(math.cos(radians)) * 36.0 + abs(math.sin(radians)) * 7.0
        expected_y = 340.0 - bottom_extent
        if abs(y - expected_y) > 3.0:
            return False, f"domino {domino_id} is not resting on the tabletop", 0.0, set()
        poses.append({"id": domino_id, "x": x, "y": y, "axis": axis})

    expected_ids = {str(item) for item in truth.get("expected_body_ids") or []}
    if {str(item["id"]) for item in poses} != expected_ids:
        return False, "replay body identities differ from the generated world", 0.0, set()
    poses.sort(key=lambda item: float(item["x"]))
    if not poses or str(poses[0]["id"]) != str(truth.get("first_body_id") or ""):
        return False, "the designated first domino is not first in the replay", 0.0, set()

    replay_edges: set[tuple[str, str]] = set()
    gaps: list[float] = []
    for left, right in zip(poses, poses[1:]):
        gap = float(right["x"]) - float(left["x"])
        if gap <= 0:
            return False, "domino order is not physically valid", 0.0, set()
        left_axis = math.radians(float(left["axis"]))
        right_axis = math.radians(float(right["axis"]))
        left_half_width = abs(math.cos(left_axis)) * 7.0 + abs(math.sin(left_axis)) * 36.0
        right_half_width = abs(math.cos(right_axis)) * 7.0 + abs(math.sin(right_axis)) * 36.0
        if gap < left_half_width + right_half_width - 1.0:
            return False, "domino placements overlap before the run", 0.0, set()
        if gap > 60.0:
            return False, f"domino gap {gap:.2f}px exceeds physical toppling reach", 0.0, set()
        gaps.append(gap)
        replay_edges.add(tuple(sorted((str(left["id"]), str(right["id"])))))

    bell = truth.get("bell") or {}
    bell_id = str(truth.get("bell_body_id") or "bell-body")
    try:
        bell_surface_gap = float(bell.get("x")) - 26.0 - float(poses[-1]["x"])
    except (TypeError, ValueError):
        return False, "hidden bell geometry is invalid", 0.0, set()
    if not 0.0 <= bell_surface_gap <= 60.0:
        return False, "the final domino cannot physically reach the bell", 0.0, set()
    gaps.append(bell_surface_gap)
    replay_edges.add(tuple(sorted((str(poses[-1]["id"]), bell_id))))

    mean_excess = sum(max(0.0, gap - 40.0) for gap in gaps) / max(1, len(gaps))
    max_excess = max((max(0.0, gap - 40.0) for gap in gaps), default=0.0)
    loose_axis_error = sum(
        abs(float(item["axis"])) for item in poses if str(item["id"]) in loose_ids
    ) / max(1, len(loose_ids))
    replay_swing = max(
        0.0,
        0.68 - 0.010 * mean_excess - 0.004 * max_excess - 0.006 * loose_axis_error,
    )

    submitted_pairs = result.get("collision_pairs")
    if not isinstance(submitted_pairs, list):
        return False, "collision transcript is missing", replay_swing, replay_edges
    normalized_pairs: list[tuple[str, str]] = []
    for pair in submitted_pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            return False, "collision transcript is malformed", replay_swing, replay_edges
        left, right = str(pair[0]), str(pair[1])
        if not left or not right or left == right:
            return False, "collision transcript is malformed", replay_swing, replay_edges
        normalized_pairs.append(tuple(sorted((left, right))))
    if len(normalized_pairs) != len(set(normalized_pairs)):
        return False, "collision transcript contains duplicate contacts", replay_swing, replay_edges
    if set(normalized_pairs) != replay_edges:
        return False, "collision transcript disagrees with independent pose replay", replay_swing, replay_edges
    return True, "", replay_swing, replay_edges


def _domino(result: dict[str, Any], truth: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if str(result.get("challenge_id") or "") != str(truth.get("challenge_id") or ""):
        return {"graded": True, "passed": False, "feedback": "stale domino challenge"}
    loose_ids = set(str(item) for item in truth.get("loose_ids") or [])
    condition = truth.get("control_condition")
    if condition is not None:
        if state.get("control_condition") != condition:
            return {"graded": True, "passed": False, "feedback": "public interaction condition differs from domino contract"}
        expected_source = {"simplified": "domino_click_place", "full": "domino_drag"}.get(
            str(condition.get("interaction") or "")
        )
        sources = result.get("placement_sources") or {}
        if (
            expected_source is None
            or not isinstance(sources, dict)
            or any(sources.get(domino_id) != expected_source for domino_id in loose_ids)
        ):
            return {"graded": True, "passed": False, "feedback": "domino placement uses the wrong interaction input"}
    replay_ok, replay_error, replay_swing, replay_edges = _domino_replay(result, truth)
    if not replay_ok:
        return {"graded": True, "passed": False, "feedback": replay_error}
    minimum_swing = float(truth.get("minimum_bell_swing_radians") or 0.03)
    try:
        bell_swing = abs(float(result.get("bell_peak_angle") or 0.0))
    except (TypeError, ValueError):
        bell_swing = 0.0
    physics_engine = str(result.get("physics_engine") or "")
    passed = (
        result.get("run_completed") is True
        and result.get("bell_hit") is True
        and math.isfinite(bell_swing)
        and bell_swing <= 1.25
        and bell_swing >= minimum_swing
        and replay_swing >= minimum_swing
        and physics_engine == "matter-js@0.20.0"
    )
    return {
        "graded": True,
        "passed": passed,
        "feedback": (
            f"independent pose replay contacts {len(replay_edges)}; "
            f"replay swing={replay_swing:.3f} rad; browser swing={bell_swing:.3f} rad"
        ),
    }


def _funeral(result: dict[str, Any], truth: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    condition = truth.get("control_condition")
    if condition is not None and str(result.get("challenge_id") or "") != str(truth.get("challenge_id") or ""):
        return {"graded": True, "passed": False, "feedback": "stale funeral challenge"}
    required_events = [str(item) for item in truth.get("required_events") or []]
    events = [str(item) for item in result.get("events") or []]
    max_cells_value = truth.get("moss_cells")
    max_cells = int(max_cells_value) if max_cells_value is not None else 24
    cells = set()
    for item in result.get("brushed_cells") or []:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= value < max_cells:
            cells.add(value)
    flowers = [str(item) for item in result.get("gathered_flower_ids") or []]
    expected_flowers = [str(item) for item in truth.get("flower_ids") or []]
    expected_order = [str(item) for item in truth.get("flower_order") or []]
    flowers_match = flowers == expected_order if expected_order else len(flowers) == len(expected_flowers) and set(flowers) == set(expected_flowers)
    threshold_value = truth.get("brush_threshold")
    threshold = int(threshold_value) if threshold_value is not None else 17
    completed = result.get("completed") is True
    interaction_ok = True
    if condition is not None:
        expected_surface = str(condition.get("interaction") or "")
        surfaces = result.get("action_surfaces") or []
        expected_actions = [{"event": event, "surface": expected_surface} for event in required_events]
        flower_sources = result.get("flower_sources") or {}
        interaction_ok = (
            state.get("control_condition") == condition
            and expected_surface in {"simplified", "full"}
            and result.get("interaction_mode") == expected_surface
            and surfaces == expected_actions
            and isinstance(flower_sources, dict)
            and all(flower_sources.get(flower_id) == expected_surface for flower_id in expected_flowers)
        )
    passed = completed and events == required_events and len(cells) >= threshold and flowers_match and interaction_ok
    return {
        "graded": True,
        "passed": passed,
        "feedback": (
            f"ritual {len(events)}/{len(required_events)}; moss {len(cells)}/{threshold}; "
            f"flowers {len(flowers)}/{len(expected_flowers)}"
        ),
    }


GRADERS: dict[str, Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "motion_only_ghost_jigsaw": _ghost,
    "cursor_constellation_hunt": _constellation,
    "parallel_grillmaster": _grillmaster,
    "rotating_keyboard": _rotating_keyboard,
    "slot_reel_capture": _slot_reel,
    "domino_autopsy": _domino,
    "funeral_ritual": _funeral,
}


def grade(
    result: dict[str, Any],
    ground_truth: dict[str, Any],
    public_state: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mechanic_id = str(ground_truth.get("mechanic_id") or result.get("mechanic_id") or "")
    if mechanic_id == "slot_reel_capture":
        return _slot_reel(
            result,
            ground_truth,
            public_state,
            runtime_context,
        )
    grader = GRADERS.get(mechanic_id)
    if grader is None:
        return {"graded": False, "passed": False, "feedback": f"no legacy grader for {mechanic_id}"}
    return grader(result, ground_truth, public_state)
