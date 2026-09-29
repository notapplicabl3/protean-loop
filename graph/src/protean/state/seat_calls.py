"""`SeatCallRecord` — the sixth persisted artifact, one line per **journalled call**.

`the build specification (not in this mirror)` § Deliverable 2 (seam contract S2), § Directional decisions
12 and 13, § Resolutions A1-5, A1-6, S-8, S-18, S-19.

Build 1 records what a seat *returned* — the envelope in the journal, the prediction and the
outcome in the cortex folder's `trace.jsonl` — and what it was *asked* only as a digest
(`protean.state.records.InputSignature`). Build 3 compiles habits, and a habit is a
situation→action pair; a hash of the situation compiles nothing. The request held in full is
what that needs (folded: A1-5) — and in build A.1 it is held by the **journal** alone.

**One line per journalled call at the first boundary the tick reaches, restored or live**
(`the build specification (not in this mirror)` § Deliverable 6, folded: S-A8). Build 2's rule was "one
line per live invocation, and a replay writes none"; a torn tick committed nothing, so its calls
have no record yet, and writing one per *journalled* call is what makes each real invocation
appear exactly once however many boundaries the tick took to reach. The runtime composes the
record at the boundary — never inside the adapter and never inside the port call — because
`task`, `tick` and `ref` are the *runtime's* facts and only the boundary holds all three
(folded: S-18); on a restored call there are no adapter facts at all and the columns they fill
are empty, which is the visible difference between a call this pass made and one it replayed.

**One consequence is stated rather than hidden** (folded: S-A8): a **decode-retry's failed first
attempt** is known only to the live pass and is absent after a replay, because the retry is not
separately journalled. It is the one place a replayed commit and a live one differ.

**The request has one home, and it is not this one** (folded: S-A73). `request` is **removed**
rather than deprecated: the journal entry for the same call carries the payload in full, and a
fact with two homes is a fact with two versions. § Deliverable 4's table is the split — the
journal takes the addressee, the payload, the kind and the block reference; this takes the
resolved argv, the effective caps, the usage, the outcome and the `dispatch_id`, with `kind` the
one licensed duplicate because a receipt read alone must say what ran.

**A retry is its own line** (folded: S-8). The dedupe key carries `outcome` for exactly that
reason: the first invocation of a retried call is `decode_retry` and the second is `ok` or
`unavailable`, so two invocations of one call never collide, and a replayed commit's re-append
is the same silent no-op every other appended artifact gets. The precedent is
`TraceRecord.dedupe_key()`, where `source` is load-bearing for the same reason. **The key widens
with the journal's** — `(task, tick, tier, outcome)` becomes
`(task, tick, node, call#, member#, outcome)` — so N calls per node per tick cannot collide into
a silent no-op.

**Cache reads are recorded here and counted nowhere** (folded: S-19). `usage` and `model_usage`
are copied off the envelope whole, so the cache receipt is on the record; but the tick's *spend*
is `spend_tokens()` — the per-iteration sum of `input_tokens + cache_creation_input_tokens +
output_tokens` — because the top-level aggregate sums a read across the CLI's internal turns and
would bill a cache hit as if it were a miss.

**What it is not.** Not a second trace and not a resume point. `trace.jsonl` still holds the
prediction and the grade; this holds the call. Build 3 reads both, joined on `ref`.

**The writer and the loader live here rather than under `protean.brain/`**, which build 1
otherwise reserves for artifact writers — order W3's writable set names this module and does not
name that package (see the dispatch ledger). Both go through
`protean.brain.jsonl.append_keyed`, so the append-only and keyed-idempotent rules are the same
physical ones every other appended artifact gets.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, JsonValue

from protean import config
from protean.brain.jsonl import append_keyed, read_lines
from protean.state.base import ProteanModel
from protean.state.calls import SpawnAudit
from protean.state.enums import Addressee, CallType, NodeName, Tier
from protean.state.errors import SchemaVersionMismatch
from protean.state.seats import CACHE_READ_KEY

if TYPE_CHECKING:  # pragma: no cover - the annotation only, so `state` imports no `runtime`
    from protean.runtime.seat import SeatCallFacts

#: The artifact name the refusal quotes, so a captured `SchemaVersionMismatch` names the file.
ARTIFACT = "seat_calls"

#: The three counters that are **spend**. `cache_read_input_tokens` is deliberately absent:
#: it is the receipt for tokens that were *not* paid for again (folded: S-19).
SPEND_KEYS: tuple[str, ...] = (
    "input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)

#: `usage.iterations` — the per-iteration breakdown the spend rule sums over when it is present.
ITERATIONS_KEY = "iterations"

#: `SeatCallRecord.outcome`, the closed set. It restates `protean.runtime.seat`'s
#: `SEAT_CALL_OUTCOMES` rather than importing it, because a persisted contract may not depend on
#: the runtime; `tests/state/test_seat_calls.py` pins the two sets equal so the copy cannot drift.
SeatCallOutcome = Literal["ok", "decode_retry", "unavailable"]


def _addressee(value: Any) -> Addressee:
    """A `Tier` for a seat call, a `CallType` for everything else — whichever the name is.

    One function so the receipt and the journal read the same string the same way; a receipt
    keyed on a name neither set holds is a refusal rather than a silent tier.
    """
    text = str(value)
    return Tier(text) if text in set(config.TIERS) else CallType(text)


def _sum_spend(usage: Mapping[str, Any]) -> int:
    return sum(value for key in SPEND_KEYS if isinstance(value := usage.get(key), int))


def spend_tokens(usage: Mapping[str, Any]) -> int:
    """The tokens one invocation actually spent (folded: S-19).

    The **per-iteration** sum of `input_tokens + cache_creation_input_tokens + output_tokens`
    over `usage.iterations`, never the top-level aggregate — the aggregate sums
    `cache_read_input_tokens` across the CLI's own internal turns, so counting it would charge a
    cache hit at the price of a miss and would trip homeostasis's ceilings on the cheapest call
    of the run.

    An envelope with no `iterations` (a scripted seat's, and the at-cap shape whose list is
    empty) is read as one iteration of its top-level counters — the same three keys, so a cache
    read is not spend on that path either.
    """
    iterations = usage.get(ITERATIONS_KEY)
    if isinstance(iterations, list) and iterations:
        return sum(
            _sum_spend(entry) for entry in iterations if isinstance(entry, Mapping)
        )
    return _sum_spend(usage)


def cache_reads(usage: Mapping[str, Any]) -> int:
    """The cache receipt, recorded and reported — never added to `spend_tokens()`."""
    value = usage.get(CACHE_READ_KEY)
    return value if isinstance(value, int) else 0


class SeatCallRecord(ProteanModel):
    """One journalled call, as the line `brain/state/<task_id>/seat_calls.jsonl` holds it.

    Every field of S2's table as build A.1 amends it, plus three the DoD asks of the record
    rather than of the facts: `argv` and `num_turns`, which row K1 reads off "every director and
    planner `SeatCallRecord`", and `error`, which is the only durable place a refused
    invocation's message lands — a refusal writes no journal envelope at all.
    """

    schema_version: int
    task: str
    tick: int
    #: The calling node — the key's third component, and what makes N calls per tick separable.
    #: A seat call is the cortex's; a think, an escalate and a delegate are the calling node's.
    node: NodeName = NodeName.CORTEX
    #: The `call#` this record's journal entry is keyed under. Model calls number from **1**;
    #: `0` is the reserved key of a node's own output entry, which is not a call and gets no
    #: receipt at all.
    call_number: int = Field(default=1, ge=1)
    #: The wave member's sub-key beneath the wave's one `call#`. `None` outside a wave — which is
    #: every call A.1 makes, the wave being order W8's.
    member_number: int | None = None
    #: **The addressee in build A.1**, not the tier (§ Scaffold clause item 2, S2's amendments):
    #: the executor seat is gone and a dispatch receipt is emitted by a call type, so a receipt
    #: for one has a legal column to sit in. Optional for `JournalEntry.tier`'s own reason — a
    #: think call has no tier — so the two columns move together.
    tier: Addressee | None = None
    #: The subagent kind that answered. **The one licensed duplicate** of § Deliverable 4's
    #: split: the journal carries it too, because a receipt read alone must say what ran.
    kind: str = ""
    #: The dispatch this call belongs to. **Receipt-only** (folded: S-A14) — it is never on
    #: `UnitObservation`, whose schema this build leaves untouched.
    dispatch_id: str = ""
    #: The `prediction_key()` of the cortex-trace prediction this call belongs to — the join to
    #: `trace.jsonl`, explicit rather than inferred. `None` on a call that produced no prediction
    #: to name: a refusal mints no tier-keyed record, and **think, escalate and delegate mint
    #: none by construction** (folded: S-A9) — the calling node already records its one
    #: prediction for the tick, so N calls per node never contend for a single `ref`.
    ref: str | None = None
    session_handle: str = ""
    model: str = ""
    effort: str = ""
    permission_mode: str | None = None
    #: The resolved CLI version at call time — the mitigation that ships in place of a pin
    #: (§ Rulings 16, decision 13).
    cli_version: str = ""
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    model_usage: dict[str, JsonValue] = Field(default_factory=dict)
    wall_seconds: float = 0.0
    outcome: SeatCallOutcome = "ok"
    argv: list[str] = Field(default_factory=list)
    num_turns: int | None = None
    error: str = ""
    #: **The four columns build A.1.i adds, under one bump 2 → 3**
    #: (`the build specification (not in this mirror)` § Scaffold clause item 2, § Deliverable 6, A1-7,
    #: A1-9). The first two are the **effective caps as they ran**: `SPAWN_RECEIPT_FIELDS` has named
    #: both since A.1 and **no column carried either until this build** — the landed gap A.1.i
    #: lands. The last two are the amendment itself: the envelope's own denial list, and the four
    #: derived audit lists as one nested object. All four ride from the spawn to this boundary on
    #: `SeatCallFacts`, which gains the same four (folded: S-i4), and **nothing but a spawn fills
    #: them** — a seat call resolves no kind block and has no caps of a spawn's kind to report.
    max_call_usd: float | None = None
    timeout_seconds: float | None = None
    permission_denials: list[dict[str, JsonValue]] = Field(default_factory=list)
    audit: SpawnAudit | None = None

    @classmethod
    def from_call(
        cls,
        facts: "SeatCallFacts | None" = None,
        *,
        task: str,
        tick: int,
        node: NodeName,
        call_number: int,
        member_number: int | None = None,
        tier: Addressee | None = None,
        kind: str = "",
        dispatch_id: str = "",
        ref: str | None = None,
        outcome: SeatCallOutcome | None = None,
        schema_version: int | None = None,
    ) -> "SeatCallRecord":
        """Compose the record at the boundary: the journal's key plus the adapter's facts.

        The key — `task`, `tick`, `node`, `call#`, `member#` — and `ref` are passed rather than
        read off the facts because the adapter knows none of them, which is the whole reason the
        write is at the boundary (S-18). **`facts` is optional** for build A.1's own reason: the
        boundary writes one line per journalled call *restored or live*, and a restored call made
        no invocation, so the adapter's columns are empty and the journal's key is the whole of
        what the line can say.
        """
        return cls(
            schema_version=(
                config.SEAT_CALL_SCHEMA_VERSION if schema_version is None else schema_version
            ),
            task=task,
            tick=tick,
            node=node,
            call_number=call_number,
            member_number=member_number,
            tier=(
                tier
                if facts is None
                else _addressee(facts.tier) if tier is None else tier
            ),
            kind=kind,
            dispatch_id=dispatch_id,
            ref=ref,
            session_handle="" if facts is None else facts.session_handle,
            model="" if facts is None else facts.model,
            effort="" if facts is None else facts.effort,
            permission_mode=None if facts is None else facts.permission_mode,
            cli_version="" if facts is None else facts.cli_version,
            usage={} if facts is None else dict(facts.usage),
            model_usage={} if facts is None else dict(facts.model_usage),
            wall_seconds=0.0 if facts is None else facts.wall_seconds,
            outcome=(
                outcome
                if outcome is not None
                else "ok" if facts is None else facts.outcome
            ),
            argv=[] if facts is None else list(facts.argv),
            num_turns=None if facts is None else facts.num_turns,
            error="" if facts is None else facts.error,
            # **The same `facts is None` shape as every column above, for build A.1's own reason**:
            # the boundary writes one line per journalled call *restored or live*, and a restored
            # call made no invocation. A live call that was not a spawn carries these as their own
            # empty values, which is the visible difference between a spawn's receipt and a seat's.
            max_call_usd=None if facts is None else facts.max_call_usd,
            timeout_seconds=None if facts is None else facts.timeout_seconds,
            permission_denials=(
                [] if facts is None else [dict(one) for one in facts.permission_denials]
            ),
            audit=None if facts is None else facts.audit,
        )

    def dedupe_key(self) -> tuple[str, int, str, int, int | None, str]:
        """`(task, tick, node, call#, member#, outcome)` — a collision is a silent no-op.

        The journal's own key plus `outcome`, which is the component that keeps a retry's two
        lines apart, the way `source` keeps a `operator_answer` and a `runtime_grade` apart on one
        trace file: the first of a retried pair is always `decode_retry`. The key **widened with
        the journal's** (§ Deliverable 4) so that N calls per node per tick cannot collide into
        a silent no-op — which build 2's `(task, tick, tier, outcome)` could not prevent once a
        node made more than one.
        """
        return (
            self.task,
            self.tick,
            str(self.node),
            self.call_number,
            self.member_number,
            str(self.outcome),
        )

    def spend_tokens(self) -> int:
        """This invocation's spend, per S-19. Cache reads are not in it."""
        return spend_tokens(self.usage)

    def cache_reads(self) -> int:
        """This invocation's cache receipt — recorded, never counted as spend."""
        return cache_reads(self.usage)


def dedupe_key(payload: Mapping[str, Any]) -> Hashable:
    """`(task, tick, node, call#, member#, outcome)` — `SeatCallRecord.dedupe_key()`'s own key.

    Both implementations widened together (§ Deliverable 4): a payload read off disk and a
    record in hand must key identically, or a re-append would be a no-op on one path and a
    duplicate line on the other.
    """
    member = payload.get("member_number")
    return (
        str(payload.get("task")),
        int(payload.get("tick", -1)),
        str(payload.get("node")),
        int(payload.get("call_number", -1)),
        None if member is None else int(member),
        str(payload.get("outcome")),
    )


def append_seat_call(path: Path, record: SeatCallRecord) -> SeatCallRecord | None:
    """Append one record unless its key is already committed. `None` means already there."""
    written = append_keyed(path, record.model_dump(mode="json"), key_fn=dedupe_key)
    return None if written is None else record


def load_seat_calls(path: Path) -> list[SeatCallRecord]:
    """Every record in one task's file, refusing a `schema_version` this code does not write.

    The refusal is `SchemaVersionMismatch`, which already quotes both numbers — build 2 ships no
    migration path either, so a version this loader does not recognise is a stop and not a
    conversion.
    """
    records: list[SeatCallRecord] = []
    for line in read_lines(path):
        found = int(line.get("schema_version", -1))
        if found != config.SEAT_CALL_SCHEMA_VERSION:
            raise SchemaVersionMismatch(
                artifact=ARTIFACT,
                found=found,
                expected=config.SEAT_CALL_SCHEMA_VERSION,
            )
        records.append(SeatCallRecord.model_validate(line))
    return records
