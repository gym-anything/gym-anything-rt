"""Disclosed privileged oracle; the exact downstream HTTP API is the sole input.

Reads generated recipes and read-only rendered geometry. No Playwright actions,
DOM focus, state mutation, clock control, or internal action calls are used.
"""
from __future__ import annotations

MECHANIC_ID = "craftcha_alchemy_bench_v2"


def next_pair(items, time_ms, truth):
    """Use mature available pairs, prioritizing the oldest perishable input."""
    choices = []
    for recipe in truth["recipes"]:
        if not all(key in items for key in recipe["inputs"]):
            continue
        hot = [items[key]["born_ms"] for key in recipe["inputs"] if truth["materials"][key]["hot"]]
        ready = max((born + truth["formation_ms"] for born in hot), default=0)
        if ready <= time_ms:
            choices.append((min(hot, default=float("inf")), recipe))
    return min(choices, key=lambda entry: entry[0])[1] if choices else None


def solve_http(ui, truth, *, execution="live", pacing_seconds=.3):
    def read():
        return ui.read("window.craftchaStormglassModel.snapshot()")

    def button(selector):
        return ui.read("(()=>{const r=document.querySelector(" + repr(selector) +
                       ").getBoundingClientRect();return [Math.round(r.x+r.width/2),Math.round(r.y+r.height/2)];})()")

    def screen(scene, point):
        r = scene["canvas"]
        return [round(r["x"] + point[0]*r["width"]/880), round(r["y"] + point[1]*r["height"]/360)]

    def click(point):
        return [{"mouse": {"left_click": point}}]

    mode = truth["control_condition"]["interaction"]
    scene = read()
    if scene["status"] == "ready":
        ui.send(click(button("#stormglass-start")))
    merges = 0
    while merges < len(truth["recipes"]):
        scene = read()
        if scene["status"] != "running":
            raise AssertionError(f"Alchemy run ended before merge: {scene['status']}")
        items = {i["id"]: i for i in scene["items"]}
        recipe = next_pair(items, scene["t_ms"], truth)
        if recipe is None:
            if execution == "paused":
                # The existing gateway's observation window advances the clock.
                ui.send([{"mouse": {"move": [2, 2]}}])
            else:
                ui.wait(.2)
            continue
        for attempt in range(4):
            scene = read()
            if scene["status"] != "running":
                raise AssertionError(f"Alchemy run ended before merge: {scene['status']}")
            items = {i["id"]: i for i in scene["items"]}
            source, target = recipe["inputs"]
            p = screen(scene, items[source]["point"])
            ui.send([{"mouse": {"move": p, "buttons": {"left_down": True}}}] if mode == "full" else click(p))
            scene = read()
            if scene["held"] == source:
                break
            if scene["held"] is not None:
                raise AssertionError("Oracle selected a wrong reagent")
            if mode == "full":
                ui.send([{"mouse": {"buttons": {"left_up": True}}}])
        else:
            raise AssertionError("Four fresh source observations could not select a reagent")
        items = {i["id"]: i for i in scene["items"]}
        p = screen(scene, items[target]["point"])
        ui.send([{"mouse": {"move": p}}, {"mouse": {"buttons": {"left_up": True}}}]
                if mode == "full" else click(p))
        scene = read()
        if recipe["output"] not in {i["id"] for i in scene["items"]}:
            raise AssertionError("HTTP placement did not craft its declared output")
        merges += 1
        if execution == "live" and pacing_seconds:
            ui.wait(pacing_seconds)
    if read()["status"] != "won":
        raise AssertionError("Heart was not completed through HTTP input")
    ui.send(click(button("#stormglass-certify")))
    return read()


def simulated_trace(truth, *, stale_ms=0, delay_ms=0, parked=False, spacing_ms=1500,
                    initial_only=False, honor_formation=True):
    """Pure replay diagnostic. This is never action-space or browser evidence."""
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.craftcha_alchemy_bench_v2 import position, hit
    mode = truth["control_condition"]["interaction"]
    src = {"full": ("pointer_down", "pointer_up"), "simplified": ("select_click", "place_click")}[mode]
    items = {i["id"]: dict(i) for i in truth["initial"]}
    events = [dict(sequence=1, kind="start", t_ms=0, input_surface="start_button")]
    def event(kind, t, **details):
        events.append(dict(sequence=len(events)+1,kind=kind,t_ms=t,**details))
    t = 1000
    for index in range(len(truth["recipes"])):
        if honor_formation:
            r = next_pair(items, t, truth)
            while r is None:
                t += 100
                r = next_pair(items, t, truth)
        else:
            r = truth["recipes"][index]
        t += spacing_ms
        source, target = r["inputs"]
        observed = 0 if initial_only else max(0, t-stale_ms)
        a = list(truth["lots"][items[source]["lot"]]["center"]) if parked else position(truth["lots"][items[source]["lot"]], observed)
        picked = hit(items, a, t, truth)
        event("pick" if picked else "probe", t, point=a, material_id=picked, input_surface=src[0])
        t += 300 + delay_ms
        b = list(truth["lots"][items[target]["lot"]]["center"]) if parked else position(truth["lots"][items[target]["lot"]], 0 if initial_only else max(0,t-stale_ms-delay_ms))
        actual = hit(items, b, t, truth, source)
        event("drop", t, point=b, target_id=actual, output_id=r["output"] if actual == target else None, input_surface=src[1])
        if picked != source or actual != target:
            break
        lot = items[target]["lot"]
        del items[source], items[target]
        items[r["output"]] = dict(id=r["output"], lot=lot, born_ms=t)
    event("submit",t+100,input_surface="certify_button")
    return dict(mechanic_id=MECHANIC_ID, revision=truth["revision"], task_id=truth["task_id"],challenge_id=truth["challenge_id"],
                interaction_mode=mode,events=events,final_t_ms=t+100,final_inventory=sorted(items.values(),key=lambda i:i["id"]),
                completed=len(items)==1 and truth["goal"] in items)
