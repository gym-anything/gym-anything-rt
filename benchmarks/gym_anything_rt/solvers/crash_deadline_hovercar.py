from __future__ import annotations

import json
import math
import time
from pathlib import Path

from playwright.sync_api import expect


MECHANIC_ID = "crash_deadline_hovercar"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shot(page, out_dir: Path, mechanic: str, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True); page.screenshot(path=str(out_dir / f"{mechanic}-{name}.png"), full_page=True)


def _wait_new(state_dir: Path, previous: str) -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        if str(_read(state_dir / "ground_truth.json").get("challenge_id")) != previous: return
        time.sleep(.05)
    raise AssertionError("hovercar challenge did not regenerate after rejection")


def _interaction(truth: dict) -> str:
    return str((truth.get("control_condition") or {}).get("interaction") or "full")


def _set_drive(page, current: set[str], key: str, down: bool, interaction: str) -> None:
    if down and key in current or not down and key not in current:
        return
    if interaction == "simplified":
        page.locator(f".hover-proxy-key[data-key='{key}']").click()
    else:
        physical_key = {"up": "w", "down": "s", "left": "a", "right": "d"}[key]
        if down:
            page.keyboard.down(physical_key)
        else:
            page.keyboard.up(physical_key)
    if down:
        current.add(key)
    else:
        current.remove(key)


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID: raise AssertionError(mechanic)
    # Exercise symmetric road-departure collision and humane local retry on the
    # course that will be discarded, preserving a clean final flight record.
    interaction = _interaction(_read(state_dir / "ground_truth.json"))
    held: set[str] = set()
    _set_drive(page, held, "up", True, interaction); _set_drive(page, held, "right", True, interaction)
    expect(page.locator(".hover-crash[data-visible='true']")).to_be_visible(timeout=4_000)
    _set_drive(page, held, "right", False, interaction); _set_drive(page, held, "up", False, interaction)
    _shot(page, out_dir, mechanic, "road-departure-crash")
    page.locator(".hover-retry").click(); expect(page.locator(".readout")).to_contain_text("RE-ARMED")
    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    page.locator(".hover-submit").click(); _wait_new(state_dir, before)
    expect(page.locator(".hovercar-captcha[data-fresh-failure='true']")).to_be_visible(timeout=8_000); expect(page.locator(".readout")).to_contain_text("FAIL"); _shot(page, out_dir, mechanic, "fail-fresh-course")


def _road(progress: float, physics: dict) -> float:
    return 240 + physics["road_amplitude"] * math.sin(progress / physics["road_period"] + physics["road_phase"])


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID: raise AssertionError(mechanic)
    truth = _read(state_dir / "ground_truth.json"); interaction = _interaction(truth); physics = truth["physics"]; box = page.locator(".hover-canvas").bounding_box()
    if not box: raise AssertionError("hovercar flight canvas missing")
    if interaction == "simplified":
        page.locator(".hover-proxy-track").click()
    held: set[str] = set(); first_dwell_shot = False; deadline = time.time() + 22
    while time.time() < deadline:
        snapshot = page.evaluate("""() => { const m=window.crashDeadlineHovercarModel; const active=m.state.targets.find(t=>!m.checks.has(t.id)&&m.tick>=t.window_start&&m.tick<=t.window_end); return {tick:m.tick,progress:m.progress,lateral:m.lateral,velocity:m.lateralVelocity,speed:m.speed,checks:[...m.checks],crashed:m.crashed,finished:m.finished,active:active?{id:active.id,point:m.targetPoint(active)}:null}; }""")
        if snapshot["crashed"]:
            _shot(page, out_dir, mechanic, "unexpected-solver-crash")
            (out_dir / f"{mechanic}-unexpected-solver-crash.json").write_text(
                json.dumps({"snapshot": snapshot, "truth": truth}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raise AssertionError(f"hovercar crashed during controlled solve at {snapshot}")
        if snapshot["finished"]: break
        desired_offset = 0.0
        # The narrow L5 road leaves only 88 px of lateral travel after the
        # hovercar body is accounted for.  Begin an obstacle bypass early
        # enough for the damped steering model to settle on the far side of
        # the lane marker instead of starting the turn inside collision range.
        # The policy remains a browser-driving smoke helper; the puzzle's
        # visible physics and authoritative grader retain the same geometry.
        bypass_range = 175 if int(physics["road_half_width"]) <= 105 else 135
        # A modest offset clears either ±30 px barrier lane by more than a car
        # width.  The narrow L5 course needs a little more clearance; broader
        # courses retain extra road-following recovery room instead of aiming
        # close to their edge during a damped turn.
        clearance = 60.0 if int(physics["road_half_width"]) <= 105 else 52.0
        clearance = min(clearance, float(physics["road_half_width"]) - float(physics["car_half_height"]) - 20.0)
        for obstacle in truth["obstacles"]:
            distance = float(obstacle["world_x"]) - snapshot["progress"]
            if -48 <= distance <= bypass_range:
                desired_offset = -clearance if float(obstacle["lane_offset"]) > 0 else clearance
                break
        # Full throttle finishes before the late checks.  The longer L5 course
        # cruises faster between barriers, then has a visible speed-planning
        # margin while it shifts lanes on its narrow, damped road.
        cruise = 56 if float(physics["finish_progress"]) > 1_500 else 47
        if desired_offset and float(physics["finish_progress"]) > 1_500:
            cruise = 53
        _set_drive(page, held, "up", snapshot["speed"] < cruise - 3, interaction)
        _set_drive(page, held, "down", snapshot["speed"] > cruise + 3, interaction)
        desired = _road(snapshot["progress"], physics) + desired_offset
        control = desired - snapshot["lateral"] - snapshot["velocity"] * 3.0
        _set_drive(page, held, "right", control > 1.5, interaction); _set_drive(page, held, "left", control < -1.5, interaction)
        if snapshot["active"] and interaction == "full":
            point = snapshot["active"]["point"]; page.mouse.move(box["x"] + point[0] / truth["stage"]["width"] * box["width"], box["y"] + point[1] / truth["stage"]["height"] * box["height"], steps=2)
            if not first_dwell_shot and snapshot["tick"] > truth["targets"][0]["window_start"] + 4:
                _shot(page, out_dir, mechanic, "simultaneous-drive-hover-dwell"); first_dwell_shot = True
        # Poll considerably faster than the 50 ms fixed physics step.  A
        # browser click can land just before or after a tick; polling once per
        # step made narrow L5 obstacle transitions depend on that scheduling
        # race.  The visible controls and replayed physics are unchanged.
        page.wait_for_timeout(12)
    for key in list(held): _set_drive(page, held, key, False, interaction)
    expect(page.locator(".hover-finish[data-visible='true']")).to_be_visible(timeout=4_000)
    finished = page.evaluate("() => ({checks:[...window.crashDeadlineHovercarModel.checks].sort(),finished:window.crashDeadlineHovercarModel.finished,crashes:window.crashDeadlineHovercarModel.crashes,retries:window.crashDeadlineHovercarModel.retries,samples:window.crashDeadlineHovercarModel.pointerSamples,tick:window.crashDeadlineHovercarModel.tick})")
    minimum_samples = max(10, len(truth["targets"]) * 5)
    if not finished["finished"] or len(finished["checks"]) != len(truth["targets"]) or finished["crashes"] != 0 or finished["retries"] != 0 or finished["samples"] < minimum_samples: raise AssertionError(f"clean divided-attention run incomplete: {finished}")
    _shot(page, out_dir, mechanic, "solved-pre-submit"); page.locator(".hover-submit").click(); expect(page.locator(".readout")).to_have_text("PASS", timeout=8_000)
