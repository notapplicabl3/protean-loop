"""Composing the per-tick `UnitObservation` and maintaining the baselines it is derived against.

`the build specification (not in this mirror)` § Deliverable 2's `UnitObservation` and `PathBaseline` rows,
and § Deliverable 3's boundary rule: "one is composed only for a unit that produced an
`ExecutorSummary` this tick or was vetoed: **a planner or director tick composes none**, so an
escalation never feeds the next escalation" (the operator's over-firing constraint, folded: T-8).

**`change_bytes` is runtime-derived, never seat-reported** (folded: T-9). Per path: `0` when the
content hash matches the committed baseline, `abs(size − baseline.size)` when it differs, and
the full size for a path newly created or removed. A path absent from the newest summary keeps
its baseline and counts zero, so a unit that stopped touching a file does not read as a large
delta.

**It is state, not an artifact** (folded: U-7). The row is appended to
`BrainState.unit_windows[unit_id]` inside the checkpoint and carries no key of its own; the
window is trimmed to `BrainState.window_len`, which is derived from the anterior cingulate's own
thresholds so retuning one retunes the window.

**A vetoed tick is a failing observation with zero change**, which is what makes the veto visible
to the detectors instead of a hole in the window.

**Build A.1 adds the wave's merge and the suppression that keys on it**
(`the build specification (not in this mirror)` § Deliverable 3). A dispatch wave's members merge into
**one** `ExecutorSummary` per field before the monitor grades — one observation per unit per
tick, whatever the fan-out — and a wave that merged `partial` or `conflicted` composes **no
observation row at all**. The inherited quotation above uses the retired planner name:
under A.1 a manager tick with a complete wave can produce a row. A tick with no summary and no
veto produces none; a veto produces a failing row with zero change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from protean.nodes.vocabulary import EXPECTATION_PATH
from protean.runtime.seat import IllegalReturn
from protean.state.brain_state import BrainState
from protean.state.enums import ExpectationKind
from protean.state.enums import MismatchClass
from protean.state.inputs import (
    WAVE_COMPLETE,
    WAVE_CONFLICTED,
    WAVE_PARTIAL,
)
from protean.state.outputs import AdmittedContext, MonitorVerdict
from protean.state.primitives import (
    PathBaseline,
    UnitObservation,
    WorkUnit,
    WorkspaceObservation,
)
from protean.state.seats import ExecutorSummary

#: What `UnitObservation.redirect_by` records: the tier whose redirect landed on this unit's
#: goal this tick. It is the Misleading detector's marker, so it names *who*, not *what*.
REDIRECT_BY_DIRECTOR = "director"

#: The two wave statuses that suppress the tick's observation row (§ Deliverable 3): against a
#: partial or a conflicted observation the monitor grades **no `expected` predicate at all**, the
#: unit stays `PENDING` and the mismatch streak is untouched — so an absence never scores as a
#: unit mismatch and one disagreement never scores as a failure.
SUPPRESSING_WAVE_STATUSES: tuple[str, ...] = (WAVE_PARTIAL, WAVE_CONFLICTED)


@dataclass(frozen=True, slots=True)
class WaveMerge:
    """One dispatch wave's returns, merged into the single observed state the monitor grades.

    `the build specification (not in this mirror)` § Deliverable 3, "The merge is defined per field", and
    decision 17: "Fan-out is an implementation of a unit's work, never a multiplication of
    units." A wave may hold several members; its returns merge into **one** `ExecutorSummary`
    before the monitor grades, because the monitor reads `executor_summary`, singular.

    `conflicting_paths` is the list the conflicted rule names — it is carried here rather than on
    the merged summary because `ExecutorSummary` is contract 2's and this build amends it in
    exactly the ways § Scaffold clause item 2 enumerates, none of which is a field.
    """

    summary: ExecutorSummary | None
    status: str
    conflicting_paths: tuple[str, ...] = ()
    conflicting_predicate_ids: tuple[str, ...] = ()
    failed_members: tuple[int, ...] = ()


def merge_wave(
    returns: Sequence[tuple[int, ExecutorSummary | None]], *, tick: int
) -> WaveMerge:
    """The wave's members → one `ExecutorSummary`, merged **per field** exactly as stated.

    `observations` **union** under the path-conflict rule; `expectation_values` merged **per
    predicate id**, any disagreement on one id marking the wave `conflicted`; `cited_ids`
    **union**; `exit_code` the **worst**; `narrative` concatenated **in `member#` order**; and
    `unit_id` **identical across every member** — a wave whose members name two units is an
    **illegal return** rather than a merge (§ Deliverable 3).

    **Interrupts are not merged at all** (folded: S-A52): each member raises its own under its
    own widened id, which is why nothing here reads the `interrupt` slot.

    A member with no legal return is a **failed member** and the wave is `partial`; two members
    disagreeing about one path or one predicate id make it `conflicted`. A conflicted wave is a
    partial wave, **not** a containment fault: nothing was misconfigured, two members disagreed,
    which is a fact about the work.
    """
    ordered = sorted(returns, key=lambda item: item[0])
    answered = [(number, item) for number, item in ordered if item is not None]
    failed = tuple(number for number, item in ordered if item is None)
    if not answered:
        return WaveMerge(summary=None, status=WAVE_PARTIAL, failed_members=failed)

    unit_ids = {item.unit_id for _number, item in answered}
    if len(unit_ids) > 1:
        raise IllegalReturn(
            f"a wave's members name one unit and are merged into one observation; these name "
            f"{sorted(unit_ids)} — an illegal return, not a merge (§ Deliverable 3)"
        )

    seen_paths: dict[str, WorkspaceObservation] = {}
    conflicting_paths: list[str] = []
    values: dict[str, Any] = {}
    conflicting_ids: list[str] = []
    cited: list[str] = []
    narratives: list[str] = []
    exit_code = 0
    for _number, item in answered:
        for observation in item.observations:
            prior = seen_paths.get(observation.path)
            if prior is None:
                seen_paths[observation.path] = observation
            elif prior != observation and observation.path not in conflicting_paths:
                conflicting_paths.append(observation.path)
        for key, value in item.expectation_values.items():
            if key in values and values[key] != value:
                if key not in conflicting_ids:
                    conflicting_ids.append(key)
                continue
            values[key] = value
        for cited_id in item.cited_ids:
            if cited_id not in cited:
                cited.append(cited_id)
        if item.narrative:
            narratives.append(item.narrative)
        exit_code = max(exit_code, item.exit_code)

    merged = ExecutorSummary(
        tick=tick,
        unit_id=next(iter(unit_ids)),
        narrative="\n".join(narratives),
        observations=list(seen_paths.values()),
        exit_code=exit_code,
        expectation_values=values,
        cited_ids=cited,
    )
    if conflicting_paths or conflicting_ids:
        status = WAVE_CONFLICTED
    elif failed:
        status = WAVE_PARTIAL
    else:
        status = WAVE_COMPLETE
    return WaveMerge(
        summary=merged,
        status=status,
        conflicting_paths=tuple(conflicting_paths),
        conflicting_predicate_ids=tuple(conflicting_ids),
        failed_members=failed,
    )


#: The largest file, in bytes, `fill_file_contains` reads for a `FILE_CONTAINS` predicate. A
#: builder's default (E64, on `triggers.py`'s `CONTEXT_BOUND` precedent): it caps what one
#: predicate grows the checkpoint's `latest.dispatch` by. A larger file is refused, never truncated.
FILE_CONTAINS_BOUND: Final[int] = 262_144


def fill_file_contains(
    summary: ExecutorSummary, units: Sequence[WorkUnit], workspace_path: str
) -> ExecutorSummary:
    """The merged summary with every `FILE_CONTAINS` value **observed from the clone**.

    `the build specification (not in this mirror)` § Deliverable 5 (A.2 L25, Option B) and § Scaffold clause
    item 2(e): the one amended reading of contract 2's `expectation_values`. The runtime calls it
    after `merge_wave()` returns and before the monitor's projection, so the monitor grades, and
    the checkpoint commits as `latest.dispatch`, what the workspace holds. The committed value is
    the text, and a seat receives a bounded record of it (`the build specification (not in this mirror)`
    § Deliverable 2). The rules, each as stated:

    - **Per predicate.** For each `FILE_CONTAINS` expectation of the summary's unit, found in
      `units` by the summary's `unit_id`, the file at its `path` argument is read under the task
      workspace and **the file's text as read** is written into `expectation_values[id]`. The text
      is the file's bytes decoded as UTF-8, with no newline translation. Every other kind's value,
      and every id no `FILE_CONTAINS` expectation names, passes through untouched.
    - **Realpath-confined.** The path is read only if its realpath lies inside the workspace's
      realpath. A symlink, a `..` or an absolute path that leaves the workspace is **not read**.
      The gate's lexical path veto (`brain/nodes/basal_ganglia/NODE.md`) resolves no symlink;
      this confinement is the read's own floor, not a second veto.
    - **The runtime's read wins.** A member-reported value for the id is replaced, because the
      summary is "observed, not asserted" (`ExecutorSummary`).
    - **A missing file or a refused path deletes and writes nothing** (F4). Any member-reported
      value for that id is removed and none is written, so the id ends the fill absent and the
      armed kind grades it as a failure. A path that cannot be resolved, is not a regular file, or
      whose read or UTF-8 decode fails is handled the same way.
    - **A file over `FILE_CONTAINS_BOUND` is refused, never truncated** (E64). Its size is
      measured before any read, and a regular file larger than the bound is handled exactly as a
      missing file: the id ends the fill absent. A file at the bound is read whole.
    - **No workspace path, no fill.** With `workspace_path` empty, the summary is returned as it
      came in: no wave can have run, since the desk refuses a wave without a workspace.
    - **`merge_wave()` is untouched**, so a wave its members made `conflicted` on the id stays
      conflicted and the monitor grades nothing against it. **A replay re-reads the clone**, since
      the helper runs on every pass that merges a wave, restored or re-run.

    It reads the workspace and never writes it. Its one output is the returned copy
    (`model_copy`); the summary handed in is not mutated.
    """
    if not workspace_path:
        return summary
    unit = next((one for one in units if one.id == summary.unit_id), None)
    if unit is None:
        return summary
    root = Path(workspace_path).resolve()
    values = dict(summary.expectation_values)
    for expectation in unit.expected:
        if expectation.kind is not ExpectationKind.FILE_CONTAINS:
            continue
        values.pop(expectation.id, None)
        try:
            target = (root / str(expectation.arguments.get(EXPECTATION_PATH, ""))).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                continue
            if target.stat().st_size > FILE_CONTAINS_BOUND:
                continue
            values[expectation.id] = target.read_bytes().decode("utf-8")
        except (OSError, ValueError):
            continue
    return summary.model_copy(update={"expectation_values": values})


def change_bytes(
    summary: ExecutorSummary, baselines: Mapping[str, PathBaseline]
) -> tuple[dict[str, int], list[str]]:
    """Per-path change volume against the committed baselines, and the paths that are new."""
    changes: dict[str, int] = {}
    new_paths: list[str] = []
    for observation in summary.observations:
        baseline = baselines.get(observation.path)
        if baseline is None:
            new_paths.append(observation.path)
            changes[observation.path] = observation.size_bytes
        elif baseline.content_hash == observation.content_hash:
            changes[observation.path] = 0
        else:
            changes[observation.path] = abs(observation.size_bytes - baseline.size_bytes)
    return changes, new_paths


def updated_baselines(
    summary: ExecutorSummary,
    baselines: Mapping[str, PathBaseline],
    tick: int,
    skip_paths: Sequence[str] = (),
) -> dict[str, PathBaseline]:
    """The committed baselines after this tick. A path not touched keeps its own.

    **`skip_paths` is the conflicted wave's rule** (`the build specification (not in this mirror)`
    § Deliverable 3, folded: S-A32): when two members disagreed about one path, the baselines
    update from the **non-conflicting paths only** — "one disagreement does not poison the paths
    nobody disputed". Empty on every other tick, which is every tick build 1, 2 and 3 ran.
    """
    skipped = set(skip_paths)
    updated = dict(baselines)
    for observation in summary.observations:
        if observation.path in skipped:
            continue
        updated[observation.path] = PathBaseline(
            size_bytes=observation.size_bytes,
            content_hash=observation.content_hash,
            tick=tick,
        )
    return updated


def uncited_ratio(summary: ExecutorSummary, admitted: AdmittedContext | None) -> float:
    """The share of the seat's citations that name material never admitted — Progression's
    signal: "output beyond what is understood"."""
    if not summary.cited_ids:
        return 0.0
    known: set[str] = set()
    if admitted is not None:
        for item in admitted.admitted:
            known.add(item.admitted_id)
            if item.episode_id is not None:
                known.add(item.episode_id)
    unknown = [cited for cited in summary.cited_ids if cited not in known]
    return len(unknown) / len(summary.cited_ids)


def compose(
    *,
    tick: int,
    unit: WorkUnit,
    verdict: MonitorVerdict | None,
    summary: ExecutorSummary | None,
    admitted: AdmittedContext | None,
    baselines: Mapping[str, PathBaseline],
    vetoed: bool,
    abandoned: bool = False,
    redirect_by: str | None = None,
    mismatch_class: MismatchClass | None = None,
    wave_status: str | None = None,
) -> UnitObservation | None:
    """One row for one unit, for a tick that produced an `ExecutorSummary` or was vetoed.

    **`None` means no row at all, and it keys on a wave having run**
    (`the build specification (not in this mirror)` § Deliverable 3, folded: S-A69): a tick whose
    dispatch wave merged `partial` or `conflicted` composes **no observation row** — no
    `vetoed=True`, no streak increment — because an absence and a disagreement are facts about
    the work rather than a failing tick. A **wave-less tick, a vetoed tick and a director tick
    compose exactly what they compose today**: the suppression reads `wave_status`, never the
    summary's absence, and that distinction is load-bearing — the arm below treats a `None`
    summary as a veto, so keying on the field alone would delete the gate's veto from committed
    state on every tick that never dispatched.
    """
    if wave_status in SUPPRESSING_WAVE_STATUSES:
        return None
    if vetoed or summary is None:
        return UnitObservation(
            tick=tick,
            unit_revision=unit.revision,
            failed_predicate_ids=[expectation.id for expectation in unit.expected],
            passed_predicate_ids=[],
            change_bytes={},
            change_bytes_total=0,
            paths_new=[],
            abandoned=abandoned,
            vetoed=True,
            uncited_ratio=0.0,
            redirect_by=redirect_by,
            mismatch_class=mismatch_class,
        )

    changes, new_paths = change_bytes(summary, baselines)
    return UnitObservation(
        tick=tick,
        unit_revision=unit.revision,
        failed_predicate_ids=list(verdict.failed_predicate_ids) if verdict else [],
        passed_predicate_ids=list(verdict.passed_predicate_ids) if verdict else [],
        change_bytes=changes,
        change_bytes_total=sum(changes.values()),
        paths_new=new_paths,
        abandoned=abandoned,
        vetoed=False,
        uncited_ratio=uncited_ratio(summary, admitted),
        redirect_by=redirect_by,
        mismatch_class=mismatch_class,
    )


def append_window(state: BrainState, unit_id: str, row: UnitObservation) -> None:
    """Append the row and trim to `window_len`. The window is bounded, per unit."""
    window: list[UnitObservation] = list(state.unit_windows.get(unit_id, []))
    window = [existing for existing in window if existing.tick != row.tick]
    window.append(row)
    window.sort(key=lambda item: item.tick)
    if state.window_len > 0:
        window = window[-state.window_len :]
    state.unit_windows = {**state.unit_windows, unit_id: window}


def window_of(state: BrainState, unit_id: str) -> Sequence[UnitObservation]:
    """One unit's committed window."""
    return state.unit_windows.get(unit_id, [])
