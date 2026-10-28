"""Privileged geometric planning for implementation checks, not an agent score.

The simulator helper produces replay fixtures. ``solve_http`` is a task policy
for the existing frozen HTTPUI; it verifies the actual sandbox direct route.
``solve`` exercises the same primitive-action policy through isolated headless
mouse events. Headless evidence is not native action-space parity.
"""
from __future__ import annotations

import math
import colorsys
import copy
import json
from pathlib import Path
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.branch_repair_v3 import Simulation, position
from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.branch_repair_v3 import PROFILES

DELAYS = {1: 550, 2: 450, 3: 340, 4: 260, 5: 200}
PORT_COLOURS = [
    ['f7d789','aacddd','76b4ed','a2a5df','d79dce'],
    ['e9df86','9ed3ac','55bfa2','62c5d8','839ddb'],
    ['ffc49b','d4b396','dda178','dd898d','bd93bc'],
]


def _pixel_components(mask, minimum=1):
    """Connected pixel sets; optional image dependencies stay out of grading."""
    import numpy as np
    remaining = set(map(tuple, np.argwhere(mask)))
    components = []
    while remaining:
        first = remaining.pop()
        queue, component = [first], [first]
        while queue:
            y, x = queue.pop()
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                neighbour = y+dy, x+dx
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
                    component.append(neighbour)
        if len(component) >= minimum:
            components.append(np.asarray(component))
    return components


def _pixel_runs(indices, *, gap=0, minimum=1):
    """Inclusive runs of integer pixel indices."""
    runs = []
    for i in indices:
        if runs and i == runs[-1][1]+1:
            runs[-1][1] = int(i)
        else:
            runs.append([int(i), int(i)])
    merged = []
    for lo, hi in runs:
        if hi-lo+1 < minimum:
            continue
        if merged and lo-merged[-1][1]-1 <= gap:
            merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    return merged


def pixel_layout(image):
    """Calibrate the four visible pane rectangles from screenshot pixels.

    No DOM boxes, contract geometry, motion seeds or hidden state are read.
    The native pane dimensions are the documented fixed projection scales.
    Calibration is retained only while the screenshot size is unchanged.
    """
    import numpy as np
    rgb = np.asarray(image.convert('RGB')).astype(int)
    caption = np.max(abs(rgb-[25, 50, 59]), axis=2) <= 4
    bands = _pixel_runs(np.flatnonzero(caption.sum(axis=1) > 150))
    panels = []
    for lo, hi in bands:
        if not (20 <= hi-lo <= 35 and lo < image.height*.85):
            continue
        row = lo+int(np.argmax(caption[lo:hi+1].sum(axis=1)))
        # JPEG ringing can split a flat caption into several long runs.
        # Discard isolated compression pixels before bridging tiny gaps;
        # the actual gap between panels remains much wider.
        for left, right in _pixel_runs(np.flatnonzero(caption[row]), gap=3, minimum=16):
            if right-left < 100:
                continue
            top = hi+1
            base = np.max(abs(rgb[top:, left:right+1]-[9, 24, 33]), axis=2) <= 2
            stops = np.flatnonzero(base.mean(axis=1) < .12)
            bottom = top+next((a for a,b in _pixel_runs(stops) if a > 25 and b-a >= 5), len(base))
            panels.append(dict(x=left, y=top, width=right-left+1, height=bottom-top))
    if len(panels) > 4:
        # The header gradient can cross the caption colour. The actual XY
        # caption is the unique wide rectangle; its three registered side
        # captions are right of it and no higher than it.
        wide = [p for p in panels if p['width'] > image.width*.55]
        if len(wide) == 1:
            main = wide[0]
            panels = [main,*[p for p in panels if p['x'] > main['x']+main['width'] and p['y'] >= main['y']]]
    if len(panels) != 4:
        raise ValueError('four unobscured visible panes required for calibration')
    main = max(panels, key=lambda p:p['width'])
    depth = sorted((p for p in panels if p is not main), key=lambda p:p['y'])
    # The three linked side panes share the same grid row size; the final
    # operating-plane boundary aligns with their last visible border.
    depth[2]['height'] = depth[1]['height']
    # A one-pixel border can be located even when the footer shares parts of
    # the pane background. Side panes have fractional CSS heights, so adding
    # their rounded heights would introduce a scaling error in the XY plane.
    edge = np.max(abs(rgb[main['y']:,main['x']:main['x']+main['width']]-[37,60,69]),axis=2)<=3
    boundaries=np.flatnonzero(edge.mean(axis=1)>.95)
    boundaries=boundaries[boundaries>50]
    if not len(boundaries):
        # JPEG chroma subsampling changes a thin border more than the flat
        # caption. Locate complete border rows at a wider colour tolerance;
        # do not infer canvas height from content or read a private rectangle.
        # Retain the exact lossless calibration path above when it succeeds.
        for panel in panels:
            patch=rgb[panel['y']:,panel['x']:panel['x']+panel['width']]
            compressed_edge=np.max(abs(patch-[37,60,69]),axis=2)<=12
            rows=np.flatnonzero(compressed_edge.mean(axis=1)>.95)
            rows=rows[rows>50]
            if not len(rows):
                raise ValueError('visible pane border could not be calibrated')
            panel['height']=int(rows[0])
    else:
        main['height']=int(boundaries[0])
    return dict(size=list(image.size), xy=main, xz=depth[0], yz=depth[1], mesh=depth[2])


def pixel_controls(image, layout):
    """Locate ready-screen controls, including V3's optional section lens."""
    import numpy as np
    rgb=np.asarray(image.convert('RGB')).astype(int)
    start=layout['xy']['y']+layout['xy']['height']+5
    patch=rgb[start:]
    mask=(np.max(abs(patch-[25,51,62]),axis=2)<=4) | (np.max(abs(patch-[241,211,150]),axis=2)<=4)
    row=int(np.argmax(mask.sum(axis=1)))
    runs=[(a,b) for a,b in _pixel_runs(np.flatnonzero(mask[row])) if b-a>45]
    if len(runs) not in (4,5):
        raise ValueError('ready-screen buttons could not be calibrated')
    buttons={}
    names=('begin','stitch','cut','inspect','submit') if len(runs)==5 else ('begin','stitch','cut','submit')
    for name,(left,right) in zip(names,runs):
        column=int((left+right)/2)
        bands=[(a,b) for a,b in _pixel_runs(np.flatnonzero(mask[:,column])) if a<=row<=b]
        lo,hi=bands[0]
        buttons[name]=[round((left+right+1)/2),round(start+(lo+hi+1)/2)]
    return buttons


def pixel_observation(image, *, layout=None, level=None):
    """Measure visible port centres, glyphs and pink bridge pixels.

    Receives an image only. Exact scene geometry is never a fallback. A
    rejected measurement is explicit rather than silently reading page state.
    """
    import numpy as np
    layout = layout or pixel_layout(image)
    if list(image.size) != layout['size']:
        raise ValueError('viewport changed; recalibrate from a visible frame')
    rgb = np.asarray(image.convert('RGB')).astype(int)
    pane = layout['xy']
    left, top = pane['x'], pane['y']
    crop = rgb[top:top+pane['height'], left:left+pane['width']]
    pink = np.max(abs(crop-[215, 161, 164]), axis=2) <= 18
    bridges = []
    for blob in _pixel_components(pink, minimum=40):
        middle = np.mean(blob, axis=0)
        bridges.append(dict(point=[float(middle[1]+left),float(middle[0]+top)],
                            world=[float(middle[1]/pane['width']*960),float(middle[0]/pane['height']*490)],
                            pixels=len(blob)))
    if image.format == 'JPEG':
        count = PROFILES[level]['candidate_count'] if level is not None else None
        ports = jpeg_ports(image, layout, candidate_count=count,
                           port_radius=PROFILES[level]['port_radius'] if level is not None else None)
        if level is not None:
            selected = visible_selection(image, layout, ports, PROFILES[level]['port_radius'])
            for port in ports:
                port['selected'] = any(port is p for p in selected)
        return dict(layout=layout, ports=ports, bridges=bridges,
                    signals=pixel_signals(image,layout,level) if level is not None else [],
                    depths=jpeg_depths(image, layout,
                    incoming_ports=ports if level is not None else None,
                    front_count=PROFILES[level]['front_count'] if level is not None else None))
    filled = np.max(abs(crop-[17, 47, 61]), axis=2) <= 5
    ports = []
    for blob in _pixel_components(filled, minimum=60):
        low, high = blob.min(axis=0), blob.max(axis=0)
        h, w = high-low+1
        if not (7 <= w <= 80 and 7 <= h <= 80):
            continue
        y, x = (low+high+1)/2
        # Interior blobs propose candidates; correspondence colours identify
        # ports without encoding which continuation is correct.
        # A passing signal may split a circle's interior. Fit the surviving
        # coloured circumference instead of centring either interior fragment.
        y0,y1=max(0,int(y-60)),min(len(crop),int(y+61))
        x0,x1=max(0,int(x-60)),min(len(crop[0]),int(x+61))
        ring = crop[y0:y1, x0:x1]
        fits=[]
        for lane,colours in enumerate(PORT_COLOURS):
            for glyph,hex_colour in enumerate(colours):
                colour=[int(hex_colour[i:i+2],16) for i in (0,2,4)]
                colour_distance=np.max(abs(ring-colour),axis=2)
                pixels=np.argwhere(colour_distance<=6)
                if len(pixels)<10:
                    continue
                xs=(pixels[:,1]+x0+.5)*960/pane['width']
                ys=(pixels[:,0]+y0+.5)*490/pane['height']
                # Translate to keep the circle fit well conditioned.
                ox,oy=float(xs.mean()),float(ys.mean());xs-=ox;ys-=oy
                coefficients=np.linalg.lstsq(np.column_stack((2*xs,2*ys,np.ones(len(xs)))),xs*xs+ys*ys,rcond=None)[0]
                cx,cy=coefficients[:2];radius=math.sqrt(max(0,coefficients[2]+cx*cx+cy*cy))
                residual=float(np.sqrt(np.mean((np.hypot(xs-cx,ys-cy)-radius)**2)))
                centre=[cx+ox,cy+oy]
                distance=math.dist(centre,[x*960/pane['width'],y*490/pane['height']])
                if 12<=radius<=22 and residual<1.2 and distance<radius:
                    fits.append((int(colour_distance.min()),-int((colour_distance<=2).sum()),distance,residual,lane,glyph,centre))
        if not fits:
            continue
        _,_,_,residual,lane,glyph,centre=min(fits)
        x,y=centre[0]*pane['width']/960,centre[1]*pane['height']/490
        if any(p['lane']==lane and p['glyph']==glyph and math.dist(p['world'],centre)<1 for p in ports):
            continue
        ports.append(dict(point=[float(x+left),float(y+top)], glyph=glyph,lane=lane,
                          world=[float(x/pane['width']*960),float(y/pane['height']*490)],
                          box=[int(low[1]+left),int(low[0]+top),int(w),int(h)]))
    depths = {}
    for view in ('xz', 'yz', 'mesh'):
        pane = layout[view]
        patch = rgb[pane['y']:pane['y']+pane['height'],pane['x']:pane['x']+pane['width']]
        markers = []
        for lane,colours in enumerate(PORT_COLOURS):
          for glyph,hex_colour in enumerate(colours):
            colour=[int(hex_colour[i:i+2],16) for i in (0,2,4)]
            marker = np.max(abs(patch-colour), axis=2) <= 6
            for blob in _pixel_components(marker, minimum=6):
                low, high = blob.min(axis=0), blob.max(axis=0)
                height,width = high-low+1
                if not (3 <= width <= 15 and 3 <= height <= 17 and .45 <= width/height <= 1.9):
                    continue
                y,x = (low+high+1)/2
                markers.append(dict(point=[float(x/pane['width']*260),float(y/pane['height']*145)],incoming=glyph==0,lane=lane,glyph=glyph))
        depths[view] = markers
    return dict(layout=layout, ports=ports, bridges=bridges, depths=depths,
                signals=pixel_signals(image,layout,level) if level is not None else [])


def pixel_signals(image, layout, level):
    """Measure the filled gold discs, excluding port rims and small glyphs."""
    import numpy as np
    pane=layout['xy'];rgb=np.asarray(image.convert('RGB')).astype(int)
    patch=rgb[pane['y']:pane['y']+pane['height'],pane['x']:pane['x']+pane['width']]
    red,green,blue=patch[:,:,0],patch[:,:,1],patch[:,:,2]
    solid=(red>220)&(green>185)&(blue<180)
    solid[:,:round(30*pane['width']/960)]=False
    # A signal has a solid eight-unit core; the source diamond and the
    # two-unit luminous rims cannot survive this image-only erosion.
    for _ in range(max(1,round(5*min(pane['width']/960,pane['height']/490)))):
        padded=np.pad(solid,1)
        solid=solid&padded[:-2,1:-1]&padded[2:,1:-1]&padded[1:-1,:-2]&padded[1:-1,2:]
    nominal={1:[245],2:[155,345],3:[88,245,402]}[PROFILES[level]['front_count']]
    measured=[]
    for blob in _pixel_components(solid,minimum=3):
        y,x=np.mean(blob,axis=0)+.5
        centre=[float(x/pane['width']*960),float(y/pane['height']*490)]
        lane=min(range(len(nominal)),key=lambda i:abs(centre[1]-nominal[i]))
        measured.append(dict(lane=lane,world=centre,measurement='visible filled gold core'))
    # Multiple unresolved proposals in a lane do not become an urgency
    # estimate. The rest of the observation remains independently usable.
    return [s for s in measured if sum(q['lane']==s['lane'] for q in measured)==1]


def pixel_stations(observation, level, *, allow_partial=False):
    """Register port glyphs and depth across the visible projections."""
    profile = PROFILES[level]
    if allow_partial:
        # An unreadable lane must not discard a separately observable
        # repair opportunity in another lane. Strict callers retain the
        # original complete-observation rejection behavior below.
        rows=[]
        for lane in range(profile['front_count']):
            local={**observation,'ports':[p for p in observation['ports'] if p['lane']==lane]}
            try:rows.extend(pixel_stations(local,level))
            except ValueError:continue
        return sorted(rows,key=lambda s:(s['column'],s['lane']))
    nominal_y = {1:[245],2:[155,345],3:[88,245,402]}[profile['front_count']]
    stations = []
    for source in (p for p in observation['ports'] if p['glyph']==0):
        lane = source['lane']
        column = min(range(3),key=lambda i:abs(source['world'][0]-(165+300*i)))
        outlets = [p for p in observation['ports'] if p['glyph'] and p['lane']==lane and
                   50 <= p['world'][0]-source['world'][0] <= 102 and
                   abs(p['world'][1]-source['world'][1]) <= 56]
        if len(outlets) != profile['candidate_count'] or len({p['glyph'] for p in outlets}) != len(outlets):
            raise ValueError('open outlet circles are overlapped or unreadable')
        # Gold marks incoming ports in depth; it does not mark a correct outlet.
        sx = source['world'][0]*.25+10
        nominal_z = {1:[0],2:[-40,40],3:[-60,0,60]}[profile['front_count']][lane]
        matches = [(abs(x['point'][0]-sx),x['point'][1])
                   for x in observation['depths']['xz'] if x['incoming'] and x['lane']==lane and abs(x['point'][0]-sx)<3
                   if abs(x['point'][1]-(72+nominal_z*.45))<10]
        if not matches:
            raise ValueError('incoming depth could not be registered from pixels')
        depth = min(matches)[1]
        continuations = []
        for port in outlets:
            px = port['world'][0]*.25+10
            py = port['world'][1]*.46+15
            z=(depth-72)/.45
            projections=dict(xz=[px,depth],yz=[py,depth],mesh=[18+port['world'][0]*.22+z*.18,16+port['world'][1]*.23-z*.16])
            fits=[];column_match=False
            for view,target in projections.items():
                match=[math.dist(x['point'],target) for x in observation['depths'][view]
                       if x['lane']==lane and x['glyph']==port['glyph'] and math.dist(x['point'],target)<3]
                if match:
                    fits.append(min(match))
                    if view in ('xz','mesh'):column_match=True
            # XZ and the oblique view retain the column coordinate. YZ alone
            # may align with the same glyph from a different station. A
            # visible marker in either column-preserving view suffices; the
            # other panes can have real point overlap.
            if column_match:
                continuations.append((len(fits),sum(fits),port['glyph'],port))
        if len(continuations)>1:
            # JPEG colour fragments can make a second glyph appear at an
            # orthogonal marker. A unique candidate registered in all three
            # linked views resolves that weaker two-view correspondence.
            complete=[candidate for candidate in continuations if candidate[0]==3]
            if len(complete)==1:continuations=complete
        if len(continuations)!=1:
            raise ValueError('depth continuation is not uniquely measurable')
        stations.append(dict(key=f'{lane}:{column}',lane=lane,column=column,
                             source=source, continuation=continuations[0][3], outlets=outlets))
    return sorted(stations,key=lambda s:(s['column'],s['lane']))


def _spline_basis(ms, span, indices):
    u = max(0,ms)/span
    n = math.floor(u)
    f = u-n
    smooth = f*f*(3-2*f)
    return [((1-smooth) if i==n else smooth if i==n+1 else 0) for i in indices]


def _bounded_linear_range(rows, values, epsilon, future):
    """Tiny bounded LP by vectorized vertices, normally two or three knots.

    Unknown knot values stay in [-1,1]. Each measurement supplies an interval,
    not an ideal centre. The result contains all values consistent with it.
    """
    import itertools
    import numpy as np
    rows, values, future = np.asarray(rows), np.asarray(values), np.asarray(future)
    dimension = len(future)
    a = np.concatenate((rows,-rows,np.eye(dimension),-np.eye(dimension)))
    b = np.concatenate((values+epsilon,-values+epsilon,np.ones(dimension),np.ones(dimension)))
    combinations = list(itertools.combinations(range(len(b)),dimension))
    matrices = a[np.asarray(combinations)]
    determinants = np.linalg.det(matrices)
    good = np.abs(determinants)>1e-12
    points = np.linalg.solve(matrices[good],b[np.asarray(combinations)[good]][:,:,None])[:,:,0]
    feasible = np.all(points@a.T <= b+1e-8,axis=1)
    if not feasible.any():
        raise ValueError('pixels fall outside the declared measurement interval')
    extrema = points[feasible]@future
    return float(extrema.min()),float(extrema.max())


def spline_pixel_prediction(samples, target_ms, *, base, amplitude, span_ms, epsilon=1.0):
    """Causal interval prediction from recent measured pixels only."""
    indices = sorted({i for ms,_ in samples for i in (int(ms//span_ms),int(ms//span_ms)+1)} |
                     {int(target_ms//span_ms),int(target_ms//span_ms)+1})
    rows = [_spline_basis(ms,span_ms,indices) for ms,_ in samples]
    values = [(value-base)/amplitude for _,value in samples]
    lo,hi = _bounded_linear_range(rows,values,epsilon/amplitude,_spline_basis(target_ms,span_ms,indices))
    return dict(point=base+amplitude*(lo+hi)/2, error=amplitude*(hi-lo)/2)


def _linear_maximum(rows, bounds, objective):
    """Two-phase simplex for a small bounded polytope, variables >= 0.

    Used only by the image diagnostic. Infeasibility remains an explicit
    measurement failure; no generated geometry is substituted for pixels.
    """
    import numpy as np
    a, b, c = np.asarray(rows, float), np.asarray(bounds, float), np.asarray(objective, float)
    m, n = a.shape
    table = np.zeros((m+2, n+2))
    table[:m, :n] = a
    table[:m, n] = -1
    table[:m, n+1] = b
    table[m, :n] = -c
    table[m+1, n] = 1
    basic, nonbasic = list(range(n, n+m)), list(range(n))+[-1]
    tolerance = 1e-9

    def pivot(row, column):
        inv = 1/table[row, column]
        old_row, old_column = table[row].copy(), table[:, column].copy()
        table[:] -= np.outer(old_column, old_row)*inv
        table[row] = old_row*inv
        table[:, column] = -old_column*inv
        table[row, column] = inv
        basic[row], nonbasic[column] = nonbasic[column], basic[row]

    def simplex(phase):
        objective_row = m+1 if phase == 1 else m
        for _ in range(1000):
            candidates = [j for j in range(n+1) if phase == 1 or nonbasic[j] != -1]
            column = min(candidates, key=lambda j:(table[objective_row, j], nonbasic[j]))
            if table[objective_row, column] >= -tolerance:
                return
            candidates = [i for i in range(m) if table[i, column] > tolerance]
            if not candidates:
                raise ValueError('unbounded prediction interval')
            row = min(candidates, key=lambda i:(table[i, n+1]/table[i, column], basic[i]))
            pivot(row, column)
        raise ValueError('prediction interval did not converge')

    row = int(np.argmin(table[:m, n+1]))
    if table[row, n+1] < -tolerance:
        pivot(row, n)
        simplex(1)
        if abs(table[m+1, n+1]) > 1e-7:
            raise ValueError('pixels fall outside the declared measurement interval')
        if -1 in basic:
            row = basic.index(-1)
            candidates = [j for j in range(n+1) if abs(table[row, j]) > tolerance]
            if candidates:
                pivot(row, min(candidates, key=lambda j:nonbasic[j]))
    simplex(2)
    return float(table[m, n+1])


def _joint_pixel_range(rows, values, epsilon, future):
    """Enclose knots in [-1,1] using direct source AND outlet observations."""
    import numpy as np
    a, values, future = np.asarray(rows, float), np.asarray(values, float), np.asarray(future, float)
    n = len(future)
    # z = knot+1 is nonnegative; z<=2 supplies the other box boundary.
    constraints = np.concatenate((a, -a, np.eye(n)))
    bounds = np.concatenate((values+epsilon+a.sum(1), -values+epsilon-a.sum(1), np.full(n, 2.0)))
    upper = _linear_maximum(constraints, bounds, future)-future.sum()
    lower = -_linear_maximum(constraints, bounds, -future)-future.sum()
    return float(lower), float(upper)


def joint_pixel_prediction(source_samples, outlet_samples, target_ms, *, source_base, outlet_base,
                           common_amplitude, flex_amplitude, span_ms, epsilon=1.0):
    """Causal outlet prediction without subtracting two noisy measurements.

    Source and outlet have the same common translation. Measuring the outlet
    directly constrains their sum; treating its flex as a source-subtracted
    independent error loses that constraint and overstates uncertainty.
    """
    times = [t for t, _ in source_samples+outlet_samples]+[target_ms]
    common_indices = sorted({i for t in times for i in (int(t//span_ms), int(t//span_ms)+1)})
    flex_span = span_ms+317
    flex_indices = sorted({i for t in times for i in (int(t//flex_span), int(t//flex_span)+1)})
    rows, values = [], []
    for t, value in source_samples:
        rows.append([common_amplitude*x for x in _spline_basis(t, span_ms, common_indices)]+[0]*len(flex_indices))
        values.append(value-source_base)
    for t, value in outlet_samples:
        rows.append([common_amplitude*x for x in _spline_basis(t, span_ms, common_indices)]+
                    [flex_amplitude*x for x in _spline_basis(t, flex_span, flex_indices)])
        values.append(value-outlet_base)
    future = ([common_amplitude*x for x in _spline_basis(target_ms, span_ms, common_indices)]+
              [flex_amplitude*x for x in _spline_basis(target_ms, flex_span, flex_indices)])
    lo, hi = _joint_pixel_range(rows, values, epsilon, future)
    return dict(point=outlet_base+(lo+hi)/2, error=(hi-lo)/2)


def input_control_context(input_history, *, mode, now_ms):
    """Motor state from the player's own completed input history only.

    None denotes unknown history and keeps conservative cancellation. A
    completed history starts at Begin and contains no future event. Escape
    clears the game preview but does not release a physically held mouse.
    Port acquisition success still comes from the current visible ring.
    """
    if input_history is None:
        return dict(known=False, tool=None, physical_down=None, preview=None, press_point=None,
                    hold_tool=None)
    if mode not in ('full', 'simplified') or not isinstance(input_history, (list, tuple)):
        raise ValueError('a declared mode and own input history are required')
    tool, physical_down, preview, begun, previous = 'stitch', False, False, False, -1
    press_point = hold_tool = None
    for event in input_history:
        ms = event.get('t_ms')
        if not isinstance(ms, (int, float)) or not previous <= ms <= now_ms:
            raise ValueError('input history must be chronological and precede the window endpoint')
        previous = ms
        kind = event.get('kind')
        if kind == 'begin':
            if begun:
                raise ValueError('own history cannot restart the episode')
            begun = True
        elif kind == 'tool':
            if event.get('tool') not in ('stitch', 'cut'):
                raise ValueError('unknown tool in own history')
            tool = event['tool']
            if mode == 'simplified':
                preview = False
        elif kind == 'cancel':
            preview = False
            hold_tool = None
        elif kind == 'inspect':
            # Section discovery changes knowledge, not the motor preview.
            pass
        elif begun and kind == 'down' and mode == 'full':
            physical_down = True
            preview = True
            hold_tool = tool
            point = event.get('point')
            press_point = (list(point) if isinstance(point, (list, tuple)) and len(point) == 2
                           and all(isinstance(x, (int, float)) and math.isfinite(x) for x in point)
                           else None)
        elif begun and kind == 'up' and mode == 'full':
            physical_down = False
            preview = False
            press_point = None
            hold_tool = None
        elif begun and kind == 'click' and mode == 'simplified':
            preview = not preview if tool == 'stitch' else False
        elif kind != 'submit':
            raise ValueError('invalid event in own input history')
    if not begun:
        raise ValueError('active planning requires the player\'s Begin history')
    return dict(known=True, tool=tool, physical_down=physical_down, preview=preview,
                press_point=press_point,hold_tool=hold_tool)


def pixel_window_plan(frames, *, level, mode, delay_ms, event_spacing_ms=1, input_history=None):
    """Historical V6 repair plan from a recent pixel window.

    This task-specific implementation diagnostic uses only raster measurements
    and the declared profile. It may request another window when uncertainty
    prevents a certified contact; that is not an all-C_Delta optimality proof.
    Native input timing and transport are deliberately not assumed here.
    Own input history avoids spending an urgent contact budget on redundant
    cancellation, physical release or selecting the already active tool.
    The positive nominal spacing describes the requested compound schedule;
    it is not a lower bound on input duration or a native latency guarantee.
    In particular, a ten-ms simulation tick is not a ten-ms input quota.
    V7 uses the separate observable-state decoder/kernel below. This legacy
    spline planner remains for source-bound historical regression fixtures;
    its finite successes are not relabelled as V7 optimal-control evidence.
    """
    if mode not in ('full','simplified') or not frames or frames[-1][0]-frames[0][0]>600:
        raise ValueError('a bounded recent frame window and declared mode are required')
    if (not isinstance(event_spacing_ms, (int, float)) or isinstance(event_spacing_ms, bool)
            or not math.isfinite(event_spacing_ms) or event_spacing_ms <= 0):
        raise ValueError('compound input spacing must be finite and positive')
    profile=PROFILES[level]; now,observation=frames[-1]
    control=input_control_context(input_history,mode=mode,now_ms=now)
    parsed=[]; motion_frames=[]
    for ms,frame in frames:
        try: parsed.append((ms,{s['key']:s for s in pixel_stations(frame,level,allow_partial=True)}))
        except ValueError: parsed.append((ms,{}))
        # Depth correspondence is needed in the final frame, but a moving
        # gold signal can overlap an earlier depth marker while its operating
        # port circles remain clear. Retain those measured positions without
        # assigning a depth answer to an unreadable earlier projection.
        rows={}
        for source in (p for p in frame['ports'] if p['glyph']==0):
            column=min(range(3),key=lambda i:abs(source['world'][0]-(165+300*i)))
            outlets=[p for p in frame['ports'] if p['glyph'] and p['lane']==source['lane']
                     and 50 <= p['world'][0]-source['world'][0] <= 102
                     and abs(p['world'][1]-source['world'][1]) <= 56]
            if len(outlets)==profile['candidate_count'] and len({p['glyph'] for p in outlets})==len(outlets):
                rows[f"{source['lane']}:{column}"]=dict(source=source,outlets=outlets)
        motion_frames.append((ms,rows))
    current=parsed[-1][1]
    nominal_y={1:[245],2:[155,345],3:[88,245,402]}[profile['front_count']]
    cutoff=min(profile['port_radius']-1,{1:26,2:21.5,3:21.5,4:15.5,5:12}[level]-.5)
    events=[]; decisions=[]
    active_tool=control['tool']
    if observation['ports'] and not current:
        decisions.append(dict(action='observe_again',reason='current frame has unresolved depth correspondence'))
    for lane in {p['lane'] for p in observation['ports'] if p['glyph']==0}:
        if not any(row['lane']==lane for row in current.values()):
            decisions.append(dict(lane=lane,action='observe_again',reason='this lane has unresolved depth correspondence'))
    def emit(kind,point=None,tool=None):
        nonlocal active_tool
        events.append(dict(kind=kind,point=point,tool=tool,offset_ms=len(events)*event_spacing_ms))
        if kind=='tool':active_tool=tool
    def predicted(row,glyph,at):
        common_samples=[(ms,rows[row['key']]['source']['world']) for ms,rows in motion_frames if row['key'] in rows]
        if len(common_samples)<3:
            raise ValueError('wait for sufficient recently visible port measurements')
        result,errors=[],[]
        spacing=34 if profile['candidate_count']==4 else 46 if profile['candidate_count']==3 else 64
        offset_y=(glyph-1-(profile['candidate_count']-1)/2)*spacing if glyph else 0
        for axis,amp in ((0,profile['drift_px']),(1,14)):
            base=165+300*row['column'] if axis==0 else nominal_y[row['lane']]
            p=spline_pixel_prediction([(ms,q[axis]) for ms,q in common_samples],at,base=base,amplitude=amp,span_ms=profile['span_ms'])
            if glyph:
                offset=76 if axis==0 else offset_y
                samples=[]
                for ms,rows in motion_frames:
                    if row['key'] not in rows:continue
                    old=rows[row['key']]
                    port=next(q for q in old['outlets'] if q['glyph']==glyph)
                    samples.append((ms,port['world'][axis]))
                joint=joint_pixel_prediction([(ms,q[axis]) for ms,q in common_samples],samples,at,
                                             source_base=base,outlet_base=base+offset,common_amplitude=amp,
                                             flex_amplitude=24 if axis==0 else 1.5,span_ms=profile['span_ms'])
                result.append(joint['point']);errors.append(joint['error'])
            else:result.append(p['point']);errors.append(p['error'])
        return result,math.hypot(*errors)
    def urgency(row):
        gaps=[]
        for (ms,rows),(_,frame) in zip(motion_frames,frames):
            signal=next((s for s in frame.get('signals',[]) if s['lane']==row['lane']),None)
            if row['key'] in rows and signal is not None:
                gaps.append((ms,max(0,rows[row['key']]['source']['world'][0]-signal['world'][0])))
        if len(gaps)>=2 and gaps[-1][0]>gaps[0][0]:
            closing=(gaps[0][1]-gaps[-1][1])/(gaps[-1][0]-gaps[0][0])
            if closing>0:return (gaps[-1][1]/closing,row['column'],row['lane'])
        return (float('inf'),row['column'],row['lane'])

    def bridge_key(bridge):
        # A bridge midpoint stays in its lane/column corridor at every
        # profile. These are visible geometric groups, not private IDs.
        lane=min(range(len(nominal_y)),key=lambda i:abs(bridge['world'][1]-nominal_y[i]))
        column=min(range(3),key=lambda i:abs(bridge['world'][0]-(203+300*i)))
        return f'{lane}:{column}',lane,column

    def bridge_samples(bridge):
        key,_,_=bridge_key(bridge)
        samples=[]
        for ms,frame in frames:
            choices=[b for b in frame['bridges'] if bridge_key(b)[0]==key]
            if choices:
                samples.append((ms,min(choices,key=lambda b:math.dist(b['world'],bridge['world']))['world']))
        return samples

    def cut_urgency(bridge):
        key,lane,column=bridge_key(bridge)
        gaps=[]
        for ms,point in bridge_samples(bridge):
            # Match by time: some older frames can lack this bridge.
            frame=next(frame for at,frame in frames if at==ms)
            signal=next((s for s in frame.get('signals',[]) if s['lane']==lane),None)
            if signal is not None:
                gaps.append((ms,point[0]-38-signal['world'][0]))
        if len(gaps)>=2 and gaps[-1][0]>gaps[0][0]:
            closing=(gaps[0][1]-gaps[-1][1])/(gaps[-1][0]-gaps[0][0])
            if closing>0:
                # The midpoint includes half the outlet's horizontal flex.
                # Use a lower gap estimate when the joined source no longer
                # has a large port ring. This is visible urgency evidence,
                # not an exact future crossing or an optimality certificate.
                gap=max(0,gaps[-1][1]-profile['outlet_flex_px']/2-1)
                return gap/closing,column,lane
        return float('inf'),column,lane

    def predicted_bridge(bridge,at):
        samples=bridge_samples(bridge)
        if len(samples)<2:return None
        first_ms,old=samples[0];last_ms,latest=samples[-1]
        if last_ms==first_ms:return None
        return [latest[i]+(latest[i]-old[i])*(at-now)/(last_ms-first_ms) for i in range(2)]

    def emit_cut(bridge):
        middle=predicted_bridge(bridge,now+delay_ms+(len(events)+2)*event_spacing_ms)
        if middle is None:return False
        if active_tool!='cut':emit('tool',tool='cut')
        at=now+delay_ms+(len(events)+1)*event_spacing_ms
        middle=predicted_bridge(bridge,at)
        if mode=='full':
            emit('down',[middle[0],middle[1]-45]);emit('up',[middle[0],middle[1]+45])
        else:
            for dy in (0,-8,8,-16,16,-24,24):emit('click',[middle[0],middle[1]+dy])
        return True
    # Complete the narrow moving-port contacts before the wider knife/grid
    # sweep. Joining before cutting is legal, and leaves the pink bridge
    # visible. This reduces prediction horizons without changing either goal.
    pending = [(row,port) for row in current.values() for port in [row['source'],*row['outlets']]
               if port.get('selected')]
    open_keys={f"{p['lane']}:{min(range(3),key=lambda i:abs(p['world'][0]-(165+300*i)))}"
               for p in observation['ports'] if p['glyph']==0}
    cut_only=sorted((b for b in observation['bridges'] if bridge_key(b)[0] not in open_keys),
                    key=cut_urgency)
    completed = set()
    released = False
    # A held knife is already an acquired stroke. Try its actual swept
    # segment through the earlier cut-only opportunity instead of releasing
    # a zero-length stroke and reacquiring. Ordinary cuts below remain a
    # fallback; a knife miss is harmless and does not certify contact.
    if (mode=='full' and cut_only and control['hold_tool']=='cut'
            and control['press_point'] is not None
            and cut_urgency(cut_only[0]) < min((urgency(r) for r in current.values()),
                                             default=(float('inf'),0,0))):
        middle=predicted_bridge(cut_only[0],now+delay_ms)
        if middle is not None:
            start=control['press_point'];length=math.dist(start,middle)
            direction=([(middle[i]-start[i])/length for i in range(2)] if length else [0,1])
            end=[middle[i]+direction[i]*max(45,length) for i in range(2)]
            emit('up',end);released=True
            decisions.append(dict(key=bridge_key(cut_only[0])[0],action='use_held_knife',
                                  contact_certified=False,target_time=now+delay_ms))
    clear_preview_for_cut=(mode=='simplified' and len(pending)==1 and cut_only
                           and cut_urgency(cut_only[0])<urgency(pending[0][0]))
    if clear_preview_for_cut:
        # Selecting Cut clears a simplified preview as part of the existing
        # tool effect. Completing a later stitch first spends another input.
        emit('tool',tool='cut');released=True
        decisions.append(dict(key=pending[0][0]['key'],action='clear_preview_for_earlier_cut'))
    elif len(pending) == 1:
        row,port = pending[0]
        if port['glyph'] in (0,row['continuation']['glyph']):
            glyph = row['continuation']['glyph'] if port['glyph'] == 0 else 0
            try:
                dest,error = predicted(row,glyph,now+delay_ms)
                if error <= cutoff:
                    emit('up' if mode=='full' else 'click',dest)
                    completed.add(row['key'])
                    decisions.append(dict(key=row['key'],action='complete_visible_preview',
                                          error=error,cutoff=cutoff,target_time=now+delay_ms))
            except ValueError:
                pass
    if not completed and not released:
        if mode=='full' and control['known'] and control['physical_down'] and control['press_point'] is not None:
            # The existing six-unit ring is centred on the original press.
            # Returning there cancels and releases in one physical event.
            # It is proprioception from I_t, even for an older acquisition.
            emit('up',control['press_point'])
        else:
            if not control['known'] or control['preview']:
                emit('cancel')
            if mode=='full' and (not control['known'] or control['physical_down']):
                emit('up',[900,450])
    remaining = [row for row in current.values() if row['key'] not in completed]
    # A joined-but-uncut lane can expire before an unrelated moving-port
    # repair. Keep the usual narrow-contact batching, but promote an earlier
    # visible cut-only opportunity instead of always putting every knife
    # operation last. An unresolved open source is not treated as joined.
    next_stitch=min((urgency(row) for row in remaining),default=(float('inf'),0,0))
    promoted=set()
    for index,bridge in sorted(enumerate(observation['bridges']),key=lambda item:cut_urgency(item[1])):
        key,_,_=bridge_key(bridge);estimate=cut_urgency(bridge)
        if key not in open_keys and math.isfinite(estimate[0]) and estimate[0]<next_stitch[0]:
            if emit_cut(bridge):
                promoted.add(index)
                decisions.append(dict(key=key,action='cut_before_later_stitch',
                    estimated_visible_time_to_contact_ms=estimate[0],
                    exact_deadline_or_optimality_certified=False))
    if remaining and active_tool != 'stitch':emit('tool',tool='stitch')
    for row in sorted(remaining,key=urgency):
        at1=now+delay_ms+len(events)*event_spacing_ms
        at2=at1+event_spacing_ms
        try:
            source,error1=predicted(row,0,at1)
            dest,error2=predicted(row,row['continuation']['glyph'],at2)
        except ValueError as exc:
            decisions.append(dict(key=row['key'],action='observe_again',reason=str(exc)));continue
        if max(error1,error2)>cutoff:
            decisions.append(dict(key=row['key'],action='observe_again',error=[error1,error2],cutoff=cutoff));continue
        emit('down' if mode=='full' else 'click',source)
        emit('up' if mode=='full' else 'click',dest)
        decisions.append(dict(key=row['key'],action='stitch',error=[error1,error2],cutoff=cutoff,
                              estimated_visible_time_to_contact_ms=(urgency(row)[0]
                                  if math.isfinite(urgency(row)[0]) else None),
                              target_times=[at1,at2]))
    # Cut capsules are directly visible, including joined-but-uncut lesions.
    # The same predicted vertical stroke/grid covers local centroid motion.
    for index,bridge in sorted(enumerate(observation['bridges']),key=lambda item:item[1]['world'][0]):
        if index not in promoted:emit_cut(bridge)
    return dict(t_ms=now,delay_ms=delay_ms,event_spacing_ms=event_spacing_ms,events=events,
                decisions=decisions,input_control_context=control,
                pixel_only_geometry=True,native_http_action_space_parity=False)


def recent_observation(sim):
    """Ideal measurements of the rendered 200-ms suffix, not future state.

    This diagnostic extracts exact geometric centres rather than estimating
    them from pixels. Port depth, pink bridge identity and repair colours are
    visible after section inspection. Neither the hidden answers nor later
    motion knots enter the plan. Uninspected V3 stations are omitted.
    """
    c, ms = sim.c, sim.ms
    return dict(t_ms=ms, delivered=sim.done, stations=[dict(
        id=st["id"], source=st["source"]["id"], bridge_to=st["bridge_to"],
        cut=st["id"] in sim.cut, joined=st["id"] in sim.join, ports=[dict(
            id=p["id"], now=position(c, st, p, ms, sim.recoils),
            previous=position(c, st, p, max(0, ms-200), sim.recoils))
            for p in [st["source"], *st["candidates"]]])
        for st in c["stations"] if (not c.get("inspection_model") or st["id"] in sim.inspected) and st["id"] in sim.open and
        (st["id"] not in sim.cut or st["id"] not in sim.join)])


def window_plan(observation, *, mode, delay_ms):
    """One compound batch chosen solely from the recent visible measurements.

    A vertical knife stroke, or seven ordinary capsule clicks, covers the
    bounded extrapolation error of the pink bridge. Stitch coordinates are
    velocity predictions from two measurements 200 ms apart. Cancel is safe
    for any pending preview; a redundant full up releases the physical button.
    """
    events = [("cancel", None, None)]
    if mode == "full":
        events.append(("up", [900, 450], None))
    for st in observation["stations"]:
        ports = {p["id"]: p for p in st["ports"]}
        source = ports[st["source"]]
        continuation = min((p for p in st["ports"] if p["id"] != st["source"]),
                           key=lambda p: abs(p["now"][2]-source["now"][2]))

        def predicted(port):
            return [port["now"][i]+(port["now"][i]-port["previous"][i])*delay_ms/200
                    for i in range(2)]

        a, b = predicted(source), predicted(continuation)
        if not st["cut"]:
            events.append(("tool", None, "cut"))
            pink = predicted(ports[st["bridge_to"]])
            middle = [(a[i]+pink[i])/2 for i in range(2)]
            if mode == "full":
                events += [("down", [middle[0], middle[1]-40], None),
                           ("up", [middle[0], middle[1]+40], None)]
            else:
                events += [("click", [middle[0], middle[1]+dy], None)
                           for dy in (-30, -20, -10, 0, 10, 20, 30)]
        if not st["joined"]:
            events.append(("tool", None, "stitch"))
            events += [("down" if mode == "full" else "click", a, None),
                       ("up" if mode == "full" else "click", b, None)]
    return events


def solve_window_simulation(contract, *, delay_ms=None, observation_gap_ms=600):
    """Delayed whole-game controller; ideal-coordinate implementation evidence.

    The batch is frozen before advancing to its delivery time. No current
    repair feedback or true delivery-time coordinates change that batch.
    Actual native dispatch duration remains a separate unrun check.
    """
    sim, events, decisions = Simulation(contract), [], []
    level = next(l for l, p in PROFILES.items() if p == contract["parameters"])
    delay = DELAYS[level] if delay_ms is None else delay_ms

    def emit(kind, point=None, tool=None):
        events.append(dict(sequence=len(events)+1, t_ms=sim.ms, kind=kind,
                           input_source="button" if kind in ("begin", "tool", "submit") else contract["interaction"],
                           **({"point": point} if point is not None else {}),
                           **({"tool": tool} if tool else {})))
        if kind != "submit":
            sim.input(kind, point, contract["interaction"], tool)

    emit("begin")
    sim.advance(600)
    while not sim.failed and not sim.done:
        observation = recent_observation(sim)
        batch = window_plan(observation, mode=contract["interaction"], delay_ms=delay)
        decisions.append(dict(observation=observation, delivery_t_ms=sim.ms+delay, batch=batch))
        sim.advance(sim.ms+delay)
        if sim.failed or sim.done:
            break
        for kind, point, tool in batch:
            emit(kind, point, tool)
            if sim.failed:
                break
        sim.advance(sim.ms+observation_gap_ms)
    emit("submit")
    return dict(mechanic_id=contract["mechanic_id"], task_id=contract["task_id"],
                challenge_id=contract["challenge_id"], revision=contract["revision"],
                interaction=contract["interaction"], events=events, summary=sim.summary(),
                completed=sim.done and not sim.failed, window_decisions=decisions)


def solve_simulation(contract, *, policy="fresh", lag_ms=0):
    sim = Simulation(contract)
    mode = contract["interaction"]
    events = []

    def emit(kind, point=None, tool=None):
        events.append(dict(sequence=len(events)+1, t_ms=sim.ms, kind=kind,
                           input_source="button" if kind in ("begin", "tool", "submit") else mode,
                           **({"point": point} if point is not None else {}),
                           **({"tool": tool} if tool else {})))
        if kind != "submit":
            sim.input(kind, point, mode, tool)

    def at(st, port):
        observed = 0 if policy in ("initial_plan", "frozen_coordinates_feedback", "blind_batch") else max(0, sim.ms-lag_ms)
        return position(contract, st, port, observed, sim.recoils)[:2]

    def gesture(a, b=None):
        if mode == "simplified":
            emit("click", a)
            if b is not None:
                sim.advance(sim.ms+80)
                if not sim.failed:
                    emit("click", b)
        else:
            emit("down", a)
            sim.advance(sim.ms+80)
            if not sim.failed:
                emit("up", b)
        sim.advance(sim.ms+80)

    emit("begin")
    if policy in ("parked", "pre_run"):
        sim.advance(contract["max_ms"])
    elif policy == "initial_plan":
        # One immutable script from initial geometry and nominal signal speed.
        # No current simulation state chooses times, targets or retries.
        scheduled = sorted(contract["stations"],key=lambda s:
                           (s["material_x"]-contract["fronts"][s["lane"]]["start_x"]-contract["parameters"]["lead_px"]*.5))
        for st in scheduled:
            target = max(600,int((st["material_x"]-contract["fronts"][st["lane"]]["start_x"]-
                                 contract["parameters"]["lead_px"]*.5)/contract["parameters"]["signal_speed"]*1000)//10*10)
            sim.advance(target)
            if sim.failed:
                break
            emit("tool",tool="cut")
            dest = next(p for p in st["candidates"] if p["id"] == st["bridge_to"])
            a,b=at(st,st["source"]),at(st,dest)
            midpoint=[(a[i]+b[i])/2 for i in range(2)]
            if mode == "simplified":gesture(midpoint)
            else:
                dx,dy=b[0]-a[0],b[1]-a[1]; length=math.hypot(dx,dy);normal=[-dy/length*22,dx/length*22]
                gesture([midpoint[i]-normal[i] for i in range(2)],[midpoint[i]+normal[i] for i in range(2)])
            if sim.failed:break
            emit("tool",tool="stitch")
            dest=next(p for p in st["candidates"] if p["p"][2] == st["source"]["p"][2])
            gesture(at(st,st["source"]),at(st,dest))
            if sim.failed:break
        sim.advance(contract["max_ms"])
    elif policy == "blind_batch":
        # Dense repeated fixed batches, including future closed lesions. No
        # opened/cut/joined feedback controls the sequence or the coordinates.
        scheduled=sorted(contract["stations"],key=lambda s:(s["column"],s["lane"]))
        while not sim.done and not sim.failed:
            for st in scheduled:
                emit("tool",tool="cut")
                dest=next(p for p in st["candidates"] if p["id"]==st["bridge_to"])
                a,b=at(st,st["source"]),at(st,dest);midpoint=[(a[i]+b[i])/2 for i in range(2)]
                if mode=="simplified":gesture(midpoint)
                else:
                    dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy);normal=[-dy/length*22,dx/length*22]
                    gesture([midpoint[i]-normal[i] for i in range(2)],[midpoint[i]+normal[i] for i in range(2)])
                if sim.failed or sim.done:break
                emit("tool",tool="stitch")
                dest=next(p for p in st["candidates"] if p["p"][2]==st["source"]["p"][2])
                gesture(at(st,st["source"]),at(st,dest))
                if sim.failed or sim.done:break
    else:
        while not sim.done and not sim.failed:
            pending = [s for s in contract["stations"] if s["id"] in sim.open and
                       (s["id"] not in sim.cut or s["id"] not in sim.join)]
            pending.sort(key=lambda s: s["material_x"]-sim.x[s["lane"]])
            if not pending:
                sim.advance(sim.ms+200)
                continue
            st = pending[0]
            if st["id"] not in sim.cut:
                emit("tool", tool="cut")
                dest = next(p for p in st["candidates"] if p["id"] == st["bridge_to"])
                a, b = at(st, st["source"]), at(st, dest)
                midpoint = [(a[i]+b[i])/2 for i in range(2)]
                if mode == "simplified":
                    gesture(midpoint)
                else:
                    dx, dy = b[0]-a[0], b[1]-a[1]
                    length = math.hypot(dx, dy)
                    normal = [-dy/length*22, dx/length*22]
                    gesture([midpoint[i]-normal[i] for i in range(2)],
                            [midpoint[i]+normal[i] for i in range(2)])
            if not sim.failed and st["id"] not in sim.join:
                emit("tool", tool="stitch")
                dest = next(p for p in st["candidates"] if p["p"][2] == st["source"]["p"][2])
                gesture(at(st, st["source"]), at(st, dest))
    emit("submit")
    return dict(mechanic_id=contract["mechanic_id"], task_id=contract["task_id"],
                challenge_id=contract["challenge_id"], revision=contract["revision"],
                interaction=mode, events=events, summary=sim.summary(), completed=sim.done and not sim.failed)


def canvas_point(page, p):
    box = page.locator("#br2-xy").bounding_box()
    if box is None:
        raise AssertionError("operating canvas unavailable")
    return (box["x"]+p[0]/960*box["width"], box["y"]+p[1]/490*box["height"])


def _mouse_button(page, selector):
    box = page.locator(selector).bounding_box()
    page.mouse.click(box["x"]+box["width"]/2, box["y"]+box["height"]/2)


def wait_for(page, expression, timeout_seconds=10):
    # A paused task stops its requestAnimationFrame callbacks. Poll from Python
    # so browser validation does not depend on a clock that it has just frozen.
    deadline = time.monotonic()+timeout_seconds
    while not page.evaluate(expression):
        if time.monotonic() >= deadline:
            raise AssertionError("timed out: "+expression)
        time.sleep(.02)


def _gesture(page, mode, a, b=None):
    a = canvas_point(page, a)
    if mode == "simplified":
        page.mouse.click(*a)
        if b is not None:
            page.mouse.click(*canvas_point(page, b))
    else:
        page.mouse.move(*a)
        page.mouse.down()
        page.mouse.move(*canvas_point(page, b), steps=4)
        page.mouse.up()


def _drag_actions(start, end):
    return [dict(mouse=dict(move=list(start), buttons=dict(left_down=True))),
            dict(mouse=dict(move=list(end))), dict(mouse=dict(buttons=dict(left_up=True)))]


def _solve_ui(ui, contract, *, screen_origin, time_mode, timeout_seconds=120, max_requests=400, on_stage=None):
    """Emit frozen mouse dictionaries; geometry/time reads are privileged.

    Batch repairs at one paused input boundary. Live input has no task-clock
    control. Never retry an uncertain acknowledgement in this task policy.
    """
    if contract["mechanic_id"] != "branch_repair_v3" or time_mode not in ("live", "paused"):
        raise ValueError("wrong branch repair oracle configuration")
    if len(screen_origin) != 2 or not all(math.isfinite(v) for v in screen_origin):
        raise ValueError("verified viewport origin in desktop pixels is required")
    requests = []
    deadline = time.monotonic() + timeout_seconds
    expression = """(() => {
        const m=branchRepairV3Model,r=document.querySelector('#br2-xy').getBoundingClientRect();
        const buttons=Object.fromEntries(['begin','cut','stitch','submit',...(document.querySelector('#br2-inspect')?['inspect']:[])].map(name=>{
            const b=document.querySelector('#br2-'+name).getBoundingClientRect();return [name,[b.x+b.width/2,b.y+b.height/2]];
        }));
        return {summary:m.sim.summary(),canvas:{x:r.x,y:r.y,width:r.width,height:r.height},buttons,
                verdict:document.querySelector('.br2').dataset.verdict||null};
    })()"""

    def send(actions):
        if time.monotonic() >= deadline or len(requests) >= max_requests:
            raise AssertionError("oracle exceeded declared time/request budget")
        ui.send(actions)
        requests.append(actions)

    def button(snapshot, name):
        return dict(mouse=dict(left_click=[round(snapshot["buttons"][name][i]+screen_origin[i]) for i in range(2)]))

    def screen(snapshot, point):
        r = snapshot["canvas"]
        return [round(screen_origin[0]+r["x"]+point[0]*r["width"]/960),
                round(screen_origin[1]+r["y"]+point[1]*r["height"]/490)]

    saved = set()
    snapshot=ui.read(expression)
    if contract.get('inspection_model') and 'inspect' in snapshot['buttons']:
        # Reveal the actual linked sections through ordinary port clicks.
        # This oracle uses geometry to aim; it is not a screenshot-only or
        # native-action parity claim. There is no inspection quota in grading.
        actions=[button(snapshot,'inspect')]
        for station in sorted(contract['stations'],key=lambda st:(st['column'],st['lane'])):
            point=position(contract,station,station['source'],snapshot['summary']['t_ms'],
                           snapshot['summary'].get('recoil_t_ms',[]))[:2]
            actions.append(dict(mouse=dict(left_click=screen(snapshot,point))))
        send(actions)
        if on_stage:on_stage('inspected-sections')
    send([button(ui.read(expression), "begin")])
    while time.monotonic() < deadline:
        snapshot = ui.read(expression)
        summary = snapshot["summary"]
        if summary["failed"]:
            raise AssertionError(summary["failed"])
        if summary["delivered"]:
            send([button(snapshot, "submit")])
            while time.monotonic() < deadline:
                verdict = ui.read(expression)["verdict"]
                if verdict == "pass":
                    return requests
                if verdict == "fail":
                    raise AssertionError("visible completion failed independent grading")
                ui.wait(.02)
            break
        pending = [s for s in contract["stations"] if s["id"] in summary["opened"] and
                   (s["id"] not in summary["cut"] or s["id"] not in summary["joins"])]
        pending.sort(key=lambda s: s["material_x"]-summary["signal_x"][s["lane"]])
        if not pending:
            if time_mode == "paused":
                send([])
            else:
                ui.wait(.08)
            continue
        st = pending[0]
        if time_mode == "live" and callable(getattr(ui, "send_repair", None)):
            if time.monotonic() >= deadline or len(requests) >= max_requests:
                raise AssertionError("oracle exceeded declared time/request budget")
            # The native consumer reads a fresh clock/geometry reference after
            # its private checks, then schedules the contact program through
            # the existing HTTP API. Its reads cannot stale this earlier aim.
            requests.append(ui.send_repair(contract, st))
            if on_stage and st["column"] not in saved:
                saved.add(st["column"])
                on_stage(f"column-{st['column']}-repair")
            continue
        ms = summary["t_ms"]
        recoils = summary.get("recoil_t_ms", [])
        actions = []
        if st["id"] not in summary["cut"]:
            actions.append(button(snapshot, "cut"))
            dest = next(p for p in st["candidates"] if p["id"] == st["bridge_to"])
            at = ms + (20 if time_mode == "live" else 0)
            a, b = position(contract, st, st["source"], at, recoils)[:2], position(contract, st, dest, at, recoils)[:2]
            midpoint = [(a[i]+b[i])/2 for i in range(2)]
            if contract["interaction"] == "simplified":
                actions.append(dict(mouse=dict(left_click=screen(snapshot, midpoint))))
            else:
                dx, dy = b[0]-a[0], b[1]-a[1]
                length = math.hypot(dx, dy)
                normal = [-dy/length*25, dx/length*25]
                actions += _drag_actions(screen(snapshot, [midpoint[i]-normal[i] for i in range(2)]),
                                         screen(snapshot, [midpoint[i]+normal[i] for i in range(2)]))
        if st["id"] not in summary["joins"]:
            actions.append(button(snapshot, "stitch"))
            dest = next(p for p in st["candidates"] if p["p"][2] == st["source"]["p"][2])
            a = screen(snapshot, position(contract, st, st["source"], ms+(40 if time_mode == "live" else 0), recoils)[:2])
            b = screen(snapshot, position(contract, st, dest, ms+(60 if time_mode == "live" else 0), recoils)[:2])
            if contract["interaction"] == "simplified":
                actions += [dict(mouse=dict(left_click=a)), dict(mouse=dict(left_click=b))]
            else:
                actions += _drag_actions(a, b)
        send(actions)
        if on_stage and st["column"] not in saved:
            saved.add(st["column"])
            on_stage(f"column-{st['column']}-repair")
    raise AssertionError("oracle exceeded declared budget")


def solve_http(ui, contract, *, sandbox, screen_origin, time_mode="live", timeout_seconds=120, max_requests=400, on_stage=None):
    """Use existing HTTPUI.send(actions), never a Playwright input route.

    The caller must use the frozen same-machine gateway and verify loaded
    native capture before admission. Verify the actual sandbox connection,
    rather than a matching hostname or flag. Obtain screen_origin from
    read-only Firefox mozInnerScreenX/Y and verify native pixel scale.
    No sandbox allocation occurs here. The validation consumer must wait for
    the task's recorded events before reading repair feedback: an X-server
    receipt alone can precede Firefox handlers. Native evidence records that
    separate, privileged observation barrier and its original source hashes.
    """
    from gym_anything_rt.native_capture import require_direct_local_connection
    require_direct_local_connection(sandbox)
    return _solve_ui(ui, contract, screen_origin=screen_origin, time_mode=time_mode,
                     timeout_seconds=timeout_seconds, max_requests=max_requests, on_stage=on_stage)


class _HeadlessPrimitiveUI:
    """Test consumer only. It is explicitly not the native HTTP interface."""
    def __init__(self, page, time_mode):
        self.page, self.time_mode = page, time_mode

    def read(self, expression):
        return self.page.evaluate(expression)

    def wait(self, seconds):
        self.page.wait_for_timeout(seconds*1000)

    def send(self, actions):
        for action in actions:
            mouse = action["mouse"]
            if "left_click" in mouse:
                self.page.mouse.click(*mouse["left_click"])
            if "move" in mouse:
                self.page.mouse.move(*mouse["move"])
            buttons = mouse.get("buttons", {})
            if buttons.get("left_down"):
                self.page.mouse.down()
            if buttons.get("left_up"):
                self.page.mouse.up()
        if self.time_mode == "paused":
            self.page.evaluate("GymAnythingRTTime.runFor(600)")
            wait_for(self.page, "GymAnythingRTTime.status().phase==='completed'")


def solve(page, contract, out_dir=None, mechanic="branch_repair_v3", *, time_mode=None, timeout_seconds=120, on_stage=None):
    """Canonical shared solver; headless consumer tests the HTTP action policy.

    Privileged geometry/time planning and physical mouse input only. No DOM
    mutation/focus, internal action calls, or success injection. Primitive
    plans and browser behavior are tested. Native coverage belongs to the
    source-bound HTTP validation records, not this headless consumer.
    """
    if mechanic != "branch_repair_v3":
        raise ValueError("wrong mechanic for branch repair oracle")
    if not isinstance(contract, dict):
        source = Path(contract) / "public_state.json"
        contract = json.loads(source.read_text()) if source.is_file() else page.evaluate("branchRepairV3Model.state")
    if time_mode is None:
        time_mode = page.evaluate("GymAnythingRTTime.status().mode")
    if on_stage is None and out_dir is not None:
        destination = Path(out_dir)
        destination.mkdir(parents=True, exist_ok=True)
        on_stage = lambda pg, stage: pg.screenshot(path=str(destination/f"branch_repair_v3-{stage}.png"))
    callback = (lambda stage: on_stage(page, stage)) if on_stage else None
    requests = _solve_ui(_HeadlessPrimitiveUI(page, time_mode), contract, screen_origin=(0, 0),
                        time_mode=time_mode, timeout_seconds=timeout_seconds, on_stage=callback)
    if out_dir is not None:
        destination = Path(out_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination/"branch_repair_v3-primitive-requests.json").write_text(json.dumps(dict(
            transport="headless-primitive-consumer", native_http_action_space_parity=False,
            privileged_planning=True, requests=requests), indent=2)+"\n")
    return page.evaluate("branchRepairV3Model.events")


# JPEG raster measurements stay in this task's explicitly permitted solver.
def _palette():
    import numpy as np
    return np.asarray([[int(c[i:i+2], 16) for i in (0, 2, 4)]
                       for lane in PORT_COLOURS for c in lane])


def _rim_identity(sample, lane, *, source_allowed=True):
    """Use an unambiguous correspondence colour when the cursor covers text."""
    import numpy as np
    sample = np.asarray(sample)
    if np.ptp(sample) < 20:
        return None
    # Chroma subsampling mixes a thin rim with the neutral reconstruction
    # line, interior and cursor. Hue survives that mixture; a fixed RGB
    # background model can instead mistake the warm two-dot colour for one.
    hue = colorsys.rgb_to_hsv(*(sample/255))[0]
    hues = np.asarray([colorsys.rgb_to_hsv(*(colour/255))[0]
                       for colour in _palette()[lane*5:(lane+1)*5]])
    errors = abs((hues-hue+.5)%1-.5)*360
    if not source_allowed:
        # Cursor glare can make a warm outlet resemble the gold source.
        # A source diamond supplies independent shape evidence; the ring's
        # brightness alone must not turn an outlet into an incoming port.
        errors[0] = np.inf
    order = errors.argsort()
    if errors[order[0]] > 12 or errors[order[1]]-errors[order[0]] < 1.5:
        return None
    return int(order[0])


def jpeg_ports(image, layout, *, candidate_count=None, port_radius=None,
               retain_acquired=False):
    """Fit the luminous rim, read dot/diamond shapes, register source bars.

    RGB equality is unsuitable for a two-pixel ring after JPEG chroma
    subsampling. Luminance preserves the circumference and the white glyph.
    The stationary gold source bars supply lane identity from this image.
    """
    import numpy as np
    pane = layout['xy']
    rgb = np.asarray(image.convert('RGB')).astype(float)
    left, top = pane['x'], pane['y']
    crop = rgb[top:top+pane['height'], left:left+pane['width']]
    bars = crop[:, :round(20*pane['width']/960)]
    gold = np.max(abs(bars-[245, 211, 145]), axis=2) < 30
    lanes = [(lo+hi+1)/2*490/pane['height']
             for lo, hi in _pixel_runs(np.flatnonzero(gold.sum(1) > 5))
             if hi-lo > 8]
    if len(lanes) not in (1, 2, 3):
        raise ValueError('visible source bars could not be registered')
    fill = np.max(abs(crop-[17, 47, 61]), axis=2) <= 8
    ports = []
    for blob in _pixel_components(fill, minimum=60):
        low, high = blob.min(0), blob.max(0)
        height, width = high-low+1
        if not (7 <= width <= 80 and 7 <= height <= 80):
            continue
        y, x = (low+high+1)/2
        guess = np.asarray([x*960/pane['width'], y*490/pane['height']])
        radius = max(width*960/pane['width'], height*490/pane['height'])/2+1.5
        y0, y1 = max(0, int(y-45)), min(len(crop), int(y+46))
        x0, x1 = max(0, int(x-45)), min(len(crop[0]), int(x+46))
        patch = crop[y0:y1, x0:x1]
        yy, xx = np.indices(patch.shape[:2])
        xx = (xx+x0+.5)*960/pane['width']
        yy = (yy+y0+.5)*490/pane['height']
        distance = np.hypot(xx-guess[0], yy-guess[1])
        angle = (np.arctan2(yy-guess[1], xx-guess[0])+math.pi)/(2*math.pi)
        luminance = patch@np.asarray([.299, .587, .114])
        mask = (abs(distance-radius) < 3.5) & (luminance > 105)
        points, colours = [], []
        for index in range(48):
            locations = np.argwhere(mask & (angle >= index/48) & (angle < (index+1)/48))
            if not len(locations):
                continue
            at = tuple(max(locations, key=lambda p:luminance[tuple(p)]))
            points.append([xx[at], yy[at]])
            colours.append(patch[at])
        if len(points) < 24:
            continue
        points, colours = np.asarray(points), np.asarray(colours)
        kept = np.ones(len(points), dtype=bool)
        for _ in range(3):
            origin = points[kept].mean(0)
            q = points-origin
            a = np.column_stack((2*q[:, 0], 2*q[:, 1], np.ones(len(q))))
            c = np.linalg.lstsq(a[kept], (q*q).sum(1)[kept], rcond=None)[0]
            centre = origin+c[:2]
            r = math.sqrt(max(0, c[2]+sum(c[:2]**2)))
            residual = abs(np.linalg.norm(points-centre, axis=1)-r)
            kept = residual < 1.5
            if kept.sum() < 20:
                break
        if kept.sum() < 20 or not (12 <= r <= 22) or np.linalg.norm(centre-guess) > r:
            continue
        # A neutral damage marker can split one V3 port's interior into two
        # independently fitted blobs. Register that visible circle once;
        # the annular fit below still determines its final measured centre.
        # Distinct V7 ports are farther apart than half a port radius.
        duplicate_radius = port_radius/2 if retain_acquired and port_radius else 2
        if any(math.dist(centre, p['world']) < duplicate_radius for p in ports):
            continue
        cx, cy = left+centre[0]*pane['width']/960, top+centre[1]*pane['height']/490
        x0, x1 = max(0, int(cx-45)), min(image.width, int(cx+46))
        y0, y1 = max(0, int(cy-20)), min(image.height, int(cy+21))
        patch = rgb[y0:y1, x0:x1]
        yy, xx = np.indices(patch.shape[:2])
        yy = (yy+y0+.5-cy)*490/pane['height']
        xx = (xx+x0+.5-cx)*960/pane['width']
        glyph_mask = (abs(xx) < .87*r) & (abs(yy) < 4) & (patch@np.asarray([.299, .587, .114]) > 115)
        glyphs = _pixel_components(glyph_mask, minimum=2)
        diamonds, dots = [], []
        for b in glyphs:
            h, w = b.max(0)-b.min(0)+1
            if 7 <= w <= 13 and 7 <= h <= 12:
                diamonds.append(b)
            elif w <= 5 and h <= 5:
                dots.append(b)
        lane = min(range(len(lanes)), key=lambda i:abs(centre[1]-lanes[i]))
        glyph = 0 if diamonds else len(dots) if 1 <= len(dots) <= 4 else None
        source = 'visible glyph'
        # A cursor, signal or pink bridge contaminates a short arc. Median
        # colour across surviving angular bins preserves the exposed rim.
        rim_glyph = _rim_identity(np.median(colours[kept], axis=0), lane, source_allowed=bool(diamonds))
        if rim_glyph is not None and rim_glyph != glyph:
            # A pale damage front or the native cursor can cover just one
            # dot, turning a two-dot label into an apparent one-dot label.
            # Its independently visible, unambiguous rim retains identity.
            glyph = rim_glyph
            source = 'unambiguous visible circumference'
        ports.append(dict(lane=lane, glyph=glyph, glyph_measurement=source,
                          world=centre.tolist(), point=[float(cx), float(cy)],
                          box=[int(low[1]+left), int(low[0]+top), int(width), int(height)]))
    if port_radius is not None:
        # A held full gesture draws a cancellation ring and stroke through
        # the dark interior. Use its independently visible outer ring to
        # recover the centre instead of fitting those interior fragments.
        for centre in _selection_centres(image, layout, port_radius):
            ports = [p for p in ports if math.dist(p['world'], centre) >= port_radius]
            lane = min(range(len(lanes)), key=lambda i:abs(centre[1]-lanes[i]))
            ports.append(dict(lane=lane,glyph=None,selected=True,
                glyph_measurement='visible acquired-port ring',world=centre,
                point=[left+centre[0]*pane['width']/960,top+centre[1]*pane['height']/490]))
    if candidate_count is not None:
        if candidate_count not in (2, 3, 4):
            raise ValueError('invalid declared outlet count')
        spacing = {2:64, 3:46, 4:34}[candidate_count]
        for lane in range(len(lanes)):
            group = [p for p in ports if p['lane'] == lane]
            incoming=[p for p in group if p['glyph']==0]
            proposed_outlets=[p for p in group if p['glyph']!=0]
            ordered=sorted(proposed_outlets,key=lambda p:p['world'][1])
            complete_outlet_row=(len(proposed_outlets)==candidate_count and len(incoming)<=1
                and all(abs(b['world'][1]-a['world'][1]-spacing)<=5 for a,b in zip(ordered,ordered[1:]))
                and max(p['world'][0] for p in proposed_outlets)-min(p['world'][0] for p in proposed_outlets)<=50)
            if port_radius is not None and complete_outlet_row:
                # A gold signal can fill the incoming circle's dark interior
                # and cover its diamond. Fit its still-visible gold rim in
                # the source gap of the complete outlet row, rather than
                # requiring an interior blob or inspecting private state.
                source=_incoming_rim(image,layout,proposed_outlets,lane,port_radius)
                if source is not None:
                    if incoming:
                        # A surviving interior fragment can instead propose
                        # a displaced circle. The same independent annular
                        # fit refines it, retaining visible selection state.
                        incoming[0].update(source)
                    else:
                        ports.append(source);group.append(source)
            if len(group) != candidate_count+1:
                continue
            incoming = min(group, key=lambda p:p['world'][0])
            outlets = sorted((p for p in group if p is not incoming),key=lambda p:p['world'][1])
            # These are visible geometric correspondences, not the answer:
            # every outlet is at least 52 units to the right of its incoming
            # port, and glyphs are printed in increasing vertical order.
            # Require the complete declared row pattern before using it to
            # recover labels obscured by a cursor or compression.
            if not all(50 <= p['world'][0]-incoming['world'][0] <= 102 for p in outlets):
                continue
            if not all(abs(b['world'][1]-a['world'][1]-spacing) <= 5 for a,b in zip(outlets,outlets[1:])):
                continue
            if abs(sum(p['world'][1] for p in outlets)/candidate_count-incoming['world'][1]) > 3.5:
                continue
            for glyph,p in enumerate([incoming,*outlets]):
                p['glyph'] = glyph
                p['glyph_measurement'] = 'complete visible source gap and ordered outlet rows'
    # The V7 scene contains three visible columns. Its per-station geometric
    # registration resolves a selected circle even when the preview stroke
    # obscures its printed dots. Do not discard that independently measured
    # ring before registration. Legacy single-row readers keep their existing
    # resolved-only contract.
    return [p for p in ports if p['glyph'] is not None
            or (retain_acquired and p.get('selected'))]


def _incoming_rim(image, layout, outlets, lane, radius):
    """Visible annular evidence in the registered incoming-port corridor."""
    import numpy as np
    pane=layout['xy'];rgb=np.asarray(image.convert('RGB')).astype(float)
    colour=_palette()[lane*5]
    y=sum(p['world'][1] for p in outlets)/len(outlets)
    low=max(p['world'][0]-102 for p in outlets)
    high=min(p['world'][0]-50 for p in outlets)
    if high<=low:return None
    # Search in operating units; samples still address original image bytes
    # at their calibrated resolution. Nothing is resized or re-encoded.
    xx,yy=np.meshgrid(np.arange(low,high+.2,.4),np.arange(y-3.5,y+3.6,.4))
    centres=np.column_stack((xx.ravel(),yy.ravel()))
    angles=np.arange(96)*2*math.pi/96
    scale=np.asarray([pane['width']/960,pane['height']/490])
    centre_px=centres*scale+[pane['x'],pane['y']]
    offsets=np.column_stack((np.cos(angles),np.sin(angles)))*radius*scale
    sample=np.rint(centre_px[:,None,:]+offsets[None,:,:]).astype(int)
    sample[:,:,0]=np.clip(sample[:,:,0],0,image.width-1)
    sample[:,:,1]=np.clip(sample[:,:,1],0,image.height-1)
    pixels=rgb[sample[:,:,1],sample[:,:,0]]
    # Chroma subsampling moves RGB values on thin rings. Require bright,
    # independently gold pixels distributed around the whole circumference.
    distance=np.max(abs(pixels-colour),axis=2)
    matching=distance<55
    fractions=matching.mean(axis=1)
    quadrants=np.stack([matching[:,k:k+24].mean(axis=1) for k in range(0,96,24)],axis=1)
    valid=(fractions>.72)&(quadrants.min(axis=1)>.42)
    if not valid.any():return None
    score=np.where(valid,fractions-np.minimum(distance,100).mean(axis=1)*.002,-np.inf)
    best=int(score.argmax());centre=centres[best]
    return dict(lane=lane,glyph=0,glyph_measurement='visible gold rim and complete outlet source gap',
                world=centre.tolist(),point=centre_px[best].tolist(),rim_fraction=float(fractions[best]))


def _outlet_rim(image,layout,source,lane,glyph,count,radius,*,proposal=None):
    """Recover a visible coloured rim whose interior is covered by a front.

    The source gap and vertically ordered roles bound the search. The centre
    still requires independent circumference pixels in every quadrant; no
    trajectory, seed, answer or missing-port coordinate is supplied.
    """
    import numpy as np
    pane=layout['xy'];rgb=np.asarray(image.convert('RGB')).astype(float)
    spacing={2:64,3:46,4:34}[count]
    x,y=source['world'];y+=(glyph-1-(count-1)/2)*spacing
    low,high=x+50,x+102
    bottom,top=y-4,y+4
    if proposal is not None:
        # An interior fragment can give a biased free-circle fit even when
        # it retained a label. Use that proposal only to bound the pixel
        # search; the displayed circumference determines the final centre.
        low,high=max(low,proposal['world'][0]-4),min(high,proposal['world'][0]+4)
        bottom,top=max(bottom,proposal['world'][1]-4),min(top,proposal['world'][1]+4)
    xx,yy=np.meshgrid(np.arange(low,high+.01,.4),np.arange(bottom,top+.01,.4))
    centres=np.column_stack((xx.ravel(),yy.ravel()))
    angles=np.arange(96)*2*math.pi/96
    offsets=radius*np.column_stack((np.cos(angles),np.sin(angles)))
    scale=np.asarray([pane['width']/960,pane['height']/490])
    sample=(centres[:,None,:]+offsets[None,:,:])*scale+[pane['x'],pane['y']]
    sample-=.5
    sample[:,:,0]=np.clip(sample[:,:,0],0,image.width-2)
    sample[:,:,1]=np.clip(sample[:,:,1],0,image.height-2)
    low=np.floor(sample).astype(int);weight=sample-low
    x,y=low[:,:,0],low[:,:,1];wx,wy=weight[:,:,0,None],weight[:,:,1,None]
    pixels=(rgb[y,x]*(1-wx)*(1-wy)+rgb[y,x+1]*wx*(1-wy)
            +rgb[y+1,x]*(1-wx)*wy+rgb[y+1,x+1]*wx*wy)
    distance=np.max(abs(pixels-_palette()[lane*5+glyph]),axis=2)
    matching=distance<55;fractions=matching.mean(axis=1)
    quadrants=np.stack([matching[:,k:k+24].mean(axis=1) for k in range(0,96,24)],axis=1)
    valid=(fractions>.72)&(quadrants.min(axis=1)>.42)
    if not valid.any():return None
    score=np.where(valid,fractions-np.minimum(distance,100).mean(axis=1)*.002,-np.inf)
    best=int(score.argmax());centre=centres[best]
    return dict(lane=lane,glyph=glyph,world=centre.tolist(),
        point=(centre*scale+[pane['x'],pane['y']]).tolist(),
        glyph_measurement='visible outlet circumference in registered station row',
        rim_fraction=float(fractions[best]))


def _selection_centres(image, layout, radius):
    """Independent complete outer-ring candidates, excluding long strokes."""
    import numpy as np
    rgb=np.asarray(image.convert('RGB')).astype(float);pane=layout['xy']
    patch=rgb[pane['y']:pane['y']+pane['height'],pane['x']:pane['x']+pane['width']]
    red,green,blue=patch[:,:,0],patch[:,:,1],patch[:,:,2]
    cream=(red>135)&(green>.88*red)&(blue>.53*red)&(blue<.9*red)
    centres=[]
    for component in _pixel_components(cream,minimum=30):
        low,high=component.min(0),component.max(0)
        width=(high[1]-low[1]+1)*960/pane['width']
        height=(high[0]-low[0]+1)*490/pane['height']
        if max(abs(width-2*(radius+4)),abs(height-2*(radius+4)))>4:
            # Near a crossing, the gold signal can join the cream ring's
            # connected component. Its bounding box is then asymmetric.
            # Recover the circular part from fixed-radius votes, retaining
            # the independent circumference check below.
            if max(width,height)<=200:
                centre=_cream_ring_centre(component,image,layout,radius,rgb=rgb)
                if centre is not None:centres.append(centre)
            continue
        centre=[float((low[1]+high[1]+1)/2*960/pane['width']),
                float((low[0]+high[0]+1)/2*490/pane['height'])]
        # A box alone is insufficient: independently require a circular
        # ring around the measured centre before altering port proposals.
        if visible_selection(image,layout,[dict(world=centre)],radius):
            centres.append(centre)
    return [_refine_selection_centre(image,layout,centre,radius,rgb=rgb)
            for centre in centres]


def _refine_selection_centre(image,layout,centre,radius,*,rgb):
    """Fit the known outer circle with equal weight per angular sample.

    A full preview adds a long cream stroke to the ring component. Counting
    all of its pixels can bias a free circle fit toward that stroke. The
    displayed radius and colour let the exposed circumference determine the
    centre instead. Bilinear pixel reads do not alter the original image.
    """
    import numpy as np
    pane=layout['xy'];scale=np.asarray([pane['width']/960,pane['height']/490])
    xx,yy=np.meshgrid(np.arange(-2,2.001,.2),np.arange(-2,2.001,.2))
    candidates=np.asarray(centre)+np.column_stack((xx.ravel(),yy.ravel()))
    angles=np.arange(96)*2*math.pi/96
    offsets=(radius+4)*np.column_stack((np.cos(angles),np.sin(angles)))
    coordinates=(candidates[:,None,:]+offsets[None,:,:])*scale+[pane['x'],pane['y']]
    coordinates-=.5
    coordinates[:,:,0]=np.clip(coordinates[:,:,0],0,image.width-2)
    coordinates[:,:,1]=np.clip(coordinates[:,:,1],0,image.height-2)
    low=np.floor(coordinates).astype(int);weight=coordinates-low
    x,y=low[:,:,0],low[:,:,1];wx,wy=weight[:,:,0,None],weight[:,:,1,None]
    samples=(rgb[y,x]*(1-wx)*(1-wy)+rgb[y,x+1]*wx*(1-wy)
             +rgb[y+1,x]*(1-wx)*wy+rgb[y+1,x+1]*wx*wy)
    cost=np.minimum(np.max(abs(samples-[255,244,183]),axis=2),80).mean(axis=1)
    fitted=candidates[int(cost.argmin())].tolist()
    return fitted if visible_selection(image,layout,[dict(world=fitted)],radius,_rgb=rgb) else centre


def _cream_ring_centre(component,image,layout,radius,*,rgb):
    import numpy as np
    pane=layout['xy'];scale=np.asarray([pane['width']/960,pane['height']/490])
    angles=np.linspace(0,2*math.pi,96,endpoint=False)
    offsets=np.unique(np.round(np.column_stack((np.cos(angles),np.sin(angles)))*(radius+4)*scale).astype(int),axis=0)
    points=component[:,::-1]
    votes=(points[:,None,:]-offsets[None,:,:]).reshape(-1,2)
    low=votes.min(0);votes-=low;shape=votes.max(0)+1
    counts=np.bincount(votes[:,1]*shape[0]+votes[:,0],minlength=int(shape[0]*shape[1]))
    attempted=[]
    for index in np.argsort(counts)[-96:][::-1]:
        point=np.asarray([index%shape[0],index//shape[0]])+low+.5
        centre=point/scale
        if any(np.linalg.norm(centre-p)<2 for p in attempted):continue
        attempted.append(centre)
        if not visible_selection(image,layout,[dict(world=centre.tolist())],radius,_rgb=rgb):continue
        # Fit exposed outer-ring pixels; the nearby signal and cancellation
        # stroke are outside this annulus and cannot displace its centre.
        world=(points+.5)/scale
        ring=world[abs(np.linalg.norm(world-centre,axis=1)-(radius+4))<1.5]
        if len(ring)<30:continue
        for _ in range(3):
            origin=ring.mean(0);q=ring-origin
            a=np.column_stack((2*q[:,0],2*q[:,1],np.ones(len(q))))
            c=np.linalg.lstsq(a,(q*q).sum(1),rcond=None)[0]
            fitted=origin+c[:2];r=math.sqrt(max(0,c[2]+sum(c[:2]**2)))
            ring=ring[abs(np.linalg.norm(ring-fitted,axis=1)-r)<.9]
            if len(ring)<30:break
        if len(ring)>=30 and abs(r-radius-4)<1 and np.linalg.norm(fitted-centre)<2:
            value=fitted.tolist()
            if visible_selection(image,layout,[dict(world=value)],radius,_rgb=rgb):return value
    return None


def jpeg_depths(image, layout, *, incoming_ports=None, front_count=None):
    """Locate the filled colour cores above the linked reconstruction lines."""
    import numpy as np
    rgb = np.asarray(image.convert('RGB')).astype(float)
    palette = _palette()
    depths = {}
    for view in ('xz', 'yz', 'mesh'):
        pane = layout[view]
        patch = rgb[pane['y']:pane['y']+pane['height'], pane['x']:pane['x']+pane['width']]
        distances = np.sqrt(((patch[:, :, None, :]-palette)**2).sum(3))
        best, close = distances.argmin(2), distances.min(2) < 40
        markers = []
        for lane in range(3):
            for glyph in range(5):
                for blob in _pixel_components(close & (best == lane*5+glyph), minimum=3):
                    low, high = blob.min(0), blob.max(0)
                    h, w = high-low+1
                    if not (2 <= w <= 15 and 2 <= h <= 17 and .35 < w/h < 2):
                        continue
                    y, x = (low+high+1)/2
                    markers.append(dict(point=[float(x/pane['width']*260), float(y/pane['height']*145)],
                                        incoming=glyph == 0, lane=lane, glyph=glyph))
        depths[view] = markers
        if view=='xz' and incoming_ports is not None and front_count is not None:
            # A travelling gold signal can merge with an incoming depth dot,
            # making the whole component wider than a marker. Cross-register
            # its exposed gold pixels using the independently measured XY
            # source x and the visible lane band; no answer or true z enters.
            nominal_z={1:[0],2:[-40,40],3:[-60,0,60]}[front_count]
            yy,xx=np.indices(patch.shape[:2]);xx=(xx+.5)*260/pane['width'];yy=(yy+.5)*145/pane['height']
            for port in incoming_ports:
                if port['glyph']!=0:continue
                lane=port['lane'];sx=port['world'][0]*.25+10
                if any(p['incoming'] and p['lane']==lane and abs(p['point'][0]-sx)<3 for p in markers):continue
                # The overlaid signal is gold in every lane, while source
                # correspondence colours vary by lane. Classify the merged
                # gold evidence by its independently visible XY source and
                # registered depth band, not the signal's nearest palette
                # colour (which otherwise assigns it to lane zero).
                gold=(close&((best%5)==0))|((patch[:,:,0]>215)&(patch[:,:,1]>175)&(patch[:,:,2]<180))
                local=gold&(abs(xx-sx)<1.5)&(abs(yy-(72+nominal_z[lane]*.45))<10)
                blobs=_pixel_components(local,minimum=3)
                if not blobs:continue
                blob=np.concatenate(blobs);rows=yy[blob[:,0],blob[:,1]]
                if rows.max()-rows.min()>7:continue
                point=[float(np.mean(xx[blob[:,0],blob[:,1]])),float(np.mean(rows))]
                markers.append(dict(point=point,incoming=True,lane=lane,glyph=0,
                    measurement='gold pixels cross-registered to visible source x'))
    return depths


def visible_selection(image, layout, ports, radius, *, _rgb=None):
    """Read the outer cream ring that marks an acquired moving port.

    Requiring support around half the circumference excludes a cursor, a
    passing signal and the small cancellation preview. An ambiguous ring
    is rejected; an acquisition identity never comes from hidden state.
    """
    import numpy as np
    rgb = np.asarray(image.convert('RGB')).astype(float) if _rgb is None else _rgb
    pane = layout['xy']
    selected = []
    for port in ports:
        support = 0
        for angle in np.linspace(0, 2*math.pi, 64, endpoint=False):
            hits = []
            for extra in (-1, 0, 1):
                r = radius+4+extra
                x = round(pane['x']+(port['world'][0]+r*math.cos(angle))*pane['width']/960)
                y = round(pane['y']+(port['world'][1]+r*math.sin(angle))*pane['height']/490)
                if not (0 <= x < image.width and 0 <= y < image.height):
                    continue
                red, green, blue = rgb[y, x]
                hits.append(red > 135 and green > .88*red and .53*red < blue < .9*red)
            support += any(hits)
        if support >= 32:
            selected.append(port)
    return selected if len(selected) == 1 else []


def phase_from_visible(displacement, heading, clock_ms, amplitude, span_ms, *, error=1.0):
    """Decode the visible calibration lattice; no seed search or future read.

    Heading distinguishes the two sides of a reflection. The four-unit
    initial calibration spacing is strictly wider than twice the admitted
    centre error. At a wall the encoded branch follows the renderer's
    half-open phase convention; tissue-clock sign is handled separately.
    Rejection reports a measurement problem rather than a private fallback.
    """
    if not 0 <= error < 2 or heading not in (-1, 1):
        raise ValueError('invalid visible measurement bound or heading')
    period = 4*amplitude
    candidates = []
    for initial in range(0, int(period), 4):
        phase = (initial+2*amplitude*clock_ms/span_ms) % period
        value, sign = (phase-amplitude, 1) if phase < 2*amplitude else (3*amplitude-phase, -1)
        if sign == heading and abs(value-displacement) <= error:
            candidates.append(initial)
    if len(candidates) != 1:
        raise ValueError('visible phase is unresolved: '+str(candidates))
    return candidates[0]


def phase_value(initial, clock_ms, amplitude, span_ms):
    phase = (initial+2*amplitude*clock_ms/span_ms) % (4*amplitude)
    return phase-amplitude if phase < 2*amplitude else 3*amplitude-phase


def observable_motion_state(measurements, *, level, t_ms, drift_ms, drift_heading):
    """Finite task-motion state recovered from visible centres and arrows.

    ``measurements`` contains cell/glyph correspondence, XY centres, and
    tissue/flex arrow headings. Time, signed drift time and global heading
    are the duplicated visible flow instruments. No contract, seed, past
    frame, private port identity or future knot is accepted by this decoder.
    Static depths, bridge identity and repair/motor state are separate
    visible/input-history components of the full task state.
    """
    p = PROFILES[level]
    nominal_y = {1:[245], 2:[155,345], 3:[88,245,402]}[p['front_count']]
    result = {}
    for lane in range(p['front_count']):
      for column in range(3):
        row = [v for v in measurements if (v['lane'], v['column']) == (lane, column)]
        source = next(v for v in row if v['glyph'] == 0)
        x0 = (165,465,765)[column]
        horizontal = phase_from_visible(source['world'][0]-x0,
            source['headings'][0]*drift_heading, drift_ms, p['drift_px'], p['span_ms'])
        vertical = phase_from_visible(source['world'][1]-nominal_y[lane],
            source['headings'][1], t_ms, 14, p['span_ms'])
        exact_dx = phase_value(horizontal, drift_ms, p['drift_px'], p['span_ms'])
        flex = {}
        for outlet in row:
            if outlet['glyph']:
                flex[outlet['glyph']] = phase_from_visible(outlet['world'][0]-x0-76-exact_dx,
                    outlet['headings'][0], t_ms, 24, p['span_ms']+317)
        if len(flex) != p['candidate_count']:
            raise ValueError('incomplete visible outlet row')
        result[lane,column] = dict(horizontal=horizontal, vertical=vertical, flex=flex)
    return dict(level=level, t_ms=t_ms, drift_ms=drift_ms, drift_heading=drift_heading, cells=result)


def observable_position(state, lane, column, glyph, t_ms, *, future_joins=()):
    """Exact motion kernel from the decoded state and planned action times."""
    p = PROFILES[state['level']]
    clock, previous, heading = state['drift_ms'], state['t_ms'], state['drift_heading']
    for at in future_joins:
        if at > t_ms:
            break
        clock += heading*(at-previous)
        previous, heading = at, -heading
    clock += heading*(t_ms-previous)
    cell = state['cells'][lane,column]
    x = phase_value(cell['horizontal'], clock, p['drift_px'], p['span_ms'])
    y = phase_value(cell['vertical'], t_ms, 14, p['span_ms'])
    flex = phase_value(cell['flex'][glyph], t_ms, 24, p['span_ms']+317) if glyph else 0
    spacing = 34 if p['candidate_count'] == 4 else 46 if p['candidate_count'] == 3 else 64
    offset = (glyph-1-(p['candidate_count']-1)/2)*spacing if glyph else 0
    return [(165,465,765)[column]+(76 if glyph else 0)+x+flex,
            {1:[245],2:[155,345],3:[88,245,402]}[p['front_count']][lane]+offset+y+flex/16]


def jpeg_motion_measurements(image, *, level, layout=None):
    """Read V7 centre/heading geometry from the original JPEG pixels only."""
    import numpy as np
    layout = layout or pixel_layout(image)
    ports = jpeg_ports(image, layout, candidate_count=PROFILES[level]['candidate_count'],
                       port_radius=PROFILES[level]['port_radius'], retain_acquired=True)
    count=PROFILES[level]['candidate_count']
    # Station centres remain disjoint before the ring's role is known.
    # Relative to material_x+38, any source/outlet lies in [-90,114],
    # even at D5 extrema; neighbouring station centres are 300 units apart.
    # Treating an unresolved outlet as a source instead moves that boundary
    # 38 units left and can incorrectly put it in the next station.
    column_centres=(203,503,803)
    for port in ports:
        port['column']=min(range(3),key=lambda col:abs(port['world'][0]-column_centres[col]))
    # V7 keeps all three station rows visible. Register each row separately;
    # the legacy reader's single-open-row test must not pool their outlets.
    for lane in range(PROFILES[level]['front_count']):
      for column in range(3):
        row=[v for v in ports if (v['lane'],v['column'])==(lane,column)]
        if len(row)>=2:
            source=min(row,key=lambda v:v['world'][0])
            ordered=sorted((v for v in row if v is not source),key=lambda v:v['world'][1])
            spacing={2:64,3:46,4:34}[count]
            nominal_y={1:[245],2:[155,345],3:[88,245,402]}[PROFILES[level]['front_count']][lane]
            proposed={}
            if (abs(source['world'][1]-nominal_y)<=15
                    and all(50<=v['world'][0]-source['world'][0]<=102 for v in ordered)):
                for port in ordered:
                    offset=port['world'][1]-source['world'][1]
                    glyph=round(offset/spacing+(count-1)/2)+1
                    expected=(glyph-1-(count-1)/2)*spacing
                    if not 1<=glyph<=count or abs(offset-expected)>4 or glyph in proposed:
                        proposed={};break
                    proposed[glyph]=port
            if proposed:
                source['glyph']=0
                for glyph in range(1,count+1):
                    if glyph not in proposed:
                        recovered=_outlet_rim(image,layout,source,lane,glyph,count,PROFILES[level]['port_radius'])
                        if recovered is None:raise ValueError('outlet circumference is unresolved')
                        recovered['column']=column;ports.append(recovered);row.append(recovered)
                        proposed[glyph]=recovered
                    elif not proposed[glyph].get('selected'):
                        refined=_outlet_rim(image,layout,source,lane,glyph,count,
                            PROFILES[level]['port_radius'],proposal=proposed[glyph])
                        if refined is None:raise ValueError('outlet circumference is unresolved')
                        proposed[glyph].update(refined)
                    proposed[glyph]['glyph']=glyph
                    proposed[glyph]['glyph_measurement']='visible station gap and ordered outlet rows'
        outlets=sorted([v for v in row if v['glyph']!=0],key=lambda v:v['world'][1])
        if len(outlets)!=count:
            raise ValueError('incomplete visible candidate row')
        for glyph,port in enumerate(outlets,1):port['glyph']=glyph
        sources=[v for v in row if v['glyph']==0]
        if not (sources and sources[0].get('selected')):
            incoming=_incoming_rim(image,layout,outlets,lane,PROFILES[level]['port_radius'])
            if incoming is None:raise ValueError('incoming circumference is unresolved')
            if sources:sources[0].update(incoming)
            else:ports.append(dict(incoming,lane=lane,column=column,glyph=0))
    rgb = np.asarray(image.convert('RGB')).astype(int)
    pane, radius = layout['xy'], PROFILES[level]['port_radius']

    def arrow(cx, cy, axis):
        px = pane['x']+cx*pane['width']/960
        py = pane['y']+cy*pane['height']/490
        x0,x1=max(0,round(px-7)),min(image.width,round(px+8))
        y0,y1=max(0,round(py-7)),min(image.height,round(py+8))
        patch = rgb[y0:y1,x0:x1]
        yy,xx = np.nonzero(np.max(abs(patch-[102,231,239]),axis=2)<38)
        if len(xx)<3:
            return None
        dx=(xx+x0+.5-px)*960/pane['width']
        dy=(yy+y0+.5-py)*490/pane['height']
        along,across=(dx,dy) if axis==0 else (dy,dx)
        # A preview can cover the arrowhead while leaving one end of the
        # symmetric shaft. Its remaining-pixel centroid then points the wrong
        # way. Require the off-shaft wings in the actual arrow footprint;
        # an occluded copy contributes no heading, while its exposed duplicate
        # supplies the same visible direction.
        wings=(abs(across)>.9)&(abs(across)<3.2)&(abs(along)>.25)&(abs(along)<4.2)
        positive=int((wings&(along>0)).sum())
        negative=int((wings&(along<0)).sum())
        if max(positive,negative)<1 or positive==negative:
            return None
        if max(positive,negative)<.7*(positive+negative):
            return None
        return 1 if positive>negative else -1

    for port in ports:
        # Tissue translation/flex ranges leave adjacent columns disjoint.
        port['column']=min(range(3),key=lambda col:abs(port['world'][0]-column_centres[col]))
        x,y=port['world'];headings=[]
        for axis in range(1 if port['glyph'] else 2):
            signs=[arrow(x+side*(radius+13),y+(0 if port['glyph'] else -7 if axis==0 else 7),axis) for side in (-1,1)]
            resolved=[h for h in signs if h is not None]
            if not resolved or len(set(resolved)) != 1:
                raise ValueError('visible heading unresolved at '+str((port['lane'],port['column'],port['glyph'],axis,signs)))
            headings.append(resolved[0])
        port['headings']=headings
    return ports


class ObservableSimulation(Simulation):
    """Task kernel on visible state, with opaque generator state removed.

    ``state`` contains decoded phases/instruments, depth/bridge roles, repair
    flags and the motor preview reconstructed from the visible highlight and
    own inputs. Depth/bridge classifications are supplied by visible evidence;
    the model reads no private answer fallback, motion seed, opaque identity
    or earlier frame. This is a planning/model-checking object, not an input
    route and not a claim to have executed a screenshot-only native policy.
    The inherited contact/commit rules retain the complete primitive space.
    """
    def __init__(self,state,mode):
        self.observable=state
        p=PROFILES[state['level']]
        ys={1:[245],2:[155,345],3:[88,245,402]}[p['front_count']]
        zs={1:[0],2:[-40,40],3:[-60,0,60]}[p['front_count']]
        stations=[]
        for (lane,column),cell in state['cells'].items():
            key=f'l{lane}c{column}';x=(165,465,765)[column]
            count=p['candidate_count'];spacing=34 if count==4 else 46 if count==3 else 64
            candidates=[dict(id=f'{key}p{glyph}',glyph=glyph,p=[x+76,ys[lane]+(glyph-1-(count-1)/2)*spacing,
                zs[lane] if glyph==cell['correct_glyph'] else zs[lane]+(1 if (glyph-1)%2 else -1)*(p['depth_gap']+8*(glyph-1))]) for glyph in range(1,count+1)]
            stations.append(dict(id=key,lane=lane,column=column,material_x=x,
                source=dict(id=key+'p0',glyph=0,p=[x,ys[lane],zs[lane]]),candidates=candidates,bridge_to=f"{key}p{cell['bridge_glyph']}",motion_seed=0))
        contract=dict(revision='living-fibre-7',parameters=p,stations=stations,
            fronts=[dict(start_x=0,y=ys[i],z=zs[i],speed_seed=f['rate_index']) for i,f in enumerate(state['flow'])],
            finish_x=925,max_ms=100000,interaction=mode)
        super().__init__(contract)
        self.ms=state['t_ms'];self.started=True
        self.x_units=[f['signal_units'] for f in state['flow']];self.x=[v/100000 for v in self.x_units]
        for st in stations:
            cell=state['cells'][st['lane'],st['column']];key=st['id']
            if cell['open']:self.open.add(key)
            if cell['cut']:self.cut.add(key)
            if cell['joined']:self.join[key]=f"{key}p{cell['correct_glyph']}"
            if cell['crossed']:self.crossed.add(key)
        motor=state.get('motor',{})
        def acquired(role):
            if role is None:return None
            lane,col,glyph=role;key=f'l{lane}c{col}';return (key,f'{key}p{glyph}')
        self.tool=motor.get('tool','stitch')
        if motor.get('hold'):
            hold=motor['hold'];self.hold=(hold['tool'],hold['point'],acquired(hold.get('role')))
        if motor.get('selected'):
            selected=motor['selected'];self.selected=dict(point=selected['point'],port=acquired(selected.get('role')))

    def position(self,station,port,ms=None):
        at=self.ms if ms is None else ms
        xy=observable_position(self.observable,station['lane'],station['column'],port['glyph'],at,future_joins=self.recoils)
        cell=self.observable['cells'][station['lane'],station['column']];p=self.c['parameters']
        y=phase_value(cell['vertical'],at,14,p['span_ms'])
        flex=phase_value(cell['flex'][port['glyph']],at,24,p['span_ms']+317) if port['glyph'] else 0
        return [*xy,port['p'][2]+18*y/14+flex/16]

    def summary(self):
        result=super().summary()
        clock,previous,heading=self.observable['drift_ms'],self.observable['t_ms'],self.observable['drift_heading']
        for at in self.recoils:
            clock+=heading*(at-previous);previous,heading=at,-heading
        result['motion_clock_ms']=clock+heading*(self.ms-previous)
        return result


def compile_visible_program(state, mode, *, contact_interval_ms=80):
    """Freeze an active repair program from one decoded V7 observation.

    This is the stronger preplanned diagnostic from continuation audit 5.
    It accepts visible state only, predicts its own recoil/rate effects and
    never observes the executing game. Extraction of ``state`` is a separate
    evidence boundary; ideal fixtures do not establish screenshot extraction.
    It demonstrates successful planning, not Bellman-optimality, native
    timing tolerance or passive preparation. It leaves the game unchanged.

    The diagnostic starts with Begin already recorded, no repairs and no
    preview. This scope is not a restriction on the real-time control domain.
    Returned events include that Begin prefix and administrative submission.
    """
    if mode not in ('full', 'simplified'):
        raise ValueError('unsupported interaction')
    if contact_interval_ms < 10 or contact_interval_ms % 10:
        raise ValueError('diagnostic spacing must be a positive whole task tick')
    motor = state.get('motor', {})
    if motor.get('hold') or motor.get('selected'):
        raise ValueError('compiled initial-state diagnostic requires no preview')
    if any(cell[key] for cell in state['cells'].values()
           for key in ('cut', 'joined', 'crossed')):
        raise ValueError('compiled initial-state diagnostic requires no repairs')
    model = ObservableSimulation(copy.deepcopy(state), mode)
    events = [dict(sequence=1, t_ms=0, kind='begin', input_source='button')]

    def emit(at, kind, point=None, tool=None):
        model.advance(at)
        if model.failed or model.done:
            raise ValueError('compiled program reached a terminal state before contact')
        event = dict(sequence=len(events)+1, t_ms=model.ms, kind=kind,
                     input_source='button' if kind == 'tool' else mode)
        if point is not None:
            event['point'] = list(point)
        if tool is not None:
            event['tool'] = tool
        events.append(event)
        model.input(kind, point, mode, tool)

    gap = contact_interval_ms
    while not model.done and not model.failed:
        pending = [st for st in model.c['stations'] if st['id'] in model.open
                   and (st['id'] not in model.cut or st['id'] not in model.join)]
        pending.sort(key=lambda st: (st['material_x']-model.x[st['lane']],
                                     st['lane'], st['column']))
        if not pending:
            model.advance(model.ms+100)
            continue
        st = pending[0]
        if st['id'] not in model.cut:
            emit(model.ms, 'tool', tool='cut')
            release = model.ms+(2*gap if mode == 'full' else gap)
            destination = next(p for p in st['candidates'] if p['id'] == st['bridge_to'])
            a = model.position(st, st['source'], release)
            b = model.position(st, destination, release)
            midpoint = [(a[i]+b[i])/2 for i in range(2)]
            if mode == 'full':
                emit(model.ms+gap, 'down', [midpoint[0], midpoint[1]-45])
                emit(model.ms+gap, 'up', [midpoint[0], midpoint[1]+45])
            else:
                emit(model.ms+gap, 'click', midpoint)
            if st['id'] not in model.cut or model.failed:
                raise ValueError('compiled knife contact failed')
        if st['id'] not in model.join:
            emit(model.ms+gap, 'tool', tool='stitch')
            destination = next(p for p in st['candidates']
                               if p['p'][2] == st['source']['p'][2])
            point = model.position(st, st['source'], model.ms+gap)[:2]
            emit(model.ms+gap, 'down' if mode == 'full' else 'click', point)
            point = model.position(st, destination, model.ms+gap)[:2]
            emit(model.ms+gap, 'up' if mode == 'full' else 'click', point)
            if st['id'] not in model.join or model.failed:
                raise ValueError('compiled stitch contact failed')
        model.advance(model.ms+gap)
    if not model.done or model.failed:
        raise ValueError('compiled program cannot complete this initial state')
    events.append(dict(sequence=len(events)+1, t_ms=model.ms,
                       kind='submit', input_source='button'))
    return events
