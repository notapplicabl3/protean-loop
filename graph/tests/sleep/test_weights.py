"""Row L4 and row L2's third clause: the update rule, its five arms, and the floor it clears.

`the build specification (not in this mirror)` § Deliverable 3, § DoD rows L4 and L2 (third clause, decomposed
onto order W3 by ledger entry V2-1), § Resolutions A1-1, S-6, S-7, S-8, S-14, S-16, S-17.

**One fixture per arm of the rule** — applied, withheld by `k`, withheld by the two-task rule,
withheld by the loosening arm (both halves: a confirmed detector, and a window whose tasks did not
all end `done`), and refused for an absent key — each asserted against the *record's own floor
arithmetic* rather than against a bare boolean, because "the tracked half's diff says what changed;
this says why" is the deliverable's own claim.

**The second task is always read out of project memory, never off another task's node traces**
(decision 22). The writer is order W5's, so every memory line below is hand-authored against the
P4 model (ledger entry V2-8) — which is exactly what makes these tests a check of the *reader*.

**Nothing here writes into the repo's own `brain/`.** Every run copies the tracked seed tree into
`tmp_path` first (`tests.sleep.seeded_brain`), because an applied update that reached the repo's
own tree would move the number `tests/state/test_brain_tree.py` pins and falsify the floor this
module exists to prove.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import pytest

from protean import config
from protean.brain.folders import load_weights
from protean.runtime import paths as paths_module
from protean.sleep.run import SeedMoved, run_sleep
from protean.sleep.weights import (
    PERSISTENCE_FLOOR_KEYS,
    PERSISTENCE_FLOOR_MINIMUM,
    REQUIRED_PAIRS_LOOSEN,
    REQUIRED_PAIRS_TIGHTEN,
    REQUIRED_TASKS,
    SIGNAL_KEY_MAP,
    bounded_step,
    clears_the_floor,
    consumption_map,
    declared_weight_keys,
    derive_updates,
    rules_for,
    seeded_keys,
)
from protean.state.enums import NodeName, TrapDetector
from tests.sleep import tree_hashes, write_run
from tests.sleep.conftest import (
    by_key,
    drop_weight_key,
    flatten,
    hippocampus_pair,
    memory_line,
    monitor_journal,
    monitor_pair,
    phase_input,
)

SLEEP_ID = "sleep-20260908-000000Z"
EARLIER = "task-earlier"
CURRENT = "task-fixture"


# --------------------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------------------


def run_of(tmp_path: Path, brain, pairs, *, terminal: str | None = "done", name: str = "run"):
    directory = tmp_path / name
    return write_run(
        directory, brain=brain, records=flatten(pairs), task=CURRENT, tick=4, terminal=terminal
    )


# --------------------------------------------------------------------------------------
# The map itself
# --------------------------------------------------------------------------------------


def test_every_mapped_key_exists_in_the_node_it_names(brain_seed_root: Path) -> None:
    """A map row that named a key no seed file carries would refuse on every run."""
    for rule in SIGNAL_KEY_MAP:
        carried = load_weights(brain_seed_root / "nodes" / rule.node / "weights.yaml")
        assert rule.key in carried, f"{rule.node}.{rule.key} is named by the map"


def test_the_two_signals_that_map_to_no_key_map_to_none() -> None:
    """`dispatch_expectations` drives procedure candidacy; `gate_unit_survives` is the gate's."""
    assert rules_for("dispatch_expectations") == ()
    assert rules_for("gate_unit_survives") == ()
    assert {rule.node for rule in SIGNAL_KEY_MAP} == set(config.WEIGHTS_WRITABLE_NODES)
    assert "basal_ganglia" not in {rule.node for rule in SIGNAL_KEY_MAP}


def test_the_polarity_column_carries_the_three_the_spec_names() -> None:
    """`rut_ticks` lower = loosen · `max_tokens` higher = loosen · `semantic_min_overlap` lower."""
    polarity = {rule.key: rule.polarity for rule in SIGNAL_KEY_MAP}
    assert polarity["rut_ticks"] == -1
    assert polarity["max_tokens"] == +1
    assert polarity["semantic_min_overlap"] == -1
    assert set(polarity.values()) == {-1, +1}


def test_a_bounded_step_is_one_for_an_integer_and_a_tenth_for_a_ratio() -> None:
    assert bounded_step(20, -1, loosening=False) == 21
    assert bounded_step(20, +1, loosening=False) == 19
    assert bounded_step(0.1, -1, loosening=False) == pytest.approx(0.11)
    assert bounded_step(8.0, -1, loosening=True) == pytest.approx(7.2)
    assert isinstance(bounded_step(20, +1, loosening=True), int)


def test_the_floor_is_one_implementation_and_order_w6_calls_it() -> None:
    """`k = 3` across two tasks to tighten; `k = 6` plus the second arm to loosen."""
    assert clears_the_floor(pairs=REQUIRED_PAIRS_TIGHTEN, tasks=REQUIRED_TASKS, loosening=False)
    assert not clears_the_floor(pairs=2, tasks=REQUIRED_TASKS, loosening=False)
    assert not clears_the_floor(pairs=REQUIRED_PAIRS_TIGHTEN, tasks=1, loosening=False)
    assert not clears_the_floor(pairs=REQUIRED_PAIRS_TIGHTEN, tasks=2, loosening=True)
    assert clears_the_floor(pairs=REQUIRED_PAIRS_LOOSEN, tasks=2, loosening=True)
    assert not clears_the_floor(
        pairs=REQUIRED_PAIRS_LOOSEN, tasks=2, loosening=True, confirmations=1
    )
    assert not clears_the_floor(
        pairs=REQUIRED_PAIRS_LOOSEN, tasks=2, loosening=True, every_task_done=False
    )


# --------------------------------------------------------------------------------------
# Arm 1 — applied
# --------------------------------------------------------------------------------------


def test_a_tightening_update_applies_on_three_pairs_across_two_tasks(tmp_path, brain) -> None:
    """The applied arm, with the floor arithmetic that decided it and the file re-valued."""
    directory = run_of(
        tmp_path,
        brain,
        [
            hippocampus_pair(tick=1, matched=True),
            hippocampus_pair(tick=2, matched=False),
        ],
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")

    phase = derive_updates(phase_input(brain, directory))
    rows = by_key(phase.updates)

    assert set(rows) == {"candidate_window", "semantic_window", "semantic_min_overlap"}
    window = rows["candidate_window"]
    assert window.applied and window.withheld_reason == ""
    assert (window.from_value, window.to_value) == (20, 19)
    assert window.direction == "tighten"
    assert window.evidence.pairs == 3 and window.evidence.matched == 2
    assert window.evidence.required_pairs == REQUIRED_PAIRS_TIGHTEN
    assert window.evidence.required_tasks == REQUIRED_TASKS
    assert window.evidence.tasks == sorted([CURRENT, EARLIER])
    assert window.evidence.projects == [paths_module.ROOT_PROJECT_SLUG]

    assert rows["semantic_min_overlap"].to_value == pytest.approx(0.11)
    assert load_weights(brain.node_weights("hippocampus"))["candidate_window"] == 19
    assert phase.files == (brain.node_weights("hippocampus"),)


def test_only_the_re_valued_keys_change_in_a_touched_weights_file(tmp_path, brain) -> None:
    """No key minted, deleted or moved — and every comment the operator wrote is still there."""
    path = brain.node_weights("hippocampus")
    before = path.read_text(encoding="utf-8")
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")
    derive_updates(phase_input(brain, directory))

    after = path.read_text(encoding="utf-8")
    changed = [
        (old, new)
        for old, new in zip(before.splitlines(), after.splitlines(), strict=True)
        if old != new
    ]
    assert [new.split(":")[0] for _, new in changed] == [
        "candidate_window",
        "semantic_window",
        "semantic_min_overlap",
    ]
    assert tuple(load_weights(path)) == tuple(yaml_keys(before))
    assert before.count("#") == after.count("#")


def yaml_keys(text: str) -> tuple[str, ...]:
    import yaml

    return tuple(yaml.safe_load(text) or {})


# --------------------------------------------------------------------------------------
# Arms 2 and 3 — withheld by k, withheld by the two-task rule
# --------------------------------------------------------------------------------------


def test_an_update_is_withheld_by_k(tmp_path, brain) -> None:
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    phase = derive_updates(phase_input(brain, directory))
    row = by_key(phase.updates)["candidate_window"]

    assert not row.applied
    assert "floor k: 2 admissible pair(s)" in row.withheld_reason
    assert f"{REQUIRED_PAIRS_TIGHTEN} required to tighten" in row.withheld_reason
    assert row.evidence.pairs == 2
    assert load_weights(brain.node_weights("hippocampus"))["candidate_window"] == 20
    assert phase.files == ()


def test_an_update_is_withheld_by_the_two_task_rule(tmp_path, brain) -> None:
    """Three pairs, one task: the arm project memory exists to satisfy (decision 22)."""
    directory = run_of(
        tmp_path,
        brain,
        [
            hippocampus_pair(tick=1, matched=True),
            hippocampus_pair(tick=2, matched=True),
            hippocampus_pair(tick=3, matched=False),
        ],
    )
    phase = derive_updates(phase_input(brain, directory))
    row = by_key(phase.updates)["candidate_window"]

    assert not row.applied
    assert "two-task rule" in row.withheld_reason
    assert row.evidence.tasks == [CURRENT]
    assert load_weights(brain.node_weights("hippocampus"))["candidate_window"] == 20


# --------------------------------------------------------------------------------------
# Arm 4 — the loosening arm, both halves
# --------------------------------------------------------------------------------------


def test_a_loosening_step_needs_six_pairs_not_three(tmp_path, brain) -> None:
    """Every pair matched, so the step loosens — and three pairs are no longer enough."""
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=True)],
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")

    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]
    assert row.direction == "loosen"
    assert not row.applied
    assert row.evidence.required_pairs == REQUIRED_PAIRS_LOOSEN
    assert "3 admissible pair(s) in the window, 6 required to loosen" in row.withheld_reason


def _six_matched_hippocampus(tmp_path, brain, *, earlier_terminal: str):
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=tick, matched=True) for tick in (1, 2, 3)],
    )
    for index in range(3):
        memory_line(
            brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref=f"r-{index}"
        )
    checkpoint = brain.task(EARLIER).checkpoint
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": config.CHECKPOINT_SCHEMA_VERSION,
                "state": {"task_id": EARLIER, "tick": 3, "terminal": earlier_terminal},
                "seed_hashes": {},
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return directory


def test_a_non_detector_loosening_step_applies_when_every_task_ended_done(
    tmp_path, brain
) -> None:
    directory = _six_matched_hippocampus(tmp_path, brain, earlier_terminal="done")
    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]

    assert row.applied and row.direction == "loosen"
    assert (row.from_value, row.to_value) == (20, 21)
    assert row.evidence.every_task_done is True
    assert row.evidence.pairs == REQUIRED_PAIRS_LOOSEN


def test_a_non_detector_loosening_step_is_withheld_when_a_task_did_not_end_done(
    tmp_path, brain
) -> None:
    """S-16's arm: the terminal is the run-level analogue of a confirmation."""
    directory = _six_matched_hippocampus(tmp_path, brain, earlier_terminal="stuck")
    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]

    assert not row.applied
    assert row.evidence.every_task_done is False
    assert "a non-detector key loosens only when every task" in row.withheld_reason
    assert "task-earlier=stuck" in row.withheld_reason
    assert load_weights(brain.node_weights("hippocampus"))["candidate_window"] == 20


def _six_matched_monitor(tmp_path, brain, *, fired: TrapDetector | None):
    directory = run_of(
        tmp_path, brain, [monitor_pair(tick=tick, matched=True) for tick in (1, 2, 3)]
    )
    for tick in (1, 2, 3):
        monitor_journal(directory / "state", task=CURRENT, tick=tick, fired=fired)
    for index in range(3):
        memory_line(
            brain,
            node=NodeName.ANTERIOR_CINGULATE,
            signal="monitor_next_verdict",
            ref=f"m-{index}",
        )
    monitor_journal(brain.task(EARLIER).state_dir, task=EARLIER, tick=1, fired=None)
    return directory


def test_a_detector_loosening_step_is_withheld_by_a_confirmation(tmp_path, brain) -> None:
    """Ruling 16 on the learner: a detector still firing is not one to relax."""
    directory = _six_matched_monitor(tmp_path, brain, fired=TrapDetector.DISLODGING)
    rows = by_key(derive_updates(phase_input(brain, directory)).updates)

    rut = rows["rut_ticks"]
    assert not rut.applied and rut.direction == "loosen"
    assert rut.evidence.confirmations == 3
    assert "3 confirmation(s) of dislodging in the window, zero required" in rut.withheld_reason
    assert load_weights(brain.node_weights("anterior_cingulate"))["rut_ticks"] == 2

    forming = rows["forming_ticks"]
    assert forming.applied and forming.evidence.confirmations == 0
    assert (forming.from_value, forming.to_value) == (6, 5)


def test_a_detector_loosening_step_that_would_breach_the_floor_is_withheld(
    tmp_path, brain
) -> None:
    """Arm three: `rut_ticks` is seeded at the floor, so it can only ever tighten."""
    directory = _six_matched_monitor(tmp_path, brain, fired=None)
    rows = by_key(derive_updates(phase_input(brain, directory)).updates)

    rut = rows["rut_ticks"]
    assert not rut.applied and rut.evidence.confirmations == 0
    assert rut.evidence.floor_minimum == PERSISTENCE_FLOOR_MINIMUM
    assert "persistence floor: rut_ticks would fall to 1" in rut.withheld_reason
    assert load_weights(brain.node_weights("anterior_cingulate"))["rut_ticks"] == 2


def test_a_loosening_step_never_reads_an_unreadable_run_as_favourable(tmp_path, brain) -> None:
    """No journal for a window task means the confirmations cannot be counted, not that they are 0."""
    directory = _six_matched_monitor(tmp_path, brain, fired=None)
    for path in brain.task(EARLIER).state_dir.iterdir():
        path.unlink()

    row = by_key(derive_updates(phase_input(brain, directory)).updates)["forming_ticks"]
    assert not row.applied
    assert "no readable per-tick journal for task-earlier" in row.withheld_reason


# --------------------------------------------------------------------------------------
# Arm 5 — a key the file does not carry
# --------------------------------------------------------------------------------------


def test_a_key_absent_from_the_weights_file_is_refused_rather_than_inserted(
    tmp_path, brain
) -> None:
    path = brain.node_weights("hippocampus")
    drop_weight_key(brain, node="hippocampus", key="semantic_window")

    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")
    rows = by_key(derive_updates(phase_input(brain, directory)).updates)

    absent = rows["semantic_window"]
    assert not absent.applied
    assert absent.from_value is None and absent.to_value is None
    assert "absent key: 'semantic_window' is not in weights.yaml" in absent.withheld_reason
    assert "semantic_window" not in load_weights(path)
    assert rows["candidate_window"].applied


# --------------------------------------------------------------------------------------
# The window's own bookkeeping
# --------------------------------------------------------------------------------------


def test_a_pair_already_consumed_for_a_key_leaves_that_key_s_window(tmp_path, brain) -> None:
    """Consumption is per `(node, key)`: one pair funds at most one update per key (S-17)."""
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    memory_line(
        brain,
        node=NodeName.HIPPOCAMPUS,
        signal="hippocampus_citation",
        ref="r-1",
        consumed={"candidate_window": "sleep-earlier:hippocampus/candidate_window"},
    )
    rows = by_key(derive_updates(phase_input(brain, directory)).updates)

    assert rows["candidate_window"].evidence.pairs == 2
    assert not rows["candidate_window"].applied
    assert rows["semantic_window"].evidence.pairs == 3
    assert rows["semantic_window"].applied


def test_one_run_slept_twice_does_not_clear_the_floor_on_its_own_pairs(tmp_path, brain) -> None:
    """De-duplication by `ref`: a second reading of one pair is not a second pair."""
    pairs = [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)]
    directory = run_of(tmp_path, brain, pairs)
    for record, _ in pairs:
        memory_line(
            brain,
            node=NodeName.HIPPOCAMPUS,
            signal="hippocampus_citation",
            ref=record.prediction_key(),
            task=CURRENT,
        )
    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]

    assert row.evidence.pairs == 2
    assert not row.applied


def test_a_second_task_in_the_trace_files_is_not_the_windows_second_task(tmp_path, brain) -> None:
    """Decision 22: the cross-task evidence is project memory's, never another task's traces.

    A live brain root's `brain/nodes/*/trace.jsonl` accumulates across tasks, so this is the
    shortcut that would otherwise clear the two-task arm without project memory existing at all.
    """
    directory = run_of(
        tmp_path,
        brain,
        [
            hippocampus_pair(tick=1, matched=True),
            hippocampus_pair(tick=2, matched=False),
            hippocampus_pair(tick=3, matched=True, task=EARLIER),
        ],
    )
    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]

    assert row.evidence.tasks == [CURRENT]
    assert row.evidence.pairs == 2
    assert not row.applied
    assert "floor k: 2 admissible pair(s)" in row.withheld_reason


def test_evidence_spanning_one_named_project_is_withheld_from_the_node_folder(
    tmp_path, brain
) -> None:
    """S-2's split: `brain/nodes/` takes `_root` or >= 2-named-project evidence."""
    directory = write_run(
        tmp_path / "run",
        brain=brain,
        records=flatten(
            [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)]
        ),
        task=CURRENT,
        tick=4,
        project="alpha",
    )
    memory_line(
        brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1", slug="alpha"
    )
    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]

    assert not row.applied
    assert row.evidence.projects == ["alpha"]
    assert "cross-project rule: the evidence spans 1 named project(s) (alpha)" in row.withheld_reason

    memory_line(
        brain,
        node=NodeName.HIPPOCAMPUS,
        signal="hippocampus_citation",
        ref="r-2",
        slug="beta",
        task="task-beta",
    )
    second = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]
    assert second.evidence.projects == ["alpha", "beta"]
    assert second.applied


def test_consumption_credits_only_applied_updates(tmp_path, brain) -> None:
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")
    updates = derive_updates(phase_input(brain, directory)).updates

    consumed = consumption_map(updates, SLEEP_ID)
    assert consumed["r-1"] == {
        "candidate_window": f"{SLEEP_ID}:hippocampus/candidate_window",
        "semantic_window": f"{SLEEP_ID}:hippocampus/semantic_window",
        "semantic_min_overlap": f"{SLEEP_ID}:hippocampus/semantic_min_overlap",
    }
    assert consumption_map([row for row in updates if not row.applied], SLEEP_ID) == {}


def test_a_key_with_no_evidence_produces_no_record(tmp_path, brain) -> None:
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    updates = derive_updates(phase_input(brain, directory)).updates
    assert {row.key for row in updates} == {
        "candidate_window",
        "semantic_window",
        "semantic_min_overlap",
    }
    assert all(str(row.node) == "hippocampus" for row in updates)


# --------------------------------------------------------------------------------------
# `was_seeded`, and `brain/seeds.yaml` before order W4 lands
# --------------------------------------------------------------------------------------


def test_no_seeds_file_means_no_key_is_seeded_and_none_is_created(brain) -> None:
    assert not brain.seeds.exists()
    assert seeded_keys(brain) == frozenset()
    assert not brain.seeds.exists()


def test_a_seeds_file_marks_its_keys_in_either_spelling(brain) -> None:
    brain.seeds.write_text(
        "rule_over_firing:\n  node: anterior_cingulate\n  key: rut_ticks\n  value: 2\n",
        encoding="utf-8",
    )
    assert seeded_keys(brain) == {("anterior_cingulate", "rut_ticks")}

    brain.seeds.write_text("hippocampus:\n  candidate_window: 20\n", encoding="utf-8")
    assert seeded_keys(brain) == {("hippocampus", "candidate_window")}


def test_an_applied_update_on_a_seeded_key_records_was_seeded(tmp_path, brain) -> None:
    """`DIGEST:110`'s weakening clause has a subject the moment the map names the key."""
    brain.seeds.write_text(
        "feedback_retrieval:\n  node: hippocampus\n  key: candidate_window\n  value: 20\n",
        encoding="utf-8",
    )
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")
    rows = by_key(derive_updates(phase_input(brain, directory)).updates)

    assert rows["candidate_window"].applied and rows["candidate_window"].was_seeded is True
    assert rows["semantic_window"].was_seeded is False


# --------------------------------------------------------------------------------------
# Row L2, clause 3 — the seed hash every applied update carries
# --------------------------------------------------------------------------------------


def test_every_applied_update_carries_the_seed_hash_it_verified(tmp_path, brain) -> None:
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")

    outcome_ = run_sleep(brain, source=directory, report_dir=tmp_path / "reports")
    applied = outcome_.report.weights.applied()

    assert applied
    for row in applied:
        assert row.seed_hash
        assert row.seed_hash == outcome_.report.source.seed_hashes[f"nodes/{row.node}/weights.yaml"]


def test_a_moved_seed_hash_produces_no_applied_update_at_all(tmp_path, brain) -> None:
    """Decision 17: the run is refused **as evidence**, before one update is derived.

    Carries DoD row L2 and row L2 clause 3 together: `SeedMoved` names the moved
    `weights.yaml`, and no update is applied. Absorbs
    `tests/sleep/test_verb.py::test_a_moved_seed_hash_refuses_the_run_as_evidence_naming_the_file`
    (row S10), whose only claims — `SeedMoved` raised, the file named in the message — are
    the two assertions below.
    """
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")
    path = brain.node_weights("hippocampus")
    path.write_text(path.read_text(encoding="utf-8") + "\n# moved\n", encoding="utf-8")

    with pytest.raises(SeedMoved) as raised:
        run_sleep(brain, source=directory, report_dir=tmp_path / "reports")
    assert "nodes/hippocampus/weights.yaml" in str(raised.value)
    assert not (tmp_path / "reports").exists()
    assert load_weights(path)["candidate_window"] == 20


def test_an_unverified_seed_withholds_the_update(tmp_path, brain) -> None:
    directory = write_run(
        tmp_path / "run",
        brain=brain,
        records=flatten(
            [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)]
        ),
        task=CURRENT,
        tick=4,
        seeds={},
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")
    row = by_key(derive_updates(phase_input(brain, directory)).updates)["candidate_window"]

    assert not row.applied and row.seed_hash == ""
    assert "unverified seed" in row.withheld_reason


# --------------------------------------------------------------------------------------
# The floor after a sequence, and the `## Weights` identity
# --------------------------------------------------------------------------------------


class AppliedSequence(NamedTuple):
    """One drive of the sequence: the updates it produced, and the gate file before it ran."""

    updates: list
    gate_before: str


@pytest.fixture()
def applied_sequence(tmp_path, brain) -> AppliedSequence:
    """Every applied arm this module can drive, run in sequence against one brain root.

    Function-scoped, and shared by the four tests below: they assert four disjoint
    post-conditions on one end state, so four names read off one sequence rather than four
    sequences. `gate_before` is captured here because the gate test can no longer read the file
    for itself before the sequence has run.
    """
    gate_before = brain.node_weights("basal_ganglia").read_text(encoding="utf-8")
    applied = []
    hippocampus = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
        name="run-hippocampus",
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")
    applied.extend(derive_updates(phase_input(brain, hippocampus)).updates)

    monitor = _six_matched_monitor(tmp_path, brain, fired=None)
    applied.extend(derive_updates(phase_input(brain, monitor)).updates)
    return AppliedSequence(updates=applied, gate_before=gate_before)


def test_the_persistence_floor_holds_after_a_sequence_of_applied_updates(
    applied_sequence: AppliedSequence, brain
) -> None:
    """Row L4's third arm, asserted here and re-run as `tests/state/test_brain_tree.py`."""
    updates = applied_sequence.updates
    assert [row.key for row in updates if row.applied]

    for node in config.NODE_ORDER:
        loaded = load_weights(brain.node_weights(node))
        for key in PERSISTENCE_FLOOR_KEYS:
            if key in loaded:
                assert loaded[key] >= PERSISTENCE_FLOOR_MINIMUM, f"{node}.{key}"


def test_every_node_md_weights_list_still_names_exactly_its_file_s_keys(
    applied_sequence: AppliedSequence, brain
) -> None:
    """No key minted, deleted or moved — the identity read off the prose and off the file."""
    for node in config.NODE_ORDER:
        node_md = (brain.root / "nodes" / node / "NODE.md").read_text(encoding="utf-8")
        assert sorted(declared_weight_keys(node_md)) == sorted(
            load_weights(brain.node_weights(node))
        ), node


def test_no_applied_step_ever_exceeds_its_bound(applied_sequence: AppliedSequence) -> None:
    for row in applied_sequence.updates:
        if not row.applied:
            continue
        if isinstance(row.from_value, int):
            assert abs(row.to_value - row.from_value) == 1
        else:
            assert abs(row.to_value - row.from_value) == pytest.approx(
                abs(row.from_value) * 0.1
            )


def test_the_gate_is_never_a_subject_and_its_file_is_never_touched(
    applied_sequence: AppliedSequence, brain
) -> None:
    path = brain.node_weights("basal_ganglia")
    before = applied_sequence.gate_before
    updates = applied_sequence.updates
    assert "basal_ganglia" not in {str(row.node) for row in updates}
    assert path.read_text(encoding="utf-8") == before
    assert load_weights(path) == {}


# --------------------------------------------------------------------------------------
# `--dry-run`
# --------------------------------------------------------------------------------------


def test_a_dry_run_derives_everything_and_writes_no_file_under_brain(tmp_path, brain) -> None:
    directory = run_of(
        tmp_path,
        brain,
        [hippocampus_pair(tick=1, matched=True), hippocampus_pair(tick=2, matched=False)],
    )
    memory_line(brain, node=NodeName.HIPPOCAMPUS, signal="hippocampus_citation", ref="r-1")
    before = tree_hashes(brain.root)

    phase = derive_updates(phase_input(brain, directory, dry_run=True))

    assert [row.key for row in phase.updates if row.applied]
    assert phase.files == ()
    assert tree_hashes(brain.root) == before
