# Retry and First-Failure Policy

Each configuration either ends at its first qualifying failure or lets the player retry. This document gives the rules for deciding which, and for deciding what counts as a failure. Classify a configuration from its instructions, visible interface and mechanics, before looking at any model's outcome. A model's claim that it is exploring cannot establish an exception.

## 1. Initial 15 seconds

Allow observation, with no input, for the first 15 seconds after the task appears. Allow retries if the attempt fails during that interval or becomes impossible to complete. This includes a failure followed by an automatic restart. It excludes the long overall evaluation timeout. If the instance remains solvable, continue to the exploration check.

A failed search for a continuation does not prove impossibility. Keep the classification unresolved when the available evidence cannot settle it.

## 2. Exploration

Allow retries when necessary information about controls or environment behavior must be learned through interaction, and those discovery actions can cause failure. Record all four of the following for every environment:

1. The information missing initially.
2. The interaction that reveals it.
3. How that discovery interaction can cause failure.
4. Any available safe way to learn the same information.

Judge safe alternatives using what a screenshot-only player can discover. Knowledge of private state or of an oracle solution does not establish that the interface explains a safe route. A failure-free solution existing does not by itself eliminate the exploration exception.

Unfamiliar appearance, difficult calculation, forgetting displayed information, and repeating a mistake whose consequence is already known do not establish an exploration exception. Neither does the benchmark's broad exploration capability label by itself.

## 3. Failure boundaries

| Event | Treatment |
|---|---|
| Death, destruction of a required object, or resource exhaustion that makes completion impossible | Failure |
| Rejected committed answer or final submission | Failure |
| Blocked movement, editable placement, or recoverable control correction | Continue |
| Information-gathering probe or explicit preview | Continue |
| Unsuccessful committed execution | Failure |
| Reset following demonstrated failure | The earlier failure remains counted |
| Reset with no demonstrated preceding failure | Insufficient evidence of failure |

For an editor or test control, establish its meaning from the interface and mechanics. An explicit preview or information probe remains available, and a failed committed execution counts. Do not infer that distinction solely from a button's name, a negative message, or the model's explanation.

## 4. Recording the classification

Record `first_failure`, `retry_exception`, or `unresolved` for each configuration, with the relevant failure boundary and evidence. An unresolved classification must remain visible.

For a first-failure configuration, the first qualifying failure is preserved across resets and later submissions. For a retry-exception configuration, the game provides a visible retry that restarts the challenge, and a later valid success passes. In both cases a reset alone does not demonstrate failure, and a zero counter at the end does not prove that no failure happened earlier.
