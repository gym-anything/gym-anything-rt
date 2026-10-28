"""Privileged read-only planner. Every input uses the supplied mouse transport.

The native validator supplies the frozen downstream HTTP gateway. A Playwright
adapter in task tests is explicitly wiring evidence, never native API evidence.
"""
import json
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.consequences_boss_v2 import active, hit, position


def box(ui, selector):
    return ui.read('(() => {const r=document.querySelector('+json.dumps(selector)+').getBoundingClientRect(); return [r.x,r.y,r.width,r.height];})()')


def center(rect):
    return [rect[0]+rect[2]/2,rect[1]+rect[3]/2]


def click(ui, point):
    ui.send([{'mouse':{'left_click':list(point)}}])


def cast(ui, rect, seal, target, mode):
    def screen(point):
        return [rect[0]+point[0]*rect[2]/1100,rect[1]+point[1]*rect[3]/500]
    start=screen([seal['x'],seal['y']]);end=screen(target)
    if mode=='full':
        ui.send([{'mouse':{'move':start,'buttons':{'left_down':True}}},
                 {'mouse':{'move':end}}, {'mouse':{'buttons':{'left_up':True}}}])
    else:
        ui.send([{'mouse':{'left_click':start}},{'mouse':{'left_click':end}}])


def prepare(ui,truth,all_mercy=False):
    rect=box(ui,'#cb-arena');mode=truth.get('control_condition',{}).get('interaction','full')
    vows={}
    for i,w in enumerate(truth['witnesses']):
        seal=truth['seals'][0 if all_mercy else i%2]
        cast(ui,rect,seal,[w['x'],w['y']],mode)
        vows[w['id']]=seal['id']
    click(ui,center(box(ui,'#cb-judgment')))
    return rect,mode,vows


def forecast_aim(truth,item,time,saved,window_ms=0):
    """Aim within the visible forecast, allowing for input delivery uncertainty."""
    if not window_ms:
        point=position(item,time)
        return point if (hit(truth,point,time,saved) or {}).get('id')==item['id'] else None
    times=[time+d for d in range(0,window_ms+1,100)]
    if not all(active(item,t) for t in times):return None
    points=[position(item,t) for t in times]
    point=[(min(p[k] for p in points)+max(p[k] for p in points))/2 for k in (0,1)]
    # The same thread samples are visible in the task. The margin covers the
    # small interpolation difference between samples, without changing hits.
    if any(sum((point[k]-p[k])**2 for k in (0,1))>(item['radius']-5)**2 for p in points):return None
    return point if all((hit(truth,point,t,saved) or {}).get('id')==item['id'] for t in times) else None


def solve(ui,truth,lead_ms=30,all_mercy=False,delivery_window_ms=0):
    rect,mode,vows=prepare(ui,truth,all_mercy)
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        status=ui.read('({t:Math.round(performance.now()-consequencesBossV2Model.epoch)-consequencesBossV2Model.started,saved:[...consequencesBossV2Model.saved],terminal:consequencesBossV2Model.terminal,reason:consequencesBossV2Model.reason})')
        if status['terminal']:
            assert len(status['saved'])==len(truth['echoes']),status
            return
        predicted=status['t']+lead_ms
        # Late enough for motion evidence; prioritize the oldest live judgment.
        candidates=[e for e in truth['echoes'] if e['id'] not in status['saved'] and active(e,predicted) and predicted-e['spawn_ms']>=1800]
        candidates.sort(key=lambda e:e['spawn_ms']+e['lifetime_ms'])
        aimed=[(e,forecast_aim(truth,e,predicted,set(status['saved']),delivery_window_ms)) for e in candidates]
        chosen=next(((e,p) for e,p in aimed if p is not None),None)
        if chosen:
            item,point=chosen
            seal=next(s for s in truth['seals'] if s['id']==vows[item['witness_id']])
            cast(ui,rect,seal,point,mode)
        else:
            ui.wait(.24)
    raise AssertionError('covenant controller timed out')
