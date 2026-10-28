#!/usr/bin/env bash
set -euo pipefail

# Make the existing state-directory setting available to this task's grader and
# generator as well as the unchanged shared server.
export GYM_ANYTHING_RT_STATE_DIR="${GYM_ANYTHING_RT_STATE_DIR:-/tmp/gym_anything_rt}"
exec /workspace/shared_scripts/setup_puzzle_runtime.sh
