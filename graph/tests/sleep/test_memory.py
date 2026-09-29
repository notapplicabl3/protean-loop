"""Row L8: project memory written per node, read back across tasks, and the cross-project split.

`the build specification (not in this mirror)` § Deliverable 5, § DoD rows L8 and N6, § Directional decisions
19 and 22, § Resolutions A1-6, S-2, S-9, S-14, S-17.

**The round trip is the deliverable and it is driven end to end.** Every arm below runs the verb
itself (`run_sleep`), never the phase in isolation, because row L8's claim is about two runs over
one brain root: the first writes the records, the second reads them back through order W3's
`read_project_memory()`, and the update applies **only** in the second. A test that called the
writer and then hand-fed the reader would prove neither half of that sentence.

**Nothing here writes into the repo's own `brain/`.** Every run copies the tracked seed tree into
`tmp_path` first (`tests.sleep.seeded_brain`), for `tests/sleep/test_weights.py`'s reason: an
applied update that reached the repo's tree would move the number `tests/state/test_brain_tree.py`
pins.

**Everything the memory phase writes lands under `brain/projects/`**, which is gitignored whole —
row N6's shape, asserted here as a property of the paths the phase returns and captured against
`git status` by the order's own receipt.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from protean import config
from protean.brain.jsonl import read_lines
from protean.runtime import paths as paths_module
from protean.sleep.memory import (
    cross_project_reason,
    line_key,
    named_projects,
    procedures_dir,
    promotes_to_node_folder,
    weights_key_of,
    write_project_memory,
)
from protean.sleep.run import run_sleep
from protean.sleep.weights import consumption_map, derive_updates, rules_for
from protean.state.enums import NodeName
from protean.state.sleep import (
    ProjectMemoryRecord,
    ProjectMemorySummary,
    load_project_memory,
)
from tests.sleep import prediction, write_run
from tests.sleep.conftest import (
    by_key,
    earlier_memory_line,
    flatten,
    habit_run,
    hippocampus_pair,
    phase_input,
)
from tests.sleep.conftest import memory_line as _memory_line

RUN_ONE = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)
RUN_TWO = datetime(2026, 9, 8, 2, 0, 0, tzinfo=UTC)
SLEEP_ID = "sleep-20260908-000000Z"
EARLIER = "task-earlier"
CURRENT = "task-fixture"
SECOND = "task-second"
SIGNAL = "hippocampus_citation"

#: Every line this module appends is one hippocampus citation, so the shared builder's two
#: constant columns are bound once here rather than repeated at every call site.
memory_line = partial(_memory_line, node=NodeName.HIPPOCAMPUS, signal=SIGNAL)


# --------------------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------------------


def run_dir(
    tmp_path: Path,
    brain,
    pairs,
    *,
    name: str,
    task: str = CURRENT,
    project: str | None = None,
) -> Path:
    """One archive-shaped run directory, its checkpoint carrying the slug it ran under."""
    return write_run(
        tmp_path / name,
        brain=brain,
        records=flatten(pairs),
        task=task,
        tick=4,
        project=project,
    )


def sleep(brain, directory: Path, tmp_path: Path, *, now: datetime, dry_run: bool = False):
    """One `protean sleep` over an archived run, reporting outside the brain root."""
    return run_sleep(
        brain,
        source=directory,
        dry_run=dry_run,
        report_dir=tmp_path / "reports",
        now=now,
    )


def lines_of(brain, node: str = "hippocampus", slug: str = paths_module.ROOT_PROJECT_SLUG):
    """Every line of one project-memory file, read back through P4's own loader."""
    return [
        load_project_memory(line)
        for line in read_lines(brain.project_learning(slug, node))
    ]


# --------------------------------------------------------------------------------------
# The written lines
# --------------------------------------------------------------------------------------


def test_a_sleep_run_writes_one_line_per_pair_and_one_summary_per_node(
    tmp_path, brain
) -> None:
    """Pair granularity, admissible **and** excluded, keyed by node (folded: S-9)."""
    directory = run_dir(
        tmp_path,
        brain,
        [
            hippocampus_pair(tick=1, matched=True),
            hippocampus_pair(tick=2, matched=False),
            hippocampus_pair(tick=3, matched=True, cited=False),
        ],
        name="run",
    )
    outcome_of = sleep(brain, directory, tmp_path, now=RUN_ONE)

    path = brain.project_learning(paths_module.ROOT_PROJECT_SLUG, "hippocampus")
    assert path.is_file()
    written = lines_of(brain)
    pairs = [row for row in written if isinstance(row, ProjectMemoryRecord)]
    summaries = [row for row in written if isinstance(row, ProjectMemorySummary)]

    assert len(pairs) == 3 and len(summaries) == 1
    assert [row.tick for row in pairs] == [1, 2, 3]
    assert [row.admissible for row in pairs] == [True, True, False]
    assert pairs[2].excluded_reason == config.EXCLUSION_VACUOUS
    assert {row.project for row in written} == {paths_module.ROOT_PROJECT_SLUG}
    assert {str(row.node) for row in written} == {str(NodeName.HIPPOCAMPUS)}
    assert {row.sleep_id for row in written} == {outcome_of.sleep_id}
    assert [row.ref for row in pairs] == [
        f"{CURRENT}:{tick}:{NodeName.HIPPOCAMPUS}:-:prediction" for tick in (1, 2, 3)
    ]


def test_the_summary_closes_the_file_with_the_runs_own_counts(tmp_path, brain) -> None:
    """The summary is a reading of the same pairs the report counts, never a second measure."""
    directory = run_dir(
        tmp_path,
        brain,
        [
            hippocampus_pair(tick=1, matched=True),
            hippocampus_pair(tick=2, matched=False),
            hippocampus_pair(tick=3, matched=True, cited=False),
        ],
        name="run",
    )
    report = sleep(brain, directory, tmp_path, now=RUN_ONE).report

    summary = lines_of(brain)[-1]
    assert isinstance(summary, ProjectMemorySummary)
    assert (summary.admissible, summary.matched) == (2, 1)
    assert summary.excluded == {
        reason: (1 if reason == config.EXCLUSION_VACUOUS else 0)
        for reason in config.SLEEP_EXCLUSION_REASONS
    }
    assert summary.admissible == report.evidence.admissible
    assert summary.updates == len(report.weights.applied())
    # a hippocampus summary counts no procedure: habits are cortex-only (ledger `D16-6`,
    # which reordered the phases and retired `D10-4`'s always-zero)
    assert summary.procedures == 0


def test_the_report_carries_every_record_in_full_and_names_the_file(tmp_path, brain) -> None:
    """`brain/projects/` is gitignored, so the report is the only review surface it has."""
    directory = run_dir(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
        name="run",
    )
    result = sleep(brain, directory, tmp_path, now=RUN_ONE)

    assert [row.model_dump(mode="json") for row in result.report.project_memory.records] == [
        row.model_dump(mode="json")
        for row in lines_of(brain)
        if isinstance(row, ProjectMemoryRecord)
    ]
    assert len(result.report.project_memory.summaries) == 1
    assert "projects/_root/memory/hippocampus/learning.jsonl" in result.report.files_written


def test_every_file_the_memory_phase_writes_is_under_brain_projects(tmp_path, brain) -> None:
    """Row N6's shape: nothing this phase writes can enter the tracked view."""
    directory = run_dir(
        tmp_path, brain, [hippocampus_pair(tick=1, matched=True)], name="run"
    )
    phase = write_project_memory(phase_input(brain, directory))

    assert phase.files
    assert all(path.is_relative_to(brain.projects) for path in phase.files)


def test_a_dry_run_derives_every_line_and_writes_no_file_under_brain(tmp_path, brain) -> None:
    """§ Deliverable 2: a dry run derives everything and writes nothing under `brain/`."""
    directory = run_dir(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
        name="run",
    )
    result = sleep(brain, directory, tmp_path, now=RUN_ONE, dry_run=True)

    assert len(result.report.project_memory.records) == 2
    assert result.report.files_written == []
    assert not brain.projects.exists()


def test_re_sleeping_one_run_appends_no_second_copy(tmp_path, brain) -> None:
    """P4's `dedupe_key()` is the append key: a repeat of the same run is a silent no-op."""
    directory = run_dir(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
        name="run",
    )
    sleep(brain, directory, tmp_path, now=RUN_ONE)
    before = brain.project_learning(paths_module.ROOT_PROJECT_SLUG, "hippocampus").read_text(
        encoding="utf-8"
    )
    sleep(brain, directory, tmp_path, now=RUN_ONE)

    assert (
        brain.project_learning(paths_module.ROOT_PROJECT_SLUG, "hippocampus").read_text(
            encoding="utf-8"
        )
        == before
    )


def test_the_append_key_is_p4s_own_dedupe_key(tmp_path, brain) -> None:
    """One key, defined on the model — never a second spelling in the writer."""
    directory = run_dir(
        tmp_path, brain, [hippocampus_pair(tick=1, matched=True)], name="run"
    )
    phase = write_project_memory(phase_input(brain, directory))
    record = phase.records[0]

    assert line_key(record.model_dump(mode="json")) == record.dedupe_key()
    assert line_key(phase.summaries[0].model_dump(mode="json")) == (
        SLEEP_ID,
        paths_module.ROOT_PROJECT_SLUG,
        str(NodeName.HIPPOCAMPUS),
        "summary",
    )


def test_the_key_field_is_null_while_one_signal_funds_several_keys(tmp_path, brain) -> None:
    """Ledger `D10-2`: which key a pair funded is `consumed_by`'s question, not this field's."""
    assert len(rules_for(SIGNAL)) > 1
    assert weights_key_of(SIGNAL) is None
    assert weights_key_of("gate_unit_survives") is None

    directory = run_dir(
        tmp_path, brain, [hippocampus_pair(tick=1, matched=True)], name="run"
    )
    phase = write_project_memory(phase_input(brain, directory))
    assert phase.records[0].key is None


# --------------------------------------------------------------------------------------
# The round trip — row L8's own sentence
# --------------------------------------------------------------------------------------


def test_the_update_applies_only_in_the_second_run(tmp_path, brain) -> None:
    """The deliverable: one fixture, two runs, and the floor cleared only by the read-back."""
    first = run_dir(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
        name="run-one",
        task=CURRENT,
    )
    second = run_dir(
        tmp_path,
        brain,
        [
            hippocampus_pair(tick=1, matched=True, task=SECOND),
            hippocampus_pair(tick=2, matched=False, task=SECOND),
        ],
        name="run-two",
        task=SECOND,
    )
    weights_file = brain.node_weights("hippocampus")
    before = weights_file.read_text(encoding="utf-8")

    one = sleep(brain, first, tmp_path, now=RUN_ONE).report
    assert one.weights.applied() == []
    assert "floor k: 2 admissible pair(s)" in by_key(one.weights.updates)[
        "candidate_window"
    ].withheld_reason
    assert weights_file.read_text(encoding="utf-8") == before
    assert len(one.project_memory.records) == 2

    two = sleep(brain, second, tmp_path, now=RUN_TWO).report
    applied = by_key(two.weights.applied())
    assert set(applied) == {"candidate_window", "semantic_window", "semantic_min_overlap"}

    window = applied["candidate_window"]
    assert window.evidence.pairs == 4
    assert window.evidence.tasks == sorted([CURRENT, SECOND])
    assert window.evidence.projects == [paths_module.ROOT_PROJECT_SLUG]
    assert (window.from_value, window.to_value) == (20, 19)
    assert weights_file.read_text(encoding="utf-8") != before


def test_the_second_runs_records_carry_this_runs_consumption(tmp_path, brain) -> None:
    """`consumed_by` is the applied updates of the run that wrote the line (folded: S-17)."""
    first = run_dir(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
        name="run-one",
    )
    second = run_dir(
        tmp_path,
        brain,
        [
            hippocampus_pair(tick=1, matched=True, task=SECOND),
            hippocampus_pair(tick=2, matched=False, task=SECOND),
        ],
        name="run-two",
        task=SECOND,
    )
    sleep(brain, first, tmp_path, now=RUN_ONE)
    result = sleep(brain, second, tmp_path, now=RUN_TWO)

    expected = consumption_map(result.report.weights.updates, result.sleep_id)
    written = [row for row in lines_of(brain) if isinstance(row, ProjectMemoryRecord)]
    first_run_lines = [row for row in written if row.sleep_id != result.sleep_id]
    second_run_lines = [row for row in written if row.sleep_id == result.sleep_id]

    assert all(row.consumed_by == {} for row in first_run_lines)
    assert second_run_lines
    for row in second_run_lines:
        assert row.consumed_by == expected[row.ref]
        assert set(row.consumed_by) == {
            "candidate_window",
            "semantic_window",
            "semantic_min_overlap",
        }
        assert row.consumed_by["candidate_window"] == (
            f"{result.sleep_id}:hippocampus/candidate_window"
        )


def test_a_compiled_habit_is_written_into_the_lines_it_consumed(tmp_path, brain) -> None:
    """S-17's procedure half, end to end: compiled, persisted, and counted (ledger `D16-6`).

    Driven through the verb rather than the writer, because the claim is about the phase
    order: `run.py` runs procedures before project memory and threads the result on, so the
    lines this run writes carry the habit that spent them and the next run's window subtracts
    exactly those pairs.
    """
    earlier_memory_line(brain)
    directory = habit_run(tmp_path, brain, name="habit-run")

    result = sleep(brain, directory, tmp_path, now=RUN_ONE)
    written = result.report.procedures.written
    assert len(written) == 1, "the fixture compiles exactly one habit"
    procedure_id = written[0].procedure_id
    identifier = f"{result.sleep_id}:{config.CORTEX_NODE}/{procedure_id}"

    lines = lines_of(brain, node=config.CORTEX_NODE)
    pairs = [
        row
        for row in lines
        if isinstance(row, ProjectMemoryRecord) and row.sleep_id == result.sleep_id
    ]
    assert pairs, "this run wrote its own cortex lines"
    consumed = [row for row in pairs if row.ref in set(written[0].compiled_from.refs)]
    assert consumed
    for row in consumed:
        assert row.consumed_by["procedures"] == identifier

    summary = [
        row
        for row in lines
        if isinstance(row, ProjectMemorySummary) and row.sleep_id == result.sleep_id
    ]
    assert len(summary) == 1
    assert summary[0].procedures == 1


# --------------------------------------------------------------------------------------
# The cross-project split
# --------------------------------------------------------------------------------------


def test_the_split_promotes_root_and_two_named_projects_and_withholds_one() -> None:
    """§ Deliverable 5's rule, stated once: `_root` evidence, or >= 2 named across >= 2 tasks."""
    root = paths_module.ROOT_PROJECT_SLUG
    assert promotes_to_node_folder(projects=[root], tasks=[CURRENT, EARLIER])
    assert not promotes_to_node_folder(projects=["alpha"], tasks=[CURRENT, EARLIER])
    assert promotes_to_node_folder(projects=["alpha", "beta"], tasks=[CURRENT, EARLIER])
    assert not promotes_to_node_folder(projects=["alpha", "beta"], tasks=[CURRENT])
    assert named_projects([root, "beta", "alpha"]) == ("alpha", "beta")
    assert cross_project_reason([root], [CURRENT, EARLIER]) == ""
    assert "cross-project rule" in cross_project_reason(["alpha"], [CURRENT, EARLIER])


def test_the_split_agrees_with_the_update_rules_own_arm(tmp_path, brain) -> None:
    """Every window row L8 grades: the two implementations return the same verdict."""
    root = paths_module.ROOT_PROJECT_SLUG
    directory = run_dir(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
        name="run",
        project="alpha",
    )
    memory_line(brain, slug="alpha", ref="r-1", task=EARLIER)

    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]
    assert not row.applied and "cross-project rule" in row.withheld_reason
    assert not promotes_to_node_folder(
        projects=row.evidence.projects, tasks=row.evidence.tasks
    )

    memory_line(brain, slug="beta", ref="r-2", task="task-beta")
    second = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]
    assert second.applied
    assert promotes_to_node_folder(
        projects=second.evidence.projects, tasks=second.evidence.tasks
    )


def test_root_slug_evidence_promotes_in_both_implementations(tmp_path, brain) -> None:
    """The `_root` arm — run 1's own case, and the one the wet oracle exercises."""
    root = paths_module.ROOT_PROJECT_SLUG
    directory = run_dir(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
        name="root-run",
    )
    memory_line(brain, slug=root, ref="r-3", task=EARLIER)

    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]
    assert row.evidence.projects == [root]
    assert row.applied
    assert promotes_to_node_folder(projects=row.evidence.projects, tasks=row.evidence.tasks)


def test_a_mixed_root_and_named_window_is_withheld_by_the_one_split(tmp_path, brain) -> None:
    """D10-6, resolved: `weights.decide()` and this module share one split predicate.

    The union spans `_root` and one named project, so neither SPEC arm is satisfied — not
    ">= 2 named projects", not "every task ran under `_root`" — and the update is withheld with
    the cross-project reason.

    The window itself stays per slug (folded: S-6): the `_root` line is what makes the floor's
    two-task arm clear, and the `alpha` line reaches only the cross-slug union (folded: S-14).
    """
    directory = run_dir(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
        name="run",
    )
    memory_line(brain, slug=paths_module.ROOT_PROJECT_SLUG, ref="r-1", task=EARLIER)
    memory_line(brain, slug="alpha", ref="r-2", task="task-alpha")

    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]
    assert row.evidence.projects == ["_root", "alpha"]
    assert not row.applied
    assert row.withheld_reason.startswith("cross-project rule")
    assert not promotes_to_node_folder(
        projects=row.evidence.projects, tasks=row.evidence.tasks
    )


def test_the_split_chooses_the_directory_a_compiled_habit_lands_in(brain) -> None:
    """S-2: single-project habits compile under that project's memory, never the node folder."""
    root = paths_module.ROOT_PROJECT_SLUG
    assert procedures_dir(
        brain, slug=root, projects=[root], tasks=[CURRENT, EARLIER]
    ) == brain.node_procedures(config.CORTEX_NODE)
    assert procedures_dir(
        brain, slug="alpha", projects=["alpha", "beta"], tasks=[CURRENT, EARLIER]
    ) == brain.node_procedures(config.CORTEX_NODE)
    assert procedures_dir(
        brain, slug="alpha", projects=["alpha"], tasks=[CURRENT, EARLIER]
    ) == brain.project_procedures("alpha")
