"""The operator surface: `run` · `resume` · `status` · `dry` · `intake` · `sleep`. Parsing only.

`the build specification (not in this mirror)` § Deliverable 3 → *The operator surface*, decision 21. A
foreground CLI, per-task, no daemon: the console skill the digest names as the human face is
build 2, and it becomes a **caller** of this surface rather than a second writer — which is
what makes § Deliverable 5's writable-set boundary enforceable at all.

**This module parses arguments and dispatches; it holds no runtime logic.** `run`, `resume`
and `status` resolve a brain root, take the lock and hand off to `protean.runtime.engine`;
`dry` materializes a throwaway root and workspace, runs one scripted scenario on them, and
destroys both — it takes no lock, because the root it operates on is one it just created;
`intake`, build 2's fifth verb, seeds `brain/semantic/` offline and is refused while a task
occupies the root, because the runtime may never write a seed file (§ Deliverable 3, decision
14, folded: A1-13);
`sleep`, build 3's sixth verb, grades one run offline and re-values what it learned, and is
refused twice — while a task is in flight, and while a committed not-`done` task's checkpoint
holds a seed it would write (§ Deliverable 2, decision 16, folded: A1-10, folded: S-11).
`protean --help` and `protean <verb> --help` exit 0 without touching a brain root, which is
half of what M1 closes on.

**No exit code is written as an integer here.** `protean.config` owns the table — the five
terminal states and the named refusals — so the operator surface, the tests and the runtime
cannot drift on what `interrupted` means to a shell.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from protean import config
from protean.intake.policy_home import BadProjectSlug, check_slug
from protean.runtime import engine, lock, seat
from protean.runtime.errors import (
    LayerUnavailable,
    NoTask,
    RootOccupied,
    SeatLayerUnavailable,
)
from protean.runtime.interrupts import resolve_mailbox
from protean.runtime.paths import ROOT_PROJECT_SLUG, BrainPaths
from protean.state.errors import CallsDrift, ReadsDrift, RefusalError


def build_parser() -> argparse.ArgumentParser:
    """The six verbs, and nothing that runs. `VERBS` is `config`'s literal, not a list here."""
    parser = argparse.ArgumentParser(
        prog="protean",
        description=(
            "PROTEAN — one fixed tick cycle over six node folders. Six verbs: run, "
            "resume, status and dry drive a task; intake seeds the semantic store offline, "
            "between tasks; sleep grades a finished run and re-values what it learned."
        ),
    )
    parser.add_argument("--version", action="version", version="protean 0.1.0")
    parser.add_argument(
        "--brain",
        metavar="PATH",
        default=None,
        help=(
            "the brain root to operate on; defaults to $PROTEAN_BRAIN, else <repo>/brain "
            "(`protean dry` always overrides it with a throwaway copy)"
        ),
    )
    verbs = parser.add_subparsers(dest="verb", metavar="VERB", required=True)

    run = verbs.add_parser(
        "run",
        help="start a task in this brain root",
        description=(
            "Take the lock, refuse a root already holding a task whose committed terminal is "
            "anything but done, and run the cycle until a terminal state commits."
        ),
    )
    run.add_argument("goal", help="the goal text the task opens with")
    run.add_argument(
        "--project",
        metavar="SLUG",
        default=ROOT_PROJECT_SLUG,
        type=check_slug,
        help=(
            "the project this task runs under; carried in the task's state and the folder "
            "sleep writes its learning to (default: the projectless root)"
        ),
    )
    run.add_argument(
        "--workspace",
        metavar="PATH",
        default=None,
        help=(
            "the task workspace a tier-three spawn is granted; checkpointed with the task, so "
            "`resume` needs no flag. Omitting it is legal and refuses at the spawn desk, not "
            "here: a wave never runs in a throwaway directory nobody asked for"
        ),
    )
    run.set_defaults(handler=_run)

    resume = verbs.add_parser(
        "resume",
        help="resume the task in this brain root",
        description=(
            "Lock first, then mailbox reconciliation, then the answer check, then the refusal "
            "ladder, then replay-or-advance. The three flags are operator acts on exactly "
            "that state and are exempt from the answer check, never from the lock."
        ),
    )
    resume.add_argument(
        "--extend",
        metavar="TICKS|MINUTES",
        default=None,
        help="write ceiling_overrides so a stopped task can pass its ceiling",
    )
    resume.add_argument(
        "--abandon",
        action="store_true",
        help="resolve every open item as abandoned, close every open goal, free the root",
    )
    resume.add_argument(
        "--reseed",
        action="store_true",
        help="the one legal way to change NODE.md or weights.yaml under a suspended task",
    )
    resume.set_defaults(handler=_resume)

    status = verbs.add_parser(
        "status",
        help="report the root's task, tick, terminal and open interrupts",
        description="Read-only. Takes no lock and changes no state.",
    )
    status.set_defaults(handler=_status)

    dry = verbs.add_parser(
        "dry",
        help="run a scripted scenario on a throwaway brain root",
        description=(
            "Materialize a throwaway brain root by copying the tracked seed tree, export "
            "$PROTEAN_BRAIN at it, run the scenario, and destroy both it and the fixture's "
            "temp workspace. The repo's own brain/ is never written, by construction."
        ),
    )
    dry.add_argument("scenario", help="the scenario under fixtures/scenarios/")
    dry.set_defaults(handler=_dry)

    intake = verbs.add_parser(
        "intake",
        help="seed the semantic store from the manifest's sources, offline",
        description=(
            "Read every logical source brain/intake/manifest.yaml names, cut each document at "
            "the granularity its row declares, and replace each brain/semantic/<store>.jsonl "
            "wholesale. Refused while a task occupies the root: the runtime may never write a "
            "seed file, so intake and a task are refused apart rather than serialized. Makes "
            "no model call and writes nothing under brain/nodes/."
        ),
    )
    intake.add_argument(
        "--project",
        metavar="SLUG",
        default=None,
        help="the project memory that enters, tagged onto every chunk it produces",
    )
    intake.set_defaults(handler=_intake)

    sleep = verbs.add_parser(
        "sleep",
        help="grade one run offline and re-value what it learned",
        description=(
            "Read one run — an archived brain/archive/workload-run-*/ directory with --from, else "
            "the live node folders plus the root's most recent committed task — join each "
            "outcome to its prediction by ref, keep only the admissible pairs, and write a "
            "SleepReport under reports/sleep/. Refused twice: while a task is in flight, and "
            "while a committed not-done task's checkpoint holds a seed this run would write. "
            "No flag overrides either. Makes no model call. --dry-run derives everything, "
            "writes the report, prints the diff it would apply, and writes nothing under brain/."
        ),
    )
    sleep.add_argument(
        "--from",
        dest="source",
        metavar="DIR",
        default=None,
        help=(
            "an archived run directory to read instead of the live traces; the default source "
            "and the only read-only-safe one (the archive is read, never written)"
        ),
    )
    sleep.add_argument(
        "--dry-run",
        action="store_true",
        help="derive everything and write the report, but write no file under brain/",
    )
    sleep.set_defaults(handler=_sleep)

    return parser


def _root(args: argparse.Namespace) -> Path:
    """`--brain` if given, else `$PROTEAN_BRAIN`, else `<repo>/brain` — `config` owns the rule."""
    return Path(args.brain).expanduser().resolve() if args.brain else config.brain_root()


def _refuse(exc: Exception, refusal: str) -> int:
    """Print a named refusal and return its code. No integer is written here.

    `EXIT_CODES` rather than `REFUSAL_EXIT_CODES` because build 2's named refusals sit beside
    build 1's rather than inside them, and the merged table is what every caller reads.
    """
    print(str(exc), file=sys.stderr)
    return config.EXIT_CODES[refusal]


def _report(outcome: engine.RunOutcome) -> int:
    """Print whatever the driver has to say, then exit on the **committed** terminal."""
    for message in outcome.messages:
        print(message)
    if outcome.terminal is not None:
        print(f"terminal: {outcome.terminal} after {len(outcome.ticks)} tick(s)")
    return outcome.exit_code


def _run(args: argparse.Namespace) -> int:
    """Take the lock, refuse an occupied root, run the cycle, exit on the committed terminal."""
    root = _root(args)
    # The seat layer resolves its own brain root through `config.brain_root()` — `build()` takes
    # no arguments, by that contract — so `--brain` reaches it the one way it can: the variable
    # `config` already reads. Without this a flagged root moves the task and not the ladder's
    # counts, and the two halves of one run read two different trees.
    os.environ[config.BRAIN_ROOT_ENV] = str(root)
    layer = seat.resolve_seat_layer()
    mailbox = resolve_mailbox(root)
    task_id = engine.mint_task_id()
    with lock.held(BrainPaths(root=root).lock, task_id) as acquisition:
        if acquisition.reclaimed:
            print(acquisition.message())
            engine.record_lock_reclamation(root, task_id, acquisition)
        try:
            outcome = engine.start(
                root, args.goal, layer, mailbox=mailbox, task_id=task_id,
                project=args.project,
                # `--workspace`, reaching the engine **exactly as `dry` and
                # `tests/wet/probe_refusal.py` already hand one** (A.1.i § Deliverable 4): one
                # argument, no second channel. `None` becomes the empty default the engine takes,
                # so omitting the flag is legal here and refuses at the spawn desk.
                workspace_path=args.workspace or "",
            )
        except RootOccupied as exc:
            return _refuse(exc, "root_occupied")
        except (ReadsDrift, CallsDrift) as exc:
            return _refuse(exc, "seed_drift")
    return _report(outcome)


def _resume(args: argparse.Namespace) -> int:
    """Lock, mailbox reconciliation, the answer check, the refusal ladder, replay-or-advance."""
    root = _root(args)
    brain = BrainPaths(root=root)
    administrative = args.abandon or args.reseed or args.extend is not None
    try:
        task_id = engine.current_task(brain)
    except NoTask as exc:
        print(str(exc), file=sys.stderr)
        return config.REFUSAL_EXIT_CODES["root_occupied"]

    os.environ[config.BRAIN_ROOT_ENV] = str(root)  # both halves read the flagged root
    layer = None if administrative else seat.resolve_seat_layer()
    mailbox = resolve_mailbox(root)
    with lock.held(brain.lock, task_id) as acquisition:
        if acquisition.reclaimed:
            print(acquisition.message())
            engine.record_lock_reclamation(root, task_id, acquisition)
        try:
            outcome = engine.resume(
                root,
                layer,
                mailbox=mailbox,
                extend=args.extend,
                abandon=args.abandon,
                reseed=args.reseed,
            )
        except RefusalError as exc:
            return _refuse(
                exc,
                "seed_drift" if isinstance(exc, (ReadsDrift, CallsDrift)) else "contract_refused",
            )
    if outcome.refusal is not None:
        for message in outcome.messages:
            print(message, file=sys.stderr)
        return outcome.exit_code
    if administrative:
        for message in outcome.messages:
            print(message)
        return config.EXIT_DONE if outcome.terminal is None else outcome.exit_code
    return _report(outcome)


def _status(args: argparse.Namespace) -> int:
    """A read-only report of the root's task, tick, terminal and open interrupts."""
    print(engine.status(_root(args)).render())
    return config.EXIT_DONE


def _intake(args: argparse.Namespace) -> int:
    """Seed `brain/semantic/` from the manifest, printing every file it writes.

    Offline and between tasks (decision 14): no lock is taken, because the one thing intake must
    not race is a *task*, and an occupied root is refused by name before anything is read. A
    bad `--project` slug is refused the same way rather than interpolated into a glob.
    """
    from protean.intake import run_intake  # imported here: no other verb needs the package

    root = _root(args)
    try:
        outcome = run_intake(BrainPaths(root=root), project=args.project)
    except RootOccupied as exc:
        return _refuse(exc, "intake_refused")
    except BadProjectSlug as exc:
        return _refuse(exc, "intake_refused")
    for message in outcome.messages():
        print(message)
    return config.EXIT_DONE


def _sleep(args: argparse.Namespace) -> int:
    """Grade one run offline, printing every file it writes.

    Offline and between tasks (decision 16): no lock is taken, for intake's reason — the one
    thing sleep must not race is a *task*, and a task in flight is refused by name before
    anything is read. The second refusal is build 3's own and names the task and the files it
    holds; neither is overridable, which is why this verb ships no `--force`.
    """
    from protean.sleep.run import SeedHashHeld, SeedMoved, run_sleep

    root = _root(args)
    try:
        outcome = run_sleep(
            BrainPaths(root=root),
            source=Path(args.source).expanduser().resolve() if args.source else None,
            dry_run=args.dry_run,
        )
    except RootOccupied as exc:
        return _refuse(exc, "sleep_refused")
    except (SeedHashHeld, SeedMoved) as exc:
        return _refuse(exc, "sleep_seed_refused")
    for message in outcome.messages():
        print(message)
    return config.EXIT_DONE


# --------------------------------------------------------------------------------------
# `dry` — a throwaway brain root, a seeded throwaway workspace, and one scripted run
# --------------------------------------------------------------------------------------

#: The fixture tree, and the directory under it holding one workspace seed per scenario. A
#: scenario names its seed the way it names its seat script: by the directory it is called
#: after, never by a path, so no fixture carries a machine-specific string.
FIXTURES_DIR: str = "fixtures"
WORKSPACE_SEEDS_DIR: str = "workspaces"

#: The one entry of a node folder that is generated rather than seeded
#: (`config.NODE_FOLDER_ENTRIES`). The copy leaves it behind and the throwaway root starts it
#: empty, so a dry run never inherits whatever the repo's own trace files last held.
GENERATED_NODE_ENTRY: str = "trace.jsonl"


def _seed_root(destination: Path) -> Path:
    """Copy the tracked seed tree to a throwaway root and create the directories the runtime owns."""
    shutil.copytree(
        config.repo_root() / "brain" / "nodes",
        destination / "nodes",
        ignore=shutil.ignore_patterns(GENERATED_NODE_ENTRY),
    )
    for node in config.NODE_ORDER:
        entry = config.node_dir(node, destination) / GENERATED_NODE_ENTRY
        entry.write_text("", encoding="utf-8")
    for relative in config.GENERATED_BRAIN_DIRS:
        (destination / relative).mkdir(parents=True, exist_ok=True)
    return destination


def _seed_workspace(scenario: str, destination: Path) -> Path:
    """`fixtures/workspaces/<scenario>/` copied to a throwaway directory, or an empty one."""
    seed = config.repo_root() / FIXTURES_DIR / WORKSPACE_SEEDS_DIR / scenario
    if seed.is_dir():
        shutil.copytree(seed, destination)
    else:
        destination.mkdir(parents=True)
    return destination


def _scenario_names() -> list[str]:
    """Every scenario the fixture tree holds, so a mistyped one is refused with the choices."""
    scenarios = config.repo_root() / FIXTURES_DIR / "scenarios"
    if not scenarios.is_dir():
        return []
    return sorted(path.name for path in scenarios.iterdir() if path.is_dir())


def _print_trace(outcome: engine.RunOutcome) -> None:
    """One line per tick — the tier the router chose, why, and the unit it named."""
    for result in outcome.ticks:
        selection = result.selection
        tier = "-" if selection is None else str(selection.tier)
        why = (
            "-"
            if selection is None or selection.escalation is None
            else str(selection.escalation)
        )
        unit = "-" if selection is None or selection.unit_id is None else selection.unit_id
        skipped = " seat-skipped" if result.seat_skipped else ""
        print(
            f"tick {result.tick}: {tier} ({why}) unit={unit} "
            f"nodes={len(result.order)} journal={result.journal_entries}{skipped}"
        )


def _dry(args: argparse.Namespace) -> int:
    """Run a scripted scenario on a throwaway brain root and workspace, then destroy both.

    Both copies live under **one** temp directory removed in `finally`, so the repo's own
    `brain/` is unwritten and the before/after tree hash unchanged *by construction* rather
    than by assertion (§ Deliverable 7, decision 17). `$PROTEAN_BRAIN` is exported at the copy
    and the root is then resolved back **through** it rather than around it, which is the
    rule § Deliverable 7 states; it is **restored** afterwards, because this verb is also
    called in process by the battery and a dead temp path left in the environment would
    follow it into the next test.

    The seat layer is built through the explicit form rather than the environment: a scenario
    runner already holds the root and the script it resolved, and re-resolving either from a
    variable would give the run two sources for one fact.
    """
    try:
        from protean.cortex.layer import build_layer
        from protean.cortex.scenario import load_scenario
    except ImportError as exc:  # the seam `resolve_seat_layer()` refuses on, same refusal
        raise SeatLayerUnavailable(f"protean.cortex is not importable ({exc})") from exc

    try:
        scenario = load_scenario(args.scenario)
    except FileNotFoundError as exc:
        raise SystemExit(
            f"no scenario named {args.scenario!r}; "
            f"the fixture tree holds {_scenario_names()}"
        ) from exc

    sandbox = Path(tempfile.mkdtemp(prefix=f"protean-dry-{args.scenario}-"))
    inherited = os.environ.get(config.BRAIN_ROOT_ENV)
    try:
        os.environ[config.BRAIN_ROOT_ENV] = str(_seed_root(sandbox / "brain"))
        root = config.brain_root()  # resolved THROUGH the variable, never around it
        workspace = _seed_workspace(args.scenario, sandbox / "workspace")
        print(f"scenario: {scenario.name} — {scenario.goal}")
        print(f"seat script: {scenario.script.name} (scripted; no model is called)")
        print(f"brain root: {root} — a copy of the tracked seed tree, destroyed on exit")
        print(f"workspace: {workspace} — seeded from fixtures, destroyed on exit")
        outcome = engine.start(
            root,
            scenario.goal,
            build_layer(root=root, script=scenario.script),
            mailbox=resolve_mailbox(root),
            workspace_path=str(workspace),
        )
        _print_trace(outcome)
        return _report(outcome)
    finally:
        if inherited is None:
            os.environ.pop(config.BRAIN_ROOT_ENV, None)
        else:
            os.environ[config.BRAIN_ROOT_ENV] = inherited
        shutil.rmtree(sandbox, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse and dispatch. The return value is the process exit code `config` names.

    The one exception `main` converts rather than returns is a layer this checkout does not
    have — the cortex seats or the mailbox's file half. Neither is a refusal `config` has a code
    for, since every one of its five names a different thing, so it exits through `SystemExit`
    with the message and no invented integer.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verb not in config.VERBS:  # pragma: no cover - argparse refuses first
        parser.error(f"unknown verb {args.verb!r}; the surface is {list(config.VERBS)}")
    try:
        return args.handler(args)
    except LayerUnavailable as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
