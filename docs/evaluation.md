# Evaluating Agents

`gym-anything-rt-evaluate` runs one agent on one configuration and writes the episode, the agent's trace and a timing record to the episode directory. It uses the standard Gym-Anything doors: the environment is loaded with `gym_anything.api.from_config`, and the runner named in each `env.json`, `gym_anything_rt`, wraps an inner runner that provides the Linux desktop.

## Settings

| Setting | Options | What happens |
|---|---|---|
| Live | `--temporal-mode live` | The minigame keeps running from observation through action at its natural speed. Each screenshot is a single frame. |
| Slowed | `--temporal-mode live --time-scale 0.25` | Every clock of the minigame runs at the given fraction of its normal rate. A slowdown of 4 is `--time-scale 0.25`, and a slowdown of 16 is `--time-scale 0.0625`. Input and screenshots still run in real time. |
| Paused | `--temporal-mode paused` | The minigame advances through a short observation window, then freezes on the final frame until the agent acts. The agent receives the frames of that window. |

The length of the observation window and the number of frames come from `benchmarks/gym_anything_rt/real_time.json`, and `--observation-window-ms` and `--frames-per-observation` override them. The same file sets each minigame's play time. `--no-play-time-limit` removes that cutoff, and the step limit and model-request limits still apply.

The paper's runs used these options:

```bash
--seed 42 --steps 100 --no-play-time-limit --inner-runner sandweave --fast-io \
--request-attempts 1 --request-timeout-seconds 930
```

with `"max_steps": 100` and `"timeout_sec": 21600`, a six-hour limit, in the agent arguments. A step is one request with one or more actions. Requests that only return a screenshot do not use a step.

`--inner-runner` names the backend, as a registered runner key or a `module:Class` locator. `--fast-io` delivers input and screenshots directly to the sandbox and requires a runner that acknowledges input delivery, such as Sandweave. `--remote-url` runs the episode on a Gym-Anything remote worker instead.

## Agents

Pass an agent as `--agent module:Class` and its arguments as JSON in `--agent-args`.

| Agent | Models in the paper | Required arguments |
|---|---|---|
| `gym_anything_rt.agents.codex_no_code:NoCodeCodexAgent` | GPT-6 Astra, GPT-6 Luna | `model`, `reasoning_effort`, `no_code_model_catalog` |
| `gym_anything_rt.agents.codex_cli:RealTimeCodexCliAgent` | Astra and Luna in the coding experiment | `model`, `reasoning_effort` |
| `gym_anything_rt.agents.claude_no_code:NoCodeClaudeAgent` | Claude Opus 5.5 | `model`, `reasoning_effort`, `claude_binary`, `claude_auth_dir` |
| `gym_anything_rt.agents.rulebook_no_code:RulebookNoCodeAgent` | Luna with an interface rulebook | as `NoCodeCodexAgent`, plus `rulebook_path` and `rulebook_sha256` |
| `gym_anything_rt.agents.qwen_policy:NoCodeNativeQwenAgent` | Qwen3.5-9B, Qwen3.8-27B | `model`, `tokenizer_path`, and `TINKER_BASE_URL` and `TINKER_API_KEY` in the environment |

The no-code agents run their CLI inside an isolated sandbox that has no shell or code execution. The model receives screenshots and sends literal mouse and keyboard actions through a single `computer` tool. `no_code_model_catalog` is a Codex model catalog JSON with a `models` list that contains the chosen model. The agent copies only that model's entry into the sandbox and clears its tool settings, so that Codex exposes no tools beyond `computer`.

The Claude agent copies `.credentials.json` and `.claude.json` from `claude_auth_dir`, which must be readable only by its owner, and the Claude Code binary at `claude_binary` into the sandbox.

The Codex agents read the login created by `codex login` from `~/.codex/auth.json`, or from `codex_auth_path` when it is given. Both CLIs run inside Gym-Anything's agent sandbox. See the [Gym-Anything agent docs](https://cmu-l3.github.io/gym-anything/docs/agents/) for the sandbox requirements.

## Running Many Configurations

The split files list the configurations of each environment:

```python
from benchmarks.gym_anything_rt import get_tasks_for_environment, load_pairs

for pair in load_pairs():
    for env in (pair["real_time_environment"], pair["non_real_time_environment"]):
        for task in get_tasks_for_environment(env, split="d5_full"):
            ...  # one gym-anything-rt-evaluate run per (env, task)
```

`d5_full` is the configuration of the main results. The other splits are `all`, `full`, `simplified`, and `d1` to `d5`.

## Outputs

Each episode directory contains the observations the agent received, a timing record of every turn with the model time and the execution time of each action, the agent's CLI session, and the verifier's result. With `--episode-summary-path`, a finished episode also writes a JSON summary with the task, seed, setting, number of submissions and the verifier's result. A crashed episode writes no summary, so the summary's presence marks a completed run.
