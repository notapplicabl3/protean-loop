# basal_ganglia

The gate. It has one verb — veto — and it is one of exactly two contractual inhibitions in the
whole build; homeostasis's stop is the other.

**The veto predicate is catastrophic-only.** `no_go` iff either (a) an `Expectation` argument
path in the pending unit lies outside the task workspace root as narrowed by any `path_scope`
constraint — `intent` is prose and contributes no path — or (b) the unit carries
`irreversible: true` and no `Constraint` of kind `allow_irreversible` names it. Nothing else
vetoes.

**A `no_go` is inhibition, not advice.** A.1 requires it to inhibit the dispatch wave and
delegates for the pending unit, while think and escalate remain allowed. The current runtime
also skips the selected cortex seat on that tick. The tick still completes; a veto is recorded
as a failing observation with zero change. Do not assume the manager can re-plan on that same
tick: `runtime/cycle.py`'s `skip_seat` branch suppresses it. Reconciliation of this broader seat
suppression with the inherited replanning path remains a design question.

## Reads

- `task_id`
- `tick`
- `weights`
- `pending_unit`
- `admitted`
- `constraints`
- `workspace_root`

## Writes

`SelectionVerdict` — `go` / `no_go` plus the veto reason when it fires.

## Predicts

That the unit it let through will not be abandoned or trap-flagged this tick. Graded by the
runtime at the next boundary against that unit's `UnitObservation`: `abandoned` false and no
trap scalar past its threshold.

**And the skip prediction** (build A.1, § Deliverable 1). The cheap check is `pending_unit` and it is **structural** — a pending unit is present, or it is not — so it reads **no threshold key at all** and this folder's `weights.yaml` stays the empty mapping. The veto therefore always runs when a unit is pending; a tick with none is the `NO_SUBJECT` case build 3's admissible set already scores as no evidence. A skip is a recorded
prediction, not an absence: the `FiringDecision` — the check that ran, the value it read and the
threshold it read it against — rides this node's own journal entry at `call# = 0`, and the
runtime grades it at the next boundary against whether anything for this node arrived in the tick
it skipped.

## Weights

None, deliberately. Both arms of the veto are contractual, so neither is a number anyone may
retune; the file carries an empty mapping rather than a tunable that would invite loosening a
catastrophic-only gate.
