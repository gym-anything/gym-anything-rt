"""Sandweave fast-I/O capture without per-frame processes or guest PNG files."""
from __future__ import annotations

import json
import socket
from pathlib import Path


# Read only the public clock record served verbatim by /time-control/status.
# Keep Python alive across observations; never infer browser time from a host clock.
_CLOCK_READER = '''
import json, sys
from pathlib import Path
clock_path = Path(sys.argv[1])
for line in sys.stdin:
    if line.strip() != "status":
        break
    try:
        status = json.loads(clock_path.read_text())
        print(json.dumps({"status": status}), flush=True)
    except Exception as error:
        print(json.dumps({"error": str(error)}), flush=True)
'''


def require_direct_local_connection(sandbox):
    connection = sandbox._connection
    if hasattr(connection, "_route"):
        route = connection._route(sandbox.id)
        endpoint = route["endpoint"]
        if endpoint.get("relay") or endpoint.get("hostname") != socket.gethostname():
            raise RuntimeError("fast I/O requires a direct same-machine worker connection")
        connection = connection._worker(route)
    if type(connection).__name__ == "ForwardedConnection" or getattr(connection, "host", None) != "127.0.0.1":
        raise RuntimeError("fast I/O requires a direct loopback connection; forwarding is prohibited")
    if connection.call("ping").get("hostname") != socket.gethostname():
        raise RuntimeError("fast I/O worker must run on the client's machine")


class NativeCapture:
    def __init__(self, sandbox, *, image_format="png", quality=85,
                 clock_path="/tmp/gym_anything_rt/time_status.json"):
        if image_format not in {"png", "jpeg"}:
            raise ValueError("image_format must be png or jpeg")
        require_direct_local_connection(sandbox)
        self.image_format, self.quality = image_format, quality
        if image_format == "jpeg" and not callable(getattr(sandbox.desktop, "capture_image", None)):
            raise RuntimeError("JPEG capture requires the local encoded-image Sandweave SDK and worker")
        if not callable(getattr(sandbox.desktop, "capture_png", None)):
            raise RuntimeError("native capture requires the local timestamped Sandweave SDK and worker")
        self.sandbox = sandbox
        self.clock = sandbox.exec(argv=["python3", "-u", "-c", _CLOCK_READER, clock_path])

    def capture(self, host_dir: Path) -> dict:
        if self.image_format == "jpeg":
            frame = self.sandbox.desktop.capture_image(format="jpeg", quality=self.quality, cursor=True)
            image_bytes = frame.data
            if frame.mime_type != "image/jpeg":
                raise RuntimeError("native capture returned the wrong image format")
        else:
            frame = self.sandbox.desktop.capture_png(cursor=True)
            image_bytes = frame.png
        metadata = frame.metadata
        start = metadata["capture_started_wall_ns"] / 1_000_000
        end = metadata["capture_completed_wall_ns"] / 1_000_000
        if not 0 < start <= end or metadata.get("cursor") is not True:
            raise RuntimeError("native capture returned invalid timestamps or omitted the cursor")
        self.clock.stdin.write("status\n")
        reply = json.loads(self.clock.stdout.readline())
        if "error" in reply or not isinstance(reply.get("status"), dict):
            raise RuntimeError(f"native capture clock read failed: {reply}")
        host_dir.mkdir(parents=True, exist_ok=True)
        path = host_dir / ("frame-000.jpg" if self.image_format == "jpeg" else "frame-000.png")
        path.write_bytes(image_bytes)
        return {
            "mode": "live", "capture_protocol": f"sandweave-native-{self.image_format}-v1",
            "image_mime_type": "image/" + self.image_format,
            "resolution": list(frame.size), "observation_window_ms": 0,
            "frames_per_observation": 1,
            "window_started_wall_ms": start, "window_completed_wall_ms": end,
            "scheduled_window_completed_wall_ms": start,
            "actual_window_wall_ms": end - start,
            "frames": [{"path": str(path), "offset_ms": end - start, "target_offset_ms": 0}],
            "time_status": reply["status"], "native_capture": metadata,
        }

    def close(self):
        try:
            self.clock.stdin.close()
        finally:
            self.clock.terminate()
