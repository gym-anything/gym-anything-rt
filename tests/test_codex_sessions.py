from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from gym_anything_rt.agents import codex_cli


@pytest.mark.parametrize("failure", [None, "copy_timeout", "empty", "invalid"])
@pytest.mark.parametrize("cli_timeout", [False, True])
def test_session_export_failure_retains_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure, cli_timeout: bool
) -> None:
    original = tmp_path / "private" / "sessions" / "rollout.jsonl"
    original.parent.mkdir(parents=True)
    original.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')
    stopped = []

    class Sandbox:
        gateway_bind_host = "127.0.0.1"

        def build(self):
            pass

        def start(self, **kwargs):
            pass

        def exec(self, command, timeout_sec):
            if cli_timeout:
                raise subprocess.TimeoutExpired(command, timeout_sec)
            return subprocess.CompletedProcess(command, 0, "", "")

        def copy_directory_from(self, source, destination):
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / original.name
            if failure == "copy_timeout":
                target.touch()
                raise subprocess.TimeoutExpired("copy", 60)
            if failure == "empty":
                target.touch()
            elif failure == "invalid":
                target.write_text("not JSON\n")
            else:
                shutil.copy2(original, target)

        def stop(self):
            stopped.append(True)
            shutil.rmtree(original.parent.parent)

    gateway = SimpleNamespace(
        display_w=1920, display_h=1080, transcript=[],
        start=lambda **kwargs: 12345, stop=lambda: None,
    )
    monkeypatch.setattr(codex_cli, "RealTimeCodexActionGateway", lambda *a, **k: gateway)
    monkeypatch.setattr(codex_cli, "select_sandbox", lambda *a, **k: Sandbox())
    agent = codex_cli.RealTimeCodexCliAgent(
        agent_args={"persist_session": True, "temporal_mode": "paused"}
    )
    agent.init("Solve the puzzle", (1920, 1080), str(tmp_path / "episode"))
    monkeypatch.setattr(agent, "prepare_sandbox", lambda sandbox: None)

    if failure:
        with pytest.raises(RuntimeError, match="agent sandbox retained"):
            agent.run_episode(SimpleNamespace(max_steps=100))
        assert not stopped
        assert original.read_text().endswith('"test"}}\n')
        assert not agent.done
    else:
        agent.run_episode(SimpleNamespace(max_steps=100))
        assert stopped == [True]
        assert not original.exists()
        exported = tmp_path / "episode/cli_harness/codex_home/sessions/rollout.jsonl"
        assert exported.read_text().endswith('"test"}}\n')
        assert agent.done
