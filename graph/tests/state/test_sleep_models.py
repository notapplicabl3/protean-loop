"""P1, P2, P4 and P5 carry the fields their SPEC tables name, and refuse a version mismatch.

`the build specification (not in this mirror)` § Deliverable 3 (P1's field table), § Deliverable 4 (P2's
provenance header), § Deliverable 5 (P4's line), § Deliverable 2 (P5's five groups), § Scaffold
clause (the five seam contracts this build introduces).

**The field lists below are transcribed from the SPEC, not read off the models.** That is the
point of the module: `src/protean/state/sleep.py` is read-only to orders W3–W10, and a producer
that finds a field missing writes a `BLOCKED` entry rather than widening a seam — so the shape
has to be pinned where a widening would fail rather than pass.

It lives under `tests/state/` beside the model it pins, which is where every other contract's
conformance test lives.
"""

from __future__ import annotations

import pytest

from protean import config
from protean.state.enums import NodeName, Tier
from protean.state.errors import SchemaVersionMismatch
from protean.state.sleep import (
    CompiledFrom,
    Procedure,
    ProcedureResponse,
    ProjectMemoryRecord,
    ProjectMemorySummary,
    SleepReport,
    UpdateEvidence,
    WeightUpdate,
    load_procedure,
    load_project_memory,
    load_sleep_report,
    load_weight_update,
)

#: § Deliverable 3's P1 table, transcribed row for row.
P1_FIELDS = {
    "schema_version",
    "node",
    "key",
    "from_value",
    "to_value",
    "direction",
    "signal",
    "evidence",
    "applied",
    "withheld_reason",
    "seed_hash",
    "was_seeded",
}

#: § Deliverable 4's P2 sentence: a `SeatScript` (`name`, `responses`) plus the five-field
#: provenance header the loader ignores.
P2_FIELDS = {
    "schema_version",
    "procedure_id",
    "name",
    "seed",
    "hits_required",
    "compiled_from",
    "responses",
}

#: § Deliverable 5's P4 line, transcribed (folded: S-9, folded: S-17).
P4_FIELDS = {
    "schema_version",
    "project",
    "node",
    "sleep_id",
    "task",
    "tick",
    "ref",
    "signal",
    "key",
    "matched",
    "admissible",
    "excluded_reason",
    "consumed_by",
}

#: § Deliverable 2's group table, plus the report's own three facts.
P5_GROUPS = {"source", "evidence", "weights", "procedures", "project_memory"}


def _update() -> WeightUpdate:
    return WeightUpdate(
        node=NodeName.CORTEX,
        key="manager_horizon",
        from_value=2,
        to_value=3,
        direction="tighten",
        signal="manager_horizon",
        evidence=UpdateEvidence(refs=["r-1"], tasks=["t-1"], pairs=1),
    )


def _procedure() -> Procedure:
    return Procedure(
        procedure_id="habit-1",
        compiled_from=CompiledFrom(sleep_id="s-1"),
        responses=[ProcedureResponse(tier=Tier.MANAGER)],
    )


def _record() -> ProjectMemoryRecord:
    return ProjectMemoryRecord(
        project="demo",
        node=NodeName.THALAMUS,
        sleep_id="s-1",
        task="t-1",
        tick=1,
        ref="t-1:1:thalamus:-:prediction",
        signal="thalamus_citation",
    )


# --------------------------------------------------------------------------------------
# The four field tables
# --------------------------------------------------------------------------------------


def test_p1_carries_every_field_deliverable_3_names() -> None:
    assert set(WeightUpdate.model_fields) == P1_FIELDS


def test_p2_carries_every_field_deliverable_4_names() -> None:
    assert set(Procedure.model_fields) == P2_FIELDS


def test_p4_carries_every_field_deliverable_5_names() -> None:
    assert set(ProjectMemoryRecord.model_fields) == P4_FIELDS


def test_p5_carries_five_groups_and_no_comparison_group() -> None:
    """folded: S-13 — the two-run numbers are the wet script's, never a seam field."""
    assert P5_GROUPS <= set(SleepReport.model_fields)
    assert "comparison" not in SleepReport.model_fields


def test_p1s_evidence_carries_the_floor_arithmetic() -> None:
    """§ Deliverable 2's `weights` group: "with the floor arithmetic that decided it"."""
    assert {
        "refs",
        "tasks",
        "projects",
        "pairs",
        "matched",
        "match_rate",
        "required_pairs",
        "required_tasks",
        "confirmations",
        "every_task_done",
        "floor_minimum",
    } == set(UpdateEvidence.model_fields)


def test_p4_gains_a_summary_line_per_run() -> None:
    """§ Deliverable 5: "plus one summary line per sleep run"."""
    assert {"admissible", "matched", "excluded", "updates", "procedures"} <= set(
        ProjectMemorySummary.model_fields
    )


# --------------------------------------------------------------------------------------
# Their contracts
# --------------------------------------------------------------------------------------


def test_a_compiled_procedure_is_never_a_seed() -> None:
    """`seed: false` is `Literal[False]`: a seeded procedure cannot be constructed."""
    with pytest.raises(ValueError):
        Procedure(
            procedure_id="habit-1",
            seed=True,
            compiled_from=CompiledFrom(),
            responses=[],
        )


def test_every_model_forbids_an_unknown_field() -> None:
    """Build 1's rule: `extra="forbid"` everywhere but `SeatEnvelope`."""
    for model, sample in (
        (WeightUpdate, _update()),
        (Procedure, _procedure()),
        (ProjectMemoryRecord, _record()),
    ):
        payload = sample.model_dump(mode="json") | {"injected": 1}
        with pytest.raises(ValueError):
            model.model_validate(payload)


def test_a_pair_line_and_a_summary_line_share_one_file_and_stay_apart() -> None:
    record = _record()
    summary = ProjectMemorySummary(
        project="demo", node=NodeName.THALAMUS, sleep_id="s-1"
    )
    assert isinstance(load_project_memory(record.model_dump(mode="json")), ProjectMemoryRecord)
    assert isinstance(
        load_project_memory(summary.model_dump(mode="json")), ProjectMemorySummary
    )


def test_the_dedupe_key_keeps_two_runs_readings_of_one_pair_apart() -> None:
    first = _record()
    second = first.model_copy(update={"sleep_id": "s-2"})
    assert first.dedupe_key() != second.dedupe_key()
    assert first.dedupe_key() == first.model_copy().dedupe_key()


@pytest.mark.parametrize(
    ("loader", "sample", "artifact"),
    [
        (load_weight_update, _update(), "weight_update"),
        (load_procedure, _procedure(), "procedure"),
        (load_project_memory, _record(), "project_memory"),
        (load_sleep_report, SleepReport(sleep_id="s-1"), "sleep_report"),
    ],
)
def test_every_loader_refuses_a_schema_version_it_does_not_write(
    loader, sample, artifact
) -> None:
    payload = sample.model_dump(mode="json")
    assert loader(payload) == sample
    payload["schema_version"] = payload["schema_version"] + 1
    with pytest.raises(SchemaVersionMismatch) as raised:
        loader(payload)
    assert artifact in str(raised.value)


def test_the_five_new_schema_versions_are_in_the_build_3_table() -> None:
    assert sorted(config.BUILD3_ARTIFACT_SCHEMA_VERSIONS) == [
        "habit_hit",
        "procedure",
        "project_memory",
        "sleep_report",
        "weight_update",
    ]
    assert set(config.BUILD3_ARTIFACT_SCHEMA_VERSIONS).isdisjoint(
        set(config.ARTIFACT_SCHEMA_VERSIONS) | set(config.BUILD2_ARTIFACT_SCHEMA_VERSIONS)
    )


def test_the_sleep_models_are_not_on_the_state_roster() -> None:
    """folded: D8-2 — the roster is build 1's inter-node contract set; none of these is one."""
    import protean.state as state

    assert "WeightUpdate" not in state.__all__
    assert "SleepReport" not in state.__all__
