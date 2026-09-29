"""The checkpoint envelope, the one canonicalization, and the refusal ladder.

`the build specification (not in this mirror)` § Deliverable 2 — the envelope table, the canonicalization
recipe, and "Versioning is a refusal, not a migration"; § Deliverable 3's administrative
`revision`; decision 11.

**The checkpoint is a typed envelope, not a dump of `BrainState`.** Its `schema_version` is
the *envelope's*, distinct from the state's, so the two can be refused independently — which
is what makes the ladder's first two rungs different rungs.

**One function computes and verifies `integrity`** — `canonical_body()` — so there is no
second implementation to drift. The recipe is fixed: `model_dump(mode="json")`, delete the
`integrity` key, `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`,
UTF-8, sha256, hex.

**The ladder runs in order and stops at the first failure**, quoting both sides: envelope
version → `BrainState.schema_version` → every extension's version → the integrity hash → each
`seed_hashes` entry against the file on disk.

**This module performs no file IO.** The `seed_hashes` arm takes a `seed_reader` callable —
relative path → sha256 — supplied by the runtime's brain-folder layer. Passing `None` is how
`resume --reseed` disarms exactly that arm while the version arms and the integrity arm over
the stored body stay armed (§ Deliverable 3); it is a parameter rather than a flag inside the
ladder so that the disarm is visible at the call site.
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable, Mapping

from pydantic import Field

from protean import config
from protean.state.base import ProteanModel
from protean.state.brain_state import BrainState
from protean.state.errors import (
    ExtensionVersionMismatch,
    IntegrityMismatch,
    SchemaVersionMismatch,
    SeedHashMismatch,
)

#: The key excluded from its own hash.
INTEGRITY_FIELD = "integrity"


class Checkpoint(ProteanModel):
    """Runtime → `checkpoint.json` at every boundary, written temp-then-renamed.

    Its presence is the definition of "tick completed" — no marker file, no sixth artifact.
    `revision` exists from v1 and is incremented only by an administrative commit
    (`--abandon` · `--reseed` · `--extend`), which recomputes `integrity` and appends its
    `event` record while no node runs.
    """

    schema_version: int = config.CHECKPOINT_SCHEMA_VERSION
    revision: int = 0
    state: BrainState
    extensions: dict[str, int] = Field(default_factory=dict)
    seed_hashes: dict[str, str] = Field(default_factory=dict)
    integrity: str = ""


def canonical_body(payload: Mapping[str, object]) -> str:
    """The canonicalized envelope body, with `integrity` excluded. The one recipe."""
    body = {key: value for key, value in payload.items() if key != INTEGRITY_FIELD}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_integrity(checkpoint: Checkpoint | Mapping[str, object]) -> str:
    """sha256 over `canonical_body`, hex. Computes and verifies through the same path."""
    payload = (
        checkpoint.model_dump(mode="json")
        if isinstance(checkpoint, Checkpoint)
        else dict(checkpoint)
    )
    return hashlib.sha256(canonical_body(payload).encode("utf-8")).hexdigest()


def sealed(checkpoint: Checkpoint) -> Checkpoint:
    """The same envelope with `integrity` filled in. What the boundary commit writes."""
    return checkpoint.model_copy(update={INTEGRITY_FIELD: compute_integrity(checkpoint)})


def verify_integrity(payload: Mapping[str, object]) -> None:
    """Raise `IntegrityMismatch` quoting both hashes if the body was edited."""
    recorded = str(payload.get(INTEGRITY_FIELD, ""))
    recomputed = compute_integrity(payload)
    if recorded != recomputed:
        raise IntegrityMismatch(found=recorded, expected=recomputed)


def load_checkpoint(
    payload: Mapping[str, object],
    *,
    extension_versions: Mapping[str, int] | None = None,
    seed_reader: Callable[[str], str] | None = None,
) -> Checkpoint:
    """The refusal ladder, in order, first failure raising and quoting both sides.

    `extension_versions` is what the running code registers; `seed_reader` returns the current
    sha256 of a seed file by its checkpoint-relative path, or is `None` to disarm that arm for
    `resume --reseed`. Build 1 ships no migration path, so every arm is a refusal.
    """
    envelope_version = int(payload.get("schema_version", -1))
    if envelope_version != config.CHECKPOINT_SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            artifact="checkpoint",
            found=envelope_version,
            expected=config.CHECKPOINT_SCHEMA_VERSION,
        )

    raw_state = payload.get("state")
    state_version = (
        int(raw_state.get("schema_version", -1)) if isinstance(raw_state, Mapping) else -1
    )
    if state_version != config.BRAIN_STATE_SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            artifact="BrainState",
            found=state_version,
            expected=config.BRAIN_STATE_SCHEMA_VERSION,
        )

    registered = dict(extension_versions or {})
    manifest = payload.get("extensions") or {}
    if isinstance(manifest, Mapping):
        for name, version in manifest.items():
            expected = registered.get(str(name))
            if expected is None or int(version) != int(expected):
                raise ExtensionVersionMismatch(
                    extension=str(name),
                    found=int(version),
                    expected=int(expected) if expected is not None else -1,
                )

    verify_integrity(payload)

    if seed_reader is not None:
        hashes = payload.get("seed_hashes") or {}
        if isinstance(hashes, Mapping):
            for path, recorded in sorted(hashes.items()):
                current = seed_reader(str(path))
                if current != str(recorded):
                    raise SeedHashMismatch(
                        path=str(path), found=current, expected=str(recorded)
                    )

    return Checkpoint.model_validate(payload)
