from __future__ import annotations

import copy
import math
from typing import Any


MECHANIC_ID = "lanternwing_roundup"
DT = 0.08


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "score": 0, "feedback": message}


def _round(value: float) -> float:
    return round(float(value), 5)


def _close(a: Any, b: Any, tolerance: float = 0.002) -> bool:
    try:
        return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tolerance
    except (TypeError, ValueError):
        return False


def _position(motion: dict[str, Any], tick: int) -> dict[str, float]:
    phase = float(motion["phase"]) + float(motion["rate"]) * int(tick)
    return {
        "x": _round(float(motion["base_x"]) + float(motion["amp_x"]) * math.sin(phase)),
        "y": _round(float(motion["base_y"]) + float(motion["amp_y"]) * math.sin(phase * 1.31)),
        "z": _round(float(motion["base_z"]) + float(motion["amp_z"]) * math.cos(phase * 0.83)),
    }


def _direction(yaw: float, pitch: float) -> tuple[float, float, float]:
    cp = math.cos(pitch)
    return math.sin(yaw) * cp, math.sin(pitch), math.cos(yaw) * cp


def _move(player: dict[str, float], keys: set[str], world: dict[str, Any], command: str | None = None) -> None:
    active = set(keys)
    if command:
        active = {command}
    forward_x, _, forward_z = _direction(float(player["yaw"]), 0.0)
    right_x, right_z = math.cos(float(player["yaw"])), -math.sin(float(player["yaw"]))
    dx = dz = 0.0
    if "w" in active or "arrowup" in active or "forward" in active:
        dx += forward_x
        dz += forward_z
    if "s" in active or "arrowdown" in active or "back" in active:
        dx -= forward_x
        dz -= forward_z
    if "d" in active or "arrowright" in active or "right" in active:
        dx += right_x
        dz += right_z
    if "a" in active or "arrowleft" in active or "left" in active:
        dx -= right_x
        dz -= right_z
    length = math.hypot(dx, dz)
    if length:
        speed = float(world["move_speed"]) * DT
        player["x"] += dx / length * speed
        player["z"] += dz / length * speed
    bounds = world["bounds"]
    player["x"] = max(float(bounds["x_min"]) + 0.45, min(float(bounds["x_max"]) - 0.45, player["x"]))
    player["z"] = max(float(bounds["z_min"]) + 0.45, min(float(bounds["z_max"]) - 0.45, player["z"]))


def _inside_obstacle(point: dict[str, float], obstacle: dict[str, Any]) -> bool:
    return (
        float(obstacle["x"]) - float(obstacle["width"]) / 2 <= point["x"] <= float(obstacle["x"]) + float(obstacle["width"]) / 2
        and float(obstacle["z"]) - float(obstacle["depth"]) / 2 <= point["z"] <= float(obstacle["z"]) + float(obstacle["depth"]) / 2
        and float(obstacle["y"]) <= point["y"] <= float(obstacle["y"]) + float(obstacle["height"])
    )


def _snapshot(player: dict[str, float], live: list[dict[str, Any]], projectile: dict[str, Any] | None, tick: int, captures: list[str], ammo: int) -> dict[str, Any]:
    return {
        "tick": tick,
        "player": {key: _round(value) for key, value in player.items()},
        "creatures": [
            {"id": item["id"], "x": _round(item["x"]), "y": _round(item["y"]), "z": _round(item["z"])}
            for item in live
        ],
        "projectile": None if projectile is None else {key: _round(projectile[key]) if key != "age" else int(projectile[key]) for key in ("x", "y", "z", "vx", "vy", "vz", "age")},
        "captures": list(captures),
        "ammo": int(ammo),
    }


def _same_snapshot(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if actual.get("tick") != expected.get("tick") or actual.get("captures") != expected.get("captures") or actual.get("ammo") != expected.get("ammo"):
        return False
    for key in ("player",):
        for field, value in (expected.get(key) or {}).items():
            if not _close((actual.get(key) or {}).get(field), value):
                return False
    actual_creatures = actual.get("creatures") or []
    expected_creatures = expected.get("creatures") or []
    if [item.get("id") for item in actual_creatures] != [item.get("id") for item in expected_creatures]:
        return False
    for left, right in zip(actual_creatures, expected_creatures):
        if any(not _close(left.get(field), right.get(field)) for field in ("x", "y", "z")):
            return False
    left_projectile, right_projectile = actual.get("projectile"), expected.get("projectile")
    if (left_projectile is None) != (right_projectile is None):
        return False
    if left_projectile is not None and any(not _close(left_projectile.get(field), right_projectile.get(field)) for field in ("x", "y", "z", "vx", "vy", "vz")):
        return False
    return True


def grade(payload: dict[str, Any], truth: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mechanic_id") != MECHANIC_ID or truth.get("mechanic_id") != MECHANIC_ID:
        return _fail("mechanic mismatch")
    if payload.get("task_id") != truth.get("task_id") or payload.get("challenge_id") != truth.get("challenge_id") or public.get("challenge_id") != truth.get("challenge_id"):
        return _fail("stale task or challenge")
    if public.get("world") != truth.get("world") or public.get("physics") != truth.get("physics"):
        return _fail("public geometry differs from the replay contract")
    condition = truth.get("control_condition")
    if condition is not None and public.get("control_condition") != condition:
        return _fail("control condition mismatch")
    interaction = str((condition or {}).get("interaction") or "full")
    expected = {
        "full": {"move_keydown", "move_keyup", "mouse_drag", "canvas_throw"},
        "simplified": {"move_button", "look_button", "throw_button"},
    }[interaction]
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 12000:
        return _fail("malformed transcript")
    player = {key: float(value) for key, value in truth["world"]["player_start"].items()}
    live = copy.deepcopy(truth["initial_creatures"])
    keys: set[str] = set()
    pending_command: str | None = None
    projectile: dict[str, Any] | None = None
    captures: list[str] = []
    ammo = int(truth["physics"]["ammo"])
    tick = 0
    terminal = False
    target_ids = set(str(value) for value in truth["target_ids"])
    for seq, event in enumerate(events, 1):
        if not isinstance(event, dict) or int(event.get("seq", -1)) != seq:
            return _fail(f"event {seq} sequence invalid")
        if terminal:
            return _fail("events appeared after terminal submission")
        kind = str(event.get("type") or "")
        if kind == "input":
            source = str(event.get("input_source") or "")
            if source not in expected:
                return _fail("wrong interaction surface")
            action = str(event.get("action") or "")
            if action == "key_down":
                key = str(event.get("key") or "").lower()
                if key not in {"w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright"}:
                    return _fail("unknown movement key")
                keys.add(key)
            elif action == "key_up":
                keys.discard(str(event.get("key") or "").lower())
            elif action == "step":
                pending_command = str(event.get("move") or "")
                if pending_command not in {"forward", "back", "left", "right"}:
                    return _fail("unknown proxy movement")
            else:
                return _fail("unknown input event")
            continue
        if kind == "look":
            source = str(event.get("input_source") or "")
            if source not in expected:
                return _fail("wrong interaction surface")
            try:
                yaw, pitch = float(event["yaw"]), float(event["pitch"])
            except (KeyError, TypeError, ValueError):
                return _fail("malformed look event")
            if not (-math.pi <= yaw <= math.pi and -1.15 <= pitch <= 1.15):
                return _fail("look outside camera limits")
            player["yaw"], player["pitch"] = yaw, pitch
            continue
        if kind == "throw":
            source = str(event.get("input_source") or "")
            if source not in expected or (interaction == "full" and source != "canvas_throw") or (interaction == "simplified" and source != "throw_button"):
                return _fail("wrong throw input surface")
            if int(event.get("tick", -1)) != tick or projectile is not None or ammo <= 0:
                return _fail("throw was not available at its recorded tick")
            dx, dy, dz = _direction(player["yaw"], player["pitch"])
            if any(not _close(event.get(field), value, 0.004) for field, value in (("dir_x", dx), ("dir_y", dy), ("dir_z", dz))):
                return _fail("throw direction disagrees with the camera")
            origin = {"x": player["x"], "y": player["y"] + float(truth["world"]["eye_height"]), "z": player["z"]}
            if any(not _close(event.get(field), value, 0.004) for field, value in (("origin_x", origin["x"]), ("origin_y", origin["y"]), ("origin_z", origin["z"]))):
                return _fail("throw origin disagrees with the player")
            speed = float(truth["physics"]["projectile_speed"])
            projectile = {"x": origin["x"], "y": origin["y"], "z": origin["z"], "vx": dx * speed, "vy": dy * speed, "vz": dz * speed, "age": 0}
            ammo -= 1
            continue
        if kind == "tick":
            snapshot = event.get("snapshot") or {}
            if int(snapshot.get("tick", -1)) != tick + 1 or tick >= int(truth["physics"]["max_ticks"]):
                return _fail("tick order or task clock invalid")
            tick += 1
            _move(player, keys, truth["world"], pending_command)
            pending_command = None
            for item in live:
                item.update(_position(item["motion"], tick))
            resolution = None
            if projectile is not None:
                projectile["x"] += projectile["vx"] * DT
                projectile["y"] += projectile["vy"] * DT - 0.5 * float(truth["physics"]["gravity"]) * DT * DT
                projectile["z"] += projectile["vz"] * DT
                projectile["vy"] -= float(truth["physics"]["gravity"]) * DT
                projectile["age"] += 1
                if projectile["y"] <= 0 or projectile["age"] >= int(truth["physics"]["max_projectile_ticks"]) or any(_inside_obstacle(projectile, obstacle) for obstacle in truth["world"]["obstacles"]):
                    resolution = "miss"
                    projectile = None
                else:
                    hit = next((item for item in live if math.dist((projectile["x"], projectile["y"], projectile["z"]), (item["x"], item["y"], item["z"])) <= float(item["radius"]) + float(truth["physics"]["projectile_radius"])), None)
                    if hit is not None:
                        resolution = "target" if hit["id"] in target_ids else "decoy"
                        captures.append(str(hit["id"]))
                        live.remove(hit)
                        projectile = None
            expected_snapshot = _snapshot(player, live, projectile, tick, captures, ammo)
            if not _same_snapshot(snapshot, expected_snapshot):
                return _fail(f"tick {tick} disagrees with independent 3D replay")
            continue
        if kind == "certify":
            if event.get("input_source") != "certify_button":
                return _fail("certification did not use the visible button")
            terminal = event
            accepted = target_ids.issubset(set(captures))
            if bool(event.get("accepted")) != accepted:
                return _fail("visible certification disagrees with replay")
            continue
        return _fail(f"unknown event type {kind!r}")
    if not isinstance(terminal, dict):
        return _fail("no visible certification")
    accepted = target_ids.issubset(set(captures))
    passed = accepted and payload.get("completed") is True
    return {
        "graded": True, "passed": passed, "score": 100 if passed else 0,
        "feedback": f"3D roundup replay: wanted {len(target_ids & set(captures))}/{len(target_ids)}; decoy or miss events {len(captures) - len(target_ids & set(captures))}; ticks {tick}",
    }


def cheat(public_state: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_ids": list(ground_truth.get("target_ids") or []),
        "instruction": "Use ordinary movement, camera and capsule controls; inspect the wanted-wing cards and lead each moving wing through its ballistic flight.",
        "answers": [],
        "public_challenge_id": public_state.get("challenge_id"),
    }
