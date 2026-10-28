from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parents[4]
GRADER_PATH = BENCHMARK_ROOT / "shared_runtime" / "server" / "incubator_graders" / "code_to_diagram_captcha_v3.py"
HISTORY_PATH = "/tmp/code_to_diagram_captcha_v3_episode.json"


def _copy_json(env_info: dict[str, Any], source: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    copy_from_env = env_info.get("copy_from_env")
    if not callable(copy_from_env):
        return None, None, "copy_from_env unavailable"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    handle.close()
    try:
        copy_from_env(source, handle.name)
        raw = Path(handle.name).read_bytes()
        exported = json.loads(raw)
    except Exception as exc:
        return None, None, f"error reading {source}: {exc}"
    finally:
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass
    if not isinstance(exported, dict):
        return None, None, f"{source} is not a JSON object"
    return exported, hashlib.sha256(raw).hexdigest(), None


def _load_grader():
    spec = importlib.util.spec_from_file_location("code_to_diagram_captcha_v3_independent_grader", GRADER_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_task(traj=None, env_info=None, task_info=None):
    del traj
    def fail(message):
        return {"passed": False, "score": 0, "feedback": message}
    exported, digest, error = _copy_json(env_info or {}, "/tmp/task_result.json")
    if error:
        return fail(error)
    truth, public = exported.get("ground_truth"), exported.get("public_state")
    if not isinstance(truth, dict) or not isinstance(public, dict):
        return fail("Missing bound task state.")
    if isinstance(task_info, dict) and task_info.get("id") and task_info["id"] != truth.get("task_id"):
        return fail("Export belongs to a different task.")
    if truth.get("episode_failed") or public.get("episode_failed"):
        return fail("A failed submission already ended this episode.")
    history, _, error = _copy_json(env_info or {}, HISTORY_PATH)
    if error:
        return fail("Episode failure history is unavailable: " + error)
    if (history.get("schema_version") != 1 or history.get("mechanic_id") != "code_to_diagram_captcha_v3" or
            history.get("result_export_sha256") != digest or
            any(history.get(key) != truth.get(key) for key in ("task_id", "challenge_id"))):
        return fail("Episode history does not match the bound task export.")
    if history.get("history_error") != "":
        return fail("Episode failure history is unavailable.")
    grader = _load_grader()
    if grader is None or not callable(getattr(grader, "grade_attempt", None)):
        return fail(f"cannot load independent grader from {GRADER_PATH}")
    failure, error = grader.episode_failure_from_attempts(history.get("attempts"), truth.get("task_id"))
    if failure or error:
        return fail(failure or error)
    counter = exported.get("graded_failures")
    if type(counter) is not int or counter < 0 or counter != len(history["attempts"]):
        return fail("Failure counter differs from archived attempts.")
    result = exported.get("result")
    if not isinstance(result, dict) or not result:
        return fail("No submitted UI result found.")
    decision = grader.grade_attempt(result, truth, public)
    passed = bool(decision.get("passed"))
    return {"passed": passed, "score": 100 if passed else 0, "feedback": str(decision.get("feedback") or "independent replay failed")}
