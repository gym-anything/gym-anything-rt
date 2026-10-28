"""Export the real-time minigames as a static site that runs in the browser.

Each game's challenges are generated ahead of time by the benchmark's own
generator, and its grader runs in the page through Pyodide. The output is
served from the website's play/ folder.

    python website/build_play.py --output _site/play
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

BENCHMARK = Path(__file__).resolve().parents[1] / "benchmarks" / "gym_anything_rt"
RUNTIME = BENCHMARK / "shared_runtime"
GRADERS = RUNTIME / "server" / "incubator_graders"
LEGACY_GRADER = RUNTIME / "server" / "legacy_browser_grader.py"
CHALLENGES_PER_CONFIGURATION = 4
LEVELS = (1, 2, 3, 4, 5)
INTERACTIONS = ("simplified", "full")
DEFAULT_DIFFICULTY = 5
DEFAULT_INTERACTION = "full"

sys.path.insert(0, str(BENCHMARK / "shared_scripts"))
from setup_task import generate_task_state, load_task  # noqa: E402


def copy_runtime(play):
    runtime = play / "runtime"
    runtime.mkdir(parents=True)
    browser = RUNTIME / "browser"
    shutil.copy2(browser / "index.html", play / "index.html")
    shutil.copy2(browser / "PYODIDE-NOTICE.txt", play / "PYODIDE-NOTICE.txt")
    for name in ("browser_adapter.js", "demo_controls.css", "demo_controls.js", "grader_worker.js"):
        shutil.copy2(browser / name, runtime / name)
    for name in ("app.js", "styles.css", "time_controller.js"):
        shutil.copy2(RUNTIME / "app" / name, runtime / name)
    shutil.copytree(RUNTIME / "app" / "mechanics", runtime / "mechanics")
    shutil.copytree(RUNTIME / "app" / "vendor", runtime / "vendor")


def challenges(task, environment, level):
    """Generate one configuration's challenges.

    Both interaction modes of a level share their seeds, so switching modes
    keeps the same world and only changes the controls.
    """
    generated, seen = [], set()
    for attempt in range(CHALLENGES_PER_CONFIGURATION):
        public_state, ground_truth = generate_task_state(task, f"browser-play:{environment}:d{level}:{attempt}")
        challenge_id = ground_truth.get("challenge_id")
        if not challenge_id or challenge_id in seen:
            raise ValueError(f"{environment}: challenge ids are not unique")
        seen.add(challenge_id)
        generated.append({"public_state": public_state, "ground_truth": ground_truth})
    return generated


def grader(mechanic):
    """Return the grader file for a game, falling back to the shared legacy grader."""
    path = GRADERS / f"{mechanic}.py"
    return path if path.is_file() else LEGACY_GRADER


def bundle(name, environment, settings):
    mechanic = environment.removesuffix("_env")
    tasks = BENCHMARK / "environments" / environment / "tasks"
    profiles = {}
    for level in LEVELS:
        interactions = {}
        for interaction in INTERACTIONS:
            task_id = f"{mechanic}_d{level}_{interaction}_seed_0001"
            task = load_task(tasks / task_id / "task.json")
            interactions[interaction] = {
                "interaction": interaction,
                "task_id": task_id,
                "instruction": task["natural_language"],
                "challenges": challenges(task, environment, level),
            }
        # The page always selects an interaction profile, so a level does not
        # repeat its default interaction's challenges.
        profiles[str(level)] = {
            "level": level,
            "task_id": interactions[DEFAULT_INTERACTION]["task_id"],
            "instruction": interactions[DEFAULT_INTERACTION]["instruction"],
            "interaction_profiles": interactions,
        }
    default = profiles[str(DEFAULT_DIFFICULTY)]["interaction_profiles"][DEFAULT_INTERACTION]
    return {
        "version": 4,
        "environment_id": environment,
        "mechanic_id": mechanic,
        "title": name,
        "task_id": default["task_id"],
        "default_difficulty": DEFAULT_DIFFICULTY,
        "default_interaction": DEFAULT_INTERACTION,
        "difficulty_profiles": profiles,
        "real_time": settings[mechanic],
        "grader": f"graders/{grader(mechanic).name}",
        "challenges": default["challenges"],
    }


def catalog_entry(name, environment, data, settings):
    """Describe a game for the arcade page, using the benchmark's own control summaries."""
    controls = json.loads((BENCHMARK / "environments" / environment / "controls.json").read_text())
    default = data["difficulty_profiles"][str(DEFAULT_DIFFICULTY)]["interaction_profiles"][DEFAULT_INTERACTION]
    goal = re.split(r"(?<=[.!?])\s+", default["instruction"].strip(), maxsplit=1)[0]
    return {
        "environment": environment,
        "name": name,
        "goal": goal,
        "time_limit_seconds": settings[data["mechanic_id"]]["play_time_seconds"],
        "levels": [
            {
                "level": level,
                "label": controls["difficulty"][str(level)]["label"].replace("_", " "),
                "summary": controls["difficulty"][str(level)]["summary"],
            }
            for level in LEVELS
        ],
        "interactions": {
            interaction: controls["interaction"][interaction].get("summary")
            or controls["interaction"][interaction].get("description", "")
            for interaction in INTERACTIONS
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    play = args.output
    if play.exists():
        shutil.rmtree(play)
    copy_runtime(play)
    (play / "challenges").mkdir()
    (play / "graders").mkdir()

    pairs = json.loads((BENCHMARK / "pairs.json").read_text())["pairs"]
    settings = json.loads((BENCHMARK / "real_time.json").read_text())["environments"]
    games = []
    for pair in sorted(pairs, key=lambda pair: pair["name"].lower()):
        environment = pair["real_time_environment"]
        data = bundle(pair["name"], environment, settings)
        (play / "challenges" / f"{environment}.json").write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        shutil.copy2(grader(data["mechanic_id"]), play / data["grader"])
        games.append(catalog_entry(pair["name"], environment, data, settings))
    (play / "games.json").write_text(json.dumps({"games": games}, indent=1) + "\n", encoding="utf-8")
    print(f"exported {len(games)} games to {play}")


if __name__ == "__main__":
    main()
