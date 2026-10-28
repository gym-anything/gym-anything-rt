"""Privileged dye-plant oracle with an injected mouse action transport.

``ui.read`` is disclosed privileged planning. Every actual input uses ``ui.send``
and the frozen downstream action dictionary, including physical handle drags.
The caller must supply the approved HTTP transport for native validation.
Headless Playwright tests use a separate transport and cannot establish parity.
"""
import math
import time

from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.two_lamp_dyeworks_v3 import quantize, rail, stock_strength


def desired_settings(contract, target_density, active_ms, anticipation_ms=200):
    """Invert the common pump for the locally visible incoming stock.

    The default lookahead is 200ms; the live oracle uses 450ms to allow for
    sequential physical input. Both stay inside the rendered 3.5s stock trace.
    Target concentrations are privileged; no future stock beyond that visible
    horizon is used. It is a wiring oracle, not a screenshot-only agent.
    """
    physics = contract['physics']
    strengths = [stock_strength(contract['stock'][p['id']],max(0,active_ms)+anticipation_ms)
                 for p in contract['pigments']]
    base = [[density/(physics['supply_scale']*strengths[i]) for i,density in enumerate(row)]
            for row in target_density]
    denominator = 1-physics['coupling']*sum(map(sum,base))
    if denominator <= 0:
        raise ValueError('requested dye equilibrium exceeds pump capacity')
    return [[quantize(value/denominator) for value in row] for row in base]


def _rect(ui, selector):
    return ui.read(f'(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; }})()')


def _center(rect):
    return [rect[0]+rect[2]/2,rect[1]+rect[3]/2]


def solve(ui, truth, interval_seconds=.25, budget_seconds=100):
    """Complete through literal mouse input; deadline and cadence are explicit."""
    rect = _rect(ui,'#dye-v2-canvas')
    simple = truth.get('control_condition',{}).get('interaction') == 'simplified'
    def screen(point):
        return [rect[0]+point[0]*rect[2]/1120,rect[1]+point[1]*rect[3]/500]
    def apply(desired, current):
        actions = []
        for v,row in enumerate(desired):
            for i,value in enumerate(row):
                if abs(value-current[v][i]) < .009:
                    continue
                x,y,width = rail(truth,v,i)
                end = screen([x+width*value,y])
                if simple:
                    actions.append({'mouse':{'left_click':end}})
                else:
                    start = screen([x+width*current[v][i],y])
                    actions.extend([{'mouse':{'move':start,'buttons':{'left_down':True}}},
                                    {'mouse':{'move':end}},
                                    {'mouse':{'buttons':{'left_up':True}}}])
        if actions:
            ui.send(actions)
    snapshot = '({summary:twoLampDyeworksV3Model.sim.summary(),terminal:twoLampDyeworksV3Model.terminal,outcome:twoLampDyeworksV3Model.outcome||null})'
    initial = ui.read(snapshot)
    # Use each actual inlet spot test before acting on its dye identity.
    # Truth-based planning below remains explicitly privileged.
    ui.send([{'mouse':{'left_click':screen([
        60+i*1080/len(truth['pigments']),13])}}
        for i in range(len(truth['pigments']))])
    apply(desired_settings(truth,truth['target_density'],0,0),initial['summary']['targets'])
    ui.wait(5)
    ui.send([{'mouse':{'left_click':_center(_rect(ui,'#dye-v2-start'))}}])
    deadline = time.monotonic()+budget_seconds
    while time.monotonic()<deadline:
        observed = ui.read(snapshot)
        state = observed['summary']
        if state['status'] == 'failed':
            raise AssertionError(f"irreversible dye failure: {state}")
        if state['status'] == 'complete':
            ui.send([{'mouse':{'left_click':_center(_rect(ui,'#dye-v2-seal'))}}])
            return
        active_ms = (state['tick']-state['start_tick'])*truth['physics']['tick_ms']
        # Physical drags are delivered sequentially. The visible incoming
        # trace permits this short anticipation of the batch's execution.
        apply(desired_settings(truth,truth['target_density'],active_ms,450),state['targets'])
        ui.wait(interval_seconds)
    raise TimeoutError('dye oracle exceeded its declared budget')


# The selector below has no episode-state/DOM/truth input. Calibration is the
# fixed dye/illuminant model and five plant profiles, shared by all instances.
# It decodes only the visibly rendered stock plots and two-lamp colour patches.
# It is technical screenshot-policy evidence, not an evaluated model.
def _rgb_float(density, pigments):
    import numpy as np
    from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.two_lamp_dyeworks_v3 import SPECTRUM
    s=SPECTRUM
    reflectance=np.array(s['base'])*np.exp(-s['strength']*np.array(density)@np.array([p['absorption'] for p in pigments]))
    out=[]
    for lamp in ('north','sodium'):
        power=np.array(s['lamps'][lamp]); cie=np.array(s['cie'])
        relative=cie@(power*reflectance)/(cie@power)
        x,y,z=relative*np.array([.95047,1,1.08883])
        linear=np.clip(np.array([3.2406*x-1.5372*y-.4986*z,-.9689*x+1.8758*y+.0415*z,.0557*x-.204*y+1.057*z]),0,1)
        srgb=np.where(linear<=.0031308,12.92*linear,1.055*linear**(1/2.4)-.055)
        out.extend(255*np.clip(srgb*np.array(s['casts'][lamp]),0,1))
    return np.array(out)


def read_visible_frame(canvas_image, level):
    """Decode one accumulated visual window; never reads per-instance code/state.

    canvas_image is an RGB PIL image of the visible 1120x500 workbench. Pixel
    coordinates are projected at its actual capture resolution, without a
    second encoding or a claim about native screenshot delivery.
    """
    import numpy as np
    from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.two_lamp_dyeworks_v3 import PIGMENTS,PROFILES,PREVIEW_MS
    image=np.asarray(canvas_image.convert('RGB'),dtype=float)
    height,width=image.shape[:2];sx=width/1120;sy=sx
    def patch(x,y,w=30,h=30):
        return np.median(image[round(y*sy):round((y+h)*sy),round(x*sx):round((x+w)*sx)].reshape(-1,3),axis=0).tolist()
    n=PROFILES[level]['pigment_count'];m=PROFILES[level]['vat_count'];panel=1080/n
    # Anonymous traces and valve labels intentionally contain no dye identity.
    # Read only a sampled inlet's persistent green indicator and coloured trace.
    for i in range(n):
        sampled=patch(32+i*panel,10,w=4,h=4)
        if max(abs(a-b) for a,b in zip(sampled,[184,223,185])) > 18:
            raise ValueError('unidentified dye lot; use the visible stock spot test first')
    pigments=[];curves=[]
    background=np.array([9,15,25])
    # JPEG chroma subsampling blurs colour independently of luminance. Fit
    # positive luminance/chroma coverage separately, retaining the trace hue.
    ycc=np.array([[.299,-.168736,.5],[.587,-.331264,-.418688],[.114,.5,-.081312]])
    def colour_weights(pixels,colour):
        signal=(pixels-background)@ycc
        reference=(colour-background)@ycc
        light=signal[...,0]/reference[0]
        coverage=(signal[...,1:]@reference[1:])/(reference[1:]@reference[1:])
        residual=np.linalg.norm(signal[...,1:]-coverage[...,None]*reference[1:],axis=-1)
        valid=(light>.35)&(light<1.15)&(coverage>.12)&(coverage<1.15)&(residual<8)
        return np.where(valid,light*np.exp(-.5*(residual/6)**2),0)
    for i in range(n):
        x=20+i*panel;area=image[round(26*sy):round(72*sy),round((x+10)*sx):round((x+panel-12)*sx)]
        matches=[]
        for p in PIGMENTS[:n]:
            colour=np.array([int(p['color'][j:j+2],16) for j in (1,3,5)])
            matches.append((float(colour_weights(area,colour).sum()),p,colour))
        _,pigment,colour=max(matches,key=lambda row:row[0]);pigments.append(pigment)
        points=[]
        now_x=x+8+(panel-18)*800/(800+PREVIEW_MS)
        for column in range(round((x+10)*sx),round((x+panel-12)*sx)):
            strip=image[round(26*sy):round(72*sy),column]
            if abs((column+.5)/sx-now_x)<3:
                continue  # The rendered NOW line occludes the stock trace.
            weights=colour_weights(strip,colour)
            if weights.sum()>.1:
                cy=(np.arange(len(strip))+round(26*sy)+.5)/sy
                centre=float(weights@cy/weights.sum())
                dx=(column+.5)/sx
                offset=-800+(800+PREVIEW_MS)*(dx-x-8)/(panel-18)
                points.append((offset,.5+(71-centre)/43*1.1))
        if len(points)<20:raise ValueError('stock curve not readable from pixels')
        offsets=np.arange(-750,PREVIEW_MS-49,50)
        curves.append(dict(offsets_ms=offsets.tolist(),strengths=np.interp(offsets,*np.array(points).T).tolist()))
    if len({p['id'] for p in pigments})!=n:raise ValueError('ambiguous visible pigment ordering')
    targets=[];density=[];fit=[]
    for v in range(m):
        left=20+v*560 if m==2 else 280
        pinned=[patch(left+40+j*250,178) for j in range(2)]
        wet=[patch(left+150+j*250,178) for j in range(2)]
        from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.two_lamp_dyeworks_v3 import SPECTRUM
        def fiber_density(x):
            # The same reflectance strip is visible beneath both lamps.
            # Average their luminance to suppress JPEG colour bleed in these
            # narrow bands, without treating a single RGB channel as exact.
            values=np.array([np.mean([
                np.array(patch(x+delta+(band+.5)*104/9-2,222,w=4,h=4))@
                np.array([.299,.587,.114]) for delta in (0,250)
            ])/255 for band in range(9)])
            optical=-np.log(np.clip(values,.5/255,1)/np.array(SPECTRUM['base']))/SPECTRUM['strength']
            return np.clip(np.linalg.lstsq(np.array([p['absorption'] for p in pigments]).T,
                                          optical,rcond=None)[0],0,3).tolist()
        goal=fiber_density(left+16);mix=fiber_density(left+126)
        goal_error=math.sqrt(float(np.mean((_rgb_float(goal,pigments)-np.array(pinned).reshape(-1))**2)))
        mix_error=math.sqrt(float(np.mean((_rgb_float(mix,pigments)-np.array(wet).reshape(-1))**2)))
        targets.append(goal);density.append(mix);fit.append(dict(pinned_rgb_rmse=goal_error,wet_rgb_rmse=mix_error))
    return dict(level=level,pigments=pigments,stock_curves=curves,visible_preview_ms=PREVIEW_MS,target_density_from_pixels=targets,
                density_from_pixels=density,colour_fit=fit,image_size=[width,height],
                information_source='rendered stock traces, pinned/wet fibre strips and two-lamp pixels only')


def select_from_visible_window(observation, action_history, task_ms, start_ms, delay_ms=0, anticipation_ms=450):
    """Predict delivery using only the last plotted window and own inputs.

    action_history contains actual command batches and their task-clock times;
    no old visual observations are retained. Mechanical valves are exactly
    determined by these inputs. The last <=600ms of plotted supply reconstructs
    the FIFO. Current bath concentration is inferred from the visible wet fibre strip.
    """
    from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.two_lamp_dyeworks_v3 import PROFILES
    import numpy as np
    p=PROFILES[observation['level']];n=p['pigment_count'];m=p['vat_count'];tick_ms=50
    valves=[[0.0]*n for _ in range(m)];targets=[[0.0]*n for _ in range(m)]
    history=sorted(action_history,key=lambda row:row['task_ms']);cursor=0;recent={}
    for tick in range(task_ms//tick_ms+1):
        if tick:
            for v in range(m):
                for i in range(n):valves[v][i]+=max(-p['valve_speed']*.05,min(p['valve_speed']*.05,targets[v][i]-valves[v][i]))
        while cursor<len(history) and history[cursor]['task_ms']//tick_ms==tick:
            targets=[list(row) for row in history[cursor]['settings']];cursor+=1
        if tick>task_ms//tick_ms-p['pipe_ms']//tick_ms:recent[tick]=[list(row) for row in valves]
    def strength(offset):
        if any(not c['offsets_ms'][0]<=offset<=c['offsets_ms'][-1] for c in observation['stock_curves']):
            raise ValueError('requested supply lies outside visible window')
        return [float(np.interp(offset,c['offsets_ms'],c['strengths'])) for c in observation['stock_curves']]
    def flux(openings,offset):
        gain=1/(1+p['coupling']*sum(map(sum,openings)));s=strength(offset)
        return [[1.8*s[i]*value*gain for i,value in enumerate(row)] for row in openings]
    current_tick=task_ms//tick_ms
    pipe=[flux(recent[t],(t-current_tick)*tick_ms) for t in range(current_tick-p['pipe_ms']//tick_ms+1,current_tick+1)]
    density=[list(row) for row in observation['density_from_pixels']]
    blend=1-math.exp(-50/p['mixing_ms'])
    for offset in range(50,delay_ms+1,50):
        for v in range(m):
            for i in range(n):valves[v][i]+=max(-p['valve_speed']*.05,min(p['valve_speed']*.05,targets[v][i]-valves[v][i]))
        pipe.append(flux(valves,offset));incoming=pipe.pop(0)
        for v in range(m):
            for i in range(n):density[v][i]+=(incoming[v][i]-density[v][i])*blend
    arrival_strength=strength(delay_ms+anticipation_ms)
    base=[[d/(1.8*arrival_strength[i]) for i,d in enumerate(row)] for row in observation['target_density_from_pixels']]
    denominator=1-p['coupling']*sum(map(sum,base))
    if denominator<=0:raise ValueError('visible match exceeds pump capacity')
    equilibrium=[[quantize(value/denominator) for value in row] for row in base]
    selected,forecast=_choose_visible_command(observation,p,density,valves,pipe,targets,
        equilibrium,strength,delay_ms,max(0,task_ms-start_ms))
    return dict(settings=selected,forecast=forecast,
                predicted_density_at_delivery=density,predicted_valves_at_delivery=valves,
                delivery_delay_ms=delay_ms,supply_lookahead_ms=delay_ms+anticipation_ms,
                information_source=observation['information_source']+' and own timestamped inputs')


def _choose_visible_command(observation,p,density,valves,pipe,current,equilibrium,strength,delay_ms,active_ms):
    import numpy as np
    from benchmarks.gym_anything_rt.shared_scripts.incubator_generators.two_lamp_dyeworks_v3 import SPECTRUM
    s=SPECTRUM;n=p['pigment_count'];m=p['vat_count'];pigments=observation['pigments']
    absorption=np.array([pig['absorption'] for pig in pigments]);cie=np.array(s['cie'])
    def labs(rows,lamp):
        power=np.array(s['lamps'][lamp]);r=np.array(s['base'])*np.exp(-s['strength']*rows@absorption)
        rel=(r*power)@cie.T/(cie@power)
        f=np.where(rel>(6/29)**3,np.cbrt(rel),rel/(3*(6/29)**2)+4/29)
        return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)
    target=np.array(observation['target_density_from_pixels'])
    target_labs={lamp:labs(target,lamp) for lamp in ('north','sodium')}
    horizon=800 if delay_ms else 1200
    if delay_ms+horizon>min(c['offsets_ms'][-1] for c in observation['stock_curves']):
        raise ValueError('prediction horizon exceeds bounded visible supply')
    blend=1-np.exp(-50/p['mixing_ms']);step=p['valve_speed']*.05
    def evaluate(values):
        values=np.asarray(values).reshape(-1,m,n);count=len(values)
        actual=np.tile(valves,(count,1,1));mixed=np.tile(density,(count,1,1))
        fifo=[np.tile(row,(count,1,1)) for row in pipe];cost=np.zeros(count);bad=np.zeros((count,m));errors=None
        for offset in range(50,horizon+1,50):
            actual+=np.clip(values-actual,-step,step);gain=1/(1+p['coupling']*actual.sum(axis=(1,2)))
            incoming_strength=np.array(strength(delay_ms+offset))
            fifo.append(1.8*incoming_strength*actual*gain[:,None,None]);delivered=fifo.pop(0)
            mixed+=(delivered-mixed)*blend
            errors=np.maximum(*[np.linalg.norm(labs(mixed,lamp)-target_labs[lamp],axis=-1) for lamp in ('north','sodium')])
            if active_ms+delay_ms+offset>6000:bad+=(errors>p['tolerance'])*.5
            cost+=(errors**2).sum(axis=1)
        return bad.sum(axis=1)*1e6+cost,bad,errors
    reference=np.array(equilibrium)
    if n*m==2 and delay_ms:
        candidates=np.array([[i/100,j/100] for i in range(101) for j in range(101)]).reshape(-1,1,2)
        costs,bad,errors=evaluate(candidates);index=int(costs.argmin());command=candidates[index]
    else:
        command=reference.copy()
        for _ in range(2):
            for v in range(m):
                for i in range(n):
                    options={quantize(reference[v,i]+d) for d in (-.12,-.08,-.04,-.02,0,.02,.04,.08,.12)}
                    options.add(quantize(current[v][i]));options.add(float(command[v,i]))
                    candidates=np.tile(command,(len(options),1,1))
                    for index,value in enumerate(sorted(options)):candidates[index,v,i]=value
                    costs,bad,errors=evaluate(candidates);index=int(costs.argmin());command=candidates[index]
        costs,bad,errors=evaluate([command]);index=0
    return command.tolist(),dict(horizon_ms=horizon,predicted_spoil_mm=bad[index].tolist(),
        predicted_end_errors=errors[index].tolist(),
        objective='predicted irreversible spoil first, then two-lamp colour error; visible plant state and input history')
