"""`WorkloadRunReport` — the run's receipt, and the artifact the operator reads at B14 and B18.

`the build specification (not in this mirror)` § Deliverable 6 → *S6 — `WorkloadRunReport`*, § Rulings 6 and 16,
§ Named assumptions 2, and § DoD row W8.

**A builder's default, not a seam contract** (folded: S-27). S1–S5 are the seam contracts; this
one's only consumer is the operator at review, so its group list, its module and its format all move on a
one-line builder's-ledger note. Two things do **not** move, because the DoD row names them rather
than the SPEC's table: every number is *derived* from `seat_calls.jsonl`, the six `trace.jsonl`
files or the tree — none is a literal anywhere in the build — and the archive that carries this
file lands on **every** terminal (folded: S-35).

**Five groups and one count.** § Deliverable 6's table names five groups — detector telemetry,
seat economics, mismatch, versions, files — and § Named assumptions 2 asks for a sixth number
beside them: "on the first live tick, count the predicates the evaluator cannot grade, and
report the count in `WorkloadRunReport`". That count is `ungradeable_predicates`, and it is the
sixth thing row W8 reads back.

**And one list of request bytes** (`the build specification (not in this mirror)` § Deliverable 4):
`seat_requests`, one `SeatRequestBytes` row per journalled seat call, derived from the per-tick
journals like the groups above and defaulting empty, so a report written before build A.3 still
loads and `WORKLOAD_RUN_REPORT_SCHEMA_VERSION` does not move.

**Nothing here computes.** Every model below is a container: `protean.runtime.report` derives
the numbers from the artifacts on disk and fills them in. The one exception is
`DetectorTelemetry.over_firing`, which is a *reading* of two fields already on the row rather
than a measurement of its own — § Rulings 6's sentence, made a predicate so the operator does not have
to do the subtraction themselves.

**Not exported through `protean.state`'s roster**, following its build-2 siblings `oracle.py`,
`semantic.py` and `seat_calls.py` (folded: D8-2): the roster is build 1's inter-node contract
set, and a run receipt is a measurement artifact rather than a contract between two nodes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from pydantic import Field

from protean.state.base import ProteanModel
from protean.state.enums import Addressee, CallType, TerminalState, Tier, TrapDetector
from protean.state.errors import SchemaVersionMismatch

#: The artifact name a refusal quotes, so a captured `SchemaVersionMismatch` names the file.
ARTIFACT: Final[str] = "workload_run_report"


class DetectorTelemetry(ProteanModel):
    """One detector's row: how often it fired, how often the manager dismissed it, what held.

    § Rulings 6 is the operator's over-firing constraint made a number: *"make sure this isn't
    over-firing, we don't want metaphorical 'over thinking' when we haven't actually reached a
    stuck state yet."* § Deliverable 6 states the test — "a detector whose dismissals outnumber
    its confirmations is over-firing" — so the subtraction is carried here rather than left for
    the reader.
    """

    detector: TrapDetector
    #: Fired scalars on this detector, counted once per `(unit, tick)` (`TrapScalar.fired`).
    fires: int = 0
    #: `ManagerPlan.trap_dismissed` entries naming this detector, off the cortex trace.
    dismissals: int = 0
    #: The fires the manager did **not** dismiss. Never negative: a dismissal with no fire
    #: behind it is a manager dismissing a detector that had already been reset.
    confirmations: int = 0

    @property
    def over_firing(self) -> bool:
        """§ Deliverable 6's own test, as a predicate rather than as arithmetic in a reader."""
        return self.dismissals > self.confirmations


class SeatEconomics(ProteanModel):
    """One tier's economics. "The planner choice is measured, not tasted" (`DIGEST:118`).

    `tokens` is **spend** as `protean.state.seat_calls.spend_tokens()` defines it (folded:
    S-19) — the per-iteration sum of input + cache-creation + output — and the cache receipt is
    reported beside it as a ratio rather than added to it.

    `cost_usd` is the sum of the CLI's own `costUSD` over every `model_usage` entry on every
    record of the tier. It is an estimate the *binary* made, never a rate this build holds: a
    price literal here would be the one hardcoded number § Deliverable 6 forbids.
    """

    tier: Addressee
    calls: int = 0
    tokens: int = 0
    cache_read_tokens: int = 0
    #: `cache_read_tokens / (cache_read_tokens + tokens)`, `0.0` when the tier made no call.
    cache_read_ratio: float = 0.0
    wall_seconds: float = 0.0
    cost_usd: float = 0.0


class TierMismatch(ProteanModel):
    """One tier's failure surface: how often the monitor disagreed, and how often the seat did.

    `mismatch_rate` is over the ticks this tier was *called on*: a tier that made no call in a
    tick cannot be charged with that tick's mismatch. `graded_ticks` carries the denominator, so
    a rate of `0.0` on a tier that never ran is readable as such rather than as a clean sheet.
    """

    tier: Addressee
    #: Ticks in which this tier made at least one call **and** the monitor reached a verdict.
    graded_ticks: int = 0
    #: Of those, the ticks whose `MonitorVerdict.match` was false.
    mismatch_ticks: int = 0
    mismatch_rate: float = 0.0
    #: `SeatCallRecord.outcome == "decode_retry"`.
    decode_retries: int = 0
    #: `SeatCallRecord.outcome == "unavailable"` — decision 11's refusals.
    seat_unavailable: int = 0
    #: The S-43 fallback: a rejected `--resume` re-run as a fresh `--session-id` on the same
    #: uuid, marked on the record's `error`. Not one of § Deliverable 6's named numbers; it
    #: rides here because it is the one seat event that leaves no other trace.
    resumed_as_new: int = 0


class VersionSpread(ProteanModel):
    """Decision 13's mitigation, made visible: every `cli_version` the run resolved.

    § Rulings 16 buys the unpinned binary with exactly this — "the resolved version on every
    `SeatCallRecord`, every distinct version enumerated in `WorkloadRunReport`, and a mid-run change
    recorded as an `event` episode".
    """

    #: Distinct non-empty versions, in the order the run first saw them.
    versions: list[str] = Field(default_factory=list)
    changed_mid_run: bool = False


class FileChange(ProteanModel):
    """One file the run created or changed in the clone, with git's own status letters.

    "The exporter-manifest duty the operator discharges at review" — so the path is the clone-relative
    one and the status is what git said, unedited.
    """

    path: str
    status: str


class SeatRequestBytes(ProteanModel):
    """One journalled seat call's request, measured: how many bytes the seat was sent.

    `the build specification (not in this mirror)` § Deliverable 4. One row per cortex call entry in the
    per-tick journals addressed `director` or `manager`, answered or refused alike.
    `request_bytes` is the UTF-8 length of the entry's journalled `payload` serialized as the port
    serializes it — the byte count the seat's stdin carried on its **first** invocation: a decode
    retry's appended text is not counted, and a replayed tick's surviving entry is (§ Named
    assumptions 14).
    """

    tick: int
    tier: Tier
    #: `len(request_on_stdin(entry.payload).encode("utf-8"))`, with the port's serializer
    #: restated in `protean.runtime.report` and pinned equal to it by a test.
    request_bytes: int = 0


class WorkloadRunReport(ProteanModel):
    """The run's receipt: five groups and § Named assumptions 2's count."""

    schema_version: int
    task: str
    #: The committed terminal this report was written at. `None` only on a report built for a
    #: task whose checkpoint carries none, which the driver never does.
    terminal: TerminalState | None = None
    #: Ticks with a journal file — the run's length as the tree records it.
    ticks: int = 0
    detectors: list[DetectorTelemetry] = Field(default_factory=list)
    seats: list[SeatEconomics] = Field(default_factory=list)
    mismatch: list[TierMismatch] = Field(default_factory=list)
    versions: VersionSpread = Field(default_factory=VersionSpread)
    files: list[FileChange] = Field(default_factory=list)
    #: One row per journalled seat call, in tick order — derived from the journals each time the
    #: report is built and never stored anywhere else (A.3 § Deliverable 4). Defaults empty, so a
    #: report written before the field existed still loads.
    seat_requests: list[SeatRequestBytes] = Field(default_factory=list)
    #: § Named assumptions 2: the predicates the monitor's evaluator could not grade — graded
    #: from missing evidence rather than from evidence. A count, never a threshold.
    ungradeable_predicates: int = 0
    #: What the run could not measure, in the run's own words. Empty on a run with a live git
    #: workspace and a full set of artifacts.
    notes: list[str] = Field(default_factory=list)

    def detector(self, name: TrapDetector | str) -> DetectorTelemetry | None:
        wanted = TrapDetector(name)
        return next((row for row in self.detectors if row.detector is wanted), None)

    def seat(self, tier: Addressee | str) -> SeatEconomics | None:
        # Rows are addressee-keyed under build A.1 (S1/S2 per-addressee): a call type's row is
        # as legal as a tier's, and `protean.state` stays free of a runtime import.
        wanted = next((a for a in (*Tier, *CallType) if str(a) == str(tier)), None)
        return next((row for row in self.seats if row.tier is wanted), None)

    def tier_mismatch(self, tier: Addressee | str) -> TierMismatch | None:
        wanted = next((a for a in (*Tier, *CallType) if str(a) == str(tier)), None)
        return next((row for row in self.mismatch if row.tier is wanted), None)

    def over_firing(self) -> tuple[TrapDetector, ...]:
        """The detectors § Rulings 6's test names. The operator's row B14 reads this."""
        return tuple(row.detector for row in self.detectors if row.over_firing)

    def render(self) -> str:
        """One screen of the run, for the operator surface and for a captured receipt."""
        lines = [
            f"task      {self.task}",
            f"terminal  {self.terminal if self.terminal is not None else '-'}",
            f"ticks     {self.ticks}",
            f"calls     {sum(row.calls for row in self.seats)} "
            f"({sum(row.tokens for row in self.seats)} tokens, "
            f"${sum(row.cost_usd for row in self.seats):.4f})",
            f"versions  {', '.join(self.versions.versions) or '-'}"
            f"{' (changed mid-run)' if self.versions.changed_mid_run else ''}",
            f"overfire  {', '.join(str(one) for one in self.over_firing()) or '-'}",
            f"ungraded  {self.ungradeable_predicates} predicate(s)",
            f"files     {len(self.files)} changed in the clone",
            # The largest request any seat call was sent, or `-` on a run that made none.
            (
                "request   -"
                if (top := max(self.seat_requests, key=lambda row: row.request_bytes, default=None))
                is None
                else f"request   {top.request_bytes} bytes, {top.tier} at tick {top.tick} (largest)"
            ),
        ]
        return "\n".join(lines)


def detector_rows(
    fires: Iterable[tuple[TrapDetector, int]], dismissals: Iterable[tuple[TrapDetector, int]]
) -> list[DetectorTelemetry]:
    """Assemble one row per detector from two counted mappings, in `TrapDetector`'s own order.

    The subtraction lives here so the one place that defines "confirmation" is the contract's
    own module: a fire the manager did not dismiss. It is floored at zero rather than allowed
    negative, because a dismissal can name a detector whose window was already clear.
    """
    fired = dict(fires)
    dismissed = dict(dismissals)
    rows: list[DetectorTelemetry] = []
    for detector in TrapDetector:
        count = fired.get(detector, 0)
        dropped = dismissed.get(detector, 0)
        rows.append(
            DetectorTelemetry(
                detector=detector,
                fires=count,
                dismissals=dropped,
                confirmations=max(count - dropped, 0),
            )
        )
    return rows


def load_run_report(payload: dict, *, expected: int) -> WorkloadRunReport:
    """Validate a report payload, refusing a `schema_version` this code does not write.

    The same refusal shape `protean.state.seat_calls.load_seat_calls()` uses: build 2 ships no
    migration path, so a version this loader does not recognise is a stop and not a conversion.
    """
    found = int(payload.get("schema_version", -1))
    if found != expected:
        raise SchemaVersionMismatch(artifact=ARTIFACT, found=found, expected=expected)
    return WorkloadRunReport.model_validate(payload)
