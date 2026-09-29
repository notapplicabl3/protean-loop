"""Rows L3 and L2 and builder row N2: the two refusals, the verification, and `--dry-run`.

`the build specification (not in this mirror)` § Deliverable 2 (the refusals, the verification rule, the
write set, `--dry-run`), § Directional decisions 16 and 17, § Resolutions A1-10, A1-11, S-11,
and § DoD rows L3, L2 (clauses 1–2) and N2.

**Row N2 is the builder's own list, not a gate** (`the work orders (not in this mirror)` § W2
Process step 10): it closes nothing. The verb's surface is asserted here anyway, because the
claim — no integer at the call site, one line per file written — is one a test can hold.

**Every wet-shaped case runs against a temp copy of the tracked seed tree.** The repo's own
brain root is what refusal 2 is *about* on this checkout, so a test that pointed at it would be
asserting the refusal by accident rather than on purpose.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from protean import cli, config
from protean.runtime.errors import RootOccupied
from protean.sleep.run import SeedHashHeld, SeedMoved, run_sleep, writable_seed_keys
from protean.state.enums import NodeName
from protean.state.records import ThalamusOutcome, ThalamusPrediction
from tests.sleep import occupy, outcome, prediction, tree_hashes, write_run
from tests.sleep.conftest import numeric_literals


@pytest.fixture()
def run_dir(tmp_path: Path, brain) -> Path:
    """One archived run whose single pair is admissible, so nothing else can fail a case."""
    predicted = prediction(
        node=NodeName.THALAMUS, payload=ThalamusPrediction(admitted_ids=["admitted:e-1"])
    )
    return write_run(
        tmp_path / "run",
        brain=brain,
        records=[
            predicted,
            outcome(
                predicted, ThalamusOutcome(cited_admitted_ids=["admitted:e-1"], matched=True)
            ),
        ],
    )


def _sleep(brain, run_dir: Path, tmp_path: Path, **kwargs):
    return run_sleep(brain, source=run_dir, report_dir=tmp_path / "reports", **kwargs)


# --------------------------------------------------------------------------------------
# Row L3 — refusal 1: a task in flight
# --------------------------------------------------------------------------------------


def test_a_committed_terminal_of_none_refuses_before_anything_is_read(
    brain, run_dir, tmp_path
) -> None:
    task_id = occupy(brain, terminal=None)
    before = tree_hashes(brain.root)
    with pytest.raises(RootOccupied) as raised:
        _sleep(brain, run_dir, tmp_path)
    assert task_id in str(raised.value)
    assert tree_hashes(brain.root) == before
    assert not (tmp_path / "reports").exists(), "a refused sleep writes no report either"


def test_a_live_lock_refuses_even_with_no_task_on_the_root(brain, run_dir, tmp_path) -> None:
    """The other arm of refusal 1: the instance lock held by a live pid."""
    import os

    brain.lock.parent.mkdir(parents=True, exist_ok=True)
    brain.lock.write_text(
        json.dumps({"pid": os.getpid(), "task_id": "task-live", "started_at": "now"}),
        encoding="utf-8",
    )
    with pytest.raises(RootOccupied) as raised:
        _sleep(brain, run_dir, tmp_path)
    assert "task-live" in str(raised.value)


def test_a_dead_lock_does_not_refuse(brain, run_dir, tmp_path) -> None:
    """A stale lock is not a task in flight — build 1 reclaims it and sleep reads past it."""
    brain.lock.parent.mkdir(parents=True, exist_ok=True)
    brain.lock.write_text(
        json.dumps({"pid": -1, "task_id": "task-dead", "started_at": "then"}),
        encoding="utf-8",
    )
    assert _sleep(brain, run_dir, tmp_path).report.evidence.admissible == 1


def test_refusal_one_is_narrower_than_intakes_arm(brain, run_dir, tmp_path) -> None:
    """folded: S-11 — a committed `interrupted` task is refusal 2's to own, not refusal 1's."""
    occupy(brain, terminal="interrupted", seeds={})
    assert _sleep(brain, run_dir, tmp_path).report.evidence.admissible == 1


# --------------------------------------------------------------------------------------
# Row L3 — refusal 2: a committed, not-`done` task holding a seed this run would write
# --------------------------------------------------------------------------------------


def test_a_committed_not_done_task_holding_a_weights_hash_is_refused(
    brain, run_dir, tmp_path
) -> None:
    task_id = occupy(brain, terminal="interrupted")
    before = tree_hashes(brain.root)
    with pytest.raises(SeedHashHeld) as raised:
        _sleep(brain, run_dir, tmp_path)
    message = str(raised.value)
    assert task_id in message and "interrupted" in message
    for node in config.WEIGHTS_WRITABLE_NODES:
        assert f"nodes/{node}/weights.yaml" in message
    assert tree_hashes(brain.root) == before
    assert not (tmp_path / "reports").exists()


def test_a_done_task_does_not_hold_the_root(brain, run_dir, tmp_path) -> None:
    occupy(brain, terminal="done")
    assert _sleep(brain, run_dir, tmp_path).report.evidence.admissible == 1


def test_the_gates_weights_file_is_not_a_file_this_run_would_write() -> None:
    """§ Deliverable 3: five node folders are writable and one is not."""
    keys = writable_seed_keys(
        {f"nodes/{node}/weights.yaml": "x" for node in config.NODE_ORDER}
    )
    assert "nodes/basal_ganglia/weights.yaml" not in keys
    assert len(keys) == len(config.WEIGHTS_WRITABLE_NODES) == 5


def _sleep_parser():
    """The `sleep` sub-parser, off the built parser. argparse exposes no public accessor."""
    parser = cli.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    return subparsers.choices["sleep"]


def test_no_flag_overrides_either_refusal() -> None:
    """`--force` does not override them, and the strongest form of that is having no `--force`.

    The exact flag set carries two more citations, folded here when
    `test_the_verb_carries_no_project_and_no_limit_flag` was removed as redundant (row S7):
    folded: S-12 (the slug is the task's own) and folded: S-6 (`--limit` dropped) — set
    equality implies neither `--project` nor `--limit` is a flag on this verb.
    """
    flags = {
        option for action in _sleep_parser()._actions for option in action.option_strings
    }
    assert flags == {"-h", "--help", "--from", "--dry-run"}


# --------------------------------------------------------------------------------------
# Row L2 — verify before you grade
# --------------------------------------------------------------------------------------


def test_a_deleted_seed_refuses_by_name_rather_than_raising(brain, run_dir, tmp_path) -> None:
    brain.node_weights("cortex").unlink()
    with pytest.raises(SeedMoved) as raised:
        _sleep(brain, run_dir, tmp_path)
    assert "nodes/cortex/weights.yaml" in str(raised.value)


def test_the_verified_hashes_land_in_the_reports_source_group(brain, run_dir, tmp_path) -> None:
    from protean.brain.folders import file_sha256

    report = _sleep(brain, run_dir, tmp_path).report
    # Every recorded weights.yaml — the gate's included — never only the writable five (P6-1).
    assert sorted(report.source.seed_hashes) == [
        f"nodes/{node}/weights.yaml" for node in sorted(config.NODE_ORDER)
    ]
    assert "nodes/basal_ganglia/weights.yaml" in report.source.seed_hashes
    for relative, recorded in report.source.seed_hashes.items():
        assert recorded == file_sha256(brain.root / relative)


def test_a_moved_gate_hash_refuses_as_evidence_even_though_sleep_never_writes_it(
    brain, run_dir, tmp_path
) -> None:
    """Row L2's quantifier is the RECORDED set (P6-1): refusal 2 asks what sleep would write,
    verification asks whether the evidence is still the run's."""
    weights = brain.node_weights("basal_ganglia")
    weights.write_text(weights.read_text(encoding="utf-8") + "\n# moved\n", encoding="utf-8")
    with pytest.raises(SeedMoved) as raised:
        _sleep(brain, run_dir, tmp_path)
    assert "nodes/basal_ganglia/weights.yaml" in str(raised.value)


def test_the_source_directory_is_byte_identical_before_and_after(
    brain, run_dir, tmp_path
) -> None:
    """Row L2's first clause, over the run sleep read: read without touching."""
    before = tree_hashes(run_dir)
    _sleep(brain, run_dir, tmp_path)
    assert tree_hashes(run_dir) == before


# --------------------------------------------------------------------------------------
# Row L3 — `--dry-run` writes its report and no file under `brain/`
# --------------------------------------------------------------------------------------


def test_a_dry_run_writes_its_report_and_nothing_under_brain(brain, run_dir, tmp_path) -> None:
    before = tree_hashes(brain.root)
    outcome_ = _sleep(brain, run_dir, tmp_path, dry_run=True)
    assert tree_hashes(brain.root) == before
    assert outcome_.report_path.is_file()
    assert outcome_.report.dry_run is True
    assert outcome_.report.files_written == []
    assert outcome_.writes == ()


def test_a_dry_run_prints_the_diff_it_would_apply(
    brain, run_dir, tmp_path, capsys, monkeypatch
) -> None:
    """Driven through the CLI, whose report directory is `<repo>/reports/sleep/` by default.

    The default is redirected here rather than exercised: `reports/` is the operator's, and a
    collected test that wrote a file into it would grow the repo by one artifact per run.
    """
    monkeypatch.setattr(
        "protean.sleep.run.sleep_report_dir", lambda _root: tmp_path / "reports"
    )
    code = cli.main(
        ["--brain", str(brain.root), "sleep", "--from", str(run_dir), "--dry-run"]
    )
    assert code == config.EXIT_DONE
    printed = capsys.readouterr().out
    assert "dry run: nothing under brain/ is written" in printed
    # every sleep run writes project memory (decision 22), so even a quiet run appends a line
    assert "would append 1 project-memory line(s) under project '_root'" in printed


# --------------------------------------------------------------------------------------
# Row N2 — the verb's surface matches intake's (the builder's own list, closing nothing)
# --------------------------------------------------------------------------------------


def test_help_exits_zero_without_touching_a_brain_root() -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["sleep", "--help"])
    assert raised.value.code == 0


def test_the_verb_is_in_the_config_surface() -> None:
    assert config.SLEEP_VERB in config.VERBS
    assert config.VERBS[-1] == "sleep"


def test_the_refusals_exit_on_their_own_named_codes(brain, run_dir, tmp_path, capsys) -> None:
    occupy(brain, task_id="task-flight", terminal=None)
    code = cli.main(["--brain", str(brain.root), "sleep", "--from", str(run_dir)])
    assert code == config.EXIT_SLEEP_REFUSED == config.EXIT_CODES["sleep_refused"]
    assert "task-flight" in capsys.readouterr().err

    brain.task("task-flight").checkpoint.unlink()
    occupy(brain, task_id="task-held", terminal="interrupted")
    code = cli.main(["--brain", str(brain.root), "sleep", "--from", str(run_dir)])
    assert code == config.EXIT_SLEEP_SEED_REFUSED == config.EXIT_CODES["sleep_seed_refused"]
    assert "task-held" in capsys.readouterr().err


def test_no_integer_exit_code_is_written_at_the_call_site() -> None:
    """N2's own clause: the codes come from `config.EXIT_CODES`, by name.

    `bools=True` keeps the original walk's reach: `isinstance(True, int)` is true, so a `True`
    written at the call site was caught before and is caught still.
    """
    found = numeric_literals(Path(cli.__file__), within="_sleep", bools=True)
    assert found == [], found


def test_the_verb_prints_one_line_per_file_it_wrote_and_nothing_else(
    brain, run_dir, tmp_path, capsys
) -> None:
    outcome_ = _sleep(brain, run_dir, tmp_path)
    for message in outcome_.messages():
        print(message)
    printed = capsys.readouterr().out
    assert printed.count("wrote ") == len(outcome_.files) == 2
    assert f"wrote {outcome_.report_path}" in printed
    assert f"wrote {brain.project_learning('_root', 'thalamus')}" in printed
    assert outcome_.report_path.is_file()
