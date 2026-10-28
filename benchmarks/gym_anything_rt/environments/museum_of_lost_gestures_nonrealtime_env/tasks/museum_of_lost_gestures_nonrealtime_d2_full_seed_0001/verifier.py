from __future__ import annotations

import importlib.util
import json
from pathlib import Path


BENCHMARK_ROOT = Path(__file__).resolve().parents[4]
HELPER_PATH = BENCHMARK_ROOT / "shared_runtime" / "verifier_helpers.py"
GRADER_PATH = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / "museum_of_lost_gestures_nonrealtime.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_task(traj=None, env_info=None, task_info=None):
    try:
        helpers = _load_module("gym_anything_rt_verifier_helpers", HELPER_PATH)
        grader = _load_module("museum_of_lost_gestures_nonrealtime_independent_grader", GRADER_PATH)
    except Exception as exc:
        return {"passed": False, "score": 0, "feedback": f"cannot load verifier dependency: {exc}"}
    exported, error = helpers.load_exported_result(env_info or {})
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    exported = exported or {}
    if exported.get("graded_failures", 0):
        return {"passed": False, "score": 0, "feedback": "A failed submission ended this episode."}
    result = exported.get("result") or {}
    ground_truth = exported.get("ground_truth") or {}
    public_state = exported.get("public_state") or {}
    try:
        # Materialization packages this file with the actual task definition.
        # Neither an exported policy nor supplied task_info can rebind it.
        bound_task = json.loads(Path(__file__).with_name("task.json").read_text())
        metadata = bound_task["metadata"]
        for envelope in (result, ground_truth, public_state):
            if (envelope.get("task_id") != bound_task["id"]
                    or envelope.get("mechanic_id") != metadata["mechanic_id"]
                    or envelope.get("control_condition") != metadata["control_condition"]):
                return {"passed": False, "score": 0, "feedback": "Export does not match the bound task."}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"passed": False, "score": 0, "feedback": f"cannot verify bound task: {exc}"}
    replay = grader.grade(result, ground_truth, public_state)
    passed = replay.get("passed") is True
    return {
        "passed": passed,
        "score": replay.get("score", 0),
        "feedback": f"independent browser-gesture replay: {replay.get('feedback') or 'no feedback'}",
    }
