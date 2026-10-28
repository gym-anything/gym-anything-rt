"""Privileged causal planning; all native solution inputs use ui.send / HTTP.

The oracle reads exact instantaneous ball and catcher state. It does not read
future wind samples, mutate the page, call task functions or send Playwright input.
Exact state access is disclosed; this is wiring and solvability evidence.
"""
from __future__ import annotations

import math
import time


def choose_control(snapshot, world, lead=.24):
    balls = [b for b in snapshot["balls"].values() if b["phase"] == "free"]
    if not balls:
        rail = list(snapshot["balls"].values())
        if not rail or "gates" not in snapshot:
            return snapshot["target"], snapshot.get("orientation", 0)
        # Anticipate the next exit using the inspected inlet and the visible
        # current vanes. There is no reason to wait for free fall before
        # beginning a long traverse of the catcher rail.
        ball = min(rail, key=lambda b:b["id"])
        column = ball["column"]
        if ball["row"] == world["rows"]-1:
            x = ball["bx"]
        else:
            for row in range(ball["row"]+1, world["rows"]):
                gate = world["gates"][world["offsets"][row]+column]
                direction = snapshot["gates"][gate["id"]]
                column += direction
            x = gate["x"] + (1 if direction else -1)*world["spacing"]/2
    else:
        ball = max(balls, key=lambda b: b["y"])
        # Recent motion supplies velocity. The visible wind instrument supplies
        # instantaneous acceleration. Future random wind is not consulted.
        horizon = min(lead, max(0, (world["rim_y"] - ball["radius"] - ball["y"]) / max(1, ball["vy"])))
        x, vx = ball["x"], ball["vx"]
        acceleration = snapshot.get("wind", 0) * ball["wind_scale"]
        for _ in range(math.ceil(horizon / .01)):
            vx += (acceleration - .12 * vx) * .01
            x += vx * .01
            lo, hi = world["wall_left"] + ball["radius"], world["wall_right"] - ball["radius"]
            if x < lo or x > hi:
                x = 2 * lo - x if x < lo else 2 * hi - x
                vx *= -.65
    orientation = snapshot.get("orientation", 0)
    width = world["pockets"]*world["pocket_width"]+(world["pockets"]-1)*world["divider_width"]
    lo, hi = world["wall_left"]+width/2, world["wall_right"]-width/2
    if world["pockets"] == 2:
        # Choose the pocket whose required catcher movement is smaller. A
        # clamped target can still catch near a wall; evaluate the actual
        # opening rather than requiring the marble to hit its exact center.
        def cost(candidate):
            offset = (-1 if ball["kind"] == candidate else 1) * (world["pocket_width"]+world["divider_width"])/2
            target = max(lo,min(hi,x-offset))
            unreachable = max(0,abs(x-(target+offset))+ball['radius']-world['pocket_width']/2)
            return unreachable*100 + abs(target-snapshot.get('x',480)) + (20 if candidate != orientation else 0)
        orientation = min((0,1),key=cost)
        offset = (-1 if ball["kind"] == orientation else 1) * (world["pocket_width"]+world["divider_width"])/2
    else:
        offset = 0
    return max(0, min(960, x-offset)), orientation


def choose_target(snapshot, world, lead=.24):
    return choose_control(snapshot, world, lead)[0]


def latch_ready(snapshot, world, margin=12):
    """Current visible geometry, with clearance for native input travel time."""
    balls = [b for b in snapshot["balls"].values() if b["phase"] == "free"
             and world["capture_top"] + b["radius"] <= b["y"]
             and b["y"] + b["radius"] + margin <= world["rim_y"]]
    if not balls:
        return False
    ball = max(balls, key=lambda b: b["y"])
    orientation = snapshot.get("orientation", 0)
    offset = 0 if world["pockets"] == 1 else (-1 if ball["kind"] == orientation else 1) * (world["pocket_width"] + world["divider_width"]) / 2
    left = snapshot["x"] + offset - world["pocket_width"] / 2
    right = left + world["pocket_width"]
    # The cabinet wall already confines the complete marble. A stationary
    # catcher held against that wall needs no extra clearance on the outside
    # edge; retain the ordinary input-travel margin on the other three edges.
    left_margin = 0 if abs(left-world["wall_left"]) < 1e-6 and snapshot.get("target",snapshot["x"]) <= snapshot["x"] else margin
    right_margin = 0 if abs(right-world["wall_right"]) < 1e-6 and snapshot.get("target",snapshot["x"]) >= snapshot["x"] else margin
    return left + ball["radius"] + left_margin <= ball["x"] <= right - ball["radius"] - right_margin


READ = """(() => {
 const m=window.flipGateCascadeV3Model,p=m.physics,r=m.canvas.getBoundingClientRect();
 const b=document.querySelector('#fcv2-start').getBoundingClientRect();
 const swap=document.querySelector('#fcv2-swap')?.getBoundingClientRect();
 return {ms:p.ms,run_start:p.run_start,x:p.x,vx:p.vx,target:p.target,balls:p.balls,gates:p.gates,orientation:p.orientation,
   wind:window.FlipGateCascadeV3Wind(p.w,p.run_start===null?0:p.ms-p.run_start),
   done:p.done,failed:p.failed,terminal:m.terminal,grade:m.grade,hold:m.hold,
   rect:{x:r.x,y:r.y,width:r.width,height:r.height},start:[b.x+b.width/2,b.y+b.height/2],swap:swap?[swap.x+swap.width/2,swap.y+swap.height/2]:null};
})()"""


def pixel(snapshot, x, y):
    r = snapshot["rect"]
    return [round(r["x"] + x * r["width"] / 960), round(r["y"] + y * r["height"] / 570)]


def inspect_inlets_http(ui, truth):
    """Use the ordinary pointer surface for the restored safe inspection.

    The oracle knows the cabinet geometry; each actual information probe is
    delivered through the same HTTP client as its subsequent steering.
    """
    state = ui.read(READ)
    actions = [{"mouse": {"move": pixel(state, gate["x"], 12)}}
               for gate in truth["world"]["gates"][:truth["world"]["top_chutes"]]]
    return ui.send(actions)


def solve_http(ui, truth, *, execution_mode="live", interval=.20, max_requests=300, inspect=True):
    world = truth["world"]
    mode = (truth.get("control_condition") or {}).get("interaction", "full")
    if inspect:
        inspect_inlets_http(ui, truth)
    state = ui.read(READ)
    response = ui.send([{"mouse": {"left_click": state["start"]}}])
    gateway_finished = bool(response.get("done"))
    held = False
    try:
        for _ in range(max_requests - 2):
            state = ui.read(READ)
            if state["failed"]:
                # A live miss can happen after the previous response while
                # waiting. Preserve its cause; lifecycle cleanup releases
                # the held button without a rejected post-episode action.
                gateway_finished = True
                raise AssertionError(f"native cascade failed: {state['failed']}")
            if state["done"] or state["terminal"]:
                gateway_finished = True
                return
            # Aim through the next declared 300 ms observation window. Live
            # requests retain the shorter continuously corrected lookahead.
            lead = .30 if execution_mode == "paused" else .24
            target, orientation = choose_control(state, world, lead=lead)
            common = [{"keyboard": {"keys": ["Space"]}}] if orientation != state['orientation'] else []
            if latch_ready(state, world):
                # A closure is irreversible. Do not swap the matching pocket
                # or add pointer travel ahead of this currently valid action.
                common = []
                actions = [{"keyboard": {"keys": ["Enter"]}}]
            elif mode == "full":
                actions = []
                if not held:
                    actions = [{"mouse": {"move": pixel(state, state["x"], 538)}},
                               {"mouse": {"buttons": {"left_down": True}}}]
                    held = True
                actions.append({"mouse": {"move": pixel(state, target, 538)}})
            else:
                actions = [{"mouse": {"left_click": pixel(state, target, 532)}}]
            response = ui.send(common+actions)
            gateway_finished = bool(response.get("done"))
            if execution_mode == "live":
                ui.wait(interval)
        raise AssertionError("declared cascade HTTP request budget exhausted")
    finally:
        if held and not gateway_finished:
            ui.send([{"mouse": {"buttons": {"left_up": True}}}])
