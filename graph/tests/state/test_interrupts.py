"""The mailbox's state half: two licensed raisers, a derived id, and no default.

`the build specification (not in this mirror)` § Deliverable 5 and § Deliverable 2's `InterruptRequest` →
`Interrupt` row. This is binding contract 4's model side; the file format's writer and the
resolve-and-delete path belong to a later order.

Three properties carry the weight:

* **`kind` is closed and each kind has one licensed raiser.** `question` is a node's ordinary
  output; `stuck` is the runtime's, and the runtime is licensed for nothing else.
* **The id derives from `(task, tick, raiser)`**, so a raise replayed after a crash reproduces
  the same filename — one open file, not two, without a check anywhere in the writer.
* **There is no `default` field, anywhere.** An unanswered item is refused, never defaulted:
  silence is never assent, and a `default` slot is what "silence is assent" would look like in
  a contract.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from protean import config
from protean.state import (
    ANSWER_HEADING,
    Interrupt,
    InterruptKind,
    InterruptRequest,
    OpenInterrupt,
    Raiser,
    ResolvedInterrupt,
    interrupt_id,
)
from protean.state.interrupts import components_of

MAILBOX_MODELS = (InterruptRequest, Interrupt, OpenInterrupt, ResolvedInterrupt)


#: `InterruptKind` is closed at exactly `("question", "stuck")` — asserted by exact value list
#: at `test_enums.py::test_the_set_is_exactly_these_members[InterruptKind]`, with every other
#: closed set, so the closure is proved in one place. What this module adds is the licensing:
#: which raiser may raise which of the two.


@pytest.mark.parametrize("bad", ["blocked", "note", "warning", "info"])
def test_a_third_kind_is_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        InterruptRequest(kind=bad, raised_by=Raiser.MANAGER, question="?")


def test_stuck_may_only_be_raised_by_the_runtime() -> None:
    InterruptRequest(kind=InterruptKind.STUCK, raised_by=Raiser.RUNTIME, question="?")
    with pytest.raises(ValidationError) as raised:
        InterruptRequest(kind=InterruptKind.STUCK, raised_by=Raiser.MANAGER, question="?")
    assert "may only be raised by runtime" in str(raised.value)


def test_the_runtime_is_licensed_for_stuck_and_no_other_kind() -> None:
    with pytest.raises(ValidationError) as raised:
        InterruptRequest(kind=InterruptKind.QUESTION, raised_by=Raiser.RUNTIME, question="?")
    assert "and no other kind" in str(raised.value)


@pytest.mark.parametrize("model", MAILBOX_MODELS, ids=lambda m: m.__name__)
def test_no_mailbox_model_has_a_default_slot(model: type) -> None:
    """folded: U-15 — an unanswered item is refused, never defaulted."""
    assert "default" not in model.model_fields


def test_the_id_derives_from_task_tick_and_raiser() -> None:
    first = interrupt_id("task-a", 7, "manager")
    replayed = interrupt_id("task-a", 7, "manager")
    assert first == replayed == "task-a-t7-manager"
    assert interrupt_id("task-a", 8, "manager") != first
    assert interrupt_id("task-a", 7, "runtime") != first


def test_the_id_widens_for_a_call_bearing_raiser_and_for_nothing_else() -> None:
    """Contract 4's first amendment (`the build specification (not in this mirror)` § Scaffold clause
    item 2, folded: S-A52, folded: S-A72, folded: S-A90).

    `(task, tick, node, raiser, call#[, member#])` for a think, escalate, delegate or dispatch
    member; the three-part id for a node or the runtime raising on its own account, which has no
    `call#` to put there. Every component is therefore defined for every raiser, and the id is
    replay-stable by construction — the same call on the same pass reproduces the same filename.
    """
    member = interrupt_id(
        "task-a", 7, "dispatch", node="cortex", call_number=2, member_number=1
    )
    assert member == "task-a-t7-cortex-dispatch-c2-m1"
    assert member == interrupt_id(
        "task-a", 7, "dispatch", node="cortex", call_number=2, member_number=1
    ), "replay-stable"
    assert member != interrupt_id(
        "task-a", 7, "dispatch", node="cortex", call_number=2, member_number=2
    ), "two members of one wave cannot collapse onto one filename"

    think = interrupt_id("task-a", 7, "think", node="thalamus", call_number=1)
    assert think == "task-a-t7-thalamus-think-c1"
    assert think != interrupt_id("task-a", 7, "think", node="hippocampus", call_number=1), (
        "a call type is a raiser every outer node shares, so the node is IN the id"
    )
    assert interrupt_id("task-a", 7, "thalamus") == "task-a-t7-thalamus", "three-part, still"


def test_a_half_widened_id_is_refused_rather_than_written() -> None:
    """A node with no call number names a call that does not exist."""
    with pytest.raises(ValueError):
        interrupt_id("task-a", 7, "think", node="thalamus")
    with pytest.raises(ValueError):
        interrupt_id("task-a", 7, "think", call_number=1)


def test_the_components_read_back_out_of_the_id() -> None:
    """The answer path's own read: `resolution_target()` recovers the calling node from here."""
    assert components_of("task-a-t7-cortex-dispatch-c2-m1") == ("cortex", "dispatch", 2, 1)
    assert components_of("task-a-t7-thalamus-think-c1") == ("thalamus", "think", 1, None)
    assert components_of("task-a-t7-thalamus") == (None, "thalamus", None, None)
    # Read from the right, because the task id is the one component that may hold a `-`.
    assert components_of("task-2026-09-12-t4-runtime") == (None, "runtime", None, None)
    assert components_of(
        interrupt_id("task-2026-09-12", 4, "escalate", node="anterior_cingulate", call_number=3)
    ) == ("anterior_cingulate", "escalate", 3, None), "and a node name holds no `-` to confuse it"


def test_an_absent_or_empty_answer_body_is_unanswered() -> None:
    def item(answer: str | None) -> Interrupt:
        return Interrupt(
            schema_version=config.MAILBOX_SCHEMA_VERSION,
            id=interrupt_id("t", 1, "planner"),
            task="t",
            tick=1,
            raised_at="tick 1",
            kind=InterruptKind.QUESTION,
            raised_by=Raiser.MANAGER,
            question="which shape?",
            answer=answer,
        )

    assert item(None).is_answered() is False
    assert item("").is_answered() is False
    assert item("   \n  ").is_answered() is False
    assert item("the second one").is_answered() is True


def test_the_answer_heading_is_the_literal_the_spec_names() -> None:
    assert ANSWER_HEADING == "## Answer"


def test_an_open_interrupt_carries_everything_a_rematerialized_file_needs() -> None:
    """folded: U-11 — a vanished file is rebuilt from state, then refused for its answer."""
    for field in ("id", "kind", "raised_by", "raised_at_tick", "raised_at", "path", "question", "evidence"):
        assert field in OpenInterrupt.model_fields


def test_a_stuck_open_item_carries_its_trap_evidence() -> None:
    item = OpenInterrupt(
        id=interrupt_id("t", 12, "runtime"),
        kind=InterruptKind.STUCK,
        raised_by=Raiser.RUNTIME,
        raised_at_tick=12,
        raised_at="tick 12",
        path="mailbox/open/t-t12-runtime.md",
        question="the ladder is exhausted on g-1; how should this go?",
        evidence={"detector": "dislodging", "unit": "u-1", "ticks": 4},
    )
    assert item.evidence["detector"] == "dislodging"


def test_a_resolved_interrupt_keeps_both_ticks_and_the_answer() -> None:
    resolved = ResolvedInterrupt(
        id=interrupt_id("t", 3, "thalamus"),
        kind=InterruptKind.QUESTION,
        raised_by=Raiser.THALAMUS,
        raised_at_tick=3,
        resolved_at_tick=5,
        question="admit the older episode?",
        answer="yes",
    )
    assert (resolved.raised_at_tick, resolved.resolved_at_tick) == (3, 5)
