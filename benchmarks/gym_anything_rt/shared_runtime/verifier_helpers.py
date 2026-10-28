from __future__ import annotations

import json
import importlib.util
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


GRADER_ROOT = Path(__file__).resolve().parent / "server" / "incubator_graders"


def verify_external_mechanic(exported: dict[str, Any], mechanic_id: str) -> dict[str, Any]:
    result = exported.get("result") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    path = GRADER_ROOT / f"{mechanic_id}.py"
    spec = importlib.util.spec_from_file_location(f"gym_anything_rt_export_grader_{mechanic_id}", path)
    if spec is None or spec.loader is None:
        return {"passed": False, "score": 0, "feedback": f"cannot load grader for {mechanic_id}"}
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        grade = module.grade(result, exported.get("ground_truth") or {}, exported.get("public_state") or {})
    except Exception as exc:
        return {"passed": False, "score": 0, "feedback": f"grader error: {exc}"}
    passed = grade.get("passed") is True
    return {"passed": passed, "score": 100 if passed else 0, "feedback": str(grade.get("feedback") or "grade unavailable")}


def load_exported_result(env_info: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    copy_from_env: Callable[[str, str], None] | None = env_info.get("copy_from_env")
    if copy_from_env is None:
        return None, "copy_from_env unavailable"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    handle.close()
    try:
        copy_from_env("/tmp/task_result.json", handle.name)
        with open(handle.name, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return None, f"error reading /tmp/task_result.json: {exc}"
    finally:
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass
    if not isinstance(data, dict):
        return None, "exported result is not a JSON object"
    return data, None


def verify_reverse_identity_gate(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {
            "passed": False,
            "score": 0,
            "feedback": "No submitted UI result found.",
        }

    score = 0
    feedback: list[str] = []

    expected_identity = ground_truth.get("expected_identity")
    if result.get("identity") == expected_identity:
        score += 35
        feedback.append("identity declaration correct")
    else:
        feedback.append(f"identity declaration was {result.get('identity')!r}")

    switches = result.get("switches") or {}
    required = list(ground_truth.get("required_switches") or [])
    switched = [name for name in required if switches.get(name) is True]
    if required:
        switch_score = int(35 * len(switched) / len(required))
        score += switch_score
        feedback.append(f"robot ports set {len(switched)}/{len(required)}")

    expected_checksum = str(ground_truth.get("expected_checksum") or "").strip().upper()
    actual_checksum = str(result.get("checksum") or "").strip().upper()
    if actual_checksum == expected_checksum:
        score += 30
        feedback.append("checksum correct")
    else:
        feedback.append("checksum incorrect")

    return {
        "passed": score >= 100,
        "score": score,
        "feedback": " | ".join(feedback),
    }


def verify_moving_checkbox_evasive_button(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {
            "passed": False,
            "score": 0,
            "feedback": "No submitted UI result found.",
        }

    expected_target_id = str(ground_truth.get("expected_target_id") or "")
    actual_target_id = str(result.get("target_id") or "")
    checked = result.get("checked") is True
    decoy_hits = int(result.get("decoy_hits") or 0)

    score = 0
    feedback: list[str] = []
    if checked:
        score += 45
        feedback.append("a checkbox was checked")
    else:
        feedback.append("no checkbox was checked")

    if actual_target_id == expected_target_id:
        score += 45
        feedback.append("the moving checkbox was selected")
    else:
        feedback.append("selected target was not the moving checkbox")

    if decoy_hits == 0:
        score += 10
        feedback.append("no decoys clicked")
    else:
        feedback.append(f"decoys clicked: {decoy_hits}")

    return {
        "passed": checked and actual_target_id == expected_target_id,
        "score": min(score, 100),
        "feedback": " | ".join(feedback),
    }


def verify_surreal_apple_on_tree_grid(exported: dict[str, Any]) -> dict[str, Any]:
    if (exported.get("public_state") or {}).get("generator", {}).get("name") == "analytic_parallax_orchard_v2":
        return verify_external_mechanic(exported, "surreal_apple_on_tree_grid")
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {
            "passed": False,
            "score": 0,
            "feedback": "No submitted UI result found.",
        }

    expected = set(str(item) for item in ground_truth.get("expected_tile_ids") or [])
    selected = set(str(item) for item in result.get("selected_tile_ids") or [])
    true_positive = expected & selected
    false_positive = selected - expected
    missed = expected - selected

    precision = len(true_positive) / len(selected) if selected else 0.0
    recall = len(true_positive) / len(expected) if expected else 0.0
    score = int(round(100 * precision * recall)) if expected else 0
    passed = selected == expected
    feedback = (
        f"selected {len(selected)}; correct {len(true_positive)}/{len(expected)}; "
        f"false positives {len(false_positive)}; missed {len(missed)}"
    )
    return {
        "passed": passed,
        "score": 100 if passed else score,
        "feedback": feedback,
    }


def verify_modifier_stack_image_grid(exported: dict[str, Any]) -> dict[str, Any]:
    if (exported.get("public_state") or {}).get("generator", {}).get("name") == "kinetic_modifier_restoration_press_v2":
        return verify_external_mechanic(exported, "modifier_stack_image_grid")
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {
            "passed": False,
            "score": 0,
            "feedback": "No submitted UI result found.",
        }

    expected = set(str(item) for item in ground_truth.get("expected_tile_ids") or [])
    selected = set(str(item) for item in result.get("selected_tile_ids") or [])
    true_positive = expected & selected
    false_positive = selected - expected
    missed = expected - selected
    precision = len(true_positive) / len(selected) if selected else 0.0
    recall = len(true_positive) / len(expected) if expected else 0.0
    score = int(round(100 * precision * recall)) if expected else 0
    passed = selected == expected
    return {
        "passed": passed,
        "score": 100 if passed else score,
        "feedback": (
            f"selected {len(selected)}; correct {len(true_positive)}/{len(expected)}; "
            f"false positives {len(false_positive)}; missed {len(missed)}"
        ),
    }


def verify_cursor_lens_reveal(exported: dict[str, Any]) -> dict[str, Any]:
    if (exported.get("public_state") or {}).get("generator", {}).get("name") in {"polarized_moving_palimpsest_v2", "polarized_moving_palimpsest_v3"}:
        return verify_external_mechanic(exported, "cursor_lens_reveal")
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {
            "passed": False,
            "score": 0,
            "feedback": "No submitted UI result found.",
        }

    expected = ground_truth.get("expected_click") or {}
    click = result.get("click") or {}
    try:
        expected_x = float(expected.get("x"))
        expected_y = float(expected.get("y"))
        radius = float(expected.get("radius"))
        actual_x = float(click.get("x"))
        actual_y = float(click.get("y"))
    except (TypeError, ValueError):
        return {
            "passed": False,
            "score": 0,
            "feedback": "Submitted click coordinate is missing or invalid.",
        }

    distance = math.hypot(actual_x - expected_x, actual_y - expected_y)
    passed = distance <= radius
    score = 100 if passed else max(0, int(round(100 * (1 - min(distance, radius * 4) / (radius * 4)))))
    return {
        "passed": passed,
        "score": score,
        "feedback": f"click distance {distance:.2f}; accepted radius {radius:.2f}",
    }


def verify_board_game_captcha(exported: dict[str, Any]) -> dict[str, Any]:
    if (exported.get("public_state") or {}).get("generator", {}).get("name") == "deterministic_gyroscopic_tilt_board_v2":
        return verify_external_mechanic(exported, "board_game_captcha")
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {
            "passed": False,
            "score": 0,
            "feedback": "No submitted UI result found.",
        }

    expected = str(ground_truth.get("solution_cell_id") or "")
    selected = str(result.get("selected_cell_id") or "")
    passed = bool(expected) and selected == expected
    return {
        "passed": passed,
        "score": 100 if passed else 0,
        "feedback": "selected accepted cell" if passed else "selected cell was not accepted",
    }


def verify_semantic_drag_drop_absurdity(exported: dict[str, Any]) -> dict[str, Any]:
    return verify_external_mechanic(exported, "semantic_drag_drop_absurdity")


def _verify_semantic_drag_drop_absurdity_v1(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    expected = {
        str(key): str(value)
        for key, value in (ground_truth.get("expected_assignments") or {}).items()
    }
    placements = {
        str(key): str(value)
        for key, value in (result.get("placements") or {}).items()
        if value is not None
    }
    correct = sum(1 for key, value in expected.items() if placements.get(key) == value)
    passed = placements == expected
    return {
        "passed": passed,
        "score": 100 if passed else int(round(100 * correct / max(1, len(expected)))),
        "feedback": f"assignments {correct}/{len(expected)}",
    }


def verify_reload_interruption(exported: dict[str, Any]) -> dict[str, Any]:
    return verify_external_mechanic(exported, "reload_interruption")


def _verify_reload_interruption_v1(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    expected = set(str(item) for item in ground_truth.get("expected_interruptions") or [])
    cleared = set(str(item) for item in result.get("cleared_interruptions") or [])
    completed = result.get("completed") is True
    failed = bool(result.get("failed_interruption_id"))
    passed = completed and not failed and cleared == expected
    score = 0
    if completed:
        score += 40
    if expected:
        score += int(round(60 * len(cleared & expected) / len(expected)))
    return {
        "passed": passed,
        "score": 100 if passed else score,
        "feedback": f"completed={completed}; cleared {len(cleared & expected)}/{len(expected)}",
    }


def _angle_delta(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def verify_rotate_wrong_thing_upright(exported: dict[str, Any]) -> dict[str, Any]:
    return verify_external_mechanic(exported, "rotate_wrong_thing_upright")


def _verify_rotate_wrong_thing_upright_v1(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    try:
        target = float(ground_truth.get("target_angle"))
        tolerance = float(ground_truth.get("tolerance") or 10)
        submitted = float(result.get("angle"))
    except (TypeError, ValueError):
        return {"passed": False, "score": 0, "feedback": "Submitted angle is missing or invalid."}
    delta = _angle_delta(submitted, target)
    passed = delta <= tolerance
    score = 100 if passed else max(0, int(round(100 * (1 - min(delta, 90) / 90))))
    return {
        "passed": passed,
        "score": score,
        "feedback": f"angle delta {delta:.2f}; accepted tolerance {tolerance:.2f}",
    }


def verify_bureaucratic_signature_trap(exported: dict[str, Any]) -> dict[str, Any]:
    return verify_external_mechanic(exported, "bureaucratic_signature_trap")


def _verify_bureaucratic_signature_trap_v1(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    expected = [
        (str(mark.get("field_id")), str(mark.get("mark_type")))
        for mark in ground_truth.get("required_marks") or []
    ]
    marks = [
        (str(mark.get("field_id")), str(mark.get("mark_type")))
        for mark in result.get("marks") or []
        if isinstance(mark, dict)
    ]
    passed = sorted(marks) == sorted(expected)
    correct = len(set(marks) & set(expected))
    return {
        "passed": passed,
        "score": 100 if passed else int(round(100 * correct / max(1, len(expected)))),
        "feedback": f"marks {correct}/{len(expected)}",
    }


def _normalize_token(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def verify_wonky_text_hostile_rendering(exported: dict[str, Any]) -> dict[str, Any]:
    return verify_external_mechanic(exported, "wonky_text_hostile_rendering")


def _verify_wonky_text_hostile_rendering_v1(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    accepted = set(_normalize_token(item) for item in ground_truth.get("accepted") or [])
    submitted = _normalize_token(result.get("text"))
    passed = submitted in accepted
    return {
        "passed": passed,
        "score": 100 if passed else 0,
        "feedback": "token accepted" if passed else "token rejected",
    }


def verify_temporal_memory_first_change(exported: dict[str, Any]) -> dict[str, Any]:
    return verify_external_mechanic(exported, "temporal_memory_first_change")


def _verify_temporal_memory_first_change_v1(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    expected = str(ground_truth.get("target_object_id") or "")
    selected = str(result.get("selected_object_id") or "")
    passed = bool(expected) and selected == expected
    return {
        "passed": passed,
        "score": 100 if passed else 0,
        "feedback": "selected first-change object" if passed else "selected object was not accepted",
    }


def verify_motion_only_ghost_jigsaw(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    public_state = exported.get("public_state") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    expected = {str(key): int(value) for key, value in (ground_truth.get("expected_positions") or {}).items()}
    try:
        placements = {str(key): int(value) for key, value in (result.get("placements") or {}).items()}
    except (TypeError, ValueError):
        placements = {}
    condition = ground_truth.get("control_condition")
    if condition is not None:
        if public_state.get("control_condition") != condition:
            return {"passed": False, "score": 0, "feedback": "public interaction condition differs from ghost-jigsaw contract"}
        expected_source = {"simplified": "piece_slot_clicks", "full": "piece_drag"}.get(str(condition.get("interaction") or ""))
        sources = result.get("placement_sources") or {}
        if expected_source is None or not isinstance(sources, dict) or any(sources.get(piece_id) != expected_source for piece_id in expected):
            return {"passed": False, "score": 0, "feedback": "ghost-jigsaw placement uses the wrong interaction input"}
    correct = sum(1 for key, value in expected.items() if placements.get(key) == value)
    passed = bool(expected) and placements == expected
    return {"passed": passed, "score": 100 if passed else int(round(100 * correct / max(1, len(expected)))), "feedback": f"pieces {correct}/{len(expected)}"}


def verify_cursor_constellation_hunt(exported: dict[str, Any]) -> dict[str, Any]:
    if (exported.get("ground_truth") or {}).get("control_condition") is not None:
        return verify_external_mechanic(exported, "cursor_constellation_hunt")
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    expected = ground_truth.get("expected_click") or {}
    click = result.get("click") or {}
    try:
        distance = math.hypot(float(click.get("x")) - float(expected.get("x")), float(click.get("y")) - float(expected.get("y")))
        radius = float(expected.get("radius"))
    except (TypeError, ValueError):
        distance = math.inf
        radius = 0.0
    passed = distance <= radius
    score = 100 if passed else max(0, int(round(100 * (1 - distance / max(radius * 4, 1)))))
    return {"passed": passed, "score": score, "feedback": f"click distance {distance:.2f}px"}


def verify_parallel_grillmaster(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    if (
        (exported.get("ground_truth") or {}).get("control_condition")
        is not None
        or isinstance(result.get("trusted_witness"), dict)
    ):
        return verify_external_mechanic(exported, "parallel_grillmaster")
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    targets = ground_truth.get("targets") or {}
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
    return {"passed": passed, "score": 100 if passed else int(round(100 * correct / max(1, len(targets)))), "feedback": f"foods {correct}/{len(targets)}"}


def verify_rotating_keyboard(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    public_state = exported.get("public_state") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    expected = str(ground_truth.get("target") or "")
    submitted = str(result.get("text") or "").upper()
    condition = ground_truth.get("control_condition")
    if condition is not None:
        expected_source = {"simplified": "physical_keyboard", "full": "onscreen_keys"}.get(str(condition.get("interaction") or ""))
        if public_state.get("control_condition") != condition or expected_source is None or result.get("input_source") != expected_source:
            return {"passed": False, "score": 0, "feedback": "rotating-keyboard code uses the wrong interaction input"}
    correct = sum(1 for left, right in zip(expected, submitted) if left == right)
    passed = bool(expected) and submitted == expected
    return {"passed": passed, "score": 100 if passed else int(round(100 * correct / max(1, len(expected)))), "feedback": f"characters {correct}/{len(expected)}"}


def verify_slot_reel_capture(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    grader_path = Path(__file__).resolve().parent / "server" / "legacy_browser_grader.py"
    spec = importlib.util.spec_from_file_location(
        "gym_anything_rt_slot_reel_export_grader",
        grader_path,
    )
    if spec is None or spec.loader is None:
        return {
            "passed": False,
            "score": 0,
            "feedback": "cannot load Slot Reel task-time replay grader",
        }
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        grade = module.grade(
            result,
            exported.get("ground_truth") or {},
            exported.get("public_state") or {},
        )
    except Exception as exc:
        return {
            "passed": False,
            "score": 0,
            "feedback": f"slot-reel replay grader error: {exc}",
        }
    passed = grade.get("passed") is True
    return {
        "passed": passed,
        "score": 100 if passed else 0,
        "feedback": str(grade.get("feedback") or "slot-reel grade unavailable"),
    }


def verify_domino_autopsy(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    grader_path = Path(__file__).resolve().parent / "server" / "legacy_browser_grader.py"
    spec = importlib.util.spec_from_file_location(
        "gym_anything_rt_domino_export_grader",
        grader_path,
    )
    if spec is None or spec.loader is None:
        return {"passed": False, "score": 0, "feedback": "cannot load Domino Autopsy replay grader"}
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        grade = module.grade(
            result,
            exported.get("ground_truth") or {},
            exported.get("public_state") or {},
        )
    except Exception as exc:
        return {"passed": False, "score": 0, "feedback": f"domino replay grader error: {exc}"}
    passed = grade.get("passed") is True
    return {
        "passed": passed,
        "score": 100 if passed else 0,
        "feedback": str(grade.get("feedback") or "domino replay unavailable"),
    }


def verify_consequences_boss(exported: dict[str, Any]) -> dict[str, Any]:
    return verify_external_mechanic(exported, "consequences_boss")


def _verify_consequences_boss_v1(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    valid = {str(key): [str(item) for item in value] for key, value in (ground_truth.get("valid_choices") or {}).items()}
    kind = {str(key): str(value) for key, value in (ground_truth.get("kind_choices") or {}).items()}
    choices = {str(key): str(value) for key, value in (result.get("choices") or {}).items()}
    actions = {str(key): str(value) for key, value in (result.get("boss_actions") or {}).items()}
    legal = set(choices) == set(valid) and all(choices[key] in valid[key] for key in valid)
    correct = sum(1 for key in valid if actions.get(key) == ("protect" if choices.get(key) == kind.get(key) else "exploit"))
    passed = legal and set(actions) == set(valid) and correct == len(valid)
    return {"passed": passed, "score": 100 if passed else int(round(100 * correct / max(1, len(valid)))), "feedback": f"consequences answered {correct}/{len(valid)}"}


def verify_popup_exorcist(exported: dict[str, Any]) -> dict[str, Any]:
    return verify_external_mechanic(exported, "popup_exorcist")


def _verify_popup_exorcist_v1(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    expected = set(str(item) for item in ground_truth.get("popup_ids") or [])
    cleared = set(str(item) for item in result.get("cleared_popup_ids") or [])
    mode = str(result.get("mode") or "manual")
    trigger = str(result.get("trigger_popup_id") or "")
    valid_mode = mode == "manual" or (mode == "purge" and trigger == str(ground_truth.get("blocker_id") or ""))
    passed = bool(expected) and cleared == expected and valid_mode
    correct = len(cleared & expected)
    return {"passed": passed, "score": 100 if passed else int(round(100 * correct / max(1, len(expected)))), "feedback": f"windows cleared {correct}/{len(expected)}; mode={mode}"}


def verify_funeral_ritual(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    public_state = exported.get("public_state") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    condition = ground_truth.get("control_condition")
    if condition is not None and str(result.get("challenge_id") or "") != str(ground_truth.get("challenge_id") or ""):
        return {"passed": False, "score": 0, "feedback": "stale funeral challenge"}
    required_events = [str(item) for item in ground_truth.get("required_events") or []]
    events = [str(item) for item in result.get("events") or []]
    max_cells_value = ground_truth.get("moss_cells")
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
    expected_flowers = [str(item) for item in ground_truth.get("flower_ids") or []]
    expected_order = [str(item) for item in ground_truth.get("flower_order") or []]
    flowers_match = flowers == expected_order if expected_order else len(flowers) == len(expected_flowers) and set(flowers) == set(expected_flowers)
    threshold_value = ground_truth.get("brush_threshold")
    threshold = int(threshold_value) if threshold_value is not None else 17
    interaction_ok = True
    if condition is not None:
        expected_surface = str(condition.get("interaction") or "")
        surfaces = result.get("action_surfaces") or []
        expected_actions = [{"event": event, "surface": expected_surface} for event in required_events]
        flower_sources = result.get("flower_sources") or {}
        interaction_ok = (
            public_state.get("control_condition") == condition
            and expected_surface in {"simplified", "full"}
            and result.get("interaction_mode") == expected_surface
            and surfaces == expected_actions
            and isinstance(flower_sources, dict)
            and all(flower_sources.get(flower_id) == expected_surface for flower_id in expected_flowers)
        )
    checks = [events == required_events, len(cells) >= threshold, flowers_match, result.get("completed") is True, interaction_ok]
    passed = all(checks)
    return {"passed": passed, "score": 100 if passed else int(round(100 * sum(checks) / len(checks))), "feedback": f"ritual {len(events)}/{len(required_events)}; moss {len(cells)}/{threshold}; flowers {len(flowers)}/{len(expected_flowers)}"}


def verify_slime_commute(exported: dict[str, Any]) -> dict[str, Any]:
    return verify_external_mechanic(exported, "slime_commute")


def _verify_slime_commute_v1(exported: dict[str, Any]) -> dict[str, Any]:
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    if not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    visited = set()
    for item in result.get("visited_rows") or []:
        try:
            visited.add(int(item))
        except (TypeError, ValueError):
            continue
    required = set(int(item) for item in ground_truth.get("required_rows") or [])
    final = result.get("final") or {}
    goal = ground_truth.get("goal") or {}
    try:
        deaths = int(result.get("deaths") or 0)
        at_goal = (int(final.get("x")), int(final.get("y"))) == (int(goal.get("x")), int(goal.get("y")))
    except (TypeError, ValueError):
        deaths, at_goal = 999, False
    max_deaths = int(ground_truth.get("max_deaths") or 4)
    rows = len(visited & required)
    passed = result.get("completed") is True and required <= visited and at_goal and deaths < max_deaths
    return {"passed": passed, "score": 100 if passed else int(round(80 * rows / max(1, len(required)))), "feedback": f"rows {rows}/{len(required)}; wipeouts {deaths}/{max_deaths}"}
