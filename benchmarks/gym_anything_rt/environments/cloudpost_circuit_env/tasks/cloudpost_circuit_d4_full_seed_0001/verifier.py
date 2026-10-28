from __future__ import annotations

import importlib.util
from pathlib import Path

MECHANIC_ID = "cloudpost_circuit"
ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "shared_runtime" / "verifier_helpers.py"
GRADER = ROOT / "shared_runtime" / "server" / "incubator_graders" / f"{MECHANIC_ID}.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_task(traj=None, env_info=None, task_info=None):
    del traj, task_info
    try:
        helpers = _load("cloudpost_verifier_helpers", HELPER)
        grader = _load("cloudpost_circuit_independent_grader", GRADER)
        exported, error = helpers.load_exported_result(env_info or {})
    except Exception as exc:
        return {"passed": False, "score": 0, "feedback": f"cannot load verifier dependency: {exc}"}
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    exported = exported or {}
    decision = grader.grade(exported.get("result") or {}, exported.get("ground_truth") or {}, exported.get("public_state") or {})
    passed = decision.get("passed") is True
    return {"passed": passed, "score": 100 if passed else 0, "feedback": f"independent Cloudpost Circuit replay: {decision.get('feedback') or 'no feedback'}"}
