#!/usr/bin/env bash
set -euo pipefail

# Regeneration reads the episode ledger in the server process as well as setup.
export GYM_ANYTHING_RT_STATE_DIR="${GYM_ANYTHING_RT_STATE_DIR:-/tmp/gym_anything_rt}"

exec /workspace/shared_scripts/setup_puzzle_runtime.sh
