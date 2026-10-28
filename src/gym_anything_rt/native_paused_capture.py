"""Native screenshots during the existing paused observation-window protocol."""
from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import time

from .native_capture import NativeCapture


_CONTROL = '''
import json, sys
sys.path.insert(0, "/workspace/shared_scripts")
from time_control import send_command, wait_for_status
for line in sys.stdin:
    try:
        request = json.loads(line)
        result = send_command(**request)
        if request["command"] == "pause":
            sequence = int(result["sequence"])
            result = wait_for_status(lambda s: int(s.get("sequence") or -1) >= sequence
                                    and s.get("state") == "paused", timeout=30)
        print(json.dumps({"response": result}), flush=True)
    except Exception as error:
        print(json.dumps({"error": str(error)}), flush=True)
'''


class NativePausedCapture(NativeCapture):
    def control(self, **request):
        if getattr(self, "controller", None) is None:
            self.controller = self.sandbox.exec(argv=["python3", "-u", "-c", _CONTROL], user="root")
        try:
            self.controller.stdin.write(json.dumps(request) + "\n")
            line = self.controller.stdout.readline()
        except BrokenPipeError as error:
            raise RuntimeError(f"native paused controller exited: {self.controller.stderr.read()}") from error
        if not line:
            raise RuntimeError(f"native paused controller exited: {self.controller.stderr.read()}")
        reply = json.loads(line)
        if "error" in reply or not isinstance(reply.get("response"), dict):
            raise RuntimeError(f"native paused clock command failed: {reply}")
        return reply["response"]

    def capture_window(self, host_dir: Path, *, duration_ms: int, count: int,
                       hold_paused: bool = False) -> dict:
        if duration_ms < 0 or count < 1:
            raise ValueError("Invalid paused observation window")
        # Use the same run_for command, delayed start, completion criterion,
        # frame targets, and nearest-frame selection as the original recorder.
        # Only the source of the encoded screenshots changes.
        host_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="native-window-", dir=host_dir) as temporary:
            directory = Path(temporary)
            before = self.capture(directory / "before")["time_status"]
            running = duration_ms > 0 and not hold_paused
            scale = float(before.get("time_scale", 1.0))
            wall_duration_ms = duration_ms / scale if running else duration_ms
            if running:
                accepted = self.control(command="run_for", milliseconds=duration_ms,
                                        start_delay_ms=150)
            else:
                accepted = self.control(command="pause")
            sequence = int(accepted["sequence"])
            prior_done = float(before.get("window_completed_wall_ms") or 0)
            period = 1 / max(30, math.ceil(count * 1000 / max(1, duration_ms)) * 2)
            frames = []
            start = end = None
            completed = None
            deadline = time.monotonic() + 30 + wall_duration_ms / 1000
            try:
                while True:
                    tick = time.monotonic()
                    if tick >= deadline:
                        raise TimeoutError("Native paused observation window did not complete")
                    frame = self.capture(directory / str(len(frames)))
                    frames.append(frame)
                    status = frame["time_status"]
                    stamp = frame["window_completed_wall_ms"]
                    if running:
                        if (int(status.get("sequence") or -1) >= sequence
                                and status.get("phase") == "completed"
                                and float(status.get("window_completed_wall_ms") or 0) > prior_done):
                            completed = status
                            start = float(status["window_started_wall_ms"])
                            end = float(status["window_completed_wall_ms"])
                    else:
                        if start is None:
                            start = frame["window_started_wall_ms"]
                        if status.get("state") != "paused" or abs(
                            float(status.get("task_time_ms") or 0)
                            - float(accepted.get("task_time_ms") or 0)
                        ) > 5:
                            raise RuntimeError("Native paused hold advanced the task clock")
                        if completed is None and stamp >= start + duration_ms:
                            completed, end = status, stamp
                    # Retain the historical post-window capture allowance so a
                    # final rendered frame is available after the clock freezes.
                    if completed is not None and stamp >= end + max(80, 2000 * period):
                        break
                    time.sleep(max(0, period - (time.monotonic() - tick)))
            except Exception:
                # Freeze an interrupted window before returning a failed capture.
                self.control(command="pause")
                raise
            if frames[-1]["time_status"].get("state") != "paused":
                raise RuntimeError("Native observation returned before the task paused")
            targets = ([start + wall_duration_ms] if count == 1 else
                       [start + wall_duration_ms * i / (count - 1) for i in range(count)])
            selected = [min(frames, key=lambda f: abs(f["window_completed_wall_ms"] - t))
                        for t in targets]
            result_frames = []
            for index, (frame, target) in enumerate(zip(selected, targets, strict=True)):
                original = Path(frame["frames"][0]["path"])
                destination = host_dir / f"frame-{index:03d}{original.suffix}"
                destination.write_bytes(original.read_bytes())
                result_frames.append(dict(path=str(destination),
                    offset_ms=frame["window_completed_wall_ms"] - start,
                    target_offset_ms=target - start, native_capture=frame["native_capture"]))
            final = frames[-1]
            return dict(final, mode="paused", frames=result_frames,
                        observation_window_ms=duration_ms, frames_per_observation=count,
                        window_started_wall_ms=start, window_completed_wall_ms=end,
                        scheduled_window_completed_wall_ms=start + wall_duration_ms,
                        actual_window_wall_ms=end - start,
                        paused_capture_protocol="native-paused-window-v1")

    def close(self):
        try:
            controller = getattr(self, "controller", None)
            if controller is not None:
                controller.stdin.close()
                controller.terminate()
        finally:
            super().close()
