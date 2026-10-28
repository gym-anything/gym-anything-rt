# Independent audit of a source-derived real-time game

Read `requirements.md` and `examples.md` in this prompt directory in full.
Read the source selection entry, original survey records, and cited sources.
Read `docs/real-time.md`, `docs/retry-policy.md`, and the controllability
documents in `docs/controllability/`. Independently
inspect the generator, browser implementation, grader, verifier, controls,
solver, tests, and visible evidence for the target environment.

Do not modify the implementation. Write only the requested audit report and
isolated reproduction artifacts in the target's `evidence_docs/`. Use fresh
headless browser profiles; never touch the user's live browser or desktop.

Do not create additional catalog-discoverable `solution_videos/manifest.json`
copies while archiving audit evidence. Keep diagnostic manifest copies under
non-discoverable names or in a separate private temporary directory, preserving
their bytes and provenance. An audit must not break the target's media export.
Task-owned media packaging can be repaired by the creator within the existing
catalog contract; it does not require a catalog or core change.

Check each of these requirements and cite supporting artifacts:

1. Source grounding: does the new game develop the original source idea into
   real-time interaction? Are the sources recorded and existing environments
   preserved?
2. Real time: independently test all three clauses of the settled definition
   for the same phenomenon. Inspect the declared window, delay, action
   opportunities, and seeds. Test the pre-run threshold and plausible fixed
   schedules. Static games cannot pass this profile. Motion alone is insufficient.
3. Difficulty: does D5 impose substantial observable prediction and control
   demands? Challenge the strongest shortcut. Test pauses, held drags, brakes,
   resets, repetitive motion, static preparation, action batches, and repeated
   submissions. Check that success remains feasible at the declared timing.
   Hidden quotas, arbitrary rejection, and impossible reaction windows are
   blocking defects. Inspect meaningful ordering from D1 through D5.
4. Interaction: do full and simplified controls preserve the same world,
   information, timing, physics, goal, and success condition at each difficulty
   and seed? Check that simplified controls retain the real-time decision.
5. Execution modes: does live evolution continue during model decision time,
   and does the shared framework freeze task time correctly in paused mode?
   Inspect chronological frames and timing records. Task-specific branches or
   silent alternate input/capture paths violate the contract.
6. Solvability and integrity: verify successful complete action-API traces on
   multiple seeds, including both D5 interaction modes. Reconcile visible
   geometry, hit tests, physics, grading, export, and the actual verifier.
   Playwright-only solutions do not meet action-space parity. Privileged oracle
   planning must be disclosed. Reproduce any previously failing timing check.
7. Failure: apply the approved initial 15-second test and all four exploration
   fields in requirements.md to the actual new mechanics. Independently justify
   first_failure or retry_exception before looking at model outcomes. Check
   previews, probes, corrections, existing mistake allowances, and committed
   failure boundaries. First-failure tasks must preserve qualifying failures;
   retry-exception tasks must allow a visible retry followed by a valid success.
   Verify both paths through the UI, server grade, export, and task verifier.
   Preserve evidence of earlier failures and keep the evaluator unchanged.
8. Evidence and scope: inspect rendered images and recordings yourself. Audit
   task-attributable changes against the starting worktree and allowed paths.
   Leave unrelated pre-existing work untouched. Check that empirical model
   scores, human calibration, implementation tests, and design hypotheses are
   clearly distinguished. Do not demand invented model or human evidence.

Missing evidence required by `requirements.md`, demonstrated shortcuts removing
real-time control, unsolvable instances, or scope violations require revision.
List the concrete issue, reproduction, and evidence needed to resolve it.
Unavailable infrastructure is a verification blocker; it cannot count as a
game pass or model failure. A PASS certifies the scoped construction audit and
its recorded checks; human calibration and unrun model evaluations retain their
own statuses.

Apply the shared runtime scope rules in `requirements.md`. Separate
task-attributable defects and missing task evidence from findings in the
unchanged shared runtime. Record the latter with their evidence and remaining
limitations without requiring core repairs. Do not introduce new protocol
guarantees. Preserve previous reports and failed checks. State explicitly what
the scoped construction verdict establishes and what remains unverified.

Save the complete report to the requested audit file. End it with exactly one
of these markers:

`AUDIT_VERDICT: PASS`

`AUDIT_VERDICT: REVISION_REQUIRED`
