"""The tier-three seam: the call record, the wave's member, and the scripted-return path.

`the build specification (not in this mirror)` § Deliverable 4 (seam contract C2) and § Deliverable 3
(Option A, the wave, the merge).

**A.1 fixed the seam; A.1.i fixed what sits behind it** (folded: S-A79). This module still states
only the *shape* of a tier-three call — the record it is carried by, the facts a scripted return is
matched on, and nothing else. **The spawn path exists now, and it is next door**
(`the build specification (not in this mirror)`): the `kinds:` container and its two classes in
`brain/seats.yaml`, loaded by `protean.cortex.live.kinds` (I1 `KindBlock`); the containment floor as
a **per-class positive grant** resolved against a block's own `allowed_tools` (I2
`CapabilityProfile`); a sandbox profile **composed per spawn** from the class, write-denied by default
over a named allowed set; four static bounds under `runtime:` checked before the first member; and
**the wave's desk**, `protean.cortex.live.wave.SpawnDesk` (I5) — the tick's one spawner, memoized per
`(task, tick)`, one port instance per spawn, opened by `run_wave` per wave and by the `node_calls`
desk's `delegate` arm per call. C2's **receipt half** carries what those spawns are witnessed by, in
`protean.state.calls` beside I4 `SpawnWitness`.

**What is still not here is any library kind**, because the library is seed data and not code:
A.2 landed its two kinds, one per class, under `brain/seats.yaml`'s `kinds:` container with their
prefixes in `brain/seats/kinds/` (`the build specification (not in this mirror)`), so this module carries no
kind name, no dispatch rule and no per-member writable path set. **Which nodes delegate is decided
by the trigger rules** in `the build specification (not in this mirror)`, and none does in this cut: no
authored rule plans a delegate. **A.1.i's battery drives a stand-in binary on fixture roots** —
real argv, real profile, real processes, no model call — where A.1's scripted returns had nothing
behind them at all.

**Where it lands** (§ Deliverable 4, "Where it lands"): `src/protean/cortex/subagents.py` beside
`live/`, inside the licensed package, with its models in `protean.state.calls` beside
`seat_calls.py`'s precedent. `tests/cortex/` takes the mirror; nothing lands flat at
`src/protean/`.

**Two kinds of tier-three call, one record.** A manager **dispatch** member and an outer node's
**delegate** are both calls to a subagent kind, so both compose a C2 `SubagentSpawn` — "the
tier-three call record, carried by **two artifacts under one key** and split between them
without overlap". The journal's half is what a re-invoke needs; the receipt's half is the
durable read of the run; `kind` is the one licensed duplicate, because a receipt read alone must
say what ran. Row M3's spawn half is exactly this: **a layer without the delegate seam writes no
`SubagentSpawn`**, as a layer without `calls` writes no `SeatCallRecord`.

**The member request carries no path** (folded: S-A68). A `WaveMember` is a kind, a unit id and a
reference to this tick's admitted context. The workspace a member sees is filled by the
**runtime** from the tick context — the live layer is handed one at construction — and the
manager's own output never names one, which is the field `--add-dir` would have followed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from protean.state.calls import SpawnAudit, SubagentSpawn
from protean.state.enums import CallType, NodeName
from protean.state.seats import SeatEnvelope, WaveMember

#: The call types a tier-three call is addressed to: the manager's **dispatch** member and an
#: outer node's **delegate**. Both reach a subagent kind; think and escalate reach a model with
#: no kind behind it at all, which is why neither composes a spawn record.
SPAWN_CALL_TYPES: tuple[CallType, ...] = (CallType.DISPATCH, CallType.DELEGATE)

#: The payload key a delegate names its kind in, read as a mapping because the payload travels
#: as the request model dumped (folded: D3-2).
KIND_KEY = "kind"


@dataclass(frozen=True, slots=True)
class MemberFacts:
    """The fields of one wave member a scripted return may be matched on.

    The member is the request (§ Deliverable 3's model table), so the only facts it carries are
    its own: the **kind** asked for, the unit the wave is about, and the admitted-context
    reference. A scripted fixture tells one member from another by its `kind`, which is the one
    thing that differs between two members of one wave — `unit_id` is identical across every
    member by the merge rule, and a wave naming two units is an illegal return rather than a
    merge.
    """

    kind: str
    unit_id: str
    admitted_ref: str


def member_facts(member: WaveMember) -> MemberFacts:
    """One `WaveMember` → what a scripted return is matched on. No process, no path, no spawn."""
    return MemberFacts(
        kind=member.kind, unit_id=member.unit_id, admitted_ref=member.admitted_ref
    )


def spawn_of(
    call: Any,
    *,
    task: str,
    envelope: SeatEnvelope | None = None,
    member_number: int | None = None,
    kind: str = "",
    block_ref: str = "",
    dispatch_id: str = "",
    outcome: str = "",
    permission_denials: Sequence[Mapping[str, Any]] = (),
    audit: SpawnAudit | None = None,
) -> SubagentSpawn:
    """One tier-three call → its C2 record, both halves under the one key.

    `call` is the C1 `NodeCall` a delegate was sent as, or any record carrying the same key
    fields. The record is composed **here**, in the licensed package, because the call is a
    model call and those happen in this package and nowhere else; the runtime writes the two
    artifacts the record is split across, which is what keeps the split a property of the
    contract rather than of two writers agreeing.

    **The last two are build A.1.i's witness fields**, the two names `SPAWN_RECEIPT_FIELDS` gained
    (§ Scaffold clause item 2, A1-7): the envelope's own denial list and the four derived audit
    lists. They are accepted here so a C2 record composed in this package can hold what the receipt
    half now names; `spawns_in()` below composes the **journal's** half and passes neither, which is
    the same shape it already gives `argv` and the caps.
    """
    payload: Mapping[str, Any] = dict(getattr(call, "payload", {}) or {})
    return SubagentSpawn(
        task=task,
        tick=call.tick,
        node=NodeName(call.node),
        call_number=call.call_number,
        member_number=member_number,
        addressee=call.addressee,
        payload=dict(payload),
        payload_model=getattr(call, "payload_model", ""),
        kind=kind or str(payload.get(KIND_KEY, "")),
        block_ref=block_ref,
        envelope=envelope,
        outcome=outcome,
        dispatch_id=dispatch_id,
        permission_denials=[dict(one) for one in permission_denials],
        audit=audit,
    )


def spawns_in(records: Sequence[Any], *, task: str) -> tuple[SubagentSpawn, ...]:
    """Every tier-three call a tick's desk made, as C2 records, in the order they were made.

    Row M3's spawn half: a desk that issued no delegate answers an empty tuple, so **a layer
    without the delegate seam writes no `SubagentSpawn`** — the same shape a layer without
    `calls` gives `SeatCallRecord`.
    """
    return tuple(
        spawn_of(
            record.call,
            task=task,
            envelope=None if record.refused else record.envelope,
            outcome="unavailable" if record.refused else "ok",
        )
        for record in records
        if record.call.addressee in SPAWN_CALL_TYPES
    )
