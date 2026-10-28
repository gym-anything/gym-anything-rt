from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
from types import SimpleNamespace

import pytest

from benchmarks.gym_anything_rt.shared_scripts.scheduled_input import InputQueue, InputCompiler, SandweaveInput
from tests.test_codex_actions import NATIVE_ACTIONS
from gym_anything_rt.agents.codex_cli import RealTimeCodexActionGateway
from gym_anything_rt.runner import RealTimeRunner


class Backend:
    def __init__(self):
        self.events = []
        self.closed = False

    def prepare(self, commands):
        if any(command[0] == "invalid" for command in commands):
            raise ValueError("invalid batch")
        return commands

    def inject(self, command):
        self.events.append(command)

    def fence(self):
        pass

    def close(self):
        self.closed = True


def test_non_sandweave_runner_keeps_existing_input_path(monkeypatch, tmp_path):
    from agents.shared.cli_harness import ActionGateway
    from gym_anything_rt import scheduled_input
    from tests.test_codex_actions import InputEnvironment
    env = InputEnvironment("live_timestamped_execution")
    env.inner = SimpleNamespace(compatibility=lambda: SimpleNamespace(runner="qemu"))
    env.prepare_input = lambda: pytest.fail("QEMU must not start the Sandweave input service")
    assert scheduled_input.prepare_input(env) == {"sandbox_scheduling": False}
    gateway = RealTimeCodexActionGateway(env, (1280, 720), 10, "token",
                                     temporal_mode="live_timestamped_execution", timing_path=tmp_path / "timing.jsonl")
    monkeypatch.setattr(ActionGateway, "_execute_action", lambda *a, **kw: (False, 123))
    monkeypatch.setattr(ActionGateway, "_capture_payload", lambda *a, **kw: {"original": True})
    assert gateway._execute_action([{"mouse": {"move": [1, 2]}}], target_wall_ms=123) == (False, 123)
    assert gateway._capture_payload(action_receipt={}) == {"original": True}


def test_non_sandweave_scheduled_step_keeps_existing_wait_and_actions():
    runner = object.__new__(RealTimeRunner)
    runner.inner = SimpleNamespace(compatibility=lambda: SimpleNamespace(runner="qemu"))
    calls = []
    runner.inject_action = calls.append
    actions = [{"mouse": {"move": [1, 2]}}, {"keyboard": {"keys": ["w"]}}]
    RealTimeRunner.inject_action(runner, {"action": "scheduled_input", "wall_time_ms": 123, "actions": actions})
    assert calls == [{"action": "wait_until", "wall_time_ms": 123}, *actions]


@pytest.mark.parametrize("action", NATIVE_ACTIONS)
def test_native_compiler_covers_input_contract(action, monkeypatch):
    import sys
    from gym_anything_rt.agents import codex_actions
    monkeypatch.setitem(sys.modules, "codex_actions", codex_actions)
    backend = object.__new__(InputCompiler)
    backend.size = (1920, 1080)
    backend.x = SimpleNamespace(XStringToKeysym=lambda key: 1)
    commands = backend.prepare([action])
    if action != {"mouse": {"scroll": 0}}:
        assert commands
    if "left_click_drag" in action.get("mouse", {}):
        assert commands[1] == ("button", (1, True))
        assert commands[-1] == ("button", (1, False))


@pytest.mark.parametrize("action", NATIVE_ACTIONS + [{"keyboard": {"text": "héllo + 世界\n"}}])
def test_sandweave_events_match_sdk(action, monkeypatch):
    import ctypes
    import importlib
    import sys
    from pathlib import Path
    from gym_anything_rt.agents import codex_actions
    sdk = pytest.importorskip("sandweave")
    directory = Path(sdk.__file__).parent / "sandbox/runtimes/gvisor/_engine"
    monkeypatch.syspath_prepend(str(directory))
    reference = importlib.import_module("fast_io")
    monkeypatch.setitem(sys.modules, "codex_actions", codex_actions)
    backend = object.__new__(SandweaveInput)
    backend.size = (1920, 1080)
    backend.x = ctypes.CDLL("libX11.so.6")
    backend.x.XStringToKeysym.argtypes = [ctypes.c_char_p]
    backend.x.XStringToKeysym.restype = ctypes.c_ulong
    expected_action = json.loads(json.dumps(action))
    mouse = expected_action.get("mouse", {})
    if "buttons" in mouse:
        mouse["buttons"] = [key for key, enabled in mouse["buttons"].items() if enabled]
    commands = backend.prepare([action])
    if action.get("action", action.get("type")) == "wait":
        assert commands == [("wait", action.get("time", action.get("seconds")))]
    elif action.get("action", action.get("type")) == "screenshot":
        assert commands == []
    else:
        assert [event for kind, events in commands for event in events] == reference.events_for_action(expected_action)


@pytest.fixture
def queue():
    receipts, condition = {}, threading.Condition()
    backend = Backend()

    def reply(receipt):
        with condition:
            receipts[receipt["id"]] = receipt
            condition.notify_all()

    service = InputQueue(backend, time.time_ns() / 1e6, reply)

    def wait(identity):
        with condition:
            assert condition.wait_for(lambda: identity in receipts, timeout=2)
            return receipts[identity]

    service.wait = wait
    yield service, backend
    service.close()


def test_future_release_does_not_block_immediate_press(queue):
    service, backend = queue
    target = service.seconds() + .12
    service.submit({"id": "release", "actions": [("up", "w")], "execute_at_s": target})
    service.submit({"id": "press", "actions": [("down", "w")]})
    press, release = service.wait("press"), service.wait("release")
    assert backend.events == [("down", "w"), ("up", "w")]
    assert press["action_executed_at_s"] < target
    assert release["action_executed_at_s"] >= target
    assert release["queued_at_s"] < target - .05
    assert release["action_completed_at_s"] >= release["action_executed_at_s"]


def test_same_deadline_is_fifo_and_late_request_runs_immediately(queue):
    service, backend = queue
    target = service.seconds() + .05
    for identity in ("a", "b", "c"):
        service.submit({"id": identity, "actions": [("event", identity)], "execute_at_s": target})
    service.wait("c")
    service.submit({"id": "late", "actions": [("event", "late")], "execute_at_s": 0})
    late = service.wait("late")
    assert [event[1] for event in backend.events] == ["a", "b", "c", "late"]
    assert late["action_executed_at_s"] >= late["queued_at_s"]


def test_batch_wait_yields_to_other_requests(queue):
    service, backend = queue
    service.submit({"id": "hold", "actions": [("down", "w"), ("wait", .12), ("up", "w")]})
    time.sleep(.02)
    service.submit({"id": "click", "actions": [("click", [1, 2])]})
    service.wait("hold")
    assert backend.events == [("down", "w"), ("click", [1, 2]), ("up", "w")]


def test_invalid_batch_never_partially_executes(queue):
    service, backend = queue
    with pytest.raises(ValueError):
        service.submit({"id": "bad", "actions": [("down", "w"), ("invalid", None)]})
    assert backend.events == []


@pytest.mark.parametrize("target", [float("nan"), float("inf"), -1, True, "5", 10000])
def test_invalid_deadline_rejected(queue, target):
    service, backend = queue
    with pytest.raises(ValueError):
        service.submit({"id": "bad", "actions": [("click", [1, 2])], "execute_at_s": target})
    assert backend.events == []


def test_retries_do_not_reinject_and_conflicting_id_is_rejected(queue):
    service, backend = queue
    request = {"id": "once", "actions": [("click", [1, 2])], "execute_at_s": .05}
    service.submit(request)
    service.submit(request)
    first = service.wait("once")
    service.submit(request)
    assert service.wait("once") == first
    assert backend.events == [("click", [1, 2])]
    with pytest.raises(ValueError, match="different input"):
        service.submit({**request, "execute_at_s": .2})


def test_close_discards_future_actions_and_closes_backend(queue):
    service, backend = queue
    service.submit({"id": "future", "actions": [("click", [1, 2])], "execute_at_s": 60})
    service.close()
    assert backend.events == []
    assert backend.closed
    with pytest.raises(RuntimeError, match="closed"):
        service.submit({"id": "new", "actions": [("click", [1, 2])]})


def test_gateway_returns_guest_timestamp_before_screenshot_finishes(tmp_path):
    from tests.test_codex_actions import InputEnvironment
    env = InputEnvironment("live_timestamped_execution")
    gateway = RealTimeCodexActionGateway(env, (1280, 720), 10, "token",
        temporal_mode="live_timestamped_execution", timing_path=tmp_path / "timing.jsonl")
    gateway.step_from_command("[]")
    captured, release = threading.Event(), threading.Event()
    original_capture = env.capture_observation

    def slow_capture():
        captured.set()
        assert release.wait(2)
        return original_capture()

    env.capture_observation = slow_capture
    try:
        with ThreadPoolExecutor(2) as pool:
            screenshot = pool.submit(gateway.step_from_command, "[]")
            assert captured.wait(1)
            response = gateway.step_from_command(json.dumps({"keyboard": {"keys_down": ["w"]}}))
            assert not screenshot.done()
            assert response["screenshot_b64"] is None
            assert response["timing"]["action_executed_at_s"] == response["input_receipt"]["action_executed_at_s"]
            release.set()
            screenshot.result(1)
    finally:
        release.set()


def test_pure_live_ack_does_not_expose_timestamps(tmp_path):
    from tests.test_codex_actions import InputEnvironment
    env = InputEnvironment("live")
    gateway = RealTimeCodexActionGateway(env, (1280, 720), 10, "token",
        temporal_mode="live", timing_path=tmp_path / "timing.jsonl")
    response = gateway.step_from_command('{"keyboard":{"keys":["w"]}}')
    assert response["timing"] is None
    assert "input_receipt" not in response
    assert response["acknowledgement"] == "x-server-processed"
    gateway.stop()
    assert env.input_closed


def test_termination_closes_input_without_injecting_empty_batch(tmp_path):
    from tests.test_codex_actions import InputEnvironment
    env = InputEnvironment("live_timestamped_execution")
    gateway = RealTimeCodexActionGateway(env, (1280, 720), 10, "token",
        temporal_mode="live_timestamped_execution", timing_path=tmp_path / "timing.jsonl")
    response = gateway.step_from_command('{"action":"terminate"}')
    assert response["done"] and env.input_closed
    assert env.calls == []


def test_post_task_closes_queue_before_export_hook():
    events = []
    runner = object.__new__(RealTimeRunner)
    runner._input_start_lock = threading.Lock()
    runner._input_service = SimpleNamespace(close=lambda: events.append("closed"))
    runner.inner = SimpleNamespace(run_hook=lambda *a, **k: events.append("export"))
    runner.run_hook("export_result", stage="post_task")
    assert events == ["closed", "export"]
    runner.spec = SimpleNamespace(runner_options={"time_mode": "live"})
    with pytest.raises(RuntimeError, match="closed"):
        runner.prepare_input()


def test_stop_collects_artifacts_even_if_input_shutdown_fails():
    events = []
    runner = object.__new__(RealTimeRunner)

    def failed_close():
        raise RuntimeError("input shutdown failed")

    runner.close_input = failed_close
    runner.collect_artifacts = lambda: events.append("collect")
    runner.inner = SimpleNamespace(stop=lambda: events.append("stop"))
    runner.stop()
    assert events == ["collect", "stop"]


def test_process_stream_transport_sleeps_when_idle_and_acknowledges_close():
    import socket
    from gym_anything_rt.scheduled_input import SandboxInput
    from benchmarks.gym_anything_rt.shared_scripts.scheduled_input import serve
    client, guest = socket.socketpair()
    client_stream, guest_stream = client.makefile("rb"), guest.makefile("rb")
    backend = Backend()

    def send(message):
        guest.sendall(json.dumps(message).encode() + b"\n")

    thread = threading.Thread(target=serve, args=(guest_stream, backend, time.time_ns() / 1e6, send))
    thread.start()
    assert json.loads(client_stream.readline())["version"] == 1
    reads = []

    def read():
        reads.append(True)
        return client_stream.readline()

    transport = object.__new__(SandboxInput)
    transport.lock = threading.Lock()
    transport.readable = threading.Event()
    transport.pending, transport.closed = {}, False
    transport.stream = SimpleNamespace(readline=read)
    transport.process = SimpleNamespace(stdin=SimpleNamespace(write=client.sendall, close=lambda: None))
    transport.reader = threading.Thread(target=transport._read, daemon=True)
    transport.reader.start()
    try:
        time.sleep(.02)
        assert not reads
        result = transport.execute([["down", "w"]])
        assert result["acknowledgement"] == "x-server-processed"
        time.sleep(.02)
        assert len(reads) == 1
        transport.close()
        assert backend.closed
        assert not transport.reader.is_alive()
        thread.join(1)
        assert not thread.is_alive()
    finally:
        client.close()
        guest.close()
        client_stream.close()
        guest_stream.close()
