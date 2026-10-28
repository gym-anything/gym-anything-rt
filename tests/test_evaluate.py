from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from gym_anything_rt.runner import capture_observation_window
from gym_anything_rt.agents.corpus import evaluation_pairs
from gym_anything_rt.agents.qwen35vl import (
    RealTimeQwen35VLAgent,
    call_qwen_with_null_response_retry,
    image_from_screen,
    observation_frames,
)
from gym_anything_rt import evaluate as evaluator


class JsonResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def json(self) -> dict:
        return self.payload


def test_evaluator_parser_accepts_gym_remote_and_fast_io_options() -> None:
    args = evaluator.build_parser().parse_args(
        [
            "--env-dir",
            "environment",
            "--task",
            "task",
            "--agent",
            "Qwen35VLAgent",
            "--agent-args",
            "{}",
            "--time-mode",
            "paused",
            "--fast-io",
            "--remote-url",
            "http://master:5000",
            "--remote-worker-reset-policy",
            "baseline_setup",
        ]
    )
    assert args.fast_io is True
    assert args.remote_url == "http://master:5000"
    assert args.remote_worker_reset_policy == "baseline_setup"
    assert args.temporal_mode == "paused"


def test_evaluator_parser_accepts_four_temporal_modes() -> None:
    parser = evaluator.build_parser()
    for mode in (
        "paused",
        "live",
        "live_timestamped",
        "live_timestamped_execution",
    ):
        args = parser.parse_args(
            [
                "--env-dir",
                "environment",
                "--task",
                "task",
                "--agent",
                "Qwen35VLAgent",
                "--agent-args",
                "{}",
                "--temporal-mode",
                mode,
            ]
        )
        assert args.temporal_mode == mode


def test_temporal_modes_map_to_two_runner_clock_modes() -> None:
    settings = SimpleNamespace(
        observation_window_ms=800,
        frames_per_observation=6,
        play_time_seconds=90,
    )
    for temporal_mode, expected in (
        ("paused", "paused"),
        ("live", "live"),
        ("live_timestamped", "live"),
        ("live_timestamped_execution", "live"),
    ):
        args = SimpleNamespace(temporal_mode=temporal_mode)
        options = evaluator._runner_options(args, settings)
        assert options["time_mode"] == expected
        assert options["observation_window_ms"] == (
            800 if temporal_mode == "paused" else 0
        )
        assert options["frames_per_observation"] == (
            6 if temporal_mode == "paused" else 1
        )


@pytest.mark.parametrize("inner", ["sandweave", "qemu", "example.runner:Runner"])
@pytest.mark.parametrize("mode", evaluator.TEMPORAL_MODES)
def test_inner_runner_selection_preserves_temporal_mode(inner, mode) -> None:
    args = evaluator.build_parser().parse_args([
        "--env-dir", "environment", "--task", "task",
        "--agent", "CodexCliAgent", "--agent-args", "{}",
        "--temporal-mode", mode, "--inner-runner", inner,
    ])
    settings = SimpleNamespace(
        observation_window_ms=800, frames_per_observation=6, play_time_seconds=90,
    )
    options = evaluator._runner_options(args, settings)
    assert options["inner"] == inner
    assert options["time_mode"] == ("paused" if mode == "paused" else "live")
    assert options["frames_per_observation"] == (6 if mode == "paused" else 1)
    assert options["observation_window_ms"] == (800 if mode == "paused" else 0)
    args.inner_runner = None
    assert "inner" not in evaluator._runner_options(args, settings)


def test_codex_sandbox_uses_astra_compatible_cli() -> None:
    from gym_anything_rt.agents.codex_cli import RealTimeCodexCliAgent

    assert RealTimeCodexCliAgent.sandbox_install == (
        "npm install -g @openai/codex@0.153.3"
    )


def test_evaluator_can_disable_the_task_clock_limit() -> None:
    args = evaluator.build_parser().parse_args(
        [
            "--env-dir",
            "environment",
            "--task",
            "task",
            "--agent",
            "Qwen35VLAgent",
            "--agent-args",
            "{}",
            "--time-mode",
            "live",
            "--no-play-time-limit",
        ]
    )
    settings = SimpleNamespace(play_time_seconds=120)
    assert evaluator._play_time_limit_seconds(args, settings) is None
    assert evaluator._play_time_exhausted(10**12, None) is False


def test_evaluator_keeps_the_configured_task_clock_limit_by_default() -> None:
    args = evaluator.build_parser().parse_args(
        [
            "--env-dir",
            "environment",
            "--task",
            "task",
            "--agent",
            "Qwen35VLAgent",
            "--agent-args",
            "{}",
            "--time-mode",
            "paused",
        ]
    )
    settings = SimpleNamespace(play_time_seconds=120)
    assert evaluator._play_time_limit_seconds(args, settings) == 120
    assert evaluator._play_time_exhausted(119_999, 120) is False
    assert evaluator._play_time_exhausted(120_000, 120) is True


def test_evaluator_sends_the_controlled_task_instruction_to_the_agent() -> None:
    env = SimpleNamespace(
        task_spec=SimpleNamespace(
            natural_language="Solve the L1 task.",
            description="Generic environment description.",
        )
    )
    args = SimpleNamespace(env_dir="unused", task="unused")
    description = evaluator._task_description(env, args)
    assert description.startswith("Solve the L1 task.\n\n")
    assert evaluator.VISIBLE_UI_ONLY_RULE in description


def test_evaluator_falls_back_to_task_description() -> None:
    env = SimpleNamespace(
        task_spec=SimpleNamespace(
            natural_language=None,
            description="Fallback task description.",
        )
    )
    args = SimpleNamespace(env_dir="unused", task="unused")
    assert evaluator._task_description(env, args).startswith(
        "Fallback task description.\n\n"
    )


def test_autonomous_instruction_allows_programs_only_through_gateway() -> None:
    env = SimpleNamespace(
        task_spec=SimpleNamespace(
            natural_language="Solve the task.",
            description="Fallback.",
        )
    )
    args = SimpleNamespace(env_dir="unused", task="unused")

    description = evaluator._task_description(
        env,
        args,
        gateway_programs_allowed=True,
    )

    assert "write programs inside the isolated agent sandbox" in description
    assert "screenshots returned by the action gateway" in description
    assert "Do not connect to the task VM" in description
    assert evaluator.VISIBLE_UI_ONLY_RULE not in description


def test_make_env_merges_runner_options_locally(monkeypatch) -> None:
    sentinel = object()
    received = {}

    def fake_from_config(env_dir, task_id, overrides, fast_io):
        received.update(
            env_dir=env_dir, task_id=task_id, overrides=overrides, fast_io=fast_io
        )
        return sentinel

    import gym_anything.api

    monkeypatch.setattr(gym_anything.api, "from_config", fake_from_config)
    args = SimpleNamespace(
        remote_url=None,
        env_dir="environment",
        task="task",
        fast_io=True,
    )
    options = {"inner": "sandweave", "time_mode": "paused", "observation_window_ms": 800}
    assert evaluator._make_env(args, options) is sentinel
    assert received == {
        "env_dir": "environment",
        "task_id": "task",
        "overrides": {"runner_options": options},
        "fast_io": True,
    }


def test_make_env_creates_remote_by_benchmark_name_with_overrides(monkeypatch) -> None:
    sentinel = object()
    received = {}

    def fake_from_benchmark(**kwargs):
        received.update(kwargs)
        return sentinel

    from gym_anything.remote import RemoteGymEnv

    monkeypatch.setattr(RemoteGymEnv, "from_benchmark", fake_from_benchmark)
    args = SimpleNamespace(
        remote_url="http://master:5000",
        env_dir="benchmarks/gym_anything_rt/environments/rotating_keyboard_v2_env",
        task="rotating_keyboard_v2_d5_full_seed_0001",
        remote_timeout=123,
        remote_worker_reset_policy="baseline_setup",
        fast_io=True,
        observation_window_ms=None,
        frames_per_observation=None,
    )
    options = {
        "inner": "sandweave",
        "time_mode": "live",
        "observation_window_ms": 0,
        "frames_per_observation": 1,
    }
    assert evaluator._make_env(args, options) is sentinel
    assert received == {
        "remote_url": "http://master:5000",
        "benchmark": "gym_anything_rt",
        "env_name": "rotating_keyboard_v2_env",
        "task_id": "rotating_keyboard_v2_d5_full_seed_0001",
        "timeout": 123,
        "worker_reset_policy": "baseline_setup",
        "fast_io": True,
        "overrides": {"runner_options": options},
    }


def test_task_clock_paused_reads_observations_and_live_extrapolates() -> None:
    import time as _time

    paused = evaluator._TaskClock("paused")
    paused.observe({"time": {"task_time_ms": 1200}})
    assert paused.now_ms() == 1200
    _time.sleep(0.05)
    assert paused.now_ms() == 1200

    live = evaluator._TaskClock("live")
    live.observe({"time": {"task_time_ms": 1000}})
    _time.sleep(0.05)
    estimated = live.now_ms()
    assert 1030 <= estimated <= 1500


def test_runner_configures_the_guest_environment_on_episode_start(tmp_path: Path) -> None:
    from gym_anything.runtime.runners import registry as runner_registry

    from gym_anything_rt.runner import RealTimeRunner
    from tests.test_runner import FAKE_INNER_KEY, FakeVMRunner, make_spec

    runner_registry.register_runner(FAKE_INNER_KEY, FakeVMRunner, replace=True)
    spec = make_spec()
    spec.security.resolved_env["EXISTING"] = "yes"
    runner = RealTimeRunner(spec)
    runner.on_episode_start({"episode_dir": str(tmp_path), "seed": 42})
    resolved = runner.inner.spec.security.resolved_env
    assert resolved["EXISTING"] == "yes"
    assert resolved["GYM_ANYTHING_RT_TIME_MODE"] == "paused"
    assert resolved["GYM_ANYTHING_RT_START_PAUSED"] == "1"
    assert resolved["GYM_ANYTHING_RT_CHALLENGE_SEED"] == "42"


def test_capture_returns_absolute_paths_for_remote_fetching(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeRunner:
        @staticmethod
        def exec_capture(_command):
            return json.dumps(
                {
                    "frames": [
                        {
                            "path": "/guest/frame.png",
                            "offset_ms": 0,
                            "target_offset_ms": 0,
                        }
                    ],
                    "resolution": [1920, 1080],
                    "time_status": {"task_time_ms": 0},
                }
            )

        @staticmethod
        def copy_from(_source, destination):
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"file")

    observation = capture_observation_window(
        SimpleNamespace(
            runner=FakeRunner(),
            env_spec=SimpleNamespace(
                observation=[SimpleNamespace(resolution=[1920, 1080])]
            ),
        ),
        mode="paused",
        duration_ms=0,
        frames_per_observation=1,
        turn=0,
        host_dir=Path("relative-artifacts"),
    )
    assert Path(observation["screen"]["path"]).is_absolute()
    assert Path(observation["capture_manifest"]).is_absolute()
    assert observation["screen"]["resolution"] == [1920, 1080]


def test_capture_rejects_a_resolution_that_cannot_share_action_coordinates(
    tmp_path: Path,
) -> None:
    class FakeRunner:
        @staticmethod
        def exec_capture(_command):
            return json.dumps(
                {
                    "frames": [
                        {
                            "path": "/guest/frame.png",
                            "offset_ms": 0,
                            "target_offset_ms": 0,
                        }
                    ],
                    "resolution": [1280, 720],
                    "time_status": {"task_time_ms": 0},
                }
            )

        @staticmethod
        def copy_from(_source, destination):
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"file")

    env = SimpleNamespace(
        runner=FakeRunner(),
        env_spec=SimpleNamespace(
            observation=[SimpleNamespace(resolution=[1920, 1080])]
        ),
    )
    try:
        capture_observation_window(
            env,
            mode="paused",
            duration_ms=0,
            frames_per_observation=1,
            turn=0,
            host_dir=tmp_path / "artifacts",
        )
    except RuntimeError as error:
        assert "captured [1280, 720], configured [1920, 1080]" in str(error)
    else:
        raise AssertionError("capture accepted incompatible observation coordinates")


def test_localize_observation_fetches_remote_frames(tmp_path: Path, monkeypatch) -> None:
    remote_observation = {
        "screen": {"path": "/worker/episode/observations/turn-0003/frame-001.png"},
        "frames": [
            {"path": "/worker/episode/observations/turn-0003/frame-000.png", "offset_ms": 0},
            {"path": "/worker/episode/observations/turn-0003/frame-001.png", "offset_ms": 100},
        ],
        "capture_manifest": "/worker/episode/observations/turn-0003/manifest.json",
        "time": {"task_time_ms": 100},
        "time_status": {"state": "paused", "task_time_ms": 100},
        "settle_status": {"state": "paused", "task_time_ms": 90},
    }

    class FakeRemoteEnv:
        episode_dir = Path("/worker/episode_x")

        def __init__(self):
            self.fetches = []

        def fetch_path(self, remote_path, local_path):
            self.fetches.append((remote_path, local_path))
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            Path(local_path).write_bytes(b"file")
            return local_path

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    env = FakeRemoteEnv()
    observation = evaluator._localize_observation(env, remote_observation)

    assert len(env.fetches) == 3
    assert observation["screen"]["path"] == observation["frames"][-1]["path"]
    assert Path(observation["capture_manifest"]).is_file()
    for frame in observation["frames"]:
        assert Path(frame["path"]).is_file()
        assert str(tmp_path) in frame["path"]
    # a local environment (no fetch_path) passes through untouched
    plain = SimpleNamespace()
    assert evaluator._localize_observation(plain, remote_observation) is remote_observation


def test_remote_episode_mirror_accepts_explicit_root(tmp_path: Path) -> None:
    remote_observation = {
        "screen": {"path": "/worker/episode/turn-0003/frame-000.png"},
        "frames": [
            {
                "path": "/worker/episode/turn-0003/frame-000.png",
                "offset_ms": 0,
            }
        ],
        "capture_manifest": "/worker/episode/turn-0003/manifest.json",
    }

    class FakeRemoteEnv:
        episode_dir = Path("/worker/episode_x")

        @staticmethod
        def fetch_path(remote_path, local_path):
            path = Path(local_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(remote_path.encode())
            return local_path

    mirror_root = tmp_path / "remote-episodes"
    env = FakeRemoteEnv()
    observation = evaluator._localize_observation(
        env,
        remote_observation,
        mirror_root,
    )

    assert Path(observation["screen"]["path"]).is_relative_to(mirror_root)
    assert evaluator._client_episode_dir(env, mirror_root) == mirror_root / "episode_x"


def test_qwen_screen_loader_accepts_path_image_and_remote_base64(tmp_path: Path) -> None:
    path = tmp_path / "screen.png"
    Image.new("RGB", (20, 10), "red").save(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")

    assert image_from_screen({"path": str(path)}).size == (20, 10)
    assert image_from_screen({"image": Image.new("RGB", (8, 6), "blue")}).size == (8, 6)
    assert image_from_screen({"png_b64": encoded}).size == (20, 10)
    assert observation_frames({"screen": {"path": str(path)}}) == [
        {"path": str(path)}
    ]


def test_qwen_retries_null_content_from_successful_requests(monkeypatch) -> None:
    responses = iter([None, None, "<tool_call>valid</tool_call>"])
    calls = []

    def fake_call_llm(*args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr(
        "gym_anything_rt.agents.qwen35vl.call_llm",
        fake_call_llm,
    )

    response = RealTimeQwen35VLAgent.llm_call(
        [], "Qwen/Qwen3.5-9B", 0.0, 0.95, 20, 2048
    )

    assert response == "<tool_call>valid</tool_call>"
    assert len(calls) == 3


def test_qwen_null_content_retry_reports_exhaustion(monkeypatch) -> None:
    monkeypatch.setattr(
        "gym_anything_rt.agents.qwen35vl.call_llm",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(
        RuntimeError,
        match="Qwen returned content=null after 3 attempts",
    ):
        call_qwen_with_null_response_retry(
            [], "Qwen/Qwen3.5-9B", 0.0, 0.95, 20, 2048
        )


def test_qwen_sends_every_frame_at_the_native_display_resolution(tmp_path: Path) -> None:
    source = tmp_path / "native.png"
    Image.new("RGB", (1920, 1080), "navy").save(source)
    agent = object.__new__(RealTimeQwen35VLAgent)
    agent.display_resolution = [1920, 1080]
    agent.save_folder_custom = str(tmp_path)
    agent.step_idx = 3
    agent.b64_to_path = {}
    agent.original_sizes = []

    _latest_encoded, latest_path = agent.process_image(str(source))
    _earlier_encoded, earlier_path = agent._process_frame(
        {"path": str(source)},
        step=4,
        index=0,
    )

    with Image.open(latest_path) as latest:
        assert latest.size == (1920, 1080)
    with Image.open(earlier_path) as earlier:
        assert earlier.size == (1920, 1080)
    assert agent.original_sizes == [(1920, 1080)]
    assert agent.processed_size == (1920, 1080)


def test_qwen_multiframe_step_serializes_only_native_resolution_images(
    tmp_path: Path,
    monkeypatch,
) -> None:
    frame_paths = []
    for index in range(6):
        path = tmp_path / f"source-{index}.png"
        Image.new("RGB", (1920, 1080), (index * 20, 0, 0)).save(path)
        frame_paths.append(str(path))

    agent = object.__new__(RealTimeQwen35VLAgent)
    agent.display_resolution = [1920, 1080]
    agent.save_folder_custom = str(tmp_path)
    agent.step_idx = -1
    agent.b64_to_path = {}
    agent.original_sizes = []
    agent.frame_sequences = []
    agent._current_extra_frames = []
    agent.screenshots = []
    agent.history = []
    agent.responses = []
    agent.history_n = 1
    agent.image_max = 20
    agent.fold_size = 10
    agent.task_description = "Confirm the code."

    def parent_step(self, obs, _action_outputs):
        self.step_idx += 1
        encoded, _path = self.process_image(obs["screen"]["path"])
        self.screenshots.append(encoded)
        return self.build_messages(encoded)

    monkeypatch.setattr(RealTimeQwen35VLAgent.__mro__[1], "step", parent_step)
    messages = agent.step(
        {"frames": [{"path": path} for path in frame_paths]},
        [],
    )
    image_urls = [
        item["image_url"]["url"]
        for item in messages[-1]["content"]
        if item["type"] == "image_url"
    ]

    assert len(image_urls) == 6
    for url in image_urls:
        with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
            assert image.size == (1920, 1080)


def test_qwen_messages_preserve_chronological_frame_order() -> None:
    agent = object.__new__(RealTimeQwen35VLAgent)
    agent._current_extra_frames = ["first", "second"]
    agent.frame_sequences = []
    agent.step_idx = 0
    agent.history_n = 1
    agent.image_max = 20
    agent.fold_size = 10
    agent.screenshots = ["third"]
    agent.history = []
    agent.responses = []
    agent.task_description = "Do the task"
    agent.display_resolution = [1280, 720]

    messages = agent.build_messages(
        "third",
        history_n=1,
        image_max=20,
        fold_size=10,
    )
    user_content = messages[-1]["content"]
    image_urls = [
        item["image_url"]["url"]
        for item in user_content
        if item["type"] == "image_url"
    ]
    assert image_urls == [
        "data:image/png;base64,first",
        "data:image/png;base64,second",
        "data:image/png;base64,third",
    ]
    assert agent.frame_sequences == [["first", "second", "third"]]

    agent.build_messages(
        "third",
        history_n=1,
        image_max=20,
        fold_size=10,
    )
    assert agent.frame_sequences == [["first", "second", "third"]]


def test_qwen_context_backoff_folds_complete_old_observations() -> None:
    agent = object.__new__(RealTimeQwen35VLAgent)
    agent._current_extra_frames = ["new-first"]
    agent.frame_sequences = [["old-first", "old-last"]]
    agent.step_idx = 1
    agent.history_n = 100
    agent.image_max = 20
    agent.fold_size = 10
    agent.screenshots = ["old-last", "new-last"]
    agent.history = ["Clicked the old target"]
    agent.responses = ["old response"]
    agent.task_description = "Do the task"
    agent.display_resolution = [1280, 720]

    messages = agent.build_messages(
        "new-last",
        history_n=100,
        image_max=2,
        fold_size=1,
    )
    assert messages[1]["content"][0] == {
        "type": "text",
        "text": "This screenshot has been collapsed.",
    }
    latest_images = [
        item["image_url"]["url"]
        for item in messages[-1]["content"]
        if item["type"] == "image_url"
    ]
    assert latest_images == [
        "data:image/png;base64,new-first",
        "data:image/png;base64,new-last",
    ]


def test_summary_written_only_with_decided_verdict(tmp_path, monkeypatch) -> None:
    """A crashed episode leaves no summary; a decided one writes it even
    when env.close() fails against a dead worker."""

    class FakeEnv:
        episode_dir = None

        def __init__(self):
            self.closed = False

        def reset(self, **kwargs):
            raise RuntimeError("worker unreachable at create")

        def close(self):
            self.closed = True
            raise RuntimeError("close also fails")

    summary = tmp_path / "s.json"
    args = evaluator.build_parser().parse_args([
        "--env-dir", "benchmarks/gym_anything_rt/environments/rotating_keyboard_v2_env",
        "--task", "rotating_keyboard_v2_d5_full_seed_0001",
        "--agent", "AuthoritativeObservationProbeAgent",
        "--agent-args", "{}",
        "--time-mode", "paused",
        "--episode-summary-path", str(summary),
    ])
    fake = FakeEnv()
    monkeypatch.setattr(evaluator, "_make_env", lambda *a, **k: fake)
    with pytest.raises(RuntimeError, match="worker unreachable"):
        evaluator.run(args)
    assert fake.closed
    assert not summary.exists()


def test_evaluator_delegates_autonomous_agent_episode(tmp_path, monkeypatch) -> None:
    calls = {}

    class AutonomousAgent:
        autonomous = True

        def __init__(self, agent_args, verbose, debug):
            calls["agent_args"] = agent_args

        def init(self, task_description, display_resolution, save_path):
            calls["description"] = task_description
            calls["resolution"] = display_resolution
            calls["save_path"] = save_path

        def run_episode(self, env, task_description):
            calls["run_episode"] = (env, task_description)

        def finish(self, info):
            calls["finish"] = info

    class FakeEnv:
        max_steps = 12
        episode_dir = tmp_path
        task_spec = SimpleNamespace(
            natural_language="Solve the moving task.",
            description="Fallback.",
        )
        env_spec = SimpleNamespace(
            observation=[
                SimpleNamespace(type="frame_window", resolution=(1920, 1080))
            ]
        )

        def set_episode_limits(self, max_steps, timeout_sec):
            calls["limits"] = (max_steps, timeout_sec)

        def step(self, actions, **kwargs):
            calls["mark_done"] = (actions, kwargs)
            return {}, 1.0, True, {
                "verifier": {"decided": True, "passed": True, "score": 100}
            }

        def close(self):
            calls["closed"] = True

    env = FakeEnv()
    initial = {
        "screen": {"path": str(tmp_path / "frame.png")},
        "frames": [{"path": str(tmp_path / "frame.png")}],
        "time": {"task_time_ms": 0},
    }
    (tmp_path / "frame.png").write_bytes(b"frame")
    monkeypatch.setattr(
        evaluator,
        "_create_and_reset",
        lambda args, runner_options: (
            calls.setdefault("runner_options", runner_options) and env,
            initial,
        ),
    )
    monkeypatch.setattr(evaluator, "_resolve_agent_class", lambda *args: AutonomousAgent)

    args = evaluator.build_parser().parse_args([
        "--env-dir", "benchmarks/gym_anything_rt/environments/rotating_keyboard_v2_env",
        "--task", "rotating_keyboard_v2_d5_full_seed_0001",
        "--agent", "CodexCliAgent",
        "--agent-args", '{"model": "gpt-5.6-luna"}',
        "--temporal-mode", "live_timestamped_execution",
        "--steps", "9",
    ])

    assert evaluator.run(args) == 0
    assert calls["runner_options"]["observation_window_ms"] == 0
    assert calls["runner_options"]["frames_per_observation"] == 1
    assert calls["agent_args"]["temporal_mode"] == "live_timestamped_execution"
    assert calls["agent_args"]["max_steps"] == 9
    assert "write programs inside the isolated agent sandbox" in calls["description"]
    assert calls["run_episode"] == (env, calls["description"])
    assert calls["mark_done"] == (
        [],
        {
            "mark_done": True,
            "capture_observation": False,
            "settle_after_actions": False,
        },
    )
    assert calls["finish"]["verifier"]["passed"] is True
    assert calls["closed"] is True


def test_admission_waits_out_capacity_refusals(tmp_path, monkeypatch) -> None:
    """Create/reset 503s are back pressure: the client retries with backoff
    instead of dying, and non-transient errors still raise immediately."""

    calls = {"n": 0}

    class BusyEnv:
        def __init__(self):
            self.closed = False

        def reset(self, **kwargs):
            calls["n"] += 1
            if calls["n"] < 4:
                raise RuntimeError(
                    "Remote request failed: 503 Server Error: for url: "
                    "http://master:5900/envs/create"
                )
            return {"ok": True}

        def close(self):
            self.closed = True

    envs = []

    def fake_make_env(args, options):
        # The remote client POSTs /envs/create in its constructor, so
        # capacity refusals surface here, not at reset.
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError(
                "Remote request failed: 503 Server Error: for url: "
                "http://master:5900/envs/create"
            )
        env = BusyEnv()
        envs.append(env)
        return env

    monkeypatch.setattr(evaluator, "_make_env", fake_make_env)
    monkeypatch.setattr(evaluator.time, "sleep", lambda s: None)
    args = SimpleNamespace(
        remote_timeout=600,
        seed=42,
        use_cache=False,
        cache_level="pre_start",
        use_savevm=False,
    )
    env, obs = evaluator._create_and_reset(args, {"time_mode": "paused"})
    assert obs == {"ok": True}
    assert calls["n"] == 5
    assert len(envs) == 2
    assert envs[0].closed and not envs[1].closed

    class FatalEnv:
        def reset(self, **kwargs):
            raise ValueError("bad spec")

        def close(self):
            pass

    monkeypatch.setattr(evaluator, "_make_env", lambda a, o: FatalEnv())
    with pytest.raises(ValueError):
        evaluator._create_and_reset(args, {"time_mode": "paused"})
