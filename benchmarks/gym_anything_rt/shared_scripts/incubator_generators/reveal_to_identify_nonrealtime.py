"""Action-triggered non-real-time counterpart of the evaluated V2 scanner world."""
from __future__ import annotations

import copy
import hashlib
import math
import random
import re

MECHANIC_ID = "reveal_to_identify_nonrealtime"
DONOR_MECHANIC_ID = "reveal_to_identify_v2"
REVISION = "moving-darkroom-7-nonrealtime-1"
ACTION_STEP_TICKS = 12
PROFILES = {
    1: dict(carriers=3, targets=2, speed=72, current_memory_ms=2400, lens_radius=116,
            carrier_radius=34, pulse_lag_ms=650, scanner_acceleration=1800,
            scanner_speed=380, scanner_damping=12, similar_decoys=0),
    2: dict(carriers=4, targets=2, speed=86, current_memory_ms=2200, lens_radius=106,
            carrier_radius=33, pulse_lag_ms=700, scanner_acceleration=1550,
            scanner_speed=340, scanner_damping=11, similar_decoys=0),
    3: dict(carriers=5, targets=2, speed=100, current_memory_ms=2000, lens_radius=96,
            carrier_radius=32, pulse_lag_ms=750, scanner_acceleration=1300,
            scanner_speed=310, scanner_damping=10, similar_decoys=1),
    4: dict(carriers=6, targets=2, speed=112, current_memory_ms=1800, lens_radius=86,
            carrier_radius=31, pulse_lag_ms=800, scanner_acceleration=1100,
            scanner_speed=285, scanner_damping=9.5, similar_decoys=2),
    5: dict(carriers=8, targets=3, speed=124, current_memory_ms=1600, lens_radius=78,
            carrier_radius=30, pulse_lag_ms=850, scanner_acceleration=950,
            scanner_speed=260, scanner_damping=9, similar_decoys=3),
}


def generate(task, seed):
    # The optional flow component is a general procedural seed factor. It varies
    # the initial *visible* flow state while preserving the layout/glyph factor.
    # No seed, hash or private schedule is consulted after initialization.
    match = re.search(r"#flow=(-?\d+)(?=[:#]|$)", str(seed))
    flow_variant = int(match.group(1)) if match else 0
    valve_match = re.search(r"#valves=(\d+)(?=[:#]|$)", str(seed))
    valve_rank = int(valve_match.group(1)) if valve_match else int.from_bytes(hashlib.sha256((str(seed)+"|valves").encode()).digest(), "big") % 16
    if not 0 <= valve_rank < 16:
        raise ValueError("invalid valve cartridge")
    layout_seed = re.sub(r"#(?:flow=-?\d+|valves=\d+)(?=[:#]|$)", "", str(seed))
    # Keep corresponding seeds on the donor's layout/glyph stream.  The
    # counterpart changes only timing, not the generated puzzle identity.
    rng = random.Random(hashlib.sha256(f"{layout_seed}|{DONOR_MECHANIC_ID}|moving-darkroom-1".encode()).digest())
    supplied = copy.deepcopy(task.get("_control_condition"))
    level = int((supplied or {}).get("difficulty", 5))
    mode = (supplied or {}).get("interaction", "full")
    if level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("invalid scanner condition")
    parameters = copy.deepcopy(PROFILES[level])
    overrides = (supplied or {}).get("difficulty_parameters", {})
    if overrides and overrides != parameters:
        raise ValueError("scanner profiles must match the declared, tested control contract")
    condition = supplied or dict(difficulty=level, interaction=mode, real_time="live",
                                difficulty_parameters=copy.deepcopy(parameters))
    families = list(range(6)); rng.shuffle(families)
    wanted = [dict(family=families[i], crown=rng.choice((0, 1)), eye=rng.choice((0, 1)))
              for i in range(parameters["targets"])]
    glyphs = copy.deepcopy(wanted)
    for i in range(parameters["similar_decoys"]):
        glyph = copy.deepcopy(wanted[i % len(wanted)])
        glyph["crown"] = 1 - glyph["crown"]
        glyphs.append(glyph)
    while len(glyphs) < parameters["carriers"]:
        glyph = dict(family=rng.randrange(6), crown=rng.randrange(2), eye=rng.randrange(2))
        if glyph not in glyphs:
            glyphs.append(glyph)
    rng.shuffle(glyphs)
    cells = [(x, y) for y in (105, 250, 395) for x in (140, 350, 560, 770)]
    rng.shuffle(cells)
    items = []
    for index, glyph in enumerate(glyphs):
        x, y = cells[index]
        angle = rng.uniform(0, math.tau)
        vx=round(math.cos(angle) * parameters["speed"], 3)
        vy=round(math.sin(angle) * parameters["speed"], 3)
        items.append(dict(id=f"carrier-{index}", plate=index+1, glyph=glyph,
                          x=round(x + rng.uniform(-20, 20), 3),
                          y=round(y + rng.uniform(-18, 18), 3),
                          vx=vx, vy=vy, cx=vx, cy=vy))
        rng.getrandbits(32)  # preserve the earlier layout sequence, discard key
    initial_flow = [round(rng.uniform(-16, 16), 6), round(rng.uniform(-20, 20), 6),
                    round(rng.uniform(18, 38), 6)]
    initial_flow[0] = round(initial_flow[0] + flow_variant / 1000000, 6)
    if not -40 <= initial_flow[0] <= 40:
        raise ValueError("flow seed component exceeds physical range")
    world = dict(width=900, height=500, dt_ms=10, duration_ms=150000,
                 pulse_radius=6, scanner_spring=36, scanner_handle_radius=24,
                 pulse_cooldown_ms=1000, current_response=1.5,
                 current_limit_multiplier=1.8, state_precision=1000,
                 flow_precision=1000000, flow_initial=initial_flow,
                 flow_dt=.005, flow_sigma=10, flow_rho=28, flow_beta=8/3,
                 valve_program=[(valve_rank >> (2*i)) & 3 for i in range(parameters["targets"]-1)],
                 valve_presets=[[10,16,20],[-10,-16,20],[16,-12,30],[-16,12,30]],
                 motion_model="observable-lorenz-flow-v1",
                 timing_model="action-triggered-fixed-step-v1",
                 action_step_ticks=ACTION_STEP_TICKS,
                 pulse_settle_ticks=math.ceil(parameters["pulse_lag_ms"] / 10), **parameters)
    task_id = task["id"]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  revision=REVISION, task_id=task_id,
                  challenge_id=hashlib.sha256(f"{seed}|{task_id}|d{level}|{REVISION}".encode()).hexdigest()[:16],
                  control_condition=condition, world=world, carriers=items, wanted=wanted,
                  prompt="Optically certify every numbered plate, then intercept only the requested shapes.",
                  submit_label="CERTIFY", asset_manifest="shared_runtime/assets/provenance/reveal_to_identify_v2_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18,
                                 variant_count_kind="seeded positions, silhouettes and initial observable nonlinear flow states"),
                  render_boundary="Current physical state, initial calibration, and every realized valve switch are visible at their simulation precision. Pulses arm only after every glyph is optically certified. A wanted tag removes a load and switches to one of four visible flow presets; the future cartridge choices remain hidden. Scanner actions advance one fixed simulation step and a pulse action completes its fixed flight; waiting alone changes no state. Old motion observations contain no cartridge information beyond the visible initial calibration and switch record. Page-state access is outside the screenshot-only surface.")
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    truth["wanted_ids"] = [item["id"] for item in items if item["glyph"] in wanted]
    assert len(truth["wanted_ids"]) == parameters["targets"]
    return public, truth
