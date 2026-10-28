"""Sandbox-side keyboard/mouse queue. No task state or screenshot access.

The wrapper starts this once and owns its authenticated, persistent connection.
Only the queue thread touches X11. Deadlines use the sandbox's monotonic clock.
"""
from __future__ import annotations

import argparse
import ctypes as C
import heapq
import io
import json
import math
import os
from pathlib import Path
import select
import sys
import struct
import subprocess
import tempfile
import threading
import time

MAX_MESSAGE = 1024 * 1024
ALIASES = {
    "ctrl": "Control_L", "control": "Control_L", "shift": "Shift_L",
    "alt": "Alt_L", "super": "Super_L", "meta": "Super_L", "win": "Super_L",
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
    "space": "space", "tab": "Tab", "backspace": "BackSpace", "delete": "Delete",
    "left": "Left", "right": "Right", "up": "Up", "down": "Down",
    "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next",
    "insert": "Insert", "capslock": "Caps_Lock", "print": "Print", "pause": "Pause",
}


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


class InputCompiler:
    """Validate the benchmark action contract before admitting a batch."""

    @staticmethod
    def _bind(lib, name, args, result=C.c_int):
        function = getattr(lib, name)
        function.argtypes, function.restype = args, result

    def prepare(self, actions):
        # The same validator is uploaded beside this service, not reimplemented.
        from codex_actions import native_action
        if not isinstance(actions, list) or not actions:
            raise ValueError("actions must be a nonempty list")
        commands = []

        def move(point):
            if any(not 0 <= p < size for p, size in zip(point, self.size)):
                raise ValueError("pointer outside desktop")
            commands.append(("move", point))

        def key_name(key):
            name = ALIASES.get(key.lower(), key)
            if key.lower().startswith("f") and key[1:].isdigit():
                name = key.upper()
            if len(key) == 1:
                # Uxxxx also avoids interpreting literal '+' as a chord separator.
                name = f"U{ord(key):04X}"
            if "\x00" in name or not self.x.XStringToKeysym(name.encode()):
                raise ValueError(f"unknown key: {key}")
            return name

        for raw in actions:
            action = native_action(raw, (1, 1))
            kind = action.get("action", action.get("type"))
            if kind == "wait":
                commands.append(("wait", action.get("time", action.get("seconds", 1.0))))
                continue
            if kind == "screenshot":
                continue
            for field, value in action.get("mouse", {}).items():
                if field == "move":
                    move(value)
                elif field.endswith("_click") or field in {"double_click", "triple_click"}:
                    move(value)
                    button = {"right_click": 3, "middle_click": 2}.get(field, 1)
                    for _ in range({"double_click": 2, "triple_click": 3}.get(field, 1)):
                        commands.extend([("button", (button, True)), ("button", (button, False))])
                elif field.endswith("_drag"):
                    start, end = value
                    move(start)
                    button = 3 if field.startswith("right") else 1
                    commands.append(("button", (button, True)))
                    for index in range(1, 9):
                        move([round(a + (b - a) * index / 8) for a, b in zip(start, end)])
                    commands.append(("button", (button, False)))
                elif field == "buttons":
                    for name, enabled in value.items():
                        if enabled:
                            button, direction = name.rsplit("_", 1)
                            commands.append(("button", ({"left": 1, "middle": 2, "right": 3}[button], direction == "down")))
                elif field == "scroll":
                    if abs(value) > 4096:
                        raise ValueError("scroll batch exceeds 4096 wheel notches")
                    for _ in range(abs(int(value))):
                        commands.extend([("button", (5 if value > 0 else 4, True)),
                                         ("button", (5 if value > 0 else 4, False))])
            for field, value in action.get("keyboard", {}).items():
                if field == "text":
                    if "\x00" in value:
                        raise ValueError("keyboard text cannot contain NUL")
                    commands.append(("text", value))
                else:
                    keys = [key_name(k) for k in ([value] if isinstance(value, str) else value)]
                    commands.append((field, keys))
            if len(commands) > 32768:
                raise ValueError("input batch is too large")
        return commands

class SandweaveInput(InputCompiler):
    """Schedule against the installed Sandweave XTEST helper, protocol v1.

    A separate persistent helper avoids the SDK's screenshot request lane.
    Its native Unicode allocation/drain logic remains the input authority.
    """

    def __init__(self):
        self.x = C.CDLL("libX11.so.6")
        for name, args, result in [
            ("XOpenDisplay", [C.c_char_p], C.c_void_p),
            ("XCloseDisplay", [C.c_void_p], C.c_int),
            ("XDisplayWidth", [C.c_void_p, C.c_int], C.c_int),
            ("XDisplayHeight", [C.c_void_p, C.c_int], C.c_int),
            ("XStringToKeysym", [C.c_char_p], C.c_ulong),
        ]:
            self._bind(self.x, name, args, result)
        display = self.x.XOpenDisplay(None)
        if not display:
            raise RuntimeError("cannot open sandbox X11 display")
        self.size = (self.x.XDisplayWidth(display, 0), self.x.XDisplayHeight(display, 0))
        self.x.XCloseDisplay(display)
        binaries = set()
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    path = Path(os.readlink(entry / "exe"))
                    if path.name == "bridge" and path.parent.parent == Path("/opt/engine-fast-io"):
                        binaries.add(path)
                except OSError:
                    pass
        if len(binaries) != 1:
            raise RuntimeError("cannot identify the running Sandweave input helper")
        binary = binaries.pop()
        self.frame = tempfile.TemporaryFile()
        os.ftruncate(self.frame.fileno(), 64 + 64 * 1024 * 1024)
        descriptor = self.frame.fileno()
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            bufsize=0, env={**os.environ, "LD_LIBRARY_PATH": str(binary.parent)},
            pass_fds=tuple({descriptor, 3}), preexec_fn=lambda: os.dup2(descriptor, 3))
        self.stream = io.BufferedReader(self.process.stdout)
        hello = json.loads(self.stream.readline(MAX_MESSAGE + 1))
        if not hello.get("ready") or hello.get("version") != 1:
            self.process.terminate()
            self.process.wait()
            self.frame.close()
            raise RuntimeError("unsupported Sandweave input helper protocol")
        self.pending, self.held_keys, self.held_buttons = [], set(), set()

    def prepare(self, actions):
        commands, events = [], []
        shifted = dict(zip('~!@#$%^&*()_+{}|:\"<>?', '`1234567890-=[]\\;\',./'))

        def symbol(key):
            if key.startswith("U") and len(key) >= 5:
                value = int(key[1:], 16)
                return value if value < 256 else 0x01000000 | value
            value = self.x.XStringToKeysym(key.encode())
            if not value:
                raise ValueError(f"unknown key: {key}")
            return value

        def key(name, down):
            events.append((4 if down else 5, symbol(name), 0, 0))

        def flush():
            if len(events) > 8192:
                raise ValueError("input batch exceeds 8192 native events")
            if events:
                commands.append(("events", list(events)))
                events.clear()

        for kind, value in super().prepare(actions):
            if kind == "wait":
                flush()
                commands.append((kind, value))
            elif kind == "move":
                events.append((1, 0, *value))
            elif kind == "button":
                events.append((2 if value[1] else 3, value[0], 0, 0))
            elif kind == "text":
                for char in value:
                    name = {"\n": "Return", "\r": "Return", "\t": "Tab", "\b": "BackSpace"}.get(char, char)
                    shift = name in shifted or (len(name) == 1 and 'A' <= name <= 'Z')
                    name = shifted.get(name, name.lower() if shift else name)
                    if len(name) == 1:
                        name = f"U{ord(name):04X}"
                    if shift:
                        key("Shift_L", True)
                    key(name, True)
                    key(name, False)
                    if shift:
                        key("Shift_L", False)
            else:
                if kind != "keys_up":
                    for name in value:
                        key(name, True)
                if kind != "keys_down":
                    for name in reversed(value):
                        key(name, False)
        flush()
        return commands

    def inject(self, command):
        self.pending.extend(command[1])

    def _request(self, operation, events):
        payload = struct.pack("<II", operation, len(events))
        payload += b"".join(struct.pack("<IIii", *event) for event in events)
        view = memoryview(payload)
        while view:
            written = self.process.stdin.write(view)
            if not written:
                raise RuntimeError("native input helper stopped accepting input")
            view = view[written:]
        if not select.select([self.stream], [], [], 10)[0]:
            raise TimeoutError("native input acknowledgement timed out; delivery outcome unknown")
        reply = json.loads(self.stream.readline(MAX_MESSAGE + 1))
        if reply.get("error"):
            raise RuntimeError(reply["error"])
        return reply

    def fence(self):
        if self.pending:
            events, self.pending = self.pending, []
            self._request(2, events)
            for kind, value, _, _ in events:
                if kind in (4, 5):
                    (self.held_keys.add if kind == 4 else self.held_keys.discard)(value)
                elif kind in (2, 3):
                    (self.held_buttons.add if kind == 2 else self.held_buttons.discard)(value)

    def close(self):
        try:
            self.pending = [(5, key, 0, 0) for key in self.held_keys]
            self.pending += [(3, button, 0, 0) for button in self.held_buttons]
            self.fence()
            self._request(4, [])
            self.process.stdin.write(struct.pack("<II", 0, 0))
            self.process.stdin.close()
            self.process.wait(timeout=5)
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=5)
            self.stream.close()
            self.frame.close()


class InputQueue:
    def __init__(self, backend, origin_wall_ms, reply):
        self.backend, self.reply = backend, reply
        self.origin_ns = time.monotonic_ns() - round((time.time_ns() / 1e6 - origin_wall_ms) * 1e6)
        self.condition = threading.Condition()
        self.jobs, self.seen = [], {}
        self.sequence, self.closed = 0, False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def seconds(self):
        return (time.monotonic_ns() - self.origin_ns) / 1e9

    def submit(self, message):
        identity = message["id"]
        if not isinstance(identity, str) or not 1 <= len(identity) <= 100:
            raise ValueError("invalid request id")
        signature = json.dumps(message, sort_keys=True)
        with self.condition:
            if identity in self.seen:
                previous = self.seen[identity]
                if previous["signature"] != signature:
                    raise ValueError("request id reused with different input")
                if "receipt" in previous:
                    self.reply(previous["receipt"])
                return
            if self.closed:
                raise RuntimeError("input queue is closed")
            if len(self.seen) >= 10000:
                raise ValueError("episode input limit reached")
        target = message.get("execute_at_s")
        if target is not None and (finite(target, "execute_at_s") < 0 or target > self.seconds() + 3600):
            raise ValueError("execute_at_s must be nonnegative and at most one hour ahead")
        commands = self.backend.prepare(message["actions"])
        queued = self.seconds()
        waits = sum(command[1] for command in commands if command[0] == "wait")
        if max(0, (target or queued) - queued) + waits > 3600:
            raise ValueError("input batch exceeds one hour")
        job = {"id": identity, "signature": signature, "commands": commands, "index": 0,
               "queued_at_s": queued, "requested_execute_at_s": target, "started_at_s": None}
        with self.condition:
            self.seen[identity] = job
            heapq.heappush(self.jobs, (self.origin_ns + round((queued if target is None else target) * 1e9), self.sequence, job))
            self.sequence += 1
            self.condition.notify()

    def run(self):
        try:
            while True:
                with self.condition:
                    while not self.closed and not self.jobs:
                        self.condition.wait()
                    if self.closed:
                        return
                    delay = (self.jobs[0][0] - time.monotonic_ns()) / 1e9
                    if delay > 0:
                        self.condition.wait(delay)
                        continue
                    _, _, job = heapq.heappop(self.jobs)
                if job["started_at_s"] is None:
                    job["started_at_s"] = self.seconds()
                error, waiting = None, False
                try:
                    while job["index"] < len(job["commands"]):
                        if self.closed:
                            return
                        command = job["commands"][job["index"]]
                        job["index"] += 1
                        if command[0] == "wait":
                            self.backend.fence()
                            with self.condition:
                                heapq.heappush(self.jobs, (time.monotonic_ns() + round(command[1] * 1e9), self.sequence, job))
                                self.sequence += 1
                            waiting = True
                            break
                        self.backend.inject(command)
                    self.backend.fence()
                except Exception as exc:
                    error = str(exc)
                if waiting and error is None:
                    continue
                completed = self.seconds()
                receipt = {"id": job["id"], "queued_at_s": job["queued_at_s"],
                           "requested_execute_at_s": job["requested_execute_at_s"],
                           "action_executed_at_s": job["started_at_s"],
                           "action_completed_at_s": completed, "ack_sent_at_s": self.seconds(),
                           "acknowledgement": "x-server-processed", "error": error}
                with self.condition:
                    job["receipt"] = receipt
                self.reply(receipt)
        finally:
            self.backend.close()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("input executor did not stop")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin-wall-ms", required=True, type=float)
    args = parser.parse_args()
    backend = SandweaveInput()
    send_lock = threading.Lock()

    def send(message):
        with send_lock:
            sys.stdout.write(json.dumps(message, allow_nan=False) + "\n")
            sys.stdout.flush()

    serve(sys.stdin.buffer, backend, args.origin_wall_ms, send)


def serve(stream, backend, origin_wall_ms, send):
    send({"version": 1, "pid": os.getpid()})
    queue = InputQueue(backend, origin_wall_ms, send)
    try:
        while line := stream.readline(MAX_MESSAGE + 1):
            if len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                raise ValueError("invalid input message")
            message = json.loads(line)
            try:
                if message.get("operation") == "close":
                    queue.close()
                    send({"id": message["id"], "closed": True})
                    break
                queue.submit(message)
            except Exception as error:
                send({"id": message.get("id"), "error": str(error)})
    finally:
        queue.close()


if __name__ == "__main__":
    main()
