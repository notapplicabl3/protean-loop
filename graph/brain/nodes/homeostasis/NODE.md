# homeostasis

Hypothalamus + insula: the brain's interoception. It measures what the task has spent —
tokens, wall time, errors, ticks, cumulative for this task — reports the ceilings in force
after any `resume --extend` override, and raises the one contractual stop a deterministic node
is allowed to raise.

It runs **first** in the cycle because the seat reads its numbers off the workspace, so they
must exist before the seat is asked anything.

Its stop is inhibition, not advice. When a ceiling is crossed the terminal is `stopped`, and
that terminal is **committed at the boundary** like any other: every later model call is suppressed while the remaining node steps still run their firing
checks. Bodies remain subject to those checks. The process exits after the commit, never
before it.

## Reads

- `task_id`
- `tick`
- `weights`
- `cost`
- `ceiling_overrides`
- `constraints`
- `think_answer`

## Writes

`HomeostasisReport` — the read-out of `BrainState.cost`, the ceilings after
`ceiling_overrides`, and the `stop` flag. It writes no file: the runtime holds the output in
state and journals it.

## Predicts

The next tick's cost in its own units. Graded by the runtime at the next boundary against the
next tick's report deltas.

**And the skip prediction** (build A.1, § Deliverable 1). The cheap check is `ceiling_pressure` — the largest fraction of any ceiling in force this task has consumed — read against `firing_threshold`. **It gates this node's think call and never its body:** the ceiling evaluation and the `stop` flag are contractual and always run. A skip is a recorded
prediction, not an absence: the `FiringDecision` — the check that ran, the value it read and the
threshold it read it against — rides this node's own journal entry at `call# = 0`, and the
runtime grades it at the next boundary against whether anything for this node arrived in the tick
it skipped.

## Weights

`max_ticks`, `max_tokens`, `max_wall_seconds`, `max_error_rate`, `firing_threshold`,
`think_threshold` — read-only outside sleep; the offline sleep graph is their only writer.
`firing_threshold` is build A.1's: the cheap check fires when its score is >= it, so raising it
makes this node skip more. `think_threshold` is build A.2.i's trigger key: static, so no learner
moves it; shipped off; and it gates this node's think in series behind `firing_threshold`, which
reads the same score.

## Calls

The questions this node's calls ask, read verbatim by the call policy — one line per call type
its rule can plan, used only while its trigger key is on.

- think: Given this task's cost counters and the ceilings in force in the context sent, how close is it to exhausting its budget, and is that spend on course for the work it has bought or running ahead of it? Answer as a signal only: it can neither raise nor suppress the stop, which the ceilings decide on their own.
