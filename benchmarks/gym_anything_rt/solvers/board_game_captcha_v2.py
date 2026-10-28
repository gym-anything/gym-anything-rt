from __future__ import annotations

import json
import math
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "board_game_captcha_v2"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def _wait_new(state_dir: Path, previous: str) -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json").get("challenge_id")) != previous:
            return
        time.sleep(0.05)
    raise AssertionError("gyro board did not issue a fresh run")


def _pad(page) -> tuple[dict, float, float, float]:
    box = page.locator("#tilt-pad").bounding_box()
    if not box:
        raise AssertionError("analog tilt pad is not visible")
    return box, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, min(box["width"], box["height"]) * 0.38


def _move_pad(page, center_x: float, center_y: float, radius: float, tilt: tuple[float, float]) -> None:
    length = math.hypot(*tilt)
    x, y = tilt
    if length > 1:
        x, y = x / length, y / length
    page.mouse.move(center_x + x * radius, center_y + y * radius, steps=1)


def _compass_name(tilt: tuple[float, float]) -> str:
    if math.hypot(*tilt) < 0.12:
        return "level"
    names = ("e", "se", "s", "sw", "w", "nw", "n", "ne")
    return names[round(math.atan2(tilt[1], tilt[0]) / (math.pi / 4)) % 8]


def _choose_compass(page, tilt: tuple[float, float]) -> None:
    page.locator(f'.tilt-choice[data-compass="{_compass_name(tilt)}"]').click()


def _compass_control(command, carry):
    length = math.hypot(*command)
    target = [value / max(1.0, length) + carry[index] for index, value in enumerate(command)]
    choices = {"level": [0.0,0.0], "e": [1.0,0.0], "se": [.71,.71], "s": [0.0,1.0],
               "sw": [-.71,.71], "w": [-1.0,0.0], "nw": [-.71,-.71], "n": [0.0,-1.0], "ne": [.71,-.71]}
    name = min(choices, key=lambda key: math.dist(choices[key], target))
    vector = choices[name]
    return name, vector, [target[index] - vector[index] for index in (0,1)]


def _drive(page, waypoints: list[list[float]], switch_targets: list[int], interaction: str, timeout_s: float = 90.0) -> None:
    analog = interaction == "full"
    carry = [0.0, 0.0]
    if analog:
        _, cx, cy, radius = _pad(page)
        page.mouse.move(cx, cy)
        page.mouse.down()
    deadline = time.time() + timeout_s
    try:
        expected_switches = {waypoint: sequence + 1 for sequence, waypoint in enumerate(switch_targets)}
        for index, target in enumerate(waypoints):
            while time.time() < deadline:
                state = page.evaluate("() => ({position:gyroBoardModel.position,velocity:gyroBoardModel.velocity,switchIndex:gyroBoardModel.switchIndex,completed:gyroBoardModel.completed,deaths:gyroBoardModel.deaths,externalTilt:gyroBoardModel.externalTilt,holeGravity:gyroBoardModel.holeGravity})")
                if state["completed"]:
                    return
                if index in expected_switches:
                    expected_switch = expected_switches[index]
                    if state["switchIndex"] >= expected_switch:
                        break
                elif math.hypot(target[0] - state["position"][0], target[1] - state["position"][1]) < 12:
                    break
                dx, dy = target[0] - state["position"][0], target[1] - state["position"][1]
                vx, vy = state["velocity"]
                external = [a + b for a, b in zip(state.get("externalTilt") or [0, 0],
                                                (state.get("holeGravity") or {}).get("tilt", [0, 0]))]
                command = (dx * 0.018 - vx * 0.0105 - external[0], dy * 0.018 - vy * 0.0105 - external[1])
                if analog:
                    _move_pad(page, cx, cy, radius, command)
                else:
                    name, _, carry = _compass_control(command, carry)
                    page.locator(f'.tilt-choice[data-compass="{name}"]').click()
                page.wait_for_timeout(95)
            else:
                raise AssertionError(f"gyro controller timed out at waypoint {index}: {target}")
        while time.time() < deadline and not page.evaluate("() => gyroBoardModel.completed"):
            state = page.evaluate("() => ({position:gyroBoardModel.position,velocity:gyroBoardModel.velocity,externalTilt:gyroBoardModel.externalTilt,holeGravity:gyroBoardModel.holeGravity})")
            target = waypoints[-1]
            external = [a + b for a, b in zip(state.get("externalTilt") or [0, 0],
                                                (state.get("holeGravity") or {}).get("tilt", [0, 0]))]
            command = ((target[0] - state["position"][0]) * 0.018 - state["velocity"][0] * 0.011 - external[0], (target[1] - state["position"][1]) * 0.018 - state["velocity"][1] * 0.011 - external[1])
            if analog:
                _move_pad(page, cx, cy, radius, command)
            else:
                name, _, carry = _compass_control(command, carry)
                page.locator(f'.tilt-choice[data-compass="{name}"]').click()
            page.wait_for_timeout(95)
        if not page.evaluate("() => gyroBoardModel.completed"):
            raise AssertionError("ball never settled in the goal cup")
    finally:
        if analog:
            page.mouse.up()
        elif page.locator('.tilt-choice[data-compass="level"]').count():
            page.locator('.tilt-choice[data-compass="level"]').click()


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    page.locator("#gyro-submit").click()
    _wait_new(state_dir, before)
    expect(page.locator('.gyro-board[data-fresh-failure="true"]')).to_be_visible(timeout=8_000)
    expect(page.locator(".readout")).to_have_text("FAIL")
    _shot(page, out_dir, mechanic, "fail-fresh-board")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    page.wait_for_function("() => document.querySelector('.gyro-board')?.dataset.freshFailure === 'false'", timeout=4_000)

    switch_waypoints = truth.get("solver_switch_waypoint_indices") or [0, 2, 4]
    _drive(page, truth["solver_waypoints"], switch_waypoints, interaction)
    expect(page.locator('.gyro-board[data-completed="true"]')).to_be_visible(timeout=4_000)
    state = page.evaluate("() => ({ticks:gyroBoardModel.tickCount,controls:gyroBoardModel.controlChanges,switches:gyroBoardModel.switchIndex,deaths:gyroBoardModel.deaths,collisions:gyroBoardModel.collisions,resets:gyroBoardModel.manualResets})")
    if state["switches"] != len(truth["switches"]):
        raise AssertionError(f"gyro run lacks physical evidence: {state}")
    _shot(page, out_dir, mechanic, "all-lamps-and-cup")
    page.locator("#gyro-submit").click()
    expect(page.locator(".readout")).to_have_text("PASS", timeout=8_000)
    expect(page.locator(".gyro-verdict")).to_contain_text("PASS")
    expect(page.locator(".gyro-verdict")).not_to_contain_text("FAIL")
