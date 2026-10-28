from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "clockwork_clutch_safe_v2"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    page.locator("#clutch2-drive").click()
    page.wait_for_function("() => window.clockworkClutchSafeV2Model.tick >= 2")
    page.locator("#clutch2-abandon").click()
    expect(page.locator(".ivv2-verdict.is-fresh")).to_be_visible(timeout=8_000)
    deadline = time.time() + 8
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json")["challenge_id"]) != before:
            break
        time.sleep(.05)
    else:
        raise AssertionError(f"{mechanic} failure did not issue a fresh challenge")
    page.wait_for_timeout(300)
    expect(page.locator("#clutch2-tick")).to_contain_text("0/")
    _shot(page, out_dir, mechanic, "fail-fresh")
    expect(page.locator(".ivv2-verdict.is-fresh")).to_be_hidden(timeout=3_000)


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")

    def prepare_lever(shaft: int):
        lever = page.locator(f'[data-clutch-lever="{shaft}"]')
        handle = lever.locator(".clutch-lever-handle")
        rail = lever.locator(".clutch-lever-rail")
        handle_box = handle.bounding_box()
        rail_box = rail.bounding_box()
        if not handle_box or not rail_box:
            raise AssertionError(f"clutch {shaft} has no draggable lever geometry")
        page.mouse.move(handle_box["x"] + handle_box["width"] / 2, handle_box["y"] + handle_box["height"] / 2)
        page.mouse.down()
        page.mouse.move(rail_box["x"] + rail_box["width"] - handle_box["width"] / 2 - 4, rail_box["y"] + rail_box["height"] / 2)
        return lever

    def release_lever(lever) -> None:
        page.mouse.up()
        expect(lever).to_have_attribute("data-state", "free")

    _shot(page, out_dir, mechanic, "initial-coupled-train")
    page.locator("#clutch2-drive").click()
    # The reference solver knows the generated `release_schedule` (the exact
    # tick, not the wobble curve itself) so it can brake at the intended
    # instant, exactly like the V1 clockwork solver. It still performs only
    # ordinary pointer/keyboard actions against the live wobbling animation;
    # it does not read or special-case the wobble anchors.
    for schedule_index, item in enumerate(truth["release_schedule"]):
        target_tick = int(item["tick"])
        shaft = int(item["shaft"])
        page.wait_for_function(
            "target => window.clockworkClutchSafeV2Model?.tick >= target",
            arg=target_tick,
            polling=4,
            timeout=60_000,
        )
        page.locator("#clutch2-brake").click(force=True)
        page.wait_for_function("() => window.clockworkClutchSafeV2Model.running === false", polling=50)
        stopped_tick = int(page.evaluate("() => window.clockworkClutchSafeV2Model.tick"))
        if stopped_tick != target_tick:
            raise AssertionError(f"clockwork brake missed release tick {target_tick}; stopped at {stopped_tick}")
        if interaction == "full":
            lever = prepare_lever(shaft)
            release_lever(lever)
        else:
            page.locator(f'[data-clutch="{shaft}"]').click()
        if schedule_index == 0:
            _shot(page, out_dir, mechanic, "first-release-load-redistributed")
        if schedule_index + 1 < len(truth["release_schedule"]):
            page.locator("#clutch2-drive").click()
    _shot(page, out_dir, mechanic, f"{len(truth['release_schedule'])}-phases-braked")
    page.locator("#clutch2-unlock").click()
