"""Opt-in Codex ablation exposing only literal screenshot and input requests."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import secrets
import shlex
import subprocess
import tempfile

from agents.shared.agent_sandbox import select_sandbox
from gym_anything_rt.agents.codex_cli import RealTimeCodexCliAgent, RealTimeCodexActionGateway
from gym_anything_rt.agents.codex_prompt import build_codex_prompt
from gym_anything_rt.agents.temporal_modes import validate_temporal_mode

logger = logging.getLogger(__name__)
PRIVATE = "/gym-agent-private/no-code"
NO_CODE_RULE = (
    "Solve the task using your own visual reasoning and the computer tool. "
    "Choose literal mouse/keyboard inputs or request a screenshot with actions=[]. "
    "Writing or executing code, scripts, loops, OCR, automated image processing, "
    "and background automation is prohibited. Use only visible controls of the "
    "task webpage. Do not open a terminal, external application, browser developer "
    "tools, console, inspector, source, DOM, or network panel. Do not navigate, "
    "reload, change URLs, inspect hidden state, or switch to unrelated tabs."
)
PROGRAM_PERMISSION = (
    "Solve only from screenshots returned by the action gateway and visible "
    "controls in the task webpage. You may write programs inside the isolated "
    "agent sandbox to call that gateway and process its screenshots. Do not "
    "connect to the task VM, use SSH or VNC, inspect its filesystem, call its "
    "services, or use Developer Tools, the console, debugger, inspector, "
    "network panel, source, DOM, page-state, address-bar, URL, query, reload, "
    "navigation, browser extensions, external applications, or hidden state. "
    "Do not switch to unrelated tabs."
)


def no_code_config(temporal_mode="live"):
    validate_temporal_mode(temporal_mode)
    disabled = (
        "shell_tool", "unified_exec", "code_mode", "code_mode_host", "multi_agent",
        "multi_agent_v2", "apps", "plugins", "skill_search", "browser_use",
        "computer_use", "image_generation", "goals", "sleep_tool", "view_image",
    )
    return {
        **{f"features.{name}": False for name in disabled},
        "tools.view_image": False,
        "web_search": "disabled",
        "model_catalog_json": f"{PRIVATE}/models.json",
        "developer_instructions": NO_CODE_RULE,
        "mcp_servers.computer.command": "python3",
        "mcp_servers.computer.args": [f"{PRIVATE}/codex_no_code_mcp.py"],
        "mcp_servers.computer.env_vars": ["GATEWAY_URL", "GATEWAY_TOKEN"],
        "mcp_servers.computer.env.NO_CODE_TEMPORAL_MODE": temporal_mode,
        "mcp_servers.computer.required": True,
        "mcp_servers.computer.enabled_tools": ["computer"],
        "mcp_servers.computer.tools.computer.approval_mode": "approve",
        "mcp_servers.computer.startup_timeout_sec": 20,
        "mcp_servers.computer.tool_timeout_sec": 300,
    }


def restricted_catalog(catalog, model):
    selected = [m for m in catalog["models"] if m["slug"] == model]
    if len(selected) != 1:
        raise ValueError("The model catalog must contain the requested model exactly once")
    record = dict(selected[0])
    # Codex 0.153.3's model defaults override the feature switches. Clear only
    # tool selections, retaining the model identity and all inference metadata.
    record.update(tool_mode=None, multi_agent_version=None,
                  apply_patch_tool_type=None, experimental_supported_tools=[],
                  supports_search_tool=False)
    return {"models": [record]}


def no_code_prompt(task, resolution, max_steps, mode):
    validate_temporal_mode(mode)
    if PROGRAM_PERMISSION not in task:
        raise ValueError("Unrecognized task instruction boundary; refusing to rewrite it")
    task = task.replace(PROGRAM_PERMISSION, NO_CODE_RULE)
    original = build_codex_prompt(task, resolution, max_steps, mode)
    controls = original.split("Coordinates use the returned ", 1)[1].split("Python HTTP client:", 1)[0]
    controls = controls.replace('- {"action":"terminate", "status":"success"} ends the task attempt.\n', "")
    return (
        NO_CODE_RULE + "\n\nUse the computer tool with {\"actions\": [...]} for all observations "
        "and inputs. Every call returns the screenshot after its inputs complete. "
        "Start with actions=[].\n\nCoordinates use the returned " + controls +
        f"\nYou have at most {max_steps} steps. Each non-observation request, including "
        "an ordered action list, consumes one step. Screenshot-only requests do not "
        "consume steps. Inputs in a batch execute in order. Release held inputs "
        "before finishing. Stop when done is true.\n\nTask:\n" + task
    )


class NoCodeCodexAgent(RealTimeCodexCliAgent):
    def prepare_sandbox(self, sandbox):
        super().prepare_sandbox(sandbox)
        directory = Path(__file__).parent
        for name in ("codex_no_code_mcp.py", "codex_actions.py"):
            sandbox.copy_file(directory / name, f"{PRIVATE}/{name}", mode=0o444)
        catalog = json.loads(Path(self.agent_args["no_code_model_catalog"]).read_text())
        restricted = restricted_catalog(catalog, self.model.split("/")[-1])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "models.json"
            path.write_text(json.dumps(restricted))
            sandbox.copy_file(path, f"{PRIVATE}/models.json", mode=0o444)

    def build_cli_command(self):
        command = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only",
                   "--model", self.model.split("/")[-1], "--json"]
        if not self.agent_args.get("persist_session"):
            command.append("--ephemeral")
        config = dict(no_code_config(self.temporal_mode),
                      model_reasoning_effort=self.agent_args["reasoning_effort"])
        for key, value in config.items():
            command.extend(["-c", f"{key}={json.dumps(value)}"])
        return shlex.join(command) + ' -- "$(cat /logs/prompt.txt)"'

    def run_episode(self, env, task_description=None):
        task = task_description or self.task_description
        max_steps = int(self.max_steps_override or getattr(env, "max_steps", None) or 50)
        logs = Path(self.save_path) / "cli_harness" if self.save_path else Path(tempfile.mkdtemp())
        logs.mkdir(parents=True, exist_ok=True)
        gateway = RealTimeCodexActionGateway(
            env, self.display_resolution, max_steps, secrets.token_hex(16),
            temporal_mode=self.temporal_mode, timing_path=logs / "timing.jsonl",
        )
        sandbox = select_sandbox(self.sandbox_spec(), logs)
        started = False
        port = gateway.start(host=sandbox.gateway_bind_host)
        try:
            sandbox.build()
            sandbox.start(port, gateway.token, self.container_env())
            started = True
            self.prepare_sandbox(sandbox)
            (logs / "prompt.txt").write_text(no_code_prompt(
                task, (gateway.display_w, gateway.display_h), max_steps, self.temporal_mode))
            result = sandbox.exec(self.build_cli_command(), timeout_sec=self.timeout_sec)
            if result.returncode:
                logger.warning("No-code Codex exited %s: %s", result.returncode, result.stderr[:2000])
        except subprocess.TimeoutExpired:
            logger.warning("No-code Codex timed out after %ds", self.timeout_sec)
        finally:
            self._transcript = gateway.transcript
            gateway.stop()
            if started:
                try:
                    self.collect_sandbox_artifacts(sandbox)
                except Exception as error:
                    raise RuntimeError("Codex session export failed; agent sandbox retained") from error
                sandbox.stop()
            self.done = True
