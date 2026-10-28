# Real-time environment construction

Create a new, self-contained real-time game from the supplied original source
material. The target directory is reserved for this new environment. Read the
complete matching `picks` entry in `--selection-file`, the selection criteria at
`--survey-root/selection/SELECTION_CRITERIA.md`, every cited `survey_ids` record
under `dashboard/data/entries/`, and the original sources those records cite.
Record source IDs as `source_anchors` and explain the source-to-game design in
the target's `evidence_docs/`. Preserve the selection, survey, existing games,
and historical results. Existing games supply architectural examples; derive
the new real-time mechanic from the source idea.

Read `requirements.md` and `examples.md` in this prompt directory in full.
Also read `AGENTS.md`, `docs/real-time.md`, `docs/retry-policy.md`, and every
file under `docs/controllability/`. Follow the real-time definition and
validation requirements in those documents and this profile. Build the full
environment contract: env.json, task, generator, browser mechanic, independent
grader, exported verifier, solver, controls, registry entries, split, and tests.

Design an ambitious difficulty-5 task with observable, time-sensitive decisions.
State what has to be observed, how the world changes while an action is being
chosen, and why a delayed action loses value. Actively test ways to finish from
one initial plan, exploit periodic motion, or stop meaningful task evolution.
Revise the design when such a strategy removes the intended real-time demand.
Construct five meaningful difficulty levels and both interaction modes under
the shared controllability framework. Keep each same-seed interaction pair's
world, information, timing, physics, goal, and success condition identical.

Keep edits inside the file scope in `requirements.md`. Snapshot the starting
Git status and scoped diff for attribution. Do not alter shared infrastructure
to accommodate the game. Report an infrastructure blocker with evidence.
Browser checks must use isolated headless processes and fresh temporary
profiles. Never control the user's browser, desktop, or foreground applications.

Implement, exercise, and revise the game. Save rendered screenshots, solution
recordings, exact commands, action traces, independent grader results, and the
real-time and difficulty checks in `evidence_docs/`. Execute the solvability
demonstration through the downstream model's action API. Follow the distinction
between implementation checks, privileged oracle planning, human calibration,
and model evaluation in `requirements.md`. Finish with an evidence-backed
implementation report. Missing checks must remain explicitly identified.
