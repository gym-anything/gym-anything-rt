"""Privileged oracle planning through the supplied mouse-input adapter.

The read-only diagnostic sees current task state and future seeded geometry.
Native callers supply the downstream HTTP mouse API. Headless evidence may use
a Playwright adapter and must identify that boundary. No page mutations, focus
calls or internal game calls are used. This is not model-performance evidence.
"""
import copy
import re
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.crackglaze_crossing_v3 import center, crossing_failure, span_distance, direction
from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.crackglaze_crossing_v3 import certificate

READ = "({t_ms:crackglazeV3Model.terminal?crackglazeV3Model.currentMs:Math.max(0,Math.round(performance.now()-crackglazeV3Model.startedAt)),position:crackglazeV3Model.position,flight:crackglazeV3Model.flight,lit_at:crackglazeV3Model.litAt,collected:[...crackglazeV3Model.collected],terminal:crackglazeV3Model.terminal,failure:crackglazeV3Model.failure,passed:crackglazeV3Model.passed})"
READ_SAMPLES = "[...document.querySelectorAll('.cc-v3-sample')].map(s=>({glaze:Number(s.dataset.glaze),mark:s.querySelector('i').textContent.trim(),name:s.querySelector('span').firstChild.textContent.trim(),stamp:s.querySelector('b').textContent.trim(),inspected:s.dataset.inspected==='true'}))"


def rectangle(ui, selector):
    return ui.read("(()=>{const r=document.querySelector("+repr(selector)+").getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};})()")


def midpoint(rect):
    return [round(rect['x']+rect['width']/2), round(rect['y']+rect['height']/2)]


def inspect_glazes(ui, truth):
    """Build lifetime knowledge from revealed UI text, not private fuse values.

    Future geometry and the route remain privileged oracle inputs. Reading the
    rendered sample text is diagnostic DOM access, not screenshot-only evidence.
    Every sample turn still goes through the caller's ordinary mouse adapter.
    """
    samples = ui.read(READ_SAMPLES)
    for sample in samples:
        selector = f'[data-glaze="{sample["glaze"]}"]'
        ui.send([{'mouse': {'left_click': midpoint(rectangle(ui, selector))}}])
    world = copy.deepcopy(truth)
    lifetimes, observed = {}, {}
    for sample in ui.read(READ_SAMPLES):
        match = re.fullmatch(r'(\d+(?:\.\d+)?)s after leaving', sample['stamp'])
        glaze = sample['glaze']
        if (not sample['inspected'] or not match or glaze in lifetimes
            or type(glaze) is not int or not 0 <= glaze < len(world['glazes'])):
            raise AssertionError('missing or malformed visible kiln stamp')
        life_ms = round(float(match[1]) * 1000)
        if life_ms <= 0:
            raise AssertionError('invalid visible kiln lifetime')
        lifetimes[glaze] = life_ms
        observed[sample['mark']] = dict(text=sample['stamp'], life_ms=life_ms)
        world['glazes'][glaze].update(name=sample['name'], mark=sample['mark'], fuse_ms=life_ms)
    if len(lifetimes) != len(world['glazes']):
        raise AssertionError('not every glaze has a visible kiln stamp')
    for cell in world['cells']:
        cell['fuse_ms'] = lifetimes[cell['glaze']]
    return world, observed


def plan_continuation(truth, route, start_ms, margin, lit_at):
    # The certificate samples future crossings every 100 ms. Searching only
    # 500 ms start offsets keeps the same sampling phase and can miss a valid
    # nonperiodic continuation. Search all four 25 ms phases without changing
    # the certificate used to accept generated worlds or the actual game clock.
    for settle in (100, 200, 400, 600):
        for delay in range(0, 30001, 500):
            for phase in (0, 25, 50, 75):
                schedule = certificate(truth, route, start_ms=start_ms+delay+phase,
                                       margin=margin, settle_ms=settle, lit_at=lit_at)
                if schedule:
                    return schedule
    return None


def solve_api(ui, truth, mode='live', max_seconds=420, prediction_ms=140, margin=5):
    interaction=truth['control_condition']['interaction']
    board=rectangle(ui,'#crack-v2-canvas')
    buttons={d:midpoint(rectangle(ui,f'[data-direction="{d}"]')) for d in ('up','down','left','right')} if interaction=='simplified' else {}
    truth,observed=inspect_glazes(ui,truth)
    route=truth['certificate']['route']
    cells={c['id']:c for c in truth['cells']}
    # A locally safe outgoing span can strand a later return on a lit fuse.
    # Reuse the existing future-motion certificate to plan the entire remaining
    # route after inspection, rather than greedily waiting at each branch.
    schedule=None
    schedule_index=0
    started=time.monotonic()
    index=0
    while index<len(route)-1:
        if time.monotonic()-started>max_seconds:
            raise TimeoutError('finite ceramic oracle wall-clock budget exhausted')
        state=ui.read(READ)
        if state['terminal']:
            raise AssertionError('ceramic attempt ended: '+str(state))
        if state['flight']:
            if mode=='paused':ui.send([])
            else:ui.wait(.05)
            continue
        origin,destination=route[index:index+2]
        if state['position']!=origin:
            raise AssertionError('HTTP crossing did not reach planned raft: '+str(state))
        if mode=='live' and (schedule is None or state['t_ms']>schedule['events'][index-schedule_index]['t_ms']+250):
            schedule=plan_continuation(truth,route[index:],state['t_ms']+2000,
                                       margin,state['lit_at'])
            if not schedule:raise AssertionError('no future-motion continuation found after inspection')
            schedule_index=index
            continue  # Read the actual shared clock again after planning.
        t=state['t_ms']+(prediction_ms if mode=='live' else 0)
        if schedule and t<schedule['events'][index-schedule_index]['t_ms']:
            ui.wait(min(.1,(schedule['events'][index-schedule_index]['t_ms']-t)/1000))
            continue
        clear=not crossing_failure(truth,origin,destination,t,state['lit_at']) and not crossing_failure(truth,origin,destination,state['t_ms'],state['lit_at'])
        if clear:
            # Reserve half the plan's spatial buffer for delivery uncertainty.
            # Requiring the entire planning margin at both now and the predicted
            # click time can reject a valid scheduled span solely because its
            # conservative 4 px window is shorter than the prediction interval.
            clear=max(span_distance(truth,origin,destination,start+dt) for start in (state['t_ms'],t) for dt in (0,250,500))<=truth['parameters']['reach_px']-margin/2
        if not clear:
            if mode=='paused':ui.send([])
            else:ui.wait(.1)
            continue
        if interaction=='full':
            p=center(cells[destination],t,truth['parameters'])
            point=[round(board['x']+p[0]*board['width']/truth['stage']['width']),round(board['y']+p[1]*board['height']/truth['stage']['height'])]
        else:
            d=direction(cells,origin,destination)
            point=buttons[d]
        ui.send([{'mouse':{'left_click':point}}])
        if mode=='live':ui.wait(.52)
        index+=1
    for _ in range(30):
        state=ui.read(READ)
        if state['passed']:return dict(state, inspected_glazes=observed,
                                      lifetime_source='revealed kiln sample text')
        if state['terminal'] and state['failure']:raise AssertionError(str(state))
        if mode=='paused' and state['flight']:ui.send([])
        else:time.sleep(.1)
    raise AssertionError('independent server pass not received: '+str(ui.read(READ)))
