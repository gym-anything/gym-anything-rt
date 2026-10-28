from __future__ import annotations

import copy
import math
from typing import Any


MECHANIC_ID = "consent_gauntlet"


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _bind(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> str | None:
    if any(str(value.get("mechanic_id") or "") != MECHANIC_ID for value in (payload, truth, public)):
        return "mechanic mismatch"
    for key in ("task_id", "challenge_id"):
        expected = str(truth.get(key) or "")
        if not expected or str(payload.get(key) or "") != expected or str(public.get(key) or "") != expected:
            return f"stale or mismatched {key}"
    return None


def _contract(truth: dict[str, Any], public: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bool], dict[str, bool], str, dict[str, Any]]:
    surface = truth.get("surface")
    if not isinstance(surface, dict) or public.get("surface") != surface:
        raise ValueError("public consent surface differs from replay contract")
    parameters = truth.get("parameters")
    if not isinstance(parameters, dict) or public.get("parameters") != parameters:
        raise ValueError("difficulty parameters differ from replay contract")
    condition = truth.get("control_condition")
    if condition != public.get("control_condition"):
        raise ValueError("public control condition differs from replay contract")
    if condition is not None and condition.get("difficulty_parameters") != parameters:
        raise ValueError("condition parameters differ from generated surface")
    interaction = str((condition or {}).get("interaction") or "full")
    if interaction not in {"simplified", "full"}:
        raise ValueError("interaction mode is invalid")
    targets = truth.get("targets")
    initial_states = truth.get("initial_states")
    if not isinstance(targets, dict) or not isinstance(initial_states, dict):
        raise ValueError("purpose contract is missing")
    purpose_ids = {str(item.get("id") or "") for item in surface.get("purposes") or []}
    if not purpose_ids or set(targets) != purpose_ids or set(initial_states) != purpose_ids:
        raise ValueError("purpose identities differ from replay contract")
    if any(not isinstance(value, bool) for value in (*targets.values(), *initial_states.values())):
        raise ValueError("purpose states must be boolean")
    return copy.deepcopy(surface), dict(targets), dict(initial_states), interaction, copy.deepcopy(parameters)


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("value is not a finite number")
    return float(value)


def _angle_distance(first: float, second: float) -> float:
    return abs((first - second + 180) % 360 - 180)


def _gateway_gesture(
    event: dict[str, Any],
    option: dict[str, Any],
    parameters: dict[str, Any],
    surface_phase: float,
    stage: str,
    stage_started_ms: float,
) -> None:
    try:
        offset = _finite_number(event.get("pointer_offset_norm"))
        reported_phase = _finite_number(event.get("phase_deg"))
        pointer_x = _finite_number(event.get("pointer_x_norm"))
        pointer_y = _finite_number(event.get("pointer_y_norm"))
        center_x = _finite_number(event.get("card_center_x_norm"))
        center_y = _finite_number(event.get("card_center_y_norm"))
        card_width = _finite_number(event.get("card_width_norm"))
        card_height = _finite_number(event.get("card_height_norm"))
        event_time = _finite_number(event.get("task_time_ms"))
        option_offset = _finite_number(option.get("angle_offset_deg"))
    except ValueError as exc:
        raise ValueError(f"moving option lacks replayable pointer geometry: {exc}") from exc
    if not 0 <= offset <= 0.85:
        raise ValueError("moving option click fell outside its visible card")
    if not all(0 <= value <= 1 for value in (pointer_x, pointer_y, center_x, center_y)):
        raise ValueError("moving option geometry fell outside the consent orbit")
    if not 0.03 <= card_width <= 0.4 or not 0.03 <= card_height <= 0.3:
        raise ValueError("moving option reports an implausible visible card size")
    elapsed = max(0.0, event_time - stage_started_ms)
    speed = float(parameters.get("orbit_speed_deg_per_second") or 0)
    expected_phase = surface_phase + (33 if stage == "final" else 0)
    if parameters.get("moving_gateways"):
        expected_phase += elapsed * speed / 1000
    phase_tolerance = 0.8 if parameters.get("moving_gateways") else 0.08
    if _angle_distance(reported_phase, expected_phase) > phase_tolerance:
        raise ValueError("moving option phase disagrees with task-time replay")
    radians = math.radians(reported_phase + option_offset)
    expected_x = 0.5 + math.cos(radians) * 0.37
    expected_y = 0.5 + math.sin(radians) * 0.31
    if abs(center_x - expected_x) > 0.008 or abs(center_y - expected_y) > 0.008:
        raise ValueError("moving option center disagrees with orbital geometry")
    dx = (pointer_x - center_x) / (card_width / 2)
    dy = (pointer_y - center_y) / (card_height / 2)
    recomputed_offset = math.hypot(dx, dy)
    if recomputed_offset > 0.9 or abs(recomputed_offset - offset) > 0.08:
        raise ValueError("moving option pointer disagrees with its visible bounds")


def _gesture(event: dict[str, Any], before: bool, after: bool) -> None:
    gesture = event.get("gesture")
    if not isinstance(gesture, dict):
        raise ValueError("direct switch event lacks gesture proof")
    start = gesture.get("start_fraction")
    end = gesture.get("end_fraction")
    travel = gesture.get("travel_px")
    samples = gesture.get("sample_count")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in (start, end, travel)):
        raise ValueError("direct switch gesture has invalid geometry")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 2:
        raise ValueError("direct switch gesture has too few movement samples")
    expected_start = 0.82 if before else 0.18
    expected_end = 0.82 if after else 0.18
    if abs(float(start) - expected_start) > 0.08 or abs(float(end) - expected_end) > 0.08:
        raise ValueError("direct switch gesture disagrees with visible endpoints")
    if float(travel) < 24:
        raise ValueError("stationary click is not a direct switch gesture")


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    binding = _bind(payload, truth, public)
    if binding:
        return _fail(binding)
    try:
        surface, targets, initial_states, interaction, parameters = _contract(truth, public)
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"invalid consent contract: {exc}")
    if payload.get("interaction_mode") != interaction:
        return _fail("submitted interaction mode differs from task condition")
    events = payload.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= 300:
        return _fail("consent transcript is missing or outside limits")

    options = {
        str(option["id"]): {**option, "stage": stage}
        for stage, key in (("entry", "entry_options"), ("final", "final_options"))
        for option in surface.get(key) or []
    }
    drawers = {str(item["id"]): item for item in surface.get("drawers") or []}
    purposes = {str(item["id"]): item for item in surface.get("purposes") or []}
    traps = {str(item["id"]): item for item in surface.get("reset_traps") or []}
    links = list(surface.get("links") or [])
    states = dict(initial_states)
    current_drawer = next(iter(drawers), "")
    stage = "entry"
    terminal = None
    activated_links: set[str] = set()
    last_task_time = -1.0
    stage_started_ms = 0.0
    surface_phase = float(surface.get("phase_deg") or 0)
    sources = {
        "full": {"gateway": "orbit_card", "drawer": "drawer_tab", "purpose": "switch_drag", "trap": "trap_slider"},
        "simplified": {"gateway": "option_proxy", "drawer": "drawer_navigator", "purpose": "switch_direction_button", "trap": "trap_proxy"},
    }[interaction]

    try:
        for sequence, event in enumerate(events, 1):
            if terminal is not None:
                raise ValueError("events continue after a terminal consent decision")
            if not isinstance(event, dict) or event.get("sequence") != sequence:
                raise ValueError(f"event {sequence} has an invalid sequence")
            task_time = _finite_number(event.get("task_time_ms"))
            if not 0 <= task_time <= 180_000 or task_time < last_task_time:
                raise ValueError(f"event {sequence} has invalid task-time order")
            last_task_time = task_time
            event_type = event.get("type")
            item_id = str(event.get("id") or "")
            if event_type == "gateway":
                option = options.get(item_id)
                if option is None or option["stage"] != stage:
                    raise ValueError(f"event {sequence} names an unavailable gateway option")
                if event.get("input_source") != sources["gateway"]:
                    raise ValueError(f"event {sequence} uses the wrong gateway surface")
                if interaction == "full":
                    _gateway_gesture(event, option, parameters, surface_phase, stage, stage_started_ms)
                if stage == "entry":
                    if option.get("action") == "manage":
                        stage = "preferences"
                    else:
                        terminal = "accepted_at_entry"
                else:
                    terminal = "committed" if option.get("action") == "commit" else "accepted_at_final"
            elif event_type == "drawer":
                if stage != "preferences" or item_id not in drawers:
                    raise ValueError(f"event {sequence} names an unavailable drawer")
                if event.get("input_source") != sources["drawer"]:
                    raise ValueError(f"event {sequence} uses the wrong drawer surface")
                if event.get("before") != current_drawer or event.get("after") != item_id:
                    raise ValueError(f"event {sequence} has a stale drawer transition")
                current_drawer = item_id
            elif event_type == "purpose":
                purpose = purposes.get(item_id)
                if stage != "preferences" or purpose is None or purpose.get("drawer_id") != current_drawer:
                    raise ValueError(f"event {sequence} operates an unavailable purpose")
                if event.get("input_source") != sources["purpose"]:
                    raise ValueError(f"event {sequence} uses the wrong switch surface")
                before, after = event.get("before"), event.get("after")
                if not isinstance(before, bool) or not isinstance(after, bool) or before != states[item_id] or after is before:
                    raise ValueError(f"event {sequence} has an invalid switch transition")
                if interaction == "full":
                    _gesture(event, before, after)
                states[item_id] = after
                effects = []
                for link in links:
                    if link.get("source_id") != item_id:
                        continue
                    activated_links.add(str(link["id"]))
                    target_id = str(link.get("target_id") or "")
                    target_before = states[target_id]
                    target_after = not target_before
                    states[target_id] = target_after
                    effects.append({"link_id": link["id"], "id": target_id, "before": target_before, "after": target_after})
                if event.get("effects") != effects:
                    raise ValueError(f"event {sequence} reports incorrect linked-switch effects")
            elif event_type == "trap":
                trap = traps.get(item_id)
                if stage != "preferences" or trap is None or trap.get("drawer_id") != current_drawer:
                    raise ValueError(f"event {sequence} operates an unavailable reset control")
                if event.get("input_source") != sources["trap"]:
                    raise ValueError(f"event {sequence} uses the wrong reset surface")
                if interaction == "full":
                    _gesture(event, False, True)
                effects = []
                for purpose_id in drawers[current_drawer].get("purpose_ids") or []:
                    before = states[purpose_id]
                    after = initial_states[purpose_id]
                    states[purpose_id] = after
                    effects.append({"id": purpose_id, "before": before, "after": after})
                if event.get("effects") != effects:
                    raise ValueError(f"event {sequence} reports incorrect reset effects")
            elif event_type == "review":
                if stage != "preferences" or event.get("input_source") != "review_button":
                    raise ValueError(f"event {sequence} cannot open final review")
                stage = "final"
                stage_started_ms = task_time
            elif event_type == "back":
                if stage != "final" or event.get("input_source") != "back_button":
                    raise ValueError(f"event {sequence} cannot return to preferences")
                stage = "preferences"
            else:
                raise ValueError(f"event {sequence} has an unknown type")
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"consent replay rejected: {exc}")

    expected_final = {"stage": stage, "current_drawer": current_drawer, "purpose_states": states}
    if payload.get("final_state") != expected_final:
        return _fail("submitted consent state does not match transcript replay")
    try:
        elapsed_task_ms = _finite_number(payload.get("elapsed_task_ms"))
    except ValueError:
        return _fail("submitted consent result lacks finite elapsed task time")
    if not last_task_time <= elapsed_task_ms <= 180_000:
        return _fail("submitted elapsed task time is outside the replayed event interval")
    exact = sum(states[item_id] == target for item_id, target in targets.items())
    all_links = {str(link["id"]) for link in links}
    passed = terminal == "committed" and payload.get("completed") is True and exact == len(targets) and activated_links == all_links
    return {
        "graded": True,
        "passed": passed,
        "feedback": f"optional purposes blocked {exact}/{len(targets)}; linked controls exercised {len(activated_links)}/{len(all_links)}; terminal decision {terminal or 'none'}; {len(events)} replayed actions; {elapsed_task_ms / 1000:.2f}s task time",
    }
