#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${GYM_ANYTHING_RT_STATE_DIR:-/tmp/gym_anything_rt}"

python3 - <<'PY'
from __future__ import annotations

import json
import os
import time
from pathlib import Path

state_dir = Path(os.environ.get("GYM_ANYTHING_RT_STATE_DIR", "/tmp/gym_anything_rt"))

def read_json(name: str) -> dict:
    path = state_dir / name
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_error": str(exc)}
    return data if isinstance(data, dict) else {"_value": data}

def graded_failures() -> int:
    # The server appends one line to attempts.jsonl per graded-and-failed
    # submission, then issues a fresh challenge. Count them so a run can tell
    # "never submitted" apart from "submitted and was rejected N times".
    path = state_dir / "attempts.jsonl"
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return 0
    return sum(1 for line in text.splitlines() if line.strip())

payload = {
    "exported_at": time.time(),
    "public_state": read_json("public_state.json"),
    "ground_truth": read_json("ground_truth.json"),
    "result": read_json("result.json"),
    "graded_failures": graded_failures(),
    "current_task": {
        key: read_json("current_task.json").get(key)
        for key in ("challenge_index", "last_reason")
    },
}
target = Path("/tmp/task_result.json")
tmp = target.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
os.replace(tmp, target)
target.chmod(0o666)
print(json.dumps({"ok": True, "target": str(target)}))
PY
