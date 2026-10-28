# Interaction

## Definition

Interaction is how the computer-use agent uses mouse and keyboard to make an intended action happen in the interface.

The two modes describe the input surface. They do not describe the overall difficulty of the puzzle.

- A simplified mode exposes a proxy that produces an intended action's effect more directly.
- A full mode uses the task-appropriate mouse or keyboard manipulation represented by that proxy.

Examples include click-to-place versus dragging, separate direction controls versus direct movement, or side-panel rotation controls versus direct object manipulation. These are examples rather than a global mapping.

## Decide independently for each environment

Inspect the easiest valid passing path through the current interface. If a side control, shortcut, or two-step proxy stands in for a direct task action, the current interface may be simplified even when the puzzle itself is difficult.

Full does not always mean dragging, WASD, or removing every button. The correct full action depends on what the interface represents. Visible BUY, HOLD, and SELL buttons can be the full interaction for a trading interface while keyboard shortcuts are its simplified mode.

Record:

1. Whether the existing interface is simplified or full.
2. Which intended actions have proxy controls.
3. The task-appropriate input that replaces each proxy.
4. Which actions remain unchanged between modes.

Do not copy another environment's mapping.

## Preserve the task

For a fixed seed and difficulty, both modes must preserve:

- the generated world;
- all information available to the agent;
- the goal;
- action effects;
- physics and timing;
- tolerances and success conditions.

Only the mouse and keyboard procedure for producing the intended action changes. Do not narrow the sensor, expose extra state, change the route, alter the goal, or weaken grading to manufacture a second interaction mode.

Random generation must not depend on interaction mode. Record which input surface produced each controlled action. The grader and verifier must reject a passing transcript produced through the wrong mode.
