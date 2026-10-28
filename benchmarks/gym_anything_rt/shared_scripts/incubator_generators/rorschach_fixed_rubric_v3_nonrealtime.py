"""Living ink press. Randomness depends on seed and difficulty, never interface."""
from __future__ import annotations

import copy
import hashlib
import math
import random

MECHANIC_ID = "rorschach_fixed_rubric_v3_nonrealtime"
SEED_NAMESPACE = "rorschach_fixed_rubric_v3"
REVISION = "living-ink-press-5-inspection"
FLOW_REVISION = "living-ink-press-4"
ACTION_WINDOW_MS = 240
PARAMETERS = {
    1: dict(landmarks=2, drift=95, spread=0, twist=0, flex=0, knot_ms=2200, tolerance=44, spring=18, damping=8),
    2: dict(landmarks=2, drift=110, spread=34, twist=0, flex=0, knot_ms=4200, tolerance=40, spring=20, damping=8),
    3: dict(landmarks=3, drift=120, spread=40, twist=.25, flex=0, knot_ms=3800, tolerance=36, spring=24, damping=8.5),
    4: dict(landmarks=3, drift=130, spread=48, twist=.34, flex=35, knot_ms=3400, tolerance=32, spring=26, damping=9),
    5: dict(landmarks=3, drift=140, spread=60, twist=.44, flex=60, knot_ms=3000, tolerance=28, spring=28, damping=9.5),
}
RULE = ("Inspect the ink centres with the pointer to uncover their registration marks. "
        "Each sheet assigns the apertures differently; uncovered marks stay visible. "
        "Keep every ink centre inside its marked registration aperture to develop the butterfly print. "
        "The apertures have inertia. Uncovered ink fills the spill gutter and the print fades. "
        "The dotted fibres show the next 1.2 seconds of flow; fading fibres show the recent past. "
        "Begin flow when ready. A full gutter, expired sheet, or incomplete certification ends the episode.")
UI_ONLY = ("Use only screenshots and visible controls in the task webpage. Do not use code, scripts, automation, "
           "Developer Tools, console, debugger, inspector, network, source, DOM or page-state inspection, terminal, "
           "shell, Python, address-bar or URL/query edits, reload or navigation, browser extensions, external "
           "applications, hidden state, or unrelated tabs.")


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition"))
    level = (condition or {}).get("difficulty", 5)
    if type(level) is not int or level not in PARAMETERS:
        raise ValueError("ink difficulty must be an integer from 1 through 5")
    params = copy.deepcopy(PARAMETERS[level])
    if condition is not None:
        if (condition.get("interaction") not in ("full", "simplified") or
                condition.get("difficulty_parameters") != params):
            raise ValueError("ink control condition does not match its complete difficulty profile")
    # Preserve the mechanically forked V2 flow exactly. The concealed sheet
    # correspondence uses a separate random stream and changes no motion draws.
    # Keep corresponding V3 seeds on the donor's puzzle stream. The
    # counterpart identity is used only for public task/challenge identity.
    rng = random.Random(hashlib.sha256(f"{seed}|{SEED_NAMESPACE}|{FLOW_REVISION}|{level}".encode()).digest())
    channels = {}
    for name, amplitude in (("x", params["drift"]), ("y", params["drift"]*.42),
                            ("spread", params["spread"]), ("twist", params["twist"]),
                            ("flex", params["flex"])):
        direction = rng.choice((-1, 1))
        def value():
            # The ink pump crosses the sheet rather than lingering around a
            # parkable mean. Unequal spans, magnitudes and other channels still
            # change the route and delayed action across instances.
            return direction*rng.uniform(.8*amplitude, amplitude) if name == "x" else rng.uniform(-amplitude, amplitude)
        knots = [[0, value()]]
        while knots[-1][0] < 58000:
            # Independent unequal spans avoid a shared repeatable turning schedule.
            direction *= -1
            knots.append([knots[-1][0] + rng.randint(round(params["knot_ms"]*.8), round(params["knot_ms"]*1.25)), value()])
        channels[name] = knots
    registration = list(range(params["landmarks"]))
    random.Random(hashlib.sha256(f"{seed}|ink-registration|{level}".encode()).digest()).shuffle(registration)
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, revision=REVISION,
        task_id=task["id"], challenge_id=hashlib.sha256(f"{seed}|{MECHANIC_ID}|{REVISION}|{level}".encode()).hexdigest()[:16],
        prompt=RULE, stage=dict(width=920, height=440), parameters=params, channels=channels,
        labels=[f"APERTURE {i+1}" for i in range(params["landmarks"])],
        contact_labels=["LEFT WING", "RIGHT WING", "SPINE"][:params["landmarks"]],
        registration=registration, inspection_radius=24,
        ink_radius=14, development_seconds=9, fade_rate=1.5, spill_limit=14,
        duration_ms=55000, dt_ms=10, action_window_ms=ACTION_WINDOW_MS,
        speed_limit=230, acceleration_limit=1100,
        forecast_ms=1200, trail_ms=800,
        asset_manifest="shared_runtime/assets/provenance/rorschach_fixed_rubric_v3_v0.json",
        generator=dict(name=REVISION, variant_count=10**24))
    if condition is not None:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
