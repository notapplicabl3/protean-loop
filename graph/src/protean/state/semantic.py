"""`SemanticChunk` — seam contract S4, one JSON line per chunk of seeded source text.

`the build specification (not in this mirror)` § Deliverable 3 (seam contracts S3, S4), § Directional
decisions 5, 6, 15, 16, § Resolutions A1-10, S-12, S-13, S-14, S-20, S-22.

**The store is content, never structure** (decision 5). A chunk carries the *text* of a source
document and a lower-cased term set derived from it; it carries no path, no directory name and
no layout — `source` is the manifest's **logical** name (`docs`, `projects`, `feedback`,
`memory`) and `heading` is the document's own heading, not its location. That is what keeps
`brain/intake/manifest.yaml` and every tracked file free of a policy-home path while the
gitignored store holds the source text verbatim (folded: S-20).

**Every chunk is a seed and says so.** `seed` is `Literal[True]`, so a record that does not
carry `seed: true` cannot be constructed at all — build 3's sleep graph weakens a seeded prior
rather than inheriting it as settled fact, and it can only do that if the marking is a property
of the type instead of a habit of the writer. `manifest_revision` is the second half of the same
guarantee: two chunks with the same revision were produced by the same manifest over the same
source bytes and are comparable; a different revision means the manifest or a source moved
(folded: S-13).

**Ten fields, not nine.** S4's list is the nine content fields; `schema_version` sits beside
them the way it does on every other persisted artifact in the build, and the loader refuses a
version it does not write. The precedent is `protean.state.seat_calls.SeatCallRecord`, whose
docstring records the same reading of a seam contract's field list — a floor, not a ceiling —
and `protean.config.SEMANTIC_CHUNK_SCHEMA_VERSION` is the literal order W2 authored for it
(recorded in the dispatch ledger).

**A store is replaced wholesale, never appended to** (folded: S-14). Intake is idempotent by
construction: the same sources under the same manifest produce the same bytes, so a second run
leaves each file identical rather than doubling it. That is why `write_store()` lives here and
not behind `protean.brain.jsonl.append_keyed`, which is the *append-only* primitive the runtime's
artifacts share and offers no path that rewrites a file. The line encoding is still that
module's, so a store line is byte-stable for a given payload exactly as a trace line is.

**`terms_of()` lives here, beside the contract, rather than in the intake package.** A
deterministic node scores a chunk by term overlap with the live goal and unit text (§ Deliverable
3, *How a chunk reaches the seat*), so the tokenizer that produced `terms` has to be reachable
from `protean.nodes/` without importing the offline verb's package. The precedent is
`protean.state.seat_calls.spend_tokens()`: a pure function beside the contract whose field it
explains.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field

from protean import config
from protean.brain.jsonl import encode_line, read_lines
from protean.state.base import ProteanModel
from protean.state.errors import SchemaVersionMismatch

#: The artifact name a refusal quotes, so a captured `SchemaVersionMismatch` names the store.
ARTIFACT = "semantic_chunk"

#: `semantic:<sha256[:16]>` — the id convention § Deliverable 3 fixes, and the prefix that makes
#: the *kind* readable where `RetrievalSet.candidates` mixes chunks with episodes (S-2).
CHUNK_ID_PREFIX = "semantic:"
CHUNK_ID_DIGEST_CHARS = 16

#: Tokens are lower-cased runs of letters and digits. Anything shorter than three characters is
#: noise at this scale, and the closed stop list below is the only vocabulary judgment made here.
_TOKEN = re.compile(r"[a-z0-9]+")
_MIN_TOKEN_CHARS = 3

#: Words that appear in every document and therefore separate none of them. Deliberately tiny:
#: a long stop list is a retrieval tuning decision, and tuning lives on `weights` (S-25).
STOP_WORDS: frozenset[str] = frozenset(
    {
        "and", "are", "but", "for", "from", "has", "have", "into", "its", "not", "now",
        "one", "only", "over", "per", "que", "she", "than", "that", "the", "their",
        "them", "then", "there", "these", "they", "this", "those", "was", "were", "what",
        "when", "which", "who", "why", "will", "with", "you", "your",
    }
)


def chunk_id_of(text: str) -> str:
    """`semantic:<sha256[:16]>` of the chunk's text — the same text always the same id."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{CHUNK_ID_PREFIX}{digest[:CHUNK_ID_DIGEST_CHARS]}"


def terms_of(*parts: str) -> list[str]:
    """The lower-cased token set the lexical match runs over, sorted so a line is byte-stable.

    Sorted rather than in order of appearance because `terms` is a *set* in everything but its
    JSON type: the scorer intersects it, and a stable order is what makes two runs over the same
    bytes produce the same file.
    """
    found: set[str] = set()
    for part in parts:
        for token in _TOKEN.findall(part.lower()):
            if len(token) >= _MIN_TOKEN_CHARS and token not in STOP_WORDS:
                found.add(token)
    return sorted(found)


class SemanticChunk(ProteanModel):
    """One chunk of seeded source text, as the persisted line `brain/semantic/<store>.jsonl` holds."""

    schema_version: int
    #: `semantic:<sha256[:16]>` of `text`. Content-derived, so it is stable across runs and
    #: across machines, and two identical sections are one chunk rather than two.
    chunk_id: str
    #: The store file's stem — `docs`, `projects`, `feedback`, `memory`.
    store: str
    #: The manifest's **logical** source name. Never a path (decision 5).
    source: str
    #: The document's own heading, row label or `name`. Empty for a document that has none.
    heading: str = ""
    #: The source text, verbatim. The store is gitignored and licensed to hold it (S-20).
    text: str
    terms: list[str] = Field(default_factory=list)
    #: The `--project <slug>` this chunk entered under; `None` outside the `memory` store (S-12).
    project: str | None = None
    #: Not a default a writer may forget: `Literal[True]` makes an unseeded chunk unconstructable.
    seed: Literal[True] = True
    #: `sha256[:12]` over the manifest plus every source file the run read (S-13).
    manifest_revision: str

    @classmethod
    def of(
        cls,
        *,
        store: str,
        source: str,
        text: str,
        manifest_revision: str,
        heading: str = "",
        terms: Sequence[str] | None = None,
        project: str | None = None,
        schema_version: int | None = None,
    ) -> "SemanticChunk":
        """Compose a chunk, deriving `chunk_id` from `text` and `terms` from the text it scores on."""
        return cls(
            schema_version=(
                config.SEMANTIC_CHUNK_SCHEMA_VERSION if schema_version is None else schema_version
            ),
            chunk_id=chunk_id_of(text),
            store=store,
            source=source,
            heading=heading,
            text=text,
            terms=list(terms) if terms is not None else terms_of(heading, text),
            project=project,
            manifest_revision=manifest_revision,
        )


def write_store(path: Path, chunks: Iterable[SemanticChunk]) -> int:
    """Replace one store file wholesale with these chunks, and return the line count (S-14).

    Wholesale, because a second intake over unchanged sources must leave the file *byte*
    identical rather than merely equivalent — which is what makes "did a seed move between two
    ticks" answerable by the seed-hash ladder instead of by a diff.
    """
    lines = [encode_line(chunk.model_dump(mode="json")) for chunk in chunks]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Temp-then-replace, as the checkpoint lands (`protean.runtime.commit`): a writer killed
    # mid-store leaves the previous store whole rather than a truncated file that every later
    # tick's `load_stores` would refuse (audit 2026-09-19, D3).
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text("".join(lines), encoding="utf-8")
    temp.replace(path)
    return len(lines)


def load_store(path: Path) -> list[SemanticChunk]:
    """Every chunk in one store file, refusing a `schema_version` this code does not write.

    Build 2 ships no migration path, here as everywhere: a version this loader does not
    recognise is a stop, and `SchemaVersionMismatch` already quotes both numbers.
    """
    chunks: list[SemanticChunk] = []
    for line in read_lines(path):
        found = int(line.get("schema_version", -1))
        if found != config.SEMANTIC_CHUNK_SCHEMA_VERSION:
            raise SchemaVersionMismatch(
                artifact=ARTIFACT,
                found=found,
                expected=config.SEMANTIC_CHUNK_SCHEMA_VERSION,
            )
        chunks.append(SemanticChunk.model_validate(line))
    return chunks


def load_stores(paths: Iterable[Path]) -> list[SemanticChunk]:
    """Every chunk in the store files a caller enumerated, in the order it gave them.

    The caller passes the paths rather than a directory because `brain/semantic/` is derived in
    `protean.runtime.paths`, and a persisted contract may not depend on the runtime — the same
    layering `protean.state.seat_calls` keeps behind its `TYPE_CHECKING` guard.
    """
    chunks: list[SemanticChunk] = []
    for store in paths:
        chunks.extend(load_store(store))
    return chunks
