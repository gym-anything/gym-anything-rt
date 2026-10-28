"""Claude CLI provider over the unchanged literal-input evaluation protocol."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import tempfile

from gym_anything_rt.agents.codex_no_code import (
    NO_CODE_RULE, PRIVATE, NoCodeCodexAgent,
)

CLAUDE_HOME = "/gym-agent-private/claude-home"
CLAUDE_BINARY = "/gym-agent-private/claude"
COMPUTER_TOOL = "mcp__computer__computer"


def claude_command(model, effort, prompt_path="/logs/prompt.txt"):
    if model != "claude-opus-5-5" or effort != "xhigh":
        raise ValueError("This campaign requires Claude Opus 5.5 at xhigh")
    command = [CLAUDE_BINARY, "--print", "--verbose", "--output-format", "stream-json",
               "--model", model, "--effort", effort,
               "--tools", "", "--allowedTools", COMPUTER_TOOL,
               "--strict-mcp-config", "--mcp-config", f"{PRIVATE}/claude-mcp.json",
               "--setting-sources", "", "--disable-slash-commands", "--restricted",
               "--system-prompt", NO_CODE_RULE]
    return shlex.join(command) + " < " + shlex.quote(prompt_path)


def audit_cli_records(records, require_result=True):
    initialized = [r for r in records if r.get("type") == "system" and r.get("subtype") == "init"]
    if len(initialized) != 1:
        raise ValueError("Expected one Claude initialization record")
    init = initialized[0]
    if init.get("model") != "claude-opus-5-5":
        raise ValueError("Unexpected Claude model")
    if set(init.get("tools", [])) != {COMPUTER_TOOL}:
        raise ValueError(f"Unexpected tool catalog: {init.get('tools')}")
    calls = []
    for row in records:
        if row.get("type") != "assistant":
            continue
        message = row.get("message", {})
        if message.get("model") and message["model"] != "claude-opus-5-5":
            raise ValueError("Model changed during episode")
        for block in message.get("content", []):
            if block.get("type") == "tool_use":
                if block.get("name") != COMPUTER_TOOL:
                    raise ValueError("Non-computer tool used")
                calls.append(block)
    results = [r for r in records if r.get("type") == "result"]
    if require_result and len(results) != 1:
        raise ValueError("Missing Claude terminal result")
    return dict(model=init["model"], tools=init["tools"], computer_calls=len(calls),
                result=results[-1] if results else None)


class NoCodeClaudeAgent(NoCodeCodexAgent):
    # Reuse the existing isolated image. Only the provider executable and
    # private login change; the gateway, MCP server, prompt and runner stay fixed.
    def container_env(self):
        return {"CLAUDE_CONFIG_DIR": CLAUDE_HOME,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_AUTOUPDATER": "1",
                "API_TIMEOUT_MS": "900000", "CLAUDE_CODE_MAX_RETRIES": "2",
                "NO_CODE_TEMPORAL_MODE": self.temporal_mode}

    def prepare_sandbox(self, sandbox):
        if sandbox.exec("test ! -e /usr/local/bin/act", timeout_sec=30).returncode:
            raise RuntimeError("Deprecated act wrapper is present")
        auth = Path(self.agent_args["claude_auth_dir"])
        credentials = auth / ".credentials.json"
        if credentials.stat().st_mode & 0o077:
            raise ValueError("Claude credentials must be private")
        sandbox.copy_file(credentials, f"{CLAUDE_HOME}/.credentials.json", mode=0o600)
        sandbox.copy_file(auth / ".claude.json", f"{CLAUDE_HOME}/.claude.json", mode=0o600)
        sandbox.copy_file(Path(self.agent_args["claude_binary"]), CLAUDE_BINARY, mode=0o500)
        directory = Path(__file__).parent
        for name in ("codex_no_code_mcp.py", "codex_actions.py"):
            sandbox.copy_file(directory / name, f"{PRIVATE}/{name}", mode=0o444)
        config = {"mcpServers": {"computer": {
            "type": "stdio", "command": "python3",
            "args": [f"{PRIVATE}/codex_no_code_mcp.py"],
            "env": {"NO_CODE_TEMPORAL_MODE": self.temporal_mode},
        }}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "claude-mcp.json"
            path.write_text(json.dumps(config))
            sandbox.copy_file(path, f"{PRIVATE}/claude-mcp.json", mode=0o444)

    def build_cli_command(self):
        return claude_command(self.model, self.agent_args["reasoning_effort"])

    def collect_sandbox_artifacts(self, sandbox):
        if not self.save_path:
            raise RuntimeError("A persistent episode directory is required")
        destination = Path(self.save_path) / "cli_harness" / "claude_sessions"
        sandbox.copy_directory_from(f"{CLAUDE_HOME}/projects", destination)
        files = list(destination.rglob("*.jsonl"))
        if not files:
            raise RuntimeError("Claude session export contained no JSONL files")
        for path in files:
            for line in path.read_text().splitlines():
                json.loads(line)
