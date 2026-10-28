"""Export this task's verified-attempt journal without changing shared export."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

MECHANIC_ID = "code_to_diagram_captcha_v3_nonrealtime"
HISTORY_PATH = "/tmp/code_to_diagram_captcha_v3_nonrealtime_episode.json"


def export_episode_history(state_dir: Path, exported_path: Path, target: Path) -> dict:
    history = dict(schema_version=1, mechanic_id=MECHANIC_ID, attempts=[], history_error="")
    try:
        raw = exported_path.read_bytes()
        exported = json.loads(raw)
        if not isinstance(exported, dict):
            raise ValueError("shared export is not an object")
        history["result_export_sha256"] = hashlib.sha256(raw).hexdigest()
        truth = exported.get("ground_truth") or {}
        history.update(task_id=truth.get("task_id"), challenge_id=truth.get("challenge_id"))
        if truth.get("mechanic_id") != MECHANIC_ID:
            raise ValueError("wrong task in shared export")
        # Bind the receipt to the actual current state and the exact shared
        # export bytes. A racing regeneration must not certify a clean history.
        for key in ("public_state", "ground_truth", "result"):
            path = state_dir / (key + ".json")
            value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if value != exported.get(key):
                raise ValueError("state changed during export: " + key)
        journal = state_dir / "attempts.jsonl"
        text = journal.read_text(encoding="utf-8") if journal.exists() else ""
        history["attempts"] = [json.loads(line) for line in text.splitlines() if line.strip()]
        history["journal_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if (type(exported.get("graded_failures")) is not int or
                len(history["attempts"]) != exported["graded_failures"]):
            raise ValueError("shared counter differs from archived attempts")
    except (OSError, UnicodeError, ValueError, AttributeError, TypeError) as exc:
        history["history_error"] = "Episode failure history is unavailable: " + str(exc)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    target.chmod(0o666)
    return history


if __name__ == "__main__":
    receipt = export_episode_history(
        Path(os.environ.get("GYM_ANYTHING_RT_STATE_DIR", "/tmp/gym_anything_rt")),
        Path("/tmp/task_result.json"), Path(HISTORY_PATH))
    print(json.dumps(dict(ok=not bool(receipt["history_error"]), target=HISTORY_PATH)))
