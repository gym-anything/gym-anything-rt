# Four source-to-real-time examples

Study these examples before designing or auditing the new game. They illustrate
changes to the decisions and controls required during play. Preserve the source
idea while designing a mechanic whose changing state requires timely action.
The examples do not establish that every variant defeats a strong model.

For each mechanic below, inspect the matching `_v2` environment and its
generator, JS/CSS, Python grader, verifier, controls, and solver.
Follow the target selection's own original source records when creating a game.

## 1. Parallax Orchard: identify, release, and catch

Mechanic: `surreal_apple_on_tree_grid_v2`.

Source idea: inspect fruit and branches from different views to determine which
stems are connected in depth, then harvest those fruit. Visual identification
and planning can happen before release.

Real-time design: plucking starts a physical fall. Gravity, inherited velocity,
and changing wind determine the trajectory. The player steers a basket with
bounded speed and acceleration. Recent motion informs where the basket should
move; waiting can lose a catch that was still possible. Difficulty changes the
basket width and the strength and rate of motion changes.

Lesson: tree sway alone left much of the task solvable through static planning.
The falling fruit adds a control phase with consequences for stale actions.
Keep wind observable and locally predictable. Preserve consistency between
visible fruit, collision geometry, and grading. The corrected revision removes
the hidden minimum of 18 camera-movement events while retaining view coverage.
Its Astra xhigh no-code D5/full/live attempt missed the first catch, with 0/3
caught. That single attempt supplies limited empirical evidence. Native
action-API oracle completion for this falling revision remains unverified;
earlier HTTP success records describe the superseded delivery mechanic.

## 2. Three-Camera Claw Machine: steer through moving geometry

Mechanic: `three_camera_claw_machine_v2`.

Source idea: locate and move a marked object through a cage using several camera
views. The real-time design adds continuously evolving inertial claw motion,
changing wind, independently moving cargo and a destination chute, and delayed
camera views. The player must estimate the current configuration and correct
the claw before gripping or releasing. A coordinate plan becomes stale as the
objects move. D5 combines the cage, decoys, and differently delayed views.

Lesson: couple motion to capture, collision, and delivery. Test whether parking,
freezing a grabbed object, or holding an input eliminates the need for further
observations. Camera delays must remain interpretable and controls responsive.

## 3. Tiny FPS Customs: track before firing

Mechanic: `tiny_fps_customs_v2`.

Source idea: identify warranted targets and protected look-alikes in a maze.
The real-time design makes them walk along independently seeded changing routes.
The current position, motion, and wall occlusion determine whether a shot will
hit the intended target when it is delivered. A missed shot or protected hit
ends the attempt. D5 combines several moving targets, look-alikes, and occlusion.

Lesson: test whether stationary ambushes, repeating patrol loops, or a dense
batch of shots can solve the task without fresh tracking. Preserve continuous
visible motion and physical occlusion. An arbitrary target disappearance or
invisible hit-test discrepancy creates invalid difficulty.

## 4. Parallel Grillmaster: respond to changing cooking rates

Mechanic: `parallel_grillmaster_v2`.

Source idea: cook food and serve it at the right doneness. The real-time design
uses independently changing heating rates with overlapping cooking intervals.
Visible cooking progress informs when each food should be served. The foods
continue cooking during dragging and model decision time. D5 requires handling
several items concurrently with narrow, observable serving opportunities.

Lesson: enforce meaningful overlap so cooking one item at a time cannot remove
the monitoring requirement. A known fixed recipe time is a scheduling problem;
changing visible rates create an observation-dependent serving decision. Rate
variation must permit successful control, and a visible valid serving action
must agree with the grader.

For all four examples, inspect failure cases and successful traces alongside
the design descriptions. Reuse architectural contracts and the lessons from
their defects. Verify the new task independently across its generated states.
