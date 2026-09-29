"""The three live handles: minted once per task, resumed after, adopted on a resume.

`the build specification (not in this mirror)` § Deliverable 1 → *Sessions*, and build 1's *fresh per task,
cached within task* (S8-1). Order W2's DoD row **W2**, its session clause: "the seat handles
are checkpointed in `BrainState.seat_sessions` and reused across a resume in a new process
without minting".

The argv half of that clause — that a resumed run's recorded argv carries no `--session-id` —
is in `test_live_invoke.py`, where an argv is recorded. This module is the book itself.
"""

from __future__ import annotations

import pytest

from protean import config

from protean.cortex.live.session import (
    SESSION_MINT_FLAG,
    SESSION_RESUME_FLAG,
    LiveSessionBook,
)
from protean.runtime.seat import SeatSessions
from protean.state.enums import CallType, Tier


@pytest.fixture()
def book() -> LiveSessionBook:
    return LiveSessionBook()


def test_the_book_satisfies_the_runtimes_session_seam(book) -> None:
    """`SeatSessions` is what the boundary commit reads and what a resume hands back."""
    assert isinstance(book, SeatSessions)


def test_every_seat_handle_is_minted_together_on_the_first_sight_of_a_task(book) -> None:
    handles = book.open_task("task-1")
    assert sorted(handles) == sorted(str(tier) for tier in Tier)
    assert len(set(handles.values())) == len(config.TIERS), "opaque and distinct, never derived from the task id"
    assert book.minted_tasks == ["task-1"]


def test_the_same_task_gets_the_same_three(book) -> None:
    first = book.open_task("task-1")
    assert book.open_task("task-1") == first
    assert book.minted_tasks == ["task-1"], "cached within task"


def test_a_new_task_discards_all_three_and_mints_three_more(book) -> None:
    first = book.open_task("task-1")
    second = book.open_task("task-2")
    assert set(first.values()).isdisjoint(second.values()), "fresh per task"
    assert book.minted_tasks == ["task-1", "task-2"]


def test_for_task_answers_only_for_the_open_task(book) -> None:
    book.open_task("task-1")
    assert book.for_task("task-1")
    assert book.for_task("task-2") == {}


# --------------------------------------------------------------------------------------
# Which flag the next call carries
# --------------------------------------------------------------------------------------


def test_the_first_call_of_a_task_mints_and_every_later_one_resumes(book) -> None:
    book.open_task("task-1")
    flag, handle = book.session_flag(Tier.DIRECTOR)
    assert flag == SESSION_MINT_FLAG
    book.mark_opened(Tier.DIRECTOR)
    assert book.session_flag(Tier.DIRECTOR) == (SESSION_RESUME_FLAG, handle)


def test_opening_one_tier_does_not_open_another(book) -> None:
    """Three sessions, three lifetimes: the planner's first call still mints."""
    book.open_task("task-1")
    book.mark_opened(Tier.DIRECTOR)
    assert book.session_flag(Tier.MANAGER)[0] == SESSION_MINT_FLAG


def test_reading_the_flag_does_not_open_the_session(book) -> None:
    """A call that never left the adapter must not strand the handle mid-mint."""
    book.open_task("task-1")
    book.session_flag(Tier.MANAGER)
    assert book.session_flag(Tier.MANAGER)[0] == SESSION_MINT_FLAG


# --------------------------------------------------------------------------------------
# The resume
# --------------------------------------------------------------------------------------


def test_a_restore_adopts_the_checkpoints_handles_and_mints_nothing(book) -> None:
    carried = {"director": "d-1", "manager": "m-1"}
    book.restore("task-1", carried)
    assert book.for_task("task-1") == carried
    assert book.minted_tasks == [], "a restore is not a mint"


def test_a_restored_session_is_resumed_rather_than_re_minted(book) -> None:
    """Row W2: "reused across a resume in a new process **without minting**"."""
    book.restore("task-1", {"director": "d-1", "manager": "m-1"})
    for tier in Tier:
        flag, handle = book.session_flag(tier)
        assert flag == SESSION_RESUME_FLAG
        assert handle.endswith("-1")


def test_an_empty_restore_is_a_no_op(book) -> None:
    """A checkpoint with no handles — the first tick of a task — leaves the book alone."""
    book.open_task("task-1")
    before = book.for_task("task-1")
    book.restore("task-1", {})
    assert book.for_task("task-1") == before


def test_a_restore_leaves_all_three_opened_but_unconfirmed(book) -> None:
    """The fix: a checkpointed handle carries `--resume` and no promise that it exists.

    All three are minted at task open and one tier runs per tick, so a crash before a tier's
    first invocation checkpoints a handle the CLI was never asked to create.
    """
    carried = {"director": "d-1", "manager": "m-1"}
    book.restore("task-1", carried)
    for tier in Tier:
        assert book.session_flag(tier)[0] == SESSION_RESUME_FLAG, "still a resume"
        assert book.is_unconfirmed(tier) is True, "and still unconfirmed"


def test_an_invocation_confirms_the_handle_it_ran_against_and_no_other(book) -> None:
    """`mark_opened()` is what the adapter calls once a process has actually run."""
    book.restore("task-1", {"director": "d-1", "manager": "m-1"})
    book.mark_opened(Tier.DIRECTOR)
    assert book.is_unconfirmed(Tier.DIRECTOR) is False
    assert book.is_unconfirmed(Tier.MANAGER) is True
    assert book.session_flag(Tier.DIRECTOR) == (SESSION_RESUME_FLAG, "d-1"), "still the same"


def test_a_minted_task_has_nothing_unconfirmed(book) -> None:
    """A handle this process minted needs no fallback: its first call carries `--session-id`."""
    book.open_task("task-1")
    assert [book.is_unconfirmed(tier) for tier in Tier] == [False] * len(config.TIERS)


def test_a_new_task_and_a_close_both_clear_the_unconfirmed_set(book) -> None:
    book.restore("task-1", {"director": "d-1", "manager": "m-1"})
    book.open_task("task-2")
    assert book.unconfirmed == set(), "a mint confirms nothing and carries nothing over"
    book.restore("task-3", {"director": "d-3", "manager": "m-3"})
    book.close_task()
    assert book.unconfirmed == set()


def test_a_handle_read_before_a_task_opened_is_a_wiring_bug(book) -> None:
    with pytest.raises(RuntimeError) as raised:
        book.handle(Tier.DIRECTOR)
    assert "router opens the task" in str(raised.value)


def test_close_task_discards_all_three(book) -> None:
    book.open_task("task-1")
    book.close_task()
    assert book.for_task("task-1") == {}
