#!/usr/bin/env bash
set -euo pipefail
if [[ -x /workspace/shared_scripts/export_result.sh ]]; then
  exec /workspace/shared_scripts/export_result.sh
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec bash "${script_dir}/../../../../../benchmarks/gym_anything_rt/shared_scripts/export_result.sh"
