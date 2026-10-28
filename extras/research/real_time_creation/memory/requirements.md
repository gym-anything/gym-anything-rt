# Real-time construction requirements

These requirements apply to the creator and every independent auditor.

## What real time means

The authoritative definition is in
`docs/real-time.md`. Read it in full, including
the mathematical criterion, grouped control modes, and pre-run threshold.

During an active control opportunity, the player must use visible evidence of
task-state evolution to choose an action for the state in which it will execute.
The environment advances while the player observes, reasons, and sends input.
For a reported positive delay Delta and bounded recent visual window w, all
three conditions must hold for the same outcome-affecting phenomenon:

1. The player's prior actions and their times alone cannot determine the
   delayed-optimal action across the relevant still-solvable states.
2. Those prior actions together with the recent visible window are sufficient
   to choose that action, accounting for future randomness in expectation.
3. Autonomous task-state evolution can make a previously useful action lose
   value or advantage within the delay, while success is still possible.
   The window must evidence the evolution responsible for that loss.

Report concrete states, actions, w, and Delta that witness each condition.
Delta is tied to the mechanic's time scale. It is independent of a particular
provider's current response latency. A visible trace in one screenshot can
contain sufficient temporal evidence. Multiple images are needed when the
relevant motion cannot be inferred from one image. Retaining memories from
an arbitrarily old observation does not satisfy the bounded-window condition.

A countdown, idle animation, fixed wait, or minimum hold duration alone does
not establish real time. A static decision beside moving decoration also fails
the definition. Random changes that cannot be anticipated from visible evidence
violate observability. Motion should remain continuous and locally trackable.
Seeded variation may be reproducible; it must change the decisions sufficiently
to defeat an observation-free fixed schedule. Avoid repeating trajectories that
let the player solve by memorizing a period.

Apply the catalog's pre-run threshold: a configuration is Not real-time when
at least 50% of generated instances admit success after preparation with no
further outcome-affecting action during the autonomous run. Administrative
submission does not count. Test plausible pre-positioning, parking, fixed
scripts, and one-batch solutions across declared seeds. Report sample sizes
and results; a failed search does not prove no such policy exists.

Evaluate the whole relevant control mode across seeds and occurrences. A
hand-picked difficult interval cannot establish the configuration's label.
Preserve meaningful real-time control across all five difficulties and both
interaction variants. If a variant removes that demand, revise or report it;
do not silently label it real-time.

## Difficulty and fairness

Difficulty 5 should challenge highly capable agents, including Astra xhigh.
Design for sustained observation and timely correction: interacting moving
objects, inertia, changing but visible motion, competing control demands, or
several overlapping opportunities can supply that difficulty. Explain the
specific source-derived mechanic and its strongest plausible shortcut.

Difficulty must remain human-manageable and demonstrably solvable. Use visible
geometry and physically consistent rules. Avoid hidden movement-event counts,
arbitrary action quotas, tiny unreadable targets, teleportation, unobservable
future choices, and deadlines shorter than any feasible observation/action
response. Extra repeated rounds alone do not establish harder decisions.
Do not tune the grader to reject a visibly valid solution. Renderer, hit tests,
physics, server grader, and exported verifier must agree.

Choose difficulty parameters that change perception, prediction, planning, or
control. Document their effects at all five levels and assign the baseline
level from the actual design. Keep full and simplified interaction comparable:
simplified controls must preserve the moving world, information, tolerances,
timing, and outcome. They must not offer auto-aim, perfect interception, or
an automatic catch absent from the full interaction task.

Inspection before starting a challenge may be safe. During the active real-time
challenge, test every stop, brake, clutch, hold, drag, reset, retry, and submit
control for ways to remove the intended temporal demand. Holding an input must
not silently freeze unrelated motion. Use visible consequences for actual
failures and apply the approved task-specific retry policy below. Difficulty
does not authorize a universal first-failure restriction.

### Retry eligibility and failure boundaries

Read `docs/retry-policy.md`. Apply the procedure to the new mechanics; do not
copy another environment's classification.

Classify before inspecting model outcomes. Observe the initial instance for
15 seconds without input. If it fails or becomes impossible to complete,
allow retries; include a failure followed by automatic restart and exclude
the long overall evaluation timeout. Otherwise assess necessary exploration.
Record all four fields: missing information, the interaction that reveals it,
how that discovery risks failure, and any discoverable safe alternative.
Allow retries when necessary discovery risks failure and no discoverable safe
alternative exists. A known oracle solution does not establish safe learning.
A Start button establishes safe initial observation only. It does not settle
the exploration check. A broad exploration label or the model's explanation
does not establish an exception either.

For a first-failure task, preserve the first qualifying failure across resets
and subsequent submissions. For a retry-exception task, provide a working
visible retry path and permit a subsequently successful valid attempt to pass.
Keep failures recorded in evidence. Never clear history to manufacture success.
Retries must restart the challenge rather than provide a pause or rewind during
an active attempt. Keep the evaluator's existing time and step budgets.

Explicit previews, information probes, blocked movement, reversible edits,
and recoverable control corrections remain available under either policy.
Preserve existing within-attempt mistake allowances. Count actual death,
irrecoverable loss, or a rejected committed answer at its established boundary.
A reset alone does not demonstrate failure; zero final counters do not prove
the absence of earlier failures. Document these boundaries per task and test
the UI, live server, export, and independent verifier together. Assess all ten
variants if their available information or recovery behavior differs.

## Required evidence

Save evidence under the target environment's `evidence_docs/`:

- Source records and links, the transformation, the three real-time witnesses,
  difficulty parameters, intended controls, failure rules, and shortcut tests.
- All ten difficulty/interaction combinations loading and behaving correctly;
  live evolution and exact framework pause behavior; negative submissions;
  grader, export, and verifier agreement; fresh-seed checks and regression tests.
- Successful complete solutions on multiple declared seeds. Include D5 in both
  interaction modes. Every solution action must use the same mouse/keyboard
  HTTP action API exposed to downstream models, with the same timing semantics
  and declared budgets. Privileged state may support oracle planning, and must
  be disclosed. Direct Playwright clicks, DOM focus or mutation, internal game
  function calls, and injected successes cannot establish action-space parity.
- A recorded solution film and action trace bound to source hashes, seed,
  difficulty, interaction, execution mode, and grader/verifier results. Save
  MP4/WebM and a manifest under `evidence_docs/solution_videos/`, matching the
  existing manifest schema. Isolated headless browser capture may record the
  result; actual oracle actions must pass through the model's action API.
- A comparison of timely observation-driven control with delayed observations
  and a plausible preplanned or parked policy. Keep generated instances and
  initial conditions matched. Report outcomes and timing at declared settings.
  Such a diagnostic supports the proposed mechanism; it is not a model score.

Read `docs/fast-io.md` before native validation. Use the approved
same-host direct action/screenshot route and preserve the evaluator. Check
resources and the 15% node-local free-space floor before staging or launching.
No new paid model evaluations, authentication changes, or cluster allocations
are authorized by this prompt. Run model calibration only with explicit run
authorization. Record model and human evidence separately, including coverage
and limitations. A single model failure does not establish general difficulty;
an infrastructure or grader failure cannot count as a model failure. Never
claim human validation or a model score that has not been measured.

## File scope and implementation boundaries

Allowed implementation paths, relative to `benchmarks/gym_anything_rt/`, are the new
target environment directory; its own
`shared_runtime/app/mechanics/<mechanic>.js` and `.css`;
`shared_runtime/server/incubator_graders/<mechanic>.py`;
`shared_scripts/incubator_generators/<mechanic>.py`;
`shared_runtime/assets/provenance/<mechanic>_v0.json`;
`solvers/<mechanic>.py`; `splits/<environment>_split.json`;
and adding only this environment's entries to `real_time.json` and
`pairs.json`. Task-specific tests may be added under repository
`tests/`. Place temporary diagnostic scripts in `evidence_docs/` or `/tmp`.

Preserve existing environments, shared runners, model adapters, evaluation
harnesses, clocks, browser/server frameworks, dashboards, shared tools, and
historical artifacts. Implement live and paused behavior through the shared
clock. Do not add task-level live/paused branches. Compare changes against the
starting worktree; preserve unrelated edits and other creators' files. Do not
discard, stash, or overwrite them. Use a branch, never a Git worktree.

### Shared runtime scope

Do not change core code to build a new game. Assess each new environment against the existing, frozen harness. Verify that
its physics uses the shared clock, remains still while that clock is paused,
accepts the existing action API, and has the required task-specific evidence.
Do not add stricter shared-clock, screenshot-metadata, or acknowledgement-field
requirements as prerequisites for finishing environment construction.

Record findings attributable to the unchanged shared runtime in a separate
shared-runtime findings section, preserving raw failures and uncertainties.
These findings do not authorize shared-code repairs or task-side workarounds.
Missing task evidence, an incompatible task, task-caused timing defects, and
unproved solvability still require revision. A scoped construction PASS covers
the environment checks that were actually completed; it does not certify the
shared runtime or turn any failed protocol check into a pass.

Only isolated headless browser processes with fresh temporary profiles may be
used for browser validation. Never access the user's live browser or desktop.
Open and inspect the actual rendered screenshots and recordings. A successful
build or a claimed solver pass alone does not establish visual correctness.
