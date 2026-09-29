"""The three live session handles: minted once per task, resumed on every later call.

`the build specification (not in this mirror)` § Deliverable 1 → *Sessions*, and build 1's § Deliverable 6
*fresh per task, cached within task* (`DIGEST:70`, S8-1).

**`SessionBook`'s contract is unchanged and this is its live half.** Build 1's scripted book
mints three `uuid4` stand-ins per task and hands the same three back for the life of it; the
live book mints three real `--session-id` values and does one more thing with them: it
remembers which have been *opened*, because the CLI mints a session with `--session-id` and
joins it with `--resume`, and passing the wrong one of those two is the difference between a
cold call and the cache hold the first wet row measured (22,170 tokens created = 22,170 read).

**A restore is not a mint.** `restore()` adopts the two seat handles a checkpoint carried and
marks all three opened, so a resume in a new process joins the sessions that already exist
rather than minting three more — which is exactly what row W2 checks by looking for the
absence of `--session-id` in a resumed run's recorded argv.

**A restore marks them opened-but-*unconfirmed*.** Both seat handles are minted at task open
and only one tier is invoked per tick, so a checkpoint can carry a handle whose session the CLI
was never asked to create; after a crash before that tier's first invocation, a resume would
send `--resume` on a session that does not exist, deterministically, on every retry. `restore()`
therefore also records the three as `unconfirmed`, and a handle leaves that set only when an
invocation has actually run against it (`mark_opened()`). The adapter reads
`is_unconfirmed()` to know that a non-zero exit on this call may mean "no such session", and
falls back once to `--session-id` on the same handle.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from protean.state.enums import Tier

#: The two forms a handle takes on the command line, and which one a call carries.
SESSION_MINT_FLAG = "--session-id"
SESSION_RESUME_FLAG = "--resume"


def mint_handle() -> str:
    """One session id. Opaque and minted, never derived from the task id.

    A handle a second process could recompute would hide the fact that reusing one across a
    resume needs it to have been **carried** rather than re-derived.
    """
    return str(uuid.uuid4())


def call_session() -> str:
    """A **session-less** call's handle: minted fresh per invocation, then discarded.

    `the build specification (not in this mirror)` § Deliverable 2 and § Deliverable 5's session-mechanics
    clause (folded: S-A31). The mechanics are "mint, resume, discard at task end" for the two
    seats and **none** for everything else: a think, escalate, delegate or dispatch call carries
    a fresh `--session-id` and nothing about it is checkpointed — no entry in the book, no entry
    in `BrainState.seat_sessions`, which is keyed by tier and refuses anything else.

    The reason is that these calls are small, cold and independent: a node's think about this
    tick's own input carries nothing forward to the next tick's think, so a resumable handle per
    node per call type would buy a warm cache nobody reads at the price of a slot in committed
    state. **It is a function and not a book method** because there is deliberately nothing to
    keep: the book below would have to remember a handle for the rule to be broken.
    """
    return mint_handle()


@dataclass(slots=True)
class LiveSessionBook:
    """One handle per tier for the life of a task, and which flag the next call carries.

    Implements `protean.runtime.seat.SeatSessions` — `for_task()` and `restore()` — so the
    runtime checkpoints the two seat handles at the boundary and hands them back on a resume
    without knowing anything about how they are used.
    """

    task_id: str | None = None
    handles: dict[str, str] = field(default_factory=dict)
    opened: set[str] = field(default_factory=set)
    unconfirmed: set[str] = field(default_factory=set)
    minted_tasks: list[str] = field(default_factory=list)

    def open_task(self, task_id: str) -> dict[str, str]:
        """Mint both seat handles the first time this task is seen; return the same two after."""
        if self.task_id == task_id:
            return dict(self.handles)
        self.task_id = task_id
        self.handles = {str(tier): mint_handle() for tier in Tier}
        self.opened = set()
        self.unconfirmed = set()
        self.minted_tasks.append(task_id)
        return dict(self.handles)

    def for_task(self, task_id: str) -> dict[str, str]:
        """The two seat handles open for this task — nothing if a different task is open."""
        return dict(self.handles) if self.task_id == task_id else {}

    def restore(self, task_id: str, handles: Mapping[str, str]) -> None:
        """Adopt a checkpoint's handles and mark them opened — but *unconfirmed*.

        A resume joins rather than mints (row W2), so all three carry `--resume`. None of the
        three is known to exist yet, though: the checkpoint records what was minted at task
        open, not what was invoked. Until an invocation runs against one, it stays in
        `unconfirmed` and the adapter is allowed to fall back to `--session-id` on it once.
        """
        if not handles:
            return
        self.task_id = task_id
        self.handles = {str(key): str(value) for key, value in handles.items()}
        self.opened = set(self.handles)
        self.unconfirmed = set(self.handles)

    def close_task(self) -> None:
        """Discard all three at task end. A later task mints its own."""
        self.task_id = None
        self.handles = {}
        self.opened = set()
        self.unconfirmed = set()

    def handle(self, tier: Tier | str) -> str:
        """The handle this tier is using. A call before a task opened is a wiring bug."""
        key = str(Tier(tier))
        if key not in self.handles:
            raise RuntimeError(
                "no seat session is open: the router opens the task before the port is called"
            )
        return self.handles[key]

    def session_flag(self, tier: Tier | str) -> tuple[str, str]:
        """`--session-id <h>` on this tier's first call of the task, `--resume <h>` after.

        Reading it does not open the session: `mark_opened()` is called once the invocation has
        actually happened, so a call that never left the adapter does not strand the handle in
        a state where the next one would try to resume a session that was never minted.
        """
        key = str(Tier(tier))
        handle = self.handle(key)
        flag = SESSION_RESUME_FLAG if key in self.opened else SESSION_MINT_FLAG
        return flag, handle

    def mark_opened(self, tier: Tier | str) -> None:
        """Record that an invocation has run on this tier: the next call resumes it.

        This is also what *confirms* a restored handle — an invocation has now been made
        against it, so a later non-zero exit is a failure of the call rather than possible
        evidence that the session was never created.
        """
        key = str(Tier(tier))
        self.opened.add(key)
        self.unconfirmed.discard(key)

    def is_unconfirmed(self, tier: Tier | str) -> bool:
        """True while this tier's handle came from a checkpoint and has not been invoked yet."""
        return str(Tier(tier)) in self.unconfirmed
