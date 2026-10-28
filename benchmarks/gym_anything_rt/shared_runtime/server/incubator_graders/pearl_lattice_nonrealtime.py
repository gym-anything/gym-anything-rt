"""Independent replay grader for the Pearl Lattice 4x4x4 board."""

from __future__ import annotations

import itertools
import math
import copy
from typing import Any


MECHANIC_ID = "pearl_lattice_nonrealtime"
SIZE = 4
PLAYER = 1
OPPONENT = -1
EMPTY = 0
Coord = tuple[int, int, int]
Column = tuple[int, int]


def _fail(message: str) -> dict[str, Any]:
    return {"graded": True, "passed": False, "feedback": message}


def _line(start: Coord, direction: Coord) -> list[Coord]:
    return [tuple(start[i] + step * direction[i] for i in range(3)) for step in range(4)]


def _all_lines() -> list[list[Coord]]:
    lines: list[list[Coord]] = []
    for start in itertools.product(range(SIZE), repeat=3):
        for direction in itertools.product((-1, 0, 1), repeat=3):
            if direction == (0, 0, 0):
                continue
            end = tuple(start[i] + 3 * direction[i] for i in range(3))
            previous = tuple(start[i] - direction[i] for i in range(3))
            if not all(0 <= value < SIZE for value in end):
                continue
            if all(0 <= value < SIZE for value in previous):
                continue
            lines.append(_line(start, direction))
    return lines


ALL_LINES = _all_lines()


def _has_line(board: dict[Coord, int], mark: int) -> bool:
    return any(all(board.get(cell, EMPTY) == mark for cell in line) for line in ALL_LINES)


def _legal_columns(board: dict[Coord, int]) -> list[Column]:
    return [
        (x, z)
        for z in range(SIZE)
        for x in range(SIZE)
        if board.get((x, SIZE - 1, z), EMPTY) == EMPTY
    ]


def _height(board: dict[Coord, int], column: Column) -> int:
    for y in range(SIZE):
        if board.get((column[0], y, column[1]), EMPTY) == EMPTY:
            return y
    return SIZE


def _drop(board: dict[Coord, int], column: Column, mark: int) -> Coord | None:
    height = _height(board, column)
    if height >= SIZE:
        return None
    cell = (column[0], height, column[1])
    board[cell] = mark
    return cell


def _immediate_columns(board: dict[Coord, int], mark: int) -> list[Column]:
    result: list[Column] = []
    for column in _legal_columns(board):
        candidate = dict(board)
        _drop(candidate, column, mark)
        if _has_line(candidate, mark):
            result.append(column)
    return result


def _opponent_column(board: dict[Coord, int], pressure: list[Column], pressure_index: int, policy: str = "threat_then_block") -> tuple[Column | None, int]:
    own_wins = _immediate_columns(board, OPPONENT)
    if own_wins:
        return own_wins[0], pressure_index
    player_wins = _immediate_columns(board, PLAYER) if policy == "threat_then_block" else []
    if player_wins:
        return player_wins[0], pressure_index
    legal = set(_legal_columns(board))
    for offset in range(len(pressure)):
        column = tuple(int(value) for value in pressure[(pressure_index + offset) % len(pressure)])
        if column in legal:
            return column, pressure_index + offset + 1
    return (next((column for column in _legal_columns(board) if column in legal), None), pressure_index + 1)


def _parse_board(truth: dict[str, Any]) -> dict[Coord, int] | None:
    raw = truth.get("initial_board")
    if not isinstance(raw, dict):
        return None
    board: dict[Coord, int] = {}
    for raw_key, raw_value in raw.items():
        try:
            x, y, z = (int(value) for value in str(raw_key).split(","))
            value = int(raw_value)
        except (TypeError, ValueError):
            return None
        if not all(0 <= coord < SIZE for coord in (x, y, z)) or value not in {PLAYER, OPPONENT}:
            return None
        board[(x, y, z)] = value
    return board


def _column(value: Any) -> Column | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        result = (int(value[0]), int(value[1]))
    except (TypeError, ValueError):
        return None
    return result if all(0 <= item < SIZE for item in result) else None


def noise(seed, index):
    n = (int(seed) ^ ((int(index)+1)*0x9e3779b9)) & 0xffffffff
    n = ((n ^ (n >> 16))*0x85ebca6b) & 0xffffffff
    n = ((n ^ (n >> 13))*0xc2b2ae35) & 0xffffffff
    return ((n ^ (n >> 16)) & 0xffffffff)/4294967295*2-1


def motion(seed, ms, span):
    u = max(0, ms)/span
    i = math.floor(u)
    f = u-i
    a, b = noise(seed, i), noise(seed, i+1)
    return a+(b-a)*f*f*(3-2*f)


def gate_center(contract, layer, column, ms):
    gate = contract['physics']['collars'][layer]
    return [160+96*column[0]+gate['offset'][0]+gate['amplitude'][0]*motion(gate['seed'],ms,gate['span_ms']),
            96+96*column[1]+gate['offset'][1]+gate['amplitude'][1]*motion(gate['seed']+7919,ms,gate['span_ms'])]


def current(contract, ms):
    s = contract['physics']
    return [s['wind_acceleration']*motion(s['wind_seed']+7919*i,ms,s['wind_span_ms']) for i in range(2)]


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class CastingPhysics:
    """Independent fixed-step replay of input, steering, moving gates and gravity."""
    def __init__(self, contract):
        self.contract = contract
        self.s = contract['physics']
        self.tick = 0
        self.head = list(self.s['initial_magnet'])
        self.hv = [0.,0.]
        self.target = list(self.head)
        self.ball = None
        self.board = {tuple(map(int,k.split(','))):v for k,v in contract['initial_board'].items()}
        self.pressure_index = 0
        self.moves = 0
        self.won = False
        self.failed = ''
        self.landings = []

    def launch(self):
        if self.ball or self.won or self.failed:
            return False
        self.ball = dict(p=list(self.head),v=list(self.hv),depth=0.,vy=0.,gate=0,channel=None)
        return True

    def advance(self, end_tick):
        s = self.s
        while self.tick < end_tick and not self.won and not self.failed:
            self.tick += 1
            ms = self.tick*10
            for i, maximum in enumerate(s['field']):
                a = clamp((self.target[i]-self.head[i])*s['magnet_spring']-self.hv[i]*s['magnet_damping'], -s['magnet_acceleration'],s['magnet_acceleration'])
                self.hv[i] = clamp(self.hv[i]+a*.01, -s['magnet_speed'],s['magnet_speed'])
                self.head[i] = clamp(self.head[i]+self.hv[i]*.01,24,maximum-24)
                if self.head[i] in (24,maximum-24):self.hv[i] = 0.
            if not self.ball:
                continue
            b = self.ball
            old_p, old_depth = list(b['p']), b['depth']
            wind = current(self.contract, ms)
            for i, maximum in enumerate(s['field']):
                a = clamp((self.head[i]-b['p'][i])*s['steering_spring']-b['v'][i]*s['steering_damping']+wind[i], -s['pearl_acceleration'],s['pearl_acceleration'])
                b['v'][i] = clamp(b['v'][i]+a*.01, -s['pearl_speed'],s['pearl_speed'])
                b['p'][i] += b['v'][i]*.01
                if not s['pearl_radius'] <= b['p'][i] <= maximum-s['pearl_radius']:
                    self.failed = 'The pearl struck the outer glass.'
                    break
            if self.failed:break
            b['vy'] += s['gravity']*.01
            b['depth'] += b['vy']*.01
            layer = b['gate']
            rim = s['collars'][layer]['depth']
            if old_depth < rim <= b['depth']:
                f = (rim-old_depth)/(b['depth']-old_depth)
                point = [old_p[i]+f*(b['p'][i]-old_p[i]) for i in range(2)]
                crossing_ms = ms-10+10*f
                candidates = _legal_columns(self.board) if layer == 0 else [tuple(b['channel'])]
                hit = next((col for col in candidates if math.dist(point,gate_center(self.contract,layer,col,crossing_ms))+s['pearl_radius'] <= s['mouth_radius']+1e-9),None)
                if hit is None:
                    self.failed = f'The pearl struck the {"upper" if layer == 0 else "lower"} collar.'
                    break
                if layer == 0:
                    b['gate'],b['channel'] = 1,list(hit)
                else:
                    cell = _drop(self.board,hit,PLAYER)
                    if cell is None:
                        self.failed = 'The column is full.'
                        break
                    self.moves += 1
                    landing = dict(tick=self.tick,column=list(hit),height=cell[1],rival=None)
                    self.ball = None
                    self.won = _has_line(self.board,PLAYER)
                    if not self.won:
                        if self.moves >= self.contract['control_condition']['difficulty_parameters']['max_player_moves']:
                            self.failed = 'No jade line remains within the placement limit.'
                        else:
                            col,self.pressure_index = _opponent_column(self.board,[tuple(c) for c in self.contract['pressure_columns']],self.pressure_index,self.contract['control_condition']['difficulty_parameters']['opponent_policy'])
                            if col is None:self.failed = 'The glass lattice is full.'
                            else:
                                rival = _drop(self.board,col,OPPONENT)
                                landing['rival'] = list(rival)
                                if _has_line(self.board,OPPONENT):self.failed = 'The coral rival completed four.'
                    self.landings.append(landing)

    def snapshot(self):
        return dict(tick=self.tick,head=self.head,hv=self.hv,target=self.target,ball=self.ball,
                    board={'%d,%d,%d'%c:v for c,v in self.board.items()},moves=self.moves,
                    won=self.won,failed=self.failed,landings=self.landings)


def _number(v):
    if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('non-finite coordinate')
    return v


def _casting_point(v, field):
    if not isinstance(v,list) or len(v)!=2:raise ValueError('missing casting point')
    out=[_number(n) for n in v]
    if any(not 0<=n<=field[i] for i,n in enumerate(out)):raise ValueError('point outside casting field')
    return out


def grade(payload, truth, public):
    try:
        if not all(isinstance(o,dict) for o in (payload,truth,public)):return _fail('malformed casting contract')
        for key in ('mechanic_id','task_id','challenge_id'):
            if not truth.get(key) or payload.get(key)!=truth[key] or public.get(key)!=truth[key]:return _fail('stale or mismatched '+key)
        if truth['mechanic_id']!=MECHANIC_ID:return _fail('wrong casting mechanic')
        for key in ('control_condition','physics','initial_board','pressure_columns'):
            if public.get(key)!=truth.get(key):return _fail('public contract differs: '+key)
        mode=truth['control_condition']['interaction']
        if mode not in ('full','simplified') or payload.get('control_condition')!=truth['control_condition']:return _fail('wrong interaction condition')
        events=payload.get('events')
        if not isinstance(events,list) or not 1<=len(events)<=6000:return _fail('missing or excessive casting trace')
        physics=CastingPhysics(truth)
        action_step=int(truth.get('physics',{}).get('action_step_ticks',10))
        if action_step <= 0:return _fail('invalid action-step clock')
        held=False
        sealed=False
        for seq,event in enumerate(events,1):
            if not isinstance(event,dict) or event.get('seq')!=seq or sealed:return _fail('invalid casting event sequence')
            tick=event.get('tick')
            if type(tick) is not int or not physics.tick<=tick<=18000:return _fail('invalid casting action time')
            kind=event.get('kind')
            # Browser state is action-stepped, not wall-clock-stepped.  A
            # normal action consumes one bounded transition.  A terminal
            # collision can stop that transition at its exact crossing tick,
            # so a shorter tick is valid only when replaying the complete
            # bounded transition reaches that same terminal tick. Certification
            # is immediate after a completed line, or consumes one bounded
            # transition while incomplete.
            upper_tick = min(18000, physics.tick + action_step)
            if kind == 'seal':
                if physics.won or physics.failed:
                    if tick != physics.tick:
                        return _fail('invalid certification action time')
                elif tick != upper_tick:
                    probe = copy.deepcopy(physics)
                    probe.advance(upper_tick)
                    if not (probe.tick == tick and (probe.won or probe.failed)):
                        return _fail('invalid certification action time')
            else:
                if not physics.tick < tick <= upper_tick:
                    return _fail('casting actions must use the fixed action-step clock')
                if tick != upper_tick:
                    probe = copy.deepcopy(physics)
                    probe.advance(upper_tick)
                    if not (probe.tick == tick and (probe.won or probe.failed)):
                        return _fail('casting actions must use the fixed action-step clock')
            physics.advance(tick)
            if physics.tick != tick:
                return _fail('casting action ended before its recorded tick')
            if kind=='seal':
                if event.get('source')!='seal_button':return _fail('wrong certification control')
                sealed=True
                continue
            if (physics.failed or physics.won) and kind!='aim_end':return _fail('action after the terminal state')
            source='magnet_drag' if mode=='full' else 'magnet_click'
            if kind in ('aim_start','aim_move','aim_end','aim_target'):
                if event.get('source')!=source:return _fail('wrong magnet input surface')
                point=_casting_point(event.get('point'),truth['physics']['field'])
                if kind=='aim_target':
                    if mode!='simplified' or held:return _fail('click target is simplified only')
                    physics.target=point
                elif mode!='full':return _fail('drag is full interaction only')
                elif kind=='aim_start':
                    if held or math.dist(point,physics.head)>truth['physics']['magnet_radius']+.01:return _fail('drag must begin on the visible magnet')
                    held=True
                elif not held:return _fail('magnet is not held')
                elif kind=='aim_move':physics.target=point
                elif kind=='aim_end':held=False
            elif kind=='launch':
                if event.get('source')!='release_button' or held or not physics.launch():return _fail('invalid release')
            else:return _fail('unknown casting action; no reset or stop control exists')
        if not sealed or held:return _fail('casting is not certified or the drag remains held')
        if payload.get('final_tick')!=physics.tick:return _fail('false final casting time')
        if payload.get('final_board')!=physics.snapshot()['board'] or payload.get('landings')!=physics.landings:return _fail('landing geometry differs from independent replay')
        if physics.failed:return _fail(physics.failed)
        if not physics.won or physics.ball or payload.get('completed') is not True:return _fail('no completed jade four-in-a-row')
        return dict(graded=True,passed=True,score=100,feedback=f'Independent double-collar and 3D gravity replay: {physics.moves} cast pearls; jade line verified.')
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as exc:
        return _fail('invalid casting trace: '+str(exc))


def cheat(public_state,ground_truth):
    return dict(note='Privileged oracle plan; not a screenshot-only solution.',solution_moves=ground_truth.get('solution_moves'))
