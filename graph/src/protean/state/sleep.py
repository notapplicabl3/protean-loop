"""P1, P2, P4 and P5 — the four persisted models the sleep graph writes.

`the build specification (not in this mirror)` § Deliverable 2 (P5 `SleepReport` and its five groups),
§ Deliverable 3 (P1 `WeightUpdate`), § Deliverable 4 (P2 `Procedure`), § Deliverable 5
(P4 `ProjectMemoryRecord`), § Scaffold clause (the five seam contracts this build introduces),
§ Resolutions S-2, S-6, S-8, S-9, S-13, S-14, S-16, S-17.

**Authored in one pass, read-only to orders W3–W10** (`the work orders (not in this mirror)`
order W2, ledger entry V2-4). Every field below is taken from the SPEC's own tables rather than
from what this order happens to need: W3 fills `weights`, W5 fills `project_memory`, W6 fills
`procedures`, and a producer that finds a field missing writes a `BLOCKED` entry rather than
widening a seam contract at the keyboard.

**They live beside their writers on `state/seat_calls.py`'s precedent** (D8-1) and are **not**
exported through `protean.state`'s roster, following `oracle.py`, `semantic.py`, `seat_calls.py`
and `run_report.py` (folded: D8-2): the roster is build 1's inter-node contract set, and none of
these is a contract between two nodes.

**Nothing here computes.** Every model is a container; `protean.sleep` derives the numbers from
the traces, `seat_calls.jsonl` and `habit_hits.jsonl` and fills them in (row L9: "every number
derived … none hardcoded"). The two exceptions are `SleepReport.excluded` and
`SignalEvidence.excluded_total`, which are *readings* of rows already on the model rather than
measurements of their own — the same carve-out `DetectorTelemetry.over_firing` takes.

**P3 `HabitHit` is not here.** It lands on `protean.state.habit_hits` (order W7), beside the
runtime that writes it at the tick boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from pydantic import Field, JsonValue

from protean import config
from protean.state.base import ProteanModel
from protean.state.enums import NodeName, TerminalState, Tier
from protean.state.errors import SchemaVersionMismatch

#: The artifact names a refusal quotes, so a captured `SchemaVersionMismatch` names the file.
#: They are the keys of `config.BUILD3_ARTIFACT_SCHEMA_VERSIONS`, not a second list.
WEIGHT_UPDATE_ARTIFACT: Final[str] = "weight_update"
PROCEDURE_ARTIFACT: Final[str] = "procedure"
PROJECT_MEMORY_ARTIFACT: Final[str] = "project_memory"
SLEEP_REPORT_ARTIFACT: Final[str] = "sleep_report"

#: § Deliverable 3's numeric-risk axis (folded: S-8). `loosen` is the move that makes a
#: detector, ceiling or admission fire more readily; which direction that is for a given key is
#: the signal→key map's `loosening polarity` column, never a property of the number itself.
UpdateDirection = Literal["tighten", "loosen"]


def refuse_mismatch(payload: Mapping[str, Any], *, artifact: str, expected: int) -> None:
    """Raise `SchemaVersionMismatch` unless the payload carries the version this code writes.

    One refusal for all four models, on `protean.state.seat_calls.load_seat_calls()`'s shape:
    build 3 ships no migration path either, so a version this loader does not recognise is a
    stop and not a conversion.
    """
    found = int(payload.get("schema_version", -1))
    if found != expected:
        raise SchemaVersionMismatch(artifact=artifact, found=found, expected=expected)


# --------------------------------------------------------------------------------------
# P1 — `WeightUpdate`: one re-valued key, its evidence, and the seed hash it was taken under
# --------------------------------------------------------------------------------------


class UpdateEvidence(ProteanModel):
    """The admissible pairs that drove one update, and the floor arithmetic they decide.

    § Deliverable 3's `signal` · `evidence` row is "the admissible pairs that drove it: their
    `ref`s, their tasks, and the match rate"; § Deliverable 2's `weights` group asks for "the
    floor arithmetic that decided it" beside them. Both live here, so `withheld_reason` names
    an arm and this says which numbers that arm read.

    `projects` is the cross-project test's own input (folded: S-14): the promotion of an update
    into `brain/nodes/` unions every project's memory for that `(node, key)`, so the slugs the
    window spanned are part of the arithmetic rather than a fact recomputed by a reader.
    """

    #: Every admissible pair's `ref`, exactly — what P4's pair granularity exists to make
    #: fillable (folded: S-9).
    refs: list[str] = Field(default_factory=list)
    #: The distinct tasks those `ref`s came from — the `≥ 2 distinct tasks` arm's numerator.
    tasks: list[str] = Field(default_factory=list)
    #: The distinct project slugs, `_root` included — the `≥ 2 named projects` arm's.
    projects: list[str] = Field(default_factory=list)
    #: Admissible pairs in the window, and how many of them graded `matched: true`.
    pairs: int = 0
    matched: int = 0
    #: `matched / pairs`, `0.0` on an empty window.
    match_rate: float = 0.0
    #: The k this move had to clear — 3 to tighten, 6 to loosen (folded: A1-1).
    required_pairs: int = 0
    #: The distinct-task floor this move had to clear.
    required_tasks: int = 0
    #: The loosening arm's detector confirmations in the window, derived exactly as
    #: `WorkloadRunReport` derives them (D16-3, folded: S-7). Meaningless on a tightening move.
    confirmations: int = 0
    #: The loosening arm for a key that is **not** a detector threshold: every task in the
    #: window ended `done` (folded: S-16). `None` when the arm did not apply.
    every_task_done: bool | None = None
    #: The floor `tests/state/test_brain_tree.py:171-179` enforces for this key, when it names
    #: one. A move that would breach it is withheld rather than clamped.
    floor_minimum: int | None = None


class WeightUpdate(ProteanModel):
    """P1 — one record per key **considered**, applied or withheld (§ Deliverable 3).

    A key not already present in the node's `weights.yaml` is a refusal, not an insert
    (decision 11): such a record is written with `applied: false` and a `withheld_reason`
    naming the absent key, so the report says what the learner was asked for and declined.
    """

    schema_version: int = config.WEIGHT_UPDATE_SCHEMA_VERSION
    #: Which existing key, in which node's file. The gate is never a subject: its
    #: `weights.yaml` is the empty mapping by contract (`config.WEIGHTS_WRITABLE_NODES`).
    node: NodeName
    key: str
    #: The bounded move. Integers by ±1, ratios by ±10% of the **seeded** value, never an
    #: arbitrary value. `to_value` equals `from_value` on a record that names an absent key.
    from_value: float | int | None = None
    to_value: float | int | None = None
    direction: UpdateDirection
    #: The signal whose admissible pairs funded it — one of `config.ADMISSIBLE_SIGNALS`.
    signal: str
    evidence: UpdateEvidence = Field(default_factory=UpdateEvidence)
    #: Whether it landed, and if not, which arm of the floor stopped it. Exactly one of the
    #: two is informative: an applied update carries an empty reason.
    applied: bool = False
    withheld_reason: str = ""
    #: The verified hash the run ran under (decision 17) — the file's own, re-hashed before
    #: the first update was derived. This is what makes the archive's missing seed *values*
    #: self-closing: the first sleep run's report is the durable record of run 1's thresholds.
    seed_hash: str = ""
    #: Whether the key is named in `brain/seeds.yaml`'s seeding map (folded: S-10, S-15). Any
    #: applied move on a seeded key weakens the seed — the orthogonal fact to `direction`.
    was_seeded: bool = False

    def landed_under(self) -> str:
        """The one-line receipt the `--dry-run` diff prints: what moved, and under which hash."""
        verb = "apply" if self.applied else "withhold"
        return (
            f"{verb} {self.node}/{self.key}: {self.from_value!r} -> {self.to_value!r} "
            f"({self.direction}, seed_hash={self.seed_hash[:12]}"
            f"{', seeded' if self.was_seeded else ''})"
            + ("" if self.applied else f" — {self.withheld_reason}")
        )


# --------------------------------------------------------------------------------------
# P2 — `Procedure`: the compiled habit's on-disk format under `procedures/`
# --------------------------------------------------------------------------------------


class CompiledFrom(ProteanModel):
    """P2's provenance: the run a habit was compiled from, and the `ref`s that funded it.

    § Deliverable 4 names the field "`compiled_from` (the run and the `ref`s)". Both runs are
    carried because both are needed to re-find the evidence: `sleep_id` names the sleep run
    that wrote the file, `source` names the workload run it read, `tasks` the tasks inside it.
    """

    sleep_id: str = ""
    #: The run read — an archive directory name under `--from`, or the live task's id.
    source: str = ""
    tasks: list[str] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)


class ProcedureResponse(ProteanModel):
    """One response of the compiled `SeatScript` — the half `parse_script()` reads.

    `when` is a `ResponseCondition` payload and is validated by `protean.cortex.scripts`, never
    here: this build widens `CONDITION_KEYS` by exactly one key (`goal_digest`, folded: S-3) in
    that module, and a second copy of the closed set here would be a second thing to drift.
    A compiled condition binds `goal_digest` and never `unit_id` — order W6's rule, checked
    where the candidate is compiled.
    """

    tier: Tier
    when: dict[str, JsonValue] = Field(default_factory=dict)
    result: dict[str, JsonValue] = Field(default_factory=dict)
    usage: dict[str, int] = Field(default_factory=dict)


class Procedure(ProteanModel):
    """P2 — one compiled habit, as the YAML file under `procedures/` holds it.

    **A compiled `SeatScript` and nothing more exotic** (decision 13): `name` and `responses`
    are exactly what `protean.cortex.scripts.parse_script()` reads, and the five provenance
    fields beside them are ones that loader ignores — it reads by key and never refuses an
    unknown one, which is what lets sleep write provenance without touching build 1's format.

    Where the file lands carries the cross-project split (folded: S-2): `brain/nodes/cortex/
    procedures/` for `_root`-slug or ≥ 2-named-project evidence, `brain/projects/<slug>/memory/
    cortex/procedures/` for single-project evidence. The split is the path, never a field —
    the same way a `WeightUpdate`'s is.
    """

    schema_version: int = config.PROCEDURE_SCHEMA_VERSION
    #: Precedence across procedure files is lexical by this id, first match, one per tick.
    procedure_id: str
    #: `SeatScript.name`. Equal to `procedure_id` unless a compiler has reason otherwise.
    name: str = ""
    #: Compiled, never seeded — the field that keeps a habit distinguishable from a prior.
    seed: Literal[False] = False
    #: The persistence floor this habit cleared, carried so a reader can see what it cost.
    hits_required: int = 0
    compiled_from: CompiledFrom = Field(default_factory=CompiledFrom)
    responses: list[ProcedureResponse] = Field(default_factory=list)

    def script_payload(self) -> dict[str, Any]:
        """The mapping `parse_script()` takes — provenance included, and ignored by it.

        Written whole rather than split, so the file on disk and the record in `SleepReport`
        are the same bytes' worth of facts and a reader never has to join them.
        """
        return self.model_dump(mode="json")


class RejectedCandidate(ProteanModel):
    """A habit the run nearly compiled, and why it did not (§ Deliverable 2's `procedures`).

    "Where the operator sees what the loop *nearly* learned" — row B22's other half. Carried in the
    report only; nothing is written to disk for a candidate that was rejected.
    """

    procedure_id: str = ""
    tier: Tier | None = None
    #: The condition set the candidate would have bound, as it stood when it was rejected.
    when: dict[str, JsonValue] = Field(default_factory=dict)
    refs: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    #: Which gate stopped it: inadmissible evidence, an unmatched outcome, or the floor.
    reason: str


class WithdrawnProcedure(ProteanModel):
    """A habit that stopped working, deleted by this run (§ Deliverable 4, *un-learning*).

    "The file is deleted and the deletion is a line in the report and in the git diff." The
    path is carried because the git diff shows only the tracked half.
    """

    procedure_id: str
    path: str
    #: Consecutive hits grading `matched: false`, and the k that withdrawal needed.
    failed_hits: int = 0
    hits_required: int = 0
    reason: str = ""


# --------------------------------------------------------------------------------------
# P4 — `ProjectMemoryRecord`: project-specific node learning, keyed by node
# --------------------------------------------------------------------------------------


class ProjectMemoryRecord(ProteanModel):
    """P4 — one line per admissible **or excluded** pair (§ Deliverable 5, folded: S-9).

    Pair granularity is what makes P1's `evidence` fillable across runs: the floor's second
    task is read back from here, never off another task's node traces (decision 22, folded:
    S-2). `key` is nullable because a signal with no weights key — `gate_unit_survives`,
    `dispatch_expectations` — still tallies as evidence for procedure candidacy.
    """

    schema_version: int = config.PROJECT_MEMORY_SCHEMA_VERSION
    #: The task's own slug, `_root` when it named no project (decision 22, folded: S-12).
    project: str
    node: NodeName
    sleep_id: str
    task: str
    tick: int
    #: The prediction's `prediction_key()` — the join both halves of the pair carry.
    ref: str
    signal: str
    key: str | None = None
    matched: bool = False
    admissible: bool = False
    #: One of `config.SLEEP_EXCLUSION_REASONS`, empty on an admissible pair.
    excluded_reason: str = ""
    #: `key → WeightUpdate or Procedure id` for each key this pair has funded — empty until it
    #: funds one. Consumption is per `(node, key)`: a pair funds at most one update per key its
    #: signal maps to (folded: S-17), which is what keeps the evidence window from double-
    #: counting across runs (folded: S-6).
    consumed_by: dict[str, str] = Field(default_factory=dict)

    def dedupe_key(self) -> tuple[str, str, str, str]:
        """`(sleep_id, project, node, ref)` — a re-run of one sleep is a silent no-op.

        `sleep_id` is in the key rather than out of it because the *next* sleep run writes the
        same `ref` again with its own `consumed_by`; two runs' readings of one pair are two
        lines, and only a repeat of the same run collapses.
        """
        return (self.sleep_id, self.project, str(self.node), self.ref)


class ProjectMemorySummary(ProteanModel):
    """The one summary line per sleep run that closes a node's file (§ Deliverable 5).

    Beside the pair lines rather than instead of them: the pairs are what the floor reads, the
    summary is what a human reads, and the two are written to the same file so a run's whole
    contribution is one contiguous block.
    """

    schema_version: int = config.PROJECT_MEMORY_SCHEMA_VERSION
    project: str
    node: NodeName
    sleep_id: str
    admissible: int = 0
    matched: int = 0
    #: By reason, over `config.SLEEP_EXCLUSION_REASONS`.
    excluded: dict[str, int] = Field(default_factory=dict)
    updates: int = 0
    procedures: int = 0
    #: The discriminator that keeps a summary line and a pair line apart on one file.
    kind: Literal["summary"] = "summary"


# --------------------------------------------------------------------------------------
# P5 — `SleepReport`: the run's own receipt, and the review artifact for the gitignored half
# --------------------------------------------------------------------------------------


class RunRead(ProteanModel):
    """One run this sleep read: where it came from, and what it was.

    § Deliverable 2's `source` group is "the run(s) read, their task ids, tick counts, and the
    seed hashes verified". The list is plural because the group is; sleep reads **one run per
    invocation**, so it carries one entry today (folded: S-13).
    """

    #: `--from`'s archive directory, or the brain root the live traces were read from.
    source: str
    task: str
    ticks: int = 0
    terminal: TerminalState | None = None
    #: The task's own project slug, read off its checkpoint (decision 22).
    project: str = ""


class SourceGroup(ProteanModel):
    """§ Deliverable 2's `source` group — what the update was taken *under* (decision 17)."""

    runs: list[RunRead] = Field(default_factory=list)
    #: `{relative path: sha256}` for every `weights.yaml` the checkpoint recorded and this run
    #: **re-hashed and found unmoved**. A moved hash refuses the run as evidence instead, so a
    #: report that exists carries a verified set by construction.
    seed_hashes: dict[str, str] = Field(default_factory=dict)
    #: The brain root the seeds were verified against — the tree the hashes are *of*.
    brain_root: str = ""


class SignalEvidence(ProteanModel):
    """One signal's row of the `evidence` group: pairs seen, admissible, and the exclusions.

    "A rising exclusion count is a defect detector for the layer above" — which is why the
    map is keyed by reason rather than totalled.
    """

    signal: str
    pairs: int = 0
    admissible: int = 0
    matched: int = 0
    #: Reason → count, over `config.SLEEP_EXCLUSION_REASONS`.
    excluded: dict[str, int] = Field(default_factory=dict)

    @property
    def excluded_total(self) -> int:
        """A reading of the row above, not a second measurement."""
        return sum(self.excluded.values())


class EvidenceGroup(ProteanModel):
    """§ Deliverable 2's `evidence` group — Deliverable 1's admissible set, made countable."""

    signals: list[SignalEvidence] = Field(default_factory=list)
    pairs: int = 0
    admissible: int = 0
    #: Every exclusion, by reason, over every signal — row L1's own map. Serialized rather
    #: than derived at read time, because the row's check reads it out of the written JSON.
    excluded: dict[str, int] = Field(default_factory=dict)

    def signal(self, name: str) -> SignalEvidence | None:
        return next((row for row in self.signals if row.signal == name), None)


class WeightsGroup(ProteanModel):
    """§ Deliverable 2's `weights` group — every update, applied or withheld, with its floor."""

    updates: list[WeightUpdate] = Field(default_factory=list)

    def applied(self) -> list[WeightUpdate]:
        return [row for row in self.updates if row.applied]

    def withheld(self) -> list[WeightUpdate]:
        return [row for row in self.updates if not row.applied]


class ProceduresGroup(ProteanModel):
    """§ Deliverable 2's `procedures` group — written, rejected **and** withdrawn."""

    written: list[Procedure] = Field(default_factory=list)
    rejected: list[RejectedCandidate] = Field(default_factory=list)
    withdrawn: list[WithdrawnProcedure] = Field(default_factory=list)


class ProjectMemoryGroup(ProteanModel):
    """§ Deliverable 2's `project_memory` group — every P4 record written, **in full**.

    In full rather than counted, and that is the whole reason P5 is a required deliverable:
    `brain/projects/` is gitignored, so this is the only review artifact the untracked half
    has (§ Automation gate). A run whose report was not read has had half its output reviewed.
    """

    records: list[ProjectMemoryRecord] = Field(default_factory=list)
    summaries: list[ProjectMemorySummary] = Field(default_factory=list)


class SleepReport(ProteanModel):
    """P5 — one sleep run's receipt: five groups, and no `comparison` group (folded: S-13).

    The two-run numbers of decision 20 are `tests/wet/run_sleep_compare.py`'s own output, a
    builder's default beside `reports/sleep/`, never a seam field: sleep reads **one run per
    invocation**, so a comparison group would have no second subject to hold.
    """

    schema_version: int = config.SLEEP_REPORT_SCHEMA_VERSION
    sleep_id: str
    #: `--dry-run` derives everything and writes no file under `brain/`; the report is written
    #: either way, and this is how a reader tells the two apart.
    dry_run: bool = False
    source: SourceGroup = Field(default_factory=SourceGroup)
    evidence: EvidenceGroup = Field(default_factory=EvidenceGroup)
    weights: WeightsGroup = Field(default_factory=WeightsGroup)
    procedures: ProceduresGroup = Field(default_factory=ProceduresGroup)
    project_memory: ProjectMemoryGroup = Field(default_factory=ProjectMemoryGroup)
    #: Every file the run wrote under the brain root, brain-root-relative. Empty on a
    #: `--dry-run` by construction, which is what row L3's second half reads.
    files_written: list[str] = Field(default_factory=list)
    #: What the run could not do, in the run's own words. Empty on a clean run.
    notes: list[str] = Field(default_factory=list)

    @property
    def excluded(self) -> Mapping[str, int]:
        """Row L1's map: every excluded pair counted under its reason. A reading, not a count."""
        return self.evidence.excluded

    def render(self) -> str:
        """One screen of the run, for the operator surface and for a captured receipt."""
        excluded = ", ".join(
            f"{reason}={self.evidence.excluded.get(reason, 0)}"
            for reason in config.SLEEP_EXCLUSION_REASONS
        )
        return "\n".join(
            [
                f"sleep     {self.sleep_id}{' (dry run)' if self.dry_run else ''}",
                f"source    {', '.join(row.task for row in self.source.runs) or '-'} "
                f"({sum(row.ticks for row in self.source.runs)} tick(s), "
                f"{len(self.source.seed_hashes)} seed hash(es) verified)",
                f"evidence  {self.evidence.admissible}/{self.evidence.pairs} admissible",
                f"excluded  {excluded}",
                f"weights   {len(self.weights.applied())} applied, "
                f"{len(self.weights.withheld())} withheld",
                f"habits    {len(self.procedures.written)} written, "
                f"{len(self.procedures.rejected)} rejected, "
                f"{len(self.procedures.withdrawn)} withdrawn",
                f"memory    {len(self.project_memory.records)} pair record(s)",
                f"files     {len(self.files_written)} written under the brain root",
            ]
        )


# --------------------------------------------------------------------------------------
# Loaders — one refusal shape, four artifacts
# --------------------------------------------------------------------------------------


def load_weight_update(payload: Mapping[str, Any]) -> WeightUpdate:
    """One P1 record, refusing a `schema_version` this code does not write."""
    refuse_mismatch(
        payload,
        artifact=WEIGHT_UPDATE_ARTIFACT,
        expected=config.WEIGHT_UPDATE_SCHEMA_VERSION,
    )
    return WeightUpdate.model_validate(payload)


def load_procedure(payload: Mapping[str, Any]) -> Procedure:
    """One P2 file's mapping, refusing a `schema_version` this code does not write."""
    refuse_mismatch(
        payload, artifact=PROCEDURE_ARTIFACT, expected=config.PROCEDURE_SCHEMA_VERSION
    )
    return Procedure.model_validate(payload)


def load_project_memory(payload: Mapping[str, Any]) -> ProjectMemoryRecord | ProjectMemorySummary:
    """One P4 line, pair or summary, refusing a `schema_version` this code does not write.

    The two shapes share a file, so the `kind` discriminator picks which model reads the line;
    a pair line carries no `kind` at all, which is what keeps build 3's first written line
    readable by a loader that never saw a summary.
    """
    refuse_mismatch(
        payload,
        artifact=PROJECT_MEMORY_ARTIFACT,
        expected=config.PROJECT_MEMORY_SCHEMA_VERSION,
    )
    if str(payload.get("kind", "")) == "summary":
        return ProjectMemorySummary.model_validate(payload)
    return ProjectMemoryRecord.model_validate(payload)


def load_sleep_report(payload: Mapping[str, Any]) -> SleepReport:
    """One P5 report, refusing a `schema_version` this code does not write."""
    refuse_mismatch(
        payload, artifact=SLEEP_REPORT_ARTIFACT, expected=config.SLEEP_REPORT_SCHEMA_VERSION
    )
    return SleepReport.model_validate(payload)


__all__ = [
    "CompiledFrom",
    "EvidenceGroup",
    "Procedure",
    "ProcedureResponse",
    "ProceduresGroup",
    "ProjectMemoryGroup",
    "ProjectMemoryRecord",
    "ProjectMemorySummary",
    "RejectedCandidate",
    "RunRead",
    "SignalEvidence",
    "SleepReport",
    "SourceGroup",
    "UpdateDirection",
    "UpdateEvidence",
    "WeightUpdate",
    "WeightsGroup",
    "WithdrawnProcedure",
    "load_procedure",
    "load_project_memory",
    "load_sleep_report",
    "load_weight_update",
    "refuse_mismatch",
]
