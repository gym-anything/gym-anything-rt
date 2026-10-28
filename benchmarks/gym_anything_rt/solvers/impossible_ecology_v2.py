from __future__ import annotations

import json
import math
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "impossible_ecology_v2"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def _wait(page, milliseconds: int) -> None:
    """Use the repository clock when validating its paused observation mode."""
    paused = page.evaluate("() => window.GymAnythingRTTime?.status().mode === 'paused'")
    if paused:
        page.evaluate("ms => GymAnythingRTTime.runFor(ms)", milliseconds)
        deadline = time.monotonic() + milliseconds / 1000 + 10
        while page.evaluate("GymAnythingRTTime.status().phase") != "completed":
            if time.monotonic() >= deadline:
                raise AssertionError("paused ecology observation window did not finish")
            time.sleep(.01)
    else:
        page.wait_for_timeout(milliseconds)


def _wait_new(state_dir: Path, before: str) -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json").get("challenge_id")) != before:
            return
        time.sleep(.05)
    raise AssertionError("coupled ecology did not regenerate after failure")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(mechanic)
    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    page.locator(".eco-submit").click()
    _wait_new(state_dir, before)
    expect(page.locator(".impossible-ecology-v2-captcha[data-fresh-failure='true']")).to_be_visible(timeout=8_000)
    expect(page.locator(".readout")).to_contain_text("FAIL")
    _shot(page, out_dir, mechanic, "fail-refresh")


def _screen(box: dict, arena: dict, point: tuple[float, float] | list[float]) -> tuple[float, float]:
    return box["x"] + float(point[0]) / arena["width"] * box["width"], box["y"] + float(point[1]) / arena["height"] * box["height"]


def _live(page, organism_id: str) -> dict:
    return page.evaluate("""id => { const item=window.impossibleEcologyV2Model.organisms[id]; return {x:item.x,y:item.y,vx:item.vx,vy:item.vy,captured:item.captured,tick:window.impossibleEcologyV2Model.tick}; }""", organism_id)


def _herd(page, truth: dict, box: dict, organism: dict) -> None:
    target = next(item for item in truth["targets"] if item["organism_id"] == organism["id"])
    primary = max(organism["responses"], key=lambda field: abs(float(organism["responses"][field])))
    sign = 1 if float(organism["responses"][primary]) > 0 else -1
    page.locator(f'[data-field="{primary}"]').click()
    state = _live(page, organism["id"])
    if state["captured"]:
        return
    pointer_is_down = False
    try:
        for _ in range(190):
            state = _live(page, organism["id"])
            if state["captured"]:
                return
            dx, dy = float(target["center"][0]) - state["x"], float(target["center"][1]) - state["y"]
            remaining = math.hypot(dx, dy)
            ux, uy = (dx / remaining, dy / remaining) if remaining > 1e-6 else (1.0, 0.0)
            if sign > 0:
                lure = [float(target["center"][0]) + ux * 62, float(target["center"][1]) + uy * 62]
            else:
                lure = [state["x"] - ux * 142, state["y"] - uy * 142]
            lure[0] = max(4, min(float(truth["arena"]["width"]) - 4, lure[0]))
            lure[1] = max(4, min(float(truth["arena"]["height"]) - 4, lure[1]))
            point = _screen(box, truth["arena"], lure)
            if not pointer_is_down:
                page.mouse.move(*point, steps=8)
                page.mouse.down()
                pointer_is_down = True
            else:
                page.mouse.move(*point, steps=3)
            _wait(page, 105)
        raise AssertionError(f"organism {organism['id']} did not reach its sanctuary: {_live(page, organism['id'])}")
    finally:
        if pointer_is_down:
            page.mouse.up()
            _wait(page, 90)


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(mechanic)
    truth = _read(state_dir / "ground_truth.json")
    expect(page.locator(".impossible-ecology-v2-captcha")).to_be_visible(timeout=8_000)
    page.locator(".eco-calibrate").click()
    _wait(page, 720)
    _shot(page, out_dir, mechanic, "active-calibration-film")
    _wait(page, int(truth["controls"]["calibration_field_ms"]) * len(truth["fields"]) + 50)
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    surface = page.locator(".eco-arena" if interaction == "full" else ".eco-coordinate-pad")
    box = surface.bounding_box()
    if not box:
        raise AssertionError("coupled ecology field-lure surface is not visible")

    # Start with the organisms whose primary responses are strongest so their
    # coupled motion is removed from the live field first.
    organisms = sorted(truth["organisms"], key=lambda item: -max(abs(float(value)) for value in item["responses"].values()))
    for index, organism in enumerate(organisms):
        if not _live(page, organism["id"])["captured"]:
            _herd(page, truth, box, organism)
        captured = int(page.locator(".impossible-ecology-v2-captcha").get_attribute("data-captured") or "0")
        if index == 1:
            _shot(page, out_dir, mechanic, "active-coupled-herding")
        if captured >= 4 and not (out_dir / f"{mechanic}-four-sanctuaries.png").exists():
            _shot(page, out_dir, mechanic, "four-sanctuaries")

    expect(page.locator(".eco-complete[data-visible='true']")).to_be_visible(timeout=8_000)
    final = page.evaluate("""() => ({captured:Object.values(window.impossibleEcologyV2Model.organisms).filter(x=>x.captured).length,completed:window.impossibleEcologyV2Model.completed,tick:window.impossibleEcologyV2Model.tick,resets:window.impossibleEcologyV2Model.resets,drags:window.impossibleEcologyV2Model.pointerDrags})""")
    if final["captured"] != len(truth["organisms"]) or not final["completed"] or final["resets"] != 0 or final["drags"] < 1:
        raise AssertionError(f"coupled ecology clean solve incomplete: {final}")
    _shot(page, out_dir, mechanic, "stable-all-sanctuaries")
    page.locator(".eco-submit").click()
    expect(page.locator(".readout")).to_have_text("PASS", timeout=10_000)
