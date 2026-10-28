from __future__ import annotations

import io
import json
import math
import re
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect


MECHANIC_ID = "impossible_panorama"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def _wait_fresh(state_dir: Path, previous: str) -> str:
    deadline = time.time() + 8
    while time.time() < deadline:
        current = str(_read(state_dir / "ground_truth.json").get("challenge_id") or "")
        if current and current != previous:
            return current
        time.sleep(0.05)
    raise AssertionError("panorama failure did not issue a fresh challenge")


def _camera(page) -> tuple[float, float, float]:
    root = page.locator(".impossible-panorama")
    return (
        float(root.get_attribute("data-camera-x") or 0),
        float(root.get_attribute("data-camera-y") or 0),
        float(root.get_attribute("data-zoom") or 0),
    )


def _move_camera(page, destination: dict, *, tolerance: float = 16.0) -> None:
    interaction = page.locator(".impossible-panorama").get_attribute("data-interaction") or "legacy"
    if interaction == "simplified":
        _move_camera_with_pan_pad(page, destination, tolerance=tolerance)
        return
    canvas = page.locator("#panorama-canvas")
    box = canvas.bounding_box()
    if not box:
        raise AssertionError("panorama canvas has no physical geometry")
    origin_x = box["x"] + box["width"] / 2
    origin_y = box["y"] + box["height"] / 2
    for _ in range(90):
        camera_x, camera_y, zoom = _camera(page)
        delta_x = float(destination["x"]) - camera_x
        delta_y = float(destination["y"]) - camera_y
        if math.hypot(delta_x, delta_y) <= tolerance:
            return
        drag_x = max(-118.0, min(118.0, -delta_x * zoom * box["width"] / 820.0))
        drag_y = max(-88.0, min(88.0, -delta_y * zoom * box["height"] / 450.0))
        page.mouse.move(origin_x, origin_y)
        page.mouse.down()
        page.mouse.move(origin_x + drag_x, origin_y + drag_y, steps=6)
        page.mouse.up()
    raise AssertionError(f"could not physically pan to {destination}; camera ended at {_camera(page)}")


def _move_camera_with_pan_pad(page, destination: dict, *, tolerance: float) -> None:
    """Use the visible coarse/fine proxy pad, including its final reticle trim."""
    root = page.locator(".impossible-panorama")
    scale = page.locator("#panorama-pan-scale")
    if scale.inner_text().startswith("COARSE"):
        scale.click()
    for _ in range(480):
        camera_x, camera_y, _zoom = _camera(page)
        delta_x = float(destination["x"]) - camera_x
        delta_y = float(destination["y"]) - camera_y
        if math.hypot(delta_x, delta_y) <= tolerance:
            return
        if abs(delta_x) >= abs(delta_y):
            direction = "right" if delta_x > 0 else "left"
        else:
            direction = "down" if delta_y > 0 else "up"
        page.locator(f'[data-pan="{direction}"]').click()
    raise AssertionError(f"could not proxy-pan to {destination}; camera ended at {_camera(page)}")


def _set_zoom(page, target: float, truth: dict) -> None:
    interaction = page.locator(".impossible-panorama").get_attribute("data-interaction") or "legacy"
    controls = truth["controls"]
    minimum = float(controls["zoom_min"])
    step = float(controls["zoom_step"])
    presses = round((target - minimum) / step)
    if interaction == "full":
        slider = page.locator("#panorama-zoom-slider")
        slider.focus()
        page.keyboard.press("Home")
        for _ in range(presses):
            page.keyboard.press("ArrowRight")
    else:
        current = _camera(page)[2]
        button = "#panorama-zoom-in" if target >= current else "#panorama-zoom-out"
        for _ in range(abs(round((target - current) / step))):
            page.locator(button).click()
    expect(page.locator(".impossible-panorama")).to_have_attribute("data-zoom", f"{target:.2f}".rstrip("0").rstrip("."))


def _set_focus(page, target: int, truth: dict) -> None:
    interaction = page.locator(".impossible-panorama").get_attribute("data-interaction") or "legacy"
    if interaction == "simplified":
        current = int(page.locator(".impossible-panorama").get_attribute("data-focus") or 0)
        selector = "#panorama-focus-far" if target >= current else "#panorama-focus-near"
        for _ in range(abs(target - current)):
            page.locator(selector).click()
    else:
        focus = page.locator("#panorama-focus-slider")
        focus.focus()
        page.keyboard.press("Home")
        for _ in range(target):
            page.keyboard.press("ArrowRight")
    expect(page.locator(".impossible-panorama")).to_have_attribute("data-focus", str(target))


def _ring_present(canvas) -> bool:
    image = Image.open(io.BytesIO(canvas.screenshot())).convert("RGB")
    center_x, center_y = image.width // 2, image.height // 2
    cyan = 0
    for red, green, blue in image.crop((center_x - 72, center_y - 72, center_x + 72, center_y + 72)).getdata():
        if red < 165 and green > 185 and blue > 180 and green - red > 45 and blue - red > 35:
            cyan += 1
    return cyan >= 32


def _cyan_event_center(canvas) -> tuple[float, float] | None:
    image = Image.open(io.BytesIO(canvas.screenshot())).convert("RGB")
    center_x, center_y = image.width // 2, image.height // 2
    left, top = max(0, center_x - 120), max(0, center_y - 120)
    crop = image.crop((left, top, min(image.width, center_x + 120), min(image.height, center_y + 120)))
    points = []
    for index, (red, green, blue) in enumerate(crop.getdata()):
        if red < 175 and green > 185 and blue > 180 and green - red > 48 and blue - red > 38:
            points.append((left + index % crop.width, top + index // crop.width))
    if len(points) < 32:
        return None
    return (
        sum(x for x, _y in points) / len(points),
        sum(y for _x, y in points) / len(points),
    )


def _center_visible_event(page) -> None:
    """Trim the reticle against the cyan event the same way a viewer can."""
    canvas = page.locator("#panorama-canvas")
    interaction = page.locator(".impossible-panorama").get_attribute("data-interaction") or "legacy"
    center = _cyan_event_center(canvas)
    if center is None:
        return
    box = canvas.bounding_box()
    if not box:
        return
    # Locator screenshots use the displayed canvas dimensions. Compare their
    # pixels with the displayed geometry, not the intrinsic drawing buffer.
    width = float(box["width"])
    height = float(box["height"])
    delta_x, delta_y = center[0] - width / 2, center[1] - height / 2
    # Every generated profile keeps its target's in-window motion inside the
    # smallest reticle. Avoid needless physical correction for the ordinary
    # visible offset left after screenshot scaling and animation sampling.
    if math.hypot(delta_x, delta_y) <= 30:
        return
    camera_x, camera_y, zoom = _camera(page)
    if interaction == "simplified":
        scale = page.locator("#panorama-pan-scale")
        if scale.inner_text().startswith("COARSE"):
            scale.click()
        if abs(delta_x) > 12:
            page.locator('[data-pan="right"]' if delta_x > 0 else '[data-pan="left"]').click()
        if abs(delta_y) > 12:
            page.locator('[data-pan="down"]' if delta_y > 0 else '[data-pan="up"]').click()
    else:
        _move_camera(
            page,
            {"x": camera_x + delta_x / zoom, "y": camera_y + delta_y / zoom},
            tolerance=4.0,
        )


def _wait_for_new_event(canvas) -> None:
    deadline = time.time() + 8
    while time.time() < deadline and _ring_present(canvas):
        time.sleep(0.06)
    while time.time() < deadline:
        if _ring_present(canvas):
            return
        time.sleep(0.055)
    raise AssertionError("the repeating tip-to-tip ring event was not visibly observed")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    # Exercise local recovery on the challenge that will be discarded. The
    # eventual passing transcript stays a clean, mistake-free solve.
    interaction = page.locator(".impossible-panorama").get_attribute("data-interaction") or "legacy"
    if interaction == "full":
        page.locator("#panorama-zoom-slider").focus()
        page.keyboard.press("ArrowRight")
        page.locator("#panorama-focus-slider").focus()
        page.keyboard.press("ArrowRight")
        _move_camera(page, {"x": float(truth["initial_camera"]["x"]) + 80, "y": float(truth["initial_camera"]["y"])})
    else:
        page.locator("#panorama-zoom-in").click()
        if interaction == "simplified":
            page.locator("#panorama-focus-far").click()
        else:
            page.locator("#panorama-focus-slider").focus()
            page.keyboard.press("ArrowRight")
        page.locator('[data-pan="right"]').click()
    page.locator("#panorama-reset").click()
    expect(page.locator(".panorama-foot .readout")).to_contain_text("PLATE RESET")
    expect(page.locator(".impossible-panorama")).to_have_attribute("data-visited-count", "1")
    initial = truth["initial_camera"]
    camera_x, camera_y, zoom = _camera(page)
    assert abs(camera_x - float(initial["x"])) < .1 and abs(camera_y - float(initial["y"])) < .1 and abs(zoom - float(initial["zoom"])) < .01
    _shot(page, out_dir, mechanic, "reset-recovery")

    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    page.locator("#panorama-submit").click()
    _wait_fresh(state_dir, before)
    page.wait_for_selector('.impossible-panorama[data-fresh-failure="true"]', timeout=7_000)
    page.wait_for_function("() => document.querySelector('.panorama-foot .readout')?.textContent.includes('FAIL')")
    expect(page.locator(".impossible-panorama")).to_have_class(re.compile(r"\bis-failed\b"))
    _shot(page, out_dir, mechanic, "fail-refresh")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    page.wait_for_function("() => !document.querySelector('.impossible-panorama')?.classList.contains('is-failed')", timeout=5_000)
    truth = _read(state_dir / "ground_truth.json")
    solution = truth["solution"]

    # A couple of ordinary search sweeps prove the pan controls without making
    # arbitrary mileage part of the pass condition.
    for index, waypoint in enumerate(solution["search_waypoints"][:2]):
        _move_camera(page, waypoint, tolerance=90.0)
        if index == 1:
            _shot(page, out_dir, mechanic, "active-search")
    _shot(page, out_dir, mechanic, "search-sectors")

    _set_zoom(page, float(solution["zoom"]), truth)
    _set_focus(page, int(solution["target_depth"]), truth)
    interaction = page.locator(".impossible-panorama").get_attribute("data-interaction") or "legacy"
    # The proxy pad's fine step is intentionally coarser than the direct drag
    # endpoint. Its visible event trim below supplies the final correction.
    _move_camera(page, solution["target_base"], tolerance=45.0 if interaction == "simplified" else 8.0)
    _shot(page, out_dir, mechanic, "focused-reticle")

    canvas = page.locator("#panorama-canvas")
    _wait_for_new_event(canvas)
    page.wait_for_timeout(75)
    _shot(page, out_dir, mechanic, "event-observed")
    # The evidence capture is intentionally separate from the final exposure:
    # reacquire a fresh phase so it cannot consume the short L4 event window.
    _wait_for_new_event(canvas)
    shutter = page.locator("#panorama-shutter")
    box = shutter.bounding_box()
    if not box:
        raise AssertionError("shutter control has no physical geometry")
    for attempt in range(3):
        if attempt:
            _wait_for_new_event(canvas)
        _center_visible_event(page)
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.wait_for_timeout(330)
        # Do not capture a screenshot during the continuous physical hold:
        # image capture can delay the browser's 90 ms witness interval.
        page.wait_for_timeout(850)
        page.mouse.up()
        if "COHERENT EVENT" in (page.locator(".panorama-foot .readout").text_content() or ""):
            break
        _shot(page, out_dir, mechanic, f"exposure-retry-{attempt + 1}")
    else:
        raise AssertionError("three visible event exposures did not produce a coherent plate")
    page.wait_for_timeout(100)
    _shot(page, out_dir, mechanic, "solved-exposure")
    page.locator("#panorama-submit").click()
    expect(page.locator(".panorama-foot .readout")).to_have_text("PASS", timeout=10_000)
