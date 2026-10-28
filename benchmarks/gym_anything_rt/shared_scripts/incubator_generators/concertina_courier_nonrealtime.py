"""Original fixed-area, nonrotating rectangle delivery room."""
import copy
import hashlib
import json
import random

MECHANIC_ID = 'concertina_courier_nonrealtime'
# The room and challenge identity are inherited from the v2 donor.  Keeping
# this separate from the plugin namespace makes corresponding seeds retain
# the donor's generated puzzle content.
CONTENT_MECHANIC_ID = 'concertina_courier_v2'
# The original linear configuration remains exactly available at controlled L2.
BASELINE_PARAMETERS = dict(layout='island', island_width=240,
                           gap_range=[80, 120], opening_range=[100, 120],
                           clearance=80, reach=160, drag=.85, well_clearance=90)


def generate(task, seed):
    public, truth = _generate_room(task, seed)
    # The donor's changing draft is the autonomous timing dependency.  The
    # counterpart keeps the same draft indicator surface but removes that
    # autonomous force from replay; controls alone move the parcel while
    # engaged, and release still gives the donor-style finite coast before
    # parking.  The room seed, object layout, and all control parameters
    # remain independent of the renamed plugin identity.
    fixed_wind = [0.0] * (public['max_ticks'] + 1)
    for world in (public, truth):
        world['wind'] = fixed_wind[:world['max_ticks'] + 1]
        world['prompt'] = ('Collect every gold seal. Use the visible controls; after '
                           'release the parcel coasts briefly, then holds its state '
                           'until the next deliberate control. Keep the parcel inside '
                           'the dashed open room edges.')
    return public, truth


def _generate_room(task, seed):
    condition = task.get('_control_condition')
    p = copy.deepcopy(condition['difficulty_parameters'] if condition else BASELINE_PARAMETERS)
    rng = random.Random(int(hashlib.sha256(str(seed).encode()).hexdigest()[:16], 16))
    if p.get('layout') == 'island':
        return _island(task, seed, p, rng)
    shift = rng.randint(-20, 20)
    tunnel = 240 + shift
    end = tunnel + rng.randint(100, 130)
    gap_start = 575 + rng.randint(-12, 12)
    gap_end = gap_start + p['gap']
    # Every platform is a full AABB, including the bottom faces of shelves.
    solids = [[0,420,gap_start,160], [gap_end,420,1000-gap_end,160],
              [tunnel,100,end-tunnel,320-p['clearance']]]
    if not p['gap']: solids = [[0,420,1000,160],solids[-1]]
    seals = [[145+rng.randint(-15,15),390],[(tunnel+end)/2,420-p['clearance']/2],
             [end+85,420-p['reach']], [850+rng.randint(-15,15),310]]
    if p['alcove']:
        # Vertical well between two shelves: tall body must approach flattened,
        # centre beneath the opening, then narrow while rising into it.
        solids += [[740,180,65,110],[890,180,90,110]]
        seals[-1] = [847+rng.randint(-8,8),235 if p['reach']<180 else 225]
    world = dict(area=6400,min_height=32,max_height=200,tick_ms=40,max_ticks=4500,
                 parameters=p,solids=solids,seals=seals,initial_state=dict(x=100.,bottom=420.,h=80.,vx=0.,vy=0.,tick=0,collected=[],status='active'))
    cid=hashlib.sha256((str(seed)+json.dumps(p,sort_keys=True)+CONTENT_MECHANIC_ID).encode()).hexdigest()[:16]
    pub=dict(benchmark='gym_anything_rt',mechanic_id=MECHANIC_ID,task_id=task.get('id','concertina_courier_nonrealtime_seed_0001@0.1'),challenge_id=cid,prompt='Collect every gold seal.',generator=dict(name='concertina_courier_v0',variant_count=1000000),asset_manifest='shared_runtime/assets/provenance/concertina_courier_v0.json',**world)
    truth=copy.deepcopy(pub);truth['seed']=seed
    if condition:
        pub['control_condition']=copy.deepcopy(condition);truth['control_condition']=copy.deepcopy(condition)
    return pub,truth


def _island(task, seed, p, rng):
    """A reversible morphology puzzle with an irreversible wrong-side fall.

    The far floor on one side is beyond the maximum parcel width. The other
    side can be bridged, then requires unfolding between visible shelves.
    Reflection, platform position, gap, well position and well width vary
    independently. There is no stored route or collection quota.
    """
    centre = rng.randint(385, 460)
    left = centre - p['island_width'] / 2
    right = centre + p['island_width'] / 2
    landing = right + rng.randint(*p['gap_range'])
    opening = rng.randint(*p['opening_range'])
    well = rng.randint(int(landing + 140), 890)
    roof_bottom = 420 - p['well_clearance']
    solids = [[0, 420, 30, 160], [left, 420, right-left, 160],
              [landing, 420, 1000-landing, 160],
              [landing+70, 160, well-opening/2-landing-70, roof_bottom-160],
              [well+opening/2, 160, 1000-well-opening/2, roof_bottom-160],
              [landing, 160, 40, 260-p['clearance']]]
    seals = [[centre+rng.randint(-35,35), 420-p['reach']],
             [(right+landing)/2, 398],
             [landing+35, 420-p['clearance']/2],
             [well, 420-p['reach']]]
    x = float(centre)
    if rng.randrange(2):
        solids = [[1000-x-w,y,w,h] for x,y,w,h in solids]
        seals = [[1000-x,y] for x,y in seals]
        x = 1000-x
    world = dict(area=6400,min_height=32,max_height=200,tick_ms=40,max_ticks=4500,
                 parameters=p,solids=solids,seals=seals,
                 initial_state=dict(x=x,bottom=420.,h=80.,vx=0.,vy=0.,tick=0,
                                    collected=[],status='active'))
    cid=hashlib.sha256((str(seed)+json.dumps(p,sort_keys=True)+CONTENT_MECHANIC_ID).encode()).hexdigest()[:16]
    pub=dict(benchmark='gym_anything_rt',mechanic_id=MECHANIC_ID,
             task_id=task.get('id','concertina_courier_nonrealtime_seed_0001@0.1'),
             challenge_id=cid,prompt='Collect every gold seal.',
             generator=dict(name='concertina_courier_v0',variant_count=1000000),
             asset_manifest='shared_runtime/assets/provenance/concertina_courier_v0.json',
             **world)
    if task.get('_control_condition'):
        pub['control_condition']=copy.deepcopy(task['_control_condition'])
    truth=copy.deepcopy(pub);truth['seed']=seed
    return pub,truth
