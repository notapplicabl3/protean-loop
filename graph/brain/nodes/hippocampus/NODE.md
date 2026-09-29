# hippocampus

Episodic memory: one scheduled step per tick retrieves candidates when its firing check runs
the body. The runtime separately composes the **previous** tick's episode at the boundary;
outer-node model calls are separate journalled calls, not extra node steps.

It fetches. It does not choose what the seat sees — the thalamus does that, downstream, and
the exclusion it makes stays visible.

The candidates are the last `candidate_window` records of **this task's** `episodes.jsonl`,
projected by the runtime's boundary loader. Build 3 writes project memory and loads project-scoped habits and priors; it does not add
cross-task episode retrieval to this input. The node does not open the file itself.

Build 2 adds a second kind on the same path: the `semantic_window` chunks of the seeded lexical
store that the boundary loader kept for this tick, projected on `semantic`. They arrive the same
way the episodes do — as data, already narrowed, with no file opened here — and they are scored
on their **own** scale, term overlap in `[0, 1]` against `semantic_min_overlap`, never against
`min_score`. Chunks and episodes are never ranked against each other; the id prefix is what makes
the kind readable downstream.

## Reads

- `task_id`
- `tick`
- `weights`
- `goals`
- `units`
- `candidates`
- `semantic`

## Writes

`RetrievalSet` — candidates with retrieval scores, each carrying the stable `episode_id` the
thalamus admits on and the grader keys on. A chunk rides the same list under its own
`semantic:<sha>` id and carries its `text`, so the body — not the id — can reach the seat. The
runtime writes the composed `EpisodeRecord` at the boundary; the node writes nothing.

## Predicts

That what it retrieved will be **cited** by the seat that consumed it. Graded by the runtime at
the next boundary against `cited_ids` on that tick's seat result, intersected with the
`episode_id`s it returned.

**And the skip prediction** (build A.1, § Deliverable 1). The cheap check is `projected_candidates` — how many episode records and chunks the boundary loader handed over — read against `firing_threshold`. A skip is a recorded
prediction, not an absence: the `FiringDecision` — the check that ran, the value it read and the
threshold it read it against — rides this node's own journal entry at `call# = 0`, and the
runtime grades it at the next boundary against whether anything for this node arrived in the tick
it skipped.

## Weights

`candidate_window`, `recency_weight`, `min_score`, `semantic_window`, `semantic_min_overlap`,
`firing_threshold` — read-only outside sleep. `firing_threshold` is build A.1's: the cheap check
fires when its score is >= it, so raising it makes this node skip more.
