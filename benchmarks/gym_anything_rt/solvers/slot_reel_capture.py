from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "slot_reel_capture"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def _wait_fresh(page, state_dir: Path, previous: str) -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        truth = _read(state_dir / "ground_truth.json")
        visible = page.locator(".slot-captcha").get_attribute("data-challenge-id")
        if truth.get("challenge_id") != previous and visible == truth.get("challenge_id"):
            return
        time.sleep(0.05)
    raise AssertionError("slot-reel failure did not issue and render a fresh challenge")


def _wait_for_capture_window(page, reel_id: str, target: str, *, target_visible: bool) -> None:
    page.wait_for_function(
        """({reelId, target, targetVisible}) => {
          const reel = document.querySelector(`.slot-reel[data-reel-id="${CSS.escape(reelId)}"]`);
          if (!reel) return false;
          const data = slotModel.state.reels.find((item) => item.id === reelId);
          if (!data) return false;
          const symbol = reel.querySelector(".slot-symbol")?.textContent || "";
          const visible = symbol === target;
          const elapsed = performance.now() - slotModel.startedAt;
          const cyclePosition = (elapsed % data.interval_ms) / data.interval_ms;
          const tokenIndex = (
            Math.floor(elapsed / data.interval_ms) + Number(data.phase || 0)
          ) % data.tokens.length;
          const currentToken = data.tokens[tokenIndex];
          const remaining = data.interval_ms - (elapsed % data.interval_ms);
          const ratio = Number(slotModel.state.capture_window_ratio || 1);
          const safelyTimed = ratio < 1
            ? Math.abs(cyclePosition - 0.5) < ratio * 0.18
            : remaining > Math.max(120, data.interval_ms * 0.45);
          return reel.dataset.active === "true"
            && reel.dataset.captureReady !== "false"
            && safelyTimed
            && (
              targetVisible
                ? visible && currentToken === target
                : !visible && currentToken !== target
            );
        }""",
        arg={"reelId": reel_id, "target": target, "targetVisible": target_visible},
        timeout=12_000,
        polling=10,
    )


def _click_capture_button(page) -> None:
    button = page.locator("#capture-slot")
    if not button.is_visible():
        raise AssertionError("slot-reel simplified capture button is not visible")
    button.click(force=True)


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    before = str(truth["challenge_id"])
    condition = truth.get("control_condition") or {}
    interaction = str(condition.get("interaction") or "full")
    max_strikes = int(truth["max_strikes"])
    _shot(page, out_dir, mechanic, "initial")
    attempts = 0
    recoverable_captured = False
    while int(page.evaluate("slotModel.wrongKeys")) < max_strikes:
        attempts += 1
        if attempts > max_strikes * 4:
            raise AssertionError("slot-reel deliberate failure could not exhaust the visible strike budget")
        before_wrong = int(page.evaluate("slotModel.wrongKeys"))
        frozen_count = int(page.evaluate("slotModel.frozen.length"))
        reel_id = str(truth["reel_ids"][frozen_count])
        target = str(truth["sequence"][frozen_count])
        if interaction == "simplified":
            _wait_for_capture_window(page, reel_id, target, target_visible=False)
            _click_capture_button(page)
        else:
            wrong_key = "A" if target != "A" else "B"
            page.keyboard.press(wrong_key)
        page.wait_for_function(
            "({wrong, frozen}) => slotModel.wrongKeys > wrong || slotModel.frozen.length > frozen",
            arg={"wrong": before_wrong, "frozen": frozen_count},
            timeout=2000,
        )
        current_wrong = int(page.evaluate("slotModel.wrongKeys"))
        if current_wrong < max_strikes:
            expect(page.locator(".slot-strikes-count")).to_have_text(f"{current_wrong}/{max_strikes}")
        if current_wrong == 1 and max_strikes > 1 and not recoverable_captured:
            _shot(page, out_dir, mechanic, "recoverable-strike")
            recoverable_captured = True
    page.wait_for_function(
        "() => slotModel.submitting || document.querySelector('.readout')?.dataset.status === 'error'",
        timeout=3000,
    )
    _wait_fresh(page, state_dir, before)
    expect(page.locator(".readout")).to_have_attribute("data-status", "error", timeout=5000)
    _shot(page, out_dir, mechanic, "fail-refresh")
    attempts_path = state_dir / "attempts.jsonl"
    attempts = [
        json.loads(line)
        for line in attempts_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if attempts_path.is_file() else []
    if not attempts:
        raise AssertionError("slot-reel server did not archive the failed attempt")
    _write(out_dir / f"{mechanic}-failed-attempt.json", attempts[-1])


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    for index, (reel_id, target) in enumerate(zip(truth["reel_ids"], truth["sequence"])):
        _wait_for_capture_window(page, str(reel_id), str(target), target_visible=True)
        if interaction == "simplified":
            _click_capture_button(page)
        else:
            page.keyboard.press(str(target))
        expect(page.locator('.slot-reel[data-frozen="true"]')).to_have_count(index + 1, timeout=2000)
        if index == max(0, len(truth["reel_ids"]) // 2 - 1):
            _shot(page, out_dir, mechanic, "active")
    if page.evaluate("slotModel.captured") != truth["sequence"]:
        raise AssertionError("slot-reel captured sequence does not match the generated target")
    if int(page.evaluate("slotModel.wrongKeys")) != 0:
        raise AssertionError("slot-reel passing attempt contains a hidden strike")
    _shot(page, out_dir, mechanic, "solved-state")
    page.locator("#submit-slot").click()
    expect(page.locator(".readout")).to_have_attribute("data-status", "passed", timeout=5000)
    _shot(page, out_dir, mechanic, "pass")
    _write(out_dir / f"{mechanic}-pass-result.json", _read(state_dir / "result.json"))
