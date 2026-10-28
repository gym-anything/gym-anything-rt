"""Privileged read-only planner. ALL inputs are literal model mouse/keyboard actions.

Pass an HTTPUI from the frozen native validation recipe for action-API evidence.
A separately labelled Playwright transport can exercise wiring, but proves no parity.
"""
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.funeral_ritual_v2 import wind


def solve(ui, truth):
    box = ui.read("(() => {const r=document.querySelector('#vigil-canvas').getBoundingClientRect();return [r.x,r.y,r.width,r.height];})()")
    mode = truth.get('control_condition', {}).get('interaction', 'full')
    def screen(p):
        return [box[0]+p[0]*box[2]/1000, box[1]+p[1]*box[3]/580]
    def click(p):
        ui.send([{'mouse': {'left_click': screen(p)}}])
    def drag(a,b):
        return [{'mouse': {'move': screen(a), 'buttons': {'left_down': True}}},
                {'action':'wait','time':.035},
                {'mouse': {'move': screen(b)}},
                {'action':'wait','time':.035},
                {'mouse': {'buttons': {'left_up': True}}}]
    click([500,250])
    if mode == 'simplified':
        click([500,314])
    else:
        for y in (267,297):
            for x in (439,499,559):
                click([x,y])
    click([truth['candles'][0]['x'],205])
    # The frozen paused protocol advances only .4s per observation and can
    # spend several wall-clock seconds delivering a multi-drag batch. Keep the
    # oracle within the existing 600s episode budget without ending a healthy
    # paused vigil at the former 100s planner limit.
    deadline = time.monotonic()+550
    while time.monotonic() < deadline:
        state = ui.read("(() => {const v=funeralVigilModel.physics;const s=funeralVigilModel.state;return {ms:v.ms,x:v.x,health:v.health,offered:v.offered,terminal:funeralVigilModel.terminal,failed:v.failed,active:v.active,flowerPoints:s.flowers.map(f=>FuneralVigilPhysics.flowerPoint(s,f.id,v.ms)),socketPoints:s.sockets.map(f=>FuneralVigilPhysics.socketPoint(s,f.id,v.ms))};})()")
        assert not state['failed'],state
        if state['terminal']:
            assert len(state['offered']) == len(truth['order']),state
            return
        assert state['active'], 'The lighting input did not reach the candle.'
        actions=[]
        for i,c in enumerate(truth['candles']):
            # Each subsequent gesture in a batch executes later. Compensate for
            # that delivery delay and the physical shield's approximately .4s lag.
            target=wind(truth,i,state['ms']+400+70*i)
            if mode=='simplified':
                actions.append({'mouse':{'left_click':screen([target,125])}})
            else:
                actions.extend(drag([state['x'][i],125],[target,125]))
        ui.send(actions)
        if len(state['offered']) < len(truth['order']):
            # Paused observations advance the approved .4s window after input;
            # use the resulting visible positions for the next gesture.
            state = ui.read("(() => {const v=funeralVigilModel.physics,s=funeralVigilModel.state;return {ms:v.ms,offered:v.offered,failed:v.failed,flowerPoints:s.flowers.map(f=>FuneralVigilPhysics.flowerPoint(s,f.id,v.ms)),socketPoints:s.sockets.map(f=>FuneralVigilPhysics.socketPoint(s,f.id,v.ms))};})()")
            assert not state['failed'],state
            k=len(state['offered']);f=truth['order'][k]
            # Visible destination has generous physical area; reading state is
            # privileged planning, not an alternate input or success injection.
            if mode=='full':
                ui.send(drag(state['flowerPoints'][f],state['socketPoints'][k]))
            else:
                click(state['flowerPoints'][f]);click(state['socketPoints'][k])
        elif state['ms']>=truth['ritual']['vigil_ms']:
            rect=ui.read("(() => {const r=document.querySelector('#vigil-seal').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()")
            ui.send([{'mouse':{'left_click':rect}}]);return
        ui.wait(.14)
    raise AssertionError('Vigil controller exceeded its finite planning budget')


SOLVERS={'funeral_ritual_v2':solve}
