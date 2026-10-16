---
description: Solve a mathematical-modelling problem end to end, headless.
argument-hint: "[problem statement, or path to the statement file]"
skills: modelling
---

Run the whole modelling loop on the problem below, using the `modelling` skill as
the procedure and the `mathmodel` MCP server as the compute.

$ARGUMENTS

Do it in this order, and do not stop early:

1. If the argument is a path, read it; otherwise treat the text as the statement.
2. Call `mcp__mathmodel__run_task` with the full statement. That runs the agent headless:
   it decides the decision variables, builds the model, solves it numerically,
   validates the solution, plots, and writes up. Pass `max_steps` 60 unless the
   problem is large.
3. If the run reports it could not solve something, fix the specific gap yourself
   with `run_python` rather than narrating a method you did not execute.
4. Present the result as the report the competition wants: model assumptions,
   formulation, numerical answer with units, validation, sensitivity, and the
   figure files. Every number must trace to a cell you ran.

Never answer a sensitivity question by multiplying a shadow price by the proposed
change. `shadow_price_analysis` exists because that product is wrong exactly when
the problem is interesting; use it and report its valid range.
