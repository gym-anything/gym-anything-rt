# Controllability

Every Gym-Anything-RT minigame is controllable along three axes: its difficulty level, its interaction mode, and the clock that decides whether it waits for the agent. These documents define each axis and how to validate a minigame against them.

Read them in this order:

1. The repository `AGENTS.md`.
2. [difficulty.md](difficulty.md): what the five levels mean and how to construct them.
3. [interaction.md](interaction.md): the simplified and full interaction modes.
4. [../real-time.md](../real-time.md): when a configuration counts as real-time.
5. [temporal.md](temporal.md): the temporal understanding and memory capability label.
6. [validation.md](validation.md): the checks a finished minigame must pass.

[../retry-policy.md](../retry-policy.md) decides whether a configuration ends at its first failure or allows retries.

New minigames are built and audited with the pipeline in [extras/research/real_time_creation](../../extras/research/real_time_creation), whose prompts require these documents.
