"""`brain/seeds.yaml` — the seeding map, its refusals, and S-21's collision rule.

`the build specification (not in this mirror)` § Deliverable 3 (*Seeded priors come in, narrowly*),
§ Directional decisions 5, 11 and 12, § Rulings 20, § Named assumptions 11, § DoD row L5,
§ Resolutions A1-7, S-10, S-15, S-21.

**Build 2 seeded no weights key and this is where that changes** (folded: S-28). Without a seeded
key there is nothing in a weights file for the sleep graph to weaken, so the weakening clause
`brain/nodes/*/weights.yaml` exists to serve would go a second layer unproven. It comes in as a
*sparse hand-authored map* and no wider.

**The row is the provenance and nothing enters `weights.yaml` but a value** (folded: S-10). A
`seeds:` block inside a weights file would mint a key (decision 11), break row L4's `## Weights`
identity and reach the extras-forbidden node input projection, so `was_seeded` means *named in
`brain/seeds.yaml`* — which is what `protean.sleep.weights.seeded_keys()` reads and this module
writes against. The two readers of one file agree by construction: the shape below is one of the
two spellings that reader accepts.

**S-21's first-write-only guard, revived as the collision rule** (§ Named assumptions 11 — "Two
writers now touch `weights.yaml` and one comparison keeps them apart"). A row is applied **only**
while the on-disk value still equals the row's value; a key that has moved is skipped and
printed, by name, with both numbers. Sleep stays the sole *re*writer (`DIGEST:85`); intake stays a
seeder between tasks. The guard is deliberately memoryless — it asks the file, not a ledger —
which is why a seeded value that happens to equal a learned value is indistinguishable from an
unmoved key (§ Named assumptions 11, stated there as a known limit rather than fixed here).

**A consequence worth saying out loud: on the tracked tree the seeding write is a no-op.** The
map's values equal the numbers the node files carry, so "re-value while still equal" writes back
what is already there. That is the rule as specified and not a weakening of it: the guard's whole
content is the *skip*, and the write path is exercised — and non-vacuous — wherever the on-disk
*spelling* differs from the row's own (`20.0` loads equal to `20` and is re-valued to `20`).

**The write is a line edit, never a YAML round trip** (ledger `D14-2`). `WeightsFile` is order
W3's and is imported rather than copied: every seed file is half comments, the tracked half of
what these two writers touch is reviewed as a git diff (row B21), and a second line-substituter
would be a second thing to drift.

**Refusals, all of them before the first write.** A document that is not a mapping · a block that
is neither a row nor a list of rows · a row missing or over-naming a field · a node outside
`config.WEIGHTS_WRITABLE_NODES` (which is `NODE_ORDER` less the gate, whose weights file is the
empty mapping by contract) · a value that is not a number · a key the node's `weights.yaml` does
not already carry. **A key not already present is a refusal, not an insert** — decision 11, the
same sentence that governs a weight update.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from protean import config
from protean.runtime.paths import BrainPaths
from protean.sleep.weights import WeightsFile, format_value
from protean.state.base import ProteanModel
from protean.state.errors import RefusalError

#: The artifact name a refusal quotes, in `load_manifest`'s shape.
ARTIFACT = "seed_map"


class BadSeedMap(RefusalError):
    """A seeding map this build declines to read, quoting the row that made it undecidable.

    A `RefusalError` for `SchemaVersionMismatch`'s reason: it is the loader refusing an
    artifact, before anything is written, and `run_intake` resolves the whole map before it
    writes its first store so a bad map costs nothing.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"{ARTIFACT}: {detail}")


class SeedRow(ProteanModel):
    """One seeding row: which memory seeded which existing key, in which node, to what value.

    Extras-forbidden like every other contract in the build, which is what makes an unknown
    field a refused map rather than a silently dropped intention.
    """

    #: The provenance — a logical memory *name*, never a path (`brain/seeds.yaml`'s own note).
    memory: str
    node: str
    key: str
    #: Bounded to what a weights key holds and what a bounded step is defined over.
    value: int | float

    def weights_key(self) -> str:
        """`<node>/<key>` — the same spelling a `WeightUpdate` quotes."""
        return f"{self.node}/{self.key}"

    def seeded_key(self) -> tuple[str, str]:
        """The `(node, key)` pair `protean.sleep.weights.seeded_keys()` reads out of the map."""
        return (self.node, self.key)


@dataclass(frozen=True, slots=True)
class SeedWrite:
    """What the collision rule decided for one row, and the line the verb prints for it."""

    row: SeedRow
    path: Path
    #: The value the node's file held when the comparison was made.
    on_disk: int | float
    #: `True` when the on-disk value still equalled the row's — the re-value arm.
    applied: bool
    #: `True` only when the re-value actually changed the file's bytes.
    changed: bool = False

    def message(self) -> str:
        """One unambiguous line, naming both numbers whenever they disagree (Process step 4).

        Never `wrote …`: that prefix is reserved for one line per *file* the verb wrote, and
        two rows may re-value two keys of one file.
        """
        row = self.row
        if not self.applied:
            return (
                f"intake: skipped {row.weights_key()} — {self.path} holds "
                f"{format_value(self.on_disk)} and the seeding row {row.memory!r} holds "
                f"{format_value(row.value)}; a key that has moved belongs to sleep, the sole "
                f"re-writer, and intake never overwrites a learner"
            )
        tail = "" if self.changed else " — unchanged, the file already holds it"
        return (
            f"intake: seeded {row.weights_key()} = {format_value(row.value)} from "
            f"{row.memory!r}{tail}"
        )


@dataclass(frozen=True, slots=True)
class SeedPlan:
    """Every row resolved against disk, and the open files no write has touched yet.

    Resolution and commit are two steps because `run_intake` refuses a bad map **before** it
    replaces a single store: the loader's refusals and the absent-key refusal both fire here.
    """

    writes: tuple[SeedWrite, ...]
    #: `(open file, its text when it was opened)`. The second half is why: `WeightsFile.revalue`
    #: marks a handle dirty on every successful substitution, including one that re-writes the
    #: token already there — and a run that rewrote a byte-identical file would print a `wrote`
    #: line for a file it did not change.
    _files: tuple[tuple[WeightsFile, str], ...] = ()

    def commit(self) -> tuple[Path, ...]:
        """Write every weights file whose bytes actually moved, and nothing else."""
        return tuple(
            handle.commit() for handle, opened in self._files if handle.text != opened
        )

    @property
    def applied(self) -> tuple[SeedWrite, ...]:
        return tuple(write for write in self.writes if write.applied)

    @property
    def skipped(self) -> tuple[SeedWrite, ...]:
        return tuple(write for write in self.writes if not write.applied)


def load_seed_map(path: Path) -> tuple[SeedRow, ...]:
    """Read `brain/seeds.yaml` into rows. A missing file means **nothing is seeded**.

    Never creates the file, for `seeded_keys()`'s reason: a checkout that carries no map seeds
    no weights key, and the absence is an answer rather than an error.
    """
    if not path.is_file():
        return ()
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if document is None:
        return ()
    if not isinstance(document, Mapping):
        raise BadSeedMap(
            f"{path} is a mapping of memory name to seeding row(s), not "
            f"{type(document).__name__}"
        )
    rows: list[SeedRow] = []
    for memory, block in document.items():
        for payload in _row_payloads(memory, block, path):
            rows.append(_row(memory, payload, path))
    return tuple(rows)


def _row_payloads(memory: Any, block: Any, path: Path) -> list[Mapping[str, Any]]:
    """A memory's block, as a list of row mappings. One row or many, and nothing else."""
    if isinstance(block, Mapping):
        return [block]
    if isinstance(block, Sequence) and not isinstance(block, (str, bytes)):
        for item in block:
            if not isinstance(item, Mapping):
                raise BadSeedMap(
                    f"{path}: {memory!r} lists {type(item).__name__}, and a seeding row is a "
                    f"mapping of node, key and value"
                )
        return list(block)
    raise BadSeedMap(
        f"{path}: {memory!r} holds {type(block).__name__}, and a memory names one seeding row "
        f"or a list of them"
    )


def _row(memory: Any, payload: Mapping[str, Any], path: Path) -> SeedRow:
    """One validated row. An unknown field, a missing one or a bad node is a refused map.

    The boolean arm runs on the *raw* payload, before validation: pydantic's lax mode reads
    `true` as the integer `1`, so a row asserting a flag would otherwise seed a threshold.
    """
    if isinstance(payload.get("value"), bool):
        raise BadSeedMap(
            f"{path}: {memory!r} holds a boolean value, which no weights key carries"
        )
    try:
        row = SeedRow.model_validate({"memory": str(memory), **dict(payload)})
    except ValidationError as invalid:
        raise BadSeedMap(f"{path}: {memory!r} names an unreadable row — {invalid}") from invalid
    if row.node not in config.WEIGHTS_WRITABLE_NODES:
        raise BadSeedMap(
            f"{path}: {row.node!r} is not one of the {len(config.WEIGHTS_WRITABLE_NODES)} node "
            f"folders whose weights.yaml may be written "
            f"({', '.join(config.WEIGHTS_WRITABLE_NODES)})"
        )
    return row


def plan_seeds(brain: BrainPaths, rows: Sequence[SeedRow]) -> SeedPlan:
    """Resolve every row against the node files and apply the collision rule. Writes nothing.

    Raises `BadSeedMap` for a node folder with no `weights.yaml` and for a key that file does
    not already carry — decision 11's "a key not already present is a refusal, not an insert",
    said of the seeder rather than of the learner.
    """
    handles: dict[str, tuple[WeightsFile, str]] = {}
    writes: list[SeedWrite] = []
    for row in rows:
        path = brain.node_weights(row.node)
        if not path.is_file():
            raise BadSeedMap(
                f"{path} does not exist, so {row.weights_key()} names no seeded key"
            )
        if row.node not in handles:
            opened = WeightsFile(path)
            handles[row.node] = (opened, opened.text)
        handle = handles[row.node][0]
        if row.key not in handle.keys:
            raise BadSeedMap(
                f"absent key: {row.key!r} is not in {path.name} for node {row.node} — a seeding "
                f"row re-values an existing key and never mints one"
            )
        on_disk = handle.value_of(row.key)
        applied = _comparable(on_disk) and on_disk == row.value
        changed = False
        if applied:
            before = handle.text
            handle.revalue(row.key, row.value)
            changed = handle.text != before
        writes.append(
            SeedWrite(
                row=row, path=path, on_disk=on_disk, applied=applied, changed=changed
            )
        )
    return SeedPlan(writes=tuple(writes), _files=tuple(handles.values()))


def _comparable(value: Any) -> bool:
    """A weights value the collision rule can compare. `True == 1` is not a number here."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def seeded_keys(rows: Sequence[SeedRow]) -> frozenset[tuple[str, str]]:
    """The `(node, key)` set the map names — the seeder's half of `was_seeded`.

    `protean.sleep.weights.seeded_keys()` reads the same file for the reader's half; this one
    exists so a test can assert the two agree over the shipped seed rather than assume it.
    """
    return frozenset(row.seeded_key() for row in rows)


__all__ = [
    "ARTIFACT",
    "BadSeedMap",
    "SeedPlan",
    "SeedRow",
    "SeedWrite",
    "load_seed_map",
    "plan_seeds",
    "seeded_keys",
]
