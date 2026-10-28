"""Privileged construction oracle. Every input uses the downstream UI transport.

Read-only optics/DOM geometry supports planning, not a screenshot-only score.
The same oracle can use the frozen native HTTPUI or isolated headless wiring UI.
"""
from __future__ import annotations

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.cursor_constellation_hunt_v3 import target_at, target_velocity

MECHANIC_ID = "cursor_constellation_hunt_v3"


def _scene(ui):
    return ui.read("(() => {const m=cursorConstellationV3Model;const rect=e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height];};return {sim:m.sim.snapshot(),mode:m.mode,terminal:m.terminal,grade:m.grade,guides:[...document.querySelectorAll('[data-guide-current]')].map(e=>[+e.getAttribute('cx'),+e.getAttribute('cy')]),fields:[...document.querySelectorAll('.ccv2 canvas')].map(rect),start:rect(document.getElementById('ccv2-start')),seal:rect(document.getElementById('ccv2-seal'))};})()")


def _xy(rect, point):
    return [round(rect[0]+point[0]*rect[2]/320),round(rect[1]+point[1]*rect[3]/320)]


def _retarget(scene, targets):
    actions=[]
    for i,p in enumerate(targets):
        destination=_xy(scene["fields"][i],p)
        if scene["mode"]=="simplified":
            actions.append({"mouse":{"left_click":destination}})
        else:
            origin=_xy(scene["fields"][i],scene["sim"]["lenses"][i]["p"])
            actions.extend([{"mouse":{"move":origin}},
                            {"mouse":{"buttons":{"left_down":True}}},
                            {"mouse":{"move":destination}},
                            {"mouse":{"buttons":{"left_up":True}}}])
    return actions


def probe_response(ui):
    """Learn each guide's response through reversible visible preparation moves.

    DOM geometry/painted guide coordinates are read for this construction oracle;
    this helper is not evidence of screenshot-only or native-API equivalence.
    No guide angle or generated target is read to choose the initial focus.
    """
    scene = _scene(ui)
    if scene['sim']['origin'] is not None:
        raise ValueError('response probes require the safe preparation stage')
    count = len(scene['fields'])
    samples = []
    for point in ([160, 160], [200, 160], [160, 200]):
        ui.send(_retarget(scene, [point] * count))
        scene = _scene(ui)
        samples.append(scene['guides'])
    matrices, focus = [], []
    for index in range(count):
        base, horizontal, vertical = [sample[index] for sample in samples]
        a, c = [(horizontal[k]-base[k])/20 for k in (0, 1)]
        b, d = [(vertical[k]-base[k])/20 for k in (0, 1)]
        determinant = a*d-b*c
        if abs(determinant) < .9:
            raise RuntimeError('visible guide probe did not produce an invertible response')
        x, y = [2*(coordinate-128) for coordinate in base]
        focus.append([160-(d*x-b*y)/determinant,
                      160-(-c*x+a*y)/determinant])
        matrices.append([[a, b], [c, d]])
    return dict(matrices=matrices, initial_focus=focus, samples=samples)


def solve(ui, truth, update_ms=300, stale_ms=0, policy="feedback",
          initial_points=None, recovery_wait_ms=0, prepared_discovery=None):
    world=truth["world"]
    discovery=prepared_discovery or probe_response(ui)
    scene=_scene(ui)
    initial=initial_points or discovery['initial_focus']
    ui.send(_retarget(scene,initial))
    start=scene["start"]
    ui.send([{"mouse":{"left_click":[round(start[0]+start[2]/2),round(start[1]+start[3]/2)]}}])
    # Optional construction diagnostic: recover an exposure started at a legal
    # boundary pose. The wait and all corrections use the same UI transport.
    if recovery_wait_ms:
        ui.wait(recovery_wait_ms/1000)
    history=[]
    for _ in range(130):
        scene=_scene(ui)
        if scene["terminal"]:
            scene['discovery']=discovery
            return scene
        history.append(scene["sim"]["ms"])
        time_ms=scene["sim"]["ms"]
        observed=max(0,time_ms-stale_ms)
        lead=world["damping"]/world["spring"]+update_ms/2000
        if policy=="parked":
            targets=initial
        elif policy=="fixed":
            # Plausible observation-free controller learned on another seed.
            targets=[[160+70*__import__('math').cos(time_ms/2600+i),160+70*__import__('math').sin(time_ms/2600+i)] for i in range(len(initial))]
        else:
            targets=[[max(16,min(304,x+v*lead)) for x,v in zip(target_at(f,observed),target_velocity(f,observed))] for f in world["fields"]]
        ui.send(_retarget(scene,targets))
        ui.wait(update_ms/1000)
    raise RuntimeError("construction oracle exhausted its declared 130 correction cycles")


def fail_once(page, state_dir, out_dir, mechanic=MECHANIC_ID):
    """Legacy headless wiring hook, explicitly not native parity evidence."""
    del state_dir
    assert mechanic==MECHANIC_ID
    page.locator('#ccv2-seal').click()
    page.wait_for_function("cursorConstellationV3Model.grade !== null")
    page.screenshot(path=str(out_dir / 'failure.png'))
