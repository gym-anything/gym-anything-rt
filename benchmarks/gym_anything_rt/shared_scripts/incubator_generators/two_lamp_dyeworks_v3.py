"""Original continuous dye plant, derived from the three selected color controls.

No assets, UI, or code from the surveyed games are shipped. The stock parcels
are reproducible for replay, but only a short moving section is rendered.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random

MECHANIC_ID = "two_lamp_dyeworks_v3"
REVISION = "flow-spectrum-v3-stock-sampling"
# Preserve the mechanically forked V2 world's draws and physical profiles.
SEED_REVISION = "flow-spectrum-v1"
PREVIEW_MS = 3500
POLICY_REVISION = "approved-retry-policy-20261006"


def _episode_failure(task_id):
    # This task-local module already ships in native and static grader bundles.
    # No runtime dependency on the audit-only retry_policy.json is introduced.
    path = Path(__file__).resolve().parents[2] / "shared_runtime/server/incubator_graders/two_lamp_dyeworks_v3.py"
    spec = importlib.util.spec_from_file_location("dyeworks_retry_history", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.first_failure(module.read_episode_history(task_id), task_id)
PROFILES = {
    1: dict(pigment_count=2, vat_count=1, transition_ms=8500, mixing_ms=850,
            pipe_ms=200, valve_speed=0.65, coupling=0.0, tolerance=5.0, waste_mm=80),
    2: dict(pigment_count=3, vat_count=1, transition_ms=8000, mixing_ms=1000,
            pipe_ms=300, valve_speed=0.60, coupling=0.025, tolerance=4.6, waste_mm=70),
    3: dict(pigment_count=4, vat_count=1, transition_ms=7500, mixing_ms=1200,
            pipe_ms=400, valve_speed=0.55, coupling=0.045, tolerance=4.2, waste_mm=60),
    4: dict(pigment_count=3, vat_count=2, transition_ms=7000, mixing_ms=1350,
            pipe_ms=500, valve_speed=0.50, coupling=0.060, tolerance=3.8, waste_mm=55),
    5: dict(pigment_count=4, vat_count=2, transition_ms=6500, mixing_ms=1500,
            pipe_ms=600, valve_speed=0.45, coupling=0.075, tolerance=3.4, waste_mm=50),
}
# Nine-band Beer-Lambert approximation. This is a dye simulation, not a claim
# of accurate colorimetry for real industrial pigments or illuminants.
SPECTRUM = {
    "base": [.88, .90, .92, .94, .95, .95, .94, .92, .90],
    "strength": 2.0,
    "cie": [[.134, .336, .095, .004, .594, 1.056, .642, .165, .011],
            [.004, .038, .208, .793, .995, .631, .265, .061, .004],
            [.646, 1.772, 1.287, .272, .004, .001, 0, 0, 0]],
    "lamps": {"north": [.76, .90, 1.04, 1.08, 1.05, 1.0, .94, .89, .84],
              "sodium": [.05, .07, .11, .25, .92, 1.40, .78, .18, .05]},
    "casts": {"north": [1, 1, .98], "sodium": [1.05, .78, .42]},
}
PIGMENTS = [
    dict(id="woad", name="WOAD", color="#59b6d8", absorption=[.08,.05,.04,.12,.28,.55,.82,.92,1.0]),
    dict(id="madder", name="MADDER", color="#ed7a7e", absorption=[.78,.90,.88,.65,.38,.16,.08,.07,.08]),
    dict(id="weld", name="WELD", color="#e7c25e", absorption=[1,.90,.70,.25,.08,.04,.03,.03,.04]),
    dict(id="logwood", name="LOGWOOD", color="#bd9be1", absorption=[.30,.18,.10,.46,.86,.84,.48,.25,.18]),
]


def colors(density, pigments, spectrum=SPECTRUM):
    reflectance = [spectrum["base"][b] * math.exp(-spectrum["strength"] *
                   sum(d * p["absorption"][b] for d, p in zip(density, pigments)))
                   for b in range(9)]
    result = {}
    for lamp, power in spectrum["lamps"].items():
        white = [sum(power[b] * row[b] for b in range(9)) for row in spectrum["cie"]]
        xyz = [sum(power[b] * reflectance[b] * row[b] for b in range(9)) / white[1]
               for row in spectrum["cie"]]
        def f(x):
            return x ** (1/3) if x > (6/29)**3 else x/(3*(6/29)**2) + 4/29
        fx, fy, fz = [f(xyz[i] / (white[i]/white[1])) for i in range(3)]
        lab = [116*fy-16, 500*(fx-fy), 200*(fy-fz)]
        x, y, z = .95047 * (fx**3 if fx > 6/29 else 3*(6/29)**2*(fx-4/29)), \
                  fy**3 if fy > 6/29 else 3*(6/29)**2*(fy-4/29), \
                  1.08883 * (fz**3 if fz > 6/29 else 3*(6/29)**2*(fz-4/29))
        linear = [3.2406*x-1.5372*y-.4986*z, -.9689*x+1.8758*y+.0415*z, .0557*x-.204*y+1.057*z]
        rgb = []
        for v, cast in zip(linear, spectrum["casts"][lamp]):
            v = max(0, min(1, v))
            s = 12.92*v if v <= .0031308 else 1.055*v**(1/2.4)-.055
            rgb.append(math.floor(255*max(0,min(1,s*cast))+.5))
        result[lamp] = dict(lab=lab, rgb=rgb)
    return result


def _stock(rng, transition):
    initial = round(rng.uniform(.92, 1.08), 6)
    nodes = [dict(t_ms=0, strength=initial), dict(t_ms=1800, strength=initial)]
    extremes = [rng.uniform(.52,.62), rng.uniform(1.48,1.58)]
    rng.shuffle(extremes)
    values = extremes + [rng.uniform(.52,1.58) for _ in range(10)]
    t = 1800
    for strength in values:
        t += rng.randrange(int(transition*.85), int(transition*1.15), 50)
        nodes.append(dict(t_ms=t, strength=round(strength,6)))
        t += rng.randrange(3500, 5001, 50)
        nodes.append(dict(t_ms=t, strength=round(strength,6)))
    return nodes


def generate(task, seed):
    condition = task.get("_control_condition")
    level = (condition or {}).get("difficulty", 5)
    mode = (condition or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("unsupported dyeworks condition")
    parameters = copy.deepcopy(PROFILES[level])
    supplied = (condition or {}).get("difficulty_parameters", {})
    if supplied and supplied != parameters:
        raise ValueError("dyeworks requires one of the five declared physical profiles")
    # A reproducible order can be run with independent supply deliveries.
    # Ordinary seeds retain their original stream byte-for-byte. Factored
    # seeds use "order-id::delivery-id", or "order-id::batch-id::delivery-id"
    # to share the three already loaded parcels. Parts are arbitrary seed text.
    # This is generator configuration, never a player control or restart.
    order_seed, separator, delivery_seed = str(seed).partition("::")
    batch_seed, batch_separator, independent_delivery = delivery_seed.partition("::")
    if batch_separator:
        if not batch_seed or not independent_delivery:
            raise ValueError("shared-lot seed needs order, batch and delivery")
        delivery_seed=independent_delivery
    if separator and (not order_seed or not delivery_seed):
        raise ValueError("factored seed needs both order and delivery")
    rng = random.Random(hashlib.sha256(f"{MECHANIC_ID}|{SEED_REVISION}|{order_seed}|d{level}".encode()).digest())
    supply_rng = (random.Random(hashlib.sha256(
        f"{MECHANIC_ID}|{SEED_REVISION}|supply|{delivery_seed}|d{level}".encode()).digest())
        if separator else rng)
    pigments = copy.deepcopy(PIGMENTS[:parameters["pigment_count"]])
    rng.shuffle(pigments)
    stock = {p["id"]: _stock(supply_rng, parameters["transition_ms"]) for p in pigments}
    if separator:
        # The order's premixed starting batch is common; only the incoming
        # deliveries differ. This separates autonomous supply evolution from
        # static targets or initial-stock differences in matched instances.
        batch_rng=random.Random(hashlib.sha256(
            f"{MECHANIC_ID}|{SEED_REVISION}|batch|{order_seed}|d{level}".encode()).digest())
        for p in pigments:
            initial=round(batch_rng.uniform(.92,1.08),6)
            stock[p['id']][0]['strength']=stock[p['id']][1]['strength']=initial
        if batch_separator:
            # A batch identifier fixes the already loaded starting parcels.
            # Independently seeded later deliveries then fork continuously.
            # This also permits causal comparisons with identical visible
            # goals, stocks and physical history before the fork.
            lot_rng=random.Random(hashlib.sha256(
                f"{MECHANIC_ID}|{SEED_REVISION}|lot|{batch_seed}|d{level}".encode()).digest())
            for p in pigments:
                common=_stock(lot_rng,parameters['transition_ms'])[:8]
                common[0]['strength']=common[1]['strength']=stock[p['id']][0]['strength']
                nodes=stock[p['id']]
                shift=common[-1]['t_ms']-nodes[7]['t_ms']
                stock[p['id']]=common+[dict(node,t_ms=node['t_ms']+shift) for node in nodes[8:]]
    targets = [[round(rng.uniform(.29,.49), 6) for _ in pigments] for _ in range(parameters["vat_count"])]
    vats = [dict(id=f"vat-{i}", name=f"BATH {'AB'[i]}", target=colors(target, pigments),
                 fiber_spectrum=[base*math.exp(-SPECTRUM['strength']*sum(
                     d*p['absorption'][band] for d,p in zip(target,pigments)))
                     for band,base in enumerate(SPECTRUM['base'])])
            for i, target in enumerate(targets)]
    physics = dict(tick_ms=50, supply_scale=1.8, leader_ms=6000, run_ms=42000,
                   cloth_speed_mm_s=10, preview_ms=PREVIEW_MS, **parameters)
    task_id = task.get("id", f"{MECHANIC_ID}_seed_0001@0.1")
    episode_failure, history_error = _episode_failure(task_id)
    world = dict(revision=REVISION, pigments=pigments, stock=stock, vats=vats,
                 inspection=dict(kind="stock_spot_test", anonymous_lots=True,
                                 persistent_reveal=True, sample_density=.25),
                 physics=physics, spectrum=copy.deepcopy(SPECTRUM), stage=dict(width=1120,height=500))
    digest = hashlib.sha256(json.dumps(world,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    public = dict(benchmark="gym_anything_rt", mechanic_id=MECHANIC_ID, task_id=task_id,
                  challenge_id=hashlib.sha256(f"{task_id}|{seed}|{digest}".encode()).hexdigest()[:18],
                  world_digest=digest, single_attempt=True, **world,
                  retry_policy_revision=POLICY_REVISION,
                  episode_failed=bool(episode_failure),
                  episode_failure=episode_failure, episode_history_error=history_error,
                  prompt="Spot-test the anonymous inlet lots to learn their dye responses, then match moving cloth under BOTH lamps. Finish each roll within its spoil allowance; maximize usable yield as dye strength changes.",
                  submit_label="CERTIFY ROLLS",
                  asset_manifest="shared_runtime/assets/provenance/two_lamp_dyeworks_v3_v0.json",
                  generator=dict(name=REVISION, variant_count=None,
                                 variant_count_kind="not enumerated: varied target spectra and independently seeded nonperiodic stock parcels"))
    if condition:
        public["control_condition"] = copy.deepcopy(condition)
    truth = copy.deepcopy(public)
    truth.update(seed=str(seed), target_density=targets,
                 oracle="benchmarks.gym_anything_rt.solvers.two_lamp_dyeworks_v3:solve")
    return public, truth
