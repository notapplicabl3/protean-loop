"""The sixth verb's body: refuse twice, verify the seeds, join the evidence, write the report.

`the build specification (not in this mirror)` § Deliverable 2 (whole), § Directional decisions 10, 16, 17,
18 and 22, § Build process leg 2, § Resolutions A1-3, A1-10, A1-11, S-6, S-11, S-12, S-13.

**Copying the intake verb whole and diverging only where build 3 requires** (§ Deliverable 2).
The shape is `protean.intake.run`'s: refuse before anything is read, do the reading in one pass,
return an outcome object whose `messages()` prints one line per file written and nothing it did
not write. Three things diverge — sleep refuses **twice**, it verifies the seeds a run ran under
before it grades them, and it accumulates rather than replacing.

**It refuses twice, and `--force` overrides neither** (decision 16, folded: A1-10). There is no
`--force` on this verb at all, which is the strongest form of that sentence.

1. **A task in flight** — the instance lock held, or a task whose committed `terminal` is
   `None`. Build 1's own `RootOccupied`, raised before any source is read. Deliberately
   **narrower** than `engine.occupied_task()`, which refuses any non-`done` task: the
   committed-but-not-`done` case is refusal 2's to own and to name (folded: S-11).
2. **A committed, not-`done` task whose checkpoint records a seed hash for a file this run
   would write.** Stricter than intake needs to be, because intake writes files no checkpoint
   hashes and sleep writes files **every** checkpoint hashes — so a paused task always trips
   it, by design. The refusal names the task and the files; the doors out are finishing the
   task or `resume --abandon`.

**It verifies before it grades** (decision 17, folded: A1-11). The archive preserves seed
*hashes* and never seed *values*, so before deriving one update sleep re-hashes every
`weights.yaml` the run's `checkpoint.json` recorded and refuses the run **as evidence** if one
has moved, naming the file. The verified set lands in the report's `source` group, which is what
makes the gap self-closing: the first sleep run's report is the durable record of run 1's
thresholds.

**Three producer seams, filled by three later orders.** `weights.py` (order W3), `memory.py`
(order W5) and `habits.py` (order W6) are not this module's to write. Each is resolved by dotted
path at call time, exactly as `protean.runtime.seat.resolve_seat_layer()` resolves the cortex
package, and an absent module takes the empty branch — so the pipeline runs whole today and a
producer lands its phase by creating its module.

**Zero model calls, by construction** (decision 10, decision 4). This package sits inside the
static grep's walked set and names no binary; the exclusion list stays at exactly two packages.

**Its write set is exactly four places and it prints every file it writes** (§ Deliverable 2).
Nothing under `brain/state/`, `brain/episodes/`, `brain/mailbox/`, `brain/semantic/` or
`brain/archive/` is written, and nothing outside the brain root but the report.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Final

from protean import config
from protean.brain.folders import SEED_ABSENT, file_sha256
from protean.runtime import lock
from protean.runtime.errors import RootOccupied
from protean.runtime.paths import BrainPaths, sleep_report_dir
from protean.sleep.evidence import (
    AdmissibleSet,
    RunRecords,
    admissible_set,
    load_archived_run,
    load_live_run,
)
from protean.sleep.report import (
    Phases,
    ProceduresPhase,
    ProjectMemoryPhase,
    WeightsPhase,
    build_report,
    diff_lines,
    write_report,
)
from protean.state.errors import ProteanError
from protean.state.sleep import SleepReport

#: `sleep-YYYYMMDD-HHMMSSZ`, minted from the UTC clock at the run's open — `mint_run_id()`'s
#: shape, one verb over.
SLEEP_ID_PREFIX: Final[str] = "sleep-"
SLEEP_ID_STAMP: Final[str] = "%Y%m%d-%H%M%SZ"

#: The three producer seams: the module a later order writes, and the entry point it exposes.
#: Resolved by dotted path so this order's pipeline runs before any of them exists.
WEIGHTS_MODULE: Final[str] = "protean.sleep.weights"
WEIGHTS_ENTRY: Final[str] = "derive_updates"
MEMORY_MODULE: Final[str] = "protean.sleep.memory"
MEMORY_ENTRY: Final[str] = "write_project_memory"
HABITS_MODULE: Final[str] = "protean.sleep.habits"
HABITS_ENTRY: Final[str] = "compile_habits"

#: The note a run records when a producer module is not installed in this checkout. It is a
#: *note*, never a refusal: the verb's own half — the refusals, the verification, the evidence
#: join and the report — is complete without them.
PHASE_ABSENT_NOTE: Final[str] = "no {module} in this checkout: the {name} group is empty"


class SeedHashHeld(ProteanError):
    """Refusal 2: a committed, not-`done` task's checkpoint holds a file this run would write.

    Names the task and the files, because both are what an operator acts on: the doors out are
    finishing the task or `resume --abandon`, and neither is reachable without the task id.
    """

    def __init__(self, task_id: str, terminal: str, files: tuple[str, ...]) -> None:
        self.task_id = task_id
        self.terminal = terminal
        self.files = files
        listed = ", ".join(files)
        super().__init__(
            f"task {task_id!r} (terminal={terminal!r}) is committed but not done, and its "
            f"checkpoint records a seed hash for {len(files)} file(s) this run would write: "
            f"{listed} — finish the task, or free the root with `resume --abandon`. "
            f"No flag overrides this."
        )


class SeedMoved(ProteanError):
    """The verification refusal: a recorded `weights.yaml` hash has moved since the run.

    Refuses the run **as evidence** (decision 17), before one update is derived. Naming the file
    is the whole point: the archive kept the hash and never the value, so the file is the only
    thing that can be looked at.
    """

    def __init__(self, source: str, moved: Mapping[str, tuple[str, str]]) -> None:
        self.source = source
        self.moved = dict(moved)
        listed = ", ".join(
            f"{path} (recorded {was[:12]}, now {now[:12]})"
            for path, (was, now) in sorted(moved.items())
        )
        super().__init__(
            f"the run at {source} was taken under seed values that have since moved: {listed} — "
            f"refused as evidence, because an update derived from it would be taken under a "
            f"threshold nobody can now read"
        )


def mint_sleep_id(now: datetime | None = None) -> str:
    """`sleep-YYYYMMDD-HHMMSSZ`, minted at the run's open."""
    return f"{SLEEP_ID_PREFIX}{(now or datetime.now(UTC)).strftime(SLEEP_ID_STAMP)}"


# --------------------------------------------------------------------------------------
# The two refusals
# --------------------------------------------------------------------------------------


def _committed_terminals(brain: BrainPaths) -> dict[str, str | None]:
    """Every checkpointed task's committed `terminal`, by task id.

    Read raw rather than through `load_checkpoint()`: this runs *before* anything is read as
    evidence, and the refusal ladder's own arms are not the question here. `engine.occupied_task`
    reads the same field; this returns all of them rather than the first, because refusal 1 and
    refusal 2 select different tasks out of the same set and a first-match helper would let a
    committed `interrupted` task hide a task still in flight.
    """
    terminals: dict[str, str | None] = {}
    for task_id in brain.task_ids():
        payload: Any = json.loads(brain.task(task_id).checkpoint.read_text(encoding="utf-8"))
        state = payload.get("state") or {}
        terminal = state.get("terminal")
        terminals[task_id] = None if terminal is None else str(terminal)
    return terminals


def refuse_a_task_in_flight(brain: BrainPaths) -> None:
    """Refusal 1 — the lock held, or a committed `terminal` of `None`. Raises `RootOccupied`.

    `lock._pid_is_live` is imported rather than re-written: `protean.runtime.lock` is read-only
    to this order, so it cannot gain a public alias, and a second pid probe here would be a
    second definition of "live" for the one fact both refusals turn on.
    """
    holder = lock.read_holder(brain.lock)
    if holder is not None and lock._pid_is_live(holder.pid):
        raise RootOccupied(task_id=holder.task_id, terminal=None)
    for task_id, terminal in _committed_terminals(brain).items():
        if terminal is None:
            raise RootOccupied(task_id=task_id, terminal=None)


def writable_seed_keys(recorded: Mapping[str, str]) -> tuple[str, ...]:
    """The recorded seed keys naming a file this run would write, sorted.

    Every `weights.yaml` of a node in `config.WEIGHTS_WRITABLE_NODES` — the gate's is the empty
    mapping by contract and receives no update, so it is not a file this run would write. The
    other three write targets (`procedures/`, project memory) are named by no `seed_hashes` key.
    """
    wanted = {f"nodes/{node}/weights.yaml" for node in config.WEIGHTS_WRITABLE_NODES}
    return tuple(sorted(key for key in recorded if key in wanted))


def recorded_weights_keys(recorded: Mapping[str, str]) -> tuple[str, ...]:
    """Every `weights.yaml` the checkpoint recorded, sorted — the gate's included.

    The verification's set, wider than refusal 2's: refusal 2 asks which seeds this run would
    WRITE (five), verification asks whether the evidence is still the run's (row L2: "every
    `weights.yaml` the run's `checkpoint.json` recorded is re-hashed"). A moved gate hash means
    the run was taken under a different seed tree, so it refuses as evidence like any other
    (folded: P6-1).
    """
    return tuple(sorted(key for key in recorded if key.endswith("/weights.yaml")))


def refuse_a_held_seed(brain: BrainPaths) -> None:
    """Refusal 2 — a committed, not-`done` task holding a seed this run would write."""
    for task_id, terminal in sorted(_committed_terminals(brain).items()):
        if terminal is None or terminal == str(config.TERMINAL_STATES[0]):
            continue  # in flight is refusal 1's; `done` frees the root
        payload: Any = json.loads(brain.task(task_id).checkpoint.read_text(encoding="utf-8"))
        held = writable_seed_keys(payload.get("seed_hashes") or {})
        if held:
            raise SeedHashHeld(task_id=task_id, terminal=terminal, files=held)


# --------------------------------------------------------------------------------------
# Verify before you grade
# --------------------------------------------------------------------------------------


def verify_seeds(brain: BrainPaths, records: RunRecords) -> dict[str, str]:
    """Re-hash every `weights.yaml` the run's checkpoint recorded. Raises `SeedMoved` on a move.

    Returns `{relative path: sha256}` for the verified set — the report's `source` group, and
    the `seed_hash` every `WeightUpdate` then carries (decision 17, row L2).

    A recorded seed that is **gone** hashes to `folders.SEED_ABSENT`, which can never equal a
    sha256, so a deleted `weights.yaml` refuses by name rather than raising `FileNotFoundError`
    out of the middle of the verification — the sentinel `seed_reader()` uses, for its reason.
    """
    verified: dict[str, str] = {}
    moved: dict[str, tuple[str, str]] = {}
    for relative in recorded_weights_keys(records.seed_hashes):
        recorded = records.seed_hashes[relative]
        path = brain.root / relative
        current = file_sha256(path) if path.is_file() else SEED_ABSENT
        if current != recorded:
            moved[relative] = (recorded, current)
        else:
            verified[relative] = current
    if moved:
        raise SeedMoved(source=records.source, moved=moved)
    return verified


# --------------------------------------------------------------------------------------
# The three producer seams
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhaseInput:
    """Everything a producer phase is handed. One argument, so a seam never grows a signature.

    `dry_run` is on it rather than around it: § Deliverable 2 says a dry run "derives
    everything" and writes no file under `brain/`, which is a decision each producer makes at
    its own write, not one the pipeline can make for it.

    `weights` and `procedures` are the fields a phase fills for a later phase (ledger `D10-1`,
    `D16-6`): the project memory the next run reads must carry `consumed_by` for **this** run's
    applied updates *and* for the pairs this run's compiled habits consumed (folded: S-17,
    ledger `D8-8`), and neither result is otherwise reachable from a frozen argument every phase
    shares. Both are keyword-defaulted, so a caller assembling a `PhaseInput` by hand — every
    collected test does — is unchanged, and a phase called without one sees `None` and consumes
    nothing.
    """

    brain: BrainPaths
    records: RunRecords
    pairs: AdmissibleSet
    seed_hashes: Mapping[str, str]
    sleep_id: str
    dry_run: bool
    weights: WeightsPhase | None = None
    procedures: ProceduresPhase | None = None


def _phase(module_name: str, entry: str, argument: PhaseInput, default: Any) -> Any:
    """Call one producer's entry point, or take the absent branch.

    Lazy and by dotted path for `resolve_seat_layer()`'s reason one verb over: the module is a
    later order's, and a checkout without it must still be able to refuse, verify, join and
    report — which is the whole of § Build process leg 2.
    """
    try:
        module = import_module(module_name)
    except ImportError:
        return None
    producer = getattr(module, entry, None)
    if producer is None:
        return None
    result = producer(argument)
    return default if result is None else result


def run_phases(argument: PhaseInput) -> tuple[Phases, list[str]]:
    """The pipeline's three phases, in the order the runtime needs them, and their notes.

    Weights (leg 3) before procedures (leg 5) before project memory (leg 4). § Build process's
    leg order is the order the legs were **built**, not the order one run executes them: project
    memory is the run's last writer because it is the only phase that persists what the two
    producers before it consumed (ledger `D16-6`).

    The window a weight update reads is project memory **as previous runs left it** — this run's
    lines are still written after every producer, which is what keeps row L8's "applies only in
    the second run" true.

    Each producer's result is threaded onto the argument the later phases receive, so the lines
    project memory writes carry `consumed_by` for both the updates this run applied and the
    pairs its compiled habits consumed, and the next run's window subtracts them (ledger
    `D10-1`, `D16-6`; folded: S-17).
    """
    notes: list[str] = []
    results: dict[str, Any] = {}
    for key, module_name, entry, empty in (
        ("weights", WEIGHTS_MODULE, WEIGHTS_ENTRY, WeightsPhase()),
        ("procedures", HABITS_MODULE, HABITS_ENTRY, ProceduresPhase()),
        ("project_memory", MEMORY_MODULE, MEMORY_ENTRY, ProjectMemoryPhase()),
    ):
        produced = _phase(module_name, entry, argument, empty)
        if produced is None:
            notes.append(PHASE_ABSENT_NOTE.format(module=module_name, name=key))
            produced = empty
        results[key] = produced
        if key == "weights":
            argument = replace(argument, weights=produced)
        elif key == "procedures":
            argument = replace(argument, procedures=produced)
    return Phases(**results), notes


# --------------------------------------------------------------------------------------
# The verb
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SleepOutcome:
    """What one `protean sleep` did, in the shape the CLI prints and a test asserts against."""

    sleep_id: str
    dry_run: bool
    report: SleepReport
    report_path: Path
    #: Every file written **under the brain root**. Empty on a `--dry-run`, by construction.
    writes: tuple[Path, ...] = ()

    @property
    def files(self) -> tuple[Path, ...]:
        """Every file this run wrote, the report included."""
        return (*self.writes, self.report_path)

    def messages(self) -> list[str]:
        """The lines the verb prints — one per file written, and nothing it did not write."""
        lines = [
            f"sleep: {self.sleep_id}" + (" (dry run: nothing under brain/ is written)"
                                         if self.dry_run else ""),
            f"sleep: read {len(self.report.source.runs)} run(s), "
            f"{self.report.evidence.admissible}/{self.report.evidence.pairs} pair(s) admissible",
            f"sleep: verified {len(self.report.source.seed_hashes)} seed hash(es)",
        ]
        lines.extend(f"wrote {path}" for path in self.writes)
        lines.append(f"wrote {self.report_path} — the sleep report")
        if self.dry_run:
            lines.extend(diff_lines(self.report))
        return lines


def run_sleep(
    brain: BrainPaths,
    *,
    source: Path | None = None,
    dry_run: bool = False,
    report_dir: Path | None = None,
    now: datetime | None = None,
) -> SleepOutcome:
    """Grade one run and write the report. Refuses twice, and verifies before it grades.

    Raises `RootOccupied` before anything is read (refusal 1), `SeedHashHeld` on a committed
    not-`done` task holding a seed this run would write (refusal 2), `SeedMoved` on a run whose
    recorded `weights.yaml` hash has moved, and `RunUnreadable` on a `--from` that names no run.
    """
    refuse_a_task_in_flight(brain)
    refuse_a_held_seed(brain)

    sleep_id = mint_sleep_id(now)
    records = load_archived_run(source) if source is not None else load_live_run(brain)
    verified = verify_seeds(brain, records)
    pairs = admissible_set(records)

    phases, notes = run_phases(
        PhaseInput(
            brain=brain,
            records=records,
            pairs=pairs,
            seed_hashes=verified,
            sleep_id=sleep_id,
            dry_run=dry_run,
        )
    )
    report = build_report(
        sleep_id=sleep_id,
        dry_run=dry_run,
        records=records,
        pairs=pairs,
        verified=verified,
        brain=brain,
        phases=phases,
        notes=notes,
    )
    destination = report_dir if report_dir is not None else sleep_report_dir(config.repo_root())
    return SleepOutcome(
        sleep_id=sleep_id,
        dry_run=dry_run,
        report=report,
        report_path=write_report(report, destination),
        writes=phases.files(),
    )


__all__ = [
    "PhaseInput",
    "SeedHashHeld",
    "SeedMoved",
    "SleepOutcome",
    "mint_sleep_id",
    "refuse_a_held_seed",
    "recorded_weights_keys",
    "refuse_a_task_in_flight",
    "run_phases",
    "run_sleep",
    "verify_seeds",
    "writable_seed_keys",
]
