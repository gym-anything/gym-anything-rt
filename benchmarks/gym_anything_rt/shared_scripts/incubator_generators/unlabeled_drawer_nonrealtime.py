"""Matched v2 cabinet contract with stable, action-driven decision geometry."""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import random

MECHANIC_ID = "unlabeled_drawer_nonrealtime"
REVISION = "moving-cabinet-3"
GENERATION_REVISION = "moving-cabinet-1"
PROFILES = {
    1: dict(family="literal", feature_pool=2, drawers=2, lanes=1, mouth_width=220,
            motion_amplitude=240, motion_span_ms=11000, life_ms=18000, spacing_ms=10000, nuisance=.05),
    2: dict(family="literal", feature_pool=4, drawers=2, lanes=1, mouth_width=190,
            motion_amplitude=260, motion_span_ms=9500, life_ms=16000, spacing_ms=8500, nuisance=.2),
    3: dict(family="relation", feature_pool=4, drawers=2, lanes=2, mouth_width=162,
            motion_amplitude=280, motion_span_ms=8500, life_ms=14000, spacing_ms=4800, nuisance=.35),
    4: dict(family="two_bits", feature_pool=4, drawers=4, lanes=2, mouth_width=140,
            motion_amplitude=300, motion_span_ms=7500, life_ms=12500, spacing_ms=4000, nuisance=.5),
    5: dict(family="two_relations", feature_pool=4, drawers=4, lanes=3, mouth_width=118,
            motion_amplitude=320, motion_span_ms=7000, life_ms=11500, spacing_ms=3100, nuisance=.7),
}
FEATURES = ["hollow / solid core", "spined / smooth rim", "paired / single satellites", "crossed / parallel veins"]


def category(features, rule):
    a = [int(features[i]) for i in rule["indices"]]
    family = rule["family"]
    if family == "literal": value = a[0]
    elif family == "relation": value = a[0] ^ a[1]
    elif family == "two_bits": value = 2 * a[0] + a[1]
    elif family == "two_relations": value = 2 * (a[0] ^ a[1]) + (a[2] ^ a[3])
    else: raise ValueError("unknown concept family")
    return rule["mapping"][value]


def rule_hypotheses(parameters):
    family, pool = parameters["family"], parameters["feature_pool"]
    n = {"literal": 1, "relation": 2, "two_bits": 2, "two_relations": 4}[family]
    vectors = list(itertools.product((False, True), repeat=pool))
    unique = {}
    for indices in itertools.permutations(range(pool), n):
        for mapping in itertools.permutations(range(parameters["drawers"])):
            rule = dict(family=family, indices=list(indices), mapping=list(mapping))
            signature = tuple(category(v, rule) for v in vectors)
            unique.setdefault(signature, rule)
    return list(unique.values())


def episode_history(task_id):
    """Carry the bound episode's first rejected commitment through generation.

    Calibration and cancellations never submit a result. The existing server
    journal therefore contains committed rejections, not calibration feedback.
    Read it without clearing counters, replacing records or changing the server.
    """
    directory = Path(os.environ.get("GYM_ANYTHING_RT_STATE_DIR", "/tmp/gym_anything_rt"))
    try:
        with (directory / "attempts.jsonl").open(encoding="utf-8") as journal:
            current = json.loads((directory / "current_task.json").read_text(encoding="utf-8"))
            bound = current.get("task") if isinstance(current, dict) else None
            metadata = bound.get("metadata") if isinstance(bound, dict) else None
            if (not isinstance(bound, dict) or not bound.get("id")
                    or not isinstance(metadata, dict) or not metadata.get("mechanic_id")):
                raise ValueError("unavailable bound task")
            if bound["id"] != task_id or metadata.get("mechanic_id") != MECHANIC_ID:
                return False, "", ""
            for line in journal:
                if not line.strip():
                    continue
                attempt = json.loads(line)
                decision = attempt.get("server_grade") if isinstance(attempt, dict) else None
                if not isinstance(decision, dict) or decision.get("graded") is not True:
                    raise ValueError("unverified episode record")
                if decision.get("passed") is False:
                    # Rejected payload identity is client input; the journal is
                    # scoped by current_task.json, written by the shared server.
                    return True, str(decision.get("feedback") or "Rejected committed filing case."), ""
                if decision.get("passed") is not True:
                    raise ValueError("missing episode verdict")
    except FileNotFoundError as error:
        if error.filename != str(directory / "attempts.jsonl"):
            return False, "", "Episode history has no bound task record."
    except (OSError, UnicodeError, ValueError, TypeError):
        return False, "", "Episode failure history is unavailable."
    return False, "", ""


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    level = (condition or {}).get("difficulty", 5)
    if type(level) is not int or level not in PROFILES:
        raise ValueError("difficulty must be an integer from 1 through 5")
    parameters = copy.deepcopy((condition or {}).get("difficulty_parameters", PROFILES[level]))
    if parameters != PROFILES[level]:
        raise ValueError("unsupported moving-cabinet profile")
    if (condition or {}).get("interaction", "full") not in ("full", "simplified"):
        raise ValueError("unsupported interaction")
    # Keep counterpart seeds content-compatible with the evaluated v2 donor;
    # only the task namespace and timing contract differ.
    stable = hashlib.sha256(f"unlabeled_drawer_v2|{GENERATION_REVISION}|{seed}|{level}".encode()).hexdigest()
    rng = random.Random(int(stable, 16))
    rules = rule_hypotheses(parameters)
    rule = copy.deepcopy(rng.choice(rules))
    pool = parameters["feature_pool"]
    vectors = list(itertools.product((False, True), repeat=pool))
    rng.shuffle(vectors)

    def specimen(identifier, vector):
        return dict(id=identifier, features=list(vector) + [False] * (4-pool),
                    style=dict(palette=rng.randrange(4), angle=round(rng.uniform(-18, 18)*parameters["nuisance"], 3),
                               scale=round(rng.uniform(.93, 1.07), 4)))

    probes = [dict(specimen(f"P{i+1:02}", vector), center=[105+(i%4)*155, 47+(i//4)*72], width=112, height=64)
              for i, vector in enumerate(vectors)]
    # Every class occurs twice; classification is independent of arrival order and lane.
    final_vectors = []
    for drawer in range(parameters["drawers"]):
        choices = [v for v in vectors if category(v, rule) == drawer]
        final_vectors.extend(rng.choice(choices) for _ in range(8//parameters["drawers"]))
    rng.shuffle(final_vectors)
    cargo = []
    columns = (8 + parameters["lanes"] - 1) // parameters["lanes"]
    release = 1200
    for i, vector in enumerate(final_vectors):
        if i: release += parameters["spacing_ms"] + rng.randint(-260, 260)
        stable_x = 480 if columns == 1 else 70 + 820 * (i // parameters["lanes"]) / (columns - 1)
        cargo.append(dict(specimen(f"S{i+1:02}", vector), spawn_ms=release, lane=i % parameters["lanes"],
                          life_ms=parameters["life_ms"] + rng.randint(-350, 350),
                          stable_center=[round(stable_x, 3), 70 + 90 * (i % parameters["lanes"])],
                          width=112, height=82))
    drawers = [dict(id=i, label=chr(65+i), seed=rng.getrandbits(32), y=325+60*i,
                    width=parameters["mouth_width"], height=46, amplitude=parameters["motion_amplitude"],
                    span_ms=parameters["motion_span_ms"] + rng.randint(-200, 200))
               for i in range(parameters["drawers"])]
    public = dict(mechanic_id=MECHANIC_ID, revision=REVISION, task_id=task["id"],
                  challenge_id="ud2-"+stable[:20], parameters=parameters, stage=dict(width=960, height=560),
                  probes=probes, cargo=cargo, drawers=drawers, probe_slot=[760, 165, 180, 128],
                  runtime_probe_answers={p["id"]: category(p["features"], rule) for p in probes},
                  runtime_final_answers={p["id"]: category(p["features"], rule) for p in cargo},
                  feature_legend=FEATURES[:pool], single_attempt=True, play_time_ms=180000,
                  asset_manifest="shared_runtime/assets/provenance/unlabeled_drawer_v2_v0.json")
    failed, reason, history_error = episode_history(task["id"])
    public.update(episode_failed=failed, episode_failure_reason=reason, episode_history_error=history_error)
    if condition is not None: public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), rule=rule)
    return public, truth
