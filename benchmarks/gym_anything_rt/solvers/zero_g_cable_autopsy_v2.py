"""Privileged diagnostic planner; send() must be the frozen model HTTP action API.

Browser tests may supply a labelled Playwright transport to check implementation.
That transport is never action-space evidence. The planner reads cable state and
motion seeds; its results are solvability diagnostics, not screenshot-only scores.
"""
from __future__ import annotations

import copy
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders import zero_g_cable_autopsy_v2 as physics

READ = "({physics:zeroGCableV2Model.physics,tool:zeroGCableV2Model.tool,terminal:zeroGCableV2Model.terminal,outcome:zeroGCableV2Model.outcome||null,result:zeroGCableV2Model.result||null})"


def box(ui, selector):
    return ui.read(f"(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()")


def button(ui, selector):
    r = box(ui, selector)
    return {"mouse": {"left_click": [r[0] + r[2] / 2, r[1] + r[3] / 2]}}


def drag(a, b):
    return [{"mouse": {"move": a, "buttons": {"left_down": True}}},
            {"mouse": {"move": b}}, {"mouse": {"buttons": {"left_up": True}}}]


def cut_points(w, s, spec):
    p, i = physics.collar(w, s, spec)
    a, b = s["nodes"][i:i + 2]
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = max(1e-9, math.hypot(dx, dy))
    normal = [-dy / d, dx / d]
    return [[p[k] + sign * normal[k] * 15 for k in (0, 1)] for sign in (-1, 1)]


def solve_api(ui, truth):
    w = truth["world"]
    simple = truth["control_condition"]["interaction"] == "simplified"
    rect = box(ui, "#zg-canvas")

    def screen(p):
        return [rect[0] + p[0] * rect[2] / w["width"], rect[1] + p[1] * rect[3] / w["height"]]

    ui.send([button(ui, "#zg-start")])
    # This bounds oracle planning wall time, independently of the task clock.
    # The frozen paused HTTP route collects four frames per request and can
    # take seconds while advancing only 240 ms of task time. Keep the same
    # action budget and leave those transport timings in the evidence.
    deadline = time.monotonic() + 300
    for cycle in range(70):
        state = ui.read(READ)
        s = state["physics"]
        if s["failed"]:
            raise AssertionError(s["failed"])
        if s["complete"]:
            for _ in range(100):
                state = ui.read(READ)
                if state["outcome"]:
                    assert state["outcome"]["passed"], state
                    return state
                ui.wait(.03)
            raise AssertionError("No server verdict after complete dissection")
        assert time.monotonic() < deadline, "Cable controller deadline"
        actions = []
        if state["tool"] == "knife":
            actions.append(button(ui, "#zg-tool"))
        for i, g in enumerate(s["grips"]):
            # Feed forward the measured inertial-servo lag. The published image
            # trails provide motion evidence; this oracle also knows the seeds.
            target = physics.motion(w["ports"][i], s["tick"] * w["tick_ms"] + 330)
            dest = screen([w["ports"][i]["x"], target])
            if simple:
                actions.extend([button(ui, f'[data-zg-select="{i}"]'), {"mouse": {"left_click": dest}}])
            else:
                actions.extend(drag(screen([w["ports"][i]["x"], g["y"]]), dest))
        ui.send(actions)
        ui.wait(.24)
        state = ui.read(READ)
        s = state["physics"]
        predicted = copy.deepcopy(s)
        # Native drag completion lands on evolving geometry; estimate 60 ms of
        # delivery. Paused transport reports its frozen input boundary instead.
        horizon = 0 if getattr(ui, "execution", "live") == "paused" else 3
        physics.advance(w, predicted, predicted["tick"] + horizon)
        if not s["failed"] and s["energy"] <= w["cut_energy_limit"] and physics.isolated(w, s) and physics.isolated(w, predicted) and physics.stretch(w, predicted) <= w["max_stretch"]:
            remaining = [c for c in w["collars"] if c["id"] not in s["removed"]]
            # Pick a physically safe transverse slice. This is privileged
            # geometry planning only; every actual stroke uses mouse input.
            for spec in remaining:
                a, b = cut_points(w, predicted, spec)
                trial = copy.deepcopy(predicted)
                physics.cut(w, trial, a, b)
                if trial["failed"]:
                    continue
                acts = [button(ui, "#zg-tool")]
                if simple:
                    acts.extend([{"mouse": {"left_click": screen(a)}}, {"mouse": {"left_click": screen(b)}}])
                else:
                    acts.extend(drag(screen(a), screen(b)))
                ui.send(acts)
                break
    raise AssertionError("Cable oracle exhausted its declared 70 control cycles")


def diagnostic_solution(world, *, period_ms=240, stale_ms=0, parked=False):
    """Matched-seed physics experiment; no claim of native or model execution."""
    s = physics.initial_state(world)
    s["started"] = True
    history = {0: copy.deepcopy(s)}
    calls = 0
    while s["tick"] < 2000 and not s["failed"] and not s["complete"]:
        observed = history.get(max(0, s["tick"] - stale_ms // world["tick_ms"]), history[0])
        if not parked:
            for i in range(2):
                s["grips"][i]["target"] = physics.motion(world["ports"][i], observed["tick"] * world["tick_ms"] + 330)
        if physics.isolated(world, observed) and observed["energy"] <= world["cut_energy_limit"] and observed["tick"] > 40:
            for spec in world["collars"]:
                if spec["id"] in observed["removed"]:
                    continue
                a, b = cut_points(world, observed, spec)
                physics.cut(world, s, a, b)
                calls += 1
                break
        if s["failed"] or s["complete"]:
            break
        for _ in range(period_ms // world["tick_ms"]):
            physics.step(world, s)
            history[s["tick"]] = copy.deepcopy(s)
        calls += 1
    return dict(success=s["complete"] and not s["failed"], failed=s["failed"],
                tick=s["tick"], removed=s["removed"], control_cycles=calls,
                observation_staleness_ms=stale_ms, period_ms=period_ms, parked=parked)
