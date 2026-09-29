"""`TraceRecord`'s two kinds, `EpisodeRecord`'s dedupe key, and the journal's seat slot.

`the build specification (not in this mirror)` § Deliverable 2's contract table and § Deliverable 4's
prediction→outcome loop. `TraceRecord` is binding contract 3.

The half of § Deliverable 4's enforcement that lives in the model is here: a `prediction`-kind
record with no prediction, and an `outcome`-kind record with no `ref`, cannot be *constructed*.
The other half — an `outcome` whose `ref` names no **committed** prediction raises and writes
nothing — needs the file and belongs to the brain-folder layer a later order builds.

The `source` component of the dedupe key is asserted on its own case, because it is the
component doing work: it is what lets an interrupt resolution (`operator_answer`) and an ordinary
grading (`runtime_grade`) land at the same resume tick without colliding.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from protean import config
from protean.state import (
    OperatorAnswerOutcome,
    CallType,
    DirectorPrediction,
    EpisodeKind,
    EpisodeRecord,
    EventName,
    HomeostasisOutcome,
    HomeostasisPrediction,
    HomeostasisReport,
    JournalEntry,
    NodeName,
    ManagerPlan,
    SeatEnvelope,
    Tier,
    TraceKind,
    TraceRecord,
    TraceSource,
)

#: A.1's own contracts are imported from their own modules rather than through
#: `protean.state`'s roster, exactly as S2 and P1–P5 are (folded: D3-7).
from protean.state.calls import FiringDecision, SubagentSpawn
from protean.state.records import (
    FIRING_KEY_SUFFIX,
    OUTPUT_CALL_NUMBER,
    FiringOutcome,
    FiringPrediction,
)

PREDICTION = HomeostasisPrediction(next_tick_tokens=100, next_tick_wall_seconds=2.0)


def prediction_record(**overrides) -> TraceRecord:
    payload = dict(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task="t-1",
        tick=3,
        node=NodeName.HOMEOSTASIS,
        kind=TraceKind.PREDICTION,
        source=TraceSource.NODE,
        prediction=PREDICTION,
    )
    payload.update(overrides)
    return TraceRecord(**payload)


def test_a_prediction_with_no_prediction_cannot_be_constructed() -> None:
    """"A node that records no prediction cannot learn" — enforced by the type, not by habit."""
    with pytest.raises(ValidationError) as raised:
        prediction_record(prediction=None)
    assert "cannot learn" in str(raised.value)


def test_an_outcome_with_no_ref_names_no_prediction_to_grade() -> None:
    with pytest.raises(ValidationError) as raised:
        TraceRecord(
            schema_version=config.TRACE_SCHEMA_VERSION,
            task="t-1",
            tick=4,
            node=NodeName.HOMEOSTASIS,
            kind=TraceKind.OUTCOME,
            source=TraceSource.RUNTIME_GRADE,
            outcome=HomeostasisOutcome(
                observed_tokens=90, observed_wall_seconds=1.8, matched=True
            ),
        )
    assert "names no prediction to grade" in str(raised.value)


def test_a_prediction_carries_no_outcome_and_an_outcome_carries_no_prediction() -> None:
    with pytest.raises(ValidationError):
        prediction_record(
            outcome=HomeostasisOutcome(
                observed_tokens=1, observed_wall_seconds=1.0, matched=True
            )
        )
    with pytest.raises(ValidationError):
        TraceRecord(
            schema_version=config.TRACE_SCHEMA_VERSION,
            task="t-1",
            tick=4,
            node=NodeName.HOMEOSTASIS,
            kind=TraceKind.OUTCOME,
            source=TraceSource.RUNTIME_GRADE,
            prediction=PREDICTION,
            outcome=HomeostasisOutcome(
                observed_tokens=1, observed_wall_seconds=1.0, matched=True
            ),
            ref="anything",
        )


@pytest.mark.parametrize(
    "source",
    [TraceSource.RUNTIME_GRADE, TraceSource.OPERATOR_ANSWER, TraceSource.FIRING_GRADE],
)
def test_a_prediction_may_not_take_an_outcome_source(source: TraceSource) -> None:
    with pytest.raises(ValidationError):
        prediction_record(source=source)


@pytest.mark.parametrize(
    "source", [TraceSource.NODE, TraceSource.RUNTIME, TraceSource.FIRING]
)
def test_an_outcome_may_not_take_a_prediction_source(source: TraceSource) -> None:
    with pytest.raises(ValidationError):
        TraceRecord(
            schema_version=config.TRACE_SCHEMA_VERSION,
            task="t-1",
            tick=4,
            node=NodeName.HOMEOSTASIS,
            kind=TraceKind.OUTCOME,
            source=source,
            outcome=HomeostasisOutcome(
                observed_tokens=1, observed_wall_seconds=1.0, matched=True
            ),
            ref="r",
        )


def test_tier_is_the_cortex_folders_key_and_only_the_cortex_folders() -> None:
    with pytest.raises(ValidationError):
        prediction_record(tier=Tier.MANAGER)
    with pytest.raises(ValidationError):
        prediction_record(node=NodeName.CORTEX, tier=None)
    record = prediction_record(
        node=NodeName.CORTEX,
        tier=Tier.DIRECTOR,
        prediction=DirectorPrediction(goal_id="g-1", progress_window_ticks=8),
    )
    assert record.tier is Tier.DIRECTOR


def test_the_dedupe_key_is_the_six_the_spec_names() -> None:
    record = prediction_record()
    assert record.dedupe_key() == ("t-1", 3, "homeostasis", None, "prediction", "node")


def test_source_is_what_keeps_a_operator_answer_from_colliding_with_a_grading() -> None:
    """Both land on the cortex folder at the same resume tick; the key must still differ."""
    graded = TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task="t-1",
        tick=9,
        node=NodeName.CORTEX,
        tier=Tier.DIRECTOR,
        kind=TraceKind.OUTCOME,
        source=TraceSource.RUNTIME_GRADE,
        outcome=HomeostasisOutcome(observed_tokens=1, observed_wall_seconds=1.0, matched=True),
        ref="t-1:5:cortex:director:prediction",
    )
    answered = graded.model_copy(
        update={
            "source": TraceSource.OPERATOR_ANSWER,
            "outcome": OperatorAnswerOutcome(question="which shape?", answer="the second"),
        }
    )
    assert graded.dedupe_key() != answered.dedupe_key()
    assert graded.dedupe_key()[:5] == answered.dedupe_key()[:5]


def test_the_synthetic_stuck_prediction_is_the_one_runtime_sourced_prediction() -> None:
    """folded: T-7 — minted on the cortex folder, director tier, so a operator_answer has a ref."""
    record = prediction_record(
        node=NodeName.CORTEX,
        tier=Tier.DIRECTOR,
        source=TraceSource.RUNTIME,
        prediction=DirectorPrediction(
            goal_id="g-1", progress_window_ticks=8, synthetic_stuck=True
        ),
    )
    assert record.prediction.synthetic_stuck is True
    assert record.prediction_key() == "t-1:3:cortex:director:prediction"


def test_an_outcome_ref_matches_the_prediction_key_it_names() -> None:
    prediction = prediction_record()
    outcome = TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task="t-1",
        tick=4,
        node=NodeName.HOMEOSTASIS,
        kind=TraceKind.OUTCOME,
        source=TraceSource.RUNTIME_GRADE,
        outcome=HomeostasisOutcome(observed_tokens=90, observed_wall_seconds=1.8, matched=True),
        ref=prediction.prediction_key(),
        scored_at_tick=4,
    )
    assert outcome.ref == prediction.prediction_key()


# --------------------------------------------------------------------------------------
# Build A.1 — contract 3's amendments (a), (d) and (e): the `firing_check` pair, the widened
# per-kind source validator, and the `:firing` suffix (row G15)
# --------------------------------------------------------------------------------------

FIRING_PREDICTION = FiringPrediction(
    check="ceiling_pressure", key="firing_threshold", value=0.25, threshold=0.5, fired=False
)


def test_the_firing_pair_are_members_of_the_two_payload_unions() -> None:
    """Amendment (a): one prediction member and one outcome member, resolved on `signal`."""
    prediction = prediction_record(source=TraceSource.FIRING, prediction=FIRING_PREDICTION)
    assert isinstance(prediction.prediction, FiringPrediction)
    assert prediction.prediction.signal == "firing_check"

    graded = TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task="t-1",
        tick=4,
        node=NodeName.HOMEOSTASIS,
        kind=TraceKind.OUTCOME,
        source=TraceSource.FIRING_GRADE,
        outcome=FiringOutcome(work_arrived=False, matched=True),
        ref=prediction.prediction_key(),
        scored_at_tick=4,
    )
    assert isinstance(graded.outcome, FiringOutcome)
    assert graded.outcome.signal == "firing_check"


def test_the_widened_validator_admits_firing_on_a_prediction_and_firing_grade_on_an_outcome() -> None:
    """Amendment (d), both arms — and nothing else in the validator moves."""
    assert prediction_record(source=TraceSource.FIRING, prediction=FIRING_PREDICTION).source is (
        TraceSource.FIRING
    )
    with pytest.raises(ValidationError) as raised:
        prediction_record(source=TraceSource.FIRING_GRADE, prediction=FIRING_PREDICTION)
    assert "node|runtime|firing" in str(raised.value)


def test_the_firing_suffix_reaches_a_firing_prediction_and_nothing_else() -> None:
    """Amendment (e): the suffix is keyed on `source == firing`, and on nothing else."""
    firing = prediction_record(source=TraceSource.FIRING, prediction=FIRING_PREDICTION)
    assert firing.prediction_key() == "t-1:3:homeostasis:-:prediction" + FIRING_KEY_SUFFIX

    for source in (TraceSource.NODE, TraceSource.RUNTIME):
        other = prediction_record(
            node=NodeName.CORTEX,
            tier=Tier.DIRECTOR,
            source=source,
            prediction=DirectorPrediction(goal_id="g-1", progress_window_ticks=8),
        )
        assert other.prediction_key() == "t-1:3:cortex:director:prediction"
        assert not other.prediction_key().endswith(FIRING_KEY_SUFFIX)


def test_the_two_trace_lines_of_one_tick_differ_by_dedupe_key_and_by_prediction_key() -> None:
    """Homeostasis's live case: its own prediction and its firing prediction, one tick."""
    own = prediction_record()
    firing = prediction_record(source=TraceSource.FIRING, prediction=FIRING_PREDICTION)
    assert own.tick == firing.tick and own.node is firing.node
    assert own.dedupe_key() != firing.dedupe_key()
    assert own.dedupe_key()[:5] == firing.dedupe_key()[:5]
    assert own.prediction_key() != firing.prediction_key()


def test_an_event_episode_is_named_and_a_tick_episode_is_not() -> None:
    with pytest.raises(ValidationError):
        EpisodeRecord(
            schema_version=config.EPISODE_SCHEMA_VERSION,
            episode_id="t-1:3",
            task="t-1",
            tick=3,
            kind=EpisodeKind.EVENT,
        )
    with pytest.raises(ValidationError):
        EpisodeRecord(
            schema_version=config.EPISODE_SCHEMA_VERSION,
            episode_id="t-1:3",
            task="t-1",
            tick=3,
            kind=EpisodeKind.TICK,
            event_name=EventName.TASK_START,
        )


def test_the_episode_dedupe_key_separates_a_tick_from_its_events() -> None:
    tick = EpisodeRecord(
        schema_version=config.EPISODE_SCHEMA_VERSION,
        episode_id="t-1:3",
        task="t-1",
        tick=3,
        kind=EpisodeKind.TICK,
    )
    event = EpisodeRecord(
        schema_version=config.EPISODE_SCHEMA_VERSION,
        episode_id="t-1:3",
        task="t-1",
        tick=3,
        kind=EpisodeKind.EVENT,
        event_name=EventName.LOCK_RECLAIMED,
    )
    assert tick.dedupe_key() == ("t-1", 3, "tick", None)
    assert event.dedupe_key() == ("t-1", 3, "event", "lock_reclaimed")


def test_every_nodes_entry_may_carry_an_envelope_now(load_envelope) -> None:
    """The A.1 re-base of folded: S-4 (`the build specification (not in this mirror)` § Deliverable 6).

    Build 1's `_the_envelope_rides_the_seat_entry` enforced two halves of the one-call-per-tick
    shape together — `tier` set exactly when the node is the cortex, and only the cortex entry
    carrying a `SeatEnvelope` — and is removed whole, because every node's entry may now carry
    both. The journal is still the envelope store; what moved is how many of them a tick holds.
    """
    envelope = SeatEnvelope.model_validate(load_envelope("planner_success.json"))
    entry = JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task="t-1",
        tick=2,
        node=NodeName.CORTEX,
        call_number=1,
        tier=Tier.MANAGER,
        envelope=envelope,
    )
    assert entry.dedupe_key() == ("t-1", 2, "cortex", 1, None)
    think = JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task="t-1",
        tick=2,
        node=NodeName.HOMEOSTASIS,
        call_number=1,
        tier=CallType.THINK,
        payload={"question": "is this tick's spend near the ceiling?"},
        payload_model="ThinkPayload",
        envelope=envelope,
    )
    assert think.dedupe_key() == ("t-1", 2, "homeostasis", 1, None)
    assert think.tier is CallType.THINK, "the column is the addressee, and a think has no tier"


def test_the_nodes_own_output_entry_takes_the_reserved_call_zero() -> None:
    """§ Deliverable 6 (folded: A1-9, folded: S-A76) — and model calls number from 1.

    Without the reservation a skipped node's decision entry and its first call entry would
    contend for `call# = 1`, which is order W6's failure exactly.
    """
    output = JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task="t-1",
        tick=2,
        node=NodeName.HOMEOSTASIS,
        output=HomeostasisReport(tick=2, tokens=1, wall_seconds=1.0, error_rate=0.0, ticks=2),
    )
    assert output.call_number == OUTPUT_CALL_NUMBER == 0
    assert output.dedupe_key() == ("t-1", 2, "homeostasis", 0, None)
    assert output.is_call() is False, "the output entry is not a call and gets no receipt"
    assert output.is_restorable() is False
    with pytest.raises(ValidationError):
        JournalEntry(
            schema_version=config.JOURNAL_SCHEMA_VERSION,
            task="t-1",
            tick=2,
            node=NodeName.HOMEOSTASIS,
            call_number=-1,
        )


def test_a_refused_calls_entry_is_journalled_and_is_not_restorable() -> None:
    """§ Deliverable 2 — "journalled and counted" — and § Deliverable 6's replay condition.

    The condition for restoring is a **restorable result being present**, never an entry
    existing: an entry recording a refusal carries no envelope, so that call is re-invoked in
    place while the journalled calls after it still restore.
    """
    refused = JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task="t-1",
        tick=2,
        node=NodeName.HIPPOCAMPUS,
        call_number=2,
        tier=CallType.DELEGATE,
        payload={"kind": "reviewer", "question": "?"},
        payload_model="DelegatePayload",
        kind="reviewer",
    )
    assert refused.is_call() is True
    assert refused.is_restorable() is False
    assert refused.kind == "reviewer", "the one licensed duplicate of Deliverable 4's split"
    assert refused.block_ref == "", "A.1 fixes the field; A.1.i fills it"


def test_the_member_sub_key_is_carried_and_is_none_outside_a_wave() -> None:
    """§ Deliverable 6 — a wave takes one `call#` and its members `member#` beneath it.

    **The wave itself is order W8's**; what W4 lands is the key's shape, so the buffered
    `member#`-ordered writes have somewhere to sit.
    """
    member = JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task="t-1",
        tick=2,
        node=NodeName.CORTEX,
        call_number=1,
        member_number=3,
        tier=CallType.DISPATCH,
    )
    assert member.dedupe_key() == ("t-1", 2, "cortex", 1, 3)
    assert SubagentSpawn(
        task="t-1", tick=2, node=NodeName.CORTEX, call_number=1, member_number=3
    ).key() == member.dedupe_key(), "one key, both artifacts (§ Deliverable 4)"


def test_a_firing_decision_is_a_member_of_the_output_union() -> None:
    """§ Scaffold clause item 2's one member addition (folded: S-A93).

    A skipped node's `call# = 0` entry carries its `FiringDecision` as that entry's `output`
    and is unconstructible until the union names it. **The check that produces one is order
    W6's**; the union member is W4's.
    """
    decision = FiringDecision(
        tick=2,
        node=NodeName.HIPPOCAMPUS,
        check="retrieval_pressure",
        key="firing_check",
        value=0.2,
        threshold=0.5,
        fired=False,
    )
    entry = JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task="t-1",
        tick=2,
        node=NodeName.HIPPOCAMPUS,
        output=decision,
    )
    restored = JournalEntry.model_validate(entry.model_dump(mode="json"))
    assert isinstance(restored.output, FiringDecision)
    assert restored == entry
    assert restored.output.emitter == "firing", "the discriminator it joins the union on"


def test_the_journal_output_union_resolves_two_same_shaped_results_apart() -> None:
    """Without the `emitter` discriminator a `{"tick": n}` line is ambiguous on reload."""
    entry = JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task="t-1",
        tick=2,
        node=NodeName.CORTEX,
        tier=Tier.MANAGER,
        output=ManagerPlan(tick=2),
    )
    restored = JournalEntry.model_validate(entry.model_dump(mode="json"))
    assert isinstance(restored.output, ManagerPlan)
    assert restored == entry
