"""Independent, standalone Python replay. Suitable for the frozen Pyodide seam."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import sys

MECHANIC_ID = "wonky_text_hostile_rendering_v3_nonrealtime"
RETRY_POLICY = "first_failure"
HISTORY_KEY = "wonky_text_hostile_rendering_v3_nonrealtime_episode_history"


def episode_state_directory():
    """Use the existing runtime setting/CLI; offline replay has no journal."""
    directory = os.environ.get("GYM_ANYTHING_RT_STATE_DIR")
    if directory:
        return directory
    if Path(sys.argv[0]).name in ("minigame_server.py", "setup_task.py"):
        if "--state-dir" in sys.argv:
            index = sys.argv.index("--state-dir") + 1
            if index < len(sys.argv):
                return sys.argv[index]
        return "/tmp/gym_anything_rt"
    return None


def read_attempts(directory):
    if not directory:
        return [], None
    try:
        text = (Path(directory) / "attempts.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()], None
    except FileNotFoundError:
        return [], None
    except (OSError, UnicodeError, ValueError):
        return None, "Episode failure history is unavailable."


def episode_failure_from_attempts(attempts, task_id):
    """Only server-graded commitments enter this task's failure journal.

    Preparation, pointer misses and recoverable tracking never POST /result.
    The server replaces server_grade, so its bound IDs also cover rejected
    submissions that misstate their own identity. Preserve legacy UI failures.
    """
    if not isinstance(attempts, list) or not isinstance(task_id, str) or not task_id:
        return None, "Invalid episode failure history."
    for attempt in attempts:
        if not isinstance(attempt, dict):
            return None, "Invalid episode failure history."
        decision = attempt.get("server_grade")
        if (not isinstance(decision, dict) or decision.get("graded") is not True
                or decision.get("passed") is not False):
            return None, "Episode history lacks a verified failed submission."
        mechanic = decision.get("episode_mechanic_id")
        bound_task = decision.get("episode_task_id")
        if mechanic is not None or bound_task is not None:
            if not isinstance(mechanic, str) or not isinstance(bound_task, str) or not bound_task:
                return None, "Episode history has no verified task binding."
            if mechanic != MECHANIC_ID or bound_task != task_id:
                continue
        elif attempt.get("mechanic_id") != MECHANIC_ID or attempt.get("task_id") != task_id:
            # Old matching UI records remain evidence. An unmatched old payload
            # cannot establish which task was rejected, or a clean trajectory.
            return None, "Episode history has no verified task binding."
        return "A failed submission already ended this episode.", None
    return None, None


def read_episode_failure(task_id, directory=None):
    attempts, error = read_attempts(directory if directory is not None else episode_state_directory())
    return (None, error) if error else episode_failure_from_attempts(attempts, task_id)


def attach_episode_history(exported, directory):
    """Append evidence without changing the common export or prior attempts."""
    attempts, error = read_attempts(directory)
    truth = exported.get("ground_truth") or {}
    exported[HISTORY_KEY] = dict(schema_version=1, mechanic_id=truth.get("mechanic_id"),
        task_id=truth.get("task_id"), attempts=attempts, error=error)
    return exported


def rejected(message):
    return dict(graded=True, passed=False, score=0, feedback=message)


def verify_export(exported):
    if not isinstance(exported, dict):
        return rejected("Invalid exported result.")
    truth, public = exported.get("ground_truth"), exported.get("public_state")
    if not isinstance(truth, dict) or not isinstance(public, dict):
        return rejected("Missing task binding.")
    failures = exported.get("graded_failures")
    if type(failures) is not int or failures < 0:
        return rejected("Invalid graded failure count.")
    if failures:
        return rejected("A failed submission already ended this episode.")
    history = exported.get(HISTORY_KEY)
    if (not isinstance(history, dict) or history.get("schema_version") != 1
            or history.get("mechanic_id") != MECHANIC_ID
            or history.get("task_id") != truth.get("task_id") or history.get("error")):
        return rejected("Missing or invalid bound episode history.")
    attempts = history.get("attempts")
    failure, error = episode_failure_from_attempts(attempts, truth.get("task_id"))
    if failure or error:
        return rejected(failure or error)
    if len(attempts) != failures:
        return rejected("Episode journal and failure count differ.")
    result = exported.get("result")
    if not isinstance(result, dict) or not result:
        return rejected("No submitted UI result found.")
    # An exported episode is independent of any ambient live server directory.
    return _grade_attempt(result, truth, public)


def target(press, plate, t_ms):
    u = max(0, t_ms) + plate["phase_ms"]
    times = plate["node_times_ms"]
    index = 0
    while index < len(times)-2 and u >= times[index+1]:
        index += 1
    f = min(1, (u-times[index]) / (times[index+1]-times[index]))
    s = f * f * (3 - 2 * f)
    a, b = plate["nodes"][index:index+2]
    return [a[j] + (b[j] - a[j]) * s for j in range(2)]


def new_state(press):
    return dict(t_ms=0, started=False, ended=False, failed=False, spoil_ms=0.0, clean_ms=0,
                positions=[list(p["initial"]) for p in press["plates"]],
                goals=[list(p["initial"]) for p in press["plates"]], drag=None, pending=[])


def advance_action(press, state):
    """Run one fixed beat caused by a complete set of deliberate controls.

    There is no idle-time operation in this counterpart.  The browser and
    replay advance the same 600 ms only after every existing plate control has
    been used once, leaving the visible decision state stable between beats.
    """
    end = min(state["t_ms"] + press["preview_ms"], press["duration_ms"])
    while state["started"] and not state["ended"] and state["t_ms"] < end:
        state["t_ms"] += press["tick_ms"]
        worst = 0.0
        for index, plate in enumerate(press["plates"]):
            p, goal = state["positions"][index], state["goals"][index]
            alpha = 1 - math.exp(-press["tick_ms"] / press["servo_ms"])
            for j in range(2):
                p[j] += (goal[j] - p[j]) * alpha
            error = math.dist(p, target(press, plate, state["t_ms"]))
            worst = max(worst, min(1.0, max(0.0, (error - press["tolerance"]) / press["tolerance"])))
        state["spoil_ms"] += worst * press["tick_ms"]
        if worst == 0:
            state["clean_ms"] += press["tick_ms"]
        if state["spoil_ms"] >= press["spoil_limit_ms"]:
            state["ended"] = state["failed"] = True
        elif state["clean_ms"] >= press["required_clean_ms"]:
            state["ended"] = True
        elif state["t_ms"] == press["duration_ms"]:
            state["ended"] = state["failed"] = True
    return state


def commit_action(press, state, plate_index):
    """Queue one existing plate control and settle a complete fixed beat."""
    if not state["started"] or state["ended"]:
        return state
    if plate_index not in state["pending"]:
        state["pending"].append(plate_index)
    if len(state["pending"]) == len(press["plates"]):
        state["pending"].clear()
        advance_action(press, state)
    return state


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def point(value, press):
    return (isinstance(value, list) and len(value) == 2 and all(finite(v) for v in value)
            and press["bounds"][0] <= value[0] <= press["bounds"][1]
            and press["bounds"][2] <= value[1] <= press["bounds"][3])


def grade(payload, ground_truth, public_state):
    if isinstance(ground_truth, dict) and ground_truth.get("mechanic_id") == MECHANIC_ID:
        failure, error = read_episode_failure(ground_truth.get("task_id"))
        if failure or error:
            decision = rejected(failure or error)
        else:
            decision = _grade_attempt(payload, ground_truth, public_state)
        decision.update(episode_mechanic_id=MECHANIC_ID, episode_task_id=ground_truth.get("task_id"))
        return decision
    return _grade_attempt(payload, ground_truth, public_state)


def _grade_attempt(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    if not all(isinstance(v, dict) for v in (payload, ground_truth, public_state)):
        return fail("letterpress contract and payload must be objects")
    try:
        for key in ("mechanic_id", "task_id", "challenge_id"):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail("stale or wrong " + key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("press", "control_condition", "single_attempt", "episode_failed", "episode_history_error"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public contract mismatch: " + key)
        if ground_truth.get("single_attempt") is not True:
            return fail("invalid one-attempt contract")
        if ground_truth.get("episode_failed"):
            return fail("A failed submission already ended this episode.")
        if ground_truth.get("episode_history_error"):
            return fail(str(ground_truth["episode_history_error"]))
        press = ground_truth["press"]
        mode = ground_truth["control_condition"]["interaction"]
        if payload.get("interaction_mode") != mode or mode not in ("full", "simplified"):
            return fail("wrong interaction")
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 3000:
            return fail("missing or oversized transcript")
        state = new_state(press)
        last = 0
        finished = False
        by_id = {p["id"]: i for i, p in enumerate(press["plates"])}
        for sequence, event in enumerate(events, 1):
            t = event["t_ms"]
            if (event.get("sequence") != sequence or not finite(t) or t != int(t)
                    or not last <= t <= press["duration_ms"] or event.get("input_source") != mode or finished):
                return fail("invalid event sequence, time or input surface")
            last = t
            if state["started"] and t != state["t_ms"]:
                return fail("task time can advance only after a complete plate-command beat")
            if not state["started"] and t != 0:
                return fail("preparation must have zero press time")
            kind = event.get("kind")
            if kind == "start":
                if state["started"] or t != 0 or state["drag"] is not None:
                    return fail("invalid or repeated start")
                state["started"] = True
            elif kind == "inspect":
                # A read-only loupe probe, before or during the live run. It
                # neither pauses the paper nor supplies credit toward success.
                # There is deliberately no required inspection count.
                if state["ended"] or event.get("plate_id") not in by_id:
                    return fail("inspection after terminal state or unknown plate")
                plate = press["plates"][by_id[event["plate_id"]]]
                p = event.get("point")
                if (not isinstance(p, list) or len(p) != 2 or not all(finite(v) for v in p)
                        or not 0 <= p[0] <= press["sleeve_size"][0]
                        or not 0 <= p[1] <= press["sleeve_size"][1]
                        or math.dist(p, [plate["stamp_x"], 32]) > press["loupe_radius"] - press["stamp_radius"] + .001):
                    return fail("loupe did not expose the plate stamp")
            elif kind in ("down", "set", "up"):
                if state["ended"] or event.get("plate_id") not in by_id:
                    return fail("input after terminal state or unknown plate")
                i = by_id[event["plate_id"]]
                p = event.get("point")
                if not point(p, press) or (press["axes"] == 1 and kind == "set" and p[1] != 100):
                    return fail("point outside the rendered registration plane")
                if mode == "full":
                    if kind == "down":
                        if state["drag"] is not None or math.dist(p, state["positions"][i]) > press["handle_radius"] + 0.02:
                            return fail("drag did not begin on the physical handle")
                        state["drag"] = i
                    elif kind == "set":
                        if state["drag"] != i:
                            return fail("movement without held handle")
                        state["goals"][i] = list(p)
                    elif state["drag"] == i:
                        state["drag"] = None
                    else:
                        return fail("release without a held handle")
                elif kind == "set":
                    state["goals"][i] = list(p)
                else:
                    return fail("direct drag in proxy mode")
                # Safe preparation positions the actuators. It does not reveal
                # a future route or pause anything after the paper starts.
                if not state["started"]:
                    state["positions"][i] = list(state["goals"][i])
                elif (mode == "full" and kind == "up") or (mode == "simplified" and kind == "set"):
                    commit_action(press, state, i)
            elif kind == "finish":
                finished = True
                if not state["ended"] or not state["started"] or state["failed"]:
                    return fail("spoiled, unfinished or held print")
            else:
                return fail("unknown control or reset")
        if not finished or payload.get("completed") is not True:
            return fail("strip not certified")
        if not finite(payload.get("final_t_ms")) or payload["final_t_ms"] != last:
            return fail("final timestamp mismatch")
        return dict(graded=True, passed=True, score=100, feedback="Independent letterpress replay passed.",
                    spoil_ms=round(state["spoil_ms"], 6), elapsed_ms=state["t_ms"], clean_ms=state["clean_ms"])
    except (KeyError, ValueError, TypeError, OverflowError, IndexError) as exc:
        return fail("invalid letterpress transcript: " + str(exc))
