from __future__ import annotations

import json
import math
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "horizon_relay_v2"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{MECHANIC_ID}-{label}.png"))


def _snapshot(page) -> dict:
    return page.evaluate("() => window.horizonRelayV2Model.snapshot()")


def _stage_point(page, point: dict[str, float]) -> tuple[float, float]:
    box = page.locator("#horizon-relay-v2-stage").bounding_box()
    if box is None:
        raise AssertionError("horizon relay stage has no bounding box")
    return box["x"] + float(point["x"]) * box["width"] / 800, box["y"] + float(point["y"]) * box["height"] / 560


def _drag_dish(page, snapshot: dict, station_id: str, craft_id: str) -> None:
    start = _stage_point(page, snapshot["stationPoints"][station_id])
    end = _stage_point(page, snapshot["craftPoints"][craft_id])
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(*end, steps=5)
    page.mouse.up()


def _choose_pair(snapshot: dict) -> tuple[str, str] | None:
    done = set(snapshot.get("completed") or [])
    pairs = [(str(station), str(craft)) for station, craft in snapshot.get("pairs") or [] if str(craft) not in done]
    if not pairs:
        return None
    return pairs[0]


def _aim(page, snapshot: dict, station_id: str, craft_id: str, interaction: str) -> None:
    if interaction == "simplified":
        for selector in (f'[data-station-button="{station_id}"]', f'[data-target-button="{craft_id}"]'):
            box = page.locator(selector).bounding_box()
            if box:
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    else:
        _drag_dish(page, snapshot, station_id, craft_id)


def _run(page, out_dir: Path) -> None:
    first_photo = False
    last_refresh: tuple[str, str, int] | None = None
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        snapshot = _snapshot(page)
        if len(snapshot.get("completed") or []) >= len(snapshot.get("progress") or {}):
            break
        interaction = str(page.locator(".hr-shell").get_attribute("data-interaction") or "full")
        active = snapshot.get("active")
        if active:
            station_id, craft_id = str(active["stationId"]), str(active["craftId"])
            tick = int(snapshot["tick"])
            # Refresh sooner than half the configured angular tolerance. This
            # is an ordinary closed-loop correction from the rendered globe.
            speed = float(page.evaluate("() => window.horizonRelayV2Model.speed"))
            tolerance = float(page.evaluate("() => window.horizonRelayV2Model.tolerance"))
            refresh_ticks = max(2, int(tolerance / max(.01, speed) / 3.2))
            if last_refresh is None or last_refresh[:2] != (station_id, craft_id) or tick - last_refresh[2] >= refresh_ticks:
                _aim(page, snapshot, station_id, craft_id, interaction)
                last_refresh = (station_id, craft_id, tick)
                if not first_photo:
                    _shot(page, out_dir, "active-relay-and-horizon")
                    first_photo = True
        else:
            pair = _choose_pair(snapshot)
            if pair is None:
                break
            station_id, craft_id = pair
            _aim(page, snapshot, station_id, craft_id, interaction)
            if interaction == "simplified":
                page.locator("#hr-hold").click()
            last_refresh = (station_id, craft_id, int(snapshot["tick"]))
        if page.evaluate("() => Boolean(window.GymAnythingRTTime?.status && GymAnythingRTTime.status().mode === 'paused')"):
            page.evaluate("() => window.GymAnythingRTTime.resume()")
            page.wait_for_timeout(520)
            page.evaluate("() => window.GymAnythingRTTime.pause()")
        else:
            page.wait_for_timeout(45)
    _shot(page, out_dir, "before-certify")
    page.locator("#hr-certify").click()
    expect(page.locator(".hr-readout")).to_contain_text("PASS", timeout=12_000)
    _shot(page, out_dir, "solved")


def _wait_for_new_challenge(state_dir: Path, previous: str) -> str:
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        current = str(_read(state_dir / "ground_truth.json").get("challenge_id") or "")
        if current and current != previous:
            return current
        time.sleep(.05)
    raise AssertionError("horizon relay did not regenerate after a failed certification")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = str(_read(state_dir / "ground_truth.json").get("challenge_id") or "")
    _shot(page, out_dir, "failure-initial")
    page.locator("#hr-certify").click()
    _wait_for_new_challenge(state_dir, before)
    expect(page.locator(".hr-shell")).to_be_visible(timeout=10_000)
    _shot(page, out_dir, "failure-recovered-new-world")
    _run(page, out_dir)


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    del state_dir
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    expect(page.locator(".hr-shell")).to_be_visible(timeout=10_000)
    _shot(page, out_dir, "initial")
    _run(page, out_dir)
