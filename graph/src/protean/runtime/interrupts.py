"""The interrupt seam: the runtime owns the state half, `src/protean/mailbox/` owns the files.

`the build specification (not in this mirror)` § Deliverable 5 (the closed `kind` set, the two licensed
raisers, the answer path, resolution inside the commit) and § Deliverable 3's resume order.

**A node requests; the runtime writes.** `InterruptRequest` is an optional slot on every node
output model and every seat result model; the runtime lifts it into an `Interrupt` (the file)
and an `OpenInterrupt` (committed state), and the mailbox file is the commit's **last append**
before the checkpoint. No node writes the mailbox, which is why the lift lives here.

**`MailboxPort` is the file half and this module does not implement it.** Reading a directory,
rendering YAML front matter over a markdown body, parsing the `## Answer` section and deleting a
resolved file all belong to `src/protean/mailbox/`; the runtime declares the calls it makes and
their order. A test drives it with a stub.

**Silence is never assent.** `unanswered()` returns the open items with no `## Answer` body — or
an empty one — and `resume` refuses on a non-empty result with its own exit code, naming the
file, before any task state changes.

**Resolution is a committed write like any other**: the answer lands in
`BrainState.resolved_interrupts` before the next tick runs, the Q+A is appended to the raising
folder's `trace.jsonl` as a `operator_answer` outcome keyed to the **resume** tick, an
`interrupt_resolved` `event` episode is appended — and only then is the file deleted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Protocol, runtime_checkable

from protean import config
from protean.runtime.errors import MailboxUnavailable
from protean.state.brain_state import BrainState
from protean.state.enums import (
    Addressee,
    CallType,
    NodeName,
    Raiser,
    Tier,
    TraceKind,
    TraceSource,
)
from protean.state.interrupts import (
    Interrupt,
    InterruptRequest,
    OpenInterrupt,
    ResolvedInterrupt,
    components_of,
    interrupt_id,
)
from protean.state.records import OperatorAnswerOutcome, TraceRecord

#: The dotted path the operator surface resolves the mailbox's file half from. W3 lands it.
MAILBOX_MODULE = "protean.mailbox.files"


#: Which node folder a raiser's resolution record lands on, and under which tier. A seat's raise
#: is the cortex folder's, keyed by the tier that raised it; the runtime's own `stuck` raise is
#: the cortex folder under the **director** tier, because the exhausted rung is the director's
#: (folded: T-7).
_SEAT_RAISERS = {
    Raiser.DIRECTOR: Tier.DIRECTOR,
    Raiser.MANAGER: Tier.MANAGER,
    Raiser.RUNTIME: Tier.DIRECTOR,
}


def now_iso() -> str:
    """The `raised_at` stamp. UTC and ISO-8601, so a file sorts by the time it was raised."""
    return datetime.now(timezone.utc).isoformat()


#: The four call types, as raisers. A call-bearing raiser resolves to the **calling node**,
#: which is read out of the id's own `node` component (§ Scaffold clause item 2, contract 4's
#: second amendment, folded: S-A74, folded: S-A90) — a call type is a raiser every outer node
#: shares, so there is nothing in the raiser itself to resolve.
_CALL_RAISERS = (Raiser.THINK, Raiser.ESCALATE, Raiser.DELEGATE, Raiser.DISPATCH)


def resolution_target(identifier: Raiser | str) -> tuple[NodeName, Addressee | None]:
    """The `(folder, tier)` an item's `operator_answer` outcome is appended to, read off **the id**.

    **It takes the id rather than the bare `Raiser`** (contract 4's second amendment): a think's
    or a dispatch member's question was asked by a *node*, and the id is the only thing the
    answer path is given, so the calling node is recovered from the id's own `node` component
    rather than from a table over raisers that cannot hold one. A three-part id — a node or the
    runtime raising on its own account — resolves exactly as it did before.
    """
    node_component, raiser_name, _call, _member = components_of(str(identifier))
    raiser = Raiser(raiser_name)
    if raiser in _CALL_RAISERS:
        if node_component is None:
            raise ValueError(
                f"{raiser} is a call-bearing raiser and its id carries the calling node; "
                f"{identifier!r} carries none, so the answer has no folder to land in"
            )
        # The call's answer belongs to the node that asked: a think is the calling node's own
        # question, and its `operator_answer` ref lands on that node's own prediction, which is
        # keyed with no tier — think, escalate and delegate mint no cortex prediction
        # (folded: S-A9). A **dispatch member** is the cortex's own call and its node component
        # says so; its column is the addressee `dispatch`, because that is the key the wave's
        # own prediction was minted under (contract 3 (c)) and an answer whose `ref` named no
        # committed key would be refused at the trace append.
        if raiser is Raiser.DISPATCH:
            return NodeName(node_component), CallType.DISPATCH
        return NodeName(node_component), None
    if raiser in _SEAT_RAISERS:
        return NodeName.CORTEX, _SEAT_RAISERS[raiser]
    return NodeName(str(raiser)), None


@runtime_checkable
class MailboxPort(Protocol):
    """The file half of the mailbox, implemented in `src/protean/mailbox/`."""

    def write(self, interrupt: Interrupt) -> Path:  # pragma: no cover - protocol
        """Render one open item to `mailbox/open/<id>.md` and return its path."""

    def read(self, interrupt_id: str) -> Interrupt | None:  # pragma: no cover - protocol
        """The item on disk, answer included, or `None` when its file has vanished."""

    def open_ids(self) -> list[str]:  # pragma: no cover - protocol
        """Every id with a file in `mailbox/open/`, whether or not state knows it."""

    def delete(self, interrupt_id: str) -> None:  # pragma: no cover - protocol
        """Remove a resolved item's file. Called inside the commit, after the records land."""

    def orphan(self, interrupt_id: str) -> Path:  # pragma: no cover - protocol
        """Move a file with no committed entry to `mailbox/orphaned/`, never counted as open."""


def lift(
    request: InterruptRequest,
    *,
    task: str,
    tick: int,
    path: str,
    raised_at: str | None = None,
    node: str | None = None,
    call_number: int | None = None,
    member_number: int | None = None,
) -> tuple[Interrupt, OpenInterrupt]:
    """A node's request → the file model and the committed state entry.

    The id derives from `(task, tick, raiser)`, so a raise re-run after a crash reproduces the
    same filename and yields one open file, not two. **A call-bearing raiser carries the node
    and the call components into it** (§ Scaffold clause item 2, contract 4): this is the
    function that mints the id, so it is where the widening lands, and `resolution_target()`
    beside it is what reads the node back out.
    """
    stamp = raised_at or now_iso()
    identifier = interrupt_id(
        task,
        tick,
        str(request.raised_by),
        node=node,
        call_number=call_number,
        member_number=member_number,
    )
    interrupt = Interrupt(
        schema_version=config.MAILBOX_SCHEMA_VERSION,
        id=identifier,
        kind=request.kind,
        raised_by=request.raised_by,
        task=task,
        tick=tick,
        raised_at=stamp,
        question=request.question,
        evidence=dict(request.evidence),
    )
    entry = OpenInterrupt(
        id=identifier,
        kind=request.kind,
        raised_by=request.raised_by,
        raised_at_tick=tick,
        raised_at=stamp,
        path=path,
        question=request.question,
        evidence=dict(request.evidence),
    )
    return interrupt, entry


def reconcile(state: BrainState, port: MailboxPort) -> tuple[list[str], list[str]]:
    """Read the mailbox against committed state. Returns `(orphaned, re-materialized)`.

    A file with no committed entry is an orphan of a torn commit and is moved aside; an open
    item whose file has vanished is re-materialized from `OpenInterrupt`, which carries
    everything the file needs (folded: U-11). Both happen at a boundary and never mid-tick.
    """
    committed = {item.id: item for item in state.open_interrupts}
    on_disk = set(port.open_ids())

    orphaned = sorted(on_disk - set(committed))
    for identifier in orphaned:
        port.orphan(identifier)

    rematerialized: list[str] = []
    for identifier, entry in sorted(committed.items()):
        if identifier in on_disk:
            continue
        port.write(
            Interrupt(
                schema_version=config.MAILBOX_SCHEMA_VERSION,
                id=entry.id,
                kind=entry.kind,
                raised_by=entry.raised_by,
                task=state.task_id,
                tick=entry.raised_at_tick,
                raised_at=entry.raised_at,
                question=entry.question,
                evidence=dict(entry.evidence),
            )
        )
        rematerialized.append(identifier)
    return orphaned, rematerialized


def unanswered(state: BrainState, port: MailboxPort) -> list[OpenInterrupt]:
    """Every open item with no `## Answer` body, or an empty one. Silence is never assent."""
    pending: list[OpenInterrupt] = []
    for entry in state.open_interrupts:
        item = port.read(entry.id)
        if item is None or not item.is_answered():
            pending.append(entry)
    return pending


def answers(state: BrainState, port: MailboxPort) -> dict[str, str]:
    """`{id: answer}` for every open item that has one."""
    found: dict[str, str] = {}
    for entry in state.open_interrupts:
        item = port.read(entry.id)
        if item is not None and item.is_answered():
            found[entry.id] = (item.answer or "").strip()
    return found


def resolve(state: BrainState, entry: OpenInterrupt, answer: str, resume_tick: int) -> None:
    """Move one item from open to resolved, in committed state, before the next tick runs."""
    state.open_interrupts = [item for item in state.open_interrupts if item.id != entry.id]
    state.resolved_interrupts = [
        *state.resolved_interrupts,
        ResolvedInterrupt(
            id=entry.id,
            kind=entry.kind,
            raised_by=entry.raised_by,
            raised_at_tick=entry.raised_at_tick,
            resolved_at_tick=resume_tick,
            question=entry.question,
            answer=answer,
        ),
    ]


def answer_outcome(
    entry: OpenInterrupt, answer: str, *, task: str, resume_tick: int
) -> TraceRecord:
    """The `operator_answer` outcome: keyed to the resume tick, `ref` to the raise-tick prediction.

    the operator's answers are the top reinforcement signal, not a verdict on the node that asked, so
    `matched` is left unset.
    """
    node, tier = resolution_target(entry.id)
    tier_key = str(tier) if tier is not None else "-"
    return TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task=task,
        tick=resume_tick,
        node=node,
        tier=tier,
        kind=TraceKind.OUTCOME,
        source=TraceSource.OPERATOR_ANSWER,
        outcome=OperatorAnswerOutcome(question=entry.question, answer=answer),
        ref=f"{task}:{entry.raised_at_tick}:{node}:{tier_key}:prediction",
        scored_at_tick=resume_tick,
    )


def requests_in(outputs: Iterable[object]) -> list[InterruptRequest]:
    """Every `interrupt` slot filled on this tick's outputs, in the order the nodes ran."""
    found: list[InterruptRequest] = []
    for output in outputs:
        request = getattr(output, "interrupt", None)
        if isinstance(request, InterruptRequest):
            found.append(request)
    return found


def open_ids(entries: Sequence[OpenInterrupt]) -> list[str]:
    """The ids of every committed open item."""
    return [entry.id for entry in entries]


def resolve_mailbox(root: Path) -> MailboxPort:
    """Import the installed mailbox file layer for one brain root, or refuse by name.

    Lazy and by dotted path for the same reason the seat layer is: `src/protean/mailbox/` is a
    separate order's package, and a checkout without it must fail loudly rather than raise an
    interrupt nobody can answer.
    """
    try:
        module = import_module(MAILBOX_MODULE)
    except ImportError as exc:
        raise MailboxUnavailable(f"{MAILBOX_MODULE} is not importable ({exc})") from exc
    builder = getattr(module, "build", None)
    if builder is None:
        raise MailboxUnavailable(f"{MAILBOX_MODULE} exposes no `build(root)`")
    port = builder(root)
    if not isinstance(port, MailboxPort):
        raise MailboxUnavailable(f"{MAILBOX_MODULE}.build() did not return a MailboxPort")
    return port
