from __future__ import annotations

import json
import math
import time
from pathlib import Path


MECHANIC_ID = "lanternwing_roundup"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _model(page) -> dict:
    value = page.evaluate(
        """() => {
          const m = window.lanternwingRoundupModel;
          if (!m) return null;
          return {tick:m.tick, ammo:m.ammo, captures:[...m.captures], player:{...m.player}, creatures:m.creatures.map(c=>({...c, motion:{...c.motion}})), projectile:Boolean(m.projectile), physics:{...m.state.physics}, world:{...m.state.world}};
        }"""
    )
    if not value:
        raise AssertionError("Lanternwing Roundup model was not rendered")
    return value


def _position(motion: dict, tick: int) -> tuple[float, float, float]:
    phase = float(motion["phase"]) + float(motion["rate"]) * int(tick)
    return (
        float(motion["base_x"]) + float(motion["amp_x"]) * math.sin(phase),
        float(motion["base_y"]) + float(motion["amp_y"]) * math.sin(phase * 1.31),
        float(motion["base_z"]) + float(motion["amp_z"]) * math.cos(phase * 0.83),
    )


def _aim(snapshot: dict, creature: dict) -> tuple[float, float]:
    player = snapshot["player"]
    physics = snapshot["physics"]
    origin = (float(player["x"]), float(player["y"]) + .18, float(player["z"]))
    speed = float(physics["projectile_speed"])
    gravity = float(physics["gravity"])
    current = (float(creature["x"]), float(creature["y"]), float(creature["z"]))
    distance = math.dist(origin, current)
    flight = max(.28, distance / speed)
    for _ in range(6):
        future_tick = int(snapshot["tick"] + max(1, round(flight / .08)))
        target = _position(creature["motion"], future_tick)
        dx, dy, dz = target[0] - origin[0], target[1] - origin[1], target[2] - origin[2]
        horizontal = math.hypot(dx, dz)
        vertical_velocity = dy / max(.18, flight) + .5 * gravity * max(.18, flight)
        horizontal_speed = math.sqrt(max(.1, speed * speed - vertical_velocity * vertical_velocity)) if abs(vertical_velocity) < speed else speed * .72
        flight = max(.22, horizontal / max(1.0, horizontal_speed))
    target = _position(creature["motion"], int(snapshot["tick"] + max(1, round(flight / .08))))
    dx, dy, dz = target[0] - origin[0], target[1] - origin[1], target[2] - origin[2]
    vertical_velocity = dy / max(.18, flight) + .5 * gravity * max(.18, flight)
    vertical_velocity = max(-speed * .75, min(speed * .75, vertical_velocity))
    horizontal_speed = math.sqrt(max(.1, speed * speed - vertical_velocity * vertical_velocity))
    return math.atan2(dx, dz), math.atan2(vertical_velocity, horizontal_speed)


def _full_look(page, yaw: float, pitch: float) -> None:
    snapshot = _model(page)
    current_yaw = float(snapshot["player"]["yaw"])
    current_pitch = float(snapshot["player"]["pitch"])
    dyaw = ((yaw - current_yaw + math.pi) % (2 * math.pi)) - math.pi
    dpitch = pitch - current_pitch
    if abs(dyaw) < .006 and abs(dpitch) < .006:
        return
    box = page.locator("#lw-canvas").bounding_box()
    if box is None:
        raise AssertionError("Lanternwing canvas has no visible bounds")
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dyaw / .008, y + dpitch / .006, steps=3)
    page.mouse.up()


def _proxy_look(page, yaw: float, pitch: float) -> None:
    for _ in range(48):
        current = _model(page)["player"]
        dyaw = ((yaw - float(current["yaw"]) + math.pi) % (2 * math.pi)) - math.pi
        if abs(dyaw) < .045:
            break
        page.locator("[data-look='yaw'][data-delta]").nth(1 if dyaw > 0 else 0).click()
    for _ in range(30):
        current = _model(page)["player"]
        dpitch = pitch - float(current["pitch"])
        if abs(dpitch) < .035:
            break
        page.locator("[data-look='pitch'][data-delta]").nth(1 if dpitch > 0 else 0).click()


def _walk_forward(page, interaction: str) -> None:
    if interaction == "full":
        page.keyboard.down("w")
        page.wait_for_timeout(620)
        page.keyboard.up("w")
    else:
        for _ in range(8):
            page.locator("[data-move='forward']").click()
            page.wait_for_timeout(18)


def _throw_at(page, interaction: str, target_id: str) -> None:
    snapshot = _model(page)
    creature = next((item for item in snapshot["creatures"] if item["id"] == target_id), None)
    if creature is None:
        return
    yaw, pitch = _aim(snapshot, creature)
    if interaction == "full":
        _full_look(page, yaw, pitch)
        box = page.locator("#lw-canvas").bounding_box()
        if box is None:
            raise AssertionError("Lanternwing canvas disappeared")
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] * .56)
    else:
        _proxy_look(page, yaw, pitch)
        page.locator("#lw-throw-proxy").click()


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    del out_dir
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = _read(Path(state_dir) / "public_state.json")["challenge_id"]
    page.locator("#lw-submit").click()
    page.wait_for_function("() => document.querySelector('.lw-verdict.is-fresh') !== null", timeout=8_000)
    after = _read(Path(state_dir) / "public_state.json")["challenge_id"]
    if before == after:
        raise AssertionError("failed roundup did not issue a fresh challenge")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    del state_dir, out_dir
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    snapshot = _model(page)
    interaction = page.locator(".lanternwing").get_attribute("data-interaction") or "full"
    target_ids = page.evaluate("() => window.lanternwingRoundupModel.creatures.filter(c => window.lanternwingRoundupModel.state.wanted.some(w => w.appearance.color === c.appearance.color && w.appearance.sigil === c.appearance.sigil)).map(c => c.id)")
    _walk_forward(page, interaction)
    for target_id in target_ids:
        for _ in range(3):
            current = _model(page)
            if target_id in current["captures"]:
                break
            if current["ammo"] <= 0:
                raise AssertionError("Lanternwing solver ran out of capsules")
            _throw_at(page, interaction, target_id)
            page.wait_for_function("() => !window.lanternwingRoundupModel.projectile", timeout=6_000)
            if target_id in _model(page)["captures"]:
                break
        if target_id not in _model(page)["captures"]:
            raise AssertionError(f"target {target_id} was not secured")
    page.wait_for_function("() => document.querySelector('#lw-readout')?.textContent.includes('PASS')", timeout=12_000)
