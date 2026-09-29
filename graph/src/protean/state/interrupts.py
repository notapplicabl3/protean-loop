"""The mailbox's four models: request, file, open item, resolved item.

`the build specification (not in this mirror)` § Deliverable 2 (`InterruptRequest` → `Interrupt`) and
§ Deliverable 5 (the closed `kind` set, the two licensed raisers, the file format, the
answer path). This is **binding contract 4**'s state half — the file format and the answer
path — so nothing here is a builder's default.

**A node requests; the runtime writes.** `InterruptRequest` is the optional slot on every
node output model and every seat result model; the runtime turns it into an `Interrupt` on
disk as the commit's last append before the checkpoint, and records an `OpenInterrupt` in
committed state. No node writes the mailbox.

**The id derives from `(task, tick, raiser)`**, so a re-raise after a crash reproduces the
same filename and yields one open file, not two — the idempotency that M12's replay case
closes on is a property of `interrupt_id()`, not of a check somewhere in the runtime.
**Build A.1 widens it for a call-bearing raiser only** (`the build specification (not in this mirror)`
§ Scaffold clause item 2, contract 4): a think, escalate, delegate or dispatch member raises
under `(task, tick, node, raiser, call#[, member#])`, because a call type is a raiser every
outer node shares. The file's shape beyond the front matter, and the answer path, are
unchanged.

**There is no `default`** (folded: U-15). An unanswered item is refused, never defaulted:
silence is never assent, so no field here can carry "what to do if the operator says nothing".

**`OpenInterrupt` carries everything a re-materialized file needs** (folded: U-11) — question,
evidence, `raised_at` — because § Deliverable 3 makes a vanished mailbox file a
re-materialization from state followed by the ordinary refusal, never a terminal state.
"""

from __future__ import annotations

from pydantic import Field, JsonValue, model_validator

from protean.state.base import ProteanModel
from protean.state.enums import InterruptKind, Raiser

#: The literal heading the answer is written beneath, in the same file (§ Deliverable 5).
#: Exactly one path is writable by anything that is not the runtime process, and it is the
#: body under this heading.
ANSWER_HEADING = "## Answer"


#: The two markers that make the widened id parseable from the right, whatever the task id
#: holds: the call component is `c<call#>` and the member component `m<member#>`. Read back by
#: `components_of()`, which is what `protean.runtime.interrupts.resolution_target()` resolves a
#: call-type raiser's calling node through.
CALL_MARKER = "c"
MEMBER_MARKER = "m"


def interrupt_id(
    task: str,
    tick: int,
    raiser: str,
    node: str | None = None,
    call_number: int | None = None,
    member_number: int | None = None,
) -> str:
    """`(task, tick, raiser)` → the id, and therefore the filename. At most one per raiser
    per tick, which is what makes a crashed raise idempotent on replay.

    **Widened for a call-bearing raiser only** (`the build specification (not in this mirror)`
    § Scaffold clause item 2, contract 4's first amendment): a think, an escalate, a delegate
    or a dispatch member raises under `(task, tick, node, raiser, call#[, member#])`, because a
    call type is a raiser **every** outer node shares — the hippocampus's think and the
    thalamus's think in one tick would otherwise collapse onto one filename, and two members of
    one wave onto another — while a node or the runtime raising on its own account has no
    `call#` to put there and keeps the three-part id. Every component is therefore defined for
    every raiser and the id stays replay-stable by construction.

    **`node` is a component of the id, not a fact left in the file's body** (folded: S-A90):
    the id is the only thing the answer path is given, so a `node` absent from it is a `node`
    `resolution_target()` cannot recover.
    """
    if node is None and call_number is None:
        return f"{task}-t{tick}-{raiser}"
    if node is None or call_number is None:
        raise ValueError(
            "a call-bearing raiser's id carries both the calling node and the call number; "
            f"node={node!r}, call_number={call_number!r}"
        )
    identifier = f"{task}-t{tick}-{node}-{raiser}-{CALL_MARKER}{call_number}"
    if member_number is None:
        return identifier
    return f"{identifier}-{MEMBER_MARKER}{member_number}"


def components_of(identifier: str) -> tuple[str | None, str, int | None, int | None]:
    """One id → `(node, raiser, call#, member#)`, read from the right.

    From the right because the task id is the one component that may itself hold a `-`: the
    member and call components are marked, the raiser is the segment before them, and the node
    is the segment before that. A three-part id answers `(None, raiser, None, None)`, which is
    what a node or the runtime raising on its own account wrote.
    """
    parts = identifier.split("-")
    member: int | None = None
    call: int | None = None
    if len(parts) >= 2 and _marked(parts[-1], MEMBER_MARKER):
        member = int(parts[-1][1:])
        parts = parts[:-1]
    if len(parts) >= 3 and _marked(parts[-1], CALL_MARKER):
        call = int(parts[-1][1:])
        parts = parts[:-1]
        return (parts[-2] if len(parts) >= 2 else None), parts[-1], call, member
    return None, parts[-1], call, member


def _marked(segment: str, marker: str) -> bool:
    """Whether one segment is `<marker><digits>` — the only shape a component marker takes."""
    return len(segment) > 1 and segment[0] == marker and segment[1:].isdigit()


class _Raised(ProteanModel):
    """The kind/raiser licensing shared by every model below.

    § Deliverable 5: `question` is raised by a node as ordinary output; `stuck` is raised by
    the **runtime**, which is a licensed raiser for that one kind and no other.
    """

    kind: InterruptKind
    raised_by: Raiser

    @model_validator(mode="after")
    def _only_two_licensed_raisers(self) -> "_Raised":
        if self.kind is InterruptKind.STUCK and self.raised_by is not Raiser.RUNTIME:
            raise ValueError(
                f"kind={self.kind} may only be raised by {Raiser.RUNTIME}, not {self.raised_by}"
            )
        if self.kind is InterruptKind.QUESTION and self.raised_by is Raiser.RUNTIME:
            raise ValueError(
                f"{Raiser.RUNTIME} is licensed for {InterruptKind.STUCK} and no other kind"
            )
        return self


class InterruptRequest(_Raised):
    """A node's (or the runtime's) *request*, carried as ordinary output.

    One per raiser per tick, so `(task, tick, raiser)` is unique. A seat's request travels
    inside `SeatEnvelope.result` (folded: U-2).
    """

    question: str
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class Interrupt(_Raised):
    """The mailbox file itself: YAML front matter over a markdown body (folded: A1-5).

    `brain/mailbox/open/<id>.md`. Front matter is `schema_version`, `id`, `raised_by`, `task`,
    `tick`, `raised_at`, `kind`; the question is the body; the answer is written beneath
    `## Answer` **in the same file**.
    """

    schema_version: int
    id: str
    task: str
    tick: int
    raised_at: str
    question: str
    evidence: dict[str, JsonValue] = Field(default_factory=dict)
    answer: str | None = None

    def is_answered(self) -> bool:
        """An absent *or empty* `## Answer` body is unanswered (§ Deliverable 5)."""
        return self.answer is not None and self.answer.strip() != ""


class OpenInterrupt(_Raised):
    """The committed state entry. `BrainState.open_interrupts` is the mailbox's source of truth.

    A file on disk with no entry here is an orphan of a torn commit; an entry here whose file
    has vanished is re-materialized from these fields (folded: U-11).
    """

    id: str
    raised_at_tick: int
    raised_at: str
    path: str
    question: str
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class ResolvedInterrupt(_Raised):
    """Every answered Q+A this task. The operator's answers are the top reinforcement signal.

    Loaded into `BrainState.resolved_interrupts` **before the next tick runs**, which is the
    landing place that lets an answer change what the brain does next.
    """

    id: str
    raised_at_tick: int
    resolved_at_tick: int
    question: str
    answer: str
