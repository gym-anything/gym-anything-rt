"""Apply the existing visible-UI-only rule to the frozen Qwen system prompt."""
from gym_anything_rt.agents.qwen_tinker_native import NativeImageTinkerQwenAgent
from gym_anything_rt.evaluate import VISIBLE_UI_ONLY_RULE


class NoCodeNativeQwenAgent(NativeImageTinkerQwenAgent):
    def get_system_prompt(self):
        return super().get_system_prompt() + '\n\n' + VISIBLE_UI_ONLY_RULE
