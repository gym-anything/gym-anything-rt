from __future__ import annotations

import importlib.util
from pathlib import Path


BENCHMARK_ROOT = Path(__file__).resolve().parents[4]
HELPER_PATH = BENCHMARK_ROOT / "shared_runtime" / "verifier_helpers.py"


def _load_helpers():
    spec = importlib.util.spec_from_file_location("gym_anything_rt_verifier_helpers", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load verifier helper from {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_grader():
    grader_path = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / "cursor_lens_reveal_nonrealtime.py"
    spec = importlib.util.spec_from_file_location("cursor_lens_reveal_nonrealtime_grader", grader_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load counterpart grader from {grader_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_task(traj=None, env_info=None, task_info=None):
    del traj, task_info
    helpers = _load_helpers()
    exported, error = helpers.load_exported_result(env_info or {})
    if error:
        return {
            "passed": False,
            "score": 0,
            "feedback": error,
        }
    if not isinstance(exported, dict):
        return {"passed": False, "score": 0, "feedback": "exported result is not an object"}
    grader = _load_grader()
    return grader.grade(exported.get("result") or {}, exported.get("ground_truth") or {}, exported.get("public_state") or {})
