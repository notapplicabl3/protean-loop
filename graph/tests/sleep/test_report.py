"""Row L9: `SleepReport` is written, carries all five groups, and hardcodes no number.

`the build specification (not in this mirror)` § Deliverable 2 → *S5's mirror — P5 `SleepReport`* and its
group table, § Automation gate (the split review surface), § Resolutions S-13, § DoD row L9.

**Five groups, and no `comparison` group** (folded: S-13). The three producer groups are filled
by orders W3, W5 and W6; this order proves they round-trip field for field, so a producer that
lands its phase writes into a shape already known to serialize.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean import config
from protean.sleep import report as report_module
from protean.sleep import run as run_module
from protean.sleep.report import Phases, ProceduresPhase, ProjectMemoryPhase, WeightsPhase
from protean.sleep.run import run_sleep
from protean.state.enums import NodeName, Tier
from protean.state import sleep as state_sleep_module
from protean.state.records import ThalamusOutcome, ThalamusPrediction
from protean.state.sleep import (
    CompiledFrom,
    Procedure,
    ProcedureResponse,
    ProceduresGroup,
    ProjectMemoryGroup,
    ProjectMemoryRecord,
    ProjectMemorySummary,
    RejectedCandidate,
    SleepReport,
    UpdateEvidence,
    WeightUpdate,
    WeightsGroup,
    WithdrawnProcedure,
    load_sleep_report,
)
from tests.sleep import outcome, prediction, seeded_brain, write_run
from tests.sleep.conftest import numeric_literals

#: § Deliverable 2's table, transcribed. The absence is as binding as the presence.
GROUPS = ("source", "evidence", "weights", "procedures", "project_memory")


@pytest.fixture(scope="module")
def report_brain(tmp_path_factory: pytest.TempPathFactory, repo_root: Path):
    """The one brain root the module's `--from` run sleeps on. Nothing may write into it."""
    return seeded_brain(tmp_path_factory.mktemp("report-brain"), repo_root)


@pytest.fixture(scope="module")
def written(report_brain, tmp_path_factory: pytest.TempPathFactory):
    """One `--from` run over a fixture, and the report it wrote, read back off disk.

    Module-scoped: the run and its report are a read-only artifact and five tests read them, so
    one `run_sleep()` answers all five. `test_a_report_of_another_schema_version_is_refused`
    mutates a `dict(payload)` copy rather than the shared payload.
    """
    tmp_path = tmp_path_factory.mktemp("report-run")
    predicted = prediction(
        node=NodeName.THALAMUS, payload=ThalamusPrediction(admitted_ids=["admitted:e-1"])
    )
    directory = write_run(
        tmp_path / "run",
        brain=report_brain,
        task="task-report",
        tick=2,
        records=[
            predicted,
            outcome(
                predicted, ThalamusOutcome(cited_admitted_ids=["admitted:e-1"], matched=True)
            ),
        ],
    )
    result = run_sleep(report_brain, source=directory, report_dir=tmp_path / "reports")
    return result, json.loads(result.report_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# The five groups, on disk
# --------------------------------------------------------------------------------------


def test_the_written_report_carries_all_five_groups_and_no_comparison(written) -> None:
    _, payload = written
    for group in GROUPS:
        assert group in payload, group
    assert "comparison" not in payload


def test_source_and_evidence_are_populated_from_the_run(written, report_brain) -> None:
    """Every field of the two read-off-the-run groups, and row L9's "none hardcoded" from the
    other end: every count equals what the pairs actually held (folded: audit row S6)."""
    result, payload = written
    assert payload["source"]["runs"][0]["task"] == "task-report"
    assert payload["source"]["runs"][0]["ticks"] == 2
    assert payload["source"]["brain_root"] == str(report_brain.root)
    # every recorded weights.yaml is verified, the gate's included (P6-1)
    assert len(payload["source"]["seed_hashes"]) == len(config.NODE_ORDER)
    assert payload["evidence"]["pairs"] == 1
    assert payload["evidence"]["admissible"] == 1
    assert sorted(payload["evidence"]["excluded"]) == sorted(config.SLEEP_EXCLUSION_REASONS)
    assert [row["signal"] for row in payload["evidence"]["signals"]] == ["thalamus_citation"]
    assert result.report.excluded == result.report.evidence.excluded

    pairs = payload["evidence"]["pairs"]
    assert pairs == sum(row["pairs"] for row in payload["evidence"]["signals"])
    assert payload["evidence"]["admissible"] == sum(
        row["admissible"] for row in payload["evidence"]["signals"]
    )
    assert sum(payload["evidence"]["excluded"].values()) == pairs - payload["evidence"][
        "admissible"
    ]
    assert result.report.source.runs[0].ticks == 2


def test_the_report_reads_back_through_its_own_version_refusal(written) -> None:
    result, payload = written
    assert load_sleep_report(payload) == result.report
    assert report_module.load_report_file(result.report_path) == result.report


def test_a_report_of_another_schema_version_is_refused(written) -> None:
    from protean.state.errors import SchemaVersionMismatch

    _, shared = written
    # a copy: `written` is module-scoped and the other four tests read the payload as written
    payload = dict(shared)
    payload["schema_version"] = config.SLEEP_REPORT_SCHEMA_VERSION + 1
    with pytest.raises(SchemaVersionMismatch):
        load_sleep_report(payload)


# --------------------------------------------------------------------------------------
# The three producer groups, field for field
# --------------------------------------------------------------------------------------


def _phases() -> Phases:
    """One instance of each of P1, P2 and P4, as the three later orders will return them."""
    update = WeightUpdate(
        node=NodeName.ANTERIOR_CINGULATE,
        key="rut_ticks",
        from_value=3,
        to_value=4,
        direction="tighten",
        signal="monitor_next_verdict",
        evidence=UpdateEvidence(
            refs=["task-a:1:anterior_cingulate:-:prediction"],
            tasks=["task-a", "task-b"],
            projects=["demo"],
            pairs=3,
            matched=2,
            match_rate=0.5,
            required_pairs=3,
            required_tasks=2,
            confirmations=1,
            every_task_done=True,
            floor_minimum=2,
        ),
        applied=True,
        seed_hash="f" * 64,
        was_seeded=True,
    )
    procedure = Procedure(
        procedure_id="habit-0001",
        name="habit-0001",
        hits_required=3,
        compiled_from=CompiledFrom(
            sleep_id="sleep-x", source="workload-run-1", tasks=["task-a"], refs=["r-1"]
        ),
        responses=[
            ProcedureResponse(
                tier=Tier.MANAGER,
                when={"goal_digest": "0123456789abcdef"},
                result={"unit_id": "$unit"},
                usage={"input_tokens": 1},
            )
        ],
    )
    record = ProjectMemoryRecord(
        project="demo",
        node=NodeName.THALAMUS,
        sleep_id="sleep-x",
        task="task-a",
        tick=1,
        ref="task-a:1:thalamus:-:prediction",
        signal="thalamus_citation",
        key="max_admitted",
        matched=True,
        admissible=True,
        consumed_by={"max_admitted": "update-1"},
    )
    return Phases(
        weights=WeightsPhase(updates=(update,)),
        project_memory=ProjectMemoryPhase(
            records=(record,),
            summaries=(
                ProjectMemorySummary(
                    project="demo",
                    node=NodeName.THALAMUS,
                    sleep_id="sleep-x",
                    admissible=1,
                    matched=1,
                    excluded={reason: 0 for reason in config.SLEEP_EXCLUSION_REASONS},
                    updates=1,
                    procedures=1,
                ),
            ),
        ),
        procedures=ProceduresPhase(
            written=(procedure,),
            rejected=(
                RejectedCandidate(
                    procedure_id="habit-0002",
                    tier=Tier.DIRECTOR,
                    when={"goal_digest": "beef"},
                    refs=["r-2"],
                    tasks=["task-a"],
                    reason="its driving pair was ungradeable",
                ),
            ),
            withdrawn=(
                WithdrawnProcedure(
                    procedure_id="habit-0003",
                    path="nodes/cortex/procedures/habit-0003.yaml",
                    failed_hits=3,
                    hits_required=3,
                    reason="three hits graded matched: false",
                ),
            ),
        ),
    )


def test_every_field_of_the_three_producer_groups_round_trips(tmp_path: Path, brain) -> None:
    """Row L9's serialization half: build from P1, P2 and P4 and read every field back."""
    phases = _phases()
    report = SleepReport(
        sleep_id="sleep-x",
        weights=WeightsGroup(updates=list(phases.weights.updates)),
        procedures=ProceduresGroup(
            written=list(phases.procedures.written),
            rejected=list(phases.procedures.rejected),
            withdrawn=list(phases.procedures.withdrawn),
        ),
        project_memory=ProjectMemoryGroup(
            records=list(phases.project_memory.records),
            summaries=list(phases.project_memory.summaries),
        ),
    )
    path = report_module.write_report(report, tmp_path / "reports")
    payload = json.loads(path.read_text(encoding="utf-8"))

    update = payload["weights"]["updates"][0]
    assert set(update) == set(WeightUpdate.model_fields)
    assert update["evidence"]["refs"] == ["task-a:1:anterior_cingulate:-:prediction"]
    assert update["evidence"]["floor_minimum"] == 2
    assert update["seed_hash"] == "f" * 64 and update["was_seeded"] is True

    compiled = payload["procedures"]["written"][0]
    assert set(compiled) == set(Procedure.model_fields)
    assert compiled["seed"] is False
    assert compiled["responses"][0]["when"] == {"goal_digest": "0123456789abcdef"}
    assert payload["procedures"]["rejected"][0]["reason"]
    assert payload["procedures"]["withdrawn"][0]["path"].endswith(".yaml")

    line = payload["project_memory"]["records"][0]
    assert set(line) == set(ProjectMemoryRecord.model_fields)
    assert line["consumed_by"] == {"max_admitted": "update-1"}
    assert payload["project_memory"]["summaries"][0]["kind"] == "summary"

    assert report_module.load_report_file(path) == report


def test_a_compiled_procedure_loads_through_parse_script_unchanged(tmp_path: Path) -> None:
    """P2's own claim: the provenance header is ignored by build 1's loader (row L6's shape).

    The condition is empty here rather than binding `goal_digest`, because the fifth condition
    key is **order W6's** to add to `scripts.py` — this order authors the model and does not
    widen the loader. The second assertion pins that seam, so the day W6 lands the key this
    test says so instead of quietly agreeing.
    """
    from protean.cortex.scripts import CONDITION_KEYS, parse_script

    procedure = Procedure(
        procedure_id="habit-0001",
        name="habit-0001",
        hits_required=3,
        compiled_from=CompiledFrom(sleep_id="sleep-x", source="workload-run-1", refs=["r-1"]),
        responses=[ProcedureResponse(tier=Tier.MANAGER, result={"unit_id": "$unit"})],
    )
    script = parse_script(procedure.script_payload(), name=procedure.procedure_id)
    assert script.name == "habit-0001"
    assert [str(response.tier) for response in script.responses] == ["manager"]
    assert "goal_digest" in CONDITION_KEYS, "order W6 landed the fifth key (D16-8)"


def test_the_dry_run_diff_names_every_thing_it_would_apply() -> None:
    phases = _phases()
    report = SleepReport(
        sleep_id="sleep-x",
        dry_run=True,
        weights=WeightsGroup(updates=list(phases.weights.updates)),
        procedures=ProceduresGroup(
            written=list(phases.procedures.written),
            withdrawn=list(phases.procedures.withdrawn),
        ),
        project_memory=ProjectMemoryGroup(
            records=list(phases.project_memory.records)
        ),
    )
    lines = "\n".join(report_module.diff_lines(report))
    assert "anterior_cingulate/rut_ticks" in lines
    assert "habit-0001" in lines and "habit-0003" in lines
    assert "project 'demo'" in lines


# --------------------------------------------------------------------------------------
# Row L9's last clause — every number derived, none hardcoded
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("module", "allowed"),
    [
        # `2` is `REPORT_INDENT`, the JSON layout; `0` and `1` are counter seeds and indices.
        (report_module, {0, 1, 2}),
        # `12` is the digest width a refusal message prints; `0` is an index.
        (run_module, {0, 12}),
        # every default is a zero or the empty ratio; `1` is `-1`'s operand in the version
        # refusal, and `12` is the digest width `landed_under()` prints.
        (state_sleep_module, {0, 0.0, 1, 12}),
    ],
)
def test_the_sleep_modules_hardcode_no_number(module, allowed) -> None:
    """Row L9: "every number derived … none hardcoded".

    Every threshold, every k and every count comes from `config`, from the trace, or from a
    caller — so the only literals a sleep module may carry are the ones named beside it above.
    A new number here fails this rather than riding into a report.
    """
    found = {value for _line, value in numeric_literals(Path(module.__file__))}
    assert found <= allowed, f"{module.__name__} carries {sorted(found - allowed)}"
