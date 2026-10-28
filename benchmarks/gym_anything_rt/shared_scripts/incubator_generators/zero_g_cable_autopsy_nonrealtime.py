"""Source-derived cable dissection; seeded worlds do not depend on input mode."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random

MECHANIC_ID = "zero_g_cable_autopsy_nonrealtime"
DONOR_MECHANIC_ID = "zero_g_cable_autopsy_v2"
REVISION = "moving-isolation-flexible-cable-v1"
SOURCE_ANCHORS = ["research/collection/sources/captcha-rpg/gordian-knot",
                  "https://www.playstation.com/en-gb/games/tentacular/"]
PROFILES = {
    1: dict(node_count=11, collar_count=1, port_radius=66, port_amplitude=75,
            port_span_ms=6500, collar_radius=32, collar_span_ms=10000,
            collar_amplitude=.35, flow_acceleration=0, contact_count=0),
    2: dict(node_count=13, collar_count=1, port_radius=56, port_amplitude=90,
            port_span_ms=9000, collar_radius=29, collar_span_ms=4800,
            collar_amplitude=.18, flow_acceleration=8, contact_count=1),
    3: dict(node_count=15, collar_count=2, port_radius=47, port_amplitude=100,
            port_span_ms=7600, collar_radius=26, collar_span_ms=3600,
            collar_amplitude=.10, flow_acceleration=12, contact_count=1),
    4: dict(node_count=17, collar_count=2, port_radius=39, port_amplitude=105,
            port_span_ms=6400, collar_radius=23, collar_span_ms=3000,
            collar_amplitude=.13, flow_acceleration=20, contact_count=2),
    5: dict(node_count=19, collar_count=3, port_radius=32, port_amplitude=110,
            port_span_ms=5200, collar_radius=20, collar_span_ms=2600,
            collar_amplitude=.095, flow_acceleration=28, contact_count=2),
}


def generate(task, seed):
    condition = copy.deepcopy(task.get("_control_condition") or
                              task.get("metadata", {}).get("control_condition") or {})
    level = int(condition.get("difficulty", 5))
    if level not in PROFILES:
        raise ValueError("Cable difficulty must be 1..5")
    mode = condition.get("interaction", "full")
    if mode not in ("full", "simplified"):
        raise ValueError("Cable interaction must be full or simplified")
    p = {**PROFILES[level], **condition.get("difficulty_parameters", {})}
    if p != PROFILES[level]:
        raise ValueError("Unsupported cable profile; revise the explicit profile contract")
    condition.update(difficulty=level, interaction=mode, real_time="live",
                     difficulty_parameters=copy.deepcopy(p))
    # Keep corresponding seeds identical to the evaluated donor.  The
    # namespace changes, but the generated puzzle contract does not.
    rng = random.Random(hashlib.sha256(f"{DONOR_MECHANIC_ID}|{REVISION}|{seed}|{level}".encode()).digest())
    n = p["node_count"]
    nodes = [[100 + 660 * i / (n - 1), 210 + 100 * math.sin(math.pi * i / (n - 1))]
             for i in range(n)]
    rest = [math.dist(a, b) for a, b in zip(nodes, nodes[1:])]
    bend = [math.dist(nodes[i], nodes[i + 2]) for i in range(n - 2)]
    centers = {1: [.5], 2: [.30, .70], 3: [.24, .50, .76]}[p["collar_count"]]
    collars = [dict(id=i, center=u, seed=rng.getrandbits(32),
                    span_ms=p["collar_span_ms"] + i * 373,
                    amplitude=p["collar_amplitude"], radius=p["collar_radius"])
               for i, u in enumerate(centers)]
    world = dict(parameters=p, width=860, height=470, tick_ms=20, nodes=nodes,
                 rest_lengths=rest, bend_lengths=bend,
                 ports=[dict(x=x, center=225, seed=rng.getrandbits(32),
                             span_ms=p["port_span_ms"] + i * 719,
                             amplitude=p["port_amplitude"], radius=p["port_radius"])
                        for i, x in enumerate((100, 760))],
                 collars=collars, flow_seed=rng.getrandbits(32),
                 peg=dict(x=430, y=267, radius=30),
                 contacts=[dict(x=315 + rng.uniform(-25, 25), y=65, radius=22),
                           dict(x=550 + rng.uniform(-25, 25), y=432, radius=22)][:p["contact_count"]],
                 grip_radius=12, cable_radius=4, servo_speed=180,
                 servo_acceleration=600, servo_gain=7, servo_drag=5,
                 rail_bounds=[70, 390], constraint_iterations=10,
                 damping=.991, clamp_stiffness=.28, max_stretch=1.15,
                 discharge_rate=.18, recharge_rate=.40, cut_energy_limit=.08,
                 exposed_energy=.40,
                 max_time_ms=120000, trail_window_ms=800)
    digest = hashlib.sha256(json.dumps(world, sort_keys=True).encode()).hexdigest()[:20]
    prompt = ("Isolate the live cable with both moving green ports, then slice every copper collar. "
              "Keep the cable off red contacts. The wire bends around the insulating peg; "
              "cutting a collar removes its stiff brace. Both grippers must fit inside their ports "
              "while the visible capacitor energy drains to green and at stroke release. "
              "Removing a brace exposes another charged section, so isolate it again before "
              "the next stroke. Cutting bare wire, a red contact, or an "
              "unisolated cable ends the attempt. Each deliberate gripper or knife action "
              "advances one fixed control slice; waiting between actions leaves the visible "
              "state unchanged.")
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID,
                  task_id=task["id"], challenge_id=digest, revision=REVISION,
                  world=world, prompt=prompt, control_condition=condition,
                  source_anchors=SOURCE_ANCHORS,
                  asset_manifest="shared_runtime/assets/provenance/zero_g_cable_autopsy_v2_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18,
                                 variant_count_kind="independent continuous geometry and seeded nonrepeating drift"))
    truth = copy.deepcopy(public)
    truth.update(seed=seed, oracle="tools/incubator_solvers/zero_g_cable_autopsy_v2.py")
    return public, truth
