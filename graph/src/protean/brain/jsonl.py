"""The append-only keyed-append primitive every runtime-written `.jsonl` file uses.

`the build specification (not in this mirror)` § Deliverable 3 → *Idempotent replay is a physical rule*:
"every appended artifact is append-only; before appending, a writer reads the file's tail for
this tick's existing keys and treats a key collision as a **silent no-op** — distinct from the
two raising refusals of decision 5 — so the surviving orphan is authoritative".

**Two behaviours live here and they are deliberately different.** A key collision returns
`None` and writes nothing, because the record already on disk is the authoritative one and a
replay must not double it. A *refusal* — a record the contract forbids — is not this module's
business at all: `protean.brain.trace` raises before it ever reaches `append_keyed`, so the
file is byte-unchanged for a reason stronger than "we checked the tail".

**Append-only is physical, not asserted.** Every write opens the file in `"a"` mode and the
module offers no path that truncates or rewrites one, so the bytes already in a file are always
a prefix of the bytes after a write. The one file the runtime truncates is the per-tick journal,
which does it through `protean.runtime.journal` and its own `unlink`, never through here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Hashable, Iterator
from pathlib import Path
from typing import Any

#: One JSON document per line, no spaces, UTF-8 — the same separators the checkpoint
#: canonicalization uses, so a line is byte-stable for a given payload.
_SEPARATORS = (",", ":")


def encode_line(payload: Any) -> str:
    """One record as its `.jsonl` line, terminator included."""
    return json.dumps(payload, separators=_SEPARATORS, ensure_ascii=False) + "\n"


def read_lines(path: Path) -> list[dict[str, Any]]:
    """Every record in the file, in order. A missing file reads as no records."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def iter_lines(path: Path) -> Iterator[dict[str, Any]]:
    """Every record in the file, streamed."""
    yield from read_lines(path)


def existing_keys(path: Path, key_fn: Callable[[dict[str, Any]], Hashable]) -> set[Hashable]:
    """The keys already committed to this file — the tail read that makes a replay idempotent."""
    return {key_fn(record) for record in read_lines(path)}


def append_keyed(
    path: Path,
    payload: dict[str, Any],
    *,
    key_fn: Callable[[dict[str, Any]], Hashable],
) -> dict[str, Any] | None:
    """Append one record unless its key is already on disk.

    Returns the payload when it was written and `None` when the key collided, so a caller can
    tell "committed now" from "already committed" without re-reading the file. The parent
    directory is created on demand: the brain root's generated directories are untracked
    (`protean.config.GENERATED_BRAIN_DIRS`) and a fresh checkout does not carry them.
    """
    key = key_fn(payload)
    if key in existing_keys(path, key_fn):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encode_line(payload))
    return payload
