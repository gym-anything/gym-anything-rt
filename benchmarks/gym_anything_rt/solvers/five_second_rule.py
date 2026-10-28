from __future__ import annotations

import json
import time
from pathlib import Path


MECHANIC_ID = "five_second_rule"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_fresh(state_dir: Path, previous: str) -> str:
    deadline = time.time() + 8
    while time.time() < deadline:
        current = str(_read(state_dir / "ground_truth.json").get("challenge_id") or "")
        if current and current != previous:
            return current
        time.sleep(.04)
    raise AssertionError("five-second failure did not issue a fresh challenge")


def _center(locator) -> tuple[float, float]:
    box = locator.bounding_box()
    if not box:
        raise AssertionError("visible control has no geometry")
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _wait_round(page, round_spec: dict) -> None:
    page.wait_for_function(
        "roundId => document.querySelector('.five-second-rule') && document.querySelector('.fsr-order')?.textContent && document.querySelector(`[data-token-id]`) && window.getComputedStyle(document.querySelector('.fsr-stage')).display !== 'none' && document.querySelector('.fsr-status small')?.textContent",
        arg=round_spec["id"],
        timeout=7_000,
    )
    page.wait_for_selector(f'.fsr-stage.family-{round_spec["family"]}', state="visible", timeout=7_000)


def _wrong_id(round_spec: dict, expected: str) -> str:
    return next(item["id"] for item in round_spec["tokens"] if item["id"] != expected)


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    del out_dir
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    before = str(truth["challenge_id"])
    mode = str((truth.get("control_condition") or {}).get("interaction") or "full")
    spec = truth["rounds"][0]
    _wait_round(page, spec)
    family = spec["family"]
    if family == "gate_tag":
        wrong = _wrong_id(spec, spec["predicate"]["target_id"])
        page.locator(f'[data-{"token-id" if mode == "full" else "proxy-tag"}="{wrong}"]').click(force=True)
    elif family == "relay_pair":
        wrong = _wrong_id(spec, spec["predicate"]["first_id"])
        page.locator(f'[data-{"token-id" if mode == "full" else "proxy-tap"}="{wrong}"]').click(force=True)
    elif family == "sync_hold":
        wrong = _wrong_id(spec, spec["predicate"]["target_id"])
        node = page.locator(f'[data-{"token-id" if mode == "full" else "proxy-hold"}="{wrong}"]')
        page.mouse.move(*_center(node)); page.mouse.down(); page.wait_for_timeout(40); page.mouse.up()
    elif family == "vector_flick":
        wrong = _wrong_id(spec, spec["predicate"]["target_id"])
        if mode == "simplified":
            page.locator(f'[data-proxy-select="{wrong}"]').click()
            page.locator('[data-proxy-direction="NORTH"]').click()
        else:
            x, y = _center(page.locator(f'[data-token-id="{wrong}"]'))
            page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 80, y, steps=3); page.mouse.up()
    else:
        wrong = _wrong_id(spec, spec["predicate"]["target_id"])
        if mode == "simplified":
            page.locator(f'[data-proxy-select="{wrong}"]').click()
            page.locator(f'[data-proxy-bay="{spec["predicate"]["bay_id"]}"]').click()
        else:
            start = _center(page.locator(f'[data-token-id="{wrong}"]'))
            end = _center(page.locator(f'[data-bay-id="{spec["predicate"]["bay_id"]}"]'))
            page.mouse.move(*start); page.mouse.down(); page.mouse.move(*end, steps=4); page.mouse.up()
    _wait_fresh(state_dir, before)
    page.wait_for_selector('.five-second-rule[data-fresh-failure="true"]', state="visible", timeout=8_000)
    page.wait_for_selector('.fsr-verdict.is-fail', state="visible", timeout=8_000)


def _solve_gate(page, spec: dict, mode: str) -> None:
    target_id = spec["predicate"]["target_id"]
    page.wait_for_function(
        "target => document.querySelector(`[data-token-id=\"${target}\"]`)?.classList.contains('is-in-gate')",
        arg=target_id,
        polling=8,
        timeout=5_000,
    )
    target = next(item for item in spec["tokens"] if item["id"] == target_id)
    page.wait_for_timeout(int(spec["gate"]["half_width"] / abs(float(target["motion"]["vx"])) * 1000))
    if mode == "simplified":
        page.locator(f'[data-proxy-tag="{target_id}"]').click()
    else:
        page.mouse.click(*_center(page.locator(f'[data-token-id="{target_id}"]')))


def _solve_hold(page, spec: dict, mode: str) -> None:
    target_id = spec["predicate"]["target_id"]
    page.wait_for_function(
        "() => document.querySelector('.fsr-sweep-board')?.classList.contains('is-ready')",
        polling=5,
        timeout=5_000,
    )
    node = page.locator(f'[data-{"proxy-hold" if mode == "simplified" else "token-id"}="{target_id}"]')
    page.mouse.move(*_center(node)); page.mouse.down()
    page.wait_for_function(
        "() => document.querySelector('.fsr-sweep-board')?.classList.contains('is-release')",
        polling=5,
        timeout=3_000,
    )
    page.mouse.up()


def _solve_flick(page, spec: dict, mode: str) -> None:
    target_id = spec["predicate"]["target_id"]
    direction = spec["flick"]["flick_direction"]
    drag = None
    if mode == "simplified":
        # Token selection is untimed but the direction send is not. Select
        # first so the timed action is a single visible click.
        page.locator(f'[data-proxy-select="{target_id}"]').click()
    else:
        # Put the pointer on the visible token before waiting for the narrow
        # orientation window. Bounding-box lookup and the first mouse move can
        # otherwise consume most of L5's 15-degree window on a loaded host.
        vectors = {"NORTH": (0, -1), "EAST": (1, 0), "SOUTH": (0, 1), "WEST": (-1, 0)}
        dx, dy = vectors[direction]
        distance = float(spec["flick"]["min_travel_px"]) + 24
        stage = page.locator('.fsr-stage').bounding_box()
        if not stage:
            raise AssertionError("flick field is not visible")
        x, y = _center(page.locator(f'[data-token-id="{target_id}"]'))
        page.mouse.move(x, y)
        # Travel is graded in the 820×390 field, not viewport pixels. The
        # rendered field can stretch independently along its two axes.
        drag = (x, y, dx * stage['width'] / 820, dy * stage['height'] / 390, distance)
    page.wait_for_function(
        "([face, tolerance]) => { const raw = getComputedStyle(document.querySelector('[data-pointer-for]')).getPropertyValue('--angle'); const angle = Number.parseFloat(raw); const diff = Math.abs(((angle - face + 540) % 360) - 180); return diff <= tolerance * .35; }",
        arg=[spec["flick"]["face_angle_deg"], spec["flick"]["angle_tolerance_deg"]],
        polling=5,
        timeout=5_000,
    )
    if mode == "simplified":
        page.locator(f'[data-proxy-direction="{direction}"]').click()
        return
    assert drag is not None
    x, y, dx, dy, distance = drag
    page.mouse.down(); page.mouse.move(x + dx * distance, y + dy * distance); page.mouse.up()


def _solve_relay(page, spec: dict, mode: str) -> None:
    attribute = "proxy-tap" if mode == "simplified" else "token-id"
    page.locator(f'[data-{attribute}="{spec["predicate"]["first_id"]}"]').click()
    page.locator(f'[data-{attribute}="{spec["predicate"]["second_id"]}"]').click()


def _solve_drop(page, spec: dict, mode: str) -> None:
    target_id = spec["predicate"]["target_id"]
    bay_id = spec["predicate"]["bay_id"]
    drag = None
    if mode == "simplified":
        # Cargo selection has no physical timing effect, so perform it before
        # waiting for the shutter's visible opening.
        page.locator(f'[data-proxy-select="{target_id}"]').click()
    else:
        start = _center(page.locator(f'[data-token-id="{target_id}"]'))
        end = _center(page.locator(f'[data-bay-id="{bay_id}"]'))
        page.mouse.move(*start)
        drag = (start, end)
    page.wait_for_function(
        "bay => { const node = document.querySelector(`[data-bay-id=\"${bay}\"]`); return node?.classList.contains('is-open') && Number.parseFloat(node.style.getPropertyValue('--aperture')) >= .85; }",
        arg=bay_id,
        polling=8,
        timeout=5_000,
    )
    if mode == "simplified":
        page.locator(f'[data-proxy-bay="{bay_id}"]').click()
        return
    assert drag is not None
    _start, end = drag
    page.mouse.down(); page.mouse.move(*end, steps=5); page.mouse.up()


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    del out_dir
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    truth = _read(state_dir / "ground_truth.json")
    mode = str((truth.get("control_condition") or {}).get("interaction") or "full")
    solvers = {
        "gate_tag": _solve_gate,
        "sync_hold": _solve_hold,
        "vector_flick": _solve_flick,
        "relay_pair": _solve_relay,
        "shutter_drop": _solve_drop,
    }
    for spec in truth["rounds"]:
        _wait_round(page, spec)
        solvers[spec["family"]](page, spec, mode)
    page.wait_for_selector('.fsr-verdict.is-pass', state="visible", timeout=8_000)
