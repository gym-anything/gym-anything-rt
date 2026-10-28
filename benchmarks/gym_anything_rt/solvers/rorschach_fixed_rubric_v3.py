"""Construction oracle. Privileged read-only planning; send() supplies all inputs.

Native evidence supplies send() via the frozen downstream HTTP gateway. A local
Playwright adapter is an implementation check, never action-space evidence.
"""
from __future__ import annotations

import time

COLORS = ((18,124,131),(198,89,73),(121,93,154))


def concealed_centres_from_pixels(png):
    """Locate the visible neutral ? discs without task or DOM state."""
    from io import BytesIO
    from PIL import Image
    im=Image.open(BytesIO(png)).convert('RGB')
    width,height=im.size;pixels=im.load()
    points={(x,y) for y in range(height) for x in range(width) if pixels[x,y]==(118,104,121)}
    discs=[]
    while points:
        first=points.pop();stack=[first];component=[first]
        while stack:
            x,y=stack.pop()
            for q in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if q in points:
                    points.remove(q);stack.append(q);component.append(q)
        xs,ys=zip(*component);w=max(xs)-min(xs)+1;h=max(ys)-min(ys)+1
        if 100<len(component)<1500 and 15<=w<=40 and 15<=h<=40:
            discs.append([(min(xs)+max(xs))/2,(min(ys)+max(ys))/2])
    discs.sort()
    assert len(discs) in (2,3),discs
    return [discs[0],discs[-1]]+([discs[1]] if len(discs)==3 else [])


def registration_geometry_from_pixels(png,level):
    """Measure coloured ink discs and aperture rings in a rendered bitmap.

    Profile radii are configuration constants, not generated-instance truth.
    Colour tolerance includes the translucent fit fill painted over a disc.
    """
    from io import BytesIO
    import numpy as np
    from PIL import Image
    image=np.asarray(Image.open(BytesIO(png)).convert('RGB'),dtype=np.int32)
    height,width=image.shape[:2]
    radius={1:58,2:54,3:50,4:46,5:42}[level]*width/920
    def circle(mask,r):
        yy,xx=np.nonzero(mask);votes=np.zeros((height,width),dtype=np.int16)
        for angle in np.linspace(0,2*np.pi,64,endpoint=False):
            x=xx-round(r*np.cos(angle));y=yy-round(r*np.sin(angle))
            valid=(x>=0)&(x<width)&(y>=0)&(y<height)
            np.add.at(votes,(y[valid],x[valid]),1)
        y,x=np.unravel_index(np.argmax(votes),votes.shape)
        assert votes[y,x]>=28,('registration circle is not visually resolved',int(votes[y,x]),r)
        return [int(x),int(y)]
    ink=[];pads=[]
    for rgb in COLORS[:2 if level<=2 else 3]:
        mask=np.sum((image-np.array(rgb))**2,axis=2)<32**2
        ink.append(circle(mask,11*width/920));pads.append(circle(mask,radius))
    return dict(ink=ink,pads=pads)


def inspect_and_prepare_pixels(ui, *, level, interaction):
    """Discover the correspondence and seat apertures using bitmap facts only.

    ui.read is used solely for visible control rectangles. ui.capture returns
    the canvas PNG. No generated geometry, correspondence, clock, archive text
    or other page state supplies a discovery or preparation decision.
    """
    import math
    field=rect(ui,'.inkv2-field')
    png=ui.capture('.inkv2-field');unknown=concealed_centres_from_pixels(png)
    assert len(unknown)==(2 if level<=2 else 3)
    screen=lambda q:[round(field[0]+q[0]),round(field[1]+q[1])]
    for point in unknown:ui.send([{'mouse':{'move':screen(point)}}])
    discovered=ui.capture('.inkv2-field')
    geometry=registration_geometry_from_pixels(discovered,level)
    registration=[min(range(len(unknown)),key=lambda j:math.dist(point,unknown[j])) for point in geometry['ink']]
    assert sorted(registration)==list(range(len(unknown)))
    proxies=[centre(ui,f'.ink-proxy[data-pad="{i}"]') for i in range(len(unknown))] if interaction=='simplified' else []
    def aim(i,goal):
        if interaction=='full':
            pad=registration_geometry_from_pixels(ui.capture('.inkv2-field'),level)['pads'][i]
            ui.send([{'mouse':{'move':screen(pad),'buttons':{'left_down':True}}},
                     {'mouse':{'move':screen(goal)}},{'mouse':{'buttons':{'left_up':True}}}])
        else:
            ui.send([{'mouse':{'left_click':[round(v) for v in proxies[i]]}},
                     {'mouse':{'left_click':screen(goal)}}])
    # Parking avoids ambiguous grabs when a different aperture still occupies
    # a discovered target. These are ordinary reversible preparation moves.
    for i in range(len(unknown)):aim(i,[110+270*i,65])
    for i,goal in enumerate(geometry['ink']):aim(i,goal)
    final=registration_geometry_from_pixels(ui.capture('.inkv2-field'),level)
    assert all(math.dist(a,b)<=6 for a,b in zip(final['pads'],final['ink'])),final
    return dict(registration=registration,initial_neutral_centres=unknown,
                discovered_geometry=geometry,prepared_geometry=final,
                information='Canvas bitmap pixels only; DOM reads restricted to visible control rectangles.')

READ = "({s:livingInkModel.state,p:livingInkModel.press.snapshot(),result:livingInkModel.result||null,grade:livingInkModel.grade||null,finished:livingInkModel.finished})"


def rect(ui, selector):
    return ui.read("(() => {const r=document.querySelector("+repr(selector)+").getBoundingClientRect();return [r.x,r.y,r.width,r.height];})()")


def click(ui, point):
    return ui.send([{"mouse":{"left_click":[round(v) for v in point]}}])


def centre(ui, selector):
    r=rect(ui,selector)
    return [r[0]+r[2]/2,r[1]+r[3]/2]


def solve(ui, truth=None, *, interval=.12, limit=240, registration=None, prepared=False):
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.rorschach_fixed_rubric_v3 import ink_centres
    context=ui.read(READ)
    state=context['s']
    if truth is not None:
        assert truth['challenge_id']==state['challenge_id']
    mode=(state.get('control_condition') or {}).get('interaction','full')
    field=rect(ui,'.inkv2-field')
    proxies=[centre(ui,f'.ink-proxy[data-pad="{i}"]') for i in range(len(state['labels']))] if mode=='simplified' else []
    screen=lambda p:[round(field[0]+p[0]*field[2]/920),round(field[1]+p[1]*field[3]/440)]
    # Restore V1's inspect/learn/act path without a probe quota. All discoveries
    # are ordinary pointer input; geometry is privileged oracle planning here.
    # The evidence driver separately locates the concealed centres in pixels.
    if registration is None:
        for i in range(len(state['labels'])):
            point=ink_centres(state,ui.read(READ)['p']['t_ms'])[i]
            ui.send([{'mouse':{'move':screen(point)}}])
        marks=ui.read("Array.from(document.querySelectorAll('.ink-mark-archive span'),n=>n.textContent)")
        registration=[None]*len(state['labels'])
        for contact,mark in enumerate(marks):
            assert '→ APERTURE ' in mark,marks
            registration[int(mark.rsplit(' ',1)[1])-1]=contact
    else:
        registration=list(registration)
        assert sorted(registration)==list(range(len(state['labels'])))
        marks='Externally supplied registration learned from canvas pixels.'
    def targets(t):
        points=ink_centres(state,t)
        return [points[i] for i in registration]
    # Safe reversible preparation seats the discovered correspondence before
    # starting. Keep the frozen V2 motor law and active-flow timing unchanged.
    if not context['p']['started'] and not prepared:
        for i in range(len(state['labels'])):
            pad=ui.read(READ)['p']['pads'][i];goal=[110+270*i,65]
            if mode=='full':
                ui.send([{'mouse':{'move':screen(pad['p']),'buttons':{'left_down':True}}},
                         {'mouse':{'move':screen(goal)}},{'mouse':{'buttons':{'left_up':True}}}])
            else:
                ui.send([{'mouse':{'left_click':[round(v) for v in proxies[i]]}},
                         {'mouse':{'left_click':screen(goal)}}])
        for i,goal in enumerate(targets(0)):
            pad=ui.read(READ)['p']['pads'][i]
            if mode=='full':
                ui.send([{'mouse':{'move':screen(pad['p']),'buttons':{'left_down':True}}},
                         {'mouse':{'move':screen(goal)}},{'mouse':{'buttons':{'left_up':True}}}])
            else:
                ui.send([{'mouse':{'left_click':[round(v) for v in proxies[i]]}},
                         {'mouse':{'left_click':screen(goal)}}])
    click(ui,centre(ui,'.ink-begin'))
    count=1
    while count<limit:
        row=ui.read(READ)
        if row['finished']: break
        p=row['p']
        # Compensate the visible aperture motor's damping lag. The target used
        # here lies inside the exact 1.2-second preview drawn on the normal UI.
        lag=state['parameters']['damping']/state['parameters']['spring']
        target=targets(p['t_ms']+1000*(lag+.12))
        actions=[]
        for i,(pad,goal) in enumerate(zip(p['pads'],target)):
            if mode=='full':
                actions += [{'mouse':{'move':screen(pad['p']),'buttons':{'left_down':True}}},
                            {'mouse':{'move':screen(goal)}}, {'mouse':{'buttons':{'left_up':True}}}]
            else:
                actions += [{'mouse':{'left_click':[round(v) for v in proxies[i]]}},
                            {'mouse':{'left_click':screen(goal)}}]
        ui.send(actions);count+=1
        ui.wait(interval)
    else:
        raise AssertionError('Declared living-ink construction request budget exhausted')
    ui.wait(.2)
    row=ui.read(READ)
    if row['grade'] is None:
        ui.wait(.3);row=ui.read(READ)
    assert row['grade'] and row['grade']['passed'],row
    return dict(oracle='privileged read-only state, geometry and visible-preview planning',
                registration_marks=marks,requests=count,final=row['p'],server_grade=row['grade'])
