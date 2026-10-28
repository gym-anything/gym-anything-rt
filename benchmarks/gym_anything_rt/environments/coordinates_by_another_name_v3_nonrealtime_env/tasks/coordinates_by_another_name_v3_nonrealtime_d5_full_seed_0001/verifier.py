from __future__ import annotations

import importlib.util
from pathlib import Path


MECHANIC_ID = "coordinates_by_another_name_v3_nonrealtime"


def _benchmark_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "shared_runtime" / "verifier_helpers.py").is_file():
            return parent
    spec = importlib.util.find_spec("benchmarks.gym_anything_rt")
    for location in (spec.submodule_search_locations if spec else ()) or ():
        root = Path(location)
        if (root / "shared_runtime" / "verifier_helpers.py").is_file():
            return root
    raise ImportError("installed Gym-Anything-RT benchmark runtime is unavailable")


BENCHMARK_ROOT = _benchmark_root()
HELPER_PATH = BENCHMARK_ROOT / "shared_runtime" / "verifier_helpers.py"
GRADER_PATH = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / f"{MECHANIC_ID}.py"


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
        helpers = _load("gym_anything_rt_verifier_helpers", HELPER_PATH)
        grader = _load(f"{MECHANIC_ID}_independent_grader", GRADER_PATH)
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
    return {"passed": passed, "score": 100 if passed else 0, "feedback": f"independent symbolic sonar replay: {decision.get('feedback') or 'no feedback'}"}
