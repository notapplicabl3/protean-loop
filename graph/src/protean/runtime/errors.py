"""The refusals the runtime raises that are not contract refusals.

`the build specification (not in this mirror)` § Deliverable 3 — the instance lock ("a second run exits
non-zero naming the holder"), one task per brain root ("`run` refuses, with its own exit code,
while a task exists there whose committed `terminal` is anything but `done`"), and the operator
surface.

`protean.state.errors` holds the *contract* refusals — version, integrity, seed hash, reads
drift, trace append, unanswered interrupt — because a loader raises them and loaders live in the
state layer. The three below are process-level: they are about this brain root and this machine,
not about an artifact's shape.

**No exit code is named here.** `protean.config` owns the table and `protean.cli` reads it, so a
refusal that changed its code would change one mapping rather than an exception.
"""

from __future__ import annotations

from protean.state.errors import ProteanError


class LockHeld(ProteanError):
    """A second instance against a brain root whose lock is live. The message names the holder."""

    def __init__(self, path: str, pid: int, task_id: str, started_at: str) -> None:
        self.path = path
        self.pid = pid
        self.task_id = task_id
        self.started_at = started_at
        super().__init__(
            f"{path} is held by pid {pid} running task {task_id!r} since {started_at} — "
            f"one instance per brain root"
        )


class RootOccupied(ProteanError):
    """`run` against a root already holding a task that has not committed `done`."""

    def __init__(self, task_id: str, terminal: str | None) -> None:
        self.task_id = task_id
        self.terminal = terminal
        super().__init__(
            f"brain root already holds task {task_id!r} (terminal={terminal!r}) — "
            f"`resume` it, or free the root with `resume --abandon`"
        )


class NoTask(ProteanError):
    """`resume` or `status` against a root with no checkpointed task."""

    def __init__(self, root: str) -> None:
        self.root = root
        super().__init__(f"no task is checkpointed under {root} — start one with `run`")


class LayerUnavailable(ProteanError):
    """A package the runtime holds the port for is not installed in this checkout.

    The runtime declares two seams it does not implement — the cortex seat layer and the
    mailbox's file half — and both live in their own packages. This is not a *refusal* with a
    `config` exit code: none of the five named refusals means "a layer is missing", so the
    operator surface prints it and exits through `SystemExit` rather than inventing a code.
    """


class SeatLayerUnavailable(LayerUnavailable):
    """`src/protean/cortex/` is absent, so no tick can run.

    Build 1's seats are scripted and live there; the runtime holds only the port they
    implement. A checkout without it can still `status`, which runs no node.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"no cortex seat layer is installed: {detail}")


class MailboxUnavailable(LayerUnavailable):
    """`src/protean/mailbox/` is absent, so an interrupt could be raised and never written."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"no mailbox file layer is installed: {detail}")


class SeatUnavailable(ProteanError):
    """A live seat call that produced no answer at all — build 2's decision 11.

    `the build specification (not in this mirror)` § Deliverable 1 → *Failure is not an envelope*
    (folded: A1-9, folded: S-32, folded: S-33). A non-zero exit, an `is_error` response, a
    rate limit, or a timeout cannot satisfy `SeatEnvelope`'s four required facts, so the
    adapter refuses **by name** instead of constructing an envelope out of a failure.

    **It lives here and not in the cortex package** so the runtime can catch it without
    importing the seats: the seat step is inside `runtime/cycle.py`, and a `except` clause
    that had to import `protean.cortex` would invert the seam the whole build is built on.

    It is not a `LayerUnavailable`: the layer is installed and answering, this one *call*
    refused. The tick still completes — a null cortex journal entry, the monitor runs, the
    boundary commits `stopped` and raises the mailbox interrupt carrying `message` verbatim.

    `message` is the CLI's own words, unedited, because that string is what reaches the operator in the
    mailbox and a paraphrase would be the runtime guessing at a failure it did not diagnose.
    """

    def __init__(self, tier: str, reason: str, message: str = "", exit_code: int | None = None):
        self.tier = tier
        self.reason = reason
        self.message = message
        self.exit_code = exit_code
        detail = f" ({message})" if message else ""
        code = "" if exit_code is None else f", exit {exit_code}"
        super().__init__(f"the {tier} seat is unavailable: {reason}{code}{detail}")
