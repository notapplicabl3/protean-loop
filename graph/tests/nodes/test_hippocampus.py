"""Hippocampus — episodic memory. One call per tick: it fetches, it never chooses.

`the build specification (not in this mirror)` § Deliverable 2's `RetrievalSet` row and
`brain/nodes/hippocampus/NODE.md`. The candidates arrive **projected** — the runtime's boundary
loader reads the last `candidate_window` records of this task's `episodes.jsonl` — so the node
opens no file and the window is a weights key rather than a literal.

`recency_weight` and `min_score` arrive on `weights`; this battery reads both out of the seed
file, never restating a number.

**Build 2's half is the semantic chunk, and it is driven from hand-authored chunks** — never
from `brain/semantic/`, which is gitignored and absent on a fresh clone. The chunks below are
constructed through `SemanticChunk.of()`, so their `chunk_id` and `terms` are derived by the
same code intake uses and the battery cannot drift from the store's real shape.
"""

from __future__ import annotations

import pytest

from protean import config
from protean.nodes.hippocampus import (
    WEIGHT_MIN_SCORE,
    WEIGHT_RECENCY,
    WEIGHT_SEMANTIC_MIN_OVERLAP,
    live_terms,
    run,
    semantic_overlap,
)
from protean.state.enums import EpisodeKind
from protean.state.inputs import HippocampusInput
from protean.state.outputs import RetrievalSet
from protean.state.records import EpisodeRecord, GoalSnapshot, UnitSnapshot
from protean.state.semantic import CHUNK_ID_PREFIX, SemanticChunk
from tests.nodes.conftest import GOAL_ID, TASK_ID, UNIT_ID, goal, unit

#: `goal()` says "do the thing" and `unit()` intends "write the file", so the live vocabulary of
#: a payload carrying both is exactly these three tokens — "do" is under the length floor and
#: "the" is on the stop list. Every chunk below is written against this set rather than against
#: a number, so the coverage fractions asserted are readable from the text itself.
LIVE_TERMS = {"thing", "write", "file"}


def _chunk(text: str, *, store: str = "docs") -> SemanticChunk:
    """One hand-authored chunk, its id and terms derived exactly as intake derives them."""
    return SemanticChunk.of(
        store=store, source=store, text=text, manifest_revision="rev-test"
    )


def _record(tick: int, *, goals=(), units=()) -> EpisodeRecord:
    return EpisodeRecord(
        schema_version=config.EPISODE_SCHEMA_VERSION,
        episode_id=f"{TASK_ID}:{tick}",
        task=TASK_ID,
        tick=tick,
        kind=EpisodeKind.TICK,
        goals=[GoalSnapshot(id=item, status="open") for item in goals],
        units=[UnitSnapshot(id=item, status="pending") for item in units],
    )


def _input(weights, candidates, *, goals=(), units=(), tick=5, semantic=()):
    return HippocampusInput(
        task_id=TASK_ID,
        tick=tick,
        weights=dict(weights),
        goals=list(goals),
        units=list(units),
        candidates=list(candidates),
        semantic=list(semantic),
    )


def _stacked(weights, *, semantic=(), candidates=()):
    """A payload with the live stacks `LIVE_TERMS` describes."""
    return _input(
        weights, candidates, goals=[goal()], units=[unit()], semantic=semantic
    )


def test_no_candidates_retrieves_nothing(hippocampus_weights):
    result = run(_input(hippocampus_weights, []))
    assert isinstance(result, RetrievalSet)
    assert result.emitter == "hippocampus"
    assert result.candidates == []
    assert result.tick == 5


def test_the_newest_candidate_scores_full_recency(hippocampus_weights):
    result = run(_input(hippocampus_weights, [_record(1), _record(2)]))
    newest = next(item for item in result.candidates if item.episode_id == f"{TASK_ID}:2")
    assert newest.score == pytest.approx(1.0)


def test_recency_decays_by_the_weights_key_per_record_of_age(hippocampus_weights):
    decay = float(hippocampus_weights[WEIGHT_RECENCY])
    result = run(_input(hippocampus_weights, [_record(1), _record(2), _record(3)]))
    scores = {item.episode_id: item.score for item in result.candidates}
    assert scores[f"{TASK_ID}:3"] == pytest.approx(1.0)
    assert scores[f"{TASK_ID}:2"] == pytest.approx(decay)
    assert scores[f"{TASK_ID}:1"] == pytest.approx(decay**2)


def test_stack_overlap_lifts_a_record_that_names_a_live_goal(hippocampus_weights):
    plain = _record(1)
    overlapping = _record(2, goals=[GOAL_ID])
    result = run(
        _input(hippocampus_weights, [plain, overlapping], goals=[goal()], units=[])
    )
    scores = {item.episode_id: item.score for item in result.candidates}
    assert scores[f"{TASK_ID}:2"] == pytest.approx(2.0), "recency 1.0 × (1 + full overlap)"
    assert scores[f"{TASK_ID}:1"] < scores[f"{TASK_ID}:2"]


def test_overlap_is_the_fraction_of_referenced_ids_still_live(hippocampus_weights):
    record = _record(1, goals=[GOAL_ID, "g-dead"], units=[UNIT_ID, "u-dead"])
    result = run(
        _input(hippocampus_weights, [record], goals=[goal()], units=[unit()])
    )
    assert result.candidates[0].score == pytest.approx(1.0 * (1 + 0.5))


def test_a_record_referencing_nothing_has_no_overlap_term(hippocampus_weights):
    result = run(_input(hippocampus_weights, [_record(1)], goals=[goal()]))
    assert result.candidates[0].score == pytest.approx(1.0)


def test_the_min_score_floor_drops_the_rest(hippocampus_weights):
    hippocampus_weights[WEIGHT_MIN_SCORE] = 0.9
    result = run(_input(hippocampus_weights, [_record(1), _record(2), _record(3)]))
    assert [item.episode_id for item in result.candidates] == [f"{TASK_ID}:3"]


def test_the_floor_comes_from_the_weights_and_nowhere_else(hippocampus_weights):
    """Raise it past every score and the node returns nothing — no literal survives it."""
    hippocampus_weights[WEIGHT_MIN_SCORE] = 99.0
    assert run(_input(hippocampus_weights, [_record(1), _record(2)])).candidates == []


def test_results_are_ordered_by_score_then_id(hippocampus_weights):
    result = run(_input(hippocampus_weights, [_record(1), _record(2), _record(3)]))
    scores = [item.score for item in result.candidates]
    assert scores == sorted(scores, reverse=True)


def test_ties_break_on_the_episode_id(hippocampus_weights):
    hippocampus_weights[WEIGHT_RECENCY] = 1.0
    result = run(_input(hippocampus_weights, [_record(2), _record(1)]))
    assert [item.episode_id for item in result.candidates] == [
        f"{TASK_ID}:1",
        f"{TASK_ID}:2",
    ]


def test_it_does_not_decide_what_the_seat_sees(hippocampus_weights):
    """Every candidate above the floor is returned; the admission is the thalamus's, downstream."""
    candidates = [_record(tick) for tick in range(1, 6)]
    hippocampus_weights[WEIGHT_MIN_SCORE] = 0.0
    assert len(run(_input(hippocampus_weights, candidates)).candidates) == 5


def test_the_projection_is_the_only_input_it_reads(hippocampus_weights):
    """No file is opened, so the call is a function of its argument: twice is once."""
    payload = _input(hippocampus_weights, [_record(1), _record(2)])
    assert run(payload) == run(payload)


def test_the_input_model_is_not_mutated(hippocampus_weights):
    payload = _input(hippocampus_weights, [_record(1)], goals=[goal()])
    before = payload.model_dump(mode="json")
    run(payload)
    assert payload.model_dump(mode="json") == before


def test_it_raises_no_interrupt_of_its_own(hippocampus_weights):
    assert run(_input(hippocampus_weights, [_record(1)])).interrupt is None


# --------------------------------------------------------------------------------------
# Build 2 — the semantic chunk, on its own scale, against its own floor (S-2, S-16, S-25)
# --------------------------------------------------------------------------------------


def test_the_live_vocabulary_is_the_goal_and_unit_text_tokenised(hippocampus_weights):
    """The query side of the match, built by intake's own tokenizer so both sides agree."""
    assert live_terms([goal()], [unit()]) == LIVE_TERMS


def test_overlap_is_the_fraction_of_the_live_vocabulary_the_chunk_carries():
    assert semantic_overlap(["thing", "write", "file"], LIVE_TERMS) == pytest.approx(1.0)
    assert semantic_overlap(["thing"], LIVE_TERMS) == pytest.approx(1 / 3)
    assert semantic_overlap(["quite", "unrelated"], LIVE_TERMS) == pytest.approx(0.0)


def test_overlap_is_bounded_by_one_however_long_the_chunk():
    long_chunk = _chunk("write the file about the thing " * 40)
    assert semantic_overlap(long_chunk.terms, LIVE_TERMS) == pytest.approx(1.0)


def test_an_empty_live_vocabulary_scores_nothing_rather_than_dividing_by_zero():
    assert semantic_overlap(["thing"], set()) == pytest.approx(0.0)


def test_a_matching_chunk_is_emitted_under_its_semantic_id_with_its_text(hippocampus_weights):
    chunk = _chunk("write the file that names the thing")
    result = run(_stacked(hippocampus_weights, semantic=[chunk]))

    assert [item.episode_id for item in result.candidates] == [chunk.chunk_id]
    assert result.candidates[0].episode_id.startswith(CHUNK_ID_PREFIX)
    assert result.candidates[0].text == chunk.text, "the body rides with the id (S-2)"
    assert result.candidates[0].score == pytest.approx(1.0)


def test_an_episode_carries_no_text(hippocampus_weights):
    result = run(_stacked(hippocampus_weights, candidates=[_record(1)]))
    assert result.candidates[0].text is None


def test_the_chunk_floor_comes_from_its_own_weights_key(hippocampus_weights):
    """One third of the live vocabulary: kept under the seeded floor, dropped above it."""
    chunk = _chunk("a thing, described at length and in some detail")
    assert (
        semantic_overlap(chunk.terms, LIVE_TERMS)
        >= hippocampus_weights[WEIGHT_SEMANTIC_MIN_OVERLAP]
    )
    assert run(_stacked(hippocampus_weights, semantic=[chunk])).candidates

    hippocampus_weights[WEIGHT_SEMANTIC_MIN_OVERLAP] = 0.5
    assert run(_stacked(hippocampus_weights, semantic=[chunk])).candidates == []


def test_a_chunk_sharing_no_vocabulary_is_dropped(hippocampus_weights):
    assert run(
        _stacked(hippocampus_weights, semantic=[_chunk("entirely other subject matter")])
    ).candidates == []


def test_the_two_floors_are_separate_scales(hippocampus_weights):
    """`min_score` never reaches a chunk and `semantic_min_overlap` never reaches an episode."""
    chunk = _chunk("write the file that names the thing")
    hippocampus_weights[WEIGHT_MIN_SCORE] = 99.0
    kept = run(_stacked(hippocampus_weights, semantic=[chunk], candidates=[_record(1)]))
    assert [item.episode_id for item in kept.candidates] == [chunk.chunk_id]

    hippocampus_weights[WEIGHT_MIN_SCORE] = 0.0
    hippocampus_weights[WEIGHT_SEMANTIC_MIN_OVERLAP] = 99.0
    kept = run(_stacked(hippocampus_weights, semantic=[chunk], candidates=[_record(1)]))
    assert [item.episode_id for item in kept.candidates] == [f"{TASK_ID}:1"]


def test_both_kinds_ride_the_one_existing_candidates_list(hippocampus_weights):
    chunk = _chunk("write the file that names the thing")
    result = run(_stacked(hippocampus_weights, semantic=[chunk], candidates=[_record(1)]))
    assert isinstance(result, RetrievalSet)
    assert {item.episode_id for item in result.candidates} == {
        chunk.chunk_id, f"{TASK_ID}:1"
    }


def test_no_semantic_slice_leaves_the_episode_half_untouched(hippocampus_weights):
    """A brain root with no intake behind it: the field defaults empty and nothing changes."""
    payload = _input(hippocampus_weights, [_record(1), _record(2)])
    assert payload.semantic == []
    assert [item.episode_id for item in run(payload).candidates] == [
        f"{TASK_ID}:2", f"{TASK_ID}:1"
    ]


def test_the_chunk_half_opens_no_file_either(hippocampus_weights):
    """Still a function of its argument once the store is in the picture: twice is once."""
    payload = _stacked(hippocampus_weights, semantic=[_chunk("write the thing to a file")])
    assert run(payload) == run(payload)


def test_the_input_model_is_not_mutated_by_the_chunk_half(hippocampus_weights):
    payload = _stacked(hippocampus_weights, semantic=[_chunk("write the thing to a file")])
    before = payload.model_dump(mode="json")
    run(payload)
    assert payload.model_dump(mode="json") == before
