"""Census validation policies; every executed input uses the supplied API.

Planning includes the generated future trajectory. This is an oracle validation
policy. A separate image feedback policy below accepts screenshots and mouse
input only. Playwright evidence does not establish native transport parity.
"""
from __future__ import annotations

import time

MECHANIC_ID = "charter_of_the_nine_cantons_v3"
ORACLE_REVISION = "selective-trajectory-folios-r8"
READ = "({t_ms:charterCensusV3Model.t_ms,boundaries:charterCensusV3Model.boundaries,charge_ms:charterCensusV3Model.charge_ms,status:charterCensusV3Model.status,submitted:charterCensusV3Model.submitted,serverGrade:charterCensusV3Model.serverGrade})"


def rectangle(ui, selector):
    return ui.read(f"(() => {{ const r=document.querySelector({selector!r}).getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; }})()")


def midpoint(rect):
    return [rect[0]+rect[2]/2, rect[1]+rect[3]/2]


def safe_interval(border, start_ms, end_ms, margin=2):
    """Coordinates valid throughout a future interval, including any turn.

    Each generated smoothstep segment is monotone, so its endpoints and the
    enclosed knots give exact extrema. Future knots are privileged planning.
    """
    from benchmarks.gym_anything_rt.shared_runtime.server.incubator_graders.charter_of_the_nine_cantons_v3 import center
    times = [start_ms, end_ms] + [t for t, _ in border["knots"] if start_ms < t < end_ms]
    positions = [center(border, t) for t in times]
    rail_low, rail_high = (220, 460) if border["id"] % 2 == 0 else (580, 820)
    return (max(rail_low, max(positions)-border["gap"]/2+margin),
            min(rail_high, min(positions)+border["gap"]/2-margin))


def planned_updates(truth, snapshot, next_window_ms, holding_horizon_ms=4000):
    """Move only borders that cannot safely remain for the next observation.

    For a required correction, maximize its safe holding interval rather than
    recentering all six handles after every half-second window. This reduces
    native primitive work without changing the world or input surface.
    """
    now = snapshot["t_ms"]
    end = min(now + next_window_ms, truth["simulation"]["deadline_ms"])
    updates = []
    for index, border in enumerate(truth["borders"]):
        low, high = safe_interval(border, now, end)
        if low <= snapshot["boundaries"][index] <= high:
            continue
        if low > high:
            raise ValueError("observation horizon exceeds this border's safe placement interval")
        left, right = end, min(now + holding_horizon_ms, truth["simulation"]["deadline_ms"])
        # The intersection shrinks monotonically with the proposed holding
        # time, including reversals; bisection finds the longest feasible hold.
        for _ in range(24):
            future = (left + right) / 2
            candidate_low, candidate_high = safe_interval(border, now, future)
            if candidate_low <= candidate_high:
                left = future
                low, high = candidate_low, candidate_high
            else:
                right = future
        updates.append((index, (low + high) / 2))
    return updates


def solve_api(ui, truth, update_seconds=.35, prediction_seconds=.25):
    mode = (truth.get("control_condition") or {}).get("interaction", "full")
    rect = rectangle(ui, "#census-map")
    start = midpoint(rectangle(ui, "#census-start"))
    def point(index, x):
        return [rect[0]+x*rect[2]/1040, rect[1]+(index//2*190+164)*rect[3]/570]
    def updates(snapshot):
        # Cover the existing 500-ms paused window and the live update/transport
        # allowance with one policy. The task has no mode-specific physics.
        next_window_ms = max(500, 1000*(update_seconds + prediction_seconds))
        actions = []
        for index, target in planned_updates(truth, snapshot, next_window_ms):
            if mode == "full":
                actions.extend([{"mouse":{"move":point(index,snapshot["boundaries"][index]),"buttons":{"left_down":True}}},
                                {"mouse":{"move":point(index,target),"buttons":{"left_up":True}}}])
            else:
                actions.append({"mouse":{"left_click":point(index,target)}})
        return actions
    initial = ui.read(READ)
    # Inspect the actual field registers with the same click in both modes.
    # These are information probes, with no effect on borders or acceptance.
    folios = [{"mouse":{"left_click":[rect[0]+92*rect[2]/1040,
                rect[1]+(row*190+162)*rect[3]/570]}} for row in range(3)]
    ui.send(folios+updates(initial)+[{"mouse":{"left_click":start}}])
    deadline = time.monotonic()+150
    requests = 1
    while True:
        state = ui.read(READ)
        if state["submitted"]:
            ui.wait(.3)
            return ui.read(READ)
        if time.monotonic() >= deadline or requests >= 95:
            raise AssertionError("census oracle exhausted its finite 95-action-request/150-second budget")
        ui.send(updates(state))
        requests += 1
        ui.wait(update_seconds)


def solve(page,state_dir,out_dir,mechanic=MECHANIC_ID,advance=None):
    import json
    from pathlib import Path
    if mechanic != MECHANIC_ID:
        raise ValueError("wrong oracle mechanic")
    truth = json.loads((Path(state_dir)/"ground_truth.json").read_text())
    class BrowserUI:
        def read(self,expression):return page.evaluate(expression)
        def wait(self,seconds):
            if advance is None:page.wait_for_timeout(seconds*1000)
            else:advance(page,500)
        def send(self,actions):
            for action in actions:
                mouse=action["mouse"]
                if "move" in mouse:page.mouse.move(*mouse["move"])
                for key in mouse.get("buttons",{}):
                    button,transition=key.rsplit("_",1)
                    getattr(page.mouse,transition)(button=button)
                if "left_click" in mouse:page.mouse.click(*mouse["left_click"])
    result=solve_api(BrowserUI(),truth)
    Path(out_dir).mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(Path(out_dir)/f"{MECHANIC_ID}-pass.png"))
    return result


def visible_census(image_bytes):
    """Read household columns and handles from the actual 1920x1080 image.

    Pixel sampling locations were measured from the opened V3 screenshots.
    The two samples through each house's colored rim exclude its white glyph,
    the horizontal motion trail, and stationary houses at neighboring heights.
    No generated world, browser state, DOM geometry or future motion is read.
    """
    import io
    from PIL import Image
    image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    if image.size != (1920, 1080):
        raise ValueError('visible census controller requires a 1920x1080 screenshot')
    pixels = image.load()
    guild_colors = [(173,119,20), (20,119,140), (150,60,104)]

    def near(pixel, color, tolerance=5):
        return all(abs(a-b) <= tolerance for a,b in zip(pixel,color))

    def runs(mask):
        intervals = []
        begin = None
        for x, active in enumerate(mask + [False]):
            if active and begin is None:
                begin = x
            elif not active and begin is not None:
                if x-begin >= 4:
                    intervals.append((begin+x-1)/2)
                begin = None
        return intervals

    def columns(y, palette, low=300, high=1320):
        mask = [False] * 1920
        palette = set(palette)
        for x in range(low,high):
            mask[x] = pixels[x,y-10] in palette and pixels[x,y+10] in palette
        return runs(mask)

    # The verdict text occupies this otherwise unlabelled central map region.
    green = sum(count for count,color in image.crop((650,465,1280,510)).getcolors(30000)
                if near(color,(40,104,79)))
    if green > 100:
        return {'passed':True, 'rows':[]}

    rows = []
    for house_y, handle_y in [(341,401), (606,667), (872,932)]:
        options = [columns(y,guild_colors) for y in range(house_y-2,house_y+3)]
        candidates = [xs for xs in options if len(xs)==4]
        if not candidates:
            raise ValueError('field folio is concealed or four migrant columns are not visible')
        houses = candidates[len(candidates)//2]
        handles = columns(handle_y, [(25,60,72)])
        if len(handles)!=2:
            raise ValueError('the two visible border handles could not be located')
        rows.append({'houses':houses, 'handles':handles,
                     'centers':[(houses[0]+houses[1])/2,(houses[2]+houses[3])/2]})
    return {'passed':False, 'rows':rows}


def solve_visible_api(ui, interaction, evidence_dir=None, wait_seconds=.1):
    """Feedback controller using screenshots and ordinary mouse input only.

    This supplements the existing privileged oracle. ui supplies screenshot(),
    send() and wait(); there is deliberately no read()/truth argument. Recent
    measured household motion predicts the short image-to-input delay. The
    screenshot controller is browser evidence, not native action-API parity.
    """
    import json
    from pathlib import Path
    if interaction not in ('full','simplified'):
        raise ValueError('invalid visible-controller interaction')
    folder = Path(evidence_dir) if evidence_dir is not None else None
    if folder:
        folder.mkdir(parents=True,exist_ok=True)
    trace = []
    began = time.monotonic()
    unreadable = []

    def observe():
        # A border can briefly cross a household rim, and the terminal
        # verification overlay covers the map before the verdict arrives.
        # Wait for another image of this same attempt, using no private state.
        deadline = time.monotonic()+2
        while True:
            image = ui.screenshot()
            try:
                return image,visible_census(image)
            except ValueError as error:
                unreadable.append({'wall_s':time.monotonic()-began,'reason':str(error)})
                if folder:
                    (folder/f'unreadable-{len(unreadable):04d}.png').write_bytes(image)
                    (folder/'unreadable-observations.json').write_text(json.dumps(unreadable,indent=2)+'\n')
                if time.monotonic()>=deadline:
                    raise
                ui.wait(.1)

    image = ui.screenshot()
    if folder:
        (folder/'initial.png').write_bytes(image)
    # These are the visible folded-paper and footer control centers measured
    # from the opened screenshots, not selectors or generated world geometry.
    ui.send([{'mouse':{'left_click':[170,y]}} for y in (399,665,930)])
    image,observed = observe()
    if folder:
        (folder/'discovered.png').write_bytes(image)

    def corrections(observation, previous, now, delivered):
        actions = []
        for row, values in enumerate(observation['rows']):
            for side, center_x in enumerate(values['centers']):
                handle = values['handles'][side]
                velocity = 0
                if previous is not None:
                    elapsed = now-previous[0]
                    if elapsed>0:
                        velocity = (center_x-previous[1]['rows'][row]['centers'][side])/elapsed
                # Allow for the screenshot and sequential visible gestures.
                # Only the recent screenshot pair supplies motion prediction.
                target = center_x + velocity*.5
                low,high = (361,718) if side==0 else (897,1253)
                target = min(high-2,max(low+2,target))
                if abs(target-handle)<12:
                    continue
                y = (401,667,932)[row]
                if interaction=='full':
                    pickup = min(high-2,max(low+2,handle))
                    actions += [{'mouse':{'move':[pickup,y],'buttons':{'left_down':True}}},
                                {'mouse':{'move':[target,y],'buttons':{'left_up':True}}}]
                else:
                    actions.append({'mouse':{'left_click':[target,y]}})
                delivered.append({'row':row,'side':side,'observed_gap':values['houses'][side*2:side*2+2],
                                  'handle_x':handle,'target_x':target,'velocity_px_s':velocity})
        return actions

    delivered=[]
    now = time.monotonic()
    ui.send(corrections(observed,None,now,delivered)+[{'mouse':{'left_click':[1661,1052]}}])
    trace.append({'wall_s':now-began,'observation':observed,'decisions':delivered,'start':True})
    previous = (now,observed)
    active_saved=False
    while time.monotonic()-began < 145:
        ui.wait(wait_seconds)
        image,observed = observe()
        now = time.monotonic()
        if observed['passed']:
            if folder:
                (folder/'final-pass.png').write_bytes(image)
                (folder/'visible-trace.json').write_text(json.dumps(trace,indent=2)+'\n')
            return {'passed':True,'frames':len(trace)+2,'wall_seconds':now-began,
                    'unreadable_observations':len(unreadable),
                    'observation_source':'Screenshot pixels only; no page state, DOM or future trajectories'}
        if folder and not active_saved and now-began>2:
            (folder/'active.png').write_bytes(image)
            active_saved=True
        delivered=[]
        actions=corrections(observed,previous,now,delivered)
        ui.send(actions)
        trace.append({'wall_s':now-began,'observation':observed,'decisions':delivered})
        previous=(now,observed)
    if folder:
        (folder/'incomplete.png').write_bytes(image)
        (folder/'visible-trace.json').write_text(json.dumps(trace,indent=2)+'\n')
    raise AssertionError('visible census controller did not observe a pass before its finite deadline')
