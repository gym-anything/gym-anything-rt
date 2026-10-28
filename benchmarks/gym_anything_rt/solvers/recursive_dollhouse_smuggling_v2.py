"""Privileged causal planner; all actual inputs use the caller's mouse API.

Native checks supply the frozen HTTP gateway. Headless implementation checks
identify their Playwright transport separately and do not establish parity.
Only present state and the visible 500 ms aperture preview inform control.
"""
import time

READ = """(() => {
  const m=recursiveDollhouseSmugglingV2Model, s=m.state.physics, ms=m.ms;
  function noise(seed,index) {let x=(seed^Math.imul(index+1,0x9e3779b9))>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b)>>>0;x=Math.imul(x^(x>>>13),0xc2b2ae35)>>>0;
    return ((x^(x>>>16))>>>0)/4294967295*2-1;}
  function motion(seed,t,span) {const u=Math.max(0,t)/span,i=Math.floor(u),f=u-i;
    const a=noise(seed,i),b=noise(seed,i+1);return a+(b-a)*f*f*(3-2*f);}
  const rect=n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height];};
  return {ms,active:m.active,ended:m.ended,failed:m.failed,result:m.result,
    parcels:m.parcels.map((p,i)=>({...p,wind:s.wind*motion(p.wind_seed,ms,s.wind_span_ms),
      rail:rect(document.querySelector('.rd-rail[data-index="'+i+'"]'))})),
    gates:m.state.gates.map(g=>({x:g.x,y:g.base_y+g.drift*motion(g.motion_seed,ms,g.span_ms),
      future:g.base_y+g.drift*motion(g.motion_seed,ms+500,g.span_ms)})),
    stiffness:s.stiffness,damping:s.damping,
    start:rect(document.querySelector('#rd-start'))};
})()"""


def center(rect):
    return [rect[0]+rect[2]/2, rect[1]+rect[3]/2]


def target(snapshot, parcel):
    g = snapshot["gates"][parcel["transfers"]]
    velocity = (g["future"]-g["y"])/.5
    # Spring/damping compensation for a moving reference, using only the
    # physically displayed short preview and current pressure.
    return max(7, min(65, g["y"]+velocity*snapshot["damping"]/snapshot["stiffness"]
                      -parcel["wind"]/snapshot["stiffness"]))


def actions_for(snapshot, mode):
    actions = []
    for p in snapshot["parcels"]:
        if p["delivered"]:
            continue
        r = p["rail"]
        xy = lambda value: [r[0]+(value-7)/58*r[2], r[1]+r[3]/2]
        if mode == "simplified":
            actions.append({"mouse": {"left_click": xy(target(snapshot, p))}})
        else:
            actions.extend([
                {"mouse": {"move": xy(p["target"]), "buttons": {"left_down": True}}},
                {"action": "wait", "time": .015},
                {"mouse": {"move": xy(target(snapshot, p))}},
                {"action": "wait", "time": .015},
                {"mouse": {"buttons": {"left_up": True}}},
            ])
    return actions


def solve(ui, truth, cadence_s=.24, max_seconds=580):
    snapshot = ui.read(READ)
    ui.send([{"mouse": {"left_click": center(snapshot["start"])}}])
    deadline = time.monotonic()+max_seconds
    mode = truth["control_condition"]["interaction"]
    while time.monotonic() < deadline:
        snapshot = ui.read(READ)
        if snapshot["failed"]:
            raise AssertionError(snapshot["failed"])
        if snapshot["result"] is not None:
            assert snapshot["result"]["passed"], snapshot["result"]
            return
        if snapshot["ended"]:
            ui.wait(.05)
            continue
        ui.send(actions_for(snapshot, mode))
        ui.wait(cadence_s)
    raise AssertionError("nested-tether oracle exceeded its declared wall-time budget")
