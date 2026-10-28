from __future__ import annotations

import importlib.util
import importlib
from pathlib import Path


MECHANIC_ID = "lampwrights_program_v2"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dependencies():
    # Source checkout, materialized task, and the declared sandbox mount.
    # A copied verifier need not retain the original directory depth.
    for root in (*Path(__file__).resolve().parents, Path("/workspace")):
        runtime = root / "shared_runtime"
        helper = runtime / "verifier_helpers.py"
        grader = runtime / "server" / "incubator_graders" / f"{MECHANIC_ID}.py"
        if helper.is_file() and grader.is_file():
            return (_load("gym_anything_rt_verifier_helpers", helper),
                    _load(f"{MECHANIC_ID}_independent_grader", grader))
    return (importlib.import_module("benchmarks.gym_anything_rt.shared_runtime.verifier_helpers"),
            importlib.import_module(f"benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.{MECHANIC_ID}"))


def verify_task(traj=None, env_info=None, task_info=None):
    del traj, task_info
    try:
        helpers, grader = _dependencies()
        exported, error = helpers.load_exported_result(env_info or {})
    except Exception as exc:
        return {"passed": False, "score": 0, "feedback": f"cannot load verifier dependency: {exc}"}
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    exported = exported or {}
    if exported.get("graded_failures", 0):
        return {"passed": False, "score": 0, "feedback": "A failed submission already ended this episode."}
    decision = grader.grade(exported.get("result") or {}, exported.get("ground_truth") or {}, exported.get("public_state") or {})
    passed = decision.get("passed") is True
    return {"passed": passed, "score": 100 if passed else 0, "feedback": f"independent Lampwrights Program V2 replay: {decision.get('feedback') or 'no feedback'}"}
