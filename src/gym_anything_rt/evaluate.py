#!/usr/bin/env python3
"""Gym-Anything-RT evaluation harness over the standard Gym-Anything doors.

The world behavior lives in ``gym_anything_rt.runner``:
``RealTimeRunner`` owns the puzzle clock, frame-window observation
capture, guest configuration, and artifact collection. This harness only
schedules turns: it merges the run condition into ``EnvSpec.runner_options``,
loops agent.step over the observations ``env.reset``/``env.step`` return,
enforces the model-request deadline and single retry layer, and writes the
timing manifest.
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import math
import signal
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any

import agents.agents as agent_registry

from gym_anything_rt.runner import (
    capture_observation_window,
    guest_json,
)
from gym_anything_rt.agents.qwen35vl import RealTimeQwen35VLAgent
from gym_anything_rt.agents.temporal_modes import (
    TEMPORAL_MODES,
    scheduled_execution_enabled,
    timestamps_enabled,
    world_time_mode,
)
from gym_anything_rt.realtime import (
    RealTimeSettings,
    load_real_time_settings,
    mechanic_id_from_env_dir,
)
from gym_anything_rt.agents.probe import (
    AuthoritativeObservationProbeAgent,
)


logger = logging.getLogger(__name__)

VISIBLE_UI_ONLY_RULE = (
    "Solve only from screenshots and visible controls in the task webpage. "
    "Do not use code, scripts, automation, Developer Tools, the console, debugger, "
    "inspector, network panel, source or DOM inspection, page-state inspection, a "
    "terminal, shell, Python, address-bar or URL changes, query edits, reload, "
    "navigation, browser extensions, external applications, or hidden-state access. "
    "Do not switch to unrelated tabs. A tab opened by a visible task control is allowed "
    "only when it is part of the task and only through its visible controls."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Gym-Anything-RT temporal modes.")
    parser.add_argument("--env-dir", "--env_dir", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--agent-args", "--agent_args", required=True)
    parser.add_argument(
        "--temporal-mode",
        "--time-mode",
        dest="temporal_mode",
        choices=TEMPORAL_MODES,
        required=True,
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--time-scale", type=float, default=1.0,
                        help="Game-clock rate in (0, 1]; 0.25 runs at quarter speed.")
    parser.add_argument("--steps", type=int)
    parser.add_argument("--use-cache", "--use_cache", action="store_true")
    parser.add_argument("--cache-level", "--cache_level", default="pre_start")
    parser.add_argument("--use-savevm", "--use_savevm", action="store_true")
    parser.add_argument("--fast-io", "--fast_io", action="store_true")
    parser.add_argument(
        "--inner-runner",
        help="Execution backend for the benchmark runner (registered key or class locator).",
    )
    parser.add_argument("--remote-url", "--remote_url")
    parser.add_argument("--remote-timeout", "--remote_timeout", type=int, default=300)
    parser.add_argument(
        "--remote-worker-reset-policy",
        "--remote_worker_reset_policy",
        choices=("core", "baseline_setup"),
        default="core",
    )
    play_time = parser.add_mutually_exclusive_group()
    play_time.add_argument("--play-time-seconds", type=int)
    play_time.add_argument(
        "--no-play-time-limit",
        action="store_true",
        help="Disable the task-clock cutoff. Step and model-request limits still apply.",
    )
    parser.add_argument("--observation-window-ms", type=int)
    parser.add_argument("--frames-per-observation", type=int)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--request-timeout-seconds", type=float, default=120)
    parser.add_argument("--request-attempts", type=int, default=3)
    parser.add_argument(
        "--client-episode-root",
        type=Path,
        help=(
            "Local root for remote episode mirrors. Defaults to "
            "~/.gym-anything-rt/remote-episodes."
        ),
    )
    parser.add_argument("--episode-summary-path", type=Path)
    return parser


def _settings(args: argparse.Namespace) -> tuple[str, RealTimeSettings]:
    mechanic_id = mechanic_id_from_env_dir(args.env_dir)
    base = load_real_time_settings(mechanic_id)
    return mechanic_id, RealTimeSettings.from_dict({
        "play_time_seconds": (
            base.play_time_seconds
            if args.play_time_seconds is None
            else args.play_time_seconds
        ),
        "observation_window_ms": (
            base.observation_window_ms
            if args.observation_window_ms is None
            else args.observation_window_ms
        ),
        "frames_per_observation": (
            base.frames_per_observation
            if args.frames_per_observation is None
            else args.frames_per_observation
        ),
    })


def _temporal_mode(args: argparse.Namespace) -> str:
    return getattr(args, "temporal_mode", getattr(args, "time_mode", None))


def _runner_options(args: argparse.Namespace, settings: RealTimeSettings) -> dict[str, Any]:
    """The complete runner_options for this run: the environment's declared
    observation schedule with the invocation's run condition merged in."""
    temporal_mode = _temporal_mode(args)
    live = world_time_mode(temporal_mode) == "live"
    time_scale = getattr(args, "time_scale", 1.0)
    if not math.isfinite(time_scale) or not 0 < time_scale <= 1:
        raise ValueError("time_scale must be finite and in (0, 1]")
    options = {
        "time_mode": "live" if live else "paused",
        "time_scale": time_scale,
        "start_paused": True,
        # A live agent can request another observation at any time. Each
        # response is therefore one instantaneous frame; only paused mode
        # advances through the benchmark's configured frame window.
        "observation_window_ms": 0 if live else settings.observation_window_ms,
        "frames_per_observation": 1 if live else settings.frames_per_observation,
        "play_time_seconds": settings.play_time_seconds,
    }
    if getattr(args, "inner_runner", None):
        options["inner"] = args.inner_runner
    return options


def _play_time_limit_seconds(
    args: argparse.Namespace,
    settings: RealTimeSettings,
) -> int | None:
    return None if args.no_play_time_limit else settings.play_time_seconds


def _play_time_exhausted(task_time_ms: float, limit_seconds: int | None) -> bool:
    return limit_seconds is not None and task_time_ms >= limit_seconds * 1000


def _actions_with_schedule(
    group: dict[str, Any],
    *,
    temporal_mode: str,
) -> list[dict[str, Any]]:
    actions = list(group["actions"])
    metadata = group.get("metadata") or {}
    target_wall_ms = metadata.get("execute_at_wall_ms")
    if target_wall_ms is None or not actions:
        return actions
    if not scheduled_execution_enabled(temporal_mode):
        raise ValueError(
            "scheduled actions are supported only in "
            "live_timestamped_execution mode"
        )
    target_wall_ms = float(target_wall_ms)
    if not math.isfinite(target_wall_ms) or target_wall_ms < 0:
        raise ValueError("scheduled action wall time must be finite and non-negative")
    return [
        {"action": "scheduled_input", "wall_time_ms": target_wall_ms, "actions": actions},
    ]


def _time_command(env, command: str) -> dict:
    """Clock command for local evidence and probe tools.

    Evaluation itself never queries the clock: paused task time is exact in
    every observation, and live task time is extrapolated from the last
    observation by wall clock (see _TaskClock)."""
    return env.runner.time_command(command)


class _TaskClock:
    """Task time as reported by observations.

    Paused mode: the clock is frozen between observations, so the last
    observation's task time is exact. Live mode: the virtual clock advances
    with wall time while the task runs, so the tracker anchors each
    observation and extrapolates by wall clock. The world and the grader own
    authoritative expiry either way."""

    def __init__(self, mode: str, time_scale: float = 1.0):
        self.mode = mode
        self.time_scale = time_scale
        self._task_ms = 0.0
        self._anchor: float | None = None

    def observe(self, obs: dict[str, Any]) -> None:
        value = (obs.get("time") or {}).get("task_time_ms")
        if value is None:
            return
        self._task_ms = float(value)
        self._anchor = time.perf_counter()

    def now_ms(self) -> float:
        if self.mode == "live" and self._anchor is not None:
            return self._task_ms + (time.perf_counter() - self._anchor) * 1000 * self.time_scale
        return self._task_ms


def _guest_json(env, arguments: list[str]) -> dict[str, Any]:
    return guest_json(env, arguments)


def _capture_observation(
    env,
    *,
    mode: str,
    settings: RealTimeSettings,
    turn: int,
    hold_paused: bool = False,
) -> dict[str, Any]:
    """Explicit window capture for evidence and probe tools.

    Evaluation itself no longer calls this: ``env.reset``/``env.step`` return
    the runner's frame-window observation directly. Evidence tools keep this
    door for ``hold_paused`` recordings and custom turn labeling.
    """
    return capture_observation_window(
        env,
        mode=mode,
        duration_ms=settings.observation_window_ms,
        frames_per_observation=settings.frames_per_observation,
        turn=turn,
        host_dir=Path(env.episode_dir) / "observations" / f"turn-{turn:04d}",
        hold_paused=hold_paused,
    )


def _task_time_ms(env) -> float:
    """Local evidence and probe tools only; see _time_command."""
    return float(_time_command(env, "status").get("task_time_ms") or 0)


def _write_record(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


class _ModelRequestDeadline(TimeoutError):
    pass


@contextmanager
def _request_deadline(seconds: float):
    if seconds <= 0:
        raise ValueError("request timeout must be positive")
    if not hasattr(signal, "setitimer"):
        yield
        return
    prior_handler = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise _ModelRequestDeadline(
            f"model request exceeded the evaluator deadline of {seconds:g}s"
        )

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prior_handler)


def _http_status(error: BaseException) -> int | None:
    for candidate in (
        getattr(error, "status_code", None),
        getattr(error, "status", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ):
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _retryable_request_error(error: BaseException) -> bool:
    if isinstance(
        error,
        (
            TimeoutError,
            ConnectionError,
            RemoteDisconnected,
            BrokenPipeError,
            ConnectionResetError,
        ),
    ):
        return True
    status = _http_status(error)
    return status in {408, 429} or (
        status is not None and 500 <= status <= 599
    )


@contextmanager
def _action_error_feedback(agent, action_outputs):
    errors = [result["output"] for result in action_outputs if result.get("error")]
    if not errors or not isinstance(agent, RealTimeQwen35VLAgent):
        yield
        return
    # Qwen accepts action_outputs but ignores them when building messages.
    # Add feedback to this observation without changing its agent implementation.
    original = agent.build_messages
    previous = vars(agent).get("build_messages")

    def build_messages(*args, **kwargs):
        messages = original(*args, **kwargs)
        message = dict(messages[-1])
        content = list(message["content"])
        feedback = {"type": "text", "text": "Action error:\n" + "\n".join(errors)}
        if content and content[-1].get("text") == "\n</tool_response>":
            content.insert(len(content) - 1, feedback)
        else:
            content.append(feedback)
        message["content"] = content
        return [*messages[:-1], message]

    agent.build_messages = build_messages
    try:
        yield
    finally:
        if previous is None:
            del agent.build_messages
        else:
            agent.build_messages = previous


def _step_with_action_feedback(env, actions):
    try:
        return env.step(
            actions, wait_between_actions=0.0, settle_after_actions=False
        )
    except (ValueError, RuntimeError) as error:
        outside_desktop = False
        if str(error) == "pointer outside desktop":
            # Sandweave is optional for other runners. Match this rejection
            # without treating other sandbox failures as invalid model input.
            try:
                from sandweave.sandbox.errors import SandboxError
            except ImportError:
                raise error
            outside_desktop = type(error) is SandboxError
        # These are explicit input-validation errors, not transport, capture,
        # missing-runtime, or unknown implementation failures.
        known_value_error = isinstance(error, ValueError) and str(error).startswith((
            "unknown key: ", "key names must be nonempty strings",
            "position requires [x, y]", "coordinates must be integers in ",
            "actions support mouse and keyboard only",
            "mouse and keyboard must be dictionaries",
            "drag requires at least two positions", "scroll requires an integer",
            "buttons require left/middle/right/back/forward_down/up",
            "unknown mouse action: ", "unknown keyboard action: ",
            "text must contain at most 2048 characters",
            "keys require a string or list of strings",
            "action exceeds 8192 input events",
        ))
        if not outside_desktop and not known_value_error:
            raise
        message = f"{type(error).__name__}: {error}"
        logger.warning("Action rejected; returning feedback to the agent: %s", message)
        # Do not replay any part of the failed group. Earlier inputs may have
        # landed, so obtain a fresh observation before the model acts again.
        obs, reward, done, info = env.step(
            {"action": "screenshot"},
            wait_between_actions=0.0,
            settle_after_actions=False,
        )
        return obs, reward, done, {
            **info,
            "action_result": {
                "action": "error",
                "error": message,
                "output": (
                    f"Action group stopped: {message}. Earlier inputs in this "
                    "group may already have executed. Remaining action groups "
                    "were skipped. Use the current screenshot to choose your next action."
                ),
            },
        }


def _call_agent_with_retry(
    clock,
    agent,
    obs: dict[str, Any],
    action_outputs: list[dict[str, Any]],
    *,
    timeout_seconds: float,
    attempts: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if attempts < 1:
        raise ValueError("request attempts must be positive")
    records = []
    for attempt in range(1, attempts + 1):
        before_task_ms = clock.now_ms()
        started = time.perf_counter()
        try:
            with _request_deadline(timeout_seconds), _action_error_feedback(agent, action_outputs):
                actions = agent.step(obs, action_outputs)
        except Exception as error:
            elapsed_ms = (time.perf_counter() - started) * 1000
            after_task_ms = clock.now_ms()
            retryable = _retryable_request_error(error)
            records.append(
                {
                    "attempt": attempt,
                    "outcome": "error",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "retryable": retryable,
                    "wall_ms": elapsed_ms,
                    "task_time_before_request_ms": before_task_ms,
                    "task_time_after_request_ms": after_task_ms,
                    "task_time_delta_ms": after_task_ms - before_task_ms,
                }
            )
            if not retryable or attempt == attempts:
                raise
            continue
        elapsed_ms = (time.perf_counter() - started) * 1000
        after_task_ms = clock.now_ms()
        records.append(
            {
                "attempt": attempt,
                "outcome": "success",
                "retryable": False,
                "wall_ms": elapsed_ms,
                "task_time_before_request_ms": before_task_ms,
                "task_time_after_request_ms": after_task_ms,
                "task_time_delta_ms": after_task_ms - before_task_ms,
            }
        )
        return actions, records
    raise AssertionError("request loop ended without returning or raising")


def _task_description(
    env,
    args: argparse.Namespace,
    *,
    gateway_programs_allowed: bool = False,
) -> str:
    task_spec = env.task_spec
    description = task_spec.natural_language if task_spec else ""
    if not isinstance(description, str) or not description.strip():
        description = task_spec.description if task_spec else ""
    if not isinstance(description, str) or not description.strip():
        task_path = Path(args.env_dir) / "tasks" / args.task / "task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        description = task.get("natural_language") or task.get("description", "")
    interaction_rule = VISIBLE_UI_ONLY_RULE
    if gateway_programs_allowed:
        interaction_rule = (
            "Solve only from screenshots returned by the action gateway and visible "
            "controls in the task webpage. You may write programs inside the isolated "
            "agent sandbox to call that gateway and process its screenshots. Do not "
            "connect to the task VM, use SSH or VNC, inspect its filesystem, call its "
            "services, or use Developer Tools, the console, debugger, inspector, "
            "network panel, source, DOM, page-state, address-bar, URL, query, reload, "
            "navigation, browser extensions, external applications, or hidden state. "
            "Do not switch to unrelated tabs."
        )
    submit_rule = (
        "Your answer only counts once it is submitted: after completing the "
        "task, press the visible submit/confirm/verify control and check the "
        "UI acknowledges it before you declare the task finished."
    )
    return f"{description}\n\n{interaction_rule}\n\n{submit_rule}"


def _submission_counts(env, *, passed: bool) -> dict:
    """How many times the benchmark server graded a submission this episode.

    The server appends every graded-and-failed submission to attempts.jsonl and
    then issues a fresh challenge; a passing submission is not archived. Zero
    graded submissions is the common case and means the agent never pressed
    submit, so it is reported separately from the verdict."""
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    handle.close()
    try:
        # Two hops for a remote env: copy_from_env lands the file on the worker
        # (its host_dst is remote), then fetch_path brings it back here.
        staged = f"/tmp/task_result_attempts_{uuid.uuid4().hex}.json"
        env.copy_from_env("/tmp/task_result.json", staged)
        env.fetch_path(staged, handle.name)
        exported = json.loads(Path(handle.name).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        Path(handle.name).unlink(missing_ok=True)
    failures = int(exported.get("graded_failures") or 0)
    return {
        "graded_failures": failures,
        "graded_total": failures + (1 if passed else 0),
        "submitted": failures > 0 or passed,
    }


def _mark_done(env, *, reason: str) -> tuple[dict, float, bool, dict]:
    obs, reward, done, info = env.step(
        [], mark_done=True, capture_observation=False, settle_after_actions=False
    )
    info["benchmark_reason"] = reason
    return obs, reward, done, info


def _resolve_agent_class(name: str, temporal_mode: str = "live"):
    if name == "AuthoritativeObservationProbeAgent":
        return AuthoritativeObservationProbeAgent
    if name == "CodexCliAgent":
        from gym_anything_rt.agents.codex_cli import RealTimeCodexCliAgent

        return RealTimeCodexCliAgent
    if name in {"Qwen35VLAgent", "RealTimeQwen35VLAgent"}:
        if timestamps_enabled(temporal_mode):
            raise ValueError("timestamped temporal modes are supported by the Codex and Claude agents only")
        return RealTimeQwen35VLAgent
    if ":" in name:
        module_name, _, class_name = name.partition(":")
        return getattr(importlib.import_module(module_name), class_name)
    return getattr(agent_registry, name)


def _make_env(args: argparse.Namespace, runner_options: dict[str, Any] | None = None):
    if runner_options is None:
        _mechanic, settings = _settings(args)
        runner_options = _runner_options(args, settings)
    if not args.remote_url:
        from gym_anything.api import from_config

        return from_config(
            args.env_dir,
            task_id=args.task,
            overrides={"runner_options": runner_options},
            fast_io=args.fast_io,
        )
    from gym_anything.remote import RemoteGymEnv

    # By-name create keeps code resolution worker-local and verifies the task
    # digest. Runtime runner options cross the normal remote override door;
    # an evaluation never creates or edits benchmark task directories.
    return RemoteGymEnv.from_benchmark(
        remote_url=args.remote_url,
        benchmark="gym_anything_rt",
        env_name=Path(args.env_dir).name,
        task_id=args.task,
        timeout=args.remote_timeout,
        worker_reset_policy=args.remote_worker_reset_policy,
        fast_io=args.fast_io,
        overrides={"runner_options": runner_options},
    )


def _require_frames(obs: dict[str, Any], *, where: str) -> None:
    """Core swallows delegated capture errors outside fast_io; an
    observation without frames means the window capture failed."""
    if "frames" not in obs or "screen" not in obs:
        raise RuntimeError(
            f"the {where} observation has no frame window; the in-guest "
            "capture failed (see the environment logs)"
        )


def _remote_episode_root(client_episode_root: Path | None = None) -> Path:
    if client_episode_root is not None:
        return client_episode_root
    return Path.home() / ".gym-anything-rt" / "remote-episodes"


def _client_episode_dir(
    env,
    client_episode_root: Path | None = None,
) -> Path:
    """Where this harness writes its own records.

    Local runs write into the episode directory. Remote runs write into a
    per-episode mirror under the caller's home, because env.episode_dir is a
    worker-host path that need not exist on this machine.
    """
    worker_dir = Path(str(env.episode_dir))
    if not hasattr(env, "fetch_path"):
        return worker_dir
    mirror = _remote_episode_root(client_episode_root) / worker_dir.name
    mirror.mkdir(parents=True, exist_ok=True)
    return mirror


def _localize_observation(
    env,
    obs: dict[str, Any],
    client_episode_root: Path | None = None,
) -> dict[str, Any]:
    """Fetch a remote observation's frame files to this host.

    Local environments return host paths already. Remote observations carry
    worker paths; each frame and the capture manifest come over the standard
    fetch_path route into a per-episode mirror, and the paths are rewritten
    so every downstream consumer (agents, records) stays uniform.
    """
    fetch = getattr(env, "fetch_path", None)
    if fetch is None:
        return obs
    turn_name = Path(obs["frames"][0]["path"]).parent.name
    episode_name = Path(str(env.episode_dir)).name if env.episode_dir else "episode"
    mirror = _remote_episode_root(client_episode_root) / episode_name / turn_name
    mirror.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, frame in enumerate(obs["frames"]):
        local = fetch(frame["path"], str(mirror / f"frame-{index:03d}.png"))
        frames.append({**frame, "path": local})
    manifest = fetch(
        obs["capture_manifest"], str(mirror / "guest-capture-manifest.json")
    )
    localized = dict(obs)
    localized["frames"] = frames
    localized["capture_manifest"] = manifest
    localized["screen"] = {**obs["screen"], "path": frames[-1]["path"]}
    return localized


def _create_and_reset(args, runner_options):
    """Create the environment and complete reset, waiting out transient
    refusals.

    A busy fleet answers creates with 503 (at capacity, or a worker died
    moments ago and routing has not caught up). That is back pressure, not
    failure: the client waits and retries until the admission deadline so a
    full fleet queues work instead of shedding it.
    """
    deadline = time.monotonic() + max(float(args.remote_timeout), 60.0)
    attempt = 0
    while True:
        attempt += 1
        env = None
        try:
            env = _make_env(args, runner_options)
            obs = env.reset(
                seed=args.seed,
                use_cache=args.use_cache,
                cache_level=args.cache_level,
                use_savevm=args.use_savevm,
            )
            return env, obs
        except Exception as error:
            if env is not None:
                try:
                    env.close()
                except Exception:
                    pass
            transient = _retryable_request_error(error) or "503" in str(error)
            if not transient or time.monotonic() >= deadline:
                raise
            wait = min(60.0, 5.0 * attempt)
            logger.info(
                "admission attempt %d refused (%s); retrying in %.0fs",
                attempt,
                str(error)[:120],
                wait,
            )
            time.sleep(wait)


def run(args: argparse.Namespace) -> int:
    temporal_mode = _temporal_mode(args)
    base_time_mode = world_time_mode(temporal_mode)
    mechanic_id, settings = _settings(args)
    play_time_limit_seconds = _play_time_limit_seconds(args, settings)
    runner_options = _runner_options(args, settings)
    agent_args = json.loads(args.agent_args)
    agent_args["temporal_mode"] = temporal_mode
    agent_args.setdefault("request_timeout_seconds", args.request_timeout_seconds)
    agent_args.setdefault("request_attempts", args.request_attempts)

    env, obs = _create_and_reset(args, runner_options)
    info: dict[str, Any] = {}
    agent = None
    episode_dir = None
    try:
        _require_frames(obs, where="initial")
        obs = _localize_observation(env, obs, args.client_episode_root)
        clock = _TaskClock(base_time_mode, getattr(args, "time_scale", 1.0))
        clock.observe(obs)
        max_steps = args.steps or env.max_steps or 50
        # Clock queries ride env.step now, so the environment-level step
        # counter includes them; the loop below owns the real turn budget.
        env.set_episode_limits(max_steps=1_000_000, timeout_sec=86400)
        episode_dir = _client_episode_dir(env, args.client_episode_root)
        timing_path = episode_dir / "realtime_timing.jsonl"

        agent_cls = _resolve_agent_class(args.agent, temporal_mode)
        agent_args.setdefault("max_steps", max_steps)
        agent = agent_cls(agent_args=agent_args, verbose=args.verbose, debug=args.debug)
        autonomous = bool(getattr(agent, "autonomous", False))
        description = _task_description(
            env,
            args,
            gateway_programs_allowed=autonomous,
        )
        # Select the frame_window entry by TYPE, as the worker-side runner
        # does. Base-preset composition prepends the preset's rgb_screen
        # (1920x1080) at observation[0], which mis-sized the agent for the
        # eight 1280x720 environments.
        frame_obs = next(
            (o for o in env.env_spec.observation if o.type == "frame_window"),
            env.env_spec.observation[0],
        )
        agent.init(
            task_description=description,
            display_resolution=frame_obs.resolution,
            save_path=episode_dir,
        )
        _write_record(timing_path, {
            "event": "setup",
            "mechanic_id": mechanic_id,
            "temporal_mode": temporal_mode,
            "time_mode": base_time_mode,
            "settings": settings.__dict__,
            "effective_runner_options": runner_options,
            "task_play_time_limit_seconds": play_time_limit_seconds,
            "task_play_time_limit_enabled": play_time_limit_seconds is not None,
            "clock": obs.get("time_status"),
            "task_time_live_estimated": base_time_mode == "live",
            "request_timeout_seconds": args.request_timeout_seconds,
            "request_attempts": args.request_attempts,
            "fast_io": args.fast_io,
            "remote_url": args.remote_url,
            "action_error_policy": "input-validation-feedback-v2",
            "request_retry_policy": {
                "single_layer": True,
                "total_attempt_limit": args.request_attempts,
                "retryable": [
                    "timeouts",
                    "connection/read/write errors",
                    "server disconnects and protocol errors",
                    "HTTP 408",
                    "HTTP 429",
                    "HTTP 5xx",
                ],
                "not_retryable": [
                    "safety blocks",
                    "authentication or authorization failures",
                    "invalid requests",
                ],
                "failed_attempts_consume_environment_steps": False,
            },
        })

        action_outputs = []
        turn = 0
        model_turn = 0
        reason = "step_limit"
        done = False

        if autonomous:
            model_started = time.perf_counter()
            agent.run_episode(env=env, task_description=description)
            model_ms = (time.perf_counter() - model_started) * 1000
            reason = "agent_completed"
            _, _reward, done, info = _mark_done(env, reason=reason)
            _write_record(timing_path, {
                "event": "autonomous_episode",
                "model_ms": model_ms,
                "task_time_ms": clock.now_ms(),
                "reason": reason,
            })

        while not autonomous and turn < max_steps and model_turn < max_steps and not done:
            before_model_ms = clock.now_ms()
            if _play_time_exhausted(before_model_ms, play_time_limit_seconds):
                reason = "play_time_limit"
                break

            model_started = time.perf_counter()
            actions, request_records = _call_agent_with_retry(
                clock,
                agent,
                obs,
                action_outputs,
                timeout_seconds=args.request_timeout_seconds,
                attempts=args.request_attempts,
            )
            model_turn += 1
            model_ms = (time.perf_counter() - model_started) * 1000
            after_model_ms = clock.now_ms()
            action_outputs = []
            action_records = []

            if base_time_mode == "live" and _play_time_exhausted(
                after_model_ms,
                play_time_limit_seconds,
            ):
                reason = "play_time_limit"
                _write_record(timing_path, {
                    "event": "turn",
                    "turn": turn,
                    "model_ms": model_ms,
                    "task_time_before_model_ms": before_model_ms,
                    "task_time_after_model_ms": after_model_ms,
                    "actions_applied": 0,
                    "stopped_before_action": True,
                    "request_attempts": request_records,
                })
                break

            for group in actions:
                actual_actions = _actions_with_schedule(
                    group, temporal_mode=temporal_mode
                )
                task_time_before_action_ms = clock.now_ms()
                action_started = time.perf_counter()
                # The runner owns the turn discipline. In paused mode it
                # delivers native input while task time stays frozen, waits
                # for Chromium to finish synchronous event dispatch, then
                # advances exactly one configured observation window.
                obs, _reward, done, info = _step_with_action_feedback(env, actual_actions)
                action_ms = (time.perf_counter() - action_started) * 1000
                _require_frames(obs, where=f"turn {turn + 1}")
                obs = _localize_observation(env, obs, args.client_episode_root)
                clock.observe(obs)
                # Paused mode: the last browser input-delivery boundary,
                # before the fixed observation window. Live mode: the raw
                # clock status the capture reported.
                clock_after_action = (
                    obs.get("action_delivery_status") or obs["time_status"]
                )
                task_time_after_execution_ms = float(
                    clock_after_action.get("task_time_ms") or 0
                )
                input_receipt = obs.get("input_receipt")
                if input_receipt is not None:
                    task_time_after_execution_ms = input_receipt["action_completed_at_s"] * 1000

                turn += 1
                action_result = info.get("action_result", {"action": "other", "output": "Executed the action"})
                if action_result.get("action") == "screenshot":
                    action_result["output"] = obs["screen"]["path"]
                action_outputs.append({**action_result, "tool_id": group.get("tool_id"), "obs": obs})
                action_records.append({
                    "input_receipt": input_receipt,
                    "tool_id": group.get("tool_id"),
                    "action_count": len(actual_actions),
                    "requested_execute_at_s": (
                        (group.get("metadata") or {}).get("execute_at_s")
                    ),
                    "action_ms": action_ms,
                    "task_time_before_action_ms": task_time_before_action_ms,
                    "task_time_after_execution_ms": task_time_after_execution_ms,
                    "task_time_delta_during_action_ms": (
                        task_time_after_execution_ms
                        - task_time_before_action_ms
                    ),
                    "clock_after_action": clock_after_action,
                    "action_delivery_statuses": obs.get(
                        "action_delivery_statuses", []
                    ),
                    "task_time_ms": obs["time"]["task_time_ms"],
                    "following_observation_manifest": obs[
                        "capture_manifest"
                    ],
                    "following_observation_screen": obs["screen"]["path"],
                })
                if action_result.get("error"):
                    action_records[-1].update(
                        outcome="rejected",
                        error=action_result["error"],
                        submitted_actions=actual_actions,
                        input_receipt=None,
                        task_time_after_execution_ms=None,
                        task_time_delta_during_action_ms=None,
                        action_delivery_statuses=[],
                    )
                    # The rejected group consumed this turn. Let the model
                    # correct it on its next turn, within the same step budget.
                    agent.done = False
                    break
                task_time_ms = float(obs["time"]["task_time_ms"] or 0)
                if (
                    done
                    or turn >= max_steps
                    or _play_time_exhausted(task_time_ms, play_time_limit_seconds)
                ):
                    if _play_time_exhausted(task_time_ms, play_time_limit_seconds):
                        reason = "play_time_limit"
                    break

            _write_record(timing_path, {
                "event": "turn",
                "turn": turn,
                "model_ms": model_ms,
                "task_time_before_model_ms": before_model_ms,
                "task_time_after_model_ms": after_model_ms,
                "request_attempts": request_records,
                "actions": action_records,
            })
            if getattr(agent, "done", False):
                reason = "agent_completed"
                break

        if not autonomous:
            _, _reward, done, info = _mark_done(env, reason=reason)
        logger.info("Episode finished: %s", info)
    finally:
        if episode_dir is None and env.episode_dir:
            episode_dir = _client_episode_dir(env, args.client_episode_root)
        # The summary is written only when the episode produced a verifier
        # verdict: a crashed episode leaves no summary and a nonzero exit,
        # so orchestrators can trust summary existence as completion.
        decided = bool(((info.get("verifier") or {}).get("decided")))
        if (
            episode_dir is not None
            and args.episode_summary_path is not None
            and decided
        ):
            args.episode_summary_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            attempts = _submission_counts(
                env, passed=bool((info.get("verifier") or {}).get("passed"))
            )
            args.episode_summary_path.write_text(
                json.dumps(
                    {
                        "episode_dir": str(episode_dir),
                        "mechanic_id": mechanic_id,
                        "task": args.task,
                        "seed": args.seed,
                        "temporal_mode": temporal_mode,
                        "time_mode": base_time_mode,
                        "attempts": attempts,
                        "info": info,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        # Benchmark artifacts (public state, witness files) are collected by
        # RealTimeRunner.stop() when the environment closes. Close after
        # the summary: a close failure against a dead worker must not
        # discard a completed episode's result.
        try:
            env.close()
        except Exception:
            logger.warning("env.close() failed", exc_info=True)

    if agent is not None:
        agent.finish(info=info)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
