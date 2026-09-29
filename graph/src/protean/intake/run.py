"""The fifth verb's body: refuse an occupied root, read the sources, replace the stores.

`the build specification (not in this mirror)` § Deliverable 3, § Directional decisions 14, § Resolutions
A1-13, S-12, S-13, S-14, S-28.

**Refused while a task occupies the root** (decision 14). Intake writes seed files and the
runtime may never write one, so the two are refused apart rather than serialized: the refusal is
build 1's own `RootOccupied` — reused, not reinvented — and it exits on
`config.EXIT_INTAKE_REFUSED`, the code order W2 authored for exactly this.

**The revision is computed before the first chunk exists** (folded: S-13). `manifest_revision` is
`sha256[:12]` over the manifest bytes plus the sorted `(logical path, sha256)` of every source
file the run read, so every chunk of one run carries the same number and two chunks that carry it
were produced from the same bytes. That forces the two-pass shape here: read everything, hash,
then cut.

**Each store is replaced wholesale** (folded: S-14), which is what makes a second intake
byte-identical rather than doubled — and **wholesale replacement is a fact about stores, never
about a weights key.** Build 3 is where S-28 comes in
(`the build specification (not in this mirror)` § Deliverable 3): the verb now also opens the five writable
`brain/nodes/*/weights.yaml` files, re-values only the keys `brain/seeds.yaml` names, and only
while the on-disk value still equals the seeding row's — a key sleep has moved is skipped and
printed, because sleep is the sole *re*writer and intake is a seeder between tasks (folded:
S-10, S-15, S-21). The whole map is resolved *before* the first store is replaced, so a map this
build refuses costs nothing; `protean.intake.seeds` holds the rule and its refusals.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from protean.intake import policy_home
from protean.intake.chunks import cut
from protean.intake.manifest import IntakeManifest, ManifestSource, load_manifest
from protean.intake.seeds import SeedWrite, load_seed_map, plan_seeds
from protean.runtime.engine import occupied_task
from protean.runtime.errors import RootOccupied
from protean.runtime.paths import BrainPaths
from protean.state.semantic import SemanticChunk, terms_of, write_store

#: `sha256[:12]`, the width § Deliverable 3 fixes for a manifest revision.
REVISION_DIGEST_CHARS = 12


@dataclass(frozen=True, slots=True)
class StoreWrite:
    """One store file as written: where it landed, from which source, and how many lines."""

    source: str
    store: str
    path: Path
    chunks: int


@dataclass(frozen=True, slots=True)
class IntakeOutcome:
    """What one `protean intake` did, in the shape the CLI prints and a test asserts against."""

    manifest_revision: str
    project: str | None
    #: The logical paths read, sorted — the set `manifest_revision` was computed over, and the
    #: set a test asserts holds no skill and no registry.
    sources_read: tuple[str, ...]
    writes: tuple[StoreWrite, ...] = field(default_factory=tuple)
    #: One row per line of `brain/seeds.yaml`, applied or skipped, with both numbers (S-28).
    seeds: tuple[SeedWrite, ...] = field(default_factory=tuple)
    #: The `weights.yaml` files the seeding phase actually rewrote — usually none, because a
    #: row is applied only while the file already holds its value.
    seed_files: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def files(self) -> tuple[Path, ...]:
        """Every file this run wrote — the stores, plus any weights file the map re-valued."""
        return tuple(write.path for write in self.writes) + self.seed_files

    def messages(self) -> list[str]:
        """The lines the verb prints — one per file written, and nothing it did not write.

        A seeding row prints its own decision line, which never begins `wrote `: two rows may
        re-value two keys of one file, and the `wrote ` prefix stays one line per file.
        """
        lines = [
            f"intake: manifest revision {self.manifest_revision}",
            f"intake: read {len(self.sources_read)} source file(s)"
            + (f" for project {self.project!r}" if self.project else ""),
        ]
        lines.extend(
            f"wrote {write.path} — {write.chunks} chunk(s) from source {write.source!r}"
            for write in self.writes
        )
        lines.extend(seeded.message() for seeded in self.seeds)
        lines.extend(
            f"wrote {path} — re-valued "
            f"{sum(1 for seeded in self.seeds if seeded.changed and seeded.path == path)} "
            f"seeded key(s)"
            for path in self.seed_files
        )
        return lines


def manifest_revision(manifest_bytes: bytes, reads: Sequence[tuple[str, bytes]]) -> str:
    """`sha256[:12]` over the manifest plus the sorted `(logical path, sha256)` of each source."""
    digest = hashlib.sha256()
    digest.update(hashlib.sha256(manifest_bytes).hexdigest().encode("utf-8"))
    for logical, payload in sorted(reads):
        digest.update(logical.encode("utf-8"))
        digest.update(hashlib.sha256(payload).hexdigest().encode("utf-8"))
    return digest.hexdigest()[:REVISION_DIGEST_CHARS]


def _chunks_for(
    row: ManifestSource,
    documents: Sequence[tuple[str, str]],
    *,
    revision: str,
    project: str | None,
) -> list[SemanticChunk]:
    """Every chunk one manifest row produces, deduplicated by `chunk_id` in reading order."""
    seen: set[str] = set()
    chunks: list[SemanticChunk] = []
    for _logical, text in documents:
        for piece in cut(row.shape, text):
            chunk = SemanticChunk.of(
                store=row.store,
                source=row.source,
                heading=piece.heading,
                text=piece.text,
                terms=terms_of(piece.heading, piece.extra, piece.text),
                project=project if row.project_scoped else None,
                manifest_revision=revision,
            )
            if chunk.chunk_id in seen:
                continue
            seen.add(chunk.chunk_id)
            chunks.append(chunk)
    return chunks


def run_intake(
    brain: BrainPaths,
    *,
    project: str | None = None,
    source_root: Path | None = None,
) -> IntakeOutcome:
    """Seed `brain/semantic/` from the manifest's sources. Refuses an occupied root.

    Raises `RootOccupied` before reading anything, `SchemaVersionMismatch` on a manifest this
    build does not write, `policy_home.BadProjectSlug` on a `--project` value that is not a slug, and
    `seeds.BadSeedMap` on a seeding map whose rows this build cannot read — the last of these
    before a single store is replaced.
    """
    occupied = occupied_task(brain)
    if occupied is not None:
        raise RootOccupied(
            task_id=occupied[0],
            terminal=None if occupied[1] is None else str(occupied[1]),
        )
    if project is not None:
        policy_home.check_slug(project)

    manifest_path = brain.intake_manifest
    manifest: IntakeManifest = load_manifest(manifest_path)

    # Resolved before the first store is replaced: every refusal the map can raise — an
    # unreadable row, a node that is not writable, a key the node's file does not carry —
    # fires here, while the run has written nothing at all (folded: S-28).
    plan = plan_seeds(brain, load_seed_map(brain.seeds))

    resolved: dict[str, list[tuple[str, str]]] = {}
    reads: list[tuple[str, bytes]] = []
    for row in manifest.sources:
        documents: list[tuple[str, str]] = []
        for logical, path in policy_home.source_files(
            row.source, project=project, override=source_root
        ):
            payload = path.read_bytes()
            reads.append((logical, payload))
            documents.append((logical, payload.decode("utf-8")))
        resolved[row.source] = documents

    revision = manifest_revision(manifest_path.read_bytes(), reads)

    writes: list[StoreWrite] = []
    for row in manifest.sources:
        chunks = _chunks_for(
            row, resolved[row.source], revision=revision, project=project
        )
        path = brain.semantic_store(row.store)
        written = write_store(path, chunks)
        writes.append(
            StoreWrite(source=row.source, store=row.store, path=path, chunks=written)
        )

    return IntakeOutcome(
        manifest_revision=revision,
        project=project,
        sources_read=tuple(sorted(logical for logical, _ in reads)),
        writes=tuple(writes),
        seeds=plan.writes,
        seed_files=plan.commit(),
    )


__all__ = ["IntakeOutcome", "StoreWrite", "manifest_revision", "run_intake"]
