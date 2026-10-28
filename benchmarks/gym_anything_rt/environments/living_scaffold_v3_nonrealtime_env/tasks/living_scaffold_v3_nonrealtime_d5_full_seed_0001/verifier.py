from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _benchmark_root() -> Path:
    relative = Path("shared_runtime/server/incubator_graders/living_scaffold_v3_nonrealtime.py")
    for root in Path(__file__).resolve().parents:
        if (root / relative).is_file():
            return root
    package = importlib.util.find_spec("benchmarks.gym_anything_rt")
    if package and package.submodule_search_locations:
        for location in package.submodule_search_locations:
            root = Path(location)
            if (root / relative).is_file():
                return root
    return Path("/workspace")


BENCHMARK_ROOT = _benchmark_root()
GRADER_PATH = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / "living_scaffold_v3_nonrealtime.py"


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
    spec = importlib.util.spec_from_file_location("living_scaffold_v3_nonrealtime_independent_grader", GRADER_PATH)
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
    failures = (exported or {}).get("graded_failures")
    if type(failures) is not int or failures < 0:
        return {"passed": False, "score": 0, "feedback": "Missing or invalid exported failure ledger."}
    if failures:
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
