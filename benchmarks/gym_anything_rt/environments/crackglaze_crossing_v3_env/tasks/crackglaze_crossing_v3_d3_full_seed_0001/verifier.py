from __future__ import annotations

import importlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any


GRADER_MODULE = "benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.crackglaze_crossing_v3"
GRADER_RELATIVE_PATH = Path("shared_runtime/server/incubator_graders/crackglaze_crossing_v3.py")


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
    # Controlled tasks are copied outside the checkout. Their depth cannot
    # identify the benchmark root; use the installed benchmark in that case.
    try:
        return importlib.import_module(GRADER_MODULE)
    except ModuleNotFoundError:
        pass
    # The standalone container mounts shared_runtime beside its task tree.
    for root in Path(__file__).resolve().parents:
        path = root / GRADER_RELATIVE_PATH
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("crackglaze_crossing_v3_independent_grader", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return None


def _bound_task_error(exported: dict[str, Any], task_info: Any) -> str | None:
    # Gym-Anything supplies task_id, metadata and task_spec. Direct replay
    # callers may supply the raw specification or omit task_info entirely.
    if task_info is None:
        return None
    if not isinstance(task_info, dict):
        return "Invalid bound task information."
    sources = [task_info]
    if "task_spec" in task_info:
        if not isinstance(task_info["task_spec"], dict):
            return "Invalid bound task specification."
        sources.append(task_info["task_spec"])
    truth = exported.get("ground_truth")
    if not isinstance(truth, dict):
        return "No exported ground truth found."
    for source in sources:
        for key in ("task_id", "id"):
            if key in source and source[key] != truth.get("task_id"):
                return "Exported result belongs to a different bound task."
        metadata = source.get("metadata", {})
        if not isinstance(metadata, dict):
            return "Invalid bound task metadata."
        mechanic = metadata.get("mechanic_id")
        if mechanic is not None and mechanic != truth.get("mechanic_id"):
            return "Exported mechanic differs from the bound task."
        condition = metadata.get("control_condition")
        if condition is not None and condition != truth.get("control_condition"):
            return "Exported control condition differs from the bound task."
    return None


def verify_task(traj=None, env_info=None, task_info=None):
    del traj
    exported, error = _load_exported_result(env_info or {})
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    if (exported or {}).get("graded_failures", 0):
        return {"passed": False, "score": 0, "feedback": "A failed submission already ended this episode."}
    error = _bound_task_error(exported, task_info)
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    result = (exported or {}).get("result")
    if not isinstance(result, dict) or not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    try:
        grader = _load_grader()
    except (ImportError, OSError) as exc:
        return {"passed": False, "score": 0, "feedback": f"cannot load independent grader: {exc}"}
    if grader is None or not callable(getattr(grader, "grade", None)):
        return {"passed": False, "score": 0, "feedback": f"cannot load independent grader {GRADER_MODULE}"}
    decision = grader.grade(result, (exported or {}).get("ground_truth") or {}, (exported or {}).get("public_state") or {})
    passed = bool(decision.get("passed"))
    return {"passed": passed, "score": 100 if passed else 0, "feedback": str(decision.get("feedback") or "independent replay failed")}
