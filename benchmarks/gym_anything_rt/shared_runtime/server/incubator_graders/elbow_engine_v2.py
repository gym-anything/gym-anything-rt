"""Independent fixed-step replay of a two-link acrobot.

Coordinates: q1 from downward vertical; q2 relative elbow angle. The mass
matrix includes both bodies; generalized motor force is (0, torque).
RK4, 20 ms task ticks, time_scale converts task time to physical time.
"""
from __future__ import annotations
import math

MECHANIC_ID = 'elbow_engine_v2'



def motion_noise(seed, index):
    """Stable 32-bit mixing, independently implemented by the browser."""
    x = (int(seed) + (int(index) + 1) * 0x9E3779B9) & 0xffffffff
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xffffffff
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xffffffff
    return ((x ^ (x >> 16)) & 0xffffffff) / 2147483648 - 1


def motion_value(seed, t_ms, span_ms=1300):
    t = max(0.0, float(t_ms)) / span_ms
    index = int(t)
    u = t - index
    a, b = motion_noise(seed, index), motion_noise(seed, index + 1)
    return a + (b - a) * u * u * (3 - 2 * u)


def motion_integral(seed, t_ms, span_ms=1300):
    """Integral in seconds; a fresh smooth velocity segment follows each one."""
    t = max(0.0, float(t_ms)) / span_ms
    count = int(t)
    total = sum((motion_noise(seed, i) + motion_noise(seed, i + 1)) / 2 for i in range(count))
    u = t - count
    a, b = motion_noise(seed, count), motion_noise(seed, count + 1)
    return span_ms / 1000 * (total + a * u + (b - a) * (u**3 - .5 * u**4))


def disturbance(p, tick):
    return p['torque']*p['disturbance_fraction']*motion_value(p['disturbance_seed'],tick*p['tick_ms'],1500)


def derivative(s, torque, p):
    a, b, va, vb = s
    m1, m2, l1, l2 = (p[k] for k in ('mass1', 'mass2', 'length1', 'length2'))
    c1, c2 = l1/2, l2/2
    coupling = m2*l1*c2
    d11 = p['inertia1']+p['inertia2']+m1*c1*c1+m2*(l1*l1+c2*c2+2*l1*c2*math.cos(b))
    d12 = p['inertia2']+m2*(c2*c2+l1*c2*math.cos(b))
    d22 = p['inertia2']+m2*c2*c2
    gravity2 = m2*c2*p['gravity']*math.sin(a+b)
    gravity1 = (m1*c1+m2*l1)*p['gravity']*math.sin(a)+gravity2
    rhs1 = coupling*math.sin(b)*(2*va*vb+vb*vb)-gravity1-p['damping']*va
    rhs2 = torque-coupling*math.sin(b)*va*va-gravity2-p['damping']*vb
    det = d11*d22-d12*d12
    return [va, vb, (rhs1*d22-rhs2*d12)/det, (rhs2*d11-rhs1*d12)/det]


def step(s, torque, p):
    dt = p['tick_ms']/1000*p['time_scale']
    k1 = derivative(s, torque, p)
    k2 = derivative([v+dt*k/2 for v,k in zip(s,k1)], torque, p)
    k3 = derivative([v+dt*k/2 for v,k in zip(s,k2)], torque, p)
    k4 = derivative([v+dt*k for v,k in zip(s,k3)], torque, p)
    out = [v+dt*(a+2*b+2*c+d)/6 for v,a,b,c,d in zip(s,k1,k2,k3,k4)]
    # No velocity clamps, impulses, automatic pumping, or energy injection.
    return out


def height(s, p):
    return -p['length1']*math.cos(s[0])-p['length2']*math.cos(s[0]+s[1])


def energy(s, p):
    a,b,va,vb=s
    m1,m2,l1,l2=(p[k] for k in ('mass1','mass2','length1','length2'))
    d11=p['inertia1']+p['inertia2']+m1*(l1/2)**2+m2*(l1*l1+(l2/2)**2+l1*l2*math.cos(b))
    d12=p['inertia2']+m2*((l2/2)**2+l1*l2/2*math.cos(b))
    d22=p['inertia2']+m2*(l2/2)**2
    return .5*(d11*va*va+2*d12*va*vb+d22*vb*vb)-(m1*l1/2+m2*l1)*p['gravity']*math.cos(a)-m2*l2/2*p['gravity']*math.cos(a+b)


def grade(payload, truth, public):
    def result(passed, feedback):
        return {'graded': True, 'passed': passed, 'score': 100 if passed else 0, 'feedback': feedback}
    if not all(isinstance(value, dict) for value in (payload, truth, public)):
        return result(False, 'Physical contract must contain JSON objects')
    try:
        for key in ('mechanic_id','task_id','challenge_id'):
            if not truth.get(key) or payload.get(key) != truth[key] or public.get(key) != truth[key]:
                return result(False, 'Stale task or challenge')
        if truth['mechanic_id'] != MECHANIC_ID:
            return result(False, 'Wrong mechanic')
        for key in ('physics','initial','control_condition'):
            if truth.get(key) != public.get(key):
                return result(False, 'Generated contract differs')
        cond = truth.get('control_condition') or {}
        mode = cond.get('interaction','full')
        if mode not in ('full','simplified') or payload.get('control_condition') != truth.get('control_condition'):
            return result(False, 'Wrong condition')
        source = 'held_torque' if mode == 'full' else 'latched_torque'
        p=truth['physics']; s=list(truth['initial']); events=payload.get('events')
        if not isinstance(events,list) or not 2 <= len(events) <= 18002:
            return result(False,'Malformed torque transcript')
        tick=0; torque=0; started=False; crossed=False; final=False; held=0
        for seq,e in enumerate(events,1):
            if not isinstance(e,dict) or type(e.get('seq')) is not int or e['seq'] != seq or final:
                return result(False,'Invalid event order')
            t=e.get('tick')
            if type(t) is not int or not tick <= t <= p['max_ticks'] or (not started and t != 0):
                return result(False,'Invalid elapsed time')
            while tick < t:
                if crossed:
                    return result(False,'Time advanced after height hold completed')
                s=step(s,torque*p['torque']+disturbance(p,tick),p); tick+=1
                held=held+p['tick_ms'] if height(s,p)>p['target_height'] else 0
                crossed=held>=p['hold_ms']
            kind=e.get('type')
            if kind=='start':
                if started or seq!=1:
                    return result(False,'Duplicate start')
                started=True
            elif kind=='torque':
                u=e.get('value')
                if not started or crossed or tick>=p['max_ticks'] or type(u) is not int or u not in (-1,0,1) or u==torque or e.get('input_source')!=source:
                    return result(False,'Invalid torque control surface or transition')
                torque=u
            elif kind=='finish':
                if not started or seq!=len(events):
                    return result(False,'Invalid final event')
                final=True
                reported=e.get('state')
                if not isinstance(reported,list) or len(reported)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x-y)>1e-6 for x,y in zip(reported,s)):
                    return result(False,'Physical replay differs from displayed pose')
            else:
                return result(False,'Unknown event')
        passed=final and crossed and payload.get('completed') is True
        return result(passed, f'Height hold completed at {tick*p["tick_ms"]/1000:.2f}s' if passed else 'Tip did not sustain the height hold')
    except (KeyError,TypeError,ValueError,OverflowError):
        return result(False,'Malformed physical transcript')
