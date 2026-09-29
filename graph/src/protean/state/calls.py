"""The four seam contracts build A.1 introduces — C1, C2, C3 and C4.

`the build specification (not in this mirror)` § Scaffold clause item 3 (the four contracts, lettered
`C*` so they cannot be read as DoD row ids), § Deliverable 2 (C1 `NodeCall`), § Deliverable 4
(C2 `SubagentSpawn` and its two-artifact split), § Deliverable 1 (C3 `FiringDecision`) and
§ Deliverable 5 (C4 `BodyTransport`).

**This module is authored once, for the whole build, and is read-only to orders W2–W10**
(`the work orders (not in this mirror)` order W1). Every field below comes from the SPEC's own
tables. A producer order that finds a field missing writes a `BLOCKED` entry rather than
widening a seam contract — which is why authoring it completely here is the job.

**Where the models live, and why here.** Beside `seat_calls.py`'s precedent
(§ Deliverable 4, "Where it lands"): a persisted or journalled contract lives under
`protean.state`, and the package that *makes* the call lives under `protean.cortex`. This
module imports nothing from `protean.runtime` and nothing from `protean.cortex`, so the
contract cannot acquire a dependency on the thing it constrains.

**What is not here.** **The spawn path exists now** — build A.1.i landed the `kinds:` container,
the per-class containment floor, the per-spawn profile, the four bounds and the wave's desk — and
**C2's receipt half carries the witness**: `permission_denials` and one `audit` object, the four
lists the runtime derives, which is the only part of A.1's seam A.1.i reopened
(`the build specification (not in this mirror)` § Scaffold clause item 2, § Deliverable 6, A1-7). I4
`SpawnWitness` below is that object's shape, and it lives here because it is persisted.

What is still not here is **any library kind**, because the library is seed data and not code:
A.2 landed it in the shipping seed, whose two class sub-mappings under `kinds:` no longer ship
empty, with each kind's prefix in `brain/seats/kinds/` and the manager's dispatch rule a clause of
its own prefix (`the build specification (not in this mirror)`), so this module holds no kind name, no
dispatch rule and no per-member writable path set. **And the no-import rule is unchanged**: this
module imports nothing from
`protean.runtime` and nothing from `protean.cortex`, so the contract still cannot acquire a
dependency on the thing it constrains — the four audit lists are *derived* in
`protean.cortex.live.audit` and only their **shape** is stated here.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import Field, JsonValue, model_validator

from protean.state.base import ProteanModel
from protean.state.enums import Addressee, CallType, NodeName, Tier
from protean.state.seats import SeatEnvelope

# --------------------------------------------------------------------------------------
# C1 — `NodeCall`: one call through the one port
# --------------------------------------------------------------------------------------


class NodeCall(ProteanModel):
    """C1 — one call, as the journal keys it and homeostasis counts it.

    § Deliverable 2: "**C1 `NodeCall`** carries: `type` (one of the three), `node`, `tick`,
    `call#`, the typed payload, and the **addressee** it is sent to — a `Tier` for a seat call,
    a call type otherwise. It is what the journal keys on (Deliverable 6) and what homeostasis
    counts (Deliverable 7)."

    **One call is one record here whatever it addresses.** think, escalate and delegate are
    three *callers* of the one `(addressee, request) -> SeatEnvelope`, never three ports
    (decision 10): a second record type would give containment, the caps and the journal a
    second code path, which is exactly what the one-port decision exists to forbid.

    **The payload is the request model as sent, dumped to JSON, with the model it was dumped
    from named beside it.** That is `SeatCallRecord.request`'s shape and `InputSignature`'s
    habit of naming the model it digested: a contract under `protean.state` may not import the
    per-addressee request models from the runtime, and a mapping the sender names the type of
    stays reconstructable by the receiver without one. The journal holds the payload in full —
    the receipt does not, because a fact with two homes is a fact with two versions
    (§ Deliverable 4).
    """

    #: The call type this is. A seat call carries the addressee's tier below and no call type,
    #: which is the one shape `type` is `None` for.
    type: CallType | None = None
    node: NodeName
    tick: int
    #: The `call#` component of the journal key `(task, tick, node, call#[, member#])`. The
    #: node's **own output entry** is the reserved `call# = 0` (§ Deliverable 1,
    #: folded: S-A76), so a call's number starts at 1. The reservation itself is order W4's.
    call_number: int = Field(ge=1)
    #: The request as sent, in full.
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    #: The name of the model `payload` was dumped from — how a typed payload survives a
    #: mapping. `""` for a payload no model produced.
    payload_model: str = ""
    #: A `Tier` for a seat call, a `CallType` for everything else (decision 10).
    addressee: Addressee

    @model_validator(mode="after")
    def _a_call_type_addressee_is_the_call_type(self) -> "NodeCall":
        """The addressee and the type name one thing, or the journal keys two.

        A call type addressed anywhere but at itself would make the legality table
        (§ Deliverable 4) unreachable: the table is keyed by addressee, and a `think` sent to
        `escalate` would be checked against the wrong legal return.
        """
        if isinstance(self.addressee, CallType):
            if self.type is None:
                raise ValueError(
                    "a call-type addressee carries the call type it names; "
                    f"addressee={self.addressee}, type=None"
                )
            if self.addressee is not self.type:
                raise ValueError(
                    f"a call is addressed to its own type: "
                    f"addressee={self.addressee}, type={self.type}"
                )
        elif self.type is not None:
            raise ValueError(
                f"a seat call carries no call type: addressee={self.addressee}, "
                f"type={self.type}"
            )
        return self

    def is_seat_call(self) -> bool:
        """A seat call is addressed to a tier; everything else to a call type."""
        return isinstance(self.addressee, Tier)


# --------------------------------------------------------------------------------------
# C2 — `SubagentSpawn`: the tier-three call record, two artifacts under one key
# --------------------------------------------------------------------------------------

#: The key both artifacts carry (§ Deliverable 4's table). `member#` is the sub-key a wave's
#: member takes beneath the wave's one `call#`.
SPAWN_KEY_FIELDS: Final[tuple[str, ...]] = (
    "task",
    "tick",
    "node",
    "call_number",
    "member_number",
)

#: The journal's half — "what a re-invoke needs, and nothing more".
SPAWN_JOURNAL_FIELDS: Final[tuple[str, ...]] = (
    "addressee",
    "payload",
    "payload_model",
    "kind",
    "block_ref",
    "envelope",
)

#: The receipt's half — the durable read of the run.
#:
#: **Build A.1.i's one additive amendment, and the only part of A.1's seam it reopens**
#: (`the build specification (not in this mirror)` § Scaffold clause item 2, § Deliverable 6, A1-7):
#: it gains exactly two names — `permission_denials`, the envelope's own denial list and a fact of
#: the same class as `usage`, and `audit`, one nested object carrying the four lists the runtime
#: derives (I4 `SpawnWitness` below). `SPAWN_JOURNAL_FIELDS` does not move, and the import-time
#: no-overlap assertion still holds with `kind` the one licensed duplicate.
SPAWN_RECEIPT_FIELDS: Final[tuple[str, ...]] = (
    "argv",
    "max_call_usd",
    "timeout_seconds",
    "usage",
    "outcome",
    "kind",
    "dispatch_id",
    "permission_denials",
    "audit",
)

#: The one field § Deliverable 4 licenses to appear in both halves: "the **kind** (the one
#: licensed duplicate, because a receipt read alone must say what ran)".
SPAWN_LICENSED_DUPLICATES: Final[tuple[str, ...]] = ("kind",)

_OVERLAP = (set(SPAWN_JOURNAL_FIELDS) & set(SPAWN_RECEIPT_FIELDS)) - set(
    SPAWN_LICENSED_DUPLICATES
)
if _OVERLAP:  # pragma: no cover - a module-level contract assertion, not a branch
    raise ImportError(
        "the journal's half and the receipt's half are split without overlap "
        f"(§ Deliverable 4); these fields are in both: {sorted(_OVERLAP)}"
    )
del _OVERLAP


# --------------------------------------------------------------------------------------
# I4 — `SpawnWitness`: what one spawn is witnessed by, beside C2 because it is persisted
# --------------------------------------------------------------------------------------

#: How many changed paths one tree's diff may carry before it says so and stops
#: (`the build specification (not in this mirror)` § Deliverable 6, "Bounded"). Build 2's
#: `TEMP_FILE_LIMIT` precedent: a spawn that filled a granted tree must still produce a receipt a
#: person can read, and a list that grows without a ceiling is a receipt nobody reads.
SPAWN_CHANGED_PATH_LIMIT: Final[int] = 200

#: What a truncated list says in place of the paths it dropped. A *name* rather than a sentence,
#: so a reader greps for one token (`RESUMED_AS_NEW`'s own precedent).
SPAWN_CHANGED_TRUNCATED: Final[str] = "truncated-at-SPAWN_CHANGED_PATH_LIMIT"


class SpawnTreeDiff(ProteanModel):
    """One tree's own half of `wrote` or `wrote_outside_workspace`.

    § Deliverable 6's derivation table: **one digest per tree** to say that the tree moved at all,
    beside a **bounded changed-path list by mtime and size** — never a hash per path, which is what
    build 2's landed per-tree digest and bounded changed-path list are the precedent for
    (folded: S-i47).

    **It carries no baseline** (folded: S-i47). `digest` is the tree as the **join** found it and
    `moved` is the comparison's answer; the baseline is the desk's own working state between its
    open and the join, and a persisted field with no reader is a field that invites one.
    """

    #: The tree this diff is of, resolved.
    tree: str
    #: Did this tree move at all between the desk's open and the join?
    moved: bool = False
    #: The tree as the **join** found it, or `""` where the tree is witnessed by mtime alone — a
    #: machine-shared tree a digest would only report as noise (§ Deliverable 6).
    digest: str = ""
    #: The paths that appeared or changed, by mtime and size, bounded and sorted. The last entry is
    #: `SPAWN_CHANGED_TRUNCATED` where the bound was reached.
    changed: list[str] = Field(default_factory=list)


class SpawnAudit(ProteanModel):
    """The four lists the runtime derives — the shape the persisted `audit` column takes.

    § Deliverable 6. Two of the four are **wave-level** facts and not per-member ones
    (folded: S-i24, folded: S-i39): one baseline before the first member, one diff after the join,
    over trees every member shares — so `wrote` and `wrote_outside_workspace` are written
    **identically to every member's receipt** exactly as `dispatch_id` is, and are per spawn only
    for a **delegate**, whose wave is one. Per-member attribution is not available from one baseline
    and one diff and nothing fakes it. `wrote` stays wave-level because **A.2 upheld row B52's
    default** and bought the attribution with the manager's dispatch rule instead: at most one
    writing member per wave, so a non-empty wave-level `wrote` attributes to exactly one member
    (`the build specification (not in this mirror)` § Deliverable 4, L5).

    The remaining two are per spawn, being derived from that spawn's own denials.
    """

    #: The granted workspace's own diff. Wave-level.
    wrote: list[SpawnTreeDiff] = Field(default_factory=list)
    #: The same question asked of every allowed **directory** subpath — the resolved
    #: `runtime.spawn_writable` trees and `SPAWN_PROCESS_ALLOWANCES`' own directories, its device
    #: literals excluded by name because a device is not a file (folded: S-i49). Wave-level, and it
    #: exists because writes **into** the allowed set were witnessed by nothing (folded: S-i39).
    wrote_outside_workspace: list[SpawnTreeDiff] = Field(default_factory=list)
    #: Why each denial wrote or reached outside the granted workspace. Per spawn.
    left_the_clone: list[str] = Field(default_factory=list)
    #: Why each denial, the wrapper's own `execvp` text or the join-time process-group read is an
    #: attempt to **run** a binary rather than to name one. Per spawn.
    exec_attempted: list[str] = Field(default_factory=list)


class SpawnWitness(ProteanModel):
    """**I4** — what one spawn is witnessed by: the denial list and the four audit lists.

    `the build specification (not in this mirror)` § Scaffold clause item 3, § Deliverable 6. Composed
    in the licensed package, because a spawn is a model call and those happen there; **written** by
    the runtime, because the runtime writes both artifacts.

    **Its home is here, beside C2**, because it is the shape the persisted `audit` column takes and
    a persisted model lives where the artifact it rides on lives (folded: S-i28) — where
    `KindBlock` and `CapabilityProfile` stay in `protean.cortex.live.kinds`, neither being
    persisted, and `WaveBound` is retired (row M2, folded: S-i16).

    **The two halves it fills are the two names `SPAWN_RECEIPT_FIELDS` gained and no more**: the
    denial list goes to the `permission_denials` column and `audit` to the `audit` column, so
    neither fact has two homes on disk. **It carries no baseline reference** (folded: S-i47).
    """

    #: The envelope's own `permission_denials`, as received. Empty where no envelope came back.
    permission_denials: list[dict[str, JsonValue]] = Field(default_factory=list)
    #: The four derived lists, and the whole of what the `audit` column holds.
    audit: SpawnAudit = Field(default_factory=SpawnAudit)


# --------------------------------------------------------------------------------------
# C2 — the model itself
# --------------------------------------------------------------------------------------


class SubagentSpawn(ProteanModel):
    """C2 — one tier-three call, as the journal and the receipt carry it between them.

    § Deliverable 4: "**C2 `SubagentSpawn`** — the tier-three call record, carried by **two
    artifacts under one key** and split between them without overlap." The whole record is one
    model so that the split is a property of the contract rather than of two writers agreeing;
    `journal_half()` and `receipt_half()` are the only two views of it, and
    `SPAWN_LICENSED_DUPLICATES` names the one field allowed in both.

    **`SeatCallRecord.request` is removed and the request payload lives in the journal alone**
    (folded: S-A73). `dispatch_id` is receipt-only (folded: S-A14): a committed observation
    joins to the call that produced it by the tick's own `(node, call#)` keys, and
    `UnitObservation` — a forbid-extras model with no version key of its own — is untouched by
    this build.

    **The block reference is the field a kind's containment block is named in.** A.1 fixes the
    field; A.1.i fills it. In A.1's scripted battery it names the fixture's scripted return.
    """

    # the key — both artifacts carry it
    task: str
    tick: int
    node: NodeName
    #: The wave takes **one** `call#`; its members take `member#` sub-keys beneath it, assigned
    #: in the order the `ManagerPlan` lists them (§ Deliverable 4).
    call_number: int = Field(ge=1)
    member_number: int | None = None

    # the journal's half — what a re-invoke needs, and nothing more
    addressee: Addressee = CallType.DISPATCH
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    payload_model: str = ""
    #: The subagent kind that answered. The one licensed duplicate.
    kind: str = ""
    #: The containment block this spawn resolved: `kinds.<class>.<name>`, the block reference
    #: `protean.cortex.live.kinds.KindBlock.block_ref` mints and nothing else does. A.1 fixed the
    #: field and wrote the bare kind name into the journal's own column; A.1.i fills it with the
    #: reference the desk resolved, which is a change of **value** and not of field set — so no
    #: schema version but the receipt's moves (folded: S-i12).
    block_ref: str = ""
    envelope: SeatEnvelope | None = None

    # the receipt's half — the durable read of the run
    argv: list[str] = Field(default_factory=list)
    #: The **effective** caps as they ran, not as they were configured.
    max_call_usd: float | None = None
    timeout_seconds: float | None = None
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    outcome: str = ""
    #: Receipt-only, and never on `UnitObservation` (folded: S-A14). **What fills it is the
    #: landed `protean.runtime.cycle.dispatch_id_of()`'s own format — `<task>-t<tick>-c<call#>`,
    #: identical across every member of one wave and minted nowhere** (A1-15, folded: S-i8): a
    #: receipt line can then be read alone without giving one fact two sources of truth.
    dispatch_id: str = ""
    #: The envelope's own `permission_denials` — every call this spawn's permission layer
    #: **refused**. A denial is a receipt rather than a violation (build 2's S-44), and it is the
    #: source both of `audit.left_the_clone` and of `audit.exec_attempted`.
    permission_denials: list[dict[str, JsonValue]] = Field(default_factory=list)
    #: The four derived audit lists (I4 `SpawnWitness`). `None` on a call with no spawn behind it.
    audit: SpawnAudit | None = None

    def key(self) -> tuple[str, int, str, int, int | None]:
        """`(task, tick, node, call#, member#)` — the one key both artifacts are under."""
        return (
            self.task,
            self.tick,
            str(self.node),
            self.call_number,
            self.member_number,
        )

    def journal_half(self) -> dict[str, Any]:
        """The key plus what a re-invoke needs. No receipt field is in it."""
        return self._half(SPAWN_JOURNAL_FIELDS)

    def receipt_half(self) -> dict[str, Any]:
        """The key plus the durable read of the run. No journal field but `kind` is in it."""
        return self._half(SPAWN_RECEIPT_FIELDS)

    def _half(self, fields: tuple[str, ...]) -> dict[str, Any]:
        dumped = self.model_dump(mode="json")
        return {name: dumped[name] for name in SPAWN_KEY_FIELDS + fields}


# --------------------------------------------------------------------------------------
# C3 — `FiringDecision`: the cheap check's answer and the prediction it records
# --------------------------------------------------------------------------------------


class FiringDecision(ProteanModel):
    """C3 — the check that ran, the value it read, and the threshold it read it against.

    § Deliverable 1: every outer node gains one pure function beside its body — projected input
    and its own weights in, a `FiringDecision` out. "It opens no file, spawns nothing, names no
    binary, and its threshold is a `weights.yaml` key — so *which* nodes fire is adaptation in
    data, exactly as ruling 2 [B] requires, and never a difference in wiring."

    **The comparison sense is stated, not implied** (folded: S-A91): a check **fires** when its
    score is **≥** its threshold, exactly as `nodes/detectors.py` scores a trap scalar, so
    *raising* the threshold makes the node skip more. `fired` is that comparison's answer and
    is carried rather than recomputed, because the gate's check has no threshold to recompute
    it from.

    **The gate is the stated exemption** (folded: S-A17). `basal_ganglia` is the one node
    outside `WEIGHTS_WRITABLE_NODES` and its `weights.yaml` is contractually empty, so its
    cheap check carries **no threshold key at all**: it is structural — a pending unit is
    present, or it is not. `threshold` is `None` and `key` is `""` for exactly that check.

    **It is an output, and it rides the node's own journal entry.** A skipped node appends this
    at the reserved `call# = 0` as that entry's `output`, which is why `NodeOutputPayload`
    gains it as a union member (§ Scaffold clause item 2, folded: S-A93). That membership is
    **order W4's**, not W1's, and the `emitter` discriminator below is what it joins on.
    """

    emitter: Literal["firing"] = "firing"
    tick: int
    node: NodeName
    #: The check that ran, named. One per outer node, beside its body.
    check: str
    #: The `weights.yaml` key the threshold was read from. `""` for the gate's structural check.
    key: str = ""
    #: The value the check read.
    value: float
    #: The threshold it read it against. `None` for the gate's structural check.
    threshold: float | None = None
    #: `value >= threshold` — the node did its work. Carried, because the structural check has
    #: no threshold to recompute it from.
    fired: bool

    @model_validator(mode="after")
    def _a_threshold_and_its_key_arrive_together(self) -> "FiringDecision":
        """A threshold with no key is a number no learner can move (§ Deliverable 1)."""
        if (self.threshold is None) != (self.key == ""):
            raise ValueError(
                "a firing threshold and the weights key it was read from arrive together; "
                f"key={self.key!r}, threshold={self.threshold!r} — the gate's structural "
                "check carries neither"
            )
        return self


# --------------------------------------------------------------------------------------
# C4 — `BodyTransport`: what a body is, and what is held identical across bodies
# --------------------------------------------------------------------------------------

#: `runtime.body`'s two legal values (§ Deliverable 5, folded: S-A78). `print` is the default
#: body — the CLI's non-interactive mode, whose binary this module may not name (M21, and the
#: static half of `tests/test_zero_calls.py`); `terminal` is a live interactive session the
#: **runtime** launches. The key
#: applies to the two cortex seats only, and a `body` key anywhere else in `brain/seats.yaml` is
#: refused at load by name — order W9 lands the key and its refusal; the literal is authored
#: here with the rest of the build's.
BODY_PRINT: Final[str] = "print"
BODY_TERMINAL: Final[str] = "terminal"
BodyName = Literal["print", "terminal"]
BODY_NAMES: Final[tuple[str, ...]] = (BODY_PRINT, BODY_TERMINAL)

#: **What is identical across bodies, by contract** (§ Deliverable 5, decision 9), exactly that
#: list and no other:
#:
#: - `system_prompt_prefix` — the **assembled** prefix, two seed halves in a fixed order — a
#:   `NODE.md` first, then the seat, call-type or kind prefix file — plus, for a `dispatch` member
#:   only, the unit's `intent` after a fixed delimiter line (A.2 § Deliverable 7), which is the
#:   port's and therefore still identical across bodies. Never either file alone — a think call's
#:   first half is the **calling node's** `NODE.md`, so a body that substituted a different
#:   first half would change the result while passing a file-level comparison (folded: S-A66).
#: - `request_on_stdin` — the request bytes handed to the body.
#: - `tool_set` — the resolved tool set.
#: - `schema` — the schema handed to the model.
#: - `session_mechanics` — "mint, resume, discard at task end" for the two seats and **none**
#:   for everything else (folded: S-A31), so the clause is satisfied for the non-seat calls by
#:   both bodies doing nothing.
#: - `journaling` — the entry the call writes.
BODY_INVARIANTS: Final[tuple[str, ...]] = (
    "system_prompt_prefix",
    "request_on_stdin",
    "tool_set",
    "schema",
    "session_mechanics",
    "journaling",
)


class BodyTransport(ProteanModel):
    """C4 — a body is a transport: it carries bytes to a model and bytes back, and decides nothing.

    § Deliverable 5: "**What is identical across bodies, by contract:** the system-prompt
    prefix, the request on stdin, the tool set, the schema handed to the model, the session
    mechanics and the journaling. **C4 `BodyTransport`** names exactly that list, and the loader
    refuses a body that does not implement all of it."

    **The refusal is the contract's, not the loader's own invention.** A body that implements
    five of the six is refused here by name, before a session handle is minted, so "the body
    never changes the result" is a property of what can be constructed rather than of what a
    reviewer remembered to check. `implements` is a set rather than a flag per invariant so
    that the refusal can quote the missing names.

    **Containment is identical across bodies by construction** (folded: A1-8, the operator 2026-09-11),
    because both bodies are processes the runtime spawns: the same absolute-path binary, the
    same argv minus the print flag plus the interactive flags, the same env scrub, sandbox
    wrapper, tool set and session handles. A body the runtime did not launch is refused by name.
    **Tier three always runs under the `print` body.** Which binary either body actually spawns
    is `protean.cortex`'s to name and never this module's.
    """

    name: BodyName
    #: The invariants this body implements. Every one of `BODY_INVARIANTS`, or it is refused.
    implements: tuple[str, ...] = BODY_INVARIANTS
    #: Whether the runtime launched this body. The operator attaches to the runtime-launched session,
    #: never the reverse (§ Deliverable 5); order W9 is where the refusal is enforced at load.
    runtime_launched: bool = True

    @model_validator(mode="after")
    def _a_body_implements_every_invariant(self) -> "BodyTransport":
        """The loader's refusal, stated on the contract (§ Deliverable 5)."""
        missing = tuple(name for name in BODY_INVARIANTS if name not in self.implements)
        if missing:
            raise ValueError(
                f"body {self.name!r} does not implement {list(missing)}; a body carries bytes "
                f"and decides nothing, so all of {list(BODY_INVARIANTS)} are identical across "
                f"bodies by contract"
            )
        unknown = tuple(name for name in self.implements if name not in BODY_INVARIANTS)
        if unknown:
            raise ValueError(
                f"body {self.name!r} names invariants that are not in the contract: "
                f"{list(unknown)} — the list is closed at {list(BODY_INVARIANTS)}"
            )
        return self
