from __future__ import annotations

import ast
import inspect
import json
import textwrap
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

from gym_anything.runtime.runners.qemu_apptainer import QemuApptainerRunner

from gym_anything_rt.agents.codex_actions import (
    KEYBOARD_FIELDS,
    MOUSE_BUTTONS,
    MOUSE_DRAGS,
    MOUSE_POINTS,
    parse_command,
)
from gym_anything_rt.agents.codex_cli import RealTimeCodexActionGateway
from gym_anything_rt.agents.codex_prompt import build_codex_prompt
from gym_anything_rt.agents.temporal_modes import TEMPORAL_MODES


class InputEnvironment:
    def __init__(self, mode="live"):
        self.mode = mode
        self.calls = []
        self.captures = 0
        self.held = set()
        self.window_holds = []
        self.origin = time.time_ns() / 1_000_000 - 1000
        self.runner = self
        self._episode_started_wall_ms = self.origin

    def prepare_input(self):
        pass

    def close_input(self):
        self.input_closed = True

    def execute_input_step(self, env, actions, execute_at_s=None, *, request_id):
        queued = (time.time_ns() / 1e6 - self.origin) / 1000
        if execute_at_s is not None:
            time.sleep(max(0, execute_at_s - queued))
        started = (time.time_ns() / 1e6 - self.origin) / 1000
        self.step(actions, capture_observation=False, settle_after_actions=False)
        finished = (time.time_ns() / 1e6 - self.origin) / 1000
        return {"done": False, "receipt": {"id": request_id, "queued_at_s": queued,
                "requested_execute_at_s": execute_at_s, "action_executed_at_s": started,
                "action_completed_at_s": finished, "ack_sent_at_s": finished,
                "acknowledgement": "x-server-processed"}}

    def step(self, actions, *, capture_observation, settle_after_actions):
        assert not capture_observation and not settle_after_actions
        self.calls.append(actions)
        for action in actions:
            keyboard = action.get("keyboard", {})
            self.held.update(keyboard.get("keys_down", []))
            self.held.difference_update(keyboard.get("keys_up", []))
        return {}, 0, False, {}

    def capture_observation(self):
        self.captures += 1
        self.window_holds.append(set(self.held))
        return {"time": {"episode_started_wall_ms": self.origin}}


def gateway(tmp_path, *, mode="live", resolution=(1280, 720), steps=100):
    env = InputEnvironment(mode)
    result = RealTimeCodexActionGateway(
        env,
        resolution,
        steps,
        "test-token",
        temporal_mode=mode,
        timing_path=tmp_path / "timing.jsonl",
    )
    return result, env


NATIVE_ACTIONS = (
    [{"mouse": {field: [12, 34]}} for field in MOUSE_POINTS]
    + [{"mouse": {field: [[12, 34], [56, 78]]}} for field in MOUSE_DRAGS]
    + [{"mouse": {"buttons": {field: True}}} for field in MOUSE_BUTTONS]
    + [{"mouse": {"scroll": n}} for n in (-2, 0, 3)]
    + [
        {"keyboard": {field: ["shift", "w"]}}
        for field in KEYBOARD_FIELDS
        if field != "text"
    ]
    + [{"keyboard": {field: "w"}} for field in KEYBOARD_FIELDS]
    + [{"keyboard": {"text": "héllo <世界>"}}]
    + [{"action": "wait", "time": 0.02}, {"type": "wait", "seconds": 0.1}]
    + [{"mouse": {"move": [30, 40], "scroll": -1}, "keyboard": {"keys": ["ctrl", "a"]}}]
)


@pytest.mark.parametrize("mode", TEMPORAL_MODES)
@pytest.mark.parametrize("action", NATIVE_ACTIONS)
def test_every_native_input_reaches_env_step_unchanged(tmp_path, mode, action):
    proxy, env = gateway(tmp_path, mode=mode)
    response = proxy.step_from_command(json.dumps([action]))
    assert response["error"] is None
    assert env.calls == [[action]]
    assert response["step"] == 1
    assert env.captures == (1 if mode == "paused" else 0)
    if "timestamped" in mode:
        assert "action_executed_at_s" in response["timing"]


def test_curved_drag_and_modifier_scroll_preserve_order_and_values(tmp_path):
    proxy, env = gateway(tmp_path)
    actions = [
        {"keyboard": {"keys_down": ["shift"]}},
        {"mouse": {"move": [10, 20]}},
        {"mouse": {"buttons": {"left_down": True}}},
        {"mouse": {"move": [30, 5]}},
        {"action": "wait", "time": 0.25},
        {"mouse": {"move": [50, 20]}},
        {"mouse": {"buttons": {"left_up": True}}},
        {"mouse": {"scroll": -2}},
        {"keyboard": {"keys_up": ["shift"]}},
    ]
    response = proxy.step_from_command(json.dumps({"actions": actions}))
    assert env.calls == [actions]
    assert response["step"] == 1


def test_hold_survives_paused_observation_windows(tmp_path):
    proxy, env = gateway(tmp_path, mode="paused")
    proxy.step_from_command(json.dumps([{"keyboard": {"keys_down": ["w"]}}]))
    proxy.step_from_command("[]")
    proxy.step_from_command(json.dumps({"action": "screenshot"}))
    proxy.step_from_command(json.dumps([{"keyboard": {"keys_up": ["w"]}}]))
    assert env.window_holds == [{"w"}, {"w"}, {"w"}, set()]
    assert proxy.steps_taken == 2


INVALID = [
    "{",
    "null",
    "42",
    '"key"',
    "{}",
    "[null]",
    "[{}]",
    '{"actions": {"keyboard": {"keys": ["w"]}}}',
    '{"keyboard":{"keys":["w"],"duration":2}}',
    '{"action":"key","keys":["w"],"duration":2}',
    '{"action":"key","keys":["w"],"time":2}',
    '{"action":"key"}',
    '{"action":"hold_key","keys":["w"]}',
    '{"action":"key","keys":[]}',
    '{"keyboard":{"keys":[1]}}',
    '{"mouse":{"buttons":{"left_down":1}}}',
    '{"mouse":{"buttons":{"side_down":true}}}',
    '{"mouse":{"move":[1]}}',
    '{"mouse":{"move":[true,2]}}',
    '{"mouse":{"move":[1,NaN]}}',
    '{"mouse":{"move":[1,Infinity]}}',
    '{"mouse":{"left_click_drag":[[1,2],[3,4],[5,6]]}}',
    '{"mouse":{"move":[1,2],"duration":2}}',
    '{"mouse":{"scroll":0.5}}',
    '{"mouse":{"scroll_horizontal":2}}',
    '{"keyboard":{"text":42}}',
    '{"keyboard":{"keys":["w"]},"keyboard":{"keys":["s"]}}',
    '{"action":"wait","time":-1}',
    '{"action":"wait","time":true}',
    '{"action":"wait","time":0,"seconds":1}',
    '{"action":"wait","time":"2"}',
    '{"action":"screenshot","seconds":1}',
    '{"actions":[],"execute_at_s":null}',
    '{"actions":[],"execute_at_s":1}',
    '{"action":"terminate","execute_at_s":1}',
    '{"action":"time","command":"resume"}',
    '{"action":"wait_until","wall_time_ms":1}',
    '{"api_call":{"url":"http://task"}}',
    '{"shell":"ls"}',
    '{"keyboard":{"keys":["w"]},"shell":"ls"}',
    '[{"keyboard":{"keys_down":["w"]}},{"mouse":{"bad":1}}]',
]


@pytest.mark.parametrize("command", INVALID)
def test_invalid_request_neither_injects_nor_advances_task(tmp_path, command):
    proxy, env = gateway(tmp_path, mode="paused")
    response = proxy.step_from_command(command)
    assert response["error"]
    assert env.calls == []
    assert env.captures == 0
    assert proxy.steps_taken == 0
    assert response["budget_remaining"] == 100


@pytest.mark.parametrize(
    "command,expected",
    [
        (
            {"action": "key", "keys": ["ctrl", "s"]},
            [{"keyboard": {"keys": ["ctrl", "s"]}}],
        ),
        (
            {"action": "drag", "coordinate": [1, 2], "coordinate2": [3, 4]},
            [{"mouse": {"left_click_drag": [[1, 2], [3, 4]]}}],
        ),
        (
            {"action": "left_click", "coordinate": [1, 2]},
            [{"mouse": {"left_click": [1, 2]}}],
        ),
        (
            {"action": "type", "text": "hello", "clear": True, "enter": True},
            [
                {"keyboard": {"keys": ["ctrl", "a"]}},
                {"keyboard": {"text": "hello"}},
                {"keyboard": {"keys": ["Return"]}},
            ],
        ),
        (
            {"action": "scroll", "coordinate": [1, 2], "pixels": -2},
            [{"mouse": {"move": [1, 2]}}, {"mouse": {"scroll": -2}}],
        ),
    ],
)
def test_existing_clients_keep_their_action_mappings(command, expected):
    assert parse_command(json.dumps(command), (1, 1))[0] == expected


def test_native_batch_scheduling_and_mode_gate(tmp_path):
    proxy, env = gateway(tmp_path, mode="live_timestamped_execution")
    command = json.dumps(
        {"actions": [{"keyboard": {"keys_down": ["w"]}}], "execute_at_s": 0}
    )
    assert proxy.step_from_command(command)["error"]
    proxy.step_from_command("[]")
    response = proxy.step_from_command(command)
    assert not response["error"]
    assert response["timing"]["previous_action_requested_execute_at_s"] == 0
    assert env.calls == [[{"keyboard": {"keys_down": ["w"]}}]]
    for mode in TEMPORAL_MODES[:-1]:
        other, unused = gateway(tmp_path, mode=mode)
        assert other.step_from_command(command)["error"]
        assert not unused.calls


def test_scheduled_release_does_not_block_immediate_press(tmp_path):
    proxy, env = gateway(tmp_path, mode="live_timestamped_execution")
    first = proxy.step_from_command("[]")
    target = first["timing"]["current_time_s"] + 0.15
    with ThreadPoolExecutor(max_workers=2) as pool:
        release = pool.submit(
            proxy.step_from_command,
            json.dumps(
                {
                    "actions": [{"keyboard": {"keys_up": ["w"]}}],
                    "execute_at_s": target,
                }
            ),
        )
        press = proxy.step_from_command(json.dumps({"keyboard": {"keys_down": ["w"]}}))
        assert not press["error"]
        assert not release.result(timeout=2)["error"]
    assert env.calls == [
        [{"keyboard": {"keys_down": ["w"]}}],
        [{"keyboard": {"keys_up": ["w"]}}],
    ]


def test_finished_gateway_rejects_further_input(tmp_path):
    proxy, env = gateway(tmp_path)
    assert proxy.step_from_command('{"action":"terminate"}')["done"]
    count = len(env.calls)
    assert proxy.step_from_command('{"keyboard":{"keys_down":["w"]}}')["error"]
    assert len(env.calls) == count


def test_real_http_transport_accepts_native_actions_and_checks_auth(tmp_path):
    proxy, env = gateway(tmp_path)
    port = proxy.start(host="127.0.0.1")
    actions = [{"keyboard": {"keys_down": ["w"]}}]

    def post(token):
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}",
            data=json.dumps({"command": json.dumps(actions)}).encode(),
            headers={"X-Gateway-Token": token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.load(response)

    try:
        with pytest.raises(urllib.error.HTTPError) as failure:
            post("wrong")
        assert failure.value.code == 403
        assert not env.calls
        assert post("test-token")["error"] is None
        assert env.calls == [actions]
    finally:
        proxy.stop()


def test_pinned_runtime_pointer_fields_are_all_exposed():
    # Tripwire when the pinned runner gains a mouse or keyboard field.
    # Extract the fields it actually dispatches, not every string in its class.
    pointer = ast.parse(
        textwrap.dedent(inspect.getsource(QemuApptainerRunner._pointer_steps))
    )
    fields = {"buttons", "scroll"}
    for node in ast.walk(pointer):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant):
            if any(
                isinstance(rhs, ast.Name) and rhs.id == "mouse"
                for rhs in node.comparators
            ):
                fields.add(node.left.value)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            if (
                isinstance(node.target.elts[0], ast.Name)
                and node.target.elts[0].id == "key"
            ):
                fields.update(ast.literal_eval(item.elts[0]) for item in node.iter.elts)
    assert fields == set(MOUSE_POINTS) | set(MOUSE_DRAGS) | {"buttons", "scroll"}
    keyboard = ast.parse(
        textwrap.dedent(inspect.getsource(QemuApptainerRunner._build_keyboard_script))
    )
    fields = {
        node.left.value
        for node in ast.walk(keyboard)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Constant)
        and any(
            isinstance(rhs, ast.Name) and rhs.id == "keyboard"
            for rhs in node.comparators
        )
    }
    assert fields == set(KEYBOARD_FIELDS)


@pytest.mark.parametrize("mode", TEMPORAL_MODES)
def test_prompt_documents_native_contract_and_existing_timing(mode):
    prompt = build_codex_prompt("Solve the visible task.", (1280, 720), 100, mode)
    for field in (*MOUSE_POINTS, *MOUSE_DRAGS, *MOUSE_BUTTONS, *KEYBOARD_FIELDS):
        assert field in prompt
    assert "wheel notches" in prompt
    assert "Python" in prompt and "Programming in your sandbox is allowed" in prompt
    assert "Solve the visible task." in prompt
    if mode == "paused":
        assert "does not advance the paused task clock" in prompt
        assert "final frame" in prompt
    if "timestamped" in mode:
        assert "your_recent_observe_to_execute_latencies_s" in prompt
    if mode.endswith("execution"):
        assert '"execute_at_s": 10.0' in prompt
