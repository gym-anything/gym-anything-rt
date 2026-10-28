"""Every configuration generates a deterministic world for its own mechanic.

By default this checks the main configuration and the easiest simplified
configuration of every environment. Set GYM_ANYTHING_RT_ALL_CONFIGURATIONS=1
to check all 2,000 configurations.
"""

import importlib.util
import json
import os

import pytest

from benchmarks.gym_anything_rt import DEFAULT_ENVIRONMENTS_ROOT, load_pairs
from benchmarks.gym_anything_rt.registry.splits import BENCHMARK_ROOT

spec = importlib.util.spec_from_file_location("gym_anything_rt_setup_task", BENCHMARK_ROOT / "shared_scripts/setup_task.py")
setup_task = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_task)

ALL = os.environ.get("GYM_ANYTHING_RT_ALL_CONFIGURATIONS") == "1"
CASES = []
for pair in load_pairs():
    for env in (pair["real_time_environment"], pair["non_real_time_environment"]):
        for task_dir in sorted((DEFAULT_ENVIRONMENTS_ROOT / env / "tasks").iterdir()):
            if ALL or task_dir.name.endswith(("_d5_full_seed_0001", "_d1_simplified_seed_0001")):
                CASES.append(task_dir)


@pytest.mark.parametrize("task_dir", CASES, ids=[p.name for p in CASES])
def test_generation_is_deterministic(task_dir):
    task = json.loads((task_dir / "task.json").read_text())
    mechanic = task["metadata"]["mechanic_id"]
    public, truth = setup_task.generate_task_state(task, "42")
    again = setup_task.generate_task_state(task, "42")
    assert json.dumps([public, truth], sort_keys=True, default=str) == json.dumps(list(again), sort_keys=True, default=str)
    assert public["mechanic_id"] == mechanic
