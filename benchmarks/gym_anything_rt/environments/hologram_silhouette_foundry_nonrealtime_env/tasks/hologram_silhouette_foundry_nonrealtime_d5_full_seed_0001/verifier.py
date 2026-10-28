from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parents[4]
GRADER_PATH = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / "hologram_silhouette_foundry_nonrealtime.py"
GENERATOR_PATH = BENCHMARK_ROOT / "shared_scripts" / "incubator_generators" / "hologram_silhouette_foundry_nonrealtime.py"


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


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bound_states(exported, task_info):
    """Bind replay to the runner's task, or the packaged task for local checks."""
    try:
        task = json.loads(Path(__file__).with_name("task.json").read_text(encoding="utf-8"))
        if isinstance(task_info, dict):
            if isinstance(task_info.get("task_spec"), dict) and task_info["task_spec"].get("id"):
                task = dict(task_info["task_spec"])
            else:
                if task_info.get("task_id"):
                    task["id"] = task_info["task_id"]
                if isinstance(task_info.get("metadata"), dict):
                    task["metadata"] = task_info["metadata"]
        if (task.get("metadata") or {}).get("mechanic_id") != "hologram_silhouette_foundry_nonrealtime":
            raise ValueError("wrong bound mechanic")
        condition = (task.get("metadata") or {}).get("control_condition")
        if condition:
            task["_control_condition"] = condition
        truth = exported.get("ground_truth")
        public = exported.get("public_state")
        if not isinstance(truth, dict) or not isinstance(public, dict) or not isinstance(truth.get("seed"), str):
            raise ValueError("missing bound world or seed")
        generator = _load_module("hologram_silhouette_foundry_nonrealtime_bound_generator", GENERATOR_PATH)
        if generator is None or not callable(getattr(generator, "generate", None)):
            raise ValueError("cannot load packaged foundry generator")
        expected_public, expected_truth = generator.generate(task, truth["seed"])
        for name, actual, expected in (("ground truth", truth, expected_truth), ("public state", public, expected_public)):
            for key, value in expected.items():
                if actual.get(key) != value:
                    raise ValueError(f"{name} differs from bound task: {key}")
        return expected_truth, expected_public, None
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return None, None, f"Cannot verify bound task: {exc}"


def verify_task(traj=None, env_info=None, task_info=None):
    del traj
    exported, error = _load_exported_result(env_info or {})
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    failure_count = exported.get("graded_failures")
    if type(failure_count) is not int or failure_count < 0:
        return {"passed": False, "score": 0, "feedback": "Missing or invalid authoritative failure history."}
    current_task = exported.get("current_task") or {}
    if failure_count or (isinstance(current_task, dict) and current_task.get("last_reason") == "fail"):
        return {"passed": False, "score": 0, "feedback": "A failed submission already ended this episode."}
    result = (exported or {}).get("result")
    if not isinstance(result, dict) or not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    truth, public, error = _bound_states(exported, task_info)
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    grader = _load_module("hologram_silhouette_foundry_nonrealtime_independent_grader", GRADER_PATH)
    if grader is None or not callable(getattr(grader, "grade", None)):
        return {"passed": False, "score": 0, "feedback": f"cannot load independent grader from {GRADER_PATH}"}
    decision = grader.grade(result, truth, public)
    passed = bool(decision.get("passed"))
    return {"passed": passed, "score": 100 if passed else 0, "feedback": str(decision.get("feedback") or "independent replay failed")}
