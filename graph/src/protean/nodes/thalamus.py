"""Thalamus — what reaches the seat this tick, and what did not, and why.

`the build specification (not in this mirror)` § Deliverable 2's `AdmittedContext` row and
`brain/nodes/thalamus/NODE.md`: "Admission is a **signal**, not a silent filter."

**Every exclusion is reported with its reason.** A node that quietly dropped material would be
choosing, which deterministic nodes do not do — so `AdmittedContext` carries the admitted subset
*and* `ExcludedItem`s, and the seat can see the shape of what it was not given.

**`admitted_id` is derived, not minted.** It is a stable function of the episode id, so the
thalamus's prediction ("which admitted items the seat will cite this tick") and the seat's
`cited_ids` can be intersected across a resume without a counter that a replay would advance.

**Admission is per kind, and that is the whole of build 2's change here** (folded: S-16). An
episode's score is recency times stack overlap; a seeded chunk's is term overlap in `[0, 1]`.
Those are not one scale, so they do not compete for one capacity: `semantic_max_admitted` is a
sub-quota **inside** `max_admitted`, and a store of chunks can no more crowd out this task's own
episodes than the reverse. The kind is read off the id prefix the hippocampus emitted, which is
why § Deliverable 3 fixed a prefix rather than adding a discriminator field.

**A chunk is admitted with its body up to the summary bound, an episode with its id** (folded:
S-2; `the build specification (not in this mirror)` § Deliverables 2 and 3). `summary` is what this tick's
`AdmittedContext` carries, and the body reaches a seat on `workspace.admitted` only — a
`WaveMember` references it and names no path (`the build specification (not in this mirror)`
§ Deliverable 3). A chunk's `RetrievedEpisode.text` is copied there up to the integer part of
`max_summary_chars` and ends in `SUMMARY_CUT_MARKER` when, and only when, it was cut; with the
key absent it is copied whole, the landed behaviour. The bound applies here, in the node, so the
committed `AdmittedContext` carries it. An episode has no `text` and keeps the id it always
carried.

`max_admitted`, `min_relevance`, `semantic_max_admitted` and `max_summary_chars` arrive on
`weights`; this module names none of the numbers.
"""

from __future__ import annotations

from protean.state.calls import FiringDecision
from protean.state.enums import NodeName
from protean.state.inputs import ThalamusInput
from protean.state.outputs import AdmittedContext, AdmittedItem, ExcludedItem, RetrievedEpisode
from protean.state.semantic import CHUNK_ID_PREFIX

WEIGHT_MAX_ADMITTED = "max_admitted"
WEIGHT_MIN_RELEVANCE = "min_relevance"
WEIGHT_SEMANTIC_MAX_ADMITTED = "semantic_max_admitted"

#: The summary bound (build A.3, § Deliverable 3): a chunk's text is admitted up to the integer
#: part of this key's value. The key absent (or `null`) leaves every summary whole.
WEIGHT_MAX_SUMMARY_CHARS = "max_summary_chars"

#: What a cut summary ends in, and only a cut one — the cut is a signal, not a silent filter. It
#: names no number, so it cannot restate the seed it reports.
SUMMARY_CUT_MARKER = " [... cut by the thalamus's summary bound]"

#: This node's firing threshold and the check it names (§ Deliverable 1, seam contract C3).
WEIGHT_FIRING = "firing_threshold"
CHECK_RETRIEVED_CANDIDATES = "retrieved_candidates"

#: The reasons an exclusion carries. Closed by construction: there are exactly three ways out,
#: one per knob. The third landed with the per-kind quota (build 2, S-16) and is named
#: separately rather than folded into the second because "admission is a signal, not a silent
#: filter" — an operator reading `beyond max_admitted` against a half-empty context would be
#: reading a false one.
REASON_BELOW_RELEVANCE = "below min_relevance"
REASON_BEYOND_CAPACITY = "beyond max_admitted"
REASON_BEYOND_KIND_QUOTA = "beyond semantic_max_admitted"


def admitted_id(episode_id: str) -> str:
    """A stable id derived from the episode's, so it survives a resume unchanged."""
    return f"admitted:{episode_id}"


def is_semantic(candidate: RetrievedEpisode) -> bool:
    """Whether this candidate is a seeded chunk, read off the id prefix § Deliverable 3 fixed."""
    return candidate.episode_id.startswith(CHUNK_ID_PREFIX)


def retrieved(payload: ThalamusInput) -> list[RetrievedEpisode]:
    """What the hippocampus retrieved **this tick** — an empty list when nothing reached here.

    `ThalamusInput.retrieval` is optional in build A.1: the projection boundary stamp-tests the
    slot, so a hippocampus that declined this tick arrives as `None`. An absent required input
    **is** this consumer's own "nothing for me" condition (§ Deliverable 1, folded: S-A92), and
    reading it as an empty retrieval is what keeps last tick's answer from wearing this tick's
    authority.
    """
    return [] if payload.retrieval is None else list(payload.retrieval.candidates)


def retrieved_candidates(payload: ThalamusInput) -> float:
    """How much there is to admit from. The cheap check's score."""
    return float(len(retrieved(payload)))


def firing_check(payload: ThalamusInput) -> FiringDecision:
    """The cheap check, beside the body (§ Deliverable 1, seam contract C3).

    It **fires when the score is ≥ its threshold**, so **raising** `firing_threshold` makes the
    node skip more (folded: S-A91). A slot the boundary withheld scores zero — the bottom of the
    scale — so whether an empty retrieval skips this node is a number in `weights.yaml` and never
    a branch in the wiring.
    """
    threshold = float(payload.weights.get(WEIGHT_FIRING, 0.0))
    value = retrieved_candidates(payload)
    return FiringDecision(
        tick=payload.tick,
        node=NodeName.THALAMUS,
        check=CHECK_RETRIEVED_CANDIDATES,
        key=WEIGHT_FIRING,
        value=value,
        threshold=threshold,
        fired=value >= threshold,
    )


def run(payload: ThalamusInput) -> AdmittedContext:
    """Admit the most relevant candidates up to capacity; report every exclusion with a reason."""
    candidates = retrieved(payload)
    capacity = int(payload.weights.get(WEIGHT_MAX_ADMITTED, len(candidates)))
    kind_quota = int(payload.weights.get(WEIGHT_SEMANTIC_MAX_ADMITTED, capacity))
    floor = float(payload.weights.get(WEIGHT_MIN_RELEVANCE, 0.0))
    bound = payload.weights.get(WEIGHT_MAX_SUMMARY_CHARS)
    limit = None if bound is None else int(bound)

    ranked = sorted(candidates, key=lambda item: (-item.score, item.episode_id))
    admitted: list[AdmittedItem] = []
    excluded: list[ExcludedItem] = []
    chunks_admitted = 0
    for candidate in ranked:
        semantic = is_semantic(candidate)
        if candidate.score < floor:
            excluded.append(
                ExcludedItem(episode_id=candidate.episode_id, reason=REASON_BELOW_RELEVANCE)
            )
        elif len(admitted) >= capacity:
            excluded.append(
                ExcludedItem(episode_id=candidate.episode_id, reason=REASON_BEYOND_CAPACITY)
            )
        elif semantic and chunks_admitted >= kind_quota:
            excluded.append(
                ExcludedItem(episode_id=candidate.episode_id, reason=REASON_BEYOND_KIND_QUOTA)
            )
        else:
            chunks_admitted += int(semantic)
            text = candidate.text
            if text is not None and limit is not None and len(text) > limit:
                text = text[:limit] + SUMMARY_CUT_MARKER
            admitted.append(
                AdmittedItem(
                    admitted_id=admitted_id(candidate.episode_id),
                    episode_id=candidate.episode_id,
                    # The body for a chunk, the id for an episode — `text` is `None` for one and
                    # never for the other, so the kind decides this and no default has to.
                    summary=candidate.episode_id if text is None else text,
                    score=candidate.score,
                )
            )

    return AdmittedContext(tick=payload.tick, admitted=admitted, excluded=excluded)
