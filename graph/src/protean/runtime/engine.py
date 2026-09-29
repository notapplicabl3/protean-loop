"""The three drivers behind `run`, `resume` and `status`.

`the build specification (not in this mirror)` § Deliverable 3 — the operator surface, the lock, one task per
brain root, the resume order, the administrative commits — and § Deliverable 5's refusal on an
unanswered item.

**The lock comes first, before any read or write** — every `resume` form, flags included, takes
it or exits naming the holder. Then, reading the mailbox against committed
`BrainState.open_interrupts`: orphan files aside, vanished files re-materialized, and then the
answer check, whose failure is its own exit code with no task state changed. `--abandon`,
`--reseed` and `--extend` are exempt from the **answer check** and never from the lock.

**Everything the runtime persists happens in a boundary commit**, including the three
administrative acts: each rewrites the tick's checkpoint with an incremented `revision`,
recomputes `integrity`, appends its `event` record, and runs no node.

**Nothing here decides an exit code.** A driver returns the committed terminal or raises a named
refusal; `protean.cli` maps both through `protean.config`.

**Build 2 adds one step after the commit, not inside it** (`the build specification (not in this mirror)`
§ Deliverable 6, § Directional decisions 20, folded: S-35): once a terminal has committed,
`close_out()` writes the run's `WorkloadRunReport` and copies the run into `brain/archive/`. It is
deliberately *not* a boundary write — it copies a run that is already committed, on every one of
the five terminals, and it never changes state.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path

from protean import config
from protean.brain.episodes import append_episode, episode_id
from protean.brain.folders import changed_seed_files, read_all_folders, seed_hashes, seed_reader
from protean.brain.trace import append_trace
from protean.runtime import interrupts as mailbox_state
from protean.runtime.archive import ArchiveResult, archive_run
from protean.runtime.commit import build_checkpoint, write_checkpoint
from protean.runtime.cycle import TickContext, TickResult, run_tick
from protean.runtime.errors import NoTask, RootOccupied
from protean.runtime.interrupts import MailboxPort
from protean.runtime.lock import LockAcquisition
from protean.runtime.paths import ROOT_PROJECT_SLUG, BrainPaths, TaskPaths
from protean.runtime.report import build_report, write_report
from protean.runtime.resume import ResumePlan, classify
from protean.runtime.seat import SeatHabits, SeatLayer
from protean.runtime.triggers import check_seeds
from protean.state.brain_state import BrainState
from protean.state.checkpoint import Checkpoint, load_checkpoint
from protean.state.enums import (
    EpisodeKind,
    EventName,
    GoalStatus,
    NodeName,
    TerminalState,
    window_len,
)
from protean.state.errors import InterruptUnanswered
from protean.state.primitives import GoalItem, ProjectExtension
from protean.state.records import EpisodeRecord, TraceRecord

#: The answer text `resume --abandon` records for every open item it retires.
ABANDONED_ANSWER = "abandoned"

#: The `BrainState.extensions` namespace a task's project slug is carried in
#: (`the build specification (not in this mirror)` § Directional decisions 22, folded: S-2) — **the first real
#: user of build 1's extension registry**. Adaptation is data: the slug extends state by
#: registering a namespace, never by adding a core field, and `BrainState` is unchanged.
PROJECT_EXTENSION = "project"
PROJECT_SLUG_FIELD = "slug"

#: The registered version of that namespace. `Checkpoint.extensions` is the manifest a resume
#: checks a registration against; build 3 registers version 1 and ships no migration path, here
#: as everywhere.
PROJECT_EXTENSION_VERSION = 1

#: The `BrainState.extensions` namespace a task's **workspace** is carried in
#: (`the build specification (not in this mirror)` § Deliverable 4, decision 3, folded: S-i50) — the
#: second user of the registry, on `PROJECT_EXTENSION`'s precedent exactly.
#:
#: A spawn's `--add-dir` is the runtime's task workspace or the spawn does not happen, so a live
#: run has to be able to name one: `protean run --workspace <path>` supplies it, `start()` writes
#: it here, and `resume()` reads it back into `build_context` — which is what makes `resume` need
#: **no flag** and a resumed live task refuse only once rather than forever. **`extensions` is the
#: open registry by design, so no schema version moves**: registering a namespace is how state is
#: extended, and `BrainState` is unchanged.
WORKSPACE_EXTENSION = "workspace"
WORKSPACE_PATH_FIELD = "path"

#: The registered version of that namespace, on `PROJECT_EXTENSION_VERSION`'s rule: version 1 and
#: no migration path.
WORKSPACE_EXTENSION_VERSION = 1

#: The dotted path the task-open step resolves the habit matcher from — `SEAT_LAYER_MODULE`'s
#: rule one seam over (`protean.runtime.seat.resolve_seat_layer()`, ledger `D19-2`). Lazy and by
#: dotted path because the matcher is a *cortex* module: no runtime module imports
#: `protean.cortex` at module scope, which is the seam the whole build is built on
#: (`protean.runtime.errors.SeatUnavailable`). A checkout without the package still runs every
#: verb that runs no seat.
HABIT_MATCHER_MODULE = "protean.cortex.habits"


def habit_seam(root: Path, project: str) -> SeatHabits | None:
    """The task's compiled procedures, as the `SeatLayer.habits` seam — or `None`.

    `the build specification (not in this mirror)` § Deliverable 4, folded: S-18: `build()` takes no argument
    and no task exists when the layer is built, so the **runtime** loads the procedure set, once,
    at task open or resume — from the cortex node folder's `procedures/` and the task's own
    project procedures under the slug in `BrainState.extensions` — and holds it for the life of
    the task. A sleep run mid-task is refused (decision 16), so the set cannot change underneath
    a run and re-reading it per tick would buy nothing.

    `None` on a root that has compiled nothing, which is every root before the first sleep run:
    the layer then carries no third seam, `habit_of()` short-circuits, and no `habit_hits.jsonl`
    is ever written.
    """
    module = import_module(HABIT_MATCHER_MODULE)
    return module.open_task(root, project=project)


def mint_task_id(now: datetime | None = None) -> str:
    """A filesystem-safe, sortable task id. One task per brain root, so uniqueness is by time."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S%f")
    return f"task-{stamp}"


@dataclass(slots=True)
class RunOutcome:
    """What a driver did: the committed terminal, the ticks it ran, and what to print."""

    task_id: str
    terminal: TerminalState | None = None
    ticks: list[TickResult] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    refusal: str | None = None

    @property
    def exit_code(self) -> int:
        if self.refusal is not None:
            return config.REFUSAL_EXIT_CODES[self.refusal]
        if self.terminal is None:
            return config.EXIT_DONE
        return config.TERMINAL_EXIT_CODES[str(self.terminal)]


def load_task(paths: TaskPaths, *, verify_seeds: bool = True) -> Checkpoint:
    """The refusal ladder, run in order, first failure raising and quoting both sides."""
    payload = json.loads(paths.checkpoint.read_text(encoding="utf-8"))
    return load_checkpoint(
        payload,
        extension_versions={
            name: extension["version"] for name, extension in
            (payload.get("state", {}).get("extensions") or {}).items()
        },
        seed_reader=seed_reader(paths.root) if verify_seeds else None,
    )


def record_lock_reclamation(
    root: Path, task_id: str, acquisition: LockAcquisition
) -> EpisodeRecord | None:
    """§ Deliverable 3: a reclamation is printed **and** written as an `event`, never silent.

    `protean.runtime.lock` deliberately reports the reclamation as a return value rather than
    writing it: an episode record needs a task and a tick, which that module has no business
    knowing. This is the caller half. `None` means nothing was reclaimed.
    """
    stale = acquisition.reclaimed_from
    if stale is None:
        return None
    paths = BrainPaths(root=root).task(task_id)
    tick = 0
    if paths.checkpoint.exists():
        payload = json.loads(paths.checkpoint.read_text(encoding="utf-8"))
        tick = int((payload.get("state") or {}).get("tick", 0))
    return append_episode(
        paths.episodes,
        EpisodeRecord(
            schema_version=config.EPISODE_SCHEMA_VERSION,
            episode_id=episode_id(task_id, tick),
            task=task_id,
            tick=tick,
            kind=EpisodeKind.EVENT,
            event_name=EventName.LOCK_RECLAIMED,
            detail={
                "from_pid": stale.pid,
                "from_task": stale.task_id,
                "from_started_at": stale.started_at,
                "message": acquisition.message(),
            },
        ),
    )


def occupied_task(brain: BrainPaths) -> tuple[str, TerminalState | None] | None:
    """The task occupying this root, if any: committed `terminal` anything but `done`."""
    for task_id in brain.task_ids():
        payload = json.loads(brain.task(task_id).checkpoint.read_text(encoding="utf-8"))
        terminal = (payload.get("state") or {}).get("terminal")
        if terminal != str(TerminalState.DONE):
            return task_id, None if terminal is None else TerminalState(terminal)
    return None


def build_context(
    root: Path,
    task_id: str,
    layer: SeatLayer,
    *,
    mailbox: MailboxPort | None = None,
    workspace_path: str = "",
    revision: int = 0,
    project: str = ROOT_PROJECT_SLUG,
) -> TickContext:
    """Read every node folder, refusing a `## Reads` or `## Calls` drift, and hash the seeds.

    **The second refusal is the call policy's** (`the build specification (not in this mirror)`
    § Deliverable 1): the folders are read once and handed to `triggers.check_seeds()` before
    `TickContext` holds them, so an authored node whose trigger key is on with no `## Calls` line,
    or whose key is neither off nor a positive number, is refused before any tick — and both
    refusals reach the operator as `config.EXIT_SEED_DRIFT`.

    **This is task open**, so it is also where build 3's procedure set is loaded and attached to
    the layer as its third seam (§ Deliverable 4, folded: S-18). The layer is *replaced* rather
    than mutated — it is frozen, and `build()` may not know a task — so the port, the router and
    both build-2 seams are carried through untouched and a root with no compiled habit gets the
    layer it was handed, unchanged.
    """
    folders = read_all_folders(root)
    check_seeds(folders)
    habits = habit_seam(root, project)
    return TickContext(
        paths=BrainPaths(root=root).task(task_id),
        root=root,
        folders=folders,
        layer=layer if habits is None else replace(layer, habits=habits),
        seed_hashes=seed_hashes(root),
        workspace_path=workspace_path,
        mailbox=mailbox,
        revision=revision,
    )


def project_extension(slug: str) -> ProjectExtension:
    """The `project` namespace one task registers, carrying its slug (decision 22).

    A namespaced sub-model with its own version, exactly as `ProjectExtension` is documented —
    the payload carries the slug, because the model forbids an extra field and `BrainState` is
    inherited unchanged (§ Directional decisions 1).
    """
    return ProjectExtension(
        name=PROJECT_EXTENSION,
        version=PROJECT_EXTENSION_VERSION,
        payload={PROJECT_SLUG_FIELD: slug},
    )


def workspace_extension(path: str) -> ProjectExtension:
    """The `workspace` namespace a task registers, carrying the path `--workspace` named.

    `project_extension()`'s shape one namespace over: a namespaced sub-model with its own version,
    the payload carrying the value, and `BrainState` unchanged (folded: S-i50).
    """
    return ProjectExtension(
        name=WORKSPACE_EXTENSION,
        version=WORKSPACE_EXTENSION_VERSION,
        payload={WORKSPACE_PATH_FIELD: path},
    )


def task_workspace(state: BrainState) -> str:
    """The workspace this task was opened against, `""` when it registered no namespace.

    The one reader inside the runtime: a `resume` that was handed no workspace reads it back from
    here, so the tick that refused for want of one can proceed without the operator re-naming it
    (`the build specification (not in this mirror)` § Deliverable 4, row G5 (d)). An explicitly handed
    workspace still wins — `dry` and the wet probe hand one on purpose — so this is the fallback
    and never an override.
    """
    extension = state.extensions.get(WORKSPACE_EXTENSION)
    if extension is None:
        return ""
    path = extension.payload.get(WORKSPACE_PATH_FIELD)
    return path if isinstance(path, str) else ""


def project_slug(state: BrainState) -> str:
    """The task's own project slug, `_root` when it registered no namespace (decision 22).

    The one reader inside the runtime: order W6's seat step loads the procedures compiled under
    this slug at task open, so a second spelling of "which project is this task" would be a
    second thing to drift.
    """
    extension = state.extensions.get(PROJECT_EXTENSION)
    if extension is None:
        return ROOT_PROJECT_SLUG
    slug = extension.payload.get(PROJECT_SLUG_FIELD)
    return slug if isinstance(slug, str) and slug else ROOT_PROJECT_SLUG


def new_state(
    task_id: str,
    goal_text: str,
    context: TickContext,
    *,
    project: str = ROOT_PROJECT_SLUG,
) -> BrainState:
    """A task's opening state. `window_len` is set once, from the detectors' own thresholds.

    **Every task carries a project slug** (decision 22), `_root` when `run` named none: sleep
    writes that project's memory on every run, so a projectless root still accumulates the
    evidence the two-task floor reads back.

    **A task that was handed a workspace carries that too** (A.1.i § Deliverable 4, decision 3,
    folded: S-i50), under its own registered namespace and on the same precedent, so a `resume`
    re-reads the path with no flag. A task handed none registers nothing: the absence is what the
    spawn desk refuses on, and registering an empty string would make "no workspace" a value.
    """
    weights = context.weights(NodeName.ANTERIOR_CINGULATE)
    extensions = {PROJECT_EXTENSION: project_extension(project)}
    if context.workspace_path:
        extensions[WORKSPACE_EXTENSION] = workspace_extension(context.workspace_path)
    return BrainState(
        task_id=task_id,
        tick=0,
        goals=[
            GoalItem(
                id=f"{task_id}-g1",
                text=goal_text,
                status=GoalStatus.OPEN,
                opened_at_tick=0,
                last_progress_tick=0,
            )
        ],
        window_len=window_len(weights),
        extensions=extensions,
    )


def _drive(
    context: TickContext,
    state: BrainState,
    outcome: RunOutcome,
    *,
    max_ticks: int,
    plan: ResumePlan | None = None,
    extra_outcomes: Sequence[TraceRecord] = (),
    extra_episodes: Sequence[EpisodeRecord] = (),
    resolved_ids: Sequence[str] = (),
) -> RunOutcome:
    """Run ticks until a terminal commits. The terminal is committed, then the driver returns."""
    replay = plan is not None and plan.replays
    if plan is not None:
        state.tick = plan.tick - 1
    ran = 0
    while ran < max_ticks:
        state.tick += 1
        result = run_tick(
            context,
            state,
            replay=replay and ran == 0,
            extra_outcomes=extra_outcomes if ran == 0 else (),
            extra_episodes=extra_episodes if ran == 0 else (),
            resolved_ids=resolved_ids if ran == 0 else (),
        )
        outcome.ticks.append(result)
        ran += 1
        if result.committed_terminal is not None:
            outcome.terminal = result.committed_terminal
            close_out(context, outcome)
            return outcome
    return outcome


def close_out(
    context: TickContext,
    outcome: RunOutcome,
    *,
    base_ref: str | None = None,
    oracle_report: Path | None = None,
    hashes: Mapping[str, str] | None = None,
) -> ArchiveResult:
    """The terminal step: write the run's receipt, then archive the run before it can be lost.

    `the build specification (not in this mirror)` § Deliverable 6 and § Directional decisions 20 (folded:
    A1-17, folded: S-35). It runs on **every** terminal — `done`, `stopped`, `stuck`, `blocked`
    and `interrupted` — because a partial run is the one whose product is most likely to be
    lost: the branch lives in a throwaway clone and nothing else preserves it.

    It hangs here rather than in `protean.runtime.terminal`, which decides *which* condition
    fired and writes nothing, and rather than in `protean.runtime.cycle`, which owns the
    boundary commit: the archive is a copy of a committed run, so it must happen strictly after
    the commit that made the run committed.

    `oracle_report` and `hashes` are the run driver's to pass (order W8): an `OracleReport` is
    graded outside the brain root, and S-41's four before/after tree hashes are taken around the
    *run* rather than around the copy, so nothing here can observe them.
    """
    report = build_report(
        context.root,
        outcome.task_id,
        terminal=outcome.terminal,
        workspace_path=context.workspace_path,
        base_ref=base_ref,
    )
    write_report(context.paths, report)
    archived = archive_run(
        context.root,
        outcome.task_id,
        terminal=outcome.terminal,
        workspace_path=context.workspace_path,
        base_ref=base_ref,
        oracle_report=oracle_report,
        hashes=hashes,
    )
    outcome.messages.append(f"archived {archived.directory}")
    return archived


def start(
    root: Path,
    goal_text: str,
    layer: SeatLayer,
    *,
    mailbox: MailboxPort | None = None,
    workspace_path: str = "",
    task_id: str | None = None,
    project: str = ROOT_PROJECT_SLUG,
    max_ticks: int = 1000,
) -> RunOutcome:
    """`protean run <goal>`: refuse an occupied root, open a task, run to a terminal.

    `project` is `--project`'s slug, default `_root` (decision 22). It is written once, at task
    open, into `BrainState.extensions` — and restored on resume for free, because the checkpoint
    carries the whole state through `load_checkpoint()`'s own refusal ladder.

    `workspace_path` is `--workspace`'s value from A.1.i, and it travels the same way: written
    once at task open under the `workspace` namespace, read back by `resume()` below. Omitting it
    stays legal and lands at the **spawn desk** rather than at the parser (row G5 (d)).
    """
    brain = BrainPaths(root=root)
    occupied = occupied_task(brain)
    if occupied is not None:
        raise RootOccupied(task_id=occupied[0], terminal=None if occupied[1] is None else str(occupied[1]))

    identifier = task_id or mint_task_id()
    context = build_context(
        root,
        identifier,
        layer,
        mailbox=mailbox,
        workspace_path=workspace_path,
        project=project,
    )
    state = new_state(identifier, goal_text, context, project=project)
    outcome = RunOutcome(task_id=identifier)
    append_episode(
        context.paths.episodes,
        EpisodeRecord(
            schema_version=config.EPISODE_SCHEMA_VERSION,
            episode_id=episode_id(identifier, 0),
            task=identifier,
            tick=0,
            kind=EpisodeKind.EVENT,
            event_name=EventName.TASK_START,
            detail={"goal": goal_text},
        ),
    )
    return _drive(context, state, outcome, max_ticks=max_ticks)


def current_task(brain: BrainPaths) -> str:
    """The one task under this root. `resume` and `status` operate on it."""
    task_ids = brain.task_ids()
    if not task_ids:
        raise NoTask(str(brain.root))
    occupied = occupied_task(brain)
    return occupied[0] if occupied is not None else task_ids[-1]


def resume(
    root: Path,
    layer: SeatLayer | None,
    *,
    mailbox: MailboxPort | None = None,
    workspace_path: str = "",
    extend: str | None = None,
    abandon: bool = False,
    reseed: bool = False,
    max_ticks: int = 1000,
) -> RunOutcome:
    """`protean resume`: reconcile, check the answer, run the ladder, then replay or advance."""
    brain = BrainPaths(root=root)
    task_id = current_task(brain)
    paths = brain.task(task_id)
    outcome = RunOutcome(task_id=task_id)

    checkpoint = load_task(paths, verify_seeds=not reseed)
    state = checkpoint.state
    revision = checkpoint.revision

    if mailbox is not None:
        orphaned, rematerialized = mailbox_state.reconcile(state, mailbox)
        outcome.messages.extend(f"orphaned {item}" for item in orphaned)
        outcome.messages.extend(f"re-materialized {item}" for item in rematerialized)

    administrative = abandon or reseed or extend is not None
    answers: dict[str, str] = {}
    if not administrative and mailbox is not None:
        pending = mailbox_state.unanswered(state, mailbox)
        if pending:
            outcome.refusal = "unanswered_interrupt"
            outcome.messages.append(
                str(InterruptUnanswered(pending[0].path))
            )
            return outcome
        answers = mailbox_state.answers(state, mailbox)

    if abandon:
        return _abandon(paths, state, revision, root, outcome, mailbox)
    if reseed:
        return _reseed(paths, state, revision, root, outcome)
    if extend is not None:
        return _extend(paths, state, revision, root, outcome, extend)

    if layer is None:  # pragma: no cover - the operator surface resolves one first
        raise ValueError("a resume that runs a tick needs a seat layer")

    context = build_context(
        root,
        task_id,
        layer,
        mailbox=mailbox,
        # **The workspace the task was opened against, re-read off the checkpoint** (A.1.i
        # § Deliverable 4, row G5 (d), folded: S-i50): `resume` needs no flag, so a live task that
        # stopped for want of one does not refuse forever once `run --workspace` gave it one. A
        # value handed in still wins — `dry` and the wet probe hand one on purpose.
        workspace_path=workspace_path or task_workspace(state),
        revision=revision,
        # The slug the task was opened under, restored from the checkpoint with the rest of
        # state — so a resume consults the same project's procedures the run opened with, and
        # "loaded once at task open **or resume**" is one code path (§ Deliverable 4).
        project=project_slug(state),
    )
    # Before the first tick of the resumed run: a new process's layer mints nothing for a task
    # whose handles the checkpoint already carries (§ Deliverable 6).
    if state.seat_sessions and layer.sessions is not None:
        layer.sessions.restore(task_id, state.seat_sessions)
    plan = classify(paths, checkpoint)

    extra_outcomes: list[TraceRecord] = []
    extra_episodes: list[EpisodeRecord] = []
    resolved_ids: list[str] = []
    for entry in list(state.open_interrupts):
        answer = answers.get(entry.id)
        if answer is None:
            continue
        extra_outcomes.append(
            mailbox_state.answer_outcome(
                entry, answer, task=task_id, resume_tick=plan.tick
            )
        )
        extra_episodes.append(
            EpisodeRecord(
                schema_version=config.EPISODE_SCHEMA_VERSION,
                episode_id=episode_id(task_id, plan.tick),
                task=task_id,
                tick=plan.tick,
                kind=EpisodeKind.EVENT,
                event_name=EventName.INTERRUPT_RESOLVED,
                detail={"id": entry.id, "question": entry.question, "answer": answer},
            )
        )
        resolved_ids.append(entry.id)
        mailbox_state.resolve(state, entry, answer, plan.tick)
        _reset_ladder(state, entry, plan.tick)

    state.terminal = None
    return _drive(
        context,
        state,
        outcome,
        max_ticks=max_ticks,
        plan=plan,
        extra_outcomes=extra_outcomes,
        extra_episodes=extra_episodes,
        resolved_ids=resolved_ids,
    )


def _reset_ladder(state: BrainState, entry, resume_tick: int) -> None:
    """Resolving a `stuck` item resets the exhausted goal's counters and its units' windows.

    Exactly as `--extend` resets a ceiling: without it the resumed run re-exhausts the ladder at
    its first boundary (folded: T-10).
    """
    if str(entry.kind) != "stuck":
        return
    for goal in state.goals:
        if goal.status is not GoalStatus.OPEN:
            continue
        goal.replan_count = 0
        goal.redirect_count = 0
        goal.last_progress_tick = resume_tick
        for unit in state.units:
            if unit.goal_id == goal.id and unit.id in state.unit_windows:
                state.unit_windows = {
                    key: ([] if key == unit.id else value)
                    for key, value in state.unit_windows.items()
                }


def _administrative_commit(
    paths: TaskPaths,
    state: BrainState,
    revision: int,
    root: Path,
    name: EventName,
    detail: dict,
) -> Checkpoint:
    """One rewrite of the tick's checkpoint, `revision` incremented, with its `event` record."""
    append_episode(
        paths.episodes,
        EpisodeRecord(
            schema_version=config.EPISODE_SCHEMA_VERSION,
            episode_id=episode_id(state.task_id, state.tick),
            task=state.task_id,
            tick=state.tick,
            kind=EpisodeKind.EVENT,
            event_name=name,
            detail=detail,
        ),
    )
    checkpoint = build_checkpoint(
        state, seed_hashes=seed_hashes(root), revision=revision + 1
    )
    write_checkpoint(paths, checkpoint)
    return checkpoint


def _abandon(
    paths: TaskPaths, state: BrainState, revision: int, root: Path,
    outcome: RunOutcome, mailbox: MailboxPort | None,
) -> RunOutcome:
    """Retire the task: every open item abandoned, every open goal closed, the root freed."""
    for entry in list(state.open_interrupts):
        record = mailbox_state.answer_outcome(
            entry, ABANDONED_ANSWER, task=state.task_id, resume_tick=state.tick
        )
        try:
            append_trace(paths.trace(str(record.node)), record)
        except Exception as exc:  # the raise-tick prediction may predate this checkout
            outcome.messages.append(f"{entry.id}: {exc}")
        mailbox_state.resolve(state, entry, ABANDONED_ANSWER, state.tick)
        if mailbox is not None:
            mailbox.delete(entry.id)
    for goal in state.goals:
        if goal.status is GoalStatus.OPEN:
            goal.status = GoalStatus.ABANDONED
    state.terminal = TerminalState.DONE
    _administrative_commit(
        paths, state, revision, root, EventName.ABANDONED, {"task": state.task_id}
    )
    outcome.terminal = TerminalState.DONE
    outcome.messages.append(f"task {state.task_id} abandoned; the brain root is free")
    return outcome


def _reseed(
    paths: TaskPaths, state: BrainState, revision: int, root: Path, outcome: RunOutcome
) -> RunOutcome:
    """The one legal way to change `NODE.md` or `weights.yaml` under a suspended task."""
    payload = json.loads(paths.checkpoint.read_text(encoding="utf-8"))
    changed = changed_seed_files(root, payload.get("seed_hashes") or {})
    for path, (was, now) in sorted(changed.items()):
        outcome.messages.append(f"reseeded {path}: {was} -> {now}")
    if not changed:
        outcome.messages.append("no seed file changed; the checkpoint is re-hashed anyway")
    _administrative_commit(
        paths, state, revision, root, EventName.RESEEDED,
        {"changed": sorted(changed)},
    )
    outcome.terminal = state.terminal
    return outcome


def _extend(
    paths: TaskPaths, state: BrainState, revision: int, root: Path,
    outcome: RunOutcome, extend: str,
) -> RunOutcome:
    """`--extend <ticks|minutes>` writes `ceiling_overrides` — the only thing that moves a ceiling."""
    text = extend.strip().lower()
    if text.endswith("m"):
        state.ceiling_overrides.extra_seconds += float(text[:-1]) * 60.0
    else:
        state.ceiling_overrides.extra_ticks += int(text)
    state.ceiling_overrides.set_at_tick = state.tick
    state.terminal = None
    _administrative_commit(
        paths, state, revision, root, EventName.TERMINAL,
        {"extend": extend, "extra_ticks": state.ceiling_overrides.extra_ticks,
         "extra_seconds": state.ceiling_overrides.extra_seconds},
    )
    outcome.messages.append(f"ceiling extended by {extend}; resume again to continue the task")
    return outcome


@dataclass(frozen=True, slots=True)
class StatusReport:
    """`protean status`: read-only, takes no lock, changes no state."""

    root: Path
    task_id: str | None
    tick: int
    terminal: TerminalState | None
    open_interrupts: tuple[str, ...]
    open_goals: tuple[str, ...]
    revision: int

    def render(self) -> str:
        if self.task_id is None:
            return f"{self.root}: no task"
        lines = [
            f"root      {self.root}",
            f"task      {self.task_id}",
            f"tick      {self.tick} (revision {self.revision})",
            f"terminal  {self.terminal if self.terminal is not None else '-'}",
            f"goals     {', '.join(self.open_goals) if self.open_goals else '-'}",
            f"open      {', '.join(self.open_interrupts) if self.open_interrupts else '-'}",
        ]
        return "\n".join(lines)


def status(root: Path) -> StatusReport:
    """Report the root's task, tick, terminal and open interrupts. Nothing is written."""
    brain = BrainPaths(root=root)
    task_ids = brain.task_ids()
    if not task_ids:
        return StatusReport(
            root=root, task_id=None, tick=0, terminal=None,
            open_interrupts=(), open_goals=(), revision=0,
        )
    task_id = current_task(brain)
    payload = json.loads(brain.task(task_id).checkpoint.read_text(encoding="utf-8"))
    state = payload.get("state") or {}
    terminal = state.get("terminal")
    return StatusReport(
        root=root,
        task_id=task_id,
        tick=int(state.get("tick", 0)),
        terminal=None if terminal is None else TerminalState(terminal),
        open_interrupts=tuple(item["id"] for item in state.get("open_interrupts") or []),
        open_goals=tuple(
            item["id"] for item in state.get("goals") or [] if item.get("status") == "open"
        ),
        revision=int(payload.get("revision", 0)),
    )
