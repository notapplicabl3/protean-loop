"""M12, end to end and on disk: raise → commit → file → `interrupted` → answer → resolved.

`the build specification (not in this mirror)` § Deliverable 5 (raising, the refusal, the resolution inside
the commit) and § Deliverable 3's commit order, in which the mailbox file is the **last append
before the checkpoint** and the resolved file is deleted only after its records have landed.

**Every assertion here is about the filesystem or a process exit code**, because that is what
M12's row claims: a directory listing after the raise and after the two-request tick, the exit
code `protean.config` names for `interrupted`, the `operator_answer` line in the raising folder's
`trace.jsonl` with its `ref`, the `interrupt_resolved` episode line, the file's absence
afterwards, and one open file — never two — after a replayed raise.

The listings and lines are printed as well as asserted, so a `-s` capture of this module is the
receipt itself rather than a summary of one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean import config, cli
from protean.brain.jsonl import read_lines
from protean.cortex.layer import SEAT_SCRIPT_ENV
from protean.mailbox.files import build as build_mailbox
from protean.runtime import cycle as cycle_module
from protean.runtime.cycle import WAVE_CALL_NUMBER, run_tick
from protean.runtime.engine import resume
from protean.runtime.paths import BrainPaths
from protean.state.enums import InterruptKind, NodeName, Raiser, TerminalState
from protean.state.interrupts import InterruptRequest, components_of

from tests.conftest import tagged_show
from tests.mailbox.answering import answer, leave_unanswered
from tests.mailbox.conftest import QUESTION_SCRIPT, committed_prediction_keys, listing


show = tagged_show("M12")


@pytest.fixture()
def operator(brain: Path, monkeypatch):
    """`protean <verb>` against the throwaway root, through the real operator surface.

    `run` resolves its seat layer and its mailbox by dotted path, so this drives the same
    `resolve_seat_layer()` / `resolve_mailbox()` seams a shell would.
    """
    monkeypatch.setenv(config.BRAIN_ROOT_ENV, str(brain))
    monkeypatch.setenv(SEAT_SCRIPT_ENV, QUESTION_SCRIPT)

    def _run(*argv: str) -> int:
        return cli.main(list(argv))

    return _run


def _task_paths(brain: Path):
    paths = BrainPaths(root=brain)
    return paths.task(paths.task_ids()[-1])


def _lines(path: Path) -> list[dict]:
    return read_lines(path)


# --------------------------------------------------------------------------------------
# Raise → commit → write file → exit `interrupted`
# --------------------------------------------------------------------------------------


def test_a_raise_commits_writes_one_file_and_exits_with_the_interrupted_code(
    brain: Path, open_dir: Path, operator
):
    code = operator("run", "settle the ledger question")
    show("mailbox/open/ after the raise", listing(open_dir))
    show("exit code", f"{code} (config.EXIT_INTERRUPTED={config.EXIT_INTERRUPTED})")

    assert code == config.EXIT_INTERRUPTED
    assert len(listing(open_dir)) == 1

    paths = _task_paths(brain)
    committed = json.loads(paths.checkpoint.read_text(encoding="utf-8"))
    assert committed["state"]["terminal"] == str(TerminalState.INTERRUPTED)
    assert [item["id"] for item in committed["state"]["open_interrupts"]] == [
        listing(open_dir)[0].removesuffix(".md")
    ]


def test_the_mailbox_file_is_the_commits_last_append_before_the_checkpoint(started, mailbox):
    """§ Deliverable 3's commit order, read off the receipt rather than asserted about it."""
    context, state = started
    for _ in range(2):
        state.tick += 1
        result = run_tick(context, state)
    kinds = result.receipt.kinds()
    show("commit write order", kinds)
    assert result.receipt.order_is_contractual()
    assert result.receipt.checkpoint_is_last()
    assert kinds[-2] == "mailbox.write", "the file is the last append before the checkpoint"


# --------------------------------------------------------------------------------------
# Two requests in one tick
# --------------------------------------------------------------------------------------


def _also_raise_from_the_thalamus(monkeypatch):
    """A second licensed raiser on the same tick: a node's ordinary output carries a request."""
    original = cycle_module.NODES[str(NodeName.THALAMUS)]

    def _wrapped(payload):
        output = original(payload)
        if payload.tick < 2:
            return output
        return output.model_copy(
            update={
                "interrupt": InterruptRequest(
                    kind=InterruptKind.QUESTION,
                    raised_by=Raiser.THALAMUS,
                    question="nothing was admitted this tick; is the retrieval window right?",
                )
            }
        )

    monkeypatch.setattr(
        cycle_module,
        "NODES",
        {**cycle_module.NODES, str(NodeName.THALAMUS): _wrapped},
    )


def test_two_requests_in_one_tick_yield_two_files_and_a_two_item_open_interrupts(
    brain: Path, open_dir: Path, operator, monkeypatch
):
    _also_raise_from_the_thalamus(monkeypatch)
    code = operator("run", "settle the ledger question")

    files = listing(open_dir)
    committed = json.loads(_task_paths(brain).checkpoint.read_text(encoding="utf-8"))
    open_ids = [item["id"] for item in committed["state"]["open_interrupts"]]
    show("mailbox/open/ after the two-request tick", files)
    show("committed open_interrupts", open_ids)

    assert code == config.EXIT_INTERRUPTED
    assert len(files) == 2, "one file per raiser, and both raisers raised on the same tick"
    assert len(open_ids) == 2
    assert sorted(f"{item}.md" for item in open_ids) == files
    # **Re-based by build A.1**: the raiser is read out of the id by `components_of()`, the
    # same reader the answer path uses, because a **call-bearing** raiser's id is widened to
    # `(task, tick, node, raiser, call#[, member#])` while a node raising on its own account
    # keeps the three-part one (§ Scaffold clause item 2, contract 4).
    raisers = {components_of(item)[1] for item in open_ids}
    assert raisers == {str(Raiser.DISPATCH), str(Raiser.THALAMUS)}
    member = next(item for item in open_ids if components_of(item)[1] == str(Raiser.DISPATCH))
    node, _raiser, call_number, member_number = components_of(member)
    show("the member's id components", [node, call_number, member_number])
    assert node == str(NodeName.CORTEX), "the calling node is IN the id, not only in the body"
    assert call_number == WAVE_CALL_NUMBER and member_number == 1


# --------------------------------------------------------------------------------------
# A resume with an `## Answer`
# --------------------------------------------------------------------------------------


def test_an_answered_item_resolves_before_the_next_tick_and_leaves_its_records(
    brain: Path, open_dir: Path, operator
):
    assert operator("run", "settle the ledger question") == config.EXIT_INTERRUPTED
    raised = listing(open_dir)[0].removesuffix(".md")
    raise_tick = int(raised.split("-t")[-1].split("-")[0])  # the id's own tick component
    answer(open_dir / f"{raised}.md", "the primary ledger is the source of truth")

    code = operator("resume")
    show("exit code after resume", f"{code} (config.EXIT_DONE={config.EXIT_DONE})")
    show("mailbox/open/ after resolution", listing(open_dir))
    assert code == config.EXIT_DONE
    assert listing(open_dir) == [], "the file is deleted, inside the commit"

    paths = _task_paths(brain)
    resume_tick = json.loads(paths.checkpoint.read_text(encoding="utf-8"))["state"]["tick"]

    # The Q+A, appended to the raising folder's trace as an outcome keyed to the resume tick.
    trace = [
        record
        for record in _lines(paths.trace(str(NodeName.CORTEX)))
        if record.get("source") == "operator_answer"
    ]
    assert len(trace) == 1
    landed = trace[0]
    show("operator_answer trace line", json.dumps(landed, sort_keys=True))
    assert landed["kind"] == "outcome"
    assert landed["tick"] == resume_tick
    # The answer reaches the **node that asked** and lands on the prediction the wave minted:
    # `resolution_target()` reads the `node` component out of the id, and a dispatch member's
    # column is the addressee it was called on (contract 3 (c)).
    assert landed["ref"] == f"{paths.task_id}:{raise_tick}:cortex:dispatch:prediction"
    assert landed["outcome"]["answer"] == "the primary ledger is the source of truth"

    # The `ref` names a prediction that is actually committed in that folder.
    keys = committed_prediction_keys(_lines(paths.trace(str(NodeName.CORTEX))))
    assert landed["ref"] in keys

    # And the `event` episode record beside it.
    events = [
        record
        for record in _lines(paths.episodes)
        if record.get("event_name") == "interrupt_resolved"
    ]
    assert len(events) == 1
    show("interrupt_resolved episode line", json.dumps(events[0], sort_keys=True))
    assert events[0]["kind"] == "event"
    assert events[0]["tick"] == resume_tick
    assert events[0]["detail"]["id"] == raised

    # The answer is in committed state before the next tick ran, not only in the record.
    resolved = json.loads(paths.checkpoint.read_text(encoding="utf-8"))["state"][
        "resolved_interrupts"
    ]
    assert [item["id"] for item in resolved] == [raised]
    assert resolved[0]["resolved_at_tick"] == resume_tick


def test_a_resume_over_an_unanswered_item_refuses_and_changes_no_task_state(
    brain: Path, open_dir: Path, operator
):
    """The mailbox half of M13: silence is never assent, and the message names the file."""
    assert operator("run", "settle the ledger question") == config.EXIT_INTERRUPTED
    raised = listing(open_dir)[0]
    before = _task_paths(brain).checkpoint.read_bytes()

    assert operator("resume") == config.REFUSAL_EXIT_CODES["unanswered_interrupt"]
    assert _task_paths(brain).checkpoint.read_bytes() == before
    assert listing(open_dir) == [raised]

    leave_unanswered(open_dir / raised)
    assert operator("resume") == config.REFUSAL_EXIT_CODES["unanswered_interrupt"]
    assert _task_paths(brain).checkpoint.read_bytes() == before


def test_a_deleted_mailbox_file_is_re_materialized_and_then_refused(
    brain: Path, open_dir: Path, operator
):
    """A vanished file is not a terminal: it is rebuilt from state, then refused for its answer."""
    assert operator("run", "settle the ledger question") == config.EXIT_INTERRUPTED
    raised = listing(open_dir)[0]
    (open_dir / raised).unlink()
    assert listing(open_dir) == []

    assert operator("resume") == config.REFUSAL_EXIT_CODES["unanswered_interrupt"]
    show("mailbox/open/ after re-materialization", listing(open_dir))
    assert listing(open_dir) == [raised]


# --------------------------------------------------------------------------------------
# A raise re-run after a crash
# --------------------------------------------------------------------------------------


def _tear_the_commit(monkeypatch):
    """Kill the process inside the boundary commit, after the mailbox write and before the rename."""
    from protean.runtime import commit as commit_module

    def _die(paths, checkpoint):
        raise RuntimeError("killed inside the commit, after the mailbox write")

    monkeypatch.setattr(commit_module, "write_checkpoint", _die)


def test_a_raise_re_run_after_a_crash_yields_one_open_file_not_two(
    brain: Path, workspace: Path, open_dir: Path, layer, mailbox, started, monkeypatch
):
    context, state = started
    state.tick += 1
    run_tick(context, state)  # tick 1 completes and checkpoints

    _tear_the_commit(monkeypatch)
    state.tick += 1
    with pytest.raises(RuntimeError):
        run_tick(context, state)

    torn = listing(open_dir)
    show("mailbox/open/ after the torn commit", torn)
    assert len(torn) == 1, "the torn commit did land its mailbox write"
    assert json.loads(context.paths.checkpoint.read_text("utf-8"))["state"]["tick"] == 1

    monkeypatch.undo()
    outcome = resume(
        brain,
        layer,
        mailbox=build_mailbox(brain),
        workspace_path=str(workspace),
        max_ticks=1,
    )

    replayed = listing(open_dir)
    orphaned = listing(brain / "mailbox" / "orphaned")
    show("mailbox/open/ after the replayed raise", replayed)
    show("mailbox/orphaned/ after the replayed raise", orphaned)

    assert outcome.ticks[0].tick == 2, "the crashed tick was replayed, not advanced past"
    assert len(replayed) == 1, "one open file after the replay, never two"
    assert replayed == torn, "the same id, so the same filename"
    assert orphaned == torn, "the pre-crash file had no committed entry and was set aside"
