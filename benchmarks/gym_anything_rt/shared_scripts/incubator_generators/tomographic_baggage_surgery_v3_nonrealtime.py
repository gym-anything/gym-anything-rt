"""Source-derived moving, layered 3D baggage extraction. No mode-specific world."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "tomographic_baggage_surgery_v3_nonrealtime"
DONOR_MECHANIC_ID = "tomographic_baggage_surgery_v3"
REVISION = "moving-aperture-tomographic-survey-1"
# Keep the mechanically forked V2 trajectories exactly as they were in V3.
# The repair changes the observation surface, not seeded geometry or physics.
TRAJECTORY_REVISION = "moving-aperture-extraction-1"
PROFILES = {
    1: dict(gates=2, aperture=1.10, amplitude=1.55, span_ms=5200, speed=.55, gain=28, damping=10),
    2: dict(gates=2, aperture=.96, amplitude=1.60, span_ms=4700, speed=.58, gain=26, damping=10),
    3: dict(gates=3, aperture=.88, amplitude=1.65, span_ms=4400, speed=.60, gain=24, damping=9),
    4: dict(gates=4, aperture=.80, amplitude=1.70, span_ms=4100, speed=.62, gain=22, damping=8),
    5: dict(gates=4, aperture=.72, amplitude=1.75, span_ms=3600, speed=.64, gain=20, damping=8),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    if level not in PROFILES:
        raise ValueError("difficulty must be 1..5")
    p = dict(PROFILES[level])
    p.update((condition or {}).get("difficulty_parameters") or {})
    if p != PROFILES[level]:
        raise ValueError("unsupported extraction profile")
    if condition is None:
        condition = dict(difficulty=level, interaction="full", real_time="live", difficulty_parameters=p)
    if condition["interaction"] not in ("full", "simplified"):
        raise ValueError("interaction must be full or simplified")
    # The counterpart changes only the clock contract; corresponding seeds
    # retain the evaluated V3 donor's scene and trajectory.
    rng = random.Random(hashlib.sha256(f"{seed}|{DONOR_MECHANIC_ID}|{level}|{TRAJECTORY_REVISION}".encode()).digest())
    # Independent non-repeating knots. Smoothstep is C1 and has finite velocity.
    # The next 1.2 s of each motion is also drawn as a dashed forecast, so a
    # random knot never creates an unobservable imminent trajectory change.
    def motion(amplitude, span):
        return dict(span_ms=span, knots=[[round(rng.uniform(-amplitude, amplitude), 6) for _ in range(2)] for _ in range(60)])
    gates = [dict(id=i+1, x=2.0+i*6.0/max(1, p["gates"]-1), radius=p["aperture"], half=.09,
                  motion=motion(p["amplitude"], p["span_ms"]+rng.randrange(-200,201))) for i in range(p["gates"])]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, revision=REVISION,
        task_id=task["id"], challenge_id=hashlib.sha256(f"{seed}|{level}|{REVISION}".encode()).hexdigest()[:16],
        control_condition=condition, parameters=p, gates=gates,
        target=dict(x=9.5, radius=.25, motion=motion(1.15, p["span_ms"]+550)),
        physics=dict(body_shape="axial_cylinder", dt_ms=10, action_step_ms=100, entry_x=.4, target_x=9.5, bounds=3.0, tool_radius=.14,
                     load_radius=.27, max_speed=3.0, max_accel=12.0, grip_distance=.40,
                     max_ms=120000, forecast_ms=1200, tail_ms=240),
        views=dict(width=500, height=280, origin=[35,140], depth_scale=44, transverse_scale=36,
                   slice_origin=[150,140], slice_scale=38,
                   pad_origin=[150,140], pad_scale=38, pad_extent=2.55, handle_radius=16),
        sensing=dict(initially_scanned=[], discovery="numbered_transverse_slice",
                     retained="live_aperture_track", input_source="slice_button"),
        prompt="Scan each numbered layer to reveal its aperture. Guide the probe through the moving layers, grip the pink relic at the back, then withdraw. Waiting preserves the current geometry; each deliberate probe control advances one fixed simulation step. Contact ends the attempt.",
        asset_manifest="shared_runtime/assets/provenance/tomographic_baggage_surgery_v3_v0.json",
        generator=dict(name=REVISION, variant_count=10**18, variant_count_kind="seeded continuous non-repeating aperture and relic trajectories"),
        render_boundary="Unscanned layers show only their depth and opaque extent, not their aperture centers, holes or trajectories. Selecting a numbered transverse slice reveals that layer's actual aperture and retains its live track in both projections. Waiting between controls does not advance the simulation. Dashed trails show the next 1.2 seconds; solid fading trails show the last 0.24 seconds. Geometry necessarily exists in browser render state; privileged page state is forbidden to evaluated agents.")
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
