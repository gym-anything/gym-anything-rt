"""Separate V2: current-beat intentions are visible; future intentions vary by seed."""
import hashlib, random, copy, importlib.util
from pathlib import Path
_SPEC=importlib.util.spec_from_file_location("clockbeat_generation_replay",Path(__file__).resolve().parents[2]/"shared_runtime/server/incubator_graders/clockbeat_catacomb_nonrealtime.py")
_REPLAY=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_REPLAY)
MECHANIC_ID='clockbeat_catacomb_nonrealtime'
PROFILES={
 1:dict(size=7,wall_count=2,kinds=['crawler'],enemy_health=1,health=4),
 2:dict(size=7,wall_count=3,kinds=['crawler','hopper'],enemy_health=1,health=4),
 3:dict(size=8,wall_count=5,kinds=['crawler','hopper','hopper'],enemy_health=1,health=3),
 4:dict(size=8,wall_count=6,kinds=['crawler','hopper','lancer'],enemy_health=2,health=3),
 5:dict(size=9,wall_count=9,kinds=['crawler','hopper','lancer','lancer'],enemy_health=2,health=2)}

def generate(task,seed,_attempt=0):
    condition=task.get('_control_condition') or task.get('metadata',{}).get('control_condition')
    p=dict(PROFILES[4]);p.update((condition or {}).get('difficulty_parameters') or {})
    # Keep the counterpart's namespace separate while retaining the donor's
    # seeded board layout for corresponding seeds.
    rng=random.Random(int(hashlib.sha256((str(seed)+'|clockbeat_catacomb_v2|'+str(_attempt)).encode()).hexdigest(),16))
    n=p['size']; outer=[[x,y] for y in range(n) for x in range(n) if x in (0,n-1) or y in (0,n-1)]
    cells=[[x,y] for y in range(1,n-1) for x in range(1,n-1)]
    # Reject disconnected layouts; positions change independently of the input mode.
    for _ in range(100):
        wall=outer+rng.sample(cells,p['wall_count']);floor=[c for c in cells if c not in wall]
        reached=[floor[0]]
        for x,y in reached:
            for dx,dy in ((0,-1),(1,0),(0,1),(-1,0)):
                q=[x+dx,y+dy]
                if q in floor and q not in reached:reached.append(q)
        if len(reached)==len(floor):break
    start=rng.choice(floor); candidates=[c for c in floor if abs(c[0]-start[0])+abs(c[1]-start[1])>=3]
    locations=rng.sample(candidates,len(p['kinds'])+1)
    board=dict(size=n,walls=wall,start=start,exit=locations.pop(),enemies=[dict(id=i+1,kind=k,pos=locations[i],hp=p['enemy_health'],phase_seed=rng.getrandbits(32),offset=rng.randrange({'crawler':1,'hopper':2,'lancer':3}[k])) for i,k in enumerate(p['kinds'])],health=p['health'],beat_ms=1800,open_ms=1150,max_beats=100)
    try:
        _REPLAY.find_route(board,limit=40000)
    except RuntimeError:
        if _attempt>=30:raise ValueError('No reachable catacomb within generation budget')
        return generate(task,seed,_attempt+1)
    identity=hashlib.sha256((str(seed)+'|'+task['id']).encode()).hexdigest()[:16]
    public=dict(benchmark='gym_anything_rt',mechanic_id=MECHANIC_ID,task_id=task['id'],challenge_id=identity,board=board,prompt='Clear the sentries. Reach the stair alive.',generator=dict(name='clockbeat_catacomb_nonrealtime_v0',variant_count=1000000),asset_manifest='environments/clockbeat_catacomb_nonrealtime_env/provenance.json')
    truth=dict(mechanic_id=MECHANIC_ID,task_id=task['id'],challenge_id=identity,board=copy.deepcopy(board),seed=str(seed))
    if condition:public['control_condition']=copy.deepcopy(condition);truth['control_condition']=copy.deepcopy(condition)
    return public,truth
