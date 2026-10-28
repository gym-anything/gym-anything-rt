"""Gym-Anything-RT's Codex CLI temporal adapter over Gym-Anything's CLI harness."""

from __future__ import annotations

import json
import logging
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from agents.agents.codex_cli import CodexCliAgent
from agents.shared.agent_sandbox import select_sandbox, ApptainerSandbox
ApptainerSandbox._CACHE_DIR = Path('/tmp/wcb-astra-low-rt32-fast-20260922/agent-images')
from agents.shared.cli_harness import ActionGateway

from gym_anything_rt.agents.codex_actions import parse_command
from gym_anything_rt.agents.fast_http import FastImageGatewayMixin
from gym_anything_rt.agents.codex_prompt import build_codex_prompt
from gym_anything_rt.agents.temporal_modes import (
    episode_clock_origin_ms,
    scheduled_execution_enabled,
    timestamps_enabled,
)

logger = logging.getLogger(__name__)


class RealTimeCodexActionGateway(FastImageGatewayMixin, ActionGateway):
    """Bind Codex timing to the Gym-Anything-RT episode clock and persist every event."""

    def __init__(self, *args: Any, timing_path: Path, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._timing_path = timing_path
        self._timing_path.parent.mkdir(parents=True, exist_ok=True)
        self._timing_write_lock = threading.Lock()
        self._next_request_index = 0
        self._finished = False
        self._input_ready = False
        self._sandbox_input = False
        self._input_ready_lock = threading.Lock()
        self._input_request = threading.local()

    def _prepare_input(self):
        if self.temporal_mode == "paused":
            return
        with self._input_ready_lock:
            if not self._input_ready:
                from gym_anything_rt.scheduled_input import prepare_input
                ready = prepare_input(self.env)
                self._sandbox_input = ready.get("sandbox_scheduling", True)
                if self._sandbox_input:
                    self._t0_ms = float(ready["episode_started_wall_ms"])
                self._input_ready = True

    def _execute_action(self, env_actions, *, target_wall_ms):
        if self.temporal_mode == "paused":
            return super()._execute_action(env_actions, target_wall_ms=target_wall_ms)
        from gym_anything_rt.scheduled_input import execute_input
        self._prepare_input()
        if not self._sandbox_input:
            return super()._execute_action(env_actions, target_wall_ms=target_wall_ms)
        if not env_actions:
            from gym_anything_rt.scheduled_input import close_input
            close_input(self.env)
            return True, time.time_ns() / 1e6
        result = execute_input(self.env, env_actions, self._input_request.execute_at_s)
        self._input_request.receipt = result["receipt"]
        return bool(result["done"]), self._t0_ms + result["receipt"]["action_executed_at_s"] * 1000

    def _capture_payload(self, *, action_receipt=None):
        if self.temporal_mode == "paused":
            return super()._capture_payload(action_receipt=action_receipt)
        self._prepare_input()
        if not self._sandbox_input:
            return super()._capture_payload(action_receipt=action_receipt)
        if action_receipt is None or self._input_request.receipt is None:
            return super()._capture_payload()
        receipt = self._input_request.receipt
        timing = None
        if timestamps_enabled(self.temporal_mode):
            executed = receipt["action_executed_at_s"]
            timing = {
                "action_executed_at_s": executed,
                "action_completed_at_s": receipt["action_completed_at_s"],
                "previous_action_finished_executing_by_s": receipt["action_completed_at_s"],
                "action_queued_at_s": receipt["queued_at_s"],
                "action_ack_sent_at_s": receipt["ack_sent_at_s"],
                "current_time_s": (time.time_ns() / 1e6 - self._t0_ms) / 1000,
                "acknowledgement": receipt["acknowledgement"],
            }
            target = receipt.get("requested_execute_at_s")
            if target is not None:
                timing["previous_action_requested_execute_at_s"] = target
                timing["action_execution_lateness_s"] = executed - target
            observed = action_receipt.get("observed_frame_s")
            if observed is not None:
                latency = executed - observed
                with self._state_lock:
                    self._latency_log.append(latency)
                    recent = self._latency_log[-8:]
                timing["seconds_between_your_last_screenshot_and_that_action_landing"] = latency
                timing["your_recent_observe_to_execute_latencies_s"] = recent
        payload = {"screenshots_b64": [], "screenshot_b64": None, "observation": None,
                   "timing": timing, "acknowledgement": receipt["acknowledgement"]}
        if timestamps_enabled(self.temporal_mode):
            payload["input_receipt"] = receipt
        return payload

    def _env_actions_for(
        self, command: str,
    ) -> tuple[list[dict[str, Any]], bool, bool, float | None, str | None]:
        try:
            actions, terminal, observation, execute_at_s = parse_command(
                self.action_command(command), (self.ratio_x, self.ratio_y)
            )
            if execute_at_s is not None:
                if not scheduled_execution_enabled(self.temporal_mode):
                    raise ValueError(
                        "execute_at_s is available only in live_timestamped_execution mode"
                    )
                with self._state_lock:
                    if self._t0_ms is None:
                        raise ValueError("request a screenshot before using execute_at_s")
            return actions, terminal, observation, execute_at_s, None
        except (ValueError, TypeError, KeyError) as error:
            return [], False, False, None, f"invalid action request: {error}"

    def _timing_payload(
        self,
        obs: dict[str, Any],
        *,
        action_receipt: dict[str, float | None] | None,
        capture_finished_wall_ms: float,
    ) -> dict[str, Any] | None:
        if timestamps_enabled(self.temporal_mode):
            origin = episode_clock_origin_ms(obs)
            if self._t0_ms is None:
                self._t0_ms = origin
            elif abs(origin - self._t0_ms) > 1:
                raise RuntimeError("observation and input service have different episode clocks")
        return super()._timing_payload(
            obs,
            action_receipt=action_receipt,
            capture_finished_wall_ms=capture_finished_wall_ms,
        )

    def step_from_command(self, command: str) -> dict[str, Any]:
        # The upstream error response captures a new observation. In paused
        # mode that advances task time, so validate here before entering it.
        parsed = self._env_actions_for(command)
        error = parsed[-1]
        with self._state_lock:
            if self._finished or error is not None:
                if self._finished:
                    error = "episode is finished"
                self.transcript.append(
                    {"step": self.steps_taken, "command": command, "error": error}
                )
                return {
                    "step": self.steps_taken,
                    "budget_remaining": max(
                        0, self.max_steps - self.steps_taken - self._actions_reserved
                    ),
                    "done": self._finished,
                    "error": error,
                    "screenshots_b64": [],
                    "screenshot_b64": None,
                }
            request_index = self._next_request_index
            self._next_request_index += 1
        self._input_request.execute_at_s = parsed[3]
        self._input_request.receipt = None
        response = super().step_from_command(command)
        with self._state_lock:
            self._finished = self._finished or bool(response.get("done"))
        timing = response.get("timing")
        if isinstance(timing, dict):
            common = {
                "request_index": request_index,
                "step": response.get("step"),
                "command": command,
            }
            events: list[dict[str, Any]] = []
            if timing.get("action_executed_at_s") is not None:
                events.append(
                    {
                        "event": "action_executed",
                        **common,
                        "action_executed_at_s": timing["action_executed_at_s"],
                        "requested_execute_at_s": timing.get(
                            "previous_action_requested_execute_at_s"
                        ),
                        "action_execution_lateness_s": timing.get(
                            "action_execution_lateness_s"
                        ),
                        "input_receipt": response.get("input_receipt"),
                    }
                )
            if timing.get("frame_captured_at_s") is not None:
                events.append(
                    {
                        "event": "screenshot_captured",
                        **common,
                        "observation": response.get("observation"),
                        "frame_captured_at_s": timing["frame_captured_at_s"],
                        "current_time_s": timing.get("current_time_s"),
                    }
                )
            with self._timing_write_lock:
                with self._timing_path.open("a", encoding="utf-8") as handle:
                    for event in events:
                        handle.write(json.dumps(event, sort_keys=True) + "\n")
        return response

    def stop(self):
        try:
            if self._sandbox_input:
                from gym_anything_rt.scheduled_input import close_input
                close_input(self.env)
        finally:
            super().stop()


class RealTimeCodexCliAgent(CodexCliAgent):
    """Codex CLI using Gym-Anything-RT's episode-clock and timing-artifact contract."""

    # Keep the benchmark sandbox new enough for the Codex models used by the
    # evaluation protocol without changing Gym-Anything's upstream default.
    sandbox_install = "npm install -g @openai/codex@0.153.3"

    def container_env(self):
        return dict(super().container_env(), PYTHONPATH="/gym-agent-private/http-timing")

    def prepare_sandbox(self, sandbox):
        super().prepare_sandbox(sandbox)
        result = sandbox.exec("test ! -e /usr/local/bin/act", timeout_sec=30)
        if result.returncode:
            raise RuntimeError("deprecated act wrapper is present in agent image")
        sandbox.copy_file(Path(__file__).with_name("http_timing_sitecustomize.py"),
                          "/gym-agent-private/http-timing/sitecustomize.py", mode=0o644)

    def run_episode(self, env: Any, task_description: str | None = None) -> None:
        task = task_description or self.task_description
        resolution = self.display_resolution
        max_steps = int(
            self.max_steps_override or getattr(env, "max_steps", None) or 50
        )
        logs_dir = (
            Path(self.save_path) / "cli_harness"
            if self.save_path
            else Path(tempfile.mkdtemp())
        )
        logs_dir.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(16)
        gateway = RealTimeCodexActionGateway(
            env,
            resolution,
            max_steps,
            token,
            temporal_mode=self.temporal_mode,
            timing_path=logs_dir / "timing.jsonl",
        )
        sandbox = select_sandbox(self.sandbox_spec(), logs_dir)
        sandbox_started = False

        port = gateway.start(host=sandbox.gateway_bind_host)
        try:
            sandbox.build()
            sandbox.start(
                gateway_port=port,
                gateway_token=token,
                container_env=self.container_env(),
            )
            sandbox_started = True
            self.prepare_sandbox(sandbox)
            prompt = build_codex_prompt(
                task,
                (gateway.display_w, gateway.display_h),
                max_steps,
                temporal_mode=self.temporal_mode,
            )
            (logs_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
            result = sandbox.exec(
                self.build_cli_command(), timeout_sec=self.timeout_sec
            )
            if result.returncode != 0 and self.verbose:
                logger.warning(
                    "CLI exited with %d; stderr: %s",
                    result.returncode,
                    result.stderr[:2000],
                )
        except subprocess.TimeoutExpired:
            logger.warning("CLI harness timed out after %ds", self.timeout_sec)
        finally:
            self._transcript = gateway.transcript
            gateway.stop()
            if sandbox_started:
                try:
                    self.collect_sandbox_artifacts(sandbox)
                except Exception as error:
                    logger.exception(
                        "Session export failed; retaining the agent sandbox and "
                        "its private files for recovery"
                    )
                    raise RuntimeError(
                        "Codex session export failed; agent sandbox retained"
                    ) from error
            sandbox.stop()
            self.done = True
