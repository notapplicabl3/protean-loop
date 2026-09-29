"""The update rule, and it is the whole learning algorithm: bounded steps over a hard floor.

`the build specification (not in this mirror)` § Deliverable 3 (P1's field table and *The update rule*),
§ Directional decisions 8, 9, 11, 18 and 22, § Rulings 16, § Build process leg 3, § Named
assumptions 3 and 4, § Resolutions A1-1, S-6, S-7, S-8, S-14, S-16, S-17, and § DoD rows L2
(third clause) and L4.

**It re-values an existing key and never mints, deletes or moves one** (decision 11). A key the
node's `weights.yaml` does not already carry is a *refusal* with a record, not an insert — so the
report says what the learner was asked for and declined. The gate's file is the empty mapping by
contract and is named by no map row, so `gate_unit_survives` reaches no key by any path
(`config.WEIGHTS_WRITABLE_NODES` is `NODE_ORDER` less `basal_ganglia`).

**The write is a line edit, never a YAML round-trip.** Every seed file is half comments — the operator's
own reasoning about why each number is where it is — and the tracked half of what sleep writes is
reviewed *as a git diff* (§ Automation gate, row B21). `yaml.safe_dump` would erase the comments,
reorder the keys and make that diff unreadable, which is the same failure as moving a key. So
`WeightsFile.revalue()` substitutes the value token of one line and proves the result by loading
it back: the key set must be unchanged and the key must hold exactly the value proposed.

**Every considered key produces a record, applied or withheld, with the arithmetic that decided
it.** "The tracked half's diff says *what* changed; this says *why*." A key is *considered* when
its evidence window holds at least one unconsumed admissible pair (ledger `D8-6`).

**The window, defined once** (folded: S-6, S-17): every admissible pair in project memory under
the task's slug plus the current run's, less the pairs already credited to an applied update or a
compiled procedure for that key — `consumed_by`, per `(node, key)`. Memory records are matched on
`(node, signal)` and de-duplicated by `ref`, never on P4's nullable `key`: one signal maps to as
many as three keys, so the key a pair funds is a question of `consumed_by` and not of the line.
The **cross-project test reads across slugs** (folded: S-14): the slugs an update's evidence spans
are unioned over every project's memory, because a promotion into `brain/nodes/` is what the
≥ 2-named-projects arm governs.

**The three arms of the floor, all required** (folded: A1-1, S-7, S-16):

1. `k = 3` admissible pairs across `≥ 2` distinct tasks;
2. `k = 6` **and** zero confirmations of that detector in the window for a *loosening* step —
   confirmations derived exactly as `WorkloadRunReport` derives them (D16-3,
   `protean.runtime.report`: fires off the per-tick journals' `MonitorVerdict.traps` per
   `(tick, unit, detector)`, dismissals off the manager's `trap_dismissed`, confirmations
   `max(fires - dismissals, 0)`), so no new grading field is recorded. For a key that is not a
   detector threshold the arm reads instead: `k = 6` **and every task in the evidence window
   ended `done`**;
3. the result still clears the floor `tests/state/test_brain_tree.py` enforces — `rut_ticks`,
   `forming_ticks`, `rework_window`, `abandon_window`, `mislead_window` at `>= 2`. A move that
   would breach it is **withheld, never clamped**, and that test is neither re-based nor relaxed.

**Ruling 16 governs the learner in both directions**, which is why a loosening step reads a run's
detector record at all and why an *unreadable* run is never read as favourable: a window task
whose journals or whose terminal cannot be read withholds a loosening step under its own reason
(ledger `D8-7`). "A learner that loosens `rut_ticks` on one run is the named failure."

**Zero model calls, by construction** (decision 10). Nothing here spawns anything; the module
sits inside the static grep's walked set and names no binary.

**The floor is written once and called twice.** Order W6's procedure candidate "clears the same
persistence floor as a weight update" — `clears_the_floor()` is that implementation, never a
second copy of it.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import yaml

from protean import config
from protean.brain.jsonl import read_lines
from protean.nodes.detectors import THRESHOLD_KEYS
from protean.runtime import journal as journal_module
from protean.runtime import paths as paths_module
from protean.runtime.firing import FIRING_KEYS
from protean.runtime.paths import BrainPaths
from protean.sleep.evidence import AdmissibleSet, Pair, RunRecords
from protean.sleep.report import WeightsPhase
from protean.state.enums import WINDOW_LEN_KEYS, NodeName, TrapDetector
from protean.state.outputs import MonitorVerdict
from protean.state.records import ManagerPrediction, TraceRecord
from protean.state.sleep import (
    ProjectMemoryRecord,
    UpdateEvidence,
    WeightUpdate,
    load_project_memory,
)

if TYPE_CHECKING:  # pragma: no cover - the seam's own type, resolved by dotted path at runtime
    from protean.sleep.run import PhaseInput


# --------------------------------------------------------------------------------------
# The floor's own numbers
# --------------------------------------------------------------------------------------

#: `k` for a step that tightens, and the distinct-task arm beside it (folded: A1-1).
REQUIRED_PAIRS_TIGHTEN: Final[int] = 3
REQUIRED_TASKS: Final[int] = 2

#: `k` for a step that loosens. Six, and the second arm — zero confirmations, or every task in
#: the window ended `done` — beside it (folded: S-7, S-16).
REQUIRED_PAIRS_LOOSEN: Final[int] = 6

#: The keys `tests/state/test_brain_tree.py::test_every_threshold_defaults_high_enough_to_need_persistence`
#: floors, and the value it floors them at. Taken from `state.enums.WINDOW_LEN_KEYS` rather than
#: re-listed, because that tuple is already the same five names and a second list would drift.
PERSISTENCE_FLOOR_KEYS: Final[tuple[str, ...]] = WINDOW_LEN_KEYS
PERSISTENCE_FLOOR_MINIMUM: Final[int] = 2

#: A ratio moves by 10 % of the value the run ran under (ledger `D8-5`), rounded so that two runs
#: of one fixture are byte-identical (row N3's exact-equality half).
RATIO_STEP_FRACTION: Final[float] = 0.1
RATIO_PRECISION: Final[int] = 12

#: An integer moves by exactly one (§ Deliverable 3: "Integers by ±1").
INTEGER_STEP: Final[int] = 1

#: The `terminal` a task must carry for the non-detector loosening arm (folded: S-16).
DONE_TERMINAL: Final[str] = config.TERMINAL_STATES[0]

#: `weights.yaml`, relative to a node folder — the key shape `seed_hashes` records
#: (`protean.brain.folders.seed_relative_path`).
WEIGHTS_FILENAME: Final[str] = "weights.yaml"


# --------------------------------------------------------------------------------------
# The signal→key map, with its loosening-polarity column
# --------------------------------------------------------------------------------------

#: The two polarities (folded: S-8). `LOOSEN_DOWN` is a key whose *lower* value is the loosening
#: move — a detector threshold a measured value is compared against, or an admission floor.
#: `LOOSEN_UP` is a ceiling, quota or window, whose higher value permits more.
LOOSEN_DOWN: Final[int] = -1
LOOSEN_UP: Final[int] = +1


@dataclass(frozen=True, slots=True)
class KeyRule:
    """One row of the signal→key map: which key, in which node's file, and which way is loose.

    `detector` is set exactly when the key is a *detector threshold* — the six keys of
    `protean.nodes.detectors.THRESHOLD_KEYS`, each the key its detector's value is scored
    against. It selects which arm the loosening step must clear (folded: S-7, S-16).
    """

    node: str
    key: str
    signal: str
    #: `LOOSEN_DOWN` or `LOOSEN_UP` — the sign of the loosening step.
    polarity: int
    detector: TrapDetector | None = None

    @property
    def is_detector(self) -> bool:
        return self.detector is not None

    def weights_key(self) -> str:
        """The `seed_hashes` key of the file this row re-values."""
        return f"nodes/{self.node}/{WEIGHTS_FILENAME}"


def _detector_rules() -> tuple[KeyRule, ...]:
    """`monitor_next_verdict` → the anterior cingulate's detector thresholds (ledger `D8-1`).

    `THRESHOLD_KEYS` is the map's source rather than a hand-kept list: it is documented as
    "Detector → the weights key its threshold is read from", and `TrapScalar.fired` is
    `value >= threshold`, so every one of them loosens downward.
    """
    return tuple(
        KeyRule(
            node=str(NodeName.ANTERIOR_CINGULATE),
            key=key,
            signal="monitor_next_verdict",
            polarity=LOOSEN_DOWN,
            detector=detector,
        )
        for detector, key in sorted(THRESHOLD_KEYS.items(), key=lambda row: row[1])
    )


#: § Deliverable 3's map, seeded here as the builder's default it is declared to be, with the
#: polarity column P1 requires. `dispatch_expectations` and `gate_unit_survives` name no key —
#: the first drives procedure candidacy (D4), the second is the gate's, by contract.
SIGNAL_KEY_MAP: Final[tuple[KeyRule, ...]] = (
    # `homeostasis_cost` → homeostasis's ceilings. Higher permits more (SPEC: `max_tokens`).
    KeyRule("homeostasis", "max_ticks", "homeostasis_cost", LOOSEN_UP),
    KeyRule("homeostasis", "max_tokens", "homeostasis_cost", LOOSEN_UP),
    KeyRule("homeostasis", "max_wall_seconds", "homeostasis_cost", LOOSEN_UP),
    KeyRule("homeostasis", "max_error_rate", "homeostasis_cost", LOOSEN_UP),
    # `hippocampus_citation` → the retrieval quotas and the chunk floor.
    KeyRule("hippocampus", "candidate_window", "hippocampus_citation", LOOSEN_UP),
    KeyRule("hippocampus", "semantic_window", "hippocampus_citation", LOOSEN_UP),
    KeyRule("hippocampus", "semantic_min_overlap", "hippocampus_citation", LOOSEN_DOWN),
    # `thalamus_citation` → the admission quotas and the relevance floor.
    KeyRule("thalamus", "max_admitted", "thalamus_citation", LOOSEN_UP),
    KeyRule("thalamus", "semantic_max_admitted", "thalamus_citation", LOOSEN_UP),
    KeyRule("thalamus", "min_relevance", "thalamus_citation", LOOSEN_DOWN),
    KeyRule("thalamus", "max_summary_chars", "thalamus_citation", LOOSEN_UP),
    # `manager_horizon` / `director_progress` → the cortex's four ladder counts, split by the
    # tier whose prediction the signal is (ledger `D8-3`).
    KeyRule("cortex", "k_replan", "manager_horizon", LOOSEN_DOWN),
    KeyRule("cortex", "manager_horizon", "manager_horizon", LOOSEN_UP),
    KeyRule("cortex", "k_redirect", "director_progress", LOOSEN_DOWN),
    KeyRule("cortex", "progress_window", "director_progress", LOOSEN_UP),
    # `firing_check` → each firing-key-bearing node's own threshold (build A.1, § Deliverable 1,
    # decision 18). **Four rows, one per node that carries the key**: `basal_ganglia` gets none,
    # because the gate is the stated exemption — it is outside `WEIGHTS_WRITABLE_NODES`, its
    # `weights.yaml` is contractually empty and its check is structural, reading no threshold at
    # all (folded: S-A17, folded: S-A39). One row could only ever move one node's threshold while
    # the other three stayed unlearnable.
    #
    # **`LOOSEN_UP`, and the direction is the whole point** (folded: S-A91, row B29). A cheap
    # check **fires** at `>=` its threshold, so *raising* the threshold makes the node skip more;
    # `LOOSEN_UP` is documented above as the polarity whose higher value permits more, so raising
    # it is the **loosening** move and has to clear the strict arm — k = 6 across >= 2 tasks,
    # every evidence task terminal `done`, the persistence floor green. Under `LOOSEN_DOWN` the
    # skip-more direction would fall on the k = 3 tightening arm and B29 would be inverted.
    #
    # **`detector` stays `None` and `KeyRule` gains no class** (folded: S-A64). A firing key is
    # not a `TrapDetector`, so the **existing** non-detector arm runs and no confirmations count
    # is read — which is precisely the strict arm decision 18 asks for. The key is spelled once,
    # in the node modules, and reaches here through `runtime.firing.FIRING_KEYS` exactly as the
    # detector rows reach `THRESHOLD_KEYS` (folded: D15-1).
    KeyRule("homeostasis", FIRING_KEYS["homeostasis"], "firing_check", LOOSEN_UP),
    KeyRule("hippocampus", FIRING_KEYS["hippocampus"], "firing_check", LOOSEN_UP),
    KeyRule("thalamus", FIRING_KEYS["thalamus"], "firing_check", LOOSEN_UP),
    KeyRule("anterior_cingulate", FIRING_KEYS["anterior_cingulate"], "firing_check", LOOSEN_UP),
) + _detector_rules()

#: Signal → its rows, in the map's order. `dispatch_expectations` and `gate_unit_survives` are
#: absent by design and a lookup of either is the empty tuple.
RULES_BY_SIGNAL: Final[Mapping[str, tuple[KeyRule, ...]]] = {
    signal: tuple(rule for rule in SIGNAL_KEY_MAP if rule.signal == signal)
    for signal in config.ADMISSIBLE_SIGNALS
}


def rules_for(signal: str) -> tuple[KeyRule, ...]:
    """Every key one signal may fund. Empty for the two signals that map to none."""
    return RULES_BY_SIGNAL.get(signal, ())


# --------------------------------------------------------------------------------------
# Why a record was withheld — one string per arm, each carrying its own arithmetic
# --------------------------------------------------------------------------------------


def _absent_key(rule: KeyRule, path: Path) -> str:
    return (
        f"absent key: {rule.key!r} is not in {path.name} for node {rule.node} — an update "
        f"re-values an existing key and never mints one"
    )


def _unverified_seed(rule: KeyRule) -> str:
    return (
        f"unverified seed: the run recorded no hash for {rule.weights_key()}, so an applied "
        f"update could not carry the seed_hash it was taken under"
    )


def _not_a_number(rule: KeyRule, value: Any) -> str:
    return f"not a number: {rule.key} holds {value!r}, which no bounded step is defined over"


def _zero_step(rule: KeyRule, value: Any) -> str:
    return (
        f"zero step: 10% of {value!r} moves {rule.key} nowhere, and an update that re-values "
        f"nothing is not an update"
    )


def _short_of_k(pairs: int, required: int, direction: str) -> str:
    return (
        f"floor k: {pairs} admissible pair(s) in the window, {required} required to {direction}"
    )


def _short_of_tasks(tasks: Sequence[str]) -> str:
    return (
        f"two-task rule: the window's evidence spans {len(tasks)} task(s) "
        f"({', '.join(tasks) or 'none'}), {REQUIRED_TASKS} required"
    )


def _confirmed(detector: TrapDetector, count: int) -> str:
    return (
        f"loosening arm: {count} confirmation(s) of {detector} in the window, zero required — "
        f"no update may loosen a detector that is still firing"
    )


def _not_every_task_done(terminals: Mapping[str, str | None]) -> str:
    listed = ", ".join(f"{task}={value or 'unknown'}" for task, value in sorted(terminals.items()))
    return (
        f"loosening arm: a non-detector key loosens only when every task in the window ended "
        f"{DONE_TERMINAL!r}; the window holds {listed}"
    )


def _unreadable_run(tasks: Sequence[str]) -> str:
    return (
        f"loosening arm: no readable per-tick journal for {', '.join(sorted(tasks))}, so the "
        f"detector's confirmations in the window cannot be counted and are not assumed zero"
    )


def _breaches_floor(rule: KeyRule, to_value: Any) -> str:
    return (
        f"persistence floor: {rule.key} would fall to {to_value!r} and "
        f"tests/state/test_brain_tree.py holds it at >= {PERSISTENCE_FLOOR_MINIMUM} — a move "
        f"that would breach it is withheld, never clamped"
    )


def named_projects(projects: Sequence[str]) -> tuple[str, ...]:
    """The slugs of the union less `_root`, sorted — what "named project" counts."""
    return tuple(
        sorted({slug for slug in projects if slug != paths_module.ROOT_PROJECT_SLUG})
    )


def promotes_to_node_folder(*, projects: Sequence[str], tasks: Sequence[str]) -> bool:
    """Whether this evidence may move a cross-project prior (§ Deliverable 5, folded: S-2).

    "`brain/nodes/` only when its evidence spans ≥ 2 tasks in ≥ 2 named projects … or when every
    task in its evidence ran under the `_root` slug" — the `_root` arm first, because run 1's own
    brain root carries no project and is the arm the wet oracle exercises (folded: A1-6). The ONE
    implementation: `decide()` and `sleep.memory` both call it (D10-6). A mixed `{_root, one
    named}` union satisfies neither arm and is withheld.
    """
    named = named_projects(projects)
    if not named:
        return True
    return len(named) >= 2 and len(set(tasks)) >= REQUIRED_TASKS


def _single_project(projects: Sequence[str], tasks: Sequence[str]) -> str:
    named = named_projects(projects)
    return (
        f"cross-project rule: the evidence spans {len(named)} named project(s) "
        f"({', '.join(named)}) across {len(set(tasks))} task(s); brain/nodes/ takes "
        f"{paths_module.ROOT_PROJECT_SLUG!r}-slug evidence, or >= 2 named projects across "
        f">= {REQUIRED_TASKS} tasks"
    )


def _unwritable(rule: KeyRule, path: Path) -> str:
    return (
        f"unwritable: {rule.key} is not a single top-level scalar line in {path.name}, so it "
        f"could not be re-valued in place without moving a key"
    )


# --------------------------------------------------------------------------------------
# The evidence window
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowPair:
    """One pair in the window, from the current run or from a project's memory.

    The two sources are normalised to one shape here so the floor arithmetic never asks where a
    pair came from — which is what makes "applies only in the second run" (row L8) a property of
    the *window* rather than of two code paths.
    """

    ref: str
    task: str
    project: str
    matched: bool


@dataclass(frozen=True, slots=True)
class EvidenceWindow:
    """The window for one `(node, key)`, and the slugs the cross-project union spans."""

    rule: KeyRule
    pairs: tuple[WindowPair, ...] = ()
    #: Every slug the cross-slug union saw for this `(node, key)` (folded: S-14) — the
    #: `>= 2 named projects` arm's own input, wider than the window the `k` arms count.
    projects: tuple[str, ...] = ()

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(sorted({pair.ref for pair in self.pairs}))

    @property
    def tasks(self) -> tuple[str, ...]:
        return tuple(sorted({pair.task for pair in self.pairs}))

    @property
    def matched(self) -> int:
        return sum(1 for pair in self.pairs if pair.matched)

    @property
    def match_rate(self) -> float:
        return (self.matched / len(self.pairs)) if self.pairs else 0.0

    @property
    def named_projects(self) -> tuple[str, ...]:
        """The union's slugs less `_root` — what the cross-project arm counts."""
        return tuple(
            slug for slug in self.projects if slug != paths_module.ROOT_PROJECT_SLUG
        )


def read_project_memory(brain: BrainPaths) -> tuple[ProjectMemoryRecord, ...]:
    """Every pair line under `brain/projects/*/memory/*/learning.jsonl`, every slug.

    The cross-slug read S-14 licenses, done once per run: the per-slug window is a filter over
    this, and the promotion arm reads it whole. Summary lines are dropped by P4's own `kind`
    discriminator. A version this build does not write refuses through `load_project_memory()`
    rather than being skipped — a memory file sleep cannot read is not evidence it may ignore.
    """
    found: list[ProjectMemoryRecord] = []
    projects = brain.projects
    if not projects.is_dir():
        return ()
    for slug_dir in sorted(projects.iterdir()):
        if not slug_dir.is_dir():
            continue
        for node in config.NODE_ORDER:
            path = brain.project_learning(slug_dir.name, node)
            if not path.is_file():
                continue
            for line in read_lines(path):
                record = load_project_memory(line)
                if isinstance(record, ProjectMemoryRecord):
                    found.append(record)
    return tuple(found)


def _memory_matches(record: ProjectMemoryRecord, rule: KeyRule) -> bool:
    """Whether one memory line is evidence for this rule, and still unconsumed.

    Matched on `(node, signal)` and never on P4's nullable `key`: one signal maps to as many as
    three keys, so which key a pair has funded is `consumed_by`'s question (folded: S-17).
    """
    if not record.admissible:
        return False
    if str(record.node) != rule.node or record.signal != rule.signal:
        return False
    return rule.key not in record.consumed_by


def _current_run_pairs(pairs: AdmissibleSet, rule: KeyRule) -> tuple[Pair, ...]:
    """The current run's admissible pairs for this rule's signal, in the node that owns the key.

    Counted, never re-classified (order W2 owns the classification): `admissible` is read off
    the pair the classifier returned.

    **The run's own task, and no other** (decision 22: the floor's cross-task evidence is read
    from project memory "and never off another task's node traces"). A live brain root's
    `brain/nodes/*/trace.jsonl` accumulates across tasks, so an unfiltered read would satisfy
    the two-task arm off the trace files — the exact shortcut that decision forbids.
    """
    return tuple(
        pair
        for pair in pairs.admissible
        if pair.signal == rule.signal
        and str(pair.node) == rule.node
        and (not pairs.task or pair.task == pairs.task)
    )


def evidence_window(
    rule: KeyRule,
    *,
    pairs: AdmissibleSet,
    memory: Sequence[ProjectMemoryRecord],
    slug: str,
) -> EvidenceWindow:
    """The window for one `(node, key)`: the task's slug plus the current run, less consumed.

    De-duplicated by `ref`, because a `ref` is `TraceRecord.prediction_key()` — one prediction —
    and every sleep run writes its own reading of the same pair (`ProjectMemoryRecord.
    dedupe_key()`). Without the de-duplication, re-sleeping one run twice would clear `k = 3` on
    three copies of one pair.
    """
    seen: dict[str, WindowPair] = {}
    union: set[str] = set()

    for record in memory:
        if not _memory_matches(record, rule):
            continue
        union.add(record.project)
        if record.project != slug:
            continue  # the window is per slug (folded: S-6); the union is the promotion arm's
        seen.setdefault(
            record.ref,
            WindowPair(
                ref=record.ref,
                task=record.task,
                project=record.project,
                matched=record.matched,
            ),
        )

    for pair in _current_run_pairs(pairs, rule):
        union.add(pair.project)
        seen[pair.ref] = WindowPair(
            ref=pair.ref, task=pair.task, project=pair.project, matched=pair.matched
        )

    ordered = tuple(seen[ref] for ref in sorted(seen))
    return EvidenceWindow(rule=rule, pairs=ordered, projects=tuple(sorted(union)))


# --------------------------------------------------------------------------------------
# What the loosening arm reads: confirmations, and the runs' terminals
# --------------------------------------------------------------------------------------


def _run_state_dir(brain: BrainPaths, records: RunRecords) -> Path:
    """Where the run this sleep read keeps its per-tick journals.

    An archive keeps them under `<source>/state/` and a live root under
    `brain/state/<task_id>/` — the two layouts `protean.sleep.evidence` itself resolves.
    """
    source = Path(records.source)
    if source == brain.root:
        return brain.task(records.task).state_dir
    return source / "state"


def _journal_files(state_dir: Path) -> tuple[Path, ...]:
    """Every `journal-<tick>.jsonl` under one state directory, ascending by tick."""
    if not state_dir.is_dir():
        return ()
    prefix, suffix = paths_module.JOURNAL_PREFIX, paths_module.JOURNAL_SUFFIX
    found = [
        path
        for path in state_dir.iterdir()
        if path.is_file() and path.name.startswith(prefix) and path.name.endswith(suffix)
    ]
    return tuple(sorted(found, key=lambda path: int(path.name[len(prefix) : -len(suffix)])))


def detector_fires(journals: Iterable[Path]) -> Counter[TrapDetector]:
    """Every fired scalar, counted once per `(tick, unit, detector)`.

    `protean.runtime.report.detector_fires()`'s arithmetic over the same records, reached from a
    path rather than from a `TaskPaths`: sleep reads a run it did not produce, and an archived
    run has no `TaskPaths` to hand it (folded: S-7, D16-3).
    """
    counted: Counter[TrapDetector] = Counter()
    for path in journals:
        for entry in journal_module.load(path):
            if entry.node is not NodeName.ANTERIOR_CINGULATE:
                continue
            if not isinstance(entry.output, MonitorVerdict):
                continue
            for scalar in entry.output.traps:
                if scalar.fired:
                    counted[scalar.detector] += 1
    return counted


def manager_dismissals(
    predictions: Iterable[TraceRecord], tasks: Sequence[str]
) -> Counter[TrapDetector]:
    """Every detector the manager dismissed, off the committed `ManagerPrediction` records.

    `protean.runtime.report.manager_dismissals()`'s count, restricted to the window's tasks —
    the cortex trace of a live root accumulates across tasks, and a dismissal from a run the
    window does not span is not this window's evidence.
    """
    wanted = set(tasks)
    counted: Counter[TrapDetector] = Counter()
    for record in predictions:
        if record.task not in wanted:
            continue
        if isinstance(record.prediction, ManagerPrediction):
            counted.update(record.prediction.trap_dismissed)
    return counted


@dataclass(frozen=True, slots=True)
class WindowRuns:
    """What the window's tasks put on disk: their journals, and their committed terminals."""

    journals: Mapping[str, tuple[Path, ...]] = field(default_factory=dict)
    terminals: Mapping[str, str | None] = field(default_factory=dict)

    def unreadable(self) -> tuple[str, ...]:
        """Tasks with no readable journal — never read as "no detector fired"."""
        return tuple(sorted(task for task, files in self.journals.items() if not files))

    def every_task_done(self) -> bool:
        """S-16's arm: every task in the window ended `done`, an unknown terminal counting no."""
        return bool(self.terminals) and all(
            value == DONE_TERMINAL for value in self.terminals.values()
        )

    def all_journals(self) -> tuple[Path, ...]:
        return tuple(path for files in self.journals.values() for path in files)


def _committed_terminal(brain: BrainPaths, task_id: str) -> str | None:
    """One earlier task's committed `terminal`, or `None` when it cannot be read."""
    checkpoint = brain.task(task_id).checkpoint
    if not checkpoint.is_file():
        return None
    try:
        payload: Any = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    terminal = (payload.get("state") or {}).get("terminal")
    return None if terminal is None else str(terminal)


def window_runs(
    tasks: Sequence[str], *, brain: BrainPaths, records: RunRecords
) -> WindowRuns:
    """The journals and terminals of every task the window spans.

    The current run's come from the run this sleep read — archived or live; an earlier task's
    from `brain/state/<task_id>/`, which is where a second sleep run over the same root finds
    them. Nothing here is written and nothing is assumed: an unreadable run is recorded as
    unreadable (ledger `D8-7`).
    """
    journals: dict[str, tuple[Path, ...]] = {}
    terminals: dict[str, str | None] = {}
    for task in sorted(set(tasks)):
        if task == records.task:
            journals[task] = _journal_files(_run_state_dir(brain, records))
            terminals[task] = None if records.terminal is None else str(records.terminal)
            continue
        journals[task] = _journal_files(brain.task(task).state_dir)
        terminals[task] = _committed_terminal(brain, task)
    return WindowRuns(journals=journals, terminals=terminals)


# --------------------------------------------------------------------------------------
# The bounded step
# --------------------------------------------------------------------------------------


def bounded_step(value: int | float, polarity: int, loosening: bool) -> int | float:
    """The one step this rule may propose: ±1 for an integer, ±10 % of the value for a ratio.

    The sign is the key's loosening polarity when the step loosens and its opposite when it
    tightens (folded: S-8). A ratio is rounded so two runs of one fixture write the same bytes.
    """
    sign = polarity if loosening else -polarity
    if isinstance(value, int):
        return value + sign * INTEGER_STEP
    step = round(abs(value) * RATIO_STEP_FRACTION, RATIO_PRECISION)
    return round(value + sign * step, RATIO_PRECISION)


def clears_the_floor(
    *,
    pairs: int,
    tasks: int,
    loosening: bool,
    confirmations: int = 0,
    every_task_done: bool = True,
) -> bool:
    """The persistence floor, in one place — order W6 calls this rather than copying it.

    `k = 3` across `>= 2` distinct tasks to tighten; `k = 6` plus the second arm to loosen. The
    third arm — the value the move would leave behind — is the caller's, because only the caller
    knows the number (`breaches_persistence_floor()`).
    """
    required = REQUIRED_PAIRS_LOOSEN if loosening else REQUIRED_PAIRS_TIGHTEN
    if pairs < required or tasks < REQUIRED_TASKS:
        return False
    if not loosening:
        return True
    return confirmations == 0 and every_task_done


def breaches_persistence_floor(key: str, value: int | float) -> bool:
    """Whether this move would take a floored key under `tests/state/test_brain_tree.py`'s 2."""
    return key in PERSISTENCE_FLOOR_KEYS and value < PERSISTENCE_FLOOR_MINIMUM


# --------------------------------------------------------------------------------------
# The write: one line re-valued in place
# --------------------------------------------------------------------------------------


def _key_pattern(key: str) -> re.Pattern[str]:
    """A top-level `key: value` line, with any trailing comment kept.

    Anchored at column zero, so a nested key of the same name is not a subject; the value group
    is non-greedy and stops before a `#`, so `max_ticks: 200  # the ceiling` keeps its comment.
    """
    return re.compile(
        rf"^(?P<head>{re.escape(key)}:[ \t]*)(?P<value>[^#\n]*?)(?P<tail>[ \t]*(?:#.*)?)$",
        re.MULTILINE,
    )


def format_value(value: int | float) -> str:
    """The token written back into the line. `repr` keeps a float a float and an int an int."""
    return repr(value)


class WeightsFile:
    """One `weights.yaml`, re-valued in place — comments, order and every other key untouched.

    The file is the tracked half of what sleep writes and the operator reviews it as a git diff (row B21),
    so a re-value must be a one-line diff. Every substitution is proven by loading the candidate
    text back: the key set must be unchanged (no key minted, deleted or moved) and the key must
    hold exactly the value proposed.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.text = path.read_text(encoding="utf-8")
        self.original = _load_mapping(self.text, path)
        self.dirty = False

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self.original)

    def value_of(self, key: str) -> Any:
        return self.original.get(key)

    def revalue(self, key: str, value: int | float) -> bool:
        """Substitute one line's value token. `False` leaves the text exactly as it was."""
        pattern = _key_pattern(key)
        matches = pattern.findall(self.text)
        if len(matches) != 1:
            return False
        candidate = pattern.sub(
            lambda found: f"{found.group('head')}{format_value(value)}{found.group('tail')}",
            self.text,
            count=1,
        )
        try:
            loaded = _load_mapping(candidate, self.path)
        except ValueError:
            return False
        if tuple(loaded) != self.keys or loaded.get(key) != value:
            return False
        self.text = candidate
        self.dirty = True
        return True

    def commit(self) -> Path:
        """Write the re-valued text. Called only off a run that is not a `--dry-run`."""
        self.path.write_text(self.text, encoding="utf-8")
        return self.path


def _load_mapping(text: str, path: Path) -> dict[str, Any]:
    """`protean.brain.folders.load_weights()`'s contract, over text rather than a path.

    An empty or comments-only file is the empty mapping — the gate's file, by contract — and a
    document that is not a mapping is a `ValueError`, exactly as `load_weights()` raises.
    """
    loaded = yaml.safe_load(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{path}: a weights file is a mapping, not {type(loaded).__name__}")
    return dict(loaded)


# --------------------------------------------------------------------------------------
# `was_seeded` — membership in `brain/seeds.yaml`, which order W4 writes
# --------------------------------------------------------------------------------------


def seeded_keys(brain: BrainPaths) -> frozenset[tuple[str, str]]:
    """The `(node, key)` pairs `brain/seeds.yaml` names, or nothing when it does not exist.

    Order W4 creates that file; until it lands a missing file means **no key is seeded**, and
    this never creates it (§ Deliverable 3, folded: S-10, S-15). The read is deliberately
    tolerant of the sparse `memory → (node, key, value)` shape's spelling (ledger `D8-9`): no
    `seeds:` block enters any `weights.yaml`, so this file is the only provenance there is.
    """
    path = brain.seeds
    if not path.is_file():
        return frozenset()
    found: set[tuple[str, str]] = set()
    _walk_seeds(yaml.safe_load(path.read_text(encoding="utf-8")), found)
    return frozenset(found)


def _walk_seeds(payload: Any, found: set[tuple[str, str]]) -> None:
    """Collect every `(node, key)` a seeding document names, in either spelling."""
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for item in payload:
            _walk_seeds(item, found)
        return
    if not isinstance(payload, Mapping):
        return
    node = payload.get("node")
    key = payload.get("key")
    if isinstance(node, str) and isinstance(key, str):
        found.add((node, key))
        return
    for name, value in payload.items():
        if name in config.NODE_ORDER and isinstance(value, Mapping):
            found.update((str(name), str(inner)) for inner in value)
            continue
        _walk_seeds(value, found)


# --------------------------------------------------------------------------------------
# The `## Weights` list — the other half of "no key minted, deleted or moved"
# --------------------------------------------------------------------------------------

_WEIGHTS_HEADING: Final[str] = "## Weights"
_LEADING_NAMES = re.compile(r"`([^`]+)`")


def declared_weight_keys(node_md: str) -> tuple[str, ...]:
    """The keys a `NODE.md`'s `## Weights` section *lists*, in order (ledger `D8-10`).

    The list is the leading run of backticked names, taken while consecutive names are separated
    only by commas and whitespace. Prose after the run — the anterior cingulate's note that
    `window_len` is derived and never written — is not part of the list. Row L4 pins this
    identity: sleep re-values keys and never mints, deletes or moves one, so a `## Weights` list
    that stops naming exactly its file's key set is the signature of the failure that row names.
    """
    if _WEIGHTS_HEADING not in node_md:
        return ()
    body = node_md.split(_WEIGHTS_HEADING, 1)[1]
    body = body.split("\n## ", 1)[0]
    names: list[str] = []
    position = 0
    for match in _LEADING_NAMES.finditer(body):
        gap = body[position : match.start()]
        if names and gap.strip(" \t\r\n,"):
            break
        if not names and gap.strip():
            break
        names.append(match.group(1))
        position = match.end()
    return tuple(names)


# --------------------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------------------


def update_id(sleep_id: str, node: str, key: str) -> str:
    """The id `consumed_by` records for an applied update (ledger `D8-8`).

    At most one update per `(node, key)` exists per sleep run, so the run's id and the key name
    it uniquely and make it re-findable in that run's report.
    """
    return f"{sleep_id}:{node}/{key}"


def consumption_map(
    updates: Sequence[WeightUpdate], sleep_id: str
) -> dict[str, dict[str, str]]:
    """`ref → {key: update id}` for every pair an **applied** update consumed.

    The bookkeeping half of the evidence window (folded: S-6, S-17), produced here and persisted
    by order W5 onto `ProjectMemoryRecord.consumed_by`. A withheld update consumes nothing: the
    window is "less the pairs already credited to an **applied** update or a compiled procedure".
    """
    consumed: dict[str, dict[str, str]] = {}
    for update in updates:
        if not update.applied:
            continue
        for ref in update.evidence.refs:
            consumed.setdefault(ref, {})[update.key] = update_id(
                sleep_id, str(update.node), update.key
            )
    return consumed


def _evidence_of(
    window: EvidenceWindow,
    *,
    required_pairs: int,
    confirmations: int,
    every_task_done: bool | None,
    floor_minimum: int | None,
) -> UpdateEvidence:
    """P1's `evidence` block: the pairs that drove it, and the arithmetic that decided it."""
    return UpdateEvidence(
        refs=list(window.refs),
        tasks=list(window.tasks),
        projects=list(window.projects),
        pairs=len(window.pairs),
        matched=window.matched,
        match_rate=window.match_rate,
        required_pairs=required_pairs,
        required_tasks=REQUIRED_TASKS,
        confirmations=confirmations,
        every_task_done=every_task_done,
        floor_minimum=floor_minimum,
    )


def decide(
    window: EvidenceWindow,
    *,
    weights: WeightsFile,
    runs: WindowRuns,
    dismissals: Counter[TrapDetector],
    seed_hashes: Mapping[str, str],
    seeded: frozenset[tuple[str, str]],
) -> WeightUpdate:
    """One key considered: the step it proposes, the arm that stopped it, or the move it applies.

    The arms are tested in a fixed order so a report names exactly one — the *first* thing wrong
    with the move, which is what makes a withheld record diagnostic rather than a list.
    """
    rule = window.rule
    loosening = bool(window.pairs) and window.matched == len(window.pairs)
    direction = "loosen" if loosening else "tighten"
    required_pairs = REQUIRED_PAIRS_LOOSEN if loosening else REQUIRED_PAIRS_TIGHTEN
    was_seeded = (rule.node, rule.key) in seeded
    seed_hash = seed_hashes.get(rule.weights_key(), "")

    confirmations = 0
    every_task_done: bool | None = None
    if loosening:
        if rule.detector is not None:
            fires = detector_fires(runs.all_journals())
            confirmations = max(
                fires.get(rule.detector, 0) - dismissals.get(rule.detector, 0), 0
            )
        else:
            every_task_done = runs.every_task_done()

    current = weights.value_of(rule.key)
    numeric = isinstance(current, (int, float)) and not isinstance(current, bool)
    to_value: int | float | None = None
    if numeric:
        to_value = bounded_step(current, rule.polarity, loosening)

    floor_minimum = (
        PERSISTENCE_FLOOR_MINIMUM if rule.key in PERSISTENCE_FLOOR_KEYS else None
    )

    def record(*, applied: bool, reason: str) -> WeightUpdate:
        return WeightUpdate(
            node=NodeName(rule.node),
            key=rule.key,
            from_value=current if numeric else None,
            to_value=to_value if numeric else None,
            direction=direction,
            signal=rule.signal,
            evidence=_evidence_of(
                window,
                required_pairs=required_pairs,
                confirmations=confirmations,
                every_task_done=every_task_done,
                floor_minimum=floor_minimum,
            ),
            applied=applied,
            withheld_reason=reason,
            seed_hash=seed_hash,
            was_seeded=was_seeded,
        )

    if rule.key not in weights.keys:
        return record(applied=False, reason=_absent_key(rule, weights.path))
    if not numeric:
        return record(applied=False, reason=_not_a_number(rule, current))
    if not seed_hash:
        return record(applied=False, reason=_unverified_seed(rule))
    if to_value == current:
        return record(applied=False, reason=_zero_step(rule, current))
    if len(window.pairs) < required_pairs:
        return record(
            applied=False, reason=_short_of_k(len(window.pairs), required_pairs, direction)
        )
    if len(window.tasks) < REQUIRED_TASKS:
        return record(applied=False, reason=_short_of_tasks(window.tasks))
    if loosening and rule.detector is not None:
        if runs.unreadable():
            return record(applied=False, reason=_unreadable_run(runs.unreadable()))
        if confirmations:
            return record(applied=False, reason=_confirmed(rule.detector, confirmations))
    if loosening and rule.detector is None and not runs.every_task_done():
        return record(applied=False, reason=_not_every_task_done(runs.terminals))
    if breaches_persistence_floor(rule.key, to_value):
        return record(applied=False, reason=_breaches_floor(rule, to_value))
    if not promotes_to_node_folder(projects=window.projects, tasks=window.tasks):
        return record(applied=False, reason=_single_project(window.projects, window.tasks))
    if not weights.revalue(rule.key, to_value):
        return record(applied=False, reason=_unwritable(rule, weights.path))
    return record(applied=True, reason="")


# --------------------------------------------------------------------------------------
# The phase
# --------------------------------------------------------------------------------------


def derive_updates(argument: "PhaseInput") -> WeightsPhase:
    """The weights phase: one record per considered key, and every file it re-valued.

    Resolved by dotted path from `protean.sleep.run` (D5-7), which hands over one frozen
    `PhaseInput` and takes back the phase. `dry_run` derives everything and writes no file under
    `brain/` — the decision is made here, at the write, because only this module knows what it
    would have written.
    """
    brain = argument.brain
    slug = argument.pairs.project or argument.records.project or paths_module.ROOT_PROJECT_SLUG
    memory = read_project_memory(brain)
    seeded = seeded_keys(brain)

    files: dict[str, WeightsFile] = {}
    updates: list[WeightUpdate] = []

    for rule in SIGNAL_KEY_MAP:
        window = evidence_window(rule, pairs=argument.pairs, memory=memory, slug=slug)
        if not window.pairs:
            continue  # a key with no evidence was never considered (ledger `D8-6`)
        path = brain.node_weights(rule.node)
        if not path.is_file():
            continue  # no folder, no file, nothing to re-value
        if rule.node not in files:
            files[rule.node] = WeightsFile(path)
        weights = files[rule.node]
        runs = window_runs(window.tasks, brain=brain, records=argument.records)
        dismissals = manager_dismissals(argument.records.predictions, window.tasks)
        updates.append(
            decide(
                window,
                weights=weights,
                runs=runs,
                dismissals=dismissals,
                seed_hashes=argument.seed_hashes,
                seeded=seeded,
            )
        )

    written: list[Path] = []
    if not argument.dry_run:
        for weights in files.values():
            if weights.dirty:
                written.append(weights.commit())

    return WeightsPhase(updates=tuple(updates), files=tuple(sorted(written)))


__all__ = [
    "EvidenceWindow",
    "KeyRule",
    "PERSISTENCE_FLOOR_KEYS",
    "PERSISTENCE_FLOOR_MINIMUM",
    "REQUIRED_PAIRS_LOOSEN",
    "REQUIRED_PAIRS_TIGHTEN",
    "REQUIRED_TASKS",
    "SIGNAL_KEY_MAP",
    "WeightsFile",
    "WindowPair",
    "WindowRuns",
    "bounded_step",
    "breaches_persistence_floor",
    "clears_the_floor",
    "consumption_map",
    "decide",
    "declared_weight_keys",
    "derive_updates",
    "detector_fires",
    "evidence_window",
    "manager_dismissals",
    "read_project_memory",
    "rules_for",
    "seeded_keys",
    "update_id",
    "window_runs",
]
