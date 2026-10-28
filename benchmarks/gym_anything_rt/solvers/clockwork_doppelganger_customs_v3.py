"""Causal privileged oracle planning with literal mouse actions.

`ui.send` must be the frozen downstream HTTP transport for native validation.
Headless Playwright adapters only check event wiring and must be identified as
such. No solver reads can constitute a screenshot-only model evaluation.
"""
from __future__ import annotations

import time
import copy
import random

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.clockwork_doppelganger_customs_v3 import (
    motor, path_y, clamp, passport_position, normalize_path, Relay)

MECHANIC_ID = "clockwork_doppelganger_customs_v3"


def reconstruct_from_window(geometry, own_events, frames):
    """Reconstruct an alive relay from own inputs and the visible drive register.

    `geometry` contains the fixed rules and geometry, never motor tapes. Each
    chronological frame contains only the rendered relay `ms` and all current
    `drives` origin/end pairs. The window is bounded to 240 ms. Prior successful
    contacts follow from the visible alive condition; custody and seal masks
    therefore follow the fixed cam schedule. Actuators are replayed from one's
    own target gestures, with no old motor or hidden snapshot read.

    Unknown future endpoints remain None until independently sampled. This is
    a planning/diagnostic helper, not a game control or a native action route.
    """
    if "motors" in geometry:
        raise ValueError("geometry must not contain private motor tapes")
    if not frames or frames[-1]["ms"]-frames[0]["ms"] > 240:
        raise ValueError("a chronological window of at most 240 ms is required")
    times = [f["ms"] for f in frames]
    if times != sorted(times):
        raise ValueError("nonchronological visible frames")
    world = copy.deepcopy(geometry)
    s = world["spec"]
    clocks = [f.get("clock_ms",f["ms"]) for f in frames]
    if clocks != sorted(clocks) or clocks[-1]-clocks[0]>240:
        raise ValueError("a chronological clock window of at most 240 ms is required")
    if any(not ms<=clock<ms+s["tick_ms"] for ms,clock in zip(times,clocks)):
        raise ValueError("rendered clock and physical tick disagree")
    count = 2*s["workers"]+1
    length = s["end_ms"]//s["motor_span_ms"]+4
    world["motors"] = [[None]*length for _ in range(count)]
    for frame in frames:
        if len(frame["drives"]) != count:
            raise ValueError("every current contact drive must be visible")
        k = min(frame["ms"]//s["motor_span_ms"], length-2)
        for index, pair in enumerate(frame["drives"]):
            if len(pair) != 2:
                raise ValueError("visible origin and endpoint required")
            for offset, value in enumerate(pair):
                if not isinstance(value, int) or not 230-s["amplitude"] <= value <= 230+s["amplitude"]:
                    raise ValueError("invalid visible drive pin")
                old = world["motors"][index][k+offset]
                if old is not None and old != value:
                    raise ValueError("inconsistent visible motor segment")
                world["motors"][index][k+offset] = value

    recording, path, sim, deployed_at, hold = None, None, None, None, None
    collected = [False]*s["parcel_count"]

    def actuators_until(end):
        # This recurrence uses only deterministic actuator rules and own input.
        # Geometric contacts are reconstructed separately under the alive
        # condition, so obsolete unseen motor values cannot enter the replay.
        while sim.ms+s["tick_ms"] <= end:
            sim.ms += s["tick_ms"]
            dt = s["tick_ms"]/1000
            for i in range(s["workers"]):
                a = clamp(s["kp"]*(sim.targets[i]-sim.y[i])-s["kd"]*sim.v[i],
                          -s["acceleration"], s["acceleration"])
                sim.v[i] = clamp(sim.v[i]+a*dt, -s["speed"], s["speed"])
                sim.y[i] = clamp(sim.y[i]+sim.v[i]*dt, s["min_y"], s["max_y"])
                if sim.y[i] in (s["min_y"], s["max_y"]):
                    sim.v[i] = 0.0

    for event in own_events:
        kind = event["type"]
        if sim is not None:
            relative = event["t_ms"]-deployed_at
            if relative > clocks[-1]:
                raise ValueError("own inputs occur after the current image")
            actuators_until(relative)
        if kind == "record_start":
            recording = [event["point"]]
        elif kind in ("record_move", "record_end"):
            recording.append(event["point"])
            if kind == "record_end":
                try:
                    path = normalize_path(recording, world)
                except ValueError:
                    pass
                recording = None
        elif kind == "deploy":
            if path is None or sim is not None:
                raise ValueError("one valid deployment required")
            sim, deployed_at = Relay(world, path), event["t_ms"]
        elif kind in ("lever_move", "lever_target"):
            sim.targets[event["worker"]] = clamp(event["point"][1], s["min_y"], s["max_y"])
        elif kind == "lever_start":
            hold = event["worker"]
        elif kind == "lever_end":
            hold = None
        elif kind == "collect":
            arrivals = [(t, p) for t, i, p, action, _ in sim.contacts
                        if i == s["workers"]-1 and action == "pass"
                        and t <= event["t_ms"]-deployed_at and not collected[p]]
            if len(arrivals) != 1:
                raise ValueError("own successful pickup history is inconsistent")
            collected[arrivals[0][1]] = True

    if sim is None:
        raise ValueError("active relay required")
    actuators_until(times[-1])
    for t, i, parcel, kind, _ in sim.contacts:
        if t > sim.ms:
            break
        sim.contact_index += 1
        if kind == "catch":
            sim.custody[parcel] = -(i+1)
        elif kind == "seal":
            sim.seals[parcel] |= 1 << i
        else:
            sim.custody[parcel] = i+1
            if i == s["workers"]-1:
                sim.delivery_times[parcel] = t
                sim.delivered += 1
    sim.collected = collected
    outgoing = [p for p, t in enumerate(sim.delivery_times) if t is not None and not collected[p]]
    if len(outgoing) > 1:
        raise ValueError("alive output counter cannot contain two passports")
    sim.outgoing = outgoing[0] if outgoing else None
    return sim, dict(hold=hold, deployed_at=deployed_at, clock_ms=clocks[-1],
                     within_tick_ms=clocks[-1]-times[-1],
                     information="own inputs + current/recent visible drive register; no old or future tape")


def sample_conditional_future(sim, draw_seed):
    """Sample only unrevealed endpoints from the declared uniform draw law."""
    result = copy.deepcopy(sim)
    rng = random.Random(draw_seed)
    k = result.ms//result.s["motor_span_ms"]
    for tape in result.world["motors"]:
        for j, value in enumerate(tape):
            if value is None:
                # Unseen obsolete values never affect a continuation. The
                # 240-ms window already supplies any recent segment needed.
                tape[j] = 230 if j <= k+1 else 230+rng.randint(-result.s["amplitude"], result.s["amplitude"])
    return result


def targets(world, sim, observation_delay_ms=0):
    """Use current/recent motor positions only; no future waypoint lookup.

    Own action-clock phase supplies the next cam contact. The observation uses
    a 100 ms difference and compensates for actuator response, not model delay.
    Future drive pins/tapes are deliberately not queried by this diagnostic.
    """
    result = []
    s = world["spec"]
    observed = max(0, sim.ms-observation_delay_ms)
    for i in range(s["workers"]):
        contact = next((e for e in sim.contacts[sim.contact_index:] if e[1] == i), None)
        if contact is None:
            continue
        _, _, _, kind, fraction = contact
        index = i if kind == "catch" else s["workers"]+1+i if kind == "seal" else i+1
        y = motor(world, index, observed)
        previous = max(0, observed-100)
        velocity = (y-motor(world,index,previous))/max(.001,(observed-previous)/1000)
        target = clamp(y+velocity*.29-path_y(sim.path,fraction),s["min_y"],s["max_y"])
        result.append((i,target))
    return result


def contact_targets(world, sim):
    """Aim ahead at each next contact using only the current drive-pin pair.

    Unlike the velocity diagnostic above, a contact goal stays fixed within
    the displayed motor segment. That gives the actuator time to settle and
    avoids spending mouse gestures on following an irrelevant current height.
    If the contact lies beyond the displayed segment, approach its visible
    endpoint and revise after the next pair becomes visible. Never inspect an
    undisclosed waypoint. Contact phase and actuator rules are privileged
    oracle planning; this is not a screenshot-only solver.
    """
    s = world["spec"]
    span = s["motor_span_ms"]
    result = []
    for i in range(s["workers"]):
        contact = next((e for e in sim.contacts[sim.contact_index:] if e[1] == i), None)
        if contact is None:
            continue
        t, _, _, kind, fraction = contact
        index = i if kind == "catch" else s["workers"]+1+i if kind == "seal" else i+1
        tape = world["motors"][index]
        k = min(sim.ms//span, len(tape)-2)
        a, b = tape[k:k+2]
        f = clamp((t-k*span)/span, 0, 1)
        y = a+(b-a)*f*f*(3-2*f)
        result.append((i, clamp(y-path_y(sim.path, fraction), s["min_y"], s["max_y"])))
    return result


def _rect(ui, selector):
    return ui.read(f"(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; }})()")


def _point(rect, x, y, width, height):
    return [rect[0]+x*rect[2]/width, rect[1]+y*rect[3]/height]


def _button(ui, selector):
    r = _rect(ui,selector)
    ui.send([{"mouse":{"left_click":[r[0]+r[2]/2,r[1]+r[3]/2]}}])


def inspect_drives(ui, world):
    """Lift visible housing covers with ordinary clicks before committing.

    Read-only diagnostics locate already earned inspections. This oracle still
    uses privileged planning; the click trace and screenshots are UI evidence.
    """
    stage = _rect(ui, "#cd2-stage")
    opened = ui.read("clockworkDoppelgangerCustomsV3Model.inspected")
    count = 2*world["spec"]["workers"]+1
    calls = 0
    for i in range(count):
        if not opened[i]:
            n = world["spec"]["workers"]
            column = 2*i if i <= n else 2*(i-n-1)+1
            x = 18+(column+.5)*824/count-3
            ui.send([{"mouse":{"left_click":_point(stage,x,53,860,460)}}])
            calls += 1
    return calls


def solve(ui, truth, *, interval_ms=160, max_calls=500, max_wall_seconds=90):
    from types import SimpleNamespace

    start = time.monotonic()
    world = truth["world"]
    mode = truth["control_condition"]["interaction"]
    stage = _rect(ui,"#cd2-stage")
    calls = 0
    if not ui.read("clockworkDoppelgangerCustomsV3Model.sim !== null"):
        calls += inspect_drives(ui, world)
        first = _point(stage,90,230,860,460)
        last = _point(stage,770,230,860,460)
        ui.send([{"mouse":{"move":first,"buttons":{"left_down":True}}},
                 {"mouse":{"move":last}}, {"mouse":{"buttons":{"left_up":True}}}])
        _button(ui,"#cd2-deploy")
        calls += 2
    # Continuing a calibration must preserve its cam, deployment and progress.
    # Repeating editor/deploy gestures adds delay to an already live relay.
    lever = _rect(ui,"#cd2-levers")
    last_targets = {}
    while time.monotonic()-start < max_wall_seconds:
        data = ui.read("({snapshot:clockworkDoppelgangerCustomsV3Model.sim.snapshot(),path:clockworkDoppelgangerCustomsV3Model.path,contacts:clockworkDoppelgangerCustomsV3Model.sim.contacts,terminal:clockworkDoppelgangerCustomsV3Model.terminal})")
        state = data["snapshot"]
        if state["failed"]:
            raise AssertionError(state["failed"])
        if all(state["collected"]):
            return {"transport_calls":calls,"interval_ms":interval_ms,
                    "privileged_planning":True,"native_action_parity":"determined by caller transport"}
        if state["outgoing"] is not None:
            x,y=passport_position(world,state["outgoing"],state["ms"],state["delivery_times"])
            calls += 1
            if calls >= max_calls:
                raise AssertionError("declared oracle action-call budget exhausted")
            ui.send([{"mouse":{"left_click":_point(stage,x,y,860,460)}}])
            continue
        # Fresh privileged observation per physical gesture. A shared snapshot
        # made later workers' commands stale during sequential full-mode drags.
        # No future motor waypoint or internal game action is used.
        order=sorted(range(world["spec"]["workers"]),key=lambda i:next((e[0] for e in data["contacts"][state["contacts"]:] if e[1]==i),float("inf")))
        for i in order:
            current=ui.read("({snapshot:clockworkDoppelgangerCustomsV3Model.sim.snapshot(),path:clockworkDoppelgangerCustomsV3Model.path,contacts:clockworkDoppelgangerCustomsV3Model.sim.contacts})")
            state=current["snapshot"]
            if state["failed"]:
                raise AssertionError(state["failed"])
            if all(state["collected"]) or state["delivered"]==3:
                break
            sim = SimpleNamespace(ms=state["ms"],contacts=current["contacts"],
                                  contact_index=state["contacts"],path=current["path"])
            choice=dict(contact_targets(world,sim))
            if i not in choice:
                continue
            target=choice[i]
            # Repeat endpoints have no control effect but delay moving hands.
            # Compare requested endpoints: pointer mapping can round the
            # delivered target even when the same endpoint is sent again.
            if last_targets.get(i) == target:
                continue
            actions=[]
            x=world["lever"]["xs"][i]
            p = _point(lever,x,target,240,460)
            if mode == "simplified":
                actions.append({"mouse":{"left_click":p}})
            else:
                actions.extend([{"mouse":{"move":_point(lever,x,state["targets"][i],240,460),"buttons":{"left_down":True}}},
                                {"mouse":{"move":p}}, {"mouse":{"buttons":{"left_up":True}}}])
            calls += 1
            if calls >= max_calls:
                raise AssertionError("declared oracle action-call budget exhausted")
            ui.send(actions)
            last_targets[i] = target
        ui.wait(interval_ms/1000)
    raise AssertionError("declared oracle wall-time budget exhausted")
