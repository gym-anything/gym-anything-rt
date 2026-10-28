"""Privileged read-only planning with ordinary mouse inputs via a supplied UI.

Playwright validation uses its own isolated transport. It is implementation
evidence, not screenshot-only solving or native action-API parity.
"""
from __future__ import annotations

import time
import copy
import re


def drive(world, positions, velocities, winds):
    """Causal feedback; uses current pressure, never reads future noise values."""
    s = world["stage"]
    scales = [s["w"], s["h"], s["h"], s["w"] * (1 - world["target"][0])]
    result = []
    for i in range(world["parameters"]["seam_count"]):
        error = (positions[i] - world["target"][i]) * scales[i]
        speed = velocities[i] * scales[i]
        wanted = -2.5 * error - .4 * speed
        trim = (wanted - world["parameters"]["wind_speed"] * winds[i]) / world["motor_speed"]
        result.append(max(-1., min(1., trim)) * world["linkages"][i]["sign"])
    return result


READ = r'''(() => {
  const m = reflowVitrineV3Model, w = m.state.world;
  const noise = (seed,index) => {
    let x=(seed^Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;
    x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    const z=((x^(x>>>16))>>>0)/4294967295*2-1;
    return (z<0?-1:1)*(.28+.72*Math.abs(z));
  };
  const pressure=w.gust_seeds.map(seed=>{
    const u=m.ms/w.parameters.gust_span_ms,n=Math.floor(u),f=u-n;
    return noise(seed,n)+(noise(seed,n+1)-noise(seed,n))*f*f*(3-2*f);
  });
  const rect = selector => {const r=document.querySelector(selector).getBoundingClientRect();return [r.x,r.y,r.width,r.height];};
  const canvas=rect('#rv2-canvas'),s=w.stage,a=s.x+s.w*m.p[0];
  const points=[[a,s.y+18],[s.x+s.w-20,s.y+s.h*m.p[1]],
    [s.x+18,s.y+s.h*m.p[2]],[a+s.w*(1-m.p[0])*m.p[3],s.y+18]];
  return {p:m.p,v:m.v,trim:m.trim,ms:m.ms,pressure,terminal:m.outcome,
    result:m.result,started:m.started,blur_ms:m.blurMs,
    badges:points.slice(0,w.parameters.seam_count).map(p=>[canvas[0]+p[0]/800*canvas[2],canvas[1]+p[1]/376*canvas[3]]),
    rails:w.linkages.map((_,i)=>{const b=document.querySelector(`[data-rv2-rail="${i}"]`).getBoundingClientRect();return [b.x,b.y,b.width,b.height];}),
    start:rect('#rv2-start')};
})()'''


READ_RAIL_LABELS = r'''(() => [...document.querySelectorAll('.rv2-control')].map(control => {
  const rail=control.querySelector('.rv2-rail'),r=rail.getBoundingClientRect();
  const thumb=control.querySelector('.rv2-thumb').getBoundingClientRect();
  const needle=new DOMMatrixReadOnly(getComputedStyle(control.querySelector('.rv2-wind i')).transform);
  const labels=control.querySelectorAll('.rv2-labels span');
  return {heading:control.querySelector('.rv2-control-head b').innerText,
    left:labels[0].innerText,right:labels[1].innerText,rect:[r.x,r.y,r.width,r.height],
    trim:2*((thumb.x+thumb.width/2-r.x)/r.width)-1,
    pressure:Math.atan2(needle.b,needle.a)/(65*Math.PI/180)};
}))()'''


READ_CONTROL_STATE = r'''(() => {
  const m=reflowVitrineV3Model,r=document.querySelector('#rv2-start').getBoundingClientRect();
  return {p:m.p,v:m.v,ms:m.ms,terminal:m.outcome,result:m.result,started:m.started,
    blur_ms:m.blurMs,start:[r.x,r.y,r.width,r.height]};
})()'''


def revealed_linkages(ui, count):
    """Read only the rail names and arrows that inspection made visible.

    The physics oracle may know geometry, velocity and current pressure. Its
    choice of rail and lever direction must still use the information revealed
    by the V3 interface, rather than canonical DOM seam IDs or private wiring.
    """
    rows = ui.read(READ_RAIL_LABELS)
    assert len(rows) == count
    links = [None] * count
    for row in rows:
        match = re.fullmatch(r"RAIL (\d+) · ([A-D]) / .+", row["heading"])
        assert match, "Inspect the seam badges before planning with their rail linkages."
        number, letter = int(match[1]), match[2]
        i = "ABCD".index(letter)
        assert 0 <= i < count and links[i] is None
        left, right = row["left"].removeprefix("← "), row["right"].removesuffix(" →")
        negative, positive = ("LEFT", "RIGHT") if i in (0, 3) else ("UP", "DOWN")
        assert {left, right} == {negative, positive}
        links[i] = dict(rail=number, sign=1 if right == positive else -1)
    assert sorted(link["rail"] for link in links) == list(range(1, count+1))
    return links


def observed_control_state(ui, links):
    """Locate numbered rails from their visible headings, with no seam IDs."""
    state = ui.read(READ_CONTROL_STATE)
    visible = ui.read(READ_RAIL_LABELS)
    by_number = {int(row["heading"].split(" · ", 1)[0].removeprefix("RAIL ")): row for row in visible}
    for key,field in (("rails","rect"),("trim","trim"),("pressure","pressure")):
        state[key] = [by_number[link["rail"]][field] for link in links]
    return state


def inspected_world(ui, truth, *, inspect=True):
    count = truth["world"]["parameters"]["seam_count"]
    if inspect:
        inspect_frames(ui, truth)
    links = revealed_linkages(ui, count)
    world = copy.deepcopy(truth["world"])
    world["linkages"] = links
    return world


def inspect_frames(ui, truth):
    """Select actual seam badges. Learned facts remain visible for the run."""
    for i in range(truth["world"]["parameters"]["seam_count"]):
        ui.send([{"mouse": {"left_click": ui.read(READ)["badges"][i]}}])


def solve(ui, truth, *, cadence_s=.24, max_seconds=60, inspect=True):
    world = inspected_world(ui, truth, inspect=inspect)
    simple = (truth.get("control_condition") or {}).get("interaction", "full") == "simplified"
    before = observed_control_state(ui, world["linkages"])
    b = before["start"]
    if not before["started"]:
        ui.send([{"mouse": {"left_click": [b[0] + b[2] / 2, b[1] + b[3] / 2]}}])
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        state = observed_control_state(ui, world["linkages"])
        if state["terminal"]:
            assert state["terminal"] == "pass", state
            for _ in range(50):
                if ui.read(READ_CONTROL_STATE)["result"]:
                    assert ui.read(READ_CONTROL_STATE)["result"]["passed"]
                    return
                ui.wait(.1)
            raise AssertionError("terminal inspection was not independently graded")
        assert state["started"], "start click did not reach task"
        commands = drive(world, state["p"], state["v"], state["pressure"])
        actions = []
        for i, command in enumerate(commands):
            x, y, width, height = state["rails"][i]
            target = [x + width * (command + 1) / 2, y + height / 2]
            if simple:
                actions.append({"mouse": {"left_click": target}})
            else:
                origin = [x + width * (state["trim"][i] + 1) / 2, y + height / 2]
                actions.extend([{"mouse": {"move": origin, "buttons": {"left_down": True}}},
                                {"mouse": {"move": target}}, {"mouse": {"buttons": {"left_up": True}}}])
        ui.send(actions)
        ui.wait(cadence_s)
    raise AssertionError("kinetic layout oracle exceeded declared wall deadline")


SOLVERS = {"reflow_vitrine_v3": solve}
