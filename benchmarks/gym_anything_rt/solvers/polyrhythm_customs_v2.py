"""Causal geometry controller for diagnostic wiring, with transport supplied by caller.

read() is explicitly privileged current-state observation, not screenshot vision.
send() must be the frozen downstream HTTP API for native parity evidence. The
headless test adapter does not establish that parity. No future seed or motion
function is consulted by choose().
"""
from __future__ import annotations

MECHANIC_ID = "polyrhythm_customs_v2"


def choose(snapshot, half_width, circumference, forecast_ms=0):
    lanes = {lane["id"]: lane for lane in snapshot["lanes"]}
    notes = {note["id"]: note for note in snapshot["notes"]}
    cleared = set(snapshot["cleared"])
    held = snapshot["held"]
    actions = []
    seconds = forecast_ms / 1000
    for lane_id, lane in lanes.items():
        center = lane["gate"] + seconds * lane["gate_speed"]
        movement = seconds * lane["speed"]
        if lane_id in held:
            h = held[lane_id]
            note = notes[h["note"]]
            error = note["phase"] + movement - note["length"] - h["cycle"] * circumference - center
            if h["kind"] == "tap" or abs(error) <= .45 * half_width:
                actions.append(("up", lane_id))
        else:
            for note in notes.values():
                if note["lane"] != lane_id or note["id"] in cleared:
                    continue
                error = (note["phase"] + movement) % circumference - center
                if abs(error) <= .45 * half_width:
                    actions.append(("down", lane_id))
                    break
    return actions


SNAPSHOT_EXPRESSION = """() => {
    const m = polyrhythmCustomsV2Model;
    const t = m.active && !m.terminal ? Math.max(0,performance.now()-m.startedAt) : m.sim.ms;
    return {...m.sim.snapshot(t), terminal:m.terminal, verdict:m.verdict,
      mode:m.mode, half_width:m.state.parameters.band_half_width, circumference:m.sim.c};
}"""


def solve(ui, *, budget=500, cadence_ms=100, begin_point=None, pad_points=None):
    """ui.read/send/wait protocol; current geometry is privileged planning.

    All outcome-affecting operations are ordinary mouse/key action dictionaries.
    Coordinates are measured before the run from visible controls. No DOM focus,
    mutation, reload, game-method calls, or submitted synthetic successes occur.
    """
    if type(budget) is not int or budget < 1:
        raise ValueError("Diagnostic budget must be a positive integer")
    if begin_point is None:
        begin_point = ui.point("#pc-begin")
    if pad_points is None:
        pad_points = {lane: ui.point(f"#pc-pad-{lane}") for lane in "asdf"
                      if ui.exists(f"#pc-pad-{lane}")}
    ui.send({"mouse": {"left_click": begin_point}})
    observations = 0
    action_requests = 1
    while observations + action_requests < budget:
        snapshot = ui.read(SNAPSHOT_EXPRESSION)
        observations += 1
        if snapshot["terminal"]:
            return dict(terminal=True, verdict=snapshot["verdict"],
                        observations=observations, action_requests=action_requests,
                        task_time_ms=snapshot["t_ms"], budget=budget)
        decisions = choose(snapshot, snapshot["half_width"], snapshot["circumference"])
        for kind, lane in decisions:
            if observations + action_requests >= budget:
                raise AssertionError(f"Diagnostic solver exhausted {budget} observations + input requests")
            if snapshot["mode"] == "full":
                action = {"keyboard": {"keys_down" if kind == "down" else "keys_up": [lane]}}
            else:
                action = {"mouse": {"left_click": pad_points[lane]}}
            ui.send(action)
            action_requests += 1
        ui.wait(cadence_ms / 1000)
    raise AssertionError(f"Diagnostic solver exhausted {budget} observations + input requests")
