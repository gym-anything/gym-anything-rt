"""Model-facing HTTP contract for the benchmark's Codex adapter."""

from __future__ import annotations

from gym_anything_rt.agents.codex_actions import (
    KEYBOARD_FIELDS,
    MOUSE_BUTTONS,
    MOUSE_DRAGS,
    MOUSE_POINTS,
)
from gym_anything_rt.agents.temporal_modes import (
    scheduled_execution_enabled,
    timestamps_enabled,
    validate_temporal_mode,
)


def build_codex_prompt(
    task_description: str,
    resolution: tuple[int, int],
    max_steps: int,
    temporal_mode: str = "live",
) -> str:
    validate_temporal_mode(temporal_mode)
    width, height = resolution
    if temporal_mode == "paused":
        timing = """The task clock is paused while you reason and while inputs are delivered.
Each screenshot request or step response advances one configured observation
window, returning its frames in chronological order. The task then freezes on
the final frame, and the next input acts on that state. A wait sleeps in wall
time but does not advance the paused task clock. To hold a key or mouse button
while the task advances, send down in one request and up in a later request.
Additional screenshot requests advance additional
windows while the input stays held. Down, wait, up in a single batch does NOT
advance paused task time between down and up."""
    else:
        timing = """The task keeps running while you reason, deliver inputs, and wait.
Each response returns one instantaneous screenshot after the action batch
finishes. Held keys/buttons remain down across responses until you release them.
A batch containing down, wait, up can express a timed hold in live mode."""
    if timestamps_enabled(temporal_mode):
        timing += """
Time zero is the start of the environment. Responses include
timing.frame_captured_at_s for the screenshot and timing.current_time_s near
response serialization. Input responses include timing.action_executed_at_s
(the acknowledgement after the whole batch),
seconds_between_your_last_screenshot_and_that_action_landing, and
your_recent_observe_to_execute_latencies_s. Screenshot capture and action
injection can overlap across concurrent requests."""
    if scheduled_execution_enabled(temporal_mode):
        timing += """
Optionally send {"actions": [...], "execute_at_s": 10.0} to schedule the start
of a batch at an absolute time on this clock. A time in the past runs as soon
as the injection lane is free. This is a start time, not a hold duration.
The response reports previous_action_requested_execute_at_s and
action_execution_lateness_s. For a timed press and release, schedule separate
down and up requests. Omit execute_at_s for immediate execution."""
    else:
        timing += "\nexecute_at_s is not available in this mode."
    return f"""You operate a task computer through an authenticated HTTP gateway.
Your sandbox is separate from that computer. You may write Python, JavaScript,
shell programs, loops, timing logic, OCR or image-analysis code in your sandbox.
All observations of the task must come from gateway screenshots, and all task
interaction must be keyboard/mouse input through this gateway. Do not access
the task computer's files, services, DOM, source, developer tools, SSH or VNC.
Use only the task's visible interface. Programming in your sandbox is allowed.
You may choose actions in code without a model turn between them, and need
not inspect every intermediate frame.

HTTP contract:
- POST to GATEWAY_URL with Content-Type: application/json.
- Set X-Gateway-Token to GATEWAY_TOKEN.
- Body: {{"command": "<JSON-encoded action object or list>"}}
- The command can be an env.step action list, a single native action, or an
  object containing "actions": [...]. List order is preserved. The complete
  list is validated before any input is sent. Unsupported fields are errors.
- Add "observe": true to an action object, such as
  {{"actions": [{{"mouse": {{"left_click": [100, 200]}}}}], "observe": true}},
  to include the following screenshot in the same HTTP response.
- Responses include screenshots_b64 (chronological PNG or JPEG frames),
  observation, step, budget_remaining, done, error, and timing
  in timestamped modes. An invalid request returns an error without executing
  input, advancing an observation window, or spending the action budget.

Coordinates use the returned {width}x{height} screenshot at its original
resolution: x increases rightward and y downward from [0, 0]. Coordinates
are passed directly to the task display.

Native env.step input objects (use the fields needed for your action):
- Mouse point fields: {", ".join(MOUSE_POINTS)}. Each takes [x,y],
  e.g. {{"mouse":{{"move":[100,200]}}}}.
- Mouse drag fields: {", ".join(MOUSE_DRAGS)}. Each takes [[x1,y1],[x2,y2]].
- "mouse": {{"buttons": {{...}}}} accepts boolean states: {", ".join(MOUSE_BUTTONS)}.
- "mouse": {{"scroll": n}} sends n wheel notches, positive down, negative up.
  These are NOT pixels. To scroll at a point, move the pointer first.
- "keyboard" accepts {", ".join(KEYBOARD_FIELDS)}. text is a string. keys,
  keys_down and keys_up accept a key name or a list of key names, e.g. "w",
  "shift", "ctrl", "left", "space", "Return". keys taps a chord. keys_down
  presses without releasing. keys_up releases. A separate wait after a tap
  does not hold the key. There is no duration field on keyboard or mouse.
- {{"action":"wait", "time":0.2}} waits in seconds ("seconds" is also accepted).
- {{"action":"screenshot"}} or [] observes without spending the step budget.
  A screenshot entry inside a batch does not yield an intermediate frame.
- {{"action":"terminate", "status":"success"}} ends the task attempt.

Keep distinct inputs in separate list entries when order matters. The runtime
processes mouse before keyboard within a combined object, so use keys_down,
mouse input, keys_up entries for modifier-held gestures. To draw a curved path,
send mouse down, a sequence of mouse moves (and waits if needed), then mouse up.
Inputs can stay held across requests and screenshots. Do not replace a held
input with repeated taps or type repeated letters to simulate movement.

Temporal mode: {temporal_mode}
{timing}

Python HTTP client:
```python
import base64, json, os, urllib.request
from pathlib import Path

def computer(actions):
    if isinstance(actions, list):
        actions = {{"actions": actions, "observe": True}}
    else:
        actions = dict(actions, observe=True)
    request = urllib.request.Request(
        os.environ["GATEWAY_URL"],
        data=json.dumps({{"command": json.dumps(actions)}}).encode(),
        headers={{"Content-Type": "application/json",
                 "X-Gateway-Token": os.environ["GATEWAY_TOKEN"]}},
    )
    response = json.load(urllib.request.urlopen(request, timeout=180))
    if response.get("error"):
        raise RuntimeError(response["error"])
    paths = []
    for i, encoded in enumerate(response.get("screenshots_b64") or []):
        image = base64.b64decode(encoded)
        suffix = "jpg" if image.startswith(b"\\xff\\xd8\\xff") else "png"
        path = Path("obs") / ("%04d_%03d.%s" % (response["observation"], i, suffix))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)
        paths.append(str(path))
    return response, paths

response, paths = computer([])  # Begin by observing the task.
# A held-input example, when appropriate for the visible task:
# response, paths = computer([{{"keyboard": {{"keys_down": ["w"]}}}}])
# Optionally make further observations, then release:
# response, paths = computer([{{"keyboard": {{"keys_up": ["w"]}}}}])
```

You have at most {max_steps} steps. One non-observation request (including an
ordered action list) consumes one step, just as one env.step call does. A batch
returns its observation after the entire list. Release held inputs before
finishing. Stop when done is true. No further inputs will be accepted.

Task:
{task_description}
"""
