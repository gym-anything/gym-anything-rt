from __future__ import annotations

import json
import math
import time
from pathlib import Path


MECHANIC_ID = "microgame_gauntlet"


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
    raise AssertionError("reactor failure did not issue a fresh challenge")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    page.locator("#gauntlet-certify").click()
    _wait_fresh(state_dir, before)
    page.wait_for_selector('.gauntlet-reactor[data-fresh-failure="true"]', timeout=7_000)
    page.wait_for_function("() => document.querySelector('.readout')?.textContent.includes('FAIL')")
    _shot(page, out_dir, mechanic, "fail-refresh")


def _wait_round(page, round_data: dict) -> None:
    page.wait_for_function(
        "roundId => document.querySelector('.gauntlet-reactor')?.dataset.roundId === roundId",
        arg=round_data["id"], timeout=7_000,
    )


def _dial_point(box: dict, angle: float, radius: float = 88) -> tuple[float, float]:
    radians = math.radians(angle)
    return box["x"] + box["width"] / 2 + math.cos(radians) * radius, box["y"] + box["height"] / 2 + math.sin(radians) * radius


def solve(page, state_dir: Path, out_dir: Path, mechanic: str, start_round_index: int = 0) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    if not 0 <= start_round_index < len(truth["rounds"]):
        raise AssertionError(f"invalid Microgame Gauntlet start round {start_round_index}")
    for round_index, round_data in enumerate(truth["rounds"][start_round_index:], start=start_round_index):
        _wait_round(page, round_data)
        round_type = round_data["type"]
        if round_type == "pressure":
            if interaction == "simplified":
                page.locator("#pressure-proxy-engage").click()
            else:
                page.keyboard.down("Space")
            for pulse in round_data["pulses"]:
                page.locator(f'[data-pulse-id="{pulse["id"]}"]').click()
                page.wait_for_timeout(35)
            if round_index < 3:
                _shot(page, out_dir, mechanic, "active-pressure-hold")
            if interaction == "simplified":
                page.locator("#pressure-proxy-release").click()
            else:
                page.keyboard.up("Space")
        elif round_type == "chord":
            if interaction == "simplified":
                for chord_index, _chord in enumerate(round_data["chords"]):
                    page.locator("#chord-proxy-engage").click()
                    page.locator("#chord-proxy-release").wait_for(state="visible")
                    page.wait_for_function("() => !document.getElementById('chord-proxy-release')?.disabled", timeout=5_000)
                    if chord_index == 1 or (len(round_data["chords"]) == 1 and chord_index == 0):
                        _shot(page, out_dir, mechanic, "active-three-stage-chord")
                    page.locator("#chord-proxy-release").click()
                    if chord_index < len(round_data["chords"]) - 1:
                        page.wait_for_function("index => document.querySelector(`[data-chord-stage=\"${index}\"]`)?.dataset.status === 'active'", arg=chord_index + 1)
            else:
                for chord_index, (first, second) in enumerate(round_data["chords"]):
                    page.keyboard.down(first)
                    page.keyboard.down(second)
                    page.wait_for_timeout(int(round_data["required_ticks"] * round_data["tick_ms"] + 180))
                    if chord_index == 1 or (len(round_data["chords"]) == 1 and chord_index == 0):
                        _shot(page, out_dir, mechanic, "active-three-stage-chord")
                    page.keyboard.up(first)
                    page.keyboard.up(second)
                    if chord_index < len(round_data["chords"]) - 1:
                        page.wait_for_function("index => document.querySelector(`[data-chord-stage=\"${index}\"]`)?.dataset.status === 'active'", arg=chord_index + 1)
        elif round_type == "dial":
            if interaction == "simplified":
                start = float(round_data["start_angle"])
                target = float(round_data["target_angle"])
                tolerance = float(round_data["target_tolerance"])
                candidates: list[tuple[float, int, int]] = []
                for direction in (-1, 1):
                    for turns in range(2, 34):
                        first_coast_angle = (start + direction * 12 * (turns + 1)) % 360
                        distance = abs((first_coast_angle - target + 180) % 360 - 180)
                        candidates.append((distance, direction, turns))
                distance, direction, turns = min(candidates)
                if distance > tolerance:
                    raise AssertionError(f"no calibrated simplified dial launch reaches the visible brake sector: {distance} > {tolerance}")
                page.locator("#dial-proxy-begin").click()
                turn = "#dial-proxy-cw" if direction > 0 else "#dial-proxy-ccw"
                for _ in range(turns):
                    page.locator(turn).click()
                page.locator("#dial-proxy-release").click()
            else:
                dial = page.locator("#gauntlet-dial")
                box = dial.bounding_box()
                if not box:
                    raise AssertionError("dial has no physical geometry")
                target = float(round_data["target_angle"])
                angles = [target - 90, target - 75, target - 60, target - 45]
                start = _dial_point(box, angles[0])
                page.mouse.move(*start)
                page.mouse.down()
                for angle in angles[1:]:
                    page.mouse.move(*_dial_point(box, angle))
                    page.wait_for_timeout(25)
                page.mouse.up()
            _shot(page, out_dir, mechanic, "active-inertial-coast")
            page.wait_for_function(
                "() => document.getElementById('gauntlet-brake')?.dataset.inZone === 'true'",
                polling=4,
                timeout=6_000,
            )
            page.locator("#gauntlet-brake").click(force=True)
        elif round_type == "intercept":
            page.locator("#intercept-proxy-arm" if interaction == "simplified" else "#intercept-arm").click()
            page.wait_for_timeout(120)
            _shot(page, out_dir, mechanic, "active-moving-intercept")
            for packet_index, _packet in enumerate(round_data["packets"]):
                page.wait_for_function(
                    "() => document.getElementById('intercept-target')?.dataset.inGate === 'true'",
                    polling=4,
                    timeout=6_000,
                )
                if interaction == "simplified":
                    page.locator("#intercept-proxy-capture").click(force=True)
                else:
                    target_box = page.locator("#intercept-target").bounding_box()
                    if not target_box:
                        raise AssertionError("moving intercept target has no visible geometry")
                    page.mouse.click(
                        target_box["x"] + target_box["width"] / 2,
                        target_box["y"] + target_box["height"] / 2,
                    )
                if packet_index < len(round_data["packets"]) - 1:
                    page.wait_for_function("index => document.querySelector(`[data-packet-mark=\"${index}\"]`)?.dataset.status === 'captured'", arg=packet_index)
        elif round_type == "route":
            points = round_data["points"]
            if interaction == "simplified":
                for point_index in range(len(points)):
                    page.locator(f'.route-hoop-select[data-point="{point_index}"]').click()
                    if point_index == max(0, len(points) - 2):
                        _shot(page, out_dir, mechanic, "active-balance-route")
            else:
                pad = page.locator("#route-pad")
                box = pad.bounding_box()
                if not box:
                    raise AssertionError("route pad has no physical geometry")
                def screen(point: dict) -> tuple[float, float]:
                    return box["x"] + box["width"] * float(point["x"]) / 100, box["y"] + box["height"] * float(point["y"]) / 100
                page.mouse.move(*screen(points[0]))
                page.mouse.down()
                for point in points[1:]:
                    page.mouse.move(*screen(point), steps=3)
                _shot(page, out_dir, mechanic, "active-balance-route")
                page.mouse.up()
        else:
            raise AssertionError(f"unknown reactor round {round_type!r}")
        if round_index < len(truth["rounds"]) - 1:
            page.wait_for_function("index => Number(document.getElementById('gauntlet-round-counter')?.textContent.split('/')[0].trim()) === index", arg=round_index + 2, timeout=7_000)
    page.wait_for_function("() => document.querySelector('.gauntlet-reactor')?.dataset.roundType === 'complete'", timeout=7_000)
    _shot(page, out_dir, mechanic, "solved-five-rounds")
    page.locator("#gauntlet-certify").click()
    page.wait_for_function("() => document.querySelector('.readout')?.textContent === 'PASS'", timeout=8_000)
