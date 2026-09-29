"""Row L5: the seeding map, the licensed seed writer, and S-21's collision rule.

`the build specification (not in this mirror)` \xa7 Deliverable 3 (*Seeded priors come in, narrowly*), \xa7 DoD
row L5, \xa7 Directional decisions 5, 11 and 12, \xa7 Named assumptions 11, \xa7 Resolutions A1-7,
S-10, S-15, S-21.

**Two writers, one comparison.** Sleep re-values a key and intake seeds one, and the only thing
keeping them off each other is "the on-disk value still equals the seeding row's value". So the
tests below are written from both ends: the shipped map is checked against the tracked node files
it names, and the collision rule is fired in both directions on a throwaway copy of that tree.

**Nothing here writes into the repo's own `brain/`** (`tests.sleep.seeded_brain`'s rule, and the
repo root holds a paused task besides). Every run copies the tracked seed tree plus the tracked
seeding map into `tmp_path` first; the one thing read out of the checkout is those seed bytes,
because a map asserted against a fixture of its own would prove nothing about the shipped file.

**The `was_seeded` arm is row L5's first half and it is a *tightening* move** — three admissible
pairs across two tasks, one of them unmatched, which is the k = 3 arm. The withheld loosening
seeded move is row N3's separate fixture and order W8's.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from protean import cli, config
from protean.brain.folders import load_weights
from protean.intake import run_intake
from protean.intake.policy_home import ROOT_ENV
from protean.intake.seeds import (
    BadSeedMap,
    SeedRow,
    load_seed_map,
    plan_seeds,
)
from protean.runtime import paths as paths_module
from protean.runtime.paths import BrainPaths
from protean.sleep import weights as sleep_weights
from protean.sleep.evidence import admissible_set, load_archived_run
from protean.sleep.run import PhaseInput, verify_seeds
from protean.state.enums import NodeName
from protean.state.records import HippocampusOutcome, HippocampusPrediction
from protean.state.sleep import ProjectMemoryRecord
from tests.conftest import PREFIXES
from tests.intake.conftest import node_tree_hashes
from tests.sleep import outcome, prediction, write_run

SLEEP_ID = "sleep-20260908-000000Z"
EARLIER = "task-earlier"
CURRENT = "task-fixture"

#: The row row L5 drives: seeded, mapped by `SIGNAL_KEY_MAP`, and moved by a tightening step.
MOVED_NODE = "hippocampus"
MOVED_KEY = "candidate_window"


@pytest.fixture(scope="module")
def shipped(repo_root: Path) -> tuple[SeedRow, ...]:
    """The tracked map itself, read the way `run_intake` reads it — once, and never written."""
    return load_seed_map(repo_root / "brain" / paths_module.SEEDS_FILENAME)


@pytest.fixture()
def seeded_root(tmp_path: Path, repo_root: Path) -> BrainPaths:
    """A throwaway root carrying the tracked node tree, the tracked map, and the manifest."""
    root = tmp_path / "brain"
    shutil.copytree(
        repo_root / "brain" / "nodes", root / "nodes",
        ignore=shutil.ignore_patterns("trace.jsonl"),
    )
    shutil.copy(repo_root / "brain" / paths_module.SEEDS_FILENAME, root / "seeds.yaml")
    (root / "intake").mkdir(parents=True)
    shutil.copy(
        repo_root / "brain" / "intake" / "manifest.yaml", root / "intake" / "manifest.yaml"
    )
    return BrainPaths(root=root)


def node_hashes(brain: BrainPaths) -> list[tuple[str, str]]:
    """The shared per-file walk, over this root's own `nodes/` tree."""
    return node_tree_hashes(brain.root / "nodes")


# --------------------------------------------------------------------------------------
# The shipped map: sparse, hand-authored, and true of the tree it names
# --------------------------------------------------------------------------------------


def test_the_shipped_map_names_only_existing_keys_in_writable_nodes(
    shipped, repo_root: Path
) -> None:
    """Decision 11, said of the seeder twice over: the key is there, and it still holds the value.

    **Both halves are Decision 11 anchors** and both were made by the same loop over the same
    rows, the second re-parsing every weights file the first had already read (audit row W10):
    a key not already present is a refusal rather than an insert, and — because the collision
    rule compares against these numbers — a row whose value has drifted from its node file would
    skip on every run instead of seeding. One walk of the tracked tree proves both.
    """
    assert shipped, "an empty map would pass every assertion below vacuously"
    for row in shipped:
        assert row.node in config.WEIGHTS_WRITABLE_NODES, row.node
        weights = load_weights(config.node_dir(row.node, repo_root / "brain") / "weights.yaml")
        assert row.key in weights, row.weights_key()
        assert weights[row.key] == row.value, row.weights_key()


def test_the_map_is_sparse_and_names_the_gate_nowhere(shipped, repo_root: Path) -> None:
    """It is the provenance for `was_seeded`, not a second copy of the weights tree."""
    covered = sum(
        len(load_weights(config.node_dir(node, repo_root / "brain") / "weights.yaml"))
        for node in config.WEIGHTS_WRITABLE_NODES
    )
    assert len(shipped) < covered, "a map as wide as the tree is not a sparse map"
    assert "basal_ganglia" not in {row.node for row in shipped}


def test_every_row_carries_a_memory_name_and_no_two_rows_name_one_key(shipped) -> None:
    keys = [row.seeded_key() for row in shipped]
    assert len(keys) == len(set(keys)), keys
    for row in shipped:
        assert row.memory and not row.memory.startswith("/"), row.memory


@pytest.mark.parametrize("prefix", PREFIXES, ids=("policy_home", "harness_home"))
def test_the_seeding_map_names_neither_policy_prefix(repo_root: Path, prefix: str) -> None:
    """A logical memory *name* is the provenance — the manifest seed's rule, one file over."""
    text = (repo_root / "brain" / paths_module.SEEDS_FILENAME).read_text(encoding="utf-8")
    assert prefix not in text


def test_no_weights_file_carries_a_seeds_key(repo_root: Path) -> None:
    """Folded S-10: the row is the provenance, so no `seeds:` block enters a weights file."""
    for node in config.NODE_ORDER:
        path = config.node_dir(node, repo_root / "brain") / "weights.yaml"
        assert "seeds" not in load_weights(path), node
        assert "seeds:" not in path.read_text(encoding="utf-8"), node


def test_the_two_readers_of_the_map_agree_over_the_shipped_file(
    shipped, seeded_root: BrainPaths
) -> None:
    """`was_seeded` is *named in the map*: sleep's reader and the seeder must see one set."""
    from protean.intake.seeds import seeded_keys as seeder_keys

    assert seeder_keys(shipped) == sleep_weights.seeded_keys(seeded_root)
    assert (MOVED_NODE, MOVED_KEY) in seeder_keys(shipped)


# --------------------------------------------------------------------------------------
# The loader's refusals
# --------------------------------------------------------------------------------------


def test_a_missing_map_seeds_nothing_and_is_never_created(tmp_path: Path) -> None:
    path = tmp_path / "seeds.yaml"
    assert load_seed_map(path) == ()
    assert not path.exists()


def test_an_empty_map_seeds_nothing(tmp_path: Path) -> None:
    path = tmp_path / "seeds.yaml"
    path.write_text("# nothing here\n", encoding="utf-8")
    assert load_seed_map(path) == ()


def test_a_map_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "seeds.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(BadSeedMap) as raised:
        load_seed_map(path)
    assert "mapping" in str(raised.value)


@pytest.mark.parametrize(
    ("body", "quoted"),
    [
        ("m:\n  - node: hippocampus\n    key: candidate_window\n", "value"),
        ("m:\n  - node: hippocampus\n    value: 20\n", "key"),
        ("m:\n  - node: hippocampus\n    key: candidate_window\n    value: 20\n    why: x\n", "why"),
        ("m:\n  - node: telepathy\n    key: candidate_window\n    value: 20\n", "telepathy"),
        ("m:\n  - node: basal_ganglia\n    key: anything\n    value: 1\n", "basal_ganglia"),
        ("m:\n  - node: hippocampus\n    key: candidate_window\n    value: true\n", "boolean"),
        ("m: 7\n", "int"),
        ("m:\n  - 7\n", "int"),
    ],
    ids=(
        "no_value", "no_key", "extra_field", "unknown_node", "the_gate", "boolean",
        "block_is_scalar", "row_is_scalar",
    ),
)
def test_a_row_this_build_cannot_read_is_a_refused_map(
    tmp_path: Path, body: str, quoted: str
) -> None:
    """Extras-forbidden like every other contract: an unknown field is a refusal, not a drop."""
    path = tmp_path / "seeds.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(BadSeedMap) as raised:
        load_seed_map(path)
    assert quoted in str(raised.value)


def test_both_spellings_of_a_block_load(tmp_path: Path) -> None:
    """One row or a list of them — the same tolerance sleep's reader carries (ledger `D8-9`)."""
    path = tmp_path / "seeds.yaml"
    single = "m:\n  node: hippocampus\n  key: candidate_window\n  value: 20\n"
    listed = "m:\n  - node: hippocampus\n    key: candidate_window\n    value: 20\n"
    path.write_text(single, encoding="utf-8")
    first = load_seed_map(path)
    path.write_text(listed, encoding="utf-8")
    assert load_seed_map(path) == first


def test_a_key_the_node_file_does_not_carry_is_refused_rather_than_inserted(
    seeded_root: BrainPaths,
) -> None:
    """Decision 11 for the seeder, and the refusal fires before anything is written."""
    before = node_hashes(seeded_root)
    rows = (SeedRow(memory="m", node="hippocampus", key="not_a_key", value=1),)
    with pytest.raises(BadSeedMap) as raised:
        plan_seeds(seeded_root, rows)
    assert "not_a_key" in str(raised.value) and "never mints" in str(raised.value)
    assert node_hashes(seeded_root) == before


# --------------------------------------------------------------------------------------
# S-21's collision rule, fired in both directions
# --------------------------------------------------------------------------------------


def test_a_row_whose_value_still_matches_disk_is_applied(shipped, seeded_root) -> None:
    plan = plan_seeds(seeded_root, shipped)
    assert len(plan.applied) == len(shipped) and plan.skipped == ()
    assert plan.commit() == (), "the tree already holds every value, so nothing is rewritten"


def test_a_key_sleep_has_moved_is_skipped_and_printed(shipped, seeded_root) -> None:
    """The rule's whole content: a moved key belongs to sleep, the sole re-writer."""
    path = seeded_root.node_weights(MOVED_NODE)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"{MOVED_KEY}: 20", f"{MOVED_KEY}: 19"
        ),
        encoding="utf-8",
    )
    plan = plan_seeds(seeded_root, shipped)
    skipped = {write.row.weights_key(): write for write in plan.skipped}
    assert set(skipped) == {f"{MOVED_NODE}/{MOVED_KEY}"}
    message = skipped[f"{MOVED_NODE}/{MOVED_KEY}"].message()
    assert "skipped" in message and "19" in message and "20" in message
    assert "never overwrites a learner" in message
    assert plan.commit() == ()
    assert load_weights(path)[MOVED_KEY] == 19, "the learner's value stands"


def test_the_writer_writes_when_the_spelling_differs_but_the_value_does_not(
    seeded_root,
) -> None:
    """The one arm where the re-value moves bytes — and the proof the writer is not inert.

    **Decision 11 / S-21, from both sides of the one rewrite** (audit row W9). The `20 → 20.0`
    setup was written twice to assert two disjoint things about the same commit: that the
    re-value lands (the file names the row's spelling, comments and every other key survive, and
    the plan says `intake: seeded`), and that it lands *narrowly* — the whole mapping the file
    parses to is byte-for-byte the one it carried before, so no other key moved and none was
    minted. One rewrite, one commit, both.
    """
    path = seeded_root.node_weights(MOVED_NODE)
    before = load_weights(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"{MOVED_KEY}: 20", f"{MOVED_KEY}: 20.0"
        ),
        encoding="utf-8",
    )
    rows = (SeedRow(memory="m", node=MOVED_NODE, key=MOVED_KEY, value=20),)
    plan = plan_seeds(seeded_root, rows)
    assert len(plan.applied) == 1 and plan.applied[0].changed
    assert plan.commit() == (path,)
    text = path.read_text(encoding="utf-8")
    assert f"{MOVED_KEY}: 20\n" in text
    assert "# The semantic half" in text, "comments, order and every other key untouched"
    assert plan.applied[0].message().startswith("intake: seeded")
    assert load_weights(path) == before, "no other key moved, and none was minted"


# --------------------------------------------------------------------------------------
# The verb: what it writes under `brain/nodes/`, and what it prints
# --------------------------------------------------------------------------------------


def test_intake_writes_no_key_the_map_does_not_name(
    seeded_root: BrainPaths, source_root: Path
) -> None:
    """Row L5's third clause, asserted over the whole node tree rather than over one file."""
    before = dict(node_hashes(seeded_root))
    outcome_ = run_intake(seeded_root, source_root=source_root, project="demo")
    assert dict(node_hashes(seeded_root)) == before
    assert {write.row.weights_key() for write in outcome_.seeds} == {
        f"{row.node}/{row.key}"
        for row in load_seed_map(seeded_root.seeds)
    }
    assert all(path.parent == seeded_root.semantic for path in outcome_.files)


def test_a_root_with_no_map_seeds_nothing_at_all(
    seeded_root: BrainPaths, source_root: Path
) -> None:
    """Build 2's stance survives on any root that carries no map: the stores and nothing else."""
    seeded_root.seeds.unlink()
    before = dict(node_hashes(seeded_root))
    outcome_ = run_intake(seeded_root, source_root=source_root)
    assert outcome_.seeds == () and outcome_.seed_files == ()
    assert dict(node_hashes(seeded_root)) == before


def test_a_refused_map_costs_the_run_nothing(
    seeded_root: BrainPaths, source_root: Path
) -> None:
    """Resolved before the first store is replaced, so a bad map writes no file at all."""
    seeded_root.seeds.write_text(
        "m:\n  - node: hippocampus\n    key: not_a_key\n    value: 1\n", encoding="utf-8"
    )
    with pytest.raises(BadSeedMap):
        run_intake(seeded_root, source_root=source_root)
    assert not seeded_root.semantic.exists(), "a refused map leaves the stores untouched"


def test_the_verb_prints_the_seeding_decision_for_every_row(
    seeded_root: BrainPaths, source_root: Path, monkeypatch, capsys
) -> None:
    path = seeded_root.node_weights(MOVED_NODE)
    path.write_text(
        path.read_text(encoding="utf-8").replace(f"{MOVED_KEY}: 20", f"{MOVED_KEY}: 19"),
        encoding="utf-8",
    )
    monkeypatch.setenv(ROOT_ENV, str(source_root))
    code = cli.main(["--brain", str(seeded_root.root), "intake"])
    assert code == config.EXIT_DONE
    printed = capsys.readouterr().out
    rows = load_seed_map(seeded_root.seeds)
    for row in rows:
        assert f"{row.node}/{row.key}" in printed
    assert f"intake: skipped {MOVED_NODE}/{MOVED_KEY}" in printed
    written = sorted(seeded_root.semantic.glob("*.jsonl"))
    assert printed.count("wrote ") == len(written), "one `wrote` line per file written"


# --------------------------------------------------------------------------------------
# Row L5's first arm: sleep moves a seeded key and the record says so
# --------------------------------------------------------------------------------------


def _hippocampus_pair(*, tick: int, matched: bool, task: str = CURRENT):
    record = prediction(
        node=NodeName.HIPPOCAMPUS,
        payload=HippocampusPrediction(episode_ids=[f"e-{tick}"]),
        task=task,
        tick=tick,
    )
    graded = outcome(
        record,
        HippocampusOutcome(
            cited_episode_ids=[f"e-{tick}"] if matched else [], matched=matched
        ),
    )
    return record, graded


def _memory_line(brain: BrainPaths, *, ref: str) -> None:
    """The window's second task, at pair granularity, in order W5's own P4 shape."""
    record = ProjectMemoryRecord(
        project=paths_module.ROOT_PROJECT_SLUG,
        node=NodeName.HIPPOCAMPUS,
        sleep_id="sleep-20260907-000000Z",
        task=EARLIER,
        tick=1,
        ref=ref,
        signal="hippocampus_citation",
        matched=True,
        admissible=True,
    )
    path = brain.project_learning(paths_module.ROOT_PROJECT_SLUG, str(NodeName.HIPPOCAMPUS))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.model_dump(mode="json"), separators=(",", ":")) + "\n")


def test_sleep_moves_a_key_the_shipped_map_names_and_records_was_seeded(
    tmp_path: Path, seeded_root: BrainPaths
) -> None:
    """Row L5's first half: the weakening clause has a subject, and it is a tightening move."""
    pairs = [
        _hippocampus_pair(tick=1, matched=True),
        _hippocampus_pair(tick=2, matched=False),
    ]
    directory = write_run(
        tmp_path / "run",
        brain=seeded_root,
        records=[row for pair in pairs for row in pair],
        task=CURRENT,
        tick=4,
        terminal="done",
    )
    _memory_line(seeded_root, ref="r-1")
    records = load_archived_run(directory)
    result = sleep_weights.derive_updates(
        PhaseInput(
            brain=seeded_root,
            records=records,
            pairs=admissible_set(records),
            seed_hashes=verify_seeds(seeded_root, records),
            sleep_id=SLEEP_ID,
            dry_run=False,
        )
    )
    moved = {row.key: row for row in result.updates}[MOVED_KEY]
    assert moved.applied and moved.was_seeded is True
    assert moved.direction == "tighten" and moved.to_value < moved.from_value
    assert seeded_root.node_weights(MOVED_NODE) in result.files
    assert load_weights(seeded_root.node_weights(MOVED_NODE))[MOVED_KEY] == moved.to_value


def test_the_seeded_key_sleep_moved_is_then_skipped_by_intake(
    tmp_path: Path, seeded_root: BrainPaths, source_root: Path
) -> None:
    """Row L5 end to end: a seeder cannot overwrite a learner, on the shipped map's own key."""
    before = load_weights(seeded_root.node_weights(MOVED_NODE))[MOVED_KEY]
    first = run_intake(seeded_root, source_root=source_root)
    assert [w.applied for w in first.seeds if w.row.key == MOVED_KEY] == [True]

    pairs = [
        _hippocampus_pair(tick=1, matched=True),
        _hippocampus_pair(tick=2, matched=False),
    ]
    directory = write_run(
        tmp_path / "run",
        brain=seeded_root,
        records=[row for pair in pairs for row in pair],
        task=CURRENT,
        tick=4,
        terminal="done",
    )
    _memory_line(seeded_root, ref="r-1")
    records = load_archived_run(directory)
    sleep_weights.derive_updates(
        PhaseInput(
            brain=seeded_root,
            records=records,
            pairs=admissible_set(records),
            seed_hashes=verify_seeds(seeded_root, records),
            sleep_id=SLEEP_ID,
            dry_run=False,
        )
    )
    learned = load_weights(seeded_root.node_weights(MOVED_NODE))[MOVED_KEY]
    assert learned != before

    second = run_intake(seeded_root, source_root=source_root)
    skipped = [w for w in second.seeds if w.row.key == MOVED_KEY]
    assert [w.applied for w in skipped] == [False]
    assert load_weights(seeded_root.node_weights(MOVED_NODE))[MOVED_KEY] == learned
    assert second.seed_files == ()


def test_the_map_survives_a_yaml_round_trip_of_its_own_shape(repo_root: Path) -> None:
    """A guard on the hand-authored file: every block is a list of rows, and nothing else."""
    document = yaml.safe_load(
        (repo_root / "brain" / paths_module.SEEDS_FILENAME).read_text(encoding="utf-8")
    )
    assert isinstance(document, dict) and document
    for memory, block in document.items():
        assert isinstance(memory, str) and isinstance(block, list), memory
        for row in block:
            assert set(row) == {"node", "key", "value"}, memory
