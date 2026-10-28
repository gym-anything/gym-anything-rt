"""Privileged read-only oracle planning; all actual inputs use the caller's HTTP UI.

No page mutation, event dispatch, DOM focus or navigation is performed. The local
browser check supplies an explicitly separate Playwright implementation-check UI.
"""
from __future__ import annotations
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.wonky_text_hostile_rendering_v2 import target

READ = """(() => {
 const m=window.wonkyTextHostileRenderingV2Model;
 return {t:m.t_ms,started:m.started,ended:m.ended,failed:m.failed,submitted:m.submitted,
 positions:m.positions,goals:m.goals,spoil_ms:m.spoil_ms,clean_ms:m.clean_ms,
 pads:[...document.querySelectorAll('[data-pad]')].map(n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height];}),
 start:(()=>{const r=document.querySelector('.wth-start').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()};
})()"""


def commands(truth, snapshot, horizon_ms=0):
    actions = []
    press = truth["press"]
    mode = truth["control_condition"]["interaction"]
    for i, plate in enumerate(press["plates"]):
        t = snapshot["t"] + horizon_ms
        goal = target(press, plate, t)
        rect = snapshot["pads"][i]
        def screen(p):
            return [round(rect[0] + p[0] * rect[2] / 300), round(rect[1] + p[1] * rect[3] / 200)]
        if mode == "full":
            actions.extend([
                {"mouse": {"move": screen(snapshot["positions"][i]), "buttons": {"left_down": True}}},
                {"mouse": {"move": screen(goal)}},
                {"mouse": {"buttons": {"left_up": True}}},
            ])
        else:
            actions.append({"mouse": {"left_click": screen(goal)}})
    return actions


def solve(ui, truth, *, interval_s=0.32, observation_delay_s=0.0, policy="feedback"):
    """100-request task budget; UI must count captures and record acknowledgements.

    Target nodes are privileged. Feedback evaluates a short lead position;
    the ordinary UI exposes a 600 ms path preview. Other policies intentionally
    suppress later feedback, or hold observations stale, for matched diagnostics.
    """
    snap = ui.read(READ)
    ui.send(commands(truth, snap))
    ui.send([{"mouse": {"left_click": snap["start"]}}])
    wall_end = time.monotonic() + 90
    reference = truth
    if policy == "fixed":
        from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.wonky_text_hostile_rendering_v2 import generate
        _, reference = generate({"id":truth["task_id"],"_control_condition":truth["control_condition"]}, "fixed-reference")
    calls = 2
    while time.monotonic() < wall_end:
        ui.wait(interval_s)
        snap = ui.read(READ)
        if snap["ended"]:
            return dict(failed=snap["failed"], spoil_ms=snap["spoil_ms"], calls=calls)
        if policy == "parked":
            continue
        if observation_delay_s:
            ui.wait(observation_delay_s)
        ui.send(commands(reference, snap, truth["press"]["servo_ms"] + 160))
        calls += 1
        if calls >= 98:
            raise AssertionError("oracle exhausted its declared 100-request budget")
    raise AssertionError("letterpress oracle exceeded its finite wall deadline")
