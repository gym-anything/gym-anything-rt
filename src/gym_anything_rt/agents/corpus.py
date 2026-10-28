from __future__ import annotations

from pathlib import Path

from gym_anything.registry import (
    load_environment_task_splits,
    resolve_benchmark_root,
)


def evaluation_pairs(
    benchmark: str | Path = "gym_anything_rt",
    *,
    split: str = "all",
    surface: str = "raw",
) -> list[tuple[Path, str]]:
    """Return environment and task pairs through Gym Anything's registry."""
    root = resolve_benchmark_root(benchmark)
    registry = load_environment_task_splits(root, surface=surface)
    pairs: list[tuple[Path, str]] = []
    for environment_name, splits in registry.items():
        if split not in splits:
            available = ", ".join(sorted(splits))
            raise KeyError(
                f"unknown split {split!r} for {environment_name}; available: {available}"
            )
        environment_dir = root / "environments" / environment_name
        pairs.extend((environment_dir, task_id) for task_id in splits[split])
    return pairs
