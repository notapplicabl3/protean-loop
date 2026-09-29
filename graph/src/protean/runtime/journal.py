"""The per-tick journal: crash forensics, observability, and the seat-envelope store.

`the build specification (not in this mirror)` § Deliverable 3 → *Two writes, and they are not the same
write*: "after every node — a journal entry. `journal.jsonl`, keyed `(task, tick, node)`,
overwritten on replay … **It is never a resume point.**" and "the journal is one file per tick,
`journal-<tick>.jsonl`, truncated on replay".

**Truncate, do not append, when a tick replays.** Every other artifact in the build is
append-only and treats a key collision as a no-op; the journal is the exception, and it is the
exception precisely because it is not a resume point — the checkpoint's presence is what "tick
completed" means, so a replayed tick's journal is allowed to be replaced by the replay's.

**It is a loaded artifact, which is why it is versioned.** A re-run restores the journaled
`SeatEnvelope` rather than re-invoking the call (folded: S-4), so this file is read by the
runtime and not only written by it — and a loaded artifact is a contract with a
`schema_version` its loader refuses a mismatch on.

**Build A.1 generalizes the key and nothing else** (`the build specification (not in this mirror)`
§ Deliverable 6, folded: A1-2). The restore is keyed `(node, call#, member#)` rather than on the
cortex folder and a tier, so **any** node's call restores rather than only the seat's: the
seat's single exception became the rule when a tick learned to hold several calls. The
truncate-at-tick-start rule and "it is never a resume point" are unchanged, and so is the
condition's *meaning* — what a replay must not redo. What restores is a call entry carrying a
**restorable result**; an entry recording a refusal or a timeout carries no envelope, so that
call is re-invoked in place while the journalled calls after it still restore.
"""

from __future__ import annotations

from pathlib import Path

from protean import config
from protean.brain.jsonl import encode_line, read_lines
from protean.state.enums import NodeName
from protean.state.errors import SchemaVersionMismatch
from protean.state.records import JournalEntry
from protean.state.seats import SeatEnvelope


def start_tick(path: Path) -> None:
    """Truncate this tick's journal. Called once, before the tick's first node runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def append(path: Path, entry: JournalEntry) -> JournalEntry:
    """Append one entry. The tick's file is truncated at tick start, so keys cannot collide."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encode_line(entry.model_dump(mode="json")))
    return entry


def load(path: Path) -> list[JournalEntry]:
    """Every entry of one tick, refusing a `schema_version` this code does not write."""
    entries: list[JournalEntry] = []
    for record in read_lines(path):
        found = int(record.get("schema_version", -1))
        if found != config.JOURNAL_SCHEMA_VERSION:
            raise SchemaVersionMismatch(
                artifact="journal",
                found=found,
                expected=config.JOURNAL_SCHEMA_VERSION,
            )
        entries.append(JournalEntry.model_validate(record))
    return entries


def journalled_calls(path: Path) -> list[JournalEntry]:
    """Every **call** entry this tick already journalled, in key order.

    The node's own output entry at the reserved `call# = 0` is not a call and is not here: it
    records what the node produced, never what a re-invoke would redo. Read **before**
    `start_tick()` truncates, which is the whole reason the restore is built at the top of the
    tick rather than at the step that needs it.
    """
    if not path.exists():
        return []
    return sorted(
        (entry for entry in load(path) if entry.is_call()),
        key=lambda entry: (
            str(entry.node),
            entry.call_number,
            -1 if entry.member_number is None else entry.member_number,
        ),
    )


def journaled_envelope(
    path: Path, node: NodeName | str, call_number: int, member_number: int | None = None
) -> SeatEnvelope | None:
    """The `SeatEnvelope` this tick already recorded for one call key, or `None`.

    The restore half of § Deliverable 3's one named exception to idempotency-from-purity: a call
    is the one thing whose effect is external, so a replay reads its envelope back rather than
    invoking it a second time. A crash that fell *inside* a call leaves no entry, the replay
    re-invokes, and the workspace is re-observed.

    **Keyed `(node, call#, member#)` in build A.1**, where build 1 keyed the cortex folder and a
    tier: a tick holds several calls now, and the tier of a think call is not a thing that
    exists. `None` means either no such entry or an entry with no restorable result — the two
    are the same answer to the only question the replay asks.
    """
    wanted = (
        str(NodeName(node) if not isinstance(node, NodeName) else node),
        call_number,
        member_number,
    )
    for entry in journalled_calls(path):
        if (str(entry.node), entry.call_number, entry.member_number) == wanted:
            return entry.envelope
    return None


def restorable_calls(path: Path) -> dict[tuple[str, int, int | None], JournalEntry]:
    """`(node, call#, member#) → the entry` for every call carrying a **restorable result**.

    The replay's whole condition (§ Deliverable 6, folded: S-A36): *a restorable result being
    present*, never an entry existing. In key order, so a restore walks the tick's calls in the
    order the keys give rather than the order the file happens to hold.
    """
    return {
        (str(entry.node), entry.call_number, entry.member_number): entry
        for entry in journalled_calls(path)
        if entry.is_restorable()
    }


def has_entries(path: Path) -> bool:
    """Whether this tick wrote anything — half of the replay-or-advance classifier."""
    return path.exists() and bool(read_lines(path))
