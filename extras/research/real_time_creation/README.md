# Real-Time Minigame Creation

This pipeline builds one new real-time minigame from a surveyed source idea. A creator agent implements the minigame and records evidence of its behavior. Independent auditor agents then check the implementation and the evidence, and the creator revises the minigame until an audit passes. This is the construction loop described in the Gym-Anything-RT paper.

The creator implements the full environment: its specification and tasks, the generator, the browser interface, the server grader, the exported verifier, an oracle solver, the five difficulty levels and two interaction modes, the real-time settings, and tests. It may edit only the files of its own minigame. It runs all ten configurations in the live and paused settings and saves screenshots, recordings and command outputs under the environment's `evidence_docs/`.

## Prerequisites

- Gym-Anything-RT installed from a checkout, with Sandweave for the native validation runs: `uv pip install -e ".[sandweave]"`.
- The [Codex CLI](https://github.com/openai/codex) on `PATH` and logged in. `--codex-bin` or `CODEX_BIN` selects another binary.
- A survey directory that contains `selection/SELECTION_CRITERIA.md` and one record per surveyed source under `dashboard/data/entries/`.
- A selection file whose `picks` list has exactly one entry with `env_dir` equal to the new environment. The entry cites its `survey_ids`.

## Running

Create an empty folder for the new environment, then start the loop from the repository root:

```bash
mkdir -p benchmarks/gym_anything_rt/environments/new_game_env
python -m extras.research.real_time_creation.method \
  --env-dir new_game_env \
  --selection-file /path/to/selection.json \
  --survey-root /path/to/survey
```

The loop runs in three phases:

1. **Creation.** The creator reads the selection, the survey records and their original sources, these prompts and the docs they cite, then builds and exercises the minigame.
2. **Blind recheck.** The creator is asked to reread its instructions and finish anything it missed. `--blind-nudges` sets how many rechecks run, and the default is one.
3. **Audit.** A fresh auditor session, with no access to the creator's reasoning, explores the repository and writes a report. The creator receives the report and fixes the issues it raises. Each round uses a new auditor. `--audit-rounds` sets the maximum, and the default is three.

The command exits with 0 when an audit passes and with 2 when the last audit still requires revision.

The default model is `gpt-6.1-sol` with `max` reasoning effort. `--model` and `--reasoning-effort` change both agents.

To resume a creator session at a later phase, pass its session id and the phase index:

```bash
python -m extras.research.real_time_creation.method \
  --env-dir new_game_env \
  --selection-file /path/to/selection.json \
  --survey-root /path/to/survey \
  --session-id <creator-session-id> --start-idx 2
```

## Outputs

- `benchmarks/gym_anything_rt/environments/<env>/evidence_docs/`: the creator's evidence.
- `audits/real_time_creation/audit_<env>.md`: the latest audit report.
- `creation_audit_logs/real_time_creation/<env>.jsonl`: one record per phase.

`--audits-dir` and `--logs-dir` move the last two.

## Prompts

`memory/` holds the instructions that both agents receive:

- `creation_prompt.md` for the creator.
- `audit_prompt.md` for each auditor.
- `requirements.md`, the shared definition of a valid real-time minigame and the evidence it needs.
- `examples.md`, four released minigames that show how a source idea became a real-time mechanic.

Both agents also read `AGENTS.md`, [docs/real-time.md](../../../docs/real-time.md), [docs/retry-policy.md](../../../docs/retry-policy.md), [docs/fast-io.md](../../../docs/fast-io.md) and [docs/controllability/](../../../docs/controllability).

Agents never control your browser or desktop. Browser checks run headless with fresh temporary profiles.
