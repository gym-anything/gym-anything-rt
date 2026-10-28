"""Privileged construction controllers with explicit input adapters.

The controller reads current task state and the displayed 1.2-second forecast's
geometry. It is construction evidence, not a screenshot-only model policy.
``solve`` requires native HTTP; ``solve_browser`` uses isolated Playwright and
cannot establish native action-API parity. Both inspect layers with UI clicks.
"""
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.tomographic_baggage_surgery_v3 import motion

READ = """(() => {const m=tomographicBaggageSurgeryV3Model;
 const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return [r.x,r.y,r.width,r.height];};
 return {t:m.t,x:m.x,yz:m.yz,velocity:m.velocity,command:m.command,phase:m.phase,held:m.held,failure:m.failure,
 grade:m.grade||null,submitted:m.submitted,pad:rect('.tbs2-pad'),start:rect('.tbs2-start'),
 slices:[...document.querySelectorAll('[data-slice]')].map(b=>{const r=b.getBoundingClientRect();return [r.x,r.y,r.width,r.height];}),
 grip:document.querySelector('.tbs2-grip')?rect('.tbs2-grip'):null};})()"""


def aim(c,s,t=None):
    t=s['t'] if t is None else t
    r=c['physics']['load_radius'] if s['held'] else c['physics']['tool_radius']
    gates=list(reversed(c['gates'])) if s['held'] else c['gates']
    g=next((g for g in gates if s['x']>=g['x']-g['half']-r),None) if s['held'] else next((g for g in gates if s['x']<=g['x']+g['half']+r),None)
    spec=g['motion'] if g else c['target']['motion']
    # Compensate ordinary damped-servo lag within the visible forecast.
    future=t+220
    a,b=motion(spec,future),motion(spec,future+40)
    vel=[(y-x)/.04 for x,y in zip(a,b)]
    p=c['parameters'];limit=c['views']['pad_extent']
    return [max(-limit,min(limit,x+v*p['damping']/p['gain'])) for x,v in zip(a,vel)]


def pad_point(c,command):
    v=c['views'];return [v['pad_origin'][0]+v['pad_scale']*command[0],v['pad_origin'][1]-v['pad_scale']*command[1]]


def screen(rect,point):
    return [rect[0]+point[0]*rect[2]/300,rect[1]+point[1]*rect[3]/280]


def controls(c,s,desired):
    destination=screen(s['pad'],pad_point(c,desired))
    if c['control_condition']['interaction']=='simplified':
        return [{'mouse':{'left_click':destination}}]
    origin=screen(s['pad'],pad_point(c,s['command']))
    return [{'mouse':{'move':origin,'buttons':{'left_down':True}}},
            {'mouse':{'move':destination}}, {'mouse':{'buttons':{'left_up':True}}}]


def solve(ui,truth,execution_mode='live',observation_delay_ms=0,parked=False):
    assert getattr(ui,'native_http_action_api',False), 'Complete solution evidence requires the verified native HTTP API'
    s=ui.read(READ)
    for r in s['slices']:
        ui.send([{'mouse':{'left_click':[r[0]+r[2]/2,r[1]+r[3]/2]}}])
    a=s['start'];ui.send([{'mouse':{'left_click':[a[0]+a[2]/2,a[1]+a[3]/2]}}])
    wall_limit=560 if execution_mode=='paused' else 150
    deadline=time.monotonic()+wall_limit;samples=[]
    while time.monotonic()<deadline:
        began=time.monotonic();s=ui.read(READ);samples.append(s)
        if s['submitted']:return dict(successful=s['grade'].get('passed') is True,samples=samples,privileged_planning=True)
        if s['phase'] in ('failed','complete'):
            time.sleep(.05);continue
        desired=aim(truth,s,max(0,s['t']-observation_delay_ms))
        actions=[] if parked else controls(truth,s,desired)
        if s['phase']=='grip' and math.dist(s['yz'],motion(truth['target']['motion'],s['t']))<truth['physics']['grip_distance']*.65:
            if truth['control_condition']['interaction']=='full':actions.append({'keyboard':{'keys':['Space']}})
            else:
                r=s['grip'];actions.append({'mouse':{'left_click':[r[0]+r[2]/2,r[1]+r[3]/2]}})
        ui.send(actions)
        if execution_mode=='live':ui.wait(max(0,.15-(time.monotonic()-began)))
    raise TimeoutError('Extraction did not finish within the declared finite oracle budget')


def simulation(c,interval_ms=150,delay_ms=0,parked=None,fixed=False,inspect=True):
    """Privileged controller diagnostic; no action-space or human claim."""
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.tomographic_baggage_surgery_v3 import initial,advance,apply
    s=initial(c);events=[]
    def event(kind,**kw):
        e=dict(sequence=len(events)+1,t_ms=s['t'],kind=kind,**kw);events.append(e);apply(c,s,e)
    mode=c['control_condition']['interaction'];source='drag_pad' if mode=='full' else 'click_pad'
    def steer(dest):
        if mode=='full':
            event('pad_down',point=pad_point(c,s['command']),input_source=source)
            event('pad_move',point=pad_point(c,dest),input_source=source)
            event('pad_up',point=pad_point(c,dest),input_source=source)
        else:event('pad_click',point=pad_point(c,dest),input_source=source)
    if inspect:
        for g in c['gates']:event('slice_scan',layer_id=g['id'],input_source='slice_button')
    if parked is not None:steer(parked)
    event('start')
    while s['t']<c['physics']['max_ms'] and s['phase'] not in ('failed','complete'):
        if parked is None:
            desired=[0,0] if fixed else aim(c,s,max(0,s['t']-delay_ms))
            steer(desired)
        if s['phase']=='grip' and math.dist(s['yz'],motion(c['target']['motion'],s['t']))<c['physics']['grip_distance']*.65:
            event('grip',input_source='space_key' if mode=='full' else 'grip_button')
        advance(c,s,min(c['physics']['max_ms'],s['t']+interval_ms))
    return dict(mechanic_id=c['mechanic_id'],revision=c['revision'],task_id=c['task_id'],challenge_id=c['challenge_id'],
                interaction=mode,events=events,final_t_ms=s['t']),s


def steer_browser(page, c, s, desired):
    """Ordinary pointer inputs on the visible pad, with privileged planning."""
    destination=screen(s['pad'],pad_point(c,desired))
    if c['control_condition']['interaction']=='full':
        page.mouse.move(*screen(s['pad'],pad_point(c,s['command'])))
        page.mouse.down();page.mouse.move(*destination);page.mouse.up()
    else:page.mouse.click(*destination)


def solve_browser(page, c, on_sample=None, first_layer_observer=None):
    """Live Playwright solve. No task-clock or page-state mutation.

    Geometry/state reads plan the feedback controller. Only visible controls
    deliver scans, steering, START and grip. Screenshots may be saved by the
    callback; this adapter makes no end-to-end screenshot-only or native API
    claim. An optional observer can supply screenshot-derived steering until
    the first layer has been crossed; no private aim is used in that interval.
    """
    for i in range(len(c['gates'])):page.locator(f'[data-slice="{i}"]').click()
    if first_layer_observer:page.locator('[data-slice="0"]').click()
    page.locator('.tbs2-start').click()
    deadline=time.monotonic()+150;samples=[]
    while time.monotonic()<deadline:
        began=time.monotonic();s=page.evaluate(READ);samples.append(s)
        if s['submitted']:
            return dict(successful=s['grade'].get('passed') is True,samples=samples,
                        privileged_planning=True,action_path='Playwright mouse/keyboard')
        if s['phase'] not in ('failed','complete'):
            desired=first_layer_observer(page,s) if first_layer_observer else None
            s['planning_source']='scanned_pixels' if desired is not None else 'privileged_replay'
            steer_browser(page,c,s,aim(c,s) if desired is None else desired)
            if s['phase']=='grip' and math.dist(s['yz'],motion(c['target']['motion'],s['t']))<c['physics']['grip_distance']*.65:
                if c['control_condition']['interaction']=='full':page.keyboard.press('Space')
                else:page.locator('.tbs2-grip').click()
        if on_sample:on_sample(page,s)
        page.wait_for_timeout(max(0,150-(time.monotonic()-began)*1000))
    raise TimeoutError('Live browser extraction exceeded the finite 150-second construction budget')
