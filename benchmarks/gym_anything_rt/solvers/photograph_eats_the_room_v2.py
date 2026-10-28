from __future__ import annotations

import json
import math
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "photograph_eats_the_room_v2"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def _camera(page) -> tuple[float, float, float]:
    root = page.locator(".photo-room")
    return (
        float(root.get_attribute("data-camera-x") or 0),
        float(root.get_attribute("data-camera-y") or 0),
        float(root.get_attribute("data-yaw") or 0),
    )


def _interaction(page) -> str:
    return page.locator(".photo-room").get_attribute("data-interaction") or "simplified"


def _turn_to(page, target: float) -> None:
    for _ in range(30):
        yaw = _camera(page)[2] % 360
        delta = (target - yaw) % 360
        if min(delta, 360 - delta) < 7.6:
            return
        positive = delta <= 180
        if _interaction(page) == "full":
            page.keyboard.press("ArrowRight" if positive else "ArrowLeft")
        else:
            page.locator('[data-turn="15"]' if positive else '[data-turn="-15"]').click()
    raise AssertionError(f"could not turn camera to {target}; ended at {_camera(page)}")


def _move_axis(page, axis: str, destination: float, *, tolerance: float = 0.16) -> None:
    for _ in range(150):
        x, y, _yaw = _camera(page)
        current = x if axis == "x" else y
        delta = destination - current
        if abs(delta) <= tolerance:
            return
        if axis == "x":
            _turn_to(page, 0 if delta > 0 else 180)
        else:
            _turn_to(page, 90 if delta > 0 else 270)
        # Short real holds preserve collision sampling and avoid teleporting or
        # overshooting sockets at low VNC frame rates.
        hold_ms = max(95, min(260, int(abs(delta) / 2.35 * 1000)))
        if _interaction(page) == "full":
            page.keyboard.down("w")
            page.wait_for_timeout(hold_ms)
            page.keyboard.up("w")
        else:
            button = page.locator('[data-move="forward"]')
            box = button.bounding_box()
            if not box:
                raise AssertionError("simplified movement control has no geometry")
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            page.wait_for_timeout(hold_ms)
            page.mouse.up()
    raise AssertionError(f"could not move {axis} to {destination}; ended at {_camera(page)}")


def _move_to(page, destination: dict) -> None:
    for _ in range(400):
        x, y, _yaw = _camera(page)
        dx, dy = float(destination["x"]) - x, float(destination["y"]) - y
        if math.hypot(dx, dy) < .14:
            return
        _turn_to(page, math.degrees(math.atan2(dy, dx)) % 360)
        # A short ordinary hold is followed by a fresh observation of the
        # camera, whose yaw keeps changing after every key release.
        if _interaction(page) == "full":
            page.keyboard.down("w")
            page.wait_for_timeout(85)
            page.keyboard.up("w")
        else:
            box = page.locator('[data-move="forward"]').bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            page.wait_for_timeout(85)
            page.mouse.up()
    raise AssertionError(f"could not navigate to {destination}; ended at {_camera(page)}")


def _place_plane(page, state: dict, socket: dict) -> None:
    camera_x, camera_y, yaw_deg = _camera(page)
    yaw = math.radians(yaw_deg)
    dx = float(socket["center"]["x"]) - camera_x
    dy = float(socket["center"]["y"]) - camera_y
    depth = dx * math.cos(yaw) + dy * math.sin(yaw)
    lateral = -dx * math.sin(yaw) + dy * math.cos(yaw)
    controls = state["controls"]
    u = (lateral - float(controls["plane_lateral_min"])) / (float(controls["plane_lateral_max"]) - float(controls["plane_lateral_min"]))
    v = 1 - (depth - float(controls["plane_depth_min"])) / (float(controls["plane_depth_max"]) - float(controls["plane_depth_min"]))
    target = page.locator("#photo-room-canvas" if _interaction(page) == "full" else "#photo-plane-pad")
    box = target.bounding_box()
    if not box:
        raise AssertionError("photo placement pad has no geometry")
    start_x, start_y = box["x"] + box["width"] * .5, box["y"] + box["height"] * .82
    end_x = box["x"] + box["width"] * max(.01, min(.99, u))
    end_y = box["y"] + box["height"] * max(.01, min(.99, v))
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(end_x, end_y)
    page.mouse.up()


def _scale_to(page, target: float) -> None:
    for _ in range(30):
        text = page.locator("#photo-scale").inner_text().replace("×", "")
        current = float(text)
        if abs(current - target) < .04:
            return
        if _interaction(page) == "full":
            canvas = page.locator("#photo-room-canvas")
            box = canvas.bounding_box()
            if not box:
                raise AssertionError("direct photograph canvas has no geometry")
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.wheel(0, -100 if target > current else 100)
        else:
            page.locator("#photo-scale-up" if target > current else "#photo-scale-down").click()
    raise AssertionError(f"could not scale photograph to {target}")


def _rotate_plane_to(page, target: int, state: dict) -> None:
    step = int(state["controls"]["plane_rotation_step_deg"])
    yaw = _camera(page)[2]
    choices = []
    for turn in (-15, 0, 15):
        relative = round((target - yaw - turn) / step) * step % 360
        error = abs((yaw + turn + relative - target + 180) % 360 - 180)
        choices.append((error, abs(turn), turn, relative))
    _, _, camera_turn, target = min(choices)
    if camera_turn:
        if _interaction(page) == "full":
            page.keyboard.press("ArrowRight" if camera_turn > 0 else "ArrowLeft")
        else:
            page.locator('[data-turn="15"]' if camera_turn > 0 else '[data-turn="-15"]').click()
    for _ in range(30):
        current = int(page.locator("#photo-rotation").inner_text().replace("°", "")) % 360
        if current == target % 360:
            return
        delta = (target - current) % 360
        positive = delta <= 180
        if _interaction(page) == "full":
            canvas = page.locator("#photo-room-canvas")
            box = canvas.bounding_box()
            if not box:
                raise AssertionError("direct photograph canvas has no geometry")
            start_x, start_y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            page.keyboard.down("Shift")
            page.mouse.move(start_x, start_y)
            page.mouse.down()
            rotation_step = int(state["controls"]["plane_rotation_step_deg"])
            step_count = round(min(delta, 360 - delta) / rotation_step)
            page.mouse.move(start_x + (1 if positive else -1) * (step_count * 12 + 1), start_y)
            page.mouse.up()
            page.keyboard.up("Shift")
        else:
            page.locator("#photo-rotate-right" if positive else "#photo-rotate-left").click()
    raise AssertionError(f"could not rotate photograph to {target}")


def _capture(page) -> None:
    if _interaction(page) == "full":
        page.keyboard.press("c")
    else:
        page.locator("#photo-capture").click()


def _capture_source(page, truth, index):
    target = dict(truth["solution"]["captures"][index]["camera"])
    source = truth["sources"][index]["midpoint"]
    target["y"] -= .55 if source["y"] > target["y"] else -.55
    if index:
        # Finish crossing on the bridge centre before turning toward a source
        # set off the main route. Cutting that corner can hit the void edge.
        bridge = page.evaluate("() => photographEatsTheRoomV2Model.operations.find(o => o.operation === 'add_walkway')")
        _move_to(page, {"x": float(truth["room"]["void"]["x2"]) + .6,
                        "y": bridge["center"]["y"]})
    _move_to(page, target)
    x, y, _yaw = _camera(page)
    _turn_to(page, math.degrees(math.atan2(source["y"] - y, source["x"] - x)) % 360)
    _capture(page)


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    before = str(truth["challenge_id"])
    expect(page.locator(".photo-room")).to_have_attribute("data-active", "true")
    # Exercise local rejection on this non-passing challenge only.  The clean
    # authoritative solve below never needs to make this mistake.
    first_capture = truth["solution"]["captures"][0]
    _capture_source(page, truth, 0)
    expect(page.locator(".photo-room")).to_have_attribute("data-carrying", "beam")
    page.locator("#photo-develop").click()
    expect(page.locator(".photo-foot .readout")).to_contain_text("DEVELOPMENT REJECTED")
    expect(page.locator(".photo-room")).to_have_attribute("data-operation-count", "0")
    _shot(page, out_dir, mechanic, "local-transform-rejected-negative-run")
    page.locator("#photo-submit").click()
    expect(page.locator(".photo-room[data-fresh-failure='true']")).to_be_visible(timeout=7_000)
    expect(page.locator(".photo-foot .readout")).to_have_text("FAIL", timeout=7_000)
    deadline = time.time() + 7
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json")["challenge_id"]) != before:
            break
        time.sleep(.05)
    else:
        raise AssertionError("failed room did not issue a fresh challenge")
    _shot(page, out_dir, mechanic, "fail-refresh")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    expect(page.locator(".photo-room")).to_have_attribute("data-active", "true", timeout=6_000)
    truth = _read(state_dir / "ground_truth.json")
    solution = truth["solution"]
    _shot(page, out_dir, mechanic, "initial-fresh-room")

    # Frame and capture the real beam from its camera mark.
    first_capture = solution["captures"][0]
    _capture_source(page, truth, 0)
    expect(page.locator(".photo-room")).to_have_attribute("data-carrying", "beam")
    _shot(page, out_dir, mechanic, "active-frustum-capture")

    first_placement = solution["placements"][0]
    _move_to(page, first_placement["camera"])
    _turn_to(page, float(first_placement["camera"]["yaw_deg"]))
    _place_plane(page, truth, truth["sockets"][0])
    _scale_to(page, float(first_placement["scale"]))
    _rotate_plane_to(page, int(first_placement["rotation_deg"]), truth)
    _place_plane(page, truth, truth["sockets"][0])
    _shot(page, out_dir, mechanic, "photo-plane-aligned")
    page.locator("#photo-develop").click()
    expect(page.locator(".photo-room")).to_have_attribute("data-operation-count", "1")
    _shot(page, out_dir, mechanic, "bridge-developed")

    if len(solution["captures"]) > 1:
        second_capture = solution["captures"][1]
        _capture_source(page, truth, 1)
        expect(page.locator(".photo-room")).to_have_attribute("data-carrying", "opening")

        second_placement = solution["placements"][1]
        _move_to(page, second_placement["camera"])
        _turn_to(page, float(second_placement["camera"]["yaw_deg"]))
        _place_plane(page, truth, truth["sockets"][1])
        _rotate_plane_to(page, int(second_placement["rotation_deg"]), truth)
        _scale_to(page, float(second_placement["scale"]))
        _place_plane(page, truth, truth["sockets"][1])
        page.locator("#photo-develop").click()
        expect(page.locator(".photo-room")).to_have_attribute("data-operation-count", "2")
        _shot(page, out_dir, mechanic, "room-overwritten-twice")

    terminal = solution["terminal"]
    _move_to(page, terminal)
    _turn_to(page, 0)
    _shot(page, out_dir, mechanic, "terminal-contact")
    page.locator("#photo-submit").click()
    expect(page.locator(".photo-foot .readout")).to_have_text("PASS", timeout=10_000)
