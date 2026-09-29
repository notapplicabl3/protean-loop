"""The two bodies behind one configuration key — C4 `BodyTransport`, made a transport.

`the build specification (not in this mirror)` § Deliverable 5 (seam contract C4, decision 9, § Rulings 7,
folded: A1-8, folded: S-A30, folded: S-A31, folded: S-A66, folded: S-A78, folded: S-A86).

**A body is a transport and it decides nothing.** `claude -p` is the default body; a live
terminal Claude Code session is the second. Both carry bytes to a model and bytes back, and the
one thing that differs between them is the flag that selects the CLI's mode — `-p` for the print
body, and for the terminal body the interactive flags, which **A.1 does not fix** (§ Named
assumptions 1) and therefore names as none.

**What is identical across bodies, by contract**, is `BODY_INVARIANTS` exactly: the assembled
system-prompt prefix, the request on stdin, the tool set, the schema handed to the model, the
session mechanics and the journaling. Every one of the six is resolved **here, once**, off the
port and the request — a body carries no resolver of its own — which is what makes "identical
across bodies" a property of what can be constructed rather than of what a reviewer remembered
to check. Row G9's comparison is therefore true by construction, and its **positive control** is
what proves the comparison is live: a body that substitutes a different first half of the prefix
makes the same comparison fail.

**Two clauses of that list are narrowed rather than assumed** (§ Deliverable 5).

* **The prefix is two halves in a fixed order** — a `NODE.md` **first**, then the seat or
  call-type prefix file, plus — for a `dispatch` member only — the unit's `intent` after a fixed
  delimiter (A.2 § Deliverable 7) — and what a body holds identical is the **assembled** prefix,
  never either file alone: a think call's first half is the **calling node's** `NODE.md`
  rather than the cortex's, so a file-level comparison would pass while the result changed
  (folded: S-A66). `system_prompt_prefix()` below therefore asks the port for the assembled
  bytes and compares those.
* **The session mechanics are "mint, resume, discard at task end" for the two seats and "none"
  for everything else** (folded: S-A31), so the clause is satisfied for the non-seat calls by
  **both bodies doing nothing** — which is stated here rather than left looking unmet.

**Containment is identical across bodies by construction** (the operator 2026-09-11, folded: A1-8),
because both bodies are processes the **runtime** spawns: the same absolute-path binary, the
same argv minus the print flag plus the interactive flags, the same env scrub, the same
`sandbox-exec` wrapper, the same tool set and the same session handles. The operator attaches to the
runtime-launched session, never the reverse — so **a body the runtime did not launch is refused
by name, before any session handle is minted** (`refuse_an_unlaunched_body()`).

**The key is one key, and it applies to the two cortex seats only** (folded: S-A78).
`brain/seats.yaml`'s `runtime.body` takes `print` or `terminal`; `body_for()` reads it and
`for_addressee()` applies it to a **seat** addressee alone. Every other addressee takes the print
body: **tier three always runs under `claude -p`**, and in A.1 no tier-three process exists at
all. A `body` key anywhere else in the file is refused at load by name, in
`protean.cortex.live.config` — `TIER_KEYS`-exactly already forbids a per-block one, and a body
selectable per call is a body that could differ per call.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from protean.cortex.live.schema import schema_argument
from protean.state.calls import (
    BODY_INVARIANTS,
    BODY_NAMES,
    BODY_PRINT,
    BODY_TERMINAL,
    BodyTransport,
)
from protean.state.enums import Tier

#: The flag that selects the CLI's **print** body — its non-interactive mode. It lives here
#: rather than with the rest of `invoke.py`'s pinned wire flags because it is the one flag that
#: distinguishes the two bodies, and `invoke.py` imports it back so the name stays where every
#: caller already reads it.
PRINT_FLAG = "-p"

#: What the **terminal** body adds to the argv, and it is deliberately empty.
#:
#: § Named assumptions 1: no runtime-launched interactive session has ever been attached to, and
#: "the interactive flag list is exactly the part that is unfixed" — so A.1 names **none**, and
#: row G13 asserts "no flag outside the named `-p` set is added" rather than a whole-argv
#: equality whose right-hand side does not exist (folded: S-A86). The terminal body is therefore
#: the print body's argv **minus** the print flag, which is exactly what § Deliverable 5 says it
#: is. The operator's row B32 is where a live attach fixes the list; a flag added here before then would
#: be a claim this build cannot make.
TERMINAL_FLAGS: tuple[str, ...] = ()

#: Each body's own flags — the whole of what a body changes about a call.
BODY_FLAGS: Mapping[str, tuple[str, ...]] = {
    BODY_PRINT: (PRINT_FLAG,),
    BODY_TERMINAL: TERMINAL_FLAGS,
}

#: The session mechanics clause, said in the two ways it is satisfied (folded: S-A31).
SEAT_SESSION_MECHANICS = "mint, resume, discard at task end"
NO_SESSION_MECHANICS = "none"


class BodyRefused(ValueError):
    """A body that cannot be used: an unknown name, or one the runtime did not launch.

    A `ValueError` for the same reason `SeatConfigError` is one — it is a malformed *seed* or a
    malformed hand-off, caught before a call, not a refusal the operator surface maps to an exit
    code. `protean.cortex.live.config.SeatConfigError` is its sibling and not its parent, so
    this module imports nothing from the loader it is read by.
    """


@dataclass(frozen=True, slots=True)
class BodyCall:
    """The six C4 invariants as one body received them, recorded so they can be diffed.

    Row G9 compares two of these field by field — the request bytes handed to the body and the
    envelope handed back are compared as **bytes**, because that is what the row claims.
    """

    body: str
    system_prompt_prefix: bytes
    request_on_stdin: bytes
    tool_set: tuple[str, ...]
    schema: bytes
    session_mechanics: str
    journaling: tuple[str, ...]

    def invariants(self) -> dict[str, object]:
        """The six by name, in `BODY_INVARIANTS` order, so a diff can name what moved."""
        return {name: getattr(self, name) for name in BODY_INVARIANTS}


def request_payload(request: Any) -> dict[str, Any]:
    """The request as the port dumps it: a model's JSON mode, or a mapping taken as it is."""
    if hasattr(request, "model_dump"):
        return dict(request.model_dump(mode="json"))
    return dict(request)


def request_on_stdin(payload: Mapping[str, Any]) -> str:
    """The exact text a call puts on the child's stdin.

    One implementation, called by `LiveSeat.__call__` **and** by `Body.request_on_stdin()`, so
    "the request on stdin is identical across bodies" is a fact about the code rather than two
    copies that happen to agree today.
    """
    return json.dumps(dict(payload), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class Body:
    """One body: a name, whether the runtime launched it, and the flags it puts on the argv.

    It holds **no** resolver of its own for any of C4's six invariants — the methods below are
    the port's own facts, read through one code path for both bodies. A body that could answer
    one of them differently is the thing this class exists to make unbuildable.
    """

    name: str
    #: Whether the **runtime** launched this body. The operator attaches to the runtime-launched session,
    #: never the reverse (§ Deliverable 5), so a `False` here is refused by name.
    runtime_launched: bool = True

    # ----------------------------------------------------------------------------------
    # The argv half — the whole of what a body changes
    # ----------------------------------------------------------------------------------

    def flags(self) -> tuple[str, ...]:
        """What this body puts on the argv, before the flags every call carries."""
        return tuple(BODY_FLAGS.get(self.name, ()))

    # ----------------------------------------------------------------------------------
    # C4's six, resolved once for both bodies
    # ----------------------------------------------------------------------------------

    def system_prompt_prefix(
        self, port: Any, addressee: Any, node: Any = None, *, block: Any = None
    ) -> bytes:
        """The **assembled** prefix: a `NODE.md` first, then the block's own prefix file — and,
        for a `dispatch` member whose port carries its unit's `intent`, a third part the port
        appends after a fixed delimiter line (A.2 § Deliverable 7). This method never sees the
        unit: the port holds it as instance state.

        Never either file alone (folded: S-A66) — `port.system_prompt()` is the one assembler,
        and a body that substituted a different first half would change the result while passing
        a file-level comparison. That substitution is row G9's positive control.

        **The resolved block arrives as a parameter** (A.1.i § Deliverable 3, folded: S-i35): this
        method reaches the port's resolver, and `SeatsConfig.block()` is addressee-only because an
        addressee cannot name WHICH kind — so a spawn's kind block is passed in, and `None` means
        "ask the port", which is what keeps `carried()` unwidened and this a **signature** change.
        """
        resolved = port.block_for(addressee) if block is None else block
        return port.system_prompt(addressee, node, block=resolved).encode("utf-8")

    def request_on_stdin(self, request: Any) -> bytes:
        """The request bytes handed to the body, through the port's own dump."""
        return request_on_stdin(request_payload(request)).encode("utf-8")

    def tool_set(self, port: Any, addressee: Any, *, block: Any = None) -> tuple[str, ...]:
        """The **resolved** tool set: what `--tools` names, as names.

        `()` for a tool-less seat and for either `calls:` block — which is every addressee A.1
        configures, and the reason `Task` is in no body's tool set. **A spawn's is its kind block's
        own `tools`**, which the loader proved equal as a set to the names derived from that
        block's `allowed_tools`, so the tool set a body reports and the `--allowedTools` patterns on
        the wire cannot disagree (A.1.i § Deliverable 2).

        **Signature widening only** (A.1.i § Deliverable 3, folded: S-i35), for the reason one
        module over: `SeatsConfig.block()` refuses `dispatch` and `delegate` by design, so the
        resolved block arrives as a parameter and `None` means "ask the port".
        """
        resolved = port.block_for(addressee) if block is None else block
        argument = resolved.tools_argument()
        if argument is None:
            return ()
        return tuple(name for name in argument.split(",") if name)

    def schema(self, addressee: Any) -> bytes:
        """The schema handed to the model — the narrowed `--json-schema`, per addressee."""
        return schema_argument(addressee).encode("utf-8")

    def session_mechanics(self, addressee: Any) -> str:
        """"Mint, resume, discard at task end" for a seat, and **none** for everything else.

        The clause is satisfied for the non-seat calls by both bodies doing nothing
        (folded: S-A31): a think, escalate, delegate or dispatch call mints a fresh handle per
        invocation and checkpoints nothing, whichever body carries it.
        """
        return SEAT_SESSION_MECHANICS if isinstance(addressee, Tier) else NO_SESSION_MECHANICS

    def journaling(self, addressee: Any, request: Any) -> tuple[str, ...]:
        """What the call hands the journal: the addressee, the request model, the kind and block.

        `JournalEntry`'s call columns — "what a re-invoke needs, and nothing more". The body
        writes none of it; the boundary does. The tuple is here so the clause is **compared**
        rather than asserted, and so a body that ever started editing an entry would show up.
        The kind travels on the request and the block reference is the constant `""` **because the
        boundary fills that field**, never the body: `SubagentSpawn.block_ref` is written where the
        spawn is recorded, so a tuple that resolved it here would be a second writer of one fact
        (A.1.i § Deliverable 6, folded: S-i54). The tuple does not move.
        """
        payload = request_payload(request)
        model = type(request).__name__ if hasattr(request, "model_dump") else ""
        return (str(addressee), model, str(payload.get("kind", "")), "")

    # ----------------------------------------------------------------------------------
    # C4's refusal, and the record row G9 diffs
    # ----------------------------------------------------------------------------------

    def implements(self) -> tuple[str, ...]:
        """The invariants this body can actually carry — read off the object, never declared.

        A body that names an invariant it cannot resolve is exactly the failure C4's refusal
        exists for, so the list is `hasattr` rather than a field a body fills in about itself.
        """
        return tuple(
            name for name in BODY_INVARIANTS if callable(getattr(self, name, None))
        )

    def transport(self) -> BodyTransport:
        """C4 `BodyTransport` for this body — the loader's refusal, stated on the contract.

        A body that implements five of the six is refused **here**, by name, before any session
        handle is minted (§ Deliverable 5: "the loader refuses a body that does not implement
        all of it").
        """
        return BodyTransport(
            name=self.name,
            implements=self.implements(),
            runtime_launched=self.runtime_launched,
        )

    def carried(self, port: Any, addressee: Any, request: Any, node: Any = None) -> BodyCall:
        """The six invariants as this body received them, for one addressee and one request."""
        return BodyCall(
            body=self.name,
            system_prompt_prefix=self.system_prompt_prefix(port, addressee, node),
            request_on_stdin=self.request_on_stdin(request),
            tool_set=self.tool_set(port, addressee),
            schema=self.schema(addressee),
            session_mechanics=self.session_mechanics(addressee),
            journaling=self.journaling(addressee, request),
        )


def refuse_an_unlaunched_body(body: Body) -> None:
    """Refuse, **by name**, a body the runtime did not launch (§ Deliverable 5, row G13).

    the operator attaches to the runtime-launched session, never the reverse: a session the runtime did
    not spawn has none of the containment the other half of this module is about — not the
    absolute-path binary, not the scrubbed environment, not the sandbox wrapper. The refusal
    fires before a handle is minted, so nothing is left half-open behind it.
    """
    if not body.runtime_launched:
        raise BodyRefused(
            f"body {body.name!r} was not launched by the runtime — the operator attaches to the "
            f"runtime-launched session, never the reverse, and a body the runtime did not "
            f"launch carries none of the containment the runtime spawns it under "
            f"(§ Deliverable 5, row G13). Refused before any session handle is minted"
        )


def select(name: str, *, runtime_launched: bool = True) -> Body:
    """One body by name, refusing an unknown name, an unlaunched body and an incomplete one."""
    if name not in BODY_NAMES:
        raise BodyRefused(
            f"body {name!r} is not one of {list(BODY_NAMES)} — `runtime.body` takes "
            f"{BODY_PRINT!r} or {BODY_TERMINAL!r} and nothing else"
        )
    body = Body(name=name, runtime_launched=runtime_launched)
    refuse_an_unlaunched_body(body)
    body.transport()  # C4's own refusal: all six invariants, or this body does not load.
    return body


def body_for(config: Any) -> Body:
    """The body `runtime.body` selects, for a root whose seed carries the key.

    `SeatsConfig.body` defaults to `print`, so a containment object built directly rather than
    from a seed — `protean.oracle.config`, which carries no seats — is unchanged by A.1.
    """
    return select(str(getattr(config, "body", BODY_PRINT)))


def for_addressee(config: Any, addressee: Any) -> Body:
    """The body **this addressee** runs under: `runtime.body` for a seat, `print` otherwise.

    § Deliverable 5: the key "applies to the two cortex seats only", and **tier three always
    runs under the `claude -p` body**. The two `calls:` blocks take the print body for the same
    reason: the terminal body exists for the director and the manager, which carry no tools and
    never touch the workspace, and a cheap advisory call is not one of them.
    """
    if isinstance(addressee, Tier):
        return body_for(config)
    return select(BODY_PRINT)
