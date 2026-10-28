"""Privileged implementation oracle with transport-neutral primitive inputs.

The truth and read-only diagnostics plan this oracle. All effects go through
ui.send(mouse/keyboard actions). Headless Playwright tests of this solver do
NOT establish frozen downstream HTTP action-API parity.
"""
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.surveyors_toybox_v2 import handle, pose, project
from gym_anything_rt.tools.nonrealtime_four_v2_oracle import box, center, click, drag


def snapshot(ui):
    return ui.read('({ms:surveyorsToyboxV2Model.sim.ms, active:surveyorsToyboxV2Model.sim.active, '
                   'annotations:surveyorsToyboxV2Model.sim.annotations, terminal:surveyorsToyboxV2Model.terminal, '
                   'selected:surveyorsToyboxV2Model.selected, tool:surveyorsToyboxV2Model.tool, '
                   'charge:surveyorsToyboxV2Model.sim.charge, outcome:surveyorsToyboxV2Model.outcome})')


def select(ui, target):
    if snapshot(ui)['selected'] != target:
        click(ui, center(box(ui, f'[data-target="{target}"]')))


def edit(ui, truth, target, tool, expected):
    select(ui, target)
    if snapshot(ui)['terminal']:
        return
    if snapshot(ui)['tool'] != tool:
        click(ui, center(box(ui, f'[data-tool="{tool}"]')))
    state = snapshot(ui)
    if state['terminal']:
        return
    annotation = state['annotations'][target]
    surface = 'plan' if tool == 'plan' else 'front' if tool == 'height' else 'dial' if tool == 'yaw' else 'extent'
    size = (440, 420) if surface in ('plan', 'front') else (230, 160) if surface == 'dial' else (230, 130)
    rect = box(ui, f'[data-surface="{surface}"]')
    start = handle(truth, annotation, tool)
    if tool == 'plan':
        end = project(truth['views']['plan'], expected['center'])
    elif tool == 'height':
        end = project(truth['views']['front'], expected['center'])
        if truth['interaction_mode'] == 'full':
            end[0] = start[0]
    elif tool == 'yaw':
        angle = math.radians(expected['yaw'])
        end = [115 + 56 * math.cos(angle), 80 + 56 * math.sin(angle)]
    else:
        axis = int(tool[-1])
        end = [20 + 160 * expected['half'][axis], 25 + 40 * axis]
    def screen(point):
        return [rect[0] + point[0] * rect[2] / size[0], rect[1] + point[1] * rect[3] / size[1]]
    if truth['interaction_mode'] == 'full':
        drag(ui, screen(start), screen(end))
    else:
        click(ui, screen(end))


def prepare(ui, truth):
    objects = {obj['id']: obj for obj in truth['objects']}
    for label, object_id in truth['target_map'].items():
        select(ui, label)
        click(ui, center(box(ui, '[data-tool="link"]')))
        # At its projected center a target is nearest to itself in the
        # transparent plate. No DOM focus or injected link is used.
        point = project(truth['views']['plan'], pose(objects[object_id], 0)['center'])
        rect = box(ui, '[data-surface="plan"]')
        point = [rect[0] + point[0]*rect[2]/440, rect[1] + point[1]*rect[3]/420]
        if truth['interaction_mode'] == 'full':
            drag(ui, point, center(box(ui, '.st2-socket')))
        else:
            click(ui, point)
        expected = pose(objects[object_id], 0)
        for tool in ('extent0', 'extent1', 'extent2', 'yaw', 'height', 'plan'):
            edit(ui, truth, label, tool, expected)


def solve(ui, truth, *, max_seconds=105, lead_ms=120):
    """Complete a live scan; the caller owns transport, tracing and recording."""
    prepare(ui, truth)
    click(ui, center(box(ui, '.st2-start')))
    objects = {obj['id']: obj for obj in truth['objects']}
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        state = snapshot(ui)
        if state['terminal']:
            for _ in range(100):
                state = snapshot(ui)
                if state['outcome'] is not None:
                    if not state['outcome'].get('passed'):
                        raise AssertionError(f"survey oracle failed: {state}")
                    return state
                ui.wait(.03)
            raise AssertionError('server did not return a verdict')
        for label, object_id in truth['target_map'].items():
            for tool in ('plan', 'height', 'yaw'):
                state = snapshot(ui)
                if state['terminal']:
                    break
                expected = pose(objects[object_id], state['ms'] + lead_ms)
                annotation = state['annotations'][label]
                change = (math.hypot(expected['center'][0]-annotation['center'][0], expected['center'][2]-annotation['center'][2]) > .045
                          if tool == 'plan' else abs(expected['center'][1]-annotation['center'][1]) > .035
                          if tool == 'height' else abs((expected['yaw']-annotation['yaw']+90) % 180-90) > 1.8)
                if change:
                    edit(ui, truth, label, tool, expected)
        ui.wait(.02)
    raise AssertionError('survey implementation oracle timed out')
