from __future__ import annotations

import json
import math
import time
from pathlib import Path
from playwright.sync_api import expect
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.elastic_membrane_sorter_v2 import _drift

MECHANIC_ID = "elastic_membrane_sorter_v2"

def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{label}.png"), full_page=True)


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    page.locator("#membrane-abandon").click()
    expect(page.locator(".ivv-verdict.is-fresh")).to_be_visible(timeout=8_000)
    deadline = time.time() + 8
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json")["challenge_id"]) != before:
            break
        time.sleep(.05)
    else:
        raise AssertionError(f"{mechanic} failure did not issue a fresh challenge")
    _shot(page, out_dir, mechanic, "fail-fresh")
    expect(page.locator(".ivv-verdict.is-fresh")).to_be_hidden(timeout=3_000)


def _adjust_range(page, selector: str, target: int) -> None:
    control = page.locator(selector)
    current = int(float(control.input_value()))
    target = int(target)
    if current == target:
        return
    box=control.bounding_box()
    if not box:
        raise AssertionError("visible tension slider missing")
    page.mouse.click(box["x"]+8+(box["width"]-16)*target/100,box["y"]+box["height"]/2)
    current=int(float(control.input_value()))
    key = "ArrowRight" if target > current else "ArrowLeft"
    for _ in range(abs(target - current)):
        page.keyboard.press(key)


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
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
            "(index) => ({height: window.elasticMembraneSorterV2Model.heights[index], tick:elasticMembraneSorterV2Model.elapsedTicks+elasticMembraneSorterV2Model.ticks, point: window.elasticMembraneSorterV2Model.state.post_positions[index]})",
            index,
        )
        offset = _drift(truth["physics"],snapshot["tick"])[index]
        current = max(0,min(1,float(snapshot["height"])+offset))
        point = snapshot["point"]
        start_x = box["x"] + float(point[0]) / 900 * box["width"]
        start_y = box["y"] + (float(point[1]) + (.5 - current) * 80) / 480 * box["height"]
        end_y = box["y"] + (float(point[1]) + (.5 - max(0,min(1,float(target) / 100+offset))) * 80) / 480 * box["height"]
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
        tick = page.evaluate("elasticMembraneSorterV2Model.elapsedTicks+elasticMembraneSorterV2Model.ticks")
        initial = [max(0, min(100, round(100 * (value-offset)))) for value,offset in zip((.5 + hx + hy, .5 - hx + hy, .5 + hx - hy, .5 - hx - hy),_drift(truth["physics"],tick))]
        for post, value in enumerate(initial):
            adjust_post(post, value)
        if index == 0:
            page.locator("#membrane-release").click()
        last_control = -10
        photographed = False
        deadline = time.time() + 32
        while time.time() < deadline:
            if page.locator(".ivv-verdict.is-pass").count() and page.locator(".ivv-verdict.is-pass").is_visible():
                break
            snapshot = page.evaluate("() => {const m=window.elasticMembraneSorterV2Model;return {roundIndex:m.roundIndex,ticks:m.ticks,globalTick:m.elapsedTicks+m.ticks,checkpoint:m.checkpoint,ball:{...m.ball},running:m.running}}")
            if int(snapshot["roundIndex"]) > index:
                break
            if not snapshot["running"] and int(snapshot["ticks"]) >= int(truth["physics"]["max_ticks"]):
                raise AssertionError("closed-loop membrane controller reached the visible simulation limit")
            if int(snapshot["globalTick"]) - last_control >= 6:
                checkpoint = int(snapshot["checkpoint"])
                target = round_data["checkpoints"][checkpoint] if checkpoint < len(round_data["checkpoints"]) else round_data["wells"][round_data["target_well"]]
                ball = snapshot["ball"]
                fx = max(-.048, min(.048, .004 * (float(target[0]) - float(ball["x"])) - .09 * float(ball["vx"])))
                fy = max(-.048, min(.048, .004 * (float(target[1]) - float(ball["y"])) - .09 * float(ball["vy"])))
                hx, hy = fx / scale, fy / scale
                targets = [max(0, min(100, round(100 * (value-offset)))) for value,offset in zip((.5 + hx + hy, .5 - hx + hy, .5 + hx - hy, .5 - hx - hy),_drift(truth["physics"],snapshot["globalTick"]))]
                for post, value in enumerate(targets):
                    adjust_post(post, value)
                last_control = int(snapshot["globalTick"])
            if index == 0 and int(snapshot["checkpoint"]) == 1 and not photographed:
                _shot(page, out_dir, mechanic, "live-steering-between-rings")
                photographed = True
            page.wait_for_timeout(28)
        else:
            raise AssertionError(f"membrane round {index + 1} did not capture")
    expect(page.locator(".ivv-verdict.is-pass")).to_be_visible(timeout=10_000)
