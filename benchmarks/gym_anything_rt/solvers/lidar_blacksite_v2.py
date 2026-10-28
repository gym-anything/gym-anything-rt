from __future__ import annotations

import json
import math
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "lidar_blacksite_v2"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def _wait(page, milliseconds: int) -> None:
    if page.evaluate("() => window.GymAnythingRTTime?.status().mode === 'paused'"):
        page.evaluate("ms => GymAnythingRTTime.runFor(ms)", milliseconds)
        deadline = time.monotonic() + milliseconds / 1000 + 10
        while page.evaluate("GymAnythingRTTime.status().phase") != "completed":
            if time.monotonic() > deadline:
                raise AssertionError("LIDAR paused observation window timed out")
            time.sleep(.01)
    else:
        page.wait_for_timeout(milliseconds)


def _position(page) -> tuple[float, float]:
    value = page.evaluate("() => [window.lidarBlacksiteV2Model.player.x, window.lidarBlacksiteV2Model.player.y]")
    return float(value[0]), float(value[1])


def _heading(page) -> float:
    return float(page.evaluate("() => window.lidarBlacksiteV2Model.player.heading"))


def _normalize(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def _interaction(page) -> str:
    return str(page.locator(".lidar-blacksite-v2").get_attribute("data-interaction") or "simplified")


def _hold_control(page, control: str, duration_ms: int) -> None:
    if _interaction(page) == "full":
        key = {
            "forward": "w",
            "back": "s",
            "strafe_left": "a",
            "strafe_right": "d",
        }[control]
        page.keyboard.down(key)
        try:
            _wait(page, duration_ms)
        finally:
            page.keyboard.up(key)
        return
    button = page.locator(f'[data-hold="{control}"]')
    box = button.bounding_box()
    if not box:
        raise AssertionError(f"LIDAR control button {control!r} is not visible")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    try:
        _wait(page, duration_ms)
    finally:
        page.mouse.up()


def _drag_look(page, delta_pixels: float) -> None:
    canvas = page.locator("#lidar-canvas")
    box = canvas.bounding_box()
    if not box:
        raise AssertionError("LIDAR viewport is not visible")
    center_x = box["x"] + box["width"] / 2
    center_y = box["y"] + box["height"] / 2
    maximum = max(30.0, box["width"] * .34)
    delta = max(-maximum, min(maximum, delta_pixels))
    page.mouse.move(center_x, center_y)
    page.mouse.down()
    page.mouse.move(center_x + delta, center_y, steps=2)
    page.mouse.up()


def _turn_to(page, target: tuple[float, float] | float) -> None:
    if isinstance(target, tuple):
        x, y = _position(page)
        desired = math.atan2(target[1] - y, target[0] - x)
    else:
        desired = target
    turn_speed = math.radians(float(page.evaluate(
        "() => window.lidarBlacksiteV2Model.state.controls.turn_speed_deg"
    )))
    for _ in range(20):
        difference = _normalize(desired - _heading(page))
        if abs(difference) <= .045:
            return
        if _interaction(page) == "full":
            _drag_look(page, difference / .004)
            _wait(page, 22)
            continue
        # Use one physical hold for the remaining turn. Splitting a right-angle
        # turn into many sampled pulses makes a recorded env.step replay depend
        # on the oracle browser's exact 20 ms timer phase. One continuous hold
        # has at most one tick of phase uncertainty; re-read once for any small
        # final correction.
        pulse_ms = max(22, round(abs(difference) / turn_speed * 1000))
        _hold_control(page, "turn_right" if difference > 0 else "turn_left", pulse_ms)
        _wait(page, 22)
    difference = abs(_normalize(desired - _heading(page)))
    if difference > .08:
        raise AssertionError(f"continuous turn stopped {difference:.4f} radians from its target")


def _move_to(page, point: list[float] | tuple[float, float], tolerance: float = .04) -> None:
    target = (float(point[0]), float(point[1]))
    stalls = 0
    for _ in range(180):
        if _interaction(page) == "full" and page.evaluate(
            """() => {
              const model = window.lidarBlacksiteV2Model;
              if (!model?.carrying) return false;
              const gate = model.state.objects.find((item) => item.kind === "exit");
              const center = [(gate.min[0] + gate.max[0]) / 2, (gate.min[1] + gate.max[1]) / 2];
              return Math.hypot(model.player.x - center[0], model.player.y - center[1]) <= model.state.controls.exit_radius;
            }"""
        ):
            return
        x, y = _position(page)
        remaining = math.dist((x, y), target)
        if remaining <= tolerance:
            return
        _turn_to(page, target)
        speed = float(page.evaluate("() => window.lidarBlacksiteV2Model.state.controls.move_speed"))
        # Re-observe and correct the continuously rotating rig during travel.
        pulse_ms = max(20, min(350, round(remaining / speed * 1000)))
        _hold_control(page, "forward", pulse_ms)
        _wait(page, 28)
        next_remaining = math.dist(_position(page), target)
        if next_remaining < remaining - .025:
            stalls = 0
            continue
        stalls += 1
        if stalls >= 2:
            # A human releases the key instead of grinding against the wall,
            # backs out of a corner by one short physical pulse, and re-aims.
            _hold_control(page, "back", 100)
            _wait(page, 28)
            stalls = 0
    x, y = _position(page)
    heading = _heading(page)
    collisions = int(page.evaluate("() => window.lidarBlacksiteV2Model.player.collisions"))
    raise AssertionError(
        f"continuous movement stalled before {target}: position=({x:.3f}, {y:.3f}), "
        f"heading={heading:.4f}, remaining={math.dist((x, y), target):.3f}, collisions={collisions}"
    )


def _scan(page) -> None:
    cooldown = int(page.evaluate("() => Math.max(0, lidarBlacksiteV2Model.state.controls.scan_cooldown_ticks - (lidarBlacksiteV2Model.player.tick-lidarBlacksiteV2Model.lastScanTick)) * lidarBlacksiteV2Model.state.controls.tick_ms"))
    if cooldown:
        _wait(page, cooldown + 20)
    before = int(page.evaluate("() => window.lidarBlacksiteV2Model.scanCount"))
    if _interaction(page) == "full":
        canvas = page.locator("#lidar-canvas")
        box = canvas.bounding_box()
        if not box:
            raise AssertionError("LIDAR viewport is not visible")
        # Keep the horizontal aim centered while clicking outside the pickup reticle.
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] * .2)
    else:
        page.locator("#lidar-scan").click()
    assert page.evaluate("lidarBlacksiteV2Model.scanCount") == before + 1


def _pickup(page) -> None:
    if _interaction(page) == "full":
        beacon = page.evaluate(
            """() => {
              const model = window.lidarBlacksiteV2Model;
              const object = model.state.objects.find((item) => item.kind === "beacon");
              return [(object.min[0] + object.max[0]) / 2, (object.min[1] + object.max[1]) / 2];
            }"""
        )
        _turn_to(page, (float(beacon[0]), float(beacon[1])))
        canvas = page.locator("#lidar-canvas")
        box = canvas.bounding_box()
        if not box:
            raise AssertionError("LIDAR viewport is not visible")
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    else:
        page.locator("#lidar-pickup").click()
    assert page.evaluate("lidarBlacksiteV2Model.carrying") is True


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    expect(page.locator(".lidar-blacksite-v2")).to_be_visible()
    page.locator("#lidar-abandon").click()
    expect(page.locator(".lidar-verdict.is-fail")).to_be_visible(timeout=7_000)
    expect(page.locator(".lidar-foot .readout")).to_contain_text("FAIL", timeout=7_000)
    deadline = time.time() + 7
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json")["challenge_id"]) != before:
            break
        time.sleep(.05)
    else:
        raise AssertionError("aborted blacksite did not issue a fresh facility")
    _shot(page, out_dir, mechanic, "fail-fresh-facility")
    expect(page.locator(".lidar-verdict.is-fresh")).to_be_hidden(timeout=3_500)

    # Prove swept collision on this disposable facility. The damaged transcript
    # is then abandoned so the accepted trajectory starts with a zero ledger.
    truth = _read(state_dir / "ground_truth.json")
    route = [list(map(float, point)) for point in truth["solution"]["route_points"]]
    first_heading = math.atan2(route[1][1] - route[0][1], route[1][0] - route[0][0])
    _turn_to(page, first_heading + math.pi / 2)
    prior_collisions = int(page.evaluate("() => window.lidarBlacksiteV2Model.player.collisions"))
    if _interaction(page) == "full":
        page.keyboard.down("w")
        try:
            page.wait_for_function(
                "before => window.lidarBlacksiteV2Model.player.collisions > before",
                arg=prior_collisions,
                timeout=3_000,
            )
        finally:
            page.keyboard.up("w")
    else:
        button = page.locator('[data-hold="forward"]')
        box = button.bounding_box()
        if not box:
            raise AssertionError("LIDAR forward control is not visible")
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        try:
            page.wait_for_function(
                "before => window.lidarBlacksiteV2Model.player.collisions > before",
                arg=prior_collisions,
                timeout=3_000,
            )
        finally:
            page.mouse.up()
    _shot(page, out_dir, mechanic, "swept-wall-collision")
    before = str(truth["challenge_id"])
    page.locator("#lidar-abandon").click()
    expect(page.locator(".lidar-verdict.is-fail")).to_be_visible(timeout=7_000)
    deadline = time.time() + 7
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json")["challenge_id"]) != before:
            break
        time.sleep(.05)
    else:
        raise AssertionError("collision smoke was not replaced by a fresh facility")
    truth = _read(state_dir / "ground_truth.json")
    page.wait_for_function(
        "id => document.querySelector('.lidar-blacksite-v2')?.dataset.challengeId === id",
        arg=str(truth["challenge_id"]),
        timeout=7_000,
    )
    expect(page.locator(".lidar-verdict.is-fresh")).to_be_hidden(timeout=3_500)
    expect(page.locator("#lidar-collisions")).to_have_text("00")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    expect(page.locator(".lidar-blacksite-v2")).to_be_visible(timeout=6_000)
    truth = _read(state_dir / "ground_truth.json")
    route = [list(map(float, point)) for point in truth["solution"]["route_points"]]
    scan_indices = set(map(int, truth["solution"]["scan_route_indices"]))
    beacon_index = int(truth["solution"]["beacon_route_index"])
    if (
        not route
        or 0 not in scan_indices
        or not 0 < beacon_index < len(route) - 1
        or any(index < 0 or index > beacon_index for index in scan_indices)
        or max(index for index in scan_indices if index < beacon_index) != beacon_index - 1
    ):
        raise AssertionError("hidden LIDAR verification route violates its controlled solver contract")
    _shot(page, out_dir, mechanic, "initial-lightless-facility")

    expect(page.locator("#lidar-collisions")).to_have_text("00")
    _shot(page, out_dir, mechanic, "clean-acceptance-facility")
    first_heading = math.atan2(route[1][1] - route[0][1], route[1][0] - route[0][0])
    _turn_to(page, first_heading)
    scan_count = 0
    target_shot = False

    for index, waypoint in enumerate(route):
        if index:
            _move_to(page, waypoint)
        if index in scan_indices:
            if index < len(route) - 1:
                _turn_to(page, (float(route[index + 1][0]), float(route[index + 1][1])))
            _scan(page)
            scan_count += 1
            if scan_count == 1:
                _shot(page, out_dir, mechanic, "world-anchored-point-cloud")
            elif scan_count == 2:
                _shot(page, out_dir, mechanic, "multi-station-rescan")
            target_seen = bool(page.evaluate("() => window.lidarBlacksiteV2Model.targetSeen"))
            if target_seen and not target_shot and index < beacon_index:
                _shot(page, out_dir, mechanic, "occluded-beacon-revealed")
                target_shot = True
        if index == beacon_index:
            beacon = next(o for o in truth["objects"] if o["kind"] == "beacon")
            _turn_to(page, tuple((beacon["min"][axis]+beacon["max"][axis])/2 for axis in (0,1)))
            _scan(page)
            assert page.evaluate("lidarBlacksiteV2Model.targetSeen") is True
            if _interaction(page) == "simplified":
                expect(page.locator("#lidar-pickup")).to_be_enabled()
            _pickup(page)
            _shot(page, out_dir, mechanic, "physical-beacon-carry")

    collisions = int(page.evaluate("() => window.lidarBlacksiteV2Model.player.collisions"))
    if collisions != 0:
        raise AssertionError(f"authoritative LIDAR solve was not clean: collisions={collisions}")
    _shot(page, out_dir, mechanic, "extraction-gate-arrival")
    if _interaction(page) == "simplified":
        expect(page.locator("#lidar-verify")).to_be_enabled(timeout=3_000)
        page.locator("#lidar-verify").click()
    expect(page.locator(".lidar-verdict.is-pass")).to_be_visible(timeout=10_000)
    expect(page.locator(".lidar-foot .readout")).to_have_text("PASS", timeout=10_000)
    expect(page.locator(".lidar-foot .readout")).to_have_attribute("data-status", "passed")
    _shot(page, out_dir, mechanic, "authoritative-pass")
