from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parents[4]
GRADER_PATH = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / "rorschach_fixed_rubric_v3.py"
GENERATOR_PATH = BENCHMARK_ROOT / "shared_scripts" / "incubator_generators" / "rorschach_fixed_rubric_v3.py"


def _load_exported_result(env_info: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    copy_from_env = env_info.get("copy_from_env")
    if not callable(copy_from_env):
        return None, "copy_from_env unavailable"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    handle.close()
    try:
        copy_from_env("/tmp/task_result.json", handle.name)
        with open(handle.name, "r", encoding="utf-8") as stream:
            exported = json.load(stream)
    except Exception as exc:
        return None, f"error reading /tmp/task_result.json: {exc}"
    finally:
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass
    return (exported, None) if isinstance(exported, dict) else (None, "exported result is not a JSON object")


def _load_grader():
    spec = importlib.util.spec_from_file_location("rorschach_fixed_rubric_v3_independent_grader", GRADER_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bound_task_error(exported, task_info):
    """Bind replay to the packaged task and its unchanged seeded world."""
    try:
        task = json.loads(Path(__file__).with_name("task.json").read_text(encoding="utf-8"))
        assigned_id = (task_info.get("id", task_info.get("task_id"))
                       if isinstance(task_info, dict) else getattr(task_info, "id", None))
        if assigned_id is not None and assigned_id != task["id"]:
            return "Verifier does not match the assigned task."
        truth = exported.get("ground_truth")
        if not isinstance(truth, dict) or not isinstance(truth.get("seed"), str):
            return "Missing authoritative seeded ink world."
        spec = importlib.util.spec_from_file_location("rorschach_fixed_rubric_v3_bound_generator", GENERATOR_PATH)
        if spec is None or spec.loader is None:
            return "Cannot load the bound ink generator."
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        condition = (task.get("metadata") or {}).get("control_condition")
        if condition is not None:
            task["_control_condition"] = condition
        public, expected_truth = generator.generate(task, truth["seed"])
        if truth != expected_truth or exported.get("public_state") != public:
            return "Exported ink world does not match the bound task and seed."
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return f"Cannot establish the bound ink task: {exc}"
    return None


def verify_task(traj=None, env_info=None, task_info=None):
    del traj
    exported, error = _load_exported_result(env_info or {})
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    # The frozen exporter supplies this integer from the failure ledger.
    # Missing evidence, or a browser's inner counter, cannot prove a clean run.
    failures = exported.get("graded_failures")
    if type(failures) is not int or failures < 0:
        return {"passed": False, "score": 0, "feedback": "Missing or invalid episode failure history."}
    if failures:
        return {"passed": False, "score": 0, "feedback": "A failed submission already ended this episode."}
    error = _bound_task_error(exported, task_info)
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    result = (exported or {}).get("result")
    if not isinstance(result, dict) or not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    grader = _load_grader()
    if grader is None or not callable(getattr(grader, "grade", None)):
        return {"passed": False, "score": 0, "feedback": f"cannot load independent grader from {GRADER_PATH}"}
    decision = grader.grade(result, (exported or {}).get("ground_truth") or {}, (exported or {}).get("public_state") or {})
    passed = bool(decision.get("passed"))
    return {"passed": passed, "score": 100 if passed else 0, "feedback": str(decision.get("feedback") or "independent replay failed")}
