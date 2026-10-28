"""Privileged oracle planner using the supplied UI's ordinary mouse actions.

The diagnostic planner knows the inverse path and reads current task time and
visible geometry through Marionette. It never invokes game functions or writes
DOM/state. Inspection clicks reveal actual patches before the inverse path is
executed. BrowserUI evidence does not establish native HTTP action-API parity.
This is implementation evidence, not a screenshot-only model solve.
"""
import math,time
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.bandaged_rose_window_v3 import collar
M='bandaged_rose_window_v3'
MODEL='bandagedRoseWindowV3Model'

def snapshot(ui):
    return ui.read('({t:bandagedRoseWindowV3Model.started?Math.round(performance.now()-bandagedRoseWindowV3Model.startedAt):0,started:bandagedRoseWindowV3Model.started,terminal:bandagedRoseWindowV3Model.terminal,cracked:bandagedRoseWindowV3Model.cracked,successful:bandagedRoseWindowV3Model.successful,last:bandagedRoseWindowV3Model.lastTurn,ready:bandagedRoseWindowV3Model.ready,svg:document.querySelector(".current-rose svg").getBoundingClientRect().toJSON(),start:document.querySelector("#rose-start").getBoundingClientRect().toJSON(),seal:document.querySelector("#rose-certify").getBoundingClientRect().toJSON(),patches:[...document.querySelectorAll(".conservation-patch")].map(p=>({slot:Number(p.dataset.slot),rect:p.getBoundingClientRect().toJSON()})),buttons:[...document.querySelectorAll(".rose-turn-button")].map(b=>({disc:b.dataset.disc,direction:Number(b.dataset.direction),rect:b.getBoundingClientRect().toJSON()}))})')

def midpoint(r):return [r['x']+r['width']/2,r['y']+r['height']/2]

def inspect_glass(ui):
    """Lift visible paper covers; no piece identities select these clicks."""
    while (snap := snapshot(ui))['patches']:
        count=len(snap['patches']);x,y=midpoint(snap['patches'][0]['rect'])
        ui.send([{'mouse':{'left_click':[round(x),round(y)]}}])
        assert len(snapshot(ui)['patches'])==count-1,'glass inspection did not register'

def turn_actions(truth,move,snap):
    mode=truth.get('control_condition',{}).get('interaction','full')
    if mode=='simplified':
        b=next(x for x in snap['buttons'] if x['disc']==move['disc_id'] and x['direction']==move['direction'])
        return [{'mouse':{'left_click':[round(midpoint(b['rect'])[0]),round(midpoint(b['rect'])[1])]}}]
    disc=next(x for x in truth['rose']['discs'] if x['id']==move['disc_id']);r=snap['svg'];scale=min(r['width']/640,r['height']/510)
    ox=r['x']+(r['width']-640*scale)/2-180*scale;oy=r['y']+(r['height']-510*scale)/2-18*scale
    a=disc['handle_angle']*math.pi/180;cx,cy=disc['center'];radius=disc['handle_radius']
    def point(q):return dict(x=round(ox+(cx+math.cos(q)*radius)*scale),y=round(oy+(cy+math.sin(q)*radius)*scale))
    out=[{'mouse':{'move':list(point(a).values())}},{'mouse':{'buttons':{'left_down':True}}}]
    # One arc, sparse pointer delivery accepted. No browser focus shortcut.
    out.extend({'mouse':{'move':list(point(a+move['direction']*.90*k/5).values())}} for k in range(1,6))
    out.append({'mouse':{'buttons':{'left_up':True}}});return out

def solution(ui,truth,deadline_seconds=300,cadence_seconds=.20):
    last_image=time.monotonic();deadline=time.monotonic()+deadline_seconds
    inspect_glass(ui)
    snap=snapshot(ui)
    if not snap['started']:
        x,y=midpoint(snap['start']);ui.send([{'mouse':{'left_click':[round(x),round(y)]}}])
    moves=truth['solution_moves'];r=truth['rose'];mode=truth.get('control_condition',{}).get('interaction','full')
    paused=getattr(ui,'execution','live')=='paused';ids=['north','southwest','southeast']
    for n,move in enumerate(moves):
        d=ids.index(move['disc_id'])
        while True:
            assert time.monotonic()<deadline,'Oracle wall deadline exhausted'
            snap=snapshot(ui);assert not snap['terminal'],snap
            t=snap['t'];margin=.20 if not paused else .12
            # Current and short-horizon notch overlap; no future event tape read.
            if t-snap['last']>=r['cooldown_ms'] and abs(collar(r,d,t))<r['notch_half_width']-margin and (paused or abs(collar(r,d,t+250))<r['notch_half_width']-margin):break
            if paused:ui.send([])
            else:
                if time.monotonic()-last_image>=1.0:
                    ui.send([]);last_image=time.monotonic()
                time.sleep(cadence_seconds)
        ui.send(turn_actions(truth,move,snap));check=snapshot(ui)
        assert check['successful']==n+1 and not check['cracked'],check
    snap=snapshot(ui);assert snap['ready'],snap;x,y=midpoint(snap['seal']);ui.send([{'mouse':{'left_click':[round(x),round(y)]}}])
