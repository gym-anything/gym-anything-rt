"""Original seeded four-picture registration world; no copied commercial assets."""
import copy
import hashlib
import random

MECHANIC_ID = 'four_pane_pilgrimage_v2'
BASELINE = dict(active_panes=4, x_amplitude=85, y_amplitude=44,
                radius_amplitude=10, segment_ms=11000, position_tolerance=19, radius_tolerance=5,
                segment_factor_min=.8, segment_factor_max=1.25)


def generate(task, seed):
    condition = copy.deepcopy(task.get('_control_condition'))
    p = copy.deepcopy((condition or {}).get('difficulty_parameters', BASELINE))
    if set(p) != set(BASELINE) or p['active_panes'] not in range(1, 5):
        raise ValueError('Invalid registration profile')
    rng = random.Random(hashlib.sha256(f'{seed}|{MECHANIC_ID}|1'.encode()).digest())
    route = list(range(4)); rng.shuffle(route)
    slots = route.copy(); rng.shuffle(slots)
    if slots == route: slots[0], slots[1] = slots[1], slots[0]
    tray = list(range(4)); rng.shuffle(tray)
    panels = []
    for i in range(4):
        active = route.index(i) < p['active_panes']
        knots = []
        time = 0
        side = rng.choice((-1, 1))
        while time < 210000:
            knots.append([time, 170 + (side * rng.uniform(.7, 1) * p['x_amplitude'] if active else 0),
                          110 + (rng.uniform(-1, 1) * p['y_amplitude'] if active else 0),
                          44 + (rng.uniform(-1, 1) * p['radius_amplitude'] if active else 0)])
            side *= -1
            time += int(p['segment_ms'] * rng.uniform(p['segment_factor_min'], p['segment_factor_max']))
        panels.append(dict(id=i, knots=knots, scene=i, active=active,
                           hatching=[[rng.randrange(10, 330), rng.randrange(20, 210), rng.randrange(8, 25)] for _ in range(16)]))
    public = dict(benchmark='gym_anything_rt', mechanic_id=MECHANIC_ID,
                  task_id=task['id'], challenge_id=hashlib.sha256(f'{task["id"]}|{seed}|registration-v2'.encode()).hexdigest()[:16],
                  prompt='Keep the four lanterns inside their matching windows. Carry the light to the shrine.',
                  route=route, initial_slots=slots, tray=tray, panels=panels, parameters=p,
                  tick_ms=20, journey_ms=24000, retreat_rate=2, burn_ms=150000,
                  bounds=dict(x=[45, 295], y=[40, 180], r=[24, 66]), radius_step=2,
                  asset_manifest=f'shared_runtime/assets/provenance/{MECHANIC_ID}_v0.json',
                  generator=dict(name='four-pane-drifting-registration-v2', variant_count=10**18))
    if condition: public['control_condition'] = condition
    return public, dict(copy.deepcopy(public), seed=str(seed))
