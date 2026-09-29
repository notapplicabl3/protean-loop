"""Thalamus — what reaches the seat this tick, and what did not, and why.

`the build specification (not in this mirror)` § Deliverable 2's `AdmittedContext` row and
`brain/nodes/thalamus/NODE.md`: "Admission is a **signal**, not a silent filter." Every
exclusion is reported with its reason, so the seat can see the shape of what it was not given.

`max_admitted`, `min_relevance` and `semantic_max_admitted` arrive on `weights`; the module
names none of the three numbers and neither does this battery.

**Build 2's half is per-kind admission** (S-16) **and the body reaching the seat** (S-2). The
chunk candidates below are hand-authored `RetrievedEpisode`s under the `semantic:` prefix the
hippocampus emits, so this battery needs no store on disk and none of `brain/semantic/`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from protean.nodes.thalamus import (
    REASON_BELOW_RELEVANCE,
    REASON_BEYOND_CAPACITY,
    REASON_BEYOND_KIND_QUOTA,
    SUMMARY_CUT_MARKER,
    WEIGHT_MAX_ADMITTED,
    WEIGHT_MAX_SUMMARY_CHARS,
    WEIGHT_MIN_RELEVANCE,
    WEIGHT_SEMANTIC_MAX_ADMITTED,
    admitted_id,
    is_semantic,
    run,
)
from protean.sleep.weights import LOOSEN_UP, SIGNAL_KEY_MAP, bounded_step
from protean.state.inputs import ThalamusInput
from protean.state.outputs import AdmittedContext, RetrievalSet, RetrievedEpisode
from protean.state.semantic import CHUNK_ID_PREFIX
from tests.conftest import REPO_ROOT
from tests.nodes.conftest import TASK_ID


def _retrieval(*scored: tuple[str, float]) -> RetrievalSet:
    return RetrievalSet(
        tick=1,
        candidates=[
            RetrievedEpisode(episode_id=episode, score=score) for episode, score in scored
        ],
    )


def _chunk_id(suffix: str) -> str:
    """A candidate id in the shape the hippocampus emits — the prefix IS the kind."""
    return f"{CHUNK_ID_PREFIX}{suffix}"


def _mixed(*scored: tuple[str, float, str | None]) -> RetrievalSet:
    """One retrieval set of both kinds: `text` is the body for a chunk, `None` for an episode."""
    return RetrievalSet(
        tick=1,
        candidates=[
            RetrievedEpisode(episode_id=item, score=score, text=text)
            for item, score, text in scored
        ],
    )


def _input(weights, retrieval, *, tick=1):
    return ThalamusInput(
        task_id=TASK_ID, tick=tick, weights=dict(weights), retrieval=retrieval
    )


def test_an_empty_retrieval_admits_and_excludes_nothing(thalamus_weights):
    result = run(_input(thalamus_weights, _retrieval()))
    assert isinstance(result, AdmittedContext)
    assert result.emitter == "thalamus"
    assert result.admitted == []
    assert result.excluded == []


def test_every_candidate_is_either_admitted_or_excluded(thalamus_weights):
    """Nothing vanishes: admission is a signal, not a silent filter."""
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 2
    thalamus_weights[WEIGHT_MIN_RELEVANCE] = 0.5
    retrieval = _retrieval(("e1", 0.9), ("e2", 0.8), ("e3", 0.7), ("e4", 0.1))
    result = run(_input(thalamus_weights, retrieval))

    seen = {item.episode_id for item in result.admitted} | {
        item.episode_id for item in result.excluded
    }
    assert seen == {"e1", "e2", "e3", "e4"}
    assert len(result.admitted) + len(result.excluded) == 4


def test_capacity_comes_from_the_weights_key(thalamus_weights):
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 1
    result = run(_input(thalamus_weights, _retrieval(("e1", 0.9), ("e2", 0.8))))
    assert [item.episode_id for item in result.admitted] == ["e1"]
    assert [item.reason for item in result.excluded] == [REASON_BEYOND_CAPACITY]


def test_the_relevance_floor_comes_from_the_weights_key(thalamus_weights):
    thalamus_weights[WEIGHT_MIN_RELEVANCE] = 0.5
    result = run(_input(thalamus_weights, _retrieval(("e1", 0.9), ("e2", 0.4))))
    assert [item.episode_id for item in result.admitted] == ["e1"]
    assert result.excluded == [
        item for item in result.excluded if item.reason == REASON_BELOW_RELEVANCE
    ]
    assert result.excluded[0].episode_id == "e2"


def test_the_two_exclusion_reasons_are_distinguished(thalamus_weights):
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 1
    thalamus_weights[WEIGHT_MIN_RELEVANCE] = 0.5
    result = run(_input(thalamus_weights, _retrieval(("e1", 0.9), ("e2", 0.8), ("e3", 0.1))))
    reasons = {item.episode_id: item.reason for item in result.excluded}
    assert reasons == {"e2": REASON_BEYOND_CAPACITY, "e3": REASON_BELOW_RELEVANCE}


def test_the_floor_is_applied_before_capacity(thalamus_weights):
    """A below-floor candidate does not consume a seat slot it was never eligible for."""
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 2
    thalamus_weights[WEIGHT_MIN_RELEVANCE] = 0.5
    result = run(_input(thalamus_weights, _retrieval(("e1", 0.9), ("e2", 0.1), ("e3", 0.6))))
    assert [item.episode_id for item in result.admitted] == ["e1", "e3"]


def test_candidates_are_ranked_by_score_then_id(thalamus_weights):
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 2
    result = run(_input(thalamus_weights, _retrieval(("b", 0.5), ("a", 0.5), ("c", 0.9))))
    assert [item.episode_id for item in result.admitted] == ["c", "a"]


def test_the_admitted_id_is_derived_from_the_episode_id(thalamus_weights):
    """Stable across a resume: the prediction and the seat's `cited_ids` intersect without a
    counter a replay would advance."""
    result = run(_input(thalamus_weights, _retrieval(("e1", 0.9))))
    assert result.admitted[0].admitted_id == admitted_id("e1")
    assert result.admitted[0].episode_id == "e1"
    assert admitted_id("e1") == admitted_id("e1")


def test_the_admitted_item_carries_its_score(thalamus_weights):
    result = run(_input(thalamus_weights, _retrieval(("e1", 0.42))))
    assert result.admitted[0].score == pytest.approx(0.42)


def test_an_absent_capacity_key_admits_everything_above_the_floor(thalamus_weights):
    thalamus_weights.pop(WEIGHT_MAX_ADMITTED)
    result = run(_input(thalamus_weights, _retrieval(*[(f"e{i}", 0.9) for i in range(20)])))
    assert len(result.admitted) == 20


def test_the_same_input_yields_the_same_admission(thalamus_weights):
    payload = _input(thalamus_weights, _retrieval(("e1", 0.9), ("e2", 0.8)))
    assert run(payload) == run(payload)


def test_the_input_model_is_not_mutated(thalamus_weights):
    payload = _input(thalamus_weights, _retrieval(("e1", 0.9)))
    before = payload.model_dump(mode="json")
    run(payload)
    assert payload.model_dump(mode="json") == before


def test_it_raises_no_interrupt_of_its_own(thalamus_weights):
    assert run(_input(thalamus_weights, _retrieval(("e1", 0.9)))).interrupt is None


# --------------------------------------------------------------------------------------
# Build 2 — per-kind admission, and the body rather than the id (S-2, S-16)
# --------------------------------------------------------------------------------------


def test_the_kind_is_read_off_the_id_prefix():
    assert is_semantic(RetrievedEpisode(episode_id=_chunk_id("aa"), score=1.0, text="body"))
    assert not is_semantic(RetrievedEpisode(episode_id="e1", score=1.0))


def test_a_chunk_is_admitted_with_its_text_as_the_summary(thalamus_weights):
    """The seat receives the body, not the id — the whole of S-2 in one assertion."""
    body = "the paragraph the seat is meant to read"
    result = run(_input(thalamus_weights, _mixed((_chunk_id("aa"), 0.9, body))))
    item = result.admitted[0]
    assert item.summary == body
    assert item.summary != item.episode_id
    assert item.episode_id == _chunk_id("aa")
    assert item.admitted_id == admitted_id(_chunk_id("aa"))


def test_an_episode_still_carries_its_id_as_the_summary(thalamus_weights):
    result = run(_input(thalamus_weights, _mixed(("e1", 0.9, None))))
    assert result.admitted[0].summary == "e1"


def test_an_empty_chunk_body_is_admitted_as_itself_not_as_the_id(thalamus_weights):
    """`text is None` is the kind test, so a chunk never silently reverts to carrying its id."""
    result = run(_input(thalamus_weights, _mixed((_chunk_id("aa"), 0.9, ""))))
    assert result.admitted[0].summary == ""


def test_the_kind_quota_comes_from_its_own_weights_key(thalamus_weights):
    thalamus_weights[WEIGHT_SEMANTIC_MAX_ADMITTED] = 1
    result = run(
        _input(
            thalamus_weights,
            _mixed((_chunk_id("aa"), 0.9, "a"), (_chunk_id("bb"), 0.8, "b")),
        )
    )
    assert [item.episode_id for item in result.admitted] == [_chunk_id("aa")]
    assert [item.reason for item in result.excluded] == [REASON_BEYOND_KIND_QUOTA]


def test_the_kind_quota_reports_its_own_reason(thalamus_weights):
    """Three knobs, three reasons: `beyond max_admitted` against a half-empty context would lie."""
    assert REASON_BEYOND_KIND_QUOTA != REASON_BEYOND_CAPACITY
    assert REASON_BEYOND_KIND_QUOTA != REASON_BELOW_RELEVANCE


def test_chunks_cannot_crowd_the_episodes_out(thalamus_weights):
    """Every chunk outscores every episode, and the episodes are admitted anyway (S-16)."""
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 3
    thalamus_weights[WEIGHT_SEMANTIC_MAX_ADMITTED] = 1
    result = run(
        _input(
            thalamus_weights,
            _mixed(
                (_chunk_id("aa"), 0.9, "a"),
                (_chunk_id("bb"), 0.9, "b"),
                (_chunk_id("cc"), 0.9, "c"),
                ("e1", 0.1, None),
                ("e2", 0.1, None),
            ),
        )
    )
    assert [item.episode_id for item in result.admitted] == [_chunk_id("aa"), "e1", "e2"]


def test_the_episode_half_has_no_quota_of_its_own(thalamus_weights):
    """The sub-quota is one-sided by construction: only the seeded kind is capped."""
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 3
    thalamus_weights[WEIGHT_SEMANTIC_MAX_ADMITTED] = 1
    result = run(_input(thalamus_weights, _retrieval(("e1", 0.9), ("e2", 0.8), ("e3", 0.7))))
    assert len(result.admitted) == 3


def test_the_kind_quota_sits_inside_the_total_capacity(thalamus_weights):
    """`max_admitted` still binds when the sub-quota would have allowed more."""
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 1
    thalamus_weights[WEIGHT_SEMANTIC_MAX_ADMITTED] = 5
    result = run(
        _input(
            thalamus_weights,
            _mixed((_chunk_id("aa"), 0.9, "a"), (_chunk_id("bb"), 0.8, "b")),
        )
    )
    assert len(result.admitted) == 1
    assert [item.reason for item in result.excluded] == [REASON_BEYOND_CAPACITY]


def test_an_absent_kind_quota_key_falls_back_to_the_total_capacity(thalamus_weights):
    thalamus_weights.pop(WEIGHT_SEMANTIC_MAX_ADMITTED)
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 2
    result = run(
        _input(
            thalamus_weights,
            _mixed((_chunk_id("aa"), 0.9, "a"), (_chunk_id("bb"), 0.8, "b")),
        )
    )
    assert len(result.admitted) == 2


def test_every_candidate_of_either_kind_is_still_admitted_or_excluded(thalamus_weights):
    """Nothing vanishes once there are two kinds and three ways out."""
    thalamus_weights[WEIGHT_MAX_ADMITTED] = 2
    thalamus_weights[WEIGHT_SEMANTIC_MAX_ADMITTED] = 1
    thalamus_weights[WEIGHT_MIN_RELEVANCE] = 0.5
    retrieval = _mixed(
        (_chunk_id("aa"), 0.9, "a"),
        (_chunk_id("bb"), 0.8, "b"),
        (_chunk_id("cc"), 0.1, "c"),
        ("e1", 0.7, None),
        ("e2", 0.6, None),
    )
    result = run(_input(thalamus_weights, retrieval))
    seen = {item.episode_id for item in result.admitted} | {
        item.episode_id for item in result.excluded
    }
    assert seen == {_chunk_id("aa"), _chunk_id("bb"), _chunk_id("cc"), "e1", "e2"}
    assert len(result.admitted) + len(result.excluded) == 5
    assert {item.reason for item in result.excluded} == {
        REASON_BELOW_RELEVANCE, REASON_BEYOND_CAPACITY, REASON_BEYOND_KIND_QUOTA
    }


def test_a_mixed_admission_is_still_a_function_of_its_input(thalamus_weights):
    payload = _input(
        thalamus_weights, _mixed((_chunk_id("aa"), 0.9, "a"), ("e1", 0.8, None))
    )
    assert run(payload) == run(payload)


# --------------------------------------------------------------------------------------
# Build A.3 — the summary bound (`the build specification (not in this mirror)` § Deliverable 3, G6)
# --------------------------------------------------------------------------------------

#: A test value `v` with a fractional part, so the cut is seen to fall at `int(v)`.
TEST_BOUND = 40.9

#: A 28 KB-class body — the largest measured section's size — from a run no marker can hide in.
SECTION = "abcdefghij" * 2800

SOURCE_TREES = (
    REPO_ROOT / "src" / "protean" / "nodes",
    REPO_ROOT / "src" / "protean" / "runtime",
)


def test_G6_a_chunk_longer_than_the_bound_is_cut_at_int_v_and_marked(thalamus_weights):
    """The first `int(v)` characters, then the marker: at a test value and at the shipped seed."""
    assert not any(character.isdigit() for character in SUMMARY_CUT_MARKER), "names no number"
    seed = thalamus_weights[WEIGHT_MAX_SUMMARY_CHARS]
    assert len(SECTION) > int(seed), "the section is longer than the shipping bound"
    shipped = run(_input(thalamus_weights, _mixed((_chunk_id("aa"), 0.9, SECTION))))
    assert shipped.admitted[0].summary == SECTION[: int(seed)] + SUMMARY_CUT_MARKER
    assert len(shipped.admitted[0].summary) == int(seed) + len(SUMMARY_CUT_MARKER)

    thalamus_weights[WEIGHT_MAX_SUMMARY_CHARS] = TEST_BOUND
    body = "y" * (int(TEST_BOUND) + 1)
    item = run(_input(thalamus_weights, _mixed((_chunk_id("bb"), 0.9, body)))).admitted[0]
    assert item.summary == body[: int(TEST_BOUND)] + SUMMARY_CUT_MARKER
    assert item.episode_id == _chunk_id("bb")


@pytest.mark.parametrize("length", [0, 1, int(TEST_BOUND) - 1, int(TEST_BOUND)])
def test_G6_a_chunk_of_at_most_int_v_characters_is_whole_with_no_marker(
    thalamus_weights, length
):
    thalamus_weights[WEIGHT_MAX_SUMMARY_CHARS] = TEST_BOUND
    body = "z" * length
    item = run(_input(thalamus_weights, _mixed((_chunk_id("aa"), 0.9, body)))).admitted[0]
    assert item.summary == body
    assert SUMMARY_CUT_MARKER not in item.summary


def test_G6_an_episode_s_summary_is_its_id_under_any_bound(thalamus_weights):
    """The bound reads a chunk's text; an episode has none, so its id is never cut."""
    episode = "an-episode-id-longer-than-the-bound"
    thalamus_weights[WEIGHT_MAX_SUMMARY_CHARS] = 3.0
    assert len(episode) > int(thalamus_weights[WEIGHT_MAX_SUMMARY_CHARS])
    result = run(
        _input(thalamus_weights, _mixed((episode, 0.9, None), (_chunk_id("aa"), 0.8, SECTION)))
    )
    summaries = {item.episode_id: item.summary for item in result.admitted}
    assert summaries[episode] == episode
    assert summaries[_chunk_id("aa")] == SECTION[:3] + SUMMARY_CUT_MARKER, "the bound is on"


def test_G6_with_the_key_absent_every_summary_is_whole(thalamus_weights):
    """The landed behaviour, on the module's own absent-key fallback precedent."""
    thalamus_weights.pop(WEIGHT_MAX_SUMMARY_CHARS)
    result = run(
        _input(
            thalamus_weights,
            _mixed(
                (_chunk_id("aa"), 0.9, SECTION),
                (_chunk_id("bb"), 0.8, "short"),
                ("e1", 0.7, None),
            ),
        )
    )
    summaries = {item.episode_id: item.summary for item in result.admitted}
    assert summaries == {_chunk_id("aa"): SECTION, _chunk_id("bb"): "short", "e1": "e1"}
    assert all(SUMMARY_CUT_MARKER not in summary for summary in summaries.values())


def test_G6_sleep_moves_the_float_seed_by_a_tenth_on_its_one_row(thalamus_weights):
    """`bounded_step(7000.0, LOOSEN_UP, loosening=True) == 7700.0`, and the tightening arm."""
    seed = thalamus_weights[WEIGHT_MAX_SUMMARY_CHARS]
    assert isinstance(seed, float) and seed == 7000.0, "the seed is a float, so the step reaches it"
    rows = [
        (rule.node, rule.key, rule.signal, rule.polarity)
        for rule in SIGNAL_KEY_MAP
        if rule.key == WEIGHT_MAX_SUMMARY_CHARS
    ]
    assert rows == [("thalamus", WEIGHT_MAX_SUMMARY_CHARS, "thalamus_citation", LOOSEN_UP)]
    assert bounded_step(7000.0, LOOSEN_UP, loosening=True) == 7700.0
    assert bounded_step(7000.0, LOOSEN_UP, loosening=False) == 6300.0


@pytest.mark.parametrize("tree", SOURCE_TREES, ids=lambda path: path.name)
def test_G6_no_module_restates_the_summary_bound_s_seeded_value(tree: Path, seed_weights):
    """K5's shape (`tests/runtime/test_semantic_projection.py:193-222`), run for the new key.

    The key **is** a seeded `weights.yaml` key, and a vacuous grep proves nothing, so the value
    set and the tree being walked are both asserted non-empty before their absence means anything.
    """
    weights = seed_weights["thalamus"]
    assert WEIGHT_MAX_SUMMARY_CHARS in weights, f"thalamus/{WEIGHT_MAX_SUMMARY_CHARS}"
    seeded = {float(weights[WEIGHT_MAX_SUMMARY_CHARS])}
    assert seeded, "the value must exist before its absence from the modules means anything"
    assert list(tree.glob("*.py")), "and the tree must hold modules"
    offenders: list[str] = []
    for path in sorted(tree.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=path.name)):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, (int, float))
                and not isinstance(node.value, bool)
                and float(node.value) in seeded
            ):
                offenders.append(f"{path.name}:{node.lineno} = {node.value}")
    assert offenders == [], offenders
