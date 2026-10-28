from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any


GRADER_RELATIVE_PATH = Path("shared_runtime/server/incubator_graders/rising_causeway_v2.py")
BENCHMARK_ROOT = next(
    (parent for parent in Path(__file__).resolve().parents
     if (parent / GRADER_RELATIVE_PATH).is_file()),
    Path(__file__).resolve().parent,
)
GRADER_PATH = BENCHMARK_ROOT / GRADER_RELATIVE_PATH


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
    if not GRADER_PATH.is_file():
        # Controlled tasks may be materialized outside the source tree. Use
        # the same installed task grader rather than requiring an extra copy.
        try:
            from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders import rising_causeway_v2
        except ImportError:
            return None
        return rising_causeway_v2
    spec = importlib.util.spec_from_file_location("rising_causeway_v2_independent_grader", GRADER_PATH)
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
    failures = (exported or {}).get("graded_failures", 0)
    if type(failures) is not int or failures < 0:
        return {"passed": False, "score": 0, "feedback": "Invalid historical failure count."}
    result = (exported or {}).get("result")
    if not isinstance(result, dict) or not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    grader = _load_grader()
    if grader is None or not callable(getattr(grader, "grade", None)):
        return {"passed": False, "score": 0, "feedback": f"cannot load independent grader from {GRADER_PATH}"}
    truth = (exported or {}).get("ground_truth") or {}
    public = (exported or {}).get("public_state") or {}
    decision = grader.grade(result, truth, public)
    if failures and not grader.allows_episode_retries(truth, public):
        return {"passed": False, "score": 0, "feedback": "A failed submission already ended this episode."}
    passed = bool(decision.get("passed"))
    feedback = str(decision.get("feedback") or "independent replay failed")
    if passed and failures:
        feedback += f" {failures} earlier failed submission(s) remain recorded; retries are allowed for this configuration."
    return {"passed": passed, "score": 100 if passed else 0, "feedback": feedback}
