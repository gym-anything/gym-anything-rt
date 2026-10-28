from __future__ import annotations

import importlib.util
from pathlib import Path


MECHANIC_ID = "specular_lighthouse_relay"
COMMON = Path(__file__).with_name("_interaction_vii_viii_common.py")


def _common():
    spec = importlib.util.spec_from_file_location("interaction_vii_viii_solver_common", COMMON)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {COMMON}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    _common().fail_once(page, state_dir, out_dir, mechanic)


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    _common().solve(page, state_dir, out_dir, mechanic)
