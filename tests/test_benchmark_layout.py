"""The released benchmark has the expected environments, configurations and metadata."""

import json
import re

import pytest

from benchmarks.gym_anything_rt import (
    DEFAULT_ENVIRONMENTS_ROOT,
    get_tasks_for_environment,
    load_environment_task_splits,
    load_pairs,
)
from benchmarks.gym_anything_rt.registry.splits import BENCHMARK_ROOT

PAIRS = load_pairs()
ENVIRONMENTS = [env for pair in PAIRS for env in (pair["real_time_environment"], pair["non_real_time_environment"])]
CONFIGURATIONS = [f"d{d}_{mode}" for d in range(1, 6) for mode in ("full", "simplified")]


def test_one_hundred_pairs_and_two_hundred_environments():
    assert len(PAIRS) == 100
    assert len(set(ENVIRONMENTS)) == 200
    on_disk = sorted(p.name for p in DEFAULT_ENVIRONMENTS_ROOT.iterdir() if p.is_dir())
    assert on_disk == sorted(ENVIRONMENTS)
    assert all(pair["non_real_time_environment"].endswith("_nonrealtime_env") for pair in PAIRS)


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_environment_has_ten_configurations(env):
    directory = DEFAULT_ENVIRONMENTS_ROOT / env
    spec = json.loads((directory / "env.json").read_text())
    assert spec["runner"] == "gym_anything_rt"
    assert spec["id"] == f"gym_anything_rt.{env}@{spec['version']}"
    assert (directory / "controls.json").is_file()
    tasks = sorted(p.name for p in (directory / "tasks").iterdir())
    assert len(tasks) == 10
    assert sorted(re.sub(r"^.*_(d\d_(?:full|simplified))_seed_0001$", r"\1", t) for t in tasks) == sorted(CONFIGURATIONS)
    for task in tasks:
        data = json.loads((directory / "tasks" / task / "task.json").read_text())
        assert data["env_id"] == spec["id"]
        assert data["metadata"]["benchmark"] == "gym_anything_rt"


def test_splits_cover_every_configuration():
    splits = load_environment_task_splits()
    for env in ENVIRONMENTS:
        assert len(splits[env]["all"]) == 10
        assert len(splits[env]["d5_full"]) == 1
        assert len(splits[env]["full"]) == 5 and len(splits[env]["simplified"]) == 5
        for level in range(1, 6):
            assert len(splits[env][f"d{level}"]) == 2


def test_core_registry_resolves_the_benchmark_by_name():
    from gym_anything.registry import resolve_benchmark_root

    assert resolve_benchmark_root("gym_anything_rt") == BENCHMARK_ROOT
    env = PAIRS[0]["real_time_environment"]
    assert get_tasks_for_environment(env, split="d5_full")[0].endswith("_d5_full_seed_0001")


def test_every_game_has_real_time_settings():
    settings = json.loads((BENCHMARK_ROOT / "real_time.json").read_text())["environments"]
    from gym_anything_rt.realtime import load_real_time_settings, mechanic_id_from_env_dir

    for env in ENVIRONMENTS:
        mechanic = mechanic_id_from_env_dir(DEFAULT_ENVIRONMENTS_ROOT / env)
        assert mechanic in settings
        load_real_time_settings(mechanic)


def test_runner_is_registered_with_gym_anything():
    from gym_anything.runtime.runners.registry import resolve_runner_class
    from gym_anything_rt.runner import RealTimeRunner

    assert resolve_runner_class("gym_anything_rt") is RealTimeRunner
