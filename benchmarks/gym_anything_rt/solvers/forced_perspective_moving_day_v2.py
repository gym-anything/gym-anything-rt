from __future__ import annotations

import json
import math
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "forced_perspective_moving_day_v2"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True); page.screenshot(path=str(out_dir / f"{mechanic}-{name}.png"), full_page=True)


def _wait_new(state_dir: Path, before: str) -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json").get("challenge_id")) != before: return
        time.sleep(.05)
    raise AssertionError("perspective challenge did not regenerate")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID: raise AssertionError(mechanic)
    # Collision evidence belongs to this disposable negative attempt, never to
    # the accepted solution transcript.
    page.keyboard.down("w")
    try:
        expect(page.locator(".persp-impact[data-visible='true']")).to_be_visible(timeout=5_000)
    finally:
        page.keyboard.up("w")
    _shot(page, out_dir, mechanic, "unbridged-void-collision")
    page.locator(".persp-reset").click()
    expect(page.locator(".readout")).to_contain_text("REWOUND")
    before = str(_read(state_dir / "ground_truth.json")["challenge_id"]); page.locator(".persp-submit").click(); _wait_new(state_dir, before)
    expect(page.locator(".perspective-captcha[data-fresh-failure='true']")).to_be_visible(timeout=8_000); expect(page.locator(".readout")).to_contain_text("FAIL"); _shot(page, out_dir, mechanic, "fail-fresh-room")


def _camera_coords(point: list[float], camera: dict) -> tuple[float, float, float]:
    dx, dy, dz = point[0] - camera["x"], point[1] - camera["y"], point[2] - camera["z"]; c, s = math.cos(camera["yaw"]), math.sin(camera["yaw"])
    return c * dx - s * dz, dy, s * dx + c * dz


def _project(point: list[float], camera: dict) -> tuple[float, float, float]:
    x, y, depth = _camera_coords(point, camera); return camera["center"][0] + camera["focal"] * x / depth, camera["center"][1] - camera["focal"] * y / depth, depth


def _canvas_screen(box: dict, stage: dict, point: tuple[float, float]) -> tuple[float, float]:
    return box["x"] + point[0] / stage["width"] * box["width"], box["y"] + point[1] / stage["height"] * box["height"]


def _center_dolly(page):
    for _ in range(80):
        x, tick = page.evaluate("() => [forcedPerspectiveMovingDayV2Model.camera.x, forcedPerspectiveMovingDayV2Model.tick]")
        if abs(x) < .22:
            return
        key = "a" if x > 0 else "d"
        page.keyboard.down(key)
        page.wait_for_function("tick => forcedPerspectiveMovingDayV2Model.tick > tick", arg=tick, polling=4)
        page.keyboard.up(key)
    raise AssertionError("could not counteract dolly drift")


def _pick(page, truth: dict, box: dict, object_id: str, interaction: str) -> None:
    _center_dolly(page)
    truth["camera"] = page.evaluate("() => ({...forcedPerspectiveMovingDayV2Model.camera})")
    obj = next(item for item in truth["objects"] if item["id"] == object_id); projected = _project(obj["center"], truth["camera"]); page.mouse.move(*_canvas_screen(box, truth["stage"], truth["camera"]["center"]), steps=8); page.mouse.move(*_canvas_screen(box, truth["stage"], projected[:2]), steps=8)
    if interaction == "full":
        page.mouse.down()
    else:
        page.mouse.click(*_canvas_screen(box, truth["stage"], projected[:2]))
    expect(page.locator(".persp-held-value")).to_have_text(object_id.upper())


def _target_aim(truth: dict, object_id: str, target_xz: list[float], actual_depth: float, apparent: float) -> tuple[float, float]:
    camera = truth["camera"]; obj = next(item for item in truth["objects"] if item["id"] == object_id); target_point = [target_xz[0], 0, target_xz[1]]; camera_x, _camera_y, target_depth = _camera_coords(target_point, camera)
    # Preserve target camera-x while accepting the nearest legal 0.5-depth plane.
    c, s = math.cos(camera["yaw"]), math.sin(camera["yaw"]); world_x = camera["x"] + c * camera_x + s * actual_depth; world_z = camera["z"] - s * camera_x + c * actual_depth; scale = apparent * actual_depth / (camera["focal"] * obj["reference_size"]); vertical_size = obj["base_size"][2] if obj["role"] == "bridge" else obj["base_size"][1]; world_y = vertical_size * scale / 2
    screen = _project([world_x, world_y, world_z], camera); return screen[0], screen[1]


def _place(page, truth: dict, box: dict, object_id: str, target: list[float], use_wheel: bool, out_dir: Path | None = None) -> None:
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")
    _pick(page, truth, box, object_id, interaction); held = page.evaluate("() => ({depth:window.forcedPerspectiveMovingDayV2Model.held.depth,apparent:window.forcedPerspectiveMovingDayV2Model.held.apparent})"); camera_target = _camera_coords([target[0], 0, target[1]], truth["camera"]); steps = round((camera_target[2] - held["depth"]) / truth["depth_controls"]["step"]); direction = 1 if steps > 0 else -1
    if use_wheel or interaction == "full":
        canvas = page.locator(".persp-canvas"); canvas.hover()
        for _ in range(abs(steps)): page.mouse.wheel(0, 120 * direction); page.wait_for_timeout(18)
    else:
        button = page.locator(".persp-farther" if direction > 0 else ".persp-nearer")
        for _ in range(abs(steps)): button.click()
    _center_dolly(page)
    actual_depth = page.evaluate("() => window.forcedPerspectiveMovingDayV2Model.held.depth")
    truth["camera"] = page.evaluate("() => ({...forcedPerspectiveMovingDayV2Model.camera})")
    target_depth = _camera_coords([target[0], 0, target[1]], truth["camera"])[2]
    remaining = round((target_depth - actual_depth) / truth["depth_controls"]["step"])
    if remaining:
        page.locator(".persp-canvas").hover()
        for _ in range(abs(remaining)):
            page.mouse.wheel(0, 120 if remaining > 0 else -120)
            page.wait_for_timeout(18)
        actual_depth = page.evaluate("() => window.forcedPerspectiveMovingDayV2Model.held.depth")
        truth["camera"] = page.evaluate("() => ({...forcedPerspectiveMovingDayV2Model.camera})")
    aim = _target_aim(truth, object_id, target, actual_depth, held["apparent"])
    page.mouse.move(*_canvas_screen(box, truth["stage"], aim), steps=2)
    # Reconcile the floor-contact y coordinate against the live camera after CSS/canvas scaling.
    live_aim = page.evaluate("""() => { const m=window.forcedPerspectiveMovingDayV2Model,h=m.held,o=m.objects[h.id],c=m.camera,cx=(m.aim[0]-c.center[0])/c.focal*h.depth,co=Math.cos(c.yaw),si=Math.sin(c.yaw),x=c.x+co*cx+si*h.depth,z=c.z-si*cx+co*h.depth,scale=h.apparent*h.depth/(c.focal*o.reference_size),vertical=o.role==='bridge'?o.base_size[2]:o.base_size[1],y=vertical*scale/2,dx=x-c.x,dy=y-c.y,dz=z-c.z,camx=co*dx-si*dz,depth=si*dx+co*dz; return [m.aim[0],c.center[1]-c.focal*dy/depth]; }""")
    page.mouse.move(*_canvas_screen(box, truth["stage"], live_aim), steps=4); page.wait_for_timeout(60)
    if object_id == "sign" and out_dir is not None: _shot(page, out_dir, MECHANIC_ID, "active-perspective-depth")
    truth["camera"] = page.evaluate("() => ({...forcedPerspectiveMovingDayV2Model.camera})")
    aim = _target_aim(truth, object_id, target, actual_depth, held["apparent"])
    page.mouse.move(*_canvas_screen(box, truth["stage"], aim))
    if interaction == "full":
        page.mouse.up()
    else:
        page.locator(".persp-release").click()
    expect(page.locator(".persp-held-value")).to_have_text("NONE")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID: raise AssertionError(mechanic)
    truth = _read(state_dir / "ground_truth.json")
    box = page.locator(".persp-canvas").bounding_box()
    if not box: raise AssertionError("perspective room canvas missing")
    _place(page, truth, box, "crate", truth["solver_targets"]["crate"], use_wheel=False, out_dir=out_dir); expect(page.locator(".persp-door-state")).to_have_text("UNLOCKED"); _shot(page, out_dir, mechanic, "shrunk-crate-key-slot")
    _place(page, truth, box, "sign", truth["solver_targets"]["sign"], use_wheel=True, out_dir=out_dir); expect(page.locator(".persp-bridge-state")).to_have_text("LOAD-BEARING"); _shot(page, out_dir, mechanic, "enlarged-sign-bridge")
    navigate_and_submit(page, out_dir, mechanic)


def navigate_and_submit(page, out_dir: Path, mechanic: str, *, allow_recovery=False) -> None:
    held: set[str] = set(); deadline = time.time() + 20; blocked_ticks = 0
    page.keyboard.down("w"); held.add("w")
    while time.time() < deadline:
        state = page.evaluate("() => ({x:window.forcedPerspectiveMovingDayV2Model.camera.x,z:window.forcedPerspectiveMovingDayV2Model.camera.z,doorX:window.forcedPerspectiveMovingDayV2Model.doorX,done:window.forcedPerspectiveMovingDayV2Model.completed,blocked:window.forcedPerspectiveMovingDayV2Model.blocked})")
        if state["done"]: break
        target_x = state["doorX"] if 16 < state["z"] < 20 else 0
        error_x = state["x"] - target_x
        if state["blocked"]:
            blocked_ticks += 1
            # A physical lip/door contact can occur between observation polls.
            # Explicitly strafe back toward the bridge/door centre and let the
            # collision resolver slide along the supported edge.
            correction = "a" if error_x > 0 else "d"
            opposite = "d" if correction == "a" else "a"
            if opposite in held: page.keyboard.up(opposite); held.remove(opposite)
            if correction not in held: page.keyboard.down(correction); held.add(correction)
            if blocked_ticks > 20: raise AssertionError(f"avatar could not recover from rigid contact: {state}")
            page.wait_for_timeout(45); continue
        blocked_ticks = 0
        if error_x > .18 and "a" not in held: page.keyboard.down("a"); held.add("a")
        if error_x <= .05 and "a" in held: page.keyboard.up("a"); held.remove("a")
        if error_x < -.18 and "d" not in held: page.keyboard.down("d"); held.add("d")
        if error_x >= -.05 and "d" in held: page.keyboard.up("d"); held.remove("d")
        page.wait_for_timeout(12)
    for key in list(held): page.keyboard.up(key)
    if not state["done"]:
        final_state = page.evaluate("() => ({x:window.forcedPerspectiveMovingDayV2Model.camera.x,z:window.forcedPerspectiveMovingDayV2Model.camera.z,done:window.forcedPerspectiveMovingDayV2Model.completed,blocked:window.forcedPerspectiveMovingDayV2Model.blocked,bridge:window.forcedPerspectiveMovingDayV2Model.bridgeReady,door:window.forcedPerspectiveMovingDayV2Model.doorOpen,tick:window.forcedPerspectiveMovingDayV2Model.tick})")
        raise AssertionError(f"avatar did not reach impossible-door exit: {final_state}")
    expect(page.locator(".persp-complete[data-visible='true']")).to_be_visible(timeout=3_000); state = page.evaluate("() => ({completed:window.forcedPerspectiveMovingDayV2Model.completed,bridge:window.forcedPerspectiveMovingDayV2Model.bridgeReady,door:window.forcedPerspectiveMovingDayV2Model.doorOpen,collisions:window.forcedPerspectiveMovingDayV2Model.collisions,resets:window.forcedPerspectiveMovingDayV2Model.resets,tick:window.forcedPerspectiveMovingDayV2Model.tick})")
    if not state["completed"] or not state["bridge"] or not state["door"] or (not allow_recovery and (state["collisions"] != 0 or state["resets"] != 0)): raise AssertionError(f"perspective move was not a clean completion: {state}")
    _shot(page, out_dir, mechanic, "solved-impossible-door"); page.locator(".persp-submit").click(); expect(page.locator(".readout")).to_have_text("PASS", timeout=8_000)
