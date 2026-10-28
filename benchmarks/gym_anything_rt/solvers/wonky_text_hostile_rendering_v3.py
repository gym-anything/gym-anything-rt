"""Privileged read-only oracle planning; all actual inputs use the caller's HTTP UI.

No page mutation, event dispatch, DOM focus or navigation is performed. The local
browser check supplies an explicitly separate Playwright implementation-check UI.
"""
from __future__ import annotations
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.wonky_text_hostile_rendering_v3 import target

READ = """(() => {
 const m=window.wonkyTextHostileRenderingV3Model;
 return {t:m.t_ms,started:m.started,ended:m.ended,failed:m.failed,submitted:m.submitted,
 positions:m.positions,goals:m.goals,spoil_ms:m.spoil_ms,clean_ms:m.clean_ms,
 pads:[...document.querySelectorAll('[data-pad]')].map(n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height];}),
 sleeves:[...document.querySelectorAll('[data-sleeve]')].map(n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height];}),
 start:(()=>{const r=document.querySelector('.wth-start').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()};
})()"""


def inspection_commands(snapshot):
    """Sweep visible sleeves without using concealed stamp positions or marks."""
    return [{"mouse": {"move": [round(x + u * width / 300), round(y + height / 2)]}}
            for x, y, width, height in snapshot["sleeves"] for u in range(50, 251, 20)]


def commands(truth, snapshot, horizon_ms=0, guide_marks=None):
    actions = []
    press = truth["press"]
    mode = truth["control_condition"]["interaction"]
    for i, plate in enumerate(press["plates"]):
        t = snapshot["t"] + horizon_ms
        goal = target(press, plate, t)
        if guide_marks is not None and guide_marks[i] != plate["register_mark"]:
            goal = [300-goal[0], 200-goal[1]]
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


def solve(ui, truth, *, interval_s=0.32, observation_delay_s=0.0, policy="feedback", guide_marks=None):
    """100-request task budget; UI must count captures and record acknowledgements.

    Target nodes are privileged. guide_marks may supply stamps learned from
    visible inspection; choosing the other mark follows the reflected guide.
    Feedback evaluates a short lead position;
    the ordinary UI exposes a 600 ms path preview. Other policies intentionally
    suppress later feedback, or hold observations stale, for matched diagnostics.
    """
    snap = ui.read(READ)
    ui.send(inspection_commands(snap))
    ui.send(commands(truth, snap, guide_marks=guide_marks))
    ui.send([{"mouse": {"left_click": snap["start"]}}])
    wall_end = time.monotonic() + 90
    reference = truth
    if policy == "fixed":
        from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.wonky_text_hostile_rendering_v3 import generate
        _, reference = generate({"id":truth["task_id"],"_control_condition":truth["control_condition"]}, "fixed-reference")
    calls = 3
    while time.monotonic() < wall_end:
        ui.wait(interval_s)
        snap = ui.read(READ)
        if snap["ended"]:
            return dict(failed=snap["failed"], spoil_ms=snap["spoil_ms"], calls=calls)
        if policy == "parked":
            continue
        if observation_delay_s:
            ui.wait(observation_delay_s)
        ui.send(commands(reference, snap, truth["press"]["servo_ms"] + 160, guide_marks=guide_marks))
        calls += 1
        if calls >= 98:
            raise AssertionError("oracle exhausted its declared 100-request budget")
    raise AssertionError("letterpress oracle exceeded its finite wall deadline")
