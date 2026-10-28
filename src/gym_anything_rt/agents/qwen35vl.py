from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from PIL import Image
from agents.agents.qwen35vl import Qwen35VLAgent
from agents.shared.llm_clients import call_llm


NULL_RESPONSE_ATTEMPTS = 3


def call_qwen_with_null_response_retry(*args, **kwargs):
    """Retry successful model requests whose message content is null."""
    for attempt in range(1, NULL_RESPONSE_ATTEMPTS + 1):
        response = call_llm(*args, **kwargs)
        if response is not None:
            return response
        print(
            "Qwen returned content=null "
            f"(attempt {attempt}/{NULL_RESPONSE_ATTEMPTS})"
        )
    raise RuntimeError(
        f"Qwen returned content=null after {NULL_RESPONSE_ATTEMPTS} attempts"
    )


def image_from_screen(value: Any) -> Image.Image:
    if isinstance(value, (str, Path)):
        with Image.open(value) as image:
            return image.convert("RGB")
    if not isinstance(value, dict):
        raise TypeError(f"unsupported screen value: {type(value).__name__}")
    image = value.get("image")
    if image is not None:
        return image.convert("RGB")
    encoded = value.get("png_b64")
    if encoded:
        with Image.open(BytesIO(base64.b64decode(encoded))) as decoded:
            return decoded.convert("RGB")
    path = value.get("path")
    if path:
        with Image.open(path) as decoded:
            return decoded.convert("RGB")
    raise ValueError("screen value has no image, png_b64, or path")


def observation_frames(obs: dict[str, Any]) -> list[Any]:
    frames = obs.get("frames")
    if isinstance(frames, list) and frames:
        return frames
    screen = obs.get("screen")
    if screen is None:
        raise ValueError("observation has no screen")
    return [screen]


class RealTimeQwen35VLAgent(Qwen35VLAgent):
    """Gym Anything's Qwen 3.5 agent with chronological frame observations."""

    llm_call = staticmethod(call_qwen_with_null_response_retry)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.frame_sequences: list[list[str]] = []
        self._current_extra_frames: list[str] = []

    @staticmethod
    def _parse_keys(raw_keys):
        aliases = {"arrowup": "up", "arrowdown": "down",
                   "arrowleft": "left", "arrowright": "right"}
        return [aliases.get(key.lower(), key)
                for key in Qwen35VLAgent._parse_keys(raw_keys)]

    def _native_image(self, value: Any) -> Image.Image:
        image = image_from_screen(value)
        expected = tuple(int(item) for item in self.display_resolution)
        if image.size != expected:
            raise ValueError(
                f"observation image is {image.size[0]}x{image.size[1]}; "
                f"expected {expected[0]}x{expected[1]}"
            )
        return image

    def process_image(self, image_path: str) -> tuple[str, str]:
        """Send the native observation pixels to Qwen without resampling."""
        image = self._native_image(image_path)
        path = Path(self.save_folder_custom) / f"observation_{self.step_idx}.png"
        image.save(path, format="PNG")
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        original_sizes = getattr(self, "original_sizes", None)
        if isinstance(original_sizes, list):
            original_sizes.append(image.size)
        self.processed_size = image.size
        return encoded, str(path)

    def _process_frame(self, value: Any, *, step: int, index: int) -> tuple[str, str]:
        image = self._native_image(value)
        path = Path(self.save_folder_custom) / f"observation_{step}_frame_{index:03d}.png"
        image.save(path, format="PNG")
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        self.b64_to_path[encoded] = str(path)
        return encoded, str(path)

    def step(self, obs, action_outputs):
        frames = observation_frames(obs)
        next_step = self.step_idx + 1
        self._current_extra_frames = [
            self._process_frame(frame, step=next_step, index=index)[0]
            for index, frame in enumerate(frames[:-1])
        ]
        latest = image_from_screen(frames[-1])
        latest_path = Path(self.save_folder_custom) / f"rt_input_{next_step}.png"
        latest.save(latest_path, format="PNG")
        normalized = dict(obs)
        normalized["screen"] = {
            "path": str(latest_path),
            "format": "png",
            "resolution": list(latest.size),
        }
        return super().step(normalized, action_outputs)

    @staticmethod
    def _image_parts(sequence: list[str]) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        if len(sequence) > 1:
            parts.append(
                {
                    "type": "text",
                    "text": (
                        "These screenshots are one observation in chronological order. "
                        "The final screenshot is the current state."
                    ),
                }
            )
        parts.extend(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
            for encoded in sequence
        )
        return parts

    @staticmethod
    def _wrap_tool_response(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return (
            [{"type": "text", "text": "<tool_response>\n"}]
            + parts
            + [{"type": "text", "text": "\n</tool_response>"}]
        )

    def _record_current_sequence(self, current_screenshot_b64: str) -> None:
        current_sequence = [*self._current_extra_frames, current_screenshot_b64]
        current_index = max(0, len(self.screenshots) - 1)
        if len(self.frame_sequences) <= current_index:
            self.frame_sequences.append(current_sequence)
        else:
            self.frame_sequences[current_index] = current_sequence

    def _collapsed_turns(
        self,
        *,
        start_index: int,
        image_max: int,
        fold_size: int,
    ) -> set[int]:
        current_index = len(self.screenshots) - 1
        candidates = list(range(start_index, current_index))
        active_images = sum(
            len(self.frame_sequences[index])
            for index in range(start_index, current_index + 1)
        )
        collapsed: set[int] = set()
        while active_images > image_max and candidates:
            batch = candidates[:fold_size]
            candidates = candidates[fold_size:]
            for index in batch:
                collapsed.add(index)
                active_images -= len(self.frame_sequences[index])
        return collapsed

    def build_messages(
        self,
        current_screenshot_b64,
        history_n: Optional[int] = None,
        image_max: Optional[int] = None,
        fold_size: Optional[int] = None,
    ):
        self._record_current_sequence(current_screenshot_b64)

        history_n = max(1, int(self.history_n if history_n is None else history_n))
        image_max = max(
            1,
            int(getattr(self, "image_max", 20) if image_max is None else image_max),
        )
        fold_size = max(
            1,
            int(getattr(self, "fold_size", 10) if fold_size is None else fold_size),
        )
        total_steps = len(self.screenshots)
        start_step = max(1, total_steps - history_n)
        start_index = start_step - 1
        collapsed = self._collapsed_turns(
            start_index=start_index,
            image_max=image_max,
            fold_size=fold_size,
        )

        previous_actions = [
            f"Step {index + 1}: {self.history[index]}"
            for index in range(0, min(start_step - 1, len(self.history)))
        ]
        previous_actions_text = "\n".join(previous_actions) if previous_actions else "None"
        instruction = (
            "\nPlease generate the next move according to the UI screenshots, instruction, "
            "and previous actions.\n\n"
            f"Instruction: {self.task_description}\n\n"
            f"Previous actions:\n{previous_actions_text}"
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": [{"type": "text", "text": self.get_system_prompt()}],
            }
        ]

        for step_num in range(start_step, total_steps + 1):
            index = step_num - 1
            first = step_num == start_step
            if index in collapsed:
                parts = [{"type": "text", "text": "This screenshot has been collapsed."}]
            else:
                parts = self._image_parts(self.frame_sequences[index])
            if first:
                content = [*parts, {"type": "text", "text": instruction}]
            else:
                content = self._wrap_tool_response(parts)
            messages.append({"role": "user", "content": content})

            if step_num <= total_steps - 1 and index < len(self.responses):
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": str(self.responses[index])}
                        ],
                    }
                )
        return messages
