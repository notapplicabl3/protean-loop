"""Rows L6, L8's procedure clause and N4's sleep half: habits compiled, refused and withdrawn.

`the build specification (not in this mirror)` § Deliverable 4, § Directional decisions 13 and 21,
§ Build process leg 5 and its "Legs 1 and 5" paragraph, § Named assumptions 9, § Resolutions
A1-2, A1-9, S-3, S-4, and § DoD rows L6, L8 and N4.

**The archived run is an arm, not a backdrop.** § Build process's legs 1 and 5 are the same
argument from both ends: run 1's three-tick `u-branch` repeat is the most repetitive pattern the
data offers and it must not compile, *because* leg 1 classified its driving predicates
ungradeable. So the real archive is read here, the three ticks' three distinct
`InputSignature.digest`s are asserted beside their one identical condition set, and the compiler
is driven over it — the read is byte-for-byte read-only, and every write target is a `tmp_path`.

**Nothing here writes into the repo's own `brain/`** (`tests/sleep/test_weights.py`'s reason):
every run copies the tracked seed tree into `tmp_path` first, so a compiled habit never lands in
the tracked `brain/nodes/cortex/procedures/` folder that row N6 watches.

**Every compiled file is read back through `parse_script()` unmodified**, which is row L6's whole
claim: a procedure is a `SeatScript` and nothing more exotic, and the provenance header is
something build 1's loader ignores rather than something build 3 taught it to skip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from protean import config
from protean.cortex.scripts import CONDITION_KEYS, goal_digest_of, parse_script
from protean.runtime import paths as paths_module
from protean.runtime.seat import decode_seat_result
from protean.sleep.habits import (
    PROCEDURE_CONSUMPTION_KEY,
    Candidate,
    WindowHit,
    candidates,
    compile_habits,
    gate,
    goal_texts,
    procedure_consumption_map,
    procedure_id_for,
    read_habit_hits,
    seat_outputs,
    tier_of_ref,
)
from protean.sleep.run import PhaseInput
from protean.state.enums import CallType, Tier
from protean.state.records import TraceRecord
from protean.state.sleep import Procedure, ProcedureResponse
from tests.sleep import outcome, prediction, tree_hashes, unit, write_run
from tests.sleep.conftest import (
    GOAL_ID,
    GOAL_TEXT,
    UNIT_ID,
    earlier_memory_line,
    habit_run,
    patch_goal_stack,
    planner_pair,
)
from tests.sleep.conftest import phase_input as shared_phase_input

ARCHIVE = "brain/archive/workload-run-20260907T153455290946"

#: Run 1's two deleted tier names, read forward onto build A.1's addressees **in memory only**.
#: The archive itself is never rewritten (§ Out of scope: "Migrating any checkpoint or
#: artifact"); this is a test reading an old line for a claim that is not about the name.
_FORWARD = {"planner": "manager", "executor": "dispatch"}


def _forward(payload: dict) -> dict:
    """One archived trace line, with its tier read forward. Never written back."""
    moved = dict(payload)
    if moved.get("tier") in _FORWARD:
        moved["tier"] = _FORWARD[moved["tier"]]
    signature = moved.get("input_signature")
    if isinstance(signature, dict) and signature.get("tier") in _FORWARD:
        moved["input_signature"] = {**signature, "tier": _FORWARD[signature["tier"]]}
    signals = {"executor_expectations": "dispatch_expectations", "planner_horizon": "manager_horizon"}
    for slot in ("prediction", "outcome"):
        payload_slot = moved.get(slot)
        if isinstance(payload_slot, dict) and payload_slot.get("signal") in signals:
            moved[slot] = {**payload_slot, "signal": signals[payload_slot["signal"]]}
    return moved
SLEEP_ID = "sleep-20260908-000000Z"
EARLIER_SLEEP_ID = "sleep-20260907-000000Z"
CURRENT = "task-fixture"
EARLIER = "task-earlier"


# --------------------------------------------------------------------------------------
# Builders — a run whose planner answered the same goal twice
# --------------------------------------------------------------------------------------


def phase_input(brain, directory: Path, *, dry_run: bool = False) -> PhaseInput:
    """What `protean.sleep.run` hands the procedures phase, assembled the way it assembles it.

    `seed_hashes` is empty rather than verified: the procedures phase reads none of them, and a
    fixture run over the real archive is taken under seeds this checkout's tree no longer holds.
    That is the shared builder's `verify=False`, named once here so every call below reads the
    same as the other modules' calls do.
    """
    return shared_phase_input(brain, directory, dry_run=dry_run, verify=False)


def written_files(brain) -> list[Path]:
    node = brain.node_procedures(config.CORTEX_NODE)
    return sorted(node.glob("*.yaml")) if node.is_dir() else []


# --------------------------------------------------------------------------------------
# Row L6, the archive's half — the bad habit does not compile, and why it does not
# --------------------------------------------------------------------------------------


def test_the_archived_repeat_carries_three_digests_over_one_condition_set(
    repo_root: Path,
) -> None:
    """The reason a procedure is not keyed on the request: the digests differ, the keys do not.

    **Re-based by build A.1**: run 1's trace lines name `planner` and `executor`, two tiers A.1
    deletes, and the build ships **no migration path** — an old artifact is refused by name, not
    converted (§ Out of scope). The claim is about a repeat *shape*, not about those two names,
    so the lines are read forward onto A.1's addressees at the boundary and the shape is asserted
    on the result. Nothing is written back: the archive stays byte-identical (the test below).
    """
    trace = repo_root / ARCHIVE / "nodes" / "cortex" / "trace.jsonl"
    records = [
        TraceRecord.model_validate(_forward(json.loads(line)))
        for line in trace.read_text(encoding="utf-8").splitlines()
        if line
    ]
    repeat = [
        record
        for record in records
        if record.prediction is not None
        and getattr(record.prediction, "unit_id", None) == "u-branch"
        and record.tier is CallType.DISPATCH
    ]
    assert [record.tick for record in repeat] == [2, 3, 4]

    digests = {record.input_signature.digest for record in repeat}
    assert len(digests) == 3, "three ticks, three distinct InputSignature.digests"

    conditions = {
        (
            record.prediction.unit_id,
            tuple(record.prediction.expectation_ids),
            str(record.tier),
        )
        for record in repeat
    }
    assert len(conditions) == 1, "one byte-identical condition set across all three"


def test_the_archived_run_is_refused_by_name_rather_than_compiled_from(
    tmp_path: Path, brain, repo_root: Path
) -> None:
    """**Re-based by build A.1**: run 1's archive is a pre-A.1 artifact and the loader refuses it.

    Six schema versions moved 1 → 2 together and A.1 ships no migration path, so the compiler
    cannot read a run written under the old ones. Build 3's claim — that the three-tick
    `u-branch` repeat does **not** compile, because leg 1 graded every driving pair
    `ungradeable` or `unjoined` — is unchanged as a fact about that run and re-opens against a
    post-A.1 one, which build 3's own wet sequence owes. What A.1 owes is the refusal, and that
    the refusal is by **name** rather than a raw `ValidationError`.
    """
    from protean.state.errors import SchemaVersionMismatch

    with pytest.raises(SchemaVersionMismatch) as raised:
        compile_habits(phase_input(brain, repo_root / ARCHIVE))
    print(f"    [A.1] archive refusal: {raised.value}")
    assert "schema_version 1 on disk" in str(raised.value)
    assert written_files(brain) == [], "and nothing was written on the refusal path"


def _archive_goal_text(repo_root: Path) -> str:
    payload = json.loads(
        (repo_root / ARCHIVE / "state" / "checkpoint.json").read_text(encoding="utf-8")
    )
    return payload["state"]["goals"][0]["text"]


def test_the_compiler_names_no_input_signature_anywhere(repo_root: Path) -> None:
    """Row L6's negative half, as a property of the source rather than of a comment.

    The row's own check is a grep for `InputSignature` over this module with no hit, so the
    docstring names the fact it refuses in prose and never in the spelling the grep reads.
    """
    source = (repo_root / "src" / "protean" / "sleep" / "habits.py").read_text(
        encoding="utf-8"
    )
    assert "InputSignature" not in source
    assert "input_signature" not in source


def test_the_archive_is_byte_identical_after_a_compile_run(
    tmp_path: Path, brain, repo_root: Path
) -> None:
    """Row N8's clause for this order: sleep reads a run without touching it.

    Also carries row N8 for the evidence module: absorbs
    `tests/sleep/test_evidence.py::test_the_archive_is_read_and_never_written` (row S9),
    whose `SchemaVersionMismatch` and hash-equality claims are the two below — `compile_habits`
    goes through `load_archived_run` + `admissible_set` — and whose `len(before) >= 18` floor
    (folded: D3-5) lives on
    `tests/sleep/test_battery.py::test_the_archive_is_byte_identical_across_the_whole_battery`.
    """
    from protean.state.errors import SchemaVersionMismatch

    archive = repo_root / ARCHIVE
    before = tree_hashes(archive)
    # The read now refuses (build A.1's schema bump). The claim this row makes holds either
    # way, and on the refusal path as much as on the success path: nothing under the archive is
    # written.
    with pytest.raises(SchemaVersionMismatch):
        compile_habits(phase_input(brain, repo_root / ARCHIVE))
    assert tree_hashes(archive) == before


# --------------------------------------------------------------------------------------
# Row L6, the positive half — what a compiled procedure is
# --------------------------------------------------------------------------------------


def test_a_compiled_habit_is_a_seat_script_parse_script_loads_unmodified(
    tmp_path: Path, brain
) -> None:
    """Row L6 whole: the file loads, its keys are `CONDITION_KEYS`, it binds `goal_digest`."""
    earlier_memory_line(brain)
    directory = habit_run(tmp_path, brain, name="run")
    phase = compile_habits(phase_input(brain, directory))

    assert len(phase.written) == 1, "the planner's answer on the repeated goal"
    procedure = phase.written[0]
    assert procedure.procedure_id == procedure_id_for("manager", goal_digest_of(GOAL_TEXT))
    assert procedure.seed is False and procedure.hits_required == 3
    assert procedure.compiled_from.sleep_id == SLEEP_ID
    assert set(procedure.compiled_from.tasks) == {EARLIER, CURRENT}
    assert len(procedure.compiled_from.refs) == 3

    written = written_files(brain)
    assert [path.name for path in written] == [f"{procedure.procedure_id}.yaml"]

    payload = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    script = parse_script(payload, name=written[0].stem)
    assert script.name == procedure.procedure_id
    assert [str(response.tier) for response in script.responses] == ["manager"]

    condition = payload["responses"][0]["when"]
    assert set(condition) <= set(CONDITION_KEYS)
    assert condition == {"goal_digest": goal_digest_of(GOAL_TEXT)}
    assert "unit_id" not in condition, "the planner mints one per task; it never recurs"
    assert payload["seed"] is False and payload["schema_version"]


def test_a_compiled_habit_answers_the_one_decode_seat_result_path_and_only_its_own_goal(
    tmp_path: Path, brain
) -> None:
    """Row L6, both directions on one compiled script.

    Positive: a `SeatEnvelope` through the unchanged port — a habit is not a second decode path.
    Negative: the same object refuses a workspace whose goal it was not compiled from. One
    compile answers both, because the claim is about one script rather than about two.
    """
    from protean.cortex.adapters import build_envelope
    from protean.cortex.scripts import SeatScriptError

    from protean.state.primitives import GoalItem
    from protean.state.workspace import ManagerRequest, Workspace

    earlier_memory_line(brain)
    directory = habit_run(tmp_path, brain, name="run")
    compile_habits(phase_input(brain, directory))

    script = parse_script(
        yaml.safe_load(written_files(brain)[0].read_text(encoding="utf-8")), name="habit"
    )
    workspace = Workspace(
        task_id="task-later",
        tick=7,
        goals=[
            GoalItem(
                id="task-later-g9",
                text=GOAL_TEXT,
                status="open",
                opened_at_tick=0,
                last_progress_tick=0,
            )
        ],
    )
    request = ManagerRequest(workspace=workspace, escalation="empty_unit_stack")

    result = script.respond(Tier.MANAGER, request)
    decoded = decode_seat_result(Tier.MANAGER, build_envelope(Tier.MANAGER, result, session_id="s"))
    assert decoded.emitter == "manager"
    assert decoded.tick == 7, "the tick is stamped from the request, never from the file"
    assert [row.goal_id for row in decoded.units] == ["task-later-g9"], (
        "$goal resolved to the NEW task's goal id — a habit compiled in one task fires in another"
    )

    other = Workspace(
        task_id="task-other",
        tick=1,
        goals=[
            GoalItem(
                id="g",
                text="a different goal entirely",
                status="open",
                opened_at_tick=0,
                last_progress_tick=0,
            )
        ],
    )
    with pytest.raises(SeatScriptError, match="no manager response matching"):
        script.respond(Tier.MANAGER, ManagerRequest(workspace=other, escalation="empty_unit_stack"))


# --------------------------------------------------------------------------------------
# The three gates
# --------------------------------------------------------------------------------------


def test_a_candidate_short_of_the_floor_is_reported_rather_than_compiled(
    tmp_path: Path, brain
) -> None:
    """One task can never clear a two-task floor (§ Named assumptions 3 and 7)."""
    directory = habit_run(tmp_path, brain, name="run")
    phase = compile_habits(phase_input(brain, directory))

    assert phase.written == () and written_files(brain) == []
    assert len(phase.rejected) == 1
    assert "short of the persistence floor" in phase.rejected[0].reason
    assert "2 admissible pair(s) across 1 task(s)" in phase.rejected[0].reason


def test_a_window_holding_one_failure_compiles_nothing(tmp_path: Path, brain) -> None:
    """"its outcome **matched**" — a habit compiles only from a window that never failed."""
    earlier_memory_line(brain)
    directory = write_run(
        tmp_path / "run",
        brain=brain,
        records=[
            record
            for pair in (
                planner_pair(tick=1, matched=True),
                planner_pair(tick=3, matched=False),
            )
            for record in pair
        ],
        task=CURRENT,
        tick=4,
        units=[unit(UNIT_ID, goal_id=GOAL_ID)],
    )
    patch_goal_stack(directory / "state", goal_id=GOAL_ID, text=GOAL_TEXT)

    phase = compile_habits(phase_input(brain, directory))
    assert phase.written == ()
    assert "outcome not matched" in phase.rejected[0].reason
    assert "2/3 admissible pair(s) graded matched" in phase.rejected[0].reason


def test_the_executor_tier_is_refused_by_name_even_with_admissible_matched_evidence() -> None:
    """Decision 21, isolated from the archive's own inadmissibility."""
    candidate = Candidate(
        tier="dispatch",
        goal_id="g",
        goal_digest="0" * 16,
        hits=tuple(
            WindowHit(ref=f"t{n}:1:cortex:executor:prediction", task=f"t{n}", project="_root",
                      matched=True, admissible=True)
            for n in range(3)
        ),
    )
    assert "answers no procedure in build 3" in gate(candidate)


def test_a_candidate_with_no_journalled_answer_is_reported_not_compiled(
    tmp_path: Path, brain
) -> None:
    """The run recorded the grade and not the answer, so there is nothing to can."""
    earlier_memory_line(brain)
    directory = habit_run(tmp_path, brain, name="run", journal_ticks=())
    phase = compile_habits(phase_input(brain, directory))

    assert phase.written == ()
    assert "no journalled manager output" in phase.rejected[0].reason


# --------------------------------------------------------------------------------------
# Row L8's procedure clause — the cross-project split
# --------------------------------------------------------------------------------------


def test_single_named_project_evidence_lands_under_that_project_s_memory(
    tmp_path: Path, brain
) -> None:
    """Row L8: one named project, so the habit moves no cross-project prior (folded: S-2)."""
    earlier_memory_line(brain, slug="demo")
    directory = habit_run(tmp_path, brain, name="run", project="demo")
    phase = compile_habits(phase_input(brain, directory))

    assert len(phase.written) == 1
    landed = phase.files[0]
    assert landed.parent == brain.project_procedures("demo")
    assert landed.is_file()
    assert written_files(brain) == [], "and nothing under brain/nodes/"
    assert brain.projects in landed.parents, "gitignored whole (row N6)"


def test_root_slug_evidence_lands_in_the_node_folder(tmp_path: Path, brain) -> None:
    """The other arm of the same fixture pair — run 1's own brain root carries no project."""
    earlier_memory_line(brain)
    directory = habit_run(tmp_path, brain, name="run")
    phase = compile_habits(phase_input(brain, directory))

    assert len(phase.written) == 1
    landed = phase.files[0]
    assert landed.parent == brain.node_procedures(config.CORTEX_NODE)
    assert landed.is_file()
    assert not brain.project_procedures(paths_module.ROOT_PROJECT_SLUG).exists()


# --------------------------------------------------------------------------------------
# `--dry-run`
# --------------------------------------------------------------------------------------


def test_a_dry_run_derives_the_habit_and_writes_no_file(tmp_path: Path, brain) -> None:
    earlier_memory_line(brain)
    directory = habit_run(tmp_path, brain, name="run")
    phase = compile_habits(phase_input(brain, directory, dry_run=True))

    assert len(phase.written) == 1 and len(phase.files) == 1
    assert not phase.files[0].exists()
    assert written_files(brain) == []


# --------------------------------------------------------------------------------------
# Row N4's sleep half — un-learning
# --------------------------------------------------------------------------------------


def install_procedure(brain, *, procedure_id: str, hits_required: int = 3) -> Path:
    """A habit already on the root, as an earlier sleep run left it."""
    procedure = Procedure(
        procedure_id=procedure_id,
        name=procedure_id,
        hits_required=hits_required,
        responses=[
            ProcedureResponse(
                tier=Tier.MANAGER,
                when={"goal_digest": goal_digest_of(GOAL_TEXT)},
                result={"emitter": "manager"},
            )
        ],
    )
    directory = brain.node_procedures(config.CORTEX_NODE)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{procedure_id}.yaml"
    path.write_text(yaml.safe_dump(procedure.script_payload(), sort_keys=False), encoding="utf-8")
    return path


def write_hits(brain, *, procedure_id: str, ticks, task: str = CURRENT) -> None:
    """P3 lines in the shape § Deliverable 4 names, before order W7 writes them (ledger D16-7)."""
    path = brain.task(task).habit_hits
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for tick in ticks:
            handle.write(
                json.dumps(
                    {
                        "schema_version": config.CHECKPOINT_SCHEMA_VERSION,
                        "task": task,
                        "tick": tick,
                        "tier": "manager",
                        "ref": f"{task}:{tick}:cortex:manager:prediction",
                        "procedure_id": procedure_id,
                        "matched_condition": {"goal_digest": goal_digest_of(GOAL_TEXT)},
                        "avoided_model": "claude-opus-5",
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )


def test_a_habit_whose_hits_stop_grading_is_deleted_and_reported(
    tmp_path: Path, brain
) -> None:
    """Row N4's sleep half: the file goes, and the deletion is a line in the report."""
    habit = install_procedure(brain, procedure_id="habit-manager-deadbeefdeadbeef")
    write_hits(brain, procedure_id="habit-manager-deadbeefdeadbeef", ticks=(1, 3, 5))

    directory = habit_run(tmp_path, brain, name="run", ticks=(1, 3, 5), matched=False)
    phase = compile_habits(phase_input(brain, directory))

    assert not habit.exists(), "deleted, so it shows in the git diff"
    assert [row.procedure_id for row in phase.withdrawn] == [
        "habit-manager-deadbeefdeadbeef"
    ]
    withdrawn = phase.withdrawn[0]
    assert withdrawn.failed_hits == 3 and withdrawn.hits_required == 3
    assert withdrawn.path == "nodes/cortex/procedures/habit-manager-deadbeefdeadbeef.yaml"
    assert "falls back to a live call" in withdrawn.reason
    assert phase.deleted == (habit,)


def test_a_habit_short_of_k_failed_hits_survives(tmp_path: Path, brain) -> None:
    """the operator's over-firing constraint on the un-learner too: two failures are not three."""
    habit = install_procedure(brain, procedure_id="habit-manager-deadbeefdeadbeef")
    write_hits(brain, procedure_id="habit-manager-deadbeefdeadbeef", ticks=(1, 3))

    directory = habit_run(tmp_path, brain, name="run", ticks=(1, 3), matched=False)
    phase = compile_habits(phase_input(brain, directory))

    assert habit.exists() and phase.withdrawn == () and phase.deleted == ()


def test_one_later_success_clears_the_consecutive_count(tmp_path: Path, brain) -> None:
    """`failed_hits` is the trailing run: a habit that started working again is not retired."""
    habit = install_procedure(brain, procedure_id="habit-manager-deadbeefdeadbeef")
    write_hits(brain, procedure_id="habit-manager-deadbeefdeadbeef", ticks=(1, 3, 5, 7))

    pairs = [
        planner_pair(tick=tick, matched=(tick == 7)) for tick in (1, 3, 5, 7)
    ]
    directory = write_run(
        tmp_path / "run",
        brain=brain,
        records=[record for pair in pairs for record in pair],
        task=CURRENT,
        tick=8,
        units=[unit(UNIT_ID, goal_id=GOAL_ID)],
    )
    phase = compile_habits(phase_input(brain, directory))

    assert habit.exists() and phase.withdrawn == ()


def test_a_dry_run_reports_the_withdrawal_and_deletes_nothing(
    tmp_path: Path, brain
) -> None:
    habit = install_procedure(brain, procedure_id="habit-manager-deadbeefdeadbeef")
    write_hits(brain, procedure_id="habit-manager-deadbeefdeadbeef", ticks=(1, 3, 5))

    directory = habit_run(tmp_path, brain, name="run", ticks=(1, 3, 5), matched=False)
    phase = compile_habits(phase_input(brain, directory, dry_run=True))

    assert habit.exists()
    assert [row.procedure_id for row in phase.withdrawn] == [
        "habit-manager-deadbeefdeadbeef"
    ]


def test_the_hit_reader_skips_a_line_it_cannot_join_rather_than_refusing(brain) -> None:
    """Order W7 has not fixed P3's shape; a reader that raised would fail the whole run."""
    path = brain.task(CURRENT).habit_hits
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"procedure_id": "h", "task": CURRENT, "tick": 1, "ref": "r-1"},
                {"procedure_id": "h", "task": CURRENT, "ref": "r-2"},
                {"task": CURRENT, "tick": 3, "ref": "r-3"},
                {"procedure_id": "h", "task": CURRENT, "tick": 4, "ref": "r-4",
                 "schema_version": 99, "tier": "manager", "matched_condition": {},
                 "avoided_model": "m"},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    hits = read_habit_hits(brain)
    assert [hit.ref for hit in hits] == ["r-1", "r-4"], "a later schema_version is not refused"


# --------------------------------------------------------------------------------------
# The seams this order hands on
# --------------------------------------------------------------------------------------


def test_the_tier_of_a_memory_line_is_read_out_of_its_ref(tmp_path: Path, brain) -> None:
    """P4 carries no tier, and `prediction_key()` is `task:tick:node:tier:prediction`."""
    assert tier_of_ref("task-a:3:cortex:manager:prediction") == "manager"
    assert tier_of_ref("task-a:3:thalamus:-:prediction") == "-"
    assert tier_of_ref("nonsense") == ""


def test_a_compiled_habit_declares_the_pairs_it_consumed(tmp_path: Path, brain) -> None:
    """S-17's procedure half, produced here and persisted by order W5 (ledger `D16-6`)."""
    earlier_memory_line(brain)
    directory = habit_run(tmp_path, brain, name="run")
    phase = compile_habits(phase_input(brain, directory))

    consumed = procedure_consumption_map(phase.written, SLEEP_ID)
    procedure_id = phase.written[0].procedure_id
    assert set(consumed) == set(phase.written[0].compiled_from.refs)
    for entry in consumed.values():
        assert entry == {PROCEDURE_CONSUMPTION_KEY: f"{SLEEP_ID}:cortex/{procedure_id}"}


def test_the_goal_text_is_read_off_the_committed_stack_and_the_journal_off_the_run(
    tmp_path: Path, brain
) -> None:
    """The two things `RunRecords` does not carry, and where each is read from."""
    directory = habit_run(tmp_path, brain, name="run")
    argument = phase_input(brain, directory)

    assert goal_texts(brain, argument.records) == {GOAL_ID: GOAL_TEXT}
    outputs = seat_outputs(brain, argument.records)
    assert set(outputs) == {(1, "manager"), (3, "manager")}
    assert outputs[(3, "manager")]["units"][0]["goal_id"] == GOAL_ID


def test_a_candidate_groups_this_run_s_pairs_with_the_project_s_memory(
    tmp_path: Path, brain
) -> None:
    earlier_memory_line(brain)
    directory = habit_run(tmp_path, brain, name="run")
    found = candidates(phase_input(brain, directory))

    assert len(found) == 1
    candidate = found[0]
    assert candidate.tier == "manager" and candidate.goal_id == GOAL_ID
    assert candidate.goal_digest == goal_digest_of(GOAL_TEXT)
    assert len(candidate.admissible) == 3 and len(candidate.tasks) == 2
    assert candidate.match_rate == 1.0
    assert candidate.ticks() == (1, 3)
