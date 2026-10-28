from __future__ import annotations

import copy
import math
from typing import Any


MECHANIC_ID = "anthill_front"
VALID_ACTIONS = {"GATHER", "SCOUT", "DIG", "RAISE", "MARCH"}
VALID_TARGETS = {"seed", "front", "brood", "north", "south", "enemy"}


def initial_state(world: dict[str, Any]) -> dict[str, Any]:
    worker_ids = [str(unit["id"]) for unit in world.get("workers") or []]
    return {
        "tick": 0,
        "seeds": int(world["initial_seeds"]),
        "brood_ready": bool(world["brood_ready"]),
        "brood_progress": int(world["dig_work"]) if world["brood_ready"] else 0,
        "queen_hp": int(world["home_queen"]["hp"]),
        "enemy_queen_hp": int(world["enemy_queen"]["hp"]),
        "workers": worker_ids,
        "soldiers": [],
        "orders": {unit_id: "idle" for unit_id in worker_ids},
        "order_started": {unit_id: 0 for unit_id in worker_ids},
        "scout_id": None,
        "scout_started": None,
        "opening_revealed": not bool(world["hidden_opening"]),
        "production": [],
        "next_soldier": 1,
        "assault_at": {},
        "attacked": [],
        "rival_outposts_ready": [],
        "defense_commitments": {},
        "successful_intercepts": [],
        "resolved_waves": [],
        "units_lost": 0,
        "terminal": False,
        "won": False,
    }


def _living(state: dict[str, Any]) -> set[str]:
    return set(state["workers"]) | set(state["soldiers"])


def intercept_lane(raid: dict[str, Any], tick: int) -> str:
    """Return the branch indicated by the formation's visible vertical motion."""
    phase = (tick - int(raid["response_open_tick"]) + int(raid.get("motion_phase_offset_ticks", 0))) * math.tau / 36.0
    seeded_sign = 1.0 if str(raid["lane"]) == "south" else -1.0
    return "south" if seeded_sign * math.cos(phase) >= 0 else "north"


def _step(state: dict[str, Any], world: dict[str, Any]) -> None:
    if state["terminal"]:
        return
    state["tick"] += 1
    tick = state["tick"]

    if not state["opening_revealed"] and state["scout_started"] is not None:
        scout_id = state["scout_id"]
        if scout_id not in state["workers"] or state["orders"].get(scout_id) != "scout":
            state["scout_id"] = None
            state["scout_started"] = None
        elif tick - int(state["scout_started"]) >= int(world["scout_ticks"]):
            state["opening_revealed"] = True
            state["orders"][scout_id] = "gather"
            state["order_started"][scout_id] = tick
            state["scout_id"] = None
            state["scout_started"] = None

    if not state["brood_ready"]:
        diggers = [unit_id for unit_id in state["workers"] if state["orders"].get(unit_id) == "dig"]
        if len(diggers) == int(world["dig_workers"]):
            state["brood_progress"] += len(diggers)
        if state["brood_progress"] >= int(world["dig_work"]):
            state["brood_progress"] = int(world["dig_work"])
            state["brood_ready"] = True
            for unit_id in diggers:
                state["orders"][unit_id] = "gather"
                state["order_started"][unit_id] = tick

    cycle = int(world["gather_cycle_ticks"])
    for unit_id in state["workers"]:
        if state["orders"].get(unit_id) != "gather":
            continue
        elapsed = tick - int(state["order_started"].get(unit_id, tick))
        if elapsed > 0 and elapsed % cycle == 0:
            state["seeds"] += 1

    ready = [item for item in state["production"] if int(item["ready_tick"]) <= tick]
    state["production"] = [item for item in state["production"] if int(item["ready_tick"]) > tick]
    for _item in ready:
        soldier_id = f"S{state['next_soldier']}"
        state["next_soldier"] += 1
        state["soldiers"].append(soldier_id)
        state["orders"][soldier_id] = "rally"
        state["order_started"][soldier_id] = tick

    for raid in world["raids"]:
        wave = int(raid["wave"])
        if wave not in state["rival_outposts_ready"] and tick >= int(raid["expand_complete_tick"]):
            state["rival_outposts_ready"].append(wave)

    for raid in world["raids"]:
        wave = int(raid["wave"])
        if wave in state["resolved_waves"] or tick < int(raid["impact_tick"]):
            continue
        if wave not in state["rival_outposts_ready"]:
            raise ValueError("rival raid reached impact before its outpost was completed")
        lane = str(raid["lane"])
        commitment = state["defense_commitments"].get(wave)
        defenders = []
        if commitment and commitment["correct"]:
            defenders = sorted(
                unit_id
                for unit_id in commitment["unit_ids"]
                if unit_id in state["soldiers"] and state["orders"].get(unit_id) == commitment["lane"]
            )
        count = int(raid["count"])
        stopped = min(len(defenders), count)
        losses = min(stopped, (count + 2) // 3)
        for unit_id in defenders[:losses]:
            state["soldiers"].remove(unit_id)
            state["orders"].pop(unit_id, None)
            state["order_started"].pop(unit_id, None)
            state["assault_at"].pop(unit_id, None)
            state["units_lost"] += 1
        breach = count - stopped
        state["queen_hp"] -= breach
        if stopped == count:
            state["successful_intercepts"].append(wave)
        state["resolved_waves"].append(wave)
        if state["queen_hp"] <= 0:
            state["queen_hp"] = 0
            state["terminal"] = True
            state["won"] = False
            return

    all_raids_cleared = len(state["resolved_waves"]) == len(world["raids"])
    for unit_id in sorted(list(state["soldiers"])):
        due = state["assault_at"].get(unit_id)
        if due is None or unit_id in state["attacked"] or tick < int(due):
            continue
        state["attacked"].append(unit_id)
        state["enemy_queen_hp"] -= 1
        if state["enemy_queen_hp"] <= 0:
            state["enemy_queen_hp"] = 0
            state["terminal"] = True
            state["won"] = len(state["successful_intercepts"]) == len(world["raids"])
            return

    if tick >= int(world["max_ticks"]):
        state["terminal"] = True
        state["won"] = False


def advance(state: dict[str, Any], world: dict[str, Any], target_tick: int) -> None:
    if target_tick < int(state["tick"]):
        raise ValueError("event ticks move backwards")
    if target_tick > int(world["max_ticks"]):
        raise ValueError("event tick exceeds the match clock")
    while int(state["tick"]) < target_tick:
        _step(state, world)


def apply_action(state: dict[str, Any], world: dict[str, Any], action: str, unit_ids: list[str], target: str) -> None:
    if state["terminal"]:
        raise ValueError("command issued after the match ended")
    if action not in VALID_ACTIONS or target not in VALID_TARGETS:
        raise ValueError("unsupported colony command")
    if len(unit_ids) != len(set(unit_ids)) or any(unit_id not in _living(state) for unit_id in unit_ids):
        raise ValueError("command selects missing or duplicate ants")
    workers = set(state["workers"])
    soldiers = set(state["soldiers"])
    tick = int(state["tick"])

    def cancel_selected_scout() -> None:
        scout_id = state.get("scout_id")
        if scout_id is not None and scout_id in unit_ids and state["orders"].get(scout_id) == "scout":
            state["scout_id"] = None
            state["scout_started"] = None

    if action == "GATHER":
        if target != "seed" or not unit_ids or any(unit_id not in workers for unit_id in unit_ids):
            raise ValueError("gather requires selected workers and the seed pile")
        cancel_selected_scout()
        for unit_id in unit_ids:
            state["orders"][unit_id] = "gather"
            state["order_started"][unit_id] = tick
    elif action == "SCOUT":
        if target != "front" or len(unit_ids) != 1 or unit_ids[0] not in workers:
            raise ValueError("scout requires one selected worker and the front")
        if state["opening_revealed"]:
            raise ValueError("the listening front already has contact")
        if state["scout_id"] is not None:
            raise ValueError("a scout is already deployed")
        unit_id = unit_ids[0]
        state["orders"][unit_id] = "scout"
        state["order_started"][unit_id] = tick
        state["scout_id"] = unit_id
        state["scout_started"] = tick
    elif action == "DIG":
        needed = int(world["dig_workers"])
        if target != "brood" or needed <= 0 or len(unit_ids) != needed or any(unit_id not in workers for unit_id in unit_ids):
            raise ValueError("dig requires exactly the configured worker crew at the brood chamber")
        cancel_selected_scout()
        for unit_id in state["workers"]:
            if state["orders"].get(unit_id) == "dig" and unit_id not in unit_ids:
                state["orders"][unit_id] = "gather"
                state["order_started"][unit_id] = tick
        for unit_id in unit_ids:
            state["orders"][unit_id] = "dig"
            state["order_started"][unit_id] = tick
    elif action == "RAISE":
        cost = int(world["soldier_cost"])
        if target != "brood" or unit_ids or not state["brood_ready"] or state["seeds"] < cost:
            raise ValueError("soldier production is not currently available")
        state["seeds"] -= cost
        state["production"].append({"ready_tick": tick + int(world["production_ticks"])})
    elif action == "MARCH":
        if target not in {"north", "south", "enemy"} or not unit_ids or any(unit_id not in soldiers for unit_id in unit_ids):
            raise ValueError("march requires selected soldiers and a tunnel or rival queen")
        all_raids_cleared = len(state["resolved_waves"]) == len(world["raids"])
        if target == "enemy":
            if not all_raids_cleared:
                raise ValueError("the rival queen cannot be assaulted before every raid is cleared")
        else:
            if not state["opening_revealed"]:
                raise ValueError("the listening front has not acquired contact")
            active = [
                raid
                for raid in world["raids"]
                if int(raid["wave"]) not in state["resolved_waves"]
                and int(raid["wave"]) not in state["defense_commitments"]
                and int(raid["response_open_tick"]) <= tick <= int(raid["response_deadline_tick"])
            ]
            if not active:
                raise ValueError("no uncommitted raid is inside the visible intercept band")
            raid = min(active, key=lambda item: int(item["wave"]))
            reserved = {
                reserved_id
                for wave, commitment in state["defense_commitments"].items()
                if int(wave) not in state["resolved_waves"]
                for reserved_id in commitment["unit_ids"]
            }
            if any(unit_id in reserved for unit_id in unit_ids):
                raise ValueError("a soldier cannot be committed to two unresolved interceptions")
            state["defense_commitments"][int(raid["wave"])] = {
                "tick": tick,
                "lane": target,
                "unit_ids": list(unit_ids),
                "correct": target == intercept_lane(raid, tick),
            }
        for unit_id in unit_ids:
            state["orders"][unit_id] = target
            state["order_started"][unit_id] = tick
            if target == "enemy":
                state["assault_at"][unit_id] = tick + int(world["assault_travel_ticks"])
            else:
                state["assault_at"].pop(unit_id, None)


def summary(state: dict[str, Any], world: dict[str, Any]) -> dict[str, Any]:
    return {
        "tick": int(state["tick"]),
        "seeds": int(state["seeds"]),
        "brood_ready": bool(state["brood_ready"]),
        "brood_progress": int(state["brood_progress"]),
        "queen_hp": int(state["queen_hp"]),
        "enemy_queen_hp": int(state["enemy_queen_hp"]),
        "worker_count": len(state["workers"]),
        "soldier_count": len(state["soldiers"]),
        "units_lost": int(state["units_lost"]),
        "scout_active": state["scout_id"] is not None,
        "rival_outposts_ready": len(state["rival_outposts_ready"]),
        "intercepts_committed": len(state["defense_commitments"]),
        "waves_intercepted": len(state["successful_intercepts"]),
        "waves_cleared": len(state["resolved_waves"]),
        "opening_revealed": bool(state["opening_revealed"]),
        "production_queued": len(state["production"]),
        "terminal": bool(state["terminal"]),
        "won": bool(state["won"]),
    }


def _failure(feedback: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": feedback}


def grade(payload: dict[str, Any], ground_truth: dict[str, Any], public_state: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("mechanic_id") or "") != MECHANIC_ID:
        return _failure("mechanic mismatch")
    if str(ground_truth.get("mechanic_id") or "") != MECHANIC_ID or str(public_state.get("mechanic_id") or "") != MECHANIC_ID:
        return _failure("anthill contract mechanic mismatch")
    challenge_id = str(ground_truth.get("challenge_id") or "")
    if not challenge_id or payload.get("challenge_id") != challenge_id or public_state.get("challenge_id") != challenge_id:
        return _failure("stale challenge")
    task_id = str(ground_truth.get("task_id") or "")
    if not task_id or payload.get("task_id") != task_id or public_state.get("task_id") != task_id:
        return _failure("task identity mismatch")
    if public_state.get("world") != ground_truth.get("world"):
        return _failure("public and private world contracts differ")
    if public_state.get("control_condition") != ground_truth.get("control_condition"):
        return _failure("public and private control conditions differ")
    world = ground_truth.get("world")
    if not isinstance(world, dict):
        return _failure("missing world contract")
    condition = ground_truth.get("control_condition") or {}
    interaction = str(condition.get("interaction") or "full")
    expected_source = {"full": "direct_map", "simplified": "command_panel"}.get(interaction)
    if expected_source is None:
        return _failure("invalid interaction condition")
    events = payload.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= 240:
        return _failure("command transcript is missing or outside limits")

    state = initial_state(world)
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("sequence") != index:
            return _failure(f"command {index} has an invalid sequence")
        if event.get("input_source") != expected_source:
            return _failure(f"command {index} uses the wrong interaction surface")
        try:
            tick = int(event.get("tick"))
            action = str(event.get("action") or "")
            target = str(event.get("target") or "")
            unit_ids = event.get("unit_ids")
            if not isinstance(unit_ids, list) or any(not isinstance(value, str) for value in unit_ids):
                raise ValueError("unit selection is malformed")
            advance(state, world, tick)
            apply_action(state, world, action, unit_ids, target)
        except (KeyError, TypeError, ValueError) as exc:
            return _failure(f"command {index} is invalid: {exc}")

    try:
        final_tick = int(payload.get("final_tick"))
        advance(state, world, final_tick)
    except (TypeError, ValueError) as exc:
        return _failure(f"invalid final clock: {exc}")
    expected_summary = summary(state, world)
    if payload.get("final_state") != expected_summary:
        return _failure("submitted final state does not match deterministic replay")
    passed = (
        state["terminal"]
        and state["won"]
        and state["queen_hp"] > 0
        and state["enemy_queen_hp"] == 0
        and len(state["successful_intercepts"]) == len(world["raids"])
    )
    return {
        "graded": True,
        "passed": bool(passed),
        "feedback": (
            f"front {'won' if state['won'] else 'unsecured'} at tick {state['tick']}; "
            f"own queen {state['queen_hp']} HP; rival queen {state['enemy_queen_hp']} HP; "
            f"outposts {len(state['rival_outposts_ready'])}/{len(world['raids'])}; "
            f"intercepts {len(state['successful_intercepts'])}/{len(world['raids'])}; "
            f"waves {len(state['resolved_waves'])}/{len(world['raids'])}; ants lost {state['units_lost']}"
        ),
    }


def cheat(public_state: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    return {
        "route": copy.deepcopy(ground_truth.get("opponent_opening") or []),
        "instruction": "Gather with the colony, keep one worker at the listening front until contact is acquired, dig with the exact crew, raise soldiers, intercept each visibly moving formation inside the band, then march survivors to the rival queen.",
        "answers": [],
    }
