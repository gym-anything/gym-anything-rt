"""Independent fixed-step replay. No browser positions or completion are trusted."""
from __future__ import annotations

import copy
import math
from functools import lru_cache

MECHANIC_ID = "lampwrights_program_nonrealtime"
TOKENS = ("F", "J", "D", "L", "R", "G", "A", "B")
DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))


@lru_cache(maxsize=32768)
def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def matrix_product(a, b, modulus):
    return tuple(sum(a[i*2+k]*b[k*2+j] for k in range(2)) % modulus
                 for i in range(2) for j in range(2))


def matrix_power(matrix, exponent, modulus):
    result = (1, 0, 0, 1)
    while exponent:
        if exponent & 1:
            result = matrix_product(result, matrix, modulus)
        matrix = matrix_product(matrix, matrix, modulus)
        exponent //= 2
    return result


@lru_cache(maxsize=65536)
def lift_pair_at(first, second, index, modulus, coefficient, previous_coefficient):
    if index < 0:
        # Invertibility is needed for reconstructing every earlier input from
        # a current screenshot, including long routines and in-flight states.
        inverse = pow(previous_coefficient, -1, modulus)
        matrix = (-coefficient*inverse % modulus, inverse, 1, 0)
    else:
        matrix = (0, 1, previous_coefficient, coefficient)
    m = matrix_power(matrix, abs(index), modulus)
    return ((m[0]*first+m[1]*second) % modulus,
            (m[2]*first+m[3]*second) % modulus)


def lift_goal(physics, roof, pair):
    first, second = pair
    previous = ((second-physics['lift_coefficient']*first) *
                pow(physics['lift_previous_coefficient'], -1, physics['lift_modulus'])) % physics['lift_modulus']
    count = round(2*physics['sway']/physics['motion_quantum'])+1
    quantum = physics['motion_quantum']
    return [round(roof['cell'][0]-physics['sway']+quantum*((first+2*previous) % count), 2),
            round(roof['cell'][1]-physics['sway']+quantum*((3*first+previous) % count), 2),
            round(roof['base_z']-physics['lift']+quantum*first, 2)]


def roof_pose(world, roof, ms):
    """Continuous position/velocity/acceleration; fresh, nonrepeating lift goals.

    Quintic ramps have zero velocity AND acceleration at each knot. The current
    start, current goal, next goal and remaining ramp time are visible for EVERY
    roof. V3 endpoints lie on the displayed centimetre grid. Thus a screenshot
    describes both ramps through delay + maximum flight, including at a knot.
    Legacy worlds retain their original unquantized motion when replayed.
    """
    p = world["physics"]
    u = (ms+roof["phase_ms"])/p["span_ms"]
    n, f = math.floor(u), u-math.floor(u)
    blend = f**3*(10-15*f+6*f*f)
    derivative = 30*f*f*(1-f)**2/(p["span_ms"]/1000)
    amplitudes = (p["sway"], p["sway"], p["lift"])
    base = (*roof["cell"], roof["base_z"])
    points, velocities, starts, goals, next_goals = [], [], [], [], []
    if p.get('motion_revision') == 'visible-lift-v1':
        controller_endpoints = [lift_goal(p, roof, lift_pair_at(*roof['lift_pair'], n+k,
            p['lift_modulus'],p['lift_coefficient'],p['lift_previous_coefficient'])) for k in range(3)]
    for axis, amplitude in enumerate(amplitudes):
        if p.get('motion_revision') == 'visible-lift-v1':
            endpoints = [point[axis] for point in controller_endpoints]
        else:
            # Exact v2-v4 replay remains tied to the archived world's flags.
            seed = (roof["motion_seed"]+axis*7919) & 0xFFFFFFFF
            endpoints = [base[axis]+amplitude*noise(seed, n+k) for k in range(3)]
            if p.get("motion_quantum"):
                quantum = p["motion_quantum"]
                endpoints = [math.floor(x/quantum+.5)*quantum for x in endpoints]
        a, b, c = endpoints
        points.append(a+(b-a)*blend)
        velocities.append((b-a)*derivative)
        starts.append(a)
        goals.append(b)
        next_goals.append(c)
    return dict(position=points, velocity=velocities, start=starts, goal=goals, next_goal=next_goals,
                phase=f, remaining_ms=(1-f)*p["span_ms"])


def swept_deck_contact(previous, point, previous_center, center, half, radius, thickness):
    """Segment/AABB intersection in a deck's moving reference frame.

    The same linear interpolation within a fixed 10-ms tick is used by the top
    contact. Test the whole solid volume, so a side or underside cannot be
    traversed between sampled endpoints. Starting on a deck and moving upward
    is allowed; a descending top contact is handled separately by containment.
    """
    enter, leave = 0., 1.
    for axis, (low, high) in enumerate(((-half-radius,half+radius),
                                       (-half-radius,half+radius),(-thickness,-1e-8))):
        a = previous[axis]-previous_center[axis]
        b = point[axis]-center[axis]
        velocity = b-a
        if abs(velocity)<1e-12:
            if not low<a<high:return None
        else:
            t0,t1=(low-a)/velocity,(high-a)/velocity
            enter=max(enter,min(t0,t1));leave=min(leave,max(t0,t1))
            if enter>=leave-1e-12:return None
    return enter


class Physics:
    def __init__(self, world, pose=None):
        self.world = copy.deepcopy(world)
        self.pose = pose or roof_pose
        self.roofs = {r["id"]: r for r in world["roofs"]}
        self.ms = 0
        self.roof = world["start_roof"]
        self.heading = world["start_heading"]
        self.offset = [0., 0.]
        self.position = self.pose(world, self.roofs[self.roof], 0)["position"]
        self.flight = None
        self.busy_until = 0
        self.pending_light = None
        self.queue = []
        self.lit = set()
        self.failed = ""
        self.steps = []
        self.centering = None

    def command(self, token):
        if self.failed or self.flight or self.ms < self.busy_until:
            raise ValueError("robot is busy")
        if token == "L" or token == "R":
            self.heading = (self.heading+(3 if token == "L" else 1)) % 4
            self.busy_until = self.ms+self.world["physics"]["command_ms"]
        elif token == "G":
            if not self.roofs[self.roof]["lamp"]:
                self.failed = "The LIGHT instruction struck an unmarked roof."
                return
            self.pending_light = self.roof
            self.busy_until = self.ms+self.world["physics"]["lamp_ms"]
        elif token in ("F", "J", "D"):
            spec = self.world["physics"]
            pose = self.pose(self.world, self.roofs[self.roof], self.ms)
            start = [pose["position"][i]+(self.offset[i] if i < 2 else 0) for i in range(3)]
            direction = DIRS[self.heading]
            tau = spec["nominal_flight_s"]
            dz = {"F": 0., "J": spec["height_step"], "D": -spec["height_step"]}[token]
            velocity = [direction[i]/tau+spec["momentum"]*pose["velocity"][i] for i in range(2)]
            velocity.append(dz/tau+.5*spec["gravity"]*tau+spec["momentum"]*pose["velocity"][2])
            self.flight = dict(start_ms=self.ms, start=start, velocity=velocity, source=self.roof)
            self.position = start
            self.roof = None
        else:
            raise ValueError("invalid primitive")
        self.steps.append(dict(t_ms=self.ms, token=token))

    def dispatch(self, commands):
        if self.flight or self.ms < self.busy_until or self.queue or self.failed:
            raise ValueError("robot is busy or terminal")
        self.queue = list(commands)
        if not self.queue:
            raise ValueError("empty routine")
        self.command(self.queue.pop(0))
        self.advance_action()

    def advance_action(self):
        """Finish one deliberate dispatch; idle task time never advances."""
        tick = self.world["physics"]["tick_ms"]
        for _ in range(300000):
            if self.failed or (not self.flight and not self.queue and
                               not self.pending_light and not self.centering and
                               self.ms >= self.busy_until):
                return
            before = self.ms
            self.advance(before + tick)
            if self.ms <= before:
                raise ValueError("action transition did not advance")
        raise ValueError("action transition exceeded its fixed-step budget")

    def advance(self, target_ms):
        tick = self.world["physics"]["tick_ms"]
        if (not self.flight and not self.queue and not self.pending_light and
                not self.centering and self.ms >= self.busy_until):
            return
        while self.ms+tick <= target_ms and not self.failed:
            if not self.flight and not self.queue and not self.pending_light and not self.centering:
                self.ms = (target_ms//tick)*tick
                pose = self.pose(self.world, self.roofs[self.roof], self.ms)["position"]
                self.position = [pose[i]+(self.offset[i] if i < 2 else 0) for i in range(3)]
                break
            before_ms = self.ms
            self.ms += tick
            if self.flight:
                f = self.flight
                s = (self.ms-f["start_ms"])/1000
                previous = list(self.position)
                point = [f["start"][i]+f["velocity"][i]*s for i in range(3)]
                point[2] -= .5*self.world["physics"]["gravity"]*s*s
                self.position = point
                contacts = []
                radius = self.world["physics"]["robot_radius"]
                for roof in self.roofs.values():
                    a = self.pose(self.world, roof, before_ms)["position"]
                    b = self.pose(self.world, roof, self.ms)["position"]
                    above, below = previous[2]-a[2], point[2]-b[2]
                    if above > 1e-9 and below <= 0:
                        fraction = above/(above-below)
                        hit = [previous[i]+fraction*(point[i]-previous[i]) for i in range(3)]
                        center = [a[i]+fraction*(b[i]-a[i]) for i in range(3)]
                        dx, dy = abs(hit[0]-center[0]), abs(hit[1]-center[1])
                        if dx <= roof["half"]+radius and dy <= roof["half"]+radius:
                            contacts.append((fraction, roof["id"], hit, center,
                                             dx+radius <= roof["half"]+1e-8 and dy+radius <= roof["half"]+1e-8))
                    thickness = self.world["physics"]["roof_thickness"]
                    if self.world["physics"].get("collision_revision") == "swept-deck-v1":
                        solid_contact = swept_deck_contact(previous,point,a,b,roof["half"],radius,thickness) is not None
                    else:
                        # Preserve the exact older-world replay contract.
                        solid_contact = (b[2]-thickness < point[2] < b[2]-1e-8 and
                                         abs(point[0]-b[0]) < roof["half"]+radius and
                                         abs(point[1]-b[1]) < roof["half"]+radius)
                    if solid_contact:
                        if not any(c[1] == roof["id"] for c in contacts):
                            self.failed = "The robot struck a moving roof edge."
                if contacts and not self.failed:
                    _, roof_id, hit, center, contained = min(contacts)
                    if not contained:
                        self.failed = "The robot clipped the visible roof edge."
                    else:
                        self.roof = roof_id
                        self.offset = [hit[i]-center[i] for i in range(2)]
                        self.flight = None
                        self.busy_until = self.ms+300
                        self.centering = dict(start_ms=self.ms, offset=list(self.offset))
                        self.steps.append(dict(t_ms=self.ms, landed=roof_id))
                elif self.ms-f["start_ms"] >= self.world["physics"]["maximum_flight_ms"]:
                    self.failed = "The robot fell between the roofs."
            else:
                if self.centering:
                    fraction = max(0., 1-(self.ms-self.centering["start_ms"])/300)
                    self.offset = [v*fraction for v in self.centering["offset"]]
                    if fraction == 0:
                        self.centering = None
                pose = self.pose(self.world, self.roofs[self.roof], self.ms)["position"]
                self.position = [pose[i]+(self.offset[i] if i < 2 else 0) for i in range(3)]
            if not self.flight and self.ms >= self.busy_until and not self.failed:
                if self.pending_light:
                    self.lit.add(self.pending_light)
                    self.pending_light = None
                if self.queue:
                    self.command(self.queue.pop(0))

    def snapshot(self):
        return dict(t_ms=self.ms, roof=self.roof, heading=self.heading, offset=list(self.offset),
                    position=list(self.position), flight=copy.deepcopy(self.flight),
                    busy_until=self.busy_until, queue=list(self.queue), lit=sorted(self.lit),
                    failed=self.failed, steps=copy.deepcopy(self.steps))


def grade(payload, ground_truth, public_state):
    def fail(message):
        return dict(graded=True, passed=False, score=0, feedback=message)
    try:
        for key in ("mechanic_id", "task_id", "challenge_id", "physics_revision", "world_digest"):
            if not ground_truth.get(key) or any(x.get(key) != ground_truth[key] for x in (payload, public_state)):
                return fail("stale or wrong "+key)
        if ground_truth["mechanic_id"] != MECHANIC_ID:
            return fail("wrong mechanic")
        for key in ("world", "control_condition"):
            if public_state.get(key) != ground_truth.get(key):
                return fail("public replay contract differs: "+key)
        condition = ground_truth["control_condition"]
        mode = condition["interaction"]
        if mode not in ("simplified", "full") or payload.get("interaction_mode") != mode:
            return fail("wrong interaction mode")
        source = "click_place" if mode == "simplified" else "pointer_drag"
        physics = Physics(ground_truth["world"])
        routines = {"A": [None]*ground_truth["world"]["routine_slots"],
                    "B": [None]*ground_truth["world"]["routine_slots"]}
        events = payload.get("events")
        if not isinstance(events, list) or not events:
            return fail("missing input trace")
        previous = 0
        launched = False
        for sequence, e in enumerate(events, 1):
            ms = e["t_ms"]
            if (e.get("sequence") != sequence or type(ms) is not int or
                not previous <= ms <= ground_truth["world"]["physics"]["max_task_ms"] or ms % 10):
                return fail("invalid event sequence or task time")
            previous = ms
            if not launched and ms != 0:
                return fail("preparation time is not active task time")
            physics.advance(ms)
            if physics.failed:
                return fail(physics.failed)
            kind = e.get("kind")
            if kind in ("edit", "dispatch") and e.get("input_source") != source:
                return fail("wrong interaction surface")
            if kind in ("edit", "dispatch") and mode == "full":
                a, b = e.get("start_point"), e.get("end_point")
                if (not isinstance(a, list) or not isinstance(b, list) or len(a) != 2 or len(b) != 2 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in a+b) or math.dist(a, b) < 5):
                    return fail("instruction requires a physical drag")
            if kind == "start":
                if launched or e.get("input_source") != "start_button":
                    return fail("start or restart invalid")
                launched = True
            elif kind == "edit":
                panel, index, token = e.get("panel"), e.get("index"), e.get("token")
                if panel not in routines or type(index) is not int or not 0 <= index < len(routines[panel]):
                    return fail("invalid routine slot")
                if token not in TOKENS[:6]:
                    return fail("routines contain primitive instructions only")
                routines[panel][index] = token
            elif kind == "dispatch":
                token = e.get("token")
                if not launched or token not in TOKENS:
                    return fail("invalid live instruction")
                commands = [t for t in routines[token] if t] if token in routines else [token]
                physics.dispatch(commands)
            elif kind == "seal":
                if e.get("input_source") != "certify_button" or sequence != len(events):
                    return fail("invalid or repeated certification")
            else:
                return fail("unknown input; reset and world-stop controls do not exist")
        final = payload.get("final_t_ms")
        if type(final) is not int or not previous <= final <= ground_truth["world"]["physics"]["max_task_ms"] or final % 10:
            return fail("invalid final task time")
        physics.advance(final)
        if physics.failed:
            return fail(physics.failed)
        targets = {r["id"] for r in ground_truth["world"]["roofs"] if r["lamp"]}
        passed = (launched and events[-1]["kind"] == "seal" and not physics.flight and not physics.queue
                  and physics.ms >= physics.busy_until and physics.lit == targets and payload.get("completed") is True)
        if payload.get("lit") != sorted(physics.lit) or payload.get("steps") != physics.steps:
            return fail("reported physical outcome differs from replay")
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback=f"moving-roof replay: {len(physics.lit)}/{len(targets)} lamps; "+("shift complete" if passed else "shift incomplete"))
    except (KeyError, ValueError, TypeError, OverflowError) as error:
        return fail("invalid lampwright transcript: "+str(error))


def cheat(public_state, ground_truth):
    return dict(world=ground_truth.get("world"), planning="privileged geometry only; no success action")
