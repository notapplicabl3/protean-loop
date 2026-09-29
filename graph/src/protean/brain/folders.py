"""Reading a node folder: its `NODE.md`, its `weights.yaml`, the drift refusal, the seed hash.

`the build specification (not in this mirror)` § Deliverable 4 → *`NODE.md` is prose, and the model is the
contract*: "A startup check asserts each `NODE.md`'s `## Reads` list names exactly the fields
its input model declares — no more, no fewer — and a drift is a refusal, not a warning."
§ Deliverable 2 adds the other half: `Checkpoint.seed_hashes` carries "`{relative path: sha256}`
for **every `weights.yaml` and `NODE.md` the run loaded**".

**The drift check is not re-implemented here.** `protean.state.reads.check_reads()` owns both
sides of it — the model side and the parse of the `## Reads` list — so this module reads the
file and hands the text over. A second parser would be a second thing to drift from the seed
files it is checking.

**A weights file may be empty and that is a contract, not a tolerance.**
`brain/nodes/basal_ganglia/weights.yaml` is the empty mapping on purpose: both arms of the
gate's veto are contractual, so there is no number anyone may retune. `load_weights()`
therefore reads `{}` and a comments-only file (which parses to `None`) identically.

**Nothing here writes.** `weights.yaml`, `NODE.md` and `procedures/` are read-only in build 1 —
the offline sleep graph is their only writer and it is build 3 — and the runtime's only write
under a node folder is the append to `trace.jsonl`. **Build 3 reads the fourth entry**:
`read_procedures()` and `procedure_set()` below load the compiled habits a task opens with
(`the build specification (not in this mirror)` § Deliverable 4), still without writing one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from protean import config
from protean.runtime import paths as paths_module
from protean.runtime.paths import BrainPaths
from protean.state.enums import NodeName
from protean.state.reads import check_reads

#: The two hand-authored seed files inside every node folder, in the order they are hashed.
SEED_FILES: tuple[str, ...] = ("NODE.md", "weights.yaml")

#: The one synthetic `seed_hashes` key — an inventory digest rather than a file (build 2,
#: folded: S-11). It is not a path and nothing reads a file for it; `seed_reader()` recomputes
#: it. Written only when the widened set is non-empty, so a build-1 checkpoint never grows it.
SEED_INDEX_KEY: str = "seeds/index"

#: What a recorded seed that is no longer on disk hashes to. Deliberately not a hex digest, so
#: it can never collide with a real sha256 and "gone" is always a mismatch.
SEED_ABSENT: str = "absent"


@dataclass(frozen=True, slots=True)
class NodeFolder:
    """One node's folder, read once at task start and never written except through `trace`."""

    node: NodeName
    path: Path
    node_md: str
    weights: Mapping[str, Any]

    @property
    def trace_path(self) -> Path:
        """`trace.jsonl` — the one file under this folder the runtime appends to."""
        return self.path / "trace.jsonl"

    @property
    def procedures_path(self) -> Path:
        """`procedures/` — build 3 compiles habits here; build 1 reads and writes nothing."""
        return self.path / "procedures"


def load_weights(path: Path) -> Mapping[str, Any]:
    """A `weights.yaml` as a mapping. An empty or comments-only file is the empty mapping."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{path}: a weights file is a mapping, not {type(loaded).__name__}")
    return dict(loaded)


def read_node_folder(node: NodeName | str, root: Path) -> NodeFolder:
    """Read one node folder and refuse a `## Reads` list that has drifted from its model.

    Raises `protean.state.errors.ReadsDrift` — which the operator surface maps to
    `config.EXIT_SEED_DRIFT` — before returning, so a drifted folder can never be used. That exit
    code is **shared** with the call policy's seed-shape refusal
    (`the build specification (not in this mirror)` § Deliverable 1), which `engine.build_context()` raises
    over the folders this reads.
    """
    name = NodeName(node)
    path = config.node_dir(str(name), root)
    node_md = (path / "NODE.md").read_text(encoding="utf-8")
    check_reads(name, node_md)
    return NodeFolder(
        node=name,
        path=path,
        node_md=node_md,
        weights=load_weights(path / "weights.yaml"),
    )


def read_all_folders(root: Path) -> dict[NodeName, NodeFolder]:
    """Every folder in `config.NODE_ORDER`, drift-checked. The runtime's startup check."""
    return {
        NodeName(name): read_node_folder(name, root) for name in config.NODE_ORDER
    }


def file_sha256(path: Path) -> str:
    """The hash `Checkpoint.seed_hashes` stores, over the file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_relative_path(node: str, filename: str) -> str:
    """The brain-root-relative key a seed hash is stored under — stable across roots.

    `protean dry` runs against a copy of the seed tree, so an absolute key would make every
    dry run's checkpoint unrepeatable and `resume --reseed`'s diff meaningless.
    """
    return f"nodes/{node}/{filename}"


def widened_seed_files(root: Path) -> list[str]:
    """The seeds outside the node folders, brain-root-relative, **present at task start**.

    `the build specification (not in this mirror)` § Deliverable 1's seed-hash paragraph (folded: S-4,
    folded: S-11): the ladder widens from `NODE.md` + `weights.yaml` to also cover
    `seats.yaml`, `seats/**/*.md` — **recursive from build A.1, so the two call-type prefixes
    under `seats/calls/` are hashed like the two seats' own** (§ Resolutions D11-4) —
    `intake/manifest.yaml` and `semantic/*.jsonl`. **Build 3 adds `seeds.yaml`** — the seeding
    map, a hand-authored tracked seed beside `seats.yaml`, hashed
    like every other one so that editing it between two ticks is a drift refusal rather than a
    silent adoption (`the build specification (not in this mirror)` § Deliverable 3, folded: S-15).

    **Present-at-call, never a fixed list.** A fresh checkout carries no store and no manifest,
    and a build-1 root carries no `seats.yaml` either; hashing an absent file would make every
    such root unrunnable. So an absent store hashes an empty set — and `seed_index()` below is
    what turns "a store appeared between two ticks" into a refusal rather than a silence.
    """
    brain = BrainPaths(root=root)
    found: list[str] = []
    if brain.seats.is_file():
        found.append(paths_module.SEATS_FILENAME)
    if brain.seeds.is_file():
        found.append(paths_module.SEEDS_FILENAME)  # build 3, and see `inventory_seed_files()`
    if brain.seats_dir.is_dir():
        # **Recursive from build A.1** (`the build specification (not in this mirror)` § Resolutions
        # D11-4): the glob was `seats/*.md`, which reached `director.md` and `manager.md` and
        # stopped at the directory boundary — so editing a call-type prefix mid-task was not a
        # drift refusal while editing a seat's was, for two files the loader reads the same way.
        # `seats/calls/*.md` joins the hashed set here, which also puts it under the inventory's
        # appearance detector: a prefix file appearing between two ticks changes what a think or
        # an escalate is framed by, exactly as a seat prefix does. The key is the brain-root
        # relative path rather than the file name, because the set is no longer flat.
        found.extend(
            entry.relative_to(root).as_posix()
            for entry in sorted(brain.seats_dir.rglob(f"*{paths_module.SEAT_PROMPT_SUFFIX}"))
            if entry.is_file()
        )
    if brain.intake_manifest.is_file():
        found.append(
            f"{paths_module.INTAKE_DIRNAME}/{paths_module.INTAKE_MANIFEST_FILENAME}"
        )
    if brain.semantic.is_dir():
        found.extend(
            f"{paths_module.SEMANTIC_DIRNAME}/{entry.name}"
            for entry in sorted(brain.semantic.glob(f"*{paths_module.SEMANTIC_SUFFIX}"))
            if entry.is_file()
        )
    return found


def inventory_seed_files(root: Path) -> list[str]:
    """The widened set the **appearance detector** covers — everything but `seeds.yaml`.

    `seed_index()` below turns "a seed file appeared between two ticks" into a refusal, and for
    a store or a seat prefix that is exactly right: the boundary loader reads them *at tick
    time*, so one appearing mid-task changes what a seat sees. **`seeds.yaml` has no tick-time
    reader at all** — `protean.sleep.weights.seeded_keys()` is its only one, and sleep refuses an
    occupied root before it reads anything (decision 16), as does the intake verb that writes
    against it (decision 14). A map appearing mid-task can therefore move no number this task
    runs on; the numbers themselves are the per-file `weights.yaml` hashes, which the ladder
    checks unchanged.

    So `seeds.yaml` is hashed like every other seed — an edit to it under a task that recorded
    it is a drift refusal by the per-file arm — and is kept out of the *inventory* digest, so a
    checkpoint written before build 3 authored the file still loads (ledger `D14-4`). This is
    build 2's own carve-out one build on: the index is written only when its set is non-empty,
    "which is what keeps a build-1 root's checkpoint exactly the twelve node-file keys it has
    always carried". A root with no `seeds.yaml` sees no behaviour change of any kind.
    """
    return [
        relative
        for relative in widened_seed_files(root)
        if relative != paths_module.SEEDS_FILENAME
    ]


def seed_index(relatives: Sequence[str]) -> str:
    """sha256 over the sorted *inventory* of widened seeds — the appearance detector.

    The per-file arm of the refusal ladder walks the keys a checkpoint recorded, so a seed file
    that did not exist at task start is invisible to it: nothing recorded it, so nothing
    compares it. This one key records the set itself, so a store appearing — or a prefix file
    vanishing — mid-task moves a hash the ladder does check (folded: S-11).

    It is written **only when the widened set is non-empty**, which is what keeps a build-1
    root's checkpoint exactly the twelve node-file keys it has always carried. Its subject is
    `inventory_seed_files()` rather than `widened_seed_files()` — the one seed with no tick-time
    reader is hashed per file and left out of this set; that function carries the reason.
    """
    joined = "\n".join(sorted(relatives))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def seed_hashes(root: Path) -> dict[str, str]:
    """`{relative path: sha256}` over every seed file a run loads.

    Build 1's twelve — six `NODE.md` and six `weights.yaml` — plus build 2's widened set and
    its inventory key, when that set is non-empty.
    """
    hashes: dict[str, str] = {}
    for node in config.NODE_ORDER:
        folder = config.node_dir(node, root)
        for filename in SEED_FILES:
            hashes[seed_relative_path(node, filename)] = file_sha256(folder / filename)
    for relative in widened_seed_files(root):
        hashes[relative] = file_sha256(root / relative)
    inventory = inventory_seed_files(root)
    if inventory:
        hashes[SEED_INDEX_KEY] = seed_index(inventory)
    return hashes


def seed_reader(root: Path):
    """The `seed_reader` callable `protean.state.checkpoint.load_checkpoint` takes.

    Passing `None` in its place is how `resume --reseed` disarms exactly that arm of the
    refusal ladder while every other arm stays armed (§ Deliverable 3).

    Two build-2 cases join the plain hash: the inventory key, which is recomputed rather than
    read, and a recorded seed that is **gone** — which returns a sentinel that can never equal
    a sha256, so a deleted seed refuses by name instead of raising `FileNotFoundError` out of
    the middle of the ladder.
    """

    def _read(relative: str) -> str:
        if relative == SEED_INDEX_KEY:
            return seed_index(inventory_seed_files(root))
        path = root / relative
        return file_sha256(path) if path.is_file() else SEED_ABSENT
    return _read


def changed_seed_files(root: Path, recorded: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    """`{relative path: (recorded, current)}` for every seed file that moved under a task.

    What `resume --reseed` prints before it re-hashes: "every changed seed file is printed,
    re-hashed into the checkpoint, `integrity` recomputed, and a `reseeded` event recorded".

    Build 2 adds the two edits the widened ladder made possible — a seed that **appeared**
    (recorded as `SEED_ABSENT`) and one that **vanished** (current `SEED_ABSENT`) — so
    `--reseed` prints an intake that ran between two ticks rather than silently adopting it.
    The inventory key is not printed: it is the detector, not an edit.
    """
    current = seed_hashes(root)
    changed = {
        path: (was, current[path])
        for path, was in recorded.items()
        if path != SEED_INDEX_KEY and path in current and current[path] != was
    }
    for path, was in recorded.items():
        if path != SEED_INDEX_KEY and path not in current:
            changed[path] = (was, SEED_ABSENT)
    for path, now in current.items():
        if path != SEED_INDEX_KEY and path not in recorded:
            changed[path] = (SEED_ABSENT, now)
    return changed


def read_procedures(directory: Path) -> list[tuple[str, Mapping[str, Any]]]:
    """Every `<procedure_id>.yaml` under one `procedures/` folder, as `(procedure_id, payload)`.

    `the build specification (not in this mirror)` § Deliverable 4. Build 1 left `procedures_path()` above as
    a stub — "build 3 compiles habits here; build 1 reads and writes nothing" — and this is the
    read half of that sentence, landing beside the widened seed ladder rather than in the
    runtime: reading a file under `brain/` is what this module is for.

    **Reading only, and never parsing.** The payload is handed on as the loaded mapping;
    `protean.cortex.habits` turns it into a `SeatScript` through `parse_script()`, which is the
    one loader P2 is defined against. Splitting it that way is what keeps the matcher pure and
    keeps this package from importing the seat layer.

    The `procedure_id` is the payload's own when it carries one — sleep writes it and
    `parse_script()` ignores it — and the file stem otherwise, so a hand-planted file is still
    orderable. An absent directory is the ordinary case (a root on which no sleep run has ever
    compiled) and reads as no procedures, never as a refusal.
    """
    if not directory.is_dir():
        return []
    found: list[tuple[str, Mapping[str, Any]]] = []
    for path in sorted(directory.glob(f"*{paths_module.PROCEDURE_SUFFIX}")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, Mapping):
            continue
        identifier = loaded.get("procedure_id")
        found.append(
            (str(identifier) if isinstance(identifier, str) and identifier else path.stem,
             dict(loaded))
        )
    return found


def procedure_set(root: Path, *, project: str) -> list[tuple[str, Mapping[str, Any]]]:
    """The compiled habits one task may match, in the order precedence reads them.

    The two halves of P2's cross-project split (folded: S-2): the cortex node folder's
    `procedures/`, which is tracked and holds cross-project evidence, and the task's own
    project's under its slug, which is gitignored. **Lexical by `procedure_id`, first match
    wins, at most one per tick** (ledger `D16-2`) — so the two halves are one sorted sequence
    rather than two consulted in turn, and the node folder breaks a tie on equal ids.
    """
    brain = BrainPaths(root=root)
    entries = [
        (identifier, order, payload)
        for order, directory in enumerate(
            (brain.node_procedures(config.CORTEX_NODE), brain.project_procedures(project))
        )
        for identifier, payload in read_procedures(directory)
    ]
    return [
        (identifier, payload)
        for identifier, _order, payload in sorted(entries, key=lambda item: item[:2])
    ]
