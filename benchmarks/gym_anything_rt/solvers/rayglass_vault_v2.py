"""Privileged planning oracle with a transport supplied by the validator.

Only literal downstream mouse dictionaries are sent. The read callback reads
current browser diagnostics, including receiver motion and servo state; this is
not a screenshot-only model policy. A headless Playwright transport establishes
event/physics wiring only. HTTP action-space parity requires the frozen direct
native gateway, and remains pending for this construction batch.
"""
from __future__ import annotations

import math
import time

MECHANIC_ID = "rayglass_vault_v2"


def box(ui, selector):
    return ui.read(f"(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; }})()")


def center(rect):
    return [rect[0]+rect[2]/2, rect[1]+rect[3]/2]


def click(point):
    return [{"mouse": {"left_click": list(point)}}]


def drag(start, end):
    return [{"mouse": {"move": list(start), "buttons": {"left_down": True}}},
            {"mouse": {"move": list(end)}}, {"mouse": {"buttons": {"left_up": True}}}]


def diagnostics(ui):
    # A read only; never calls an internal action, physics tick, clock, or draw.
    return ui.read("({state:rayglassVaultV2Model.sim.snapshot(),terminal:rayglassVaultV2Model.terminal,shots:rayglassVaultV2Model.shots,trails:rayglassVaultV2Model.sim.trails})")


def receiver_range(position, direction, bound, speed_min, speed_max, delay, *, error=0, earliest=None):
    """Visible-information reachability, including any number of reflections.

    No motion seed or future sample is consulted. Smooth drift always lies in
    the printed speed range. Reflection is a triangular, 1-Lipschitz map.
    """
    phase = position+bound if direction > 0 else 3*bound-position
    low = phase+speed_min*(delay if earliest is None else earliest)-error
    high = phase+speed_max*delay+error
    fold = lambda value: bound-abs(value % (4*bound)-2*bound)
    samples = [fold(low),fold(high)]
    for k in range(math.ceil(low/(2*bound)),math.floor(high/(2*bound))+1):
        samples.append(fold(k*2*bound))
    return min(samples),max(samples)


def solve(ui, state, *, interval=.20, observation_delay=0, max_calls=100, max_seconds=85, on_observation=None):
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.rayglass_vault_v2 import trim_point
    mode = (state.get("control_condition") or {}).get("interaction", "full")
    cabinet_rect, optics_rect = box(ui, "#rgv-cabinet"), box(ui, "#rgv-optics")
    def screen(rect, point, width, height):
        return [rect[0]+point[0]*rect[2]/width,rect[1]+point[1]*rect[3]/height]
    def cabinet(point): return screen(cabinet_rect,point,340,430)
    def optics(point): return screen(optics_rect,point,680,490)
    sends = 0
    def send(actions):
        nonlocal sends
        if sends >= max_calls:
            raise AssertionError("oracle action-call budget exhausted")
        ui.send(actions); sends += 1
    for i, channel in enumerate(state["channels"]):
        # Reciprocity is a valid source-derived shortcut for preparing a
        # route. It deliberately does not solve continuous receiver tracking.
        output = channel["exit_port"]
        p = state["cabinet"]["ports"][output]
        send(click(cabinet([p["x"],p["y"]])))
        response = diagnostics(ui)["shots"][str(output)]
        assert type(response) is int, "requested output must have a transmissive mate"
        socket = state["cabinet"]["sockets"][i]
        port = state["cabinet"]["ports"][response]
        a,b = cabinet([socket["x"],socket["y"]]),cabinet([port["x"],port["y"]])
        if mode == "full": send(drag(a,b))
        else: send(click(a)+click(b))
    distance = state["optics"]["receiver_x"]-state["optics"]["mirror_x"]
    def controls(current, positions):
        actions = []
        for i,y in enumerate(positions):
            angle = math.degrees(math.atan(y/distance))/2
            target = trim_point(state,i,angle)
            if mode == "full":
                start = trim_point(state,i,current["targets"][i])
                actions.extend(drag(optics(start),optics(target)))
            else: actions.extend(click(optics(target)))
        return actions
    initial = diagnostics(ui)["state"]
    send(controls(initial,initial["positions"]))
    ui.wait(.4)
    send(click(center(box(ui,"#rgv-start"))))
    deadline = time.monotonic()+max_seconds
    observations = 0
    while time.monotonic() < deadline:
        reading = diagnostics(ui); current = reading["state"]
        if current["failed"]:
            raise AssertionError(current["failed"])
        if current["complete"]:
            return dict(calls=sends,observations=observations,active_seconds=current["active_tick"]*.01,
                        completed=True,privileged_planning=True,action_transport=getattr(ui,"transport_name","unspecified"))
        if reading["terminal"]:
            raise AssertionError("terminal outcome before complete charge")
        if current["ready"]:
            key=state["cabinet"]["seal_key"]
            pickup=cabinet([key["x"],key["y"]])
            if mode == "full":
                send([{"mouse":{"move":pickup,"buttons":{"left_down":True}}}])
            else:
                send(click(pickup))
            armed=diagnostics(ui)["state"]
            p,o=state["parameters"],state["optics"]
            low,high=receiver_range(armed["positions"][0],armed["directions"][0],o["rail_half_span"],p["speed_min"],p["speed_max"],.15,earliest=0,error=.1)
            destination=optics([o["receiver_x"],o["row_centers"][0]+(low+high)/2])
            if mode == "full":
                send([{"mouse":{"move":destination}},{"mouse":{"buttons":{"left_up":True}}}])
            else:
                send(click(destination))
            continue
        observations += 1
        if on_observation: on_observation(reading)
        # Recent trail estimates motion. The present bumper direction is
        # disclosed as privileged state; no future seed samples are read.
        forecast=[]
        for i,y in enumerate(current["positions"]):
            trail = reading["trails"][i]
            age=min(8,len(trail)-1)
            measured=abs((trail[-1]-trail[-1-age])/(age*.01)) if age else state["parameters"]["speed_min"]
            velocity=current["directions"][i]*measured
            future=y+velocity*(.20+interval/2+observation_delay)
            bound=state["optics"]["rail_half_span"]
            while future > bound or future < -bound:
                future=2*bound-future if future > bound else -2*bound-future
            forecast.append(future)
        if observation_delay: ui.wait(observation_delay)
        send(controls(current,forecast))
        ui.wait(interval)
    raise AssertionError("oracle wall-time budget exhausted")


def solve_browser(page, public_state, **kwargs):
    """Convenience for explicit headless implementation checks only."""
    from tests.test_nonrealtime_four_v2 import BrowserUI
    ui = BrowserUI(page)
    ui.transport_name = "headless Playwright; NOT native HTTP parity"
    return solve(ui,public_state,**kwargs)
