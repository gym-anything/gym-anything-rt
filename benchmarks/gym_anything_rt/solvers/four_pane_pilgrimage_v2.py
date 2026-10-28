"""Privileged planning; every input uses the caller's mouse/keyboard action transport.

Native validation supplies the frozen HTTP gateway. Headless implementation checks
supply an explicitly identified Playwright transport, which is not parity evidence.
"""
import math
import time
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.four_pane_pilgrimage_v2 import pose

MODEL='fourPanePilgrimageV2Model'


def click(p): return {'mouse':{'left_click':[int(p[0]),int(p[1])]}}


def drag(a,b):
    return [{'mouse':{'move':[int(a[0]),int(a[1])],'buttons':{'left_down':True}}},
            {'mouse':{'move':[int(b[0]),int(b[1])]}},{'mouse':{'buttons':{'left_up':True}}}]


def rect(ui,selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def center(b):return [b[0]+b[2]/2,b[1]+b[3]/2]


def read(ui):
    return ui.read(f'({{tick:{MODEL}.tick,windows:{MODEL}.windows,terminal:{MODEL}.terminal,progress:{MODEL}.progress,slots:{MODEL}.slots}})')


def solve(ui, truth, *, cadence=.12, horizon_ms=120, timeout_sec=180):
    mode=(truth.get('control_condition') or {}).get('interaction','full')
    slots=list(truth['initial_slots'])
    for slot,i in enumerate(truth['route']):
        if slots[slot]==i:continue
        a=center(rect(ui,f'[data-header="{i}"]'));b=center(rect(ui,f'[data-header="{slots[slot]}"]'))
        ui.send([click(a),click(b)] if mode=='simplified' else drag(a,b))
        prev=slots.index(i);slots[prev],slots[slot]=slots[slot],i
    boxes={i:rect(ui,f'[data-canvas="{i}"]') for i in range(4)}
    def screen(i,p):
        b=boxes[i];return [b[0]+p[0]*b[2]/340,b[1]+p[1]*b[3]/220]
    for i in range(4):
        a=center(rect(ui,f'[data-layer="{i}"]'));b=screen(i,pose(truth['panels'][i],0))
        ui.send([click(a),click(b)] if mode=='simplified' else drag(a,b))
    size_buttons={i:{d:center(rect(ui,f'[data-size="{i},{d}"]')) for d in (-1,1)} for i in range(4)} if mode=='simplified' else {}
    def adjustments(s,t):
        actions=[]
        for i in range(4):
            target=pose(truth['panels'][i],t);current=s['windows'][i]
            if math.dist(current[:2],target[:2])>1.5:
                if mode=='simplified':actions.append(click(screen(i,target)))
                else:
                    # Pan from the canvas centre: sparse delivered displacement
                    # is the same direct manipulation the human can perform.
                    a=screen(i,[170,110]);b=screen(i,[170+target[0]-current[0],110+target[1]-current[1]])
                    actions.extend(drag(a,b))
            n=round((target[2]-current[2])/truth['radius_step'])
            for _ in range(abs(n)):
                d=1 if n>0 else -1
                if mode=='simplified':actions.append(click(size_buttons[i][d]))
                # The frozen native API uses positive notches for wheel-down.
                # The visible canvas enlarges on wheel-up, hence the negation.
                else:actions.extend([{'mouse':{'move':[int(x) for x in screen(i,[170,110])]}},{'mouse':{'scroll':-d}}])
        return actions
    actions=adjustments(read(ui),0)
    if actions:ui.send(actions)
    ui.send([click(center(rect(ui,'.fpv-begin')))])
    deadline=time.monotonic()+timeout_sec
    while time.monotonic()<deadline:
        s=read(ui)
        if s['terminal']:
            assert s['terminal']=='arrived',s
            ui.send([click(center(rect(ui,'.fpv-seal')))])
            return
        actions=adjustments(s,s['tick']*20+horizon_ms)
        if actions:ui.send(actions)
        if hasattr(ui,'advance'):ui.advance(600)
        else:ui.wait(cadence)
    raise AssertionError('Registration controller timed out')
