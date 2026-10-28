# Real Time

## What changes

Real time is an evaluation setting rather than another generated task. The task, seed, difficulty, interaction mode, observation settings, and play-time allowance remain the same between live and paused runs.

The only experimental difference is whether the environment advances while the model produces its next action:

- In live mode, the environment continues during frame collection, model inference, and action execution.
- In paused mode, browser task time advances only during the configured frame-collection window. Native input and synchronous browser event dispatch happen while task time is frozen.

Do not add live-versus-paused branches to an environment. Use the shared clock and evaluation framework.

## Diagnostic definition of a real-time environment

This definition was revised on 2026-08-13 after a source-based pilot over 25 configurations. It classifies which environments actually have a real-time component: visually evidenced task-state change must be used to choose a delayed action, and waiting must lose some part of that action opportunity. The classification is diagnostic and does not appear in result plots unless explicitly requested.

### Symbols

```text
H_t              visible interaction history through task time t
I_t              the agent's own prior actions and task times in H_t
W_t^w            the visible window from t-w through t
u                 terminal task outcome, with less task-active continuation
                  time after delivery of the next action used only to break
                  ties between equal outcomes
D                 one grouped control mode
C_Delta(D)        histories in D from which success remains possible after Delta
                  of no new action
A*_Delta(H_t)     actions maximising expected u when delivered at t+Delta,
                  followed by optimal continuation
H_t^tau           history tau later if the agent supplies no new action
Q(H_t, a)         expected u if a is the next action, followed by optimal continuation
```

Expectations use only visible task information and average over future randomness; private generator or page state is not available to the policy. For a fixed difficulty and interaction configuration, `D` contains every occurrence across seeds, rounds, and attempts of the same outcome-affecting control mode. It is not a hand-picked early interval. `C_Delta(D)` removes only histories whose outcome is already unsalvageable after the delay.

### Definition

A fixed difficulty and interaction configuration of `E` is real-time iff there are a grouped control mode `D`, a delay `Delta > 0`, and a bounded visual window `w` such that `C_Delta(D)` is nonempty and:

```text
(i)    there is no q : I_t -> a
       with q(I_t) in A*_Delta(H_t) for every H_t in C_Delta(D)

(ii)   there is a g : (I_t, W_t^w) -> a
       with g(I_t, W_t^w) in A*_Delta(H_t)
       for every H_t in C_Delta(D)

(iii)  for some H_t in C_Delta(D), action a, and 0 < tau < Delta,
       the environment changes autonomously from H_t to H_t^tau,
       success remains possible from H_t^tau, and

       Q(H_t^tau, a) < Q(H_t, a)

       or

       Q(H_t^tau, a) - Q(H_t^tau, no-op)
         < Q(H_t, a) - Q(H_t, no-op).
```

An unavailable or ineffective action has the value of `no-op`. The strict loss in clause (iii) must be caused by non-clock task-state evolution, not merely by less remaining deadline or later completion. An action becoming enabled or more effective after a fixed wait does not satisfy the clause. In particular, a fixed animation that later enables controls or permanently archives its result is not an expiring opportunity.

The three clauses must be witnessed by the same phenomenon. The autonomous evolution in clause (iii) must be visibly evidenced within `W_t^w`, and that evidence must be what makes the delayed-optimal action depend on observation in clauses (i) and (ii). The window must support prediction of the evolution's effect at `t+Delta`; an unrelated idle animation or future randomness independent of the window cannot supply clause (iii).

The evidence may appear across consecutive frames or as an accumulated visible trace, chart, or trajectory in one screenshot. A single screenshot is therefore allowed when it visibly contains the relevant temporal evidence. This does not admit a static puzzle next to an unrelated animation.

`Delta` is a reported witness horizon on the scale of the mechanic, not the current provider's response latency. It must begin inside a nontrivial active control opportunity and may extend across the point at which that opportunity gets worse or closes. The benchmark's configured `observation_window_ms` and `frames_per_observation` bound `w`; they do not force every environment to need every captured frame.

### Pre-run threshold

For the configuration-level catalog label, a configuration is Not real-time when
at least 50% of its generated instances admit a successful pre-run solution:
after preparation, the solution starts the autonomous outcome phase and sends
no more outcome-affecting actions until that phase ends. Final submission or
certification is administrative and does not count as an action during the run.

### Required interpretation

The conjunction isolates a specific property:

- Clause (i) rules out a fixed schedule or a policy driven only by the agent's own action clock.
- Clause (ii) requires a bounded recent visual window to be sufficient. This excludes unobservable randomness and information that must be recalled only from outside the window.
- Clause (iii) requires a useful action opportunity to get worse inside the delay because the task state changes. This excludes fixed waits, minimum-duration holds solvable from the agent's own clock, and information that remains actionable indefinitely.

Together, the model must use visible evidence of change to predict the state in which its delayed action will land, while some relevant opportunity is being lost. The evidence can be motion across frames or an accumulated visible record such as a market chart. This is not the broader property that task-clock progression can affect an outcome.

A stationary visual policy is not disqualifying. It can map the currently evidenced dynamic state to an action without using absolute task time. Likewise, pausing may affect a deadline, timed script, idle animation, random process, or memory task without making that task real-time under this definition.

In live mode, task time advances during `Delta`, so the prediction problem remains. In paused mode, the game-time delay from the final observation frame through model inference and native input delivery is zero. The live-versus-paused comparison therefore removes this prediction problem specifically for environments satisfying the definition, rather than merely granting extra wall-clock time.

### Principles

```text
P1   Every optimal policy must choose its action from BOTH state and time.
P2   No invented words. Standard terms only.
P3   The verifier reads the OUTCOME. Real-timeness is about how you reach it.
P4   Fixed timed schedule (up 1s, down 1s, right 1s) = NOT real-time.
     The model never looks at the state.
P5   It is a property of the ENVIRONMENT: how it changes between two of
     your actions.
P6   Time-sensitive: waste time, lose something.
P7   Act, wait 100s, act again, no penalty => NOT real-time.
P8   Constant change that only defeats fixed schedules is randomness,
     not real-timeness.
P9   Relevant change must be visually evidenced; the evidence may be an
     accumulated trace in one screenshot.
P10  An optimal stationary policy existing is NOT disqualifying.
P11  As short as possible. Mathematics, not prose.
```

In P1, time means visible temporal evolution of the task state, not an absolute clock input. A stationary policy over that visually evidenced state is consistent with P1 and P10.

P6 includes strict loss of an action's value or advantage, not only total failure. For example, waiting need not reduce the eventual verifier value in Rotating On-Screen Keyboard; the correct mouse target still moves and the old click loses its advantage. The observation-window bound is declared because an unbounded history would incorrectly admit memory tasks such as a code flashed once and typed much later.

### Reference cases

| Case | Result | Reason |
|---|---|---|
| Static CAPTCHA | No | Clauses (i) and (iii) fail. |
| CAPTCHA with an idle animation | No | Clauses (i) and (iii) fail. |
| Fixed up/down/right timed schedule | No | A solution need not study the state. |
| Fixed material response, permanently archived | No | Waiting enables the next control but loses no action opportunity. |
| Minimum-duration hold with a fixed target | No | The agent's own action clock supplies the release schedule. |
| Card shown once and recalled later | No | The declared recent window is insufficient. |
| Code flashed for 200 ms and typed later | No | The declared recent window is insufficient. |
| Market whose visible chart predicts delayed order value | Yes | The chart evidences the price process and an order opportunity loses value. |
| Tilt maze whose ball retains momentum | Yes | Position alone is insufficient, recent motion predicts the delayed state, and the correct control expires. |
| Rotating keyboard controlled by mouse | Yes | Recent motion determines the future location of the required key. |
| The same keyboard controlled by physical keys | No | The correct physical key does not move. |
| Wind tunnel with moving apertures | Yes | Recent motion is needed to predict a time-sensitive opening. |
| Hidden flight with an expiring catcher-commit window | Yes | The visible trajectory predicts the catcher action and flight progress closes that action window. |
| Two-second deadline with no precursor | No | No observation window makes the delayed action knowable. |

The clauses are intentionally independent. Dropping (i) admits known-speed motion solvable by a schedule; dropping (ii) admits deadlines with no observable precursor; dropping (iii) admits measurements that remain actionable indefinitely; omitting the shared-phenomenon requirement admits a static puzzle next to an unrelated animation; and leaving the observation window unbounded admits long-term memory tasks.

## Environment settings

Set three values from the behavior of the environment:

- `observation_window_ms` is the task time covered by one observation.
- `frames_per_observation` is the number of chronological frames captured across that window.
- `play_time_seconds` is the maximum task-active time available for the episode.

Choose the window and frame count with two separate checks:

1. Determine whether any valid solution needs task-clock progress. This includes action-triggered timers, animation or physics ticks, held-input movement, and duration-based gestures even when the agent does not need temporal reasoning. Use a zero-length window only when every required transition can complete synchronously at the paused action boundary.
2. Determine what the agent must observe during that progress. Use one endpoint frame when only the resulting state matters. Use multiple chronological frames when direction, trajectory, phase, or a transient visual state is needed for the next action.

Choose `observation_window_ms` against the environment's actual time constants at all five difficulties, not against whether the task is described as static or temporal. Keep it short enough to preserve useful control opportunities and transient information, but long enough that required progress completes in a practical number of fixed windows. Set `play_time_seconds` so the complete interaction remains feasible and finite.

The latest captured frame remains `obs["screen"]`. The complete chronological sequence is `obs["frames"]`.

Both values remain ordinary Gym-Anything observations. Local runs store the frames in the Gym-Anything episode directory. Remote runs use the normal Gym-Anything master and worker routing, then download the captured frame window into the remote client's local artifact cache. The Weird CUA Qwen 3.5 adapter subclasses Gym-Anything's current `Qwen35VLAgent` and changes only image ingestion so paths, in-memory FastIO images, remote base64 images, and chronological frame sequences are accepted.

## Paused action cycle

The shared paused cycle is:

1. Run the environment for the observation window and capture the configured frames.
2. Pause the environment.
3. Keep it paused throughout model inference and request retries.
4. Arm a browser-visible input barrier while task time remains paused.
5. Deliver the complete native action and confirm trusted browser event dispatch plus synchronous handler completion.
6. Re-scan and pause CSS or Web Animations created by the action.
7. Advance exactly `observation_window_ms`, capture the configured frames, and pause at the exact virtual endpoint.

A click or drag therefore lands on the same virtual world shown at the final observation frame. Native input latency is recorded as wall-time telemetry but does not move the task. A handler can start a timer, animation, or physical transition while paused; that asynchronous effect begins advancing only inside the next fixed observation window. If it is unfinished at the endpoint, the next model observation exposes the unfinished state. The evaluator does not wait for environment-specific action settlement outside the window.

Task time includes continuous wall time in live mode and fixed observation windows in paused mode. Model response time and native input-transport time are excluded only in paused mode. A final provider timeout or failure terminates the episode without advancing paused task time.

The public browser inspector exposes the same settings for visual inspection. It is a demonstration surface rather than an authoritative evaluation run.
