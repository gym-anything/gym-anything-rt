from __future__ import annotations

import json
import time
from pathlib import Path

from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.ballast_lantern import _control_for_target


MECHANIC_ID = "ballast_lantern"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _screenshot(page, out_dir: Path, mechanic: str, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / f"{mechanic}-{name}.png"), full_page=True)


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    from playwright.sync_api import expect

    before = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    page.locator(".ballast-abandon").click()
    expect(page.locator(".ballast-foot .readout")).to_contain_text("FAIL", timeout=7000)
    after = str(_read(state_dir / "ground_truth.json")["challenge_id"])
    if before == after:
        raise AssertionError("Ballast Lantern did not regenerate after deliberate failure")
    _screenshot(page, out_dir, mechanic, "fail-refresh")


def _click_winch(page, engaged: bool) -> None:
    box = page.locator(".ballast-haul" if engaged else ".ballast-coast").bounding_box()
    if box is None:
        raise AssertionError("Ballast Lantern winch button is not visible")
    # The live shaft can finish after observation but before input delivery.
    # A native click on its now-disabled button is harmless; locator.click()
    # would wait for it to become enabled again even though the run is over.
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    from playwright.sync_api import expect

    truth = _read(state_dir / "ground_truth.json")
    parameters = truth["parameters"]
    crate = truth["crate"]
    interaction = str((truth.get("control_condition") or {}).get("interaction") or "full")
    paused_mode = page.evaluate("() => new URLSearchParams(location.search).get('time_mode') === 'paused'")
    decision_interval = max(1, 600 // parameters["tick_ms"]) if paused_mode else 1
    next_decision = 0
    crate_mode = False
    low_reserve = max(1200, parameters["capture_initial"] * 2 // 5)
    high_reserve = min(parameters["capture_max"] - 1600, parameters["capture_initial"] + 1100)
    deadline = time.monotonic() + parameters["max_ticks"] * parameters["tick_ms"] / 1000 + 30
    try:
        while time.monotonic() < deadline:
            observed = page.evaluate("""() => ({
                challenge: ballastLanternModel.state.challenge_id,
                sim: ballastLanternModel.sim, engaged: ballastLanternModel.engaged,
                completed: ballastLanternModel.completed,
            })""")
            if observed["challenge"] != truth["challenge_id"]:
                raise AssertionError("Ballast Lantern failed and regenerated during the reference solve")
            sim = observed["sim"]
            if sim["status"] != "active":
                if sim["status"] != "secured":
                    raise AssertionError(f"Ballast Lantern ended with {sim['status']}: {sim}")
                if observed["completed"]:
                    break
                time.sleep(.01)
                continue
            if sim["tick"] < next_decision:
                time.sleep(.005)
                continue
            # Reuse the generator's feedback policy, not its tick-zero replay.
            # Host observation/capture latency may have changed the cage state.
            if sim["tick"] >= crate["spawn_tick"] and sim["crate_meter"] < parameters["crate_meter_max"]:
                if sim["capture_meter"] <= low_reserve:
                    crate_mode = False
                elif sim["capture_meter"] >= high_reserve:
                    crate_mode = True
            else:
                crate_mode = False
            desired = (_control_for_target(sim, crate["y"]) if crate_mode else
                       _control_for_target(sim, sim["specimen_y"], sim["specimen_velocity"]))
            if desired != observed["engaged"]:
                if interaction == "full":
                    (page.keyboard.down if desired else page.keyboard.up)("Space")
                else:
                    _click_winch(page, desired)
            next_decision = (sim["tick"] // decision_interval + 1) * decision_interval
            if paused_mode:
                page.evaluate("ms => GymAnythingRTTime.runFor(ms)", (next_decision - sim["tick"]) * parameters["tick_ms"])
                while page.evaluate("GymAnythingRTTime.status().phase") != "completed":
                    if time.monotonic() >= deadline:
                        raise AssertionError("Ballast Lantern observation window did not complete")
                    time.sleep(.005)
        else:
            raise AssertionError("Ballast Lantern reference solve exceeded its deadline")
    finally:
        if interaction == "full":
            page.keyboard.up("Space")
    expect(page.locator(".ballast-foot .readout")).to_have_attribute("data-status", "passed")
    _screenshot(page, out_dir, mechanic, "pass")
