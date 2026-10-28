from __future__ import annotations

import importlib.util
import os
from pathlib import Path


MECHANIC_ID = "lanternwing_roundup"
ROOT = Path(os.environ.get("GYM_ANYTHING_RT_ROOT", Path(__file__).resolve().parents[4]))


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("lanternwing_roundup_verifier_grader", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_task(traj=None, env_info=None, task_info=None):
    del traj, task_info
    try:
        from benchmarks.gym_anything_rt.shared_runtime.verifier_helpers import load_exported_result
        exported, error = load_exported_result(env_info or {})
        if error:
            return {"passed": False, "score": 0, "feedback": error}
        grader = _load(ROOT / "shared_runtime/server/incubator_graders/lanternwing_roundup.py")
        decision = grader.grade(exported.get("result") or {}, exported.get("ground_truth") or {}, exported.get("public_state") or {})
        return {"passed": decision.get("passed") is True, "score": 100 if decision.get("passed") else 0, "feedback": f"independent Lanternwing Roundup replay: {decision.get('feedback', '')}"}
    except Exception as exc:
        return {"passed": False, "score": 0, "feedback": f"cannot load verifier dependency: {exc}"}
