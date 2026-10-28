# Temporal Understanding and Memory

Temporal understanding and memory is a core capability, not a controllable
knob. Classify it for each fixed difficulty and interaction configuration.
Live and paused runs of the same configuration receive the same capability
label; the live-versus-paused setting is handled by the separate real-time
diagnostic.

## Definition

A fixed difficulty and interaction configuration is temporal when every
general screenshot-only solution must use task progression in at least one of
these ways:

1. interpret change, motion, order, or duration across time;
2. remember relevant earlier task state that is no longer visible; or
3. control when, how long, or during which evolving state an action remains
   active.

The temporal relationship must affect successful action choice or execution.
If one general solution works across the configuration's seeds, rounds, and
attempts while ignoring all change, timing, duration, and past state, classify
the configuration as not temporal.

Temporal evidence may span multiple screenshots or be accumulated visibly in
one screenshot, such as a trajectory or market chart.

## Required interpretation

- A fixed timed schedule is temporal, although it is not necessarily
  real-time.
- A fixed-target minimum-duration hold is temporal when the agent must sustain
  or release the action, even when the agent's own clock makes it non-real-time.
- A moving target controlled through changing screen coordinates is temporal.
  The same target controlled through a stationary physical key can be
  non-temporal.
- Relevant information shown earlier and recalled later is temporal memory,
  even when it is not real-time.
- Motion needed only for perception is temporal when the agent must interpret
  that motion, even if the eventual physical action is untimed.
- An idle animation, irrelevant countdown, ordinary deadline, repeated steps,
  automatic transition, or simple visible sequence does not count by itself.
- If one action starts an automatic transition and the agent merely waits for
  the next static state, that transition alone does not make the configuration
  temporal.
- A held movement input is temporal when its continuing effect must be
  sustained, stopped, redirected, or coordinated with the changing task state.

The real-time diagnostic is narrower:

```text
real-time = yes  =>  temporal = yes
temporal = yes   does not imply real-time = yes
```

A real-time configuration uses recent visible temporal evidence to choose a
delayed action whose usefulness is being lost. Temporal configurations also
include fixed timing, long-term memory, and untimed actions based on motion.

## Annotation shape

Store the current classification as:

```text
temporal[environment][interaction][difficulty] in {yes, no}
```

Any recorded reason such as change, memory, or action duration is audit
evidence, not a new public capability category.
