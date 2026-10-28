#!/usr/bin/env bash
set -euo pipefail
python3 /workspace/shared_scripts/setup_task.py --task-json /workspace/tasks/tiny_fps_customs_v2_d5_simplified_seed_0001/task.json
exec /workspace/shared_scripts/open_puzzle_browser.sh
