"""Privileged flight planning; effects are native pointer moves/button clicks."""
from __future__ import annotations

import json
import math
from pathlib import Path

from playwright.sync_api import expect

MECHANIC_ID = "cloudpost_circuit"


def _control_for(plane: dict[str, float], target: dict, physics: dict) -> list[float]:
    dx, dy, dz = (float(target[key])-plane[key] for key in ("x","y","z"))
    distance = max(1e-6, math.sqrt(dx*dx+dy*dy+dz*dz))
    return [max(-1.0,min(1.0,math.atan2(dx,dz)/physics["max_yaw"])),
            max(-1.0,min(1.0,math.asin(max(-1.0,min(1.0,dy/distance)))/physics["max_pitch"]))]


def _read_public(state_dir: Path) -> dict:
    return json.loads((state_dir / "public_state.json").read_text())


def _snapshot(page) -> dict:
    return page.evaluate("() => window.GymAnythingRTMechanics.cloudpost_circuit.snapshot()")


def _shot(page, out_dir: Path, label: str) -> None:
    page.screenshot(path=str(out_dir / f"{MECHANIC_ID}-{label}.png"))


def _button_points(page) -> dict:
    result = {}
    for name in ("left","right","up","down","level"):
        box = page.locator(f'[data-trim="{name}"]').bounding_box()
        if not box:
            raise AssertionError(f"Cloudpost trim {name} is not visible")
        result[name] = (box["x"]+box["width"]/2,box["y"]+box["height"]/2)
    return result


def _trim_once(page, points: dict, control: list[float], desired: list[float]) -> bool:
    errors = [desired[0]-control[0],desired[1]-control[1]]
    axis = max(range(2),key=lambda i:abs(errors[i])/(.12 if i==0 else .10))
    step = .12 if axis==0 else .10
    if abs(errors[axis]) <= step/2:
        return False
    direction = ("right" if errors[0]>0 else "left") if axis==0 else ("up" if errors[1]>0 else "down")
    page.mouse.click(*points[direction])
    return True


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    state = _read_public(state_dir)
    physics = state["physics"]
    simplified = state.get("control_condition",{}).get("interaction")=="simplified"
    box = page.locator(".cloudpost-canvas").bounding_box()
    if not box:
        raise AssertionError("Cloudpost canvas is not visible")
    points = _button_points(page) if simplified else {}
    photographed = set()
    for _ in range(6000):
        snapshot = _snapshot(page)
        if snapshot["challenge_id"] != state["challenge_id"]:
            raise AssertionError("Cloudpost flight failed and regenerated during a positive solve")
        if len(snapshot["collected"]) == len(state["targets"]):
            break
        if snapshot["terminal"]:
            raise AssertionError("Cloudpost flight ended before collecting every seal")
        target = next(item for item in state["targets"] if item["id"] not in snapshot["collected"])
        desired = _control_for(snapshot["plane"],target,physics)
        if simplified:
            changed = _trim_once(page,points,snapshot["control"],desired)
        else:
            x = box["x"]+(.5+.5*desired[0])*box["width"]
            y = box["y"]+(.5-.5*desired[1])*box["height"]
            page.mouse.move(max(box["x"]+.1,min(box["x"]+box["width"]-.1,x)),
                            max(box["y"]+.1,min(box["y"]+box["height"]-.1,y)))
            changed = False
        # Re-observe after every trim: clicks can straddle several live ticks.
        # Never apply the final command retroactively to all elapsed ticks.
        if not changed:
            page.wait_for_timeout(20)
        count = len(snapshot["collected"])
        if count and count not in photographed:
            photographed.add(count)
            _shot(page,out_dir,f"contact-{count}")
    else:
        raise AssertionError("Cloudpost ordinary-input controller exhausted its bounded solve")
    expect(page.locator(".cloudpost-readout")).to_have_text("PASS · WORLD-SPACE DELIVERY CONFIRMED",timeout=15000)
    _shot(page,out_dir,"pass")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    state = _read_public(state_dir)
    with page.expect_response(lambda response: response.request.method=="POST" and response.url.endswith("/result"),timeout=30000) as received:
        if state.get("control_condition",{}).get("interaction")=="simplified":
            points = _button_points(page)
            for _ in range(9):
                page.mouse.click(*points["right"])
        else:
            box = page.locator(".cloudpost-canvas").bounding_box()
            page.mouse.move(box["x"]+box["width"]-1,box["y"]+box["height"]/2)
    response = received.value.json()
    if response.get("passed") is not False:
        raise AssertionError("Cloudpost negative flight was not explicitly rejected")
    page.wait_for_function("before => window.GymAnythingRTMechanics.cloudpost_circuit.snapshot().challenge_id !== before",arg=state["challenge_id"])
    fresh = _read_public(state_dir)
    if fresh["challenge_id"] == state["challenge_id"]:
        raise AssertionError("Cloudpost rejection did not issue a fresh flight")
    _shot(page,out_dir,"failure-fresh-flight")
