"""Privileged oracle planning; every real action uses a supplied UI transport.

Native validation supplies the frozen downstream HTTP mouse/keyboard API.
Playwright checks are separately labelled and cannot establish action parity.
"""
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.rising_causeway_v2 import support, wind

MECHANIC_ID = "rising_causeway_v2"


def control(world, s, *, future=False):
    """State feedback. future=True discloses seeded future-motion planning.

    The diagnostic future=False uses current and 100-ms-old support positions
    and current courier velocity, rather than the seeded future trajectory.
    """
    p, t, x = world["parameters"], s["t"], s["x"]
    if s["flight"]:
        return 0.0, 0.0
    tx = x
    tile = support(world, s, tx, t)
    if tile is None:
        return 0.0, 0.0
    prev = support(world, s, max(0,tx-s['vx']*.1), max(0,t-100)) or tile
    prev2 = support(world, s, max(0,tx-s['vx']*.2), max(0,t-200)) or prev
    velocity = (3*tile[0]-4*prev[0]+prev2[0])/.2
    acceleration = (tile[0]-2*prev[0]+prev2[0])/.01
    if future:
        next_tile=support(world,s,min(world['end_x'],tx+s['vx']*.15),t+150) or tile
        symmetric_previous=support(world,s,max(0,tx-s['vx']*.15),max(0,t-150)) or tile
        velocity=(next_tile[0]-symmetric_previous[0])/.3
        acceleration=(next_tile[0]-2*tile[0]+symmetric_previous[0])/.0225
    force = (tile[0]-s['y'])*8 + (velocity-s['vy'])*4 + p['drag']*velocity + max(-2,min(2,acceleration)) - wind(world,t)
    return 0.0, max(-1,min(1,force/p["steering"]))


def landing_model(world, s, *, forecast=None):
    """Affine landing map, independent of subsequent controls.

    Native oracle planning reads the seeded future. A diagnostic may instead
    supply the announced route/wind forecast; no future seed is then read.
    """
    p, dt = world['parameters'], world['tick_ms']/1000
    y, vy, gain, velocity_gain = s['y'], s['vy'], 0.0, world['spring_vy']
    z, vz, n = s['z'], world['spring_vz'], 0
    while True:
        n += 1
        t = s['t'] + n * world['tick_ms']
        disturbance = forecast['wind'][n] if forecast is not None else wind(world, t)
        vy += (world['air_wind'] * disturbance - world['air_drag'] * vy) * dt
        velocity_gain *= 1-world['air_drag']*dt
        y += vy*dt; gain += velocity_gain*dt
        vz -= world['gravity']*dt; z += vz*dt
        if vz < 0 and z <= p['stair_height']:
            break
    x = s['x'] + (s['vx'] + world['spring_vx'])*dt*n
    target = forecast['centre'](x, n) if forecast is not None else support(world,s,x,t)[0]
    clearance = p['landing_half_width']-world['radius']
    return dict(x=x, base_y=y, gain=gain, target=target, flight_ms=n*world['tick_ms'],
                interval=[max(-1,(target-clearance-y)/gain),min(1,(target+clearance-y)/gain)])


def launch_aim(world, s):
    plan = landing_model(world, s)
    if not world['delivery_start']+world['radius'] <= plan['x'] <= world['end_x']+.8-world['radius']:
        raise ValueError('launch misses the longitudinal delivery bay')
    if plan['interval'][0] > plan['interval'][1]:
        raise ValueError('landing is outside spring steering range')
    return max(-1,min(1,(plan['target']-plan['base_y'])/plan['gain']))


def rect(ui, selector):
    return ui.read(f'(() => {{const r=document.querySelector({selector!r}).getBoundingClientRect();return [r.x,r.y,r.width,r.height];}})()')


def centre(r):
    return [r[0]+r[2]/2,r[1]+r[3]/2]


def click(ui, point):
    ui.send([{"mouse": {"left_click": list(point)}}])


def solve_http(ui, truth, *, interval=.20):
    """No DOM focus, synthetic input, physics calls or page mutations."""
    simple = (truth.get("control_condition") or {}).get("interaction") == "simplified"
    scene = rect(ui, "#rcv2-scene")
    def canvas_point(x,y):
        return [scene[0]+x/920*scene[2],scene[1]+y/520*scene[3]]
    if simple:
        red=centre(rect(ui,"#rcv2-red")); stair=centre(rect(ui,"#rcv2-far")); blue=centre(rect(ui,"#rcv2-prime"))
    else:
        red=canvas_point(248,448); stair=canvas_point(483 if truth["world"]["mirror"]==1 else 423,448); blue=canvas_point(665,448)
    for _ in range(3): click(ui,red)
    click(ui,stair); click(ui,blue)
    pad=rect(ui,"#rcv2-pad")
    rail=rect(ui,"#rcv2-launch")
    click(ui,centre(rect(ui,"#rcv2-start")))
    deadline=time.monotonic()+75
    while time.monotonic()<deadline:
        snapshot=ui.read('({physics:risingCausewayV2Model.physics,terminal:risingCausewayV2Model.terminal,grade:risingCausewayV2Model.grade})')
        s=snapshot['physics']
        if snapshot['terminal']:
            assert s['completed'] and not s['failed'],snapshot
            return
        if s['flight']:
            # A paused native HTTP request collects the next observation
            # window; a wall-clock sleep alone leaves flight frozen.
            ui.send([])
            ui.wait(interval)
            continue
        if s['loaded'] and s['primed']:
            aim=launch_aim(truth['world'],s)
            target=[round(rail[0]+rail[2]*(.5+.42*aim)),round(rail[1]+rail[3]/2)]
            if simple:
                click(ui,target)
            else:
                start=[round(rail[0]+rail[2]*(.5+.42*s['aim'])),target[1]]
                ui.send([{'mouse':{'move':start,'buttons':{'left_down':True}}},
                         {'mouse':{'move':target}}, {'mouse':{'buttons':{'left_up':True}}}])
            ui.wait(interval)
            continue
        ux,uy=control(truth['world'],s,future=True)
        target=[pad[0]+pad[2]*(.5+.36*uy),pad[1]+pad[3]*(.5-.36*ux)]
        if simple:
            click(ui,target)
        else:
            start=[pad[0]+pad[2]*(.5+.36*s['uy']),pad[1]+pad[3]*(.5-.36*s['ux'])]
            ui.send([{'mouse':{'move':start,'buttons':{'left_down':True}}},
                     {'mouse':{'move':target}}, {'mouse':{'buttons':{'left_up':True}}}])
        ui.wait(interval)
    raise AssertionError('Causeway oracle deadline exceeded')
