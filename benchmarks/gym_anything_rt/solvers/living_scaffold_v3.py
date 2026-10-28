"""Privileged observation controller. UI adapters must send all inputs through HTTP."""
import math
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.living_scaffold_v3 import blossom, wind, clamp


def targets(world, state):
    result=[]
    for i,b in enumerate(state['bridges']):
        if b['docked']:
            continue
        if not b['fed']:
            desired=clamp((world['lanes'][i]['feed_s']+10-b['s'])*1.15,-32,25)
        else:
            desired=min(50,max(32,(world['final_length']-b['s'])*.8))
        accel=2.8*(desired-b['v'])
        angle=math.asin(clamp((accel*7/5-wind(world,i,state['tick']*world['dt_ms']))/world['parameters']['gravity'],-.25,.25))
        if b['fed'] and b['s']>380:
            # Aim the actual grown body into the visible moving mouth. Pod speed
            # remains physical; the controller does not catch, freeze or teleport.
            mouth=blossom(world,i,state['tick']*world['dt_ms']+300)
            angle=math.asin(clamp((mouth[1]-world['lanes'][i]['anchor_y']+world['radius']+world['skin_radius'])/world['final_length'],-.26,.26))
        others=[0. if a['docked'] else a['theta'] for j,a in enumerate(state['bridges']) if j!=i]
        angle+=world['parameters']['coupling']*sum(others)/max(1,len(others))
        result.append((i,clamp(angle,-world['max_angle'],world['max_angle'])))
    return result


def solve(ui, truth):
    """Existing HTTPUI protocol; Marionette is read-only privileged planning."""
    world=truth['world']
    def read():
        return ui.read('livingScaffoldV3Model.snapshot()')
    def screen(pt):
        box=ui.read("(()=>{const r=document.querySelector('.lsv-world').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()")
        return [round(box['x']+pt[0]*box['w']/world['width']),round(box['y']+pt[1]*box['h']/world['height'])]
    def click(pt):
        ui.send([{'mouse':{'left_click':pt}}])
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.living_scaffold_v3 import point
    # The shared inspection gesture is a visible input in both modes. This
    # controller still uses privileged physical observations, not image parsing.
    for i in range(len(world['lanes'])):
        click(screen(point(world,i,44,0,world['radius']+world['skin_radius'])))
    start=ui.read("(()=>{const r=document.querySelector('.lsv-start').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()")
    click(start)
    # Include the inspection requests in the declared max_steps=100 budget.
    for _ in range(99-len(world['lanes'])):
        s=read()
        if s['failed']:
            raise AssertionError(s)
        if all(b['docked'] for b in s['bridges']):
            return
        actions=[]
        for i,angle in targets(world,s):
            b=s['bridges'][i]
            simple=(truth.get('control_condition') or {}).get('interaction','full')=='simplified'
            endpoint=screen([760+i*70,300+angle*530] if simple else [760,world['lanes'][i]['anchor_y']+angle*530])
            if simple:
                actions.append({'mouse':{'left_click':endpoint}})
            else:
                from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.living_scaffold_v3 import point
                head=screen(point(world,i,b['length'],b['theta']))
                actions.extend([{'mouse':{'move':head,'buttons':{'left_down':True}}},
                                {'mouse':{'move':endpoint}}, {'mouse':{'buttons':{'left_up':True}}}])
        ui.send(actions)
        ui.wait(.16)
    raise AssertionError('Living bridge controller exceeded the declared 100-step budget')
