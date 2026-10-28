"""Original continuous-census district game, grounded in WEB-320 and TRW-161."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "charter_of_the_nine_cantons_v3"
REVISION = "continuous-census-folios-4"
# Preserve the frozen V2 worlds, including every nonperiodic turning point.
MOTION_REVISION = "continuous-census-3"
PROFILES = {
    1: dict(active_borders=1, gap=90, amplitude=110, span_ms=9500, per_canton=6),
    2: dict(active_borders=2, gap=82, amplitude=110, span_ms=9000, per_canton=6),
    3: dict(active_borders=3, gap=74, amplitude=110, span_ms=8500, per_canton=9),
    4: dict(active_borders=4, gap=62, amplitude=110, span_ms=8200, per_canton=9),
    5: dict(active_borders=6, gap=52, amplitude=110, span_ms=8000, per_canton=12),
}
GUILDS = [dict(id="gilt", color="#ad7714", mark="sun"),
          dict(id="tide", color="#14778c", mark="wave"),
          dict(id="plum", color="#963c68", mark="bloom")]
COLORS = ["#d68b69", "#d7b45e", "#a4b36d", "#76ae91", "#6faab6",
          "#90a5c5", "#b297c3", "#cc9eb0", "#c5a278"]


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    level = (condition or {}).get("difficulty", 5)
    mode = (condition or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("invalid continuous-census controls")
    parameters = copy.deepcopy((condition or {}).get("difficulty_parameters", PROFILES[level]))
    if parameters != PROFILES[level]:
        raise ValueError("continuous-census profile differs from the documented difficulty")
    stable = hashlib.sha256(f"{MOTION_REVISION}|{seed}|d{level}".encode()).hexdigest()
    rng = random.Random(int(stable[:16], 16))
    winners = ["gilt"] * 5 + ["tide"] * 2 + ["plum"] * 2
    rng.shuffle(winners)
    active = rng.sample(range(6), parameters["active_borders"])
    borders = []
    for index in range(6):
        span = parameters["span_ms"] + rng.randrange(-400, 401)
        amplitude = parameters["amplitude"] if index in active else 0
        # Alternating distant turning points make any parked border lose
        # balance within an audit. Durations and amplitudes are freshly seeded
        # at each turn; there is no repeatable patrol period.
        direction = rng.choice((-1, 1))
        t = -rng.randrange(span // 2)
        knots = []
        while t <= 145000:
            knots.append([t, round(direction * amplitude * rng.uniform(.85, 1), 3)])
            direction *= -1
            t += rng.randrange(round(span * .65), round(span * 1.35) + 1)
        knots.append([t, round(direction * amplitude * rng.uniform(.85, 1), 3)])
        borders.append(dict(id=index, row=index // 2, base=340 if index % 2 == 0 else 700,
                            amplitude=parameters["amplitude"] if index in active else 0,
                            span_ms=span, knots=knots, gap=parameters["gap"],
                            initial=340 if index % 2 == 0 else 700))
    voters = []
    population = parameters["per_canton"]
    for canton, winner in enumerate(winners):
        row, column = divmod(canton, 3)
        # Stable households + two migrating households on each internal border.
        descriptions = []
        for side in ("left", "right"):
            if (side == "left" and column == 0) or (side == "right" and column == 2):
                continue
            border = row * 2 + (column - 1 if side == "left" else column)
            sign = 1 if side == "left" else -1
            for offset in range(2):
                descriptions.append(dict(border=border, offset=sign * parameters["gap"] / 2,
                                         y=75 + offset * 46))
        fixed_count = population - len(descriptions)
        center = [160, 520, 880][column]
        for offset in range(fixed_count):
            descriptions.append(dict(x=center + (offset % 3 - 1) * 26,
                                     y=50 + (offset // 3) * 28))
        # A strict plurality is visible, independent of population counts.
        labels = [winner] * (population // 2 + 1)
        losers = [g["id"] for g in GUILDS if g["id"] != winner]
        labels += [losers[index % 2] for index in range(population - len(labels))]
        rng.shuffle(labels)
        for index, (description, guild) in enumerate(zip(descriptions, labels)):
            voters.append(dict(id=f"house-{canton}-{index}", row=row, guild=guild, **description))
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  revision=REVISION, task_id=task["id"], challenge_id="census-folios-" + stable[:16],
                  prompt="Charter of the Nine Cantons V3", parameters=parameters,
                  borders=borders, voters=voters, guilds=GUILDS, colors=COLORS,
                  population=population, target_split=dict(gilt=5, tide=2, plum=2),
                  inspection=dict(kind="field_census_folios", rows=3,
                                  concealed="migrant_households_and_row_register",
                                  persistence="revealed_rows_remain_live"),
                  simulation=dict(tick_ms=20, audit_ms=30000, imbalance_rule="reset_streak",
                                  deadline_ms=120000, world_width=1040, row_height=190),
                  asset_manifest="shared_runtime/assets/provenance/charter_of_the_nine_cantons_v3_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18))
    if condition is not None:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), intended_winners=winners)
    return public, truth
