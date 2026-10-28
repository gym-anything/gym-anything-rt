from __future__ import annotations

import json
import time
from pathlib import Path

MECHANIC_ID = "letter_rapids_v2"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"))


def _band_midpoint(truth: dict, output: str, symbol: str) -> int:
    context = output[-1] if output else "^"
    row = truth["probability_rows"][context]
    floor = int(truth["simulation"]["display_band_floor_milli"])
    free = 10_000 - floor * len(row)
    widths = [floor + free * (int(item["end_milli"]) - int(item["start_milli"])) // 10_000 for item in row]
    for index in range(10_000 - sum(widths)):
        widths[index] += 1
    cursor = 0
    for item, width in zip(row, widths):
        if item["symbol"] == symbol:
            return cursor + width // 2
        cursor += width
    raise AssertionError(f"symbol {symbol!r} is missing from context {context!r}")


def _point_in_canvas(page, x_milli: int, y_milli: int, *, steps: int = 1) -> None:
    box = page.locator("#rapids-canvas").bounding_box()
    if box is None:
        raise AssertionError("letter canyon is not visible")
    page.mouse.move(
        box["x"] + box["width"] * x_milli / 10_000,
        box["y"] + box["height"] * y_milli / 10_000,
        steps=steps,
    )


def _set_proxy_value(page, selector: str, value: int, maximum: int) -> None:
    rail = page.locator(selector)
    box = rail.bounding_box()
    if box is None:
        raise AssertionError(f"simplified proxy axis {selector} is not visible")
    # Chromium's native range thumb has an eight-pixel radius; its value track
    # therefore runs between the two thumb centres rather than edge to edge.
    track_inset = min(8.0, box["width"] * .04)
    page.mouse.click(
        box["x"] + track_inset + (box["width"] - track_inset * 2) * value / maximum,
        box["y"] + box["height"] / 2,
    )


def _set_proxy_aim(page, y_milli: int) -> None:
    rail = page.locator("#rapids-aim")
    box = rail.bounding_box()
    if box is None:
        raise AssertionError("simplified letter rail is not visible")
    track_inset = min(8.0, box["height"] * .04)
    page.mouse.click(
        box["x"] + box["width"] / 2,
        box["y"] + track_inset + (box["height"] - track_inset * 2) * y_milli / 9_999,
    )


def _set_proxy_flow(page, x_milli: int) -> None:
    _set_proxy_value(page, "#rapids-flow", x_milli, 10_000)


def _wait_output(page, output: str, timeout: int = 8_000) -> None:
    # Reduce flow promptly after a commit, then aim the next channel while
    # the minimum current continues to advance.
    page.wait_for_function(
        "output => document.querySelector('.rapids-output-value')?.dataset.output === output",
        arg=output, polling=5, timeout=timeout,
    )


def _enter_symbol(page, truth: dict, output: str, symbol: str) -> str:
    y_milli = _band_midpoint(truth, output, symbol)
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    if interaction == "simplified":
        _set_proxy_aim(page, y_milli)
        _set_proxy_flow(page, 9_500)
        _wait_output(page, output + symbol)
        _set_proxy_flow(page, int(truth["simulation"]["neutral_x_milli"]))
    else:
        neutral = int(truth["simulation"]["neutral_x_milli"])
        _point_in_canvas(page, neutral, y_milli, steps=5)
        _point_in_canvas(page, 9_500, y_milli, steps=3)
        _wait_output(page, output + symbol)
        _point_in_canvas(page, neutral, y_milli)
    return output + symbol


def _wait_new(state_dir: Path, previous: str) -> None:
    deadline = time.time() + 25
    while time.time() < deadline:
        current = str(_read(state_dir / "ground_truth.json").get("challenge_id") or "")
        if current and current != previous:
            return
        time.sleep(.05)
    raise AssertionError("letter canyon did not regenerate after failure")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    from playwright.sync_api import expect

    if mechanic != MECHANIC_ID:
        raise AssertionError(mechanic)
    truth = _read(state_dir / "ground_truth.json")
    before = str(truth["challenge_id"])
    first = truth["target"][0]
    wrong = next(symbol for symbol in truth["alphabet"] if symbol != first)
    output = _enter_symbol(page, truth, "", wrong)
    _shot(page, out_dir, mechanic, "wrong-letter-committed")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    if interaction == "simplified":
        y_milli = _band_midpoint(truth, output, wrong)
        _set_proxy_aim(page, y_milli)
        _set_proxy_flow(page, 9_500)
    else:
        y_milli = _band_midpoint(truth, output, wrong)
        _point_in_canvas(page, 9_500, y_milli)
    expect(page.locator('.letter-rapids-v2[data-fresh-failure="true"]')).to_be_visible(timeout=25_000)
    _wait_new(state_dir, before)
    expect(page.locator(".rapids-foot .readout")).to_contain_text("FAIL")
    _shot(page, out_dir, mechanic, "fail-fresh-current")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    from playwright.sync_api import expect

    if mechanic != MECHANIC_ID:
        raise AssertionError(mechanic)
    truth = _read(state_dir / "ground_truth.json")
    output = ""
    target = str(truth["target"])
    for index, symbol in enumerate(target):
        output = _enter_symbol(page, truth, output, symbol)
        if index == max(1, len(target) // 2):
            _shot(page, out_dir, mechanic, "active-reflow")
    expect(page.locator(".rapids-foot .readout")).to_have_text("PASS", timeout=10_000)
    expect(page.locator('.letter-rapids-v2[data-terminal="pass"]')).to_be_visible()
    _shot(page, out_dir, mechanic, "pass")
    result = _read(state_dir / "result.json")
    if result.get("output") != target or result.get("terminal_reason") != "target":
        raise AssertionError("clean letter-canyon solve did not export the exact target")
    expected_source = {"full": "canyon_pointer", "simplified": "axis_proxy"}.get(
        str((truth.get("control_condition") or {}).get("interaction") or "")
    )
    if expected_source and {event.get("input_source") for event in result.get("events") or []} != {expected_source}:
        raise AssertionError("clean letter-canyon solve crossed interaction surfaces")
