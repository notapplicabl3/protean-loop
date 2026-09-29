"""The five port calls, against the directory on disk.

`the build specification (not in this mirror)` § Deliverable 5 (a mailbox holding **only open items**, read
at a tick boundary and never polled) and § Deliverable 3's resume order, which is where
`orphan` and the re-materializing `write` are called from.

The port is `protean.runtime.interrupts.MailboxPort` — the runtime declares it, this package
implements it — so the first assertion below is that the implementation *is* one, structurally,
rather than that it happens to have the right method names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean.mailbox.files import ITEM_SUFFIX, FileMailbox, build
from protean.mailbox.format import MailboxFormatError
from protean.runtime.interrupts import MailboxPort, lift, reconcile
from protean.state.brain_state import BrainState
from protean.state.enums import InterruptKind, Raiser
from protean.state.interrupts import Interrupt, InterruptRequest

from tests.mailbox.answering import answer
from tests.mailbox.conftest import item


def _item(identifier: str = "task-x-t1-planner", **overrides) -> Interrupt:
    """The shared factory, keyed by the id this module names its files after."""
    return item(id=identifier, **overrides)


@pytest.fixture()
def mailbox(tmp_path: Path) -> FileMailbox:
    """The port over a **bare** root, overriding the battery's seeded one.

    `FileMailbox` reads and writes `mailbox/` and nothing else — it never opens `nodes/` — so
    the twelve cases below paid a full copy of the tracked seed tree for a directory the layer
    creates itself. The two cases that genuinely assert about the seeded root take `brain`.
    """
    return build(tmp_path / "bare-root")


@pytest.fixture()
def open_dir(mailbox: FileMailbox) -> Path:
    """`mailbox/open/` — the bare root's, so it follows the mailbox above."""
    return mailbox.open_dir


def test_the_file_layer_is_the_port_the_runtime_declared(brain):
    assert isinstance(build(brain), MailboxPort)


def test_build_returns_a_mailbox_rooted_at_the_brain_root(brain):
    port = build(brain)
    assert isinstance(port, FileMailbox)
    assert port.open_dir == brain / "mailbox" / "open"
    assert port.orphaned_dir == brain / "mailbox" / "orphaned"


def test_write_lands_one_file_named_by_the_interrupt_id(mailbox, open_dir):
    path = mailbox.write(_item())
    assert path == open_dir / f"task-x-t1-planner{ITEM_SUFFIX}"
    assert path.exists()
    assert [entry.name for entry in open_dir.iterdir()] == [path.name]


def test_write_creates_the_open_directory_when_a_fresh_checkout_has_none(brain, tmp_path):
    """Every generated brain directory is untracked, so the writer makes its own."""
    fresh = tmp_path / "empty-root"
    port = build(fresh)
    assert not port.open_dir.exists()
    port.write(_item())
    assert port.open_dir.is_dir()


def test_read_returns_the_item_and_none_when_the_file_has_vanished(mailbox):
    mailbox.write(_item())
    assert mailbox.read("task-x-t1-planner") == _item()
    mailbox.path_for("task-x-t1-planner").unlink()
    assert mailbox.read("task-x-t1-planner") is None


def test_read_names_the_file_in_a_format_refusal(mailbox):
    path = mailbox.write(_item())
    path.write_text("not a mailbox item\n", encoding="utf-8")
    with pytest.raises(MailboxFormatError, match=path.name):
        mailbox.read("task-x-t1-planner")


def test_open_ids_lists_every_file_and_ignores_anything_that_is_not_one(mailbox, open_dir):
    mailbox.write(_item("task-x-t1-planner"))
    mailbox.write(_item("task-x-t1-executor", raised_by=Raiser.DISPATCH))
    (open_dir / "README.txt").write_text("not an item", encoding="utf-8")
    assert mailbox.open_ids() == ["task-x-t1-executor", "task-x-t1-planner"]


def test_open_ids_on_a_root_with_no_mailbox_yet_is_empty(tmp_path):
    assert build(tmp_path / "nothing-here").open_ids() == []


def test_an_answer_written_under_the_heading_is_what_read_returns(mailbox):
    path = mailbox.write(_item())
    answer(path, "the primary ledger")
    item = mailbox.read("task-x-t1-planner")
    assert item.is_answered() is True and item.answer == "the primary ledger"


def test_delete_removes_the_file_and_is_safe_on_one_already_gone(mailbox, open_dir):
    mailbox.write(_item())
    mailbox.delete("task-x-t1-planner")
    assert mailbox.open_ids() == []
    mailbox.delete("task-x-t1-planner")


def test_orphan_moves_the_file_aside_and_it_is_never_open_again(mailbox):
    mailbox.write(_item())
    target = mailbox.orphan("task-x-t1-planner")
    assert target.parent == mailbox.orphaned_dir
    assert target.exists()
    assert mailbox.open_ids() == []


def test_a_second_write_of_the_same_id_replaces_its_own_file(mailbox, open_dir):
    """The id derives from `(task, tick, raiser)`, so a re-raise is the same file, never a second."""
    mailbox.write(_item())
    mailbox.write(_item(question="which ledger, restated"))
    assert len(list(open_dir.iterdir())) == 1
    assert mailbox.read("task-x-t1-planner").question == "which ledger, restated"


# --------------------------------------------------------------------------------------
# The two resume-time calls, driven through the runtime's own reconciler
# --------------------------------------------------------------------------------------


def _state_with(entry) -> BrainState:
    state = BrainState(task_id="task-x", tick=1)
    state.open_interrupts = [entry]
    return state


def _request(**overrides) -> InterruptRequest:
    payload = {
        "kind": InterruptKind.QUESTION,
        "raised_by": Raiser.MANAGER,
        "question": "which ledger?",
    }
    payload.update(overrides)
    return InterruptRequest(**payload)


def test_a_file_with_no_committed_entry_is_orphaned_by_the_reconciler(mailbox):
    mailbox.write(_item())
    orphaned, rematerialized = reconcile(BrainState(task_id="task-x", tick=1), mailbox)
    assert orphaned == ["task-x-t1-planner"] and rematerialized == []
    assert mailbox.open_ids() == []
    assert (mailbox.orphaned_dir / f"task-x-t1-planner{ITEM_SUFFIX}").exists()


def test_a_vanished_file_is_re_materialized_from_committed_state(mailbox):
    """`OpenInterrupt` carries the question, the evidence and `raised_at` for exactly this."""
    interrupt, entry = lift(
        _request(evidence={"candidates": ["a", "b"]}),
        task="task-x",
        tick=1,
        path=str(mailbox.path_for("task-x-t1-planner")),
    )
    mailbox.write(interrupt)
    mailbox.path_for(entry.id).unlink()

    orphaned, rematerialized = reconcile(_state_with(entry), mailbox)
    assert orphaned == [] and rematerialized == [entry.id]

    restored = mailbox.read(entry.id)
    assert restored.question == interrupt.question
    assert restored.evidence == {"candidates": ["a", "b"]}
    assert restored.raised_at == interrupt.raised_at
    assert restored.is_answered() is False, "a re-materialized item is unanswered, not defaulted"
