"""RealTimeRunner: the Gym-Anything-RT world party for Gym-Anything.

This runner composes an inner VM runner (avf, qemu, docker, ...) resolved
through the Gym-Anything runner registry and owns every benchmark-specific
behavior that previously lived in the evaluation control layer:

- the puzzle clock (live/paused), driven through the in-guest time
  controller, exposed to core via ``supports_time_control`` and forwarded
  ``{"action": "time", "command": ...}`` action payloads;
- frame-window observations (the ``frame_window`` modality), captured by
  the in-guest observation script and returned through the standard
  ``capture_observation`` door;
- guest configuration (``GYM_ANYTHING_RT_*`` variables) derived from
  ``EnvSpec.runner_options`` and the episode seed;
- benchmark artifact collection into the episode directory.

Core never learns any of this: it forwards the modality, the actions, and
the options untouched. The inner runner never learns it either: it sees a
spec whose ``frame_window`` entry is rewritten to ``rgb_screen`` so display
geometry is configured exactly as before.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import shlex
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from gym_anything.runtime.runners import registry as runner_registry
from gym_anything.runtime.runners.base import BaseRunner
from gym_anything.specs import EnvSpec

logger = logging.getLogger(__name__)

FRAME_WINDOW_TYPE = "frame_window"

TIME_CONTROL_SCRIPT = "/workspace/shared_scripts/time_control.py"
INPUT_CONTROL_SCRIPT = "/workspace/shared_scripts/input_control.py"
CAPTURE_SCRIPT = "/workspace/shared_scripts/capture_observation_window.py"
GUEST_OBSERVATION_ROOT = "/tmp/gym_anything_rt_observations"

TIME_COMMANDS = {"status", "wait-ready", "pause", "settle-pause", "resume"}
TIME_MODES = {"live", "paused"}

COLLECTABLE_ARTIFACTS = {
    "current_task.json": "/tmp/gym_anything_rt/current_task.json",
    "public_state.json": "/tmp/gym_anything_rt/public_state.json",
    "parallel_grillmaster_witness_ledger.json": (
        "/tmp/gym_anything_rt/parallel_grillmaster_witness_ledger.json"
    ),
    "parallel_grillmaster_witness_clock.json": (
        "/tmp/gym_anything_rt/parallel_grillmaster_witness_clock.json"
    ),
    "slot_reel_witness_ledger.json": (
        "/tmp/gym_anything_rt/slot_reel_witness_ledger.json"
    ),
    "slot_reel_witness_clock.json": (
        "/tmp/gym_anything_rt/slot_reel_witness_clock.json"
    ),
}

_ALLOWED_OPTIONS = {
    "inner",
    "time_mode",
    "time_scale",
    "start_paused",
    "challenge_seed",
    "observation_window_ms",
    "frames_per_observation",
    "play_time_seconds",
}


def guest_json(env: Any, arguments: list) -> Dict[str, Any]:
    """Run a guest command through the environment's runner, parse the last
    JSON object line. Kept for evidence and probe tools that drive captures
    explicitly; evaluation itself goes through the runner's own methods."""
    command = " ".join(shlex.quote(str(part)) for part in arguments)
    output = env.runner.exec_capture(command)
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError(f"guest command returned no JSON object: {output}")


def capture_observation_window(
    env: Any,
    *,
    mode: str,
    duration_ms: int,
    frames_per_observation: int,
    turn: int,
    host_dir: Path,
    hold_paused: bool = False,
) -> Dict[str, Any]:
    """Explicit window capture for evidence and probe tools.

    ``hold_paused`` records the scheduled frame sequence during a frozen
    paused-mode hold instead of advancing the task. Evaluation does not call
    this; ``RealTimeRunner.capture_observation`` owns the schedule.
    """
    if mode not in TIME_MODES:
        raise ValueError(f"unsupported time mode: {mode}")
    if hold_paused and mode != "paused":
        raise ValueError("hold_paused is valid only for paused observations")
    if duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    if frames_per_observation < 1:
        raise ValueError("frames_per_observation must be positive")
    if turn < 0:
        raise ValueError("turn must be non-negative")

    host_dir = host_dir.resolve()
    guest_dir = f"{GUEST_OBSERVATION_ROOT}/turn-{turn:04d}"
    command = [
        "python3",
        CAPTURE_SCRIPT,
        "--mode",
        mode,
        "--duration-ms",
        str(duration_ms),
        "--frames",
        str(frames_per_observation),
        "--output-dir",
        guest_dir,
    ]
    if hold_paused:
        command.append("--hold-paused")
    manifest = guest_json(env, command)

    host_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, frame in enumerate(manifest["frames"]):
        host_path = host_dir / f"frame-{index:03d}.png"
        env.runner.copy_from(frame["path"], str(host_path))
        frames.append(
            {
                "path": str(host_path),
                "offset_ms": frame["offset_ms"],
                "target_offset_ms": frame["target_offset_ms"],
            }
        )

    manifest_path = host_dir / "guest-capture-manifest.json"
    env.runner.copy_from(f"{guest_dir}/manifest.json", str(manifest_path))
    time_status = manifest["time_status"]
    resolution = manifest.get("resolution")
    if (
        not isinstance(resolution, list)
        or len(resolution) != 2
        or not all(isinstance(value, int) and value > 0 for value in resolution)
    ):
        raise RuntimeError(f"capture returned an invalid resolution: {resolution!r}")
    configured_resolution = list(env.env_spec.observation[0].resolution)
    if resolution != configured_resolution:
        raise RuntimeError(
            "capture resolution does not match the environment: "
            f"captured {resolution}, configured {configured_resolution}"
        )
    return {
        "screen": {
            "path": frames[-1]["path"],
            "format": "png",
            "resolution": resolution,
        },
        "frames": frames,
        "capture_manifest": str(manifest_path),
        "time": {
            "mode": mode,
            "task_time_ms": time_status.get("task_time_ms"),
            "observation_window_ms": duration_ms,
            "frames_per_observation": frames_per_observation,
        },
    }


def _inner_spec_for(spec: EnvSpec) -> EnvSpec:
    """The spec view the inner VM runner receives.

    The outer spec declares ``frame_window`` so core delegates observation
    capture to this runner. The inner runner still needs ``rgb_screen`` to
    configure display geometry (resolution, fps), so the entry is rewritten
    in its copy.
    """
    inner = copy.deepcopy(spec)
    for entry in inner.observation:
        if entry.type == FRAME_WINDOW_TYPE:
            entry.type = "rgb_screen"
    return inner


class RealTimeRunner(BaseRunner):
    """Composing world runner for Gym-Anything-RT puzzle environments."""

    def __init__(self, spec: EnvSpec):
        super().__init__(spec)
        options = spec.runner_options or {}
        # The base preset injects an rgb_screen observation, and the preset
        # merge keeps it alongside frame_window. This world owns the screen
        # through its frame windows, so it declines core's per-step
        # screenshot convenience by removing the merged-in entry. Otherwise
        # core would deliver its own stale "screen" ahead of the window's
        # final frame.
        if any(entry.type == FRAME_WINDOW_TYPE for entry in spec.observation):
            spec.observation[:] = [
                entry for entry in spec.observation if entry.type != "rgb_screen"
            ]
        self._inner_spec = _inner_spec_for(spec)
        inner_ref = options.get("inner")
        if inner_ref:
            ref = inner_ref if runner_registry.is_locator(inner_ref) else inner_ref.lower()
            inner_cls = runner_registry.resolve_runner_class(ref, self._inner_spec)
            if inner_cls is None:
                raise runner_registry.RunnerRegistryError(
                    f"runner_options.inner {inner_ref!r} does not resolve to a runner"
                )
        else:
            inner_cls = runner_registry.autodetect_runner_class(self._inner_spec)
        if inner_cls is type(self):
            raise runner_registry.RunnerRegistryError(
                "runner_options.inner must name the VM runner, not gym_anything_rt itself"
            )
        self.inner: BaseRunner = inner_cls(self._inner_spec)
        logger.info("RealTimeRunner wraps %s", type(self.inner).__name__)

        self._context: Dict[str, Any] = {}
        self._turn = 0
        self._ready = False
        self._live_started = False
        self._episode_started_wall_ms: Optional[float] = None
        self._clock_running = False
        self._native_capture = None
        self._bootstrap_done = False
        self._resolved_time_mode: Optional[str] = None
        self.last_time_status: Dict[str, Any] = {}
        self.last_action_result: Optional[Dict[str, Any]] = None
        self.last_input_status: Optional[Dict[str, Any]] = None
        self._pending_input_statuses: list[Dict[str, Any]] = []
        # Ordered (command, result) clock transitions for this episode.
        self.clock_log: list = []
        self.input_log: list = []
        self._input_service = None
        self._input_closed = False
        self._last_input_receipt = None
        self._input_start_lock = threading.Lock()
        self._input_step_lock = threading.Lock()
        self._input_requests = {}

    # --- class-level facts ------------------------------------------------

    @classmethod
    def validate_options(cls, spec: EnvSpec) -> list:
        options = spec.runner_options or {}
        errors = [
            f"unknown runner_options key: {key!r}"
            for key in options
            if key not in _ALLOWED_OPTIONS
        ]
        mode = options.get("time_mode")
        if mode is not None and mode not in TIME_MODES:
            errors.append(f"time_mode must be one of {sorted(TIME_MODES)}, got {mode!r}")
        scale = options.get("time_scale", 1.0)
        if (isinstance(scale, bool) or not isinstance(scale, (int, float))
                or not math.isfinite(scale) or not 0 < scale <= 1):
            errors.append(f"time_scale must be finite and in (0, 1], got {scale!r}")
        inner = options.get("inner")
        if inner is not None and not runner_registry.is_known_reference(str(inner)):
            errors.append(f"runner_options.inner {inner!r} is not a known runner reference")
        for key in ("observation_window_ms", "frames_per_observation", "play_time_seconds"):
            value = options.get(key)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"{key} must be a non-negative integer, got {value!r}")
        frames = options.get("frames_per_observation")
        if frames is not None and frames < 1:
            errors.append("frames_per_observation must be positive")
        seed = options.get("challenge_seed")
        if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
            errors.append(f"challenge_seed must be an integer, got {seed!r}")
        start_paused = options.get("start_paused")
        if start_paused is not None and not isinstance(start_paused, bool):
            errors.append(f"start_paused must be a boolean, got {start_paused!r}")
        return errors

    @classmethod
    def doctor_status(cls) -> Dict[str, Any]:
        # This wrapper has no host dependencies of its own; the inner VM
        # runner's probe (avf, qemu, docker) covers the host. A non-empty
        # reason means unavailable by convention, so it stays None here.
        return {"available": True, "reason": None, "deps": {}}

    @classmethod
    def platform_priority(cls) -> int:
        return 0

    @classmethod
    def autodetect_eligible(cls, spec=None) -> bool:
        return False

    # --- option accessors -------------------------------------------------

    @property
    def time_mode(self) -> str:
        resolved = getattr(self, "_resolved_time_mode", None)
        if resolved:
            return resolved
        return (self.spec.runner_options or {}).get("time_mode", "paused")

    def _task_condition_time_mode(self, task_id) -> Optional[str]:
        """The task's declared real_time condition, read from the task folder
        on this host via the tasks mount. This is how a run condition reaches
        a worker that resolved the benchmark by name: the condition is task
        identity, covered by the task content digest."""
        if not task_id:
            return None
        task_dir = str(task_id).split("@", 1)[0]
        tasks_source = next(
            (
                mount.source
                for mount in self.spec.mounts
                if mount.target == "/workspace/tasks"
            ),
            None,
        )
        if not tasks_source:
            return None
        try:
            task = json.loads(
                (Path(tasks_source) / task_dir / "task.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            return None
        mode = ((task.get("metadata") or {}).get("control_condition") or {}).get(
            "real_time"
        )
        return mode if mode in TIME_MODES else None

    @property
    def observation_window_ms(self) -> int:
        value = (self.spec.runner_options or {}).get("observation_window_ms")
        if value is None:
            raise ValueError("runner_options.observation_window_ms is required to capture")
        return int(value)

    @property
    def frames_per_observation(self) -> int:
        value = (self.spec.runner_options or {}).get("frames_per_observation")
        if value is None:
            raise ValueError("runner_options.frames_per_observation is required to capture")
        return int(value)

    # --- episode participation -------------------------------------------

    def on_episode_start(self, context: Dict[str, Any]) -> None:
        if self._native_capture is not None:
            self._native_capture.close()
            self._native_capture = None
        if self._input_service is not None:
            self._input_service.close()
            self._input_service = None
        self._input_requests = {}
        self._input_closed = False
        self._last_input_receipt = None
        self._context = dict(context)
        if self._context.get("episode_dir"):
            # Frame paths travel to remote clients that fetch them by this
            # string; a cwd-relative episode dir would not survive the trip.
            self._context["episode_dir"] = str(
                Path(self._context["episode_dir"]).resolve()
            )
        self._turn = 0
        self._ready = False
        self._live_started = False
        self._episode_started_wall_ms = None
        self._clock_running = False
        self._bootstrap_done = False
        self.last_time_status = {}
        self.last_action_result = None
        self.last_input_status = None
        self._pending_input_statuses = []
        self.clock_log = []
        self.input_log = []

        options = self.spec.runner_options or {}
        # Precedence: an explicit local run option, then the task's declared
        # condition, then the paused default.
        self._resolved_time_mode = (
            options.get("time_mode")
            or self._task_condition_time_mode(context.get("task_id"))
            or "paused"
        )
        guest_env: Dict[str, str] = {
            "GYM_ANYTHING_RT_TIME_MODE": self.time_mode,
            "GYM_ANYTHING_RT_TIME_SCALE": str(options.get("time_scale", 1.0)),
            "GYM_ANYTHING_RT_START_PAUSED": (
                "1" if options.get("start_paused", True) else "0"
            ),
        }
        seed = options.get("challenge_seed", context.get("seed"))
        if seed is not None:
            guest_env["GYM_ANYTHING_RT_CHALLENGE_SEED"] = str(seed)
            guest_env["SEED"] = str(seed)
        for spec in (self.spec, self._inner_spec):
            spec.security.resolved_env.update(guest_env)
        self.inner.on_episode_start(context)

    def supports_time_control(self) -> bool:
        return True

    # --- the clock --------------------------------------------------------

    def _guest_json(self, arguments: list) -> Dict[str, Any]:
        command = " ".join(shlex.quote(str(part)) for part in arguments)
        output = self.inner.exec_capture(command)
        for line in reversed(output.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise RuntimeError(f"guest command returned no JSON object: {output}")

    def time_command(self, command: str) -> Dict[str, Any]:
        if command not in TIME_COMMANDS:
            raise ValueError(f"unsupported time command: {command}")
        result = self._guest_json(
            ["python3", TIME_CONTROL_SCRIPT, command, "--timeout", "120"]
        )
        if command == "resume":
            self._clock_running = True
        elif command in ("pause", "settle-pause"):
            self._clock_running = False
        self.last_time_status = result
        self.clock_log.append({"command": command, "result": result})
        return result

    def _ensure_ready(self) -> None:
        if not self._ready:
            self.time_command("wait-ready")
            self._ready = True

    def _ensure_live_started(self) -> None:
        if self.time_mode == "live" and not self._live_started:
            status = self.time_command("resume")
            native_date_ms = status.get("native_date_ms")
            task_time_ms = status.get("task_time_ms")
            if native_date_ms is None or task_time_ms is None:
                raise RuntimeError(
                    "live clock start did not report native_date_ms and task_time_ms"
                )
            # This is the wall-clock instant at which the browser's task clock
            # read zero. It is fixed once per episode and precedes every live
            # frame and action; observations consume this origin, never define it.
            self._episode_started_wall_ms = (
                float(native_date_ms) - float(task_time_ms) / float(status.get("time_scale", 1.0))
            )
            self._live_started = True

    def input_command(
        self,
        command: str,
        *,
        category: Optional[str] = None,
        arm_sequence: Optional[int] = None,
        required: bool = True,
    ) -> Dict[str, Any]:
        if command not in {"arm", "complete", "cancel", "status"}:
            raise ValueError(f"unsupported input command: {command}")
        arguments = ["python3", INPUT_CONTROL_SCRIPT, command, "--timeout", "30"]
        if category is not None:
            arguments.extend(["--category", category])
        if arm_sequence is not None:
            arguments.extend(["--arm-sequence", str(arm_sequence)])
        if command == "arm":
            arguments.append("--required" if required else "--no-required")
        result = self._guest_json(arguments)
        self.last_input_status = result
        self.input_log.append({"command": command, "result": result})
        return result

    @staticmethod
    def _input_category(action: Dict[str, Any]) -> Optional[str]:
        has_mouse = bool(action.get("mouse"))
        has_keyboard = bool(action.get("keyboard"))
        if has_mouse and has_keyboard:
            return "mixed"
        if has_mouse:
            return "mouse"
        if has_keyboard:
            return "keyboard"
        return None

    @staticmethod
    def _input_receipt_required(action: Dict[str, Any]) -> bool:
        mouse = action.get("mouse") or {}
        keyboard = action.get("keyboard") or {}
        # Moving to the position already held is a valid no-op on transports
        # that cannot guarantee an observable motion event. Every click,
        # button, wheel, drag, and non-empty keyboard action must be observed
        # by Chromium before the task clock can advance.
        if mouse and not keyboard and set(mouse) <= {"move"}:
            return False
        if keyboard:
            return any(bool(value) for value in keyboard.values())
        return bool(mouse)

    # --- actions ----------------------------------------------------------

    def prepare_input(self):
        if self.time_mode != "live":
            raise ValueError("sandbox input scheduling requires live mode")
        with self._input_start_lock:
            if self._input_closed:
                raise RuntimeError("episode input is closed")
            self._ensure_ready()
            self._ensure_live_started()
            if self._input_service is None:
                from gym_anything_rt.scheduled_input import SandboxInput
                self._input_service = SandboxInput(self.inner, self._episode_started_wall_ms)
        return self._input_service

    def close_input(self):
        with self._input_start_lock:
            self._input_closed = True
            if self._input_service is not None:
                self._input_service.close()
                self._input_service = None

    def execute_input_step(self, env, actions, execute_at_s=None, *, request_id):
        from concurrent.futures import Future
        signature = json.dumps([actions, execute_at_s], sort_keys=True, allow_nan=False)
        with self._input_step_lock:
            previous = self._input_requests.get(request_id)
            if previous is not None:
                if previous[0] != signature:
                    raise ValueError("request id reused with different input")
                future, owner = previous[1], False
            else:
                future, owner = Future(), True
                self._input_requests[request_id] = (signature, future)
        if not owner:
            return future.result(timeout=3660)
        try:
            receipt = self.prepare_input().execute(actions, execute_at_s, request_id=request_id)
            # Core still owns step accounting, trajectory logging and limits.
            # Waiting for the guest never holds this short accounting lock.
            with self._input_step_lock:
                _, reward, done, info = env.step([{
                    "action": "input_receipt", "actions": actions, "receipt": receipt,
                }], capture_observation=False, settle_after_actions=False)
            result = {"receipt": receipt, "reward": reward, "done": done, "info": info}
            future.set_result(result)
            return result
        except BaseException as error:
            future.set_exception(error)
            raise

    def inject_action(self, action: Dict[str, Any]):
        kind = action.get("action") if isinstance(action, dict) else None
        if kind == "input_receipt":
            self.last_action_result = action["receipt"]
            self._last_input_receipt = action["receipt"]
            self.input_log.append(dict(action))
            return self.last_action_result
        if kind == "scheduled_input":
            if self.inner.compatibility().runner != "sandweave":
                target_ms = action.get("wall_time_ms")
                if target_ms is None:
                    self._ensure_ready()
                    self._ensure_live_started()
                    target_ms = self._episode_started_wall_ms + float(action["execute_at_s"]) * 1000
                self.inject_action({"action": "wait_until", "wall_time_ms": target_ms})
                for item in action["actions"]:
                    self.inject_action(item)
                return
            target = action.get("execute_at_s")
            if target is None and "wall_time_ms" in action:
                self._ensure_ready()
                self._ensure_live_started()
                target = (float(action["wall_time_ms"]) - self._episode_started_wall_ms) / 1000
            receipt = self.prepare_input().execute(action["actions"], target)
            self.last_action_result = receipt
            self._last_input_receipt = receipt
            self.input_log.append({"action": "input_receipt", "actions": action["actions"], "receipt": receipt})
            return receipt
        if kind == "time":
            self._ensure_ready()
            result = self.time_command(str(action.get("command")))
            self.last_action_result = result
            # Returned dicts surface in env.step info["world_action_results"],
            # locally and over the remote wire.
            return result
        if kind == "wait":
            seconds = float(action.get("time", 1.0))
            self._ensure_ready()
            if self.time_mode == "live":
                self._ensure_live_started()
            # In paused mode an explicit wall wait remains frozen; the one
            # configured observation window is the only task-time advance.
            time.sleep(seconds)
            return
        if kind == "wait_until":
            if self.time_mode != "live":
                raise ValueError("wait_until is supported only in live mode")
            target_wall_ms = float(action["wall_time_ms"])
            if not math.isfinite(target_wall_ms) or target_wall_ms < 0:
                raise ValueError("wait_until wall_time_ms must be finite and non-negative")
            self._ensure_ready()
            self._ensure_live_started()
            result = self._guest_json(
                [
                    "python3",
                    TIME_CONTROL_SCRIPT,
                    "wait-until",
                    "--wall-time-ms",
                    repr(target_wall_ms),
                ]
            )
            self.last_action_result = result
            return result
        self._ensure_ready()
        if self.time_mode == "live":
            self._ensure_live_started()
            if self._input_service is None:
                self.inner.inject_action(action)
            else:
                self.last_action_result = self._input_service.execute([action])
                self._last_input_receipt = self.last_action_result
            return

        if self._clock_running:
            self.time_command("pause")
        category = self._input_category(action)
        if category is None:
            self.inner.inject_action(action)
            return
        required = self._input_receipt_required(action)
        armed = self.input_command("arm", category=category, required=required)
        arm_sequence = int(armed["arm_sequence"])
        try:
            self.inner.inject_action(action)
        except Exception:
            try:
                self.input_command("cancel", arm_sequence=arm_sequence)
            except Exception:
                logger.warning("Could not cancel failed browser input barrier", exc_info=True)
            raise
        delivered = self.input_command("complete", arm_sequence=arm_sequence)
        if required and not delivered.get("receipt_confirmed"):
            raise RuntimeError(
                "native action reached the input transport but Chromium did not "
                f"confirm a {category} event: {delivered}"
            )
        self._pending_input_statuses.append(delivered)

    # --- observations -----------------------------------------------------

    def capture_observation(self) -> Dict[str, Any]:
        if not self._context.get("episode_dir"):
            raise RuntimeError("no episode context; capture requires on_episode_start")
        self._ensure_ready()
        episode_dir = Path(self._context["episode_dir"])

        if not self._bootstrap_done:
            # Core captures one observation mid-reset, right after the
            # pre_task hook, as came-up evidence. That capture must not
            # spend task time, so it is a frozen hold-paused window outside
            # the turn numbering.
            self._bootstrap_done = True
            observation = self._capture_window(
                mode="paused",
                hold_paused=True,
                host_dir=episode_dir / "observations" / "bootstrap",
            )
            observation["bootstrap"] = True
            observation["settle_status"] = None
            return observation

        input_statuses = list(self._pending_input_statuses)
        if self.time_mode == "live":
            self._ensure_live_started()
        elif self._clock_running:
            self.time_command("pause")

        observation = self._capture_window(
            mode=self.time_mode,
            hold_paused=False,
            host_dir=episode_dir / "observations" / f"turn-{self._turn:04d}",
        )
        self._turn += 1
        self._pending_input_statuses = []
        observation["settle_status"] = None
        observation["action_delivery_statuses"] = input_statuses
        observation["action_delivery_status"] = (
            input_statuses[-1] if input_statuses else None
        )
        return observation

    def _capture_window(
        self, *, mode: str, hold_paused: bool, host_dir: Path
    ) -> Dict[str, Any]:
        native = (getattr(self, "_fast_io", False)
                  and getattr(self.inner, "_sandbox", None) is not None)
        if native and mode == "live" and (hold_paused or self.observation_window_ms != 0 or self.frames_per_observation != 1):
            raise RuntimeError("native live capture requires one instantaneous frame")
        if native:
            from .native_paused_capture import NativePausedCapture
            if self._native_capture is None:
                sandbox = getattr(self.inner, "_sandbox", None)
                if sandbox is None:
                    raise RuntimeError("native live capture requires a Sandweave inner runner")
                self._native_capture = NativePausedCapture(
                    sandbox, image_format=self.spec.runner_options.get("capture_image_format", "jpeg")
                )
            if mode == "paused":
                manifest = self._native_capture.capture_window(
                    host_dir, duration_ms=self.observation_window_ms,
                    count=self.frames_per_observation, hold_paused=hold_paused,
                )
            else:
                manifest = self._native_capture.capture(host_dir)
            frames = manifest["frames"]
            manifest_path = host_dir / "guest-capture-manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            return self._observation_from_manifest(manifest, frames, manifest_path, mode)

        guest_dir = f"{GUEST_OBSERVATION_ROOT}/{host_dir.name}"
        command = [
            "python3",
            CAPTURE_SCRIPT,
            "--mode",
            mode,
            "--duration-ms",
            str(self.observation_window_ms),
            "--frames",
            str(self.frames_per_observation),
            "--output-dir",
            guest_dir,
        ]
        if hold_paused:
            command.append("--hold-paused")
        manifest = self._guest_json(command)

        host_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for index, frame in enumerate(manifest["frames"]):
            host_path = host_dir / f"frame-{index:03d}.png"
            self.inner.copy_from(frame["path"], str(host_path))
            frames.append(
                {
                    "path": str(host_path),
                    "offset_ms": frame["offset_ms"],
                    "target_offset_ms": frame["target_offset_ms"],
                }
            )
        manifest_path = host_dir / "guest-capture-manifest.json"
        self.inner.copy_from(f"{guest_dir}/manifest.json", str(manifest_path))

        return self._observation_from_manifest(manifest, frames, manifest_path, mode)

    def _observation_from_manifest(self, manifest, frames, manifest_path, mode):
        resolution = manifest.get("resolution")
        if (
            not isinstance(resolution, list)
            or len(resolution) != 2
            or not all(isinstance(value, int) and value > 0 for value in resolution)
        ):
            raise RuntimeError(f"capture returned an invalid resolution: {resolution!r}")
        configured = next(
            (
                list(entry.resolution)
                for entry in self.spec.observation
                if entry.type == FRAME_WINDOW_TYPE and entry.resolution
            ),
            None,
        )
        if configured is not None and resolution != configured:
            raise RuntimeError(
                "capture resolution does not match the environment: "
                f"captured {resolution}, configured {configured}"
            )

        time_status = manifest["time_status"]
        self.last_time_status = time_status
        return {
            "screen": {
                "path": frames[-1]["path"],
                "format": manifest.get("image_mime_type", "image/png").split("/")[-1],
                "resolution": resolution,
            },
            "frames": frames,
            "capture_manifest": str(manifest_path),
            "time": {
                "mode": mode,
                "task_time_ms": time_status.get("task_time_ms"),
                "episode_started_wall_ms": self._episode_started_wall_ms,
                "observation_window_ms": self.observation_window_ms,
                "frames_per_observation": self.frames_per_observation,
            },
            # Raw clock report for callers that need it without another
            # guest roundtrip; it also crosses the remote wire this way.
            "time_status": time_status,
            "input_receipt": self._last_input_receipt,
        }

    # --- artifacts --------------------------------------------------------

    def collect_artifacts(self) -> None:
        episode_dir = self._context.get("episode_dir")
        if not episode_dir:
            return
        for name, guest_path in COLLECTABLE_ARTIFACTS.items():
            try:
                present = self.inner.exec_capture(
                    f"test -s {shlex.quote(guest_path)} && echo present"
                )
                if "present" not in present.split():
                    continue
                self.inner.copy_from(guest_path, str(Path(episode_dir) / name))
            except Exception:
                continue

    # --- lifecycle delegation ---------------------------------------------

    def start(self, seed: Optional[int] = None) -> None:
        self.inner.start(seed)

    def stop(self) -> None:
        try:
            if self._native_capture is not None:
                self._native_capture.close()
                self._native_capture = None
        except Exception:
            logger.warning("Could not close fast-I/O clock reader", exc_info=True)
        try:
            self.close_input()
        except Exception:
            logger.warning("Could not close Gym-Anything-RT input service", exc_info=True)
        try:
            self.collect_artifacts()
        except Exception:
            logger.warning("Could not collect Gym-Anything-RT artifacts", exc_info=True)
        finally:
            self.inner.stop()

    def run_reset(self, reset_script: str, seed: Optional[int] = None) -> None:
        self.inner.run_reset(reset_script, seed)

    def run_task_init(self, init_script: str) -> None:
        self.inner.run_task_init(init_script)

    def run_hook(self, command: str, *, stage: str,
                 timeout: Optional[int] = None, use_pty: bool = True) -> int:
        if stage == "post_task":
            self.close_input()
        return self.inner.run_hook(command, stage=stage, timeout=timeout, use_pty=use_pty)

    def set_reporter(self, reporter) -> None:
        super().set_reporter(reporter)
        self.inner.set_reporter(reporter)

    def set_fast_io(self, enabled: bool) -> None:
        super().set_fast_io(enabled)
        self.inner.set_fast_io(enabled)

    # --- capability queries (owned by the inner world) ----------------------

    def supports_live_recording(self) -> bool:
        return self.inner.supports_live_recording()

    def supports_native_recording(self) -> bool:
        capability = getattr(self.inner, "supports_native_recording", None)
        return bool(capability()) if callable(capability) else False

    def supports_checkpoint_caching(self) -> bool:
        return self.inner.supports_checkpoint_caching()

    def supports_savevm(self) -> bool:
        return self.inner.supports_savevm()

    def supports_fast_io(self) -> bool:
        return self.inner.supports_fast_io()

    def acks_input_delivery(self) -> bool:
        return self.inner.acks_input_delivery()

    def get_platform_family(self):
        return self.inner.get_platform_family()

    def get_runtime_info(self):
        return self.inner.get_runtime_info()

    # --- guest access delegation -------------------------------------------

    def exec(self, cmd: str, env: Optional[Dict[str, str]] = None,
             user: Optional[str] = None, use_pty: bool = True, timeout: int = 600) -> int:
        return self.inner.exec(cmd, env=env, user=user, use_pty=use_pty, timeout=timeout)

    def exec_async(self, cmd: str, env: Optional[Dict[str, str]] = None, stdout=None, stderr=None):
        return self.inner.exec_async(cmd, env=env, stdout=stdout, stderr=stderr)

    def exec_capture(self, cmd: str) -> str:
        return self.inner.exec_capture(cmd)

    def exec_capture_bytes(self, cmd: str) -> bytes:
        return self.inner.exec_capture_bytes(cmd)

    def put_file(self, host_path) -> str:
        return self.inner.put_file(host_path)

    def to_container_path(self, host_path):
        return self.inner.to_container_path(host_path)

    def copy_to(self, host_src: str, container_dst: str) -> None:
        self.inner.copy_to(host_src, container_dst)

    def copy_from(self, container_src: str, host_dst: str) -> None:
        self.inner.copy_from(container_src, host_dst)

    def capture_screenshot(self, host_path) -> bool:
        return self.inner.capture_screenshot(host_path)

    def capture_screenshot_image(self):
        return self.inner.capture_screenshot_image()

    def capture_audio_raw(self, duration_sec: float, rate: int, channels: int) -> bytes:
        return self.inner.capture_audio_raw(duration_sec, rate, channels)

    def capture_ui_tree(self) -> str:
        return self.inner.capture_ui_tree()

    def save_state(self, save_paths) -> str:
        return self.inner.save_state(save_paths)

    def load_state(self, snapshot_container_path: str) -> None:
        self.inner.load_state(snapshot_container_path)

    def set_checkpoint_key(self, cache_level: str, task_id: Optional[str] = None,
                           use_savevm: bool = False) -> None:
        self.inner.set_checkpoint_key(cache_level, task_id=task_id, use_savevm=use_savevm)

    def checkpoint_exists(self) -> bool:
        return self.inner.checkpoint_exists()

    def create_checkpoint(self) -> bool:
        return self.inner.create_checkpoint()

    def start_from_checkpoint(self, seed: Optional[int] = None) -> bool:
        return self.inner.start_from_checkpoint(seed)
