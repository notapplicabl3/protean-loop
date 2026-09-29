"""The habit matcher: a compiled procedure answering a tick, with no call behind it.

`the build specification (not in this mirror)` § Deliverable 4 (seam contracts P2, P3), § Directional
decisions 13, 19, 21, § Resolutions A1-2, S-1, S-4, S-18, D16-2, D16-3.

**A procedure is a compiled `SeatScript`** (decision 13), so this module is `scripts.py` read
from the other end: sleep writes a file `parse_script()` loads unmodified, and this matches an
incoming request against it exactly as the scripted seat matches a hand-authored one. There is
no second matching rule and no second condition set — `RequestFacts`, `ResponseCondition` and
`substitute()` are imported rather than restated, because a habit that matched by different
arithmetic than it compiled by would be a habit that never fires for a reason no test could see.

**The matcher is pure and the runtime resolves it** (folded: S-18). `protean.cortex.layer.build()`
takes no argument and runs before any task exists, so the procedure set cannot be resolved there.
`open_task()` below is the task-open factory the runtime calls instead: it reads the two
`procedures/` folders through `protean.brain.folders`, holds the result for the life of the task
— a sleep run mid-task is refused (decision 16), so it cannot change underneath a run — and
hands back the `SeatLayer.habits` seam. `match()` itself opens no file.

**Two rules are enforced here as well as at the compiler.** A procedure answers the **manager
and director seats only** (decision 21, folded: S-4) — a canned `ExecutorSummary` would assert
file states nothing looked at — and a response whose condition binds no `goal_digest` matches
nothing (ledger `D19-4`): "a compiled condition binds `goal_digest`" is what stands between a
habit and an everything-matches prior, and a file on disk can be edited by hand.

**On a match the port is still the port** (§ Directional decisions 3). The answer is an ordinary
`SeatEnvelope`, built by the same `build_envelope()` the scripted seat answers through, and the
runtime decodes it on the one `decode_seat_result()` path it decodes a live call and a journal
restore on. What the envelope cannot carry — which procedure answered, which condition it bound,
which model it stood in for — travels beside it on `HabitFacts`, and the runtime writes P3
`HabitHit` from that at the boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from protean.brain.folders import procedure_set
from protean.cortex.adapters import build_envelope
from protean.cortex.scripts import (
    CONDITION_KEYS,
    STAMPED_FIELD,
    ResponseCondition,
    SeatScript,
    facts_of,
    parse_script,
    substitute,
)
from protean.runtime.paths import ROOT_PROJECT_SLUG
from protean.runtime.seat import HabitFacts, SeatSelection
from protean.state.enums import Tier

#: The two tiers a procedure may answer (§ Directional decisions 21, folded: S-4). Their results
#: are *decisions*, and a canned decision on a repeated goal is a habit; an `ExecutorSummary` is
#: an observation of the workspace the runtime commits as path baselines, so a canned one would
#: assert file states nothing looked at. Acting procedures are § Out of scope.
ANSWERABLE_TIERS: tuple[Tier, ...] = (Tier.DIRECTOR, Tier.MANAGER)

#: The one condition key a compiled habit must bind (§ Deliverable 4, folded: S-3, ledger
#: `D16-2`). Checked at match time as well as at compile time, so a hand-edited file cannot
#: become the everything-matches habit the SPEC's parenthesis forbids.
REQUIRED_CONDITION_KEY = "goal_digest"


@dataclass(frozen=True, slots=True)
class LoadedProcedure:
    """One compiled habit, parsed: its id, and the `SeatScript` it is.

    The provenance header sleep writes — `compiled_from`, `hits_required`, `seed`,
    `schema_version` — is deliberately absent: `parse_script()` ignores it by design, and the
    only provenance a *match* needs is the id precedence is read on and P3 records.
    """

    procedure_id: str
    script: SeatScript


def load_procedures(
    entries: Sequence[tuple[str, Mapping[str, object]]],
) -> tuple[LoadedProcedure, ...]:
    """`(procedure_id, payload)` pairs → parsed procedures, in precedence order.

    **Lexical by `procedure_id`, first match wins** (ledger `D16-2`). The sort is stable, so two
    files carrying one id keep the order the reader gave them — the node folder's before the
    project's, which is `procedure_set()`'s own tie-break.

    Every payload goes through `parse_script()` unmodified, which is row L6's claim read from
    the runtime's side: a file that does not load raises `SeatScriptError` here rather than
    matching nothing quietly, because a compiled habit that cannot be loaded is a compiler
    defect and not a tick-time tolerance.
    """
    loaded = [
        LoadedProcedure(procedure_id=identifier, script=parse_script(payload, name=identifier))
        for identifier, payload in entries
    ]
    return tuple(sorted(loaded, key=lambda item: item.procedure_id))


def bound_keys(condition: ResponseCondition) -> dict[str, str]:
    """The condition as the keys it actually binds — P3's `matched_condition`.

    Derived from `CONDITION_KEYS` rather than written out, so the widened set and this stay one
    fact. A compiled condition binds `goal_digest` and never `unit_id`, so in practice this is
    the one key; it is a mapping anyway, because what P3 records is what matched.
    """
    return {
        key: str(value)
        for key in CONDITION_KEYS
        if (value := getattr(condition, key, None)) is not None
    }


def match(
    tier: Tier | str,
    request: object,
    procedures: Sequence[LoadedProcedure],
    selection: SeatSelection | None = None,
    *,
    avoided_model: str = "",
) -> HabitFacts | None:
    """`(request, procedures) → HabitFacts | None` — the pure matcher, no I/O.

    At most one match per tick: the first response of the first procedure, in the precedence
    `load_procedures()` fixed, whose condition matches the incoming request. `None` means the
    tick falls through to the port, which is every tick on a root that has compiled nothing.

    The result payload is filled exactly as the scripted seat fills a hand-authored one —
    `substitute()` for `$goal` and `$unit`, `tick` stamped from the request — so a compiled
    `$goal` placeholder (ledger `D16-3`) resolves through the one implementation and never a
    second substitution.
    """
    chosen = Tier(tier)
    if chosen not in ANSWERABLE_TIERS:
        return None
    facts = facts_of(chosen, request, selection)
    if facts.goal_digest is None:
        return None
    for procedure in procedures:
        for response in procedure.script.for_tier(chosen):
            if getattr(response.when, REQUIRED_CONDITION_KEY) is None:
                continue
            if not response.when.matches(facts):
                continue
            payload = substitute(dict(response.result), facts)
            payload[STAMPED_FIELD] = facts.tick
            return HabitFacts(
                tier=str(chosen),
                envelope=build_envelope(
                    chosen, payload, session_id="", usage=response.usage
                ),
                procedure_id=procedure.procedure_id,
                matched_condition=bound_keys(response.when),
                avoided_model=avoided_model,
            )
    return None


@dataclass(frozen=True, slots=True)
class HabitBook:
    """The `SeatLayer.habits` seam: one task's procedure set, consulted before the port.

    Holds what the matcher may not go and get — the parsed set and the per-tier model ids — and
    nothing that changes inside a task. It is attached to the layer by the runtime at task open
    and discarded with the task; `build()` never sees one.
    """

    procedures: tuple[LoadedProcedure, ...] = ()
    models: Mapping[str, str] = field(default_factory=dict)

    def __call__(
        self,
        tier: Tier,
        request: object,
        selection: SeatSelection | None = None,
    ) -> HabitFacts | None:
        return match(
            tier,
            request,
            self.procedures,
            selection,
            avoided_model=self.models.get(str(Tier(tier)), ""),
        )


def seat_models(root: Path) -> dict[str, str]:
    """`tier → the model id `brain/seats.yaml` names`, for the tiers a habit may answer.

    What P3's `avoided_model` records: the model the habit stood in for (ledger `D19-5`). Empty
    on a root with no `seats.yaml` and on one that does not select the live layer — every test
    root and every `protean dry` copy — because no model was avoided there and an invented id
    would be the record claiming a call nothing configured.

    The import is function-scoped: this module is loaded at task open on every root, and the
    live subpackage is build 2's heavier one.
    """
    from protean.cortex.live.config import load_seats

    seats = load_seats(root)
    if seats is None or not seats.is_live:
        return {}
    return {str(tier): seats.tier(tier).model for tier in ANSWERABLE_TIERS}


def open_task(root: Path, *, project: str = ROOT_PROJECT_SLUG) -> HabitBook | None:
    """The procedure set one task opens with, or `None` when the root has compiled nothing.

    The task-open half of § Deliverable 4's "the runtime's seat step loads the procedure set
    once at task open or resume, from the node folder's `procedures/` and the task's own project
    procedures under the slug in `BrainState.extensions`, holds it for the life of the task, and
    consults the matcher before it calls the port".

    `None` rather than an empty book, so a root with no compiled habit carries no seam at all
    and `habit_of()` short-circuits on the field rather than on an empty loop.
    """
    entries = procedure_set(root, project=project)
    if not entries:
        return None
    return HabitBook(procedures=load_procedures(entries), models=seat_models(root))
