"""P4's writer: project memory keyed by node, at pair granularity, and the cross-project split.

`the build specification (not in this mirror)` § Deliverable 5 (whole), § Directional decisions 19 and 22,
§ Rulings 12, § Build process leg 4, § Named assumptions 5, § Out of scope (the tick-time
retrieval bullet), § Resolutions A1-6, S-2, S-9, S-14, S-17, and § DoD rows L8 and N6.

**Build 3 is the first writer of `brain/projects/`** (`DIGEST:86` [B], § Rulings 12). Build 1
created the directory and wrote nothing into it; every line below is the first of its kind, and
the whole store is gitignored — which is why `SleepReport.project_memory` carries every record
*in full* and is the only review surface this half has (row N6, § Automation gate).

**One line per admissible or excluded pair, plus one summary line per run, per node** (folded:
S-9). Pair granularity is what makes P1's `evidence` name every `ref` exactly across runs: the
persistence floor's second task is read back out of these lines and never off another task's node
traces (decision 22). An excluded pair is written too — a rising exclusion count in one project's
memory is the same defect detector the report's `excluded` map is.

**The pairs written are this run's own** (ledger `D10-3`). A pair the window read back out of an
earlier run's memory is not re-written here; `ProjectMemoryRecord.dedupe_key()` carries `sleep_id`
precisely so that the *next* run's reading of the same `ref` is a second line rather than a
collision, and re-sleeping one run twice is a silent no-op through `append_keyed()`.

**`consumed_by` is what this run actually spent — applied updates *and* compiled habits**
(folded: S-17, ledger `D8-8`, `D16-6`). `weights.consumption_map()` produces
`ref → {key: update id}` and `procedure_consumption_map()` below produces
`ref → {"procedures": procedure id}`; this module persists both merged, so the next run's window
subtracts exactly the pairs an applied update or a compiled procedure already spent. A withheld
update spends nothing, and a rejected candidate spends nothing. The procedure half is reachable
because `run.py` runs the procedures phase **before** this one and threads its result onto the
argument, the way it threads the weights phase's (ledger `D16-6`).

**The reader is not here** (ledger `D10-5`). `weights.read_project_memory()` is the floor's
reader and landed with order W3; this module is the writer, the `key` resolver and the split.
`memory.py` reads `weights.py` for both — one implementation of the consumption map, one of the
signal→key map, and no second copy of either.

**The cross-project split, stated once** (§ Deliverable 5, folded: S-2, S-14). A `WeightUpdate` or
a `Procedure` lands under `brain/nodes/` only when its evidence spans ≥ 2 tasks in ≥ 2 named
projects, or when every task in its evidence ran under `_root`; anything else accumulates in that
project's memory and moves no cross-project prior. `weights.decide()` carries its own arm of this
rule and the two agree on every window row L8 grades — they diverge on a mixed `_root`-plus-one-
named union, which is ledger `D10-6`'s entry and `weights.py`'s to settle, never this module's.

**Tick-time retrieval is out of scope.** Nothing here is read at a tick: no node input model gains
a field, no `NODE.md` `## Reads` list changes, and `candidate_window` stays task-local. The two
readers are sleep itself and — in order W6 — the runtime's seat step, neither of them a node
(decision 19, folded: A1-6).

**Zero model calls, by construction** (decision 10). This module sits inside the static grep's
walked set and names no binary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from protean import config
from protean.brain.jsonl import append_keyed
from protean.runtime import paths as paths_module
from protean.runtime.paths import BrainPaths
from protean.sleep.evidence import Pair
from protean.sleep.report import ProjectMemoryPhase
from protean.sleep.weights import (
    REQUIRED_TASKS,
    consumption_map,
    named_projects,
    promotes_to_node_folder,
    rules_for,
)
from protean.state.sleep import (
    Procedure,
    ProjectMemoryRecord,
    ProjectMemorySummary,
    WeightUpdate,
)

if TYPE_CHECKING:  # pragma: no cover - the seam's own type, resolved by dotted path at runtime
    from protean.sleep.run import PhaseInput

#: What a summary line takes in place of a pair's `ref` in the append key. A `ref` is
#: `TraceRecord.prediction_key()` — `task:tick:node:tier:prediction` — so no pair can collide
#: with it, and one run contributes at most one summary line per node file.
SUMMARY_KEY: Final[str] = "summary"

#: `consumed_by`'s key for the procedure half of S-17, beside the weights keys a
#: `WeightUpdate` contributes. Defined here rather than in `sleep.habits`, which imports
#: this module: one implementation of the map, one of the key, and no second copy (D16-6).
PROCEDURE_CONSUMPTION_KEY: Final[str] = "procedures"


# --------------------------------------------------------------------------------------
# The nullable `key`
# --------------------------------------------------------------------------------------


def weights_key_of(signal: str) -> str | None:
    """The weights key a signal funds, when it funds exactly one (ledger `D10-2`).

    `None` for a signal that maps to no key — `dispatch_expectations`, `gate_unit_survives`,
    which still tally as evidence for procedure candidacy — and `None` for a signal that maps to
    several, which is every mapped signal in the landed `SIGNAL_KEY_MAP`. Which key a pair has
    actually funded is `consumed_by`'s question, per `(node, key)` (folded: S-17), and
    `weights._memory_matches()` matches on `(node, signal)` for exactly that reason.
    """
    rules = rules_for(signal)
    return rules[0].key if len(rules) == 1 else None


# --------------------------------------------------------------------------------------
# The cross-project split — one implementation, called by the weights and procedure halves
# --------------------------------------------------------------------------------------


# `named_projects()` and `promotes_to_node_folder()` are `sleep.weights`'s — the ONE
# implementation of § Deliverable 5's split, re-exported here for the writer and W6 (D10-6).


def cross_project_reason(projects: Sequence[str], tasks: Sequence[str]) -> str:
    """Why this evidence stayed in the project's memory. Empty when it promotes."""
    if promotes_to_node_folder(projects=projects, tasks=tasks):
        return ""
    named = named_projects(projects)
    return (
        f"cross-project rule: the evidence spans {len(named)} named project(s) "
        f"({', '.join(named)}) across {len(set(tasks))} task(s); brain/nodes/ takes "
        f"{paths_module.ROOT_PROJECT_SLUG!r}-slug evidence, or >= 2 named projects across "
        f">= {REQUIRED_TASKS} tasks"
    )


def procedures_dir(
    brain: BrainPaths, *, slug: str, projects: Sequence[str], tasks: Sequence[str]
) -> Path:
    """Where a compiled habit lands: the node folder, or that project's memory (folded: S-2).

    The split is the *path*, never a field on P2 — the same way a `WeightUpdate`'s is. Order W6
    calls this rather than re-deciding it, so "node folders hold only cross-project priors" has
    one implementation for both halves of what sleep writes.
    """
    if promotes_to_node_folder(projects=projects, tasks=tasks):
        return brain.node_procedures(config.CORTEX_NODE)
    return brain.project_procedures(slug)


def procedure_consumption_map(
    procedures: Sequence[Procedure], sleep_id: str
) -> dict[str, dict[str, str]]:
    """`ref → {"procedures": id}` for every pair a compiled habit consumed (ledger `D16-6`).

    `weights.consumption_map()`'s shape for the other half of S-17 — "a pair credited to a
    compiled procedure is consumed too". `sleep.habits` delegates to this rather than owning it,
    because it imports this module for `procedures_dir()` and the reverse import would be a
    cycle; the writer below is the one caller that persists what it returns.
    """
    consumed: dict[str, dict[str, str]] = {}
    for procedure in procedures:
        identifier = f"{sleep_id}:{config.CORTEX_NODE}/{procedure.procedure_id}"
        for ref in procedure.compiled_from.refs:
            consumed.setdefault(ref, {})[PROCEDURE_CONSUMPTION_KEY] = identifier
    return consumed


# --------------------------------------------------------------------------------------
# The lines
# --------------------------------------------------------------------------------------


def line_key(payload: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """`ProjectMemoryRecord.dedupe_key()` over a written line — a summary keyed alongside.

    P4's own key rather than a second one: a re-run of the same sleep over the same source is a
    silent no-op, and the *next* run's reading of one `ref` is a new line because `sleep_id` is
    inside the key (`state/sleep.py`'s own note).
    """
    return (
        str(payload.get("sleep_id", "")),
        str(payload.get("project", "")),
        str(payload.get("node", "")),
        str(payload.get("ref", SUMMARY_KEY)),
    )


def pair_record(
    pair: Pair,
    *,
    slug: str,
    sleep_id: str,
    consumed: Mapping[str, Mapping[str, str]],
) -> ProjectMemoryRecord:
    """One pair's line — admissible or excluded, both written (folded: S-9)."""
    return ProjectMemoryRecord(
        project=slug,
        node=pair.node,
        sleep_id=sleep_id,
        task=pair.task,
        tick=pair.tick,
        ref=pair.ref,
        signal=pair.signal,
        key=weights_key_of(pair.signal),
        matched=pair.matched,
        admissible=pair.admissible,
        excluded_reason=pair.excluded_reason,
        consumed_by=dict(consumed.get(pair.ref, {})),
    )


def summary_record(
    node: str,
    pairs: Sequence[Pair],
    *,
    slug: str,
    sleep_id: str,
    updates: Sequence[WeightUpdate],
    procedures: Sequence[Procedure] = (),
) -> ProjectMemorySummary:
    """The one line that closes a node's file for this run (§ Deliverable 5).

    Counted the way `report.evidence_group()` counts, so a node's summary and the run's report
    are two readings of one set rather than two measurements. `procedures` counts the habits
    this run compiled, which is reachable now that the procedures phase runs before this one
    (ledger `D16-6`, correcting `D10-4`'s standing zero) — and it lands on the cortex node's
    summary alone, because a `Procedure` carries no node and every one of them compiles under
    `cortex`, whichever folder the cross-project split sends it to.
    """
    excluded = {reason: 0 for reason in config.SLEEP_EXCLUSION_REASONS}
    for pair in pairs:
        if not pair.admissible:
            excluded[pair.excluded_reason] = excluded.get(pair.excluded_reason, 0) + 1
    return ProjectMemorySummary(
        project=slug,
        node=next(pair.node for pair in pairs),
        sleep_id=sleep_id,
        admissible=sum(1 for pair in pairs if pair.admissible),
        matched=sum(1 for pair in pairs if pair.admissible and pair.matched),
        excluded=excluded,
        updates=sum(1 for row in updates if row.applied and str(row.node) == node),
        procedures=len(procedures) if node == config.CORTEX_NODE else 0,
    )


# --------------------------------------------------------------------------------------
# The phase
# --------------------------------------------------------------------------------------


def _by_node(pairs: Sequence[Pair]) -> dict[str, list[Pair]]:
    """This run's pairs, grouped by the node that owns them, in `NODE_ORDER`.

    Ordered by the tick cycle's own order rather than by first appearance, so two runs of one
    fixture write the same files in the same sequence (row N3's exact-equality half).
    """
    grouped: dict[str, list[Pair]] = {}
    for pair in pairs:
        grouped.setdefault(str(pair.node), []).append(pair)
    return {node: grouped[node] for node in config.NODE_ORDER if node in grouped}


def write_project_memory(argument: "PhaseInput") -> ProjectMemoryPhase:
    """The project-memory phase: one line per pair, one summary per node, under the task's slug.

    Resolved by dotted path from `protean.sleep.run` (D5-7), which hands over one frozen
    `PhaseInput` — carrying the weights and procedures phases' own results (ledger `D10-1`,
    `D16-6`) — and takes back the phase. `dry_run` derives every line and writes no file under
    `brain/`: the decision is made here, at the write, because only this module knows what it
    would have written.

    **Every sleep run writes project memory** (decision 22): a projectless root accumulates under
    `_root`, which is the arm run 1's own brain root exercises and the reason the ≥ 2-task floor
    is reachable on this repo at all.
    """
    slug = (
        argument.pairs.project
        or argument.records.project
        or paths_module.ROOT_PROJECT_SLUG
    )
    updates = argument.weights.updates if argument.weights is not None else ()
    compiled = argument.procedures.written if argument.procedures is not None else ()
    consumed = consumption_map(updates, argument.sleep_id)
    for ref, entry in procedure_consumption_map(compiled, argument.sleep_id).items():
        consumed.setdefault(ref, {}).update(entry)

    records: list[ProjectMemoryRecord] = []
    summaries: list[ProjectMemorySummary] = []
    written: list[Path] = []

    for node, pairs in _by_node(argument.pairs.pairs).items():
        lines = [
            pair_record(pair, slug=slug, sleep_id=argument.sleep_id, consumed=consumed)
            for pair in pairs
        ]
        closing = summary_record(
            node,
            pairs,
            slug=slug,
            sleep_id=argument.sleep_id,
            updates=updates,
            procedures=compiled,
        )
        records.extend(lines)
        summaries.append(closing)
        if argument.dry_run:
            continue
        path = argument.brain.project_learning(slug, node)
        appended = False
        for row in (*lines, closing):
            if append_keyed(path, row.model_dump(mode="json"), key_fn=line_key) is not None:
                appended = True
        if appended:
            written.append(path)

    return ProjectMemoryPhase(
        records=tuple(records), summaries=tuple(summaries), files=tuple(written)
    )


__all__ = [
    "PROCEDURE_CONSUMPTION_KEY",
    "SUMMARY_KEY",
    "cross_project_reason",
    "line_key",
    "named_projects",
    "pair_record",
    "procedure_consumption_map",
    "procedures_dir",
    "promotes_to_node_folder",
    "summary_record",
    "weights_key_of",
    "write_project_memory",
]
