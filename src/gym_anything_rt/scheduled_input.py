"""Host side of the wrapper-owned sandbox input connection."""
from __future__ import annotations

from concurrent.futures import Future
import json
from pathlib import Path
import shlex
import threading
import time
import uuid


class SandboxInput:
    def __init__(self, runner, origin_wall_ms):
        if runner.compatibility().runner != "sandweave":
            raise ValueError("sandbox input service requires Sandweave")
        self.lock = threading.Lock()
        self.readable = threading.Event()
        self.pending = {}
        self.closed = False
        from gym_anything.registry import resolve_benchmark_root

        shared_scripts = resolve_benchmark_root("gym_anything_rt") / "shared_scripts"
        directory = f"/tmp/gym-anything-rt-input-{uuid.uuid4().hex}"
        # Upload from the installed benchmark, not an old filesystem checkpoint.
        runner.exec(f"mkdir -p {shlex.quote(directory)}", use_pty=False)
        runner.copy_to(str(shared_scripts / "scheduled_input.py"), directory + "/scheduled_input.py")
        runner.copy_to(str(Path(__file__).parent / "agents/codex_actions.py"), directory + "/codex_actions.py")
        # Public SDK process streams work even with guest network=offline.
        command = ["env", "DISPLAY=:1", "XAUTHORITY=/home/ga/.Xauthority", "python3", "-u",
                   directory + "/scheduled_input.py", "--origin-wall-ms", str(origin_wall_ms)]
        self.process = runner.exec_async(" ".join(map(shlex.quote, command)))
        self.stream = self.process.stdout
        hello = self.stream.readline()
        if not hello or json.loads(hello).get("version") != 1:
            raise RuntimeError(f"sandbox input failed to start: {self.process.result().stderr}")
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                # SDK readline polls. Do not generate RPC traffic while
                # no request is awaiting a receipt.
                with self.lock:
                    if not self.pending:
                        self.readable.clear()
                self.readable.wait()
                line = self.stream.readline()
                if not line:
                    break
                if isinstance(line, str):
                    line = line.encode()
                if len(line) > 1024 * 1024 or not line.endswith(b"\n"):
                    raise RuntimeError("invalid sandbox input receipt")
                receipt = json.loads(line)
                receipt["worker_ack_received_wall_ms"] = time.time_ns() / 1e6
                with self.lock:
                    future = self.pending.pop(receipt["id"], None)
                if future is not None:
                    if receipt.get("error"):
                        future.set_exception(RuntimeError(receipt["error"]))
                    else:
                        future.set_result(receipt)
                if receipt.get("closed"):
                    break
        except Exception as error:
            failure = error
        else:
            failure = RuntimeError("sandbox input disconnected; pending delivery outcomes are unknown")
        finally:
            with self.lock:
                self.closed = True
                pending, self.pending = self.pending, {}
            for future in pending.values():
                future.set_exception(failure)

    def execute(self, actions, execute_at_s=None, *, request_id=None):
        identity = request_id or uuid.uuid4().hex
        message = {"id": identity, "actions": actions, "execute_at_s": execute_at_s}
        return self._request(message, timeout=3660)

    def _request(self, message, *, timeout):
        identity = message["id"]
        encoded = json.dumps(message, allow_nan=False).encode() + b"\n"
        if len(encoded) > 1024 * 1024:
            raise ValueError("input message is too large")
        future = Future()
        with self.lock:
            if self.closed:
                raise RuntimeError("sandbox input connection is closed")
            if identity in self.pending:
                raise ValueError("request is already pending")
            self.pending[identity] = future
            self.readable.set()
            try:
                self.process.stdin.write(encoded)
            except Exception:
                self.pending.pop(identity)
                raise RuntimeError("input transport failed; delivery outcome unknown, not replayed") from None
        # The guest enforces the one-hour scheduling horizon. A dropped channel
        # completes all pending futures with errors; no request is replayed.
        return future.result(timeout=timeout)

    def close(self):
        try:
            if not self.closed:
                self._request({"id": uuid.uuid4().hex, "operation": "close"}, timeout=6)
        finally:
            self.process.stdin.close()
            self.reader.join(timeout=5)


def execute_input(env, actions, execute_at_s=None, *, request_id=None):
    """Use Gym's remote transport, or the same operation on a local wrapper."""
    from gym_anything.remote import RemoteGymEnv
    identity = request_id or uuid.uuid4().hex
    if isinstance(env, RemoteGymEnv):
        raise NotImplementedError("Scheduled input runs only on a local RealTimeRunner, not on a remote worker")
    return env.runner.execute_input_step(env, actions, execute_at_s, request_id=identity)


def prepare_input(env):
    from gym_anything.remote import RemoteGymEnv
    if isinstance(env, RemoteGymEnv):
        # Remote episodes use the standard Gym-Anything step path.
        return {"sandbox_scheduling": False}
    if hasattr(env.runner, "inner") and env.runner.inner.compatibility().runner != "sandweave":
        return {"sandbox_scheduling": False}
    env.runner.prepare_input()
    return {"sandbox_scheduling": True, "episode_started_wall_ms": env.runner._episode_started_wall_ms}


def close_input(env):
    from gym_anything.remote import RemoteGymEnv
    if isinstance(env, RemoteGymEnv):
        raise NotImplementedError("Scheduled input runs only on a local RealTimeRunner, not on a remote worker")
    else:
        env.runner.close_input()
