# Working in Gym-Anything-RT

This file is for coding agents working in this repository, including the creator, auditor and review agents of the creation pipeline.

## Layout

- `benchmarks/gym_anything_rt/environments/<game>_env/` holds one real-time minigame, and `<game>_nonrealtime_env/` holds its counterpart. Each has `env.json`, `controls.json`, `scripts/`, and one folder per configuration under `tasks/`.
- Each game's code is spread across files named after its mechanic id:
  - `shared_scripts/incubator_generators/<mechanic>.py` generates the public state and the ground truth from the task and seed.
  - `shared_runtime/app/mechanics/<mechanic>.js` and `.css` render the game in the browser.
  - `shared_runtime/server/incubator_graders/<mechanic>.py` grades a submission.
  - `solvers/<mechanic>.py` is the scripted oracle solution, where one exists.
  - `real_time.json` holds the game's play time and paused observation window.
- `src/gym_anything_rt/` is the runtime: `runner.py` owns the game clock, `evaluate.py` runs an agent, and `agents/` holds the evaluated agents.
- `docs/real-time.md` defines when a configuration is real-time. It is frozen. Its SHA-256 is quoted in the paper.

## Rules

- Never change the strings a generator hashes into its random seed, such as mechanic ids or seed namespaces. They decide the world of every configuration.
- A change to one game stays in that game's files. Shared runtime, runner, agents and evaluation code serve every game.
- Keep the two interaction modes of a configuration identical in world, information, timing, goal and success condition. They differ only in their controls.
- A real-time game and its counterpart differ only in timing.
- Browser checks run headless with fresh temporary profiles. Never control a user's browser or desktop.

## Checks

```bash
pytest
```

`tests/test_generation.py` generates every configuration and checks that generation is deterministic and that each game reports its own mechanic id.
