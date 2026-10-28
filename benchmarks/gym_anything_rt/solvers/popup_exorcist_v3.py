"""Popup Exorcist V3 browser solvers.

solve_visible() receives screenshots and ordinary input only, with no world,
clock, DOM, pane identities or state-file channel. Its evidence is separate
from solve(), which uses privileged geometry for task wiring diagnostics.
The inherited solve_http() is an oracle helper, not new V3 native-API evidence.
None of these helpers establishes human calibration or native API parity.
"""
from __future__ import annotations

import json
import time
import io
import csv
import subprocess
from pathlib import Path

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.popup_exorcist_v3 import hit, seal, pose, pane_at

MECHANIC_ID = "popup_exorcist_v3"


def _pixel_regions(rgb, color, tolerance=4):
    """Connected visible color regions, using horizontal screenshot runs."""
    import numpy as np
    mask=np.ones(rgb.shape[:2],dtype=bool)
    for channel,value in enumerate(color):
        band=rgb[:,:,channel]
        mask &= (band >= max(0,value-tolerance)) & (band <= min(255,value+tolerance))
    edges = np.diff(np.pad(mask.astype(np.int8), ((0,0),(1,1))), axis=1)
    starts = list(zip(*np.where(edges == 1)))
    ends = np.where(edges == -1)[1]
    runs = [(int(y),int(x),int(end)) for (y,x),end in zip(starts,ends)]
    parents = list(range(len(runs)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    previous, current, row = [], [], -2
    for i,(y,x,end) in enumerate(runs):
        if y != row:
            previous = current if y == row + 1 else []
            current, row = [], y
        for j in previous:
            _,a,b = runs[j]
            if a < end and x < b:
                parents[find(i)] = find(j)
        current.append(i)
    groups = {}
    for i,run in enumerate(runs):
        groups.setdefault(find(i),[]).append(run)
    regions = []
    for group in groups.values():
        x0=min(r[1] for r in group);x1=max(r[2] for r in group)
        y0=group[0][0];y1=group[-1][0]+1
        regions.append(dict(box=[x0,y0,x1,y1],area=sum(b-a for _,a,b in group),runs=group))
    return regions


def _pixel_targets(rgb, color):
    """Choose an interior point of a visibly exposed, full-size seal.

    The small forecast, text and flash outlines cannot meet these visible-size
    and fill tests. Filling glyph holes does not consult task geometry.
    """
    import numpy as np
    targets=[]
    for region in _pixel_regions(rgb,color):
        x0,y0,x1,y1=region['box'];w,h=x1-x0,y1-y0
        if not (24 <= min(w,h) and max(w,h) <= 85 and region['area'] >= w*h*.5):
            continue
        filled=np.zeros((h,w),dtype=bool)
        for y,a,b in region['runs']:
            filled[y-y0,a-x0:b-x0]=True
        # The question mark, cross and lock are visual glyphs inside the seal.
        # Fill their horizontal holes, keeping the observed outer silhouette.
        for row in filled:
            xs=np.flatnonzero(row)
            if xs.size:row[xs[0]:xs[-1]+1]=True
        interior=filled;clearance=0
        while interior.any():
            ys,xs=np.where(interior)
            nearest=int(np.argmin((xs-xs.mean())**2+(ys-ys.mean())**2))
            center=[int(x0+xs[nearest]),int(y0+ys[nearest])]
            clearance+=1
            padded=np.pad(interior,1)
            interior=np.logical_and.reduce([padded[dy:dy+h,dx:dx+w] for dy in range(3) for dx in range(3)])
        if clearance >= 10:
            targets.append(dict(point=center,box=region['box'],clearance_px=clearance,visible_pixels=region['area']))
    return sorted(targets,key=lambda target:-target['clearance_px'])


def _pixel_ocr(png, psm=11):
    """Local OCR of captured pixels; never a browser text/DOM query."""
    result=subprocess.run(['tesseract','stdin','stdout','--psm',str(psm),'tsv'],
        input=png,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    rows=list(csv.DictReader(io.StringIO(result.stdout.decode()),delimiter='\t'))
    return [row for row in rows if row.get('text','').strip()], result.stdout.decode()


def solve_visible(ui, mode, out_dir: Path, *, idle_seconds=0, max_wall_seconds=125):
    """Play live from raw screenshots, with no private-state input channel.

    ui exposes screenshot(), mouse, keyboard and wait_for_timeout() only. The
    regression test supplies a restricted facade that rejects other accesses.
    Every decision frame is saved verbatim. Playwright input is not native API
    evidence. Public mode selection and the visible color legend are known.
    """
    import numpy as np
    from PIL import Image
    if mode not in ('full','simplified'):raise ValueError(mode)
    out_dir.mkdir(parents=True,exist_ok=True)
    # The ready screen is stationary: retain its thin button borders losslessly
    # for OCR. Live decisions use the faster full-resolution JPEG path below.
    initial=ui.screenshot(path=str(out_dir/'initial.png'))
    initial_image=Image.open(io.BytesIO(initial)).convert('RGB')
    buttons=[r['box'] for r in _pixel_regions(np.asarray(initial_image),[119,145,161])
        if 70 <= r['box'][2]-r['box'][0] <= 180 and 30 <= r['box'][3]-r['box'][1] <= 50]
    start=None
    for x0,y0,x1,y1 in sorted(buttons):
        crop=initial_image.crop((x0+3,y0+3,x1-3,y1-3))
        crop=crop.resize((crop.width*4,crop.height*4));buf=io.BytesIO();crop.save(buf,format='PNG')
        words,tsv=_pixel_ocr(buf.getvalue(),7)
        if ''.join(word['text'].upper() for word in words)=='OPENDESKTOP':
            start=[(x0+x1)/2,(y0+y1)/2]
            (out_dir/'initial-ocr.tsv').write_text(tsv)
            break
    if start is None:raise AssertionError('OPEN DESKTOP not found in screenshot pixels')
    idle_started=time.monotonic()
    if idle_seconds:
        ui.wait_for_timeout(idle_seconds*1000)
        ui.screenshot(path=str(out_dir/'idle.jpg'),type='jpeg',quality=90)
    trace=dict(input_information='raw screenshots, public interaction mode and visible controls only',
        private_state_access=False,native_action_api=False,mode=mode,initial_idle_seconds=time.monotonic()-idle_started,
        start_from_ocr=start,actions=[],observations=[])
    ui.mouse.click(*start)
    started=time.monotonic();deadline=started+max_wall_seconds
    try:
        for frame in range(1000):
            if time.monotonic()>=deadline:raise AssertionError('visible solver reached its wall deadline')
            path=out_dir/f'frame-{frame:04d}.jpg'
            captured=time.monotonic();png=ui.screenshot(path=str(path),type='jpeg',quality=90)
            im=Image.open(io.BytesIO(png)).convert('RGB');rgb=np.asarray(im)
            # Look for a group of large colored glyphs, then read that visible
            # word. Thin verdict borders can fragment under JPEG compression.
            terminal=[]
            for color in ([184,239,196],[255,159,146]):
                glyphs=[r for r in _pixel_regions(rgb,color,tolerance=20) if
                    14 <= r['box'][2]-r['box'][0] <= 80 and 35 <= r['box'][3]-r['box'][1] <= 70
                    and r['area'] < (r['box'][2]-r['box'][0])*(r['box'][3]-r['box'][1])*.6]
                for anchor in glyphs:
                    group=[r for r in glyphs if abs(r['box'][1]-anchor['box'][1])<8]
                    if len(group)>=3:
                        box=[min(r['box'][0] for r in group),min(r['box'][1] for r in group),
                             max(r['box'][2] for r in group),max(r['box'][3] for r in group)]
                        if 100 < box[2]-box[0] < 400:terminal.append((box,color))
            if terminal:
                (x0,y0,x1,y1),color=terminal[0]
                crop=rgb[max(0,y0-10):min(im.height,y1+10),max(0,x0-10):min(im.width,x1+10)]
                # Isolate the observed verdict ink. The translucent overlay
                # otherwise lets underlying pane text confuse local OCR.
                ink=np.all(np.abs(crop.astype(np.int16)-color)<=20,axis=2)
                crop=Image.fromarray((~ink).astype(np.uint8)*255)
                crop=crop.resize((crop.width*4,crop.height*4));buf=io.BytesIO();crop.save(buf,format='PNG')
                text,tsv=_pixel_ocr(buf.getvalue(),7)
                label=''.join(row['text'].upper() for row in text)
                if 'PASS' in label or 'FAIL' in label:
                    trace['terminal']='PASS' if 'PASS' in label else 'FAIL'
                    trace['terminal_frame']=path.name;trace['wall_seconds']=time.monotonic()-started
                    (out_dir/'terminal-ocr.tsv').write_text(tsv)
                    (out_dir/'final.jpg').write_bytes(png)
                    if trace['terminal']!='PASS':raise AssertionError('visible browser ended in FAIL')
                    return trace
            close=_pixel_targets(rgb,[179,239,186])
            unknown=_pixel_targets(rgb,[198,185,142])
            services=_pixel_targets(rgb,[20,60,81])
            trace['observations'].append(dict(frame=path.name,wall_seconds=captured-started,
                haunted_seals=close,uninspected_seals=unknown,protected_seals=services))
            choice=close[0] if close else unknown[0] if unknown else None
            if choice:
                kind='close' if close else 'inspect'
                ui.mouse.click(*choice['point'],button='right' if kind=='inspect' and mode=='full' else 'left')
                if mode=='simplified':ui.keyboard.press('Space' if kind=='close' else 'i')
                trace['actions'].append(dict(kind=kind,frame=path.name,**choice,
                    wall_seconds=time.monotonic()-started,observation_to_input_ms=(time.monotonic()-captured)*1000))
            ui.wait_for_timeout(70)
        raise AssertionError('visible solver exhausted its frame bound')
    finally:
        (out_dir/'visible-trace.json').write_text(json.dumps(trace,indent=2)+'\n')


def choose(world, closed, ms, horizon=0, known_haunts=None):
    """Choose a generously exposed seal; never shoot through another pane."""
    for w in sorted(world["windows"], key=lambda w: w["z"], reverse=True):
        if w["id"] in closed or (w["trusted"] if known_haunts is None else w["id"] not in known_haunts):
            continue
        center = seal(w, world, ms + horizon)
        # Prefer a point with a 7px geometric reserve on all sides at delivery.
        for dx, dy in ((0, 0), (-10, 0), (10, 0), (0, 10), (0, -10)):
            p = [center[0] + dx, center[1] + dy]
            if all(hit(world, closed, [p[0]+a, p[1]+b], ms+horizon) == ("close", w["id"])
                   for a, b in ((0, 0), (7, 0), (-7, 0), (0, 7), (0, -7))):
                return p
    return None


def choose_inspection(world, closed, inspected, ms, horizon=0):
    """Geometry-only pointing; do not use the concealed role to choose a probe."""
    for w in sorted(world["windows"], key=lambda w: w["z"], reverse=True):
        if w["id"] in closed or w["id"] in inspected:
            continue
        x, y, _ = pose(w, ms + horizon)
        for fx, fy in ((.5,.75),(.15,.75),(.85,.75),(.5,.25),(.15,.25),(.85,.25)):
            p = [x + w["w"] * fx, y + w["h"] * fy]
            owners = [pane_at(world, closed, [p[0]+a,p[1]+b], ms+horizon)
                      for a,b in ((0,0),(7,0),(-7,0),(0,7),(0,-7))]
            if all(owner and owner["id"] == w["id"] for owner in owners):
                return p, w["id"]
    return None


def snapshot_expression():
    return "({ms:popupExorcistV3Model.startedAt===null?0:performance.now()-popupExorcistV3Model.startedAt,started:popupExorcistV3Model.startedAt!==null,closed:[...popupExorcistV3Model.closed],inspected:[...popupExorcistV3Model.inspected],misses:popupExorcistV3Model.misses,terminal:popupExorcistV3Model.terminal,events:popupExorcistV3Model.events,clock:GymAnythingRTTime.status(),box:(()=>{let r=document.querySelector('.pe2-canvas').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()})"


def solve_http(ui, truth, execution="live", budget=100):
    """ui.read is explicitly privileged read-only planning; send is frozen HTTP."""
    world = truth["world"]
    start = ui.read("(()=>{const r=document.querySelector('.pe2-start').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()")
    ui.send([{"mouse":{"left_click":start}}])
    while len(ui.rows) < budget - 1:
        s = ui.read(snapshot_expression())
        if s["terminal"]:
            return s
        if s['ms'] >= world['play_time_ms']:
            raise AssertionError('oracle exhausted the declared 120 task seconds')
        p = choose(world, set(s["closed"]), s["ms"], 0 if execution == "paused" else 60)
        if p is None:
            if execution == "paused":
                ui.send([])
            else:
                ui.wait(.6)
                ui.send([])
            continue
        box = s["box"]
        target = [box["x"] + p[0] * box["w"] / world["width"], box["y"] + p[1] * box["h"] / world["height"]]
        actions = [{"mouse":{"left_click":target}}]
        if (truth.get("control_condition") or {}).get("interaction", "full") == "simplified":
            actions.append({"keyboard":{"keys":["Space"]}})
        ui.send(actions)
    raise AssertionError("oracle did not finish inside the declared 100-request/120-task-second budget")


def solve(page, state_dir: Path, out_dir: Path, mechanic=MECHANIC_ID):
    """Headless wiring demonstration; roles are learned through safe inspection."""
    assert mechanic == MECHANIC_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    truth = json.loads((state_dir / "ground_truth.json").read_text())
    page.locator(".pe2-start").click()
    page.screenshot(path=str(out_dir / f"{MECHANIC_ID}-active.png"))
    paused = page.evaluate("GymAnythingRTTime.status().mode") == "paused"
    if paused:
        from tests.test_round_three_task_clocks import advance_window
        advance_window(page, 600)
    known_haunts, inspected, discoveries = set(), set(), []
    mode = (truth.get("control_condition") or {}).get("interaction", "full")
    deadline = time.monotonic() + 125
    while time.monotonic() < deadline:
        s = page.evaluate(snapshot_expression())
        if s["terminal"]:
            break
        horizon = 0 if paused else 45
        p = choose(truth["world"], set(s["closed"]), s["ms"], horizon, known_haunts)
        if p is not None:
            b = s["box"]
            page.mouse.click(b["x"] + p[0]*b["w"]/1040, b["y"] + p[1]*b["h"]/460)
            if mode == "simplified":
                page.keyboard.press("Space")
        else:
            candidate = choose_inspection(truth["world"],set(s["closed"]),inspected,s["ms"],horizon)
            if candidate:
                point, _ = candidate
                b = s["box"]
                page.mouse.click(b["x"]+point[0]*b["w"]/1040,b["y"]+point[1]*b["h"]/460,
                                 button="right" if mode == "full" else "left")
                if mode == "simplified":
                    page.keyboard.press("i")
                feedback = page.locator(".readout").inner_text()
                # Event identity supports geometric diagnostics, not the role
                # decision. That decision uses the rendered readout above.
                event = page.evaluate("popupExorcistV3Model.events.at(-1)")
                if event["kind"] == "inspect" and event["window_id"]:
                    inspected.add(event["window_id"])
                    if "HAUNTED PROCESS" in feedback:
                        known_haunts.add(event["window_id"])
                    discoveries.append(dict(event=event,visible_feedback=feedback))
                    if not (out_dir / "inspection-haunt.png").exists() and "HAUNTED PROCESS" in feedback:
                        if paused: advance_window(page, 600)
                        page.screenshot(path=str(out_dir / "inspection-haunt.png"))
                    if not (out_dir / "inspection-service.png").exists() and "PROTECTED SERVICE" in feedback:
                        if paused: advance_window(page, 600)
                        page.screenshot(path=str(out_dir / "inspection-service.png"))
        if paused:
            advance_window(page, 600)
        else:
            page.wait_for_timeout(140)
    else:
        raise AssertionError("headless wiring solve did not finish")
    page.locator(".pe2-verdict[data-status='passed']").wait_for(timeout=10000)
    page.screenshot(path=str(out_dir / f"{MECHANIC_ID}-pass.png"))
    (out_dir / "action-events.json").write_text(json.dumps(page.evaluate("popupExorcistV3Model.events"), indent=2))
    (out_dir / "discoveries.json").write_text(json.dumps(discoveries, indent=2))
