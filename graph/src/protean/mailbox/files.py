"""The mailbox's file half: one directory of open items, and the five calls the runtime makes.

`the build specification (not in this mirror)` § Deliverable 5 — the file mailbox holding **only open
items**, read at a tick boundary and never polled — and § Deliverable 3's resume order, which
is where `orphan` and the re-materializing `write` are called from.

**The runtime owns the state half; this module owns the files.**
`protean.runtime.interrupts.MailboxPort` declares the calls and their order:

* `write` — render one open item into `mailbox/open/<id>.md`. Called inside the boundary
  commit, as its **last append before the checkpoint**, and again on resume to re-materialize
  an item whose file has vanished.
* `read` — the item on disk, answer included, or `None` when the file is gone.
* `open_ids` — every id with a file, whether or not committed state knows about it. Reconcile
  reads this against `BrainState.open_interrupts`.
* `delete` — a resolved item's file, removed inside the commit **after** the `operator_answer`
  outcome and the `interrupt_resolved` episode have landed.
* `orphan` — a file with no committed entry is an orphan of a torn commit; it is moved to
  `mailbox/orphaned/` and never counted as open again.

**The write is a whole-file replace, and the id is what makes that safe.** An interrupt id
derives from `(task, tick, raiser)`, so a raise re-run after a crash reproduces the same
filename: the replay overwrites its own orphan rather than appending a second file, which is
the on-disk shape M12's replay case closes on. A file that reached the disk without its
committed entry is orphaned by the reconcile that runs *before* any replay, so a replaced file
is never one a person has already answered.

**Nothing here writes an answer.** Exactly one path is writable by anything that is not the
runtime process — the `## Answer` body — and this package is the runtime. A caller that stands
in for the person at that keyboard supplies its own writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protean.mailbox.format import MailboxFormatError, parse, render
from protean.state.interrupts import Interrupt

#: The suffix every mailbox item carries — the format is markdown under YAML front matter.
ITEM_SUFFIX = ".md"

#: The two directories under the brain root this layer owns, relative to it. Both are generated
#: state (`protean.config.GENERATED_BRAIN_DIRS`), so neither is assumed to exist on disk.
OPEN_DIR = ("mailbox", "open")
ORPHANED_DIR = ("mailbox", "orphaned")


@dataclass(frozen=True, slots=True)
class FileMailbox:
    """`protean.runtime.interrupts.MailboxPort` over one brain root's `mailbox/` tree."""

    root: Path

    @property
    def open_dir(self) -> Path:
        """`brain/mailbox/open/` — one file per OPEN item, and nothing else."""
        return self.root.joinpath(*OPEN_DIR)

    @property
    def orphaned_dir(self) -> Path:
        """`brain/mailbox/orphaned/` — where a torn commit's leftover file is set aside."""
        return self.root.joinpath(*ORPHANED_DIR)

    def path_for(self, interrupt_id: str) -> Path:
        """The one filename an id maps to. `OpenInterrupt.path` is this, as a string."""
        return self.open_dir / f"{interrupt_id}{ITEM_SUFFIX}"

    def write(self, interrupt: Interrupt) -> Path:
        """Render one open item and return its path. The commit's last append."""
        self.open_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(interrupt.id)
        path.write_text(render(interrupt), encoding="utf-8")
        return path

    def read(self, interrupt_id: str) -> Interrupt | None:
        """The item on disk, answer included, or `None` when its file has vanished."""
        path = self.path_for(interrupt_id)
        if not path.exists():
            return None
        try:
            return parse(path.read_text(encoding="utf-8"))
        except MailboxFormatError as exc:
            raise MailboxFormatError(f"{path}: {exc}") from exc

    def open_ids(self) -> list[str]:
        """Every id with a file in `mailbox/open/`, sorted, whether or not state knows it."""
        if not self.open_dir.exists():
            return []
        return sorted(
            path.name[: -len(ITEM_SUFFIX)]
            for path in self.open_dir.iterdir()
            if path.is_file() and path.name.endswith(ITEM_SUFFIX)
        )

    def delete(self, interrupt_id: str) -> None:
        """Remove a resolved item's file. Called after its records have landed, never before."""
        self.path_for(interrupt_id).unlink(missing_ok=True)

    def orphan(self, interrupt_id: str) -> Path:
        """Move a file with no committed entry aside. It is never counted as open again."""
        self.orphaned_dir.mkdir(parents=True, exist_ok=True)
        target = self.orphaned_dir / f"{interrupt_id}{ITEM_SUFFIX}"
        self.path_for(interrupt_id).replace(target)
        return target


def build(root: Path | str) -> FileMailbox:
    """The entry point `protean.runtime.interrupts.resolve_mailbox` imports and calls.

    Resolved lazily and by dotted path from the runtime, so a checkout without this package
    fails loudly rather than raising an interrupt nobody can answer.
    """
    return FileMailbox(root=Path(root))
