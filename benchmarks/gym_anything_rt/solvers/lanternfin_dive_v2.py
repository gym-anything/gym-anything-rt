from __future__ import annotations

import json
import math
import time
from pathlib import Path
from playwright.sync_api import expect
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.lanternfin_dive_v2 import _step, _arrival


MECHANIC_ID = "lanternfin_dive_v2"
KEYS = {
    ("tail", -1): "a", ("tail", 1): "d",
    ("yaw", -1): "j", ("yaw", 1): "l",
    ("pitch", -1): "k", ("pitch", 1): "i",
    ("roll", -1): "q", ("roll", 1): "e",
}
CHANNELS = ("tail", "yaw", "pitch", "roll")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _model(page):
    return page.evaluate(
        """() => {
          const m = window.lanternfinDiveV2Model;
          if (!m) return null;
          return {tick:m.tick, hold:m.hold, fish:{...m.fish}, controls:{...m.controls}, target:{...m.state.target}, physics:{...m.state.physics}, interaction:m.interaction};
        }"""
    )


def _wrap(value: float) -> float:
    return (value + math.pi) % (2 * math.pi) - math.pi


def _wait(page, milliseconds):
    paused = page.evaluate("() => !!window.GymAnythingRTTime && GymAnythingRTTime.status().mode === 'paused'")
    if paused:
        page.evaluate("duration => GymAnythingRTTime.runFor(duration)", milliseconds)
        deadline = time.monotonic() + milliseconds / 1000 + 10
        while page.evaluate("GymAnythingRTTime.status().phase") != "completed":
            if time.monotonic() > deadline:
                raise AssertionError("Lanternfin paused observation window timed out")
            time.sleep(.01)
    else:
        page.wait_for_timeout(milliseconds)


def _desired(snapshot: dict) -> dict[str, int]:
    fish = snapshot["fish"]
    target = snapshot["target"]
    physics = snapshot["physics"]
    linear_coast = float(physics["linear_damping"]) / (1 - float(physics["linear_damping"]))
    angular_coast = float(physics["angular_damping"]) / (1 - float(physics["angular_damping"]))
    dx, dy, dz = (float(target[axis]) - float(fish[axis]) - float(fish["v" + axis]) * linear_coast for axis in ("x", "y", "z"))
    horizontal = math.hypot(dx, dz)
    desired_yaw = math.atan2(dz, dx)
    desired_pitch = math.atan2(dy, max(0.001, horizontal))
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    stopped_yaw = float(fish["yaw"]) + float(fish["yaw_rate"]) * angular_coast
    # Reverse thrust can correct an overshoot without a half-turn orbit.
    if abs(_wrap(desired_yaw - stopped_yaw)) > math.pi / 2:
        desired_yaw = _wrap(desired_yaw + math.pi)
        desired_pitch = -desired_pitch
    yaw_error = _wrap(desired_yaw - stopped_yaw)
    radius = float(physics["arrival_radius"])
    pitch_error = (
        0 if distance < .30 and abs(dy) < radius * .55 else desired_pitch
    ) - (
        float(fish["pitch"]) + float(fish["pitch_rate"]) * angular_coast
    )
    def sign(value: float, deadband: float) -> int:
        return 1 if value > deadband else -1 if value < -deadband else 0
    forward = (math.cos(fish["pitch"]) * math.cos(fish["yaw"]), math.sin(fish["pitch"]), math.cos(fish["pitch"]) * math.sin(fish["yaw"]))
    along = sum(a * b for a, b in zip((dx, dy, dz), forward))
    tail = sign(along, radius * .2) if distance > radius * .65 and abs(along) > distance * .65 else 0
    return {
        "yaw": sign(yaw_error, .075) if distance > radius * .65 else 0,
        "pitch": sign(pitch_error, .06),
        "roll": sign(-float(fish["roll"]) - float(fish["roll_rate"]) * angular_coast, .06),
        "tail": tail,
    }


def _coast_safe(snapshot: dict) -> bool:
    """Check a short certification window under the changing water current."""
    fish, target, physics = dict(snapshot["fish"]), snapshot["target"], snapshot["physics"]
    remaining = max(3, int(physics["hold_ticks"]) - int(snapshot["hold"]) + 2)
    for tick in range(snapshot["tick"], snapshot["tick"] + remaining):
        if not _arrival(fish, target, physics):
            return False
        _step(fish, {channel: 0 for channel in CHANNELS}, physics, tick)
    return True


def _set_simplified(page, active: dict[str, int], desired: dict[str, int]) -> None:
    for channel in CHANNELS:
        value = int(desired[channel])
        if active.get(channel, 0) == value:
            continue
        page.locator(f'button[data-channel="{channel}"][data-value="{value}"]').click()
        active[channel] = value


def _set_full(page, active: dict[str, int], desired: dict[str, int]) -> None:
    for channel in CHANNELS:
        value = int(desired[channel])
        previous = int(active.get(channel, 0))
        if previous == value:
            continue
        if previous:
            page.keyboard.up(KEYS[(channel, previous)])
        if value:
            page.keyboard.down(KEYS[(channel, value)])
        active[channel] = value


def _release_full(page, active: dict[str, int]) -> None:
    for channel, value in list(active.items()):
        if value:
            page.keyboard.up(KEYS[(channel, value)])
        active[channel] = 0


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = _read(state_dir / "ground_truth.json")["challenge_id"]
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/result")) as received:
        page.locator("#lf-certify").click()
    result = received.value.json()
    assert result.get("passed") is False, result
    fresh = result.get("state", {}).get("challenge_id")
    assert fresh and fresh != before, "rejection did not replace the dive"
    page.locator(f'.lanternfin[data-challenge-id="{fresh}"]').wait_for(state="visible")
    page.locator(".lf-verdict.is-fresh").wait_for(state="visible")
    page.screenshot(path=str(out_dir / "lanternfin-fresh-failure.png"))
    page.locator(".lf-verdict.is-fresh").wait_for(state="hidden")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    del state_dir
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    first = _model(page)
    if not first:
        raise AssertionError("Lanternfin model was not rendered")
    interaction = first["interaction"]
    active = {channel: 0 for channel in CHANNELS}
    out_dir.mkdir(parents=True, exist_ok=True)
    # A small camera orbit is an ordinary inspection action. It changes only
    # the view, leaving the generated world and the replay contract untouched.
    page.mouse.move(490, 360)
    page.mouse.down()
    page.mouse.move(560, 338, steps=3)
    page.mouse.up()
    page.screenshot(path=str(out_dir / "lanternfin-orbit-initial.png"))
    settled = False
    for index in range(min(2000, int(first["physics"]["replay_tick_limit"]))):
        snapshot = _model(page)
        if not snapshot:
            raise AssertionError("Lanternfin model disappeared during solve")
        desired = {channel: 0 for channel in CHANNELS} if _coast_safe(snapshot) else _desired(snapshot)
        if interaction == "simplified":
            _set_simplified(page, active, desired)
        else:
            _set_full(page, active, desired)
        _wait(page, 82)
        current = _model(page)
        if index == 30:
            page.screenshot(path=str(out_dir / "lanternfin-approach.png"))
        if current and current["tick"] >= int(current["physics"]["replay_tick_limit"]):
            break
        if current:
            fish = current["fish"]
            target = current["target"]
            distance = math.sqrt(sum((float(fish[a]) - float(target[a])) ** 2 for a in ("x", "y", "z")))
            speed = math.sqrt(sum(float(fish[a]) ** 2 for a in ("vx", "vy", "vz")))
            if int(current.get("hold", 0)) >= int(current["physics"]["hold_ticks"]) and _coast_safe(current):
                # Neutralize the visible controls and require the hold to
                # survive one more physical tick before certifying. This
                # avoids turning a transient overlap into a false oracle
                # pass when a held key is released at the window boundary.
                if interaction == "full":
                    _release_full(page, active)
                else:
                    _set_simplified(page, active, {channel: 0 for channel in CHANNELS})
                _wait(page, 82)
                stable = _model(page)
                if stable and _coast_safe(stable) and int(stable.get("hold", 0)) >= int(stable["physics"]["hold_ticks"]):
                    settled = True
                    break
    if interaction == "full":
        _release_full(page, active)
    elif not settled:
        _set_simplified(page, active, {channel: 0 for channel in CHANNELS})
    assert settled, "controller did not produce a stable upright arrival"
    page.screenshot(path=str(out_dir / "lanternfin-settled.png"))
    page.locator("#lf-certify").click()
    expect(page.locator("#lanternfin-readout")).to_have_text("PASS", timeout=20_000)
