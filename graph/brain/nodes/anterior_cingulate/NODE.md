# anterior_cingulate

Conflict monitoring: it grades the tick against what the manager declared, and it measures
whether the loop is stuck.

**The verdict is mechanical, never a judgment.** It evaluates the unit's `expected` — the
manager's deterministic `Expectation` predicates — against the `ExecutorSummary`, and reports
match or mismatch with the failed predicate ids and the streak. It does not classify *why* a
mismatch happened; the manager does that, in `ManagerPlan.mismatch_class`.

**The six trap detectors read the projected `unit_windows` slice and nothing else.** No trace
file is opened here — history reaches this node as state, which is what keeps a node pure.
Every threshold arrives on `weights`; not one of them is a literal in the node module.

**A signal past its threshold is not a stop.** It escalates the unit to the manager, rung 1 of
the ladder, which may re-plan it, abandon it, or **dismiss** the detector — and a dismissal is
itself a prediction the manager is graded on. Only the ladder's last rung ends a task `stuck`.
That layering is the operator's over-firing constraint made structural: the measure fires early and
cheaply, the stop stays far away.

## Reads

- `task_id`
- `tick`
- `weights`
- `goals`
- `units`
- `unit_windows`
- `trap_dismissals`
- `executor_summary`
- `vetoed_unit_id`
- `wave_status`
- `think_answer`

## Writes

`MonitorVerdict` — match/mismatch, the failed and passed predicate ids, the streak on this
unit, and `traps`: the six scalars, each carrying the weights key that scored it and the
threshold it was scored against, so a `stuck` interrupt's evidence body is rulable.

## Predicts

The next tick's verdict — repeat or clear. Graded by the runtime at the next boundary against
the next tick's `MonitorVerdict.match`.

**And the skip prediction** (build A.1, § Deliverable 1). The cheap check is `live_units` — how many units there are to grade and to measure traps over — read against `firing_threshold`. A skip is a recorded
prediction, not an absence: the `FiringDecision` — the check that ran, the value it read and the
threshold it read it against — rides this node's own journal entry at `call# = 0`, and the
runtime grades it at the next boundary against whether anything for this node arrived in the tick
it skipped.

## Weights

`rut_ticks`, `rut_delta_max`, `forming_ticks`, `rework_spike_ratio`, `rework_window`,
`abandon_count`, `abandon_window`, `mislead_window`, `mislead_rise`, `uncited_ratio`,
`mismatch_streak`, `firing_threshold`, `think_threshold`. `window_len` is derived from five of the
trap keys, never written. `firing_threshold` is build A.1's: the cheap check fires when its score
is >= it, so raising it makes this node skip more. `think_threshold` is build A.2.i's trigger key:
static, so no learner moves it; shipped off; and it gates this node's think in series behind
`firing_threshold`, which reads a different score. Read-only outside sleep.

## Calls

The questions this node's calls ask, read verbatim by the call policy — one line per call type
its rule can plan, used only while its trigger key is on.

- think: Does what the executor summary claims match what its workspace observations show, on each of the predicates this unit declared? Name any predicate where the claim and the evidence disagree; the answer is a signal, and the verdict stays the mechanical grade.
