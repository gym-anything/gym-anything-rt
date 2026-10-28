#!/usr/bin/env bash
set -euo pipefail

export GYM_ANYTHING_RT_STATE_DIR="${GYM_ANYTHING_RT_STATE_DIR:-/tmp/gym_anything_rt}"

python3 /workspace/shared_scripts/setup_task.py --task-json /workspace/tasks/coordinates_by_another_name_v3_d5_simplified_seed_0001/task.json
exec /workspace/shared_scripts/open_puzzle_browser.sh
