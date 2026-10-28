"""Privileged feedback planner; all actual inputs use the caller's public API.

HTTPUI is the frozen downstream gateway in native validation. A separately
labelled headless Playwright adapter is allowed for implementation diagnostics.
No expression below mutates page state, focuses DOM nodes, or invokes the game.
"""
from __future__ import annotations

import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.motion_only_ghost_jigsaw_v2 import socket_pose, angle_error


def center(ui, selector):
    return ui.read(f'(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }})()')


def click(ui, point):
    return ui.send([{"mouse":{"left_click":[round(point[0]),round(point[1])]}}])


def solve(ui, truth):
    mode=truth["control_condition"]["interaction"]
    paused=getattr(ui,"execution_mode","live")=="paused"
    rect=ui.read('(() => { const r=document.querySelector("#loom-canvas").getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; })()')
    def screen(p):
        return [round(rect[0]+p[0]*rect[2]/970),round(rect[1]+p[1]*rect[3]/560)]
    def read():
        return ui.read('({s:motionOnlyGhostJigsawV2Model.physics,grade:motionOnlyGhostJigsawV2Model.serverGrade})')
    click(ui,center(ui,'#loom-start'))
    held_key=None
    # The declared task wall allowance is 600 s. Paused observations include
    # their 400 ms windows and native transport overhead; allow that existing
    # budget to serve all nine fragments, with the caller's 300-request cap.
    deadline=time.monotonic()+330
    left,right=center(ui,'#loom-left') if mode=='simplified' else None,center(ui,'#loom-right') if mode=='simplified' else None
    stitch=center(ui,'#loom-stitch') if mode=='simplified' else None
    for piece in truth['pieces']:
        while time.monotonic()<deadline:
            row=read();s=row['s']
            if piece['id'] in s['placed']: break
            assert not s['terminal'],row
            body=s['pieces'][piece['id']]
            if s['held'] is None:
                point=screen([body['x'],body['y']])
                if mode=='full': ui.send([{'mouse':{'move':point,'buttons':{'left_down':True}}}])
                else: click(ui,point)
                continue
            assert s['held']==piece['id'],s
            t=socket_pose(truth,piece['source_index'],s['tick'])
            p=truth['profile']
            distance=math.hypot(body['x']-t['x'],body['y']-t['y'])
            error=angle_error(t['angle'],body['angle'])
            # A drop is assessed against the physical body, not the pointer.
            if distance < p['position_tolerance']*.65 and abs(error)<p['angle_tolerance']*.55:
                if held_key:
                    ui.send([{'keyboard':{'keys_up':[held_key]}}]);held_key=None
                    continue
                if mode=='full': ui.send([{'mouse':{'buttons':{'left_up':True}}}])
                else: click(ui,stitch)
                continue
            # Predict a short amount of the visibly moving socket. Velocity is
            # available to the privileged planner; arrows/recent frames expose
            # it to an ordinary screenshot-only policy.
            horizon=.20 if not paused else .22
            goal=[t['x']+t['vx']*horizon,t['y']+t['vy']*horizon]
            actions=[]
            if mode=='full':
                future_error=angle_error(t['angle']+t['omega']*(.05 if not paused else .20),body['angle'])
                threshold=p['angle_tolerance']*.35 if not paused else 20
                desired=('d' if future_error>0 else 'a') if abs(future_error)>threshold else None
                if held_key and desired!=held_key: actions.append({'keyboard':{'keys_up':[held_key]}})
                if desired and desired!=held_key: actions.append({'keyboard':{'keys_down':[desired]}})
                held_key=desired
                actions.append({'mouse':{'move':screen(goal)}})
                ui.send(actions)
                ui.wait(.10)
            else:
                threshold=p['angle_tolerance']*.6 if not paused else 20
                if abs(error)>threshold and distance<110:
                    point=right if error>0 else left
                    ui.send([{'mouse':{'move':point,'buttons':{'left_down':True}}}])
                    if not paused: ui.wait(min(.35,max(.025,abs(error)/truth['rotation_speed']*.65)))
                    ui.send([{'mouse':{'buttons':{'left_up':True}}}])
                else:
                    click(ui,screen(goal));ui.wait(.12)
        else: raise AssertionError('Ghost loom feedback controller exceeded its declared deadline')
    if held_key: ui.send([{'keyboard':{'keys_up':[held_key]}}])
    ui.wait(.3)
    final=read()
    assert len(final['s']['placed'])==len(truth['pieces']),final
    return final
