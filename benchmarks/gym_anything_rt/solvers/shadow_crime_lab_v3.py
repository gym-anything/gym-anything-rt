"""Task-local solvability helpers, with evidence categories kept separate.

solve_native is an unexecuted native planning helper, not native parity proof.
The Playwright helper identifies the delayed response from rendered chart PNGs,
then uses privileged current camera/optical geometry for continuous tracking.
Neither helper is a screenshot-only model policy or a model score.
"""
from __future__ import annotations
import math
import time
from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.shadow_crime_lab_v3 import polygons, sample_hit, lamp_shift_at


def aim_point(state, bench_index, ms, lamp_shifts=None, specimen_index=None):
    bench=state["benches"][bench_index]
    index=bench["forged_index"] if specimen_index is None else specimen_index
    entry=polygons(state,bench,ms,lamp_shifts)[index]
    center=entry["center"]
    base=[sum(p[k] for p in entry["base"])/len(entry["base"]) for k in (0,1)]
    direction=[center[k]-base[k] for k in (0,1)]
    length=math.hypot(*direction)
    direction=[v/max(1,length) for v in direction]
    # Start in the exposed distal portion, clear of the specimen's base.
    radius=bench["objects"][index]["radius"]
    candidates=[[center[k]+direction[k]*radius*f for k in (0,1)] for f in (.45,.65,.25,0)]
    candidates.extend([[center[0]+radius*.5*math.cos(a*math.pi/4),center[1]+radius*.5*math.sin(a*math.pi/4)] for a in range(8)])
    for point in candidates:
        if sample_hit(state,bench,ms,point,lamp_shifts)==entry["id"]:
            return [round(v,4) for v in point]
    return [round(v,4) for v in candidates[0]]


def screen(box, state, bench, point):
    offset=110 if len(state["benches"])==1 else 220*bench
    return [round(box['x']+point[0]*box['width']/960),round(box['y']+(point[1]+offset)*box['height']/440)]


def inspect_lamps_playwright(page, public, output=None, advance=None, target_shift=50, diagnose=True):
    """Ordinary rail inputs; select the delayed row from visible pixels only.

    Clock/geometry reads plan the input placement. No forged identity is read
    when identifying the row. Fresh headless contexts belong to the caller.
    """
    from io import BytesIO
    from pathlib import Path
    from PIL import Image
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.shadow_crime_lab_v3 import lamp_at
    box=page.locator('#scv2-canvas').bounding_box()
    mode=public['control_condition']['interaction']
    for i,bench in enumerate(public['benches']):
        snapshot=page.evaluate('shadowCrimeLabV3Model.sim.snapshot()');ms=snapshot['t_ms']
        lamp=lamp_at(public,bench,ms)
        origin=[lamp[0]+lamp_shift_at(snapshot['lamp_shifts'][i],ms),lamp[1]]
        destination=[lamp[0]+target_shift,lamp[1]]
        if mode=='full':
            page.mouse.move(*screen(box,public,i,origin));page.mouse.down()
            page.mouse.move(*screen(box,public,i,destination));page.mouse.up()
        else:page.mouse.click(*screen(box,public,i,destination))
    duration=public['parameters']['lag_ms']+700
    if advance:advance(duration)
    else:page.wait_for_timeout(duration)
    if not diagnose:return []
    rows=[]
    for i,bench in enumerate(public['benches']):
        png=page.locator(f'#scv3-probe-{i}').screenshot()
        if output:
            Path(output).mkdir(parents=True,exist_ok=True)
            (Path(output)/f'table-{i+1}-visible-response.png').write_bytes(png)
        im=Image.open(BytesIO(png)).convert('RGB')
        # CSS scales the 220x88 canvas inside a one-pixel border. Early in
        # the saved test the delayed row stays on its baseline while the
        # ordinary rows have already followed the positive lamp shift.
        sx=(im.width-2)/220;sy=(im.height-2)/88
        scores=[]
        step=68/len(bench['objects'])
        for j in range(len(bench['objects'])):
            baseline=1+(11+j*step)*sy
            pixels=[]
            for x in range(round(1+79*sx),round(1+96*sx)):
                for y in range(max(1,round(baseline-step*.46*sy)),min(im.height-1,round(baseline+step*.46*sy))):
                    r,g,b=im.getpixel((x,y))
                    if r>115 and r>g*1.6 and g>b*1.2:pixels.append(y)
            if not pixels:raise AssertionError('No visible red response trace in specimen row')
            scores.append(abs(sum(pixels)/len(pixels)-baseline))
        choice=min(range(len(scores)),key=scores.__getitem__)
        rows.append(dict(bench=i,specimen_index=choice,specimen_id=bench['objects'][choice]['id'],
                         pixel_baseline_distances=scores))
    return rows


def select_lamp_record(page,bench,index):
    """Operate the visible history selector with ordinary mouse/keyboard input."""
    page.locator(f'#scv3-record-{bench}').click()
    page.keyboard.press('Home')
    for _ in range(index):page.keyboard.press('ArrowDown')
    page.keyboard.press('Enter')


def solve_playwright(page, public, choices, advance=None, honest=False, recover=False):
    """Visible Playwright inputs, privileged geometry for pursuing chosen caps."""
    mode=public['control_condition']['interaction'];correction=None;faded=False
    for _ in range(240):
        snap=page.evaluate('shadowCrimeLabV3Model.sim.snapshot()')
        if snap['terminal']:break
        if recover and correction is None and all(c['charge']>=1500 for c in snap['cameras']):
            correction=snap['t_ms']
        blank=correction is not None and snap['t_ms']<correction+3200
        if correction is not None and snap['t_ms']>=correction+2600:
            faded|=all(c['charge']==0 for c in snap['cameras'])
        box=page.locator('#scv2-canvas').bounding_box()
        for i,camera in enumerate(snap['cameras']):
            index=choices[i]['specimen_index']
            if honest:index=(index+1)%len(public['benches'][i]['objects'])
            lead=public['physics']['damping']/public['physics']['spring']*1000+100
            point=[530,194] if blank or honest and i>0 else aim_point(public,i,snap['t_ms']+lead,snap['lamp_shifts'][i],index)
            destination=screen(box,public,i,point)
            if mode=='full':
                page.mouse.move(*screen(box,public,i,camera['position']));page.mouse.down()
                page.mouse.move(*destination);page.mouse.up()
            else:page.mouse.click(*destination)
        if advance:advance(200)
        else:page.wait_for_timeout(120)
    else:raise AssertionError('Playwright controller exceeded feedback budget')
    for _ in range(100):
        outcome=page.evaluate('shadowCrimeLabV3Model.outcome||null')
        if outcome is not None:break
        page.wait_for_timeout(50)
    assert outcome is not None,'HTTP grader did not settle'
    if recover:assert correction is not None and faded,'Film correction did not reach the intended zero-charge state'
    return dict(outcome=outcome,snapshot=snap,correction_started_ms=correction,film_faded=faded)


def solve_native(ui, truth):
    geometry=ui.read('(() => {const r=document.querySelector("#scv2-canvas").getBoundingClientRect();const b=document.querySelector("#scv2-start").getBoundingClientRect();return {canvas:{x:r.x,y:r.y,width:r.width,height:r.height},start:[b.x+b.width/2,b.y+b.height/2]};})()')
    box=geometry['canvas'];ui.start_point=[round(v) for v in geometry['start']]
    ui.send([{'mouse':{'left_click':ui.start_point}}])
    mode=truth['control_condition']['interaction']
    for _ in range(160):
        current=ui.read('({snapshot:shadowCrimeLabV3Model.sim.snapshot(),outcome:shadowCrimeLabV3Model.outcome||null,error:shadowCrimeLabV3Model.error||null})')
        if current['snapshot']['terminal']:
            assert current['snapshot']['terminal']=='pass',current
            break
        acts=[]
        time_ms=current['snapshot']['t_ms']
        # Camera spring lag plus delivery and half the feedback interval.
        lead=truth['physics']['damping']/truth['physics']['spring']*1000+120
        if ui.execution_mode=='paused':lead=truth['physics']['damping']/truth['physics']['spring']*1000+120
        for i,camera in enumerate(current['snapshot']['cameras']):
            point=aim_point(truth,i,time_ms+lead,current['snapshot'].get('lamp_shifts',[[] for _ in truth['benches']])[i])
            destination=screen(box,truth,i,point)
            if mode=='full':
                origin=screen(box,truth,i,camera['position'])
                acts.extend([{'mouse':{'move':origin,'buttons':{'left_down':True}}}, {'mouse':{'move':destination}}, {'mouse':{'buttons':{'left_up':True}}}])
            else:acts.append({'mouse':{'left_click':destination}})
        ui.send(acts)
        if ui.execution_mode!='paused':ui.wait(.12)
    else:raise AssertionError('oracle exceeded its declared feedback budget')
    ui.wait(.4)
    # Verification is an asynchronous HTTP response even when task time is
    # frozen. Poll wall time after terminal success; do not send another input.
    for _ in range(100):
        outcome=ui.read('shadowCrimeLabV3Model.outcome||null')
        if outcome is not None:break
        time.sleep(.05)
    assert outcome and outcome.get('passed'),outcome
