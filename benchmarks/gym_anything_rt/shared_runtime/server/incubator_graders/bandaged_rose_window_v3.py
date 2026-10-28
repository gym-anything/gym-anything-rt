"""Independent analytic collar motion and bandaged permutation replay."""
import math
MECHANIC_ID = 'bandaged_rose_window_v3'
IDS = ('north','southwest','southeast')
SLOTS = ((3,7,6,0,5,4),(3,10,9,1,8,7),(3,4,12,2,11,10))

def noise(seed, n):
    x=(int(seed)^((n+1)*0x9e3779b9))&0xffffffff
    x=((x^(x>>16))*0x85ebca6b)&0xffffffff
    x=((x^(x>>13))*0xc2b2ae35)&0xffffffff
    return ((x^(x>>16))&0xffffffff)/4294967295*2-1

def integral(seed, t, span):
    u=max(0,t)/span;n=int(u);f=u-n
    total=sum((noise(seed,k)+noise(seed,k+1))/2 for k in range(n))
    a,b=noise(seed,n),noise(seed,n+1)
    return span*(total+a*f+(b-a)*(f**3-f**4/2))

def collar(rose, disc, t):
    c=rose['collars'][disc]
    raw=c['phase']+c['direction']*(rose['collar_speed']*t/1000+rose['collar_amplitude']*integral(c['seed'],t,rose['collar_span_ms'])/1000)
    return (raw+math.pi)%(2*math.pi)-math.pi

def legal(state, disc):
    return state.index(3) in SLOTS[disc] and all(p==disc or state.index(p) not in SLOTS[disc] for p in range(3))

def turn(state, disc, direction):
    out=list(state);s=SLOTS[disc];v=[state[k] for k in s];v=v[-1:]+v[:-1] if direction==1 else v[1:]+v[:1]
    for k,x in zip(s,v):out[k]=x
    return tuple(out)

def grade(payload, ground_truth, public_state):
    def fail(s):return dict(graded=True,passed=False,score=0,feedback=s)
    if not isinstance(payload,dict):return fail('invalid result')
    for k in ('mechanic_id','challenge_id','task_id'):
        if not ground_truth.get(k) or payload.get(k)!=ground_truth[k] or public_state.get(k)!=ground_truth[k]:return fail('stale or wrong '+k)
    if ground_truth['mechanic_id']!=MECHANIC_ID:return fail('wrong mechanic')
    r=ground_truth.get('rose')
    if not isinstance(r,dict) or public_state.get('rose')!=r or public_state.get('control_condition')!=ground_truth.get('control_condition'):return fail('public contract mismatch')
    mode=(ground_truth.get('control_condition') or {}).get('interaction','full')
    source={'full':'rim_drag','simplified':'proxy_buttons'}.get(mode)
    if not source or payload.get('interaction_mode')!=mode:return fail('wrong interaction')
    ev=payload.get('events')
    if not isinstance(ev,list) or not ev:return fail('missing transcript')
    s=tuple(r['initial_state']);turns=refused=0;prev=-1;last=-1e9;cracked=False;started=False;revealed=set()
    try:
        for n,e in enumerate(ev,1):
            t=e['t_ms']
            if type(t) not in (int,float) or not math.isfinite(t) or not 0<=t<=r['play_time_ms'] or t<prev or e['sequence']!=n:return fail('invalid sequence or task time')
            prev=t
            if cracked:return fail('actions after terminal crack')
            if e['kind']=='inspect':
                slot=e.get('slot_id');piece=e.get('piece_id')
                if (e.get('input_source')!='glass_patch' or type(slot) is not int or not 0<=slot<13
                        or type(piece) is not int or piece!=s[slot] or piece in revealed
                        or (not started and t!=0)):return fail('invalid glass inspection')
                revealed.add(piece);continue
            if e['kind']=='start':
                if started or t!=0 or e.get('input_source')!='start_button':return fail('invalid start')
                started=True;continue
            if e['kind']!='turn' or not started or e.get('input_source')!=source:return fail('wrong action surface or unstarted run')
            d=IDS.index(e['disc_id']);direction=e['direction']
            if type(direction) is not int or direction not in (-1,1) or e['before_state']!=list(s):return fail('invalid turn')
            if mode=='full':
                a,b=e.get('start_point'),e.get('end_point');disc=r['discs'][d];cx,cy=disc['center'];radius=disc['handle_radius'];base=disc['handle_angle']*math.pi/180
                if not all(isinstance(p,list) and len(p)==2 and all(type(x) in (int,float) and math.isfinite(x) for x in p) for p in (a,b)):return fail('missing drag geometry')
                # The painted SVG handle has radius 20 plus half its 7-unit stroke.
                if math.dist(a,[cx+math.cos(base)*radius,cy+math.sin(base)*radius])>23.5:return fail('drag did not start on handle')
                delta=(math.atan2(b[1]-cy,b[0]-cx)-math.atan2(a[1]-cy,a[0]-cx)+math.pi)%(2*math.pi)-math.pi
                if abs(delta)<.45 or (1 if delta>0 else -1)!=direction:return fail('invalid rim gesture')
            if not legal(s,d):outcome='refused';refused+=1
            elif t-last<r['cooldown_ms']:outcome='settling';refused+=1
            elif abs(collar(r,d,t))>r['notch_half_width']:outcome='cracked';cracked=True
            else:outcome='turned';s=turn(s,d,direction);turns+=1;last=t
            if e.get('outcome')!=outcome or e.get('after_state')!=list(s) or e.get('turns_after')!=turns:return fail('permutation or collar physics mismatch')
        end=payload['final_t_ms']
        if type(end) not in (int,float) or not math.isfinite(end) or end<prev or end>r['play_time_ms']+1000:return fail('invalid final task time')
        complete=started and not cracked and s==tuple(r['solved_state']) and end<=r['play_time_ms']
        if payload.get('final_state')!=list(s) or payload.get('successful_turns')!=turns or payload.get('refused_turns')!=refused or payload.get('cracked') is not cracked or payload.get('completed') is not complete:return fail('final claims mismatch')
        return dict(graded=True,passed=complete,score=100 if complete else 0,feedback=f'Collar and bandage replay: {turns} turns; '+('restored' if complete else 'cracked or incomplete'))
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as exc:return fail('invalid transcript: '+str(exc))

def cheat(ground_truth, public_state):
    return {'solution_moves':ground_truth.get('solution_moves',[])}
