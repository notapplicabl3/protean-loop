"""The trace append path, where the prediction contract is enforced rather than assumed.

`the build specification (not in this mirror)` § Deliverable 4 → *The prediction is enforced at
trace-append, not by convention*: "`brain/`'s append path refuses a `prediction`-kind
`TraceRecord` with no `prediction`, and an `outcome`-kind record whose `ref` names no committed
prediction — **it raises and writes nothing**." § Deliverable 2 fixes the dedupe key
`(task, tick, node, tier, kind, source)`; § Deliverable 3 makes a key collision a silent no-op.

**Three outcomes, and they are three different things.**

* A record the contract forbids raises `TraceAppendRefused` and the file is byte-unchanged.
  Validation runs before the file is opened at all, so "unchanged" is a property of the control
  flow rather than of a rollback.
* A record whose dedupe key is already committed returns `None` and writes nothing — the
  surviving record is authoritative, which is what makes a replayed tick idempotent.
* Anything else is appended, and the appended `TraceRecord` is returned.

**The append accepts a raw mapping as well as a model, and that is the point.**
`TraceRecord`'s own validators already make a prediction-without-a-prediction unconstructible,
so a check that only accepted models would be checking something that cannot happen. Taking the
mapping means the *writer* is the enforcement point: a caller that hand-builds a malformed line
still cannot get it onto disk.

**Outcomes are appended records, never in-place edits.** Nothing in this module rewrites a
line; the only write is `protean.brain.jsonl.append_keyed`, which opens in append mode.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from protean.brain.jsonl import append_keyed, read_lines
from protean.state.enums import TraceKind, TraceSource
from protean.state.errors import TraceAppendRefused
from protean.state.records import FIRING_KEY_SUFFIX, TraceRecord

#: The tier component of a key on a folder that has no tiers — the five deterministic nodes.
NO_TIER = "-"


def _tier_of(payload: Mapping[str, Any]) -> str:
    tier = payload.get("tier")
    return NO_TIER if tier is None else str(tier)


def dedupe_key(payload: Mapping[str, Any]) -> Hashable:
    """`(task, tick, node, tier, kind, source)` — the same key `TraceRecord.dedupe_key()` names."""
    tier = payload.get("tier")
    return (
        str(payload.get("task")),
        int(payload.get("tick", -1)),
        str(payload.get("node")),
        None if tier is None else str(tier),
        str(payload.get("kind")),
        str(payload.get("source")),
    )


def prediction_key(payload: Mapping[str, Any]) -> str:
    """The key an outcome's `ref` names, computed off a raw record.

    **The second implementation of `TraceRecord.prediction_key()`, and it suffixes on the same
    condition** (§ Scaffold clause item 2, contract 3's fifth amendment, folded: S-A89): a
    firing prediction's key takes `:firing`, keyed on the record's `source == firing`, and every
    other key stays byte-identical. `committed_prediction_keys()` is built from this function
    and `append_trace()` refuses by name any outcome whose `ref` names no key in that set — so
    the suffix applied at the model alone would leave **every** firing grade `TraceAppendRefused`
    at write and the pair this amendment exists to make gradeable would never land.
    """
    suffix = (
        FIRING_KEY_SUFFIX
        if str(payload.get("source")) == TraceSource.FIRING.value
        else ""
    )
    return (
        f"{payload.get('task')}:{payload.get('tick')}:"
        f"{payload.get('node')}:{_tier_of(payload)}:prediction{suffix}"
    )


def committed_prediction_keys(path: Path) -> set[str]:
    """Every prediction key already on disk in this folder's `trace.jsonl`."""
    return {
        prediction_key(record)
        for record in read_lines(path)
        if str(record.get("kind")) == TraceKind.PREDICTION.value
    }


def committed_predictions(path: Path) -> list[TraceRecord]:
    """Every committed `prediction` record, parsed — what deferred grading scans."""
    return [
        TraceRecord.model_validate(record)
        for record in read_lines(path)
        if str(record.get("kind")) == TraceKind.PREDICTION.value
    ]


def graded_refs(path: Path) -> set[str]:
    """Every `ref` an `outcome` record in this folder has already claimed.

    A horizon prediction is graded once: the deferred grader skips a `ref` in this set rather
    than relying on the dedupe key, because a `operator_answer` outcome and a `runtime_grade`
    outcome at the same tick have *different* keys by design.
    """
    return {
        str(record["ref"])
        for record in read_lines(path)
        if str(record.get("kind")) == TraceKind.OUTCOME.value and record.get("ref")
    }


def _validated(record: TraceRecord | Mapping[str, Any]) -> tuple[TraceRecord, dict[str, Any]]:
    """The record as both a model and its wire payload, or `TraceAppendRefused`."""
    if isinstance(record, TraceRecord):
        return record, record.model_dump(mode="json")
    try:
        model = TraceRecord.model_validate(dict(record))
    except ValidationError as exc:
        raise TraceAppendRefused(_first_message(exc)) from exc
    return model, model.model_dump(mode="json")


def _first_message(exc: ValidationError) -> str:
    """The first validation message, so the refusal names what was wrong rather than the count."""
    errors = exc.errors()
    if not errors:  # pragma: no cover - pydantic always reports at least one
        return str(exc)
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "record"
    return f"{location}: {first.get('msg')}"


def append_trace(path: Path, record: TraceRecord | Mapping[str, Any]) -> TraceRecord | None:
    """Append one record to a node folder's `trace.jsonl`, enforcing the prediction contract.

    Raises `TraceAppendRefused` — writing nothing — for a `prediction` with no prediction and
    for an `outcome` whose `ref` names no committed prediction in this folder. Returns `None`
    when the dedupe key is already committed, and the record when it was written.
    """
    model, payload = _validated(record)

    if model.kind is TraceKind.OUTCOME:
        if model.ref not in committed_prediction_keys(path):
            raise TraceAppendRefused(
                f"outcome ref {model.ref!r} names no committed prediction in {path.name}"
            )

    written = append_keyed(path, payload, key_fn=dedupe_key)
    return None if written is None else model
