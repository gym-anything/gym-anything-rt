from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _benchmark_root() -> Path:
    # Materialized verifiers can live outside the source environment tree.
    # Mounted runtimes and installed benchmark packages still supply the
    # same task-owned generator and grader; never ship a second replay copy.
    for parent in Path(__file__).resolve().parents:
        if (parent / "shared_runtime" / "server" / "incubator_graders" / "recursive_dollhouse_smuggling_v2.py").is_file():
            return parent
    package = importlib.util.find_spec("benchmarks.gym_anything_rt")
    if package and package.submodule_search_locations:
        return Path(next(iter(package.submodule_search_locations)))
    return Path("/workspace")


BENCHMARK_ROOT = _benchmark_root()
GRADER_PATH = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / "recursive_dollhouse_smuggling_v2.py"
GENERATOR_PATH = BENCHMARK_ROOT / "shared_scripts" / "incubator_generators" / "recursive_dollhouse_smuggling_v2.py"


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
    spec = importlib.util.spec_from_file_location("recursive_dollhouse_smuggling_v2_independent_grader", GRADER_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bound_task(task_info: dict[str, Any] | None) -> dict[str, Any]:
    if task_info is None:
        task = json.loads(Path(__file__).with_name("task.json").read_text(encoding="utf-8"))
    else:
        if not isinstance(task_info, dict):
            raise ValueError("invalid bound task information")
        # Gym-Anything supplies task_spec plus task_id and metadata. Local
        # implementation checks may provide the actual task specification.
        task = task_info.get("task_spec", task_info)
        if not isinstance(task, dict):
            raise ValueError("invalid bound task specification")
        if "task_id" in task_info and task_info["task_id"] != task.get("id"):
            raise ValueError("bound task identity mismatch")
        if "task_spec" in task_info and task_info.get("metadata", task.get("metadata")) != task.get("metadata"):
            raise ValueError("bound task metadata mismatch")
    if not isinstance(task, dict) or not task.get("id") or (task.get("metadata") or {}).get("mechanic_id") != "recursive_dollhouse_smuggling_v2":
        raise ValueError("missing or wrong bound task")
    return task


def _check_bound_state(exported: dict[str, Any], task_info: dict[str, Any] | None) -> None:
    task = _bound_task(task_info)
    truth, public, result = (exported.get(key) for key in ("ground_truth", "public_state", "result"))
    if any(not isinstance(value, dict) or value.get("task_id") != task["id"] for value in (truth, public, result)):
        raise ValueError("export does not belong to the bound task")
    seed = truth.get("seed")
    if not isinstance(seed, str) or not seed:
        raise ValueError("missing generated-world seed")
    spec = importlib.util.spec_from_file_location("recursive_dollhouse_smuggling_v2_bound_generator", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load bound task generator")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    bound = dict(task)
    condition = (task.get("metadata") or {}).get("control_condition")
    if condition is not None:
        bound["_control_condition"] = condition
    expected, _ = generator.generate(bound, seed)
    for field in ("mechanic_id", "task_id", "challenge_id", "control_condition", "views", "room", "gates", "parcels", "physics", "single_attempt"):
        if any(value.get(field) != expected[field] for value in (truth, public)):
            raise ValueError("bound generated-world mismatch: " + field)


def verify_task(traj=None, env_info=None, task_info=None):
    del traj
    exported, error = _load_exported_result(env_info or {})
    if error:
        return {"passed": False, "score": 0, "feedback": error}
    failures = (exported or {}).get("graded_failures")
    if type(failures) is not int or failures < 0:
        return {"passed": False, "score": 0, "feedback": "Missing or malformed episode failure ledger."}
    if failures:
        return {"passed": False, "score": 0, "feedback": "A failed submission already ended this episode."}
    result = (exported or {}).get("result")
    if not isinstance(result, dict) or not result:
        return {"passed": False, "score": 0, "feedback": "No submitted UI result found."}
    try:
        _check_bound_state(exported, task_info)
    except (OSError, KeyError, TypeError, ValueError, ImportError, AttributeError) as exc:
        return {"passed": False, "score": 0, "feedback": "Invalid bound task export: " + str(exc)}
    grader = _load_grader()
    if grader is None or not callable(getattr(grader, "grade", None)):
        return {"passed": False, "score": 0, "feedback": f"cannot load independent grader from {GRADER_PATH}"}
    decision = grader.grade(result, (exported or {}).get("ground_truth") or {}, (exported or {}).get("public_state") or {})
    passed = bool(decision.get("passed"))
    return {"passed": passed, "score": 100 if passed else 0, "feedback": str(decision.get("feedback") or "independent replay failed")}
