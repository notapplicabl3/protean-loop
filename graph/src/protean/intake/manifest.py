"""`IntakeManifest` — seam contract S3, the tracked map from a logical source to its store.

`the build specification (not in this mirror)` § Deliverable 3's S3 table and its granularity rule
(folded: S-22).

**It names no path.** A row names a *logical* source — `docs`, `projects`, `feedback`,
`memory` — and `protean.intake.policy_home` is the one module that turns that name into files. That
split is the whole reason M24's grep stays true over the `brain/` tree with the manifest tracked
in it (folded: A1-11).

**Shape and granularity are two facts, not one.** `shape` is what the document looks like — a
markdown file with headings, a registry of bold-line rows, a document behind YAML frontmatter —
and `granularity` is how much of it becomes one chunk. They coincide today (a `markdown_sections`
document is cut per `heading`), and they are declared apart because S-22 settles the granularity
*per source*: a heading-less file is one chunk, and no feedback memory has a heading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from protean import config
from protean.state.base import ProteanModel
from protean.state.errors import SchemaVersionMismatch

#: The artifact name a refusal quotes.
ARTIFACT = "intake_manifest"

#: What a source document looks like. Closed: a shape the chunker cannot cut is a refused
#: manifest rather than a silently empty store.
Shape = Literal["markdown_sections", "registry_rows", "frontmatter_document"]

#: How much of a document becomes one chunk (folded: S-22).
Granularity = Literal["heading", "row", "file"]


class ManifestSource(ProteanModel):
    """One row of S3's table."""

    #: The logical source name. Never a path — that is `policy_home.py`'s only job.
    source: str
    #: The store file's stem under `brain/semantic/`.
    store: str
    shape: Shape
    granularity: Granularity
    #: `True` for a source whose files are selected by `protean intake --project <slug>`; with
    #: no slug the source contributes nothing and its store is written empty (folded: S-12).
    project_scoped: bool = False


class IntakeManifest(ProteanModel):
    """The whole of `brain/intake/manifest.yaml`: a version and one row per logical source."""

    schema_version: int
    sources: list[ManifestSource] = Field(default_factory=list)

    def store_names(self) -> list[str]:
        """Every store this manifest writes, in declaration order."""
        return [row.store for row in self.sources]


def load_manifest(path: Path) -> IntakeManifest:
    """Read the tracked manifest, refusing a `schema_version` this code does not write."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    found = int(payload.get("schema_version", -1))
    if found != config.INTAKE_MANIFEST_SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            artifact=ARTIFACT,
            found=found,
            expected=config.INTAKE_MANIFEST_SCHEMA_VERSION,
        )
    return IntakeManifest.model_validate(payload)
