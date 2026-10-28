"""Full-resolution encoded-image delivery for the benchmark HTTP interface."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from gym_anything_rt.agents.codex_actions import _unique_object


class FastImageGatewayMixin:
    """Keep native image bytes and native action coordinates throughout HTTP."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.display_w, self.display_h = self.width, self.height
        self.ratio_x = self.ratio_y = 1.0

    def _display_screenshots_b64(self, obs):
        if not obs.get("frames") and not obs.get("screen"):
            return []
        frames = obs.get("frames") or [obs.get("screen", {})]
        if self.temporal_mode != "paused":
            frames = frames[-1:]
        encoded = []
        for frame in frames:
            path = frame.get("path") if isinstance(frame, dict) else frame
            if not path:
                raise RuntimeError("fast HTTP delivery requires an encoded native frame")
            data = Path(path).read_bytes()
            if not data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
                raise RuntimeError("fast HTTP delivery requires PNG or JPEG bytes")
            encoded.append(base64.b64encode(data).decode("ascii"))
        return encoded

    def _screenshot_payload(self, obs, **kwargs):
        payload = super()._screenshot_payload(obs, **kwargs)
        # The list contains the complete image. Avoid serializing its last
        # entry a second time under the legacy single-frame alias.
        payload.pop("screenshot_b64", None)
        return payload

    def step_from_command(self, command):
        request = json.loads(command, object_pairs_hook=_unique_object)
        observe = request.pop("observe", False) if isinstance(request, dict) else False
        if type(observe) is not bool:
            raise ValueError("observe must be a boolean")
        response = super().step_from_command(json.dumps(request))
        # Existing live action requests return an acknowledgement. An explicit
        # observe=True includes the following frame in the same HTTP response.
        if observe and not response.get("error") and not response.get("screenshots_b64"):
            capture = self._capture_payload()
            timing = {**(response.get("timing") or {}), **(capture.get("timing") or {})}
            response.update(capture)
            if timing:
                response["timing"] = timing
        return response

    @staticmethod
    def action_command(command):
        request = json.loads(command, object_pairs_hook=_unique_object)
        if isinstance(request, dict) and "observe" in request:
            if type(request.pop("observe")) is not bool:
                raise ValueError("observe must be a boolean")
        return json.dumps(request)
