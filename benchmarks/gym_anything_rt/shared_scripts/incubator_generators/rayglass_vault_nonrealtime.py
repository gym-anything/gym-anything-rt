"""Original Black Box derived optical routing and continuous beam control.

Generation is independent of interaction and execution mode. The public route
table is needed by the opaque cabinet's local probe UI, not rendered wholesale.
This is a screenshot-only boundary, not a browser-internals secrecy claim.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
from pathlib import Path

MECHANIC_ID = "rayglass_vault_nonrealtime"
REVISION = "moving-receivers-3"
SEED_NAMESPACE = "rayglass_vault_v2"
CONTROLS = Path(__file__).resolve().parents[2] / "environments/rayglass_vault_nonrealtime_env/controls.json"
COLORS = ["#efbc6b", "#86ddce", "#cda7f0"]


def ray(n, beads, port):
    """Black Box rules, implemented here rather than importing an older game."""
    side, k = divmod(port, n)
    x, y, dx, dy = ((k, -1, 0, 1), (n, k, -1, 0),
                    (n-1-k, n, 0, -1), (-1, n-1-k, 1, 0))[side]
    balls = set(beads)
    def has(a, b):
        return 0 <= a < n and 0 <= b < n and b*n+a in balls
    if has(x+dx, y+dy):
        return "H"
    if has(x+dx-dy, y+dy+dx) or has(x+dx+dy, y+dy-dx):
        return "R"
    x, y = x+dx, y+dy
    visited = set()
    while (x, y, dx, dy) not in visited:
        visited.add((x, y, dx, dy))
        if has(x+dx, y+dy):
            return "H"
        left, right = has(x+dx+dy, y+dy-dx), has(x+dx-dy, y+dy+dx)
        if left and right:
            dx, dy = -dx, -dy
        elif left:
            dx, dy = -dy, dx
        elif right:
            dx, dy = dy, -dx
        else:
            x, y = x+dx, y+dy
            if not (0 <= x < n and 0 <= y < n):
                output = x if y < 0 else n+y if x >= n else 3*n-1-x if y >= n else 4*n-1-y
                return "R" if output == port else output
    return "R"


def cabinet_geometry(n, channels):
    step = 240/n
    ports = []
    for p in range(4*n):
        side, k = divmod(p, n)
        ports.append(dict(x=[50+(k+.5)*step, 316, 290-(k+.5)*step, 24][side],
                          y=[24, 50+(k+.5)*step, 316, 290-(k+.5)*step][side], size=32))
    return dict(width=340, height=430, grid=dict(x=50, y=50, width=240, size=n),
                seal_key=dict(x=170, y=240, width=104, height=38),
                ports=ports, sockets=[dict(x=170+(i-(channels-1)/2)*104, y=374, width=94, height=60)
                                     for i in range(channels)])


def generate(task, seed):
    controls = json.loads(CONTROLS.read_text())
    condition = task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition")
    level = controls["baseline"]["difficulty"] if condition is None else condition.get("difficulty")
    if type(level) is not int or not 1 <= level <= 5:
        raise ValueError("Rayglass Vault V2 difficulty must be 1 through 5")
    parameters = copy.deepcopy(controls["difficulty"][str(level)]["parameters"])
    if condition is not None:
        if condition.get("interaction") not in ("full", "simplified"):
            raise ValueError("invalid Rayglass interaction")
        if condition.get("difficulty_parameters") != parameters:
            raise ValueError("Rayglass profile differs from controls.json")
    profile_key = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    # Keep the counterpart's renamed mechanic identity out of puzzle
    # generation so corresponding seeds retain the donor's optical content.
    digest = hashlib.sha256(f"{SEED_NAMESPACE}|{REVISION}|{seed}|d{level}|{profile_key}".encode()).hexdigest()
    # A seed may name an optical family followed by a motion variant. This
    # permits paired, reachable histories with identical cable preparation;
    # ordinary seed strings still vary both optics and motion.
    family = str(seed).split("|", 1)[0]
    optical_digest = hashlib.sha256(f"{SEED_NAMESPACE}|{REVISION}|{family}|d{level}|{profile_key}".encode()).hexdigest()
    rng = random.Random(int(optical_digest, 16))
    motion_rng = random.Random(int(digest, 16))
    n, count, channels = parameters["size"], parameters["bead_count"], parameters["channels"]
    for _ in range(1000):
        beads = sorted(rng.sample(range(n*n), count))
        responses = [ray(n, beads, p) for p in range(4*n)]
        pairs = [(p, q) for p, q in enumerate(responses) if type(q) is int and p < q]
        if len(pairs) >= channels:
            break
    else:
        raise ValueError("could not generate enough distinct transmissive routes")
    chosen = rng.sample(pairs, channels)
    optical_channels = []
    for i, pair in enumerate(chosen):
        exit_port = rng.choice(pair)
        optical_channels.append(dict(id=i, color=COLORS[i], label=["AMBER", "JADE", "LILAC"][i],
            exit_port=exit_port, motion_seed=motion_rng.getrandbits(32),
            initial_y=round(rng.uniform(-44, 44), 6), direction=rng.choice([-1, 1])))
    shared = dict(mechanic_id=MECHANIC_ID, task_id=task.get("id", "rayglass_vault_nonrealtime_seed_0001@0.1"),
                  challenge_id=digest[:16], physics_revision=REVISION, parameters=parameters,
                  cabinet=cabinet_geometry(n, channels), channels=optical_channels,
                  optics=dict(width=680, height=490, mirror_x=112, receiver_x=484, rail_half_span=60,
                              mirror_limit_deg=8.5, beam_width=4, receiver_width=36,
                              seal_key_radius=4, trim_left=192, trim_right=428,
                              row_centers=[80+160*i for i in range(channels)]),
        requirements=dict(tick_ms=10, action_step_ticks=4, max_ticks=30000, active_limit_ticks=9000,
                                    charge_leak=4.0, cooling_rate=1.5, max_events=12000),
                  source_anchors=["PLOG-001"])
    if condition is not None:
        shared["control_condition"] = copy.deepcopy(condition)
    public = dict(shared, benchmark="gym_anything_rt", sensor_responses=responses,
                  prompt="Find the optical routes. Charge every moving receiver together, then place the seal key inside AMBER's moving opening.",
                  asset_manifest="shared_runtime/assets/provenance/rayglass_vault_v2_v0.json",
                  generator=dict(name=MECHANIC_ID+"_"+REVISION, variant_count=10**18),
                  render_boundary="Probe responses and seeded motion are loaded for local rendering. Only probes, current geometry and recent trails are visible. No browser-state secrecy is claimed.")
    truth = dict(copy.deepcopy(shared), beads=beads, seed=str(seed))
    return public, truth
