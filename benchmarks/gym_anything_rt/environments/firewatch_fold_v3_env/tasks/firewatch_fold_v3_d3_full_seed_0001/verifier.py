from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _benchmark_root():
    explicit = os.environ.get("GYM_ANYTHING_RT_ROOT")
    if explicit:
        return Path(explicit)
    # Controlled tasks may be materialized outside the checkout. An installed
    # benchmark locates its grader through the package, while sandbox mounts
    # expose shared_runtime next to /workspace/tasks.
    package = importlib.util.find_spec("benchmarks.gym_anything_rt")
    candidates = ([Path(package.origin).resolve().parent] if package and package.origin else [])
    candidates.extend(Path(__file__).resolve().parents)
    return next((root for root in candidates if (root / "shared_runtime/server/incubator_graders/firewatch_fold_v3.py").is_file()), Path(__file__).resolve().parent)


BENCHMARK_ROOT = _benchmark_root()
GRADER_PATH = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / "firewatch_fold_v3.py"


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
        return None
    spec = importlib.util.spec_from_file_location("firewatch_fold_v3_independent_grader", GRADER_PATH)
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
    if (exported or {}).get("graded_failures", 0):
        return {"passed": False, "score": 0, "feedback": "A failed submission already ended this episode."}
    result = (exported or {}).get("result")
    if not isinstance(result, dict) or not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    grader = _load_grader()
    if grader is None or not callable(getattr(grader, "grade", None)):
        return {"passed": False, "score": 0, "feedback": f"cannot load independent grader from {GRADER_PATH}"}
    decision = grader.grade(result, (exported or {}).get("ground_truth") or {}, (exported or {}).get("public_state") or {})
    passed = bool(decision.get("passed"))
    return {"passed": passed, "score": 100 if passed else 0, "feedback": str(decision.get("feedback") or "independent replay failed")}
