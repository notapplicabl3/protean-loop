"""The advisory instance lock: one process per brain root, reclaimed loudly when it is dead.

`the build specification (not in this mirror)` § Deliverable 3 → *The instance lock*: "An advisory file at
the brain root carrying pid, start time and task id, taken at task start and released on every
exit path — the interrupt path included. A second run exits non-zero naming the holder. A
dead-pid lock is reclaimed, and the reclamation is printed and written as an `event`
`EpisodeRecord`, never silent."

**The lock is deliberately not a versioned artifact** (decision 12): it is inspected for a pid,
never loaded as a contract, so an unreadable or malformed lock is treated as stale rather than
raising a schema refusal. That is the one place in the build where a corrupt file is not a
refusal, and it is corrupt-lock-means-crashed rather than corrupt-lock-means-mismatch.

**Reclamation is a return value, not a side effect.** `acquire()` reports that it reclaimed and
from which pid; the caller prints it and writes the `lock_reclaimed` event, because writing an
episode record needs a task and a tick that this module has no business knowing.

**Parallel instances stay undefined** (folded: A1-4). This refuses a second instance; it does
not make two safe.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from protean.runtime.errors import LockHeld


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_is_live(pid: int) -> bool:
    """Whether a pid names a running process. Signal 0 tests without delivering."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True, slots=True)
class LockHolder:
    """What a lock file carries."""

    pid: int
    task_id: str
    started_at: str


@dataclass(frozen=True, slots=True)
class LockAcquisition:
    """The result of taking the lock, including whether a dead holder was reclaimed."""

    path: Path
    holder: LockHolder
    reclaimed_from: LockHolder | None = None

    @property
    def reclaimed(self) -> bool:
        return self.reclaimed_from is not None

    def message(self) -> str:
        """The line the operator surface prints on a reclamation. Never silent."""
        stale = self.reclaimed_from
        if stale is None:
            return ""
        return (
            f"reclaimed a stale lock at {self.path} from dead pid {stale.pid} "
            f"(task {stale.task_id!r}, started {stale.started_at})"
        )


def read_holder(path: Path) -> LockHolder | None:
    """The current holder, or `None` when the file is absent or unreadable.

    Unreadable is `None` on purpose: the lock is not a contract, so a torn write means the
    writer died mid-write, which is exactly the case a reclamation exists for.
    """
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return LockHolder(
            pid=int(payload["pid"]),
            task_id=str(payload["task_id"]),
            started_at=str(payload["started_at"]),
        )
    except (ValueError, KeyError, TypeError, OSError):
        return None


def _create_exclusively(path: Path, body: str) -> bool:
    """Land `body` at `path` only if nothing is there — whole when it appears, never torn.

    A hard link from a private temp file is the exclusive primitive: `os.link` fails with
    `FileExistsError` when the name is already taken, and the file that appears under the name
    already carries the full body, so a reader never sees a half-written lock.
    """
    temp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temp.write_text(body, encoding="utf-8")
    try:
        os.link(temp, path)
    except FileExistsError:
        return False
    finally:
        temp.unlink(missing_ok=True)
    return True


def acquire(path: Path, task_id: str, *, pid: int | None = None) -> LockAcquisition:
    """Take the lock, or raise `LockHeld` naming the live holder.

    A dead-pid lock is reclaimed and reported. Taking the lock is the **first act** of every
    `run` and every `resume`, flags included, before any read or write of task state.

    The take is exclusive (audit 2026-09-19, D2): the file is created by `_create_exclusively`,
    never written over a name the check found empty, so two instances starting inside the same
    window cannot both hold it — the second sees the first's file and is refused by name. What
    stays open is narrower: two instances reclaiming the *same dead* lock at once may both
    unlink it before one links. That is the unlink-to-link gap, not the check-to-write one.
    """
    mine = LockHolder(pid=os.getpid() if pid is None else pid, task_id=task_id, started_at=_now())
    body = json.dumps(
        {"pid": mine.pid, "task_id": mine.task_id, "started_at": mine.started_at},
        separators=(",", ":"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    reclaimed: LockHolder | None = None
    for _attempt in range(3):
        present = path.exists()
        holder = read_holder(path)
        if holder is not None and _pid_is_live(holder.pid):
            raise LockHeld(
                path=str(path),
                pid=holder.pid,
                task_id=holder.task_id,
                started_at=holder.started_at,
            )
        if present:
            # Dead or unreadable: stale (decision 12), removed so the exclusive take can land.
            if holder is not None:
                reclaimed = holder
            path.unlink(missing_ok=True)
        if _create_exclusively(path, body):
            return LockAcquisition(path=path, holder=mine, reclaimed_from=reclaimed)
    # Three takes lost in a row: something keeps landing first. Name it if it can be read.
    holder = read_holder(path)
    raise LockHeld(
        path=str(path),
        pid=holder.pid if holder is not None else 0,
        task_id=holder.task_id if holder is not None else "",
        started_at=holder.started_at if holder is not None else "",
    )


def release(path: Path) -> None:
    """Release on every exit path, the interrupt path included. Idempotent."""
    path.unlink(missing_ok=True)


class held:
    """Context manager form: acquire on enter, release on **every** exit path.

    `with held(paths.lock, task_id) as lock:` is how the operator surface guarantees the
    release, including the one that follows an `interrupted` commit and the one that follows a
    refusal raised inside the body.
    """

    def __init__(self, path: Path, task_id: str, *, pid: int | None = None) -> None:
        self._path = path
        self._task_id = task_id
        self._pid = pid
        self.acquisition: LockAcquisition | None = None

    def __enter__(self) -> LockAcquisition:
        self.acquisition = acquire(self._path, self._task_id, pid=self._pid)
        return self.acquisition

    def __exit__(self, *exc_info: object) -> None:
        release(self._path)
