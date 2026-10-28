"""Disclosed oracle planning with only literal HTTP mouse/keyboard inputs.

The caller supplies read-only planning diagnostics and the frozen HTTP action
transport. This solver never mutates DOM/state, invokes game controls through
JavaScript, or supplies an implementation-level success token.
"""
import time
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.cell_gatekeeper_v2 import position

MECHANIC_ID = "cell_gatekeeper_v2"


def box(ui, selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def center(rect):
    return [rect[0]+rect[2]/2, rect[1]+rect[3]/2]


def solution(ui, truth, *, deadline_seconds=150, cadence_seconds=.10):
    rect = box(ui, ".cgv2-canvas")
    screen = lambda p: [rect[0]+p[0]*rect[2]/960, rect[1]+p[1]*rect[3]/450]
    mode = (truth.get("control_condition") or {}).get("interaction", "full")
    toggles = [center(box(ui, f'[data-toggle="{l["id"]}"]')) for l in truth["lanes"]] if mode == "simplified" else []
    ui.send([{"mouse": {"left_click": center(box(ui, "[data-start]"))}}])
    deadline = time.monotonic()+deadline_seconds
    while time.monotonic() < deadline:
        data = ui.read('({sim:cellGatekeeperV2Model.sim,elapsed_ms:cellGatekeeperV2Model.sim.started?performance.now()-cellGatekeeperV2Model.start:0,terminal:cellGatekeeperV2Model.terminal,decision:cellGatekeeperV2Model.decision})')
        sim = data["sim"]
        if sim["status"] == "failed":
            raise AssertionError(sim["failure"])
        if data["terminal"]:
            if data.get("decision"):
                assert data["decision"].get("passed"), data["decision"]
                # Preserve a final API observation after the asynchronous
                # grader reply, so the solution recording includes its verdict.
                ui.send([])
                return data
            ui.wait(.05)
            continue
        # A live animation callback can lag behind task time. Its last physics
        # tick must not grant the oracle extra time before the extension deadline.
        # performance.now() uses the same shared task clock in paused execution.
        ms = max(sim["tick"]*10, data.get("elapsed_ms", 0))
        actions = []
        for lane, pump in zip(truth["lanes"], sim["pumps"]):
            pending = [p for p in truth["particles"] if p["lane"] == lane["id"] and p["id"] not in sim["resolved"]]
            if not pending:
                continue
            nutrients = [p for p in pending if p["kind"] == "nutrient"]
            if not nutrients or pump["stroke_start"] is not None:
                continue
            ion = min(nutrients, key=lambda p: p["arrival_ms"])
            # Privileged oracle planning includes the landing coordinate.
            # This proves physical/API solvability, not screenshot inference.
            y = position(ion, ion["arrival_ms"], truth)[1]
            half = truth["parameters"]["aperture"]/2
            y = max(lane["low"]+half, min(lane["high"]-half, y))
            at_stop = y in (lane["low"]+half, lane["high"]-half)
            # Native integer coordinates can land up to one logical pixel below
            # a requested height. Repeating that identical click cannot improve
            # it; travel stops still require the existing exact clamp treatment.
            pixel = 450/rect[3]
            if abs(y-pump["target"]) > max(.5, pixel+.001) or (at_stop and abs(y-pump["target"]) > 1e-6):
                pointer_y = y-4 if y == lane["low"]+half else y+4 if y == lane["high"]-half else y
                if mode == "simplified":
                    actions.append({"mouse": {"left_click": screen([534,pointer_y])}})
                else:
                    actions.extend([{"mouse": {"move": screen([480,pump["y"]]), "buttons": {"left_down": True}}},
                                    {"mouse": {"move": screen([480,pointer_y])}},
                                    {"mouse": {"buttons": {"left_up": True}}}])
            p=truth["parameters"]
            lead=ion["arrival_ms"]-ms
            if p["stroke_arm_ms"] < lead < p["stroke_arm_ms"]+p["stroke_open_ms"]*.90:
                actions.append({"mouse": {"left_click": toggles[lane["id"]]}} if mode == "simplified" else
                               {"keyboard": {"keys": [str(lane["id"]+1)]}})
        ui.send(actions)
        ui.wait(cadence_seconds)
    raise AssertionError("membrane HTTP oracle exceeded its declared deadline")


def solve(page, state_dir, out_dir, mechanic):
    """Legacy solver seam deliberately refuses to claim HTTP action parity."""
    del page, state_dir, out_dir
    raise RuntimeError(f"{mechanic}: use solution(ui, truth) with the frozen native HTTP gateway; direct Playwright solutions are implementation diagnostics only")
