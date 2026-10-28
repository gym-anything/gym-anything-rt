from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import expect

from benchmarks.gym_anything_rt.solvers.reviewed_overhaul_common import (
    center, expect_fail_and_fresh, read_json, shot,
)

MECHANIC_ID = "reload_interruption_v2"
VECTORS = {"up": (0, -62), "right": (62, 0), "down": (0, 62), "left": (-62, 0)}


def _interaction(state: dict) -> str:
    return str((state.get("control_condition") or {}).get("interaction") or "full")


def _gesture(page, direction: str, interaction: str) -> None:
    if interaction == "simplified":
        page.locator(f'[data-reload-direction="{direction}"]').click()
        return
    lever = page.locator(".reload-v2-lever")
    x, y = center(lever)
    dx, dy = VECTORS[direction]
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=5)
    page.mouse.up()


def _clear_overload(page, interaction: str, spec: dict) -> None:
    if interaction == "simplified":
        stabilizer = page.locator(".overload-proxy")
        expect(stabilizer).to_be_visible(timeout=3_000)
        x, y = center(stabilizer)
        page.mouse.move(x, y)
        page.mouse.down()
        page.wait_for_timeout(int(spec["hold_ms"]) + 220)
        page.mouse.up()
        expect(page.locator(".reload-overload")).to_have_count(0, timeout=3_000)
        return
    spark = page.locator(".overload-spark")
    expect(spark).to_be_visible(timeout=3_000)
    stage = page.locator(".reload-v2-stage")
    stage_box = stage.bounding_box()
    if not stage_box:
        raise AssertionError("reload stage is not physically visible")
    # Let the browser's normal visible hit-testing place the pointer on the
    # animated spark immediately before the hold begins.  A stale box from a
    # prior painted frame can otherwise land on the decorative orbit.
    spark.hover(force=True, timeout=1_000)
    x, y = center(spark)
    page.mouse.move(x, y)
    page.mouse.down()
    started = time.monotonic()
    deadline = started + int(spec["hold_ms"]) / 1_000 + .20
    while time.monotonic() < deadline:
        bounds = spark.bounding_box()
        if bounds is None:
            raise AssertionError("moving spark disappeared")
        page.mouse.move(
            bounds["x"] + bounds["width"]/2,
            bounds["y"] + bounds["height"]/2,
            steps=1,
        )
        page.wait_for_timeout(16)
    page.mouse.up()
    expect(page.locator(".reload-overload")).to_have_count(0, timeout=3_000)


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    assert mechanic == MECHANIC_ID
    truth = read_json(state_dir / "ground_truth.json")
    state = read_json(state_dir / "public_state.json")
    before = truth["challenge_id"]
    expect(page.locator(".reload-v2.is-ready")).to_be_visible(timeout=8_000)
    wrong = next(item for item in VECTORS if item != truth["sequence"][0])
    _gesture(page, wrong, _interaction(state))
    expect_fail_and_fresh(page, state_dir, before)
    shot(page, out_dir, mechanic, "real-memory-gesture-rejection")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    assert mechanic == MECHANIC_ID
    state = read_json(state_dir / "public_state.json")
    interaction = _interaction(state)
    expect(page.locator(".reload-v2.is-ready")).to_be_visible(timeout=8_000)
    interruption_steps = {int(item["after_step"]) for item in state["interruptions"]}
    for index, direction in enumerate(state["sequence"], start=1):
        _gesture(page, direction, interaction)
        if index in interruption_steps:
            shot(page, out_dir, mechanic, f"moving-overload-{index}")
            spec = next(item for item in state["interruptions"] if int(item["after_step"]) == index)
            _clear_overload(page, interaction, spec)
    # The final accepted gesture triggers the task's shared virtual submit
    # timer.  Keep the visible action cycle running until it resolves so a
    # paused evaluator does not freeze the task halfway through submission.
    page.wait_for_timeout(1_000)
