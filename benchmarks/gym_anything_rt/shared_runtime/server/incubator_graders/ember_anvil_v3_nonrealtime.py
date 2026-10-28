"""Standalone replay of contact geometry, local heat and conserved solid volume.

No generator/browser imports; also runs unchanged in the static Pyodide grader.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import sys

MECHANIC_ID = 'ember_anvil_v3_nonrealtime'
REVISION = 'kinetic-smithing-1'
RETRY_POLICY = 'first_failure'
ACTION_STEP_MS = 800
DIRS = ((1,0),(0,1),(-1,0),(0,-1))


def episode_failure_from_attempts(attempts, task_id):
    """Only the server's archived grading decisions establish prior failure.

    Air/cold/blocked feedback and cancelled pickups never submit /result and
    never enter this journal. Keep the first rejected commitment across seeds.
    """
    if not isinstance(attempts, list) or not isinstance(task_id, str) or not task_id:
        return None, 'Invalid episode failure history.'
    for attempt in attempts:
        if not isinstance(attempt, dict):
            return None, 'Invalid episode failure history.'
        decision = attempt.get('server_grade')
        if (not isinstance(decision, dict) or decision.get('graded') is not True
                or decision.get('passed') is not False):
            return None, 'Episode history lacks a verified failed submission.'
        mechanic = decision.get('episode_mechanic_id', attempt.get('mechanic_id'))
        bound_task = decision.get('episode_task_id', attempt.get('task_id'))
        if not isinstance(mechanic, str) or not isinstance(bound_task, str) or not bound_task:
            return None, 'Episode history has no verified task binding.'
        if mechanic == MECHANIC_ID and bound_task == task_id:
            return 'A failed submission already ended this episode.', None
    return None, None


def episode_state_directory():
    """Use the existing live server/setup path; offline replay has no journal."""
    directory = os.environ.get('GYM_ANYTHING_RT_STATE_DIR')
    if directory:
        return directory
    # The frozen shared commands already pass --state-dir. No core hook is
    # needed, including when its default path was selected by setup.
    if Path(sys.argv[0]).name in ('minigame_server.py', 'setup_task.py'):
        if '--state-dir' in sys.argv:
            index = sys.argv.index('--state-dir') + 1
            if index < len(sys.argv):
                return sys.argv[index]
        return '/tmp/gym_anything_rt'
    return None


def read_attempts(directory):
    if not directory:
        return [], None
    try:
        text = (Path(directory) / 'attempts.jsonl').read_text(encoding='utf-8')
        return [json.loads(line) for line in text.splitlines() if line.strip()], None
    except FileNotFoundError:
        return [], None
    except (OSError, UnicodeError, ValueError):
        return None, 'Episode failure history is unavailable.'


def read_episode_failure(task_id, directory=None):
    attempts, error = read_attempts(directory if directory is not None else episode_state_directory())
    return (None, error) if error else episode_failure_from_attempts(attempts, task_id)


def attach_episode_history(exported, directory):
    """Task-local export extension; preserve all shared fields and the journal."""
    attempts, error = read_attempts(directory)
    truth = exported.get('ground_truth') or {}
    exported['ember_anvil_episode_history'] = dict(schema_version=1,
        mechanic_id=truth.get('mechanic_id'), task_id=truth.get('task_id'),
        attempts=attempts, error=error)
    return exported


def verify_export(exported):
    if not isinstance(exported, dict):
        return fail('Invalid exported result.')
    truth, public = exported.get('ground_truth'), exported.get('public_state')
    if not isinstance(truth, dict) or not isinstance(public, dict):
        return fail('Missing task binding.')
    failures = exported.get('graded_failures')
    if type(failures) is not int or failures < 0:
        return fail('Invalid graded failure count.')
    if failures:
        return fail('A failed submission already ended this episode.')
    history = exported.get('ember_anvil_episode_history')
    if (not isinstance(history, dict) or history.get('schema_version') != 1
            or history.get('mechanic_id') != MECHANIC_ID
            or history.get('task_id') != truth.get('task_id') or history.get('error')):
        return fail('Missing or invalid bound episode history.')
    attempts = history.get('attempts')
    failure, error = episode_failure_from_attempts(attempts, truth.get('task_id'))
    if failure or error:
        return fail(failure or error)
    if len(attempts) != failures:
        return fail('Episode journal and failure count differ.')
    # This replay is detached from the live server. Its bound export history
    # above is authoritative; an ambient server directory belongs to another
    # episode and must not affect independent verification.
    return _grade_attempt(exported.get('result'), truth, public)


def noise(seed, index):
    value = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    value = ((value ^ (value >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    value = ((value ^ (value >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((value ^ (value >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0, ms)/span
    index = math.floor(u)
    f = u-index
    a, b = noise(seed,index), noise(seed,index+1)
    return a+(b-a)*f*f*(3-2*f)


def pose(w, ms):
    values = [w['travel'][i]*motion(w['motion_seed']+i*7919,ms,w['motion_span_ms']) for i in range(3)]
    return w['origin'][0]+values[0], w['origin'][1]+values[1], values[2]


def heat(w, cell, ms):
    return .60+.40*motion(w['heat_seeds'][cell],ms,w['heat_span_ms'])


def project(w, cell, ms):
    cx,cy,a = pose(w,ms)
    x,y = (cell%w['size']+.5-w['size']/2)*w['cell_px'], (cell//w['size']+.5-w['size']/2)*w['cell_px']
    return [cx+x*math.cos(a)-y*math.sin(a), cy+x*math.sin(a)+y*math.cos(a)]


def contact(w, point, ms):
    cx,cy,a = pose(w,ms)
    dx,dy = point[0]-cx,point[1]-cy
    x = (dx*math.cos(a)+dy*math.sin(a))/w['cell_px']+w['size']/2
    y = (-dx*math.sin(a)+dy*math.cos(a))/w['cell_px']+w['size']/2
    ix,iy = math.floor(x),math.floor(y)
    edge = w['face_inset']/w['cell_px']
    if not 0 <= ix < w['size'] or not 0 <= iy < w['size'] or not edge <= x-ix <= 1-edge or not edge <= y-iy <= 1-edge:
        return None
    return iy*w['size']+ix


def strike(w, h, tool, direction, point, ms):
    out = h[:]
    i = contact(w,point,ms)
    if i is None or not h[i]:
        return out, i, 'air', 0
    if heat(w,i,ms) < w['workable']:
        return out, i, 'cold', 0
    if tool == 'split':
        out[i] -= 1
        return out, i, 'split', 1
    x,y = i%w['size']+DIRS[direction][0], i//w['size']+DIRS[direction][1]
    if not 0 <= x < w['size'] or not 0 <= y < w['size']:
        return out,i,'blocked',0
    j = y*w['size']+x
    if h[j] >= w['cap'] or (tool == 'draw' and h[j] >= h[i]) or (tool == 'upset' and h[j] != h[i]):
        return out,i,'blocked',0
    out[i] -= 1
    out[j] += 1
    return out,i,'moved',0


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def point(value,w):
    return isinstance(value,list) and len(value)==2 and all(finite(v) and 0 <= v <= w['stage'][i] for i,v in enumerate(value))


def inside(p,r):
    return r[0] <= p[0] <= r[0]+r[2] and r[1] <= p[1] <= r[1]+r[3]


def gauge_cell(p):
    """Target-canvas contact, independent of the moving billet's geometry."""
    if not isinstance(p,list) or len(p)!=2 or not all(finite(v) for v in p):
        return None
    x,y = math.floor((p[0]-55)/28),math.floor((p[1]-133)/28)
    if not 0<=x<5 or not 0<=y<5 or p[0]-(55+x*28)>26 or p[1]-(133+y*28)>26:
        return None
    return y*5+x


def fail(message):
    return dict(graded=True,passed=False,score=0,feedback=message)


def _grade_attempt(payload, truth, public):
    try:
        if not all(isinstance(x,dict) for x in (payload,truth,public)):
            return fail('malformed result')
        for key in ('mechanic_id','task_id','challenge_id'):
            if not truth.get(key) or payload.get(key)!=truth[key] or public.get(key)!=truth[key]:
                return fail('stale '+key)
        if truth['mechanic_id'] != MECHANIC_ID or public.get('world') != truth.get('world') or public.get('control_condition') != truth.get('control_condition'):
            return fail('render/replay contract mismatch')
        for key in ('single_attempt', 'episode_failed', 'episode_history_error'):
            if key in truth and public.get(key) != truth[key]:
                return fail('episode policy binding differs')
        if truth.get('single_attempt', True) is not True:
            return fail('first-failure policy is required')
        if type(truth.get('episode_failed', False)) is not bool:
            return fail('invalid episode failure latch')
        if truth.get('episode_failed') or truth.get('episode_history_error'):
            return fail(truth.get('episode_history_error') or 'A failed submission already ended this episode.')
        mode = (truth.get('control_condition') or {}).get('interaction','full')
        source = {'full':'hammer_drag','simplified':'contact_click'}.get(mode)
        if source is None or payload.get('interaction_mode') != mode:
            return fail('wrong interaction mode')
        w = truth['world']
        if (w['revision'] != REVISION or w['size']!=5 or w['stage'] != [860,450]
                or w.get('action_step_ms') != ACTION_STEP_MS):
            return fail('unsupported geometry revision')
        h = w['initial'][:]
        if len(h)!=25 or len(w['target'])!=25 or any(type(v) is not int or not 0<=v<=w['cap'] for v in h+w['target']):
            return fail('invalid solid')
        events = payload.get('events')
        if not isinstance(events,list) or len(events) < 2:
            return fail('missing trace')
        tool,direction,last,phase,discarded,begun,hold,terminal = 'draw',0,0,0,0,False,None,False
        for seq,e in enumerate(events,1):
            if not isinstance(e,dict) or e.get('seq')!=seq or terminal:
                return fail('invalid event order')
            ms = e.get('t_ms')
            if (type(ms) is not int or ms != phase or not 0 <= ms <= w['run_ms']
                    or (not begun and ms != 0)):
                return fail('invalid fixed action phase')
            last = ms
            kind = e.get('kind')
            if kind in ('mode','direction','begin','stamp'):
                if e.get('input_source') != 'tool_control':
                    return fail('wrong tool control surface')
                if kind=='mode':
                    if hold or e.get('tool') not in ('draw','upset','split'):
                        return fail('invalid hammer mode')
                    tool = e['tool']
                elif kind=='direction':
                    if hold or type(e.get('direction')) is not int or e['direction'] not in range(4):
                        return fail('invalid billet direction')
                    direction=e['direction']
                elif kind=='begin':
                    if begun or ms!=0:
                        return fail('duplicate run; no reset is available')
                    begun=True
                else:
                    if hold or not begun:
                        return fail('stamp during preparation or pointer hold')
                    if ms >= w['run_ms']:
                        return fail('fuel exhaustion ended this attempt')
                    terminal=True
            elif kind=='inspect':
                # Inspection is a safe information probe, never a commitment
                # or a mandatory-count prerequisite for an otherwise valid tool.
                cell=gauge_cell(e.get('point'))
                if (hold or e.get('input_source')!='target_gauge' or cell is None
                        or type(e.get('cell')) is not int or e['cell']!=cell
                        or type(e.get('layers')) is not int or e['layers']!=w['target'][cell]):
                    return fail('die gauge measurement differs from replay')
            elif kind in ('hammer_down','hammer_cancel'):
                if mode!='full' or not begun or e.get('input_source')!='hammer_drag' or not point(e.get('point'),w):
                    return fail('wrong hammer drag surface')
                if kind=='hammer_down':
                    if hold or not inside(e['point'],w['hammer_box']):
                        return fail('pick up the physical hammer')
                    hold=e['point']
                elif hold is None:
                    return fail('cancel without held hammer')
                else:
                    hold=None
            elif kind=='strike':
                if not begun or e.get('input_source')!=source or not point(e.get('point'),w):
                    return fail('wrong contact surface')
                if mode=='full':
                    if hold is None or math.dist(hold,e['point'])<8:
                        return fail('strike requires a hammer drag')
                    hold=None
                elif hold is not None:
                    return fail('unexpected held input')
                if e.get('tool')!=tool or e.get('direction')!=direction:
                    return fail('false tool state')
                if phase >= w['run_ms']:
                    return fail('fuel exhaustion ended this attempt')
                h,i,outcome,lost = strike(w,h,tool,direction,e['point'],ms)
                discarded += lost
                if e.get('cell')!=i or e.get('outcome')!=outcome or e.get('heights')!=h:
                    return fail('contact, heat or volume differs from replay')
                if sum(h)<sum(w['target']):
                    return fail('insufficient metal ended this attempt')
                phase = min(w['run_ms'], phase + ACTION_STEP_MS)
            else:
                return fail('unknown action; stop, reset and retry are unavailable')
        if not terminal or events[-1]['kind']!='stamp' or payload.get('final_t_ms')!=last:
            return fail('missing terminal stamp')
        if payload.get('heights')!=h or payload.get('discarded')!=discarded or sum(h)+discarded!=sum(w['initial']):
            return fail('material conservation or final solid differs')
        passed = h==w['target'] and payload.get('completed') is True
        return dict(graded=True,passed=passed,score=100 if passed else 0,
                    feedback='Complete moving tool accepted.' if passed else 'FAIL · solid differs from target.')
    except (KeyError,TypeError,ValueError,IndexError,OverflowError,ZeroDivisionError):
        return fail('malformed kinetic smithing trace')


def grade(payload, truth, public):
    decision = _grade_attempt(payload, truth, public)
    if decision.get('passed'):
        failure, error = read_episode_failure(truth['task_id'])
        if failure or error:
            decision = fail(failure or error)
    # Archive the actual server-bound task, rather than relying on an ID or
    # requested retry policy supplied only by the browser.
    if isinstance(truth, dict):
        decision.update(episode_task_id=truth.get('task_id'),
                        episode_mechanic_id=truth.get('mechanic_id'))
    return decision
