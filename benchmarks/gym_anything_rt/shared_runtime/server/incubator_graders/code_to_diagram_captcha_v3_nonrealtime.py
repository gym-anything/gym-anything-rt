"""Independent replay of input-stepped heaters and manual geometric welds.

Standalone standard-library source also loaded unchanged by the static Python grader.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path

MECHANIC_ID = "code_to_diagram_captcha_v3_nonrealtime"
REVISION = "inspected-dispatch-input-step-v1"


def episode_failure_from_attempts(attempts, task_id):
    """Inspect the server journal, not a browser's requested retry policy.

    This mechanic submits only committed certification or terminal execution.
    Cold aiming, partial heat and other recoverable feedback never POST /result
    and therefore never enter this journal. The shared server overwrites each
    archived record's server_grade with its actual grading decision.
    """
    if not isinstance(attempts, list) or not isinstance(task_id, str) or not task_id:
        return None, "Episode failure history is invalid."
    binding_error = None
    for attempt in attempts:
        if not isinstance(attempt, dict):
            return None, "Episode failure history is invalid."
        decision = attempt.get("server_grade")
        if (not isinstance(decision, dict) or decision.get("graded") is not True or
                decision.get("passed") is not False):
            return None, "Episode failure history lacks a verified failed submission."
        bound_task = decision.get("episode_task_id")
        bound_mechanic = decision.get("episode_mechanic_id")
        if bound_task is not None or bound_mechanic is not None:
            if not isinstance(bound_task, str) or not bound_task or not isinstance(bound_mechanic, str):
                return None, "Episode failure history has an invalid task binding."
            # These fields are written by the actual grader against server
            # ground truth, even when the rejected payload misstates its ID.
            if bound_task != task_id or bound_mechanic != MECHANIC_ID:
                continue
        elif attempt.get("mechanic_id") != MECHANIC_ID or attempt.get("task_id") != task_id:
            # Preserve legacy matching UI failures. An unmatched old payload
            # without an authoritative binding cannot establish a clean run.
            binding_error = "Episode failure history has no verified task binding."
            continue
        return "A failed submission already ended this episode.", None
    return None, binding_error


def read_episode_failure(task_id, directory=None):
    """Task-local live gate; offline and Pyodide replay need no filesystem."""
    directory = directory if directory is not None else os.environ.get("GYM_ANYTHING_RT_STATE_DIR")
    if not directory:
        return None, None
    try:
        text = (Path(directory) / "attempts.jsonl").read_text(encoding="utf-8")
        attempts = [json.loads(line) for line in text.splitlines() if line.strip()]
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeError, ValueError):
        return None, "Episode failure history is unavailable."
    return episode_failure_from_attempts(attempts, task_id)


def noise(seed, index):
    n = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    n = ((n ^ (n >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    n = ((n ^ (n >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFFFFFF)/4294967295


def node_position(contract, node, ms):
    spec = contract["physics"]
    u = (max(0, ms)+node["phase_ms"])/spec["motion_span_ms"]
    index, fraction = math.floor(u), u % 1
    blend = fraction*fraction*(3-2*fraction)
    def offset(axis):
        def knot(i):
            return node["motion_knots"][i][axis]
        return knot(index)+(knot(index+1)-knot(index))*blend
    return [node["center"][0]+spec["amplitude_x"]*offset(0),
            node["center"][1]+spec["amplitude_y"]*offset(1)]


def motion_preview(contract, node, ms):
    """The same finite motion information drawn on the field, including a turn.

    This is an observation, not a controller: it never moves a probe or selects
    an edge. The next unannounced segment remains outside the preview.
    """
    spec = contract["physics"]
    span = spec["motion_span_ms"]
    u = (max(0, ms)+node["phase_ms"])/span
    index, fraction = math.floor(u), u % 1
    knots = [[node["center"][axis]+spec[("amplitude_x", "amplitude_y")[axis]]*
              node["motion_knots"][i][axis] for axis in range(2)]
             for i in (index, index+1, index+2)]
    return dict(knots=knots, remaining_ms=(1-fraction)*span, span_ms=span)


def position_from_preview(preview, delay_ms):
    """Prediction using ONLY the displayed preview; no seed or old frames."""
    remaining, span = preview["remaining_ms"], preview["span_ms"]
    if not 0 <= delay_ms <= remaining+span:
        raise ValueError("prediction exceeds visible motion preview")
    if delay_ms <= remaining:
        a, b = preview["knots"][:2]
        f = 1-(remaining-delay_ms)/span
    else:
        a, b = preview["knots"][1:]
        f = (delay_ms-remaining)/span
    blend = f*f*(3-2*f)
    return [a[i]+(b[i]-a[i])*blend for i in range(2)]


def weld_position(contract, node, ms):
    xy = node_position(contract,node,ms)
    return [xy[0]+contract["physics"]["weld_offset"],xy[1]]


def successor(contract, stream):
    node = next(n for n in contract["nodes"] if n["id"]==stream["node"])
    if node["kind"] == "exit":
        return None
    if node["kind"] == "branch":
        bit = (stream["sun"] == stream["diamond"]) if node["predicate"]=="equal" else stream[node["predicate"]]
        return node["yes"] if bit else node["no"]
    if node.get("feedback") and stream["repeat"]:
        return contract["first_gate"]
    return node["next"]


class FlowPhysics:
    def __init__(self, contract):
        self.contract = contract
        self.s = contract["physics"]
        self.tick, self.running, self.failed, self.won = 0, False, "", False
        self.time_ms, self.completed_at_ms = 0.0, None
        self.streams = [dict(copy.deepcopy(p), node=contract["entry_id"],
                             tip=list(p["home"]), velocity=[0., 0.], target=list(p["home"]),
                             candidate=None, charge=0, armed=False, ready_tick=0, done=False, visits=[])
                        for p in contract["streams"]]
        self.by_node = {n["id"]: n for n in contract["nodes"]}

    def start(self):
        if self.running or self.failed or self.won:
            raise ValueError("execution can start only once")
        self.running = True

    def advance(self, end_tick):
        """Compatibility for physics diagnostics using integral 10-ms steps."""
        self.advance_time(end_tick*10)

    def advance_time(self, end_ms):
        """Advance the unchanged physics to a deliberate input boundary.

        The fixed-step contract is enforced by ``grade_attempt``: idle wall
        time and read-only dispatch inspection do not call this method, while
        each heat/aim/select/weld input calls it once with ``action_step_ms``.
        """
        if type(end_ms) not in (int, float) or not math.isfinite(end_ms) or end_ms < self.time_ms:
            raise ValueError("time must be finite and nondecreasing")
        if not self.running:
            return
        while (self.tick+1)*10 <= end_ms and not self.failed and not self.won:
            self.tick += 1
            s, ms = self.s, self.tick*10
            self.time_ms = float(ms)
            positions = {n["id"]: node_position(self.contract,n,ms) for n in self.contract["nodes"]}
            for p in self.streams:
                if p["done"]:
                    continue
                # Both input surfaces set a coordinate, with identical actuator limits.
                for axis in range(2):
                    a = max(-s["tip_acceleration"], min(s["tip_acceleration"],
                        (p["target"][axis]-p["tip"][axis])*s["spring"]-p["velocity"][axis]*s["damping"]))
                    p["velocity"][axis] = max(-s["tip_speed"],min(s["tip_speed"],p["velocity"][axis]+a*.01))
                    p["tip"][axis] = max(s["tip_radius"],min(s["field"][axis]-s["tip_radius"],p["tip"][axis]+p["velocity"][axis]*.01))
                if self.tick < p["ready_tick"]:
                    continue
                if ms-p["ready_tick"]*10 > s["buffer_ms"]:
                    self.failed = f'{p["id"]} execution buffer overflowed.'
                    break
                if p["armed"]:
                    continue
                hits = [(math.dist(p["tip"],xy),key) for key,xy in positions.items()
                        if key != p["node"] and math.dist(p["tip"],xy)+s["tip_radius"] <= s["contact_radius"]+1e-9]
                hit = min(hits)[1] if hits else None
                if hit is None:
                    p["charge"] = max(0,p["charge"]-10*s["charge_decay"])
                    if not p["charge"]:
                        p["candidate"] = None
                else:
                    if p["candidate"] != hit:
                        p["candidate"],p["charge"] = hit,0
                    p["charge"] += 10
                    if p["charge"] >= s["charge_ms"]:
                        if hit != successor(self.contract,p):
                            self.failed = f'{p["id"]} committed an invalid edge {p["node"]} → {hit}.'
                            break
                        p["charge"] = s["charge_ms"]
                        p["armed"] = True
            self.won = all(p["done"] for p in self.streams) and not self.failed
            if ms >= self.s["session_ms"] and not self.won and not self.failed:
                self.failed = "The live program was not completed."
        if not self.failed and not self.won:
            self.time_ms = float(end_ms)

    def pulse(self, stream, point):
        """An actual, non-cancellable weld at the manually chosen endpoint.

        Heating arms the tool; it does not install an edge. All endpoint points
        wholly inside the required contact produce exactly the same next physical
        state. A missed shot shorts the tool and is terminal. Neither input surface
        substitutes a node ID, tracks a contact, nor changes the actuator target
        as part of a weld.
        """
        if not self.running or self.failed or self.won or stream["done"] or not stream["armed"]:
            raise ValueError("weld requires an armed active probe")
        hit = successor(self.contract, stream)
        xy = weld_position(self.contract, self.by_node[hit], self.time_ms)
        if math.dist(point, xy)+self.s["weld_tip_radius"] > self.s["weld_radius"]+1e-9:
            self.failed = f'{stream["id"]} weld missed {hit}; the live wire shorted.'
            return
        arrival, departure = self.by_node[hit], self.by_node[stream["node"]]
        stream["visits"].append(dict(tick=self.tick, time_ms=self.time_ms, source=stream["node"], destination=hit,
                                    sun=stream["sun"], diamond=stream["diamond"], repeat=stream["repeat"]))
        if departure.get("feedback") and stream["repeat"]:
            stream["repeat"] -= 1
        stream["node"],stream["candidate"],stream["charge"],stream["armed"] = hit,None,0,False
        if arrival["operation"]:
            bit = arrival["operation"]
            stream[bit] = not stream[bit]
        stream["done"] = arrival["kind"] == "exit"
        stream["ready_tick"] = math.ceil((self.time_ms+self.s["process_ms"])/10)
        self.won = all(p["done"] for p in self.streams) and not self.failed
        if self.won:
            self.completed_at_ms = self.time_ms

    def snapshot(self):
        return dict(tick=self.tick,time_ms=self.time_ms,completed_at_ms=self.completed_at_ms,
                    running=self.running,failed=self.failed,won=self.won,streams=copy.deepcopy(self.streams))


def finite_point(point, spec):
    if not isinstance(point,list) or len(point)!=2:
        raise ValueError("point must have two coordinates")
    if any(type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=spec["field"][i] for i,v in enumerate(point)):
        raise ValueError("point is non-finite or outside the field")
    return point


def trace_time(tick, time_ms, sim):
    if (type(tick) is not int or type(time_ms) not in (int, float) or
        not math.isfinite(time_ms) or not sim.time_ms <= time_ms <= sim.s["session_ms"] or
        tick != math.floor(time_ms/10)):
        raise ValueError("invalid continuous input time or physics tick")
    return time_ms


def action_step(sim):
    """Return the task-local time advanced by one deliberate control input."""
    step = sim.s.get("action_step_ms")
    if type(step) is not int or step <= 0 or step % 10:
        raise ValueError("invalid input-step timing contract")
    return float(step)


def _same_snapshot(a,b):
    if isinstance(a,dict) and isinstance(b,dict):
        return set(a)==set(b) and all(_same_snapshot(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):
        return len(a)==len(b) and all(_same_snapshot(x,y) for x,y in zip(a,b))
    if type(a) in (int,float) and type(b) in (int,float):
        return math.isfinite(a) and math.isfinite(b) and abs(a-b)<1e-6
    return type(a)==type(b) and a==b


def grade_attempt(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True,passed=False,score=0,feedback=message)
    try:
        if not all(isinstance(v,dict) for v in (payload,ground_truth,public_state)):
            return fail("invalid submission object")
        for key in ("mechanic_id","task_id","challenge_id","revision"):
            if not ground_truth.get(key) or payload.get(key)!=ground_truth[key] or public_state.get(key)!=ground_truth[key]:
                return fail("stale or mismatched "+key)
        if ground_truth["mechanic_id"]!=MECHANIC_ID or ground_truth["revision"]!=REVISION:
            return fail("unknown flow revision")
        for key in ("control_condition","physics","nodes","streams","entry_id","first_gate",
                    "single_attempt","episode_failed","episode_history_error"):
            if public_state.get(key)!=ground_truth.get(key):
                return fail("public/replay contract differs: "+key)
        if ground_truth.get("single_attempt") is not True:
            return fail("unknown episode policy")
        if type(ground_truth.get("episode_failed", False)) is not bool:
            return fail("invalid episode status")
        if ground_truth.get("episode_failed", False):
            return fail("A failed submission already ended this episode.")
        history_error = ground_truth.get("episode_history_error", "")
        if not isinstance(history_error, str) or history_error:
            return fail("Episode failure history is unavailable.")
        mode = ground_truth["control_condition"]["interaction"]
        source = {"full":"probe_drag","simplified":"probe_click"}.get(mode)
        if not source or payload.get("interaction_mode")!=mode:
            return fail("wrong interaction mode")
        events = payload.get("events")
        if not isinstance(events,list) or not 2<=len(events)<=20000:
            return fail("missing or excessive mouse trace")
        sim = FlowPhysics(ground_truth)
        hold,selected,weld_selected,ended = None,None,None,False
        for seq,event in enumerate(events,1):
            if not isinstance(event,dict):
                return fail("event must be an object")
            tick = event.get("tick")
            if type(event.get("sequence")) is not int or event.get("sequence")!=seq or ended:
                return fail("invalid trace order or time")
            time_ms = trace_time(tick, event.get("time_ms"), sim)
            previous_time = sim.time_ms
            kind = event.get("kind")
            if kind=="inspect":
                # Read-only inspection has no quota, unlock effect or physics
                # mutation. It can precede RUN or occur during live execution.
                if (sim.won or time_ms != previous_time or
                        event.get("input_source")!="dispatch_inspection" or
                        event.get("node_id") not in sim.by_node or
                        sim.by_node[event["node_id"]]["kind"]=="exit"):
                    return fail("invalid dispatch inspection")
            elif kind=="run":
                if sim.running or time_ms!=0 or event.get("input_source")!="run_button":
                    return fail("run must begin at the visible run button")
                sim.start()
            elif kind=="seal":
                if (event.get("input_source")!="seal_button" or hold is not None or
                        time_ms != previous_time):
                    return fail("invalid certification")
                ended = True
            elif kind=="release" and mode=="full":
                if hold is None or hold["stream"]!=event.get("stream_id") or event.get("input_source")!=source:
                    return fail("invalid probe release")
                if hold["tool"]=="weld":
                    return fail("weld-tool release must fire a weld")
                finite_point(event.get("point"),sim.s)
                hold = None
                expected = previous_time + action_step(sim)
                if time_ms != expected:
                    return fail("deliberate input did not advance one fixed physics step")
                sim.advance_time(time_ms)
                if sim.failed:
                    return fail(sim.failed)
            else:
                if not sim.running or sim.won or event.get("input_source")!=source:
                    return fail("wrong input surface or inactive execution")
                lane = event.get("stream_id")
                if lane not in {p["id"] for p in sim.streams}:
                    return fail("unknown probe")
                p = next(p for p in sim.streams if p["id"]==lane)
                if p["done"]:
                    return fail("completed probe is unavailable")
                if kind=="select" and mode=="simplified":
                    selected = lane
                    weld_selected = None
                elif kind=="weld_select" and mode=="simplified":
                    if selected!=lane or not p["armed"]:
                        return fail("select an armed probe before its weld tool")
                    weld_selected = lane
                elif kind=="target" and mode=="simplified":
                    if selected!=lane:
                        return fail("click the probe selector before aiming")
                    if weld_selected is not None:
                        return fail("weld-mode field click must fire a weld")
                    point=finite_point(event.get("point"),sim.s)
                    if not p["armed"]:
                        p["target"] = list(point)
                elif kind=="pulse":
                    point = finite_point(event.get("point"),sim.s)
                    if (mode=="full" and (hold is None or hold["stream"]!=lane or hold["tool"]!="weld")) or (mode=="simplified" and (selected!=lane or weld_selected!=lane)):
                        return fail("weld did not use the selected or held probe")
                    sim.pulse(p,point)
                    if mode=="full":
                        hold = None
                    weld_selected = None
                elif kind=="grab" and mode=="full":
                    point = finite_point(event.get("point"),sim.s)
                    reachable = [q for q in sim.streams if not q["done"] and
                                 math.dist(point,q["tip"])<=sim.s["tip_radius"]+6]
                    nearest = min(reachable,key=lambda q:math.dist(point,q["tip"]),default=None)
                    if hold is not None or nearest is None:
                        return fail("drag did not begin on the visible probe tip")
                    # The browser chooses the nearest tip; stable stream order
                    # breaks exact ties. A trace cannot select an occluded probe.
                    if nearest["id"]!=lane:
                        return fail("drag did not grab the nearest visible probe tip")
                    tool="weld" if p["armed"] else "heat"
                    if event.get("tool")!=tool:
                        return fail("grab did not use the visible heat/weld tool")
                    hold = dict(stream=lane,tool=tool)
                elif kind in ("move","release") and mode=="full":
                    if hold is None or hold["stream"]!=lane:
                        return fail("probe is not held")
                    point = finite_point(event.get("point"),sim.s)
                    if kind=="move":
                        if hold["tool"]=="heat" and not p["armed"]:
                            p["target"] = list(point)
                    else:
                        if hold["tool"]=="weld":
                            return fail("weld-tool release must fire a weld")
                        hold = None
                else:
                    return fail("unsupported control; no brake, reset or automatic connection exists")
                if sim.failed:
                    return fail(sim.failed)
                if sim.won:
                    # The terminal weld is evaluated at the current boundary;
                    # its post-action step is intentionally not needed.
                    if time_ms != previous_time:
                        return fail("terminal input time differs from replay")
                else:
                    expected = previous_time + action_step(sim)
                    if time_ms != expected:
                        return fail("deliberate input did not advance one fixed physics step")
                    sim.advance_time(time_ms)
                    if sim.failed:
                        return fail(sim.failed)
        final_tick = payload.get("final_tick")
        final_time = trace_time(final_tick, payload.get("final_time_ms"), sim)
        if final_time != sim.time_ms:
            return fail("final time differs from terminal replay")
        sim.advance_time(final_time)
        if final_tick != sim.tick or final_time != sim.time_ms:
            return fail("final time differs from terminal replay")
        if sim.failed:
            return fail(sim.failed)
        if not _same_snapshot(payload.get("final_state"),sim.snapshot()):
            return fail("final state differs from independent contact replay")
        passed = ended and hold is None and sim.won and payload.get("completed") is True
        return dict(graded=True,passed=passed,score=100 if passed else 0,
                    feedback=f'live control-flow replay: {sum(p["done"] for p in sim.streams)}/{len(sim.streams)} executions; {sum(len(p["visits"]) for p in sim.streams)} valid edges')
    except (KeyError,TypeError,ValueError,OverflowError,StopIteration) as exc:
        return fail("invalid control-flow trace: "+str(exc))


def grade(payload, ground_truth, public_state):
    decision = grade_attempt(payload, ground_truth, public_state)
    if decision.get("passed"):
        failure, error = read_episode_failure(ground_truth["task_id"])
        if failure or error:
            decision = dict(graded=True, passed=False, score=0, feedback=failure or error)
    if (isinstance(ground_truth, dict) and ground_truth.get("mechanic_id") == MECHANIC_ID and
            isinstance(ground_truth.get("task_id"), str) and ground_truth["task_id"]):
        # The shared server overwrites browser-supplied server_grade and stores
        # this decision unchanged. Journal identity must come from bound truth,
        # including a rejected certification with an incorrect payload task ID.
        decision.update(episode_task_id=ground_truth["task_id"], episode_mechanic_id=MECHANIC_ID)
    return decision


def cheat(public_state, ground_truth):
    return {"program":ground_truth.get("nodes",[]), "note":"Privileged planning only; no synthetic success action."}
