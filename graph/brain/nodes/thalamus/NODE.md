# thalamus

The gate on attention, and the most load-bearing node in the build: it decides what reaches
the seat this tick out of what the hippocampus retrieved.

Admission is a **signal**, not a silent filter. `AdmittedContext` carries the admitted subset
*and* what was excluded and why, so the seat can see the shape of what it was not given. A
node that quietly dropped material would be choosing, which deterministic nodes do not do.

It runs after the hippocampus and before the gate: the thalamus gates what was retrieved, and
the gate's go/no-go is the last step before the act.

Admission is **per kind**. A seeded semantic chunk and an episode carry scores on different
scales, so they are never ranked against each other for one capacity: `semantic_max_admitted`
is a sub-quota inside `max_admitted`, and neither kind can crowd the other out. A chunk is
admitted with its **text** as the summary, so the seat receives the body rather than the id —
**bounded**: the text is admitted up to `max_summary_chars` characters (the integer part of the
number) and marked where cut, and it is whole when the key is absent.

## Reads

- `task_id`
- `tick`
- `weights`
- `retrieval`
- `goals`
- `units`

## Writes

`AdmittedContext` — each admitted item with a stable `admitted_id`, plus the exclusions with
their reasons. An episode's `summary` is its id; a chunk's is its text up to
`max_summary_chars` characters, marked when cut.

## Predicts

Which admitted items the seat will cite this tick. Graded by the runtime at the next boundary
against `cited_ids` intersected with this tick's `AdmittedContext.admitted`.

**And the skip prediction** (build A.1, § Deliverable 1). The cheap check is `retrieved_candidates` — how much the hippocampus retrieved **this tick** — read against `firing_threshold`. A hippocampus that declined reaches this node as `None` rather than as last tick's answer, and scores zero. A skip is a recorded
prediction, not an absence: the `FiringDecision` — the check that ran, the value it read and the
threshold it read it against — rides this node's own journal entry at `call# = 0`, and the
runtime grades it at the next boundary against whether anything for this node arrived in the tick
it skipped.

## Weights

`max_admitted`, `min_relevance`, `semantic_max_admitted`, `firing_threshold`,
`max_summary_chars` — read-only outside sleep. `firing_threshold` is build A.1's: the cheap
check fires when its score is >= it, so raising it makes this node skip more.
