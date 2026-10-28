from __future__ import annotations

import copy
import hashlib
import json
import random
from typing import Any


MECHANIC_ID = "ballast_lantern_nonrealtime"
GENERATOR_NAME = "ballast_lantern_nonrealtime_v2"
# The counterpart reuses the donor's original HTML/CSS asset manifest.  The
# task-local timing rule is implemented in this plugin, not in an asset.
ASSET_MANIFEST = "shared_runtime/assets/provenance/ballast_lantern_v0.json"
SEED_SALT = "ballast_lantern"
ACTION_WINDOW_MS = 600
TRACK_UNITS = 10_000
VARIANT_COUNT = 48_000_000_000

# Ballast Lantern had no pre-control implementation. This first source-grounded
# configuration is the baseline and is assigned from its active control problem.
BASELINE_PARAMETERS: dict[str, Any] = {
    "tick_ms": 50,
    "max_ticks": 1_000,
    "cage_half_height": 800,
    "specimen_half_height": 180,
    "crate_half_height": 260,
    "thrust_accel": 5,
    "gravity_accel": 4,
    "drag_numerator": 95,
    "drag_denominator": 100,
    "boundary_restitution_numerator": 1,
    "boundary_restitution_denominator": 3,
    "motion_law_pool": ["steady_sinker", "darter", "floater", "oscillator"],
    "specimen_speed_min": 28,
    "specimen_speed_max": 38,
    "specimen_accel": 2,
    "darter_interval_min": 24,
    "darter_interval_max": 36,
    "capture_initial": 3_400,
    "capture_max": 10_000,
    "capture_fill_per_tick": 24,
    "capture_drain_per_tick": 14,
    "crate_meter_max": 3_400,
    "crate_fill_per_tick": 34,
    "crate_spawn_tick_min": 92,
    "crate_spawn_tick_max": 108,
    "crate_min_separation": 2_200,
    "trail_samples": 3,
    "show_trend_beacon": False,
}


def _seed_int(seed: str, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _condition(task: dict[str, Any]) -> dict[str, Any] | None:
    value = task.get("_control_condition")
    return copy.deepcopy(value) if isinstance(value, dict) else None


def _parameters(task: dict[str, Any]) -> dict[str, Any]:
    condition = _condition(task)
    if condition:
        return copy.deepcopy(condition["difficulty_parameters"])
    return copy.deepcopy(BASELINE_PARAMETERS)


def _integer(value: Any, key: str, lower: int, upper: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise ValueError(f"{key} must be an integer in [{lower}, {upper}]")
    return value


def _validate(parameters: dict[str, Any]) -> None:
    ranges = {
        "tick_ms": (40, 100),
        "max_ticks": (500, 1_500),
        "cage_half_height": (600, 1_400),
        "specimen_half_height": (120, 260),
        "crate_half_height": (180, 400),
        "thrust_accel": (3, 8),
        "gravity_accel": (2, 7),
        "drag_numerator": (85, 99),
        "drag_denominator": (100, 100),
        "boundary_restitution_numerator": (0, 3),
        "boundary_restitution_denominator": (2, 5),
        "specimen_speed_min": (14, 52),
        "specimen_speed_max": (18, 64),
        "specimen_accel": (1, 4),
        "darter_interval_min": (14, 50),
        "darter_interval_max": (18, 60),
        "capture_initial": (2_500, 5_500),
        "capture_max": (8_000, 12_000),
        "capture_fill_per_tick": (16, 40),
        "capture_drain_per_tick": (5, 24),
        "crate_meter_max": (1_800, 4_500),
        "crate_fill_per_tick": (24, 64),
        "crate_spawn_tick_min": (60, 150),
        "crate_spawn_tick_max": (70, 170),
        "crate_min_separation": (600, 3_500),
        "trail_samples": (1, 6),
    }
    for key, (lower, upper) in ranges.items():
        _integer(parameters.get(key), key, lower, upper)
    laws = parameters.get("motion_law_pool")
    supported = {"steady_sinker", "darter", "floater", "oscillator"}
    if not isinstance(laws, list) or not laws or len(laws) != len(set(laws)) or not set(laws) <= supported:
        raise ValueError("motion_law_pool must contain distinct supported laws")
    if not isinstance(parameters.get("show_trend_beacon"), bool):
        raise ValueError("show_trend_beacon must be boolean")
    if parameters["cage_half_height"] <= max(parameters["specimen_half_height"], parameters["crate_half_height"]):
        raise ValueError("cage must be visibly large enough to contain each target")
    if parameters["specimen_speed_min"] > parameters["specimen_speed_max"]:
        raise ValueError("specimen speed range is inverted")
    if parameters["darter_interval_min"] > parameters["darter_interval_max"]:
        raise ValueError("darter interval range is inverted")
    if parameters["capture_initial"] >= parameters["capture_max"]:
        raise ValueError("capture meter must start below its terminal value")
    if parameters["capture_fill_per_tick"] <= parameters["capture_drain_per_tick"]:
        raise ValueError("capture fill must exceed drain for a trackable specimen")
    if parameters["crate_spawn_tick_min"] > parameters["crate_spawn_tick_max"]:
        raise ValueError("crate spawn range is inverted")
    if parameters["boundary_restitution_numerator"] >= parameters["boundary_restitution_denominator"]:
        raise ValueError("shaft boundary restitution must lose energy")


def _trunc_div(numerator: int, denominator: int) -> int:
    return numerator // denominator if numerator >= 0 else -((-numerator) // denominator)


def _motion_candidate(
    rng: random.Random,
    parameters: dict[str, Any],
    law: str | None = None,
) -> dict[str, Any]:
    law = law or rng.choice(parameters["motion_law_pool"])
    speed = rng.randint(parameters["specimen_speed_min"], parameters["specimen_speed_max"])
    lower = 900 + parameters["specimen_half_height"]
    upper = 9_100 - parameters["specimen_half_height"]
    start_y = rng.randint(lower + 900, upper - 900)
    direction = rng.choice((-1, 1))
    if law == "steady_sinker":
        start_v = -max(8, speed // 2)
    elif law == "floater":
        start_v = max(8, speed // 2)
    else:
        start_v = direction * speed
    darter_interval = rng.randint(parameters["darter_interval_min"], parameters["darter_interval_max"])
    darter_velocities: list[int] = []
    for index in range(40):
        sign = -1 if (index + rng.randrange(3)) % 2 == 0 else 1
        magnitude = rng.randint(max(14, speed // 2), speed + max(6, speed // 3))
        darter_velocities.append(sign * magnitude)
    return {
        "law": law,
        "min_y": lower,
        "max_y": upper,
        "start_y": start_y,
        "start_velocity": start_v,
        "speed": speed,
        "acceleration": parameters["specimen_accel"],
        "boundary_burst": speed + max(12, speed // 2),
        "darter_interval": darter_interval,
        "darter_velocities": darter_velocities,
    }


def initial_simulation(parameters: dict[str, Any], motion: dict[str, Any], crate: dict[str, Any]) -> dict[str, Any]:
    return {
        "tick": 0,
        "cage_y": max(parameters["cage_half_height"], 1_850),
        "cage_velocity": 0,
        "specimen_y": int(motion["start_y"]),
        "specimen_velocity": int(motion["start_velocity"]),
        "capture_meter": int(parameters["capture_initial"]),
        "crate_meter": 0,
        "crate_spawned": False,
        "specimen_inside": False,
        "crate_inside": False,
        "status": "active",
    }


def _advance_specimen(sim: dict[str, Any], motion: dict[str, Any]) -> None:
    tick = int(sim["tick"])
    law = str(motion["law"])
    velocity = int(sim["specimen_velocity"])
    if law == "darter" and (tick - 1) % int(motion["darter_interval"]) == 0:
        index = ((tick - 1) // int(motion["darter_interval"])) % len(motion["darter_velocities"])
        velocity = int(motion["darter_velocities"][index])
    elif law == "steady_sinker":
        velocity = max(-int(motion["speed"]), velocity - int(motion["acceleration"]))
    elif law == "floater":
        velocity = min(int(motion["speed"]), velocity + int(motion["acceleration"]))

    position = int(sim["specimen_y"]) + velocity
    lower, upper = int(motion["min_y"]), int(motion["max_y"])
    if position <= lower:
        position = lower
        velocity = int(motion["boundary_burst"]) if law == "steady_sinker" else abs(velocity)
    elif position >= upper:
        position = upper
        velocity = -int(motion["boundary_burst"]) if law == "floater" else -abs(velocity)
    sim["specimen_y"] = position
    sim["specimen_velocity"] = velocity


def advance_tick(
    sim: dict[str, Any],
    engaged: bool,
    parameters: dict[str, Any],
    motion: dict[str, Any],
    crate: dict[str, Any],
) -> None:
    if sim["status"] != "active":
        return
    sim["tick"] += 1
    acceleration = parameters["thrust_accel"] if engaged else -parameters["gravity_accel"]
    velocity = int(sim["cage_velocity"]) + int(acceleration)
    velocity = _trunc_div(velocity * parameters["drag_numerator"], parameters["drag_denominator"])
    position = int(sim["cage_y"]) + velocity
    lower = parameters["cage_half_height"]
    upper = TRACK_UNITS - parameters["cage_half_height"]
    if position <= lower:
        position = lower
        velocity = _trunc_div(abs(velocity) * parameters["boundary_restitution_numerator"], parameters["boundary_restitution_denominator"])
    elif position >= upper:
        position = upper
        velocity = -_trunc_div(abs(velocity) * parameters["boundary_restitution_numerator"], parameters["boundary_restitution_denominator"])
    sim["cage_y"] = position
    sim["cage_velocity"] = velocity

    _advance_specimen(sim, motion)
    sim["crate_spawned"] = sim["tick"] >= int(crate["spawn_tick"])
    specimen_limit = parameters["cage_half_height"] - parameters["specimen_half_height"]
    crate_limit = parameters["cage_half_height"] - parameters["crate_half_height"]
    sim["specimen_inside"] = abs(sim["cage_y"] - sim["specimen_y"]) <= specimen_limit
    sim["crate_inside"] = bool(sim["crate_spawned"] and abs(sim["cage_y"] - int(crate["y"])) <= crate_limit)
    if sim["specimen_inside"]:
        sim["capture_meter"] = min(parameters["capture_max"], sim["capture_meter"] + parameters["capture_fill_per_tick"])
    else:
        sim["capture_meter"] = max(0, sim["capture_meter"] - parameters["capture_drain_per_tick"])
    if sim["crate_inside"]:
        sim["crate_meter"] = min(parameters["crate_meter_max"], sim["crate_meter"] + parameters["crate_fill_per_tick"])

    if sim["capture_meter"] <= 0:
        sim["status"] = "escaped"
    elif sim["capture_meter"] >= parameters["capture_max"]:
        sim["status"] = "secured" if sim["crate_meter"] >= parameters["crate_meter_max"] else "specimen_only"
    elif sim["tick"] >= parameters["max_ticks"]:
        sim["status"] = "timeout"


def action_advance_ticks(parameters: dict[str, Any]) -> int:
    """Physics ticks in one deliberate, finite control segment."""

    return max(1, ACTION_WINDOW_MS // int(parameters["tick_ms"]))


def advance_action(
    sim: dict[str, Any],
    engaged: bool,
    parameters: dict[str, Any],
    motion: dict[str, Any],
    crate: dict[str, Any],
) -> None:
    """Advance one action-triggered segment; idle time never calls this."""

    for _ in range(action_advance_ticks(parameters)):
        if sim["status"] != "active":
            break
        advance_tick(sim, engaged, parameters, motion, crate)


def _control_for_target(sim: dict[str, Any], target_y: int, target_velocity: int = 0) -> bool:
    # A phase-leading relay: desired velocity is proportional to future target
    # error. The binary comparison incorporates the cage's retained momentum.
    predicted_target = target_y + target_velocity * 6
    desired_velocity = _trunc_div(predicted_target - int(sim["cage_y"]), 14)
    desired_velocity = max(-105, min(105, desired_velocity))
    return int(sim["cage_velocity"]) < desired_velocity


def _required_exclusive_crate_ticks(parameters: dict[str, Any]) -> int:
    """Require material crate service while the specimen is outside the cage."""

    decision_interval = max(1, 600 // int(parameters["tick_ms"]))
    total_fill_ticks = (
        int(parameters["crate_meter_max"])
        + int(parameters["crate_fill_per_tick"])
        - 1
    ) // int(parameters["crate_fill_per_tick"])
    # At least one complete observation/action interval, and at least 20% of
    # all crate-fill ticks. This rejects incidental edge overlap while scaling
    # the competing-target requirement across the five difficulty profiles.
    return max(decision_interval, (total_fill_ticks + 4) // 5)


def _reference_run(parameters: dict[str, Any], motion: dict[str, Any], crate: dict[str, Any]) -> dict[str, Any]:
    sim = initial_simulation(parameters, motion, crate)
    engaged = False
    crate_mode = False
    events: list[dict[str, Any]] = []
    # Each deliberate control event starts exactly one finite action segment.
    # Repeating the same setting is legal: the player may inspect the settled
    # result indefinitely before issuing that next action.
    decision_interval = action_advance_ticks(parameters)
    low_reserve = max(1_200, parameters["capture_initial"] * 2 // 5)
    high_reserve = min(parameters["capture_max"] - 1_600, parameters["capture_initial"] + 1_100)
    crate_fill_ticks = 0
    exclusive_crate_fill_ticks = 0
    while sim["status"] == "active":
        if sim["tick"] % decision_interval == 0:
            if sim["tick"] >= int(crate["spawn_tick"]) and sim["crate_meter"] < parameters["crate_meter_max"]:
                if sim["capture_meter"] <= low_reserve:
                    crate_mode = False
                elif sim["capture_meter"] >= high_reserve:
                    crate_mode = True
                if crate_mode:
                    desired = _control_for_target(sim, int(crate["y"]))
                else:
                    desired = _control_for_target(sim, int(sim["specimen_y"]), int(sim["specimen_velocity"]))
            else:
                desired = _control_for_target(sim, int(sim["specimen_y"]), int(sim["specimen_velocity"]))
            engaged = desired
            events.append({"tick": int(sim["tick"]), "engaged": engaged})
        for _ in range(action_advance_ticks(parameters)):
            if sim["status"] != "active":
                break
            previous_crate_meter = int(sim["crate_meter"])
            advance_tick(sim, engaged, parameters, motion, crate)
            if int(sim["crate_meter"]) > previous_crate_meter:
                crate_fill_ticks += 1
                if not bool(sim["specimen_inside"]):
                    exclusive_crate_fill_ticks += 1
    return {
        "events": events,
        "final_state": copy.deepcopy(sim),
        "allocation_metrics": {
            "crate_fill_ticks": crate_fill_ticks,
            "exclusive_crate_fill_ticks": exclusive_crate_fill_ticks,
        },
    }


def _specimen_only_run(
    parameters: dict[str, Any], motion: dict[str, Any], crate: dict[str, Any]
) -> dict[str, Any]:
    """Run the same cadence while deliberately targeting only the specimen."""

    sim = initial_simulation(parameters, motion, crate)
    engaged = False
    decision_interval = action_advance_ticks(parameters)
    while sim["status"] == "active":
        if int(sim["tick"]) % decision_interval == 0:
            engaged = _control_for_target(
                sim, int(sim["specimen_y"]), int(sim["specimen_velocity"])
            )
        advance_action(sim, engaged, parameters, motion, crate)
    return copy.deepcopy(sim)


def _specimen_at_tick(parameters: dict[str, Any], motion: dict[str, Any], tick: int) -> int:
    dummy_crate = {"spawn_tick": tick + 1, "y": TRACK_UNITS // 2}
    sim = initial_simulation(parameters, motion, dummy_crate)
    for _ in range(tick):
        sim["tick"] += 1
        _advance_specimen(sim, motion)
    return int(sim["specimen_y"])


def _crate_candidate(rng: random.Random, parameters: dict[str, Any], motion: dict[str, Any]) -> dict[str, Any] | None:
    spawn_tick = rng.randint(parameters["crate_spawn_tick_min"], parameters["crate_spawn_tick_max"])
    specimen_y = _specimen_at_tick(parameters, motion, spawn_tick)
    lower = parameters["cage_half_height"] + 250
    upper = TRACK_UNITS - parameters["cage_half_height"] - 250
    candidates = [
        value
        for value in range(lower, upper + 1, 200)
        if abs(value - specimen_y) >= parameters["crate_min_separation"]
    ]
    if not candidates:
        return None
    return {"spawn_tick": spawn_tick, "y": rng.choice(candidates)}


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parameters = _parameters(task)
    _validate(parameters)
    # Keep corresponding donor/counterpart seeds on the same generated world;
    # only the task-local mechanic identity and timing contract differ.
    rng = random.Random(_seed_int(seed, SEED_SALT))
    selected_law = rng.choice(parameters["motion_law_pool"])
    chosen: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], int] | None = None
    required_exclusive_ticks = _required_exclusive_crate_ticks(parameters)
    for attempt in range(1, 513):
        motion = _motion_candidate(rng, parameters, selected_law)
        crate = _crate_candidate(rng, parameters, motion)
        if crate is None:
            continue
        reference = _reference_run(parameters, motion, crate)
        final = reference["final_state"]
        specimen_only_final = _specimen_only_run(parameters, motion, crate)
        if (
            final["status"] == "secured"
            and 8 <= len(reference["events"]) <= 220
            and specimen_only_final["status"] != "secured"
            and reference["allocation_metrics"]["exclusive_crate_fill_ticks"]
            >= required_exclusive_ticks
        ):
            chosen = motion, crate, reference, specimen_only_final, attempt
            break
    if chosen is None:
        raise ValueError("could not generate a certified Ballast Lantern shaft")
    motion, crate, reference, specimen_only_final, generation_attempts = chosen

    condition = _condition(task)
    parameter_token = hashlib.sha256(
        json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:10]
    challenge_id = hashlib.sha256(
        f"{seed}|{MECHANIC_ID}|{GENERATOR_NAME}|{parameter_token}".encode("utf-8")
    ).hexdigest()[:12]
    task_id = str(task.get("id") or "ballast_lantern_nonrealtime_seed_0001@0.1")
    world = {
        "track_units": TRACK_UNITS,
        "parameters": copy.deepcopy(parameters),
        "motion": copy.deepcopy(motion),
        "crate": copy.deepcopy(crate),
        "initial_state": initial_simulation(parameters, motion, crate),
    }
    public_state: dict[str, Any] = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "asset_manifest": ASSET_MANIFEST,
        "prompt": task.get("natural_language")
        or "Secure the drifting specimen and the ballast crate with the same momentum-carrying lantern cage.",
        "generator": {"name": GENERATOR_NAME, "variant_count": VARIANT_COUNT},
        **copy.deepcopy(world),
    }
    ground_truth: dict[str, Any] = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "asset_manifest": ASSET_MANIFEST,
        **copy.deepcopy(world),
        "reference_schedule": reference["events"],
        "reference_final_state": reference["final_state"],
        "reference_metrics": {
            "terminal_tick": reference["final_state"]["tick"],
            "control_transitions": len(reference["events"]),
            "law": motion["law"],
            "crate_fill_ticks": reference["allocation_metrics"]["crate_fill_ticks"],
            "exclusive_crate_fill_ticks": reference["allocation_metrics"][
                "exclusive_crate_fill_ticks"
            ],
            "required_exclusive_crate_fill_ticks": required_exclusive_ticks,
            "specimen_only_final_status": specimen_only_final["status"],
            "specimen_only_crate_meter": specimen_only_final["crate_meter"],
            "specimen_only_crate_completed": (
                specimen_only_final["crate_meter"] >= parameters["crate_meter_max"]
            ),
            "competing_target_certified": True,
            "generation_attempts": generation_attempts,
        },
    }
    if condition:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    return public_state, ground_truth
