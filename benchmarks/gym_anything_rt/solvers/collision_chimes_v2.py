"""Privileged solvability planner; the caller supplies the downstream HTTP API.

Reads browser state and seeded motion to plan. It does not establish a
screenshot-only policy or a model score. Every actual input is a literal
mouse action supported by the frozen model gateway. Never mutate game state.
"""
from __future__ import annotations

import time

from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.collision_chimes_v2 import pulse_position

MECHANIC_ID = "collision_chimes_v2"
SNAPSHOT = "({time:collisionChimesV2Model.time,phase:collisionChimesV2Model.phase,pickups:collisionChimesV2Model.pickups,targets:collisionChimesV2Model.targets,caught:collisionChimesV2Model.caught,terminal:collisionChimesV2Model.terminal,reason:collisionChimesV2Model.reason,clock:GymAnythingRTTime.status()})"


def box(ui, selector):
    return ui.read(f"(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; }})()")


def click(point):
    return {"mouse": {"left_click": list(point)}}


def rail_point(rect, side, u, size=9):
    along = u / size * 360
    x, y = ((270 + along, 30) if side == "top" else (270 + along, 522) if side == "bottom"
            else (204, 96 + along) if side == "left" else (696, 96 + along))
    return [rect[0] + x * rect[2] / 950, rect[1] + y * rect[3] / 552]


def solve(ui, state, *, max_calls=360, max_seconds=110, observation_delay=0):
    mode = (state.get("control_condition") or {}).get("interaction", "full")
    world = state["world"]
    rect = box(ui, "#cc2-canvas")
    start = box(ui, "#cc2-start")
    strikes = {side: box(ui, "#cc2-strike-" + side) for side in ("top", "right", "bottom", "left")}
    calls = 0

    def send(actions):
        nonlocal calls
        if calls >= max_calls:
            raise AssertionError("declared oracle HTTP budget exhausted")
        ui.send(actions)
        calls += 1

    send([click([start[0]+start[2]/2, start[1]+start[3]/2])])
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        snap = ui.read(SNAPSHOT)
        if snap["terminal"]:
            if snap["phase"] not in ("complete", "passed"):
                raise AssertionError("native chime solution failed: " + str(snap))
            return dict(completed=True, active_ms=snap["time"], calls=calls,
                        planning="privileged current-state and seeded pulse forecast; no DOM mutation",
                        action_transport=getattr(ui, "transport_name", "unspecified"))
        if observation_delay:
            ui.wait(observation_delay)
        actions = []
        t = snap["time"]
        for side in ("top", "right", "bottom", "left"):
            # Use only pulses already visibly flying. Hidden future pulses
            # are not scheduled. The numerical forecast is privileged.
            active = [n for n in world["notes"] if n["side"] == side and
                      n["born_ms"] <= t < n["deadline_ms"] and n["id"] not in snap["caught"]]
            if not active:
                continue
            impact = min(n["deadline_ms"] for n in active)
            group = [n for n in active if n["deadline_ms"] == impact]
            half = world["parameters"]["pickup_width"] / 2
            # Strike the current physical contact, not a fixed endpoint. A
            # short prediction compensates read-to-input time in native live
            # validation; paused native input sees the exact frozen frame.
            delivery = t + (0 if getattr(ui, "execution", "live") == "paused" else 20)
            travel = world["parameters"]["pickup_speed"] * (delivery - t) / 1000
            gap = snap["targets"][side] - snap["pickups"][side]
            receiver = snap["pickups"][side] + max(-travel, min(travel, gap))
            contact = [pulse_position(world, n, delivery) for n in group]
            depth = (impact - delivery) / world["parameters"]["flight_ms"] * 66
            if 0 < impact - delivery and depth <= world["parameters"]["pickup_depth_px"] and all(abs(receiver-x) <= half-.04 for x in contact):
                strike = strikes[side]
                actions.append(click([strike[0] + strike[2]/2, strike[1] + strike[3]/2]))
                continue
            horizon = 400 if getattr(ui, "execution", "live") == "paused" else 300
            coordinates = [pulse_position(world, n, min(impact-1, t + horizon)) for n in group]
            # A single resonator can cover simultaneous pulses. Aim at the
            # shared capture interval, rather than choosing one pulse's centre.
            target = (min(coordinates) + max(coordinates)) / 2
            target = max(half, min(world["grid_size"] - half, target))
            if abs(target - snap["targets"][side]) < .06:
                continue
            end = rail_point(rect, side, target)
            if mode == "full":
                begin = rail_point(rect, side, snap["pickups"][side])
                actions.append({"mouse": {"left_click_drag": [begin, end]}})
            else:
                actions.append(click(end))
        send(actions)
        if getattr(ui, "execution", "live") == "live":
            ui.wait(.24)
    raise AssertionError("declared oracle wall-time budget exhausted")
