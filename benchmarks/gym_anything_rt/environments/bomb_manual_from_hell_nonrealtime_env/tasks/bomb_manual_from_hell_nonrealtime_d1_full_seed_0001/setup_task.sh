#!/usr/bin/env bash
set -euo pipefail
python3 /workspace/shared_scripts/setup_task.py --task-json /workspace/tasks/bomb_manual_from_hell_nonrealtime_d1_full_seed_0001/task.json
exec /workspace/shared_scripts/open_puzzle_browser.sh
