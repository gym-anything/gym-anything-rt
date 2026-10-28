from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from gym_anything_rt.realtime import (
    RealTimeSettings,
    load_real_time_settings,
    mechanic_id_from_env_dir,
)
from benchmarks.gym_anything_rt.shared_scripts import capture_observation_window as CAPTURE
from benchmarks.gym_anything_rt.shared_scripts.setup_task import generate_task_state
from benchmarks.gym_anything_rt.shared_runtime.server.minigame_server import PuzzleServer


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "gym_anything_rt"


def request_json(url: str, payload: dict | None = None) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"content-type": "application/json"} if body else {},
        method="POST" if body else "GET",
    )
    with urllib.request.urlopen(request) as response:
        return response.status, json.load(response)


def test_existing_control_files_match_canonical_real_time_settings() -> None:
    for path in (BENCHMARK / "environments").glob("*_env/controls.json"):
        mechanic_id = path.parent.name.removesuffix("_env")
        controls = json.loads(path.read_text(encoding="utf-8"))
        assert controls["real_time"] == load_real_time_settings(mechanic_id).__dict__


def test_existing_env_runner_options_match_canonical_real_time_settings() -> None:
    keys = ("play_time_seconds", "observation_window_ms", "frames_per_observation")
    for path in (BENCHMARK / "environments").glob("*_env/env.json"):
        mechanic_id = path.parent.name.removesuffix("_env")
        options = json.loads(path.read_text(encoding="utf-8"))["runner_options"]
        assert {key: options[key] for key in keys} == load_real_time_settings(
            mechanic_id
        ).__dict__


def test_mechanic_id_comes_from_environment_directory() -> None:
    assert mechanic_id_from_env_dir("/tmp/rotating_keyboard_env") == "rotating_keyboard"


def test_frame_targets_include_both_ends_of_a_window() -> None:
    assert CAPTURE.frame_targets(1000, 600, 4) == [1000, 1200, 1400, 1600]
    assert CAPTURE.frame_targets(1000, 0, 1) == [1000]


def test_frame_selection_uses_nearest_capture_time(tmp_path: Path) -> None:
    paths = []
    for index, timestamp_ms in enumerate((1000, 1100, 1200)):
        path = tmp_path / f"{index}.png"
        path.write_bytes(b"png")
        timestamp_ns = timestamp_ms * 1_000_000
        path.touch()
        os.utime(path, ns=(timestamp_ns, timestamp_ns))
        paths.append(path)
    assert CAPTURE.select_frames(paths, [1010, 1190]) == [paths[0], paths[2]]


def test_authoritative_capture_preserves_the_native_desktop_resolution() -> None:
    source = (BENCHMARK / "shared_scripts" / "capture_observation_window.py").read_text(
        encoding="utf-8"
    )
    assert '"-vf", "scale=' not in source
    assert '"resolution": [width, height]' in source


def test_puzzle_browser_launches_full_screen() -> None:
    source = (BENCHMARK / "shared_scripts" / "open_puzzle_browser.sh").read_text(
        encoding="utf-8"
    )
    assert "--kiosk" in source
    assert "--window-size=" not in source
    assert "fullscreen,maximized_vert,maximized_horz" in source
    assert "xdpyinfo" in source
    assert "wmctrl -lG" in source
    assert "Puzzle browser fullscreen verified" in source
    assert "Puzzle browser fullscreen verification failed" in source
    assert "Reusing existing puzzle browser window" in source
    assert 'dataSubmissionPolicyBypassNotification", true' in source
    assert 'browser.link.open_newwindow", 3' in source
    assert 'browser.link.open_newwindow.restriction", 0' in source
    assert "--new-instance --kiosk" in source
    assert 'profile_dir="$home_dir/gym-anything-rt-profile"' in source
    assert "--profile '$profile_dir'" in source
    assert "--disable-backgrounding-occluded-windows" in source
    assert "--disable-renderer-backgrounding" in source
    assert "--disable-features=AutomaticTabDiscarding,MemorySaverMode" in source


def test_puzzle_browser_requires_the_task_window_and_exact_display_geometry(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    def executable(name: str, source: str) -> None:
        path = fake_bin / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)

    executable(
        "google-chrome-stable",
        "#!/usr/bin/env bash\nsleep \"${FAKE_BROWSER_DELAY:-0}\"\necho launch >> \"$FAKE_BROWSER_MARKER\"\nexit 0\n",
    )
    executable("xhost", "#!/usr/bin/env bash\nexit 0\n")
    executable(
        "xdpyinfo",
        "#!/usr/bin/env bash\n"
        "echo '  dimensions:    1920x1080 pixels'\n"
        "for _ in $(seq 1 10000); do echo 'visual metadata'; done\n",
    )
    executable(
        "wmctrl",
        """#!/usr/bin/env bash
if [ "$1" = "-lx" ] && { [ "${FAKE_WMCTRL_MODE:-success}" = "success" ] || { [ "${FAKE_WMCTRL_MODE:-success}" = "after-launch" ] && [ -f "$FAKE_BROWSER_MARKER" ]; }; }; then
  echo '0x001 0 google-chrome.Google-chrome host Gym-Anything-RT'
elif [ "$1" = "-lG" ]; then
  echo '0x001 0 0 0 1920 1080 host Gym-Anything-RT'
fi
exit 0
""",
    )
    script = BENCHMARK / "shared_scripts" / "open_puzzle_browser.sh"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "GYM_ANYTHING_RT_BROWSER_COMMAND": str(fake_bin / "google-chrome-stable"),
        "GYM_ANYTHING_RT_BROWSER_USER": "root",
        "GYM_ANYTHING_RT_BROWSER_HOME": str(tmp_path / "home"),
        "GYM_ANYTHING_RT_STATE_DIR": str(tmp_path / "state"),
        "FAKE_BROWSER_MARKER": str(tmp_path / "browser-launched"),
        "GYM_ANYTHING_RT_WINDOW_ATTEMPTS": "200",
        "GYM_ANYTHING_RT_WINDOW_POLL_SECONDS": "0.02",
        "GYM_ANYTHING_RT_GEOMETRY_ATTEMPTS": "1",
        "GYM_ANYTHING_RT_GEOMETRY_POLL_SECONDS": "0",
        "GYM_ANYTHING_RT_BROWSER_LOCK_ATTEMPTS": "200",
        "GYM_ANYTHING_RT_BROWSER_LOCK_POLL_SECONDS": "0.02",
    }

    accepted = subprocess.run(
        [str(script)],
        env={**environment, "FAKE_WMCTRL_MODE": "after-launch"},
        check=False,
    )
    assert accepted.returncode == 0
    assert (tmp_path / "browser-launched").exists()
    (tmp_path / "browser-launched").unlink()
    reused = subprocess.run([str(script)], env=environment, check=False)
    assert reused.returncode == 0
    assert (tmp_path / "browser-launched").exists() is False

    concurrent_environment = {
        **environment,
        "FAKE_WMCTRL_MODE": "after-launch",
        "FAKE_BROWSER_DELAY": "0.25",
    }
    first = subprocess.Popen([str(script)], env=concurrent_environment)
    second = subprocess.Popen([str(script)], env=concurrent_environment)
    assert first.wait(timeout=10) == 0
    assert second.wait(timeout=10) == 0
    assert (tmp_path / "browser-launched").read_text(encoding="utf-8").splitlines() == [
        "launch"
    ]
    (tmp_path / "browser-launched").unlink()

    rejected = subprocess.run(
        [str(script)],
        env={**environment, "FAKE_WMCTRL_MODE": "no-window"},
        check=False,
    )

    assert rejected.returncode != 0


def test_time_control_server_sequences_commands_and_records_status(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    state_dir = tmp_path / "state"
    app_dir.mkdir()
    state_dir.mkdir()
    (app_dir / "index.html").write_text("ok", encoding="utf-8")
    PuzzleServer.app_dir = app_dir
    PuzzleServer.state_dir = state_dir
    server = ThreadingHTTPServer(("127.0.0.1", 0), PuzzleServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        _, initial = request_json(f"{base}/time-control")
        assert initial == {"command": "status", "sequence": 0}

        _, pause = request_json(f"{base}/time-control", {"command": "pause"})
        _, settled_pause = request_json(
            f"{base}/time-control", {"command": "settle_pause"}
        )
        _, window = request_json(
            f"{base}/time-control",
            {"command": "run_for", "milliseconds": 500, "start_delay_ms": 50},
        )
        assert pause["sequence"] == 1
        assert settled_pause["sequence"] == 2
        assert window["sequence"] == 3

        request_json(f"{base}/time-control/status", {
            "sequence": 3,
            "state": "paused",
            "phase": "completed",
            "task_time_ms": 500,
        })
        _, current = request_json(f"{base}/time-control")
        _, status = request_json(f"{base}/time-control/status")
        assert current["sequence"] == 3
        assert current["command"] == "pause"
        assert status["phase"] == "completed"
        assert status["task_time_ms"] == 500

        _, armed = request_json(
            f"{base}/input-control",
            {"command": "arm", "category": "mouse", "required": True},
        )
        _, completed_input = request_json(
            f"{base}/input-control",
            {"command": "complete", "arm_sequence": armed["arm_sequence"]},
        )
        assert armed["sequence"] == armed["arm_sequence"]
        assert completed_input["sequence"] == armed["sequence"] + 1
        request_json(
            f"{base}/input-control/status",
            {
                "command_sequence": completed_input["sequence"],
                "arm_sequence": armed["arm_sequence"],
                "phase": "completed",
                "receipt_confirmed": True,
                "task_time_ms": 500,
            },
        )
        _, input_command = request_json(f"{base}/input-control")
        _, delivered = request_json(f"{base}/input-control/status")
        assert input_command["command"] == "complete"
        assert delivered["receipt_confirmed"] is True
        assert delivered["task_time_ms"] == 500
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_state_refresh_is_idempotent_for_one_task_window_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    server = object.__new__(PuzzleServer)
    server.state_dir = state_dir
    server.app_dir = tmp_path / "shared_runtime" / "app"
    generated: list[str] = []

    class FakeSetup:
        @staticmethod
        def generate_task_state(task: dict, seed: str) -> tuple[dict, dict]:
            generated.append(seed)
            challenge_id = f"challenge-{len(generated)}"
            public = {
                "mechanic_id": "token_refresh_test",
                "task_id": task["id"],
                "challenge_id": challenge_id,
            }
            return public, dict(public)

    server._load_setup_module = lambda: FakeSetup
    server._write_json(
        state_dir / "current_task.json",
        {"task": {"id": "token-refresh-task"}, "attempt": 0},
    )
    monkeypatch.setenv("GYM_ANYTHING_RT_CHALLENGE_SEED", "fixed")

    first = server._try_regenerate_current_task(
        reason="refresh",
        client_task_token="window-a",
    )
    repeated = server._try_regenerate_current_task(
        reason="refresh",
        client_task_token="window-a",
    )
    assert repeated == first
    assert len(generated) == 1

    second_window = server._try_regenerate_current_task(
        reason="refresh",
        client_task_token="window-b",
    )
    assert second_window != first
    assert len(generated) == 2

    failed_retry = server._try_regenerate_current_task(reason="fail")
    repeated_after_failure = server._try_regenerate_current_task(
        reason="refresh",
        client_task_token="window-b",
    )
    assert repeated_after_failure == failed_retry
    assert len(generated) == 3
    assert json.loads((state_dir / "current_task.json").read_text(encoding="utf-8"))[
        "client_task_token"
    ] == "window-b"

    app_source = (BENCHMARK / "shared_runtime" / "app" / "app.js").read_text(
        encoding="utf-8"
    )
    assert 'new URLSearchParams(window.location.search).get("task")' in app_source
    assert "task=${encodeURIComponent(taskToken)}" in app_source
