from __future__ import annotations

import copy
import hashlib
import math
import random
from typing import Any


MECHANIC_ID = "horizon_relay_v2"
ASSET_MANIFEST = "shared_runtime/assets/provenance/horizon_relay_v0.json"
PLANET_RADIUS = 150.0


def _rotation_angles(rng: random.Random, speed: float) -> list[float]:
    """Integrate smoothly varying positive rotation over the replay clock."""
    angles = [0.0]
    current = 1.0
    while len(angles) <= 20000:
        target = rng.uniform(.65, 1.35)
        duration = rng.randint(12, 30)
        for offset in range(1, duration + 1):
            fraction = offset / duration
            eased = fraction * fraction * (3 - 2 * fraction)
            multiplier = current + (target - current) * eased
            angles.append(round(angles[-1] + speed * multiplier, 8))
            if len(angles) > 20000:
                break
        current = target
    return angles


def _seed(seed: str) -> int:
    return int(hashlib.sha256(f"{seed}|{MECHANIC_ID}".encode()).hexdigest()[:16], 16)


def _point(latitude: float, longitude: float, radius: float) -> list[float]:
    lat = math.radians(latitude)
    lon = math.radians(longitude)
    return [
        round(radius * math.cos(lat) * math.cos(lon), 5),
        round(radius * math.sin(lat), 5),
        round(radius * math.cos(lat) * math.sin(lon), 5),
    ]


def _identity(task: dict[str, Any], seed: str) -> tuple[random.Random, dict[str, Any], dict[str, Any]]:
    rng = random.Random(_seed(seed))
    task_id = str(task.get("id") or f"{MECHANIC_ID}_seed_0001@0.1")
    challenge_id = hashlib.sha256(f"{seed}|{MECHANIC_ID}".encode()).hexdigest()[:12]
    public = {
        "benchmark": "gym_anything_rt",
        "mechanic_id": MECHANIC_ID,
        "task_id": task_id,
        "challenge_id": challenge_id,
        "asset_manifest": ASSET_MANIFEST,
        "prompt": task.get("natural_language") or "Maintain every requested spacecraft relay.",
    }
    truth = {"mechanic_id": MECHANIC_ID, "task_id": task_id, "challenge_id": challenge_id, "seed": seed}
    return rng, public, truth


def generate(task: dict[str, Any], seed: str):
    rng, public, truth = _identity(task, seed)
    condition = task.get("_control_condition")
    parameters = dict((condition or {}).get("difficulty_parameters") or {})
    if condition:
        challenge_id = hashlib.sha256(
            f"{seed}|{MECHANIC_ID}|d{condition['difficulty']}|{task.get('id')}".encode()
        ).hexdigest()[:12]
        public["challenge_id"] = challenge_id
        truth["challenge_id"] = challenge_id

    craft_count = int(parameters.get("craft_count", 3))
    required_ticks = int(parameters.get("required_ticks", 20))
    rotation_speed = float(parameters.get("rotation_speed_deg_per_tick", 0.40))
    aim_tolerance = float(parameters.get("aim_tolerance_deg", 12.0))
    latitude_spread = float(parameters.get("craft_latitude_spread", 24.0))
    craft_radius = float(parameters.get("craft_radius", 2.56))
    if not 1 <= craft_count <= 5 or required_ticks <= 0 or rotation_speed <= 0 or aim_tolerance <= 0:
        raise ValueError("horizon relay difficulty parameters are outside supported bounds")

    station_specs = (
        ("california", "CALIFORNIA", 17.0, 0.0, "#f4c95d"),
        ("spain", "SPAIN", -12.0, 120.0, "#64d9c1"),
        ("australia", "AUSTRALIA", 8.0, 240.0, "#ff8a78"),
    )
    stations = [
        {"id": sid, "label": label, "latitude": lat, "longitude": lon, "color": color, "radius": PLANET_RADIUS}
        for sid, label, lat, lon, color in station_specs
    ]
    names = ("JUNO", "LUNA", "PIONEER", "AURORA", "KEPLER")
    icons = ("◆", "◈", "✦", "✧", "⬢")
    base_lons = (-28.0, 82.0, 202.0, 42.0, 282.0)
    base_lats = (-0.48, 0.58, -0.18, 0.76, -0.72)
    spacecraft = []
    for index in range(craft_count):
        # The alternating latitudes deliberately make screen-near spacecraft
        # have different station horizons.  Their inertial positions do not
        # rotate with the globe.
        latitude = base_lats[index] * latitude_spread + rng.uniform(-2.5, 2.5)
        longitude = base_lons[index] + rng.uniform(-8.0, 8.0)
        amount = required_ticks
        spacecraft.append({
            "id": f"craft-{index + 1}",
            "label": names[index],
            "icon": icons[index],
            "latitude": round(latitude, 3),
            "longitude": round(longitude % 360.0, 3),
            "position": _point(latitude, longitude, PLANET_RADIUS * craft_radius),
            "required_ticks": amount,
            "color": ("#ffd166", "#70d6ff", "#ef8354", "#c77dff", "#80ed99")[index],
        })

    angles = _rotation_angles(rng, rotation_speed)
    contract = {
        "planet_radius": PLANET_RADIUS,
        "tick_ms": 100,
        "rotation_speed_deg_per_tick": rotation_speed,
        "aim_tolerance_deg": aim_tolerance,
        "stations": copy.deepcopy(stations),
        "spacecraft": copy.deepcopy(spacecraft),
        "craft_count": craft_count,
    }
    public.update({
        "prompt": str(public["prompt"]) + " Keep each transfer uninterrupted. Lost or stopped links clear partial progress; re-aiming a live link preserves it.",
        "generator": {"name": "inertial_spacecraft_horizon_relay_v2_v1", "variant_count": 10**14},
        "planet": {"radius": PLANET_RADIUS, "rotation_axis": "y", "initial_angle_deg": 0.0},
        "rotation": {"tick_ms": 100, "speed_deg_per_tick": rotation_speed},
        "planet_radius": PLANET_RADIUS,
        "tick_ms": 100,
        "rotation_speed_deg_per_tick": rotation_speed,
        "stations": stations,
        "spacecraft": spacecraft,
        "aim_tolerance_deg": aim_tolerance,
        "interaction_mode": str((condition or {}).get("interaction") or "full"),
        "rotation_angles_deg": angles,
        "transfer_rule": "Each request requires an uninterrupted link. Losing or stopping a link clears that request's partial transfer. Re-aiming the same live link preserves it. Completed deliveries remain complete.",
        "control_condition": copy.deepcopy(condition) if condition else None,
    })
    truth.update({
        "rotation_angles_deg": copy.deepcopy(angles),
        "planet_radius": PLANET_RADIUS,
        "tick_ms": 100,
        "rotation_speed_deg_per_tick": rotation_speed,
        "aim_tolerance_deg": aim_tolerance,
        "stations": copy.deepcopy(stations),
        "spacecraft": copy.deepcopy(spacecraft),
        "required_ticks": required_ticks,
        "control_condition": copy.deepcopy(condition) if condition else None,
        "interaction_mode": str((condition or {}).get("interaction") or "full"),
    })
    return public, truth
