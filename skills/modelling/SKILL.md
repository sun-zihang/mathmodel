# Mathematical Modelling

Procedure for turning a competition problem into a defensible, executed solution.
The rule that governs everything below: **a number you did not compute does not
belong in the report.**

## 1. Read the statement for its structure, not its topic

Write down three things before choosing any method:

- **Decision variables** — what is actually being chosen. If you cannot name them,
  you do not have a model yet, you have a topic.
- **Objective** — one scalar, with units. "Profit" is not an objective;
  "thousand yuan per week of total contribution margin" is.
- **Constraints** — each one as an inequality with a right-hand-side number and a
  sentence saying *why* it binds. Classify each as resource / technology / policy.

State every assumption as a numbered list in the report. Implicit assumptions are
where marks are lost, because a marker cannot tell whether you forgot them or chose
them.

## 2. Pick the model by the shape of the problem

| What the problem looks like | Reach for | Why |
|---|---|---|
| Allocate limited resources among activities, linear returns | LP → `solve_lp_max` | Gives optimum **and** shadow prices |
| Same, but whole units / yes-no choices | ILP (`pulp` CBC, else branch-and-bound) | LP rounding is not a solution |
| Sequence of decisions, current choice affects later payoff | DP or a recurrence | Greedy silently fails here |
| Rate of change described in words | ODE, integrate with `rk4` | Analytic solution often unavailable |
| Relationship between observed quantities | Regression (`ols`), then residual check | Correlation ≠ mechanism |
| Ranking/scoring with many criteria | AHP / entropy / TOPSIS | Only if the weights are justified |
| Classification or prediction with labelled data | Train/test split, cross-validation | A fit on all data proves nothing |
| Stated system with randomness | Simulation with explicit seed + replications | One run is an anecdote |

Prefer the simplest model that answers the question. A model more complex than the
data is a common and heavily-penalised mistake.

## 3. Solve, then validate — validation is not optional

A solution with no validation is a guess with more digits. Always:

1. **Feasibility by substitution.** Feed the answer back into every constraint
   explicitly. Report the slack of each binding constraint.
2. **Independent second path.** Solve the same problem a different way and require
   agreement — LP by two solvers, ODE by a coarser step, sum by a closed form.
   `mathmodel` runs a pure-python simplex alongside scipy for exactly this; the two
   must agree on the objective *and* the duals.
3. **Degenerate inputs.** Empty set, one element, all-equal, zero denominator. A
   function that crashes on these will crash on real data.
4. **Units.** Multiply through and check the units close. Dimensional errors are
   the fastest way to lose credibility.

## 4. Sensitivity — the part most teams get wrong

- A shadow price is **local**. It holds only until the basis changes. Multiplying it
  by a proposed increase is wrong precisely when the increase is large enough to be
  worth asking about. Use `shadow_price_analysis`, which re-solves and reports the
  range over which the marginal actually holds.
- Report the *valid interval*, not just a rate: "A is worth 1 per tonne, but only
  for the first 5 tonnes; beyond that the binding constraint switches and the gain
  flattens."
- Perturb every parameter you assumed fixed, ±10%, and say which conclusions
  survive. If nothing is sensitive, say so — that is a finding.

## 5. Write it up

Order that scores: restate the problem in your own words → assumptions → notation
→ model → **solution method** → numerical results → validation → sensitivity →
discussion of limitations → what you would do with more data.

- Every figure cites the code that produced it.
- Limitations are stated by you, before the marker finds them.
- No result is described as robust without a sensitivity table behind it.

## 6. Failure modes to refuse

- Presenting a model but no numbers.
- Numbers from a solver that reported infeasible/unbounded.
- An LP rounded to integers and called an ILP answer.
- `R²` quoted without looking at residuals.
- A chart whose axis is truncated to exaggerate a difference.
- Citing an algorithm you did not run.
