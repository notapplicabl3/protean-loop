"""Projections: `BrainState` → the five node input models, the workspace, and the tick's unit.

`the build specification (not in this mirror)` § Deliverable 2 — "Every node is a callable from a typed
**input model** — the read slice its `NODE.md` declares, projected from `BrainState` by the
runtime, so a node reads nothing else" — and decision 25, which makes those projections the
runtime's job and rebuilds them every tick.

**This module is the only place a node's read slice is assembled.** That is what makes the
`## Reads` drift refusal meaningful: the fields a node can see are exactly the fields its input
model declares, and the model's field list is what `brain/nodes/<node>/NODE.md` must name.

**`weights` is a projection like any other** — the runtime loads the folder's `weights.yaml`
and hands it to the node, so a node module contains no threshold literal and opens no file.

**The workspace is rebuilt, never accumulated** (folded: S-9). Every seat gets the same
`Workspace`; the per-tier request model is the filter (folded: T-11). On the seat path three
bodies are withheld from `latest`: a `FILE_CONTAINS` value, sent as a record of its UTF-8 byte
length and SHA-256 digest; a retrieval candidate's `text`; and an admitted item's `summary` inside
`latest.thalamus`, whose bodies reach a seat once, on `workspace.admitted`. Committed state keeps
every body (`the build specification (not in this mirror)` § Deliverable 2).

**A skipped node leaves no stale slot, and the test that makes that true lives here**
(`the build specification (not in this mirror)` § Deliverable 1, folded: S-A16, folded: S-A92). Every
`LatestOutputs` slot's output model already carries `tick`, so build A.1 puts **one** mechanism in
the one place a node's read slice is assembled: `_this_tick()` below hands a slot to its consumer
only when the slot's stamp is the current tick, and hands `None` otherwise. **No committed field
is emptied and no stamp is rewritten** — last tick's output stays exactly where it is and simply
stops being projected, which is what keeps the mechanism free of a schema change and keeps it to
one. What moves is the receiving end: `ThalamusInput.retrieval` and `BasalGangliaInput.admitted`
are optional, joining `MonitorInput.executor_summary`, and an absent required input **is** the
consumer's own "nothing for me" condition.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from protean.state.brain_state import BrainState
from protean.state.enums import ExpectationKind, UnitStatus
from protean.state.inputs import (
    BasalGangliaInput,
    HippocampusInput,
    HomeostasisInput,
    MonitorInput,
    ThalamusInput,
)
from protean.state.outputs import AdmittedContext, RetrievalSet
from protean.state.primitives import WorkUnit
from protean.state.records import EpisodeRecord
from protean.state.seats import ExecutorSummary
from protean.state.semantic import SemanticChunk
from protean.state.workspace import LatestOutputs, Workspace

#: The keys of the record a withheld `FILE_CONTAINS` value reaches a seat as
#: (`the build specification (not in this mirror)` § Deliverable 2, reduction 1; the names are a builder's
#: default). The record states that the text was withheld and carries the text's UTF-8 byte
#: length and SHA-256 hex digest — never the text.
WITHHELD_KEY: Final[str] = "withheld"
UTF8_BYTES_KEY: Final[str] = "utf8_bytes"
SHA256_KEY: Final[str] = "sha256"


def pending_unit(state: BrainState) -> WorkUnit | None:
    """The unit this tick is about: the active one, else the first pending one.

    A unit the manager abandoned or the monitor passed is never selected again, which is what
    keeps `units` a stack rather than a queue that replays its own history.
    """
    for unit in state.units:
        if unit.status is UnitStatus.ACTIVE:
            return unit
    for unit in state.units:
        if unit.status is UnitStatus.PENDING:
            return unit
    return None


def _this_tick(slot: Any, tick: int) -> Any:
    """A slot, but only when its own stamp is this tick — otherwise `None` (§ Deliverable 1).

    The **one** stale-slot mechanism in the build. It reads the stamp the runtime already writes
    on every `LatestOutputs` slot and writes nothing: a node that declined leaves its slot exactly
    as last tick left it, and this is what stops that slot from reaching a consumer wearing this
    tick's authority. Adding a second test anywhere else is what § Deliverable 1 forbids.
    """
    return slot if slot is not None and slot.tick == tick else None


def homeostasis_input(state: BrainState, weights: Mapping[str, Any]) -> HomeostasisInput:
    """Cost, the ceilings after any `resume --extend` override, and the `budget` constraints."""
    return HomeostasisInput(
        task_id=state.task_id,
        tick=state.tick,
        weights=dict(weights),
        cost=state.cost,
        ceiling_overrides=state.ceiling_overrides,
        constraints=list(state.constraints),
    )


def hippocampus_input(
    state: BrainState,
    weights: Mapping[str, Any],
    candidates: Sequence[EpisodeRecord],
    semantic: Sequence[SemanticChunk] = (),
) -> HippocampusInput:
    """This task's last `candidate_window` episode records, plus the stacks they score against.

    The window is `candidate_window` from the hippocampus's own `weights.yaml`; the runtime's
    boundary loader reads the file and this projection carries the slice (folded: T-12).

    `semantic` is the second slice, the same way (build 2): the loader reads
    `brain/semantic/*.jsonl` and keeps the top `semantic_window` chunks, and this projection
    carries them. **It opens no file either way** — a projection that read the store would put
    a filesystem path inside the one place a node's read slice is assembled, and the `## Reads`
    refusal would then be checking a list against a model the runtime could bypass. It defaults
    to empty because a brain root with no intake behind it has no store, which is a shape the
    tick must survive rather than refuse.
    """
    return HippocampusInput(
        task_id=state.task_id,
        tick=state.tick,
        weights=dict(weights),
        goals=list(state.goals),
        units=list(state.units),
        candidates=list(candidates),
        semantic=list(semantic),
    )


def thalamus_input(
    state: BrainState, weights: Mapping[str, Any], retrieval: RetrievalSet | None
) -> ThalamusInput:
    """What the hippocampus retrieved *this tick*, and the stacks admission is judged relevant to.

    **Stamp-tested** (§ Deliverable 1): a hippocampus that declined this tick reaches the thalamus
    as `None`, not as last tick's retrieval.
    """
    return ThalamusInput(
        task_id=state.task_id,
        tick=state.tick,
        weights=dict(weights),
        retrieval=_this_tick(retrieval, state.tick),
        goals=list(state.goals),
        units=list(state.units),
    )


def basal_ganglia_input(
    state: BrainState,
    weights: Mapping[str, Any],
    admitted: AdmittedContext | None,
    workspace_root: str,
) -> BasalGangliaInput:
    """The pending unit, this tick's admitted context, and the constraints the veto reads.

    Exactly the two arms of the catastrophic-only predicate and nothing that would let the gate
    choose (folded: T-13).

    **Stamp-tested, the same way and by the same function** (§ Deliverable 1): a thalamus that
    declined this tick reaches the gate as `None`, which is the gate's **defined empty input** — a
    pending unit with no admitted context this tick. The veto still always runs, because neither
    of its two arms reads this slot.
    """
    return BasalGangliaInput(
        task_id=state.task_id,
        tick=state.tick,
        weights=dict(weights),
        pending_unit=pending_unit(state),
        admitted=_this_tick(admitted, state.tick),
        constraints=list(state.constraints),
        workspace_root=workspace_root,
    )


def monitor_input(
    state: BrainState,
    weights: Mapping[str, Any],
    *,
    executor_summary=None,
    vetoed_unit_id: str | None = None,
) -> MonitorInput:
    """The projected `unit_windows` slice — the six detectors' only input — and this tick's work.

    History reaches the anterior cingulate as *state*, which is how the detectors get windows
    without any node opening a trace file (folded: Ruling 16, decision 25).
    """
    return MonitorInput(
        task_id=state.task_id,
        tick=state.tick,
        weights=dict(weights),
        goals=list(state.goals),
        units=list(state.units),
        unit_windows={
            unit_id: list(rows) for unit_id, rows in state.unit_windows.items()
        },
        trap_dismissals={
            unit_id: dict(rows) for unit_id, rows in state.trap_dismissals.items()
        },
        executor_summary=executor_summary,
        vetoed_unit_id=vetoed_unit_id,
    )


def _withheld_record(value: Any) -> dict[str, Any]:
    """The record a withheld value reaches a seat as: its text's size and digest, never the text.

    A `str` is its own text. Any other JSON value — a member's report left under a withheld id —
    is measured as its sorted, compact JSON text, so no value under a withheld id rides.
    """
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    data = text.encode("utf-8")
    return {
        WITHHELD_KEY: True,
        UTF8_BYTES_KEY: len(data),
        SHA256_KEY: hashlib.sha256(data).hexdigest(),
    }


def _file_bodies_withheld(
    summary: ExecutorSummary | None, units: Sequence[WorkUnit]
) -> ExecutorSummary | None:
    """`latest.dispatch` with each file body replaced by its record (§ Deliverable 2, reduction 1).

    The unit is found by the summary's `unit_id` exactly as `observations.fill_file_contains()`
    finds it, so the ids reduced are the ids the fill wrote. An id the unit marks `FILE_CONTAINS`,
    or no longer declares under any kind (a stale id from a revised `expected` list, R3-F1 (a),
    X43), is withheld; a value under an id the unit declares under another kind passes unchanged,
    and an absent id stays absent. The match is not recomputed.
    """
    if summary is None:
        return None
    unit = next((one for one in units if one.id == summary.unit_id), None)
    if unit is None:
        return summary
    file_ids = {
        expectation.id
        for expectation in unit.expected
        if expectation.kind is ExpectationKind.FILE_CONTAINS
    }
    passed = {expectation.id for expectation in unit.expected} - file_ids
    values = {
        key: value if key in passed else _withheld_record(value)
        for key, value in summary.expectation_values.items()
    }
    return summary.model_copy(update={"expectation_values": values})


def _summaries_as_ids(admitted: AdmittedContext | None) -> AdmittedContext | None:
    """`latest.thalamus` with each admitted summary replaced by its own id (reduction 2)."""
    if admitted is None:
        return None
    return admitted.model_copy(
        update={
            "admitted": [
                item.model_copy(
                    update={
                        "summary": (
                            item.episode_id if item.episode_id is not None else item.admitted_id
                        )
                    }
                )
                for item in admitted.admitted
            ]
        }
    )


def _retrieval_without_text(retrieval: RetrievalSet | None) -> RetrievalSet | None:
    """`latest.hippocampus` with every candidate's `text` set to `None` (reduction 3)."""
    if retrieval is None:
        return None
    return retrieval.model_copy(
        update={
            "candidates": [
                candidate.model_copy(update={"text": None}) for candidate in retrieval.candidates
            ]
        }
    )


def _seat_latest(state: BrainState) -> LatestOutputs:
    """A deep copy of `state.latest`, § Deliverable 2's three bodies withheld, every slot kept."""
    latest = state.latest.model_copy(deep=True)
    return latest.model_copy(
        update={
            "dispatch": _file_bodies_withheld(latest.dispatch, state.units),
            "thalamus": _summaries_as_ids(latest.thalamus),
            "hippocampus": _retrieval_without_text(latest.hippocampus),
        }
    )


def workspace(state: BrainState) -> Workspace:
    """The compressed workspace every seat reads, rebuilt from committed state each tick.

    `latest` is a deep copy of `state.latest` with three bodies withheld
    (`the build specification (not in this mirror)` § Deliverable 2): `latest.dispatch`'s file bodies
    become records, `latest.thalamus`'s admitted summaries become their ids, and
    `latest.hippocampus`'s candidate texts become `None`. `admitted` is `state.latest.thalamus`
    unchanged, so the admitted bodies arrive exactly once. `state` is never mutated.
    """
    return Workspace(
        task_id=state.task_id,
        tick=state.tick,
        goals=list(state.goals),
        latest=_seat_latest(state),
        admitted=state.latest.thalamus,
        last_mismatch_class=(
            state.latest.manager.mismatch_class if state.latest.manager is not None else None
        ),
        resolved_interrupts=list(state.resolved_interrupts),
        modulators=state.modulators,
        constraints=list(state.constraints),
    )
