from __future__ import annotations

import json
import time
from pathlib import Path


MECHANIC_ID = "rotating_keyboard_v2"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def _wait_fresh(state_dir: Path, previous: str) -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        if _read(state_dir / "ground_truth.json").get("challenge_id") != previous:
            return
        time.sleep(0.05)
    raise AssertionError("rotating-keyboard-v2 failure did not issue a fresh challenge")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str = MECHANIC_ID) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = _read(state_dir / "ground_truth.json")["challenge_id"]
    page.locator("#submit-rotating-v2").click()
    page.wait_for_function("() => document.querySelector('.readout')?.textContent === 'FAIL'", polling=50, timeout=5_000)
    _wait_fresh(state_dir, before)
    _shot(page, out_dir, mechanic, "fail-refresh")


def _click_moving_key(page, key: str, expected_length: int) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        box = page.locator(f'.rkv2-key[data-key="{key}"]').bounding_box()
        if box and box["width"] > 8 and box["height"] > 8:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            length = int(page.evaluate("rotatingKeyboardV2Model.input.length"))
            if length == expected_length:
                return
            if length > expected_length:
                # A projected bounding-box centre can land on a neighbour while
                # the plane is steeply turned; erase it and keep tracking.
                erase = page.locator('.rkv2-key[data-key="BACKSPACE"]').bounding_box()
                if erase and erase["width"] > 8 and erase["height"] > 8:
                    page.mouse.click(erase["x"] + erase["width"] / 2, erase["y"] + erase["height"] / 2)
        page.wait_for_timeout(60)
    raise AssertionError(f"could not physically click moving key {key}")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str = MECHANIC_ID) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    target = truth["target"]
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    if interaction == "simplified":
        for key in target:
            page.keyboard.press(key)
            page.wait_for_timeout(60)
    else:
        # Coordinate clicks throughout: an immediate-motion profile has no
        # stable element for Playwright's actionability wait to settle on.
        for index, key in enumerate(target, start=1):
            _click_moving_key(page, key, index)
    if page.evaluate("rotatingKeyboardV2Model.input") != target:
        raise AssertionError("rotating keyboard V2 input does not match target")
    _shot(page, out_dir, mechanic, "solved-state")
    page.locator("#submit-rotating-v2").click()
    page.wait_for_function("() => document.querySelector('.readout')?.textContent === 'PASS'", polling=50, timeout=10_000)
