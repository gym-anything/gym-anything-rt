"""Feedback oracle with disclosed privileged geometry and physics lookahead.

The transport follows the frozen gateway's literal mouse dictionary schema.
Headless Playwright tests supply a separate transport and prove wiring only.
No solver action mutates game state or calls an internal game function.
"""
from __future__ import annotations

import math
import time
import copy

MECHANIC_ID = "unwatched_wing_v3"


def choose_target(state):
    """Current geometry and visible velocities only; never future motion seeds."""
    gates, cargo = state["gates"], state["cargo"]
    lens, pinned = state["lens"], state["pinned"]
    photo_id = state.get("photo_id")
    photo_remaining = state.get("photo_until_ms", 0) - state.get("ms", 0)
    candidates = []
    for c in cargo:
        if c["delivered"]:
            continue
        upcoming = [g for g in gates if g["lane"] == c["lane"] and c["x"] <= g["x"] + g["width"] / 2 + c["radius"] + 2]
        if not upcoming:
            continue
        g = min(upcoming, key=lambda a: a["x"])
        remaining = g["x"] - g["width"] / 2 - c["radius"] - c["x"]
        eta = remaining / max(1, c["speed"])
        clearance = g["half"] - c["radius"]
        # Aim on the outer side of the visible eye. During transit this keeps
        # the shutter nearer than the courier, until the courier is clear.
        eye = [g["x"] + 58, g["y"]]
        travel = math.dist(lens, eye) / state["aim_speed"]
        predicted = g["y"] + g["vy"] * travel
        # The courier's free vertical drift is visible in its recent trail or,
        # while restrained, the dashed release arrow. Match the entire contact
        # interval, rather than treating the lane centre as a safe corridor.
        vy = c.get("release_vy", c["vy"]) if c["id"] in (pinned, photo_id) else c["vy"]
        vx = max(1, c.get("release_vx", c["speed"]) if c["id"] in (pinned, photo_id) else c["vx"])
        midpoint = max(0, g["x"]-c["x"]) / vx
        predicted_courier = c["y"] + vy * midpoint
        contact_drift = abs(vy) * (g["width"] / 2 + c["radius"]) / vx
        safe = abs(predicted - predicted_courier) + contact_drift < clearance - 5
        clear_seconds = (g["x"] + g["width"] / 2 + c["radius"] + 3 - c["x"]) / max(1, c["speed"] * .78)
        if photo_id == g["id"] and photo_remaining > clear_seconds * 1000 + 650:
            continue
        if photo_id == c["id"] and photo_remaining > 1000 and not safe:
            continue
        if eta < 4.2:
            # Braking the courier keeps this shutter moving. Releasing that
            # courier to pin its aligned shutter does not stop the other lane.
            target = [eye[0], predicted] if safe else [c["x"] + 6, c["y"]]
            priority = eta - (7.0 if safe else 0) - (1.0 if pinned == g["id"] else 0)
            if not safe and pinned == c["id"]:
                priority = 8 + eta
            elif not safe and photo_id != c["id"] and eta < 1.8:
                priority -= 20
            if remaining < 5 and pinned == g["id"]:
                priority -= 8
            candidates.append((priority, target))
        elif safe and pinned == g["id"]:
            candidates.append((eta + 2, [eye[0], predicted]))
    return min(candidates, key=lambda a:a[0])[1] if candidates else [75, 35]


def observation(sim):
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.unwatched_wing_v3 import free_vertical
    # These are the same one-tick release velocities rendered by the browser;
    # the feedback selector never consumes the phase or seed used to draw them.
    cargo = copy.deepcopy(sim.cargo)
    for c in cargo:
        c["release_vy"] = free_vertical(c)
        c["release_vx"] = c["speed_code"] / 20
    return dict(gates=sim.gates, cargo=cargo, lens=sim.lens, goal=sim.goal, pinned=sim.pinned,
                aim_speed=sim.world["aim_speed"], photo_id=sim.photo_id,
                photo_until_ms=sim.photo_until_ms, ms=sim.ms)


def should_photo(state, target):
    """Use the single image as temporary support while the lantern changes target."""
    pinned = state.get("pinned")
    if not pinned:
        return False
    if "goal" in state and math.dist(state["lens"], state["goal"]) > 20:
        return False
    if pinned == state.get("photo_id"):
        return state.get("photo_until_ms", 0) - state["ms"] < 1000
    position = next(([g["x"] + 26, g["y"]] for g in state["gates"] if g["id"] == pinned), None)
    if position is None:
        position = next(([c["x"], c["y"]] for c in state["cargo"] if c["id"] == pinned), None)
    if position is None or math.dist(target, position) < 45:
        return False
    # Never replace an image that is keeping a shutter open during contact.
    old = next((g for g in state["gates"] if g["id"] == state.get("photo_id")), None)
    if old and any(c["lane"] == old["lane"] and abs(c["x"] - old["x"]) < old["width"]/2 + c["radius"] + 3
                   for c in state["cargo"]):
        return False
    gate = next((g for g in state["gates"] if g["id"] == pinned), None)
    if gate:
        imminent = any(c["lane"] == gate["lane"] and -22 < gate["x"] - c["x"] < 45
                       and abs(gate["y"]-c["y"]) < gate["half"]-c["radius"]-5 for c in state["cargo"])
        return imminent
    courier = next((c for c in state["cargo"] if c["id"] == pinned), None)
    return courier is not None and math.dist(target, [courier["x"], courier["y"]]) > 45


def plan_oracle(state, truth, *, horizon_ms=2400, reserve_ms=4000):
    """Privileged safety lookahead; not a screenshot-only feedback policy.

    The browser action path never invokes this physics. It is a planning copy
    in Python, using privileged numerical geometry and current motion state to avoid unsafe swaps.
    Recorded actions still use the visible mouse/keyboard controls.
    """
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.unwatched_wing_v3 import Transit
    base = Transit(truth)
    base.started = base.active = True
    for key in ("ms", "lens", "goal", "pinned", "photo_id", "photo_until_ms", "gates", "cargo"):
        setattr(base, key, copy.deepcopy(state[key]))
    target = choose_target(state)
    def legal(point):
        return [max(0., min(base.world['width'], point[0])),
                max(0., min(base.world['height'], point[1]))]
    target = legal(target)
    photograph = should_photo(state, target)
    def project(point, photo):
        trial = copy.deepcopy(base)
        if photo:
            ident = trial.observed()
            if ident is not None:
                trial.photo_id = ident
                trial.photo_until_ms = trial.ms + trial.world["photo_lifetime_ms"]
        trial.goal = list(point)
        trial.advance(trial.ms + horizon_ms)
        return trial
    intended = project(target, photograph)
    if not intended.failed:
        if reserve_ms is None:
            return target, photograph
        reserve = copy.deepcopy(intended)
        reserve.advance(base.ms + reserve_ms)
        if not reserve.failed:
            return target, photograph
    points = [list(state["goal"]), target]
    for c in state["cargo"]:
        if c["delivered"]:
            continue
        points.append([c["x"]-6, c["y"]])
        upcoming = [g for g in state["gates"] if g["lane"] == c["lane"]
                    and c["x"] <= g["x"] + g["width"]/2 + c["radius"] + 3]
        if upcoming:
            g = min(upcoming, key=lambda a:a["x"])
            travel = math.dist(state["lens"], [g["x"]+58,g["y"]]) / state["aim_speed"]
            points.append([g["x"]+58, g["y"]+g["vy"]*travel])
    candidates = []
    for point in points:
        point = legal(point)
        for photo in (False, True):
            if photo and not base.observed():
                continue
            trial = project(point, photo)
            if trial.failed:
                continue
            progress = sum(c["x"] for c in trial.cargo) - sum(c["x"] for c in base.cargo)
            reserve = copy.deepcopy(trial)
            if reserve_ms is not None:
                reserve.advance(base.ms + reserve_ms)
            # A greedy transfer can commit both couriers to contact just after
            # the image expires. Prefer a longer physical safety reserve, then
            # progress. This privileged check never changes the task's physics.
            margin = (reserve.ms-base.ms)/1000 if reserve_ms is not None else 0
            score = progress + 60*margin - math.dist(base.lens,point)*.001 - .2*photo
            candidates.append((score, point, photo))
    if candidates:
        _, target, photograph = max(candidates,key=lambda a:a[0])
    return target, photograph


def inspection_route(world):
    """Visible fixed brass plates, swept by column with alternating lanes."""
    columns = {}
    for gate in world['gates']:
        columns.setdefault(int(gate['id'].split('-')[2]), []).append(gate)
    route = []
    for column, gates in sorted(columns.items()):
        for gate in sorted(gates, key=lambda g: g['lane'], reverse=bool(column % 2)):
            route.append((gate['id'], [gate['x'] + 26, gate['baseline']]))
    return route


def survey_prefix(truth):
    """Diagnostic replay of the ordinary lantern sweep; no world mutation."""
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.unwatched_wing_v3 import Transit
    sim = Transit(truth)
    sim.started = sim.active = True
    trace = []
    for ident, point in inspection_route(truth['world']):
        before = sim.ms
        sim.goal = list(point)
        # Match the input transport's conservative travel wait, including one
        # extra tick. The lamp still has the frozen finite V2 travel speed.
        duration = math.ceil(math.dist(sim.lens, point) / sim.world['aim_speed'] * 1000 / 20) * 20 + 40
        sim.advance(sim.ms + duration)
        trace.append(dict(id=ident, point=point, duration_ms=sim.ms-before))
        if sim.failed or ident not in sim.inspected:
            raise AssertionError('initial survey did not safely reveal the shutter')
    return sim, trace


def select_oracle_strategy(truth, cadence_ms=120, initial_sim=None):
    """Privileged pre-START feasibility search; never a screenshot-only policy.

    All three strategies are seed-independent feedback planners. Their full
    physics rollouts use privileged current numerical state to select a
    feasible planner. This is disclosed oracle planning, not agent evidence.
    """
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.unwatched_wing_v3 import Transit
    trials = []
    for settings in (dict(horizon_ms=1600, reserve_ms=None),
                     dict(horizon_ms=2400, reserve_ms=None),
                     dict(horizon_ms=2400, reserve_ms=4000)):
        sim = copy.deepcopy(initial_sim) if initial_sim is not None else Transit(truth)
        sim.started = sim.active = True
        last, requests = None, 1
        while not (sim.failed or sim.passed):
            target, photo = plan_oracle(observation(sim), truth, **settings)
            if photo and (ident := sim.observed()) is not None:
                sim.photo_id = ident; sim.photo_until_ms = sim.ms + sim.world["photo_lifetime_ms"]
                requests += 1
                target, _ = plan_oracle(observation(sim), truth, **settings)
            if last is None or math.dist(last, target) > 5:
                sim.goal = list(target); last = target; requests += 1
            sim.advance(sim.ms + cadence_ms)
        trials.append(dict(settings=settings, passed=sim.passed, failure=sim.failed,
                           task_ms=sim.ms, requests=requests))
        if sim.passed and requests <= 600:
            return settings, trials
    return trials[-1]["settings"], trials


def solve_ui(ui, truth, *, cadence=.12, max_calls=600, survey_targets=None):
    """Private phases/seeds support planning; ui.send uses literal input actions."""
    surveyed, survey = survey_prefix(truth)
    settings, preparation = select_oracle_strategy(truth, round(cadence*1000), initial_sim=surveyed)
    rect = ui.read("(()=>{const r=document.querySelector('#uw2-world').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()")
    def screen(p):
        return [int(rect[0] + p[0] * rect[2] / 1100), int(rect[1] + p[1] * rect[3] / 500)]
    start = ui.read("(()=>{const r=document.querySelector('#uw2-start').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
    ui.send([{"mouse":{"left_click":[int(v) for v in start]}}])
    mode = (truth.get("control_condition") or {}).get("interaction", "full")
    held, last, calls = False, None, 1
    # Evidence runners may supply points measured from the initial screenshot.
    # Otherwise the implementation oracle reads the same rendered brass sites.
    targets = survey_targets or [row['point'] for row in survey]
    for target in targets:
        lens = ui.read('unwatchedWingV3Model.sim.lens')
        if mode == 'full':
            action = {'move':screen(target)}
            if not held:
                action['buttons'] = {'left_down':True}; held = True
            ui.send([{'mouse':action}])
        else:
            ui.send([{'mouse':{'left_click':screen(target)}}])
        calls += 1
        ui.wait(math.dist(lens,target)/truth['world']['aim_speed'] + .04)
        last = list(target)
    if hasattr(ui, 'survey_complete'):
        ui.survey_complete()
    def read_state():
        return ui.read("({gates:unwatchedWingV3Model.sim.gates,cargo:unwatchedWingV3Model.sim.cargo.map(c=>({...c,release_vx:unwatchedWingV3Model.sim.releaseVelocity(c),release_vy:unwatchedWingV3Model.sim.releaseVerticalVelocity(c)})),lens:unwatchedWingV3Model.sim.lens,goal:unwatchedWingV3Model.sim.goal,pinned:unwatchedWingV3Model.sim.pinned,aim_speed:unwatchedWingV3Model.sim.world.aim_speed,failed:unwatchedWingV3Model.sim.failed,passed:unwatchedWingV3Model.sim.passed,photo_id:unwatchedWingV3Model.sim.photo_id,photo_until_ms:unwatchedWingV3Model.sim.photo_until_ms,ms:unwatchedWingV3Model.sim.ms})")
    deadline = time.monotonic() + 200
    while time.monotonic() < deadline:
        data = read_state()
        if data["failed"]:
            raise AssertionError(data["failed"])
        if data["passed"]:
            return {"transport_calls":calls, "budget":max_calls, "privileged_planning":True,
                    "survey_targets":targets,
                    "oracle_settings":settings, "preparation_rollouts":preparation}
        target, photograph = plan_oracle(data, truth, **settings)
        if photograph:
            if mode == "full":
                ui.send([{"keyboard":{"keys":["SPACE"]}}])
            else:
                pos = ui.read("(()=>{const r=document.querySelector('#uw2-photo').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
                ui.send([{"mouse":{"left_click":[int(v) for v in pos]}}])
            calls += 1
            # Photograph the object actually illuminated at execution time.
            # Movement can change it during the input call; read the observed
            # result rather than pretending the earlier intended capture ran.
            data = read_state()
            if data["failed"]:
                raise AssertionError(data["failed"])
            if data["passed"]:
                return {"transport_calls":calls, "budget":max_calls, "privileged_planning":True,
                        "survey_targets":targets,
                        "oracle_settings":settings, "preparation_rollouts":preparation}
            target, _ = plan_oracle(data, truth, **settings)
        if last is None or math.dist(target, last) > 5:
            if mode == "full":
                action = {"move":screen(target)}
                if not held:
                    action["buttons"] = {"left_down":True}
                    held = True
                ui.send([{"mouse":action}])
            else:
                ui.send([{"mouse":{"left_click":screen(target)}}])
            calls += 1
            if calls > max_calls:
                raise AssertionError("oracle exceeded its declared input-request budget")
            last = target
        ui.wait(cadence)
    raise AssertionError("oracle exceeded the declared task time")


def solve(page, state_dir, out_dir, mechanic):
    """Repository solver seam. Browser-only implementation evidence."""
    import json
    from pathlib import Path
    class HeadlessInput:
        def read(self, expression):
            return page.evaluate(expression)
        def wait(self, seconds):
            page.wait_for_timeout(seconds * 1000)
        def send(self, actions):
            for action in actions:
                if "keyboard" in action:
                    page.keyboard.press("Space")
                    continue
                mouse = action["mouse"]
                if "left_click" in mouse:
                    page.mouse.click(*mouse["left_click"])
                if "move" in mouse:
                    page.mouse.move(*mouse["move"])
                if mouse.get("buttons", {}).get("left_down"):
                    page.mouse.down()
                if mouse.get("buttons", {}).get("left_up"):
                    page.mouse.up()
    assert mechanic == MECHANIC_ID
    truth = json.loads((Path(state_dir) / "ground_truth.json").read_text())
    result = solve_ui(HeadlessInput(), truth)
    page.wait_for_function("document.querySelector('.uw2-transfer').dataset.verdict==='pass'")
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / "implementation-pass.png"))
    return result



VISIBLE_FRAME_FIELDS = frozenset(('ms','active','lens','goal','pinned','photo_id','photo_until_ms','aim_speed','focus_radius','dock_x','photo_lifetime_ms','objects'))
VISIBLE_OBJECT_FIELDS = frozenset(('id','lane','x','y','kind','baseline','amplitude','release_vx','release_vy','nominal_rate','width','half','radius','delivered','phase_code','rate_code','rate_min','rate_max','rate_step','rate_direction','speed_code','speed_min','speed_max','speed_step','speed_direction'))


def _validate_visible_window(frame, window):
    """The planner receives bounded measurements, never a simulation object."""
    if not window or len(window)>4 or window[-1] != frame:
        raise ValueError('visible forecast requires one to four chronological measurements ending at the current frame')
    previous=-1
    for row in window:
        if set(row) != VISIBLE_FRAME_FIELDS or row['ms'] < previous or not 0 <= frame['ms']-row['ms'] <= 400:
            raise ValueError('unknown/private frame data or window outside 400 ms')
        previous=row['ms']
        for obj in row['objects']:
            if set(obj)-VISIBLE_OBJECT_FIELDS:
                raise ValueError('private object data is not a visual measurement')

def _infer_visible_phase_rate(y, baseline, amplitude, velocity, acceleration, nominal):
    sine = max(-1.0, min(1.0, (y-baseline)/amplitude))
    angle = math.asin(sine)
    phase = angle if velocity >= 0 else math.pi-angle
    cosine = math.sqrt(max(0.0, 1-sine*sine))
    if cosine > .08:
        rate = abs(velocity)/(amplitude*cosine)
    elif acceleration*(y-baseline) < 0 and abs(y-baseline)>1:
        rate = math.sqrt(-acceleration/(y-baseline))
    else:
        rate = nominal
    return phase, max(nominal*.4, min(nominal*1.65, rate))


def _window_kinematics(rows, ident, axis):
    points = [(row['ms']/1000, next(o for o in row['objects'] if o['id']==ident)[axis]) for row in rows]
    if len(points)<2:return 0.,0.
    # Four actual positions spanning at most 400 ms; fitting has no past cache.
    intervals = [(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]) for i in range(1,len(points))]
    rates = [dy/dt for dt,dy in intervals if dt>0]
    if not rates:return 0.,0.
    velocity_span = (points[-1][0]+points[-2][0]-points[0][0]-points[1][0])/2
    acceleration = (rates[-1]-rates[0]) / velocity_span if len(rates)>1 and velocity_span>0 else 0.
    return rates[-1]+acceleration*(points[-1][0]-points[-2][0])/2,acceleration


class WindowForecast:
    """Recent-visible-state forecast; no actual future PRNG."""
    def __init__(self, frame, window):
        self.ms=frame['ms'];self.active=frame['active'];self.lens=list(frame['lens']);self.goal=list(frame['goal'])
        self.pinned=frame['pinned'];self.photo_id=frame['photo_id'];self.photo_until_ms=frame['photo_until_ms']
        self.aim_speed=frame['aim_speed'];self.radius=frame['focus_radius'];self.dock_x=frame['dock_x']
        self.photo_lifetime_ms=frame['photo_lifetime_ms'];self.failed=False;self.passed=False
        self.gates=[];self.cargo=[]
        for measured in frame['objects']:
            obj=copy.deepcopy(measured)
            vx,ax=_window_kinematics(window,obj['id'],'x')
            vy,ay=_window_kinematics(window,obj['id'],'y')
            restrained=obj['id'] in (self.pinned,self.photo_id)
            if restrained:
                vy=obj['release_vy']
                if obj['kind']=='courier':vx=obj['release_vx']
            elif len(window)<2:
                vy=obj.get('release_vy',0.)
                vx=obj.get('release_vx',0.)
            if 'phase_code' in obj and 'rate_code' in obj:
                phase=obj['phase_code']*math.pi/180000
                rate=obj['rate_code']*math.pi/1800
                if obj['kind']=='courier':vx=obj['speed_code']/20
            else:
                # Retain old diagnostic fixtures; current dials give exact
                # phase and rate without hidden seed or old-history fitting.
                phase,rate=_infer_visible_phase_rate(obj['y'],obj['baseline'],obj['amplitude'],vy,ay,obj['nominal_rate'])
            obj.update(phase=phase,rate=rate,vx=vx,vy=vy)
            (self.gates if obj['kind']=='shutter' else self.cargo).append(obj)

    def observed(self):
        if not self.active:return None
        positions=[(g['id'],[g['x']+26,g['y']]) for g in self.gates]
        positions += [(c['id'],[c['x'],c['y']]) for c in self.cargo if not c['delivered']]
        candidates=[(math.dist(self.lens,p),ident) for ident,p in positions if math.dist(self.lens,p)<=self.radius]
        return min(candidates)[1] if candidates else None

    def advance(self,end):
        def hit(c,left,top,right,bottom):
            if bottom<top:return False
            dx=c['x']-max(left,min(c['x'],right));dy=c['y']-max(top,min(c['y'],bottom))
            # A forecast tolerance, never a change to actual collision grading.
            return dx*dx+dy*dy<(c['radius']+3)**2-1e-9
        while self.ms+20<=end and not (self.failed or self.passed):
            self.ms+=20
            if self.photo_id is not None and self.ms>=self.photo_until_ms:self.photo_id=None
            dx=self.goal[0]-self.lens[0];dy=self.goal[1]-self.lens[1];distance=math.hypot(dx,dy)
            fraction=min(1,self.aim_speed*.02/distance) if distance else 0
            self.lens=[self.lens[0]+dx*fraction,self.lens[1]+dy*fraction]
            self.pinned=self.observed()
            for g in self.gates:
                if g['id'] not in (self.pinned,self.photo_id):
                    g['phase']+=g['rate']*.02;g['y']=g['baseline']+g['amplitude']*math.sin(g['phase'])
            for c in self.cargo:
                if c['delivered']:continue
                if c['id'] not in (self.pinned,self.photo_id):
                    c['x']+=max(1,c['vx'])*.02
                    c['phase']+=c['rate']*.02;c['y']=c['baseline']+c['amplitude']*math.sin(c['phase'])
                for g in self.gates:
                    if g['lane']!=c['lane']:continue
                    left,right=g['x']-g['width']/2,g['x']+g['width']/2
                    if hit(c,left,g['baseline']-104,right,g['y']-g['half']) or hit(c,left,g['y']+g['half'],right,g['baseline']+104):
                        self.failed=True;return
                if c['x']-c['radius']>=self.dock_x:c['delivered']=True
            self.passed=all(c['delivered'] for c in self.cargo)


class VisibleCurrentForecast:
    """Physical projection reconstructed solely from currently printed dials.

    No generator seed, initial phase, old observations or rate bank is an
    argument. Numeric visual measurements are privileged instrumentation;
    this class does not decode a screenshot or compute an optimal policy.
    """
    def __init__(self, frame, window):
        _validate_visible_window(frame, window)
        from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.unwatched_wing_v3 import Transit
        objects = copy.deepcopy(frame['objects'])
        for obj in objects:
            obj['phase'] = obj['phase_code']*math.pi/180000
            obj['age_ms'] = 0
            obj['speed'] = obj.get('speed_code', 0)/20
        gates = [o for o in objects if o['kind']=='shutter']
        cargo = [o for o in objects if o['kind']=='courier']
        world = dict(width=1100,height=500,tick_ms=20,max_active_ms=180000,
            rate_update_ms=200,trace_ms=400,initial_lens=list(frame['lens']),
            gates=gates,cargo=cargo,lanes=sorted({o['baseline'] for o in cargo}),
            aim_speed=frame['aim_speed'],focus_radius=frame['focus_radius'],
            dock_x=frame['dock_x'],photo_lifetime_ms=frame['photo_lifetime_ms'])
        self.sim=Transit({'world':world})
        self.sim.started=True
        for name in ('ms','active','lens','goal','pinned','photo_id','photo_until_ms'):
            setattr(self.sim,name,copy.deepcopy(frame[name]))
        for measured,current in zip(cargo,self.sim.cargo):
            current['delivered']=measured['delivered']
        self.aim_speed=frame['aim_speed']
        self.photo_lifetime_ms=frame['photo_lifetime_ms']
        self.dock_x=frame['dock_x']

    def __getattr__(self,name):
        sim=self.__dict__.get('sim')
        if sim is None:raise AttributeError(name)
        if name=='radius':return sim.world['focus_radius']
        return getattr(sim,name)

    def observed(self):return self.sim.observed()
    def advance(self,end):self.sim.advance(end)

    @property
    def active(self):return self.sim.active
    @active.setter
    def active(self,value):self.sim.active=value
    @property
    def goal(self):return self.sim.goal
    @goal.setter
    def goal(self,value):self.sim.goal=list(value)
    @property
    def photo_id(self):return self.sim.photo_id
    @photo_id.setter
    def photo_id(self,value):self.sim.photo_id=value
    @property
    def photo_until_ms(self):return self.sim.photo_until_ms
    @photo_until_ms.setter
    def photo_until_ms(self,value):self.sim.photo_until_ms=value


def plan_visible(frame, window, horizon=1600, reserve=2400):
    _validate_visible_window(frame, window)
    complete=all('phase_code' in o and 'rate_direction' in o for o in frame['objects'])
    base=VisibleCurrentForecast(frame,window) if complete else WindowForecast(frame,window)
    points=[list(base.goal),[75,35]]
    for c in base.cargo:
        if c['delivered']:continue
        points.append([c['x']-6,c['y']])
        upcoming=[g for g in base.gates if g['lane']==c['lane'] and c['x']<=g['x']+g['width']/2+c['radius']+3]
        if not upcoming:continue
        gate=min(upcoming,key=lambda g:g['x'])
        travel=math.dist(base.lens,[gate['x']+58,gate['y']])/base.aim_speed
        rate=gate['rate_code']*math.pi/1800 if complete else gate['rate']
        predicted=gate['baseline']+gate['amplitude']*math.sin(gate['phase']+rate*travel)
        points.append([gate['x']+58,predicted])
        points.append([gate['x']+58,gate['y']])
    ident=base.observed()
    candidates=[]
    for point in points:
        for photo in (False,True) if ident and ident!=base.photo_id else (False,):
            trial=copy.deepcopy(base);trial.active=True;trial.goal=point
            if photo:trial.photo_id=ident;trial.photo_until_ms=trial.ms+trial.photo_lifetime_ms
            trial.advance(base.ms+horizon)
            if trial.failed:continue
            progress=sum(c['x'] for c in trial.cargo)-sum(c['x'] for c in base.cargo)
            backup=copy.deepcopy(trial)
            backup.advance(base.ms+reserve)
            safe_ms=reserve if backup.passed else backup.ms-base.ms
            delivered=sum(c['delivered'] for c in backup.cargo)-sum(c['delivered'] for c in base.cargo)
            # Terminal success is safe; never reward waiting over docking.
            score=progress+60*safe_ms/1000+500*delivered-math.dist(base.lens,point)*.001-.2*photo
            candidates.append((score,point,photo))
    if candidates:
        _,point,photo=max(candidates,key=lambda row:row[0])
        return point,photo
    courier=min((c for c in base.cargo if not c['delivered']),key=lambda c:c['x'],default=None)
    return ([courier['x']-6,courier['y']] if courier else [75,35]),False
