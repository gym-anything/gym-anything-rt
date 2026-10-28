"""Original synthetic living-fibre proofreading game; no source data/assets."""
from __future__ import annotations

import copy
import hashlib
import random

MECHANIC_ID = "branch_repair_v3_nonrealtime"
REVISION = "living-fibre-7"
ACTION_STEP_MS = 2000
# Keep the geometry distribution fixed while improving visible correspondence.
LAYOUT_REVISION = "living-fibre-4"
ANCHORS = ["XCOG-252", "XCOG-249", "XCOG-253"]
PROFILES = {
    1: dict(front_count=1, candidate_count=2, drift_px=46, span_ms=3200, port_radius=20, signal_speed=14, lead_px=190, depth_gap=58),
    2: dict(front_count=1, candidate_count=3, drift_px=46, span_ms=2800, port_radius=18, signal_speed=15, lead_px=180, depth_gap=50),
    3: dict(front_count=2, candidate_count=3, drift_px=48, span_ms=2400, port_radius=17, signal_speed=16, lead_px=175, depth_gap=44),
    4: dict(front_count=2, candidate_count=4, drift_px=50, span_ms=2100, port_radius=15, signal_speed=17, lead_px=165, depth_gap=36),
    5: dict(front_count=3, candidate_count=4, drift_px=52, span_ms=1800, port_radius=14, signal_speed=18, lead_px=155, depth_gap=30),
}
for _profile in PROFILES.values():
    _profile["outlet_flex_px"] = 24


def generate(task, seed):
    # Explicit legacy fixtures preserve the old contracts and their replays.
    # Authoritative/current tasks do not select a legacy revision.
    revision = task.get("world_revision", REVISION)
    if revision not in ("living-fibre-6", REVISION):
        raise ValueError("unsupported branch repair revision")
    condition = copy.deepcopy(task.get("_control_condition") or task.get("metadata", {}).get("control_condition"))
    level = int((condition or {}).get("difficulty", 5))
    interaction = (condition or {}).get("interaction", "full")
    if level not in PROFILES or interaction not in ("full", "simplified"):
        raise ValueError("unsupported branch repair condition")
    params = dict(PROFILES[level])
    params.update((condition or {}).get("difficulty_parameters") or {})
    if params != PROFILES[level]:
        raise ValueError("use one complete declared branch repair profile")
    # A renamed task must retain the frozen V2 world for the same seed.
    rng = random.Random(hashlib.sha256(f"{seed}|branch_repair_v2|{LAYOUT_REVISION}".encode()).digest())
    count = params["front_count"]
    ys = {1: [245], 2: [155, 345], 3: [88, 245, 402]}[count]
    zs = {1: [0], 2: [-40, 40], 3: [-60, 0, 60]}[count]
    stations, fronts, answers = [], [], {}
    for lane, (y, z) in enumerate(zip(ys, zs)):
        fronts.append(dict(id=f"axon-{lane}", y=y, z=z, speed_seed=rng.getrandbits(32), start_x=28 + rng.randint(0, 12)))
        for column, x in enumerate((165, 465, 765)):
            token = hashlib.sha256(f"{seed}|{lane}|{column}".encode()).hexdigest()[:10]
            station_id = "lesion-" + token
            n = params["candidate_count"]
            spacing = 34 if n == 4 else 46 if n == 3 else 64
            offsets = [(j - (n-1)/2)*spacing for j in range(n)]
            chosen = rng.randrange(n)
            # Anatomical continuity is visible in XZ: only one outlet remains
            # in the incoming fibre's depth plane. XY alone is ambiguous.
            candidates = []
            for j, offset in enumerate(offsets):
                depth = z if j == chosen else z + (1 if j % 2 else -1) * (params["depth_gap"] + 8*j)
                candidates.append(dict(id="port-" + hashlib.sha256(f"{token}|{j}".encode()).hexdigest()[:8],
                                       p=[x+76, y+offset, depth], glyph=j+1))
            source = dict(id="port-" + hashlib.sha256(f"{token}|in".encode()).hexdigest()[:8],
                          p=[x, y, z], glyph=0)
            wrong = rng.choice([c for j, c in enumerate(candidates) if j != chosen])
            answers[station_id] = dict(join=candidates[chosen]["id"], cut=wrong["id"])
            rng.shuffle(candidates)
            stations.append(dict(id=station_id, lane=lane, column=column, material_x=x,
                                 source=source, candidates=candidates, bridge_to=wrong["id"],
                                 motion_seed=rng.getrandbits(32)))
    rng.shuffle(stations)
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, revision=revision,
                  task_id=task["id"], challenge_id=hashlib.sha256(f"{seed}|{revision}|d{level}".encode()).hexdigest()[:16],
                  prompt="Keep every signal in its own fibre. Split false bridges and stitch the matching continuation as the damage front arrives.",
                  interaction=interaction, parameters=params, stage=dict(width=960, height=490),
                  fronts=fronts, stations=stations, finish_x=925, tick_ms=10, max_ms=100000,
                  single_attempt=True, submit_label="CERTIFY SIGNAL DELIVERY",
                  generator=dict(name=revision, layout_revision=LAYOUT_REVISION, source_anchors=ANCHORS),
                  asset_manifest="environments/branch_repair_v3_nonrealtime_env/counterpart-provenance.json",
                  render_boundary="Synthetic 3D geometry and reproducible motion are public for rendering; screenshot-only play must not inspect them. No source connectome data is shipped.")
    if revision == REVISION:
        public["inspection_model"] = "linked-local-sections-v1"
        public["prompt"] = "Use SECTION LENS on XY ports to inspect the local bridge path and depth continuity. Keep every signal in its own fibre: cut false bridges and stitch the matching moving continuation. Inspected sections stay visible; inspection is safe before BEGIN and does not pause live flow."
        public["motion_model"] = dict(name="reflecting-fibre-recoil", phase_step=4,
            tissue_speed="2 * amplitude / span_ms", flex_speed="48 / (span_ms + 317)",
            stitch_effect="A completed correct stitch reverses horizontal tissue drift, without a position jump.",
            sealing_effect="Each cut-and-joined lesion increases its signal's base rate by ten percent. Material progress uses displayed 0.00001-unit resolution.",
            observation="Source arrows show tissue headings; outlet arrows show flex headings. Inspected sections retain faint scars marking future false bridges. Flow meters show material progress and rate.",
            timing_model="action-stepped-live",
            action_step_ms=ACTION_STEP_MS,
            idle_behavior="No task time, material progress, opening, crossing, or failure occurs while no input is being processed.",
            held_input_behavior="A held pointer is evaluated at its native release; cutting/arming waits for completion, while a correct stitch or deliberate no-hit probe advances one full fixed 2,000 ms step, including a terminal endpoint reached during that step.")
    if condition:
        public["control_condition"] = condition
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), answers=answers, level=level)
    return public, truth
