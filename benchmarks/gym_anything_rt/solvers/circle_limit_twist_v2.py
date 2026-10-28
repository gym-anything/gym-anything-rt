"""Privileged oracle planner with mouse-only actions through the supplied UI.

``ui.send`` must be the frozen downstream HTTP gateway for parity evidence.
A headless Playwright adapter is useful for wiring checks and is explicitly
not HTTP parity. This module never mutates game state or invokes game actions.
"""
from __future__ import annotations

READ = """(() => {
 const m=circleLimitTwistV2Model, r=m.canvas.getBoundingClientRect();
 const t=Math.min(m.puzzle.play_time_ms,Math.round(performance.now()-m.startedAt));
 const view=circleLimitTwistV2Math.flowView(m.userView,m.puzzle.flow,t,m.motor);
 return {t, ready:m.readyAt, twists:m.twists, terminal:m.terminal, outcome:m.outcome,
   mode:m.interaction, state:m.current, selected:m.focusedFace,
   faces:m.puzzle.faces.map(f=>circleLimitTwistV2Math.applyView(view,f.center)),
   aperture:m.puzzle.activation_radius, box:{x:r.x,y:r.y,w:r.width,h:r.height}};
})()"""


def click(ui, point, right=False):
    point = [round(v) for v in point]
    if right:
        ui.send([{"mouse": {"move": point, "buttons": {"right_down": True}}},
                 {"mouse": {"buttons": {"right_up": True}}}])
    else:
        ui.send([{"mouse": {"left_click": point}}])


def drag(ui, start, end):
    ui.send([{"mouse": {"move": [round(v) for v in start], "buttons": {"left_down": True}}},
             {"mouse": {"move": [round(v) for v in end]}},
             {"mouse": {"buttons": {"left_up": True}}}])


def screen(box, point):
    return [box['x'] + (450 + 420 * point[0]) * box['w'] / 900,
            box['y'] + (450 + 420 * point[1]) * box['h'] / 900]


def button(ui, selector):
    return ui.read(f"(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()")


def solve_api(ui, ground_truth, request_budget=180):
    """Read privileged poses for planning; send only literal mouse primitives."""
    initial_calls = getattr(ui, 'calls', 0)
    # The proxy buttons stay in fixed positions throughout this challenge.
    # Retain selection and cache their rectangles so a correction can turn
    # promptly instead of reselecting a moving face on every failed attempt.
    initial = ui.read(READ)
    proxy_points = {direction: button(ui, f'.twist-proxy button[data-direction="{direction}"]')
                    for direction in (-1,1)} if initial['mode'] == 'simplified' else {}
    drag_delay_ms = 0
    expected_twists = initial['twists']

    def accepted_move(state, move):
        if state['twists'] == expected_twists:
            return False
        if state['twists'] != expected_twists + 1:
            raise AssertionError('oracle observed unexpected additional accepted turns')
        event = ui.read("circleLimitTwistV2Model.events.filter(e => e.kind === 'turn' && e.accepted).at(-1)")
        if event['face_id'] != move['face_id'] or event['direction'] != move['direction']:
            raise AssertionError('oracle clicked a different face or direction')
        return True

    for move in ground_truth['solution_moves']:
        for _ in range(60):
            if getattr(ui, 'calls', 0) - initial_calls >= request_budget - 1:
                raise AssertionError('oracle request budget exhausted')
            state = ui.read(READ)
            # HTTP acknowledges X processing; browser event delivery can be
            # later. Reconcile the previous input before retrying its turn.
            if accepted_move(state, move):
                break
            if state['terminal']:
                raise AssertionError(f"unexpected terminal state: {state}")
            if state['t'] < state['ready']:
                ui.wait(min(.25, (state['ready'] - state['t']) / 1000))
                continue
            p = state['faces'][move['face_id']]
            distance = (p[0]**2 + p[1]**2)**.5
            centered_fraction = .60 if state['mode'] == 'simplified' and state['selected'] == move['face_id'] else .25
            if distance > state['aperture'] * centered_fraction:
                # Large translations can begin on empty disc space. No tiny
                # rim sticker must be grabbed to bring a rim face inward.
                # Plan against the measured time of input and redraw rather
                # than repeatedly dragging toward an already stale position.
                if drag_delay_ms:
                    forecast = READ.replace('flow,t,m.motor)', f'flow,t+{drag_delay_ms},m.motor)')
                    state = ui.read(forecast)
                    p = state['faces'][move['face_id']]
                    distance = (p[0]**2 + p[1]**2)**.5
                scale = min(1, .80 / max(distance, 1e-9))
                drag(ui, screen(state['box'], [v * scale for v in p]), screen(state['box'], [0, 0]))
                delivered = ui.read(READ)
                measured = max(0, delivered['t'] - state['t'])
                drag_delay_ms = min(900, round(measured if not drag_delay_ms else .5 * (drag_delay_ms + measured)))
                continue
            if state['mode'] == 'full':
                click(ui, screen(state['box'], p), right=move['direction'] == 1)
            else:
                if state['selected'] != move['face_id']:
                    click(ui, screen(state['box'], p))
                click(ui, proxy_points[move['direction']])
            after = ui.read(READ)
            if accepted_move(after, move):
                break
        else:
            raise AssertionError('could not execute the next inverse turn')
        expected_twists += 1
    state = ui.read(READ)
    if not all(len(set(face)) == 1 for face in state['state']):
        raise AssertionError('inverse trace did not restore every face')
    click(ui, button(ui, '#clt2-certify'))
    for _ in range(100):
        result = ui.read(READ)
        if result.get('outcome') is not None:
            if not result['outcome']['passed']:
                raise AssertionError(result)
            return result
        ui.wait(.03)
    raise AssertionError('grade response did not arrive')
