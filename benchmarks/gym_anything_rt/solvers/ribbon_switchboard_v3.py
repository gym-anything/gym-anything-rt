"""Task-specific oracle and screenshot-driven controllers.

solve() retains privileged planning. solve_visible() accepts screenshots and
mouse input only; it never reads task truth, DOM, model state or wind seeds.
The supplied transport must identify Playwright versus native API evidence.
"""
from __future__ import annotations

import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.ribbon_switchboard_v3 import ribbon_y, clamp


def solve(ui, truth, cadence=.18, lookahead_ms=320, wall_timeout_seconds=120):
    rect = ui.read("(() => {const r=document.querySelector('.rs2-canvas').getBoundingClientRect();return [r.x,r.y,r.width,r.height];})()")
    start = ui.read("(() => {const r=document.querySelector('.rs2-start').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()")
    simple = truth.get('control_condition', {}).get('interaction') == 'simplified'
    # Native paused observations can consume several seconds of wall time for
    # one fixed 400 ms task window. The caller declares its finite wall budget.
    deadline = time.monotonic()+wall_timeout_seconds
    p = truth['parameters']
    count = len(truth['lanes'])

    def screen(i, y):
        cy = (450-count*150)/2+i*150+75
        return [round(rect[0]+44*rect[2]/1100), round(rect[1]+(cy+y)*rect[3]/450)]

    # Restore the source game's local-light affordance using ordinary inputs.
    # No minimum scan count gates Energize or independent replay.
    for i in range(count):
        cy = (450-count*150)/2+i*150+75
        # Interior centers cover both ends without an exact-edge hit that can
        # round outside the canvas after CSS coordinate conversion.
        for x in range(200, 1001, 160):
            point = [rect[0]+x*rect[2]/1100, rect[1]+cy*rect[3]/450]
            ui.send([{'mouse': {'left_click' if simple else 'move': point}}])
    ui.send([{'mouse': {'left_click': start}}])

    while time.monotonic() < deadline:
        status = ui.read("({t:ribbonSwitchboardV3Model.t,bodies:ribbonSwitchboardV3Model.bodies,terminal:ribbonSwitchboardV3Model.terminal,grade:ribbonSwitchboardV3Model.grade})")
        if status['terminal']:
            # The asynchronous grade can still be in flight at the end.
            if not status.get('grade'):
                ui.wait(.05)
                continue
            assert status['grade']['passed'], status
            return status
        future = min(p['travel_ms'],status['t']+lookahead_ms)
        x = future/p['travel_ms']
        actions = []
        for lane, b in zip(truth['lanes'],status['bodies']):
            y = clamp(ribbon_y(lane['ribbons'][lane['target']],x,future,p),-65,65)
            end = screen(lane['id'],y)
            if simple:
                actions.append({'mouse':{'left_click':end}})
            else:
                actions.extend([{'mouse':{'move':screen(lane['id'],b['aim']),'buttons':{'left_down':True}}},
                                {'mouse':{'move':end}}, {'mouse':{'buttons':{'left_up':True}}}])
        ui.send(actions)
        ui.wait(cadence)
    raise AssertionError('Finite oracle deadline exceeded')


def solve_visible(ui, interaction, *, cadence=.025, wall_timeout_seconds=100):
    """Follow the revealed ribbon from screenshots using ordinary mouse input.

    ui.observe() returns an unmodified viewport PNG; ui.send()/wait() deliver
    literal input and wall-time waits. Palette and geometry constants describe
    the visible interface. No generated-world values enter this controller.
    """
    import io
    import numpy as np
    from PIL import Image

    if interaction not in ('full', 'simplified'):
        raise ValueError('unknown interaction surface')
    deadline = time.monotonic()+wall_timeout_seconds
    palette = np.array([[241,184,104],[121,207,201],[180,164,228],
                        [237,147,152],[170,198,133]], dtype=np.int16)

    def frame():
        pixels = np.asarray(Image.open(io.BytesIO(ui.observe())).convert('RGB'), dtype=np.int16)
        return pixels, time.monotonic()

    def mask(pixels, color, tolerance=8):
        return np.max(np.abs(pixels-np.asarray(color)), axis=2) <= tolerance

    def groups(values):
        return np.split(values, np.flatnonzero(np.diff(values)>1)+1) if len(values) else []

    pixels, captured = frame()
    # CSS scaling blends the one-pixel frame with its dark background.
    border = mask(pixels, [56,80,77], 22)
    rows = np.flatnonzero(border.sum(axis=1)>pixels.shape[1]*.40)
    edges = [int(round(float(g.mean()))) for g in groups(rows)]
    if len(edges) not in (2,4,6):
        raise AssertionError('cannot identify visible lane borders')
    centers = [(a+b)/2 for a,b in zip(edges[::2],edges[1::2])]
    ys, xs = np.nonzero(border[edges[0]-1:edges[0]+2])
    scale = (int(xs.max())-int(xs.min()))/1080
    origin = int(xs.min())-10*scale
    rail_x, source_x, end_x = origin+44*scale, origin+140*scale, origin+1040*scale

    def region(cy):
        return max(0,round(cy-70*scale)),min(pixels.shape[0],round(cy+71*scale))

    colors=[]
    for cy in centers:
        y0,y1=region(cy)
        sample=pixels[y0:y1,round(source_x-9*scale):round(source_x+10*scale)]
        counts=[int(mask(sample,c,12).sum()) for c in palette]
        if max(counts)<15:
            raise AssertionError('cannot identify the visible source color')
        colors.append(palette[int(np.argmax(counts))])

    for cy in centers:
        for x in range(200,1001,160):
            q=[origin+x*scale,cy]
            ui.send([{'mouse':{'left_click' if interaction=='simplified' else 'move':q}}])
    pixels, captured = frame()
    band_radii=[]
    # Learn the displayed tolerance width from the illuminated, unenergized
    # weave. This uses pixels rather than the hidden difficulty parameters.
    for cy,color in zip(centers,colors):
        y0,y1=region(cy)
        faint=np.rint(np.asarray([16,38,39])*.86+color*.14)
        widths=[]
        for x in np.arange(source_x+50*scale,end_x-30*scale,12*scale):
            column=pixels[y0:y1,round(x):round(x)+1]
            strong=np.flatnonzero(mask(column,color,20)[:,0])
            if not len(strong):continue
            middle=float(np.median(strong))
            dim=np.flatnonzero(mask(column,faint,3)[:,0])
            above=dim[(dim<middle-4*scale)&(dim>middle-25*scale)]
            below=dim[(dim>middle+4*scale)&(dim<middle+25*scale)]
            if len(above) and len(below):widths.append((below.max()-above.min())/2)
        if not widths:raise AssertionError('cannot learn the visible target-band width')
        band_radii.append(float(np.median(widths)))
    # The actual button fill locates Energize; no DOM coordinates are read.
    yy,xx=np.nonzero(mask(pixels,[236,209,162],4))
    if len(xx)<200:
        raise AssertionError('cannot locate the visible Energize button')
    ui.send([{'mouse':{'left_click':[float(np.median(xx)),float(np.median(yy))]}}])
    previous_targets=[None for _ in centers]
    decisions=[]

    def path(image,cy,color,x,reference,radius):
        y0,y1=region(cy)
        x0=max(round(source_x+2*scale),round(x-32*scale))
        x1=min(round(end_x-2*scale),round(x+33*scale))
        if x1<=x0:return None
        hits=mask(image[y0:y1,x0:x1],color,20)
        xx=[];yy=[]
        for column in range(hits.shape[1]):
            candidates=np.flatnonzero(hits[:,column])
            if len(candidates):
                xx.append(x0+column);yy.append(float(np.median(candidates))+y0)
        if len(xx)>=3 and min(abs(v-x) for v in xx)<=8*scale:
            # Nearby visible portions interpolate through a short crossing.
            coefficients=np.polyfit(np.asarray(xx)-x,np.asarray(yy),1)
            return float(coefficients[1])
        # A broader visible piece on each side supplies the strand's bend
        # through a prolonged overlap. It disambiguates which exposed band rim
        # belongs above or below the center without relying on a stale height.
        wide0=max(round(source_x+2*scale),round(x-110*scale))
        wide1=min(round(end_x-2*scale),round(x+111*scale))
        wide=mask(image[y0:y1,wide0:wide1],color,20)
        wx=[];wy=[]
        for column in range(wide.shape[1]):
            matches=np.flatnonzero(wide[:,column])
            if len(matches):
                wx.append(wide0+column-x);wy.append(float(np.median(matches))+y0)
        curve=None
        if len(wx)>=12:
            candidate=np.polyfit(wx,wy,3,w=1/(1+np.abs(wx)/(50*scale))**2)
            estimate=float(np.polyval(candidate,0))
            # Extrapolation from a single exposed side can be ill-conditioned.
            # Preserve the last observed strand when that fit jumps across it.
            if reference is None or abs(estimate-reference)<12*scale:
                curve=candidate
                reference=estimate
        if reference is None:return None
        # A strand can run underneath another for longer than this window.
        # Its broad live band remains visible beside the raised strands. Use
        # its learned width and recent position to identify an exposed rim.
        faint=np.rint(np.asarray([16,38,39])*.86+color*.14)
        x0=max(round(source_x+2*scale),round(x-12*scale))
        x1=min(round(end_x-2*scale),round(x+13*scale))
        if x1<=x0:return None
        hits=mask(image[y0:y1,x0:x1],faint,3)
        estimates=[]
        for column in range(hits.shape[1]):
            candidates=[]
            for segment in groups(np.flatnonzero(hits[:,column])):
                if len(segment)>=2:
                    candidates.extend([float(segment[0])+y0+radius,float(segment[-1])+y0-radius])
            predicted=float(np.polyval(curve,x0+column-x)) if curve is not None else reference
            if candidates:estimates.append(min(candidates,key=lambda y:abs(y-predicted)))
        return float(np.median(estimates)) if estimates else reference

    while time.monotonic()<deadline:
        pixels,captured=frame()
        # Inspect the visible verdict area without repeatedly scanning the
        # viewport background. Pixel delivery and processing stay in wall time.
        verdict=pixels[:round(centers[-1]+100*scale),
                       round(origin+210*scale):round(origin+1000*scale)]
        if np.max(mask(verdict,[180,212,152],6).sum(axis=1))>pixels.shape[1]*.25:
            return dict(completed=True,decisions=decisions,band_radii_screen=band_radii,
                        information_source='viewport PNG pixels only')
        if np.max(mask(verdict,[244,128,112],6).sum(axis=1))>pixels.shape[1]*.25:
            error=AssertionError('visible burn/failure stamp')
            error.decisions=decisions
            raise error
        y0,y1=region(centers[0])
        x0,x1=round(source_x),round(end_x)+1
        # The one-pixel guide can be split between two screen columns. Match
        # its actual blend against the dark lane instead of requiring opacity.
        alpha=(pixels[y0:y1,x0:x1]-np.asarray([16,38,39]))/np.asarray([151,144,132])
        guide=((np.max(alpha,axis=2)-np.min(alpha,axis=2)<.07)&
               (np.mean(alpha,axis=2)>.25)&(np.mean(alpha,axis=2)<1.1)).sum(axis=0)
        if int(guide.max())<25:
            ui.wait(cadence)
            continue
        contact_x=float(np.flatnonzero(guide==guide.max()).mean())+x0
        ahead=min(end_x-3*scale,contact_x+14*scale)
        actions=[];observed=[]
        for i,(cy,color) in enumerate(zip(centers,colors)):
            old=previous_targets[i]
            target=path(pixels,cy,color,ahead,old[0] if old is not None else None,band_radii[i])
            if target is None:
                observed.append(None)
                continue
            if old is not None:
                # A crossing can briefly mask a colored centerline. Bound an
                # isolated image estimate by the recently observed motion.
                limit=max(6*scale,25*scale*(captured-old[1]))
                target=max(old[0]-limit,min(old[0]+limit,target))
            raw_target=target
            previous_targets[i]=(target,captured)
            if old is not None and .02<captured-old[1]<1:
                # Track the source height across recent frames. This includes
                # both wind and motion through the weave, and compensates for
                # screenshot delivery plus the visibly damped actuator.
                drift=max(-25*scale,min(25*scale,(target-old[0])/(captured-old[1])))
                target+=drift*.7
            target=max(cy-64*scale,min(cy+64*scale,target))
            y0,y1=region(cy)
            rail=pixels[y0:y1,round(rail_x-12*scale):round(rail_x+13*scale)]
            knob_y=np.nonzero(mask(rail,[247,234,208],10))[0]
            if not len(knob_y):
                raise AssertionError('visible servo knob unavailable')
            knob=float(np.mean(knob_y))+y0
            q=[rail_x,target]
            if interaction=='simplified':actions.append({'mouse':{'left_click':q}})
            else:
                actions.extend([{'mouse':{'move':[rail_x,knob],'buttons':{'left_down':True}}},
                                {'mouse':{'move':q}},{'mouse':{'buttons':{'left_up':True}}}])
            observed.append(dict(lane=i,source_rgb=color.tolist(),target_screen_y=round(target,3),
                                 raw_target_screen_y=round(raw_target,3),knob_screen_y=round(knob,3)))
        ui.send(actions)
        decisions.append(dict(frame=len(decisions),contact_screen_x=round(contact_x,3),
                              lanes=observed))
        ui.wait(cadence)
    raise AssertionError('finite screenshot-controller deadline exceeded')
