"""The two model bases: one that forbids extras, one that tolerates them.

`the build specification (not in this mirror)` § Deliverable 2: "Every model sets `extra="forbid"`, with
exactly one exception, `SeatEnvelope`."

The exception is expressed here, once, rather than as a `model_config` repeated on sixty
classes — so "which models tolerate an unknown field" is answerable by reading the class
statement of each model, and `tests/state/test_conformance.py` can assert the asymmetry over
the whole exported roster instead of over a hand-kept list.

`ExtraTolerantModel` **preserves** what it accepts: pydantic stores unmatched keys in
`model_extra` and round-trips them through `model_dump()`, which is the property build 2
needs — it captures a real seat envelope from the live CLI and *diffs* it against
`SeatEnvelope`, and a
model that dropped the unexpected field would silently pass the diff it exists to fail.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProteanModel(BaseModel):
    """Every contract in the build except one. An unknown field is a validation error."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExtraTolerantModel(BaseModel):
    """The single extra-tolerant base. `SeatEnvelope` is its only subclass in build 1."""

    model_config = ConfigDict(extra="allow", validate_assignment=True)
