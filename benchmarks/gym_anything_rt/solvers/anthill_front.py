from __future__ import annotations

import json
import re
import time
from io import BytesIO
from pathlib import Path

from PIL import Image


MECHANIC_ID = "anthill_front"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def _tick(page) -> int:
    return int(page.locator("#anthill-tick").inner_text().split("/")[0].strip())


def _canvas_point(page, world: dict, wx: float, wy: float, camera_x: float) -> tuple[float, float]:
    box = page.locator("#anthill-world").bounding_box()
    if not box:
        raise AssertionError("anthill canvas has no visible geometry")
    view = min(float(world["viewport_cells"]), float(world["width"]))
    return (
        box["x"] + (wx - camera_x) / view * box["width"],
        box["y"] + wy / float(world["height"]) * box["height"],
    )


def _minimap_pan(page, world: dict, wx: float) -> float:
    box = page.locator("#anthill-minimap").bounding_box()
    if not box:
        raise AssertionError("anthill minimap has no visible geometry")
    page.mouse.click(box["x"] + wx / float(world["width"]) * box["width"], box["y"] + box["height"] / 2)
    view = min(float(world["viewport_cells"]), float(world["width"]))
    return max(0.0, min(float(world["width"]) - view, wx - view / 2))


def _marquee(page, world: dict, camera_x: float, left: float, top: float, right: float, bottom: float) -> None:
    start = _canvas_point(page, world, left, top, camera_x)
    end = _canvas_point(page, world, right, bottom, camera_x)
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(*end, steps=6)
    page.mouse.up()


def _worker_position(world: dict, unit_index: int, tick: int, gather_tick: int) -> tuple[float, float]:
    worker = world["workers"][unit_index]
    start_x = float(worker["x"])
    start_y = float(worker["y"])
    elapsed = max(0, tick - gather_tick)
    cycle = int(world["gather_cycle_ticks"])
    phase = (elapsed % cycle) / cycle
    travel = phase * 2 if phase < 0.5 else (1 - phase) * 2
    return (
        start_x + (float(world["seed_pile"]["x"]) - start_x) * travel,
        start_y + (float(world["seed_pile"]["y"]) - start_y) * travel,
    )


def _select_worker(page, world: dict, camera_x: float, unit_index: int, gather_tick: int, shift: bool = False) -> None:
    wx, wy = _worker_position(world, unit_index, _tick(page), gather_tick)
    x, y = _canvas_point(page, world, wx, wy, camera_x)
    if shift:
        page.keyboard.down("Shift")
    page.mouse.click(x, y)
    if shift:
        page.keyboard.up("Shift")


def _wait_tick(page, target: int, timeout: int = 45_000) -> None:
    page.wait_for_function(
        "target => Number(document.querySelector('#anthill-tick')?.textContent.split('/')[0]) >= target",
        arg=target,
        timeout=timeout,
    )


def _select_simplified(page, unit_ids: list[str]) -> None:
    page.locator('[data-select-role="clear"]').click()
    for unit_id in unit_ids:
        page.locator(f'[data-roster-unit="{unit_id}"]').click()


def _select_full_idle_workers(page, world: dict, camera_x: float, unit_ids: list[str]) -> None:
    expected = set(unit_ids)
    for _attempt in range(3):
        for offset, unit_id in enumerate(unit_ids):
            worker = world["workers"][int(unit_id[1:]) - 1]
            x, y = _canvas_point(page, world, float(worker["x"]), float(worker["y"]), camera_x)
            if offset:
                page.keyboard.down("Shift")
            page.mouse.click(x, y)
            if offset:
                page.keyboard.up("Shift")
        visible_ids = set(re.findall(r"[WS]\d+", page.locator("#anthill-selection").inner_text()))
        if visible_ids == expected:
            return
    raise AssertionError(f"could not visibly select exact idle worker group {sorted(expected)}")


def _select_full_workers(page, world: dict, camera_x: float, unit_ids: list[str], gather_tick: int) -> None:
    expected = set(unit_ids)
    for tick_bias in (0, -1, -2, 1, 2):
        for offset, unit_id in enumerate(unit_ids):
            _select_worker(page, world, camera_x, int(unit_id[1:]) - 1, gather_tick + tick_bias, shift=offset > 0)
        visible_ids = set(re.findall(r"[WS]\d+", page.locator("#anthill-selection").inner_text()))
        if visible_ids == expected:
            return
        page.wait_for_timeout(35)
    raise AssertionError(f"could not visibly select exact full-mode worker crew {sorted(expected)}")


def _select_full_rally_soldiers(page, world: dict, camera_x: float, unit_ids: list[str]) -> None:
    for offset, unit_id in enumerate(unit_ids):
        index = int(unit_id[1:]) - 1
        wx = float(world["rally"]["x"]) + (index % 5) * 0.35
        wy = float(world["rally"]["y"]) - 0.8 + (index // 5) * 0.32
        x, y = _canvas_point(page, world, wx, wy, camera_x)
        if offset:
            page.keyboard.down("Shift")
        page.mouse.click(x, y)
        if offset:
            page.keyboard.up("Shift")


def _select_full_positioned_soldiers(page, world: dict, camera_x: float, unit_ids: list[str], orders: dict[str, str]) -> None:
    expected = set(unit_ids)
    for _attempt in range(3):
        for offset, unit_id in enumerate(unit_ids):
            index = int(unit_id[1:]) - 1
            order = orders.get(unit_id, "rally")
            if order in {"north", "south"}:
                wx = float(world["defense_post_x"]) + (index % 4) * 0.38
                wy = float(world["lane_y"][order]) + (index // 4 - 0.5) * 0.22
            else:
                wx = float(world["rally"]["x"]) + (index % 5) * 0.35
                wy = float(world["rally"]["y"]) - 0.8 + (index // 5) * 0.32
            x, y = _canvas_point(page, world, wx, wy, camera_x)
            if offset:
                page.keyboard.down("Shift")
            page.mouse.click(x, y)
            if offset:
                page.keyboard.up("Shift")
        visible_ids = set(re.findall(r"[WS]\d+", page.locator("#anthill-selection").inner_text()))
        if visible_ids == expected:
            return
        page.wait_for_timeout(35)
    raise AssertionError(
        f"could not visibly select exact positioned soldier group {sorted(expected)}; "
        f"last visible selection was {sorted(visible_ids)}"
    )


def _visible_formation_y(page, world: dict, raid: dict, camera_x: float) -> float:
    tick = _tick(page)
    image = Image.open(BytesIO(page.locator("#anthill-world").screenshot())).convert("RGB")
    progress = max(0.0, min(1.0, (tick - int(raid["spawn_tick"])) / max(1, int(raid["impact_tick"]) - int(raid["spawn_tick"]))))
    world_x = float(raid["outpost"]["x"]) + (2.8 - float(raid["outpost"]["x"])) * progress
    view = min(float(world["viewport_cells"]), float(world["width"]))
    screen_x = (world_x - camera_x) / view * image.width
    if not 0 <= screen_x < image.width:
        raise AssertionError("moving formation is outside the visible viewport")
    x0, x1 = max(0, int(screen_x - 42)), min(image.width, int(screen_x + 58))
    points: list[int] = []
    for y in range(image.height):
        for x in range(x0, x1):
            r, g, b = image.getpixel((x, y))
            if r > 145 and r - g > 65 and r - b > 45:
                points.append(y)
    if len(points) < 18:
        raise AssertionError(f"no visible formation pixels near expected advance x ({len(points)})")
    return sum(points) / len(points)


def _raid_x_at_tick(raid: dict, tick: int) -> float:
    progress = max(
        0.0,
        min(
            1.0,
            (tick - int(raid["spawn_tick"]))
            / max(1, int(raid["impact_tick"]) - int(raid["spawn_tick"])),
        ),
    )
    return float(raid["outpost"]["x"]) + (2.8 - float(raid["outpost"]["x"])) * progress


def _wait_visible_contact(page, world: dict, raid: dict, camera_x: float, timeout_ms: int = 20_000) -> str:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        wave = page.locator(".anthill-wave").nth(int(raid["wave"]) - 1)
        if wave.count() and "CONTACT IN BAND" in wave.inner_text():
            try:
                before = _visible_formation_y(page, world, raid, camera_x)
                page.wait_for_timeout(90)
                middle = _visible_formation_y(page, world, raid, camera_x)
                page.wait_for_timeout(90)
                after = _visible_formation_y(page, world, raid, camera_x)
                first_delta = middle - before
                second_delta = after - middle
                # Stay clear of a vertical turning point: a direction sampled on the
                # last pre-turn tick can expire before the following pointer event.
                if abs(first_delta) >= 2.5 and abs(second_delta) >= 2.5 and first_delta * second_delta > 0:
                    return "south" if second_delta > 0 else "north"
            except AssertionError:
                pass
        page.wait_for_timeout(70)
    raise AssertionError("a visually moving raid never yielded a readable advance vector")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = _read_json(state_dir / "public_state.json")["challenge_id"]
    page.locator("#anthill-certify").click()
    page.wait_for_function("() => document.querySelector('#anthill-readout')?.textContent.includes('FAIL')", timeout=6_000)
    after = _read_json(state_dir / "public_state.json")["challenge_id"]
    if before == after:
        raise AssertionError("premature front certification did not generate a fresh challenge")
    _shot(page, out_dir, mechanic, "fail-refresh")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    public = _read_json(state_dir / "public_state.json")
    world = public["world"]
    interaction = str((public.get("control_condition") or {}).get("interaction") or "full")
    camera_x = 0.0
    scout_id = "W1"
    dig_crew = [f"W{index + 2}" for index in range(int(world["dig_workers"]))]
    gather_crew = [str(worker["id"]) for worker in world["workers"] if str(worker["id"]) != scout_id and str(worker["id"]) not in dig_crew]
    if not world["hidden_opening"]:
        gather_crew.insert(0, scout_id)

    if interaction == "simplified":
        if dig_crew:
            _select_simplified(page, dig_crew)
            page.locator('[data-simple="dig"]').click()
        if world["hidden_opening"]:
            _select_simplified(page, [scout_id])
            page.locator('[data-simple="scout"]').click()
        _select_simplified(page, gather_crew)
        page.locator('[data-simple="gather"]').click()
    else:
        if dig_crew:
            _select_full_idle_workers(page, world, camera_x, dig_crew)
            page.keyboard.press("d")
            page.mouse.click(*_canvas_point(page, world, float(world["brood"]["x"]), float(world["brood"]["y"]), camera_x))
        if world["hidden_opening"]:
            _select_full_idle_workers(page, world, camera_x, [scout_id])
            page.keyboard.press("s")
            camera_x = _minimap_pan(page, world, float(world["listening_front"]["x"]))
            page.mouse.click(*_canvas_point(page, world, float(world["listening_front"]["x"]), float(world["listening_front"]["y"]), camera_x))
            if f"SCOUT {scout_id} DEPLOYED" not in page.locator("#anthill-intel-body").inner_text():
                raise AssertionError("full-mode scout order did not visibly deploy the selected worker")
            camera_x = _minimap_pan(page, world, 2.0)
        _select_full_idle_workers(page, world, camera_x, gather_crew)
        page.keyboard.press("g")
        page.mouse.click(*_canvas_point(page, world, float(world["seed_pile"]["x"]), float(world["seed_pile"]["y"]), camera_x))

    if world["hidden_opening"]:
        page.wait_for_function("() => document.querySelectorAll('.anthill-wave').length > 0", timeout=12_000)
        _shot(page, out_dir, mechanic, "scout-report")
    page.wait_for_function("() => document.querySelector('#anthill-brood-state')?.textContent === 'READY'", timeout=15_000)

    desired = int(world["enemy_queen"]["hp"]) + sum((int(raid["count"]) + 2) // 3 for raid in world["raids"])
    deadline_tick = int(world["raids"][0]["response_open_tick"]) - 12
    while True:
        soldier_text = page.locator("#anthill-soldiers").inner_text()
        live, queued = (int(part.strip()) for part in soldier_text.split("+"))
        if live + queued >= desired:
            break
        if _tick(page) >= deadline_tick:
            raise AssertionError(f"colony did not raise {desired} soldiers before the first raid")
        seeds = int(page.locator("#anthill-seeds").inner_text())
        if seeds >= int(world["soldier_cost"]):
            if interaction == "simplified":
                page.locator('[data-simple="raise"]').click()
            else:
                page.keyboard.press("r")
        else:
            page.wait_for_timeout(45)
    page.wait_for_function(
        "desired => Number(document.querySelector('#anthill-soldiers').textContent.split('+')[0]) >= desired",
        arg=desired,
        timeout=8_000,
    )

    committed_groups: list[list[str]] = []
    live_soldiers = [f"S{index + 1}" for index in range(desired)]
    soldier_orders = {unit_id: "rally" for unit_id in live_soldiers}
    processed_losses = 0
    overlapping = len(world["raids"]) > 1 and int(world["raids"][1]["response_open_tick"]) <= int(world["raids"][0]["response_deadline_tick"])
    for raid_index, raid in enumerate(world["raids"]):
        if raid_index and not overlapping:
            _wait_tick(page, int(world["raids"][raid_index - 1]["impact_tick"]) + 2)
            previous_group = committed_groups[raid_index - 1]
            losses = min(len(previous_group), (int(world["raids"][raid_index - 1]["count"]) + 2) // 3)
            for unit_id in sorted(previous_group)[:losses]:
                if unit_id in live_soldiers:
                    live_soldiers.remove(unit_id)
                    soldier_orders.pop(unit_id, None)
            processed_losses = raid_index
        if overlapping:
            start = sum(int(item["count"]) for item in world["raids"][:raid_index]) + 1
            unit_ids = [f"S{index}" for index in range(start, start + int(raid["count"]))]
        else:
            unit_ids = list(live_soldiers)
        if interaction == "simplified":
            if overlapping:
                _select_simplified(page, unit_ids)
            else:
                page.locator('[data-select-role="soldiers"]').click()
        else:
            camera_x = _minimap_pan(page, world, float(world["rally"]["x"]))
            _select_full_positioned_soldiers(page, world, camera_x, unit_ids, soldier_orders)
        observation_tick = min(
            int(raid["response_deadline_tick"]) - 2,
            int(raid["response_open_tick"]) + 8,
        )
        camera_x = _minimap_pan(page, world, _raid_x_at_tick(raid, observation_tick))
        lane = _wait_visible_contact(page, world, raid, camera_x)
        if interaction == "simplified":
            page.locator(f'[data-simple="{lane}"]').click()
        else:
            page.keyboard.press("m")
            target_x = camera_x + min(float(world["viewport_cells"]), float(world["width"])) * .35
            page.mouse.click(*_canvas_point(page, world, target_x, float(world["lane_y"][lane]), camera_x))
        committed_groups.append(list(unit_ids))
        for unit_id in unit_ids:
            soldier_orders[unit_id] = lane
        _shot(page, out_dir, mechanic, "defense-committed" if raid_index == 0 else f"wave-{raid_index}-redirect")

    _wait_tick(page, max(int(raid["impact_tick"]) for raid in world["raids"]) + 2)
    for raid_index in range(processed_losses, len(world["raids"])):
        group = committed_groups[raid_index]
        losses = min(len(group), (int(world["raids"][raid_index]["count"]) + 2) // 3)
        for unit_id in sorted(group)[:losses]:
            if unit_id in live_soldiers:
                live_soldiers.remove(unit_id)
                soldier_orders.pop(unit_id, None)

    if interaction == "simplified":
        page.locator('[data-select-role="soldiers"]').click()
        page.locator('[data-simple="enemy"]').click()
    else:
        camera_x = _minimap_pan(page, world, float(world["rally"]["x"]))
        _select_full_positioned_soldiers(page, world, camera_x, live_soldiers, soldier_orders)
        page.keyboard.press("m")
        camera_x = _minimap_pan(page, world, float(world["width"]) - 1.0)
        page.mouse.click(*_canvas_point(page, world, float(world["enemy_queen"]["x"]), float(world["enemy_queen"]["y"]), camera_x))
        expected_readout = f"MARCH → ENEMY · {len(live_soldiers)} ORDERED"
        if expected_readout not in page.locator("#anthill-readout").inner_text():
            raise AssertionError("full-mode final assault was not visibly accepted")
    page.wait_for_function("() => document.querySelector('#anthill-verdict')?.textContent.includes('VICTORY')", timeout=12_000)
    _shot(page, out_dir, mechanic, "victory-visible")
    page.locator("#anthill-certify").click()
    page.wait_for_function("() => document.querySelector('#anthill-readout')?.textContent.startsWith('PASS')", timeout=8_000)
