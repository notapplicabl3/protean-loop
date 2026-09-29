"""Every path the runtime writes, derived from one brain root and one task id.

`the build specification (not in this mirror)` § Deliverable 1's two-tree layout, § Deliverable 2 (the five
persisted artifacts), § Deliverable 3 (`brain/state/<task_id>/`, the advisory lock at the brain
root, `brain/mailbox/orphaned/`).

**One task per brain root** (§ Deliverable 3): checkpoints are task-keyed under
`brain/state/<task_id>/`, and `occupied_task()` is what `run` refuses on — a root holding a task
whose committed `terminal` is anything but `done`.

**The journal is one file per tick.** § Deliverable 3: "the journal is one file per tick,
`journal-<tick>.jsonl`, truncated on replay". § Deliverable 2 names the artifact
`journal.jsonl`; the per-tick filename is the reading taken, recorded in the dispatch ledger,
because "a tick that has journal entries but no checkpoint" is then a file-existence question
rather than a scan of a shared file.

**Nothing here creates a directory.** Creation happens at the moment of a write, in the writer,
because every generated directory under the brain root is untracked
(`protean.config.GENERATED_BRAIN_DIRS`) and a fresh checkout does not carry it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protean import config

#: The checkpoint's filename. Its **presence** is the definition of "tick completed".
CHECKPOINT_FILENAME = "checkpoint.json"

#: The temp file the checkpoint is written to before it is renamed into place.
CHECKPOINT_TEMP_SUFFIX = ".tmp"

#: `journal-<tick>.jsonl`.
JOURNAL_PREFIX = "journal-"
JOURNAL_SUFFIX = ".jsonl"

# --------------------------------------------------------------------------------------
# Build 2's brain-root paths — authored here for the whole build (ledger entry V2-3)
# --------------------------------------------------------------------------------------
#
# `the work orders (not in this mirror)` order W2: this module is read-only to orders W3–W9, so
# every path build 2 adds is derived here, once, beside build 1's. Every one of them is under
# the **brain root**, never the repo: a dry run and the workload run resolve the same names against
# different roots, which is what keeps `protean dry` incapable of writing the tracked tree.

#: The live seat configuration and the three per-tier prefixes (§ Deliverable 1, decision 9).
#: Both are hand-authored *seeds*, hashed into the checkpoint through the widened ladder.
SEATS_FILENAME = "seats.yaml"
SEATS_DIRNAME = "seats"
SEAT_PROMPT_SUFFIX = ".md"

#: The sixth persisted artifact, per task beside its checkpoints (§ Deliverable 2, S2).
SEAT_CALLS_FILENAME = "seat_calls.jsonl"

#: policy-home intake: the tracked manifest, and the generated store it writes (§ Deliverable 3).
INTAKE_DIRNAME = "intake"
INTAKE_MANIFEST_FILENAME = "manifest.yaml"
SEMANTIC_DIRNAME = "semantic"
SEMANTIC_SUFFIX = ".jsonl"

#: The run archive, one directory per terminal (§ Deliverable 6, decision 20).
ARCHIVE_DIRNAME = "archive"
ARCHIVE_PREFIX = "workload-run-"

# --------------------------------------------------------------------------------------
# Build 3's paths — authored here for the whole build (ledger entry V2-4)
# --------------------------------------------------------------------------------------
#
# `the work orders (not in this mirror)` order W2: this module is read-only to orders W3–W10, so
# every path Deliverables 2–5 name is derived here, once, beside build 2's — `brain/seeds.yaml`
# (W4), `brain/nodes/<node>/procedures/` (W6), `brain/projects/<slug>/memory/<node>/` (W5),
# `brain/projects/<slug>/memory/cortex/procedures/` (W6), `brain/state/<task_id>/habit_hits.jsonl`
# (W7) and `reports/sleep/` (W2).
#
# All but the last are under the **brain root**, for build 2's reason unchanged. `reports/sleep/`
# is the one exception and is deliberate: § Deliverable 2 puts the report outside the brain root
# ("nothing outside the brain root but its own report"), on `protean.oracle.run`'s precedent.

#: The seeding map S-28 comes in as: a new tracked seed beside `brain/seats.yaml`, hashed in the
#: widened ladder, read by the one licensed intake module and by sleep (folded: S-10, S-15).
#: **Not** a widening of `brain/intake/manifest.yaml`, whose seam S3 decision 2 inherits whole.
SEEDS_FILENAME = "seeds.yaml"

#: `procedures/` — the fourth entry of every node folder (`config.NODE_FOLDER_ENTRIES`), and
#: the first build in which anything writes one. One YAML file per compiled habit (P2).
PROCEDURES_DIRNAME = "procedures"
PROCEDURE_SUFFIX = ".yaml"

#: `brain/projects/<slug>/memory/<node>/learning.jsonl` — project memory, keyed by node, at
#: pair granularity (§ Deliverable 5, P4, folded: S-9). Gitignored, which is why `SleepReport`
#: is its only review artifact.
PROJECTS_DIRNAME = "projects"
PROJECT_MEMORY_DIRNAME = "memory"
PROJECT_LEARNING_FILENAME = "learning.jsonl"

#: The slug a task carries when it names no project (decision 22). A projectless root still
#: accumulates evidence, which is what makes the two-task floor reachable on this repo.
ROOT_PROJECT_SLUG = "_root"

#: The seventh persisted artifact, per task beside its checkpoints (§ Deliverable 4, P3). Its
#: own file rather than a `seat_calls.jsonl` line, because S2 fixes that file at one line per
#: **live** invocation and build 2's landed row W3 verified it.
HABIT_HITS_FILENAME = "habit_hits.jsonl"

#: `<repo>/reports/sleep/<sleep_id>.json` — P5's home. `reports/` is already gitignored (D14-7)
#: and already carries `reports/oracle/`; the sub-directory keeps the two products apart.
REPORTS_DIRNAME = "reports"
SLEEP_REPORTS_SUBDIRNAME = "sleep"


def sleep_report_dir(root: Path) -> Path:
    """`<root>/reports/sleep/`. Not under `brain/`, and not under `fixtures/`.

    `root` is the **repo** root rather than the brain root, exactly as
    `protean.oracle.run.default_report_dir()` takes it: the report is the one thing sleep writes
    outside the brain root, so it is the one path here that a brain root does not resolve.
    """
    return root / REPORTS_DIRNAME / SLEEP_REPORTS_SUBDIRNAME


@dataclass(frozen=True, slots=True)
class BrainPaths:
    """The root-level paths, task-independent."""

    root: Path

    @property
    def lock(self) -> Path:
        """The advisory instance lock — outside the versioned-artifact set (decision 12)."""
        return self.root / config.LOCK_FILENAME

    @property
    def mailbox_open(self) -> Path:
        """`brain/mailbox/open/` — one file per OPEN interrupt, nothing else."""
        return self.root / "mailbox" / "open"

    @property
    def mailbox_orphaned(self) -> Path:
        """Where a torn commit's orphan file is moved; never counted as open."""
        return self.root / "mailbox" / "orphaned"

    @property
    def state(self) -> Path:
        """`brain/state/` — one sub-directory per task."""
        return self.root / "state"

    @property
    def episodes(self) -> Path:
        """`brain/episodes/` — one sub-directory per task."""
        return self.root / "episodes"

    @property
    def seats(self) -> Path:
        """`brain/seats.yaml` — the whole of build 2's model configuration, a seed."""
        return self.root / SEATS_FILENAME

    @property
    def seats_dir(self) -> Path:
        """`brain/seats/` — one prefix file per tier, seeds."""
        return self.root / SEATS_DIRNAME

    def seat_prompt(self, tier: str) -> Path:
        """`brain/seats/<tier>.md` — the tier half of the seat's stable cached prefix."""
        return self.seats_dir / f"{tier}{SEAT_PROMPT_SUFFIX}"

    @property
    def intake_manifest(self) -> Path:
        """`brain/intake/manifest.yaml` — source → store, a tracked seed (S3)."""
        return self.root / INTAKE_DIRNAME / INTAKE_MANIFEST_FILENAME

    @property
    def semantic(self) -> Path:
        """`brain/semantic/` — the lexical store the intake verb writes, gitignored."""
        return self.root / SEMANTIC_DIRNAME

    def semantic_store(self, name: str) -> Path:
        """One store file, `brain/semantic/<name>.jsonl` (S4)."""
        return self.semantic / f"{name}{SEMANTIC_SUFFIX}"

    @property
    def archive(self) -> Path:
        """`brain/archive/` — where a terminal's run is copied before it can be lost."""
        return self.root / ARCHIVE_DIRNAME

    def archive_run(self, stamp: str) -> Path:
        """`brain/archive/workload-run-<ts>/` — one directory per archived run (decision 20)."""
        return self.archive / f"{ARCHIVE_PREFIX}{stamp}"

    # -- build 3 ------------------------------------------------------------------------

    @property
    def seeds(self) -> Path:
        """`brain/seeds.yaml` — the sparse `memory → (node, key, value)` map (order W4)."""
        return self.root / SEEDS_FILENAME

    def node_weights(self, node: str) -> Path:
        """`brain/nodes/<node>/weights.yaml` — the file a `WeightUpdate` re-values."""
        return config.node_dir(node, self.root) / "weights.yaml"

    def node_procedures(self, node: str) -> Path:
        """`brain/nodes/<node>/procedures/` — the cross-project half of P2 (order W6)."""
        return config.node_dir(node, self.root) / PROCEDURES_DIRNAME

    @property
    def projects(self) -> Path:
        """`brain/projects/` — one directory per slug, gitignored whole."""
        return self.root / PROJECTS_DIRNAME

    def project(self, slug: str) -> Path:
        """`brain/projects/<slug>/`. The slug is the task's own (decision 22, folded: S-12)."""
        return self.projects / slug

    def project_memory(self, slug: str, node: str) -> Path:
        """`brain/projects/<slug>/memory/<node>/` — project learning, keyed by node (P4)."""
        return self.project(slug) / PROJECT_MEMORY_DIRNAME / node

    def project_learning(self, slug: str, node: str) -> Path:
        """`brain/projects/<slug>/memory/<node>/learning.jsonl` — the pair-granular lines."""
        return self.project_memory(slug, node) / PROJECT_LEARNING_FILENAME

    def project_procedures(self, slug: str) -> Path:
        """`brain/projects/<slug>/memory/cortex/procedures/` — single-project habits (S-2)."""
        return (
            self.project_memory(slug, config.CORTEX_NODE) / PROCEDURES_DIRNAME
        )

    def task(self, task_id: str) -> TaskPaths:
        """The paths of one task under this root."""
        return TaskPaths(root=self.root, task_id=task_id)

    def task_ids(self) -> list[str]:
        """Every task with a checkpoint under this root, sorted."""
        if not self.state.exists():
            return []
        return sorted(
            entry.name
            for entry in self.state.iterdir()
            if entry.is_dir() and (entry / CHECKPOINT_FILENAME).exists()
        )


@dataclass(frozen=True, slots=True)
class TaskPaths:
    """Every path one task writes."""

    root: Path
    task_id: str

    @property
    def state_dir(self) -> Path:
        return self.root / "state" / self.task_id

    @property
    def checkpoint(self) -> Path:
        return self.state_dir / CHECKPOINT_FILENAME

    @property
    def checkpoint_temp(self) -> Path:
        """Written here, then renamed — so a crash never leaves a half-written checkpoint."""
        return self.state_dir / (CHECKPOINT_FILENAME + CHECKPOINT_TEMP_SUFFIX)

    def journal(self, tick: int) -> Path:
        return self.state_dir / f"{JOURNAL_PREFIX}{tick}{JOURNAL_SUFFIX}"

    def journal_ticks(self) -> list[int]:
        """Every tick with a journal file, ascending."""
        if not self.state_dir.exists():
            return []
        ticks: list[int] = []
        for entry in self.state_dir.iterdir():
            name = entry.name
            if name.startswith(JOURNAL_PREFIX) and name.endswith(JOURNAL_SUFFIX):
                ticks.append(int(name[len(JOURNAL_PREFIX) : -len(JOURNAL_SUFFIX)]))
        return sorted(ticks)

    @property
    def seat_calls(self) -> Path:
        """`brain/state/<task_id>/seat_calls.jsonl` — one line per **journalled call** (S2 as A.1 amends it).

        Task-keyed like the checkpoints beside it, because "calls per task" is the number
        build 3 reads and a shared file would make it a scan rather than a count.
        """
        return self.state_dir / SEAT_CALLS_FILENAME

    @property
    def habit_hits(self) -> Path:
        """`brain/state/<task_id>/habit_hits.jsonl` — one line per habit-answered tick (P3).

        Task-keyed beside `seat_calls.jsonl` for its reason unchanged: "calls drop" is the
        identity over **both** files per `(tick, tier)`, so the two have to be counted the
        same way (§ Deliverable 4, decision 14, folded: S-1).
        """
        return self.state_dir / HABIT_HITS_FILENAME

    @property
    def episodes(self) -> Path:
        return self.root / "episodes" / self.task_id / "episodes.jsonl"

    def trace(self, node: str) -> Path:
        """One node folder's append-only trace file."""
        return config.node_dir(node, self.root) / "trace.jsonl"
