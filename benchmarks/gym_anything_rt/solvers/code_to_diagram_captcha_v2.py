"""Privileged feasibility controller with a caller-supplied literal action API.

``read`` is read-only implementation inspection, explicitly privileged. ``send``
receives only the frozen mouse/keyboard/wait shapes. A headless transport is an
implementation test, not native HTTP parity. No new client or harness is added.
"""
from __future__ import annotations

import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.code_to_diagram_captcha_v2 import node_position, successor, motion_preview, position_from_preview, weld_position

READ = "({physics:liveFlowV2Model.physics.snapshot(),outcome:liveFlowV2Model.outcome,result:liveFlowV2Model.result,hold:liveFlowV2Model.hold})"


def box(ui, selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height]}})()')


def center(rect):
    return [rect[0]+rect[2]/2,rect[1]+rect[3]/2]


def click(ui, xy):
    ui.send([{"mouse":{"left_click":list(xy)}}])


def target_point(truth, stream, tick, lead_ms=230):
    node = next(n for n in truth["nodes"] if n["id"]==successor(truth,stream))
    return node_position(truth,node,tick*10+lead_ms)


def choose_stream(streams, tick):
    available = [p for p in streams if not p["done"] and p["ready_tick"]<=tick]
    return min(available,key=lambda p:p["ready_tick"]) if available else None


def simulate_policy(truth, interval_ms=200, observation_delay_ms=0, policy="feedback"):
    """Matched deterministic mechanism diagnostic; NOT an action-interface solve.

    One probe is serviced at a time. Exact replay state supports planning. Delayed
    observations are used without correction for the delay. The center policy knows
    the correct code edges but parks at cell centers, a strong static alternative.
    """
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.code_to_diagram_captcha_v2 import FlowPhysics
    sim = FlowPhysics(truth)
    sim.start()
    current=None
    history={0:sim.snapshot()}
    changes=0
    while not sim.won and not sim.failed:
        observed=history[max(0,sim.tick-observation_delay_ms//10)]
        if current is None or next(p for p in sim.streams if p["id"]==current[0])["node"]!=current[1]:
            selected=choose_stream(observed["streams"],observed["tick"])
            current=(selected["id"],selected["node"]) if selected else None
        if current:
            p=next(p for p in observed["streams"] if p["id"]==current[0])
            actual=next(p for p in sim.streams if p["id"]==current[0])
            if not p["done"] and not actual["done"]:
                if actual["armed"]:
                    node=next(n for n in truth["nodes"] if n["id"]==successor(truth,p))
                    xy=(list(node["center"]) if policy=="center" else
                        position_from_preview(motion_preview(truth,node,observed["tick"]*10),0))
                    xy[0]+=truth['physics']['weld_offset']
                    sim.pulse(actual,xy);changes+=1
                    current=None
                    continue
                if policy=="center":
                    node=next(n for n in truth["nodes"] if n["id"]==successor(truth,p))
                    actual["target"]=list(node["center"])
                elif policy=="feedback":
                    actual["target"]=target_point(truth,p,observed["tick"])
                elif policy=="visible_feedback":
                    # Uses the same announced finite rails as the UI, across
                    # knots as well as within a segment; no hidden tape query.
                    node=next(n for n in truth["nodes"] if n["id"]==successor(truth,p))
                    ms=observed["tick"]*10
                    actual["target"]=position_from_preview(motion_preview(truth,node,ms),230)
                else:
                    raise ValueError("unknown diagnostic policy")
                changes+=1
        end=min(sim.s["session_ms"]//10,sim.tick+interval_ms//10)
        while sim.tick<end and not sim.won and not sim.failed:
            sim.advance(sim.tick+1);history[sim.tick]=sim.snapshot()
        # Keep only the declared lag window, not an unbounded observation archive.
        cutoff=max(0,sim.tick-observation_delay_ms//10-interval_ms//10)
        history={k:v for k,v in history.items() if k>=cutoff}
    return dict(passed=sim.won,failed=sim.failed,tick=sim.tick,target_updates=changes,
                visits=sum(len(p["visits"]) for p in sim.streams),state=sim.snapshot())


def solve_api(ui, truth, *, cadence_seconds=.4, aim_lead_ms=430, max_calls=360, timeout_seconds=240):
    """Every input is submitted through ``ui.send``; no direct browser actions."""
    rect=box(ui,'.lfv-field')
    def screen(p):
        return [rect[0]+p[0]*rect[2]/880,rect[1]+p[1]*rect[3]/470]
    click(ui,center(box(ui,'.lfv-run')))
    mode=truth["control_condition"]["interaction"]
    current=None
    deadline=time.monotonic()+timeout_seconds
    while time.monotonic()<deadline:
        state=ui.read(READ);sim=state["physics"]
        if sim["failed"]:
            raise AssertionError(sim["failed"])
        if sim["won"]:
            if state["hold"]:ui.send([{"mouse":{"buttons":{"left_up":True}}}])
            click(ui,center(box(ui,'.lfv-seal')))
            grade_deadline=time.monotonic()+15
            while time.monotonic()<grade_deadline:
                result=ui.read(READ)
                if result.get("outcome") is not None:
                    return result
                ui.wait(.1)
            raise AssertionError('administrative server grading did not return')
        if getattr(ui,'calls',0)>=max_calls:
            raise AssertionError(f'feasibility action budget {max_calls} exhausted')
        p=next((p for p in sim["streams"] if current and p["id"]==current[0]),None)
        actions=[]
        if p is None or p["node"]!=current[1]:
            if state["hold"]:actions.append({"mouse":{"buttons":{"left_up":True}}})
            p=choose_stream(sim["streams"],sim["tick"])
            if p is None:
                if actions:ui.send(actions)
                current=None;ui.wait(cadence_seconds);continue
            current=(p["id"],p["node"])
            if mode=='full':
                actions.append({"mouse":{"move":screen(p["tip"]),"buttons":{"left_down":True}}})
            else:
                actions.append({"mouse":{"left_click":center(box(ui,f'[data-stream="{p["id"]}"]'))}})
        if p["armed"]:
            # A weld uses a directly chosen point, not the inertial aiming lead.
            node=next(n for n in truth['nodes'] if n['id']==successor(truth,p))
            target=weld_position(truth,node,sim['time_ms'])
            if mode=='full':
                if not state['hold'] or state['hold']['tool']!='weld':
                    if state['hold']:actions.append({"mouse":{"buttons":{"left_up":True}}})
                    actions.append({"mouse":{"move":screen(p['tip']),"buttons":{"left_down":True}}})
                actions.extend([{"mouse":{"move":screen(target)}},{"mouse":{"buttons":{"left_up":True}}}])
            else:
                actions.append({"mouse":{"left_click":center(box(ui,'.lfv-weld-tool'))}})
                actions.append({"mouse":{"left_click":screen(target)}})
            ui.send(actions);current=None
            ui.wait(cadence_seconds);continue
        target=target_point(truth,p,sim["tick"],aim_lead_ms)
        if mode=='full':
            actions.append({"mouse":{"move":screen(target)}})
        else:
            actions.append({"mouse":{"left_click":screen(target)}})
        ui.send(actions)
        ui.wait(cadence_seconds)
    raise AssertionError('live control-flow feasibility controller timed out')


def solve(page,state_dir,out_dir,mechanic):
    raise RuntimeError('Use solve_api with an explicitly identified transport; no implicit Playwright or HTTP fallback.')
