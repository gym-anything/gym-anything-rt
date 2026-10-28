from __future__ import annotations
import importlib.util
from pathlib import Path

BENCHMARK_ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_task(traj=None, env_info=None, task_info=None):
    del traj, task_info
    try:
        helpers = load('ud2_verifier_helpers', BENCHMARK_ROOT/'shared_runtime/verifier_helpers.py')
        exported, error = helpers.load_exported_result(env_info or {})
        if error: return dict(passed=False, score=0, feedback=error)
        if exported.get('graded_failures', 0):
            return dict(passed=False, score=0, feedback='A failed submission already ended this episode.')
        grader = load('ud2_independent_grader', BENCHMARK_ROOT/'shared_runtime/server/incubator_graders/unlabeled_drawer_nonrealtime.py')
        decision = grader.grade(exported.get('result') or {}, exported.get('ground_truth') or {}, exported.get('public_state') or {})
        return dict(passed=decision['passed'], score=decision['score'], feedback=decision['feedback'])
    except Exception as error:
        return dict(passed=False, score=0, feedback='Cannot verify cabinet export: '+str(error))
