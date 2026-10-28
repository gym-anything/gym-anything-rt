<div align="center">
    <h1>Gym-Anything-RT: Scaling Real-Time Environments for Vision-Language Agents</h1>
    <a href="https://gym-anything.github.io/gym-anything-rt/"><img src="https://img.shields.io/badge/Website-Visit-blue?style=for-the-badge"></a>
    <a href="https://arxiv.org/abs/2610.37567"><img src="https://img.shields.io/badge/arXiv-2610.37567-red.svg?style=for-the-badge"></a>
    <a href="https://github.com/gym-anything/gym-anything-rt"><img src="https://img.shields.io/badge/GitHub-Code-black?style=for-the-badge&logo=github"></a>
    <a href="https://github.com/cmu-l3/gym-anything"><img src="https://img.shields.io/badge/Built%20on-Gym--Anything-purple?style=for-the-badge"></a>
</div>

<br>

Video games and physical devices keep changing while an agent thinks. Gym-Anything-RT measures how well vision-language agents act in such settings. It contains 100 real-time minigames, and each one has a non-real-time counterpart that poses the same task without requiring a real-time response. Every minigame has five difficulty levels and two interaction modes, giving 2,000 configurations in total.

The evaluation stack controls the clock of each minigame, so the same configuration can run live, slowed down, or paused. Comparing these settings separates the cost of acting in real time from the difficulty of the task itself.

| | Real-time | Non-real-time counterpart |
|---|---:|---:|
| GPT-6 Astra (xHigh) | 9.0% | 66.0% |
| GPT-6 Astra (Low) | 8.0% | 58.0% |
| Claude Opus 5.5 (xHigh) | 5.0% | 57.0% |
| GPT-6 Luna (xHigh) | 1.0% | 17.0% |
| Qwen3.8-27B | 1.0% | 2.0% |
| Qwen3.5-9B | 0.0% | 1.0% |

Pass rates at difficulty 5 with full interaction, in the live setting. Astra (xHigh) rises to 75.0% on the real-time minigames when the environment is paused. A human author solved 9 of 20 randomly sampled real-time minigames, or 45.0%.

## Quickstart

Gym-Anything-RT is a Gym-Anything benchmark. It adds a runner that owns the minigame clock, a set of agents, and the minigames themselves.

```bash
# 1. Install (we recommend uv: https://docs.astral.sh/uv/)
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[sandweave]"

# 2. Check what is available on your machine
gym-anything doctor
```

All results in the paper use the Sandweave backend on Linux. Any Gym-Anything runner that can show a Linux desktop also works as the inner runner.

Run one configuration with GPT-6 Astra through the Codex CLI, in the live setting:

```bash
gym-anything-rt-evaluate \
  --env-dir benchmarks/gym_anything_rt/environments/concertina_courier_v2_env \
  --task concertina_courier_v2_d5_full_seed_0001 \
  --agent gym_anything_rt.agents.codex_no_code:NoCodeCodexAgent \
  --agent-args '{"model": "gpt-6-astra", "reasoning_effort": "xhigh", "no_code_model_catalog": "models.json"}' \
  --temporal-mode live --inner-runner sandweave --fast-io --seed 42
```

Change `--temporal-mode live` to `--temporal-mode paused` to freeze the minigame between actions, or add `--time-scale 0.25` to run it at a quarter of its normal speed. [docs/evaluation.md](docs/evaluation.md) describes every setting and agent.

## What Is Inside

```text
benchmarks/gym_anything_rt/      the benchmark
  environments/<game>_env/       100 real-time minigames
  environments/<game>_nonrealtime_env/   their 100 counterparts
  shared_runtime/                browser app, game server and graders
  shared_scripts/                task generators and in-guest clock control
  solvers/                       scripted oracle solutions
  splits/                        task splits for each environment
  pairs.json                     each minigame with its counterpart
  real_time.json                 play time and observation window of each game
src/gym_anything_rt/             the runtime
  runner.py                      the runner that owns each minigame's clock
  evaluate.py                    the evaluation command
  agents/                        the agents evaluated in the paper
extras/research/real_time_creation/   the agentic pipeline that creates minigames
docs/                            the definition of real time, the controllability framework and guides
website/                         the project page
```

Each environment follows the standard Gym-Anything layout, with an `env.json`, a `controls.json` describing its difficulty and interaction settings, and one task folder for each of its ten configurations. Task folders are named `<game>_d<difficulty>_<full|simplified>_seed_0001`. The task seed passed at run time determines the exact world, so `--seed` controls the instance.

The split files group the configurations. For example, `d5_full` holds the configuration used for the main results, `full` and `simplified` hold one interaction mode, and `d1` to `d5` hold one difficulty level.

```python
from gym_anything.registry import get_tasks_for_environment

get_tasks_for_environment("concertina_courier_v2_env", "gym_anything_rt", split="d5_full")
```

## How It Works

Each minigame runs in a browser inside a Linux desktop. The runner starts the game paused, then advances its clock according to the chosen setting. In the live setting, the game keeps running from observation through action. In the slowed setting, every clock of the game, including timers, animations and server-side clocks, runs at a fraction of its normal rate. In the paused setting, the game advances through a short observation window and then freezes until the agent acts. All settings use the same game, seed, difficulty, interaction mode and verifier.

Agents receive screenshots and act through mouse and keyboard input only. Each action and screenshot travels over a direct connection to the agent's own sandbox, which keeps the median time from sending an action to receiving the resulting screenshot below 50 ms.

[docs/real-time.md](docs/real-time.md) gives the definition used to label a configuration as real-time, and [docs/fast-io.md](docs/fast-io.md) describes the direct connection. [docs/controllability](docs/controllability) defines the difficulty levels and interaction modes.

## Creating New Minigames

The minigames were built by coding agents. Creator agents implement a game with five difficulty levels and two interaction modes, together with a generator, grader, verifier and oracle solver. Independent auditor agents check the implementation and its evidence, and the creator revises the game until it passes the audit. [extras/research/real_time_creation](extras/research/real_time_creation) contains this loop and its prompts.

## Citation

```bibtex
@misc{aggarwal2026gymanythingrt,
  title         = {Gym-Anything-RT: Scaling Real-Time Environments for Vision-Language Agents},
  author        = {Aggarwal, Pranjal and Welleck, Sean},
  year          = {2026},
  eprint        = {2610.37567},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LG},
  url           = {https://arxiv.org/abs/2610.37567}
}
```

## License

MIT. See [LICENSE](LICENSE).
