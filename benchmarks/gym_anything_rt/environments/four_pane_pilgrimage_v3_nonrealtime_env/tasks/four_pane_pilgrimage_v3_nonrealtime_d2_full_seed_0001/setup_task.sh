#!/usr/bin/env bash
set -euo pipefail
python3 /workspace/shared_scripts/setup_task.py --task-json /workspace/tasks/four_pane_pilgrimage_v3_nonrealtime_d2_full_seed_0001/task.json
exec /workspace/shared_scripts/open_puzzle_browser.sh
