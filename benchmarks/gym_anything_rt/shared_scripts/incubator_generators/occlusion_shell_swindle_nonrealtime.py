from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "occlusion_shell_swindle_nonrealtime"
# Keep the extracted counterpart on the donor's seed stream.  The mechanic
# namespace is deliberately different, but renaming it must not reshuffle the
# corresponding shell scene.
SEED_SALT = "occlusion_shell_swindle_v2"
STAGE_WIDTH = 1000
STAGE_HEIGHT = 420
TICK_MS = 120
PREVIEW_MS = 900
SHELL_RADIUS = 27


# The uncontrolled task is intentionally represented by these values rather
# than a nearby controlled profile.  In particular, keeping the same random
# calls and parameter values for L2 preserves the historical world for a
# fixed seed.
DEFAULT_PROFILE = {
    "shell_count_values": (4, 5),
    "round_count": 3,
    "transfer_round_count_values": (1, 2),
    "frame_count_min": 60,
    "frame_count_max": 68,
    "tick_ms": TICK_MS,
    "preview_ms": PREVIEW_MS,
    "handoff_window_ticks": 3,
    "inspection_minimum_samples": 3,
    "inspection_port_radius": 46,
    "decoy_port_count": 0,
}


def _profile(task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return a validated controlled profile without perturbing legacy seeds."""

    condition = task.get("_control_condition")
    if condition is None:
        return dict(DEFAULT_PROFILE), None
    if not isinstance(condition, dict):
        raise ValueError("occlusion-shell-v2 control condition is malformed")
    parameters = condition.get("difficulty_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("occlusion-shell-v2 difficulty parameters are missing")
    required = set(DEFAULT_PROFILE)
    if set(parameters) != required:
        raise ValueError("occlusion-shell-v2 difficulty parameters do not match the profile schema")
    try:
        profile = {
            "shell_count_values": tuple(int(value) for value in parameters["shell_count_values"]),
            "round_count": int(parameters["round_count"]),
            "transfer_round_count_values": tuple(int(value) for value in parameters["transfer_round_count_values"]),
            "frame_count_min": int(parameters["frame_count_min"]),
            "frame_count_max": int(parameters["frame_count_max"]),
            "tick_ms": int(parameters["tick_ms"]),
            "preview_ms": int(parameters["preview_ms"]),
            "handoff_window_ticks": int(parameters["handoff_window_ticks"]),
            "inspection_minimum_samples": int(parameters["inspection_minimum_samples"]),
            "inspection_port_radius": int(parameters["inspection_port_radius"]),
            "decoy_port_count": int(parameters["decoy_port_count"]),
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("occlusion-shell-v2 difficulty parameters must be numeric") from exc
    if (
        not profile["shell_count_values"]
        or any(not 3 <= value <= 6 for value in profile["shell_count_values"])
        or not 1 <= profile["round_count"] <= 5
        or not profile["transfer_round_count_values"]
        or any(not 0 <= value <= profile["round_count"] for value in profile["transfer_round_count_values"])
        or not 42 <= profile["frame_count_min"] <= profile["frame_count_max"] <= 90
        or not 80 <= profile["tick_ms"] <= 180
        or not 500 <= profile["preview_ms"] <= 1600
        or not 2 <= profile["handoff_window_ticks"] <= 5
        or not 2 <= profile["inspection_minimum_samples"] <= profile["handoff_window_ticks"] * 2 + 1
        or not 28 <= profile["inspection_port_radius"] <= 70
        or not 0 <= profile["decoy_port_count"] <= 3
    ):
        raise ValueError("occlusion-shell-v2 difficulty profile is outside supported limits")
    return profile, copy.deepcopy(condition)


def _seed_int(seed: str, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _smoothstep(value: float) -> float:
    return value * value * (3 - 2 * value)


def _interpolate(first: tuple[float, float], second: tuple[float, float], amount: float) -> tuple[float, float]:
    eased = _smoothstep(amount)
    return first[0] + (second[0] - first[0]) * eased, first[1] + (second[1] - first[1]) * eased


def _circle_inside(point: list[int], rect: dict[str, int], radius: int = SHELL_RADIUS) -> bool:
    return (
        point[0] - radius >= rect["x"]
        and point[0] + radius <= rect["x"] + rect["width"]
        and point[1] - radius >= rect["y"]
        and point[1] + radius <= rect["y"] + rect["height"]
    )


def generate(task: dict[str, Any], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed_int(seed, SEED_SALT))
    profile, condition = _profile(task)
    shell_count = rng.choice(profile["shell_count_values"])
    shell_ids = [f"shell-{chr(65 + index)}" for index in range(shell_count)]
    round_count = profile["round_count"]
    transfer_rounds = set(rng.sample(range(round_count), rng.choice(profile["transfer_round_count_values"])))
    rounds_public: list[dict[str, Any]] = []
    rounds_truth: list[dict[str, Any]] = []

    for round_index in range(round_count):
        frame_count = rng.randint(profile["frame_count_min"], profile["frame_count_max"])
        start_x = [round(105 + index * 790 / (shell_count - 1)) for index in range(shell_count)]
        endpoint_order = list(range(shell_count))
        while endpoint_order == list(range(shell_count)) or sum(a != b for a, b in zip(endpoint_order, range(shell_count))) < 3:
            rng.shuffle(endpoint_order)
        end_x_by_shell = {shell_ids[shell_index]: start_x[endpoint_order[shell_index]] for shell_index in range(shell_count)}
        initial_carrier = rng.choice(shell_ids)
        inspection_partner = rng.choice([shell_id for shell_id in shell_ids if shell_id != initial_carrier])
        transfers = round_index in transfer_rounds

        lane_order = list(range(shell_count))
        rng.shuffle(lane_order)
        midpoints: dict[str, tuple[float, float]] = {}
        for shell_index, shell_id in enumerate(shell_ids):
            lane = lane_order[shell_index]
            midpoints[shell_id] = (
                330 + lane * 340 / max(1, shell_count - 1),
                112 + ((lane + round_index) % 3) * 56 + rng.randint(-10, 10),
            )
        center_x = rng.randint(430, 570)
        center_y = rng.randint(142, 214)
        midpoints[initial_carrier] = (center_x - 34, center_y)
        midpoints[inspection_partner] = (center_x + 34, center_y + rng.randint(-5, 5))
        wobble_signs = {shell_id: rng.choice((-1, 1)) for shell_id in shell_ids}

        frames: list[dict[str, Any]] = []
        for tick in range(1, frame_count + 1):
            t = tick / frame_count
            shells = []
            for shell_index, shell_id in enumerate(shell_ids):
                start = (start_x[shell_index], 338.0)
                midpoint = midpoints[shell_id]
                end = (end_x_by_shell[shell_id], 338.0)
                if t <= 0.5:
                    x, y = _interpolate(start, midpoint, t * 2)
                else:
                    x, y = _interpolate(midpoint, end, (t - 0.5) * 2)
                y += math.sin(math.pi * t) * wobble_signs[shell_id] * (5 + shell_index % 3)
                shells.append({
                    "id": shell_id,
                    "x": round(x),
                    "y": round(y),
                    "angle": round(math.sin(t * math.pi * 4 + shell_index) * 8),
                })
            frames.append({"tick": tick, "shells": shells})

        handoff = None
        occluders: list[dict[str, Any]] = []
        handoff_tick = frame_count // 2
        window_start = handoff_tick - profile["handoff_window_ticks"]
        window_end = handoff_tick + profile["handoff_window_ticks"]
        hidden_points = []
        for tick in range(window_start, window_end + 1):
            frame_shells = {item["id"]: item for item in frames[tick - 1]["shells"]}
            hidden_points.extend([
                [frame_shells[initial_carrier]["x"], frame_shells[initial_carrier]["y"]],
                [frame_shells[inspection_partner]["x"], frame_shells[inspection_partner]["y"]],
            ])
        min_x = min(point[0] for point in hidden_points) - SHELL_RADIUS - 9
        max_x = max(point[0] for point in hidden_points) + SHELL_RADIUS + 9
        min_y = min(point[1] for point in hidden_points) - SHELL_RADIUS - 9
        max_y = max(point[1] for point in hidden_points) + SHELL_RADIUS + 9
        rect = {
            "id": f"curtain-{round_index + 1}-handoff",
            "x": max(18, min_x),
            "y": max(48, min_y),
            "width": min(STAGE_WIDTH - 36, max_x) - max(18, min_x),
            "height": min(292, max_y) - max(48, min_y),
            "style": rng.choice(("velvet", "mirror", "ledger")),
        }
        occluders.append(rect)
        actual_target = inspection_partner if transfers else initial_carrier
        handoff = {
            "tick": handoff_tick,
            "window_start": window_start,
            "window_end": window_end,
            "from_shell": initial_carrier,
            "partner_shell": inspection_partner,
            "to_shell": actual_target,
            "transfers": transfers,
            "occluder_id": rect["id"],
        }
        assert all(_circle_inside(point, rect) for point in hidden_points)

        def add_decoy(index: int) -> dict[str, Any]:
            cover_tick = round(frame_count * rng.choice((0.31, 0.67)))
            cover_shell = rng.choice(shell_ids)
            cover_position = next(item for item in frames[cover_tick - 1]["shells"] if item["id"] == cover_shell)
            cover_width, cover_height = rng.randint(116, 148), rng.randint(90, 116)
            cover = {
                "id": (
                    f"curtain-{round_index + 1}-decoy"
                    if index == 1
                    else f"curtain-{round_index + 1}-decoy-{index}"
                ),
                "x": max(22, min(STAGE_WIDTH - cover_width - 22, cover_position["x"] - cover_width // 2)),
                "y": max(50, min(278 - cover_height, cover_position["y"] - cover_height // 2)),
                "width": cover_width,
                "height": cover_height,
                "style": rng.choice(("velvet", "mirror", "ledger")),
            }
            occluders.append(cover)
            return cover

        # This first decoy is part of the historical generator and remains in
        # the same place for a fixed uncontrolled/L2 seed.
        add_decoy(1)
        while len(occluders) - 1 < profile["decoy_port_count"]:
            add_decoy(len(occluders))

        final_carrier = actual_target
        inspection = {
            "occluder_id": rect["id"],
            "window_start": window_start,
            "window_end": window_end,
            "port": [round(rect["x"] + rect["width"] / 2), round(rect["y"] + min(24, rect["height"] / 3))],
            "radius": profile["inspection_port_radius"],
            "from_shell": initial_carrier,
            "partner_shell": inspection_partner,
            "to_shell": actual_target,
            "minimum_samples": profile["inspection_minimum_samples"],
        }
        decoy_ports = [
            {
                "occluder_id": item["id"],
                "port": [round(item["x"] + item["width"] / 2), round(item["y"] + min(24, item["height"] / 3))],
                "radius": profile["inspection_port_radius"],
            }
            for item in occluders[1:1 + profile["decoy_port_count"]]
        ]
        public_round = {
            "index": round_index,
            "label": f"TRACKING ROUND {round_index + 1} / {round_count}",
            "preview_ms": profile["preview_ms"],
            "tick_ms": profile["tick_ms"],
            "frame_count": frame_count,
            "duration_ms": frame_count * profile["tick_ms"],
            "shell_ids": shell_ids,
            "initial_carrier": initial_carrier,
            "start_positions": [{"id": shell_ids[index], "x": start_x[index], "y": 338} for index in range(shell_count)],
            "frames": frames,
            "occluders": occluders,
            "inspection": inspection,
        }
        if decoy_ports:
            public_round["decoy_ports"] = decoy_ports
        rounds_public.append(public_round)
        rounds_truth.append({
            **public_round,
            "handoff": handoff,
            "final_carrier": final_carrier,
        })

    task_id = str(task.get("id") or "occlusion_shell_swindle_nonrealtime_seed_0001@0.1")
    challenge_salt = (
        SEED_SALT
        if condition is None or int(condition["difficulty"]) == 2
        else f"{SEED_SALT}|d{condition['difficulty']}"
    )
    challenge_id = hashlib.sha256(f"{seed}|{challenge_salt}".encode("utf-8")).hexdigest()[:12]
    submit_label = "CERTIFY THREE TRACKS"
    if condition is not None and round_count != 3:
        submit_label = "CERTIFY ONE TRACK" if round_count == 1 else f"CERTIFY {round_count} TRACKS"
    public_state = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "prompt": task.get("natural_language") or "Track the marked token. When paired shells enter a cover, hold the cursor over its peephole and read the physical shuttle.",
        "submit_label": submit_label,
        "asset_manifest": "shared_runtime/assets/provenance/incubator_full_build_v1.json",
        "generator": {"name": "observable_inspection_port_shells_v2", "variant_count": 7_900_000_000},
        "stage": {"width": STAGE_WIDTH, "height": STAGE_HEIGHT},
        "shell_radius": SHELL_RADIUS,
        "rounds": rounds_public,
    }
    ground_truth = {
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "seed": seed,
        "challenge_id": challenge_id,
        "stage": public_state["stage"],
        "shell_radius": SHELL_RADIUS,
        "rounds": rounds_truth,
        "transfer_rounds": sorted(transfer_rounds),
        "variant_count": public_state["generator"]["variant_count"],
    }
    if condition is not None:
        public_state["control_condition"] = copy.deepcopy(condition)
        ground_truth["control_condition"] = copy.deepcopy(condition)
    assert len(rounds_public) == round_count
    return public_state, ground_truth
