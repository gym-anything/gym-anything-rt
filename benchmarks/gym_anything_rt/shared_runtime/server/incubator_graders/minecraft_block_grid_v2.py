"""Independent moving-voxel projection, ray occlusion and terminal replay.

Standalone for the existing Pyodide exporter; no browser completion claims are
trusted. Geometry is unit-cube geometry, not a screen-space target tolerance.
"""
from __future__ import annotations
import math

MECHANIC_ID = 'minecraft_block_grid_v2'
REVISION = 'moving-quarry-4'


def noise(seed, index):
    x = (int(seed) ^ ((int(index)+1)*0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16))*0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13))*0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF)/4294967295*2-1


def integral(seed, ms, span):
    u = max(0, ms)/span
    n, f = math.floor(u), u % 1
    total = sum((noise(seed, i)+noise(seed, i+1))/2 for i in range(n))
    a, b = noise(seed, n), noise(seed, n+1)
    return span*(total+a*f+(b-a)*(f**3-f**4/2))


def rack_x(contract, rack, ms):
    elapsed = max(0, ms-rack['spawn_ms'])
    return contract['travel']['entry_x']+rack['speed']*(elapsed+rack['speed_variation']*integral(
        rack['velocity_seed'], elapsed, rack['velocity_span_ms']))/1000


def rotate(x, y, view):
    return ((x, y), (-y, x), (-x, -y), (y, -x))[view]


def project(x, y, z, view):
    rx, ry = rotate(x, y, view)
    return 540+(rx-ry)*34, 274+(rx+ry)*16-z*34


def faces(contract, ms, view, removed=()):
    gone = set(removed)
    racks = {r['id']: r for r in contract['racks'] if r['spawn_ms'] <= ms and
             rack_x(contract, r, ms) < contract['travel']['exit_x']}
    cubes = [v for v in contract['voxels'] if v['rack'] in racks and v['id'] not in gone]
    occupied = {(v['rack'], *v['local']) for v in cubes}
    located = []
    for v in cubes:
        r = racks[v['rack']]
        x, y, z = v['local']
        x += rack_x(contract, r, ms)
        y += r['y']
        rx, ry = rotate(x, y, view)
        located.append((rx+ry, z, rx, v, x, y))
    located.sort(key=lambda a: (a[0], a[1], a[2], a[3]['id']))
    result = []
    # Front-facing neighbors after the quarter-turn view transformation.
    nx = ((1,0), (0,-1), (-1,0), (0,1))[view]
    ny = ((0,1), (1,0), (0,-1), (-1,0))[view]
    for _, z, _, v, x, y in located:
        sx, sy = project(x, y, z, view)
        lx, ly, lz = v['local']
        candidates = [
            ('right', nx[0], nx[1], 0, [(sx+34,sy+16),(sx,sy+32),(sx,sy+66),(sx+34,sy+50)]),
            ('left', ny[0], ny[1], 0, [(sx-34,sy+16),(sx,sy+32),(sx,sy+66),(sx-34,sy+50)]),
            ('top', 0, 0, 1, [(sx,sy),(sx+34,sy+16),(sx,sy+32),(sx-34,sy+16)])]
        for label, dx, dy, dz, poly in candidates:
            if (v['rack'], lx+dx, ly+dy, lz+dz) not in occupied:
                result.append(dict(voxel_id=v['id'], material=v['material'], face=label, points=poly))
    return result


def inside(point, poly):
    x, y = point
    result = False
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[i-1]
        if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/(yj-yi)+xi:
            result = not result
    return result


def raycast(contract, ms, view, removed, point):
    return next((f for f in reversed(faces(contract, ms, view, removed)) if inside(point, f['points'])), None)


def find_point(contract, ms, view, removed, voxel_id, margin=2):
    for face in reversed(faces(contract, ms, view, removed)):
        if face['voxel_id'] != voxel_id:
            continue
        a,b,c,d = face['points']
        for u in (.5,.3,.7):
            for v in (.5,.3,.7):
                point = [(1-u)*(1-v)*a[i]+u*(1-v)*b[i]+u*v*c[i]+(1-u)*v*d[i] for i in (0,1)]
                if all((raycast(contract, ms, view, removed, [point[0]+dx,point[1]+dy]) or {}).get('voxel_id') == voxel_id
                       for dx,dy in ((0,0),(margin,0),(-margin,0),(0,margin),(0,-margin))):
                    return point
    return None


def lost(contract, ms, removed):
    gone = set(removed)
    return next((r['id'] for r in contract['racks'] if f"{r['id']}-ore" not in gone and
                 rack_x(contract, r, ms) >= contract['travel']['exit_x']), None)


def finite(value):
    return type(value) in (float,int) and math.isfinite(value)


def grade(payload, ground_truth, public_state):
    def fail(reason):
        return dict(graded=True, passed=False, score=0, feedback=reason)
    try:
        for key in ('mechanic_id','task_id','challenge_id','revision'):
            if not ground_truth.get(key) or payload.get(key) != ground_truth[key] or public_state.get(key) != ground_truth[key]:
                return fail('stale or mismatched '+key)
        if ground_truth['mechanic_id'] != MECHANIC_ID or ground_truth['revision'] != REVISION:
            return fail('unsupported quarry revision')
        for key in ('stage','racks','voxels','travel','control_condition','target_count'):
            if public_state.get(key) != ground_truth.get(key):
                return fail('public contract mismatch: '+key)
        mode = ground_truth['control_condition']['interaction']
        if mode not in ('full','simplified') or payload.get('interaction_mode') != mode:
            return fail('wrong interaction mode')
        events = payload.get('events')
        if not isinstance(events,list) or not 1 <= len(events) <= 3000:
            return fail('missing or excessive action trace')
        removed, view, previous, launched, sealed, holding = set(), 0, -1, False, False, None
        lookup = {v['id']:v for v in ground_truth['voxels']}
        for seq, event in enumerate(events,1):
            if not isinstance(event,dict) or event.get('sequence') != seq or sealed:
                return fail('invalid event sequence or input after submission')
            t = event.get('t_ms')
            if not finite(t) or not previous <= t <= 180000:
                return fail('invalid event time')
            previous = t
            if launched and lost(ground_truth,t,removed):
                return fail('uncollected ore entered the crusher')
            kind, source = event.get('kind'), event.get('input_source')
            if kind == 'launch':
                if launched or t != 0 or source != 'launch_button':
                    return fail('duplicate or invalid launch')
                launched = True
            elif kind == 'rotate':
                expected = 'canvas_drag' if mode == 'full' else 'rotation_buttons'
                delta = event.get('delta')
                if source != expected or type(delta) is not int or delta not in (-1,1):
                    return fail('wrong camera input')
                if mode == 'full':
                    a,b = event.get('start'),event.get('end')
                    if not isinstance(a,list) or not isinstance(b,list) or len(a)!=2 or len(b)!=2 or not all(finite(x) for x in a+b):
                        return fail('camera drag missing physical endpoints')
                    if abs(b[0]-a[0]) < 48 or abs(b[0]-a[0]) <= abs(b[1]-a[1]) or delta != (1 if b[0]<a[0] else -1):
                        return fail('invalid camera gesture')
                view = (view+delta)%4
                if event.get('view') != view:
                    return fail('false camera view')
            elif kind == 'mine':
                p = event.get('point')
                if not launched or source != 'canvas_pick' or event.get('view') != view or not isinstance(p,list) or len(p)!=2 or not all(finite(x) for x in p):
                    return fail('invalid mining input')
                if not 0 <= p[0] <= 1080 or not 0 <= p[1] <= 530:
                    return fail('mining outside the canvas')
                hit = raycast(ground_truth,t,view,removed,p)
                target = hit['voxel_id'] if hit else None
                label = hit['face'] if hit else None
                if event.get('voxel_id') != target or event.get('face') != label:
                    return fail('mine does not hit the current frontmost face')
                if hit:
                    if lookup[target]['material'] == 'support':
                        return fail('protected support fractured')
                    removed.add(target)
            elif kind == 'seal':
                if source != 'exit_button' or not launched:
                    return fail('invalid exit')
                sealed = True
            elif kind == 'failure':
                return fail('terminal quarry failure recorded')
            else:
                return fail('unknown control; world-stop/reset unavailable')
        final = payload.get('final_t_ms')
        if not finite(final) or not previous <= final <= 180000 or lost(ground_truth,final,removed):
            return fail('invalid final time or lost ore')
        if sorted(removed) != payload.get('removed_ids') or payload.get('final_view') != view:
            return fail('claimed excavation differs from geometric replay')
        ores = {v['id'] for v in ground_truth['voxels'] if v['material'] == 'ore'}
        passed = sealed and launched and ores <= removed and payload.get('completed') is True
        return dict(graded=True,passed=passed,score=100 if passed else 0,
                    feedback=f'Excavated {len(ores & removed)}/{len(ores)} ore cores; supports intact.')
    except (TypeError,ValueError,KeyError,IndexError,OverflowError):
        return fail('malformed quarry transcript')


def cheat(public_state, ground_truth):
    return {'note':'No automatic success. Use visible mining and camera controls.'}
