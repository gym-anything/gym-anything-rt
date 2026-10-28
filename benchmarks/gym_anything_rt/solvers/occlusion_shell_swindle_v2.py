from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "occlusion_shell_swindle_v2"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _screenshot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def _wait_for_new_challenge(state_dir: Path, previous: str) -> str:
    deadline = time.time() + 8
    while time.time() < deadline:
        current = str(_read_json(state_dir / "ground_truth.json").get("challenge_id") or "")
        if current and current != previous:
            return current
        time.sleep(0.05)
    raise AssertionError("shell swindle did not regenerate after invalid certification")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = str(_read_json(state_dir / "ground_truth.json")["challenge_id"])
    page.locator(".shell-certify").click()
    _wait_for_new_challenge(state_dir, before)
    expect(page.locator(".occlusion-shell-v2-captcha[data-fresh-failure='true']")).to_be_visible(timeout=8_000)
    expect(page.locator(".readout")).to_contain_text("FAIL")
    _screenshot(page, out_dir, mechanic, "fail-refresh")


def _choose_relay(page, round_state: dict, *, cover_id: str | None = None) -> None:
    visible_ports = [round_state["inspection"], *(round_state.get("decoy_ports") or [])]
    relays = page.locator(".shell-inspection-relay")
    expect(relays).to_have_count(len(visible_ports))
    selected_cover = cover_id or str(round_state["inspection"]["occluder_id"])
    relay = page.locator(f'.shell-inspection-relay[data-cover-id="{selected_cover}"]')
    expect(relay).to_be_enabled()
    relay.click()


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read_json(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    for round_index, round_state in enumerate(truth["rounds"]):
        expect(page.locator(".shell-start-round")).to_be_enabled()
        page.locator(".shell-start-round").click()
        if interaction == "simplified":
            _choose_relay(page, round_state)
        else:
            stage = page.locator(".shell-stage").bounding_box()
            if not stage:
                raise AssertionError("shell theater is not visible")
            port = round_state["inspection"]["port"]
            page.mouse.move(stage["x"] + port[0] / truth["stage"]["width"] * stage["width"], stage["y"] + port[1] / truth["stage"]["height"] * stage["height"])
        handoff_tick = int(round_state["handoff"]["tick"])
        page.wait_for_function("tick => window.occlusionShellV2Model.tick >= tick", arg=handoff_tick, timeout=10_000)
        if round_index == 1:
            expect(page.locator('.shell-inspection-port[data-revealed="true"]')).to_be_visible()
            _screenshot(page, out_dir, mechanic, "active-physical-shuttle")
        page.wait_for_function("() => window.occlusionShellV2Model.mode === 'select'", timeout=12_000)
        if round_index == 0:
            _screenshot(page, out_dir, mechanic, "round-one-stop")
        carrier = str(round_state["final_carrier"])
        if interaction == "simplified":
            page.locator(f'.shell-proxy-select[data-shell-id="{carrier}"]').click()
        else:
            page.locator(f'.shell-piece[data-shell-id="{carrier}"]').click()
        if round_index < len(truth["rounds"]) - 1:
            page.wait_for_function("index => window.occlusionShellV2Model.roundIndex === index && window.occlusionShellV2Model.mode === 'ready'", arg=round_index + 1, timeout=4_000)
        else:
            page.wait_for_function("() => window.occlusionShellV2Model.mode === 'certify'", timeout=4_000)

    physical = page.evaluate("""() => ({
      rounds: window.occlusionShellV2Model.roundIndex,
      choices: window.occlusionShellV2Model.choices,
      ticks: window.occlusionShellV2Model.totalTicks,
      observed: window.occlusionShellV2Model.observedMs,
      inspections: window.occlusionShellV2Model.inspectionSamples,
      rewinds: window.occlusionShellV2Model.rewindCount,
    })""")
    expected_ticks = sum(int(item["frame_count"]) for item in truth["rounds"])
    minimum_inspections = sum(int(item["inspection"]["minimum_samples"]) for item in truth["rounds"])
    expected_rounds = len(truth["rounds"])
    expected_observation = sum(int(item["preview_ms"]) + int(item["duration_ms"]) for item in truth["rounds"])
    if physical["rounds"] != expected_rounds or len(physical["choices"]) != expected_rounds or physical["ticks"] != expected_ticks or physical["observed"] < expected_observation or physical["inspections"] < minimum_inspections or physical["rewinds"] != 0:
        raise AssertionError(f"physical shell observation ended unexpectedly: {physical}")
    _screenshot(page, out_dir, mechanic, "three-tracks-sealed")
    page.locator(".shell-certify").click()
    expect(page.locator(".readout")).to_have_text("PASS", timeout=8_000)
