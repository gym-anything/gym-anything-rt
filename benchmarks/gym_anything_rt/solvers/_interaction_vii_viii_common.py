from __future__ import annotations

import json
import math
import time
from pathlib import Path

from playwright.sync_api import Error, expect


ABANDON = {
    "specular_lighthouse_relay": "#specular-abandon",
    "wind_tunnel_seed_courier": "#wind-abandon",
    "hologram_silhouette_foundry": "#holo-abandon",
    "orbital_docking_customs": "#orbital-abandon",
    "gravity_room_freight": "#gravity-abandon",
    "floodgate_archive_rescue": "#flood-abandon",
    "elastic_membrane_sorter": "#membrane-abandon",
    "pheromone_dispatch": "#pheromone-abandon",
    "clockwork_clutch_safe": "#clutch-abandon",
    "marionette_checkpoint": "#marionette-abandon",
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    if mechanic == "clockwork_clutch_safe":
        page.locator("#clutch-drive").click()
        page.wait_for_function("() => window.clockworkClutchSafeModel.tick >= 2")
    page.locator(ABANDON[mechanic]).click()
    expect(page.locator(".ivv-verdict.is-fresh")).to_be_visible(timeout=8_000)
    deadline = time.time() + 8
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json")["challenge_id"]) != before:
            break
        time.sleep(.05)
    else:
        raise AssertionError(f"{mechanic} failure did not issue a fresh challenge")
    if mechanic == "clockwork_clutch_safe":
        page.wait_for_timeout(300)
        expect(page.locator("#clutch-tick")).to_contain_text("0/")
    _shot(page, out_dir, mechanic, "fail-fresh")
    expect(page.locator(".ivv-verdict.is-fresh")).to_be_hidden(timeout=3_000)


def _click_many(locator, count: int) -> None:
    for _ in range(max(0, count)):
        locator.click()


def _set_range(page, selector: str, target: int, minimum: int = 0) -> None:
    control = page.locator(selector)
    control.focus()
    page.keyboard.press("Home")
    for _ in range(int(target) - int(minimum)):
        page.keyboard.press("ArrowRight")
    expect(control).to_have_value(str(int(target)))


def _adjust_range(page, selector: str, target: int) -> None:
    control = page.locator(selector)
    current = int(float(control.input_value()))
    target = int(target)
    if current == target:
        return
    control.focus()
    key = "ArrowRight" if target > current else "ArrowLeft"
    for _ in range(abs(target - current)):
        page.keyboard.press(key)


def _specular(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")
    _shot(page, out_dir, mechanic, "initial-fresh-optical-bench")
    def drag_steps(mirror_index: int, signed_steps: int) -> None:
        canvas = page.locator("#specular-canvas")
        box = canvas.bounding_box()
        if not box:
            raise AssertionError("specular canvas has no physical geometry")
        remaining = int(signed_steps)
        while remaining:
            chunk = max(-16, min(16, remaining))
            round_index = int(page.evaluate("() => window.specularLighthouseRelayModel.roundIndex"))
            center = truth["rounds"][round_index]["mirrors"][mirror_index]["center"]
            start_x = box["x"] + float(center[0]) / 900 * box["width"]
            start_y = box["y"] + float(center[1]) / 480 * box["height"]
            page.mouse.move(start_x, start_y)
            page.mouse.down()
            page.mouse.move(start_x + chunk * 8, start_y, steps=max(2, abs(chunk)))
            page.mouse.up()
            remaining -= chunk
    def aim(mirror_index: int, target: float) -> None:
        current = float(page.evaluate("i => window.specularLighthouseRelayModel.angles[i]", mirror_index))
        step = float(truth["rounds"][int(page.evaluate("() => window.specularLighthouseRelayModel.roundIndex"))]["angle_step_deg"])
        plus_steps = round(((float(target) - current) % 180) / step)
        minus_steps = round(((current - float(target)) % 180) / step)
        signed_steps = plus_steps if plus_steps <= minus_steps else -minus_steps
        if interaction == "full":
            drag_steps(mirror_index, signed_steps)
        else:
            selector = f'[data-mirror="{mirror_index}"][data-delta="{step if plus_steps <= minus_steps else -step:g}"]'
            for _ in range(min(plus_steps, minus_steps)):
                if page.locator(".ivv-verdict.is-pass").count() and page.locator(".ivv-verdict.is-pass").is_visible():
                    return
                try:
                    page.locator(selector).click(timeout=1_000)
                except Error:
                    if page.locator(".ivv-verdict.is-pass").count() and page.locator(".ivv-verdict.is-pass").is_visible():
                        return
                    raise

    for round_index, solution in enumerate(truth["solutions"]):
        for mirror_index, target in enumerate(solution["angles"]):
            if page.locator(".ivv-verdict.is-pass").count() and page.locator(".ivv-verdict.is-pass").is_visible():
                return
            aim(mirror_index, float(target))
        if round_index == 0:
            _shot(page, out_dir, mechanic, "three-mirror-beam-aligned")
        page.locator("#specular-charge").click()
        deadline = time.time() + 22
        photographed = False
        while time.time() < deadline:
            if page.locator(".ivv-verdict.is-pass").count() and page.locator(".ivv-verdict.is-pass").is_visible():
                break
            snapshot = page.evaluate("() => ({roundIndex:window.specularLighthouseRelayModel.roundIndex,tick:window.specularLighthouseRelayModel.tick,charge:window.specularLighthouseRelayModel.charge})")
            if int(snapshot["roundIndex"]) > round_index:
                break
            round_data = truth["rounds"][round_index]
            receiver = round_data["receiver"]
            receiver_y = float(receiver["center"][1]) + float(receiver["amplitude"]) * math.sin(int(snapshot["tick"]) * float(receiver["angular_rate"]) + float(receiver["phase"]))
            last_index = len(round_data["mirrors"]) - 1
            previous = round_data["emitter"] if last_index == 0 else round_data["mirrors"][last_index - 1]["center"]
            center = round_data["mirrors"][last_index]["center"]
            incoming = math.atan2(float(center[1]) - float(previous[1]), float(center[0]) - float(previous[0]))
            outgoing = math.atan2(receiver_y - float(center[1]), float(receiver["center"][0]) - float(center[0]))
            target = (math.degrees((incoming + outgoing) / 2 + math.pi / 2) + 90) % 180
            aim(last_index, target)
            if round_index == 0 and int(snapshot["charge"]) > 18 and not photographed:
                _shot(page, out_dir, mechanic, "live-moving-receiver-track")
                photographed = True
            page.wait_for_timeout(24)
        else:
            raise AssertionError(f"moving receiver {round_index + 1} did not charge")
        if page.locator(".ivv-verdict.is-pass").count() and page.locator(".ivv-verdict.is-pass").is_visible():
            return
    expect(page.locator(".ivv-verdict.is-pass")).to_be_visible(timeout=10_000)


def _wind(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    truth = _read(state_dir / "ground_truth.json")
    public = _read(state_dir / "public_state.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")
    canvas = page.locator("#wind-canvas")

    def set_fan(fan: int, power: int) -> None:
        if interaction == "simplified":
            page.locator(f'[data-fan="{fan}"][data-power="{power}"]').click()
            return
        box = canvas.bounding_box()
        if not box:
            raise AssertionError("wind tunnel has no visible fan-lever geometry")
        x = box["x"] + float(public["fans"][fan]["x"]) * box["width"] / 900
        start_y = box["y"] + 435 * box["height"] / 480
        target_y = box["y"] + {-1: 410, 0: 435, 1: 460}[power] * box["height"] / 480
        page.mouse.move(x, start_y)
        page.mouse.down()
        page.mouse.move(x, target_y, steps=2)
        page.mouse.up()

    page.locator("#wind-launch").click()
    for event_index, item in enumerate(truth["plan"]):
        page.wait_for_function("tick => window.windTunnelSeedCourierModel.tick >= tick", arg=int(item["tick"]), timeout=8_000)
        set_fan(int(item["fan"]), int(item["power"]))
        if event_index == 0:
            _shot(page, out_dir, mechanic, "fan-field-armed")
    active_tick = max(1, int(truth["physics"]["ticks"]) * 55 // 100)
    page.wait_for_function("tick => window.windTunnelSeedCourierModel.tick > tick", arg=active_tick, timeout=12_000)
    _shot(page, out_dir, mechanic, "active-gate-flight")
    expect(page.locator(".ivv-verdict.is-pass")).to_be_visible(timeout=20_000)


def _hologram(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")
    _shot(page, out_dir, mechanic, "initial-three-view-foundry")
    gizmo = page.locator("#holo-gizmo")

    def gizmo_drag(axis: str, delta: int) -> None:
        box = gizmo.bounding_box()
        if not box:
            raise AssertionError("foundry direct-manipulation gizmo is not visible")
        center = (132, 88)
        handles = {
            ("x", 1): (205, 88), ("x", -1): (59, 88),
            ("y", 1): (132, 28), ("y", -1): (132, 148),
            ("z", 1): (188, 42), ("z", -1): (76, 134),
        }
        point = handles[(axis, delta)]
        scale_x, scale_y = box["width"] / 264, box["height"] / 176
        start = (box["x"] + point[0] * scale_x, box["y"] + point[1] * scale_y)
        end = (
            start[0] + (point[0] - center[0]) * .58 * scale_x,
            start[1] + (point[1] - center[1]) * .58 * scale_y,
        )
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(*end, steps=5)
        page.mouse.up()

    def rotate_gizmo() -> None:
        box = gizmo.bounding_box()
        if not box:
            raise AssertionError("foundry orientation ring is not visible")
        scale_x, scale_y = box["width"] / 264, box["height"] / 176
        # Start on a clear arc of the ring, away from the direct X/Z handles.
        # The browser distinguishes an orientation drag from an axis-handle
        # drag by this same visible geometry.
        start = (box["x"] + 155 * scale_x, box["y"] + 39 * scale_y)
        end = (box["x"] + 105 * scale_x, box["y"] + 52 * scale_y)
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(*end, steps=6)
        page.mouse.up()

    for target in truth["solution_objects"]:
        page.locator(f'[data-rod="{target["id"]}"]').click()
        current = page.evaluate("id => window.hologramSilhouetteFoundryModel.objects.find(item => item.id === id)", target["id"])
        for axis_index, axis in enumerate("xyz"):
            delta = int(target["center"][axis_index]) - int(current["center"][axis_index])
            if interaction == "full":
                for _ in range(abs(delta)):
                    gizmo_drag(axis, 1 if delta > 0 else -1)
            else:
                button = page.locator(f'[data-move="{axis}{"+" if delta > 0 else "-"}"]')
                _click_many(button, abs(delta))
        current_axis = str(page.evaluate("id => window.hologramSilhouetteFoundryModel.objects.find(item => item.id === id).axis", target["id"]))
        turns = ("xyz".index(target["axis"]) - "xyz".index(current_axis)) % 3
        if interaction == "full":
            for _ in range(turns):
                rotate_gizmo()
        else:
            _click_many(page.locator("#holo-rotate"), turns)
    _shot(page, out_dir, mechanic, "three-shadow-dies-coincident")
    page.locator("#holo-cast").click()


def _orbital(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")
    plan = truth["reference_plan"]
    _shot(page, out_dir, mechanic, "initial-rendezvous")
    key_for = {
        "thrust": "KeyW", "retro": "KeyS", "strafe-up": "KeyA", "strafe-down": "KeyD",
        "rotate-left": "KeyQ", "rotate-right": "KeyE", "coast": "Space", "coast-long": "Shift+Space",
    }
    def act(action: str, count: int = 1) -> None:
        if interaction == "full":
            for _ in range(count):
                page.keyboard.press(key_for[action])
        else:
            _click_many(page.locator(f'[data-orbit="{action}"]'), count)
    coast_seen = 0
    for item in plan:
        action = str(item["action"])
        if action in {"thrust", "retro", "strafe-up", "strafe-down"}:
            act(action, int(item["count"]))
        elif action == "coast":
            ticks = int(item["ticks"])
            act("coast-long", ticks // 30)
            act("coast", ticks % 30 // 10)
            coast_seen += 1
            if coast_seen == 2:
                _shot(page, out_dir, mechanic, "first-scan-s-corridor")
        elif action == "rotate":
            target = int(round(float(item["target_deg"]))) % 360
            current = int(round(float(page.evaluate("() => window.orbitalDockingCustomsModel.ship.angle_deg")))) % 360
            right = ((target - current) % 360) // 15
            left = ((current - target) % 360) // 15
            act(f'rotate-{"right" if right <= left else "left"}', min(right, left))
        elif action == "dock":
            if interaction == "full":
                page.keyboard.press("Enter")
            else:
                page.locator("#orbital-dock").click()
        else:
            raise AssertionError(f"unknown orbital reference action: {action}")


def _gravity(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")
    _shot(page, out_dir, mechanic, "initial-gravity-room")
    for index, action in enumerate(truth["solution"]):
        if interaction == "simplified":
            page.locator(f'[data-gravity="{action}"]').click()
        else:
            canvas = page.locator("#gravity-canvas")
            box = canvas.bounding_box()
            if box is None:
                raise AssertionError("gravity room canvas has no visible bounds")
            start_x = box["x"] + box["width"] * (0.34 if action == "cw" else 0.66)
            end_x = box["x"] + box["width"] * (0.66 if action == "cw" else 0.34)
            center_y = box["y"] + box["height"] * .5
            page.mouse.move(start_x, center_y)
            page.mouse.down()
            page.mouse.move(end_x, center_y, steps=8)
            page.mouse.up()
        page.wait_for_timeout(680)
        if index == len(truth["solution"]) // 2:
            _shot(page, out_dir, mechanic, "mid-rotation-airlocks")
    page.locator("#gravity-certify").click()


def _flood(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")
    def vault_center(index: int) -> tuple[float, float]:
        tank = page.locator(f'.flood-tank[data-vault="{index}"]')
        box = tank.bounding_box()
        if not box:
            raise AssertionError(f"flood vault {index + 1} has no direct-manipulation geometry")
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    def water_point(index: int) -> tuple[float, float]:
        tank = page.locator(f'.flood-tank[data-vault="{index}"]')
        box = tank.bounding_box()
        if not box:
            raise AssertionError(f"flood vault {index + 1} has no direct water geometry")
        # Capsules render on the horizontal midpoint.  Use an uncovered part
        # of the same visible tank so the full solver drives water, not a
        # capsule that happens to float at the current level.
        return box["x"] + box["width"] * .22, box["y"] + box["height"] / 2
    def drag(start: tuple[float, float], end: tuple[float, float]) -> None:
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(*end, steps=8)
        page.mouse.up()
    _shot(page, out_dir, mechanic, "initial-unequal-vaults")
    for index, action in enumerate(truth["reference_plan"]):
        if action["action"] == "pump":
            if interaction == "simplified":
                page.locator(f'[data-circuit="{action["circuit"]}"][data-direction="{action["direction"]}"]').click()
            else:
                circuit = truth.get("circuits", [])
                if not circuit:
                    circuit = page.evaluate("() => window.floodgateArchiveRescueModel.state.circuits")
                endpoints = circuit[int(action["circuit"])]["between"] if isinstance(circuit[int(action["circuit"])], dict) else circuit[int(action["circuit"])]
                source, destination = (int(endpoints[0]), int(endpoints[1])) if int(action["direction"]) == 1 else (int(endpoints[1]), int(endpoints[0]))
                drag(water_point(source), water_point(destination))
        elif action["action"] == "gate":
            if interaction == "simplified":
                page.locator(f'[data-lock="{action["gate"]}"]').click()
            else:
                page.locator(f'#flood-lock-{action["gate"]}').click()
        else:
            if interaction == "simplified":
                page.locator("#flood-flow").click()
            else:
                gate = int(action["gate"])
                capsule = page.evaluate(
                    """gate => window.floodgateArchiveRescueModel.capsules.find((item) =>
                      (item.direction === 1 && item.chamber === gate) ||
                      (item.direction === -1 && item.chamber === gate + 1)
                    )""",
                    gate,
                )
                if not capsule:
                    raise AssertionError(f"no capsule can directly cross flood lock {gate + 1}")
                source = int(capsule["chamber"])
                destination = source + int(capsule["direction"])
                marker = page.locator(f'#flood-capsule-{capsule["id"]}-{source}')
                marker_box = marker.bounding_box()
                if not marker_box:
                    raise AssertionError(f"flood capsule {capsule['id']} has no direct drag target")
                drag((marker_box["x"] + marker_box["width"] / 2, marker_box["y"] + marker_box["height"] / 2), vault_center(destination))
        if index == len(truth["reference_plan"]) // 2:
            _shot(page, out_dir, mechanic, "active-lock-transfer")
    page.locator("#flood-certify").click()


def _membrane(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")
    _shot(page, out_dir, mechanic, "initial-live-membrane")
    canvas = page.locator("#membrane-canvas")

    def adjust_post(index: int, target: int) -> None:
        if interaction == "simplified":
            _adjust_range(page, f'[data-post="{index}"]', target)
            return
        box = canvas.bounding_box()
        if not box:
            raise AssertionError("membrane canvas has no direct post geometry")
        snapshot = page.evaluate(
            "(index) => ({height: window.elasticMembraneSorterModel.heights[index], point: window.elasticMembraneSorterModel.state.post_positions[index]})",
            index,
        )
        current = float(snapshot["height"])
        point = snapshot["point"]
        start_x = box["x"] + float(point[0]) / 900 * box["width"]
        start_y = box["y"] + (float(point[1]) + (.5 - current) * 80) / 480 * box["height"]
        end_y = box["y"] + (float(point[1]) + (.5 - float(target) / 100) * 80) / 480 * box["height"]
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x, end_y, steps=3)
        page.mouse.up()

    for index, round_data in enumerate(truth["rounds"]):
        first = round_data["checkpoints"][0]
        fx = max(-.048, min(.048, .004 * (float(first[0]) - 450)))
        fy = max(-.048, min(.048, .004 * (float(first[1]) - 230)))
        scale = 2 * float(truth["physics"]["slope_accel"])
        hx, hy = fx / scale, fy / scale
        initial = [max(0, min(100, round(100 * value))) for value in (.5 + hx + hy, .5 - hx + hy, .5 + hx - hy, .5 - hx - hy)]
        for post, value in enumerate(initial):
            adjust_post(post, value)
        page.locator("#membrane-release").click()
        last_control = -10
        photographed = False
        deadline = time.time() + 32
        while time.time() < deadline:
            if page.locator(".ivv-verdict.is-pass").count() and page.locator(".ivv-verdict.is-pass").is_visible():
                break
            snapshot = page.evaluate("() => {const m=window.elasticMembraneSorterModel;return {roundIndex:m.roundIndex,ticks:m.ticks,checkpoint:m.checkpoint,ball:{...m.ball},running:m.running}}")
            if int(snapshot["roundIndex"]) > index:
                break
            if not snapshot["running"] and int(snapshot["ticks"]) >= int(truth["physics"]["max_ticks"]):
                raise AssertionError("closed-loop membrane controller reached the visible simulation limit")
            if int(snapshot["ticks"]) - last_control >= 6:
                checkpoint = int(snapshot["checkpoint"])
                target = round_data["checkpoints"][checkpoint] if checkpoint < len(round_data["checkpoints"]) else round_data["wells"][round_data["target_well"]]
                ball = snapshot["ball"]
                fx = max(-.048, min(.048, .004 * (float(target[0]) - float(ball["x"])) - .09 * float(ball["vx"])))
                fy = max(-.048, min(.048, .004 * (float(target[1]) - float(ball["y"])) - .09 * float(ball["vy"])))
                hx, hy = fx / scale, fy / scale
                targets = [max(0, min(100, round(100 * value))) for value in (.5 + hx + hy, .5 - hx + hy, .5 + hx - hy, .5 - hx - hy)]
                for post, value in enumerate(targets):
                    adjust_post(post, value)
                last_control = int(snapshot["ticks"])
            if index == 0 and int(snapshot["checkpoint"]) == 1 and not photographed:
                _shot(page, out_dir, mechanic, "live-steering-between-rings")
                photographed = True
            page.wait_for_timeout(28)
        else:
            raise AssertionError(f"membrane round {index + 1} did not capture")
    expect(page.locator(".ivv-verdict.is-pass")).to_be_visible(timeout=10_000)


def _pheromone(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    truth = _read(state_dir / "ground_truth.json")
    public = _read(state_dir / "public_state.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    canvas = page.locator("#pheromone-canvas")
    box = canvas.bounding_box()
    if not box: raise AssertionError("pheromone habitat has no pointer geometry")
    def screen(point): return box["x"] + point[0] / 900 * box["width"], box["y"] + point[1] / 480 * box["height"]

    def has_passed() -> bool:
        verdict = page.locator(".ivv-verdict.is-pass")
        return verdict.count() > 0 and verdict.is_visible()

    def paint_route(field_id: str) -> None:
        path = truth["reference_paths"][field_id]
        if interaction == "simplified":
            page.locator(f'[data-field="{field_id}"]').click()
            points = [path[0]]
            for first, second in zip(path, path[1:]):
                steps = max(1, math.ceil(math.dist(first, second) / 120))
                points.extend([
                    [first[0] + (second[0] - first[0]) * step / steps, first[1] + (second[1] - first[1]) * step / steps]
                    for step in range(1, steps + 1)
                ])
            for point in points:
                page.mouse.click(*screen(point))
            page.locator("#pheromone-commit").click()
            return
        page.locator(f'[data-field="{field_id}"]').click()
        page.mouse.move(*screen(path[0])); page.mouse.down()
        try:
            for first, second in zip(path, path[1:]):
                steps = max(1, math.ceil(math.dist(first, second) / 120))
                for step in range(1, steps + 1):
                    amount = step / steps
                    page.mouse.move(*screen([first[0] + (second[0] - first[0]) * amount, first[1] + (second[1] - first[1]) * amount]))
        finally:
            page.mouse.up()
    for field_id in truth["reference_paths"]:
        paint_route(field_id)
    _shot(page, out_dir, mechanic, "two-fields-painted")
    page.locator("#pheromone-dispatch").click()
    photographed = False
    deadline = time.time() + 38
    while time.time() < deadline:
        if has_passed():
            break
        snapshot = page.evaluate("() => {const m=window.pheromoneDispatchModel;return {tick:m.tick,lastRefresh:{...m.lastRefresh},delivered:{...m.delivered},carrying:Object.values(m.ants).flat().some(a=>a.carrying)}}")
        for field in truth["reference_paths"]:
            if has_passed():
                break
            spec = next(item for item in public["fields"] if item["id"] == field)
            if int(snapshot["tick"]) - int(snapshot["lastRefresh"][field]) >= int(spec["trail_ttl_ticks"]) - 28:
                paint_route(field)
        if snapshot["carrying"] and not photographed:
            _shot(page, out_dir, mechanic, "two-active-cache-carrier-swarms")
            photographed = True
        page.wait_for_timeout(100)
    else:
        raise AssertionError("dual pheromone teams did not complete")
    expect(page.locator(".ivv-verdict.is-pass")).to_be_visible(timeout=10_000)


def _clutch(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
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
    page.locator("#clutch-drive").click()
    for schedule_index, item in enumerate(truth["release_schedule"]):
        target_tick = int(item["tick"])
        shaft = int(item["shaft"])
        page.wait_for_function(
            "target => window.clockworkClutchSafeModel?.tick >= target",
            arg=target_tick,
            polling=4,
            timeout=60_000,
        )
        page.locator("#clutch-brake").click(force=True)
        page.wait_for_function("() => window.clockworkClutchSafeModel.running === false", polling=50)
        stopped_tick = int(page.evaluate("() => window.clockworkClutchSafeModel.tick"))
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
            page.locator("#clutch-drive").click()
    _shot(page, out_dir, mechanic, f"{len(truth['release_schedule'])}-phases-braked")
    page.locator("#clutch-unlock").click()


def _marionette(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "simplified")
    active_indices = list(truth.get("active_string_indices") or (0, 1, 2, 3))
    _shot(page, out_dir, mechanic, "initial-coupled-puppet")

    def set_length(string: int, length: int) -> None:
        if interaction == "simplified":
            _adjust_range(page, f'[data-string="{string}"]', int(length))
            return
        canvas = page.locator("#marionette-canvas")
        box = canvas.bounding_box()
        if not box:
            raise AssertionError("marionette theatre canvas is not visible")
        current = float(page.evaluate("index => window.marionetteCheckpointModel.lengths[index]", string))
        start = (box["x"] + (290 + string * 105) * box["width"] / 900, box["y"] + (22 + (current - 20) * 1.8) * box["height"] / 480)
        target = (start[0], box["y"] + (22 + (int(length) - 20) * 1.8) * box["height"] / 480)
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(*target)
        page.mouse.up()

    for pose_index, pose in enumerate(truth["poses"]):
        photographed = False
        deadline = time.time() + 18
        while time.time() < deadline:
            if page.locator(".ivv-verdict.is-pass").count() and page.locator(".ivv-verdict.is-pass").is_visible():
                break
            snapshot = page.evaluate("() => {const m=window.marionetteCheckpointModel;return {poseIndex:m.poseIndex,tick:m.tick,progress:m.progress}}")
            if int(snapshot["poseIndex"]) > pose_index:
                break
            future_tick = int(snapshot["tick"]) + (5 if interaction == "full" else 2)
            targets = [round(float(base) + float(pose["amplitudes"][index]) * math.sin(future_tick * float(pose["angular_rate"]) + float(pose["phases"][index]))) for index, base in enumerate(pose["base_lengths"])]
            for string in active_indices:
                set_length(string, int(targets[string]))
            if pose_index == 0 and int(snapshot["progress"]) > 22 and not photographed:
                _shot(page, out_dir, mechanic, "live-four-limb-tracking")
                photographed = True
            page.wait_for_timeout(85)
        else:
            raise AssertionError(f"moving marionette act {pose_index + 1} did not clear")
    expect(page.locator(".ivv-verdict.is-pass")).to_be_visible(timeout=10_000)


SOLVERS = {
    "specular_lighthouse_relay": _specular,
    "wind_tunnel_seed_courier": _wind,
    "hologram_silhouette_foundry": _hologram,
    "orbital_docking_customs": _orbital,
    "gravity_room_freight": _gravity,
    "floodgate_archive_rescue": _flood,
    "elastic_membrane_sorter": _membrane,
    "pheromone_dispatch": _pheromone,
    "clockwork_clutch_safe": _clutch,
    "marionette_checkpoint": _marionette,
}


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    expect(page.locator(f'.ivv-{mechanic.replace("_", "-")}')).to_be_visible(timeout=6_000)
    SOLVERS[mechanic](page, state_dir, out_dir, mechanic)
