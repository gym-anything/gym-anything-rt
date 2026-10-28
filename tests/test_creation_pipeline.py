"""The creation pipeline's command line, prompts and cited documents."""

import json
import re
from pathlib import Path

import pytest

from extras.research.real_time_creation import method

ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "extras/research/real_time_creation/memory"


def test_prompts_exist():
    for name in ("creation_prompt.md", "audit_prompt.md", "requirements.md", "examples.md"):
        assert (MEMORY / name).is_file()


def test_every_cited_repository_file_exists():
    cited = set()
    for prompt in MEMORY.glob("*.md"):
        cited.update(re.findall(r"`((?:docs/|AGENTS\.md)[^`<>*]*)`", prompt.read_text()))
    assert cited
    for path in sorted(cited):
        assert (ROOT / path).exists(), path


def test_example_games_are_released():
    examples = (MEMORY / "examples.md").read_text()
    for mechanic in re.findall(r"Mechanic: `([a-z0-9_]+)`", examples):
        assert (ROOT / "benchmarks/gym_anything_rt/environments" / f"{mechanic}_env").is_dir(), mechanic


def test_selection_and_survey_are_required():
    with pytest.raises(SystemExit):
        method.build_parser().parse_args(["--env-dir", "new_game_env"])
    args = method.build_parser().parse_args([
        "--env-dir", "new_game_env", "--selection-file", "s.json", "--survey-root", "survey"])
    assert args.model == method.DEFAULT_MODEL


def test_selection_must_name_the_target_once(tmp_path):
    survey = tmp_path / "survey"
    survey.mkdir()
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"picks": [{"env_dir": "other_env"}]}))
    with pytest.raises(ValueError, match="exactly one selection entry"):
        method._selection_context("new_game_env", selection, survey)
    selection.write_text(json.dumps({"picks": [{"env_dir": "new_game_env", "survey_ids": ["A-1"]}]}))
    assert "new_game_env" in method._selection_context("new_game_env", selection, survey)


def test_repository_root_is_found():
    assert method._repo_root() == ROOT
