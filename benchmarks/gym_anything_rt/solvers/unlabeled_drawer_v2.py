"""Implementation oracle: read-only privileged planning, literal transported inputs.

The caller owns delivery. Native evidence uses the frozen downstream HTTP API;
isolated Playwright delivery is explicitly separate implementation evidence.
Calibration answers are read only after visible feedback. The planner reads
generated visual features and live clock/geometry; it is not a screenshot-only
agent and produces no model score.
"""
import time
from collections import Counter
from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.unlabeled_drawer_v2 import category, rule_hypotheses
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.unlabeled_drawer_v2 import cargo_position, drawer_position


def click(point): return {'mouse': {'left_click': list(point)}}


def transfer(ui, start, end, mode):
    if mode == 'simplified':
        return ui.send([click(start), click(end)])
    return ui.send([{'mouse': {'move': list(start), 'buttons': {'left_down': True}}},
                    {'mouse': {'move': list(end)}}, {'mouse': {'buttons': {'left_up': True}}}])


def solve(ui, truth=None):
    del truth
    state = ui.read('unlabeledDrawerV2Model.state')
    mode = state.get('control_condition', {}).get('interaction', 'full')
    rect = ui.read('(() => {const r=document.querySelector("#ud2-stage").getBoundingClientRect();return [r.x,r.y,r.width,r.height];})()')

    def screen(point): return [rect[0]+point[0]*rect[2]/960, rect[1]+point[1]*rect[3]/560]
    hypotheses = rule_hypotheses(state['parameters'])
    untested = list(state['probes'])
    while len(hypotheses)>1:
        # Most informative visible card, selected without its unreturned outcome.
        def score(p):
            counts = Counter(category(p['features'], h) for h in hypotheses)
            return sum(n*n for n in counts.values())
        probe = min(untested, key=score)
        transfer(ui, screen(probe['center']), screen(state['probe_slot'][:2]), mode)
        returned = ui.read('unlabeledDrawerV2Model.tested')
        assert probe['id'] in returned, ('calibration input missed', returned, probe['id'])
        answer = returned[probe['id']]
        hypotheses = [h for h in hypotheses if category(probe['features'], h)==answer]
        assert hypotheses, 'feedback contradicts advertised family'
        untested.remove(probe)
    button = ui.read('(() => {const r=document.querySelector("#ud2-start").getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()')
    ui.send([click(button)])
    deadline = time.monotonic()+130
    while time.monotonic()<deadline:
        live = ui.read('({ms:unlabeledDrawerV2Model.ms,runAt:unlabeledDrawerV2Model.runAt,filed:unlabeledDrawerV2Model.filed,terminal:unlabeledDrawerV2Model.terminal,completed:unlabeledDrawerV2Model.completed,reason:unlabeledDrawerV2Model.reason})')
        if live['terminal']:
            assert live['completed'], live
            return
        ms = live['ms']-live['runAt']
        cargo = [p for p in state['cargo'] if p['id'] not in live['filed'] and p['spawn_ms']+120<=ms<p['spawn_ms']+p['life_ms']]
        if not cargo:
            ui.wait(.55)
            continue
        specimen = min(cargo, key=lambda p:p['spawn_ms']+p['life_ms'])
        target = category(specimen['features'], hypotheses[0])
        drawer = next(d for d in state['drawers'] if d['id']==target)
        # Prediction compensates only the ordinary live delivery interval.
        lead = getattr(ui, 'prediction_ms', 40)
        transfer(ui, screen(cargo_position(specimen, ms)), screen(drawer_position(drawer, ms+lead)), mode)
    raise AssertionError('cabinet oracle exceeded its declared task time')
