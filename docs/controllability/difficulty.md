# Difficulty

## What a level describes

A difficulty level describes the exact task configuration that the agent receives. It does not describe the environment idea or the hardest version that could be built.

- The existing configuration may belong at any level from L1 through L5. Never place it at L3 by default.
- L5 is the benchmark's highest named profile. It is not a claim that the environment cannot be made harder.
- The five labels have one meaning across the benchmark. They are not five equal divisions of each environment's parameter range.
- Assignments remain open to revision when human and computer-use-agent results provide better evidence.

## Inspect before assigning

Read the complete task specification, generator, browser implementation, grader, verifier, solver, and current control file. Identify the parameters and rules that are active in the configuration shown to the agent.

Do not count unused options, inactive metadata, verifier-only ticks, minimum-action checks, or grader quotas as difficulty. Do not infer difficulty from the environment name, task description, or an earlier label.

Use the existing controlled environments as calibration examples before assigning the current level. For each example, inspect the actual current task and the code that determines its visible problem and success condition. Reading only its `controls.json` summary is not enough. Compare the new task with the approved examples at nearby levels and state why it belongs above some examples and below others.

## Construct the profiles

First determine the existing configuration's level. For a fixed seed, that profile must preserve the existing generated challenge and visible behavior exactly. Build the lower and higher profiles around that reference point.

Do not preserve user-facing text that objectively contradicts the existing generator and grader. Repair only the inconsistent text. Record the historical and corrected contracts. Prove that the generated world, success condition, timing, observation surface, and assigned level remain unchanged.

Change parameters that alter the problem the agent must solve. Depending on the environment, these can include:

- information available to the agent;
- visual ambiguity or scene complexity;
- number of variables that must be handled together;
- dependencies between decisions;
- planning depth or topology;
- motion speed and timing windows;
- action precision and control sensitivity;
- recovery options and consequences of mistakes.

Do not use a universal formula. The effect of a parameter depends on the task. Faster motion can make one task harder and another easier. More objects can add ambiguity or provide useful visual evidence.

More steps, rounds, ticks, actions, or waiting do not by themselves make a task harder. Repetition matters when an earlier action changes the state needed for later decisions. A longer route matters when its topology, dependencies, or control requirements change the solution rather than merely extending it.

For every adjacent pair, state what changes in the agent's decision or control problem. If that difference cannot be stated from the implementation, the profiles have not yet been distinguished.

## Keep the axes separate

Difficulty may include task motion, timing, precision, or control sensitivity. Real time separately determines whether the environment advances while the model is producing its next action. Do not freeze task speed merely because the benchmark also has a real-time axis.

Difficulty profiles must not silently swap the interaction mode. Interaction profiles must not silently change the generated problem.
