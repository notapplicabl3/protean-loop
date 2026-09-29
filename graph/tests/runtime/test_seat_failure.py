"""Row W9: a forced seat failure stops the task cleanly and the tick still completes.

`the build specification (not in this mirror)` § Deliverable 1 → *Failure is not an envelope*
(§ Directional decisions 11, folded: A1-9, folded: S-32, folded: S-33). Order W2's DoD row
**W9**, clause by clause:

* three forced failures, one scenario each — a **non-zero exit**, an **`is_error`** response and
  a **rate limit** — each raising `SeatUnavailable` rather than constructing a `SeatEnvelope`;
* **no journal envelope** for that tick, so a resume re-invokes rather than restoring;
* `cost.errors` incremented, `stopped` committed with the refusal named;
* **exactly one** open mailbox item, carrying the CLI's message **verbatim**;
* and the following `resume` making a fresh invocation.

**Every assertion is on disk or on an exit code**, and the seat is the shipping live adapter
driven against `tests/cortex/fake_cli` — a stand-in binary answering with order W1's own
captured error envelopes. No model is called and no money is spent.

**Contract 5 is not opened by a failure** (S-33): the six-entry journal is asserted here, beside
the refusal, because "every node every tick" is the thing a failure path is most likely to break.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean import config
from protean.brain.folders import seed_hashes
from protean.brain.jsonl import read_lines
from protean.cortex.layer import build_live_layer
from protean.cortex.live.invoke import MESSAGE_LIMIT, REASON_SPAWN
from protean.mailbox.files import build as build_mailbox
from protean.runtime import engine
from protean.runtime.commit import build_checkpoint, write_checkpoint
from protean.runtime.errors import SeatUnavailable
from protean.runtime.paths import BrainPaths
from protean.state.enums import Escalation, NodeName, TerminalState, Tier
from protean.mailbox.format import parse
from protean.state.interrupts import ANSWER_HEADING
from protean.state.seats import SeatEnvelope
from protean.runtime.seat import SeatSelection, build_request
from protean.state.workspace import Workspace
from protean.state.primitives import GoalItem
from tests.conftest import tagged_show
from tests.cortex import fake_cli
from tests.runtime import stubs
from tests.mailbox.answering import answer

GOAL = "settle the failing seat"

#: The three shapes, one scenario each (row W9). Two are order W1's captured wire bytes; the
#: rate limit is shaped on them. `exit_code` is what the CLI exited with beside the body.
SCENARIOS = {
    "non_zero_exit": ("live_refusal.json", 1),
    "is_error": ("live_rate_limit.json", 0),
    "rate_limit_fixture": ("live_rate_limit.json", 1),
}


show = tagged_show("W9")


@pytest.fixture()
def failing(tmp_path: Path, monkeypatch, load_envelope):
    """A brain root whose live seat answers with one of row W9's three failures."""

    def _build(scenario: str, *, then: list | None = None):
        name, exit_code = SCENARIOS[scenario]
        responses = [load_envelope(name), *(then or [])]
        codes = [exit_code, *([0] * len(then or []))]
        binaries = fake_cli.install(tmp_path / "bin", responses, exit_codes=codes)
        fake_cli.on_path(monkeypatch, binaries)
        root = fake_cli.seed_live_root(tmp_path / "brain")
        return root, binaries

    return _build


@pytest.fixture(scope="module")
def ran(tmp_path_factory, load_envelope) -> dict[str, tuple]:
    """One failing `protean run` tick per scenario, run once and read by every consumer.

    Row W9's five disk claims — the journal, the checkpoint, the exit code, the mailbox item and
    the terminal event — are five readings of **one** tick, not five ticks. Each scenario's tick
    is driven here, under a module-scoped `pytest.MonkeyPatch()` context that puts that
    scenario's stand-in binary on `PATH` for the length of the run, and every consumer below is
    read-only afterwards: nothing in this dictionary is written to again. A consumer that needs
    to *drive* the root (a resume, a second invocation) takes the function-scoped `failing`
    fixture instead.
    """
    with pytest.MonkeyPatch().context() as patch:
        runs: dict[str, tuple] = {}
        for scenario in sorted(SCENARIOS):
            name, exit_code = SCENARIOS[scenario]
            base = tmp_path_factory.mktemp(f"w9_{scenario}")
            binaries = fake_cli.install(base / "bin", [load_envelope(name)], exit_codes=[exit_code])
            fake_cli.on_path(patch, binaries)
            root = fake_cli.seed_live_root(base / "brain")
            outcome, _ = _run_one_tick(root)
            runs[scenario] = (root, outcome, binaries)
    return runs


def _run_one_tick(root: Path):
    """One `protean run` tick against the failing seat, through the shipping drivers."""
    layer = build_live_layer(root=root)
    outcome = engine.start(
        root, GOAL, layer, mailbox=build_mailbox(root), max_ticks=1
    )
    return outcome, layer


def _task_paths(root: Path):
    paths = BrainPaths(root=root)
    return paths.task(paths.task_ids()[-1])


def _age_the_task(root: Path, ticks: int = 10) -> None:
    """Re-seal the checkpoint as a task that had already run `ticks` ticks when the seat failed.

    One error on tick one is an error **rate** of 1.0, so homeostasis's `max_error_rate` ceiling
    stops the very next tick — correct behaviour, and not what row W9 is about. A real failure
    arrives with a task's worth of ticks behind it, and this is that task: only `cost.ticks`
    moves, and the envelope is re-sealed through the same `build_checkpoint()` the boundary
    commit uses, so every arm of the resume's refusal ladder stays armed.
    """
    from protean.state.checkpoint import load_checkpoint

    paths = _task_paths(root)
    checkpoint = load_checkpoint(stubs.committed_state(paths), seed_reader=None)
    state = checkpoint.state
    state.cost.ticks = ticks
    write_checkpoint(
        paths,
        build_checkpoint(
            state, seed_hashes=seed_hashes(root), revision=checkpoint.revision
        ),
    )


# --------------------------------------------------------------------------------------
# The raise itself
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_the_forced_failure_raises_seat_unavailable_and_builds_no_envelope(
    failing, scenario: str
) -> None:
    """Decision 11: an error cannot satisfy the four facts, so it is refused by name."""
    root, _ = failing(scenario)
    layer = build_live_layer(root=root)
    selection = SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    workspace = Workspace(
        task_id="task-direct",
        tick=1,
        goals=[GoalItem(id="g1", text=GOAL, opened_at_tick=0, last_progress_tick=0)],
    )
    layer.sessions.open_task("task-direct")

    with pytest.raises(SeatUnavailable) as raised:
        layer.port(Tier.MANAGER, build_request(selection, workspace=workspace))

    show(f"{scenario} refusal", str(raised.value))
    assert raised.value.tier == str(Tier.MANAGER)
    assert not isinstance(raised.value, SeatEnvelope)
    assert layer.calls()[0].outcome == "unavailable"


# --------------------------------------------------------------------------------------
# The tick still completes, and what it leaves behind
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_the_tick_completes_with_every_node_and_no_journal_envelope(
    ran, scenario: str
) -> None:
    """S-33: contract 5 is never opened by a failure — one output entry per node, the seat's carrying none."""
    root, outcome, _ = ran[scenario]

    journal = _task_paths(root).journal(1)
    entries = read_lines(journal)
    outputs = [entry["node"] for entry in entries if entry["call_number"] == 0]
    show(f"{scenario} journal nodes", [(e["node"], e["call_number"]) for e in entries])

    assert outputs == list(config.NODE_ORDER), "every node every tick, in order"
    # A.1 § Deliverable 6: the node's own output entry keeps its place at the reserved
    # `call# = 0`, and the refused seat **call** is journalled beside it at `call# = 1` —
    # "journalled and counted" (§ Deliverable 2) — carrying the request it was refused on and
    # no envelope, which is what re-invokes it in place on a replay.
    refused = next(
        item for item in entries
        if item["node"] == str(NodeName.CORTEX) and item["call_number"] == 1
    )
    seat_entry = next(
        item for item in entries
        if item["node"] == str(NodeName.CORTEX) and item["call_number"] == 0
    )
    assert refused["envelope"] is None, "no journal envelope, so a resume re-invokes"
    assert seat_entry["output"] is None
    assert outcome.ticks[0].seat_refusal


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_the_checkpoint_counts_the_error_and_commits_stopped(ran, scenario: str) -> None:
    root, outcome, _ = ran[scenario]

    committed = stubs.committed_state(_task_paths(root))
    show(f"{scenario} cost", committed["state"]["cost"])
    show(f"{scenario} terminal", committed["state"]["terminal"])

    assert committed["state"]["cost"]["errors"] == 1
    assert committed["state"]["terminal"] == str(TerminalState.STOPPED)
    assert outcome.terminal is TerminalState.STOPPED


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_the_process_exit_code_is_the_one_config_names_for_stopped(
    ran, scenario: str
) -> None:
    _, outcome, _ = ran[scenario]
    show(f"{scenario} exit code", f"{outcome.exit_code} (EXIT_STOPPED={config.EXIT_STOPPED})")
    assert outcome.exit_code == config.EXIT_STOPPED


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_exactly_one_open_item_carries_the_clis_message_verbatim(
    ran, load_envelope, scenario: str
) -> None:
    """"raises the mailbox interrupt carrying the CLI's own message verbatim"."""
    name, _ = SCENARIOS[scenario]
    root, _, _ = ran[scenario]

    open_dir = BrainPaths(root=root).mailbox_open
    files = sorted(path.name for path in open_dir.glob("*.md"))
    show(f"{scenario} mailbox/open/", files)
    assert len(files) == 1, "one refusal, one item"

    body = (open_dir / files[0]).read_text(encoding="utf-8")
    payload = load_envelope(name)
    message = "; ".join(payload["errors"]) if payload.get("errors") else payload["result"].strip()
    # The adapter bounds what reaches an interrupt at `MESSAGE_LIMIT`; W1's captured refusal is
    # the one fixture that is longer (406 characters), so the expectation carries the same bound.
    message = message[:MESSAGE_LIMIT]
    item = parse(body)
    show(f"{scenario} message", item.evidence["message"][:120])
    assert item.evidence["message"] == message, "the CLI's own words, unedited"
    assert item.evidence["tier"] == str(Tier.MANAGER), "and which seat said them"
    assert ANSWER_HEADING in body, "and it is the operator's to answer"


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_the_committed_terminal_event_names_the_refusal(ran, scenario: str) -> None:
    """"commits `stopped` naming the refusal" — in the record, not only in the mailbox file."""
    root, _, _ = ran[scenario]

    episodes = read_lines(_task_paths(root).episodes)
    terminal = next(item for item in episodes if item.get("event_name") == "terminal")
    show(f"{scenario} terminal event", terminal["detail"])
    assert terminal["detail"]["terminal"] == str(TerminalState.STOPPED)
    assert "refusal" in terminal["detail"]
    assert str(Tier.MANAGER) in terminal["detail"]["refusal"]


# --------------------------------------------------------------------------------------
# The resume re-invokes rather than restoring
# --------------------------------------------------------------------------------------


def test_the_following_resume_re_invokes_the_seat(failing, tmp_path: Path) -> None:
    """No journal envelope was written, so there is nothing to restore — the seat is called."""
    good = fake_cli.envelope(fake_cli.planner_result("u1", "g1"))
    root, binaries = failing("non_zero_exit", then=[good])
    _run_one_tick(root)

    assert fake_cli.invocations(binaries) == 1, "the failing tick made exactly one call"
    _age_the_task(root)
    open_dir = BrainPaths(root=root).mailbox_open
    answer(next(open_dir.glob("*.md")), "retry it")

    # A **new** layer, as a second process would build: nothing carries over but the checkpoint.
    resumed = build_live_layer(root=root)
    outcome = engine.resume(root, resumed, mailbox=build_mailbox(root), max_ticks=1)

    show("invocations after the resume", fake_cli.invocations(binaries))
    show("resume tick restored?", outcome.ticks[0].seat_restored)
    assert fake_cli.invocations(binaries) == 2, "a fresh invocation, not a restore"
    assert outcome.ticks[0].seat_restored is False
    assert outcome.ticks[0].seat_refusal is None


def test_the_resumed_call_reuses_the_checkpointed_session_without_minting(
    failing, tmp_path: Path
) -> None:
    """Row W2's session clause, proven where it matters: across a process boundary."""
    good = fake_cli.envelope(fake_cli.planner_result("u1", "g1"))
    root, binaries = failing("non_zero_exit", then=[good])
    _run_one_tick(root)

    committed = stubs.committed_state(_task_paths(root))
    carried = committed["state"]["seat_sessions"]
    show("checkpointed seat_sessions", sorted(carried))
    assert sorted(carried) == sorted(str(tier) for tier in Tier)

    _age_the_task(root)
    open_dir = BrainPaths(root=root).mailbox_open
    answer(next(open_dir.glob("*.md")), "retry it")
    engine.resume(root, build_live_layer(root=root), mailbox=build_mailbox(root), max_ticks=1)

    argv = fake_cli.argv_of(binaries, 2)
    show("resumed argv session flag", argv[argv.index("--resume") - 1 : argv.index("--resume") + 2])
    assert "--session-id" not in argv, "a resume joins; it does not mint"
    assert argv[argv.index("--resume") + 1] == carried[str(Tier.MANAGER)]


def test_an_early_failure_trips_the_error_rate_ceiling_on_the_next_tick(failing) -> None:
    """The other half of the same behaviour, asserted rather than left as a surprise.

    `cost.errors` is a **rate** against `cost.ticks`, and the seeded ceiling is `0.5`, so one
    refusal inside a task's first two ticks stops the next one before the seat is reached. That
    is homeostasis working, not the failure path breaking — but it means a workload run that
    refuses early needs a re-seed rather than a plain `resume`, and order W8 should know it.
    """
    good = fake_cli.envelope(fake_cli.planner_result("u1", "g1"))
    root, binaries = failing("non_zero_exit", then=[good])
    _run_one_tick(root)
    open_dir = BrainPaths(root=root).mailbox_open
    answer(next(open_dir.glob("*.md")), "retry it")

    outcome = engine.resume(
        root, build_live_layer(root=root), mailbox=build_mailbox(root), max_ticks=1
    )
    show("resumed terminal", outcome.terminal)
    show("invocations after the resume", fake_cli.invocations(binaries))
    assert outcome.terminal is TerminalState.STOPPED
    assert outcome.ticks[0].seat_skipped, "homeostasis skipped the call, the tick still ran"
    assert fake_cli.invocations(binaries) == 1, "no second call: the ceiling came first"


# --------------------------------------------------------------------------------------
# A fourth shape: no process at all
# --------------------------------------------------------------------------------------


def test_a_binary_that_cannot_be_spawned_stops_the_task_like_any_other_refusal(
    failing,
) -> None:
    """`OSError` at the spawn takes decision 11's path, so the tick still completes.

    The three scenarios above are answers on the wire; this one is no process at all. The
    binary still resolves — `shutil.which` is satisfied by the execute bit — and the kernel
    refuses it at `execv`, which is the shape a deleted, replaced or unmounted binary takes.
    Before it was classified, that `OSError` left the tick loop raw and no tick completed.
    """
    root, binaries = failing("non_zero_exit")
    fake_cli.unspawnable(binaries, "missing")
    outcome, _ = _run_one_tick(root)

    entries = read_lines(_task_paths(root).journal(1))
    show("spawn refusal", outcome.ticks[0].seat_refusal)
    assert fake_cli.invocations(binaries) == 0, "no process ever ran"
    assert [e["node"] for e in entries if e["call_number"] == 0] == list(config.NODE_ORDER)
    assert outcome.ticks[0].seat_refusal, "the tick recorded a refusal rather than raising"

    committed = stubs.committed_state(_task_paths(root))
    assert committed["state"]["cost"]["errors"] == 1
    assert committed["state"]["terminal"] == str(TerminalState.STOPPED)
    assert outcome.exit_code == config.EXIT_STOPPED

    episodes = read_lines(_task_paths(root).episodes)
    terminal = next(item for item in episodes if item.get("event_name") == "terminal")
    show("spawn terminal event", terminal["detail"]["refusal"])
    assert REASON_SPAWN in terminal["detail"]["refusal"], "refused by the new name"

    open_dir = BrainPaths(root=root).mailbox_open
    files = sorted(path.name for path in open_dir.glob("*.md"))
    assert len(files) == 1, "one refusal, one item"
    item = parse((open_dir / files[0]).read_text(encoding="utf-8"))
    show("spawn mailbox message", item.evidence["message"])
    assert "No such file or directory" in item.evidence["message"], "the OS error text"
    assert len(item.evidence["message"]) <= MESSAGE_LIMIT
