"""Standalone independent optical/servo replay (also run unchanged in Pyodide)."""
from __future__ import annotations

import math

MECHANIC_ID = "rayglass_vault_nonrealtime"
REVISION = "moving-receivers-3"


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295


def speed(contract, channel, active_tick):
    p = contract["parameters"]
    u = active_tick*10/p["speed_span_ms"]
    k, f = math.floor(u), u-math.floor(u)
    a, b = noise(channel["motion_seed"], k), noise(channel["motion_seed"], k+1)
    return p["speed_min"]+(p["speed_max"]-p["speed_min"])*(a+(b-a)*f*f*(3-2*f))


def ray(n, beads, port):
    balls = {(i % n, i // n) for i in beads}
    side, k = divmod(port, n)
    x, y, dx, dy = ((k, -1, 0, 1), (n, k, -1, 0), (n-1-k, n, 0, -1), (-1, n-1-k, 1, 0))[side]
    front = lambda: (x+dx, y+dy)
    diagonal = lambda s: (x+dx+s*dy, y+dy-s*dx)
    if front() in balls:
        return "H"
    if diagonal(1) in balls or diagonal(-1) in balls:
        return "R"
    x, y = x+dx, y+dy
    seen = set()
    while (x, y, dx, dy) not in seen:
        seen.add((x, y, dx, dy))
        if front() in balls:
            return "H"
        a, b = diagonal(1) in balls, diagonal(-1) in balls
        if a and b:
            dx, dy = -dx, -dy
        elif a:
            dx, dy = -dy, dx
        elif b:
            dx, dy = dy, -dx
        else:
            x, y = x+dx, y+dy
            if y < 0: out = x
            elif x >= n: out = n+y
            elif y >= n: out = 3*n-1-x
            elif x < 0: out = 4*n-1-y
            else: continue
            return "R" if out == port else out
    return "R"


def beam_y(contract, angle):
    o = contract["optics"]
    # Incident ray points down (90 degrees), mirror is 45+angle degrees.
    # Reflection therefore points at 2*angle degrees from the horizontal.
    return (o["receiver_x"]-o["mirror_x"])*math.tan(math.radians(2*angle))


def trim_point(contract, channel, angle):
    o = contract["optics"]
    return [o["trim_left"]+(angle/o["mirror_limit_deg"]+1)/2*(o["trim_right"]-o["trim_left"]),
            o["row_centers"][channel]+69]


def trim_angle(contract, point):
    o = contract["optics"]
    return clamp((point[0]-o["trim_left"])/(o["trim_right"]-o["trim_left"])*2-1, -1, 1)*o["mirror_limit_deg"]


class Physics:
    def __init__(self, contract):
        self.contract = contract
        count = len(contract["channels"])
        self.tick = self.active_tick = 0
        self.started = self.ready = self.complete = False
        self.failed = ""
        self.angles = [0.0]*count
        self.velocities = [0.0]*count
        self.targets = [0.0]*count
        self.positions = [c["initial_y"] for c in contract["channels"]]
        self.directions = [c["direction"] for c in contract["channels"]]
        self.charges = [0.0]*count
        self.heat = [0.0]*count
        self.hits = [False]*count

    def advance(self, target_tick):
        p, req, o = self.contract["parameters"], self.contract["requirements"], self.contract["optics"]
        while self.tick < target_tick and not self.failed and not self.complete:
            self.tick += 1
            velocities = []
            for angle, velocity, goal in zip(self.angles, self.velocities, self.targets):
                acceleration = clamp((goal-angle)*100-velocity*20, -p["servo_acceleration"], p["servo_acceleration"])
                velocities.append(clamp(velocity+acceleration*.01, -p["servo_speed"], p["servo_speed"]))
            total = sum(abs(v) for v in velocities)
            scale = min(1, p["shared_slew_budget"]/total) if total else 1
            self.velocities = [v*scale for v in velocities]
            for i, velocity in enumerate(self.velocities):
                self.angles[i] = clamp(self.angles[i]+velocity*.01, -o["mirror_limit_deg"], o["mirror_limit_deg"])
                if abs(self.angles[i]) == o["mirror_limit_deg"]:
                    self.velocities[i] = 0
            if not self.started:
                if self.tick >= req["max_ticks"]:
                    self.failed = "The optical supply expired."
                continue
            self.active_tick += 1
            for i, channel in enumerate(self.contract["channels"]):
                self.positions[i] += self.directions[i]*speed(self.contract, channel, self.active_tick)*.01
                bound = o["rail_half_span"]
                if self.positions[i] > bound:
                    self.positions[i], self.directions[i] = 2*bound-self.positions[i], -1
                elif self.positions[i] < -bound:
                    self.positions[i], self.directions[i] = -2*bound-self.positions[i], 1
                self.hits[i] = abs(beam_y(self.contract, self.angles[i])-self.positions[i])+o["beam_width"]/2 <= p["receiver_height"]/2
                if not self.ready:
                    self.charges[i] = clamp(self.charges[i]+(.01 if self.hits[i] else -.01*req["charge_leak"]), 0, p["charge_seconds"])
                    self.heat[i] = clamp(self.heat[i]+(-.01*req["cooling_rate"] if self.hits[i] else .01), 0, p["heat_limit_seconds"])
            if any(h >= p["heat_limit_seconds"]-1e-9 for h in self.heat):
                self.failed = "A receiver overheated."
            elif all(c >= p["charge_seconds"]-1e-9 for c in self.charges):
                # Capacitors isolate the stored charge. The receiver continues
                # moving until the player physically inserts the seal key.
                self.ready = True
            if self.active_tick >= req["active_limit_ticks"] or self.tick >= req["max_ticks"]:
                self.failed = "The optical supply expired."

    def action_step(self):
        """Advance one fixed transition caused by a deliberate control action."""
        step = self.contract["requirements"].get("action_step_ticks")
        if type(step) is not int or step <= 0:
            raise ValueError("invalid action transition")
        self.advance(min(self.tick + step, self.contract["requirements"]["max_ticks"]))

    def place_key(self, point):
        o, p = self.contract["optics"], self.contract["parameters"]
        if not self.ready or self.failed or self.complete:
            raise ValueError("The seal key is not available")
        radius = o["seal_key_radius"]
        center = o["row_centers"][0]+self.positions[0]
        if abs(point[0]-o["receiver_x"])+radius <= o["receiver_width"]/2 and abs(point[1]-center)+radius <= p["receiver_height"]/2:
            self.complete = True
        else:
            self.failed = "The seal key missed AMBER's moving opening."

    def snapshot(self):
        return dict(tick=self.tick, active_tick=self.active_tick, started=self.started, ready=self.ready, complete=self.complete,
                    failed=self.failed, angles=[round(x, 6) for x in self.angles],
                    velocities=[round(x, 6) for x in self.velocities], targets=[round(x, 6) for x in self.targets],
                    positions=[round(x, 6) for x in self.positions], directions=list(self.directions),
                    charges=[round(x, 6) for x in self.charges], heat=[round(x, 6) for x in self.heat])


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("nonfinite or nonnumeric value")
    return value


def _point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("malformed pointer point")
    return [_number(x) for x in value]


def _inside(point, box):
    return abs(point[0]-box["x"]) <= box.get("width", box.get("size", 0))/2+.001 and abs(point[1]-box["y"]) <= box.get("height", box.get("size", 0))/2+.001


def _fail(message):
    return dict(graded=True, passed=False, score=0, feedback=message)


def grade(payload, truth, public):
    if not all(isinstance(x, dict) for x in (payload, truth, public)):
        return _fail("Malformed submission")
    for key in ("mechanic_id", "task_id", "challenge_id", "physics_revision"):
        if not truth.get(key) or payload.get(key) != truth[key] or public.get(key) != truth[key]:
            return _fail("Stale task, challenge or physics revision")
    if truth["mechanic_id"] != MECHANIC_ID or truth["physics_revision"] != REVISION:
        return _fail("Wrong mechanic or physics")
    try:
        for key in ("parameters", "cabinet", "channels", "optics", "requirements", "control_condition"):
            if public.get(key) != truth.get(key):
                raise ValueError("Public contract mismatch: "+key)
        condition = truth.get("control_condition")
        mode = (condition or {}).get("interaction", "full")
        if mode not in ("full", "simplified") or payload.get("interaction_mode") != mode or payload.get("control_condition") != condition:
            raise ValueError("Wrong control condition or interaction")
        params = truth["parameters"]
        if condition is not None and condition.get("difficulty_parameters") != params:
            raise ValueError("Difficulty parameters mismatch")
        expected = [ray(params["size"], truth["beads"], p) for p in range(4*params["size"])]
        if public.get("sensor_responses") != expected:
            raise ValueError("Optical response disagrees with hidden beads")
        events = payload.get("events")
        if events == []:
            return _fail("Patch the lamps, then charge the receiver bank before sealing.")
        if not isinstance(events, list) or not 1 <= len(events) <= truth["requirements"]["max_events"]:
            raise ValueError("Missing or excessive transcript")
        count, cabinet = len(truth["channels"]), truth["cabinet"]
        sim, routes, selected, hold = Physics(truth), [None]*count, None, None
        key_selected = False
        def index(value, limit):
            if type(value) is not int or not 0 <= value < limit:
                raise ValueError("Invalid target index")
            return value
        for seq, event in enumerate(events, 1):
            if not isinstance(event, dict) or type(event.get("sequence")) is not int or event["sequence"] != seq:
                raise ValueError("Invalid event sequence")
            tick = event.get("tick")
            if type(tick) is not int or tick != sim.tick or not 0 <= tick <= truth["requirements"]["max_ticks"]:
                raise ValueError("Only action-triggered fixed transitions may advance time")
            if sim.failed or sim.complete:
                raise ValueError("Input after a terminal outcome")
            kind, surface = event.get("kind"), event.get("input_surface")
            if kind == "probe":
                port, point = index(event.get("port"), len(expected)), _point(event.get("point"))
                if sim.started or hold or selected is not None or surface != "port_probe" or not _inside(point, cabinet["ports"][port]):
                    raise ValueError("Probe outside available port")
                if type(event.get("response")) is not type(expected[port]) or event["response"] != expected[port]:
                    raise ValueError("Forged probe response")
            elif kind == "select_socket":
                channel, point = index(event.get("channel"), count), _point(event.get("point"))
                if sim.started or hold or mode != "simplified" or surface != "patch_click" or not _inside(point, cabinet["sockets"][channel]):
                    raise ValueError("Wrong socket selection")
                selected = channel
            elif kind == "clear_selection":
                if sim.started or mode != "simplified" or surface != "patch_click":
                    raise ValueError("Wrong probe-mode control")
                selected = None
            elif kind == "patch_start":
                channel, point = index(event.get("channel"), count), _point(event.get("point"))
                if sim.started or hold or mode != "full" or surface != "patch_drag" or not _inside(point, cabinet["sockets"][channel]):
                    raise ValueError("Cable drag must start at its socket")
                hold = ("patch", channel)
            elif kind in ("patch_end", "patch_click"):
                channel, point = index(event.get("channel"), count), _point(event.get("point"))
                port = event.get("port")
                if sim.started:
                    raise ValueError("Routing cannot change during the optical run")
                if kind == "patch_end":
                    if mode != "full" or surface != "patch_drag" or hold != ("patch", channel):
                        raise ValueError("Missing cable drag")
                    hold = None
                elif mode != "simplified" or surface != "patch_click" or hold or selected != channel:
                    raise ValueError("Wrong patch proxy")
                if port is not None:
                    port = index(port, len(expected))
                    if not _inside(point, cabinet["ports"][port]):
                        raise ValueError("Cable does not land at a visible port")
                    routes[channel] = port
                selected = None
            elif kind in ("trim_start", "trim_move", "trim_end", "trim_target"):
                channel, point = index(event.get("channel"), count), _point(event.get("point"))
                o = truth["optics"]
                source = "trim_drag" if mode == "full" else "trim_click"
                if key_selected or surface != source or not 0 <= point[0] <= o["width"] or not 0 <= point[1] <= o["height"]:
                    raise ValueError("Wrong trim input surface or pointer bounds")
                if kind == "trim_start":
                    if mode != "full" or hold or math.dist(point, trim_point(truth, channel, sim.targets[channel])) > 19.001:
                        raise ValueError("Trim drag must start on the visible handle")
                    hold = ("trim", channel)
                elif kind == "trim_target":
                    if mode != "simplified" or hold or abs(point[1]-(o["row_centers"][channel]+69)) > 19 or not o["trim_left"]-19 <= point[0] <= o["trim_right"]+19:
                        raise ValueError("Click the trim rail")
                    sim.targets[channel] = trim_angle(truth, point)
                    sim.action_step()
                elif mode != "full" or hold != ("trim", channel):
                    raise ValueError("No held trim handle")
                elif kind == "trim_move":
                    sim.targets[channel] = trim_angle(truth, point)
                elif kind == "trim_end":
                    # Sparse native delivery can omit the final pointermove.
                    sim.targets[channel] = trim_angle(truth, point)
                    hold = None
                    sim.action_step()
            elif kind in ("seal_start", "seal_select"):
                point = _point(event.get("point"))
                if not sim.ready or hold or key_selected or not _inside(point, cabinet["seal_key"]):
                    raise ValueError("Pick up the charged seal key")
                if kind == "seal_start":
                    if mode != "full" or surface != "seal_drag":
                        raise ValueError("Wrong seal input surface")
                    hold = ("seal", 0)
                else:
                    if mode != "simplified" or surface != "seal_click":
                        raise ValueError("Wrong seal input surface")
                    key_selected = True
            elif kind in ("seal_end", "seal_click", "seal_cancel"):
                point = _point(event.get("point"))
                if kind in ("seal_end", "seal_cancel"):
                    if mode != "full" or surface != "seal_drag" or hold != ("seal", 0):
                        raise ValueError("Missing held seal key")
                    hold = None
                elif mode != "simplified" or surface != "seal_click" or not key_selected or hold:
                    raise ValueError("Select the seal key before placing it")
                key_selected = False
                if kind == "seal_cancel":
                    sim.failed = "The seal key was dropped outside the receiver."
                else:
                    sim.place_key(point)
            elif kind == "start":
                if surface != "start_button" or sim.started or hold:
                    raise ValueError("Duplicate start or overlapping hold")
                sim.started = True
                if any(r is None or expected[r] != c["exit_port"] for r, c in zip(routes, truth["channels"])):
                    sim.failed = "An optical cable feeds the wrong exit."
                else:
                    sim.action_step()
            else:
                raise ValueError("Unknown action; stop, reset and rewind are unavailable")
        final_tick = payload.get("final_tick")
        if type(final_tick) is not int or final_tick != sim.tick or not 0 <= final_tick <= truth["requirements"]["max_ticks"]:
            raise ValueError("Final tick does not match the action-stepped replay")
        if sim.tick != final_tick or payload.get("routes") != routes:
            raise ValueError("Terminal time or routes differ from replay")
        snapshot = payload.get("final_state")
        if not isinstance(snapshot, dict):
            raise ValueError("Missing final physical state")
        for key, value in sim.snapshot().items():
            actual = snapshot.get(key)
            if isinstance(value, list):
                if not isinstance(actual, list) or len(actual) != len(value) or any(abs(_number(a)-b) > 3e-5 for a, b in zip(actual, value)):
                    raise ValueError("Final "+key+" differs from physical replay")
            elif type(actual) is not type(value) or actual != value:
                raise ValueError("Final "+key+" differs from physical replay")
        passed = sim.complete and not sim.failed and payload.get("completed") is True
        return dict(graded=True, passed=passed, score=100 if passed else 0,
                    feedback="Receiver bank charged and seal key inserted. Vault opened." if passed else sim.failed or ("Place the charged seal key inside AMBER's moving opening." if sim.ready else "Charge every receiver before sealing the vault."),
                    metrics=dict(active_seconds=sim.active_tick*.01, channels=count, charge=sim.charges, heat=sim.heat,
                                 probe_count=sum(e["kind"] == "probe" for e in events)))
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as error:
        return _fail("Invalid optical replay: "+str(error))
