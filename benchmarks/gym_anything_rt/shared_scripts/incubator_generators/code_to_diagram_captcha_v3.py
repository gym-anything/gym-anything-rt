"""Live control-flow execution with read-only discovery of concealed dispatches."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import math
import os
from pathlib import Path
import random

MECHANIC_ID = "code_to_diagram_captcha_v3"
REVISION = "inspected-dispatch-v7"
# Keep the frozen V2 world's seed law, geometry, flags and motion tapes.
SOURCE_RANDOMNESS_ID = "code_to_diagram_captcha_v2"
# This timing revision preserves the v5 motion/program law and seed pairing.
WORLD_REVISION = "previewed-weld-tools-v5"
FORK_PREFIX = "flow-fork1|"
PROFILES = {
    1: dict(stream_count=1, gate_count=1, feedback=False, contact_radius=38,
            motion_span_ms=5000, amplitude_x=56, amplitude_y=32, charge_ms=900, buffer_ms=18000),
    2: dict(stream_count=2, gate_count=1, feedback=False, contact_radius=36,
            motion_span_ms=4400, amplitude_x=58, amplitude_y=34, charge_ms=950, buffer_ms=17000),
    3: dict(stream_count=2, gate_count=2, feedback=False, contact_radius=32,
            motion_span_ms=3600, amplitude_x=60, amplitude_y=36, charge_ms=1000, buffer_ms=16000),
    4: dict(stream_count=3, gate_count=2, feedback=True, contact_radius=29,
            motion_span_ms=3100, amplitude_x=62, amplitude_y=38, charge_ms=1100, buffer_ms=15000),
    5: dict(stream_count=3, gate_count=3, feedback=True, contact_radius=26,
            motion_span_ms=2500, amplitude_x=64, amplitude_y=40, charge_ms=1200, buffer_ms=14000),
}


def episode_status(task_id):
    # The environment's runtime hook exports the existing state-directory
    # setting before launching the unchanged server. Static generation remains
    # deterministic and filesystem-independent when that setting is absent.
    if not os.environ.get("GYM_ANYTHING_RT_STATE_DIR"):
        return dict(episode_failed=False, episode_history_error="")
    path = Path(__file__).resolve().parents[2] / "shared_runtime/server/incubator_graders/code_to_diagram_captcha_v3.py"
    spec = importlib.util.spec_from_file_location("flow_v2_episode_history", path)
    if spec is None or spec.loader is None:
        return dict(episode_failed=False, episode_history_error="Episode failure history is unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failure, error = module.read_episode_failure(task_id)
    return dict(episode_failed=bool(failure), episode_history_error=error or "")


def generate(task, seed):
    # Common-random-number seeds support reproducible control counterfactuals.
    # They redraw ONE waypoint from the identical uniform law. No coordinates,
    # success state, timing rule, profile change or solver exception is accepted.
    # Flat seeds retain their world geometry and program across timing revisions.
    seed_text = str(seed)
    fork = None
    world_seed = seed_text
    if seed_text.startswith(FORK_PREFIX):
        fields = seed_text.split("|")
        if len(fields)!=5 or not fields[1] or not fields[2] or not fields[4]:
            raise ValueError("motion-fork seed requires base, node, knot and nonce")
        _,world_seed,node_id,knot_text,nonce = fields
        try:
            knot_index = int(knot_text)
        except ValueError as exc:
            raise ValueError("motion-fork knot must be an integer") from exc
        fork = dict(node_id=node_id,knot_index=knot_index,nonce=nonce)
    condition = copy.deepcopy(task.get("_control_condition"))
    level = (condition or {}).get("difficulty", 5)
    if type(level) is not int or level not in PROFILES:
        raise ValueError("difficulty must be 1 through 5")
    params = copy.deepcopy((condition or {}).get("difficulty_parameters", PROFILES[level]))
    if params != PROFILES[level]:
        raise ValueError("profile does not match the versioned flow contract")
    if condition is None:
        condition = dict(difficulty=5, interaction="full", real_time="live", difficulty_parameters=params)
    if condition.get("interaction") not in ("full", "simplified"):
        raise ValueError("invalid interaction mode")
    # Mode and task name do not affect randomness or world geometry.
    rng = random.Random(hashlib.sha256(f"{SOURCE_RANDOMNESS_ID}|{WORLD_REVISION}|{world_seed}|{level}".encode()).digest())
    gates = params["gate_count"]
    names = rng.sample(["FERN", "KITE", "MOTH", "LIME", "REED", "WAVE", "COVE", "LARK", "MICA"], 3*gates)
    nodes = [dict(id="BOOT", kind="entry", next=names[0], operation=None)]
    for index in range(gates):
        gate, a, b = names[3*index:3*index+3]
        following = names[3*index+3] if index+1 < gates else "OUT"
        predicate = rng.choice(("sun", "diamond", "equal")) if level >= 3 else rng.choice(("sun", "diamond"))
        nodes.extend([
            dict(id=gate, kind="branch", predicate=predicate, yes=a, no=b, operation=None),
            dict(id=a, kind="operation", next=following, operation=rng.choice(("sun", "diamond")), feedback=index==gates-1 and params["feedback"]),
            dict(id=b, kind="operation", next=following, operation=rng.choice(("sun", "diamond")), feedback=index==gates-1 and params["feedback"]),
        ])
    nodes.append(dict(id="OUT", kind="exit", operation=None))
    cells = [(132+210*x, 96+148*y) for y in range(3) for x in range(4)]
    rng.shuffle(cells)
    for node, center in zip(nodes, cells):
        node.update(center=list(center), phase_ms=rng.randrange(params["motion_span_ms"]),
                    motion_knots=[[rng.uniform(-1,1),rng.uniform(-1,1)]
                                  for _ in range(math.ceil(180000/params["motion_span_ms"])+3)])
    streams = [dict(id=f"P{i+1}", color=["#f6bd60", "#75dfc9", "#c8a4ff"][i],
                    sun=bool(rng.randrange(2)), diamond=bool(rng.randrange(2)),
                    repeat=int(params["feedback"]), home=[42, 98+148*i])
               for i in range(params["stream_count"])]
    # Opposing first branches produce concurrent, different spatial demands.
    if len(streams)>1:
        first = nodes[1]["predicate"]
        if first == "equal":
            streams[0].update(sun=True, diamond=True)
            streams[1].update(sun=True, diamond=False)
        else:
            streams[0][first], streams[1][first] = True, False
    if fork is not None:
        node = next((n for n in nodes if n["id"]==fork["node_id"]),None)
        if node is None or not 0<=fork["knot_index"]<len(node["motion_knots"]):
            raise ValueError("motion-fork draw is outside the generated tape")
        draw = random.Random(hashlib.sha256(f"{SOURCE_RANDOMNESS_ID}|motion-fork|{seed_text}|{level}".encode()).digest())
        node["motion_knots"][fork["knot_index"]] = [draw.uniform(-1,1),draw.uniform(-1,1)]
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task["id"], challenge_id=hashlib.sha256(f"{seed}|{level}|{REVISION}".encode()).hexdigest()[:16],
                  revision=REVISION, control_condition=condition, nodes=nodes, streams=streams,
                  physics=dict(field=[880, 470], tick_ms=10, tip_radius=14,
                               tip_speed=680, tip_acceleration=3600, spring=72,
                               damping=17, process_ms=1000, charge_decay=2,
                               weld_radius=18, weld_tip_radius=6,
                               weld_offset=params["contact_radius"]+2,
                               session_ms=180000, **params),
                  entry_id="BOOT", first_gate=names[0], single_attempt=True,
                  prompt="Inspect each block's dispatch to discover its directed targets, then heat and weld the next moving contact. Inspection is read-only and leaves discovered routes visible; live contacts keep moving.",
                  submit_label="CERTIFY EXECUTION",
                  asset_manifest="shared_runtime/assets/provenance/code_to_diagram_captcha_v3_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18,
                                 variant_count_kind="Independent seeded placement, branch operations, execution flags and nonperiodic contact motion."),
                  render_boundary="Players initially see predicates and flag operations, but dispatch destinations and outgoing graph lines are concealed until that block's INSPECT DISPATCH control is used. Discovered routes stay visible. Current flags, probe tips, charge/armed state, velocity arrows and current/next motion segments remain visible as in V2. Later motion is not previewed. The bundled runtime contains route data for local replay; this is a screenshot-only information boundary, not protection against source or page-state inspection.")
    public.update(episode_status(task["id"]))
    truth = copy.deepcopy(public)
    truth["seed"] = str(seed)
    return public, truth
