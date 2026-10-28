"""Append an interface rulebook to the frozen no-code task prompt."""
import hashlib
from pathlib import Path

from gym_anything_rt.agents.codex_no_code import NoCodeCodexAgent


class RulebookNoCodeAgent(NoCodeCodexAgent):
    def __init__(self, agent_args=None, **kwargs):
        arguments = dict(agent_args or {})
        path = Path(arguments['rulebook_path']).resolve()
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != arguments['rulebook_sha256']:
            raise ValueError(f'Rulebook hash mismatch: {path}')
        self.rulebook_text = content.decode('utf-8').strip()
        if not self.rulebook_text:
            raise ValueError(f'Empty rulebook: {path}')
        super().__init__(agent_args=arguments, **kwargs)

    def run_episode(self, env, task_description=None):
        task = task_description or self.task_description
        return super().run_episode(
            env=env,
            task_description=f'{task}\n\nInterface rulebook:\n{self.rulebook_text}',
        )
