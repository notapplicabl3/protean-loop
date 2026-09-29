"""One tick: every node on the path, in `config.py`'s order, then one boundary commit.

`the build specification (not in this mirror)` § Deliverable 3 — the cycle, the two writes, the commit order,
the two seat-skip conditions — and § Deliverable 4's prediction→outcome loop. A.1 rewrites binding contract 5: each node retains its scheduled step, outer bodies use
cheap firing checks, and calls use the addressee-keyed port. The scripted battery remains zero-call.

**The order is iterated, never restated.** The loop walks `protean.config.NODE_ORDER` itself, so
the recorded call sequence is that tuple by construction; a node module that hardcoded an order
would be the failure this arrangement exists to make impossible.

**A journal entry per call, keyed `(task, tick, node, call#)`; one checkpoint at the boundary.**
Every node writes exactly one entry of its own at the reserved **`call# = 0`**, carrying its
`output` — six of six, the seat's included, whatever else the step did — and **each model call
the tick makes writes one more, numbered from 1 per node and written once, at return**. A tick is
therefore six output entries plus its call entries; a wave adds member entries beneath its
call key, so a tick that reaches the seat need not hold exactly seven.
A call that never returned leaves no entry to reconcile; a call that returned a refusal leaves one
with no envelope, which is what re-invokes it in place while the journalled calls after it
restore. **The boundary is still the only resume point**: one checkpoint, after the cycle, and a
torn tick replays from it.

**A node may skip its body on its own cheap check, and it still records a prediction**
(`the build specification (not in this mirror)` § Deliverable 1, decisions 3 and 15). The check is a pure
function beside the node's body over its projected input and its own `weights.yaml` threshold, so
*which* nodes fire is adaptation in data and never a difference in wiring; a node that declines
issues none of the calls planned for it, runs no body, leaves its `LatestOutputs` slot exactly as
last tick left it — `projections` stamp-tests every slot, which is the one mechanism that stops a
stale one reaching a consumer — and writes its `call# = 0` entry carrying the `FiringDecision` as
that entry's `output`. A skip is a recorded prediction, not an absence.

**The two contractual inhibitions never skip** (decision 14). Homeostasis's ceiling evaluation
and `stop` flag always run and the node always produces its full `HomeostasisReport`, so only its
think call is skippable; the gate's veto always runs when a unit is pending, which is exactly
when its structural check fires.

**Two conditions skip the seat call and neither shortens the tick**: the gate's `no_go`, which
inhibits the dispatch wave and every delegate for the pending unit, and a mid-tick terminal —
homeostasis's ceiling — which is detected mid-tick and committed at the boundary.

**A call is the one thing whose effect is external**, so a replay restores its journaled
`SeatEnvelope` instead of re-invoking it; a crash *inside* the call leaves no entry, the re-run
invokes, and the workspace is re-observed. **In A.1 that is every call and not only the seat's**
— the condition is a restorable result being present, never an entry existing — and the boundary
writes one `SeatCallRecord` per journalled call of the committing pass, restored or live, which
is what makes a torn tick's real invocations appear exactly once.

**Build 3 adds one step before the call and one write after the commit** (`the build specification (not in this mirror)` § Deliverable 4): the seat step consults the task's compiled procedures before it
reaches the port, and a match answers with a `SeatEnvelope` through the unchanged port — same
decode, same journal entry, same cortex prediction — while the boundary records the answer as a
P3 `HabitHit` instead of a `SeatCallRecord`. A layer without the third seam consults nothing.

**Nothing here calls a model.** The runtime holds the port; the scripted seats live in
`src/protean/cortex/`.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from protean import config
from protean.brain.episodes import episode_id, recent_episodes
from protean.brain.folders import NodeFolder
from protean.brain.trace import committed_predictions, graded_refs
from protean.nodes import homeostasis as homeostasis_node
from protean.nodes.hippocampus import live_terms, semantic_overlap
from protean.nodes.registry import NODES
from protean.runtime import (
    firing,
    observations,
    outcomes,
    predictions,
    projections,
    terminal,
    triggers,
)
from protean.runtime.commit import CommitReceipt, commit
from protean.runtime.errors import SeatUnavailable
from protean.runtime.interrupts import MailboxPort, lift, requests_in
from protean.runtime.observations import WaveMerge
from protean.state.interrupts import interrupt_id
from protean.runtime.journal import append as journal_append
from protean.runtime.journal import journalled_calls as journalled_call_entries
from protean.runtime.journal import restorable_calls, start_tick
from protean.runtime.paths import SEMANTIC_SUFFIX, BrainPaths, TaskPaths
from protean.runtime.seat import (
    OUTCOME_DECODE_RETRY,
    HabitFacts,
    IllegalReturn,
    MemberUnfinished,
    SeatDecodeError,
    SeatLayer,
    SeatSelection,
    TickCalls,
    TickSpawns,
    build_request,
    calls_of,
    decode_seat_result,
    habit_of,
    spawn_desk_of,
    tick_calls_of,
)
from protean.state.calls import FiringDecision
from protean.state.brain_state import BrainState
from protean.state.enums import (
    Addressee,
    CallType,
    EpisodeKind,
    EventName,
    GoalStatus,
    InterruptKind,
    NodeName,
    Raiser,
    SelectionDecision,
    TerminalState,
    Tier,
    UnitStatus,
)
from protean.state.interrupts import Interrupt, InterruptRequest, OpenInterrupt
from protean.state.outputs import HomeostasisReport
from protean.state.records import (
    OUTPUT_CALL_NUMBER,
    EpisodeRecord,
    GoalSnapshot,
    JournalEntry,
    TraceRecord,
    UnitSnapshot,
)
from protean.state.habit_hits import HabitHit, append_habit_hit
from protean.state.seat_calls import SeatCallRecord, spend_tokens
from protean.state.semantic import SemanticChunk, load_stores
from protean.state.seats import (
    DirectorDirection,
    ExecutorSummary,
    ManagerPlan,
    ManagerReply,
    ThinkResult,
    WaveMember,
)

#: The hippocampus weights key that sizes the episode projection.
WEIGHT_CANDIDATE_WINDOW = "candidate_window"

#: The hippocampus weights key that sizes the **semantic** projection, beside it (build 2, S-25).
#: Both live here rather than in the node module because both size a *loader*, not a score: the
#: node never sees a window, it sees the slice.
WEIGHT_SEMANTIC_WINDOW = "semantic_window"

#: The seat call's own `call#`. A tick makes **one** seat call and a node's own output entry
#: holds the reserved `0`, so the seat's call numbers 1 exactly as a node's first think does
#: (§ Deliverable 6, folded: S-A76).
SEAT_CALL_NUMBER = 1

#: **The dispatch wave's own `call#`** (`the build specification (not in this mirror)` § Deliverable 4,
#: folded: A1-1, folded: S-A2). A wave is **one call**: it takes one `call#` at the cortex, the
#: one after the seat call that produced the plan, and its members take `member#` sub-keys
#: beneath it. The counter advances once per wave and the ordering inside it is fixed before
#: anything starts, so `call#` ordering is well-defined however the members are later run —
#: which is what leaves "whether and how members run concurrently" to build A.1.i.
WAVE_CALL_NUMBER = SEAT_CALL_NUMBER + 1

#: `member#` numbers from 1, in the order the `ManagerPlan` lists its members, which is the
#: order the runtime hands them to the seam.
FIRST_MEMBER_NUMBER = 1

#: The two reasons a tier-three fault refuses under, in the shape build 2's `SeatUnavailable`
#: takes them. § Deliverable 4 splits the refusal classes by **who was called** rather than by
#: what went wrong, so the reason is the fact and the class is the addressee's.
REASON_ILLEGAL_RETURN = "illegal_return"
REASON_MEMBER_FAULT = "call_failed"
#: A `dispatch` member whose `unit_id` names no unit in `state.units`, refused in `run_wave` after
#: the restore arm and before the desk, so no process is created
#: (`the build specification (not in this mirror)` § Deliverable 7) — one more reason under the class that
#: already exists, never a class of its own.
REASON_NO_UNIT = "no_unit"

#: The payload key a delegate call names its subagent kind in. Read as a mapping rather than
#: imported: `runtime/` may not import `protean.cortex`, where the payload models live (D5-2).
CALL_KIND_KEY = "kind"

#: Build 1's flat token-key suffix. **The boundary no longer sums this way** — build 2's S-19
#: rule is `protean.state.seat_calls.spend_tokens()`, which counts the per-iteration sum and
#: leaves `cache_read_input_tokens` out of spend. Kept because it is build 1's stated reading of
#: an envelope with no per-iteration breakdown and `tests/runtime/test_seat_port.py` pins it.
TOKEN_KEY_SUFFIX = "tokens"


@dataclass(frozen=True, slots=True)
class TickContext:
    """Everything a tick needs that is not `BrainState`."""

    paths: TaskPaths
    root: Path
    folders: Mapping[NodeName, NodeFolder]
    layer: SeatLayer
    seed_hashes: Mapping[str, str]
    workspace_path: str = ""
    mailbox: MailboxPort | None = None
    revision: int = 0
    #: The members this run's escalate replies **proposed** and no manager has ruled on yet
    #: (§ Deliverable 3, folded: S-A33). A pre-cortex proposal reaches **this** tick's wave; a
    #: director tick assembles no wave at all, so its proposals stay here and are offered to the
    #: next manager tick. It is the runtime's own buffer and not committed state: `BrainState` is
    #: contract 1, amended in exactly one way by this build, and none of it is a field.
    proposals: list[WaveMember] = field(default_factory=list)

    def weights(self, node: NodeName | str) -> Mapping[str, Any]:
        return self.folders[NodeName(node)].weights


@dataclass(slots=True)
class TickResult:
    """What one tick did — the artifact M5's cycle assertions read."""

    tick: int
    order: tuple[str, ...] = ()
    receipt: CommitReceipt | None = None
    committed_terminal: TerminalState | None = None
    losing_terminals: tuple[TerminalState, ...] = ()
    selection: SeatSelection | None = None
    seat_skipped: bool = False
    seat_restored: bool = False
    #: The P3 line this tick wrote, when a compiled procedure answered instead of the port
    #: (build 3, § Deliverable 4). `None` on every tick that called, skipped, refused or
    #: restored — which is what makes "matched a procedure" countable from the run itself and
    #: not only from the file the identity is checked against.
    habit_hit: HabitHit | None = None
    #: What this tick spent, over **every** call in it (§ Deliverable 7, folded: A1-4) — the
    #: number the boundary adds to `state.cost.tokens`, on the one `spend_tokens()` path with
    #: cache reads excluded.
    tokens: int = 0
    #: The tick's calls per addressee and its wave-member count, both **derived from the
    #: journal's call keys** rather than tallied beside them. They live here rather than on
    #: `BrainState`, which is contract 1 and gains no field in this build (§ Scaffold clause
    #: item 2): the journal is the committed home of the keys and this is the tick's own read
    #: of them.
    calls_by_type: Mapping[str, int] = field(default_factory=dict)
    wave_members: int = 0
    #: The CLI's own message when the seat call refused (build 2, decision 11). `None` on every
    #: tick that reached an envelope — including a skipped one, which made no call to refuse.
    seat_refusal: str | None = None
    journal_entries: int = 0
    #: The tick's single dispatch wave, as the manager assembled it — empty on a wave-less tick,
    #: which is a director tick, a vetoed tick and every tick builds 1–3 ran.
    wave: tuple[WaveMember, ...] = ()
    #: `complete` · `partial` · `conflicted`, or `None` when no wave ran (§ Deliverable 3).
    wave_status: str | None = None
    #: Whether the whole wave was restored from the journal rather than re-run (§ Deliverable 6).
    wave_restored: bool = False
    #: The proposals still buffered at the tick's end — a director tick's, waiting for the next
    #: manager tick.
    proposals: tuple[WaveMember, ...] = ()
    raised: tuple[str, ...] = ()
    #: Every outer node's cheap-check answer this tick, in `NODE_ORDER` (§ Deliverable 1, C3).
    #: The declining ones also ride the journal at `call# = 0`; a node that **fired** has no
    #: journal carrier for its decision, so this is the tick's own read of what was asked and
    #: answered. Minting the prediction from it is order W7's.
    firing: tuple[FiringDecision, ...] = ()
    predictions: tuple[TraceRecord, ...] = field(default_factory=tuple)
    outcomes: tuple[TraceRecord, ...] = field(default_factory=tuple)


def windowed_chunks(root: Path, state: BrainState, window: int) -> list[SemanticChunk]:
    """The top-`window` seeded chunks by term overlap with the live goal and unit text (S-15).

    The boundary loader's second half, and the same shape as its first: `recent_episodes` reads
    `episodes.jsonl` and keeps the last `candidate_window`; this reads `brain/semantic/*.jsonl`
    and keeps the best `semantic_window`. **A runtime narrowing, not a filter in a node** — the
    node is handed the slice and scores what it is handed, so the fetch stays where every other
    fetch in the build is and `src/protean/nodes/` still opens no file.

    The ranking function is the node's own `semantic_overlap`, imported rather than restated:
    if the loader narrowed on one measure and the node scored on another, a chunk could be
    dropped by the window and still have out-scored one the window kept.

    Three shapes return empty rather than refusing, because all three are ordinary: a window of
    zero or less (the key is absent, so the feature is off), a root with no `brain/semantic/`
    (a checkout on which `protean intake` has never run), and a store directory with no files.
    """
    if window <= 0:
        return []
    store_dir = BrainPaths(root=root).semantic
    if not store_dir.is_dir():
        return []
    stores = sorted(store_dir.glob(f"*{SEMANTIC_SUFFIX}"))
    if not stores:
        return []
    query = live_terms(state.goals, state.units)
    ranked = sorted(
        load_stores(stores),
        key=lambda chunk: (-semantic_overlap(chunk.terms, query), chunk.chunk_id),
    )
    return ranked[:window]


def _output_entry(
    state: BrainState,
    node: NodeName,
    *,
    tier: Addressee | None = None,
    output: Any = None,
) -> JournalEntry:
    """A node's **own** output entry, at the reserved `call# = 0` (§ Deliverable 6).

    Every node writes exactly one of these every tick, whatever else it did: it is build 1's
    per-node entry, keeping its place under the generalized key. A skipped node's
    `FiringDecision` rides it as `output` (order W6's), and the cortex's carries the decoded
    seat result and the addressee that produced it.
    """
    return JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task=state.task_id,
        tick=state.tick,
        node=node,
        call_number=OUTPUT_CALL_NUMBER,
        tier=tier,
        output=output,
    )


def _call_entry(
    state: BrainState,
    node: NodeName,
    *,
    call_number: int,
    tier: Addressee,
    payload: Mapping[str, Any] | None = None,
    payload_model: str = "",
    kind: str = "",
    block_ref: str = "",
    envelope: Any = None,
    member_number: int | None = None,
) -> JournalEntry:
    """One call's entry, written **once, at return** (§ Deliverable 4's table, folded: S-A50).

    It carries the addressee, the request payload, the kind and the block reference beside the
    returned envelope — "what a re-invoke needs, and nothing more"; the argv, the effective caps
    and the usage are the receipt's. `envelope=None` is a call that returned a **refusal**:
    journalled and counted, with no result for a replay to restore.
    """
    return JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task=state.task_id,
        tick=state.tick,
        node=node,
        call_number=call_number,
        member_number=member_number,
        tier=tier,
        payload=dict(payload or {}),
        payload_model=payload_model,
        kind=kind,
        block_ref=block_ref,
        envelope=envelope,
    )


def _projected(
    context: TickContext,
    state: BrainState,
    name: NodeName,
    weights: Mapping[str, Any],
    *,
    summary: ExecutorSummary | None,
    wave: WaveMerge | None,
    vetoed_unit_id: str | None,
) -> Any:
    """One outer node's read slice, assembled before anything at its step runs.

    Build 1 assembled each node's projection inside its own branch, immediately before its body.
    **A.1 needs it one step earlier**: the node's cheap check is a function of this projection and
    its weights (§ Deliverable 1), and the check decides whether the step does any work at all —
    so the slice has to exist before the calls and the body, not between them. Nothing else about
    the five projections moved.
    """
    if name is NodeName.HOMEOSTASIS:
        return projections.homeostasis_input(state, weights)
    if name is NodeName.HIPPOCAMPUS:
        window = int(weights.get(WEIGHT_CANDIDATE_WINDOW, 0))
        return projections.hippocampus_input(
            state,
            weights,
            recent_episodes(context.paths.episodes, window),
            windowed_chunks(
                context.root, state, int(weights.get(WEIGHT_SEMANTIC_WINDOW, 0))
            ),
        )
    if name is NodeName.THALAMUS:
        return projections.thalamus_input(state, weights, state.latest.hippocampus)
    if name is NodeName.BASAL_GANGLIA:
        return projections.basal_ganglia_input(
            state, weights, state.latest.thalamus, context.workspace_path
        )
    # **Against a partial or a conflicted observation the monitor grades no `expected` predicate
    # at all** (§ Deliverable 3): the unit stays `PENDING` and the mismatch streak is untouched,
    # so an absence never scores as a unit mismatch and one disagreement never scores as a
    # failure. The merged summary is still committed to `latest.dispatch` — the conflict reaches
    # the manager as a signal at its next step — it is just not handed to the grader.
    graded_summary = (
        summary
        if wave is None or wave.status not in observations.SUPPRESSING_WAVE_STATUSES
        else None
    )
    payload = projections.monitor_input(
        state,
        weights,
        executor_summary=graded_summary,
        vetoed_unit_id=vetoed_unit_id,
    )
    if wave is not None:
        # `wave_status` is `MonitorInput`'s one added field and `projections` is another order's
        # module, so the runtime fills it here, where the wave is in hand.
        payload = payload.model_copy(update={"wave_status": wave.status})
    return payload


def _inhibit(desk: TickCalls, call_type: CallType) -> None:
    """Tell the desk not to issue this call type for the rest of the tick, if it can hear it.

    Read through the accessor the desk publishes rather than by importing `protean.cortex`,
    which `runtime/` may not do — the same rule `_calls_made()` follows one accessor over. A
    desk without it issues what it planned, which is every desk build 1, 2 and 3 opened.
    """
    inhibit = getattr(desk, "inhibit", None)
    if inhibit is not None:
        inhibit(call_type)


def _calls_made(desk: TickCalls, node: NodeName) -> tuple[Any, ...]:
    """The records the desk kept for this node's calls this tick, in `call#` order.

    **The desk holds the records and the runtime journals them** — W2 landed the desk saying so
    in as many words. It is read through the accessor the desk publishes rather than by
    importing `protean.cortex`, which `runtime/` may not do; a desk without the accessor is read
    as having made no call, exactly as a layer without the seam is.
    """
    reader = getattr(desk, "calls_for", None)
    return () if reader is None else tuple(reader(node))


def _entry_for(
    state: BrainState, node: NodeName, made: Any, spawns: Any | None = None
) -> JournalEntry:
    """One `CallRecord` from the desk → the journal entry for that call.

    A refused call's entry carries **no envelope** even when the refusal came with one (an
    illegal return): the replay's condition is a *restorable* result, and a shape the decoder
    already refused is not one.

    **A delegate's entry names its containment, where this passed none at all**
    (`the build specification (not in this mirror)` § Deliverable 6, folded: S-i51): `kinds.delegate.
    <name>`, read off the tick's spawn desk by the journal's own key, so a delegate's entry says
    under what block it ran exactly as a member's does. The reference is `KindBlock.block_ref`'s and
    is minted nowhere else — which is why it is **read off the desk** through the accessor, on
    `_calls_made()`'s own `getattr` precedent, rather than spelled here: `protean.runtime` may not
    import `protean.cortex`. A layer without the fifth seam resolved no block, so its delegate's
    entry carries `""` exactly as A.1 left it.
    """
    call = made.call
    payload = dict(call.payload)
    return _call_entry(
        state,
        node,
        call_number=call.call_number,
        tier=call.addressee,
        payload=payload,
        payload_model=call.payload_model,
        kind=str(payload.get(CALL_KIND_KEY, "")),
        block_ref=_block_ref_of(spawns, (str(node), call.call_number, None)),
        envelope=None if made.refused else made.envelope,
    )


def _block_ref_of(spawns: Any | None, key: tuple[str, int, int | None]) -> str:
    """`kinds.<class>.<name>` for this journal key, off the tick's desk — or `""`.

    Read through the accessor the desk publishes rather than by importing `protean.cortex`, which
    `runtime/` may not do: a desk without the accessor, and a layer without the seam, are both read
    as having resolved no block, exactly as a desk without `calls_for` is read as having made no
    call. **The string is the desk's; nothing here mints one** (folded: S-i51).
    """
    reader = None if spawns is None else getattr(spawns, "block_refs_of", None)
    if reader is None:
        return ""
    return str(reader().get(key, ""))


def dispatch_id_of(task: str, tick: int, call_number: int) -> str:
    """The wave's own id, minted from its key and carried on **the receipt** alone.

    `the build specification (not in this mirror)` § Deliverable 3, "Where `dispatch_id` lives"
    (folded: S-A14, folded: S-A73): on the `SeatCallRecord` and **never on `UnitObservation`**,
    which is a forbid-extras model carrying no version key of its own and is untouched by this
    build. A committed observation joins to the call that produced it by the tick's own
    `(node, call#)` keys, which the journal already carries — so the id is a pure function of
    that key rather than a value anything has to thread through the tick.
    """
    return f"{task}-t{tick}-c{call_number}"


def _member_raises(
    returns: Sequence[tuple[int, ExecutorSummary | None]], call_number: int
) -> list[tuple[InterruptRequest, str, int, int | None]]:
    """Each member's own `interrupt`, with the components its widened id is minted from.

    **Interrupts are not merged at all** (§ Deliverable 3, folded: S-A52): each member raises its
    own under its own `(task, tick, node, raiser, call#, member#)` id, which is the whole reason
    the id widened — two members of one wave would otherwise collapse onto one filename and lose
    a question in silence.
    """
    raised: list[tuple[InterruptRequest, str, int, int | None]] = []
    for member_number, result in sorted(returns, key=lambda item: item[0]):
        if result is not None and result.interrupt is not None:
            raised.append(
                (result.interrupt, str(NodeName.CORTEX), call_number, member_number)
            )
    return raised


def _call_raises(
    made: Sequence[Any], node: NodeName
) -> list[tuple[InterruptRequest, str, int, int | None]]:
    """Every interrupt a node's own calls raised this tick, with their id components.

    A call-bearing raiser's id carries the **calling node**, because a call type is a raiser
    every outer node shares: the hippocampus's think and the thalamus's think in one tick would
    otherwise write one file between them (§ Scaffold clause item 2, contract 4).
    """
    raised: list[tuple[InterruptRequest, str, int, int | None]] = []
    for record in made:
        result = getattr(record, "result", None)
        request = getattr(result, "interrupt", None)
        if isinstance(request, InterruptRequest):
            raised.append((request, str(node), record.call.call_number, None))
    return raised


def _proposed_in(made: Sequence[Any]) -> list[WaveMember]:
    """The members a node's escalate replies **proposed** this tick, in call order.

    § Deliverable 3: "An escalate reply to a **pre-cortex** node **proposes** members for that
    tick's wave, and the manager includes or drops each proposal at its own step. **An escalate
    reply never authorizes a member**" — so they are buffered here and nothing is dispatched
    until the manager's own step, which is the whole mechanical content of the sentence.
    """
    proposed: list[WaveMember] = []
    for record in made:
        result = getattr(record, "result", None)
        if isinstance(result, ManagerReply):
            proposed.extend(result.proposed)
    return proposed


def _wave_entry(
    state: BrainState,
    member: WaveMember,
    *,
    member_number: int,
    envelope: Any,
    spawns: Any | None = None,
) -> JournalEntry:
    """One member's journal entry, under the wave's one `call#` and its own `member#`.

    **`block_ref` is the block the desk resolved** — `kinds.<class>.<name>`, where A.1 wrote the bare
    kind name (§ Deliverable 6, folded: S-i12). `kind` stays the bare name, being the one licensed
    duplicate, so the change is one of **value** and not of field set and no version but the
    receipt's moves. A scripted layer resolved no block and carries `""`: the column says under what
    containment the member ran, and a scripted member ran under none.
    """
    return _call_entry(
        state,
        NodeName.CORTEX,
        call_number=WAVE_CALL_NUMBER,
        member_number=member_number,
        tier=CallType.DISPATCH,
        payload=member.model_dump(mode="json"),
        payload_model=type(member).__name__,
        kind=member.kind,
        block_ref=_block_ref_of(
            spawns, (str(NodeName.CORTEX), WAVE_CALL_NUMBER, member_number)
        ),
        envelope=envelope,
    )


def run_wave(
    context: TickContext,
    state: BrainState,
    members: Sequence[WaveMember],
    *,
    restorable: Mapping[tuple[str, int, int | None], JournalEntry],
    order: Sequence[int] | None = None,
    spawns: TickSpawns | None = None,
) -> tuple[list[JournalEntry], list[tuple[int, ExecutorSummary | None]], bool]:
    """The tick's single dispatch wave: one call, `member#` sub-keys, buffered writes.

    Returns the wave's journal entries **in `member#` order**, its returns, and whether the
    whole wave was restored from the journal rather than run.

    **A wave is the replay unit** (§ Deliverable 6, folded: S-A2): it restores only if **every**
    member carries a restorable return, and otherwise the whole wave re-runs and its already
    returned members' observations are discarded — the workspace is re-observed, never
    re-trusted.

    **The entries are buffered and written in `member#` order after the last member returns**
    (folded: S-A77), so the journal's line order is the wave's order rather than the completion
    order, which is what makes G7's byte-identity claim reachable at all. `order` is the order
    the members are **run** in — `None` is the plan's own, and **what fills it is build A.1.i's**,
    which is exactly why the keys are assigned before anything starts.

    **Any fault on a `dispatch` member is `SeatUnavailable` to the boundary** (§ Deliverable 4):
    the tick completes and the terminal is `stopped`. A member that returned nothing legal is a
    failed member and the wave merges `partial`; that is the caller's read of the returns.

    **`spawns` is A.1.i's fifth seam, and the wave goes to the desk through it**
    (`the build specification (not in this mirror)` § Deliverable 4): the desk checks the bounds over
    the members **before the first spawn**, runs them concurrently one port instance and one
    thread each, kills a member that crosses its own wall cap, and joins only after every member
    has returned or been killed. It answers each member's envelope or that member's own fault as
    a value, so the classification below is **one block for both paths** and no catch is added to
    it: the three pre-process refusals are raised from the desk as `SeatUnavailable`, which this
    function already lets through to the boundary, and a member's `CallCapExceeded` or timeout
    arrives as the `MemberUnfinished` the landed catch already reads. **The landed per-member port
    loop stays for a layer without the seam** (row M3), which is every scripted layer.

    **On the seam path each member's unit is looked up by that member's own `unit_id`**
    (`the build specification (not in this mirror)` § Deliverable 7): after the restore arm — a wave that
    restores whole spawns nothing and needs no unit — and before the desk is called, in
    `state.units`, per member and never once per wave, because the one-unit property is enforced
    only over the returns. A member naming no unit refuses as `SeatUnavailable` under
    `REASON_NO_UNIT`: no process is created, the tick completes `stopped` and a checkpoint is
    written. The found intents reach the desk as `units=`, each member's unit id mapped to its
    unit's `intent`, and each member's prompt carries its own as a third part. So the sent prompt
    is reconstructable from the seat-call receipt's recorded `argv`, and not from the checkpoint
    alone: a re-plan replaces the unit in the checkpoint, which holds only its current revision,
    and the delimiter is a code literal outside `seed_hashes()`. The landed per-member port loop
    spawns no process and assembles no prompt, so it takes no lookup.
    """
    numbered = list(enumerate(members, start=FIRST_MEMBER_NUMBER))
    keys = [(str(NodeName.CORTEX), WAVE_CALL_NUMBER, number) for number, _m in numbered]
    restored = [restorable.get(key) for key in keys]
    if numbered and all(entry is not None for entry in restored):
        returns = [
            (number, _decoded_member(state, entry))
            for (number, _member), entry in zip(numbered, restored)
        ]
        return [entry for entry in restored if entry is not None], returns, True

    run_order = list(order) if order is not None else [number for number, _m in numbered]
    by_member = {number: member for number, member in numbered}
    buffered: dict[int, JournalEntry] = {}
    returns_by_member: dict[int, ExecutorSummary | None] = {}
    units: dict[str, str] = {}
    if spawns is not None:
        known = {unit.id: unit.intent for unit in state.units}
        for number, member in numbered:
            if member.unit_id not in known:
                raise SeatUnavailable(
                    tier=str(CallType.DISPATCH),
                    reason=REASON_NO_UNIT,
                    message=(
                        f"member {number} ({member.kind}) names unit {member.unit_id!r}, which "
                        f"is not among the checkpoint's units — no process was created"
                    ),
                )
            units[member.unit_id] = known[member.unit_id]
    # The whole wave, at the desk, before the first member is classified — or `None`, which is the
    # landed per-member port loop below. A refusal from here is the wave's own and is raised, not
    # returned: an over-wide wave, a wave whose caps sum above the bound, a kind the seed does not
    # define and a desk with no workspace are all `SeatUnavailable` and all reach the boundary
    # through the arm this function already has for that class.
    spawned = (
        None
        if spawns is None
        else spawns.dispatch_wave(
            by_member,
            node=str(NodeName.CORTEX),
            call_number=WAVE_CALL_NUMBER,
            order=run_order,
            units=units,
        )
    )
    for member_number in run_order:
        member = by_member[member_number]
        try:
            if spawned is None:
                envelope = context.layer.port(CallType.DISPATCH, member)
            else:
                envelope = spawned[member_number]
                if isinstance(envelope, BaseException):
                    # The desk's own re-raise, handed over as a value so that the three named
                    # faults stay this function's to classify (folded: S-i41).
                    raise envelope
            decoded = decode_seat_result(CallType.DISPATCH, envelope, state.tick).model_copy(
                update={"tick": state.tick}
            )
        except (MemberUnfinished, TimeoutError):
            # The third refusal class: a cap exceeded or a timeout marks **this member** failed
            # and the wave `partial`; the tick does not stop. The member is still journalled and
            # counted — with no envelope, so its burn is visible and a replay re-runs the wave.
            buffered[member_number] = _wave_entry(
                state, member, member_number=member_number, envelope=None, spawns=spawns
            )
            returns_by_member[member_number] = None
            continue
        except (SeatUnavailable, IllegalReturn):
            raise
        except (SeatDecodeError, LookupError) as fault:
            # **Any fault on a `dispatch` member is `SeatUnavailable` to the boundary** — no
            # configuration, an illegal return, a call failure alike (§ Deliverable 4). The tick
            # completes and the terminal is `stopped`; it is not an advisory refusal, because a
            # dispatch is the tick's own work rather than a node's question.
            #
            # **The three named faults and no more.** Anything else propagates, because a
            # process that died mid-wave is not a fault the runtime caught — it leaves no
            # checkpoint, and the replay is what handles it (§ Deliverable 6). A catch-all here
            # would turn a torn pass into a committed `stopped` one.
            raise SeatUnavailable(
                tier=str(CallType.DISPATCH), reason=REASON_MEMBER_FAULT, message=str(fault)
            ) from fault
        buffered[member_number] = _wave_entry(
            state, member, member_number=member_number, envelope=envelope, spawns=spawns
        )
        returns_by_member[member_number] = decoded
    # The buffer is what makes the line order the wave's rather than the completion order.
    entries = [buffered[number] for number, _member in numbered if number in buffered]
    returns = [(number, returns_by_member.get(number)) for number, _member in numbered]
    return entries, returns, False


def _decoded_member(state: BrainState, entry: JournalEntry) -> ExecutorSummary | None:
    """One restored member entry → its `ExecutorSummary`, on the one decode path."""
    if entry.envelope is None:
        return None
    decoded = decode_seat_result(CallType.DISPATCH, entry.envelope, state.tick)
    return decoded.model_copy(update={"tick": state.tick})


def _receipts(
    entries: Sequence[JournalEntry],
    facts: Sequence[Any],
    *,
    refs: Mapping[str, str],
    task: str,
    tick: int,
    answered_by_habit: tuple[str, int, int | None] | None = None,
    spawns: TickSpawns | None = None,
) -> list[SeatCallRecord]:
    """One `SeatCallRecord` per journalled call of the committing pass — restored or live.

    § Deliverable 6 (folded: S-A8). A torn tick committed nothing, so its calls have no record
    yet; writing one per *journalled* call is what makes each real invocation appear exactly
    once however many boundaries the tick took to reach. The adapter's facts fill the receipt's
    own columns where this pass produced them and are simply absent on a restored call.

    **A retry is its own line and the journal has no entry for it** (folded: S-8, folded: S-A8):
    the first attempt of a retried call is `decode_retry` and only the attempt that returned is
    journalled, so a retry's facts are emitted under the same key with the outcome that keeps
    them apart — and are absent after a replay, which is the one place a replayed commit and a
    live one differ.

    **A habit-answered call writes a P3 `HabitHit` instead** (`the build specification (not in this mirror)`
    § Deliverable 4). Build 3's P1–P5 are untouched by A.1 (§ Scaffold clause item 2), so the
    one call an answered procedure stood in for is journalled — a replay must not re-make it —
    and is not a receipt.

    **A second read lands beside `calls_of()`, and it is keyed rather than positional**
    (`the build specification (not in this mirror)` § Deliverable 6, folded: S-i23, folded: S-i42). A
    spawn's facts belong to a **per-spawn** port instance the desk built, so `calls_of()` — which
    reports the single construction-time instance's invocations — never sees them at all
    (folded: S-i4). The tick's one `spawn_desk_of()` is resolved **once**, at the top of the tick,
    and `spawns_of()` is read here **once**: every journalled entry's spawn facts are looked up by
    the journal's own key `(node, call#, member#)`.

    **The FIFO match below stays exactly as it is for `calls_of()`** — seats, think and escalate —
    because reading the spawn facts positionally is what breaks: the landed match would meet a
    **pre-cortex delegate's** entry with a later `dispatch` fact and write that entry empty. A key
    the desk holds no facts for falls through to the FIFO unchanged, which is every delegate on a
    layer without the fifth seam and every tick builds 1, 2 and 3 ran.
    """
    pending = list(facts)
    spawned = {} if spawns is None else dict(spawns.spawns_of())
    records: list[SeatCallRecord] = []
    for entry in entries:
        key = (str(entry.node), entry.call_number, entry.member_number)
        if key == answered_by_habit:
            continue
        spawn_facts = spawned.get(key)
        if spawn_facts is not None:
            records.append(_receipt(entry, spawn_facts, refs=refs, task=task, tick=tick))
            continue
        matched = None
        while pending and str(pending[0].tier) == str(entry.tier):
            fact = pending.pop(0)
            if fact.outcome == OUTCOME_DECODE_RETRY:
                records.append(_receipt(entry, fact, refs=refs, task=task, tick=tick))
                continue
            matched = fact
            break
        records.append(_receipt(entry, matched, refs=refs, task=task, tick=tick))
    return records


def _receipt(
    entry: JournalEntry,
    facts: Any | None,
    *,
    refs: Mapping[str, str],
    task: str,
    tick: int,
) -> SeatCallRecord:
    """The journal's key and kind, plus the adapter's columns when this pass produced them.

    `ref` is the cortex prediction this call belongs to, and it is `None` for every call that is
    not the seat's: think, escalate and delegate mint no cortex prediction (folded: S-A9), so
    the calling node's own one prediction is never contended for by N calls.
    """
    return SeatCallRecord.from_call(
        facts,
        task=task,
        tick=tick,
        node=entry.node,
        call_number=entry.call_number,
        member_number=entry.member_number,
        tier=entry.tier,
        kind=entry.kind,
        # **`dispatch_id` is receipt-only** and names the wave this member belonged to
        # (§ Deliverable 3, folded: S-A14). Every other call carries none: there is no dispatch
        # to name.
        dispatch_id=(
            dispatch_id_of(task, tick, entry.call_number)
            if entry.tier is CallType.DISPATCH
            else ""
        ),
        ref=(
            refs.get(str(entry.tier))
            if entry.node is NodeName.CORTEX and entry.envelope is not None
            else None
        ),
        outcome=None if facts is not None else ("ok" if entry.envelope is not None else "unavailable"),
    )


def _tokens_in(usage: Mapping[str, Any]) -> int:
    """Build 1's flat sum over every counter whose key ends in `tokens`.

    **Superseded at the boundary by `spend_tokens()`** (build 2, folded: S-19): this one counts
    `cache_read_input_tokens` as spend, which bills a cache hit at the price of a miss. It is
    kept, unchanged, because it is build 1's own reading and its pinning tests are outside order
    W3's writable set.
    """
    total = 0
    for key, value in usage.items():
        if str(key).endswith(TOKEN_KEY_SUFFIX) and isinstance(value, int):
            total += value
    return total


def _spend_of(entry: JournalEntry) -> int:
    """One journalled call's spend, on the one spend path (§ Deliverable 7, folded: A1-4).

    `protean.state.seat_calls.spend_tokens()` is **the** rule and this is a read of it, never a
    second copy: the per-iteration sum of input + cache-creation + output tokens, with
    `cache_read_input_tokens` left out exactly as build 2 ruled (folded: S-19). An entry with no
    envelope is a call that returned a **refusal** — journalled and counted as a call, and spent
    nothing the runtime can see, so it contributes zero rather than being skipped.
    """
    return 0 if entry.envelope is None else spend_tokens(entry.envelope.usage)


def calls_by_type(entries: Sequence[JournalEntry]) -> dict[str, int]:
    """The tick's calls per addressee, **derived from the journal's call keys**.

    § Deliverable 7: "the tick's counters — calls per type, wave members — are derived from the
    journal's call keys, so the two cannot drift". A tally kept beside the journal would be a
    second version of one fact; this is a read of the entries the tick actually wrote, so a call
    the journal does not hold cannot be counted and one it holds cannot be missed.
    """
    counters: dict[str, int] = {}
    for entry in entries:
        if not entry.is_call():
            continue
        key = str(entry.tier)
        counters[key] = counters.get(key, 0) + 1
    return counters


def wave_members_in(entries: Sequence[JournalEntry]) -> int:
    """How many wave members the tick ran, off the same keys — the `member#` sub-keys.

    **No width is bounded here and none is implied** (§ Out of scope): bounding a wave before it
    starts is build A.1.i's, and this counts what a tick did rather than limiting what it may do.
    """
    return sum(1 for entry in entries if entry.is_call() and entry.member_number is not None)


def _ceiling_report(context: TickContext, state: BrainState) -> HomeostasisReport:
    """Homeostasis's own ceiling function, run against `state.cost` as it stands.

    **The boundary's half of "run twice in the tick, yielding one stop"** (§ Deliverable 7). The
    node's own step is the first run, against the cost the tick opened on; this is the second,
    against the spend the tick accumulated — which is the only reading that can see a ceiling
    crossed *by this tick's own calls*. It is **the same callable** — `homeostasis.run` is what
    `NODES` holds for that name — so there is one ceiling arithmetic and not two, and
    `effective_ceilings()` is read here exactly as the node reads it.

    **It is not reached through `NODES`, and that is the point**: the registry is the tick's node
    dispatch table, so a call through it *is* a node step, and contract 5's recorded sequence —
    every node once, in `config.NODE_ORDER` — would hold a seventh entry. The node ran once; the
    runtime read its pure function a second time, which is a different act and is named as one.

    It is called **before** the tick and error tallies move, so ticks and the error rate are the
    same numbers the node's step saw and only the spend differs: § Deliverable 7's "what does not
    change" keeps the ceilings, the narrowing rule, `resume --extend` and the terminal as they
    are, and a re-evaluation that moved `max_ticks` a tick earlier would be changing one.
    """
    weights = context.weights(NodeName.HOMEOSTASIS)
    return homeostasis_node.run(projections.homeostasis_input(state, weights))


def _goal_of(state: BrainState, unit_id: str | None) -> str | None:
    for unit in state.units:
        if unit.id == unit_id:
            return unit.goal_id
    return None


def _mark_progress(state: BrainState, goal_id: str | None) -> None:
    if goal_id is None:
        return
    for goal in state.goals:
        if goal.id == goal_id:
            goal.last_progress_tick = state.tick


def apply_manager(state: BrainState, plan: ManagerPlan, selection: SeatSelection) -> None:
    """Merge a plan into state: units keep their ids, `revision` increments instead.

    A unit that took a fresh id on every re-plan would reset its trap windows and make the
    ladder's upper rungs unreachable (decision 28), so the merge is by id.
    """
    existing = {unit.id: unit for unit in state.units}
    for unit in plan.units:
        previous = existing.get(unit.id)
        if previous is None:
            state.units = [*state.units, unit]
        else:
            merged = unit.model_copy(update={"revision": previous.revision + 1})
            state.units = [merged if item.id == unit.id else item for item in state.units]

    for goal_id in plan.goals_satisfied:
        for goal in state.goals:
            if goal.id == goal_id:
                goal.status = GoalStatus.SATISFIED
                goal.last_progress_tick = state.tick

    if plan.units and selection.escalation is not None:
        replanned = _goal_of(state, plan.units[0].id) or plan.units[0].goal_id
        for goal in state.goals:
            if goal.id == replanned and selection.unit_id is not None:
                goal.replan_count += 1

    if plan.trap_dismissed and selection.unit_id is not None:
        dismissals = dict(state.trap_dismissals.get(selection.unit_id, {}))
        for detector in plan.trap_dismissed:
            dismissals[str(detector)] = state.tick
        state.trap_dismissals = {**state.trap_dismissals, selection.unit_id: dismissals}


def apply_director(state: BrainState, direction: DirectorDirection) -> None:
    """Goal-stack edits, constraints and modulator fields — the only slice a director writes."""
    if direction.goals_pushed:
        state.goals = [*state.goals, *direction.goals_pushed]
    for goal_id in direction.goals_closed:
        for goal in state.goals:
            if goal.id == goal_id:
                goal.status = GoalStatus.SATISFIED
                goal.last_progress_tick = state.tick
    if direction.constraints:
        state.constraints = [*state.constraints, *direction.constraints]
    if direction.modulators is not None:
        state.modulators = direction.modulators
    if direction.redirect_of is not None:
        for goal in state.goals:
            if goal.id == direction.redirect_of:
                goal.redirect_count += 1


def _episode(state: BrainState, verdict) -> EpisodeRecord:
    """The tick's `EpisodeRecord`, composed by the runtime from committed state."""
    return EpisodeRecord(
        schema_version=config.EPISODE_SCHEMA_VERSION,
        episode_id=episode_id(state.task_id, state.tick),
        task=state.task_id,
        tick=state.tick,
        kind=EpisodeKind.TICK,
        goals=[GoalSnapshot(id=goal.id, status=goal.status) for goal in state.goals],
        units=[UnitSnapshot(id=unit.id, status=unit.status) for unit in state.units],
        verdict=verdict,
        cost=state.cost,
    )


def _stuck_request(state: BrainState, goal, verdict) -> InterruptRequest:
    """The runtime's one licensed raise: kind `stuck`, carrying the evidence the operator rules on.

    "Which signals fired, on which units, for how many ticks" — the fired scalars come off the
    monitor's own verdict, each already carrying the weights key that scored it, so the body is
    rulable without reading any other file.
    """
    fired = [] if verdict is None else [
        scalar.model_dump(mode="json") for scalar in verdict.traps if scalar.fired
    ]
    return InterruptRequest(
        kind=InterruptKind.STUCK,
        raised_by=Raiser.RUNTIME,
        question=(
            f"the ladder is exhausted on goal {goal.id!r} ({goal.text!r}): "
            f"{goal.redirect_count} redirect(s) and no goal-stack progress for "
            f"{goal.no_progress_ticks(state.tick)} tick(s). How should it proceed?"
        ),
        evidence={
            "goal_id": goal.id,
            "redirect_count": goal.redirect_count,
            "replan_count": goal.replan_count,
            "no_progress_ticks": goal.no_progress_ticks(state.tick),
            "fired": fired,
        },
    )


def _seat_refusal_request(refusal: SeatUnavailable) -> InterruptRequest:
    """The one interrupt a refused seat call raises, carrying the CLI's message verbatim.

    `the build specification (not in this mirror)` § Deliverable 1 → *Failure is not an envelope*: the
    boundary "raises the mailbox interrupt carrying the CLI's own message verbatim". Verbatim
    is the contract — the runtime did not diagnose the failure and a paraphrase would be it
    pretending otherwise — so the message goes in `evidence` unedited and the question above it
    is the runtime's own, asking what to do rather than what happened.

    **It is the runtime's raise, on the one pair the runtime is licensed for.**
    `protean.state.interrupts` allows the runtime exactly `kind=stuck`, and a raise attributed
    to the tier instead would land its `operator_answer` outcome on a cortex-tier prediction that
    does not exist — the seat never answered, so it minted none — and the resume would refuse
    the trace append. The runtime's own raise resolves onto the cortex folder's **director**
    tier, which is what `predictions.synthetic_stuck()` exists to give a ref to (folded: T-7).
    The tier that actually refused is named in the question and in the evidence.
    """
    return InterruptRequest(
        kind=InterruptKind.STUCK,
        raised_by=Raiser.RUNTIME,
        question=(
            f"the {refusal.tier} seat refused this tick: {refusal.reason}. "
            f"The task is stopped with no envelope for the tick. "
            f"Retry it, change the seat's configuration, or abandon the task?"
        ),
        evidence={
            "tier": refusal.tier,
            "reason": refusal.reason,
            "exit_code": refusal.exit_code,
            "message": refusal.message,
        },
    )


def _event(state: BrainState, name: EventName, detail: dict[str, Any] | None = None) -> EpisodeRecord:
    return EpisodeRecord(
        schema_version=config.EPISODE_SCHEMA_VERSION,
        episode_id=episode_id(state.task_id, state.tick),
        task=state.task_id,
        tick=state.tick,
        kind=EpisodeKind.EVENT,
        event_name=name,
        detail=detail or {},
    )


def run_tick(
    context: TickContext,
    state: BrainState,
    *,
    replay: bool = False,
    extra_episodes: Sequence[EpisodeRecord] = (),
    extra_outcomes: Sequence[TraceRecord] = (),
    resolved_ids: Sequence[str] = (),
) -> TickResult:
    """Run every node once, in `config.NODE_ORDER`, then commit the boundary.

    `extra_outcomes`, `extra_episodes` and `resolved_ids` carry a resume's interrupt resolution
    into the **first boundary commit of the resumed run**, which is where § Deliverable 5 puts
    it — the `operator_answer` record, the `interrupt_resolved` event, and only then the file's
    deletion.
    """
    paths = context.paths
    result = TickResult(tick=state.tick)
    previous_latest = state.latest.model_copy(deep=True)
    started = time.monotonic()
    journal_path = paths.journal(state.tick)
    # The restore is read **before** the truncate. `start_tick` replaces this tick's journal —
    # the one artifact in the build that is not append-only, because it is not a resume point —
    # so a replay that consulted the file at the seat's own step would find it already empty and
    # § Deliverable 3's one named exception to idempotency-from-purity could never fire.
    #
    # **Two reads, because the replay's condition is a restorable result being present and not
    # an entry existing** (§ Deliverable 6, folded: S-A36). `journalled_before` is every call
    # the torn pass wrote; `restorable` is the subset carrying an envelope. An entry recording a
    # refusal or a timeout is in the first and not the second, which is exactly what re-invokes
    # that call in place while the journalled calls after it still restore.
    journalled_before = journalled_call_entries(journal_path) if replay else []
    restorable = restorable_calls(journal_path) if replay else {}
    start_tick(journal_path)
    # This tick's own call entries, in the order they were written — the receipt's source at the
    # boundary, because the rule is now one line per **journalled call** rather than per live
    # invocation (folded: S-A8).
    call_entries: list[JournalEntry] = []

    def write_entry(entry: JournalEntry) -> JournalEntry:
        """Append one journal entry, count it, and keep it — and its spend — if it is a call.

        **This is the per-call site the tick's cost accumulates at** (§ Deliverable 7,
        folded: A1-4). Build 1 incremented once, inside the seat branch, from the single
        envelope's usage; a tick holding N calls under-counted by N−1. Every call the tick makes
        passes through here exactly once, at return, so accumulating here is what makes "every
        call in the tick" mean the same set of calls the journal holds — the counters below are
        derived from these same entries, which is what leaves the two unable to drift.
        """
        nonlocal tokens_this_tick
        journal_append(journal_path, entry)
        result.journal_entries += 1
        if entry.is_call():
            call_entries.append(entry)
            tokens_this_tick += _spend_of(entry)
        return entry

    order: list[str] = []
    node_inputs: dict[str, Any] = {}
    #: The tick's spend, over **every** call in it — the seat's, every node's think, escalate
    #: and delegate, and every member of the wave — on the one `spend_tokens()` path.
    tokens_this_tick = 0
    summary: ExecutorSummary | None = None
    #: This tick's wave, merged — `None` on a wave-less tick, which is what the suppression rule
    #: keys off rather than off the summary's absence (§ Deliverable 3, folded: S-A69).
    wave: WaveMerge | None = None
    #: Every interrupt this tick's **calls** raised, with the components their widened ids are
    #: minted from: `(request, node, call#, member#)`. A node or the runtime raising on its own
    #: account is in `raised` below and keeps the three-part id.
    call_raises: list[tuple[InterruptRequest, str, int, int | None]] = []
    #: Every outer node's cheap-check answer this tick, in the order the ring asked for them.
    firing_decisions: list[FiringDecision] = []
    vetoed_unit_id: str | None = None
    redirect_marker: str | None = None
    selection: SeatSelection | None = None
    skip_seat = False
    seat_refusal: SeatUnavailable | None = None
    # Whether the port was **called** this tick. It is the guard on the boundary's read of the
    # `calls` seam and it is not the same question as `seat_restored`: a layer's `calls()`
    # reports the invocations of its last port call and is not cleared by a tick that makes
    # none, so a replay that read the seam unguarded would attach the previous tick's facts to
    # this tick's journalled calls. The **lines** come from the journal now; what the guard
    # protects is which adapter columns are true of this pass.
    port_called = False
    # The compiled procedure that answered this tick, if one did (build 3, P3). It is the
    # negation of `port_called` on a tick that reached the seat: the consult happens **before**
    # the port, so a match spawns nothing and appends nothing to `seat_calls.jsonl`. A replayed
    # tick consults nothing at all — it restores the journalled envelope — which is why this
    # stays `None` there and neither record is appended (row N5).
    habit: HabitFacts | None = None
    # The call key a compiled procedure answered, if one did. The boundary skips the receipt for
    # exactly that key: build 3's P3 rule — a habit answer is recorded as a `HabitHit` **instead
    # of** a `SeatCallRecord` — and P1–P5 are untouched by A.1 (§ Scaffold clause item 2). The
    # call is still journalled, because a replay must not re-make it.
    habit_key: tuple[str, int, int | None] | None = None
    # A.1's mid-tick edges (§ Deliverable 2, § Directional decisions 4): the desk one tick's
    # think, escalate and delegate calls are made through, opened from the layer's fourth
    # optional seam. `None` means the layer has no such seam, which is every tick build 1, 2 and
    # 3 ran. The desk is the **layer's** — a `cycle.py` that imported `protean.cortex` to build
    # one would invert the seam the whole build is built on — and `call#` is per node within
    # this tick, which is why it is opened here and not once per task.
    # A.1.i's fifth seam (`the build specification (not in this mirror)` § Deliverable 4, contract
    # I5): the desk this tick's tier-three spawns are opened on. Resolved **here, before the
    # node-call desk**, for one reason: the seam is memoized per `(task, tick)` and this is the
    # one place the tick's own workspace is in hand, so whichever of the two openers reaches the
    # desk first meets a desk that already carries `TickContext.workspace_path` — the only
    # channel a path reaches a spawn on (folded: S-i22). Resolving it **constructs** the desk and
    # refuses nothing: the two pre-process refusals belong to the open each opener performs
    # before its first spawn, so a tick with no wave and no delegate call spawns nothing, opens
    # nothing and refuses nothing. `None` is a layer without the seam, which is every scripted
    # layer and every tick builds 1, 2 and 3 ran (row M3).
    spawns: TickSpawns | None = spawn_desk_of(
        context.layer, state.task_id, state.tick, context.workspace_path
    )
    node_calls: TickCalls | None = tick_calls_of(context.layer, state.task_id, state.tick)
    # **The tick's running count of planned delegates** (`the build specification (not in this mirror)`
    # § Deliverable 1, the per-tick delegate bound): the call policy plans a delegate only while
    # this is under the bound the desk publishes, so the bound is applied in `NODE_ORDER`. It
    # lives within this tick and starts at zero; nothing carries it across ticks.
    delegates_planned = 0

    for node in config.NODE_ORDER:
        order.append(node)
        name = NodeName(node)

        if name is NodeName.CORTEX:
            workspace = projections.workspace(state)
            selection = context.layer.router(workspace)
            tier = Tier(selection.tier)
            if skip_seat:
                # The two skip conditions skip the seat **call**, never the routing and never
                # the tick: the node's own output entry records that the seat was reached and
                # made no call, and a call that was never made leaves no call entry at all.
                result.seat_skipped = True
                write_entry(_output_entry(state, name, tier=tier))
                continue

            # No work unit and no workspace path reach the request any more: a seat call is
            # the director's or the manager's, and a dispatch member is a `WaveMember` the
            # **runtime** fills the workspace for (§ Deliverable 3). Order W8 builds those.
            request = build_request(selection, workspace=workspace)
            node_inputs[node] = request
            # The seat's own call key. One seat call per tick — the manager's wave is order
            # W8's — so it is the cortex's `call# = 1`, restored on the same condition every
            # other call is: a restorable result being present on its journalled entry.
            seat_key = (str(name), SEAT_CALL_NUMBER, None)
            restored = restorable.get(seat_key)
            result.seat_restored = restored is not None
            envelope = None if restored is None else restored.envelope
            if envelope is None:
                # § Deliverable 4: the seat step consults the procedure set **before** it
                # spawns a model, and on a match returns a `SeatEnvelope` through the unchanged
                # port — decoded below on the one `decode_seat_result()` path, journalled like
                # any other envelope, and still minting this tier's cortex prediction, which is
                # the only thing that lets a bad habit be un-learned. The set was loaded once
                # at task open and rides on the layer's third optional seam; a layer without
                # the seam answers `None` here and nothing about the tick changes.
                habit = habit_of(context.layer, tier, request, selection)
                envelope = None if habit is None else habit.envelope
                if habit is not None:
                    habit_key = seat_key
            if envelope is None:
                port_called = True
                try:
                    # The port's first argument is the **addressee** (§ Deliverable 2,
                    # decision 10): a `Tier` here, because this is the one seat call of the
                    # tick, and a call type for every think, escalate and delegate the node
                    # steps above make through the same callable.
                    envelope = context.layer.port(tier, request)
                except SeatUnavailable as refusal:
                    # The third way the seat produces no envelope, beside the two skip
                    # conditions (build 2 § Deliverable 1, folded: S-33). **The tick still
                    # completes**: a null cortex entry is journalled exactly as a skipped
                    # seat's is, the anterior cingulate still runs, and the boundary commits
                    # `stopped` with the refusal named. Contract 5 — every node every tick —
                    # is never opened by a failure. **No journal envelope is written**, so a
                    # resume re-invokes cleanly through the path build 1 already defined for a
                    # crash inside the seat call.
                    #
                    # **Journalled and counted** (§ Deliverable 2): the call returned without a
                    # result, so its entry is written with the request it was refused on and no
                    # envelope — which a replay reads as "re-invoke this one in place" and the
                    # boundary reads as `unavailable` on the receipt. The node's own output
                    # entry follows it, carrying nothing, exactly as a skipped seat's does.
                    seat_refusal = refusal
                    result.seat_refusal = refusal.message or str(refusal)
                    write_entry(
                        _call_entry(
                            state,
                            name,
                            call_number=SEAT_CALL_NUMBER,
                            tier=tier,
                            payload=request.model_dump(mode="json"),
                            payload_model=type(request).__name__,
                        )
                    )
                    write_entry(_output_entry(state, name, tier=tier))
                    continue
            # The tick stamp on a `latest` slot is the runtime's fact, not the seat's: a
            # seat reports what it did, and *when* is what the runtime knows. Normalizing here
            # is what makes `LatestOutputs` "one typed, tick-stamped slot" true of a scripted
            # seat and of a live one alike. The tick also goes **into** the decoder, which is
            # where a live seat's missing `tick` and `emitter` are filled before validation
            # (decision 10, folded: S-17, folded: S-36).
            try:
                decoded = decode_seat_result(tier, envelope, state.tick).model_copy(
                    update={"tick": state.tick}
                )
            except IllegalReturn as illegal:
                # **A fault on a seat call is `SeatUnavailable` to the boundary**
                # (§ Deliverable 4's refusal classes): an illegal return is one of the three
                # named faults, the tick still completes, and the terminal is `stopped`. The
                # call is journalled with no envelope, exactly as a refusal is, so a replay
                # re-invokes it in place.
                seat_refusal = SeatUnavailable(
                    tier=str(tier), reason=REASON_ILLEGAL_RETURN, message=str(illegal)
                )
                result.seat_refusal = str(illegal)
                write_entry(
                    _call_entry(
                        state,
                        name,
                        call_number=SEAT_CALL_NUMBER,
                        tier=tier,
                        payload=request.model_dump(mode="json"),
                        payload_model=type(request).__name__,
                    )
                )
                write_entry(_output_entry(state, name, tier=tier))
                continue
            # The seat call's spend is accumulated where every other call's is — on its journal
            # entry, below (§ Deliverable 7). The rule itself is unchanged and unmoved: the
            # **per-iteration** sum of input + cache-creation + output tokens, never the
            # top-level aggregate, which sums `cache_read_input_tokens` across the CLI's own
            # internal turns and would charge a cache hit at the price of a miss.

            # Two seats and no third branch (§ Deliverable 3). A dispatch is a call type, not a
            # tier, so an `ExecutorSummary` no longer arrives through a seat call at all: the
            # wave that produces one, and the merge into `state.latest.dispatch`, are order
            # W8's.
            if isinstance(decoded, ManagerPlan):
                state.latest.manager = decoded
                apply_manager(state, decoded, selection)
            else:
                state.latest.director = decoded
                apply_director(state, decoded)
                if decoded.redirect_of is not None:
                    redirect_marker = observations.REDIRECT_BY_DIRECTOR

            # Two entries where build 1 wrote one, and the split is § Deliverable 4's table: the
            # **call** entry carries what a re-invoke needs — the addressee, the request payload
            # and the returned envelope — and the node's **own output** entry carries what the
            # node produced, at the reserved `call# = 0`. A restored call re-writes its
            # journalled entry rather than composing a second one, so a replayed pass's journal
            # is the torn pass's byte for byte.
            write_entry(
                restored
                if restored is not None
                else _call_entry(
                    state,
                    name,
                    call_number=SEAT_CALL_NUMBER,
                    tier=tier,
                    payload=request.model_dump(mode="json"),
                    payload_model=type(request).__name__,
                    envelope=envelope,
                )
            )

            # **One dispatch wave per tick, and only the manager assembles it**
            # (§ Deliverable 3, folded: S-A3, folded: S-A33). It is assembled **here**, at the
            # cortex step, which is what makes decision 17's one-observation rule well-defined:
            # one producer per tick, so nothing to fold across waves. On a director tick no wave
            # is assembled at all and this tick's proposals stay buffered for the next manager
            # tick. **An escalate reply never authorizes a member**: a proposal reaches the wave
            # only where the manager's own plan names it, which is the rule this arm enforces by
            # dispatching `plan.wave` and nothing else.
            if isinstance(decoded, ManagerPlan):
                # The manager ruled on every buffered proposal at its own step: the ones it
                # kept are in `plan.wave` and the rest are dropped, so the buffer is empty
                # either way once a manager tick has run.
                context.proposals.clear()
                result.wave = tuple(decoded.wave)
                if decoded.wave:
                    try:
                        wave_entries, returns, wave_restored = run_wave(
                            context,
                            state,
                            decoded.wave,
                            restorable=restorable,
                            spawns=spawns,
                        )
                    except SeatUnavailable as refusal:
                        # A fault on a `dispatch` member is the seat call's class, not the
                        # advisory one: `SeatUnavailable` to the boundary, the tick completes,
                        # the terminal is `stopped` (§ Deliverable 4).
                        seat_refusal = refusal
                        result.seat_refusal = refusal.message or str(refusal)
                        write_entry(_output_entry(state, name, tier=tier, output=decoded))
                        continue
                    except IllegalReturn as illegal:
                        seat_refusal = SeatUnavailable(
                            tier=str(CallType.DISPATCH),
                            reason=REASON_ILLEGAL_RETURN,
                            message=str(illegal),
                        )
                        result.seat_refusal = str(illegal)
                        write_entry(_output_entry(state, name, tier=tier, output=decoded))
                        continue
                    if not wave_restored:
                        port_called = True
                    result.wave_restored = wave_restored
                    for entry in wave_entries:
                        write_entry(entry)
                    call_raises.extend(_member_raises(returns, WAVE_CALL_NUMBER))
                    try:
                        merged = observations.merge_wave(returns, tick=state.tick)
                    except IllegalReturn as illegal:
                        # A wave naming two units is an **illegal return, not a merge**
                        # (§ Deliverable 3) — a fault on a dispatch member, so the boundary
                        # hears it and the tick completes `stopped`.
                        seat_refusal = SeatUnavailable(
                            tier=str(CallType.DISPATCH),
                            reason=REASON_ILLEGAL_RETURN,
                            message=str(illegal),
                        )
                        result.seat_refusal = str(illegal)
                        write_entry(_output_entry(state, name, tier=tier, output=decoded))
                        continue
                    wave = merged
                    result.wave_status = merged.status
                    summary = merged.summary
                    if summary is not None:
                        # **`FILE_CONTAINS` is observed from the clone, not taken on a member's
                        # word** (`the build specification (not in this mirror)` § Deliverable 5): after the
                        # merge and before this commit and the monitor's projection, each such
                        # value is the workspace file's text, read realpath-confined, and a missing
                        # or refused path leaves none. A restored wave merges here too, so a replay
                        # re-reads the clone.
                        summary = observations.fill_file_contains(
                            summary, state.units, context.workspace_path
                        )
                        state.latest.dispatch = summary

            write_entry(_output_entry(state, name, tier=tier, output=decoded))
            continue

        weights = context.weights(name)
        # **The cheap check, before anything at this step runs** (§ Deliverable 1, decision 3).
        # Projected input and the node's own weights in, a `FiringDecision` out — a pure function
        # beside the node's body, so *which* nodes fire is adaptation **in data** and never a
        # difference in wiring. `NODE_ORDER` is untouched: a node that declines is still on the
        # path and still writes its own journal entry; what it stops doing is work.
        payload = _projected(
            context,
            state,
            name,
            weights,
            summary=summary,
            wave=wave,
            vetoed_unit_id=vetoed_unit_id,
        )
        decision = firing.decide(name, payload)
        firing_decisions.append(decision)
        # The node's first think of the tick by `call#`, kept for the carrier fill before the
        # body: its decoded answer on the live path, its journal entry on the restore path.
        think_answer: Any = None
        restored_think: JournalEntry | None = None
        # **The three call seams, beside the node's body** (§ Deliverable 2's table: every outer
        # node may think, escalate and delegate). The call is constructed by the desk, carried
        # by the runtime and answered through the one port, so the node itself stays the pure
        # callable it was — it opens nothing and spawns nothing. The answer arrives *at the
        # step*, before the body runs, which is what "a node's step may reach the cortex and get
        # an answer back before it ends" means; **a think's answer reaches the body on the
        # node's input model and moves no output** (`the build specification (not in this mirror)`
        # § Deliverable 2): homeostasis's and the monitor's carrier field is filled just before
        # their bodies, and no node output model carries it. **Counting its spend is order
        # W5's**; the desk holds the records for that too.
        #
        # **Each call is journalled at return, under its own `(node, call#)` key**
        # (§ Deliverable 6). On a replay the node's journalled calls are restored instead —
        # re-written from the journal, calling no model — when every one of them carries a
        # restorable result; a node whose journalled set holds a refusal, or which the crash
        # fell inside, re-issues its calls in place through the desk, and the journalled calls
        # of the nodes after it still restore. **The granularity is the node's**, because
        # `TickCalls.run(node, handed)` issues that node's calls whole: the runtime's call policy
        # decides *that* the node calls, the desk issues what it was handed, and a desk's static
        # fixture plan outranks the policy for a node that plan names
        # (`the build specification (not in this mirror)` § Deliverable 1).
        #
        # **A node that declined issues none of them.** The calls a plan named for a node are
        # that node's work at its step, and a skip that still spent on a think call would not be
        # a skip. This is also the whole of homeostasis's skip: its body is contractual and runs
        # either way, so **only its think call is skippable** (folded: S-A16).
        if node_calls is not None and decision.fired:
            # **A `no_go` inhibits the dispatch wave and every delegate for the pending unit
            # while think and escalate stay allowed** (§ DoD row G2). The gate runs before the
            # cortex, so the wave is inhibited by the seat skip above; a delegate is a
            # tier-three call on the same unit and is simply **not issued** — no call, no
            # journal entry, and the gate's own output entry is where the tick names why.
            if vetoed_unit_id is not None:
                _inhibit(node_calls, CallType.DELEGATE)
            # **The policy plans; the desk issues.** The plan is asked for through the module
            # attribute, over the projected input, this node's own `NODE.md`, the delegate bound
            # the desk publishes (`None`, where it publishes none, is unbounded) and the tick's
            # running delegate count — and it is asked **whether or not the node's calls then
            # restore**, so a replay counts exactly the delegates the pass it replays counted.
            planned = triggers.plan(
                name,
                payload,
                context.folders[name].node_md,
                getattr(node_calls, "delegate_bound", None),
                delegates_planned,
            )
            delegates_planned += sum(1 for item in planned if item.type is CallType.DELEGATE)
            prior = [entry for entry in journalled_before if entry.node is name]
            if prior and all(entry.is_restorable() for entry in prior):
                for entry in prior:
                    write_entry(entry)
                restored_think = min(
                    (entry for entry in prior if entry.tier == CallType.THINK),
                    key=lambda entry: entry.call_number,
                    default=None,
                )
            else:
                node_calls.run(name, planned)
                made = _calls_made(node_calls, name)
                if made:
                    port_called = True
                for call_record in made:
                    write_entry(_entry_for(state, name, call_record, spawns))
                call_raises.extend(_call_raises(made, name))
                context.proposals.extend(_proposed_in(made))
                first_think = min(
                    (record for record in made if record.call.type == CallType.THINK),
                    key=lambda record: record.call.call_number,
                    default=None,
                )
                think_answer = getattr(first_think, "result", None)
        # **A skip is a recorded prediction, not an absence** (decision 15, folded: A1-9). The
        # declining node runs no body, leaves its `LatestOutputs` slot exactly as last tick left
        # it — the projection boundary is what stops that slot reaching a consumer — and writes
        # its own output entry at the reserved `call# = 0` carrying the `FiringDecision` as that
        # entry's `output`. Minting its trace record, its `:firing` key and its grade are order
        # W7's. It mints **no ordinary prediction**: § Deliverable 4 writes one per folder per
        # tick **in which it ran**, and a prediction derived from last tick's slot would be one
        # the node never made.
        if not firing.body_runs(name, decision):
            write_entry(_output_entry(state, name, output=decision))
            continue

        # **The think-answer carrier** (`the build specification (not in this mirror)` § Deliverable 2):
        # homeostasis's and the monitor's first think of the tick by `call#` — whatever planned
        # it, the policy or a fixture's static plan — reaches the body on the input model, by
        # `model_copy(update=…)` on `wave_status`'s precedent. On the restore path the journalled
        # envelope is decoded on the one `decode_seat_result()` path, so a replay after the think's
        # entry was journalled hands the body the answer the torn pass did (F11). A refused or
        # absent think leaves the field `None`. The firing check and the call check read the
        # projection before this, so the field is `None` whenever they run; `node_inputs` records
        # the filled input, so the prediction's `input_signature` digests the answer with it. Both
        # bodies read nothing of it: the report and the verdict move on no answer.
        if name in (NodeName.HOMEOSTASIS, NodeName.ANTERIOR_CINGULATE):
            if restored_think is not None:
                think_answer = decode_seat_result(
                    CallType.THINK, restored_think.envelope, state.tick
                )
            if isinstance(think_answer, ThinkResult):
                payload = payload.model_copy(update={"think_answer": think_answer})

        output = NODES[node](payload)
        if name is NodeName.HOMEOSTASIS:
            state.latest.homeostasis = output
            if output.stop:
                # **A crossed ceiling suppresses every further model call for the rest of the
                # tick** (§ Deliverable 7, folded: S-A15). The nodes still run, exactly as
                # `skip_seat` already makes them run: what is suppressed is the spending, not
                # the pass. `skip_seat` was that rule when a tick held one call; a tick now
                # holds N, so the seat's skip is joined by the desk's — every call type
                # inhibited for the rest of the tick, the same accessor the gate's veto uses.
                #
                # **What it cannot do is stated rather than implied**: suppression reaches the
                # *next* model call and cannot recall a wave already away, whose members are
                # separate processes. Bounding a wave's width before it starts is build A.1.i's
                # and no number is written or implied here; in A.1's battery the returns are
                # scripted, so nothing is ever away.
                skip_seat = True
                if node_calls is not None:
                    for call_type in CallType:
                        _inhibit(node_calls, call_type)
        elif name is NodeName.HIPPOCAMPUS:
            state.latest.hippocampus = output
        elif name is NodeName.THALAMUS:
            state.latest.thalamus = output
        elif name is NodeName.BASAL_GANGLIA:
            state.latest.basal_ganglia = output
            if output.decision is SelectionDecision.NO_GO:
                vetoed_unit_id = output.unit_id
                skip_seat = True
        else:
            state.latest.anterior_cingulate = output

        write_entry(_output_entry(state, name, output=output))
        node_inputs[node] = payload

    result.order = tuple(order)
    result.firing = tuple(firing_decisions)
    result.selection = selection
    result.proposals = tuple(context.proposals)
    # A partial or a conflicted wave grades nothing: the unit stays `PENDING`, whatever the
    # monitor's no-subject verdict says about a tick it was handed no summary for.
    suppressed = wave is not None and wave.status in observations.SUPPRESSING_WAVE_STATUSES

    verdict = state.latest.anterior_cingulate
    graded_unit_id = vetoed_unit_id or (summary.unit_id if summary is not None else None)
    graded_unit = next((item for item in state.units if item.id == graded_unit_id), None)

    if graded_unit is not None:
        baselines = state.path_baselines.get(graded_unit.id, {})
        row = observations.compose(
            tick=state.tick,
            unit=graded_unit,
            verdict=verdict,
            summary=summary,
            admitted=state.latest.thalamus,
            baselines=baselines,
            vetoed=vetoed_unit_id == graded_unit.id,
            redirect_by=redirect_marker,
            mismatch_class=(
                state.latest.manager.mismatch_class if state.latest.manager is not None else None
            ),
            wave_status=None if wave is None else wave.status,
        )
        # `None` is **no row at all**: a partial or conflicted wave composes none, so the window
        # is untouched and the streak does not move (§ Deliverable 3, folded: S-A69).
        if row is not None:
            observations.append_window(state, graded_unit.id, row)
        if summary is not None:
            state.path_baselines = {
                **state.path_baselines,
                graded_unit.id: observations.updated_baselines(
                    summary,
                    baselines,
                    state.tick,
                    # **The conflicted rule**: the baselines update from the non-conflicting
                    # paths only — one disagreement does not poison the paths nobody disputed.
                    skip_paths=() if wave is None else wave.conflicting_paths,
                ),
            }
        if verdict is not None and verdict.match and summary is not None and not suppressed:
            for unit in state.units:
                if unit.id == graded_unit.id:
                    unit.status = UnitStatus.PASSED
            _mark_progress(state, graded_unit.goal_id)

    seconds_this_tick = time.monotonic() - started
    # The tick's counters, read off the journal's own call keys — one source for "what this tick
    # called", so a counter and an entry cannot disagree (§ Deliverable 7).
    result.tokens = tokens_this_tick
    result.calls_by_type = calls_by_type(call_entries)
    result.wave_members = wave_members_in(call_entries)
    state.cost.tokens += tokens_this_tick
    state.cost.wall_seconds += seconds_this_tick
    # **The ceiling, re-evaluated at the boundary against the tick's accumulated spend**
    # (§ Deliverable 7). Homeostasis's own function, run twice in the tick and yielding **one**
    # stop: this reading subsumes the node's own — spend only grows — so a crossing seen at the
    # step and a crossing seen here are the same single `stopped` condition below, never two.
    # The stop itself is unchanged: still contractual, still committed here and never mid-tick.
    boundary_report = _ceiling_report(context, state)
    state.cost.ticks += 1
    if seat_refusal is not None:
        # The error tally homeostasis reads its `max_error_rate` against. Counted at the
        # boundary with everything else the tick spent, never inside the adapter.
        state.cost.errors += 1

    minted = _mint(context, state, summary=summary,
                   selection=None if (result.seat_skipped or seat_refusal is not None)
                   else selection,
                   tokens=tokens_this_tick, seconds=seconds_this_tick,
                   graded_unit_id=graded_unit_id, node_inputs=node_inputs)
    # **A skip is a recorded prediction, not an absence** (§ Deliverable 1, decision 15,
    # folded: A1-9). `result.firing` carries every outer node's decision in `NODE_ORDER`,
    # firing and declining alike (folded: D15-6); the declining ones mint one `source: firing`
    # trace record each, whose `prediction_key()` takes the `:firing` suffix so a node's skip
    # and its own prediction are two separately gradeable keys rather than one. The grade needs
    # nothing here: `outcomes.derive()` already scans this folder's committed predictions
    # (folded: D19-3).
    minted.extend(
        predictions.firing_records(
            task=state.task_id, tick=state.tick, decisions=result.firing
        )
    )
    result.predictions = tuple(minted)

    # The cortex-trace prediction each tier's answer belongs to. Resolved here rather than
    # inferred later because this is the only place both the answer and the prediction it
    # belongs to are in hand — and read off the records `_mint()` just returned, before the
    # `stuck` and refusal branches append the synthetic `source: runtime` prediction, which is
    # the runtime's own and belongs to no answer. Both boundary writes below name the same
    # `ref`, which is what makes the two files one identity per `(tick, tier)` rather than two
    # unrelated counts (folded: S-1).
    refs = {
        str(record.tier): record.prediction_key()
        for record in minted
        if record.node is NodeName.CORTEX and record.tier is not None
    }

    # The boundary's write, at the boundary and nowhere else: **one `SeatCallRecord` per
    # journalled call of the committing pass, restored or live** (§ Deliverable 6,
    # folded: S-A8). Build 2 wrote one per `SeatCallFacts` the port call returned and a replay
    # wrote none; a torn tick committed nothing, so its calls had no record at all and the run's
    # own count of what it spent was short by however many calls the tear swallowed.
    #
    # The adapter's facts are still read through the `calls` seam and still guarded on the port
    # having been called **this** tick — a layer reports the invocations of its last port call
    # and is not cleared by a tick that makes none, so an unguarded read would re-compose the
    # previous tick's facts under this tick's key.
    seat_calls = _receipts(
        call_entries,
        calls_of(context.layer) if port_called else (),
        refs=refs,
        task=state.task_id,
        tick=state.tick,
        answered_by_habit=habit_key,
        # The tick's one desk, resolved once at the top of this function and read once here — the
        # witness's only carrier (A.1.i § Deliverable 6, folded: S-i23).
        spawns=spawns,
    )

    derived = outcomes.derive(
        tick=state.tick,
        state=state,
        previous=previous_latest,
        current=state.latest,
        cost=outcomes.TickCost(tokens=tokens_this_tick, wall_seconds=seconds_this_tick),
        committed={
            node: committed_predictions(paths.trace(node)) for node in config.NODE_ORDER
        },
        graded={node: graded_refs(paths.trace(node)) for node in config.NODE_ORDER},
    )
    result.outcomes = tuple([*extra_outcomes, *derived])

    raised = requests_in(
        [
            output
            for output in (
                state.latest.homeostasis,
                state.latest.hippocampus,
                state.latest.thalamus,
                state.latest.basal_ganglia,
                state.latest.anterior_cingulate,
            )
            if output is not None and output.tick == state.tick
        ]
        + [
            output
            for output in (state.latest.director, state.latest.manager, state.latest.dispatch)
            if output is not None and output.tick == state.tick
        ]
    )

    mailbox_writes: list[Interrupt] = []
    new_entries: list[OpenInterrupt] = []
    open_dir = context.root / "mailbox" / "open"
    # **The id widens for a call-bearing raiser only** (§ Scaffold clause item 2, contract 4): a
    # node or the runtime raising on its own account keeps `(task, tick, raiser)`, and a think,
    # escalate, delegate or dispatch member carries the calling node and its call components
    # into the id — so two nodes' think calls in one tick write two files, two members of one
    # wave write two, and `resolution_target()` can read the asking node back out.
    lifted: list[tuple[InterruptRequest, str | None, int | None, int | None]] = [
        (request, None, None, None) for request in raised
    ]
    lifted.extend(
        (request, node, call_number, member_number)
        for request, node, call_number, member_number in call_raises
    )
    for request, node_component, call_number, member_number in lifted:
        identifier = interrupt_id(
            state.task_id,
            state.tick,
            str(request.raised_by),
            node=node_component,
            call_number=call_number,
            member_number=member_number,
        )
        interrupt, entry = lift(
            request,
            task=state.task_id,
            tick=state.tick,
            path=str(open_dir / f"{identifier}.md"),
            node=node_component,
            call_number=call_number,
            member_number=member_number,
        )
        if any(existing.id == entry.id for existing in state.open_interrupts):
            continue
        if any(existing.id == entry.id for existing in new_entries):
            continue
        mailbox_writes.append(interrupt)
        new_entries.append(entry)
    if new_entries:
        state.open_interrupts = [*state.open_interrupts, *new_entries]
    result.raised = tuple(entry.id for entry in new_entries)

    cortex_weights = context.weights(NodeName.CORTEX)
    conditions = terminal.fired(
        state,
        # The boundary's reading, not the step's: it is the same report the node produced with
        # this tick's own spend added, so a ceiling crossed by the tick's N calls is committed
        # by the tick that crossed it rather than by the next one (§ Deliverable 7). One report
        # reaches `fired()`, which is what makes "exactly one stop" structural.
        report=boundary_report,
        raised_this_tick=bool(new_entries),
        cortex_weights=cortex_weights,
    )
    if seat_refusal is not None and TerminalState.STOPPED not in conditions:
        # A refused seat call ends the task `stopped` (decision 11) — not `interrupted`, even
        # though it also raises an interrupt below. The precedence table is build 1's and is
        # not opened here: the refusal's item is written **after** the winner is decided, in
        # the same shape the `stuck` raise already uses, so `raised_this_tick` never sees it.
        conditions.append(TerminalState.STOPPED)
    committed_terminal = terminal.winner(conditions)

    if committed_terminal is TerminalState.STUCK:
        # § Deliverable 3's `stuck` row: the **runtime** writes ONE mailbox interrupt carrying
        # the trap evidence, and mints one synthetic director-tier prediction — only when no
        # director-tier record exists for that tick — so the operator's answer has a `ref` to grade.
        exhausted = terminal.exhausted_goal(state, cortex_weights)
        if exhausted is not None:
            request = _stuck_request(state, exhausted, verdict)
            # The second of the three call sites, passing the widened components: the runtime
            # raises on its **own** account, so it has no node and no `call#` to put there and
            # keeps the three-part id — which is the rule, not an omission (contract 4).
            identifier = interrupt_id(
                state.task_id,
                state.tick,
                str(request.raised_by),
                node=None,
                call_number=None,
                member_number=None,
            )
            if not any(existing.id == identifier for existing in state.open_interrupts):
                interrupt, entry = lift(
                    request,
                    task=state.task_id,
                    tick=state.tick,
                    path=str(open_dir / f"{identifier}.md"),
                    node=None,
                    call_number=None,
                    member_number=None,
                )
                mailbox_writes.append(interrupt)
                state.open_interrupts = [*state.open_interrupts, entry]
                result.raised = (*result.raised, entry.id)
            if not any(
                record.tier is Tier.DIRECTOR and record.tick == state.tick for record in minted
            ):
                minted.append(
                    predictions.synthetic_stuck(
                        task=state.task_id,
                        tick=state.tick,
                        goal_id=exhausted.id,
                        weights=cortex_weights,
                    )
                )

    if seat_refusal is not None:
        # The refusal reaches the operator the way every other unanswerable thing does: one mailbox
        # item carrying the CLI's own message **verbatim**. It is written here, after the
        # winner is decided, for the same reason the `stuck` raise is — see the note above —
        # and it is minted with the same synthetic director-tier prediction, and under the same
        # guard, so the `operator_answer` outcome the resume writes has a `ref` that resolves.
        request = _seat_refusal_request(seat_refusal)
        # The third call site, on the same rule: a refused seat call is the **runtime's** raise,
        # on the one pair it is licensed for, so the id stays three-part.
        identifier = interrupt_id(
            state.task_id,
            state.tick,
            str(request.raised_by),
            node=None,
            call_number=None,
            member_number=None,
        )
        if not any(existing.id == identifier for existing in state.open_interrupts):
            interrupt, entry = lift(
                request,
                task=state.task_id,
                tick=state.tick,
                path=str(open_dir / f"{identifier}.md"),
                node=None,
                call_number=None,
                member_number=None,
            )
            mailbox_writes.append(interrupt)
            state.open_interrupts = [*state.open_interrupts, entry]
            result.raised = (*result.raised, entry.id)
        open_goals = state.open_goals()
        if open_goals and not any(
            record.tier is Tier.DIRECTOR and record.tick == state.tick for record in minted
        ):
            minted.append(
                predictions.synthetic_stuck(
                    task=state.task_id,
                    tick=state.tick,
                    goal_id=open_goals[0].id,
                    weights=cortex_weights,
                )
            )

    state.terminal = committed_terminal
    result.committed_terminal = committed_terminal
    result.predictions = tuple(minted)
    result.losing_terminals = tuple(terminal.losers(conditions))

    episodes: list[EpisodeRecord] = [*extra_episodes, _episode(state, verdict)]
    if committed_terminal is not None:
        detail: dict[str, Any] = {"terminal": str(committed_terminal)}
        if seat_refusal is not None:
            # "commits `stopped` naming the refusal": the name is in the committed record, not
            # only in the mailbox file a `git clean` could take.
            detail["refusal"] = str(seat_refusal)
        episodes.append(_event(state, EventName.TERMINAL, detail))
    for loser in result.losing_terminals:
        episodes.append(_event(state, EventName.TERMINAL_LOSER, {"terminal": str(loser)}))

    # § Deliverable 6's *fresh per task, cached within task*: the two seat handles are minted in
    # the adapter and **carried** by the checkpoint, so a resume in a new process reuses them
    # rather than minting two more. The boundary commit is the only place that can write them.
    if context.layer.sessions is not None:
        handles = context.layer.sessions.for_task(state.task_id)
        if handles:
            state.seat_sessions = dict(handles)

    result.receipt = commit(
        paths,
        state,
        predictions=minted,
        seat_calls=seat_calls,
        outcomes=result.outcomes,
        episodes=episodes,
        mailbox_writes=mailbox_writes,
        mailbox_deletes=resolved_ids,
        mailbox=context.mailbox,
        seed_hashes=context.seed_hashes,
        revision=context.revision,
    )

    # § Deliverable 4's write: one P3 `HabitHit` per habit-answered tick, at the same boundary
    # and through the same `ref`, so scripted, live and habit paths stay one code path here.
    # It is appended **after** the commit rather than inside it, because the commit's stages are
    # `protean.runtime.commit`'s and this order does not own that module (ledger `D19-1`) —
    # which also makes "the `ref` names a prediction *committed* in `trace.jsonl`" true by
    # construction rather than by ordering inside a stage list. The subscript is deliberate: a
    # habit-answered tick is neither skipped nor refused, so `_mint()` always keyed this tier's
    # cortex prediction, and a missing one is a defect that should raise rather than write a
    # hit with no join.
    if habit is not None:
        record = HabitHit.from_facts(
            habit, task=state.task_id, tick=state.tick, ref=refs[str(habit.tier)]
        )
        append_habit_hit(paths.habit_hits, record)
        result.habit_hit = record
    return result


def _mint(
    context: TickContext,
    state: BrainState,
    *,
    summary: ExecutorSummary | None,
    selection: SeatSelection | None,
    tokens: int,
    seconds: float,
    graded_unit_id: str | None,
    node_inputs: Mapping[str, Any],
) -> list[TraceRecord]:
    """One prediction per node folder that ran; the cortex folder's keyed by tier."""
    task = state.task_id
    tick = state.tick

    def signature(node: NodeName, tier: Addressee | None = None):
        payload = node_inputs.get(str(node))
        return None if payload is None else predictions.input_signature(node, payload, tier)

    def ran(node: NodeName) -> bool:
        """Whether this node's **body** ran this tick (§ Deliverable 4, decision 13).

        "Each node folder writes exactly one prediction record per `(folder, tier)` per tick **in
        which it ran**" — and build A.1 is the first build in which a node may not. A node that
        declined its cheap check has no output of its own this tick, only last tick's still
        sitting in its slot, so a prediction derived here would be one the node never made. Its
        `FiringDecision` is its record for the tick instead (§ Deliverable 1); minting the
        prediction from it is order W7's. `node_inputs` is the set of steps that projected a
        slice **and** ran a body, which is exactly that question.
        """
        return str(node) in node_inputs

    minted: list[TraceRecord] = []
    if ran(NodeName.HOMEOSTASIS):
        minted.append(
            predictions.homeostasis(
                task=task, tick=tick, report=state.latest.homeostasis,
                tokens_this_tick=tokens, seconds_this_tick=seconds,
                signature=signature(NodeName.HOMEOSTASIS),
            )
        )
    if ran(NodeName.HIPPOCAMPUS):
        minted.append(
            predictions.hippocampus(
                task=task, tick=tick, retrieval=state.latest.hippocampus,
                signature=signature(NodeName.HIPPOCAMPUS),
            )
        )
    if ran(NodeName.THALAMUS):
        minted.append(
            predictions.thalamus(
                task=task, tick=tick, admitted=state.latest.thalamus,
                signature=signature(NodeName.THALAMUS),
            )
        )
    if ran(NodeName.BASAL_GANGLIA):
        minted.append(
            predictions.basal_ganglia(
                task=task, tick=tick, verdict=state.latest.basal_ganglia,
                signature=signature(NodeName.BASAL_GANGLIA),
            )
        )
    if ran(NodeName.ANTERIOR_CINGULATE):
        minted.append(
            predictions.anterior_cingulate(
                task=task, tick=tick, verdict=state.latest.anterior_cingulate,
                signature=signature(NodeName.ANTERIOR_CINGULATE),
            )
        )
    if selection is None:
        return minted

    cortex_weights = context.weights(NodeName.CORTEX)
    tier = Tier(selection.tier)
    # The dispatch branch keys on the **merged observation**, not on a tier: tier three is not a
    # seat, so `dispatch_expectations` is minted under the addressee `dispatch` from whatever
    # the wave merged. Nothing produces a summary until order W8 dispatches a wave.
    if summary is not None:
        unit = next((item for item in state.units if item.id == summary.unit_id), None)
        minted.append(
            predictions.dispatch(
                task=task,
                tick=tick,
                summary=summary,
                expectation_ids=[e.id for e in unit.expected] if unit else [],
                signature=signature(NodeName.CORTEX, CallType.DISPATCH),
            )
        )
    elif tier is Tier.MANAGER and state.latest.manager is not None:
        minted.append(
            predictions.manager(
                task=task, tick=tick, plan=state.latest.manager,
                unit_id=selection.unit_id or graded_unit_id, weights=cortex_weights,
                signature=signature(NodeName.CORTEX, tier),
            )
        )
    elif tier is Tier.DIRECTOR and state.latest.director is not None:
        open_goals = state.open_goals()
        minted.append(
            predictions.director(
                task=task, tick=tick, direction=state.latest.director,
                goal_id=open_goals[0].id if open_goals else None, weights=cortex_weights,
                signature=signature(NodeName.CORTEX, tier),
            )
        )
    return minted
