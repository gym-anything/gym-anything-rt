"""CRAFTCHA's material lineage, rebuilt as a moving stormglass foundry.

All art, recipes and paths are original. Interaction never enters world RNG.
The forecast on the task surface is a real sample of the motion used for hits.
"""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "craftcha_alchemy_bench_v2"
REVISION = "stormglass-2"
PROFILES = {
    1: dict(raw_count=3, radius=28, motion_span_ms=6500, hot_lifetime_ms=60000, tree="chain"),
    2: dict(raw_count=4, radius=27, motion_span_ms=5600, hot_lifetime_ms=48000, tree="balanced"),
    3: dict(raw_count=6, radius=26, motion_span_ms=4800, hot_lifetime_ms=36000, tree="balanced"),
    4: dict(raw_count=8, radius=25, motion_span_ms=4300, hot_lifetime_ms=26000, tree="balanced"),
    5: dict(raw_count=10, radius=24, motion_span_ms=3600, hot_lifetime_ms=18000, tree="balanced"),
}
SYMBOLS = ("✦", "◇", "≋", "△", "☽", "✚", "⊙", "⌁", "⬡", "⊗")
COLORS = ("#ffbf69", "#74d6c8", "#c4a0f6", "#ff9292", "#83bafa", "#dddb87", "#f6a9db", "#8fd2a2", "#e4b18b", "#acc6f5")
NAMES = ("Sun salt", "Tide glass", "Moon ash", "Ember", "Night dew", "Thorn oil", "Star iron", "Mist", "Honey stone", "Echo dust")


def generate(task, seed):
    condition = task.get("_control_condition") or task.get("metadata", {}).get("control_condition")
    level = (condition or {}).get("difficulty", 5)
    if type(level) is not int or level not in PROFILES:
        raise ValueError("Alchemy difficulty must be an integer from one through five")
    mode = (condition or {}).get("interaction", "full")
    if mode not in ("full", "simplified"):
        raise ValueError("Unknown alchemy input surface")
    params = copy.deepcopy(PROFILES[level])
    if condition and condition.get("difficulty_parameters") != params:
        raise ValueError("Alchemy controls differ from the supported profile")
    rng = random.Random(hashlib.sha256(f"{MECHANIC_ID}|{REVISION}|{seed}|{level}".encode()).digest())
    challenge_id = hashlib.sha256(f"{MECHANIC_ID}|{REVISION}|{seed}|{level}".encode()).hexdigest()[:16]
    # Ten separated levitation wells. Even at their extremities two bodies
    # cannot overlap; the whole visible circle is the selection/drop hitbox.
    lots = []
    for index in range(10):
        lots.append(dict(id=index, center=[88 + 176 * (index % 5), 90 + 170 * (index // 5)],
                         motion_seed=rng.getrandbits(32), amplitude=[55, 25],
                         span_ms=params["motion_span_ms"]))
    slots = rng.sample(range(10), params["raw_count"])
    identities = rng.sample(range(10), params["raw_count"])
    materials, initial = {}, []
    for i, (lot, identity) in enumerate(zip(slots, identities)):
        key = f"raw-{i}"
        materials[key] = dict(name=NAMES[identity], symbol=SYMBOLS[identity], color=COLORS[identity], hot=False)
        initial.append(dict(id=key, lot=lot, born_ms=0))
    recipes = []

    def join(left, right):
        key = f"blend-{len(recipes)}"
        # Pair colors with an explicit numeral: color is never the only cue.
        symbol = str(len(recipes) + 1)
        materials[key] = dict(name=f"Blend {symbol}", symbol=symbol,
                              color=COLORS[(len(recipes) + level) % 10], hot=True)
        recipes.append(dict(inputs=[left, right], output=key))
        return key

    def tree(leaves):
        if len(leaves) == 1:
            return leaves[0]
        split = 1 if params["tree"] == "chain" else len(leaves) // 2
        return join(tree(leaves[:split]), tree(leaves[split:]))

    leaves = [item["id"] for item in initial]
    rng.shuffle(leaves)
    goal = tree(leaves)
    materials[goal].update(name="Stormglass heart", symbol="♥", hot=False)
    if condition is None:
        condition = dict(difficulty=level, interaction=mode, real_time="live", difficulty_parameters=params)
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, revision=REVISION,
                  task_id=task["id"], challenge_id=challenge_id,
                  control_condition=copy.deepcopy(condition), parameters=params,
                  prompt="Forge the Stormglass heart. Merge the pictured pairs while the other reagent keeps moving.",
                  lots=lots, materials=materials, initial=initial, recipes=recipes, goal=goal,
                  stage=dict(width=880, height=360), forecast_ms=2500, trail_ms=800, formation_ms=5000,
                  play_time_ms=210000, max_events=1000,
                  asset_manifest=f"shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18,
                                 variant_count_kind="Recipe permutations, well assignments and independent nonperiodic motion"))
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    truth["oracle_order"] = copy.deepcopy(recipes)
    return public, truth
