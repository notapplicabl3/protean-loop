"""P2's compiler: candidates, the three gates, the compiled `SeatScript`, and withdrawal.

`the build specification (not in this mirror)` § Deliverable 4 (the compilation half; the matcher and the
seat step are order W7's), § Directional decisions 13 and 21, § Rulings 6 and 16, § Build process
leg 5 and its "Legs 1 and 5" paragraph, § Named assumptions 9, § Resolutions A1-2, A1-9, S-3, S-4,
and § DoD rows L6, L8 and N4.

**A procedure is a compiled `SeatScript` and nothing more exotic** (decision 13). Everything this
module writes is a mapping `protean.cortex.scripts.parse_script()` reads unmodified, plus the five
provenance fields that loader ignores — `procedure_id`, `compiled_from`, `hits_required`, `seed:
false`, `schema_version`. There is no second format and no post-processing step: the file on disk
is `Procedure.script_payload()`, dumped as YAML.

**Keyed on `goal_digest`, and on nothing the request carries** (folded: S-3, ledger `D16-2`). A
compiled condition binds `goal_digest` — `sha256[:16]` of the served goal's *text*, computed by
`scripts.goal_digest_of()`, the one implementation the matcher calls too — and binds nothing else.
It never binds `unit_id`, which the manager mints per task and which never recurs; and no field of
anything below is derived from a trace record's input-signature digest or from the request bytes —
row L6 makes that a literal grep over this file, so neither name appears anywhere in it. The
archive settles why: its three `u-branch` ticks carry three different digests over one
byte-identical condition set.

**The manager and the director, and no worker call** (decision 21, folded: S-4). An
`ExecutorSummary` is an observation of the workspace that `runtime/observations.py` commits as the
path baselines every later tick is measured against, so a canned dispatch envelope would assert
file states nothing looked at. A dispatch candidate is *formed* and *rejected*, never skipped, so
the report says what the loop nearly learned.

**Three gates, in this order** (§ Deliverable 4, ledger `D16-4`). Admissible first, because
§ Build process's legs 1 and 5 are one argument: run 1's three-tick `u-branch` repeat must not
compile, and *the reason it does not* is that leg 1 classified its driving predicates ungradeable.
Then the tier, then `match_rate == 1.0`, then the **same** persistence floor a weight update
clears — `weights.clears_the_floor()`, called and never copied.

**Un-learning is first-class** (§ Deliverable 4, row N4). A procedure whose hits grade
`matched: false` `hits_required` times consecutively is deleted by the next run, and the deletion
is a line in `SleepReport.procedures` and in the git diff. The hits are P3 `HabitHit` lines under
`brain/state/<task_id>/habit_hits.jsonl`, which order W7 writes; the reader below is deliberately
tolerant of a shape W7 has not yet fixed (ledger `D16-7`).

**Zero model calls, by construction** (decision 10). This module sits inside the static grep's
walked set and names no binary.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import yaml

from protean import config
from protean.brain.jsonl import read_lines
from protean.cortex.scripts import GOAL_PLACEHOLDER, STAMPED_FIELD, goal_digest_of
from protean.runtime import paths as paths_module
from protean.runtime.paths import CHECKPOINT_FILENAME, BrainPaths
from protean.sleep.evidence import Pair, RunRecords
from protean.sleep.memory import (
    PROCEDURE_CONSUMPTION_KEY,
    procedure_consumption_map as _memory_consumption_map,
    procedures_dir,
)
from protean.sleep.report import ProceduresPhase
from protean.sleep.weights import (
    REQUIRED_PAIRS_TIGHTEN,
    REQUIRED_TASKS,
    clears_the_floor,
    read_project_memory,
)
from protean.state.enums import NodeName, Tier
from protean.state.sleep import (
    CompiledFrom,
    Procedure,
    ProcedureResponse,
    RejectedCandidate,
    WithdrawnProcedure,
)

if TYPE_CHECKING:  # pragma: no cover - the seam's own type, resolved by dotted path at runtime
    from protean.sleep.run import PhaseInput

#: The two tiers a procedure may answer (decision 21, folded: S-4). The acting tier is out of
#: scope in build 3 and its candidates are rejected by name rather than filtered out of sight.
ANSWERABLE_TIERS: Final[tuple[Tier, ...]] = (Tier.DIRECTOR, Tier.MANAGER)

#: `<procedure_id>.yaml` under whichever `procedures/` the cross-project split chose.
PROCEDURE_SUFFIX: Final[str] = ".yaml"

_ANSWERABLE_NAMES: Final[frozenset[str]] = frozenset(str(tier) for tier in ANSWERABLE_TIERS)

#: The `procedure_id` shape (ledger `D16-2`): stable across runs, so recompiling one candidate
#: overwrites its file rather than minting a second, and lexically sortable, which is what
#: § Resolutions S-3 makes precedence out of.
PROCEDURE_ID_PREFIX: Final[str] = "habit"

#: The archive's own state directory name — `protean.sleep.evidence`'s literal, restated here
#: because that module exposes it under a private name.
ARCHIVE_STATE_DIRNAME: Final[str] = "state"

#: Every tier's own name, for the two places a raw string is turned back into a `Tier`.
_TIER_NAMES: Final[frozenset[str]] = frozenset(str(tier) for tier in Tier)

#: `ExecutorSummary`, `ManagerPlan` and `DirectorDirection` all declare an `emitter` literal
#: equal to their tier's own name, which is what a journal entry is selected on.
EMITTER_FIELD: Final[str] = "emitter"

#: How a YAML procedure file is written: block style, keys in the model's own order, so a git
#: diff of `brain/nodes/cortex/procedures/` reads like the review artifact row B22 makes of it.
YAML_DUMP: Final[Mapping[str, Any]] = {
    "sort_keys": False,
    "default_flow_style": False,
    "allow_unicode": True,
}


# --------------------------------------------------------------------------------------
# What the run put on disk that `RunRecords` does not carry
# --------------------------------------------------------------------------------------


def run_state_dir(brain: BrainPaths, records: RunRecords) -> Path:
    """Where the run this sleep read keeps its checkpoint and its per-tick journals.

    An archive keeps them under `<source>/state/` and a live root under
    `brain/state/<task_id>/`. `protean.sleep.weights` holds the same resolution under a private
    name; this is the procedures phase's copy of one four-line fact rather than an import of
    another module's underscore.
    """
    source = Path(records.source)
    if source == brain.root:
        return brain.task(records.task).state_dir
    return source / ARCHIVE_STATE_DIRNAME


def goal_texts(brain: BrainPaths, records: RunRecords) -> dict[str, str]:
    """`goal id → text` off the run's **committed** goal stack (ledger `D16-1`).

    `BrainState.goals` is authoritative and the workspace's copy is a projection
    (`state/workspace.py`), so this is the same text `facts_of()` will digest at match time.
    Read raw: a run this sleep did not produce may carry a stack shape a later build wrote, and
    an unreadable checkpoint yields no goal rather than an exception out of the middle of a phase.
    """
    path = run_state_dir(brain, records) / CHECKPOINT_FILENAME
    if not path.is_file():
        return {}
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    state = payload.get("state") or {}
    found: dict[str, str] = {}
    for row in state.get("goals") or []:
        if not isinstance(row, Mapping):
            continue
        identifier, text = row.get("id"), row.get("text")
        if isinstance(identifier, str) and isinstance(text, str):
            found[identifier] = text
    return found


def seat_outputs(brain: BrainPaths, records: RunRecords) -> dict[tuple[int, str], dict[str, Any]]:
    """`(tick, tier) → the journalled cortex output` for that tick (ledger `D16-3`).

    `JournalEntry` is "the seat-envelope store" and its `output` is the decoded seat result, so
    this is where a past run's manager plan or director direction still lives.
    `protean.sleep.evidence._summaries_from()` reads the same files for the dispatch-summary
    half; a tick with a null entry — which a refused seat call writes — contributes nothing.
    """
    state_dir = run_state_dir(brain, records)
    found: dict[tuple[int, str], dict[str, Any]] = {}
    if not state_dir.is_dir():
        return found
    prefix, suffix = paths_module.JOURNAL_PREFIX, paths_module.JOURNAL_SUFFIX
    journals = sorted(
        (
            path
            for path in state_dir.iterdir()
            if path.is_file() and path.name.startswith(prefix) and path.name.endswith(suffix)
        ),
        key=lambda path: int(path.name[len(prefix) : -len(suffix)]),
    )
    for journal in journals:
        for line in read_lines(journal):
            if str(line.get("node")) != str(NodeName.CORTEX):
                continue
            output = line.get("output")
            if not isinstance(output, Mapping):
                continue
            emitter = str(output.get(EMITTER_FIELD, ""))
            if not emitter:
                continue
            found[(int(line.get("tick", -1)), emitter)] = dict(output)
    return found


# --------------------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------------------


def tier_of(pair: Pair) -> str:
    """The tier a cortex pair belongs to, off whichever half of it is committed."""
    record = pair.prediction or pair.outcome
    return "" if record is None or record.tier is None else str(record.tier)


def tier_of_ref(ref: str) -> str:
    """The tier inside a `ref`. `TraceRecord.prediction_key()` is `task:tick:node:tier:prediction`.

    The only way to read a memory line's tier: `ProjectMemoryRecord` carries `node` and `signal`
    and no tier, and widening P2/P4 is order W2's contract, not this order's (ledger `D16-5`).
    """
    parts = ref.split(":")
    return parts[3] if len(parts) >= 5 else ""


def goal_of(pair: Pair, records: RunRecords) -> str:
    """The goal id a cortex pair's prediction names (ledger `D16-1`), or `""`.

    A manager prediction names a unit and the unit names the goal; a director prediction names
    the goal directly. Nothing here reads the request, and nothing reads the signature.
    """
    prediction = pair.prediction
    payload = None if prediction is None else prediction.prediction
    if payload is None:
        return ""
    goal_id = getattr(payload, "goal_id", None)
    if isinstance(goal_id, str) and goal_id:
        return goal_id
    unit_id = getattr(payload, "unit_id", None)
    if isinstance(unit_id, str):
        unit = records.unit(unit_id)
        if unit is not None:
            return unit.goal_id
    return ""


def procedure_id_for(tier: str, digest: str) -> str:
    """`habit-<tier>-<goal_digest>` — stable across runs, lexically sortable (ledger `D16-2`)."""
    return f"{PROCEDURE_ID_PREFIX}-{tier}-{digest}"


@dataclass(frozen=True, slots=True)
class WindowHit:
    """One pair in a candidate's window, from this run or from a project's memory.

    Normalised to one shape so the floor arithmetic never asks where a pair came from — the same
    reason `weights.WindowPair` exists, and the reason row L8's "only in the second run" is a
    property of the window rather than of two code paths.
    """

    ref: str
    task: str
    project: str
    matched: bool
    admissible: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Candidate:
    """One `(tier, goal)` a run repeated, with everything the three gates read.

    Formed over **every** cortex pair, admissible or not, so a candidate that fails a gate is
    reported rather than silently absent — "where the operator sees what the loop *nearly* learned".
    """

    tier: str
    goal_id: str
    goal_digest: str
    hits: tuple[WindowHit, ...] = ()
    #: Every slug the cross-slug union saw for this tier — the ≥ 2-named-projects arm's input.
    projects: tuple[str, ...] = ()

    @property
    def admissible(self) -> tuple[WindowHit, ...]:
        return tuple(hit for hit in self.hits if hit.admissible)

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(sorted({hit.ref for hit in self.admissible}))

    @property
    def tasks(self) -> tuple[str, ...]:
        return tuple(sorted({hit.task for hit in self.admissible}))

    @property
    def matched(self) -> int:
        return sum(1 for hit in self.admissible if hit.matched)

    @property
    def match_rate(self) -> float:
        seen = self.admissible
        return (self.matched / len(seen)) if seen else 0.0

    @property
    def when(self) -> dict[str, str]:
        """The condition a compiled response binds: `goal_digest`, and nothing else."""
        return {"goal_digest": self.goal_digest}

    def ticks(self) -> tuple[int, ...]:
        """This run's own ticks for the candidate, ascending — where its answer was journalled."""
        found: set[int] = set()
        for hit in self.admissible:
            parts = hit.ref.split(":")
            if len(parts) >= 5 and parts[1].isdigit():
                found.add(int(parts[1]))
        return tuple(sorted(found))


def _exclusion_summary(hits: Sequence[WindowHit]) -> str:
    counts: dict[str, int] = {}
    for hit in hits:
        if not hit.admissible:
            counts[hit.reason] = counts.get(hit.reason, 0) + 1
    return ", ".join(f"{reason} x {count}" for reason, count in sorted(counts.items()))


def candidates(argument: "PhaseInput") -> list[Candidate]:
    """Every `(tier, goal)` this run offers, with its window (ledger `D16-5`).

    This run's cortex pairs are grouped by the goal their prediction names; the cross-task half
    is every unconsumed admissible cortex memory line whose `ref` parses to the same tier, under
    the task's own slug. The goal constrains only this run's half, because no landed P4 field
    carries one — and the floor a candidate clears is then literally "the same floor a weight
    update clears", which counts by `(node, signal)` and never by goal.
    """
    slug = (
        argument.pairs.project
        or argument.records.project
        or paths_module.ROOT_PROJECT_SLUG
    )
    texts = goal_texts(argument.brain, argument.records)
    memory = read_project_memory(argument.brain)

    grouped: dict[tuple[str, str], list[WindowHit]] = {}
    for pair in argument.pairs.pairs:
        if pair.node is not NodeName.CORTEX:
            continue
        tier = tier_of(pair)
        goal_id = goal_of(pair, argument.records)
        if not tier or not goal_id:
            continue
        grouped.setdefault((tier, goal_id), []).append(
            WindowHit(
                ref=pair.ref,
                task=pair.task,
                project=pair.project,
                matched=pair.matched,
                admissible=pair.admissible,
                reason=pair.excluded_reason,
            )
        )

    found: list[Candidate] = []
    for (tier, goal_id), hits in sorted(grouped.items()):
        text = texts.get(goal_id, "")
        if not text:
            continue  # no goal text, no digest — a candidate that could bind nothing
        seen = {hit.ref: hit for hit in hits}
        union = {hit.project for hit in hits}
        for record in memory:
            if str(record.node) != config.CORTEX_NODE or not record.admissible:
                continue
            if tier_of_ref(record.ref) != tier:
                continue
            if PROCEDURE_CONSUMPTION_KEY in record.consumed_by:
                continue
            union.add(record.project)
            if record.project != slug:
                continue  # the window is per slug (folded: S-6); the union is the split's input
            seen.setdefault(
                record.ref,
                WindowHit(
                    ref=record.ref,
                    task=record.task,
                    project=record.project,
                    matched=record.matched,
                    admissible=True,
                ),
            )
        found.append(
            Candidate(
                tier=tier,
                goal_id=goal_id,
                goal_digest=goal_digest_of(text),
                hits=tuple(seen[ref] for ref in sorted(seen)),
                projects=tuple(sorted(union)),
            )
        )
    return found


# --------------------------------------------------------------------------------------
# The three gates
# --------------------------------------------------------------------------------------


def rejected_for(candidate: Candidate, reason: str) -> RejectedCandidate:
    """One rejected candidate, in the shape `SleepReport.procedures.rejected` carries."""
    return RejectedCandidate(
        procedure_id=procedure_id_for(candidate.tier, candidate.goal_digest),
        tier=Tier(candidate.tier) if candidate.tier in _TIER_NAMES else None,
        when=dict(candidate.when),
        refs=list(candidate.refs) or sorted({hit.ref for hit in candidate.hits}),
        tasks=list(candidate.tasks) or sorted({hit.task for hit in candidate.hits}),
        reason=reason,
    )


def gate(candidate: Candidate) -> str:
    """The first gate this candidate fails, as the reason the report prints. `""` compiles.

    The order is load-bearing (ledger `D16-4`): admissibility precedes the tier, so run 1's
    three-tick `u-branch` repeat is rejected for the reason § Build process's legs 1 and 5 give
    it — its driving predicates were classified ungradeable — rather than for its tier.
    """
    if not candidate.admissible:
        return (
            f"no admissible driving pair: {len(candidate.hits)} cortex pair(s) on this goal, "
            f"every one excluded ({_exclusion_summary(candidate.hits)}) — order W1's "
            f"classification, never re-decided here"
        )
    if candidate.tier not in _ANSWERABLE_NAMES:
        return (
            f"the {candidate.tier} tier answers no procedure in build 3: an ExecutorSummary is "
            f"an observation the runtime commits as path baselines, so a canned envelope would "
            f"assert file states nothing looked at (decision 21)"
        )
    if candidate.match_rate < 1.0:
        return (
            f"outcome not matched: {candidate.matched}/{len(candidate.admissible)} admissible "
            f"pair(s) graded matched, and a habit compiles only from a window that never failed"
        )
    if not clears_the_floor(
        pairs=len(candidate.admissible), tasks=len(candidate.tasks), loosening=False
    ):
        return (
            f"short of the persistence floor: {len(candidate.admissible)} admissible pair(s) "
            f"across {len(candidate.tasks)} task(s); a habit clears the same floor a weight "
            f"update does — {REQUIRED_PAIRS_TIGHTEN} pairs across >= {REQUIRED_TASKS} tasks"
        )
    return ""


# --------------------------------------------------------------------------------------
# Compilation
# --------------------------------------------------------------------------------------


def compiled_result(payload: Mapping[str, Any], *, goal_id: str) -> dict[str, Any]:
    """The seat's journalled answer, made into a `ScriptedResponse` result (ledger `D16-3`).

    Two edits and no third: `tick` is dropped, because the responder stamps it from the request
    and `ScriptedResponse.parse()` refuses a response that writes it; and every string equal to
    the source run's goal id becomes `$goal`, because a goal id is minted at task start and a
    habit that named the old one would push units onto a goal the new task does not have.
    Work-unit ids are left as compiled: `$unit` resolves to one id and would collapse a plan.
    """

    def _replace(value: Any) -> Any:
        if isinstance(value, str):
            return GOAL_PLACEHOLDER if value == goal_id else value
        if isinstance(value, Mapping):
            return {key: _replace(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_replace(item) for item in value]
        return value

    return {
        key: _replace(value)
        for key, value in payload.items()
        if key != STAMPED_FIELD
    }


def compile_one(
    candidate: Candidate,
    *,
    sleep_id: str,
    records: RunRecords,
    outputs: Mapping[tuple[int, str], Mapping[str, Any]],
) -> Procedure | None:
    """One candidate that passed all three gates → P2, or `None` if the run journalled no answer.

    The **last** tick of the candidate's window in this run is the answer compiled: it is the
    most recent thing the tier said on this goal, and every earlier tick's answer was graded on
    the way to it.
    """
    for tick in reversed(candidate.ticks()):
        payload = outputs.get((tick, candidate.tier))
        if payload is None:
            continue
        return Procedure(
            procedure_id=procedure_id_for(candidate.tier, candidate.goal_digest),
            name=procedure_id_for(candidate.tier, candidate.goal_digest),
            hits_required=REQUIRED_PAIRS_TIGHTEN,
            compiled_from=CompiledFrom(
                sleep_id=sleep_id,
                source=records.source,
                tasks=list(candidate.tasks),
                refs=list(candidate.refs),
            ),
            responses=[
                ProcedureResponse(
                    tier=Tier(candidate.tier),
                    when=dict(candidate.when),
                    result=compiled_result(payload, goal_id=candidate.goal_id),
                )
            ],
        )
    return None


def procedure_path(
    brain: BrainPaths, candidate: Candidate, procedure: Procedure, *, slug: str
) -> Path:
    """Where this habit lands — `memory.procedures_dir()` decides, never a second predicate."""
    directory = procedures_dir(
        brain,
        slug=slug,
        projects=list(candidate.projects),
        tasks=list(candidate.tasks),
    )
    return directory / f"{procedure.procedure_id}{PROCEDURE_SUFFIX}"


def write_procedure(path: Path, procedure: Procedure) -> Path:
    """The YAML file `parse_script()` loads unmodified, provenance header and all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(procedure.script_payload(), **YAML_DUMP), encoding="utf-8"
    )
    return path


def procedure_consumption_map(
    procedures: Sequence[Procedure], sleep_id: str
) -> dict[str, dict[str, str]]:
    """`ref → {"procedures": id}` for every pair a compiled habit consumed (ledger `D16-6`).

    `weights.consumption_map()`'s shape for the other half of S-17 — "a pair credited to a
    compiled procedure is consumed too". **Persisted by this run**: `run.py` runs this phase
    before the memory phase and threads the result onto its argument, so `memory.py`'s writer
    merges what this returns into `ProjectMemoryRecord.consumed_by` beside the applied updates.
    The map itself lives in `memory.py` — this module imports that one for `procedures_dir()`,
    so the reverse import would be a cycle — and this is the compiler-side name for it.
    """
    return _memory_consumption_map(procedures, sleep_id)


# --------------------------------------------------------------------------------------
# Un-learning
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HabitHitLine:
    """One P3 line as this reader needs it, before order W7 fixes the shape (ledger `D16-7`)."""

    procedure_id: str
    task: str
    tick: int
    ref: str
    tier: str = ""


def read_habit_hits(brain: BrainPaths) -> list[HabitHitLine]:
    """Every `habit_hits.jsonl` line on the root, tolerantly (ledger `D16-7`).

    Order W7 writes P3 and has not landed, so this reads the eight fields § Deliverable 4 names
    and *requires* only the four withdrawal joins on. A line it cannot read is skipped rather
    than refused: a reader that raised would make the whole sleep run fail on a shape its author
    has not written yet, and W7 conforms to this or ledgers the divergence.

    Every state directory is walked rather than `brain.task_ids()`: that accessor selects on a
    committed `checkpoint.json`, and the hits of a task are evidence about a *habit* whether or
    not the task that wrote them ever committed.
    """
    found: list[HabitHitLine] = []
    state = brain.state
    if not state.is_dir():
        return found
    for task_dir in sorted(entry for entry in state.iterdir() if entry.is_dir()):
        task_id = task_dir.name
        path = brain.task(task_id).habit_hits
        if not path.is_file():
            continue
        for line in read_lines(path):
            if not isinstance(line, Mapping):
                continue
            procedure_id = line.get("procedure_id")
            ref = line.get("ref")
            task = line.get("task", task_id)
            tick = line.get("tick")
            if not isinstance(procedure_id, str) or not procedure_id:
                continue
            if not isinstance(ref, str) or not isinstance(task, str):
                continue
            if not isinstance(tick, int):
                continue
            found.append(
                HabitHitLine(
                    procedure_id=procedure_id,
                    task=task,
                    tick=tick,
                    ref=ref,
                    tier=str(line.get("tier", "")),
                )
            )
    return sorted(found, key=lambda hit: (hit.task, hit.tick, hit.procedure_id))


def outcomes_by_ref(records: RunRecords) -> dict[str, bool]:
    """`ref → matched`, off the run this sleep is grading — the grade a hit is joined to.

    A habit-answered tick is graded exactly like a model-answered one (§ Deliverable 4), so the
    hit names a cortex prediction and the prediction's outcome is the verdict on the habit.
    """
    graded: dict[str, bool] = {}
    for record in records.outcomes:
        if record.ref is None:
            continue
        graded[str(record.ref)] = bool(getattr(record.outcome, "matched", False))
    return graded


def installed_procedures(brain: BrainPaths, *, slug: str) -> list[tuple[Path, Procedure]]:
    """Every procedure file this root holds, node folder first then the task's own project.

    Read through P2's own model rather than through `parse_script()`: withdrawal needs the
    provenance header — `procedure_id` and `hits_required` — which the loader ignores by design.
    """
    found: list[tuple[Path, Procedure]] = []
    for directory in (
        brain.node_procedures(config.CORTEX_NODE),
        brain.project_procedures(slug),
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(f"*{PROCEDURE_SUFFIX}")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                continue
            found.append((path, Procedure.model_validate(dict(payload))))
    return found


def failed_run(hits: Sequence[HabitHitLine], graded: Mapping[str, bool]) -> int:
    """The **trailing consecutive** hits grading `matched: false` (ledger `D16-7`).

    `WithdrawnProcedure.failed_hits` is documented as consecutive, so one later success clears
    the count — a habit that starts working again is not withdrawn for what it did before.
    """
    count = 0
    for hit in reversed(list(hits)):
        verdict = graded.get(hit.ref)
        if verdict is None:
            continue  # a hit this run holds no grade for counts on neither side
        if verdict:
            break
        count += 1
    return count


def withdraw(
    brain: BrainPaths,
    records: RunRecords,
    *,
    slug: str,
    dry_run: bool,
    keep: Iterable[str] = (),
) -> tuple[list[WithdrawnProcedure], list[Path]]:
    """Delete every habit whose hits stopped grading, and say so (§ Deliverable 4, row N4).

    `keep` is the set of `procedure_id`s this run just compiled: a habit written and withdrawn in
    one run would be a file the report claims twice, and the fresh evidence that compiled it is
    newer than the hits that would retire it.
    """
    graded = outcomes_by_ref(records)
    hits = read_habit_hits(brain)
    protected = set(keep)
    withdrawn: list[WithdrawnProcedure] = []
    deleted: list[Path] = []
    for path, procedure in installed_procedures(brain, slug=slug):
        if procedure.procedure_id in protected:
            continue
        mine = [hit for hit in hits if hit.procedure_id == procedure.procedure_id]
        failed = failed_run(mine, graded)
        if failed < procedure.hits_required:
            continue
        withdrawn.append(
            WithdrawnProcedure(
                procedure_id=procedure.procedure_id,
                path=(
                    path.relative_to(brain.root).as_posix()
                    if path.is_relative_to(brain.root)
                    else str(path)
                ),
                failed_hits=failed,
                hits_required=procedure.hits_required,
                reason=(
                    f"{failed} consecutive habit hit(s) graded matched: false, and the habit "
                    f"cleared a floor of {procedure.hits_required} — withdrawn, so the seat step "
                    f"falls back to a live call on the next matching tick"
                ),
            )
        )
        deleted.append(path)
        if not dry_run:
            path.unlink()
    return withdrawn, deleted


# --------------------------------------------------------------------------------------
# The phase
# --------------------------------------------------------------------------------------


def compile_habits(argument: "PhaseInput") -> ProceduresPhase:
    """The procedures phase: compile what cleared every gate, report the rest, withdraw the dead.

    Resolved by dotted path from `protean.sleep.run` (D5-7), which hands over one frozen
    `PhaseInput` and takes back the phase. `dry_run` derives every candidate, every rejection and
    every withdrawal and writes and deletes **nothing** under `brain/` — the decision is made
    here, at the write, because only this module knows what it would have written.
    """
    slug = (
        argument.pairs.project
        or argument.records.project
        or paths_module.ROOT_PROJECT_SLUG
    )
    outputs = seat_outputs(argument.brain, argument.records)

    written: list[Procedure] = []
    rejected: list[RejectedCandidate] = []
    files: list[Path] = []

    for candidate in candidates(argument):
        reason = gate(candidate)
        if reason:
            rejected.append(rejected_for(candidate, reason))
            continue
        procedure = compile_one(
            candidate,
            sleep_id=argument.sleep_id,
            records=argument.records,
            outputs=outputs,
        )
        if procedure is None:
            rejected.append(
                rejected_for(
                    candidate,
                    f"no journalled {candidate.tier} output for tick(s) "
                    f"{list(candidate.ticks())} — the run recorded the grade and not the answer, "
                    f"so there is nothing to can",
                )
            )
            continue
        written.append(procedure)
        path = procedure_path(argument.brain, candidate, procedure, slug=slug)
        if not argument.dry_run:
            write_procedure(path, procedure)
        files.append(path)

    withdrawn, deleted = withdraw(
        argument.brain,
        argument.records,
        slug=slug,
        dry_run=argument.dry_run,
        keep=[procedure.procedure_id for procedure in written],
    )

    return ProceduresPhase(
        written=tuple(written),
        rejected=tuple(rejected),
        withdrawn=tuple(withdrawn),
        files=tuple(files),
        deleted=tuple(deleted),
    )


__all__ = [
    "ANSWERABLE_TIERS",
    "PROCEDURE_CONSUMPTION_KEY",
    "PROCEDURE_SUFFIX",
    "Candidate",
    "HabitHitLine",
    "WindowHit",
    "candidates",
    "compile_habits",
    "compile_one",
    "compiled_result",
    "failed_run",
    "gate",
    "goal_of",
    "goal_texts",
    "installed_procedures",
    "outcomes_by_ref",
    "procedure_consumption_map",
    "procedure_id_for",
    "procedure_path",
    "read_habit_hits",
    "rejected_for",
    "run_state_dir",
    "seat_outputs",
    "tier_of",
    "tier_of_ref",
    "withdraw",
    "write_procedure",
]
