"""Original CaptchaWare close_popups idea, rebuilt as a moving layered desktop."""
from __future__ import annotations

import copy
import hashlib
import json
import random

MECHANIC_ID = "popup_exorcist_v3"
REVISION = "drifting-seals-inspection-v5"
SOURCE_ANCHORS = ["CaptchaWare/close_popups"]
BASELINE_LEVEL = 4
PROFILES = {
    1: dict(haunted_count=3, trusted_count=1, seal_size=64, span_ms=4000, travel_x=100, travel_y=65, rail_travel=30, overlap=0),
    2: dict(haunted_count=4, trusted_count=2, seal_size=60, span_ms=4000, travel_x=105, travel_y=65, rail_travel=35, overlap=35),
    3: dict(haunted_count=5, trusted_count=2, seal_size=56, span_ms=4000, travel_x=110, travel_y=70, rail_travel=40, overlap=60),
    4: dict(haunted_count=7, trusted_count=3, seal_size=52, span_ms=4000, travel_x=115, travel_y=75, rail_travel=50, overlap=80),
    5: dict(haunted_count=9, trusted_count=3, seal_size=48, span_ms=4000, travel_x=120, travel_y=75, rail_travel=60, overlap=100),
}


def _fits_paused_budget(world):
    """Generate only worlds with a 600-ms endpoint solution inside 90 steps.

    This checks geometry during construction, never adds a gameplay rule or
    changes grading. The independent grader and rendered native executions
    remain separate checks.
    """
    panes = sorted(world["windows"], key=lambda w: -w["z"])
    closed = set()
    radius = world["parameters"]["seal_size"] / 2
    rail_travel = world["parameters"]["rail_travel"]
    for ms in range(600, 54001, 600):
        positions = {}
        for w in panes:
            u = (ms + w["phase_ms"]) / w["span_ms"]
            i = min(len(w["knots"]) - 2, int(u))
            f = min(1, u - i)
            blend = f * f * (3 - 2 * f)
            positions[w["id"]] = [a + (b-a)*blend for a,b in zip(w["knots"][i],w["knots"][i+1])]
        def owner(point):
            for w in panes:
                if w["id"] in closed:
                    continue
                x,y,rail = positions[w["id"]]
                if x <= point[0] <= x+w["w"] and y <= point[1] <= y+w["h"]:
                    sx = x+w["w"]-radius-10-rail_travel+rail
                    sy = y+radius+8
                    if not w["trusted"] and abs(point[0]-sx)<=radius and abs(point[1]-sy)<=radius:
                        return w["id"]
                    return None
            return None
        chosen = None
        for w in panes:
            if w["trusted"] or w["id"] in closed:
                continue
            x,y,rail = positions[w["id"]]
            sx,sy = x+w["w"]-radius-10-rail_travel+rail,y+radius+8
            for dx,dy in ((0,0),(-10,0),(10,0),(0,10),(0,-10)):
                if all(owner([sx+dx+a,sy+dy+b])==w["id"] for a,b in ((0,0),(7,0),(-7,0),(0,7),(0,-7))):
                    chosen = w["id"]
                    break
            if chosen:
                break
        if chosen:
            closed.add(chosen)
        if len(closed)==world["parameters"]["haunted_count"]:
            return True
    return False


def generate(task, seed, _attempt=0):
    condition = task.get("_control_condition") or (task.get("metadata") or {}).get("control_condition")
    level = (condition or {}).get("difficulty", BASELINE_LEVEL)
    mode = (condition or {}).get("interaction", "full")
    if type(level) is not int or level not in PROFILES or mode not in ("full", "simplified"):
        raise ValueError("invalid Popup Exorcist V3 condition")
    params = dict(PROFILES[level])
    supplied = (condition or {}).get("difficulty_parameters") or {}
    if supplied and supplied != params:
        raise ValueError("difficulty parameters differ from the selected profile")
    # Keep accepted V3 geometry stable, and deterministically resample only
    # worlds whose physical occlusion would consume the frozen paused budget.
    salt = f"{seed}|{MECHANIC_ID}|drifting-seals-v3"
    if _attempt:
        salt += f"|budget-resample-{_attempt}"
    rng = random.Random(hashlib.sha256(salt.encode()).digest())
    count = params["haunted_count"] + params["trusted_count"]
    trusted = set(rng.sample(range(count), params["trusted_count"]))
    windows = []
    # Four wide columns and three rows: the overlap parameter compresses this
    # arrangement without changing the minimum readable seal size.
    slots = [(x, y) for y in (42, 168, 280) for x in (145, 348, 551, 754)]
    rng.shuffle(slots)
    for i in range(count):
        x, y = slots[i]
        x = 445 + (x - 445) * (1 - params["overlap"] / 450)
        y = 164 + (y - 164) * (1 - params["overlap"] / 650)
        w, h = rng.randint(215, 240), rng.randint(122, 138)
        tx, ty = params["travel_x"], params["travel_y"]
        base_x = min(1030 - w - tx, max(10 + tx, x - w / 2))
        base_y = min(452 - h - ty, max(8 + ty, y - h / 2))
        span = params["span_ms"] + rng.randint(-350, 350)
        knots = [[round(base_x + rng.uniform(-tx, tx), 4),
                  round(base_y + rng.uniform(-ty, ty), 4),
                  round(rng.uniform(-params["rail_travel"], params["rail_travel"]), 4)]
                 for _ in range(150000 // span + 3)]
        windows.append(dict(id=f"pane-{rng.getrandbits(40):010x}", z=i,
                            trusted=i in trusted, w=w, h=h,
                            span_ms=span, knots=knots,
                            phase_ms=rng.randint(0, span - 1),
                            color=rng.choice(("#a789f5", "#5ed6bf", "#f2b969", "#df82ba"))))
    # One real foreground service covers a haunt at opening. Both panes share
    # their first continuous drift, then follow independent seeded paths around
    # the same center. The covered seal cannot be clicked from the opening
    # geometry or the 1.2-second preview. There is no activation timer: the
    # ordinary solid-pane hit test determines every later exposure.
    haunt = next(w for w in windows if not w["trusted"])
    service = next(w for w in reversed(windows) if w["trusted"])
    haunt["w"], haunt["h"] = 215, 122
    service["w"], service["h"], service["z"] = 240, 138, count
    tx, ty = params["travel_x"], params["travel_y"]
    bx = min(1030 - 240 - tx, max(10 + tx, haunt["knots"][0][0] - 12))
    by = min(452 - 138 - ty, max(8 + ty, haunt["knots"][0][1] - 8))
    common = [[round(bx + rng.uniform(-tx, tx), 4),
               round(by + rng.uniform(-ty, ty), 4)] for _ in range(2)]
    for pane, ox, oy in ((service, 0, 0), (haunt, 12, 8)):
        pane["span_ms"], pane["phase_ms"] = params["span_ms"], 0
        pane["knots"] = [[round(bx + ox + rng.uniform(-tx, tx), 4),
                           round(by + oy + rng.uniform(-ty, ty), 4),
                           round(rng.uniform(-params["rail_travel"], params["rail_travel"]), 4)]
                          for _ in range(150000 // params["span_ms"] + 3)]
        for j in range(2):
            pane["knots"][j][:2] = [common[j][0] + ox, common[j][1] + oy]
    world = dict(revision=REVISION, width=1040, height=460, parameters=params,
                 windows=windows, play_time_ms=120000, miss_limit=4,
                 preview_ms=1200, trace_ms=600)
    if not _fits_paused_budget(world):
        if _attempt >= 31:
            raise ValueError("could not generate a reachable desktop inside the frozen paused budget")
        return generate(task, seed, _attempt + 1)
    identity = dict(mechanic_id=MECHANIC_ID, task_id=task["id"],
                    challenge_id=hashlib.sha256(f"{seed}|{task['id']}|{json.dumps(condition,sort_keys=True)}|{REVISION}".encode()).hexdigest()[:20],
                    control_condition=copy.deepcopy(condition))
    public = dict(**identity, world=copy.deepcopy(world),
                  title="Popup Exorcist V3", prompt="Inspect the sealed notices. Close haunted windows; preserve protected services.",
                  source_anchors=SOURCE_ANCHORS,
                  asset_manifest="shared_runtime/assets/provenance/popup_exorcist_v3_v0.json",
                  generator=dict(name=REVISION, variant_count=10**18))
    truth = dict(**identity, world=copy.deepcopy(world), seed=str(seed))
    return public, truth
