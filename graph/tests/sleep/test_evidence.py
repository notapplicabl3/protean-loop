"""Row L1 clause 3: the classifier admits a pair only when all four tests hold.

`the build specification (not in this mirror)` § Deliverable 1 (the admissible-set table), § Directional
decisions 18, § Resolutions A1-8, A1-13, D3-2, D3-3, and § DoD row L1's third clause
(decomposed onto order W2 by ledger entry V2-1).

**One fixture per exclusion reason, each landing in `SleepReport.excluded` under its own key** —
which is the row's own check. The two the row names by hand are here as their own cases: the
empty-`episode_ids` pair and the `NO_SUBJECT` gate prediction.

**The archive is the seventh fixture and the only one nobody authored.** The last test drives
the real `brain/archive/workload-run-*/` directory and asserts what the SPEC says must be true of
it: run 1's executor pairs are excluded before a candidate can form, which is the whole of
"Legs 1 and 5 are the same argument from both ends".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean import config
from protean.runtime.predictions import NO_SUBJECT
from protean.sleep.evidence import admissible_set, load_archived_run
from protean.state.enums import CallType, NodeName, Tier, TraceSource
from protean.state.records import (
    BasalGangliaOutcome,
    BasalGangliaPrediction,
    OperatorAnswerOutcome,
    DirectorOutcome,
    DirectorPrediction,
    DispatchOutcome,
    DispatchPrediction,
    HippocampusOutcome,
    HippocampusPrediction,
    ThalamusOutcome,
    ThalamusPrediction,
)
from tests.sleep import (
    codeless_exit_code,
    gradeable_file_exists,
    outcome,
    prediction,
    summary,
    unit,
    write_run,
)


def _set(tmp_path: Path, brain, **kwargs):
    directory = write_run(tmp_path / "run", brain=brain, **kwargs)
    return admissible_set(load_archived_run(directory))


# --------------------------------------------------------------------------------------
# Admissible — the non-vacuous control, without which every exclusion below proves nothing
# --------------------------------------------------------------------------------------


def test_a_joined_on_list_gradeable_non_vacuous_pair_is_admitted(tmp_path, brain) -> None:
    predicted = prediction(
        node=NodeName.THALAMUS, payload=ThalamusPrediction(admitted_ids=["admitted:e-1"])
    )
    pairs = _set(
        tmp_path,
        brain,
        records=[
            predicted,
            outcome(
                predicted,
                ThalamusOutcome(cited_admitted_ids=["admitted:e-1"], matched=True),
            ),
        ],
    )
    assert [pair.admissible for pair in pairs.pairs] == [True]
    assert pairs.by_reason() == {reason: 0 for reason in config.SLEEP_EXCLUSION_REASONS}


# --------------------------------------------------------------------------------------
# Test 1 — joined
# --------------------------------------------------------------------------------------


def test_a_prediction_no_outcome_claims_is_unjoined(tmp_path, brain) -> None:
    pairs = _set(
        tmp_path,
        brain,
        records=[
            prediction(
                node=NodeName.HIPPOCAMPUS, payload=HippocampusPrediction(episode_ids=["e-1"])
            )
        ],
    )
    assert pairs.by_reason()[config.EXCLUSION_UNJOINED] == 1
    assert pairs.admissible == ()


def test_an_outcome_whose_ref_names_no_committed_prediction_is_unjoined(
    tmp_path, brain
) -> None:
    """Test 1 asks that **both** records be committed, so an orphan outcome is counted too."""
    predicted = prediction(
        node=NodeName.HIPPOCAMPUS, payload=HippocampusPrediction(episode_ids=["e-1"])
    )
    graded = outcome(
        predicted, HippocampusOutcome(cited_episode_ids=["e-1"], matched=True)
    )
    pairs = _set(tmp_path, brain, records=[graded])  # the prediction is never committed
    assert pairs.by_reason()[config.EXCLUSION_UNJOINED] == 1


# --------------------------------------------------------------------------------------
# Test 2 — on the list
# --------------------------------------------------------------------------------------


def test_a_operator_answer_outcome_is_off_list(tmp_path, brain) -> None:
    """`OperatorAnswerOutcome` declines to put a verdict on the node that asked, so it is not
    evidence for a learner — even though the prediction beneath it is on the list."""
    predicted = prediction(
        node=NodeName.CORTEX,
        tier=Tier.DIRECTOR,
        payload=DirectorPrediction(
            goal_id="g1", progress_window_ticks=2, synthetic_stuck=True
        ),
    )
    pairs = _set(
        tmp_path,
        brain,
        records=[
            predicted,
            outcome(
                predicted,
                OperatorAnswerOutcome(question="what now?", answer="carry on"),
                source=TraceSource.OPERATOR_ANSWER,
            ),
        ],
    )
    assert pairs.by_reason()[config.EXCLUSION_OFF_LIST] == 1
    assert [pair.signal for pair in pairs.pairs] == ["operator_answer"]


def test_a_director_progress_pair_the_runtime_graded_is_on_the_list(tmp_path, brain) -> None:
    """The control for the case above: the same signal, graded by the runtime, is admitted."""
    predicted = prediction(
        node=NodeName.CORTEX,
        tier=Tier.DIRECTOR,
        payload=DirectorPrediction(goal_id="g1", progress_window_ticks=2),
    )
    pairs = _set(
        tmp_path,
        brain,
        records=[
            predicted,
            outcome(predicted, DirectorOutcome(progress_observed=True, matched=True)),
        ],
    )
    assert pairs.admissible and pairs.by_reason()[config.EXCLUSION_OFF_LIST] == 0


# --------------------------------------------------------------------------------------
# Test 3 — gradeable (D16-4), read off order W1's own predicates
# --------------------------------------------------------------------------------------


def test_a_verdict_resting_partly_on_an_absent_predicate_is_ungradeable(
    tmp_path, brain
) -> None:
    """Run 1's shape exactly: two codeless `exit_code` predicates beside one that graded."""
    subject = unit(
        "u-branch",
        codeless_exit_code("e-branch-1"),
        gradeable_file_exists("e-branch-2", "a planning record (not in this mirror)"),
    )
    predicted = prediction(
        node=NodeName.CORTEX,
        tier=CallType.DISPATCH,
        tick=2,
        payload=DispatchPrediction(
            unit_id="u-branch", expectation_ids=["e-branch-1", "e-branch-2"]
        ),
    )
    pairs = _set(
        tmp_path,
        brain,
        tick=2,
        records=[
            predicted,
            outcome(
                predicted,
                DispatchOutcome(
                    verdict_match=False, failed_predicate_ids=["e-branch-1"], matched=False
                ),
            ),
        ],
        units=[subject],
        summaries={2: summary("u-branch", tick=2, observed=["a planning record (not in this mirror)"])},
    )
    assert pairs.by_reason()[config.EXCLUSION_UNGRADEABLE] == 1
    assert pairs.admissible == ()


def test_a_verdict_on_predicates_that_all_graded_is_admitted(tmp_path, brain) -> None:
    """The control: the same shape with a `code` argument present grades from evidence."""
    subject = unit("u-clean", gradeable_file_exists("e-1", "a planning record (not in this mirror)"))
    predicted = prediction(
        node=NodeName.CORTEX,
        tier=CallType.DISPATCH,
        tick=2,
        payload=DispatchPrediction(unit_id="u-clean", expectation_ids=["e-1"]),
    )
    pairs = _set(
        tmp_path,
        brain,
        tick=2,
        records=[
            predicted,
            outcome(
                predicted,
                DispatchOutcome(verdict_match=True, failed_predicate_ids=[], matched=True),
            ),
        ],
        units=[subject],
        summaries={2: summary("u-clean", tick=2, observed=["a planning record (not in this mirror)"])},
    )
    assert pairs.admissible and pairs.by_reason()[config.EXCLUSION_UNGRADEABLE] == 0


# --------------------------------------------------------------------------------------
# Test 4 — non-vacuous (folded: A1-13), including the two cases row L1 names by hand
# --------------------------------------------------------------------------------------


def test_a_unit_whose_only_predicate_is_withheld_is_vacuous(tmp_path, brain) -> None:
    """D3-2: it grades `match: true` on no evidence, which is A1-13's class."""
    subject = unit("u-only", codeless_exit_code("e-only"))
    predicted = prediction(
        node=NodeName.CORTEX,
        tier=CallType.DISPATCH,
        tick=2,
        payload=DispatchPrediction(unit_id="u-only", expectation_ids=["e-only"]),
    )
    pairs = _set(
        tmp_path,
        brain,
        tick=2,
        records=[
            predicted,
            outcome(
                predicted,
                DispatchOutcome(verdict_match=True, failed_predicate_ids=[], matched=True),
            ),
        ],
        units=[subject],
        summaries={2: summary("u-only", tick=2)},
    )
    assert pairs.by_reason()[config.EXCLUSION_VACUOUS] == 1


def test_an_empty_episode_id_set_is_vacuous(tmp_path, brain) -> None:
    """Row L1 names this case: `matched` is then independent of what the node retrieved."""
    predicted = prediction(
        node=NodeName.HIPPOCAMPUS, payload=HippocampusPrediction(episode_ids=[])
    )
    pairs = _set(
        tmp_path,
        brain,
        records=[
            predicted,
            outcome(predicted, HippocampusOutcome(cited_episode_ids=[], matched=True)),
        ],
    )
    assert pairs.by_reason()[config.EXCLUSION_VACUOUS] == 1


def test_an_empty_admitted_id_set_is_vacuous(tmp_path, brain) -> None:
    predicted = prediction(
        node=NodeName.THALAMUS, payload=ThalamusPrediction(admitted_ids=[])
    )
    pairs = _set(
        tmp_path,
        brain,
        records=[
            predicted,
            outcome(predicted, ThalamusOutcome(cited_admitted_ids=[], matched=True)),
        ],
    )
    assert pairs.by_reason()[config.EXCLUSION_VACUOUS] == 1


def test_a_no_subject_gate_prediction_is_vacuous(tmp_path, brain) -> None:
    """The second case row L1 names: the gate predicted about no unit at all."""
    predicted = prediction(
        node=NodeName.BASAL_GANGLIA, payload=BasalGangliaPrediction(unit_id=NO_SUBJECT)
    )
    pairs = _set(
        tmp_path,
        brain,
        records=[
            predicted,
            outcome(
                predicted,
                BasalGangliaOutcome(abandoned=False, trap_flagged=False, matched=True),
            ),
        ],
    )
    assert pairs.by_reason()[config.EXCLUSION_VACUOUS] == 1


def test_a_gate_prediction_naming_a_real_unit_is_admitted(tmp_path, brain) -> None:
    predicted = prediction(
        node=NodeName.BASAL_GANGLIA, payload=BasalGangliaPrediction(unit_id="u-real")
    )
    pairs = _set(
        tmp_path,
        brain,
        records=[
            predicted,
            outcome(
                predicted,
                BasalGangliaOutcome(abandoned=False, trap_flagged=False, matched=True),
            ),
        ],
    )
    assert pairs.admissible and pairs.by_reason()[config.EXCLUSION_VACUOUS] == 0


# --------------------------------------------------------------------------------------
# The archive — the one run nobody authored
# --------------------------------------------------------------------------------------


RUN_ONE_ARCHIVE = "workload-run-20260907T153455290946"


def _archive(repo_root: Path) -> Path:
    """Run 1's archive **by name** — the newest `workload-run-*` is a post-A.1 run since 2026-09-26."""
    found = repo_root / "brain" / "archive" / RUN_ONE_ARCHIVE
    if not found.is_dir():
        pytest.skip("this checkout carries no archive of run 1")
    return found


def test_run_ones_archive_is_refused_by_name_rather_than_migrated(repo_root: Path) -> None:
    """Re-based by build A.1: run 1's archive is a **pre-A.1 artifact** and is refused.

    § Scaffold clause item 2 moves six schema versions together, 1 → 2, and § Out of scope
    forbids migrating any checkpoint or artifact: "Old artifacts are **refused, never
    migrated**". Run 1 is retired as a baseline (decision 20), so the refusal costs nothing on
    disk — and it is the **expected** result of the bump rather than a defect to repair.

    Build 3's claim about this archive — that every graded `dispatch_expectations` pair in it is
    `ungradeable`, which is why the three-tick repeat cannot compile — is unchanged as a fact
    about that run; it is simply no longer readable by A.1's loaders. It re-opens against a
    post-A.1 run, which build 3's own wet sequence owes.
    """
    from protean.state.errors import SchemaVersionMismatch

    directory = _archive(repo_root)
    with pytest.raises(SchemaVersionMismatch) as raised:
        admissible_set(load_archived_run(directory))
    message = str(raised.value)
    print(f"    [A.1] archive refusal: {message}")
    assert "schema_version 1 on disk" in message and "in the running code" in message
