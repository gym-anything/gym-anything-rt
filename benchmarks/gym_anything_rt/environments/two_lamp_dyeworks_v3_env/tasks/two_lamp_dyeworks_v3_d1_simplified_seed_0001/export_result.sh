#!/usr/bin/env bash
set -euo pipefail
/workspace/shared_scripts/export_result.sh
python3 - <<'PY'
import importlib.util
from pathlib import Path

path = Path('/workspace/shared_runtime/server/incubator_graders/two_lamp_dyeworks_v3.py')
spec = importlib.util.spec_from_file_location('dyeworks_export_history', path)
grader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grader)
grader.export_episode_history(Path('/tmp/task_result.json'))
PY
