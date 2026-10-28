from __future__ import annotations

import copy
import hashlib
import math
import random
from collections import deque
from typing import Any


ASSET_MANIFEST = "shared_runtime/assets/provenance/interaction_vii_viii_v0.json"


def _seed(seed: str, mechanic: str) -> int:
    return int(hashlib.sha256(f"{seed}|{mechanic}".encode()).hexdigest()[:16], 16)


def _identity(mechanic: str, task: dict[str, Any], seed: str) -> tuple[random.Random, dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed(seed, mechanic))
    task_id = str(task.get("id") or f"{mechanic}_seed_0001@0.1")
    challenge_id = hashlib.sha256(f"{seed}|{mechanic}".encode()).hexdigest()[:12]
    public = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": mechanic,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "asset_manifest": ASSET_MANIFEST,
        "prompt": task.get("natural_language") or "Complete the physical verification.",
    }
    truth = {
        "mechanic_id": mechanic,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "seed": seed,
    }
    return rng, public, truth


def _angle(value: float) -> float:
    return (value % 180.0 + 180.0) % 180.0


def _mirror_angle(previous: tuple[float, float], center: tuple[float, float], following: tuple[float, float]) -> float:
    incoming = math.atan2(center[1] - previous[1], center[0] - previous[0])
    outgoing = math.atan2(following[1] - center[1], following[0] - center[0])
    normal = (incoming + outgoing) / 2.0 + math.pi / 2.0
    return round(_angle(math.degrees(normal) + 90.0), 2)


def _specular(task: dict[str, Any], seed: str):
    mechanic = "specular_lighthouse_relay"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(f"{seed}|{mechanic}|d{condition['difficulty']}|{task.get('id')}".encode()).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id
    round_count = int(parameters.get("round_count", 4))
    mirror_count = int(parameters.get("mirror_count", 3))
    if not 1 <= round_count <= 5 or not 1 <= mirror_count <= 4:
        raise ValueError("specular relay counts are outside supported limits")
    mirror_x = {1: (455.0,), 2: (330.0, 600.0), 3: (250.0, 455.0, 660.0), 4: (205.0, 375.0, 545.0, 715.0)}[mirror_count]
    mirror_y_ranges = ((80, 190), (265, 395), (85, 225), (260, 390))
    amplitudes = tuple(parameters.get("receiver_amplitudes") or (38, 42, 46))
    angular_rates = tuple(parameters.get("receiver_angular_rates") or (0.044, 0.048, 0.052))
    initial_offsets = tuple(parameters.get("initial_angle_offsets") or (-58, -42, 37, 53))
    rounds = []
    solutions = []
    for index in range(round_count):
        emitter = (70.0, float(rng.randint(150, 330)))
        mirrors = [(x, float(rng.randint(*mirror_y_ranges[n]))) for n, x in enumerate(mirror_x)]
        receiver = (845.0, float(rng.randint(165, 335)))
        points = [emitter, *mirrors, receiver]
        angles = [_mirror_angle(points[i], points[i + 1], points[i + 2]) for i in range(mirror_count)]
        initial = [round(_angle(value + rng.choice(initial_offsets)), 2) for value in angles]
        round_id = f"lamp-{index + 1}-{hashlib.sha1(f'{seed}|lamp|{index}'.encode()).hexdigest()[:5]}"
        rounds.append({
            "id": round_id,
            "emitter": list(emitter),
            "mirrors": [{"id": f"m{n + 1}", "center": list(center), "length": int(parameters.get("mirror_length", 118)), "angle_deg": initial[n]} for n, center in enumerate(mirrors)],
            "receiver": {
                "center": list(receiver),
                "radius": int(parameters.get("receiver_radius", 23)),
                "motion_axis": "y",
                "amplitude": rng.choice(amplitudes),
                "angular_rate": rng.choice(angular_rates),
                "phase": round(rng.random() * math.tau, 5),
            },
            "angle_step_deg": int(parameters.get("angle_step_deg", 1)),
            "tolerance_px": int(parameters.get("tolerance_px", 15)),
            "required_charge_ticks": int(parameters.get("required_charge_ticks", 52)),
            "miss_decay_ticks": int(parameters.get("miss_decay_ticks", 2)),
        })
        solutions.append({"round_id": round_id, "angles": angles})
    public.update({
        "generator": {"name": "live_tracking_specular_relay_v2", "variant_count": 10**12},
        "rounds": rounds,
        "round_count": len(rounds),
        "palette": rng.choice(("storm-lantern", "salt-glass", "signal-oxide")),
    })
    truth.update({"rounds": rounds, "solutions": solutions, "angle_tolerance_deg": float(parameters.get("angle_tolerance_deg", 3.25))})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth


def _wind_sim(
    plan: list[dict[str, int]],
    ticks: int,
    phase: float,
    pods: list[dict[str, Any]],
    physics: dict[str, Any],
    fan_x: tuple[float, ...],
) -> dict[str, list[tuple[float, float, int]]]:
    """Author two routes with the same shared spooling/thermal plant used by the UI."""
    commands = [0 for _ in fan_x]
    actual = [0.0 for _ in fan_x]
    heat = [0.0 for _ in fan_x]
    events: dict[int, list[dict[str, int]]] = {}
    for item in plan:
        events.setdefault(int(item["tick"]), []).append(item)
    bodies = {item["id"]: {key: float(item[key]) for key in ("x", "y", "vx", "vy")} for item in pods}
    samples: dict[str, list[tuple[float, float, int]]] = {item["id"]: [] for item in pods}
    for tick in range(ticks):
        for item in events.get(tick, []):
            commands[int(item["fan"])] = int(item["power"])
        accelerations = {item["id"]: 0.006 * math.sin(tick * 0.083 + phase + float(item["gust_phase"])) for item in pods}
        for index, center in enumerate(fan_x):
            heat[index] = max(0.0, heat[index] + (float(physics["heat_rate"]) if commands[index] else -float(physics["cool_rate"])))
            if heat[index] >= float(physics["trip_heat"]):
                raise RuntimeError("authored wind plan overheated")
            actual[index] += (commands[index] - actual[index]) * float(physics["spool_rate"])
            for item in pods:
                body = bodies[item["id"]]
                influence = max(0.0, 1.0 - abs(body["x"] - center) / 112.0)
                accelerations[item["id"]] += actual[index] * float(physics["fan_accel"]) * float(item["response"]) * influence
        for item in pods:
            body = bodies[item["id"]]
            body["vy"] = (body["vy"] + accelerations[item["id"]]) * float(physics["drag"])
            body["y"] = max(35.0, min(441.0, body["y"] + body["vy"]))
            body["x"] += body["vx"]
            samples[item["id"]].append((body["x"], body["y"], tick + 1))
    return samples


def _wind(task: dict[str, Any], seed: str):
    mechanic = "wind_tunnel_seed_courier"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{mechanic}|d{condition['difficulty']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id
    phase = round(rng.random() * math.tau, 5)
    all_fan_x = (205, 365, 525, 685)
    fan_count = int(parameters.get("fan_count", 4))
    gate_count = int(parameters.get("gate_count", 4))
    pod_count = int(parameters.get("pod_count", 2))
    if not 2 <= fan_count <= 4 or not 2 <= gate_count <= 5 or not 1 <= pod_count <= 2:
        raise ValueError("wind courier profile is outside supported pod, fan, or gate counts")
    raw_fan_x = parameters.get("fan_x")
    fan_x = tuple(float(value) for value in raw_fan_x) if raw_fan_x is not None else all_fan_x[:fan_count]
    if len(fan_x) != fan_count:
        raise ValueError("wind courier fan count does not match its physical fan wall")
    default_gate_x = (285, 445, 605, 765)
    raw_gate_x = parameters.get("gate_x")
    if raw_gate_x is None:
        gate_x = default_gate_x[:gate_count]
    else:
        gate_x = tuple(float(value) for value in raw_gate_x)
    if len(gate_x) != gate_count:
        raise ValueError("wind courier gate count does not match its air corridor")
    all_pods = [
        {"id": "thistle", "x": 76.0, "y": 166.0, "vx": 2.48, "vy": 0.0, "response": 1.0, "gust_phase": 0.0, "color": "#f4c84d"},
        {"id": "acorn", "x": -142.0, "y": 314.0, "vx": 2.18, "vy": 0.0, "response": 0.72, "gust_phase": 1.7, "color": "#a85b39"},
    ]
    pods = copy.deepcopy(all_pods[:pod_count])
    physics = {
        "tick_ms": int(parameters.get("tick_ms", 38)), "ticks": int(parameters.get("ticks", 466)), "phase": phase,
        "fan_accel": float(parameters.get("fan_accel", 0.030)), "drag": float(parameters.get("drag", 0.968)), "pod_radius": int(parameters.get("pod_radius", 11)),
        "spool_rate": float(parameters.get("spool_rate", 0.15)), "heat_rate": float(parameters.get("heat_rate", 0.006)), "cool_rate": float(parameters.get("cool_rate", 0.014)),
        "trip_heat": float(parameters.get("trip_heat", 1.0)),
    }
    amplitudes = tuple(int(value) for value in (parameters.get("gate_amplitudes") or (14, 17, 20)))
    angular_rates = tuple(float(value) for value in (parameters.get("gate_angular_rates") or (0.061, 0.073, 0.087)))
    half_gap = int(parameters.get("gate_half_gap", 31))
    if not amplitudes or not angular_rates or half_gap <= int(physics["pod_radius"]):
        raise ValueError("wind courier gate profile is invalid")
    plan: list[dict[str, int]] = []
    for pod in pods:
        for index, center in enumerate(fan_x):
            power = rng.choice((-1, 1))
            on_tick = max(0, round((center - 90 - float(pod["x"])) / float(pod["vx"])))
            off_tick = round((center + 76 - float(pod["x"])) / float(pod["vx"]))
            plan.extend((
                {"tick": on_tick, "fan": index, "power": power},
                {"tick": off_tick, "fan": index, "power": 0},
            ))
    plan.sort(key=lambda item: (item["tick"], item["fan"]))
    samples = _wind_sim(plan, int(physics["ticks"]), phase, pods, physics, fan_x)
    gates = []
    for index, gx in enumerate(gate_x):
        slots = []
        for pod in pods:
            sample = min(samples[pod["id"]], key=lambda item: abs(item[0] - gx))
            amplitude = rng.choice(amplitudes)
            angular_rate = rng.choice(angular_rates)
            gate_phase = round(rng.random() * math.tau, 5)
            base_y = sample[1] - amplitude * math.sin(sample[2] * angular_rate + gate_phase)
            slots.append({
                "pod_id": pod["id"], "base_y": round(base_y, 3),
                "amplitude": amplitude, "angular_rate": angular_rate,
                "phase": gate_phase, "half_gap": half_gap,
            })
        gates.append({
            "id": f"gate-{index + 1}", "x": gx, "slots": slots,
        })
    dock_x = parameters.get("dock_x", 855 if gate_count == 4 else gate_x[-1] + 90.0)
    dock_radius = int(parameters.get("dock_radius", 32))
    docks = []
    for pod in pods:
        sample = min(samples[pod["id"]], key=lambda item: abs(item[0] - dock_x))
        docks.append({"pod_id": pod["id"], "x": dock_x, "y": round(sample[1], 2), "radius": dock_radius})
    public.update({
        "generator": {"name": "dual_pod_shared_wind_field_v3", "variant_count": 2**8 * 10**10},
        "canvas": {"width": 900, "height": 480},
        "fans": [{"id": f"fan-{i + 1}", "x": x, "radius": 112} for i, x in enumerate(fan_x)],
        "gates": gates,
        "pods": pods,
        "physics": physics,
        "docks": docks,
    })
    truth.update({"plan": plan, "gates": gates, "physics": physics, "docks": docks})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth


def _rod_cells(item: dict[str, Any]) -> set[tuple[int, int, int]]:
    center = [int(value) for value in item["center"]]
    axis = "xyz".index(str(item["axis"]))
    cells = set()
    for offset in (-1, 0, 1):
        point = center.copy()
        point[axis] += offset
        cells.add(tuple(point))
    return cells


def _masks(objects: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Return the frontmost colored cell for every orthographic ray."""
    views = {
        "front": (lambda cell: (cell[0], cell[2]), lambda cell: cell[1]),
        "side": (lambda cell: (cell[1], cell[2]), lambda cell: cell[0]),
        "top": (lambda cell: (cell[0], cell[1]), lambda cell: cell[2]),
    }
    result: dict[str, list[str]] = {}
    for view, (project, depth) in views.items():
        nearest: dict[tuple[int, int], tuple[int, str]] = {}
        for item in objects:
            for cell in _rod_cells(item):
                key = project(cell)
                candidate = (depth(cell), str(item["color"]))
                if key not in nearest or candidate[0] < nearest[key][0]:
                    nearest[key] = candidate
        result[view] = sorted(f"{u}:{v}:{color}" for (u, v), (_depth, color) in nearest.items())
    return result


def _hologram(task: dict[str, Any], seed: str):
    mechanic = "hologram_silhouette_foundry"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{mechanic}|d{condition['difficulty']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id
    rod_count = int(parameters.get("rod_count", 6))
    grid_size = int(parameters.get("grid_size", 7))
    min_occluded = int(parameters.get("min_occluded_rays_per_view", 2))
    max_occluded_raw = parameters.get("max_occluded_rays_per_view")
    max_occluded = None if max_occluded_raw is None else int(max_occluded_raw)
    if not 3 <= rod_count <= 7 or not 5 <= grid_size <= 8 or min_occluded < 0:
        raise ValueError("hologram foundry profile is outside supported limits")
    if max_occluded is not None and max_occluded < min_occluded:
        raise ValueError("hologram foundry occlusion range is invalid")
    palette = (
        "#ff6d4a", "#5bd8c8", "#f6c85f", "#a983ff", "#62a7ff", "#ef7fc4", "#72e2ad",
    )[:rod_count]
    solutions: list[dict[str, Any]] = []
    attempt_limit = 500 if (rod_count, grid_size, min_occluded, max_occluded) == (6, 7, 2, None) else 2400
    for _attempt in range(attempt_limit):
        candidate: list[dict[str, Any]] = []
        occupied: set[tuple[int, int, int]] = set()
        for index, color in enumerate(palette):
            for _ in range(160):
                axis = rng.choice("xyz")
                center = [rng.randint(1, grid_size - 2), rng.randint(1, grid_size - 2), rng.randint(1, grid_size - 2)]
                item = {"id": f"rod-{index + 1}", "center": center, "axis": axis, "color": color}
                cells = _rod_cells(item)
                if not cells & occupied and all(0 <= value < grid_size for cell in cells for value in cell):
                    occupied |= cells
                    candidate.append(item)
                    break
            else:
                break
        if len(candidate) != rod_count:
            continue
        masks = _masks(candidate)
        occluded = {view: rod_count * 3 - len(masks[view]) for view in ("front", "side", "top")}
        if all(value >= min_occluded for value in occluded.values()) and (
            max_occluded is None or all(value <= max_occluded for value in occluded.values())
        ):
            solutions = candidate
            break
    if not solutions:
        raise RuntimeError("could not generate a foundry casting for the selected profile")
    if rod_count == 6 and grid_size == 7:
        # The original six-rod task used this exact rack. Keep it byte-for-byte
        # equivalent for the controlled baseline.
        rack = ([1, 1, 1], [3, 1, 1], [5, 1, 1], [1, 5, 5], [3, 5, 5], [5, 5, 5])
    else:
        limit = grid_size - 2
        positions = [(x, y) for y in range(1, limit + 1) for x in range(1, limit + 1)]
        rack = [[x, y, 1 if index % 2 == 0 else limit] for index, (x, y) in enumerate(positions[:rod_count])]
    initial = [{**item, "center": list(rack[index]), "axis": "z"} for index, item in enumerate(solutions)]
    public.update({
        "generator": {"name": "occluding_color_inverse_foundry_v2", "variant_count": 10**14},
        "grid_size": grid_size,
        "objects": initial,
        "target_masks": _masks(solutions),
        "views": ("front", "side", "top"),
    })
    truth.update({"solution_objects": solutions, "target_masks": public["target_masks"]})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth


def _orbital(task: dict[str, Any], seed: str):
    mechanic = "orbital_docking_customs"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    lane_y = 240.0
    thrusts = 6
    acceleration = 0.20
    velocity = thrusts * acceleration
    routes = {
        "single_beacon": {
            "station_y": lane_y - 60.0,
            "debris": [{"id": "debris-a", "x": 265.0, "y": lane_y, "radius": 39}],
            "beacons": [{"id": "scan-a", "x": 187.0, "y": lane_y - 60.0, "radius": 27}],
            "plan": [
                {"action": "thrust", "count": thrusts},
                {"action": "strafe-up", "count": 5},
                {"action": "coast", "ticks": 60},
                {"action": "strafe-down", "count": 5},
                {"action": "coast", "ticks": 300},
                {"action": "retro", "count": thrusts},
            ],
        },
        "double_s": {
            "station_y": lane_y + 60.0,
            "debris": [
                {"id": "debris-a", "x": 265.0, "y": lane_y, "radius": 39},
                {"id": "debris-b", "x": 505.0, "y": lane_y, "radius": 39},
            ],
            "beacons": [
                {"id": "scan-a", "x": 187.0, "y": lane_y - 60.0, "radius": 27},
                {"id": "scan-b", "x": 403.0, "y": lane_y + 60.0, "radius": 27},
            ],
            "plan": [
                {"action": "thrust", "count": thrusts},
                {"action": "strafe-up", "count": 5},
                {"action": "coast", "ticks": 60},
                {"action": "strafe-down", "count": 5},
                {"action": "coast", "ticks": 120},
                {"action": "strafe-down", "count": 10},
                {"action": "coast", "ticks": 60},
                {"action": "strafe-up", "count": 10},
                {"action": "coast", "ticks": 360},
                {"action": "retro", "count": thrusts},
            ],
        },
        "triple_s": {
            "station_y": lane_y - 60.0,
            "debris": [
                {"id": "debris-a", "x": 265.0, "y": lane_y, "radius": 39},
                {"id": "debris-b", "x": 505.0, "y": lane_y, "radius": 39},
                {"id": "debris-c", "x": 715.0, "y": lane_y, "radius": 39},
            ],
            "beacons": [
                {"id": "scan-a", "x": 187.0, "y": lane_y - 60.0, "radius": 27},
                {"id": "scan-b", "x": 403.0, "y": lane_y + 60.0, "radius": 27},
                {"id": "scan-c", "x": 619.0, "y": lane_y - 60.0, "radius": 27},
            ],
            "plan": [
                {"action": "thrust", "count": thrusts},
                {"action": "strafe-up", "count": 5},
                {"action": "coast", "ticks": 60},
                {"action": "strafe-down", "count": 5},
                {"action": "coast", "ticks": 120},
                {"action": "strafe-down", "count": 10},
                {"action": "coast", "ticks": 60},
                {"action": "strafe-up", "count": 10},
                {"action": "strafe-up", "count": 10},
                {"action": "coast", "ticks": 60},
                {"action": "strafe-down", "count": 10},
                {"action": "coast", "ticks": 120},
                {"action": "coast", "ticks": 180},
                {"action": "retro", "count": thrusts},
            ],
        },
    }
    if condition is None:
        # Keep the historical generated world byte-for-byte intact. The
        # controlled L4 branch below uses the same route and random draws.
        parameters = {
            "route_profile": "double_s",
            "debris_count": 2,
            "beacon_count": 2,
            "station_angle_mode": "random_15",
            "station_y_amplitude_options": [20.0, 24.0, 28.0],
            "station_y_rate_options": [0.016, 0.018, 0.020],
            "station_port_rate_options": [-1.5, 1.5],
            "dock_distance": 22,
            "dock_speed": 0.12,
            "angle_tolerance_deg": 8,
            "fuel": 64,
            "max_ticks": 760,
        }
    route_name = str(parameters.get("route_profile") or "")
    route = routes.get(route_name)
    if route is None:
        raise ValueError("orbital docking route profile is invalid")
    if int(parameters.get("debris_count", -1)) != len(route["debris"]) or int(parameters.get("beacon_count", -1)) != len(route["beacons"]):
        raise ValueError("orbital docking route does not match its debris or beacon profile")
    angle_mode = str(parameters.get("station_angle_mode") or "")
    if angle_mode == "random_15":
        station_angle = rng.randrange(0, 360, 15)
    elif angle_mode == "fixed_zero":
        station_angle = 0.0
    else:
        raise ValueError("orbital docking station angle mode is invalid")
    port_rates = tuple(float(value) for value in parameters.get("station_port_rate_options") or ())
    amplitudes = tuple(float(value) for value in parameters.get("station_y_amplitude_options") or ())
    motion_rates = tuple(float(value) for value in parameters.get("station_y_rate_options") or ())
    if not port_rates or not amplitudes or not motion_rates or any(value < 0 for value in amplitudes) or any(value < 0 for value in motion_rates):
        raise ValueError("orbital docking station motion profile is invalid")
    port_rate = rng.choice(port_rates)
    total_coast_ticks = sum(int(item["ticks"]) for item in route["plan"] if item["action"] == "coast")
    station_amplitude = rng.choice(amplitudes)
    station_motion_rate = rng.choice(motion_rates)
    station_phase = round(math.pi / 2 - total_coast_ticks * station_motion_rate, 6)
    final_port_angle = (station_angle + total_coast_ticks * port_rate) % 360
    plan = [*route["plan"], {"action": "rotate", "target_deg": final_port_angle}, {"action": "dock"}]
    station_x = 115.0 + round(velocity * total_coast_ticks, 3)
    dock_distance = float(parameters.get("dock_distance"))
    dock_speed = float(parameters.get("dock_speed"))
    angle_tolerance = float(parameters.get("angle_tolerance_deg"))
    fuel = int(parameters.get("fuel"))
    max_ticks = int(parameters.get("max_ticks"))
    if not 1 <= fuel <= 96 or not total_coast_ticks < max_ticks <= 900 or not 8 <= dock_distance <= 40 or not .04 <= dock_speed <= .30 or not 3 <= angle_tolerance <= 25:
        raise ValueError("orbital docking physical profile is outside supported limits")
    public.update({
        "generator": {"name": "scanned_s_rendezvous_v3", "variant_count": 10**11},
        "canvas": {"width": 900, "height": 480},
        "ship": {"x": 115.0, "y": lane_y, "vx": 0.0, "vy": 0.0, "angle_deg": 0.0, "radius": 16},
        "station": {
            "x": station_x, "base_y": float(route["station_y"]) - station_amplitude,
            "y_amplitude": station_amplitude, "y_rate": station_motion_rate,
            "y_phase": station_phase, "angle_deg": station_angle,
            "rotation_deg_per_tick": port_rate, "port_radius": 26,
        },
        "physics": {
            "impulse": acceleration, "rotation_step_deg": 15,
            "coast_step_ticks": 10, "coast_long_ticks": 30,
            "fuel": fuel, "dock_speed": dock_speed, "dock_distance": dock_distance,
            "angle_tolerance_deg": angle_tolerance, "max_ticks": max_ticks,
        },
        "debris": route["debris"],
        "beacons": route["beacons"],
    })
    truth.update({"reference_plan": plan, "station": public["station"], "physics": public["physics"]})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{mechanic}|d{condition['difficulty']}|{condition['interaction']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth


def _slide(board: dict[str, Any], position: tuple[int, int], direction: int, collected: int) -> tuple[tuple[int, int], int]:
    vectors = ((1, 0), (0, 1), (-1, 0), (0, -1))
    dx, dy = vectors[direction % 4]
    walls = {tuple(item) for item in board["walls"]}
    gates = [tuple(item) for item in board["gates"]]
    x, y = position
    while (x + dx, y + dy) not in walls:
        x += dx
        y += dy
        if collected < len(gates) and (x, y) == gates[collected]:
            collected += 1
    return (x, y), collected


def _gravity_board(
    rng: random.Random,
    *,
    size: int = 8,
    wall_probability: float = 0.21,
    gate_count: int = 4,
    min_solution_length: int = 14,
    max_solution_length: int = 30,
) -> tuple[dict[str, Any], list[str]]:
    if (
        not 6 <= size <= 9
        or not 0.08 <= wall_probability <= 0.30
        or not 2 <= gate_count <= 5
        or not 0 <= min_solution_length <= max_solution_length <= 48
    ):
        raise ValueError("gravity room difficulty profile is outside supported limits")
    perimeter = {(x, 0) for x in range(size)} | {(x, size - 1) for x in range(size)} | {(0, y) for y in range(size)} | {(size - 1, y) for y in range(size)}
    for _ in range(2400):
        walls = set(perimeter)
        for y in range(1, size - 1):
            for x in range(1, size - 1):
                if rng.random() < wall_probability:
                    walls.add((x, y))
        free = [(x, y) for y in range(1, size - 1) for x in range(1, size - 1) if (x, y) not in walls]
        minimum_free = max(12 if size == 6 else 18, gate_count + 4)
        if len(free) < minimum_free:
            continue
        cargo_start, counter_start, *rest = rng.sample(free, gate_count + 4)
        gates, cargo_target, counter_target = rest[:gate_count], rest[gate_count], rest[gate_count + 1]
        board = {
            "size": size, "walls": [list(p) for p in sorted(walls)],
            "cargo_start": list(cargo_start), "counter_start": list(counter_start),
            "gates": [list(p) for p in gates],
            "cargo_target": list(cargo_target), "counter_target": list(counter_target),
            "counter_layer": "isolated-under-deck-rail",
        }
        queue = deque([(cargo_start, counter_start, 0, 0, [])])
        seen = {(cargo_start, counter_start, 0, 0)}
        while queue:
            cargo, counter, orientation, collected, path = queue.popleft()
            if cargo == cargo_target and counter == counter_target and collected == gate_count and min_solution_length <= len(path) <= max_solution_length:
                return board, path
            if len(path) >= max_solution_length:
                continue
            for label, delta in (("cw", 1), ("ccw", -1)):
                new_orientation = (orientation + delta) % 4
                next_cargo, next_collected = _slide(board, cargo, new_orientation, collected)
                next_counter, _ = _slide(board, counter, new_orientation, 0)
                state = (next_cargo, next_counter, new_orientation, next_collected)
                if state not in seen:
                    seen.add(state)
                    queue.append((next_cargo, next_counter, new_orientation, next_collected, [*path, label]))
    raise RuntimeError("could not generate gravity room")


def _gravity(task: dict[str, Any], seed: str):
    mechanic = "gravity_room_freight"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{mechanic}|d{condition['difficulty']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id
    board, solution = _gravity_board(
        rng,
        size=int(parameters.get("grid_size", 8)),
        wall_probability=float(parameters.get("wall_probability", 0.21)),
        gate_count=int(parameters.get("gate_count", 4)),
        min_solution_length=int(parameters.get("min_solution_length", 14)),
        max_solution_length=int(parameters.get("max_solution_length", 30)),
    )
    public.update({
        "generator": {"name": "dual_body_rotating_gravity_room_v2", "variant_count": 10**12},
        "board": board,
        "initial_orientation": 0,
        "rotation_ms": 620,
    })
    truth.update({"board": board, "solution": solution})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth


def _equalize_levels(
    start: tuple[int, ...],
    gate: int,
    circuits: list[tuple[int, int]],
    *,
    safe_min: int = 3,
    safe_max: int = 17,
    tolerance: int = 1,
    max_pumps: int = 14,
) -> tuple[tuple[int, ...], list[dict[str, int]]]:
    queue = deque([(start, [])])
    seen = {start}
    while queue:
        levels, path = queue.popleft()
        if abs(levels[gate] - levels[gate + 1]) <= tolerance:
            return levels, path
        if len(path) >= max_pumps:
            continue
        for circuit, (first, second) in enumerate(circuits):
            for source, destination, direction in ((first, second, 1), (second, first, -1)):
                if levels[source] <= safe_min or levels[destination] >= safe_max:
                    continue
                changed = list(levels)
                changed[source] -= 1
                changed[destination] += 1
                candidate = tuple(changed)
                if candidate not in seen:
                    seen.add(candidate)
                    queue.append((candidate, [*path, {"action": "pump", "circuit": circuit, "direction": direction}]))
    raise RuntimeError("could not equalize authored flood lock")


def _equalize_levels_greedy(
    start: tuple[int, ...],
    gate: int,
    circuits: list[tuple[int, int]],
    *,
    safe_min: int,
    safe_max: int,
    tolerance: int,
    max_pumps: int,
) -> tuple[tuple[int, ...], list[dict[str, int]]]:
    """Route conserved units along the visible manifold without exhaustive state search.

    The controlled profiles use this only outside the preserved L4 reference.
    A whole source-to-destination route leaves intermediate vault levels
    unchanged after each unit, so the same visible safety bounds used by the
    browser and replay are maintained at every primitive pump event.
    """
    adjacency: dict[int, list[tuple[int, int, int]]] = {}
    for index, (first, second) in enumerate(circuits):
        adjacency.setdefault(first, []).append((second, index, 1))
        adjacency.setdefault(second, []).append((first, index, -1))

    def route(source: int, destination: int) -> list[tuple[int, int, int]]:
        queue = deque([(source, [])])
        seen = {source}
        while queue:
            current, path = queue.popleft()
            if current == destination:
                return path
            for following, circuit, direction in adjacency.get(current, []):
                if following not in seen:
                    seen.add(following)
                    queue.append((following, [*path, (following, circuit, direction)]))
        raise RuntimeError("floodgate manifold does not connect a selected lock")

    levels = list(start)
    plan: list[dict[str, int]] = []
    while abs(levels[gate] - levels[gate + 1]) > tolerance:
        source, destination = (gate, gate + 1) if levels[gate] > levels[gate + 1] else (gate + 1, gate)
        path = route(source, destination)
        cursor = source
        for following, circuit, direction in path:
            if levels[cursor] <= safe_min or levels[following] >= safe_max:
                raise RuntimeError("visible floodgate safety bands prevent equalization")
            levels[cursor] -= 1
            levels[following] += 1
            plan.append({"action": "pump", "circuit": circuit, "direction": direction})
            cursor = following
            if len(plan) > max_pumps:
                raise RuntimeError("controlled floodgate lock exceeds its pump budget")
    return tuple(levels), plan


def _flood(task: dict[str, Any], seed: str):
    mechanic = "floodgate_archive_rescue"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{mechanic}|d{condition['difficulty']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id

    chamber_count = int(parameters.get("chamber_count", 5))
    raw_circuits = parameters.get("circuits", ((0, 2), (2, 4), (4, 1), (1, 3), (3, 0)))
    raw_crossing_order = parameters.get("crossing_order", (0, 3, 1, 2, 1, 3, 0))
    try:
        circuits = [tuple(int(value) for value in edge) for edge in raw_circuits]
        crossing_order = tuple(int(value) for value in raw_crossing_order)
    except (TypeError, ValueError) as exc:
        raise ValueError("floodgate circuit or lock profile is malformed") from exc
    level_min = int(parameters.get("level_min_units", 5))
    level_max = int(parameters.get("level_max_units", 15))
    safe_min = int(parameters.get("safe_min_units", 3))
    safe_max = int(parameters.get("safe_max_units", 17))
    unit_divisor = int(parameters.get("unit_divisor", 20))
    pump_step_units = int(parameters.get("pump_step_units", 1))
    equal_tolerance_units = int(parameters.get("equal_tolerance_units", 1))
    per_lock_pump_limit = int(parameters.get("per_lock_pump_limit", 14))
    pump_count_min = int(parameters.get("pump_count_min", 10))
    pump_count_max = int(parameters.get("pump_count_max", 30))
    equal_tolerance = float(
        parameters.get(
            "equal_tolerance",
            0.055 if condition is None else round((equal_tolerance_units + 0.1) / unit_divisor, 4),
        )
    )
    if (
        not 3 <= chamber_count <= 6
        or not circuits
        or any(len(edge) != 2 or min(edge) < 0 or max(edge) >= chamber_count or edge[0] == edge[1] for edge in circuits)
        or not crossing_order
        or any(gate < 0 or gate >= chamber_count - 1 for gate in crossing_order)
        or not 0 < safe_min < level_min <= level_max < safe_max
        or unit_divisor not in {20, 40}
        or pump_step_units != 1
        or not 0 <= equal_tolerance_units <= 2
        or not 1 <= per_lock_pump_limit <= 28
        or not 0 <= pump_count_min <= pump_count_max <= 48
        or equal_tolerance <= 0
    ):
        raise ValueError("floodgate difficulty profile is outside supported limits")

    for _ in range(240):
        integer_levels = tuple(rng.randint(level_min, level_max) for _ in range(chamber_count))
        cursor = integer_levels
        plan: list[dict[str, Any]] = []
        try:
            for gate in crossing_order:
                equalizer = _equalize_levels if condition is None or int(condition["difficulty"]) == 4 else _equalize_levels_greedy
                cursor, pumps = equalizer(
                    cursor,
                    gate,
                    circuits,
                    safe_min=safe_min,
                    safe_max=safe_max,
                    tolerance=equal_tolerance_units,
                    max_pumps=per_lock_pump_limit,
                )
                plan.extend(pumps)
                plan.extend((
                    {"action": "gate", "gate": gate, "open": True},
                    {"action": "transfer", "gate": gate},
                    {"action": "gate", "gate": gate, "open": False},
                ))
        except RuntimeError:
            continue
        pump_count = sum(item["action"] == "pump" for item in plan)
        if pump_count_min <= pump_count <= pump_count_max:
            break
    else:
        raise RuntimeError("could not author coupled opposing flood route")
    levels = [value / unit_divisor for value in integer_levels]
    level_precision = 3 if unit_divisor == 40 else 2
    public.update({
        "generator": {"name": "conserved_dual_capsule_lock_archive_v2", "variant_count": 10**10},
        "chambers": [{"id": f"vault-{i + 1}", "level": round(level, level_precision), "safe_min": safe_min / unit_divisor, "safe_max": safe_max / unit_divisor} for i, level in enumerate(levels)],
        "gates": [{"id": f"lock-{i + 1}", "between": [i, i + 1]} for i in range(chamber_count - 1)],
        "circuits": [{"id": f"circuit-{i + 1}", "between": list(edge)} for i, edge in enumerate(circuits)],
        "capsules": [
            {"id": "amber", "chamber": 0, "dock_chamber": chamber_count - 1, "direction": 1, "color": "#ffb13b"},
            {"id": "cyan", "chamber": chamber_count - 1, "dock_chamber": 0, "direction": -1, "color": "#55dbe8"},
        ],
        "pump_step": pump_step_units / unit_divisor,
        "equal_tolerance": equal_tolerance,
    })
    if unit_divisor == 40:
        public["level_precision"] = level_precision
    truth.update({"reference_plan": plan, "initial_levels": levels, "pump_step": public["pump_step"], "equal_tolerance": public["equal_tolerance"]})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth


def _membrane(task: dict[str, Any], seed: str):
    mechanic = "elastic_membrane_sorter"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{mechanic}|d{condition['difficulty']}|{condition['interaction']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id
    round_count = int(parameters.get("round_count", 3))
    checkpoints_per_round = int(parameters.get("checkpoints_per_round", 2))
    if not 1 <= round_count <= 3 or not 1 <= checkpoints_per_round <= 3:
        raise ValueError("elastic membrane profile is outside supported course limits")
    initial_height_low = float(parameters.get("initial_height_low", 0.42))
    initial_height_high = float(parameters.get("initial_height_high", 0.58))
    if not 0 <= initial_height_low <= initial_height_high <= 1:
        raise ValueError("elastic membrane post-height range is invalid")
    wells = ((125, 115), (775, 120), (450, 385))
    rounds = []
    courses = (
        [[355, 175], [235, 108], [155, 150]],
        [[545, 175], [665, 110], [745, 155]],
        [[365, 305], [515, 355], [455, 410]],
    )
    order = list(range(3))
    rng.shuffle(order)
    for index, target in enumerate(order[:round_count]):
        initial = [round(rng.uniform(initial_height_low, initial_height_high), 2) for _ in range(4)]
        rounds.append({
            "id": f"marble-{index + 1}", "target_well": target,
            "start": [450, 230], "post_heights": initial,
            "wells": [list(item) for item in wells],
            "checkpoints": courses[target][:checkpoints_per_round],
        })
    public.update({
        "generator": {"name": "live_steered_membrane_course_v2", "variant_count": 10**9},
        "canvas": {"width": 900, "height": 480},
        "rounds": rounds,
        "post_positions": [[70, 55], [830, 55], [70, 425], [830, 425]],
        "physics": {
            "tick_ms": 35,
            "slope_accel": float(parameters.get("slope_accel", 0.10)),
            "drag": float(parameters.get("drag", 0.955)),
            "well_radius": int(parameters.get("well_radius", 30)),
            "capture_speed": float(parameters.get("capture_speed", 2.8)),
            "checkpoint_radius": int(parameters.get("checkpoint_radius", 34)),
            "max_ticks": int(parameters.get("max_ticks", 720)),
            "boundary_restitution": 0.55,
        },
    })
    truth.update({"rounds": rounds, "physics": public["physics"]})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth


def _pheromone(task: dict[str, Any], seed: str):
    mechanic = "pheromone_dispatch"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(f"{seed}|{mechanic}|d{condition['difficulty']}".encode()).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id
    centre = rng.randint(232, 248)
    nest = [rng.randint(55, 70), centre]
    dock = [rng.randint(830, 845), centre]
    upper = rng.randint(78, 103)
    lower = rng.randint(377, 402)
    all_fields = {
        "amber": {"id": "amber", "label": "AMBER / UPPER CACHE", "color": "#d94f72", "cache": [450, upper], "trail_ttl_ticks": int(parameters.get("amber_ttl_ticks", 96)), "speed": float(parameters.get("amber_speed", 3.25))},
        "violet": {"id": "violet", "label": "VIOLET / LOWER CACHE", "color": "#6f5bd8", "cache": [450, lower], "trail_ttl_ticks": int(parameters.get("violet_ttl_ticks", 112)), "speed": float(parameters.get("violet_speed", 2.85))},
    }
    field_ids = tuple(parameters.get("field_ids") or ("amber", "violet"))
    if not field_ids or any(field_id not in all_fields for field_id in field_ids):
        raise ValueError("pheromone dispatch field profile is invalid")
    fields = [all_fields[field_id] for field_id in field_ids]
    all_obstacles = [
        {"x": rng.randint(285, 315), "y": centre, "w": rng.randint(88, 108), "h": rng.randint(175, 195)},
        {"x": rng.randint(585, 615), "y": centre, "w": rng.randint(88, 108), "h": rng.randint(175, 195)},
    ]
    obstacle_count = int(parameters.get("obstacle_count", 2))
    if not 1 <= obstacle_count <= len(all_obstacles):
        raise ValueError("pheromone dispatch obstacle profile is invalid")
    obstacles = all_obstacles[:obstacle_count]
    reference_paths = {
        field["id"]: [nest, [175, field["cache"][1]], [380, field["cache"][1]], field["cache"], [690, field["cache"][1]], dock]
        for field in fields
    }
    public.update({
        "generator": {"name": "dual_decaying_pheromone_fields_v3", "variant_count": 10**10},
        "canvas": {"width": 900, "height": 480},
        "nest": nest,
        "dock": dock,
        "fields": fields,
        "obstacles": obstacles,
        "ant_count": int(parameters.get("ant_count", 10)),
        "physics": {
            "tick_ms": 45,
            "sample_radius": 22,
            "brush_radius": 23,
            "delivery_required": int(parameters.get("delivery_required", 7)),
            "ant_spacing": int(parameters.get("ant_spacing", 18)),
        },
    })
    truth.update({"reference_paths": reference_paths, "obstacles": obstacles, "physics": public["physics"]})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth


CLUTCH_RATIO_PROFILES = {
    "single": (
        (1.0,),
    ),
    "paired": (
        (1.0, -1.25),
        (1.25, -1.0),
        (1.5, -1.25),
    ),
    "legacy_four": (
        (1.0, -1.25, 1.5, -1.75),
        (1.25, -1.0, 1.75, -1.5),
        (1.5, -1.75, 1.0, -1.25),
    ),
    "wide_four": (
        (1.25, -1.5, 1.75, -2.0),
        (1.5, -1.25, 2.0, -1.75),
        (1.75, -2.0, 1.25, -1.5),
    ),
}


def _clutch(task: dict[str, Any], seed: str):
    mechanic = "clockwork_clutch_safe"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{mechanic}|d{condition['difficulty']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id

    shaft_count = int(parameters.get("shaft_count", 4))
    ratio_profile = str(parameters.get("ratio_profile", "legacy_four"))
    ratio_bank = CLUTCH_RATIO_PROFILES.get(ratio_profile)
    if not 1 <= shaft_count <= 4 or ratio_bank is None or any(len(profile) != shaft_count for profile in ratio_bank):
        raise ValueError("clockwork shaft count and ratio profile do not agree")
    ratios = rng.choice(ratio_bank)

    raw_ranges = parameters.get(
        "release_tick_ranges",
        ((31, 38), (56, 65), (84, 94), (116, 128)),
    )
    if not isinstance(raw_ranges, (list, tuple)) or len(raw_ranges) != shaft_count:
        raise ValueError("clockwork release window count does not match the shaft count")
    release_tick_ranges: list[tuple[int, int]] = []
    for value in raw_ranges:
        if not isinstance(value, (list, tuple)) or len(value) != 2 or any(isinstance(item, bool) for item in value):
            raise ValueError("clockwork release window is malformed")
        start, end = int(value[0]), int(value[1])
        if start < 1 or end < start:
            raise ValueError("clockwork release window is inverted")
        release_tick_ranges.append((start, end))
    if any(previous[1] >= following[0] for previous, following in zip(release_tick_ranges, release_tick_ranges[1:])):
        raise ValueError("clockwork release windows must be strictly ordered and disjoint")

    tick_ms = int(parameters.get("tick_ms", 85))
    drive_deg = float(parameters.get("drive_deg_per_tick", 1.8))
    load_numerator = int(parameters.get("load_numerator", 4))
    tolerance = float(parameters.get("phase_tolerance_deg", 13.0))
    max_ticks = int(parameters.get("max_ticks", 170))
    show_angle_readout = parameters.get("show_angle_readout", True)
    show_speed_readout = parameters.get("show_speed_readout", True)
    reengagement_allowed = parameters.get("reengagement_allowed", True)
    if not 50 <= tick_ms <= 200 or not .5 <= drive_deg <= 3.0:
        raise ValueError("clockwork drive timing is outside supported limits")
    if load_numerator != shaft_count or not 3.0 <= tolerance <= 40.0:
        raise ValueError("clockwork load or phase tolerance is outside supported limits")
    if not release_tick_ranges[-1][1] < max_ticks <= 400:
        raise ValueError("clockwork wind limit must follow every release window")
    if any(not isinstance(value, bool) for value in (show_angle_readout, show_speed_readout, reengagement_allowed)):
        raise ValueError("clockwork telemetry and recovery policies must be boolean")

    order = list(range(shaft_count))
    rng.shuffle(order)
    moments = [rng.randint(start, end) for start, end in release_tick_ranges]
    release_schedule = sorted(({"tick": tick, "shaft": shaft} for tick, shaft in zip(moments, order)), key=lambda item: item["tick"])
    accumulated = [0.0] * shaft_count
    active = set(range(shaft_count))
    by_tick = {item["tick"]: item["shaft"] for item in release_schedule}
    for tick in range(1, max(moments) + 1):
        factor = load_numerator / len(active)
        for shaft in active:
            accumulated[shaft] += ratios[shaft] * drive_deg * factor
        if tick in by_tick:
            active.remove(by_tick[tick])
    initial = [round((-value) % 360.0, 3) for value in accumulated]
    physics = {
        "tick_ms": tick_ms,
        "drive_deg_per_tick": drive_deg,
        "load_numerator": load_numerator,
        "phase_tolerance_deg": tolerance,
        "max_ticks": max_ticks,
    }
    # True is the legacy/current behavior. Omit default policy flags so the
    # calibrated L3 public and hidden contracts stay byte-for-byte equivalent
    # to the original generator once control identity is removed.
    if not show_angle_readout:
        physics["show_angle_readout"] = False
    if not show_speed_readout:
        physics["show_speed_readout"] = False
    if not reengagement_allowed:
        physics["reengagement_allowed"] = False
    public.update({
        "generator": {"name": "load_redistributing_clutch_safe_v2", "variant_count": 10 ** (shaft_count + 6)},
        "shafts": [{"id": f"seal-{i + 1}", "ratio": ratio, "angle_deg": initial[i], "engaged": True} for i, ratio in enumerate(ratios)],
        "physics": physics,
    })
    truth.update({"release_schedule": release_schedule, "ratios": ratios, "initial_angles": initial, "physics": public["physics"]})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
    return public, truth


def _marionette(task: dict[str, Any], seed: str):
    mechanic = "marionette_checkpoint"
    rng, public, truth = _identity(mechanic, task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{mechanic}|d{condition['difficulty']}|{condition['interaction']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id
    act_count = int(parameters.get("act_count", 3))
    active_indices = tuple(int(value) for value in parameters.get("active_string_indices", (0, 1, 2, 3)))
    base_low = int(parameters.get("base_length_low", 34))
    base_high = int(parameters.get("base_length_high", 66))
    amplitude_low = int(parameters.get("amplitude_low", 5))
    amplitude_high = int(parameters.get("amplitude_high", 8))
    angular_rates = tuple(float(value) for value in parameters.get("angular_rates", (0.046, 0.050, 0.054)))
    tracking_ticks = int(parameters.get("tracking_ticks", 68))
    miss_decay_ticks = int(parameters.get("miss_decay_ticks", 2))
    ring_radius = int(parameters.get("ring_radius", 21))
    tick_ms = int(parameters.get("tick_ms", 55))
    if (
        not 1 <= act_count <= 3
        or not active_indices
        or len(set(active_indices)) != len(active_indices)
        or any(index not in range(4) for index in active_indices)
        or not 20 <= base_low <= base_high <= 80
        or not 0 <= amplitude_low <= amplitude_high <= 15
        or not angular_rates
        or any(not .015 <= rate <= .09 for rate in angular_rates)
        or not 20 <= tracking_ticks <= 120
        or not 1 <= miss_decay_ticks <= 5
        or not 17 <= ring_radius <= 34
        or not 40 <= tick_ms <= 100
    ):
        raise ValueError("marionette difficulty profile is outside supported limits")
    poses = []
    for index in range(act_count):
        base = [50] * 4
        for string in active_indices:
            base[string] = rng.randint(base_low, base_high)
        amplitudes = [0] * 4
        for string in active_indices:
            upper = min(amplitude_high, base[string] - 21, 79 - base[string])
            if upper < amplitude_low:
                raise ValueError("marionette base range cannot accommodate its string amplitude")
            amplitudes[string] = rng.randint(amplitude_low, upper)
        poses.append({
            "id": f"inspection-{index + 1}",
            "base_lengths": base,
            "amplitudes": amplitudes,
            "phases": [round(rng.random() * math.tau, 5) for _ in range(4)],
            "angular_rate": rng.choice(angular_rates),
            "tracking_ticks": tracking_ticks,
            "miss_decay_ticks": miss_decay_ticks,
        })
    public.update({
        "generator": {"name": "moving_coupled_marionette_inspection_v2", "variant_count": 10**11},
        "canvas": {"width": 900, "height": 480},
        "initial_lengths": [50, 50, 50, 50],
        "poses": poses,
        "length_range": [20, 80],
        "ring_radius": ring_radius,
        "tick_ms": tick_ms,
    })
    truth.update({"poses": poses, "ring_radius": public["ring_radius"]})
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
        truth["control_condition"] = copy.deepcopy(condition)
        # The L4 reference deliberately omits these defaults so, once control
        # identity is removed, it remains byte-for-byte the original task.
        if int(condition["difficulty"]) != 4:
            public["active_string_indices"] = list(active_indices)
            truth["active_string_indices"] = list(active_indices)
    return public, truth


GENERATORS = {
    "specular_lighthouse_relay": _specular,
    "wind_tunnel_seed_courier": _wind,
    "hologram_silhouette_foundry": _hologram,
    "orbital_docking_customs": _orbital,
    "gravity_room_freight": _gravity,
    "floodgate_archive_rescue": _flood,
    "elastic_membrane_sorter": _membrane,
    "pheromone_dispatch": _pheromone,
    "clockwork_clutch_safe": _clutch,
    "marionette_checkpoint": _marionette,
}


def generate(mechanic: str, task: dict[str, Any], seed: str):
    return GENERATORS[mechanic](task, seed)
