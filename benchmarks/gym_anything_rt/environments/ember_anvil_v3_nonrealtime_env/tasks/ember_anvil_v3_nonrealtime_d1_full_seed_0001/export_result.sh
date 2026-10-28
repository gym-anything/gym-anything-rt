#!/usr/bin/env bash
set -euo pipefail

/workspace/shared_scripts/export_result.sh

# Keep the common export fields and append this task's server-verified history.
python3 - <<'PY'
import importlib.util
import json
import os
from pathlib import Path

path = Path('/workspace/shared_runtime/server/incubator_graders/ember_anvil_v3_nonrealtime.py')
spec = importlib.util.spec_from_file_location('ember_anvil_export_policy', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
target = Path('/tmp/task_result.json')
exported = json.loads(target.read_text(encoding='utf-8'))
module.attach_episode_history(exported, os.environ.get('GYM_ANYTHING_RT_STATE_DIR', '/tmp/gym_anything_rt'))
temporary = target.with_suffix('.ember-anvil.tmp')
temporary.write_text(json.dumps(exported, indent=2, sort_keys=True), encoding='utf-8')
os.replace(temporary, target)
target.chmod(0o666)
PY
