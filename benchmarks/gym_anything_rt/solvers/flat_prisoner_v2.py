from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "flat_prisoner_v2"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _screenshot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"))


def _wait_for_new_challenge(state_dir: Path, previous: str) -> str:
    deadline = time.time() + 8
    while time.time() < deadline:
        current = str(_read_json(state_dir / "ground_truth.json").get("challenge_id") or "")
        if current and current != previous:
            return current
        time.sleep(.05)
    raise AssertionError("flat prison did not regenerate after terminal failure")


def _click_many(page, selector: str, count: int, *, out_dir: Path | None = None, label: str | None = None) -> None:
    for index in range(count):
        page.locator(selector).click()
        page.wait_for_timeout(30)
        if out_dir is not None and label and index == max(0, count // 2):
            _screenshot(page, out_dir, MECHANIC_ID, label)


def _direct_drag_step(page, box: dict, dx: float, dy: float) -> None:
    x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy)
    page.mouse.up()


def _align_camera(page, truth: dict, out_dir: Path) -> None:
    initial = truth["initial_camera"]
    target = truth["solution"]["camera"]
    controls = truth["controls"]
    orbit = float(controls["orbit_step_deg"])
    pan = float(controls["pan_step"])
    dolly = float(controls["dolly_step"])
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")

    yaw_steps = round((float(target["yaw_deg"]) - float(initial["yaw_deg"])) / orbit)
    pitch_steps = round((float(target["pitch_deg"]) - float(initial["pitch_deg"])) / orbit)
    x_steps = round((float(target["target"][0]) - float(initial["target"][0])) / pan)
    y_steps = round((float(target["target"][1]) - float(initial["target"][1])) / pan)
    dolly_steps = round((float(target["distance"]) - float(initial["distance"])) / dolly)
    if interaction == "simplified":
        _click_many(page, "#orbit-right" if yaw_steps > 0 else "#orbit-left", abs(yaw_steps), out_dir=out_dir, label="active-camera-orbit")
        _click_many(page, "#orbit-down" if pitch_steps > 0 else "#orbit-up", abs(pitch_steps))
        _click_many(page, "#pan-right" if x_steps > 0 else "#pan-left", abs(x_steps))
        _click_many(page, "#pan-up" if y_steps > 0 else "#pan-down", abs(y_steps))
        _click_many(page, "#dolly-out" if dolly_steps > 0 else "#dolly-in", abs(dolly_steps))
    else:
        box = page.locator("#flat-prison-canvas").bounding_box()
        if not box:
            raise AssertionError("flat-prison canvas is not visible")
        for index in range(abs(yaw_steps)):
            _direct_drag_step(page, box, (1 if yaw_steps > 0 else -1) * orbit / 0.12, 0)
            if index == max(0, abs(yaw_steps) // 2):
                _screenshot(page, out_dir, MECHANIC_ID, "active-camera-orbit")
        for _ in range(abs(pitch_steps)):
            _direct_drag_step(page, box, 0, (1 if pitch_steps > 0 else -1) * orbit / 0.12)
        page.locator('[data-drag-mode="pan"]').click()
        for _ in range(abs(x_steps)):
            _direct_drag_step(page, box, -(1 if x_steps > 0 else -1) * pan / 0.018, 0)
        for _ in range(abs(y_steps)):
            _direct_drag_step(page, box, 0, (1 if y_steps > 0 else -1) * pan / 0.018)
        page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
        for _ in range(abs(dolly_steps)):
            page.mouse.wheel(0, 1 if dolly_steps > 0 else -1)
            page.wait_for_timeout(30)
    page.wait_for_timeout(90)

    camera = page.evaluate("() => window.flatPrisonerV2Model.camera")
    audit = page.evaluate("""() => ({
      valid: window.flatPrisonerV2Model.topology.valid,
      joins: window.flatPrisonerV2Model.topology.joins.length,
      cameraEvents: window.flatPrisonerV2Model.cameraEventCount,
    })""")
    if not audit["valid"] or audit["joins"] < int(truth["requirements"]["minimum_screen_joins"]):
        raise AssertionError(f"aligned camera did not create a qualifying projection: {audit}; camera={camera}; reference={target}")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = str(_read_json(state_dir / "ground_truth.json")["challenge_id"])
    page.locator("#abandon-flat").click()
    _wait_for_new_challenge(state_dir, before)
    expect(page.locator(".flat-prison-verdict.is-fail")).to_be_visible(timeout=8_000)
    expect(page.locator(".readout")).to_contain_text("FAIL")
    _screenshot(page, out_dir, mechanic, "dominant-fail-refresh")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    page.wait_for_timeout(1_450)
    expect(page.locator(".flat-prison-verdict.is-fresh")).to_have_count(0)
    truth = _read_json(state_dir / "ground_truth.json")

    _align_camera(page, truth, out_dir)
    _screenshot(page, out_dir, mechanic, "successful-camera-topology")
    page.locator("#freeze-view").click()
    expect(page.locator('.flat-prisoner[data-mode="flat"]')).to_be_visible()
    _screenshot(page, out_dir, mechanic, "successful-frozen-topology")

    thresholds = page.evaluate("""() => {
      const segments = window.flatPrisonerV2Model.topology.segments;
      const byId = id => segments.find(segment => segment.id === id);
      return [byId('surface-02').right - 35, byId('surface-04').right - 35];
    }""")
    page.keyboard.down("ArrowRight")
    for index, threshold in enumerate(thresholds):
        page.wait_for_function(
            "threshold => window.flatPrisonerV2Model.prisoner.x >= threshold && window.flatPrisonerV2Model.prisoner.grounded",
            arg=threshold,
            timeout=8_000,
        )
        page.keyboard.down("Space")
        page.wait_for_timeout(95)
        if index == 0:
            _screenshot(page, out_dir, mechanic, "active-prisoner-jump")
        page.keyboard.up("Space")
    page.wait_for_function("() => window.flatPrisonerV2Model.prisoner?.reached === true", timeout=10_000)
    # Once reached, physics deliberately latches the prisoner at the exit.
    # Keep Right held briefly so a replay on a different browser timer cannot
    # release one tick before the exit-radius test.
    page.wait_for_timeout(400)
    page.keyboard.up("ArrowRight")
    physical = page.evaluate("""() => ({
      reached: window.flatPrisonerV2Model.prisoner.reached,
      alive: window.flatPrisonerV2Model.prisoner.alive,
      ticks: window.flatPrisonerV2Model.prisoner.tick,
      jumps: window.flatPrisonerV2Model.prisoner.jumps,
      transitions: window.flatPrisonerV2Model.prisoner.transitions,
      cameraEvents: window.flatPrisonerV2Model.cameraEventCount,
      freezes: window.flatPrisonerV2Model.freezeCount,
      thaws: window.flatPrisonerV2Model.thawCount,
      deaths: window.flatPrisonerV2Model.deathCount,
    })""")
    requirements = truth["requirements"]
    if not physical["reached"] or not physical["alive"] or physical["ticks"] < int(requirements["minimum_traversal_ticks"]) or physical["jumps"] < int(requirements["minimum_jumps"]) or physical["transitions"] < int(requirements["minimum_key_transitions"]) or physical["freezes"] != 1 or physical["thaws"] != 0 or physical["deaths"] != 0:
        raise AssertionError(f"flat-prison clean physical workflow was incomplete: {physical}")
    _screenshot(page, out_dir, mechanic, "exit-reached-before-certification")
    page.locator("#certify-escape").click()
    expect(page.locator(".readout")).to_have_text("PASS", timeout=10_000)
    expect(page.locator(".readout")).to_have_attribute("data-status", "passed")
    expect(page.locator(".flat-prison-verdict.is-pass")).to_be_visible()
