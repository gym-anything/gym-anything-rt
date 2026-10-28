from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


MECHANIC_ID = "hologram_silhouette_foundry"
COMMON = Path(__file__).with_name("_interaction_vii_viii_common.py")


def generate(task: dict[str, Any], seed: str):
    spec = importlib.util.spec_from_file_location("interaction_vii_viii_generator_common", COMMON)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {COMMON}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate(MECHANIC_ID, task, seed)
