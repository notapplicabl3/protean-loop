"""Hippocampus — episodic memory. Its scheduled body fetches when its firing check allows it.

`the build specification (not in this mirror)` § Deliverable 2's `RetrievalSet` row, § Deliverable 3 (the
single call that "composes the previous tick's `EpisodeRecord` … *and* retrieves for this one,
which keeps every node to one call per tick"), and `brain/nodes/hippocampus/NODE.md`.

**The candidates arrive projected.** The runtime's boundary loader reads the last
`candidate_window` records of *this task's* `episodes.jsonl` and hands them over on
`HippocampusInput.candidates`; the node opens no file. Build 3 adds project memory and priors,
but the current projection still retrieves episode candidates only from this task.

**Scoring is recency plus stack overlap, and both terms are mechanical.** Recency decays by
`recency_weight` per record of age, so the newest candidate scores 1.0. Overlap is the fraction
of the record's goal and unit ids that are still live, which is what makes the goal and unit
stacks part of this node's read slice rather than decoration. `min_score` drops the rest.

**Build 2 adds a second kind on the same path, and a second scale.** `HippocampusInput.semantic`
carries the boundary loader's slice of the seeded lexical store, and a chunk is scored by *term*
overlap with the live goal and unit text — a fraction in `[0, 1]` against its own floor,
`semantic_min_overlap`, never against `min_score`. The two kinds share `RetrievalSet.candidates`
and nothing else: they are not comparable numbers and the thalamus admits them under separate
quotas, so neither can crowd the other out (folded: S-16). The chunk rides under its own
`semantic:<sha>` id **with its text** (folded: S-2). The text reaches the thalamus, which admits
it to the seats bounded by its summary key; `latest.hippocampus`'s copy of the text never
reaches a seat (`the build specification (not in this mirror)` § Deliverable 2), so the thalamus is the
body's only route to a seat.

**It does not decide what the seat sees.** That is the thalamus, downstream, and the exclusion
it makes stays visible.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from protean.state.calls import FiringDecision
from protean.state.enums import NodeName
from protean.state.inputs import HippocampusInput
from protean.state.outputs import RetrievalSet, RetrievedEpisode
from protean.state.semantic import terms_of

WEIGHT_RECENCY = "recency_weight"
WEIGHT_MIN_SCORE = "min_score"
WEIGHT_SEMANTIC_MIN_OVERLAP = "semantic_min_overlap"

#: This node's firing threshold and the check it names (§ Deliverable 1, seam contract C3).
WEIGHT_FIRING = "firing_threshold"
CHECK_PROJECTED_CANDIDATES = "projected_candidates"


def _overlap(record, live_goal_ids: set[str], live_unit_ids: set[str]) -> float:
    """The fraction of a record's referenced ids that are still on the stacks."""
    referenced = [goal.id for goal in record.goals] + [unit.id for unit in record.units]
    if not referenced:
        return 0.0
    live = live_goal_ids | live_unit_ids
    return sum(1 for item in referenced if item in live) / len(referenced)


def live_terms(goals: Sequence, units: Sequence) -> set[str]:
    """The live task's vocabulary: the tokens of every open goal's text and every unit's intent.

    The tokenizer is `protean.state.semantic.terms_of()` — the same one that produced a chunk's
    `terms` at intake — so the two sides of the match are lower-cased, stop-listed and minimum-
    length filtered identically. A query built with a different tokenizer would silently miss.
    """
    return set(
        terms_of(*[goal.text for goal in goals], *[unit.intent for unit in units])
    )


def semantic_overlap(chunk_terms: Iterable[str], query: set[str]) -> float:
    """The fraction of the live vocabulary this chunk carries, in `[0, 1]`.

    The denominator is the *query*, not the chunk: § Deliverable 3 and S-15 both phrase the
    measure as overlap **with** the live goal and unit text, and a chunk-sided denominator would
    cap a long document's best possible score at `len(query) / len(chunk_terms)` — which would
    make one floor un-seedable across stores whose chunks differ in size by two orders of
    magnitude. Empty query, no overlap: nothing is live to be relevant to.

    The cost of this reading is a length bias toward big documents, recorded in the dispatch
    ledger; the run's `cited_ids` is the observable that settles it (§ Named assumptions 9).
    """
    if not query:
        return 0.0
    return len(query & set(chunk_terms)) / len(query)


def projected_candidates(payload: HippocampusInput) -> float:
    """How much there is to retrieve from: the episode records and the chunks handed over.

    The cheap check's score. It counts what the boundary loader projected — it opens nothing and
    scores nothing — so a tick whose window came back empty has nothing for this node to rank.
    """
    return float(len(payload.candidates) + len(payload.semantic))


def firing_check(payload: HippocampusInput) -> FiringDecision:
    """The cheap check, beside the body (§ Deliverable 1, seam contract C3).

    It **fires when the score is ≥ its threshold**, so **raising** `firing_threshold` makes the
    node skip more (folded: S-A91). A declining hippocampus runs no body and leaves its
    `LatestOutputs` slot exactly as last tick left it; the projection boundary is what stops that
    slot from reaching the thalamus.
    """
    threshold = float(payload.weights.get(WEIGHT_FIRING, 0.0))
    value = projected_candidates(payload)
    return FiringDecision(
        tick=payload.tick,
        node=NodeName.HIPPOCAMPUS,
        check=CHECK_PROJECTED_CANDIDATES,
        key=WEIGHT_FIRING,
        value=value,
        threshold=threshold,
        fired=value >= threshold,
    )


def run(payload: HippocampusInput) -> RetrievalSet:
    """Score this task's recent episodes by recency and stack overlap, and its chunks by terms."""
    decay = float(payload.weights.get(WEIGHT_RECENCY, 1.0))
    floor = float(payload.weights.get(WEIGHT_MIN_SCORE, 0.0))
    goal_ids = {goal.id for goal in payload.goals}
    unit_ids = {unit.id for unit in payload.units}

    newest = len(payload.candidates) - 1
    scored: list[RetrievedEpisode] = []
    for position, record in enumerate(payload.candidates):
        recency = decay ** (newest - position)
        score = recency * (1.0 + _overlap(record, goal_ids, unit_ids))
        if score >= floor:
            scored.append(RetrievedEpisode(episode_id=record.episode_id, score=score))

    # The chunks, on their own scale against their own floor. Two `if`s and two appends rather
    # than one merged ranking: putting them on one scale is exactly what S-16 refuses.
    overlap_floor = float(payload.weights.get(WEIGHT_SEMANTIC_MIN_OVERLAP, 0.0))
    query = live_terms(payload.goals, payload.units)
    for chunk in payload.semantic:
        overlap = semantic_overlap(chunk.terms, query)
        if overlap >= overlap_floor:
            scored.append(
                RetrievedEpisode(episode_id=chunk.chunk_id, score=overlap, text=chunk.text)
            )

    scored.sort(key=lambda item: (-item.score, item.episode_id))
    return RetrievalSet(tick=payload.tick, candidates=scored)
