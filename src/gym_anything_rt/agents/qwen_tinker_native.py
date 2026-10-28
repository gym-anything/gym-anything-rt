"""Capture-only adapter for the frozen Qwen/Tinker evaluation deployment."""
import base64
from io import BytesIO
from pathlib import Path

from PIL import Image
from agents.agents.qwen35vl import Qwen35VLAgent
from gym_anything_rt.agents.qwen35vl import observation_frames
from gym_anything_rt.agents.qwen_tinker import TinkerRealTimeQwen35VLAgent


class NativeImageTinkerQwenAgent(TinkerRealTimeQwen35VLAgent):
    def process_image(self, image_path):
        path = Path(image_path)
        raw = path.read_bytes()
        with Image.open(BytesIO(raw)) as image:
            size, image_format = image.size, image.format
        if image_format != 'JPEG':
            raise ValueError('This live deployment requires native JPEG capture')
        if size != tuple(self.display_resolution):
            raise ValueError(f'Native capture size {size} differs from {self.display_resolution}')
        self.original_sizes.append(size)
        self.processed_size = size
        return base64.b64encode(raw).decode('ascii'), str(path)

    def step(self, obs, action_outputs):
        frames = observation_frames(obs)
        if len(frames) != 1:
            raise ValueError('Plain live requires exactly one native frame')
        frame = frames[0]
        path = frame if isinstance(frame, (str, Path)) else frame['path']
        self._current_extra_frames = []
        normalized = dict(obs, screen={'path': str(path), 'format': 'jpeg',
                                      'resolution': list(self.display_resolution)})
        return Qwen35VLAgent.step(self, normalized, action_outputs)

    @staticmethod
    def _image_parts(sequence):
        if len(sequence) != 1:
            raise ValueError('Plain-live history requires one image per turn')
        return [{'type': 'image_url',
                 'image_url': {'url': 'data:image/jpeg;base64,' + sequence[0]}}]
