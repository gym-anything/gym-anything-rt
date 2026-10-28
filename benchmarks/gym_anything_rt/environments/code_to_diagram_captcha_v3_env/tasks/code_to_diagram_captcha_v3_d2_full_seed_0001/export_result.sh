#!/usr/bin/env bash
set -euo pipefail

bash /workspace/shared_scripts/export_result.sh
exec python3 "$(dirname "$0")/export_episode_history.py"
