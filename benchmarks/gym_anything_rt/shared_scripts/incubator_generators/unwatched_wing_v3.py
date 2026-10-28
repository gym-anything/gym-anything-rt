"""Original observer-controlled transit, derived from VGE-535/536/508."""
from __future__ import annotations

import copy
import hashlib
import math
import random

MECHANIC_ID = "unwatched_wing_v3"
REVISION = "lantern-survey-v3"
# Keep the frozen V2 world for a fixed seed; V3 changes the observation surface.
WORLD_SEED_ID = "unwatched_wing_v2"
def _seed_axes(seed):
    """Optional independent stream tags retain a common initial layout.

    Ordinary benchmark seeds are unchanged. A structured seed such as
    'layout#iris-0-4=weather-b' changes only that object's initial angle and current direction.
    This is useful for matched causal diagnostics; it changes no physical rule.
    """
    layout, separator, tags = str(seed).partition("#")
    streams = {}
    if separator:
        if not layout or not tags:
            raise ValueError("empty layout or rate-stream seed")
        for tag in tags.split(","):
            name, equal, value = tag.partition("=")
            if not equal or not name or not value or name in streams:
                raise ValueError("invalid independent rate-stream seed")
            streams[name] = value
    return layout, streams


def _visible_directions(seed, objects):
    layout, tags = _seed_axes(seed)
    names = {o['id'] for o in objects}
    if set(tags)-names:
        raise ValueError('unknown current-stream channel')
    for obj in objects:
        token=tags.get(obj['id'], '')
        digest=hashlib.sha256(f'{layout}|{obj["id"]}|{token}|current'.encode()).digest()
        obj['rate_direction']=1 if digest[0]&1 else -1
        if 'speed_code' in obj:
            obj['speed_direction']=1 if digest[1]&1 else -1
        if token:
            obj['phase_code']=int.from_bytes(digest[2:6], 'big')%360000
            obj['phase']=obj['phase_code']*math.pi/180000
            if 'radius' in obj:
                obj['y']=math.floor((obj['baseline']+obj['amplitude']*math.sin(obj['phase']))*1000+.5)/1000


def _dial(obj, nominal, lower, upper):
    obj["phase_code"] = math.floor((obj["phase"] % math.tau) * 180000 / math.pi + .5) % 360000
    obj["phase"] = obj["phase_code"] * math.pi / 180000
    scale = 1800 / math.pi  # tenths of a degree per second
    obj.update(rate_code=math.floor(obj["omega"] * scale + .5),
               rate_min=math.floor(nominal * lower * scale + .5),
               rate_max=math.floor(nominal * upper * scale + .5),
               rate_step=max(1, math.floor(nominal * .025 * scale + .5)))
PROFILES = {
    1: dict(lanes=1, gates_per_lane=3, aperture_half=43, amplitude=78, omega=.25, cargo_speed=15, cargo_amplitude=52, cargo_omega=.11, photo_lifetime_ms=6000),
    2: dict(lanes=1, gates_per_lane=3, aperture_half=39, amplitude=82, omega=.34, cargo_speed=17, cargo_amplitude=54, cargo_omega=.14, photo_lifetime_ms=5000),
    3: dict(lanes=1, gates_per_lane=4, aperture_half=35, amplitude=84, omega=.42, cargo_speed=20, cargo_amplitude=56, cargo_omega=.16, photo_lifetime_ms=4200),
    4: dict(lanes=2, gates_per_lane=4, aperture_half=37, amplitude=82, omega=.40, cargo_speed=17, cargo_amplitude=56, cargo_omega=.15, photo_lifetime_ms=4000),
    5: dict(lanes=2, gates_per_lane=5, aperture_half=32, amplitude=85, omega=.47, cargo_speed=20, cargo_amplitude=60, cargo_omega=.18, photo_lifetime_ms=3200),
}


def generate(task, seed):
    layout_seed, _ = _seed_axes(seed)
    condition = copy.deepcopy(task.get("_control_condition") or task.get("metadata", {}).get("control_condition"))
    level = (condition or {}).get("difficulty", 5)
    mode = (condition or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("lantern transit needs difficulty 1–5 and a supported interaction")
    parameters = dict(PROFILES[level])
    parameters.update((condition or {}).get("difficulty_parameters", {}))
    if set(parameters) != set(PROFILES[5]):
        raise ValueError("unknown lantern transit difficulty parameter")
    if parameters["lanes"] not in (1, 2) or not 3 <= parameters["gates_per_lane"] <= 5:
        raise ValueError("unsupported transit layout")
    for key, lower, upper in (("aperture_half", 30, 44), ("amplitude", 76, 86),
                              ("omega", .2, .5), ("cargo_speed", 14, 23),
                              ("cargo_amplitude", 50, 64), ("cargo_omega", .10, .20),
                              ("photo_lifetime_ms", 3000, 6500)):
        if not isinstance(parameters[key], (int, float)) or not math.isfinite(parameters[key]) or not lower <= parameters[key] <= upper:
            raise ValueError(f"unsupported {key}")
    # Interaction and task identity deliberately do not affect world randomness.
    # Preserve v1 shutter layouts and horizontal drafts for paired regressions.
    rng = random.Random(hashlib.sha256(f"{layout_seed}|{WORLD_SEED_ID}|lantern-transit-v1".encode()).digest())
    lanes = [250] if parameters["lanes"] == 1 else [145, 355]
    gates, cargo = [], []
    for lane, y in enumerate(lanes):
        count = parameters["gates_per_lane"]
        for i in range(count):
            gates.append(dict(id=f"iris-{lane}-{i}", lane=lane,
                x=round(285 + i * 645 / (count - 1) + rng.uniform(-14, 14), 3),
                baseline=y, half=parameters["aperture_half"], amplitude=parameters["amplitude"],
                phase=rng.uniform(0, math.tau), omega=parameters["omega"] * rng.uniform(.85, 1.1),
                motion_seed=rng.getrandbits(32), span_ms=rng.randrange(3700, 5701), width=14))
            _dial(gates[-1], parameters["omega"], .51, 1.54)
        cargo.append(dict(id=f"courier-{lane}", lane=lane, x=95 + lane * 12, y=y, radius=12,
            speed=parameters["cargo_speed"] * (1 + lane * .07), motion_seed=rng.getrandbits(32),
            span_ms=4500, color=("#93e8cf", "#e3b3ff")[lane], glyph=("moth", "heron")[lane]))
        drift_rng = random.Random(hashlib.sha256(f"{layout_seed}|{WORLD_SEED_ID}|lantern-crosscurrent-v2|{lane}".encode()).digest())
        courier = cargo[-1]
        courier.update(baseline=y, amplitude=parameters["cargo_amplitude"],
            phase=drift_rng.uniform(0, math.tau), omega=parameters["cargo_omega"] * drift_rng.uniform(.9, 1.1),
            drift_seed=drift_rng.getrandbits(32), drift_span_ms=drift_rng.randrange(4300, 7201))
        _dial(courier, parameters["cargo_omega"], .648, 1.408)
        courier.update(speed_code=math.floor(courier["speed"] * 20 + .5),
            speed_min=math.floor(courier["speed"] * .78 * 20 + .5),
            speed_max=math.floor(courier["speed"] * 1.22 * 20 + .5),
            speed_step=max(1, math.floor(courier["speed"] * .01 * 20 + .5)))
        courier["y"] = math.floor((y + courier["amplitude"] * math.sin(courier["phase"])) * 1000 + .5) / 1000
    _visible_directions(seed, gates+cargo)
    world = dict(width=1100, height=500, lanes=lanes, gates=gates, cargo=cargo,
        dock_x=1030, focus_radius=34, aim_speed=620, initial_lens=[75, 35],
        tick_ms=20, max_active_ms=180000, trace_ms=400, photo_lifetime_ms=parameters["photo_lifetime_ms"],
        rate_update_ms=200,
        motion_law="Every 200 ms, each meter moves one visible step in its displayed direction. It reflects at its displayed limits, including while restrained. Height equals lane plus swing times sin(angle); angle advances at the current rate.")
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, revision=REVISION,
        task_id=task["id"], challenge_id=hashlib.sha256(
            f"{seed}|{MECHANIC_ID}|{REVISION}|{level}".encode()).hexdigest()[:16],
        prompt="Bring every sleeping courier to the archive. Inspect frosted shutters with the lantern before guiding the couriers through.",
        world=world, parameters=parameters, single_attempt=True,
        rules=["Frosted survey glass conceals each shutter's aperture, eye, trail and motion dials. Aim the lantern at the visible brass plate to reveal its live view permanently. Inspection consumes normal running time and changes no physical shutter rule.",
               "The lantern pins the nearest eye or courier inside its circle. The dim survey view does not pin objects.",
               "An illuminated eye pins its shutter; an illuminated courier stops both its advance and vertical drift.",
               "A photograph of the currently illuminated object pins it until its visible image fades.",
               "Unrestrained couriers advance and drift vertically. Match each aperture to the moving courier, not the lane center.",
               "Trails show the recent 0.4 seconds. Arrows use a one-second speed scale; dashed arrows show immediate release drift. Faint tracks mark swing limits.",
               "Dials show current angle, angular speed and its rising/falling direction. Courier meters also show forward speed and its direction. Rates step every 0.2 seconds and reflect at the displayed limits, including under restraint.",
               "All other objects keep moving. Touching a closed shutter ends the attempt."],
        asset_manifest="shared_runtime/assets/provenance/unwatched_wing_v3_v0.json",
        generator=dict(name=REVISION, variation_axes=["independent shutter phases", "visible bounded angular currents",
            "shutter placement", "independent courier drafts", "independent vertical courier crosscurrents"]))
    if condition is not None:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), planning_boundary="No route or controller is delivered to the browser. Current angles, rates, rate directions, geometry, lamp and photo determine the physical continuation. Read-only page-state oracle measurements remain privileged implementation evidence.")
    return public, truth
