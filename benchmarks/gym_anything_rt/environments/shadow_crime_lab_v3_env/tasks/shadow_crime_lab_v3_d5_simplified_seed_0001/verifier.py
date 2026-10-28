from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parents[4]
GRADER_PATH = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / "shadow_crime_lab_v3.py"


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
    spec = importlib.util.spec_from_file_location("shadow_crime_lab_v3_independent_grader", GRADER_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_task(traj=None, env_info=None, task_info=None):
    del traj, task_info
    exported, error = _load_exported_result(env_info or {})
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    # The shared export supplies this episode-wide count from attempts.jsonl.
    # A browser policy flag or a clean final camera transcript cannot replace it.
    failures = exported.get("graded_failures")
    if type(failures) is not int or failures < 0:
        return {"passed": False, "score": 0, "feedback": "Missing or invalid episode failure count."}
    current = exported.get("current_task", {})
    if not isinstance(current, dict):
        return {"passed": False, "score": 0, "feedback": "Invalid episode history summary."}
    if failures or current.get("last_reason") == "fail":
        return {"passed": False, "score": 0, "feedback": "A failed submission already ended this episode."}
    # Every materialized task carries this verifier beside its own task.json.
    # Bind to that task before replaying the trusted exported ground truth.
    try:
        bound_task = json.loads(Path(__file__).with_name("task.json").read_text(encoding="utf-8"))
        condition = bound_task["metadata"]["control_condition"]
        public = exported["public_state"]
        truth = exported["ground_truth"]
        if not isinstance(public, dict) or not isinstance(truth, dict):
            raise ValueError("malformed exported contract")
        for state in (public, truth):
            if state.get("task_id") != bound_task["id"] or state.get("mechanic_id") != "shadow_crime_lab_v3":
                raise ValueError("export does not belong to the bound task")
            if state.get("control_condition") != condition or state.get("parameters") != condition["difficulty_parameters"]:
                raise ValueError("export does not match the bound control condition")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"passed": False, "score": 0, "feedback": f"Invalid bound task contract: {exc}"}
    result = exported.get("result")
    if not isinstance(result, dict) or not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    grader = _load_grader()
    if grader is None or not callable(getattr(grader, "grade", None)):
        return {"passed": False, "score": 0, "feedback": f"cannot load independent grader from {GRADER_PATH}"}
    decision = grader.grade(result, truth, public)
    passed = bool(decision.get("passed"))
    return {"passed": passed, "score": 100 if passed else 0, "feedback": str(decision.get("feedback") or "independent replay failed")}
