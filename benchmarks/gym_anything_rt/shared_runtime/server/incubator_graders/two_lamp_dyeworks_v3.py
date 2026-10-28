"""Standalone Python/WebAssembly replay of valves, pipes, dye and cloth.

No browser outcome, quality counter, density, or success flag is authoritative.
The browser has a separate implementation; agreement is checked numerically.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys

MECHANIC_ID = "two_lamp_dyeworks_v3"
REVISION = "flow-spectrum-v3-stock-sampling"
POLICY_REVISION = "approved-retry-policy-20261006"


def episode_state_directory():
    """Use the unchanged server's actual state directory, including --state-dir."""
    for index, arg in enumerate(sys.argv):
        if arg == "--state-dir" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
        if arg.startswith("--state-dir="):
            return Path(arg.split("=", 1)[1])
    return Path(os.environ.get("GYM_ANYTHING_RT_STATE_DIR", "/tmp/gym_anything_rt"))


def read_episode_history(task_id, directory=None):
    """Read retained server receipts; never infer failure merely from a reset."""
    history = dict(schema_version=1, policy_revision=POLICY_REVISION,
                   task_id=task_id, attempts=[], error=None)
    path = (Path(directory) if directory is not None else episode_state_directory()) / "attempts.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return history
    except (OSError, UnicodeError) as exc:
        history["error"] = "Cannot read retained attempts: " + str(exc)
        return history
    try:
        for line in lines:
            if line.strip():
                receipt = json.loads(line)
                if not isinstance(receipt, dict):
                    raise ValueError("attempt receipt is not an object")
                history["attempts"].append(receipt)
    except (ValueError, TypeError) as exc:
        history["error"] = "Invalid retained attempts: " + str(exc)
    return history


def first_failure(history, task_id):
    """Only a server-replayed terminal roll/certification is qualifying evidence.

    Old, unchanged receipts have replay metrics but no qualifying_failure bit.
    Malformed/stale input rejection has neither and cannot establish a failed
    committed roll. Preparation probes never submit or enter this journal.
    """
    if (not isinstance(history, dict) or history.get("schema_version") != 1
            or history.get("policy_revision") != POLICY_REVISION
            or history.get("task_id") != task_id or not isinstance(history.get("attempts"), list)):
        return None, "Invalid task-bound retry history"
    if history.get("error"):
        return None, str(history["error"])
    for index, receipt in enumerate(history["attempts"], 1):
        if not isinstance(receipt, dict):
            return None, "Invalid retained attempt receipt"
        if receipt.get("task_id") != task_id or receipt.get("mechanic_id") != MECHANIC_ID:
            continue
        decision = receipt.get("server_grade") or {}
        if not isinstance(decision, dict):
            return None, "Invalid retained server grade"
        events = receipt.get("events")
        state = receipt.get("final_state") or {}
        verified_failure = (
            decision.get("graded") is True and decision.get("passed") is False
            and isinstance(state, dict) and state.get("status") == "failed"
            and isinstance(events, list) and bool(events) and isinstance(events[-1], dict)
            and events[-1].get("kind") == "submit"
            and (decision.get("qualifying_failure") is True
                 or ("usable_mm" in decision and "yield_percent" in decision
                     and str(decision.get("feedback", "")).startswith("failed:"))))
        if verified_failure:
            digest = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return dict(task_id=task_id, challenge_id=receipt.get("challenge_id"),
                        attempt_index=index, attempt_sha256=digest,
                        feedback=str(decision.get("feedback") or "Committed rolls failed")), None
    return None, None


def export_episode_history(export_path, directory=None):
    """Task-owned extension of the frozen shared exporter; preserve its fields."""
    path = Path(export_path)
    exported = json.loads(path.read_text(encoding="utf-8"))
    task_id = (exported.get("ground_truth") or {}).get("task_id")
    exported["retry_policy_history"] = read_episode_history(task_id, directory)
    temporary = path.with_suffix(".policy.tmp")
    temporary.write_text(json.dumps(exported, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    path.chmod(0o666)
    return exported


def verify_exported(exported, task_info=None):
    def reject(message):
        return dict(passed=False, score=0, feedback=message)
    truth = exported.get("ground_truth") or {}
    public = exported.get("public_state") or {}
    if not isinstance(truth, dict) or not isinstance(public, dict):
        return reject("Invalid bound challenge")
    bound_id = (task_info or {}).get("id") if isinstance(task_info, dict) else None
    if bound_id and bound_id != truth.get("task_id"):
        return reject("Export belongs to another task")
    failures = exported.get("graded_failures", 0)
    if type(failures) is not int or failures < 0:
        return reject("Invalid archived submission count")
    history = exported.get("retry_policy_history")
    if history is None:
        # Historical exports stay unchanged. New generated tasks require the
        # task-owned export hook; a final zero counter alone is not proof.
        if truth.get("retry_policy_revision") == POLICY_REVISION:
            return reject("Missing retained retry-policy history")
        if failures:
            return reject("A failed submission already ended this episode.")
    else:
        failure, error = first_failure(history, truth.get("task_id"))
        if error:
            return reject(error)
        if len(history["attempts"]) != failures:
            return reject("Archived submission count disagrees with retained history")
        if failure:
            return reject("First committed failure retained: " + failure["feedback"])
    payload = exported.get("result")
    if not isinstance(payload, dict) or not payload:
        return reject("No submitted UI result found.")
    decision = _grade_replay(payload, truth, public, check_runtime_history=False)
    passed = bool(decision.get("passed"))
    return dict(passed=passed, score=decision.get("score", 0) if passed else 0,
                feedback=str(decision.get("feedback") or "independent replay failed"))


def colors(density, pigments, spectrum):
    r = [base*math.exp(-spectrum["strength"]*sum(d*p["absorption"][band]
         for d,p in zip(density,pigments))) for band,base in enumerate(spectrum["base"])]
    out = {}
    for lamp,power in spectrum["lamps"].items():
        white = [sum(a*b for a,b in zip(power,row)) for row in spectrum["cie"]]
        relative = [sum(a*b*c for a,b,c in zip(power,r,row))/w
                    for row,w in zip(spectrum["cie"],white)]
        def f(v):
            return v**(1/3) if v > (6/29)**3 else v/(3*(6/29)**2)+4/29
        fx,fy,fz = map(f,relative)
        lab = [116*fy-16,500*(fx-fy),200*(fy-fz)]
        def inverse(v):
            return v**3 if v > 6/29 else 3*(6/29)**2*(v-4/29)
        x,y,z = .95047*inverse(fx),inverse(fy),1.08883*inverse(fz)
        linear = [3.2406*x-1.5372*y-.4986*z,-.9689*x+1.8758*y+.0415*z,.0557*x-.204*y+1.057*z]
        rgb = []
        for v,cast in zip(linear,spectrum["casts"][lamp]):
            v = max(0,min(1,v))
            encoded = 12.92*v if v <= .0031308 else 1.055*v**(1/2.4)-.055
            rgb.append(math.floor(255*max(0,min(1,encoded*cast))+.5))
        out[lamp] = dict(lab=lab,rgb=rgb)
    return out


def stock_strength(nodes, ms):
    """Continuous monotone cubic between parcels; no short repeating orbit."""
    if ms <= 0:
        return nodes[0]["strength"]
    for a,b in zip(nodes,nodes[1:]):
        if ms <= b["t_ms"]:
            u = (ms-a["t_ms"])/(b["t_ms"]-a["t_ms"])
            return a["strength"]+(b["strength"]-a["strength"])*u*u*(3-2*u)
    return nodes[-1]["strength"]


def rail(contract, vat, pigment):
    count = len(contract["vats"])
    left = 20 + vat * 560 if count == 2 else 280
    return [left+132, 282+pigment*44, 302]


def quantize(value):
    return math.floor(max(0,min(1,value))*100+.5)/100


class Plant:
    def __init__(self, contract):
        self.c = contract
        self.p = contract["physics"]
        self.tick = 0
        self.start_tick = None
        self.n = len(contract["pigments"])
        self.m = len(contract["vats"])
        self.targets = [[0.0]*self.n for _ in range(self.m)]
        self.valves = [[0.0]*self.n for _ in range(self.m)]
        self.density = [[0.0]*self.n for _ in range(self.m)]
        self.pipe = [[[0.0]*self.n for _ in range(self.m)]
                     for _ in range(self.p["pipe_ms"]//self.p["tick_ms"])]
        self.bad_mm = [0.0]*self.m
        self.errors = [0.0]*self.m
        self.produced_mm = 0.0
        self.status = "preparation"
        self.failure = ""
        for v in range(self.m):
            current = colors(self.density[v],contract["pigments"],contract["spectrum"])
            self.errors[v] = max(math.dist(current[lamp]["lab"],contract["vats"][v]["target"][lamp]["lab"])
                                 for lamp in ("north","sodium"))

    def begin(self):
        if self.start_tick is not None or self.status != "preparation":
            raise ValueError("production can start only once")
        self.start_tick = self.tick
        self.status = "running"

    def advance(self, target):
        dt = self.p["tick_ms"]/1000
        slew = self.p["valve_speed"]*dt
        blend = 1-math.exp(-self.p["tick_ms"]/self.p["mixing_ms"])
        while self.tick < target and self.status not in ("failed","complete"):
            self.tick += 1
            for row,desired in zip(self.valves,self.targets):
                for i,value in enumerate(row):
                    row[i] += max(-slew,min(slew,desired[i]-value))
            gain = 1/(1+self.p["coupling"]*sum(sum(row) for row in self.valves))
            ms = 0 if self.start_tick is None else (self.tick-self.start_tick)*self.p["tick_ms"]
            strengths = [stock_strength(self.c["stock"][p["id"]],ms) for p in self.c["pigments"]]
            self.pipe.append([[self.p["supply_scale"]*strengths[i]*row[i]*gain
                               for i in range(self.n)] for row in self.valves])
            delayed = self.pipe.pop(0)
            for v in range(self.m):
                for i in range(self.n):
                    equilibrium = delayed[v][i]
                    self.density[v][i] += (equilibrium-self.density[v][i])*blend
                current = colors(self.density[v],self.c["pigments"],self.c["spectrum"])
                self.errors[v] = max(math.dist(current[lamp]["lab"],self.c["vats"][v]["target"][lamp]["lab"])
                                     for lamp in ("north","sodium"))
            if self.start_tick is not None and ms > self.p["leader_ms"]:
                length = self.p["cloth_speed_mm_s"]*dt
                self.produced_mm += length
                for v,error in enumerate(self.errors):
                    if error > self.p["tolerance"]:
                        self.bad_mm[v] += length
                    if self.bad_mm[v] > self.p["waste_mm"]+1e-7:
                        self.status = "failed"
                        self.failure = f"{self.c['vats'][v]['name']} spoiled too much cloth"
            if self.status != "failed" and self.start_tick is not None and ms >= self.p["leader_ms"]+self.p["run_ms"]:
                self.status = "complete"

    def summary(self):
        return dict(tick=self.tick, start_tick=self.start_tick, status=self.status,
                    density=self.density, valves=self.valves, targets=self.targets,
                    bad_mm=self.bad_mm, produced_mm=self.produced_mm)


def _finite(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError("non-finite numeric value")
    return float(value)


def _point(raw, contract):
    if not isinstance(raw,list) or len(raw) != 2:
        raise ValueError("malformed pointer point")
    point = [_finite(v) for v in raw]
    if not 0 <= point[0] <= contract["stage"]["width"] or not 0 <= point[1] <= contract["stage"]["height"]:
        raise ValueError("pointer outside workbench")
    return point


def _close(a,b):
    if isinstance(b,list):
        return isinstance(a,list) and len(a)==len(b) and all(_close(x,y) for x,y in zip(a,b))
    return abs(_finite(a)-b) <= 2e-6


def grade(payload, ground_truth, public_state):
    return _grade_replay(payload, ground_truth, public_state, check_runtime_history=True)


def _grade_replay(payload, ground_truth, public_state, *, check_runtime_history):
    def fail(message):
        return dict(graded=True,passed=False,score=0,feedback=message)
    try:
        if not all(isinstance(d,dict) for d in (payload,ground_truth,public_state)):
            return fail("malformed result or challenge")
        for key in ("mechanic_id","task_id","challenge_id"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("wrong or stale "+key)
        if ground_truth["mechanic_id"] != MECHANIC_ID or ground_truth["revision"] != REVISION or payload.get("revision") != REVISION:
            return fail("wrong dyeworks revision")
        for key in ("revision","world_digest","physics","stock","pigments","vats","spectrum","stage","control_condition","inspection"):
            if ground_truth.get(key) != public_state.get(key):
                return fail("public contract mismatch: "+key)
        for key in ("single_attempt", "retry_policy_revision", "episode_failed", "episode_failure", "episode_history_error"):
            if ground_truth.get(key) != public_state.get(key):
                return fail("public policy contract mismatch: " + key)
        if ground_truth.get("single_attempt") is not True:
            return fail("dyeworks requires the task's first-failure policy")
        if ground_truth.get("retry_policy_revision") not in (None, POLICY_REVISION):
            return fail("unsupported retry-policy revision")
        if ground_truth.get("episode_history_error"):
            return fail("Retained history unavailable: " + str(ground_truth["episode_history_error"]))
        if ground_truth.get("episode_failed"):
            return fail("First committed failure retained; this episode has ended.")
        if check_runtime_history:
            prior, history_error = first_failure(read_episode_history(ground_truth["task_id"]), ground_truth["task_id"])
            if prior or history_error:
                return fail(history_error or "First committed failure retained: " + prior["feedback"])
        condition = ground_truth.get("control_condition")
        mode = (condition or {}).get("interaction","full")
        if mode not in ("full","simplified") or payload.get("interaction_mode") != mode or payload.get("control_condition") != condition:
            return fail("wrong control condition")
        for v,target in enumerate(ground_truth["target_density"]):
            calculated = colors(target,ground_truth["pigments"],ground_truth["spectrum"])
            for lamp in ("north","sodium"):
                if not _close(ground_truth["vats"][v]["target"][lamp]["lab"],calculated[lamp]["lab"]):
                    return fail("target spectrum mismatch")
            if "fiber_spectrum" in ground_truth["vats"][v]:
                spectrum=ground_truth['spectrum']
                expected=[base*math.exp(-spectrum['strength']*sum(
                    d*p['absorption'][band] for d,p in zip(target,ground_truth['pigments'])))
                    for band,base in enumerate(spectrum['base'])]
                if not _close(ground_truth['vats'][v]['fiber_spectrum'],expected):
                    return fail("pinned fibre spectrum mismatch")
        events = payload.get("events")
        if not isinstance(events,list) or not 1 <= len(events) <= 20000:
            return fail("missing or excessive input trace")
        sim = Plant(ground_truth)
        drag = None
        submitted = False
        for seq,event in enumerate(events,1):
            if not isinstance(event,dict) or event.get("sequence") != seq or type(event.get("tick")) is not int:
                return fail("invalid event sequence")
            tick = event["tick"]
            if not sim.tick <= tick <= 3600 or submitted:
                return fail("invalid event time or event after certification")
            sim.advance(tick)
            if sim.tick != tick:
                return fail("input after terminal plant state")
            kind = event.get("kind")
            if kind == "submit":
                submitted = True
                if sim.status not in ("failed", "complete"):
                    sim.status = "failed"
                    sim.failure = "Rolls certified before production finished"
                continue
            if sim.status in ("failed","complete"):
                return fail("terminal cloth cannot be changed")
            if kind == "stock_sample":
                i = event.get("pigment")
                if type(i) is not int or not 0 <= i < sim.n or drag is not None:
                    return fail("invalid dye-stock inspection")
                point = _point(event.get("point"), ground_truth)
                width = 1080 / sim.n
                x = 28 + i * width
                if (event.get("input_source") != "stock_spot_test" or not 3 <= point[1] <= 23
                        or not x <= point[0] <= x+width-72):
                    return fail("inspection must land on the visible inlet spot test")
                pigment = ground_truth['pigments'][i]
                ms = 0 if sim.start_tick is None else (sim.tick-sim.start_tick)*sim.p['tick_ms']
                strength = stock_strength(ground_truth['stock'][pigment['id']], ms)
                density = [0.0] * sim.n
                density[i] = ground_truth['inspection']['sample_density'] * strength
                expected = colors(density, ground_truth['pigments'], ground_truth['spectrum'])
                sample = event.get('sample')
                if (not isinstance(sample, dict) or sample.get('pigment_id') != pigment['id']
                        or not _close(sample.get('strength'), strength)
                        or any(not _close((sample.get('rgb') or {}).get(lamp), expected[lamp]['rgb'])
                               for lamp in ('north', 'sodium'))):
                    return fail('stock spot-test response disagrees with the measured dye')
                continue
            if kind == "begin":
                if drag is not None or event.get("input_source") != "start_button":
                    return fail("invalid production start")
                sim.begin()
                continue
            if kind not in ("valve_click","drag_start","drag_move","drag_end","drag_cancel"):
                return fail("unknown action; no stop, brake, reset or retry")
            v,i = event.get("vat"),event.get("pigment")
            if type(v) is not int or type(i) is not int or not 0 <= v < sim.m or not 0 <= i < sim.n:
                return fail("invalid valve identity")
            point = _point(event.get("point"),ground_truth)
            x,y,width = rail(ground_truth,v,i)
            source = "rail_click" if mode == "simplified" else "valve_drag"
            if event.get("input_source") != source:
                return fail("wrong valve input surface")
            if kind == "valve_click":
                if mode != "simplified" or drag is not None or not x-16 <= point[0] <= x+width+16 or abs(point[1]-y)>16:
                    return fail("click must land on visible valve rail")
                sim.targets[v][i] = quantize((point[0]-x)/width)
            elif mode != "full":
                return fail("drag is full interaction only")
            elif kind == "drag_start":
                if drag is not None or math.dist(point,[x+width*sim.targets[v][i],y])>16.001:
                    return fail("drag must begin on the visible valve handle")
                drag = (v,i,point[0]-x-width*sim.targets[v][i])
            else:
                if drag is None or drag[:2] != (v,i):
                    return fail("valve has no active pointer capture")
                if kind != "drag_cancel":
                    sim.targets[v][i] = quantize((point[0]-x-drag[2])/width)
                if kind in ("drag_end","drag_cancel"):
                    drag = None
        if not submitted:
            return fail("rolls were not certified")
        summary = payload.get("final_state")
        if not isinstance(summary,dict):
            return fail("missing replay-bound final state")
        actual = sim.summary()
        for key in ("tick","start_tick","status"):
            if summary.get(key) != actual[key]:
                return fail("final "+key+" disagrees with replay")
        for key in ("density","valves","targets","bad_mm","produced_mm"):
            if not _close(summary.get(key),actual[key]):
                return fail("final "+key+" disagrees with replay")
        passed = sim.status == "complete" and payload.get("completed") is True
        usable_mm = sim.produced_mm*sim.m-sum(sim.bad_mm)
        planned_mm = sim.p["run_ms"]*sim.p["cloth_speed_mm_s"]/1000*sim.m
        yield_percent = 100*usable_mm/planned_mm
        return dict(graded=True,passed=passed,score=yield_percent if passed else 0,
                    qualifying_failure=sim.status == "failed",
                    usable_mm=usable_mm,yield_percent=yield_percent,
                    feedback=(f"{sim.status}: {sim.produced_mm:g} mm per roll; spoiled "
                              +", ".join(f"{x:g}" for x in sim.bad_mm)
                              +f" mm; usable yield {yield_percent:.2f}%; "+sim.failure))
    except (KeyError,TypeError,ValueError,IndexError,OverflowError) as exc:
        return fail("invalid dye transcript: "+str(exc))


def cheat(public_state, ground_truth):
    """Development planning information, never part of the player's controls."""
    del public_state
    return dict(target_density=ground_truth.get("target_density",[]), privileged_planning=True)
