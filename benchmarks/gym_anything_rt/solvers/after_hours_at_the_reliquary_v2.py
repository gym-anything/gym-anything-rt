"""Privileged read-only planning; all mutations are literal public inputs.

UI must implement read, send and wait. Native send is the frozen model HTTP
API. The headless test adapter is separately labelled wiring evidence.
"""
import math
import time
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.after_hours_at_the_reliquary_v2 import socket_pose

MECHANIC_ID='after_hours_at_the_reliquary_v2'

def rect(ui,selector):
    return ui.read(f'(()=>{{let r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')

def screen(r,p,wh):return [r[0]+p[0]*r[2]/wh[0],r[1]+p[1]*r[3]/wh[1]]
def center(r):return [r[0]+r[2]/2,r[1]+r[3]/2]
def click(p):return [{'mouse':{'left_click':p}}]
def drag(a,b):return [{'mouse':{'move':a,'buttons':{'left_down':True}}},{'mouse':{'move':b}},{'mouse':{'buttons':{'left_up':True}}}]

def solve(ui,truth,*,delay=0,interval=.10,prepared=False):
    mode=(truth.get('control_condition') or {}).get('interaction','full')
    scene=rect(ui,'.rel2-scene');dial=rect(ui,'.rel2-angle');rail=rect(ui,'.rel2-span')
    def canvas(p):return screen(scene,p,[1000,500])
    def turn(view):
        current=ui.read('reliquaryV2Model.view')
        while current!=view:
            selector='.rel2-right' if (view-current)%len(truth['views']) <= (current-view)%len(truth['views']) else '.rel2-left'
            ui.send(click(center(rect(ui,selector))));current=ui.read('reliquaryV2Model.view')
    def combine(item,mate):
        a=center(rect(ui,f'[data-item="{item}"]'));b=center(rect(ui,f'[data-item="{mate}"]'))
        ui.send(drag(a,b) if mode=='full' else click(a)+click(b))
    def use(item,dest):
        turn(dest['view']);a=center(rect(ui,f'[data-item="{item}"]'));b=canvas(center(dest['rect']))
        ui.send(drag(a,b) if mode=='full' else click(a)+click(b))
    if not prepared:
        for o in truth['targets']:
            turn(o['view']);ui.send(click(canvas(center(o['rect'])))+click(canvas(center(o['rect']))))
        combine('handle','wire')
        if truth['parameters']['loupe']:
            combine('frame','glass');use('loupe',truth['mural'])
        use('key',truth['ignition'])
    # Paused native input can consume several wall seconds per 200 ms task
    # window. Keep the controller inside the declared 600 s episode budget.
    deadline=time.monotonic()+540;loops=0
    while time.monotonic()<deadline:
        state=ui.read('({tick:reliquaryV2Model.tick,start:reliquaryV2Model.start,pose:reliquaryV2Model.pose,target:reliquaryV2Model.target,unsealed:reliquaryV2Model.unsealed,failed:reliquaryV2Model.failed,charge:reliquaryV2Model.charge})')
        if state['failed']:raise AssertionError('ward spring exhausted: '+str(state))
        if state['unsealed']:
            ui.send(click(canvas([930,295])));return dict(control_updates=loops,charge=state['charge'])
        if delay:ui.wait(delay)
        goal=socket_pose(truth,(state['tick']-state['start'])*20+180)
        axes=[('position',canvas([state['pose']['x'],state['pose']['y']]),canvas([goal['x'],goal['y']]))]
        if truth['parameters']['angle']:
            def dialpoint(v):return screen(dial,[90+58*math.cos(math.radians(v)),80+58*math.sin(math.radians(v))],[280,160])
            axes.append(('angle',dialpoint(state['target']['angle']),dialpoint(goal['angle'])))
        if truth['parameters']['span']:
            def railpoint(v):return screen(rail,[20+(v-180)/380*240,40],[280,80])
            axes.append(('span',railpoint(state['target']['span']),railpoint(goal['span'])))
        actions=[]
        for axis,a,b in axes:actions+=drag(a,b) if mode=='full' else click(b)
        ui.send(actions);loops+=1;ui.wait(interval)
    raise AssertionError('articulated ward controller timed out')
