"""The seat adapters: one session handle per seat, and the envelope every addressee answers inside.

Build A.1 (`the build specification (not in this mirror)` § Deliverables 2–3): two seats — director and
manager — hold session handles; think, escalate, delegate and dispatch are session-less call
types answered through the same port. The build-1 paragraphs below are kept as the record of
where this module started.

`the build specification (not in this mirror)` § Deliverable 6 — the wire shape's four measured facts, the
per-tier seat behaviour, and *fresh per task, cached within task* (`DIGEST:70`, folded: S-14).

**In build 1 all three tiers are scripted and there are zero model calls.** This package is the
one place in the build licensed to name the CLI seat at all, and build 1 must not invoke it:
nothing in this module imports a process module, opens a pipe or spawns anything. The constant
below exists so the seam has a name build 2 fills, and so that the static half of M21 — "no
module outside `src/protean/cortex/` names the `claude` binary" — is a check with something to
find rather than a vacuous one.

**One adapter, one session per seat.** `SessionBook` mints one handle per seat tier when a
task opens and hands the same one back for every call inside that task; a new task discards
them and mints afresh (build 1 had three tiers; A.1 has two seats, and a call type takes a
fresh `--session-id` per invocation instead). The port's signature is `(addressee, request) -> SeatEnvelope` and
carries no task id, so the book learns which task is open from the **router**, which the runtime
calls first on every tick and which is handed the whole `Workspace`. `SeatDesk` is that channel:
the router writes the open task and the selection onto it, and the port reads both. Nothing else
crosses it, and it holds no state that outlives a task.

**The envelope is the real one's shape, not a tidier one.** All four measured facts are filled
on every response — `stop_reason == "tool_use"`, a `result` that is a JSON *string*, a
`modelUsage` map carrying a second haiku-tier overhead entry beside the first-party call, and a
`usage.cache_read_input_tokens` receipt — plus the envelope keys a real one carries and
`SeatEnvelope` tolerates without naming. A mock tidier than the thing it stands in for is the
failure named assumption 1 exists to name.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from protean.cortex.calls import CallConfigurationError
from protean.cortex.live.session import call_session
from protean.cortex.scripts import SeatScript, SeatScriptError
from protean.state.enums import Addressee, CallType, Tier
from protean.state.seats import CACHE_READ_KEY, STRUCTURED_SUCCESS_STOP_REASON, SeatEnvelope

#: The CLI seat build 2 fills these adapters with. **Build 1 never invokes it**: no module in
#: this package imports `subprocess`, `os.exec*` or any other spawn path, and
#: `tests/cortex/test_no_model_calls.py` asserts it of the package's own source.
SEAT_BINARY = "claude"

#: The prefix of the second, overhead entry a real `--output-format json` envelope carries
#: beside the first-party call (§ Deliverable 6, measured fact 3). `SeatEnvelope` deliberately
#: does not name it — "the seat adapters own that literal and pass it in" — so this is the
#: module that holds it, and `first_party_models()` is read against it.
OVERHEAD_MODEL_PREFIX = "claude-haiku-"

#: The overhead entry a scripted response reports. It conforms to the prefix above and says
#: plainly that it is a stand-in; build 2 replaces it with the id a real envelope carried.
OVERHEAD_MODEL = f"{OVERHEAD_MODEL_PREFIX}overhead"

#: The first-party entry, one per tier. It does **not** start with the overhead prefix, which
#: is what makes `SeatEnvelope.first_party_models(OVERHEAD_MODEL_PREFIX)` return exactly it.
FIRST_PARTY_MODEL_TEMPLATE = "protean-{tier}-model"

#: The envelope keys a real one carries that `SeatEnvelope` tolerates without requiring.
ENVELOPE_TYPE = "result"
ENVELOPE_SUBTYPE = "success"


def first_party_model(addressee: Addressee) -> str:
    """The `modelUsage` key one **addressee's** first-party call is reported under."""
    return FIRST_PARTY_MODEL_TEMPLATE.format(tier=str(addressee))


@dataclass(slots=True)
class SessionBook:
    """One session handle per seat for the life of a task; both minted together.

    § Deliverable 6: "each tier's adapter owns one session handle for the life of a task, all
    three minted per task ... and discarded at task end. Whether a director or planner call is
    cheap enough to be cold is a build-2 measurement, not a build-1 design choice, so all three
    tiers take the executor's lifetime." A.1 reduces that retained set to director and manager.

    The ids are minted, not derived from the task id: a real session handle is opaque, and a
    handle a second process could recompute would hide the fact that reusing one across a
    resume needs it to have been *carried* rather than re-derived.
    """

    task_id: str | None = None
    handles: dict[str, str] = field(default_factory=dict)
    minted_tasks: list[str] = field(default_factory=list)

    def open_task(self, task_id: str) -> dict[str, str]:
        """Mint both seat handles the first time this task is seen; return the same two after."""
        if self.task_id == task_id:
            return dict(self.handles)
        self.task_id = task_id
        self.handles = {str(tier): f"seat-{tier}-{uuid.uuid4().hex}" for tier in Tier}
        self.minted_tasks.append(task_id)
        return dict(self.handles)

    def for_task(self, task_id: str) -> dict[str, str]:
        """The two seat handles open for this task — nothing if a different task is open.

        The runtime's half of `protean.runtime.seat.SeatSessions`: it reads them at the boundary
        it commits, so the checkpoint carries what this task is actually using.
        """
        return dict(self.handles) if self.task_id == task_id else {}

    def restore(self, task_id: str, handles: Mapping[str, str]) -> None:
        """Adopt the handles a checkpoint carried, so a resume reuses them instead of minting.

        Not a mint: `minted_tasks` is untouched, which is what lets a caller tell "carried across
        a resume" from "three more minted in a new process" (§ Deliverable 6).
        """
        if not handles:
            return
        self.task_id = task_id
        self.handles = {str(key): str(value) for key, value in handles.items()}

    def close_task(self) -> None:
        """Discard all three at task end. A later task mints its own."""
        self.task_id = None
        self.handles = {}

    def handle(self, tier: Tier) -> str:
        """The handle this tier is using. A call before a task opened is a wiring bug."""
        key = str(tier)
        if key not in self.handles:
            raise RuntimeError(
                "no seat session is open: the router opens the task before the port is called"
            )
        return self.handles[key]


@dataclass(slots=True)
class SeatDesk:
    """The router → port channel the port's signature has no room for.

    `SeatPort` is `(tier, request) -> SeatEnvelope` and carries no task id, so neither the task
    id nor the reason the router named this seat can reach the seat through its argument list.
    The runtime calls the router first on every tick, so the router writes both here on its way
    past and the seat reads them.
    """

    sessions: SessionBook = field(default_factory=SessionBook)
    selection: Any | None = None

    def open_tick(self, task_id: str, selection: Any) -> None:
        """What the router does on every tick, before the port is called at all."""
        self.sessions.open_task(task_id)
        self.selection = selection

    def handle(self, tier: Tier) -> str:
        """The session handle this tier is using inside the open task."""
        return self.sessions.handle(tier)


def build_envelope(
    tier: Addressee,
    result: Mapping[str, Any],
    *,
    session_id: str,
    usage: Mapping[str, int] | None = None,
) -> SeatEnvelope:
    """One **addressee's** result payload → the envelope the runtime decodes, four facts and all."""
    counters = {"input_tokens": 0, "output_tokens": 0, CACHE_READ_KEY: 0}
    counters.update({str(key): int(value) for key, value in (usage or {}).items()})
    return SeatEnvelope(
        type=ENVELOPE_TYPE,
        subtype=ENVELOPE_SUBTYPE,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        stop_reason=STRUCTURED_SUCCESS_STOP_REASON,
        result=json.dumps(result),
        modelUsage={
            first_party_model(tier): {
                "inputTokens": counters["input_tokens"],
                "outputTokens": counters["output_tokens"],
                "cacheReadInputTokens": counters[CACHE_READ_KEY],
            },
            OVERHEAD_MODEL: {
                "inputTokens": 0,
                "outputTokens": 0,
                "cacheReadInputTokens": 0,
            },
        },
        usage=counters,
    )


@dataclass(slots=True)
class ScriptedSeat:
    """`protean.runtime.seat.SeatPort` over one hand-authored script. Zero model calls.

    The adapter's job **ends at the envelope** (folded: the W2 seam): decoding
    `SeatEnvelope.result` into `DirectorDirection` / `ManagerPlan` / a non-seat return is the
    runtime's, so a replayed tick that restores a journalled envelope takes the identical path.

    **It answers all four addressees** (`the build specification (not in this mirror)` § Deliverable 2,
    row M3): the two seats by `Tier` and think, escalate, delegate and dispatch by call type.
    Two things differ for a non-seat call and nothing else does — **the session is minted fresh
    per invocation and discarded**, so the book is never touched and `BrainState.seat_sessions`
    never sees a key outside `config.TIERS` (folded: S-A31); and a script with no answer for
    that addressee is a **missing configuration**, which is a refusal to the calling node rather
    than a stop (§ Deliverable 2). The **delegate and dispatch answers are scripted returns with
    no process behind them**, and order W8 extends them for the wave.
    """

    script: SeatScript
    desk: SeatDesk
    calls: list[tuple[str, str]] = field(default_factory=list)

    def __call__(self, addressee: Addressee, request: object) -> SeatEnvelope:
        """One scripted turn: match on the request, stamp the tick, wrap it in the envelope."""
        chosen = addressee if isinstance(addressee, (Tier, CallType)) else Tier(addressee)
        selection = self.desk.selection
        try:
            payload = self.script.respond(chosen, request, selection)
            usage = self.script.usage_for(chosen, request, selection)
        except SeatScriptError as unmatched:
            if isinstance(chosen, CallType):
                raise CallConfigurationError(str(unmatched)) from unmatched
            raise
        handle = self.handle(chosen)
        self.calls.append((str(chosen), handle))
        return build_envelope(chosen, payload, session_id=handle, usage=usage)

    def handle(self, addressee: Addressee) -> str:
        """The seats' task-long handle, or a **fresh** one for a call that is not a seat call."""
        if isinstance(addressee, CallType):
            return call_session()
        return self.desk.handle(addressee)

    def calls_for(self, tier: Addressee) -> list[tuple[str, str]]:
        """Every call made to one addressee, with the session handle it used."""
        return [item for item in self.calls if item[0] == str(tier)]
