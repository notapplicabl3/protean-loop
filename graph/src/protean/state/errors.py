"""The named refusals. Versioning is a refusal, not a migration.

`the build specification (not in this mirror)` § Deliverable 2 → *Versioning is a refusal*: "the first
failure raises a named error quoting both sides and exits non-zero. Build 1 ships no
migration path."

Every error below quotes **both sides** in its message — what the artifact carries and what
the running code demands — because the DoD row that closes on it (M2) reads the captured
error text for both numbers. A refusal that printed only "version mismatch" would pass the
raise and fail the row.

The exit code each maps to lives in `protean.config`, never here: this module is importable
by anything, and a contract module that knew about process exit codes would put the operator
surface inside the state layer.
"""

from __future__ import annotations


class ProteanError(Exception):
    """Base of every refusal this package raises."""


class RefusalError(ProteanError):
    """The resume ladder's base: an artifact the running code declines to load."""


class SchemaVersionMismatch(RefusalError):
    """A persisted artifact whose `schema_version` is not the one the code writes."""

    def __init__(self, artifact: str, found: int, expected: int) -> None:
        self.artifact = artifact
        self.found = found
        self.expected = expected
        super().__init__(
            f"{artifact}: schema_version {found} on disk, {expected} in the running code — "
            f"build 1 refuses rather than migrating"
        )


class ExtensionVersionMismatch(RefusalError):
    """A registered extension whose version differs from the one the code registers."""

    def __init__(self, extension: str, found: int, expected: int) -> None:
        self.extension = extension
        self.found = found
        self.expected = expected
        super().__init__(
            f"extension {extension!r}: version {found} on disk, {expected} in the running "
            f"code — build 1 refuses rather than migrating"
        )


class IntegrityMismatch(RefusalError):
    """The checkpoint's `integrity` hash does not match its canonicalized body."""

    def __init__(self, found: str, expected: str) -> None:
        self.found = found
        self.expected = expected
        super().__init__(
            f"checkpoint integrity: {found} recorded, {expected} recomputed over the "
            f"canonicalized body — the checkpoint was edited outside the runtime"
        )


class SeedHashMismatch(RefusalError):
    """A `NODE.md` or `weights.yaml` changed under a suspended task."""

    def __init__(self, path: str, found: str, expected: str) -> None:
        self.path = path
        self.found = found
        self.expected = expected
        super().__init__(
            f"seed file {path}: sha256 {found} on disk, {expected} hashed into the "
            f"checkpoint — retune with `resume --reseed`, never a silent edit"
        )


class ReadsDrift(RefusalError):
    """A `NODE.md` `## Reads` list that no longer names exactly its input model's fields."""

    def __init__(self, node: str, missing: tuple[str, ...], extra: tuple[str, ...]) -> None:
        self.node = node
        self.missing = missing
        self.extra = extra
        super().__init__(
            f"{node}/NODE.md `## Reads` has drifted from its input model — "
            f"missing {list(missing)}, unexpected {list(extra)}"
        )


class CallsDrift(RefusalError):
    """A trigger key the call policy cannot plan from: out of its domain, or on with no question.

    `the build specification (not in this mirror)` § Deliverable 1 → *The payload*: an authored node whose
    trigger key is **on** and whose `NODE.md` `## Calls` lacks the line for a type its rule can
    plan is refused before the task's first tick, and so is a key that is neither off (`null` or
    absent) nor a positive number. It sits beside `ReadsDrift` because it is the same kind of fact
    — a seed the running code declines to start on — and shares its exit code.
    """

    def __init__(
        self,
        node: str,
        *,
        missing: tuple[str, ...] = (),
        key: str | None = None,
        value: object = None,
    ) -> None:
        self.node = node
        self.missing = missing
        self.key = key
        self.value = value
        if key is not None:
            detail = (
                f"{node}/weights.yaml `{key}` is {value!r} on disk; the call policy reads a "
                f"trigger key as off (`null` or absent) or a positive int or float, never a bool, "
                f"a string, zero or a negative"
            )
        else:
            detail = (
                f"{node}/NODE.md `## Calls` has no line for {list(missing)}, while its trigger key "
                f"is on and the call policy reads the question from that line"
            )
        super().__init__(f"{type(self).__name__}: {detail}")


class TraceAppendRefused(ProteanError):
    """A trace append that would break the prediction contract. Nothing is written."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"trace append refused, file unchanged: {reason}")


class InterruptUnanswered(ProteanError):
    """A resume over an open mailbox item with no `## Answer` body. Silence is not assent."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(
            f"open interrupt {path} has no `## Answer` body — answer it and resume; "
            f"silence is never assent"
        )
