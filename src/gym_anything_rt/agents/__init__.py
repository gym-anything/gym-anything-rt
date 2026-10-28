"""Agents evaluated in the Gym-Anything-RT paper.

- ``codex_no_code:NoCodeCodexAgent``: GPT models through the Codex CLI, acting only
  through screenshots and mouse and keyboard input.
- ``codex_cli:RealTimeCodexCliAgent``: the same models, also allowed to write and
  run code in an isolated sandbox (the coding experiment).
- ``claude_no_code:NoCodeClaudeAgent``: Claude models through Claude Code.
- ``rulebook_no_code:RulebookNoCodeAgent``: the Codex agent with an
  environment rulebook appended to the task prompt.
- ``qwen_policy:NoCodeNativeQwenAgent``: Qwen models served through Tinker.
- ``probe:AuthoritativeObservationProbeAgent``: a scripted agent for checking the
  runtime without a model.
"""
