from __future__ import annotations

import copy
import hashlib
import json
import random
from typing import Any


MECHANIC_ID = "consent_gauntlet"

POSITIVE_PURPOSES = (
    "Use my rough location for tailored offers",
    "Combine browsing history with partner data",
    "Store a device fingerprint for recognition",
    "Measure me across affiliated sites",
    "Create a personalised advertising profile",
    "Let vendors retain session activity",
    "Share checkout behaviour with sponsors",
    "Permit cross-site analytics",
    "Link this visit to data-broker records",
    "Keep a persistent advertising identifier",
    "Send reading habits to commercial partners",
    "Use purchase intent for targeted messages",
)

NEGATIVE_PURPOSES = (
    "Do not sell my activity history",
    "Disable personalised advertising",
    "Block partner profiling",
    "Refuse cross-site measurement",
    "Disallow precise-location storage",
    "Prevent vendors from linking sessions",
    "Never share purchase intent",
    "Stop device fingerprinting",
    "Do not combine this visit with broker records",
    "Disable commercial audience matching",
)

ENTRY_CORRECT = (
    "Audit optional processing",
    "Review data controls",
    "Configure privacy choices",
    "Open the processing ledger",
)
ENTRY_DECOYS = (
    "Continue with recommended settings",
    "Accept partner services",
    "Agree and enter",
    "Use the personalised experience",
    "Allow selected and recommended uses",
    "Save time with standard consent",
    "Proceed with trusted partners",
    "Accept and manage later",
)
FINAL_CORRECT = (
    "Keep only the choices shown",
    "Save selected answers",
    "Apply my current privacy choices",
    "Confirm these controls",
)
FINAL_DECOYS = (
    "Apply recommended selections",
    "Accept all and continue",
    "Enable essential and partner services",
    "Reset then save",
    "Approve all current purposes",
    "Use the provider defaults",
    "Accept selected plus recommendations",
    "Confirm the standard experience",
)
DRAWER_LABELS = ("IDENTITY", "BEHAVIOUR", "PARTNERS", "MEASUREMENT")
STYLE_TONES = ("ink", "coral", "mint", "paper", "violet", "amber", "ghost")


def _condition(task: dict[str, Any]) -> dict[str, Any] | None:
    value = task.get("_control_condition")
    return copy.deepcopy(value) if isinstance(value, dict) else None


def _parameters(task: dict[str, Any]) -> dict[str, Any]:
    condition = _condition(task)
    if condition:
        return copy.deepcopy(condition["difficulty_parameters"])
    return {
        "purpose_count": 6,
        "negative_count": 2,
        "drawer_count": 2,
        "entry_option_count": 5,
        "final_option_count": 5,
        "reset_trap_count": 1,
        "link_count": 0,
        "moving_gateways": True,
        "orbit_speed_deg_per_second": 14,
    }


def _validate(parameters: dict[str, Any]) -> None:
    bounds = {
        "purpose_count": (3, 10),
        "negative_count": (0, 5),
        "drawer_count": (1, 4),
        "entry_option_count": (1, 7),
        "final_option_count": (1, 7),
        "reset_trap_count": (0, 2),
        "link_count": (0, 2),
        "orbit_speed_deg_per_second": (0, 36),
    }
    for key, (low, high) in bounds.items():
        value = parameters.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{key} must be an integer in [{low}, {high}]")
    if parameters["negative_count"] > parameters["purpose_count"]:
        raise ValueError("negative_count exceeds purpose_count")
    if parameters["drawer_count"] > parameters["purpose_count"]:
        raise ValueError("drawer_count exceeds purpose_count")
    if parameters["reset_trap_count"] > parameters["drawer_count"]:
        raise ValueError("reset_trap_count exceeds drawer_count")
    if parameters["link_count"] * 2 > parameters["purpose_count"]:
        raise ValueError("link_count exceeds available purposes")
    if not isinstance(parameters.get("moving_gateways"), bool):
        raise ValueError("moving_gateways must be boolean")
    if not parameters["moving_gateways"] and parameters["orbit_speed_deg_per_second"] != 0:
        raise ValueError("stationary gateways must use zero orbit speed")


def _gateway(
    rng: random.Random,
    prefix: str,
    option_count: int,
    correct_pool: tuple[str, ...],
    decoy_pool: tuple[str, ...],
    correct_action: str,
    decoy_action: str,
) -> list[dict[str, Any]]:
    labels = [(rng.choice(correct_pool), correct_action)]
    labels.extend((label, decoy_action) for label in rng.sample(decoy_pool, option_count - 1))
    rng.shuffle(labels)
    phase_shift = rng.uniform(0, 360)
    return [
        {
            "id": f"{prefix}-{index + 1}",
            "label": label,
            "action": action,
            "tone": rng.choice(STYLE_TONES),
            "angle_offset_deg": round((phase_shift + index * 360 / option_count) % 360, 5),
        }
        for index, (label, action) in enumerate(labels)
    ]


def generate(task: dict[str, Any], seed: str):
    parameters = _parameters(task)
    _validate(parameters)
    stable = hashlib.sha256(
        f"{MECHANIC_ID}:{seed}:{json.dumps(parameters, sort_keys=True, separators=(',', ':'))}".encode("utf-8")
    ).hexdigest()
    rng = random.Random(int(stable[:16], 16))
    challenge_id = f"cgt-{stable[:18]}"
    task_id = str(task.get("id") or "consent_gauntlet")

    positive_count = parameters["purpose_count"] - parameters["negative_count"]
    purpose_specs = [(label, False) for label in rng.sample(POSITIVE_PURPOSES, positive_count)]
    purpose_specs.extend((label, True) for label in rng.sample(NEGATIVE_PURPOSES, parameters["negative_count"]))
    rng.shuffle(purpose_specs)

    purposes = []
    for index, (label, target) in enumerate(purpose_specs):
        initial = rng.choice((True, False))
        purposes.append({
            "id": f"purpose-{index + 1}",
            "label": label,
            "drawer_id": f"drawer-{index % parameters['drawer_count'] + 1}",
            "state": initial,
            "initial_state": initial,
            "target": target,
        })

    drawers = []
    for index in range(parameters["drawer_count"]):
        drawer_id = f"drawer-{index + 1}"
        drawers.append({
            "id": drawer_id,
            "label": DRAWER_LABELS[index],
            "purpose_ids": [item["id"] for item in purposes if item["drawer_id"] == drawer_id],
        })

    reset_traps = [
        {
            "id": f"reset-{index + 1}",
            "drawer_id": drawers[index]["id"],
            "label": rng.choice((
                "Restore provider defaults",
                "Reapply recommended balance",
                "Return this drawer to standard",
                "Reset all choices in this drawer",
            )),
        }
        for index in range(parameters["reset_trap_count"])
    ]

    shuffled_ids = [item["id"] for item in purposes]
    rng.shuffle(shuffled_ids)
    links = []
    for index in range(parameters["link_count"]):
        source_id = shuffled_ids[index * 2]
        target_id = shuffled_ids[index * 2 + 1]
        links.append({
            "id": f"link-{index + 1}",
            "source_id": source_id,
            "target_id": target_id,
            "effect": "flip",
            "label": f"{source_id.replace('purpose-', 'P')} moves {target_id.replace('purpose-', 'P')}",
        })
    linked_sources = {item["source_id"] for item in links}
    for purpose in purposes:
        if purpose["id"] in linked_sources:
            purpose["state"] = not purpose["target"]
            purpose["initial_state"] = purpose["state"]

    surface = {
        "entry_options": _gateway(
            rng, "entry", parameters["entry_option_count"], ENTRY_CORRECT, ENTRY_DECOYS, "manage", "accept"
        ),
        "final_options": _gateway(
            rng, "final", parameters["final_option_count"], FINAL_CORRECT, FINAL_DECOYS, "commit", "accept"
        ),
        "drawers": drawers,
        "purposes": [{key: value for key, value in item.items() if key != "target"} for item in purposes],
        "reset_traps": reset_traps,
        "links": links,
        "phase_deg": round(rng.uniform(0, 360), 5),
    }
    targets = {item["id"]: item["target"] for item in purposes}
    initial_states = {item["id"]: item["initial_state"] for item in purposes}
    condition = _condition(task)
    public_state = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": "Leave every optional purpose blocked, then keep only the choices you made.",
        "surface": copy.deepcopy(surface),
        "parameters": copy.deepcopy(parameters),
        "asset_manifest": str((task.get("metadata") or {}).get("asset_manifest") or "shared_runtime/assets/provenance/consent_gauntlet_v0.json"),
        "status": "ready",
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "surface": copy.deepcopy(surface),
        "targets": targets,
        "initial_states": initial_states,
        "parameters": copy.deepcopy(parameters),
    }
    if condition is not None:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    return public_state, ground_truth
