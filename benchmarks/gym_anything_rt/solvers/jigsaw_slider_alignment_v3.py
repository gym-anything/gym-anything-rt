"""Privileged trajectory planning with separate HTTP and Playwright adapters.

Drive directions may instead be supplied from visible calibration feedback;
that path works with the private polarity fields removed. Neither adapter's
implementation alone establishes native action-API parity or human difficulty.
"""
from __future__ import annotations

import math

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.jigsaw_slider_alignment_v3 import clamp, target


def commands(truth, sim, lead_ms=120, *, drive_directions=None):
    p=truth["parameters"]
    directions=([piece["drive_x"] for piece in truth["pieces"]]
                if drive_directions is None else list(drive_directions))
    if len(directions)!=len(truth["pieces"]) or any(type(d) is not int or d not in (-1,1) for d in directions):
        raise ValueError("one direct or reversed drive direction is required per fragment")
    out=[]
    for i,piece in enumerate(truth["pieces"]):
        q=target(piece,sim["tick"]*10+lead_ms)
        before=target(piece,max(0,sim["tick"]*10+lead_ms-10))
        after=target(piece,sim["tick"]*10+lead_ms+10)
        c={}
        for axis,vel in (("x","vx"),("y","vy")):
            acc=(after[vel]-before[vel])/.02
            spring=sum((target(truth["pieces"][j],sim["tick"]*10+lead_ms)[axis]-q[axis])*p["spring"]
                       for j in (i-1,i+1) if 0 <= j < len(truth["pieces"]))
            c[axis]=clamp(q[axis]+(p["damping"]*q[vel]+acc-spring)/p["stiffness"],-120 if axis=="x" else -145,120 if axis=="x" else 150)
        acc=(after["omega"]-before["omega"])/.02
        c["angle"]=clamp(q["angle"]+(truth["angular_damping"]*q["omega"]+acc)/truth["angular_stiffness"],-90,90)
        # Commands are pointer destinations. Invert the learned transmission;
        # the unchanged plant still receives the same physical setpoint.
        c["x"] *= directions[i]
        out.append(c)
    return out


READ="""(()=>{const m=jigsawSliderAlignmentV3Model,r=m.canvas.getBoundingClientRect();
 const rect=s=>{const q=document.querySelector(s).getBoundingClientRect();return [q.x+q.width/2,q.y+q.height/2];};
 return {sim:m.sim,grade:m.grade||null,rect:[r.x,r.y,r.width,r.height],
 start:rect('[data-control="start"]'),clamp:rect('[data-control="clamp"]'),clock:GymAnythingRTTime.status()};})()"""


def solve(ui, truth):
    state=ui.read(READ)
    ui.send([{"mouse":{"left_click":state["start"]}}])
    for _ in range(90):
        state=ui.read(READ)
        sim=state["sim"]
        if sim["phase"]=="passed":
            return
        if sim["phase"]=="failed":
            raise AssertionError(sim)
        x,y,w,h=state["rect"]
        point=lambda a,b:[round(x+a*w/1080),round(y+b*h/540)]
        paused=state["clock"].get("mode")=="paused"
        controls=commands(truth,sim,150 if paused else 90)
        actions=[]
        full=truth["control_condition"]["interaction"]=="full"
        for i,c in enumerate(controls):
            cx=(i+.5)*1080/len(controls)
            b=sim["bodies"][i]
            dest=point(cx+c["x"],220+c["y"])
            if full:
                actions.extend([{"mouse":{"move":point(cx+b["x"],220+b["y"]),"buttons":{"left_down":True}}},
                                {"mouse":{"move":dest}}, {"mouse":{"buttons":{"left_up":True}}}])
            else: actions.append({"mouse":{"left_click":dest}})
            if truth["parameters"]["rotation_amplitude"]:
                dest=point(cx+38*math.sin(math.radians(c["angle"])),466-38*math.cos(math.radians(c["angle"])))
                if full:
                    actions.extend([{"mouse":{"move":point(cx,428),"buttons":{"left_down":True}}},
                                    {"mouse":{"move":dest}}, {"mouse":{"buttons":{"left_up":True}}}])
                else: actions.append({"mouse":{"left_click":dest}})
        if sim["phase"]=="running" and sim["tick"]>=180:
            from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.jigsaw_slider_alignment_v3 import errors,registered
            margin=all(e['position']<truth['parameters']['position_tolerance']*.6 and
                       e['angle']<truth['parameters']['angle_tolerance']*.6 for e in errors(truth,sim))
            if registered(truth,sim) and margin:
                # Correct and clamp in one request. A separate paused observation
                # would create an unnecessary 600ms gap between corrections.
                actions.append({"mouse":{"left_click":state["clamp"]}})
        ui.send(actions)
        if not paused:ui.wait(.11)
    raise AssertionError("moving registration controller exhausted the declared HTTP step budget")


def solve_browser(page, truth, *, drive_directions=None):
    """Isolated Playwright motor proof with privileged planning, not native API evidence.

    The caller owns a fresh headless context and can first inspect/probe using
    visible input. This controller also accepts an already-running calibration.
    Pass screenshot-learned drive_directions to avoid private polarity access;
    target trajectories and current plant observations remain privileged.
    It never writes browser state or changes the runtime clock contract.
    """
    import time
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.jigsaw_slider_alignment_v3 import registered, errors

    if page.evaluate('jigsawSliderAlignmentV3Model.sim.phase') == 'ready':
        page.locator('[data-control="start"]').click()
    for _ in range(450):
        sim=page.evaluate('jigsawSliderAlignmentV3Model.sim')
        if sim['phase']=='passed':
            page.wait_for_function('jigsawSliderAlignmentV3Model.grade !== undefined',timeout=10000)
            assert page.evaluate('jigsawSliderAlignmentV3Model.grade.passed')
            return page.evaluate('jigsawSliderAlignmentV3Model.payload')
        if sim['phase']=='failed':
            raise AssertionError(sim)
        paused=page.evaluate('GymAnythingRTTime.status().mode')=='paused'
        box=page.locator('canvas').bounding_box()
        def point(a,b):
            return box['x']+a*box['width']/1080,box['y']+b*box['height']/540
        full=truth['control_condition']['interaction']=='full'
        for i in range(len(sim['bodies'])):
            # Playwright pointer delivery spans several animation frames. Read
            # the current plant for each lane rather than holding an entire
            # multi-lane batch to the first lane's observation time.
            observed=sim if paused else page.evaluate('jigsawSliderAlignmentV3Model.sim')
            c=commands(truth,observed,100 if paused else (140 if full else 90),
                       drive_directions=drive_directions)[i]
            center=(i+.5)*1080/len(sim['bodies'])
            destination=point(center+c['x'],220+c['y'])
            if full:
                body=page.evaluate('i=>jigsawSliderAlignmentV3Model.sim.bodies[i]',i)
                page.mouse.move(*point(center+body['x'],220+body['y']))
                page.mouse.down();page.mouse.move(*destination);page.mouse.up()
            else:
                page.mouse.click(*destination)
            if truth['parameters']['rotation_amplitude']:
                angle=math.radians(c['angle'])
                destination=point(center+38*math.sin(angle),466-38*math.cos(angle))
                if full:
                    page.mouse.move(*point(center,428));page.mouse.down()
                    page.mouse.move(*destination);page.mouse.up()
                else:
                    page.mouse.click(*destination)
        sim=page.evaluate('jigsawSliderAlignmentV3Model.sim')
        if sim['phase']=='running' and sim['tick']>=200:
            margin=all(e['position']<truth['parameters']['position_tolerance']*.6 and
                       e['angle']<truth['parameters']['angle_tolerance']*.6 for e in errors(truth,sim))
            if registered(truth,sim) and margin:
                page.locator('[data-control="clamp"]').click()
        if paused:
            page.evaluate('GymAnythingRTTime.runFor(200)')
            deadline=time.monotonic()+10
            while page.evaluate('GymAnythingRTTime.status().phase')!='completed':
                assert time.monotonic()<deadline
                time.sleep(.01)
        else:
            page.wait_for_timeout(10 if full else 60)
    raise AssertionError('Playwright controller exhausted its diagnostic budget')
