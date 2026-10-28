"""Gym-Anything-RT bindings for the core benchmark registry.

All discovery logic lives in ``gym_anything.registry``. This module binds it
to the Gym-Anything-RT roots and adds the pairing between each real-time
minigame and its non-real-time counterpart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Union

from gym_anything import registry as _core

resolve_environment_key = _core.resolve_environment_key

BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPLITS_ROOT = BENCHMARK_ROOT / "splits"
DEFAULT_ENVIRONMENTS_ROOT = BENCHMARK_ROOT / "environments"
PAIRS_PATH = BENCHMARK_ROOT / "pairs.json"

# Every task folder physically present under ``<env>/tasks/``.
DISK_SPLIT = _core.DISK_SPLIT


def resolve_environment_dir(
    env_ref: Union[str, Path],
    environments_root: Path = DEFAULT_ENVIRONMENTS_ROOT,
) -> Path:
    return _core.resolve_environment_dir(env_ref, environments_root=environments_root)


def load_environment_task_splits(
    *,
    surface: str = "raw",
    splits_root: Path = DEFAULT_SPLITS_ROOT,
    environments_root: Path = DEFAULT_ENVIRONMENTS_ROOT,
) -> Dict[str, Dict[str, List[str]]]:
    return _core.load_environment_task_splits(
        surface=surface,
        splits_root=splits_root,
        environments_root=environments_root,
    )


def get_tasks_for_environment(
    env_ref: Union[str, Path],
    *,
    split: str = "all",
    surface: str = "raw",
    splits_root: Path = DEFAULT_SPLITS_ROOT,
    environments_root: Path = DEFAULT_ENVIRONMENTS_ROOT,
) -> List[str]:
    return _core.get_tasks_for_environment(
        env_ref,
        split=split,
        surface=surface,
        splits_root=splits_root,
        environments_root=environments_root,
    )


def load_pairs(path: Path = PAIRS_PATH) -> List[dict]:
    """Each real-time minigame with its non-real-time counterpart."""
    return json.loads(Path(path).read_text(encoding="utf-8"))["pairs"]
